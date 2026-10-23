"""Build-time generator for repair-handoff-20/v1 (evaluator side; run before the freeze, never by the executor).

It holds the authored workload (tickets, requirements, public examples, A-tier and I-tier inputs, core stubs, the
coverage labels and the seeded-defect declarations) and writes the frozen pack:

  repair-handoff-20-v1/tickets/<T>.rev<N>.json   exact ticket bytes (the authoritative sources), with the exact model
                                                records and the replacement spans
  repair-handoff-20-v1/tier_a.json               per-job acceptance rows with expected outcomes
  repair-handoff-20-v1/tier_i.json               package integration rows with expected outcomes
  repair-handoff-20-v1/coverage.json             the coverage matrix (M5)
  repair-handoff-20-v1/defects.json              the seeded defects, why each needs semantic repair, discriminating rows
  evaluator/heldout.json                         H-tier expected outcomes (evaluator only)

Expected outcomes come from the two references (ref1, ref2), which must agree on every A, I and H input; any
disagreement stops the build. The executor reads only the frozen pack, never this directory.

    python bench/o1/evaluator/build.py [--check]
"""
from __future__ import annotations

import ast
import base64
import hashlib
import json
from pathlib import Path
import sys
import zlib

HERE = Path(__file__).resolve().parent
O1 = HERE.parent
PACK = O1 / 'repair-handoff-20-v1'
sys.path.insert(0, str(O1))
sys.path.insert(0, str(HERE))

import heldout as H  # noqa: E402
import sandbox_worker as SW  # noqa: E402

POLICY = json.loads((PACK / 'policy.json').read_text(encoding='utf-8'))
ACCEPTED_MARKER = 'Accepted core function (already in scope; call it, do not redefine it):\n'

MODULES = {  # ticket -> (module file name, core, core params, adapter, adapter params)
    'A': ('amounts.py', 'parse_amount', ['text'], 'total_amount', ['texts']),
    'B': ('intervals.py', 'union_intervals', ['intervals'], 'free_slots', ['busy', 'window']),
    'C': ('config_patch.py', 'merge_patch', ['base', 'patch'], 'apply_revisions', ['base', 'revisions']),
    'D': ('jobs.py', 'topological_order', ['jobs'], 'execution_batches', ['jobs']),
}
REVISIONS = (('A', 1), ('A', 2), ('B', 1), ('C', 1), ('D', 1))
TITLES = {'A': 'Exact decimal amounts', 'B': 'Interval availability', 'C': 'Configuration updates',
          'D': 'Dependency execution'}
PERMITTED = ['Replace the defective function with a corrected one; keep its def line exactly as given.',
             'Nested def and lambda inside the function are allowed.',
             'No imports, decorators, annotations, default values, helper definitions or other top-level statements.']
ALIAS = {'A': False, 'B': False, 'C': True, 'D': False}


def precision(ticket, rev):
    return 3 if (ticket, rev) == ('A', 2) else 2


def requirements(ticket, rev):
    p = precision(ticket, rev)
    unit = 'thousandths' if p == 3 else 'hundredths'
    zero = '0.' + '0' * p
    return {
        'A': ({'core': [
            f'text must be a str of ASCII characters matching -?(0|[1-9][0-9]*)(\\.[0-9]{{1,{p}}})? with at most nine '
            'integer digits. Anything else (other types, booleans, whitespace, a plus sign, exponents, leading zeros, '
            'a missing digit on either side of the point) raises ValueError.',
            f'Return the amount as an int number of minor units ({unit}, the value times {10 ** p}) without floating '
            'point. "-0" and "-0.0" return 0.',
            f'A fractional part shorter than {p} digits is padded with zeros; more than {p} fractional digits is '
            'invalid (ValueError), never rounded.'],
            'adapter': [
            'texts is a list of str. Call parse_amount exactly once per element, in list order; let its ValueError '
            'propagate (stop at the first invalid element).',
            'Sum the minor units exactly with int arithmetic.',
            f'Return text: "-" for a negative total, the integer part without leading zeros (at least "0"), ".", and '
            f'exactly {p} fractional digits. A zero total is "{zero}", never negative; an empty list gives "{zero}".']}),
        'B': ({'core': [
            'intervals is a list. An interval is a two-element list [start, end] of ints (a bool is not an int here) '
            'with start <= end; any other element raises ValueError, checked for every element before merging.',
            'Intervals are half-open [start, end). Drop zero-length intervals. Merge intervals that overlap or touch '
            '([1, 3] and [3, 5] give [1, 5]).',
            'Return a new list of new [start, end] lists sorted by start, pairwise disjoint and not touching. Never '
            'modify the input.'],
            'adapter': [
            'window is an interval [ws, we] and busy is a list of intervals; an interval is a two-element list '
            '[start, end] of ints (a bool is not an int here) with start <= end. If the window or any busy interval is '
            'invalid, raise ValueError before calling union_intervals.',
            'Call union_intervals exactly once, with a new list holding, in busy order, [max(start, ws), min(end, we)] '
            'for every busy interval where max(start, ws) < min(end, we).',
            'Return the parts of the window not covered by the intervals union_intervals returned, as [start, end] '
            'lists in increasing order, each of positive length; a zero-width window gives [].']}),
        'C': ({'core': [
            'base and patch are JSON values: None, bool, int, str, list, or dict with str keys.',
            'If patch is not a dict, return a deep copy of patch. Otherwise start from a deep copy of base when base is '
            'a dict, else from {}; for each key of patch, a None value deletes the key (no error when it is absent) and '
            'any other value v sets the key to merge_patch(the current value of the key or None, v).',
            'Never modify base or patch, and share no list or dict with them in the result.'],
            'adapter': [
            'revisions is a list of dicts with keys "seq" and "patch". Every seq must be an int >= 1 (a bool is not an '
            'int here) and the seqs must be distinct; otherwise raise ValueError before calling merge_patch.',
            'Apply the patches in increasing seq order: current = base, then current = merge_patch(current, patch) for '
            'each revision, calling merge_patch exactly once per revision; return current.',
            'With no revisions, return a deep copy of base. Never modify base or revisions, and share no list or dict '
            'with them in the result.']}),
        'D': ({'core': [
            'jobs is a list of dicts {"id": str, "deps": list of str}. Raise ValueError when two jobs share an id, when '
            'a dependency names no job in the list, or when the dependencies form a cycle (a job depending on itself '
            'included). Repeated entries in deps count once.',
            'Return the list of ids in execution order: repeatedly take, among the jobs not yet taken whose '
            'dependencies are all taken, the one that comes first in the input list.',
            'Never modify the input.'],
            'adapter': [
            'Call topological_order(jobs) exactly once; let its ValueError propagate.',
            'A job\'s level is 0 when it has no dependencies, else 1 plus the largest level among its dependencies.',
            'Return a list of batches: batch k lists the ids of level k in the order they appear in the list '
            'topological_order returned. No empty batches; [] for no jobs. Never modify the input.']}),
    }[ticket]


LIMITS = {'A': 'text at most 32 characters; texts at most 16 elements.',
          'B': 'at most 16 intervals; endpoints between -10**9 and 10**9.',
          'C': 'JSON values nested at most 4 deep with at most 8 entries per list or dict.',
          'D': 'at most 8 jobs; ids at most 8 characters.'}

