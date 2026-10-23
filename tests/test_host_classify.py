"""Step 4 v3 (docs/design/boundary-adoption-2026-10-23/decision-host-classify.md): the classify nodes are host
operations. This file covers the v3 pack and its per-pack module copies, the host.classify@1 operation (equality at
both limits, 0.01 breaches, changed limits, unknown, invalid inputs, an exhaustive grid against an independent
integer oracle), the graph rules, the freeze, the command line guards, the USAGE.md authoring rule and the zero-token
dry gate end to end. Nothing here is paid and no model is called."""
import copy
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'bench' / 'step4'))
sys.path.insert(0, str(ROOT))

from oz import Error  # noqa: E402
from oz_flow import HostError, HostOp, ModelOp  # noqa: E402
import adopt as A  # noqa: E402
import evaluator as E1  # noqa: E402
import host_classify as H  # noqa: E402
import packs  # noqa: E402
import step4 as S1  # noqa: E402
import v3  # noqa: E402
import workflow as W1  # noqa: E402

W2, E2 = A.W, A.E
W3, G3, E3 = H.W, H.G, H.E
LIMITS = {'lower': '12.48', 'upper': '12.52', 'unit': 'mm', 'inclusive': True}
V2_DIR = ROOT / 'bench' / 'step4' / 'inspection-handoff-20-v2'
V3_DIR = ROOT / 'bench' / 'step4' / 'inspection-handoff-20-v3'


def mm(hundredths: int) -> str:
    return f'{hundredths // 100}.{hundredths % 100:02d} mm'


def oracle(interval, lower: int, upper: int) -> str:
    """The independent integer oracle (hundredths of a millimetre, no Decimal, no float)."""
    if interval == 'unknown':
        return 'unknown'
    low, high = (int(x[:-3].replace('.', '')) for x in interval)
    return 'inside' if lower <= low and high <= upper else 'outside'


