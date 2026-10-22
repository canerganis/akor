# AKOR foundation decision record

Date: 2026-10-23  
Status: signed foundation for steps 3 through 6 (Astra and Opus 5.5); O3 open  
Base: Astra round 2, clauses 1 through 12 and the implementation steps table

**Signed: Astra**  
**Signed: Opus 5.5, with C1 to C3 (accepted by Astra)**

This record incorporates A1 to A10 and A12 to A15 from Opus round 3, subject to the explicit boundaries below. A11, concerning qualification after CLI updates, remains open. Both positions and the deciding experiment appear in clause 9.

Acceptance of A2 does not override the prohibition on automatically regenerating after a verifier outage. Acceptance of A10 does not turn fixture coverage into a proof of equivalence for every possible input. These boundaries preserve the base text.

The record specifies requirements and release gates. It does not claim that the proposed executor is implemented, that its compatibility tests have passed, or that its savings have been measured.

## Objective and fixed boundaries

Decisions follow this order:

1. Maximize independently correct requested work completed before the deadline within quotas.
2. Minimize total billed tokens, including hidden reasoning, failed calls, and all attributable orchestration.
3. Minimize elapsed time.

A token improvement cannot compensate for reduced correctness or missed required deadlines.

Transport remains authenticated `claude -p` and `codex exec`. No API key, direct API adapter, or hosted service is introduced. Core remains Python standard library; new dependencies belong only in bench or optional extras.

The shipped OZ/1g system text H, packet grammar, and `oz1g-header` parser behavior remain unchanged for their qualified cells. A wire change creates a new profile and requires its own preregistered qualification. There is no malformed-reply repair, record salvage from invalid replies, or automatic format detection.

The target is the scoring unit. The logical job is the acceptance and recovery unit. The invocation is an accounting unit. The packet is transport.

## Evidence carried into this record

The supplied 16-job pilot used three seeds, strict oracles, and invocation accounting from `modelUsage`.

| Model | OZ/1g, one call | Plain JSON, one call | One plain-JSON call per job | One subagent per job |
|---|---:|---:|---:|---:|
| Sonnet 5.5 | 200.5 tokens per verified job; 48/48 correct | 245.1; 48/48 | 2,793; 34/48 | 8,617; 48/48 |
| Opus 5.5 | 196.6; 48/48 | 233.2; 48/48 | 3,737; 25/48 | 8,247; 48/48 |
| Haiku 5.5 | 272.3; 48/48 | 300.9; 48/48 | 3,471; 31/48 | 9,519; 39/48 |

Reported median durations per 16 jobs were 9 to 13 seconds for OZ/1g, 34 to 50 seconds for the subagent arm, and approximately 115 seconds for sequential per-job calls.

These results support investigating batched execution on the measured workloads. Comparisons with per-job and subagent execution measure execution-strategy differences. They do not isolate additional wire savings, fixed overhead, reasoning cost, or tool scaffolding as causal contributions.

The per-job arm used plain JSON. Its failures do not establish that small OZ/1g packets fail.

The supplied archive reports 91/91 accepted published qualified replies. The nine OZ/1g pilot replies at 16 jobs were experimental and remain separately reported. Combining them does not establish “100 qualified replies,” a per-cell reliability bound, or a salvage benefit.

The supplied audit found `usage` equal to `modelUsage` in all 162 examined single-call records. This historical equality does not authorize substituting last-turn usage when invocation accounting is missing.

The authorized 64-job repeat and missing integration arm remain completion gates unless their results are separately recorded. This record does not infer their outcomes.

Evidence sources are the supplied pilot table and audit, `pilot-plan.md`, the foundation pack, and the saved round records. Code observations attributed to `fabbc8a` are reported observations from those records, not fresh execution results from this consolidation.

## 1. Identities: separate computation, acceptance, and intent

Keep distinct identities for request, run, target, node, logical job generation, dispatch attempt, effect intent, candidate result, and acceptance evidence.

Requested work consists of frozen targets and weights. Nodes, retries, calls, coalescing, and replanning cannot create score. Resume retains the run identity and its consumed budgets.

A logical job is scoped to its run, node, and immutable generation. Its resolved inputs and acceptance contract/profile are pinned. Changing that contract requires an explicit new admission or acceptance association; it does not silently mutate an existing job.

Use two related keys:

```text
K_compute:
    versioned computation manifest

K_accept:
    K_compute + candidate digest
    + acceptance contract/profile
    + relevant evidence and freshness requirements
```

For model work, the computation manifest includes the exact goal, operation/version/instruction, ordered model-visible input bytes, declared computation-relevant provenance, and pinned execution route.

Required provenance means fields the operation declares as computation inputs or dependencies. Other provenance remains dispatch metadata. For host work, the manifest includes the implementation, complete declared dependencies, and relevant environment or snapshot.

The execution route includes adapter identity, model ID, effort, wire digest, and CLI version. Additional computation-relevant configuration must also be pinned.

Separate the execution route from its qualification cell. Batch size and packet membership belong to dispatch provenance and qualification. Siblings, packet positions, receipts, and caller node names are excluded from computation identity only under a declared independence contract. The complete actual packet remains retained provenance.

