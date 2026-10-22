# AKOR foundation decisions, round 2: Opus 5.5 on Astra's record, and a joint draft

Date: 2026-10-23. Read: found_brief.md, Astra's round 1 (found_astra_r1.txt), my round 1, and the code again where a
compatibility claim depends on it. No model calls, no repository edits.

## 0. New facts, and an evidence audit of my round 1

1. The Claude adapter now sums `modelUsage` (commit fabbc8a; 342 tests green). My D8.1 is implemented.
2. The trailing-zero defect is reproduced independently: `regroup` stores 12.50 as 12.5. The fix is ours to decide
   (J12 below).
3. The brief's pilot table matches my round-1 table to the decimal. It adds two facts: per requested job, one call
   per job still costs about 10x OZ/1g, and in 162 single-call records CLI `usage` equals `modelUsage`; only
   multi-turn calls differ. A 64-job Sonnet repeat is running.
4. Evidence rule (brief, limit 7). My round 1 also used figures I derived from the raw pilot rows, not from the packs:
   a fixed cost of about 1.8k input tokens per call, about 50 input tokens per job on OZ/1g, 6.4k to 7.9k input tokens
   per subagent job, an orchestrator last turn of 20k to 49k tokens, the per-model split of unparseable and
   wrong one-job replies, and Opus spawning 17 subagents for 16 jobs. They are reproducible from
   `bench/live/data/pilot2_*.jsonl`, but nobody has committed the derivation. In the joint record each one either gets
   a committed script (about 30 lines added to `bench/live/pilot2_report.py`) or appears as a hypothesis with its test.
   I do not lean on any of them below.

## 1. Verdict

Astra's record and mine agree on the load-bearing parts:
1. Whole-reply wire validity stays atomic, with no salvage.
2. Each record in a valid reply is accepted on its own checks.
3. A logical job is the retry unit, and packets may be repacked.
4. SQLite is authoritative and JSONL is an export.
5. The four-field plan syntax stays, every author passes the same admission, and authority never comes from model
   text.
6. `modelUsage` is the source of tokens, and unknown usage is null.
7. The wire stays frozen, the CLI is the primary contract, MCP is deferred, and the planner comes after the manual
   executor.

Astra is better than my round 1 on six points: effect identity and resource overlap, ambiguous launches, verifier
outages, cross-record checks, an explicit evidence list, and the request, run and target split. I adopt all six.
I hold on two points where the difference is measurable: pure jobs fenced by generation rather than attempt, and one
agent round trip per fan-out. Five smaller items are still open (section 5).

## 2. What I adopt from Astra

| Astra r1 | Adopted as | Replaces in my r1 |
|---|---|---|
| D1: request, run and target as separate units; run keeps its ID across resume | J1 | My single "Request (run)" unit |
| D1: wire IDs opaque, host-assigned, stable for retries of one logical job | J1, with the spelling pinned by the qualified profile (my addition, because spelling is model-visible) | "Node ID when unique in the packet" |
| D2: four gates (origin and completion, wire, per-job, target); no candidate reaches gate 3 before gate 2 | J2 | My W, C, V description, kept as the vocabulary |
| D2: verifier unavailable, crashed or inconclusive leaves the candidate unaccepted with a blocker, not failed and not regenerated | J2 | Nothing; my r1 had a gap here |
| D2: per-job checks never depend on unaccepted siblings; cross-record requirements belong to one collection-valued job or a downstream aggregate check | J2 | My drift demotion of siblings (see C1) |
| D2: evidence names each check performed (schema, source binding, constraint, execution, oracle, review); no single `verified` flag | J2; my three scopes become a derived summary of that list | My scope as the primary record |
| D3: each dispatch persists the coordinator ownership epoch and each job's execution generation | J3 | Receipt and K only |
| D3: allocated `effect_id` stable across recovery; resource-overlap checks against uncertain mutations; idempotency keys passed to sinks that support them; no "fenced" claim for sinks without fencing | J3 | My content-addressed effect key, which missed different mutations on the same resource |
| D4: freshness classes (snapshot-bound, current-state, time-bounded under an explicit age policy, revoked) | J4 | My "no TTL by default" sentence |
| D4: ops needing fresh randomness or independent samples declare it or are not memoizable; a hit gets a new acceptance association and never counts as a new execution | J4 | Nothing; gaps in my r1 |
| D5: a crash between launch intent and confirmed process creation is ambiguous; keep the reservation and report it | J5 | My "prepared, not spawned: no attempt charged" row (see C3) |
| D5: acceptance history is immutable; staleness changes a usability projection, never history | J5 | My "mark stale" wording |
| D6: a persisted, inspectable compiled execution descriptor per node | J6 | My "checks belong to the op version" prose |
| D7: eligibility re-checked at dispatch; deterministic rotation with recorded service debt between runs; atomic reservation of the quota slot and each run's participation allowance; a result verified after the deadline does not count | J7 | My aging rule and my missing call-budget rule for shared packets |
| D8: the decoder proves the three input columns do not overlap; separate counters for dispatches, turns, spawns and participating jobs | J8 | Nothing; additions |
| D11 whole: execution policy for generated code, enforced controls reported, digests are not permissions | J11 | My D6.3 authority sentence |
| D12 whole: reporting list, separate per-requested and per-verified figures, acceptance time after checks, one variable at a time | J13 | My D8.8 |
| D13 whole: additive build in the signed order; the manual executor uses the planner's paths; reopen only on a failed test, a changed requirement or defeating evidence | J14 | Nothing; my r1 lacked a governance rule |
| Profile name `oz1g-selective-v1` beside the shipped atomic behavior kept as an immutable baseline | J2, J14 | My unnamed change to OZ9 3.3 |

