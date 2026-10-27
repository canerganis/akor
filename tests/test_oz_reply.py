"""OZ/9 stage-1g replies ({"id":value} and [id,"error",code,message] lines), usage, negotiation and atomic Worker acceptance."""
import json
import unittest

from oz import Error
from oz_batch import INSTRUCTIONS, SYSTEM
from wire_helpers import body_of, job_ids, job_instructions, rows
from oz_reply import (HEADER, Failure, check_capabilities, encode_reply, loads, parse_reply, regroup, slot_ids, validate_response,
                      validate_usage)
from oz_runtime import Inbox
from oz_worker import Worker
from test_oz2 import extended

CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}
NL = chr(10)
CR = chr(13)
IDS = ('a', 'b')


def line(row):
    """One reply line: a str is kept raw; a two-element [id, value] row with a str id is the success line
    {"id":value}; any other row (dict, error line, malformed shape) is dumped as given, as compact JSON (a
    model's own spacing is kept byte for byte since clause 12, so compact rows keep stored values compact)."""
    if isinstance(row, str):
        return row
    if isinstance(row, list) and len(row) == 2 and isinstance(row[0], str):
        row = {row[0]: row[1]}
    return json.dumps(row, ensure_ascii=False, separators=(',', ':'))


HEAD = 'OZ/1g'
H = HEAD + NL


def text(*rows, end='', header=HEAD):
    """Reply text: the OZ/1g header line (None omits it), then one line per row (see line)."""
    lines = [line(row) for row in rows]
    return NL.join(([header] if header is not None else []) + lines) + end


def reasons(parsed):
    return [(v['line'], v['reason']) for v in parsed.violations]


def answer(request, *values):
    """Adapter response answering the packet's jobs in prompt order with the given result values."""
    ids = job_ids(request['prompt'])
    return {'reply': text(*({mid: value} for mid, value in zip(ids, values)))}


def answer_by_id(request, values):
    """Adapter response answering each packet job ID with values[id], whatever the body's grouping order."""
    return {'reply': text(*({mid: values[mid]} for mid in job_ids(request['prompt'])))}


