"""Stage B packets of the frozen stage-1g decision test (docs/design/stage-1g-final-decision.md): five heterogeneous
64-job packets, data seeds 3001-3005. Every result of a packet is of one family, so the first output record is of that
family whatever the output order: P1 empty arrays, P2 scalars, P3 objects, P4 nested arrays, P5 job failures (16 per code).
The test measures the wire, so each expected result follows from the op text and the refs alone, no judgment.
packet(k) -> (body_text, ids, expected); expected maps job ID -> ("ok", value) or ("error", code).
judge(reply, ids, expected, header) -> (accepted, correct, error); the product parser decides acceptance.
"""
import json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import live11 as M
import oz_batch

N = 64
ESC = ['say "hi"', 'C:\\temp\\new', 'line one\nline two', 'a "b" \\ c', '"quoted"', 'end\\']
NAMES = ['ada', 'bo', 'cy', 'dee', 'eli', 'fay', 'gus', 'hal', 'ivy', 'jo', 'kai', 'lu']
CITIES = ['Oslo', 'Rome', 'Lima', 'Kyiv', 'Bern', 'Doha', 'Nuuk', 'Port "A"', 'Quay\\9']
SPECIAL = {1: ['error'], 2: ['id'], 3: ['error'], 4: ['id'], 5: ['error', 'id']}
PREFIX = ['a', 'j', 't', 'job-', 'r_', 'k', 'x-']


def pick(rng, plain, esc=ESC, p=0.4):
    return rng.choice(esc) if rng.random() < p else rng.choice(plain)


# P1: every result is []
def p1_tags(rng):
    return [{'tags': [rng.choice(NAMES)[:rng.randint(2, 4)] for _ in range(rng.randint(2, 5))]}], []


def p1_flags(rng):
    return [{'flags': {k: False for k in rng.sample('abcde', rng.randint(1, 4))}}], []


def p1_diff(rng):
    first = rng.sample(range(1, 21), rng.randint(1, 3))
    second = first + rng.sample(range(21, 31), rng.randint(1, 3))
    rng.shuffle(second)
    return [{'items': first}, {'items': second}], []


def p1_note(rng):
    words = ['red', 'blue', 'sky', 'fox', 'run', 'top', 'say "hi"', 'C:\\tmp', 'one\ntwo']
    return [{'note': ' '.join(rng.sample(words, rng.randint(2, 4)))}], []


# P2: every result is a scalar
def p2_sum(rng):
    a, b = rng.randint(0, 9), rng.randint(0, 9)
    return [{'a': a, 'b': b}], a + b


def p2_title(rng):
    t = pick(rng, ['Weekly report', 'Q3 plan', 'Draft v2', 'notes'])
    return [{'title': t, 'rev': rng.randint(1, 9)}], t


def p2_status(rng):
    s = rng.choice(['done', 'open', 'blocked', 'wip'])
    return [{'status': s}], s == 'done'


def p2_rank(rng):
    a, b = rng.randint(1, 9), rng.randint(1, 9)
    return [{'rank': a}, {'rank': b}], a - b


def p2_owner(rng):
    if rng.random() < 0.5:
        return [{'task': rng.randint(1, 99)}], 'unknown'
    o = pick(rng, NAMES, ['o"neil', 'back\\slash'], 0.25)
    return [{'owner': o, 'task': rng.randint(1, 99)}], o


def p2_price(rng):
    p = rng.randint(0, 9) + rng.choice([0.25, 0.75])
    return [{'price': p}], p * 2


def p2_count(rng):
    n = rng.randint(0, 5)
    return [{'tags': [rng.choice(NAMES) for _ in range(n)]}], n


def const(value):
    return lambda rng: ([], value)


# P3: every result is an object
def p3_pos(rng):
    pos = {'x': rng.randint(-5, 9), 'y': rng.randint(-5, 9)}
    if rng.random() < 0.4:
        pos['tags'] = rng.sample(NAMES, rng.randint(1, 2))
    return [{'pos': pos}], pos


def p3_name(rng):
    name, n = pick(rng, NAMES), rng.randint(0, 4)
    return [{'name': name, 'tags': rng.sample(NAMES, n)}], {'name': name, 'n': n}


