"""O1 harness for repair-handoff-20/v1 (G3c-O1): G0 freeze, G2 zero-token dry gate, measurement, guarded live run.

    python bench/o1/o1.py freeze [--write]               G0: verify (or write) every frozen digest
    python bench/o1/o1.py measure                        packet tokens, reserves, tier runtimes, expected spend
    python bench/o1/o1.py dry --workspace DIR            G2: five scenarios, recovery fixtures, sabotage, escape suite,
                                                         seeds, oracle checks, feasibility (zero tokens)
    python bench/o1/o1.py live --workspace DIR           G3c-O1: five scenarios through claude -p (paid, one fresh suite)
    python bench/o1/o1.py run-flow --workspace DIR --kind K --prefix P --scenario S   one flow invocation

Every scenario runs through oz_flow.run_flow, which sends model stages through oz do (oz1g-selective-v1, durable
runner, per-job checks, memo, quota reservation, admission), with experimental_sizes=(4, 1). The dry gate and the live
run share every line except the adapter (fixture_adapter.py versus examples/claude_cli_adapter.py), the route
identity and the memo namespaces. The verdict comes from gate.py and the independent evaluator, never from the
executor's own flags. See docs/design/o1-real-workflow-2026-10-23/plan-frozen.md.
"""
from __future__ import annotations

import argparse
import base64
import copy
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
for p in (str(ROOT), str(HERE), str(HERE / 'evaluator')):
    if p not in sys.path:
        sys.path.insert(0, p)

import evaluator as E  # noqa: E402
import gate as GT  # noqa: E402
import sandbox  # noqa: E402
import sandbox_worker as SW  # noqa: E402
import workflow as W  # noqa: E402
from oz import Error  # noqa: E402
from oz_batch import J  # noqa: E402
from oz_flow import Flow, HostOp, Settings, flow_dir, flow_usage, run_flow, stage_launches  # noqa: E402
from oz_memo import MemoStore  # noqa: E402
from oz_quota import Quota  # noqa: E402
from oz_reply import LANGUAGE, PROTOCOL  # noqa: E402
from oz_runner import read_capture  # noqa: E402
from oz_workspace import initialize  # noqa: E402
import oz_fault  # noqa: E402

KILL = oz_fault.KILL_EXIT
CODE = ('oz.py', 'oz_batch.py', 'oz_reply.py', 'oz_accept.py', 'oz_runtime.py', 'oz_worker.py', 'oz_runner.py',
        'oz_do.py', 'oz_memo.py', 'oz_quota.py', 'oz_flow.py', 'oz_fault.py', 'oz_workspace.py',
        'examples/claude_cli_adapter.py', 'bench/step4/g3b.py', 'bench/o1/o1.py', 'bench/o1/workflow.py',
        'bench/o1/o1_dry.py', 'bench/o1/sandbox.py', 'bench/o1/sandbox_worker.py', 'bench/o1/gate.py',
        'bench/o1/fixture_adapter.py',
        'bench/o1/evaluator/evaluator.py', 'bench/o1/evaluator/eval_worker.py', 'bench/o1/evaluator/heldout.py',
        'bench/o1/evaluator/build.py')
SCENARIOS = ('clean', 'repeat', 'interrupt', 'stale', 'bump')
FREEZE_FILE = W.FROZEN / 'freeze.json'
TARGET = 'repair_package'
LIVE_ENV = 'O1_LIVE_CONFIRM'


