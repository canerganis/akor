"""Step 4 harness for inspection-handoff-20/v1 (executor conformance gate): G0 freeze, G2 dry gate, G3b live, G4 baseline.

    python bench/step4/step4.py freeze [--write]                 G0: verify (or write) every frozen digest (freeze-g3b.json)
    python bench/step4/step4.py dry --workspace DIR             G2: five scenarios, C3/C5, recovery fixtures, sabotage, zero tokens
    python bench/step4/step4.py live --workspace DIR            G3b: five scenarios through claude -p (paid, one fresh suite)
    python bench/step4/step4.py baseline --workspace DIR        G4: four no-orchestration calls (paid; refused live under G3b)
    python bench/step4/step4.py run-flow --workspace DIR --kind K --prefix P --scenario S   one flow invocation
    python bench/step4/step4.py replay-live1                     read-only predicate regression test on the live1 evidence
    python bench/step4/step4.py replay-live2                     read-only predicate run on the live2 evidence (not a verdict)

Every scenario runs through oz_flow.run_flow, which sends model stages through oz do (oz1g-selective-v1, durable
runner, per-job checks, memo, quota reservation, admission). The dry gate and the live run share every line except
the adapter (fixture_adapter.py versus examples/claude_cli_adapter.py), the route identity and the memo namespaces.
See docs/design/step4-2026-10-23/g3b/plan-frozen.md for the preregistered G3b commands, caps and expected launches.
The live1 run and its gate G3 (docs/design/step4-2026-10-23/plan-frozen.md, freeze.json) stay as recorded and failed.
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
import g3b as G  # noqa: E402
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
        'bench/step4/fixture_adapter.py', 'bench/step4/g3b.py', 'bench/step4/step4.py')
SCENARIOS = ('clean', 'repeat', 'interrupt', 'stale', 'bump')
RERUN: dict = {}  # scenario -> rerun number (dry gate tests only: G3b allows no scenario reruns)
FREEZE_RECORDS = ('freeze.json', 'freeze-g3b.json')  # freeze.json is the live1 record, kept intact; G3b writes its own
FREEZE_FILE = W.FROZEN / 'freeze-g3b.json'
ENTRY = Path(__file__).resolve()  # the command the interrupted scenario's hard-killed invocations run (adopt.py for v2)


def rid(prefix: str, scenario: str) -> str:
    return f'{prefix}-{scenario}' + (f'-r{RERUN[scenario]}' if scenario in RERUN else '')


def ndigest(path: Path) -> str:
    """SHA-256 with CRLF normalized to LF, so a checkout's line-ending conversion does not change identities."""
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def spec():
    return W.load('workflow.json')


def allocation() -> dict:
    """The G3b executor allocation (g3b.json). workflow.json's budgets.executor is live1's 60k/16/8, kept byte for byte."""
    return G.allocation()


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
    return sorted(p for p in W.FROZEN.rglob('*') if p.is_file() and p.name not in FREEZE_RECORDS)


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


def freeze(write=False, path=None) -> dict:
    base = W.FROZEN / 'baseline'
    if write:
        base.mkdir(exist_ok=True)
        (base / 'system.txt').write_text(BASELINE_SYSTEM, encoding='utf-8', newline='\n')
        for variant in ('rev1', 'rev2'):
            (base / f'prompt-{variant}.txt').write_text(baseline_prompt(variant), encoding='utf-8', newline='\n')
    current = digests()
    current['digest'] = hashlib.sha256(J(current).encode('utf-8')).hexdigest()
    path = Path(path) if path is not None else FREEZE_FILE
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
    # The stored per-file maps must still hash to the stored digest: a map edited together with its file would
    # otherwise pass the per-file comparison below.
    again = hashlib.sha256(J({'frozen': stored.get('frozen', {}), 'code': stored.get('code', {})}).encode('utf-8'))
    if stored.get('digest') != again.hexdigest():
        problems.append('the stored file maps do not hash to the stored digest')
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


def live_refusal(frozen: dict, version) -> str | None:
    """Why a paid run must not start (the freeze, the CLI version), or None. Shared by `live` and `run-flow --kind live`."""
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


