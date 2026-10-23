"""Code-review pilot oracle (codereview-v1, codereview-witness-v1). Evaluator-only; standard library only.

Rules: docs/design/codereview-pilot-2026-10-24/02 section 4 as amended by 03, and WITNESS_FORMAT.md of the fixture
(Astra revision 1, with its seed span rule). It imports no executor code (no oz*.py, no workflow.py, no
sandbox_worker.py, nothing under bench/live). It reads the frozen answer key and the shipped and reference modules from
evaluator-only storage, and runs witnesses in its own worker (eval_worker.py) under the O1 launcher and Job Object
(bench/o1/sandbox.py, imported unchanged and pinned by its LF-normalized SHA-256). No model scores anything.

    score(answer_text, pack, root=FIX, fixes=None)   a run's final answer against its own pack's seeds
    judge_witness(witness, shipped_source, reference_source)
    validate_finding(obj, file, line_count)
    edits_inside_span(shipped, reference, start, end), in_span(line, span)

Categories of one finding (frozen):
  invalid     the record or its witness breaks the codereview-witness-v1 schema
  out_of_domain  the witness's call leaves its function's documented input domain (DOMAINS) without exercising a
              documented rejection rule through an exception expectation; never executed
  seeded      proven (the reference expectation matches; the shipped call completes, by return or target-call
              exception, without matching), the class is a seed's class and the line lies in that seed's span
  mislocated  proven, but no seed of the file has that class and a span holding that line
  unseeded    the witness runs cleanly and fails on both shipped and reference code, and it passes on a registered fix
              of that file (fixes={file: source}, a fix supplied by a person or Astra after review, never by a model
              under test): a real unseeded defect, reported apart, neither correct nor a false positive
  unproven    anything else: both match, the reference does not match, a timeout or any execution error. A witness
              failing on both sides without a registered fix stays unproven and is listed under review_both_fail.
Per file: a defective file is correct when its proven findings (seeded plus mislocated) map exactly onto its seed set
(no mislocated finding, every seed hit; duplicates of one seed are one seed). A clean control is correct when its
response, without unseeded findings, is exactly []. Totals reported separately: recall (seeds hit / seeds), false
positives (findings neither seeded nor unseeded), unproven (findings without a proven differential, invalid ones
included), unseeded, review_both_fail. A response that is not one strict JSON object keyed by exactly the pack's three
module paths makes every file of the run incorrect.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
import keyword
import math
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIX = HERE / 'fixtures' / 'codereview-v1'
O1 = ROOT / 'bench' / 'o1'
EVAL_WORKER = HERE / 'eval_worker.py'
SANDBOX_FILE = O1 / 'sandbox.py'
SANDBOX_SHA256 = '579417ae66558f87f08a41fde0d3deb0f65fffe92a3767e37a31265c2138ce86'   # LF-normalized bytes
ORACLE_VERSION = 'codereview-oracle/1'
CLASSES = ('off_by_one', 'missing_guard')
EXCEPTIONS = ('ValueError', 'TypeError', 'IndexError', 'KeyError', 'ZeroDivisionError', 'OverflowError')
FINDING_KEYS = {'file', 'line', 'class', 'witness'}
WITNESS_KEYS = {'function', 'args', 'kwargs', 'expected'}
_SANDBOX = None
_CACHE: dict = {}
MISSING = object()


class EvaluatorUnavailable(Exception):
    """The sandbox could not be created or confined: nothing is decided and the run's scoring is blocked."""


def norm_sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def sandbox():
    """bench/o1/sandbox.py (the launcher and Job Object only), after checking its byte pin."""
    global _SANDBOX
    if _SANDBOX is None:
        if norm_sha(SANDBOX_FILE) != SANDBOX_SHA256:
            raise EvaluatorUnavailable('bench/o1/sandbox.py differs from its pinned bytes')
        if str(O1) not in sys.path:
            sys.path.append(str(O1))
        import sandbox as launcher  # noqa: E402  the launcher only; every outcome is decided here
        _SANDBOX = launcher
    return _SANDBOX


def load_key(root=FIX) -> dict:
    return json.loads((Path(root) / 'answer_key.json').read_text(encoding='utf-8'))


