"""O1 (G3c-O1, repair-handoff-20/v1) focused tests: the confined worker and its launcher, the AST policy, the frozen
records and tiers, the host operations, the gate predicate with independent verdicts, one scenario pair through the
real executor with the zero-token fixture adapter, and the live guards. Nothing here is paid."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
O1 = ROOT / 'bench' / 'o1'
# bench/step4 also has modules named workflow, evaluator and fixture_adapter; load the O1 ones under their names, then put back
# whatever another test module had registered, so neither side sees the other's module.
for p in (str(ROOT), str(O1 / 'evaluator'), str(O1)):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)
_SHARED = ('workflow', 'evaluator', 'fixture_adapter')
_SAVED = {name: sys.modules.pop(name) for name in _SHARED if name in sys.modules}

import build as B  # noqa: E402
import evaluator as E  # noqa: E402
import gate as GT  # noqa: E402
import heldout as H  # noqa: E402
import o1 as O  # noqa: E402
import o1_dry as D  # noqa: E402
import sandbox  # noqa: E402
import sandbox_worker as SW  # noqa: E402
import workflow as W  # noqa: E402
from oz_accept import Inputs, Unavailable, pin, run_checks  # noqa: E402
from oz_flow import HostError, Settings, admit  # noqa: E402

for _name in _SHARED:
    sys.modules.pop(_name, None)
sys.modules.update(_SAVED)

POLICY = W.policy()


def fn(ticket, rev, name, kind='fixture'):
    return D.fixture_source(ticket, rev, name, kind)


def payload(source, rows, name='parse_amount', params=('text',), probe=False):
    out = {'policy': POLICY, 'units': [{'id': 'core', 'kind': 'function', 'source': source, 'name': name,
                                        'params': list(params)}],
           'rows': [{'unit': 'core', 'fn': name, 'args': a} for a in rows]}
    if probe:
        out['probe'] = True
    return out


def inputs(record):
    return Inputs(({'op': '', 'refs': [json.dumps(record)]},))


class ConfinementTests(unittest.TestCase):
    def test_job_limits_read_back_as_frozen(self):
        job = sandbox.Job()
        try:
            self.assertEqual(job.limits(), {'flags': sandbox.LIMIT_FLAGS, 'cpu_100ns': 20_000_000, 'processes': 1,
                                            'memory': 256 * 1024 * 1024})
        finally:
            job.close()
        self.assertEqual(POLICY['limits'], {'process_memory_bytes': 268435456, 'active_processes': 1,
                                            'cpu_seconds': 2.0, 'wall_seconds': 5.0})

    def test_each_run_reports_a_fresh_temporary_cwd_two_variables_and_the_launcher_flags(self):
        res = sandbox.run(payload('def parse_amount(text):\n    return len(text)\n', [['abc']]), 0)
        self.assertEqual(res['status'], 'ok')
        self.assertEqual(res['rows'], [{'r': '3'}])
        meta = res['meta']
        self.assertEqual(sorted(meta['env']), ['PYTHONHASHSEED', 'SYSTEMROOT'])
        self.assertNotIn(ROOT.resolve(), Path(meta['cwd']).resolve().parents)
        self.assertTrue(Path(meta['cwd']).name.startswith('o1-sbx-'))
        self.assertFalse(Path(meta['cwd']).exists())
        self.assertEqual((meta['flags']['no_site'], meta['flags']['safe_path'], meta['flags']['ignore_environment'],
                          meta['flags']['isolated']), (1, True, 0, 0))

    def test_the_launcher_honors_hash_seeds_0_and_1(self):
        empty = {'policy': POLICY, 'units': [], 'rows': []}
        h0, h0b, h1 = (sandbox.run(empty, s)['meta']['hash'] for s in (0, 0, 1))
        self.assertEqual(h0, h0b)
        self.assertNotEqual(h0, h1)

    def test_a_cpu_loop_is_stopped_and_is_a_candidate_resource_failure(self):
        res = sandbox.run(payload('def parse_amount(text):\n    while True:\n        pass\n', [['1']]), 0)
        self.assertEqual(res['status'], 'resource')
        self.assertGreaterEqual(res['cpu_seconds'], 1.9)

    def test_a_huge_allocation_and_a_recursion_bomb_are_contained_rows(self):
        src = ('def parse_amount(text):\n    def f(n):\n        return f(n + 1)\n    if text == "r":\n'
               '        return f(0)\n    return [0] * (10 ** 10)\n')
        res = sandbox.run(payload(src, [['r'], ['m']]), 0)
        self.assertEqual(res['status'], 'ok')
        self.assertEqual([r.get('x') for r in res['rows']], ['RecursionError', 'MemoryError'])

    def test_the_worker_refuses_policy_violations_before_running_anything(self):
        res = sandbox.run(payload('def parse_amount(text):\n    import os\n    return os.getcwd()\n', [['1']]), 0)
        self.assertEqual(res['status'], 'refused')
        self.assertIn('Import', json.dumps(res['reasons']))

    def test_the_audit_hooks_refuse_import_open_os_socket_and_subprocess_once_armed(self):
        for name, row in D.audit_hooks().items():
            self.assertTrue(row['pass'], (name, row))

    def test_a_second_process_cannot_start_inside_the_job(self):
        result = D.process_confinement()
        self.assertTrue(result['checks']['second_process_refused'], result['child'])

    def test_a_worker_that_cannot_start_is_unavailable_and_never_a_verdict(self):
        t = W.ticket('A', 1)
        with patch.object(sandbox, 'interpreter', side_effect=sandbox.SandboxUnavailable('no interpreter')):
            with self.assertRaises(Unavailable):
                W.check_tier_a(fn('A', 1, 'parse_amount'), {'op': 'core'}, inputs(t['core_record']))
            verdicts = run_checks(json.dumps(fn('A', 1, 'parse_amount')), inputs(t['core_record']),
                                  pin(W.spec()['model_ops']['model.repair_core']['checks'], W.CHECKS), W.CHECKS)
        self.assertEqual([v['verdict'] for v in verdicts], ['pass', 'pass', 'pass', 'inconclusive'])


class PolicyTests(unittest.TestCase):
    def test_every_escape_fixture_is_refused_by_both_policy_implementations(self):
        for name, (expect, body) in D.ESCAPES.items():
            source = 'def parse_amount(text):\n' + body
            runtime = SW.check_function(source, 'parse_amount', ['text'], POLICY)
            independent = E.policy_problems(source, 'parse_amount', ['text'])
            self.assertEqual(bool(runtime), expect == 'refused', name)
            self.assertEqual(bool(independent), expect == 'refused', name)

    def test_one_function_with_the_frozen_signature_only(self):
        ok = 'def parse_amount(text):\n    def inner(x):\n        return x\n    return inner(1)\n'
        self.assertEqual(SW.check_function(ok, 'parse_amount', ['text'], POLICY), [])
        for bad in ('def parse_amount(text, extra):\n    return 1\n', 'def parse(text):\n    return 1\n',
                    'X = 1\ndef parse_amount(text):\n    return 1\n', 'def parse_amount(text=1):\n    return 1\n',
                    'def parse_amount(text: str):\n    return 1\n', 'def parse_amount(*text):\n    return 1\n',
                    'def parse_amount(text):\n    return 1\ndef helper():\n    return 2\n'):
            self.assertTrue(SW.check_function(bad, 'parse_amount', ['text'], POLICY), bad)
            self.assertTrue(E.policy_problems(bad, 'parse_amount', ['text']), bad)

    def test_the_source_limit_is_4096_bytes_of_decoded_source_apart_from_the_wire(self):
        body = 'def parse_amount(text):\n    return "' + 'é' * 2030 + '"\n'
        self.assertGreater(len(body.encode('utf-8')), 4096)
        self.assertLess(len(json.dumps(body)), 65536)
        self.assertFalse(W.source_ok(body))
        self.assertTrue(SW.check_function(body, 'parse_amount', ['text'], POLICY))
        self.assertTrue(W.source_ok('def parse_amount(text):\n    return 1\n'))

    def test_outputs_are_type_strict_and_refused_before_serialization(self):
        self.assertEqual(SW.canonical([1, True, None, 'x', {'a': [0]}]), '[1,true,null,"x",{"a":[0]}]')
        for bad in ((1, 2), {1, 2}, 1.5, {1: 'a'}, [(1,)]):
            with self.assertRaises(SW.Unsupported):
                SW.canonical(bad)


class RecordAndTierTests(unittest.TestCase):
    def test_records_are_the_frozen_texts_and_anything_else_is_refused(self):
        t = W.ticket('A', 1)
        self.assertEqual(W.parse_record(t['core_record'])[1], 'core')
        core = fn('A', 1, 'parse_amount')
        ticket, op, accepted = W.parse_record(t['adapter_record_prefix'] + core)
        self.assertEqual((op, accepted), ('adapter', core))
        for bad in (t['core_record'].replace('nine', 'ten'), t['core_record'].replace('ticket: A', 'ticket: Z'),
                    t['core_record'].replace('revision: 1', 'revision: 3'), t['adapter_record_prefix'], 'free text'):
            with self.assertRaises(HostError):
                W.parse_record(bad)

    def test_the_a_tier_accepts_a_valid_alternative_and_rejects_the_defective_original(self):
        t = W.ticket('D', 1)
        spec_ = {'op': 'core'}
        self.assertTrue(W.check_tier_a(fn('D', 1, 'topological_order'), spec_, inputs(t['core_record'])))
        self.assertFalse(W.check_tier_a(fn('D', 1, 'topological_order', 'original'), spec_,
                                        inputs(t['core_record'])))
        self.assertFalse(W.check_tier_a(fn('D', 1, 'topological_order'), {'op': 'adapter'},
                                        inputs(t['core_record'])))

    def test_adapter_rows_use_stubs_and_the_accepted_core_with_call_records(self):
        t = W.ticket('C', 1)
        core = fn('C', 1, 'merge_patch')
        payload_, expected = W.tier_a_payload(t, 'adapter', fn('C', 1, 'apply_revisions'), core)
        kinds = {r.get('core') for r in payload_['rows']}
        self.assertEqual(kinds, {'stub', 'recorded'})
        self.assertTrue(payload_['alias'])
        self.assertTrue(all('calls' in e for e in expected))
        self.assertTrue(W.judge(payload_, expected)['pass'])

    def test_every_core_call_of_an_integration_row_is_an_a_tier_core_input(self):
        tier = W.load('tier_a.json')
        for ticket, rev in B.REVISIONS:
            have = {SW.canonical(r['args']) for r in tier[f'{ticket}{rev}.core']}
            for row in tier[f'{ticket}{rev}.adapter']:
                if row['kind'] == 'integration':
                    self.assertTrue(set(row['expect']['calls']) <= have, row['id'])

    def test_coverage_rows_families_sides_and_categories(self):
        matrix = W.load('coverage.json')
        self.assertEqual(len(matrix), 10)
        for key, m in matrix.items():
            self.assertGreaterEqual(m['rows'], 12, key)
            for family, f in m['families'].items():
                if family != 'integration_support':
                    self.assertGreaterEqual(f['rows'], 2, (key, family))
                if {'inside', 'outside'} & set(f['sides']):
                    self.assertLessEqual({'inside', 'outside'}, set(f['sides']), (key, family))
            for c in ('value', 'empty_or_identity', 'raises:ValueError'):
                self.assertTrue(c in m['categories'] or c in m['inapplicable'], (key, c))

    def test_every_seeded_defect_has_discriminating_a_rows_and_a_reason(self):
        defects = W.load('defects.json')
        self.assertGreaterEqual(len(defects), 26)
        for d in defects:
            self.assertTrue(d['discriminating_rows'], d['defect'])
            self.assertTrue(d['why_semantic'])

    def test_revision_2_changes_precision_and_old_implementations_fail_it(self):
        t1, t2 = W.ticket('A', 1), W.ticket('A', 2)
        self.assertEqual((t1['precision'], t2['precision']), (2, 3))
        self.assertNotEqual(t1['core_record'], t2['core_record'])
        old = fn('A', 1, 'parse_amount')
        self.assertFalse(W.check_tier_a(old, {'op': 'core'}, inputs(t2['core_record'])))

    def test_the_frozen_pack_equals_its_generator_and_both_references_agree(self):
        self.assertEqual(B.main(['--check']), 0)

    def test_held_out_domains_have_their_frozen_cardinalities_and_digests(self):
        data = json.loads((O1 / 'evaluator' / 'heldout.json').read_text(encoding='utf-8'))
        for key in H.KEYS:
            inputs_, expects = E.h_vectors(key)
            self.assertEqual(len(inputs_), H.CARDINALITY[key])
            self.assertEqual(len(expects), data['domains'][key]['cardinality'])

    def test_references_and_held_out_data_are_unreachable_from_the_executor(self):
        result = D.provenance_scan()
        self.assertTrue(result['pass'], result['found'])


class HostOpTests(unittest.TestCase):
    def sources(self, kind='fixture'):
        out = {}
        for name in W.TICKETS:
            t = W.ticket(name, 1)
            out[name] = (t, fn(name, 1, t['core']['name'], kind), fn(name, 1, t['adapter']['name'], kind))
        return out

    def test_assembly_inserts_the_accepted_bytes_unchanged_and_the_patch_rebuilds_the_package(self):
        snap = {'tickets': {n: {'ticket': t} for n, (t, c, a) in self.sources().items()}}
        package = W.op_assemble({'snapshot': snap, 'cores': [c for t, c, a in self.sources().values()],
                                 'adapters': [a for t, c, a in self.sources().values()]}, None)
        for name, (t, core, adapter) in self.sources().items():
            text = package['modules'][name]['text']
            self.assertIn(core, text)
            self.assertIn(adapter, text)
            self.assertEqual(E.assemble(t, core, adapter), text)
        patch_text = W.render_patch(snap, package)
        originals = {snap['tickets'][n]['ticket']['module']: snap['tickets'][n]['ticket']['module_source']
                     for n in W.TICKETS}
        rebuilt = W.apply_patch(originals, patch_text)
        for name in W.TICKETS:
            self.assertEqual(rebuilt[package['modules'][name]['file']], package['modules'][name]['text'])
        with self.assertRaises(HostError):
            W.apply_patch(originals, patch_text.replace('\n-    ', '\n-     ', 1))
        tampered = W.apply_patch(originals, patch_text.replace('\n+    ', '\n+     ', 1))
        self.assertNotEqual(tampered, rebuilt)

    def test_twenty_nodes_eight_model_jobs_and_twelve_host_steps(self):
        descriptors = admit(W.graph(), W.registry(), effects=['local_publish'])
        kinds = [d['kind'] for d in descriptors]
        self.assertEqual((len(kinds), kinds.count('model'), kinds.count('host')), (20, 8, 12))
        self.assertEqual(W.graph()['outputs'], {'repair_package': 'publish'})

    def test_settings_label_sizes_4_and_1_experimental_and_the_default_stays(self):
        self.assertEqual(Settings.__dataclass_fields__['experimental_sizes'].default, (4,))
        ws = Path(tempfile.mkdtemp())
        try:
            s = O.settings(ws, 'fixture', 'ns', quota=None)
            self.assertEqual((s.packet_sizes, s.experimental_sizes), ((4, 1), (4, 1)))
            self.assertEqual(s.budget['max_tokens'], 150000)
            self.assertEqual((s.budget['max_launches'], s.budget['max_launches_per_flow']), (18, 8))
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_the_scenario_table(self):
        rows = {s['name']: (s['expected_launches'], s['expected_packets'], s['expected_memo_hits'])
                for s in W.spec()['scenarios']}
        self.assertEqual(rows, {'clean': (2, [4, 4], 0), 'repeat': (0, [], 8), 'interrupt': (2, [4, 4], 0),
                                'stale': (4, [4, 4, 1, 1], 6), 'bump': (0, [], 16)})


def dispatch(stage, jobs, records, attempt=1, story=None, receipt=None, t=[0.0]):
    t[0] += 1
    d = {'stage': stage, 'receipt': receipt or f'r{stage}{attempt}{"".join(j[-1] for j in jobs)}{t[0]}',
         'created_at': t[0], 'label': 'experimental',
         'members': [{'id': j, 'generation': 1, 'attempt': attempt, 'compute_key': 'k-' + j} for j in jobs],
         'refs': {j: records[j] for j in jobs}}
    D.restory(d, story or {})
    return d


def clean_records():
    out = {}
    for name in W.TICKETS:
        t = W.ticket(name, 1)
        out['core_' + name] = t['core_record']
        out['adapter_' + name] = t['adapter_record_prefix'] + fn(name, 1, t['core']['name'])
    return out


CORES = ['core_' + n for n in W.TICKETS]
ADAPTERS = ['adapter_' + n for n in W.TICKETS]


class PredicateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = clean_records()

    def trace(self, core_story=None, resends=()):
        trace = [dispatch(0, CORES, self.records, story=core_story)]
        for jobs in resends:
            trace.append(dispatch(0, jobs, self.records, attempt=2))
        trace.append(dispatch(1, ADAPTERS, self.records))
        return trace

    def test_the_failure_free_trace_derives_two_size_four_packets(self):
        errors, derived, blocked, _ = GT.trace_errors('clean', self.trace(), 8)
        self.assertEqual(errors, [])
        self.assertEqual(derived, [(0, tuple(CORES), 1), (1, tuple(ADAPTERS), 1)])
        self.assertIsNone(blocked)

    def test_rejected_members_go_back_alone_and_four_rejections_one_size_four_resend(self):
        trace = self.trace({'core_A': 'check_rejected', 'core_C': 'check_rejected'}, [['core_A'], ['core_C']])
        errors, derived, blocked, _ = GT.trace_errors('clean', trace, 8)
        self.assertEqual(errors, [])
        all4 = self.trace({j: 'check_rejected' for j in CORES}, [CORES])
        self.assertEqual(GT.trace_errors('clean', all4, 8)[0], [])

    def test_a_model_failure_record_is_terminal_and_a_resend_of_it_is_caught(self):
        trace = [dispatch(0, CORES, self.records, story={'core_C': 'model_error'})]
        errors, derived, blocked, _ = GT.trace_errors('clean', trace, 8)
        self.assertEqual(errors, [])
        self.assertEqual(blocked['model_failure'], ['core_C'])
        resent = trace + [dispatch(0, ['core_C'], self.records, attempt=2)]
        self.assertIn('model_failure_resent', {e['code'] for e in GT.trace_errors('clean', resent, 8)[0]})

    def test_a_correct_candidate_rejected_by_the_executor_is_a_false_rejection(self):
        trace = self.trace({'core_B': 'executor_rejects_right'}, [['core_B']])
        errors = GT.trace_errors('clean', trace, 8)[0]
        self.assertTrue(any(e['code'] == 'verdict_disagreement' and e.get('kind') == 'false_rejection'
                            for e in errors))

    def test_a_defective_candidate_accepted_by_the_executor_is_a_false_acceptance(self):
        trace = self.trace({'core_D': 'executor_accepts_wrong'})
        errors = GT.trace_errors('clean', trace, 8)[0]
        self.assertTrue(any(e['code'] == 'verdict_disagreement' and e.get('kind') == 'false_acceptance'
                            for e in errors))

    def test_accepted_sibling_resend_third_attempt_and_held_resend_are_caught(self):
        sibling = self.trace() [:1] + [dispatch(0, ['core_B'], self.records, attempt=2)]
        self.assertIn('accepted_member_resent', {e['code'] for e in GT.trace_errors('clean', sibling, 8)[0]})
        third = [dispatch(0, CORES, self.records, story={'core_A': 'check_rejected'}),
                 dispatch(0, ['core_A'], self.records, attempt=2, story={'core_A': 'check_rejected'}),
                 dispatch(0, ['core_A'], self.records, attempt=3)]
        self.assertIn('third_attempt', {e['code'] for e in GT.trace_errors('clean', third, 8)[0]})
        held = [dispatch(0, CORES, self.records, story={'core_A': 'held'}),
                dispatch(0, ['core_A'], self.records, attempt=2)]
        self.assertIn('held_member_resent', {e['code'] for e in GT.trace_errors('clean', held, 8)[0]})

    def test_a_wire_rejection_is_atomic_and_resent_whole(self):
        trace = self.trace({'core_A': 'wire_rejected'}, [CORES])
        trace[0]['verdicts'] = dict.fromkeys(CORES, 'no_candidate')
        self.assertEqual(GT.trace_errors('clean', trace, 8)[0], [])
        broken = copy.deepcopy(trace)
        broken[0]['evidence']['candidates']['core_B'] = {'status': 'accepted', 'value': json.dumps('x')}
        self.assertIn('wire_rejection_not_atomic', {e['code'] for e in GT.trace_errors('clean', broken, 8)[0]})

    def test_an_adapter_record_must_carry_the_core_accepted_before_it(self):
        trace = self.trace()
        trace[1]['refs']['adapter_A'] = W.ticket('A', 1)['adapter_record_prefix'] + fn('A', 1, 'parse_amount',
                                                                                        'ref2')
        D.restory(trace[1], {})
        self.assertIn('stale_input', {e['code'] for e in GT.trace_errors('clean', trace, 8)[0]})


class ScenarioTests(unittest.TestCase):
    """clean and repeat through the real executor (fixture adapter), judged by the gate and the evaluator."""

    @classmethod
    def setUpClass(cls):
        cls.saved = os.environ.get('OZ_FIXTURE_DIR')
        cls.base = Path(tempfile.mkdtemp(prefix='o1-test-'))
        cls.ws = cls.base / 'ws'
        O.prepare(cls.ws, 'fixture')
        cls.rows = {s: O.scenario_report(cls.ws, 'fixture', 't', s) for s in ('clean', 'repeat')}

    @classmethod
    def tearDownClass(cls):
        if cls.saved is None:
            os.environ.pop('OZ_FIXTURE_DIR', None)
        else:
            os.environ['OZ_FIXTURE_DIR'] = cls.saved
        shutil.rmtree(cls.base, ignore_errors=True)

    def test_clean_passes_with_two_experimental_size_four_launches(self):
        row = self.rows['clean']
        self.assertTrue(row[GT.LABEL], row['gate']['checks'])
        self.assertEqual((row['launches'], row['packets'], row['labels']), (2, [4, 4], ['experimental'] * 2))
        self.assertEqual(row['gate']['package']['errors'], [])
        self.assertTrue(all(v['pass'] for v in row['gate']['package']['detail']['H_reference_core'].values()))

    def test_the_delivered_functions_are_the_accepted_reply_bytes(self):
        dest = Path(self.rows['clean']['_obs']['delivery_dir'])
        text = (dest / 'jobs.py').read_text(encoding='utf-8')
        self.assertIn(fn('D', 1, 'topological_order'), text)
        self.assertIn('not independently discovered bug reports', (dest / 'provenance.json').read_text('utf-8'))

    def test_repeat_is_eight_memo_hits_and_no_launch(self):
        row = self.rows['repeat']
        self.assertTrue(row[GT.LABEL], row['gate']['checks'])
        self.assertEqual((row['launches'], row['memo_hits']), (0, 8))

    def test_a_delivered_package_with_a_changed_function_fails_the_evaluator(self):
        obs = self.rows['clean']['_obs']
        copy_dir = self.base / 'tampered'
        shutil.copytree(obs['delivery_dir'], copy_dir)
        path = copy_dir / 'amounts.py'
        path.write_text(path.read_text(encoding='utf-8').replace("'invalid amount'", "'bad amount'", 1),
                        encoding='utf-8', newline='\n')
        verdict = GT.scenario_verdict(dict(obs, delivery_dir=str(copy_dir)))
        self.assertFalse(verdict[GT.LABEL])
        self.assertTrue(any('byte for byte' in e for e in verdict['package']['errors']))


class LiveGuardTests(unittest.TestCase):
    def test_live_needs_the_confirmation_variable(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(O.LIVE_ENV, None)
            self.assertEqual(O.main(['live', '--workspace', str(Path(tempfile.gettempdir()) / 'o1-never')]), 2)
            self.assertEqual(O.main(['run-flow', '--workspace', 'x', '--kind', 'live', '--prefix', 'p',
                                     '--scenario', 'clean']), 2)

    def test_live_refuses_a_changed_freeze_another_cli_or_a_used_workspace(self):
        self.assertIsNotNone(O.live_refusal({'frozen': False}, '2.1.306'))
        self.assertIsNotNone(O.live_refusal({'frozen': True}, '9.9.9'))
        self.assertIsNone(O.live_refusal({'frozen': True}, '2.1.306'))
        ws = Path(tempfile.mkdtemp())
        try:
            (ws / 'flows' / 'x').mkdir(parents=True)
            self.assertIsNotNone(O.fresh_refusal(ws))
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_the_freeze_holds(self):
        result = O.freeze()
        self.assertTrue(result['frozen'], result['problems'][:5])


if __name__ == '__main__':
    unittest.main()