class PackTests(unittest.TestCase):
    def test_v3_is_beside_v1_and_v2_and_the_copies_are_separate(self):
        self.assertEqual(W3.FROZEN.name, 'inspection-handoff-20-v3')
        self.assertEqual((W1.WORKFLOW_ID, W2.WORKFLOW_ID, W3.WORKFLOW_ID),
                         ('inspection-handoff-20/v1', 'inspection-handoff-20/v2', 'inspection-handoff-20/v3'))
        self.assertEqual((E1.WORKFLOW, E2.WORKFLOW, E3.WORKFLOW),
                         ('inspection-handoff-20/v1', 'inspection-handoff-20/v2', 'inspection-handoff-20/v3'))
        self.assertEqual(E3.FROZEN, V3_DIR)
        self.assertEqual(G3.FROZEN, V3_DIR)
        self.assertIsNot(W3, W2)
        self.assertIs(packs.load('workflow'), W2)  # the default copy is still v2
        # The v3 operation is registered in the v3 copy only.
        self.assertIn('host.classify', {op.name for op in W3.HOST_OPS})
        self.assertNotIn('host.classify', {op.name for op in W2.HOST_OPS})
        self.assertNotIn('host.classify', {op.name for op in W1.HOST_OPS})
        self.assertIs(S1.W, W1)
        self.assertIs(H.S.W, W3)

    def test_v3_differs_from_v2_only_in_the_classify_nodes_and_what_follows_from_that(self):
        v2, v3d = W2.load('workflow.json'), W3.load('workflow.json')
        for key in ('goal', 'goal_template', 'limits', 'sources', 'mutations', 'fixture_route', 'deadlines', 'effects',
                    'target'):
            if key == 'mutations':
                self.assertEqual({k: {a: b for a, b in m.items() if a != 'note'} for k, m in v2[key].items()},
                                 {k: {a: b for a, b in m.items() if a != 'note'} for k, m in v3d[key].items()})
            else:
                self.assertEqual(v2[key], v3d[key], key)
        self.assertEqual(set(v3d['model_ops']), {'model.extract', 'model.bounds'})
        for name in ('model.extract', 'model.bounds'):
            self.assertEqual(v2['model_ops'][name], v3d['model_ops'][name])
        self.assertIn('host.classify@1', v3d['host_ops'])
        self.assertEqual([h for h in v3d['host_ops'] if h != 'host.classify@1'], v2['host_ops'])
        self.assertEqual({s['name']: (s['expected_launches'], s['expected_packets'], s['expected_memo_hits'])
                          for s in v3d['scenarios']},
                         {'clean': (2, [4, 4], 0), 'repeat': (0, [], 8), 'interrupt': (2, [4, 4], 0),
                          'stale': (4, [4, 4, 1, 1], 6), 'bump': (0, [], 16)})
        for name in ('expected.json', 'sources/A.txt', 'sources/A.rev2.txt', 'sources/B.txt', 'sources/C.txt',
                     'sources/D.txt'):
            self.assertEqual((V2_DIR / name).read_bytes(), (V3_DIR / name).read_bytes(), name)
        g2, g3d = W2.graph(), W3.graph()
        self.assertEqual(len(g3d['nodes']), 20)
        self.assertEqual(len(g2['nodes']), 20)
        for a, b in zip(g2['nodes'], g3d['nodes']):
            self.assertEqual(a['id'], b['id'])
            if a['id'].startswith('classify_'):
                self.assertEqual(b['op'], 'host.classify')
                self.assertEqual(b['in'], {'interval': {'node': 'checked_intervals',
                                                        'path': '/bounds/' + a['id'][-1]},
                                           'limits': {'lit': LIMITS}})
            else:
                self.assertEqual(a, b)
        self.assertEqual({n['op'] for n in g3d['nodes'] if n['op'].startswith('model.')},
                         {'model.extract', 'model.bounds'})

    def test_the_structured_limits_agree_and_the_graph_literal_is_the_same_object_of_truth(self):
        spec = W3.load('workflow.json')
        self.assertEqual(spec['limits'], LIMITS)
        self.assertEqual(W3.limits_problems(), [])
        self.assertEqual((W3.LOWER, W3.UPPER), (Decimal('12.48'), Decimal('12.52')))
        self.assertEqual(E3.ACCEPTANCE_INTERVAL, {'lower': '12.48 mm', 'upper': '12.52 mm', 'inclusive': True})
        self.assertEqual(H.graph_problems(), [])
        bad = copy.deepcopy(spec)
        bad['goal'] = bad['goal'].replace('12.52', '12.53')
        self.assertTrue(W3.limits_problems(bad))

    def test_the_registry_has_the_host_operation_and_no_model_classify(self):
        reg = W3.registry()
        self.assertIsInstance(reg['host.classify'], HostOp)
        self.assertEqual(reg['host.classify'].identity, 'host.classify@1')
        self.assertEqual(reg['host.classify'].inputs, frozenset({'interval', 'limits'}))
        self.assertIsNone(reg['host.classify'].effect)
        self.assertNotIn('model.classify', reg)
        self.assertIsInstance(reg['model.extract'], ModelOp)
        self.assertIsInstance(reg['model.bounds'], ModelOp)
        self.assertEqual(reg['model.extract'].identity, W2.registry()['model.extract'].identity)
        self.assertEqual(reg['model.bounds'].identity, W2.registry()['model.bounds'].identity)

    def test_the_graph_rules(self):
        base = W3.graph()

        def broken(edit):
            graph = copy.deepcopy(base)
            edit(graph)
            return H.graph_problems(graph)

        def node(graph, name):
            return next(n for n in graph['nodes'] if n['id'] == name)
        self.assertEqual(H.graph_problems(base), [])
        self.assertTrue(broken(lambda g: node(g, 'classify_A')['in']['interval'].update(path='/bounds/B')))
        self.assertTrue(broken(lambda g: node(g, 'classify_A')['in']['interval'].update(node='normalized_records')))
        self.assertTrue(broken(lambda g: node(g, 'classify_C')['in']['limits']['lit'].update(upper='12.53')))
        self.assertTrue(broken(lambda g: node(g, 'classify_C')['in']['limits']['lit'].update(inclusive=False)))
        self.assertTrue(broken(lambda g: node(g, 'classify_D')['in'].update(limits={'node': 'snapshot'})))
        self.assertTrue(broken(lambda g: node(g, 'classify_D').update(op='model.classify')))
        self.assertTrue(broken(lambda g: node(g, 'classify_B').update(after=['extract_A'])))
        self.assertTrue(broken(lambda g: g['nodes'].pop(g['nodes'].index(node(g, 'classify_B')))))
        self.assertTrue(broken(lambda g: node(g, 'handoff_rows')['in']['status']['list'].reverse()))


