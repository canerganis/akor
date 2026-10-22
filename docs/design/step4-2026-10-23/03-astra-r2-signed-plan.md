**I sign `inspection-handoff-20/v2` as the step 4 executor conformance gate, with the amendments below.** It demonstrates execution and recovery on controlled records. Model necessity and live model-to-model handoff remain unproven.

Accounting correction accepted: at `fabbc8a`, the adapter uses `modelUsage` when present and falls back to last-turn `usage` only when absent. Opus’s “when empty” description is incorrect. The absent-field fallback still cannot support whole-call accounting.

**O1–O3**

- **O1, recommendation to the owner:** accept this workflow plus its baseline as the technical step 4 gate. Record a model-necessary workflow afterward, before claiming practical model-workflow usefulness. Until the owner decides, report “conformance passed,” not unconditional completion of the owner’s real-workflow criterion.
- **O2:** experimental composition with oracle proof. No additional ten-call composition gate.
- **O3:** the baseline belongs in the step 4 record. It informs M14 but does not establish a general inline-versus-executor threshold. Separately, a CLI version change blocks further dispatch under this freeze.

**C1–C8 disposition**

| Change | Decision |
|---|---|
| **C1** | Accept. Qualification identity includes composition. The three homogeneous size-4 stages are experimental. Singleton recovery uses the existing qualified cells only when all their dimensions match. Composition stays separate from per-job computation identity under the declared independence contract. |
| **C2** | Accept. Pin adapter argv and script digest, canonical model ID, effort, CLI version, wire digest and parser behavior version. Freeze any alias-to-canonical mapping. Verify envelope model IDs before acceptance; missing identity or unexpected models block acceptance. Fixture and live memo namespaces must be disjoint. |
| **C3** | Accept all four observables. Explicitly record mutation commitment and subsequent dispatch ordering. Final correctness alone cannot pass this scenario. |
| **C4** | Accept. SQLite is authoritative. Check the entire relevant revision read-set and commit acceptance or delivery in the same transaction. Imported files are not a competing authority. |
| **C5** | Accept. Keep request-specific acceptance IDs, timestamps and capture links in the manifest so artifacts can remain byte-identical. Run each negative check on an isolated copy of clean state. The strengthened check must be acceptance-only. |
| **C6** | Accept all dry scenarios and sabotage fixtures. Capture recovery is legitimate; falsely recording recovered evidence as another physical invocation must fail. |
| **C7** | Accept. Hard exits, same resume command and request identity, original deadline and consumed budget, no database repair. Live interruption still totals three launches. |
| **C8** | Accept with reporting changes. Freeze the baseline’s complete semantic JSON contract, including provenance and follow-ups, without executor-specific receipts. Use the same independent semantic evaluator. Markdown, durable publication and crash recovery remain explicitly outside baseline coverage. |

For C8, report four measured baseline calls separately from any five-scenario projection. Do not divide four calls by five scenarios and call that measured amortization. Repeat, revision-bump and interruption costs are explicitly counterfactual estimates; a killed baseline call’s consumed tokens are unknown. No winner is assumed.

**Final signed execution plan**

- **Workflow:** retain the original 20 nodes: snapshot; four extractions; host join; four bounds jobs; validation barrier; four classifications; host follow-ups; JSON/Markdown fan-out; independent verification; durable publication. One target, weight 1. Use frozen live2 records and unchanged `MAT_D` e/b/v instructions; compute m on the host. Parameterize record sets without adding M9 runs.
- **Route:** Sonnet 5.5, default effort, authenticated `claude -p`, no tools, unchanged H, durable execution and `oz1g-selective-v1`. No planner, importer, `host.map`, cross-run batching or filler jobs.
- **Executor:** shared service admission and execution, persisted graph/descriptors, current dependency evidence, conditional commits, authorized memo reuse, durable dispatch-bound captures, stable publication intent and reconciliation, raw-envelope retention and whole-call accounting. **Keep transactional quota reservations on the live path.** Contention testing may be fixture-only; reservation enforcement may not.
- **Scenarios:** clean; exact repeat; interrupted cold run with both kills; stale-input cold run; identical-byte revision bump using clean memo. Expected launches: **3, 0, 3, 5, 0**. Preserve C3’s selective-recomputation evidence and all C5 checks.
- **Budget:** executor approximately **28.5k estimated tokens**, maximum **60k tokens / 16 launches**, eight launches per main scenario, two attempts per logical generation. Reserve 5k per launch as empirical headroom, not a hard output bound. Baseline: four expected calls, **20k tokens / five launches**, with admission headroom based initially on the 6k upper estimate. Both arms share the four-hour envelope; scenarios retain 3,600-second deadlines and calls a 300-second timeout. One model-reply-failure scenario rerun is permitted within the same caps; failed work remains counted.

**Gates:** G0 freezes contracts, expected values, route, hooks, baseline prompt, budgets and digests. G1 passes the full current regression and focused fault suites. G2 passes the complete zero-token dry gate. G3 records all five live scenarios and C3/C5 observables. G4 records the baseline. The final report follows clause 13.

Incomplete accounting preserves independently established correctness but **blocks an overall within-budget pass and exact cost comparison**. Uncertain execution blocks automatic replay. An executor bug requires fixing, refreezing and rerunning all G3; previous expenditure remains charged, and exhausted caps require a new allocation.

These amendments are my signature conditions. O1 remains the owner’s decision. No implementation or live validation is claimed.
