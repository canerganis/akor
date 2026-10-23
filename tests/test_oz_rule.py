"""oz-rule/1: spec conformance vectors, worked and invalid ASTs, bounds, exact decimals, admission, and a no-raise fuzz."""
import decimal
import hashlib
import json
from pathlib import Path
import random
import unittest

from oz_rule import admit, canonical_value_text, evaluate, label_ok, validate
from test_oz_registry import decimal_cases, make_registry, operation

COMPACT = dict(ensure_ascii=False, separators=(',', ':'))
SPEC = Path(__file__).resolve().parent.parent / 'docs' / 'design' / 'ozmap-2026-10-24' / 'oz-rule-1-spec.md'


def ast(expr):
    return json.dumps({'lang': 'oz-rule/1', 'expr': expr}, **COMPACT).encode('utf-8')


E = ('{"lang":"oz-rule/1","expr":["list",["field","length"],["field","uncertainty"],["field","n"],'
     '["field","method"],["field","basis"],["field","physical_validation"]]}')
B = ('{"lang":"oz-rule/1","expr":["if",["eq",["field","uncertainty"],["s","unknown"]],["s","unknown"],'
     '["require",["le",["d","0"],["num",["field","uncertainty"],"mm"]],["list",["fmt",["sub",["num",["field","length"],"mm"],'
     '["num",["field","uncertainty"],"mm"]],2,"mm"],["fmt",["add",["num",["field","length"],"mm"],'
     '["num",["field","uncertainty"],"mm"]],2,"mm"]]]]}')
M = ('{"lang":"oz-rule/1","expr":["cat",["if",["eq",["field","uncertainty"],["s","unknown"]],["list",["s","uncertainty"]],["list"]],'
     '["if",["eq",["field","method"],["s","unknown"]],["list",["s","method"]],["list"]],'
     '["if",["eq",["field","basis"],["s","unknown"]],["list",["s","basis"]],["list"]]]}')
V = ('{"lang":"oz-rule/1","expr":["if",["eq",["field","uncertainty"],["s","unknown"]],["s","unknown"],'
     '["require",["le",["d","0"],["num",["field","uncertainty"],"mm"]],["if",["le",["d","12.48"],'
     '["sub",["num",["field","length"],"mm"],["num",["field","uncertainty"],"mm"]]],["if",["le",["add",'
     '["num",["field","length"],"mm"],["num",["field","uncertainty"],"mm"]],["d","12.52"]],["s","inside"],["s","outside"]],'
     '["s","outside"]]]]}')
T = '{"lang":"oz-rule/1","expr":["at",["split",["input"],"|"],1]}'
L = '{"lang":"oz-rule/1","expr":["lookup",["input"],[["A","alpha"],["B","beta"]]]}'
ASTS = {'E': E.encode(), 'B': B.encode(), 'M': M.encode(), 'V': V.encode(), 'T': T.encode(), 'L': L.encode()}

INVALID = [
    '{"lang":"oz-rule/1","expr":["eval","1+1"]}',
    '{"lang":"oz-rule/1","expr":["add",["s","1"],["d","2"]]}',
    '{"lang":"oz-rule/1","expr":["lookup",["input"],[["a","x"],["a","y"]]]}',
]

ABSTAIN = {'status': 'abstain'}
VECTORS = [
    ["length=12.50 mm; uncertainty=0.02 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed", "E", ["12.50 mm", "0.02 mm", "3", "unknown", "unknown", "not_claimed"]],
    ["length=12.500 mm; uncertainty=0.020 mm; n=03; method=x; basis=y; physical_validation=not_claimed", "E", ["12.500 mm", "0.020 mm", "03", "x", "y", "not_claimed"]],
    ["length=12.50 mm; uncertainty=0.02 mm; method=x; basis=y; physical_validation=not_claimed", "E", ABSTAIN],
    ["length=12.50 mm; uncertainty=0.02 mm", "B", ["12.48 mm", "12.52 mm"]],
    ["uncertainty=unknown", "B", "unknown"],
    ["length=12.50 mm", "B", ABSTAIN],
    ["length=twelve mm; uncertainty=0.02 mm", "B", ABSTAIN],
    ["length=12.50 cm; uncertainty=0.02 mm", "B", ABSTAIN],
    ["length=12.50 mm; uncertainty=-0.02 mm", "B", ABSTAIN],
    ["length=12.505 mm; uncertainty=0.010 mm", "B", ["12.50 mm", "12.52 mm"]],
    ["length=12.50 mm; uncertainty=0.02 mm", "V", "inside"],
    ["length=12.49 mm; uncertainty=0.02 mm", "V", "outside"],
    ["length=12.51 mm; uncertainty=0.02 mm", "V", "outside"],
    ["length=12.48 mm; uncertainty=0 mm", "V", "inside"],
    ["uncertainty=unknown", "V", "unknown"],
    ["length=12.50 mm; length=12.51 mm; uncertainty=0.02 mm", "V", ABSTAIN],
    ["uncertainty=0.02 mm; method=unknown; basis=unknown", "M", ["method", "basis"]],
    ["uncertainty=0.02 mm; method=caliper; basis=repeatability", "M", []],
    ["uncertainty=unknown; method=unknown; basis=unknown", "M", ["uncertainty", "method", "basis"]],
    ["uncertainty=Unknown; method=caliper; basis=repeatability", "M", []],
    ["a||b", "T", ""],
    ["a", "T", ABSTAIN],
    ["A", "L", "alpha"],
    ["C", "L", ABSTAIN],
]


def depth(n):
    return 1 + max([depth(c) for c in n[1:] if isinstance(c, list) and c and isinstance(c[0], str)] or [0])


