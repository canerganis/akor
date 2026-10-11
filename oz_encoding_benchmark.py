"""Offline, exact-input token comparison for JSON-default and OZ/1/2 modes."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path

from oz2_benchmark import DOMAINS, WORK, scenario
from oz_batch import render

ROOT = Path(__file__).parent
COUNTS = (1, 4, 8, 16, 32, 64)
ENCODING_NAMES = ('o200k_base', 'cl100k_base')


def _count_factory(encodings):
    return [lambda text, encoding=encoding: len(encoding.encode(text, disallowed_special=()))
            for encoding in encodings]


def run():
    import tiktoken

    encodings = [tiktoken.get_encoding(name) for name in ENCODING_NAMES]
    counters = _count_factory(encodings)
    records = []
    for domain in DOMAINS:
        channel = scenario(domain)
        for count in COUNTS:
            messages = [(f'{domain[:2]}_{index + 1:02d}', WORK[index % len(WORK)])
                        for index in range(count)]
            json_packet = render(channel, messages, counters=counters, encoding='off')
            dictionary_packet = render(channel, messages, counters=counters, encoding='on')
            auto_packet = render(channel, messages, counters=counters, encoding='auto', min_savings=0)
            assert json_packet.mode.startswith('json/')
            assert not dictionary_packet.mode.startswith('json/')
            assert all(after <= before for after, before in zip(auto_packet.tokens, json_packet.tokens))
            records.append({
                'scenario': domain,
                'batch_size': count,
                'max_batch_size': 64,
                'json_mode': json_packet.mode,
                'json_actual_input_tokens': dict(zip(ENCODING_NAMES, json_packet.tokens)),
                'dictionary_mode': dictionary_packet.mode,
                'dictionary_actual_input_tokens': dict(zip(ENCODING_NAMES, dictionary_packet.tokens)),
                'auto_mode': auto_packet.mode,
                'auto_actual_input_tokens': dict(zip(ENCODING_NAMES, auto_packet.tokens)),
                'auto_savings_vs_json': {
                    name: json_packet.tokens[index] - auto_packet.tokens[index]
                    for index, name in enumerate(ENCODING_NAMES)
                },
                'all_rows_round_trip_exact': len(json_packet.wires) == count == len(dictionary_packet.wires)
                and json_packet.wires == dictionary_packet.wires == auto_packet.wires,
            })

    break_even = {}
    for domain in DOMAINS:
        rows = [record for record in records if record['scenario'] == domain]
        first = next((row['batch_size'] for row in rows if not row['auto_mode'].startswith('json/')), None)
        break_even[domain] = {
            'first_batch_size_auto_selecting_dictionary': first,
            'interpretation': 'Fixture-specific observed crossover; no universal batch threshold.',
        }
    return {
        'kind': 'offline_oz_encoding_actual_input_tokens',
        'package': importlib.metadata.version('akor-protocol'),
        'actual_model_calls': 0,
        'actual_tool_executions': 0,
        'tiktoken_version': importlib.metadata.version('tiktoken'),
        'encodings': list(ENCODING_NAMES),
        'measurement': 'Exact complete receiver-input text passed to each tokenizer; includes shared context and candidate dictionary, excludes provider framing/output/reasoning.',
        'fixture_source': 'Existing OZ/2 synthetic accounting scenarios in oz2_benchmark.py; the task data is synthetic.',
        'gate': {'off': 'compact JSON candidates only',
                 'auto': 'exact input comparison; no tokenizer regression; at least one strict saving; each saving meets min_savings=0',
                 'on': 'OZ/1 and OZ/2 dictionary candidates only'},
        'batch_sizes': list(COUNTS),
        'max_batch_size': 64,
        'break_even_by_fixture': break_even,
        'cases': records,
        'limitations': [
            'Synthetic offline tokenizer measurements are not provider usage, API cost, model behavior, or task-success evidence.',
            'No prompt/output/reasoning tokens, provider envelope, retries, or cache billing are measured.',
            'Break-even varies by fixture, batch size, full context, and tokenizer; no universal cutoff is inferred.',
        ],
    }


def markdown(result):
    lines = [
        '# ÖZ/encoding ölçümü',
        '',
        'Bu çevrimdışı benchmark, mevcut ÖZ/2 sentetik senaryolarında tam alıcı girdisini gerçek tokenizer’larla sayar. Model ve araç çağrısı yapılmaz.',
        '',
        '| Senaryo | İlk auto sözlük paketi |',
        '|---|---:|',
    ]
    for name, record in result['break_even_by_fixture'].items():
        value = record['first_batch_size_auto_selecting_dictionary']
        lines.append(f"| {name} | {value if value is not None else 'bu örneklerde yok'} |")
    lines += [
        '',
        '`Auto` tek bir eşik kullanmaz. Her tam JSON/sözlük girdisini tüm seçili tokenizer’larda karşılaştırır; hiçbir tokenizer’da gerileme olmamasını, en az bir kesin tasarrufu ve `min_savings` değerini ister. Tablodaki crossover yalnız bu sentetik fikstürler için gözlenen ilk pakettir.',
        '',
        '## Materials scaling senaryosu',
        '',
        '| İş sayısı | o200k JSON | o200k dictionary | o200k auto | cl100k JSON | cl100k dictionary | cl100k auto | Seçilen auto modu |',
        '|---:|---:|---:|---:|---:|---:|---:|---|',
    ]
    for row in (case for case in result['cases'] if case['scenario'] == 'materials'):
        lines.append(
            f"| {row['batch_size']} | {row['json_actual_input_tokens']['o200k_base']} | "
            f"{row['dictionary_actual_input_tokens']['o200k_base']} | {row['auto_actual_input_tokens']['o200k_base']} | "
            f"{row['json_actual_input_tokens']['cl100k_base']} | {row['dictionary_actual_input_tokens']['cl100k_base']} | "
            f"{row['auto_actual_input_tokens']['cl100k_base']} | {row['auto_mode']} |"
        )
    lines += [
        '',
        '## Yöntem ve sınırlar',
        '',
        '- Altı eski OZ/2 senaryosu ve 1, 4, 8, 16, 32, 64 görevli paketler kullanıldı. Her satırın ID, wire metni, bağlamı ve gerekiyorsa sözlüğü tam alıcı girdisinde sayıldı.',
        '- `off` yalnız kompakt JSON adaylarını; `on` yalnız OZ/1/2 sözlük adaylarını ölçer. `auto`, tam girdileri karşılaştırıp gate koşullarına uyan sonucu seçer.',
        '- En büyük ölçülen paket 64 iştir; runtime girdi bütçeleri ayrıca geçerlidir. Token sayıları yalnız `tiktoken` tokenizer’larına aittir.',
        '- Bu ölçüm canlı model tasarrufu, görev doğruluğu, gecikme veya genel performans iddiası değildir.',
        '',
        'Ham tüm senaryo sayımları ve varsayımlar `OZ-ENCODING-RESULTS.json` içindedir.',
        '',
    ]
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'reports/oz-encoding-results.json')
    args = parser.parse_args()
    os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(ROOT / '.token-cache'))
    result = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    markdown_path = ROOT / 'reports' / 'OZ-ENCODING-RESULTS.md'
    markdown_path.write_text(markdown(result), encoding='utf-8')
    print(args.output)


if __name__ == '__main__':
    main()
