**AKOR Foundation/1 — Astra’s independent decision record, 2026-10-22**

This is my Round 1 position for the next phase, pending critique and reconciliation with Opus 5.5. It defines proposed runtime requirements; it does not claim that they are implemented or measured.

**The central decision is to separate three things: a valid model reply, an accepted job result, and a completed user target.** They have different identities, different failure boundaries, and different evidence requirements.

The objective remains OZ9 §1: maximize independently correct requested work completed before the deadline within subscription quotas; then minimize total tokens; then elapsed time. The supplied accounting audit and measurements are premises for this record. They are not new measurements performed here.

The shipped behavior MUST remain reproducible as an immutable baseline. The proposed host acceptance profile is named `oz1g-selective-v1`. It retains the exact OZ/1g system text, packet grammar, and strict reply parser. It changes semantic acceptance, recovery, and checkpoint behavior explicitly described below. Its performance qualification MUST be earned separately.

Cost statements below describe expected mechanisms, not measured savings or implementation estimates.

---

**D1 — Units and identities. Decision:** Separate requested work, graph structure, execution, effects, and evidence.

| Unit | Required meaning and identity | Content-addressed? |
|---|---|---|
| Request | A caller’s frozen objective, targets, weights, input policy, and constraints. Has an allocated `request_id`. | Its immutable definition has a digest; its identity is not that digest. |
| Run | One execution and budget ledger for a request. Resume retains `run_id`. | No. |
| Target | A predeclared unit of requested work, identified within the request. This is the scoring unit. | Its contract is hashed; its identity is not its output hash. |
| Node | An immutable admitted operation and bindings, identified by `(run_id, node_id)`. | Its admitted specification has a digest. |
| Job | A node’s executable work after inputs resolve: pinned operation, exact inputs, acceptance contract, and execution policy. Has a stable logical identity. | Pure jobs additionally have a reuse key. |
| Attempt | One invocation of an executor. A model attempt may carry many jobs. Each receives a fresh `attempt_id`; membership associates it with jobs. | No. |
| Effect | One authorized mutation intent, with a stable `effect_id` across recovery attempts. | Its intent and preconditions have digests; the effect identity is allocated. |
| Result | A candidate value or artifact, plus its provenance. Acceptance is a separate evidence record binding that candidate to a job. | Artifact content is addressed by digest; acceptance has its own identity. |

A job MUST freeze its resolved inputs before execution. Changing inputs, instructions, or the acceptance contract creates new work; it MUST NOT silently mutate a retry.

Wire job IDs MUST be opaque host-assigned identifiers, unique within each packet and stable for retries of that logical job. The host MUST preserve their mapping independently of record order. A wire ID MUST NOT serve as an attempt receipt or proof of source binding.

Artifacts SHOULD use SHA-256 over exact bytes. Structured manifests and job keys MUST use a versioned, deterministic, lossless encoding with unambiguous component boundaries. Binary floating-point conversion MUST NOT silently alter numeric values. Keeps OZ9 §6.1’s exclusion of run IDs, packet indices, receipts, and enqueue times from pure-job keys.

Two equal results do not establish that two jobs were answered correctly. Conversely, two distinct requested targets may legitimately share computation while retaining separate acceptance and delivery obligations.

**Alternatives rejected:** A content hash as the universal ID conflates repeated intent with repeated content. A node ID as an attempt ID cannot distinguish late execution. Counting nodes as requested work rewards decomposition.

**Invariant:** Repacking, retrying, coalescing, resuming, or replanning cannot change what the caller requested or create additional score.

**Falsification test:** Execute the same request with different batch partitions, node decompositions, retries, and memo states. Target identities and weights MUST remain identical. Replaying a completion MUST NOT increase completed work.

**Cost:** No additional mandatory worker tokens. Host hashing and identity tables add CPU, storage, and moderate implementation work.

---

**D2 — Acceptance semantics. Decision:** Keep atomic wire validation; make semantic acceptance independent per job.

`oz1g-selective-v1` has four gates:

1. **Origin and completion:** Bind captured output to the originating dispatch, expected packet, and executor completion state.
2. **Whole-reply wire validation:** Run `oz1g-header` against the complete reply.
3. **Per-job acceptance:** Run the job’s pinned checks against its exact resolved inputs and candidate.
4. **Target acceptance:** Establish the caller’s required deliverable and evidence, including any integration checks.

No candidate may reach gate 3 before gate 2 succeeds.