def ndigest(path: Path) -> str:
    """SHA-256 with CRLF normalized to LF (a checkout's line-ending conversion does not change identities)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def spec() -> dict:
    return W.spec()


def allocation() -> dict:
    return spec()['allocation']


def entry(scenario: str) -> dict:
    return next(s for s in spec()['scenarios'] if s['name'] == scenario)


# ---- G0: the freeze ----

def frozen_files() -> list:
    pack = [p for p in W.FROZEN.rglob('*') if p.is_file() and p.name != 'freeze.json']
    evaluator = [HERE / 'evaluator' / 'heldout.json'] + sorted((HERE / 'evaluator' / 'ref1').glob('*.py')) + sorted(
        (HERE / 'evaluator' / 'ref2').glob('*.py'))
    fixture = sorted((HERE / 'fixture').glob('*.py'))
    return sorted(set(pack + evaluator + fixture))


def digests() -> dict:
    return {'frozen': {p.relative_to(ROOT).as_posix(): ndigest(p) for p in frozen_files()},
            'code': {c: ndigest(ROOT / c) for c in CODE},
            'design': {p.relative_to(ROOT).as_posix(): ndigest(p)
                       for p in sorted((ROOT / 'docs/design/o1-real-workflow-2026-10-23').glob('0*.md'))}}


def freeze(write=False) -> dict:
    current = digests()
    current['digest'] = hashlib.sha256(J(current).encode('utf-8')).hexdigest()
    problems = []
    if allocation().get('reserve_per_launch') is None:
        problems.append('the measured reserve is not frozen in workflow.json')
    if entry('bump').get('expected_memo_hits') is None:
        problems.append('the bump memo trace is not frozen in workflow.json')
    if write:
        if problems:
            raise Error('cannot freeze: ' + '; '.join(problems))
        FREEZE_FILE.write_text(json.dumps(current, indent=1) + '\n', encoding='utf-8', newline='\n')
        return {'frozen': True, 'digest': current['digest'], 'problems': []}
    stored = json.loads(FREEZE_FILE.read_text(encoding='utf-8')) if FREEZE_FILE.exists() else {}
    again = hashlib.sha256(J({k: stored.get(k, {}) for k in ('frozen', 'code', 'design')}).encode('utf-8'))
    if stored.get('digest') != again.hexdigest():
        problems.append('the stored file maps do not hash to the stored digest')
    for group in ('frozen', 'code', 'design'):
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


def envelope_of(capture):
    if not capture or not capture.get('envelope_b64'):
        return None
    try:
        return json.loads(base64.b64decode(capture['envelope_b64']).decode('utf-8'))
    except (ValueError, UnicodeError):
        return None


def response_check(model: str, alias_map: dict):
    """The actual model comes from the retained envelope's modelUsage keys; missing identity or another model refuses
    every candidate of that call."""
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


def cli_version():
    claude = shutil.which('claude')
    if claude is None:
        return None
    out = subprocess.run([claude, '--version'], capture_output=True, text=True, timeout=60).stdout.strip()
    return out.split()[0] if out else None


def live_refusal(frozen: dict, version) -> str | None:
    if not frozen['frozen'] or version != spec()['route']['cli_version']:
        return 'freeze check failed or CLI version differs; nothing was launched'
    return None


def route_check(kind: str):
    if kind != 'live':
        return None
    want = spec()['route']['cli_version']

    def check():
        found = cli_version()
        return None if found == want else f'claude CLI version {found} != frozen {want}'
    return check


def settings(ws: Path, kind: str, namespace: str, *, quota, registry=None, budget=None, route_fields=None,
             checks=None, experimental_sizes=None):
    fields, model = route(kind)
    return Settings(workspace=ws, adapter=adapter_file(ws, kind), registry=registry or W.registry(),
                    checks_registry=checks or W.CHECKS, route=route_fields or fields, model=model,
                    memo_store=ws / 'memo.sqlite', namespace=namespace, quota=quota,
                    budget=allocation() if budget is None else budget, budget_scope=ws,
                    route_check=route_check(kind),
                    response_check=response_check(model, spec()['route'].get('alias_map', {}) if kind == 'live'
                                                  else {}),
                    packet_sizes=tuple(spec()['packets']['sizes']),
                    experimental_sizes=tuple(experimental_sizes or spec()['packets']['experimental_sizes']))


def quota_store(ws: Path, kind: str) -> Quota:
    return Quota(None if kind == 'live' else ws / 'quota.sqlite')


def rid(prefix: str, scenario: str) -> str:
    return f'{prefix}-{scenario}'


def flow_request(prefix: str, scenario: str, *, request_id=None) -> dict:
    return {'v': 'oz.flow/1', 'request_id': request_id or rid(prefix, scenario), 'workflow': W.WORKFLOW_ID,
            'workflow_digest': freeze()['current_digest'], 'graph': W.graph(), 'effects': spec()['effects'],
            'deadline_seconds': spec()['deadlines']['scenario_seconds'],
            'call_timeout_seconds': spec()['deadlines']['call_timeout_seconds']}


def namespace(kind: str, prefix: str, scenario: str) -> str:
    e = next((s for s in spec()['scenarios'] if s['name'] == scenario), None)
    if e is None or e['namespace'] == 'own':
        return f'{kind}-{prefix}-{scenario}'
    return f'{kind}-{prefix}-{e["namespace"]}'


def mutation_hook(ws: Path, request_id: str, mutation: str, hook_name=None):
    m = spec()['mutations'][mutation]

    def hook(_name):
        f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
        try:
            if any(e['event'] == 'source_revised' for e in f.events()):
                return  # preregistered once; a resumed or regenerated node never mutates again
            f.bump_source(m['source'], (W.FROZEN / m['file']).read_bytes(), reason=f'preregistered mutation {mutation}')
        finally:
            f.close()
    return oz_fault.on(hook_name or m['hook'], hook)


def run_scenario_flow(ws: Path, kind: str, prefix: str, scenario: str, **options) -> dict:
    e = entry(scenario)
    request = flow_request(prefix, scenario)
    quota = quota_store(ws, kind)
    remove = mutation_hook(ws, request['request_id'], e['mutation']) if e['mutation'] else None
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


# ---- audits: plain records for the gate ----

def stage_runs(ws: Path, request_id: str) -> list:
    f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
    try:
        return list(dict.fromkeys(e['details']['run_dir'] for e in f.events() if e['event'] == 'stage_submitted'))
    finally:
        f.close()


def flow_events(ws: Path, request_id: str) -> list:
    f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
    try:
        return f.events()
    finally:
        f.close()


def _candidate_rows(run: Path) -> dict:
    import sqlite3
    path = run / 'inbox.sqlite'
    if not path.exists():
        return {}
    db = sqlite3.connect(str(path))
    try:
        return {(r[0], r[1]): {'status': r[2], 'value': r[3]}
                for r in db.execute('SELECT job,receipt,status,value FROM candidates ORDER BY seq')}
    finally:
        db.close()


def _member_verdict(d: dict, job: str, candidates: dict, outcome: dict) -> str:
    row = candidates.get((job, d['receipt']))
    if row is not None:
        return GT.CANDIDATE_VERDICT.get(row['status'], 'unknown_status:' + str(row['status']))
    if outcome.get(job) in ('pending', 'failed'):
        return 'call_failed' if d['state'] == 'failed_call' else 'no_candidate'
    return 'unknown'


def _capture_evidence(run: Path, receipt: str):
    record = read_capture(run / 'captures', receipt)
    if record is None:
        return None
    return {'exit_code': record['exit_code'], 'start_failed': bool(record.get('start_failed')),
            'stdout_b64': record['stdout_b64']}


def _labels(run: Path) -> dict:
    path = run / 'do.jsonl'
    out = {}
    for line in (path.read_text(encoding='utf-8').splitlines() if path.exists() else ()):
        r = json.loads(line)
        out[r['call_id']] = r['profile']
    return out


def trace_of(ws: Path, request_id: str) -> list:
    """The flow's dispatches in launch order as plain records: stage index among the stage runs that launched, members
    (id, generation, attempt, compute key), the exact record text each member was sent, the executor's own verdicts,
    the preserved capture and the stored candidates, and the dispatch's profile label."""
    out, stage = [], 0
    for rel in stage_runs(ws, request_id):
        rows = stage_launches(ws / rel)
        if not rows:
            continue
        candidates = _candidate_rows(ws / rel)
        labels = _labels(ws / rel)
        for d in sorted(rows, key=lambda r: (r['created_at'], len(r['receipt']), r['receipt'])):
            members = json.loads(d['members'])
            body = json.loads(d['packet'])
            refs = {row[0]: body['refs'][row[1]] for block in body['jobs'] for row in block[1:]}
            outcome = json.loads(d['outcome']) if d['outcome'] else {}
            stored = {m['id']: candidates[(m['id'], d['receipt'])] for m in members
                      if (m['id'], d['receipt']) in candidates}
            out.append({'stage': stage, 'op': members[0]['id'].split('_')[0], 'receipt': d['receipt'], 'run_dir': rel,
                        'created_at': d['created_at'], 'state': d['state'], 'call_id': d['call_id'],
                        'label': labels.get(d['call_id'], 'unrecorded'),
                        'members': [{k: m[k] for k in ('id', 'generation', 'attempt', 'compute_key')} for m in members],
                        'refs': refs, 'verdicts': {m['id']: _member_verdict(d, m['id'], candidates, outcome)
                                                   for m in members},
                        'evidence': {'capture': _capture_evidence(ws / rel, d['receipt']), 'candidates': stored}})
        stage += 1
    return out