def modules(pack: str, root=FIX) -> list:
    """The answer key's module entries of one pack ('A' or 'B'), in key order."""
    if pack not in ('A', 'B'):
        raise ValueError('pack must be A or B')
    return [m for m in load_key(root)['modules'] if m['file'].startswith(f'pack{pack}/')]


def source(rel: str, root=FIX) -> str:
    return (Path(root) / rel).read_bytes().decode('utf-8')


def line_count(text: str) -> int:
    return text.count('\n') + (0 if text.endswith('\n') or not text else 1)


# ---- the seed span rule (WITNESS_FORMAT.md, Astra revision 1) ----

def in_span(line: int, span: dict) -> bool:
    """A finding must name an existing shipped line within the inclusive span; bordering an allowed insertion
    boundary does not widen it."""
    return span['start_line'] <= line <= span['end_line']


def edits_inside_span(shipped: str, reference: str, start: int, end: int) -> tuple:
    """(inside, description): every reference edit against the shipped file obeys the seed span rule. Replacements and
    deletions may affect only shipped lines start..end. An insertion after k shipped lines is inside exactly when
    start - 1 <= k <= end; every line of an inserted block shares that boundary. A file without edits is not inside."""
    a, b = shipped.split('\n'), reference.split('\n')
    parts, inside = [], True
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        if tag == 'insert':
            ok = start - 1 <= i1 <= end
            parts.append('insert %d line(s) after %d shipped lines' % (j2 - j1, i1))
        else:
            ok = start <= i1 + 1 and i2 <= end
            parts.append('%s shipped lines %d-%d' % (tag, i1 + 1, i2))
        inside = inside and ok
    return inside and bool(parts), '; '.join(parts) or 'no difference'


# ---- strict JSON and schema ----

def strict_json(text: str):
    """json.loads with duplicate keys, NaN, Infinity and non-finite decoded numbers refused."""
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError('duplicate key ' + k)
            out[k] = v
        return out

    def constant(name):
        raise ValueError('non-finite constant ' + name)
    value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    _finite(value, 0)
    return value


def _finite(value, depth):
    if depth > 200:
        raise ValueError('nesting too deep')
    if type(value) is float and not math.isfinite(value):
        raise ValueError('non-finite number')
    if type(value) is list:
        for v in value:
            _finite(v, depth + 1)
    elif type(value) is dict:
        for v in value.values():
            _finite(v, depth + 1)


def _identifier(name) -> bool:
    return type(name) is str and name.isidentifier() and not keyword.iskeyword(name) and not name.startswith('_')


def validate_witness(w) -> list:
    if type(w) is not dict or set(w) != WITNESS_KEYS:
        return ['witness must have exactly function, args, kwargs, expected']
    problems = []
    if not _identifier(w['function']):
        problems.append('function must be a public identifier without dots')
    if type(w['args']) is not list:
        problems.append('args must be an array')
    if type(w['kwargs']) is not dict or any(not _identifier(k) for k in w['kwargs']):
        problems.append('kwargs must be an object with public identifier keys')
    e = w['expected']
    if type(e) is not dict or len(e) != 1 or set(e) - {'return', 'exception'}:
        problems.append('expected must have exactly one of return, exception')
    elif 'exception' in e and e['exception'] not in EXCEPTIONS:
        problems.append('exception must be one of ' + ', '.join(EXCEPTIONS))
    return problems


def validate_finding(obj, file: str, lines: int) -> list:
    """[] when obj is one codereview-witness-v1 finding record for file (lines physical lines), else the problems."""
    if type(obj) is not dict or set(obj) != FINDING_KEYS:
        return ['a finding has exactly file, line, class, witness']
    problems = []
    if obj['file'] != file:
        problems.append('file must be the module path ' + file)
    if type(obj['line']) is not int or not 1 <= obj['line'] <= lines:
        problems.append('line must be an integer 1..%d' % lines)
    if obj['class'] not in CLASSES:
        problems.append('class must be off_by_one or missing_guard')
    return problems + validate_witness(obj['witness'])