Acceptance-only contract changes need not alter `K_compute`. A contract change that changes instructions or computation inputs does.

Wire IDs may be packet-local. They MUST be collision-free within a combined packet and durably mapped to logical jobs. Repacking cannot make that mapping ambiguous.

The result store MUST allow multiple candidates for one computation key. Acceptance is not an intrinsic property of a value hash.

This rejects universal content-addressed identity and automatic regeneration after every verifier change. Reuse means satisfying the declared computation and the consumer’s checks. It does not assert identical output distributions.

**Test:** Change each included manifest component independently and require a different key. Repack under permitted independence and qualification conditions and preserve computation identity. Change only packet-local IDs and preserve logical identity. Strengthen an acceptance-only contract and recheck a sufficient stored candidate without a model call.

## 2. Acceptance: atomic parser, explicit per-job checks

Keep `oz1g-header` unchanged. Introduce the separately versioned host acceptance profile `oz1g-selective-v1`.

The acceptance sequence is:

```text
confirmed originating completion
→ whole-reply parser
→ checks against each job’s resolved inputs
→ durable job acceptance
→ target-level completion and delivery checks
```

A wire-invalid or incomplete reply contributes no accepted success or model-failure records. Raw captures and diagnostic records may be retained, but no candidate from that reply is eligible for acceptance or memo reuse.

Within a wire-valid reply, independently passing jobs may commit. Cross-record requirements belong to a collection-valued job or an explicit aggregate check. A target requiring that aggregate remains incomplete until it passes.

`declared`, `checked`, and `verified` are display summaries. Eligibility depends on actual check identities, versions, scope, verdicts, and evidence. A quoted-span check verifies the span’s presence. Successful command execution verifies execution under recorded conditions. Neither automatically verifies every claim in the result.

A verifier crash, unavailable environment, or inconclusive check leaves a durable candidate awaiting checks. It MUST NOT automatically consume another model attempt.

### Suspect replies and quarantine

An input-bound failure marks the reply suspect.

Candidates with independently sufficient, job-bound evidence may commit. Other candidates remain quarantined. Quarantine does not prove that a candidate is wrong and does not erase an independently sufficient acceptance.

A quarantined candidate may be released only when checks sufficient for its own pinned target contract pass for that same candidate.

If the required evidence cannot be established under the applicable contract, the job returns to bounded recovery under clause 3 without caller action, within its already authorized recovery allowance, preferably with different siblings when a qualified packet permits it. This rule does not apply merely because a verifier is unavailable or inconclusive.

A quarantined candidate remains history, cannot release dependents, and cannot become a usable memo entry. If no regeneration allowance remains, report `quarantined` and its reason, rather than a model-declared failure. Later sufficient checks may still release the same candidate if the job remains live and authorized.

### Failure records

A valid model-failure record decides the relevant logical job and its run-scoped coalesced followers. It is not a permanent negative fact about every future job sharing `K_compute`.

A late failure may become the recorded outcome only when no authorized execution is in progress and no attempt remains, subject to current authority and at-most-once commitment. It cannot overwrite an accepted success, revive a cancelled job, or cancel a newer authorized attempt.

### Parser limits

Preserve the shipped parser’s line, capture, storability, and numeric limits. Moving a limit out of the parser can change which siblings survive a reply and therefore changes observable behavior.

Additional tighter operation limits may be checked per job afterward. Relaxing a parser limit requires a separately qualified profile.

**Test:** Wire faults commit no accepted records. A valid reply with one oracle-wrong value retains independently sufficient siblings. Binding failures quarantine candidates lacking sufficient evidence, and a quarantined job with allowance left and no sufficient check is redispatched without caller action. Verifier outages resume from stored candidates without regeneration. Exhausted attempts produce the correct quarantine or failure status. Existing parser-limit fixtures retain their outcomes.

## 3. Retries and late replies: current authority may adopt old evidence

The logical job is the recovery unit. After wire rejection, every still-eligible unresolved member remains eligible for bounded recovery. No candidate from the rejected reply survives for acceptance.

Repacking may change membership and packet-local IDs while preserving computation. Smaller packets are permitted only when their sizes and configurations are supported and budgets remain.

Keep the existing default of two attempts, including the original, subject to stricter limits. Attempt allowance is charged at lease under the existing runtime contract. This is a protective execution allowance, not evidence that a physical process launched or that a known token amount was billed.

Each dispatch is immutable and records membership, mappings, packet bytes, job generations, execution profile, originating coordinator epoch, timeout, and budget reservations.

Coalesced followers MUST NOT multiply retries or replenish the representative’s recovery allowance.

For pure work, the current coordinator may adopt a late successful candidate only when:

- The complete originating reply passes its pinned parser and completion checks.
- Computation and logical job generation match a live unresolved job.
- Current authorization and freshness requirements hold.
- All required acceptance checks pass.
- Acceptance wins one conditional transaction under the current coordinator epoch.

The originating epoch remains provenance. An obsolete worker cannot commit directly.

