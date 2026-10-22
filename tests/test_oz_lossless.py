"""Clause 12, lossless values: validated value bytes survive regrouping, storage, reload, handoffs and oz do,
while the strict parser accepts and rejects exactly what it did before."""
import contextlib
import io
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

from oz import Error
from oz_batch import SYSTEM, render
from oz_cli import main
from oz_reply import MAX_RESULT_BYTES, RawJSON, dumps, loads, parse_reply, regroup
from oz_runtime import Inbox
from oz_worker import Worker
from oz_workspace import initialize
from test_oz2 import extended
from wire_helpers import body_of

CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}
COMPACT = dict(ensure_ascii=False, separators=(',', ':'), allow_nan=False)

# Source spellings an ordinary json.loads/json.dumps round trip would change.
SPELLINGS = [
    '12.50', '0.020', '1E5', '1e+05', '1.0e-3', '-0', '-0.0', '0E0', '1e300', '2.50E-10',
    '123456789012345678901234567890', '-98765432109876543210', '0.1000000000000000055511151231257827',
    r'"\u0041\/\"\\ caf\u00e9"', '"café Türkçe"', r'"tab\there"',
    '{ "len" : 12.50 , "u":0.020 }', '[ 1 ,2.0,\t-0 ]', '{"a":{"b":[ {"c":"\\u00e9"} ]}}',
    '[]', '{ }', 'true', 'null', '"  "', r'" "',
]


def reply(*pairs):
    """Reply text whose value bytes are exactly as given: one {"id":<raw>} line per (id, raw)."""
    return '\n'.join(['OZ/1g', *('{"%s":%s}' % pair for pair in pairs)]) + '\n'


class ParserUnchangedTests(unittest.TestCase):
    def test_loads_stays_float_based_and_strict(self):
        self.assertEqual(loads('12.50'), 12.5)
        self.assertIs(type(loads('12.50')), float)
        self.assertIs(type(loads('1E5')), float)
        self.assertIs(type(loads('123456789012345678901234567890')), int)
        for bad in ('1e400', '-1e400', 'NaN', 'Infinity', '{"a":1,"a":1}', '[{"k":1,"k":2}]'):
            with self.subTest(bad=bad), self.assertRaises((Error, ValueError)):
                loads(bad)

    def test_accepted_values_stay_decoded_and_texts_are_the_source_spelling(self):
        for raw in SPELLINGS:
            with self.subTest(raw=raw):
                parsed = parse_reply(reply(('a', raw)), ('a',))
                self.assertIsNone(parsed.rejection)
                self.assertEqual(parsed.accepted['a'], loads(raw))
                self.assertEqual(parsed.texts, {'a': raw})

    def test_rejections_are_unchanged(self):
        for line in ('{"a":1e400}', '{"a":-1e999}', '{"a":NaN}', '{"a":{"k":1,"k":2}}', '{"a":1,"a":1}',
                     '{"a":01}', '{"a":1.}', '{"a":.5}', '{"a":+1}', '{"a":"\ud800"}', '{"a":"\\ud800"}'):
            with self.subTest(line=line):
                parsed = parse_reply('OZ/1g\n' + line, ('a',))
                self.assertIsNotNone(parsed.rejection)
                self.assertEqual((parsed.accepted, parsed.texts), ({}, {}))

    def test_texts_match_the_decoded_value_for_random_spacing(self):
        rng = random.Random(12)
        ws = ['', ' ', '\t', '  ', ' \t ', '\r']
        def gen(depth):
            kind = rng.randrange(6 if depth < 3 else 4)
            pad = lambda: rng.choice(ws)
            if kind == 0:
                return rng.choice(['12.50', '-0', '1E+2', '7', '0.020', '-3.25e-7', '99999999999999999999'])
            if kind == 1:
                return rng.choice([r'"a\"b"', '"x y"', r'"\u00e9\n"', '""'])
            if kind == 2:
                return rng.choice(['true', 'false', 'null'])
            if kind == 3:
                return '[' + pad() + (',' + pad()).join(gen(depth + 1) for _ in range(rng.randrange(3))) + pad() + ']'
            keys = rng.sample('abcdefg', rng.randrange(4))
            return '{' + pad() + ','.join(f'{pad()}"{k}"{pad()}:{pad()}{gen(depth + 1)}{pad()}' for k in keys) + '}'
        for _ in range(300):
            value = gen(0)
            line = rng.choice(ws) + '{' + rng.choice(ws) + '"a"' + rng.choice(ws) + ':' + rng.choice(ws) + value \
                + rng.choice(ws) + '}' + rng.choice(ws)
            parsed = parse_reply('OZ/1g\n' + line, ('a',))
            self.assertIsNone(parsed.rejection, line)
            self.assertEqual(parsed.texts['a'], value)
            self.assertEqual(parsed.accepted['a'], loads(line)['a'])


