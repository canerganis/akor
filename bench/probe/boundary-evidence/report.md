# Boundary probe report (boundary-probe-2026-10-23)

Freeze digest in the ledger: 520c98e895a6bc0dfb5781cc23d66bd2a1633d11bbdc98141387755428714ac2. Launched 18 of 18, finished 18. Charged for the token ceiling: 48730 of 60000 (a call with unknown usage is charged at 5000).

## Decision

Nominate C for a separately frozen workflow evaluation and composition qualification: C met the criterion alone. No classification failures were observed in six repetitions of this frozen packet.

## Per arm

| Measure | A | B | C |
|---|---|---|---|
| Calls finished | 6 | 6 | 6 |
| Entirely correct, strictly accepted, on time (of 6) | 0 | 5 | 6 |
| Calls with a boundary misclassification (classify_C) | 5 | 0 | 0 |
| Correct members (of 24) | 15/24 | 20/24 | 24/24 |
| Correct boundary members (of 6) | 0/6 | 5/6 | 6/6 |
| Calls: semantic | 5 | 0 | 0 |
| Calls: model_error | 0 | 0 | 0 |
| Calls: wire_rejected | 1 | 1 | 0 |
| Calls: process_failure | 0 | 0 | 0 |
| Calls: deadline | 0 | 0 | 0 |
| Calls with complete accounting | 6 | 6 | 6 |
| Total tokens (known calls) | 15696 | 16549 | 16485 |
| Calls with unknown tokens | 0 | 0 | 0 |
| Tokens per correct on-time member | 1046.4 | 827.5 | 686.9 |
| Call durations (s) | 8.5, 6.4, 6.9, 8.5, 6.4, 7.3 | 8.4, 6.8, 13.4, 7.4, 6.7, 6.3 | 6.5, 6.7, 7.2, 5.5, 6.2, 7.6 |

Failed calls stay in the token numerator. Reliability is judged per call; the four members of a call are not independent trials.

## Fisher exact test (two-sided, descriptive only)

| Comparison | p |
|---|---|
| B vs A (entirely correct calls, 6 vs 6) | 0.0152 |
| C vs A (entirely correct calls, 6 vs 6) | 0.0022 |

## Thinking tokens (observed, not adjusted)

| Arm | thinking = 0 (correct / not) | thinking > 0 (correct / not) | unknown (correct / not) | boundary errors in 0, >0, unknown | known values | within-arm association |
|---|---|---|---|---|---|---|
| A | 6 calls (0 / 6) | 0 calls (0 / 0) | 0 calls (0 / 0) | 5, 0, 0 | [0, 0, 0, 0, 0, 0] | unassessable (a stratum is empty) |
| B | 1 calls (0 / 1) | 5 calls (5 / 0) | 0 calls (0 / 0) | 0, 0, 0 | [0, 90, 102, 105, 117, 124] | assessable |
| C | 5 calls (5 / 0) | 1 calls (1 / 0) | 0 calls (0 / 0) | 0, 0, 0 | [0, 0, 0, 0, 0, 152] | assessable |

A correct zero-thinking call contradicts "positive thinking is necessary". An incorrect positive-thinking call contradicts "positive thinking is sufficient". A shift in thinking between arms is an association, not evidence of mediation.

## Per-call rows

| Slot | Arm | Block | Outcome | Right | Boundary error | Thinking | Input | Cache read | Cache write | Output | Total | Route | s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | A | 1.1 | semantic | 3/4 | yes | 0 | 2 | 0 | 2541 | 61 | 2604 | ok | 8.5 |
| 2 | B | 1.2 | correct | 4/4 | no | 102 | 2 | 603 | 1986 | 163 | 2754 | ok | 8.4 |
| 3 | C | 1.3 | correct | 4/4 | no | 0 | 2 | 603 | 2056 | 61 | 2722 | ok | 6.5 |
| 4 | B | 2.1 | correct | 4/4 | no | 90 | 2 | 1930 | 653 | 151 | 2736 | ok | 6.8 |
| 5 | C | 2.2 | correct | 4/4 | no | 0 | 2 | 2007 | 655 | 61 | 2725 | ok | 6.7 |
| 6 | A | 2.3 | semantic | 3/4 | yes | 0 | 2 | 1890 | 654 | 61 | 2607 | ok | 6.4 |
| 7 | C | 3.1 | correct | 4/4 | no | 0 | 2 | 2007 | 652 | 61 | 2722 | ok | 7.2 |
| 8 | A | 3.2 | semantic | 3/4 | yes | 0 | 2 | 1890 | 654 | 61 | 2607 | ok | 6.9 |
| 9 | B | 3.3 | correct | 4/4 | no | 124 | 2 | 1930 | 654 | 185 | 2771 | ok | 13.4 |
| 10 | A | 4.1 | wire_rejected | 0/4 | no | 0 | 2 | 1890 | 652 | 125 | 2669 | ok | 8.5 |
| 11 | C | 4.2 | correct | 4/4 | no | 0 | 2 | 2007 | 653 | 61 | 2723 | ok | 5.5 |
| 12 | B | 4.3 | correct | 4/4 | no | 117 | 2 | 1930 | 649 | 178 | 2759 | ok | 7.4 |
| 13 | C | 5.1 | correct | 4/4 | no | 0 | 2 | 2007 | 650 | 61 | 2720 | ok | 6.2 |
| 14 | B | 5.2 | correct | 4/4 | no | 105 | 2 | 1930 | 655 | 166 | 2753 | ok | 6.7 |
| 15 | A | 5.3 | semantic | 3/4 | yes | 0 | 2 | 1890 | 649 | 61 | 2602 | ok | 6.4 |
| 16 | B | 6.1 | wire_rejected | 0/4 | no | 0 | 2 | 1930 | 651 | 193 | 2776 | ok | 6.3 |
| 17 | A | 6.2 | semantic | 3/4 | yes | 0 | 2 | 1890 | 654 | 61 | 2607 | ok | 7.3 |
| 18 | C | 6.3 | correct | 4/4 | no | 152 | 2 | 2007 | 651 | 213 | 2873 | ok | 7.6 |

Cache counters depend on schedule position; tokens are counted at full weight. Total = input + cache read + cache write + output over every modelUsage entry; thinking tokens are reported separately and are not added again.

