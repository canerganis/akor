"""Job generator for the replication operations in ops.md (tensile test records). Standard library, deterministic.

Every random choice comes from random.Random(sub_seed(...)), sub_seed = the first 16 hex digits of
SHA256(canonical([seed, *parts])). jobs() draws from the 'jobs' stream and admission_cases() from the 'admission'
stream; admission specimen identifiers start with 'A' and job identifiers with 'J', so the two text spaces are
disjoint even for the same seed.

jobs(seed, n): n jobs cycling through the four operations; within an operation the records cycle through that
operation's edge plan (PLANS) so any n covers every category as evenly as possible. Jobs are {id, op, text}.
admission_cases(seed, n): n labeled cases {text, op, gold} with the same plan, labeled by oracle.gold.
"""
from decimal import Decimal
import hashlib
import json
import random

from . import oracle

OPS = oracle.OPS
FIELDS = ('specimen', 'grade', 'yield', 'uts', 'gauge', 'final', 'temp', 'operator')
OPERATORS = ('mk', 'ad', 'sb', 'tl', 'rn')
GRADES = ('S235', 'S275', 'S355', 'S460', 'A36')
OTHER_GRADES = ('S420', 'S690', 'unknown')

PLANS = {
    'verdict': ['plain', 'plain', 'boundary_in', 'boundary_out', 'unknown_grade', 'unknown_value', 'spelling',
                'reorder', 'unit', 'newline'],
    'margin': ['plain', 'plain', 'tie', 'zero', 'negative', 'unknown', 'spelling', 'reorder', 'unit', 'newline'],
    'elong': ['plain', 'plain', 'tie', 'zero', 'negative', 'unknown', 'spelling', 'reorder', 'repeating',
              'newline'],
    'temp_class': ['room', 'cold', 'hot', 'boundary_in', 'boundary_out', 'negative', 'unknown', 'spelling',
                   'reorder', 'unit', 'newline'],
}


