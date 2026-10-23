"""The oz_manual example: the O1 workflow repair-handoff-20/v1 on its zero-token fixture route.

Windows-only. The workflow's checks run model-written Python in the Windows Job Object sandbox copied here from
bench/o1 (sandbox.py), which refuses when os.name != "nt". That sandbox is bench-grade confinement, not a security
boundary. Both packet sizes of this workflow, 1 and 4, are experimental labels, and packaging grants no qualification.

Standard library only; an empty or missing workspace is enough. Every file this example needs sits beside it: the
frozen request pack (repair-handoff-20-v1/), the registered operations and checks (workflow.py, sandbox.py,
sandbox_worker.py), and the fixture adapter with its stored replies (fixture_adapter.py, fixture/). Nothing is imported
from bench/. The adapter answers each job from a stored fixture reply, so no model is called and nothing is billed.

    python examples/oz_manual_o1/example.py --workspace DIR install
    python examples/oz_manual_o1/example.py --workspace DIR run
    python examples/oz_manual_o1/example.py --workspace DIR status
    python examples/oz_manual_o1/example.py --workspace DIR artifacts [--generation N]
    python examples/oz_manual_o1/example.py --workspace DIR revise     (ticket A revision 2 from the pack)
    python examples/oz_manual_o1/example.py --workspace DIR run --mutate-stale-a     (the O1 stale-A scenario)

Each command prints one JSON document on stdout and its notices on stderr. Exit codes: 0 done (run: delivered), 3 run
ended without delivering, 2 a named error (stderr names it), 86 a hard exit forced by OZ_FAULTS for a recovery drill
(for example OZ_FAULTS=worker.after_capture, then OZ_FAULTS=flow.publish.after_manifest, then a plain run).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (str(HERE), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import oz_fault  # noqa: E402
import oz_manual  # noqa: E402
import workflow as W  # noqa: E402
from oz import Error  # noqa: E402
from oz_batch import J, SYSTEM  # noqa: E402
from oz_flow import Settings  # noqa: E402
from oz_quota import Quota  # noqa: E402
from oz_reply import LANGUAGE, PROTOCOL  # noqa: E402
from oz_runner import read_capture  # noqa: E402
from oz_workspace import initialize  # noqa: E402

NAME = 'oz_manual_o1'
REQUEST_ID = 'manual-o1'
TARGET = 'repair_package'
NOTICES = ('route=fixture; model_calls=0; new_billed_tokens=0',
           'workflow=repair-handoff-20/v1; experimental_sizes=1,4',
           'platform=windows-only; sandbox=bench-grade confinement, not a security boundary')
PACK = W.FROZEN


def ndigest(path: Path) -> str:
    """SHA-256 with CRLF normalized to LF, so a checkout's line-ending conversion does not change identities."""
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def pack_digest() -> str:
    names = sorted(p for p in PACK.rglob('*.json'))
    return hashlib.sha256(J({p.relative_to(PACK).as_posix(): ndigest(p) for p in names}).encode('utf-8')).hexdigest()


def request(request_id: str = REQUEST_ID, deadline_seconds=None) -> dict:
    spec = W.spec()
    if deadline_seconds is None:
        deadline_seconds = spec['deadlines']['scenario_seconds']
    elif float(deadline_seconds).is_integer():
        deadline_seconds = int(deadline_seconds)
    return {'v': 'oz.flow/1', 'request_id': request_id, 'workflow': W.WORKFLOW_ID, 'workflow_digest': pack_digest(),
            'graph': W.graph(), 'effects': spec['effects'], 'deadline_seconds': deadline_seconds,
            'call_timeout_seconds': spec['deadlines']['call_timeout_seconds']}


def route() -> tuple:
    spec = W.spec()['fixture_route']
    script = HERE / 'fixture_adapter.py'
    adapter = f"argv:{J(['python', 'examples/oz_manual_o1/fixture_adapter.py'])};sha256:{ndigest(script)}"
    wire = hashlib.sha256(SYSTEM.encode('utf-8')).hexdigest()[:16]
    parser = f"{spec['parser']}@sha256:{ndigest(ROOT / 'oz_reply.py')[:16]};wire-H-sha256:{wire}"
    return {'effort': spec['effort'], 'cli_version': spec['cli_version'], 'adapter': adapter, 'parser': parser}, \
        spec['model']


def response_check(model: str):
    """The model that answered comes from the retained envelope; a missing identity or another model refuses the call."""
    def check(dispatch):
        capture = read_capture(dispatch['capture_dir'], dispatch['receipt'], dispatch['request_sha256'])
        try:
            envelope = json.loads(base64.b64decode(capture['envelope_b64']).decode('utf-8'))
        except (TypeError, KeyError, ValueError, UnicodeError):
            return 'model identity missing: no retained envelope'
        usage = envelope.get('modelUsage') if isinstance(envelope, dict) else None
        if not isinstance(usage, dict) or not usage:
            return 'model identity missing: envelope has no modelUsage'
        seen = sorted(usage)
        return None if seen == [model] else 'unexpected model(s): ' + ', '.join(seen)
    return check


