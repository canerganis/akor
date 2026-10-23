"""The evaluator's own code-running worker (independent of the executor's sandbox_worker.py). Standard library only.

It is started by the shared launcher (sandbox.run with worker=this file): same controlled interpreter flags, hash
seed, Job Object and temporary directory, so the confinement is the frozen one. Everything that decides an outcome is
written here again: the restricted builtins come from the payload's list, values are encoded as tagged trees
(["n"], ["b", x], ["i", "digits"], ["s", x], ["l", [...]], ["d", [[key, value], ...] sorted]) and anything else is
"unsupported", stub tables are keyed by those trees, and the audit hook refuses the same event families. The parent
(evaluator.py) runs its own AST policy before sending code here and compares outcomes itself.
"""
import builtins
import json
import os
import sys

DEEP = 64
GUARD = [False]
REFUSE = ('import', 'open', 'compile', 'exec', 'socket.', 'os.', 'subprocess.', 'ctypes.', '_winapi.', 'shutil.',
          'urllib.', 'http.', 'sys.', 'object.__getattr__', 'object.__setattr__', 'object.__delattr__',
          'function.__new__', 'code.__new__', 'builtins.input', 'gc.', 'marshal.', 'pickle.', 'winreg.', 'msvcrt.',
          'tempfile.', 'pathlib.', 'sqlite3.', 'mmap.', 'signal.', 'time.sleep')


def guard(event, args):
    if GUARD[0] and any(event == r or (r.endswith('.') and event.startswith(r)) for r in REFUSE):
        raise RuntimeError('refused by the evaluator worker: ' + event)


class Unsupported(Exception):
    pass


def tag(value, depth=0):
    if depth > DEEP:
        raise Unsupported('too deep')
    if value is None:
        return ['n']
    if value is True or value is False:
        return ['b', value]
    if type(value) is int:
        return ['i', str(value)]
    if type(value) is str:
        return ['s', value]
    if type(value) is list:
        return ['l', [tag(v, depth + 1) for v in value]]
    if type(value) is dict:
        pairs = []
        for k, v in value.items():
            if type(k) is not str:
                raise Unsupported('key')
            pairs.append([k, tag(v, depth + 1)])
        pairs.sort(key=lambda p: p[0])
        return ['d', pairs]
    raise Unsupported(type(value).__name__)


def key_of(value):
    return json.dumps(tag(value), separators=(',', ':'), ensure_ascii=True)


def mutable_ids(value, seen, depth=0):
    if depth <= DEEP and type(value) in (list, dict):
        seen.add(id(value))
        for v in (value.values() if type(value) is dict else value):
            mutable_ids(v, seen, depth + 1)
    return seen


class TableMiss(Exception):
    pass


def make_stub(table, log, allowed):
    rows = {key_of(entry['args']): entry for entry in table['responses']}

    def stub(*args):
        k = key_of(list(args))
        log.append(k)
        if k not in rows:
            raise TableMiss('no row')
        entry = rows[k]
        if 'raise' in entry:
            raise allowed[entry['raise']]('stub')
        return json.loads(json.dumps(entry['return']))
    return stub


def make_spy(fn, log):
    def spy(*args):
        try:
            log.append(key_of(list(args)))
        except Unsupported:
            log.append('unsupported')
        return fn(*args)
    return spy


def run_one(row, spaces, allowed, alias):
    space = spaces[row['unit']]
    log = []
    if space.get('binds'):
        real = spaces['core']['ns'][space['binds']] if 'core' in spaces else None
        mode = row.get('core', 'real')
        space['ns'][space['binds']] = (make_stub(row['stub'], log, allowed) if mode == 'stub'
                                       else make_spy(real, log) if mode == 'recorded' else real)
    args = json.loads(json.dumps(row['args']))
    before = key_of(args)
    owned = mutable_ids(args, set())
    result = {}
    try:
        value = space['ns'][row['fn']](*args)
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        result['raised'] = type(exc).__name__
    else:
        try:
            result['value'] = tag(value)
            if alias and mutable_ids(value, set()) & owned:
                result['shares_input'] = True
        except (Unsupported, RecursionError, MemoryError) as exc:
            result['unsupported'] = str(exc) or type(exc).__name__
    try:
        if key_of(args) != before:
            result['mutated'] = True
    except Unsupported:
        result['mutated'] = True
    if row.get('core') in ('stub', 'recorded'):
        result['log'] = log
    return result


def say(obj):
    sys.stdout.write(json.dumps(obj, separators=(',', ':'), ensure_ascii=True) + '\n')
    sys.stdout.flush()


def main():
    meta = {'cwd': os.getcwd(), 'env': sorted(os.environ), 'hash': hash('akor-o1-seed-probe'),
            'flags': {'isolated': sys.flags.isolated, 'no_site': sys.flags.no_site,
                      'ignore_environment': sys.flags.ignore_environment, 'safe_path': sys.flags.safe_path,
                      'hash_randomization': sys.flags.hash_randomization}}
    job = json.loads(sys.stdin.read())
    allowed = {n: getattr(builtins, n) for n in job['builtins']}
    allowed['TableMiss'] = TableMiss
    spaces = {}
    for unit in job['units']:
        ns = {'__builtins__': allowed}
        try:
            exec(compile(unit['source'], '<eval-' + unit['id'] + '>', 'exec'), ns)
        except BaseException as exc:
            say({'ready': meta})
            say({'refused': {unit['id']: ['definition failed: ' + type(exc).__name__]}})
            return
        spaces[unit['id']] = {'ns': ns, 'binds': unit.get('binds')}
    sys.addaudithook(guard)
    say({'ready': meta})
    GUARD[0] = True
    results = [run_one(row, spaces, allowed, bool(job.get('alias'))) for row in job['rows']]
    GUARD[0] = False
    say({'rows': results})


if __name__ == '__main__':
    main()