def _cca():
    from importlib import util
    found = util.spec_from_file_location('cca_o1', ROOT / 'examples' / 'claude_cli_adapter.py')
    module = util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


def thinking_tokens(envelope):
    usage = envelope.get('modelUsage') if isinstance(envelope, dict) else None
    if not isinstance(usage, dict) or not usage:
        return None
    total = 0
    for item in usage.values():
        value = item.get('thinkingTokens') if isinstance(item, dict) else None
        if type(value) is not int or value < 0:
            return None
        total += value
    return total


def calls_of(ws: Path, request_id: str, trace: list) -> list:
    ends = {}
    for rel in stage_runs(ws, request_id):
        ledger = ws / rel / 'calls.jsonl'
        for line in (ledger.read_text(encoding='utf-8').splitlines() if ledger.exists() else ()):
            r = json.loads(line)
            if r.get('event') == 'call_end':
                ends[(rel, r['batch_id'])] = r
    rows = []
    for d in trace:
        usage = (ends.get((d['run_dir'], d['receipt'])) or {}).get('usage') or {}
        done = ws / d['run_dir'] / 'captures' / f"{d['receipt']}.done"
        envelope = envelope_of(json.loads(done.read_text(encoding='utf-8'))) if done.exists() else None
        if not usage and envelope:
            usage = _cca().usage_from_envelope(envelope) or {}
        tin, tout = usage.get('input_tokens'), usage.get('output_tokens')
        rows.append({'stage': d['stage'], 'receipt': d['receipt'], 'members': [m['id'] for m in d['members']],
                     'attempt': GT.attempt_of(d), 'label': d.get('label'), 'verdicts': d.get('independent'),
                     'input_tokens': tin, 'output_tokens': tout,
                     'tokens': tin + tout if type(tin) is int and type(tout) is int else None,
                     'thinking_tokens': thinking_tokens(envelope),
                     'model': sorted(envelope.get('modelUsage', {})) if envelope else None})
    return rows