class HostOperationTests(unittest.TestCase):
    def label(self, interval, limits=LIMITS):
        return H.classify_interval(interval, limits)

    def test_equality_at_both_limits_is_inside(self):
        self.assertEqual(self.label(['12.48 mm', '12.52 mm']), 'inside')
        self.assertEqual(self.label(['12.48 mm', '12.50 mm']), 'inside')
        self.assertEqual(self.label(['12.50 mm', '12.52 mm']), 'inside')
        self.assertEqual(self.label(['12.50 mm', '12.50 mm']), 'inside')

    def test_a_breach_of_one_hundredth_is_outside(self):
        self.assertEqual(self.label(['12.47 mm', '12.52 mm']), 'outside')
        self.assertEqual(self.label(['12.48 mm', '12.53 mm']), 'outside')
        self.assertEqual(self.label(['12.47 mm', '12.53 mm']), 'outside')
        self.assertEqual(self.label(['12.53 mm', '12.57 mm']), 'outside')
        self.assertEqual(self.label(['12.30 mm', '12.40 mm']), 'outside')

    def test_unknown_stays_unknown_even_with_other_limits(self):
        self.assertEqual(self.label('unknown'), 'unknown')
        self.assertEqual(self.label('unknown', dict(LIMITS, lower='10.00', upper='10.08')), 'unknown')

    def test_changed_limits_change_the_labels(self):
        goal2 = dict(LIMITS, lower='10.00', upper='10.08')
        goal3 = dict(LIMITS, lower='12.46', upper='12.54')
        self.assertEqual(self.label(['10.00 mm', '10.08 mm'], goal2), 'inside')
        self.assertEqual(self.label(['9.99 mm', '10.01 mm'], goal2), 'outside')
        self.assertEqual(self.label(['12.46 mm', '12.54 mm'], goal3), 'inside')
        self.assertEqual(self.label(['12.44 mm', '12.50 mm'], goal3), 'outside')
        self.assertEqual(self.label(['12.44 mm', '12.50 mm']), 'outside')
        self.assertEqual(self.label(['12.47 mm', '12.53 mm'], goal3), 'inside')
        self.assertEqual(self.label(['12.47 mm', '12.53 mm']), 'outside')

    def test_the_24_frozen_cases_of_the_v2_qualification_agree(self):
        qual = json.loads((V2_DIR / 'qual.json').read_text(encoding='utf-8'))
        goals = {g['goal']: dict(LIMITS, lower=g['lower'], upper=g['upper']) for g in qual['goals']}
        self.assertEqual(len(qual['cases']), 24)
        for case in qual['cases']:
            self.assertEqual(self.label(case['interval'], goals[case['goal']]), case['label'], case['id'])

    def test_every_interval_on_a_grid_agrees_with_the_independent_integer_oracle(self):
        count = 0
        for lower in (1246, 1247, 1248, 1249):
            for upper in (1251, 1252, 1253, 1254):
                limits = dict(LIMITS, lower=mm(lower)[:-3], upper=mm(upper)[:-3])
                for low in range(1240, 1261):
                    for high in range(low, 1261):
                        interval = [mm(low), mm(high)]
                        self.assertEqual(self.label(interval, limits), oracle(interval, lower, upper),
                                         (interval, limits))
                        count += 1
        self.assertGreater(count, 3000)

    def test_the_operation_through_its_registered_entry(self):
        op = W3.registry()['host.classify']
        inputs = {'interval': ['12.48 mm', '12.52 mm'], 'limits': LIMITS}
        self.assertEqual(op.run(inputs, None), 'inside')
        self.assertEqual(op.run({'interval': 'unknown', 'limits': LIMITS}, None), 'unknown')
        self.assertEqual(op.run({'interval': ['12.47 mm', '12.52 mm'], 'limits': LIMITS}, None), 'outside')

    def test_malformed_intervals_and_limits_are_refused_never_guessed(self):
        bad_intervals = [None, 12.5, 'inside', 'Unknown', [], ['12.48 mm'], ['12.48 mm', '12.52 mm', '12.55 mm'],
                         ['12.48', '12.52'], ['12.5 mm', '12.52 mm'], ['12.480 mm', '12.52 mm'],
                         ['12.48 cm', '12.52 mm'], [12.48, 12.52], ['12.52 mm', '12.48 mm'], ['a mm', 'b mm'],
                         {'low': '12.48 mm', 'high': '12.52 mm'}, ['12.48 mm', None], ['12.48 mm', 'unknown']]
        for interval in bad_intervals:
            with self.assertRaises(HostError, msg=repr(interval)):
                self.label(interval)
        bad_limits = [None, [], 'mm', {}, dict(LIMITS, inclusive=False), dict(LIMITS, inclusive='true'),
                      dict(LIMITS, unit='cm'), dict(LIMITS, lower=12.48), dict(LIMITS, lower='12.5'),
                      dict(LIMITS, upper='12.520'), dict(LIMITS, lower='12.52', upper='12.48'),
                      dict(LIMITS, lower='12.50', upper='12.50'), dict(LIMITS, extra=1),
                      {k: v for k, v in LIMITS.items() if k != 'upper'}]
        for limits in bad_limits:
            with self.assertRaises(HostError, msg=repr(limits)):
                self.label(['12.48 mm', '12.52 mm'], limits)
        with self.assertRaises(HostError):  # even when the interval is unknown, bad limits are not skipped
            self.label('unknown', dict(LIMITS, inclusive=False))

    def test_the_arithmetic_is_decimal_not_float(self):
        # 0.1 + 0.2 style traps: these boundary values are not exactly representable as binary floats.
        limits = dict(LIMITS, lower='0.10', upper='0.30')
        self.assertEqual(self.label(['0.10 mm', '0.30 mm'], limits), 'inside')
        self.assertEqual(self.label(['0.09 mm', '0.30 mm'], limits), 'outside')
        self.assertEqual(self.label(['0.10 mm', '0.31 mm'], limits), 'outside')

    def test_the_label_of_node_11_s_own_intervals_matches_the_v1_host_function(self):
        for interval in (['12.48 mm', '12.52 mm'], ['12.44 mm', '12.50 mm'], ['12.50 mm', '12.52 mm'],
                         ['12.53 mm', '12.57 mm'], 'unknown'):
            self.assertEqual(self.label(interval), W3.status_of(interval))
            self.assertEqual(self.label(interval), W1.status_of(interval))


