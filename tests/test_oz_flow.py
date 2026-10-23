"""Step 4 focused tests: adapter accounting precondition, envelope retention, graph admission, freshness, memo, quota,
route identity, packet sizes, deadlines, accounting coverage, hard kills, and the zero-token dry gate end to end.
Every model call here goes to the oracle fixture adapter (bench/step4/fixture_adapter.py); nothing is paid."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'bench' / 'step4'))
sys.path.insert(0, str(ROOT))

from oz import Error  # noqa: E402
from oz_accept import Check, Unavailable  # noqa: E402
from oz_do import do  # noqa: E402
from oz_memo import MemoStore  # noqa: E402
from oz_flow import Flow, _stage_request, admit, flow_dir, flow_usage, run_flow  # noqa: E402
import evaluator as E  # noqa: E402
import fixture_adapter as FA  # noqa: E402
import oz_fault  # noqa: E402
from oz_quota import Quota  # noqa: E402
from oz_runner import read_capture  # noqa: E402
from oz_runtime import Inbox  # noqa: E402
import step4 as S  # noqa: E402
import workflow as W  # noqa: E402

spec = importlib.util.spec_from_file_location('claude_cli_adapter', ROOT / 'examples' / 'claude_cli_adapter.py')
CCA = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CCA)

FULL = {'inputTokens': 10, 'outputTokens': 5, 'cacheReadInputTokens': 100, 'cacheCreationInputTokens': 20}
LAST_TURN = {'input_tokens': 1, 'output_tokens': 1, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}


class AdapterAccountingTests(unittest.TestCase):
    """Precondition: unknown usage (never last-turn usage) when modelUsage is absent or empty."""

    def test_absent_empty_or_incomplete_model_usage_is_unknown(self):
        for envelope in ({'result': 'x', 'usage': LAST_TURN},
                         {'result': 'x', 'usage': LAST_TURN, 'modelUsage': {}},
                         {'result': 'x', 'usage': LAST_TURN, 'modelUsage': None},
                         {'result': 'x', 'usage': LAST_TURN,
                          'modelUsage': {'m': {k: v for k, v in FULL.items() if k != 'cacheReadInputTokens'}}},
                         {'result': 'x', 'modelUsage': {'m': dict(FULL, outputTokens=-1)}}):
            self.assertIsNone(CCA.usage_from_envelope(envelope))
            self.assertEqual(CCA.reduce(envelope), {'reply': 'x'})

    def test_model_usage_sums_every_model_once(self):
        envelope = {'result': 'x', 'usage': LAST_TURN, 'modelUsage': {'a': FULL, 'b': FULL}}
        self.assertEqual(CCA.reduce(envelope)['usage'], {'input_tokens': 260, 'cached_input_tokens': 200,
                                                         'cache_creation_input_tokens': 40, 'output_tokens': 10})

    def test_main_reports_unknown_usage_and_keeps_the_raw_envelope(self):
        raw = json.dumps({'result': 'OZ/1g', 'usage': LAST_TURN})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'r.envelope'
            out = io.StringIO()
            proc = subprocess.CompletedProcess([], 0, stdout=raw, stderr='')
            with patch.object(CCA.subprocess, 'run', return_value=proc) as run, \
                    patch.object(CCA.shutil, 'which', return_value='claude'), \
                    patch.dict(os.environ, {'OZ_ENVELOPE_PATH': str(path)}), \
                    patch('sys.stdin', io.StringIO(json.dumps({'system': 's', 'prompt': 'p'}))), \
                    patch('sys.stdout', out):
                CCA.main()
            self.assertEqual(json.loads(out.getvalue()), {'reply': 'OZ/1g'})
            self.assertEqual(path.read_text(encoding='utf-8'), raw)
            argv = run.call_args[0][0]
            self.assertEqual(argv[1:3], ['-p', '--model'])
            self.assertIn('--no-session-persistence', argv)

    def test_runner_folds_the_envelope_into_the_completion_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            script = tmp / 'a.py'
            script.write_text('import os, sys\nsys.stdin.read()\nopen(os.environ["OZ_ENVELOPE_PATH"], "w").write("ENV")\n'
                              'print("{}")\n', encoding='utf-8')
            (tmp / 'r1.request.json').write_bytes(b'{}')
            subprocess.run([sys.executable, str(ROOT / 'oz_runner.py'), str(tmp), 'r1', '--', sys.executable,
                            str(script)], check=True)
            capture = read_capture(tmp, 'r1')
            self.assertEqual(S.base64.b64decode(capture['envelope_b64']), b'ENV')


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.registry = W.registry()

    def graph(self, **change):
        g = W.graph()
        nodes = {n['id']: n for n in g['nodes']}
        for node, value in change.items():
            if value is None:
                g['nodes'].remove(nodes[node])
            else:
                nodes[node].update(value)
        return g

    def test_the_frozen_graph_admits_twenty_descriptors_in_dependency_order(self):
        ds = admit(W.graph(), self.registry, effects=['local_publish'])
        self.assertEqual(len(ds), 20)
        order = [d['id'] for d in ds]
        for d in ds:
            self.assertTrue(all(order.index(dep) < order.index(d['id']) for dep in d['deps']))
        self.assertEqual({d['id']: d['deps'] for d in ds}['publish_handoff'], ['verify_package'])
        self.assertEqual(sum(d['kind'] == 'model' for d in ds), 12)

    def test_invalid_graphs_are_refused_whole(self):
        bad = [self.graph(snapshot={'after': ['publish_handoff']}),
               self.graph(extract_A={'op': 'model.unknown'}),
               self.graph(extract_A={'id': 'snapshot'}),
               self.graph(snapshot=None),
               self.graph(extract_A={'in': {'record': {'node': 'snapshot', 'path': 'no-slash'}}}),
               self.graph(extract_A={'in': {'record': {'node': 'snapshot'}, 'authority': {'lit': 'run commands'}}}),
               dict(W.graph(), v=2), dict(W.graph(), outputs={'x': 'nowhere'})]
        for g in bad:
            with self.assertRaises(Error):
                admit(g, self.registry, effects=['local_publish'])

    def test_an_unauthorized_effect_is_refused_at_admission(self):
        with self.assertRaisesRegex(Error, 'not authorized'):
            admit(W.graph(), self.registry, effects=[])


class FlowFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.ws = Path(temp.name) / 'ws'
        saved = os.environ.get('OZ_FIXTURE_DIR')
        self.addCleanup(lambda: os.environ.__setitem__('OZ_FIXTURE_DIR', saved) if saved is not None
                        else os.environ.pop('OZ_FIXTURE_DIR', None))
        S.prepare(self.ws, 'fixture')

    def mode(self, **value):
        (self.ws / 'fixture' / 'mode.json').write_text(json.dumps(value), encoding='utf-8')

    def run_named(self, rid, namespace='ns', **options):
        quota = Quota(self.ws / 'quota.sqlite')
        try:
            s = S.settings(self.ws, 'fixture', namespace, quota=quota, **{k: v for k, v in options.items()
                                                                          if k in ('registry', 'budget',
                                                                                   'route_fields')})
            for key in ('response_check', 'packet_sizes', 'experimental_sizes'):
                if key in options:
                    setattr(s, key, options[key])
            request = S.flow_request('t', 'x', request_id=rid)
            request.update(options.get('request', {}))
            return run_flow(request, s, plan_only=options.get('plan_only', False))
        finally:
            quota.close()


class FlowTests(FlowFixture):
    def test_commit_is_conditional_on_the_whole_read_set(self):
        self.assertEqual(self.run_named('a1')['status'], 'delivered')
        f = Flow(flow_dir(self.ws, 'a1') / 'flow.sqlite')
        try:
            snap = f.current()['snapshot']
            f.bump_source('B', W.source_bytes('B'), reason='test')
            self.assertNotIn('snapshot', f.current())
            self.assertNotIn('publish_handoff', f.current())
            why = f.commit('snapshot', 1, snap['value'], {}, snap['cites'], {})
            self.assertIn('stale source revision: B', why)
            self.assertEqual(len(f.deliveries()), 1)  # history stays
        finally:
            f.close()

    def test_deferred_binding_failure_blocks_before_any_launch(self):
        graph = W.graph()
        next(n for n in graph['nodes'] if n['id'] == 'extract_A')['in']['record']['path'] = '/records/Z/text'
        result = self.run_named('b1', request={'graph': graph})
        self.assertEqual(result['blocker']['reason'], 'binding_failed')
        self.assertEqual(result['launches'], 0)

    def test_unexpected_model_in_the_envelope_blocks_acceptance(self):
        self.mode(model='claude-haiku-5-5')
        result = self.run_named('m1')
        self.assertEqual(result['status'], 'incomplete')
        jobs = result['blocker']['jobs']
        self.assertTrue(all('unexpected model' in j['last_error'] for j in jobs.values()))
        self.assertEqual(result['launches'], 2)  # two attempts of the extract stage, nothing accepted

    def test_missing_model_identity_blocks_and_usage_stays_unknown(self):
        self.mode(no_model_usage=True)
        result = self.run_named('u1')
        self.assertIn('model identity missing', json.dumps(result['blocker']))
        self.assertEqual(result['accounting']['coverage'], 'incomplete')
        self.assertEqual(result['accounting']['calls_without_usage'], 2)

    def test_incomplete_accounting_withholds_exact_cost_but_not_correctness(self):
        self.mode(no_model_usage=True)
        result = self.run_named('u2', response_check=None)
        self.assertEqual(result['status'], 'delivered')
        self.assertEqual(result['accounting'], {'tokens_known': 0, 'calls_without_usage': 3,
                                                'coverage': 'incomplete'})

    def test_three_remaining_jobs_go_as_three_singletons_never_size_three(self):
        op = W.registry()['model.extract']
        texts = {f'extract_{n}': W.source_bytes(n).decode('utf-8') for n in 'ABC'}
        req = _stage_request('p1', op, list(texts), texts, dict.fromkeys(texts, 1), 600, 300, 'fixture-oracle-1',
                             100000)
        fields, _ = S.route('fixture')
        result = do(req, workspace=self.ws, adapter=S.adapter_file(self.ws, 'fixture'), route=fields,
                    registry=W.CHECKS, packet_sizes=(4, 1), experimental_sizes=(4,))
        self.assertEqual([c['jobs'] for c in result['calls']], [1, 1, 1])
        self.assertEqual(result['counts'], {'accepted': 3})

    def test_deadline_admission_stops_before_launch(self):
        result = self.run_named('d1', request={'deadline_seconds': 100})
        self.assertEqual(result['blocker']['jobs']['extract_A']['reason'], 'deadline_admission')
        self.assertEqual(result['launches'], 0)

    def test_launch_cap_is_enforced_from_durable_journals(self):
        result = self.run_named('c1', budget={'max_launches': 2, 'reserve_per_launch': 5000})
        self.assertEqual(result['launches'], 2)
        self.assertEqual(result['blocker']['jobs']['classify_A']['reason'], 'launch_cap')

    def test_caps_count_launches_made_inside_the_running_stage(self):
        # Four singleton calls happen inside one do(); the stage event is written only after it returns.
        budget = {'max_launches_per_flow': 2, 'max_launches': 2, 'reserve_per_launch': 0}
        result = self.run_named('c2', budget=budget, packet_sizes=(1,), experimental_sizes=(1,))
        self.assertEqual(result['launches'], 2)
        self.assertEqual(len((self.ws / 'fixture' / 'invocations.jsonl').read_text().splitlines()), 2)
        reasons = {j['reason'] for j in result['blocker']['jobs'].values()}
        self.assertTrue(reasons & {'launch_cap', 'flow_launch_cap'}, reasons)

    def test_workspace_cap_counts_in_stage_launches_of_another_flow(self):
        budget = {'max_launches': 3, 'reserve_per_launch': 0}
        self.run_named('c3', budget=budget, packet_sizes=(1,), experimental_sizes=(1,))
        second = self.run_named('c4', budget=budget, packet_sizes=(1,), experimental_sizes=(1,))
        self.assertEqual(flow_usage(self.ws, 'c3')['launches'] + flow_usage(self.ws, 'c4')['launches'], 3)
        self.assertEqual(second['launches'], 0)

    def test_token_cap_counts_tokens_spent_inside_the_running_stage(self):
        result = self.run_named('c5', budget={'max_tokens': 1, 'reserve_per_launch': 0}, packet_sizes=(1,),
                                experimental_sizes=(1,))
        self.assertEqual(result['launches'], 1)
        self.assertEqual({j['reason'] for j in result['blocker']['jobs'].values()}, {'token_cap'})

    def test_a_stage_killed_mid_call_still_counts_from_its_journal(self):
        self.assertEqual(self.run_named('c6', budget={}, packet_sizes=(1,), experimental_sizes=(1,))['launches'], 12)
        f = Flow(flow_dir(self.ws, 'c6') / 'flow.sqlite')
        try:
            f.db.execute("DELETE FROM events WHERE event='stage'")  # what a stage killed inside do() leaves behind
        finally:
            f.close()
        self.assertEqual(flow_usage(self.ws, 'c6')['launches'], 12)


class PublishRaceTests(FlowFixture):
    def bump_a(self, rid, fired):
        f = Flow(flow_dir(self.ws, rid) / 'flow.sqlite')
        try:
            fired.append(f.bump_source('A', (W.FROZEN / 'sources/A.rev2.txt').read_bytes(), reason='race'))
        finally:
            f.close()

    def check_recovered(self, rid, result):
        self.assertEqual(result['status'], 'delivered', result['blocker'])
        target = result['targets']['inspection_handoff']
        self.assertEqual(target['cites']['A'], 2)
        self.assertTrue(target['destination'].endswith('-g2'), target['destination'])
        self.assertEqual(E.evaluate_package(self.ws / target['destination'], 'rev2',
                                            {'A': 2, 'B': 1, 'C': 1, 'D': 1}), [])
        f = Flow(flow_dir(self.ws, rid) / 'flow.sqlite')
        try:
            states = {e['intent']: e['state'] for e in f.effects()}
            deliveries = f.deliveries()
        finally:
            f.close()
        self.assertEqual(list(states.values()), ['superseded', 'delivered'], states)
        self.assertEqual(len(deliveries), 1)
        self.assertTrue(deliveries[0]['intent'].endswith(':g2'))
        # The stale files are not left at a delivery destination.
        self.assertFalse((self.ws / 'deliveries' / rid / 'publish_handoff-g1').exists())

    def test_a_revision_between_export_and_commit_recomputes_at_a_new_generation(self):
        fired = []
        remove = oz_fault.on('flow.publish.after_manifest', lambda _: fired or self.bump_a('pr1', fired))
        try:
            result = self.run_named('pr1')
        finally:
            remove()
        self.assertEqual(fired, [2])
        self.check_recovered('pr1', result)

    def test_a_crash_after_export_then_a_revision_does_not_block_the_resume(self):
        def crash(_):
            if not fired:
                self.bump_a('pr2', fired)
                raise RuntimeError('simulated crash after the manifest')
        fired = []
        remove = oz_fault.on('flow.publish.after_manifest', crash)
        try:
            with self.assertRaises(RuntimeError):
                self.run_named('pr2')
        finally:
            remove()
        self.check_recovered('pr2', self.run_named('pr2'))

    def test_a_nondeterministic_recompute_with_unchanged_sources_still_blocks(self):
        def crash(_):
            raise RuntimeError('simulated crash after the manifest')
        remove = oz_fault.on('flow.publish.after_manifest', crash)
        try:
            with self.assertRaises(RuntimeError):
                self.run_named('pr3')
        finally:
            remove()
        f = Flow(flow_dir(self.ws, 'pr3') / 'flow.sqlite')
        try:
            intent = f.effects()[0]
            files = json.loads(json.dumps(intent['files']))
            files['handoff.md']['sha256'] = '0' * 64
            f.db.execute('UPDATE effects SET files=? WHERE intent=?', (json.dumps(files), intent['intent']))
        finally:
            f.close()
        result = self.run_named('pr3')
        self.assertEqual(result['blocker']['reason'], 'effect_blocked')


class Kill(BaseException):
    """In-process stand-in for a hard stop of the coordinator at a fault boundary (nothing settles after it)."""


class StageIdentityTests(FlowFixture):
    """One stage request per logical job generation (foundation clauses 1 to 3; the O1 G2 finding of 2026-10-23): a
    resumed or re-invoked flow resubmits the stage its pending jobs were first submitted in, so their attempt
    allowance, terminal failures and awaiting candidates are never reset by a new stage request."""

    def stage_runs(self, rid, op):
        return sorted(p.name for p in (self.ws / 'do').glob(f'{rid}-{op}-*'))

    def dispatched(self, rid, op):
        out = []
        for name in self.stage_runs(rid, op):
            box = Inbox(self.ws / 'do' / name / 'inbox.sqlite')
            try:
                out += [[(m['id'], m['attempt']) for m in d['members']] for d in box.dispatches()]
            finally:
                box.close()
        return out

    def kill_after_first_capture(self):
        fired = []

        def hook(_name):
            if not fired:
                fired.append(1)
                raise Kill()
        self.addCleanup(oz_fault.on('worker.after_capture', hook))

    def all_four(self, op, attempt):
        return [(f'{op}_{n}', attempt) for n in 'ABCD']

    def test_a_killed_call_with_rejected_members_resumes_them_at_attempt_two_in_the_same_stage(self):
        self.mode(wrong_first=['extract_B', 'extract_C'])
        self.kill_after_first_capture()
        with self.assertRaises(Kill):
            self.run_named('r1')
        result = self.run_named('r1')
        self.assertEqual(result['status'], 'delivered', result['blocker'])
        self.assertEqual(len(self.stage_runs('r1', 'extract')), 1)
        self.assertEqual(self.dispatched('r1', 'extract'),
                         [self.all_four('extract', 1), [('extract_B', 2)], [('extract_C', 2)]])
        self.assertEqual((result['launches'], S.fixture_invocations(self.ws, 'r1')), (5, 5))
        self.assertTrue(S.ledger_audit(self.ws, 'r1')['ok'])

    def test_a_killed_wire_invalid_call_is_resent_whole_at_attempt_two(self):
        self.mode(wire_reject_first=['extract_C'])
        self.kill_after_first_capture()
        with self.assertRaises(Kill):
            self.run_named('r2')
        result = self.run_named('r2')
        self.assertEqual(result['status'], 'delivered', result['blocker'])
        self.assertEqual(self.dispatched('r2', 'extract'), [self.all_four('extract', 1), self.all_four('extract', 2)])
        self.assertEqual((result['launches'], S.fixture_invocations(self.ws, 'r2')), (4, 4))

    def test_invoking_the_flow_again_never_resends_an_exhausted_job(self):
        self.mode(wrong_always=['classify_B'])
        first = self.run_named('r3')
        self.assertEqual(first['status'], 'incomplete')
        self.assertEqual(first['blocker']['jobs']['classify_B']['reason'], 'attempts_exhausted')
        for _ in range(2):
            again = self.run_named('r3')
            self.assertEqual(again['blocker']['jobs']['classify_B']['reason'], 'attempts_exhausted')
        self.assertEqual((again['launches'], S.fixture_invocations(self.ws, 'r3')), (4, 4))
        self.assertEqual(len(self.stage_runs('r3', 'classify')), 1)
        self.assertEqual(self.dispatched('r3', 'classify'), [self.all_four('classify', 1), [('classify_B', 2)]])

    def test_invoking_the_flow_again_during_a_verifier_outage_regenerates_nothing(self):
        real = W.CHECKS['mat_fields']

        def run(value, spec, inputs):
            if '12.47' in inputs.texts[0]:
                raise Unavailable('verifier down for B')
            return real.run(value, spec, inputs)
        checks = dict(W.CHECKS, mat_fields=Check('mat_fields', 1, True, real.params, run))
        with patch.object(W, 'CHECKS', checks):
            first = self.run_named('r4')
            again = self.run_named('r4')
        self.assertEqual(first['blocker']['jobs']['extract_B']['status'], 'unresolved')
        self.assertEqual((again['launches'], S.fixture_invocations(self.ws, 'r4')), (1, 1))
        recovered = self.run_named('r4')
        self.assertEqual(recovered['status'], 'delivered', recovered['blocker'])
        self.assertEqual(self.dispatched('r4', 'extract'), [self.all_four('extract', 1)])
        self.assertEqual(recovered['launches'], 3)

    def test_the_stage_request_identity_does_not_depend_on_the_remaining_deadline(self):
        op = W.registry()['model.extract']
        texts = {f'extract_{n}': W.source_bytes(n).decode('utf-8') for n in 'AB'}
        early = _stage_request('p', op, list(texts), texts, dict.fromkeys(texts, 1), 3000, 300, 'm', 100000)
        late = _stage_request('p', op, list(texts), texts, dict.fromkeys(texts, 1), 20, 300, 'm', 100000)
        self.assertEqual(early['request_id'], late['request_id'])
        self.assertEqual({k: v for k, v in early.items() if k != 'deadline_seconds'},
                         {k: v for k, v in late.items() if k != 'deadline_seconds'})

    def bump_at_second_commit(self, rid, data, fired):
        """Revise source A just before the first model commit (the snapshot is the first commit)."""
        seen = []

        def hook(_name):
            seen.append(1)
            if len(seen) == 2 and not fired:
                f = Flow(flow_dir(self.ws, rid) / 'flow.sqlite')
                try:
                    fired.append(f.bump_source('A', data, reason='test'))
                finally:
                    f.close()
        self.addCleanup(oz_fault.on('flow.before_commit', hook))

    def test_a_refused_model_commit_with_unchanged_inputs_is_readopted_without_a_call(self):
        fired = []
        self.bump_at_second_commit('e1', W.source_bytes('A'), fired)
        result = self.run_named('e1')
        self.assertEqual((fired, result['status']), ([2], 'delivered'))
        self.assertEqual(result['launches'], 3)
        self.assertEqual(self.dispatched('e1', 'extract'), [self.all_four('extract', 1)])

    def test_changed_inputs_at_the_same_generation_open_an_explicit_new_generation(self):
        fired = []
        self.bump_at_second_commit('e2', (W.FROZEN / 'sources/A.rev2.txt').read_bytes(), fired)
        result = self.run_named('e2')
        self.assertEqual((fired, result['status']), ([2], 'delivered'), result['blocker'])
        f = Flow(flow_dir(self.ws, 'e2') / 'flow.sqlite')
        try:
            regenerated = [e['details'] for e in f.events() if e['event'] == 'regenerated'
                           and e['details']['node'] == 'extract_A']
            current = f.current()
        finally:
            f.close()
        self.assertEqual([(r['generation'], r.get('reason')) for r in regenerated], [(2, 'inputs_changed')])
        self.assertEqual(current['extract_A']['generation'], 2)
        self.assertEqual([current[f'extract_{n}']['generation'] for n in 'BCD'], [1, 1, 1])
        self.assertEqual(self.dispatched('e2', 'extract'), [self.all_four('extract', 1), [('extract_A', 1)]])
        self.assertEqual(len(self.stage_runs('e2', 'extract')), 2)

    def test_a_model_commit_refused_again_with_the_same_value_blocks_instead_of_looping(self):
        real = Flow.commit
        calls = []

        def refuse(flow, node, *a, **k):
            if node.startswith('extract_'):
                calls.append(node)
                if len(calls) > 40:
                    raise AssertionError('the flow keeps retrying a refused commit')
                return 'stale source revision: test'
            return real(flow, node, *a, **k)
        with patch.object(Flow, 'commit', refuse):
            result = self.run_named('e3')
        self.assertEqual(result['blocker']['reason'], 'commit_refused')
        self.assertEqual(result['blocker']['node'], 'extract_A')
        self.assertEqual(result['launches'], 1)


class DirectSourceReadTests(FlowFixture):
    def test_a_source_read_directly_by_a_model_node_is_in_its_read_set(self):
        graph = {'v': 1, 'base': 0, 'nodes': [
            {'id': 'snapshot', 'op': 'host.snapshot', 'in': {'sources': {'lit': ['A', 'B', 'C', 'D']}}, 'after': []},
            {'id': 'm', 'op': 'model.extract', 'in': {'record': {'ref': 'A'}}, 'after': []}],
            'outputs': {'x': 'm'}}
        self.run_named('rc1', request={'graph': graph})
        f = Flow(flow_dir(self.ws, 'rc1') / 'flow.sqlite')
        try:
            self.assertEqual(f.latest()['m']['cites'], {'A': 1})
            self.assertIn('m', f.current())
            f.bump_source('A', (W.FROZEN / 'sources/A.rev2.txt').read_bytes(), reason='edit')
            self.assertNotIn('m', f.current())
        finally:
            f.close()
        self.run_named('rc1', request={'graph': graph})
        f = Flow(flow_dir(self.ws, 'rc1') / 'flow.sqlite')
        try:
            self.assertEqual(f.current()['m']['cites'], {'A': 2})
            self.assertIn('12.55 mm', f.current()['m']['value'])
        finally:
            f.close()


class EvaluatorTests(unittest.TestCase):
    REVS = {'A': 1, 'B': 1, 'C': 1, 'D': 1}

    def package(self, tmp, *, doc=None, md=None):
        doc = doc or json.loads(FA.baseline_reply(S.baseline_prompt('rev1')))
        md = md if md is not None else W.op_render_markdown({'rows': {'rows': doc['records']}}, None)
        raw = (json.dumps(doc, indent=1) + '\n').encode('utf-8')
        Path(tmp, 'handoff.json').write_bytes(raw)
        Path(tmp, 'handoff.md').write_text(md, encoding='utf-8', newline='')
        manifest = {'artifacts': {'handoff.json': S.hashlib.sha256(raw).hexdigest(),
                                  'handoff.md': S.hashlib.sha256(md.encode('utf-8')).hexdigest()}}
        Path(tmp, 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        return E.evaluate_package(tmp, 'rev1', self.REVS)

    def good_md(self):
        doc = json.loads(FA.baseline_reply(S.baseline_prompt('rev1')))
        return W.op_render_markdown({'rows': {'rows': doc['records']}}, None)

    def test_a_correct_package_has_no_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.package(tmp), [])

    def test_the_markdown_source_digest_must_equal_the_frozen_digest(self):
        md = self.good_md()
        digest = S.hashlib.sha256(W.source_bytes('A')).hexdigest()
        self.assertIn(digest, md)
        with tempfile.TemporaryDirectory() as tmp:
            errors = self.package(tmp, md=md.replace(digest, '0' * 64))
        self.assertTrue(any('Markdown source cell' in e for e in errors), errors)

    def test_duplicate_markdown_rows_for_a_record_are_rejected(self):
        md = self.good_md()
        row = next(line for line in md.splitlines() if line.startswith('| A |'))
        wrong = row.replace('0.02 mm', '0.99 mm')
        with tempfile.TemporaryDirectory() as tmp:
            # The wrong row comes first and the right one last: keeping the last row would pass.
            errors = self.package(tmp, md=md.replace(row, wrong + '\n' + row))
        self.assertTrue(any('duplicate' in e for e in errors), errors)

    def test_top_level_schema_workflow_evidence_and_keys_are_checked(self):
        good = json.loads(FA.baseline_reply(S.baseline_prompt('rev1')))
        self.assertEqual(E.evaluate_document(good, 'rev1', self.REVS), [])
        for key, value in (('schema', 'other/1'), ('workflow', 'other/v1'), ('evidence', 'Numerical status is fine.')):
            errors = E.evaluate_document(dict(good, **{key: value}), 'rev1', self.REVS)
            self.assertTrue(any(key in e for e in errors), (key, errors))
        for doc in (dict(good, extra=1), {k: v for k, v in good.items() if k != 'evidence'}):
            errors = E.evaluate_document(doc, 'rev1', self.REVS)
            self.assertTrue(any('top-level keys' in e for e in errors), errors)


class LiveGateTests(unittest.TestCase):
    ARGV = ['run-flow', '--workspace', 'ws', '--kind', 'live', '--prefix', 'p', '--scenario', 'clean']

    def run_main(self, *, confirm, frozen=True, version=None):
        version = version or S.spec()['route']['cli_version']
        env = {'STEP4_LIVE_CONFIRM': '1'} if confirm else {}
        stdout = io.StringIO()
        with patch.dict(os.environ, env), patch.object(S, 'cli_version', return_value=version),                 patch.object(S, 'freeze', return_value={'frozen': frozen, 'digest': 'x', 'problems': []}),                 patch.object(S, 'prepare') as prepare,                 patch.object(S, 'run_scenario_flow', return_value={'status': 'delivered', 'blocker': None,
                                                                    'launches': 0, 'targets': {}}) as run,                 patch('sys.stderr', io.StringIO()), patch('sys.stdout', stdout):
            if not confirm:
                os.environ.pop('STEP4_LIVE_CONFIRM', None)
            code = S.main(self.ARGV)
        return code, run.called, prepare.called

    def test_run_flow_live_needs_the_confirmation_the_freeze_and_the_cli_version(self):
        self.assertEqual(self.run_main(confirm=False), (2, False, False))
        self.assertEqual(self.run_main(confirm=True, frozen=False), (2, False, False))
        self.assertEqual(self.run_main(confirm=True, version='0.0.0'), (2, False, False))
        self.assertEqual(self.run_main(confirm=True), (0, True, True))

    def test_run_flow_fixture_is_not_gated(self):
        with patch.object(S, 'prepare'), patch.object(S, 'run_scenario_flow', return_value={
                'status': 'delivered', 'blocker': None, 'launches': 0, 'targets': {}}) as run,                 patch('sys.stdout', io.StringIO()):
            self.assertEqual(S.main(['run-flow', '--workspace', 'ws', '--kind', 'fixture', '--prefix', 'p',
                                     '--scenario', 'clean']), 0)
        self.assertTrue(run.called)


class PlanRouteTests(FlowFixture):
    def test_plan_only_computes_the_route_like_the_worker_when_no_adapter_is_pinned(self):
        op = W.registry()['model.extract']
        texts = {f'extract_{n}': W.source_bytes(n).decode('utf-8') for n in 'AB'}
        fields, model = S.route('fixture')
        route = {k: v for k, v in fields.items() if k != 'adapter'}  # the caller pins no adapter identity
        adapter = S.adapter_file(self.ws, 'fixture')
        store = MemoStore(self.ws / 'memo.sqlite')
        try:
            memo = {'store': store, 'namespace': 'plan-route', 'ops': [op.name]}
            first = _stage_request('pr', op, list(texts), texts, dict.fromkeys(texts, 1), 600, 300, model, 100000)
            real = do(first, workspace=self.ws, adapter=adapter, route=route, registry=W.CHECKS, memo=memo,
                      packet_sizes=(4, 1), experimental_sizes=(4,))
            self.assertEqual(real['counts'], {'accepted': 2})
            again = _stage_request('pr', op, list(texts), texts, dict.fromkeys(texts, 2), 600, 300, model, 100000)
            plan = do(again, workspace=self.ws, adapter=adapter, route=route, registry=W.CHECKS, memo=memo,
                      packet_sizes=(4, 1), plan_only=True)
            self.assertEqual({m['decision'] for m in plan['plan']['memo'].values()}, {'hit'}, plan['plan']['memo'])
            self.assertEqual(plan['plan']['misses'], 0)
            replay = do(again, workspace=self.ws, adapter=adapter, route=route, registry=W.CHECKS, memo=memo,
                        packet_sizes=(4, 1), experimental_sizes=(4,))
            for job, m in plan['plan']['memo'].items():
                self.assertEqual(replay['memo'][job]['compute_key'], m['compute_key'])
                self.assertEqual(replay['memo'][job]['decision'], 'hit')
        finally:
            store.close()

    def test_a_callable_adapter_is_named_by_its_own_name(self):
        op = W.registry()['model.extract']
        text = W.source_bytes('A').decode('utf-8')
        texts = {'extract_A': text}
        fields, model = S.route('fixture')
        route = {k: v for k, v in fields.items() if k != 'adapter'}

        def my_adapter(request):
            raise AssertionError('plan-only never calls')
        my_adapter.capabilities = None
        req = _stage_request('pc', op, ['extract_A'], texts, {'extract_A': 1}, 600, 300, model, 100000)
        store = MemoStore(self.ws / 'memo.sqlite')
        try:
            memo = {'store': store, 'namespace': 'plan-callable', 'ops': [op.name]}
            plan = do(req, workspace=self.ws, adapter=my_adapter, route=route, registry=W.CHECKS, memo=memo,
                      packet_sizes=(4, 1), plan_only=True)
            pinned = do(req, workspace=self.ws, adapter=my_adapter, route=dict(route, adapter='my_adapter'),
                        registry=W.CHECKS, memo=memo, packet_sizes=(4, 1), plan_only=True)
            self.assertEqual(plan['plan']['memo']['extract_A']['compute_key'],
                             pinned['plan']['memo']['extract_A']['compute_key'])
        finally:
            store.close()


class MemoTests(FlowFixture):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.run_named('base')['launches'], 3)

    def test_exact_repeat_is_twelve_hits_with_dispatch_identical_keys(self):
        result = self.run_named('rep')
        self.assertEqual((result['status'], result['launches']), ('delivered', 0))
        base, rep = Flow(flow_dir(self.ws, 'base') / 'flow.sqlite'), Flow(flow_dir(self.ws, 'rep') / 'flow.sqlite')
        try:
            a, b = base.current(), rep.current()
            model = [n for n in a if n.split('_')[0] in ('extract', 'bounds', 'classify')]
            self.assertEqual(len(model), 12)
            for n in model:
                self.assertEqual(a[n]['evidence']['compute_key'], b[n]['evidence']['compute_key'])
                self.assertTrue(b[n]['evidence']['receipt'].startswith('memo:'))
        finally:
            base.close()
            rep.close()

    def test_fixture_values_are_never_hits_for_another_route(self):
        fields, _ = S.route('fixture')
        plan = self.run_named('base', route_fields=dict(fields, adapter='live-adapter', cli_version='2.1.306'),
                              plan_only=True)
        self.assertEqual((plan['misses'], plan['launched']), (12, 0))

    def test_a_verifier_outage_holds_the_hit_and_launches_nothing(self):
        def unavailable(value, spec, inputs):
            raise Unavailable('verifier down')
        checks = dict(W.CHECKS, mat_bounds=Check('mat_bounds', 1, True, lambda s: None, unavailable))
        with patch.object(W, 'CHECKS', checks):
            result = self.run_named('out')
        self.assertEqual(result['blocker']['stage_blocker'], {'reason': 'memo_revalidation_pending', 'job': 'bounds_A'})
        self.assertEqual(result['launches'], 0)

    def test_a_failed_revalidation_is_a_miss_not_a_hit(self):
        strict = W.registry(extra_checks={'model.extract': [{'check': 'max_bytes', 'bytes': 8}]})
        result = self.run_named('fail', registry=strict, budget={'max_launches': 0, 'reserve_per_launch': 5000})
        self.assertEqual(result['launches'], 0)
        self.assertEqual(result['blocker']['jobs']['extract_A']['reason'], 'launch_cap')


class QuotaTests(unittest.TestCase):
    def test_slot_is_held_until_the_holders_dispatch_reconciles(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            q = Quota(tmp / 'q.sqlite')
            try:
                run = tmp / 'run'
                run.mkdir()
                self.assertEqual(q.acquire('g', run_dir=run, receipt='1')['status'], 'acquired')
                held = q.acquire('g', run_dir=run, receipt='2')
                self.assertEqual((held['status'], held['reason']), ('held', 'held_coordinator_alive'))
                box = Inbox(run / 'inbox.sqlite')
                box.db.execute("INSERT INTO channels VALUES ('b','{}')")
                box.db.execute("INSERT INTO dispatches(receipt,binding,lease,owner,epoch,created_at,deadline,reservation,"
                               "reservation_state,members,job_map,host_slots,system_sha256,packet,route,state) VALUES "
                               "('1','b','l','o',1,0,0,'{}','held','[]','[]','[]','','','{}','uncertain')")
                self.assertEqual(q.acquire('g', run_dir=run, receipt='2')['reason'], 'held_uncertain')
                box.db.execute("UPDATE dispatches SET state='captured' WHERE receipt='1'")
                box.close()
                self.assertEqual(q.acquire('g', run_dir=run, receipt='2')['status'], 'acquired')
                events = [e['event'] for e in q.events('g')]
                self.assertEqual(events, ['acquired', 'contention', 'contention', 'reclaimed', 'acquired'])
            finally:
                q.close()

    def test_a_dead_coordinator_without_a_journaled_dispatch_frees_its_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            q = Quota(Path(tmp) / 'q.sqlite')
            try:
                q.db.execute('INSERT INTO slots VALUES (?,?,?,?)', ('g', 't', json.dumps(
                    {'run_dir': tmp, 'receipt': '9', 'coordinator': {'pid': 999999, 'created': 1}}), 0))
                self.assertEqual(q.acquire('g', run_dir=tmp, receipt='1')['status'], 'acquired')
            finally:
                q.close()


class HardKillTests(FlowFixture):
    def test_external_terminate_during_a_call_then_resume_reuses_the_capture(self):
        self.mode(sleep=2)
        cmd = [sys.executable, str(ROOT / 'bench' / 'step4' / 'step4.py'), 'run-flow', '--workspace', str(self.ws),
               '--kind', 'fixture', '--prefix', 'k', '--scenario', 'clean']
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 60
        launched = None
        while time.time() < deadline and launched is None:
            for run in (self.ws / 'do').glob('k-clean-extract-*'):
                if (run / 'inbox.sqlite').exists():
                    box = Inbox(run / 'inbox.sqlite')
                    row = box.db.execute("SELECT receipt FROM dispatches WHERE state='launched'").fetchone()
                    box.close()
                    if row:
                        launched = (run, row[0])
            time.sleep(0.1)
        self.assertIsNotNone(launched)
        proc.kill()  # TerminateProcess on Windows: no cleanup runs in the coordinator
        proc.wait()
        done = launched[0] / 'captures' / f'{launched[1]}.done'
        while time.time() < deadline and not done.exists():
            time.sleep(0.1)  # the orphaned runner still publishes its completion
        self.assertTrue(done.exists())
        self.mode()
        resumed = subprocess.run(cmd, env=env, capture_output=True, text=True)
        self.assertEqual(resumed.returncode, 0, resumed.stderr[-500:])
        self.assertEqual(flow_usage(self.ws, 'k-clean')['launches'], 3)
        self.assertEqual(S.fixture_invocations(self.ws, 'k-clean'), 3)
        self.assertTrue(S.ledger_audit(self.ws, 'k-clean')['ok'])


class DryGateTests(unittest.TestCase):
    def test_the_zero_token_dry_gate_passes_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = os.environ.get('OZ_FIXTURE_DIR')
            try:
                report = S.suite(Path(tmp) / 'dry', 'fixture', 'g2')
            finally:
                if saved is None:
                    os.environ.pop('OZ_FIXTURE_DIR', None)
                else:
                    os.environ['OZ_FIXTURE_DIR'] = saved
            failing = {k: v for k, v in report['scenarios'].items() if not v['pass']}
            self.assertEqual(failing, {})
            self.assertTrue(all(c['pass'] for c in report['c5'].values()), report['c5'])
            self.assertTrue(all(c['caught'] for c in report['sabotage'].values()), report['sabotage'])
            self.assertTrue(report['pass'])
            self.assertEqual(report['pass'], report['g3b']['pass'])
            self.assertTrue(all(s['pass_g3b'] and s['g3b']['strict_pass'] and not s['recovered']
                                for s in report['scenarios'].values()))
            self.assertTrue(all(c['pass'] for c in report['recovery'].values()), report['recovery'])
            self.assertTrue(all(c['caught'] for c in report['g3b_sabotage'].values()), report['g3b_sabotage'])
            self.assertTrue(all(c['pass'] for c in report['feasibility'].values()), report['feasibility'])
            self.assertEqual(report['totals']['launches'], 11)

    def test_the_frozen_contract_matches_its_digests(self):
        self.assertEqual(S.freeze()['problems'], [])

    def stored_copy(self, tmp, edit):
        stored = json.loads(S.FREEZE_FILE.read_text(encoding='utf-8'))
        edit(stored)
        path = Path(tmp) / 'freeze.json'
        path.write_text(json.dumps(stored), encoding='utf-8')
        return path

    def test_freeze_verifies_that_the_stored_maps_hash_to_the_stored_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(S.freeze(path=self.stored_copy(tmp, lambda s: None))['frozen'])
            for edit in (lambda s: s.update(digest='f' * 64),
                         lambda s: s['code'].update({'oz_flow.py': 'f' * 64})):
                result = S.freeze(path=self.stored_copy(tmp, edit))
                self.assertFalse(result['frozen'])
                self.assertTrue(any('do not hash to the stored digest' in p for p in result['problems']), result)

    def test_the_g2_report_requires_the_freeze_to_hold(self):
        with tempfile.TemporaryDirectory() as tmp,                 patch.object(S, 'freeze', return_value={'frozen': False, 'digest': 'x', 'current_digest': 'y',
                                                         'problems': ['forced']}):
            report = S.suite(Path(tmp) / 'dry', 'fixture', 'g2', 'clean')
        self.assertFalse(report['pass'])
        self.assertFalse(report['freeze']['frozen'])


if __name__ == '__main__':
    unittest.main()
