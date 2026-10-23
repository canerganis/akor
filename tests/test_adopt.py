"""Boundary adoption (docs/design/boundary-adoption-2026-10-23/): the v2 pack's structured limits and their
consumers, the two-ref check mat_classify_interval@1, the 24 frozen cases, the frozen run order, the qualification
packets from the workflow's own packer, the qualification run loop and scoring, the adoption verdict, the live guards,
the amended predicate's two-ref semantics, and the zero-token dry gate end to end. Nothing here is paid."""
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
from oz_accept import Inputs  # noqa: E402
from oz_batch import J  # noqa: E402
import adopt as A  # noqa: E402
import evaluator as E1  # noqa: E402
import fixture_adapter as FA  # noqa: E402
import g3b as G1  # noqa: E402
import packs  # noqa: E402
import workflow as W1  # noqa: E402

W2, G2, E2 = A.W, A.G, A.E
A_REV1 = W1.source_bytes('A').decode('utf-8')
A_REV2 = W1.source_bytes('A', 'rev2').decode('utf-8')
D_REC = W1.source_bytes('D').decode('utf-8')


def check(record, interval, value, refs=None):
    raws = refs if refs is not None else [J(record), J(interval)]
    return W2.CHECKS['mat_classify_interval'].run(value, {}, Inputs(({'op': 'x', 'refs': raws},)))


