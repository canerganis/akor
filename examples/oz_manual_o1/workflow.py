"""repair-handoff-20/v1 runtime: the registered host operations, the per-job code checks and the frozen-file loader.

This is the executor side of the O1 gate G3c-O1 (docs/design/o1-real-workflow-2026-10-23/). It reads only the frozen
pack (repair-handoff-20-v1/: tickets, policy, A-tier and I-tier rows, workflow.json, graph.json); reference
implementations and held-out data live in evaluator/ and are never read here.

Model jobs return one Python function as a JSON string. The checks pinned to both model operations are, in order:
json_type string, o1_source (at most 4,096 UTF-8 bytes of decoded source, apart from the wire limit), o1_policy (the
AST policy, job-bound: the frozen name and parameters come from the job's own record) and o1_tier_a (the A tier run in
the confined worker with hash seeds 0 and 1, job-bound: rows are selected by the header of the job's own record, and a
record that is not the frozen one for its ticket, revision and operation fails). A verifier that cannot run raises
Unavailable: the candidate awaits checks and no model attempt is consumed.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from oz import Error  # noqa: E402
from oz_accept import REGISTRY, Check, Unavailable  # noqa: E402
from oz_flow import HostError, HostOp, ModelOp  # noqa: E402
import sandbox  # noqa: E402
import sandbox_worker  # noqa: E402

FROZEN = HERE / 'repair-handoff-20-v1'
WORKFLOW_ID = 'repair-handoff-20/v1'
TICKETS = ('A', 'B', 'C', 'D')
HEADER = re.compile(r'O1 repair ticket\nticket: ([A-Z])\nrevision: ([0-9]+)\nop: repair_(core|adapter)@1\n')
PROVENANCE_NOTE = ('The defects were seeded on purpose in a purpose-built utility package; they are not independently '
                   'discovered bug reports. The patch is delivered unapplied.')
_CACHE: dict = {}
VERDICT_LOG: list = []  # diagnostics only: (value sha256, record sha256, op, verdict detail); never a verdict source


def load(name: str):
    if name not in _CACHE:
        _CACHE[name] = json.loads((FROZEN / name).read_text(encoding='utf-8'))
    return _CACHE[name]


def spec() -> dict:
    return load('workflow.json')


def policy() -> dict:
    return load('policy.json')


def sha(text) -> str:
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode('utf-8')).hexdigest()


def ticket_file(name: str, revision: int) -> Path:
    files = spec()['ticket_files']
    key = f'{name}.rev{revision}'
    if key not in files:
        raise HostError(f'no frozen ticket {key}')
    return FROZEN / files[key]


def ticket(name: str, revision: int) -> dict:
    key = f'ticket:{name}:{revision}'
    if key not in _CACHE:
        _CACHE[key] = json.loads(ticket_file(name, revision).read_text(encoding='utf-8'))
    return _CACHE[key]


def parse_record(text) -> tuple:
    """(ticket dict, op, accepted core source or None) of a model record, or HostError when the record is not the
    frozen record of a known ticket, revision and operation."""
    if not isinstance(text, str):
        raise HostError('a record is text')
    m = HEADER.match(text)
    if m is None:
        raise HostError('the record has no frozen header')
    t = ticket(m.group(1), int(m.group(2)))
    op = m.group(3)
    if op == 'core':
        if text != t['core_record']:
            raise HostError('the record is not the frozen core record of its ticket and revision')
        return t, op, None
    prefix = t['adapter_record_prefix']
    if not text.startswith(prefix) or len(text) == len(prefix):
        raise HostError('the record is not the frozen adapter record of its ticket and revision')
    return t, op, text[len(prefix):]


# ---- the per-job checks ----

def _op_param(spec_):
    if set(spec_) - {'check', 'version', 'op'} or spec_.get('op') not in ('core', 'adapter'):
        raise Error(f'check {spec_["check"]} takes op: core or adapter')


def _no_params(spec_):
    if set(spec_) - {'check', 'version'}:
        raise Error(f'check {spec_["check"]} takes no parameters')


def _record_of(inputs):
    texts = inputs.texts
    if len(texts) != 1:
        raise HostError('a repair job has exactly one record reference')
    return parse_record(texts[0])


def source_ok(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return len(value.encode('utf-8')) <= policy()['max_source_bytes']
    except UnicodeEncodeError:
        return False


def function_of(t: dict, op: str) -> tuple:
    f = t[op]
    return f['name'], f['params']


def check_policy(value, spec_, inputs) -> bool:
    try:
        t, op, _ = _record_of(inputs)
    except HostError:
        return False
    if op != spec_['op'] or not source_ok(value):
        return False
    name, params = function_of(t, op)
    return not sandbox_worker.check_function(value, name, params, policy())


def tier_a_payload(t: dict, op: str, candidate: str, core_source: str | None) -> tuple:
    """(payload, expected rows) for the A tier of one job; expected values stay in this process."""
    rows = load('tier_a.json')[f"{t['ticket']}{t['revision']}.{op}"]
    core, core_params = function_of(t, 'core')
    if op == 'core':
        units = [{'id': 'core', 'kind': 'function', 'source': candidate, 'name': core, 'params': core_params}]
        sent = [{'unit': 'core', 'fn': core, 'args': r['args']} for r in rows]
    else:
        name, params = function_of(t, 'adapter')
        units = [{'id': 'core', 'kind': 'function', 'source': core_source, 'name': core, 'params': core_params},
                 {'id': 'adapter', 'kind': 'function', 'source': candidate, 'name': name, 'params': params,
                  'binds': core}]
        sent = []
        for r in rows:
            row = {'unit': 'adapter', 'fn': name, 'args': r['args']}
            row.update({'core': 'stub', 'stub': r['stub']} if r['kind'] == 'stub' else {'core': 'recorded'})
            sent.append(row)
    payload = {'policy': policy(), 'units': units, 'rows': sent, 'alias': bool(t['alias_check'])}
    return payload, [r['expect'] for r in rows]


def row_ok(out: dict, expect: dict) -> bool:
    if 'bad' in out or out.get('mut') or out.get('alias'):
        return False
    if {k: out[k] for k in ('r', 'x') if k in out} != {k: expect[k] for k in ('r', 'x') if k in expect}:
        return False
    return 'calls' not in expect or out.get('calls') == expect['calls']


def judge(payload: dict, expected: list) -> dict:
    """Run a payload under seeds 0 and 1 and compare with the expected rows in this process.
    {'pass': bool, 'reason': str, 'runs': [...]}; raises sandbox.SandboxUnavailable for a verifier failure."""
    first = sandbox.run(payload, 0)
    runs = [{k: first.get(k) for k in ('seed', 'status', 'wall_seconds', 'cpu_seconds', 'reason')}]
    if first['status'] != 'ok':
        return {'pass': False, 'reason': first['status'] + ': ' + str(first.get('reason') or first.get('reasons')),
                'runs': runs}
    failed = [i for i, (out, exp) in enumerate(zip(first['rows'], expected)) if not row_ok(out, exp)]
    if failed or len(first['rows']) != len(expected):
        return {'pass': False, 'reason': f'rows failed: {failed[:8]}', 'runs': runs}
    second = sandbox.run(payload, 1)
    runs.append({k: second.get(k) for k in ('seed', 'status', 'wall_seconds', 'cpu_seconds', 'reason')})
    if second['status'] != 'ok' or second['rows'] != first['rows']:
        return {'pass': False, 'reason': 'hash seed 1 differs from seed 0', 'runs': runs}
    return {'pass': True, 'reason': None, 'runs': runs}


def check_tier_a(value, spec_, inputs) -> bool:
    try:
        t, op, core_source = _record_of(inputs)
    except HostError:
        return False
    if op != spec_['op'] or not check_policy(value, spec_, inputs):
        return False
    payload, expected = tier_a_payload(t, op, value, core_source)
    try:
        result = judge(payload, expected)
    except sandbox.SandboxUnavailable as exc:
        raise Unavailable(str(exc)[:150]) from None
    VERDICT_LOG.append({'value_sha256': sha(value), 'record_sha256': sha(inputs.texts[0]), 'op': op,
                        'ticket': f"{t['ticket']}{t['revision']}", 'pass': result['pass'], 'reason': result['reason']})
    return result['pass']


CHECKS = dict(REGISTRY)
CHECKS.update({c.name: c for c in (
    Check('o1_source', 1, False, _no_params, lambda v, s, i: source_ok(v)),
    Check('o1_policy', 1, True, _op_param, check_policy),
    Check('o1_tier_a', 1, True, _op_param, check_tier_a),
)})


# ---- host operations ----

def op_snapshot(inputs, ctx):
    names = inputs['tickets']
    if names != list(TICKETS):
        raise HostError('snapshot names must be the frozen ticket set')
    out = {'tickets': {}, 'core_records': {}}
    for name in names:
        s = ctx.read_source(name, FROZEN / spec()['sources'][name])
        try:
            t = json.loads(s['bytes'].decode('utf-8'))
        except ValueError:
            raise HostError(f'ticket {name} is not JSON') from None
        if t.get('ticket') != name or ticket(name, t.get('revision'))['core_record'] != t.get('core_record'):
            raise HostError(f'ticket {name} is not a frozen ticket revision')
        out['tickets'][name] = {'source_revision': s['revision'], 'sha256': s['sha256'], 'ticket': t}
        out['core_records'][name] = t['core_record']
    return out


def op_adapter_context(inputs, ctx):
    name, core = inputs['ticket'], inputs['core']
    if name not in TICKETS or not isinstance(core, str) or not core:
        raise HostError('an adapter context needs a ticket name and the accepted core source')
    t = inputs['snapshot']['tickets'][name]['ticket']
    return {'ticket': name, 'record': t['adapter_record_prefix'] + core, 'core_sha256': sha(core)}


def op_join_contexts(inputs, ctx):
    contexts = inputs['contexts']
    if [c.get('ticket') for c in contexts] != list(TICKETS):
        raise HostError('one adapter context per ticket, in ticket order')
    return {c['ticket']: c['record'] for c in contexts}


def _insert(source: str) -> bytes:
    data = source.encode('utf-8')
    return data if data.endswith(b'\n') else data + b'\n'


def assemble_module(t: dict, core: str, adapter: str) -> str:
    """The original module bytes with the two declared spans replaced by the accepted sources, unchanged."""
    data = t['module_source'].encode('utf-8')
    (cs, ce), (as_, ae) = t['spans'][t['core']['name']], t['spans'][t['adapter']['name']]
    if not ce <= as_:
        raise HostError('the declared spans overlap')
    return (data[:cs] + _insert(core) + data[ce:as_] + _insert(adapter) + data[ae:]).decode('utf-8')


def op_assemble(inputs, ctx):
    snap, cores, adapters = inputs['snapshot'], inputs['cores'], inputs['adapters']
    if len(cores) != 4 or len(adapters) != 4 or any(not isinstance(x, str) for x in cores + adapters):
        raise HostError('assembly needs four accepted cores and four accepted adapters')
    modules = {}
    for name, core, adapter in zip(TICKETS, cores, adapters):
        t = snap['tickets'][name]['ticket']
        text = assemble_module(t, core, adapter)
        modules[name] = {'file': t['module'], 'text': text, 'sha256': sha(text), 'ticket_revision': t['revision'],
                         'functions': {t['core']['name']: sha(core), t['adapter']['name']: sha(adapter)},
                         'sources': {t['core']['name']: core, t['adapter']['name']: adapter}}
    return {'modules': modules}


def i_payload(t: dict, text: str) -> tuple:
    rows = load('tier_i.json')[f"{t['ticket']}{t['revision']}"]
    functions = {t['core']['name']: t['core']['params'], t['adapter']['name']: t['adapter']['params']}
    payload = {'policy': policy(), 'units': [{'id': 'module', 'kind': 'module', 'source': text,
                                              'functions': functions}],
               'rows': [{'unit': 'module', 'fn': r['fn'], 'args': r['args']} for r in rows],
               'alias': bool(t['alias_check'])}
    return payload, [r['expect'] for r in rows]


def op_integration(inputs, ctx):
    snap, package = inputs['snapshot'], inputs['package']
    out = {}
    for name in TICKETS:
        t = snap['tickets'][name]['ticket']
        module = package['modules'][name]
        if module['sha256'] != sha(module['text']) or module['ticket_revision'] != t['revision']:
            raise HostError(f'module {name} does not match its record')
        payload, expected = i_payload(t, module['text'])
        try:
            result = judge(payload, expected)
        except sandbox.SandboxUnavailable as exc:
            raise HostError('integration verifier unavailable: ' + str(exc)[:120]) from None
        if not result['pass']:
            raise HostError(f'integration rows failed for {name}: {result["reason"]}')
        out[name] = {'sha256': module['sha256'], 'ticket_revision': t['revision'], 'rows': len(expected),
                     'passed': len(expected), 'seeds': [0, 1]}
    return {'tier': 'I', 'modules': out}


def _same_package(package, integration):
    for name in TICKETS:
        m = package['modules'][name]
        r = integration['modules'].get(name, {})
        if r.get('sha256') != m['sha256'] or r.get('passed') != r.get('rows'):
            raise HostError(f'integration evidence does not bind module {name}')


def render_patch(snap, package) -> str:
    chunks = []
    for name in TICKETS:
        t = snap['tickets'][name]['ticket']
        new = package['modules'][name]['text']
        chunks += difflib.unified_diff(t['module_source'].splitlines(keepends=True), new.splitlines(keepends=True),
                                       fromfile='a/' + t['module'], tofile='b/' + t['module'])
    return ''.join(chunks)


def op_render_patch(inputs, ctx):
    _same_package(inputs['package'], inputs['integration'])
    return render_patch(inputs['snapshot'], inputs['package'])


def provenance_doc(snap, package, integration) -> dict:
    return {'schema': 'akor.o1-provenance/1', 'workflow': WORKFLOW_ID, 'note': PROVENANCE_NOTE,
            'tickets': {n: {'source_revision': snap['tickets'][n]['source_revision'],
                            'source_sha256': snap['tickets'][n]['sha256'],
                            'ticket_revision': snap['tickets'][n]['ticket']['revision']} for n in TICKETS},
            'modules': {n: {'file': package['modules'][n]['file'], 'sha256': package['modules'][n]['sha256'],
                            'functions': package['modules'][n]['functions']} for n in TICKETS},
            'integration': integration['modules']}


def report_text(doc) -> str:
    lines = [f'# Repair package ({WORKFLOW_ID})', '', doc['note'], '',
             '| Ticket | Revision | Module | sha256 | Integration rows |', '|---|---|---|---|---|']
    for n in TICKETS:
        m, i = doc['modules'][n], doc['integration'][n]
        lines.append(f"| {n} | {doc['tickets'][n]['ticket_revision']} | {m['file']} | {m['sha256']} | "
                     f"{i['passed']} of {i['rows']}, seeds 0 and 1 |")
    lines += ['', 'Each function in the package is the exact text of an accepted model candidate; acceptance ran the '
                  'frozen A-tier rows in the confined worker. The integration rows ran on these exact module bytes.']
    return '\n'.join(lines) + '\n'


def op_render_report(inputs, ctx):
    snap, package, integration = inputs['snapshot'], inputs['package'], inputs['integration']
    _same_package(package, integration)
    doc = provenance_doc(snap, package, integration)
    return {'verification.md': report_text(doc), 'provenance.json': json.dumps(doc, indent=1, sort_keys=True) + '\n'}


def apply_patch(originals: dict, patch: str) -> dict:
    """{file: text} after applying a unified diff to {file: text}; HostError on any mismatch (independent of
    difflib's writer)."""
    out = dict(originals)
    lines = patch.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        if not lines[i].startswith('--- a/') or i + 1 >= len(lines) or not lines[i + 1].startswith('+++ b/'):
            raise HostError(f'patch line {i + 1} is not a file header')
        name = lines[i + 1][6:].rstrip('\r\n')
        if lines[i][6:].rstrip('\r\n') != name or name not in out:
            raise HostError(f'patch names an unknown file {name!r}')
        old = out[name].splitlines(keepends=True)
        new, cursor = [], 0
        i += 2
        while i < len(lines) and lines[i].startswith('@@'):
            m = re.match(r'@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@', lines[i])
            if m is None:
                raise HostError('bad hunk header')
            start = int(m.group(1)) - (0 if m.group(2) == '0' else 1)
            want_old = 1 if m.group(2) is None else int(m.group(2))
            want_new = 1 if m.group(4) is None else int(m.group(4))
            if start < cursor:
                raise HostError('hunks out of order')
            new += old[cursor:start]
            cursor = start
            i += 1
            while want_old or want_new:
                if i >= len(lines) or lines[i][:1] not in (' ', '-', '+'):
                    raise HostError('a hunk is shorter than its header says')
                tag, body = lines[i][0], lines[i][1:]
                if tag in ' -':
                    if cursor >= len(old) or old[cursor] != body or not want_old:
                        raise HostError(f'patch context does not match {name}')
                    cursor += 1
                    want_old -= 1
                if tag in ' +':
                    if not want_new:
                        raise HostError('a hunk is longer than its header says')
                    new.append(body)
                    want_new -= 1
                i += 1
        new += old[cursor:]
        out[name] = ''.join(new)
    return out


def op_verify_package(inputs, ctx):
    """Independent package check: the patch rebuilds the package from the snapshot, the report and provenance bind the
    same bytes, the integration evidence covers them, and every cited ticket is still the current source revision."""
    snap, package, integration, patch, report = (inputs[k] for k in ('snapshot', 'package', 'integration', 'patch',
                                                                     'report'))
    _same_package(package, integration)
    originals = {snap['tickets'][n]['ticket']['module']: snap['tickets'][n]['ticket']['module_source']
                 for n in TICKETS}
    rebuilt = apply_patch(originals, patch)
    try:
        doc = json.loads(report['provenance.json'])
    except (ValueError, KeyError, TypeError):
        raise HostError('provenance.json is missing or not JSON') from None
    if doc != json.loads(json.dumps(provenance_doc(snap, package, integration))):
        raise HostError('provenance.json does not describe this package')
    if report.get('verification.md') != report_text(doc):
        raise HostError('verification.md does not match the provenance')
    files = {}
    for name in TICKETS:
        m = package['modules'][name]
        t = snap['tickets'][name]['ticket']
        if rebuilt[m['file']] != m['text']:
            raise HostError(f'the patch does not rebuild {m["file"]}')
        core, adapter = t['core']['name'], t['adapter']['name']
        if assemble_module(t, m['sources'][core], m['sources'][adapter]) != m['text'] or any(
                sha(m['sources'][fn]) != m['functions'][fn] or doc['modules'][name]['functions'][fn] != m['functions'][fn]
                for fn in (core, adapter)):
            raise HostError(f'the functions in {m["file"]} are not the bound accepted sources')
        current = ctx.read_source(name)
        if current['revision'] != snap['tickets'][name]['source_revision'] or current['sha256'] != \
                snap['tickets'][name]['sha256'] or t['revision'] != m['ticket_revision']:
            raise HostError(f'ticket {name} is no longer the current source revision')
        files[m['file']] = m['text']
    files['repair.patch'] = patch
    files['verification.md'] = report['verification.md']
    files['provenance.json'] = report['provenance.json']
    return {'files': files, 'sha256': {k: sha(v) for k, v in sorted(files.items())}}


def op_publish(inputs, ctx):
    return {'files': inputs['package']['files']}


HOST_OPS = (
    HostOp('host.snapshot', 1, frozenset({'tickets'}), op_snapshot),
    HostOp('host.adapter_context', 1, frozenset({'snapshot', 'core', 'ticket'}), op_adapter_context),
    HostOp('host.join_contexts', 1, frozenset({'contexts'}), op_join_contexts),
    HostOp('host.assemble', 1, frozenset({'snapshot', 'cores', 'adapters'}), op_assemble),
    HostOp('host.integration', 1, frozenset({'snapshot', 'package'}), op_integration),
    HostOp('host.render_patch', 1, frozenset({'snapshot', 'package', 'integration'}), op_render_patch),
    HostOp('host.render_report', 1, frozenset({'snapshot', 'package', 'integration'}), op_render_report),
    HostOp('host.verify_package', 1, frozenset({'snapshot', 'package', 'integration', 'patch', 'report'}),
           op_verify_package),
    HostOp('host.publish', 1, frozenset({'package'}), op_publish, effect='local_publish'),
)


def registry(*, overrides=None) -> dict:
    """The pinned operation registry. overrides replace host implementations (sabotage fixtures only)."""
    s = spec()
    ops = {op.name: op for op in HOST_OPS}
    for name, m in s['model_ops'].items():
        ops[name] = ModelOp(m['name'], m['version'], s['goal'], m['instruction'], tuple(m['checks']), m['memo'])
    ops.update(overrides or {})
    return ops


def graph() -> dict:
    return load('graph.json')


def source_bytes(name: str, revision: int = 1) -> bytes:
    return ticket_file(name, revision).read_bytes()