def run(expr_or_bytes, text=''):
    data = expr_or_bytes if isinstance(expr_or_bytes, bytes) else ast(expr_or_bytes)
    return evaluate(data, text)


def nest(levels):
    """An if-chain whose expression depth is exactly `levels`."""
    node = ['s', 'x']
    for _ in range(levels - 1):
        node = ['if', ['bool', True], node, ['s', 'x']]
    return node


class Conformance(unittest.TestCase):
    def test_vector_count(self):
        self.assertEqual(len(VECTORS), 24)

    def test_all_vectors(self):
        for text, name, expected in VECTORS:
            with self.subTest(text=text, ast=name):
                r = evaluate(ASTS[name], text)
                if expected == ABSTAIN:
                    self.assertEqual(r['status'], 'abstain')
                else:
                    self.assertEqual(r['status'], 'value')
                    self.assertEqual(r['value'], expected)

    def test_result_shape(self):
        r = evaluate(ASTS['V'], 'length=12.50 mm; uncertainty=0.02 mm')
        self.assertEqual(list(r), ['status', 'type', 'value', 'steps'])
        self.assertEqual(r['type'], 'string')
        a = evaluate(ASTS['B'], 'length=12.50 mm')
        self.assertEqual(list(a), ['status', 'reason', 'steps'])
        self.assertEqual(a['reason'], 'missing')

    def test_types_reported(self):
        self.assertEqual(run(['d', '12.50'])['type'], 'decimal')
        self.assertEqual(run(['d', '12.50'])['value'], '12.5')
        self.assertEqual(run(['d', '0.0'])['value'], '0')
        self.assertEqual(run(['bool', False])['type'], 'bool')
        self.assertIs(run(['bool', False])['value'], False)
        self.assertEqual(run(['list'])['type'], 'list')
        self.assertEqual(run(['list'])['value'], [])
        self.assertEqual(run(['d', '100'])['value'], '100')

    def test_spec_blocks_match_embedded_asts(self):
        if not SPEC.exists():
            self.skipTest('spec not present')
        lines = {l.strip() for l in SPEC.read_text(encoding='utf-8').splitlines() if l.startswith('{"lang"')}
        for name, data in ASTS.items():
            self.assertIn(data.decode(), lines, name)
        for bad in INVALID:
            self.assertIn(bad, lines)


class Worked(unittest.TestCase):
    def test_sizes_and_depths(self):
        for name, size, dep in (('E', 162, 2), ('B', 356, 7), ('M', 289, 4), ('V', 420, 8)):
            with self.subTest(name=name):
                data = ASTS[name]
                self.assertEqual(len(data), size)
                self.assertEqual(depth(json.loads(data)['expr']), dep)
                self.assertEqual(validate(data), (True, ''))

    def test_invalid_asts(self):
        for text in INVALID:
            with self.subTest(text=text):
                ok, reason = validate(text.encode())
                self.assertFalse(ok)
                self.assertTrue(reason)
                r = evaluate(text.encode(), 'a')
                self.assertEqual(r, {'status': 'abstain', 'reason': 'invalid_ast', 'steps': 0})


class Syntax(unittest.TestCase):
    def bad(self, data):
        ok, _ = validate(data)
        self.assertFalse(ok, data)
        self.assertEqual(evaluate(data, 'x')['reason'], 'invalid_ast')

    def test_duplicate_keys(self):
        self.bad(b'{"lang":"oz-rule/1","lang":"oz-rule/1","expr":["input"]}')
        self.bad(b'{"lang":"oz-rule/1","expr":["input"],"expr":["input"]}')

    def test_bom(self):
        self.bad(b'\xef\xbb\xbf' + ast(['input']))

    def test_trailing_content(self):
        self.bad(ast(['input']) + b' x')
        self.bad(ast(['input']) + ast(['input']))
        self.assertTrue(validate(ast(['input']) + b'\n')[0])  # whitespace is not content

    def test_not_utf8_and_surrogates(self):
        self.bad(b'{"lang":"oz-rule/1","expr":["s","\xff"]}')
        self.bad(b'{"lang":"oz-rule/1","expr":["s","\\ud800"]}')
        self.bad(b'{"lang":"oz-rule/1","expr":["lookup",["input"],[["\\udc00","x"]]]}')
        self.assertTrue(validate(b'{"lang":"oz-rule/1","expr":["s","\\ud83d\\ude00"]}')[0])  # a valid pair

    def test_envelope(self):
        self.bad(b'')
        self.bad(b'[]')
        self.bad(b'{"lang":"oz-rule/1"}')
        self.bad(b'{"lang":"oz-rule/2","expr":["input"]}')
        self.bad(b'{"lang":"oz-rule/1","expr":["input"],"extra":1}')
        self.bad(b'{"lang":"oz-rule/1","expr":["input"],"x":NaN}')

    def test_shapes(self):
        for expr in (['input', 1], ['s'], ['s', 1], ['s', 'a', 'b'], ['bool', 'true'], ['bool', 1], [], 'input',
                     ['at', ['list'], -1], ['at', ['list'], 1.0], ['at', ['list'], True], ['split', ['input'], ''],
                     ['fmt', ['d', '1'], 13, ''], ['fmt', ['d', '1'], -1, ''], ['fmt', ['d', '1'], 1.5, ''],
                     ['field', 1], ['field'], ['field', None], ['d', '01'], ['d', '1.'], ['d', '1e5'],
                     ['d', '+1'], ['d', ' 1'], ['d', '1' * 39], ['d', '0.0000000000001'], [['s', 'a']], [1],
                     ['lookup', ['input'], 'x'], ['lookup', ['input'], [['a']]], ['lookup', ['input'], [['a', 1]]],
                     ['lookup', ['input'], [['a', 'x', 'y']]], ['num', ['input']], ['list', 1], ['cat', ['s', 'a']]):
            with self.subTest(expr=expr):
                self.bad(ast(expr))

    def test_types_propagate_through_if(self):
        mixed = ['if', ['bool', True], ['s', 'a'], ['list']]
        self.assertTrue(validate(ast(mixed))[0])  # string or list is fine at the root
        self.assertEqual(run(mixed)['value'], 'a')
        self.bad(ast(['add', mixed, ['d', '1']]))
        self.bad(ast(['add', ['if', ['bool', True], ['d', '1'], ['s', 'x']], ['d', '1']]))
        self.bad(ast(['if', ['s', 'x'], ['s', 'a'], ['s', 'b']]))
        self.bad(ast(['require', ['d', '1'], ['s', 'a']]))
        self.bad(ast(['eq', ['s', 'a'], ['d', '1']]))
        self.bad(ast(['eq', ['list'], ['list']]))
        self.bad(ast(['eq', ['if', ['bool', True], ['s', 'a'], ['d', '1']], ['s', 'a']]))
        self.assertTrue(validate(ast(['eq', ['if', ['bool', True], ['s', 'a'], ['s', 'b']], ['s', 'a']]))[0])
        self.assertTrue(validate(ast(['eq', ['bool', True], ['bool', False]]))[0])
        self.assertTrue(validate(ast(['add', ['if', ['bool', True], ['d', '1'], ['d', '2']], ['d', '1']]))[0])

    def test_lookup_table_limits(self):
        table = [['k%d' % i, 'v'] for i in range(32)]
        self.assertTrue(validate(ast(['lookup', ['input'], table]))[0])
        self.bad(ast(['lookup', ['input'], table + [['k32', 'v']]]))
        self.assertTrue(validate(ast(['lookup', ['input'], []]))[0])
        self.assertEqual(run(['lookup', ['input'], table], 'k7')['value'], 'v')


