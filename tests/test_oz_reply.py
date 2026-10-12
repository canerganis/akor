"""OZ/9 stage-1d replies (jsonl [id,result] lines, bare value), usage, negotiation and atomic Worker acceptance."""
import json
import unittest

from oz import Error
from oz_batch import SYSTEM, SYSTEMS as SYSTEM_TEXTS
from oz_reply import (check_capabilities, encode_reply, loads, parse_reply, regroup, slot_ids, validate_response,
                      validate_usage)
from oz_runtime import Inbox
from oz_worker import Worker
from test_oz2 import extended

CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}
NL = chr(10)
CR = chr(13)
IDS = ('a', 'b')


def text(*rows, end=''):
    """Reply text: each row is a JSON value dumped on its own line, or a str kept raw."""
    return NL.join(row if isinstance(row, str) else json.dumps(row, ensure_ascii=False) for row in rows) + end


def reasons(parsed):
    return [(v['line'], v['reason']) for v in parsed.violations]


def answer(request, *values):
    """Adapter response answering the packet's jobs in prompt order with the given result values."""
    ids = [job[0] for job in json.loads(request['prompt'])['j']]
    return {'reply': text(*([mid, value] for mid, value in zip(ids, values)))}


class ParseTests(unittest.TestCase):
    def test_jsonl_accepts_exactly_the_expected_ids_in_any_order(self):
        parsed = parse_reply(text(['b', {'a': [1, 2.5, None]}], ['a', 'done']), IDS)
        self.assertEqual(parsed.accepted, {'a': 'done', 'b': {'a': [1, 2.5, None]}})
        self.assertEqual((parsed.rejection, parsed.violations, parsed.received, parsed.duplicate_lines),
                         (None, (), 2, 0))
        self.assertEqual(parse_reply(text(['a', None], ['b', '']), IDS).accepted, {'a': None, 'b': ''})

    def test_lines_are_split_on_lf_and_only_space_tab_and_cr_are_stripped(self):
        reply = ' \t["a",1]' + CR + NL + NL + '  ["b",2] \t' + CR + NL + NL
        parsed = parse_reply(reply, IDS)
        self.assertEqual(parsed.accepted, {'a': 1, 'b': 2})
        # Other whitespace (form feed, vertical tab, NBSP) is not stripped and breaks the line.
        for junk in ('\x0c', '\x0b', '\xa0', ' '):
            with self.subTest(junk=repr(junk)):
                self.assertEqual(parse_reply(junk + '["a",1]' + NL + '["b",2]', IDS).accepted, {})
        # A lone CR is not a line break.
        self.assertEqual(parse_reply('["a",1]' + CR + '["b",2]', IDS).accepted, {})

    def test_every_deviation_rejects_the_whole_reply(self):
        for name, reply in {
            'missing id': text(['a', 1]),
            'unknown id': text(['a', 1], ['b', 2], ['c', 3]),
            'only unknown': text(['x', 1], ['y', 2]),
            'conflicting repeat': text(['a', 1], ['b', 2], ['a', 3]),
            'malformed line': text(['a', 1], '["b",'),
            'prose': 'Done.' + NL + text(['a', 1], ['b', 2]),
            'fence': '```' + NL + text(['a', 1], ['b', 2]) + NL + '```',
            'outer array': json.dumps([['a', 1], ['b', 2]]),
            'three elements': text(['a', 1, 'x'], ['b', 2]),
            'one element': text(['a'], ['b', 2]),
            'object line': text({'a': 1}, ['b', 2]),
            'non-string id': text([0, 1], ['b', 2]),
            'id case': text(['A', 1], ['b', 2]),
            'id padded': text([' a', 1], ['b', 2]),
            'empty': '',
            'blank only': NL + '  ' + NL,
        }.items():
            with self.subTest(name=name):
                parsed = parse_reply(reply, IDS)
                self.assertEqual(parsed.accepted, {})
                self.assertIsNotNone(parsed.rejection)
                self.assertTrue(parsed.violations)

    def test_byte_identical_repeats_count_once_and_are_recorded(self):
        line_a, line_b = '["a","x"]', '["b",{"k":1}]'
        parsed = parse_reply(NL.join([line_a, line_b, line_a, line_b]), IDS)
        self.assertEqual((parsed.accepted, parsed.duplicate_lines, parsed.received),
                         ({'a': 'x', 'b': {'k': 1}}, 2, 4))
        # The repeat may differ in end whitespace only.
        parsed = parse_reply(line_a + NL + line_b + NL + ' ' + line_a + ' \t' + CR, IDS)
        self.assertEqual((sorted(parsed.accepted), parsed.duplicate_lines), (['a', 'b'], 1))
        # Three identical copies still fit under the 2N cap and are tolerated.
        self.assertEqual(parse_reply(NL.join([line_a] * 3 + [line_b]), IDS).duplicate_lines, 2)

    def test_equivalent_but_different_bytes_are_a_conflict(self):
        for second in ('["a", "x"]', '["a","\\u0078"]', '["a" ,"x"]'):
            with self.subTest(second=second):
                parsed = parse_reply(NL.join(['["a","x"]', second, '["b",1]']), IDS)
                self.assertEqual(parsed.accepted, {})
                self.assertIn('conflicting', parsed.rejection)
        for first, second in (('["a",1]', '["a",1.0]'), ('["a",1]', '["a",1e0]'),
                              ('["a",{"x":1,"y":2}]', '["a",{"y":2,"x":1}]')):
            with self.subTest(first=first, second=second):
                self.assertEqual(parse_reply(NL.join([first, second, '["b",1]']), IDS).accepted, {})

    def test_more_than_2n_non_blank_lines_reject_everything(self):
        line_a, line_b = '["a",1]', '["b",2]'
        self.assertEqual(sorted(parse_reply(NL.join([line_a, line_b, line_a, line_b]), IDS).accepted), ['a', 'b'])
        parsed = parse_reply(NL.join([line_a, line_b, line_a, line_b, line_a]), IDS)
        self.assertEqual((parsed.accepted, parsed.rejection), ({}, 'more than 4 non-blank lines'))
        # Blank lines do not count; the first N lines are never taken on their own.
        blanks = NL.join([line_a, '', line_b, '  ', line_a, line_b])
        self.assertEqual(sorted(parse_reply(blanks, IDS).accepted), ['a', 'b'])
        self.assertEqual(parse_reply(NL.join([line_a, line_b, '["a",9]', '["b",9]', '["c",9]']), IDS).accepted, {})

    def test_strict_json_duplicate_keys_and_non_finite_numbers_are_rejected(self):
        for value in ('{"k":1,"k":2}', '[{"k":1,"k":2}]', 'NaN', 'Infinity', '-Infinity', '1e999', '[1,1e999]', '"\\ud800"'):
            with self.subTest(value=value):
                self.assertEqual(parse_reply('["a",' + value + ']' + NL + '["b",1]', IDS).accepted, {})
        for text_ in ('{"k":1,"k":2}', 'NaN', '1e999', '-1E999'):
            with self.subTest(text=text_), self.assertRaises(Error):
                loads(text_)
        self.assertEqual(loads('[1e300,-0.5,10]'), [1e300, -0.5, 10])

    def test_oversize_lines_and_total_capture_limit_reject_everything(self):
        big = '["a","' + 'y' * 65536 + '"]'
        parsed = parse_reply(NL.join([big, '["b",1]']), IDS)
        self.assertEqual(parsed.accepted, {})
        self.assertIn('exceeds 65536 bytes', reasons(parsed)[0][1])
        edge = '["a","' + 'y' * (65536 - 8) + '"]'
        self.assertEqual(len(edge.encode('utf-8')), 65536)
        self.assertEqual(parse_reply(NL.join([edge, '["b",1]']), IDS).accepted['a'], 'y' * (65536 - 8))
        huge = parse_reply('x' * (2 * 65536 + 4097), IDS)
        self.assertEqual((huge.accepted, huge.rejection), ({}, 'reply exceeds the total capture limit'))

    def test_unencodable_results_reject_everything(self):
        self.assertEqual(parse_reply('["a","\\ud800"]' + NL + '["b",1]', IDS).accepted, {})

    def test_reply_must_be_text_and_mode_known(self):
        for bad in [None, b'["a",1]', ['a'], {'a': 1}, 3]:
            with self.subTest(bad=str(bad)), self.assertRaises(Error):
                parse_reply(bad, IDS)
        with self.assertRaises(Error):
            parse_reply('1', ('a',), 'array')

    def test_value_mode_takes_one_bare_result_with_at_most_two_identical_lines(self):
        for reply, expected in [('"done"', 'done'), ('{"k":[1,null]}', {'k': [1, None]}), ('null', None),
                                ('[0,"x"]', [0, 'x']), ('1.5', 1.5), ('"a"' + NL + '"a"', 'a'),
                                (' "a" ' + CR + NL + NL + '"a"' + NL, 'a')]:
            with self.subTest(reply=reply):
                parsed = parse_reply(reply, ('only',), 'value')
                self.assertEqual((parsed.accepted, parsed.rejection), ({'only': expected}, None))
        self.assertEqual(parse_reply('"a"' + NL + '"a"', ('only',), 'value').duplicate_lines, 1)
        for reply in ['', 'prose', '"a"' + NL + '"b"', '"a"' + NL + '"a"' + NL + '"a"', '"a" "a"', '["only","a"]x',
                      '{"k":1,"k":2}', 'NaN', '```' + NL + '"a"' + NL + '```', '"a"' + NL + '"a",']:
            with self.subTest(reply=reply):
                parsed = parse_reply(reply, ('only',), 'value')
                self.assertEqual(parsed.accepted, {})
                self.assertIsNotNone(parsed.rejection)
        with self.assertRaises(Error):
            parse_reply('"a"', ('x', 'y'), 'value')

    def test_value_mode_does_not_look_for_ids(self):
        # The bare value ["a","x"] is the result itself; no id is peeled off.
        self.assertEqual(parse_reply('["a","x"]', ('a',), 'value').accepted, {'a': ['a', 'x']})

    def test_violations_are_capped_and_ordered(self):
        parsed = parse_reply(NL.join(['x'] * 4), ('a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm',
                                                  'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z'))
        self.assertEqual(reasons(parsed)[0], (1, 'malformed JSON line'))
        many = parse_reply(NL.join(['x'] * 60), tuple(str(i) for i in range(40)))
        self.assertEqual(len(many.violations), 20)
        self.assertEqual([v['line'] for v in many.violations], list(range(1, 21)))


