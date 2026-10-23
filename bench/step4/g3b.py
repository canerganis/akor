"""G3b: the recovery-aware conformance gate for inspection-handoff-20/v1 (docs/design/step4-2026-10-23/g3b/).

Standard library only. This module imports nothing from the executor (oz*.py, workflow.py, step4.py): it reads only
the frozen files (g3b.json, workflow.json, sources) and plain data the harness hands it, so the executor never judges
its own recovery behavior. It holds:

  derive / trace_errors   the independent exact-trace oracle. From the recorded per-member check verdicts of the
                          dispatches (accepted, check_rejected, wire_rejected, call_failed, held), the scenario's
                          primary packet table and the frozen recovery policy, it derives the dispatch sequence the
                          policy must produce and compares it, with a per-launch eligibility audit, to the actual one.
  scenario_verdict        the G3b pass predicate for one scenario. ONE label binds the gate: pass_g3b.
  suite_verdict           G3b = pass_g3b on all five scenarios, the C5 checks and the allocation (plus, for the dry
                          gate, every recovery fixture and sabotage case).
  recovery_report         first-attempt correctness, rejected jobs and packets, recovery launches and tokens, and the
                          per-call thinking tokens, reported apart from the verdict.
  replay_live1            read-only replay of the retained live1 evidence through the same predicate code; a test of
                          the predicate, never a verdict on live1.

A dispatch record is a plain dict: stage (index among the flow's stage runs that launched anything), op, receipt,
members [{id, generation, attempt, compute_key}], refs {job: input text} or None, verdicts {job: verdict}.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
FROZEN = HERE / 'inspection-handoff-20-v1'
LABEL = 'pass_g3b'
REJECTED = frozenset({'check_rejected', 'wire_rejected', 'call_failed'})
LIVE1_NOTE = ('PREDICATE REGRESSION TEST on the retained live1 evidence. This is NOT a verdict on live1: live1 G3 '
              'stays failed as preregistered and nothing here rescores it.')


def config() -> dict:
    return json.loads((FROZEN / 'g3b.json').read_text(encoding='utf-8'))


def allocation() -> dict:
    return config()['allocation']


def workflow_entry(scenario: str) -> dict:
    spec = json.loads((FROZEN / 'workflow.json').read_text(encoding='utf-8'))
    return next(s for s in spec['scenarios'] if s['name'] == scenario)


# ---- thinking tokens (a per-call fact from the raw CLI envelope) ----

def envelope_thinking_tokens(envelope):
    """Sum of modelUsage[*].thinkingTokens, or None when the envelope does not report it for every model (unknown is
    never recorded as zero)."""
    usage = envelope.get('modelUsage') if isinstance(envelope, dict) else None
    if not isinstance(usage, dict) or not usage:
        return None
    total = 0
    for entry in usage.values():
        value = entry.get('thinkingTokens') if isinstance(entry, dict) else None
        if type(value) is not int or value < 0:
            return None
        total += value
    return total


def capture_envelope(capture):
    """The CLI envelope retained in a runner capture record (oz.capture/1), or None."""
    if not isinstance(capture, dict) or not capture.get('envelope_b64'):
        return None
    try:
        return json.loads(base64.b64decode(capture['envelope_b64']).decode('utf-8'))
    except (ValueError, UnicodeError):
        return None


# ---- the trace oracle ----

def expected_text(scenario: str, stage: int, job: str, cfg=None) -> str:
    """The input text a model job must carry at this stage: the frozen source of its record, at the revision in force."""
    cfg = cfg or config()
    entry = cfg['scenarios'][scenario]
    name = job.rsplit('_', 1)[1]
    rel = f'sources/{name}.txt'
    if (entry.get('revised_from_stage') is not None and stage >= entry['revised_from_stage']
            and name == entry['revised_source']):
        rel = entry['revised_file']
    return (FROZEN / rel).read_bytes().decode('utf-8')


def plan_sizes(count: int, sizes) -> list:
    """Packet sizes for count jobs: the largest allowed size that fits, repeatedly (no padding, no other sizes)."""
    out = []
    while count > 0:
        fit = max((s for s in sizes if s <= count), default=None)
        if fit is None:
            out.append(count)
            break
        out.append(fit)
        count -= fit
    return out


def attempt_of(dispatch: dict) -> int:
    """The attempt of every member of a dispatch, or 0 when members disagree."""
    attempts = {m['attempt'] for m in dispatch['members']}
    return attempts.pop() if len(attempts) == 1 else 0


def actual_sequence(trace) -> list:
    return [(d['stage'], tuple(m['id'] for m in d['members']), attempt_of(d)) for d in trace]


def verdict_map(trace) -> dict:
    """{(stage, job, attempt): verdict} from the recorded dispatches; the first record of a key wins."""
    out = {}
    for d in trace:
        for m in d['members']:
            out.setdefault((d['stage'], m['id'], m['attempt']), d['verdicts'].get(m['id'], 'unknown'))
    return out


def derive(scenario: str, verdicts: dict, cfg=None):
    """(sequence, blocked): the dispatch sequence the frozen policy must produce, from verdicts alone.

    Each stage sends its primary packet (attempt 1). After a packet with rejected set R the stage resends exactly R at
    the next attempt, in job order, in packets of plan_sizes(|R|), before the next stage. A member rejected at the last
    allowed attempt, or held by a verifier outage, leaves the stage unresolved and ends the derivation (blocked). A
    verdict that was never recorded counts as accepted: the derivation never invents a rejection."""
    cfg = cfg or config()
    sizes, last = tuple(cfg['recovery']['packet_sizes']), cfg['recovery']['max_attempts']
    sequence, blocked = [], None
    for stage, (op, members) in enumerate(cfg['scenarios'][scenario]['stages']):
        sequence.append((stage, tuple(members), 1))
        pending = [j for j in members if verdicts.get((stage, j, 1)) in REJECTED]
        held = [j for j in members if verdicts.get((stage, j, 1)) == 'held']
        attempt = 1
        while pending and attempt < last:
            attempt += 1
            at = 0
            for size in plan_sizes(len(pending), sizes):
                sequence.append((stage, tuple(pending[at:at + size]), attempt))
                at += size
            held += [j for j in pending if verdicts.get((stage, j, attempt)) == 'held']
            pending = [j for j in pending if verdicts.get((stage, j, attempt)) in REJECTED]
        if pending or held:
            blocked = {'stage': stage, 'op': op, 'exhausted': pending, 'held': held}
            break
    return sequence, blocked


def _listed(sequence) -> list:
    return [[s, list(ids), a] for s, ids, a in sequence]


def trace_errors(scenario: str, trace, per_flow_cap: int, cfg=None):
    """(errors, derived, blocked): every eligibility violation and the exact-trace comparison.

    Eligibility, per launch and member: a resend needs a prior attempt of the same member and stage, recorded grounds
    (that attempt was rejected), the same generation and computation identity, current inputs, an attempt number
    within the allowance, and a launch within the quota; an accepted or held member is never resent. Wire rejection is
    atomic. The exact trace must equal derive()'s sequence."""
    cfg = cfg or config()
    last = cfg['recovery']['max_attempts']
    errors = []

    def err(code, **detail):
        errors.append(dict(code=code, **detail))
    derived, blocked = derive(scenario, verdict_map(trace), cfg)
    actual = actual_sequence(trace)
    if derived != actual:
        err('trace_mismatch', expected=_listed(derived), actual=_listed(actual))
    history = {}
    for i, d in enumerate(trace):
        where = {'index': i, 'receipt': d.get('receipt')}
        if i + 1 > per_flow_cap:
            err('launch_cap_exceeded', cap=per_flow_cap, **where)
        verdicts = [d['verdicts'].get(m['id'], 'unknown') for m in d['members']]
        if 'wire_rejected' in verdicts and any(v != 'wire_rejected' for v in verdicts):
            err('wire_rejection_not_atomic', **where)
        if 'unknown' in verdicts:
            err('verdict_unrecorded', **where)
        for m in d['members']:
            job, attempt, key = m['id'], m['attempt'], (d['stage'], m['id'])
            ref = None if d.get('refs') is None else d['refs'].get(job)
            if d.get('refs') is not None and ref != expected_text(scenario, d['stage'], job, cfg):
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
                elif before['verdict'] not in REJECTED:
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
                          'verdict': d['verdicts'].get(job, 'unknown'), 'ref': ref})
    return errors, derived, blocked


