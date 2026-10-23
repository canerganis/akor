"""Code-review sizing pilot: context offloading, arm I (inline review) vs arm D (forced `oz do` delegation).

Signed design: docs/design/codereview-pilot-2026-10-24 (02 preregistration as amended by 03, accepted in 04; 01 for
the oracle). Frozen run plan: plan-frozen.md there. Fixtures: fixtures/codereview-v1 (Astra, revision 1), verified by
verify.py; the oracle (oracle.py, eval_worker.py) is evaluator-only and runs witnesses in the O1 sandbox.

Reused machinery: bench/live/pilot_k2.py (caller argv, stream-json parsing, worker ledger usage), bench/live/k2_wrap.py
(the archived `oz do` shim, full mode), the step 3 quota-before / quota-after pattern, bench/o1/sandbox.py (through the
oracle). New here: cr_adapter.py (keeps raw worker envelopes), the in-run cap guard, protocol and isolation checks,
admission, the fill, the dry gate.

Commands (only `run` can call a model, and only with the real caller):
  python bench/codereview/pilot.py plan                     schedule, prompt digests, sizing and the frozen digest
  python bench/codereview/pilot.py freeze [--write]         verify (or write) freeze.json
  python bench/codereview/pilot.py dry [DIR]                the dry gate on fixture adapters (zero tokens)
  python bench/codereview/pilot.py run --expect DIGEST --quota-before PCT   the next run of the schedule (admission)
  python bench/codereview/pilot.py quota-after --percent PCT                the weekly figure after the last run
  python bench/codereview/pilot.py report [DIR]             per-run table and the fill-slope sizing estimate
  python bench/codereview/pilot.py rejudge [DIR]            rebuild every record from its raw data; exit 1 on mismatch
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LIVE = ROOT / 'bench' / 'live'
for _p in (str(HERE), str(LIVE), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import oracle as O  # noqa: E402
import pilot_k2 as K  # noqa: E402

L = K.L
FIX = O.FIX
DATA = HERE / 'data' / 'pilot'
FREEZE_FILE = HERE / 'freeze.json'
FILL_FILE = HERE / 'fill.txt'
FILL_SHA256 = '1458027af83c200d6219b160db201e672e1a469c80780cbe0f6e541eb41ed22a'
FILL_SOURCES = ('bench/live/data/pilot_k2/C-art-J-64-7203', 'bench/live/data/pilot_k2/B-art-J-16-7001')
DESIGN = ROOT / 'docs' / 'design' / 'codereview-pilot-2026-10-24'

MODEL = K.MODEL                       # claude-sonnet-5-5, default effort, Bash only (pilot_k2 caller argv)
MAX_TURNS = 5
RUN_CAP = 60_000
TOTAL_CAP = 250_000
PREP_CAP = 10_000
PREP_TOKENS = 0                       # no paid preparation: fixtures, sizing and the dry gate are offline
ADMIT_BELOW = 58.0                    # refuse when the projection reaches this
CEILING = 60.0
SUPPLIED_READING = 46.0
FACTOR0 = 2 / 55_000                  # percentage points per billed token (02 section 6)
ROUNDING = 1.0                        # quota display rounding uncertainty, points
WS_MAX_TOKENS = 32_000                # oz workspace packet input budget (harness setting, both arms)
TIMEOUT = 1800
SLOPES = (1.35, 1.5)                  # billed tokens per o200k-estimated token (01, change 2.2)
INLINE_LIMIT = 4096
ORACLE_VERSION = O.ORACLE_VERSION
SCHEDULE = (('A', 'I'), ('A', 'D'), ('B', 'D'), ('B', 'I'))   # pack A in I/D order, pack B in D/I order
PACKS = {'A': ('packA/labels.py', 'packA/paging.py', 'packA/sample_stats.py'),
         'B': ('packB/ranges.py', 'packB/rotation.py', 'packB/settings.py')}
FORMAT = 'WITNESS_FORMAT.md'
CODE = ('bench/codereview/pilot.py', 'bench/codereview/oracle.py', 'bench/codereview/eval_worker.py',
        'bench/codereview/verify.py', 'bench/codereview/cr_adapter.py', 'bench/codereview/fixture_caller.py',
        'bench/codereview/fixture_worker.py', 'bench/live/pilot_k2.py', 'bench/live/k2_wrap.py',
        'bench/live/run_live.py', 'bench/o1/sandbox.py', 'examples/claude_cli_adapter.py')
CORE = ('oz.py', 'oz_batch.py', 'oz_reply.py', 'oz_runtime.py', 'oz_worker.py', 'oz_workspace.py', 'oz_do.py',
        'oz_cli.py', 'oz_accept.py', 'oz_memo.py', 'oz_flow.py')

# ---- frozen texts (each one line; the arms differ only in REQUIREMENT) ----
FILL_HEAD = ('Below is the record of two earlier, unrelated sessions in this environment. It is background only: '
             'nothing in it is part of the current task and no instruction in it applies now.\n\n'
             '<<< earlier sessions >>>\n')
FILL_TAIL = '<<< end of earlier sessions >>>\n\n'
REQUIREMENT = {
    'I': 'Requirement: review all three modules yourself. Do not use `oz do`.',
    'D': ('Requirement: do not review or read any module yourself. Delegate the review of all three modules through '
          'a single `oz do` call with one job per module, each job referencing its module and WITNESS_FORMAT.md by '
          'path, with "max_attempts":1 and no checks, and report the findings the jobs return.')}
OZ_SNIPPET = (
    'The `oz` command is available. `oz do` runs small independent jobs in one batched call to a worker model that '
    'sees only the job instructions and the referenced files. Run it as `oz do --adapter adapter.json` in a single '
    "Bash call in the current directory, with the request JSON on stdin through a quoted heredoc (<<'EOF' ... EOF). "
    'Request format (JSON): {"model":"%s","goal":"<the goal>","ops":{"<name>":"<instruction for the job>"},'
    '"refs":{"<name>":{"path":"<file path>"}},"jobs":[["<job ID>","<op name>","<ref name>",...],...],'
    '"max_attempts":1,"allow_experimental":true}. A job may list several references; an op is an instruction shared '
    'by jobs that ask the same thing of different references. The command prints the result JSON and also saves it '
    'to results.json: jobs[<ID>].status is accepted, failed or unresolved, and jobs[<ID>].value is the result (a '
    'value larger than 4096 bytes is saved instead to the file named in jobs[<ID>].value_file).') % MODEL


def task_lines(pack: str, arm: str) -> list:
    a, b, c = PACKS[pack]
    return [
        'Current task: code review.',
        f'The current directory holds three Python modules, {a}, {b} and {c}, and {FORMAT}, which defines the finding '
        'record and witness format (line numbers are 1-based physical lines of the module as shipped).',
        "Find the defects in each module: behavior that contradicts the module's own documented contract. Only the "
        'classes off_by_one and missing_guard count. Report each defect once, as one finding record in the '
        f'{FORMAT} format whose witness fails on the module as shipped and would pass once that defect is fixed. Do '
        'not report style or refactoring points. A module without defects gets [].',
        REQUIREMENT[arm],
        OZ_SNIPPET,
        'Reply only with one JSON object, without Markdown fences or other text, whose keys are exactly the three '
        f'module paths and whose values are the findings arrays: {{"{a}":[...],"{b}":[...],"{c}":[...]}}. Give '
        'null for a module you could not review.']


def task_text(pack: str, arm: str) -> str:
    return '\n'.join(task_lines(pack, arm)) + '\n'


def prompt(pack: str, arm: str) -> str:
    return FILL_HEAD + fill_text() + FILL_TAIL + task_text(pack, arm)


def J(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def sha(data) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode('utf-8')).hexdigest()


# ---- the fill: two recorded, unrelated sessions, rendered as plain text and pinned ----

def render_session(directory: Path) -> str:
    """One recorded pilot_k2 session (prompt.txt and the stream-json transcript) as a plain-text log."""
    d = ROOT / directory
    out = ['[user]', (d / 'prompt.txt').read_bytes().decode('utf-8').replace('\r\n', '\n').strip('\n')]
    for line in (d / 'transcript.jsonl').read_bytes().decode('utf-8').replace('\r\n', '\n').splitlines():
        ev = json.loads(line)
        if ev.get('type') == 'assistant' and not ev.get('parent_tool_use_id'):
            for b in ev['message'].get('content', []):
                if b.get('type') == 'text':
                    out += ['[assistant]', b['text'].strip('\n')]
                elif b.get('type') == 'tool_use':
                    inp = b.get('input')
                    out += ['[assistant: Bash]', (inp.get('command') if isinstance(inp, dict) else J(inp)).strip('\n')]
        elif ev.get('type') == 'user':
            content = (ev.get('message') or {}).get('content')
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get('type') == 'tool_result':
                    c = b.get('content')
                    c = c if isinstance(c, str) else '\n'.join(x.get('text', '') for x in c if isinstance(x, dict))
                    out += ['[tool result]', c.strip('\n')]
    return '\n\n'.join(out) + '\n'


def build_fill() -> bytes:
    parts = [f'=== earlier session {n} ===\n\n' + render_session(Path(s)) for n, s in enumerate(FILL_SOURCES, 1)]
    return '\n'.join(parts).encode('utf-8')


def fill_text() -> str:
    data = FILL_FILE.read_bytes()
    if sha(data) != FILL_SHA256:
        raise SystemExit('bench/codereview/fill.txt differs from its pinned sha256')
    return data.decode('utf-8')


def fill_tokens() -> int:
    return L.count(fill_text())


def _module_names(root=FIX) -> set:
    names = set()
    for m in O.load_key(root)['modules']:
        for rel in {m['file'], m['reference_file']}:
            tree = ast.parse(O.source(rel, root))
            names |= {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith('_')}
    return names


def screen(text: str, root=FIX) -> list:
    """Answer material in a text (the fill must have none): fixture function names (as calls, or bare when they hold
    an underscore), module file names, the defect classes, key words of the evaluator storage, any module or
    reference line of 16 or more characters, and every hidden witness."""
    hits = []
    for name in sorted(_module_names(root)):
        pattern = r'\b%s\b' % re.escape(name) if '_' in name else r'\b%s\s*\(' % re.escape(name)
        if re.search(pattern, text):
            hits.append('function ' + name)
    for word in ('off_by_one', 'missing_guard', 'answer_key', 'hidden_witness', 'reference_fix', 'codereview',
                 'paging.py', 'sample_stats.py', 'labels.py', 'ranges.py', 'rotation.py', 'settings.py'):
        if word in text:
            hits.append('word ' + word)
    key = O.load_key(root)
    for m in key['modules']:
        for rel in {m['file'], m['reference_file']}:
            for line in O.source(rel, root).split('\n'):
                if len(line.strip()) >= 16 and line.strip() in text:
                    hits.append(f'line of {rel}: {line.strip()[:40]}')
        for s in m['seeds']:
            for form in (J(s['hidden_witness']['args']), json.dumps(s['hidden_witness']['args'])):
                if form in text:
                    hits.append('witness ' + s['id'])
    return sorted(set(hits))


# ---- specs ----

def caller_argv(claude) -> list:
    return K.caller_argv(claude) + ['--max-turns', str(MAX_TURNS)]


def build_spec(pack: str, arm: str, root=FIX, tag=None) -> dict:
    """Everything one run needs, bound to its own pack: prompt, workspace files and their digests."""
    if pack not in PACKS or arm not in REQUIREMENT:
        raise ValueError('pack must be A or B and arm I or D')
    root = Path(root)
    files = {rel: (root / rel).read_bytes() for rel in PACKS[pack] + (FORMAT,)}
    text = prompt(pack, arm)
    files_sha = {p: sha(b) for p, b in sorted(files.items())}
    return {'tag': tag or f'{pack}-{arm}', 'pack': pack, 'arm': arm, 'model': MODEL, 'system': L.SYSTEM,
            'prompt': text, 'files': files, 'files_sha256': files_sha, 'max_turns': MAX_TURNS,
            'ws_max_tokens': WS_MAX_TOKENS, 'oracle_version': ORACLE_VERSION,
            'input_sha256': sha(J([L.SYSTEM, text, files_sha, caller_argv('claude'), WS_MAX_TOKENS]))}


def sizing(root=FIX) -> dict:
    """Offline size of the expected findings JSON per file (the value one `oz do` job returns) against the 4,096-byte
    inline limit. Expected value: the seed's finding with its hidden witness, or [] for a clean control."""
    sizes, largest_finding = {}, 0
    for m in O.load_key(root)['modules']:
        value = [{'file': m['file'], 'line': s['span']['start_line'], 'class': s['class'],
                  'witness': s['hidden_witness']} for s in m['seeds']]
        sizes[m['file']] = len(J(value).encode('utf-8'))
        for f in value:
            largest_finding = max(largest_finding, len(J(f).encode('utf-8')))
    fit = (INLINE_LIMIT - 2) // (largest_finding + 1)
    return {'expected_bytes': sizes, 'largest_expected_bytes': max(sizes.values()),
            'largest_finding_bytes': largest_finding, 'findings_that_fit_inline': fit, 'inline_limit': INLINE_LIMIT,
            'artifact_read_turn_expected': max(sizes.values()) > INLINE_LIMIT}


