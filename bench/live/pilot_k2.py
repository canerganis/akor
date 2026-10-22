"""Caller-cost experiment for `oz do` (docs/design/caller-cost-2026-10-23: 03 signed plan, 04 continuation oracle).

Arms (caller is `claude -p`, Sonnet 5.5, Bash tool only, default effort, concurrency 1, fresh workspace per run):
  J    the caller does the work itself (pilot arm J, now with Bash like every other arm)
  K0   pilot_k.K_TEXT unchanged, real `oz do` (rerun of the archived arm K)
  K1f  frozen K1 text, one `oz do` call through stdin, full result printed (results.json also written)
  K1r  frozen K1 text with --receipt: full result only in results.json, a <= 2,048-byte receipt printed
Blocks: A caller-held input (pilot prompt, inline references), reply contract; B references in files refs/N.txt
(pilot text), reply or artifact plus continuation; C references in files of exactly 4,096 bytes, artifact contract.
Contracts: reply = the pilot's 0.8 JSON reply judged by the pilot's strict oracle; art = results.json plus the
frozen continuation reply (round 04), judged by judge_artifact().

Every judgment uses the expected values stored in its own run spec (built from that run's seed); nothing reads the
module-level records of live6/live11 at judging time (the pilot_k cross-seed bug).
Kept per run under data/<out>/<tag>/: prompt, raw stream-json transcript, stderr, every `oz` invocation with its raw
request bytes and stdout, every worker packet and reply (recording adapter), ledgers, results.json.

Commands (no command except smoke and run calls a model):
  python bench/live/pilot_k2.py plan                      schedule, counts and the frozen digest
  python bench/live/pilot_k2.py smoke ARM BLOCK CONTRACT N [SEED]   one excluded calibration run (seed 2999)
  python bench/live/pilot_k2.py run --expect DIGEST       the counted runs, resumable, stops on drift
  python bench/live/pilot_k2.py report [FILE]             cells, G1, G2, G3 and M14 from stored records
  python bench/live/pilot_k2.py rejudge [FILE]            re-judge stored runs from their own seeds and files
"""
import hashlib, json, os, random, re, shutil, statistics, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import live11 as M
import run_live as L

X = M.X
REPO = Path(__file__).resolve().parents[2]
LIVE = Path(__file__).parent
DATA = LIVE / 'data'
MODEL = 'claude-sonnet-5-5'
TIMEOUT = 1800                       # caller wall limit, every arm
C_MAX_TOKENS = 100000                # block C workspace input budget (set by the harness, not the caller text)
REF_BYTES = 4096                     # block C reference size
ORACLE_VERSION = 'k2-oracle/1'
SMOKE_SEED = 2999
SEEDS = {('A', 16): (3005, 3006, 3007), ('A', 64): (3105, 3106, 3107),
         ('B', 16): (7001, 7002, 7003), ('B', 64): (7101, 7102, 7103), ('C', 64): (7201, 7202, 7203)}
GROUPS = (('A', 'reply', {16: ('J',), 64: ('K0', 'J', 'K1f')}),
          ('B', 'reply', {16: ('J', 'K1f'), 64: ('J', 'K1f')}),
          ('B', 'art', {16: ('J', 'K1f', 'K1r'), 64: ('J', 'K1f', 'K1r')}),
          ('C', 'art', {64: ('J', 'K1r')}))
SMOKES = (('J', 'C', 'art', 64), ('K1f', 'B', 'art', 64), ('K1r', 'C', 'art', 64), ('K0', 'A', 'reply', 64))
HARNESS = ('pilot_k2.py', 'k2_wrap.py', 'k2_adapter.py', 'pilot_k.py', 'pilot2.py', 'live11.py', 'live6.py',
           'live2.py', 'live3.py', 'live8.py', 'run_live.py')
CORE = ('oz.py', 'oz_batch.py', 'oz_reply.py', 'oz_runtime.py', 'oz_worker.py', 'oz_workspace.py', 'oz_do.py',
        'oz_cli.py', 'examples/claude_cli_adapter.py')

# ---- frozen texts ----
K1_HEAD = (
    'You have the `oz` command. It runs many small independent jobs in one batched model call. Do not answer any job '
    'yourself. Run `oz do --adapter adapter.json%s` exactly once, in a single Bash call in the current directory, with '
    "the request JSON on stdin through a quoted heredoc (<<'EOF' ... EOF). Do not write the request to a file and do "
    'not print it. Request format (JSON): {"model":"%s","goal":"<the goal>","ops":{"<name>":"<instruction for the '
    'job, written for one reference>"},"refs":{"<name>":"<reference text>"},"jobs":[["<message ID>","<op name>",'
    '"<ref name>"],...]}. When a reference is held in a file, give {"path":"<file path>"} as its value instead of its '
    'text. One job per message ID; an op is an instruction shared by jobs that ask the same thing of different '
    'references. jobs[<ID>].status is accepted, failed or unresolved, and jobs[<ID>].value is the result.')
K1_MODE = {
    'K1f': ' The command prints the full result JSON and also saves it, unchanged, to results.json in the current '
           'directory.',
    'K1r': ' The command saves the full result JSON to results.json in the current directory and prints only a short '
           'receipt: status, counts, the IDs not accepted, and the file path and SHA-256. Read results.json only for '
           'what the task needs.'}
