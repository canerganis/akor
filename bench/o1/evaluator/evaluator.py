"""Independent evaluator for repair-handoff-20/v1 (G3c-O1). Evaluator only; standard library only.

It imports nothing from the executor or its checks (oz*.py, workflow.py, sandbox_worker.py). It reads the frozen
declarative contracts and vectors (tickets, policy.json, tier_a.json, tier_i.json), its own held-out data
(heldout.json), the reference sources, preserved runner captures and delivered bytes. Code runs in its own worker
(eval_worker.py) under the shared launcher and Job Object (sandbox.run with worker=...): the confinement is the frozen
one, every outcome-deciding step (policy, value encoding, stubs, comparison) is written here again.

    judge_candidate(record, value)     independent A-tier verdict of one candidate against its exact recorded input
    h_tier(...)                        held-out verdict (bounded exhaustive domains, both hash seeds)
    evaluate_package(...)              a delivered package: byte provenance, A, I, H, patch, provenance file
    capture_lines(...)                 the value lines of a preserved runner capture, re-parsed (g3b's parser)
"""
from __future__ import annotations

import ast
import base64
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import zlib

HERE = Path(__file__).resolve().parent
O1 = HERE.parent
PACK = O1 / 'repair-handoff-20-v1'
ROOT = O1.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(O1) not in sys.path:
    sys.path.append(str(O1))

import eval_worker as EW  # noqa: E402
import heldout as H  # noqa: E402
import sandbox  # noqa: E402  the launcher and Job Object only; outcomes are decided here

EVAL_WORKER = HERE / 'eval_worker.py'
TICKETS = ('A', 'B', 'C', 'D')
HEAD = re.compile(r'O1 repair ticket\nticket: ([A-Z])\nrevision: ([0-9]+)\nop: repair_(core|adapter)@1\n')
CHUNK = 2500
MAX_SOURCE = 4096
_G3B = None
_CACHE: dict = {}


class EvaluatorUnavailable(Exception):
    """The evaluator could not run code; it decides nothing and the gate blocks pending investigation."""


def g3b():
    """bench/step4/g3b.py (standard library only, executor-free): its OZ/1g reply parser and capture reader."""
    global _G3B
    if _G3B is None:
        found = importlib.util.spec_from_file_location('_o1_g3b', ROOT / 'bench' / 'step4' / 'g3b.py')
        _G3B = importlib.util.module_from_spec(found)
        found.loader.exec_module(_G3B)
    return _G3B


def frozen(name):
    key = 'f:' + name
    if key not in _CACHE:
        _CACHE[key] = json.loads((PACK / name).read_text(encoding='utf-8'))
    return _CACHE[key]


def ticket(name, rev):
    files = frozen('workflow.json')['ticket_files']
    key = f'{name}.rev{rev}'
    if key not in files:
        return None
    return frozen(files[key])


def sha(text):
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode('utf-8')).hexdigest()


# ---- the evaluator's own AST policy (from the declarative policy.json) ----

def policy_problems(source, name, params, policy=None):
    policy = policy or frozen('policy.json')
    if not isinstance(source, str):
        return ['not text']
    try:
        if len(source.encode('utf-8')) > MAX_SOURCE:
            return ['longer than 4096 UTF-8 bytes']
        tree = ast.parse(source)
    except (SyntaxError, ValueError, UnicodeEncodeError, MemoryError, RecursionError):
        return ['does not parse']
    return _tree_problems(tree, policy, name, params)