| Condition | Scope and outcome |
|---|---|
| Wrong origin, incomplete capture, truncation, or unconfirmed completion | Reject the attempt’s reply; deliver no records. |
| Invalid header or any OZ9 wire violation, including malformed JSON, duplicate keys, missing/extra/duplicate IDs | Reject the entire reply; deliver no records. |
| Valid wire record with task-schema, source-binding, or semantic failure | Reject that job’s candidate; independently accepted siblings may commit. |
| Valid model error record | Record failure for that job. Do not treat it as malformed output or blindly retry it. |
| Verifier unavailable, crashed, or inconclusive | Keep that candidate unaccepted with a verification blocker. Do not label it incorrect or automatically regenerate it. |
| All required checks pass | Commit the job’s acceptance evidence, subject to current attempt authority and freshness. |

Thus, a structurally valid 16-job reply with 15 independently passing records and one wrong record may retain 15 results. A reply missing one of the 16 IDs retains none.

This changes OZ9 §3.2 rule 9’s application of task validators and §3.3’s semantic commit boundary. It keeps the strict parsing rules, including no repair and no recovery from malformed replies.

Per-job checks MUST NOT depend on unaccepted sibling records. A cross-record requirement—such as uniqueness across an entire generated collection—belongs in one collection-valued job or a downstream aggregate check. Its target MUST remain incomplete until that check passes.

**Parse validity is not correctness.** Acceptance evidence MUST identify the checks actually performed: schema, source binding, deterministic constraints, execution evidence, independent oracle, or model review. A single unqualified `verified=true` flag is insufficient.

Index drift is a semantic failure. A correctly spelled job ID merely declares the binding. Verification MUST evaluate the candidate against the host-resolved inputs for that job. Echoing a source ID or digest is not proof that the adjacent answer uses that source.

If no independent semantic check exists, the host may establish a narrower contract acceptance, but MUST NOT promote it to independently verified work. An allowed `unknown` outcome counts only when the frozen target contract regards that outcome as correct.

**Alternatives rejected:** Retaining atomic semantic acceptance makes one wrong answer discard unrelated verified work. Salvaging records from malformed replies changes the explicit wire contract and adds ambiguity before evidence establishes a benefit. Schema-only acceptance cannot catch valid-looking wrong answers.

**Invariant:** Every delivered result passes its own required checks; no invalid reply contributes results; a sibling’s semantic failure cannot erase independently accepted work.

**Falsification test:** Inject swapped values under valid IDs, incorrect units, schema-valid wrong answers, valid errors, and every malformed-wire fixture. Swapped answers MUST fail their own checks; valid siblings survive only when the complete wire passes.

**Cost:** No required wire-token increase. Independent checks consume host time; evidence-bearing result shapes may consume additional tokens. Selective recovery can reduce repeated generation, but that benefit remains unmeasured.

---

**D3 — Retries and fencing. Decision:** Retry logical jobs; fence attempts and effects separately.

Each job MUST have a bounded execution history. Every model dispatch containing it consumes an attempt, including dispatches producing invalid replies. Keeps OZ9’s default of two attempts, including the original, unless a stricter contract applies.

After a wire rejection, **all live member jobs remain unresolved**. Every member still eligible for recovery MUST be scheduled within its remaining limits. Recovery MAY repack them into new valid packets. It MUST NOT preserve any candidate from the rejected reply.

After semantic rejection, only eligible rejected jobs need another model attempt. Accepted siblings MUST NOT be regenerated merely to reconstruct the old packet.

This explicitly replaces OZ9 §§3.3 and 5.3’s requirement to repeat the identical physical batch. The operation, resolved inputs, route, and logical wire ID remain unchanged. New packet indices MUST be rebuilt and validated. Cancellation, exhausted budgets, or expired deadlines may remove jobs from recovery; those jobs remain unresolved in the original request’s accounting.

Additional evidence or repair instructions create a new job. They are not a retry of unchanged work.

Each dispatch MUST persist:

- A unique attempt receipt.
- Its immutable packet and membership.
- The coordinator ownership epoch.
- Each participating job’s active execution generation.
- Budget reservations and timeout.

Result commitment MUST compare these values against current authority in one transaction. A late reply from a superseded attempt MUST NOT complete a newer attempt, enter memo, or trigger dependent work. Its usage MUST still be recorded.

A lease alone is insufficient: an expired worker may still be running. Database changes MUST use fencing checks, and effect execution MUST have its own containment and reconciliation rules.

For effects:

- Retries MUST retain the original `effect_id` and authorized intent.
- A new node ID MUST NOT evade an unresolved effect.
- Resource-conflict checks MUST detect potentially overlapping uncertain mutations.
- Idempotency keys MUST be passed to an effect sink when that sink supports them.
- A sink without fencing MUST NOT be described as fenced merely because SQLite has an epoch.
- An action with uncertain completion MUST become `unknown_effect`; repeat it only after reconciliation establishes safety.