def p3_city(rng):
    a, b = rng.sample(CITIES, 2)
    return [{'city': a}, {'city': b}], {'from': a, 'to': b}


def p3_opts(rng):
    opts = {k: rng.random() < 0.4 for k in rng.sample('abcd', rng.randint(2, 4))}
    return [{'opts': opts}], {k: v for k, v in opts.items() if v}


def p3_group(rng):
    words = rng.sample(['ant', 'apple', 'bee', 'bat', 'cat', 'cow', 'dog'], rng.randint(3, 5))
    out = {}
    for w in words:
        out.setdefault(w[0], []).append(w)
    return [{'words': words}], out


# P4: every result is an array of arrays
def grid(rng):
    return [[rng.randint(0, 9) for _ in range(c)] for c in [rng.randint(2, 3)] for _ in range(rng.randint(2, 3))]


def p4_grid(rng):
    g = grid(rng)
    return [{'grid': g}], g


def p4_transpose(rng):
    g = grid(rng)
    return [{'grid': g}], [list(col) for col in zip(*g)]


def p4_kv(rng):
    kv = {k: pick(rng, ['x', 'y', 'zed'], ['q"q', 'b\\s'], 0.25) if rng.random() < 0.5 else rng.randint(0, 9)
          for k in rng.sample('abcde', rng.randint(2, 3))}
    return [{'kv': kv}], [[k, v] for k, v in kv.items()]


def p4_ids(rng):
    a, b = rng.sample(['u1', 'u2', 'u3', 'u4', 'u5', 'u6'], 2)
    return [{'id': a}, {'id': b}], [[a, b]]


def p4_text(rng):
    words = ['red', 'fox', '"hi"', 'C:\\tmp', 'sky', 'a\\b', 'say', 'run']
    lines = [rng.sample(words, rng.randint(1, 3)) for _ in range(rng.randint(2, 3))]
    return [{'text': '\n'.join(' '.join(w) for w in lines)}], lines


# P5: every result is a job failure with the code the op text names
def err(code, gen):
    return lambda rng: (gen(rng), code)


def p5_density(rng):
    return [{'name': rng.choice(NAMES), 'mass': rng.randint(1, 99)}]


def p5_base(rng):
    a, b = {'base': rng.randint(1, 9)}, {'extra': rng.randint(1, 9)}
    return rng.choice([[a, {'base': 5}], [{'extra': 4}, b], [{'extra': 3}, {'extra': 2}]])


def p5_qty(rng):
    return [{'qty': rng.choice(['twelve', '4.5kg', 'n/a', '3.5', '12 apples', '']), 'sku': rng.randint(100, 999)}]


def p5_tags(rng):
    return [{'tags': rng.choice(['red, blue', 7, {'a': 1}, None, True, 'say "hi"\nnow', 'C:\\tags'])}]


def p5_count(rng):
    bad = rng.choice(['ten', None, '4', False])
    return rng.choice([[{'count': bad}, {'count': 5}], [{'count': 8}, {'count': bad}]])


def p5_minmax(rng):
    lo = rng.randint(1, 9)
    return [{'min': lo + rng.randint(1, 9), 'max': lo}]


def p5_owner(rng):
    a, b = rng.sample(NAMES, 2)
    return [{'owner': a}, {'owner': b}]


def p5_unit(rng):
    return [{'amount': rng.randint(1, 50), 'unit': rng.choice(['lb', 'oz', 'stone', 'ton'])}]


def p5_case(rng):
    return [{'text': pick(rng, ['hello world', 'Mixed Case', 'abc'])}, {'case': rng.choice(['title', 'snake', 'camel', 'swap'])}]


