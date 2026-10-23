"""G2 zero-token dry gate blocks for repair-handoff-20/v1 (O1): measurement, recovery fixtures, executor sabotage,
predicate sabotage, the escape suite, hash seeds, the offline oracle checks and allocation feasibility.

Every block runs through the real executor, the confined worker or the gate predicate; nothing here is paid. The
predicate sabotage cases edit a recorded real trace to break exactly one rule, the way bench/step4 did for G3b.
"""
from __future__ import annotations

import ast
import base64
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from dataclasses import replace

HERE = Path(__file__).resolve().parent
for p in (str(HERE), str(HERE / 'evaluator')):
    if p not in sys.path:
        sys.path.insert(0, p)

import evaluator as E  # noqa: E402
import fixture_adapter as F  # noqa: E402
import gate as GT  # noqa: E402
import o1 as O  # noqa: E402
import sandbox  # noqa: E402
import sandbox_worker as SW  # noqa: E402
import workflow as W  # noqa: E402
from oz_accept import Unavailable  # noqa: E402
from oz_flow import Flow, HostOp, flow_dir, run_flow  # noqa: E402
from oz_memo import MemoStore  # noqa: E402
import oz_fault  # noqa: E402

SCRATCH_PREFIX = 'g2'
FIXTURE_DIR = HERE / 'fixture'


def fixture_source(ticket: str, rev: int, name: str, kind: str = 'fixture') -> str:
    root = {'fixture': FIXTURE_DIR, 'ref1': HERE / 'evaluator' / 'ref1', 'ref2': HERE / 'evaluator' / 'ref2',
            'original': W.FROZEN / 'originals'}[kind]
    file = root / (f'{ticket}_rev{rev}.py' if ticket == 'A' else f'{ticket}.py')
    return F.function_source(file.read_text(encoding='utf-8'), name)


class fixture_env:
    def __enter__(self):
        self.saved = os.environ.get('OZ_FIXTURE_DIR')

    def __exit__(self, *_):
        if self.saved is None:
            os.environ.pop('OZ_FIXTURE_DIR', None)
        else:
            os.environ['OZ_FIXTURE_DIR'] = self.saved


def fresh(base: Path, name: str) -> Path:
    ws = (base / name).resolve()
    if ws.exists():
        shutil.rmtree(ws)
    O.prepare(ws, 'fixture')
    return ws


def case_run(base: Path, name: str, mode: dict, scenarios, prefix='g2', *, checks=None, experimental_sizes=None):
    """A fresh fixture workspace with an adapter mode; each scenario through the real executor and the gate."""
    ws = fresh(base, name)
    (ws / 'fixture' / 'mode.json').write_text(json.dumps(mode), encoding='utf-8')
    outs = {}
    from unittest.mock import patch
    saved_settings = O.settings

    def patched(*a, **k):
        if checks is not None:
            k['checks'] = checks
        if experimental_sizes is not None:
            k['experimental_sizes'] = experimental_sizes
        return saved_settings(*a, **k)
    with patch.object(O, 'settings', patched):
        for scenario in scenarios:
            outs[scenario] = O.scenario_report(ws, 'fixture', prefix, scenario)
    return ws, outs


# ---- measurement ----

def _tokens():
    from oz_workspace import token_counters
    return token_counters(['o200k_base'])[0]


def measure(base: Path | None = None) -> dict:
    """Exact input tokens (o200k_base, system text H plus packet) of every frozen packet shape, read from fixture runs
    through the real executor; reserves; tier runtimes; expected spend. The frozen reserve must equal the computed
    one and the failure-free estimate at T = 5,000 must stay within 100,000 tokens (M8)."""
    from oz_batch import SYSTEM
    count = _tokens()
    base = Path(base or (O.ROOT / '.oz-runtime' / 'o1-measure')).resolve()
    with fixture_env():
        cases = {'clean+stale': ({}, ('clean', 'stale')),
                 'singles-1': ({'wrong_first': ['core_A', 'core_B', 'core_C', 'adapter_A', 'adapter_B', 'adapter_C']},
                               ('clean',)),
                 'singles-2': ({'wrong_first': ['core_D', 'adapter_D']}, ('clean',))}
        packets = {}
        for name, (mode, scenarios) in cases.items():
            ws, outs = case_run(base, 'measure-' + name, mode, scenarios, 'm')
            for scenario, out in outs.items():
                for d in out['_obs']['trace']:
                    ids = [m['id'] for m in d['members']]
                    run = ws / d['run_dir'] / 'inbox.sqlite'
                    import sqlite3
                    db = sqlite3.connect(str(run))
                    try:
                        packet = db.execute('SELECT packet FROM dispatches WHERE receipt=?', (d['receipt'],)).fetchone()[0]
                    finally:
                        db.close()
                    refs = d['refs']
                    rev = 2 if any('revision: 2' in r[:60] for r in refs.values()) else 1
                    key = ('+'.join(ids) if len(ids) == 1 else f"{ids[0].split('_')[0]}x4") + f'.rev{rev}'
                    reply = '\n'.join(['OZ/1g'] + [json.dumps({j: v}, separators=(',', ':'))
                                                   for j, v in GT.judge_dispatch(scenario, d)['values'].items()])
                    packets.setdefault(key, {'input_tokens': count(SYSTEM) + count(packet),
                                             'packet_bytes': len(packet.encode('utf-8')), 'members': len(ids),
                                             'fixture_reply_tokens': count(reply)})
    # Upper bound for an adapter packet: four cores at the 4,096-byte source limit in place of the fixture cores.
    adapter4 = packets['adapterx4.rev1']
    fixture_cores = [fixture_source(t, 1, W.ticket(t, 1)['core']['name']) for t in W.TICKETS]
    # Each core grown to the 4,096-byte limit with its own code text (realistic token density).
    extra = sum(count(json.dumps((c * 10)[:4096])) - count(json.dumps(c)) for c in fixture_cores)
    upper = adapter4['input_tokens'] + extra
    reserve = upper + 2000 + 8000
    estimate = {}
    schedule = {'clean': ['corex4.rev1', 'adapterx4.rev1'], 'interrupt': ['corex4.rev1', 'adapterx4.rev1'],
                'stale': ['corex4.rev1', 'adapterx4.rev1', 'core_A.rev2', 'adapter_A.rev2']}
    for T in (0, 2000, 5000):
        total = 0
        for calls in schedule.values():
            for key in calls:
                pk = packets[key]
                total += pk['input_tokens'] + 2000 + pk['fixture_reply_tokens'] + T
        estimate[f'T={T}'] = total
    frozen = O.allocation()['reserve_per_launch']
    runtimes = h_runtimes()
    ok = (frozen == reserve and estimate['T=5000'] <= 100000
          and all(r['max_cpu_seconds'] < 1.0 for r in runtimes.values()))
    return {'pass': ok, 'tokenizer': 'o200k_base (the workspace tokenizer; Claude counts differ, the live run records '
                                     'modelUsage)', 'packets': dict(sorted(packets.items())),
            'adapter_x4_upper_bound_input_tokens': upper, 'reserve_per_launch': reserve,
            'reserve_frozen': frozen, 'reserve_rule': 'upper-bound adapter x4 input + 2,000 overhead + 8,000 output',
            'expected_failure_free_tokens': estimate, 'schedule': schedule, 'h_runtimes': runtimes,
            'caps': {k: O.allocation()[k] for k in ('max_tokens', 'max_launches', 'max_launches_per_flow')}}