AKOR promises durable logical completion at most once per job generation, and at-least-once execution attempts where recovery is permitted. It MUST NOT promise exactly-once execution for arbitrary commands or external services.

Coalesced pure jobs share the representative’s recovery history. Followers MUST NOT multiply retries or reset the group’s allowance.

**Alternatives rejected:** Retrying whole physical batches couples unrelated workflows. Receipts without active-generation checks accept stale work. A fresh effect ID on every retry defeats idempotency. Blind replay after lease expiry risks duplicate mutation.

**Invariant:** Obsolete execution cannot alter current logical state; uncertain mutations cannot be repeated through renaming; retries cannot replenish their own budgets.

**Falsification test:** Delay attempt A, launch permitted recovery B, then deliver A after B. A MUST be quarantined and accounted. Crash after an effect completes but before its receipt commits; resume MUST reconcile or stop that branch, never blindly replay.

**Cost:** Host-side identities add no worker tokens. Reconciliation can delay progress. Fencing and effect recovery are among the largest implementation and test obligations.

---

**D4 — Memo and freshness. Decision:** Memo stores reusable accepted evidence, not merely answers.

Keeps OZ9 §§6.1–6.3’s key components, conservative read-set rule, pure-operation restriction, and prohibition on memoizing uncertain effects.

The key MUST additionally identify the host acceptance profile and the authorized reuse namespace. A global cache shared across unrelated confidentiality domains is not the default.

An operation’s `pure=true` means that reuse is permitted under its declared contract. It does not assert that a model generates identical text every time. Operations requiring fresh randomness, independent samples, or diversity MUST declare those requirements in their inputs or be nonmemoizable.

Every memo entry MUST retain:

- Exact job-key manifest and result artifact.
- Source and dependency identities.
- Acceptance-check identities, versions, verdicts, and scope.
- Execution provenance.
- Freshness requirements and relevant observation times.
- Authorization scope.

Freshness MUST distinguish:

- **Snapshot-bound evidence:** Valid for the named immutable snapshot.
- **Current-state evidence:** Requires a new comparison with the current dependency state.
- **Time-bounded observations:** Valid only under an explicitly accepted age policy.
- **Revoked or invalidated evidence:** Ineligible for completion or propagation.

A TTL is not proof that a mutable source has remained unchanged. If the target requires current content, content or version preconditions MUST be checked.

A memo hit becomes a result for the new target only after current authorization, key equality, integrity, inexpensive structural checks, and required freshness checks pass. It receives a new acceptance association to that target while preserving the original evidence.

A memo hit may count as independently verified requested work when the retained evidence meets the target’s current verification requirement. It MUST NOT count as a newly executed test, newly generated answer, or new independent observation.

Reusing a patch proposal never reuses its application or tests against another snapshot.

**Alternatives rejected:** Caching by instruction and visible input misses hidden dependencies. TTL-only caching invents freshness. Disabling all reuse sacrifices the intended amortization. Treating every cache hit as verified work inflates completion.

**Invariant:** Reuse is equivalent to satisfying the current acceptance contract with the retained evidence; it cannot broaden that evidence’s scope.

**Falsification test:** Change each relevant dependency, verifier version, instruction, route profile, environment component, and authorization independently. Each MUST cause a miss or explicit revalidation. An unchanged snapshot-bound repeat MUST remain reusable.

**Cost:** Warm reuse can eliminate model calls. Hashing, artifact reads, and freshness checks remain. Complete-snapshot keys may cause conservative misses; narrower keys require evidence that their read sets are complete.

---

**D5 — Durable state and checkpoints. Decision:** SQLite is the authoritative execution ledger; artifact files are immutable data; JSONL is an export.

Keeps OZ9 §9.1’s persistence inventory and artifact-before-reference ordering.

State transitions, budget consumption, attempt authority, acceptance records, effect states, and ledger events MUST commit transactionally. `calls.jsonl` MUST be a replayable export of durable events, not a second independently authoritative database. Export failure MUST NOT lose accounting or change execution state.

The minimum durable sequence is:

1. Persist admitted work, resolved manifests, dispatch intent, and reservations.
2. Attempt executor launch.
3. Durably capture response, completion metadata, and available accounting.
4. Complete whole-reply parsing and persist candidate identities.
5. Run acceptance checks.
6. Commit each accepted job with its evidence and authority checks.
7. Release dependent work.

Multiple completed job checks MAY commit together. A slow or blocked verifier MUST NOT prevent unrelated checked records from committing.

A crash between launch intent and confirmed process creation is intrinsically ambiguous. Recovery MUST conservatively retain the reservation unless it can establish that no dispatch occurred. Such ambiguity MUST be reported; it MUST NOT become either “free” execution or fabricated exact call accounting.

