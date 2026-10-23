"""Boundary probe harness tests (bench/probe/boundary.py). Everything is offline: no `claude` process is ever started
(subprocess.run is patched to fail wherever a test could reach it), and every run uses fixture replies and a fake clock."""
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'bench' / 'probe'))
sys.path.insert(0, str(ROOT))

import boundary as B  # noqa: E402

DESIGN = ROOT / 'docs' / 'design' / 'boundary-probe-2026-10-23'
A_SLOTS, B_SLOTS, C_SLOTS = (1, 6, 8, 10, 15, 17), (2, 4, 9, 12, 14, 16), (3, 5, 7, 11, 13, 18)
GOOD = B.GOOD


def envelope(result=GOOD, **kw):
    return json.dumps(B.fixture_envelope(result, **kw)).encode('utf-8')


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        guard = patch('subprocess.run', side_effect=AssertionError('no process may be started in tests'))
        guard.start()
        self.addCleanup(guard.stop)
        self.record = B.freeze_record()
        self.digest = B.freeze_digest(self.record)

    def go(self, name, plan=None, *, seconds=6.0, expect=None, **options):
        clock = [1000.0]
        runner = B.fixture_runner(plan or {}, clock, seconds=seconds)
        outcome = B.run(self.tmp / name, expect or self.digest, runner, clock=lambda: clock[0], log=lambda _: None,
                        record=self.record, **options)
        return outcome, runner

    def full(self, name, plan=None, **kw):
        outcome, _ = self.go(name, plan, **kw)
        self.assertEqual(outcome['stopped'], 'schedule complete')
        return B.analyze(self.tmp / name)

    def failing(self, slots, case='wrong_label'):
        return {n: case for n in slots}