def h_runtimes() -> dict:
    """Per H domain: chunks and the largest chunk's CPU and wall seconds for reference 1 (the limit is 2 s CPU)."""
    out = {}
    for ticket, rev in (('A', 1), ('A', 2), ('B', 1), ('C', 1), ('D', 1)):
        t = W.ticket(ticket, rev)
        core_src = fixture_source(ticket, rev, t['core']['name'], 'ref1')
        for op in ('core', 'adapter'):
            src = fixture_source(ticket, rev, t[op]['name'], 'ref1')
            started = time.perf_counter()
            h = E.h_tier(t, op, src, core_src if op == 'adapter' else None)
            out[E.h_key(t, op)] = {'pass': h['pass'], 'rows': h['total'], 'chunks': h['chunks'],
                                   'max_cpu_seconds': h['max_cpu_seconds'], 'max_wall_seconds': h['max_wall_seconds'],
                                   'total_seconds': round(time.perf_counter() - started, 2)}
    return out


# ---- recovery fixtures ----

RECOVERY_CASES = (
    # name, scenario, mode, expect pass_g3c, packets (primary plus recovery)
    ('two_cores_rejected', 'clean', {'wrong_first': ['core_A', 'core_C']}, True, [4, 1, 1, 4]),
    ('three_adapters_rejected', 'clean', {'wrong_first': ['adapter_A', 'adapter_B', 'adapter_D']}, True,
     [4, 4, 1, 1, 1]),
    ('four_rejected_one_size4_resend', 'clean', {'wrong_first': ['core_A', 'core_B', 'core_C', 'core_D']}, True,
     [4, 4, 4]),
    ('wire_rejected_whole_packet', 'clean', {'wire_reject_first': ['adapter_C']}, True, [4, 4, 4]),
    ('policy_refusal_then_repair', 'clean', {'policy_first': ['core_B']}, True, [4, 1, 4]),
    ('resource_limit_then_repair', 'clean', {'loop_first': ['core_D']}, True, [4, 1, 4]),
    ('stale_with_recovery', 'stale', {'wrong_first': ['adapter_A']}, True, [4, 4, 1, 1, 1, 1]),
    ('interrupt_with_recovery', 'interrupt', {'wrong_first': ['core_B', 'core_C']}, True, [4, 1, 1, 4]),
    ('second_attempt_fails', 'clean', {'wrong_always': ['adapter_B']}, False, [4, 4, 1]),
    ('verifier_outage_holds', 'clean', {}, False, [4, 4]),
    ('model_failure_record_is_terminal', 'clean', {'model_error': ['core_C']}, False, [4]),
    ('wrong_revision_rejected', 'stale', {'rev1_core_for_rev2': True}, False, [4, 4, 1, 1]),
)


def outage_checks():
    checks = dict(W.CHECKS)
    real = W.CHECKS['o1_tier_a']

    def run(value, spec_, inputs):
        if spec_['op'] == 'adapter':
            raise Unavailable('verifier down (fixture)')
        return real.run(value, spec_, inputs)
    checks['o1_tier_a'] = replace(real, run=run)
    return checks


def recovery_fixtures(base: Path) -> tuple:
    report, runs = {}, {}
    with fixture_env():
        for name, scenario, mode, expect, packets in RECOVERY_CASES:
            ws, outs = case_run(base, name, mode, [scenario],
                                checks=outage_checks() if name == 'verifier_outage_holds' else None)
            out = outs[scenario]
            gate = out['gate']
            observed = {'pass_g3c': out[GT.LABEL], 'recovered': out['recovered'], 'packets': out['packets'],
                        'failed_checks': sorted(k for k, v in gate['checks'].items() if not v),
                        'blocked': gate['blocked'], 'status': out['status']}
            ok = observed['pass_g3c'] is expect and observed['packets'] == packets
            if expect:
                ok = ok and observed['recovered'] and not observed['failed_checks']
            else:
                ok = (ok and gate['checks']['exact_trace'] and gate['checks']['recovery_eligibility']
                      and gate['checks']['independent_verdicts'] and gate['checks']['no_unresolved_stage'] is False)
            report[name] = {'pass': bool(ok), 'expected': {'pass_g3c': expect, 'packets': packets},
                            'observed': observed}
            runs[name] = {'ws': ws, 'out': out, 'scenario': scenario}
    return report, runs


# ---- executor-level sabotage (through the real executor) ----