## 3. Where I changed my mind

C1. **Drift containment.** I drop my D2.6.4, which demoted unverified siblings when one record failed an input-bound
check. It couples siblings' outcomes, and on qualified cells there is no measured correlated drift to justify that.
The Luna evidence is from an unqualified cell. Replacement: a source-binding failure rejects only its record, and the
reply is recorded as binding-suspect. Its other records keep their acceptance, carry the flag in their evidence, are
not reused across runs, and count toward the profile monitor (J9).

C2. **Effect identity.** I adopt Astra's allocated `effect_id` with resource-overlap blocking. A content key cannot
see two different patches to the same file while the first is uncertain. The intent digest stays, only to recognize a
re-issued identical mutation and attach it to the existing effect record.

C3. **When an attempt is charged.** I withdraw "charge at spawn". Today's code charges at lease
(oz_runtime.py:343-348), which is already the conservative choice Astra asks for and is covered by tests such as
`test_oz_runtime.py:107`. An ambiguous launch stays charged and flagged; I add no refund path.

C4. **Result size limit.** I withdraw my D2.4, which moved the 64 KB per-result check out of the parser. Its benefit is
rare, and the reply-level limits are pinned by tests (`test_oz_reply.py:221-230`). Size stays a reply-level rule, as
OZ9 3.1 says of capture limits.

C5. **Units.** Request, run and target become separate units, following Astra.

C6. **Wire IDs.** IDs are host-assigned and opaque in role: never parsed, never receipts, stable per logical job.
Their spelling is part of the qualified profile, because the qualified cells used IDs shaped like `ma_01`. A new
spelling is a profile change under J9.

C7. **Batch-size qualification.** I adopt Astra's measured points 1, 4, 16, 32 and 64 in place of my buckets. A size
between two qualified points is allowed only after one interior spot check passes. The brief forbids trading
correctness for tokens, which rules out interpolating on faith.

C8. **Fairness.** I adopt Astra's deterministic rotation with service debt in place of my aging rule. Both are about 20
lines; Astra's makes the debt auditable.

C9. **Evidence.** My derived pilot figures follow section 0.4.

C10. **Evidence list.** Acceptance evidence is the list of checks performed. `declared`, `checked` and `verified` are
derived labels for reports and target requirements.

C11. **Verifier outages** are blockers (Astra D2).

C12. **How to fix the trailing zeros.** I keep the decision and change the implementation. Changing `loads` to a decimal
type would break `test_oz_reply.py:219` and `:378`: they assert float equality with 1e300, and `Decimal('1e300') !=
1e300` in Python (checked). So validation keeps today's `loads`, and storage and handoffs use a separate exact
decoder (J12).

## 4. What I keep, with the argument Astra should test

H1. **Pure jobs are fenced by generation, not by attempt** (open, O1).

