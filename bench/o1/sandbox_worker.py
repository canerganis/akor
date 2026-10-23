"""Confined code-running worker for repair-handoff-20/v1 (O1, G3c-O1). Standard library only.

The parent (sandbox.py) copies this file into a fresh empty temporary directory, starts it with the controlled
launcher (base interpreter, -P -S -s -B, an environment holding only PYTHONHASHSEED and SYSTEMROOT), assigns the process
to a Job Object (256 MiB, one active process, 2 s CPU, kill on close) and only then writes the payload to stdin. The
payload holds candidate sources and test inputs; expected results never come here.

Layers, outermost last:
  1. AST policy (check_function / check_module): one function with the frozen name and parameters, a node whitelist,
     no name or attribute starting with an underscore, attribute access only to frozen method names, no forbidden
     names. A refusal is reported as a candidate verdict, nothing runs.
  2. Restricted builtins: candidate code runs with a frozen builtins dict (no import, open, eval, getattr, type, ...).
  3. Audit hook: armed after the definitions are executed and before any candidate function is called; import, open,
     compile, exec, socket, os, subprocess, ctypes and similar events raise.
  4. The process: Job Object limits, empty environment, temporary cwd, no repo path (enforced by the parent).

Output: one JSON line {"ready": meta} after the setup (before any candidate function is called), then one JSON line
{"rows": [...]} when every row ran. A missing ready line is a verifier failure; a ready line without rows means the
candidate was stopped (resource limit or crash).
"""
import ast
import builtins
import json
import os
import sys

MAX_ROW_OUTPUT = 65536
MAX_DEPTH = 64


# ---- layer 1: the AST policy (also imported by the parent for the per-job policy check) ----

def _violations(tree, policy, top_name=None, top_params=None, module_functions=None):
    nodes = set(policy['nodes'])
    methods = set(policy['methods'])
    forbidden = set(policy['forbidden_names'])
    out = []

    def bad(node, why):
        out.append(f"line {getattr(node, 'lineno', 0)}: {why}")

    for node in ast.walk(tree):
        kind = type(node).__name__
        if kind not in nodes:
            bad(node, f'{kind} is not permitted')
            continue
        if isinstance(node, ast.Name):
            if node.id.startswith('_'):
                bad(node, f'name {node.id} starts with an underscore')
            elif node.id in forbidden:
                bad(node, f'name {node.id} is forbidden')
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith('_') or node.attr not in methods:
                bad(node, f'attribute {node.attr} is not a permitted method')
        elif isinstance(node, ast.arg):
            if node.arg.startswith('_') or node.arg in forbidden:
                bad(node, f'parameter {node.arg} is not permitted')
            if node.annotation is not None:
                bad(node, 'annotations are not permitted')
        elif isinstance(node, ast.keyword):
            if node.arg is None or node.arg.startswith('_'):
                bad(node, 'this keyword argument form is not permitted')
        elif isinstance(node, ast.ExceptHandler):
            if node.name is not None and (node.name.startswith('_') or node.name in forbidden):
                bad(node, f'handler name {node.name} is not permitted')
        elif isinstance(node, ast.FunctionDef):
            if node.decorator_list or node.returns is not None or getattr(node, 'type_params', None):
                bad(node, 'decorators, return annotations and type parameters are not permitted')
            if node.name.startswith('_') or node.name in forbidden:
                bad(node, f'function name {node.name} is not permitted')
            a = node.args
            if a.posonlyargs or a.vararg or a.kwonlyargs or a.kw_defaults or a.kwarg or a.defaults:
                bad(node, 'only plain positional parameters without defaults are permitted')
        elif isinstance(node, ast.Lambda):
            a = node.args
            if a.posonlyargs or a.vararg or a.kwonlyargs or a.kw_defaults or a.kwarg or a.defaults:
                bad(node, 'only plain positional lambda parameters without defaults are permitted')
        elif isinstance(node, ast.Constant):
            if type(node.value) not in (str, int, float, bool, type(None)):
                bad(node, f'constant of type {type(node.value).__name__} is not permitted')
    body = tree.body
    if module_functions is None:
        if len(body) != 1 or not isinstance(body[0], ast.FunctionDef):
            bad(tree, 'the source must be exactly one top-level function definition')
        else:
            fn = body[0]
            params = [a.arg for a in fn.args.args]
            if fn.name != top_name or params != list(top_params):
                bad(fn, f'the function must be def {top_name}({", ".join(top_params)}):')
    else:
        defs = [s for s in body if isinstance(s, ast.FunctionDef)]
        rest = [s for s in body if not isinstance(s, ast.FunctionDef)]
        doc = (len(rest) == 1 and rest[0] is body[0] and isinstance(rest[0], ast.Expr)
               and isinstance(rest[0].value, ast.Constant) and isinstance(rest[0].value.value, str))
        if rest and not doc:
            bad(tree, 'a module holds a docstring and its function definitions only')
        found = {d.name: [a.arg for a in d.args.args] for d in defs}
        if found != {k: list(v) for k, v in module_functions.items()} or len(defs) != len(module_functions):
            bad(tree, 'the module must define exactly the frozen functions with their frozen parameters')
    return out


