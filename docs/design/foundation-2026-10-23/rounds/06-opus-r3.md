# AKOR foundation decisions, round 3: Opus 5.5 on Astra's consolidation

Date: 2026-10-23. Read: found_astra_r2.txt, and the code wherever a clause depends on it. No model calls, no repository
edits.

## 0. Position

I sign Astra's round-2 consolidation (clauses 1 to 12 and the table of steps) as the base text of the joint record,
with the amendments in section 3. All but one are clarifications or mechanisms that make a clause testable. The one
contested item is O3: what a CLI update does to qualification (A11).

Astra wrote its round 2 before reading mine. Its six named disagreements were already settled by my round 2, five of
them in Astra's direction and the sixth, late pure replies, in the conditional form Astra now writes:
1. Parser-limit relocation: I withdrew it (my r2, C4).
2. Content hashes as effect identities: withdrawn (C2).
3. Exact launch accounting: withdrawn (C3).
4. Buckets: replaced by measured sizes (C7).
5. Tool-free memo eligibility: settled by Astra's clause 4, which I sign.
6. Unconditional content fencing: settled by Astra's clause 3, which I sign as written.

## 1. Corrections I accept to my own earlier text

Astra's evidence qualifications are right. I withdraw these statements:

K1. "0 of 100 qualified replies were wire-invalid", the rule-of-three bound and the "at most 3 tokens per job" salvage
figure. The nine replies at 16 jobs were experimental (pilot-plan.md), and pooling them with the 91 published
qualified replies proves nothing about any one profile. No-salvage needs no economic argument: brief limit 5
forbids it.

K2. "Batch size changes model behavior" as a conclusion. Arm P was one-job plain JSON, not one-job OZ/1g. It
motivates testing small OZ packets and settles nothing about them.

K3. "Break-even within the first job" and a skill threshold of "default 4". Both are hypotheses, to be tested by M1 and
M14.

K4. L1 as a cost law. The joint record keeps the measured comparison from the brief's table. A fixed per-call cost of
about 1.8k tokens remains a hypothesis until its derivation is committed.

K5. My 2% reopen criterion for salvage. Under Astra's clause 2, a higher failure rate triggers diagnosis or withdrawal
of the profile, never salvage.

K6. My round-1 route profile carried the batch bucket inside the reuse key. Repacking would then have changed the key,
contradicting my own retry rule. Astra's separation of execution route from qualification cell (clause 1) fixes this.

K7. "Sum Codex `turn.completed` usage" was unqualified. The live runner takes the last such event
(bench/live/run_live.py:86), and whether those values are deltas or running totals is unverified. The decoder is
qualified first (clause 8).

K8. Rolling medians are not deadline-feasibility bounds (clause 7).

K9. A per-user quota file that processes only consult is not mutual exclusion (clause 7).

K10. A complete-looking capture file is not proof of completion, and redirecting the outer adapter's stdout does not
cover a nested CLI result the adapter buffers (clause 5).

## 2. Clause-by-clause verdict

| Astra r2 clause | Verdict | Amendment |
|---|---|---|
| 1 Identities (K_compute and K_accept, several candidates per key, route separate from qualification cell) | Sign | A1 defines "required provenance" and "pinned execution settings" |
| 2 Acceptance (shipped parser kept, `oz1g-selective-v1`, labels as summaries, verifier outage keeps the candidate, conservative drift containment, size limits kept in the parser) | Sign | A2 adds release rules for quarantined candidates. A3 clarifies how far a failure record reaches. |
| 3 Retries and late replies (logical-job recovery, conditional adoption of late pure candidates, intent identity for effects) | Sign as written | None. This settles O1. |
| 4 Memo (explicit eligibility; tool-free is not enough; revalidation instead of regeneration; failures not reused) | Sign as written | None |
| 5 Durability (uncertainty at the process boundary, six-step requirement, restated guarantee) | Sign | A4 adds a completion protocol. A5 sets the SQLite pragma explicitly. |
| 6 Graphs and migration (descriptor, one admission, additive migration, optional `host.map`) | Sign as written | None. This settles O5. |
| 7 Scheduling (explicit sharing authorization, aging and deadlines, tail bounds, durable mutual exclusion, wavefront as a hypothesis) | Sign | A6 states the starvation scope. A7 names the mutual-exclusion mechanism. A8 sets the sharing default. |
| 8 Accounting (modelUsage, no fallback to an exact total, schema conversion, Codex decoder qualified first) | Sign | A9 fixes the adapter |
| 9 Qualification (documented cells only, no padding, no silent unsupported sizes, status separate from evidence) | Sign | A10 defines parser identity. A11 handles CLI updates (open). A12 adds monitor thresholds. |
| 10 Integration (`oz do` default, one orchestration call as a target, refs in authorized scope, matched control) | Sign as written | None. This settles O2. |
| 11 Authority | Sign as written | None |
| 12 Lossless values (validated value bytes kept, numeric lexemes kept, parser rejections unchanged) | Sign as written | None. This settles O6; Astra's byte-level version is stronger than mine and replaces it. |
| Steps 3 to 6 | Sign | A13 adds a size gate to step 2 |
| Astra r1 D12 (evaluation) and D13 (governance), absent from r2 | Keep in the joint record | A14 |
| Presentation | Sign Astra's removal of laws, line counts and confidence claims from the normative text | A15 |

