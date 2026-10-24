"""Independent gold oracle for the oz map kill pilot (joint record 3, amendment 1 D6 label provenance).

Written from the op texts only: MAT_GOAL and MAT_D in bench/live/live2.py (quoted below) and the BoolQ op text in
data.py. It never imports oz_rule, oz_registry, oz_host or any rule AST, so its labels are independent of the rule
language and of every candidate rule. Standard library only.

    MAT_GOAL  acceptance interval [12.48,12.52] mm, inclusive; inclusion is arithmetic only.
    e  compact JSON array of strings: length, uncertainty, n, method, basis, physical_validation, in that order,
       field values preserved exactly.
    b  [length-uncertainty, length+uncertainty], each a string with two decimal places and unit mm; "unknown" when the
       uncertainty is unknown.
    m  JSON array of the field names whose values are unknown, in the order uncertainty, method, basis.
    v  "inside" when the whole length +/- uncertainty interval lies within the acceptance interval, "outside"
       otherwise, "unknown" when the uncertainty is unknown.

Records the op texts leave undefined raise Undefined: a duplicate or missing field, a value that is not a plain
non-negative decimal followed by " mm", a two-decimal rounding tie (the op text names no rounding rule), or an unknown
length. The data generator never emits such records for evaluation or admission, and the tests check that.

The label of a job is gold(op, text); typed(op, value) gives the oz-rule/1 typed label form used by the registry.
"""
from decimal import Decimal, ROUND_HALF_UP
import re

LOW, HIGH = Decimal('12.48'), Decimal('12.52')
E_ORDER = ('length', 'uncertainty', 'n', 'method', 'basis', 'physical_validation')
M_ORDER = ('uncertainty', 'method', 'basis')
MATERIALS_OPS = ('e', 'b', 'm', 'v')
BOOLQ_OP = 'boolq'
UNKNOWN = 'unknown'
_QTY = re.compile(r'(\d+(?:\.\d+)?) mm\Z')


class Undefined(ValueError):
    """The op text does not define an answer for this record."""


def resolve(text):
    """Remove exactly one terminal CRLF, otherwise one terminal LF (the pilot's input policy), and nothing else."""
    if text.endswith('\r\n'):
        return text[:-2]
    if text.endswith('\n'):
        return text[:-1]
    return text


def fields(text):
    """{name: value} of a record 'name=value; name=value; ...' (separator exactly '; ')."""
    out = {}
    for part in resolve(text).split('; '):
        name, eq, value = part.partition('=')
        if not eq or not name or name in out:
            raise Undefined('malformed or duplicate field: ' + part[:40])
        out[name] = value
    return out


def quantity(value):
    m = _QTY.match(value)
    if not m:
        raise Undefined('not a plain mm quantity: ' + value[:40])
    return Decimal(m.group(1))


def two_places(x):
    """x as a string with exactly two decimal places plus ' mm'. A tie at the third decimal is undefined."""
    scaled = x * 100
    if scaled - scaled.to_integral_value(rounding='ROUND_FLOOR') == Decimal('0.5'):
        raise Undefined('rounding tie at two decimals: ' + str(x))
    return str(x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)) + ' mm'


def _need(f, *names):
    for n in names:
        if n not in f:
            raise Undefined('missing field ' + n)


def gold(op, text, answer=None):
    """The gold value of one job. BoolQ takes the dataset's own label (answer, a bool)."""
    if op == BOOLQ_OP:
        if type(answer) is not bool:
            raise Undefined('BoolQ needs its dataset label')
        return 'yes' if answer else 'no'
    f = fields(text)
    if op == 'e':
        _need(f, *E_ORDER)
        return [f[k] for k in E_ORDER]
    if op == 'm':
        _need(f, *M_ORDER)
        return [k for k in M_ORDER if f[k] == UNKNOWN]
    if op in ('b', 'v'):
        _need(f, 'length', 'uncertainty')
        if f['length'] == UNKNOWN:
            raise Undefined('unknown length')
        if f['uncertainty'] == UNKNOWN:
            return UNKNOWN
        length, unc = quantity(f['length']), quantity(f['uncertainty'])
        lo, hi = length - unc, length + unc
        if op == 'b':
            return [two_places(lo), two_places(hi)]
        return 'inside' if LOW <= lo and hi <= HIGH else 'outside'
    raise Undefined('unknown operation ' + str(op))


def typed(op, value):
    """The typed label {"type", "value"} for a gold value (strings and lists of strings only)."""
    if isinstance(value, str):
        return {'type': 'string', 'value': value}
    if isinstance(value, list) and all(isinstance(s, str) for s in value):
        return {'type': 'list', 'value': list(value)}
    raise Undefined('no typed label for ' + repr(value)[:40])


def label(op, text, answer=None):
    return typed(op, gold(op, text, answer))


def matches(value, gold_value):
    """Gold comparison of a decoded answer value: exact JSON equality (strings stay strings, order matters)."""
    return type(value) is type(gold_value) and value == gold_value
