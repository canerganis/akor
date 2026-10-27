import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bench import harness as H

M = 'claude-sonnet-5-5'


def mu(model=M, **over):
    e = {'inputTokens': 10, 'cacheReadInputTokens': 5, 'cacheCreationInputTokens': 1, 'outputTokens': 4,
         'thinkingTokens': 2}
    e.update(over)
    return {model: e}


def stream(result='ok', model_usage=None, is_error=False, spawns=0, failed=()):
    lines = [{'type': 'assistant', 'message': {'content': [
                 {'type': 'tool_use', 'name': 'Agent', 'id': f't{i}', 'input': {'prompt': f'job ma_{i + 1:02d}'}}
                 for i in range(spawns)]}},
             {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': f't{i}',
                                                       'is_error': i in failed} for i in range(spawns)]}},
             {'type': 'assistant', 'parent_tool_use_id': 'x', 'message': {'content': [{'type': 'tool_use', 'name': 'Agent'}]}},
             {'type': 'result', 'result': result, 'is_error': is_error, 'num_turns': 2,
              'modelUsage': mu() if model_usage is None else model_usage}]
    return '\n'.join(json.dumps(l) for l in lines) + '\n'


def fake_run(stdout='', returncode=0, raise_timeout=False):
    def run(cmd, **kw):
        run.cmd, run.env = cmd, kw.get('env')
        if raise_timeout:
            raise subprocess.TimeoutExpired(cmd, 1)
        return subprocess.CompletedProcess(cmd, returncode, stdout, '')
    return run


class UsageTest(unittest.TestCase):
    def test_totals_include_cache(self):
        u = H.usage_of(mu())
        self.assertEqual((u['input_tokens'], u['cached_input_tokens'], u['output_tokens']), (16, 5, 4))
        self.assertEqual(H.tokens(u), 20)

    def test_missing_or_malformed_is_none(self):
        self.assertIsNone(H.usage_of(None))
        self.assertIsNone(H.usage_of({}))
        self.assertIsNone(H.usage_of(mu(outputTokens=None)))
        self.assertIsNone(H.usage_of(mu(inputTokens='3')))
        self.assertIsNone(H.usage_of(mu(inputTokens=-5)))
        self.assertIsNone(H.usage_of(mu(inputTokens=True)))

    def test_unknown_thinking_is_none_not_zero(self):
        self.assertIsNone(H.usage_of(mu(thinkingTokens=None))['thinking_tokens'])
        self.assertIsNone(H.usage_of(mu(thinkingTokens='7'))['thinking_tokens'])
        t = H.total([H.usage_of(mu(thinkingTokens=None)), H.usage_of(mu())])
        self.assertEqual((t['thinking_tokens'], t['thinking_unknown'], t['tokens']), (None, 1, 40))
        self.assertIsNone(H.tokens(None))

    def test_total_is_inconclusive_with_unknown(self):
        t = H.total([H.usage_of(mu()), None])
        self.assertEqual((t['tokens'], t['calls'], t['calls_without_usage'], t['conclusive']), (None, 2, 1, False))
        self.assertEqual((t['input_tokens'], t['output_tokens'], t['tokens_known_calls_only']), (None, None, 20))
        self.assertTrue(H.total([H.usage_of(mu())])['conclusive'])
        e = H.total([])
        self.assertEqual((e['tokens'], e['conclusive']), (None, False))  # no calls is not zero tokens


