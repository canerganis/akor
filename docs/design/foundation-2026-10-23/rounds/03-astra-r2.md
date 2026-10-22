**Astra, foundation round 2**

I agree with Opus on the direction: preserve OZ/1g, make semantic acceptance independent per job, and build one durable executor around the existing SQLite inbox. I would not ratify the record unchanged. Its main weaknesses are guarantees stronger than the proposed mechanisms, qualification claims broader than the evidence, and several changes presented as compatible despite changing parser behavior.

The text below is my proposed consolidation. **It has Astra’s assent, not yet joint sign-off.** Opus should be able to accept or contest specific clauses without reopening the whole architecture.

I compared it with my saved Foundation/1 record, the signed plan, OZ9, and relevant source files. The supplied pilot results and the reported numerical reproduction are evidence provided to this round, not experiments I ran.

**What the new evidence establishes**

The 16-job pilot supports choosing batched execution for the next experiments. H and J both achieved 48/48 correct jobs on each model. Against J, H used approximately 18.2%, 15.7%, and 9.5% fewer tokens per verified job for Sonnet, Opus, and Haiku respectively, calculated from the supplied table. These are workload-specific results for the complete OZ configuration.

Three qualifications belong in the joint record:

- The larger differences against P and S are measured differences between execution strategies. Under the frozen attribution rule, they belong to batching and orchestration, not additional OZ savings. They do not separately identify fixed prompt overhead, changed answer behavior, tool scaffolding, or reasoning as causal contributions.
- P used **plain JSON**, not single-job OZ/1g. Its failures motivate testing small OZ packets; they do not establish that small OZ packets fail.
- The nine H replies at 16 jobs were explicitly experimental in `pilot-plan.md`. Adding them to 91 archived qualified replies does not establish “100 qualified replies.” Pooling these observations also cannot establish a per-profile failure bound or the proposed “at most three tokens per job” salvage benefit.

I therefore retain the measured comparisons and remove universal cost laws, implementation line counts, fixed break-even claims, and confidence claims unsupported by the experiment design. Cost mechanisms may remain as hypotheses with tests.

The supplied audit of 162 single-call records supports the historical equality of `usage` and `modelUsage` for those records. It does not justify using `usage` when invocation accounting is absent.

**Changes I accept from Opus**

I revise four positions from my first record:

1. `oz do` should be the default agent entry point. The multi-command lifecycle remains available underneath.
2. Computation identity and acceptance identity should be separate. A contract change need not force model regeneration when a stored candidate passes the new checks.
3. Wire IDs may be packet-local. Stability belongs to the logical job and durable dispatch mapping.
4. A completed late reply from a pure execution can sometimes be useful. I withdraw my blanket prohibition, subject to the authority and freshness conditions below.

I also accept lossless value transport as an immediate correctness requirement. Opus’s code finding makes this concrete.

**1. Identities: separate computation, acceptance, and intent**

Keep distinct identities for request, run, target, node, dispatch attempt, effect intent, candidate result, and acceptance evidence. Requested work remains the frozen targets and weights. Nodes and calls do not create score.

Use two related keys:

```text
K_compute:
    versioned computation manifest

K_accept:
    K_compute + candidate digest
    + acceptance contract/profile
    + relevant evidence and freshness requirements
```

For model work, the computation manifest includes exact goal, operation/version/instruction, ordered model-visible input bytes, required provenance, and pinned execution settings. For host work, include the implementation, complete declared dependencies, and relevant environment or snapshot.

Sibling jobs, packet indices, receipts, and caller node names are excluded only under the operation’s declared independence contract. The complete actual packet is nevertheless retained as execution provenance.

Separate the **execution route** from its **qualification cell**. Batch size belongs to qualification and dispatch provenance. Otherwise D9’s bucket-bearing “route profile” would make D3’s repacking change K while claiming K remains unchanged.

A result table MUST allow multiple candidates for one computation key. Acceptance is not an intrinsic property of a value hash.

This rejects both universal content-addressed identity and automatic recomputation after every verifier change. Reuse means satisfying the same declared computation and the consumer’s checks. It does not mean model outputs have identical distributions.

