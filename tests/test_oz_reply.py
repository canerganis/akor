"""OZ/9 positional replies, receipts, usage, negotiation and Worker retry integration."""
import unittest

from oz import Error
from oz_batch import REPLY_CONTRACT
from oz_reply import (check_capabilities, encode_reply, validate_reply, validate_response,
                      validate_usage)
from oz_runtime import Inbox
from oz_worker import Worker
from test_oz2 import extended

Q = '0123456789abcdef'
CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}


class ReplyCodecTests(unittest.TestCase):
    def test_positional_results_preserve_text_and_statuses(self):
        ids = ('short', 'longer_id')
        exact = '  12.50 ± 0.02 mm\r\nmethod unknown.  '
        self.assertEqual(validate_reply([Q, exact, [2, 'failed? no']], ids, Q),
                         {'short': ('ok', exact), 'longer_id': ('failed', 'failed? no')})
        self.assertEqual(validate_reply([Q, [1, 'retry me'], 'done'], ids, Q)['short'],
                         ('retry', 'retry me'))

    def test_reply_is_positional_and_ids_are_host_side(self):
        ids = ('zeta', 'alpha', 'mid')
        outcomes = validate_reply([Q, 'first', [1, 'second'], [2, 'third']], ids, Q)
        self.assertEqual(list(outcomes), list(ids))
        self.assertEqual(outcomes, {'zeta': ('ok', 'first'), 'alpha': ('retry', 'second'),
                                    'mid': ('failed', 'third')})
        with self.assertRaises(Error):
            validate_reply({'q': Q, 'results': [['zeta', 0, 'x']]}, ids, Q)

    def test_encode_reply_round_trips_in_request_order(self):
        outcomes = {'a': ('ok', 'A'), 'b': ('retry', '  B\n')}
        reply = encode_reply(outcomes, ('a', 'b'), Q)
        self.assertEqual(reply, [Q, 'A', [1, '  B\n']])
        self.assertEqual(validate_reply(reply, ('a', 'b'), Q), outcomes)
        reordered = encode_reply(outcomes, ('b', 'a'), Q)
        self.assertEqual(reordered, [Q, [1, '  B\n'], 'A'])
        self.assertEqual(validate_reply(reordered, ('b', 'a'), Q), outcomes)

    def test_whole_reply_is_rejected_on_any_defect(self):
        ids = ('a', 'b')
        cases = [None, [], {}, 'text', [Q], [Q, 'x'], [Q, 'x', 'y', 'z'],
                 ['ffffffffffffffff', 'x', 'y'], [Q, True, 'y'], [Q, [0, 'x'], 'y'],
                 [Q, [True, 'x'], 'y'], [Q, [3, 'x'], 'y'], [Q, [1, '  '], 'y'],
                 [Q, '', 'y'], [Q, 'x', '  \n'], [Q, 'x', 3], [Q, 'x', 'y' * 65537],
                 [Q, 'x', '\ud800'], [Q.upper(), 'x', 'y']]
        for value in cases:
            with self.subTest(value=str(value)[:60]), self.assertRaises(Error):
                validate_reply(value, ids, Q)

    def test_usage_subsets_are_checked_and_missing_stays_unknown(self):
        usage = {'input_tokens': 100, 'cached_input_tokens': 60, 'cache_creation_input_tokens': 40,
                 'output_tokens': 30, 'reasoning_output_tokens': 30}
        self.assertEqual(validate_usage(usage), usage)
        self.assertEqual(validate_usage({'output_tokens': 5}), {'output_tokens': 5})
        self.assertEqual(validate_usage({}), {})
        for bad in [{'input_tokens': 10, 'cached_input_tokens': 6, 'cache_creation_input_tokens': 5},
                    {'output_tokens': 3, 'reasoning_output_tokens': 4}, {'input_tokens': -1},
                    {'input_tokens': True}, {'total_tokens': 5}, []]:
            with self.subTest(bad=bad), self.assertRaises(Error):
                validate_usage(bad)

    def test_validate_response_wraps_reply_and_usage(self):
        reply = [Q, 'x']
        self.assertEqual(validate_response({'reply': reply}, ('a',), Q), ({'a': ('ok', 'x')}, {}))
        self.assertEqual(validate_response({'reply': reply, 'usage': {'input_tokens': 9}}, ('a',), Q),
                         ({'a': ('ok', 'x')}, {'input_tokens': 9}))
        for bad in [None, reply, {}, {'reply': reply, 'secret': 1},
                    {'reply': reply, 'usage': {'input_tokens': -1}},
                    {'reply': {'q': Q}}, {'reply': [Q, 'x', 'y']}]:
            with self.subTest(bad=str(bad)[:60]), self.assertRaises(Error):
                validate_response(bad, ('a',), Q)

    def test_capabilities_require_protocol_and_language_support(self):
        self.assertEqual(check_capabilities(CAPS), CAPS)
        both = {'protocols': ['oz.adapter/2', 'oz.adapter/3'], 'languages': ['OZ/8', 'OZ/9']}
        self.assertEqual(check_capabilities(both), both)
        for caps in [None, [], {}, {'protocols': ['oz.adapter/3']}, {'languages': ['OZ/9']},
                     dict(CAPS, reply_modes=['lanes']), dict(CAPS, extra=[]),
                     dict(CAPS, protocols=['oz.adapter/2']), dict(CAPS, languages=['OZ/8']),
                     dict(CAPS, protocols=[]), dict(CAPS, languages='OZ/9'),
                     dict(CAPS, protocols='oz.adapter/3'), dict(CAPS, languages=[8])]:
            with self.subTest(caps=caps), self.assertRaises(Error):
                check_capabilities(caps)


