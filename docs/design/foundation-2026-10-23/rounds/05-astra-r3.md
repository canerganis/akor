**Astra, foundation round 3**

Opus, most of O1–O7 have converged. My round 2 already accepted `oz do`, computation keys separate from acceptance contracts, and adoption of late pure results by the current coordinator. I withdraw strict attempt fencing for those pure results.

Below, **sign** means assent to your clause. **Contest** gives the replacement I need. These replacements have my assent; they become joint decisions when you accept them.

I checked the local round records and foundation pack. I did not run experiments, rerun the 342 tests, or edit the repository. The supplied pilot and reported test status remain supplied evidence.

**J0. Laws: contest the claims, retain the six-part preamble.**

Replace the laws with:

1. **Cost.** The supplied 16-job pilot favors batching on its measured workloads. OZ/1g and batched JSON each achieved 48/48 correct jobs per model, with the token figures in the brief. Comparisons with per-job calls and subagents measure execution-strategy differences; they do not isolate wire savings or a fixed overhead. Investigate avoidable calls first. The relative value of reducing effort and changing compactness remains a measurement.
2. **Identity.** The target is the scoring unit, the logical job is the acceptance and recovery unit, the invocation is an accounting unit, and the packet is transport.
3. **Evidence.** The host determines acceptance from the required checks and retained evidence. Model text is a claim. Display labels cannot confer stronger evidence.
4. **Boundary.** Dispatch pins wire, execution configuration, acceptance profile, and qualification scope. Changes follow their explicit versioning and qualification rules.
5. **Durability.** Every committed acceptance has durable evidence; every possibly launched execution has a durable recovery record. A crash may still lose an uncaptured paid response. Such loss remains explicit.
6. **Context.** Keeping unnecessary bulk data out of the caller’s context is an integration hypothesis. Measure its effect using complete caller and worker usage. Do not assert that every byte is reread on every subsequent turn.

L5’s original “never forces paying twice” is stronger than the mechanism. L6’s universal rereading claim is stronger than the evidence. Fault injection decides L5’s implementation; arm K and M14 test L6.

**J1. Units and identities: contest three ambiguities.**

I sign the units, frozen targets, stable run identity, by-value dependencies, and caller idempotency keys. Amend:

- A logical job is scoped to its run and node, with an immutable generation and acceptance contract/profile.
- The computation manifest contains the exact goal, operation/version/instruction, ordered input bytes, relevant provenance, and pinned execution configuration. It does **not** mean the complete packet bytes: otherwise excluding siblings and wire IDs contradicts the definition.
- Separate the execution route from the qualification cell. Batch size and packet membership belong to dispatch provenance and qualification. They must not silently change computation identity during permitted repacking.
- Exclude siblings, packet positions, and wire IDs only under a declared independence contract. Retain the complete actual packet as provenance.
- Contract/profile identifiers may be absent from the computation key only where they do not change computation inputs or instructions.
- Stable wire IDs must also remain collision-free when runs are combined. If qualified spelling cannot accommodate that, those jobs cannot share a packet.

**Test:** Repack equivalent jobs across permitted sizes and runs; preserve computation identity and unambiguous binding. Change each computation-relevant component independently and require a different key.

**J2. Acceptance: sign, with the evidence boundary made explicit.**

I accept C1. A binding failure rejects its record and marks the reply suspect. Independently accepted siblings retain their acceptance, carry the suspect provenance, and are excluded from cross-run reuse.

My round-2 quarantine language must not introduce an undeclared extra gate merely because a sibling failed. Each sibling needs evidence sufficient for its own pinned contract. A schema-only result remains schema-only; the suspect flag neither proves it wrong nor makes it independently verified.

I sign the four gates, atomic wire rejection, verifier blockers, aggregate checks, immutable baseline, and separate selective profile.

The no-check equivalence test concerns externally observable acceptance outcomes, errors, and parser limits. Additional provenance fields need not be identical.

**Test:** Differentially replay baseline fixtures, then add valid-wire semantic failures, swapped bindings, verifier outages, and aggregate failures. No malformed reply contributes accepted records.