class Bounds(unittest.TestCase):
    def test_depth(self):
        self.assertEqual(depth(nest(16)), 16)
        self.assertTrue(validate(ast(nest(16)))[0])
        self.assertFalse(validate(ast(nest(17)))[0])
        self.assertEqual(run(nest(17))['reason'], 'invalid_ast')

    def test_node_count(self):
        self.assertTrue(validate(ast(['list'] + [['s', 'a']] * 127))[0])  # 128 nodes
        ok, _ = validate(ast(['list'] + [['s', 'a']] * 128))  # 129 nodes
        self.assertFalse(ok)

    def test_ast_bytes(self):
        base = ast(['input'])
        self.assertTrue(validate(base + b' ' * (2048 - len(base)))[0])
        self.assertFalse(validate(base + b' ' * (2049 - len(base)))[0])
        self.assertEqual(len(base + b' ' * (2049 - len(base))), 2049)

    def test_input_limit(self):
        self.assertEqual(run(['s', 'a'], 'x' * 8192)['status'], 'value')
        r = run(['s', 'a'], 'x' * 8193)
        self.assertEqual((r['status'], r['reason'], r['steps']), ('abstain', 'input', 0))
        multi = 'é' * 4097  # 8194 bytes
        self.assertEqual(run(['s', 'a'], multi)['reason'], 'input')
        self.assertEqual(run(['s', 'a'], 'a\ud800')['reason'], 'input')

    def test_step_accounting(self):
        self.assertEqual(run(['s', 'ab'])['steps'], 1 + 2 + 2 + 4)  # node, literal, result, serialized '"ab"'
        self.assertEqual(run(['bool', True])['steps'], 1 + 4)
        self.assertEqual(run(['input'], 'abc')['steps'], 1 + 3 + 3 + 5)
        self.assertEqual(run(['d', '1.5'])['steps'], 1 + 3 + 5)  # serialized '"1.5"'
        self.assertEqual(run(['lookup', ['s', 'a'], [['a', 'xy'], ['b', 'z']]])['steps'],
                         (1 + 1 + 1) + (1 + 1 + 5 + 2) + 4)  # s node, lookup node with operand, table and result, serialized
        self.assertEqual(run(['list', ['s', 'a'], ['s', 'b']])['steps'], 3 + 3 + (1 + 2) + 2 + 9)

    def test_caching_does_not_change_charges(self):
        one = run(['field', 'a'], 'a=1')['steps']
        two = run(['list', ['field', 'a'], ['field', 'a']], 'a=1')['steps']
        self.assertEqual(two - one * 2, (1 + 2) + 2 + (9 - 2 * 3))  # list node, its result, serialization of two items vs two singles

    def test_step_budget(self):
        r = run(['list', ['input'], ['input']], 'x' * 8192)
        self.assertEqual((r['status'], r['reason'], r['steps']), ('abstain', 'limit', 32768))

    def test_list_limit(self):
        self.assertEqual(len(run(['split', ['input'], '|'], '|'.join('a' * 64))['value']), 64)
        r = run(['split', ['input'], '|'], '|' * 64)
        self.assertEqual((r['status'], r['reason']), ('abstain', 'limit'))
        self.assertEqual(run(['cat', ['split', ['input'], '|'], ['split', ['input'], '|']], '|' * 40)['reason'], 'limit')

    def test_result_size(self):
        self.assertEqual(run(['input'], 'a' * 4094)['status'], 'value')  # 4096 serialized bytes
        r = run(['input'], 'a' * 4095)
        self.assertEqual((r['status'], r['reason']), ('abstain', 'limit'))

    def test_string_limit(self):
        self.assertEqual(run(['fmt', ['d', '1'], 0, 'u' * 100])['status'], 'value')


