"""oz-rule/1: a small deterministic expression language that computes one complete job result.

Normative spec: docs/design/ozmap-2026-10-24/oz-rule-1-spec.md. Standard library only, no model calls.

Public API
    validate(ast_bytes)               -> (ok, reason)
    evaluate(ast_bytes, text)         -> {"status":"value",...} or {"status":"abstain","reason":...}; never raises
    admit(ast_bytes, resolved_package) -> admission response dict; never raises (package: oz_registry.resolve)
    label_ok(expected) / canonical_decimal_label(s) -> typed label validation, independent of input numeral limits
    canonical_value_text(result)      -> compact JSON text of a value result (None for an abstain)

Where the spec is ambiguous the stricter reading is taken. Each such place is marked "READING" below.
"""
import decimal
import hashlib
import json
import re

MAX_AST_BYTES = 2048
MAX_DEPTH = 16
MAX_NODES = 128
MAX_INPUT_BYTES = 8192
MAX_STRING_BYTES = 8192
MAX_LIST = 64
MAX_RESULT_BYTES = 4096
MAX_STEPS = 32768
MAX_TABLE = 32
MAX_DIGITS = 38
MAX_SCALE = 12
LANG = 'oz-rule/1'
CASES = 64
REPRESENTATIVE = 48
CHALLENGE = 16
MIN_COVERAGE = 32

STRING, DECIMAL, BOOL, LIST = 'string', 'decimal', 'bool', 'list'
_ALL = frozenset((STRING, DECIMAL, BOOL, LIST))
_SCALARS = frozenset((STRING, DECIMAL, BOOL))

_NUMERAL = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?')  # READING: a decimal point must be followed by a digit
_KEY = re.compile(r'[a-z_][a-z0-9_]*')
_BOM = b'\xef\xbb\xbf'

# Local context for exact arithmetic: precision far above 2 * 38 digits, every rounding signal trapped.
_EXACT = decimal.Context(
    prec=120, rounding=decimal.ROUND_HALF_EVEN, Emin=-999, Emax=999, capitals=1, clamp=0,
    traps=[decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow, decimal.Underflow,
           decimal.Inexact, decimal.Rounded, decimal.Subnormal, decimal.Clamped])
# fmt rounds on purpose, so Inexact and Rounded are not trapped there.
_ROUND = decimal.Context(
    prec=120, rounding=decimal.ROUND_HALF_EVEN, Emin=-999, Emax=999, capitals=1, clamp=0,
    traps=[decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow, decimal.Underflow])

_ARITY = {'s': 1, 'd': 1, 'bool': 1, 'input': 0, 'field': 1, 'split': 2, 'at': 2, 'num': 2, 'add': 2,
          'sub': 2, 'fmt': 3, 'eq': 2, 'le': 2, 'if': 3, 'require': 2, 'lookup': 2}
_VARIADIC = ('list', 'cat')


class _Invalid(Exception):
    pass


class _Abstain(Exception):
    def __init__(self, reason):
        Exception.__init__(self, reason)
        self.reason = reason


# ---------------------------------------------------------------------------------------------- parsing

def _no_constant(name):
    raise _Invalid('json constant')


def _no_float(text):
    raise _Invalid('non-integer number')  # the language has no JSON floats; index and places are integers


