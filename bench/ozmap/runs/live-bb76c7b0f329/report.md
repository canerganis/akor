# oz map kill pilot report

Verdict: **invalid: efficiency is not evaluable (validity failed)**

| cell | jobs | correct | incorrect | unresolved | rule errors | fallback errors | coverage | tokens | tokens/correct | makespan s | correct/min | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| codex/boolq/cold/A | 256 | 168 | 14 | 74 | 0 | 0 | 0.0 | 216926 | 1291.226 | 81.406 | 123.824 | incomplete |
| codex/boolq/cold/B | 256 | 223 | 19 | 14 | 0 | 14 | 0.0 | 206268 | 924.969 | 134.266 | 99.653 | incomplete |
| codex/boolq/cold/C | 256 | 225 | 19 | 12 | 0 | 14 | 0.0 | 176184 | 783.04 | 128.452 | 105.098 | incomplete |
| codex/materials/cold/A | 256 | 256 | 0 | 0 | 0 | 0 | 0.0 | 149597 | 584.363 | 52.016 | 295.294 | complete |
| codex/materials/cold/B | 256 | 256 | 0 | 0 | 0 | 0 | 0.75 | 164095 | 640.996 | 130.516 | 117.687 | incomplete |
| codex/materials/cold/C | 256 | 256 | 0 | 0 | 0 | 0 | 0.75 | 74771 | 292.074 | 117.266 | 130.984 | incomplete |
| codex/materials/warm/A | 256 | 256 | 0 | 0 | 0 | 0 | 0.0 | 149332 | 583.328 | 54.828 | 280.149 | incomplete |
| codex/materials/warm/C | 256 | 256 | 0 | 0 | 0 | 0 | 1.0 | 33675 | 131.543 | 33.438 | 459.358 | incomplete |
| sonnet/materials/cold/A | 256 | 256 | 0 | 0 | 0 | 0 | 0.0 | 64514 | 252.008 | 44.844 | 342.521 | complete |
| sonnet/materials/cold/B | 256 | 255 | 1 | 0 | 0 | 1 | 0.0 | 72536 | 284.455 | 85.968 | 177.973 | complete |
| sonnet/materials/cold/C | 256 | 256 | 0 | 0 | 0 | 0 | 0.0 | 70869 | 276.832 | 91.297 | 168.242 | complete |
| sonnet/materials/warm/A | 256 | 252 | 4 | 0 | 0 | 0 | 0.0 | 66687 | 264.631 | 49.0 | 308.571 | complete |
| sonnet/materials/warm/C | 256 | 63 | 1 | 192 | 0 | 1 | 0.0 | 16392 | 260.19 | 42.344 | 89.269 | incomplete |

## Usage evidence

Telemetry for this run: status unverified, accepted True, cache inclusion certified False. Reasons: ["cached_input_tokens did not change on the identical repeat: inclusion not shown"]

- codex/boolq/cold/A: call a5a07e4405f74240ba425e15dcd10e8b (physical) reasoning_unverified: output_tokens - reasoning_output_tokens = 2487 does not match the visible reply (2411 tokens, tolerance 8): reasoning inclusion not shown
- codex/boolq/cold/A: call a5a07e4405f74240ba425e15dcd10e8b (physical) usage_unverified: cached_input_tokens 41472 without certified cache inclusion for the frozen route and freeze
  - codex/boolq/cold/A: claims that need complete usage accounting (token totals, tokens per correct, token ratios; gates 3, 4 and 5) are unavailable for this cell
- codex/boolq/cold/B: call 186633e9b0f64f71ac4c1225a11f2ded (physical) usage_unverified: cached_input_tokens 28160 without certified cache inclusion for the frozen route and freeze
- codex/boolq/cold/B: call 92870cacf933484ba0c23952e80ec65c (physical) usage_unverified: cached_input_tokens 28160 without certified cache inclusion for the frozen route and freeze
- codex/boolq/cold/B: call dda4d7569cc847829c71c6f057be4ce9 (physical) usage_unverified: cached_input_tokens 28160 without certified cache inclusion for the frozen route and freeze
- codex/boolq/cold/B: call ef176334359e4de68892630c65749a25 (physical) usage_unverified: cached_input_tokens 28160 without certified cache inclusion for the frozen route and freeze
  - codex/boolq/cold/B: claims that need complete usage accounting (token totals, tokens per correct, token ratios; gates 3, 4 and 5) are unavailable for this cell
