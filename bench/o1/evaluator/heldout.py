"""H tier (held out, evaluator only): explicit input domains with frozen cardinalities for repair-handoff-20/v1.

Each domain is generated deterministically here; its cardinality and the sha256 of its canonical input list are frozen
in heldout.json next to the expected outcomes, which come from the two references (ref1, ref2) and must agree on every
input. The executor never reads this directory.
"""
from itertools import permutations, product
import json

KEYS = ('A1.core', 'A1.adapter', 'A2.core', 'A2.adapter', 'B.core', 'B.adapter', 'C.core', 'C.adapter',
        'D.core', 'D.adapter')
CARDINALITY = {'A1.core': 9361, 'A1.adapter': 820, 'A2.core': 9361, 'A2.adapter': 820, 'B.core': 9939,
               'B.adapter': 9737, 'C.core': 3025, 'C.adapter': 2000, 'D.core': 7598, 'D.adapter': 7598}
DESCRIPTION = {
    'A1.core': 'every string over the alphabet "-019.x" of length 0 to 5 (9,331), plus 21 long-digit strings around the '
               'nine-digit limit and 9 non-text values; precision 2',
    'A2.core': 'the A1.core domain at precision 3',
    'A1.adapter': 'every list of length 0 to 3 over 9 amount texts (820), real core; precision 2',
    'A2.adapter': 'the A1.adapter domain at precision 3',
    'B.core': 'every list of 0 to 3 valid intervals with endpoints in -2..3 (21 intervals, 9,724 lists), plus 215 lists '
              'holding one of 5 invalid intervals',
    'B.adapter': 'every busy list of 0 to 2 valid intervals over -2..3 times each of the 21 valid windows (9,723), plus '
                 '14 invalid windows or busy entries',
    'C.core': 'every (base, patch) pair over 55 JSON values (6 atoms or small objects, and every object over keys a, b '
              'with values from those 6 or absent)',
    'C.adapter': '5 bases times every list of 0 to 3 revisions over 7 revision records (400 lists)',
    'D.core': 'every job list of 0 to 3 distinct ids from a, b, c in every order with dependencies any subset of a, b, '
              'c (3,481), every 4-job list in the order c, a, d, b with dependencies any subset of the other three '
              '(4,096), and 21 lists with duplicate ids, missing or repeated dependencies',
    'D.adapter': 'the D.core domain',
}


def _amount_texts():
    out = []
    alphabet = '-019.x'
    for n in range(0, 6):
        out += [''.join(p) for p in product(alphabet, repeat=n)]
    for n in (8, 9, 10, 11):
        out += ['9' * n, '1' + '0' * (n - 1), '-' + '9' * n, '9' * n + '.99']
    out += ['999999999.999', '-999999999.001', '1000000000.0', '0.000', '0.0001']
    return [[t] for t in out] + [[v] for v in (None, True, False, 0, 5, -1, [], {}, ['1'])]


def _amount_lists():
    items = ['0', '-0', '1.5', '-1.50', '0.01', '-0.01', '10', 'x', '1.001']
    out = []
    for n in range(0, 4):
        out += [[list(p)] for p in product(items, repeat=n)]
    return out


def _intervals():
    return [[s, e] for s in range(-2, 4) for e in range(-2, 4) if s <= e]


INVALID_INTERVALS = [[1, 0], [True, 1], [0, '1'], [0], [0, 1, 2]]


def _interval_lists():
    valid = _intervals()
    out = []
    for n in range(0, 4):
        out += [[[list(x) for x in p]] for p in product(valid, repeat=n)]
    for bad in INVALID_INTERVALS:
        out.append([[bad]])
        for v in valid:
            out.append([[v, bad]])
            out.append([[bad, v]])
    return out


def _free_slot_args():
    valid = _intervals()
    out = []
    busy_lists = []
    for n in range(0, 3):
        busy_lists += [[list(x) for x in p] for p in product(valid, repeat=n)]
    for window in valid:
        for busy in busy_lists:
            out.append([busy, list(window)])
    for bad in INVALID_INTERVALS:
        out.append([[], bad])
        out.append([[[0, 1]], bad])
    for bad in INVALID_INTERVALS[:4]:
        out.append([[bad], [-2, 3]])
    return out


def _json_values():
    atoms = [None, 0, False, [], {'k': 0}, {'k': None}]
    objects = []
    choices = ['absent'] + atoms
    seen = set()
    for a, b in product(choices, repeat=2):
        obj = {}
        if a != 'absent':
            obj['a'] = a
        if b != 'absent':
            obj['b'] = b
        key = json.dumps(obj, sort_keys=True)
        if key not in seen:
            seen.add(key)
            objects.append(obj)
    return atoms + objects


def _merge_pairs():
    values = _json_values()
    return [[json.loads(json.dumps(a)), json.loads(json.dumps(b))] for a in values for b in values]


