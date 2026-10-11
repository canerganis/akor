"""Offline command line adapter for portable OZ channel manifests."""
import argparse
import json
from pathlib import Path
import sys

from oz import Channel, Error
from oz_batch import render


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
    parser.add_argument('--version', action='version', version='akor-protocol 0.3.0; OZ/1 + OZ/2')
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
    args = parser.parse_args(argv)
    try:
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
                raise Error('pack requires optional tokenizer dependency: pip install "akor-protocol[benchmark]"') from None
            encodings = [tiktoken.get_encoding(n) for n in (args.encoding or ['o200k_base'])]
            packet = render(channel, read_json(args.messages), max_tokens=args.max_tokens,
                            counters=[lambda s, enc=enc: len(enc.encode(s, disallowed_special=())) for enc in encodings])
            value = {'mode': packet.mode, 'tokens': packet.tokens, 'text': packet.text,
                     'binding': packet.binding, 'wires': packet.wires,
                     'alternatives': dict(packet.alternatives)}
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    except (Error, OSError, ValueError, TypeError) as exc:
        print(f'oz: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