EXAMPLES = {
    ('A', 1): {'core': [(['12.30'], 1230), (['-0.5'], -50), (['7'], 700), (['1.005'], 'ValueError')],
               'adapter': [([['1.50', '2.25']], '3.75'), ([[]], '0.00'), ([['1', '-1.00']], '0.00')]},
    ('A', 2): {'core': [(['12.300'], 12300), (['-0.5'], -500), (['7'], 7000), (['1.0005'], 'ValueError')],
               'adapter': [([['1.500', '2.25']], '3.750'), ([[]], '0.000'), ([['1', '-1.000']], '0.000')]},
    ('B', 1): {'core': [([[[5, 7], [1, 3], [3, 4]]], [[1, 4], [5, 7]]), ([[[2, 2]]], []), ([[[3, 1]]], 'ValueError')],
               'adapter': [([[[1, 3]], [0, 5]], [[0, 1], [3, 5]]), ([[], [2, 2]], []),
                           ([[[-5, 1], [4, 9]], [0, 6]], [[1, 4]])]},
    ('C', 1): {'core': [([{'a': 1, 'b': {'c': 2}}, {'b': {'c': None, 'd': 3}}], {'a': 1, 'b': {'d': 3}}),
                        ([{'a': [1]}, {'a': [2]}], {'a': [2]}), ([5, {'x': None}], {})],
               'adapter': [([{'a': 1}, [{'seq': 2, 'patch': {'a': 3}}, {'seq': 1, 'patch': {'b': 2}}]], {'a': 3, 'b': 2}),
                           ([{'a': 1}, []], {'a': 1}),
                           ([{}, [{'seq': 1, 'patch': {}}, {'seq': 1, 'patch': {}}]], 'ValueError')]},
    ('D', 1): {'core': [([[{'id': 'b', 'deps': ['a']}, {'id': 'a', 'deps': []}]], ['a', 'b']), ([[]], []),
                        ([[{'id': 'a', 'deps': ['a']}]], 'ValueError')],
               'adapter': [([[{'id': 'a', 'deps': []}, {'id': 'b', 'deps': ['a']}, {'id': 'c', 'deps': []}]],
                            [['a', 'c'], ['b']]), ([[]], [])]},
}


# ---- A tier: authored inputs (expected outcomes come from the references) ----

def _s(args, family, side='n/a'):
    """A row: args, coverage family, side of the family's edge (inside/outside/n/a)."""
    return {'args': args, 'family': family, 'side': side}


def a_core_rows(p):
    z = '0' * p
    rows = [
        _s(['12.3' + z[1:]], 'value_basic'), _s(['7'], 'value_basic'),
        _s(['0'], 'zero_and_negative_zero'), _s(['-0'], 'zero_and_negative_zero'),
        _s(['-0.' + z], 'zero_and_negative_zero'), _s(['0.0'], 'zero_and_negative_zero'),
        _s(['-5'], 'negative'), _s(['-0.5'], 'negative'), _s(['-123.45'], 'negative'),
        _s(['1.5'], 'fractional_padding'), _s(['1.50'], 'fractional_padding'),
        _s(['1.' + '0' * (p - 1) + '5'], 'excess_precision', 'inside'),
        _s(['1.' + '0' * p + '5'], 'excess_precision', 'outside'),
        _s(['0.' + '0' * p + '1'], 'excess_precision', 'outside'),
        _s([''], 'malformed'), _s([' 1'], 'malformed'), _s(['1 '], 'malformed'), _s(['+1'], 'malformed'),
        _s(['1e2'], 'malformed'), _s(['01'], 'malformed'), _s(['1.'], 'malformed'), _s(['.5'], 'malformed'),
        _s(['1.2.3'], 'malformed'), _s(['--1'], 'malformed'), _s(['-'], 'malformed'), _s(['abc'], 'malformed'),
        _s(['1,5'], 'malformed'), _s(['١'], 'malformed'), _s(['nan'], 'malformed'), _s(['inf'], 'malformed'),
        _s(['999999999'], 'integer_digit_limit', 'inside'), _s(['-999999999.99'], 'integer_digit_limit', 'inside'),
        _s(['1000000000'], 'integer_digit_limit', 'outside'), _s(['-1000000000.5'], 'integer_digit_limit', 'outside'),
        _s([5], 'type_confusion'), _s([True], 'type_confusion'), _s([None], 'type_confusion'),
        _s([['1']], 'type_confusion'),
        _s(['0.29'], 'float_artifact'), _s(['1.15'], 'float_artifact'), _s(['4.35'], 'float_artifact'),
        _s(['0.57'], 'float_artifact'),
    ]
    if p == 3:
        rows += [_s(['1.001'], 'revision_precision', 'inside'), _s(['2.125'], 'revision_precision', 'inside'),
                 _s(['1.0001'], 'revision_precision', 'outside')]
    return rows


def a_adapter_rows(p):
    def u(x):  # minor units of a decimal text at precision p, used to build stub tables
        neg = x.startswith('-')
        w, _, f = x.lstrip('-').partition('.')
        v = int(w) * 10 ** p + int((f + '0' * p)[:p])
        return -v if neg else v

    def stub(table, raising=()):
        return {'responses': [{'args': [k], 'return': u(v)} for k, v in table]
                + [{'args': [k], 'raise': 'ValueError'} for k in raising]}
    rows = [
        dict(_s([['a', 'b']], 'call_contract'), stub=stub([('a', '1.5'), ('b', '-0.25')])),
        dict(_s([['b', 'a', 'b']], 'call_contract'), stub=stub([('a', '2'), ('b', '0.01')])),
        dict(_s([['a', 'bad', 'c']], 'invalid_propagation'), stub=stub([('a', '1'), ('c', '1')], ['bad'])),
        dict(_s([['bad']], 'invalid_propagation'), stub=stub([], ['bad'])),
        dict(_s([['m']], 'negative_total'), stub=stub([('m', '-1.5')])),
        dict(_s([['m', 'n']], 'negative_total'), stub=stub([('m', '-0.05'), ('n', '0')])),
        dict(_s([['p', 'n']], 'cancellation'), stub=stub([('p', '1.5'), ('n', '-1.5')])),
        dict(_s([['p', 'n', 'q']], 'cancellation'), stub=stub([('p', '-0.01'), ('n', '0.02'), ('q', '-0.01')])),
        dict(_s([[]], 'empty_collection'), stub=stub([])),
        dict(_s([['z']], 'empty_collection'), stub=stub([('z', '0')])),
        dict(_s([['s']], 'formatting_padding'), stub=stub([('s', '0.07')])),
        dict(_s([['s', 't']], 'formatting_padding'), stub=stub([('s', '1000'), ('t', '0.1')])),
        dict(_s([['g', 'h']], 'large_sum'), stub=stub([('g', '999999999.99'), ('h', '999999999.99')])),
        dict(_s([['g', 'k']], 'large_sum'), stub=stub([('g', '-999999999.99'), ('k', '-999999999')])),
        _s([['1.50', '2.25']], 'integration'), _s([['-1.50']], 'integration'),
        _s([['0.29', '0.01']], 'integration'), _s([['1', 'x']], 'integration'),
        _s([[]], 'integration'), _s([['-0.05', '0.05']], 'integration'),
    ]
    if p == 3:
        rows += [dict(_s([['r']], 'revision_precision'), stub=stub([('r', '1.001')])),
                 dict(_s([['r', 's']], 'revision_precision'), stub=stub([('r', '-0.125'), ('s', '0.1')])),
                 _s([['1.001', '0.009']], 'integration')]
    return rows