def ledger_audit(ws: Path, request_id: str) -> dict:
    """Every physical launch has exactly one ledger call_start line and no ledger call lacks a launch."""
    problems, calls = [], 0
    for rel in stage_runs(ws, request_id):
        ledger = ws / rel / 'calls.jsonl'
        starts = {}
        for line in (ledger.read_text(encoding='utf-8').splitlines() if ledger.exists() else ()):
            r = json.loads(line)
            if r.get('event') == 'call_start':
                starts[r['batch_id']] = starts.get(r['batch_id'], 0) + 1
        receipts = {d['receipt'] for d in stage_launches(ws / rel)}
        calls += sum(starts.values())
        for receipt, lines in starts.items():
            if lines > 1:
                problems.append(f'{rel}: receipt {receipt} counted as {lines} calls')
            if receipt not in receipts:
                problems.append(f'{rel}: ledger call for {receipt} has no journaled launch')
        for receipt in receipts - set(starts):
            problems.append(f'{rel}: launch {receipt} has no ledger call')
    return {'ok': not problems, 'ledger_calls': calls, 'problems': problems}


def fixture_invocations(ws: Path, request_id: str) -> int:
    log = Path(os.environ.get('OZ_FIXTURE_DIR', ws / 'fixture')) / 'invocations.jsonl'
    if not log.exists():
        return 0
    from oz import Channel
    bindings = set()
    for rel in stage_runs(ws, request_id):
        cfg = json.loads((ws / rel / 'oz.json').read_text(encoding='utf-8'))
        bindings.add(Channel.from_snapshot(cfg['channels']['worker']).binding)
    return sum(1 for line in log.read_text(encoding='utf-8').splitlines() if json.loads(line)['binding'] in bindings)


