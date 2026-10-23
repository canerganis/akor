"""Step 4 harness for inspection-handoff-20/v1 (executor conformance gate): G0 freeze, G2 dry gate, G3 live, G4 baseline.

    python bench/step4/step4.py freeze [--write]                 G0: verify (or write) every frozen digest
    python bench/step4/step4.py dry --workspace DIR             G2: five scenarios, C3/C5 checks, sabotage, zero tokens
    python bench/step4/step4.py live --workspace DIR            G3: five scenarios through claude -p (paid)
    python bench/step4/step4.py baseline --workspace DIR        G4: four no-orchestration calls (paid)
    python bench/step4/step4.py run-flow --workspace DIR --kind K --prefix P --scenario S   one flow invocation

Every scenario runs through oz_flow.run_flow, which sends model stages through oz do (oz1g-selective-v1, durable
runner, per-job checks, memo, quota reservation, admission). The dry gate and the live run share every line except
the adapter (fixture_adapter.py versus examples/claude_cli_adapter.py), the route identity and the memo namespaces.
See docs/design/step4-2026-10-23/plan-frozen.md for the preregistered commands, caps and expected launches.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import evaluator as E  # noqa: E402
import workflow as W  # noqa: E402
from oz import Error  # noqa: E402
from oz_batch import J  # noqa: E402
from oz_flow import Flow, Settings, flow_dir, flow_usage, run_flow, stage_launches  # noqa: E402
from oz_memo import MemoStore  # noqa: E402
from oz_quota import Quota  # noqa: E402
from oz_reply import LANGUAGE, PROTOCOL  # noqa: E402
from oz_runner import read_capture  # noqa: E402
from oz_workspace import initialize  # noqa: E402
import oz_fault  # noqa: E402

KILL = oz_fault.KILL_EXIT
CODE = ('oz.py', 'oz_batch.py', 'oz_reply.py', 'oz_accept.py', 'oz_runtime.py', 'oz_worker.py', 'oz_runner.py',
        'oz_do.py', 'oz_memo.py', 'oz_quota.py', 'oz_flow.py', 'oz_fault.py', 'oz_workspace.py',
        'examples/claude_cli_adapter.py', 'bench/step4/workflow.py', 'bench/step4/evaluator.py',
        'bench/step4/fixture_adapter.py', 'bench/step4/step4.py')
SCENARIOS = ('clean', 'repeat', 'interrupt', 'stale', 'bump')
RERUN: dict = {}  # scenario -> rerun number (the one preregistered model-reply-failure rerun)


def rid(prefix: str, scenario: str) -> str:
    return f'{prefix}-{scenario}' + (f'-r{RERUN[scenario]}' if scenario in RERUN else '')


def ndigest(path: Path) -> str:
    """SHA-256 with CRLF normalized to LF, so a checkout's line-ending conversion does not change identities."""
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def spec():
    return W.load('workflow.json')


# ---- G0: baseline prompts and the freeze ----

def baseline_prompt(variant: str) -> str:
    records = []
    for name in E.NAMES:
        data = W.source_bytes(name, variant)
        records.append({'record': name, 'revision': 2 if variant == 'rev2' and name == 'A' else 1,
                        'sha256': hashlib.sha256(data).hexdigest(), 'text': data.decode('utf-8')})
    lines = [
        'Goal: ' + spec()['goal'], '',
        'Records (the authoritative source revisions; each text is the complete record):',
        J(records), '',
        'Produce the inspection handoff as one JSON object with exactly these keys, in this order:',
        '"schema": "akor.inspection-handoff/1"',
        '"workflow": "inspection-handoff-20/v1"',
        '"acceptance_interval": {"lower":"12.48 mm","upper":"12.52 mm","inclusive":true}',
        '"physical_validation": "not_claimed"',
        '"evidence": ' + json.dumps(W.EVIDENCE),
        '"records": one object per record, in the order given, each with exactly these keys, in this order:',
        '"record": the record name.',
        '"source": {"name": the record name, "revision": its revision, "sha256": its sha256}, copied exactly.',
        '"measurement": {"length", "uncertainty", "n", "method", "basis", "physical_validation"}, each the '
        "record's field value as a string, preserved exactly.",
        '"interval": [length-uncertainty, length+uncertainty], each a string with two decimal places and unit mm; '
        'the string "unknown" if uncertainty is unknown.',
        '"status": "inside" if the entire interval lies within the acceptance interval (inclusive), "outside" '
        'otherwise, "unknown" if uncertainty is unknown.',
        '"missing": the field names among uncertainty, method, basis, in that order, whose value is unknown.',
        '"follow_ups": one {"category":"missing_metadata","field":<name>} per missing field, in that order; then '
        '{"category":"numerical_review"} if status is outside; then {"category":"uncertainty_required"} if the '
        'interval is unknown.',
        'Reply with the JSON object only: no code fence and no explanation.']
    return '\n'.join(lines) + '\n'


BASELINE_SYSTEM = 'You prepare inspection handoffs. Reply with exactly one JSON object and nothing else.\n'


def frozen_files() -> list:
    return sorted(p for p in W.FROZEN.rglob('*') if p.is_file() and p.name != 'freeze.json')


def digests() -> dict:
    return {'frozen': {p.relative_to(ROOT).as_posix(): ndigest(p) for p in frozen_files()},
            'code': {c: ndigest(ROOT / c) for c in CODE}}


