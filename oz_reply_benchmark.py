"""Offline JSON reply-format token comparison; no provider calls are made."""
from __future__ import annotations

import importlib.metadata
import json
from pathlib import Path

from oz_reply import encode_lanes, reply_contract, validate_lanes
from oz_worker import RESPONSE_CONTRACT

ROOT = Path(__file__).parent
RECEIPT = '0123456789abcdef'


def _fixture(count: int, id_length: str, status_mix: str):
    if id_length == 'short':
        ids = [f't{i}' for i in range(1, count + 1)]
    else:
        ids = [f'task_{i:03d}_long_fixture_id' for i in range(1, count + 1)]
    if status_mix == 'same':
        statuses = [0] * count
    else:
        statuses = [i % 3 for i in range(count)]
    texts = []
    for i in range(1, count + 1):
        if i % 2:
            texts.append(f'SYNTHETIC fixture T{i}: exact short receipt; no task was executed.')
        else:
            texts.append(
                f'SYNTHETIC fixture T{i}: exact long receipt. Input value=12.50 ± 0.02 mm; '
                'procedure and measurement method unknown; no task, test, or external action was executed.'
            )
    rows = {'results': [[mid, status, text] for mid, status, text in zip(ids, statuses, texts)]}
    lanes = encode_lanes(rows, ids, RECEIPT)
    assert validate_lanes(lanes, ids, RECEIPT)['results'] == rows['results']
    row_json = json.dumps(rows, ensure_ascii=False, separators=(',', ':'))
    lane_json = json.dumps(lanes, ensure_ascii=False, separators=(',', ':'))
    return ids, rows, lanes, row_json, lane_json


def run():
    import tiktoken

    names = ['o200k_base', 'cl100k_base']
    encodings = {name: tiktoken.get_encoding(name) for name in names}
    contracts = {'rows': RESPONSE_CONTRACT, 'lanes': reply_contract(RECEIPT)}
    records = []
    for count in (1, 4, 16, 64):
        for id_length in ('short', 'long'):
            for status_mix in ('same', 'mixed'):
                ids, rows, lanes, row_json, lane_json = _fixture(count, id_length, status_mix)
                record = {'jobs': count, 'id_length': id_length, 'statuses': status_mix,
                          'fixture_ids': ids, 'fixture_statuses': [r[1] for r in rows['results']],
                          'fixture_texts': [r[2] for r in rows['results']],
                          'projected_outputs': {'rows': row_json, 'lanes': lane_json},
                          'token_counts': {}}
                for name, encoding in encodings.items():
                    count_tokens = lambda text: len(encoding.encode(text, disallowed_special=()))
                    rows_input = count_tokens(contracts['rows'])
                    lanes_input = count_tokens(contracts['lanes'])
                    rows_output = count_tokens(row_json)
                    lanes_output = count_tokens(lane_json)
                    record['token_counts'][name] = {
                        'input_contract_tokens': {'rows': rows_input, 'lanes': lanes_input,
                                                  'delta_lanes_minus_rows': lanes_input - rows_input},
                        'projected_output_tokens_fixture_only': {
                            'rows': rows_output, 'lanes': lanes_output,
                            'saved_by_lanes': rows_output - lanes_output,
                        },
                        'contract_plus_projected_fixture_output_tokens': {
                            'rows': rows_input + rows_output,
                            'lanes': lanes_input + lanes_output,
                            'saved_by_lanes': (rows_input + rows_output) - (lanes_input + lanes_output),
                        },
                    }
                records.append(record)
    return {
        'package': '0.8.0',
        'kind': 'offline_oz6_reply_format_token_comparison',
        'actual_model_calls': 0,
        'actual_tool_executions': 0,
        'tiktoken': importlib.metadata.version('tiktoken'),
        'encodings': names,
        'receipt_fixture': RECEIPT,
        'input_measurement': 'Only the additive response contract is counted; common request/context/body tokens are excluded.',
        'output_measurement': 'Projected output tokens from the exact, explicitly synthetic filled JSON fixtures; not model output or provider usage.',
        'coverage': {'job_counts': [1, 4, 16, 64], 'id_lengths': ['short', 'long'],
                     'status_patterns': ['same', 'mixed'], 'cases': len(records)},
        'cases': records,
        'limitations': [
            'All result text is synthetic fixture content; no task was executed and no model output is represented.',
            'Input counts include only the response-format contract, not the shared task prompt, IDs, provider envelope, retries, or reasoning tokens.',
            'Output counts tokenize a compact JSON serialization of the filled fixtures and are predictions, not actual provider usage.',
            'A single fixed receipt is used; tokenizer counts can vary slightly with different receipt strings.',
            'No claim is made about semantic comprehension, live latency, accuracy, or API cost.',
        ],
    }


