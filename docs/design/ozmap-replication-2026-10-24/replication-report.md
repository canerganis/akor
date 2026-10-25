# oz map clean replication: report

Mode: evaluation. Schema ozmap-rep/1. R = ['margin', 'temp_class', 'verdict']. Isolation: passed. Safety kill: False.

## Cells

| Cell | State | Jobs | Correct | Unresolved | Tokens | Tokens per correct | Makespan s | Child s | Usage | Evidence | Calls | Rule answers |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|
| codex/boolq/cold/A | invalid | 256 | 0 | 256 | 87608 | n/a | 235.0 | 233.5 | unverified | incomplete | 4 | 0 |
| codex/boolq/cold/B | complete | 256 | 225 | 14 | 100600 | 447.1 | 87.2 | 83.7 | complete | complete | 5 | 0 |
| codex/boolq/cold/C | complete | 256 | 224 | 17 | 89301 | 398.7 | 95.6 | 92.1 | complete | complete | 4 | 0 |
| codex/materials/cold/A | complete | 256 | 256 | 0 | 68889 | 269.1 | 39.5 | 37.4 | complete | complete | 4 | 0 |
| codex/materials/cold/B | complete | 256 | 256 | 0 | 83445 | 326.0 | 132.0 | 128.4 | complete | complete | 5 | 142 |
| codex/materials/cold/C | complete | 256 | 256 | 0 | 57664 | 225.2 | 143.7 | 139.9 | complete | complete | 3 | 142 |
| codex/materials/warm/A | complete | 256 | 256 | 0 | 68975 | 269.4 | 20.0 | 18.0 | complete | complete | 4 | 0 |
| codex/materials/warm/C | complete | 256 | 256 | 0 | 32821 | 128.2 | 24.9 | 22.1 | complete | complete | 2 | 192 |
| sonnet/materials/cold/A | complete | 256 | 256 | 0 | 42521 | 166.1 | 17.8 | 17.3 | complete | complete | 4 | 0 |
| sonnet/materials/cold/B | complete | 256 | 256 | 0 | 56209 | 219.6 | 42.4 | 41.4 | complete | complete | 5 | 0 |
| sonnet/materials/cold/C | complete | 256 | 256 | 0 | 50978 | 199.1 | 42.5 | 41.6 | complete | complete | 4 | 0 |
| sonnet/materials/warm/A | complete | 256 | 256 | 0 | 42805 | 167.2 | 20.1 | 19.5 | complete | complete | 4 | 0 |
| sonnet/materials/warm/C | complete | 256 | 256 | 0 | 42597 | 166.4 | 18.4 | 17.9 | complete | complete | 4 | 0 |

## Gates (A4.10)

- codex materials: verdict invalid, pass False, ratios cold_makespan 3.6391, cold_tokens 0.8371, warm_makespan 1.2470, warm_tokens 0.4758
- sonnet materials: verdict invalid, pass False, ratios cold_makespan 2.3825, cold_tokens 1.1989, warm_makespan 0.9172, warm_tokens 0.9951
- boolq: verdict invalid, pass False, ratios makespan 0.4065, tokens 1.0193
- pooling: verdict invalid, pass False, ratios makespan 1.0882, tokens 0.6910

Claims: codex {'permitted': False, 'rule_learning_claim': False, 'pooling_claim': False}, sonnet {'permitted': False, 'rule_learning_claim': False}, cross backend headline False.

## Magnitude on R (A4.11)

- codex: status invalid, token ratio n/a, makespan ratio n/a, label None, missed []
- sonnet: status invalid, token ratio n/a, makespan ratio n/a, label None, missed []

## Validity

- leakage: 4
- accounting failures: 0
- stopped cells invalid (A4.14.1): ['codex-boolq-cold-A']
- stopped cells interrupted, no finding: ['features']
- simulation: 0
- artifact chain problems: 0
- run bound freeze problems: 0
- classification problems: 0
- interrupted cells: ['features']
- bootstrap codex/boolq: status ok, efficiency valid True, proposed [], admitted [], measured errors {'boolq': 3}
- bootstrap codex/materials: status ok, efficiency valid True, proposed ['margin', 'temp_class', 'verdict'], admitted ['margin', 'temp_class', 'verdict'], measured errors {}
- bootstrap sonnet/materials: status ok, efficiency valid True, proposed [], admitted [], measured errors {}

## Budget (physical calls)

- codex: nominal 29, reserve 0, telemetry 2, total 31 of 62
- sonnet: nominal 20, reserve 0, telemetry 0, total 20 of 40

## Telemetry (reported separately, never in a cell)

- calls: 2, tokens 11519

## Preparation and review calls (A4.13, reported separately)

- current counts {'astra': 26, 'opus': 53, 'fable': 2, 'sonnet': 4, 'codex-owner': 2}, caps {'astra': 30, 'fable': 4, 'opus': 70, 'sonnet': 40}