Resume MUST:

- Reconstruct ready work from durable facts.
- Reconcile active processes and effects.
- Continue unfinished checks from captured candidates when possible.
- Preserve accepted artifacts.
- Preserve all consumed budgets, retry histories, and the original deadline.
- Recheck current usability before propagating old evidence.

Historical acceptance records MUST remain immutable. When evidence becomes stale, the current usability projection changes; history is not rewritten to claim the earlier acceptance never happened.

Artifact publication and database durability MUST be tested on the supported local filesystem configuration. A corrupted or missing referenced artifact is a blocker, not permission to invent its content.

**Alternatives rejected:** Process memory plus occasional snapshots loses the exact crash boundary. Dual authoritative SQLite/JSONL writes permit contradictory histories. Restarting from the graph root repeats expensive or unsafe work.

**Invariant:** After any crash, every committed result has durable evidence, every possible external action has a recovery record, and no budget silently resets.

**Falsification test:** Inject process termination before and after each durable boundary, including after acceptance but before JSONL export. Resume MUST preserve accepted work, avoid double commitment, and reconstruct the same accounting state or explicitly report uncertainty.

**Cost:** No mandatory model tokens. Durable writes add latency and storage. Recovery machinery is substantial code, justified by avoiding whole-workflow repetition and uncertain effects.

---

**D6 — Plan and graph format. Decision:** Keep a small submission language; compile every node into an explicit execution contract.

Keeps OZ9 §7.1’s exact four-field node syntax: `id`, `op`, `in`, `after`. Keeps its bindings, finite DAG restriction, and absence of expressions or embedded scripts.

Verifier and budget information MUST be explicit in the **admitted execution descriptor**, without requiring the planner to author security-sensitive fields.

| Effective node field | Source |
|---|---|
| Operation name, version, implementation/instruction digest | Pinned registry |
| Input bindings and dependency edges | Submitted node |
| Resolved input manifest | Host resolution |
| Required checks and minimum evidence scope | Registry and target requirements |
| Route, model, effort, isolation | Pinned run policy and registry |
| Attempt limit, timeout, result bound, deadline | Host-enforced policy |
| Effect capability and resource scope | Trusted configuration and caller authorization |
| Purity, memo eligibility, freshness | Registered operation contract |

The host MUST persist this descriptor and expose it for inspection. Resume MUST NOT reinterpret an old operation name through a newly edited registry.

Humans, deterministic programs, and optional model planners MAY author plans. All submissions pass the same admission checks. Keeps OZ9 §7.2’s atomic admission, revision checks, schema checks, acyclicity, effect checks, and target coverage.

Unknown future values require deferred validation before execution. Admission MUST NOT imply that unresolved inputs have already passed runtime validation.

A replan MAY replace unresolved work, add supported decomposition, or introduce repair work using new evidence. It MUST NOT:

- Change requested targets, weights, or correctness requirements.
- Broaden authority or replenish budgets.
- Mutate previously admitted node identities.
- Reuse an old ID, including a retired ID.
- Reclassify an uncertain effect as harmless.
- Present stale accepted evidence as current.

Keeps OZ9 §9.4’s preservation of accepted history, but clarifies that `done` MUST distinguish historical acceptance from current usability. Invalidated targets cannot remain completed merely because a prior plan once accepted them.

Caller changes to scope or budgets require an explicit request or policy revision. They are not planner decisions.

**Alternatives rejected:** Putting verifier code or arbitrary limits in planner output enlarges the authority boundary. Adding a scripting language creates another execution environment. Keeping verifier and budget selection implicit makes plans unauditable.

**Invariant:** Every executable node has one inspectable, immutable contract; plan authors propose work without gaining authority over its checks or permissions.

**Falsification test:** Submit stale revisions, cycles, weakened terminal checks, unknown operations, out-of-scope effects, and plans referencing stale `done` entries as fresh evidence. Reject before execution. A valid manually authored graph and equivalent planner graph MUST compile to equivalent contracts.

**Cost:** No new worker-envelope tokens. Optional planner catalog views consume tokens. Compilation and admission add moderate code; retaining the existing syntax avoids a second language migration.

---

**D7 — Scheduling contract. Decision:** Use deterministic host scheduling over a freshly validated ready set.

Keeps OZ9 §5.1’s readiness conditions and its preference for deterministic host work, memo resolution, and pure-job coalescing.

Scheduling eligibility MUST be checked again at dispatch, not only when a node first enters a queue. An invalidated dependency, cancelled target, expired authorization, or changed attempt generation removes eligibility.

Cross-workflow batching is permitted only when jobs share:

