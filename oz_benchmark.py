"""Measure OZ payloads and honest, dictionary-inclusive receiver inputs."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

from examples.oz_demo import example_channel
from oz import Atom, prompt

ROOT = Path(__file__).parent
CASES = ['a7', '?3', '+8.', '-9', '~10', '!11', '>12', '=13', 't14', '/',
         ':12.50 ± 0.02 mm; measurement method unknown.']


def measure(encoding):
    count = lambda text: len(encoding.encode(text, disallowed_special=()))
    ch = example_channel()
    rows = []
    for original in CASES:
        atoms = ch.accept(original, binding=ch.binding)
        wire = ch.encode(atoms, counters=[count])
        prepared = ch.prepare(atoms, counters=[count])
        expanded = ch.describe(atoms)
        rows.append({'frame': wire, 'expanded': expanded,
                     'payload_tokens': count(wire), 'expanded_tokens': count(expanded),
                     'status_only_host_routing_possible': not ch.dispatch(wire, binding=ch.binding)['needs_model'],
                     'cold_receiver_choice': prepared['mode'],
                     'cold_receiver_tokens': prepared['tokens'][0],
                     'cold_receiver_alternatives': {k: v[0] for k, v in prepared['alternatives'].items()}})
    # One *batched* prompt with repeated audit requests, not separate API turns.
    macro = prompt(['a'])
    batch = []
    for n in [1, 4, 16, 64]:
        symbolic = macro + '\n' + '\n'.join('a7' for _ in range(n))
        plain = '\n'.join(ch.describe([Atom('a', 7)]) for _ in range(n))
        batch.append({'requests_in_one_batch': n, 'symbolic_with_dictionary': count(symbolic),
                      'expanded': count(plain)})
    return {'dictionary_tokens': count(prompt()), 'cases': rows,
            'payload_total': sum(r['payload_tokens'] for r in rows),
            'expanded_total': sum(r['expanded_tokens'] for r in rows),
            'cold_adaptive_total': sum(r['cold_receiver_tokens'] for r in rows),
            'single_batch_amortization': batch}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/oz-token-counts.json')
    args = parser.parse_args()
    os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(ROOT / '.token-cache'))
    import tiktoken
    result = {
        'kind': 'synthetic_text_token_accounting',
        'tiktoken_version': importlib.metadata.version('tiktoken'),
        'dictionary_sha256': hashlib.sha256(prompt().encode('utf-8')).hexdigest(),
        'encodings': {name: measure(tiktoken.get_encoding(name)) for name in ['o200k_base', 'cl100k_base']},
        'limitations': [
            'No universal token minimum or cross-provider speed claim.',
            'These two encodings do not represent every current model.',
            'Expanded payload baseline spells out the full macro contract; concise human shorthand can be cheaper.',
            'Payload savings exclude dictionaries and contextual definitions; cold receiver totals include them.',
            'Input choice optimizes only the presented input strings; reasoning, sender bootstrap, provider framing and output are additional.',
            'Single-batch amortization is not a claim that chat history is free across separate API calls.',
            'A new arbitrary fact uses literal text; information is not created by reference IDs.',
            'Protocol and evidence checks verify declared structure and consistency, not source truth.',
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Wrote {args.output}')


if __name__ == '__main__':
    main()