def instruction_check() -> list:
    """The model operations must be live2 MAT_D e, b, v exactly as arm H sent them (unchanged instructions)."""
    # A private copy of live2: other harnesses rebind live2.MAT_C in place, the file is the reference.
    sys.path.insert(0, str(ROOT / 'bench' / 'live'))
    from importlib import util
    found = util.spec_from_file_location('_step4_live2', ROOT / 'bench' / 'live' / 'live2.py')
    live2 = util.module_from_spec(found)
    found.loader.exec_module(live2)
    errors = []
    s = spec()
    if s['goal'] != live2.MAT_GOAL:
        errors.append('goal differs from live2.MAT_GOAL')
    for name, code in (('model.extract', 'e'), ('model.bounds', 'b'), ('model.classify', 'v')):
        if s['model_ops'][name]['instruction'] != live2.MAT_D[code].replace("c[N]'s", "the ref's"):
            errors.append(f'{name} instruction differs from live2.MAT_D[{code!r}]')
    for k, name in zip('1234', E.NAMES):
        if W.source_bytes(name) != live2.MAT_C[k].encode('utf-8'):
            errors.append(f'source {name} differs from live2.MAT_C[{k!r}]')
    return errors


def freeze(write=False) -> dict:
    base = W.FROZEN / 'baseline'
    if write:
        base.mkdir(exist_ok=True)
        (base / 'system.txt').write_text(BASELINE_SYSTEM, encoding='utf-8', newline='\n')
        for variant in ('rev1', 'rev2'):
            (base / f'prompt-{variant}.txt').write_text(baseline_prompt(variant), encoding='utf-8', newline='\n')
    current = digests()
    current['digest'] = hashlib.sha256(J(current).encode('utf-8')).hexdigest()
    path = W.FROZEN / 'freeze.json'
    problems = instruction_check()
    for variant in ('rev1', 'rev2'):
        f = base / f'prompt-{variant}.txt'
        if not f.exists() or f.read_text(encoding='utf-8') != baseline_prompt(variant):
            problems.append(f'baseline prompt {variant} is not the generated one')
    if write:
        if problems:
            raise Error('cannot freeze: ' + '; '.join(problems))
        path.write_text(json.dumps(current, indent=1) + '\n', encoding='utf-8', newline='\n')
        return {'frozen': True, 'digest': current['digest'], 'problems': []}
    stored = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    for group in ('frozen', 'code'):
        for name, digest in current[group].items():
            if stored.get(group, {}).get(name) != digest:
                problems.append(f'{name} changed since the freeze')
        for name in set(stored.get(group, {})) - set(current[group]):
            problems.append(f'{name} missing')
    return {'frozen': not problems, 'digest': stored.get('digest'), 'current_digest': current['digest'],
            'problems': problems}


# ---- route, adapters, checks ----

def route(kind: str):
    r = spec()['route' if kind == 'live' else 'fixture_route']
    script = r['adapter_script']
    adapter = f"argv:{J(['python', script])};sha256:{ndigest(ROOT / script)}"
    from oz_batch import SYSTEM
    wire = hashlib.sha256(SYSTEM.encode('utf-8')).hexdigest()[:16]
    parser = f"{r['parser']}@sha256:{ndigest(ROOT / 'oz_reply.py')[:16]};wire-H-sha256:{wire}"
    return {'effort': r['effort'], 'cli_version': r['cli_version'], 'adapter': adapter, 'parser': parser}, r['model']


def adapter_file(ws: Path, kind: str) -> Path:
    r = spec()['route' if kind == 'live' else 'fixture_route']
    path = ws / f'adapter-{kind}.json'
    path.write_text(json.dumps({'argv': [sys.executable, str(ROOT / r['adapter_script'])],
                                'protocols': [PROTOCOL], 'languages': [LANGUAGE]}), encoding='utf-8')
    return path


def envelope_of(capture: dict | None):
    if not capture or not capture.get('envelope_b64'):
        return None
    try:
        return json.loads(base64.b64decode(capture['envelope_b64']).decode('utf-8'))
    except (ValueError, UnicodeError):
        return None


def response_check(model: str, alias_map: dict):
    """C2: the actual model comes from the retained envelope's modelUsage keys; missing identity or any other model
    refuses every candidate of that call."""
    def check(dispatch):
        capture = read_capture(dispatch['capture_dir'], dispatch['receipt'], dispatch['request_sha256'])
        envelope = envelope_of(capture)
        if envelope is None:
            return 'model identity missing: no retained envelope'
        mu = envelope.get('modelUsage')
        if not isinstance(mu, dict) or not mu:
            return 'model identity missing: envelope has no modelUsage'
        seen = sorted({alias_map.get(k, k) for k in mu})
        return None if seen == [model] else 'unexpected model(s): ' + ', '.join(seen)
    return check


def cli_version() -> str | None:
    claude = shutil.which('claude')
    if claude is None:
        return None
    out = subprocess.run([claude, '--version'], capture_output=True, text=True, timeout=60).stdout.strip()
    return out.split()[0] if out else None


def route_check(kind: str):
    if kind != 'live':
        return None
    want = spec()['route']['cli_version']

    def check():
        found = cli_version()
        return None if found == want else f'claude CLI version {found} != frozen {want}'
    return check


def settings(ws: Path, kind: str, namespace: str, *, quota, registry=None, budget=None, route_fields=None):
    fields, model = route(kind)
    r = spec()['route' if kind == 'live' else 'fixture_route']
    return Settings(workspace=ws, adapter=adapter_file(ws, kind), registry=registry or W.registry(),
                    checks_registry=W.CHECKS, route=route_fields or fields, model=model,
                    memo_store=ws / 'memo.sqlite', namespace=namespace, quota=quota,
                    budget=spec()['budgets']['executor'] if budget is None else budget, budget_scope=ws,
                    route_check=route_check(kind),
                    response_check=response_check(model, spec()['route'].get('alias_map', {}) if kind == 'live'
                                                  else {}),
                    packet_sizes=tuple(spec()['packets']['sizes']),
                    experimental_sizes=tuple(spec()['packets']['experimental_sizes']))


