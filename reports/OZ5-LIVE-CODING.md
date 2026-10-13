# OZ/5 live coding pilot

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

## Result

With the same `gpt-6-luna` model, 5 synthetic Python bugfix tasks were compared in the explicit JSON and OZ/5 compact transport formats. With 5 fixtures and 2 repeats in each format, the denominator is **10 cells/conditions per format, 20 cells in total**; 12 live model calls were made. The model replies were only code proposals; no production file changed. The model ran no tools/tests. The local evaluator ran the accepted candidate functions in a controlled subprocess with fixed hidden tests.

This short pilot does not give a general result about the effect of OZ/5 on code correctness. The observed full passes were 1/10 cells in explicit JSON and 3/10 in compact transport. The test results of the candidates that could be evaluated were 13/14 and 19/19 correct, respectively. Because they were measured with different denominators, they should not be read directly as a success rate on their own: in the remaining cells the candidate source did not meet the explicit AST/call constraints and was not sent to the hidden tests.

## Pinned tasks and cell results

| Fixture | Explicit r1 | Explicit r2 | OZ/5 r1 | OZ/5 r2 |
|---|---|---|---|---|
| `range-clamp` | 7/7 | 6/7 | 7/7 | 7/7 |
| `merge-adjacent` | violated the source constraint | violated the source constraint | violated the source constraint | violated the source constraint |
| `strict-retry-after` | violated the source constraint | violated the source constraint | violated the source constraint | violated the source constraint |
| `chunk-boundaries` | violated the source constraint | violated the source constraint | 5/5 | violated the source constraint |
| `stable-unique` | violated the source constraint | violated the source constraint | violated the source constraint | violated the source constraint |

In every live call the output conformed to the JSON schema and, in the batch replies, to the ID order (6/6 calls/conditions). However, the phrase "return a single `function_source` object" in the shared instructions contradicted the `results` array in the batch instructions. For this reason I do not interpret the batch results as a clean format preference measurement. The hidden test denominator is 66 fixed assertions for each condition, including the eliminated cells; only the cells that passed the AST and source signature check were executed.

The fixtures covered clamping range bounds, merging adjacent closed ranges, strict `Retry-After` input, chunk boundaries and stable deduplication with unhashable values. For each fixture the prompt had the same broken function, behavior requirements and public check examples. The hidden tests were not sent to the model. All five pre-frozen known-good solutions passed the hidden tests; all five buggy starting functions failed at least one test.

## Source and scorer evaluation

The outputs were requested under a `proposal only` contract; no code was applied. The candidates were scored only with a single function, an unchanged full public signature and a bounded Python AST allowlist. Imports, attribute access (including `.append`/`.sort`), I/O and calls that are not allowed were eliminated. JSON duplicate keys and nonfinite values were rejected; the batch ID array was checked so that a missing, extra or reordered one is rejected. Replies that used tools would not be admitted to the hidden tests; none of the 12 calls had a tool event.

The first scorer did not cover the `ast.keyword`/lambda syntax. The raw replies of the first four calls were kept and the V1 observation score was stored separately; the same replies were not requested again. The final scorer covers the allowed built-in keyword/lambda forms and the safe use of `ValueError` raise. The second fix was made after a precheck confirming that the `Raise` syntax is safe and reasonable Python; attribute uses such as `.append`, which are explicitly forbidden in the prompt, were still rejected. For this reason the OZ/5 chunk r1 reply passed 5/5 in the final scorer; the earlier `rejected_ast:Raise` result was an evaluator coverage defect and should not be counted as a model failure. The old and new scores are kept separately in each call record.

After the AST check, the candidates were evaluated in an isolated working folder, with `-I -S`, restricted builtins and a 3-second subprocess timeout. This is a controlled test harness; it is not a claim of a security sandbox. The hidden test execution was done locally; the model called no tools.

## Cost and time

| Measurement | Explicit JSON | OZ/5 compact |
|---|---:|---:|
| Live calls / cells | 6 / 10 | 6 / 10 |
| Provider usage records | 6 | 6 |
| Provider input tokens | 150,792 | 152,727 |
| Cached input tokens | 125,440 | 124,416 |
| Output / reasoning tokens | 3,418 / 1,883 | 3,692 / 2,137 |
| Prompt tokenizer estimate (o200k / cl100k) | 3,559 / 3,526 | 5,478 / 5,456 |
| Known CLI wall-time average | 15.0 s (4/6 calls) | 14.2 s (4/6 calls) |

The provider usage totals sum all the stored usage records of each call; there was one record in each coding call. The readiness call was kept separate. The tokenizer estimates were computed from the prompt texts and are shown separately from provider usage/billing. In this pilot the OZ/5 prompts were about 54% longer than explicit JSON in the tokenizer estimate; the context, dictionary and grammar headers brought extra load. The provider input values may also cover the local CLI's session costs, so they cannot be equated one to one with the prompt size.

The first four recovered calls had no reliable `wall_seconds` record; in the remaining 8 calls the time also includes the local CLI startup and session lifetime. These are not model-only latency. Model access was verified in the same session by explicitly selecting `gpt-6-luna` and in a separate readiness call; the readiness call used 0 tool events. The CLI printed warnings that it ignored an unrecognized field in the existing user settings, gave an unstable-feature notice and clamped a hook timeout value; the settings or the authentication configuration were not changed.

## Reproduction and limits

The full raw model replies, event/usage records, prompt texts, SHA-256 values and deterministic scores are stored in the JSON report and under `.oz-eval/luna-coding/`. `reports/oz5-live-coding.json` contains all 20 cells and every call. `oz5_live_coding.py --rescore-report` rescores the same saved replies and makes no model call. Checks: precheck (known-good/buggy, codec roundtrip and parser conditions), `py_compile`, CLI `--help` and the fixed hidden fixture tests with the scorer.

Five small synthetic fixtures and two short repeats; this is not a measurement of generalizable model ability, production reliability or quality on a real repository change. The batch instruction contradiction, the usage overhead coming from the session and the small number of examples limit the inferences.