class PackTests(unittest.TestCase):
    def test_the_copies_read_their_own_pack_and_v1_is_untouched(self):
        self.assertEqual(W1.FROZEN.name, 'inspection-handoff-20-v1')
        self.assertEqual(W2.FROZEN.name, 'inspection-handoff-20-v2')
        self.assertEqual((W1.WORKFLOW_ID, W2.WORKFLOW_ID), ('inspection-handoff-20/v1', 'inspection-handoff-20/v2'))
        self.assertEqual((E1.WORKFLOW, E2.WORKFLOW), ('inspection-handoff-20/v1', 'inspection-handoff-20/v2'))
        self.assertEqual(G1.FROZEN.name, 'inspection-handoff-20-v1')
        self.assertIs(packs.load('workflow'), W2)
        self.assertNotIn('inputs', W1.load('workflow.json')['model_ops']['model.classify'])
        self.assertTrue(W1.registry()['model.classify'].single)

    def test_v2_differs_from_v1_only_in_the_classify_operation_its_limits_and_labels(self):
        v1, v2 = W1.load('workflow.json'), W2.load('workflow.json')
        for key in ('goal', 'sources', 'mutations', 'route', 'fixture_route', 'deadlines', 'scenarios', 'effects',
                    'host_ops', 'target'):
            self.assertEqual(v1[key], v2[key], key)
        for name in ('model.extract', 'model.bounds'):
            self.assertEqual(v1['model_ops'][name], v2['model_ops'][name])
        for name in ('expected.json', 'sources/A.txt', 'sources/A.rev2.txt', 'sources/B.txt', 'sources/C.txt',
                     'sources/D.txt'):
            self.assertEqual((W1.FROZEN / name).read_bytes(), (W2.FROZEN / name).read_bytes(), name)
        c = v2['model_ops']['model.classify']
        self.assertEqual((c['version'], c['inputs'], c['value_inputs'], c['checks']),
                         (2, ['record', 'interval'], ['interval'], [{'check': 'mat_classify_interval'}]))
        self.assertEqual(c['instruction'], (
            "The first ref is the measurement record. The second ref is its host-checked interval: [lower,upper], or "
            "unknown. If the interval is unknown, return unknown. Otherwise use its endpoints directly. Let L and U "
            "be the lower and upper limits of the goal's acceptance interval, in mm. Return inside if lower >= L AND "
            "upper <= U; outside otherwise. Equality at either limit is inside."))

    def test_the_structured_limits_are_the_one_source_every_consumer_agrees_with(self):
        spec = W2.load('workflow.json')
        lim = spec['limits']
        self.assertEqual(lim, {'lower': '12.48', 'upper': '12.52', 'unit': 'mm', 'inclusive': True})
        self.assertEqual(W2.limits_problems(), [])
        self.assertEqual(spec['goal'], spec['goal_template'].format(lower='12.48', upper='12.52'))
        self.assertEqual((W2.LOWER, W2.UPPER), (Decimal('12.48'), Decimal('12.52')))
        self.assertEqual((W1.LOWER, W1.UPPER), (W2.LOWER, W2.UPPER))  # v1's constants are the same numbers
        want = {'lower': '12.48 mm', 'upper': '12.52 mm', 'inclusive': True}
        self.assertEqual(W2.handoff_document([])['acceptance_interval'], want)
        self.assertEqual(W1.handoff_document([])['acceptance_interval'], want)
        self.assertEqual(E2.ACCEPTANCE_INTERVAL, want)  # the evaluator's own copy
        self.assertIn('Acceptance interval: [12.48 mm, 12.52 mm], inclusive.',
                      W2.op_render_markdown({'rows': {'rows': []}}, None))
        self.assertEqual(check(A_REV1, ['12.48 mm', '12.52 mm'], 'inside'), True)
        self.assertEqual(check(A_REV1, ['12.48 mm', '12.52 mm'], 'outside'), False)

    def test_a_goal_or_limit_that_disagrees_is_refused(self):
        spec = W2.load('workflow.json')
        for edit in (lambda s: s.update(goal=s['goal'].replace('12.52', '12.53')),
                     lambda s: s['limits'].update(upper='12.53'),
                     lambda s: s['limits'].update(inclusive=False),
                     lambda s: s['limits'].update(lower='12.5'),
                     lambda s: s.update(goal_template=s['goal_template'].replace('{upper}', '12.52'))):
            bad = copy.deepcopy(spec)
            edit(bad)
            self.assertTrue(W2.limits_problems(bad), bad['limits'])
        bad = copy.deepcopy(spec)
        bad['goal'] = bad['goal'].replace('12.48', '12.47')
        with patch.object(W2, 'load', lambda name: bad if name == 'workflow.json' else W1.load(name)):
            with self.assertRaisesRegex(Error, 'limits'):
                W2.registry()

    def test_the_graph_binds_record_and_interval_of_the_same_record_from_node_11(self):
        self.assertEqual(W2.graph_problems(), [])
        node = next(n for n in W2.graph()['nodes'] if n['id'] == 'classify_C')
        self.assertEqual(node['in'], {'record': {'node': 'checked_intervals', 'path': '/records/C'},
                                      'interval': {'node': 'checked_intervals', 'path': '/bounds/C'}})
        for path, where in (('/bounds/B', 'interval'), ('/records/B', 'record')):
            graph = copy.deepcopy(W2.graph())
            target = next(n for n in graph['nodes'] if n['id'] == 'classify_A')
            target['in'][where]['path'] = path
            self.assertTrue(W2.graph_problems(graph))
        graph = copy.deepcopy(W2.graph())
        next(n for n in graph['nodes'] if n['id'] == 'classify_A')['in']['interval']['node'] = 'normalized_records'
        self.assertTrue(W2.graph_problems(graph))

    def test_the_registry_builds_the_ordered_value_form_operation(self):
        op = W2.registry()['model.classify']
        self.assertEqual((op.version, op.ref_order, op.values), (2, ('record', 'interval'), frozenset({'interval'})))
        self.assertFalse(op.single)
        self.assertNotEqual(op.identity, W1.registry()['model.classify'].identity)