def memo_trace(ws: Path, request_id: str) -> list:
    """Every memo lookup of the flow in order: [op, job, decision]."""
    return [[e['details']['op'], job, m['decision']] for e in flow_events(ws, request_id) if e['event'] == 'stage'
            for job, m in (e['details'].get('memo') or {}).items()]


def memo_detail(ws: Path, request_id: str, trace: list) -> list:
    """Memo hits in flow order with the entry's provenance, each placed after the launches made before its stage was
    submitted; verified_value is the value line the evaluator re-read from the provenance capture (None when the
    capture does not hold the entry's value)."""
    import sqlite3
    events = flow_events(ws, request_id)
    submitted = {}
    for e in events:
        if e['event'] == 'stage_submitted':
            submitted.setdefault(e['details']['run_dir'], e['at'])
    out = []
    db = sqlite3.connect(str(ws / 'memo.sqlite'))
    try:
        for e in events:
            if e['event'] != 'stage':
                continue
            at = submitted.get(e['details']['run_dir'], e['at'])
            for job, m in (e['details'].get('memo') or {}).items():
                if m['decision'] != 'hit':
                    continue
                row = db.execute('SELECT value, provenance FROM entries WHERE id=?', (m['entry'],)).fetchone()
                value = json.loads(row[0]) if row else None
                prov = json.loads(row[1]) if row else {}
                seen = E.provenance_value(ws, prov, job) if row else None
                out.append({'job': job, 'entry': m['entry'], 'provenance': prov,
                            'after_launches': sum(1 for d in trace if d['created_at'] < at),
                            'verified_value': seen if seen is not None and seen == value else None})
    finally:
        db.close()
    return out


def delivery_of(ws: Path, request_id: str, result: dict) -> tuple:
    f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
    try:
        deliveries = f.deliveries()
    finally:
        f.close()
    target = result['targets'][TARGET]
    dest = ws / target['destination'] if target['status'] == 'delivered' else None
    return deliveries, target, dest


def expected_revisions(scenario: str) -> dict:
    e = entry(scenario)
    out = {n: 1 for n in W.TICKETS}
    if e.get('revised_source'):
        out[e['revised_source']] = e['revised_revision']
    return out


def observe(ws: Path, kind: str, prefix: str, scenario: str, result: dict, observables=None) -> dict:
    request_id = rid(prefix, scenario)
    trace = trace_of(ws, request_id)
    deliveries, target, dest = delivery_of(ws, request_id, result)
    return {'scenario': scenario, 'status': result['status'], 'deliveries': len(deliveries),
            'on_time': target.get('on_time'), 'delivery_dir': str(dest) if dest else None,
            'revisions': expected_revisions(scenario), 'memo_hits': sum(1 for x in memo_trace(ws, request_id)
                                                                        if x[2] == 'hit'),
            'memo_trace': memo_trace(ws, request_id), 'memo_hits_detail': memo_detail(ws, request_id, trace),
            'acceptance_trace': [[e['details']['node'], e['details']['generation']]
                                 for e in flow_events(ws, request_id) if e['event'] == 'accepted'],
            'trace': trace, 'labels': [d['label'] for d in trace], 'ledger_ok': ledger_audit(ws, request_id)['ok'],
            'calls_without_usage': result['accounting']['calls_without_usage'],
            'per_flow_cap': allocation()['max_launches_per_flow'], 'observables': observables,
            'fixture_invocations': fixture_invocations(ws, request_id) if kind == 'fixture' else None}