def _tree_problems(tree, policy, name, params):
    allowed, methods = set(policy['nodes']), set(policy['methods'])
    banned = set(policy['forbidden_names'])
    found = []
    stack = [tree]
    while stack:
        node = stack.pop()
        stack.extend(ast.iter_child_nodes(node))
        kind = type(node).__name__
        if kind not in allowed:
            found.append('node ' + kind)
        elif kind == 'Name' and (node.id[:1] == '_' or node.id in banned):
            found.append('name ' + node.id)
        elif kind == 'Attribute' and (node.attr not in methods or node.attr[:1] == '_'):
            found.append('attribute ' + node.attr)
        elif kind == 'arg' and (node.arg[:1] == '_' or node.arg in banned or node.annotation is not None):
            found.append('parameter ' + node.arg)
        elif kind == 'keyword' and (node.arg is None or node.arg[:1] == '_'):
            found.append('keyword form')
        elif kind == 'ExceptHandler' and node.name is not None and (node.name[:1] == '_' or node.name in banned):
            found.append('handler name')
        elif kind in ('FunctionDef', 'Lambda'):
            a = node.args
            if a.posonlyargs or a.vararg or a.kwonlyargs or a.kw_defaults or a.kwarg or a.defaults:
                found.append('parameter form')
            if kind == 'FunctionDef' and (node.decorator_list or node.returns is not None
                                          or getattr(node, 'type_params', None) or node.name[:1] == '_'
                                          or node.name in banned):
                found.append('function form')
        elif kind == 'Constant' and type(node.value) not in (str, int, float, bool, type(None)):
            found.append('constant')
    if name is not None:
        if len(tree.body) != 1 or type(tree.body[0]).__name__ != 'FunctionDef':
            found.append('not exactly one function definition')
        elif tree.body[0].name != name or [a.arg for a in tree.body[0].args.args] != list(params):
            found.append('wrong name or parameters')
    return found