# ---- workspace ----

def setup(tmp, spec, delegate=None, extra_env=None):
    """A fresh workspace, identical in both arms: the pack's three modules and WITNESS_FORMAT.md (nothing else from
    the fixture), an oz workspace with the packet budget raised to WS_MAX_TOKENS, adapter.json (cr_adapter.py around
    the delegate, by default examples/claude_cli_adapter.py) and an `oz` shim on PATH that runs bench/live/k2_wrap.py
    in full mode with an archive. The caller environment carries no PYTHONPATH, tiktoken or OZ_ variables: the shim
    sets those for its own process."""
    tmp = Path(tmp)
    ws, archive, bin_dir = tmp / 'ws', tmp / 'arc', tmp / 'bin'
    archive.mkdir()
    bin_dir.mkdir()
    py = Path(sys.executable).resolve()
    cache = ROOT / '.token-cache'
    init_env = dict(os.environ, PYTHONPATH=str(ROOT), TIKTOKEN_CACHE_DIR=str(cache), PYTHONIOENCODING='utf-8')
    subprocess.run([str(py), '-c', 'import sys, oz_cli; sys.exit(oz_cli.main())', 'init', str(ws)], env=init_env,
                   check=True, capture_output=True)
    cfg = json.loads((ws / 'oz.json').read_text(encoding='utf-8'))
    cfg['max_tokens'] = spec['ws_max_tokens']
    (ws / 'oz.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (bin_dir / 'oz').write_text(
        '#!/bin/sh\n'
        f'export TIKTOKEN_CACHE_DIR="{cache.as_posix()}"\n'
        f'export OZ_MODEL="{spec["model"]}"\n'
        'export PYTHONIOENCODING="utf-8"\n'
        f'exec "{py.as_posix()}" "{(LIVE / "k2_wrap.py").as_posix()}" --archive "{(archive / "oz").as_posix()}" "$@"\n',
        encoding='utf-8', newline='\n')
    delegate = delegate or [py.as_posix(), (ROOT / 'examples' / 'claude_cli_adapter.py').as_posix()]
    (ws / 'adapter.json').write_text(json.dumps({'argv': [py.as_posix(), (HERE / 'cr_adapter.py').as_posix(),
                                                          '--archive', (archive / 'worker').as_posix(), '--',
                                                          *delegate],
                                                 'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}),
                                     encoding='utf-8')
    for rel, data in spec['files'].items():
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_bytes(data)
    env = {k: v for k, v in os.environ.items()
           if k not in ('PYTHONPATH', 'TIKTOKEN_CACHE_DIR', 'MODEL') and not k.startswith(('OZ_', 'CR_'))}
    env['PATH'] = str(bin_dir) + os.pathsep + env.get('PATH', '')
    env.update(extra_env or {})
    return ws, archive, env


def tree_digest(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in sorted(Path(root).rglob('*')) if p.is_file()}


# ---- one run ----

def kill_tree(proc) -> None:
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True)
    else:
        proc.kill()


def ledger_tokens(ws: Path) -> int:
    total = 0
    for ledger in Path(ws).glob('do/*/calls.jsonl'):
        try:
            lines = ledger.read_text(encoding='utf-8').splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            u = (ev.get('usage') or {}).get('raw') if ev.get('event') == 'call_end' else None
            if isinstance(u, dict):
                total += u.get('input_tokens', 0) + u.get('output_tokens', 0)
    return total


def launch(argv, data: bytes, ws: Path, env: dict, timeout: float, cap: int):
    """Run the caller with the in-run guard: the run is stopped (process tree killed) as soon as its running billed
    tokens (per-message caller usage plus worker ledger usage) reach cap, when a model call beyond MAX_TURNS starts,
    or at the wall timeout. Returns (stdout bytes, stderr bytes, meta)."""
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ws,
                            env=env)
    out, err, state = [], [], {'stop': None, 'peak': 0}
    msgs = {}

    def feed():
        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except OSError:
            pass

    def read_out():
        for line in proc.stdout:
            out.append(line)
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get('type') != 'assistant' or ev.get('parent_tool_use_id'):
                continue
            m = ev.get('message') or {}
            mid = m.get('id') or 'anon%d' % len(msgs)
            u = m.get('usage') or {}
            cur = msgs.setdefault(mid, {})
            for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens'):
                if type(u.get(k)) is int:
                    cur[k] = max(u[k], cur.get(k, 0))
            running = sum(sum(v.values()) for v in msgs.values()) + ledger_tokens(ws)
            state['peak'] = max(state['peak'], running)
            if state['stop'] is None and running >= cap:
                state['stop'] = 'cap'
                kill_tree(proc)
            elif state['stop'] is None and len(msgs) > MAX_TURNS:
                state['stop'] = 'turns'
                kill_tree(proc)

    threads = [threading.Thread(target=feed), threading.Thread(target=read_out),
               threading.Thread(target=lambda: err.append(proc.stderr.read()))]
    started = time.monotonic()
    for t in threads:
        t.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        state['stop'] = state['stop'] or 'timeout'
        kill_tree(proc)
        proc.wait()
    for t in threads:
        t.join(timeout=60)
    for pipe in (proc.stdout, proc.stderr):
        pipe.close()
    meta = {'exit_code': proc.returncode, 'wall_s': round(time.monotonic() - started, 2), 'stop_reason': state['stop'],
            'peak_running_tokens': state['peak'], 'cap': cap, 'max_turns': MAX_TURNS, 'timeout_s': timeout}
    return b''.join(out), b''.join(err), meta


