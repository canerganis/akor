# OZ/5 Luna live language comprehension experiment: corrected cohort

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

Model: `gpt-6-luna`. The corrected cohort has 12 calls; OZ/5 and the primitive JSON control were compared in the same cohort layout, using two independent repeats. The difficulty of the invalid inputs was not matched.

Scorer revision: 2. The raw model replies were rescored unchanged with a strict JSON parser; valid primitive frames were checked with `Channel.validate` and JSON equality was done in a type-sensitive canonical form.

The earlier faulty cohort is marked `invalidated=true` in a separate archive; the old 12+12 case denominator was not added to this new denominator. The three rejections in the earlier report were not model errors: each of the two mixed matrices opened 6 values/4 IDs, and the second regular matrix gave 2 values/3 IDs. All good/bad inputs were checked with the real `Channel.accept`, `decode_matrix` or `Channel.validate` before the live call; all 24 codec preflight checks gave the expected result. No prompt had a valid/invalid verdict field.

## Results

| Shape | Mode | Strict correct / case denominator | Semantic correct / case denominator | Correct rejection | Wrong rejection of valid | Invalid accepted | Time (s) | Tools |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| simple_form #1 | oz5 | 2/2 | 2/2 | 1 | 0 | 0 | 8.516 | 0 |
| simple_form #1 | primitive_json | 2/2 | 2/2 | 1 | 0 | 0 | 7.0 | 0 |
| regular_matrix #1 | oz5 | 2/2 | 2/2 | 1 | 0 | 0 | 11.469 | 0 |
| regular_matrix #1 | primitive_json | 2/2 | 2/2 | 1 | 0 | 0 | 7.687 | 0 |
| mixed_matrix #1 | oz5 | 2/2 | 2/2 | 1 | 0 | 0 | 10.563 | 0 |
| mixed_matrix #1 | primitive_json | 2/2 | 2/2 | 1 | 0 | 0 | 7.875 | 0 |
| simple_form #2 | oz5 | 2/2 | 2/2 | 1 | 0 | 0 | 7.734 | 0 |
| simple_form #2 | primitive_json | 2/2 | 2/2 | 1 | 0 | 0 | 7.344 | 0 |
| regular_matrix #2 | oz5 | 2/2 | 2/2 | 1 | 0 | 0 | 7.859 | 0 |
| regular_matrix #2 | primitive_json | 2/2 | 2/2 | 1 | 0 | 0 | 10.328 | 0 |
| mixed_matrix #2 | oz5 | 2/2 | 2/2 | 1 | 0 | 0 | 24.297 | 0 |
| mixed_matrix #2 | primitive_json | 2/2 | 2/2 | 1 | 0 | 0 | 13.25 | 0 |

oz5: strict 12/12, semantic 12/12; categories {"correct_rejection": 6, "exact_success": 6}.

primitive_json: strict 12/12, semantic 12/12; categories {"correct_rejection": 6, "exact_success": 6}.

The strict score requires the descriptive enum values (`read`, `audit`, `test`, `propose`) and the exact ID/frame/atom order. The semantic score also normalizes the known wire symbols (`r`, `a`, `t`, `>`) to the same primitive names; references and orders must still be exact.

The invalid examples are not of matched difficulty: on the OZ/5 side a missing Form slot, a column length error or a zero ref; in the primitive control a missing/null required ref was used every time. For this reason the 12/12 results show only that each format conforms to its codec contract on these synthetic cases; they do not show equal difficulty, superiority or parity.

## Tokens and time

| Usage field | Provider total |
|---|---:|
| input_tokens | 302552 |
| cached_input_tokens | 194560 |
| output_tokens | 2770 |
| reasoning_output_tokens | 1198 |

Local `o200k_base` prompt estimate: 7676 tokens; separate from the provider input/cached/output/reasoning fields. The times are the local wall time of each CLI process.

The scope is synthetic protocol comprehension and codec equivalence. Real coding, tool execution, physical verification or production success was not measured. The raw replies and the prompt/fixture hashes are in the JSON report.

## Language improvement

The production `FORM_GRAMMAR` and `WEAVE_GRAMMAR` were sent unchanged; the reply enum was fixed before the call. The independent ID order of the matrix and each column opening to exactly the number of IDs is the critical rule. Teaching these limits by adding one valid/invalid mixed example can be tried in the next prompt version.
