"""G3b: the recovery-aware conformance gate for inspection-handoff-20/v1 (docs/design/step4-2026-10-23/g3b/).

Standard library only. This module imports nothing from the executor (oz*.py, workflow.py, step4.py): it reads only
the frozen files (g3b.json, workflow.json, sources) and plain data the harness hands it, so the executor never judges
its own recovery behavior. It holds:

  judge_dispatch          the independent member verdicts. Each stored candidate value is judged against the frozen
                          expected values (expected.json) without executor code, and every preserved capture is
                          re-parsed here (parse_reply, a standard-library reimplementation of the OZ/1g reply
                          grammar) before a missing candidate is believed to be a wire rejection, a model error
                          line or a failed call. Any disagreement with the executor's own verdict is a finding.
  derive / trace_errors   the independent exact-trace oracle. From the independent member verdicts (accepted,
                          check_rejected, wire_rejected, model_error, call_failed, held), the scenario's primary
                          packet table and the frozen recovery policy, it derives the dispatch sequence the policy
                          must produce and compares it, with a per-launch eligibility audit (including the global
                          launch order across stages), to the actual one.
  scenario_verdict        the G3b pass predicate for one scenario. ONE label binds the gate: pass_g3b.
  suite_verdict           G3b = pass_g3b on all five scenarios, the C5 checks and the allocation (plus, for the dry
                          gate, every recovery fixture and sabotage case).
  recovery_report         first-attempt correctness, rejected jobs and packets, recovery launches and tokens, and the
                          per-call thinking tokens, reported apart from the verdict.
  replay_live1            read-only replay of the retained live1 evidence through the same predicate code; a test of
                          the predicate, never a verdict on live1.

A dispatch record is a plain dict: stage (index among the flow's stage runs that launched anything), op, receipt,
created_at, members [{id, generation, attempt, compute_key}], refs {job: input text} or None, verdicts {job: the
executor's recorded verdict} and evidence {capture: {exit_code, start_failed, stdout_b64} or None, candidates {job:
{status, value}}}, the plain facts the independent check needs.
"""
from __future__ import annotations

import base64
from datetime import datetime
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
PACK = globals().get('PACK', 'inspection-handoff-20-v1')  # packs.load sets another pack before this module runs
FROZEN = HERE / PACK
LABEL = 'pass_g3b'
# The executor's recorded verdicts: a stored candidate's status mapped, or, when the reply produced no candidate for the
# member, call_failed (the call left no completed envelope) or no_candidate (the executor cannot say why from its own
# columns). The independent verdicts name the cause from the preserved capture.
CANDIDATE_VERDICT = {'accepted': 'accepted', 'rejected': 'check_rejected', 'awaiting': 'held', 'quarantined': 'held'}
EXECUTOR_VERDICTS = frozenset({'accepted', 'check_rejected', 'held', 'call_failed', 'no_candidate'})
REJECTED = frozenset({'check_rejected', 'wire_rejected', 'model_error', 'call_failed', 'no_candidate'})
INDEPENDENCE_CODES = frozenset({'verdict_disagreement', 'independent_evidence_missing', 'capture_not_preserved',
                                'candidate_reply_mismatch', 'wire_rejection_not_atomic', 'unknown_status',
                                'verdict_unrecorded'})
HEADER = 'OZ/1g'
MAX_LINE_BYTES = 65536
MAX_RESULT_BYTES = 65536
CAPTURE_SLACK = 4096
MAX_OUTPUT_BYTES = 1048576
ERROR_CODES = ('missing_data', 'invalid_data', 'conflict', 'unsupported')
USAGE_FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_creation_input_tokens', 'output_tokens',
                'reasoning_output_tokens')
LIVE1_NOTE = ('PREDICATE REGRESSION TEST on the retained live1 evidence. This is NOT a verdict on live1: live1 G3 '
              'stays failed as preregistered and nothing here rescores it.')
LIVE2_NOTE = ('PREDICATE RUN, read-only, on the retained live2 evidence. This is NOT a verdict on live2: the live2 '
              'result was established under the earlier predicate plus the independent recheck (recheck.py).')


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


# ---- the independent member verdicts ----

