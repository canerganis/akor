"""Reproducible, offline cost accounting for OZ/2, including useful baselines."""
import argparse
import importlib.metadata
import itertools
import json
import os
from pathlib import Path
import statistics
import time

from oz import Atom, Channel, Codebook, Macro, Reference
from oz_batch import render
from oz_runtime import Inbox

ROOT = Path(__file__).parent
# Synthetic contexts, not factual research claims or actual customer records.
DOMAINS = {
    'code': ('Timeout must be 5 s per attempt, two retries, unchanged public API.',
             'Check timeout boundary and retry count; record failures separately.'),
    'materials': ('Coupon length 12.50 ± 0.02 mm; n=3; measurement method unknown. No physical validation claimed.',
                  'Check units, sample count, uncertainty and whether a method was supplied.'),
    'data': ('Table has 120 rows, 3 missing values; blanks are unknown, never zero. Source revision d2.',
             'Check row count and preserve missingness; do not infer replacements.'),
    'translation': ('Keep 0.05 wt%, alloy Al-6061 and the phrase not experimentally validated unchanged in meaning.',
                    'Check numbers, alloy name, units and negation against the supplied text.'),
    'support': ('Synthetic ticket: request timed out after 5 s; cause unknown; no refunds or account changes authorized.',
                'Check available evidence and list missing diagnostic information.'),
    'planning': ('Synthetic plan: 3 tasks, two workers, budget 40 min; task C depends on A; budget is not a guarantee.',
                 'Check dependencies and budget; retain uncertainty about task duration.'),
}
WORK = ['R', 'P', 'r1', 't2', '>3', 'r1t2>3', 'RP', ':Unverified: additional source may be needed.']
HOST = ['?9', '+4.', '-5', '!6']


def scenario(domain):
    source, procedure = DOMAINS[domain]
    return Channel(session='bench', task=domain, revision=1, sender='lead', recipient='worker', active=1,
                   goal='SYNTHETIC ' + domain + ': preserve constraints; separate claims from verified outcomes.',
                   references=[Reference(1, 'source', source, 'fixture:' + domain),
                               Reference(2, 'procedure', procedure),
                               Reference(3, 'proposal', 'Draft a constrained response based only on supplied evidence.'),
                               Reference(4, 'test', 'SYNTHETIC check report: passed.', 'fixture.log:4', 'passed'),
                               Reference(5, 'test', 'SYNTHETIC check report: failed.', 'fixture.log:5', 'failed'),
                               Reference(6, 'reason', 'Required evidence not provided.')],
                   codebook=Codebook([Macro('R', (Atom('r', 0), Atom('t', 2))),
                                      Macro('P', (Atom('r', 0), Atom('>', 3)))]))


def best(packet, mode):
    return min(v[0] for k, v in packet.alternatives.items() if k.split('/')[0] == mode)