def b_core_rows():
    return [
        _s([[]], 'empty_input'), _s([[[2, 2]]], 'empty_input'),
        _s([[[1, 10], [2, 3]]], 'nesting'), _s([[[0, 5], [1, 4], [2, 3]]], 'nesting'),
        _s([[[1, 3], [1, 3]]], 'duplicates'), _s([[[0, 1], [0, 1], [0, 1]]], 'duplicates'),
        _s([[[1, 3], [3, 5]]], 'touching', 'inside'), _s([[[3, 5], [1, 3]]], 'touching', 'inside'),
        _s([[[1, 3], [4, 5]]], 'touching', 'outside'),
        _s([[[5, 7], [1, 3]]], 'unsorted'), _s([[[8, 9], [0, 2], [1, 4]]], 'unsorted'),
        _s([[[1, 1], [3, 4]]], 'zero_length', 'inside'), _s([[[2, 2], [1, 3]]], 'zero_length', 'inside'),
        _s([[[1, 2]]], 'zero_length', 'outside'),
        _s([[[-5, -2], [-3, 0]]], 'negative_endpoints'), _s([[[-2, -1], [0, 1]]], 'negative_endpoints'),
        _s([[[3, 1]]], 'invalid'), _s([[[True, 3]]], 'invalid'), _s([[[1, '2']]], 'invalid'),
        _s([[[1, 2, 3]]], 'invalid'), _s([[[1]]], 'invalid'), _s([[[0, 1], [2, 1]]], 'invalid'),
        _s([[[0, False]]], 'invalid'),
    ]


def b_adapter_rows():
    def st(arg, ret):
        return {'responses': [{'args': [arg], 'return': ret}]}
    return [
        dict(_s([[[1, 3], [5, 9]], [0, 8]], 'call_contract'), stub=st([[1, 3], [5, 8]], [[1, 3], [5, 8]])),
        dict(_s([[[1, 2], [2, 4]], [0, 6]], 'call_contract'), stub=st([[1, 2], [2, 4]], [[1, 4]])),
        dict(_s([[[-4, 2]], [0, 5]], 'crossing_window_start'), stub=st([[0, 2]], [[0, 2]])),
        dict(_s([[[-4, 0]], [0, 5]], 'crossing_window_start'), stub=st([], [])),
        dict(_s([[[3, 9]], [0, 5]], 'crossing_window_end'), stub=st([[3, 5]], [[3, 5]])),
        dict(_s([[[5, 9]], [0, 5]], 'crossing_window_end'), stub=st([], [])),
        dict(_s([[[-5, -1], [7, 9]], [0, 5]], 'outside_window'), stub=st([], [])),
        dict(_s([[[6, 7]], [0, 5]], 'outside_window'), stub=st([], [])),
        dict(_s([[[1, 2]], [3, 3]], 'zero_width_window', 'inside'), stub=st([], [])),
        dict(_s([[], [3, 4]], 'zero_width_window', 'outside'), stub=st([], [])),
        dict(_s([[], [0, 5]], 'empty_busy'), stub=st([], [])),
        dict(_s([[], [-3, -1]], 'empty_busy'), stub=st([], [])),
        dict(_s([[[1, 2]], [5, 0]], 'invalid_window'), stub=st([], [])),
        dict(_s([[], [True, 3]], 'invalid_window'), stub=st([], [])),
        dict(_s([[[2, 1]], [0, 5]], 'invalid_busy'), stub=st([], [])),
        dict(_s([[[0, 1], [1, 'x']], [0, 5]], 'invalid_busy'), stub=st([], [])),
        dict(_s([[[0, 10]], [2, 4]], 'full_cover'), stub=st([[2, 4]], [[2, 4]])),
        dict(_s([[[0, 2], [1, 5]], [0, 5]], 'full_cover'), stub=st([[0, 2], [1, 5]], [[0, 5]])),
        _s([[[1, 4], [2, 6], [8, 9]], [0, 10]], 'integration'), _s([[], [2, 2]], 'integration'),
        _s([[[5, 7], [1, 3]], [0, 8]], 'integration'), _s([[[0, 10]], [2, 4]], 'integration'),
        _s([[[1, 5]], [3, 3]], 'integration'), _s([[[-3, 1], [4, 4], [2, 3]], [-1, 5]], 'integration'),
    ]


def c_core_rows():
    return [
        _s([{'a': 1}, {'b': None}], 'missing_deletion_target'), _s([{}, {'x': None}], 'missing_deletion_target'),
        _s([{'a': {'b': 1, 'c': 2}}, {'a': {'b': None}}], 'nested_deletion'),
        _s([{'a': {'b': {'c': 1}}}, {'a': {'b': {'c': None}}}], 'nested_deletion'),
        _s([{'a': 1}, {'a': {'b': 2}}], 'scalar_to_object'), _s([3, {'a': 1}], 'scalar_to_object'),
        _s([{'a': {'b': 1}}, {'a': 5}], 'object_to_scalar'), _s([{'a': 1}, 7], 'object_to_scalar'),
        _s([{'a': [1, 2]}, {'a': [3]}], 'arrays'), _s([{'a': 1}, [1, {'b': None}]], 'arrays'),
        _s([{'a': 0}, {'a': False}], 'false_vs_zero'), _s([{'a': False}, {'b': 0}], 'false_vs_zero'),
        _s([{}, {'a': [1]}], 'aliasing'), _s([{'a': {'b': [1]}}, {'c': 1}], 'aliasing'),
        _s([{'a': {'b': 1}}, {'a': {'c': 2}}], 'aliasing'),
        _s([None, {'a': None}], 'non_object_base'), _s([[1], {'a': 1}], 'non_object_base'),
        _s([{'a': 1}, {}], 'empty_patch'), _s([None, {}], 'empty_patch'), _s([{'a': 1}, None], 'empty_patch'),
    ]