Cancelled or retired jobs cannot be revived because a key matches. An accepted result cannot be overwritten. Exhausting dispatch allowance prevents another launch; it does not discard an otherwise eligible captured success.

Acceptance after the deadline earns no on-time completion credit. Both competing calls remain accounted, including execution continuing after one candidate wins.

For effects, retain a stable, host-authorized intent identity across recovery and replanning. Content fingerprints aid duplicate detection but are insufficient as effect identities: identical content can represent a legitimate later action, while changed arguments can still overlap an uncertain earlier action.

Use intent identity, resource-conflict checks, preconditions, and sink idempotency or fencing where available. A database fence does not fence an arbitrary external command. Uncertain non-idempotent effects remain `unknown_effect` until reconciliation establishes a safe outcome.

Submission and graph installation have idempotent durable application within their declared key scope. Acceptance commits at most once per logical job generation. Dispatch may repeat within authorized recovery limits. AKOR does not guarantee exactly-once arbitrary execution.

**Test:** Deliver A before and after B commits, including concurrent acceptance and coordinator takeover. Require at most one eligible acceptance and account for both calls. Repeat with cancellation, retirement, changed dependencies, exhausted allowances, and late failures. Reissue an uncertain effect under a new node ID or changed arguments and require conflict detection.

## 4. Memo: reusable candidates, current acceptance, preserved history

Memo eligibility is explicit in the registered operation. Tool-free does not imply memoizable. Independent samples, fresh observations, diversity requirements, or undeclared dependencies can prohibit reuse.

A lookup becomes a usable hit only after:

- Matching computation and authorized reuse namespace.
- Artifact integrity and absence of applicable revocation.
- Current required checks or sufficient retained evidence.
- Required source, environment, and time freshness.
- An acceptance association to the consuming job and target.

Contract changes can trigger revalidation rather than regeneration. If revalidation requires host execution, the hit remains pending until it completes. A verifier outage remains a blocker.

Freshness MUST hold when acceptance commits, even if checked earlier.

Distinguish immutable snapshot evidence, current-state evidence, and explicitly time-bounded observations. A TTL does not establish unchanged content.

Revocation and invalidation remove current usability from affected results and dependent targets. Historical acceptance and delivery records remain immutable. New completion claims require sufficient current evidence; historical deadline scoring is not silently rewritten.

Reusing a patch proposal does not reuse its application or tests against another snapshot. A memo hit is not a new execution, independent sample, or observation.

Valid model failures are not successful memo entries and cannot poison every equivalent node through an unconditional “terminal for K” rule.

**Test:** Exercise exact repeats, each dependency change, unchanged downstream input bytes after upstream recomputation, strengthened checks, verifier outages, authorization changes, revocation, and independent-sample requests. Require a miss or sufficient explicit revalidation as appropriate.

## 5. Durability: record uncertainty at the process boundary

SQLite is authoritative. Immutable artifact files hold captured data. JSONL is a replayable export.

Set `PRAGMA synchronous=FULL` explicitly. Record and test the selected journal mode and supported filesystem configuration. Durability must not depend on an implicit build default.

Publish immutable artifacts before committing references to them. Capture response and accounting before interpretation. Commit acceptance, state transitions, and ledger events transactionally.

The required launch and recovery sequence is:

1. Persist launch intent and protective reservations before execution can begin.
2. Record confirmed launch and process identity when available.
3. Capture the CLI envelope, available accounting, and completion evidence.
4. Distinguish confirmed execution, confirmed non-execution, and uncertainty.
5. Release protective reservations only when their execution and accounting obligations are reconciled.
6. Reuse durably completed captures without another model call.

Unknown usage remains unknown. Uncertain execution cannot silently become zero cost or permission to repeat an effect.

### Completion protocol

The runner publishes completion, not the coordinator.

It writes the CLI envelope and exit status, bound to the immutable dispatch receipt, to a temporary file; flushes and synchronizes the file; then atomically renames it on the same filesystem to `<receipt>.done`.

Only a valid completion record published through this protocol counts as a completed capture. A filename suffix or syntactically complete JSON alone is insufficient. A completed capture can record a failed process; it is not itself accepted work.

Redirected stdout may remain a secondary diagnostic capture. Redirecting only the outer adapter does not cover a nested CLI response that the adapter buffers.

Process identity includes PID and process creation time. On Windows, creation time can be obtained through `GetProcessTimes` using standard-library `ctypes`. PID alone is insufficient.

If the runner dies while the nested CLI remains active, recovery records uncertainty. Partial or complete-looking secondary captures do not become confirmed replies. A later valid runner completion record may resolve uncertainty under the same protocol.

The compatibility pipe path may remain available. The durable executor MUST explicitly select and test the durable path.

The guarantee is:

> Committed acceptance has durable evidence. Possible execution has a durable recovery record. Uncertainty remains explicit.

A crash can still lose an uncaptured paid response. AKOR does not promise that every paid reply is recoverable or that recovery never requires another paid call.