class SlotIdTests(unittest.TestCase):
    def test_single_slot_jobs_keep_their_inbox_id_and_multi_slot_jobs_get_atom_suffixes(self):
        self.assertEqual(slot_ids((('a', 0), ('b', 1), ('c', 0), ('c', 2), ('c', 3))),
                         ('a', 'b', 'c.0', 'c.2', 'c.3'))
        self.assertEqual(slot_ids(()), ())


class RegroupTests(unittest.TestCase):
    def test_single_item_job_keeps_its_value(self):
        job_map = (('a', 0), ('b', 0), ('c', 0))
        grouped = regroup(text(['a', 'text'], ['b', {'k': [1, 2]}], ['c', 7]), job_map)
        self.assertEqual(grouped.outcomes, {'a': ('ok', 'text'), 'b': ('ok', '{"k":[1,2]}'), 'c': ('ok', '7')})
        self.assertEqual(list(grouped.outcomes), ['a', 'b', 'c'])

    def test_success_null_and_blank_strings_are_stored_as_json_text(self):
        grouped = regroup(text(['a', None], ['b', ''], ['c', '  '], ['d', True]), tuple((m, 0) for m in 'abcd'))
        self.assertEqual(grouped.outcomes, {'a': ('ok', 'null'), 'b': ('ok', '""'), 'c': ('ok', '"  "'),
                                            'd': ('ok', 'true')})

    def test_exact_text_is_preserved(self):
        exact = '  12.50 ± 0.02 mm' + CR + NL + 'method unknown.  '
        self.assertEqual(regroup(text(['a', exact]), (('a', 0),)).outcomes, {'a': ('ok', exact)})
        self.assertEqual(regroup(text(['a', '[1, 2]']), (('a', 0),)).outcomes, {'a': ('ok', '[1, 2]')})

    def test_multi_item_job_stores_results_object_in_atom_order(self):
        job_map = (('a', 0), ('a', 1), ('a', 2), ('b', 0), ('c', 0), ('c', 2))
        reply = text(['c.2', 'last'], ['a.0', 'read'], ['a.1', {'v': 1.5}], ['a.2', 'Türkçe'], ['b', 'single'],
                     ['c.0', ['x']])
        grouped = regroup(reply, job_map)
        self.assertEqual(grouped.outcomes['a'], ('ok', '{"results":["read",{"v":1.5},"Türkçe"]}'))
        self.assertEqual(grouped.outcomes['b'], ('ok', 'single'))
        self.assertEqual(grouped.outcomes['c'], ('ok', '{"results":[["x"],"last"]}'))
        self.assertEqual(regroup(text(['a.0', '[1]'], ['a.1', 'x']), (('a', 0), ('a', 1))).outcomes['a'],
                         ('ok', '{"results":["[1]","x"]}'))

    def test_host_slots_join_model_slots_in_atom_order(self):
        grouped = regroup(text(['a', 'model']), (('a', 1),), host_slots=(('a', 0, ''), ('a', 2, 'cmd')))
        self.assertEqual(grouped.outcomes['a'], ('ok', '{"results":["","model","cmd"]}'))
        self.assertEqual(regroup('', (), (('h', 0, 'x'),)).outcomes, {'h': ('ok', 'x')})

    def test_any_rejected_line_retries_every_model_job_but_not_host_only_jobs(self):
        job_map = (('a', 0), ('a', 1), ('b', 0), ('c', 0))
        reply = text(['a.0', 'a0'], ['a.1', 'a1'], ['b', 'b'], ['c', 'c'], ['d', 'unknown'])
        grouped = regroup(reply, job_map, host_slots=(('h', 0, 'x'),))
        self.assertEqual({m: o[0] for m, o in grouped.outcomes.items()},
                         {'a': 'retry', 'b': 'retry', 'c': 'retry', 'h': 'ok'})
        self.assertIn('adapter_invalid_reply', grouped.outcomes['a'][1])
        self.assertEqual(grouped.values, {'h': '"x"'})
        self.assertIsNotNone(grouped.parsed.rejection)

    def test_aggregate_over_the_size_limit_retries_that_job_only(self):
        job_map = (('a', 0), ('a', 1), ('b', 0))
        reply = text(['a.0', 'y' * 40000], ['a.1', 'y' * 40000], ['b', 'fine'])
        outcomes = regroup(reply, job_map).outcomes
        self.assertEqual(outcomes['a'][0], 'retry')
        self.assertEqual(outcomes['b'], ('ok', 'fine'))

    def test_no_accepted_line_retries_everything(self):
        for reply in ['', 'prose', '{"results":["x"]}', text(['a', 'x'], ['a', 'y'])]:
            with self.subTest(reply=reply):
                grouped = regroup(reply, (('a', 0),))
                self.assertEqual(grouped.parsed.accepted, {})
                self.assertEqual(grouped.outcomes['a'][0], 'retry')

    def test_value_mode_regroup(self):
        grouped = regroup('{"k":[1]}' + NL + '{"k":[1]}', (('a', 0),), mode='value')
        self.assertEqual((grouped.outcomes, grouped.values), ({'a': ('ok', '{"k":[1]}')}, {'a': '{"k":[1]}'}))
        self.assertEqual(grouped.parsed.duplicate_lines, 1)
        self.assertEqual(regroup('"x"' + NL + '"y"', (('a', 0),), mode='value').outcomes['a'][0], 'retry')

    def test_non_text_reply_is_rejected(self):
        for bad in [None, {'results': ['x']}, ['x'], 3]:
            with self.subTest(bad=str(bad)), self.assertRaises(Error):
                regroup(bad, (('a', 0),))

    def test_encode_reply_round_trips_in_request_order(self):
        results = {'a': 'A', 'b': '  B' + NL}
        reply = encode_reply(results, ('a', 'b'))
        self.assertEqual(reply, '["a","A"]' + NL + '["b","  B' + chr(92) + 'n"]')
        self.assertEqual(regroup(reply, (('a', 0), ('b', 0))).outcomes,
                         {'a': ('ok', 'A'), 'b': ('ok', '  B' + NL)})
        self.assertEqual(regroup(encode_reply(results, ('b', 'a')), (('b', 0), ('a', 0))).outcomes['a'], ('ok', 'A'))


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
        reply = '["a","x"]'
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