- Exact goal.
- Qualified route and effort.
- Compatible isolation and execution policy.
- A data-sharing scope authorizing exposure of the packet’s entire reference union.

Every job in a model packet is exposed to the packet’s supplied context. Merely running under the same account does not establish permission to combine confidential workflows.

Keeps OZ9 §5.2’s initial batch defaults and §5.4’s quota-group coordination. These are starting profiles, not permanently optimal values.

Within a run, retain the caller-priority, target-unlocking, critical-path, and enqueue ordering in OZ9 §5.1. Between equal-priority runs, use deterministic rotation with recorded service debt. Imminent deadline infeasibility may override rotation. Overrides MUST be visible; oversubscribed systems MUST NOT claim an unconditional fairness guarantee.

Before dispatch, the host MUST reserve the quota-group slot and participating runs’ protective call allowances atomically. One physical call belongs once in global call accounting. Each participating run consumes one participation allowance; summing those run allowances is not global call count.

The scheduler MAY optimize batch composition, waiting, concurrency, compatible deduplication, and measured priority heuristics. It MUST NOT weaken checks, silently change effort, invent memo hits, or choose an unqualified fallback model.

Dispatch admission MUST reserve time for downstream verification and delivery. Without measured tail durations, use configured timeout bounds. A result verified after the deadline does not contribute deadline-completed work, even if its model output arrived earlier.

**Alternatives rejected:** Model-driven scheduling spends tokens on deterministic decisions. A permanent large-batch quorum harms small frontiers. Global FIFO ignores deadlines; unbounded throughput preference can starve smaller workflows.

**Invariant:** Scheduling changes execution order and grouping, never meaning, authority, or scoring. Queue time is part of elapsed time.

**Falsification test:** Mix broad fan-out, short chains, small workflows, cancellations, and different deadlines in one quota group. Verify bounded waiting under the declared policy, exact global dispatch accounting, no ancestor/descendant co-batching, and no incompatible data sharing.

**Cost:** No scheduling model calls. Queueing and fairness can trade some packing efficiency for completion obligations. Implementation is moderate; policy quality requires workload measurements.

---

**D8 — Accounting. Decision:** Normalize complete invocation usage once, retain raw evidence, and make incompleteness explicit.

For the supplied Claude CLI accounting model, `modelUsage` is the authoritative source for invocation-wide token totals. The top-level `usage` field MUST NOT be substituted: its last-turn scope is insufficient for tool-using calls.

The adapter MUST retain the raw accounting envelope and the versioned decoder that produced normalized fields:

```text
input_uncached
input_cache_read
input_cache_write
output_total
output_reasoning       # nullable subset, when separately reported
usage_complete
usage_source
accounting_schema_version
```

For complete records:

```text
T = Σ(input_uncached + input_cache_read + input_cache_write + output_total)
```

The decoder MUST establish that the three input columns are nonoverlapping for the installed CLI schema. An aggregate total MUST NOT be added to its components.

Reasoning included in `output_total` MUST NOT be added again. Separately reported cache-creation subcategories MUST NOT be counted both individually and through their parent aggregate.

Aggregate `modelUsage` already covering child activity MUST NOT be added to child records a second time. Keep separate counters for:

- Top-level CLI dispatches.
- Underlying model turns, when observable.
- Subagent spawns.
- Participating jobs and workflows.

A parent invocation spawning 16 subagents is not automatically 17 CLI dispatches. It does include all covered model activity in token accounting.

For Codex, the adapter MUST supply an independently qualified whole-invocation usage mapping. Provider neutrality means a common normalized contract, not pretending every provider exposes `modelUsage`.

Failed, malformed, cancelled, timed-out, late, planner, and diagnostic live calls MUST be recorded. If usage is incomplete, totals MUST be `null` with available partial counts and coverage retained. Partial known totals may be labeled lower bounds; they MUST NOT support an exact tokens-per-verified-target comparison.

Cache-adjusted financial cost and subscription quota consumption are separate quantities from `T`. Neither MUST be inferred from raw tokens alone. Quota observations need timestamps, source, scope, and any stated reset time.

The supplied report reproduction establishes arithmetic reproducibility. Coverage of all underlying turns is a separate audit property. Historical data MUST retain its provenance rather than being silently overwritten.

**Alternatives rejected:** Last-turn usage undercounts multi-turn activity. Visible-text tokenization omits reasoning and overhead. Summing root and child aggregates double-counts. Treating missing usage as zero rewards failed telemetry.

**Invariant:** Every included model token is counted once, and every unsupported total is visibly incomplete.