def quota_store(ws: Path, kind: str) -> Quota:
    return Quota(None if kind == 'live' else ws / 'quota.sqlite')


def flow_request(prefix: str, scenario: str, *, request_id: str | None = None) -> dict:
    return {'v': 'oz.flow/1', 'request_id': request_id or rid(prefix, scenario), 'workflow': W.WORKFLOW_ID,
            'workflow_digest': freeze()['current_digest'], 'graph': W.graph(), 'effects': spec()['effects'],
            'deadline_seconds': spec()['deadlines']['scenario_seconds'],
            'call_timeout_seconds': spec()['deadlines']['call_timeout_seconds']}


def namespace(kind: str, prefix: str, scenario: str) -> str:
    entry = next(s for s in spec()['scenarios'] if s['name'] == scenario) if scenario in SCENARIOS else None
    if entry is None or entry['namespace'] == 'own':
        return f'{kind}-' + (rid(prefix, scenario) if entry else f'{prefix}-{scenario}')
    return f'{kind}-' + rid(prefix, entry['namespace'])


def mutation_hook(ws: Path, request_id: str, mutation: str):
    m = spec()['mutations'][mutation]

    def hook(_name):
        f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
        try:
            if any(e['event'] == 'source_revised' for e in f.events()):
                return  # preregistered once; a resumed or regenerated node never mutates again
            f.bump_source(m['source'], (W.FROZEN / m['file']).read_bytes(), reason=f'preregistered mutation {mutation}')
        finally:
            f.close()
    return oz_fault.on(m['hook'], hook)


def run_scenario_flow(ws: Path, kind: str, prefix: str, scenario: str, **options) -> dict:
    """One invocation of one scenario's flow (in-process); the same function serves run-flow (CLI)."""
    entry = next(s for s in spec()['scenarios'] if s['name'] == scenario)
    request = flow_request(prefix, scenario)
    quota = quota_store(ws, kind)
    remove = mutation_hook(ws, request['request_id'], entry['mutation']) if entry['mutation'] else None
    try:
        return run_flow(request, settings(ws, kind, namespace(kind, prefix, scenario), quota=quota, **options))
    finally:
        quota.close()
        if remove:
            remove()


def prepare(ws: Path, kind: str):
    if not (ws / 'oz.json').exists():
        initialize(ws)
    if kind == 'fixture':
        os.environ['OZ_FIXTURE_DIR'] = str(ws / 'fixture')
        (ws / 'fixture').mkdir(exist_ok=True)
    else:
        os.environ['OZ_MODEL'] = spec()['route']['model']


# ---- audits ----

def stage_runs(ws: Path, request_id: str) -> list:
    f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
    try:
        return list(dict.fromkeys(e['details']['run_dir'] for e in f.events() if e['event'] == 'stage_submitted'))
    finally:
        f.close()


def dispatches(ws: Path, request_id: str) -> list:
    out = []
    for rel in stage_runs(ws, request_id):
        for d in stage_launches(ws / rel):
            out.append(dict(d, run_dir=rel, members=[m['id'] for m in json.loads(d['members'])]))
    return sorted(out, key=lambda d: d['created_at'])


def ledger_audit(ws: Path, request_id: str) -> dict:
    """Every physical launch has exactly one ledger call and no ledger call lacks a launch (a recovered capture must
    never be counted as another invocation)."""
    problems, calls = [], 0
    for rel in stage_runs(ws, request_id):
        ledger = ws / rel / 'calls.jsonl'
        starts = {}
        for line in (ledger.read_text(encoding='utf-8').splitlines() if ledger.exists() else ()):
            r = json.loads(line)
            if r.get('event') == 'call_start':
                starts.setdefault(r['batch_id'], set()).add(r['call_id'])
        receipts = {d['receipt'] for d in stage_launches(ws / rel)}
        calls += sum(len(v) for v in starts.values())
        for receipt, ids in starts.items():
            if len(ids) > 1:
                problems.append(f'{rel}: receipt {receipt} counted as {len(ids)} calls')
            if receipt not in receipts:
                problems.append(f'{rel}: ledger call for {receipt} has no journaled launch')
        for receipt in receipts - set(starts):
            problems.append(f'{rel}: launch {receipt} has no ledger call')
    return {'ok': not problems, 'ledger_calls': calls, 'problems': problems}


def fixture_invocations(ws: Path, request_id: str) -> int:
    log = Path(os.environ.get('OZ_FIXTURE_DIR', ws / 'fixture')) / 'invocations.jsonl'
    if not log.exists():
        return 0
    bindings = set()
    for rel in stage_runs(ws, request_id):
        cfg = json.loads((ws / rel / 'oz.json').read_text(encoding='utf-8'))
        from oz import Channel
        bindings.add(Channel.from_snapshot(cfg['channels']['worker']).binding)
    return sum(1 for line in log.read_text(encoding='utf-8').splitlines() if json.loads(line)['binding'] in bindings)


def memo_hits(ws: Path, request_id: str) -> int:
    f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
    try:
        return sum(1 for e in f.events() if e['event'] == 'stage'
                   for m in (e['details'].get('memo') or {}).values() if m['decision'] == 'hit')
    finally:
        f.close()


