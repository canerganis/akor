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
from oz_flow import Flow, _stage_request, admit, flow_dir, flow_usage, run_flow  # noqa: E402
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
            for key in ('response_check',):
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
            self.assertEqual(report['totals']['launches'], 11)

    def test_the_frozen_contract_matches_its_digests(self):
        self.assertEqual(S.freeze()['problems'], [])


if __name__ == '__main__':
    unittest.main()