def c_adapter_rows():
    def st(*pairs):
        return {'responses': [{'args': list(a), 'return': r} for a, r in pairs]}
    return [
        dict(_s([{'v': 0}, [{'seq': 10, 'patch': {'x': 10}}, {'seq': 2, 'patch': {'x': 2}}]], 'numeric_sequence_order',
                'outside'),
             stub=st(([{'v': 0}, {'x': 2}], {'s': 1}), ([{'s': 1}, {'x': 10}], {'s': 2}))),
        dict(_s([{'v': 0}, [{'seq': 3, 'patch': {'x': 3}}, {'seq': 1, 'patch': {'x': 1}}]], 'numeric_sequence_order',
                'inside'),
             stub=st(([{'v': 0}, {'x': 1}], {'t': 1}), ([{'t': 1}, {'x': 3}], {'t': 2}))),
        dict(_s([{}, [{'seq': 1, 'patch': {}}, {'seq': 1, 'patch': {}}]], 'duplicate_sequence'), stub=st()),
        dict(_s([{}, [{'seq': 2, 'patch': {'a': 1}}, {'seq': 5, 'patch': {}}, {'seq': 2, 'patch': {}}]],
                'duplicate_sequence'), stub=st()),
        dict(_s([{}, [{'seq': True, 'patch': {}}]], 'invalid_sequence', 'outside'), stub=st()),
        dict(_s([{}, [{'seq': 0, 'patch': {}}]], 'invalid_sequence', 'outside'), stub=st()),
        dict(_s([{}, [{'seq': -1, 'patch': {}}]], 'invalid_sequence', 'outside'), stub=st()),
        dict(_s([{}, [{'seq': '1', 'patch': {}}]], 'invalid_sequence', 'outside'), stub=st()),
        dict(_s([{}, [{'seq': 1, 'patch': {'a': 1}}]], 'invalid_sequence', 'inside'),
             stub=st(([{}, {'a': 1}], {'a': 1}))),
        dict(_s([{'a': [1]}, []], 'empty_revisions'), stub=st()),
        dict(_s([None, []], 'empty_revisions'), stub=st()),
        dict(_s([{'a': {'b': [2]}}, []], 'aliasing'), stub=st()),
        dict(_s([[1, [2]], []], 'aliasing'), stub=st()),
        dict(_s([{'a': 0}, [{'seq': 1, 'patch': {'a': False}}]], 'false_vs_zero'),
             stub=st(([{'a': 0}, {'a': False}], {'a': False}))),
        dict(_s([{'a': False}, [{'seq': 1, 'patch': {'b': 0}}]], 'false_vs_zero'),
             stub=st(([{'a': False}, {'b': 0}], {'a': False, 'b': 0}))),
        dict(_s([{'k': 1}, [{'seq': 4, 'patch': 9}]], 'call_contract'), stub=st(([{'k': 1}, 9], {'w': 1}))),
        dict(_s([{'k': 1}, [{'seq': 4, 'patch': {'q': 1}}, {'seq': 7, 'patch': {'q': None}}]], 'call_contract'),
             stub=st(([{'k': 1}, {'q': 1}], {'k': 1, 'q': 1}), ([{'k': 1, 'q': 1}, {'q': None}], {'k': 1}))),
        _s([{'a': 1}, [{'seq': 2, 'patch': {'a': 3}}, {'seq': 1, 'patch': {'b': 2}}]], 'integration'),
        _s([{'a': {'b': 1}}, [{'seq': 1, 'patch': {'a': {'b': None}}}]], 'integration'),
        _s([{'a': 0}, [{'seq': 10, 'patch': {'a': [1]}}, {'seq': 9, 'patch': {'a': {'k': 0}}}]], 'integration'),
        _s([{'a': 0}, [{'seq': 3, 'patch': {'a': False}}]], 'integration'),
        _s([{'a': [1]}, []], 'integration'),
    ]


def J(i, deps=()):
    return {'id': i, 'deps': list(deps)}


def d_core_rows():
    return [
        _s([[]], 'empty_graph'), _s([[J('a')]], 'empty_graph'),
        _s([[J('c', 'b'), J('b', 'a'), J('a')]], 'chain'), _s([[J('a'), J('b', 'a'), J('c', 'b')]], 'chain'),
        _s([[J('a'), J('b', 'a'), J('c', 'a'), J('d', 'bc')]], 'diamond'),
        _s([[J('d', 'bc'), J('c', 'a'), J('b', 'a'), J('a')]], 'diamond'),
        _s([[J('x'), J('y'), J('z')]], 'multiple_roots'), _s([[J('q'), J('p'), J('r', 'p')]], 'multiple_roots'),
        _s([[J('b', 'a'), J('a'), J('c')]], 'newly_ready_earlier_index'),
        _s([[J('d', 'c'), J('c', 'a'), J('a'), J('b')]], 'newly_ready_earlier_index'),
        _s([[J('x', 'z'), J('y', 'w'), J('w'), J('z')]], 'newly_ready_earlier_index'),
        _s([[J('a'), J('a')]], 'duplicate_id'), _s([[J('a'), J('b', 'a'), J('a')]], 'duplicate_id'),
        _s([[J('a', 'z')]], 'missing_dependency'), _s([[J('a'), J('b', ['a', 'q'])]], 'missing_dependency'),
        _s([[J('a', 'a')]], 'self_cycle'), _s([[J('b'), J('a', 'a')]], 'self_cycle'),
        _s([[J('a', 'b'), J('b', 'a')]], 'multi_node_cycle'),
        _s([[J('a', 'c'), J('b', 'a'), J('c', 'b')]], 'multi_node_cycle'),
        _s([[J('a'), J('b', 'aa')]], 'repeated_dependency'), _s([[J('b', 'aaa'), J('a')]], 'repeated_dependency'),
    ]


def d_adapter_rows():
    def st(jobs, ret=None, raises=False):
        entry = {'args': [jobs]}
        entry.update({'raise': 'ValueError'} if raises else {'return': ret})
        return {'responses': [entry]}
    two = [J('a'), J('b')]
    diamond = [J('a'), J('b', 'a'), J('c', 'b'), J('d', 'ac')]
    cross = [J('x', 'z'), J('y', 'w'), J('w'), J('z')]
    return [
        dict(_s([two], 'call_contract'), stub=st(two, ['b', 'a'])),
        dict(_s([[J('m'), J('n', 'm')]], 'call_contract'), stub=st([J('m'), J('n', 'm')], ['m', 'n'])),
        dict(_s([[J('a', 'a')]], 'invalid_propagation'), stub=st([J('a', 'a')], raises=True)),
        dict(_s([two], 'invalid_propagation'), stub=st(two, raises=True)),
        dict(_s([diamond], 'diamond_unequal_paths'), stub=st(diamond, ['a', 'b', 'c', 'd'])),
        dict(_s([[J('d', 'ab'), J('b', 'a'), J('a')]], 'diamond_unequal_paths'),
             stub=st([J('d', 'ab'), J('b', 'a'), J('a')], ['a', 'b', 'd'])),
        dict(_s([cross], 'within_batch_order'), stub=st(cross, ['w', 'y', 'z', 'x'])),
        dict(_s([[J('p'), J('q'), J('r')]], 'within_batch_order'),
             stub=st([J('p'), J('q'), J('r')], ['r', 'p', 'q'])),
        dict(_s([[]], 'empty_graph'), stub=st([], [])),
        dict(_s([[J('s')]], 'empty_graph'), stub=st([J('s')], ['s'])),
        dict(_s([[J('k'), J('l', 'k'), J('j')]], 'multiple_roots'),
             stub=st([J('k'), J('l', 'k'), J('j')], ['k', 'j', 'l'])),
        dict(_s([[J('k', 'jj'), J('j')]], 'chain'), stub=st([J('k', 'jj'), J('j')], ['j', 'k'])),
        dict(_s([[J('c', 'b'), J('b', 'a'), J('a')]], 'chain'),
             stub=st([J('c', 'b'), J('b', 'a'), J('a')], ['a', 'b', 'c'])),
        dict(_s([[J('u'), J('v')]], 'multiple_roots'), stub=st([J('u'), J('v')], ['u', 'v'])),
        _s([[J('a'), J('b', 'a'), J('c')]], 'integration'), _s([[]], 'integration'),
        _s([[J('b', 'a'), J('a')]], 'integration'), _s([[J('a', 'a')]], 'integration'),
        _s([cross], 'integration'), _s([diamond], 'integration'),
    ]