class TwoRefCheckTests(unittest.TestCase):
    def test_right_labels_pass(self):
        self.assertTrue(check(A_REV2, ['12.53 mm', '12.57 mm'], 'outside'))
        self.assertTrue(check(D_REC, 'unknown', 'unknown'))
        self.assertTrue(check(W1.source_bytes('C').decode('utf-8'), ['12.50 mm', '12.52 mm'], 'inside'))

    def test_wrong_label_wrong_pairing_stale_interval_and_bad_shapes_fail(self):
        self.assertFalse(check(A_REV1, ['12.48 mm', '12.52 mm'], 'outside'))
        self.assertFalse(check(A_REV1, ['12.44 mm', '12.50 mm'], 'outside'))  # B's interval with A's record
        self.assertFalse(check(A_REV2, ['12.48 mm', '12.52 mm'], 'inside'))  # an older generation's interval
        self.assertFalse(check(D_REC, ['12.48 mm', '12.52 mm'], 'inside'))
        self.assertFalse(check(A_REV1, 'unknown', 'unknown'))
        self.assertFalse(check(None, None, 'inside', refs=[J(A_REV1)]))  # one ref
        self.assertFalse(check(None, None, 'inside', refs=[J(A_REV1), J(['12.48 mm', '12.52 mm']), J('x')]))
        self.assertFalse(check(None, None, 'inside', refs=[J(['x']), J(['12.48 mm', '12.52 mm'])]))
        self.assertFalse(check(A_REV1, ['12.48 mm'], 'inside'))
        self.assertFalse(check(A_REV1, '["12.48 mm","12.52 mm"]', 'inside'))  # the interval double encoded
        self.assertTrue(W2.CHECKS['mat_classify_interval'].job_bound)


class CaseTests(unittest.TestCase):
    def test_the_24_cases_are_the_signed_table_and_recompute_on_the_host(self):
        self.assertEqual(A.case_problems(), [])
        labels = {c['id']: (c['interval'], c['label']) for c in A.qual()['cases']}
        self.assertEqual(labels['g1c1'], (['12.48 mm', '12.52 mm'], 'inside'))
        self.assertEqual(labels['g1c5'], (['12.47 mm', '12.49 mm'], 'outside'))
        self.assertEqual(labels['g1c7'], (['12.53 mm', '12.57 mm'], 'outside'))  # exactly the stale A
        self.assertEqual(labels['g2c4'], (['10.01 mm', '10.07 mm'], 'inside'))
        self.assertEqual(labels['g2c5'], (['9.99 mm', '10.01 mm'], 'outside'))
        self.assertEqual(labels['g3c2'], (['12.46 mm', '12.52 mm'], 'inside'))
        self.assertEqual(labels['g3c6'], (['12.53 mm', '12.55 mm'], 'outside'))
        self.assertEqual(labels['g3c8'], ('unknown', 'unknown'))
        self.assertEqual(sorted({c['label'] for c in A.qual()['cases'] if c['case'] <= 4}), ['inside'])
        self.assertEqual(sorted({c['label'] for c in A.qual()['cases'] if c['case'] in (5, 6, 7)}), ['outside'])

    def test_workflow_records_reappear_as_cases(self):
        cases = {c['id']: c['record'] for c in A.qual()['cases']}
        self.assertEqual(cases['g1c1'], A_REV1)
        self.assertEqual(cases['g1c3'], W1.source_bytes('C').decode('utf-8'))
        self.assertEqual(cases['g1c7'], A_REV2)
        self.assertEqual(cases['g1c8'], D_REC)

    def test_goal_three_separates_a_model_that_ignores_the_goal(self):
        for number in (2, 3, 4):
            c = A.case(3, number)
            self.assertEqual(c['label'], 'inside')
            self.assertEqual(A.oracle_label(c['interval'], Decimal('12.48'), Decimal('12.52')), 'outside')

    def test_a_case_that_breaks_the_table_is_found(self):
        q = A.qual()
        bad = copy.deepcopy(q)
        bad['cases'][4]['interval'] = ['12.46 mm', '12.50 mm']
        with patch.object(A, 'qual', return_value=bad):
            self.assertTrue(A.case_problems())
        bad = copy.deepcopy(q)
        bad['cases'][5]['label'] = 'inside'
        with patch.object(A, 'qual', return_value=bad):
            self.assertTrue(A.case_problems())
        bad = copy.deepcopy(q)
        bad['cases'][4]['record'] = bad['cases'][4]['record'].replace('0.01 mm', '0.02 mm')
        with patch.object(A, 'qual', return_value=bad):
            self.assertTrue(A.case_problems())