def verdict_of(obs: dict) -> dict:
    v = GT.scenario_verdict(obs)
    return v


def scenario_report(ws: Path, kind: str, prefix: str, scenario: str) -> dict:
    exits = run_interrupt(ws, kind, prefix) if scenario == 'interrupt' else None
    result = run_scenario_flow(ws, kind, prefix, scenario)
    observables = (interrupt_observables(ws, prefix, exits) if scenario == 'interrupt'
                   else stale_observables(ws, prefix) if scenario == 'stale' else None)
    obs = observe(ws, kind, prefix, scenario, result, observables)
    verdict = verdict_of(obs)
    annotated = GT.annotate(scenario, obs['trace'])
    calls = calls_of(ws, rid(prefix, scenario), annotated)
    out = {'scenario': scenario, 'request_id': rid(prefix, scenario), 'status': result['status'],
           'blocker': result['blocker'], 'launches': len(obs['trace']), 'packets': [len(d['members'])
                                                                                  for d in obs['trace']],
           'expected': {k: entry(scenario)[k] for k in ('expected_launches', 'expected_packets', 'expected_memo_hits')},
           'memo_hits': obs['memo_hits'], 'memo_trace': obs['memo_trace'], 'labels': obs['labels'],
           'deliveries': obs['deliveries'], 'on_time': obs['on_time'], 'accounting': result['accounting'],
           'ledger': ledger_audit(ws, rid(prefix, scenario)), 'fixture_invocations': obs['fixture_invocations'],
           'observables': observables, 'gate': {k: v for k, v in verdict.items() if k != 'judged'},
           GT.LABEL: verdict[GT.LABEL], 'recovered': verdict['recovered'],
           'recovery': GT.recovery_report(annotated, calls)}
    out['_obs'] = obs
    return out


# ---- scenario observables ----

def run_interrupt(ws: Path, kind: str, prefix: str) -> list:
    cmd = [sys.executable, str(Path(__file__).resolve()), 'run-flow', '--workspace', str(ws), '--kind', kind,
           '--prefix', prefix, '--scenario', 'interrupt']
    exits = []
    for faults, expect in ((['worker.after_capture'], KILL), (['flow.publish.after_manifest'], KILL), ([], 0)):
        env = dict(os.environ, OZ_FAULTS=','.join(faults), PYTHONIOENCODING='utf-8')
        if kind == 'live':
            env[LIVE_ENV] = '1'
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding='utf-8')
        exits.append({'faults': faults, 'exit': proc.returncode, 'expected_exit': expect,
                      'stderr_tail': proc.stderr[-400:] if proc.returncode not in (0, KILL) else ''})
    return exits


def interrupt_observables(ws: Path, prefix: str, exits: list) -> dict:
    request_id = rid(prefix, 'interrupt')
    trace = trace_of(ws, request_id)
    first = trace[0] if trace else None
    unfinished = 0
    if first:
        ledger = ws / first['run_dir'] / 'calls.jsonl'
        lines = [json.loads(x) for x in ledger.read_text(encoding='utf-8').splitlines()]
        ends = {r['call_id'] for r in lines if r.get('event') == 'call_end'}
        unfinished = sum(1 for r in lines if r.get('event') == 'call_start' and r['call_id'] not in ends)
    effects = [e for e in flow_events(ws, request_id) if e['event'] == 'effect_exported']
    files = sorted(['amounts.py', 'intervals.py', 'config_patch.py', 'jobs.py', 'repair.patch', 'verification.md',
                    'provenance.json', 'manifest.json'])
    f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
    try:
        info = f.info()
        deadline_kept = info is not None and abs(info['deadline_at'] - info['created_at']
                                                 - spec()['deadlines']['scenario_seconds']) < 1
    finally:
        f.close()
    checks = {'kills_at_boundaries': [e['exit'] for e in exits] == [e['expected_exit'] for e in exits],
              'first_capture_recovered_without_new_call': bool(first) and first['state'] == 'captured'
              and unfinished == 1,
              'manifest_reconciled_on_resume': len(effects) >= 2
              and sorted(effects[-1]['details']['detail']['reconciled']) == files,
              'request_identity_and_deadline_kept': deadline_kept}
    return {'pass': all(checks.values()), 'checks': checks, 'exits': exits}