K1_FLAG = {'K1f': '', 'K1r': ' --receipt'}
K1_REPLY_TAIL = (' Report accepted values with status 0, failed jobs with status 2 and unresolved jobs with status 1, '
                 'in the reply format stated at the end.')
FILE_LINE = 'References: the text of reference N is the content of the UTF-8 file refs/N.txt in the current directory.'
# Round 04, frozen continuation task, verbatim.
CONTINUATION = ('After `results.json` holds a top-level `jobs` map `{"<message ID>": {"status": '
                '"accepted"|"failed"|"unresolved", "value": <JSON>}}` covering every message ID, reply only with the '
                'JSON `{"outside":[...],"unknown":[...],"not_accepted":[...]}`. These are, in message order, the IDs '
                'whose value is exactly the string `outside`, the IDs whose value is exactly the string `unknown`, and '
                'the IDs whose status is not `accepted`.')
ART_LINE = 'Deliver the results in the file results.json in the current directory. ' + CONTINUATION
FILLER_WORDS = ('ledger', 'tray', 'station', 'routine', 'visual', 'check', 'recorded', 'noted', 'operator', 'handled',
                'stored', 'label', 'bin', 'sorted', 'packed', 'cleaned', 'logged', 'shift', 'batch', 'lot', 'sealed',
                'wrapped', 'shelf', 'cart', 'moved', 'returned', 'scanned', 'received', 'counted', 'stacked')


def k1_text(arm, contract):
    return K1_HEAD % (K1_FLAG[arm], MODEL) + K1_MODE[arm] + (K1_REPLY_TAIL if contract == 'reply' else '')


def k0_text():
    import pilot_k
    if pilot_k.MODEL != MODEL:
        raise SystemExit(f'pilot_k.K_TEXT was built for {pilot_k.MODEL}; unset MODEL in the environment')
    return pilot_k.K_TEXT.rstrip('\n')


# ---- workload: pure functions of the seed ----
def record_line(rec):
    return '; '.join(f'{f}={v}' for f, v in rec.items())


def oracle(rec, code):
    """live6.oracle on an explicit record (no module state)."""
    from decimal import Decimal
    if code == 'e':
        return list(rec.values())
    if code == 'm':
        return [f for f in ('uncertainty', 'method', 'basis') if rec[f] == 'unknown']
    if rec['uncertainty'] == 'unknown':
        return 'unknown'
    l, u = Decimal(rec['length'][:-3]), Decimal(rec['uncertainty'][:-3])
    if code == 'b':
        return [f'{l - u:.2f} mm', f'{l + u:.2f} mm']
    return 'inside' if l - u >= Decimal('12.48') and l + u <= Decimal('12.52') else 'outside'


def job_codes(n):
    return [f'{code}{k}' for k in range(1, 17) for code in 'ebmv'][:n]


def big_ref(seed, k, line):
    """Exactly REF_BYTES ASCII bytes: seeded filler lines, the record line on its own line at a seeded position, filler.
    The filler has no digits, '=', ';' and none of the field names or values the operations read."""
    rng = random.Random(f'k2-filler/{seed}/{k}')

    def filler_line():
        words = [rng.choice(FILLER_WORDS) for _ in range(rng.randint(8, 13))]
        return ' '.join(words).capitalize() + '.'
    lines = [filler_line() for _ in range(80)]
    room = REF_BYTES - len(line) - 1 - 64
    fits = 0
    while fits < len(lines) and sum(len(x) + 1 for x in lines[:fits + 1]) <= room:
        fits += 1
    before = rng.randint(0, fits)
    head = ''.join(x + '\n' for x in lines[:before])
    rest = REF_BYTES - len(head) - len(line) - 1
    tail = ' '.join(lines[before:])[:rest - 1] + '.'
    text = head + line + '\n' + tail
    assert len(text.encode('ascii')) == REF_BYTES and text.count(line) == 1
    return text