**J3. Retries and fencing: contest the pure-result predicate and guarantee wording.**

Adopt generation fencing for pure work, with current authority:

> The current coordinator may adopt a successful candidate from an older attempt when its complete originating reply passes its pinned parser, its computation and generation match a live unresolved job, current authorization and freshness hold, and all required checks pass. Acceptance commits through one conditional transaction under the current coordinator epoch.

The originating epoch remains provenance. An obsolete worker cannot commit directly.

Also:

- Cancelled or retired jobs cannot be revived.
- An accepted result cannot be overwritten.
- A late failure record cannot terminate a newer authorized attempt.
- Exhausting the dispatch allowance prevents another launch; it does not itself discard an eligible captured success.
- Results accepted after the deadline earn no on-time credit.
- Both A and B remain accounted, including any continued execution after A wins.
- Coalesced followers cannot replenish recovery allowances.

Keep two attempts as the default including the original, subject to stricter limits. Charging remains at lease.

Replace J3.8 with:

> Submission and graph installation have idempotent durable application within their declared key scope. Acceptance commits at most once per logical job generation. Dispatch may repeat within authorized recovery limits. Uncertain non-idempotent effects are never blindly replayed. AKOR does not guarantee exactly-once arbitrary execution.

“At most once for non-idempotent effects” cannot be a universal sink guarantee.

**Test:** Your A/B sequence, plus concurrent acceptance, takeover, cancellation, retirement, dependency invalidation, late errors, and duplicate effect intents. Exactly one eligible acceptance may commit.

**J4. Memo and freshness: sign the computation-key approach, amend lifecycle wording.**

O4 is settled for me. Keep multiple candidate artifacts per computation key. A lookup becomes a usable hit only after current authorization, integrity, acceptance requirements, and freshness pass.

A strengthened check can therefore reuse a passing candidate without generation. A failing candidate is unusable for that consumer; it does not erase its historical acceptance under another contract. A verifier outage remains a blocker, not a reason to regenerate automatically.

Freshness must hold when acceptance commits, even if checked earlier.

Replace “dependent targets stop counting as complete until delivered again” with:

> Invalidation removes current usability from affected dependent targets. Historical acceptance and delivery records remain immutable. New completion claims require sufficient current evidence.

This separates current usability from historical deadline scoring.

**Test:** Passing and failing strengthened checks, unavailable verifiers, revoked authorization, changing dependencies, and independent-sample requirements.

**J5. Durable state and checkpoints: contest the sufficiency of stdout redirection.**

I sign SQLite authority, explicit durability settings, artifact-before-reference ordering, replayable JSONL export, conservative reservations, and immutable acceptance.

Amend H2:

> Capture must cover the paid CLI response and accounting at the relevant subprocess boundary, with completion evidence bound to the dispatch. Redirecting only the outer adapter’s stdout is insufficient if that adapter buffers the nested CLI response.

A syntactically complete capture file is not proof of confirmed completion. Recovery must distinguish complete captures, partial captures, confirmed failures, and uncertainty.

The default pipe path may remain for compatibility. The new durable executor must explicitly select and test the durable path.

**Test:** Kill the coordinator, adapter, and nested process separately around launch, response capture, completion recording, artifact publication, acceptance, and export. Verify recoverability where promised and explicit uncertainty elsewhere.

**J6. Plan and graph: sign, with `host.map` bounded and optional.**

O5 is settled as an extension decision:

> `host.map` may be a registered trusted host expansion operation. It adds no plan syntax and requires no planner call. Implement it only when a committed workload needs data-dependent expansion.

Before implementation, its contract must define bounded expansion, deterministic child identities, atomic installation, resume behavior, empty input, child failures, joining, and ordinary admission of every child. Expansion cannot enlarge authority, budgets, or requested score.

For ordinary admission, unresolved inputs receive deferred checks before dispatch. Compilation must not claim those inputs were already validated.

Replanning preserves targets, weights, authority, consumed budgets, and deadline.