def run_one(spec, run_dir, claude=None, delegate=None, timeout=TIMEOUT, cap=RUN_CAP, extra_env=None, root=FIX,
            fixes=None) -> dict:
    """Run one spec end to end in a fresh workspace, keep every raw artifact under run_dir, then build the record from
    those raw files only (build_record, the same function rejudge uses)."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / 'prompt.txt').write_bytes(spec['prompt'].encode('utf-8'))
    (run_dir / 'spec.json').write_text(json.dumps({k: v for k, v in spec.items() if k not in ('files', 'prompt')},
                                                  ensure_ascii=False, indent=1), encoding='utf-8')
    tmp = Path(tempfile.mkdtemp(prefix='cr-'))
    try:
        ws, archive, env = setup(tmp, spec, delegate, extra_env)
        (run_dir / 'ws_start.json').write_text(json.dumps(tree_digest(ws), indent=1), encoding='utf-8')
        started = time.time()
        out, err, meta = launch(caller_argv(claude or L.CLAUDE), spec['prompt'].encode('utf-8'), ws, env, timeout, cap)
        meta.update(started=started, workspace=str(ws))
        (run_dir / 'transcript.jsonl').write_bytes(out)
        (run_dir / 'stderr.txt').write_bytes(err)
        final = [e for e in _events(out.decode('utf-8', 'replace')) if e.get('type') == 'result']
        if final:
            (run_dir / 'caller_envelope.json').write_text(json.dumps(final[-1], ensure_ascii=False, indent=1),
                                                          encoding='utf-8')
        if (ws / 'results.json').is_file():
            shutil.copyfile(ws / 'results.json', run_dir / 'results.json')
        if (ws / 'do').is_dir():
            shutil.copytree(ws / 'do', run_dir / 'do')
        shutil.copytree(archive, run_dir / 'archive')
        (run_dir / 'ws_files.json').write_text(json.dumps(tree_digest(ws), indent=1), encoding='utf-8')
        (run_dir / 'meta.json').write_text(json.dumps(meta, indent=1), encoding='utf-8')
        (run_dir / 'raw_complete').write_text('raw data kept\n', encoding='utf-8')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    rec = build_record(spec, run_dir, root=root, fixes=fixes)
    (run_dir / 'record.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
    return rec


def _events(text: str) -> list:
    out = []
    for line in text.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def tool_texts(text: str) -> tuple:
    """(tool inputs, tool results) of the caller's own turns, as text."""
    inputs, results = [], []
    for ev in _events(text):
        if ev.get('type') == 'assistant' and not ev.get('parent_tool_use_id'):
            for b in (ev.get('message') or {}).get('content') or []:
                if b.get('type') == 'tool_use':
                    inp = b.get('input')
                    inputs.append(inp.get('command') if isinstance(inp, dict) and isinstance(inp.get('command'), str)
                                  else J(inp))
        elif ev.get('type') == 'user':
            content = (ev.get('message') or {}).get('content')
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get('type') == 'tool_result':
                    c = b.get('content')
                    results.append(c if isinstance(c, str) else '\n'.join(
                        x.get('text', '') if isinstance(x, dict) else str(x) for x in c or []))
    return inputs, results