def sabotage(base: Path, main_ws: Path, prefix: str) -> dict:
    out = {}
    with fixture_env():
        # A corrupted patch must be refused by node 19: nothing is delivered.
        def corrupt(inputs, ctx):
            text = W.op_render_patch(inputs, ctx)
            return text.replace('+    ', '+     ', 1)
        reg = W.registry(overrides={'host.render_patch': HostOp('host.render_patch', 1,
                                                               frozenset({'snapshot', 'package', 'integration'}),
                                                               corrupt)})
        ws = fresh(base, 'sab-corrupt-patch')
        res = _run(ws, 'sabpatch', registry=reg)
        out['corrupted_patch_refused'] = {'caught': res['status'] != 'delivered'
                                          and (res['blocker'] or {}).get('node') == 'verify', 'blocker': res['blocker']}
        # A revision change between export and commit: the stale commit is refused and the delivery cites rev 2.
        ws = fresh(base, 'sab-stale-delivery')
        remove = O.mutation_hook(ws, 'g2-sabstale', 'stale', hook_name='flow.publish.after_manifest')
        try:
            res = _run(ws, 'sabstale')
        finally:
            remove()
        f = Flow(flow_dir(ws, 'g2-sabstale') / 'flow.sqlite')
        try:
            ds, states = f.deliveries(), [e['state'] for e in f.effects()]
        finally:
            f.close()
        target = res['targets'][O.TARGET]
        accepted = _accepted_sources(ws, 'g2-sabstale')
        verdict = (E.evaluate_package(ws / target['destination'], {'A': 2, 'B': 1, 'C': 1, 'D': 1}, accepted)
                   if target['status'] == 'delivered' else {'verified': False})
        out['stale_delivery_blocked'] = {'caught': (res['status'] == 'delivered' and len(ds) == 1
                                                    and ds[0]['cites'].get('A') == 2 and verdict['verified']
                                                    and states[0] == 'superseded'),
                                         'effect_states': states, 'delivery_cites': ds[0]['cites'] if ds else None}
        # A fixture value forged into a live-like namespace under the live key must not be a hit (provenance).
        copy = O.copy_of(main_ws, 'sab-forge')
        fields, _ = O.route('fixture')
        live_like = dict(fields, adapter='argv:["python","examples/claude_cli_adapter.py"];sha256:live-sim',
                         cli_version='2.1.306', effort='default')
        plan = _plan(copy, prefix, live_like, 'live-sim')
        store = MemoStore(copy / 'memo.sqlite')
        try:
            clean = {e['provenance']['job']: e for e in store.entries(O.namespace('fixture', prefix, 'clean'))}
            route = {'adapter': live_like['adapter'], 'model': O.route('fixture')[1], 'effort': 'default',
                     'cli_version': '2.1.306', 'wire': 'stage-1g', 'parser': live_like['parser']}
            for st in plan['stages']:
                for job, m in st['plan']['memo'].items():
                    e = clean[job]
                    store.publish('live-sim', m['compute_key'], value=e['value'], stored=e['stored'], route=route,
                                  checks=e['checks'], verdicts=e['verdicts'], provenance=e['provenance'])
        finally:
            store.close()
        again = _plan(copy, prefix, live_like, 'live-sim')
        out['forged_memo_eligibility_refused'] = {'caught': again['misses'] == plan['misses'] and again['misses'] >= 4,
                                                  'misses': again['misses']}
        # Missing usage: accounting is incomplete and the scenario cannot pass.
        _, outs = case_run(base, 'sab-missing-usage', {'no_model_usage': True}, ['clean'])
        g = outs['clean']['gate']['checks']
        out['missing_usage_fails'] = {'caught': not outs['clean'][GT.LABEL]
                                      and not g['one_ledger_call_per_launch_and_complete_usage']}
        # A check that falsely rejects a correct adapter: the independent verdicts disagree.
        checks = dict(W.CHECKS)
        real = W.CHECKS['o1_tier_a']

        def reject_b(value, spec_, inputs):
            return False if 'ticket: B' in inputs.texts[0][:40] and spec_['op'] == 'adapter' else real.run(
                value, spec_, inputs)
        checks['o1_tier_a'] = replace(real, run=reject_b)
        _, outs = case_run(base, 'sab-false-rejection', {}, ['clean'], checks=checks)
        g = outs['clean']['gate']
        out['executor_false_rejection_detected'] = {
            'caught': not outs['clean'][GT.LABEL] and not g['checks']['independent_verdicts']
            and any(e.get('kind') == 'false_rejection' for e in g['errors'])}
        # A check that accepts everything, with a defective core in the reply: false acceptance is detected.
        checks = dict(W.CHECKS)
        checks['o1_tier_a'] = replace(real, run=lambda v, s, i: True)
        _, outs = case_run(base, 'sab-false-acceptance', {'wrong_first': ['core_C']}, ['clean'], checks=checks)
        g = outs['clean']['gate']
        out['executor_false_acceptance_detected'] = {
            'caught': not outs['clean'][GT.LABEL] and not g['checks']['independent_verdicts']
            and not g['checks']['delivered_once_on_time_verified_A_I_H']}
        # Singleton recovery labeled qualified (experimental_sizes left at the default (4,)): M9 catches it.
        # The fixture route names a model with no qualified cell, so the route here names Sonnet (and the fixture
        # envelope reports it): without size 1 in experimental_sizes, oz do would label the singleton qualified_cell.
        from unittest.mock import patch
        real_route = O.route

        def sonnet_route(kind):
            fields, _ = real_route(kind)
            return fields, 'claude-sonnet-5-5'
        with patch.object(O, 'route', sonnet_route):
            _, outs = case_run(base, 'sab-qualified-singleton', {'wrong_first': ['core_A'],
                                                                 'model': 'claude-sonnet-5-5'}, ['clean'],
                               experimental_sizes=(4,))
        out['singleton_labeled_qualified'] = {'caught': not outs['clean'][GT.LABEL]
                                              and not outs['clean']['gate']['checks']['every_dispatch_experimental'],
                                              'labels': outs['clean']['labels']}
    return out


def _run(ws: Path, rid_: str, **options):
    quota = O.quota_store(ws, 'fixture')
    try:
        return run_flow(O.flow_request('g2', rid_.split('-')[-1], request_id=f'g2-{rid_}'),
                        O.settings(ws, 'fixture', f'fixture-g2-{rid_}', quota=quota, **options))
    finally:
        quota.close()


def _plan(ws: Path, prefix: str, route_fields, ns):
    quota = O.quota_store(ws, 'fixture')
    try:
        s = O.settings(ws, 'fixture', ns, quota=quota, route_fields=route_fields)
        return run_flow(O.flow_request(prefix, 'clean'), s, plan_only=True)
    finally:
        quota.close()


def _accepted_sources(ws: Path, request_id: str) -> dict:
    trace = O.trace_of(ws, request_id)
    judged = [GT.judge_dispatch('clean', d) for d in trace]
    out = {}
    for d, j in zip(trace, judged):
        for job, value in j['values'].items():
            parsed = E.parse_header(d['refs'][job])
            if parsed and E.judge_candidate(d['refs'][job], value)['verdict'] == 'accepted':
                out[job] = value
    return out


# ---- predicate sabotage: real traces edited to break one rule ----

