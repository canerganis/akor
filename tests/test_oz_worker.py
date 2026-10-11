import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from oz import Error
from oz_runtime import Inbox
from oz_worker import AdapterError, RESPONSE_CONTRACT, StdioAdapter, Worker, loads, process_host, validate_reply
from test_oz2 import extended


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.ch = extended()
        self.now = [100.0]
        self.box = Inbox(clock=lambda: self.now[0])
        self.addCleanup(self.box.close)

    def post(self, mid='one', wire='V', **kwargs):
        self.box.post(self.ch, mid, wire, binding=self.ch.binding, **kwargs)

    def worker(self, adapter, **kwargs):
        return Worker(self.box, self.ch, adapter, counters=[len], max_tokens=10000, **kwargs)

    def test_callable_adapter_receives_measured_prompt_and_exact_ids(self):
        self.post('one')
        self.post('two', 'r13')
        seen = []
        def adapter(request):
            seen.append(request)
            self.assertEqual(request['estimated_input_tokens'], [len(request['prompt'])])
            self.assertIn(RESPONSE_CONTRACT, request['prompt'])
            return {'results': [[i, 0, '12.50 ± 0.02 mm; method unknown.'] for i in request['ids']],
                    'usage': {'input_tokens': 500, 'output_tokens': 30, 'cached_input_tokens': 100}}
        result = self.worker(adapter).run_once()
        self.assertEqual(result['status'], 'received')
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.box.stats(), {'done': 2})
        self.assertEqual(self.box.inspect('one')['result'], '12.50 ± 0.02 mm; method unknown.')
        self.assertEqual(self.box.runs()[0]['report']['provider_reported_usage']['input_tokens'], 500)
        self.assertEqual(self.worker(adapter).run_once()['status'], 'idle')
        self.assertEqual(len(seen), 1)

    def test_successful_siblings_are_not_retried(self):
        self.post('one')
        self.post('two')
        calls = []
        def adapter(r):
            calls.append(r['ids'])
            if len(calls) == 1:
                return {'results': [['one', 0, 'done'], ['two', 1, 'retry later']]}
            return {'results': [['two', 0, 'done']]}
        worker = self.worker(adapter, retry_delay=5)
        worker.run_once()
        self.assertEqual(worker.run_once()['status'], 'idle')
        self.now[0] += 5
        worker.run_once()
        self.assertEqual(calls, [['one', 'two'], ['two']])
        self.assertEqual(self.box.inspect('one')['attempts'], 1)
        self.assertEqual(self.box.inspect('two')['attempts'], 2)

    def test_invalid_response_never_unlocks_dependencies(self):
        self.post('one')
        self.post('two', after=['one'])
        response = {'results': [['other', 0, 'wrong id']]}
        result = self.worker(lambda r: response).run_once()
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
        self.post()
        worker = self.worker(lambda r: {'results': [['one', 2, 'unsupported request']]})
        worker.run_once()
        self.assertEqual(self.box.inspect('one')['state'], 'failed')
        self.assertEqual(worker.run_once()['status'], 'idle')
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
        for text in ['{"results":[],"results":[]}', '{"usage":NaN}', '{"usage":Infinity}']:
            with self.subTest(text=text), self.assertRaises(Error):
                loads(text)

    def test_invalid_or_partial_replies_and_usage_are_rejected(self):
        cases = [None, {}, {'results': []}, {'results': [['one', True, 'x']]},
                 {'results': [['one', 0, '']]}, {'results': [['one', 0, 'x'], ['one', 0, 'x']]},
                 {'results': [['one', 0, 'x']], 'usage': {'input_tokens': -1}},
                 {'results': [['one', 0, 'x']], 'usage': {'output_tokens': True}},
                 {'results': [['one', 0, 'x']], 'secret': 'ignored?'}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(Error):
                validate_reply(value, ('one',))

    def test_stdio_adapter_real_process_round_trip_and_unicode(self):
        script = ('import json,sys; r=json.load(sys.stdin); '
                  'json.dump({"results":[[i,0,"12.50 ± 0.02 mm"] for i in r["ids"]]},sys.stdout)')
        adapter = StdioAdapter((sys.executable, '-c', script), timeout=10)
        self.post()
        result = self.worker(adapter, timeout=10).run_once()
        self.assertEqual(result['status'], 'received')
        self.assertEqual(self.box.inspect('one')['result'], '12.50 ± 0.02 mm')

    def test_stdio_does_not_interpret_shell_metacharacters(self):
        text = 'literal ; | $() & < >'
        script = 'import json,sys; json.dump({"echo":sys.argv[1]},sys.stdout)'
        self.assertEqual(StdioAdapter((sys.executable, '-c', script, text))({}), {'echo': text})

    def test_stdio_stdin_is_utf8_on_windows_too(self):
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


if __name__ == '__main__':
    unittest.main()