class Numbers(unittest.TestCase):
    def dec(self, text, expr=None):
        r = run(expr or ['num', ['input'], ''], text)
        return r['value'] if r['status'] == 'value' else r['reason']

    def test_numeral_grammar(self):
        for good, out in (('0', '0'), ('-0', '0'), ('12', '12'), ('-12.50', '-12.5'), ('0.001', '0.001'), ('100', '100'),
                          ('1' * 38, '1' * 38), ('0.' + '1' * 12, '0.' + '1' * 12)):
            self.assertEqual(self.dec(good), out)
        for bad in ('01', '00', '+1', '1.', '.5', '-', '', '1e5', '1E5', ' 1', '1 ', '1\n', 'NaN', 'inf', '1,5',
                    '١', '1' * 39, '0.' + '1' * 13, '-0.0000000000001'):
            self.assertEqual(self.dec(bad), 'number', repr(bad))

    def test_unit_rule(self):
        e = ['num', ['input'], 'mm']
        self.assertEqual(self.dec('12.5 mm', e), '12.5')
        for bad in ('12.5mm', '12.5  mm', '12.5 MM', '12.5 cm', '12.5', 'mm', ' mm'):
            self.assertIn(self.dec(bad, e), ('unit', 'number'), repr(bad))
        self.assertEqual(self.dec('12.5mm', e), 'unit')
        self.assertEqual(self.dec(' mm', e), 'number')
        self.assertEqual(self.dec('12.5 mm', ['num', ['input'], '']), 'number')  # empty unit parses the whole string

    def test_exact_arithmetic(self):
        e = ['add', ['num', ['input'], ''], ['d', '0.2']]
        self.assertEqual(self.dec('0.1', e), '0.3')
        self.assertEqual(self.dec('0.1', ['sub', ['d', '0.3'], ['num', ['input'], '']]), '0.2')
        self.assertEqual(self.dec('-5', ['add', ['num', ['input'], ''], ['d', '5']]), '0')
        # D4: the carry to 10**38 has a one digit normalized coefficient, so it is a permitted result.
        self.assertEqual(self.dec('1', ['add', ['d', '9' * 38], ['num', ['input'], '']]), '1' + '0' * 38)
        self.assertEqual(self.dec('2', ['add', ['d', '9' * 38], ['num', ['input'], '']]), 'number')  # 39 coefficient digits
        self.assertEqual(self.dec('1', ['sub', ['d', '9' * 38], ['num', ['input'], '']]), '9' * 37 + '8')
        big = ['add', ['d', '9' * 20], ['d', '9' * 20]]
        self.assertEqual(self.dec('', big), str(2 * (10 ** 20 - 1)))

    def test_result_scale_limit(self):
        tiny = ['d', '0.' + '0' * 11 + '1']  # 1e-12
        self.assertEqual(run(['add', tiny, ['d', '0']])['value'], '0.000000000001')
        self.assertEqual(run(['sub', tiny, ['d', '1']])['value'], '-0.999999999999')

    def test_comparison_uses_unrounded(self):
        e = ['le', ['num', ['input'], ''], ['d', '12.5']]
        self.assertTrue(run(e, '12.5')['value'])
        self.assertFalse(run(e, '12.500000000001')['value'])
        self.assertTrue(run(['le', ['d', '12.48'], ['d', '12.480']])['value'])

    def test_fmt(self):
        f = lambda t, p, u='': run(['fmt', ['num', ['input'], ''], p, u], t)['value']
        self.assertEqual(f('2.5', 0), '2')  # half to even
        self.assertEqual(f('3.5', 0), '4')
        self.assertEqual(f('12.505', 2, 'mm'), '12.50 mm')
        self.assertEqual(f('12.515', 2, 'mm'), '12.52 mm')
        self.assertEqual(f('12.5', 3), '12.500')
        self.assertEqual(f('100', 2), '100.00')
        self.assertEqual(f('0.0000001', 12), '0.000000100000')
        self.assertEqual(f('-1.25', 1), '-1.2')
        self.assertEqual(f('12', 0, 'mm'), '12 mm')

    def test_negative_zero_suppressed(self):
        f = lambda t, p: run(['fmt', ['num', ['input'], ''], p, ''], t)['value']
        self.assertEqual(f('-0.001', 2), '0.00')
        self.assertEqual(f('-0.4', 0), '0')
        self.assertEqual(f('-0', 1), '0.0')
        self.assertEqual(run(['num', ['input'], ''], '-0')['value'], '0')
        self.assertEqual(run(['sub', ['d', '-0'], ['d', '0']])['value'], '0')
        self.assertEqual(run(['add', ['d', '-0'], ['d', '-0.0']])['value'], '0')
        self.assertEqual(f('-0.6', 0), '-1')

    def test_ambient_context_irrelevant(self):
        saved = decimal.getcontext().copy()
        try:
            ctx = decimal.getcontext()
            ctx.prec = 2
            ctx.rounding = decimal.ROUND_DOWN
            ctx.traps[decimal.Inexact] = True
            ctx.traps[decimal.Rounded] = True
            for text, name, expected in VECTORS:
                r = evaluate(ASTS[name], text)
                if expected == ABSTAIN:
                    self.assertEqual(r['status'], 'abstain', text)
                else:
                    self.assertEqual(r['value'], expected, text)
            self.assertEqual(run(['add', ['d', '123456.789'], ['d', '0.001']])['value'], '123456.79')
            self.assertEqual(run(['fmt', ['d', '2.675'], 2, ''])['value'], '2.68')
            self.assertEqual(decimal.getcontext().prec, 2)
        finally:
            decimal.setcontext(saved)