- codex/boolq/cold/C: call 92870cacf933484ba0c23952e80ec65c (imported) usage_unverified: cached_input_tokens 28160 without certified cache inclusion for the frozen route and freeze
  - codex/boolq/cold/C: claims that need complete usage accounting (token totals, tokens per correct, token ratios; gates 3, 4 and 5) are unavailable for this cell
- codex/materials/cold/B: call 88c928f6d4ee4cc988fda62bbd4066aa (physical) usage_unverified: cached_input_tokens 30336 without certified cache inclusion for the frozen route and freeze
- codex/materials/cold/B: call e8e29d6bcab44a94a4b544be85446dbc (physical) usage_unverified: cached_input_tokens 28160 without certified cache inclusion for the frozen route and freeze
  - codex/materials/cold/B: claims that need complete usage accounting (token totals, tokens per correct, token ratios; gates 3, 4 and 5) are unavailable for this cell
- codex/materials/cold/C: call 0066e381710146b3bd69d5b9cdf92aad (physical) usage_unverified: cached_input_tokens 7296 without certified cache inclusion for the frozen route and freeze
  - codex/materials/cold/C: claims that need complete usage accounting (token totals, tokens per correct, token ratios; gates 3, 4 and 5) are unavailable for this cell
- codex/materials/warm/A: call cdbe9ae96a68447d82f7b412a08969aa (physical) usage_unverified: cached_input_tokens 7296 without certified cache inclusion for the frozen route and freeze
  - codex/materials/warm/A: claims that need complete usage accounting (token totals, tokens per correct, token ratios; gates 3, 4 and 5) are unavailable for this cell
- codex/materials/warm/C: call 58da4cff35334c75b01a524163d1c321 (physical) usage_unverified: cached_input_tokens 7296 without certified cache inclusion for the frozen route and freeze
  - codex/materials/warm/C: claims that need complete usage accounting (token totals, tokens per correct, token ratios; gates 3, 4 and 5) are unavailable for this cell

## Preparation cost: telemetry runs

| run dir | calls | tokens | calls without usage |
|---|---|---|---|
| live-538bcde9a80b | 2 | 59475 | 0 |
| live-6a518ece47ab | 2 | 59474 | 0 |
| live-bb76c7b0f329 | 2 | 59460 | 0 |
| live-e744a1525dbf | 2 | 59465 | 0 |
Total: 8 calls, 237874 tokens.

## Gates (ordered)

1. safety: PASS. "no incorrect rule-origin materials answer was accepted"
2. validity: FAIL. ["the run manifest does not attest that gold stayed inaccessible during execution", "codex/boolq/cold/A: tool_use_leakage:au6anhmeymei65rda4jumllzoho7iz554lq63vmpo35iiotx4c7lq", "bootstrap codex/boolq: 5 gold errors"]
3. materials: FAIL. {"codex": {"pass": false, "checks": {"cold_correctness_preserved": true, "cold_tokens_per_correct_ratio<=0.75": true, "warm_makespan_ratio<=0.9": true, "warm_tokens_per_correct_ratio<=0.5": true, "evidence_complete": false}, "cold_tokens_ratio": 0.499816, "cold_makespan_ratio_report_only": 2.254422, "warm_tokens_ratio": 0.225504, "warm_makespan_ratio": 0.609871}, "sonnet": {"pass": false, "checks": {"cold_correctness_preserved": true, "cold_tokens_per_correct_ratio<=0.75": false, "warm_makespan_ratio<=0.9": true, "warm_tokens_per_correct_ratio<=0.5": false, "evidence_complete": false}, "cold_tokens_ratio": 1.098505, "cold_makespan_ratio_report_only": 2.03588, "warm_tokens_ratio": 0.983218, "warm_makespan_ratio": 0.864163}}
4. boolq: FAIL. {"checks": {"no_added_gold_errors": true, "charged_tokens_ratio<=1.10": true, "measured_makespan_ratio<=1.10": false, "evidence_complete": false}, "token_ratio": 0.812185, "time_ratio": 1.577918, "errors_A": 88, "errors_C": 31, "summed_call_seconds_ratio_report_only": 0.868239}
5. pooling: FAIL. {"checks": {"C_tokens<B_tokens": true, "C_correct>=B_correct": true, "C_makespan<=B_makespan": true, "evidence_complete": false}, "B_tokens": 164095, "C_tokens": 74771, "claim": "pooling contribution claim withdrawn"}

Headline permitted: no

Correctness here is gold scoring after the run; the host receipts only state runtime acceptance.
