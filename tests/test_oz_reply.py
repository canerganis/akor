"""OZ/9 JSONL replies, usage, negotiation and Worker per-job acceptance."""
import json
import unittest

from oz import Error
from oz_batch import SYSTEM
from oz_reply import (check_capabilities, encode_reply, parse_reply, regroup, validate_response,
                      validate_usage)
from oz_runtime import Inbox
from oz_worker import Worker
from test_oz2 import extended

CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}
NL = chr(10)


def text(*rows, end=''):
    """Reply text: each row is a JSON value dumped on its own line, or a str kept raw."""
    return NL.join(row if isinstance(row, str) else json.dumps(row, ensure_ascii=False) for row in rows) + end


def reasons(parsed):
    return [(v['line'], v['reason']) for v in parsed.violations]


class ParseTests(unittest.TestCase):
    def test_success_failure_and_success_null(self):
        parsed = parse_reply(text([0, 'done'], [1, None, 'no data'], [2, None], [3, {'a': [1, 2.5, None]}]), 4)
        self.assertEqual(parsed.accepted, {0: ('ok', 'done'), 1: ('failed', 'no data'), 2: ('ok', None),
                                           3: ('ok', {'a': [1, 2.5, None]})})
        self.assertEqual((parsed.expected, parsed.received, parsed.violations), (4, 4, ()))

    def test_order_does_not_matter_and_indexes_are_positions(self):
        parsed = parse_reply(text([2, 'c'], [0, 'a'], [1, 'b']), 3)
        self.assertEqual(parsed.accepted, {0: ('ok', 'a'), 1: ('ok', 'b'), 2: ('ok', 'c')})

    def test_trailing_lf_is_ignored_but_other_empty_lines_are_violations(self):
        self.assertEqual(parse_reply(text([0, 'a'], end=NL), 1).violations, ())
        middle = parse_reply('[0,"a"]' + NL + NL + '[1,"b"]', 2)
        self.assertEqual(middle.accepted, {0: ('ok', 'a'), 1: ('ok', 'b')})
        self.assertEqual(reasons(middle), [(2, 'empty line')])
        double = parse_reply('[0,"a"]' + NL + NL, 1)
        self.assertEqual(double.accepted, {0: ('ok', 'a')})
        self.assertEqual(reasons(double), [(2, 'empty line')])
        self.assertEqual(parse_reply('', 1).accepted, {})
        self.assertEqual(parse_reply('', 1).violations, ())

    def test_missing_index_is_simply_unaccepted(self):
        parsed = parse_reply(text([0, 'a'], [2, 'c']), 3)
        self.assertEqual(sorted(parsed.accepted), [0, 2])
        self.assertEqual(parsed.violations, ())

    def test_duplicate_index_accepts_none_of_its_lines(self):
        parsed = parse_reply(text([0, 'a'], [1, 'b'], [0, 'again']), 2)
        self.assertEqual(parsed.accepted, {1: ('ok', 'b')})
        self.assertEqual(reasons(parsed), [(1, 'conflicting lines for index 0'), (3, 'conflicting lines for index 0')])
        # A failure line and a success line for one index also conflict, and so does an invalid twin.
        self.assertEqual(parse_reply(text([0, 'a'], [0, None, 'no']), 1).accepted, {})
        self.assertEqual(parse_reply(text([0, 'a'], [0, None, ' ']), 1).accepted, {})
        self.assertEqual(parse_reply(text([0, 'a'], [0, 1, 2, 3]), 1).accepted, {})

    def test_index_must_be_an_in_range_integer(self):
        for row in ([2, 'x'], [-1, 'x'], [True, 'x'], [False, 'x'], [1.0, 'x'], ['0', 'x'], [None, 'x'], [[0], 'x']):
            with self.subTest(row=row):
                parsed = parse_reply(text([0, 'ok'], row), 2)
                self.assertEqual(parsed.accepted, {0: ('ok', 'ok')})
                self.assertEqual(len(parsed.violations), 1)
        self.assertEqual(parse_reply(text([True, 'x']), 2).accepted, {})

    def test_prose_and_malformed_lines_only_drop_themselves(self):
        parsed = parse_reply(text('Here are the results:', [0, 'a'], '```json', [1, 'b'], '[2,"c"', '```', [2, 'c']), 3)
        self.assertEqual(parsed.accepted, {0: ('ok', 'a'), 1: ('ok', 'b'), 2: ('ok', 'c')})
        self.assertEqual([v['line'] for v in parsed.violations], [1, 3, 5, 6])
        self.assertEqual(parsed.received, 3)

    def test_object_or_scalar_lines_are_not_results(self):
        for line in ['{"results":["a"]}', '"a"', '5', 'null', 'true', '[]', '[0]', '[0,1,2,3]', '[0,"a"] x',
                     '[0,"a"],[1,"b"]', '[0,NaN]', '[0,Infinity]', '[0,{"k":1,"k":2}]']:
            with self.subTest(line=line):
                parsed = parse_reply(line, 2)
                self.assertEqual(parsed.accepted, {})
                self.assertEqual(len(parsed.violations), 1)

    def test_failure_needs_null_and_a_nonblank_error_string(self):
        for row in ([0, None, ''], [0, None, ' \t'], [0, None, 5], [0, None, None], [0, 'x', 'why'],
                    [0, 0, 'why'], [0, False, 'why']):
            with self.subTest(row=row):
                self.assertEqual(parse_reply(text(row), 1).accepted, {})
        self.assertEqual(parse_reply(text([0, None, ' why ']), 1).accepted, {0: ('failed', ' why ')})

    def test_oversize_value_makes_only_its_index_unaccepted(self):
        limit = 65536
        parsed = parse_reply(text([0, 'y' * (limit + 1)], [1, 'fine'], [2, ['y' * limit]], [3, 'ş' * (limit // 2 + 1)],
                                  [4, None, 'w' * (limit + 1)], [5, 'y' * limit]), 6)
        self.assertEqual(sorted(parsed.accepted), [1, 5])
        self.assertEqual([v['line'] for v in parsed.violations], [1, 3, 4, 5])
        self.assertEqual(parsed.received, 6)

    def test_unencodable_values_are_unaccepted(self):
        for line in ['[0,"\\ud800"]', '[0,1e999]']:
            with self.subTest(line=line):
                self.assertEqual(parse_reply(line, 1).accepted, {})

    def test_reply_must_be_text(self):
        for value in [None, {'results': ['x']}, ['[0,"x"]'], 5, b'[0,"x"]']:
            with self.subTest(value=str(value)), self.assertRaises(Error):
                parse_reply(value, 1)

    def test_violations_are_capped_and_ordered(self):
        parsed = parse_reply(text(*(['prose'] * 30)), 1)
        self.assertEqual([v['line'] for v in parsed.violations], list(range(1, 21)))


class RegroupTests(unittest.TestCase):
    def test_single_item_job_keeps_its_value(self):
        job_map = (('a', 0), ('b', 0), ('c', 0))
        grouped = regroup(text([0, 'text'], [1, {'k': [1, 2]}], [2, 7]), job_map)
        self.assertEqual(grouped.outcomes, {'a': ('ok', 'text'), 'b': ('ok', '{"k":[1,2]}'), 'c': ('ok', '7')})
        self.assertEqual(list(grouped.outcomes), ['a', 'b', 'c'])

    def test_success_null_and_blank_strings_are_stored_as_json_text(self):
        grouped = regroup(text([0, None], [1, ''], [2, '  '], [3, True]), tuple((m, 0) for m in 'abcd'))
        self.assertEqual(grouped.outcomes, {'a': ('ok', 'null'), 'b': ('ok', '""'), 'c': ('ok', '"  "'),
                                            'd': ('ok', 'true')})

    def test_exact_text_is_preserved(self):
        exact = '  12.50 ± 0.02 mm' + chr(13) + NL + 'method unknown.  '
        self.assertEqual(regroup(text([0, exact]), (('a', 0),)).outcomes, {'a': ('ok', exact)})
        # A string that looks like JSON stays the exact string.
        self.assertEqual(regroup(text([0, '[1, 2]']), (('a', 0),)).outcomes, {'a': ('ok', '[1, 2]')})

    def test_multi_item_job_stores_results_object_in_item_order(self):
        job_map = (('a', 0), ('a', 1), ('a', 2), ('b', 0), ('c', 0), ('c', 2))
        reply = text([5, 'last'], [0, 'read'], [1, {'v': 1.5}], [2, 'Türkçe'], [3, 'single'], [4, ['x']])
        grouped = regroup(reply, job_map)
        self.assertEqual(grouped.outcomes['a'], ('ok', '{"results":["read",{"v":1.5},"Türkçe"]}'))
        self.assertEqual(grouped.outcomes['b'], ('ok', 'single'))
        self.assertEqual(grouped.outcomes['c'], ('ok', '{"results":[["x"],"last"]}'))
        self.assertEqual(regroup(text([0, '[1]'], [1, 'x']), (('a', 0), ('a', 1))).outcomes['a'],
                         ('ok', '{"results":["[1]","x"]}'))

    def test_failed_item_fails_the_job_with_local_index_reasons(self):
        job_map = (('a', 0), ('a', 1), ('a', 2), ('b', 0), ('c', 0), ('c', 1))
        reply = text([0, 'ok'], [1, None, 'no data'], [2, None, 'unknown reference'], [3, None, 'cannot'],
                     [4, 'fine'], [5, 'fine'])
        outcomes = regroup(reply, job_map).outcomes
        self.assertEqual(outcomes['a'], ('failed', '1: no data; 2: unknown reference'))
        self.assertEqual(outcomes['b'], ('failed', 'cannot'))
        self.assertEqual(outcomes['c'], ('ok', '{"results":["fine","fine"]}'))

    def test_unaccepted_item_retries_only_its_job(self):
        job_map = (('a', 0), ('a', 1), ('b', 0), ('c', 0), ('d', 0))
        reply = text([0, 'a0'], [2, 'b'], [3, 'c'], [3, 'c again'], 'prose', [9, 'out of range'], [4, 'd'])
        outcomes = regroup(reply, job_map).outcomes
        self.assertEqual(outcomes['a'][0], 'retry')
        self.assertEqual(outcomes['b'], ('ok', 'b'))
        self.assertEqual(outcomes['c'][0], 'retry')
        self.assertEqual(outcomes['d'], ('ok', 'd'))
        self.assertIn('adapter_invalid_reply', outcomes['a'][1])

    def test_aggregate_over_the_size_limit_retries_that_job_only(self):
        job_map = (('a', 0), ('a', 1), ('b', 0))
        reply = text([0, 'y' * 40000], [1, 'y' * 40000], [2, 'fine'])
        outcomes = regroup(reply, job_map).outcomes
        self.assertEqual(outcomes['a'][0], 'retry')
        self.assertEqual(outcomes['b'], ('ok', 'fine'))

    def test_no_accepted_line_retries_everything(self):
        for reply in ['', 'prose', '{"results":["x"]}', text([0, 'x'], [0, 'y'])]:
            with self.subTest(reply=reply):
                grouped = regroup(reply, (('a', 0),))
                self.assertEqual(grouped.parsed.accepted, {})
                self.assertEqual(grouped.outcomes['a'][0], 'retry')

    def test_non_text_reply_is_rejected(self):
        for bad in [None, {'results': ['x']}, ['x'], 3]:
            with self.subTest(bad=str(bad)), self.assertRaises(Error):
                regroup(bad, (('a', 0),))

    def test_encode_reply_round_trips_in_request_order(self):
        outcomes = {'a': ('ok', 'A'), 'b': ('failed', '  B' + NL)}
        reply = encode_reply(outcomes, ('a', 'b'))
        self.assertEqual(reply, '[0,"A"]' + NL + '[1,null,"  B' + chr(92) + 'n"]')
        self.assertEqual(regroup(reply, (('a', 0), ('b', 0))).outcomes, outcomes)
        reordered = encode_reply(outcomes, ('b', 'a'))
        self.assertEqual(regroup(reordered, (('b', 0), ('a', 0))).outcomes, outcomes)


class UsageAndCapabilityTests(unittest.TestCase):
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
        reply = '[0,"x"]'
        job_map = (('a', 0),)
        grouped, usage = validate_response({'reply': reply}, job_map)
        self.assertEqual((grouped.outcomes, usage), ({'a': ('ok', 'x')}, {}))
        self.assertEqual(validate_response({'reply': reply, 'usage': {'input_tokens': 9}}, job_map)[1],
                         {'input_tokens': 9})
        for bad in [None, reply, {}, {'reply': reply, 'secret': 1},
                    {'reply': reply, 'usage': {'input_tokens': -1}}, {'reply': {'results': ['x']}},
                    {'reply': ['x']}]:
            with self.subTest(bad=str(bad)[:60]), self.assertRaises(Error):
                validate_response(bad, job_map)

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
            return {'reply': text([0, 'done'])}
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
            return {'reply': text([0, '  exact result' + chr(13) + NL]),
                    'usage': {'input_tokens': 900, 'cached_input_tokens': 800, 'output_tokens': 12}}
        report = self.worker(adapter).run_once()
        self.assertEqual(report['status'], 'received')
        self.assertEqual(report['verification'], 'unverified')
        self.assertEqual(self.box.inspect('one')['result'], '  exact result' + chr(13) + NL)
        self.assertEqual(self.box.runs()[0]['report']['usage']['cached_input_tokens'], 800)

    def test_native_json_results_are_stored_as_compact_text(self):
        self.post('one')
        self.post('two')
        adapter = lambda request: {'reply': text([0, {'value': 12.5, 'unit': 'mm'}], [1, [1, 2]])}
        self.worker(adapter, batch_size=2).run_once()
        self.assertEqual(self.box.inspect('one')['result'], '{"value":12.5,"unit":"mm"}')
        self.assertEqual(self.box.inspect('two')['result'], '[1,2]')

    def test_multi_atom_frame_is_flattened_and_regrouped_into_one_stored_result(self):
        self.post('multi', 'r7a7t14')
        self.post('single', 'r13')
        seen = []
        def adapter(request):
            seen.append(request)
            return {'reply': text([0, 'read text'], [1, {'findings': []}], [2, 'test requested'],
                                  [3, 'single value'], end=NL)}
        self.worker(adapter, batch_size=2).run_once()
        self.assertEqual(json.loads(seen[0]['prompt'])['j'], ['read 7', 'audit 7', 'test 14', 'read 13'])
        self.assertEqual(self.box.inspect('multi')['result'],
                         '{"results":["read text",{"findings":[]},"test requested"]}')
        self.assertEqual(self.box.inspect('single')['result'], 'single value')

    def test_failed_atom_fails_its_job_with_local_index_reasons_and_not_the_sibling(self):
        self.post('multi', 'r7a7t14')
        self.post('single', 'r13')
        reply = text([0, 'read text'], [1, None, 'no patch'], [2, None, 'no procedure'], [3, 'single value'])
        result = self.worker(lambda request: {'reply': reply}, batch_size=2).run_once()
        self.assertEqual(result['outcomes'], {'multi': 'failed', 'single': 'ok'})
        multi = self.box.inspect('multi')
        self.assertEqual((multi['state'], multi['error']), ('failed', '1: no patch; 2: no procedure'))
        self.assertEqual(self.box.inspect('single')['result'], 'single value')

    def test_partial_acceptance_settles_accepted_jobs_and_retries_only_the_others(self):
        for mid in ('first', 'second', 'third'):
            self.post(mid)
        calls = []
        def adapter(request):
            calls.append(request)
            if len(calls) == 1:
                # Index 1 is missing and index 2 is conflicting; index 0 is fine.
                return {'reply': text([0, 'one'], 'Done!', [2, 'x'], [2, 'y']), 'usage': {'output_tokens': 7}}
            return {'reply': text([0, 'two'], [1, 'three'])}
        worker = self.worker(adapter, batch_size=3)
        first = worker.run_once()
        self.assertEqual(first['status'], 'received')
        self.assertEqual(first['outcomes'], {'first': 'ok', 'second': 'retry', 'third': 'retry'})
        self.assertEqual(first['usage'], {'output_tokens': 7})
        self.assertEqual(self.box.inspect('first')['state'], 'done')
        self.assertEqual(self.box.inspect('first')['result'], 'one')
        for mid in ('second', 'third'):
            self.assertEqual(self.box.inspect(mid)['state'], 'pending')
        self.assertEqual(worker.run_once()['status'], 'idle')
        self.now[0] += 5
        second = worker.run_once()
        self.assertEqual(second['ids'], ['second', 'third'])
        self.assertEqual(calls[1]['ids'], ['second', 'third'])
        self.assertEqual(json.loads(calls[1]['prompt'])['j'], ['read 13', 'read 13'])
        self.assertEqual(self.box.inspect('second')['result'], 'two')
        self.assertEqual(self.box.inspect('third')['result'], 'three')
        self.assertEqual(self.box.inspect('first')['attempts'], 1)
        self.assertEqual(self.box.inspect('second')['attempts'], 2)
        self.assertNotEqual(calls[0]['receipt'], calls[1]['receipt'])

    def test_multi_atom_job_with_one_missing_atom_retries_as_a_whole(self):
        self.post('multi', 'r7a7t14')
        self.post('single', 'r13')
        calls = []
        def adapter(request):
            calls.append(request)
            if len(calls) == 1:
                return {'reply': text([0, 'read text'], [2, 'test requested'], [3, 'single value'])}
            return {'reply': text([0, 'a'], [1, 'b'], [2, 'c'])}
        worker = self.worker(adapter, batch_size=2)
        result = worker.run_once()
        self.assertEqual(result['outcomes'], {'multi': 'retry', 'single': 'ok'})
        self.assertEqual(self.box.inspect('multi')['state'], 'pending')
        self.assertIsNone(self.box.inspect('multi')['result'])
        self.assertEqual(self.box.inspect('single')['result'], 'single value')
        self.now[0] += 5
        worker.run_once()
        self.assertEqual(calls[1]['ids'], ['multi'])
        self.assertEqual(json.loads(calls[1]['prompt'])['j'], ['read 7', 'audit 7', 'test 14'])
        self.assertEqual(self.box.inspect('multi')['result'], '{"results":["a","b","c"]}')

    def test_partial_acceptance_keeps_dependants_of_retried_jobs_locked(self):
        self.post('first')
        self.post('sibling')
        self.post('dependent', after=('first',))
        result = self.worker(lambda r: {'reply': text([1, 'sibling done'])}, batch_size=2).run_once()
        self.assertEqual(result['outcomes'], {'first': 'retry', 'sibling': 'ok'})
        self.assertEqual(self.box.inspect('dependent')['attempts'], 0)
        self.assertEqual(self.box.inspect('dependent')['state'], 'pending')

    def test_partial_acceptance_ledger_counts_and_violations(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'calls.jsonl'
            self.post('one')
            self.post('two')
            reply = text([0, 'a'], 'not json', [5, 'out'])
            self.worker(lambda r: {'reply': reply}, batch_size=2, ledger_path=path).run_once()
            end = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()][-1]
        self.assertEqual(end['outcome'], 'invalid_response')
        self.assertEqual(end['validation'], dict(
            expected_results=2, received_results=2, accepted_results=1, failed_results=0,
            violations=[{'line': 2, 'reason': 'not a single JSON value'},
                        {'line': 3, 'reason': 'index out of range'}]))

    def test_object_reply_retries_every_job(self):
        self.post('multi', 'r7a7t14')
        result = self.worker(lambda request: {'reply': '{"results":["a","b","c"]}'}).run_once()
        self.assertEqual(result['error_code'], 'adapter_invalid_reply')
        self.assertEqual(result['outcomes'], {'multi': 'retry'})
        self.assertEqual(self.box.inspect('multi')['state'], 'pending')

    def test_non_text_reply_retries_every_job(self):
        self.post('one')
        result = self.worker(lambda request: {'reply': {'results': ['x']}}).run_once()
        self.assertEqual(result['error_code'], 'adapter_invalid_reply')
        self.assertEqual(self.box.inspect('one')['state'], 'pending')

    def test_positional_reply_maps_results_to_delivered_ids(self):
        for mid in ('first', 'second', 'third'):
            self.post(mid)
        def adapter(request):
            self.assertEqual(request['ids'], ['first', 'second', 'third'])
            for mid in request['ids']:
                self.assertNotIn(mid, request['prompt'])
            return {'reply': text([2, 'three'], [0, 'one'], [1, 'two'])}
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
        for bad_reply in ('legacy_object', 'prose', 'list_value', 'duplicate_everything'):
            with self.subTest(bad_reply=bad_reply):
                self.box.close()
                self.box = Inbox(clock=lambda: self.now[0])
                self.addCleanup(self.box.close)
                self.post('first')
                self.post('sibling')
                self.post('dependent', after=('first',))
                def adapter(request):
                    if bad_reply == 'legacy_object':
                        reply = json.dumps({'results': ['result', 'result']})
                    elif bad_reply == 'prose':
                        reply = 'Both jobs are done.'
                    elif bad_reply == 'list_value':
                        reply = ['result', 'result']
                    else:
                        reply = text([0, 'a'], [0, 'b'], [1, 'c'], [1, 'd'])
                    return {'reply': reply, 'usage': {'output_tokens': 7}}
                result = self.worker(adapter, batch_size=2).run_once()
                self.assertEqual(result['status'], 'adapter_error')
                self.assertEqual(result['error_code'], 'adapter_invalid_reply')
                self.assertEqual(result['usage'], {'output_tokens': 7})
                self.assertEqual(set(result['outcomes'].values()), {'retry'})
                self.assertEqual(self.box.inspect('first')['state'], 'pending')
                self.assertEqual(self.box.inspect('sibling')['state'], 'pending')
                self.assertEqual(self.box.inspect('dependent')['attempts'], 0)

    def test_failure_lines_fail_only_listed_jobs_without_retry(self):
        for mid in ('first', 'bad', 'third'):
            self.post(mid)
        calls = []
        def adapter(request):
            calls.append(request)
            return {'reply': text([0, 'done one'], [1, None, 'unsupported request'], [2, 'done three'])}
        worker = self.worker(adapter, batch_size=3)
        first = worker.run_once()
        self.assertEqual(first['outcomes'], {'first': 'ok', 'bad': 'failed', 'third': 'ok'})
        self.now[0] += 60
        self.assertEqual(worker.run_once()['status'], 'idle')
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.box.inspect('first')['result'], 'done one')
        self.assertEqual(self.box.inspect('bad')['state'], 'failed')

    def test_blank_string_result_is_stored_without_breaking_settle(self):
        self.post('one')
        self.worker(lambda request: {'reply': text([0, ''])}).run_once()
        self.assertEqual(self.box.inspect('one')['state'], 'done')
        self.assertEqual(self.box.inspect('one')['result'], '""')

    def test_failed_call_retries_all_jobs_with_fresh_receipt(self):
        for mid in ('first', 'second'):
            self.post(mid)
        calls = []
        def adapter(request):
            calls.append(request)
            if len(calls) == 1:
                raise RuntimeError('temporary outage')
            return {'reply': text([0, 'eventual one'], [1, 'eventual two'])}
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
                return {'reply': ''}
            return {'reply': text([0, 'done'])}
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
            value = 'PREDECESSOR-RESULT' if 'first' in request['ids'] else 'ok'
            return {'reply': text(*([i, value] for i in range(len(request['ids']))))}
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
