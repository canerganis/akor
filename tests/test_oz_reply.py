"""OZ/8 lanes replies, receipts, usage, negotiation and Worker retry integration."""
import json
import unittest

from oz import Error
from oz_batch import REPLY_CONTRACT
from oz_reply import (check_capabilities, encode_reply, validate_reply, validate_response, validate_usage)
from oz_runtime import Inbox
from oz_worker import Worker
from test_oz2 import extended

Q = '0123456789abcdef'
CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/8']}


class ReplyCodecTests(unittest.TestCase):
    def test_lanes_preserve_exact_text_and_statuses(self):
        ids = ('short', 'longer_id')
        exact = '  12.50 ± 0.02 mm\r\nmethod unknown.  '
        shared = validate_reply({'q': Q, 's': 0, 'v': [exact, 'failed? no']}, ids, Q)
        self.assertEqual(shared, {'short': ('ok', exact), 'longer_id': ('ok', 'failed? no')})
        mixed = validate_reply({'q': Q, 's': [0, 2], 'v': ['done', 'never']}, ids, Q)
        self.assertEqual(mixed, {'short': ('ok', 'done'), 'longer_id': ('failed', 'never')})
        self.assertEqual(validate_reply({'q': Q, 's': [1, 0], 'v': ['a', 'b']}, ids, Q)['short'], ('retry', 'a'))

    def test_reply_is_positional_v_i_answers_ids_i(self):
        ids = ('zeta', 'alpha', 'mid')
        outcomes = validate_reply({'q': Q, 's': [0, 1, 2], 'v': ['first', 'second', 'third']}, ids, Q)
        self.assertEqual(list(outcomes), ['zeta', 'alpha', 'mid'])
        self.assertEqual(outcomes, {'zeta': ('ok', 'first'), 'alpha': ('retry', 'second'),
                                    'mid': ('failed', 'third')})
        swapped = validate_reply({'q': Q, 's': 0, 'v': ['first', 'second', 'third']}, ('mid', 'zeta', 'alpha'), Q)
        self.assertEqual(swapped['mid'], ('ok', 'first'))
        self.assertEqual(swapped['alpha'], ('ok', 'third'))
        # Result text never carries IDs; a reply that names IDs instead of lanes is not accepted.
        with self.assertRaises(Error):
            validate_reply({'q': Q, 'results': [['zeta', 0, 'x'], ['alpha', 0, 'y'], ['mid', 0, 'z']]}, ids, Q)

    def test_encode_reply_round_trips_in_request_order(self):
        outcomes = {'a': ('ok', 'A'), 'b': ('retry', '  B\n')}
        reply = encode_reply(outcomes, ('a', 'b'), Q)
        self.assertEqual(reply, {'q': Q, 's': [0, 1], 'v': ['A', '  B\n']})
        self.assertEqual(validate_reply(reply, ('a', 'b'), Q), outcomes)
        reordered = encode_reply(outcomes, ('b', 'a'), Q)
        self.assertEqual(reordered['v'], ['  B\n', 'A'])
        self.assertEqual(validate_reply(reordered, ('b', 'a'), Q), outcomes)
        uniform = encode_reply({'a': ('ok', 'A'), 'b': ('ok', 'B')}, ('a', 'b'), Q)
        self.assertEqual(uniform['s'], 0)
        self.assertEqual(list(uniform), ['q', 's', 'v'])

    def test_whole_reply_is_rejected_on_any_defect(self):
        ids = ('a', 'b')
        cases = [None, [], {}, 'text', {'q': Q, 's': 0, 'v': ['x']}, {'q': Q, 's': 0, 'v': ['x', 'y', 'z']},
                 {'q': Q, 's': [0], 'v': ['x', 'y']}, {'q': Q, 's': True, 'v': ['x', 'y']},
                 {'q': Q, 's': [0, True], 'v': ['x', 'y']}, {'q': Q, 's': 3, 'v': ['x', 'y']},
                 {'q': Q, 's': -1, 'v': ['x', 'y']}, {'q': Q, 's': '0', 'v': ['x', 'y']},
                 {'q': Q, 's': 0, 'v': ['x', '']}, {'q': Q, 's': 0, 'v': ['x', '  \n']},
                 {'q': Q, 's': 0, 'v': ['x', 3]}, {'q': Q, 's': 0, 'v': 'xy'},
                 {'q': Q, 's': 0, 'v': ['x', 'y' * 65537]}, {'q': Q, 's': 0, 'v': ['x', '\ud800']},
                 {'q': 'ffffffffffffffff', 's': 0, 'v': ['x', 'y']}, {'q': Q.upper(), 's': 0, 'v': ['x', 'y']},
                 {'s': 0, 'v': ['x', 'y']}, {'q': Q, 'v': ['x', 'y']}, {'q': Q, 's': 0},
                 {'q': Q, 's': 0, 'v': ['x', 'y'], 'extra': 1},
                 {'q': Q, 'results': [['a', 0, 'x'], ['b', 0, 'y']]}]
        for value in cases:
            with self.subTest(value=str(value)[:60]), self.assertRaises(Error):
                validate_reply(value, ids, Q)

    def test_usage_subsets_are_checked_never_summed_and_missing_stays_unknown(self):
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
        reply = {'q': Q, 's': 0, 'v': ['x']}
        self.assertEqual(validate_response({'reply': reply}, ('a',), Q), ({'a': ('ok', 'x')}, {}))
        outcomes, usage = validate_response({'reply': reply, 'usage': {'input_tokens': 9}}, ('a',), Q)
        self.assertEqual((outcomes, usage), ({'a': ('ok', 'x')}, {'input_tokens': 9}))
        for bad in [None, reply, {}, {'reply': reply, 'secret': 1}, {'reply': reply, 'usage': {'input_tokens': -1}},
                    {'reply': {'q': Q, 'results': [['a', 0, 'x']]}}]:
            with self.subTest(bad=str(bad)[:60]), self.assertRaises(Error):
                validate_response(bad, ('a',), Q)

    def test_capabilities_require_exactly_protocols_and_languages(self):
        self.assertEqual(check_capabilities(CAPS), CAPS)
        both = {'protocols': ['oz.adapter/2', 'oz.adapter/3'], 'languages': ['OZ/7', 'OZ/8']}
        self.assertEqual(check_capabilities(both), both)
        for caps in [None, [], {}, {'protocols': ['oz.adapter/3']}, {'languages': ['OZ/8']},
                     dict(CAPS, reply_modes=['lanes']), dict(CAPS, extra=[]),
                     dict(CAPS, protocols=['oz.adapter/2']), dict(CAPS, languages=['OZ/7']),
                     dict(CAPS, languages=['OZ/6']), dict(CAPS, protocols=[]), dict(CAPS, languages='OZ/8'),
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

    def test_request_has_exactly_the_oz_adapter_3_fields(self):
        self.post('one')
        seen = []
        def adapter(request):
            seen.append(request)
            return {'reply': {'q': request['receipt'], 's': 0, 'v': ['done']}}
        result = self.worker(adapter).run_once()
        self.assertEqual(result['status'], 'received')
        request = seen[0]
        self.assertEqual(set(request), {'protocol', 'language', 'binding', 'receipt', 'ids', 'attempts',
                                        'prompt', 'prompt_tokens'})
        self.assertEqual(request['attempts'], [1])
        self.assertEqual(request['ids'], ['one'])
        self.assertEqual((request['protocol'], request['language']), ('oz.adapter/3', 'OZ/8'))
        self.assertEqual(request['binding'], self.ch.binding)
        self.assertNotIn('attempts', request['prompt'])
        self.assertNotIn('one', request['prompt'].split('\nDATA ')[1])
        self.assertIn(REPLY_CONTRACT, request['prompt'])
        self.assertIn('"q":"' + request['receipt'] + '"', request['prompt'])
        self.assertEqual(request['prompt_tokens'], [len(request['prompt'])])
        self.assertEqual((result['language'], result['mode']), ('OZ/8', 'frames'))

    def test_reply_is_validated_against_the_charged_receipt(self):
        self.post('one')
        def adapter(request):
            self.assertIn(REPLY_CONTRACT, request['prompt'])
            return {'reply': {'q': request['receipt'], 's': 0, 'v': ['  exact result\r\n']},
                    'usage': {'input_tokens': 900, 'cached_input_tokens': 800, 'output_tokens': 12}}
        report = self.worker(adapter).run_once()
        self.assertEqual(report['status'], 'received')
        self.assertEqual(report['verification'], 'unverified')
        self.assertEqual(self.box.inspect('one')['result'], '  exact result\r\n')
        self.assertEqual(self.box.runs()[0]['report']['usage']['cached_input_tokens'], 800)

    def test_positional_reply_maps_results_to_the_delivered_ids(self):
        for mid in ('first', 'second', 'third'):
            self.post(mid)
        def adapter(request):
            self.assertEqual(request['ids'], ['first', 'second', 'third'])
            for mid in request['ids']:
                self.assertNotIn(mid, request['prompt'])
            return {'reply': {'q': request['receipt'], 's': 0, 'v': ['one', 'two', 'three']}}
        self.worker(adapter, batch_size=3).run_once()
        self.assertEqual([self.box.inspect(m)['result'] for m in ('first', 'second', 'third')],
                         ['one', 'two', 'three'])

    def test_missing_or_legacy_capabilities_fail_before_any_claim(self):
        self.post('one')
        calls = []
        for caps in [None, dict(CAPS, reply_modes=['lanes']), {'protocols': ['oz.adapter/3']},
                     dict(CAPS, languages=['OZ/7']), dict(CAPS, protocols=['oz.adapter/2'])]:
            with self.subTest(caps=caps), self.assertRaises(Error):
                self.worker(lambda r: calls.append(r), capabilities=caps)
        self.assertEqual(calls, [])
        self.assertEqual(self.box.inspect('one')['attempts'], 0)

    def test_wrong_receipt_or_partial_result_retries_all_and_keeps_dependants_locked(self):
        for bad_reply in ('wrong_q', 'partial', 'stale_receipt', 'rows_shape'):
            with self.subTest(bad_reply=bad_reply):
                self.box.close()
                self.box = Inbox(clock=lambda: self.now[0])
                self.addCleanup(self.box.close)
                self.post('first')
                self.post('sibling')
                self.post('dependent', after=('first',))
                def adapter(request):
                    ids = request['ids']
                    q = {'wrong_q': 'ffffffffffffffff', 'stale_receipt': '0' * 16}.get(bad_reply, request['receipt'])
                    if bad_reply == 'rows_shape':
                        reply = {'q': q, 'results': [[i, 0, 'result'] for i in ids]}
                    else:
                        values = ['result'] if bad_reply == 'partial' else ['result'] * len(ids)
                        reply = {'q': q, 's': 0, 'v': values}
                    return {'reply': reply, 'usage': {'output_tokens': 7}}
                result = self.worker(adapter, batch_size=2).run_once()
                self.assertEqual(result['status'], 'adapter_error')
                self.assertEqual(result['error_code'], 'adapter_invalid_reply')
                self.assertEqual(result['usage'], {'output_tokens': 7})
                self.assertEqual(set(result['outcomes'].values()), {'retry'})
                self.assertEqual(self.box.inspect('first')['state'], 'pending')
                self.assertEqual(self.box.inspect('sibling')['state'], 'pending')
                self.assertEqual(self.box.inspect('dependent')['attempts'], 0)

    def test_mixed_statuses_retry_only_retryable_jobs_and_attempt_gets_new_receipt(self):
        for mid in ('first', 'retryme', 'third'):
            self.post(mid)
        calls = []
        def adapter(request):
            calls.append(request)
            if len(calls) == 1:
                return {'reply': {'q': request['receipt'], 's': [0, 1, 0],
                                  'v': ['done one', 'temporary', 'done three']}}
            if calls[0]['receipt'] in request['prompt']:
                return {'reply': {'q': calls[0]['receipt'], 's': 0, 'v': ['reused receipt']}}
            return {'reply': {'q': request['receipt'], 's': 0, 'v': ['eventual success']}}
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

    def test_every_attempt_uses_a_fresh_receipt_even_for_identical_jobs(self):
        self.post('one')
        receipts = []
        def adapter(request):
            receipts.append(request['receipt'])
            status = 1 if len(receipts) < 3 else 0
            return {'reply': {'q': request['receipt'], 's': status, 'v': ['x']}}
        worker = self.worker(adapter, retry_delay=0)
        for _ in range(3):
            worker.run_once()
        self.assertEqual(len(set(receipts)), 3)
        self.assertEqual(self.box.inspect('one')['state'], 'done')

    def test_predecessor_result_is_sent_once_and_ids_stay_off_the_prompt(self):
        self.post('first')
        self.post('a', after=['first'])
        self.post('b', after=['first'])
        prompts = []
        def adapter(request):
            prompts.append(request)
            return {'reply': {'q': request['receipt'], 's': 0,
                              'v': ['PREDECESSOR-RESULT' if 'first' in request['ids'] else 'ok'] * len(request['ids'])}}
        worker = self.worker(adapter, batch_size=3)
        worker.run_once()
        worker.run_once()
        second = prompts[1]
        self.assertEqual(second['ids'], ['a', 'b'])
        self.assertEqual(second['prompt'].count('PREDECESSOR-RESULT'), 1)
        data = json.loads(second['prompt'].rsplit('\nDATA ', 1)[1])
        self.assertEqual(list(data), ['j', 'p', 'h', 'q'])
        self.assertEqual(data['p'], [['first', 'PREDECESSOR-RESULT']])
        self.assertEqual(data['h'], [[0, 'first'], [1, 'first']])


if __name__ == '__main__':
    unittest.main()