def capture_of(lines: list, failed=False) -> dict:
    reply = '\n'.join(lines)
    stdout = json.dumps({'reply': reply, 'usage': {'input_tokens': 1, 'output_tokens': 1}}).encode('utf-8')
    return {'exit_code': 1 if failed else 0, 'start_failed': False, 'stdout_b64': base64.b64encode(stdout).decode()}


def restory(d: dict, story: dict) -> None:
    """Rewrite one dispatch's executor verdicts and evidence for a story {job: verdict} (others keep accepted):
    accepted gets the fixture answer, check_rejected the defective function, held an awaiting candidate."""
    lines, candidates, verdicts = ['OZ/1g'], {}, {}
    failed = any(v == 'call_failed' for v in story.values())
    wire = any(v == 'wire_rejected' for v in story.values())
    for m in d['members']:
        job = m['id']
        kind = story.get(job, 'accepted')
        parts = F.record_parts(d['refs'][job])
        if kind in ('accepted', 'held', 'executor_accepts_wrong', 'executor_rejects_right', 'rev1_for_rev2'):
            value = F.fixture_answer(parts, 1 if kind == 'rev1_for_rev2' else None)
            if kind == 'executor_accepts_wrong':
                value = parts['defective']
            status = {'held': 'awaiting', 'executor_rejects_right': 'rejected'}.get(kind, 'accepted')
            candidates[job] = {'status': status, 'value': json.dumps(value)}
            lines.append(json.dumps({job: value}, separators=(',', ':')))
            verdicts[job] = GT.CANDIDATE_VERDICT[status]
        elif kind == 'check_rejected':
            candidates[job] = {'status': 'rejected', 'value': json.dumps(parts['defective'])}
            lines.append(json.dumps({job: parts['defective']}, separators=(',', ':')))
            verdicts[job] = 'check_rejected'
        elif kind == 'model_error':
            lines.append(json.dumps([job, 'error', 'unsupported', 'declined']))
            verdicts[job] = 'no_candidate'
        else:
            verdicts[job] = 'call_failed' if kind == 'call_failed' else 'no_candidate'
    capture = capture_of(['not an OZ/1g reply'] if wire else lines, failed)
    d['verdicts'], d['evidence'] = verdicts, {'capture': capture, 'candidates': {} if failed or wire else candidates}


def like(d: dict, pool: list, *, members=None, attempt=None, receipt=None, stage=None, story=None) -> dict:
    out = copy.deepcopy(d)
    if members is not None:
        known = {m['id']: (m, x['refs'][m['id']]) for x in reversed(pool) for m in x['members']}
        out['members'] = [dict(known[j][0]) for j in members]
        out['refs'] = {j: known[j][1] for j in members}
    for m in out['members']:
        if attempt is not None:
            m['attempt'] = attempt
    if stage is not None:
        out['stage'] = stage
    out['receipt'] = receipt or out['receipt'] + 'x'
    out['label'] = 'experimental'
    restory(out, story or {})
    return out


def renumbered(trace: list) -> list:
    out = copy.deepcopy(trace)
    base = min((d['created_at'] for d in out), default=0)
    for i, d in enumerate(out):
        d['created_at'] = base + i
    return out


