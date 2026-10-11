"""OZ/7 replies, receipts, usage, negotiation and Worker retry integration."""
import unittest

from oz import Error
from oz_batch import REPLY_CONTRACTS
from oz_reply import (check_capabilities, encode_reply, resolve_reply_mode, validate_reply,
                      validate_response, validate_usage)
from oz_runtime import Inbox
from oz_worker import Worker
from test_oz2 import extended

Q = '0123456789abcdef'
CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/7'], 'reply_modes': ['rows', 'lanes']}


class ReplyCodecTests(unittest.TestCase):
    def test_rows_and_lanes_preserve_exact_text_and_statuses(self):
        ids = ('short', 'longer_id')
        exact = '  12.50 ± 0.02 mm\r\nmethod unknown.  '
        rows = validate_reply({'q': Q, 'results': [['longer_id', 1, 'retry'], ['short', 0, exact]]}, ids, Q, 'rows')
        self.assertEqual(rows, {'short': ('ok', exact), 'longer_id': ('retry', 'retry')})
        shared = validate_reply({'q': Q, 's': 0, 'v': [exact, 'failed? no']}, ids, Q, 'lanes')
        self.assertEqual(shared, {'short': ('ok', exact), 'longer_id': ('ok', 'failed? no')})
        mixed = validate_reply({'q': Q, 's': [0, 2], 'v': ['done', 'never']}, ids, Q, 'lanes')
        self.assertEqual(mixed['longer_id'], ('failed', 'never'))

    def test_encode_reply_round_trips_in_request_order(self):
        outcomes = {'a': ('ok', 'A'), 'b': ('retry', '  B\n')}
        for mode in ['rows', 'lanes']:
            with self.subTest(mode=mode):
                self.assertEqual(validate_reply(encode_reply(outcomes, ('a', 'b'), Q, mode), ('a', 'b'), Q, mode),
                                 outcomes)
        self.assertEqual(encode_reply({'a': ('ok', 'A'), 'b': ('ok', 'B')}, ('a', 'b'), Q, 'lanes')['s'], 0)

    def test_whole_reply_is_rejected_on_any_defect(self):
        ids = ('a', 'b')
        rows = [None, {}, {'results': [['a', 0, 'x'], ['b', 0, 'y']]},
                {'q': 'ffffffffffffffff', 'results': [['a', 0, 'x'], ['b', 0, 'y']]},
                {'q': Q, 'results': [['a', 0, 'x']]}, {'q': Q, 'results': [['a', 0, 'x'], ['a', 0, 'x']]},
                {'q': Q, 'results': [['a', True, 'x'], ['b', 0, 'y']]}, {'q': Q, 'results': [['a', 0, ' '], ['b', 0, 'y']]},
                {'q': Q, 'results': [['a', 0, 'x'], ['b', 0, 'y'], ['c', 0, 'z']]},
                {'q': Q, 'results': [['a', 0, 'x'], ['b', 0, 'y']], 'extra': 1},
                {'q': Q, 's': 0, 'v': ['x', 'y']}]
        lanes = [{'q': Q, 's': 0, 'v': ['x']}, {'q': Q, 's': [0], 'v': ['x', 'y']}, {'q': Q, 's': True, 'v': ['x', 'y']},
                 {'q': Q, 's': 3, 'v': ['x', 'y']}, {'q': Q, 's': 0, 'v': ['x', '']},
                 {'q': Q, 's': 0, 'v': ['x', 'y' * 65537]}, {'q': Q, 'results': [['a', 0, 'x'], ['b', 0, 'y']]},
                 {'q': Q.upper(), 's': 0, 'v': ['x', 'y']}]
        for mode, cases in [('rows', rows), ('lanes', lanes)]:
            for value in cases:
                with self.subTest(mode=mode, value=str(value)[:60]), self.assertRaises(Error):
                    validate_reply(value, ids, Q, mode)

    def test_reply_auto_uses_the_final_count_and_explicit_modes_win(self):
        self.assertEqual(resolve_reply_mode('auto', 15), 'rows')
        self.assertEqual(resolve_reply_mode('auto', 16), 'lanes')
        self.assertEqual(resolve_reply_mode('rows', 64), 'rows')
        self.assertEqual(resolve_reply_mode('lanes', 1), 'lanes')
        with self.assertRaises(Error):
            resolve_reply_mode('sometimes', 1)

    def test_usage_subsets_are_checked_never_summed_and_missing_stays_unknown(self):
        usage = {'input_tokens': 100, 'cached_input_tokens': 60, 'cache_creation_input_tokens': 40,
                 'output_tokens': 30, 'reasoning_output_tokens': 30}
        self.assertEqual(validate_usage(usage), usage)
        self.assertEqual(validate_usage({'output_tokens': 5}), {'output_tokens': 5})
        for bad in [{'input_tokens': 10, 'cached_input_tokens': 6, 'cache_creation_input_tokens': 5},
                    {'output_tokens': 3, 'reasoning_output_tokens': 4}, {'input_tokens': -1},
                    {'input_tokens': True}, {'total_tokens': 5}, []]:
            with self.subTest(bad=bad), self.assertRaises(Error):
                validate_usage(bad)
        with self.assertRaises(Error):
            validate_response({'q': Q, 'results': [['a', 0, 'x']]}, ('a',), Q, 'rows')

    def test_capabilities_must_cover_every_mode_that_may_be_sent(self):
        self.assertEqual(check_capabilities(CAPS, 'auto'), CAPS)
        rows_only = dict(CAPS, reply_modes=['rows'])
        check_capabilities(rows_only, 'rows')
        for caps, mode in [(rows_only, 'auto'), (rows_only, 'lanes'), (dict(CAPS, protocols=['oz.adapter/2']), 'rows'),
                           (dict(CAPS, languages=['OZ/6']), 'rows'), (None, 'rows'), ({'protocols': []}, 'rows')]:
            with self.subTest(caps=caps, mode=mode), self.assertRaises(Error):
                check_capabilities(caps, mode)