**Falsification test:** Reconcile a controlled multi-turn/subagent invocation against available underlying usage evidence. The adapter MUST reproduce the root aggregate, demonstrate the last-turn discrepancy, and avoid double-counting child activity. Test missing envelopes and interrupted calls explicitly.

**Cost:** No extra model calls during ordinary accounting. Qualification smoke tests have real cost. Raw envelopes, normalized tables, and decoder fixtures add modest code and storage.

---

**D9 — Model boundary. Decision:** Freeze OZ/1g; evolve host behavior through separately versioned profiles.

Keeps OZ9 §§2.1–2.4 verbatim, including exact H, packet fields, job independence, native result values, and strict ID binding. Keeps §10’s fresh authenticated CLI invocations, effective isolation checks, and absence of retained conversation history.

The qualified configuration MUST identify at least:

```text
wire and parser versions
host acceptance profile
adapter and CLI versions
resolved model identity and effort
effective instructions and isolation controls
batch and resource limits
qualified workload/evidence scope
```

A model-family label is insufficient. Qualification MUST NOT silently transfer across effort, batching, adapter, acceptance, or model changes.

“Teaching once” SHOULD mean amortizing trusted operation authoring, deterministic handlers, schemas, views, and reusable evidence. Every actual worker call must still receive sufficient instructions and input. An acknowledgement does not install durable knowledge in a future fresh invocation.

Provider prefix caching is an incidental optimization whose effects MUST be measured. It is not a semantic dependency.

A wire change requires an explicit versioned proposal, parser fixtures, migration behavior, and end-to-end qualification. Host-side semantic recovery MUST NOT be disguised as an unchanged atomic acceptance implementation.

No online wording search, progressive session, or model-driven routing loop enters this foundation.

**Alternatives rejected:** Hidden learned dictionaries violate fresh-call sufficiency. Retained conversations grow cost and complicate provenance. Simultaneous wire and runtime changes obscure causal attribution.

**Invariant:** Any qualified invocation is reproducible from its transmitted packet, pinned adapter profile, and recorded unavoidable instructions.

**Falsification test:** Run the same operation in a fresh isolated invocation without prior teaching history. If essential information is missing, the operation contract fails. Detect any adapter-added history or unsupported control.

**Cost:** Preserving explicit instructions retains some input overhead. Stable prefixes may help caching, but no quota benefit is assumed. Version/profile bookkeeping is modest code.

---

**D10 — Integration surface. Decision:** The machine-readable CLI is the primary public contract; all other surfaces share its underlying semantics.

Keeps OZ9 §11’s command responsibilities, compact JSON output, stderr diagnostics, and separation between export and publication.

The implementation SHOULD expose a small Python service layer used by the CLI. A Python API may call that layer directly; it MUST NOT maintain a second execution engine or separate interpretation of acceptance, budgets, and resume.

Public command schemas MUST be versioned. Mutating commands MUST support caller-scoped idempotency keys: repeating the same command returns the original operation identity; reusing a key with a different payload is a conflict. Revision checks remain necessary for graph mutation.

A Claude Code skill SHOULD teach the compact loop:

```text
create → submit → execute → inspect status → consume accepted result
```

It MUST NOT reproduce the runtime in prompts, poll by sending repeated model messages, or request routine model summaries of status.

MCP is deferred until a concrete consumer requires it. If added, it MUST call the same service layer, expose bounded views, and preserve the same permissions and evidence semantics.

Keeps authenticated `claude -p` and `codex exec` as the required adapters. No API key is required. No command implicitly commits, pushes, or publishes.

**Alternatives rejected:** A skill-only runtime moves durable control into model context. MCP-first design adds integration work before proving execution. Separate Python and CLI semantics create incompatible clients.

**Invariant:** Equivalent commands through supported interfaces produce the same state transitions and acceptance evidence.

**Falsification test:** Replay a command suite through CLI and Python, including duplicate submissions and stale revisions. Compare durable outcomes. If MCP is added, it must pass the same suite.

**Cost:** CLI orchestration can reduce repeated teaching and status tokens. JSON serialization adds small overhead. A shared service layer limits code duplication; MCP contributes no initial implementation cost.

---

**D11 — Authority and execution trust. Decision:** Model output proposes data; trusted host contracts authorize actions.

Keeps OZ9 §§2.3 and 4’s registry ownership, explicit host execution, argument-vector recipes, private workspaces, and publication preconditions.

A planner, worker, retrieved document, or test log MUST NOT create a command recipe, weaken a verifier, enlarge a capability, or grant permission. Schema-valid output does not change that rule.

A private workspace protects source state; it is not by itself an execution sandbox. Running generated code or repository tests requires an explicit execution policy covering filesystem access, environment, network access, process lifetime, and permitted effects.

