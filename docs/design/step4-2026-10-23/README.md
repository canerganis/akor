# Step 4: `inspection-handoff-20/v1` executor conformance gate (Astra and Opus 5.5, 2026-10-23)

Rounds: [01 Astra proposal](01-astra-r1.md), [02 Opus critique C1 to C8](02-opus-r1.md),
[03 Astra round 2, signed plan](03-astra-r2-signed-plan.md), [04 Opus sign-off](04-opus-r2-sign.md).

Signed by both. A 20-node manual graph turns four frozen inspection records into one checked handoff package (one
target, weight 1): three model stages of four jobs each (Sonnet 5.5, `claude -p`, no tools, OZ/1g text H unchanged,
selective profile, run as authorized experimental composition), host joins, a validation barrier, an independent
package check and one durable publication. Five scenarios (clean, exact repeat, interrupted with hard kills, stale
input, identical-byte revision bump), expected launches 3, 0, 3, 5, 0; a zero-token dry gate with sabotage cases
before any paid call; a no-orchestration baseline arm reported separately. Executor cap 60k tokens and 16 launches,
baseline cap 20k and 5. Gates G0 to G4.

Open for the owner (O1): this is a conformance gate. Every model job here could be done exactly by the host, so it
does not by itself satisfy "judged against a recorded 20-step real workflow". Until the owner decides, results are
reported as "conformance passed", not as the real-workflow criterion met. Both recommend recording a model-needing
workflow (for example the live2 code-repair domain) after the live runs pass, without blocking step 4.

Precondition from the review: the Claude adapter must report unknown usage, not last-turn `usage`, when `modelUsage`
is absent or empty.
