"""Route identity (oz-rule/1 amendment 1, D7): the full identity of the worker that produces a result.

route = {adapter_hash, backend, model, effort, cli_version, environment_hash}; worker_hash = SHA256(canonical(route)).
canonical(x) is the UTF-8 json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
of amendment D6. A model label alone never identifies a worker: Claude and Codex runs, or two efforts, or two CLI
versions, or two adapter sources have different worker hashes.

adapter_hash covers the canonical adapter configuration (the adapter JSON file) and a manifest of the executable source
byte hashes (every argv entry after the program that names an existing file, plus the sibling modules those Python files import,
for example claude_map_adapter.py and the frozen claude_cli_adapter.py it imports),
ordered by path. environment_hash covers the frozen nonsecret invocation configuration: the argv, the flags the adapter
reports, and the nonsecret OZ_* variables the adapter reads. Effective backend, model, effort and CLI version come from
the adapter itself (`--identity`, no model call) and are reconciled with the requested model and effort before dispatch:
an unknown or conflicting identity blocks dispatch (Error).
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess

from oz import Error

ROUTE_FIELDS = ('adapter_hash', 'backend', 'model', 'effort', 'cli_version', 'environment_hash')
# Nonsecret variables an adapter reads. Anything else in the environment (tokens, keys) is never hashed.
ENV_KEYS = ('OZ_MODEL', 'OZ_EFFORT', 'OZ_CODEX_TIMEOUT')
NOT_APPLICABLE = 'not-applicable'


def canonical(value) -> str:
    """Amendment D6 canonical text; NaN and Infinity are rejected."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def worker_hash(route: dict) -> str:
    """SHA256 of the canonical route; the route must have exactly the six fields, each a nonempty string."""
    if (not isinstance(route, dict) or set(route) != set(ROUTE_FIELDS)
            or any(not isinstance(route[k], str) or not route[k] for k in ROUTE_FIELDS)):
        raise Error('route must have exactly ' + ', '.join(ROUTE_FIELDS) + ', each a nonempty string')
    return sha256_text(canonical(route))


def _load(adapter: Path) -> dict:
    try:
        spec = json.loads(Path(adapter).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise Error(f'cannot read adapter file {adapter}') from None
    if not isinstance(spec, dict) or not isinstance(spec.get('argv'), list) or not spec['argv'] \
            or any(not isinstance(a, str) for a in spec['argv']):
        raise Error(f'adapter file {adapter} must contain an argv list')
    return spec


def _declared_data(path: Path) -> list:
    """Data files a Python source declares as executable inputs: a module-level literal tuple or list
    OZ_ROUTE_DATA of paths relative to the source's directory (for example the pinned spec text a wrapper loads).
    Read from the syntax tree, never imported. A declared file that does not exist blocks the route (Error)."""
    try:
        tree = ast.parse(path.read_bytes())
    except (OSError, SyntaxError, ValueError):
        return []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'OZ_ROUTE_DATA'
                                                for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                raise Error(f'{path.name}: OZ_ROUTE_DATA must be a literal tuple or list of paths') from None
            if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) or not v for v in value):
                raise Error(f'{path.name}: OZ_ROUTE_DATA must be a literal tuple or list of paths')
            found = []
            for rel in value:
                item = (path.parent / rel).resolve()
                if not item.is_file():
                    raise Error(f'{path.name}: declared route data file {rel} does not exist')
                found.append(item)
            return found
    return []