def stale_observables(ws: Path, prefix: str) -> dict:
    """The stale-A run: the mutation invalidates the old package verification and blocks its delivery; nothing after
    it carries old A bytes; B, C and D reassociate through memo hits on identical inputs; the delivery cites A
    revision 2; old A acceptances stay as history."""
    request_id = rid(prefix, 'stale')
    events = flow_events(ws, request_id)
    mutation = next(e for e in events if e['event'] == 'source_revised')
    f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
    try:
        history = [dict(r) for r in f.db.execute('SELECT seq,node,generation,cites FROM acceptances ORDER BY seq')]
        deliveries = f.deliveries()
        current = f.current()
    finally:
        f.close()
    old_core = W.ticket('A', 1)['core_record']
    old_prefix = W.ticket('A', 1)['adapter_record_prefix']
    after = [d for d in trace_of(ws, request_id) if d['created_at'] > mutation['at']]
    leaked = [d['receipt'] for d in after if any(r == old_core or r.startswith(old_prefix) for r in d['refs'].values())]
    first_keys = {}
    for e in events:
        if e['event'] == 'stage' and e['seq'] < mutation['seq']:
            for job, ev in _accepted_keys(ws / e['details']['run_dir']).items():
                first_keys[job] = ev
    reused = {}
    for e in events:
        if e['event'] == 'stage' and e['seq'] > mutation['seq']:
            for job, m in (e['details'].get('memo') or {}).items():
                if job[-1] in 'BCD':
                    reused[job] = {'decision': m['decision'], 'same_inputs': first_keys.get(job) == m['compute_key']}
    old_integration = [r for r in history if r['node'] == 'integration' and json.loads(r['cites']).get('A') == 1]
    checks = {
        'no_old_A_after_mutation': not leaked,
        'old_verification_invalidated_and_not_delivered': (
            bool(old_integration) and current.get('integration', {}).get('seq') not in {r['seq'] for r in
                                                                                       old_integration}
            and len(deliveries) == 1 and deliveries[0]['cites'].get('A') == 2),
        'bcd_reused_by_memo_on_identical_inputs': (
            sorted(reused) == sorted(f'{op}_{n}' for op in ('core', 'adapter') for n in 'BCD')
            and all(v['decision'] == 'hit' and v['same_inputs'] for v in reused.values())),
        'old_A_history_kept': any(r['node'] == 'core_A' and json.loads(r['cites']).get('A') == 1 for r in history)
        and any(r['node'] == 'core_A' and json.loads(r['cites']).get('A') == 2 for r in history)}
    return {'pass': all(checks.values()), 'checks': checks, 'leaked_receipts': leaked, 'reused': reused}


def _accepted_keys(run: Path) -> dict:
    import sqlite3
    db = sqlite3.connect(str(run / 'inbox.sqlite'))
    try:
        return {r[0]: r[1] for r in db.execute("SELECT job,compute_key FROM candidates WHERE status='accepted'")}
    finally:
        db.close()


# ---- suite ----

def copy_of(ws: Path, name: str) -> Path:
    dest = ws.parent / (ws.name + '.copies') / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ws, dest, ignore=shutil.ignore_patterns('*.copies'))
    return dest


def fresh_refusal(ws: Path):
    flows = ws / 'flows'
    if (flows.exists() and any(flows.iterdir())) or (ws / 'memo.sqlite').exists():
        return 'the workspace is not fresh (G3c-O1 is one suite in a fresh workspace); nothing was launched'
    return None


def totals_of(ws: Path, prefix: str, started: float) -> dict:
    usage = [flow_usage(ws, rid(prefix, s)) for s in SCENARIOS]
    out = {'launches': sum(u['launches'] for u in usage), 'tokens_known': sum(u['tokens_known'] for u in usage),
           'calls_without_usage': sum(u['calls_without_usage'] for u in usage), 'caps': allocation(),
           'elapsed_seconds': round(time.time() - started, 1)}
    out['accounting'] = 'complete' if out['calls_without_usage'] == 0 else 'incomplete'
    out['suite_over_envelope'] = out['elapsed_seconds'] > spec()['deadlines']['suite_envelope_seconds']
    return out