def _parse(source, policy):
    if not isinstance(source, str):
        return None, ['the source is not text']
    try:
        size = len(source.encode('utf-8'))
    except UnicodeEncodeError:
        return None, ['the source is not valid UTF-8 text']
    limit = policy['max_module_bytes'] if policy.get('_module') else policy['max_source_bytes']
    if size > limit:
        return None, [f'the source has {size} UTF-8 bytes, more than {limit}']
    try:
        return ast.parse(source, mode='exec'), []
    except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
        return None, ['the source does not parse: ' + type(exc).__name__]


def check_function(source, name, params, policy):
    """[] when source is one policy-conforming function def name(params), else the reasons."""
    tree, problems = _parse(source, policy)
    if tree is None:
        return problems
    try:
        return _violations(tree, policy, name, params)
    except RecursionError:
        return ['the source nests too deeply']


def check_module(source, functions, policy):
    """[] when source is a docstring plus exactly the frozen functions, each policy-conforming."""
    tree, problems = _parse(source, dict(policy, _module=True))
    if tree is None:
        return problems
    try:
        return _violations(tree, policy, module_functions=functions)
    except RecursionError:
        return ['the source nests too deeply']


# ---- type-strict canonical values ----

class Unsupported(Exception):
    pass


def _walk(value, depth):
    if depth > MAX_DEPTH:
        raise Unsupported('nesting deeper than %d' % MAX_DEPTH)
    kind = type(value)
    if value is None or kind is bool or kind is str:
        return
    if kind is int:
        return
    if kind is list:
        for item in value:
            _walk(item, depth + 1)
        return
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise Unsupported('object key of type ' + type(key).__name__)
            _walk(item, depth + 1)
        return
    raise Unsupported('value of type ' + kind.__name__)


def canonical(value):
    """Canonical JSON text of a supported value (None, bool, int, str, list, dict with str keys). Anything else,
    including tuples, sets and floats, is refused before serialization (json would turn a tuple into a list)."""
    _walk(value, 0)
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _containers(value, out, depth=0):
    if depth > MAX_DEPTH:
        return out
    if type(value) in (list, dict):
        out.add(id(value))
        for item in (value.values() if type(value) is dict else value):
            _containers(item, out, depth + 1)
    return out


# ---- layers 2 and 3 ----

ARMED = [False]
BLOCKED_EXACT = {'import', 'open', 'compile', 'exec', 'builtins.input', 'builtins.breakpoint', 'object.__getattr__',
                 'object.__setattr__', 'object.__delattr__', 'function.__new__', 'code.__new__', 'sys._getframe',
                 'sys.settrace', 'sys.setprofile', 'sys.addaudithook'}
BLOCKED_PREFIX = ('socket.', 'os.', 'subprocess.', 'ctypes.', 'shutil.', 'urllib.', 'http.', 'ftplib.', 'smtplib.',
                  'winreg.', 'msvcrt.', '_winapi.', 'gc.', 'marshal.', 'pickle.', 'cpython.', 'sys.', 'tempfile.',
                  'glob.', 'pathlib.', 'webbrowser.', 'ensurepip.', 'shelve.', 'sqlite3.', 'mmap.', 'resource.',
                  'signal.', 'time.sleep')


def _audit(event, args):
    if ARMED[0] and (event in BLOCKED_EXACT or event.startswith(BLOCKED_PREFIX)):
        raise RuntimeError('blocked by the sandbox: ' + event)