def audit(ws: Path, kind: str, prefix: str, scenario: str, result: dict) -> dict:
    entry = next(s for s in spec()['scenarios'] if s['name'] == scenario)
    request_id = rid(prefix, scenario)
    expected = W.load('expected.json')
    ds = dispatches(ws, request_id)
    target = result['targets']['inspection_handoff']
    errors = (E.evaluate_package(ws / target['destination'], expected['variants'][scenario],
                                 expected['revisions'][scenario])
              if target['status'] == 'delivered' else ['not delivered'])
    f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
    try:
        deliveries = f.deliveries()
    finally:
        f.close()
    out = {'scenario': scenario, 'request_id': request_id, 'status': result['status'], 'blocker': result['blocker'],
           'launches': len(ds), 'expected_launches': entry['expected_launches'],
           'packets': [len(d['members']) for d in ds], 'expected_packets': entry['expected_packets'],
           'memo_hits': memo_hits(ws, request_id), 'expected_memo_hits': entry['expected_memo_hits'],
           'deliveries': len(deliveries), 'on_time': target.get('on_time'),
           'evaluator': {'verified': not errors, 'errors': errors}, 'ledger': ledger_audit(ws, request_id),
           'accounting': result['accounting']}
    if kind == 'fixture':
        out['fixture_invocations'] = fixture_invocations(ws, request_id)
    # Dispatches that sent a member back to bounded recovery (wire rejection or a failed job check): the plan lets
    # such recorded reply rejections explain extra launches; the strict pass below does not.
    out['reply_rejections'] = sum(1 for d in ds if d['outcome'] and 'pending' in json.loads(d['outcome']).values())
    out['pass'] = (result['status'] == 'delivered' and not errors and out['launches'] == entry['expected_launches']
                   and out['packets'] == entry['expected_packets'] and out['memo_hits'] == entry['expected_memo_hits']
                   and out['deliveries'] == 1 and out['on_time'] and out['ledger']['ok']
                   and (kind != 'fixture' or out['fixture_invocations'] == out['launches']))
    out['pass_with_recorded_rejections'] = out['pass'] or (
        result['status'] == 'delivered' and not errors and out['deliveries'] == 1 and out['on_time']
        and out['ledger']['ok'] and 0 < out['launches'] - entry['expected_launches'] <= out['reply_rejections'])
    return out


def stale_observables(ws: Path, prefix: str) -> dict:
    """C3: what only a correct executor gets right in the stale-input run."""
    request_id = rid(prefix, 'stale')
    f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
    try:
        events = f.events()
        mutation = next(e for e in events if e['event'] == 'source_revised')
        history = [r for r in f.db.execute("SELECT node,generation,cites FROM acceptances WHERE node LIKE '%_A'")]
        deliveries = f.deliveries()
    finally:
        f.close()
    old_a = W.source_bytes('A').decode('utf-8')
    after = [d for d in dispatches(ws, request_id) if d['created_at'] > mutation['at']]
    leaked = [d['receipt'] for d in after if old_a in d['packet']]
    order = [d['members'] for d in after]
    reused = {}
    stage_memos = [e['details'] for e in events if e['event'] == 'stage' and e['seq'] > mutation['seq']]
    first_keys = {}
    for e in events:
        if e['event'] == 'stage' and e['seq'] < mutation['seq']:
            run = ws / e['details']['run_dir']
            for job, ev in _accepted_keys(run).items():
                first_keys[job] = ev
    for st in stage_memos:
        for job, m in (st.get('memo') or {}).items():
            if job[-1] in 'BCD' and job.split('_')[0] in ('extract', 'bounds'):
                reused[job] = {'decision': m['decision'], 'same_inputs': first_keys.get(job) == m['compute_key']}
    old_rows = [dict(r) for r in history if r['node'] in ('extract_A', 'bounds_A')]
    manifest_cites = deliveries[0]['cites'] if deliveries else {}
    checks = {
        'no_old_A_after_mutation': not leaked,
        'singletons_then_classify': order == [['extract_A'], ['bounds_A'], ['classify_A', 'classify_B', 'classify_C',
                                                                             'classify_D']],
        'bcd_reused_by_recorded_identical_input_decision': (
            sorted(reused) == sorted(f'{op}_{n}' for op in ('extract', 'bounds') for n in 'BCD')
            and all(v['decision'] == 'hit' and v['same_inputs'] for v in reused.values())),
        'old_A_history_kept_delivery_cites_rev2': (
            any(json.loads(r['cites']).get('A') == 1 for r in old_rows) and manifest_cites.get('A') == 2)}
    return {'pass': all(checks.values()), 'checks': checks, 'dispatches_after_mutation': order,
            'leaked_receipts': leaked, 'reused': reused}


def _accepted_keys(run: Path) -> dict:
    import sqlite3
    db = sqlite3.connect(str(run / 'inbox.sqlite'))
    try:
        return {r[0]: r[1] for r in db.execute("SELECT job,compute_key FROM candidates WHERE status='accepted'")}
    finally:
        db.close()


# ---- C5 negative checks and sabotage, each on an isolated copy of clean state ----

def copy_of(ws: Path, name: str) -> Path:
    dest = ws.parent / (ws.name + '.copies') / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ws, dest, ignore=shutil.ignore_patterns('*.copies'))
    return dest


def clean_request(prefix):
    return flow_request(prefix, 'clean')


def plan_on(copy: Path, kind: str, prefix: str, *, route_fields=None, ns=None) -> dict:
    quota = quota_store(copy, kind)
    try:
        s = settings(copy, kind, ns or namespace(kind, prefix, 'clean'), quota=quota, route_fields=route_fields)
        return run_flow(clean_request(prefix), s, plan_only=True)
    finally:
        quota.close()


