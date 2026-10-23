"""Step 3 driver: the O1 suite (repair-handoff-20/v1) on a Haiku 5.5 route, through a derived freeze.

The O1 harness (o1.py, workflow.py) and its frozen pack are not edited. This driver loads the O1 modules, replaces the
route in the in-memory workflow spec with the overlay in repair-handoff-20-haiku/route.json (model and alias_map
only), swaps in a freeze check for the derived record (repair-handoff-20-haiku/freeze.json: the base O1 freeze must
still hold, the derived spec may differ from the base spec only at route.model and route.alias_map, and every pinned
overlay, code and design file must be unchanged), and hands every other command to o1.main. The interrupt scenario
re-runs the driver, not o1.py, in its child processes, so every process of a suite sees the same route.

    python bench/o1/step3_haiku.py freeze [--write]      derived freeze: verify (or write) the record
    python bench/o1/step3_haiku.py route                 the effective live route (zero calls)
    python bench/o1/step3_haiku.py control-match         zero-call control-match checks against the Sonnet control
    python bench/o1/step3_haiku.py labels                zero-call check: Haiku dispatches at sizes 4 and 1 are experimental
    python bench/o1/step3_haiku.py dry --workspace DIR   the O1 dry gate under the derived route (fixture adapter)
    python bench/o1/step3_haiku.py live --workspace DIR --prefix P --quota-before PCT    one paid suite (guarded)
    python bench/o1/step3_haiku.py quota-after --workspace DIR --prefix P --percent PCT  record the weekly figure after

See docs/design/step3-haiku-2026-10-23/plan-frozen.md.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT), str(HERE), str(HERE / 'evaluator')):
    if p not in sys.path:
        sys.path.insert(0, p)

import o1 as O  # noqa: E402
from oz import Error  # noqa: E402
from oz_batch import J  # noqa: E402

W = O.W
PACK = HERE / 'repair-handoff-20-haiku'
ROUTE_FILE = PACK / 'route.json'
FREEZE_FILE = PACK / 'freeze.json'
CONTROL_FILE = PACK / 'control-freeze-32333561.json'
DRIVER = HERE / 'step3_haiku.py'
ROUTE_NAME = 'bench/o1/repair-handoff-20-haiku/route.json'
CONTROL_NAME = 'bench/o1/repair-handoff-20-haiku/control-freeze-32333561.json'
CODE = ('bench/o1/step3_haiku.py', 'bench/o1/step3_checks.py', 'bench/o1/step3_replay_adapter.py')
DESIGN_DIR = 'docs/design/step3-haiku-2026-10-23'
GROUPS = ('base', 'overlay', 'derived', 'code', 'design')
ALLOWED = ('route.model', 'route.alias_map')
START_BELOW = 55.0
STOP_AT = 56.0
HARD_STOP = 59.0
_ORIGINAL_FREEZE = O.freeze


def base_freeze() -> dict:
    """The O1 freeze check exactly as o1.py defines it (never the derived one)."""
    return _ORIGINAL_FREEZE()


def base_spec() -> dict:
    """workflow.json as the frozen pack holds it on disk, whatever the in-memory spec currently is."""
    return json.loads((W.FROZEN / 'workflow.json').read_text(encoding='utf-8'))


def overlay(path: Path = ROUTE_FILE) -> dict:
    """{'model', 'alias_map'} from the overlay file; anything beyond route.model and route.alias_map is refused."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) - {'route', 'evidence', 'label'} or 'route' not in data:
        raise Error('the route overlay holds route (and descriptive evidence, label) only')
    route = data['route']
    if not isinstance(route, dict) or set(route) != {'model', 'alias_map'}:
        raise Error('the route overlay changes exactly route.model and route.alias_map')
    model, alias = route['model'], route['alias_map']
    if not isinstance(model, str) or not model.strip():
        raise Error('route.model must be a nonblank string')
    if (not isinstance(alias, dict) or not alias
            or any(not isinstance(k, str) or not isinstance(v, str) or not k or not v for k, v in alias.items())):
        raise Error('route.alias_map maps reported model ids to model ids')
    return {'model': model, 'alias_map': dict(alias)}


def changed_paths(a, b, prefix: str = '', depth: int = 0) -> list:
    """Dotted paths where two specs differ, two levels deep (route.model, route.alias_map); canonical-JSON strict."""
    if isinstance(a, dict) and isinstance(b, dict) and depth < 2:
        out = []
        for key in sorted(set(a) | set(b)):
            path = f'{prefix}.{key}' if prefix else key
            if key not in a or key not in b:
                out.append(path)
            else:
                out += changed_paths(a[key], b[key], path, depth + 1)
        return out
    return [] if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else [prefix]