def shows_modules(spec, text: str) -> bool:
    """Module content reached a text: three or more distinct lines (16+ characters, not in WITNESS_FORMAT.md) of one
    of the pack's modules appear in it, verbatim after stripping (cat -n and similar prefixes do not hide them)."""
    fmt = spec['files'][FORMAT].decode('utf-8')
    for rel in PACKS[spec['pack']]:
        lines = {x.strip() for x in spec['files'][rel].decode('utf-8').split('\n')}
        lines = {x for x in lines if len(x) >= 16 and x not in fmt}
        if sum(1 for x in lines if x in text) >= 3:
            return True
    return False


def _repo_forms() -> list:
    r = str(ROOT).lower()
    posix = r.replace('\\', '/')
    forms = [r, posix]
    if re.match(r'^[a-z]:/', posix):
        forms.append('/' + posix[0] + posix[2:])
    return forms


def breaches_in(inputs, results) -> list:
    """The isolation tripwire (evaluator-only storage is reachable on disk, so reaching for it is recorded): a tool
    input naming the repository or the evaluator storage, or a tool result holding evaluator-only text."""
    out = []
    for text in inputs:
        low = text.lower()
        for form in _repo_forms() + ['answer_key', 'codereview', 'eval_worker', 'oracle.py']:
            if form in low:
                out.append('tool input names ' + form)
    key = O.load_key()
    marks = ['"classification": "evaluator-only"', '"hidden_witness": {', '"reference_fix":',
             (HERE / 'oracle.py').read_text(encoding='utf-8').split('\n')[0],
             (HERE / 'eval_worker.py').read_text(encoding='utf-8').split('\n')[0]]
    marks += [s['reference_fix'] for m in key['modules'] for s in m['seeds']]
    for text in results:
        for mark in marks:
            if mark in text:
                out.append('tool result holds evaluator-only text: ' + mark[:40])
    return sorted(set(out))


def oz_invocations(run_dir: Path) -> list:
    out = []
    for d in sorted((run_dir / 'archive' / 'oz').glob('*')):
        if (d / 'argv.json').is_file():
            argv = json.loads((d / 'argv.json').read_text(encoding='utf-8'))['argv']
            meta = json.loads((d / 'meta.json').read_text(encoding='utf-8')) if (d / 'meta.json').is_file() else {}
            out.append({'dir': d.name, 'argv': argv, 'exit': meta.get('exit'),
                        'request_bytes': (d / 'request.bin').stat().st_size if (d / 'request.bin').is_file() else None})
    return out


def dispatched_requests(run_dir: Path) -> list:
    """The stored work of every `oz do` run directory that started at least one worker call."""
    out = []
    for calls in sorted((run_dir / 'do').glob('*/calls.jsonl')):
        events = [json.loads(x) for x in calls.read_text(encoding='utf-8').splitlines() if x.strip()]
        if any(e.get('event') == 'call_start' for e in events):
            out.append(json.loads((calls.parent / 'request.json').read_text(encoding='utf-8')))
    return out


def protocol(spec, run_dir: Path, inputs, results, worker_calls: int) -> list:
    """Frozen protocol rules (03 change 2). Arm I: no `oz do` invocation. Arm D: exactly one worker call; the
    dispatched request has max_attempts 1, no profile and no checks, three jobs, each module passed by path in exactly
    one job; no module content in any caller tool input or result."""
    v = []
    do_calls = [i for i in oz_invocations(run_dir) if i['argv'][:1] == ['do']]
    if spec['arm'] == 'I':
        if do_calls:
            v.append('arm I ran oz do')
        return v
    if worker_calls == 0:
        v.append('no worker dispatch')
    elif worker_calls > 1:
        v.append('more than one worker call')
    want = {rel: f'{rel}@sha256:{sha(spec["files"][rel])}' for rel in PACKS[spec['pack']]}
    for req in dispatched_requests(run_dir):
        work = req['work']
        if work.get('max_attempts') != 1:
            v.append('max_attempts is not 1')
        if 'profile' in work or work.get('checks'):
            v.append('the request carries a profile or checks')
        sources = work.get('refs', {})
        jobs = work.get('jobs', [])
        per_module = {rel: sum(1 for j in jobs if any(sources.get(r) == src for r in j[2:])) for rel, src in want.items()}
        if len(jobs) != 3 or any(n != 1 for n in per_module.values()):
            v.append('the jobs do not pass each module by path in exactly one of three jobs')
    if any(shows_modules(spec, t) for t in list(inputs) + list(results)):
        v.append('module content reached the caller')
    return sorted(set(v))


def envelope_usage(run_dir: Path) -> dict:
    calls = inn = out = 0
    for path in sorted((run_dir / 'archive' / 'worker' / 'envelopes').glob('*.json')):
        mu = json.loads(path.read_text(encoding='utf-8')).get('modelUsage') or {}
        calls += 1
        for m in mu.values():
            inn += m.get('inputTokens', 0) + m.get('cacheReadInputTokens', 0) + m.get('cacheCreationInputTokens', 0)
            out += m.get('outputTokens', 0)
    return {'envelopes': calls, 'envelope_in': inn, 'envelope_out': out}


def build_record(spec, run_dir, root=FIX, fixes=None) -> dict:
    """The record of one run from its raw files only (transcript, caller envelope, oz archive, worker packets and
    envelopes, ledgers, meta). Judged against spec['pack'] alone."""
    run_dir = Path(run_dir)
    text = (run_dir / 'transcript.jsonl').read_bytes().decode('utf-8', 'replace')
    meta = json.loads((run_dir / 'meta.json').read_text(encoding='utf-8'))
    parsed = K.parse_stream(text)
    final = next((e for e in reversed(_events(text)) if e.get('type') == 'result'), None)
    inputs, results = tool_texts(text)
    wu = K.worker_usage(run_dir)
    ev = envelope_usage(run_dir)
    agree = (ev['envelopes'] == wu['worker_calls'] and ev['envelope_in'] == wu['worker_in']
             and ev['envelope_out'] == wu['worker_out'])
    complete = parsed['usage_reported'] and wu['worker_calls'] == wu['worker_calls_with_usage'] and agree
    caller_msgs = sum(sum(v for k, v in m.items() if k in ('input_tokens', 'cache_read_input_tokens',
                                                            'cache_creation_input_tokens', 'output_tokens'))
                      for m in parsed['messages'])
    total = (parsed['caller_in'] + parsed['caller_out'] + wu['worker_in'] + wu['worker_out']) if complete else None
    lower = max(caller_msgs, parsed['caller_in'] + parsed['caller_out']) + wu['worker_in'] + wu['worker_out']
    truncation = []
    if (final or {}).get('subtype') == 'error_max_turns':
        truncation.append('max_turns')
    if meta.get('stop_reason'):
        truncation.append(meta['stop_reason'])
    if final is None:
        truncation.append('no_result')
    elif final.get('is_error') and 'max_turns' not in truncation:
        truncation.append('caller_error')
    violations = protocol(spec, run_dir, inputs, results, wu['worker_calls'])
    breaches = breaches_in(inputs, results)
    score = O.score(parsed['text'], spec['pack'], root=root, fixes=fixes)
    status = ('isolation_breach' if breaches else 'protocol_violation' if violations else
              'truncated' if truncation else 'inconclusive_accounting' if not complete else 'valid')
    return {
        'tag': spec['tag'], 'pack': spec['pack'], 'arm': spec['arm'], 'input_sha256': spec['input_sha256'],
        'oracle_version': ORACLE_VERSION, 'status': status, 'scored_as_arm': not violations and not breaches,
        'truncated': bool(truncation), 'truncation': truncation, 'violations': violations, 'breaches': breaches,
        'caller': {'turns': parsed['turns'], 'model_calls': len(parsed['messages']), 'in_total': parsed['caller_in'],
                   'in_uncached': parsed['caller_in_uncached'], 'cache_read': parsed['caller_cache_read'],
                   'cache_write': parsed['caller_cache_write'], 'out': parsed['caller_out'],
                   'models': parsed['caller_models'], 'usage_reported': parsed['usage_reported'],
                   'envelope': final is not None, 'subtype': (final or {}).get('subtype'),
                   'bash_calls': parsed['bash_calls'], 'oz_do_calls': parsed['oz_do_calls'],
                   'per_message_tokens': caller_msgs},
        'worker': {'calls': wu['worker_calls'], 'calls_with_usage': wu['worker_calls_with_usage'],
                   'in': wu['worker_in'], 'cached_in': wu['worker_cached_in'], 'out': wu['worker_out'], **ev,
                   'sources_agree': agree, 'oz_invocations': len(oz_invocations(run_dir))},
        'accounting_complete': complete, 'total_tokens': total, 'lower_bound_tokens': lower,
        'charged_tokens': total if complete else max(RUN_CAP, lower), 'prep_tokens': 0,
        'wall_s': meta['wall_s'], 'exit_code': meta['exit_code'], 'stop_reason': meta.get('stop_reason'),
        'score': score, 'messages': parsed['messages'],
        'tool_calls': [{k: t[k] for k in ('name', 'msg', 'input_bytes', 'result_bytes')} for t in parsed['tools']],
        'text': parsed['text']}