def c5_checks(ws: Path, kind: str, prefix: str, clean_copy: Path) -> dict:
    out = {}
    exp = W.load('expected.json')
    # 1. Byte identity of the artifacts across clean, repeat and interruption; case 5 differs only in revisions.
    files = {}
    for sc in ('clean', 'repeat', 'interrupt', 'bump'):
        res = json.loads((flow_dir(ws, rid(prefix, sc)) / 'execution-record.json').read_text(encoding='utf-8'))
        dest = ws / Path(res['effects'][0]['destination']) if res['effects'] else None
        files[sc] = {n: (dest / n).read_bytes() for n in ('handoff.json', 'handoff.md')} if dest else {}
    same = all(files[sc] == files['clean'] for sc in ('repeat', 'interrupt')) and bool(files['clean'])
    bump_ok = False
    if files.get('bump') and files['clean']:
        a = json.loads(files['bump']['handoff.json'])
        b = json.loads(files['clean']['handoff.json'])
        a['records'][0]['source']['revision'] = b['records'][0]['source']['revision']
        md = files['bump']['handoff.md'].replace(b'A rev 2 sha256', b'A rev 1 sha256')
        bump_ok = a == b and md == files['clean']['handoff.md'] and files['bump'] != files['clean']
    out['byte_identity'] = {'pass': same and bump_ok, 'clean_repeat_interrupt_identical': same,
                            'bump_differs_only_in_revision': bump_ok}
    # 2. Route change: 12 misses, stops before launch (plan-only).
    copy = copy_of(clean_copy, 'c5-route')
    fields, _ = route(kind)
    plan = plan_on(copy, kind, prefix, route_fields=dict(fields, effort='changed-effort'))
    out['route_change'] = {'pass': plan['misses'] == 12 and plan['launched'] == 0, 'misses': plan['misses'],
                           'packets': plan['packets']}
    # 3. Strengthened acceptance-only check on bounds: the 4 retained candidates revalidate on the host, no call.
    copy = copy_of(clean_copy, 'c5-strong')
    quota = quota_store(copy, kind)
    try:
        strong = W.registry(extra_checks={'model.bounds': [{'check': 'max_bytes', 'bytes': 64}]})
        res = run_flow(flow_request(prefix, 'strong'), settings(copy, kind, namespace(kind, prefix, 'clean'),
                                                                quota=quota, registry=strong,
                                                                budget=dict(spec()['budgets']['executor'],
                                                                            max_launches=0)))
    finally:
        quota.close()
    strong_id = f'{prefix}-strong'
    f = Flow(flow_dir(copy, strong_id) / 'flow.sqlite')
    try:
        bounds_memo = [m for e in f.events() if e['event'] == 'stage' and e['details']['op'] == 'bounds'
                       for m in e['details']['memo'].values()]
    finally:
        f.close()
    ev = _stage_checks(copy, strong_id, 'bounds')
    errors = E.evaluate_package(copy / res['targets']['inspection_handoff'].get('destination', 'missing'), 'rev1',
                                exp['revisions']['clean']) if res['status'] == 'delivered' else ['not delivered']
    out['strengthened_check'] = {
        'pass': (res['status'] == 'delivered' and len(dispatches(copy, strong_id)) == 0 and len(bounds_memo) == 4
                 and all(m['decision'] == 'hit' for m in bounds_memo) and not errors
                 and all('max_bytes@1:pass' in c for c in ev.values()) and len(ev) == 4),
        'launches': len(dispatches(copy, strong_id)), 'bounds_checks': ev, 'evaluator_errors': errors}
    # 4. Revocation of one clean bounds_B entry: exactly one miss in the next plan, stopped before launch.
    copy = copy_of(clean_copy, 'c5-revoke')
    store = MemoStore(copy / 'memo.sqlite')
    try:
        revoked = [e['id'] for e in store.entries(namespace(kind, prefix, 'clean'))
                   if e['provenance'].get('job') == 'bounds_B']
        for entry in revoked:
            store.revoke(entry, 'C5 revocation check')
    finally:
        store.close()
    plan = plan_on(copy, kind, prefix)
    missed = [j for st in plan['stages'] for j, m in st['plan']['memo'].items() if m['decision'] != 'hit']
    out['revocation'] = {'pass': plan['misses'] == 1 and missed == ['bounds_B'] and plan['launched'] == 0,
                         'revoked_entries': revoked, 'missed': missed, 'packets': plan['packets']}
    return out


def _stage_checks(ws: Path, request_id: str, op: str) -> dict:
    out = {}
    f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
    try:
        for a in f.latest().values():
            if a['node'].startswith(op + '_'):
                out[a['node']] = a['evidence'].get('checks', [])
    finally:
        f.close()
    return out