Astra's rule: a reply from a superseded attempt is quarantined. Take this sequence: attempt A of a pure job is late,
recovery B is dispatched, A arrives while B is in flight, then B's reply fails wire validation.

1. Under Astra's rule the job may end failed with a valid, checked answer sitting in quarantine. That loses requested
   work, which is metric 1, and wastes paid tokens, which is metric 2.
2. Under generation fencing, A commits because it answers the identical frozen question, and B's record becomes
   superseded.

What I propose:
1. A job's generation changes only when its frozen inputs, instruction, route or contract change. Astra's own D1 rule
   already says such a change "creates new work".
2. Commit is one transaction that requires the job to be unresolved and the record's generation to equal the current
   one. The first valid record of the current generation wins.
3. Later records are stored as superseded and counted. They never enter memo and never release dependents, which is
   Astra's protection, kept.
4. Effectful jobs keep strict attempt and epoch fencing.
5. On coordinator takeover, reconciliation adopts the captured replies of the previous epoch under the same rule.
   Astra's D5 resume already says "continue unfinished checks from captured candidates", which needs this.

If Astra sees a hazard in a pure late reply of the same generation, the falsification test is the sequence above,
run on both rules.

H2. **The reply capture file.** Adapter stdout goes to a per-receipt file, not only to a pipe, so a reply that finishes
after a coordinator crash survives and is settled on resume. This is how Astra's "durably capture response" step works
when the coordinator dies mid-call; today `StdioAdapter` reads pipes (oz_worker.py:54-96) and the paid reply is lost.

H3. **One agent round trip per fan-out** (open, O2). Astra's skill teaches create, submit, execute, inspect, consume.
Run as separate tool calls, that is five round trips, and every round trip re-reads the agent's whole context.

I propose `oz do`:
1. It composes those five steps for work bounded by the caller's tool timeout.
2. It reads the request from stdin, so one shell call carries it.
3. Refs may be file paths, so bulk inputs never enter the agent's context.
4. The multi-command loop stays for long or background work.

This adds a verb; it removes nothing from Astra's D10.

H4. **`host.map`** (open, O5). Fan-out over runtime data is a registered host op, not syntax and not a planner call. It
is built only when a workload needs it, for example the 20-step workflow. Without it, each data-dependent fan-out
costs a planner call or an orchestrator turn.

H5. **The reuse key excludes the contract** (likely agreed, O4). Astra's D1 already separates a job's logical identity
from its reuse key, and Astra's D4 test accepts "a miss or explicit revalidation".

1. The logical identity includes the contract and the host acceptance profile.
2. The reuse key covers only the computation.
3. A hit is usable only after revalidation under the current contract and profile.
4. A strengthened check then costs a re-check instead of a recomputation.

H6. **What crosses runs in the memo.** Valid job failures and binding-suspect results are never reused across runs.
One wrong `missing_data` must not become permanent.

H7. **Integration claims count the calling agent's tokens on both sides.** The pilot's subagent arm includes its
orchestrator; the OZ/1g and JSON arms had none.

H8. **Six laws as the record's preamble.** The owner asked for the physics. Each law carries only pack numbers or is
marked as a hypothesis (J0).

## 5. Open disagreements, each with the test that settles it

| # | Question | Astra r1 | Opus | Settled by |
|---|---|---|---|---|
| O1 | Can a late reply of the same generation complete an unresolved pure job? | No: quarantine anything from a superseded attempt | Yes, for pure jobs; never for effects | Fault injection: A late, B launched, A arrives while B is in flight, B fails wire validation. Count correct jobs lost and tokens under both rules. Separately, measure how often late replies occur on the real adapter. |
| O2 | How many agent round trips does one fan-out take? | Skill teaches a five-step loop | `oz do`: exactly one, refs by path | Arm K, in both variants (`oz do`, and the loop as separate tool calls) on the pilot's 16 jobs. Count tool round trips and tokens per verified job with orchestrator tokens included. |
| O3 | Does every CLI version change require full re-qualification? | CLI version is part of qualification identity | `oz doctor` plus 2 smoke calls per qualified cell; any wire-invalid reply or oracle miss suspends the cell until re-qualification | Rerun the qualification set after the next two CLI updates. If validity and oracle results never move, the smoke rule suffices; if they move, Astra's rule stands. |
| O4 | Do contract version and acceptance profile enter the reuse key? | Yes | No: they enter the logical identity, and hits are revalidated | Likely agreed through Astra's "miss or explicit revalidation". Test: a strengthened check the stored value passes must hit without a call; one it fails must miss. |
| O5 | Is `host.map` a foundation decision? | Not mentioned | Yes, built on need | Whether the 20-step workflow, or any committed workload, has data-dependent fan-out. If none does, the decision stays on paper. |
| O6 | Numbers: preserve the value or the lexeme? | "MUST NOT silently alter numeric values" | Preserve the lexeme for storage and handoffs | The J12 fixture. The domain argument: 12.50 mm states resolution, and OZ9 2.2 forbids text normalization. |
| O7 | Order: run arm K before step 3? | Keep the signed order; finish the pilot first | Arm K is the unrun "thin skill + CLI" half of step 2, so it belongs before step 3 | Not a disagreement about order if Astra accepts that step 2 is incomplete without it. |