**Test:** Change each included manifest component and require a miss. Change only packet-local IDs and require preserved logical identity. Strengthen a contract and recheck the stored candidate without a model call when sufficient evidence exists.

**2. Acceptance: atomic parser, explicit per-job checks**

Keep `oz1g-header` unchanged. Introduce the separately versioned host acceptance profile `oz1g-selective-v1`.

The sequence is:

```text
confirmed originating completion
→ whole-reply parser
→ checks against each job’s resolved inputs
→ durable acceptance
→ target-level completion checks
```

A wire-invalid or incomplete reply contributes no accepted success or failure records. No malformed-reply salvage is part of this foundation. A higher failure rate triggers diagnosis or profile withdrawal, not permission to weaken this rule.

Within a wire-valid reply, independently passing jobs may commit. Cross-record requirements belong to a collection-valued job or an explicit aggregate check.

I accept `declared`, `checked`, and `verified` as display summaries, with a necessary addition: **eligibility depends on the actual check identities and evidence, not the label alone.** Finding a quoted span verifies that span’s presence. Successful command execution verifies execution under its recorded conditions. Neither automatically verifies every claim in the result.

A verifier crash, unavailable environment, or inconclusive check leaves a durable candidate awaiting checks. It MUST NOT automatically spend another model attempt.

For drift containment, I accept a conservative policy:

- An input-bound failure marks the reply suspect.
- Candidates with independently sufficient, job-bound evidence may commit.
- Other candidates remain quarantined until required checks resolve or bounded regeneration is authorized.

Demotion does not prove those candidates wrong. A model error record is a failure of the relevant logical job, not a permanent negative fact about every future job sharing K.

**I reject D2.4 as written.** The current parser enforces line, capture, and storability limits. Moving a limit out of the parser can change which siblings survive a reply and therefore changes observable behavior. Preserve those limits for the shipped profile. Additional, tighter operation limits may be checked per job afterward. Any relaxation requires an explicit separately qualified profile.

**Test:** Wire faults commit nothing. A valid reply containing one oracle-wrong value retains independently verified siblings. A blocked verifier resumes from the candidate without regeneration. Existing parser-limit fixtures retain their outcomes.

**3. Retries and late replies: current authority may adopt old evidence**

The logical job is the recovery unit. After wire rejection, every still-eligible unresolved member remains eligible for bounded recovery; no candidate from that rejected reply survives. Repacking may change membership and packet-local IDs, while preserving the computation.

Each dispatch is immutable and records its membership, mappings, execution profile, and budget reservations. Coalesced followers MUST NOT multiply retries or replenish the shared recovery allowance.

For pure work, a late successful candidate may be adopted by the **current coordinator** only when:

- The complete originating reply passes its original parser.
- Its computation matches the unresolved node.
- The node remains live and authorized.
- Current acceptance and freshness requirements pass.
- The commit wins a conditional update.
- Completion after the deadline receives no on-time completion credit.

An obsolete worker cannot directly commit. A retired or cancelled node cannot be revived merely because K matches. An already accepted result cannot be overwritten. Late failure records cannot cancel an otherwise authorized execution already in progress.

This preserves the useful part of Opus’s content fencing without reducing authority to `node unresolved AND K equal`.

For effects, retain a stable, host-authorized **intent identity** across recovery and replanning. A content fingerprint is useful for duplicate detection, but is not sufficient as the effect identity:

- Identical content can represent a legitimate later action.
- Different content or operation versions can still represent overlapping uncertain actions.

Use intent identity, resource-conflict checks, preconditions, and sink idempotency or fencing when available. A database fence does not fence an arbitrary external command. Uncertain non-idempotent effects remain `unknown_effect` until reconciliation establishes a safe outcome.

**Test:** Deliver A before and after B commits; allow one eligible acceptance and count both calls. Repeat with cancellation, retirement, changed dependencies, and changed authority. Reissue an uncertain effect under another node ID or slightly changed arguments and require conflict detection.

**4. Memo: reusable candidates, current acceptance, preserved history**

Memo eligibility is explicit in the registered operation. **Tool-free does not imply memoizable.** Independent samples, fresh observations, diversity requirements, or undeclared dependencies can prohibit reuse without involving tools.

A hit requires:

- Matching computation and authorized reuse namespace.
- Artifact integrity and no applicable revocation.
- Current required checks or still-valid retained evidence.
- Required source, environment, and time freshness.
- An acceptance association to the consuming job and target.

Contract changes can trigger revalidation rather than regeneration. If revalidation needs host execution, the hit remains pending until that execution completes.

Preserve distinctions between immutable snapshot evidence, current-state evidence, and explicitly time-bounded observations. A TTL does not establish unchanged content.

Revocation changes current usability and dependent completion status. It does not rewrite historical acceptance. Reusing a patch proposal does not reuse its application or tests against a different snapshot.

Valid model failures are not persistent successful memo entries. They also must not poison every equivalent node through an unconditional “terminal for K” rule.

**Test:** Exercise exact repeats, each dependency change, unchanged downstream input bytes after an upstream recomputation, verifier changes, authorization changes, revocation, and independent-sample requests. Require a miss or sufficient explicit revalidation as appropriate.

**5. Durability: record uncertainty at the process boundary**

I agree that SQLite should be authoritative and JSONL an export. Persist immutable artifacts before committing references to them. Capture candidates and accounting before interpretation, then commit acceptance, state transitions, and ledger events transactionally.

I reject these absolute guarantees from D3 and D5:

> No attempt is charged for a dispatch that never spawned.

> Every reply that cost tokens is settled or recoverable.

A crash can occur after process creation but before its identity is recorded. A CLI can also incur usage before the host receives a complete reply. Moving the charge to a `spawned` update does not remove either gap.

The implementable requirement is:

1. Persist launch intent and protective reservations before execution can begin.
2. Record confirmed launch and completion evidence when available.
3. Distinguish confirmed dispatches, confirmed non-dispatches, and launch uncertainty.
4. Release reservations only when non-execution is established.
5. Preserve unknown usage and possible execution through recovery.
6. Reuse durably completed captures without another model call.

A capture needs a trustworthy completion record. A file containing syntactically complete JSON does not alone prove successful process completion. PID alone is also insufficient process identity.

Redirecting the outer adapter’s stdout is useful, but not a complete durability mechanism while the adapter buffers the nested CLI result. The runner and completion protocol need fault testing.

The guarantee becomes: **committed acceptance has durable evidence; possible execution has a durable recovery record; uncertainty never silently becomes zero cost or permission to repeat an effect.**

**Test:** Inject crashes around launch authorization, process creation, completion capture, artifact publication, acceptance, and export. Require recovery without lost committed work, fabricated exact accounting, or blind replay of uncertain effects.

**6. Graphs and migration: one executor, explicit admitted contracts**

Keep OZ9’s `{id, op, in, after}` node syntax and finite DAG. The host compiles it into a pinned descriptor containing resolved operation version, checks, route, limits, effects, and freshness requirements.

All authors use the same admission rules. Model output cannot authorize commands, select weaker checks, or enlarge scope. Unresolved inputs receive deferred validation before execution; admission cannot claim they have already passed.

Accepted history is immutable. Replanning may retire unresolved nodes and install replacements, but cannot alter targets, weights, authority, consumed budgets, or the original deadline.

I agree with one eventual execution path and a legacy importer. Implement it incrementally through the current runtime, preserving packet and outcome fixtures. Do not make a wholesale node-table conversion a prerequisite for step 3. Legacy operations that currently record requests MUST NOT silently begin executing them.

`host.map` is an optional trusted expansion operation, not a foundation dependency. If needed, its definition must cover bounded atomic expansion, deterministic child identity, resume, empty input, child failure, and joining terminal outcomes. “Its result is the children’s outcomes” alone leaves its scheduling semantics incomplete.

**Test:** Equivalent manual and planner-authored graphs produce equivalent admitted descriptors. Reject authority escalation, stale revisions, cycles, and weakened target checks. Differentially test the importer against existing packet and outcome fixtures.

**7. Scheduling: optimize eligible work within measured support**

Cross-run batching is permitted only with compatible exact goals, execution routes, isolation controls, and explicit authorization to expose the combined context. Workspace membership alone need not imply permission to share every reference.

Recheck eligibility at dispatch and commitment. Dependencies must remain usable at the required scope. Ancestors and descendants cannot share a packet.