class ParseTests(unittest.TestCase):
    def test_accepts_exactly_the_expected_ids_in_any_order(self):
        parsed = parse_reply(text(['b', {'a': [1, 2.5, None]}], ['a', 'done']), IDS)
        self.assertEqual(parsed.accepted, {'a': 'done', 'b': {'a': [1, 2.5, None]}})
        self.assertEqual((parsed.rejection, parsed.violations, parsed.received, parsed.failed), (None, (), 2, {}))
        self.assertEqual(parse_reply(text(['a', None], ['b', '']), IDS).accepted, {'a': None, 'b': ''})

    def test_lf_and_crlf_are_accepted_and_one_trailing_line_end_is_optional(self):
        for reply in (H + '{"a":1}\n{"b":2}', H + '{"a":1}\n{"b":2}\n', 'OZ/1g\r\n{"a":1}\r\n{"b":2}\r\n',
                      'OZ/1g\r\n{"a":1}\r\n{"b":2}'):
            with self.subTest(reply=reply):
                self.assertEqual(parse_reply(reply, IDS).accepted, {'a': 1, 'b': 2})
        # JSON whitespace around the object is still valid JSON.
        self.assertEqual(parse_reply(H + ' {"a":1} \t' + NL + '{ "b" : 2 }', IDS).accepted, {'a': 1, 'b': 2})

    def test_empty_and_ascii_space_tab_lines_are_skipped(self):
        for reply in (H + '{"a":1}\n\n{"b":2}', H + '\n{"a":1}\n{"b":2}', H + '{"a":1}\n{"b":2}\n\n',
                      H + '{"a":1}\n  \n{"b":2}', 'OZ/1g\r\n{"a":1}\r\n\r\n{"b":2}', H + '{"a":1}\n{"b":2}\n \n',
                      ' \t\nOZ/1g\r\n{"a":1}\r\n\t \r\n{"b":2}\r\n   ', '\n\nOZ/1g\n\n{"a":1}\n\n\n{"b":2}\n\n\n'):
            with self.subTest(reply=reply):
                parsed = parse_reply(reply, IDS)
                self.assertEqual((parsed.accepted, parsed.rejection, parsed.violations, parsed.received),
                                 ({'a': 1, 'b': 2}, None, (), 2))

    def test_a_reply_of_only_blank_lines_is_rejected(self):
        for reply in ('', '\n', '\r\n', '\n\n\n', ' \n\t\r\n  ', '   ', '\t'):
            with self.subTest(reply=reply):
                parsed = parse_reply(reply, IDS)
                self.assertEqual((parsed.accepted, parsed.failed, parsed.rejection), ({}, {}, 'reply has no result line'))
                self.assertEqual(reasons(parsed), [(0, 'reply has no result line')])

    def test_other_whitespace_is_not_blank_and_a_lone_cr_is_not_a_line_break(self):
        # Form feed, vertical tab, NBSP, BOM and other Unicode spaces are neither blank nor JSON whitespace.
        for junk in ('\x0c', '\x0b', '\xa0', '﻿', ' ', '　', '\x85', ' '):
            with self.subTest(junk=repr(junk)):
                self.assertEqual(parse_reply(H + junk + '{"a":1}' + NL + '{"b":2}', IDS).accepted, {})
                lone = parse_reply(H + '{"a":1}' + NL + junk + NL + '{"b":2}', IDS)
                self.assertEqual((lone.accepted, reasons(lone)), ({}, [(3, 'malformed JSON line')]))
        cr = parse_reply(H + '{"a":1}' + CR + '{"b":2}', IDS)
        self.assertEqual((cr.accepted, reasons(cr)), ({}, [(2, 'malformed JSON line')]))
        self.assertEqual(parse_reply(H + '{"a":1}' + CR + NL + CR + NL + '{"b":2}', IDS).accepted, {'a': 1, 'b': 2})

    def test_every_deviation_rejects_the_whole_reply(self):
        for name, reply in {
            'missing id': text(['a', 1]),
            'unknown id': text(['a', 1], ['b', 2], ['c', 3]),
            'only unknown': text(['x', 1], ['y', 2]),
            'duplicate id': text(['a', 1], ['b', 2], ['a', 1]),
            'conflicting duplicate id': text(['a', 1], ['b', 2], ['a', 3]),
            'identical duplicate id with a missing one': text(['a', 1], ['a', 1]),
            'malformed line': text(['a', 1], '["b",'),
            'truncated reply': text(['a', 1]) + NL + '["b",2',
            'prose before the header': 'Done.' + NL + text(['a', 1], ['b', 2]),
            'prose after the header': H + 'Done.' + NL + text(['a', 1], ['b', 2], header=None),
            'trailing prose': text(['a', 1], ['b', 2]) + NL + 'Done.',
            'fence before the header': '```' + NL + text(['a', 1], ['b', 2]) + NL + '```',
            'fence after the header': H + '```' + NL + text(['a', 1], ['b', 2], header=None) + NL + '```',
            'outer array': H + json.dumps([['a', 1], ['b', 2]]),
            'three elements': text(['a', 1, 'x'], ['b', 2]),
            'five elements': text(['a', 'error', 'missing_data', 'x', 'y'], ['b', 2]),
            'one element': text(['a'], ['b', 2]),
            'old 1f success line': H + '["a",1]' + NL + '["b",2]',
            'old 1f line next to a 1g line': text({'a': 1}) + NL + '["b",2]',
            'two-member object': text({'a': 1, 'b': 2}),
            'empty object': text({}, ['b', 2]),
            'non-string id': text([0, 1], ['b', 2]),
            'id case': text(['A', 1], ['b', 2]),
            'id padded': text([' a', 1], ['b', 2]),
            'empty': '',
            'blank only': NL + '  ' + NL,
            'header only': H,
            'no header': text(['a', 1], ['b', 2], header=None),
        }.items():
            with self.subTest(name=name):
                parsed = parse_reply(reply, IDS)
                self.assertEqual((parsed.accepted, parsed.failed), ({}, {}))
                self.assertIsNotNone(parsed.rejection)
                self.assertTrue(parsed.violations)

    def test_a_duplicate_id_is_rejected_even_when_byte_identical(self):
        parsed = parse_reply(text(['a', 'x'], ['b', 1], ['a', 'x']), ('a', 'b', 'c'))
        self.assertEqual(parsed.accepted, {})
        self.assertEqual(reasons(parsed), [(4, 'duplicate id a')])
        self.assertIsNotNone(parsed.rejection)
        # With N lines allowed, a repeat displaces a needed id: the exact set is not covered.
        self.assertEqual(parse_reply(text(['a', 'x'], ['a', 'x']), IDS).accepted, {})

    def test_more_than_n_lines_reject_everything(self):
        parsed = parse_reply(NL.join([HEAD, '{"a":1}', '{"b":2}', '{"a":1}']), IDS)
        self.assertEqual((parsed.accepted, parsed.rejection), ({}, 'a malformed or unknown line rejects the whole reply'))
        self.assertEqual(reasons(parsed), [(4, 'duplicate id a')])
        self.assertEqual(parse_reply(NL.join([HEAD, '{"a":1}', '{"b":2}', '{"c":3}']), IDS).accepted, {})

    def test_error_lines_are_job_failures_with_four_elements(self):
        reply = text(['a', 'error', 'missing_data', 'Missing required field y.'],
                     ['b', 'error', 'unsupported', 'x' * 256])
        parsed = parse_reply(reply, IDS)
        self.assertEqual((parsed.accepted, parsed.rejection, parsed.received), ({}, None, 2))
        self.assertEqual(parsed.failed, {'a': ('missing_data', 'Missing required field y.'),
                                         'b': ('unsupported', 'x' * 256)})

    def test_each_error_code_is_accepted(self):
        for code in ('missing_data', 'invalid_data', 'conflict', 'unsupported'):
            with self.subTest(code=code):
                parsed = parse_reply(text(['a', 'error', code, 'why'], ['b', 1]), IDS)
                self.assertEqual((parsed.failed, parsed.accepted), ({'a': (code, 'why')}, {'b': 1}))

    def test_the_stage_1e_codes_are_no_longer_valid(self):
        for code in ('unknown_operation', 'invalid_input', 'cannot_complete'):
            with self.subTest(code=code):
                parsed = parse_reply(text(['a', 'error', code, 'why'], ['b', 1]), IDS)
                self.assertEqual((parsed.accepted, parsed.failed), ({}, {}))
                self.assertIsNotNone(parsed.rejection)

    def test_unknown_is_an_ordinary_result_value_not_an_error(self):
        parsed = parse_reply(text(['a', 'unknown'], ['b', 'inside']), IDS)
        self.assertEqual((parsed.accepted, parsed.failed, parsed.rejection), ({'a': 'unknown', 'b': 'inside'}, {}, None))

    def test_bad_error_lines_reject_everything(self):
        for name, line in {
            'wrong marker': ['a', 'failure', 'missing_data', 'x'],
            'marker case': ['a', 'Error', 'missing_data', 'x'],
            'marker not a string': ['a', None, 'missing_data', 'x'],
            'unknown code': ['a', 'error', 'timeout', 'x'],
            'code case': ['a', 'error', 'Missing_Data', 'x'],
            'code not a string': ['a', 'error', 7, 'x'],
            'empty message': ['a', 'error', 'missing_data', ''],
            'blank message': ['a', 'error', 'missing_data', ' \t'],
            'message not a string': ['a', 'error', 'missing_data', ['x']],
            'null message': ['a', 'error', 'missing_data', None],
            'unpaired surrogate message': ['a', 'error', 'missing_data', '\ud800'],
            'three elements': ['a', 'error', 'missing_data'],
            'five elements': ['a', 'error', 'missing_data', 'x', 'y'],
            'integer id': [1, 'error', 'missing_data', 'x'],
        }.items():
            with self.subTest(name=name):
                parsed = parse_reply(NL.join([HEAD, json.dumps(line), '{"b":1}']), IDS)
                self.assertEqual((parsed.accepted, parsed.failed), ({}, {}))
                self.assertIsNotNone(parsed.rejection)

    def test_a_success_value_that_looks_like_an_error_is_an_ordinary_success(self):
        value = ['error', 'missing_data', 'This is ordinary result data.']
        parsed = parse_reply(text(['a', value], ['b', 'error']), IDS)
        self.assertEqual((parsed.accepted, parsed.failed), ({'a': value, 'b': 'error'}, {}))
        # null is an ordinary result, never a failure marker.
        self.assertEqual(parse_reply(text(['a', None], ['b', None]), IDS).accepted, {'a': None, 'b': None})

    def test_mixed_successes_and_failures_and_all_failures_cover_the_ids(self):
        mixed = parse_reply(text(['b', 'error', 'invalid_data', 'bad x'], ['a', 5]), IDS)
        self.assertEqual((mixed.accepted, mixed.failed, mixed.rejection),
                         ({'a': 5}, {'b': ('invalid_data', 'bad x')}, None))
        every = parse_reply(text(['a', 'error', 'missing_data', 'm'], ['b', 'error', 'conflict', 'c']), IDS)
        self.assertEqual((every.accepted, set(every.failed), every.rejection), ({}, {'a', 'b'}, None))
        # An error line for an id does not cover a different id.
        self.assertIsNotNone(parse_reply(text(['a', 'error', 'missing_data', 'm'],
                                              ['a', 'error', 'missing_data', 'm']), IDS).rejection)

    def test_strict_json_duplicate_keys_and_non_finite_numbers_are_rejected(self):
        for value in ('{"k":1,"k":2}', '[{"k":1,"k":2}]', 'NaN', 'Infinity', '-Infinity', '1e999', '[1,1e999]', '"\\ud800"'):
            with self.subTest(value=value):
                self.assertEqual(parse_reply(H + '{"a":' + value + '}' + NL + '{"b":1}', IDS).accepted, {})
        for text_ in ('{"k":1,"k":2}', 'NaN', '1e999', '-1E999'):
            with self.subTest(text=text_), self.assertRaises(Error):
                loads(text_)
        self.assertEqual(loads('[1e300,-0.5,10]'), [1e300, -0.5, 10])

    def test_oversize_lines_and_total_capture_limit_reject_everything(self):
        big = '{"a":"' + 'y' * 65536 + '"}'
        parsed = parse_reply(NL.join([HEAD, big, '{"b":1}']), IDS)
        self.assertEqual(parsed.accepted, {})
        self.assertIn('exceeds 65536 bytes', reasons(parsed)[0][1])
        edge = '{"a":"' + 'y' * (65536 - 8) + '"}'
        self.assertEqual(len(edge.encode('utf-8')), 65536)
        self.assertEqual(parse_reply(NL.join([HEAD, edge, '{"b":1}']), IDS).accepted['a'], 'y' * (65536 - 8))
        huge = parse_reply('x' * (2 * 65536 + 4097), IDS)
        self.assertEqual((huge.accepted, huge.rejection), ({}, 'reply exceeds the total capture limit'))

    def test_unencodable_results_reject_everything(self):
        self.assertEqual(parse_reply(H + '{"a":"\\ud800"}' + NL + '{"b":1}', IDS).accepted, {})

    def test_reply_must_be_text(self):
        for bad in [None, b'["a",1]', ['a'], {'a': 1}, 3]:
            with self.subTest(bad=str(bad)), self.assertRaises(Error):
                parse_reply(bad, IDS)

    def test_violations_are_capped_and_ordered(self):
        parsed = parse_reply(NL.join([HEAD] + ['x'] * 4), ('a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm',
                                                  'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z'))
        self.assertEqual(reasons(parsed)[0], (2, 'malformed JSON line'))
        many = parse_reply(NL.join([HEAD] + ['x'] * 60), tuple(str(i) for i in range(60)))
        self.assertEqual(len(many.violations), 20)
        self.assertEqual([v['line'] for v in many.violations], list(range(2, 22)))