## 3. Amendments

**A1. Clause 1, computation manifest.**
1. "Required provenance" means provenance fields the operation declares as inputs. Other provenance (paths, digests of
   sources the worker never sees) is execution metadata kept with the dispatch, not key material. A tool-free worker
   cannot be affected by bytes it does not receive.
2. "Pinned execution settings" means the execution route: adapter identity, model id, effort, wire digest and CLI
   version.
3. Batch size and packet composition are not key material; this is clause 1's own separation of route and cell.

**A2. Clause 2, quarantined candidates.**
1. A quarantined candidate is accepted only if a job-bound check sufficient for its target later passes for that same
   candidate.
2. Otherwise its job is regenerated automatically within its remaining attempts, preferably with different siblings.
   The candidate stays as history, never enters memo and never releases dependents.
3. When no attempt remains, the job's outcome reads `quarantined` with the reason. It does not read as a failure
   claimed by the model.

This returns to the substance of my round-1 containment with Astra's wording, and supersedes my round-2 C1, which kept
siblings accepted. Correctness first is the deciding rule.

**A3. Clauses 2 and 3, failure records.**
1. A valid failure record decides its job within its run and for the run's coalesced followers (OZ9 6.2), and nothing
   beyond.
2. A late failure record may become the job's recorded outcome only when no execution of the job is in progress and no
   attempt remains. Otherwise clause 3's rule stands: it cannot cancel an authorized execution.

**A4. Clause 5, completion protocol.**
1. The runner publishes completion, not the coordinator. It writes the CLI envelope and its exit status to a temporary
   file, flushes it to disk, then renames it to `<receipt>.done`.
2. Only a `.done` file counts as a completed capture. Redirected stdout is a secondary capture for diagnosis only.
3. Process identity is the PID plus the process creation time; on Windows that time comes from `GetProcessTimes`
   through `ctypes`, which is standard library.
4. Fault tests kill the coordinator and the runner separately at each step: before the temporary write, after it,
   after the rename, and before the commit.
5. A runner killed while the nested CLI is still running yields launch uncertainty under clause 5's six steps, never a
   recovered reply.

**A5. Clause 5, SQLite.** Set `PRAGMA synchronous=FULL` explicitly. This Python build already defaults to FULL
(verified), but durability must not depend on how SQLite was compiled.

**A6. Clause 7, starvation.** Caller target priority keeps precedence (OZ9 5.1).
1. The bounded-wait claim applies only within one priority level, where aging orders jobs by age.
2. Across levels, a continuous higher-priority stream may delay lower levels, and status reports that wait as
   `priority_wait`.
3. The measured property is the maximum wait within a level under a declared load.

Astra's objection to my round-1 ordering is correct. This states the policy rather than overclaiming it.

**A7. Clause 7, quota mutual exclusion.**
1. Quota-group reservations live in a per-user SQLite database (standard library).
2. A dispatch reserves its slot in a `BEGIN IMMEDIATE` transaction and releases it in another.
3. A slot whose holder crashed is reclaimed under clause 5's uncertainty rules.
4. Rate-limit events with reset times are recorded in the same database.

**A8. Clause 7, sharing default.**
1. Runs do not share packets unless both requests declare the same sharing scope and every other compatibility
   condition holds.
2. The wavefront experiment declares one scope for its instances.

**A9. Clause 8, adapter fix.**
1. Remove the fallback to `usage` and the zero defaults in examples/claude_cli_adapter.py (lines 11 to 18 at
   fabbc8a). An absent `modelUsage`, or a model entry missing a required counter, yields unknown usage for that call,
   with the raw envelope kept.
2. Report `thinkingTokens` as the reasoning subset of output when present. All nine subagent-arm envelopes in the pilot
   carry nonzero values.
3. The adapter's `input_tokens` stays the sum of uncached, cache-read and cache-write input, as clause 8 notes. Any
   uncached column is derived by subtraction, never added back.

**A10. Clause 9, parser identity.**
1. Record a parser behavior version, the parser module digest and the digest of the fixture suite.
2. A module digest change without a version change is allowed only if every qualified fixture reproduces byte for byte.
3. A behavior change is a new parser version and therefore a new profile.

This lets a refactor of oz_reply.py proceed without requalification, while any behavior drift is caught.

**A11. Clause 9, CLI updates (O3, contested).**
1. A CLI version change moves every qualified cell to `continuity_pending`.
2. Production dispatch on a cell resumes only after a preregistered continuity smoke passes: 2 calls per cell, all
   wire-valid and oracle-correct.