class Records(unittest.TestCase):
    def field(self, text, key='a'):
        r = run(['field', key], text)
        return r['value'] if r['status'] == 'value' else r['reason']

    def test_valid_records(self):
        self.assertEqual(self.field('a=1'), '1')
        self.assertEqual(self.field('_x9=v; a=  spaced '), '  spaced ')
        self.assertEqual(self.field('b=2; a=Ünï'), 'Ünï')
        self.assertEqual(self.field('b=2; a=1', 'b'), '2')
        self.assertEqual(self.field('b=2; a=1', 'c'), 'missing')

    def test_malformed_records(self):
        for text in ('', 'a', 'a=', '=1', 'a=1;', 'a=1; ', 'a=1; ; b=2', 'a=1;b=2', 'a=1; b', 'a=1; b=', 'a==1',
                     'a=1=2', 'A=1; b=2', '1a=1', 'a b=1', 'a=1; a=2', 'a=1;  b=2', 'a=1\n', 'a=1\r', 'a=x\ny; b=2',
                     'a =1', 'a=1, b=2', ' a=1'):
            with self.subTest(text=text):
                self.assertEqual(self.field(text), 'input')

    def test_malformed_record_elsewhere_is_ignored_without_field(self):
        self.assertEqual(run(['input'], 'not a record')['value'], 'not a record')
        self.assertEqual(run(['at', ['split', ['input'], ';'], 0], 'x;y')['value'], 'x')

    def test_field_does_not_validate_numbers(self):
        self.assertEqual(self.field('a=twelve'), 'twelve')


class Semantics(unittest.TestCase):
    def test_lazy_if_and_require(self):
        bad = ['field', 'missing']
        self.assertEqual(run(['if', ['bool', True], ['s', 'a'], bad], 'x=1')['value'], 'a')
        self.assertEqual(run(['if', ['bool', False], bad, ['s', 'b']], 'x=1')['value'], 'b')
        self.assertEqual(run(['require', ['bool', False], bad], 'x=1')['reason'], 'guard')
        self.assertEqual(run(['require', ['bool', True], ['s', 'ok']])['value'], 'ok')

    def test_left_to_right_and_propagation(self):
        r = run(['list', ['field', 'first'], ['field', 'second']], 'x=1')
        self.assertEqual(r['reason'], 'missing')
        steps_first = run(['field', 'first'], 'x=1')['steps']
        self.assertGreaterEqual(r['steps'], steps_first)
        self.assertEqual(run(['list', ['s', 'a'], ['at', ['list'], 0]])['reason'], 'index')

    def test_split_and_at(self):
        self.assertEqual(run(['split', ['input'], '||'], 'a||b||')['value'], ['a', 'b', ''])
        self.assertEqual(run(['split', ['input'], ','], '')['value'], [''])
        self.assertEqual(run(['at', ['split', ['input'], '|'], 0], '|x')['value'], '')

    def test_eq_scalars(self):
        self.assertTrue(run(['eq', ['s', 'a'], ['s', 'a']])['value'])
        self.assertFalse(run(['eq', ['s', 'a'], ['s', 'A']])['value'])
        self.assertTrue(run(['eq', ['d', '1.0'], ['d', '1']])['value'])
        self.assertFalse(run(['eq', ['bool', True], ['bool', False]])['value'])

    def test_string_values_are_exact(self):
        text = 'v=12.50 mm; w=café "q" \\ ☃'
        r = run(['field', 'v'], text)
        self.assertEqual(r['value'], '12.50 mm')
        r = run(['field', 'w'], text)
        self.assertEqual(r['value'], 'café "q" \\ ☃')
        self.assertEqual(canonical_value_text(r), '"café \\"q\\" \\\\ ☃"')

    def test_cat_and_list(self):
        r = run(['cat', ['list', ['s', 'a']], ['list'], ['list', ['s', 'b'], ['s', 'c']]])
        self.assertEqual(r['value'], ['a', 'b', 'c'])
        self.assertEqual(run(['cat'])['value'], [])


class Canonical(unittest.TestCase):
    def test_texts(self):
        self.assertEqual(canonical_value_text(run(['s', 'inside'])), '"inside"')
        self.assertEqual(canonical_value_text(run(['d', '12.50'])), '"12.5"')
        self.assertEqual(canonical_value_text(run(['bool', True])), 'true')
        self.assertEqual(canonical_value_text(run(['list', ['s', 'a'], ['s', 'b\n']])), '["a","b\\n"]')
        self.assertEqual(canonical_value_text(run(['list'])), '[]')
        self.assertEqual(canonical_value_text(run(['s', 'xé\u0001'])), '"xé\\u0001"')
        self.assertIsNone(canonical_value_text(run(['field', 'a'], 'b=1')))
        self.assertEqual(canonical_value_text(evaluate(ASTS['B'], 'length=12.50 mm; uncertainty=0.02 mm')),
                         '["12.48 mm","12.52 mm"]')


