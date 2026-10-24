# Codex reasoning tokens are included in output_tokens (evidence for the sign-off)

Astra's sign-off (signoff-astra.md) held on one item: the paired telemetry showed inclusive cached input, but nothing
showed that `reasoning_output_tokens` is inside `output_tokens` rather than counted beside it.

## Recorded evidence

The recorded Codex calls in bench/codex_kit (results_gpt-6.1-sol_*.jsonl and results_gpt-6-astra_*.jsonl, 48 calls
with a reply and usage) were re-read. For each call the visible reply text was tokenized with o200k_base and compared
with the reported counters.

| Reading | Median relative deviation (26 calls with reasoning > 0) |
|---|---:|
| inclusive: output_tokens minus reasoning_output_tokens equals the visible reply | 0.7% |
| exclusive: output_tokens alone equals the visible reply | 10.5% |

Typical rows (visible, output, reasoning, output minus reasoning): 1113, 1324, 205, 1119; 424, 483, 53, 430;
1097, 1156, 53, 1103. The inclusive difference is a near constant of about 6 tokens of framing; the exclusive one
grows with the reasoning count. Under exclusive accounting output_tokens would equal the visible reply, which it
does not. So output_tokens already includes the reasoning tokens.

## Binding to the frozen route

The recorded calls ran on older CLI builds, so the live certification does not rely on them. `pilot.py telemetry`
now also requires, on each of its two calls on the frozen Codex worker, that output_tokens minus
reasoning_output_tokens equal the visible reply's o200k tokens within 8 tokens (the recorded framing residual is
always 4 or 6), and that output_tokens alone does not also match within 8, whatever the reasoning size (Astra sign-off
2: otherwise the two readings are indistinguishable). Without a tokenizer or a visible reply the certification fails.
Because 8 of 12 recorded gpt-6.1-sol medium calls reported zero reasoning, which can never certify, the pilot runs
Codex at effort high (all 12 recorded high calls reasoned, 30 to 205 tokens); every Codex arm uses the same effort. Functions: bench/ozmap/pilot.py `visible_tokens`,
`reasoning_inclusion`, `certify_codex`.
