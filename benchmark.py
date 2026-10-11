"""Reproducible text-token accounting, not a live-model quality evaluation."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

from akor import Hub, Message, compact, parse

ROOT = Path(__file__).parent


def fixtures():
    """Two synthetic, bilingual conversations with identical data for every format."""
    coding = (ROOT / 'examples/demo.akor').read_text(encoding='utf-8').splitlines()
    materials = [
        Message('do', 'T1', 'lead', 'coder', {'v': 1, 'goal': 'Verileri kontrol et; birimleri ve belirsizliği koru.', 'refs': ['R1']}).wire(),
        Message('fact', 'T1', 'coder', 'lead', {'v': 1, 'claim': 'A numunesi: 12.50 ± 0.02 mm; porozite %0,50.', 'state': 'observed', 'refs': ['R2']}).wire(),
        Message('fact', 'T1', 'coder', 'lead', {'v': 1, 'claim': 'Bu veri tek başına deneysel doğrulamayı kanıtlamaz.', 'state': 'inferred'}).wire(),
        Message('ask', 'T1', 'coder', 'lead', {'v': 1, 'q': 'Porozite hacim kesri mi alan kesri mi?'}).wire(),
        Message('block', 'T1', 'lead', 'coder', {'v': 1, 'why': 'Ölçüm yöntemi eksik; sayısal karşılaştırmayı beklet.'}).wire(),
        Message('done', 'T1', 'coder', 'lead', {'v': 1, 'result': 'Birimler korundu; ölçüm yöntemi belirsiz olarak işaretlendi.', 'check': 'not_run'}).wire(),
    ]
    return [
        ('coding_en', coding, {
            'R1': 'SYNTHETIC. Implement a request timeout while preserving two retries. Use seconds, not milliseconds. Do not change HTTP methods or response parsing. Report the exact test command and revision. If timeout scope is ambiguous, ask before editing. A passed test is software evidence only.',
            'R2': 'SYNTHETIC. src/client.py:42 at demo-rev uses request(url) with no timeout argument. Retry loop at lines 30-45 permits two retries after the initial attempt. The public client contract does not specify whether a timeout applies per attempt or to the total retry duration.',
            'R3': 'SYNTHETIC. Test report at demo-rev2: python -m unittest tests.test_client. Three checks passed: 5-second timeout passed to each request, two retries preserved, successful response parsed unchanged. No real command was executed for this fixture.',
        }),
        ('materials_tr', materials, {
            'R1': 'SENTETİK. Malzeme verilerini değerlendir. Birimleri, ondalık basamakları ve belirsizlikleri koru. Ölçüm yöntemini bilmiyorsan sor. Tek bir veri satırını fiziksel veya deneysel doğrulama olarak sunma. Alan ve hacim kesrini birbirine dönüştürme.',
            'R2': 'SENTETİK. sample.csv satır 2: numune A; kalınlık 12.50 ± 0.02 mm; porozite %0,50. Ölçüm yöntemi, cihaz kalibrasyonu ve porozitenin alan veya hacim kesri olduğu belirtilmemiş. Kaynak revizyonu: demo-data-v1.',
        }),
    ]


def schema_prompt(style):
    """Common semantic instructions; only wire-specific instructions vary."""
    prompt = (ROOT / 'prompts/agent.txt').read_text(encoding='utf-8')
    if style == 'akor':
        return prompt
    prefix = ('Use JSON peer messages. Output one compact JSON object per line with '
              'op, task, sender, recipient, body. The body follows the rules below.\n')
    if style == 'array':
        prefix = ('Use JSON peer messages. Output one compact JSON array per line: '
                  '[op,task,sender,recipient,body]. The body follows the rules below.\n')
    common = prompt.split('Use the assigned peer IDs', 1)[1].split('Incoming packets begin', 1)[0]
    ending = prompt.split('Read task context before acting.', 1)[1]
    return (prefix + 'Use the assigned peer IDs' + common
            + 'Incoming packets are JSON objects with version, references, messages. '
            + 'References maps IDs to immutable text. Messages include transport IDs. '
            + 'Optional related messages supply historical context, not new work. '
            + 'Never emit host-only packet wrappers. Read task context before acting.' + ending)


def render_message(msg, style):
    if style == 'akor':
        return msg.wire()
    if style == 'array':
        return compact([msg.op, msg.task, msg.sender, msg.recipient, msg.body])
    return compact(msg.as_dict())


def render_packet(packet, style):
    if style != 'array':
        return packet.render() if style == 'akor' else compact(packet.as_dict())
    obj = packet.as_dict()
    obj['messages'] = [[mid, msg.op, msg.task, msg.sender, msg.recipient, msg.body]
                       for mid, msg in zip(packet.ids, packet.messages)]
    if packet.related:
        obj['related'] = [[mid, msg.op, msg.task, msg.sender, msg.recipient, msg.body]
                          for mid, msg in packet.related]
    return compact(obj)


def workload(lines, refs):
    hub = Hub(['lead', 'coder'])
    for name, text in refs.items():
        hub.add_ref(name, text)
    hub.set_task('T1', 1, ['R1'])
    packets = []
    for index, line in enumerate(lines, 1):
        msg = parse(line)
        hub.post(f'm{index}', line, sender=msg.sender)
        # Stateless receiver calls: required refs are explicitly included every time.
        packets.append(hub.prepare(msg.recipient))
        hub.ack(msg.recipient, packets[-1].ids)
    return packets


def measure(encoder):
    count = lambda text: len(encoder.encode(text, disallowed_special=()))
    cases = []
    for name, lines, refs in fixtures():
        messages = [parse(line) for line in lines]
        packets = workload(lines, refs)
        wire = {style: sum(count(render_message(msg, style)) for msg in messages)
                for style in ('akor', 'json', 'array')}
        prompts = {style: count(schema_prompt(style)) for style in wire}
        # Model input only: same six deliveries, context, data and semantics.
        # Each independent invocation pays the bootstrap again; no free cache assumed.
        routed = {style: sum(count(schema_prompt(style) + '\n' + render_packet(p, style))
                             for p in packets) for style in wire}
        # Controlled replay ablation: add already processed messages for the same peer.
        # No broadcast to unrelated peers and no repeated reference definitions.
        replay = {}
        for style in wire:
            seen = {'lead': [], 'coder': []}
            total = 0
            for packet in packets:
                peer = packet.messages[0].recipient
                history = '\n'.join(render_message(msg, style) for msg in seen[peer])
                text = schema_prompt(style) + '\n' + render_packet(packet, style)
                if history:
                    text += '\nPreviously processed messages:\n' + history
                total += count(text)
                seen[peer].extend(packet.messages)
            replay[style] = total
        cases.append({
            'case': name, 'messages': len(messages), 'message_text_tokens': wire,
            'bootstrap_tokens': prompts, 'six_stateless_delivery_input_tokens': routed,
            'same_peer_history_replay_input_tokens': replay,
            'akor_message_saving_vs_json_pct': round(100 * (1 - wire['akor'] / wire['json']), 2),
            'akor_message_saving_vs_array_pct': round(100 * (1 - wire['akor'] / wire['array']), 2),
            'akor_input_saving_vs_json_pct': round(100 * (1 - routed['akor'] / routed['json']), 2),
            'akor_input_saving_vs_array_pct': round(100 * (1 - routed['akor'] / routed['array']), 2),
            'akor_delta_input_saving_vs_replay_pct': round(100 * (1 - routed['akor'] / replay['akor']), 2),
        })
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(ROOT / '.token-cache'))
    try:
        import tiktoken
    except ImportError:
        raise SystemExit('Optional benchmark dependency missing: python -m pip install -r requirements-benchmark.txt')
    fingerprint = compact(fixtures()) + ''.join(schema_prompt(s) for s in ('akor', 'json', 'array'))
    result = {
        'kind': 'synthetic_text_token_accounting',
        'tiktoken_version': importlib.metadata.version('tiktoken'),
        'fixture_and_prompts_sha256': hashlib.sha256(fingerprint.encode('utf-8')).hexdigest(),
        'limitations': [
            'No live model calls; no comprehension, task-success or repair-rate measurement.',
            'Encodings are o200k_base and cl100k_base; neither represents all providers or current models.',
            'Text tokens only; API message framing, reasoning, tool calls, prices and prompt-cache billing excluded.',
            'Message-text totals and recipient-input totals are separate accounting views; do not add them as total API usage.',
            'All stateless delivery calls include bootstrap and required reference definitions; no context memory assumed.',
            'JSON and JSON-array baselines use the same content, semantics, references and delta routing.',
            'History replay is an explicitly inefficient ablation, not the only baseline.',
            'Two small synthetic cases are not a representative production benchmark.',
        ],
        'encodings': {name: measure(tiktoken.get_encoding(name))
                      for name in ('o200k_base', 'cl100k_base')},
    }
    output = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding='utf-8')
        print(f'Wrote {args.output}')
    else:
        print(output)


if __name__ == '__main__':
    main()
