# O1: `repair-handoff-20/v1`, a real workflow for step 4 (Astra and Opus 5.5, 2026-10-23)

The owner decided that step 4 must also be judged on a recorded 20-step workflow whose model jobs genuinely need a
model. Rounds: [01 Astra proposal](01-astra-r1.md), [02 Opus critique M1 to M12](02-opus-r1.md),
[03 Astra accepts all twelve, signed with three technical conditions](03-astra-r2-signed.md),
[04 Opus sign-off](04-opus-r2-sign.md).

The workflow: eight model jobs write function bodies to repair seeded defects (the host can only run and judge code,
not write it); twelve host steps assemble context, run tests and join results. Correctness is judged in three tiers:
A (the per-job check, every boundary covered, every seeded defect must fail it), I (integration tests) and H
(evaluator-only exhaustive domains with expected outputs frozen from two agreeing references). Delivered code must be
byte-identical to an accepted model candidate. Tests run in a confined worker through a controlled launcher that
honors hash seeds 0 and 1, with type-strict comparison. Sizes 4 and 1 run as experimental, qualifying nothing.
Allocation: cap 150k tokens and 18 launches (at most 8 per scenario), reserves measured at G2; expected 70k to 95k
for a failure-free suite. Five scenarios as in step 4, G3b-style exact traces, no baseline, no reruns.
Seeded defects are not real bug reports; the report says so.
Status: signed, not built.
