"""Offline command line adapter for portable OZ channel manifests."""
import argparse
import json
from pathlib import Path
import sys
import sqlite3
import uuid

from oz import Channel, Error
from oz_batch import render
from oz_workspace import Workspace, channel_from_files, demo, initialize, read_utf8
from oz_worker import RESPONSE_CONTRACT, process_host


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
    parser.add_argument('--version', action='version', version='akor-protocol 0.8.0; OZ/1 + OZ/2 + OZ/3 + OZ/4 + OZ/5 + OZ/6 replies')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ['decode', 'pack', 'prompt', 'compile', 'unpack']:
        p = sub.add_parser(command)
        p.add_argument('--channel', type=Path, required=True, help='JSON channel snapshot')
        if command == 'decode':
            p.add_argument('frame')
        if command == 'unpack':
            p.add_argument('--matrix', type=Path, required=True, help='Bound matrix.json produced by compile')
        if command in {'pack', 'compile'}:
            p.add_argument('--messages', type=Path, required=True, help='JSON [[id,frame],...]')
            p.add_argument('--encoding', action='append', help='tiktoken encoding; repeat for multiple targets')
            p.add_argument('--worker', action='store_true', help='Include the Worker response contract in token cost')
            if command == 'pack':
                p.add_argument('--max-tokens', type=int)
            else:
                p.add_argument('--out', type=Path, required=True, help='New directory for channel, messages and cost report')
                p.add_argument('--max-macros', type=int, default=4)
                p.add_argument('--relative', action='store_true', help='Try OZ/4: send exact differences from a shared program')
                p.add_argument('--forms', action='store_true', help='Try OZ/5: infer a work shape with independent reference slots')
    for command in ['init', 'demo']:
        p = sub.add_parser(command, help='Create a local workspace' if command == 'init' else 'Run a model-free end-to-end demo')
        p.add_argument('directory', type=Path)
        if command == 'init':
            p.add_argument('--channel', type=Path, help='Optional existing channel manifest')
            p.add_argument('--goal', help='Create a real task from a goal and source file')
            p.add_argument('--source', type=Path)
            p.add_argument('--kind', choices=['source', 'patch'], default='source')
            p.add_argument('--procedure', type=Path, help='Optional UTF-8 test procedure description')
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
            p.add_argument('--max-attempts', type=int, default=3)
        if command in {'plan', 'run'}:
            p.add_argument('--max-tokens', type=int)
            p.add_argument('--reply-mode', choices=['rows', 'lanes'], default='rows',
                           help='Use OZ/6 ordered result lanes only with a compatible adapter')
        if command == 'plan':
            p.add_argument('--show-prompt', action='store_true')
        if command == 'run':
            p.add_argument('--adapter', type=Path, required=True, help='Explicit JSON file containing an argv list')
            p.add_argument('--max-calls', type=int, default=1)
            p.add_argument('--timeout', type=float, default=120)
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
        if args.command not in {'decode', 'prompt', 'pack', 'compile', 'unpack'}:
            value = workspace_command(args)
            if args.command == 'status' and not args.json:
                print('Durum: ' + ', '.join(f'{k}={v}' for k, v in value['states'].items()))
                print('ID\tKanal\tDurum\tDeneme\tBeklediği')
                for job in value['jobs']:
                    waiting = ','.join(p['id'] for p in job['waiting_for']) or '-'
                    print(f"{job['id']}\t{job['channel']}\t{job['availability']}\t{job['attempts']}/{job['max_attempts']}\t{waiting}")
                if value['next_after_seq'] is not None:
                    print(f"Devamı: --after-seq {value['next_after_seq']}")
            else:
                print(json.dumps(value, ensure_ascii=False, indent=2))
            if args.command == 'run' and any(r['status'] == 'adapter_error' or any(v != 'ok' for v in r.get('outcomes', {}).values())
                                             for r in value['runs']):
                return 3
            return 0
        channel = Channel.from_snapshot(read_json(args.channel))
        if args.command == 'prompt':
            print(channel.prompt())
            return 0
        if args.command == 'unpack':
            from oz_weave import decode_matrix
            record = read_json(args.matrix)
            if not isinstance(record, dict) or set(record) != {'binding', 'matrix'}:
                raise Error('bound matrix file requires binding and matrix only')
            rows = decode_matrix(channel, record['matrix'], binding=record['binding'])
            print(json.dumps({'binding': channel.binding, 'messages': rows,
                              'primitive_requests': sum(len(channel.accept(w, binding=channel.binding)) for _, w in rows),
                              'actual_model_calls': 0}, ensure_ascii=False, indent=2))
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
            contract = RESPONSE_CONTRACT if args.worker else ''
            if args.command == 'compile':
                from oz_compiler import compile_messages
                if args.out.exists():
                    raise Error('compiler output directory must not exist')
                result = compile_messages(channel, read_json(args.messages), counters=counters,
                                          max_macros=args.max_macros, response_contract=contract,
                                          relative=args.relative, forms=args.forms)
                report = {'changed': result.changed, 'old_binding': channel.binding,
                          'binding': result.channel.binding, 'encodings': [e.name for e in encodings],
                          'before_tokens': result.baseline.tokens, 'after_tokens': result.packet.tokens,
                          'absolute_optimized_tokens': result.absolute_tokens,
                          'relative_selected': bool(result.channel.basis),
                          'before_form_tokens': result.before_form_tokens,
                          'form_selected': bool(result.channel.form),
                          'selected_mode': result.packet.mode, 'worker_contract_included': args.worker,
                          'added_macros': [m.code for m in result.added_macros],
                          'search': {'spellings_per_frame': 32, 'templates_per_round': 8,
                                     'code_trials_per_template': 2, 'max_new_macros': args.max_macros,
                                     'relative_enabled': args.relative, 'basis_candidates': 8 if args.relative else 0,
                                     'forms_enabled': args.forms, 'form_candidates': 8 if args.forms else 0},
                          'evaluated_dictionaries': result.evaluated_dictionaries,
                          'tokenizer_evaluations': result.tokenizer_evaluations,
                          'exact_round_trip': True, 'actual_model_calls': 0,
                          'scope': 'Supplied corpus only; receiver input, including grammar, dictionary and references.'}
                files = {'channel.json': result.channel.snapshot(), 'messages.json': result.messages,
                         'report.json': report}
                report['matrix_exported'] = result.packet.mode.startswith('oz_matrix/')
                if report['matrix_exported']:
                    from oz_weave import encode_matrix
                    frames = [result.channel.accept(w, binding=result.channel.binding) for _, w in result.messages]
                    files['matrix.json'] = {'binding': result.channel.binding,
                                            'matrix': encode_matrix(result.channel, result.packet.ids, frames, counters=counters)}
                args.out.mkdir(parents=True, exist_ok=False)
                for name, data in files.items():
                    (args.out / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                (args.out / 'prompt.txt').write_bytes(result.packet.text.encode('utf-8'))
                print(json.dumps(dict(report, directory=str(args.out.resolve())), ensure_ascii=False, indent=2))
                return 0
            packet = render(channel, read_json(args.messages), max_tokens=args.max_tokens,
                            counters=counters, response_contract=contract)
            value = {'mode': packet.mode, 'tokens': packet.tokens, 'text': packet.text,
                     'binding': packet.binding, 'wires': packet.wires,
                     'alternatives': dict(packet.alternatives)}
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
            raise Error('--goal ve --source birlikte kullanılır; --channel ile birleştirilmez')
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
                                      max_tokens=args.max_tokens, timeout=args.timeout, reply_mode=args.reply_mode)}
    with workspace.inbox() as box:
        if args.command == 'send':
            if (args.frame is None) == (args.file is None):
                raise Error('Bir frame veya --file seç; ikisini birlikte kullanma')
            wire = args.frame if args.file is None else ':' + read_utf8(args.file)
            channel = workspace.channel(args.to)
            mid = args.id or 'm' + uuid.uuid4().hex[:8]
            inserted = box.post(channel, mid, wire, binding=channel.binding, after=args.after,
                                max_attempts=args.max_attempts)
            return {'id': mid, 'inserted': inserted, 'kind': box.inspect(mid)['kind']}
        if args.command == 'plan':
            plan = workspace.plan(box, args.to, max_tokens=args.max_tokens, reply_mode=args.reply_mode)
            value = {'ids': [j.id for j in plan.jobs], 'deferred': list(plan.deferred),
                     'mode': plan.packet.mode if plan.packet else None,
                     'input_tokens': list(plan.packet.tokens) if plan.packet else [],
                     'encodings': workspace.config['encodings'], 'attempts_consumed': 0}
            if args.show_prompt:
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
