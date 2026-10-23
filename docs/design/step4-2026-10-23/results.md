# Step 4 live results: G3 not passed as preregistered; G4 passed

Plan: [plan-frozen.md](plan-frozen.md) (freeze 49115f95, after the independent-review refreeze). Sonnet 5.5 through
`claude -p`, CLI 2.1.306, selective profile. Evidence: `bench/step4/live1/` (both reports, every candidate with its
check verdicts, every call ledger, the baseline replies).

## G3, five scenarios (caps 60k tokens and 16 launches)

| Scenario | Launches (expected) | Packets | Memo hits | Tokens | Package verified | Scenario gate |
|---|---:|---|---:|---:|---|---|
| clean | 3 (3) | 4, 4, 4 | 0 | 8,049 | yes | pass |
| exact repeat | 0 (0) | none | 12 | 0 | yes | pass |
| interrupted, two hard kills | 5 (3) | 4, 4, 4, 1, 1 | 0 | 12,860 | yes | **fail** |
| stale input A | 6 (5) | 4, 4, 1, 1, 4, 1 | 6 | 15,237 | yes | **fail** |
| identical-byte revision bump | 0 (0) | none | 20 | 0 | yes | pass |

Totals: 14 launches, 36,146 tokens, accounting complete. Every scenario delivered a package the independent evaluator
verified; both kills resumed with the captured call reused and the manifest reconciled; in the stale scenario no batch
after the change carried the old A bytes, B, C and D were reused on identical inputs, and the delivery cites A
revision 2.

Why two scenarios failed the gate: the model answered three classification jobs wrongly, and the host check
`mat_classify` rejected each one; the job was resent alone and answered correctly. All three are inclusive-boundary
cases:

| Run | Job | Interval | Correct | Model said |
|---|---|---|---|---|
| interrupted | classify_A | 12.50 ± 0.02 = [12.48, 12.52] | inside (bounds are inclusive) | outside |
| interrupted | classify_C | 12.51 ± 0.01 = [12.50, 12.52] | inside | outside |
| stale | classify_C | 12.51 ± 0.01 = [12.50, 12.52] | inside | outside |

The preregistered gate fixed the launch count, so these recoveries fail it, and the result stands as measured. The
plan allows one rerun of a scenario that failed on a model reply, within the same caps; 14 of 16 launches are spent
and a rerun needs at least 3, so none was made.

What this shows beyond the gate: the per-job checks did the job step 3 built them for. Without them, three wrong
values would have reached a delivered handoff; with them, the cost was three single-job resends (7,341 tokens; an earlier version of this file said about 4.8k, which counted only the interrupted run)
and every delivered value is checked.

## G4, no-orchestration baseline (caps 20k tokens and 5 launches): pass

Four single calls, each producing the whole package as JSON: 4 of 4 verified by the same evaluator, 15,999 tokens,
about 4,000 per run. On a cold run the baseline is cheaper than the executor (about 4,000 vs 8,049). The executor's
repeat and identical-byte bump runs cost 0 model tokens; the baseline would pay a full call for each, but those
baseline costs are counterfactual estimates, not measurements. Interruption recovery, durable publication and the
per-job checks are outside the baseline's coverage.

## Status

Conformance is not passed: G3 failed as preregistered. Fixing it needs a new preregistration that either budgets for
check-driven resends or freezes the boundary wording problem first, and a fresh live allocation; that is a decision
for the owner and the two designers. The real-workflow criterion (O1) stays open.