def gate_sabotage(runs: dict, main_runs: dict, main_ws: Path, prefix: str) -> dict:
    two, three = runs['two_cores_rejected'], runs['three_adapters_rejected']
    outage, failure = runs['verifier_outage_holds'], runs['model_failure_record_is_terminal']
    stale = main_runs['stale']
    cases = {}

    def add(name, base, trace, code, **obs_over):
        obs = dict(base['out']['_obs'], trace=renumbered(trace), labels=['experimental'] * len(trace),
                   fixture_invocations=None)
        obs.update(obs_over)
        cases[name] = (obs, code)
    t = two['out']['_obs']['trace']
    primary, resend_a, resend_c, adapters = t[0], t[1], t[2], t[3]
    add('accepted_sibling_resend', two, t[:3] + [like(primary, t, members=['core_B'], attempt=2, receipt='s1')] + t[3:],
        'accepted_member_resent')
    add('unsupported_packet_size', two, [primary, like(primary, t, members=['core_A', 'core_C'], attempt=2,
                                                       receipt='s2')] + t[3:], 'trace_mismatch')
    third = copy.deepcopy(t)
    restory(third[1], {'core_A': 'check_rejected'})
    add('third_attempt', two, third[:2] + [like(resend_a, t, attempt=3, receipt='s3')] + third[2:], 'third_attempt')
    add('skipped_recovery', two, [primary, resend_a, adapters], 'trace_mismatch')
    rejects = copy.deepcopy(t)
    restory(rejects[0], {'core_A': 'check_rejected', 'core_B': 'executor_rejects_right', 'core_C': 'check_rejected'})
    add('false_rejection_of_a_correct_candidate', two, rejects[:3] + [like(primary, t, members=['core_B'], attempt=2,
                                                                          receipt='s4')] + rejects[3:],
        'verdict_disagreement')
    accepts = copy.deepcopy(t)
    restory(accepts[3], {'adapter_D': 'executor_accepts_wrong'})
    add('false_acceptance_of_a_defective_candidate', two, accepts, 'verdict_disagreement')
    st = stale['_obs']['trace']
    wrong_rev = copy.deepcopy(st)
    restory(wrong_rev[2], {'core_A': 'rev1_for_rev2'})
    add('wrong_revision_accepted', {'out': stale}, wrong_rev, 'verdict_disagreement')
    leak = copy.deepcopy(st)
    leak[2]['refs']['core_A'] = W.ticket('A', 1)['core_record']
    restory(leak[2], {})
    add('stale_input_after_mutation', {'out': stale}, leak, 'stale_input')
    to = outage['out']['_obs']['trace']
    add('verifier_outage_regeneration', outage, to + [like(to[-1], to, attempt=1, receipt='s5',
                                                          stage=to[-1]['stage'] + 1)], 'trace_mismatch')
    add('verifier_outage_resend', outage, to + [like(to[-1], to, members=['adapter_A'], attempt=2, receipt='s6')],
        'held_member_resent')
    tf = failure['out']['_obs']['trace']
    add('model_failure_resent', failure, tf + [like(tf[0], tf, members=['core_C'], attempt=2, receipt='s7')],
        'model_failure_resent')
    tw = runs['wire_rejected_whole_packet']['out']['_obs']['trace']
    add('wire_rejection_resent_as_singletons', runs['wire_rejected_whole_packet'],
        tw[:-1] + [like(tw[-1], tw, members=[j], attempt=2, receipt=f'w{j}') for j in
                   [m['id'] for m in tw[-1]['members']]], 'trace_mismatch')
    na = copy.deepcopy(tw)
    na[1]['evidence']['candidates']['adapter_A'] = {'status': 'accepted', 'value': json.dumps('def x(): pass')}
    na[1]['verdicts']['adapter_A'] = 'accepted'
    add('wire_rejection_not_atomic', runs['wire_rejected_whole_packet'], na, 'wire_rejection_not_atomic')
    cap = t + [like(resend_a, t, attempt=2, receipt=f'q{i}') for i in range(6)]
    add('launch_beyond_scenario_cap', two, cap, 'launch_cap_exceeded')
    rep = main_runs['repeat']['_obs']
    forged = copy.deepcopy(rep['memo_hits_detail'])
    forged[0]['verified_value'] = None
    cases['forged_memo_provenance'] = (dict(rep, memo_hits_detail=forged), 'memo_provenance')
    cases['stale_package_delivered'] = (dict(stale['_obs'], delivery_dir=main_runs['clean']['_obs']['delivery_dir']),
                                        'package')
    cases['missing_usage'] = (dict(main_runs['clean']['_obs'], calls_without_usage=1), 'usage')
    cases['dispatch_labeled_qualified'] = (dict(main_runs['clean']['_obs'],
                                                labels=['experimental', 'qualified_cell']), 'label')
    report = {}
    for name, (obs, code) in cases.items():
        verdict = GT.scenario_verdict(obs)
        codes = sorted({e['code'] for e in verdict['errors']})
        failed = sorted(k for k, v in verdict['checks'].items() if not v)
        hit = code in codes or (code == 'package' and 'delivered_once_on_time_verified_A_I_H' in failed) or (
            code == 'usage' and 'one_ledger_call_per_launch_and_complete_usage' in failed) or (
            code == 'label' and 'every_dispatch_experimental' in failed)
        report[name] = {'caught': (not verdict[GT.LABEL]) and hit, 'expected_finding': code, 'findings': codes,
                        'failed_checks': failed}
    # Ledger edits on copies of real runs: a recovered capture counted as another launch, one call counted twice.
    for name, same_id, source in (('capture_recovery_counted_as_launch', False, ('interrupt', main_ws)),
                                  ('duplicate_ledger_record', True, ('clean', main_ws))):
        scenario, ws = source
        copy_ws = O.copy_of(ws, 'sab-' + name)
        request_id = O.rid(prefix, scenario)
        first = O.trace_of(copy_ws, request_id)[0]
        ledger = copy_ws / first['run_dir'] / 'calls.jsonl'
        start = next(json.loads(x) for x in ledger.read_text(encoding='utf-8').splitlines()
                     if json.loads(x).get('batch_id') == first['receipt'] and json.loads(x).get('event') == 'call_start')
        with ledger.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(start if same_id else dict(start, call_id='replayed-' + start['call_id'])) + '\n')
        audit = O.ledger_audit(copy_ws, request_id)
        verdict = GT.scenario_verdict(dict(main_runs[scenario]['_obs'], ledger_ok=audit['ok']))
        report[name] = {'caught': (not audit['ok']) and not verdict[GT.LABEL], 'expected_finding': 'ledger',
                        'findings': audit['problems'][:2]}
    return report


# ---- the escape suite (M7.5) ----

ESCAPES = {
    'dunder_traversal': ('refused', "    return ().__class__.__bases__[0].__subclasses__()\n"),
    'format_spec_traversal': ('refused', "    return '{0.__class__}'.format(text)\n"),
    'fstring_traversal': ('refused', "    return f'{text.__class__}'\n"),
    'builtins_recovery': ('refused', "    return __builtins__['open']\n"),
    'getattr_string': ('refused', "    return getattr(text, '__cl' + 'ass__')\n"),
    'generator_frame': ('refused', "    return (x for x in []).gi_frame.f_globals\n"),
    'traceback_frame': ('refused', "    try:\n        1 / 0\n    except ZeroDivisionError as e:\n"
                                   "        return e.__traceback__.tb_frame\n"),
    'with_traceback': ('refused', "    try:\n        1 / 0\n    except ZeroDivisionError as e:\n"
                                  "        return e.with_traceback(None)\n"),
    'import_statement': ('refused', "    import os\n    return os.getcwd()\n"),
    'import_call': ('refused', "    return __import__('socket')\n"),
    'open_file': ('refused', "    return open('README.md').read()\n"),
    'eval_exec': ('refused', "    return eval('1 + 1')\n"),
    'type_call': ('refused', "    return type(text)\n"),
    'globals_call': ('refused', "    return globals()\n"),
    'class_definition': ('refused', "    class X:\n        pass\n    return 1\n"),
    'lambda_default': ('refused', "    f = lambda x=print: x\n    return 1\n"),
    'nonlocal_yield': ('refused', "    yield text\n"),
    'with_statement': ('refused', "    with text:\n        return 1\n"),
    'recursion_bomb': ('contained', "    def f(n):\n        return f(n + 1)\n    return f(0)\n"),
    'huge_allocation': ('contained', "    return [0] * (10 ** 10)\n"),
    'doubling_string': ('contained', "    s = 'x'\n    while True:\n        s = s + s\n"),
    'cpu_loop': ('contained', "    while True:\n        pass\n"),
    'big_power': ('contained', "    return 10 ** (10 ** 8)\n"),
}

AUDIT_EVENTS = ('import', 'open', 'compile', 'exec', 'socket.connect', 'socket.__new__', 'os.system',
                'subprocess.Popen', 'ctypes.dlopen', 'os.listdir')


def audit_hooks() -> dict:
    """The audit layer of both workers, checked directly: armed, every frozen event family raises; disarmed, none."""
    import eval_worker as EW
    out = {}
    for name, hook, flag in (('sandbox_worker', SW._audit, SW.ARMED), ('eval_worker', EW.guard, EW.GUARD)):
        refused = []
        flag[0] = True
        try:
            for event in AUDIT_EVENTS:
                try:
                    hook(event, ())
                except RuntimeError:
                    refused.append(event)
        finally:
            flag[0] = False
        quiet = True
        for event in AUDIT_EVENTS:
            try:
                hook(event, ())
            except RuntimeError:
                quiet = False
        out[name] = {'pass': refused == list(AUDIT_EVENTS) and quiet, 'refused': refused}
    return out