# ---- documented input domains (WITNESS_FORMAT.md: inputs must meet each module's documented domain, except when
# exercising an explicitly documented rejection rule) ----
#
# DOMAIN_STATUS is 'provisional' until Astra answers the open questions in plan-frozen.md (fix 3 of the review): the
# rules below are the strict reading of each module's docstrings. A parameter rule is (type, precondition); a
# precondition marked 'reject' is an explicitly documented rejection rule and may be violated only by a witness that
# expects an exception (sample_stats states ValueError; page_label's "reject" states no exception type).
DOMAIN_STATUS = 'provisional'
DOMAIN_QUESTIONS = (
    'Q1 Value preconditions written as "must be positive/nonnegative", "invalid", "distinct" or "start <= end" '
    '(paging sizes, counts and page numbers; sample_stats.latest limit; ranges shape and order; rotation_order round; '
    'assign_tasks workers; chunk_tasks size; render_settings keys and values): domain limits that a witness must '
    'satisfy, or documented rejection rules a witness may violate with an exception expectation, and which exception?',
    'Q2 paging.page_label "reject pages absent from the result set": which exception?',
    'Q3 labels.make_header "one allowed delimiter": the allowed set is written only in code (",", ";", "\\t", "|"); '
    'is it the documented domain?',
    'Q4 ranges.contains: the type of value is not stated (integer excluding booleans?).',
    'Q5 sample_stats: "finite numbers": are integers allowed and booleans excluded?',
    'Q6 Element domains not stated: paging items, rotation items and tasks ("JSON-compatible"), settings keys in '
    'overlay and select_prefix, parse_settings text (any string?).')


def _int(v):
    return type(v) is int


def _num(v):
    return type(v) in (int, float) and math.isfinite(v)


def _strs(v):
    return type(v) is list and all(type(x) is str for x in v)


def _ranges(v):
    return type(v) is list and all(type(p) is list and len(p) == 2 and all(_int(x) for x in p) for p in v)


def _str_map(v):
    return type(v) is dict and all(type(x) is str for x in v.values())


def _ident(key):
    return (type(key) is str and bool(key) and key[0].isascii() and (key[0].isalpha() or key[0] == '_')
            and all(c.isascii() and (c.isalnum() or c == '_') for c in key[1:]))


def _clean_value(value):
    return value == value.strip() and (not value or value.splitlines() == [value])


T = {'int': (_int, 'an integer (not a boolean)'), 'str': (lambda v: type(v) is str, 'a string'),
     'list': (lambda v: type(v) is list, 'a list'), 'strs': (_strs, 'a list of strings'),
     'numbers': (lambda v: type(v) is list and all(_num(x) for x in v), 'a list of finite numbers (no booleans)'),
     'ranges': (_ranges, 'a list of [start, end] integer pairs'), 'str_map': (_str_map, 'an object of strings')}