def sabotage(ws: Path, prefix: str, clean_copy: Path, interrupt_ws: Path) -> dict:
    """C6: each sabotage must be caught (the gate reports it as failed or refused)."""
    out = {}
    exp = W.load('expected.json')
    # S1: a corrupted rendered value must fail node 19 (no publication).
    copy = copy_of(clean_copy, 'sab-render')

    def corrupt(inputs, ctx):
        text = W.op_render_json(inputs, ctx)
        return text.replace('"status": "outside"', '"status": "inside"', 1)
    reg = W.registry(overrides={'host.render_json': W.HostOp('host.render_json', 1, frozenset({'rows'}), corrupt)})
    quota = quota_store(copy, 'fixture')
    try:
        res = run_flow(flow_request(prefix, 'sabrender'), settings(copy, 'fixture', namespace('fixture', prefix,
                                                                   'clean'), quota=quota, registry=reg))
    finally:
        quota.close()
    out['corrupted_render'] = {'caught': (res['status'] != 'delivered' and (res['blocker'] or {}).get('node')
                                          == 'verify_package'), 'blocker': res['blocker']}
    # S2: an adapter answering classify_A from the old A bytes must not produce a delivery.
    copy = copy_of(clean_copy, 'sab-stale')
    previous = os.environ.get('OZ_FIXTURE_DIR')
    os.environ['OZ_FIXTURE_DIR'] = str(copy / 'fixture')
    (copy / 'fixture' / 'mode.json').write_text(json.dumps({'stale_classify_A': True}), encoding='utf-8')
    quota = quota_store(copy, 'fixture')
    remove = mutation_hook(copy, f'{prefix}-sabstale', 'stale')
    try:
        res = run_flow(flow_request(prefix, 'sabstale'), settings(copy, 'fixture', 'fixture-sabstale', quota=quota))
    finally:
        quota.close()
        remove()
        os.environ['OZ_FIXTURE_DIR'] = previous or ''
    target = res['targets']['inspection_handoff']
    errs = (E.evaluate_package(copy / target['destination'], 'rev2', exp['revisions']['stale'])
            if target['status'] == 'delivered' else ['not delivered'])
    out['stale_classify_A'] = {'caught': bool(errs), 'status': res['status'], 'blocker': res['blocker']}
    # S3: a recovered capture counted as another physical invocation must fail the launch audit.
    copy = copy_of(interrupt_ws, 'sab-replay')
    interrupt_id = rid(prefix, 'interrupt')
    first = dispatches(copy, interrupt_id)[0]
    ledger = copy / first['run_dir'] / 'calls.jsonl'
    start = next(json.loads(x) for x in ledger.read_text(encoding='utf-8').splitlines()
                 if json.loads(x).get('batch_id') == first['receipt'])
    with ledger.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps(dict(start, call_id='replayed-' + start['call_id'])) + '\n')
    a = ledger_audit(copy, interrupt_id)
    out['replayed_capture_counted'] = {'caught': not a['ok'], 'problems': a['problems']}
    # S4: a fixture value offered to the live namespace (forged under the live key) must not be a hit.
    copy = copy_of(clean_copy, 'sab-forge')
    fields, _ = route('fixture')
    live_like = dict(fields, adapter='argv:["python","examples/claude_cli_adapter.py"];sha256:live-sim',
                     cli_version='2.1.306', effort='default')
    plan = plan_on(copy, 'fixture', prefix, route_fields=live_like, ns='live-sim')
    store = MemoStore(copy / 'memo.sqlite')
    try:
        clean = {e['provenance']['job']: e for e in store.entries(namespace('fixture', prefix, 'clean'))}
        live_route = {'adapter': live_like['adapter'], 'model': route('fixture')[1], 'effort': 'default',
                      'cli_version': '2.1.306', 'wire': 'stage-1g', 'parser': live_like['parser']}
        for st in plan['stages']:
            for job, m in st['plan']['memo'].items():
                e = clean[job]
                store.publish('live-sim', m['compute_key'], value=e['value'], stored=e['stored'], route=live_route,
                              checks=e['checks'], verdicts=e['verdicts'], provenance=e['provenance'])
    finally:
        store.close()
    again = plan_on(copy, 'fixture', prefix, route_fields=live_like, ns='live-sim')
    reasons = sorted({r['reason'] for st in again['stages'] for m in st['plan']['memo'].values()
                      for r in (m.get('reason') or []) if isinstance(r, dict)})
    out['fixture_value_offered_to_live'] = {'caught': again['misses'] == 12, 'misses': again['misses'],
                                            'reasons': reasons}
    # Race: a revision change after an early freshness check but before commitment must be refused.
    copy = copy_of(clean_copy, 'race')
    race_id = f'{prefix}-race'
    fired = []

    def race(_name):
        f = Flow(flow_dir(copy, race_id) / 'flow.sqlite')
        try:
            if not fired and f.latest():
                fired.append(f.bump_source('A', W.source_bytes('A'), reason='race fixture'))
        finally:
            f.close()
    remove = oz_fault.on('flow.before_commit', race)
    quota = quota_store(copy, 'fixture')
    try:
        res = run_flow(flow_request(prefix, 'race'), settings(copy, 'fixture', namespace('fixture', prefix, 'clean'),
                                                              quota=quota))
    finally:
        quota.close()
        remove()
    f = Flow(flow_dir(copy, race_id) / 'flow.sqlite')
    try:
        refused = [e for e in f.events() if e['event'] == 'commit_refused']
        cites = f.deliveries()[0]['cites'] if f.deliveries() else {}
    finally:
        f.close()
    out['revision_race'] = {'caught': bool(refused) and res['status'] == 'delivered' and cites.get('A') == 2,
                            'refused': [e['details'] for e in refused][:3], 'delivery_cites': cites}
    return out


# ---- scenario suite ----

def run_interrupt(ws: Path, kind: str, prefix: str) -> list:
    """Hard kills at the preregistered boundaries; each resume is the same command with the same request identity."""
    cmd = [sys.executable, str(Path(__file__).resolve()), 'run-flow', '--workspace', str(ws), '--kind', kind,
           '--prefix', prefix, '--scenario', 'interrupt']
    if 'interrupt' in RERUN:
        cmd += ['--rerun', str(RERUN['interrupt'])]
    exits = []
    for faults, expect in ((['worker.after_capture'], KILL), (['flow.publish.after_manifest'], KILL), ([], 0)):
        env = dict(os.environ, OZ_FAULTS=','.join(faults), PYTHONIOENCODING='utf-8')
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding='utf-8')
        exits.append({'faults': faults, 'exit': proc.returncode, 'expected_exit': expect,
                      'stderr_tail': proc.stderr[-400:] if proc.returncode not in (0, KILL) else ''})
    return exits