class Amendment(unittest.TestCase):
    """oz-rule/1 amendment 1: D3 steps, D4 decimals, D5 field keys, D9 decimal strings."""

    def test_d3_vector_1_if(self):
        r = run(['if', ['bool', True], ['s', 'x'], ['s', 'y']])
        self.assertEqual(r, {'status': 'value', 'type': 'string', 'value': 'x', 'steps': 10})

    def test_d3_vector_2_failed_child(self):
        r = run(['cat', ['require', ['bool', True], ['list', ['s', 'x']]], ['list', ['field', 'z']]], 'a=b')
        self.assertEqual(r, {'status': 'abstain', 'reason': 'missing', 'steps': 18})

    def test_d3_vector_3_limit_saturates(self):
        r = run(['require', ['bool', True], ['input']], 'x' * 8192)
        self.assertEqual(r, {'status': 'abstain', 'reason': 'limit', 'steps': 32768})

    def test_d3_vectors_through_the_wrapper_text(self):
        wrapped = b'{"lang":"oz-rule/1","expr":["if",["bool",true],["s","x"],["s","y"]]}'
        self.assertEqual(evaluate(wrapped, '')['steps'], 10)

    def test_d3_lists(self):
        # list: entry 1, children 3+3 (node, literal, result each), operands 1+1, own result 2, serialization 9
        self.assertEqual(run(['list', ['s', 'a'], ['s', 'b']])['steps'], 1 + 3 + 3 + 2 + 2 + 9)
        # empty list: entry 1, serialization '[]' 2
        self.assertEqual(run(['list'])['steps'], 1 + 2)
        # members are UTF-8 bytes: 'é' is 2
        self.assertEqual(run(['list', ['s', 'é']])['steps'], 1 + (1 + 2 + 2) + 2 + 2 + (2 + 2 + 2))
        # cat: entry 1, two list children (each 1 + 3 + 1 + 1 = 6 with operand), operands 2, own result 2, serialization 9
        two = ['cat', ['list', ['s', 'a']], ['list', ['s', 'b']]]
        self.assertEqual(run(two)['steps'], 1 + (1 + 3 + 1 + 1) * 2 + 2 + 2 + 9)
        # at: entry 1, split child (1 + input 3 + separator 1 + own list 3 + ... ) checked against a hand count
        e = ['at', ['list', ['s', 'ab']], 0]
        # at 1; list 1; s 1+2+2; list operand 2; list result 2; at operand 2; index ok; at result 2; ser '"ab"' 4
        self.assertEqual(run(e)['steps'], 1 + 1 + 5 + 2 + 2 + 2 + 2 + 4)

    def test_d3_if_charges_selected_branch_only(self):
        taken = run(['if', ['bool', False], ['s', 'x' * 100], ['s', 'y']])
        self.assertEqual(taken['steps'], 10)  # the long unselected branch costs nothing
        same = run(['if', ['bool', True], ['s', 'y'], ['s', 'x' * 100]])
        self.assertEqual(same['steps'], 10)
        lazy = run(['require', ['bool', False], ['input']], 'q' * 8000)
        self.assertEqual((lazy['reason'], lazy['steps']), ('guard', 2))  # entry, bool entry; guard fails, nothing else

    def test_d3_failed_child_charges_nothing_for_the_parent(self):
        # list(s 'ab', field z): list 1, s 1+2+2, operand 2, field entry 1 + key 1 + input 3, then missing
        r = run(['list', ['s', 'ab'], ['field', 'z']], 'a=b')
        self.assertEqual((r['reason'], r['steps']), ('missing', 1 + 5 + 2 + 1 + 1 + 3))
        # a malformed record: same charges, reason input
        r = run(['field', 'z'], 'garbage')
        self.assertEqual((r['reason'], r['steps']), ('input', 1 + 1 + 7))
        # failure keeps earlier charges and adds no serialization
        r = run(['at', ['list'], 0])
        self.assertEqual((r['reason'], r['steps']), ('index', 1 + 1))

    def test_d3_serialization_is_charged_last(self):
        r = run(['s', 'ab'])
        self.assertEqual(r['steps'], 1 + 2 + 2 + 4)
        # serialization pushes the total over the budget while evaluation itself stays under
        text = 'x' * 8192
        nodes = ['input']
        r = run(['require', ['bool', True], nodes], text)
        self.assertEqual(r['reason'], 'limit')

    def test_d3_first_charge_over_the_limit_saturates(self):
        for text in ('x' * 8192, 'x' * 8000):
            r = run(['list', ['input'], ['input'], ['input']], text)
            self.assertEqual((r['status'], r['reason'], r['steps']), ('abstain', 'limit', 32768))

    def test_d3_lookup_charges_all_table_strings(self):
        table = [['a', 'xy'], ['bb', 'z']]
        # lookup 1; s 1+1+1 =3; operand 1; table 1+2+2+1 = 6; own result 2; ser 4
        self.assertEqual(run(['lookup', ['s', 'a'], table])['steps'], 1 + 3 + 1 + 6 + 2 + 4)
        # an absent key still pays for the table before matching
        r = run(['lookup', ['s', 'q'], table])
        self.assertEqual((r['reason'], r['steps']), ('lookup', 1 + 3 + 1 + 6))

    def test_d3_eq_and_decimal_operands(self):
        # eq: entry 1; two s children (3 each) with operands 1 each; a bool result adds nothing; ser 'true' 4
        self.assertEqual(run(['eq', ['s', 'a'], ['s', 'a']])['steps'], 1 + 3 + 1 + 3 + 1 + 4)
        # le of two decimals: entry 1, two d nodes (1 + literal bytes), ser 'true'
        self.assertEqual(run(['le', ['d', '1'], ['d', '22']])['steps'], 1 + 2 + 3 + 4)

    def test_d4_vector_1_carry(self):
        r = run(['add', ['d', '9' * 38], ['d', '1']])
        self.assertEqual(r, {'status': 'value', 'type': 'decimal', 'value': '1' + '0' * 38, 'steps': 83})

    def test_d4_vector_2_overflow(self):
        r = run(['add', ['d', '9' * 38], ['d', '2']])
        self.assertEqual(r, {'status': 'abstain', 'reason': 'number', 'steps': 42})

    def test_d4_normalized_coefficient_digits(self):
        big = '1' + '0' * 37  # 1E+37 as an input numeral has 38 digits
        r = run(['add', ['d', big], ['d', big]])
        self.assertEqual(r['value'], '2' + '0' * 37)
        # a 38 digit coefficient with exponent 1 is rejected, 38 digits at exponent 0 are accepted
        self.assertEqual(run(['add', ['d', '9' * 38], ['d', '0']])['value'], '9' * 38)
        self.assertEqual(run(['add', ['d', '9' * 38], ['d', '9' * 38]])['reason'], 'number')
        # zero is coefficient 0, exponent 0
        self.assertEqual(run(['sub', ['d', '1.5'], ['d', '1.5']])['value'], '0')
        self.assertEqual(run(['sub', ['d', '-0.0'], ['d', '0']])['value'], '0')

    def test_d4_scale_limit_uses_the_normalized_exponent(self):
        self.assertEqual(run(['add', ['d', '0.000000000001'], ['d', '0']])['value'], '0.000000000001')
        # sums that need 13 fractional digits cannot arise from 12 digit operands, but trailing zeros normalize away
        self.assertEqual(run(['add', ['d', '0.500000000000'], ['d', '0.500000000000']])['value'], '1')

    def test_d4_input_numeral_limits_stay_separate(self):
        self.assertEqual(run(['num', ['input'], ''], '9' * 38)['status'], 'value')
        self.assertEqual(run(['num', ['input'], ''], '9' * 39)['reason'], 'number')
        self.assertEqual(run(['num', ['input'], ''], '0.0000000000001')['reason'], 'number')
        self.assertFalse(validate(ast(['d', '1' * 39]))[0])

    def test_d5_field_key_is_any_literal_string(self):
        for key in ('Upper', '1a', '', 'a b', 'a=b', 'é', 'x;y'):
            with self.subTest(key=key):
                self.assertTrue(validate(ast(['field', key]))[0])
                r = run(['field', key], 'a=1')
                self.assertEqual((r['status'], r['reason']), ('abstain', 'missing'))
        for bad in (['field', 1], ['field', None], ['field', ['s', 'a']], ['field']):
            with self.subTest(bad=bad):
                self.assertFalse(validate(ast(bad))[0])

    def test_d5_malformed_record_is_input_before_missing(self):
        for key in ('a', 'Upper', ''):
            for text in ('', 'a', 'a=1; a=2', 'a=1;b=2', 'x=1\n', '=1'):
                with self.subTest(key=key, text=text):
                    self.assertEqual(run(['field', key], text)['reason'], 'input')
        self.assertEqual(run(['field', 'q'], 'a=1; b=2')['reason'], 'missing')
        # the whole record is validated even when the key sits in an early, valid segment
        self.assertEqual(run(['field', 'a'], 'a=1; B=2')['reason'], 'input')

    def test_d9_decimal_values_are_json_strings(self):
        r = run(['add', ['num', ['input'], ''], ['d', '0']], '12.50')
        self.assertEqual((r['type'], r['value']), ('decimal', '12.5'))
        self.assertIsInstance(r['value'], str)
        self.assertEqual(canonical_value_text(r), '"12.5"')
        self.assertEqual(json.loads(canonical_value_text(r)), '12.5')
        big = run(['add', ['d', '9' * 38], ['d', '1']])
        self.assertEqual(canonical_value_text(big), '"1' + '0' * 38 + '"')

    def test_labels(self):
        self.assertTrue(label_ok({'type': 'string', 'value': 'x'}))
        self.assertTrue(label_ok({'type': 'list', 'value': ['a']}))
        self.assertTrue(label_ok({'type': 'bool', 'value': False}))
        self.assertTrue(label_ok({'type': 'decimal', 'value': '1' + '0' * 39}))  # 1E+39: one coefficient digit
        for bad in ({'type': 'bool', 'value': 'x'}, {'type': 'decimal', 'value': 1}, {'type': 'decimal', 'value': '1.0'},
                    {'type': 'decimal', 'value': '1' + '0' * 38 + '1'}, {'type': 'list', 'value': [1]},
                    {'type': 'x', 'value': 'a'}, {'type': 'string'}, {'type': 'string', 'value': 'a', 'x': 1}, None):
            with self.subTest(bad=bad):
                self.assertFalse(label_ok(bad))