_RECORD_CACHE: dict = {}


def expected_json() -> dict:
    if 'expected' not in _RECORD_CACHE:
        _RECORD_CACHE['expected'] = json.loads((FROZEN / 'expected.json').read_text(encoding='utf-8'))
    return _RECORD_CACHE['expected']


def expected_value(scenario: str, stage: int, job: str, cfg=None):
    """The frozen expected model value of a job at this stage (the revision then in force), read from expected.json
    alone: extract -> the six field strings, bounds -> the interval, classify -> the status."""
    cfg = cfg or config()
    entry, expected = cfg['scenarios'][scenario], expected_json()
    op, name = job.split('_', 1)[0], job.rsplit('_', 1)[1]
    rev = ('rev2' if entry.get('revised_from_stage') is not None and stage >= entry['revised_from_stage']
           and name == entry['revised_source'] else 'rev1')
    if op == 'extract':
        return expected['fields'][rev][name]
    row = expected.get(rev, {}).get(name) or expected['rev1'][name]
    if op == 'bounds':
        return row['interval']
    if op == 'classify':
        return row['status']
    raise ValueError(f'unknown job {job}')


def _strict_loads(text):
    """Strict JSON as the reply grammar requires: duplicate keys and NaN or Infinity are errors."""
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('duplicate JSON key')
            out[key] = value
        return out

    def constant(_):
        raise ValueError('non-finite JSON value')

    def number(token):
        value = float(token)
        if value != value or value in (float('inf'), float('-inf')):
            raise ValueError('non-finite JSON value')
        return value
    return json.loads(text, object_pairs_hook=unique, parse_constant=constant, parse_float=number)