class ScheduleAndPacketTests(unittest.TestCase):
    def test_the_frozen_order(self):
        slots = A.schedule()
        self.assertEqual(len(slots), 36)
        self.assertEqual([s['cell'] for s in slots], ['size4'] * 12 + ['size1'] * 24)
        self.assertEqual([(s['goal'], s['cases']) for s in slots[:4]],
                         [(1, [1, 5, 3, 8]), (1, [8, 3, 5, 1]), (1, [2, 6, 4, 7]), (1, [7, 4, 6, 2])])
        self.assertEqual([s['goal'] for s in slots[:12]], [1] * 4 + [2] * 4 + [3] * 4)
        self.assertEqual([(s['cases'][0], s['goal']) for s in slots[12:15]], [(1, 1), (1, 2), (1, 3)])
        self.assertEqual([s['cases'][0] for s in slots[12::3]], [1, 5, 3, 8, 2, 6, 4, 7])
        self.assertEqual(slots[1]['expected'], {'classify_A': 'unknown', 'classify_B': 'inside',
                                                'classify_C': 'outside', 'classify_D': 'inside'})
        self.assertEqual(slots[12]['ids'], ['classify_A'])

    def test_every_packet_comes_from_the_packer_in_the_value_form_and_layout(self):
        reqs = A.requests()
        self.assertEqual(len(reqs), 36)
        for slot in A.schedule():
            members = [(A.case(slot['goal'], k)['record'], A.case(slot['goal'], k)['interval'])
                       for k in slot['cases']]
            self.assertEqual(A.packet_problems(reqs[slot['slot']]['prompt'], A.goal_text(slot['goal']), members), [])
            self.assertEqual(reqs[slot['slot']]['system'], A.SYSTEM)
        body = json.loads(reqs[1]['prompt'])
        self.assertEqual(body['refs'][1], ['12.48 mm', '12.52 mm'])
        self.assertEqual(body['refs'][7], 'unknown')
        self.assertIn('["12.47 mm","12.49 mm"]', reqs[1]['prompt'])
        self.assertEqual(json.loads(reqs[5]['prompt'])['goal'], A.goal_text(2))
        self.assertIn('[10.00,10.08] mm', A.goal_text(2))

    def test_the_layout_rule_catches_a_double_encoded_interval_or_another_order(self):
        members = A.workflow_members('rev1')
        good = A.clean_packet()['prompt']
        self.assertEqual(A.packet_problems(good, A.spec()['goal'], members), [])
        body = json.loads(good)
        body['refs'][1] = J(body['refs'][1])
        self.assertTrue(A.packet_problems(J(body), A.spec()['goal'], members))
        body = json.loads(good)
        body['refs'] = body['refs'][0::2] + body['refs'][1::2]
        body['jobs'] = [[0, *[[j, k, k + 4] for k, j in enumerate(A.qual()['job_ids'])]]]
        self.assertTrue(A.packet_problems(J(body), A.spec()['goal'], members))

    def test_the_freeze_holds_and_stores_the_samples(self):
        status = A.freeze()
        self.assertTrue(status['frozen'], status['problems'][:5])
        stored = json.loads(A.FREEZE_FILE.read_text(encoding='utf-8'))
        samples = stored['qualification']['samples']
        self.assertEqual(samples['size4'], A.requests()[1]['prompt'])
        self.assertEqual(samples['size1'], A.requests()[13]['prompt'])
        self.assertEqual(samples['clean_classify'], A.clean_packet()['prompt'])
        self.assertEqual(len(stored['qualification']['slots']), 36)
        for name in ('oz_flow.py', 'oz_do.py', 'bench/step4/adopt.py', 'bench/probe/boundary.py'):
            self.assertIn(name, stored['files']['code'])
        self.assertIn('docs/design/boundary-adoption-2026-10-23/03-astra-r2-signed.md', stored['files']['design'])

    def test_the_freeze_is_sensitive_to_its_files(self):
        original = A.files_record

        def changed():
            out = original()
            out['code']['oz_flow.py'] = 'f' * 64
            return out
        with patch.object(A, 'files_record', changed):
            status = A.freeze(full=False)
        self.assertFalse(status['frozen'])
        self.assertIn('oz_flow.py changed since the freeze', status['problems'])