class ReplyWorkerTests(unittest.TestCase):
    def setUp(self):
        self.ch = extended()
        self.now = [100.0]
        self.box = Inbox(clock=lambda: self.now[0])
        self.addCleanup(self.box.close)

    def post(self, mid, *, after=()):
        self.box.post(self.ch, mid, 'V', binding=self.ch.binding, after=after)

    def worker(self, adapter, **kwargs):
        return Worker(self.box, self.ch, adapter, counters=[len], max_tokens=10000,
                      retry_delay=5, capabilities=kwargs.pop('capabilities', CAPS), **kwargs)

    def test_request_has_exactly_the_oz_adapter_3_fields(self):
        self.post('one')
        seen = []
        def adapter(request):
            seen.append(request)
            return {'reply': {'q': request['receipt'], 'results': [['one', 0, 'done']]}}
        self.assertEqual(self.worker(adapter).run_once()['status'], 'received')
        request = seen[0]
        self.assertEqual(set(request), {'protocol', 'language', 'encoding', 'wire_format', 'reply_mode',
                                        'binding', 'receipt', 'ids', 'prompt', 'prompt_tokens'})
        self.assertEqual((request['protocol'], request['language'], request['encoding'], request['wire_format'],
                          request['reply_mode']), ('oz.adapter/3', 'OZ/7', 'off', 'json/tuples', 'rows'))
        self.assertIn(REPLY_CONTRACTS['rows'], request['prompt'])
        self.assertIn('"q":"' + request['receipt'] + '"', request['prompt'])
        self.assertEqual(request['prompt_tokens'], [len(request['prompt'])])

    def test_lanes_reply_is_validated_against_the_charged_receipt(self):
        self.post('one')
        def adapter(request):
            self.assertIn(REPLY_CONTRACTS['lanes'], request['prompt'])
            return {'reply': {'q': request['receipt'], 's': 0, 'v': ['  exact result\r\n']},
                    'usage': {'input_tokens': 900, 'cached_input_tokens': 800, 'output_tokens': 12}}
        report = self.worker(adapter, reply_mode='lanes').run_once()
        self.assertEqual(report['status'], 'received')
        self.assertEqual(report['verification'], 'unverified')
        self.assertEqual(self.box.inspect('one')['result'], '  exact result\r\n')
        self.assertEqual(self.box.runs()[0]['report']['usage']['cached_input_tokens'], 800)

    def test_missing_capabilities_fail_before_any_claim(self):
        self.post('one')
        calls = []
        for caps, mode in [(None, 'rows'), (dict(CAPS, reply_modes=['rows']), 'auto')]:
            with self.subTest(caps=caps), self.assertRaises(Error):
                self.worker(lambda r: calls.append(r), capabilities=caps, reply_mode=mode)
        self.assertEqual(calls, [])
        self.assertEqual(self.box.inspect('one')['attempts'], 0)

    def test_wrong_receipt_or_partial_result_retries_all_and_keeps_dependants_locked(self):
        for bad_reply in ('wrong_q', 'partial', 'stale_receipt'):
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
                    values = ['result'] if bad_reply == 'partial' else ['result'] * len(ids)
                    return {'reply': {'q': q, 's': 0, 'v': values}, 'usage': {'output_tokens': 7}}
                result = self.worker(adapter, reply_mode='lanes', batch_size=2).run_once()
                self.assertEqual(result['status'], 'adapter_error')
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
        worker = self.worker(adapter, reply_mode='lanes', batch_size=3)
        first = worker.run_once()
        self.assertEqual(first['outcomes'], {'first': 'ok', 'retryme': 'retry', 'third': 'ok'})
        self.assertEqual(worker.run_once()['status'], 'idle')
        self.now[0] += 5
        second = worker.run_once()
        self.assertEqual(second['ids'], ['retryme'])
        self.assertEqual(self.box.inspect('retryme')['result'], 'eventual success')
        self.assertNotEqual(calls[0]['receipt'], calls[1]['receipt'])
        self.assertEqual(self.box.inspect('first')['result'], 'done one')


if __name__ == '__main__':
    unittest.main()