def settings(ws: Path, kind: str, namespace: str, *, quota, registry=None, budget=None, route_fields=None):
    fields, model = route(kind)
    r = spec()['route' if kind == 'live' else 'fixture_route']
    return Settings(workspace=ws, adapter=adapter_file(ws, kind), registry=registry or W.registry(),
                    checks_registry=W.CHECKS, route=route_fields or fields, model=model,
                    memo_store=ws / 'memo.sqlite', namespace=namespace, quota=quota,
                    budget=allocation() if budget is None else budget, budget_scope=ws,
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


def _candidate_rows(run: Path) -> dict:
    """{(job, receipt): {status, value}} of a stage run's stored candidates (history included)."""
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
    """The executor's own recorded verdict of one member of one dispatch: its stored candidate's status mapped
    (an unknown status is recorded as such, never mapped to something else), or, when the reply produced no candidate
    for it, a failed call or no_candidate (the executor's columns do not say whether the reply was refused whole or
    held a model error line: g3b.judge_dispatch re-parses the preserved capture to say which)."""
    row = candidates.get((job, d['receipt']))
    if row is not None:
        return G.CANDIDATE_VERDICT.get(row['status'], 'unknown_status:' + str(row['status']))
    if outcome.get(job) in ('pending', 'failed'):
        return 'call_failed' if d['state'] == 'failed_call' else 'no_candidate'
    return 'unknown'


def _capture_evidence(run: Path, receipt: str):
    """The preserved runner capture of a receipt as plain data for the independent check, or None when there is none."""
    record = read_capture(run / 'captures', receipt)
    if record is None:
        return None
    return {'exit_code': record['exit_code'], 'start_failed': bool(record.get('start_failed')),
            'stdout_b64': record['stdout_b64']}


def trace_of(ws: Path, request_id: str) -> list:
    """The flow's dispatches in launch order as the plain records g3b.py audits. A stage's index counts the flow's
    stage runs that launched something; its refs are the exact input texts of the packet that was sent; its evidence is
    what the independent check re-reads (the preserved capture and each member's stored candidate)."""
    out, stage = [], 0
    for rel in stage_runs(ws, request_id):
        rows = stage_launches(ws / rel)
        if not rows:
            continue
        candidates = _candidate_rows(ws / rel)
        for d in sorted(rows, key=lambda r: (r['created_at'], len(r['receipt']), r['receipt'])):
            members = json.loads(d['members'])
            body = json.loads(d['packet'])
            # One ref per job is its input text, as shipped; an ordered two-ref job carries its refs as a list.
            refs = {row[0]: body['refs'][row[1]] if len(row) == 2 else [body['refs'][i] for i in row[1:]]
                    for block in body['jobs'] for row in block[1:]}
            outcome = json.loads(d['outcome']) if d['outcome'] else {}
            stored = {m['id']: candidates[(m['id'], d['receipt'])] for m in members
                      if (m['id'], d['receipt']) in candidates}
            out.append({'stage': stage, 'op': members[0]['id'].split('_')[0], 'receipt': d['receipt'], 'run_dir': rel,
                        'created_at': d['created_at'], 'state': d['state'],
                        'members': [{k: m[k] for k in ('id', 'generation', 'attempt', 'compute_key')} for m in members],
                        'refs': refs, 'verdicts': {m['id']: _member_verdict(d, m['id'], candidates, outcome)
                                                   for m in members},
                        'evidence': {'capture': _capture_evidence(ws / rel, d['receipt']), 'candidates': stored}})
        stage += 1
    return out


def _adapter_module():
    from importlib import util
    found = util.spec_from_file_location('cca', ROOT / 'examples' / 'claude_cli_adapter.py')
    module = util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


def calls_of(ws: Path, request_id: str, trace: list) -> list:
    """One row per physical call: tokens from the ledger's call_end record, thinking tokens from the raw CLI envelope
    the runner retained (modelUsage.thinkingTokens; None when the envelope does not report it)."""
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
        if not usage and envelope:  # a call killed after its capture has no call_end; its envelope still has usage
            usage = _adapter_module().usage_from_envelope(envelope) or {}
        tokens_in, tokens_out = usage.get('input_tokens'), usage.get('output_tokens')
        rows.append({'stage': d['stage'], 'receipt': d['receipt'], 'members': [m['id'] for m in d['members']],
                     'attempt': G.attempt_of(d), 'verdicts': G.shown_verdicts(d), 'input_tokens': tokens_in,
                     'output_tokens': tokens_out,
                     'tokens': tokens_in + tokens_out if type(tokens_in) is int and type(tokens_out) is int else None,
                     'thinking_tokens': G.envelope_thinking_tokens(envelope),
                     'model': sorted(envelope.get('modelUsage', {})) if envelope else None})
    return rows


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
                starts[r['batch_id']] = starts.get(r['batch_id'], 0) + 1  # lines, not distinct call IDs
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
    # Informational: dispatches that sent a member back to bounded recovery (a count of packets, not of members).
    out['reply_rejections'] = sum(1 for d in ds if d['outcome'] and 'pending' in json.loads(d['outcome']).values())
    # `pass` is the strict, count-based reading (live1's G3 label), reported apart. The binding label of G3b is
    # `pass_g3b`, set by g3b_finalize once the scenario's observables are attached.
    out['pass'] = (result['status'] == 'delivered' and not errors and out['launches'] == entry['expected_launches']
                   and out['packets'] == entry['expected_packets'] and out['memo_hits'] == entry['expected_memo_hits']
                   and out['deliveries'] == 1 and out['on_time'] and out['ledger']['ok']
                   and (kind != 'fixture' or out['fixture_invocations'] == out['launches']))
    out['trace'] = G.annotate(scenario, trace_of(ws, request_id))
    out['recovery'] = G.recovery_report(out['trace'], calls_of(ws, request_id, out['trace']))
    return out


def g3b_observation(out: dict, kind: str) -> dict:
    """What the G3b predicate reads from an audited scenario (plain data; the predicate imports nothing from here)."""
    entry = next(s for s in spec()['scenarios'] if s['name'] == out['scenario'])
    return {'scenario': out['scenario'], 'entry': entry, 'status': out['status'], 'deliveries': out['deliveries'],
            'on_time': out['on_time'], 'evaluator_errors': out['evaluator']['errors'], 'memo_hits': out['memo_hits'],
            'trace': out['trace'], 'ledger_ok': out['ledger']['ok'],
            'calls_without_usage': out['accounting']['calls_without_usage'],
            'per_flow_cap': allocation()['max_launches_per_flow'], 'observables': out.get('observables'),
            'fixture_invocations': out.get('fixture_invocations') if kind == 'fixture' else None}


def g3b_finalize(out: dict, kind: str) -> dict:
    """Apply the G3b predicate (pass_g3b, the one binding label) to an audited scenario, observables attached."""
    out['g3b'] = G.scenario_verdict(g3b_observation(out, kind))
    out[G.LABEL] = out['g3b'][G.LABEL]
    out['recovered'] = out['g3b']['recovered']
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
    # The order after the mutation is extract_A, bounds_A, the four classifications, then exactly the singleton
    # resends the frozen policy derives from the recorded verdicts (G3b; live1's strict list had no resends).
    derived, _ = G.derive('stale', G.effective_verdicts('stale', trace_of(ws, request_id)))
    start = G.config()['scenarios']['stale']['revised_from_stage']
    derived_order = [list(ids) for stage, ids, attempt in derived if stage >= start]
    primary_after = [list(ids) for stage, ids, attempt in derived if stage >= start and attempt == 1]
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
        'order_after_mutation_is_derived': order == derived_order and primary_after == [
            ['extract_A'], ['bounds_A'], ['classify_A', 'classify_B', 'classify_C', 'classify_D']],
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
                                                                budget=dict(allocation(), max_launches=0)))
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
    # Race between exporting the files and committing the delivery: the stale commit is refused and the flow must
    # recompute at a new generation and deliver the current revision; the stale files are never delivered.
    copy = copy_of(clean_copy, 'race-publish')
    publish_id = f'{prefix}-racepub'
    fired = []

    def publish_race(_name):
        f = Flow(flow_dir(copy, publish_id) / 'flow.sqlite')
        try:
            if not fired:
                fired.append(f.bump_source('A', (W.FROZEN / 'sources/A.rev2.txt').read_bytes(),
                                           reason='race after export'))
        finally:
            f.close()
    remove = oz_fault.on('flow.publish.after_manifest', publish_race)
    quota = quota_store(copy, 'fixture')
    try:
        res = run_flow(flow_request(prefix, 'racepub'), settings(copy, 'fixture', namespace('fixture', prefix, 'clean'),
                                                                 quota=quota))
    finally:
        quota.close()
        remove()
    f = Flow(flow_dir(copy, publish_id) / 'flow.sqlite')
    try:
        states = [e['state'] for e in f.effects()]
        ds = f.deliveries()
    finally:
        f.close()
    target = res['targets']['inspection_handoff']
    errs = (E.evaluate_package(copy / target['destination'], 'rev2', exp['revisions']['stale'])
            if target['status'] == 'delivered' else ['not delivered'])
    out['publish_race'] = {'caught': (bool(fired) and res['status'] == 'delivered' and not errs and len(ds) == 1
                                      and ds[0]['cites'].get('A') == 2 and states == ['superseded', 'delivered']),
                           'effect_states': states, 'delivery_cites': ds[0]['cites'] if ds else {},
                           'evaluator_errors': errs}
    return out