## 6. Proposed joint record

Each item is marked **agreed** (both r1 records say it), **adopted** (one proposed it and the other accepts it in
round 2) or **open** (section 5).

**J0. Laws.**

L1 cost. Brief table, 16 jobs, tokens per verified job: OZ/1g 197 to 272, plain JSON in one call 233 to 301, one call
per job 2,793 to 3,737, one subagent per job 8,247 to 9,519. The order of levers follows from those numbers: remove
calls and subagents first, then reasoning, then compactness. The fixed cost per call is a hypothesis until its
derivation is committed.

L2 to L6 as in my round 1. L6 cites only the mechanism, that every turn re-reads the context, until the
orchestrator-turn figure is committed. **Adopted** if Astra agrees.

**J1. Units and identities.** **Agreed** core, **adopted** details.
1. Request, run, target, node, job, attempt, effect and result, as Astra's table defines them. Targets are fixed with
   the request, and resume keeps the run ID.
2. A job has a logical identity: node, generation, contract and acceptance profile.
3. A pure job also has a reuse key: the computation, over exact model-visible bytes plus route profile including the
   CLI version, or over the declared read set or snapshot plus environment for host jobs.
4. Excluded from the reuse key: run, node, wire ID, receipt, enqueue time, siblings, contract.
5. Wire IDs are host-assigned, opaque in role, unique per packet, stable per logical job, and spelled as the profile
   was qualified.
6. Inputs flow by value, so equal upstream bytes leave downstream keys unchanged.
7. Mutating commands take caller idempotency keys.

**J2. Acceptance, profile `oz1g-selective-v1`.** **Agreed** core, **adopted** details.
1. Astra's four gates.
2. A wire failure, wrong origin, incomplete capture or unconfirmed completion rejects the whole reply. Nothing is
   salvaged.
3. In a valid reply, each record passes or fails on its own pinned checks against host-resolved inputs.
4. A valid error record fails only its job.
5. A verifier outage leaves a blocker.
6. Cross-record requirements live in aggregate jobs.
7. Evidence lists each check performed, with derived labels `declared`, `checked` and `verified`.
8. Index drift is a per-record source-binding failure. Its reply is binding-suspect (C1).
9. The shipped atomic behavior stays as the immutable baseline profile `oz1g-atomic`. With no registered checks,
   `oz1g-selective-v1` must produce exactly the baseline's outcomes; that is its first test.

**J3. Retries and fencing.** **Agreed** core; generation fencing is **open** (O1).
1. Logical jobs retry and may be repacked with any compatible work. The operation, inputs, route and logical wire ID
   stay unchanged.
2. Repair with new evidence is a new job.
3. `max_attempts = 2` per job. Attempts are charged at lease, as today.
4. Each dispatch persists receipt, packet bytes, membership with generations, epoch, reservations and timeout.
5. Commit is one compare-and-set transaction.
6. Pure jobs: see O1.
7. Effects:
   1. Allocated `effect_id`, stable across recovery.
   2. Overlapping uncertain resources block new effects.
   3. Idempotency keys are passed to sinks that support them.
   4. An uncertain effect becomes `unknown_effect` and repeats only after reconciliation.
