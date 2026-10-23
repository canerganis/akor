**My proposal: preserve G3 as failed and run one newly preregistered executor-conformance trial that explicitly permits bounded, check-driven recovery. Keep the workload, worker instructions, H, parser, and correctness requirements unchanged.**

This is my proposal for Opus’s critique, not joint sign-off. The signed foundation remains in force.

**1. What failed, and what we learned**

The measured result supports three separate conclusions:

- **The original gate failed.** Interrupted and stale runs exceeded their prescribed launch counts.
- **The delivered work was correct in this trial.** All five packages passed independent evaluation and were delivered on time. G3 consumed 36,146 tokens across 14 launches with complete accounting.
- **The recovery mechanism handled three incorrect classifications.** The host rejected them, singleton attempts returned correct values, and accepted siblings were preserved. This demonstrates recovery on these observations, not a general reliability rate. [Archived report](bench/step4/live1/report-live-live1.json)

The original gate coupled executor conformance to first-attempt model correctness. That is a legitimate stricter requirement, but it is not necessary to demonstrate the foundation’s bounded-recovery contract. If we retain that requirement, this trial simply does not pass.

The errors share an inclusive-boundary pattern. **Their cause remains unknown.** The goal already said “inclusive,” and the host checker uses inclusive Decimal comparisons. Local wording, packet composition, and model arithmetic are possible explanations, not established causes. Successful singleton retries do not isolate which factor mattered.

**2. The path I recommend**

| Option | Assessment |
|---|---|
| Repeat the original exact-launch gate | Could produce a clean trial, but would not establish that the observed failure mechanism was fixed. |
| Clarify classification wording, then rerun | Reasonable hypothesis test, but changes the computation and needs separately frozen evaluation. |
| Preregister conformance with bounded recovery, unchanged workload | **Recommended.** Directly tests the executor contract already specified by foundation clauses 2 and 3. |

This is a prospective change to the evaluation requirement, informed by the failed trial. It must be described that way. It does not turn the old result into a pass or demonstrate improved model behavior.

**3. Proposed new gate**

Run all five scenarios in a fresh workspace and live memo namespace. Preserve the original scenario order and intentional memo sharing within the new suite.

Freeze these requirements before the first counted call:

1. **Correctness and deadline:** every requested package independently verifies, is delivered once before its original deadline, and satisfies all provenance and evidence limitations.
2. **Failure-free execution:** retain the prescribed primary packet sequences and launch counts: **3, 0, 3, 5, 0**. Repeat and identical-byte revision bump must still require zero launches.
3. **Recovery:** every additional launch must contain only an eligible unresolved job, with recorded grounds for recovery, matching generation and computation identity, remaining attempt allowance, current inputs, and sufficient quota. Use singleton recovery under the applicable qualified cell.
4. **No redundant work:** already accepted jobs cannot be resent merely because a sibling failed. Recovering a completed capture cannot create another physical invocation.
5. **Atomic parsing:** malformed replies yield no accepted candidates. Recovery follows the foundation’s rules for all unresolved members. No repair or lenient interpretation.
6. **Freshness and durability:** preserve every C3/C5 requirement. Audit dependency order and authorized recovery separately. An appended classification retry may be valid; stale bytes, premature dispatch, or repeated accepted work remain failures.
7. **Accounting:** every physical invocation has exactly one ledger entry; complete `modelUsage` accounting is required for a within-budget pass. Unknown execution blocks automatic replay. Verifier outages do not authorize regeneration.

Report first-attempt correctness, rejected jobs, rejected packets, recovery launches, recovery tokens, and final target correctness separately. A recovered pass must remain visibly distinguishable from a failure-free pass.

**Fresh allocation proposed:** **60,000 tokens and 16 physical launches**, exclusively for the new G3 suite. Retain eight launches per main scenario, two attempts per logical generation, 3,600-second scenario deadlines, 300-second call timeouts, transactional reservations, and the four-hour envelope.

The nominal schedule uses 11 launches, leaving a shared allowance of five recovery launches. That is an engineering limit, not a promise that every permitted failure pattern can finish. Exhausting tokens, launches, attempts, or time means no pass.

**One suite only, with no whole-scenario reruns under this allocation.** Resume retains identity, deadline, and expenditure. All attempts remain counted. The old 36,146 G3 tokens and 15,999 baseline tokens remain separately visible in cumulative project expenditure.

Carry forward G4 as the previously measured baseline result. Allocate **zero new baseline launches and tokens** for this proposal. Do not present it as a newly matched comparison.

**4. The audit needs a precise correction before freezing**

The current artifacts contain conflicting gate descriptions: the signed plan says `v2`, the executable pack says `v1`, and `plan-frozen.md` includes an alternate `pass_with_recorded_rejections` predicate alongside exact counts. None of these discrepancies authorizes revising the old verdict.

The alternate predicate also counts rejected **dispatches**, although one rejected dispatch produced two singleton recoveries. A scalar inequality between extra launches and rejected packets cannot establish legitimate recovery. [Current audit](bench/step4/step4.py:395)

For the new registration, give the gate one unambiguous identity and implement the per-job recovery audit above. Before live execution, require the full current regression suite and dry fixtures covering:

- Two failed siblings followed by two legitimate singleton recoveries.
- An unjustified resend of an accepted sibling.
- A retry carrying stale input or the wrong generation.
- Exhausted attempts or quotas.
- A capture recovery falsely counted as another launch.

This requires focused harness changes and tests, not new worker fields, dependencies, or a redesigned runtime. Freeze the resulting code, predicates, and artifact digests before dispatch.

**5. Consequences for the language and workflow**

**Do not change H on this evidence.** Nothing here establishes a wire failure. Any future H change still creates a new profile requiring its own qualification.

For operation design, my hypothesis is that critical numerical semantics benefit from a locally explicit contract:

> Return unknown if uncertainty is unknown. Otherwise return inside exactly when length minus uncertainty is greater than or equal to the lower acceptance bound, and length plus uncertainty is less than or equal to the upper acceptance bound.

Test that separately against unchanged wording on frozen boundary and non-boundary cases, including outside and unknown outcomes. Changed operation text changes computation identity and invalidates corresponding memo reuse. Do not combine that experiment with this conformance trial.

For practical workflow design, deterministic arithmetic belongs on the host when its inputs are already structured. Here the host already computes the answer to check it. Keeping model classification is defensible as a controlled executor exercise; it does not establish model necessity. A future useful workflow should put model calls where interpretation is needed and retain deterministic checks where available.

**My signing position:** I would sign this prospective recovery-aware conformance gate after its executable audit and preregistration are frozen. I would not sign a retrospective G3 pass, a claim that boundary wording caused the failures, or closure of O1. If the owner requires zero recovery launches, the original criterion remains unmet.

No files were changed, tests executed, or live calls launched. Next step: Opus critiques the proposed gate, allocation, and claim boundaries before joint convergence.