def build_spec(block, contract, arm, n, seed, tag=None):
    """Everything one run needs, bound to its own seed: prompt, workspace files, IDs and expected values."""
    recs = M.make_records(seed)
    M.use_records(recs)   # packet_08 reads the module records; only the prompt text is taken from it
    ids, packet = X.V.packet_08('materials', n)
    jobs = job_codes(n)
    expected = {mid: oracle(recs[int(job[1:])], job[0]) for mid, job in zip(ids, jobs)}
    lines = packet.rstrip('\n').split('\n')
    assert lines[2].startswith('Refs [') and lines[4].startswith('Messages') and lines[-1].startswith('Reply only JSON')
    used = sorted({int(j[1:]) for j in jobs})
    assert json.loads(lines[3]) == [[k, 'source', record_line(recs[k]), '', ''] for k in used]
    files = {}
    if block in ('B', 'C'):
        lines = lines[:2] + [FILE_LINE] + lines[4:]
        files = {f'refs/{k}.txt': (record_line(recs[k]) if block == 'B' else big_ref(seed, k, record_line(recs[k])))
                 .encode('utf-8') for k in used}
    if contract == 'art':
        lines[-1] = ART_LINE
    task = '\n'.join(lines) + '\n'
    prompt = (k0_text() + '\n\n' + task if arm == 'K0' else k1_text(arm, contract) + '\n\n' + task
              if arm in ('K1f', 'K1r') else task)
    files_sha = {p: hashlib.sha256(b).hexdigest() for p, b in sorted(files.items())}
    return {'tag': tag or f'{block}-{contract}-{arm}-{n}-{seed}', 'block': block, 'contract': contract, 'arm': arm,
            'n': n, 'seed': seed, 'system': L.SYSTEM, 'prompt': prompt, 'tools': 'Bash', 'files': files,
            'files_sha256': files_sha, 'ids': ids, 'jobs': jobs, 'expected': expected,
            'oz': {'K0': 'legacy', 'K1f': 'k2', 'K1r': 'k2'}.get(arm), 'max_tokens': C_MAX_TOKENS if block == 'C' else None,
            'workload_class': 'outside_qualified' if block == 'C' else 'standard', 'oracle_version': ORACLE_VERSION,
            'input_sha256': hashlib.sha256(J([L.SYSTEM, prompt, files_sha]).encode('utf-8')).hexdigest()}


