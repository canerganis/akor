# Pooling under staggered arrivals, and the format control (live, 2026-10-26)

Decision and gate: [astra-pool-2.md](astra-pool-2.md). Runtime `akor_pool.py` (FIFO, at most 32 jobs, 500 ms wait
from the oldest job), harness `bench/pool/pool2.py` (commits de8a4c0, 09b5782; Astra review defects fixed before
the run). Sonnet 5.5, `claude -p`, no tools. Fresh BoolQ questions per experiment, the same questions within a pair.
32 launches, 164,899 tokens, no retry, no rejected reply, no call without usage. Raw: `bench/pool/live2/`.

## Arrivals: D (each producer calls at its arrival) vs P (pooled)

| Run | Arm | Calls | Tokens | Correct | Makespan s | Worst producer latency s |
|---|---|---:|---:|---:|---:|---:|
| burst 1 (D,P) | D | 4 | 15,055 | 31/32 | 6.55 | 6.10 |
| burst 1 | P | 1 | 8,983 | 30/32 | 7.64 | 7.64 |
| burst 2 (P,D) | P | 1 | 8,981 | 29/32 | 7.16 | 7.16 |
| burst 2 | D | 4 | 15,058 | 31/32 | 6.93 | 6.63 |
| sparse 1 (D,P) | D | 4 | 15,430 | 24/32 | 14.58 | 6.17 |
| sparse 1 | P | 4 | 15,431 | 25/32 | 15.15 | 6.62 |
| sparse 2 (P,D) | P | 4 | 15,438 | 25/32 | 15.36 | 6.36 |
| sparse 2 | D | 4 | 15,416 | 25/32 | 15.28 | 6.28 |

Burst (arrivals 0/0.1/0.3/0.45 s): P/D tokens 0.597 and 0.596; makespan 1.17 and 1.03; worst producer 1.25 and
1.08; accuracy 30 vs 31 and 29 vs 31. **Gate not met** (accuracy below D in both runs, latency above 1.10 in run 1).
Sparse (0/2/5/9 s): tokens 1.00 and 1.00, makespan 1.04 and 1.01, worst producer 1.07 and 1.01, accuracy 25 vs 24
and 25 vs 25. **Gate met**: with nothing to pool the queue costs at most the 500 ms wait.

## Format control (all 32 at t0, pooled into one call)

| Run | Arm | Tokens | Thinking | Correct | Seconds |
|---|---|---:|---:|---:|---:|
| 1 (Pd,Ph,A) | plain, default effort | 8,952 | 0 | 25/32 | 5.92 |
| 1 | plain, effort high | 8,949 | 0 | 29/32 | 6.73 |
| 1 | OZ/1g, default effort | 9,659 | 0 | 24/32 | 9.69 |
| 2 (A,Ph,Pd) | OZ/1g, default effort | 9,656 | 0 | 21/32 | 7.08 |
| 2 | plain, effort high | 8,947 | 0 | 26/32 | 6.58 |
| 2 | plain, default effort | 8,944 | 0 | 26/32 | 6.49 |

OZ/1g did not reason on these questions (0 thinking tokens, unlike [results-3.md](results-3.md)) and scored lowest
(24 and 21) at 8% more tokens and the longest time. The accuracy advantage seen in results-3 does not reproduce, so
no OZ-specific accuracy claim is supported. Effort high reported 0 thinking tokens on this task.

## What holds after four experiments tonight

1. Pooling ready jobs into one call saves about 40% of tokens when jobs arrive together (results-3, burst here),
   because each `claude -p` call carries about 1.9k fixed input tokens. A plain queue gets the whole saving.
2. The cost of pooling is latency (one larger call, plus the wait) and, in the burst runs, one or two answers out of
   32. Accuracy varies about ±3/32 between runs of the same questions, so the accuracy cost is not established
   either way; the frozen gate still counts it as a fail.
3. The compact OZ wires (OZ/1g, OZ/F1) gave no token, speed or accuracy advantage over a plain JSON prompt in these
   tests; when Sonnet reasoned on them it was slower.