# ---- the predicate ----

def scenario_verdict(obs: dict, cfg=None) -> dict:
    """pass_g3b for one scenario. obs: scenario, entry (the workflow.json table row), status, deliveries, on_time,
    evaluator_errors, memo_hits, trace, ledger_ok, calls_without_usage, per_flow_cap, observables (interrupt and stale
    only) and fixture_invocations (dry gate only, else None)."""
    cfg = cfg or config()
    scenario, entry, trace = obs['scenario'], obs['entry'], obs['trace']
    errors, derived, blocked = trace_errors(scenario, trace, obs['per_flow_cap'], cfg)
    actual = actual_sequence(trace)
    primary = [len(d['members']) for d in trace if attempt_of(d) == 1]
    launches = len(trace)
    checks = {
        'delivered_once_on_time_verified': (obs['status'] == 'delivered' and obs['deliveries'] == 1
                                            and bool(obs['on_time']) and not obs['evaluator_errors']),
        'primary_sequence_and_memo_hits': (primary == entry['expected_packets']
                                           and obs['memo_hits'] == entry['expected_memo_hits']),
        'recovery_eligibility': not [e for e in errors if e['code'] != 'trace_mismatch'],
        'exact_trace': derived == actual,
        'no_unresolved_stage': blocked is None,
        'within_scenario_launch_cap': launches <= obs['per_flow_cap'],
        'one_ledger_call_per_launch_and_complete_usage': (bool(obs['ledger_ok']) and obs['calls_without_usage'] == 0
                                                          and obs.get('fixture_invocations') in (None, launches))}
    observables = obs.get('observables')
    if scenario == 'interrupt':
        checks['interrupt_observables'] = bool(observables) and all(observables['checks'].values())
    if scenario == 'stale':
        start = cfg['scenarios']['stale']['revised_from_stage']
        checks['stale_observables'] = bool(observables) and all(observables['checks'].values())
        checks['stale_order_after_mutation'] = (
            [ids for s, ids, a in actual if s >= start] == [ids for s, ids, a in derived if s >= start])
    ok = all(checks.values())
    strict = ok and launches == entry['expected_launches'] and primary == entry['expected_packets'] and len(primary) == launches
    return {'label': LABEL, LABEL: ok, 'strict_pass': strict, 'recovered': ok and not strict, 'checks': checks,
            'errors': errors[:12], 'derived': _listed(derived), 'actual': _listed(actual), 'blocked': blocked}