**Test:** Kill the coordinator, runner, and nested CLI separately around launch authorization, process creation, temporary capture, synchronization, rename, artifact publication, acceptance, and export. Require preserved committed work, no fabricated exact accounting, no blind replay of uncertain effects, and explicit uncertainty where recovery is impossible. Test stronger storage-failure guarantees separately before claiming them.

## 6. Graphs and migration: one executor, explicit admitted contracts

Keep OZ9’s `{id, op, in, after}` syntax and finite DAG.

The host compiles every node into a persisted descriptor containing resolved operation version, implementation or instruction identity, input bindings, checks, route, limits, effect authority, memo eligibility, isolation controls, and freshness requirements.

All authors use the same admission rules. Model output cannot authorize commands, select weaker checks, enlarge scope, or increase budgets.

Unresolved inputs receive deferred validation before execution. Admission cannot claim that those inputs already passed.

Accepted history is immutable. Replanning may retire unresolved nodes and install replacements, but cannot alter targets, weights, authority, consumed budgets, or the original deadline.

Build one eventual execution path through the current runtime. Introduce the legacy importer only after differential fixture testing. A wholesale node-table conversion is not a prerequisite for step 3.

Legacy operations that record requests MUST NOT silently begin executing them.

`host.map` is an optional registered trusted expansion operation. It adds no plan syntax and requires no planner call. Implement it only for a committed workload that needs data-dependent expansion.

Before implementation, its contract must define bounded expansion, deterministic child identities, atomic installation, resume behavior, empty input, child failure, joining terminal outcomes, and ordinary admission for every child. Expansion cannot enlarge authority, budgets, or requested score.

**Test:** Equivalent manual and planner-authored graphs produce equivalent admitted descriptors. Reject cycles, stale revisions, authority escalation, and weakened target checks. Differentially test the importer. Duplicate expansion and crash/restart create no duplicate children; excessive expansion fails without partial installation.

## 7. Scheduling: optimize eligible work within measured support

Cross-run batching requires compatible exact goals, execution routes, isolation controls, qualified sizes, and authorization covering the packet’s complete reference union.

Runs do not share packets unless both requests explicitly declare the same sharing scope and every compatibility condition holds. Workspace membership alone does not grant sharing permission. The wavefront experiment declares a scope for its instances.

Recheck eligibility at dispatch and acceptance. Dependencies must remain usable at the required scope. Ancestors and descendants cannot share a packet.

Start with the existing bounded scheduling policy and one in-flight call per quota group. Caller target priority retains precedence. Within a priority level, aging orders eligible jobs by age, with deterministic tie handling.

A continuous higher-priority stream may delay lower-priority work. Report that condition as `priority_wait`. Measure maximum waiting time within a level under a declared load. Do not claim starvation freedom under unrestricted overload.

Service-debt machinery is not required for the first executor. Deadline decisions and any permitted overrides must be visible in the record.

Deadline admission includes execution, verification, durable acceptance, and target delivery. Use configured timeout bounds or an explicitly stated empirical tail policy. A rolling median estimates typical duration; it is not a deadline guarantee.

Quota-group reservations live in a per-user SQLite database. Reserve a dispatch slot using a `BEGIN IMMEDIATE` transaction and release it transactionally. Record rate-limit events and supplied reset times in the same database.

A crashed holder does not make its slot immediately free if execution may continue. Reclamation follows clause 5’s reconciliation rules. Retained usage or effect uncertainty must not disappear when scheduler ownership changes.

The scheduler cannot silently change goal, route, effort, checks, or authority to improve packing.

Wavefront call count depends on compatibility groups, byte limits, qualified sizes, and actual DAG width. Approximation by critical-path waves is a conditional hypothesis.

**Test:** Replay mixed widths, chains, priorities, continuous arrivals, deadlines, cancellations, incompatible scopes, and quota contention. Verify eligibility, mutual exclusion, physical call accounting, waiting behavior, and on-time target delivery.

## 8. Accounting: invocation coverage without invented totals

Use Claude `modelUsage` as the invocation accounting source, including covered subagent activity. Do not add covered child aggregates again.

Remove the adapter’s fallback from missing or empty `modelUsage` to last-turn `usage`. Remove zero defaults for required missing counters. An absent aggregate or incomplete required model entry yields unknown invocation usage, while retaining available components and the raw envelope.

Retain raw envelopes, decoder version, source, scope, completeness, and coverage relationships. Partial totals may be reported as partial totals or justified lower bounds; they cannot support an exact comparison.

Preserve the existing normalized representation:

```text
input_tokens = uncached input + cache-read input + cache-write input
```

A new uncached-input column must be derived explicitly from complete compatible components. Cache components must never be added to an already inclusive input total.

Count reasoning within output once. Report `thinkingTokens`, when available under the qualified decoder, as a reasoning subset of output. Its absence leaves that subset unknown; it does not authorize inferring zero. The reported nine nonzero pilot subagent envelopes are evidence about those envelopes only.

For Codex, qualify event semantics before prescribing aggregation. Delta events, cumulative totals, repeated events, and final events require explicit decoding rules. Reading the last event or summing every event is not justified without that qualification.

