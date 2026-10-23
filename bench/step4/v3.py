"""Step 4 v3 harness (docs/design/boundary-adoption-2026-10-23/decision-host-classify.md): the four classify nodes are
host operations (host.classify@1), so a flow sends only extract and bounds to a model. Expected primary launches are
2, 0, 2, 4, 0 for clean, repeat, interrupt, stale and bump. There is no paid command here: no model is ever called.

    python bench/step4/v3.py freeze [--write]           G0: the v3 freeze (pack, code, design, plan)
    python bench/step4/v3.py dry [--workspace DIR]      G2: five scenarios under the G3b predicate, C5, recovery
                                                        cases and the host-classification fixtures (fixtures only)
    python bench/step4/v3.py run-flow ...               one fixture flow (the interrupted scenario's subprocess)

It reuses the v2 machinery: bench/step4/packs.py per-pack module copies (host_classify.py loads the v3 copies and binds
them), step4.py's own scenario runner, audit and G3b predicate on those copies, g3b.py's predicate and trace oracle,
the evaluator's v3 copy and the fixture adapter, and adopt.py's freeze and fixture patterns. Nothing in the frozen v1
or v2 harness files is edited. Standard library only.
"""
from __future__ import annotations

import argparse
import contextlib
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import host_classify as H  # noqa: E402
from oz import Error  # noqa: E402
from oz_flow import Flow, HostError, HostOp, flow_dir, flow_usage, run_flow  # noqa: E402
from oz_memo import MemoStore  # noqa: E402
import oz_fault  # noqa: E402

W, G, E, S = H.W, H.G, H.E, H.S
PACK = W.FROZEN
FREEZE_FILE = PACK / 'freeze.json'
DESIGN = ROOT / 'docs' / 'design' / 'boundary-adoption-2026-10-23'
PLAN_ID = 'boundary-adoption-2026-10-23'
DESIGN_FILES = ('01-astra-r1.md', '02-opus-r1.md', '03-astra-r2-signed.md', '04-opus-r2-sign.md', '05-astra-next.md',
                '06-opus-next.md', 'decision-host-classify.md')
V1_PACK = HERE / 'inspection-handoff-20-v1'
V2_PACK = HERE / 'inspection-handoff-20-v2'
READS = ('bench/step4/inspection-handoff-20-v2/qual.json',)  # the 24 frozen cases, read only
CODE = ('oz.py', 'oz_batch.py', 'oz_reply.py', 'oz_accept.py', 'oz_runtime.py', 'oz_worker.py', 'oz_runner.py',
        'oz_do.py', 'oz_memo.py', 'oz_quota.py', 'oz_flow.py', 'oz_fault.py', 'oz_workspace.py',
        'examples/claude_cli_adapter.py', 'bench/step4/workflow.py', 'bench/step4/evaluator.py',
        'bench/step4/fixture_adapter.py', 'bench/step4/g3b.py', 'bench/step4/step4.py', 'bench/step4/packs.py',
        'bench/step4/host_classify.py', 'bench/step4/v3.py')
DRY_WS = ROOT / '.oz-runtime' / 'hc-dry'
EXPECTED = {'clean': (2, [4, 4], 0), 'repeat': (0, [], 8), 'interrupt': (2, [4, 4], 0), 'stale': (4, [4, 4, 1, 1], 6),
            'bump': (0, [], 16)}
RULES = {
    'host_classify': 'inside exactly when lower_limit <= interval_low and interval_high <= upper_limit, in Decimal; '
                     'outside otherwise; unknown when the interval is unknown; malformed input is refused',
    'inputs': 'node 11 checked interval (/bounds/X) and the structured goal limits as a graph literal equal to '
              'workflow.json limits',
    'no_model': 'no model.classify operation or node; the graph keeps 20 nodes',
    'live': 'none: no paid run is allocated; a later model experiment needs its own preregistration',
}


class V3Error(Exception):
    pass


