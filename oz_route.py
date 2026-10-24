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

Launch verification (council 3, B11): build(env=...) probes in that environment; the source manifest follows every
import (absolute, relative, package and parent package) of every Python file in argv inside the repo, external modules
are recorded by name and version, an import that cannot be resolved (and is not declared "external:<module>" in
OZ_ROUTE_DATA) raises Error; environment_hash covers the sha256 of the resolved interpreter and claude/codex CLI;
verify(frozen, adapter_config, env) recomputes in the real launch environment and raises with a field diff on mismatch.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from oz import Error

AKOR_ROOT = Path(__file__).resolve().parent
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


EXTERNAL_PREFIX = 'external:'
KNOWN_CLIS = ('claude', 'codex')


def _declarations(path: Path):
    """(data files, external module names) a Python source declares in its module-level literal tuple or list
    OZ_ROUTE_DATA. A plain entry is a path relative to the source's directory (for example the pinned spec text a
    wrapper loads) and must exist. An entry "external:<module>" declares a module that is deliberately not resolved
    (an optional or dynamically loaded dependency); it is recorded by name and version where one can be found.
    Read from the syntax tree, never imported."""
    try:
        tree = ast.parse(path.read_bytes())
    except (OSError, SyntaxError, ValueError):
        return [], []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'OZ_ROUTE_DATA'
                                                for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                raise Error(f'{path.name}: OZ_ROUTE_DATA must be a literal tuple or list of paths') from None
            if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) or not v for v in value):
                raise Error(f'{path.name}: OZ_ROUTE_DATA must be a literal tuple or list of paths')
            found, external = [], []
            for rel in value:
                if rel.startswith(EXTERNAL_PREFIX):
                    if not rel[len(EXTERNAL_PREFIX):].strip():
                        raise Error(f'{path.name}: OZ_ROUTE_DATA entry {rel!r} names no module')
                    external.append(rel[len(EXTERNAL_PREFIX):].strip().split('.')[0])
                    continue
                item = (path.parent / rel).resolve()
                if not item.is_file():
                    raise Error(f'{path.name}: declared route data file {rel} does not exist')
                found.append(item)
            return found, external
    return [], []


def _declared_data(path: Path) -> list:
    return _declarations(path)[0]


def _repo_root(start: Path):
    """The nearest ancestor (or start) holding .git or pyproject.toml, else None."""
    for cand in (start, *start.parents):
        if (cand / '.git').exists() or (cand / 'pyproject.toml').is_file():
            return cand
    return None


def _distribution(top: str):
    """(distribution name, version) of the installed third-party package providing top-level module top, or None."""
    try:
        from importlib import metadata
        names = metadata.packages_distributions().get(top)
        if names:
            name = sorted(names)[0]
            return name, metadata.version(name)
    except Exception:  # metadata trouble means unresolved, never a crash
        return None
    return None


def _external(top: str, declared: bool):
    """[name, kind, version] for a module outside the repo, or None when it cannot be resolved."""
    stdlib = getattr(sys, 'stdlib_module_names', None)
    if top in sys.builtin_module_names or (stdlib is not None and top in stdlib):
        return [top, 'stdlib', 'stdlib']
    dist = _distribution(top)
    if dist:
        return [top, 'third-party', f'{dist[0]}=={dist[1]}']
    if declared:
        return [top, 'declared-external', 'unversioned']
    return None


def _module_file(root: Path, parts: list):
    """(files, complete): the files that importing the dotted module parts from root executes (package __init__ files on
    the way and the module itself). Empty files and complete False when the first part is not under root."""
    files, cur = [], root
    for i, part in enumerate(parts):
        if (cur / part / '__init__.py').is_file():
            files.append(cur / part / '__init__.py')
            cur = cur / part
        elif (cur / (part + '.py')).is_file():
            files.append(cur / (part + '.py'))
            return files, i == len(parts) - 1
        elif (cur / part).is_dir():
            cur = cur / part  # namespace package: no file to hash
        else:
            return (files, False) if i else ([], False)
    return files, True


