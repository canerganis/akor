"""Full receiver cost for OZ/5, with structured, shuffled and irregular controls."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import random
import statistics
import time

from examples.oz4_demo import example_channel as previous_channel, messages as previous_messages
from examples.oz5_demo import example_channel, messages
from oz_batch import render
from oz_compiler import compile_messages
from oz_form import form_spelling
from oz_weave import decode_matrix
from oz_worker import RESPONSE_CONTRACT

ROOT = Path(__file__).parent


def irregular_rows():
    rng, ch = random.Random(70591), example_channel(form=True)
    rows = []
    for i in range(64):
        values = [rng.randrange(1, 25) for _ in range(4)] + [rng.randrange(30, 33) for _ in range(5)]
        atoms = ch.accept(ch.fill_form(*values), binding=ch.binding)
        rows.append((f'u{i}', ''.join(a.code + str(a.ref) for a in atoms)))
    assert len({w for _, w in rows}) == 64
    return rows


def run():
    os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(ROOT / '.token-cache'))
    import tiktoken
    names = ['o200k_base', 'cl100k_base']
    encodings = [tiktoken.get_encoding(n) for n in names]
    counters = [lambda s, e=e: len(e.encode(s, disallowed_special=())) for e in encodings]
    source, varied = example_channel(), messages()
    shuffled = varied[:]
    random.Random(705).shuffle(shuffled)  # No change to IDs or operation meaning.
    cases = [('single_read', source, [('m', 'r1')]),
             ('structured_8', source, varied[:8]), ('structured_32', source, varied[:32]),
             ('structured_64', source, varied), ('shuffled_64', source, shuffled),
             ('irregular_64', source, irregular_rows()),
             ('inline_macro_control_64', example_channel(phased=False), messages(phased=False)),
             ('identical_64', source, [(f'm{i}', varied[0][1]) for i in range(64)]),
             ('oz4_sparse_edits_64', previous_channel(relative=False), previous_messages()),
             ('literal', source, [('m', ':New failure at line 12; root cause unknown.\r\nNo test outcome verified.')])]
    results = []
    for label, channel, rows in cases:
        start = time.perf_counter()
        result = compile_messages(channel, rows, counters=counters, relative=True, forms=True,
                                  response_contract=RESPONSE_CONTRACT)
        elapsed = time.perf_counter() - start
        assert all(a <= b for a, b in zip(result.packet.tokens, result.before_form_tokens))
        for (mid, wire), (old_id, original) in zip(result.messages, rows):
            assert mid == old_id
            assert result.channel.accept(wire, binding=result.channel.binding) == channel.accept(original, binding=channel.binding)
        record = {'case': label, 'messages': len(rows), 'distinct_programs': len({w for _, w in rows}),
                  'mode': result.packet.mode, 'form_selected': bool(result.channel.form),
                  'base_selected': bool(result.channel.basis), 'exact_round_trip': True,
                  'local_compile_seconds': round(elapsed, 3), 'evaluated_dictionaries': result.evaluated_dictionaries,
                  'counts': {name: {'optimized_oz4': result.before_form_tokens[i], 'oz5': result.packet.tokens[i],
                                    'savings_percent': round(100 * (1 - result.packet.tokens[i] / result.before_form_tokens[i]), 2)}
                             for i, name in enumerate(names)}}
        if label == 'structured_64':
            matrix = next(json.loads(line) for line in result.packet.text.splitlines() if line.startswith('{"cols":'))
            timings = {'full_batch_render_ms': [], 'direct_bind_64_frames_ms': [], 'matrix_decode_64_jobs_ms': []}
            values = [tuple(map(int, form_spelling(result.channel.form,
                      channel.accept(w, binding=channel.binding))[1:].split(','))) for _, w in rows]
            for _ in range(5):
                start = time.perf_counter()
                render(result.channel, result.messages, counters=counters, response_contract=RESPONSE_CONTRACT)
                timings['full_batch_render_ms'].append((time.perf_counter() - start) * 1000)
                start = time.perf_counter()
                for args in values:
                    result.channel.fill_form(*args)
                timings['direct_bind_64_frames_ms'].append((time.perf_counter() - start) * 1000)
                start = time.perf_counter()
                assert len(decode_matrix(result.channel, matrix, binding=result.channel.binding)) == 64
                timings['matrix_decode_64_jobs_ms'].append((time.perf_counter() - start) * 1000)
            record['reuse_median_of_5_runs'] = {key: round(statistics.median(v), 3) for key, v in timings.items()}
            # Held-out inputs use new values, and one breaks the learned shape.
            # Exact fallback is checked; this does not assert model task accuracy.
            unseen = irregular_rows()[:16] + [('unseen', 'r1a2t31>42')]
            packet = render(result.channel, unseen, counters=counters, response_contract=RESPONSE_CONTRACT)
            assert all(result.channel.accept(w, binding=result.channel.binding) == channel.accept(old, binding=channel.binding)
                       for w, (_, old) in zip(packet.wires, unseen))
            record['held_out'] = {'messages': len(unseen), 'exact_round_trip': True, 'mode': packet.mode,
                                  'tokens': list(packet.tokens), 'model_accuracy_measured': False}
        results.append(record)
        print(json.dumps(record), flush=True)
    return {'package': '0.7.0', 'kind': 'synthetic_offline_code_review_requests',
            'tiktoken': importlib.metadata.version('tiktoken'), 'encodings': names,
            'actual_model_calls': 0, 'actual_tool_executions': 0,
            'full_dictionary_context_ids_and_response_contract_included': True,
            'baseline': 'Same corpus; bounded macro search (4 new macros), vectors, OZ/4 Base, absolute/table/plain/JSON candidates.',
            'cases': results,
            'limitations': ['No live model comprehension, coding success, network speed or total API cost measured.',
                            'Structured cases intentionally contain reusable parameter patterns; shuffled and irregular controls are separate.',
                            'No job sorting, deduplication of execution, evidence removal or ID renaming.',
                            'Output/reasoning/tool tokens, provider envelope, sender setup and retries excluded.',
                            'Compilation is bounded calibration on the provided corpus, not a global minimum.',
                            'Times are local and machine-specific; direct binding excludes packet/tokenizer work.',
                            'Held-out validation proves codec preservation only, not agent understanding.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/oz5-token-counts.json')
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