class StubCallError(Exception):
    """A stub received arguments its frozen table does not list."""


def _stub(spec, calls, safe):
    table = {}
    for entry in spec['responses']:
        table[canonical(entry['args'])] = entry

    def stub(*args):
        key = canonical(list(args))
        calls.append(key)
        entry = table.get(key)
        if entry is None:
            raise StubCallError('unexpected call')
        if 'raise' in entry:
            raise safe[entry['raise']]('stub')
        return json.loads(canonical(entry['return']))
    return stub


def _recorder(fn, calls):
    def recorded(*args):
        try:
            calls.append(canonical(list(args)))
        except Unsupported as exc:
            calls.append('unsupported: ' + str(exc))
        return fn(*args)
    return recorded


def _run_row(row, spaces, safe, alias):
    unit = spaces[row['unit']]
    fn = unit['ns'][row['fn']]
    calls = []
    if unit.get('binds'):
        core = spaces['core']['ns'][unit['binds']] if 'core' in spaces else None
        mode = row.get('core', 'real')
        if mode == 'stub':
            unit['ns'][unit['binds']] = _stub(row['stub'], calls, safe)
        elif mode == 'recorded':
            unit['ns'][unit['binds']] = _recorder(core, calls)
        else:
            unit['ns'][unit['binds']] = core
    args = json.loads(json.dumps(row['args']))
    before = canonical(args)
    held = _containers(args, set())
    out = {}
    try:
        value = fn(*args)
    except BaseException as exc:  # a candidate exception is a result (by class name), never a worker failure
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        out['x'] = type(exc).__name__
    else:
        try:
            text = canonical(value)
            if len(text) > MAX_ROW_OUTPUT:
                out['bad'] = 'output larger than %d bytes' % MAX_ROW_OUTPUT
            else:
                out['r'] = text
            if alias and _containers(value, set()) & held:
                out['alias'] = True
        except Unsupported as exc:
            out['bad'] = str(exc)
        except (ValueError, RecursionError, MemoryError) as exc:
            out['bad'] = 'output not serializable: ' + type(exc).__name__
    try:
        if canonical(args) != before:
            out['mut'] = True
    except Unsupported:
        out['mut'] = True
    if row.get('core') in ('stub', 'recorded'):
        out['calls'] = calls
    return out


def _emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=True, separators=(',', ':')) + '\n')
    sys.stdout.flush()


def main():
    meta = {'cwd': os.getcwd(), 'env': sorted(os.environ), 'hash': hash('akor-o1-seed-probe'),
            'flags': {'isolated': sys.flags.isolated, 'no_site': sys.flags.no_site,
                      'ignore_environment': sys.flags.ignore_environment, 'safe_path': sys.flags.safe_path,
                      'hash_randomization': sys.flags.hash_randomization}}
    payload = json.loads(sys.stdin.read())
    policy = payload['policy']
    safe = {name: getattr(builtins, name) for name in policy['builtins']}
    safe['StubCallError'] = StubCallError
    trusted_probe = payload.get('probe') is True  # parent-side test fixtures only: policy layer skipped
    spaces = {}
    for unit in payload['units']:
        if unit['kind'] == 'function':
            problems = [] if trusted_probe else check_function(unit['source'], unit['name'], unit['params'], policy)
        else:
            problems = [] if trusted_probe else check_module(unit['source'], unit['functions'], policy)
        if problems:
            _emit({'ready': meta})
            _emit({'refused': {unit['id']: problems[:8]}})
            return
        ns = {'__builtins__': safe}
        try:
            code = compile(unit['source'], '<' + unit['id'] + '>', 'exec')
            exec(code, ns)
        except BaseException as exc:  # a definition that cannot be built is a candidate refusal
            _emit({'ready': meta})
            _emit({'refused': {unit['id']: ['the definition failed: ' + type(exc).__name__]}})
            return
        spaces[unit['id']] = {'ns': ns, 'binds': unit.get('binds')}
    sys.addaudithook(_audit)
    _emit({'ready': meta})
    ARMED[0] = True
    rows = []
    for row in payload['rows']:
        rows.append(_run_row(row, spaces, safe, bool(payload.get('alias'))))
    ARMED[0] = False
    _emit({'rows': rows})


if __name__ == '__main__':
    main()