Record failed, interrupted, late, planner, review, and qualification calls. Separate physical CLI dispatches, underlying turns, subagent spawns, and run participation.

Cross-run allocations are reporting conventions, not measured per-job billing. Global totals count each invocation and covered activity once. If caller accounting already covers worker activity, do not add that worker activity again.

Quota is observed, not inferred from token counts.

**Test:** Cover complete multi-turn aggregates, absent and partial envelopes, covered children, repeated events, cache components, reasoning subsets, and interrupted calls. Recompute published totals from retained raw rows. Missing required usage must prevent an exact cost claim.

## 9. Qualification: exact support scope and one open policy

Freeze H, packet grammar, exact-ID binding, and shipped parser behavior.

Record qualification identity and evidence scope explicitly, including:

- Wire and parser identity.
- Host acceptance profile.
- Adapter identity and relevant configuration.
- Model ID and effort.
- CLI version.
- Isolation controls and ID spelling.
- Supported sizes.
- Workload, heterogeneity, output, and resource limits.

Qualification does not automatically transfer across these dimensions.

The existing Claude qualification evidence does not record the Claude CLI version: no evidence file under `reports/` or `bench/live/data/` at 646cd09 carries one. Those cells therefore have an unrecorded CLI identity. From step 3, every dispatch and qualification record stores the CLI version. The shipped path keeps its current behavior. Before the durable executor dispatches production work on an existing cell, that cell is requalified under its full applicable protocol at a recorded CLI version; this may run together with the step-2 size gates. That run is the old-version baseline for the O3 experiment.

### Parser identity

Record a parser behavior version, parser module digest, and fixture-suite digest.

A module digest may change without a behavior-version change only for a behavior-preserving change whose qualified fixtures reproduce their wire-level outputs, errors, and acceptance outcomes byte-for-byte where applicable.

A known behavior change requires a new parser version and profile, even if existing fixtures miss it. Fixture success is a required compatibility gate, not proof that all possible behavior is unchanged. Discovered drift requires investigation and the applicable versioning or withdrawal action.

### Sizes and production support

Existing qualification remains at its documented cells. Qualify named sizes or explicitly preregistered intervals with declared workload and resource bounds.

Endpoint results and an interior check do not silently qualify an interval. An interval protocol must declare that scope beforehand. Finite qualification establishes the declared support scope, not universal reliability.

An underfilled frontier cannot be padded with unrequested work or silently dispatched at an unsupported size. It waits within its deadline, uses an explicitly authorized experimental profile, or returns a precise blocker.

Halving a failed packet is conditional on supported sizes and remaining budgets. Smaller packets are a recovery hypothesis, not a reliability law.

Qualification status and evidence scope remain separate fields. Experimental work can have oracle proof. A qualified route can produce an unverified result.

### Production monitoring

Each cell’s preregistration must define diagnosis or withdrawal thresholds for:

- Wire validity.
- Oracle correctness on matched held-out work.
- Binding-suspect replies.

Specify the completed-call window, behavior before the window fills, denominator, trigger boundary, and reinstatement procedure.

“Below 98% over 50 calls” remains a candidate engineering policy, not reliability evidence. If selected, one invalid reply in 50 equals 98%; two fall below it.

Thresholds never authorize accepting an invalid individual reply. Increased failures trigger diagnosis or withdrawal, never salvage.

### O3: CLI updates remain open

| Issue | Astra position | Opus 5.5 position |
|---|---|---|
| New CLI version | The new version is unqualified for production cells until the applicable qualification protocol passes. Existing evidence remains historical evidence for the old version. | A version change places affected cells in `continuity_pending`. |
| Production resumption | `oz doctor` and two smoke calls are screening, not sufficient qualification today. | Resume after a preregistered continuity smoke of two calls per cell, both wire-valid and oracle-correct. |
| Smoke failure | Keep the candidate version blocked and diagnose under qualification rules. | Suspend the cell until full requalification. |
| Meaning of continuity evidence | A lighter procedure requires a versioned amendment defining eligible changes, checks, failure criteria, and scope. | Continuity evidence restores an existing cell and never qualifies a new cell. |
| Interpretation of two unchanged updates | Evidence for a bounded compatibility proposal, not proof that later updates are harmless. | If full requalification after the next two updates shows unchanged wire validity and oracle outcomes, the smoke rule suffices. |

**Deciding experiment:** Before the next two CLI updates are evaluated, preregister paired old/new runs for every affected cell using the full applicable qualification protocol, frozen oracles, fixed requested-work denominators, and the proposed two-call smoke. Retain failures, accounting, and configuration identities.

A smoke pass followed by a full-protocol failure defeats the proposed smoke procedure for that scope. Detected changes in wire validity or oracle outcomes support continued full qualification.

If both updates show no change, Opus’s proposed empirical condition is met. Astra will accept that result as evidence for a precisely bounded continuity amendment, but not as automatic authority for arbitrary future versions. That remaining inference requires explicit joint assent; the experiment cannot logically prove universal future compatibility.

Until O3 is resolved, this record grants no new production support through the proposed smoke rule. Implementation may proceed with the protocol selectable and versioned, while production uses documented qualified cells at their recorded CLI version.