class RegroupTests(unittest.TestCase):
    def test_the_reported_defect(self):
        grouped = regroup('OZ/1g\n{"job1":12.50}\n', [('job1', 0)])
        self.assertEqual(grouped.outcomes, {'job1': ('ok', '12.50')})
        self.assertEqual(grouped.values, {'job1': '12.50'})

    def test_single_slot_values_keep_their_bytes(self):
        for raw in SPELLINGS:
            with self.subTest(raw=raw):
                grouped = regroup(reply(('a', raw)), (('a', 0),))
                self.assertEqual(grouped.values, {'a': raw})
                native = loads(raw)
                stored = native if isinstance(native, str) and native.strip() else raw
                self.assertEqual(grouped.outcomes, {'a': ('ok', stored)})

    def test_multi_slot_values_keep_their_bytes_inside_a_compact_host_wrapper(self):
        grouped = regroup(reply(('a.0', '{ "len" : 12.50 }'), ('a.2', '1E5'), ('b', r'"\u00e9"')),
                          (('a', 0), ('a', 2), ('b', 0)), host_slots=(('a', 1, 'cmd'),))
        combined = '{"results":[{ "len" : 12.50 },"cmd",1E5]}'
        self.assertEqual(grouped.outcomes, {'a': ('ok', combined), 'b': ('ok', 'é')})
        self.assertEqual(grouped.values, {'a': combined, 'b': r'"\u00e9"'})

    def test_outcomes_are_judged_on_the_compact_form_as_before(self):
        # Spacing makes the source wrapper outgrow the limit that the compact form meets: same ok outcome,
        # stored compactly by the host.
        big = '"' + 'x' * (MAX_RESULT_BYTES // 2 - 40) + '"'
        spaced = '[' + ' ' * 200 + big + ']'
        grouped = regroup(reply(('a.0', spaced), ('a.1', spaced)), (('a', 0), ('a', 1)))
        status, text = grouped.outcomes['a']
        self.assertEqual(status, 'ok')
        self.assertEqual(text, json.dumps({'results': [loads(spaced)] * 2}, **COMPACT))
        self.assertLessEqual(len(text.encode('utf-8')), MAX_RESULT_BYTES)
        # A compact aggregate over the limit still retries.
        over = '"' + 'x' * (MAX_RESULT_BYTES // 2) + '"'
        self.assertEqual(regroup(reply(('a.0', over), ('a.1', over)), (('a', 0), ('a', 1))).outcomes['a'][0], 'retry')


class RawJSONTests(unittest.TestCase):
    def test_dumps_is_json_dumps_without_raw_values(self):
        value = {'k': [1, 2.5, None, 'é', {'n': True}], 'z': -0.0}
        self.assertEqual(dumps(value, **COMPACT), json.dumps(value, **COMPACT))
        self.assertEqual(dumps(value, indent=2), json.dumps(value, indent=2))

    def test_raw_values_are_written_verbatim_and_compare_by_value(self):
        raw = RawJSON('{ "len" : 12.50 }')
        self.assertEqual(dumps({'a': [raw, 'é']}, **COMPACT), '{"a":[{ "len" : 12.50 },"é"]}')
        self.assertEqual(raw, {'len': 12.5})
        self.assertEqual(raw['len'], 12.5)
        self.assertEqual(list(RawJSON('[1, 2]')), [1, 2])
        self.assertFalse(RawJSON('[]'))
        with self.assertRaises(TypeError):
            json.dumps(raw)
        with self.assertRaises(ValueError):
            dumps([raw], indent=2)


class InboxRoundTripTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'inbox.sqlite'
        self.ch = extended()

    def test_storage_reload_handoff_and_dependent_packet_keep_the_bytes(self):
        value = '{ "len" : 12.50 , "u":0.020, "e":1E+2, "z":-0.0, "n":123456789012345678901234567890, ' \
                '"s":"\\u0041\\"b\\" café" }'
        with Inbox(self.path) as box:
            box.post(self.ch, 'p', '>12', binding=self.ch.binding)
            box.post(self.ch, 'q', '>12', binding=self.ch.binding)
            box.post(self.ch, 'm', 'a7>12', binding=self.ch.binding)
            box.post(self.ch, 'd', '>12', binding=self.ch.binding, after=('p', 'q', 'm'))
            answers = {'p': value, 'q': '"plain \\u00e9 text"', 'm.0': '12.50', 'm.1': '[ -0 ]'}
            def adapter(request):
                ids = [row[0] for block in body_of(request['prompt'])['jobs'] for row in block[1:]]
                return {'reply': reply(*((mid, answers[mid]) for mid in ids))}
            report = Worker(box, self.ch, adapter, counters=[len], max_tokens=10000, capabilities=CAPS,
                            batch_size=3).run_once()
            self.assertEqual(report['status'], 'received')
        with Inbox(self.path) as box:  # reload from disk
            records = box.records(['p', 'q', 'm'])
            self.assertEqual((records['p']['result'], records['p']['result_json']), (value, value))
            self.assertEqual((records['q']['result'], records['q']['result_json']),
                             ('plain é text', '"plain \\u00e9 text"'))
            self.assertEqual(records['m']['result_json'], '{"results":[12.50,[ -0 ]]}')
            links = box._handoffs(['d'])
            self.assertEqual([link[2].text for link in links], [value, '"plain \\u00e9 text"', '{"results":[12.50,[ -0 ]]}'])
            seen = []
            def dependent(request):
                seen.append(request)
                return {'reply': reply(('d', '1'))}
            Worker(box, self.ch, dependent, counters=[len], max_tokens=10000, capabilities=CAPS).run_once()
        self.assertEqual(seen[0]['system'], SYSTEM)
        prompt = seen[0]['prompt']
        refs_text = prompt[prompt.index('"refs":[') + len('"refs":['):prompt.index('],"jobs":')]
        self.assertTrue(refs_text.endswith(','.join([value, '"plain \\u00e9 text"', '{"results":[12.50,[ -0 ]]}'])),
                        refs_text)
        self.assertEqual(body_of(prompt)['refs'][-3:], [loads(value), 'plain é text', {'results': [12.5, [0]]}])

    def test_render_without_raw_handoffs_is_unchanged_and_bad_stored_text_fails_closed(self):
        native = render(self.ch, [('a', '>12')], counters=[len], handoffs=[('a', 'p', {'v': 12.5})])
        raw = render(self.ch, [('a', '>12')], counters=[len], handoffs=[('a', 'p', RawJSON('{"v":12.5}'))])
        self.assertEqual((native.system, native.text), (raw.system, raw.text))
        for bad in ('1e400', '{"k":1,"k":2}', 'NaN'):
            with self.subTest(bad=bad), self.assertRaisesRegex(Error, 'handoff result must be a JSON value'):
                render(self.ch, [('a', '>12')], counters=[len], handoffs=[('a', 'p', RawJSON(bad))])


# Answers every job with the raw value text listed for it in values.json (default "1").
FAKE = r'''
import json, sys
from pathlib import Path
request = json.load(sys.stdin)
values = json.loads((Path(__file__).parent / 'values.json').read_text(encoding='utf-8'))
body = json.loads(request['prompt'])
lines = ['OZ/1g'] + ['{"%s":%s}' % (row[0], values.get(row[0], '1')) for block in body['jobs'] for row in block[1:]]
json.dump({'reply': '\n'.join(lines), 'usage': {'input_tokens': 10, 'output_tokens': 5}}, sys.stdout)
'''


class DoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'ws'
        initialize(self.root)
        (self.root / 'fake.py').write_text(FAKE, encoding='utf-8')
        (self.root / 'adapter.json').write_text(json.dumps({'argv': [sys.executable, 'fake.py'], **CAPS}),
                                                encoding='utf-8')

    def test_cli_result_and_value_files_carry_the_validated_bytes(self):
        values = {'j1': '12.50', 'j2': '{ "u" : 0.020, "z":-0.0, "n":123456789012345678901234567890 }',
                  'j3': '"\\u0041\\/ café"', 'j4': '[ "' + 'x' * 300 + '", 1E5 ]'}
        (self.root / 'values.json').write_text(json.dumps(values), encoding='utf-8')
        req = {'request_id': 'k1', 'goal': 'Report length facts only.', 'ops': {'extract': 'Extract the length.'},
               'refs': {'c1': 'length=12.50 mm'}, 'jobs': [[m, 'extract', 'c1'] for m in values],
               'allow_experimental': True, 'max_input_tokens': 100000, 'max_inline_bytes': 200}
        out, err = io.StringIO(), io.StringIO()
        stdin = io.TextIOWrapper(io.BytesIO(json.dumps(req).encode('utf-8')), encoding='utf-8')
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch('sys.stdin', stdin):
            code = main(['do', '--workspace', str(self.root), '--adapter', str(self.root / 'adapter.json')])
        self.assertEqual(code, 0, err.getvalue())
        text = out.getvalue()
        for mid in ('j1', 'j2', 'j3'):
            self.assertIn('"%s":{"status":"accepted","value":%s}' % (mid, values[mid]), text)
        result = json.loads(text)
        self.assertEqual(result['jobs']['j1']['value'], 12.5)
        big = result['jobs']['j4']
        self.assertEqual((self.root / big['value_file']).read_text(encoding='utf-8'), values['j4'])
        self.assertEqual(big['bytes'], len(values['j4'].encode('utf-8')))


if __name__ == '__main__':
    unittest.main()