class StageOneGParserTests(unittest.TestCase):
    """Parser rules 3 to 10 of docs/design/stage-1g-joint-decision.md: strict, atomic, no repair."""

    def rejected(self, reply, ids=IDS, reason=None):
        parsed = parse_reply(reply, ids)
        self.assertEqual((parsed.accepted, parsed.failed), ({}, {}), reply)
        self.assertIsNotNone(parsed.rejection, reply)
        self.assertTrue(parsed.violations, reply)
        if reason is not None:
            self.assertIn(reason, [v['reason'] for v in parsed.violations])
        return parsed

    def test_duplicate_keys_hidden_by_escapes_are_rejected(self):
        # "a" and "a" are the same key once the escapes are decoded.
        self.rejected(H + '{"e1":{"x":{"a":1,"\\u0061":2}}}' + NL + '{"b":2}', ('e1', 'b'), 'malformed JSON line')
        self.rejected(H + '{"e1":{"a":1,"\\u0061":2}}', ('e1',), 'malformed JSON line')
        self.rejected(H + '{"e1":[{"k":1},{"\\u006b":1,"k":1}]}', ('e1',), 'malformed JSON line')
        self.rejected(H + '{"e1":1,"\\u00651":2}', ('e1', 'b'), 'malformed JSON line')
        self.rejected(H + '{"\\u00651":1,"e1":1}' + NL + '{"b":2}', ('e1', 'b'), 'malformed JSON line')

    def test_the_same_id_on_two_lines_is_a_duplicate_even_when_one_is_escaped(self):
        for reply in (H + '{"e1":1}' + NL + '{"\\u00651":1}' + NL + '{"b":2}',
                      H + '{"\\u00651":1}' + NL + '{"e1":2}' + NL + '{"b":2}'):
            self.rejected(reply, ('e1', 'b'), 'duplicate id e1')
        # An escaped spelling of an expected ID is that ID.
        self.assertEqual(parse_reply(H + '{"\\u00651":1}' + NL + '{"b":2}', ('e1', 'b')).accepted, {'e1': 1, 'b': 2})
        self.assertEqual(parse_reply(H + '["\\u0061","error","conflict","no"]' + NL + '{"b":2}', IDS).failed,
                         {'a': ('conflict', 'no')})

    def test_nested_duplicate_keys_in_a_result_are_rejected(self):
        for value in ('{"k":1,"k":2}', '{"k":{"n":1,"n":1}}', '[{"k":1,"k":1}]', '{"x":[{"y":{"z":1,"z":2}}]}'):
            with self.subTest(value=value):
                self.rejected(H + '{"a":' + value + '}' + NL + '{"b":1}', IDS, 'malformed JSON line')
        # The same key at different depths is not a duplicate.
        self.assertEqual(parse_reply(H + '{"a":{"a":{"a":1}}}' + NL + '{"b":1}', IDS).accepted,
                         {'a': {'a': {'a': 1}}, 'b': 1})

    def test_an_object_line_needs_exactly_one_member(self):
        reason = 'line must be a one-member {id:value} object or a four-element [id,"error",code,message] array'
        for line_ in ('{"a":1,"b":2}', '{"a":1,"b":2,"c":3}', '{"a":1,"x":2}', '{}', ' { } '):
            with self.subTest(line=line_):
                parsed = self.rejected(H + line_ + NL + '{"b":3}', IDS, reason)
                self.assertEqual(reasons(parsed)[0], (2, reason))
        self.rejected(H + '{}', ('a',), reason)

    def test_other_arrays_than_the_four_element_error_line_are_rejected(self):
        for line_ in ('[]', '["a"]', '["a",1]', '["a",1,2]', '["a","error","missing_data","x","y"]', '[["a",1]]'):
            with self.subTest(line=line_):
                self.rejected(H + line_ + NL + '{"b":1}', IDS)

    def test_a_stray_closing_bracket_or_extra_json_rejects_the_line(self):
        for line_ in ('{"a":1}]', '{"a":1}}', '{"a":1} ]', '["a","error","missing_data","x"]]',
                      '{"a":1}{"b":2}', '{"a":1},', '{"a":1} {"b":2}', '{"a":1} // c', '{"a":1,}', '{"a":[1,]}'):
            with self.subTest(line=line_):
                self.rejected(H + line_ + NL + '{"b":2}', IDS, 'malformed JSON line')
        failing = H + '["a","error","missing_data","x"]]' + NL + '{"b":2}'
        self.assertEqual(reasons(self.rejected(failing)), [(2, 'malformed JSON line')])

    def test_an_appended_correction_or_explanation_rejects_everything(self):
        good = H + '{"a":1}' + NL + '{"b":2}'
        for tail in (NL + 'Correction: job b should be 3.' + NL + '{"b":3}',
                     NL + '{"b":3}',
                     NL + '{"a":1}',
                     NL + 'Note: the above is final.',
                     NL + 'Corrected:' + NL + good,
                     NL + good,
                     NL + HEAD):
            with self.subTest(tail=tail):
                self.rejected(good + tail)
        self.assertEqual(parse_reply(good, IDS).accepted, {'a': 1, 'b': 2})
        # A leading explanation is no better.
        self.rejected('Here are the results:' + NL + good)
        self.rejected(H + 'Here are the results:' + NL + good[len(H):])

    def test_typographic_quotes_are_content_not_delimiters(self):
        content = '“quoted” ‘single’ «guillemets» „german“'
        parsed = parse_reply(text({'a': content}, {'b': {content: [content]}}), IDS)
        self.assertEqual((parsed.accepted, parsed.rejection), ({'a': content, 'b': {content: [content]}}, None))
        self.assertEqual(parse_reply(H + '{"a":"say “hi”"}' + NL + '{"b":2}', IDS).accepted['a'], 'say “hi”')
        for line_ in ('{“a”:1}', '{"a":“x”}', '{‘a’:1}', '“{"a":1}”',
                      '[“a”,"error","conflict","x"]', '["a","error",“conflict”,"x"]',
                      '["a","error","conflict",“x”]', '{"a":1}”'):
            with self.subTest(line=line_):
                self.rejected(H + line_ + NL + '{"b":2}', IDS, 'malformed JSON line')

    def test_a_success_value_that_looks_like_an_error_is_a_success(self):
        value = ['error', 'missing_data', 'text']
        parsed = parse_reply(text({'x': value}, {'y': ['y', 'error', 'conflict', 'z']}, {'z': 'error'}), ('x', 'y', 'z'))
        self.assertEqual((parsed.accepted, parsed.failed, parsed.rejection),
                         ({'x': value, 'y': ['y', 'error', 'conflict', 'z'], 'z': 'error'}, {}, None))
        # An error-shaped value does not register as a failure through regroup either.
        self.assertEqual(regroup(text({'x': value}), (('x', 0),)).outcomes, {'x': ('ok', '["error","missing_data","text"]')})

    def test_every_json_type_is_a_whole_result_value(self):
        values = [None, True, False, 0, -1, 2.5, '', 'unknown', [], {}, [[]], {'k': {}}, [1, 'a', None, {'z': [0]}]]
        for value in values:
            with self.subTest(value=value):
                parsed = parse_reply(text({'a': value}, {'b': 1}), IDS)
                self.assertEqual((parsed.accepted['a'], parsed.rejection), (value, None))

    def test_whitespace_only_lines_with_spaces_tabs_and_crlf_are_skipped(self):
        reply = ' \t \r\n' + 'OZ/1g\r\n' + '{"a":1}\r\n' + '\t\r\n' + '   \r\n' + '{"b":2}\r\n' + ' \t'
        parsed = parse_reply(reply, IDS)
        self.assertEqual((parsed.accepted, parsed.rejection, parsed.violations), ({'a': 1, 'b': 2}, None, ()))
        # Violation numbers still count the skipped lines.
        bad = parse_reply('\n\nOZ/1g\n\n{"a":1}\n  \nnot json\n{"b":2}', IDS)
        self.assertEqual(reasons(bad), [(7, 'malformed JSON line')])

    def test_a_line_of_only_nbsp_is_rejected(self):
        for junk in (' ', '  ', '   ', '\t '):
            with self.subTest(junk=repr(junk)):
                parsed = self.rejected(H + '{"a":1}' + NL + junk + NL + '{"b":2}', IDS, 'malformed JSON line')
                self.assertEqual(reasons(parsed), [(3, 'malformed JSON line')])
        self.rejected(H + ' ', IDS)

    def test_the_header_constant_is_oz_1g(self):
        self.assertEqual(HEADER, 'OZ/1g')

    def test_cr_alone_is_not_a_line_separator(self):
        self.rejected(H + '{"a":1}' + CR + '{"b":2}', IDS, 'malformed JSON line')
        self.rejected(H + '{"a":1}' + CR + '{"b":2}' + CR, IDS)
        # CR only ends a line as part of CRLF; inside a string it is escaped content.
        self.assertEqual(parse_reply(H + '{"a":"x\\ry"}' + NL + '{"b":2}', IDS).accepted['a'], 'x' + CR + 'y')
        self.rejected(H + '{"a":"x' + CR + 'y"}' + NL + '{"b":2}', IDS, 'malformed JSON line')

    def test_nan_and_infinity_are_rejected(self):
        for value in ('NaN', 'Infinity', '-Infinity', '[NaN]', '{"k":Infinity}', '1e999', '-1e999', '[1.5e999]'):
            with self.subTest(value=value):
                self.rejected(H + '{"a":' + value + '}' + NL + '{"b":2}', IDS, 'malformed JSON line')
        self.assertEqual(parse_reply(H + '{"a":1e300}' + NL + '{"b":-0.0}', IDS).accepted, {'a': 1e300, 'b': -0.0})

    def test_an_error_message_of_only_unicode_whitespace_is_rejected(self):
        reason = 'error message must be a nonblank string'
        for message in ('', ' ', '\t', '\n', ' ', ' ', '　', ' ', '\u0085', '    \n'):
            with self.subTest(message=repr(message)):
                line_ = json.dumps(['a', 'error', 'missing_data', message])
                self.rejected(H + line_ + NL + '{"b":1}', IDS, reason)
        parsed = parse_reply(text(['a', 'error', 'missing_data', ' x '], {'b': 1}), IDS)
        self.assertEqual(parsed.failed, {'a': ('missing_data', ' x ')})

    def test_an_error_line_must_name_an_expected_string_id_with_a_known_code(self):
        self.rejected(text(['zzz', 'error', 'conflict', 'x'], {'b': 1}), IDS, 'unknown or non-string id')
        self.rejected(text([1, 'error', 'conflict', 'x'], {'b': 1}), IDS, 'unknown or non-string id')
        self.rejected(text(['a', 'error', 'conflict', 'x'], ['a', 'error', 'conflict', 'x']), IDS, 'duplicate id a')
        self.rejected(text(['a', 'error', 'conflict', 'x'], {'a': 1}), IDS, 'duplicate id a')

    def test_a_reply_of_only_blank_lines_is_rejected(self):
        for reply in ('\n\n\n', ' \n\t\n  \n', '\r\n\r\n', '  ', '\t\t'):
            with self.subTest(reply=reply):
                parsed = self.rejected(reply, IDS, 'reply has no result line')
                self.assertEqual((parsed.received, reasons(parsed)), (0, [(0, 'reply has no result line')]))

    def test_nothing_is_normalized_or_repaired(self):
        # No trimming of IDs, no Unicode normalization (NFC e-acute vs e + combining acute), no type conversion.
        nfc, nfd = 'é', 'é'
        self.assertEqual(parse_reply(text({nfc: 1}), (nfc,)).accepted, {nfc: 1})
        self.rejected(text({nfd: 1}), (nfc,), 'unknown or non-string id')
        self.rejected(text({' a': 1}, {'b': 1}), IDS, 'unknown or non-string id')
        self.rejected(text({'A': 1}, {'b': 1}), IDS, 'unknown or non-string id')
        # A markdown fence or a tolerated 1f array is never repaired into a reply.
        self.rejected('```json' + NL + '{"a":1}' + NL + '{"b":2}' + NL + '```')
        self.rejected(H + '[{"a":1},{"b":2}]', IDS)
        self.rejected(H + '{"a":1}' + NL + '{"b":2}' + NL + '{"a":1}')