PACKETS = {
    1: ('Answer from the supplied refs only.', [
        ('Return the strings in the ref\'s `tags` array that are longer than 6 characters, in order, as a JSON array.', 11, p1_tags),
        ('List the names of the `flags` entries of the ref whose value is true, as a JSON array of strings.', 11, p1_flags),
        ('Return the elements of the first ref\'s `items` array that are not in the second ref\'s `items` array, in the first ref\'s order, as a JSON array.', 11, p1_diff),
        ('List the integers strictly between 7 and 8 as a JSON array.', 11, const([])),
        ('List the English month names that have more than 31 days, as a JSON array of strings.', 10, const([])),
        ('Return the words of the ref\'s `note` that start with the letter z, as a JSON array of strings.', 10, p1_note)]),
    2: ('Answer from the supplied refs only.', [
        ('Return the number of days in a week as a JSON integer.', 4, const(7)),
        ('Return true if 91 is a prime number, otherwise false, as a JSON boolean.', 3, const(False)),
        ('Return the chemical symbol of sodium as a JSON string.', 3, const('Na')),
        ('Return the integer field `a` plus the integer field `b` of the ref, as a JSON integer.', 10, p2_sum),
        ('Return the ref\'s `title` field exactly as it is, as a JSON string.', 10, p2_title),
        ('Return true if the ref\'s `status` field is the string "done", otherwise false, as a JSON boolean.', 8, p2_status),
        ('Return the first ref\'s `rank` minus the second ref\'s `rank`, as a JSON integer.', 8, p2_rank),
        ('Return the ref\'s `owner` field as a JSON string. If the ref has no `owner` field, return the JSON string "unknown" instead of failing.', 8, p2_owner),
        ('Return the ref\'s `price` multiplied by 2, as a JSON number.', 5, p2_price),
        ('Return the number of elements in the ref\'s `tags` array, as a JSON integer.', 5, p2_count)]),
    3: ('Answer from the supplied refs only.', [
        ('Return a JSON object that maps "jan", "feb" and "mar" to their numbers of days in a non-leap year, as integers.', 5, const({'jan': 31, 'feb': 28, 'mar': 31})),
        ('Return a JSON object whose key "primes" is the number of primes below 10 and whose key "evens" is the number of even integers from 1 to 10, both as integers.', 4, const({'primes': 4, 'evens': 5})),
        ('Return the ref\'s `pos` object unchanged.', 10, p3_pos),
        ('Return a JSON object with "name" set to the ref\'s `name` string and "n" set to the number of elements in its `tags` array, as an integer.', 12, p3_name),
        ('Return a JSON object with "from" set to the first ref\'s `city` and "to" set to the second ref\'s `city`.', 11, p3_city),
        ('Return a JSON object holding only the entries of the ref\'s `opts` object whose value is true, with their keys and values; it may be the empty object.', 10, p3_opts),
        ('Group the ref\'s `words` array by first letter: return a JSON object that maps each first letter to the array of the words starting with it, in their order in `words`.', 12, p3_group)]),
    4: ('Answer from the supplied refs only.', [
        ('Return the multiplication table for the factors 1 and 2 against 1, 2 and 3: a JSON array of two rows, row f listing f*1, f*2, f*3 as integers.', 4, const([[1, 2, 3], [2, 4, 6]])),
        ('Return a JSON array of [letter, position] pairs for the first three letters of the English alphabet, in order, positions starting at 1.', 3, const([['a', 1], ['b', 2], ['c', 3]])),
        ('Return the ref\'s `grid` array unchanged.', 10, p4_grid),
        ('Transpose the ref\'s `grid` (an array of rows of equal length) and return the array of its columns.', 12, p4_transpose),
        ('Return a JSON array of [key, value] pairs, one per entry of the ref\'s `kv` object, in the order the keys appear.', 11, p4_kv),
        ('Return a JSON array holding exactly one pair, [first ref\'s `id`, second ref\'s `id`].', 10, p4_ids),
        ('Split the ref\'s `text` into lines at newline characters, split each line into words at single spaces, and return the array of lines, each an array of words.', 14, p4_text)]),
    5: ('Answer from the supplied refs only. Follow each operation text exactly, including its failure rule.', [
        ('Return the ref\'s `density` field as a JSON number. If the ref has no `density` field, fail with missing_data.', 6, err('missing_data', p5_density)),
        ('Return the first ref\'s `base` plus the second ref\'s `extra`, as a JSON integer. If either ref lacks its field, fail with missing_data.', 6, err('missing_data', p5_base)),
        ('Return the sum of the `qty` fields of all supplied refs, as a JSON integer. If no ref is supplied, fail with missing_data.', 4, err('missing_data', lambda rng: [])),
        ('Parse the ref\'s `qty` string as a base-10 integer and return it as a JSON integer. If it is not a base-10 integer, fail with invalid_data.', 6, err('invalid_data', p5_qty)),
        ('Return the number of elements in the ref\'s `tags` field, as a JSON integer. If `tags` is not an array, fail with invalid_data.', 5, err('invalid_data', p5_tags)),
        ('Return the first ref\'s `count` divided by the second ref\'s `count`, as a JSON number. If either `count` is not a JSON number, fail with invalid_data.', 5, err('invalid_data', p5_count)),
        ('Return a JSON object {"lo":min,"hi":max} from the ref\'s `min` and `max` integers. If `min` is greater than `max`, fail with conflict.', 6, err('conflict', p5_minmax)),
        ('Return the first ref\'s `owner`. If the second ref\'s `owner` is a different string, fail with conflict.', 6, err('conflict', p5_owner)),
        ('Return the length in minutes of a meeting that starts at 10:00 and ends at 09:00 on the same day, as a JSON integer. If the end is before the start, fail with conflict.', 4, err('conflict', lambda rng: [])),
        ('Convert the ref\'s `amount` to grams, using its `unit`. Only the units g and kg are supported; for any other unit fail with unsupported.', 6, err('unsupported', p5_unit)),
        ('Return the first ref\'s `text` converted to the case named by the second ref\'s `case`. Only the cases upper and lower are supported; for any other `case` value fail with unsupported.', 6, err('unsupported', p5_case)),
        ('Return the current local time of the host as a JSON string. You cannot read a clock, so fail with unsupported.', 4, err('unsupported', lambda rng: []))]),
}
for _k, (_goal, _ops) in PACKETS.items():
    assert sum(c for _, c, _ in _ops) == N, _k