P_SIZE = ('int', lambda v: v > 0, 'must be positive', None)
P_NONNEG = ('int', lambda v: v >= 0, 'must be nonnegative', None)
SAMPLES = ('numbers', lambda v: all(abs(x) <= 1000000 for x in v), 'outside [-1000000, 1000000]', 'ValueError')
DOMAINS = {
    'packA/paging.py': {
        'page_count': {'item_count': P_NONNEG, 'page_size': P_SIZE},
        'get_page': {'items': ('list', None, '', None), 'page_number': P_NONNEG, 'page_size': P_SIZE},
        'page_for_index': {'item_index': P_NONNEG, 'page_size': P_SIZE},
        'page_sizes': {'item_count': P_NONNEG, 'page_size': P_SIZE},
        'page_label': {'page_number': P_NONNEG, 'item_count': P_NONNEG, 'page_size': P_SIZE,
                       '*': (lambda a: a['page_number'] < -(-a['item_count'] // a['page_size']),
                             'page absent from the result set', 'any')}},
    'packA/sample_stats.py': {
        'mean': {'values': SAMPLES}, 'spread': {'values': SAMPLES}, 'describe': {'values': SAMPLES},
        'centered': {'values': SAMPLES}, 'latest': {'values': SAMPLES, 'limit': P_NONNEG}},
    'packA/labels.py': {
        'slug': {'label': ('str', None, '', None)}, 'unique_labels': {'labels': ('strs', None, '', None)},
        'make_header': {'labels': ('strs', None, '', None),
                        'delimiter': ('str', lambda v: v in (',', ';', '\t', '|'), 'not an allowed delimiter', None)},
        'label_map': {'labels': ('strs', None, '', None)}, 'is_slug': {'value': ('str', None, '', None)}},
    'packB/ranges.py': {
        **{f: {'ranges': ('ranges', lambda v: all(a <= b for a, b in v), 'start must not exceed end', None)}
           for f in ('compact_ranges', 'covered_count', 'bounding_range')},
        'contains': {'ranges': ('ranges', lambda v: all(a <= b for a, b in v), 'start must not exceed end', None),
                     'value': ('int', None, '', None)},
        'shift_ranges': {'ranges': ('ranges', lambda v: all(a <= b for a, b in v), 'start must not exceed end', None),
                         'offset': ('int', None, '', None)}},
    'packB/rotation.py': {
        'rotate_left': {'items': ('list', None, '', None), 'offset': ('int', None, '', None)},
        'rotation_order': {'workers': ('strs', lambda v: len(set(v)) == len(v), 'workers must be distinct', None),
                           'round_number': P_NONNEG},
        'assign_tasks': {'tasks': ('list', None, '', None),
                         'workers': ('strs', lambda v: bool(v) and len(set(v)) == len(v),
                                     'workers must be distinct and nonempty', None)},
        'chunk_tasks': {'tasks': ('list', None, '', None), 'size': P_SIZE},
        'interleave': {'left': ('list', None, '', None), 'right': ('list', None, '', None)}},
    'packB/settings.py': {
        'parse_settings': {'text': ('str', None, '', None)},
        'render_settings': {'settings': ('str_map', lambda v: all(_ident(k) and _clean_value(x) for k, x in v.items()),
                                         'keys must be identifiers and values clean', None)},
        'overlay': {'base': ('str_map', None, '', None), 'updates': ('str_map', None, '', None)},
        'select_prefix': {'settings': ('str_map', None, '', None), 'prefix': ('str', None, '', None)}}}


def _signature(file: str, function: str, root=FIX):
    """(parameter names, names with defaults) of a module-level function, read from the shipped source's AST."""
    tree = ast.parse(source(file, root))
    fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function), None)
    if fn is None:
        return None
    names = [a.arg for a in fn.args.args]
    return names, set(names[len(names) - len(fn.args.defaults):])


def domain_problems(file: str, witness: dict, root=FIX) -> list:
    """[] when the witness's call lies inside the documented domain of its function (or exercises a documented
    rejection rule with an exception expectation), else the reasons. Schema validity is checked first elsewhere."""
    rules = DOMAINS.get(file, {}).get(witness.get('function'))
    sig = _signature(file, witness.get('function'), root) if rules is not None else None
    if rules is None or sig is None:
        return ['no documented domain for function %s in %s' % (witness.get('function'), file)]
    names, defaulted = sig
    args, kwargs = witness['args'], witness['kwargs']
    if len(args) > len(names) or set(kwargs) - set(names) or set(kwargs) & set(names[:len(args)]):
        return ['arguments do not bind to %s(%s)' % (witness['function'], ', '.join(names))]
    bound = dict(zip(names, args), **kwargs)
    if set(names) - set(bound) - defaulted:
        return ['missing arguments for %s' % witness['function']]
    expects_exception = 'exception' in witness['expected']
    problems, rejected = [], []
    for name, value in bound.items():
        kind, pre, why, reject = rules[name]
        check, label = T[kind]
        if not check(value):
            problems.append(f'{name} must be {label}')
        elif pre is not None and not pre(value):
            (rejected if reject else problems).append((name, why, reject) if reject else f'{name} {why}')
    if not problems and '*' in rules:
        pre, why, reject = rules['*']
        if not pre(bound):
            rejected.append(('call', why, reject))
    for name, why, reject in rejected:
        if not expects_exception or (reject != 'any' and witness['expected']['exception'] != reject):
            problems.append(f'{name}: {why} (a documented rejection; only a {reject} expectation may use it)'
                            if reject != 'any' else f'{name}: {why} (only an exception expectation may use it)')
    return problems


# ---- execution and matching ----