**Test:** Reject unsupported versions, sizes, and configurations. Reproduce baseline fixtures. Exercise every monitor threshold boundary. Run the paired update experiment without reclassifying earlier exploratory calls as preregistered qualification.

## 10. Integration: one bounded foreground operation

Adopt `oz do` as the default agent entry point over a shared Python service layer.

It submits idempotently, executes within a bounded foreground deadline, and returns compact per-target outcomes, evidence scope, artifact references, blockers, and accounting coverage. The underlying multi-command lifecycle remains available.

A normal bounded fan-out should require one orchestration tool call. This is a design target, not a promise that arbitrarily large deliverables can be consumed without artifact reads. Background execution remains available for longer work.

Timeout and resubmission retain request/run identity and cannot duplicate effects.

Paths and globs resolve within authorized scope into recorded inputs. Command schemas are versioned. The skill teaches appropriate use and evidence interpretation; it does not implement another scheduler.

Complete the missing skill-plus-CLI integration arm before claiming end-to-end savings. Use the smallest wrapper needed to measure today’s path. Do not make the future graph executor a prerequisite for that experiment.

Archived controls are usable only to the extent their setup matches. Otherwise label them historical or run matched controls.

“Four jobs,” “first-job break-even,” and reduced caller-context cost remain hypotheses. Measure complete caller and worker accounting, including artifact reads and subsequent turns required to finish the target. Do not assume every byte is reread on every turn.

MCP remains deferred until a concrete client need or measured CLI limitation justifies it. Any later MCP interface uses the same service layer.

**Test:** Arm K compares `oz do` with the multi-command loop under matched caller contexts, checks, and accounting coverage. Test idempotent resubmission, bounded output, timeout, required artifact consumption, and CLI/Python equivalence.

## 11. Authority: host contracts define permission

Registered host contracts and policy authorize effects. Workers, planners, reference text, generated artifacts, and content hashes do not.

A private snapshot is not automatically an execution sandbox. Record the filesystem, process, environment, and network controls actually enforced.

Artifact access, memo lookup, coalescing, and batching must respect authorization. Hash equality does not grant access.

All admission and execution paths enforce the same boundary. Migration cannot turn a request-recording operation into command execution.

This does not require a new security platform. It requires accurately bounded behavior from the executor being built.

**Test:** Place authority-changing instructions in references, planner output, generated patches, and logs. They must not enable commands, weaken checks, or widen data access. Test authorization changes before dispatch, reuse, and acceptance.

## 12. Lossless values: preserve validated bytes

Retain validated JSON value bytes alongside any lossless typed representation needed by the host.

Storage and unchanged handoffs preserve those bytes, including numeric trailing zeros, exponent spelling, signed zero, large integers, string escaping, and internal whitespace.

Keep `oz_reply.loads` and its rejection behavior unchanged. The lossless representation is downstream of successful strict validation. Extract and retain source value bytes before regrouping or another ordinary serialization loses their spelling.

A number-preserving decoder alone is insufficient for byte identity. Fixing only storage or only `_handoffs` is also insufficient.

For an unchanged value forwarded as a reference, preserve its validated bytes. A supported projection preserves the selected source value where its contract promises that behavior. Host transformations and newly generated wrappers are explicit serializations with recorded policy.

Do not stringify native JSON merely to preserve its text.

Preserve duplicate-key rejection, non-finite rejection, and existing numeric boundary fixtures. Representation improvements cannot quietly broaden accepted input.

Trailing zeros carry task-relevant resolution when the data contract assigns that meaning. Lossless transport does not depend on treating every JSON number as a measurement.

**Test:** Round-trip nested values through reply, regrouping, storage, reload, supported projection, and dependent packet rendering. Include trailing zeros, exponent variants, signed zero, escaped strings, whitespace, large integers, duplicate keys, and existing numeric limits. Require no newly accepted wire input.

## 13. Evaluation and reporting

Freeze requested work and independent checkers before tuning. Score only eligible target completion.

Keep the requested-work definition, paired comparisons, inclusion of failed attempts, and distinction between engineering thresholds and statistical confidence.

For the selective profile:

- An invalid wire reply contributes no accepted records.
- A valid reply may contribute independently accepted records.
- Failed records cannot gain acceptance through record merging.
- Recovery covers every still-eligible unresolved member.
- No acceptance occurs without the declared checks.
- Suspect-reply handling follows clause 2 without erasing independently sufficient evidence.

Report at least:

```text
requested target count and total weight
independently verified weight delivered before deadline
contract-accepted but not independently verified targets
unresolved, quarantined, blocked, and failed targets
complete token total, or explicit incompleteness
physical CLI dispatches, underlying turns, and subagent spawns
queue-to-acceptance and target-delivery latency
memo/dedup state
accounting source, scope, and coverage
qualification status and evidence scope
```

Tokens per requested target and tokens per verified target remain separately labeled. A failure cannot disappear from the requested denominator through internal cancellation, recovery omission, or relabeling as a “nonjob.”