def suite_verdict(report: dict, cfg=None) -> dict:
    """G3b: pass_g3b on all five scenarios, C5, the allocation, and (dry gate) the recovery fixtures and sabotage."""
    cfg = cfg or config()
    alloc = cfg['allocation']
    totals = report.get('totals') or {}
    scenarios = report.get('scenarios') or {}
    checks = {
        'freeze': bool((report.get('freeze') or {}).get('frozen')),
        'five_scenarios_pass_g3b': (set(scenarios) == set(cfg['scenarios'])
                                    and all(s.get(LABEL) is True for s in scenarios.values())),
        'c5': bool(report.get('c5')) and all(c['pass'] for c in report['c5'].values()),
        'within_allocation': (bool(totals) and totals['launches'] <= alloc['max_launches']
                              and totals['tokens_known'] <= alloc['max_tokens'] and totals['accounting'] == 'complete')}
    if report.get('kind') == 'fixture':
        checks['sabotage_caught'] = all(c['caught'] for c in report.get('sabotage', {}).values())
        checks['recovery_fixtures'] = bool(report.get('recovery')) and all(c['pass'] for c in report['recovery'].values())
        checks['g3b_sabotage_caught'] = (bool(report.get('g3b_sabotage'))
                                         and all(c['caught'] for c in report['g3b_sabotage'].values()))
        checks['allocation_feasibility'] = (bool(report.get('feasibility'))
                                            and all(c['pass'] for c in report['feasibility'].values()))
        checks['baseline_smoke'] = bool(report.get('baseline_smoke', {}).get('pass'))
    return {'label': LABEL, 'gate': cfg['gate'], 'pass': all(checks.values()), 'checks': checks}


def recovery_report(trace, calls=None) -> dict:
    """What the verdict does not decide, reported separately: first-attempt correctness per job, rejected jobs and
    packets, recovery launches and tokens, final accepted attempt, and one row per call with its thinking tokens.
    Thinking tokens and rejections are an observed association, not an established cause."""
    first = [{'stage': d['stage'], 'job': m['id'], 'verdict': d['verdicts'].get(m['id'], 'unknown')}
             for d in trace for m in d['members'] if m['attempt'] == 1]
    rejected = [f"{f['stage']}:{f['job']}" for f in first if f['verdict'] in REJECTED]
    recovery = [d for d in trace if attempt_of(d) != 1]
    rows = list(calls or [])
    return {'first_attempt': first,
            'first_attempt_correct': sum(1 for f in first if f['verdict'] == 'accepted'),
            'first_attempt_total': len(first),
            'rejected_jobs': rejected,
            'rejected_packets': sum(1 for d in trace if any(v in REJECTED for v in d['verdicts'].values())),
            'recovery_launches': len(recovery),
            'recovery_tokens': sum(c['tokens'] or 0 for c in rows if c['attempt'] != 1),
            'calls': rows}


