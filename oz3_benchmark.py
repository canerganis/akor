"""Offline OZ/3 token accounting. Measures requests, not completed model work."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import time

from examples.oz3_demo import example_channel
from oz_batch import render
from oz_compiler import compile_messages, explicit
from oz_worker import RESPONSE_CONTRACT

ROOT = Path(__file__).parent


def best_by_mode(packet, mode, index):
    return min(v[index] for k, v in packet.alternatives.items() if k.split('/')[0] == mode)


def run():
    os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(ROOT / '.token-cache'))
    import tiktoken
    names = ['o200k_base', 'cl100k_base']
    encodings = [tiktoken.get_encoding(n) for n in names]
    counters = [lambda text, e=e: len(e.encode(text, disallowed_special=())) for e in encodings]
    primitive = ''.join(f'r{n}a{n}t30' for n in range(1, 17))
    rows = []
    cases = [
        ('single_read', False, [('m1', 'r1')]),
        ('vector_read', False, [('m1', ''.join(f'r{n}' for n in range(1, 17)))]),
        ('existing_macro', True, [(f'm{i}', ''.join(f'V{n}' for n in range(1, 17))) for i in range(4)]),
        ('learn_workflow', False, [(f'm{i}', primitive) for i in range(4)]),
        ('irregular_order', False, [('m1', ''.join(f'r{n}a{n}t30' for n in [9, 1, 7, 3, 9, 12, 2, 19, 4, 8]))]),
        ('literal', False, [('m1', ':12.50 ± 0.02 mm; n=3; measurement method unknown.\r\nNot experimentally validated.')]),
    ]
    learned = None
    for label, macros, messages in cases:
        ch = example_channel(vectors=False, macros=macros)
        start = time.perf_counter()
        result = compile_messages(ch, messages, counters=counters, response_contract=RESPONSE_CONTRACT)
        elapsed = time.perf_counter() - start
        frames = [ch.accept(w, binding=ch.binding) for _, w in messages]
        exact = all(result.channel.accept(w, binding=result.channel.binding) == expected
                    for (_, w), expected in zip(result.messages, frames))
        assert exact
        assert all(a <= b for a, b in zip(result.packet.tokens, result.baseline.tokens))
        rows.append({'case': label, 'messages': len(messages), 'primitive_requests': sum(len(f) for f in frames if f[0].code != ':'),
                     'changed_dictionary': result.changed, 'added_macros': [m.code for m in result.added_macros],
                     'compiled_frames': [w for _, w in result.messages], 'selected_mode': result.packet.mode,
                     'local_compile_seconds': round(elapsed, 3), 'evaluated_dictionaries': result.evaluated_dictionaries,
                     'exact_round_trip': exact,
                     'counts': {name: {'baseline_adaptive': result.baseline.tokens[i],
                                      'compiled_adaptive': result.packet.tokens[i],
                                      'brief': best_by_mode(result.packet, 'brief', i),
                                      'json': best_by_mode(result.packet, 'json', i),
                                      'compiled_payload_only': sum(counters[i](w) for _, w in result.messages),
                                      'explicit_payload_only': sum(counters[i](explicit(f)) for f in frames)}
                                for i, name in enumerate(names)}})
        if label == 'learn_workflow':
            learned = (ch, result.channel)
    # A separate, explicitly reported distribution: only read requests. Learned
    # macros need not appear in its prompt; unused definitions cost no tokens.
    old, new = learned
    heldout = [('h1', 'r3r19r2'), ('h2', ':New evidence remains unknown.')]
    old_packet = render(old, heldout, counters=counters, response_contract=RESPONSE_CONTRACT)
    new_packet = render(new, heldout, counters=counters, response_contract=RESPONSE_CONTRACT)
    ch = example_channel()
    atoms = ch.accept('V[1:16]', binding=ch.binding)
    return {'package': '0.5.0', 'kind': 'synthetic_offline_token_accounting', 'tiktoken': importlib.metadata.version('tiktoken'),
            'encodings': names, 'response_contract_included': True, 'actual_model_calls': 0, 'actual_tool_executions': 0,
            'vector_example': {'frame': 'V[1:16]', 'primitive_requests': len(atoms),
                               'payload_tokens': {n: c('V[1:16]') for n, c in zip(names, counters)}},
            'cases': rows,
            'heldout': {'messages': heldout, 'before': old_packet.tokens, 'after': new_packet.tokens,
                        'exact_round_trip': all(old.accept(w, binding=old.binding) == new.accept(w, binding=new.binding) for _, w in heldout)},
            'limitations': [
                'No global minimum; bounded candidates and greedy macro search, measured on the supplied corpus.',
                'Receiver input includes required grammar, dictionary, exact references, IDs and Worker response contract.',
                'Payload-only figures exclude all context and grammar; they are not API cost reductions.',
                'Sender bootstrapping/output, model reasoning/output, tools, retries and provider envelopes are not measured.',
                'No live model comprehension, completed task quality or end-to-end latency measurements for OZ/3.',
                'Local compiler seconds are one run on this machine; tokenizer startup is excluded.',
                'Macros describe exact requests; no evidence, completion or tool permission is inferred.',
                'Provided tokenizers are examples; other providers require their own counters.',
            ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/oz3-token-counts.json')
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'vector': result['vector_example'], 'cases': [{k: r[k] for k in ['case', 'counts', 'local_compile_seconds']} for r in result['cases']]}, indent=2))


if __name__ == '__main__':
    main()