def _local_imports(path: Path, seen: set) -> None:
    """Add to seen every sibling .py module the file imports (transitively) and every data file it declares in
    OZ_ROUTE_DATA, so a wrapper adapter hashes the adapter it imports and the pinned text it loads as well (for example
    claude_map_adapter.py imports the frozen claude_cli_adapter.py)."""
    if path.suffix != '.py':
        return
    for item in _declared_data(path):
        if item not in seen:
            seen.add(item)
            _local_imports(item, seen)
    try:
        tree = ast.parse(path.read_bytes())
    except (OSError, SyntaxError, ValueError):
        return
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name.split('.')[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.append(node.module.split('.')[0])
    for name in names:
        sibling = path.parent / (name + '.py')
        if sibling.is_file() and sibling.resolve() not in seen:
            seen.add(sibling.resolve())
            _local_imports(sibling.resolve(), seen)


def source_manifest(adapter: Path) -> list:
    """[[path, sha256 of the file bytes], ...] ordered by path, for the argv entries (after the program) that name an
    existing file relative to the adapter's directory, plus the sibling modules those Python files import (transitively)
    and the data files they declare in OZ_ROUTE_DATA. The path is relative to that directory (a file outside it keeps a
    relative path with ".." parts, so the hash does not depend on where the checkout is)."""
    adapter = Path(adapter).resolve()
    base = adapter.parent
    files = set()
    for arg in _load(adapter)['argv'][1:]:
        path = (base / arg)
        if path.is_file():
            files.add(path.resolve())
    for path in sorted(files):
        _local_imports(path, files)
    entries = {}
    for path in files:
        try:
            name = path.relative_to(base).as_posix()
        except ValueError:
            try:
                name = os.path.relpath(path, base).replace(os.sep, '/')
            except ValueError:
                name = path.as_posix()
        entries[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return [[name, entries[name]] for name in sorted(entries)]


def adapter_hash(adapter: Path) -> str:
    """SHA256 of the canonical adapter configuration plus the ordered source manifest."""
    return sha256_text(canonical({'config': _load(adapter), 'sources': source_manifest(adapter)}))


def probe(adapter: Path, *, model: str, effort: str, timeout: float = 60, run=subprocess.run) -> dict:
    """The adapter's own report of its effective identity (`<argv> --identity`; no model call). Raises Error when the
    adapter cannot report one: an identity that is not known blocks dispatch."""
    adapter = Path(adapter).resolve()
    argv = [*_load(adapter)['argv'], '--identity']
    env = dict(os.environ, OZ_MODEL=model, OZ_EFFORT=effort, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    try:
        done = run(argv, cwd=adapter.parent, env=env, capture_output=True, text=True, encoding='utf-8',
                   timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Error(f'route identity unknown: cannot run the adapter with --identity ({type(exc).__name__})') from None
    if done.returncode != 0:
        raise Error(f'route identity unknown: the adapter exited {done.returncode} on --identity: '
                    + (done.stderr or done.stdout).strip()[:300])
    try:
        report = json.loads(done.stdout)
    except ValueError:
        raise Error('route identity unknown: the adapter printed no JSON identity for --identity') from None
    if not isinstance(report, dict):
        raise Error('route identity unknown: the adapter identity is not a JSON object')
    return report


def reconcile(report: dict, *, model: str, effort: str) -> dict:
    """The effective {backend, model, effort, cli_version, flags} after comparing the adapter's report with the
    requested model and effort. Unknown or conflicting values raise Error. An adapter that says effort is not
    applicable gets the explicit value "not-applicable" (never a silent default)."""
    for key in ('backend', 'model', 'effort', 'cli_version'):
        if not isinstance(report.get(key), str) or not report[key].strip():
            raise Error(f'route identity unknown: the adapter reported no {key}')
    if report['cli_version'].startswith('unknown'):
        raise Error('route identity unknown: CLI version ' + report['cli_version'])
    if report['model'] != model:
        raise Error(f"route identity conflict: requested model {model!r} but the adapter would use {report['model']!r}")
    applicable = report.get('effort_applicable', True)
    if type(applicable) is not bool:
        raise Error('route identity unknown: effort_applicable must be true or false')
    if applicable and report['effort'] != effort:
        raise Error(f"route identity conflict: requested effort {effort!r} but the adapter would use "
                    f"{report['effort']!r}")
    flags = report.get('flags', [])
    if not isinstance(flags, list) or any(not isinstance(f, str) for f in flags):
        raise Error('route identity unknown: flags must be a list of strings')
    return {'backend': report['backend'], 'model': model, 'effort': effort if applicable else NOT_APPLICABLE,
            'cli_version': report['cli_version'], 'flags': flags}


def environment_hash(adapter: Path, flags: list, env=None) -> str:
    """SHA256 of the frozen nonsecret invocation configuration."""
    env = os.environ if env is None else env
    return sha256_text(canonical({'argv': _load(adapter)['argv'], 'flags': flags,
                                  'env': {k: env[k] for k in ENV_KEYS if k in env}}))


def build(adapter: Path, *, model: str, effort: str, run=subprocess.run, env=None) -> dict:
    """Probe, reconcile and hash. Returns {"route", "worker_hash", "do_route"}: do_route holds the fields oz_do's
    route option pins (adapter is the adapter_hash, so a changed adapter source is a different route)."""
    if not isinstance(model, str) or not model.strip() or not isinstance(effort, str) or not effort.strip():
        raise Error('model and effort are required and must be nonblank')
    effective = reconcile(probe(adapter, model=model, effort=effort, run=run), model=model, effort=effort)
    # The environment hash covers the variables the adapter will see: the requested model and effort included.
    seen = dict(os.environ if env is None else env, OZ_MODEL=model, OZ_EFFORT=effort)
    route = {'adapter_hash': adapter_hash(adapter), 'backend': effective['backend'], 'model': effective['model'],
             'effort': effective['effort'], 'cli_version': effective['cli_version'],
             'environment_hash': environment_hash(adapter, effective['flags'], seen)}
    return {'route': route, 'worker_hash': worker_hash(route),
            'do_route': {'adapter': route['adapter_hash'], 'model': route['model'], 'effort': route['effort'],
                         'cli_version': route['cli_version']}}