def escape_suite() -> dict:
    pol = W.policy()
    out = {}
    for name, (expect, body) in ESCAPES.items():
        source = 'def parse_amount(text):\n' + body
        runtime_refused = bool(SW.check_function(source, 'parse_amount', ['text'], pol))
        evaluator_refused = bool(E.policy_problems(source, 'parse_amount', ['text']))
        payload = {'policy': pol, 'units': [{'id': 'core', 'kind': 'function', 'source': source,
                                             'name': 'parse_amount', 'params': ['text']}],
                   'rows': [{'unit': 'core', 'fn': 'parse_amount', 'args': ['1']}]}
        try:
            res = sandbox.run(payload, 0)
            status = res['status']
            row = (res.get('rows') or [{}])[0]
        except sandbox.SandboxUnavailable as exc:
            status, row = 'unavailable: ' + str(exc)[:80], {}
        if expect == 'refused':
            ok = runtime_refused and evaluator_refused and status == 'refused'
        else:
            ok = (not runtime_refused and status in ('resource', 'ok')
                  and (status == 'resource' or row.get('x') in ('RecursionError', 'MemoryError', 'OverflowError')))
        out[name] = {'pass': bool(ok), 'expected': expect, 'worker_status': status, 'row': row,
                     'runtime_policy_refused': runtime_refused, 'evaluator_policy_refused': evaluator_refused}
    for name, row in audit_hooks().items():
        out['audit_hook_' + name] = row
    out['process_confinement'] = process_confinement()
    return out


TRUSTED_CHILD = ("import subprocess, sys\nsys.stdin.readline()\n"
                 "try:\n    subprocess.run([sys.executable, '-c', '0'], timeout=5)\n    print('spawned')\n"
                 "except OSError as exc:\n    print('refused', type(exc).__name__)\n")


def process_confinement() -> dict:
    """The Job Object limits read back as frozen; a second process cannot start inside the job; a sleeping worker is
    stopped by the wall timeout; every worker reports the temporary cwd and the two-variable environment."""
    job = sandbox.Job()
    try:
        limits = job.limits()
    finally:
        job.close()
    want = {'flags': sandbox.LIMIT_FLAGS, 'cpu_100ns': 20_000_000, 'processes': 1, 'memory': 256 * 1024 * 1024}
    job = sandbox.Job()
    try:
        proc = subprocess.Popen([sandbox.interpreter(), '-S', '-c', TRUSTED_CHILD], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        job.assign(int(proc._handle))
        stdout, _ = proc.communicate('go\n', timeout=30)
    finally:
        job.close()
    meta = sandbox.run({'policy': W.policy(), 'units': [], 'rows': []}, 1)['meta']
    checks = {'limits_read_back': limits == want, 'second_process_refused': stdout.strip().startswith('refused'),
              'environment_two_variables': sorted(meta['env']) == ['PYTHONHASHSEED', 'SYSTEMROOT'],
              'cwd_is_temporary_not_repo': O.ROOT.resolve() not in Path(meta['cwd']).resolve().parents
              and Path(meta['cwd']).name.startswith('o1-sbx-'),
              'launcher_flags': meta['flags']['no_site'] == 1 and meta['flags']['safe_path'] is True
              and meta['flags']['ignore_environment'] == 0}
    return {'pass': all(checks.values()), 'checks': checks, 'limits': limits, 'child': stdout.strip()}


# ---- hash seeds (Astra's condition 2, M3) ----

def seeds() -> dict:
    pol = W.policy()
    empty = {'policy': pol, 'units': [], 'rows': []}
    h0, h0b, h1 = (sandbox.run(empty, s)['meta']['hash'] for s in (0, 0, 1))
    order = {}
    probe = ("def parse_amount(text):\n    return list({'aa', 'bb', 'cc', 'dd', 'ee', 'ff', 'gg', 'hh'})\n")
    for s in (0, 1):
        res = sandbox.run({'policy': pol, 'units': [{'id': 'core', 'kind': 'function', 'source': probe,
                                                     'name': 'parse_amount', 'params': ['text']}],
                           'rows': [{'unit': 'core', 'fn': 'parse_amount', 'args': ['x']}]}, s)
        order[s] = json.loads(res['rows'][0]['r'])
    out = {'hash_seed_honored': {'pass': h0 == h0b and h0 != h1, 'seed0': h0, 'seed1': h1},
           'set_order_differs_between_seeds': {'pass': order[0] != order[1], 'seed0': order[0], 'seed1': order[1]}}
    # A candidate correct under seed 0 and wrong under seed 1 is a candidate failure (both checks).
    t = W.ticket('D', 1)
    good = fixture_source('D', 1, 'topological_order')
    head, rest = good.split('\n', 1)
    k = next((i for i, (x, y) in enumerate(zip(order[0], order[1])) if x != y), 0)
    flaky = (head + "\n    if list({'aa', 'bb', 'cc', 'dd', 'ee', 'ff', 'gg', 'hh'})[" + str(k) + "] != "
             + repr(order[0][k]) + ":\n        return []\n" + rest)
    payload, expected = W.tier_a_payload(t, 'core', flaky, None)
    runtime = W.judge(payload, expected)
    independent = E.judge_candidate(t['core_record'], flaky)
    out['seed_dependent_candidate_rejected'] = {
        'pass': (not runtime['pass'] and runtime['reason'] == 'hash seed 1 differs from seed 0'
                 and independent['verdict'] == 'check_rejected' and 'seed 1 differs' in independent['reason']),
        'runtime': runtime['reason'], 'evaluator': independent['reason']}
    # Type strictness: a tuple is not a list, True is not 1, before any JSON serialization.
    tb = W.ticket('B', 1)
    tuples = fixture_source('B', 1, 'union_intervals').replace('return out', 'return [tuple(x) for x in out]')
    ta = W.ticket('A', 1)
    truthy = fixture_source('A', 1, 'parse_amount').replace('return -value if negative else value',
                                                            'return True if value == 1 else (-value if negative else value)')
    for name, (t_, src) in {'tuple_output_rejected': (tb, tuples), 'true_is_not_one': (ta, truthy)}.items():
        payload, expected = W.tier_a_payload(t_, 'core', src, None)
        r = W.judge(payload, expected)
        e = E.judge_candidate(t_['core_record'], src)
        out[name] = {'pass': not r['pass'] and e['verdict'] == 'check_rejected', 'runtime': r['reason'],
                     'evaluator': e['reason']}
    return out


# ---- offline oracle checks ----

def _runtime_a(t, op, value, core=None):
    payload, expected = W.tier_a_payload(t, op, value, core)
    return W.judge(payload, expected)['pass']


def mutants(source: str) -> list:
    """Every single-token substitution the host could search for: comparison and arithmetic operator swaps, integer
    constants plus or minus one, and/or swaps, min/max swaps, dropping a unary not, unwrapping a one-argument call."""
    tree = ast.parse(source)
    out = []
    swaps = {ast.Lt: (ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq), ast.LtE: (ast.Lt, ast.Gt, ast.GtE, ast.Eq),
             ast.Gt: (ast.GtE, ast.Lt, ast.LtE, ast.Eq), ast.GtE: (ast.Gt, ast.Lt, ast.LtE, ast.Eq),
             ast.Eq: (ast.NotEq, ast.Lt, ast.Gt), ast.NotEq: (ast.Eq,), ast.In: (ast.NotIn,), ast.NotIn: (ast.In,),
             ast.Is: (ast.IsNot,), ast.IsNot: (ast.Is,)}
    arith = (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)
    nodes = list(ast.walk(tree))
    for idx, node in enumerate(nodes):
        variants = []
        if isinstance(node, ast.Compare):
            for k, op in enumerate(node.ops):
                for new in swaps.get(type(op), ()):
                    variants.append(('ops', k, new()))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, arith):
            variants += [('op', None, o()) for o in arith if not isinstance(node.op, o)]
        elif isinstance(node, ast.BoolOp):
            variants.append(('op', None, ast.Or() if isinstance(node.op, ast.And) else ast.And()))
        elif isinstance(node, ast.Constant) and type(node.value) is int:
            variants += [('value', None, node.value + 1), ('value', None, node.value - 1)]
        elif isinstance(node, ast.Name) and node.id in ('min', 'max'):
            variants.append(('id', None, 'max' if node.id == 'min' else 'min'))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            variants.append(('unwrap', None, None))
        elif isinstance(node, ast.Call) and len(node.args) == 1 and not node.keywords:
            variants.append(('unwrap', None, None))
        for field, k, new in variants:
            copy_tree = copy.deepcopy(tree)
            target = list(ast.walk(copy_tree))[idx]
            if field == 'ops':
                target.ops[k] = new
            elif field == 'unwrap':
                inner = target.operand if isinstance(target, ast.UnaryOp) else target.args[0]
                for parent in ast.walk(copy_tree):
                    for name, value in ast.iter_fields(parent):
                        if value is target:
                            setattr(parent, name, inner)
                        elif isinstance(value, list):
                            for j, item in enumerate(value):
                                if item is target:
                                    value[j] = inner
            else:
                setattr(target, field, new)
            try:
                out.append(ast.unparse(ast.fix_missing_locations(copy_tree)) + '\n')
            except Exception:  # noqa: BLE001  an unparsable mutant is not a candidate
                continue
    return list(dict.fromkeys(out))


