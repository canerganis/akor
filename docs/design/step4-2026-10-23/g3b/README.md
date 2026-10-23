# G3b: recovery-aware rerun of step 4's live gate (Astra and Opus 5.5, 2026-10-23)

Rounds: [01 Astra](01-astra-r1.md), [02 Opus](02-opus-r1.md), [03 Astra, signed plan](03-astra-r2-signed.md),
[04 Opus critique](04-opus-r2.md), [05 Opus sign-off](05-opus-r3-sign.md). The signed text is round 03.

Agreed: live1's G3 stays failed and is not rescored. A new, prospectively preregistered gate G3b runs the same
workload, op texts, route, wire and compositions in a fresh workspace, one suite, no scenario reruns. It passes only
if every delivery is verified on time, the primary packet sequences and memo hits match the table, every resend is
eligible (grounds, generation, identity, current inputs, attempts, quota) and the exact dispatch trace equals the one
an independent evaluator derives from the recorded per-member check verdicts (attempt 2, in order, never a third
attempt: singleton resends while fewer than four members of a size-4 packet are rejected, one size-4 resend when all
four are, which an atomic wire rejection always is; that size-4 resend repeats the experimental composition and is
not qualified singleton recovery; the policy's worst case exceeds the per-scenario cap of 10 launches, so the caps
bind and running out means no pass; this packing rule was agreed by Astra and Opus after the build). Allocation 64,000 tokens, 24 launches, 10 per scenario; expected
about 36k. G4 carries forward; no optional probe allocation. A zero-token dry gate with the recovery fixtures and
sabotage cases (whole-packet resend, accepted-member resend, size-2 resend, third attempt, skipped resend, stale
generation, exhausted quota, recovered capture counted as a launch, verifier outage triggering regeneration) must pass
first, and a read-only replay of live1 tests the predicate code only.

Thinking tokens are recorded per call. Their link to the three wrong answers is an observed association, not an
established cause. Status: signed and built through the zero-token dry gate; the preregistration is [plan-frozen.md](plan-frozen.md). No live call has been made.