class Admission(unittest.TestCase):
    """The old caller-callback admission is gone; the registry-resolved path is covered in test_oz_registry as well."""
    ECHO = ast(['input'])

    def registry(self, **over):
        return make_registry({'echo': operation(**over)})

    def test_accept(self):
        r = admit(self.ECHO, self.registry().resolve('echo'))
        self.assertEqual(r['status'], 'accepted')
        self.assertEqual((r['reasons'], r['coverage'], r['covered_errors']), ([], 64, 0))
        self.assertEqual(len(r['cases']), 64)
        self.assertEqual([c['id'] for c in r['cases']], ['c%d' % i for i in range(64)])
        self.assertEqual(r['ast_hash'], hashlib.sha256(self.ECHO).hexdigest())
        self.assertEqual(set(r['bindings']), {'contract_hash', 'check_hash', 'permission_hash', 'worker_hash',
                                              'dataset_hash', 'input_policy_hash'})
        self.assertEqual(r['operation_id'], 'echo')
        self.assertTrue(all(c['label_match'] and c['check_ok'] and not c['error'] for c in r['cases']))

    def test_signature_has_no_callbacks_or_flags(self):
        pkg = self.registry().resolve('echo')
        with self.assertRaises(TypeError):
            admit(self.ECHO, pkg, lambda t, c: True)
        with self.assertRaises(TypeError):
            admit(self.ECHO, pkg, eligible=True)

    def test_complete_typed_results_and_check_outcomes_are_retained(self):
        r = admit(self.ECHO, self.registry().resolve('echo'))
        c = r['cases'][7]
        self.assertEqual(c['result']['type'], 'string')
        self.assertEqual(c['result']['value'], 't7')
        self.assertEqual(c['checks'][0]['check'], 'quoted_span')
        self.assertEqual(c['input_sha256'], hashlib.sha256(b't7').hexdigest())

    def test_decimal_cases_compare_as_strings(self):
        ops = {'dec': operation(contract={'name': 'dec', 'deterministic': True}, cases=decimal_cases())}
        pkg = make_registry(ops).resolve('dec')
        num = ast(['add', ['num', ['input'], ''], ['d', '0']])
        r = admit(num, pkg)
        self.assertEqual((r['status'], r['coverage'], r['covered_errors']), ('accepted', 64, 0))
        self.assertEqual(r['cases'][2]['result']['type'], 'decimal')
        self.assertTrue(r['cases'][2]['label_match'])
        # a string label does not match a decimal result
        strs = decimal_cases()
        for c in strs:
            c['expected'] = {'type': 'string', 'value': c['expected']['value']}
        r = admit(num, make_registry({'dec': operation(contract={'name': 'dec', 'deterministic': True},
                                                       cases=strs)}).resolve('dec'))
        self.assertEqual((r['status'], r['covered_errors']), ('rejected', 64))

    def test_never_raises(self):
        pkg = self.registry().resolve('echo')
        for args in ((None, None), (b'x', object()), (self.ECHO, {'cases': 3}), (None, pkg), (5, pkg), (b'\xff', pkg)):
            self.assertEqual(admit(*args)['status'], 'rejected')