AUTHORED = {('A', 1, 'core'): lambda: a_core_rows(2), ('A', 1, 'adapter'): lambda: a_adapter_rows(2),
            ('A', 2, 'core'): lambda: a_core_rows(3), ('A', 2, 'adapter'): lambda: a_adapter_rows(3),
            ('B', 1, 'core'): b_core_rows, ('B', 1, 'adapter'): b_adapter_rows,
            ('C', 1, 'core'): c_core_rows, ('C', 1, 'adapter'): c_adapter_rows,
            ('D', 1, 'core'): d_core_rows, ('D', 1, 'adapter'): d_adapter_rows}

I_ROWS = {
    ('A', 1): [('total_amount', [['0.10', '0.20']]), ('total_amount', [['-3.07', '1', '0.5']]),
               ('total_amount', [['999999999.99', '-999999999.99']]), ('total_amount', [['1', '+1']]),
               ('parse_amount', ['20.01']), ('parse_amount', ['-0.09']), ('total_amount', [['0.3', '0.3', '0.3']]),
               ('total_amount', [['-0.01']])],
    ('A', 2): [('total_amount', [['0.100', '0.2']]), ('total_amount', [['-3.007', '1', '0.5']]),
               ('total_amount', [['999999999.999', '-999999999.999']]), ('total_amount', [['1', '+1']]),
               ('parse_amount', ['20.001']), ('parse_amount', ['-0.009']), ('total_amount', [['0.3', '0.3', '0.3']]),
               ('total_amount', [['-0.001']])],
    ('B', 1): [('free_slots', [[[0, 3], [2, 5], [7, 8]], [0, 9]]), ('free_slots', [[[9, 12], [-3, 1]], [0, 10]]),
               ('free_slots', [[[4, 4]], [0, 8]]), ('free_slots', [[[1, 2], [2, 3], [3, 4]], [0, 5]]),
               ('union_intervals', [[[6, 8], [0, 1], [1, 2], [7, 9]]]), ('free_slots', [[[0, 5]], [0, 5]]),
               ('free_slots', [[[1, 3]], [3, 1]]), ('union_intervals', [[[0, 0], [5, 5]]])],
    ('C', 1): [('apply_revisions', [{'srv': {'port': 80, 'tls': False}},
                                    [{'seq': 12, 'patch': {'srv': {'tls': True}}}, {'seq': 3, 'patch': {'srv': {'port': 8080}}}]]),
               ('apply_revisions', [{'a': [1, 2]}, [{'seq': 1, 'patch': {'a': None, 'b': [0]}}]]),
               ('apply_revisions', [{}, [{'seq': 2, 'patch': {'x': {'y': {'z': 1}}}}, {'seq': 1, 'patch': {'x': 0}}]]),
               ('apply_revisions', [{'a': 1}, [{'seq': False, 'patch': {}}]]),
               ('merge_patch', [{'a': {'b': {'c': 1, 'd': 2}}}, {'a': {'b': {'c': None}}}]),
               ('merge_patch', [{'a': 0}, {'a': False, 'b': None}]),
               ('apply_revisions', [{'n': None}, []]),
               ('apply_revisions', [{'a': 1}, [{'seq': 5, 'patch': [1]}, {'seq': 6, 'patch': {'k': 1}}]])],
    ('D', 1): [('execution_batches', [[J('lint'), J('test', ['build']), J('build', ['lint']), J('docs')]]),
               ('execution_batches', [[J('e', 'd'), J('d', 'c'), J('c', 'b'), J('b', 'a'), J('a')]]),
               ('execution_batches', [[J('f', 'ab'), J('e', 'a'), J('a'), J('b')]]),
               ('execution_batches', [[J('a'), J('b', 'a'), J('b')]]),
               ('topological_order', [[J('u', 'v'), J('v', 'w'), J('w'), J('x', 'u')]]),
               ('execution_batches', [[J('m'), J('n', 'mm'), J('o', 'nm')]]),
               ('execution_batches', [[J('k', 'k'), J('l')]]),
               ('topological_order', [[J('p'), J('q'), J('r'), J('s'), J('t', 'pqrs')]])],
}