def _scan(adapter: Path):
    """(files, externals) reached from every Python file in the adapter argv: absolute, relative, package and parent
    package imports followed transitively inside the repo, plus declared data files. Stdlib and third-party modules go
    to externals by name and version. An import that is neither local nor external nor declared raises Error."""
    adapter = Path(adapter).resolve()
    base = adapter.parent
    repo = _repo_root(base)
    files = set()
    for arg in _load(adapter)['argv'][1:]:
        path = base / arg
        if path.is_file():
            files.add(path.resolve())
    externals, work, done = {}, sorted(files), set()

    def add(path: Path):
        path = path.resolve()
        files.add(path)
        if path not in done:
            work.append(path)

    def add_subs(pkg: Path, subs: list):
        for sub in subs:
            got, ok = _module_file(pkg, [sub])
            if ok:
                for f in got:
                    add(f)

    while work:
        path = work.pop()
        if path in done:
            continue
        done.add(path)
        if path.suffix != '.py':
            continue
        for parent in path.parents:  # a file inside a package executes the package __init__ files above it
            init = parent / '__init__.py'
            if not init.is_file():
                break
            add(init)
        data, declared = _declarations(path)
        for item in data:
            add(item)
        try:
            tree = ast.parse(path.read_bytes())
        except (OSError, SyntaxError, ValueError) as exc:
            raise Error(f'{path.name}: cannot parse the source for the route manifest ({type(exc).__name__})') from None
        # AKOR's own checkout (and examples/, which oz_host puts on sys.path) are roots too, so an adapter outside the
        # repo may import AKOR modules such as oz_map.
        roots = [r for r in dict.fromkeys((path.parent, base, repo, AKOR_ROOT, AKOR_ROOT / 'examples')) if r is not None]
        for node in ast.walk(tree):
            requests = []  # (dotted parts, relative level, names that may be submodules)
            if isinstance(node, ast.Import):
                requests = [(alias.name.split('.'), 0, []) for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                requests = [((node.module or '').split('.') if node.module else [], node.level,
                             [alias.name for alias in node.names if alias.name != '*'])]
            for parts, level, subs in requests:
                label = '.' * level + '.'.join(parts)
                if level:
                    anchor = path.parent
                    for _ in range(level - 1):
                        anchor = anchor.parent
                    found, complete = _module_file(anchor, parts) if parts else ([], True)
                    if not parts and (anchor / '__init__.py').is_file():
                        found = [anchor / '__init__.py']
                    if not complete:
                        raise Error(f'{path.name}: unresolved relative import {label!r}; the route cannot be closed')
                    for f in found:
                        add(f)
                    add_subs(anchor.joinpath(*parts), subs)
                    continue
                local = None
                for root in roots:
                    got, complete = _module_file(root, parts)
                    if got or complete:
                        local = (root, got, complete)
                        break
                if local:
                    root, got, complete = local
                    if not complete:
                        raise Error(f'{path.name}: unresolved import {label!r}; the route cannot be closed')
                    for f in got:
                        add(f)
                    add_subs(root.joinpath(*parts), subs)
                    continue
                top = parts[0]
                entry = _external(top, top in declared)
                if entry is None:
                    raise Error(f'{path.name}: unresolved import {label!r}: not in the repo, not stdlib, not an '
                                f'installed package; declare "external:{top}" in OZ_ROUTE_DATA or fix the import')
                externals[top] = entry
    return files, externals


def source_manifest(adapter: Path) -> list:
    """[[path, sha256 of the file bytes], ...] ordered by path, for the argv entries (after the program) that name an
    existing file relative to the adapter's directory, plus every repo file those Python files import (absolute,
    relative, package __init__ and parent package, transitively) and the data files they declare in OZ_ROUTE_DATA. An
    import that cannot be resolved raises Error. The path is relative to the adapter's directory (a file outside it keeps
    a relative path with ".." parts, so the hash does not depend on where the checkout is)."""
    base = Path(adapter).resolve().parent
    files, _ = _scan(adapter)
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


def external_manifest(adapter: Path) -> list:
    """[[module, kind, version], ...] sorted: stdlib, third-party (distribution==version) and declared-external modules
    the adapter's Python sources import."""
    externals = _scan(adapter)[1]
    return [externals[k] for k in sorted(externals)]


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _which(name: str, env, base: Path):
    if os.sep in name or '/' in name or (os.altsep and os.altsep in name):
        cand = Path(name) if Path(name).is_absolute() else base / name
        return str(cand) if cand.is_file() else None
    return shutil.which(name, path=env.get('PATH'))


def executables(adapter: Path, backend=None, env=None) -> list:
    """[{"role", "path", "name", "sha256"}, ...]: the program of argv[0] (the interpreter) and, for a claude or codex
    backend, that CLI, each resolved with shutil.which in the given environment. One that is missing blocks launch (Error)."""
    adapter = Path(adapter).resolve()
    env = os.environ if env is None else env
    wanted = [('program', _load(adapter)['argv'][0])]
    if backend in KNOWN_CLIS:
        wanted.append(('backend-cli', backend))
    found = []
    for role, name in wanted:
        path = _which(name, env, adapter.parent)
        if not path:
            raise Error(f'route executable not found: {role} {name!r} is not on the launch PATH')
        real = Path(path).resolve()
        found.append({'role': role, 'path': real.as_posix(), 'name': real.name.lower(), 'sha256': _file_sha256(real)})
    return found


def adapter_hash(adapter: Path) -> str:
    """SHA256 of the canonical adapter configuration plus the ordered source manifest and the external module list."""
    return sha256_text(canonical({'config': _load(adapter), 'sources': source_manifest(adapter),
                                  'externals': external_manifest(adapter)}))


def _launch_env(env, **extra) -> dict:
    """The environment the adapter really sees: the given one (os.environ when None) plus the overrides. On Windows
    SYSTEMROOT is carried over when absent, because Python cannot start without it."""
    seen = dict(os.environ if env is None else env, **extra)
    if os.name == 'nt' and 'SYSTEMROOT' not in seen and 'SYSTEMROOT' in os.environ:
        seen['SYSTEMROOT'] = os.environ['SYSTEMROOT']
    return seen


def probe(adapter: Path, *, model: str, effort: str, timeout: float = 60, run=subprocess.run, env=None) -> dict:
    """The adapter's own report of its effective identity (`<argv> --identity`; no model call). Raises Error when the
    adapter cannot report one: an identity that is not known blocks dispatch."""
    adapter = Path(adapter).resolve()
    argv = [*_load(adapter)['argv'], '--identity']
    env = _launch_env(env, OZ_MODEL=model, OZ_EFFORT=effort, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
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


def environment_hash(adapter: Path, flags: list, env=None, backend=None) -> str:
    """SHA256 of the frozen nonsecret invocation configuration: argv, flags, the nonsecret OZ_* variables, and the name
    and sha256 of the resolved program (interpreter) and, for a claude or codex backend, the CLI executable. The
    executable paths are reported by executables() but are not hashed, so the hash is stable across checkouts."""
    env = os.environ if env is None else env
    exes = [{k: e[k] for k in ('role', 'name', 'sha256')} for e in executables(adapter, backend, env)]
    return sha256_text(canonical({'argv': _load(adapter)['argv'], 'flags': flags, 'executables': exes,
                                  'env': {k: env[k] for k in ENV_KEYS if k in env}}))


def build(adapter: Path, *, model: str, effort: str, run=subprocess.run, env=None) -> dict:
    """Probe (in the given environment), reconcile and hash. Returns {"route", "worker_hash", "do_route", "launch"}.
    do_route holds the fields oz_do's route option pins (adapter is the adapter_hash, so a changed adapter source is a
    different route). launch is the readable snapshot behind the hashes (sources, externals, executables with paths,
    flags, nonsecret env) that verify() uses to name what changed."""
    if not isinstance(model, str) or not model.strip() or not isinstance(effort, str) or not effort.strip():
        raise Error('model and effort are required and must be nonblank')
    seen = _launch_env(env, OZ_MODEL=model, OZ_EFFORT=effort)
    source_hash = adapter_hash(adapter)  # an unresolved dependency blocks before anything is run
    effective = reconcile(probe(adapter, model=model, effort=effort, run=run, env=env), model=model, effort=effort)
    exes = executables(adapter, effective['backend'], seen)
    route = {'adapter_hash': source_hash, 'backend': effective['backend'], 'model': effective['model'],
             'effort': effective['effort'], 'cli_version': effective['cli_version'],
             'environment_hash': environment_hash(adapter, effective['flags'], seen, effective['backend'])}
    launch = {'sources': source_manifest(adapter), 'externals': external_manifest(adapter), 'executables': exes,
              'flags': effective['flags'], 'env': {k: seen[k] for k in ENV_KEYS if k in seen}}
    return {'route': route, 'worker_hash': worker_hash(route), 'launch': launch,
            'do_route': {'adapter': route['adapter_hash'], 'model': route['model'], 'effort': route['effort'],
                         'cli_version': route['cli_version']}}


def _diff(label: str, old, new) -> list:
    if old == new:
        return []
    if isinstance(old, list) and isinstance(new, list) and all(isinstance(x, (list, dict)) for x in old + new):
        def key(x):
            return x.get('role') if isinstance(x, dict) else x[0]
        a, b = {key(x): x for x in old}, {key(x): x for x in new}
        return [f'{label} {k}: frozen {a.get(k)!r}, now {b.get(k)!r}'
                for k in sorted(set(a) | set(b), key=str) if a.get(k) != b.get(k)]
    return [f'{label}: frozen {old!r}, now {new!r}']


def verify(frozen_worker_hash, adapter_config, env=None, *, run=subprocess.run) -> dict:
    """Recompute the route in the real launch environment and require it to equal the frozen worker hash; return the
    recomputed route. frozen_worker_hash is the hash string, or a dict {"worker_hash", "route"?, "launch"?} (what build()
    returned): with route and launch the Error names every field and component that changed, with the hash alone it
    prints the recomputed route. adapter_config is the adapter file path, or {"adapter", "model"?, "effort"?}; model and
    effort default to env OZ_MODEL and OZ_EFFORT. An unresolved dependency, a missing executable or an unknown identity
    raises Error before any comparison, so launch is blocked."""
    frozen = frozen_worker_hash if isinstance(frozen_worker_hash, dict) else {'worker_hash': frozen_worker_hash}
    expected = frozen.get('worker_hash')
    if not isinstance(expected, str) or not expected:
        raise Error('verify needs the frozen worker hash')
    config = adapter_config if isinstance(adapter_config, dict) else {'adapter': adapter_config}
    if config.get('adapter') is None:
        raise Error('verify needs the adapter file')
    source = os.environ if env is None else env
    model, effort = config.get('model', source.get('OZ_MODEL')), config.get('effort', source.get('OZ_EFFORT'))
    built = build(Path(config['adapter']), model=model, effort=effort, run=run, env=env)
    if built['worker_hash'] == expected:
        return built['route']
    lines = []
    if isinstance(frozen.get('route'), dict):
        for field in ROUTE_FIELDS:
            lines += _diff(field, frozen['route'].get(field), built['route'][field])
    if isinstance(frozen.get('launch'), dict):
        for part in ('sources', 'externals', 'executables', 'flags', 'env'):
            lines += _diff(part, frozen['launch'].get(part), built['launch'][part])
    if not lines:
        lines = ['no frozen route was supplied, so the changed fields cannot be named; recomputed route '
                 + canonical(built['route'])]
    raise Error(f"worker route mismatch: frozen {expected[:12]}, recomputed {built['worker_hash'][:12]}; "
                + '; '.join(lines))