def derive(base: dict, ov: dict) -> dict:
    """The derived spec: the base with route.model and route.alias_map replaced; nothing else may differ."""
    out = copy.deepcopy(base)
    out['route']['model'] = ov['model']
    out['route']['alias_map'] = dict(ov['alias_map'])
    extra = [p for p in changed_paths(base, out) if p not in ALLOWED]
    if extra:
        raise Error('the derived spec differs from the base outside route.model and route.alias_map: ' + ', '.join(extra))
    return out


def _design() -> dict:
    return {p.relative_to(ROOT).as_posix(): O.ndigest(p) for p in sorted((ROOT / DESIGN_DIR).glob('0[123]-*.md'))}


def current(route_path: Path = ROUTE_FILE, control_path: Path = CONTROL_FILE) -> dict:
    ov = overlay(route_path)
    base = base_spec()
    derived = derive(base, ov)
    base_result = base_freeze()
    return {'base': {'freeze': O.FREEZE_FILE.relative_to(ROOT).as_posix(), 'digest': base_result['digest'],
                     'file_sha256': O.ndigest(O.FREEZE_FILE),
                     'workflow_sha256': O.ndigest(W.FROZEN / 'workflow.json')},
            'overlay': {ROUTE_NAME: O.ndigest(route_path), CONTROL_NAME: O.ndigest(control_path)},
            'derived': {'model': derived['route']['model'], 'alias_map': derived['route']['alias_map'],
                        'changed': changed_paths(base, derived),
                        'workflow_sha256': hashlib.sha256(J(derived).encode('utf-8')).hexdigest()},
            'code': {c: O.ndigest(ROOT / c) for c in CODE},
            'design': _design()}


def _digest_of(record: dict) -> str:
    return hashlib.sha256(J({k: record.get(k, {}) for k in GROUPS}).encode('utf-8')).hexdigest()


def derived_freeze(write: bool = False, record_path: Path = FREEZE_FILE, route_path: Path = ROUTE_FILE,
                   control_path: Path = CONTROL_FILE) -> dict:
    """G0 for the derived suite. frozen is true only when the base O1 freeze holds, the derived spec differs from the
    base at route.model and route.alias_map alone, and every pinned part matches the stored record."""
    base = base_freeze()
    problems = []
    if not base['frozen']:
        problems.append('the base freeze does not hold: ' + '; '.join(base['problems'][:5]))
    try:
        now = current(route_path, control_path)
    except Error as exc:
        return {'frozen': False, 'digest': None, 'current_digest': None, 'base_digest': base['digest'],
                'problems': problems + [str(exc)]}
    now['digest'] = _digest_of(now)
    if write:
        if problems:
            raise Error('cannot freeze: ' + '; '.join(problems))
        Path(record_path).write_text(json.dumps(now, indent=1) + '\n', encoding='utf-8', newline='\n')
        return {'frozen': True, 'digest': now['digest'], 'current_digest': now['digest'],
                'base_digest': base['digest'], 'problems': []}
    stored = json.loads(Path(record_path).read_text(encoding='utf-8')) if Path(record_path).exists() else {}
    if stored.get('digest') != _digest_of(stored):
        problems.append('the stored file maps do not hash to the stored derived digest')
    if stored.get('base', {}).get('digest') != base['digest']:
        problems.append('the stored base digest is not the O1 freeze digest')
    for group in GROUPS:
        for name, value in now[group].items():
            if stored.get(group, {}).get(name) != value:
                problems.append(f'{group}.{name} changed since the derived freeze')
        for name in set(stored.get(group, {})) - set(now[group]):
            problems.append(f'{group}.{name} missing')
    return {'frozen': not problems, 'digest': stored.get('digest'), 'current_digest': now['digest'],
            'base_digest': base['digest'], 'problems': problems}


def _o1_freeze(write: bool = False) -> dict:
    return derived_freeze(write=write)


_MISSING = object()