def oracle_checks() -> dict:
    out = {}
    import build as B
    out['frozen_pack_equals_generator_and_references_agree'] = {'pass': B.main(['--check']) == 0}
    per = {}
    for ticket, rev in B.REVISIONS:
        t = W.ticket(ticket, rev)
        ref_core = fixture_source(ticket, rev, t['core']['name'], 'ref1')
        for kind in ('fixture', 'ref2', 'original'):
            core = fixture_source(ticket, rev, t['core']['name'], kind)
            adapter = fixture_source(ticket, rev, t['adapter']['name'], kind)
            runtime = (_runtime_a(t, 'core', core), _runtime_a(t, 'adapter', adapter, ref_core))
            independent = (E.judge_candidate(t['core_record'], core)['verdict'] == 'accepted',
                           E.judge_candidate(t['adapter_record_prefix'] + ref_core, adapter)['verdict'] == 'accepted')
            h = (E.h_tier(t, 'core', core)['pass'], E.h_tier(t, 'adapter', adapter, ref_core)['pass'])
            want = kind != 'original'
            per[f'{ticket}{rev}.{kind}'] = {'pass': runtime == (want, want) and independent == (want, want)
                                            and (h == (True, True) if want else not all(h)),
                                            'runtime_A': runtime, 'evaluator_A': independent, 'H': h}
    out['valid_alternatives_pass_and_originals_fail'] = {'pass': all(v['pass'] for v in per.values()), 'cases': per}
    tA1, tA2, tB = W.ticket('A', 1), W.ticket('A', 2), W.ticket('B', 1)
    a1 = fixture_source('A', 1, 'parse_amount')
    a2 = fixture_source('A', 2, 'parse_amount')
    from oz_accept import Inputs
    spec_ = {'check': 'o1_tier_a', 'version': 1, 'op': 'core'}

    def check(record, value):
        return W.CHECKS['o1_tier_a'].run(value, spec_, Inputs(({'op': '', 'refs': [json.dumps(record)]},)))
    tampered = tA1['core_record'].replace('nine integer digits', 'ten integer digits')
    out['wrong_function_binding_detected'] = {'pass': not check(tB['core_record'], a1) and not check(tampered, a1)
                                              and check(tA1['core_record'], a1)}
    out['wrong_revision_detected'] = {'pass': not check(tA2['core_record'], a1) and not check(tA1['core_record'], a2)
                                      and check(tA2['core_record'], a2)
                                      and not _runtime_a(tA2, 'adapter', fixture_source('A', 1, 'total_amount'), a2)}
    confused = a1.replace('return -value if negative else value', 'return str(-value if negative else value)')
    out['type_confusion_detected'] = {'pass': not check(tA1['core_record'], confused)}
    mutating = fixture_source('B', 1, 'union_intervals').replace('    spans = []\n', '    intervals.sort()\n    spans = []\n')
    out['input_mutation_detected'] = {'pass': not _runtime_a(tB, 'core', mutating)
                                      and E.judge_candidate(tB['core_record'], mutating)['verdict'] == 'check_rejected'}
    b_core = fixture_source('B', 1, 'union_intervals', 'ref1')
    sorting_adapter = fixture_source('B', 1, 'free_slots').replace('    free = []\n', '    parts.sort()\n    free = []\n')
    tD = W.ticket('D', 1)
    d_core = fixture_source('D', 1, 'topological_order', 'ref1')
    ignoring = fixture_source('D', 1, 'execution_batches').replace(
        '    order = topological_order(jobs)\n',
        '    topological_order(jobs)\n    order = [job[\'id\'] for job in jobs]\n')
    out['adapter_compensation_detected'] = {
        'pass': not _runtime_a(tB, 'adapter', sorting_adapter, b_core) and not _runtime_a(tD, 'adapter', ignoring, d_core)
        and E.judge_candidate(tB['adapter_record_prefix'] + b_core, sorting_adapter)['verdict'] == 'check_rejected'}
    out['references_unreachable_from_the_executor'] = provenance_scan()
    out['no_single_substitution_repairs_a_defect'] = mutation_search()
    return out