def packet(k):
    goal, spec = PACKETS[k]
    rng = random.Random(3000 + k)
    ops, refs, ref_idx, blocks, ids, expected, used = [], [], {}, [], [], {}, set()
    rows = []
    for text, count, gen in spec:
        ops.append(text)
        rows.append([gen(rng) for _ in range(count)])
    flat = [(op, job) for op, jobs in enumerate(rows) for job in jobs]
    names = {}
    for pos, name in zip(rng.sample(range(len(flat)), len(SPECIAL[k])), SPECIAL[k]):
        names[pos] = name
    for pos, (op, (vals, exp)) in enumerate(flat):
        if pos in names:
            jid = names[pos]
        else:
            while True:
                jid = f'{rng.choice(PREFIX)}{rng.randint(1, 999)}'
                if jid not in used and jid not in SPECIAL[k]:
                    break
        used.add(jid)
        row = [jid]
        for v in vals:
            key = json.dumps(v, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
            if key not in ref_idx:
                ref_idx[key] = len(refs); refs.append(v)
            row.append(ref_idx[key])
        if op == len(blocks):
            blocks.append([op])
        blocks[op].append(row)
        ids.append(jid)
        expected[jid] = ('error', exp) if k == 5 else ('ok', exp)
    body = {'v': oz_batch.VERSION, 'goal': goal, 'ops': ops, 'refs': refs, 'jobs': blocks}
    oz_batch.validate_packet(body)
    assert len(ids) == len(set(ids)) == N
    return json.dumps(body, ensure_ascii=False, separators=(',', ':')), tuple(ids), expected


def same(a, b):
    """JSON equality with types: bool is not a number, 1 equals 1.0, objects ignore key order."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def judge(reply, ids, expected, header):
    try:
        flat = M.stage1g_flat(reply, ids, header=header)
    except Exception as exc:  # noqa: BLE001
        return False, 0, str(exc)[:200]
    correct = 0
    for jid, (good, value) in zip(ids, flat):
        kind, want = expected[jid]
        correct += same(value, want) if kind == 'ok' and good else (kind == 'error' and not good and value[0] == want)
    return True, correct, ''
