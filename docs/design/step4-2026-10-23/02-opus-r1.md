# Step 4 plan: Opus 5.5 round 1 on Astra's `inspection-handoff-20/v1`

Read against: foundation README (step 4 row, clauses 4 to 7, 9, 13), rounds/00-brief.md, size-gates-plan.md and
results, caller-cost results, USAGE.md (`oz do`, selective profile), and the code at `ae1815d` (oz_runtime.py,
oz_worker.py, oz_do.py, oz_accept.py, examples/claude_cli_adapter.py, bench/live/live2.py, bench/live/run1g.py).
Nothing was run except `claude --version` (reports 2.1.306).

Short verdict: I accept the workflow as the step 4 executor gate, with eight changes. I do not think it is, on its
own, the "real workflow" the owner asked for, and I say so below rather than let the record imply it.

## 1. What I accept

1. The shape: snapshot, three dependent model stages of four jobs, host joins after each stage, a validation barrier
   (node 11), host rendering fan-out, independent verification, one durable publication effect. One target of
   weight 1; intermediate nodes earn nothing. This answers Astra's own brainstorm risk that twenty steps must not
   count as twenty useful jobs.
2. The three model operations are the standard materials instructions (`MAT_D` e, b, v in live2.py) on the four
   live2 records, byte for byte. The `m` operation moves to host node 16. That keeps the model inside measured
   territory, and it follows my brainstorm D3: a failure should point at the runtime, not at the oracle or the wire.
3. The expected values. I rechecked them: A 12.48 to 12.52 inside, B 12.44 to 12.50 outside, C 12.50 to 12.52
   inside, D unknown; missing fields A {method, basis}, D {uncertainty, basis}; corrected A 12.53 to 12.57 outside.
4. The five recorded cases (clean, exact repeat, interruption, stale input, revision bump with identical bytes) and
   the race fixture on the authoritative revision. Case 5 is exactly my Q11 (early cutoff) from the foundation
   rounds.
5. Route: Sonnet 5.5, default effort, `claude -p`, no tools, H unchanged, durable path, `oz1g-selective-v1`. No
   planner, no `host.map`, no importer, no cross-run batching. Recovery at sizes 4 and 1 only, never padded.
6. The accounting gap is real: examples/claude_cli_adapter.py lines 12 to 18 still fall back to last-turn `usage`
   when `modelUsage` is empty, against clause 8 and A9. Fixing it, and durably keeping the raw CLI envelope before
   the adapter reduces it, is a precondition for the gate.
7. The evaluator is a separate implementation that reads frozen sources and delivered bytes and never trusts the
   executor's `accepted` flags.
8. No token-saving claim against inline work, consistent with caller-cost results.
9. Budget order of magnitude: 11 expected calls, about 28.5k tokens estimated from the gate table (2,640 per size-4
   call, 2,385 per size-1 call), 60k cap, 16 launches, 5k admission reserve per launch, 3,600 s per scenario.

## 2. Is it "real" enough for the owner's criterion?

Partly. It is a real deliverable shape: a handoff with provenance, follow-ups, a host check of the package and a
durable local effect that must survive a crash. That is enough to judge what step 4 must prove (dependency
eligibility, freshness at commit, memo, effect reconciliation, interruption).

It is not real in one respect the owner will notice. Every model job here is work the host can do exactly: the
records are already `key=value;` text, bounds are `Decimal` arithmetic, classification is a comparison. The runtime
checks Astra proposes compute the answer key itself. OZ9.md says the model is for "work requiring interpretation or
generation" (line 250) and the planner instruction says "Prefer host operations for deterministic work". A real
author would not send these jobs to a model. So the workflow proves the executor moves model work correctly through
a dependent graph; it does not show that a real workflow needed the model.

There is a second, quieter limit. The model never consumes a predecessor's output. `bounds_X` and `classify_X` read
the same six-field record text as `extract_X` (node 6 must reproduce the source bytes exactly, because extraction is
checked by exact equality), so the stage edges are validation gates, not data flow. That is the price of staying in
the qualified packet format, and I accept it, but then model-to-model handoff (clause 12, `_handoffs`) is only
exercised by fixtures, and the record must say so.

My position: sign it as the step 4 **executor conformance gate**, name it that way, and put one question to the
owner (O1 below) on whether a model-necessary workflow must also be recorded before step 4 counts as done.

## 3. Changes I ask for, with evidence

### C1. Packet composition is not a gate sample: label it experimental