def settings(workspace, *, prepare: bool = True, quota: bool = False) -> Settings:
    """The host-owned settings of one flow. prepare=False builds the same object without touching the disk (status and
    artifacts only look at the workspace path)."""
    ws = Path(workspace).resolve()
    spec = W.spec()
    fields, model = route()
    adapter = ws / 'adapter-fixture.json'
    if prepare:
        if not (ws / 'oz.json').exists():
            initialize(ws)
        (ws / 'fixture').mkdir(exist_ok=True)
        os.environ['OZ_FIXTURE_DIR'] = str(ws / 'fixture')
        adapter.write_text(json.dumps({'argv': [sys.executable, str(HERE / 'fixture_adapter.py')],
                                       'protocols': [PROTOCOL], 'languages': [LANGUAGE]}), encoding='utf-8')
    return Settings(workspace=ws, adapter=adapter, registry=W.registry(), checks_registry=W.CHECKS, route=fields,
                    model=model, memo_store=ws / 'memo.sqlite', namespace=f'fixture-{REQUEST_ID}',
                    quota=Quota(ws / 'quota.sqlite') if prepare and quota else None, budget=spec['allocation'],
                    budget_scope=ws, response_check=response_check(model),
                    packet_sizes=tuple(spec['packets']['sizes']),
                    experimental_sizes=tuple(spec['packets']['experimental_sizes']))


def invocations(workspace) -> int:
    path = Path(workspace) / 'fixture' / 'invocations.jsonl'
    return len(path.read_text(encoding='utf-8').splitlines()) if path.exists() else 0


def document(workspace, result: dict, before: int) -> dict:
    """The facade's result, untouched, beside what the fixture route did: the adapter invocations (the fixture's own
    log) and the usage its stored replies report, kept apart from the model calls and billed tokens, which are zero."""
    total = invocations(workspace)
    accounting = result.get('accounting') if isinstance(result, dict) else None
    return {'example': NAME,
            'fixture': {'route': 'fixture', 'model_calls': 0, 'new_billed_tokens': 0,
                        'fixture_invocations_total': total, 'fixture_invocations_this_call': total - before,
                        'capture_usage_tokens_reported': accounting['tokens_known'] if accounting else None},
            'result': result}


def stale_a_hook(request_id: str, s: Settings):
    """The O1 stale-A scenario: after the integration node commits, ticket A gets its revision 2 once."""
    fired = []

    def hook(_name):
        if not fired:
            fired.append(True)
            oz_manual.revise(request_id, s, 'A', (PACK / 'tickets' / 'A.rev2.json').read_bytes(),
                             reason='preregistered mutation stale')
    return oz_fault.on('flow.committed:integration', hook)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--request-id', default=REQUEST_ID)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('install', 'run'):
        p = sub.add_parser(name)
        p.add_argument('--deadline-seconds', type=float, default=None)
        if name == 'run':
            p.add_argument('--mutate-stale-a', action='store_true')
    p = sub.add_parser('revise')
    p.add_argument('--source', default='A')
    p.add_argument('--file', type=Path, default=PACK / 'tickets' / 'A.rev2.json')
    p.add_argument('--reason', default='ticket A revision 2')
    sub.add_parser('status')
    p = sub.add_parser('artifacts')
    p.add_argument('--target', default=TARGET)
    p.add_argument('--generation', type=int, default=None)
    args = parser.parse_args(argv)
    ws = args.workspace
    for line in NOTICES:
        print(line, file=sys.stderr, flush=True)
    try:
        if args.command in ('install', 'run') and os.name != 'nt':
            raise Error('PlatformUnsupported: the O1 checks run in the Windows Job Object sandbox; this example is '
                        'Windows-only')
        before = invocations(ws)
        if args.command == 'install':
            result = oz_manual.install(request(args.request_id, args.deadline_seconds), settings(ws))
        elif args.command == 'run':
            s = settings(ws, quota=True)
            remove = stale_a_hook(args.request_id, s) if args.mutate_stale_a else None
            try:
                result = oz_manual.run(request(args.request_id, args.deadline_seconds), s)
            finally:
                if remove:
                    remove()
                s.quota.close()
        elif args.command == 'revise':
            result = oz_manual.revise(args.request_id, settings(ws, prepare=False), args.source,
                                      args.file.read_bytes(), args.reason)
        elif args.command == 'status':
            result = oz_manual.status(args.request_id, settings(ws, prepare=False))
        else:
            result = oz_manual.artifacts(args.request_id, settings(ws, prepare=False), args.target, args.generation)
    except oz_manual.ArtifactsUnavailable as exc:
        print(f'error={type(exc).__name__}[{exc.code}]: {exc}', file=sys.stderr)
        return 2
    except Error as exc:
        print(f'error={type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(document(ws, result, before), ensure_ascii=False, sort_keys=True))
    return 3 if args.command == 'run' and result['status'] != 'delivered' else 0


if __name__ == '__main__':
    sys.exit(main())
