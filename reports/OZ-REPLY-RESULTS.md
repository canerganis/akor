# OZ/6 reply format measurement

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

This combined report contains 6 live model calls and 0 offline benchmark model calls.

## Offline fixture comparison

`o200k_base` and `cl100k_base` were used. On the input side only the additional reply contract was counted; the shared task input, ids, provider wrapper and retries are left out. The output tokens are an estimate from fixture texts that are explicitly labeled synthetic and filled into the JSON; they are not model output or provider usage.

| Job count | Ids | Statuses | o200k input Δ | o200k output saving | o200k net saving | cl100k input Δ | cl100k output saving | cl100k net saving |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | short | same | +51 | -6 | -57 | +51 | -5 | -56 |
| 1 | short | mixed requested; single job=0 | +51 | -6 | -57 | +51 | -5 | -56 |
| 1 | long | same | +51 | -2 | -53 | +51 | -1 | -52 |
| 1 | long | mixed requested; single job=0 | +51 | -2 | -53 | +51 | -1 | -52 |
| 4 | short | same | +51 | +15 | -36 | +51 | +16 | -35 |
| 4 | short | mixed | +51 | +9 | -42 | +51 | +10 | -41 |
| 4 | long | same | +51 | +31 | -20 | +51 | +32 | -19 |
| 4 | long | mixed | +51 | +25 | -26 | +51 | +26 | -25 |
| 16 | short | same | +51 | +99 | +48 | +51 | +100 | +49 |
| 16 | short | mixed | +51 | +69 | +18 | +51 | +70 | +19 |
| 16 | long | same | +51 | +163 | +112 | +51 | +164 | +113 |
| 16 | long | mixed | +51 | +133 | +82 | +51 | +134 | +83 |
| 64 | short | same | +51 | +435 | +384 | +51 | +436 | +385 |
| 64 | short | mixed | +51 | +309 | +258 | +51 | +310 | +259 |
| 64 | long | same | +51 | +691 | +640 | +51 | +692 | +641 |
| 64 | long | mixed | +51 | +565 | +514 | +51 | +566 | +515 |

`Input Δ` is the lanes contract minus the rows contract. `Net saving` adds the contract difference and the fixture output saving; a positive value favors lanes.

## Live gpt-6-luna format trials

Each matched example compares the same jobs in the rows and lanes formats in separate calls. The exact scorer checks the job count, order, status and text; for the lanes output it also verifies the receipt. The provider's `turn.completed` usage values are shown; the Codex system context and wrapper are included in the full-input counts. These values should not be compared with the contract token count alone.

| Job count | Ids | Exact scorer | Provider input tokens rows → lanes | Provider output tokens rows → lanes | Input + output total rows → lanes |
|---:|---|---|---:|---:|---:|
| 1 | short | passed (both formats) | 24595 → 24656 | 33 → 39 | 24628 → 24695 |
| 16 | long | passed (both formats) | 25124 → 25511 | 468 → 378 | 25592 → 25889 |
| 64 | short | passed (both formats) | 26484 → 26545 | 1574 → 1262 | 28058 → 27807 |

The reasoning output count is given as a sub-field inside `output_tokens`, so it was not added a second time in the total; `cached_input_tokens` was not added to `input_tokens` either. The `usage` object given by the provider is stored raw; unknown fields are not reinterpreted.
No overall improvement or model quality result can be drawn from 3 matched examples.

## Limits

- The offline fixture texts are synthetic; no task or tool was run.
- The token comparison was made only with `tiktoken 0.14.0` for `o200k_base` and `cl100k_base`.
- A single receipt fixture was used; other receipt sequences may cause a small tokenizer difference.
- The provider input tokens also cover the Codex CLI's hidden system context and do not measure the contract difference alone; the provider's `usage` fields are kept raw in the JSON.
- The number of live examples is small and is not enough to generalize comprehension, accuracy or production quality.

The raw live model replies and the full measurements are stored in `oz-reply-results.json`.