@contextlib.contextmanager
def applied(route_path: Path = ROUTE_FILE):
    """Within the block o1 sees the derived spec and the derived freeze, and its interrupt scenario re-runs this
    driver. Everything is restored on exit; nothing on disk changes."""
    derived = derive(base_spec(), overlay(route_path))
    saved = (O.freeze, O.__file__, W._CACHE.get('workflow.json', _MISSING))
    W._CACHE['workflow.json'] = derived
    O.freeze = _o1_freeze
    O.__file__ = str(DRIVER)
    try:
        yield derived
    finally:
        O.freeze, O.__file__ = saved[0], saved[1]
        if saved[2] is _MISSING:
            W._CACHE.pop('workflow.json', None)
        else:
            W._CACHE['workflow.json'] = saved[2]


def route_info() -> dict:
    with applied() as derived:
        fields, model = O.route('live')
        freeze = O.freeze()
        return {'model': model, 'alias_map': derived['route']['alias_map'], 'route_fields': fields,
                'frozen': freeze['frozen'], 'digest': freeze['digest'], 'base_digest': freeze['base_digest'],
                'problems': freeze['problems'], 'experimental_sizes': list(derived['packets']['experimental_sizes']),
                'packet_sizes': list(derived['packets']['sizes']), 'cli_version': derived['route']['cli_version'],
                'effort': derived['route']['effort']}


def _percent(text) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _quota_file(ws: Path, prefix: str) -> Path:
    return ws / f'quota-{prefix}.json'


def live(argv: list) -> int:
    parser = argparse.ArgumentParser(prog='step3_haiku.py live')
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--prefix', default='hk1')
    parser.add_argument('--quota-before')
    args = parser.parse_args(argv)
    if not os.environ.get(O.LIVE_ENV):
        print(f'live runs paid calls: set {O.LIVE_ENV}=1 to proceed', file=sys.stderr)
        return 2
    before = _percent(args.quota_before)
    if before is None or before >= START_BELOW:
        print(f'start only with the weekly quota figure read just now and below {START_BELOW:g}% '
              f'(--quota-before); nothing was launched', file=sys.stderr)
        return 2
    ws = args.workspace.resolve()
    with applied():
        refusal = O.live_refusal(O.freeze(), O.cli_version()) or O.fresh_refusal(ws)
        if refusal:
            print(json.dumps({'blocker': refusal}, indent=1))
            return 3
        O.prepare(ws, 'live')
        _quota_file(ws, args.prefix).write_text(json.dumps(
            {'prefix': args.prefix, 'before_percent': before, 'recorded_at': time.time(),
             'rule': {'start_below': START_BELOW, 'incomplete_at': STOP_AT, 'hard_stop_at': HARD_STOP}}, indent=1),
            encoding='utf-8')
        report = O.suite(ws, 'live', args.prefix)
    print(json.dumps({k: report.get(k) for k in ('gate', 'pass', 'g3c', 'totals', 'blocker')}, indent=1, default=str))
    return 0 if report.get('pass') else 3


def quota_after(argv: list) -> int:
    parser = argparse.ArgumentParser(prog='step3_haiku.py quota-after')
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--prefix', default='hk1')
    parser.add_argument('--percent', required=True)
    args = parser.parse_args(argv)
    after = _percent(args.percent)
    path = _quota_file(args.workspace, args.prefix)
    if after is None or not path.exists():
        print('quota-after needs a weekly figure and the record written by live', file=sys.stderr)
        return 2
    record = json.loads(path.read_text(encoding='utf-8'))
    record['after_percent'] = after
    record['status'] = 'hard_stop_59' if after >= HARD_STOP else 'stop_reached_56' if after >= STOP_AT else 'ok'
    record['after_recorded_at'] = time.time()
    path.write_text(json.dumps(record, indent=1), encoding='utf-8')
    print(json.dumps(record, indent=1))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else None
    if command == 'route':
        print(json.dumps(route_info(), indent=1))
        return 0
    if command == 'live':
        return live(argv[1:])
    if command == 'quota-after':
        return quota_after(argv[1:])
    if command in ('control-match', 'labels'):
        import step3_checks as C
        parser = argparse.ArgumentParser(prog=f'step3_haiku.py {command}')
        parser.add_argument('--out', type=Path)
        args = parser.parse_args(argv[1:])
        with tempfile.TemporaryDirectory(prefix='s3-') as tmp:
            report = C.control_match(Path(tmp)) if command == 'control-match' else C.label_check(Path(tmp))
        text = json.dumps(report, indent=1, default=str)
        if args.out:
            args.out.write_text(text + '\n', encoding='utf-8')
        print(text)
        return 0 if report.get('all_match', report.get('pass')) else 1
    with applied():
        return O.main(argv)


if __name__ == '__main__':
    sys.exit(main())