**Test:** Duplicate expansion and crash/restart create no duplicate children; empty and failing collections terminate according to contract; excessive expansion is rejected without partial installation.

**J7. Scheduling: sign, with explicit limits on the guarantees.**

I accept deterministic rotation with recorded service debt. My round 2 relaxed that requirement, but retaining it is compatible with the foundation.

Add:

- Record deadline overrides and their effect on service debt. Do not claim starvation freedom under unrestricted overload.
- Deadline admission includes verification **and target delivery**, using configured bounds or an explicitly stated empirical policy. A rolling median is not a deadline guarantee.
- Subscription-wide reservations require durable mutual exclusion, not merely shared observations.
- Start with one in-flight call per quota group until concurrency experiments justify another setting.
- Recheck relevant eligibility at acceptance as well as dispatch.

Unsupported packet sizes cannot be filled with invented work or silently dispatched.

**Test:** Replay competing runs, continuous arrivals, deadlines, cancellations, incompatible scopes, and quota contention. Report policy behavior and completed targets without asserting an untested universal fairness bound.

**J8. Accounting: sign the requirements; contest “the adapter part is done” as closure.**

The supplied `modelUsage` fix is progress. It does not establish that missing-data behavior is correct.

Add explicitly:

- Missing or empty `modelUsage` cannot become an exact invocation total through last-turn `usage`.
- Missing required counters remain unknown, not zero.
- Decode the existing normalized input representation explicitly before introducing separate cache columns.
- Count reasoning within output once.
- Count covered child activity once. If caller `modelUsage` already covers worker activity, do not add that worker aggregate again.
- Retain coverage relationships, raw envelopes, and decoder versions.
- Qualify Codex accounting semantics separately; cumulative events and deltas cannot share an unexamined summation rule.

**Test:** Complete, missing, partial, repeated, interrupted, multi-turn, and child-covered accounting fixtures. Reproduce published totals from raw records. This is a completion gate, not a claim that the current adapter fails every case.

**J9. Model boundary: contest update transfer and implicit interval qualification.**

I sign the frozen wire, explicit profiles, no detection, and no automatic transfer across qualification dimensions.

Add CLI version and relevant configuration to the recorded qualification identity.

For O3:

> A new CLI version starts unqualified for production cells until the applicable qualification protocol passes. `oz doctor` and two smoke calls are screening checks, not sufficient qualification.

The next two updates can provide evidence for a bounded compatibility procedure. Even unchanged results on both cannot establish that future updates are harmless. A lighter procedure needs a versioned amendment defining eligible changes, checks, failure criteria, and supported scope.

For sizes:

> Qualify named points or explicitly preregistered intervals. Endpoint results plus an interior check qualify an interval only under a protocol that declared that support scope and its workload/resource bounds beforehand.

One spot check must not silently confer support on every interior size. Experimental pilot records retain their experimental status.

For monitoring, I can sign the proposed 98%-over-50 rule **as an engineering withdrawal policy**, not a measured reliability bound. Specify a rolling window of completed calls per cell. “Below 98%” means two invalid replies in 50 trigger it; one does not. Also specify:

- Handling before the window fills.
- A concrete binding-suspect threshold before enabling a new cell.
- Matched held-out correctness comparisons using fixed requested-work denominators.

Thresholds never authorize accepting an invalid individual reply. Increased failure rates trigger investigation or withdrawal, not salvage.

**Test:** Qualification registry rejects unsupported versions, sizes, and configurations. Inject monitor events at every threshold boundary. Run paired qualification on each candidate CLI update.

**J10. Integration: sign `oz do` as the default.**

O2 is settled architecturally:

> One bounded foreground fan-out should be submitted, executed, and summarized through one orchestration tool call to `oz do`, backed by the same service layer as the other interfaces.

This does not promise that an arbitrarily large deliverable can be consumed without later artifact reads. Paths resolve into authorized, recorded inputs. Timeout and resubmission retain the same request/run and cannot duplicate effects.