def accounting(encoding):
    count = lambda text: len(encoding.encode(text, disallowed_special=()))
    rows = []
    for domain in DOMAINS:
        ch = scenario(domain)
        messages = [(f'w{i}', wire) for i, wire in enumerate(WORK, 1)]
        packet = render(ch, messages, counters=[count])
        singles = [render(ch, [message], counters=[count]) for message in messages]
        # Exercise the real inbox path. The synthetic adapter only acknowledges
        # receipts: it does not claim to have performed these domain tasks.
        with Inbox() as inbox:
            for mid, wire in messages:
                inbox.post(ch, mid, wire, binding=ch.binding)
            for i, wire in enumerate(HOST):
                inbox.post(ch, f'h{i}', wire, binding=ch.binding)
            work = inbox.claim(ch, owner='adapter', limit=64)
            actual = work.prepare(ch, counters=[count])
            assert actual.text == packet.text
            inbox.complete(work, {j.id: 'Synthetic receipt only.' for j in work.jobs})
            host = inbox.claim(ch, owner='host', kind='host', limit=64)
            assert all(not ch.dispatch(j.wire, binding=ch.binding)['needs_model'] for j in host.jobs)
            inbox.complete(host, {j.id: 'Synthetic host receipt only.' for j in host.jobs})
            assert inbox.stats() == {'done': 12}
        rows.append({
            'domain': domain, 'work_messages': len(WORK), 'host_messages': len(HOST),
            'individual_adaptive_tokens': sum(p.tokens[0] for p in singles),
            'individual_brief_tokens': sum(best(p, 'brief') for p in singles),
            'batch_selected_mode': packet.mode, 'batch_selected_tokens': packet.tokens[0],
            'batch_brief_tokens': best(packet, 'brief'), 'batch_json_tokens': best(packet, 'json'),
            'batch_oz_tokens': best(packet, 'oz'), 'batch_base_oz_tokens': best(packet, 'oz_base'),
            'macro_payload_tokens': sum(count(w) for w in packet.wires),
            'explicit_primitive_payload_tokens': sum(count(''.join(a.code + (str(a.ref) if a.ref is not None else '')
                                                                             for a in ch.accept(w, binding=ch.binding)))
                                                     for w in WORK if not w.startswith(':'))
                                               + sum(count(w) for w in WORK if w.startswith(':')),
            'tokenizer_evaluations_in_batch': packet.tokenizer_evaluations,
            'round_trip_exact': all(ch.accept(wire, binding=ch.binding) == ch.accept(original, binding=ch.binding)
                                    for wire, (_, original) in zip(packet.wires, messages)),
        })
    ch = scenario('materials')
    scaling = []
    for n in [1, 4, 8, 16, 32, 64]:
        packet = render(ch, [(f'w{i}', WORK[i % len(WORK)]) for i in range(n)], counters=[count])
        scaling.append({'messages': n, 'selected': packet.mode, 'tokens': packet.tokens[0],
                        'brief': best(packet, 'brief'), 'json': best(packet, 'json'), 'oz': best(packet, 'oz')})
    totals = {key: sum(row[key] for row in rows) for key in
              ['individual_adaptive_tokens', 'individual_brief_tokens', 'batch_selected_tokens',
               'batch_brief_tokens', 'batch_json_tokens', 'batch_oz_tokens', 'macro_payload_tokens',
               'explicit_primitive_payload_tokens']}
    return {'domains': rows, 'totals': totals, 'batch_scaling': scaling}


def optimizer(encoding):
    count = lambda text: len(encoding.encode(text, disallowed_special=()))
    ch = scenario('data')
    atoms = (Atom('r', 1),) * 20
    legacy_choices = [('r', 'r1')] * 12 + [('r1',)] * 8

    def legacy():
        candidates = [''.join(parts) for parts in itertools.product(*legacy_choices)]
        return min(candidates, key=lambda s: (count(s), len(s), s))

    def current():
        return ch.encode(atoms, counters=[count])

    result = {}
    for label, function, candidates in [('v0_2_base_search', legacy, 4096), ('v0_3_bounded_search', current, 256)]:
        times = []
        function()  # warm tokenizer/cache internals
        for _ in range(3):
            start = time.perf_counter()
            wire = function()
            times.append((time.perf_counter() - start) * 1000)
        assert ch.accept(wire, binding=ch.binding) == atoms
        result[label] = {'median_ms_3_runs': round(statistics.median(times), 3),
                         'candidate_cap': candidates, 'chosen_tokens': count(wire)}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=ROOT / 'reports/oz2-token-counts.json')
    args = p.parse_args()
    os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(ROOT / '.token-cache'))
    import tiktoken
    encodings = {name: tiktoken.get_encoding(name) for name in ['o200k_base', 'cl100k_base']}
    result = {'kind': 'synthetic_offline_accounting_and_queue_replay', 'package': '0.3.0',
              'tiktoken_version': importlib.metadata.version('tiktoken'),
              'messages': 72, 'model_work_messages': 48, 'host_event_messages': 24,
              'prepared_model_batches': 6, 'actual_model_calls': 0,
              'encodings': {n: accounting(e) for n, e in encodings.items()},
              'local_encoder_microbenchmark': {n: optimizer(e) for n, e in encodings.items()},
              'limitations': [
                  'Synthetic requests: no LLM task success, comprehension or model latency measurement.',
                  'No universal minimum. Choose cheapest among measured bounded candidates.',
                  'All receiver context and required dictionaries are charged in every batch.',
                  'Individual-to-batch reduction mostly comes from batching and shared context, not alphabet choice.',
                  'Payload comparison excludes dictionary/context and compares to explicit primitive OZ, not all natural languages.',
                  'Sender bootstrap, output, reasoning, provider wrappers and cached history billing are excluded.',
                  'Tokenizers are examples, not validated equivalents of every provider model.',
                  'Fewer prepared calls is a scheduling possibility for independent jobs, not measured model acceleration.',
                  'Local encoder time excludes models, network and tokenizer initialization; machine-dependent, three runs only.',
              ]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({n: r['totals'] for n, r in result['encodings'].items()}, indent=2))


if __name__ == '__main__':
    main()