# ---- read-only replay of the retained live1 evidence ----

def replay_live1(directory=None) -> dict:
    """Run the retained live1 dispatches, per-member verdicts and report through the trace oracle and the predicate.

    Reads bench/step4/live1/ only (never writes). The live1 evidence has no packet bytes, so inputs come from each
    candidate's recorded refs; the attempt of a call is the ledger's. Stale's order observable is re-derived by the
    oracle from the trace, as G3b defines it (the old strict-list observable is not applied)."""
    root = Path(directory) if directory is not None else HERE / 'live1'
    cfg = config()
    report = json.loads((root / 'report-live-live1.json').read_text(encoding='utf-8'))
    candidates = {}
    for line in (root / 'candidates.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            row = json.loads(line)
            candidates[(row['run'], row['job'], row['receipt'])] = row
    runs = {}
    for path in sorted(root.glob('calls-live1-*.jsonl')):
        run = path.stem[len('calls-'):]
        scenario, op = run.split('-')[1], run.split('-')[2]
        starts = [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()
                  if x.strip() and json.loads(x).get('event') == 'call_start']
        if starts:
            runs.setdefault(scenario, []).append({'run': run, 'op': op, 'starts': starts})
    out = {'label': LIVE1_NOTE, 'source': str(root), 'read_only': True, 'scenarios': {}}
    for scenario in cfg['scenarios']:
        trace = []
        ordered = sorted(runs.get(scenario, []), key=lambda r: min(s['started_at'] for s in r['starts']))
        for stage, r in enumerate(ordered):
            for call in sorted(r['starts'], key=lambda s: s['started_at']):
                ids = list(dict.fromkeys(m['inbox_job_id'] for m in call['job_map']))
                members, verdicts, refs = [], {}, {}
                for job in ids:
                    c = candidates.get((r['run'], job, call['batch_id']))
                    members.append({'id': job, 'generation': c['generation'] if c else None, 'attempt': call['attempt'],
                                    'compute_key': c['compute_key'] if c else None})
                    verdicts[job] = ('wire_rejected' if c is None else
                                     {'accepted': 'accepted', 'rejected': 'check_rejected'}.get(c['status'], 'held'))
                    if c is not None:
                        text = json.loads(c['inputs'])[0]['refs'][0]
                        refs[job] = json.loads(text) if isinstance(text, str) else text
                trace.append({'stage': stage, 'op': r['op'], 'receipt': call['batch_id'], 'members': members,
                              'refs': refs, 'verdicts': verdicts})
        row = report['scenarios'][scenario]
        observables = row.get('observables')
        if scenario == 'stale':
            observables = {'checks': {k: v for k, v in observables['checks'].items() if k != 'singletons_then_classify'}}
        obs = {'scenario': scenario, 'entry': workflow_entry(scenario), 'status': row['status'],
               'deliveries': row['deliveries'], 'on_time': row['on_time'], 'evaluator_errors': row['evaluator']['errors'],
               'memo_hits': row['memo_hits'], 'trace': trace, 'ledger_ok': row['ledger']['ok'],
               'calls_without_usage': row['accounting']['calls_without_usage'], 'observables': observables,
               'per_flow_cap': cfg['allocation']['max_launches_per_flow'], 'fixture_invocations': None}
        returned = scenario_verdict(obs, cfg)
        out['scenarios'][scenario] = {
            'launches': len(trace), 'actual': returned['actual'], 'derived': returned['derived'],
            'trace_matches': returned['checks']['exact_trace'],
            'eligibility_errors': [e for e in returned['errors'] if e['code'] != 'trace_mismatch'],
            'predicate_returned': {k: returned[k] for k in (LABEL, 'strict_pass', 'recovered', 'checks')}}
    out['all_traces_match'] = all(s['trace_matches'] for s in out['scenarios'].values())
    return out


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] != ['replay-live1']:
        print('usage: g3b.py replay-live1 [DIR]', file=sys.stderr)
        return 2
    print(json.dumps(replay_live1(args[1] if len(args) > 1 else None), indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