class ReplyWorkerTests(unittest.TestCase):
    def setUp(self):
        self.ch = extended()
        self.now = [100.0]
        self.box = Inbox(clock=lambda: self.now[0])
        self.addCleanup(self.box.close)

    def post(self, mid, *, after=()):
        self.box.post(self.ch, mid, 'V', binding=self.ch.binding, after=after)

    def worker(self, adapter, **kwargs):
        kwargs.setdefault('retry_delay', 5)
        return Worker(self.box, self.ch, adapter, counters=[len], max_tokens=10000,
                      capabilities=kwargs.pop('capabilities', CAPS), **kwargs)

    def test_worker_request_has_adapter3_fields_and_oz9_packet(self):
        self.post('job_zq7')
        seen = []
        def adapter(request):
            seen.append(request)
            return {'reply': [request['receipt'], 'done']}
        result = self.worker(adapter).run_once()
        request = seen[0]
        self.assertEqual(result['status'], 'received')
        self.assertEqual(set(request), {'protocol', 'language', 'binding', 'receipt', 'ids', 'attempts',
                                        'prompt', 'prompt_tokens'})
        self.assertEqual(request['attempts'], [1])
        self.assertEqual(request['ids'], ['job_zq7'])
        self.assertEqual((request['protocol'], request['language']), ('oz.adapter/3', 'OZ/9'))
        self.assertNotIn('job_zq7', request['prompt'])
        self.assertIn(REPLY_CONTRACT, request['prompt'])
        self.assertIn(request['receipt'], request['prompt'])
        self.assertEqual(request['prompt_tokens'], [len(request['prompt'])])
        self.assertEqual((result['language'], result['mode']), ('OZ/9', result['mode']))

    def test_reply_uses_charged_receipt_and_keeps_exact_result_and_usage(self):
        self.post('one')
        def adapter(request):
            return {'reply': [request['receipt'], '  exact result\r\n'],
                    'usage': {'input_tokens': 900, 'cached_input_tokens': 800, 'output_tokens': 12}}
        report = self.worker(adapter).run_once()
        self.assertEqual(report['status'], 'received')
        self.assertEqual(report['verification'], 'unverified')
        self.assertEqual(self.box.inspect('one')['result'], '  exact result\r\n')
        self.assertEqual(self.box.runs()[0]['report']['usage']['cached_input_tokens'], 800)

    def test_positional_reply_maps_results_to_delivered_ids(self):
        for mid in ('first', 'second', 'third'):
            self.post(mid)
        def adapter(request):
            self.assertEqual(request['ids'], ['first', 'second', 'third'])
            for mid in request['ids']:
                self.assertNotIn(mid, request['prompt'])
            return {'reply': [request['receipt'], 'one', 'two', 'three']}
        self.worker(adapter, batch_size=3).run_once()
        self.assertEqual([self.box.inspect(m)['result'] for m in ('first', 'second', 'third')],
                         ['one', 'two', 'three'])

    def test_missing_or_legacy_capabilities_fail_before_claim(self):
        self.post('one')
        calls = []
        for caps in [None, dict(CAPS, reply_modes=['lanes']), {'protocols': ['oz.adapter/3']},
                     dict(CAPS, languages=['OZ/8']), dict(CAPS, protocols=['oz.adapter/2'])]:
            with self.subTest(caps=caps), self.assertRaises(Error):
                self.worker(lambda r: calls.append(r), capabilities=caps)
        self.assertEqual(calls, [])
        self.assertEqual(self.box.inspect('one')['attempts'], 0)

    def test_invalid_reply_retries_all_and_keeps_dependants_locked(self):
        for bad_reply in ('wrong_q', 'partial', 'object_shape'):
            with self.subTest(bad_reply=bad_reply):
                self.box.close()
                self.box = Inbox(clock=lambda: self.now[0])
                self.addCleanup(self.box.close)
                self.post('first')
                self.post('sibling')
                self.post('dependent', after=('first',))
                def adapter(request):
                    if bad_reply == 'object_shape':
                        reply = {'q': request['receipt'], 'results': []}
                    elif bad_reply == 'wrong_q':
                        reply = ['ffffffffffffffff', 'result', 'result']
                    else:
                        reply = [request['receipt'], 'result']
                    return {'reply': reply, 'usage': {'output_tokens': 7}}
                result = self.worker(adapter, batch_size=2).run_once()
                self.assertEqual(result['status'], 'adapter_error')
                self.assertEqual(result['error_code'], 'adapter_invalid_reply')
                self.assertEqual(result['usage'], {'output_tokens': 7})
                self.assertEqual(set(result['outcomes'].values()), {'retry'})
                self.assertEqual(self.box.inspect('first')['state'], 'pending')
                self.assertEqual(self.box.inspect('sibling')['state'], 'pending')
                self.assertEqual(self.box.inspect('dependent')['attempts'], 0)

    def test_mixed_statuses_retry_only_retryable_jobs_with_fresh_receipt(self):
        for mid in ('first', 'retryme', 'third'):
            self.post(mid)
        calls = []
        def adapter(request):
            calls.append(request)
            if len(calls) == 1:
                return {'reply': [request['receipt'], 'done one', [1, 'temporary'], 'done three']}
            if calls[0]['receipt'] in request['prompt']:
                return {'reply': [calls[0]['receipt'], 'reused receipt']}
            return {'reply': [request['receipt'], 'eventual success']}
        worker = self.worker(adapter, batch_size=3)
        first = worker.run_once()
        self.assertEqual(first['outcomes'], {'first': 'ok', 'retryme': 'retry', 'third': 'ok'})
        self.assertEqual(worker.run_once()['status'], 'idle')
        self.now[0] += 5
        second = worker.run_once()
        self.assertEqual(second['ids'], ['retryme'])
        self.assertEqual(self.box.inspect('retryme')['result'], 'eventual success')
        self.assertNotEqual(calls[0]['receipt'], calls[1]['receipt'])
        self.assertNotIn(calls[0]['receipt'], calls[1]['prompt'])
        self.assertEqual(self.box.inspect('first')['result'], 'done one')

    def test_every_attempt_uses_fresh_receipt(self):
        self.post('one')
        receipts = []
        def adapter(request):
            receipts.append(request['receipt'])
            return {'reply': [request['receipt'], [1, 'retry']] if len(receipts) < 3
                    else [request['receipt'], 'done']}
        worker = self.worker(adapter, retry_delay=0)
        for _ in range(3):
            worker.run_once()
        self.assertEqual(len(set(receipts)), 3)
        self.assertEqual(self.box.inspect('one')['state'], 'done')

    def test_predecessor_result_is_sent_once_and_job_ids_stay_out_of_prompt(self):
        self.post('first')
        self.post('a', after=['first'])
        self.post('b', after=['first'])
        requests = []
        def adapter(request):
            requests.append(request)
            return {'reply': [request['receipt']] + ['PREDECESSOR-RESULT' if 'first' in request['ids']
                                                      else 'ok'] * len(request['ids'])}
        worker = self.worker(adapter, batch_size=3)
        worker.run_once()
        worker.run_once()
        request = requests[1]
        self.assertEqual(request['ids'], ['a', 'b'])
        self.assertEqual(request['prompt'].count('PREDECESSOR-RESULT'), 1)
        body = __import__('json').loads(request['prompt'].splitlines()[-1])
        self.assertEqual(body['p'], [['first', 'PREDECESSOR-RESULT']])
        self.assertEqual(body['h'], [[0, 'first'], [1, 'first']])


if __name__ == '__main__':
    unittest.main()
