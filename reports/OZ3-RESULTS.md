# OZ/3 measurement: 11 October 2026

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

Package 0.5.0; tiktoken 0.14.0. Run: `python -X utf8 oz3_benchmark.py`. [Raw results](oz3-token-counts.json). Synthetic local measurement; **real model calls and tool executions: 0**.

## Command cost

Under the dictionary `VN=rNaNt30`, `V[1:16]` expands into 48 primitive operation requests. **6 command tokens** on both tokenizers. The same explicit operation sequence is 96 tokens: a **93.75%** reduction in the command body alone. This comparison leaves out the vocabulary, context, message ids and reply format; it is not a total API saving.

## Full receiver input

All the required source texts, the grammar, the macro definitions used, the message ids and the Worker JSON reply contract are included. The starting point is the result of the old OZ/2 selector in the same context among its short text, JSON and OZ candidates; it is not compared only against a long natural language description. The compiler used both tokenizers at the same time.

| Synthetic workload | o200k before → after | cl100k before → after |
|---|---:|---:|
| Single read | 182 → 182 | 181 → 181 |
| Read of 16 targets | 707 → 707 | 704 → 704 |
| Predefined macro, 4 × 48 operations | 921 → 899 | 916 → 894 |
| Repetition starting without a dictionary, 4 × 48 operations | 1,133 → 899 | 1,127 → 894 |
| 30 operations in irregular order | 610 → 608 | 607 → 606 |
| New free text | 192 → 192 | 192 → 192 |

The saving on the repeated job that starts without a dictionary is **20.65% / 20.67%**. If a good hand-defined macro already exists, the additional saving is **2.39% / 2.40%**. This distinction matters so that the gain is not made to look larger than it is against an existing good dictionary.

In the same 4 × 48 operation example, short text is 3,180 / 3,178 and compact JSON 1,655 / 1,652 tokens. The OZ/3 result is 899 / 894. These two non-weak alternatives carry the same operation rules and sources; equal task success of the models was not measured.

On two messages kept out of the compilation, the unused macros of the new dictionary were not added to the input: cost **304 → 304 / 302 → 302**. This small check is not evidence that generalizes to all future workloads.

## Verification and limits

- 161 unit/integration tests passed. 18 tests for OZ/3; the primitive expansion of at most 16 encoding candidates was verified on each of 180 randomly ordered job sequences.
- Order, repeats, reference types, sources containing uncertainty/number/unit and new texts including CRLF are preserved. Evidence or completion reports are not taken into macros.
- Bad ranges, missing targets, incompatible types, an old context id and expansions beyond 64 operations are rejected.
- The context hash of the OZ/2 example taken from 0.4.0 stayed the same; SQLite reopening and the CLI's portable output package were tested.
- The compiler does a bounded, greedy search. Macro ordering is an estimate; the acceptance decision is based on the full-input token count. There is no global minimum guarantee.
- The local compile times are in the raw report as a single run; they do not count as model latency or a comparative speedup.
- The sender's dictionary learning cost, generation/reasoning tokens, tool outputs, retries, carrier provider fields and live task success were not measured.
- No new live model comprehension test was done for OZ/3. The old OZ/2 live pilot did not cover the vectors.