class FrozenMaterial(Harness):
    def test_control_packet_reconstructs_to_the_stale_hash(self):
        reqs = B.requests()
        self.assertEqual(B.sha(reqs['A']['prompt']), '48ecc5b04ab8c6efdafdb315217a2c1729b1c2c904e52c71648b7abb0f83b0f9')
        self.assertEqual(B.sha(reqs['A']['system']), 'd941a86d530ab0fe1d90dc1fb9d957bd95da1bfa8d150d17e320debcef50ea06')
        self.assertEqual(reqs['A']['system'], reqs['B']['system'])
        self.assertEqual(reqs['B']['system'], reqs['C']['system'])

    def test_op_texts_are_the_signed_texts(self):
        text = (DESIGN / '01-astra-r1.md').read_text(encoding='utf-8')
        blocks = [b for b in re.findall(r'```text\n(.*?)\n```', text, re.S)
                  if b.startswith(('If uncertainty is unknown', 'The first ref is'))]
        self.assertEqual(blocks, [B.OP_B, B.OP_C])
        self.assertEqual(B.ops()['A'], 'Return inside if the entire length +/- uncertainty interval lies within the '
                         "goal's acceptance interval; outside otherwise. If uncertainty is unknown, return unknown.")

    def test_c_intervals_are_the_ones_signed_by_opus(self):
        text = (DESIGN / '02-opus-r1.md').read_text(encoding='utf-8')
        for fragment in ('["12.53 mm","12.57 mm"]', '["12.44 mm","12.50 mm"]', '["12.50 mm","12.52 mm"]', '"unknown"'):
            self.assertIn(fragment, text)
        self.assertIn('outside, outside, inside, unknown', text)
        self.assertEqual(tuple(B.EXPECTED.values()), ('outside', 'outside', 'inside', 'unknown'))

    def test_packet_shapes(self):
        a, b, c = (json.loads(B.build_prompt(x)) for x in 'ABC')
        self.assertEqual(a['jobs'], [[0, ['classify_A', 0], ['classify_B', 1], ['classify_C', 2], ['classify_D', 3]]])
        self.assertEqual(a['refs'], b['refs'])
        self.assertEqual(c['refs'][:4], a['refs'])
        self.assertEqual(c['refs'][4:], [['12.53 mm', '12.57 mm'], ['12.44 mm', '12.50 mm'],
                                         ['12.50 mm', '12.52 mm'], 'unknown'])
        self.assertEqual(c['jobs'], [[0, ['classify_A', 0, 4], ['classify_B', 1, 5], ['classify_C', 2, 6],
                                      ['classify_D', 3, 7]]])
        for arm in 'ABC':
            self.assertEqual(B.validate_packet(arm, B.build_prompt(arm)), [])

    def test_schedule_is_the_signed_latin_order(self):
        sched = B.schedule()
        self.assertEqual(''.join(s['arm'] for s in sched), 'ABCBCACABACBCBABAC')
        self.assertEqual(len(sched), 18)
        for arm in 'ABC':
            self.assertEqual(sum(s['arm'] == arm for s in sched), 6)
            self.assertEqual(sorted(s['position'] for s in sched if s['arm'] == arm), [1, 1, 2, 2, 3, 3])
        self.assertEqual((A_SLOTS, B_SLOTS, C_SLOTS),
                         tuple(tuple(s['slot'] for s in sched if s['arm'] == a) for a in 'ABC'))

    def test_freeze_digest_is_stable_and_sensitive(self):
        self.assertEqual(B.freeze_digest(), B.freeze_digest())
        with patch.object(B, 'OP_B', B.OP_B + ' '):
            self.assertNotEqual(B.freeze_digest(), self.digest)
        with patch.object(B, 'CAPS', dict(B.CAPS, max_tokens=70000)):
            self.assertNotEqual(B.freeze_digest(), self.digest)

    def test_freeze_fails_when_the_reconstruction_disagrees(self):
        with patch.object(B, 'CONTROL_SHA', '0' * 64):
            with self.assertRaises(B.ProbeError):
                B.freeze_record()
        with patch.object(B, 'SYSTEM_SHA', '0' * 64):
            with self.assertRaises(B.ProbeError):
                B.freeze_record()

    def test_plan_frozen_names_the_current_digest(self):
        text = (DESIGN / 'plan-frozen.md').read_text(encoding='utf-8')
        self.assertIn(self.digest, text)
        for needle in ('--expect', '60,000', '18', 'Fisher'):
            self.assertIn(needle, text)

    def test_call_matches_the_adapter(self):
        spec = importlib.util.spec_from_file_location('adapter_under_test', B.ADAPTER)
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        seen = {}

        class Done:
            stdout = json.dumps({'result': 'x'})

        def fake(argv, **kw):
            seen.update(argv=argv, **kw)
            return Done()

        request = {'system': 'SYS', 'prompt': 'PROMPT'}
        with patch.object(adapter.subprocess, 'run', fake), patch.object(adapter.shutil, 'which', lambda _: 'claude'), \
                patch.object(adapter.sys, 'stdin', io.StringIO(json.dumps(request))), \
                patch.object(adapter.sys, 'stdout', io.StringIO()), patch.dict('os.environ', {}, clear=False):
            adapter.main()
        self.assertEqual(seen['argv'], B.call_argv('SYS', 'claude'))
        self.assertEqual(seen['input'], 'PROMPT')
        self.assertEqual(seen['timeout'], B.CAPS['call_seconds'])

    def test_usage_agrees_with_the_adapter_where_both_are_defined(self):
        spec = importlib.util.spec_from_file_location('adapter_under_test2', B.ADAPTER)
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        env = B.fixture_envelope(GOOD, tokens=(2, 603, 1935, 61))
        mine, theirs = B.model_usage(env), adapter.usage_from_envelope(env)
        self.assertEqual(mine['total'], theirs['input_tokens'] + theirs['output_tokens'])
        self.assertEqual(mine['cache_read'], theirs['cached_input_tokens'])
        broken = B.fixture_envelope(GOOD, usage=False)
        self.assertIsNone(adapter.usage_from_envelope(broken))
        self.assertFalse(B.model_usage(broken)['complete'])