def markdown(result):
    offline = result.get('offline_benchmark', result)
    lines = [
        '# ÖZ/6 yanıt biçimi ölçümü',
        '',
        f"Bu birleşik rapor {result.get('actual_model_calls', 0)} canlı model çağrısı ve {offline.get('actual_model_calls', 0)} çevrimdışı benchmark model çağrısı içerir.",
        '',
        '## Çevrimdışı fixture karşılaştırması',
        '',
        '`o200k_base` ve `cl100k_base` kullanıldı. Girdi tarafında yalnız ek yanıt sözleşmesi sayıldı; ortak görev girdisi, kimlikler, provider sarmalı ve yeniden denemeler dışarıda. Çıktı tokenları, açıkça sentetik olarak etiketlenmiş ve JSON’a doldurulmuş fixture metinlerinin tahminidir; model çıktısı veya provider kullanımı değildir.',
        '',
        '| İş sayısı | Kimlikler | Durumlar | o200k girdi Δ | o200k çıktı tasarrufu | o200k net tasarruf | cl100k girdi Δ | cl100k çıktı tasarrufu | cl100k net tasarruf |',
        '|---:|---|---|---:|---:|---:|---:|---:|---:|',
    ]
    for case in offline['cases']:
        vals = []
        for name in offline['encodings']:
            counts = case['token_counts'][name]
            vals.extend([
                counts['input_contract_tokens']['delta_lanes_minus_rows'],
                counts['projected_output_tokens_fixture_only']['saved_by_lanes'],
                counts['contract_plus_projected_fixture_output_tokens']['saved_by_lanes'],
            ])
        status_label = case['statuses']
        if case['jobs'] == 1 and status_label == 'mixed':
            status_label = 'mixed isteği; tek iş=0'
        lines.append(
            f"| {case['jobs']} | {case['id_length']} | {status_label} | {vals[0]:+d} | {vals[1]:+d} | {vals[2]:+d} | {vals[3]:+d} | {vals[4]:+d} | {vals[5]:+d} |"
        )
    lines += [
        '',
        '`Girdi Δ` lanes sözleşmesi eksi rows sözleşmesidir. `Net tasarruf`, sözleşme farkı ile fixture çıktı tasarrufunu toplar; pozitif değer lanes lehinedir.',
        '',
        '## Canlı gpt-6-luna biçim denemeleri',
        '',
        'Her eşleşmiş örnek aynı işleri rows ve lanes biçimlerinde ayrı çağrılarla karşılaştırır. Exact scorer iş sayısı, sıra, durum ve metni kontrol eder; lanes çıktısında receipt’i de doğrular. Sağlayıcının `turn.completed` kullanım değerleri gösterilir; Codex sistem bağlamı ve sarmalı tam-girdi sayılarına dahildir. Bu değerler yalnız sözleşme token hesabıyla karşılaştırılmamalıdır.',
        '',
    ]
    live_trials = result.get('live_model_trials', {})
    if isinstance(live_trials, dict):
        live_trials = live_trials.get('paired_cases', [])
    if live_trials:
        lines += [
            '| İş sayısı | Kimlikler | Exact scorer | Provider input tokens rows → lanes | Provider output tokens rows → lanes | Input + output toplamı rows → lanes |',
            '|---:|---|---|---:|---:|---:|',
        ]
    for trial in live_trials:
        rows, lanes = trial['rows'], trial['lanes']
        check = 'geçti' if rows['exact_scorer_pass'] and lanes['exact_scorer_pass'] else 'başarısız'
        row_total = rows['usage']['input_tokens'] + rows['usage']['output_tokens']
        lane_total = lanes['usage']['input_tokens'] + lanes['usage']['output_tokens']
        lines.append(
            f"| {trial['jobs']} | {trial['id_length']} | {check} (iki biçim) | {rows['usage']['input_tokens']} → {lanes['usage']['input_tokens']} | {rows['usage']['output_tokens']} → {lanes['usage']['output_tokens']} | {row_total} → {lane_total} |"
        )
    if not live_trials:
        lines.append('| — | — | henüz yok | — | — | — |')
    lines += ['', 'Reasoning output sayısı `output_tokens` içinde alt alan olarak verildiğinden toplamda ikinci kez eklenmedi; `cached_input_tokens` da `input_tokens` değerine eklenmedi. Provider’ın verdiği `usage` nesnesi ham saklanır; bilinmeyen alanlar yeniden yorumlanmaz.']
    if live_trials:
        paired_count = len(live_trials)
        lines.append(f'{paired_count} eşleşmiş örnekten genel iyileşme veya model kalitesi sonucu çıkarılamaz.')
    else:
        lines.append('Henüz canlı örnek yok; bu bölümde herhangi bir canlı çağrı veya model davranışı sonucu iddia edilmez.')
    lines += [
        '',
        '## Sınırlar',
        '',
        '- Çevrimdışı fixture metinleri sentetiktir; hiçbir görev veya araç çalıştırılmadı.',
        '- Token karşılaştırması yalnız `tiktoken 0.14.0` ile `o200k_base` ve `cl100k_base` için yapıldı.',
        '- Tek receipt fixture’ı kullanıldı; başka receipt dizileri az miktarda tokenizer farkı yaratabilir.',
        '- Provider input tokenları Codex CLI’ın gizli sistem bağlamını da kapsar ve sözleşme farkını tek başına ölçmez; provider’ın `usage` alanları ham haliyle JSON’da tutulur.',
        '- Canlı örnek sayısı azdır ve anlamayı, doğruluğu veya üretim kalitesini genellemek için yeterli değildir.',
        '',
        'Ham canlı model yanıtları ve tam ölçümler `oz-reply-results.json` içinde saklanır.',
        '',
    ]
    return '\n'.join(lines)


def main():
    offline = run()
    out = ROOT / 'reports' / 'oz-reply-results.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    live_trials = {}
    if out.exists():
        try:
            previous = json.loads(out.read_text(encoding='utf-8'))
            live_trials = previous.get('live_model_trials', {})
            if not isinstance(live_trials, (dict, list)):
                live_trials = {}
        except (OSError, ValueError, TypeError):
            pass
    paired_cases = live_trials.get('paired_cases', []) if isinstance(live_trials, dict) else live_trials
    result = {
        'package': offline['package'],
        'kind': 'oz6_reply_format_measurement_bundle',
        'actual_model_calls': 2 * len(paired_cases),
        'actual_tool_executions': 0,
        'offline_benchmark': offline,
        'live_model_trials': live_trials,
        'measurement_scope': {
            'actual_model_calls': 'Combined live model calls only; excludes offline benchmark. Each paired case contains rows and lanes calls.',
            'offline_benchmark_actual_model_calls': 0,
        },
    }
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (ROOT / 'reports' / 'OZ-REPLY-RESULTS.md').write_text(markdown(result), encoding='utf-8')
    print(out)


if __name__ == '__main__':
    main()