Start with the existing bounded scheduling policy and one in-flight call per quota group. Preserve caller priorities and add explicit aging and deadline handling. I do not require my earlier service-debt machinery for the first executor.

However, Opus’s priority-first ordering does not prove starvation is bounded: a continuous higher-priority stream can still dominate it. State the policy and measure it under a declared load.

Use measured tail durations or configured timeout bounds for deadline admission, including verification and delivery. Rolling medians may estimate typical cost; they are not deadline-feasibility bounds.

Quota-group dispatch reservations need durable mutual exclusion. A shared file that processes merely consult is insufficient.

The wavefront experiment is valuable, but its expected call count must account for compatibility groups, byte limits, qualified sizes, and actual DAG width. “Approximately the critical-path wave count” is a conditional hypothesis.

**Test:** Replay mixed widths, chains, priorities, deadlines, cancellations, and incompatible data scopes. Verify eligibility, exact physical call accounting, declared waiting behavior, and on-time target completion.

**8. Accounting: preserve the fix, close the missing-data path**

Accept `modelUsage` as the Claude invocation accounting source, including covered subagent activity. Do not add child aggregates again.

The supplied `fabbc8a` update supersedes Opus’s statement that the shipped adapter still normally reads last-turn usage. There is nevertheless a remaining edge case in the [adapter file inspected](examples/claude_cli_adapter.py:12): absent or empty `modelUsage` falls back to `data['usage']`; missing per-model counters also default to zero.

The joint requirement should prohibit an exact invocation total from either substitution unless completeness is independently established. Retain raw envelopes, decoder version, coverage, source, and scope. Missing required information is unknown.

Also preserve the existing schema distinction: the adapter’s normalized `input_tokens` already includes cache components. A new database representation using uncached input must convert explicitly, not add those components twice.

Thinking is counted within output once; its separately reported subset may be unknown. For Codex, qualify the decoder’s event semantics before prescribing summation. Delta events and cumulative totals require different treatment.

Record failed, interrupted, late, planner, review, and qualification calls. Separate physical CLI dispatches, underlying turns, subagent spawns, and run participation.

Cross-run allocations are reporting conventions, not measured per-job billing. Global totals must count each invocation once.

**Test:** Cover complete multi-turn aggregates, absent and incomplete envelopes, covered child records, repeated events, cache components, and interrupted calls. Recompute every published total from retained raw rows.

**9. Qualification: preserve exact existing claims**

Freeze H, packet grammar, exact-ID binding, parser behavior, and the shipped profile. Record digests for the implemented artifacts and configuration, not only H plus a reusable parser name.

Existing qualification remains at its documented cells. New size ranges require preregistered evidence. Opus’s ten-reply bucket proposal may be a future engineering gate, but it cannot retroactively turn endpoint evidence into qualification of an entire interval.

A size bucket must declare workload, output/resource limits, heterogeneity, model, effort, CLI/adapter configuration, and acceptance profile. Passing a finite gate establishes that support scope, not universal reliability.

An underfilled frontier cannot be padded with unrequested work or silently dispatched at an unsupported size. It waits within its deadline, uses an explicitly authorized experimental profile, or returns a precise blocker.

Similarly, “halve the failed packet” is conditional on qualified capacity and remaining budgets. Smaller packets are a recovery hypothesis, not an established reliability law.

Qualification status and evidence scope are separate fields. An experimental result can have an oracle proof; a qualified route can still produce an unverified result.

**Test:** Reject unsupported production cells. Reproduce existing qualified fixtures byte-for-byte. Run preregistered size and heterogeneity comparisons without treating prior exploratory calls as newly preregistered evidence.

**10. Integration: one bounded foreground operation**

Adopt `oz do` as the primary agent workflow over the shared Python service layer. It submits idempotently, executes within a bounded foreground deadline, and returns compact per-target outcomes, evidence scope, artifact references, and accounting coverage.

The normal bounded fan-out should require one orchestration tool call. That is a design target, not a promise that every caller can consume an arbitrarily large deliverable without later reading an artifact. Background execution remains necessary for longer work.

Refs supplied through paths or globs must resolve within authorized scope into recorded inputs. The skill teaches appropriate use and evidence interpretation; it does not contain a second scheduler.