class Oracle(unittest.TestCase):
    def test_inclusive_equality_and_outside_intervals(self):
        self.assertEqual(B.oracle_label(['12.48 mm', '12.52 mm']), 'inside')
        self.assertEqual(B.oracle_label(['12.50 mm', '12.52 mm']), 'inside')
        self.assertEqual(B.oracle_label(['12.47 mm', '12.52 mm']), 'outside')
        self.assertEqual(B.oracle_label(['12.50 mm', '12.53 mm']), 'outside')
        self.assertEqual(B.oracle_label(['12.53 mm', '12.57 mm']), 'outside')
        self.assertEqual(B.oracle_label('unknown'), 'unknown')

    def test_intervals_from_records(self):
        rec = 'length=12.51 mm; uncertainty=0.01 mm; n=1; method=caliper; basis=resolution; physical_validation=not_claimed'
        self.assertEqual(B.oracle_interval(rec), ['12.50 mm', '12.52 mm'])
        unknown = rec.replace('uncertainty=0.01 mm', 'uncertainty=unknown')
        self.assertEqual(B.oracle_interval(unknown), 'unknown')
        with self.assertRaises(B.ProbeError):
            B.oracle_interval('length=12.5 mm')

    def test_frozen_labels_follow_from_the_records(self):
        labels = {i: B.oracle_label(B.oracle_interval(t)) for i, t in zip(B.IDS, B.sources().values())}
        self.assertEqual(labels, B.EXPECTED)

    def test_mismatched_checked_interval_is_caught(self):
        records = list(B.sources().values())
        self.assertTrue(B.interval_consistent(records[2], ['12.50 mm', '12.52 mm']))
        self.assertFalse(B.interval_consistent(records[2], ['12.50 mm', '12.53 mm']))
        self.assertFalse(B.interval_consistent(records[3], ['12.50 mm', '12.52 mm']))
        packet = json.loads(B.build_prompt('C'))
        packet['refs'][6] = ['12.51 mm', '12.53 mm']
        problems = B.validate_packet('C', B.compact(packet))
        self.assertTrue(any('does not match its record' in p for p in problems), problems)
        swapped = json.loads(B.build_prompt('C'))
        swapped['refs'][4], swapped['refs'][5] = swapped['refs'][5], swapped['refs'][4]
        self.assertTrue(B.validate_packet('C', B.compact(swapped)))

    def test_packet_validation_rejects_other_packets(self):
        self.assertTrue(B.validate_packet('A', B.build_prompt('B')))
        self.assertTrue(B.validate_packet('C', B.build_prompt('A')))
        self.assertTrue(B.validate_packet('A', B.build_prompt('A') + '\n'))
        rev1 = json.loads(B.build_prompt('A'))
        rev1['refs'][0] = rev1['refs'][0].replace('12.55', '12.50')
        self.assertTrue(B.validate_packet('A', B.compact(rev1)))


