# Cross-producer pooling: D / P / A on BoolQ (live, 2026-10-26)

Runner `bench/pool/pool.py` (commit 16437b0, reviewed by Astra, three defects fixed before the run). Sonnet 5.5,
default effort, `claude -p` with no tools. Four producers × 8 BoolQ questions (pinned sample of
`bench/ozmap/data.py`, gold labels never sent). All jobs arrive at t0, no queue wait: the best case for pooling.
D = each producer one direct call, four calls concurrently. P = a plain shared queue, one direct call with all 32.
A = the same queue, one OZ/1g packet (the shipped wire). Raw: `bench/pool/live/`. No retries, no rejected reply, no
call without usage in either run.

| Run (order) | Arm | Calls | Input | Output | Thinking | Total tokens | Correct | Makespan s |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 (D,P,A) | D | 4 | 15,626 | 317 | 0 | 15,943 | 26/32 | 6.0 |
| 1 | P | 1 | 9,590 | 282 | 0 | 9,872 | 27/32 | 6.5 |
| 1 | A | 1 | 10,160 | 1,142 | 726 | 11,302 | 30/32 | 13.6 |
| 2 (A,P,D) | A | 1 | 10,164 | 1,203 | 787 | 11,367 | 30/32 | 13.9 |
| 2 | P | 1 | 9,587 | 282 | 0 | 9,869 | 27/32 | 6.3 |
| 2 | D | 4 | 15,627 | 326 | 0 | 15,953 | 28/32 | 6.2 |

Ratios to D (run 1, run 2): P tokens 0.62, 0.62; P makespan 1.08, 1.01. A tokens 0.71, 0.71; A makespan 2.26, 2.23.

Gate (A tokens at most 0.80 × D, makespan and worst producer latency at most 1.10 × D, accuracy not lower):
**A fails on latency.** P meets every condition in both runs.

Findings.
1. Pooling is the saving: one call instead of four removes the repeated per-call input (about 15.6k → 9.6k input
   tokens, -38% total) at about the same wall time. A plain queue gets all of it; it is not specific to OZ/1g.
2. The OZ/1g wire triggers hidden reasoning on Sonnet at default effort (726 and 787 thinking tokens; the plain
   prompts got 0), which doubles wall time and makes A 14% more expensive than P. The same pattern appeared with
   OZ/F1 ([results-2.md](results-2.md)).
3. A answered 30/32 in both runs, P 27/32, D 26 and 28. The reasoning appears to buy accuracy on this sample. Same
   32 questions in both runs, so this is consistent but not a general accuracy claim.