# ---- scenario suite ----

def run_interrupt(ws: Path, kind: str, prefix: str) -> list:
    """Hard kills at the preregistered boundaries; each resume is the same command with the same request identity."""
    cmd = [sys.executable, str(ENTRY), 'run-flow', '--workspace', str(ws), '--kind', kind,
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


def scenario_report(ws: Path, kind: str, prefix: str, scenario: str) -> dict:
    """One scenario: its flow (the interrupted one takes its two hard kills first), the audit, the scenario's
    observables, and the G3b verdict."""
    exits = run_interrupt(ws, kind, prefix) if scenario == 'interrupt' else None
    result = run_scenario_flow(ws, kind, prefix, scenario)  # for interrupt: reads the settled state, no new work
    out = audit(ws, kind, prefix, scenario, result)
    if scenario == 'interrupt':
        out['observables'] = interrupt_observables(ws, prefix, exits)
    if scenario == 'stale':
        out['observables'] = stale_observables(ws, prefix)
    return g3b_finalize(out, kind)


def fresh_refusal(ws: Path) -> str | None:
    """G3b runs one suite in a fresh workspace: no earlier flow and no earlier memo entry."""
    flows = ws / 'flows'
    if (flows.exists() and any(flows.iterdir())) or (ws / 'memo.sqlite').exists():
        return 'the workspace is not fresh (G3b is one suite in a fresh workspace); nothing was launched'
    return None


# ---- G3b dry gate: recovery fixtures, predicate sabotage and allocation feasibility (zero tokens) ----

RECOVERY_CASES = (
    # name, scenario, fixture mode, expected: pass_g3b, primary-plus-recovery packet sizes
    ('two_siblings_rejected', 'clean', {'wrong_first': ['classify_A', 'classify_C']}, True, [4, 4, 4, 1, 1]),
    ('three_siblings_rejected', 'clean', {'wrong_first': ['classify_A', 'classify_B', 'classify_C']}, True,
     [4, 4, 4, 1, 1, 1]),
    ('four_rejected_one_size4_resend', 'clean',
     {'wrong_first': ['classify_A', 'classify_B', 'classify_C', 'classify_D']}, True, [4, 4, 4, 4]),
    ('wire_rejected_whole_packet', 'clean', {'wire_reject_first': ['classify_B']}, True, [4, 4, 4, 4]),
    ('wire_rejected_early_stage', 'clean', {'wire_reject_first': ['extract_A']}, True, [4, 4, 4, 4]),
    ('early_stage_rejections', 'clean', {'wrong_first': ['extract_B', 'bounds_D']}, True, [4, 1, 4, 1, 4]),
    ('stale_with_recovery', 'stale', {'wrong_first': ['classify_C']}, True, [4, 4, 1, 1, 4, 1]),
    ('stale_rejections_before_and_after_mutation', 'stale', {'wrong_first': ['extract_A']}, True,
     [4, 1, 4, 1, 1, 1, 4]),
    ('interrupt_with_recovery', 'interrupt', {'wrong_first': ['classify_A', 'classify_C']}, True, [4, 4, 4, 1, 1]),
    ('second_attempt_fails', 'clean', {'wrong_always': ['classify_C']}, False, [4, 4, 4, 1]),
    ('verifier_outage_holds', 'clean', {}, False, [4, 4, 4]))


class _fixture_env:
    """Restore OZ_FIXTURE_DIR after a case: prepare() points it at the case workspace."""
    def __enter__(self):
        self.saved = os.environ.get('OZ_FIXTURE_DIR')

    def __exit__(self, *_):
        if self.saved is None:
            os.environ.pop('OZ_FIXTURE_DIR', None)
        else:
            os.environ['OZ_FIXTURE_DIR'] = self.saved


def fixture_case(base: Path, name: str, mode: dict, scenarios, prefix: str, *, outage=False) -> tuple:
    """A fresh fixture workspace with the given adapter mode; each scenario runs through scenario_report."""
    ws = (base / name).resolve()
    if ws.exists():
        shutil.rmtree(ws)
    prepare(ws, 'fixture')
    (ws / 'fixture' / 'mode.json').write_text(json.dumps(mode), encoding='utf-8')
    outs = {}
    from unittest.mock import patch
    checks = dict(W.CHECKS)
    if outage:
        from dataclasses import replace
        from oz_accept import Unavailable

        def unavailable(value, spec_, inputs):
            raise Unavailable('verifier down')
        name = spec()['model_ops']['model.classify']['checks'][0]['check']  # the classify op's own check
        checks[name] = replace(W.CHECKS[name], run=unavailable)
    with patch.object(W, 'CHECKS', checks):
        for scenario in scenarios:
            outs[scenario] = scenario_report(ws, 'fixture', prefix, scenario)
    return ws, outs


def recovery_fixtures(ws: Path, prefix: str) -> tuple:
    """Run every recovery case through the real executor and the G3b predicate. A case passes when the predicate says
    what the case expects (pass_g3b True for a recovery the policy allows; False, with the exact trace still equal to
    the derived one, for a second-attempt failure or a verifier outage)."""
    base = ws.parent / (ws.name + '.g3b')
    report, runs = {}, {}
    with _fixture_env():
        for name, scenario, mode, expect_pass, packets in RECOVERY_CASES:
            case_ws, outs = fixture_case(base, name, mode, [scenario], prefix, outage=name == 'verifier_outage_holds')
            out = outs[scenario]
            verdict = out['g3b']
            observed = {'pass_g3b': verdict[G.LABEL], 'recovered': verdict['recovered'], 'launches': out['launches'],
                        'packets': out['packets'], 'rejected_jobs': out['recovery']['rejected_jobs'],
                        'failed_checks': sorted(k for k, v in verdict['checks'].items() if not v),
                        'blocked': verdict['blocked'], 'status': out['status'],
                        'thinking_tokens': [c['thinking_tokens'] for c in out['recovery']['calls']]}
            ok = observed['pass_g3b'] is expect_pass and observed['packets'] == packets
            if expect_pass:
                ok = ok and observed['recovered'] and not observed['failed_checks']
            else:
                # A refused scenario must still show exactly the derived trace: no third attempt, no resend of a held
                # member; only delivery and the unresolved stage fail.
                ok = ok and verdict['checks']['exact_trace'] and verdict['checks']['recovery_eligibility'] \
                    and verdict['checks']['no_unresolved_stage'] is False
            report[name] = {'pass': bool(ok), 'expected': {'pass_g3b': expect_pass, 'packets': packets},
                            'observed': observed}
            runs[name] = {'ws': case_ws, 'out': out, 'scenario': scenario}
    return report, runs


EXECUTOR_OF = {'accepted': 'accepted', 'check_rejected': 'check_rejected', 'held': 'held', 'call_failed': 'call_failed',
               'wire_rejected': 'no_candidate', 'model_error': 'no_candidate'}


def synthetic_facts(scenario: str, stage: int, jobs, story: dict) -> tuple:
    """(executor verdicts, evidence) a dispatch would leave for the given story {job: independent verdict} (default
    accepted): the stored candidates, the executor's own labels and a runner capture whose reply says the same. Used to
    build the sabotaged traces and the pure tests; a wire rejection makes the whole reply invalid and a call failure
    leaves a capture of a failed process, so only an edited story (some member accepted next to a wire rejection) can
    contradict the preserved capture."""
    candidates, lines = {}, [G.HEADER]
    for job in jobs:
        kind = story.get(job, 'accepted')
        right = json.dumps(G.expected_value(scenario, stage, job), separators=(',', ':'))
        if kind in ('accepted', 'held'):
            candidates[job] = {'status': 'accepted' if kind == 'accepted' else 'awaiting', 'value': right}
            lines.append(json.dumps({job: json.loads(right)}, separators=(',', ':')))
        elif kind == 'check_rejected':
            candidates[job] = {'status': 'rejected', 'value': '"wrong"'}
            lines.append(json.dumps({job: 'wrong'}))
        elif kind == 'model_error':
            lines.append(json.dumps([job, 'error', 'missing_data', 'the record has no such field']))
    failed = any(story.get(j) == 'call_failed' for j in jobs)
    wire = any(story.get(j) == 'wire_rejected' for j in jobs)
    reply = 'this is not an OZ/1g reply' if wire else '\n'.join(lines)
    stdout = json.dumps({'reply': reply, 'usage': {'input_tokens': 1, 'output_tokens': 1}}).encode('utf-8')
    capture = {'exit_code': 1 if failed else 0, 'start_failed': False, 'stdout_b64': base64.b64encode(stdout).decode()}
    if failed:
        candidates = {}
    return ({job: EXECUTOR_OF[story.get(job, 'accepted')] for job in jobs},
            {'capture': capture, 'candidates': candidates})


def _mutated(trace: list, edit) -> list:
    import copy
    out = copy.deepcopy(trace)
    edit(out)
    return out


def _restory(dispatch: dict, scenario: str, **story) -> None:
    """Rewrite one recorded dispatch's executor verdicts and evidence for an edited story, starting from what the
    independent check currently says about it."""
    current = G.judge_dispatch(scenario, dispatch)['verdicts']
    full = {m['id']: current[m['id']] or 'accepted' for m in dispatch['members']}
    full.update(story)
    dispatch['verdicts'], dispatch['evidence'] = synthetic_facts(scenario, dispatch['stage'], list(full), full)


def _like(dispatch: dict, pool: list, *, members=None, attempt=None, receipt=None, verdict='accepted',
          refs=None, scenario='clean', stage=None, **story) -> dict:
    """A copy of a recorded dispatch for building the sabotaged traces; members are taken (identity, generation and
    input) from the first record of that member in pool, so only the edited rule is broken. Its verdicts and evidence
    are the ones an executor following the story would leave."""
    import copy
    d = copy.deepcopy(dispatch)
    if members is not None:
        known = {m['id']: (m, x['refs'][m['id']]) for x in reversed(pool) for m in x['members']}
        d['members'] = [dict(known[j][0]) for j in members]
        d['refs'] = {j: known[j][1] for j in members}
    for m in d['members']:
        if attempt is not None:
            m['attempt'] = attempt
    if stage is not None:
        d['stage'] = stage
    if refs:
        d['refs'].update(refs)
    d['receipt'] = receipt or d['receipt'] + 'x'
    jobs = [m['id'] for m in d['members']]
    d['verdicts'], d['evidence'] = synthetic_facts(scenario, d['stage'], jobs, dict({j: verdict for j in jobs}, **story))
    return d


def _renumbered(trace: list) -> list:
    """Launch times in trace order (a sabotaged trace keeps its own rules broken only: order is checked separately)."""
    import copy
    out = copy.deepcopy(trace)
    base = min((d['created_at'] for d in out), default=0)
    for i, d in enumerate(out):
        d['created_at'] = base + i
    return out


def g3b_sabotage(runs: dict) -> dict:
    """Each sabotage is a recorded real trace edited to break exactly one rule, run through the same predicate; it is
    caught when pass_g3b turns False and the expected finding is among the reasons. The regeneration cases have the
    shape the executor can produce (a new run directory and stage index, attempt 1, generation 1): the executor never
    changes a member's generation or computation inside one stage, so no sabotage case fakes that."""
    two, stale = runs['two_siblings_rejected'], runs['stale_with_recovery']
    wire, outage = runs['wire_rejected_whole_packet'], runs['verifier_outage_holds']
    early = runs['early_stage_rejections']
    old_a = W.source_bytes('A').decode('utf-8')

    def swap_tail(trace, new):  # replace the two singleton resends (last two dispatches)
        return trace[:-2] + new

    cases = {}

    def add(name, base, trace, code, *, order=False):
        cases[name] = (base, trace if order else _renumbered(trace), code)
    t = two['out']['trace']
    first_packet, resend_a, resend_c = t[2], t[3], t[4]
    add('whole_packet_resend', two, swap_tail(t, [_like(first_packet, t, attempt=2, receipt='w1')]),
        'accepted_member_resent')
    add('accepted_member_resend', two, t + [_like(first_packet, t, members=['classify_B'], attempt=2, receipt='w2')],
        'accepted_member_resent')
    add('size_2_resend', two, swap_tail(t, [_like(first_packet, t, members=['classify_A', 'classify_C'], attempt=2,
                                                  receipt='w3')]), 'trace_mismatch')
    add('third_attempt', two, _mutated(t, lambda x: _restory(x[3], 'clean', classify_A='check_rejected'))
        + [_like(resend_a, t, attempt=3, receipt='w4')], 'third_attempt')
    add('skipped_resend_then_delivery', two, t[:-1], 'trace_mismatch')
    add('resends_out_of_order', two, swap_tail(t, [resend_c, resend_a]), 'trace_mismatch')
    add('resend_other_computation', two, _mutated(t, lambda x: x[3]['members'][0].update(compute_key='f' * 64)),
        'identity_mismatch')
    add('resend_with_stale_input', two, _mutated(t, lambda x: x[3]['refs'].update(
        classify_A=W.source_bytes('A', 'rev2').decode('utf-8'))), 'stale_input')
    add('old_A_bytes_after_mutation', stale, _mutated(stale['out']['trace'], lambda x: [
        d['refs'].update(classify_A=old_a) for d in x if d['stage'] == 4]), 'stale_input')
    add('exhausted_quota_launch_beyond_cap', two, t + [_like(resend_a, t, attempt=2, receipt=f'q{i}')
                                                       for i in range(8)], 'launch_cap_exceeded')
    tw = wire['out']['trace']
    add('wire_rejection_resent_as_singletons', wire, tw[:-1] + [
        _like(tw[-1], tw, members=[j], attempt=2, receipt=f'v{j}') for j in
        [m['id'] for m in tw[-1]['members']]], 'trace_mismatch')

    def not_atomic(x):  # the executor stored a candidate for A although the preserved reply is refused whole
        x[2]['verdicts']['classify_A'] = 'accepted'
        x[2]['evidence']['candidates']['classify_A'] = {'status': 'accepted', 'value': '"inside"'}
    add('wire_rejection_not_atomic', wire, _mutated(tw, not_atomic), 'wire_rejection_not_atomic')
    to = outage['out']['trace']
    add('verifier_outage_triggers_regeneration', outage, to + [_like(to[-1], to, attempt=1, receipt='o1',
                                                                    stage=to[-1]['stage'] + 1)], 'trace_mismatch')
    add('verifier_outage_triggers_resend', outage, to + [_like(to[-1], to, attempt=2, receipt='o2')],
        'held_member_resent')
    # The independent check: each stored candidate against the frozen expected values, each missing candidate against the
    # preserved capture.

    def reject_correct(x):  # a host check bug: the executor rejects a correct classify_B, then resends it
        _restory(x[2], 'clean', classify_A='check_rejected', classify_C='check_rejected')
        x[2]['verdicts']['classify_B'] = 'check_rejected'
        x[2]['evidence']['candidates']['classify_B']['status'] = 'rejected'
    spurious = _mutated(t[:3], reject_correct)
    add('executor_rejects_a_correct_answer', two, spurious + [
        _like(first_packet, t, members=[j], attempt=2, receipt=f'r{j}') for j in ('classify_A', 'classify_B',
                                                                                  'classify_C')],
        'verdict_disagreement')

    def accept_wrong(x):  # the executor accepts a wrong value for classify_D (no resend follows)
        x[2]['evidence']['candidates']['classify_D']['value'] = '"outside"'
    add('executor_accepts_a_wrong_answer', two, _mutated(t, accept_wrong), 'verdict_disagreement')

    def refuse_valid(x):  # the executor claims a wire rejection, the preserved reply is a valid one
        x[2]['verdicts'] = dict.fromkeys(x[2]['verdicts'], 'no_candidate')
        x[2]['evidence']['candidates'] = {}
    add('wire_rejection_claimed_for_a_valid_reply', two, _mutated(t[:3], refuse_valid) + [
        _like(first_packet, t, attempt=2, receipt='z1')], 'verdict_disagreement')

    def superseded(x):
        x[2]['verdicts']['classify_D'] = 'unknown_status:superseded'
        x[2]['evidence']['candidates']['classify_D']['status'] = 'superseded'
    add('unknown_candidate_status', two, _mutated(t, superseded), 'unknown_status')

    def cross_stage(x):  # the extract_B resend is launched after the bounds primary packet
        x[1]['created_at'] = x[2]['created_at'] + 0.5
    ge = early['out']['trace']
    add('resend_launched_after_the_next_stage', early, _mutated(ge, cross_stage), 'launch_order', order=True)
    report = {}
    for name, (base, trace, code) in cases.items():
        # fixture_invocations is dropped so that only the trace rules judge the edited trace.
        verdict = G.scenario_verdict(dict(g3b_observation(base['out'], 'fixture'), trace=trace,
                                          fixture_invocations=None))
        codes = sorted({e['code'] for e in verdict['errors']})
        report[name] = {'caught': (not verdict[G.LABEL]) and code in codes, 'expected_finding': code,
                        'findings': codes,
                        'failed_checks': sorted(k for k, v in verdict['checks'].items() if not v)}
    # Two ledger edits, each on a copy of a real recovery run's ledger: a recovered capture counted as another physical
    # invocation (a replayed call_start with a new call ID) and one call counted twice (the same call_start line
    # twice, same call ID, which a set of call IDs would merge).
    for name, same_id in (('recovered_capture_counted_as_launch', False), ('one_call_counted_twice_same_call_id', True)):
        copy = copy_of(two['ws'], 'sab-' + name)
        request_id = rid(g3b_prefix(two), 'clean')
        first = dispatches(copy, request_id)[0]
        ledger = copy / first['run_dir'] / 'calls.jsonl'
        start = next(json.loads(x) for x in ledger.read_text(encoding='utf-8').splitlines()
                     if json.loads(x).get('batch_id') == first['receipt'] and json.loads(x).get('event') == 'call_start')
        with ledger.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(start if same_id else dict(start, call_id='replayed-' + start['call_id'])) + '\n')
        audit_after = ledger_audit(copy, request_id)
        verdict = G.scenario_verdict(dict(g3b_observation(two['out'], 'fixture'), ledger_ok=audit_after['ok']))
        report[name] = {'caught': (not audit_after['ok']) and not verdict[G.LABEL], 'expected_finding': 'ledger',
                        'findings': audit_after['problems'][:2],
                        'failed_checks': sorted(k for k, v in verdict['checks'].items() if not v)}
    return report