The Sonnet size-4 gate used `jobs('materials', 4)` in run1g.py, which is `e1, b1, m1, v1`: one record, four
operations, generated records per seed. Astra's packets are four records, one operation (`eA..eD`, `bA..bD`,
`vA..vD`) on the fixed live2 records. Clause 9 lists heterogeneity and workload as qualification dimensions that do
not transfer automatically. And `oz_do.CELLS` would label these calls `qualified_cell`, because it checks only the
declared model and size (oz_do.py lines 40 to 54 say so).

Change: the step 4 executor carries composition in the cell identity, and the frozen plan explicitly authorizes the
three size-4 stages as an experimental composition with oracle proof (clause 9: "Experimental work can have oracle
proof"). The live result then says nothing about qualification. Size-1 recovery stays qualified (the size-1 rerun
covered all four operations). If Astra prefers a qualified label, the alternative is a preregistered composition
gate of 10 size-4 calls, about 26k tokens estimated; I do not think step 4 needs it.

### C2. Route identity is too weak for memo; fix before any memo exists

`Worker._route` (oz_worker.py lines 385 to 390) takes the adapter identity from `__name__` or the class name, so
every stdio adapter is `StdioAdapter`. `oz do` passes `route={'model': req['model']}` only (oz_do.py line 344), so
effort and CLI version are null. The declared model is a label: the Claude adapter picks the model from `OZ_MODEL`,
not from the request. With a memo keyed on `compute_key` (oz_accept.py lines 194 to 200, which includes the route),
a fixture adapter's values and a live Sonnet call would share one key.

Change, all gate-critical:
1. Route identity = adapter argv plus a digest of the adapter script, model, effort, CLI version, wire, parser
   behavior version.
2. The actual model is read from the `modelUsage` keys of the captured envelope and must equal the declared model
   before any candidate is accepted; a mismatch rejects the call's candidates.
3. CLI version is read once per run and rechecked per dispatch (clause 9 already requires it on every dispatch
   record). The local CLI is 2.1.306 today; an auto-update during the night blocks the gate (O3), it does not void it
   silently.
4. Fixture and live runs use disjoint memo namespaces, and a test proves a fixture value cannot be a live hit.

### C3. Make the stale test decisive by its observables, not only its final output

A content-addressed key alone would already miss on a changed A, because each A job carries A's bytes. What only a
correct executor gets right is the timing: the mutation lands after node 11 has committed a checked view holding the
old A text. A naive executor dispatches `classify_A` from that view, or notices only at node 19 and restarts
everything. Both can still end with a correct package. So the pass criterion must include:
1. No packet dispatched after the mutation commit contains the old A record bytes.
2. Exactly two size-1 calls (`extract_A`, `bounds_A`, in that order) and one size-4 classification call, unless a
   recorded reply rejection explains an extra call.
3. `extract`/`bounds` for B, C, D are reused through a recorded decision that cites identical model-visible input
   bytes (node 6 recomputed, its B/C/D slices unchanged), not because the executor ignored node 6.
4. Old A acceptances remain in history, marked not current; the delivery manifest cites revision 2 only.

### C4. One authoritative source store, concretely