Acceptance timestamps follow required checks and durable commitment. Delivery is recorded separately. Cleanup and late execution costs remain attributable after the scoring deadline.

Runtime verifiers and evaluation oracles must declare independence and scope. Generator self-review is not an independent oracle. Another model’s review is review evidence unless the evaluation qualifies a narrower use.

Savings claims use a cold memo unless labeled warm. Count caller and worker usage without overlap. Unknown required usage prevents an exact cost comparison.

Do not simultaneously change effort, batching, recovery, and memo state when attributing an improvement. End-to-end comparisons may combine qualified changes but must disclose the complete combination.

**Test:** The evaluator rejects apparent gains from extra nodes, omitted hard targets, late checks or delivery, weakened checks, double-counted completion, warm/cold mismatch, or omitted failed-call usage.

## 14. Implementation boundary and governance

Extend the existing host runtime in the signed order. The foundation is a durable executor with registered operations, not a prerequisite general agent platform.

The manual executor uses the same admission, execution, and acceptance paths as any later planner. It cannot become a throwaway second runtime.

The initial architecture does not require a distributed queue, general expression language, retained model session, subagent per job, or automatic planner. Subagents remain a measured execution alternative where their work justifies their cost.

Structural invariants change only through an explicit versioned amendment. Operational parameters such as batch size, effort, concurrency, timeout, and memo retention live in qualified profiles.

A decision reopens only when its test fails, a requirement changes, or equivalent-evidence measurements defeat its rationale. Preference for another abstraction is insufficient.

### Required sequence and gates

| Step | Required work and gate |
|---|---|
| Complete step 2 | The authorized 64-job Sonnet repeat is recorded in `docs/design/brainstorm-2026-10-22/pilot-results.md` (commits b64b003 and a399e88); this record does not restate its outcome. Finish the missing integration arm. Add preregistered size gates at 1, 4, and 16 jobs for the intended cells. Run the integration arm under an explicitly experimental profile until its required sizes qualify. Preserve the distinction between execution-strategy evidence and end-to-end integration claims. |
| Step 3 | Add `oz1g-selective-v1`, candidate/check persistence, bounded recovery, conditional commitment, conservative launch accounting, and lossless handoffs. Preserve the 342-test baseline and pass focused fault and compatibility tests. |
| Step 4 | Build the manual 20-step executor through the shared service layer. Add memo eligibility, freshness, effect reconciliation, and interruption tests. Introduce cross-run batching only with qualified sizes and explicit sharing scope. |
| Step 5 | Optimize effort first, then scheduling from actual traces. Change one variable at a time. Retain held-out improvements only without correctness, deadline, or quota loss. |
| Step 6 | Package the proven interface. Add bounded replanning only for measured completion benefits. Add MCP only for demonstrated need. |

The reported existing size support is 32 and 64 on Sonnet and 64 on the other documented models, subject to each exact registry cell. The new small-size gates do not retroactively qualify experimental pilot records.

A failed size gate produces unsupported sizes or a blocker, not permission to weaken checks or invent filler work.

**Test:** Run the existing baseline and focused invariants before claiming compatibility. Complete the manual 20-step workflow with the planner disabled, then inject interruption and stale dependencies. Success must not require undocumented state repair or planner-held memory.

These decisions add host persistence, checks, synchronization, and recovery work. They impose no new mandatory worker fields or model calls merely to enforce host invariants. Their actual latency and token consequences remain measurements.

## Annex A. Compatibility obligations

This table identifies attachment points and release obligations. It is not evidence that the changes already pass the suite.

| Change | Attachment point | Compatibility obligation |
|---|---|---|
| Selective acceptance | Worker path after strict parsing and before settlement | With no additional checks or containment triggers, reproduce existing acceptance outcomes, errors, and parser limits. Added provenance need not be identical. |
| Generations, epochs, conditional adoption | Additive durable fields and a coordinator adoption path beside settlement | Preserve ordinary in-lease behavior. Test takeover, concurrent acceptance, cancellation, and late results. |
| Dispatch journal and completed captures | Runner/adapter capture path and durable tables | Preserve the compatibility pipe path. Explicitly enable and fault-test the durable path. |
| Ledger export | Transactional events with replayable JSONL export | Preserve `akor.call/1` compatibility. Export failure cannot change authoritative accounting or acceptance. |
| Lossless values | Validated source-value capture, regrouping, storage, and `_handoffs` | Keep `oz_reply.loads` behavior unchanged. Preserve exact unchanged values through the whole path. |
| Graph executor, registry, memo, `oz do` | Additive service-layer modules over the existing inbox | No wholesale conversion prerequisite. Admit the legacy importer only after fixture equivalence. |
| `host.map` | Optional registered expansion operation | Implement only for a committed need and pass bounded, atomic, resumable expansion tests. |
| Claude accounting | `examples/claude_cli_adapter.py` and normalized ledger conversion | Preserve complete `modelUsage` decoding; remove exact totals fabricated from fallback or missing counters. Test coverage and cache conversion. |

The reported 342-test result after `fabbc8a` is baseline evidence from the supplied records. It does not validate the proposed additions or close the missing-accounting cases.

