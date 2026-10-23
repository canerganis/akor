"""Code-review pilot: the evaluator's witness worker (codereview-witness-v1). Standard library only; evaluator-only.

oracle.py starts this file through the O1 launcher (bench/o1/sandbox.run with worker=this file): the base interpreter
with -P -S -s -B, an environment holding only PYTHONHASHSEED and SYSTEMROOT, a fresh empty temporary directory, a Job
Object (256 MiB, one process, 2 s CPU, 5 s wall). The payload on stdin holds one module source, one function name and
the JSON texts of args and kwargs; expected results never come here. This worker:

  1. decodes args and kwargs strictly (duplicate keys, NaN and Infinity refused) into fresh objects;
  2. executes the module source in a fresh namespace (imports happen here, before the audit hook is armed);
  3. selects the function: a public identifier bound to a plain synchronous function defined directly in the module;
  4. prevalidates the binding with inspect.signature(function).bind(*args, **kwargs);
  5. arms the audit hook (import, open, exec, os, subprocess, socket and similar events are refused) and calls
     function(*args, **kwargs) once;
  6. reports one outcome: {"outcome": "return", "value": <tagged tree>}, {"outcome": "raise", "type": name,
     "builtin": exact builtins identity}, or {"outcome": "error", "reason": ...} for anything that is not a result of
     the target call (load, selection, binding, a refused event, recursion or memory exhaustion, an unencodable value).

Output: one {"ready": meta} line after the setup, then one {"rows": [outcome]} line. The parent decides every match.
Tagged trees: ["n"], ["b", x], ["i", "digits"], ["f", repr], ["s", x], ["l", [...]], ["t", [...]],
["d", [[key, tree], ...] sorted by key] (string keys only), ["o", type name] for anything else.
"""
import builtins
import inspect
import json
import keyword
import os
import sys

DEEP = 64
MAX_OUT = 65536
ARMED = [False]
REFUSE = ('import', 'open', 'compile', 'exec', 'socket.', 'os.', 'subprocess.', 'ctypes.', '_winapi.', 'shutil.',
          'urllib.', 'http.', 'sys.', 'object.__getattr__', 'object.__setattr__', 'object.__delattr__',
          'function.__new__', 'code.__new__', 'builtins.input', 'gc.', 'marshal.', 'pickle.', 'winreg.', 'msvcrt.',
          'tempfile.', 'pathlib.', 'sqlite3.', 'mmap.', 'signal.', 'time.sleep', 'random.')


class Refused(BaseException):
    """An audited event the witness may not cause; a BaseException so module code cannot swallow it."""


def guard(event, args):
    if ARMED[0] and any(event == r or (r.endswith('.') and event.startswith(r)) for r in REFUSE):
        raise Refused(event)


def strict(text):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError('duplicate key')
            out[k] = v
        return out

    def constant(name):
        raise ValueError('non-finite constant')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def tag(value, depth=0):
    if depth > DEEP:
        raise ValueError('nesting too deep')
    kind = type(value)
    if value is None:
        return ['n']
    if kind is bool:
        return ['b', value]
    if kind is int:
        return ['i', str(value)]
    if kind is float:
        return ['f', repr(value)]
    if kind is str:
        return ['s', value]
    if kind is list:
        return ['l', [tag(v, depth + 1) for v in value]]
    if kind is tuple:
        return ['t', [tag(v, depth + 1) for v in value]]
    if kind is dict:
        pairs = []
        for k, v in value.items():
            if type(k) is not str:
                return ['o', 'dict with a non-string key']
            pairs.append([k, tag(v, depth + 1)])
        pairs.sort(key=lambda p: p[0])
        return ['d', pairs]
    return ['o', kind.__name__]


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=True, separators=(',', ':')) + '\n')
    sys.stdout.flush()


def finish(meta, outcome):
    emit({'ready': meta}) if meta is not None else None
    emit({'rows': [outcome]})


def main():
    meta = {'cwd': os.getcwd(), 'env': sorted(os.environ), 'hash': hash('akor-codereview-probe'),
            'flags': {'isolated': sys.flags.isolated, 'no_site': sys.flags.no_site,
                      'ignore_environment': sys.flags.ignore_environment, 'safe_path': sys.flags.safe_path,
                      'hash_randomization': sys.flags.hash_randomization}}
    payload = json.loads(sys.stdin.read())
    name = payload['function']
    try:
        args, kwargs = strict(payload['args']), strict(payload['kwargs'])
    except (ValueError, RecursionError):
        return finish(meta, {'outcome': 'error', 'reason': 'arguments are not strict JSON'})
    if type(args) is not list or type(kwargs) is not dict:
        return finish(meta, {'outcome': 'error', 'reason': 'args must be an array and kwargs an object'})
    ns = {'__name__': 'fixture_target', '__builtins__': builtins}
    try:
        exec(compile(payload['source'], '<fixture>', 'exec'), ns)
    except BaseException as exc:  # noqa: BLE001  a module that cannot load decides nothing
        return finish(meta, {'outcome': 'error', 'reason': 'load: ' + type(exc).__name__})
    fn = ns.get(name)
    if (type(name) is not str or not name.isidentifier() or keyword.iskeyword(name) or name.startswith('_')
            or not inspect.isfunction(fn) or fn.__module__ != 'fixture_target' or fn.__name__ != name
            or inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn)):
        return finish(meta, {'outcome': 'error', 'reason': 'no public synchronous module function ' + str(name)[:80]})
    try:
        inspect.signature(fn).bind(*args, **kwargs)
    except TypeError:
        return finish(meta, {'outcome': 'error', 'reason': 'arguments do not bind'})
    sys.addaudithook(guard)
    emit({'ready': meta})
    ARMED[0] = True
    try:
        value = fn(*args, **kwargs)
    except Refused as exc:
        ARMED[0] = False
        return finish(None, {'outcome': 'error', 'reason': 'refused event ' + str(exc)[:80]})
    except (RecursionError, MemoryError) as exc:
        ARMED[0] = False
        return finish(None, {'outcome': 'error', 'reason': 'resource: ' + type(exc).__name__})
    except BaseException as exc:  # noqa: BLE001  a target-call exception is a result
        ARMED[0] = False
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            return finish(None, {'outcome': 'error', 'reason': 'exit: ' + type(exc).__name__})
        kind = type(exc)
        return finish(None, {'outcome': 'raise', 'type': kind.__name__,
                             'builtin': getattr(builtins, kind.__name__, None) is kind})
    ARMED[0] = False
    try:
        tree = tag(value)
        text = json.dumps(tree, ensure_ascii=True)
    except (ValueError, RecursionError, MemoryError):
        return finish(None, {'outcome': 'error', 'reason': 'return value cannot be encoded'})
    if len(text) > MAX_OUT:
        return finish(None, {'outcome': 'error', 'reason': 'return value larger than %d bytes' % MAX_OUT})
    finish(None, {'outcome': 'return', 'value': tree})


if __name__ == '__main__':
    main()
