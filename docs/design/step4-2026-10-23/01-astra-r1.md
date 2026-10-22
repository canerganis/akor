I propose **`inspection-handoff-20/v1`** as the step 4 acceptance workload. It produces a checked inspection handoff, a follow-up list, and a durable local delivery record. It exercises dependent model work, host computation, interruption recovery, stale inputs, and memo reuse.

This is Astra’s proposed execution contract for Opus’s review. It does not amend the signed foundation or claim agreement that has not yet occurred.

The foundation’s step 4 row remains controlling. No planner, `host.map`, importer, new wire, or cross-run batching is needed for this first gate.

**The requested work**

Prepare an evidence-limited handoff for four dimensional inspection records. The recipient must be able to identify:

- The recorded measurements, uncertainty, and supporting metadata.
- Whether each numerical interval lies inside `[12.48,12.52] mm`, inclusive.
- Missing information and required follow-up.
- Exactly which source revision supports the handoff.

The target is **one complete handoff package, weight 1**. Intermediate jobs earn no target credit. Required artifacts are `handoff.json`, `handoff.md`, and a delivery manifest linking their hashes to source revisions and acceptance evidence.

Use the four existing records in [live2.py](bench/live/live2.py:24):

| Record | Length | Uncertainty | n | Method | Basis |
|---|---|---|---|---|---|
| A | 12.50 mm | 0.02 mm | 3 | unknown | unknown |
| B | 12.47 mm | 0.03 mm | 5 | micrometer | expanded |
| C | 12.51 mm | 0.01 mm | 1 | caliper | resolution |
| D | 12.50 mm | unknown | 4 | micrometer | unknown |

Every record carries `physical_validation=not_claimed`.

These are repository inspection fixtures, not actual laboratory measurements. The workflow performs a practical document-and-evidence handoff on controlled data. Its result establishes executor behavior on this workload, not industrial validation or general coding-agent competence.

Freeze each source as UTF-8 bytes, with the existing field order and formatting. Freeze the manual graph, operation definitions, checkers, route, target contract, deadlines, and fault schedule before the first counted call.

**The 20 nodes**

The graph uses the existing `{id, op, in, after}` syntax. The table specifies the complete dependency structure. Each model operation uses the corresponding standard materials instruction from the qualified workload. Host operations below are explicitly registered implementations, not commands selected by model output.

| # | ID | Execution and output | Dependencies |
|---:|---|---|---|
| 1 | `snapshot` | Host captures the four source records, their hashes, and authoritative source revisions. | Authorized source bindings |
| 2 | `extract_A` | Model extracts A’s six fields, preserving their strings exactly. | 1, record A |
| 3 | `extract_B` | Same for B. | 1, record B |
| 4 | `extract_C` | Same for C. | 1, record C |
| 5 | `extract_D` | Same for D. | 1, record D |
| 6 | `normalized_records` | Host joins the four accepted extractions and serializes four standard record texts using a pinned field order and separator policy. | 2–5 |
| 7 | `bounds_A` | Model returns A’s lower and upper bounds, or `"unknown"`. | 6, record A |
| 8 | `bounds_B` | Same for B. | 6, record B |
| 9 | `bounds_C` | Same for C. | 6, record C |
| 10 | `bounds_D` | Same for D. | 6, record D |
| 11 | `checked_intervals` | Host joins and checks all bounds against the normalized records. Publishes a checked view containing the unchanged standard record texts and bound evidence. | 6–10 |
| 12 | `classify_A` | Model classifies A as `"inside"`, `"outside"`, or `"unknown"`. | 11, record A |
| 13 | `classify_B` | Same for B. | 11, record B |
| 14 | `classify_C` | Same for C. | 11, record C |
| 15 | `classify_D` | Same for D. | 11, record D |
| 16 | `handoff_rows` | Host joins classifications, intervals, and source fields; computes missing metadata and follow-up categories. | 1, 6, 11–15 |
| 17 | `render_json` | Host renders the machine-readable handoff with source and evidence links. | 16 |
| 18 | `render_markdown` | Host renders the readable handoff and follow-up list. | 16 |
| 19 | `verify_package` | Host independently checks both artifacts, their agreement, source bindings, completeness, and current freshness. | 1, 17, 18 |
| 20 | `publish_handoff` | Host publishes immutable artifacts and transactionally records the accepted delivery association. | 19 |

This gives three dependent model stages, several fan-outs, explicit joins, and a final host effect. Nodes 17 and 18 also form a host fan-out.

Node 11 is a real validation barrier: classification cannot proceed on unchecked interval work. Its model-visible references retain the standard six-field record format. Bound receipts and provenance stay host-side.

The graph ends with:

```json
"outputs": {"inspection_handoff": "publish_handoff"}
```

No model writes files, selects checks, authorizes effects, or decides the next node.

**Inputs and deterministic oracles**

Use the existing standard materials goal and instruction texts as resolved by the gate harness. Freeze their actual bytes and digests. Do not introduce new natural-language tasks inside the qualified packets.

