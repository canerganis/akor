"""Gold oracle for the replication operations in ops.md (tensile test records). Standard library, Decimal only.

gold(op, text) returns the exact output string. Records outside the grammar of ops.md raise ValueError; they are
not part of the study.
"""
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP, localcontext
import re

OPS = ('verdict', 'margin', 'elong', 'temp_class')

GRADES = {'S235': (Decimal('235'), Decimal('360')), 'S275': (Decimal('275'), Decimal('410')),
          'S355': (Decimal('355'), Decimal('470')), 'S460': (Decimal('460'), Decimal('540')),
          'A36': (Decimal('250'), Decimal('400'))}
UNITS = {'yield': ('MPa', 'N/mm2'), 'uts': ('MPa', 'N/mm2'), 'gauge': ('mm',), 'final': ('mm',),
         'temp': ('C', 'degC')}
NUMERAL = re.compile(r'^-?(0|[1-9][0-9]*)(\.[0-9]+)?$')
KEY = re.compile(r'^[a-z_][a-z_0-9]*$')


def strip_terminator(text):
    if text.endswith('\r\n'):
        return text[:-2]
    if text.endswith('\n'):
        return text[:-1]
    return text


def parse(text):
    """{key: raw value} of one record text (after removing one terminal line terminator)."""
    out = {}
    for seg in strip_terminator(text).split('; '):
        if seg.count('=') != 1:
            raise ValueError('malformed segment ' + repr(seg))
        k, v = seg.split('=')
        if not KEY.match(k) or not v or k in out or '\r' in v or '\n' in v:
            raise ValueError('malformed segment ' + repr(seg))
        out[k] = v
    return out


def quantity(rec, key):
    """Decimal value of a unit-carrying field, or None when the value is 'unknown'."""
    if key not in rec:
        raise ValueError('missing field ' + key)
    v = rec[key]
    if v == 'unknown':
        return None
    parts = v.split(' ')
    if len(parts) != 2 or parts[1] not in UNITS[key] or not NUMERAL.match(parts[0]):
        raise ValueError(f'bad {key} value {v!r}')
    return Decimal(parts[0])


def _nonneg_zero(x):
    return Decimal(0) if x == 0 else x


def verdict(rec):
    if 'grade' not in rec:
        raise ValueError('missing field grade')
    y, u = quantity(rec, 'yield'), quantity(rec, 'uts')
    if rec['grade'] not in GRADES or y is None or u is None:
        return 'unknown'
    min_y, min_u = GRADES[rec['grade']]
    return 'pass' if y >= min_y and u >= min_u else 'fail'


def margin(rec):
    y, u = quantity(rec, 'yield'), quantity(rec, 'uts')
    if y is None or u is None:
        return 'unknown'
    q = _nonneg_zero((u - y).quantize(Decimal('1'), rounding=ROUND_HALF_EVEN))
    return f'{q:f} MPa'


def elong(rec):
    g, f = quantity(rec, 'gauge'), quantity(rec, 'final')
    if g is None or f is None:
        return 'unknown'
    with localcontext() as ctx:
        ctx.prec = 60
        ratio = (f - g) / g * Decimal(100)
        q = _nonneg_zero(ratio.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))
    return f'{q:.1f} %'


def temp_class(rec):
    t = quantity(rec, 'temp')
    if t is None:
        return 'unknown'
    if t < Decimal('10'):
        return 'cold'
    if t <= Decimal('35'):
        return 'room'
    return 'hot'


FUNCS = {'verdict': verdict, 'margin': margin, 'elong': elong, 'temp_class': temp_class}


def gold(op: str, text: str) -> str:
    if op not in FUNCS:
        raise ValueError('unknown op ' + repr(op))
    return FUNCS[op](parse(text))