# ---- state, admission, counted runs ----

def _jsonl(path: Path) -> list:
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()] if path.exists() else []


def state(out: Path) -> dict:
    out = Path(out)
    return {'attempts': _jsonl(out / 'attempts.jsonl'),
            'records': {r['attempt']: r for r in _jsonl(out / 'runs.jsonl')},
            'quota': {q['attempt']: q['after_percent'] for q in _jsonl(out / 'quota.jsonl')}}


def _percent(text):
    try:
        value = float(str(text).strip().rstrip('%'))
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 100 else None


def admission(st: dict, quota_before) -> dict:
    """Admission before launch (02 section 6 as amended): the weekly figure must be read just now; every earlier
    admitted run must be settled (its after-figure recorded); spent tokens (runs at their charged tokens, an attempt
    without a record at the full run cap, plus paid preparation) plus this run's whole cap must stay within the total
    cap; the projection before + factor * RUN_CAP + ROUNDING must stay below ADMIT_BELOW. factor starts at 2 points
    per 55,000 tokens and rises to the largest observed (after - before) / tokens of a settled run with complete
    accounting; it never falls."""
    reasons = []
    before = _percent(quota_before)
    if before is None:
        reasons.append('no usable weekly quota reading (pass the figure read just now)')
    admitted = [a for a in st['attempts'] if a.get('admitted') is True and 'event' not in a]
    unsettled = [a['attempt'] for a in admitted if a['attempt'] not in st['quota']]
    if unsettled:
        reasons.append('unsettled: record the weekly figure after ' + ', '.join(unsettled) + ' (quota-after)')
    spent = PREP_TOKENS + sum(st['records'].get(a['attempt'], {}).get('charged_tokens', RUN_CAP) for a in admitted)
    if spent + RUN_CAP > TOTAL_CAP:
        reasons.append(f'total cap: {spent} spent + {RUN_CAP} reserved > {TOTAL_CAP}')
    factor = FACTOR0
    for a in admitted:
        rec, after = st['records'].get(a['attempt']), st['quota'].get(a['attempt'])
        if rec and after is not None and rec.get('accounting_complete') and rec.get('total_tokens'):
            factor = max(factor, (after - a['quota_before']) / rec['total_tokens'])
    projection = None if before is None else before + factor * RUN_CAP + ROUNDING
    if projection is not None and projection >= ADMIT_BELOW:
        reasons.append(f'projection {projection:.2f}% reaches {ADMIT_BELOW:g}%')
    return {'admitted': not reasons, 'reasons': reasons, 'quota_before': before, 'projection': projection,
            'factor': factor, 'spent_tokens': spent}


def environment(claude=None) -> dict:
    head = list(claude) if isinstance(claude, (list, tuple)) else [claude or L.CLAUDE]
    cli = subprocess.run([*head, '--version'], capture_output=True, text=True).stdout.strip()
    return {'cli_version': cli, 'core_sha256': {p: O.norm_sha(ROOT / p) for p in CORE}}


def load_fixes(out: Path) -> dict:
    """Registered fixes for the unseeded rule: out/fixes/<module path>, written by a person after review."""
    base = Path(out) / 'fixes'
    return {p.relative_to(base).as_posix(): p.read_bytes().decode('utf-8') for p in sorted(base.rglob('*.py'))} \
        if base.is_dir() else {}


def append_jsonl(path: Path, row: dict) -> None:
    with Path(path).open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')


def append_record(out: Path, rec: dict) -> None:
    append_jsonl(Path(out) / 'runs.jsonl', rec)