def interrupt_observables(ws: Path, prefix: str, exits: list) -> dict:
    interrupt_id = rid(prefix, 'interrupt')
    ds = dispatches(ws, interrupt_id)
    first = ds[0] if ds else None
    unfinished = 0
    if first:
        ledger = ws / first['run_dir'] / 'calls.jsonl'
        ends = {json.loads(x)['call_id'] for x in ledger.read_text(encoding='utf-8').splitlines()
                if json.loads(x).get('event') == 'call_end'}
        starts = [json.loads(x) for x in ledger.read_text(encoding='utf-8').splitlines()
                  if json.loads(x).get('event') == 'call_start']
        unfinished = sum(1 for s in starts if s['call_id'] not in ends)
    f = Flow(flow_dir(ws, interrupt_id) / 'flow.sqlite')
    try:
        effects = [e for e in f.events() if e['event'] == 'effect_exported']
    finally:
        f.close()
    checks = {'kills_at_boundaries': [e['exit'] for e in exits] == [e['expected_exit'] for e in exits],
              'first_capture_recovered_without_new_call': bool(first) and first['state'] == 'captured'
              and unfinished == 1,
              'manifest_reconciled_on_resume': len(effects) >= 2
              and sorted(effects[-1]['details']['detail']['reconciled']) == ['handoff.json', 'handoff.md',
                                                                           'manifest.json']}
    return {'pass': all(checks.values()), 'checks': checks, 'exits': exits}


def suite(ws: Path, kind: str, prefix: str, only: str | None = None) -> dict:
    """The five scenarios in order with their checks; only runs one scenario (the preregistered rerun) and skips the
    clean-state checks, which need the clean run."""
    ws = ws.resolve()
    prepare(ws, kind)
    report = {'gate': 'G2 dry' if kind == 'fixture' else 'G3 live', 'kind': kind, 'prefix': prefix,
              'freeze': freeze(), 'started_at': time.time(), 'scenarios': {}}
    if kind == 'live':
        version = cli_version()
        report['cli_version'] = version
        if not report['freeze']['frozen'] or version != spec()['route']['cli_version']:
            report['blocker'] = 'freeze check failed or CLI version differs; nothing was launched'
            return report
    clean_copy = None
    for scenario in ([only] if only else SCENARIOS):
        if scenario == 'interrupt':
            exits = run_interrupt(ws, kind, prefix)
            result = run_scenario_flow(ws, kind, prefix, scenario)  # reads the settled state; no new work remains
            report['scenarios'][scenario] = audit(ws, kind, prefix, scenario, result)
            report['scenarios'][scenario]['observables'] = interrupt_observables(ws, prefix, exits)
        else:
            result = run_scenario_flow(ws, kind, prefix, scenario)
            report['scenarios'][scenario] = audit(ws, kind, prefix, scenario, result)
        if scenario == 'clean':
            clean_copy = copy_of(ws, 'clean-state')
        if scenario == 'stale':
            report['scenarios'][scenario]['observables'] = stale_observables(ws, prefix)
        print(scenario, 'pass' if report['scenarios'][scenario]['pass'] else 'FAIL',
              report['scenarios'][scenario]['launches'], flush=True)
    if only:
        report['pass'] = all(s['pass'] and s.get('observables', {}).get('pass', True)
                             for s in report['scenarios'].values())
        (ws / f'report-{kind}-{prefix}-{only}-r{RERUN.get(only, 0)}.json').write_text(
            json.dumps(report, indent=1, default=str) + '\n', encoding='utf-8')
        return report
    report['c5'] = c5_checks(ws, kind, prefix, clean_copy)
    if kind == 'fixture':
        report['sabotage'] = sabotage(ws, prefix, clean_copy, ws)
        report['baseline_smoke'] = baseline(ws, kind='fixture', calls=[('rev1', 1), ('rev2', 1)])
    usage = [flow_usage(ws, rid(prefix, s)) for s in SCENARIOS]
    report['totals'] = {'launches': sum(u['launches'] for u in usage),
                        'tokens_known': sum(u['tokens_known'] for u in usage),
                        'calls_without_usage': sum(u['calls_without_usage'] for u in usage),
                        'caps': spec()['budgets']['executor']}
    report['totals']['accounting'] = 'complete' if report['totals']['calls_without_usage'] == 0 else 'incomplete'
    report['pass'] = (all(s['pass'] for s in report['scenarios'].values())
                      and all(s.get('observables', {}).get('pass', True) for s in report['scenarios'].values())
                      and all(c['pass'] for c in report['c5'].values())
                      and all(c['caught'] for c in report.get('sabotage', {}).values())
                      and report.get('baseline_smoke', {}).get('pass', True))
    report['finished_at'] = time.time()
    (ws / f'report-{kind}-{prefix}.json').write_text(json.dumps(report, indent=1, default=str) + '\n',
                                                     encoding='utf-8')
    return report


# ---- G4 baseline ----

