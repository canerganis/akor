"""Step 3 (Haiku 5.5 on repair-handoff-20/v1) zero-call tests: the derived freeze (route.model and route.alias_map only,
from the O1 freeze 088815db), the driver that applies it without editing any pinned file, the control-match checks
against the archived Sonnet control (bench/o1/live1) and the experimental labels under the Haiku route. Nothing here
calls a model."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
O1 = ROOT / 'bench' / 'o1'
# bench/step4 also has modules named workflow, evaluator and fixture_adapter; load the O1 ones, then put back whatever
# another test module had registered (the same dance as tests/test_o1.py).
for p in (str(ROOT), str(O1 / 'evaluator'), str(O1)):
    if p in sys.path:
        sys.path.remove(p)
    sys.path.insert(0, p)
_SHARED = ('workflow', 'evaluator', 'fixture_adapter')
_SAVED = {name: sys.modules.pop(name) for name in _SHARED if name in sys.modules}

import o1 as O  # noqa: E402
import step3_checks as C  # noqa: E402
import step3_haiku as S  # noqa: E402
from oz import Error  # noqa: E402

for _name in _SHARED:
    sys.modules.pop(_name, None)
sys.modules.update(_SAVED)

HAIKU = 'claude-haiku-5-5'
BASE_DIGEST = '088815dbd9d1817af64b5b1d7ed96f4631681193ca1784387084e9421f2b1f36'
PACK = O1 / 'repair-handoff-20-haiku'


def envelope(model):
    return {'modelUsage': {model: {'inputTokens': 1, 'outputTokens': 1, 'cacheReadInputTokens': 0,
                                   'cacheCreationInputTokens': 0}}}


class OverlayTests(unittest.TestCase):
    def test_the_overlay_changes_only_route_model_and_alias_map(self):
        base = copy.deepcopy(O.spec())
        derived = S.derive(base, S.overlay())
        self.assertEqual(sorted(S.changed_paths(base, derived)), ['route.alias_map', 'route.model'])
        self.assertEqual((derived['route']['model'], derived['route']['alias_map']), (HAIKU, {HAIKU: HAIKU}))
        self.assertEqual(base['route']['model'], 'claude-sonnet-5-5')  # the base object is never edited

    def test_every_other_route_field_and_every_other_key_is_the_bases(self):
        base = O.spec()
        derived = S.derive(copy.deepcopy(base), S.overlay())
        for key in base:
            if key != 'route':
                self.assertEqual(base[key], derived[key], key)
        for key in set(base['route']) - {'model', 'alias_map'}:
            self.assertEqual(base['route'][key], derived['route'][key], key)

    def test_an_overlay_that_touches_anything_else_is_refused(self):
        good = json.loads((PACK / 'route.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            for name, mutate in (('effort', lambda d: d['route'].update(effort='high')),
                                 ('top', lambda d: d['route'].update(cli_version='2.1.307')),
                                 ('other_key', lambda d: d.update(allocation={'max_tokens': 1})),
                                 ('model_type', lambda d: d['route'].update(model=5)),
                                 ('alias_value', lambda d: d['route'].update(alias_map={HAIKU: 5})),
                                 ('missing_alias', lambda d: d['route'].pop('alias_map'))):
                bad = copy.deepcopy(good)
                mutate(bad)
                path = Path(tmp) / f'{name}.json'
                path.write_text(json.dumps(bad), encoding='utf-8')
                with self.assertRaises(Error, msg=name):
                    S.overlay(path)

    def test_the_alias_map_is_the_key_every_archived_haiku_report_carries(self):
        """bench/live/run_live.py writes the joined modelUsage keys of each claude -p envelope as `model`."""
        seen, count = set(), 0
        for path in sorted((ROOT / 'bench' / 'live' / 'data').glob('*haiku*.jsonl')):
            for line in path.read_text(encoding='utf-8').splitlines():
                row = json.loads(line) if line.strip() else {}
                if isinstance(row, dict) and 'model' in row:
                    seen.add(row['model'])
                    count += 1
        self.assertGreater(count, 300)
        self.assertEqual(seen, {HAIKU})
        alias = S.overlay()['alias_map']
        self.assertEqual(alias, {key: HAIKU for key in seen})
        evidence = json.loads((PACK / 'route.json').read_text(encoding='utf-8'))['evidence']
        self.assertEqual((evidence['records'], evidence['reported_models']), (count, [HAIKU]))

    def test_the_response_check_accepts_only_haiku_under_the_derived_route(self):
        derived = S.derive(copy.deepcopy(O.spec()), S.overlay())
        check = O.response_check(derived['route']['model'], derived['route']['alias_map'])
        base_check = O.response_check('claude-sonnet-5-5', O.spec()['route']['alias_map'])

        def refuses(fn, model):
            with tempfile.TemporaryDirectory() as tmp:
                capture = {'envelope_b64': __import__('base64').b64encode(
                    json.dumps(envelope(model)).encode()).decode()}
                with patch.object(O, 'read_capture', lambda *a: capture):
                    return fn({'capture_dir': tmp, 'receipt': 'r', 'request_sha256': 'x'})
        self.assertIsNone(refuses(check, HAIKU))
        self.assertIn('unexpected model', refuses(check, 'claude-sonnet-5-5'))
        self.assertIn('unexpected model', refuses(base_check, HAIKU))


class DerivedFreezeTests(unittest.TestCase):
    def test_the_base_freeze_still_holds_and_is_088815db(self):
        result = O.freeze()
        self.assertTrue(result['frozen'], result['problems'][:5])
        self.assertEqual(result['digest'], BASE_DIGEST)

    def test_the_derived_record_verifies_and_names_its_base(self):
        result = S.derived_freeze()
        self.assertTrue(result['frozen'], result['problems'][:5])
        self.assertEqual(result['base_digest'], BASE_DIGEST)
        record = json.loads((PACK / 'freeze.json').read_text(encoding='utf-8'))
        self.assertEqual(record['base']['digest'], BASE_DIGEST)
        self.assertEqual(result['digest'], record['digest'])
        self.assertNotEqual(result['digest'], BASE_DIGEST)
        self.assertEqual(sorted(record['derived']['changed']), ['route.alias_map', 'route.model'])

    def test_the_record_pins_the_driver_the_checks_the_replay_adapter_and_the_design_texts(self):
        record = json.loads((PACK / 'freeze.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(record['code']),
                         ['bench/o1/step3_checks.py', 'bench/o1/step3_haiku.py', 'bench/o1/step3_replay_adapter.py'])
        self.assertEqual(sorted(record['design']),
                         ['docs/design/step3-haiku-2026-10-23/01-astra-prereg.md',
                          'docs/design/step3-haiku-2026-10-23/02-opus-changes.md',
                          'docs/design/step3-haiku-2026-10-23/03-astra-accept.md'])
        self.assertIn('bench/o1/repair-handoff-20-haiku/control-freeze-32333561.json', record['overlay'])

    def test_drift_in_any_pinned_part_is_reported(self):
        record = json.loads((PACK / 'freeze.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            def problems(mutate):
                bad = copy.deepcopy(record)
                mutate(bad)
                path = Path(tmp) / 'freeze.json'
                path.write_text(json.dumps(bad), encoding='utf-8')
                result = S.derived_freeze(record_path=path)
                return result['frozen'], result['problems']
            for mutate in (lambda r: r['derived'].update(model='claude-sonnet-5-5'),
                           lambda r: r['base'].update(digest='0' * 64),
                           lambda r: r['overlay'].update({next(iter(r['overlay'])): '0' * 64}),
                           lambda r: r['code'].update({next(iter(r['code'])): '0' * 64}),
                           lambda r: r['design'].update({next(iter(r['design'])): '0' * 64}),
                           lambda r: r.update(digest='0' * 64)):
                frozen, found = problems(mutate)
                self.assertFalse(frozen)
                self.assertTrue(found)

    def test_a_changed_base_freeze_blocks_the_derived_freeze(self):
        with patch.object(S, 'base_freeze', lambda: {'frozen': False, 'digest': BASE_DIGEST,
                                                     'current_digest': 'f' * 64, 'problems': ['x changed']}):
            result = S.derived_freeze()
        self.assertFalse(result['frozen'])
        self.assertTrue(any('base freeze' in p for p in result['problems']))

    def test_the_control_freeze_copy_is_the_32333561_record(self):
        copy_ = json.loads((PACK / 'control-freeze-32333561.json').read_text(encoding='utf-8'))
        self.assertTrue(copy_['digest'].startswith('32333561'))


class AppliedTests(unittest.TestCase):
    def test_the_context_applies_the_haiku_route_and_restores_everything(self):
        saved = (O.freeze, O.__file__, O.spec()['route']['model'])
        with S.applied():
            self.assertEqual(O.spec()['route']['model'], HAIKU)
            self.assertEqual(O.route('live')[1], HAIKU)
            self.assertEqual(O.spec()['route']['alias_map'], {HAIKU: HAIKU})
            self.assertEqual(O.freeze()['digest'], S.derived_freeze()['digest'])
            self.assertEqual(O.__file__, str(O1 / 'step3_haiku.py'))
        self.assertEqual((O.freeze, O.__file__, O.spec()['route']['model']), saved)
        self.assertEqual(O.route('live')[1], 'claude-sonnet-5-5')

    def test_the_context_restores_after_an_error(self):
        with self.assertRaises(RuntimeError):
            with S.applied():
                raise RuntimeError('x')
        self.assertEqual(O.spec()['route']['model'], 'claude-sonnet-5-5')

    def test_a_drifted_derived_freeze_refuses_to_apply(self):
        with patch.object(S, 'derived_freeze', lambda **k: {'frozen': False, 'problems': ['p'], 'digest': 'd',
                                                            'current_digest': 'c'}):
            with S.applied():
                self.assertFalse(O.freeze()['frozen'])  # O.live_refusal then stops a live run before any launch
                self.assertIsNotNone(O.live_refusal(O.freeze(), '2.1.306'))

    def test_live_settings_name_haiku_with_every_other_route_field_the_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / 'ws'
            base_fields, base_model = O.route('live')
            with S.applied():
                fields, model = O.route('live')
                quota = O.quota_store(ws, 'fixture')
                try:
                    settings = O.settings(ws, 'live', 'ns', quota=quota)
                finally:
                    quota.close()
            self.assertEqual((base_model, model), ('claude-sonnet-5-5', HAIKU))
            self.assertEqual(fields, base_fields)
            self.assertEqual(settings.model, HAIKU)
            self.assertEqual(tuple(settings.experimental_sizes), (4, 1))
            self.assertEqual(tuple(settings.packet_sizes), (4, 1))
            self.assertEqual(settings.route, base_fields)

    def test_the_flow_request_carries_the_derived_digest(self):
        base = O.flow_request('p', 'clean')['workflow_digest']
        with S.applied():
            derived = O.flow_request('p', 'clean')['workflow_digest']
        self.assertEqual(base, BASE_DIGEST)
        self.assertEqual(derived, S.derived_freeze()['digest'])

    def test_the_interrupt_scenario_re_runs_the_driver_not_o1(self):
        seen = []

        class Done:
            returncode, stderr = 0, ''

        def fake_run(cmd, **kw):
            seen.append(cmd)
            return Done()
        with S.applied(), patch.object(O.subprocess, 'run', fake_run):
            O.run_interrupt(Path('ws'), 'live', 'p')
        self.assertEqual(len(seen), 3)
        for cmd in seen:
            self.assertEqual(Path(cmd[1]).name, 'step3_haiku.py')
            self.assertEqual(cmd[2], 'run-flow')
        with patch.object(O.subprocess, 'run', fake_run):
            seen.clear()
            O.run_interrupt(Path('ws'), 'live', 'p')
        self.assertEqual(Path(seen[0][1]).name, 'o1.py')

    def test_a_child_process_of_the_driver_sees_the_haiku_route(self):
        out = subprocess.run([sys.executable, str(O1 / 'step3_haiku.py'), 'route'], capture_output=True, text=True,
                             encoding='utf-8', cwd=str(ROOT), env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        self.assertEqual(out.returncode, 0, out.stderr)
        info = json.loads(out.stdout)
        self.assertEqual((info['model'], info['alias_map'], info['frozen']), (HAIKU, {HAIKU: HAIKU}, True))
        self.assertEqual(info['experimental_sizes'], [4, 1])
        self.assertEqual(info['base_digest'], BASE_DIGEST)


class LiveGuardTests(unittest.TestCase):
    def test_live_needs_the_confirmation_the_quota_reading_and_a_start_below_45(self):
        never = str(Path(tempfile.gettempdir()) / 'step3-never')
        calls = []
        with patch.dict(os.environ, {}, clear=False), patch.object(O, 'suite', lambda *a: calls.append(a)):
            os.environ.pop(O.LIVE_ENV, None)
            self.assertEqual(S.main(['live', '--workspace', never, '--quota-before', '40']), 2)
            os.environ[O.LIVE_ENV] = '1'
            self.assertEqual(S.main(['live', '--workspace', never]), 2)
            for bad in ('55', '55.0', '56', '59', 'abc', '-1', 'nan'):
                self.assertEqual(S.main(['live', '--workspace', never, '--quota-before', bad]), 2, bad)
        self.assertEqual(calls, [])
        self.assertFalse(Path(never).exists())

    def test_a_good_reading_runs_the_suite_once_with_the_haiku_route_and_records_the_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / 'ws'
            seen = []

            def fake_suite(path, kind, prefix):
                seen.append((kind, prefix, O.spec()['route']['model'], O.route('live')[1]))
                return {'pass': True}
            with patch.dict(os.environ, {O.LIVE_ENV: '1'}), patch.object(O, 'suite', fake_suite), \
                    patch.object(O, 'cli_version', lambda: '2.1.306'):
                code = S.main(['live', '--workspace', str(ws), '--prefix', 'hk1', '--quota-before', '44.9'])
            self.assertEqual(code, 0)
            self.assertEqual(seen, [('live', 'hk1', HAIKU, HAIKU)])
            record = json.loads((ws / 'quota-hk1.json').read_text(encoding='utf-8'))
            self.assertEqual(record['before_percent'], 44.9)

    def test_a_used_workspace_or_another_cli_refuses_before_any_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / 'ws'
            (ws / 'flows' / 'x').mkdir(parents=True)
            with patch.dict(os.environ, {O.LIVE_ENV: '1'}), patch.object(O, 'cli_version', lambda: '2.1.306'), \
                    patch.object(O, 'run_scenario_flow', side_effect=AssertionError('launched')):
                code = S.main(['live', '--workspace', str(ws), '--prefix', 'hk1', '--quota-before', '30'])
            self.assertEqual(code, 3)  # suite returned its blocker report: not fresh, nothing launched

    def test_quota_after_records_the_stop_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / 'quota-hk1.json').write_text(json.dumps({'before_percent': 40.0}), encoding='utf-8')
            for after, status in ((53, 'ok'), (56, 'stop_reached_56'), (58.9, 'stop_reached_56'), (59, 'hard_stop_59')):
                code = S.main(['quota-after', '--workspace', str(ws), '--prefix', 'hk1', '--percent', str(after)])
                self.assertEqual(code, 0)
                record = json.loads((ws / 'quota-hk1.json').read_text(encoding='utf-8'))
                self.assertEqual((record['after_percent'], record['status']), (float(after), status), after)


class ControlArchiveTests(unittest.TestCase):
    def test_the_archived_ledgers_carry_the_digests_02_names(self):
        seq = C.archived_sequences()
        short = lambda s: [(row['op'], len(row['ids']), row['system'][:8], row['prompt'][:8]) for row in seq[s]]  # noqa
        self.assertEqual(short('clean'), [('core', 4, 'd941a86d', 'ed27d59c'), ('adapter', 4, 'd941a86d', '1c08ef8e')])
        self.assertEqual(short('interrupt'), [('core', 4, 'd941a86d', 'ed27d59c'),
                                              ('adapter', 4, 'd941a86d', '1c628a20')])
        self.assertEqual(short('stale'), [('core', 4, 'd941a86d', 'ed27d59c'), ('adapter', 4, 'd941a86d', '1ca7cc03'),
                                          ('core', 1, 'd941a86d', '3fb652d8'), ('adapter', 1, 'd941a86d', '4157a4b8')])

    def test_the_replay_table_is_the_accepted_sonnet_values_by_job_and_revision(self):
        clean, stale = C.replay_table('clean'), C.replay_table('stale')
        self.assertEqual(sorted(clean), sorted(f'{op}_{t}@1' for op in ('core', 'adapter') for t in 'ABCD'))
        self.assertEqual(sorted(stale), sorted([f'{op}_{t}@1' for op in ('core', 'adapter') for t in 'ABCD']
                                               + ['core_A@2', 'adapter_A@2']))
        self.assertNotEqual(stale['core_A@1'], stale['core_A@2'])
        self.assertNotEqual(clean['core_A@1'], C.replay_table('interrupt')['core_A@1'])  # each run's own accepted bytes
        for table in (clean, stale):
            for value in table.values():
                self.assertTrue(value.startswith('def '))


class PinnedControlTests(unittest.TestCase):
    def test_the_pinned_function_digests_are_the_control_commit_sources(self):
        import ast
        import hashlib
        for key, want in C.CONTROL_FUNCTIONS.items():
            path, name = key.split(':')
            git = subprocess.run(['git', 'show', f'079a2f9:{path}'], capture_output=True, cwd=str(ROOT))
            if git.returncode != 0:
                self.skipTest('commit 079a2f9 is not in this clone')
            text = git.stdout.decode('utf-8').replace(chr(13) + chr(10), chr(10))
            node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertEqual(hashlib.sha256(ast.get_source_segment(text, node).encode('utf-8')).hexdigest(), want, key)

    def test_the_control_freeze_copy_is_what_git_holds_for_the_control_commit(self):
        git = subprocess.run(['git', 'show', '079a2f9:bench/o1/repair-handoff-20-v1/freeze.json'],
                             capture_output=True, cwd=str(ROOT))
        if git.returncode != 0:
            self.skipTest('commit 079a2f9 is not in this clone')
        self.assertEqual(json.loads(git.stdout), json.loads((PACK / 'control-freeze-32333561.json').read_text('utf-8')))


class ControlMatchTests(unittest.TestCase):
    """Real executor, fixture transport, a replay adapter that answers with the archived Sonnet accepted cores."""

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='s3-ctl-'))
        cls.saved = os.environ.get('OZ_FIXTURE_DIR')
        cls.report = C.control_match(cls.base)

    @classmethod
    def tearDownClass(cls):
        if cls.saved is None:
            os.environ.pop('OZ_FIXTURE_DIR', None)
        else:
            os.environ['OZ_FIXTURE_DIR'] = cls.saved
        shutil.rmtree(cls.base, ignore_errors=True)

    def verdicts(self):
        return {row['id']: row['verdict'] for row in self.report['items']}

    def test_every_item_is_decided_and_matches(self):
        bad = [row for row in self.report['items'] if row['verdict'] != 'MATCH']
        self.assertEqual(bad, [])
        self.assertTrue(self.report['all_match'])

    def test_the_named_items_are_all_present(self):
        self.assertEqual(sorted(self.verdicts()),
                         sorted(['core_size4_prompt', 'stale_core_A_singleton', 'adapter_prompts',
                                 'adapter_script', 'effort', 'parser_and_wire', 'wire_H_system', 'cli_version',
                                 'accounting_scope', 'executor_paths', 'run_ids', 'route_identity']))

    def test_the_four_adapter_prompt_digests_are_reproduced_from_the_archived_cores(self):
        row = next(r for r in self.report['items'] if r['id'] == 'adapter_prompts')
        self.assertEqual(sorted(x['expected'][:8] for x in row['detail']), ['1c08ef8e', '1c628a20', '1ca7cc03',
                                                                              '4157a4b8'])
        self.assertTrue(all(x['actual'] == x['expected'] for x in row['detail']))

    def test_the_core_digests_are_ed27d59c_and_3fb652d8_under_system_d941a86d(self):
        row = next(r for r in self.report['items'] if r['id'] == 'core_size4_prompt')
        self.assertEqual({x['expected'][:8] for x in row['detail']}, {'ed27d59c'})
        self.assertEqual({x['system'][:8] for x in row['detail']}, {'d941a86d'})
        self.assertEqual(len(row['detail']), 3)  # clean, interrupt, stale
        one = next(r for r in self.report['items'] if r['id'] == 'stale_core_A_singleton')
        self.assertEqual([x['expected'][:8] for x in one['detail']], ['3fb652d8'])

    def test_a_changed_archived_core_is_a_mismatch_for_the_adapter_prompt_only(self):
        real = C.replay_table

        def edited(scenario):
            table = dict(real(scenario))
            if scenario == 'clean':
                table['core_A@1'] = table['core_A@1'] + '\n'
            return table
        with tempfile.TemporaryDirectory() as tmp, patch.object(C, 'replay_table', edited):
            report = C.control_match(Path(tmp), scenarios=('clean',))
        by = {r['id']: r['verdict'] for r in report['items']}
        self.assertEqual(by['core_size4_prompt'], 'MATCH')
        self.assertEqual(by['adapter_prompts'], 'MISMATCH')
        self.assertFalse(report['all_match'])

    def test_a_changed_pinned_input_is_a_mismatch(self):
        control = json.loads((PACK / 'control-freeze-32333561.json').read_text(encoding='utf-8'))
        control['code']['examples/claude_cli_adapter.py'] = '0' * 64
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'c.json'
            path.write_text(json.dumps(control), encoding='utf-8')
            report = C.control_match(Path(tmp), scenarios=(), control_path=path)
        by = {r['id']: r['verdict'] for r in report['items']}
        self.assertEqual(by['adapter_script'], 'MISMATCH')
        self.assertFalse(report['all_match'])

    def test_o1_never_uses_ordered_or_value_inputs(self):
        for name, op in O.W.registry().items():
            if hasattr(op, 'ref_order'):
                self.assertTrue(op.single, name)
                self.assertEqual(op.values, frozenset(), name)

    def test_the_replay_adapter_refuses_a_job_it_has_no_archived_answer_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'replay.json').write_text('{}', encoding='utf-8')
            record = O.W.ticket('A', 1)['core_record']
            request = {'system': 's', 'prompt': json.dumps({'jobs': [['m', ['core_A', 0]]], 'refs': [record]}),
                       'binding': 'b', 'receipt': '1', 'ids': ['core_A']}
            out = subprocess.run([sys.executable, str(O1 / 'step3_replay_adapter.py')], input=json.dumps(request),
                                 capture_output=True, text=True, encoding='utf-8',
                                 env=dict(os.environ, OZ_FIXTURE_DIR=tmp))
            self.assertNotEqual(out.returncode, 0)


class LabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='s3-lab-'))
        cls.saved = os.environ.get('OZ_FIXTURE_DIR')
        cls.report = C.label_check(cls.base)

    @classmethod
    def tearDownClass(cls):
        if cls.saved is None:
            os.environ.pop('OZ_FIXTURE_DIR', None)
        else:
            os.environ['OZ_FIXTURE_DIR'] = cls.saved
        shutil.rmtree(cls.base, ignore_errors=True)

    def test_sizes_4_and_1_are_experimental_under_the_haiku_route(self):
        self.assertTrue(self.report['pass'], self.report)
        self.assertEqual(self.report['model'], HAIKU)
        labeled = self.report['experimental']
        self.assertEqual(sorted({size for size, _ in labeled}), [1, 4])
        self.assertTrue(all(label == 'experimental' for _, label in labeled))

    def test_the_same_dispatches_would_read_qualified_cell_without_the_experimental_sizes(self):
        control = self.report['negative_control']
        self.assertEqual(sorted({size for size, _ in control}), [1, 4])
        self.assertTrue(all(label == 'qualified_cell' for _, label in control))

    def test_the_stale_flow_sends_both_sizes_and_the_gate_agrees(self):
        self.assertEqual(self.report['packets']['stale'], [4, 4, 1, 1])
        self.assertTrue(self.report['gate_every_dispatch_experimental'])


if __name__ == '__main__':
    unittest.main()