def ndigest(path: Path) -> str:
    """SHA-256 with CRLF normalized to LF, so a checkout's line-ending conversion does not change identities."""
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def canon(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def spec() -> dict:
    return W.load('workflow.json')


def oracle_label(interval, limits) -> str:
    """The independent oracle: integer hundredths of a millimetre, no Decimal and no float, nothing from the host
    operation. interval is [low, high] strings 'NN.NN mm' or 'unknown'; limits is the structured {lower, upper}."""
    if interval == 'unknown':
        return 'unknown'
    low, high = (int(x[:-3].replace('.', '')) for x in interval)
    lower, upper = (int(limits[k].replace('.', '')) for k in ('lower', 'upper'))
    return 'inside' if lower <= low and high <= upper else 'outside'


# ---- the freeze ----

def pack_files() -> list:
    return sorted(p for p in PACK.rglob('*') if p.is_file() and p.name != 'freeze.json' and '__pycache__' not in p.parts)


def files_record() -> dict:
    return {'pack': {p.relative_to(ROOT).as_posix(): ndigest(p) for p in pack_files()},
            'code': {c: ndigest(ROOT / c) for c in CODE},
            'reads': {c: ndigest(ROOT / c) for c in READS},
            'design': {f'docs/design/{PLAN_ID}/{n}': ndigest(DESIGN / n) for n in DESIGN_FILES}}


FIXTURES = ('limits_agree_and_a_disagreeing_goal_is_refused', 'graph_binds_interval_and_limits_per_record',
            'no_classify_model_job_in_any_scenario', 'equality_at_both_limits_is_inside',
            'breaches_by_0_01_are_outside', 'the_24_frozen_cases_agree', 'unknown_interval_is_unknown',
            'invalid_inputs_are_refused_by_the_host_op', 'changed_limits_change_labels_and_are_caught',
            'changed_limits_in_the_graph_are_stopped_by_the_row_check_and_the_evaluator',
            'node11_superseded_before_the_classify_commit_is_refused', 'stale_scenario_classifies_on_the_new_interval',
            'independent_oracle_grid_agrees', 'evaluator_agrees_with_every_delivered_status',
            'sabotaged_host_operations_are_caught')


def plan_problems() -> list:
    """Where the v3 pack departs from the decision (empty when it holds)."""
    problems = W.limits_problems() + H.graph_problems()
    s = spec()
    v1 = json.loads((V1_PACK / 'workflow.json').read_text(encoding='utf-8'))
    for name in ('model.extract', 'model.bounds'):
        if s['model_ops'][name] != v1['model_ops'][name]:
            problems.append(f'{name} differs from v1')
    for rel in ('expected.json', 'sources/A.txt', 'sources/A.rev2.txt', 'sources/B.txt', 'sources/C.txt',
                'sources/D.txt'):
        if (PACK / rel).read_bytes() != (V1_PACK / rel).read_bytes():
            problems.append(f'{rel} differs from v1')
    got = {x['name']: (x['expected_launches'], x['expected_packets'], x['expected_memo_hits']) for x in s['scenarios']}
    if got != EXPECTED:
        problems.append(f'scenario expectations differ from the decision: {got}')
    if s['goal'] != json.loads((V2_PACK / 'workflow.json').read_text(encoding='utf-8'))['goal']:
        problems.append('goal differs from v2')
    return problems


def plan_record() -> dict:
    problems = plan_problems()
    if problems:
        raise V3Error('; '.join(problems[:8]))
    s = spec()
    return {'plan': PLAN_ID, 'workflow': s['workflow'], 'decision': f'docs/design/{PLAN_ID}/decision-host-classify.md',
            'operation': 'host.classify@1', 'operation_inputs': sorted(H.CLASSIFY.inputs), 'limits': s['limits'],
            'goal': s['goal'], 'model_ops': sorted(s['model_ops']), 'nodes': len(W.graph()['nodes']),
            'expected_launches': {k: v[0] for k, v in EXPECTED.items()},
            'expected_packets': {k: v[1] for k, v in EXPECTED.items()},
            'expected_memo_hits': {k: v[2] for k, v in EXPECTED.items()},
            'allocation': G.allocation(), 'fixtures': list(FIXTURES), 'recovery_cases': [c[0] for c in RECOVERY_CASES],
            'rules': RULES}


def _digest(record: dict) -> str:
    return hashlib.sha256(canon(record).encode('utf-8')).hexdigest()


def freeze(write: bool = False, *, full: bool = True) -> dict:
    """G0. full=False checks the files only (the plan part is a deterministic function of them); full=True also
    regenerates the plan record and compares it with the stored one."""
    stored = json.loads(FREEZE_FILE.read_text(encoding='utf-8')) if FREEZE_FILE.exists() else {}
    files = files_record()
    problems = []
    if write or full:
        try:
            plan = plan_record()
        except V3Error as exc:
            if write:
                raise
            return {'frozen': False, 'digest': stored.get('digest'), 'current_digest': None,
                    'problems': ['plan: ' + str(exc)]}
    else:
        plan = stored.get('plan', {})
    current = {'files': files, 'plan': plan}
    digest = _digest(current)
    if write:
        FREEZE_FILE.write_text(json.dumps(dict(current, digest=digest), indent=1, ensure_ascii=False) + '\n',
                               encoding='utf-8', newline='\n')
        return {'frozen': True, 'digest': digest, 'current_digest': digest, 'problems': []}
    if stored.get('digest') != _digest({'files': stored.get('files', {}), 'plan': stored.get('plan', {})}):
        problems.append('the stored record does not hash to the stored digest')
    for group in ('pack', 'code', 'reads', 'design'):
        for name, value in files[group].items():
            if stored.get('files', {}).get(group, {}).get(name) != value:
                problems.append(f'{name} changed since the freeze')
        for name in set(stored.get('files', {}).get(group, {})) - set(files[group]):
            problems.append(f'{name} missing')
    if full and json.loads(json.dumps(plan)) != stored.get('plan'):
        problems.append('the regenerated plan record differs from the stored one')
    return {'frozen': not problems, 'digest': stored.get('digest'), 'current_digest': digest, 'problems': problems}


def freeze_status() -> dict:
    return freeze(full=False)


# ---- binding the step 4 copy to v3 ----

_flow_request = S.flow_request


def flow_request(prefix: str, scenario: str, *, request_id: str | None = None) -> dict:
    """step4.flow_request, refusing a pack whose limits or graph disagree with the decision."""
    problems = W.limits_problems() + H.graph_problems()
    if problems:
        raise Error('v3 graph or limits: ' + '; '.join(problems[:4]))
    return _flow_request(prefix, scenario, request_id=request_id)


def stale_observables(ws: Path, prefix: str) -> dict:
    """C3 for v3 (step4.stale_observables with the classify stage gone): what only a correct executor gets right in
    the stale-input run. The host classifications are computed after the new node 11 and cite revision 2 only."""
    request_id = S.rid(prefix, 'stale')
    f = Flow(flow_dir(ws, request_id) / 'flow.sqlite')
    try:
        events = f.events()
        mutation = next(e for e in events if e['event'] == 'source_revised')
        history = [dict(r) for r in f.db.execute("SELECT node,generation,cites FROM acceptances WHERE node LIKE '%_A'")]
        classified = [json.loads(r['cites']) for r in f.db.execute(
            "SELECT cites FROM acceptances WHERE node LIKE 'classify_%'")]
        deliveries = f.deliveries()
    finally:
        f.close()
    old_a = W.source_bytes('A').decode('utf-8')
    after = [d for d in S.dispatches(ws, request_id) if d['created_at'] > mutation['at']]
    leaked = [d['receipt'] for d in after if old_a in d['packet']]
    order = [d['members'] for d in after]
    derived, _ = G.derive('stale', G.effective_verdicts('stale', S.trace_of(ws, request_id)))
    start = G.config()['scenarios']['stale']['revised_from_stage']
    derived_order = [list(ids) for stage, ids, attempt in derived if stage >= start]
    primary_after = [list(ids) for stage, ids, attempt in derived if stage >= start and attempt == 1]
    reused = {}
    stage_memos = [e['details'] for e in events if e['event'] == 'stage' and e['seq'] > mutation['seq']]
    first_keys = {}
    for e in events:
        if e['event'] == 'stage' and e['seq'] < mutation['seq']:
            first_keys.update(S._accepted_keys(ws / e['details']['run_dir']))
    for st in stage_memos:
        for job, m in (st.get('memo') or {}).items():
            if job[-1] in 'BCD' and job.split('_')[0] in ('extract', 'bounds'):
                reused[job] = {'decision': m['decision'], 'same_inputs': first_keys.get(job) == m['compute_key']}
    old_rows = [r for r in history if r['node'] in ('extract_A', 'bounds_A')]
    manifest_cites = deliveries[0]['cites'] if deliveries else {}
    checks = {
        'no_old_A_after_mutation': not leaked,
        'order_after_mutation_is_derived': order == derived_order and primary_after == [['extract_A'], ['bounds_A']],
        'bcd_reused_by_recorded_identical_input_decision': (
            sorted(reused) == sorted(f'{op}_{n}' for op in ('extract', 'bounds') for n in 'BCD')
            and all(v['decision'] == 'hit' and v['same_inputs'] for v in reused.values())),
        'old_A_history_kept_delivery_cites_rev2': (
            any(json.loads(r['cites']).get('A') == 1 for r in old_rows) and manifest_cites.get('A') == 2),
        'host_classifications_cite_revision_2_only': len(classified) == 4 and all(c.get('A') == 2 for c in classified)}
    return {'pass': all(checks.values()), 'checks': checks, 'dispatches_after_mutation': order,
            'leaked_receipts': leaked, 'reused': reused}


S.freeze = freeze_status
S.ENTRY = Path(__file__).resolve()
S.flow_request = flow_request
S.stale_observables = stale_observables
S.baseline = lambda *a, **k: {'pass': None, 'note': G.config().get('baseline_note')}


# ---- recovery cases (the model stages that remain) ----

RECOVERY_CASES = (
    # name, scenario, fixture mode, expected pass_g3b, primary-plus-recovery packet sizes
    ('wrong_answers_in_both_model_stages', 'clean', {'wrong_first': ['extract_B', 'bounds_D']}, True, [4, 1, 4, 1]),
    ('wire_rejected_extract_packet', 'clean', {'wire_reject_first': ['extract_A']}, True, [4, 4, 4]),
    ('stale_with_rejections_before_and_after_the_mutation', 'stale', {'wrong_first': ['extract_A']}, True,
     [4, 1, 4, 1, 1, 1]),
    ('interrupt_with_recovery', 'interrupt', {'wrong_first': ['bounds_A', 'bounds_C']}, True, [4, 4, 1, 1]),
    ('second_attempt_fails', 'clean', {'wrong_always': ['bounds_C']}, False, [4, 4, 1]))


def recovery_fixtures(ws: Path, prefix: str) -> dict:
    base = ws.parent / (ws.name + '.g3b')
    report = {}
    with S._fixture_env():
        for name, scenario, mode, expect_pass, packets in RECOVERY_CASES:
            _, outs = S.fixture_case(base, name, mode, [scenario], prefix)
            out = outs[scenario]
            verdict = out['g3b']
            observed = {'pass_g3b': verdict[G.LABEL], 'recovered': verdict['recovered'], 'launches': out['launches'],
                        'packets': out['packets'], 'rejected_jobs': out['recovery']['rejected_jobs'],
                        'failed_checks': sorted(k for k, v in verdict['checks'].items() if not v),
                        'blocked': verdict['blocked'], 'status': out['status']}
            ok = observed['pass_g3b'] is expect_pass and observed['packets'] == packets
            if expect_pass:
                ok = ok and observed['recovered'] and not observed['failed_checks']
            else:
                ok = (ok and verdict['checks']['exact_trace'] and verdict['checks']['recovery_eligibility']
                      and verdict['checks']['no_unresolved_stage'] is False)
            report[name] = {'pass': bool(ok), 'expected': {'pass_g3b': expect_pass, 'packets': packets},
                            'observed': observed}
    return report


# ---- C5 (the v3 subset) ----

def c5_checks(ws: Path, prefix: str, clean_copy: Path) -> dict:
    out = {}
    files = {}
    for sc in ('clean', 'repeat', 'interrupt', 'bump'):
        res = json.loads((flow_dir(ws, S.rid(prefix, sc)) / 'execution-record.json').read_text(encoding='utf-8'))
        dest = ws / Path(res['effects'][0]['destination']) if res['effects'] else None
        files[sc] = {n: (dest / n).read_bytes() for n in ('handoff.json', 'handoff.md')} if dest else {}
    same = all(files[sc] == files['clean'] for sc in ('repeat', 'interrupt')) and bool(files['clean'])
    bump_ok = False
    if files.get('bump') and files['clean']:
        a, b = json.loads(files['bump']['handoff.json']), json.loads(files['clean']['handoff.json'])
        a['records'][0]['source']['revision'] = b['records'][0]['source']['revision']
        md = files['bump']['handoff.md'].replace(b'A rev 2 sha256', b'A rev 1 sha256')
        bump_ok = a == b and md == files['clean']['handoff.md'] and files['bump'] != files['clean']
    out['byte_identity'] = {'pass': same and bump_ok, 'clean_repeat_interrupt_identical': same,
                            'bump_differs_only_in_revision': bump_ok}
    # A route change misses every model job (8) and stops before launch (plan-only).
    copy = S.copy_of(clean_copy, 'c5-route')
    fields, _ = S.route('fixture')
    plan = S.plan_on(copy, 'fixture', prefix, route_fields=dict(fields, effort='changed-effort'))
    out['route_change'] = {'pass': plan['misses'] == 8 and plan['launched'] == 0, 'misses': plan['misses'],
                           'packets': plan['packets']}
    # Revocation of one clean bounds_B entry: exactly one miss in the next plan.
    copy = S.copy_of(clean_copy, 'c5-revoke')
    store = MemoStore(copy / 'memo.sqlite')
    try:
        revoked = [e['id'] for e in store.entries(S.namespace('fixture', prefix, 'clean'))
                   if e['provenance'].get('job') == 'bounds_B']
        for entry in revoked:
            store.revoke(entry, 'C5 revocation check')
    finally:
        store.close()
    plan = S.plan_on(copy, 'fixture', prefix)
    missed = [j for st in plan['stages'] for j, m in st['plan']['memo'].items() if m['decision'] != 'hit']
    out['revocation'] = {'pass': plan['misses'] == 1 and missed == ['bounds_B'] and plan['launched'] == 0,
                         'revoked_entries': revoked, 'missed': missed}
    # A strengthened acceptance-only check on bounds revalidates the 4 retained candidates on the host, no call.
    copy = S.copy_of(clean_copy, 'c5-strong')
    quota = S.quota_store(copy, 'fixture')
    try:
        strong = W.registry(extra_checks={'model.bounds': [{'check': 'max_bytes', 'bytes': 64}]})
        res = run_flow(S.flow_request(prefix, 'strong'),
                       S.settings(copy, 'fixture', S.namespace('fixture', prefix, 'clean'), quota=quota,
                                  registry=strong, budget=dict(S.allocation(), max_launches=0)))
    finally:
        quota.close()
    checks = S._stage_checks(copy, f'{prefix}-strong', 'bounds')
    errors = (E.evaluate_package(copy / res['targets']['inspection_handoff'].get('destination', 'missing'), 'rev1',
                                 W.load('expected.json')['revisions']['clean'])
              if res['status'] == 'delivered' else ['not delivered'])
    out['strengthened_check'] = {
        'pass': (res['status'] == 'delivered' and not S.dispatches(copy, f'{prefix}-strong') and not errors
                 and len(checks) == 4 and all('max_bytes@1:pass' in c for c in checks.values())),
        'bounds_checks': checks, 'evaluator_errors': errors}
    return out


# ---- the host-classification fixtures ----

def _run(copy: Path, request_id: str, prefix: str, *, registry=None, graph=None, mutation=None, status_of=None):
    """One flow on an isolated copy of the clean state (clean memo namespace: model stages hit, nothing launches
    unless a source moved), optionally with an overriding registry, graph, mutation hook or status function."""
    request = dict(S.flow_request('x', 'clean', request_id=request_id))
    if graph is not None:
        request['graph'] = graph
    quota = S.quota_store(copy, 'fixture')
    remove = S.mutation_hook(copy, request_id, mutation) if mutation else None
    try:
        with (patch.object(W, 'status_of', status_of) if status_of else contextlib.nullcontext()):
            return run_flow(request, S.settings(copy, 'fixture', S.namespace('fixture', prefix, 'clean'),
                                                quota=quota, registry=registry))
    finally:
        quota.close()
        if remove:
            remove()


def _copy(clean_copy: Path, name: str) -> Path:
    copy = S.copy_of(clean_copy, name)
    os.environ['OZ_FIXTURE_DIR'] = str(copy / 'fixture')
    (copy / 'fixture' / 'mode.json').unlink(missing_ok=True)
    return copy


def _errors(copy: Path, res: dict, scenario: str) -> list:
    exp = W.load('expected.json')
    target = res['targets']['inspection_handoff']
    if target['status'] != 'delivered':
        return ['not delivered']
    return E.evaluate_package(copy / target['destination'], exp['variants'][scenario],
                              exp['revisions'][scenario])


def _delivered(ws: Path, prefix: str, scenario: str) -> dict:
    res = json.loads((flow_dir(ws, S.rid(prefix, scenario)) / 'execution-record.json').read_text(encoding='utf-8'))
    dest = ws / Path(res['effects'][0]['destination'])
    return json.loads((dest / 'handoff.json').read_text(encoding='utf-8'))


def _graph_with(edit) -> dict:
    graph = json.loads(json.dumps(W.graph()))
    edit(graph)
    return graph


def _node(graph: dict, name: str) -> dict:
    return next(n for n in graph['nodes'] if n['id'] == name)


def _sabotages(limits: dict):
    """(name, scenario that exposes it, status function, why): each a wrong classification rule over the same
    parsed interval and limits as the real one."""
    lower, upper = Decimal(limits['lower']), Decimal(limits['upper'])

    def rule(test):
        def status(bounds):
            if bounds == 'unknown':
                return 'unknown'
            low, high = W._mm(bounds[0]), W._mm(bounds[1])
            return 'inside' if test(low, high) else 'outside'
        return status
    real = W.status_of

    def stale_cache(bounds):  # answers for A from the interval it had before the source moved
        return 'inside' if bounds == ['12.53 mm', '12.57 mm'] else real(bounds)
    return (
        ('strict_at_the_lower_limit', 'clean', rule(lambda lo, hi: lower < lo and hi <= upper)),
        ('strict_at_the_upper_limit', 'clean', rule(lambda lo, hi: lower <= lo and hi < upper)),
        ('upper_limit_only', 'clean', rule(lambda lo, hi: hi <= upper)),
        ('lower_limit_only', 'stale', rule(lambda lo, hi: lower <= lo)),
        ('width_only', 'stale', rule(lambda lo, hi: hi - lo <= upper - lower)),
        ('previous_interval_kept', 'stale', stale_cache))


def host_fixtures(ws: Path, prefix: str, suite: dict) -> dict:
    out = {}
    clean_copy = ws.parent / (ws.name + '.copies') / 'clean-state'
    lim = spec()['limits']
    exp = W.load('expected.json')
    all_rows = {**{('rev1', k): v for k, v in exp['rev1'].items()}, **{('rev2', k): v for k, v in exp['rev2'].items()}}
    # 1. Structured limits: every consumer agrees; a goal, limit or graph literal that disagrees is refused.
    md_line = f"Acceptance interval: [{lim['lower']} mm, {lim['upper']} mm], inclusive."
    doc = W.handoff_document([])
    agree = (not W.limits_problems() and (W.LOWER, W.UPPER) == (Decimal(lim['lower']), Decimal(lim['upper']))
             and doc['acceptance_interval'] == {'lower': f"{lim['lower']} mm", 'upper': f"{lim['upper']} mm",
                                                'inclusive': True}
             and E.ACCEPTANCE_INTERVAL == doc['acceptance_interval']
             and md_line in W.op_render_markdown({'rows': {'rows': []}}, None)
             and spec()['goal'] == spec()['goal_template'].format(**lim))
    bad_goal = dict(spec(), goal=spec()['goal'].replace('12.52', '12.53'))
    moved = json.loads(json.dumps(spec()))
    moved['limits']['upper'] = '12.53'  # a consistent-looking edit of the limits alone
    moved_all = json.loads(json.dumps(moved))
    moved_all['goal'] = moved_all['goal_template'].format(**moved_all['limits'])
    out['limits_agree_and_a_disagreeing_goal_is_refused'] = {
        'pass': (agree and bool(W.limits_problems(bad_goal)) and bool(W.limits_problems(moved))
                 and not [p for p in W.limits_problems(moved_all) if 'goal sentence' in p]
                 and bool(H.graph_problems(spec=moved_all))),
        'problems_for_bad_goal': W.limits_problems(bad_goal)}
    # 2. The graph rule, and its runtime backstop: an interval of another record is classified, but the host row
    # builder recomputes the label of node 11's own interval and refuses the row.
    wrong_pair = _graph_with(lambda g: _node(g, 'classify_A')['in']['interval'].update(path='/bounds/B'))
    copy = _copy(clean_copy, 'hc-pairing')
    res = _run(copy, f'{prefix}-pair', prefix, graph=wrong_pair)
    out['graph_binds_interval_and_limits_per_record'] = {
        'pass': (not H.graph_problems() and bool(H.graph_problems(wrong_pair)) and res['status'] != 'delivered'
                 and (res['blocker'] or {}).get('node') == 'handoff_rows'),
        'graph_problems': H.graph_problems(wrong_pair), 'blocker': res['blocker']}
    # 3. No classification is ever a model job.
    seen_jobs, host_kinds = set(), set()
    for name in S.SCENARIOS:
        for d in S.dispatches(ws, S.rid(prefix, name)):
            seen_jobs |= set(d['members'])
        f = Flow(flow_dir(ws, S.rid(prefix, name)) / 'flow.sqlite')
        try:
            host_kinds |= {(d['kind'], d['identity']) for d in f.descriptors() if d['id'].startswith('classify_')}
        finally:
            f.close()
    out['no_classify_model_job_in_any_scenario'] = {
        'pass': (not [j for j in seen_jobs if j.startswith('classify')] and host_kinds == {('host', 'host.classify@1')}
                 and W.registry().get('model.classify') is None),
        'model_jobs': sorted(seen_jobs), 'classify_node_kinds': sorted(host_kinds)}
    # 4. Equality at both limits (unit, plus the delivered clean package: A touches both limits, C the upper one).
    clean_doc = _delivered(ws, prefix, 'clean')
    status = {r['record']: r['status'] for r in clean_doc['records']}
    out['equality_at_both_limits_is_inside'] = {
        'pass': (H.classify_interval(['12.48 mm', '12.52 mm'], lim) == 'inside'
                 and H.classify_interval(['12.48 mm', '12.50 mm'], lim) == 'inside'
                 and H.classify_interval(['12.50 mm', '12.52 mm'], lim) == 'inside'
                 and status['A'] == 'inside' and status['C'] == 'inside'),
        'delivered_clean': status}
    # 5. 0.01 breaches on either side.
    out['breaches_by_0_01_are_outside'] = {
        'pass': (H.classify_interval(['12.47 mm', '12.52 mm'], lim) == 'outside'
                 and H.classify_interval(['12.48 mm', '12.53 mm'], lim) == 'outside'
                 and H.classify_interval(['12.47 mm', '12.49 mm'], lim) == 'outside'
                 and H.classify_interval(['12.51 mm', '12.53 mm'], lim) == 'outside')}
    # 6. The 24 frozen cases of the v2 qualification (three goals, edges, interior, breaches, unknown).
    qual = json.loads((ROOT / READS[0]).read_text(encoding='utf-8'))
    goals = {g['goal']: dict(lim, lower=g['lower'], upper=g['upper']) for g in qual['goals']}
    wrong = [c['id'] for c in qual['cases'] if H.classify_interval(c['interval'], goals[c['goal']]) != c['label']
             or oracle_label(c['interval'], goals[c['goal']]) != c['label']]
    out['the_24_frozen_cases_agree'] = {'pass': len(qual['cases']) == 24 and not wrong, 'wrong': wrong}
    # 7. Unknown stays unknown (unit, and the delivered record D with its follow-up).
    d_row = next(r for r in clean_doc['records'] if r['record'] == 'D')
    out['unknown_interval_is_unknown'] = {
        'pass': (H.classify_interval('unknown', lim) == 'unknown' and d_row['status'] == 'unknown'
                 and d_row['interval'] == 'unknown'
                 and {'category': 'uncertainty_required'} in d_row['follow_ups'])}
    # 8. Malformed input is refused by the operation, and a flow whose limits are malformed blocks at classify_A.
    refused = 0
    bad_intervals = [None, [], ['12.48 mm'], ['12.5 mm', '12.52 mm'], ['12.48', '12.52'], ['12.52 mm', '12.48 mm'],
                     [12.48, 12.52], 'inside']
    bad_limits = [None, {}, dict(lim, inclusive=False), dict(lim, unit='cm'), dict(lim, lower='12.5'),
                  dict(lim, lower='12.52', upper='12.48'), dict(lim, extra=1)]
    for interval in bad_intervals:
        try:
            H.classify_interval(interval, lim)
        except HostError:
            refused += 1
    for limits in bad_limits:
        try:
            H.classify_interval(['12.48 mm', '12.52 mm'], limits)
        except HostError:
            refused += 1
    open_limits = _graph_with(lambda g: [n['in']['limits']['lit'].update(inclusive=False)
                                         for n in g['nodes'] if n['id'].startswith('classify_')])
    copy = _copy(clean_copy, 'hc-badlimits')
    res = _run(copy, f'{prefix}-badlim', prefix, graph=open_limits)
    out['invalid_inputs_are_refused_by_the_host_op'] = {
        'pass': (refused == len(bad_intervals) + len(bad_limits) and res['status'] != 'delivered'
                 and (res['blocker'] or {}).get('reason') == 'host_refused'
                 and (res['blocker'] or {}).get('node') == 'classify_A' and res['launches'] == 0),
        'refused': refused, 'blocker': res['blocker']}
    # 9. Changed limits change the labels; the pack's graph rule sees any disagreement between the graph literal and
    # the structured limits (either one changed alone).
    wide = dict(lim, lower='12.40', upper='12.60')
    narrow = dict(lim, lower='12.50', upper='12.54')
    intervals = [exp['rev1'][n]['interval'] for n in 'ABCD']
    labels = lambda lims: [H.classify_interval(i, lims) for i in intervals]  # noqa: E731
    narrow_spec = json.loads(json.dumps(spec()))
    narrow_spec['limits'] = narrow
    narrow_spec['goal'] = narrow_spec['goal_template'].format(**narrow)
    out['changed_limits_change_labels_and_are_caught'] = {
        'pass': (labels(lim) == ['inside', 'outside', 'inside', 'unknown']
                 and labels(wide) == ['inside', 'inside', 'inside', 'unknown']
                 and labels(narrow) == ['outside', 'outside', 'inside', 'unknown']
                 and labels(wide) == [oracle_label(i, wide) for i in intervals]
                 and labels(narrow) == [oracle_label(i, narrow) for i in intervals]
                 and W.limits_problems(narrow_spec) == ['LOWER and UPPER disagree with the structured limits']
                 and bool(H.graph_problems(spec=narrow_spec))  # the graph literal still carries the old limits
                 and bool(H.graph_problems(_graph_with(lambda g: [
                     n['in']['limits']['lit'].update(upper='12.60') for n in g['nodes']
                     if n['id'].startswith('classify_')]))))}
    # 10. A graph whose literal limits were changed alone is refused by the graph rule. Run anyway, the host row check
    # (which recomputes the label from the frozen limits) stops it; when that check shares the change (a bug in both
    # host implementations) the package is delivered and the independent evaluator catches it.
    widened = _graph_with(lambda g: [n['in']['limits']['lit'].update(lower='12.40', upper='12.60')
                                     for n in g['nodes'] if n['id'].startswith('classify_')])
    copy = _copy(clean_copy, 'hc-widened-a')
    res_a = _run(copy, f'{prefix}-wide-a', prefix, graph=widened)
    copy = _copy(clean_copy, 'hc-widened-b')
    res_b = _run(copy, f'{prefix}-wide-b', prefix, graph=widened,
                 status_of=lambda bounds: H.classify_interval(bounds, wide))
    errors = _errors(copy, res_b, 'clean')
    out['changed_limits_in_the_graph_are_stopped_by_the_row_check_and_the_evaluator'] = {
        'pass': (bool(H.graph_problems(widened)) and res_a['status'] != 'delivered' and res_a['launches'] == 0
                 and (res_a['blocker'] or {}).get('node') == 'handoff_rows'
                 and res_b['status'] == 'delivered' and res_b['launches'] == 0
                 and any(e.startswith('B: status') for e in errors)),
        'row_check_blocker': res_a['blocker'], 'evaluator_errors_when_the_row_check_shares_the_change': errors[:3]}
    # 11. Node 11 superseded after the classify host operation computed but before it committed: the commit is
    # refused, the classification runs again on the new interval, and the delivery cites revision 2.
    copy = _copy(clean_copy, 'hc-older')
    rid_ = f'{prefix}-older'
    fired = []

    def supersede(_name):
        g = Flow(flow_dir(copy, rid_) / 'flow.sqlite')
        try:
            latest = g.latest()
            if not fired and 'checked_intervals' in latest and 'classify_A' not in latest:
                fired.append(g.bump_source('A', (PACK / 'sources/A.rev2.txt').read_bytes(),
                                           reason='older node 11 generation fixture'))
        finally:
            g.close()
    remove = oz_fault.on('flow.before_commit', supersede)
    try:
        res = _run(copy, rid_, prefix)
    finally:
        remove()
    g = Flow(flow_dir(copy, rid_) / 'flow.sqlite')
    try:
        refused_commits = [e['details'] for e in g.events() if e['event'] == 'commit_refused'
                           and e['details']['node'].startswith('classify_')]
        cites = g.deliveries()[0]['cites'] if g.deliveries() else {}
        final = json.loads(g.latest()['classify_A']['value'])
        classify_cites = [json.loads(r['cites']) for r in g.db.execute(
            "SELECT cites FROM acceptances WHERE node='classify_A'")]
    finally:
        g.close()
    errors = _errors(copy, res, 'stale')
    out['node11_superseded_before_the_classify_commit_is_refused'] = {
        'pass': (bool(fired) and bool(refused_commits) and res['status'] == 'delivered' and not errors
                 and cites.get('A') == 2 and final == 'outside' and all(c.get('A') == 2 for c in classify_cites)),
        'refused': refused_commits[:2], 'delivery_cites': cites, 'final_classify_A': final,
        'classify_A_acceptance_cites': classify_cites, 'evaluator_errors': errors}
    # 12. In the stale scenario the classifications are computed after the new node 11 and cite revision 2 only.
    stale_obs = (suite['scenarios'].get('stale') or {}).get('observables') or {}
    out['stale_scenario_classifies_on_the_new_interval'] = {
        'pass': bool(stale_obs.get('pass')) and stale_obs['checks'].get('host_classifications_cite_revision_2_only')
        is True,
        'checks': stale_obs.get('checks')}
    # 13. The integer oracle against the host operation over a grid of limits and intervals, against the Decimal
    # oracle of the fixture adapter, and against the frozen expected statuses.
    import fixture_adapter as FA
    cases = bad = 0
    for lower in range(1244, 1250):
        for upper in range(1250, 1256):
            limits = dict(lim, lower=f'{lower // 100}.{lower % 100:02d}', upper=f'{upper // 100}.{upper % 100:02d}')
            goal = f"[{limits['lower']},{limits['upper']}] mm"
            for low in range(1238, 1262):
                for high in range(low, 1262):
                    interval = [f'{low // 100}.{low % 100:02d} mm', f'{high // 100}.{high % 100:02d} mm']
                    cases += 1
                    host = H.classify_interval(interval, limits)
                    if not (host == oracle_label(interval, limits) == FA.classify_interval(interval, goal)):
                        bad += 1
    against_expected = [k for k, row in all_rows.items() if oracle_label(row['interval'], lim) != row['status']
                        or H.classify_interval(row['interval'], lim) != row['status']]
    out['independent_oracle_grid_agrees'] = {'pass': cases > 10000 and bad == 0 and not against_expected,
                                             'cases': cases, 'disagreements': bad, 'against_expected': against_expected}
    # 14. Every delivered package: statuses equal the oracle's label of the delivered interval, and the independent
    # evaluator (frozen expected values only) reports no error.
    problems = {}
    for name in S.SCENARIOS:
        delivered = _delivered(ws, prefix, name)
        wrong = [r['record'] for r in delivered['records'] if r['status'] != oracle_label(r['interval'], lim)]
        evaluator = suite['scenarios'][name]['evaluator']['errors']
        if wrong or evaluator:
            problems[name] = {'oracle_disagrees': wrong, 'evaluator': evaluator[:2]}
    out['evaluator_agrees_with_every_delivered_status'] = {'pass': not problems, 'problems': problems}
    # 15. Sabotaged host operations. With the real host row check in place each is stopped there; with that check
    # given the same wrong rule (a bug shared by both host implementations) the package is delivered and the
    # independent evaluator catches it.
    sab = {}
    for n, (name, scenario, status_of) in enumerate(_sabotages(lim)):
        wrong_op = HostOp('host.classify', 1, H.CLASSIFY.inputs,
                          lambda inputs, ctx, f=status_of: f(inputs['interval']))
        reg = W.registry(overrides={'host.classify': wrong_op})
        mutation = 'stale' if scenario == 'stale' else None
        copy = _copy(clean_copy, f'hc-sab{n}a')
        rid_a = f'{prefix}-sab{n}a'
        res_a = _run(copy, rid_a, prefix, registry=reg, mutation=mutation)
        blocked_a = res_a['status'] != 'delivered' and (res_a['blocker'] or {}).get('node') == 'handoff_rows'
        copy = _copy(clean_copy, f'hc-sab{n}b')
        rid_b = f'{prefix}-sab{n}b'
        res_b = _run(copy, rid_b, prefix, registry=reg, mutation=mutation, status_of=status_of)
        errors = _errors(copy, res_b, scenario)
        sab[name] = {'caught': bool(blocked_a and res_b['status'] == 'delivered' and errors),
                     'scenario': scenario, 'host_row_check_blocked': blocked_a,
                     'evaluator_errors_when_the_row_check_shares_the_bug': errors[:2]}
    out['sabotaged_host_operations_are_caught'] = {'pass': all(v['caught'] for v in sab.values()), 'cases': sab}
    return out


# ---- the dry gate ----

def suite(ws: Path, prefix: str) -> dict:
    """The five scenarios in order with their checks and the G3b verdict, then C5 (zero tokens, fixtures only)."""
    ws = ws.resolve()
    S.prepare(ws, 'fixture')
    report = {'gate': 'v3 dry', 'run_kind': 'fixture', 'prefix': prefix, 'freeze': freeze(), 'started_at': time.time(),
              'scenarios': {}}
    clean_copy = None
    for scenario in S.SCENARIOS:
        report['scenarios'][scenario] = S.scenario_report(ws, 'fixture', prefix, scenario)
        if scenario == 'clean':
            clean_copy = S.copy_of(ws, 'clean-state')
        row = report['scenarios'][scenario]
        print(scenario, G.LABEL if row[G.LABEL] else 'FAIL', row['launches'], 'recovered' if row['recovered'] else '',
              flush=True)
    report['c5'] = c5_checks(ws, prefix, clean_copy)
    usage = [flow_usage(ws, S.rid(prefix, s)) for s in S.SCENARIOS]
    report['totals'] = {'launches': sum(u['launches'] for u in usage),
                        'tokens_known': sum(u['tokens_known'] for u in usage),
                        'calls_without_usage': sum(u['calls_without_usage'] for u in usage),
                        'caps': S.allocation()}
    report['totals']['accounting'] = 'complete' if report['totals']['calls_without_usage'] == 0 else 'incomplete'
    report['g3b'] = G.suite_verdict(report)
    report['pass'] = report['g3b']['pass']
    return report


def dry(ws: Path, prefix: str = 'dry1') -> dict:
    """G2: the freeze must hold (full), then the v3 suite, the recovery cases and the host-classification fixtures.
    Zero tokens: only the fixture adapter and in-process fixtures answer."""
    ws = Path(ws).resolve()
    status = freeze()
    report = {'gate': 'v3 G2 (dry)', 'freeze': status, 'started_at': time.time()}
    if not status['frozen']:
        report['pass'] = False
        return report
    if ws.exists():
        shutil.rmtree(ws)
    for extra in ('.copies', '.g3b'):
        shutil.rmtree(ws.parent / (ws.name + extra), ignore_errors=True)
    result = suite(ws, prefix)
    report['suite'] = {k: result.get(k) for k in ('pass', 'g3b', 'totals', 'c5')}
    report['suite']['scenarios'] = {
        k: {'launches': v['launches'], 'packets': v['packets'], 'memo_hits': v['memo_hits'], 'pass_g3b': v[G.LABEL],
            'strict_pass': v['g3b']['strict_pass'], 'recovered': v['recovered']}
        for k, v in result['scenarios'].items()}
    report['recovery'] = recovery_fixtures(ws, 'g3b')
    try:
        report['fixtures'] = host_fixtures(ws, prefix, result)
    finally:
        os.environ['OZ_FIXTURE_DIR'] = str(ws / 'fixture')
    report['pass'] = (bool(result['pass']) and result['totals']['launches'] == 8
                      and all(v['pass'] for v in report['recovery'].values())
                      and all(v['pass'] for v in report['fixtures'].values())
                      and set(report['fixtures']) == set(FIXTURES))
    report['finished_at'] = time.time()
    (ws / 'report-v3-dry.json').write_text(json.dumps(report, indent=1, default=str) + '\n', encoding='utf-8')
    return report


# ---- command line ----

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('freeze')
    p.add_argument('--write', action='store_true')
    p = sub.add_parser('dry')
    p.add_argument('--workspace', type=Path, default=DRY_WS)
    p = sub.add_parser('run-flow')
    p.add_argument('--workspace', required=True, type=Path)
    p.add_argument('--kind', choices=('fixture', 'live'), required=True)
    p.add_argument('--prefix', required=True)
    p.add_argument('--scenario', choices=S.SCENARIOS, required=True)
    p.add_argument('--rerun', type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == 'freeze':
        try:
            result = freeze(write=args.write)
        except V3Error as exc:
            print('FREEZE FAILED: ' + str(exc))
            return 2
        print(json.dumps(result, indent=1))
        return 0 if result['frozen'] else 1
    if args.command == 'dry':
        report = dry(args.workspace)
        print(json.dumps({k: report.get(k) for k in ('gate', 'pass', 'freeze', 'suite', 'recovery', 'fixtures')},
                         indent=1, default=str))
        return 0 if report['pass'] else 3
    if args.kind == 'live':
        print('v3 allocates no live run: nothing was launched', file=sys.stderr)
        return 2
    if args.rerun:
        S.RERUN[args.scenario] = args.rerun
    ws = args.workspace.resolve()
    S.prepare(ws, args.kind)
    result = S.run_scenario_flow(ws, args.kind, args.prefix, args.scenario)
    print(json.dumps({k: result[k] for k in ('status', 'blocker', 'launches', 'targets')}, separators=(',', ':')))
    return 0 if result['status'] == 'delivered' else 3


if __name__ == '__main__':
    sys.exit(main())