def provenance_scan() -> dict:
    """M1.2: no reference function (by exact text or by AST) and no held-out data is in the executor's read set: the
    frozen pack, workflow.py, sandbox.py, sandbox_worker.py and the oz modules."""
    import build as B
    executor_files = sorted(W.FROZEN.rglob('*.json')) + sorted((W.FROZEN / 'originals').glob('*.py')) + [
        HERE / 'workflow.py', HERE / 'sandbox.py', HERE / 'sandbox_worker.py'] + sorted(O.ROOT.glob('oz*.py'))
    texts = {p: p.read_text(encoding='utf-8') for p in executor_files}
    dumps = set()
    for p, text in texts.items():
        if p.suffix == '.py':
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.FunctionDef):
                    dumps.add(ast.dump(node))
    found = []
    for kind in ('ref1', 'ref2'):
        for ticket, rev in B.REVISIONS:
            t = W.ticket(ticket, rev)
            for op in ('core', 'adapter'):
                src = fixture_source(ticket, rev, t[op]['name'], kind)
                if any(src.strip() in text or json.dumps(src)[1:-1] in text for text in texts.values()):
                    found.append(f'{kind} {ticket}{rev} {op} text')
                if ast.dump(ast.parse(src).body[0]) in dumps:
                    found.append(f'{kind} {ticket}{rev} {op} ast')
    heldout = json.loads((HERE / 'evaluator' / 'heldout.json').read_text(encoding='utf-8'))
    for key, entry in heldout['domains'].items():
        if any(entry['expected_sha256'] in text or entry['expected_zlib_b64'][:40] in text for text in texts.values()):
            found.append('held-out data ' + key)
    if any('heldout' in text or "'evaluator'" in text or 'ref1' in text for p, text in texts.items()
           if p.suffix == '.py'):
            found.append('an executor module names the evaluator, its references or held-out data')
    return {'pass': not found, 'found': found, 'files_scanned': len(texts)}


def mutation_search() -> dict:
    """M1.3: every single substitution of every defective original, judged by the runtime A tier (seed 0 first): none
    may pass. A mutant that does not parse is skipped."""
    import build as B
    passed, counts = [], {}
    for ticket, rev in B.REVISIONS:
        t = W.ticket(ticket, rev)
        ref_core = fixture_source(ticket, rev, t['core']['name'], 'ref1')
        for op in ('core', 'adapter'):
            source = fixture_source(ticket, rev, t[op]['name'], 'original')
            found = mutants(source)
            counts[f'{ticket}{rev}.{op}'] = len(found)
            for m in found:
                if not SW.check_function(m, t[op]['name'], t[op]['params'], W.policy()) and _runtime_a(
                        t, op, m, ref_core if op == 'adapter' else None):
                    passed.append(f'{ticket}{rev}.{op}: {m[:80]!r}')
    return {'pass': not passed, 'mutants': counts, 'total': sum(counts.values()), 'passing_mutants': passed}


# ---- allocation feasibility ----

def feasibility(base: Path, measured: dict) -> dict:
    """Admission under the frozen caps with fixture calls reporting live-sized usage."""
    per_call = measured['packets']['adapterx4.rev1']
    usage = {'input': per_call['input_tokens'] + 2000 + 2000, 'output': per_call['fixture_reply_tokens']}
    cap = O.allocation()
    cases = (
        ('recovery_in_each_cold_scenario', {'wrong_first': ['adapter_A', 'adapter_C'], 'usage': usage},
         ('clean', 'repeat', 'interrupt', 'stale', 'bump'), True, None),
        ('scenario_launch_cap_exhausted', {'wrong_first': ['core_A', 'core_B', 'core_C', 'adapter_A', 'adapter_B',
                                                           'adapter_C'], 'usage': usage}, ('stale',), False,
         'flow_launch_cap'),
        ('token_reserve_refuses', {'wrong_first': ['core_A'], 'usage': {'input': 70000, 'output': 100}}, ('clean',),
         False, 'token_cap'))
    report = {}
    with fixture_env():
        for name, mode, scenarios, expect, reason in cases:
            ws, outs = case_run(base, 'feasibility-' + name, mode, scenarios)
            launches = sum(o['launches'] for o in outs.values())
            calls = [c for o in outs.values() for c in o['recovery']['calls']]
            tokens, peak = 0, 0
            for c in calls:
                peak = max(peak, tokens + cap['reserve_per_launch'])
                tokens += c['tokens'] or 0
            reasons = sorted({str(v.get('reason')) for o in outs.values()
                              for v in ((o['blocker'] or {}).get('jobs') or {}).values()})
            passed = all(o[GT.LABEL] for o in outs.values())
            ok = passed is expect and launches <= cap['max_launches'] and peak <= cap['max_tokens']
            if not expect:
                ok = ok and reason in reasons
            report[name] = {'pass': bool(ok), 'all_pass_g3c': passed, 'launches': launches, 'tokens': tokens,
                            'peak_tokens_plus_reserve': peak, 'refusals': reasons}
    return report


def dry_blocks(report: dict, ws: Path, runs: dict) -> None:
    base = ws.parent / (ws.name + '.g2')
    report['measured'] = measure(base)
    report['recovery'], fixture_runs = recovery_fixtures(base)
    report['sabotage'] = sabotage(base, ws, report['prefix'])
    report['gate_sabotage'] = gate_sabotage(fixture_runs, runs, ws, report['prefix'])
    report['escape'] = escape_suite()
    report['seeds'] = seeds()
    report['oracle'] = oracle_checks()
    report['feasibility'] = feasibility(base, report['measured'])
    os.environ['OZ_FIXTURE_DIR'] = str(ws / 'fixture')