def g3b_prefix(run: dict) -> str:
    return run['out']['request_id'].rsplit('-', 1)[0]


def feasibility_fixtures(ws: Path, prefix: str) -> dict:
    """Reservation feasibility under the G3b caps, with fixture calls reporting live1-sized usage (about 2.7k tokens):
    admission lets recovery through while it fits, refuses at the scenario launch cap and at the token reserve, and a
    refusal is never a pass."""
    base = ws.parent / (ws.name + '.g3b')
    cap = allocation()
    usage = {'input': 2600, 'output': 80}
    report = {}
    cases = (
        ('two_rejected_in_each_cold_scenario', {'wrong_first': ['classify_A', 'classify_C'], 'usage': usage},
         ('clean', 'interrupt', 'stale'), True),
        ('three_rejected_in_each_cold_scenario', {'wrong_first': ['classify_A', 'classify_B', 'classify_C'],
                                                  'usage': usage}, ('clean', 'interrupt', 'stale'), True),
        ('scenario_launch_cap_exhausted', {'wrong_first': ['extract_A', 'extract_B', 'extract_C', 'bounds_A',
                                                           'bounds_B', 'bounds_C', 'classify_A', 'classify_B',
                                                           'classify_C'], 'usage': usage}, ('clean',), False),
        ('token_reserve_refuses_third_launch', {'usage': {'input': 30000, 'output': 80}}, ('clean',), False))
    with _fixture_env():
        for name, mode, scenarios, expect_pass in cases:
            case_ws, outs = fixture_case(base, 'feasibility-' + name, mode, scenarios, prefix)
            launches = sum(o['launches'] for o in outs.values())
            calls = [c for o in outs.values() for c in o['recovery']['calls']]
            tokens, peak = 0, 0
            for c in calls:  # tokens admitted so far plus the reserve this launch needed
                peak = max(peak, tokens + cap['reserve_per_launch'])
                tokens += c['tokens'] or 0
            reasons = sorted({str((o['blocker'] or {}).get('jobs', {}).get(j, {}).get('reason'))
                              for o in outs.values() for j in ((o['blocker'] or {}).get('jobs') or {})})
            passed = all(o[G.LABEL] for o in outs.values())
            ok = passed is expect_pass and launches <= cap['max_launches'] and peak <= cap['max_tokens']
            if expect_pass:
                ok = ok and not reasons
            elif name == 'scenario_launch_cap_exhausted':
                ok = ok and launches == cap['max_launches_per_flow'] and 'flow_launch_cap' in reasons
            else:
                ok = ok and launches == 2 and 'token_cap' in reasons
            report[name] = {'pass': bool(ok), 'all_pass_g3b': passed, 'launches': launches, 'tokens': tokens,
                            'peak_tokens_plus_reserve': peak, 'refusals': reasons,
                            'caps': {k: cap[k] for k in ('max_tokens', 'max_launches', 'max_launches_per_flow')}}
    return report