def _pairs(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise _Invalid('duplicate key')
        _text_ok(key)
        seen[key] = value
    return seen


def _text_ok(s):
    try:
        s.encode('utf-8')
    except UnicodeEncodeError:
        raise _Invalid('unpaired surrogate')


def _walk(v):
    if isinstance(v, str):
        _text_ok(v)
    elif isinstance(v, list):
        for item in v:
            _walk(item)
    elif isinstance(v, dict):
        for item in v.values():
            _walk(item)


def _sb(s):
    return len(s.encode('utf-8'))


def _numeral(s):
    """Decimal for an exact input numeral, or None."""
    if not _NUMERAL.fullmatch(s):
        return None
    digits = s.lstrip('-')
    whole, _, frac = digits.partition('.')
    if len(whole) + len(frac) > MAX_DIGITS or len(frac) > MAX_SCALE:
        return None
    return _canon(decimal.Decimal(s))


def _canon(d):
    """Normalized value with no negative zero."""
    if d == 0:
        return decimal.Decimal(0)
    return d.normalize(_EXACT)


def _in_range(d):
    """True when a canonical decimal has at most 38 coefficient digits and a scale of at most 12 (amendment 1 D4).

    d is already normalized: coefficient trailing zeros are stripped into the exponent and zero is coefficient 0,
    exponent 0. Input numeral limits (digits in the lexeme) are separate and live in _numeral.
    """
    digits, exp = d.as_tuple()[1:]
    return len(digits) <= MAX_DIGITS and max(0, -exp) <= MAX_SCALE


def _decimal_text(d):
    return '0' if d == 0 else format(d, 'f')


def _node(n, depth, st):
    """Validate one node; returns (tree, set of possible types)."""
    if depth > MAX_DEPTH:
        raise _Invalid('depth')
    if type(n) is not list or not n or type(n[0]) is not str:
        raise _Invalid('node shape')
    st[0] += 1
    if st[0] > MAX_NODES:
        raise _Invalid('node count')
    tag = n[0]
    args = n[1:]
    if tag in _ARITY:
        if len(args) != _ARITY[tag]:
            raise _Invalid('arity')
    elif tag not in _VARIADIC:
        raise _Invalid('unknown node')

    def child(x):
        return _node(x, depth + 1, st)

    def need(ts, allowed):
        if not ts <= allowed:
            raise _Invalid('operand type')

    def lit_str(x):
        if type(x) is not str:
            raise _Invalid('parameter type')
        return x

    def lit_int(x):
        if type(x) is not int:  # bool is not an int here
            raise _Invalid('parameter type')
        return x

    if tag == 's':
        return ('s', lit_str(args[0])), frozenset((STRING,))
    if tag == 'd':
        # READING: a malformed decimal literal is an invalid AST, not a runtime abstain.
        value = _numeral(lit_str(args[0]))
        if value is None:
            raise _Invalid('decimal literal')
        return ('d', value, _sb(args[0])), frozenset((DECIMAL,))
    if tag == 'bool':
        if type(args[0]) is not bool:
            raise _Invalid('parameter type')
        return ('bool', args[0]), frozenset((BOOL,))
    if tag == 'input':
        return ('input',), frozenset((STRING,))
    if tag == 'field':
        # D5: any literal string. Record key grammar applies to input records only, so an odd key yields "missing".
        return ('field', lit_str(args[0])), frozenset((STRING,))
    if tag == 'split':
        x, ts = child(args[0])
        need(ts, frozenset((STRING,)))
        sep = lit_str(args[1])
        if not sep:
            raise _Invalid('empty separator')
        return ('split', x, sep), frozenset((LIST,))
    if tag == 'at':
        x, ts = child(args[0])
        need(ts, frozenset((LIST,)))
        index = lit_int(args[1])
        if index < 0:
            raise _Invalid('negative index')
        return ('at', x, index), frozenset((STRING,))
    if tag == 'num':
        x, ts = child(args[0])
        need(ts, frozenset((STRING,)))
        return ('num', x, lit_str(args[1])), frozenset((DECIMAL,))
    if tag in ('add', 'sub'):
        a, ta = child(args[0])
        b, tb = child(args[1])
        need(ta, frozenset((DECIMAL,)))
        need(tb, frozenset((DECIMAL,)))
        return (tag, a, b), frozenset((DECIMAL,))
    if tag == 'fmt':
        x, ts = child(args[0])
        need(ts, frozenset((DECIMAL,)))
        places = lit_int(args[1])
        if not 0 <= places <= MAX_SCALE:
            raise _Invalid('places')
        return ('fmt', x, places, lit_str(args[2])), frozenset((STRING,))
    if tag == 'eq':
        a, ta = child(args[0])
        b, tb = child(args[1])
        # READING: "matching scalar types" means both operands have the same single scalar type on every path.
        if len(ta) != 1 or ta != tb or not ta <= _SCALARS:
            raise _Invalid('operand type')
        return ('eq', a, b), frozenset((BOOL,))
    if tag == 'le':
        a, ta = child(args[0])
        b, tb = child(args[1])
        need(ta, frozenset((DECIMAL,)))
        need(tb, frozenset((DECIMAL,)))
        return ('le', a, b), frozenset((BOOL,))
    if tag == 'if':
        c, tc = child(args[0])
        need(tc, frozenset((BOOL,)))
        a, ta = child(args[1])
        b, tb = child(args[2])
        return ('if', c, a, b), ta | tb
    if tag == 'require':
        c, tc = child(args[0])
        need(tc, frozenset((BOOL,)))
        x, tx = child(args[1])
        return ('require', c, x), tx
    if tag == 'lookup':
        x, ts = child(args[0])
        need(ts, frozenset((STRING,)))
        table = args[1]
        if type(table) is not list or len(table) > MAX_TABLE:
            raise _Invalid('lookup table')
        mapping = {}
        for pair in table:
            if type(pair) is not list or len(pair) != 2 or type(pair[0]) is not str or type(pair[1]) is not str:
                raise _Invalid('lookup table')
            if pair[0] in mapping:
                raise _Invalid('duplicate lookup key')
            mapping[pair[0]] = pair[1]
        size = sum(_sb(k) + _sb(v) for k, v in mapping.items())
        return ('lookup', x, mapping, size), frozenset((STRING,))
    if tag == 'list':
        items = []
        for a in args:
            x, ts = child(a)
            need(ts, frozenset((STRING,)))
            items.append(x)
        return ('list',) + tuple(items), frozenset((LIST,))
    # cat
    items = []
    for a in args:
        x, ts = child(a)
        need(ts, frozenset((LIST,)))
        items.append(x)
    return ('cat',) + tuple(items), frozenset((LIST,))


def _parse(ast_bytes):
    if not isinstance(ast_bytes, (bytes, bytearray)):
        raise _Invalid('not bytes')
    raw = bytes(ast_bytes)
    if len(raw) > MAX_AST_BYTES:
        raise _Invalid('size')
    if raw.startswith(_BOM):
        raise _Invalid('bom')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise _Invalid('utf-8')
    try:
        doc = json.loads(text, object_pairs_hook=_pairs, parse_float=_no_float, parse_constant=_no_constant)
        _walk(doc)
    except _Invalid:
        raise
    except Exception:  # JSONDecodeError (including trailing content), RecursionError, int limits
        raise _Invalid('json')
    if type(doc) is not dict or set(doc) != {'lang', 'expr'} or doc['lang'] != LANG:
        raise _Invalid('envelope')
    tree, _ = _node(doc['expr'], 1, [0])
    return tree


def validate(ast_bytes):
    """(True, "") for a valid AST, else (False, short reason). Never raises."""
    try:
        _parse(ast_bytes)
        return True, ''
    except _Invalid as exc:
        return False, str(exc)
    except Exception:
        return False, 'internal'


# ------------------------------------------------------------------------------------------- evaluation

class _Run:
    """One evaluation. Step accounting is oz-rule/1 amendment 1 D3:

    one step on node entry; literal strings when reached; every successful child's string or list bytes when it
    returns to its parent (arg); the node's own string or list result again before it returns (own); the complete
    input before input/field access; every lookup table string before matching; the final serialization. A failure
    propagates at once and keeps only the charges made before it.
    """

    def __init__(self, text, text_bytes):
        self.text = text
        self.text_bytes = text_bytes
        self.steps = 0
        self._record = None

    def charge(self, n):
        self.steps += n
        if self.steps > MAX_STEPS:
            self.steps = MAX_STEPS
            raise _Abstain('limit')

    def own(self, typ, val):
        """Check and charge a node's own result (string or list bytes), then return it."""
        if typ == STRING:
            n = _sb(val)
            if n > MAX_STRING_BYTES:
                raise _Abstain('limit')
            self.charge(n)
        elif typ == LIST:
            if len(val) > MAX_LIST:
                raise _Abstain('limit')
            self.charge(sum(_sb(s) for s in val))
        return typ, val

    def record(self):
        if self._record is None:
            self._record = self._parse_record()
        if isinstance(self._record, str):
            raise _Abstain(self._record)
        return self._record

    def _parse_record(self):
        # READING: a malformed record or duplicate key abstains with reason "input".
        rec = {}
        for segment in self.text.split('; '):
            if segment.count('=') != 1:
                return 'input'
            key, value = segment.split('=')
            if not _KEY.fullmatch(key) or not value or ';' in value or '\r' in value or '\n' in value:
                return 'input'
            if key in rec:
                return 'input'
            rec[key] = value
        return rec

    def arg(self, t, kind=None):
        """Evaluate a child; its string or list bytes are charged as an operand of the parent."""
        typ, val = self.ev(t)
        if typ == STRING:
            self.charge(_sb(val))
        elif typ == LIST:
            self.charge(sum(_sb(s) for s in val))
        if kind is not None and typ != kind:
            raise _Abstain('type')
        return typ, val

    def get(self, t, kind):
        return self.arg(t, kind)[1]

    def ev(self, t):
        self.charge(1)  # node entry
        tag = t[0]
        if tag == 's':
            self.charge(_sb(t[1]))
            return self.own(STRING, t[1])
        if tag == 'd':
            self.charge(t[2])  # the literal's own bytes; a decimal result has no string bytes
            return DECIMAL, t[1]
        if tag == 'bool':
            return BOOL, t[1]
        if tag == 'input':
            self.charge(self.text_bytes)
            return self.own(STRING, self.text)
        if tag == 'field':
            self.charge(_sb(t[1]))
            self.charge(self.text_bytes)
            rec = self.record()  # the whole record is parsed and validated before the key is looked up
            if t[1] not in rec:
                raise _Abstain('missing')
            return self.own(STRING, rec[t[1]])
        if tag == 'split':
            x = self.get(t[1], STRING)
            self.charge(_sb(t[2]))
            return self.own(LIST, x.split(t[2], MAX_LIST))
        if tag == 'at':
            x = self.get(t[1], LIST)
            if t[2] >= len(x):
                raise _Abstain('index')
            return self.own(STRING, x[t[2]])
        if tag == 'num':
            x = self.get(t[1], STRING)
            self.charge(_sb(t[2]))
            if t[2]:
                suffix = ' ' + t[2]
                if not x.endswith(suffix):
                    raise _Abstain('unit')
                x = x[:-len(suffix)]
            value = _numeral(x)
            if value is None:
                raise _Abstain('number')
            return DECIMAL, value
        if tag in ('add', 'sub'):
            a = self.get(t[1], DECIMAL)
            b = self.get(t[2], DECIMAL)
            with decimal.localcontext(_EXACT):
                r = _canon(a + b if tag == 'add' else a - b)
            if not _in_range(r):
                raise _Abstain('number')
            return DECIMAL, r
        if tag == 'fmt':
            x = self.get(t[1], DECIMAL)
            self.charge(_sb(t[3]))
            with decimal.localcontext(_ROUND):
                q = x.quantize(decimal.Decimal((0, (1,), -t[2])))
            s = format(q, 'f')
            if s.startswith('-') and not s.strip('-0.'):
                s = s[1:]  # no negative zero
            if t[3]:
                s += ' ' + t[3]
            return self.own(STRING, s)
        if tag == 'eq':
            ta, a = self.arg(t[1])
            tb, b = self.arg(t[2])
            if ta != tb or ta == LIST:
                raise _Abstain('type')
            return BOOL, a == b
        if tag == 'le':
            a = self.get(t[1], DECIMAL)
            b = self.get(t[2], DECIMAL)
            with decimal.localcontext(_EXACT):
                return BOOL, a <= b
        if tag == 'if':
            c = self.get(t[1], BOOL)
            typ, val = self.arg(t[2] if c else t[3])
            return self.own(typ, val)
        if tag == 'require':
            c = self.get(t[1], BOOL)
            if not c:
                raise _Abstain('guard')
            typ, val = self.arg(t[2])
            return self.own(typ, val)
        if tag == 'lookup':
            x = self.get(t[1], STRING)
            self.charge(t[3])  # every table string, before matching
            if x not in t[2]:
                raise _Abstain('lookup')
            return self.own(STRING, t[2][x])
        if tag == 'list':
            items = [self.get(c, STRING) for c in t[1:]]
            return self.own(LIST, items)
        if tag == 'cat':
            parts = [self.get(c, LIST) for c in t[1:]]
            return self.own(LIST, [s for p in parts for s in p])
        raise _Abstain('internal')


def _abstain(reason, steps):
    return {'status': 'abstain', 'reason': reason, 'steps': steps}


def _dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def evaluate(ast_bytes, text):
    """Run one AST on one input string. Always returns a dict and never raises."""
    run = None
    try:
        try:
            tree = _parse(ast_bytes)
        except _Invalid:
            return _abstain('invalid_ast', 0)
        if type(text) is not str:
            return _abstain('input', 0)
        try:
            n = len(text.encode('utf-8'))
        except UnicodeEncodeError:
            return _abstain('input', 0)
        if n > MAX_INPUT_BYTES:
            return _abstain('input', 0)
        run = _Run(text, n)
        try:
            typ, val = run.ev(tree)
            if typ == DECIMAL:
                val = _decimal_text(val)
            elif typ == LIST:
                val = list(val)
            # READING: result size counts the serialized JSON value, quotes and brackets included.
            body = _dumps(val)
            size = len(body.encode('utf-8'))
            run.charge(size)
            if size > MAX_RESULT_BYTES:
                raise _Abstain('limit')
            return {'status': 'value', 'type': typ, 'value': val, 'steps': run.steps}
        except _Abstain as a:
            return _abstain(a.reason, run.steps)
    except Exception:
        return _abstain('internal', run.steps if run is not None else 0)


def canonical_value_text(result):
    """Compact JSON text of a value result, as OZ/1g values are written. None for an abstain."""
    if not isinstance(result, dict) or result.get('status') != 'value':
        return None
    return _dumps(result['value'])


# --------------------------------------------------------------------------------------------- admission

def canonical_decimal_label(s):
    """True for a canonical decimal label: numeral grammar, no exponent, no insignificant zeros, no negative zero,
    at most 38 coefficient digits and scale 12. Judged on the result rule (D4), not on input numeral limits, so a
    value such as 10**38 (39 plain digits) is a valid label."""
    try:
        if type(s) is not str or len(s) > 100 or not _NUMERAL.fullmatch(s):
            return False
        d = _canon(decimal.Decimal(s))
        return _decimal_text(d) == s and _in_range(d)
    except (decimal.DecimalException, ValueError, ArithmeticError):
        return False


def label_ok(e):
    """True when e is a typed label: {"type": ..., "value": ...}. Decimal labels are canonical decimal strings (D9)."""
    if not isinstance(e, dict) or set(e) != {'type', 'value'}:
        return False
    t, v = e['type'], e['value']
    if t == STRING:
        return type(v) is str
    if t == DECIMAL:
        return canonical_decimal_label(v)
    if t == BOOL:
        return type(v) is bool
    if t == LIST:
        return type(v) is list and all(type(s) is str for s in v)
    return False


def _reject(resp, reason):
    resp['reasons'].append(reason)
    return resp


def admit(ast_bytes, resolved_package):
    """Screen one candidate AST against a registry-resolved package of 64 labeled cases (amendment 1 D6).

    resolved_package must be an oz_registry.ResolvedPackage issued by Registry.resolve. There are no caller callbacks
    and no eligibility flags: checks come from the package's pinned registry definitions, eligibility was derived by
    the resolver, and every hash is recomputed again here, all before the first case is evaluated. Returns the
    admission response; never raises.

    Per case the response keeps the complete typed result (`result`), the checks' outcomes (`checks`, one verdict per
    pinned consumer check, pass/fail/inconclusive), and the derived label_match, check_ok and error.
    """
    resp = {'status': 'rejected', 'reasons': [], 'operation_id': None, 'ast_hash': None, 'bindings': {},
            'coverage': 0, 'covered_errors': 0, 'cases': [], 'deferred_checks': []}
    try:
        import oz_registry
        canon = oz_registry.canonical
        if isinstance(ast_bytes, (bytes, bytearray)):
            resp['ast_hash'] = hashlib.sha256(bytes(ast_bytes)).hexdigest()
        pkg = resolved_package
        if not isinstance(pkg, oz_registry.ResolvedPackage):
            return _reject(resp, 'invalid_package:unresolved')
        resp['operation_id'] = pkg.operation_id
        resp['bindings'] = pkg.bindings
        try:
            pkg.verify()
            resp['deferred_checks'] = pkg.deferred_checks()
        except oz_registry.RegistryError as exc:
            return _reject(resp, 'invalid_package:' + exc.code)
        ok, why = validate(ast_bytes)
        if not ok:
            return _reject(resp, 'invalid_ast:' + why)
        coverage = errors = 0
        for case in pkg.cases:
            text = pkg.resolved_text(case)
            result = evaluate(ast_bytes, text)
            out = {'id': case['id'], 'partition': case['partition'],
                   'input_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'result': result,
                   'status': result['status'], 'steps': result['steps'], 'checks': []}
            if result['status'] == 'abstain':
                out.update(reason=result['reason'], label_match=None, check_ok=None, error=False)
            else:
                coverage += 1
                expected = case['expected']
                match = (result['type'] == expected['type']
                         and canon(result['value']) == canon(expected['value']))
                outcomes = pkg.run_checks(canonical_value_text(result), text)
                passed = all(o['verdict'] == 'pass' for o in outcomes)
                error = not (match and passed)
                errors += error
                out.update(checks=outcomes, label_match=match, check_ok=passed, error=error)
            resp['cases'].append(out)
        resp['coverage'] = coverage
        resp['covered_errors'] = errors
        if errors:
            resp['reasons'].append('covered_errors')
        if coverage < MIN_COVERAGE:
            resp['reasons'].append('coverage')
        if not resp['reasons']:
            resp['status'] = 'accepted'
        return resp
    except Exception:
        return {'status': 'rejected', 'reasons': ['internal'], 'operation_id': resp['operation_id'],
                'ast_hash': resp['ast_hash'], 'bindings': resp['bindings'], 'coverage': 0, 'covered_errors': 0,
                'cases': [], 'deferred_checks': []}