DEFECTS = [
    {'ticket': 'A', 'op': 'core', 'defect': 'converts with float() and multiplies, so "0.29" becomes 28 minor units',
     'families': ['float_artifact'],
     'why_semantic': 'exact parsing needs integer construction from the digit strings; no operator or constant change '
                     'of the float expression is exact'},
    {'ticket': 'A', 'op': 'core', 'defect': 'rounds excess fractional digits instead of rejecting them',
     'families': ['excess_precision'],
     'why_semantic': 'rejection needs a new validation of the fractional length; round() cannot raise'},
    {'ticket': 'A', 'op': 'core', 'defect': 'accepts every syntax float() accepts (exponent, plus, whitespace, leading '
                                            'zeros, a missing digit, nan)', 'families': ['malformed'],
     'why_semantic': 'the grammar has to be checked explicitly; float() has no strict mode'},
    {'ticket': 'A', 'op': 'core', 'defect': 'no limit of nine integer digits', 'families': ['integer_digit_limit'],
     'why_semantic': 'needs a new length check on the integer part'},
    {'ticket': 'A', 'op': 'core', 'defect': 'accepts non-text input (an int or a bool)', 'families': ['type_confusion'],
     'why_semantic': 'needs a new type check that excludes bool'},
    {'ticket': 'A', 'op': 'adapter', 'defect': 'formats with divmod(total, 100), so a negative total of -150 renders '
                                               'as "-2.50"', 'families': ['negative_total'],
     'why_semantic': 'needs sign handling around the magnitude; floor division of a negative total has no operator '
                     'swap that formats correctly'},
    {'ticket': 'A', 'op': 'adapter', 'rev': 2, 'defect': 'hard-codes two fractional digits (revision 2 requires three)',
     'families': ['revision_precision', 'formatting_padding'],
     'why_semantic': 'needs a three-digit scale and three-digit padding together'},
    {'ticket': 'B', 'op': 'core', 'defect': 'assumes sorted input', 'families': ['unsorted'],
     'why_semantic': 'needs a sort step that the loop does not have'},
    {'ticket': 'B', 'op': 'core', 'defect': 'treats touching intervals as separate', 'families': ['touching'],
     'why_semantic': 'needs <= on the merge test together with the sort; alone the operator change still fails the '
                     'unsorted and zero-length rows'},
    {'ticket': 'B', 'op': 'core', 'defect': 'keeps zero-length intervals', 'families': ['zero_length'],
     'why_semantic': 'needs a new filter'},
    {'ticket': 'B', 'op': 'core', 'defect': 'no validation: reversed, bool and non-int endpoints pass',
     'families': ['invalid'], 'why_semantic': 'needs a new validation pass before merging'},
    {'ticket': 'B', 'op': 'adapter', 'defect': 'does not clip busy intervals to the window and passes busy to the union '
                                               'unchanged', 'families': ['crossing_window_start', 'call_contract'],
     'why_semantic': 'needs a new clipped list built from the window'},
    {'ticket': 'B', 'op': 'adapter', 'defect': 'no validation of the window or busy intervals',
     'families': ['invalid_window', 'invalid_busy'], 'why_semantic': 'needs a new validation pass'},
    {'ticket': 'C', 'op': 'core', 'defect': 'mutates base (the result is base itself)', 'families': ['aliasing'],
     'why_semantic': 'needs a recursive deep copy, which the module does not have'},
    {'ticket': 'C', 'op': 'core', 'defect': 'raises KeyError when deleting a missing key',
     'families': ['missing_deletion_target'], 'why_semantic': 'needs a guarded removal instead of del'},
    {'ticket': 'C', 'op': 'core', 'defect': 'returns patch values without deep copies',
     'families': ['arrays', 'aliasing'], 'why_semantic': 'needs the deep copy on every non-object value'},
    {'ticket': 'C', 'op': 'adapter', 'defect': 'orders revisions by the text of seq (10 before 2)',
     'families': ['numeric_sequence_order'], 'why_semantic': 'needs numeric ordering together with seq validation'},
    {'ticket': 'C', 'op': 'adapter', 'defect': 'accepts duplicate seqs', 'families': ['duplicate_sequence'],
     'why_semantic': 'needs a new duplicate check before any call'},
    {'ticket': 'C', 'op': 'adapter', 'defect': 'accepts bool, zero, negative and text seqs',
     'families': ['invalid_sequence'], 'why_semantic': 'needs a new type and range check'},
    {'ticket': 'C', 'op': 'adapter', 'defect': 'returns base itself when there are no revisions',
     'families': ['empty_revisions', 'aliasing'], 'why_semantic': 'needs a deep copy of base'},
    {'ticket': 'D', 'op': 'core', 'defect': 'FIFO ready queue instead of the earliest input position among ready jobs',
     'families': ['newly_ready_earlier_index'],
     'why_semantic': 'needs selection of the minimum position among ready jobs at every step'},
    {'ticket': 'D', 'op': 'core', 'defect': 'duplicate ids collapse silently', 'families': ['duplicate_id'],
     'why_semantic': 'needs a new duplicate check'},
    {'ticket': 'D', 'op': 'core', 'defect': 'a missing dependency silently drops the job',
     'families': ['missing_dependency'], 'why_semantic': 'needs a new membership check'},
    {'ticket': 'D', 'op': 'core', 'defect': 'a cycle returns a partial order', 'families': ['self_cycle',
                                                                                         'multi_node_cycle'],
     'why_semantic': 'needs a completeness check after the loop'},
    {'ticket': 'D', 'op': 'adapter', 'defect': 'level is the shortest dependency chain (min) instead of the longest',
     'families': ['diamond_unequal_paths'],
     'why_semantic': 'min to max alone still fails the within-batch order rows'},
    {'ticket': 'D', 'op': 'adapter', 'defect': 'batches follow input order instead of the topological order',
     'families': ['within_batch_order'], 'why_semantic': 'needs iteration over the returned order'},
]

CATEGORIES = ('value', 'empty_or_identity', 'raises:ValueError')
KINDS = {'core': ('direct',), 'adapter': ('stub', 'integration')}
INAPPLICABLE = {'C1.core': {'raises:ValueError': 'merge_patch raises nothing for inputs inside its contract'}}
EMPTY_FAMILIES = {'zero_and_negative_zero', 'empty_input', 'empty_collection', 'empty_graph', 'empty_patch',
                  'empty_revisions', 'empty_busy', 'zero_width_window', 'cancellation'}


# ---- sources, records and tickets ----

def module_path(kind: str, ticket: str, rev: int) -> Path:
    name = f'{ticket}_rev{rev}.py' if ticket == 'A' else f'{ticket}.py'
    root = {'original': PACK / 'originals', 'ref1': HERE / 'ref1', 'ref2': HERE / 'ref2',
            'fixture': O1 / 'fixture'}[kind]
    return root / name


def function_source(text: str, name: str) -> str:
    tree = ast.parse(text)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    lines = text.splitlines(keepends=True)
    return ''.join(lines[fn.lineno - 1:fn.end_lineno])


def spans(text: str, names) -> dict:
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    out = {}
    for fn in tree.body:
        if isinstance(fn, ast.FunctionDef) and fn.name in names:
            start = sum(len(x.encode('utf-8')) for x in lines[:fn.lineno - 1])
            end = sum(len(x.encode('utf-8')) for x in lines[:fn.end_lineno])
            out[fn.name] = [start, end]
    return out


def _example(name, args, result):
    call = f'{name}({", ".join(repr(a) for a in args)})'
    return f'{call} raises {result}' if result == 'ValueError' else f'{call} returns {result!r}'


def render_record(ticket, rev, op, module_text):
    module, core, core_params, adapter, adapter_params = MODULES[ticket]
    name, params = (core, core_params) if op == 'core' else (adapter, adapter_params)
    lines = ['O1 repair ticket', f'ticket: {ticket}', f'revision: {rev}', f'op: repair_{op}@1', f'module: {module}',
             f'function: {name}', f'signature: def {name}({", ".join(params)}):']
    if op == 'adapter':
        lines.append(f'calls: {core} (the accepted repaired core function, shown at the end)')
    lines += ['', f'{TITLES[ticket]}. Requirements:']
    lines += [f'{i}. {r}' for i, r in enumerate(requirements(ticket, rev)[op], 1)]
    lines += ['', 'Permitted edits:'] + [f'{i}. {r}' for i, r in enumerate(PERMITTED, 1)]
    lines += ['', 'Input limits: ' + LIMITS[ticket], '', 'Public examples:']
    lines += [_example(name, a, r) for a, r in EXAMPLES[(ticket, rev)][op]]
    lines += ['', 'Defective function:', function_source(module_text, name).rstrip('\n')]
    text = '\n'.join(lines) + '\n'
    if op == 'adapter':
        text += '\n' + ACCEPTED_MARKER
    return text


def ticket_json(ticket, rev) -> dict:
    module_text = module_path('original', ticket, rev).read_text(encoding='utf-8')
    module, core, core_params, adapter, adapter_params = MODULES[ticket]
    return {'schema': 'akor.o1-ticket/1', 'workflow': 'repair-handoff-20/v1', 'ticket': ticket, 'revision': rev,
            'title': TITLES[ticket], 'provenance': 'seeded defects in a purpose-built utility module, not a real bug '
                                                  'report',
            'module': module, 'module_source': module_text,
            'core': {'name': core, 'params': core_params, 'requirements': requirements(ticket, rev)['core']},
            'adapter': {'name': adapter, 'params': adapter_params, 'calls': core,
                        'requirements': requirements(ticket, rev)['adapter']},
            'precision': precision(ticket, rev) if ticket == 'A' else None,
            'spans': spans(module_text, (core, adapter)), 'alias_check': ALIAS[ticket],
            'limits': LIMITS[ticket], 'permitted_edits': PERMITTED,
            'core_record': render_record(ticket, rev, 'core', module_text),
            'adapter_record_prefix': render_record(ticket, rev, 'adapter', module_text),
            'accepted_marker': ACCEPTED_MARKER}