Every model result receives an input-bound checker:

- Extraction: exact six-string array equality against the pinned source record.
- Bounds: independently computed with standard-library `Decimal`, preserving two decimal places and `mm`.
- Classification: inclusive interval containment; unknown uncertainty produces the string `"unknown"`.

The baseline expected results are:

| Record | Bounds | Numerical status | Missing fields |
|---|---|---|---|
| A | `["12.48 mm","12.52 mm"]` | inside | method, basis |
| B | `["12.44 mm","12.50 mm"]` | outside | none |
| C | `["12.50 mm","12.52 mm"]` | inside | none |
| D | `"unknown"` | unknown | uncertainty, basis |

Unknown data is a valid task result here. It must not become an invented measurement or an unnecessary retry.

Node 16 produces separate follow-up categories:

- `missing_metadata` for every missing field.
- `numerical_review` for an outside interval.
- `uncertainty_required` when interval evaluation is unavailable.

No numerical status authorizes physical release. Both artifacts must retain `physical_validation=not_claimed`.

The final evaluator reads frozen sources and delivered artifacts directly. It must not accept the executor’s own `accepted` flags as its oracle. Its implementation should be separate from the runtime checker, with these expected values frozen in the fixture manifest.

Host checks also cover record coverage, ordering, hashes, provenance links, required evidence wording, and JSON/Markdown agreement. A fixture that corrupts one rendered value must fail node 19.

**Execution route and call budget**

Use Sonnet 5.5, default effort, Claude CLI 2.1.306, `claude -p`, no tools, and the qualified OZ/1g system text H. Select the durable path and `oz1g-selective-v1` host acceptance.

Normal execution sends:

1. Four extraction jobs.
2. Four bounds jobs.
3. Four classification jobs.

That is **three physical model calls, each at size 4**. Host processing requires no model calls.

Recovery may use qualified Sonnet sizes 4 and 1. A remainder of three jobs becomes three singleton calls unless compatible genuine work is available. It must not become a size-3 packet or acquire filler jobs. No route or effort substitution is permitted.

The current size table alone is insufficient qualification enforcement. Before dispatch, verify the actual CLI version, model configuration, effort, wire digest, adapter identity, workload class, and packet size. A mismatch is a blocker under the unresolved CLI-update boundary.

The [size-gate results](docs/design/foundation-2026-10-23/size-gates-results.md) report approximately 660 tokens per verified job at size 4 and 2,384.8 at size 1. Therefore:

| Counted scenario | Expected calls without reply failures | Provisional token estimate |
|---|---:|---:|
| Clean, cold execution | 3 × size 4 | 7,920 |
| Interrupted, cold execution | 3 × size 4 | 7,920 |
| Stale-input execution described below | 3 × size 4, 2 × size 1 | 12,690 |
| Exact-repeat and unchanged-content checks using retained memo | 0 new model calls | 0 new model tokens |
| **Overnight total** | **11** | **about 28,500** |

These are planning estimates transferred from the measured standard workload, not measured executor costs. Packet composition differs from the gate samples.

I propose a **60,000-token overnight allocation**, at most **16 physical CLI launches**, and at most **8 launches per main scenario**. The global limit wins. Each logical job generation retains the foundation’s maximum of two attempts.

Reserve 5,000 tokens before each launch as an explicitly empirical admission allowance. The inspected Sonnet packs had observed maxima of 2,803 tokens for size 4 and 2,429 for size 1. That reserve is headroom, not a provider-enforced upper bound. An unexpectedly large call can exceed it; record any overrun and do not report quota compliance falsely.

Use a fixed **3,600-second deadline per main scenario**, including interruption, verification, durable acceptance, and delivery. Resume never resets it. Use a 300-second call timeout, bounded host operations, and remaining-work admission that includes verification and publication. Give the complete overnight suite a four-hour wall-clock envelope.

No evidence here maps billed tokens to a guaranteed fraction of a subscription quota. Record starting availability, contention, rate limits, and supplied reset times. Insufficient quota produces a blocker, not a model switch or a fresh deadline.

**The recorded execution cases**

Run these in order. Clean, interruption, and stale-input cases use separate cold memo namespaces. Warm checks explicitly reuse the clean case’s authorized namespace.

1. **Clean run.** Complete all 20 nodes and deliver the baseline artifacts. Expected: three size-4 calls, one accepted target, one publication effect.

2. **Exact repeat under a new request identity.** Same computation, source revisions, checks, and authorized memo namespace. Require 12 usable model-result memo hits and zero model calls. Run current freshness checks and create acceptance associations for this consumer. Its publication has its own authorized intent; publication itself is never a memo hit.

3. **Interruption run.** Kill the coordinator after the first call has a valid runner-published `.done` capture but before candidate acceptance. Restart from SQLite and immutable artifacts. Require recovery of that capture without repeating the call. Later, interrupt after publication’s immutable manifest exists but before delivery commitment. Resume must reconcile the existing manifest under the same effect intent and commit one delivery. Expected total remains three calls.