def _storable(value) -> bool:
    text = value if isinstance(value, str) and value.strip() else json.dumps(
        value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    try:
        return len(text.encode('utf-8')) <= MAX_RESULT_BYTES
    except UnicodeEncodeError:
        return False


def parse_reply(text, ids) -> dict:
    """Judge a reply text for the packet job IDs, with no executor code: {'rejection': reason or None, 'lines':
    {id: ('value', decoded value) or ('error', code, message)}}. The reply is accepted whole or rejected whole: the
    OZ/1g header, then exactly one line per ID, each a one-member {id: value} object or a four-element
    [id, "error", code, message] array; any other line, an unknown or repeated ID, a missing ID, a result that cannot
    be stored or an oversize reply rejects everything. Nothing is repaired."""
    ids = tuple(ids)
    if not isinstance(text, str):
        return {'rejection': 'reply is not text', 'lines': {}}
    if len(text.encode('utf-8', 'surrogatepass')) > MAX_LINE_BYTES * len(ids) + CAPTURE_SLACK:
        return {'rejection': 'reply exceeds the total capture limit', 'lines': {}}
    lines = text.split('\n')
    if lines[-1] == '':
        lines.pop()
    first = next((k for k, line in enumerate(lines) if line.removesuffix('\r').strip(' \t')), None)
    if first is None:
        return {'rejection': 'reply has no result line', 'lines': {}}
    if lines[first].removesuffix('\r').rstrip(' \t') != HEADER:
        return {'rejection': f'reply does not start with {HEADER}', 'lines': {}}
    seen, bad = {}, []
    for number, line in enumerate(lines, 1):
        line = line[:-1] if line.endswith('\r') else line
        if number <= first + 1 or not line.strip(' \t'):
            continue
        if len(line.encode('utf-8', 'surrogatepass')) > MAX_LINE_BYTES:
            bad.append(number)
            continue
        try:
            value = _strict_loads(line)
        except (ValueError, RecursionError):
            bad.append(number)
            continue
        if isinstance(value, dict) and len(value) == 1:
            (key, result), = value.items()
        elif isinstance(value, list) and len(value) == 4:
            key = value[0]
        else:
            bad.append(number)
            continue
        if not isinstance(key, str) or key not in ids or key in seen:
            bad.append(number)
            continue
        if isinstance(value, dict):
            try:
                storable = _storable(result)
            except (ValueError, RecursionError):
                storable = False
            if not storable:
                bad.append(number)
                continue
            seen[key] = ('value', result)
            continue
        _, marker, code, message = value
        if (not isinstance(marker, str) or marker != 'error' or not isinstance(code, str) or code not in ERROR_CODES
                or not isinstance(message, str) or not message.strip()):
            bad.append(number)
            continue
        try:
            message.encode('utf-8')
        except UnicodeEncodeError:
            bad.append(number)
            continue
        seen[key] = ('error', code, message)
    if bad:
        return {'rejection': f'a malformed or unknown line rejects the whole reply (lines {bad[:5]})', 'lines': {}}
    if set(seen) != set(ids):
        return {'rejection': 'the reply does not cover exactly the expected jobs', 'lines': {}}
    return {'rejection': None, 'lines': seen}


def _usage_ok(value) -> bool:
    if not isinstance(value, dict) or set(value) - set(USAGE_FIELDS):
        return False
    if any(type(n) is not int or n < 0 for n in value.values()):
        return False
    total = value.get('input_tokens')
    subsets = [value[k] for k in ('cached_input_tokens', 'cache_creation_input_tokens') if k in value]
    if total is not None and sum(subsets) > total:
        return False
    return not ('output_tokens' in value and value.get('reasoning_output_tokens', 0) > value['output_tokens'])


def capture_reply(capture):
    """What a preserved runner capture (oz.capture/1: exit_code, start_failed, stdout_b64) says, re-read here:
    ('missing', None) when no capture was kept, ('call_failed', why) when the adapter process did not complete or its
    output is not JSON, ('rejected', why) when it is JSON that is not an adapter response, else ('ok', reply text)."""
    if not isinstance(capture, dict):
        return 'missing', None
    if capture.get('start_failed'):
        return 'call_failed', 'adapter_start_failed'
    if capture.get('exit_code') != 0:
        return 'call_failed', f"adapter_exit_{capture.get('exit_code')}"
    try:
        raw = base64.b64decode(capture.get('stdout_b64') or '', validate=True)
    except (ValueError, TypeError):
        return 'call_failed', 'capture_unreadable'
    if len(raw) > MAX_OUTPUT_BYTES:
        return 'call_failed', 'adapter_output_too_large'
    try:
        response = _strict_loads(raw.decode('utf-8'))
    except (ValueError, UnicodeError, RecursionError):
        return 'call_failed', 'adapter_invalid_json'
    if (not isinstance(response, dict) or 'reply' not in response or set(response) - {'reply', 'usage'}
            or not _usage_ok(response.get('usage', {}))):
        return 'rejected', 'adapter response is not {"reply":...,"usage":...}'
    return 'ok', response['reply']


def agrees(executor: str, independent: str) -> bool:
    """The executor's recorded verdict and the independent one say the same thing. The executor's columns cannot tell
    a refused reply from a model error line, so its no_candidate stands for either; the capture says which."""
    if executor == 'no_candidate':
        return independent in ('wire_rejected', 'model_error')
    return executor == independent


def judge_dispatch(scenario: str, d: dict, cfg=None) -> dict:
    """The independent verdict of every member of one dispatch, plus the findings where the preserved evidence and the
    executor's record disagree. {'verdicts': {job: verdict or None}, 'findings': [...], 'wire': reason or None}.

    A member with a stored candidate is judged by its value against the frozen expected value (accepted when equal,
    else check_rejected; held when the candidate awaits or is quarantined because the verifier was unavailable) and
    that value must be the one in the preserved reply. A member without a candidate is classified by re-parsing the
    preserved capture: a failed call, a wire rejection (the reply is refused whole), a valid model error line, or
    nothing the parse can explain (a finding: the executor recorded no candidate for a valid result)."""
    cfg = cfg or config()
    ids = [m['id'] for m in d['members']]
    evidence = d.get('evidence')
    if not isinstance(evidence, dict):
        return {'verdicts': dict.fromkeys(ids), 'findings': [{'code': 'independent_evidence_missing'}], 'wire': None}
    findings, verdicts = [], {}
    candidates = evidence.get('candidates') or {}
    kind, detail = capture_reply(evidence.get('capture'))
    lines, wire = {}, None
    if kind == 'ok':
        parsed = parse_reply(detail, ids)
        wire, lines = parsed['rejection'], parsed['lines']
    elif kind == 'rejected':
        wire = detail
    if wire is not None and any(job in candidates for job in ids):
        findings.append({'code': 'wire_rejection_not_atomic', 'reason': wire,
                         'jobs': [job for job in ids if job in candidates]})
    for job in ids:
        executor = d['verdicts'].get(job, 'unknown')
        candidate = candidates.get(job)
        independent, flagged = None, False

        def add(code, **more):
            findings.append(dict(code=code, job=job, **more))
        if candidate is not None:
            status = candidate.get('status')
            mapped = CANDIDATE_VERDICT.get(status)
            if mapped is None:
                add('unknown_status', status=status)
                flagged = True
            elif mapped == 'held':
                independent = 'held'
            else:
                try:
                    right = _strict_loads(candidate['value']) == expected_value(scenario, d['stage'], job, cfg)
                except (ValueError, RecursionError, TypeError, KeyError):
                    right = False
                independent = 'accepted' if right else 'check_rejected'
            if mapped is not None and kind == 'call_failed':
                add('candidate_reply_mismatch', reason=f'a candidate exists but the capture shows {detail}')
            elif mapped is not None and kind == 'ok' and wire is None:
                line = lines[job]
                try:
                    same = line[0] == 'value' and _strict_loads(candidate['value']) == line[1]
                except (ValueError, RecursionError, TypeError, KeyError):
                    same = False
                if not same:
                    add('candidate_reply_mismatch', reason=(
                        'the stored candidate is not the value in the preserved reply' if line[0] == 'value'
                        else 'a candidate exists but the preserved reply holds an error line'))
        elif kind == 'missing':
            if executor == 'call_failed':
                independent = 'call_failed'
            else:
                add('capture_not_preserved', executor=executor)
        elif kind == 'call_failed':
            independent = 'call_failed'
        elif wire is not None:
            independent = 'wire_rejected'
        elif lines[job][0] == 'error':
            independent = 'model_error'
        else:
            add('verdict_disagreement', executor=executor, independent='valid_reply_without_candidate',
                reason='no candidate was recorded although the preserved reply holds a valid result line')
        if executor == 'unknown':
            add('verdict_unrecorded')
        elif executor not in EXECUTOR_VERDICTS:
            if not flagged:
                add('unknown_status', verdict=executor)
        elif independent is not None and not agrees(executor, independent):
            add('verdict_disagreement', executor=executor, independent=independent,
                reason="the independent verdict differs from the executor's recorded verdict")
        verdicts[job] = independent
    return {'verdicts': verdicts, 'findings': findings, 'wire': wire}


def effective(d: dict, judged: dict) -> dict:
    """{job: verdict} used to derive the policy sequence: the independent verdict, else the executor's own record."""
    return {m['id']: judged['verdicts'].get(m['id']) or d['verdicts'].get(m['id'], 'unknown') for m in d['members']}


def shown_verdicts(d: dict) -> dict:
    """The verdicts to report for a dispatch: the independent ones when the trace was annotated, else the executor's."""
    return d.get('independent') or d['verdicts']


def annotate(scenario: str, trace, cfg=None) -> list:
    """The trace with each dispatch carrying its independent verdicts and findings (for the report)."""
    out = []
    for d in trace:
        judged = judge_dispatch(scenario, d, cfg)
        out.append(dict(d, independent={j: v if v is not None else 'unverified' for j, v in judged['verdicts'].items()},
                        independent_findings=judged['findings']))
    return out


# ---- the trace oracle ----

def expected_text(scenario: str, stage: int, job: str, cfg=None):
    """The input a model job must carry at this stage: the frozen source of its record, at the revision in force. An
    operation listed in the pack's model_refs as ["record", "interval"] (v2 classify) carries two ordered refs: that
    record text and its checked interval at the same revision, read from expected.json alone."""
    cfg = cfg or config()
    entry = cfg['scenarios'][scenario]
    name = job.rsplit('_', 1)[1]
    rel = f'sources/{name}.txt'
    revised = (entry.get('revised_from_stage') is not None and stage >= entry['revised_from_stage']
               and name == entry['revised_source'])
    if revised:
        rel = entry['revised_file']
    text = (FROZEN / rel).read_bytes().decode('utf-8')
    refs = cfg.get('model_refs', {}).get(job.split('_', 1)[0])
    if refs is None:
        return text
    if refs != ['record', 'interval']:
        raise ValueError(f'unknown model_refs {refs}')
    expected = expected_json()
    row = (expected['rev2'].get(name) if revised else None) or expected['rev1'][name]
    return [text, row['interval']]


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


def verdict_map(trace, verdicts=None) -> dict:
    """{(stage, job, attempt): verdict} from the dispatches; the first record of a key wins. verdicts is one
    {job: verdict} per dispatch (the independent ones, see effective); by default the executor's recorded ones."""
    out = {}
    for i, d in enumerate(trace):
        row = d['verdicts'] if verdicts is None else verdicts[i]
        for m in d['members']:
            out.setdefault((d['stage'], m['id'], m['attempt']), row.get(m['id'], 'unknown'))
    return out


def effective_verdicts(scenario: str, trace, cfg=None) -> dict:
    """The verdict map the policy derivation runs on: independent verdicts, executor's record where none exists."""
    cfg = cfg or config()
    return verdict_map(trace, [effective(d, judge_dispatch(scenario, d, cfg)) for d in trace])


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
    within the allowance, and a launch within the quota; an accepted or held member is never resent. The member verdicts
    are the independent ones (judge_dispatch); any finding there (a disagreement with the executor's record, an
    unknown status, a wire rejection that is not atomic, an unpreserved capture) is an error. Launches are in
    non-decreasing creation order across stages. The exact trace must equal derive()'s sequence."""
    cfg = cfg or config()
    last = cfg['recovery']['max_attempts']
    errors = []

    def err(code, **detail):
        errors.append(dict(code=code, **detail))
    judged = [judge_dispatch(scenario, d, cfg) for d in trace]
    seen = [effective(d, j) for d, j in zip(trace, judged)]
    derived, blocked = derive(scenario, verdict_map(trace, seen), cfg)
    actual = actual_sequence(trace)
    if derived != actual:
        err('trace_mismatch', expected=_listed(derived), actual=_listed(actual))
    history, previous = {}, None
    for i, d in enumerate(trace):
        where = {'index': i, 'receipt': d.get('receipt')}
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
                          'verdict': seen[i].get(job, 'unknown'), 'ref': ref})
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
        'independent_verdicts': not [e for e in errors if e['code'] in INDEPENDENCE_CODES],
        'recovery_eligibility': not [e for e in errors
                                     if e['code'] != 'trace_mismatch' and e['code'] not in INDEPENDENCE_CODES],
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
        if cfg.get('baseline', True):  # a pack without a baseline arm (v2) states it in g3b.json
            checks['baseline_smoke'] = bool(report.get('baseline_smoke', {}).get('pass'))
    return {'label': LABEL, 'gate': cfg['gate'], 'pass': all(checks.values()), 'checks': checks}