class NeverRaises(unittest.TestCase):
    TAGS = ['s', 'd', 'bool', 'input', 'field', 'split', 'at', 'num', 'add', 'sub', 'fmt', 'eq', 'le', 'if',
            'require', 'lookup', 'list', 'cat', 'eval', 'x']
    ATOMS = ['', 'a', 'mm', '|', '12.50', '-0', 'length', 'uncertainty', 0, 1, 2, 13, -1, True, False, None, 1.5,
             '\ud800', 'é', {'k': 1}]
    TEXTS = ['', 'length=12.50 mm; uncertainty=0.02 mm', 'a|b|c', '-0.001', 'x' * 300, 'a=1; a=2', '=;', '\ud800',
             '12.50 mm', 'unknown']

    def gen(self, rng, depth):
        if depth <= 0 or rng.random() < 0.25:
            return rng.choice(self.ATOMS) if rng.random() < 0.3 else [rng.choice(self.TAGS)] + [
                rng.choice(self.ATOMS) for _ in range(rng.randrange(0, 4))]
        tag = rng.choice(self.TAGS)
        n = {'s': 1, 'd': 1, 'bool': 1, 'input': 0, 'field': 1, 'split': 2, 'at': 2, 'num': 2, 'add': 2, 'sub': 2,
             'fmt': 3, 'eq': 2, 'le': 2, 'if': 3, 'require': 2, 'lookup': 2}.get(tag, rng.randrange(0, 4))
        if rng.random() < 0.1:
            n += rng.choice([-1, 1])
        node = [tag]
        for i in range(max(n, 0)):
            r = rng.random()
            if r < 0.5:
                node.append(self.gen(rng, depth - 1))
            elif r < 0.8:
                node.append(rng.choice(self.ATOMS))
            else:
                node.append([[rng.choice(self.ATOMS), rng.choice(self.ATOMS)] for _ in range(rng.randrange(0, 3))])
        return node

    def test_random_asts_and_texts(self):
        rng = random.Random(20261024)
        valid = 0
        for _ in range(400):
            doc = {'lang': 'oz-rule/1', 'expr': self.gen(rng, rng.randrange(1, 5))}
            if rng.random() < 0.05:
                doc['extra'] = 1
            try:
                data = json.dumps(doc, ensure_ascii=rng.random() < 0.5, separators=(',', ':')).encode('utf-8', 'surrogatepass')
            except (TypeError, ValueError):
                continue
            ok, reason = validate(data)
            self.assertIsInstance(ok, bool)
            self.assertIsInstance(reason, str)
            valid += ok
            for text in rng.sample(self.TEXTS, 3):
                r = evaluate(data, text)
                self.assertIsInstance(r, dict)
                self.assertIn(r['status'], ('value', 'abstain'))
                self.assertTrue(0 <= r['steps'] <= 32768)
                if r['status'] == 'abstain':
                    self.assertIn(r['reason'], ('invalid_ast', 'limit', 'input', 'missing', 'number', 'unit', 'type',
                                                'guard', 'lookup', 'index', 'internal'))
                    self.assertNotEqual(r['reason'], 'internal')
                    if r['reason'] == 'invalid_ast':
                        self.assertFalse(ok)
                else:
                    self.assertTrue(ok)
                    self.assertIn(r['type'], ('string', 'decimal', 'bool', 'list'))
                    self.assertIsInstance(canonical_value_text(r), str)
                self.assertEqual(r, evaluate(data, text))  # deterministic
        self.assertGreater(valid, 5)

    def test_random_bytes(self):
        rng = random.Random(7)
        base = ASTS['V']
        for _ in range(300):
            data = bytearray(base)
            for _ in range(rng.randrange(1, 4)):
                data[rng.randrange(len(data))] = rng.randrange(256)
            r = evaluate(bytes(data), 'length=12.50 mm; uncertainty=0.02 mm')
            self.assertIn(r['status'], ('value', 'abstain'))
        for junk in (None, 5, 'str', [], b'\x00', b'{', bytearray(b'{}')):
            self.assertEqual(evaluate(junk, 'x')['reason'], 'invalid_ast')
            self.assertEqual(validate(junk)[0], False)
        self.assertEqual(evaluate(ASTS['E'], None)['reason'], 'input')
        self.assertEqual(evaluate(bytearray(ASTS['T']), 'a|b')['value'], 'b')


if __name__ == '__main__':
    unittest.main()