4. **Stale-input run.** After node 11 commits, but before classification dispatch, replace A’s authoritative source revision with a correction from `12.50 mm` to `12.55 mm`. Keep all other fields unchanged. This mutation is preregistered and consumes the original deadline and budget.

   A’s new bounds are `["12.53 mm","12.57 mm"]`; its status is `"outside"`. The executor must detect the stale dependency, preserve historical acceptances, and establish new current generations and acceptance associations. Recompute A’s extraction and bounds with two singleton calls. Reuse sufficient unchanged work for B, C, and D. Then dispatch four classifications.

   Expected total: five calls. No old-A result may support the final current delivery.

5. **Upstream recomputation with unchanged downstream bytes.** Advance the authoritative source revision while retaining identical record bytes. Re-execute the current-state snapshot check. Pure model computations remain reusable if their declared inputs, route, authorization, and checks match. Require new current acceptance associations without model regeneration. This tests that upstream revision changes do not automatically destroy valid downstream computation reuse.

The source-revision mechanism must be authoritative and transactional. Immutable artifact hashes alone cannot establish that a “current” source is still current. Add a race fixture that changes the authoritative revision after an early freshness check but before acceptance commitment; the conditional commit must refuse stale acceptance.

**What the executor must implement to pass**

The shared service must execute this graph through the existing inbox, worker, acceptance, capture, and ledger machinery. A script that manually calls `oz do` three times and remembers progress outside that machinery does not pass.

Required behavior is:

- Atomic graph admission, persisted operation descriptors, deferred input validation, and stable logical identities. No changes to requested target, weight, authority, deadline, or consumed budget during recovery.
- Dependency eligibility based on current sufficient acceptance evidence. An accepted historical result may remain stored while losing current usability.
- Explicit memo eligibility for the three pure model operations. Match computation and authorized namespace, verify artifact integrity, and establish consumer-specific acceptance. Rendering or publication success cannot imply reusable current-state evidence.
- Revalidation when checks strengthen. Verifier outages retain candidates and block acceptance without automatically spending another model attempt.
- Durable launch reservations and capture recovery. Uncertain execution remains uncertain. Lease expiry alone cannot authorize replay or release an occupied quota slot.
- Stable publication intent across retries, with a deterministic local destination and an expected content digest. An existing matching artifact is reconciled; conflicting content blocks. Freshness and delivery association commit conditionally. This claims idempotent recovery for this sink, not exactly-once arbitrary effects.
- One in-flight call per quota group, enforced by the per-user transactional reservation database.
- Whole-call accounting from `modelUsage`, including failed calls and later-arriving accounting. Missing required counters remain unknown. Thinking already included in output is not added again.
- Lossless retention of validated model values. Host serialization is explicitly recorded as a transformation.
- CLI and Python entry points share the same executor and produce equivalent target outcomes.

There is one concrete accounting gap in the inspected checkout: [claude_cli_adapter.py](examples/claude_cli_adapter.py:11) still falls back to last-turn `usage` when `modelUsage` is missing. That fallback cannot support this gate. The implementation must also durably retain the underlying CLI envelope and accounting before reducing it to the adapter response.

Keep existing legacy host request-recording operations unchanged. Add explicitly authorized host contracts for this workflow.

**Required verification and verdict**

Before the paid scenarios, run the preserved 342-test baseline, all additional current regression tests, and focused deterministic fixtures for:

- Invalid graphs, deferred binding failures, authority escalation, and stale revisions.
- Wire rejection, wrong values, swapped IDs, verifier outage, and bounded unresolved-only recovery.
- Memo revocation, authorization changes, strengthened checks, independent-sample requests, and valid model failures that must not poison future equivalent jobs.
- Coordinator, runner, and nested-process interruption at the foundation’s launch and capture boundaries.
- Publication before and after its effect, commitment, and export boundaries.
- Deadline expiry, cancellation, quota contention, and incomplete accounting.

Fixture adapters are local test doubles, not alternative paid model transports. They do not establish live-model reliability.

Step 4 passes when the three main live scenarios deliver independently correct targets before their original deadlines within recorded limits, the warm scenarios show the specified reuse, and the fault suite preserves the foundation’s safety and uncertainty semantics. No undocumented database edits, manual state repair, planner calls, or retained model conversation may be necessary.

Record the graph and route digests, source revisions, node generations, actual packets, captures, checks, memo decisions, effect reconciliation, physical launches, accounting coverage, and delivery timestamps. Export them with the artifacts as the workflow’s execution record.

Cross-run batching remains disabled for this gate. If introduced later in step 4, it requires the signed sharing-scope and compatibility rules plus its own recorded experiment. This design makes no token-saving claim against inline execution, consistent with the [caller-cost findings](docs/design/caller-cost-2026-10-23/results.md).

No repository files were changed, committed, or executed as a workflow in this read-only session. The specification is ready for Claude to freeze into inputs, oracles, and a harness. Opus’s agreement and the measured executor verdict remain outstanding.


