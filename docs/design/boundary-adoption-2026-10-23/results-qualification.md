# Adoption qualification attempt 1: fail at call 9 (size-4 cell)

Freeze e4da3c71 (executor at 2747f32, approved by Astra after two rejected rounds), Sonnet 5.5, CLI 2.1.306, frozen
order with size-4 calls first. Evidence: `bench/step4/adopt-qual/` (report, ledger, every request and envelope).

| Call | Goal | Cases | Result | Thinking tokens |
|---:|---|---|---|---:|
| 1 to 4 | 1, [12.48, 12.52] | all four quartets | 4/4 right each | 114 to 143 |
| 5 | 2, [10.00, 10.08] | 1, 5, 3, 8 | 4/4 | 121 |
| 6 | 2 | 8, 3, 5, 1 | 4/4 | 0 |
| 7 | 2 | 2, 6, 4, 7 | 4/4 | 136 |
| 8 | 2 | 7, 4, 6, 2 | 4/4 | 0 |
| 9 | 3, [12.46, 12.54] | 1, 5, 3, 8 | **3/4**: case 3, interval [12.48, 12.54] (upper bound equal to the limit), answered "outside", correct "inside" | 0 |

The first call that did not pass ended the attempt for good (25,506 tokens, 9 of 36 launches). Size-4 cell: fail;
size-1 cell: untested; the suite did not run; adoption is not passed. Another attempt needs a new preregistration.

What it shows: passing the host-checked interval to the classifier removed the errors on the probe's packet (6 of 6,
goal 1) but does not generalize: on goal 3 the model again misread equality at the upper limit, again with zero hidden
reasoning. Two zero-thinking calls (6 and 8) were right, so zero thinking does not by itself cause the error. Across
every live classification so far, every wrong answer came from a zero-thinking call.

Open for Astra and Opus: this classification is computable exactly by the host from the checked interval and the goal
limits, which the foundation record and Opus's earlier lesson ("flag model ops the host can compute") point to.
