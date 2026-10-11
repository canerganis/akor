"""OZ/6 reply-lane validation and Worker retry integration."""
import json
import unittest

from oz import Error
from oz_runtime import Inbox
from oz_reply import encode_lanes, reply_contract, validate_lanes
from oz_worker import Worker, loads
from test_oz2 import extended


class ReplyCodecTests(unittest.TestCase):
    def test_contract_binds_the_receipt_and_explicit_status_rule(self):
        contract = reply_contract('0123456789abcdef')
        self.assertIn('0123456789abcdef', contract)
        self.assertIn('No missing status implies success', contract)
        self.assertIn('delivered order', contract)
        for receipt in ('ABCDEF0123456789', '0123456789abcde', '0123456789abcdef0', ''):
            with self.subTest(receipt=receipt), self.assertRaises(Error):
                reply_contract(receipt)

    def test_validate_shared_and_mixed_statuses_preserving_exact_text(self):
        ids = ('short', 'longer_id')
        exact = '  12.50 ± 0.02 mm\r\nmethod unknown.  '
        shared = validate_lanes({'q': '0123456789abcdef', 's': 0, 'v': [exact, 'failed? no']},
                                ids, '0123456789abcdef')
        self.assertEqual(shared['results'], [['short', 0, exact], ['longer_id', 0, 'failed? no']])
        mixed = validate_lanes({'q': '0123456789abcdef', 's': [0, 1], 'v': ['done', 'retry']},
                               ids, '0123456789abcdef')
        self.assertEqual(mixed['results'], [['short', 0, 'done'], ['longer_id', 1, 'retry']])

    def test_encode_canonicalizes_rows_to_trusted_request_order(self):
        rows = {'results': [['b', 1, '  retry\nverbatim  '], ['a', 0, 'done']]}
        encoded = encode_lanes(rows, ('a', 'b'), 'fedcba9876543210')
        self.assertEqual(encoded, {'q': 'fedcba9876543210', 's': [0, 1],
                                   'v': ['done', '  retry\nverbatim  ']})
        self.assertEqual(encode_lanes({'results': [['b', 0, 'B'], ['a', 0, 'A']]},
                                      ('a', 'b'), 'fedcba9876543210')['s'], 0)

    def test_encode_rejects_unknown_missing_duplicate_or_invalid_rows(self):
        ids, receipt = ('a', 'b'), '0123456789abcdef'
        cases = [
            {'results': [['alien', 0, 'unexpected']]},
            {'results': [['a', 0, 'partial']]},
            {'results': [['a', 0, 'first'], ['a', 0, 'duplicate']]},
            {'results': [['a', True, 'boolean status'], ['b', 0, 'valid']]},
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(Error):
                encode_lanes(value, ids, receipt)
        with self.assertRaises(Error):
            encode_lanes({'results': [['a', 0, 'ok']]}, ('bad id',), receipt)

    def test_malformed_lanes_are_rejected(self):
        ids, receipt = ('a', 'b'), '0123456789abcdef'
        cases = [
            {'q': '0123456789abcdee', 's': 0, 'v': ['a', 'b']},
            {'q': receipt, 's': 0, 'v': ['a']},
            {'q': receipt, 's': [0], 'v': ['a', 'b']},
            {'q': receipt, 's': [0, True], 'v': ['a', 'b']},
            {'q': receipt, 's': True, 'v': ['a', 'b']},
            {'q': receipt, 's': 3, 'v': ['a', 'b']},
            {'q': receipt, 's': 0, 'v': ['a', ' ']},
            {'q': receipt, 's': 0, 'v': ['a', 5]},
            {'q': receipt, 's': 0, 'v': ['a', 'b'], 'extra': 1},
            {'s': 0, 'v': ['a', 'b']},
            {'q': receipt, 's': float('nan'), 'v': ['a', 'b']},
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(Error):
                validate_lanes(value, ids, receipt)
        with self.assertRaises(Error):
            validate_lanes({'q': receipt, 's': 0, 'v': ['a', 'b']}, ('a', 'a'), receipt)
        with self.assertRaises(Error):
            validate_lanes({'q': receipt, 's': 0, 'v': ['a', 'b']}, ('a', 'b'), 'bad-receipt')
        for source in ('{"q":"0123456789abcdef","s":0,"v":["a","b"],"q":"0123456789abcdef"}',
                       '{"q":"0123456789abcdef","s":NaN,"v":["a","b"]}'):
            with self.subTest(source=source), self.assertRaises(Error):
                loads(source)

    def test_extra_usage_is_validated_by_legacy_usage_contract(self):
        ids, receipt = ('a',), '0123456789abcdef'
        valid = validate_lanes({'q': receipt, 's': 0, 'v': ['done'],
                                 'usage': {'output_tokens': 8}}, ids, receipt)
        self.assertEqual(valid['usage'], {'output_tokens': 8})
        for usage in ({'output_tokens': True}, {'secret': 1}, {'input_tokens': -1}):
            with self.subTest(usage=usage), self.assertRaises(Error):
                validate_lanes({'q': receipt, 's': 0, 'v': ['done'], 'usage': usage}, ids, receipt)


class LaneWorkerTests(unittest.TestCase):
    def setUp(self):
        self.ch = extended()
        self.now = [100.0]
        self.box = Inbox(clock=lambda: self.now[0])
        self.addCleanup(self.box.close)

    def post(self, mid, *, after=()):
        self.box.post(self.ch, mid, 'V', binding=self.ch.binding, after=after)

    def worker(self, adapter, **kwargs):
        return Worker(self.box, self.ch, adapter, counters=[len], max_tokens=10000,
                      retry_delay=5, **kwargs)

    def test_default_mode_remains_rows(self):
        self.post('one')
        seen = []
        worker = self.worker(lambda r: seen.append(r) or {'results': [['one', 0, 'done']]})
        self.assertEqual(worker.run_once()['status'], 'received')
        self.assertEqual(seen[0]['protocol'], 'oz.adapter/1')
        self.assertNotIn('receipt', seen[0])
        self.assertEqual(seen[0]['prompt'].count('Reply only JSON'), 1)

    def test_lanes_request_receipt_is_charged_and_reply_is_normalized(self):
        self.post('one')
        seen = []
        def adapter(request):
            seen.append(request)
            self.assertEqual(request['protocol'], 'oz.adapter/2')
            self.assertEqual(request['reply_mode'], 'lanes')
            self.assertIn(request['receipt'], request['prompt'])
            self.assertIn('No missing status implies success', request['prompt'])
            self.assertEqual(request['estimated_input_tokens'], [len(request['prompt'])])
            return {'q': request['receipt'], 's': 0, 'v': ['  exact result\r\n']}
        report = self.worker(adapter, reply_mode='lanes').run_once()
        self.assertEqual(report['status'], 'received')
        self.assertEqual(self.box.inspect('one')['result'], '  exact result\r\n')
        self.assertEqual(len(seen[0]['receipt']), 16)

    def test_wrong_receipt_or_partial_result_retries_all_and_keeps_dependants_locked(self):
        for bad_reply in ('wrong_q', 'partial'):
            with self.subTest(bad_reply=bad_reply):
                self.post('first')
                self.post('sibling')
                self.post('dependent', after=('first',))
                def adapter(request):
                    ids = request['ids']
                    q = 'ffffffffffffffff' if bad_reply == 'wrong_q' else request['receipt']
                    values = ['result'] if bad_reply == 'partial' else ['result'] * len(ids)
                    return {'q': q, 's': 0, 'v': values}
                result = self.worker(adapter, reply_mode='lanes', batch_size=2).run_once()
                self.assertEqual(result['status'], 'adapter_error')
                self.assertEqual(set(result['outcomes'].values()), {'retry'})
                self.assertEqual(self.box.inspect('first')['state'], 'pending')
                self.assertEqual(self.box.inspect('sibling')['state'], 'pending')
                self.assertEqual(self.box.inspect('dependent')['attempts'], 0)
                # Separate fresh inbox per subtest to avoid carrying pending rows.
                if bad_reply == 'wrong_q':
                    self.box.close()
                    self.box = Inbox(clock=lambda: self.now[0])
                    self.addCleanup(self.box.close)

    def test_mixed_statuses_retry_only_retryable_jobs_and_attempt_gets_new_receipt(self):
        for mid in ('first', 'retryme', 'third'):
            self.post(mid)
        calls = []
        def adapter(request):
            calls.append(request)
            if len(calls) == 1:
                return {'q': request['receipt'], 's': [0, 1, 0],
                        'v': ['done one', 'temporary', 'done three']}
            return {'q': request['receipt'], 's': 0, 'v': ['eventual success']}
        worker = self.worker(adapter, reply_mode='lanes', batch_size=3)
        first = worker.run_once()
        self.assertEqual(first['outcomes'], {'first': 'ok', 'retryme': 'retry', 'third': 'ok'})
        self.assertEqual(self.box.inspect('first')['attempts'], 1)
        self.assertEqual(self.box.inspect('third')['attempts'], 1)
        self.assertEqual(self.box.inspect('retryme')['attempts'], 1)
        self.assertEqual(worker.run_once()['status'], 'idle')
        self.now[0] += 5
        second = worker.run_once()
        self.assertEqual(second['ids'], ['retryme'])
        self.assertEqual(self.box.inspect('retryme')['attempts'], 2)
        self.assertNotEqual(calls[0]['receipt'], calls[1]['receipt'])
        self.assertEqual(self.box.inspect('first')['result'], 'done one')
        self.assertEqual(self.box.inspect('third')['result'], 'done three')


if __name__ == '__main__':
    unittest.main()