8. Guarantees: exactly once for request submission, graph installation and per-generation acceptance. At least once
   for dispatch and delivery. At most once for non-idempotent effects. Never exactly once for arbitrary commands.

**J4. Memo and freshness.** **Agreed** core; the key composition is **open** (O4).
1. Pure ops only, per authorized namespace (default: the workspace).
2. Entries keep the job-key manifest, artifact, provenance, check identities and verdicts, freshness class and
   authorization.
3. A hit needs, in order: key equality, current authorization, integrity, revalidation under the current contract and
   profile, and the freshness check.
4. A hit gets a new acceptance association and never counts as a new execution.
5. Revocation and staleness change the usability projection. Dependent targets stop counting as complete until
   delivered again.
6. Failures and binding-suspect results are not reused across runs.
7. Reports state memo state. Savings claims use a cold memo unless labeled warm.

**J5. Durable state and checkpoints.** **Agreed** core, **adopted** details.
1. SQLite (WAL, `synchronous=FULL` set explicitly) is authoritative. Artifacts are content-addressed and published
   before any reference to them. `calls.jsonl` is an export with today's `akor.call/1` schema, so the ledger tests
   keep passing.
2. Astra's seven-step durable sequence.
3. Adapter stdout goes to a per-receipt capture file (H2).
4. An ambiguous launch keeps its reservation and is reported.
5. Resume adopts captured replies under J3, preserves budgets and deadline, and rechecks usability before
   propagating old evidence.
6. Acceptance history is immutable.

**J6. Plan and graph.** **Agreed**.
1. OZ9 7.1 syntax unchanged.
2. Each node compiles to a persisted descriptor: registry pins, resolved inputs, required checks and scope, route,
   limits, effect capability and memo eligibility.
3. One admission for every author, in addition to OZ9 7.2:
   1. Profile availability.
   2. Target scope reachable by the registered checks.
   3. No overlap with uncertain effects.
   4. Configuration digests pinned at run start.
4. Replan limits from both records.
5. `host.map` is **open** (O5).
6. The planner only after the manual executor completes the 20-step workflow.

**J7. Scheduling.** **Agreed**, with Astra's fairness **adopted**.
1. Readiness from OZ9 5.1, re-checked at dispatch.
2. Compatibility: exact goal, qualified route and effort, isolation policy, and a data-sharing scope that covers the
   packet's whole ref union.
3. No ancestor and descendant in one packet.
4. Deterministic order: within a run, OZ9 5.1. Between runs, rotation with service debt; visible deadline overrides.
5. Atomic reservation of the quota slot and the participation allowances.
6. Packet sizes stay inside qualified intervals.
7. Deadline admission reserves verification time.
8. Rate-limit events are shared across the workspaces of one subscription.
9. The scheduler never changes meaning, checks, effort or route.

**J8. Accounting.** **Agreed**; the adapter part is done (fabbc8a).
1. Normalized columns, raw envelope and decoder version.
2. A proof that the input columns do not overlap.
3. T is counted once.
4. Unknown usage is null. Partial totals are lower bounds that never support an exact comparison.
5. Counters for dispatches, turns, spawns and participating jobs.
6. Shared-packet tokens are allocated for reporting only.
7. Integration claims count the calling agent's tokens (H7).
8. Quota is observed, never inferred.

**J9. Model boundary.** **Agreed** core; the CLI update rule is **open** (O3).
1. H, the packet grammar and oz1g-header are byte-identical.
2. Qualified profile identity:
   1. Wire and parser.
   2. Host acceptance profile.
   3. Adapter.
   4. Model id.
   5. Effort.
   6. Isolation controls.
   7. ID spelling.
   8. Qualified sizes (C7).
   9. Workload scope.
3. Qualification never transfers across these.
4. A profile monitor suspends a cell if any of these happens: its production wire-valid rate falls below 98% over 50
   calls, its oracle correctness on held-out work falls below the batched-JSON control, or its binding-suspect replies
   reach a threshold set in the qualification record. The first two thresholds are from my r1 and Astra has not ruled
   on them.
5. A wire change is a new profile with fixtures and preregistered paired qualification. Both wires coexist and there is
   no format detection.
6. Teaching once means amortizing op authoring, handlers, schemas and evidence. Each call is paid in full.

