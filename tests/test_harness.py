import json
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


def stream(result='ok', model_usage=None, is_error=False, spawns=0):
    lines = [{'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Agent', 'id': f't{i}'}
                                                           for i in range(spawns)]}},
             {'type': 'assistant', 'parent_tool_use_id': 'x', 'message': {'content': [{'type': 'tool_use', 'name': 'Agent'}]}},
             {'type': 'result', 'result': result, 'is_error': is_error, 'num_turns': 2,
              'modelUsage': mu() if model_usage is None else model_usage}]
    return 'not json\n' + '\n'.join(json.dumps(l) for l in lines) + '\n'


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
        self.assertEqual((t['thinking_tokens'], t['thinking_unknown']), (2, 1))
        self.assertIsNone(H.tokens(None))

    def test_total_is_inconclusive_with_unknown(self):
        t = H.total([H.usage_of(mu()), None])
        self.assertEqual((t['tokens'], t['calls'], t['calls_without_usage'], t['conclusive']), (20, 2, 1, False))
        self.assertTrue(H.total([H.usage_of(mu())])['conclusive'])


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
        self.assertTrue(self.live(fake_run('garbage'))['failure'].startswith('no result event'))
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
        self.assertIn('without usage', self.ledger(max_tokens=10_000).refusal())

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
    """Terra review 2026-10-27: callers of the harness."""

    def test_pool2_summary_counts_unknown_thinking(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bench' / 'pool'))
        import pool2
        calls = [{'usage': H.usage_of(mu(thinkingTokens=None))}, {'usage': H.usage_of(mu())}]
        out = pool2.summarize('P', calls, {'j': ('yes', 1.0)}, {'a': 0.0}, {'a': [('j', 'q')]}, {'j': 'yes'})
        self.assertEqual((out['thinking_tokens'], out['thinking_unknown'], out['tokens']), (2, 1, 40))
        out = pool2.summarize('P', calls + [{'usage': None}], {'j': ('yes', 1.0)}, {'a': 0.0}, {'a': [('j', 'q')]}, {'j': 'yes'})
        self.assertEqual((out['tokens'], out['tokens_known_calls_only'], out['calls_without_usage']), (None, 40, 1))

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