def ticket_bytes(ticket, rev) -> bytes:
    return (json.dumps(ticket_json(ticket, rev), ensure_ascii=False, indent=1) + '\n').encode('utf-8')


# ---- running implementations (in process for references; the sandbox for checks) ----

SAFE = None


def safe_builtins():
    import builtins
    global SAFE
    if SAFE is None:
        SAFE = {n: getattr(builtins, n) for n in POLICY['builtins']}
        SAFE['StubCallError'] = SW.StubCallError
    return SAFE


def load_module(kind, ticket, rev):
    """Execute a policy-conforming module in process with the restricted builtins (trusted build-time use)."""
    text = module_path(kind, ticket, rev).read_text(encoding='utf-8')
    _, core, cp, adapter, ap = MODULES[ticket]
    problems = SW.check_module(text, {core: cp, adapter: ap}, POLICY)
    if problems:
        raise SystemExit(f'{kind} {ticket} rev {rev} breaks the policy: {problems}')
    ns = {'__builtins__': safe_builtins()}
    exec(compile(text, f'<{kind}-{ticket}{rev}>', 'exec'), ns)
    return ns


def outcome(fn, args, *, alias=False):
    args = json.loads(json.dumps(args))
    before = SW.canonical(args)
    held = SW._containers(args, set())
    out = {}
    try:
        value = fn(*args)
    except Exception as exc:  # noqa: BLE001  the class name is the outcome
        out['x'] = type(exc).__name__
    else:
        try:
            out['r'] = SW.canonical(value)
            if alias and SW._containers(value, set()) & held:
                out['alias'] = True
        except SW.Unsupported as exc:
            out['bad'] = str(exc)
    if SW.canonical(args) != before:
        out['mut'] = True
    return out


def namespaces(kind, ticket, rev, core_kind=None):
    """(core namespace, adapter namespace) as the worker builds them: the adapter is executed alone in its own
    namespace with the core function bound by name (so the core's own recursion is never recorded or stubbed)."""
    _, core, _, adapter, _ = MODULES[ticket]
    ns_core = load_module(core_kind or kind, ticket, rev)
    text = module_path(kind, ticket, rev).read_text(encoding='utf-8')
    ns_adapter = {'__builtins__': safe_builtins(), core: ns_core[core]}
    exec(compile(function_source(text, adapter), f'<{kind}-{ticket}{rev}-adapter>', 'exec'), ns_adapter)
    return ns_core, ns_adapter


def run_row_in_process(ns_core, ns_adapter, ticket, op, row):
    """Outcome of one A row in process: stubs and call records as the worker does them."""
    _, core, _, adapter, _ = MODULES[ticket]
    if op == 'core':
        return outcome(ns_core[core], row['args'], alias=ALIAS[ticket])
    calls = []
    saved = ns_adapter[core]
    if 'stub' in row:
        ns_adapter[core] = SW._stub(row['stub'], calls, safe_builtins())
    else:
        ns_adapter[core] = SW._recorder(saved, calls)
    try:
        out = outcome(ns_adapter[adapter], row['args'], alias=ALIAS[ticket])
    finally:
        ns_adapter[core] = saved
    out['calls'] = calls
    return out


def expected_of(out: dict) -> dict:
    if 'bad' in out or out.get('mut') or out.get('alias'):
        raise SystemExit(f'a reference produced an unacceptable outcome: {out}')
    return {k: out[k] for k in ('r', 'x', 'calls') if k in out}


def build_tier_a():
    tier = {}
    for (ticket, rev, op), make in AUTHORED.items():
        rows = make()
        refs = [namespaces(k, ticket, rev) for k in ('ref1', 'ref2')]
        built = []
        for k, row in enumerate(rows):
            outs = [expected_of(run_row_in_process(nc, na, ticket, op, row)) for nc, na in refs]
            if outs[0] != outs[1]:
                raise SystemExit(f'references disagree on {ticket}{rev} {op} row {k}: {outs}')
            kind = 'stub' if 'stub' in row else ('integration' if op == 'adapter' else 'direct')
            entry = {'id': f'{ticket}{rev}.{op}.{k:02d}', 'kind': kind, 'family': row['family'], 'side': row['side'],
                     'args': row['args'], 'expect': outs[0]}
            if 'stub' in row:
                entry['stub'] = row['stub']
            entry['category'] = category(entry, op)
            built.append(entry)
        tier[f'{ticket}{rev}.{op}'] = built
    # M4: every core call an adapter integration row makes is a core A input of that ticket and revision.
    for (ticket, rev) in REVISIONS:
        core_rows = tier[f'{ticket}{rev}.core']
        have = {SW.canonical(r['args']) for r in core_rows}
        refs = [namespaces(k, ticket, rev) for k in ('ref1', 'ref2')]
        for row in tier[f'{ticket}{rev}.adapter']:
            if row['kind'] != 'integration':
                continue
            for call in row['expect']['calls']:
                if call in have:
                    continue
                args = json.loads(call)
                outs = [expected_of(run_row_in_process(nc, na, ticket, 'core', {'args': args})) for nc, na in refs]
                if outs[0] != outs[1]:
                    raise SystemExit(f'references disagree on support row {call}')
                entry = {'id': f'{ticket}{rev}.core.{len(core_rows):02d}', 'kind': 'direct',
                         'family': 'integration_support', 'side': 'n/a', 'args': args, 'expect': outs[0]}
                entry['category'] = category(entry, 'core')
                core_rows.append(entry)
                have.add(call)
    return tier


def category(entry, op):
    if 'x' in entry['expect']:
        return 'raises:' + entry['expect']['x']
    if entry['family'] in EMPTY_FAMILIES:
        return 'empty_or_identity'
    return 'value'


def build_tier_i():
    out = {}
    for (ticket, rev), rows in I_ROWS.items():
        refs = [load_module(k, ticket, rev) for k in ('ref1', 'ref2')]
        built = []
        for k, (fn, args) in enumerate(rows):
            outs = [expected_of(outcome(ns[fn], args, alias=ALIAS[ticket])) for ns in refs]
            if outs[0] != outs[1]:
                raise SystemExit(f'references disagree on I row {ticket}{rev} {k}')
            built.append({'id': f'I.{ticket}{rev}.{k:02d}', 'fn': fn, 'args': args, 'expect': outs[0]})
        out[f'{ticket}{rev}'] = built
    return out


def matches(out: dict, expect: dict) -> bool:
    if 'bad' in out or out.get('mut') or out.get('alias'):
        return False
    if {k: out[k] for k in ('r', 'x') if k in out} != {k: expect[k] for k in ('r', 'x') if k in expect}:
        return False
    return 'calls' not in expect or out.get('calls') == expect['calls']


def failing_rows(kind, ticket, rev, op, rows, *, source=None):
    """Row ids an implementation fails (in process). An adapter is judged with the reference core bound, as the
    acceptance rows assume an A-verified core. source replaces the judged function's source."""
    _, core, _, adapter, _ = MODULES[ticket]
    ns_core, ns_adapter = namespaces(kind, ticket, rev, core_kind='ref1' if op == 'adapter' else None)
    if source is not None:
        target = ns_core if op == 'core' else ns_adapter
        exec(compile(source, '<override>', 'exec'), target)
    bad = []
    for row in rows:
        try:
            out = run_row_in_process(ns_core, ns_adapter, ticket, op, row)
        except RecursionError:
            out = {'x': 'RecursionError'}
        if not matches(out, row['expect']):
            bad.append(row['id'])
    return bad