def recover(out: Path, digest: str) -> None:
    """After a crash: an admitted attempt with kept raw data but no record line is rebuilt from its raw data (never
    re-run); one without kept raw data is recorded as aborted (charged the full run cap) and its directory moved
    aside, so the run is repeated only after its quota reading is settled."""
    st = state(out)
    aborted = {a['attempt'] for a in st['attempts'] if a.get('event') == 'aborted'}
    for a in st['attempts']:
        if a.get('admitted') is not True or 'event' in a or a['attempt'] in st['records'] or a['attempt'] in aborted:
            continue
        run_dir = Path(out) / a['tag']
        if (run_dir / 'raw_complete').is_file():
            pack, arm = a['tag'].split('-')
            rec = build_record(build_spec(pack, arm), run_dir, fixes=load_fixes(out))
            rec.update(attempt=a['attempt'], manifest=digest, recovered=True)
            (run_dir / 'record.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
            append_record(out, rec)
            print(a['attempt'], 'rebuilt from its kept raw data (not re-run)', flush=True)
        else:
            if run_dir.exists():
                run_dir.rename(run_dir.with_name(a['tag'] + time.strftime('.aborted-%Y%m%dT%H%M%S')))
            append_jsonl(Path(out) / 'attempts.jsonl', {'attempt': a['attempt'], 'tag': a['tag'], 'event': 'aborted',
                                                        'charged_tokens': RUN_CAP, 'time': time.time()})
            print(a['attempt'], 'aborted without raw data: charged the run cap; settle its quota, then rerun',
                  flush=True)


def counted(expect, quota_before, out=DATA, claude=None, delegate=None, extra_env=None) -> int:
    """The next run of SCHEDULE, admitted before launch. 0: ran (or nothing left), 2: digest, freeze or environment
    drift, 3: refused by admission (recorded in attempts.jsonl, nothing launched)."""
    out = Path(out)
    digest, _ = manifest()
    if digest != expect:
        print(f'digest {digest} differs from --expect {expect}; refreeze plan-frozen.md first', flush=True)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    env = environment(claude)
    if claude is None:   # live caller: the environment must be the frozen one
        frozen = json.loads(FREEZE_FILE.read_text(encoding='utf-8'))
        if frozen['digest'] != digest or frozen['environment'] != env:
            print('freeze.json does not hold for this digest and environment (CLI version or core code)', flush=True)
            return 2
    man_path = out / 'manifest.json'
    if man_path.exists():
        man = json.loads(man_path.read_text(encoding='utf-8'))
        if man['digest'] != digest or man['environment'] != env:
            print('drift since the first counted run (digest, CLI version or core code); nothing launched', flush=True)
            return 2
    else:
        man_path.write_text(json.dumps({'digest': digest, 'environment': env, 'schedule': SCHEDULE,
                                        'started': time.strftime('%Y-%m-%dT%H:%M:%S')}, indent=1), encoding='utf-8')
    recover(out, digest)
    st = state(out)
    done = {r['tag'] for r in st['records'].values()}
    todo = [f'{p}-{a}' for p, a in SCHEDULE if f'{p}-{a}' not in done]
    if not todo:
        print('all', len(SCHEDULE), 'runs are recorded', flush=True)
        return 0
    tag = todo[0]
    adm = admission(st, quota_before)
    n = sum(1 for a in st['attempts'] if a['tag'] == tag and 'event' not in a) + 1
    attempt = f'{tag}#{n}'
    append_jsonl(out / 'attempts.jsonl', {'attempt': attempt, 'tag': tag, 'admitted': adm['admitted'],
                                          'quota_before': adm['quota_before'], 'projection': adm['projection'],
                                          'factor': adm['factor'], 'spent_tokens': adm['spent_tokens'],
                                          'reasons': adm['reasons'], 'manifest': digest, 'time': time.time(),
                                          'charged_tokens': 0 if not adm['admitted'] else None})
    if not adm['admitted']:
        print(attempt, 'REFUSED before launch:', '; '.join(adm['reasons']), flush=True)
        return 3
    print(attempt, f"admitted: projection {adm['projection']:.2f}% (factor {adm['factor']:.3e}/token)", flush=True)
    pack, arm = tag.split('-')
    rec = run_one(build_spec(pack, arm), out / tag, claude=claude, delegate=delegate, extra_env=extra_env,
                  fixes=load_fixes(out))
    rec.update(attempt=attempt, manifest=digest)
    (out / tag / 'record.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
    append_record(out, rec)
    show(rec)
    print('now read the weekly figure and run: pilot.py quota-after --percent PCT', flush=True)
    return 0


def quota_after(percent, out=DATA) -> int:
    after = _percent(percent)
    st = state(out)
    pending = [a for a in st['attempts'] if a.get('admitted') is True and 'event' not in a
               and a['attempt'] not in st['quota']]
    pending += [a for a in st['attempts'] if a.get('event') == 'aborted' and a['attempt'] not in st['quota']
                and a not in pending]
    if after is None or not pending:
        print('quota-after needs a weekly figure and an admitted run without one', flush=True)
        return 2
    a = pending[0]
    append_jsonl(Path(out) / 'quota.jsonl', {'attempt': a['attempt'], 'after_percent': after, 'time': time.time()})
    print(a['attempt'], 'settled at', after, '%' + ('  CEILING REACHED: stop' if after >= CEILING else ''),
          flush=True)
    return 0


def show(rec: dict) -> None:
    s = rec['score']
    print(rec['tag'], rec['status'], 'turns', rec['caller']['turns'], 'caller', rec['caller']['in_total'],
          rec['caller']['out'], 'worker', rec['worker']['calls'], rec['worker']['in'], rec['worker']['out'], 'total',
          rec['total_tokens'], 'charged', rec['charged_tokens'], 'correct', f"{s['correct_files']}/3", 'recall',
          s['recall'], 'FP', s['false_positives'], 'unproven', s['unproven'], 'wall', rec['wall_s'], flush=True)


# ---- freeze ----

def manifest() -> tuple:
    """(digest, payload): everything that defines the counted runs and their judgment."""
    runs = []
    for pack, arm in SCHEDULE:
        s = build_spec(pack, arm)
        runs.append([s['tag'], s['input_sha256'], s['files_sha256']])
    payload = {
        'model': MODEL, 'effort': 'default', 'caller_argv': caller_argv('claude'), 'timeout_s': TIMEOUT,
        'max_turns': MAX_TURNS, 'run_cap': RUN_CAP, 'total_cap': TOTAL_CAP, 'prep_cap': PREP_CAP,
        'prep_tokens': PREP_TOKENS, 'admission': {'below': ADMIT_BELOW, 'ceiling': CEILING, 'factor0': FACTOR0,
                                                  'rounding': ROUNDING, 'supplied_reading': SUPPLIED_READING},
        'ws_max_tokens': WS_MAX_TOKENS, 'schedule': SCHEDULE, 'packs': PACKS, 'oracle': ORACLE_VERSION,
        'texts': {'fill_head': FILL_HEAD, 'fill_tail': FILL_TAIL, 'requirement': REQUIREMENT, 'oz_snippet': OZ_SNIPPET,
                  'task_A_I': task_text('A', 'I')},
        'fill': {'sha256': FILL_SHA256, 'sources': FILL_SOURCES, 'o200k': fill_tokens()},
        'fixtures': {rel: sha(data) for rel, data in sorted(
            (p.relative_to(FIX).as_posix(), p.read_bytes()) for p in FIX.rglob('*') if p.is_file()
            and '__pycache__' not in p.parts)},
        'code': {rel: O.norm_sha(ROOT / rel) for rel in CODE},
        'design': {p.name: O.norm_sha(p) for p in sorted(DESIGN.glob('0*.md'))
                   + [DESIGN / 'fixtures-as-authored-by-astra.txt']},
        'sandbox_pin': O.SANDBOX_SHA256, 'sizing': sizing(), 'slopes': SLOPES, 'runs': runs}
    return sha(J(payload)), payload


def freeze(write=False) -> int:
    digest, payload = manifest()
    env = environment()
    record = {'digest': digest, 'environment': env, 'fill_sha256': FILL_SHA256, 'fill_o200k': payload['fill']['o200k'],
              'sha256sums_sha256': payload['fixtures']['SHA256SUMS'], 'sandbox_pin': O.SANDBOX_SHA256,
              'runs': payload['runs']}
    if write:
        record['frozen_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        FREEZE_FILE.write_text(json.dumps(record, indent=1) + '\n', encoding='utf-8', newline='\n')
        print('frozen', digest)
        return 0
    old = json.loads(FREEZE_FILE.read_text(encoding='utf-8')) if FREEZE_FILE.exists() else {}
    ok = old.get('digest') == digest and old.get('environment') == env
    print('freeze holds' if ok else 'FREEZE BROKEN', digest)
    return 0 if ok else 1


# ---- analysis ----

def report(out=DATA) -> None:
    rows = _jsonl(Path(out) / 'runs.jsonl')
    f0 = fill_tokens()
    print('tag | arm | status | caller turns | model calls | caller in | cache read | cache write | caller out | '
          'worker calls | worker in | worker out | total | time s | correct | recall | FP | unproven')
    for r in rows:
        c, w, s = r['caller'], r['worker'], r['score']
        print(' | '.join(str(x) for x in (r['tag'], r['arm'], r['status'], c['turns'], c['model_calls'],
                                           c['in_total'], c['cache_read'], c['cache_write'], c['out'], w['calls'],
                                           w['in'], w['out'], r['total_tokens'], r['wall_s'],
                                           f"{s['correct_files']}/3", s['recall'], s['false_positives'],
                                           s['unproven'])))
    print(f'\nfill-slope sizing: measured fill {f0} o200k tokens; each caller model call rereads the fill; estimate '
          f'= measured total + model calls x slope x (fill - {f0}), slope {SLOPES[0]} to {SLOPES[1]} billed tokens '
          'per o200k token')
    print('tag | model calls | measured total | 60k fill estimate | 120k fill estimate')
    for r in rows:
        n, total = r['caller']['model_calls'], r['total_tokens']
        if total is None:
            print(r['tag'], '|', n, '| inconclusive accounting | - | -')
            continue
        est = {f: [round(total + n * s * (f - f0)) for s in SLOPES] for f in (60_000, 120_000)}
        print(f"{r['tag']} | {n} | {total} | {est[60_000][0]}-{est[60_000][1]} | {est[120_000][0]}-{est[120_000][1]}")
    spent = sum(r['charged_tokens'] for r in rows)
    print(f'\ncharged tokens {spent} of the {TOTAL_CAP} total cap; paid preparation {PREP_TOKENS}')


def rejudge(out=DATA, root_for=None, fixes_for=None) -> int:
    """Rebuild every stored record from its own raw data and its own pack and compare; returns the mismatch count."""
    bad = 0
    for r in _jsonl(Path(out) / 'runs.jsonl'):
        root = (root_for or {}).get(r['tag'], FIX)
        fixes = (fixes_for or {}).get(r['tag'], load_fixes(out))
        spec = build_spec(r['pack'], r['arm'], root=root, tag=r['tag'])
        if spec['input_sha256'] != r['input_sha256']:
            print(r['tag'], 'INPUT DRIFT')
            bad += 1
            continue
        rebuilt = build_record(spec, Path(out) / r['tag'], root=root, fixes=fixes)
        stored = {k: v for k, v in r.items() if k not in ('attempt', 'manifest', 'recovered')}
        if J(rebuilt) != J(stored):
            diff = sorted(k for k in set(rebuilt) | set(stored) if J(rebuilt.get(k)) != J(stored.get(k)))
            print(r['tag'], 'MISMATCH in', ', '.join(diff))
            bad += 1
    print('rejudge mismatches:', bad)
    return bad


# ---- the dry gate (fixture caller and fixture worker; zero tokens) ----

def dry_caller(base: Path, name: str, log=None, scenario=None, worker=None, root=FIX) -> dict:
    """claude/delegate/extra_env for a fixture run. scenario 'perfect' answers each pack's seeds."""
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    py = Path(sys.executable).resolve().as_posix()
    if scenario is None:
        scenario = {'steps': [{'cat': [FORMAT]}], 'answer': '{}'}
    sc_path = base / f'{name}.caller.json'
    if log:
        scenario = dict(scenario, log=str(log))
    sc_path.write_text(json.dumps(scenario), encoding='utf-8')
    wk_path = base / f'{name}.worker.json'
    wk_path.write_text(json.dumps(worker or {'values': {}, 'texts': {}}), encoding='utf-8')
    return {'claude': [py, (HERE / 'fixture_caller.py').as_posix()],
            'delegate': [py, (HERE / 'fixture_worker.py').as_posix(), wk_path.as_posix()],
            'extra_env': {'CR_FIXTURE_CALLER': str(sc_path)}}


def _finding(file, root=FIX, line=None, cls=None, witness=None):
    m = next(m for m in O.load_key(root)['modules'] if m['file'] == file)
    s = m['seeds'][0] if m['seeds'] else None
    return {'file': file, 'line': line if line is not None else s['span']['start_line'], 'class': cls or s['class'],
            'witness': witness or s['hidden_witness']}


def _perfect(pack, root=FIX):
    return {m['file']: [_finding(m['file'], root)] if m['seeds'] else [] for m in O.modules(pack, root)}


def _oz_request(pack):
    refs = {Path(rel).stem: {'path': rel} for rel in PACKS[pack]}
    refs['format'] = {'path': FORMAT}
    return {'model': MODEL, 'goal': 'Review three Python modules for defects.',
            'ops': {'review': 'Review this module against its documented contract and return its findings array.'},
            'refs': refs, 'jobs': [['j_' + Path(rel).stem, 'review', Path(rel).stem, 'format'] for rel in PACKS[pack]],
            'max_attempts': 1, 'allow_experimental': True}


def _w(function, args, expected):
    return {'function': function, 'args': args, 'kwargs': {}, 'expected': expected}


def _variant_root(base: Path) -> tuple:
    """A dry-only copy of the fixture whose clean control packB/settings.py carries a real defect in both its shipped
    and reference form, and the registered fix for it (the frozen settings.py)."""
    root = Path(base) / 'variant'
    if not root.exists():
        shutil.copytree(FIX, root)
        path = root / 'packB' / 'settings.py'
        text = path.read_text(encoding='utf-8')
        new = text.replace('if key.startswith(prefix)}', 'if prefix and key.startswith(prefix)}')
        assert new != text
        path.write_bytes(new.encode('utf-8'))
    return root, {'packB/settings.py': O.source('packB/settings.py')}


def dry(base=None) -> dict:
    """Every scenario through run_one with the fixture caller and worker, each judged and checked against the rules;
    then rejudge must give zero mismatches."""
    base = Path(base) if base else Path(tempfile.mkdtemp(prefix='crdry-'))
    out = base / 'out'
    out.mkdir(parents=True, exist_ok=True)
    scen = base / 'scenarios'
    variant, variant_fix = _variant_root(base)
    a_text = {rel: sha(O.source(rel)) for rel in PACKS['A']}
    b_text = {rel: sha(O.source(rel)) for rel in PACKS['B']}
    v_text = {rel: sha(O.source(rel, variant)) for rel in PACKS['B']}
    sel_line = O.source('packB/settings.py', variant).split('\n').index(
        '    return {key: value for key, value in settings.items() if prefix and key.startswith(prefix)}') + 1
    jobs = lambda pack: {rel: 'j_' + Path(rel).stem for rel in PACKS[pack]}
    mixed = {'packA/paging.py': [_finding('packA/paging.py', line=35)],
             'packA/sample_stats.py': [_finding('packA/sample_stats.py'),
                                       _finding('packA/sample_stats.py', line=30, witness=_w('spread', [[1, 2, 6]],
                                                                                             {'return': 5.0}))],
             'packA/labels.py': [{'file': 'packA/labels.py', 'line': 10, 'class': 'missing_guard',
                                  'witness': _w('slug', [''], {'return': ''})}]}
    unseeded = dict(_perfect('B', variant), **{'packB/settings.py': [
        {'file': 'packB/settings.py', 'line': sel_line, 'class': 'missing_guard',
         'witness': _w('select_prefix', [{'a': '1'}, ''], {'return': {'a': '1'}})}]})
    big = {'input_tokens': 20000, 'cache_read_input_tokens': 5000, 'cache_creation_input_tokens': 0,
           'output_tokens': 500}
    plan = {
        'I-clean': ('A', 'I', FIX, None, {'steps': [{'cat': list(PACKS['A']) + [FORMAT]}],
                                          'answer': J(_perfect('A'))}, None,
                    {'status': 'valid', 'correct': 3, 'recall': 1.0, 'fp': 0, 'unproven': 0, 'violations': [],
                     'worker_calls': 0, 'complete': True}),
        'D-mixed': ('A', 'D', FIX, None, {'steps': [{'cat': [FORMAT]}, {'oz': _oz_request('A')}],
                                          'answer': {'from_oz': jobs('A')}},
                    {'values': mixed, 'texts': a_text},
                    {'status': 'valid', 'correct': 1, 'recall': 0.5, 'fp': 3, 'unproven': 2, 'mislocated': 1,
                     'review_both_fail': 1, 'violations': [], 'worker_calls': 1, 'complete': True}),
        'D-violation': ('B', 'D', FIX, None, {'steps': [{'cat': ['packB/ranges.py']}, {'oz': _oz_request('B')}],
                                              'answer': {'from_oz': jobs('B')}},
                        {'values': _perfect('B'), 'texts': b_text},
                        {'status': 'protocol_violation', 'violations': ['module content reached the caller'],
                         'scored_as_arm': False, 'correct': 3, 'worker_calls': 1}),
        'I-truncated': ('B', 'I', FIX, None, {'steps': [{'cat': [rel]} for rel in PACKS['B']] + [{'cat': [FORMAT]}] * 2,
                                              'answer': None, 'final': 'max_turns'}, None,
                        {'status': 'truncated', 'truncation': ['max_turns'], 'correct': 0, 'complete': True}),
        'I-malformed': ('B', 'I', FIX, None, {'steps': [{'cat': list(PACKS['B'])}],
                                              'answer': '```json\n' + J(_perfect('B')) + '\n```'}, None,
                        {'status': 'valid', 'answer_ok': False, 'correct': 0, 'recall': 0.0}),
        'D-unseeded': ('B', 'D', variant, variant_fix, {'steps': [{'oz': _oz_request('B')}],
                                                        'answer': {'from_oz': jobs('B')}},
                       {'values': unseeded, 'texts': v_text},
                       {'status': 'valid', 'correct': 3, 'recall': 1.0, 'fp': 0, 'unseeded': 1, 'worker_calls': 1,
                        'complete': True}),
        'I-oz-violation': ('A', 'I', FIX, None, {'steps': [{'cat': list(PACKS['A'])}, {'oz': _oz_request('A')}],
                                                 'answer': J(_perfect('A'))},
                           {'values': _perfect('A'), 'texts': a_text},
                           {'status': 'protocol_violation', 'violations': ['arm I ran oz do'], 'scored_as_arm': False,
                            'correct': 3}),
        'I-cap': ('A', 'I', FIX, None, {'steps': [{'cat': [FORMAT]}] * 4, 'answer': J(_perfect('A')), 'usage': big,
                                        'sleep': 0.3}, None,
                  {'status': 'truncated', 'stop_reason': 'cap', 'complete': False, 'charged_min': RUN_CAP}),
    }
    res = {'ok': True, 'scenarios': {}, 'out': out, 'roots': {}, 'fixes': {}}
    for name, (pack, arm, root, fixes, caller_sc, worker_sc, want) in plan.items():
        spec = build_spec(pack, arm, root=root, tag=name)
        kw = dry_caller(scen, name, scenario=caller_sc, worker=worker_sc, root=root)
        rec = run_one(spec, out / name, root=root, fixes=fixes, **kw)
        append_record(out, rec)
        s = rec['score']
        got = {'status': rec['status'], 'correct': s['correct_files'], 'recall': s['recall'],
               'fp': s['false_positives'], 'unproven': s['unproven'], 'mislocated': s['mislocated'],
               'unseeded': s['unseeded'], 'review_both_fail': s['review_both_fail'], 'answer_ok': s['answer_ok'],
               'violations': rec['violations'], 'scored_as_arm': rec['scored_as_arm'],
               'worker_calls': rec['worker']['calls'], 'complete': rec['accounting_complete'],
               'truncation': rec['truncation'], 'stop_reason': rec['stop_reason']}
        problems = [f'{k}: got {got[k]!r}, want {v!r}' for k, v in want.items() if k != 'charged_min' and got[k] != v]
        if 'charged_min' in want and rec['charged_tokens'] < want['charged_min']:
            problems.append(f"charged {rec['charged_tokens']} below {want['charged_min']}")
        if rec['breaches']:
            problems.append('isolation breach: ' + '; '.join(rec['breaches']))
        if rec['accounting_complete'] and rec['total_tokens'] != rec['charged_tokens']:
            problems.append('charged tokens differ from the total of a complete run')
        if rec['worker']['calls'] and not rec['worker']['sources_agree']:
            problems.append('worker ledger and envelopes disagree')
        res['scenarios'][name] = {'record': rec, 'problems': problems, 'run_dir': str(out / name), 'root': str(root)}
        res['roots'][name] = root
        res['fixes'][name] = fixes
        res['ok'] = res['ok'] and not problems
        print(name, 'PASS' if not problems else 'FAIL ' + '; '.join(problems), '|', rec['status'],
              f"correct {s['correct_files']}/3 FP {s['false_positives']} unproven {s['unproven']} charged "
              f"{rec['charged_tokens']}", flush=True)
    mismatches = rejudge(out, root_for=res['roots'], fixes_for=res['fixes'])
    res['rejudge_mismatches'] = mismatches
    res['ok'] = res['ok'] and mismatches == 0
    print('DRY GATE', 'PASS' if res['ok'] else 'FAIL', flush=True)
    return res


def main(argv) -> int:
    cmd = argv[0] if argv else 'plan'
    if cmd == 'plan':
        digest, payload = manifest()
        for (pack, arm), run in zip(SCHEDULE, payload['runs']):
            print(run[0], 'input', run[1])
        print('fill o200k', payload['fill']['o200k'], 'sizing', json.dumps(payload['sizing']))
        print('digest', digest)
        return 0
    if cmd == 'freeze':
        return freeze(write=argv[1:2] == ['--write'])
    if cmd == 'dry':
        return 0 if dry(argv[1] if len(argv) > 1 else None)['ok'] else 1
    if cmd == 'run':
        args = dict(zip(argv[1::2], argv[2::2]))
        if set(args) != {'--expect', '--quota-before'} or len(argv) != 5:
            print('usage: pilot.py run --expect DIGEST --quota-before PCT', flush=True)
            return 2
        return counted(args['--expect'], args['--quota-before'])
    if cmd == 'quota-after':
        if argv[1:2] != ['--percent'] or len(argv) != 3:
            print('usage: pilot.py quota-after --percent PCT', flush=True)
            return 2
        return quota_after(argv[2])
    if cmd == 'report':
        report(argv[1] if len(argv) > 1 else DATA)
        return 0
    if cmd == 'rejudge':
        return 1 if rejudge(argv[1] if len(argv) > 1 else DATA) else 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main(sys.argv[1:]))
