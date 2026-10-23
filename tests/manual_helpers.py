"""A host-only flow for tests/test_oz_manual.py: three host nodes, one local publication, no model and no adapter.

    doc    host.read   imports the source file `doc` (once) and returns its text and revision
    slow   host.wait   returns the doc; when the request names gate_file it signals entered_file and waits for the gate
    pub    host.pub    publishes out.txt and notes.txt under the usual deliveries/<request>/pub-g<n> destination

Run as a script (`manual_helpers.py WORKSPACE SOURCE_DIR run|status [--gate F --entered F]`) so a test can start a
second process, hold a run open, or hard-kill one with OZ_FAULTS.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oz_flow import HostError, HostOp, Settings  # noqa: E402
import oz_manual  # noqa: E402


def op_read(inputs, ctx):
    name = inputs['name']
    if name == 'refuse':
        raise HostError('this source is refused')
    s = ctx.read_source(name, Path(ctx.request['source_dir']) / (name + '.txt'))
    return {'name': name, 'revision': s['revision'], 'text': s['bytes'].decode('utf-8')}


def op_wait(inputs, ctx):
    gate = ctx.request.get('gate_file')
    if gate:
        Path(ctx.request['entered_file']).write_text('in', encoding='utf-8')
        end = time.time() + 60
        while not Path(gate).exists() and time.time() < end:
            time.sleep(0.05)
    return inputs['doc']


def op_pub(inputs, ctx):
    doc = inputs['doc']
    return {'files': {'out.txt': doc['text'].upper() + '\n', 'notes.txt': f"revision {doc['revision']}\n"}}


def registry() -> dict:
    return {'host.read': HostOp('host.read', 1, frozenset({'name'}), op_read),
            'host.wait': HostOp('host.wait', 1, frozenset({'doc'}), op_wait),
            'host.pub': HostOp('host.pub', 1, frozenset({'doc'}), op_pub, effect='local_publish')}


def request(source_dir, request_id='h1', **extra) -> dict:
    graph = {'v': 1, 'base': 0, 'outputs': {'package': 'pub'}, 'nodes': [
        {'id': 'doc', 'op': 'host.read', 'in': {'name': {'lit': 'doc'}}, 'after': []},
        {'id': 'slow', 'op': 'host.wait', 'in': {'doc': {'node': 'doc'}}, 'after': []},
        {'id': 'pub', 'op': 'host.pub', 'in': {'doc': {'node': 'slow'}}, 'after': []}]}
    return dict({'v': 'oz.flow/1', 'request_id': request_id, 'workflow': 'manual-host-test', 'graph': graph,
                 'effects': ['local_publish'], 'deadline_seconds': 3600, 'source_dir': str(source_dir)}, **extra)


def settings(workspace) -> Settings:
    return Settings(workspace=Path(workspace), adapter=None, registry=registry(), checks_registry={}, route={},
                    model='none')


def main(argv):
    workspace, source_dir, command, *rest = argv
    extra = {}
    if '--gate' in rest:
        extra = {'gate_file': rest[rest.index('--gate') + 1], 'entered_file': rest[rest.index('--entered') + 1]}
    req = request(source_dir, **extra)
    try:
        if command == 'run':
            result = oz_manual.run(req, settings(workspace))
        else:
            result = oz_manual.status(req['request_id'], settings(workspace))
    except oz_manual.ManualError as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get('status') == 'delivered' else 3


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