def coverage(tier):
    matrix, problems = {}, []
    for key, rows in tier.items():
        op = key.split('.')[1]
        families = {}
        for r in rows:
            f = families.setdefault(r['family'], {'rows': 0, 'sides': set(), 'categories': set()})
            f['rows'] += 1
            f['sides'].add(r['side'])
            f['categories'].add(r['category'])
        cats = sorted({r['category'] for r in rows})
        if len(rows) < 12:
            problems.append(f'{key}: {len(rows)} rows, fewer than 12')
        for name, f in families.items():
            if f['rows'] < 2 and name != 'integration_support':
                problems.append(f'{key}: family {name} has {f["rows"]} row')
            if f['sides'] & {'inside', 'outside'} and not {'inside', 'outside'} <= f['sides']:
                problems.append(f'{key}: family {name} lacks one side of its edge')
        skip = INAPPLICABLE.get(key, {})
        missing = [c for c in CATEGORIES if c not in cats and c not in skip]
        missing += [k for k in KINDS[op] if k not in {r['kind'] for r in rows}]
        if missing:
            problems.append(f'{key}: categories or kinds missing {missing}')
        if any(c in cats for c in skip):
            problems.append(f'{key}: a category marked inapplicable occurs')
        matrix[key] = {'rows': len(rows), 'categories': cats, 'inapplicable': skip,
                       'kinds': {k: sum(1 for r in rows if r['kind'] == k) for k in KINDS[op]},
                       'families': {n: {'rows': f['rows'], 'sides': sorted(f['sides']),
                                        'categories': sorted(f['categories'])} for n, f in sorted(families.items())}}
    return matrix, problems


def defect_report(tier):
    out, problems = [], []
    for d in DEFECTS:
        revs = [d['rev']] if 'rev' in d else [r for t, r in REVISIONS if t == d['ticket']]
        for rev in revs:
            rows = [r for r in tier[f"{d['ticket']}{rev}.{d['op']}"] if r['family'] in d['families']]
            failed = failing_rows('original', d['ticket'], rev, d['op'], rows)
            if not failed:
                problems.append(f"defect not discriminated: {d['ticket']}{rev} {d['op']}: {d['defect']}")
            out.append(dict({k: v for k, v in d.items() if k != 'rev'}, revision=rev, discriminating_rows=failed))
    return out, problems


# ---- H tier ----

def h_expected(key: str):
    ticket = key[0]
    rev = 2 if key.startswith('A2') else 1
    op = key.split('.')[1]
    _, core, _, adapter, _ = MODULES[ticket]
    fn = core if op == 'core' else adapter
    vectors = []
    for kind in ('ref1', 'ref2'):
        ns = load_module(kind, ticket, rev)
        vec = []
        for args in H.domain(key):
            out = outcome(ns[fn], args, alias=ALIAS[ticket])
            if 'bad' in out or out.get('mut') or out.get('alias'):
                raise SystemExit(f'{kind} unacceptable outcome on H {key} {args}: {out}')
            vec.append('r:' + out['r'] if 'r' in out else 'x:' + out['x'])
        vectors.append(vec)
    if vectors[0] != vectors[1]:
        diff = next(i for i, (a, b) in enumerate(zip(*vectors)) if a != b)
        raise SystemExit(f'references disagree on H {key} input {H.domain(key)[diff]}: {vectors[0][diff]} '
                         f'against {vectors[1][diff]}')
    return vectors[0]


def build_heldout():
    out = {'schema': 'akor.o1-heldout/1', 'note': 'evaluator only; expected outcomes from ref1 and ref2, which agree '
                                                  'on every input', 'domains': {}}
    for key in H.KEYS:
        inputs = H.domain(key)
        if len(inputs) != H.CARDINALITY[key]:
            raise SystemExit(f'H domain {key} has {len(inputs)} inputs, frozen {H.CARDINALITY[key]}')
        vec = h_expected(key)
        text = json.dumps(vec, separators=(',', ':'))
        out['domains'][key] = {
            'cardinality': len(inputs), 'description': H.DESCRIPTION[key],
            'inputs_sha256': hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            'expected_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'expected_zlib_b64': base64.b64encode(zlib.compress(text.encode(), 9)).decode('ascii'),
            'outcome_counts': {'value': sum(1 for v in vec if v.startswith('r:')),
                               'ValueError': sum(1 for v in vec if v == 'x:ValueError')}}
    return out


def check_examples() -> list:
    problems = []
    for (ticket, rev), ops in EXAMPLES.items():
        _, core, _, adapter, _ = MODULES[ticket]
        for kind in ('ref1', 'ref2'):
            ns = load_module(kind, ticket, rev)
            for op, examples in ops.items():
                fn = ns[core if op == 'core' else adapter]
                for args, result in examples:
                    out = outcome(fn, args)
                    want = {'x': 'ValueError'} if result == 'ValueError' else {'r': SW.canonical(result)}
                    if {k: out[k] for k in ('r', 'x') if k in out} != want:
                        problems.append(f'public example {ticket}{rev} {op} {args} disagrees with {kind}: {out}')
    return problems


def write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    for ticket, rev in REVISIONS:
        path = PACK / 'tickets' / f'{ticket}.rev{rev}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        if '--check' in args:
            if path.read_bytes().replace(b'\r\n', b'\n') != ticket_bytes(ticket, rev):
                print(f'{path.name} differs from its generator', file=sys.stderr)
                return 1
        else:
            path.write_bytes(ticket_bytes(ticket, rev))
    tier = build_tier_a()
    matrix, problems = coverage(tier)
    defects, more = defect_report(tier)
    problems += more
    if problems:
        print('\n'.join(problems), file=sys.stderr)
        return 1
    tier_i = build_tier_i()
    problems = check_examples()
    if problems:
        print('\n'.join(problems), file=sys.stderr)
        return 1
    if '--check' in args:
        for name, obj in (('tier_a.json', tier), ('tier_i.json', tier_i), ('coverage.json', matrix),
                          ('defects.json', defects)):
            if json.loads((PACK / name).read_text(encoding='utf-8')) != json.loads(json.dumps(obj)):
                print(f'{name} differs from its generator', file=sys.stderr)
                return 1
        if json.loads((HERE / 'heldout.json').read_text(encoding='utf-8')) != build_heldout():
            print('heldout.json differs from its generator', file=sys.stderr)
            return 1
        print('build check ok')
        return 0
    write(PACK / 'tier_a.json', tier)
    write(PACK / 'tier_i.json', tier_i)
    write(PACK / 'coverage.json', matrix)
    write(PACK / 'defects.json', defects)
    write(HERE / 'heldout.json', build_heldout())
    print(json.dumps({'tier_a_rows': {k: len(v) for k, v in tier.items()},
                      'tier_i_rows': {k: len(v) for k, v in tier_i.items()},
                      'defects': len(defects), 'heldout': {k: H.CARDINALITY[k] for k in H.KEYS}}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
