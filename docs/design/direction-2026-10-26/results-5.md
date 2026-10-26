# Results 5: 64-job pilot on four models (2026-10-27)

Same prompts and jobs on every model (manifest `ce579b4f`), 64 materials jobs per seed, seeds 3105 to 3107, 192 jobs per
arm. Strict judging, no reply retry. Data: `bench/live/data/pilot2_{sonnet,opus,haiku,fable}64.jsonl`.

Arms: H one OZ/1g call with all jobs, J one plain JSON call with all jobs, P one plain JSON call per job, S one
orchestrator call that spawns one subagent per job.

## Tokens per verified job

| Model | H | J | P | S | Correct H / J / P / S |
|---|---:|---:|---:|---:|---|
| Sonnet 5.5 | 91.6 | 151.1 | 2,834 | 7,931 | 192 / 192 / 139 / 188 |
| Opus 5.5 | 92.4 | 154.2 | 5,150 | 8,780 | 192 / 192 / 92 / 192 |
| Haiku 5.5 | 154.2 | 204.2 | 4,452 | 10,841 | 176 / 176 / 119 / 161 |
| Fable 5.1 | 97.2 | 157.7 | 3,504 | 13,110 | 192 / 192 / 134 / 127 |

## Ratios against H

| Model | P/H per requested job | P/H per verified job, strict | P/H per verified job, lenient | S/H per verified job | J/H |
|---|---:|---:|---:|---:|---:|
| Sonnet 5.5 | 22.4 | 30.9 | 30.9 | 86.6 | 1.65 |
| Opus 5.5 | 26.7 | 55.7 | 38.0 | 95.0 | 1.67 |
| Haiku 5.5 | 17.9 | 28.9 | 28.9 | 70.3 | 1.32 |
| Fable 5.1 | 25.2 | 36.1 | 33.3 | 134.9 | 1.62 |

"Per requested job" divides all tokens by 192 and ignores correctness. "Lenient" re-judges the P replies the strict
decoder rejected on their last JSON object (`bench/live/pilot2_lenient.py`, measurement only).

## What this shows

1. The batching gap holds on every model: one call per job costs 18x to 27x more tokens per requested job than one
   batched call, and 29x to 38x more per verified job when format failures are forgiven.
2. The Sonnet 31x figure is not an outlier. Opus is higher strictly (56x) because 73 of its 192 single-job replies put
   prose or a Markdown fence before the JSON; all 73 parse leniently, and 43 of them are correct.
3. Single-job calls are also less accurate in content, not only in format: even leniently, Sonnet gets 139/192 and Opus
   135/192 against 192/192 batched. The trimmed single-job prompt is a likely cause and is checked next (harness item 1).
4. The format effect is small next to the call effect: J/H is 1.3x to 1.7x, P/H is 18x or more.
5. Subagent fan-out is the most expensive way on every model, 70x to 135x per verified job, and loses accuracy on Haiku
   and Fable.

## Limits

One task family (materials extraction and interval checks), three seeds, concurrency 1. P has no reply retry; a retry
would recover some format failures at the cost of more calls. Haiku scores 176/192 in both H and J, so its misses are
not caused by either batched format.