def baseline(ws: Path, *, kind: str = 'live', calls=None) -> dict:
    """No-orchestration arm: one call per run, four records in, handoff.json content out, same evaluator (JSON only).
    Resume-safe: a receipt with a completed capture is read back, never called again."""
    from oz_worker import StdioAdapter
    ws = ws.resolve()
    prepare(ws, kind)
    calls = calls or [('rev1', 1), ('rev1', 2), ('rev1', 3), ('rev2', 1)]
    caps = spec()['budgets']['baseline']
    model = route(kind)[1]
    system = (W.FROZEN / 'baseline' / 'system.txt').read_text(encoding='utf-8')
    capture_dir = ws / ('baseline' if kind == 'live' else 'baseline-fixture') / 'captures'
    argv = (sys.executable, str(ROOT / spec()['route' if kind == 'live' else 'fixture_route']['adapter_script']))
    quota = quota_store(ws, kind)
    rows, launches, tokens, unknown, measured = [], 0, 0, 0, []
    check = response_check(model, spec()['route'].get('alias_map', {}) if kind == 'live' else {})
    try:
        for i, (variant, n) in enumerate(calls, 1):
            receipt = f'b{i}'
            prompt = (W.FROZEN / 'baseline' / f'prompt-{variant}.txt').read_text(encoding='utf-8')
            request = {'protocol': PROTOCOL, 'language': LANGUAGE, 'binding': 'baseline', 'receipt': receipt,
                       'ids': [], 'attempts': [], 'system': system, 'prompt': prompt, 'prompt_tokens': []}
            payload_sha = hashlib.sha256(json.dumps(request, ensure_ascii=False).encode('utf-8')).hexdigest()
            capture, error = read_capture(capture_dir, receipt, payload_sha), None
            if capture is None:
                # Admission headroom: the frozen 6k upper estimate until a call is measured, then the largest
                # measured call (empirical, not a provider bound); an unknown call is charged at the 6k estimate.
                reserve = max(measured) if measured else caps['reserve_per_launch']
                if (launches + 1 > caps['max_launches']
                        or tokens + caps['reserve_per_launch'] * unknown + reserve > caps['max_tokens']):
                    rows.append({'call': i, 'variant': variant, 'blocked': 'baseline cap'})
                    break
                slot = quota.acquire('claude-cli', run_dir=capture_dir.parent, receipt=receipt)
                if slot['status'] != 'acquired':
                    rows.append({'call': i, 'variant': variant, 'blocked': 'quota slot held'})
                    break
                try:
                    StdioAdapter(argv, cwd=ws, timeout=spec()['deadlines']['call_timeout_seconds'],
                                 capture_dir=capture_dir)(request)
                except Exception as exc:  # the capture, if any, is still read below
                    error = type(exc).__name__
                finally:
                    quota.release('claude-cli', slot['token'])
                capture = read_capture(capture_dir, receipt, payload_sha)
            launches += 1
            envelope = envelope_of(capture)
            from importlib import util
            s = util.spec_from_file_location('cca', ROOT / 'examples' / 'claude_cli_adapter.py')
            cca = util.module_from_spec(s)
            s.loader.exec_module(cca)
            usage = cca.usage_from_envelope(envelope) if envelope else None
            if usage is None:
                unknown += 1
            else:
                tokens += usage['input_tokens'] + usage['output_tokens']
                measured.append(usage['input_tokens'] + usage['output_tokens'])
            reply = envelope.get('result') if envelope else None
            try:
                doc = json.loads(reply)
                errors = E.evaluate_document(doc, variant, W.load('expected.json')['revisions'][
                    'stale' if variant == 'rev2' else 'clean'])
            except (TypeError, ValueError):
                errors = ['reply is not one JSON document']
            model_ok = check({'capture_dir': str(capture_dir), 'receipt': receipt, 'request_sha256': payload_sha})
            rows.append({'call': i, 'variant': variant, 'verified': not errors, 'errors': errors[:5], 'usage': usage,
                         'model_check': model_ok or 'ok', **({'adapter_error': error} if error else {})})
    finally:
        quota.close()
    out = {'calls': rows, 'launches': launches, 'tokens_known': tokens, 'calls_without_usage': unknown,
           'caps': caps, 'accounting': 'complete' if unknown == 0 else 'incomplete',
           'note': 'measured calls only; repeat, revision bump and interruption are counterfactual estimates'}
    out['pass'] = all(r.get('verified') for r in rows) and len(rows) == len(calls)
    (ws / f'baseline-{kind}.json').write_text(json.dumps(out, indent=1) + '\n', encoding='utf-8')
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('freeze')
    p.add_argument('--write', action='store_true')
    for name in ('dry', 'live', 'baseline'):
        p = sub.add_parser(name)
        p.add_argument('--workspace', required=True, type=Path)
        p.add_argument('--prefix', default={'dry': 'dry1', 'live': 'live1', 'baseline': ''}[name])
        if name != 'baseline':
            p.add_argument('--only', choices=SCENARIOS, help='run one scenario (the preregistered rerun)')
            p.add_argument('--rerun', type=int, default=0, help='rerun number: request id <prefix>-<scenario>-rN')
    p = sub.add_parser('run-flow')
    p.add_argument('--workspace', required=True, type=Path)
    p.add_argument('--kind', choices=('fixture', 'live'), required=True)
    p.add_argument('--prefix', required=True)
    p.add_argument('--scenario', choices=SCENARIOS, required=True)
    p.add_argument('--rerun', type=int, default=0)
    args = parser.parse_args(argv)
    if getattr(args, 'rerun', 0):
        key = getattr(args, 'only', None) or getattr(args, 'scenario', None)
        if key is None:
            parser.error('--rerun needs --only SCENARIO')
        RERUN[key] = args.rerun
    if args.command == 'freeze':
        result = freeze(write=args.write)
        print(json.dumps(result, indent=1))
        return 0 if result['frozen'] else 1
    if args.command == 'run-flow':
        ws = args.workspace.resolve()
        prepare(ws, args.kind)
        result = run_scenario_flow(ws, args.kind, args.prefix, args.scenario)
        print(J({k: result[k] for k in ('status', 'blocker', 'launches', 'targets')}))
        return 0 if result['status'] == 'delivered' else 3
    if args.command in ('live', 'baseline') and not os.environ.get('STEP4_LIVE_CONFIRM'):
        print('live and baseline run paid calls: set STEP4_LIVE_CONFIRM=1 to proceed', file=sys.stderr)
        return 2
    if args.command == 'baseline':
        result = baseline(args.workspace)
        print(json.dumps(result, indent=1))
        return 0 if result['pass'] else 3
    report = suite(args.workspace, 'fixture' if args.command == 'dry' else 'live', args.prefix, args.only)
    print(json.dumps({k: report.get(k) for k in ('gate', 'pass', 'totals', 'blocker')}, indent=1, default=str))
    return 0 if report.get('pass') else 3


if __name__ == '__main__':
    sys.exit(main())
