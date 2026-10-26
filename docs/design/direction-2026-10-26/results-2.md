# OZ/F1 fused executor vs direct CLI workflow (live, 2026-10-26)

Same runner, evaluator, model and caps as [results-1.md](results-1.md); arm `fused` is Astra's OZ/F1 wire
([astra-wire.md](astra-wire.md), `oz_fuse.py`, commit 390ddc8). Pair 3 fused first, pair 4 direct first. All eight
deliveries verified on time, one call each, no wire rejection, no failed call. 8 launches, 63,333 tokens.

| Pair | Arm | Stage | Input | of which cache read | Output | Thinking | Total | Seconds |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 3 | fused | cold | 6,431 | 0 | 4,991 | 2,942 | 11,422 | 33.1 |
| 3 | fused | revision | 3,451 | 0 | 1,125 | 730 | 4,576 | 13.0 |
| 3 | direct | cold | 7,467 | 6,809 | 3,572 | 1,544 | 11,039 | 27.6 |
| 3 | direct | revision | 3,515 | 2,860 | 946 | 555 | 4,461 | 11.3 |
| 4 | direct | cold | 7,463 | 6,809 | 3,945 | 1,923 | 11,408 | 30.9 |
| 4 | direct | revision | 3,511 | 2,860 | 930 | 495 | 4,441 | 11.6 |
| 4 | fused | cold | 6,434 | 5,775 | 4,845 | 2,680 | 11,279 | 33.1 |
| 4 | fused | revision | 3,453 | 2,800 | 1,254 | 822 | 4,707 | 13.7 |

Fused/direct: cold tokens 1.035 and 0.989, time 1.20 and 1.07; revision tokens 1.026 and 1.060, time 1.16 and 1.18.

Gate (astra-2.md: below 1.00 for tokens and time in each stage of each pair): **not met**. Fusion removed the call
penalty of results-1 (AKOR was 1.4x to 1.6x tokens); the remaining gap is reasoning. F1 input is 14% smaller
(6.43k vs 7.47k cold), but hidden reasoning is 1.5x to 1.9x the direct arm's and visible output is about the same
(about 2.0k versus 2.0k cold), so totals land at parity and wall time is longer.

Fixed per-call cost, measured directly (`bench/pool/live/overhead-probe.json`): a `claude -p` call with a one-line
system prompt and a two-word prompt reports 1,916 input tokens (1,914 cache creation). So each extra call costs about
1.9k input tokens before any work; the rest of the gap between the direct prompt (3,707 o200k tokens) and the
reported 7,465 is tokenizer difference, not framing. On this workload the number of calls still dominates: wire
compaction moves the total by a few percent at most.