class RegroupValueTests(unittest.TestCase):
    def test_values_are_the_compact_json_of_the_accepted_native_value(self):
        grouped = regroup(text(['a', 'plain'], ['b', {'k': [1, None]}], ['c', None]), (('a', 0), ('b', 0), ('c', 0)))
        self.assertEqual(grouped.values, {'a': '"plain"', 'b': '{"k":[1,null]}', 'c': 'null'})

    def test_multi_slot_and_host_slot_values(self):
        grouped = regroup(text(['a.0', 1], ['a.1', 'x'], ['b', 2]), (('a', 0), ('a', 1), ('b', 0)),
                          host_slots=(('b', 1, 'cmd'), ('h', 0, '')))
        self.assertEqual(grouped.values, {'a': '{"results":[1,"x"]}', 'b': '{"results":[2,"cmd"]}', 'h': '""'})

    def test_retried_jobs_have_no_value(self):
        grouped = regroup(text(['a', 1]), (('a', 0), ('b', 0)))
        self.assertEqual(grouped.values, {})
        self.assertEqual({m: o[0] for m, o in grouped.outcomes.items()}, {'a': 'retry', 'b': 'retry'})


class ReplyWorkerTests(unittest.TestCase):
    def setUp(self):
        self.ch = extended()
        self.now = [100.0]
        self.box = Inbox(clock=lambda: self.now[0])
        self.addCleanup(self.box.close)

    def post(self, mid, wire='>12', *, after=()):
        self.box.post(self.ch, mid, wire, binding=self.ch.binding, after=after)

    def worker(self, adapter, **kwargs):
        kwargs.setdefault('retry_delay', 5)
        return Worker(self.box, self.ch, adapter, counters=[len], max_tokens=10000,
                      capabilities=kwargs.pop('capabilities', CAPS), **kwargs)

    def test_worker_request_has_adapter3_fields_and_stage_1d_packet(self):
        self.post('job_zq7')
        seen = []
        def adapter(request):
            seen.append(request)
            return answer(request, 'done')
        result = self.worker(adapter).run_once()
        request = seen[0]
        self.assertEqual(result['status'], 'received')
        self.assertEqual(set(request), {'protocol', 'language', 'binding', 'receipt', 'ids', 'attempts',
                                        'system', 'prompt', 'prompt_tokens'})
        self.assertEqual(request['attempts'], [1])
        self.assertEqual(request['ids'], ['job_zq7'])
        self.assertEqual((request['protocol'], request['language']), ('oz.adapter/3', 'OZ/9'))
        self.assertEqual(json.loads(request['prompt'])['j'][0][0], 'job_zq7')
        self.assertEqual(request['system'], SYSTEM)
        self.assertNotIn(request['receipt'], request['prompt'] + request['system'])
        self.assertEqual(request['prompt_tokens'], [len(request['system']) + 1 + len(request['prompt'])])
        self.assertEqual((result['language'], result['wire'], result['reply_mode']), ('OZ/9', 'stage-1d', 'jsonl'))

    def test_reply_keeps_exact_result_and_usage(self):
        self.post('one')
        def adapter(request):
            return dict(answer(request, '  exact result' + CR + NL),
                        usage={'input_tokens': 900, 'cached_input_tokens': 800, 'output_tokens': 12})
        report = self.worker(adapter).run_once()
        self.assertEqual(report['status'], 'received')
        self.assertEqual(report['verification'], 'unverified')
        self.assertEqual(self.box.inspect('one')['result'], '  exact result' + CR + NL)
        self.assertEqual(self.box.runs()[0]['report']['usage']['cached_input_tokens'], 800)

    def test_native_json_results_are_stored_as_compact_text(self):
        self.post('one')
        self.post('two')
        self.worker(lambda request: answer(request, {'value': 12.5, 'unit': 'mm'}, [1, 2]), batch_size=2).run_once()
        self.assertEqual(self.box.inspect('one')['result'], '{"value":12.5,"unit":"mm"}')
        self.assertEqual(self.box.inspect('two')['result'], '[1,2]')

    def test_multi_atom_frame_gets_suffixed_ids_and_one_stored_result(self):
        self.post('multi', 'a7>12=13')
        self.post('single', '>12')
        seen = []
        def adapter(request):
            seen.append(request)
            return answer(request, 'audit text', {'findings': []}, 'observed', 'single value')
        self.worker(adapter, batch_size=2).run_once()
        body = json.loads(seen[0]['prompt'])
        self.assertEqual([job[:2] for job in body['j']],
                         [['multi.0', 'audit'], ['multi.1', 'propose'], ['multi.2', 'observed'],
                          ['single', 'propose']])
        self.assertEqual(self.box.inspect('multi')['result'],
                         '{"results":["audit text",{"findings":[]},"observed"]}')
        self.assertEqual(self.box.inspect('single')['result'], 'single value')

    def test_host_slots_join_the_model_slots_in_atom_order(self):
        self.post('multi', 'V')
        self.post('other', 'r7a7')
        seen = []
        def adapter(request):
            seen.append(request)
            return answer(request, {'findings': []}, 'second')
        self.worker(adapter, batch_size=2).run_once()
        self.assertEqual([job[0] for job in json.loads(seen[0]['prompt'])['j']], ['multi', 'other'])
        self.assertEqual(self.box.inspect('multi')['result'],
                         '{"results":["",{"findings":[]},"python -m unittest"]}')
        self.assertEqual(self.box.inspect('other')['result'], '{"results":["","second"]}')

    def test_job_of_only_host_operations_is_completed_without_an_adapter_call(self):
        import tempfile
        from pathlib import Path
        self.post('read', 'r13')
        self.post('test', 't14')
        self.post('both', 'r7t14')
        self.post('after', 'r13', after=['read'])
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'calls.jsonl'
            worker = self.worker(lambda request: calls.append(request), batch_size=3, ledger_path=path)
            report = worker.run_once()
            self.assertFalse(path.exists())
        self.assertEqual(calls, [])
        self.assertEqual((report['status'], report['adapter_calls'], report['model_calls']), ('host_completed', 0, 0))
        self.assertEqual(report['outcomes'], {'read': 'ok', 'test': 'ok', 'both': 'ok'})
        self.assertEqual(report['ids'], ['read', 'test', 'both'])
        self.assertEqual(self.box.inspect('read')['result'], '""')
        self.assertEqual(self.box.inspect('test')['result'], 'python -m unittest')
        self.assertEqual(self.box.inspect('both')['result'], '{"results":["","python -m unittest"]}')
        self.assertEqual(self.box.inspect('read')['attempts'], 1)
        self.assertEqual(self.box.runs()[0]['report']['status'], 'host_completed')
        self.assertEqual(worker.run_once()['status'], 'host_completed')
        self.assertEqual(self.box.inspect('after')['state'], 'done')
        self.assertEqual(calls, [])

    def test_acceptance_is_atomic_one_bad_line_retries_every_job(self):
        for mid in ('first', 'second', 'third'):
            self.post(mid)
        calls = []
        def adapter(request):
            calls.append(request)
            if len(calls) == 1:
                # first is fine, second is missing, third has a conflicting repeat.
                return {'reply': text(['first', 'one'], ['third', 'x'], ['third', 'y']), 'usage': {'output_tokens': 7}}
            return answer(request, 'two', 'three', 'four')
        worker = self.worker(adapter, batch_size=3)
        first = worker.run_once()
        self.assertEqual(first['status'], 'adapter_error')
        self.assertEqual(first['error_code'], 'adapter_invalid_reply')
        self.assertEqual(first['outcomes'], {'first': 'retry', 'second': 'retry', 'third': 'retry'})
        self.assertEqual(first['usage'], {'output_tokens': 7})
        # Nothing from the rejected reply was published.
        self.assertEqual(self.box.stats(), {'pending': 3})
        self.assertIsNone(self.box.inspect('first')['result'])
        self.assertEqual(worker.run_once()['status'], 'idle')
        self.now[0] += 5
        second = worker.run_once()
        self.assertEqual(second['ids'], ['first', 'second', 'third'])
        self.assertEqual([self.box.inspect(m)['result'] for m in ('first', 'second', 'third')],
                         ['two', 'three', 'four'])
        self.assertNotEqual(calls[0]['receipt'], calls[1]['receipt'])
        self.assertEqual(self.box.inspect('first')['attempts'], 2)

    def test_swapped_but_schema_valid_ids_are_accepted_as_declared_not_verified(self):
        # An id written by the model cannot prove the answer belongs to it: the ledger says so.
        import tempfile
        from pathlib import Path
        self.post('one')
        self.post('two')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'calls.jsonl'
            self.worker(lambda r: {'reply': text(['two', 'for one'], ['one', 'for two'])}, batch_size=2,
                        ledger_path=path).run_once()
            end = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()][-1]
        self.assertEqual((end['validation']['binding'], end['validation']['semantic_verified']), ('declared', False))
        self.assertEqual(self.box.inspect('one')['result'], 'for two')

    def test_multi_atom_job_with_one_missing_atom_retries_every_job(self):
        self.post('multi', 'a7>12')
        self.post('single', '>12')
        calls = []
        def adapter(request):
            calls.append(request)
            if len(calls) == 1:
                return {'reply': text(['multi.0', 'audit text'], ['single', 'single value'])}
            return answer(request, 'a', 'b', 'c')
        worker = self.worker(adapter, batch_size=2)
        result = worker.run_once()
        self.assertEqual(result['outcomes'], {'multi': 'retry', 'single': 'retry'})
        self.assertIsNone(self.box.inspect('single')['result'])
        self.now[0] += 5
        worker.run_once()
        self.assertEqual(calls[1]['ids'], ['multi', 'single'])
        self.assertEqual(self.box.inspect('multi')['result'], '{"results":["a","b"]}')
        self.assertEqual(self.box.inspect('single')['result'], 'c')

    def test_rejection_keeps_dependants_locked(self):
        self.post('first')
        self.post('sibling')
        self.post('dependent', after=('first',))
        result = self.worker(lambda r: {'reply': text(['sibling', 'sibling done'])}, batch_size=2).run_once()
        self.assertEqual(result['outcomes'], {'first': 'retry', 'sibling': 'retry'})
        self.assertEqual(self.box.inspect('dependent')['attempts'], 0)
        self.assertEqual(self.box.inspect('dependent')['state'], 'pending')

    def test_rejected_reply_ledger_counts_and_violations(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'calls.jsonl'
            self.post('one')
            self.post('two')
            reply = text(['one', 'a'], '["two",', ['five', 'out'])
            self.worker(lambda r: {'reply': reply}, batch_size=2, ledger_path=path).run_once()
            end = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()][-1]
        self.assertEqual(end['outcome'], 'invalid_response')
        self.assertEqual(end['validation'], dict(
            expected_results=2, received_results=2, accepted_results=0, failed_results=0,
            violations=[{'line': 2, 'reason': 'malformed JSON line'}, {'line': 3, 'reason': 'unknown or non-string id'}],
            binding='declared', duplicate_lines=0, semantic_verified=False))

    def test_object_reply_retries_every_job(self):
        self.post('multi', 'a7>12')
        result = self.worker(lambda request: {'reply': '{"results":["a","b"]}'}).run_once()
        self.assertEqual(result['error_code'], 'adapter_invalid_reply')
        self.assertEqual(result['outcomes'], {'multi': 'retry'})
        self.assertEqual(self.box.inspect('multi')['state'], 'pending')

    def test_non_text_reply_retries_every_job(self):
        self.post('one')
        result = self.worker(lambda request: {'reply': {'results': ['x']}}).run_once()
        self.assertEqual(result['error_code'], 'adapter_invalid_reply')
        self.assertEqual(self.box.inspect('one')['state'], 'pending')

    def test_replies_map_results_by_id_whatever_the_line_order(self):
        for mid in ('job_a', 'job_b', 'job_c'):
            self.post(mid)
        def adapter(request):
            self.assertEqual(request['ids'], ['job_a', 'job_b', 'job_c'])
            self.assertEqual([j[0] for j in json.loads(request['prompt'])['j']], ['job_a', 'job_b', 'job_c'])
            return {'reply': text(['job_c', 'three'], ['job_a', 'one'], ['job_b', 'two'])}
        self.worker(adapter, batch_size=3).run_once()
        self.assertEqual([self.box.inspect(m)['result'] for m in ('job_a', 'job_b', 'job_c')],
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
        for bad_reply in ('legacy_object', 'prose', 'list_value', 'duplicate_everything', 'positional'):
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
                    elif bad_reply == 'positional':
                        reply = text([0, 'a'], [1, 'b'])
                    else:
                        reply = text(['first', 'a'], ['first', 'b'], ['sibling', 'c'], ['sibling', 'd'])
                    return {'reply': reply, 'usage': {'output_tokens': 7}}
                result = self.worker(adapter, batch_size=2).run_once()
                self.assertEqual(result['status'], 'adapter_error')
                self.assertEqual(result['error_code'], 'adapter_invalid_reply')
                self.assertEqual(result['usage'], {'output_tokens': 7})
                self.assertEqual(set(result['outcomes'].values()), {'retry'})
                self.assertEqual(self.box.inspect('first')['state'], 'pending')
                self.assertEqual(self.box.inspect('sibling')['state'], 'pending')
                self.assertEqual(self.box.inspect('dependent')['attempts'], 0)

    def test_byte_identical_repeated_reply_is_tolerated(self):
        self.post('a')
        self.post('b')
        once = text(['a', 'x'], ['b', 'y'])
        report = self.worker(lambda r: {'reply': once + NL + once}, batch_size=2).run_once()
        self.assertEqual((report['status'], report['outcomes']), ('received', {'a': 'ok', 'b': 'ok'}))
        self.assertEqual((self.box.inspect('a')['result'], self.box.inspect('b')['result']), ('x', 'y'))

    def test_blank_string_result_is_stored_without_breaking_settle(self):
        self.post('one')
        self.worker(lambda request: answer(request, '')).run_once()
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
            return answer(request, 'eventual one', 'eventual two')
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
        self.box.post(self.ch, 'one', '>12', binding=self.ch.binding, max_attempts=3)
        receipts = []
        def adapter(request):
            receipts.append(request['receipt'])
            if len(receipts) < 3:
                return {'reply': ''}
            return answer(request, 'done')
        worker = self.worker(adapter, retry_delay=0)
        for _ in range(3):
            worker.run_once()
        self.assertEqual(len(set(receipts)), 3)
        self.assertEqual(self.box.inspect('one')['state'], 'done')

    def test_predecessor_result_is_the_prior_of_each_dependant(self):
        self.post('first')
        self.post('a', after=['first'])
        self.post('b', after=['first'])
        requests = []
        def adapter(request):
            requests.append(request)
            value = 'PREDECESSOR-RESULT' if 'first' in request['ids'] else 'ok'
            return answer(request, *([value] * len(request['ids'])))
        worker = self.worker(adapter, batch_size=3)
        worker.run_once()
        worker.run_once()
        request = requests[1]
        self.assertEqual(request['ids'], ['a', 'b'])
        body = json.loads(request['prompt'])
        self.assertEqual(list(body), ['goal', 'd', 'j'])
        self.assertEqual(body['j'], [['a', 'propose', 'Use 5 seconds per attempt', ['PREDECESSOR-RESULT']],
                                     ['b', 'propose', 'Use 5 seconds per attempt', ['PREDECESSOR-RESULT']]])

    def test_value_mode_sends_the_value_system_text_and_settles_a_bare_result(self):
        self.post('one')
        self.post('two', '>12')
        seen = []
        def adapter(request):
            seen.append(request)
            return {'reply': json.dumps({'k': [1]})}
        worker = self.worker(adapter, reply_mode='value')
        result = worker.run_once()
        self.assertEqual((result['status'], result['reply_mode'], result['ids']), ('received', 'value', ['one']))
        self.assertEqual(seen[0]['system'], SYSTEM_TEXTS['value'])
        self.assertEqual(json.loads(seen[0]['prompt'])['j'], ['propose', 'Use 5 seconds per attempt'])
        self.assertEqual(self.box.inspect('one')['result'], '{"k":[1]}')
        self.assertEqual(self.box.inspect('two')['state'], 'pending')
        worker.run_once()
        self.assertEqual(self.box.stats(), {'done': 2})
        self.assertEqual(len(seen), 2)

    def test_value_mode_rejects_a_different_second_line_and_tolerates_an_identical_one(self):
        self.post('one')
        replies = iter(['"a"' + NL + '"b"', '"a"' + NL + '"a"'])
        worker = self.worker(lambda r: {'reply': next(replies)}, reply_mode='value', retry_delay=0)
        self.assertEqual(worker.run_once()['outcomes'], {'one': 'retry'})
        self.assertEqual(self.box.inspect('one')['state'], 'pending')
        self.assertEqual(worker.run_once()['outcomes'], {'one': 'ok'})
        self.assertEqual(self.box.inspect('one')['result'], 'a')

    def test_value_mode_with_a_multi_atom_job_is_a_host_error_before_any_call(self):
        self.post('multi', 'a7>12')
        calls = []
        worker = self.worker(lambda r: calls.append(r), reply_mode='value')
        with self.assertRaisesRegex(Error, 'exactly one model job'):
            worker.run_once()
        self.assertEqual(calls, [])
        self.assertEqual(self.box.inspect('multi')['attempts'], 0)

    def test_jsonl_is_the_default_reply_mode(self):
        self.post('three')
        seen = []
        self.worker(lambda r: seen.append(r) or answer(r, 'x')).run_once()
        self.assertEqual(seen[0]['system'], SYSTEM)

    def test_accepted_results_are_stored_as_json_values_and_used_as_prior_in_dependency_order(self):
        self.post('p', '>12')
        self.post('q', 'a7>12')
        self.post('r', '>12')
        self.post('z', '>12', after=('q', 'p', 'r'))
        legacy = self.box.claim(self.ch, owner='old', limit=1)
        self.assertEqual([j.id for j in legacy.jobs], ['p'])
        self.box.complete(legacy, {'p': '{"older":"text"}'})
        self.assertIsNone(self.box.db.execute("SELECT result_json FROM jobs WHERE id='p'").fetchone()[0])
        requests = []
        def adapter(request):
            requests.append(request)
            if 'z' in request['ids']:
                return answer(request, 'final')
            return answer(request, 'audit text', {'k': [1, None]}, '[1, 2]')
        worker = self.worker(adapter)
        worker.run_once()
        self.assertEqual(self.box.stats(), {'done': 3, 'pending': 1})
        stored = {r['id']: r['result_json'] for r in self.box.db.execute('SELECT id,result_json FROM jobs')}
        self.assertEqual(stored, {'p': None, 'q': '{"results":["audit text",{"k":[1,null]}]}',
                                  'r': '"[1, 2]"', 'z': None})
        worker.run_once()
        self.assertEqual(requests[-1]['ids'], ['z'])
        body = json.loads(requests[-1]['prompt'])
        self.assertEqual(body['j'], [['z', 'propose', 'Use 5 seconds per attempt', [
            {'results': ['audit text', {'k': [1, None]}]}, '{"older":"text"}', '[1, 2]']]])
        self.assertIn('[{"results":["audit text",{"k":[1,null]}]},"{\\"older\\":\\"text\\"}","[1, 2]"]',
                      requests[-1]['prompt'])

    def test_a_failed_predecessor_blocks_its_dependant_which_is_never_sent(self):
        self.box.post(self.ch, 'first', '>12', binding=self.ch.binding, max_attempts=1)
        self.post('next', after=('first',))
        requests = []
        def adapter(request):
            requests.append(request)
            return {'reply': 'no result lines'}
        worker = self.worker(adapter, retry_delay=0)
        self.assertEqual(worker.run_once()['outcomes'], {'first': 'retry'})
        for _ in range(3):
            self.assertEqual(worker.run_once()['status'], 'idle')
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.box.inspect('first')['state'], 'failed')
        self.assertEqual(self.box.inspect('next')['attempts'], 0)
        self.assertEqual(self.box.inspect('next')['waiting_for'], [{'id': 'first', 'state': 'failed'}])
        self.assertEqual(self.box.plan(self.ch, counters=[len]).jobs, ())

    def test_literal_names_survive_batch_splits_retries_and_a_reopened_inbox(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'inbox.sqlite'
            box = Inbox(path, clock=lambda: self.now[0])
            for mid, wire in (('n1', ':first note'), ('n2', ':second note'), ('n3', ':first note'), ('n4', ':third')):
                box.post(self.ch, mid, wire, binding=self.ch.binding)
            names = []
            def adapter(request):
                body = json.loads(request['prompt'])
                names.append((request['ids'], [job[1] for job in body['j']], body['d']))
                if len(names) == 2:
                    return {'reply': 'prose'}
                return answer(request, *(['ok'] * len(body['j'])))
            Worker(box, self.ch, adapter, counters=[len], max_tokens=10000, capabilities=CAPS,
                   batch_size=1, retry_delay=0).run_once()
            Worker(box, self.ch, adapter, counters=[len], max_tokens=10000, capabilities=CAPS,
                   batch_size=1, retry_delay=0).run_once()
            box.close()
            box = Inbox(path, clock=lambda: self.now[0])
            worker = Worker(box, self.ch, adapter, counters=[len], max_tokens=10000, capabilities=CAPS,
                            batch_size=1, retry_delay=0)
            for _ in range(4):
                worker.run_once()
            self.assertEqual(box.stats(), {'done': 4})
            box.close()
        by_id = {ids[0]: (j, d) for ids, j, d in names}
        self.assertEqual(by_id['n1'], (['literal_0'], {'literal_0': 'first note'}))
        self.assertEqual([j for ids, j, d in names if ids == ['n2']], [['literal_1'], ['literal_1']])
        self.assertEqual(by_id['n3'], (['literal_0'], {'literal_0': 'first note'}))
        self.assertEqual(by_id['n4'], (['literal_2'], {'literal_2': 'third'}))


if __name__ == '__main__':
    unittest.main()