def run_call(src: str, witness: dict) -> dict:
    """One fresh sandbox process: the worker's outcome, or an error outcome for a stopped worker."""
    payload = {'source': src, 'function': witness['function'],
               'args': json.dumps(witness['args'], ensure_ascii=True, allow_nan=False),
               'kwargs': json.dumps(witness['kwargs'], ensure_ascii=True, allow_nan=False)}
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode('ascii')).hexdigest()
    if key in _CACHE:
        return _CACHE[key]
    launcher = sandbox()
    try:
        res = launcher.run(payload, 0, worker=EVAL_WORKER)
    except launcher.SandboxUnavailable as exc:
        raise EvaluatorUnavailable(str(exc)) from None
    if res['status'] == 'ok' and len(res['rows']) == 1 and isinstance(res['rows'][0], dict):
        out = res['rows'][0]
    else:
        out = {'outcome': 'error', 'reason': 'stopped: ' + str(res.get('reason') or res.get('status'))}
    _CACHE[key] = out
    return out


def equal(expected, tree) -> bool:
    """Exact-type recursive equality of a decoded JSON value and a worker tree (bool is not int, int is not float,
    tuple is not list; floats compare numerically, so -0.0 equals 0.0; dict key order is ignored)."""
    if type(tree) is not list or not tree:
        return False
    kind, t = type(expected), tree[0]
    if expected is None:
        return t == 'n'
    if kind is bool:
        return t == 'b' and tree[1] is expected
    if kind is int:
        return t == 'i' and int(tree[1]) == expected
    if kind is float:
        return t == 'f' and float(tree[1]) == expected
    if kind is str:
        return t == 's' and tree[1] == expected
    if kind is list:
        return t == 'l' and len(tree[1]) == len(expected) and all(equal(e, v) for e, v in zip(expected, tree[1]))
    if kind is dict:
        if t != 'd':
            return False
        got = dict((k, v) for k, v in tree[1])
        return set(got) == set(expected) and all(equal(expected[k], got[k]) for k in expected)
    return False


def met(outcome: dict, expected: dict) -> bool:
    if 'return' in expected:
        return outcome.get('outcome') == 'return' and equal(expected['return'], outcome.get('value'))
    return (outcome.get('outcome') == 'raise' and outcome.get('type') == expected['exception']
            and outcome.get('builtin') is True)


def judge_witness(witness: dict, shipped_src: str, reference_src: str) -> dict:
    """Reference and shipped calls in separate fresh sandbox processes. proven: the reference expectation matches and
    the shipped call completes (return or target-call exception) without matching. both_fail: both calls complete
    and neither matches. Execution errors never establish a mismatch."""
    ref = run_call(reference_src, witness)
    shipped = run_call(shipped_src, witness)
    ref_done = ref['outcome'] in ('return', 'raise')
    shipped_done = shipped['outcome'] in ('return', 'raise')
    ref_ok = ref_done and met(ref, witness['expected'])
    shipped_ok = shipped_done and met(shipped, witness['expected'])
    return {'reference': ref, 'shipped': shipped, 'reference_matches': ref_ok,
            'shipped_mismatch': shipped_done and not shipped_ok, 'proven': ref_ok and shipped_done and not shipped_ok,
            'both_fail': ref_done and shipped_done and not ref_ok and not shipped_ok}


# ---- scoring ----

