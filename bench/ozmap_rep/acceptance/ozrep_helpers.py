"""Shared helpers for the blind acceptance tests (see INTERFACE.md for the harness interface and the guard).

A plain module (not conftest.py) so that tests can import it by a name no other test directory uses."""
import base64
import datetime as dt
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
HARNESS_DIR = REPO / 'bench' / 'ozmap_rep'
SENTINEL = HARNESS_DIR / 'run.py'

for p in (str(REPO), str(REPO / 'examples')):
    if p not in sys.path:
        sys.path.insert(0, p)

BACKENDS = ('codex', 'sonnet')
SECRET_ACCESS_MARK = 'SECRET-ACCESS-MARK'
SECRET_REFRESH = 'SECRET-REFRESH-TOKEN-4711'


def harness_built():
    return SENTINEL.exists()


def harness(name):
    """Import bench.ozmap_rep.<name>. Skips while the harness is not built (sentinel run.py absent), fails afterwards."""
    if not harness_built():
        if os.environ.get('OZMAP_REP_STRICT') == '1':
            pytest.fail(f'harness not built: {SENTINEL} is missing (strict mode)')
        pytest.skip(f'harness not built: {SENTINEL.relative_to(REPO)} is missing')
    try:
        return importlib.import_module(f'bench.ozmap_rep.{name}')
    except ImportError as exc:  # a harness that exists but lacks a module or breaks on import is a failure
        pytest.fail(f'bench.ozmap_rep.{name} cannot be imported: {exc!r}')


def need(module, *names):
    """Fail (never skip) when a built harness module lacks an interface attribute."""
    missing = [n for n in names if not hasattr(module, n)]
    if missing:
        pytest.fail(f'{module.__name__} lacks {missing} (see INTERFACE.md)')
    return [getattr(module, n) for n in names] if len(names) > 1 else getattr(module, names[0])


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def make_jwt(exp, extra=None):
    payload = {'exp': int(exp.timestamp()), 'marker': SECRET_ACCESS_MARK, **(extra or {})}
    return '.'.join([b64u(b'{"alg":"none"}'), b64u(json.dumps(payload).encode()), b64u(b'sig')])


def auth_doc(exp, last_refresh='2026-10-15T18:40:00Z', refresh=SECRET_REFRESH):
    return {'auth_mode': 'chatgpt', 'tokens': {'id_token': 'x.y.z', 'access_token': make_jwt(exp),
                                               'refresh_token': refresh}, 'last_refresh': last_refresh}


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def write_auth(directory, doc):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'auth.json'
    path.write_text(json.dumps(doc), encoding='utf-8')
    return path


def run_cli(args, *, env=None, cwd=REPO, timeout=600, module='bench.ozmap_rep.run'):
    full_env = dict(os.environ)
    full_env.update(env or {})
    return subprocess.run([sys.executable, '-m', module, *args], cwd=str(cwd), env=full_env, capture_output=True,
                          text=True, encoding='utf-8', timeout=timeout)


def jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def tree_text(root, skip=()):
    """Every readable file under root as text, for secret scans. skip: directories (Paths) left out."""
    skip = [Path(s).resolve() for s in skip]
    found = {}
    for p in Path(root).rglob('*'):
        if not p.is_file():
            continue
        rp = p.resolve()
        if any(s == rp or s in rp.parents for s in skip):
            continue
        found[str(p)] = p.read_bytes().decode('utf-8', errors='replace')
    return found


def passing_summary():
    """A summary (INTERFACE.md, gates) in which every gate passes with room to spare except where noted."""
    def cell(tokens, makespan, correct=256, jobs=256, **kw):
        base = {'jobs': jobs, 'correct': correct, 'unresolved': 0, 'tokens': tokens,
                'makespan_s': makespan, 'usage': 'complete', 'evidence': 'complete', 'state': 'complete',
                'rule_errors': 0, 'ops': {}}
        base.update(kw)
        return base
    cells = {}
    for b in BACKENDS:
        cells[f'{b}/materials/cold/A'] = cell(100000, 50.0)
        cells[f'{b}/materials/cold/C'] = cell(70000, 90.0)
        cells[f'{b}/materials/warm/A'] = cell(100000, 50.0)
        cells[f'{b}/materials/warm/C'] = cell(40000, 40.0)
    cells['codex/materials/cold/B'] = cell(90000, 100.0)
    cells['codex/boolq/cold/A'] = cell(100000, 60.0, correct=240)
    cells['codex/boolq/cold/B'] = cell(104000, 70.0, correct=240)
    cells['codex/boolq/cold/C'] = cell(105000, 64.0, correct=240)
    boot = {k: {'efficiency_valid': True, 'completion_failure': False}
            for k in ('codex/materials', 'sonnet/materials', 'codex/boolq')}
    r_cells = {}
    for b in BACKENDS:
        r_cells[f'{b}/warm/A'] = cell(60000, 30.0, jobs=192, correct=192)
        r_cells[f'{b}/warm/C'] = cell(10000, 15.0, jobs=192, correct=192)
    return {'cells': cells, 'R': ['verdict', 'margin', 'temp_class'], 'R_cells': r_cells,
            'validity': {'isolation': 'passed', 'leakage': [], 'accounting_failures': [], 'interrupted': [],
                         'bootstrap': boot}}



def make_sentinels(directory):
    """Real-CLI tripwires: executables named codex and claude that only record that they were called.
    Returns an env dict whose PATH holds nothing but the tripwire directory, the interpreter and the system dirs."""
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / 'tripwire.log'
    nl = chr(10)
    for name in ('codex', 'claude'):
        (directory / name).write_text('#!/bin/sh' + nl + f'echo {name} >> "{log.as_posix()}"' + nl + 'exit 97' + nl,
                                      encoding='utf-8')
        try:
            (directory / name).chmod(0o755)
        except OSError:
            pass
        (directory / f'{name}.cmd').write_text('@echo off' + nl + f'echo {name}>>"{log}"' + nl + 'exit /b 97' + nl,
                                               encoding='utf-8')
        (directory / f'{name}.bat').write_text('@echo off' + nl + f'echo {name}>>"{log}"' + nl + 'exit /b 97' + nl,
                                               encoding='utf-8')
    parts = [str(directory), str(Path(sys.executable).parent)]
    root = os.environ.get('SYSTEMROOT')
    if root:
        parts += [str(Path(root) / 'System32'), root]
    else:
        parts += ['/usr/bin', '/bin']
    return {'PATH': os.pathsep.join(parts)}


def tripwire_calls(directory):
    log = directory / 'tripwire.log'
    return log.read_text(encoding='utf-8').split() if log.exists() else []