def strip(report_row: dict) -> dict:
    return {k: v for k, v in report_row.items() if not k.startswith('_')}


def suite(ws: Path, kind: str, prefix: str) -> dict:
    ws = ws.resolve()
    prepare(ws, kind)
    started = time.time()
    report = {'gate': 'G3c-O1 dry (G2)' if kind == 'fixture' else 'G3c-O1 live', 'kind': kind, 'prefix': prefix,
              'freeze': freeze(), 'started_at': started, 'scenarios': {}}
    if kind == 'live':
        version = cli_version()
        report['cli_version'] = version
        refusal = live_refusal(report['freeze'], version) or fresh_refusal(ws)
        if refusal:
            report['blocker'] = refusal
            return report
    runs = {}
    for scenario in SCENARIOS:
        row = scenario_report(ws, kind, prefix, scenario)
        runs[scenario] = row
        report['scenarios'][scenario] = strip(row)
        print(scenario, GT.LABEL if row[GT.LABEL] else 'FAIL', row['launches'], 'recovered' if row['recovered'] else '',
              flush=True)
    report['totals'] = totals_of(ws, prefix, started)
    report['thinking_tokens_per_call'] = [dict(scenario=s, **{k: v for k, v in c.items() if k != 'model'})
                                          for s in SCENARIOS for c in report['scenarios'][s]['recovery']['calls']]
    if kind == 'fixture':
        import o1_dry as D
        D.dry_blocks(report, ws, runs)
    report['g3c'] = GT.suite_verdict(report)
    report['pass'] = report['g3c']['pass']
    report['finished_at'] = time.time()
    (ws / f'report-{kind}-{prefix}.json').write_text(json.dumps(report, indent=1, default=str) + '\n',
                                                     encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('freeze')
    p.add_argument('--write', action='store_true')
    sub.add_parser('measure')
    for name in ('dry', 'live'):
        p = sub.add_parser(name)
        p.add_argument('--workspace', required=True, type=Path)
        p.add_argument('--prefix', default={'dry': 'dry1', 'live': 'live1'}[name])
    p = sub.add_parser('run-flow')
    p.add_argument('--workspace', required=True, type=Path)
    p.add_argument('--kind', choices=('fixture', 'live'), required=True)
    p.add_argument('--prefix', required=True)
    p.add_argument('--scenario', choices=SCENARIOS, required=True)
    args = parser.parse_args(argv)
    if args.command == 'freeze':
        result = freeze(write=args.write)
        print(json.dumps(result, indent=1))
        return 0 if result['frozen'] else 1
    if args.command == 'measure':
        import o1_dry as D
        result = D.measure()
        print(json.dumps(result, indent=1))
        return 0 if result['pass'] else 1
    paid = args.command == 'live' or (args.command == 'run-flow' and args.kind == 'live')
    if paid and not os.environ.get(LIVE_ENV):
        print(f'live runs paid calls: set {LIVE_ENV}=1 to proceed', file=sys.stderr)
        return 2
    if args.command == 'run-flow':
        if args.kind == 'live':
            refusal = live_refusal(freeze(), cli_version())
            if refusal:
                print(refusal, file=sys.stderr)
                return 2
        ws = args.workspace.resolve()
        prepare(ws, args.kind)
        result = run_scenario_flow(ws, args.kind, args.prefix, args.scenario)
        print(J({k: result[k] for k in ('status', 'blocker', 'launches', 'targets')}))
        return 0 if result['status'] == 'delivered' else 3
    report = suite(args.workspace, 'fixture' if args.command == 'dry' else 'live', args.prefix)
    print(json.dumps({k: report.get(k) for k in ('gate', 'pass', 'g3c', 'totals', 'blocker')}, indent=1, default=str))
    return 0 if report.get('pass') else 3


if __name__ == '__main__':
    sys.exit(main())