def module_problems(source, functions):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return ['module does not parse']
    found = _tree_problems(tree, frozen('policy.json'), None, None)
    body = list(tree.body)
    if body and type(body[0]).__name__ == 'Expr' and isinstance(getattr(body[0], 'value', None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    names = {b.name: [a.arg for a in b.args.args] for b in body if type(b).__name__ == 'FunctionDef'}
    if len(names) != len(body) or names != {k: list(v) for k, v in functions.items()}:
        found.append('module is not the docstring plus the frozen functions')
    return found


# ---- running code in the evaluator worker ----

def _run(payload, seed):
    try:
        return sandbox.run(payload, seed, worker=EVAL_WORKER)
    except sandbox.SandboxUnavailable as exc:
        raise EvaluatorUnavailable(str(exc)) from None


def expected_tag(expect):
    if 'r' in expect:
        return {'value': EW.tag(json.loads(expect['r']))}
    return {'raised': expect['x']}


def outcome_ok(out, expect):
    if out.get('unsupported') or out.get('mutated') or out.get('shares_input'):
        return False
    got = {k: out[k] for k in ('value', 'raised') if k in out}
    if got != expected_tag(expect):
        return False
    if 'calls' in expect:
        return out.get('log') == [EW.key_of(json.loads(c)) for c in expect['calls']]
    return True


def run_rows(units, rows, expects, alias, *, count_only=False):
    """{'pass', 'failed': [indexes], 'runs': [...]}: seed 0, then seed 1 when seed 0 passed every row."""
    payload = {'builtins': frozen('policy.json')['builtins'], 'units': units, 'rows': rows, 'alias': alias}
    first = _run(payload, 0)
    runs = [{k: first.get(k) for k in ('seed', 'status', 'cpu_seconds', 'wall_seconds', 'reason')}]
    if first['status'] != 'ok':
        return {'pass': False, 'failed': list(range(len(rows))), 'runs': runs, 'reason': first['status']}
    failed = [i for i, (o, e) in enumerate(zip(first['rows'], expects)) if not outcome_ok(o, e)]
    if failed or count_only:
        return {'pass': not failed, 'failed': failed, 'runs': runs, 'reason': 'rows' if failed else None}
    second = _run(payload, 1)
    runs.append({k: second.get(k) for k in ('seed', 'status', 'cpu_seconds', 'wall_seconds', 'reason')})
    if second['status'] != 'ok' or second['rows'] != first['rows']:
        return {'pass': False, 'failed': [], 'runs': runs, 'reason': 'seed 1 differs'}
    return {'pass': True, 'failed': [], 'runs': runs, 'reason': None}


def parse_header(record):
    """(ticket dict, op, accepted core or None) or None when the record is not a frozen record."""
    m = HEAD.match(record) if isinstance(record, str) else None
    if m is None:
        return None
    t = ticket(m.group(1), int(m.group(2)))
    if t is None:
        return None
    op = m.group(3)
    if op == 'core':
        return (t, op, None) if record == t['core_record'] else None
    prefix = t['adapter_record_prefix']
    if not record.startswith(prefix) or len(record) == len(prefix):
        return None
    return t, op, record[len(prefix):]


def _units(t, op, value, core_source):
    core = t['core']
    units = []
    if op == 'core':
        units.append({'id': 'core', 'source': value})
    else:
        units.append({'id': 'core', 'source': core_source})
        units.append({'id': 'adapter', 'source': value, 'binds': core['name']})
    return units


def judge_candidate(record, value):
    """The evaluator's verdict of one candidate against its exact recorded input: accepted or check_rejected, with
    the reason. Not consulting any executor flag. Cached by (record, value)."""
    key = 'j:' + sha(json.dumps([record, value]))
    if key in _CACHE:
        return _CACHE[key]
    parsed = parse_header(record)
    if parsed is None:
        out = {'verdict': 'check_rejected', 'reason': 'record is not a frozen record'}
    elif not isinstance(value, str):
        out = {'verdict': 'check_rejected', 'reason': 'value is not a string'}
    else:
        t, op, core_source = parsed
        f = t[op]
        problems = policy_problems(value, f['name'], f['params'])
        if problems:
            out = {'verdict': 'check_rejected', 'reason': 'policy: ' + '; '.join(problems[:3])}
        elif op == 'adapter' and policy_problems(core_source, t['core']['name'], t['core']['params']):
            out = {'verdict': 'check_rejected', 'reason': 'the record carries a core that breaks the policy'}
        else:
            rows = frozen('tier_a.json')[f"{t['ticket']}{t['revision']}.{op}"]
            sent = []
            for r in rows:
                row = {'unit': 'core' if op == 'core' else 'adapter', 'fn': f['name'], 'args': r['args']}
                if op == 'adapter':
                    row.update({'core': 'stub', 'stub': r['stub']} if r['kind'] == 'stub' else {'core': 'recorded'})
                sent.append(row)
            res = run_rows(_units(t, op, value, core_source), sent, [r['expect'] for r in rows],
                           bool(t['alias_check']))
            out = {'verdict': 'accepted' if res['pass'] else 'check_rejected',
                   'reason': None if res['pass'] else f"A tier: {res['reason']} {[rows[i]['id'] for i in res['failed'][:5]]}",
                   'runs': res['runs']}
    _CACHE[key] = out
    return out


# ---- H tier ----

def heldout():
    if 'heldout' not in _CACHE:
        _CACHE['heldout'] = json.loads((HERE / 'heldout.json').read_text(encoding='utf-8'))
    return _CACHE['heldout']


def h_key(t, op):
    return f"{t['ticket']}{t['revision']}.{op}" if t['ticket'] == 'A' else f"{t['ticket']}.{op}"


def h_vectors(key):
    if 'hv:' + key not in _CACHE:
        entry = heldout()['domains'][key]
        inputs = H.domain(key)
        if len(inputs) != entry['cardinality'] or sha(json.dumps(inputs, sort_keys=True, separators=(',', ':'))) != \
                entry['inputs_sha256']:
            raise EvaluatorUnavailable(f'H domain {key} does not match its frozen digest')
        text = zlib.decompress(base64.b64decode(entry['expected_zlib_b64'])).decode()
        if sha(text) != entry['expected_sha256']:
            raise EvaluatorUnavailable(f'H expected outcomes for {key} do not match their digest')
        expects = [{'r': v[2:]} if v.startswith('r:') else {'x': v[2:]} for v in json.loads(text)]
        _CACHE['hv:' + key] = (inputs, expects)
    return _CACHE['hv:' + key]


def reference_source(t, name):
    rel = f"{t['ticket']}_rev{t['revision']}.py" if t['ticket'] == 'A' else f"{t['ticket']}.py"
    text = (HERE / 'ref1' / rel).read_text(encoding='utf-8')
    tree = ast.parse(text)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ''.join(text.splitlines(keepends=True)[fn.lineno - 1:fn.end_lineno])


def h_tier(t, op, value, core_source=None):
    """H verdict of one function: every input of its frozen domain, chunked, both seeds. For an adapter, core_source
    is the core it runs with (the accepted core, or the reference core when the caller asks for that report)."""
    key = h_key(t, op)
    cache = 'h:' + sha(json.dumps([key, value, core_source]))
    if cache in _CACHE:
        return _CACHE[cache]
    if policy_problems(value, t[op]['name'], t[op]['params']):
        out = {'pass': False, 'failed': None, 'total': H.CARDINALITY[key], 'reason': 'policy'}
        _CACHE[cache] = out
        return out
    inputs, expects = h_vectors(key)
    units = _units(t, op, value, core_source)
    unit = 'core' if op == 'core' else 'adapter'
    failed, runs, first = 0, [], []
    for start in range(0, len(inputs), CHUNK):
        rows = [{'unit': unit, 'fn': t[op]['name'], 'args': a, 'core': 'real'} for a in inputs[start:start + CHUNK]]
        res = run_rows(units, rows, expects[start:start + CHUNK], bool(t['alias_check']))
        runs += res['runs']
        if not res['pass']:
            failed += max(1, len(res['failed']))
            first += [start + i for i in res['failed'][:3]]
    out = {'pass': failed == 0, 'failed': failed, 'total': len(inputs), 'key': key, 'chunks': len(runs),
           'first_failures': [inputs[i] for i in first[:3]],
           'max_cpu_seconds': max((r['cpu_seconds'] or 0) for r in runs),
           'max_wall_seconds': max((r['wall_seconds'] or 0) for r in runs)}
    _CACHE[cache] = out
    return out


def candidate_h(record, value):
    """H for a candidate as recorded (an adapter runs with the core its record carries)."""
    parsed = parse_header(record)
    if parsed is None or not isinstance(value, str):
        return None
    t, op, core_source = parsed
    return h_tier(t, op, value, core_source)


# ---- captures and memo provenance ----

def capture_lines(capture_record, ids):
    """(kind, detail, lines) of a preserved capture: kind 'ok' with the parsed reply lines, 'wire' with the reason, or
    'call_failed' / 'missing'. Uses g3b's executor-free reply parser."""
    G = g3b()
    kind, detail = G.capture_reply(capture_record)
    if kind != 'ok':
        return ('wire' if kind == 'rejected' else kind), detail, {}
    parsed = G.parse_reply(detail, ids)
    if parsed['rejection'] is not None:
        return 'wire', parsed['rejection'], {}
    return 'ok', None, parsed['lines']


def read_capture_file(ws, run_dir, receipt):
    path = Path(ws) / run_dir / 'captures' / f'{receipt}.done'
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get('receipt') != receipt:
        return None
    return {'exit_code': record.get('exit_code'), 'start_failed': bool(record.get('start_failed')),
            'stdout_b64': record.get('stdout_b64')}


def provenance_value(ws, provenance, job, refs_text=None):
    """The value line for job in the capture a memo entry's provenance names, or None. When refs_text is given the
    provenance packet must have carried exactly that record for the job."""
    capture = read_capture_file(ws, provenance.get('run_dir', ''), provenance.get('receipt', ''))
    if capture is None:
        return None
    kind, _, lines = capture_lines(capture, _packet_ids(ws, provenance))
    line = lines.get(job) if kind == 'ok' else None
    return line[1] if line and line[0] == 'value' else None


def _packet_ids(ws, provenance):
    path = Path(ws) / provenance['run_dir'] / 'captures' / f"{provenance['receipt']}.request.json"
    try:
        request = json.loads(path.read_text(encoding='utf-8'))
        return list(request['ids'])
    except (OSError, ValueError, KeyError, TypeError):
        return [provenance.get('job')]


# ---- delivered packages ----

def assemble(t, core, adapter):
    data = t['module_source'].encode('utf-8')
    (cs, ce), (a0, a1) = t['spans'][t['core']['name']], t['spans'][t['adapter']['name']]

    def body(x):
        b = x.encode('utf-8')
        return b if b.endswith(b'\n') else b + b'\n'
    return (data[:cs] + body(core) + data[ce:a0] + body(adapter) + data[a1:]).decode('utf-8')


def evaluate_package(dest, revisions, accepted):
    """Errors (empty when the package is correct) and per-tier details for one delivered package.

    dest: the delivery directory. revisions: {ticket: ticket revision the delivery must cite}. accepted: {node id:
    accepted candidate source} as the gate derived it from preserved captures and its own verdicts (never from the
    executor's flags). Gate conditions: every module byte-identical to the original with the two spans replaced by
    the accepted sources (M1); each function passes A against its exact record; the module passes I; the core passes H
    and the adapter passes H with the accepted core; the patch equals this evaluator's own rendering; provenance.json
    cites the revisions. Reported apart: the adapter on H with the reference core (M4)."""
    dest = Path(dest)
    errors, detail = [], {'A': {}, 'I': {}, 'H': {}, 'H_reference_core': {}}
    files = {}
    for name in TICKETS:
        t = ticket(name, revisions[name])
        path = dest / t['module']
        if not path.exists():
            errors.append(f'{t["module"]} is missing')
            continue
        delivered = path.read_bytes().decode('utf-8')
        files[t['module']] = delivered
        core, adapter = accepted.get('core_' + name), accepted.get('adapter_' + name)
        if not isinstance(core, str) or not isinstance(adapter, str):
            errors.append(f'no accepted candidate for ticket {name}')
            continue
        if assemble(t, core, adapter) != delivered:
            errors.append(f'{t["module"]} is not the original with the accepted candidates inserted byte for byte')
        a_core = judge_candidate(t['core_record'], core)
        a_adapter = judge_candidate(t['adapter_record_prefix'] + core, adapter)
        detail['A'][name] = {'core': a_core['verdict'], 'adapter': a_adapter['verdict']}
        if a_core['verdict'] != 'accepted' or a_adapter['verdict'] != 'accepted':
            errors.append(f'ticket {name} fails the A tier: {a_core.get("reason") or a_adapter.get("reason")}')
        functions = {t['core']['name']: t['core']['params'], t['adapter']['name']: t['adapter']['params']}
        if module_problems(delivered, functions):
            errors.append(f'{t["module"]} breaks the module policy')
        else:
            rows = frozen('tier_i.json')[f'{name}{t["revision"]}']
            res = run_rows([{'id': 'module', 'source': delivered}],
                           [{'unit': 'module', 'fn': r['fn'], 'args': r['args']} for r in rows],
                           [r['expect'] for r in rows], bool(t['alias_check']))
            detail['I'][name] = {'pass': res['pass'], 'rows': len(rows)}
            if not res['pass']:
                errors.append(f'{t["module"]} fails the I tier')
        hc = h_tier(t, 'core', core)
        ha = h_tier(t, 'adapter', adapter, core)
        hr = h_tier(t, 'adapter', adapter, reference_source(t, t['core']['name']))
        detail['H'][name] = {'core': _h_brief(hc), 'adapter_with_accepted_core': _h_brief(ha)}
        detail['H_reference_core'][name] = _h_brief(hr)
        if not hc['pass'] or not ha['pass']:
            errors.append(f'ticket {name} fails the H tier')
    patch_path = dest / 'repair.patch'
    if not patch_path.exists():
        errors.append('repair.patch is missing')
    elif len(files) == 4:
        mine = ''.join(''.join(difflib.unified_diff(
            ticket(n, revisions[n])['module_source'].splitlines(keepends=True),
            files[ticket(n, revisions[n])['module']].splitlines(keepends=True),
            fromfile='a/' + ticket(n, revisions[n])['module'], tofile='b/' + ticket(n, revisions[n])['module']))
            for n in TICKETS)
        if patch_path.read_bytes().decode('utf-8') != mine:
            errors.append('repair.patch is not the unified diff of the originals and the delivered modules')
    try:
        prov = json.loads((dest / 'provenance.json').read_text(encoding='utf-8'))
        if {n: prov['tickets'][n]['ticket_revision'] for n in TICKETS} != revisions:
            errors.append('provenance.json cites other ticket revisions')
        if any(prov['modules'][n]['sha256'] != sha(files.get(prov['modules'][n]['file'], '')) for n in TICKETS):
            errors.append('provenance.json binds other module bytes')
        if 'not independently discovered bug reports' not in prov.get('note', ''):
            errors.append('provenance.json lacks the seeded-defect statement')
    except (OSError, ValueError, KeyError, TypeError):
        errors.append('provenance.json is missing or malformed')
    if not (dest / 'verification.md').exists() or not (dest / 'manifest.json').exists():
        errors.append('verification.md or manifest.json is missing')
    return {'verified': not errors, 'errors': errors, 'detail': detail}


def _h_brief(h):
    return {k: h.get(k) for k in ('pass', 'failed', 'total', 'chunks', 'max_cpu_seconds', 'max_wall_seconds')}