def score(answer_text, pack: str, root=FIX, fixes=None) -> dict:
    """Score a run's final answer against the seeds of its own pack (root: the fixture tree, fixes: registered fixes
    {module path: source} for the unseeded rule). Strict JSON, one object keyed by exactly the pack's three module
    paths, each value a findings array or null (a module not reviewed)."""
    mods = modules(pack, root)
    paths = [m['file'] for m in mods]
    out = {'oracle_version': ORACLE_VERSION, 'pack': pack, 'answer_ok': False, 'answer_error': '', 'files': {}}
    answer = None
    try:
        if not isinstance(answer_text, str) or not answer_text.strip():
            raise ValueError('no final answer')
        answer = strict_json(answer_text)
        if type(answer) is not dict:
            raise ValueError('the answer must be one JSON object')
        if set(answer) != set(paths):
            raise ValueError('keys must be exactly ' + ', '.join(paths))
        out['answer_ok'] = True
    except (ValueError, RecursionError) as exc:
        out['answer_error'] = str(exc)[:200] or type(exc).__name__
    for m in mods:
        value = answer.get(m['file'], MISSING) if type(answer) is dict else MISSING
        out['files'][m['file']] = score_file(m, value, out['answer_ok'], root, (fixes or {}).get(m['file']))
    files = out['files'].values()
    seeds = sum(len(f['seeds']) for f in files)
    hit = sum(len(f['seeds_hit']) for f in files)
    out.update({'correct_files': sum(f['correct'] for f in files), 'file_count': len(paths), 'seeds': seeds,
                'seeds_hit': hit, 'recall': hit / seeds if seeds else None,
                **{k: sum(f[k] for f in files) for k in ('findings_total', 'false_positives', 'unproven', 'unseeded',
                                                         'review_both_fail', 'invalid', 'out_of_domain',
                                                         'mislocated')},
                'domain_status': DOMAIN_STATUS})
    return out


def score_file(module: dict, value, answer_ok: bool, root=FIX, fix: str | None = None) -> dict:
    seeds = module['seeds']
    shipped = source(module['file'], root)
    reference = source(module['reference_file'], root)
    res = {'seeds': [s['id'] for s in seeds], 'clean': not seeds, 'response': 'list', 'findings': [],
           'seeds_hit': [], 'findings_total': 0, 'false_positives': 0, 'unproven': 0, 'unseeded': 0,
           'review_both_fail': 0, 'invalid': 0, 'out_of_domain': 0, 'mislocated': 0, 'correct': False}
    if value is MISSING or value is None or type(value) is not list:
        res['response'] = 'missing' if value is MISSING else 'null' if value is None else 'invalid'
        return res
    res['findings_total'] = len(value)
    lines = line_count(shipped)
    proven_seeds = set()
    for i, finding in enumerate(value):
        entry = {'index': i}
        problems = validate_finding(finding, module['file'], lines)
        if problems:
            entry.update(category='invalid', problems=problems)
            for k in ('invalid', 'unproven', 'false_positives'):
                res[k] += 1
            res['findings'].append(entry)
            continue
        outside = domain_problems(module['file'], finding['witness'], root)
        if outside:
            entry.update(category='out_of_domain', problems=outside)
            for k in ('out_of_domain', 'unproven', 'false_positives'):
                res[k] += 1
            res['findings'].append(entry)
            continue
        verdict = judge_witness(finding['witness'], shipped, reference)
        entry.update({k: verdict[k] for k in ('proven', 'both_fail', 'reference_matches', 'shipped_mismatch')},
                     shipped=verdict['shipped'], reference=verdict['reference'], line=finding['line'],
                     **{'class': finding['class']})
        if verdict['proven']:
            seed = next((s for s in seeds if s['class'] == finding['class'] and in_span(finding['line'], s['span'])),
                        None)
            if seed is not None:
                entry.update(category='seeded', seed=seed['id'])
                proven_seeds.add(seed['id'])
            else:
                entry['category'] = 'mislocated'
                res['mislocated'] += 1
                res['false_positives'] += 1
        elif verdict['both_fail'] and fix is not None and met_on(fix, finding['witness']):
            entry['category'] = 'unseeded'
            res['unseeded'] += 1
            res['unproven'] += 1
        else:
            entry['category'] = 'unproven'
            res['unproven'] += 1
            res['false_positives'] += 1
            if verdict['both_fail']:
                entry['review'] = 'fails on shipped and reference: candidate unseeded defect, needs a registered fix'
                res['review_both_fail'] += 1
        res['findings'].append(entry)
    res['seeds_hit'] = sorted(proven_seeds)
    others = [f for f in res['findings'] if f.get('category') != 'unseeded']
    if not seeds:
        res['correct'] = answer_ok and not others
    else:
        res['correct'] = answer_ok and proven_seeds == {s['id'] for s in seeds} and res['mislocated'] == 0
    return res


def met_on(src: str, witness: dict) -> bool:
    out = run_call(src, witness)
    return out['outcome'] in ('return', 'raise') and met(out, witness['expected'])