class Parser(unittest.TestCase):
    def ok(self, text):
        return B.parse_reply(text)['ok']

    def test_accepts_the_exact_shape_in_any_order_and_with_crlf(self):
        self.assertTrue(self.ok(GOOD))
        self.assertTrue(self.ok(GOOD + '\n'))
        self.assertTrue(self.ok(GOOD.replace('\n', '\r\n')))
        self.assertTrue(self.ok('\n\nOZ/1g\n' + '\n'.join(reversed(GOOD.split('\n')[1:]))))

    def test_rejects_whole_reply_on_any_defect(self):
        lines = GOOD.split('\n')
        cases = {
            'prose before': 'Here you go:\n' + GOOD,
            'no header': '\n'.join(lines[1:]),
            'code fence': '```\n' + GOOD + '\n```',
            'prose after': GOOD + '\nDone.',
            'duplicate id': GOOD + '\n{"classify_A":"outside"}',
            'missing id': '\n'.join(lines[:-1]),
            'extra id': GOOD + '\n{"classify_E":"outside"}',
            'bad json': GOOD.replace('"classify_B":"outside"}', '"classify_B":"outside"'),
            'single quotes': GOOD.replace('"classify_A"', "'classify_A'"),
            'two members': GOOD.replace('{"classify_A":"outside"}', '{"classify_A":"outside","classify_E":"x"}'),
            'bad error code': GOOD.replace('{"classify_B":"outside"}', '["classify_B","error","oops","m"]'),
            'blank error message': GOOD.replace('{"classify_B":"outside"}', '["classify_B","error","invalid_data"," "]'),
            'duplicate key in a line': GOOD.replace('{"classify_A":"outside"}', '{"classify_A":"outside","classify_A":"inside"}'),
            'leading space header': ' ' + GOOD,
            'empty': '',
            'not text': None,
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertFalse(B.parse_reply(text)['ok'])

    def test_valid_error_line_is_readable_and_never_counted_right(self):
        text = GOOD.replace('{"classify_B":"outside"}', '["classify_B","error","invalid_data","bad record"]')
        parsed = B.parse_reply(text)
        self.assertTrue(parsed['ok'])
        self.assertEqual(parsed['entries']['classify_B'], ('error', 'invalid_data', 'bad record'))
        ev = B.evaluate(0, False, 1000, envelope(text))
        self.assertEqual((ev['outcome'], ev['model_error_lines'], ev['correct_members']), ('model_error', 1, 3))
        self.assertFalse(ev['entirely_correct'])

    def test_value_must_be_the_exact_string(self):
        for wrong in ('"Inside"', '["inside"]', 'true', '"inside "'):
            ev = B.evaluate(0, False, 1000, envelope(GOOD.replace('"classify_C":"inside"', '"classify_C":' + wrong)))
            self.assertEqual(ev['outcome'], 'semantic', wrong)
            self.assertTrue(ev['boundary_error'])


class Accounting(unittest.TestCase):
    def test_total_is_input_plus_cache_plus_output_summed_over_entries_and_excludes_thinking(self):
        env = {'modelUsage': {
            'm1': {'inputTokens': 2, 'cacheReadInputTokens': 603, 'cacheCreationInputTokens': 1935, 'outputTokens': 61,
                   'thinkingTokens': 40},
            'm2': {'inputTokens': 1, 'cacheReadInputTokens': 2, 'cacheCreationInputTokens': 3, 'outputTokens': 4,
                   'thinkingTokens': 5}}}
        u = B.model_usage(env)
        self.assertEqual((u['total'], u['thinking'], u['complete']), (2601 + 10, 45, True))

    def test_missing_thinking_is_unknown_never_zero(self):
        ev = B.evaluate(0, False, 1000, envelope(thinking=None))
        self.assertIsNone(ev['usage']['thinking'])
        self.assertTrue(ev['usage']['complete'])
        one_missing = {'modelUsage': {
            'a': {'inputTokens': 1, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0, 'outputTokens': 1,
                  'thinkingTokens': 3},
            'b': {'inputTokens': 1, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0, 'outputTokens': 1}}}
        self.assertIsNone(B.model_usage(one_missing)['thinking'])
        self.assertEqual(B.evaluate(0, False, 1, envelope(thinking=0))['usage']['thinking'], 0)

    def test_missing_counters_are_incomplete_and_never_substituted(self):
        for env in (B.fixture_envelope(GOOD, usage=False), {'modelUsage': {}}, {'modelUsage': {'m': {'inputTokens': 1}}},
                    {'modelUsage': {'m': {'inputTokens': True, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0,
                                          'outputTokens': 1}}},
                    {'modelUsage': {'m': {'inputTokens': -1, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0,
                                          'outputTokens': 1}}}):
            u = B.model_usage(env)
            self.assertFalse(u['complete'])
            self.assertIsNone(u['total'])
        env = B.fixture_envelope(GOOD, usage=False)
        env['usage'] = {'input_tokens': 5, 'output_tokens': 5}  # the CLI's last-turn usage must not fill the gap
        self.assertIsNone(B.model_usage(env)['total'])

    def test_failure_modes_are_separated(self):
        self.assertEqual(B.evaluate(None, True, 300000, b'')['outcome'], 'deadline')
        self.assertEqual(B.evaluate(1, False, 10, b'Error')['outcome'], 'process_failure')
        self.assertEqual(B.evaluate(0, False, 10, b'not json')['outcome'], 'process_failure')
        self.assertEqual(B.evaluate(0, False, 10, envelope(is_error=True))['outcome'], 'process_failure')
        self.assertEqual(B.evaluate(0, False, 10, envelope('prose'))['outcome'], 'wire_rejected')
        self.assertEqual(B.evaluate(0, False, 10, envelope())['outcome'], 'correct')
        late = B.evaluate(0, False, 300001, envelope())
        self.assertFalse(late['on_time'])
        self.assertFalse(late['entirely_correct'])

    def test_route_identity(self):
        self.assertEqual(B.evaluate(0, False, 1, envelope())['route'], 'ok')
        self.assertEqual(B.evaluate(0, False, 1, envelope(model='claude-haiku-4-5'))['route'], 'mismatch')
        self.assertEqual(B.evaluate(0, False, 1, envelope(usage=False))['route'], 'unknown')


class Statistics(unittest.TestCase):
    def test_fisher_known_values(self):
        self.assertAlmostEqual(B.fisher_two_sided(6, 6, 0, 6), 2 / 924)
        self.assertAlmostEqual(B.fisher_two_sided(3, 6, 3, 6), 1.0)
        self.assertAlmostEqual(B.fisher_two_sided(6, 6, 2, 6), 0.0606, places=4)
        self.assertAlmostEqual(B.fisher_two_sided(5, 6, 2, 6), 0.2424, places=4)
        self.assertAlmostEqual(B.fisher_two_sided(0, 6, 6, 6), B.fisher_two_sided(6, 6, 0, 6))


class Runs(Harness):
    def test_full_run_is_the_frozen_schedule_with_unique_ids_and_raw_evidence(self):
        analysis = self.full('all')
        store = B.Store(self.tmp / 'all')
        events, problems = store.events()
        self.assertEqual(problems, [])
        launches = [e for e in events if e['event'] == 'launch']
        self.assertEqual([e['arm'] for e in launches], list('ABCBCACABACBCBABAC'))
        self.assertEqual(len({e['call_id'] for e in launches}), 18)
        for e in launches:
            self.assertEqual(e['prompt_sha256'], self.record['arms'][e['arm']]['prompt_sha256'])
            self.assertEqual(e['system_sha256'], B.SYSTEM_SHA)
        for slot in B.schedule():
            cdir = store.call_dir(slot)
            for name in ('request.json', 'envelope.json', 'stderr.txt', 'meta.json'):
                self.assertTrue((cdir / name).exists(), (cdir, name))
        self.assertEqual(analysis['problems'], [])
        self.assertEqual(analysis['decision']['verdict'], 'not_reproduced')

    def test_resume_never_repeats_a_finished_slot(self):
        outcome, runner = self.go('r', {})
        self.assertEqual(len(runner.calls), 18)
        again, runner2 = self.go('r', {})
        self.assertEqual((again['launched'], len(runner2.calls)), (0, 0))

    def test_wrong_expect_digest_launches_nothing(self):
        runner_called = []
        with self.assertRaises(B.ProbeError):
            B.run(self.tmp / 'x', '0' * 64, lambda *a: runner_called.append(1), record=self.record)
        self.assertEqual(runner_called, [])
        self.assertFalse((self.tmp / 'x' / 'ledger.jsonl').exists())

    def test_preflight_failure_launches_nothing(self):
        called = []
        with self.assertRaises(B.ProbeError):
            B.run(self.tmp / 'p', self.digest, lambda *a: called.append(1), preflight=lambda: ['CLI differs'],
                  record=self.record)
        self.assertEqual(called, [])

    def test_another_freeze_cannot_reuse_the_evidence_directory(self):
        self.go('d', {})
        other = dict(self.record, plan='other')
        with self.assertRaises(B.ProbeError):
            B.run(self.tmp / 'd', B.freeze_digest(other), lambda *a: None, record=other)

    def test_token_ceiling_stops_admission(self):
        big = B.fixture_envelope(GOOD, tokens=(2, 0, 19900, 98))
        outcome, runner = self.go('ceil', {n: big for n in range(1, 19)})
        self.assertEqual(outcome['launched'], 3)
        self.assertTrue(outcome['stopped'].startswith('token ceiling'))
        self.assertEqual(B.analyze(self.tmp / 'ceil')['spent_admission_tokens'], 60000)

    def test_overrun_is_reported_not_hidden(self):
        huge = B.fixture_envelope(GOOD, tokens=(2, 0, 69900, 98))
        outcome, _ = self.go('over', {1: huge})
        self.assertEqual(outcome['launched'], 1)  # 70,000 spent in one call: stop, and the overrun stays reported
        self.assertTrue(outcome['stopped'].startswith('token ceiling'))
        self.assertEqual(B.analyze(self.tmp / 'over')['arms']['A']['total_tokens_known'], 70000)

    def test_overall_time_cap(self):
        outcome, _ = self.go('t', {}, seconds=2400.0)
        self.assertEqual((outcome['launched'], outcome['stopped']), (3, 'overall time cap reached'))

    def test_missing_usage_halts_until_acknowledged_and_blocks_selection(self):
        outcome, _ = self.go('h', {4: 'missing_usage'})
        self.assertEqual(outcome['launched'], 4)
        again, runner = self.go('h', {})
        self.assertEqual((again['launched'], len(runner.calls)), (0, 0))
        done, _ = self.go('h', {}, ack_halt=True)
        self.assertEqual(done, {'launched': 14, 'stopped': 'schedule complete'})
        analysis = B.analyze(self.tmp / 'h')
        self.assertEqual(analysis['decision']['verdict'], 'incomplete')
        self.assertEqual(analysis['spent_admission_tokens'], 17 * 2601 + 5000)

    def test_failed_calls_count_as_launched_and_are_never_retried(self):
        outcome, runner = self.go('f', {2: 'process_failure'})
        self.assertEqual(outcome['launched'], 2)  # a process failure has no usage: halt
        self.assertEqual(len(runner.calls), 2)
        analysis = B.analyze(self.tmp / 'f')
        self.assertEqual(analysis['launched'], 2)
        self.assertEqual(analysis['arms']['B']['outcomes']['process_failure'], 1)

    def test_route_mismatch_is_terminal(self):
        outcome, _ = self.go('m', {3: 'wrong_model'})
        self.assertEqual(outcome['launched'], 3)
        again, runner = self.go('m', {}, ack_halt=True)
        self.assertEqual((again['launched'], len(runner.calls)), (0, 0))
        self.assertTrue(again['stopped'].startswith('terminal halt'))

    def test_orphaned_launch_is_counted_and_blocks(self):
        store = B.Store(self.tmp / 'o')
        store.append({'event': 'plan', 'digest': self.digest, 'ts': 1.0, 'caps': B.CAPS})
        store.append({'event': 'launch', 'slot': 1, 'arm': 'A', 'block': 1, 'position': 1, 'call_id': 'a', 'ts': 2.0})
        outcome, runner = self.go('o', {})
        self.assertEqual((outcome['launched'], len(runner.calls)), (0, 0))
        self.assertIn('never recorded as finished', outcome['stopped'])
        done, _ = self.go('o', {}, ack_halt=True)
        self.assertEqual(done['launched'], 17)  # slot 1 stays spent and is not retried
        analysis = B.analyze(self.tmp / 'o')
        self.assertEqual(analysis['launched'], 18)
        self.assertEqual(analysis['decision']['verdict'], 'incomplete')

    def test_duplicate_ledger_records_are_integrity_problems(self):
        store = B.Store(self.tmp / 'dup')
        launch = {'event': 'launch', 'slot': 1, 'arm': 'A', 'block': 1, 'position': 1, 'call_id': 'a', 'ts': 2.0}
        store.append({'event': 'plan', 'digest': self.digest, 'ts': 1.0, 'caps': B.CAPS})
        store.append(launch)
        store.append(launch)
        _, problems = store.events()
        self.assertTrue(any('duplicate launch' in p for p in problems), problems)
        with self.assertRaises(B.ProbeError):
            self.go('dup', {})
        store2 = B.Store(self.tmp / 'dup2')
        store2.append({'event': 'end', 'slot': 3, 'call_id': 'z', 'ts': 1.0})
        self.assertTrue(any('without a launch' in p for p in store2.events()[1]))

    def test_report_detects_tampered_evidence(self):
        self.full('tamper')
        path = B.Store(self.tmp / 'tamper').call_dir(B.schedule()[0]) / 'envelope.json'
        path.write_bytes(envelope(GOOD.replace('"classify_C":"inside"', '"classify_C":"outside"')))
        analysis = B.analyze(self.tmp / 'tamper')
        self.assertTrue(analysis['problems'])
        self.assertEqual(analysis['decision']['verdict'], 'incomplete')

    def test_report_on_an_empty_directory(self):
        text = B.write_report(self.tmp / 'empty')
        self.assertIn('Incomplete', text)
        self.assertIn('undefined', text)


class DecisionRule(Harness):
    def verdict(self, name, plan, **kw):
        return self.full(name, plan, **kw)['decision']

    def test_not_reproduced_when_a_has_no_boundary_error(self):
        self.assertEqual(self.verdict('n1', {})['verdict'], 'not_reproduced')
        wire_only = self.failing(A_SLOTS[:4], 'malformed')  # wire failures are not boundary misclassifications
        self.assertEqual(self.verdict('n2', wire_only)['verdict'], 'not_reproduced')

    def test_insufficient_contrast_below_three_failing_a_calls(self):
        d = self.verdict('c1', self.failing(A_SLOTS[:2]))
        self.assertEqual(d['verdict'], 'insufficient_contrast')
        self.assertIsNone(d['candidate'])
        self.assertEqual(self.verdict('c2', self.failing(A_SLOTS[:3]))['verdict'], 'tie')  # floor met, B and C equal

    def test_no_candidate_when_b_and_c_each_fail_once(self):
        plan = {**self.failing(A_SLOTS[:3]), **{B_SLOTS[0]: 'wrong_label', C_SLOTS[0]: 'malformed'}}
        d = self.verdict('x', plan)
        self.assertEqual((d['verdict'], d['candidate']), ('no_candidate', None))

    def test_nominate_prefers_fewer_tokens_then_time(self):
        cheap = B.fixture_envelope(GOOD, tokens=(2, 0, 1000, 61))
        plan = {**self.failing(A_SLOTS[:3]), **{n: cheap for n in B_SLOTS}}
        d = self.verdict('p1', plan)
        self.assertEqual((d['verdict'], d['candidate']), ('nominate', 'B'))
        self.assertIn(B.CLAIM, d['text'])
        plan = {**self.failing(A_SLOTS[:3]), **{n: cheap for n in C_SLOTS}}
        self.assertEqual(self.verdict('p2', plan)['candidate'], 'C')
        d = self.verdict('p3', self.failing(A_SLOTS[:3]))
        self.assertEqual(d['verdict'], 'tie')

    def test_incomplete_arm_gives_no_decision(self):
        outcome, _ = self.go('inc', {}, seconds=2400.0)
        self.assertEqual(outcome['stopped'], 'overall time cap reached')
        d = B.analyze(self.tmp / 'inc')['decision']
        self.assertEqual(d['verdict'], 'incomplete')

    def test_thinking_strata_and_unknowns_are_tabulated(self):
        plan = {**self.failing(A_SLOTS[:3], 'wrong_label'), **{B_SLOTS[0]: 'missing_thinking'}}
        analysis = self.full('think', plan)
        a, b = analysis['arms']['A'], analysis['arms']['B']
        self.assertEqual(a['thinking_strata']['zero']['calls'], 3)
        self.assertEqual(a['thinking_strata']['zero']['boundary_errors'], 3)
        self.assertEqual(a['thinking_strata']['positive']['entirely_correct'], 3)
        self.assertTrue(a['assessable'])
        self.assertEqual(b['thinking_strata']['unknown']['calls'], 1)
        self.assertFalse(b['assessable'])
        text = B.render(analysis)
        for needle in ('Fisher', 'Thinking tokens', 'Cache read', 'Tokens per correct'):
            self.assertIn(needle, text)

    def test_zero_correct_members_gives_undefined_cost(self):
        analysis = self.full('zero', {n: 'malformed' for n in A_SLOTS})
        self.assertIsNone(analysis['arms']['A']['tokens_per_correct_member'])
        self.assertIn('undefined', B.render(analysis))


class CommandLine(Harness):
    def test_freeze_prints_the_digest(self):
        buffer = io.StringIO()
        with patch('sys.stdout', buffer):
            self.assertEqual(B.main(['freeze']), 0)
        self.assertTrue(buffer.getvalue().startswith('digest: ' + self.digest))

    def test_dry_passes_and_never_starts_a_process(self):
        buffer = io.StringIO()
        with patch('sys.stdout', buffer):
            self.assertEqual(B.main(['dry', '--out', str(self.tmp / 'dry')]), 0)
        self.assertIn('DRY OK', buffer.getvalue())
        self.assertNotIn('FAIL', buffer.getvalue())

    def test_run_requires_expect_and_refuses_a_wrong_one(self):
        with self.assertRaises(SystemExit):
            B.main(['run'])
        buffer = io.StringIO()
        with patch('sys.stdout', buffer):
            self.assertEqual(B.main(['run', '--expect', 'abc', '--out', str(self.tmp / 'live')]), 2)
        self.assertIn('REFUSED', buffer.getvalue())
        self.assertFalse((self.tmp / 'live').exists())

    def test_live_runner_uses_the_adapter_argv(self):
        captured = {}

        class Proc:
            returncode, stdout, stderr = 0, b'{}', b''

        def fake(argv, **kw):
            captured.update(argv=argv, **kw)
            return Proc()

        with patch('subprocess.run', fake), patch('shutil.which', lambda _: 'CLAUDE'):
            result = B.live_runner({'system': 'S', 'prompt': 'P'}, 300)
        self.assertEqual(captured['argv'], B.call_argv('S', 'CLAUDE'))
        self.assertEqual((captured['input'], captured['timeout']), (b'P', 300))
        self.assertEqual(result, (0, b'{}', b'', False))

    def test_forbidden_environment_blocks_a_live_run(self):
        with patch.dict('os.environ', {'CLAUDE_CODE_EFFORT_LEVEL': 'high'}), patch('shutil.which', lambda _: None):
            problems = B.preflight_live()
        self.assertTrue(any('CLAUDE_CODE_EFFORT_LEVEL' in p for p in problems))


if __name__ == '__main__':
    unittest.main()
