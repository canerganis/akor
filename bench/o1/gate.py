"""G3c-O1: the exact-trace predicate for repair-handoff-20/v1 (docs/design/o1-real-workflow-2026-10-23/).

Standard library only. It imports nothing from the executor or its checks (oz*.py, workflow.py, sandbox_worker.py);
it reads the frozen workflow.json and plain data the harness hands it, and judges every candidate through the
independent evaluator (evaluator/evaluator.py), reusing g3b's executor-free OZ/1g reply parser. It holds:

  judge_dispatch     independent member verdicts: every preserved capture is re-parsed, every value line is judged
                     against the exact recorded input (A tier, the evaluator's own worker), rejected candidates too; a
                     disagreement with the executor's record is a finding (false acceptance or false rejection)
  derive             the dispatch sequence the frozen recovery policy must produce from those verdicts; a valid model
                     failure record is terminal (M10), a held member blocks, no third attempt
  trace_errors       per-launch eligibility (grounds, attempt, generation, identity, current input records, order,
                     launch cap) plus the exact-trace comparison
  scenario_verdict   pass_g3c for one scenario (delivery verified by the evaluator on A, I and H with byte provenance)
  suite_verdict      G3c-O1 over the five scenarios and the allocation (plus the dry-gate items)
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'evaluator'))

import evaluator as E  # noqa: E402

FROZEN = HERE / 'repair-handoff-20-v1'
LABEL = 'pass_g3c'
CANDIDATE_VERDICT = {'accepted': 'accepted', 'rejected': 'check_rejected', 'awaiting': 'held', 'quarantined': 'held'}
EXECUTOR_VERDICTS = frozenset({'accepted', 'check_rejected', 'held', 'call_failed', 'no_candidate'})
RESENDABLE = frozenset({'check_rejected', 'wire_rejected', 'call_failed', 'no_candidate'})
TERMINAL = frozenset({'model_error'})
INDEPENDENCE_CODES = frozenset({'verdict_disagreement', 'independent_evidence_missing', 'capture_not_preserved',
                                'candidate_reply_mismatch', 'wire_rejection_not_atomic', 'unknown_status',
                                'verdict_unrecorded', 'evaluator_unavailable', 'memo_provenance'})


def config() -> dict:
    return json.loads((FROZEN / 'workflow.json').read_text(encoding='utf-8'))


def entry(scenario: str, cfg=None) -> dict:
    return next(s for s in (cfg or config())['scenarios'] if s['name'] == scenario)


# ---- independent member verdicts ----

def agrees(executor: str, independent: str) -> bool:
    if executor == 'no_candidate':
        return independent in ('wire_rejected', 'model_error')
    return executor == independent


def judge_dispatch(scenario: str, d: dict) -> dict:
    """{'verdicts': {job: verdict or None}, 'values': {job: decoded value line}, 'findings': [...], 'wire': reason}."""
    ids = [m['id'] for m in d['members']]
    evidence = d.get('evidence')
    if not isinstance(evidence, dict):
        return {'verdicts': dict.fromkeys(ids), 'values': {}, 'findings': [{'code': 'independent_evidence_missing'}],
                'wire': None}
    findings, verdicts, values = [], {}, {}
    candidates = evidence.get('candidates') or {}
    kind, detail, lines = E.capture_lines(evidence.get('capture'), ids)
    wire = detail if kind == 'wire' else None
    if wire is not None and any(j in candidates for j in ids):
        findings.append({'code': 'wire_rejection_not_atomic', 'reason': wire,
                         'jobs': [j for j in ids if j in candidates]})
    for job in ids:
        executor = d['verdicts'].get(job, 'unknown')
        candidate = candidates.get(job)
        independent = None

        def add(code, **more):
            findings.append(dict(code=code, job=job, **more))
        line = lines.get(job)
        if line is not None and line[0] == 'value':
            values[job] = line[1]
        if candidate is not None:
            mapped = CANDIDATE_VERDICT.get(candidate.get('status'))
            if mapped is None:
                add('unknown_status', status=candidate.get('status'))
            try:
                stored = json.loads(candidate['value'])
            except (ValueError, TypeError, KeyError):
                stored = None
            if kind == 'call_failed':
                add('candidate_reply_mismatch', reason='a candidate exists but the capture shows a failed call')
            elif kind == 'ok' and (line is None or line[0] != 'value' or line[1] != stored):
                add('candidate_reply_mismatch', reason='the stored candidate is not the value in the preserved reply')
            if mapped == 'held':
                independent = 'held'
            elif mapped is not None:
                try:
                    independent = E.judge_candidate((d.get('refs') or {}).get(job), stored)['verdict']
                except E.EvaluatorUnavailable as exc:
                    add('evaluator_unavailable', reason=str(exc)[:120])
        elif kind == 'missing':
            if executor == 'call_failed':
                independent = 'call_failed'
            else:
                add('capture_not_preserved', executor=executor)
        elif kind == 'call_failed':
            independent = 'call_failed'
        elif wire is not None:
            independent = 'wire_rejected'
        elif line is not None and line[0] == 'error':
            independent = 'model_error'
        else:
            add('verdict_disagreement', executor=executor, independent='valid_reply_without_candidate')
        if executor == 'unknown':
            add('verdict_unrecorded')
        elif executor not in EXECUTOR_VERDICTS:
            if not any(f['code'] == 'unknown_status' and f.get('job') == job for f in findings):
                add('unknown_status', verdict=executor)
        elif independent is not None and not agrees(executor, independent):
            add('verdict_disagreement', executor=executor, independent=independent,
                kind='false_rejection' if independent == 'accepted' else 'false_acceptance'
                if executor == 'accepted' else 'other')
        verdicts[job] = independent
    return {'verdicts': verdicts, 'values': values, 'findings': findings, 'wire': wire}


def annotate(scenario: str, trace) -> list:
    out = []
    for d in trace:
        judged = judge_dispatch(scenario, d)
        out.append(dict(d, independent={j: v or 'unverified' for j, v in judged['verdicts'].items()},
                        independent_findings=judged['findings'], values=judged['values']))
    return out


# ---- the policy oracle ----

def plan_sizes(count: int, sizes) -> list:
    out = []
    while count > 0:
        fit = max((s for s in sizes if s <= count), default=count)
        out.append(fit)
        count -= fit
    return out


def attempt_of(d: dict) -> int:
    attempts = {m['attempt'] for m in d['members']}
    return attempts.pop() if len(attempts) == 1 else 0


def actual_sequence(trace) -> list:
    return [(d['stage'], tuple(m['id'] for m in d['members']), attempt_of(d)) for d in trace]


def effective(d: dict, judged: dict) -> dict:
    return {m['id']: judged['verdicts'].get(m['id']) or d['verdicts'].get(m['id'], 'unknown') for m in d['members']}


def verdict_map(trace, verdicts) -> dict:
    out = {}
    for i, d in enumerate(trace):
        for m in d['members']:
            out.setdefault((d['stage'], m['id'], m['attempt']), verdicts[i].get(m['id'], 'unknown'))
    return out


def derive(scenario: str, verdicts: dict, cfg=None):
    """(sequence, blocked) the frozen policy produces from verdicts alone (see workflow.json recovery.rule)."""
    cfg = cfg or config()
    sizes, last = tuple(cfg['recovery']['packet_sizes']), cfg['recovery']['max_attempts']
    sequence, blocked = [], None
    for stage, (op, members) in enumerate(entry(scenario, cfg)['stages']):
        sequence.append((stage, tuple(members), 1))
        v1 = {j: verdicts.get((stage, j, 1)) for j in members}
        pending = [j for j in members if v1[j] in RESENDABLE]
        held = [j for j in members if v1[j] == 'held']
        terminal = [j for j in members if v1[j] in TERMINAL]
        attempt = 1
        while pending and attempt < last:
            attempt += 1
            at = 0
            for size in plan_sizes(len(pending), sizes):
                sequence.append((stage, tuple(pending[at:at + size]), attempt))
                at += size
            now = {j: verdicts.get((stage, j, attempt)) for j in pending}
            held += [j for j in pending if now[j] == 'held']
            terminal += [j for j in pending if now[j] in TERMINAL]
            pending = [j for j in pending if now[j] in RESENDABLE]
        if pending or held or terminal:
            blocked = {'stage': stage, 'op': op, 'exhausted': pending, 'held': held, 'model_failure': terminal}
            break
    return sequence, blocked


def _listed(sequence) -> list:
    return [[s, list(ids), a] for s, ids, a in sequence]


def expected_record(scenario, stage, job, cores, cfg=None):
    """The exact record text a model job must carry at this stage: the frozen core record at the revision in force,
    or the frozen adapter record prefix plus the core source accepted for that ticket before this stage."""
    cfg = cfg or config()
    e = entry(scenario, cfg)
    name = job.rsplit('_', 1)[1]
    rev = (e['revised_revision'] if e.get('revised_from_stage') is not None and stage >= e['revised_from_stage']
           and name == e['revised_source'] else 1)
    t = E.ticket(name, rev)
    if job.startswith('core_'):
        return t['core_record']
    core = cores.get('core_' + name)
    return None if core is None else t['adapter_record_prefix'] + core


def accepted_values(trace, judged, memo_hits=()) -> dict:
    """{node: accepted source} in flow order: independently accepted value lines of dispatches, and memo hits whose
    provenance capture the evaluator re-read, each placed after the launches that preceded its stage."""
    events = []
    for i, (d, j) in enumerate(zip(trace, judged)):
        for job, v in j['verdicts'].items():
            if v == 'accepted' and job in j['values']:
                events.append((i, 1, job, j['values'][job]))
    for hit in memo_hits:
        if hit.get('verified_value') is not None:
            events.append((hit['after_launches'] - 0.5, 0, hit['job'], hit['verified_value']))
    out = {}
    for _, _, job, value in sorted(events, key=lambda e: (e[0], e[1])):
        out[job] = value
    return out


def trace_errors(scenario: str, trace, per_flow_cap: int, memo_hits=(), cfg=None):
    """(errors, derived, blocked, judged): every eligibility violation and the exact-trace comparison."""
    cfg = cfg or config()
    last = cfg['recovery']['max_attempts']
    errors = []

    def err(code, **detail):
        errors.append(dict(code=code, **detail))
    judged = [judge_dispatch(scenario, d) for d in trace]
    seen = [effective(d, j) for d, j in zip(trace, judged)]
    derived, blocked = derive(scenario, verdict_map(trace, seen), cfg)
    actual = actual_sequence(trace)
    if derived != actual:
        err('trace_mismatch', expected=_listed(derived), actual=_listed(actual))
    for hit in memo_hits:
        if hit.get('verified_value') is None:
            err('memo_provenance', job=hit.get('job'), reason='the memo value is not in its provenance capture')
    history, previous, cores = {}, None, {}
    events = sorted([(h['after_launches'] - 0.5, h['job'], h.get('verified_value')) for h in memo_hits
                     if h['job'].startswith('core_')], key=lambda e: e[0])
    for i, d in enumerate(trace):
        where = {'index': i, 'receipt': d.get('receipt')}
        for at, job, value in events:
            if at < i and value is not None:
                cores[job] = value
        events = [e for e in events if e[0] >= i]
        if i + 1 > per_flow_cap:
            err('launch_cap_exceeded', cap=per_flow_cap, **where)
        for finding in judged[i]['findings']:
            err(**dict(finding, **where))
        created = d.get('created_at')
        if type(created) not in (int, float):
            err('launch_order_unrecorded', **where)
        else:
            if previous is not None and created < previous:
                err('launch_order', created_at=created, previous=previous, **where)
            previous = created
        for m in d['members']:
            job, attempt, key = m['id'], m['attempt'], (d['stage'], m['id'])
            ref = None if d.get('refs') is None else d['refs'].get(job)
            if d.get('refs') is not None and ref != expected_record(scenario, d['stage'], job, cores, cfg):
                err('stale_input', job=job, **where)
            if attempt > last:
                err('third_attempt', job=job, attempt=attempt, **where)
            prior = history.setdefault(key, [])
            if prior:
                before = prior[-1]
                if attempt != before['attempt'] + 1:
                    err('attempt_sequence', job=job, attempt=attempt, after=before['attempt'], **where)
                if before['verdict'] == 'accepted':
                    err('accepted_member_resent', job=job, **where)
                elif before['verdict'] == 'held':
                    err('held_member_resent', job=job, **where)
                elif before['verdict'] in TERMINAL:
                    err('model_failure_resent', job=job, **where)
                elif before['verdict'] not in RESENDABLE:
                    err('resend_without_grounds', job=job, **where)
                if m['generation'] != before['generation']:
                    err('generation_mismatch', job=job, **where)
                if m['compute_key'] != before['compute_key']:
                    err('identity_mismatch', job=job, **where)
                if ref != before['ref']:
                    err('input_changed', job=job, **where)
            elif attempt != 1:
                err('no_prior_attempt', job=job, attempt=attempt, **where)
            prior.append({'attempt': attempt, 'generation': m['generation'], 'compute_key': m['compute_key'],
                          'verdict': seen[i].get(job, 'unknown'), 'ref': ref})
        for job, v in judged[i]['verdicts'].items():
            if v == 'accepted' and job.startswith('core_') and job in judged[i]['values']:
                cores[job] = judged[i]['values'][job]
    return errors, derived, blocked, judged


# ---- the predicate ----

def scenario_verdict(obs: dict, cfg=None) -> dict:
    """pass_g3c for one scenario. obs (plain data from the harness): scenario, status, deliveries, on_time,
    delivery_dir, revisions (ticket revisions the delivery must cite), memo_hits (count), memo_hits_detail, trace,
    ledger_ok, calls_without_usage, per_flow_cap, labels (dispatch profile labels), observables, memo_trace,
    fixture_invocations (dry gate only, else None)."""
    cfg = cfg or config()
    scenario, trace = obs['scenario'], obs['trace']
    e = entry(scenario, cfg)
    errors, derived, blocked, judged = trace_errors(scenario, trace, obs['per_flow_cap'],
                                                    obs.get('memo_hits_detail') or (), cfg)
    actual = actual_sequence(trace)
    primary = [len(d['members']) for d in trace if attempt_of(d) == 1]
    launches = len(trace)
    accepted = accepted_values(trace, judged, obs.get('memo_hits_detail') or ())
    package = None
    if obs['status'] == 'delivered' and obs.get('delivery_dir'):
        try:
            package = E.evaluate_package(obs['delivery_dir'], obs['revisions'], accepted)
        except E.EvaluatorUnavailable as exc:
            package = {'verified': False, 'errors': ['evaluator unavailable: ' + str(exc)[:120]], 'detail': {}}
    labels = obs.get('labels') or []
    checks = {
        'delivered_once_on_time_verified_A_I_H': (obs['status'] == 'delivered' and obs['deliveries'] == 1
                                                  and bool(obs['on_time']) and bool(package)
                                                  and package['verified']),
        'primary_sequence_and_memo_hits': (primary == e['expected_packets']
                                           and obs['memo_hits'] == e['expected_memo_hits']),
        'independent_verdicts': not [x for x in errors if x['code'] in INDEPENDENCE_CODES],
        'recovery_eligibility': not [x for x in errors
                                     if x['code'] != 'trace_mismatch' and x['code'] not in INDEPENDENCE_CODES],
        'exact_trace': derived == actual,
        'no_unresolved_stage': blocked is None,
        'within_scenario_launch_cap': launches <= obs['per_flow_cap'],
        'one_ledger_call_per_launch_and_complete_usage': (bool(obs['ledger_ok']) and obs['calls_without_usage'] == 0
                                                          and obs.get('fixture_invocations') in (None, launches)),
        'every_dispatch_experimental': all(x in ('experimental', 'unrecorded') for x in labels)
        and sum(1 for x in labels if x == 'unrecorded') <= (1 if scenario == 'interrupt' else 0)
        and len(labels) == launches}
    if e.get('expected_memo_trace') is not None:
        checks['memo_lookup_trace'] = obs.get('memo_trace') == e['expected_memo_trace']
    if e.get('expected_acceptance_trace') is not None:
        checks['acceptance_trace'] = obs.get('acceptance_trace') == e['expected_acceptance_trace']
    observables = obs.get('observables')
    if scenario == 'interrupt':
        checks['interrupt_observables'] = bool(observables) and all(observables['checks'].values())
    if scenario == 'stale':
        start = e['revised_from_stage']
        checks['stale_observables'] = bool(observables) and all(observables['checks'].values())
        checks['stale_order_after_mutation'] = (
            [ids for s, ids, a in actual if s >= start] == [ids for s, ids, a in derived if s >= start])
    ok = all(checks.values())
    strict = ok and launches == e['expected_launches'] and primary == e['expected_packets'] and len(primary) == launches
    return {'label': LABEL, LABEL: ok, 'strict_pass': strict, 'recovered': ok and not strict, 'checks': checks,
            'errors': errors[:12], 'derived': _listed(derived), 'actual': _listed(actual), 'blocked': blocked,
            'package': package, 'accepted_sha256': {k: E.sha(v) for k, v in sorted(accepted.items())},
            'judged': [{'receipt': d.get('receipt'), 'verdicts': j['verdicts']} for d, j in zip(trace, judged)]}


def suite_verdict(report: dict, cfg=None) -> dict:
    cfg = cfg or config()
    alloc = cfg['allocation']
    totals = report.get('totals') or {}
    scenarios = report.get('scenarios') or {}
    checks = {
        'freeze': bool((report.get('freeze') or {}).get('frozen')),
        'five_scenarios_pass_g3c': (set(scenarios) == {s['name'] for s in cfg['scenarios']}
                                    and all(s.get(LABEL) is True for s in scenarios.values())),
        'within_allocation': (bool(totals) and totals['launches'] <= alloc['max_launches']
                              and totals['tokens_known'] <= alloc['max_tokens'] and totals['accounting'] == 'complete'
                              and not totals.get('suite_over_envelope'))}
    if report.get('kind') == 'fixture':
        for name in ('recovery', 'sabotage', 'gate_sabotage', 'escape', 'seeds', 'oracle', 'feasibility'):
            block = report.get(name)
            checks[name] = bool(block) and all(c.get('pass', c.get('caught')) for c in block.values())
        checks['measured'] = bool(report.get('measured', {}).get('pass'))
    return {'label': LABEL, 'gate': cfg['gate'], 'pass': all(checks.values()), 'checks': checks}


def recovery_report(trace, calls=()) -> dict:
    """Reported apart from the verdict: first-attempt acceptance per op, rejected jobs, recovery launches and tokens,
    check false accepts and false rejects against H, wire failures and thinking tokens per call."""
    first = [{'stage': d['stage'], 'job': m['id'], 'verdict': (d.get('independent') or d['verdicts']).get(m['id'])}
             for d in trace for m in d['members'] if m['attempt'] == 1]
    per_op = {}
    for f in first:
        op = f['job'].split('_')[0]
        row = per_op.setdefault(op, {'accepted': 0, 'total': 0})
        row['total'] += 1
        row['accepted'] += f['verdict'] == 'accepted'
    false_accepts, false_rejects, h_rows = [], [], []
    for d in trace:
        for job, value in (d.get('values') or {}).items():
            record = (d.get('refs') or {}).get(job)
            try:
                h = E.candidate_h(record, value)
            except E.EvaluatorUnavailable:
                h = None
            verdict = (d.get('independent') or {}).get(job)
            h_rows.append({'receipt': d.get('receipt'), 'job': job, 'verdict': verdict,
                           'h_pass': None if h is None else h['pass']})
            if h is not None and verdict == 'accepted' and not h['pass']:
                false_accepts.append(f"{d.get('receipt')}:{job}")
            if h is not None and verdict == 'check_rejected' and h['pass']:
                false_rejects.append(f"{d.get('receipt')}:{job}")
    rows = list(calls or [])
    return {'first_attempt': per_op, 'rejected_jobs': [f"{f['stage']}:{f['job']}" for f in first
                                                        if f['verdict'] not in ('accepted', None)],
            'recovery_launches': sum(1 for d in trace if attempt_of(d) != 1),
            'recovery_tokens': sum(c['tokens'] or 0 for c in rows if c['attempt'] != 1),
            'wire_failures': sum(1 for d in trace if 'wire_rejected' in (d.get('independent') or {}).values()),
            'check_false_accepts': false_accepts, 'check_false_rejects': false_rejects, 'candidates_h': h_rows,
            'calls': rows}