def suite(ws: Path, kind: str, prefix: str, only: str | None = None) -> dict:
    """The five scenarios in order with their checks and the G3b verdict. `only` runs one scenario and skips the
    clean-state checks, which need the clean run (dry gate tests; a live G3b is one suite with no scenario reruns)."""
    ws = ws.resolve()
    prepare(ws, kind)
    report = {'gate': 'G3b dry' if kind == 'fixture' else 'G3b live', 'kind': kind, 'prefix': prefix,
              'freeze': freeze(), 'started_at': time.time(), 'scenarios': {}}
    if kind == 'live':
        version = cli_version()
        report['cli_version'] = version
        refusal = live_refusal(report['freeze'], version) or fresh_refusal(ws)
        if refusal:
            report['blocker'] = refusal
            return report
    clean_copy = None
    for scenario in ([only] if only else SCENARIOS):
        report['scenarios'][scenario] = scenario_report(ws, kind, prefix, scenario)
        if scenario == 'clean':
            clean_copy = copy_of(ws, 'clean-state')
        row = report['scenarios'][scenario]
        print(scenario, G.LABEL if row[G.LABEL] else 'FAIL', row['launches'], 'recovered' if row['recovered'] else '',
              flush=True)
    if only:
        report['pass'] = (report['freeze']['frozen'] and all(s[G.LABEL] for s in report['scenarios'].values()))
        (ws / f'report-{kind}-{prefix}-{only}-r{RERUN.get(only, 0)}.json').write_text(
            json.dumps(report, indent=1, default=str) + '\n', encoding='utf-8')
        return report
    report['c5'] = c5_checks(ws, kind, prefix, clean_copy)
    if kind == 'fixture':
        report['sabotage'] = sabotage(ws, prefix, clean_copy, ws)
        report['recovery'], runs = recovery_fixtures(ws, 'g3b')
        report['g3b_sabotage'] = g3b_sabotage(runs)
        report['feasibility'] = feasibility_fixtures(ws, 'g3b')
        os.environ['OZ_FIXTURE_DIR'] = str(ws / 'fixture')
        report['baseline_smoke'] = baseline(ws, kind='fixture', calls=[('rev1', 1), ('rev2', 1)])
    usage = [flow_usage(ws, rid(prefix, s)) for s in SCENARIOS]
    report['totals'] = {'launches': sum(u['launches'] for u in usage),
                        'tokens_known': sum(u['tokens_known'] for u in usage),
                        'calls_without_usage': sum(u['calls_without_usage'] for u in usage),
                        'caps': allocation()}
    report['totals']['accounting'] = 'complete' if report['totals']['calls_without_usage'] == 0 else 'incomplete'
    # Per call, apart from the verdict: thinking tokens next to the members' first verdicts. An observed association
    # on the recorded calls, not an established cause.
    report['thinking_tokens_per_call'] = [
        dict(scenario=s, **{k: v for k, v in c.items() if k != 'model'})
        for s in SCENARIOS for c in report['scenarios'][s]['recovery']['calls']]
    report['g3b'] = G.suite_verdict(report)
    report['pass'] = report['g3b']['pass']
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
        p.add_argument('--prefix', default={'dry': 'dry1', 'live': G.config()['identity']['prefix'], 'baseline': ''}[name])
        if name != 'baseline':
            p.add_argument('--only', choices=SCENARIOS, help='run one scenario (dry gate only; refused for live under G3b)')
            p.add_argument('--rerun', type=int, default=0, help='rerun number (dry gate only; refused for live under G3b)')
    sub.add_parser('replay-live1', help='read-only predicate regression test on the retained live1 evidence')
    sub.add_parser('replay-live2', help='read-only predicate run on the retained live2 evidence (not a verdict)')
    p = sub.add_parser('run-flow')
    p.add_argument('--workspace', required=True, type=Path)
    p.add_argument('--kind', choices=('fixture', 'live'), required=True)
    p.add_argument('--prefix', required=True)
    p.add_argument('--scenario', choices=SCENARIOS, required=True)
    p.add_argument('--rerun', type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == 'live' and (args.only or args.rerun):
        print('G3b is one suite with no scenario reruns: --only and --rerun are refused for live', file=sys.stderr)
        return 2
    if getattr(args, 'rerun', 0):
        key = getattr(args, 'only', None) or getattr(args, 'scenario', None)
        if key is None:
            parser.error('--rerun needs --only SCENARIO')
        RERUN[key] = args.rerun
    if args.command in ('replay-live1', 'replay-live2'):
        print(json.dumps(G.replay_live1() if args.command == 'replay-live1' else G.replay_live2(), indent=1))
        return 0
    if args.command == 'baseline':
        print('G4 carries forward from live1; G3b allocates no baseline launches', file=sys.stderr)
        return 2
    if args.command == 'freeze':
        result = freeze(write=args.write)
        print(json.dumps(result, indent=1))
        return 0 if result['frozen'] else 1
    paid_flow = args.command == 'run-flow' and args.kind == 'live'
    if (args.command in ('live', 'baseline') or paid_flow) and not os.environ.get('STEP4_LIVE_CONFIRM'):
        print('live and baseline run paid calls: set STEP4_LIVE_CONFIRM=1 to proceed', file=sys.stderr)
        return 2
    if paid_flow:
        refusal = live_refusal(freeze(), cli_version())
        if refusal:
            print(refusal, file=sys.stderr)
            return 2
    if args.command == 'run-flow':
        ws = args.workspace.resolve()
        prepare(ws, args.kind)
        result = run_scenario_flow(ws, args.kind, args.prefix, args.scenario)
        print(J({k: result[k] for k in ('status', 'blocker', 'launches', 'targets')}))
        return 0 if result['status'] == 'delivered' else 3
    if args.command == 'baseline':
        result = baseline(args.workspace)
        print(json.dumps(result, indent=1))
        return 0 if result['pass'] else 3
    report = suite(args.workspace, 'fixture' if args.command == 'dry' else 'live', args.prefix, args.only)
    print(json.dumps({k: report.get(k) for k in ('gate', 'pass', 'g3b', 'totals', 'blocker')}, indent=1, default=str))
    return 0 if report.get('pass') else 3


if __name__ == '__main__':
    sys.exit(main())