def recovery_report(trace, calls=None) -> dict:
    """What the verdict does not decide, reported separately: first-attempt correctness per job, rejected jobs and
    packets, recovery launches and tokens, final accepted attempt, and one row per call with its thinking tokens.
    Thinking tokens and rejections are an observed association, not an established cause."""
    first = [{'stage': d['stage'], 'job': m['id'], 'verdict': shown_verdicts(d).get(m['id'], 'unknown')}
             for d in trace for m in d['members'] if m['attempt'] == 1]
    rejected = [f"{f['stage']}:{f['job']}" for f in first if f['verdict'] in REJECTED]
    recovery = [d for d in trace if attempt_of(d) != 1]
    rows = list(calls or [])
    return {'first_attempt': first,
            'first_attempt_correct': sum(1 for f in first if f['verdict'] == 'accepted'),
            'first_attempt_total': len(first),
            'rejected_jobs': rejected,
            'rejected_packets': sum(1 for d in trace if any(v in REJECTED for v in shown_verdicts(d).values())),
            'recovery_launches': len(recovery),
            'recovery_tokens': sum(c['tokens'] or 0 for c in rows if c['attempt'] != 1),
            'calls': rows}


# ---- read-only replay of retained live evidence ----

def replay_live(prefix: str, directory=None, note: str = LIVE1_NOTE) -> dict:
    """Run the retained live dispatches, per-member candidates and report through the independent verdicts, the trace
    oracle and the predicate.

    Reads the evidence directory only (never writes). The retained evidence has no packet bytes and no runner
    captures, so inputs come from each candidate's recorded refs, a member's verdict is judged from its stored
    candidate against the frozen expected value, a member without a candidate would be a finding (capture not
    preserved), the attempt of a call is the ledger's and a launch's creation time is its ledger start. Stale's order
    observable is re-derived by the oracle from the trace, as G3b defines it (live1's old strict-list observable is not
    applied)."""
    root = Path(directory) if directory is not None else HERE / prefix
    cfg = config()
    report = json.loads((root / f'report-live-{prefix}.json').read_text(encoding='utf-8'))
    candidates = {}
    for line in (root / 'candidates.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            row = json.loads(line)
            candidates[(row['run'], row['job'], row['receipt'])] = row
    runs = {}
    for path in sorted(root.glob(f'calls-{prefix}-*.jsonl')):
        run = path.stem[len('calls-'):]
        scenario, op = run.split('-')[1], run.split('-')[2]
        starts = [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()
                  if x.strip() and json.loads(x).get('event') == 'call_start']
        if starts:
            runs.setdefault(scenario, []).append({'run': run, 'op': op, 'starts': starts})
    out = {'label': note, 'source': str(root), 'read_only': True, 'scenarios': {}}
    for scenario in cfg['scenarios']:
        trace = []
        ordered = sorted(runs.get(scenario, []), key=lambda r: min(s['started_at'] for s in r['starts']))
        for stage, r in enumerate(ordered):
            for call in sorted(r['starts'], key=lambda s: s['started_at']):
                ids = list(dict.fromkeys(m['inbox_job_id'] for m in call['job_map']))
                members, verdicts, refs, stored = [], {}, {}, {}
                for job in ids:
                    c = candidates.get((r['run'], job, call['batch_id']))
                    members.append({'id': job, 'generation': c['generation'] if c else None, 'attempt': call['attempt'],
                                    'compute_key': c['compute_key'] if c else None})
                    verdicts[job] = ('no_candidate' if c is None
                                     else CANDIDATE_VERDICT.get(c['status'], 'unknown_status:' + c['status']))
                    if c is not None:
                        text = json.loads(c['inputs'])[0]['refs'][0]
                        refs[job] = json.loads(text) if isinstance(text, str) else text
                        stored[job] = {'status': c['status'], 'value': c['value']}
                trace.append({'stage': stage, 'op': r['op'], 'receipt': call['batch_id'], 'created_at': datetime.fromisoformat(call['started_at']).timestamp(),
                              'members': members, 'refs': refs, 'verdicts': verdicts,
                              'evidence': {'capture': None, 'candidates': stored}})
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
            'independent_verdicts_agree': returned['checks']['independent_verdicts'],
            'predicate_returned': {k: returned[k] for k in (LABEL, 'strict_pass', 'recovered', 'checks')}}
    out['all_traces_match'] = all(s['trace_matches'] for s in out['scenarios'].values())
    out['all_independent_verdicts_agree'] = all(s['independent_verdicts_agree'] for s in out['scenarios'].values())
    return out


def replay_live1(directory=None) -> dict:
    """The live1 replay: a predicate regression test, never a verdict on live1."""
    return replay_live('live1', directory, LIVE1_NOTE)


def replay_live2(directory=None) -> dict:
    """The live2 replay: the new predicate run read-only on the retained live2 evidence, not a verdict."""
    return replay_live('live2', directory, LIVE2_NOTE)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    runner = {'replay-live1': replay_live1, 'replay-live2': replay_live2}.get(args[0] if args else None)
    if runner is None:
        print('usage: g3b.py replay-live1|replay-live2 [DIR]', file=sys.stderr)
        return 2
    print(json.dumps(runner(args[1] if len(args) > 1 else None), indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
