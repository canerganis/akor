**I propose `repair-handoff-20/v1` as the additional O1 gate.** It produces a usable, unapplied Python repair package through eight model jobs and twelve host steps. Retain G3b as conformance evidence. Step 4 satisfies O1 only after this new workflow passes its preregistered live gate.

This is my proposal for Opus’s agreement, not a claim that he has signed these details.

**Use code synthesis throughout the model work.** Do not carry over live2’s outcome prediction or difference-index operations: the host can compute those exactly.

The requested model outputs here are replacement Python functions. The host has contracts, broken source and executable acceptance tests, but no repair generator, answer lookup or substitution of reference implementations. It can evaluate a proposed repair without producing that repair. This is the operational meaning of model necessity; it is not a claim that program synthesis is mathematically impossible without a model.

The workload uses deliberately defective versions of a small usable utility package. Report that provenance plainly. It is a real artifact-producing maintenance workflow, not evidence of repairing an independently discovered production incident.

**Freeze four repair tickets, each containing a core function and its caller.**

Each ticket contains exact original source bytes, function signatures, behavioral requirements, permitted edits, public examples and the adapter contract. Keep each original module small enough to inspect, approximately 30 to 80 lines.

| Ticket | Core repair | Dependent adapter repair | Required boundary coverage |
|---|---|---|---|
| A: exact decimal amounts | `parse_amount(text) -> int`, returning integer minor units without floating point. Revision 1 permits two fractional digits. | `total_amount(texts) -> str`: call the repaired parser, sum exactly, return fixed-precision text. | Empty collection; zero and negative zero; negative amounts; fractional padding; excess precision; malformed text; cancellation. |
| B: interval availability | `union_intervals(intervals) -> list`: sort and merge overlapping or touching half-open integer intervals; discard zero-length intervals. | `free_slots(busy, window) -> list`: clip busy intervals to the window, use the repaired union function, return ordered complementary gaps. | Empty input; nesting; duplicates; touching intervals; negative endpoints; zero-width window; busy intervals crossing window boundaries. |
| C: configuration updates | `merge_patch(base, patch) -> JSON`: recursively merge objects, delete keys whose patch value is null, replace arrays and scalar values, never mutate inputs. | `apply_revisions(base, revisions) -> JSON`: sort revisions by integer sequence, reject duplicates, apply their patches using the repaired core. | Missing deletion target; nested deletion; scalar-to-object replacement; arrays; false versus zero; empty revisions; numeric sequence order; input aliasing. |
| D: dependency execution | `topological_order(jobs) -> list[str]`: choose the earliest original input position among currently ready jobs. Reject duplicate IDs, missing dependencies and cycles. | `execution_batches(jobs) -> list[list[str]]`: produce dependency frontiers, with deterministic ordering within each frontier. | Empty graph; chain; diamond; multiple roots; newly ready earlier-index job; duplicate ID; missing dependency; self-cycle and multi-node cycle. |

Pin these additional details:

- A accepts ASCII decimal text matching `-?(0|[1-9][0-9]*)(\.[0-9]{1,p})?`, with at most nine integer digits. No whitespace, exponent or leading plus. Invalid input raises `ValueError`.
- B accepts integer endpoints, excluding booleans. Reversed intervals raise `ValueError`.
- C accepts JSON values with string object keys. A non-object patch replaces the target with a deep copy. An object patch treats a non-object target as an empty object.
- C revision sequences are positive integers, excluding booleans.
- D jobs are records with unique string `id` and a list of dependency IDs. Repeated dependency entries have set semantics.
- Freeze input-size limits, including maximum collection length and JSON depth, as part of the test contract.

Seed explicit defects rather than leaving “broken source” unspecified. For example: A uses floating point and rounds excess precision; B assumes sorted input and mishandles touching intervals; C shallow-copies nested objects and mishandles deletion; D confuses FIFO discovery order with the specified ready-node ordering. Adapter defects must independently exercise the second column’s requirements.