The adapter or host MUST report which controls it actually enforces. A route requiring unavailable controls is unavailable under that policy.

Evidence artifacts MUST retain the relevant input and output identities without exposing credentials. Authentication material MUST NOT enter model packets, ordinary logs, public exports, or reusable memo content.

Cross-workflow deduplication, batching, and memo lookup MUST respect authorized data-sharing boundaries. An artifact digest is not access permission.

**Alternatives rejected:** Trusting planner-selected tools delegates authority to untrusted output. Treating “refs are data” as a security mechanism confuses an instruction with enforcement. Treating a worktree as a sandbox overstates isolation.

**Invariant:** No model-authored value can increase execution authority or widen data access.

**Falsification test:** Place instructions to run commands, expose secrets, or disable checks inside references, patches, planner output, and failure logs. Those contents MUST remain data or untrusted proposals; no additional capability may become available.

**Cost:** No mandatory worker tokens beyond necessary task context. Isolation setup and restricted execution can add latency. Capability enforcement and adversarial fixtures add meaningful host code.

---

**D12 — Evaluation and qualification. Decision:** Freeze the requested work and independent checker before tuning; score only eligible target completion.

Keeps OZ9 §§12.1–12.3’s requested-work definition, paired comparisons, inclusion of failed attempts, and distinction between engineering thresholds and statistical confidence.

The acceptance-profile change requires updating the atomic-acceptance gate:

- An invalid wire reply contributes no accepted records.
- A valid reply may contribute independently accepted records.
- Failed records cannot contaminate siblings or gain acceptance through record merging.
- Protocol recovery schedules every still-eligible unresolved member.
- No acceptance occurs without the declared checks.

Report at least:

```text
requested target count and total weight
independently verified weight completed before deadline
contract-accepted but not independently verified targets
unresolved and failed targets
complete token total, or explicit incompleteness
physical CLI dispatches
queue-to-acceptance latency
memo/dedup state
```

Tokens per requested target and tokens per verified target MUST remain separately labeled. A failure MUST NOT disappear from the denominator by becoming a “nonjob,” being cancelled internally, or being omitted during recovery.

The acceptance timestamp MUST follow completion of the required checks and durable commitment. Cleanup and late execution costs remain attributable even after the scoring deadline.

Runtime verifiers and evaluation oracles MUST have declared independence and scope. A generator’s self-review is not an independent correctness oracle. A second model’s review is evidence of review unless the evaluation explicitly qualifies a narrower use.

Do not change effort, batching, semantic recovery, and memo state simultaneously when attributing performance. End-to-end system comparisons may combine qualified changes, but MUST disclose the complete combination.

**Alternatives rejected:** Measuring only accepted rows hides failures. Comparing cold baseline against warm candidate confounds reuse. Reporting generated answers before verification rewards unfinished work.

**Invariant:** A performance improvement reflects more correct requested work or less complete cost for equivalent work—not changed scoring or weaker evidence.

**Falsification test:** Construct a configuration that produces extra nodes, drops hard targets, finishes verification after deadline, or omits failed-call usage. The evaluator MUST deny the apparent improvement.

**Cost:** Independent checks and paired trials consume time and subscription capacity. Reusing frozen fixtures and reliable accounting avoids repeated inconclusive experiments.

---

**D13 — Implementation boundary and evolution. Decision:** Extend the existing host runtime in the signed sequence; keep the planner optional.

The foundation is a small durable executor with registered operations, not a general agent platform. SQLite and Python stdlib remain sufficient starting choices.

The signed sequence governs implementation:

1. Preserve the frozen evaluation and complete the running 16-job pilot.
2. Implement selective acceptance and fencing, with the durable records needed to test them.
3. Execute the manual 20-step workflow with checkpoints and freshness-verified memo.
4. Optimize one variable at a time, effort first.
5. Package the stable interfaces.
6. Add bounded replanning only if measured blockers justify it; add MCP only for an identified integration need.

The manual executor MUST use the same admission, execution, and acceptance paths that a future planner will use. It MUST NOT become a throwaway second runtime.

The initial architecture MUST NOT require a distributed queue, general expression language, retained model session, subagent per job, or automatic planner. Subagents remain a measured execution alternative where their independent work justifies their cost.

Structural invariants in this record require an explicit versioned amendment to change. Operational parameters—batch size, effort, concurrency, timeouts, and memo retention—belong in qualified profiles and may evolve through measurement.

A decision may be reopened because its falsification test fails, a stated requirement changes, or equivalent-evidence measurements defeat its rationale. Preference for a different abstraction is not sufficient.

**Alternatives rejected:** Building the full planner first postpones proof of execution safety. Rewriting the existing core discards useful baseline behavior. Freezing tuning parameters as architecture prevents adaptation.