## Annex B. Measurement agenda

These measurements tune parameters or test stated hypotheses. They cannot override the fixed correctness, authority, accounting, or no-repair boundaries.

| ID | Question | Required measurement and decision |
|---|---|---|
| M1 | What does integration cost with the caller included? | Arm K: matched `oz do` and multi-command workflows, including caller/worker usage and required artifact reads. Determines integration economics. |
| M2 | Which packet sizes support heterogeneous work? | Preregister 1, 4, and 16; extend comparisons to 32, 64, and justified interior points with declared workload/resource bounds. Determines supported sizes, not implicit intervals. |
| M3 | Which effort setting works on OZ/1g? | Paired incumbent versus medium, then low, starting with Haiku and Sonnet. Five paired trials may be an initial engineering experiment; support claims remain bounded by its preregistration. |
| M4 | What does selective acceptance retain? | Compare the immutable atomic baseline with `oz1g-selective-v1` on frozen semantic-error fixtures and matched live work. Measure correct completion, retry usage, and verifier latency. |
| M5 | How often does strict wire rejection occur? | Per-cell ledger rates with explicit denominators. Determines diagnosis or withdrawal. It cannot reopen salvage under this brief. |
| M6 | How strong are source-binding checks? | Permutations, swapped plausible answers, repeated values, overlapping schemas, and near-identical references. Measure false acceptance and suspect rates. |
| M7 | Which reuse granularity is sufficient? | Full-snapshot versus declared read-set keys under dependency mutation; inspect CLI-version effects separately. Any missed invalidation defeats the narrower key. No automatic cross-version key relaxation. |
| M8 | What does prefix caching do to quotas? | Matched warm/cold observations with comparable starting allowance and direct quota evidence. Layout changes require their own profile. |
| M9 | Does cross-run batching improve completion? | Wavefront experiment with 16 instances of the manual 20-step workflow, declared sharing scope, and compatible goals. Different goal formulations are separate configurations. Count actual calls under width, size, and byte limits. |
| M10 | What does concurrency above one buy? | Controlled trials measuring completion, latency, rate limits, failures, and observed quota effects. Changes the concurrency default only with evidence. |
| M11 | Is bounded replanning worth its cost? | Manual graph versus one permitted replan on genuine blockers. Include planner calls, invalid proposals, waiting, and downstream checks. |
| M12 | Which Windows crashes remain ambiguous? | Fault injection at every launch, capture, publication, commitment, effect, and export boundary. Determines supported recovery guarantees. |
| M13 | How useful are late pure replies? | Fault tests plus ledger frequency and recovery-cost measurements. Conditional adoption is permitted; practical benefit remains unmeasured. |
| M14 | When should a caller use inline work or `oz do`? | Matched targets and complete sessions, including required later turns and artifact consumption. Any inline threshold or first-job break-even remains a hypothesis. |

The O3 paired CLI-update experiment is additional to this agenda.

## Amendment disposition and final-read boundary

| Amendment | Disposition |
|---|---|
| A1 | Accepted in clause 1: declared computation provenance, pinned execution route, and separate qualification cell. |
| A2 | Accepted in clause 2 under the existing verifier-blocker rule. Automatic regeneration requires authorized recovery and cannot substitute for an unavailable or inconclusive verifier. |
| A3 | Accepted in clauses 2 and 3: run-scoped failures and restricted late-failure settlement. |
| A4 | Accepted in clause 5: runner-published, dispatch-bound completion protocol with explicit uncertainty. |
| A5 | Accepted in clause 5: explicit `synchronous=FULL`. |
| A6 | Accepted in clause 7: priority precedence, within-level aging, declared-load measurements, and `priority_wait`. |
| A7 | Accepted in clause 7: transactional per-user SQLite quota reservations. |
| A8 | Accepted in clause 7: explicit matching sharing scopes. |
| A9 | Accepted in clause 8: remove incomplete-accounting fallbacks, retain reasoning subsets and correct cache representation. |
| A10 | Accepted in clause 9: parser version and digests, with fixture equivalence required for behavior-preserving changes. Known behavior drift always requires versioning. |
| A11 | Open. Both positions and the deciding experiment are retained in clause 9. |
| A12 | Accepted in clause 9: preregistered monitoring thresholds, not retrospective reliability claims. |
| A13 | Accepted in the steps table: small-size qualification gates and experimental integration until supported. |
| A14 | Accepted in clauses 13 and 14: evaluation, cold-memo reporting, additive implementation, and versioned governance. The current steps table governs chronology. |
| A15 | Accepted: measured evidence is separated from normative requirements; no cost laws, code-size promises, or unsupported savings estimates. The optional preamble is omitted. |

O1, O2, O4, O5, O6, and O7 have converged under this text. O3 remains explicitly unresolved. Opus’s final read must confirm this merged wording, including the A2 and A10 boundaries, before the record is represented as jointly signed.

No repository files were changed, no commit was created, and no model experiments or test suite were run for this consolidation. The text is ready for placement in `docs/design`; publication and Opus’s final signature remain outstanding.
