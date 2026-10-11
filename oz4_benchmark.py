"""Full-cost OZ/4 accounting against optimized OZ/3 and simple deduplication."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import time
import statistics

from examples.oz4_demo import example_channel, messages
from oz import Channel, _dump
from oz_batch import COMMON, render
from oz_compiler import compile_messages
from oz_worker import RESPONSE_CONTRACT

ROOT = Path(__file__).parent


def dedup_baseline(channel, rows, counters):
    """Strong exact-frame dictionary baseline: identical messages cost one definition.

    Keeps separate message IDs and results. All shared context and contracts are
    charged; it does not execute or coalesce the work behind those IDs.
    """
    frames = [channel.accept(w, binding=channel.binding) for _, w in rows]
    wires = [channel.encode(f, counters=counters, candidate_limit=32) for f in frames]
    unique = list(dict.fromkeys(wires))
    indices = {w: i for i, w in enumerate(unique)}
    flat = tuple(a for f in frames for a in f)
    snapshot = channel.snapshot()
    needed = {channel.active} | {a.ref for a in flat}
    refs = [r for r in snapshot['references'] if r['number'] in needed]
    context = ('Goal: ' + snapshot['goal'] + '\nActive: ' + str(channel.active)
               + '\nRefs [id,kind,text,source,status]:\n'
               + _dump([[r[k] for k in ['number', 'kind', 'text', 'source', 'status']] for r in refs]))
    text = (COMMON + context + '\n' + channel.dictionary(unique)
            + '\nTemplates indexed from 0; each row [id,template_index] is an independent request.\n'
            + _dump(unique) + '\n' + _dump([[mid, indices[w]] for (mid, _), w in zip(rows, wires)])
            + '\n' + RESPONSE_CONTRACT)
    return [c(text) for c in counters]


def run():
    os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(ROOT / '.token-cache'))
    import tiktoken
    names = ['o200k_base', 'cl100k_base']
    encodings = [tiktoken.get_encoding(n) for n in names]
    counters = [lambda s, e=e: len(e.encode(s, disallowed_special=())) for e in encodings]
    source = example_channel(relative=False)
    varied = messages()
    results = []
    cases = [('small_read', [('m0', 'r1')]), ('single_long_plan', varied[:1]),
             ('distinct_8', varied[:8]), ('distinct_32', varied[:32]), ('distinct_64', varied),
             ('identical_64_control', [(f'm{i}', varied[0][1]) for i in range(64)]),
             ('literal', [('m0', ':New failure at line 12; root cause unknown.\r\nDo not claim tests passed.')])]
    for label, rows in cases:
        start = time.perf_counter()
        result = compile_messages(source, rows, counters=counters, relative=True, response_contract=RESPONSE_CONTRACT)
        elapsed = time.perf_counter() - start
        snapshot = result.channel.snapshot()
        snapshot.pop('basis', None)
        absolute = Channel.from_snapshot(snapshot)
        exact_dedup = dedup_baseline(absolute, rows, counters)
        assert all(a <= b for a, b in zip(result.packet.tokens, result.absolute_tokens))
        exact = all(result.channel.accept(w, binding=result.channel.binding) == source.accept(old, binding=source.binding)
                    for (_, w), (_, old) in zip(result.messages, rows))
        assert exact
        results.append({'case': label, 'messages': len(rows), 'unique_programs': len({w for _, w in rows}),
                        'primitive_requests': sum(len(source.accept(w, binding=source.binding)) for _, w in rows if not w.startswith(':')),
                        'relative_selected': bool(result.channel.basis), 'mode': result.packet.mode,
                        'local_compile_seconds': round(elapsed, 3), 'exact_round_trip': exact,
                        'compiled_sample': [w for _, w in result.messages[:3]],
                        'counts': {name: {'initial_adaptive': result.baseline.tokens[i],
                                          'optimized_oz3': result.absolute_tokens[i], 'exact_frame_dictionary': exact_dedup[i],
                                          'oz4': result.packet.tokens[i],
                                          'strongest_baseline': min(result.absolute_tokens[i], exact_dedup[i])}
                                   for i, name in enumerate(names)}})
        if label == 'distinct_64':
            times, decode_times = [], []
            for _ in range(3):
                before = time.perf_counter()
                render(result.channel, result.messages, counters=counters, response_contract=RESPONSE_CONTRACT)
                times.append((time.perf_counter() - before) * 1000)
                before = time.perf_counter()
                for _, wire in result.messages:
                    result.channel.accept(wire, binding=result.channel.binding)
                decode_times.append((time.perf_counter() - before) * 1000)
            results[-1]['reuse_existing_dictionary'] = {'full_batch_render_median_ms_3_runs': round(statistics.median(times), 3),
                                                       'decode_64_frames_median_ms_3_runs': round(statistics.median(decode_times), 3)}
    ch = example_channel()
    return {'package': '0.6.0', 'kind': 'synthetic_offline_distinct_code_review_plans',
            'tiktoken': importlib.metadata.version('tiktoken'), 'encodings': names,
            'actual_model_calls': 0, 'actual_tool_executions': 0, 'response_contract_included': True,
            'identity_frame': {'text': '^', 'primitive_requests': len(ch.basis),
                               'payload_tokens_only': [c('^') for c in counters]}, 'cases': results,
            'limitations': ['No global minimum or unprecedented-efficiency claim.',
                            'Synthetic code-review instructions, not completed code changes or live model comprehension.',
                            'Full Base, grammar, references, IDs and response contract are counted in every batch.',
                            'Output/reasoning/tool tokens, provider framing, retries and sender bootstrap are excluded.',
                            'No model acceleration measured. Local compilation time is single-run and machine-specific.',
                            'Exact-frame dictionary is also a production renderer candidate when messages repeat.',
                            'One Base, up to eight candidates; up to sixteen original-coordinate edits per frame.',
                            'Identical-plan control must not be confused with useful distinct tasks.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/oz4-token-counts.json')
    args = parser.parse_args()
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'identity': result['identity_frame'], 'cases': result['cases']}, indent=2))


if __name__ == '__main__':
    main()
