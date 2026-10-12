import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from oz import Error
from oz_runtime import Inbox
from oz_batch import SYSTEM
from oz_reply import validate_response
from oz_worker import AdapterError, StdioAdapter, Worker, loads, process_host
from test_oz2 import extended

CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}


def items(request):
    """Number of model jobs (j items) in the request body."""
    return len(json.loads(request['prompt'])['j'])


def reply(request, texts, failed=()):
    """Adapter response: raw JSONL text, one line per position; indexes in `failed` become failure lines."""
    lines = [json.dumps([i, None, text] if i in failed else [i, text], ensure_ascii=False)
             for i, text in enumerate(texts)]
    return {'reply': chr(10).join(lines)}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.ch = extended()
        self.now = [100.0]
        self.box = Inbox(clock=lambda: self.now[0])
        self.addCleanup(self.box.close)

    def post(self, mid='one', wire='V', **kwargs):
        self.box.post(self.ch, mid, wire, binding=self.ch.binding, **kwargs)

    def worker(self, adapter, **kwargs):
        return Worker(self.box, self.ch, adapter, counters=[len], max_tokens=10000,
                      capabilities=CAPS, **kwargs)

    def test_callable_adapter_receives_measured_prompt_and_exact_ids(self):
        self.post('one')
        self.post('two', 'r13')
        seen = []
        def adapter(request):
            seen.append(request)
            return dict(reply(request, ['12.50 ± 0.02 mm; method unknown.'] * items(request)),
                        usage={'input_tokens': 500, 'output_tokens': 30, 'cached_input_tokens': 100})
        result = self.worker(adapter).run_once()
        self.assertEqual(result['status'], 'received')
        self.assertEqual(result['language'], 'OZ/9')
        self.assertEqual(result['prompt_tokens'], seen[0]['prompt_tokens'])
        self.assertEqual(seen[0]['prompt_tokens'], [len(seen[0]['system']) + 1 + len(seen[0]['prompt'])])
        self.assertEqual(seen[0]['ids'], ['one', 'two'])
        self.assertEqual(seen[0]['system'], SYSTEM)
        self.assertEqual(json.loads(seen[0]['prompt'])['j'], ['read 7', 'audit 7', 'test 14', 'read 13'])
        self.assertNotIn('q', json.loads(seen[0]['prompt']))
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.box.stats(), {'done': 2})
        text = '12.50 ± 0.02 mm; method unknown.'
        self.assertEqual(self.box.inspect('one')['result'],
                         json.dumps({'results': [text] * 3}, ensure_ascii=False, separators=(',', ':')))
        self.assertEqual(self.box.inspect('two')['result'], text)
        self.assertEqual(self.box.runs()[0]['report']['usage']['input_tokens'], 500)
        self.assertEqual(self.worker(adapter).run_once()['status'], 'idle')
        self.assertEqual(len(seen), 1)

    def test_failed_adapter_call_retries_whole_batch_and_settled_jobs_are_not_repeated(self):
        self.post('one')
        self.post('two')
        calls = []
        def adapter(request):
            calls.append(request)
            if len(calls) == 1:
                raise RuntimeError('temporary')
            return reply(request, ['done'] * items(request))
        worker = self.worker(adapter, retry_delay=5)
        worker.run_once()
        self.assertEqual(worker.run_once()['status'], 'idle')
        self.now[0] += 5
        worker.run_once()
        self.assertEqual([c['ids'] for c in calls], [['one', 'two'], ['one', 'two']])
        self.assertNotEqual(calls[0]['receipt'], calls[1]['receipt'])
        self.assertEqual(self.worker(adapter).run_once()['status'], 'idle')
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.box.inspect('one')['attempts'], 2)
        self.assertEqual(self.box.inspect('two')['attempts'], 2)

    def test_model_reported_failure_is_final_and_siblings_are_not_repeated(self):
        self.post('one', 'r13')
        self.post('two')
        calls = []
        def adapter(request):
            calls.append(request['ids'])
            return reply(request, ['done', 'done', 'cannot do this', 'done'], failed=[2])
        worker = self.worker(adapter, retry_delay=5)
        worker.run_once()
        self.now[0] += 60
        self.assertEqual(worker.run_once()['status'], 'idle')
        self.assertEqual(calls, [['one', 'two']])
        self.assertEqual(self.box.inspect('one')['state'], 'done')
        self.assertEqual(self.box.inspect('two')['state'], 'failed')
        self.assertEqual(self.box.inspect('two')['error'], '1: cannot do this')
        self.assertEqual(self.box.inspect('two')['attempts'], 1)

    def test_invalid_response_never_unlocks_dependencies(self):
        self.post('one')
        self.post('two', after=['one'])
        result = self.worker(lambda r: {'reply': 'no result lines here'}).run_once()
        self.assertEqual(result['status'], 'adapter_error')
        self.assertEqual(self.box.inspect('one')['state'], 'pending')
        self.assertEqual(self.box.inspect('two')['attempts'], 0)

    def test_provider_exception_details_are_not_persisted(self):
        self.post()
        def adapter(_):
            raise RuntimeError('SECRET-FAKE-TOKEN-MUST-NOT-BE-LOGGED')
        result = self.worker(adapter).run_once()
        combined = json.dumps([result, self.box.runs(), self.box.history('one'), self.box.inspect('one')])
        self.assertNotIn('SECRET-FAKE', combined)
        self.assertEqual(result['error_type'], 'RuntimeError')
        self.assertEqual(str(AdapterError('SECRET-FAKE-TOKEN-MUST-NOT-BE-LOGGED')), 'adapter_failure')

    def test_permanent_outcome_requires_explicit_requeue(self):
        self.post(wire='r13')
        self.worker(lambda r: reply(r, ['unsupported request'], failed=[0])).run_once()
        self.assertEqual(self.box.inspect('one')['state'], 'failed')
        self.assertEqual(self.worker(lambda r: r).run_once()['status'], 'idle')
        self.box.requeue('one')
        self.assertEqual(self.box.inspect('one')['state'], 'pending')

    def test_host_recording_never_calls_adapter_or_executes_stop(self):
        self.post('notice', '+8.')
        self.post('stop', '/')
        result = process_host(self.box, self.ch)
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['adapter_calls'], 0)
        self.assertIn('recorded_only', self.box.inspect('stop')['result'])
        self.assertEqual(self.box.stats(), {'done': 2})

    def test_strict_json_rejects_duplicate_keys_and_nonfinite_values(self):
        for text in ['{"v":[],"v":[]}', '{"usage":NaN}', '{"usage":Infinity}']:
            with self.subTest(text=text), self.assertRaises(Error):
                loads(text)

    def test_invalid_responses_and_usage_are_rejected(self):
        good = '[0,"x"]'
        job_map = (('one', 0),)
        cases = [None, {}, {'reply': {'results': ['x']}}, {'reply': ['0123456789abcdef', 'x']},
                 {'reply': 5}, {'reply': None},
                 {'reply': good, 'usage': {'input_tokens': -1}},
                 {'reply': good, 'usage': {'output_tokens': True}},
                 {'reply': good, 'secret': 'ignored?'}, good]
        grouped, usage = validate_response({'reply': good}, job_map)
        self.assertEqual((grouped.outcomes, usage), ({'one': ('ok', 'x')}, {}))
        grouped, _ = validate_response({'reply': '[0,null,"why"]'}, job_map)
        self.assertEqual(grouped.outcomes, {'one': ('failed', 'why')})
        for value in cases:
            with self.subTest(value=value), self.assertRaises(Error):
                validate_response(value, job_map)

    def test_stdio_adapter_real_process_round_trip_and_unicode(self):
        script = ('import json,sys; r=json.load(sys.stdin); '
                  'json.dump({"reply":json.dumps([0,"12.50 ± 0.02 mm"],ensure_ascii=False)},sys.stdout)')
        adapter = StdioAdapter((sys.executable, '-c', script), timeout=10, capabilities=CAPS)
        self.post(wire='r13')
        result = self.worker(adapter, timeout=10).run_once()
        self.assertEqual(result['status'], 'received')
        self.assertEqual(self.box.inspect('one')['result'], '12.50 ± 0.02 mm')

    def test_stdio_adapter_receives_oz9_request_without_ids_in_prompt(self):
        script = ('import json,sys; r=json.load(sys.stdin); '
                  'json.dump({"reply":json.dumps([0,json.dumps(r)])},sys.stdout)')
        adapter = StdioAdapter((sys.executable, '-c', script), timeout=10, capabilities=CAPS)
        self.post('secret_job', 'r13')
        self.worker(adapter, timeout=10).run_once()
        request = json.loads(self.box.inspect('secret_job')['result'])
        self.assertEqual(set(request), {'protocol', 'language', 'binding', 'receipt', 'ids', 'attempts',
                                        'system', 'prompt', 'prompt_tokens'})
        self.assertEqual((request['protocol'], request['language'], request['ids']),
                         ('oz.adapter/3', 'OZ/9', ['secret_job']))
        self.assertEqual(request['system'], SYSTEM)
        self.assertEqual(json.loads(request['prompt'])['j'], ['read 13'])
        self.assertNotIn('secret_job', request['prompt'] + request['system'])

    def test_stdio_does_not_interpret_shell_metacharacters(self):
        text = 'literal ; | $() & < >'
        script = 'import json,sys; json.dump({"echo":sys.argv[1]},sys.stdout)'
        self.assertEqual(StdioAdapter((sys.executable, '-c', script, text))({}), {'echo': text})

    def test_stdio_stdin_is_utf8(self):
        text = 'Türkçe, 12.50 ± 0.02 mm, 𓂀'
        script = 'import json,sys; r=json.load(sys.stdin); json.dump(r,sys.stdout)'
        self.assertEqual(StdioAdapter((sys.executable, '-c', script))({'text': text}), {'text': text})

    def test_stdio_failure_does_not_expose_stderr(self):
        script = 'import sys; print("SECRET-FAKE",file=sys.stderr); sys.exit(7)'
        with self.assertRaises(Error) as caught:
            StdioAdapter((sys.executable, '-c', script))({})
        self.assertNotIn('SECRET-FAKE', str(caught.exception))
        self.assertIn('7', str(caught.exception))

    def test_stdio_invalid_json_oversized_output_and_timeout(self):
        for adapter in [StdioAdapter((sys.executable, '-c', 'print("not-json")')),
                        StdioAdapter((sys.executable, '-c', 'print("x"*1000)'), max_output_bytes=100)]:
            with self.assertRaises(Error):
                adapter({})
        with self.assertRaises(subprocess.TimeoutExpired):
            StdioAdapter((sys.executable, '-c', 'import time; time.sleep(20)'), timeout=0.1)({})

    def test_bad_adapter_and_worker_limits_are_rejected(self):
        for kwargs in [dict(argv='python command'), dict(argv=()), dict(argv=('python',), timeout=0),
                       dict(argv=('python',), max_output_bytes=0)]:
            with self.assertRaises(Error):
                StdioAdapter(**kwargs)
        with self.assertRaises(Error):
            self.worker(StdioAdapter((sys.executable,)), timeout=1)

    def test_removed_worker_options_are_rejected(self):
        for option in ['reply_mode', 'encoding', 'min_savings']:
            with self.subTest(option=option), self.assertRaises(TypeError):
                self.worker(lambda r: r, **{option: 'x'})

    def _counting_adapter(self, calls):
        def adapter(request):
            calls.append(request)
            return reply(request, ['ok'] * items(request))
        return adapter

    def test_quorum_waits_without_claiming_calling_or_spending_a_receipt(self):
        self.post('one')
        self.post('two')
        calls = []
        worker = self.worker(self._counting_adapter(calls), min_batch=3, max_wait=10)
        receipt = self.box.next_receipt()
        self.assertEqual(worker.run_once(), {'status': 'waiting', 'model_calls': 0})
        self.now[0] += 5
        self.assertEqual(worker.run_once()['status'], 'waiting')
        self.assertEqual(calls, [])
        self.assertEqual(self.box.next_receipt(), receipt)
        for mid in ('one', 'two'):
            self.assertEqual(self.box.inspect(mid)['attempts'], 0)
            self.assertEqual(self.box.inspect(mid)['state'], 'pending')

    def test_quorum_releases_partial_batch_after_max_wait(self):
        self.post('one')
        self.post('two')
        calls = []
        worker = self.worker(self._counting_adapter(calls), min_batch=3, max_wait=10)
        self.assertEqual(worker.run_once()['status'], 'waiting')
        self.now[0] += 10
        self.assertEqual(worker.run_once()['status'], 'received')
        self.assertEqual(len(calls), 1)
        self.assertEqual(sorted(calls[0]['ids']), ['one', 'two'])
        self.assertEqual(self.box.stats(), {'done': 2})

    def test_quorum_met_calls_immediately(self):
        for mid in ('one', 'two', 'three'):
            self.post(mid)
        calls = []
        result = self.worker(self._counting_adapter(calls), min_batch=3, max_wait=10).run_once()
        self.assertEqual(result['status'], 'received')
        self.assertEqual(len(calls), 1)
        self.assertEqual(sorted(calls[0]['ids']), ['one', 'three', 'two'])

    def test_default_min_batch_never_waits(self):
        self.post('one')
        calls = []
        worker = self.worker(self._counting_adapter(calls), max_wait=60)
        self.assertEqual(worker.run_once()['status'], 'received')
        self.assertEqual(len(calls), 1)

    def test_blocked_dependency_does_not_count_toward_quorum(self):
        self.post('one')
        self.post('two')
        self.post('three', after=['one'])
        calls = []
        worker = self.worker(self._counting_adapter(calls), min_batch=3, max_wait=10)
        self.assertEqual(worker.run_once()['status'], 'waiting')
        self.assertEqual(calls, [])
        self.assertEqual(self.box.inspect('three')['attempts'], 0)

    def test_invalid_quorum_values_are_rejected(self):
        cases = [dict(min_batch=0), dict(min_batch=65), dict(min_batch=5, batch_size=4),
                 dict(max_wait=-1), dict(min_batch=True), dict(max_wait='5'), dict(max_wait=86401),
                 dict(min_batch=2.0)]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(Error):
                self.worker(lambda r: r, **kwargs)

    def test_context_policy_full_sends_every_reference(self):
        self.post('one', 'r13')
        prompts = []
        def adapter(request):
            prompts.append(request['prompt'])
            return reply(request, ['ok'])
        self.worker(adapter, context_policy='full').run_once()
        self.assertIn('Use 5 seconds per attempt', prompts[0])
        self.post('two', 'r13')
        self.worker(adapter).run_once()
        self.assertNotIn('Use 5 seconds per attempt', prompts[1])


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.ch = extended()
        self.now = [100.0]
        self.box = Inbox(clock=lambda: self.now[0])
        self.addCleanup(self.box.close)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'calls.jsonl'

    def post(self, mid='one', wire='V', **kwargs):
        self.box.post(self.ch, mid, wire, binding=self.ch.binding, **kwargs)

    def worker(self, adapter, **kwargs):
        kwargs.setdefault('ledger_path', self.path)
        return Worker(self.box, self.ch, adapter, counters=[len], max_tokens=10000,
                      capabilities=CAPS, **kwargs)

    def lines(self):
        return [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()]

    def test_call_start_and_call_end_are_linked_and_complete(self):
        self.post('one')
        self.post('two', 'r13')
        seen = []
        def adapter(request):
            seen.append(request)
            return reply(request, ['ok'] * items(request))
        result = self.worker(adapter, tokenizer='len').run_once()
        start, end = self.lines()
        self.assertEqual((start['event'], end['event']), ('call_start', 'call_end'))
        self.assertEqual(start['call_id'], end['call_id'])
        self.assertEqual(start['call_id'], result['call_id'])
        self.assertRegex(start['call_id'], '^[0-9a-f]{32}$')
        self.assertEqual(list(start), list(end))
        self.assertEqual(end['schema'], 'akor.call/1')
        self.assertEqual(end['batch_id'], seen[0]['receipt'])
        self.assertEqual(end['channel_binding'], self.ch.binding)
        self.assertEqual(end['attempt'], 1)
        self.assertIsNone(end['retry_of'])
        self.assertEqual(end['job_map'], [{'inbox_job_id': 'one', 'expanded_atom_index': 0},
                                          {'inbox_job_id': 'one', 'expanded_atom_index': 1},
                                          {'inbox_job_id': 'one', 'expanded_atom_index': 2},
                                          {'inbox_job_id': 'two', 'expanded_atom_index': 0}])
        sha = lambda text: hashlib.sha256(text.encode('utf-8')).hexdigest()
        request = seen[0]
        self.assertEqual(end['system_sha256'], sha(request['system']))
        self.assertEqual(end['prompt_sha256'], sha(request['prompt']))
        self.assertEqual(end['submitted_sha256'], sha(request['system'] + '\n' + request['prompt']))
        self.assertEqual(end['system_bytes'], len(request['system'].encode('utf-8')))
        self.assertEqual(end['prompt_bytes'], len(request['prompt'].encode('utf-8')))
        self.assertEqual(end['submitted_bytes'], end['system_bytes'] + 1 + end['prompt_bytes'])
        self.assertEqual(end['token_estimates']['tokenizer'], 'len')
        self.assertEqual(end['token_estimates']['system'], len(request['system']))
        self.assertEqual(end['token_estimates']['submitted'], request['prompt_tokens'][0])
        self.assertEqual(end['outcome'], 'ok')
        self.assertEqual(end['validation'], dict(expected_results=4, received_results=4,
                                                 accepted_results=4, failed_results=0, violations=[]))
        self.assertIsNotNone(end['started_at'])
        self.assertIsNotNone(end['ended_at'])
        self.assertIsInstance(end['elapsed_ms'], int)
        self.assertIsNotNone(end['response_sha256'])
        self.assertGreater(end['response_bytes'], 0)
        self.assertGreater(end['token_estimates']['response'], 0)
        # Start has nothing about the end yet.
        for key in ('ended_at', 'elapsed_ms', 'response_sha256', 'response_bytes', 'outcome', 'validation'):
            self.assertIsNone(start[key])
        self.assertIsNotNone(start['started_at'])

    def test_unknown_usage_cost_and_model_are_null_never_zero(self):
        self.post('one', 'r13')
        self.worker(lambda r: reply(r, ['ok'])).run_once()
        end = self.lines()[-1]
        self.assertEqual(end['usage'], dict.fromkeys(['source', 'scope', 'raw', 'input_tokens', 'output_tokens',
                                                      'cache_read_tokens', 'cache_write_tokens',
                                                      'reasoning_tokens', 'total_tokens']))
        self.assertEqual(end['reported_cost'], dict.fromkeys(['amount', 'currency', 'source', 'scope']))
        self.assertEqual(end['billed_cost'], dict.fromkeys(['amount', 'currency', 'source']))
        for key in ('model_requested', 'model_reported', 'run_id', 'exit_code'):
            self.assertIsNone(end[key])
        self.assertIsNone(end['token_estimates']['tokenizer'])
        self.assertIs(end['timed_out'], False)

    def test_provider_usage_is_mapped(self):
        self.post('one', 'r13')
        usage = {'input_tokens': 500, 'cached_input_tokens': 100, 'cache_creation_input_tokens': 20,
                 'output_tokens': 30, 'reasoning_output_tokens': 10}
        self.worker(lambda r: dict(reply(r, ['ok']), usage=usage)).run_once()
        end = self.lines()[-1]['usage']
        self.assertEqual((end['source'], end['scope'], end['raw']), ('adapter', 'call', usage))
        self.assertEqual((end['input_tokens'], end['output_tokens'], end['cache_read_tokens'],
                          end['cache_write_tokens'], end['reasoning_tokens'], end['total_tokens']),
                         (500, 30, 100, 20, 10, None))
        self.post('two', 'r13')
        self.worker(lambda r: dict(reply(r, ['ok']), usage={'output_tokens': 4})).run_once()
        partial = self.lines()[-1]['usage']
        self.assertEqual((partial['output_tokens'], partial['input_tokens'], partial['cache_read_tokens']),
                         (4, None, None))

    def test_invalid_response_outcome_keeps_validation_counts(self):
        self.post('one')
        self.worker(lambda r: {'reply': '[0,"a"]' + chr(10) + 'prose' + chr(10) + '[1,"b"'},
                    retry_delay=0).run_once()
        end = self.lines()[-1]
        # One accepted item of three: the job retries as a whole, nothing else changes.
        self.assertEqual(end['outcome'], 'invalid_response')
        self.assertEqual(end['validation'], dict(
            expected_results=3, received_results=1, accepted_results=1, failed_results=0,
            violations=[{'line': 2, 'reason': 'not a single JSON value'},
                        {'line': 3, 'reason': 'not a single JSON value'}]))
        self.assertEqual(end['error'], 'adapter_invalid_reply (Error)')
        self.assertEqual(self.box.inspect('one')['state'], 'pending')

    def test_reply_without_any_valid_line_keeps_counts_and_violations(self):
        self.post('one')
        self.worker(lambda r: {'reply': '{"results":["a","b","c"]}'}, retry_delay=0).run_once()
        end = self.lines()[-1]
        self.assertEqual(end['outcome'], 'invalid_response')
        self.assertEqual(end['validation'], dict(
            expected_results=3, received_results=0, accepted_results=0, failed_results=0,
            violations=[{'line': 1, 'reason': 'not a JSON array'}]))
        self.assertEqual(end['error'], 'adapter_invalid_reply (Error)')

    def test_violations_are_capped_at_twenty(self):
        self.post('one', 'r13')
        text = chr(10).join(['[0,"ok"]'] + ['prose'] * 30)
        self.worker(lambda r: {'reply': text}).run_once()
        end = self.lines()[-1]
        self.assertEqual(end['outcome'], 'ok')
        self.assertEqual(len(end['validation']['violations']), 20)
        self.assertEqual(end['validation']['violations'][0]['line'], 2)

    def test_job_error_outcome_counts_failed_items(self):
        self.post('one')
        self.worker(lambda r: reply(r, ['a', 'b', 'c'], failed=[1])).run_once()
        end = self.lines()[-1]
        self.assertEqual(end['outcome'], 'job_error')
        self.assertEqual(end['validation'], dict(expected_results=3, received_results=3,
                                                 accepted_results=3, failed_results=1, violations=[]))
        self.assertIsNone(end['error'])

    def test_process_error_timeout_and_spawn_error_outcomes(self):
        self.post('one', 'r13', max_attempts=10)
        def broken(_):
            raise RuntimeError('SECRET-FAKE-TOKEN')
        def slow(_):
            raise subprocess.TimeoutExpired('adapter', 1)
        worker = self.worker(broken, retry_delay=0)
        worker.run_once()
        worker.adapter = slow
        worker.run_once()
        bad = StdioAdapter((sys.executable, '-c', 'import sys; sys.exit(7)'), capabilities=CAPS)
        self.worker(bad, retry_delay=0).run_once()
        missing = StdioAdapter(('definitely-not-an-installed-program-xyz',), capabilities=CAPS)
        self.worker(missing, retry_delay=0).run_once()
        ends = [x for x in self.lines() if x['event'] == 'call_end']
        self.assertEqual([x['outcome'] for x in ends], ['process_error', 'timeout', 'process_error', 'spawn_error'])
        self.assertEqual([x['timed_out'] for x in ends], [False, True, False, False])
        self.assertEqual([x['exit_code'] for x in ends], [None, None, 7, None])
        self.assertNotIn('SECRET-FAKE', self.path.read_text(encoding='utf-8'))
        for x in ends:
            self.assertEqual(x['validation']['received_results'], None)

    def test_retry_links_to_the_previous_call(self):
        self.post('one', 'r13')
        calls = []
        def adapter(request):
            calls.append(request)
            if len(calls) == 1:
                raise RuntimeError('temporary')
            return reply(request, ['ok'])
        worker = self.worker(adapter, retry_delay=0)
        worker.run_once()
        worker.run_once()
        first, second = [x for x in self.lines() if x['event'] == 'call_end']
        self.assertIsNone(first['retry_of'])
        self.assertEqual(second['retry_of'], first['call_id'])
        self.assertEqual((first['attempt'], second['attempt']), (1, 2))
        self.assertNotEqual(first['call_id'], second['call_id'])
        self.assertEqual(len(self.lines()), 4)

    def test_no_ledger_path_writes_nothing_and_idle_waiting_calls_are_not_logged(self):
        self.post('one', 'r13')
        self.worker(lambda r: reply(r, ['ok']), ledger_path=None).run_once()
        self.assertFalse(self.path.exists())
        self.assertEqual(self.worker(lambda r: r).run_once()['status'], 'idle')
        self.assertFalse(self.path.exists())

    def test_ledger_is_append_only_across_workers(self):
        self.post('one', 'r13')
        self.post('two', 'r13')
        self.worker(lambda r: reply(r, ['ok']), batch_size=1).run_once()
        self.worker(lambda r: reply(r, ['ok']), batch_size=1).run_once()
        events = [x['event'] for x in self.lines()]
        self.assertEqual(events, ['call_start', 'call_end', 'call_start', 'call_end'])

    def test_unwritable_ledger_does_not_lose_the_result(self):
        self.post('one', 'r13')
        result = self.worker(lambda r: reply(r, ['ok']), ledger_path=self.path.parent).run_once()
        self.assertEqual(result['ledger_error'], 'write_failed')
        self.assertEqual(self.box.inspect('one')['state'], 'done')


if __name__ == '__main__':
    unittest.main()