def envelope(reply, **options):
    return json.dumps(A.B.fixture_envelope(reply, **options)).encode('utf-8')


class EvaluateTests(unittest.TestCase):
    EXP = {'classify_A': 'inside', 'classify_B': 'outside'}
    GOOD = 'OZ/1g\n{"classify_A":"inside"}\n{"classify_B":"outside"}'

    def ev(self, stdout, **kw):
        return A.evaluate(kw.get('exit', 0), kw.get('timed_out', False), kw.get('ms', 5000), stdout, self.EXP, 300)

    def test_a_right_reply_passes(self):
        ev = self.ev(envelope(self.GOOD))
        self.assertTrue(ev['passed'])
        self.assertEqual((ev['outcome'], ev['correct_members'], ev['route']), ('correct', 2, 'ok'))

    def test_every_failure_mode_fails(self):
        cases = {
            'semantic': self.ev(envelope(self.GOOD.replace('"outside"', '"inside"'))),
            'model_error': self.ev(envelope('OZ/1g\n{"classify_A":"inside"}\n["classify_B","error","conflict","x"]')),
            'wire_rejected': self.ev(envelope('```\n' + self.GOOD + '\n```')),
            'process_failure': self.ev(b'boom', exit=1),
            'deadline': self.ev(b'', timed_out=True, exit=None),
        }
        for outcome, ev in cases.items():
            self.assertEqual(ev['outcome'], outcome)
            self.assertFalse(ev['passed'])
        late = self.ev(envelope(self.GOOD), ms=301000)
        self.assertEqual((late['outcome'], late['on_time'], late['passed']), ('correct', False, False))
        other = self.ev(envelope(self.GOOD, model='claude-haiku-4-5'))
        self.assertEqual((other['route'], other['passed']), ('mismatch', False))
        blind = self.ev(envelope(self.GOOD, usage=False))
        self.assertEqual((blind['usage']['complete'], blind['passed']), (False, False))
        unknown = self.ev(envelope(self.GOOD, thinking=None))
        self.assertTrue(unknown['passed'])
        self.assertIsNone(unknown['usage']['thinking'])  # thinking unknown is reported, never zero


class RunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name)
        status = A.freeze()
        self.record = dict(status, qualification=json.loads(A.FREEZE_FILE.read_text(encoding='utf-8'))
                           ['qualification'])

    def run_q(self, name, plan):
        clock = [1000.0]
        runner = A.qual_fixture_runner(plan, clock)
        return A.run_qualification(self.out / name, self.record['digest'], runner, clock=lambda: clock[0],
                                   log=lambda *_: None, record=self.record), runner

    def test_the_first_failure_ends_the_attempt_and_nothing_resumes_it(self):
        result, runner = self.run_q('w', {2: 'wrong'})
        self.assertEqual(result['launched'], 2)
        self.assertTrue(result['stopped'].startswith('terminal halt'))
        again, runner2 = self.run_q('w', {})
        self.assertEqual((again['launched'], len(runner2.calls)), (0, 0))
        analysis = A.analyze_qualification(self.out / 'w')
        self.assertEqual({k: v['verdict'] for k, v in analysis['cells'].items()}, {'size4': 'fail', 'size1': 'untested'})
        self.assertFalse(analysis['pass'])

    def test_a_changed_request_is_never_sent(self):
        record = copy.deepcopy(self.record)
        record['qualification']['slots'][0]['prompt_sha256'] = '0' * 64
        clock = [0.0]
        runner = A.qual_fixture_runner({}, clock)
        result = A.run_qualification(self.out / 'c', record['digest'], runner, clock=lambda: clock[0],
                                     log=lambda *_: None, record=record)
        self.assertEqual((result['launched'], len(runner.calls)), (0, 0))
        self.assertIn('differs from the frozen bytes', result['stopped'])

    def test_a_wrong_digest_or_a_broken_freeze_launches_nothing(self):
        with self.assertRaises(A.AdoptError):
            A.run_qualification(self.out / 'd', '0' * 64, A.qual_fixture_runner({}, [0.0]), record=self.record)
        with self.assertRaises(A.AdoptError):
            A.run_qualification(self.out / 'd', self.record['digest'], A.qual_fixture_runner({}, [0.0]),
                                record=dict(self.record, frozen=False))

    def test_tampered_evidence_makes_the_verdict_incomplete(self):
        self.run_q('t', {})
        analysis = A.analyze_qualification(self.out / 't')
        self.assertTrue(analysis['pass'])
        path = next((self.out / 't' / 'calls').glob('05-*')) / 'envelope.json'
        path.write_bytes(path.read_bytes().replace(b'outside', b'inside', 1))
        analysis = A.analyze_qualification(self.out / 't')
        self.assertFalse(analysis['pass'])
        self.assertTrue(analysis['problems'])