**Invariant:** A manually submitted graph remains sufficient to exercise the complete correctness and recovery model; planning adds proposals, not indispensable runtime authority.

**Falsification test:** Complete the 20-step workflow with the planner disabled, inject crashes and stale dependencies, and resume within original budgets. If success depends on undocumented manual state repair or model-held history, the foundation is incomplete.

**Cost:** Initial persistence and verification work is significant. Avoiding premature planner and integration layers reduces immediate code and model calls. The eventual savings must be measured end to end.

---

**Required amendments to OZ9**

The changes MUST be recorded explicitly rather than described as full compatibility with the existing atomic-acceptance specification.

| OZ9 location | Foundation/1 treatment |
|---|---|
| §1 acceptance statement | Separate atomic wire validity from the selected host semantic-acceptance profile. |
| §§2.1–2.4 | Keep verbatim. |
| §§3.1–3.2 | Keep strict whole-reply parsing; move task-specific acceptance to independent job checks after parsing. |
| §§3.3 and 5.3 | Permit selective semantic commitment and logical-job recovery; prohibit reuse of any record from a wire-rejected reply. |
| §6 | Keep key and memo principles; add acceptance-profile identity, authorization scope, and explicit freshness evidence. |
| §7.1 | Keep submission syntax; require an inspectable compiled execution descriptor. |
| §9.1 | Checkpoint individual accepted jobs and durable candidate/check states. |
| §9.4 | Preserve accepted history while excluding stale evidence from current completion and reuse. |
| §§10 and 12.1 | Require qualified invocation-wide usage decoding; use Claude `modelUsage`, not last-turn `usage`. |
| §§12.2–12.4 | Replace the new profile’s atomic-semantic gates and recovery wording; retain legacy baseline tests separately. |
| §13 | Follow the owner’s signed implementation sequence. |

**Open questions requiring measurement**

| Question | Required experiment and decision evidence |
|---|---|
| Which execution form wins the 16-job workload? | Finish the running pilot with equivalent targets and verification. Include whole-invocation usage, internal spawns, failures, and elapsed time. The supplied subagent smoke is diagnostic evidence, not a completed comparative qualification. |
| Does medium effort improve OZ/1g? | Compare qualified incumbent versus medium on fresh OZ/1g workloads, starting with Haiku and Sonnet. Earlier native-JSON effort results select candidates; they do not qualify this wire. |
| How valuable is semantic selective acceptance? | Compare legacy atomic behavior and `oz1g-selective-v1` with frozen semantic-error fixtures and fresh live workloads. Measure retained correct work, retry cost, and verifier latency. |
| Should malformed-reply salvage ever be introduced? | First measure malformed-reply frequency and lost correct work under strict parsing. Any later salvage proposal needs a separate profile, adversarial identity tests, and a wire-contract decision. It is excluded from this foundation. |
| Which batch sizes survive heterogeneous work? | Test `1, 4, 16, 32, 64` with short/long outputs, different operations, shared references, and deadline-sensitive chains. Measure complete cost and verification-adjusted completion. |
| How strong are source-binding checks? | Use ID permutations, swapped plausible answers, repeated values, overlapping schemas, missing inputs, and near-identical references. Measure false acceptance as well as rejection. |
| What is the useful memo granularity? | Compare full-snapshot keys with explicitly declared narrower read sets under controlled dependency mutations. Any missed invalidation disqualifies the narrower key. |
| What does prefix caching do to subscription capacity? | Run matched warm/cold conditions with quota observations and comparable starting allowance. Raw cached-token counts alone cannot establish the answer. |
| Which scheduling policy helps mixed workflows? | Replay finite mixed workloads under fixed deadlines, quota groups, and caller priorities. Compare completed weight, latency, service debt, and batch utilization. |
| What does concurrency actually buy? | Begin at the specified single in-flight call per quota group. Increase only in controlled trials measuring throughput, rate limits, failures, and observed subscription effects. |
| Is bounded replanning worth its cost? | Compare the manual graph with planner-assisted recovery on genuine blockers. Charge planner calls, invalid plans, waiting, and downstream verification. |
| Which crashes remain ambiguous? | Fault-inject launch, capture, artifact publication, acceptance commit, effect completion, and export boundaries on the actual supported platform. Record uncertainty rather than inventing exactly-once behavior. |

Round 1 is complete as an independent decision text. The next review should challenge the acceptance boundary, retry regrouping, freshness semantics, and effect fencing before these requirements are jointly ratified. No implementation or performance qualification is claimed here.

Historical memory was used only for continuity on language ownership and whole-cost evaluation preferences; the supplied current brief governs this record.


