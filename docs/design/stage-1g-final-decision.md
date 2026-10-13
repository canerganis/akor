# Stage 1g final decision (Astra and Fable, 2026-10-13)

Translated from Turkish by Claude Sonnet 5.5; the original text is in git history (commit 5abbc82).

After the C screen failed (stage-1g-screen-evidence.txt), Astra and Fable debated four rounds (stage-1g-debate.md). Astra froze the plan in round 4; Fable confirmed with one objection; Astra dropped the baseline 5/5 rule. Run by bench/live/run1g.py.

## Astra, round 4 (frozen, verbatim)

**Frozen decision: H first; G only if H is eliminated. No C check and no GH experiment. The plan is 70 calls; at most 95 if G is needed.** For the weekly quota I choose the sequential plan that Fable signed.

**Texts and parsers**

- **H:** The H text from Astra Round-2 as it is: C + the mandatory `OZ/1g` header. Profile: `oz1g-header`.
- **G:** The binding content of the G file is the Round-3 **G block** above, as it is and without a header. Profile: `oz1g-lines`.
- **C:** `oz_batch.SYSTEM`; the live21 byte equality reported by the owner is accepted. No new call is set aside.
- **GH:** It stays defined by the one-sentence change in Round-3; it is removed from this experiment.
- **Baseline:** The existing `0.8-exec` text and parser are not changed.

The **ten-item parser contract and the local checks** in Round-3 **apply as they are**. The profile is chosen in the call configuration; there is no automatic detection, repair or format change.

| Stage | Calls and data seeds | Count |
|---|---|---:|
| A | Sonnet 5.5-64, H: **1005-1024**; baseline: **1005,1009,1013,1017,1021** | 25 |
| B | H, if it passes A, Sonnet-64: five heterogeneous packets, **3001-3005** | 5 |
| C | If H is eliminated in A or B, G: the same 20 standard + the same five heterogeneous packets; the baseline is reused | 25 |
| D | The chosen candidate: Haiku 5.5-64 **10+5**, Fable 5.1-64 **5+5**, Luna medium-64 **5+5**, Sonnet-32 **5** | 40 |

In D the standard seeds are **2005-2014** for Haiku and **2005-2009** for the others; the heterogeneous ones are again **3001-3005**. There is no heterogeneous call in Sonnet-32.

Each of the five heterogeneous packets contains **64 jobs**: in order an empty array, a scalar, an object, a nested array and real error results. **In each packet all results are from the relevant family**; so the first record is tested independently of the output order. In the error packet there are 16 jobs for each of the four codes. Together the packets cover zero/many references, reference order, the allowed `unknown` and the `"error"` ID.

**Pass gates**

- Sonnet-64 standard candidate arm: **at least 19/20**; stop at the second failure. Heterogeneous **5/5**, D as a whole **40/40**. Early success is not declared.
- Success = parser acceptance **and the correctness of all jobs**. Needless error/unknown, a wrong value, truncation or timeout is a failure.
- The baseline must be **5/5**; otherwise the comparison is inconclusive and there is no adoption.
- On the Sonnet-64 standard workload, including the consumption of failed calls: the total tokens reported by the provider / verified job **≤ baseline tokens / requested job × 0.65**. **35% is the requirement, 40% the target.** The monetary cost / verified job will also not be higher than the baseline's.
- In the same scope, total `api_ms` / verified job **≤ baseline `api_ms` / requested job**. The mean and the median are reported separately. The uncertainty of five baselines is stated; the threshold is not loosened afterwards.
- Seed-1000 o200k system+body budgets, at 32/64 jobs: **H ≤1020/1479; G ≤991/1450**. These do not replace the provider economic gate.

The cost/speed gates are **for Sonnet-64 only**; D is a compatibility check. The `C_verified` value of both sides and the total experiment spend are reported.

Calls run in independent contexts, with concurrency **1** and all retry layers **0**. The texts, inputs, oracle, settings and program are hashed before the first call. The old five calls are not counted. If D fails, the candidate is not changed; there is no adoption and the existing `0.8-exec` is kept. Early stops can reduce the 70/95 ceilings.

No experiment or file change was made in this turn. Local reading was blocked because of `helper_sandbox_lock_failed`; I could not verify the file path of G, the text reference is the full block above.


## Fable confirmation (verbatim)

Fable: I confirm the frozen plan (H first, G only if H fails, no C or GH, seeds, 64-job single-family heterogeneous packets, Stage D cells, concurrency 1, retry 0, hashed artifacts, Sonnet-64-only cost and speed gates, money cost gate) with one concrete objection.

The "baseline must be 5/5 or nothing is adopted" rule should go: C_requested(0.8-exec) divides by requested jobs, so a baseline packet with a wrong value changes neither that denominator nor the candidate's gate, and the baseline already slipped once in live21 (rep 1, 63/64) and once in live17, so this rule has roughly a one in four chance of voiding 70 calls of the owner's quota over an event unrelated to H. Report baseline failures, count their tokens and time in C_requested as the formula already does, and do not let them block adoption.

## Astra ruling on the objection (verbatim)

**I remove it:** The baseline being **5/5** is not a condition for adoption; a baseline accuracy error alone does not block adopting the candidate.  
The token, monetary cost and `api_ms` consumption of failed baseline calls are included in the `C_requested` computation; the errors and `C_verified` are reported separately.  
The accuracy, cost and speed gates of the candidate are kept as they are; **Stage A continues, no extra calls are needed.**