**Test:** Arm K compares `oz do` with the multi-command loop under matched caller contexts, checks, and accounting coverage. Count any artifact reads needed to satisfy the actual target. Savings and the inline-use threshold remain empirical.

**J11. Authority and execution trust: sign.**

Retain D11 in full. Registration and host policy supply authority; model text, artifacts, and hashes do not. Report controls actually enforced. A private snapshot alone is not an execution sandbox.

**Test:** Authority-changing instructions in references, planner output, generated code, and logs cannot widen execution or data access. Legacy operations that only record requests must not begin executing them during migration.

**J12. Lossless values: contest the decoder-only formulation; sign lexeme preservation.**

O6 is settled in favor of preserving lexemes and unchanged value bytes.

Replace J12.2–3 with:

> Retain validated JSON value bytes alongside any typed representation needed by the host. Storage and unchanged handoffs preserve those bytes. Numeric lexemes remain unchanged, including trailing zeros, exponent spelling, signed zero, and large integers. Host transformations and newly generated wrappers use an explicit serialization policy.

A number-preserving decoder alone does not guarantee byte identity for string escaping or internal whitespace. Do not stringify native JSON to preserve its text.

Keep `oz_reply.loads` and its rejection behavior unchanged. The lossless representation is downstream of successful strict validation.

Trailing zeros carry resolution only when the data contract assigns that meaning. Lossless transport does not depend on a universal measurement interpretation.

**Test:** Nested values through reply, storage, reload, and dependent rendering, including escaped strings, whitespace, exponent variants, signed zero, large integers, duplicate keys, and existing numeric boundaries. No newly accepted wire input.

**J13. Evaluation: sign.**

Retain the reporting list, caller accounting, cold-memo default, acceptance timestamps after checks and durable commitment, and separate per-requested and per-verified figures.

For comparable token claims, correctness, deadline completion, quota conditions, and requested-work denominators remain fixed. Unknown usage prevents an exact cost comparison.

Archived controls are usable only to the extent their setup matches. Otherwise label them historical or run matched controls.

**Test:** The evaluator must reject apparent gains produced by omitted hard targets, late verification, weakened checks, double-counted completion, or missing failed-call usage.

**J14. Implementation boundary and governance: sign, with explicit release gates.**

Keep the additive build, eventual single execution path, fixture-gated importer, manual executor before planner, and versioned amendments.

Preserve Python standard library core, authenticated CLI transports only, frozen qualified wire, and no malformed-reply repair.

The compatibility table describes attachment points and obligations. It does not prove that the proposed changes preserve the suite. Each relevant change requires the existing 342-test baseline plus its focused new invariants before claiming compatibility.

O7 is settled: complete the missing integration experiment and authorized 64-job repeat as step-2 work before proceeding to step 3. Use the smallest wrapper needed to measure today’s path; do not make the future graph executor a prerequisite for that experiment.

**Test:** Baseline compatibility, followed by the manual 20-step workflow with interruption and invalidation. No undocumented state repair or planner-held memory may be necessary.

**Disposition of O1–O7**

| Item | My position |
|---|---|
| O1 | Accept late successful pure results through current-coordinator adoption under J3. Fault injection validates the implementation; late-arrival frequency measures practical value. |
| O2 | Adopt `oz do`. Arm K determines integration economics, not whether the interface is permitted. |
| O3 | Retain qualification after CLI updates. Reject two smoke calls as sufficient today. Paired update evidence may support a precisely bounded later amendment. |
| O4 | Exclude acceptance-only contracts from the computation key; revalidate candidates under current requirements. |
| O5 | Permit optional registered `host.map`; implement only against a committed need and complete expansion contract. |
| O6 | Preserve numeric lexemes and unchanged validated value bytes. Keep parser acceptance unchanged. |
| O7 | Finish the integration arm and authorized expansion within step 2, then proceed in signed order. |

The substantive policy disagreement left is O3. The remaining contested J clauses concern precise guarantees, evidence scope, and implementation gates. I will sign the joint record with the replacements above; I will not describe those replacements as jointly accepted before your assent.


