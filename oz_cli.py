"""Offline command line adapter for portable OZ channel manifests."""
import argparse
import json
from pathlib import Path
import sys
import sqlite3
import uuid

from oz import Channel, Error
from oz_batch import render
from oz_do import do
from oz_workspace import Workspace, channel_from_files, demo, initialize, read_utf8
from oz_worker import process_host


def read_json(path):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise Error('duplicate JSON key')
            value[key] = item
        return value
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version', version='akor-protocol 0.9.0; OZ/9 (OZ/1 atoms, OZ/2 host macros)')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ['decode', 'pack', 'prompt']:
        p = sub.add_parser(command)
        p.add_argument('--channel', type=Path, required=True, help='JSON channel snapshot')
        if command == 'decode':
            p.add_argument('frame')
        if command == 'pack':
            p.add_argument('--messages', type=Path, required=True, help='JSON [[id,frame],...]')
            p.add_argument('--encoding', action='append', help='tiktoken encoding; repeat for multiple targets')
            p.add_argument('--max-tokens', type=int)
            p.add_argument('--context', choices=['needed'], default='needed',
                           help='needed: only referenced context (full is gone with the c table)')
    for command in ['init', 'demo']:
        p = sub.add_parser(command, help='Create a local workspace' if command == 'init' else 'Run a model-free end-to-end demo')
        p.add_argument('directory', type=Path)
        if command == 'init':
            p.add_argument('--channel', type=Path, help='Optional existing channel manifest')
            p.add_argument('--goal', help='Create a real task from a goal and source file')
            p.add_argument('--source', type=Path)
            p.add_argument('--kind', choices=['source', 'patch'], default='source')
            p.add_argument('--procedure', type=Path, help='Optional UTF-8 test procedure description')
    p = sub.add_parser('do', help='Run one bounded fan-out request and print one compact JSON result')
    p.add_argument('request', nargs='?', default='-', help='Request JSON file; - or omitted reads stdin')
    p.add_argument('--workspace', type=Path, default=Path('.'), help='Directory containing oz.json')
    p.add_argument('--adapter', type=Path, required=True, help='Explicit JSON file containing an argv list')
    p.add_argument('--allow', type=Path, help='Directory reference paths must stay inside (default: workspace)')
    for command in ['send', 'plan', 'run', 'events', 'status', 'inspect', 'retry', 'channel-add']:
        p = sub.add_parser(command)
        p.add_argument('--workspace', type=Path, default=Path('.'), help='Directory containing oz.json')
        if command in {'send', 'plan', 'run', 'events'}:
            p.add_argument('--to', default='worker', help='Channel alias')
        if command == 'send':
            p.add_argument('frame', nargs='?')
            p.add_argument('--file', type=Path, help='Send UTF-8 file as literal data')
            p.add_argument('--id', help='Reuse for retries; generated when omitted')
            p.add_argument('--after', action='append', default=[])
            p.add_argument('--max-attempts', type=int, default=2)
        if command in {'plan', 'run'}:
            p.add_argument('--max-tokens', type=int)
            p.add_argument('--context', choices=['needed'], default='needed',
                           help='needed: only referenced context (full is gone with the c table)')
        if command == 'plan':
            p.add_argument('--show-prompt', action='store_true')
        if command == 'run':
            p.add_argument('--adapter', type=Path, required=True, help='Explicit JSON file containing an argv list')
            p.add_argument('--max-calls', type=int, default=1)
            p.add_argument('--timeout', type=float, default=120)
            p.add_argument('--min-batch', type=int, default=1,
                           help='Wait for this many ready jobs before calling (fewer, larger calls)')
            p.add_argument('--max-wait', type=float, default=0,
                           help='Seconds the oldest ready job may wait for --min-batch')
        if command == 'status':
            p.add_argument('--json', action='store_true')
            p.add_argument('--limit', type=int, default=100)
            p.add_argument('--after-seq', type=int, default=0)
        if command in {'inspect', 'retry'}:
            p.add_argument('id')
        if command == 'retry':
            p.add_argument('--extra-attempts', type=int, default=1)
        if command == 'channel-add':
            p.add_argument('name')
            p.add_argument('manifest', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'do':
            text = (sys.stdin.buffer.read() if args.request == '-' else Path(args.request).read_bytes()).decode('utf-8')
            value = do(text, workspace=args.workspace, adapter=args.adapter, allow=args.allow)
            print(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
            return 0 if value['counts'].get('accepted', 0) == len(value['jobs']) else 3
        if args.command not in {'decode', 'prompt', 'pack'}:
            value = workspace_command(args)
            if args.command == 'status' and not args.json:
                print('Status: ' + ', '.join(f'{k}={v}' for k, v in value['states'].items()))
                print('ID\tChannel\tState\tAttempts\tWaiting for')
                for job in value['jobs']:
                    waiting = ','.join(p['id'] for p in job['waiting_for']) or '-'
                    print(f"{job['id']}\t{job['channel']}\t{job['availability']}\t{job['attempts']}/{job['max_attempts']}\t{waiting}")
                if value['next_after_seq'] is not None:
                    print(f"More: --after-seq {value['next_after_seq']}")
            else:
                print(json.dumps(value, ensure_ascii=False, indent=2))
            if args.command == 'run' and any(r['status'] == 'adapter_error' or any(v != 'ok' for v in r.get('outcomes', {}).values())
                                             for r in value['runs']):
                return 3
            return 0
        channel = Channel.from_snapshot(read_json(args.channel))
        if args.command == 'prompt':
            print(channel.codebook.prompt())
            return 0
        if args.command == 'decode':
            atoms = channel.accept(args.frame, binding=channel.binding)
            value = {'binding': channel.binding, 'atoms': [vars(a) for a in atoms],
                     'meaning': channel.describe(atoms),
                     'needs_model': channel.dispatch(args.frame, binding=channel.binding)['needs_model']}
        else:
            try:
                import tiktoken
            except ImportError:
                raise Error('token counting requires: pip install "akor-protocol[benchmark]"') from None
            encodings = [tiktoken.get_encoding(n) for n in (args.encoding or ['o200k_base'])]
            counters = [lambda s, enc=enc: len(enc.encode(s, disallowed_special=())) for enc in encodings]
            packet = render(channel, read_json(args.messages), max_tokens=args.max_tokens,
                            counters=counters, context_policy=args.context)
            value = {'language': 'OZ/9', 'mode': packet.mode, 'tokens': packet.tokens, 'system': packet.system,
                     'prompt': packet.text, 'binding': packet.binding, 'wires': packet.wires,
                     'job_map': [list(slot) for slot in packet.job_map],
                     'host_slots': [list(slot) for slot in packet.host_slots],
                     'packet_ids': list(packet.packet_ids)}
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except (Error, OSError, ValueError, TypeError, sqlite3.Error) as exc:
        print(f'oz: {exc}', file=sys.stderr)
        return 2


def workspace_command(args):
    if args.command == 'demo':
        return demo(args.directory)
    if args.command == 'init':
        if (bool(args.goal) != bool(args.source) or (args.channel and (args.goal or args.source or args.procedure))
                or (args.procedure and not args.source)):
            raise Error('--goal and --source go together; they cannot be combined with --channel')
        channel = Channel.from_snapshot(read_json(args.channel)) if args.channel else None
        if args.source:
            channel = channel_from_files(args.goal, args.source, kind=args.kind, procedure=args.procedure)
        workspace = initialize(args.directory, channel)
        return {'workspace': str(workspace.root), 'channels': list(workspace.channels), 'adapter_executed': False}
    workspace = Workspace(args.workspace)
    if args.command == 'channel-add':
        workspace.add_channel(args.name, Channel.from_snapshot(read_json(args.manifest)))
        return {'added': args.name}
    if args.command == 'run':
        return {'runs': workspace.run(args.to, args.adapter, max_calls=args.max_calls,
                                      max_tokens=args.max_tokens, timeout=args.timeout,
                                      context_policy=args.context, min_batch=args.min_batch,
                                      max_wait=args.max_wait)}
    with workspace.inbox() as box:
        if args.command == 'send':
            if (args.frame is None) == (args.file is None):
                raise Error('Give exactly one of a frame or --file')
            wire = args.frame if args.file is None else ':' + read_utf8(args.file)
            channel = workspace.channel(args.to)
            mid = args.id or 'm' + uuid.uuid4().hex[:8]
            inserted = box.post(channel, mid, wire, binding=channel.binding, after=args.after,
                                max_attempts=args.max_attempts)
            return {'id': mid, 'inserted': inserted, 'kind': box.inspect(mid)['kind']}
        if args.command == 'plan':
            plan = workspace.plan(box, args.to, max_tokens=args.max_tokens, context_policy=args.context)
            value = {'ids': [j.id for j in plan.jobs], 'deferred': list(plan.deferred),
                     'mode': plan.packet.mode if plan.packet else None,
                     'input_tokens': list(plan.packet.tokens) if plan.packet else [],
                     'encodings': workspace.config['encodings'], 'attempts_consumed': 0}
            if args.show_prompt:
                value['system'] = plan.packet.system if plan.packet else ''
                value['prompt'] = plan.packet.text if plan.packet else ''
            return value
        if args.command == 'events':
            return process_host(box, workspace.channel(args.to))
        if args.command == 'retry':
            box.requeue(args.id, extra_attempts=args.extra_attempts)
            return {'id': args.id, 'state': 'pending'}
        if args.command == 'inspect':
            return {'job': box.inspect(args.id), 'history': box.history(args.id)}
        jobs = box.list_jobs(limit=args.limit, after_seq=args.after_seq)
        aliases = {ch.binding: name for name, ch in workspace.channels.items()}
        for job in jobs:
            job['channel'] = aliases.get(job['binding'], 'unconfigured')
        return {'states': box.stats(), 'jobs': jobs, 'recent_runs': box.runs(limit=20),
                'next_after_seq': jobs[-1]['seq'] if len(jobs) == args.limit else None}


if __name__ == '__main__':
    raise SystemExit(main())