class FreezeTests(unittest.TestCase):
    def test_the_freeze_holds_and_covers_pack_code_and_design(self):
        status = v3.freeze()
        self.assertTrue(status['frozen'], status['problems'][:3])
        record = json.loads(v3.FREEZE_FILE.read_text(encoding='utf-8'))
        self.assertEqual(record['digest'], status['digest'])
        pack = set(record['files']['pack'])
        self.assertIn('bench/step4/inspection-handoff-20-v3/workflow.json', pack)
        self.assertIn('bench/step4/inspection-handoff-20-v3/graph.json', pack)
        self.assertNotIn('bench/step4/inspection-handoff-20-v3/freeze.json', pack)
        self.assertTrue(all('-v3/' in p for p in pack))
        code = set(record['files']['code'])
        for name in ('bench/step4/host_classify.py', 'bench/step4/v3.py', 'bench/step4/workflow.py',
                     'bench/step4/evaluator.py', 'bench/step4/g3b.py', 'bench/step4/step4.py',
                     'bench/step4/packs.py', 'bench/step4/fixture_adapter.py', 'oz_flow.py'):
            self.assertIn(name, code)
        design = set(record['files']['design'])
        for name in ('decision-host-classify.md', '05-astra-next.md', '06-opus-next.md'):
            self.assertIn(f'docs/design/boundary-adoption-2026-10-23/{name}', design)
        self.assertEqual(record['plan']['expected_launches'], {'clean': 2, 'repeat': 0, 'interrupt': 2, 'stale': 4,
                                                               'bump': 0})

    def test_the_freeze_is_sensitive_to_its_files(self):
        original = v3.ndigest
        with patch.object(v3, 'ndigest', lambda p: 'x' if Path(p).name == 'host_classify.py' else original(p)):
            status = v3.freeze(full=False)
        self.assertFalse(status['frozen'])
        self.assertIn('bench/step4/host_classify.py changed since the freeze', status['problems'])
        with patch.object(v3, 'ndigest', lambda p: 'x' if Path(p).name == 'graph.json' else original(p)):
            status = v3.freeze(full=False)
        self.assertIn('bench/step4/inspection-handoff-20-v3/graph.json changed since the freeze', status['problems'])

    def test_the_v1_and_v2_freezes_still_hold_untouched(self):
        self.assertTrue(S1.freeze()['frozen'], S1.freeze()['problems'][:3])
        self.assertTrue(A.freeze(full=False)['frozen'], A.freeze(full=False)['problems'][:3])