def J(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


# ---- oracles (pure: they read only the spec) ----
def strict_json(text):
    """Strict JSON: duplicate keys and NaN/Infinity are errors; no fences or prose (surrounding whitespace allowed)."""
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError('duplicate key ' + key)
            obj[key] = value
        return obj

    def constant(name):
        raise ValueError('non-finite number ' + name)
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def text_ok(text, want):
    """The pilot's string rule (live6.check, native=False): the exact word, or JSON text equal to the expected value."""
    t = text.strip()
    try:
        return t == want or json.loads(t) == want
    except ValueError:
        return False


def value_ok(value, want):
    """Artifact value rule, same for every arm: the native JSON value, or a string the pilot's rule accepts."""
    return (type(value) is type(want) and value == want) or (isinstance(value, str) and text_ok(value, want))


def judge_reply(text, spec):
    """Reply contract: the pilot's strict oracle (json.loads, results08, per-job check). (error, verified)."""
    try:
        out = L.results08(json.loads(text), spec['ids'])
    except Exception as exc:  # noqa: BLE001
        return str(exc)[:200] or type(exc).__name__, 0
    return '', sum(out[m][0] == 'ok' and text_ok(out[m][1], spec['expected'][m]) for m in spec['ids'])


def continuation_expected(spec):
    ids, exp = spec['ids'], spec['expected']
    return {'outside': [m for m in ids if exp[m] == 'outside'], 'unknown': [m for m in ids if exp[m] == 'unknown'],
            'not_accepted': []}


def judge_artifact(data, reply, spec):
    """Artifact plus continuation (round 04). data: results.json bytes or None. A missing or malformed file, or a
    reply that does not match exactly, scores 0 verified; otherwise verified = accepted jobs whose value passes."""
    ids = spec['ids']
    res = {'file_error': '', 'reply_error': '', 'file_jobs_passed': 0, 'reply_ok': False, 'verified': 0}
    jobs = None
    if data is None:
        res['file_error'] = 'missing'
    else:
        try:
            obj = strict_json(data.decode('utf-8'))
            jobs = obj.get('jobs') if isinstance(obj, dict) else None
            if not isinstance(jobs, dict):
                raise ValueError('no top-level jobs map')
            if set(jobs) != set(ids):
                raise ValueError(f'jobs keys differ: {len(set(ids) - set(jobs))} missing, {len(set(jobs) - set(ids))} extra')
            for mid in ids:
                entry = jobs[mid]
                if not isinstance(entry, dict) or entry.get('status') not in ('accepted', 'failed', 'unresolved'):
                    raise ValueError(f'bad entry {mid}')
        except (ValueError, UnicodeError) as exc:
            res['file_error'], jobs = str(exc)[:200], None
    if jobs is not None:
        res['file_jobs_passed'] = sum(jobs[m]['status'] == 'accepted' and 'value' in jobs[m]
                                      and value_ok(jobs[m]['value'], spec['expected'][m]) for m in ids)
    try:
        got = strict_json(reply)
        if not isinstance(got, dict) or set(got) != {'outside', 'unknown', 'not_accepted'}:
            raise ValueError('reply keys must be exactly outside, unknown, not_accepted')
        if any(not isinstance(v, list) or any(not isinstance(x, str) for x in v) for v in got.values()):
            raise ValueError('reply lists must hold ID strings')
        want = continuation_expected(spec)
        bad = [k for k in ('outside', 'unknown', 'not_accepted') if got[k] != want[k]]
        if bad:
            raise ValueError('lists differ: ' + ', '.join(bad))
        res['reply_ok'] = True
    except (ValueError, TypeError) as exc:
        res['reply_error'] = str(exc)[:200]
    if jobs is not None and res['reply_ok']:
        res['verified'] = res['file_jobs_passed']
    return res


def judge(spec, reply, data):
    """(fields, verified) for either contract."""
    if spec['contract'] == 'reply':
        err, ok = judge_reply(reply, spec)
        return {'reply_error': err, 'reply_ok': not err, 'verified': ok}, ok
    res = judge_artifact(data, reply, spec)
    return res, res['verified']


# ---- caller transcript ----
def parse_stream(text):
    """Usage, per-message usage, tool calls and tool-result sizes from `claude -p --output-format stream-json`."""
    events, bad = [], 0
    for line in text.splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except ValueError:
                bad += 1
    final, msgs, order, tools, results, emitted = None, {}, [], [], {}, []
    for ev in events:
        kind = ev.get('type')
        if kind == 'result':
            final = ev
        elif kind == 'assistant' and not ev.get('parent_tool_use_id'):
            m = ev.get('message') or {}
            mid = m.get('id') or f'anon{len(order)}'
            if mid not in msgs:
                msgs[mid] = {}
                order.append(mid)
            for key, value in (m.get('usage') or {}).items():
                if type(value) is int:
                    msgs[mid][key] = max(value, msgs[mid].get(key, 0))
            for block in m.get('content') or []:
                if block.get('type') == 'tool_use':
                    inp = block.get('input')
                    text_in = inp.get('command') if isinstance(inp, dict) and isinstance(inp.get('command'), str) else J(inp)
                    tools.append({'id': block.get('id'), 'name': block.get('name'), 'msg': mid, 'input': text_in,
                                  'input_bytes': len(J(inp).encode('utf-8'))})
                    emitted.append(J(inp))
                elif block.get('type') in ('text', 'thinking'):
                    emitted.append(block.get('text') or block.get('thinking') or '')
        elif kind == 'user':
            content = (ev.get('message') or {}).get('content')
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get('type') == 'tool_result':
                    c = block.get('content')
                    c = c if isinstance(c, str) else J(c)
                    results[block.get('tool_use_id')] = len(c.encode('utf-8'))
    mu = (final or {}).get('modelUsage') or {}
    tot = lambda f: sum(m.get(f, 0) for m in mu.values())
    for t in tools:
        t['result_bytes'] = results.get(t['id'])
    return {'text': (final or {}).get('result', '') if final else '', 'has_result': final is not None,
            'usage_reported': bool(mu), 'is_error': (final or {}).get('is_error'), 'turns': (final or {}).get('num_turns'),
            'caller_in': tot('inputTokens') + tot('cacheReadInputTokens') + tot('cacheCreationInputTokens'),
            'caller_in_uncached': tot('inputTokens'), 'caller_cache_read': tot('cacheReadInputTokens'),
            'caller_cache_write': tot('cacheCreationInputTokens'), 'caller_out': tot('outputTokens'),
            'caller_models': sorted(mu), 'bash_calls': sum(t['name'] == 'Bash' for t in tools),
            'oz_do_calls': sum(t['name'] == 'Bash' and bool(re.search(r'\boz\s+do\b', t['input'])) for t in tools),
            'messages': [dict(id=mid, **msgs[mid]) for mid in order], 'tools': tools, 'emitted': ''.join(emitted),
            'unparsed_lines': bad}


CARRIER = (re.compile(r'["\']jobs["\']'), re.compile(r'["\']ops["\']'))


def attribution(parsed, total, count=L.count):
    """G3: caller tokens spent on the oz.do/1 request (generation plus rereads in every later turn), / run total.
    Carriers are tool calls whose input holds a request ("jobs" and "ops" keys). upper uses the API's output count of
    each carrier's whole message (thinking and other text included); estimate uses the o200k count of the carrier
    text times the run's ratio of reported caller output tokens to o200k tokens of everything the caller emitted.
    Both treat every later turn as rereading the request in full (cache reads at full weight, as the record does)."""
    order = [m['id'] for m in parsed['messages']]
    carriers = [t for t in parsed['tools'] if all(p.search(t['input']) for p in CARRIER)]
    if not carriers or not total:
        return {'carriers': len(carriers), 'request_o200k': 0, 'estimate': 0 if not carriers else None,
                'upper': 0 if not carriers else None, 'estimate_share': 0.0 if not carriers else None,
                'upper_share': 0.0 if not carriers else None}
    emitted = count(parsed['emitted'])
    ratio = parsed['caller_out'] / emitted if emitted else None
    est, upper, seen = 0.0, 0, set()
    for t in carriers:
        later = len(order) - order.index(t['msg']) - 1
        est = est + count(t['input']) * (1 + later) * ratio if ratio is not None else None
        if t['msg'] not in seen and upper is not None:
            seen.add(t['msg'])
            out = next(m for m in parsed['messages'] if m['id'] == t['msg']).get('output_tokens')
            upper = upper + out * (1 + later) if out else None
    return {'carriers': len(carriers), 'request_o200k': sum(count(t['input']) for t in carriers),
            'out_ratio': ratio, 'estimate': est, 'upper': upper,
            'estimate_share': est / total if est is not None else None,
            'upper_share': upper / total if upper is not None else None}


def worker_usage(ws):
    """Worker calls from every oz do run ledger: (calls started, calls with usage, input, cached input, output)."""
    started, used, inn, cached, out = set(), 0, 0, 0, 0
    for ledger in sorted(Path(ws).glob('do/*/calls.jsonl')):
        for line in ledger.read_text(encoding='utf-8').splitlines():
            ev = json.loads(line)
            if ev.get('event') == 'call_start':
                started.add((str(ledger), ev.get('call_id')))
            u = (ev.get('usage') or {}).get('raw') if ev.get('event') == 'call_end' else None
            if isinstance(u, dict):
                used += 1
                inn += u.get('input_tokens', 0)
                cached += u.get('cached_input_tokens', 0)
                out += u.get('output_tokens', 0)
    return {'worker_calls': len(started), 'worker_calls_with_usage': used, 'worker_in': inn,
            'worker_cached_in': cached, 'worker_out': out}


# ---- one run ----
def caller_argv(claude):
    head = list(claude) if isinstance(claude, (list, tuple)) else [claude]   # a list is a test double's argv
    return [*head, '-p', '--model', MODEL, '--system-prompt', L.SYSTEM, '--tools', 'Bash', '--allowedTools', 'Bash',
            '--setting-sources', '', '--strict-mcp-config', '--no-session-persistence', '--output-format',
            'stream-json', '--verbose']


def setup(tmp, spec, delegate=None):
    """Fresh workspace (and for K arms an oz workspace, the `oz` shim on PATH and the recording adapter)."""
    tmp = Path(tmp)
    ws, archive = tmp / 'ws', tmp / 'archive'
    archive.mkdir()
    py = Path(sys.executable).resolve()
    env = dict(os.environ, PYTHONPATH=str(REPO), OZ_MODEL=MODEL, TIKTOKEN_CACHE_DIR=str(REPO / '.token-cache'),
               PYTHONIOENCODING='utf-8')
    env.pop('MODEL', None)
    if spec['oz']:
        subprocess.run([str(py), '-c', 'import sys, oz_cli; sys.exit(oz_cli.main())', 'init', str(ws)], env=env,
                       check=True, capture_output=True)
        if spec['max_tokens']:
            cfg = json.loads((ws / 'oz.json').read_text(encoding='utf-8'))
            cfg['max_tokens'] = spec['max_tokens']
            (ws / 'oz.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        bin_dir = tmp / 'bin'
        bin_dir.mkdir()
        legacy = ' --legacy' if spec['oz'] == 'legacy' else ''
        (bin_dir / 'oz').write_text(f'#!/bin/sh\nexec "{py.as_posix()}" "{(LIVE / "k2_wrap.py").as_posix()}" --archive '
                                    f'"{(archive / "oz").as_posix()}"{legacy} "$@"\n', encoding='utf-8', newline='\n')
        delegate = delegate or [py.as_posix(), (REPO / 'examples' / 'claude_cli_adapter.py').as_posix()]
        (ws / 'adapter.json').write_text(json.dumps({'argv': [py.as_posix(), (LIVE / 'k2_adapter.py').as_posix(),
                                                              '--archive', (archive / 'worker').as_posix(), '--',
                                                              *delegate],
                                                     'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}),
                                         encoding='utf-8')
        env['PATH'] = str(bin_dir) + os.pathsep + env['PATH']
    else:
        ws.mkdir()
    for rel, data in spec['files'].items():
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_bytes(data)
    return ws, archive, env


def run_one(spec, run_dir, claude=None, delegate=None, timeout=TIMEOUT):
    """Run one spec end to end, keep its artifacts under run_dir, judge it against its own spec; returns the record."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / 'prompt.txt').write_text(spec['prompt'], encoding='utf-8', newline='\n')
    (run_dir / 'spec.json').write_text(json.dumps({k: v for k, v in spec.items() if k not in ('files', 'prompt')},
                                                  ensure_ascii=False, indent=1), encoding='utf-8')
    tmp = tempfile.mkdtemp(prefix='ozk2-')
    started = time.monotonic()
    call_error = None
    try:
        ws, archive, env = setup(tmp, spec, delegate)
        proc = subprocess.Popen(caller_argv(claude or L.CLAUDE), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=ws, env=env)
        try:
            out, err = proc.communicate(spec['prompt'].encode('utf-8'), timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, err = proc.communicate()
            call_error = 'timeout'
        wall = round(time.monotonic() - started, 2)
        (run_dir / 'transcript.jsonl').write_bytes(out)
        (run_dir / 'stderr.txt').write_bytes(err)
        results = (ws / 'results.json').read_bytes() if (ws / 'results.json').is_file() else None
        if results is not None:
            (run_dir / 'results.json').write_bytes(results)
        wu = worker_usage(ws)
        if (ws / 'do').is_dir():
            shutil.copytree(ws / 'do', run_dir / 'do', ignore=shutil.ignore_patterns('inbox.sqlite*'))
        shutil.copytree(archive, run_dir / 'archive')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    parsed = parse_stream(out.decode('utf-8', 'replace'))
    published = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((run_dir / 'archive' / 'oz').glob('*/published.json'))]
    fields, verified = judge(spec, parsed['text'], results)
    total = parsed['caller_in'] + parsed['caller_out'] + wu['worker_in'] + wu['worker_out']
    usage_complete = parsed['usage_reported'] and wu['worker_calls'] == wu['worker_calls_with_usage']
    rec = {'tag': spec['tag'], 'block': spec['block'], 'contract': spec['contract'], 'arm': spec['arm'], 'n': spec['n'],
           'seed': spec['seed'], 'input_sha256': spec['input_sha256'], 'oracle_version': ORACLE_VERSION,
           'workload_class': spec['workload_class'], 'jobs': spec['n'], 'verified': verified, **fields,
           'call_error': call_error, 'exit_code': proc.returncode, 'wall_s': wall, 'is_error': parsed['is_error'],
           'has_result': parsed['has_result'], 'turns': parsed['turns'], 'bash_calls': parsed['bash_calls'],
           'oz_do_calls': parsed['oz_do_calls'], 'oz_invocations': len(list((run_dir / 'archive' / 'oz').glob('*/meta.json'))),
           **{k: parsed[k] for k in ('caller_in', 'caller_in_uncached', 'caller_cache_read', 'caller_cache_write',
                                     'caller_out', 'caller_models')}, **wu,
           'total_tokens': total, 'usage_complete': usage_complete,
           'tokens_per_verified': round(total / verified, 2) if verified else None,
           'results_sha256': hashlib.sha256(results).hexdigest() if results is not None else None,
           'published_sha256': published[-1]['sha256'] if published else None,
           'artifact_intact': (published[-1]['sha256'] == hashlib.sha256(results).hexdigest())
           if published and results is not None else None,
           'messages': parsed['messages'],
           'tool_calls': [{k: t[k] for k in ('name', 'msg', 'input_bytes', 'result_bytes')} for t in parsed['tools']],
           'attribution': attribution(parsed, total) if spec['arm'] != 'J' else None,
           'text': parsed['text']}
    (run_dir / 'record.json').write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding='utf-8')
    return rec


# ---- schedule, freeze, drift ----
def schedule():
    """[(block, contract, arm, n, seed)] in run order: pairs of one seed run back to back, arm order seeded."""
    out = []
    for block, contract, arms_by_n in GROUPS:
        for n in sorted(arms_by_n):
            for seed in SEEDS[(block, n)]:
                arms = list(arms_by_n[n])
                random.Random(f'k2/{block}/{contract}/{n}/{seed}').shuffle(arms)
                out += [(block, contract, arm, n, seed) for arm in arms]
    return out


def norm_sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def manifest():
    """(digest, payload): everything that defines the counted runs. Any change to it changes the digest."""
    runs = []
    for cell in schedule():
        s = build_spec(*cell)
        runs.append([s['tag'], s['system'], s['prompt'], s['tools'], s['oz'], s['max_tokens'], s['files_sha256'],
                     s['expected'], s['input_sha256']])
    payload = {'model': MODEL, 'caller_argv': caller_argv('claude'), 'timeout_s': TIMEOUT, 'oracle': ORACLE_VERSION,
               'c_max_tokens': C_MAX_TOKENS, 'ref_bytes': REF_BYTES, 'concurrency': 1, 'effort': 'default',
               'texts': {'K1_HEAD': K1_HEAD, 'K1_MODE': K1_MODE, 'K1_FLAG': K1_FLAG, 'K1_REPLY_TAIL': K1_REPLY_TAIL,
                         'FILE_LINE': FILE_LINE, 'ART_LINE': ART_LINE, 'K0': k0_text()},
               'sources': {name: norm_sha(LIVE / name) for name in HARNESS}, 'runs': runs}
    return hashlib.sha256(J(payload).encode('utf-8')).hexdigest(), payload


def environment(claude=None):
    """What can drift between freeze and run without changing the digest: CLI version, core code, git state."""
    head = list(claude) if isinstance(claude, (list, tuple)) else [claude or L.CLAUDE]
    cli = subprocess.run([*head, '--version'], capture_output=True, text=True).stdout.strip()
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return {'cli_version': cli, 'git_head': head, 'core_sha256': {p: norm_sha(REPO / p) for p in CORE}}


def counted(expect, out=DATA / 'pilot_k2.jsonl', claude=None, delegate=None):
    digest, payload = manifest()
    if digest != expect:
        raise SystemExit(f'digest {digest} differs from --expect {expect}; refreeze plan-frozen.md first')
    env = environment(claude)
    man_path = out.with_suffix('.manifest.json')
    if man_path.exists():
        man = json.loads(man_path.read_text(encoding='utf-8'))
        if man['sha256'] != digest:
            raise SystemExit(f'{man_path} was started under digest {man["sha256"]}')
    else:
        man = {'sha256': digest, 'schedule': [list(c) for c in schedule()], 'environment': env,
               'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'model': MODEL, 'concurrency': 1}
        man_path.write_text(json.dumps(man, indent=1), encoding='utf-8')
    done = {json.loads(l)['tag'] for l in out.read_text(encoding='utf-8').splitlines()} if out.exists() else set()
    print('manifest', digest, 'done', len(done), 'of', len(schedule()), flush=True)
    for cell in schedule():
        spec = build_spec(*cell)
        if spec['tag'] in done:
            continue
        now = environment(claude)
        if now['cli_version'] != man['environment']['cli_version'] or now['core_sha256'] != man['environment']['core_sha256']:
            raise SystemExit('environment drift since the first counted run (CLI version or core code); stopped before '
                             + spec['tag'])
        run_dir = out.with_suffix('') / spec['tag']
        if run_dir.exists():   # an interrupted attempt left no record: keep its files aside, never reuse them
            run_dir.rename(run_dir.with_name(spec['tag'] + time.strftime('.aborted-%Y%m%dT%H%M%S')))
            print(spec['tag'], 'previous attempt interrupted; its files were kept aside and the run is repeated', flush=True)
        rec = run_one(spec, run_dir, claude=claude, delegate=delegate)
        rec['manifest'] = digest
        with out.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        show(rec)


def show(rec):
    print(rec['tag'], 'verified', f"{rec['verified']}/{rec['jobs']}", 'reply_ok', rec.get('reply_ok'),
          'file_err', rec.get('file_error', '-') or '-', 'caller', rec['caller_in'], rec['caller_out'],
          'worker', rec['worker_calls'], rec['worker_in'], rec['worker_out'], 'bash', rec['bash_calls'],
          'tpv', rec['tokens_per_verified'], 'wall', rec['wall_s'], 'err', rec['call_error'], flush=True)


def smoke(arm, block, contract, n, seed=SMOKE_SEED, out=DATA / 'pilot_k2_smoke.jsonl', claude=None, delegate=None):
    spec = build_spec(block, contract, arm, int(n), int(seed), tag=f'smoke-{block}-{contract}-{arm}-{n}-{seed}')
    run_dir = out.with_suffix('') / (spec['tag'] + time.strftime('-%Y%m%dT%H%M%S'))
    rec = run_one(spec, run_dir, claude=claude, delegate=delegate)
    rec['excluded'] = 'calibration smoke'
    rec['environment'] = environment(claude)
    rec['manifest'] = manifest()[0]
    with out.open('a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    show(rec)
    for pk in sorted(run_dir.glob('archive/worker/packets.jsonl')):
        for line in pk.read_text(encoding='utf-8').splitlines():
            p = json.loads(line)
            req = p['request'] or {}
            print('worker packet', len((req.get('system') or '').encode()), len((req.get('prompt') or '').encode()),
                  'bytes; ids', len(req.get('ids') or []), 'exit', p['exit'])
    return rec


# ---- analysis (preregistered gate rules) ----
def load(path):
    return [json.loads(l) for l in Path(path).read_text(encoding='utf-8').splitlines() if l.strip()]


def tpv(r):
    if not r.get('usage_complete', True) or r.get('total_tokens') is None:
        return None
    return r['total_tokens'] / r['verified'] if r['verified'] else float('inf')


def archived_k0():
    """Archived arm K at 64 (pilot_k_sonnet64.jsonl, rescored) in this module's record shape, for G1 without a rerun."""
    out = []
    for r in load(DATA / 'pilot_k_sonnet64.jsonl'):
        out.append({'arm': 'K0', 'block': 'A', 'contract': 'reply', 'n': 64, 'seed': r['seed'], 'verified': r['jobs_passed'],
                    'total_tokens': r['in'] + r['out'], 'bash_calls': r['bash_calls'], 'usage_complete': True,
                    'call_error': None, 'archived': True})
    return out


def cell(rows, block, contract, arm, n):
    return {r['seed']: r for r in rows if (r['block'], r['contract'], r['arm'], r['n']) == (block, contract, arm, n)}


def gates(rows):
    res = {}
    k1, k0 = cell(rows, 'A', 'reply', 'K1f', 64), cell(rows, 'A', 'reply', 'K0', 64)
    if not k0:
        k0 = {r['seed']: r for r in archived_k0()}
    seeds = SEEDS[('A', 64)]
    if not all(s in k1 and s in k0 for s in seeds):
        res['G1'] = 'incomplete'
    elif any(tpv(k1[s]) is None or tpv(k0[s]) is None for s in seeds):
        res['G1'] = 'inconclusive (missing usage)'
    else:
        ok = (sum(k1[s]['verified'] for s in seeds) == 192 and all(k1[s]['bash_calls'] <= k0[s]['bash_calls'] for s in seeds)
              and all(tpv(k1[s]) < tpv(k0[s]) for s in seeds))
        res['G1'] = 'pass' if ok else 'fail'
    g2, med = [], None
    for n in (16, 64):
        r, f = cell(rows, 'B', 'art', 'K1r', n), cell(rows, 'B', 'art', 'K1f', n)
        seeds = SEEDS[('B', n)]
        if not all(s in r and s in f for s in seeds):
            g2.append('incomplete')
            continue
        if any(tpv(r[s]) is None or tpv(f[s]) is None for s in seeds):
            g2.append('inconclusive')
            continue
        kept = all(r[s]['verified'] >= f[s]['verified'] and r[s]['file_jobs_passed'] >= f[s]['file_jobs_passed']
                   and (r[s]['reply_ok'] or not f[s]['reply_ok']) for s in seeds)
        cheaper = all(tpv(r[s]) < tpv(f[s]) for s in seeds)
        if n == 64:
            med = statistics.median(1 - tpv(r[s]) / tpv(f[s]) if tpv(f[s]) not in (0, float('inf')) else 0 for s in seeds)
        g2.append('pass' if kept and cheaper and (n == 16 or (med or 0) >= 0.10) else 'fail')
    res['G2'] = ('pass' if g2 == ['pass', 'pass'] else 'incomplete' if 'incomplete' in g2
                 else 'inconclusive (missing usage)' if 'inconclusive' in g2 else 'fail')
    res['G2_median_reduction_64'] = med
    shares = [r['attribution']['upper_share'] for r in rows if r['arm'] in ('K1f', 'K1r') and r['n'] == 64
              and r['block'] in ('B', 'C') and r.get('attribution')]
    if not shares or any(s is None for s in shares):
        res['G3'] = 'incomplete' if not shares else 'inconclusive (missing per-message usage)'
    else:
        est = [r['attribution']['estimate_share'] for r in rows if r['arm'] in ('K1f', 'K1r') and r['n'] == 64
               and r['block'] in ('B', 'C') and r.get('attribution')]
        res['G3_upper_median'] = statistics.median(shares)
        res['G3_estimate_median'] = statistics.median([e for e in est if e is not None]) if any(e is not None for e in est) else None
        res['G3'] = 'trigger producer preregistration' if res['G3_upper_median'] >= 0.25 else 'defer importer'
    m14 = {}
    for block, contract, arms_by_n in GROUPS:
        for n, arms in arms_by_n.items():
            for k in [a for a in arms if a in ('K1f', 'K1r')]:
                j, kk = cell(rows, block, contract, 'J', n), cell(rows, block, contract, k, n)
                seeds = SEEDS[(block, n)]
                name = f'{block}-{contract}-{n} J vs {k}'
                if not all(s in j and s in kk for s in seeds):
                    m14[name] = 'incomplete'
                elif any(tpv(j[s]) is None or tpv(kk[s]) is None for s in seeds):
                    m14[name] = 'inconclusive (missing usage)'
                else:
                    regress = lambda a, b, s: a[s]['verified'] < b[s]['verified'] or (a[s]['call_error'] and not b[s]['call_error'])
                    if all(tpv(j[s]) < tpv(kk[s]) and not regress(j, kk, s) for s in seeds):
                        m14[name] = 'J'
                    elif all(tpv(kk[s]) < tpv(j[s]) and not regress(kk, j, s) for s in seeds):
                        m14[name] = k
                    else:
                        m14[name] = 'undecided'
    res['M14'] = m14
    return res


def report(path=DATA / 'pilot_k2.jsonl'):
    rows = load(path)
    keys = sorted({(r['block'], r['contract'], r['arm'], r['n']) for r in rows})
    print('cell | runs | verified | tokens/verified per seed | caller share | bash calls')
    for key in keys:
        c = cell(rows, *key)
        per = [tpv(c[s]) for s in sorted(c)]
        share = [round((c[s]['caller_in'] + c[s]['caller_out']) / c[s]['total_tokens'], 3) if c[s]['total_tokens'] else None
                 for s in sorted(c)]
        print('-'.join(map(str, key)), len(c), sum(r['verified'] for r in c.values()), '/', sum(r['jobs'] for r in c.values()),
              [round(x, 1) if x not in (None, float('inf')) else x for x in per], share, [c[s]['bash_calls'] for s in sorted(c)])
    print(json.dumps(gates(rows), indent=1))


def rejudge(path=DATA / 'pilot_k2.jsonl'):
    """Re-judge every stored run from its stored reply and results.json against a spec rebuilt from its own seed."""
    bad = 0
    for r in load(path):
        spec = build_spec(r['block'], r['contract'], r['arm'], r['n'], r['seed'])
        if spec['input_sha256'] != r['input_sha256']:
            print(r['tag'], 'INPUT DRIFT', spec['input_sha256'], r['input_sha256'])
            bad += 1
            continue
        art = Path(path).with_suffix('') / r['tag'] / 'results.json'
        _, verified = judge(spec, r['text'], art.read_bytes() if art.is_file() else None)
        if verified != r['verified']:
            print(r['tag'], 'stored', r['verified'], 'rejudged', verified)
            bad += 1
    print('rejudge mismatches:', bad)
    return bad


def main(argv):
    cmd = argv[0] if argv else 'plan'
    if cmd == 'plan':
        digest, payload = manifest()
        for i, (block, contract, arm, n, seed) in enumerate(schedule()):
            print(i, block, contract, arm, n, seed)
        print('counted runs', len(payload['runs']), 'digest', digest)
    elif cmd == 'smoke':
        if argv[1:2] == ['all']:
            for s in SMOKES:
                smoke(*s)
        else:
            smoke(*argv[1:])
    elif cmd == 'run':
        if argv[1:2] != ['--expect'] or len(argv) != 3:
            raise SystemExit('usage: pilot_k2.py run --expect DIGEST')
        counted(argv[2])
    elif cmd == 'report':
        report(*argv[1:])
    elif cmd == 'rejudge':
        raise SystemExit(1 if rejudge(*argv[1:]) else 0)
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