class VerdictAndGuardTests(unittest.TestCase):
    def suite_report(self, verdict='accepted', ok=True):
        rows = {}
        for name, n in (('clean', 4), ('repeat', 0), ('interrupt', 4), ('stale', 4), ('bump', 0)):
            first = [{'stage': 0, 'job': 'extract_A', 'verdict': 'accepted'}]
            first += [{'stage': 2, 'job': f'classify_{x}', 'verdict': 'accepted'} for x in 'ABCD'[:n]]
            rows[name] = {'recovery': {'first_attempt': first if n else []}}
        rows['stale']['recovery']['first_attempt'][3]['verdict'] = verdict
        return {'pass': ok, 'scenarios': rows}

    def cells(self, a='pass', b='pass'):
        return {'cells': {'size4': {'verdict': a}, 'size1': {'verdict': b}}}

    def test_adoption_needs_both_cells_the_suite_and_every_first_attempt(self):
        self.assertTrue(A.adoption_verdict(self.cells(), self.suite_report())['adopted'])
        self.assertFalse(A.adoption_verdict(self.cells('fail'), self.suite_report())['adopted'])
        self.assertFalse(A.adoption_verdict(self.cells(b='untested'), self.suite_report())['adopted'])
        self.assertFalse(A.adoption_verdict(self.cells(), self.suite_report(ok=False))['adopted'])
        # A suite that passed through recovery still fails adoption when a classification was wrong first.
        self.assertFalse(A.adoption_verdict(self.cells(), self.suite_report('check_rejected'))['adopted'])
        self.assertFalse(A.adoption_verdict(self.cells(), None)['adopted'])

    def test_paid_commands_need_the_confirmation(self):
        with patch.dict(os.environ, {}, clear=False), patch('sys.stderr'), patch('sys.stdout'):
            os.environ.pop(A.LIVE_ENV, None)
            self.assertEqual(A.main(['qualify', '--expect', 'x']), 2)
            self.assertEqual(A.main(['suite', '--workspace', 'ws']), 2)
            self.assertEqual(A.main(['run-flow', '--workspace', 'ws', '--kind', 'live', '--prefix', 'p',
                                     '--scenario', 'clean']), 2)

    def test_the_suite_waits_for_a_passed_qualification(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn('qualification', A.suite_refusal(Path(tmp) / 'ws', Path(tmp) / 'none'))
            with patch.object(A, 'analyze_qualification', return_value={'digest': A.freeze_status()['digest'],
                                                                           'pass': True}):
                self.assertIsNone(A.suite_refusal(Path(tmp) / 'ws'))
                (Path(tmp) / 'ws' / 'flows' / 'x').mkdir(parents=True)
                self.assertIn('not fresh', A.suite_refusal(Path(tmp) / 'ws'))
            with patch.object(A, 'analyze_qualification', return_value={'digest': 'other', 'pass': True}):
                self.assertIsNotNone(A.suite_refusal(Path(tmp) / 'ws2'))

    def test_the_suite_uses_its_own_allocation_and_identity(self):
        self.assertEqual(G2.allocation(), {'max_tokens': 64000, 'max_launches': 24, 'max_launches_per_flow': 10,
                                           'reserve_per_launch': 5000, 'estimate_tokens': 30000})
        self.assertEqual(A.qual()['caps'], {'max_tokens': 120000, 'max_launches': 36, 'reserve_tokens': 5000,
                                            'call_seconds': 300, 'overall_seconds': 14400})
        self.assertEqual(G2.config()['identity']['prefix'], 'ad1')
        self.assertIs(A.S.W, W2)
        self.assertEqual(A.S.ENTRY.name, 'adopt.py')
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(A.S.settings(Path(tmp), 'fixture', 'ns', quota=None).budget, G2.allocation())


class PredicateTwoRefTests(unittest.TestCase):
    def test_expected_inputs_are_record_and_interval_for_v2_classify_only(self):
        self.assertEqual(G2.expected_text('clean', 2, 'classify_A'), [A_REV1, ['12.48 mm', '12.52 mm']])
        self.assertEqual(G2.expected_text('stale', 4, 'classify_A'), [A_REV2, ['12.53 mm', '12.57 mm']])
        self.assertEqual(G2.expected_text('stale', 4, 'classify_D'), [D_REC, 'unknown'])
        self.assertEqual(G2.expected_text('clean', 0, 'extract_A'), A_REV1)
        self.assertEqual(G1.expected_text('clean', 2, 'classify_A'), A_REV1)

    def test_the_fixture_oracle_answers_v2_from_the_interval_and_the_goal(self):
        op = W2.load('workflow.json')['model_ops']['model.classify']['instruction']
        goal = A.goal_text(2)
        self.assertEqual(FA.answer(op, None, {}, [A_REV1, ['10.00 mm', '10.08 mm']], goal), 'inside')
        self.assertEqual(FA.answer(op, None, {}, [A_REV1, ['9.99 mm', '10.01 mm']], goal), 'outside')
        self.assertEqual(FA.answer(op, None, {}, [D_REC, 'unknown'], goal), 'unknown')
        self.assertEqual(FA.answer(op, None, {'stale_classify_A': True}, [A_REV2, ['12.53 mm', '12.57 mm']],
                                   A.spec()['goal']), 'inside')


class DryGateTests(unittest.TestCase):
    def test_the_zero_token_adoption_dry_gate_passes_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = os.environ.get('OZ_FIXTURE_DIR')
            try:
                report = A.dry(Path(tmp) / 'ad')
            finally:
                if saved is None:
                    os.environ.pop('OZ_FIXTURE_DIR', None)
                else:
                    os.environ['OZ_FIXTURE_DIR'] = saved
        self.assertTrue(report['freeze']['frozen'], report['freeze']['problems'][:3])
        self.assertTrue(all(v['pass'] for v in report['qualification_dry'].values()), report['qualification_dry'])
        self.assertTrue(report['suite']['pass'], report['suite'])
        self.assertEqual(report['suite']['totals']['launches'], 11)
        self.assertEqual({k: v['packets'] for k, v in report['suite']['scenarios'].items()},
                         {'clean': [4, 4, 4], 'repeat': [], 'interrupt': [4, 4, 4], 'stale': [4, 4, 1, 1, 4],
                          'bump': []})
        self.assertTrue(all(v['pass'] for v in report['fixtures'].values()), report['fixtures'])
        self.assertTrue(report['pass'])


if __name__ == '__main__':
    unittest.main()