class GuardTests(unittest.TestCase):
    def test_there_is_no_paid_command_and_a_live_flow_is_refused(self):
        with self.assertRaises(SystemExit):
            v3.main(['live', '--workspace', 'x'])
        with self.assertRaises(SystemExit):
            v3.main(['qualify', '--expect', 'x'])
        with patch.object(v3.S, 'run_scenario_flow') as run:
            code = v3.main(['run-flow', '--workspace', 'x', '--kind', 'live', '--prefix', 'p', '--scenario', 'clean'])
        self.assertEqual(code, 2)
        run.assert_not_called()

    def test_the_fixture_route_is_the_only_route_a_v3_run_uses(self):
        self.assertEqual(v3.S.spec()['fixture_route']['model'], 'fixture-oracle-1')
        self.assertEqual(v3.S.route('fixture')[1], 'fixture-oracle-1')


class UsageGuidanceTests(unittest.TestCase):
    def test_usage_carries_the_authoring_rule_with_its_citation_and_no_dashes(self):
        text = (ROOT / 'USAGE.md').read_text(encoding='utf-8')
        self.assertIn('## Authoring guidance', text)
        section = text.split('## Authoring guidance', 1)[1].split('\n## ', 1)[0]
        self.assertIn('host operation', section)
        self.assertIn('docs/design/boundary-adoption-2026-10-23/decision-host-classify.md', section)
        self.assertIn('experimental reason', section)
        for dash in ('—', '–', ' - '):
            self.assertNotIn(dash, section)
        self.assertLess(len(section.split()), 220)  # a short note


class DryGateTests(unittest.TestCase):
    def test_the_zero_token_dry_gate_passes_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = os.environ.get('OZ_FIXTURE_DIR')
            try:
                report = v3.dry(Path(tmp) / 'hc')
                invocations = Path(tmp) / 'hc' / 'fixture' / 'invocations.jsonl'
                logged = [json.loads(x) for x in invocations.read_text(encoding='utf-8').splitlines()]
            finally:
                if saved is None:
                    os.environ.pop('OZ_FIXTURE_DIR', None)
                else:
                    os.environ['OZ_FIXTURE_DIR'] = saved
        self.assertTrue(report['freeze']['frozen'], report['freeze']['problems'][:3])
        suite = report['suite']
        self.assertTrue(suite['pass'], suite)
        self.assertEqual({k: v['launches'] for k, v in suite['scenarios'].items()},
                         {'clean': 2, 'repeat': 0, 'interrupt': 2, 'stale': 4, 'bump': 0})
        self.assertEqual({k: v['packets'] for k, v in suite['scenarios'].items()},
                         {'clean': [4, 4], 'repeat': [], 'interrupt': [4, 4], 'stale': [4, 4, 1, 1], 'bump': []})
        self.assertEqual({k: v['memo_hits'] for k, v in suite['scenarios'].items()},
                         {'clean': 0, 'repeat': 8, 'interrupt': 0, 'stale': 6, 'bump': 16})
        self.assertTrue(all(v['pass_g3b'] for v in suite['scenarios'].values()))
        self.assertTrue(all(v['strict_pass'] for v in suite['scenarios'].values()))
        self.assertEqual(suite['totals']['launches'], 8)
        self.assertTrue(all(v['pass'] for v in suite['c5'].values()), suite['c5'])
        self.assertTrue(all(v['pass'] for v in report['recovery'].values()), report['recovery'])
        fixtures = report['fixtures']
        for name in ('limits_agree_and_a_disagreeing_goal_is_refused', 'graph_binds_interval_and_limits_per_record',
                     'no_classify_model_job_in_any_scenario', 'equality_at_both_limits_is_inside',
                     'breaches_by_0_01_are_outside', 'the_24_frozen_cases_agree', 'unknown_interval_is_unknown',
                     'invalid_inputs_are_refused_by_the_host_op', 'changed_limits_change_labels_and_are_caught',
                     'changed_limits_in_the_graph_are_stopped_by_the_row_check_and_the_evaluator',
                     'node11_superseded_before_the_classify_commit_is_refused',
                     'stale_scenario_classifies_on_the_new_interval', 'independent_oracle_grid_agrees',
                     'evaluator_agrees_with_every_delivered_status', 'sabotaged_host_operations_are_caught'):
            self.assertIn(name, fixtures)
        self.assertTrue(all(v['pass'] for v in fixtures.values()), {k: v for k, v in fixtures.items()
                                                                    if not v['pass']})
        self.assertTrue(report['pass'])
        # Zero tokens: only the fixture oracle answered, once per launch of the five scenarios plus the fixtures.
        self.assertTrue(logged)
        self.assertEqual(suite['totals']['calls_without_usage'], 0)
        self.assertFalse(any('classify' in ' '.join(x['ids']) for x in logged))


if __name__ == '__main__':
    unittest.main()