**Register two model operations.**

`repair_core@1` receives one ticket and returns its repaired core function.

`repair_adapter@1` receives that ticket, the original adapter and the **actual accepted core source**. It returns the repaired adapter function.

Both return exactly:

```json
{"source":"def required_function(...):\n    ..."}
```

The source must contain exactly one function with the frozen name and signature. No additional top-level statements, decorators, imports, helper definitions or changed defaults. Missing or extra keys, duplicate keys, Markdown and explanation prose fail the applicable contract. Preserve the existing strict wire parser; do not introduce text extraction or cleanup.

Freeze a maximum source length, for example 4,096 UTF-8 bytes per function. Assembly inserts accepted source into declared replacement spans. It does not fix indentation, rewrite expressions or repair a rejected candidate.

The two operations declare job independence across tickets. Their computation identities include exact instructions, ticket bytes, actual upstream source where applicable, and the pinned route. Packet positions and siblings remain dispatch provenance under that declaration.

**The manual graph has exactly these twenty nodes.**

| Node | Kind | Work and dependencies |
|---:|---|---|
| 1 | Host | Snapshot tickets A to D into authoritative source storage. |
| 2 | Model | Repair A core from node 1’s A record. |
| 3 | Model | Repair B core from node 1’s B record. |
| 4 | Model | Repair C core from node 1’s C record. |
| 5 | Model | Repair D core from node 1’s D record. |
| 6 | Host | Build A adapter context from ticket A and node 2’s accepted source. |
| 7 | Host | Build B adapter context from ticket B and node 3’s accepted source. |
| 8 | Host | Build C adapter context from ticket C and node 4’s accepted source. |
| 9 | Host | Build D adapter context from ticket D and node 5’s accepted source. |
| 10 | Host | Join the four adapter contexts into a keyed record collection. |
| 11 | Model | Repair A adapter from node 10’s A context. |
| 12 | Model | Repair B adapter from node 10’s B context. |
| 13 | Model | Repair C adapter from node 10’s C context. |
| 14 | Model | Repair D adapter from node 10’s D context. |
| 15 | Host | Assemble the four modules from the original snapshot and eight accepted functions. |
| 16 | Host | Run frozen package integration tests and record results against exact assembled bytes. |
| 17 | Host | Render the unapplied unified patch from the verified package. |
| 18 | Host | Render the verification report and provenance manifest from the same package evidence. |
| 19 | Host | Independently verify the patch, reconstructed package, report, manifest and current source bindings. |
| 20 | Host | Durably publish the verified package to the authorized local destination. |

Nodes 2 to 5 form one size-4 frontier. Nodes 11 to 14 form another. Nodes 17 and 18 are a host fan-out followed by the final join.

Use the current binding forms. Every model node has one `record` string. Node 10 supplies branch-specific strings through JSON Pointer bindings. Those strings include the complete relevant ticket and accepted core source, but exclude request IDs, timestamps and unrelated tickets.

The target is **one complete repair package, weight 1**. Eight accepted functions do not independently earn eight target successes.

**Per-job acceptance must judge the submitted code, independently of its author’s claims.**

For each core job, run frozen tests against that function and its own ticket revision.

For each adapter job, require both:

1. Contract tests using frozen core stubs with controlled returns, exceptions and call records. These test the adapter independently.
2. Integration tests using the actual accepted core source and independently frozen expected outcomes.

The stubs are narrow test fixtures, not general reference implementations offered as replacement code. Neither model supplies its own acceptance tests or expected answers.

Before live calls, freeze at least twelve test rows per ticket per operation, adding rows where needed to cover every listed boundary. Record a coverage matrix by operation, ticket, revision, expected outcome category and boundary family. Categories include successful values, empty or identity behavior, and required exceptions where applicable. Mark inapplicable categories explicitly.

Require offline oracle checks:

- Known valid alternative implementations pass, without requiring identical source bytes.
- The original defective functions fail.
- Every seeded defect has a discriminating test.
- Wrong-function binding, wrong revision, type confusion, input mutation and adapter compensation for a broken core are detected.
- A deliberately false rejection is detected by the independent evaluator.

These tests establish correctness within the frozen acceptance scope, not proof for every possible Python input.

**Freeze the code-execution boundary too.** Use a benchmark-only restricted AST policy and a worker exposing only approved pure built-ins and required core callables. Prohibit reflection, arbitrary attribute access, imports, file access, process creation and dynamic execution.

On this Windows host, use a standard-library `ctypes` Job Object to enforce a 256 MiB process-memory limit, one process, a two-second CPU limit and a five-second wall timeout. Assign the worker before sending candidate code. Keep expected results in the parent; send only test inputs to the worker. Freeze the exact AST whitelist and permitted methods before the run.

`python -I` and a temporary directory alone are not isolation. If these controls cannot be established, G0 is blocked. Candidate resource-limit violations are contract failures; verifier infrastructure failures are inconclusive and must not consume another model attempt automatically.

**Record five scenarios, with no scenario reruns.**

The following are failure-free expectations, not worst-case launch guarantees:

| Scenario | Setup and injection | Expected physical launches |
|---|---|---:|
| Clean | Fresh flow and empty memo namespace. | 2: core 4, adapter 4 |
| Exact repeat | New flow, identical computation inputs, authorized clean memo. | 0 |
| Interrupted | Fresh cold flow. Kill after the first durable worker capture; resume. Kill again after publication manifest creation; resume. | 2 |
| Stale A | Fresh cold flow. After node 16 commits, change A’s authoritative source to revision 2 before rendering or delivery. | 4: core 4, adapter 4, core A 1, adapter A 1 |
| Identical-byte bump | New flow using clean memo. After node 16 commits, add an A revision with identical bytes. | 0 |

For stale A, revision 2 changes precision from two to three fractional digits. Freeze its full ticket bytes and oracles in advance. For example, `"1.001"` changes from invalid to valid, and adapter formatting changes from two to three digits. Old core and adapter implementations must fail discriminating revision-2 tests.

This mutation must invalidate the old package verification and prevent its delivery. The final package must cite revision 2. B, C and D remain byte-identical computation inputs.

The current executor propagates provenance through joins. Therefore, do not require unaffected flow acceptances to remain current. Require that any necessary reassociation of B, C and D uses memo rather than new model calls.

Expected memo behavior includes eight hits on exact repeat and six unaffected computation reuses during stale recovery. For the bump scenario, freeze the exact lookup and acceptance trace from the zero-token dry run. Do not confuse lookup counts, reused computations and accepted flow nodes.

At both kill points, preserve the request identity, deadline and consumed allocation. The first capture must include the originating completion and accounting evidence needed for recovery without a new invocation. The publication interruption must reconcile the same verified bytes and stable intent. An uncertain invocation is a blocker, not permission to replay.

**Use a fresh allocation of 80,000 billed tokens and 16 physical launches.**

This allocation covers the entire five-scenario suite, including failures and recovery. It does not reuse the earlier G3b allocation.

Freeze:

- Sonnet 5.5, default effort, authenticated `claude -p`, no tools.
- Recorded CLI version, canonical model ID, adapter argv and digest.
- Unchanged H and `oz1g-header`; `oz1g-selective-v1`.
- Experimental code-repair workload at sizes 4 and 1.
- Two attempts per logical job generation, including the original.
- At most eight physical launches per scenario.
- One in-flight call in the quota group.
- A 10,000-token admission reserve per launch.
- A 300-second call timeout, 3,600-second scenario deadline and four-hour suite envelope.
- No planner, filler jobs, cross-run batching, model switching or effort adaptation.

The reserve is admission headroom, not a hard upper bound on a call’s consumption. Any actual allocation overrun prevents an overall pass.