"Authoritative and transactional" needs a mechanism. Proposal: sources live in the run's SQLite as `(name,
revision, sha256, bytes)`; a host command bumps the revision in one transaction; every acceptance and the delivery
row commit conditionally on the revisions they cite (`WHERE revision = ?` in the same transaction). Files are
imported into the store at node 1; the file system is not the authority. This keeps the race fixture a single-DB
conditional commit, standard library only.

### C5. Free checks on the real artifacts

Several clause 4 tests cost nothing once the clean run exists, and they are stronger on live artifacts than on
fixtures. Add, all with zero model calls:
1. Byte identity: `handoff.json` and `handoff.md` from clean, exact repeat and interruption runs are identical
   (artifacts carry no timestamps or request IDs; the manifest does). Case 5 differs only in revision fields.
2. Route change: the exact repeat with a changed route field (for example declared effort) must produce 12 misses
   and stop before launch (plan-only mode), so the miss costs nothing.
3. Strengthened check: add one check to `bounds`; the 4 retained candidates revalidate on the host with no call.
4. Revocation: revoke one clean-run `bounds_B` candidate; the next plan shows exactly one miss, then stops before
   launch.

### C6. A zero-token dry gate before any paid call

The whole harness, all five scenarios, the kill hooks, the mutation hook and the evaluator run end to end with a
fixture adapter that returns oracle values, through the same entry point, in a separate namespace. Required
sabotage fixtures must fail it: a corrupted rendered value (node 19), an adapter that answers classify_A from old A
bytes, a replayed capture counted as a new call, and a fixture value offered to the live namespace. No paid call
until this passes. This is where most of step 4's bugs should surface, at no quota cost.

### C7. Interruption: hard kills at named boundaries, resumed by the same command

Kills are process exits at preregistered hooks (`os._exit` in the coordinator at the boundary, plus external
`TerminateProcess` in fixtures), never exceptions that run cleanup. Live kill points stay as Astra wrote: after the
first `.done` and before acceptance; after the publication manifest and before delivery commit. Resume is the same
CLI command with the same request identity; the record shows no DB edits between the two invocations. Expected live
launches stay 3. Runner death and uncertain execution stay in fixtures, because live uncertainty correctly ends in
a blocker, not a delivery.

### C8. The owner's criterion names a baseline; record one, small and separately capped

The 2026-10-12 build order says the executor is "judged against a recorded 20-step real workflow and the baseline".
Astra's plan has no baseline. Add a no-orchestration arm: one `claude -p` call, no tools, same model, given the four
records, revisions and goal, asked for `handoff.json` content; the same independent evaluator scores it (Markdown
excluded and stated). Runs: three clean calls and one on revision 2 (4 calls). Interruption and exact repeat are
reported analytically for the baseline (a killed call is lost; a repeat is a full call), not paid for.

Cost per baseline call is a hypothesis, 3k to 6k tokens; the first call measures it. Cap: 20k tokens, 5 launches,
separate from the executor's 60k/16. Report tokens per scenario and amortized over the five scenarios for both. My
expectation, stated now so nobody tunes toward it: the baseline will be cheaper on clean and stale runs; the
executor wins on repeat, case 5 and interruption. The metric order (correct work first) decides, not the token
table.

## 4. The plan I would sign

**Workflow.** `inspection-handoff-20/v1` as Astra wrote it, labeled "executor conformance gate", with C1 to C4.
Records parameterized by a record set (live2 records are set 0) so M9 can later run 16 instances on generated sets.

**What the executor must do to pass.** Astra's list, plus C2 and C4. Gate-critical (on the live path): graph
admission and persisted descriptors, dependency eligibility on current evidence, source store and conditional
commit, memo with namespace and route identity, durable launch and capture reuse, publication intent with
reconciliation, `modelUsage`-only accounting with the raw envelope retained, model verified from the envelope.
Fixture-only for this gate: the per-user quota reservation DB (nothing contends in a single-coordinator run),
verifier outage, authorization changes, independent-sample refusal, deadline expiry, cancellation, incomplete
accounting.

**Decisive tests.**
1. Interruption: two hard kills, zero repeated launches, one delivery, artifacts byte-identical to clean.
2. Stale dependency: the four observables of C3.
3. Memo: 12 hits and zero launches on exact repeat; zero launches on case 5; the C5 negative checks.

**Budget.** Executor: 11 expected launches, about 28.5k tokens estimated, cap 60k and 16 launches, 5k admission
reserve, 3,600 s per scenario, 300 s per call, four-hour envelope. Baseline: 4 launches, cap 20k and 5 launches.
One preregistered rerun of a scenario is allowed only when the failure is a recorded model reply failure with
correct executor behavior; it is paid from the same caps. Quota is observed, not inferred; insufficient quota is a
blocker.

**Gates, in order.**
1. G0 freeze: graph, operations, checks, both revisions' expected values, hooks, fault schedule, caps, adapter and
   evaluator digests, CLI version.
2. G1 build: full current suite (the 342 baseline and everything added since) plus the focused fault suite.
3. G2 dry: C6, zero tokens.
4. G3 live: five cases in Astra's order; each delivers an independently verified target before its deadline within
   caps; launch counts match expectations or are explained by recorded rejections; C3 and C5 observables hold;
   every call has complete `modelUsage` or the exact cost claim is withheld.
5. G4 baseline: C8.
6. Report per clause 13, including amortized tokens, and the conformance label.

An executor bug found in G3 means fix, refreeze and rerun all of G3; it is not patched in place.

## 5. Open

1. **O1 (owner).** Is a conformance workflow on host-reproducible model jobs enough for "real workflow", or must step
   4 also record a model-necessary one? The cheapest candidate already in the repo is the code domain in live2.py
   (`CODE_D` p: repair proposals, checked by the host actually running the frozen cases in an isolated copy). It is
   not size-gated at 4, so it would run experimental or need its own gate. I recommend recording it after G3 passes,
   not blocking step 4 on it, and saying so to the owner plainly.
2. **O2 (Astra).** C1: experimental label (my preference) or a 10-call composition gate.
3. **O3 (Astra).** C8: whether the baseline belongs in the step 4 record or in a separate M14-style note. I think the
   owner's wording puts it in step 4.
4. Build cost dominates. The live gate is about 30k to 50k tokens; one design round costs more. Tests and fixtures
   go to Sonnet or Haiku per the owner's delegation rule, with Opus reviewing.