def canonical(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sub_seed(seed, *parts):
    return int(hashlib.sha256(canonical([seed, *parts])).hexdigest()[:16], 16)


# ------------------------------------------------------------------------------------------------- values

def _d(x):
    return Decimal(x)


def _spell(x, places):
    return f'{_d(x):.{places}f}'


def _grid(lo, hi, step):
    out, x = [], _d(lo)
    while x <= _d(hi):
        out.append(x)
        x += _d(step)
    return out


def _strength(rng, grade):
    """(yield, uts) Decimals that pass the grade table comfortably."""
    min_y, min_u = oracle.GRADES[grade]
    y = min_y + rng.randint(5, 80)
    u = max(min_u + rng.randint(5, 80), y + rng.randint(20, 120))
    return y, u


def _record(rng, prefix, *, grade=None, yield_=None, uts=None, gauge=None, final=None, temp=None, order=None):
    """One record text. Numeric arguments are ready value strings (with unit) or None for a plain random value."""
    g = grade or rng.choice(GRADES)
    if yield_ is None or uts is None:
        y, u = _strength(rng, g if g in oracle.GRADES else rng.choice(GRADES))
        yield_ = yield_ or f'{y} MPa'
        uts = uts or f'{u} MPa'
    if gauge is None or final is None:
        gl = rng.choice(_grid('50.00', '80.00', '0.50'))
        gauge = gauge or _spell(gl, 2) + ' mm'
        final = final or _spell(gl + rng.choice(_grid('5.00', '20.00', '0.25')), 2) + ' mm'
    temp = temp or f'{rng.randint(18, 27)} C'
    values = {'specimen': f'{prefix}{rng.randint(20, 26)}-{rng.randint(1, 999):04d}', 'grade': g,
              'yield': yield_, 'uts': uts, 'gauge': gauge, 'final': final, 'temp': temp,
              'operator': rng.choice(OPERATORS)}
    names = order or FIELDS
    return '; '.join(f'{k}={values[k]}' for k in names)


def _reorder(rng):
    order = list(FIELDS)
    while tuple(order) == FIELDS:
        rng.shuffle(order)
    return order


def _with_newline(rng, text):
    return text + rng.choice(['\n', '\r\n'])


def _make_verdict(rng, prefix, category):
    if category == 'plain':
        g = rng.choice(GRADES)
        if rng.random() < 0.4:
            min_y, min_u = oracle.GRADES[g]
            return _record(rng, prefix, grade=g, yield_=f'{min_y - rng.randint(5, 60)} MPa',
                           uts=f'{min_u + rng.randint(0, 40)} MPa')
        return _record(rng, prefix, grade=g)
    if category in ('boundary_in', 'boundary_out'):
        g = rng.choice(GRADES)
        min_y, min_u = oracle.GRADES[g]
        which = rng.choice(['yield', 'uts', 'both'])
        delta = _d('0') if category == 'boundary_in' else rng.choice([_d('-1'), _d('-0.1'), _d('-0.5')])
        places = 1 if delta != 0 and delta != _d('-1') else rng.choice([0, 1])
        y = _spell(min_y + (delta if which in ('yield', 'both') else rng.randint(10, 60)), places)
        u = _spell(min_u + (delta if which in ('uts', 'both') else rng.randint(10, 60)), places)
        return _record(rng, prefix, grade=g, yield_=y + ' MPa', uts=u + ' MPa')
    if category == 'unknown_grade':
        return _record(rng, prefix, grade=rng.choice(OTHER_GRADES))
    if category == 'unknown_value':
        pick = rng.choice([('unknown', None), (None, 'unknown'), ('unknown', 'unknown')])
        return _record(rng, prefix, yield_=pick[0], uts=pick[1])
    if category == 'spelling':
        g = rng.choice(GRADES)
        y, u = _strength(rng, g)
        return _record(rng, prefix, grade=g, yield_=_spell(y, rng.choice([1, 2])) + ' MPa',
                       uts=_spell(u, rng.choice([1, 2])) + ' MPa')
    if category == 'reorder':
        return _record(rng, prefix, order=_reorder(rng))
    if category == 'unit':
        g = rng.choice(GRADES)
        y, u = _strength(rng, g)
        return _record(rng, prefix, grade=g, yield_=f'{y} N/mm2', uts=f'{u} {rng.choice(["N/mm2", "MPa"])}')
    if category == 'newline':
        return _with_newline(rng, _record(rng, prefix))
    raise ValueError(category)


def _make_margin(rng, prefix, category):
    if category == 'plain':
        return _record(rng, prefix)
    if category == 'tie':
        y = _d(rng.randint(300, 500))
        half = rng.choice(_grid('0.5', '200.5', '1'))
        if rng.random() < 0.5:
            return _record(rng, prefix, yield_=_spell(y, 1) + ' MPa', uts=_spell(y + half, 1) + ' MPa')
        return _record(rng, prefix, yield_=_spell(y + _d('0.5'), 1) + ' MPa', uts=_spell(y + half + _d('0.5'), 0) + ' MPa')
    if category == 'zero':
        y = rng.randint(300, 500)
        u = rng.choice([f'{y} MPa', f'{y}.0 MPa', f'{_d(y) + _d("0.4"):.1f} MPa', f'{_d(y) - _d("0.3"):.1f} MPa'])
        return _record(rng, prefix, yield_=f'{y} MPa', uts=u)
    if category == 'negative':
        y = rng.randint(400, 600)
        return _record(rng, prefix, yield_=f'{y} MPa', uts=f'{y - rng.randint(1, 60)} MPa')
    if category == 'unknown':
        pick = rng.choice([('unknown', None), (None, 'unknown'), ('unknown', 'unknown')])
        return _record(rng, prefix, yield_=pick[0], uts=pick[1])
    if category == 'spelling':
        g = rng.choice(GRADES)
        y, u = _strength(rng, g)
        return _record(rng, prefix, grade=g, yield_=_spell(y, 2) + ' MPa', uts=_spell(u, rng.choice([1, 2])) + ' MPa')
    if category == 'reorder':
        return _record(rng, prefix, order=_reorder(rng))
    if category == 'unit':
        g = rng.choice(GRADES)
        y, u = _strength(rng, g)
        return _record(rng, prefix, grade=g, yield_=f'{y} {rng.choice(["N/mm2", "MPa"])}', uts=f'{u} N/mm2')
    if category == 'newline':
        return _with_newline(rng, _record(rng, prefix))
    raise ValueError(category)


def _make_elong(rng, prefix, category):
    if category == 'plain':
        return _record(rng, prefix)
    if category == 'tie':
        # (final - gauge) / gauge * 100 lands exactly on a second decimal of 5: gauge 80.00 with a difference of
        # k + 0.6 or k + 0.2 (18.25, 17.75 ...), gauge 40.00 with k + 0.3 or k + 0.1.
        gl, step = rng.choice([(_d('80.00'), rng.choice([_d('0.60'), _d('0.20')])),
                               (_d('40.00'), rng.choice([_d('0.30'), _d('0.10')]))])
        diff = _d(rng.randint(5, 20)) + step
        if rng.random() < 0.25:
            diff = -step
        return _record(rng, prefix, gauge=_spell(gl, 2) + ' mm', final=_spell(gl + diff, 2) + ' mm')
    if category == 'zero':
        gl = rng.choice(_grid('50', '80', '10'))
        return _record(rng, prefix, gauge=rng.choice([_spell(gl, 0), _spell(gl, 2)]) + ' mm',
                       final=rng.choice([_spell(gl, 0), _spell(gl, 2), _spell(gl + _d('0.02'), 2),
                                         _spell(gl - _d('0.02'), 2)]) + ' mm')
    if category == 'negative':
        gl = rng.choice(_grid('50.00', '80.00', '0.50'))
        return _record(rng, prefix, gauge=_spell(gl, 2) + ' mm',
                       final=_spell(gl - rng.choice(_grid('0.05', '2.00', '0.05')), 2) + ' mm')
    if category == 'unknown':
        pick = rng.choice([('unknown', None), (None, 'unknown'), ('unknown', 'unknown')])
        return _record(rng, prefix, gauge=pick[0], final=pick[1])
    if category == 'spelling':
        gl = rng.choice(_grid('50', '80', '5'))
        return _record(rng, prefix, gauge=_spell(gl, rng.choice([0, 1, 3])) + ' mm',
                       final=_spell(gl + rng.choice(_grid('5.0', '20.0', '0.5')), rng.choice([1, 3])) + ' mm')
    if category == 'reorder':
        return _record(rng, prefix, order=_reorder(rng))
    if category == 'repeating':
        gl = rng.choice([_d('30.00'), _d('60.00'), _d('70.00'), _d('90.00')])
        return _record(rng, prefix, gauge=_spell(gl, 2) + ' mm',
                       final=_spell(gl + rng.choice(_grid('5.00', '20.00', '1.00')), 2) + ' mm')
    if category == 'newline':
        return _with_newline(rng, _record(rng, prefix))
    raise ValueError(category)


def _make_temp(rng, prefix, category):
    if category == 'room':
        return _record(rng, prefix, temp=f'{rng.randint(11, 34)} C')
    if category == 'cold':
        return _record(rng, prefix, temp=f'{rng.randint(-20, 8)} C')
    if category == 'hot':
        return _record(rng, prefix, temp=f'{rng.randint(36, 200)} C')
    if category == 'boundary_in':
        return _record(rng, prefix, temp=rng.choice(['10 C', '35 C', '10.0 C', '35.0 C', '10.00 C', '35.00 C']))
    if category == 'boundary_out':
        return _record(rng, prefix, temp=rng.choice(['9.9 C', '35.1 C', '9.99 C', '35.01 C', '9 C', '36 C']))
    if category == 'negative':
        return _record(rng, prefix, temp=f'{_spell(-rng.randint(1, 60), rng.choice([0, 1]))} C')
    if category == 'unknown':
        return _record(rng, prefix, temp='unknown')
    if category == 'spelling':
        return _record(rng, prefix, temp=_spell(rng.randint(-10, 60), rng.choice([1, 2])) + ' C')
    if category == 'reorder':
        return _record(rng, prefix, order=_reorder(rng))
    if category == 'unit':
        return _record(rng, prefix, temp=f'{rng.choice([rng.randint(-5, 9), rng.randint(10, 35), rng.randint(36, 80)])} degC')
    if category == 'newline':
        return _with_newline(rng, _record(rng, prefix))
    raise ValueError(category)


MAKERS = {'verdict': _make_verdict, 'margin': _make_margin, 'elong': _make_elong, 'temp_class': _make_temp}


def _unique(rng, op, prefix, category, taken):
    for _ in range(10000):
        text = MAKERS[op](rng, prefix, category)
        if text not in taken and oracle.strip_terminator(text) not in taken:
            taken.add(text)
            taken.add(oracle.strip_terminator(text))
            return text
    raise RuntimeError(f'cannot draw a fresh {op} record for {category}')


def _texts(seed, stream, prefix, n):
    """[(op, category, text)] for n jobs: operations cycle, each operation walks its own plan."""
    rngs = {op: random.Random(sub_seed(seed, stream, op)) for op in OPS}
    counts = {op: 0 for op in OPS}
    taken, out = set(), []
    for i in range(n):
        op = OPS[i % len(OPS)]
        category = PLANS[op][counts[op] % len(PLANS[op])]
        counts[op] += 1
        out.append((op, category, _unique(rngs[op], op, prefix, category, taken)))
    return out


def jobs(seed: int, n: int) -> list:
    """n jobs {id, op, text}; deterministic for a given seed, texts unique within the call."""
    return [{'id': f'{op}-{i:04d}', 'op': op, 'text': text} for i, (op, _, text) in enumerate(_texts(seed, 'jobs', 'J', n))]


def job_categories(seed: int, n: int) -> list:
    """The edge category of every job in jobs(seed, n), in the same order (for reports, never for scoring)."""
    return [category for _, category, _ in _texts(seed, 'jobs', 'J', n)]


def admission_cases(seed: int, n: int) -> list:
    """n labeled cases {text, op, gold} from the 'admission' stream, labeled by oracle.gold."""
    return [{'text': text, 'op': op, 'gold': oracle.gold(op, text)} for op, _, text in _texts(seed, 'admission', 'A', n)]