**J10. Integration.** **Agreed** core; `oz do` as the agent default is **open** (O2).
1. The CLI is the primary contract.
2. One Python service layer sits under both the CLI and the Python API.
3. Command schemas are versioned and mutating commands take idempotency keys.
4. MCP comes only for a client without a shell, or after a measured need. If built, it goes through the same service
   layer.

**J11. Authority and execution trust.** **Agreed**: Astra's D11 as written.

**J12. Lossless values.** **Open** (O6).
1. Validation keeps `oz_reply.loads` as it is, so the tests at `test_oz_reply.py:219` and `:378` stay green.
2. Storage, handoffs and reuse keys use a separate decoder that keeps each number's source text and writes it back
   unchanged.
3. Test: a fixture of trailing zeros, exponents and 20-digit integers comes out byte-identical after reply, store and
   dependent packet.
4. Non-finite values stay rejected by validation before storage.

**J13. Evaluation.** **Agreed**: Astra's D12 reporting list, plus memo state, orchestrator tokens and cold-memo
default.

**J14. Implementation boundary and governance.** **Agreed**: Astra's D13.
1. Additive build: the new profile and executor sit beside today's inbox path.
2. The legacy channel path becomes an importer only after it reproduces the existing fixtures.
3. Structural rules change only by versioned amendment. Parameters live in profiles.
4. A decision reopens only on a failed test, a changed requirement or evidence that defeats its rationale.

## 7. Compatibility with today's code and the 342 tests

| Change | Where it attaches | Why existing tests stay green |
|---|---|---|
| `oz1g-selective-v1` | One step after `regroup` and before `settle` (oz_worker.py:226-255) | With no registered checks it must equal today's outcomes, and that equality is a required test. The parser is untouched. |
| Generation and epoch columns, conditional commit | New columns; one new late-settle path beside `settle` | `settle` and `_check` keep their behavior for in-lease replies |
| Capture file, dispatch journal | Optional `capture_path` on `StdioAdapter`; new tables | The pipe default remains; `calls.jsonl` keeps schema `akor.call/1` and its write points |
| Exact number decoder | New function used by `regroup` storage and `_handoffs` | `loads` unchanged (C12) |
| Graph executor, registry, memo, `host.map`, `oz do` | New modules beside the inbox | Nothing existing changes until the importer reproduces the fixtures (J14) |
| modelUsage adapter | Done | 342 green after fabbc8a |

## 8. Joint open questions (merged and deduplicated)

Budgets are planning estimates, not evidence.

| # | Question | Measurement | Moves |
|---|---|---|---|
| M1 | Integration cost with the orchestrator counted | Arm K in both variants (O2) | J10, the skill |
| M2 | Which batch sizes hold on heterogeneous work? | Astra's sizes 1, 4, 16, 32, 64, plus interior spot checks | J9 profile sizes |
| M3 | Effort on OZ/1g | Incumbent against medium, then low, Haiku and Sonnet first, 5 paired trials | Route defaults |
| M4 | Value of selective acceptance | `oz1g-atomic` against `oz1g-selective-v1` on frozen semantic-error fixtures and live work | Whether J2 ships as default |
| M5 | Wire-invalid frequency under strict parsing | Ledger, per qualified cell | The no-salvage rule's reopen criterion |
| M6 | Source-binding check strength | Astra's permutation and swap fixtures; false acceptance and binding-suspect rate | J2.8, J9 monitor |
| M7 | Reuse key granularity and the CLI-version component | Astra's read-set comparison; rerun memoized jobs across a CLI update | J4, O3, O4 |
| M8 | Prefix caching against quota | Matched quota observations | Any layout change (a new profile) |
| M9 | Mixed-workflow scheduling and cross-run batching | Wavefront test: 16 instances of the 20-step workflow; per-run goal against a generic goal | J7 |
| M10 | Concurrency above 1 | Controlled trials with rate-limit observation | J7 defaults |
| M11 | Replanning value | Manual graph against one permitted replan on genuine blockers | Whether the planner is built |
| M12 | Crash ambiguity on Windows | Fault injection at every durable boundary (Astra) | J5 |
| M13 | Late-reply frequency, and loss under each fencing rule | Fault injection plus ledger counts | O1 |
| M14 | Inline answers against `oz do` | Same jobs, counting the remaining session turns' context re-reads | Skill threshold |