REVISIONS = [{'seq': 1, 'patch': {'a': 0}}, {'seq': 2, 'patch': {'a': None}}, {'seq': 2, 'patch': {'b': {'k': 0}}},
             {'seq': 1, 'patch': 5}, {'seq': True, 'patch': {}}, {'seq': 0, 'patch': {}},
             {'seq': 10, 'patch': {'a': {'k': None}}}]
BASES = [None, {}, {'a': 0}, {'a': {'k': 0}}, [1]]


def _revision_args():
    out = []
    for base in BASES:
        for n in range(0, 4):
            for p in product(REVISIONS, repeat=n):
                out.append([json.loads(json.dumps(base)), json.loads(json.dumps(list(p)))])
    return out


def _job_lists():
    out = []
    names = ['a', 'b', 'c']
    subsets = [[x for x, keep in zip(names, mask) if keep] for mask in product([0, 1], repeat=3)]
    for n in range(0, 4):
        for ids in permutations(names, n):
            for deps in product(subsets, repeat=n):
                out.append([[{'id': i, 'deps': list(d)} for i, d in zip(ids, deps)]])
    order = ['c', 'a', 'd', 'b']
    for deps in product(range(8), repeat=4):
        jobs = []
        for i, mask in zip(order, deps):
            others = [x for x in order if x != i]
            jobs.append({'id': i, 'deps': [o for k, o in enumerate(others) if mask >> k & 1]})
        out.append([jobs])
    extra = [
        [{'id': 'a', 'deps': []}, {'id': 'a', 'deps': []}],
        [{'id': 'a', 'deps': []}, {'id': 'b', 'deps': ['a']}, {'id': 'a', 'deps': []}],
        [{'id': 'b', 'deps': ['a']}, {'id': 'b', 'deps': []}],
        [{'id': 'a', 'deps': ['z']}],
        [{'id': 'a', 'deps': []}, {'id': 'b', 'deps': ['a', 'q']}],
        [{'id': 'a', 'deps': ['a', 'a']}],
        [{'id': 'a', 'deps': []}, {'id': 'b', 'deps': ['a', 'a', 'a']}],
        [{'id': 'b', 'deps': ['a', 'a']}, {'id': 'a', 'deps': []}],
        [{'id': 'd', 'deps': ['c']}, {'id': 'c', 'deps': ['a']}, {'id': 'a', 'deps': []}, {'id': 'b', 'deps': []}],
        [{'id': 'x', 'deps': ['z']}, {'id': 'y', 'deps': ['w']}, {'id': 'w', 'deps': []}, {'id': 'z', 'deps': []}],
        [{'id': 'a', 'deps': []}, {'id': 'b', 'deps': ['a']}, {'id': 'c', 'deps': ['b']}, {'id': 'd', 'deps': ['a', 'c']}],
        [{'id': 'e', 'deps': ['d']}, {'id': 'd', 'deps': ['c']}, {'id': 'c', 'deps': ['b']}, {'id': 'b', 'deps': ['a']},
         {'id': 'a', 'deps': []}],
        [{'id': 'a', 'deps': ['b']}, {'id': 'b', 'deps': ['c']}, {'id': 'c', 'deps': ['a']}],
        [{'id': 'a', 'deps': []}, {'id': 'b', 'deps': ['c']}, {'id': 'c', 'deps': ['b']}],
        [{'id': 'p', 'deps': []}, {'id': 'q', 'deps': []}, {'id': 'r', 'deps': []}, {'id': 's', 'deps': []},
         {'id': 't', 'deps': ['p', 'q', 'r', 's']}],
        [{'id': 'f', 'deps': ['a', 'b']}, {'id': 'e', 'deps': ['a']}, {'id': 'a', 'deps': []}, {'id': 'b', 'deps': []}],
        [{'id': 'm', 'deps': []}, {'id': 'n', 'deps': ['m', 'm']}, {'id': 'o', 'deps': ['n', 'm']}],
        [{'id': 'k', 'deps': ['k']}, {'id': 'l', 'deps': []}],
        [{'id': 'a', 'deps': []}, {'id': 'b', 'deps': []}, {'id': 'b', 'deps': ['a']}],
        [{'id': 'u', 'deps': ['v']}, {'id': 'v', 'deps': ['w']}, {'id': 'w', 'deps': []}, {'id': 'x', 'deps': ['u']}],
        [{'id': 'a', 'deps': ['missing', 'a']}],
    ]
    out += [[jobs] for jobs in extra]
    return out


def domain(key: str) -> list:
    """The frozen H input list for key: a list of argument lists."""
    base = {'A1.core': _amount_texts, 'A2.core': _amount_texts, 'A1.adapter': _amount_lists,
            'A2.adapter': _amount_lists, 'B.core': _interval_lists, 'B.adapter': _free_slot_args,
            'C.core': _merge_pairs, 'C.adapter': _revision_args, 'D.core': _job_lists, 'D.adapter': _job_lists}[key]
    return base()