class CallTest(unittest.TestCase):
    def live(self, run):
        with mock.patch.object(H.subprocess, 'run', run):
            return H.call('sys', 'prompt', model=M, kind='live', tools='Agent')

    def test_ok_counts_top_level_spawns_and_pins_subagents(self):
        run = fake_run(stream(spawns=3))
        c = self.live(run)
        self.assertIsNone(c['failure'])
        self.assertEqual((c['text'], c['spawns'], c['turns']), ('ok', 3, 2))
        self.assertEqual(run.env['CLAUDE_CODE_SUBAGENT_MODEL'], M)
        self.assertEqual(run.env['CLAUDE_CODE_SUBAGENT_MODEL_FORCE'], '1')
        self.assertIn('--model', run.cmd)

    def test_delegations_carry_input_and_result_status(self):
        c = self.live(fake_run(stream(spawns=2, failed={1})))
        self.assertEqual([(d['id'], d['ok']) for d in c['delegations']], [('t0', True), ('t1', False)])
        self.assertEqual(c['delegations'][0]['input'], {'prompt': 'job ma_01'})

    def test_unreadable_or_conflicting_stream_fails(self):
        self.assertTrue(self.live(fake_run('not json\n' + stream()))['failure'].startswith('1 unreadable'))
        two = stream(is_error=True, model_usage=mu('claude-haiku-5-5')) + stream()
        c = self.live(fake_run(two))
        self.assertTrue(c['failure'].startswith('2 result events'))
        self.assertEqual(c['text'], '')

    def test_spawns_are_unique_tool_ids(self):
        ev = {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Agent', 'id': 'a'}]}}
        out = '\n'.join(json.dumps(e) for e in (ev, ev, json.loads(stream().strip().split('\n')[-1])))
        self.assertEqual(self.live(fake_run(out))['spawns'], 1)

    def test_split_on_lf_only(self):
        # The CLI may write U+2028 and U+0085 raw inside a JSON string; splitlines() would cut the event there.
        raw = json.dumps({'type': 'result', 'result': 'a\u2028b\u0085c', 'is_error': False, 'modelUsage': mu()},
                         ensure_ascii=False)
        c = self.live(fake_run(raw + '\n'))
        self.assertIsNone(c['failure'])
        self.assertEqual(c['text'], 'a\u2028b\u0085c')

    def test_other_model_fails(self):
        c = self.live(fake_run(stream(model_usage={**mu(), **mu('claude-haiku-5-5')})))
        self.assertTrue(c['failure'].startswith('unexpected model'))
        self.assertEqual(c['text'], '')
        self.assertIsNotNone(c['usage'])  # tokens were still spent and stay countable

    def test_failures(self):
        self.assertEqual(self.live(fake_run(raise_timeout=True))['failure'], 'timeout')
        self.assertIsNone(self.live(fake_run(raise_timeout=True))['usage'])
        self.assertTrue(self.live(fake_run(''))['failure'].startswith('0 result events'))
        self.assertEqual(self.live(fake_run(stream(), returncode=1))['failure'], 'exit 1')
        self.assertEqual(self.live(fake_run(stream(is_error=True)))['failure'], 'is_error')
        c = self.live(fake_run(stream(model_usage={})))
        self.assertIsNotNone(c['failure'])
        self.assertIsNone(c['usage'])

        def boom(cmd, **kw):
            raise OSError('claude not found')
        c = self.live(boom)
        self.assertTrue(c['failure'].startswith('OSError'))
        self.assertEqual(c['text'], '')

    def test_timeout_keeps_partial_evidence(self):
        def run(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 1, output=b'partial line')
        c = self.live(run)
        self.assertEqual((c['failure'], c['raw'], c['usage']), ('timeout', 'partial line', None))

    def test_fixture_and_bad_kind(self):
        c = H.call('s', 'p' * 40, model=M, fixture=lambda: 'abcd')
        self.assertEqual((c['text'], c['failure']), ('abcd', None))
        self.assertEqual(c['usage']['output_tokens'], 1)
        with self.assertRaises(ValueError):
            H.call('s', 'p', model=M, kind='other')


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / 'ledger.sqlite'

    def tearDown(self):
        self.dir.cleanup()

    def ledger(self, **kw):
        return H.Ledger(self.path, **{'max_launches': 3, 'max_tokens': 100, 'reserve': 30, **kw})

    def test_inflight_reserve(self):
        L = self.ledger()
        ids = [L.reserve() for _ in range(4)]
        self.assertEqual(sum(i is not None for i in ids), 3)  # 3 * 30 <= 100, the fourth does not fit
        self.assertEqual(L.state()['in_flight'], 3)

    def test_tokens_shared_between_instances(self):
        a, b = self.ledger(max_launches=10), self.ledger(max_launches=10)
        a.charge(a.reserve(), H.usage_of(mu(inputTokens=74)))  # 80 + 4 = 84 tokens
        self.assertIsNone(b.reserve())  # 84 + 30 > 100, seen by the other instance
        self.assertEqual(b.state()['tokens'], 84)

    def test_unknown_usage_stops_everything(self):
        L = self.ledger(max_launches=10, max_tokens=10_000)
        L.charge(L.reserve(), None)
        self.assertIsNone(L.reserve())
        self.assertIn('without usage', self.ledger(max_launches=10, max_tokens=10_000).refusal())

    def test_policy_is_stored_and_enforced(self):
        self.ledger()
        with self.assertRaises(ValueError):
            self.ledger(reserve=10)  # another client cannot count reservations differently
        with self.assertRaises(ValueError):
            self.ledger(max_launches=99)
        self.ledger()  # same policy opens fine

    def test_stale_reservation_counts_as_unknown(self):
        L = self.ledger(max_launches=10, max_tokens=10_000, stale_after=0.05)
        L.reserve()  # its process "dies" and never settles
        time.sleep(0.1)
        s = L.state()
        self.assertEqual((s['stale_unsettled'], s['calls_without_usage']), (1, 1))
        self.assertIsNone(L.reserve())

    def test_double_settle_and_unknown_id_raise(self):
        L = self.ledger()
        rid = L.reserve()
        L.charge(rid, None)
        with self.assertRaises(RuntimeError):
            L.charge(rid, None)
        with self.assertRaises(RuntimeError):
            L.charge('nope', None)

    def test_overshoot_is_reported(self):
        L = self.ledger(max_launches=10)
        L.charge(L.reserve(), H.usage_of(mu(inputTokens=500)))
        self.assertEqual(L.state()['overshoot'], 506 + 4 - 100)

    def test_run_charged_settles_even_when_fn_raises(self):
        L = self.ledger(max_tokens=10_000)
        with self.assertRaises(KeyError):
            H.run_charged(L, lambda: {}['x'])
        self.assertEqual(L.state()['calls_without_usage'], 1)
        self.assertIsNone(H.run_charged(L, lambda: {'usage': None}))  # stopped by the unknown call

    def test_threads_never_overshoot_launches(self):
        L = self.ledger(max_launches=5, max_tokens=10**9, reserve=1)
        got = []
        ts = [threading.Thread(target=lambda: got.append(L.reserve() is not None)) for _ in range(30)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sum(got), 5)

    def test_processes_never_overshoot_launches(self):
        code = ('import sys; sys.path.insert(0, sys.argv[2]); from bench import harness as H; '
                'L = H.Ledger(sys.argv[1], max_launches=6, max_tokens=10**9, reserve=1); '
                'print(sum(L.reserve() is not None for _ in range(5)))')
        root = str(Path(__file__).resolve().parent.parent)
        procs = [subprocess.Popen([sys.executable, '-c', code, str(self.path), root], stdout=subprocess.PIPE, text=True)
                 for _ in range(4)]
        self.assertEqual(sum(int(p.communicate()[0]) for p in procs), 6)


class CallerTest(unittest.TestCase):
    """Callers of the harness (reviews 2026-10-27)."""

    def test_pool2_summary_counts_unknown_thinking(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bench' / 'pool'))
        import pool2
        calls = [{'usage': H.usage_of(mu(thinkingTokens=None)), 'ended': 2.0}, {'usage': H.usage_of(mu()), 'ended': 3.0}]
        args = ({'j': ('yes', 1.0)}, {'a': 0.0}, {'a': [('j', 'q')]}, {'j': 'yes'})
        out = pool2.summarize('P', calls, *args)
        self.assertEqual((out['thinking_tokens'], out['thinking_unknown'], out['tokens']), (None, 1, 40))
        self.assertEqual((out['makespan_seconds'], out['run_seconds']), (3.0, 3.0))  # every attempt counts
        out = pool2.summarize('P', calls + [{'usage': None, 'ended': 4.0}], *args)
        self.assertEqual((out['tokens'], out['input_tokens'], out['tokens_known_calls_only'], out['calls_without_usage']),
                         (None, None, 40, 1))

    def test_pool2_refused_or_unanswered_publishes_no_tokens(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bench' / 'pool'))
        import pool2
        ok = [{'usage': H.usage_of(mu()), 'ended': 1.0}]
        out = pool2.summarize('P', ok + [{'refused': True, 'usage': None}], {'j': ('yes', 1.0)}, {'a': 0.0},
                              {'a': [('j', 'q')]}, {'j': 'yes'})
        self.assertEqual((out['tokens'], out['complete'], out['refused_launches']), (None, False, 1))
        out = pool2.summarize('P', ok, {}, {'a': 0.0}, {'a': [('j', 'q')]}, {'j': 'yes'})
        self.assertEqual((out['tokens'], out['makespan_seconds'], out['run_seconds']), (None, None, 1.0))
        self.assertEqual(pool2.summarize('P', [], {}, {'a': 0.0}, {'a': [('j', 'q')]}, {'j': 'yes'})['tokens'], None)

    def report(self, rows, man, ledger_launches=None):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bench' / 'live'))
        import pilot2_report as R
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'pilot2_sonnet.jsonl'
            f.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
            f.with_suffix('.manifest.json').write_text(json.dumps(man), encoding='utf-8')
            if ledger_launches is not None:
                L = H.Ledger(f.with_suffix('.ledger.sqlite'), max_launches=99, max_tokens=10**9, reserve=1)
                for _ in range(ledger_launches):
                    L.charge(L.reserve(), H.usage_of(mu()))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                R.main([f])
        return {l.split('|')[2].strip(): [c.strip() for c in l.split('|')[1:-1]] for l in out.getvalue().splitlines()[2:]}

    def row(self, arm, part=0, **kw):
        r = {'seed': 1, 'arm': arm, 'part': part, 'manifest': 'x', 'in': 90, 'out': 10, 'in_uncached': 90,
             'cache_read': 0, 'cache_write': 0, 'model': M, 'valid': True, 'jobs': 2 if arm in 'HS' else 1,
             'jobs_passed': 2 if arm in 'HS' else 1, 'wall_s': 1.0, 'api_ms': 900}
        r.update(kw)
        return r

    def test_report_withholds_figures_for_unclean_cells(self):
        man = {'sha256': 'x', 'n': 2, 'model': M, 'schedule': [[1, 'H'], [1, 'S'], [1, 'P']]}
        rows = [self.row('H'), self.row('H', manifest='old', **{'in': 5000}),  # an older run in the same file
                self.row('S', spawns=2, delegation_ok=False), self.row('P', 0), self.row('P', 1, model='')]
        t = self.report(rows, man)
        h, s, p = t['OZ/1g, one call'], t['one subagent per job'], t['plain JSON, one call per job']
        self.assertEqual((h[5], h[7]), ('100', '50.0'))  # the old run is ignored, not summed
        self.assertIn('another run ignored', h[-1])
        self.assertEqual((s[7], s[11]), ('n/a', 'n/a'))
        self.assertIn('without proven', s[-1])
        self.assertEqual((p[7], p[11]), ('n/a', 'n/a'))  # an empty model is not the pinned model
        rows = [self.row('H'), self.row('S', delegation_ok=True), self.row('P', 0), self.row('P', 1)]
        t = self.report(rows, man)
        self.assertEqual(t['plain JSON, one call per job'][11], '2.0')
        self.assertEqual(t['one subagent per job'][11], '1.0')
        t = self.report(rows, man, ledger_launches=5)  # a paid launch never written
        self.assertEqual(t['OZ/1g, one call'][7], 'n/a')
        self.assertIn('without a record', t['OZ/1g, one call'][-1])
        t = self.report([self.row('H', **{'in': -80})] + rows[1:], man)
        self.assertEqual(t['OZ/1g, one call'][5], 'n/a')  # a negative counter is not usage

    def test_pilot2_delegation_must_cover_each_job_once(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bench' / 'live'))
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {'OUT': str(Path(d) / 'p.jsonl')}):
            import pilot2
            d1 = lambda i, ok=True: {'id': f't{i}', 'ok': ok, 'input': {'prompt': f'do ma_{i:02d}'}}
            self.assertTrue(pilot2.delegation_ok([d1(1), d1(2)], 2))
            self.assertFalse(pilot2.delegation_ok([d1(1), d1(1)], 2))  # same job twice
            self.assertFalse(pilot2.delegation_ok([d1(1), d1(2, ok=False)], 2))  # a failed subagent
            self.assertFalse(pilot2.delegation_ok([d1(1)], 2))
            both = {'id': 't', 'ok': True, 'input': {'prompt': 'ma_01 and ma_02'}}
            self.assertFalse(pilot2.delegation_ok([both, d1(2)], 2))
            pilot2.LEDGER = None

    def test_report_coverage_with_other_manifest(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bench' / 'live'))
        import pilot2_report as R
        man = {'sha256': 'x', 'n': 2, 'schedule': [[1, 'H'], [1, 'P']]}
        rows = [{'seed': 1, 'arm': 'H', 'part': 0, 'manifest': 'x'},
                {'seed': 1, 'arm': 'P', 'part': 0, 'manifest': 'x'}, {'seed': 1, 'arm': 'P', 'part': 1, 'manifest': 'old'}]
        ok = R.coverage(rows, man)
        self.assertEqual((ok['H'], ok['P']), (True, False))
        rows[2]['manifest'] = 'x'
        self.assertTrue(R.coverage(rows, man)['P'])
        self.assertFalse(R.coverage(rows + [rows[2]], man)['P'])  # duplicate part

    def test_run_live_needs_an_experiment_ledger(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bench' / 'live'))
        import run_live
        env = {k: v for k, v in os.environ.items() if k != 'LIVE_LEDGER'}
        with mock.patch.dict(os.environ, env, clear=True):
            run_live._LEDGER.clear()
            with self.assertRaises(SystemExit):
                run_live.call('hi')

    def test_codex_failed_turn_and_missing_cache(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bench' / 'live'))
        import run_live
        msg = {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'hi'}}
        done = {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'output_tokens': 10}}
        out = lambda *ev: subprocess.CompletedProcess([], 0, '\n'.join(json.dumps(e) for e in ev), '')
        with mock.patch.object(run_live.subprocess, 'run', lambda *a, **k: out(msg, done)), \
                mock.patch.object(run_live.shutil, 'which', lambda _: 'codex'):
            r = run_live.call_codex('p', 'm')
        self.assertEqual((r['is_error'], r['cache_read'], r['in_uncached'], r['model']), (False, None, None, None))
        with mock.patch.object(run_live.subprocess, 'run', lambda *a, **k: out(msg, done, {'type': 'turn.failed'})), \
                mock.patch.object(run_live.shutil, 'which', lambda _: 'codex'):
            r = run_live.call_codex('p', 'm')
        self.assertEqual((r['is_error'], r['in']), (True, None))

    def test_run_live_stops_when_ledger_refuses(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bench' / 'live'))
        import run_live
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(run_live.os.environ, {
                'LIVE_LEDGER': str(Path(d) / 'l.sqlite'), 'LIVE_MAX_LAUNCHES': '0', 'MODEL': 'sonnet'}):
            run_live._LEDGER.clear()
            try:
                with self.assertRaises(SystemExit):
                    run_live.call('hi')
            finally:
                run_live._LEDGER.clear()


if __name__ == '__main__':
    unittest.main()
