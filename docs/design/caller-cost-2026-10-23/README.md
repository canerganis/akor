# Cutting the caller-side cost of `oz do` (Astra and Opus 5.5, 2026-10-23)

Problem (measured in [arm K](../foundation-2026-10-23/arm-k-results.md)): a caller agent handing 64 jobs to `oz do`
spends 81% to 89% of the end-to-end tokens on its own side; `oz do` beats one subagent per job by 9 to 10 times but
costs 4 to 5 times more than the caller doing the work itself in one reply.

Rounds: [01 Astra proposal](01-astra-r1.md), [02 Opus critique and counter-plan](02-opus-r1.md),
[03 Astra round 2, signed plan](03-astra-r2-signed-plan.md), [04 Opus sign-off and the frozen continuation task](04-opus-r2-sign.md).

Agreed:
1. The caller decides (goal, operations, which input goes to which job, delivery form); the host does the
   deterministic work (loading references, building the request, running, publishing results). No wire change.
2. One cell is already decided by stored numbers: when the caller already holds every job and must put every
   answer in its reply, `oz do` with the same worker model cannot beat doing the work inline (the caller must read
   the inputs once anyway, and the worker then does the work again). That cell is not re-litigated.
3. The open question is where `oz do` earns its cost: inputs that live in files, results delivered as an artifact
   with a follow-up step, and large references. A 45-run preregistered experiment (48 with a K0 rerun) with gates
   G0 to G3 decides it; see round 03 for blocks, arms and gates and round 04 for the continuation task and oracle.
4. A bounded receipt (at most 2,048 bytes, non-accepted IDs listed up to 32 plus counts) is built in bench first and
   enters the product only if gate G2 passes.
Status: signed by both; harness not built yet.