class HeaderRuleTests(unittest.TestCase):
    """The first nonblank line must be exactly OZ/1g (trailing spaces and tabs allowed, nothing before it)."""
    RECORDS = '{"a":1}' + NL + '{"b":2}'
    START = 'reply does not start with OZ/1g'
    LINE = 'first nonblank line must be OZ/1g'

    def start_rejected(self, reply, line, ids=IDS):
        parsed = parse_reply(reply, ids)
        self.assertEqual((parsed.accepted, parsed.failed, parsed.received, parsed.rejection),
                         ({}, {}, 0, self.START), reply)
        self.assertEqual(parsed.violations, ({'line': line, 'reason': self.LINE},), reply)
        return parsed

    def test_a_missing_header_rejects_the_whole_reply(self):
        self.start_rejected(self.RECORDS, 1)
        self.start_rejected(self.RECORDS + NL, 1)
        self.start_rejected(text(['a', 1], ['b', 2], header=None), 1)
        self.start_rejected('{"a":1}', 1, ('a',))
        self.start_rejected(CR + NL + self.RECORDS, 2)

    def test_the_violation_line_is_the_first_nonblank_line(self):
        self.start_rejected(NL + '  ' + NL + self.RECORDS, 3)
        self.start_rejected(' \t' + CR + NL + NL + 'Done.' + NL + H + self.RECORDS, 3)

    def test_blank_and_space_only_lines_before_the_header_are_skipped(self):
        for lead in (NL, NL * 3, ' ' + NL, '\t' + NL, ' \t ' + NL + NL, '  ' + CR + NL + NL, NL + ' ' + NL + '\t' + NL):
            with self.subTest(lead=lead):
                parsed = parse_reply(lead + H + self.RECORDS, IDS)
                self.assertEqual((parsed.accepted, parsed.rejection, parsed.violations, parsed.received),
                                 ({'a': 1, 'b': 2}, None, (), 2))

    def test_trailing_spaces_tabs_and_crlf_after_the_header_are_accepted(self):
        for header in ('OZ/1g ', 'OZ/1g\t', 'OZ/1g \t  ', 'OZ/1g' + CR, 'OZ/1g \t' + CR):
            with self.subTest(header=header):
                parsed = parse_reply(header + NL + self.RECORDS, IDS)
                self.assertEqual((parsed.accepted, parsed.rejection, parsed.violations, parsed.received),
                                 ({'a': 1, 'b': 2}, None, (), 2))
        crlf = 'OZ/1g\r\n{"a":1}\r\n{"b":2}\r\n'
        self.assertEqual(parse_reply(crlf, IDS).accepted, {'a': 1, 'b': 2})

    def test_leading_whitespace_before_the_header_rejects(self):
        for header in (' OZ/1g', '\tOZ/1g', '  OZ/1g  ', ' \tOZ/1g', '\xa0OZ/1g', '﻿OZ/1g', 'OZ/1g\xa0', 'OZ/1g\x0c'):
            with self.subTest(header=repr(header)):
                self.start_rejected(header + NL + self.RECORDS, 1)
                self.start_rejected(NL + header + NL + self.RECORDS, 2)

    def test_other_spellings_of_the_header_reject(self):
        for header in ('oz/1g', 'OZ/1G', 'Oz/1g', 'OZ/1g.', 'OZ/1g:', 'OZ/1g;', 'OZ/1g x', 'OZ/1gg', 'OZ/ 1g', 'OZ-1g',
                       '"OZ/1g"', "'OZ/1g'", '`OZ/1g`', '# OZ/1g', 'OZ/1f', 'OZ/9', 'OZ/1', '1g', 'OZ/1g' + CR + CR,
                       '"OZ/1g"' + ',', '["OZ/1g"]', '{"OZ/1g":1}'):
            with self.subTest(header=repr(header)):
                self.start_rejected(header + NL + self.RECORDS, 1)

    def test_a_header_only_reply_rejects_for_having_no_jobs(self):
        for reply in ('OZ/1g', H, 'OZ/1g \t' + NL, H + NL + ' ' + NL + NL, NL + H, 'OZ/1g' + CR + NL):
            with self.subTest(reply=reply):
                parsed = parse_reply(reply, IDS)
                self.assertEqual((parsed.accepted, parsed.failed, parsed.received), ({}, {}, 0))
                self.assertEqual(parsed.rejection, 'the reply does not cover exactly the expected jobs')
                self.assertEqual(reasons(parsed), [(0, 'the reply does not cover exactly the expected jobs')])
        grouped = regroup(H, (('a', 0), ('b', 0)))
        self.assertEqual({m: o[0] for m, o in grouped.outcomes.items()}, {'a': 'retry', 'b': 'retry'})

    def test_a_second_header_line_rejects_the_whole_reply(self):
        for name, reply, line_ in (('right after the header', H + H + self.RECORDS, 2),
                                   ('between records', H + '{"a":1}' + NL + H + '{"b":2}', 3),
                                   ('after the records', H + self.RECORDS + NL + HEAD, 4),
                                   ('after a blank line', H + NL + HEAD + NL + self.RECORDS, 3),
                                   ('padded', H + 'OZ/1g \t' + NL + self.RECORDS, 2)):
            with self.subTest(name=name):
                parsed = parse_reply(reply, IDS)
                self.assertEqual((parsed.accepted, parsed.failed), ({}, {}))
                self.assertEqual(parsed.rejection, 'a malformed or unknown line rejects the whole reply')
                self.assertEqual(reasons(parsed), [(line_, 'malformed JSON line')])

    def test_a_record_line_before_the_header_rejects(self):
        self.start_rejected('{"a":1}' + NL + H + '{"b":2}', 1)
        self.start_rejected(self.RECORDS + NL + HEAD, 1)
        self.start_rejected(NL + '{"b":2}' + NL + H + '{"a":1}', 2)
        self.start_rejected('["a","error","missing_data","x"]' + NL + H + '{"b":2}', 1)

    def test_a_rejected_header_rejects_every_job_through_regroup(self):
        grouped = regroup(self.RECORDS, (('a', 0), ('b', 0)), host_slots=(('h', 0, 'x'),))
        self.assertEqual({m: o[0] for m, o in grouped.outcomes.items()}, {'a': 'retry', 'b': 'retry', 'h': 'ok'})
        self.assertEqual(grouped.parsed.rejection, self.START)
        ok = regroup(H + self.RECORDS, (('a', 0), ('b', 0)))
        self.assertEqual({m: o for m, o in ok.outcomes.items()}, {'a': ('ok', '1'), 'b': ('ok', '2')})

    def test_error_lines_after_the_header_still_parse(self):
        parsed = parse_reply(H + '["a","error","conflict","no"]' + NL + '{"b":2}', IDS)
        self.assertEqual((parsed.failed, parsed.accepted, parsed.received), ({'a': ('conflict', 'no')}, {'b': 2}, 2))

    def test_encode_reply_starts_with_the_header_and_parses(self):
        reply = encode_reply({'a': 1, 'b': Failure('conflict', 'no')})
        self.assertTrue(reply.startswith('OZ/1g' + NL))
        self.assertEqual(reply.split(NL)[0], HEADER)
        parsed = parse_reply(reply, IDS)
        self.assertEqual((parsed.accepted, parsed.failed, parsed.rejection, parsed.received),
                         ({'a': 1}, {'b': ('conflict', 'no')}, None, 2))
        self.assertEqual(encode_reply({}), 'OZ/1g')
        self.assertEqual(encode_reply({'a': 1, 'b': 2}, ('b',)), 'OZ/1g' + NL + '{"b":2}')


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

    def test_a_valid_error_line_fails_that_job_and_commits_with_the_successes(self):
        job_map = (('a', 0), ('b', 0), ('c', 0))
        reply = text(['a', 'ok'], ['b', 'error', 'missing_data', 'Missing required field y.'],
                     ['c', 'error', 'invalid_data', 'x is not a number'])
        grouped = regroup(reply, job_map)
        self.assertEqual(grouped.outcomes, {'a': ('ok', 'ok'), 'b': ('failed', 'missing_data: Missing required field y.'),
                                            'c': ('failed', 'invalid_data: x is not a number')})
        self.assertEqual(grouped.values, {'a': '"ok"'})
        self.assertIsNone(grouped.parsed.rejection)

    def test_every_job_failing_is_still_an_accepted_reply(self):
        grouped = regroup(text(['a', 'error', 'conflict', 'no'], ['b', 'error', 'conflict', 'no']),
                          (('a', 0), ('b', 0)))
        self.assertEqual({m: o[0] for m, o in grouped.outcomes.items()}, {'a': 'failed', 'b': 'failed'})
        self.assertEqual(grouped.values, {})

    def test_a_multi_slot_job_with_one_failed_slot_fails_with_the_first_failure(self):
        job_map = (('a', 0), ('a', 1), ('a', 2), ('b', 0))
        reply = text(['a.0', 'fine'], ['a.1', 'error', 'invalid_data', 'second'],
                     ['a.2', 'error', 'missing_data', 'third'], ['b', 'v'])
        grouped = regroup(reply, job_map, host_slots=(('a', 3, 'cmd'),))
        self.assertEqual(grouped.outcomes, {'a': ('failed', 'invalid_data: second'), 'b': ('ok', 'v')})
        self.assertEqual(grouped.values, {'b': '"v"'})

    def test_a_bad_error_line_rejects_the_successes_too(self):
        grouped = regroup(text(['a', 'ok'], ['b', 'error', 'nope', 'x']), (('a', 0), ('b', 0)))
        self.assertEqual({m: o[0] for m, o in grouped.outcomes.items()}, {'a': 'retry', 'b': 'retry'})
        self.assertEqual(grouped.values, {})

    def test_non_text_reply_is_rejected(self):
        for bad in [None, {'results': ['x']}, ['x'], 3]:
            with self.subTest(bad=str(bad)), self.assertRaises(Error):
                regroup(bad, (('a', 0),))

    def test_encode_reply_round_trips_in_request_order(self):
        results = {'a': 'A', 'b': '  B' + NL}
        reply = encode_reply(results, ('a', 'b'))
        self.assertEqual(reply, H + '{"a":"A"}' + NL + '{"b":"  B' + chr(92) + 'n"}')
        self.assertEqual(regroup(reply, (('a', 0), ('b', 0))).outcomes,
                         {'a': ('ok', 'A'), 'b': ('ok', '  B' + NL)})
        self.assertEqual(regroup(encode_reply(results, ('b', 'a')), (('b', 0), ('a', 0))).outcomes['a'], ('ok', 'A'))
        failing = encode_reply({'a': Failure('missing_data', 'no y'), 'b': 'B'})
        self.assertEqual(failing, H + '["a","error","missing_data","no y"]' + NL + '{"b":"B"}')
        self.assertEqual(regroup(failing, (('a', 0), ('b', 0))).outcomes,
                         {'a': ('failed', 'missing_data: no y'), 'b': ('ok', 'B')})


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
        reply = H + '{"a":"x"}'
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

    def test_worker_request_has_adapter3_fields_and_stage_1g_packet(self):
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
        self.assertEqual(job_ids(request['prompt']), ['job_zq7'])
        self.assertEqual(request['system'], SYSTEM)
        self.assertNotIn('receipt', request['prompt'] + request['system'])
        self.assertEqual(request['prompt_tokens'], [len(request['system']) + 1 + len(request['prompt'])])
        self.assertEqual((result['language'], result['wire']), ('OZ/9', 'stage-1g'))
        self.assertNotIn('reply_mode', result)

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
            return answer_by_id(request, {'multi.0': 'audit text', 'multi.1': {'findings': []},
                                          'multi.2': 'observed', 'single': 'single value'})
        self.worker(adapter, batch_size=2).run_once()
        # The body groups by operation (audit, propose, observed); the reply binds by ID.
        self.assertEqual(job_ids(seen[0]['prompt']), ['multi.0', 'multi.1', 'single', 'multi.2'])
        self.assertEqual(job_instructions(seen[0]['prompt']),
                         [['multi.0', INSTRUCTIONS['a']], ['multi.1', INSTRUCTIONS['>']],
                          ['single', INSTRUCTIONS['>']], ['multi.2', INSTRUCTIONS['=']]])
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
        self.assertEqual(job_ids(seen[0]['prompt']), ['multi', 'other'])
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
            violations=[{'line': 3, 'reason': 'malformed JSON line'}, {'line': 4, 'reason': 'unknown or non-string id'}],
            binding='declared', semantic_verified=False))

    def test_object_reply_retries_every_job(self):
        self.post('multi', 'a7>12')
        result = self.worker(lambda request: {'reply': H + '{"results":["a","b"]}'}).run_once()
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
            self.assertEqual(job_ids(request['prompt']), ['job_a', 'job_b', 'job_c'])
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
        for bad_reply in ('legacy_object', 'prose', 'list_value', 'duplicate_everything', 'positional', 'repeated_reply'):
            with self.subTest(bad_reply=bad_reply):
                self.box.close()
                self.box = Inbox(clock=lambda: self.now[0])
                self.addCleanup(self.box.close)
                self.post('first')
                self.post('sibling')
                self.post('dependent', after=('first',))
                def adapter(request):
                    if bad_reply == 'legacy_object':
                        reply = H + json.dumps({'results': ['result', 'result']})
                    elif bad_reply == 'prose':
                        reply = H + 'Both jobs are done.'
                    elif bad_reply == 'list_value':
                        reply = ['result', 'result']
                    elif bad_reply == 'positional':
                        reply = text([0, 'a'], [1, 'b'])
                    elif bad_reply == 'repeated_reply':
                        reply = text(['first', 'a'], ['sibling', 'b']) + NL + text(['first', 'a'], ['sibling', 'b'])
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

    def test_job_failures_commit_with_the_successes_in_one_atomic_acceptance(self):
        import tempfile
        from pathlib import Path
        for mid in ('a', 'b', 'c'):
            self.post(mid)
        self.post('after_a', after=('a',))
        self.post('after_b', after=('b',))
        requests = []
        reply = (text(['a', 'ok'], ['b', 'error', 'missing_data', 'Missing required field y.'], ['c', 7]))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'calls.jsonl'
            worker = self.worker(lambda r: requests.append(r) or {'reply': reply, 'usage': {'output_tokens': 9}},
                                 batch_size=3, ledger_path=path)
            report = worker.run_once()
            end = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()][-1]
        self.assertEqual((report['status'], report['outcomes']), ('received', {'a': 'ok', 'b': 'failed', 'c': 'ok'}))
        self.assertEqual(self.box.stats(), {'done': 2, 'failed': 1, 'pending': 2})
        self.assertEqual((self.box.inspect('a')['result'], self.box.inspect('c')['result']), ('ok', '7'))
        failed = self.box.inspect('b')
        self.assertEqual((failed['state'], failed['error'], failed['attempts']),
                         ('failed', 'missing_data: Missing required field y.', 1))
        self.assertEqual((end['outcome'], end['validation']['accepted_results'], end['validation']['failed_results']),
                         ('job_error', 2, 1))
        self.assertEqual(end['validation']['violations'], [])
        # The successful predecessor releases its dependant; the failed one's dependant is never sent.
        worker.run_once()
        self.assertEqual(requests[1]['ids'], ['after_a'])
        self.assertEqual(self.box.inspect('after_b')['attempts'], 0)
        self.assertEqual(self.box.inspect('after_b')['waiting_for'], [{'id': 'b', 'state': 'failed'}])
        self.assertEqual(worker.run_once()['status'], 'idle')
        self.assertEqual(len(requests), 2)

    def test_every_job_failing_is_accepted_and_final(self):
        self.post('a')
        self.post('b')
        replies = [text(['a', 'error', 'conflict', 'no'], ['b', 'error', 'invalid_data', 'bad'])]
        worker = self.worker(lambda r: {'reply': replies.pop()}, batch_size=2)
        report = worker.run_once()
        self.assertEqual((report['status'], report['outcomes']), ('received', {'a': 'failed', 'b': 'failed'}))
        self.assertEqual(self.box.stats(), {'failed': 2})
        self.assertEqual(worker.run_once()['status'], 'idle')

    def test_a_malformed_error_line_rejects_the_successes_and_retries_everything(self):
        self.post('a')
        self.post('b')
        replies = iter([text(['a', 'fine'], ['b', 'error', 'timeout', 'x']), text(['a', 'one'], ['b', 'two'])])
        worker = self.worker(lambda r: {'reply': next(replies)}, batch_size=2, retry_delay=0)
        first = worker.run_once()
        self.assertEqual((first['status'], first['outcomes']), ('adapter_error', {'a': 'retry', 'b': 'retry'}))
        self.assertEqual(self.box.stats(), {'pending': 2})
        self.assertEqual(worker.run_once()['outcomes'], {'a': 'ok', 'b': 'ok'})

    def test_unknown_operation_is_rejected_for_every_job_the_worker_sends(self):
        self.post('a')
        replies = iter([text(['a', 'error', 'unknown_operation', 'Operation propose is not defined.']), text(['a', 'v'])])
        worker = self.worker(lambda r: {'reply': next(replies)}, retry_delay=0)
        self.assertEqual(worker.run_once()['outcomes'], {'a': 'retry'})
        self.assertEqual(worker.run_once()['outcomes'], {'a': 'ok'})

    def test_a_byte_identical_repeated_reply_is_rejected(self):
        self.post('a')
        self.post('b')
        once = text(['a', 'x'], ['b', 'y'])
        report = self.worker(lambda r: {'reply': once + NL + once}, batch_size=2).run_once()
        self.assertEqual((report['status'], report['outcomes']), ('adapter_error', {'a': 'retry', 'b': 'retry'}))

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

    def test_predecessor_result_travels_once_in_refs_and_is_named_by_each_dependant(self):
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
        self.assertEqual(list(body), ['v', 'goal', 'ops', 'refs', 'jobs'])
        self.assertEqual(body['refs'], ['Use 5 seconds per attempt', 'PREDECESSOR-RESULT'])
        self.assertEqual(request['prompt'].count('PREDECESSOR-RESULT'), 1)
        self.assertEqual(body['jobs'], [[0, ['a', 0, 1], ['b', 0, 1]]])

    def test_there_is_no_reply_mode(self):
        with self.assertRaises(TypeError):
            self.worker(lambda r: r, reply_mode='value')

    def test_the_one_system_text_is_sent(self):
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
        # Dependency declaration order q, p, r: indices follow it, values are JSON values (stored text stays a string).
        self.assertEqual(body['jobs'], [[0, ['z', 0, 1, 2, 3]]])
        self.assertEqual(body['refs'], ['Use 5 seconds per attempt',
                                        {'results': ['audit text', {'k': [1, None]}]},
                                        '{"older":"text"}', '[1, 2]'])
        self.assertIn(',{"results":["audit text",{"k":[1,null]}]},"{\\"older\\":\\"text\\"}","[1, 2]"]',
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

    def test_literal_texts_survive_batch_splits_retries_and_a_reopened_inbox(self):
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
                names.append((request['ids'], body['jobs'], body['ops']))
                if len(names) == 2:
                    return {'reply': 'prose'}
                return answer(request, *(['ok'] * len(body['jobs'])))
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
        # The wire carries the literal text itself, never a persisted number.
        self.assertEqual(by_id['n1'], ([[0, ['n1']]], ['first note']))
        self.assertEqual([(j, d) for ids, j, d in names if ids == ['n2']],
                         [([[0, ['n2']]], ['second note'])] * 2)
        self.assertEqual(by_id['n3'], ([[0, ['n3']]], ['first note']))
        self.assertEqual(by_id['n4'], ([[0, ['n4']]], ['third']))


if __name__ == '__main__':
    unittest.main()