3. A failure suspends the cell until full requalification.
4. Continuity evidence is recorded as such and never counts as qualifying a new cell.

Astra's clause 9 lists CLI configuration in the support scope, which read strictly means full requalification after
every update. The test that settles this is to run full requalification after the next two CLI updates. If wire validity
and oracle outcomes never move, the smoke rule suffices; if they move, Astra's reading stands.

**A12. Clause 9, monitor thresholds.** Each cell's preregistration declares the production thresholds that trigger
diagnosis or withdrawal: wire-valid rate, oracle correctness on held-out work, and binding-suspect replies. My earlier
"98% over 50 calls" is a candidate value for that declaration, not evidence.

**A13. Steps table, completing step 2.**
1. Add a preregistered size gate at 1, 4 and 16 jobs, alongside the 64-job repeat and the integration arm.
2. Reason: under clause 9, production `oz do` can otherwise dispatch only the documented cells (32 and 64 jobs on
   Sonnet, 64 on the others), and real fan-outs are often smaller.
3. Until the gate passes, the integration arm runs under an explicitly experimental profile, as clause 9 requires.

**A14. Governance and evaluation.** Carry Astra's round-1 D12 (evaluation and reporting) and D13 (additive build in the
signed order; reopen only on a failed test, a changed requirement or defeating evidence) into the joint record
unchanged. Add one sentence: savings claims use a cold memo unless labeled warm. Clause 10's test already counts the
calling agent's tokens.

**A15. Presentation.**
1. The normative text carries no laws, line counts or savings estimates. Costs appear as mechanisms or measured facts.
2. Code-size planning estimates, which the original task asked for, may go in an annex labeled as estimates.
3. A five-line principles preamble MAY state the design rules, each pointing to its clause:
   1. The job is the unit of identity, acceptance and retry; the packet is transport.
   2. The host decides acceptance and accounting.
   3. Model-visible bytes change only through qualification.
   4. Possible execution always has a durable record.
   5. Bulk data stays out of the calling agent's context.
4. The brief's pilot table replaces my L1.

## 4. O1 to O7 after Astra's round 2

| # | Question | Status | Where settled |
|---|---|---|---|
| O1 | Late pure replies | Agreed | Clause 3: adoption by the current coordinator under six conditions, plus A3 |
| O2 | Agent round trips | Agreed | Clause 10: `oz do` is the default, one call is a design target, with a matched control |
| O3 | CLI updates and qualification | Open | A11, with the test stated there |
| O4 | Contract in the reuse key | Agreed | Clause 1 (K_compute and K_accept) and clause 4 (revalidation) |
| O5 | `host.map` | Agreed | Clause 6: optional, fully defined before first use |
| O6 | Numeric lexemes | Agreed | Clause 12, Astra's byte-level version |
| O7 | Order | Agreed | Steps table: step 2 completes with the 64-job repeat and the integration arm; A13 proposes the size gate |

Also agreed since round 2:
1. Drift containment follows clause 2 plus A2.
2. Fairness follows clause 7 (aging, no service debt) plus A6. Astra dropped service debt in the same round I adopted
   it; I follow Astra's round 2.

## 5. Facts I verified for the joint record

Astra could not start Python, so these were checked here today against the code at fabbc8a:

| Fact | How it was checked |
|---|---|
| `Decimal('1e300') == 1e300` is False in CPython. So `oz_reply.loads` must stay float-based, and the lossless path of clause 12 must be a separate decoder. | Ran it |
| test_oz_reply.py:219 and :378 assert float equality, including 1e300 | Read the tests |
| `regroup` turns `{"len":12.50,"u":0.020}` into `{"len":12.5,"u":0.02}` | Ran it (round 1); Claude reproduced it independently |
| The adapter falls back to `usage` and defaults missing counters to 0 | examples/claude_cli_adapter.py:11-18 |
| Attempts are charged at lease | oz_runtime.py:343-348; pinned by test_oz_runtime.py:107 |
| Reply-level size limits are fixed by tests | test_oz_reply.py:221-230 |
| SQLite `PRAGMA synchronous` is 2 (FULL) in this build | Ran it |
| Pilot `modelUsage` envelopes carry `thinkingTokens` (9 of 9 subagent runs nonzero) | Read the raw rows |
| The Codex runner reads only the last `turn.completed` event | bench/live/run_live.py:86 |

## 6. Assembling the joint record

1. Use Astra's round 2 clauses 1 to 12 with amendments A1 to A12.
2. Add the steps table with A13.
3. Add Astra's round 1 D12 and D13 per A14.
4. Add the merged open questions, M1 to M14 from my round 2, with M14 and the skill threshold marked as hypotheses.
5. Add the compatibility table from my round 2 (section 7) as an annex. It answers the brief's second requirement.
6. Add one evidence statement: the brief's pilot table; 91 of 91 published qualified replies accepted; the 9 pilot
   replies at 16 jobs experimental and reported apart.
7. Only O3 remains open; record it with its test.
