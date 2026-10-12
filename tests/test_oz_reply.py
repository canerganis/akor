"""OZ/9 JSON object replies, usage, negotiation and Worker retry integration."""
import json
import unittest

from oz import Error
from oz_batch import SYSTEM
from oz_reply import (check_capabilities, encode_reply, regroup, validate_reply, validate_response,
                      validate_usage)
from oz_runtime import Inbox
from oz_worker import Worker
from test_oz2 import extended

CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}


class ReplyCodecTests(unittest.TestCase):
    def test_results_preserve_text_and_native_values(self):
        ids = ('short', 'longer_id')
        exact = '  12.50 ± 0.02 mm\r\nmethod unknown.  '
        self.assertEqual(validate_reply({'results': [exact, 'done']}, ids),
                         {'short': ('ok', exact), 'longer_id': ('ok', 'done')})
        outcomes = validate_reply({'results': [{'a': [1, 2.5, None], 'b': 'Türkçe'}, 7]}, ids)
        self.assertEqual(outcomes, {'short': ('ok', '{"a":[1,2.5,null],"b":"Türkçe"}'),
                                    'longer_id': ('ok', '7')})

    def test_non_string_results_become_compact_json_text(self):
        ids = ('a', 'b', 'c', 'd', 'e')
        outcomes = validate_reply({'results': [3, [1, 'x'], {'k': 'v'}, None, True]}, ids)
        self.assertEqual([outcomes[i] for i in ids],
                         [('ok', '3'), ('ok', '[1,"x"]'), ('ok', '{"k":"v"}'),
                          ('ok', 'null'), ('ok', 'true')])
        # A string that happens to look like JSON stays the exact string.
        self.assertEqual(validate_reply({'results': ['[1, 2]']}, ('a',)), {'a': ('ok', '[1, 2]')})

    def test_errors_map_marks_failed_jobs_by_index(self):
        ids = ('zeta', 'alpha', 'mid')
        reply = {'results': ['first', None, 'third'], 'errors': {'1': 'no data supplied'}}
        outcomes = validate_reply(reply, ids)
        self.assertEqual(list(outcomes), list(ids))
        self.assertEqual(outcomes, {'zeta': ('ok', 'first'), 'alpha': ('failed', 'no data supplied'),
                                    'mid': ('ok', 'third')})
        both = validate_reply({'results': [None, None], 'errors': {'0': 'a', '1': ' b\n'}}, ('x', 'y'))
        self.assertEqual(both, {'x': ('failed', 'a'), 'y': ('failed', ' b\n')})

    def test_reply_is_positional_and_ids_are_host_side(self):
        with self.assertRaises(Error):
            validate_reply({'results': [['zeta', 0, 'x']], 'q': '0'}, ('zeta', 'alpha'))
        with self.assertRaises(Error):
            validate_reply({'zeta': 'x', 'alpha': 'y'}, ('zeta', 'alpha'))

    def test_encode_reply_round_trips_in_request_order(self):
        outcomes = {'a': ('ok', 'A'), 'b': ('failed', '  B\n')}
        reply = encode_reply(outcomes, ('a', 'b'))
        self.assertEqual(reply, {'results': ['A', None], 'errors': {'1': '  B\n'}})
        self.assertEqual(validate_reply(reply, ('a', 'b')), outcomes)
        reordered = encode_reply(outcomes, ('b', 'a'))
        self.assertEqual(reordered, {'results': [None, 'A'], 'errors': {'0': '  B\n'}})
        self.assertEqual(validate_reply(reordered, ('b', 'a')), outcomes)
        clean = encode_reply({'a': ('ok', 'A')}, ('a',))
        self.assertEqual(clean, {'results': ['A']})
        self.assertEqual(validate_reply(clean, ('a',)), {'a': ('ok', 'A')})
        # Anything that is not ok is reported as a model-side failure.
        self.assertEqual(encode_reply({'a': ('retry', 'later')}, ('a',)),
                         {'results': [None], 'errors': {'0': 'later'}})

    def test_whole_reply_is_rejected_on_any_defect(self):
        ids = ('a', 'b')
        cases = [None, [], 'text', 3, ['x', 'y'], {}, {'errors': {'0': 'x'}},
                 {'results': 'xy'}, {'results': {'0': 'x', '1': 'y'}},
                 {'results': ['x']}, {'results': ['x', 'y', 'z']}, {'results': []},
                 {'results': ['x', 'y'], 'q': '0'}, {'results': ['x', 'y'], 'extra': 1},
                 {'results': ['x', 'y'], 'errors': {}},
                 {'results': ['x', 'y'], 'errors': []},
                 {'results': ['x', None], 'errors': {'01': 'why'}},
                 {'results': [None, 'y'], 'errors': {'00': 'why'}},
                 {'results': ['x', None], 'errors': {'-1': 'why'}},
                 {'results': ['x', None], 'errors': {'+1': 'why'}},
                 {'results': ['x', None], 'errors': {'1.0': 'why'}},
                 {'results': ['x', None], 'errors': {'one': 'why'}},
                 {'results': ['x', None], 'errors': {'2': 'why'}},
                 {'results': ['x', None], 'errors': {'1': 'why', '9': 'why'}},
                 {'results': ['x', 'y'], 'errors': {'1': 'why'}},
                 {'results': ['x', ''], 'errors': {'1': 'why'}},
                 {'results': ['x', None], 'errors': {'1': ''}},
                 {'results': ['x', None], 'errors': {'1': '  \n'}},
                 {'results': ['x', None], 'errors': {'1': 5}},
                 {'results': ['x', None], 'errors': {'1': None}},
                 {'results': ['x', None], 'errors': {'1': 'w' * 65537}},
                 {'results': ['x', 'y' * 65537]},
                 {'results': ['x', ['y' * 65537]]},
                 {'results': ['x', '\ud800']},
                 {'results': ['x', float('nan')]},
                 {'results': ['x', float('inf')]}]
        for value in cases:
            with self.subTest(value=str(value)[:60]), self.assertRaises(Error):
                validate_reply(value, ids)

    def test_size_limits_are_in_bytes(self):
        limit = 65536
        self.assertEqual(validate_reply({'results': ['y' * limit]}, ('a',)), {'a': ('ok', 'y' * limit)})
        self.assertEqual(validate_reply({'results': [None], 'errors': {'0': 'w' * limit}}, ('a',))['a'][0],
                         'failed')
        with self.assertRaises(Error):
            validate_reply({'results': ['ş' * (limit // 2 + 1)]}, ('a',))
        with self.assertRaises(Error):
            validate_reply({'results': [None], 'errors': {'0': 'ş' * (limit // 2 + 1)}}, ('a',))

    def test_regroup_single_item_job_keeps_its_value(self):
        job_map = (('a', 0), ('b', 0), ('c', 0))
        outcomes = regroup({'results': ['text', {'k': [1, 2]}, 7]}, job_map)
        self.assertEqual(outcomes, {'a': ('ok', 'text'), 'b': ('ok', '{"k":[1,2]}'), 'c': ('ok', '7')})
        self.assertEqual(list(outcomes), ['a', 'b', 'c'])

    def test_regroup_multi_item_job_stores_results_object_in_item_order(self):
        job_map = (('a', 0), ('a', 1), ('a', 2), ('b', 0), ('c', 0), ('c', 2))
        reply = {'results': ['read', {'v': 1.5}, 'Türkçe', 'single', ['x'], 'last']}
        outcomes = regroup(reply, job_map)
        self.assertEqual(outcomes['a'], ('ok', '{"results":["read",{"v":1.5},"Türkçe"]}'))
        self.assertEqual(outcomes['b'], ('ok', 'single'))
        self.assertEqual(outcomes['c'], ('ok', '{"results":[["x"],"last"]}'))
        # Strings stay strings; nothing is stringified twice.
        self.assertEqual(regroup({'results': ['[1]', 'x']}, (('a', 0), ('a', 1)))['a'],
                         ('ok', '{"results":["[1]","x"]}'))

    def test_regroup_failed_item_fails_the_job_with_local_index_reasons(self):
        job_map = (('a', 0), ('a', 1), ('a', 2), ('b', 0), ('c', 0), ('c', 1))
        reply = {'results': ['ok', None, None, None, 'fine', 'fine'],
                 'errors': {'1': 'no data', '2': 'unknown reference', '3': 'cannot'}}
        outcomes = regroup(reply, job_map)
        self.assertEqual(outcomes['a'], ('failed', '1: no data; 2: unknown reference'))
        self.assertEqual(outcomes['b'], ('failed', 'cannot'))
        self.assertEqual(outcomes['c'], ('ok', '{"results":["fine","fine"]}'))

    def test_regroup_keeps_validation_strict(self):
        job_map = (('a', 0), ('a', 1))
        for bad in [{'results': ['x']}, {'results': ['x', 'y', 'z']}, {'results': ['x', 'y'], 'q': '0'},
                    {'results': ['x', 'y'], 'errors': {}}, {'results': ['x', 'y'], 'errors': {'1': 'why'}},
                    {'results': ['x', None], 'errors': {'2': 'why'}}, {'results': ['x', None], 'errors': {'1': ' '}},
                    {'results': [['y' * 40000], ['y' * 40000]]}, ['x', 'y'], None]:
            with self.subTest(bad=str(bad)[:50]), self.assertRaises(Error):
                regroup(bad, job_map)

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
        reply = {'results': ['x']}
        self.assertEqual(validate_response({'reply': reply}, ('a',)), ({'a': ('ok', 'x')}, {}))
        self.assertEqual(validate_response({'reply': reply, 'usage': {'input_tokens': 9}}, ('a',)),
                         ({'a': ('ok', 'x')}, {'input_tokens': 9}))
        for bad in [None, reply, {}, {'reply': reply, 'secret': 1},
                    {'reply': reply, 'usage': {'input_tokens': -1}},
                    {'reply': {'results': []}}, {'reply': {'results': ['x', 'y']}},
                    {'reply': ['x']}]:
            with self.subTest(bad=str(bad)[:60]), self.assertRaises(Error):
                validate_response(bad, ('a',))

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

    def post(self, mid, wire='r13', *, after=()):
        self.box.post(self.ch, mid, wire, binding=self.ch.binding, after=after)

    def worker(self, adapter, **kwargs):
        kwargs.setdefault('retry_delay', 5)
        return Worker(self.box, self.ch, adapter, counters=[len], max_tokens=10000,
                      capabilities=kwargs.pop('capabilities', CAPS), **kwargs)

    def test_worker_request_has_adapter3_fields_and_oz9_packet(self):
        self.post('job_zq7')
        seen = []
        def adapter(request):
            seen.append(request)
            return {'reply': {'results': ['done']}}
        result = self.worker(adapter).run_once()
        request = seen[0]
        self.assertEqual(result['status'], 'received')
        self.assertEqual(set(request), {'protocol', 'language', 'binding', 'receipt', 'ids', 'attempts',
                                        'system', 'prompt', 'prompt_tokens'})
        self.assertEqual(request['attempts'], [1])
        self.assertEqual(request['ids'], ['job_zq7'])
        self.assertEqual((request['protocol'], request['language']), ('oz.adapter/3', 'OZ/9'))
        self.assertNotIn('job_zq7', request['prompt'] + request['system'])
        self.assertEqual(request['system'], SYSTEM)
        # The receipt is host-side: the model never sees it.
        self.assertNotIn('q', json.loads(request['prompt']))
        self.assertEqual(request['prompt_tokens'], [len(request['system']) + 1 + len(request['prompt'])])
        self.assertEqual((result['language'], result['mode']), ('OZ/9', result['mode']))

    def test_reply_keeps_exact_result_and_usage(self):
        self.post('one')
        def adapter(request):
            return {'reply': {'results': ['  exact result\r\n']},
                    'usage': {'input_tokens': 900, 'cached_input_tokens': 800, 'output_tokens': 12}}
        report = self.worker(adapter).run_once()
        self.assertEqual(report['status'], 'received')
        self.assertEqual(report['verification'], 'unverified')
        self.assertEqual(self.box.inspect('one')['result'], '  exact result\r\n')
        self.assertEqual(self.box.runs()[0]['report']['usage']['cached_input_tokens'], 800)

    def test_native_json_results_are_stored_as_compact_text(self):
        self.post('one')
        self.post('two')
        adapter = lambda request: {'reply': {'results': [{'value': 12.5, 'unit': 'mm'}, [1, 2]]}}
        self.worker(adapter, batch_size=2).run_once()
        self.assertEqual(self.box.inspect('one')['result'], '{"value":12.5,"unit":"mm"}')
        self.assertEqual(self.box.inspect('two')['result'], '[1,2]')

    def test_multi_atom_frame_is_flattened_and_regrouped_into_one_stored_result(self):
        self.post('multi', 'r7a7t14')
        self.post('single', 'r13')
        seen = []
        def adapter(request):
            seen.append(request)
            return {'reply': {'results': ['read text', {'findings': []}, 'test requested', 'single value']}}
        self.worker(adapter, batch_size=2).run_once()
        self.assertEqual(json.loads(seen[0]['prompt'])['j'], ['read 7', 'audit 7', 'test 14', 'read 13'])
        self.assertEqual(self.box.inspect('multi')['result'],
                         '{"results":["read text",{"findings":[]},"test requested"]}')
        self.assertEqual(self.box.inspect('single')['result'], 'single value')

    def test_failed_atom_fails_its_job_with_local_index_reasons_and_not_the_sibling(self):
        self.post('multi', 'r7a7t14')
        self.post('single', 'r13')
        reply = {'results': ['read text', None, None, 'single value'],
                 'errors': {'1': 'no patch', '2': 'no procedure'}}
        result = self.worker(lambda request: {'reply': reply}, batch_size=2).run_once()
        self.assertEqual(result['outcomes'], {'multi': 'failed', 'single': 'ok'})
        multi = self.box.inspect('multi')
        self.assertEqual((multi['state'], multi['error']), ('failed', '1: no patch; 2: no procedure'))
        self.assertEqual(self.box.inspect('single')['result'], 'single value')

    def test_reply_count_must_match_model_jobs_not_inbox_jobs(self):
        self.post('multi', 'r7a7t14')
        result = self.worker(lambda request: {'reply': {'results': ['one job result']}}).run_once()
        self.assertEqual(result['error_code'], 'adapter_invalid_reply')
        self.assertEqual(self.box.inspect('multi')['state'], 'pending')

    def test_positional_reply_maps_results_to_delivered_ids(self):
        for mid in ('first', 'second', 'third'):
            self.post(mid)
        def adapter(request):
            self.assertEqual(request['ids'], ['first', 'second', 'third'])
            for mid in request['ids']:
                self.assertNotIn(mid, request['prompt'])
            return {'reply': {'results': ['one', 'two', 'three']}}
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
        for bad_reply in ('legacy_list', 'partial', 'extra_key', 'empty_errors'):
            with self.subTest(bad_reply=bad_reply):
                self.box.close()
                self.box = Inbox(clock=lambda: self.now[0])
                self.addCleanup(self.box.close)
                self.post('first')
                self.post('sibling')
                self.post('dependent', after=('first',))
                def adapter(request):
                    if bad_reply == 'legacy_list':
                        reply = [request['receipt'], 'result', 'result']
                    elif bad_reply == 'extra_key':
                        reply = {'results': ['result', 'result'], 'q': request['receipt']}
                    elif bad_reply == 'empty_errors':
                        reply = {'results': ['result', 'result'], 'errors': {}}
                    else:
                        reply = {'results': ['result']}
                    return {'reply': reply, 'usage': {'output_tokens': 7}}
                result = self.worker(adapter, batch_size=2).run_once()
                self.assertEqual(result['status'], 'adapter_error')
                self.assertEqual(result['error_code'], 'adapter_invalid_reply')
                self.assertEqual(result['usage'], {'output_tokens': 7})
                self.assertEqual(set(result['outcomes'].values()), {'retry'})
                self.assertEqual(self.box.inspect('first')['state'], 'pending')
                self.assertEqual(self.box.inspect('sibling')['state'], 'pending')
                self.assertEqual(self.box.inspect('dependent')['attempts'], 0)

    def test_errors_map_fails_only_listed_jobs_without_retry(self):
        for mid in ('first', 'bad', 'third'):
            self.post(mid)
        calls = []
        def adapter(request):
            calls.append(request)
            return {'reply': {'results': ['done one', None, 'done three'],
                              'errors': {'1': 'unsupported request'}}}
        worker = self.worker(adapter, batch_size=3)
        first = worker.run_once()
        self.assertEqual(first['outcomes'], {'first': 'ok', 'bad': 'failed', 'third': 'ok'})
        self.now[0] += 60
        self.assertEqual(worker.run_once()['status'], 'idle')
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.box.inspect('first')['result'], 'done one')
        self.assertEqual(self.box.inspect('bad')['state'], 'failed')

    def test_failed_call_retries_all_jobs_with_fresh_receipt(self):
        for mid in ('first', 'second'):
            self.post(mid)
        calls = []
        def adapter(request):
            calls.append(request)
            if len(calls) == 1:
                raise RuntimeError('temporary outage')
            return {'reply': {'results': ['eventual one', 'eventual two']}}
        worker = self.worker(adapter, batch_size=2)
        first = worker.run_once()
        self.assertEqual(first['outcomes'], {'first': 'retry', 'second': 'retry'})
        self.assertEqual(worker.run_once()['status'], 'idle')
        self.now[0] += 5
        second = worker.run_once()
        self.assertEqual(second['ids'], ['first', 'second'])
        self.assertEqual(self.box.inspect('first')['result'], 'eventual one')
        self.assertEqual(self.box.inspect('second')['result'], 'eventual two')
        self.assertNotEqual(calls[0]['receipt'], calls[1]['receipt'])
        self.assertEqual(self.box.inspect('first')['attempts'], 2)

    def test_every_attempt_uses_fresh_receipt(self):
        self.post('one')
        receipts = []
        def adapter(request):
            receipts.append(request['receipt'])
            if len(receipts) < 3:
                return {'reply': {'results': []}}
            return {'reply': {'results': ['done']}}
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
            return {'reply': {'results': ['PREDECESSOR-RESULT' if 'first' in request['ids']
                                          else 'ok'] * len(request['ids'])}}
        worker = self.worker(adapter, batch_size=3)
        worker.run_once()
        worker.run_once()
        request = requests[1]
        self.assertEqual(request['ids'], ['a', 'b'])
        self.assertEqual(request['prompt'].count('PREDECESSOR-RESULT'), 1)
        body = json.loads(request['prompt'])
        self.assertEqual(body['p'], {'first': 'PREDECESSOR-RESULT'})
        self.assertEqual(body['h'], [['first', 0], ['first', 1]])


if __name__ == '__main__':
    unittest.main()