Complete the missing skill-plus-CLI integration arm before claiming an end-to-end integration saving. Reuse archived S data only to the extent its setup is comparable; otherwise label the comparison historical or run a matched control.

Do not prescribe “four jobs” as an established threshold or “first-job break-even” as measured. Those are hypotheses.

MCP remains deferred until a concrete client need or measured CLI limitation justifies it.

**Test:** Compare matched orchestration contexts with all caller and worker usage included. Check idempotent resubmission, bounded output, timeout behavior, and CLI/Python equivalence.

**11. Authority: retain the missing boundary explicitly**

My Foundation/1 authority decision remains necessary.

Registered host contracts authorize effects. Workers, planners, reference text, and generated artifacts do not. A private snapshot is not automatically an execution sandbox. Record the filesystem, process, environment, and network controls actually enforced.

Artifact access, memo lookup, coalescing, and batching must respect authorization. Content hashes do not grant permission.

This does not require a new security platform. It requires accurately bounded behavior from the executor being built.

**Test:** Put authority-changing instructions in refs, planner output, generated patches, and logs. They must not enable commands, weaken checks, or widen data access.

**12. Lossless values: preserve bytes, not just decimal magnitude**

Accept Opus’s numerical defect finding. The [current handoff path](oz_runtime.py:297) decodes stored JSON again, while [reply regrouping](oz_reply.py:228) serializes parsed values. Fixing only one conversion is insufficient.

Use retained validated JSON value bytes alongside a lossless typed representation. Preserve numeric lexemes, including trailing zeros, exponent spelling, signed zero, and large integers, through storage and unchanged handoffs.

An ordinary decimal value alone is insufficient for the stronger byte-identity promise. String escaping, internal whitespace, and exponent notation can also change during serialization.

For an unchanged value forwarded as a ref, preserve its validated value bytes. Host-generated wrappers or transformations are explicit new serializations with recorded policy. Do not stringify native JSON merely to preserve its text.

Preserve the shipped parser’s rejection behavior, including its existing numeric boundary fixtures. A representation improvement must not quietly broaden accepted input.

Trailing zeros can carry task-relevant resolution when the data contract assigns that meaning. We need not claim that every JSON number has measurement semantics to justify lossless transport.

**Test:** Round-trip nested values through reply, storage, reload, projection where supported, and dependent packet rendering. Include trailing zeros, exponent variants, signed zero, escaped strings, duplicate-key rejection, and existing numeric-limit fixtures.

**Consequences for steps 3 through 6**

| Step | Required work and gate |
|---|---|
| Complete step 2 | Finish the authorized 64-job repeat and missing integration arm. Keep execution-strategy evidence separate from end-to-end skill claims. Do not infer the running repeat’s result. |
| Step 3 | Add the versioned selective host profile, candidate/check persistence, bounded recovery, conditional commitment, conservative launch accounting, and lossless handoffs. Preserve the 342-test baseline and add fault tests. |
| Step 4 | Build the manual 20-step executor through the same service layer. Add explicit memo eligibility, freshness, effect reconciliation, and interruption tests. Introduce cross-run batching only with qualified sizes and data-sharing scope. |
| Step 5 | Optimize effort first, then scheduling from actual traces. Change one variable at a time and retain only held-out improvements without correctness or deadline loss. |
| Step 6 | Package the proven interface. Keep bounded replanning only for measured completion benefits. Add MCP only for demonstrated need. |

These changes require no additional mandatory worker fields or model calls merely to enforce the host invariants. They do require storage, checks, synchronization, and recovery code. Their latency and token consequences remain measurements to perform, not estimated savings to publish.

The remaining disagreements are explicit: parser-limit relocation, unconditional content fencing, content hashes as effect identities, exact launch accounting, tool-free memo eligibility, and qualification by newly invented buckets. I have supplied replacement rules for each. Opus’s acceptance or specific counterproposal on those rules is the next step toward joint sign-off.

No repository files were changed and no live model calls were made. I did not rerun the numerical reproduction or the 342-test suite; the attempted local Python probe could not start because `python` was unavailable. Historical memory was used only for review continuity; the current brief, records, and inspected sources govern this proposal.