Recovery uses size 4 when four eligible unresolved members remain; otherwise it uses singletons. Accepted siblings are not resent within the same generation. A wire-invalid reply yields no eligible members. A verifier outage leaves candidates pending checks.

The failure-free schedule needs eight launches across the suite. This is a schedule count, not a token-cost prediction. Available subscription quota must be observed separately.

The existing size gates remain unchanged: Sonnet 1/4/16/32/64, Opus 4/16/64 and Haiku 1/4/16/64. Their materials results do not qualify this new workload. In particular, this design does not authorize Opus singleton recovery.

**Call the additional gate `G3c-O1`, with these prerequisites and pass conditions.**

Before the first counted call, commit and hash the complete preregistration:

- All original sources, tickets, revision-2 bytes, public examples and graph.
- Operation instructions, candidate schemas, AST policy and resource limits.
- Runtime checks, independent evaluator, frozen expected results and coverage matrix.
- Route, authority, namespaces, budgets, deadlines and fault schedule.
- Exact dry-run traces, recovery rules and report schema.

No live exploratory calls are included outside that allocation. Oracle or implementation changes after a counted call require a new freeze; prior expenditure remains recorded.

G0 requires that freeze and Opus’s agreement on the executable contract. G1 requires the full current regression suite, preserving the original 342-test compatibility obligations, plus focused new tests. G2 requires a complete zero-token fixture run and the adversarial gate tests below.

Before reusing G3b machinery, fix its identified predicate defects. The independent evaluator must:

- Re-read complete captures and independently decide wire validity and candidate eligibility.
- Judge every candidate, including rejected candidates, against its exact recorded inputs.
- Detect both false acceptance and false rejection.
- Check cross-stage ordering, source mutation ordering, generations and publication ordering.
- Reject duplicate physical-call start records rather than silently merging them.
- Distinguish model failure records, wire rejection, semantic rejection, resource rejection and verifier unavailability.
- Exercise regeneration states the executor can actually produce.
- Reconstruct permitted recovery from independently derived verdicts, not executor labels.

The dry sabotage suite must include accepted-sibling resend, unsupported packet size, third attempt, stale delivery, wrong revision, forged memo eligibility, missing usage, duplicate ledger records, false rejection, skipped recovery, verifier-outage regeneration and capture recovery falsely counted as another launch.

**G3c-O1 passes only when all five requested scenario targets are independently verified and durably delivered before their original deadlines, within the shared allocation.** In addition, the recorded interruption, stale dependency and memo behavior must match the independently reconstructed permitted trace.

Node 19’s approval must bind the exact bytes published by node 20. Final acceptance and delivery must recheck the relevant source revisions transactionally. An earlier successful test run cannot authorize a stale package.

The independent evaluator must not import the runtime check implementations or treat their verdict flags as truth. It may consume frozen declarative contracts and test vectors. A disagreement blocks the gate pending investigation.

**Report correctness before cost.** Retain every invocation’s raw `modelUsage` and count whole-call input and output once, including failed calls and hidden reasoning. Report `thinkingTokens` per call when present; missing is unknown, not zero. Do not use thinking-token observations to change effort during this suite.

The report should separate first-attempt acceptance, recovery, wire failures, independently correct rejected candidates, final package correctness, memo reuse, physical launches, total billed tokens and elapsed time. Missing accounting can preserve a correctness finding but cannot support an overall within-budget pass.

I allocate **zero new baseline launches** here. The earlier G4 remains historical evidence on a different workload. This gate makes no savings claim and does not infer that orchestration beats direct execution. A matched comparison would require its own allocation and preregistration.

A successful result supports this bounded statement:

> AKOR completed and recovered a recorded 20-step code-repair workflow, using model-generated repairs, independent per-job checks, current-source validation and memo reuse, within the registered deadlines and allocation.

It does not establish general coding reliability, new production qualification or token superiority.

No files were changed and no model experiments were launched for this proposal. The next action is Claude’s implementation of the frozen fixture and independent gate, followed by Opus’s review before counted calls.


