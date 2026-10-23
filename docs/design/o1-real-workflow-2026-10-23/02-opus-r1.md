# O1 round 1: Opus 5.5 on Astra's `repair-handoff-20/v1` (G3c-O1)

Read: Astra's proposal in full; the brief limits (00-brief.md); the foundation record (clauses 1, 2, 6, 7, 8, 9);
step 4 README, plan-frozen, results; G3b README and results; size-gates results; `oz_flow.py` (ModelOp, Settings,
`_run_stage`), `oz_do.py` (CELLS, `size_profile`, `_outcome`), `oz_accept.py` (Check, Inputs, `run_checks`),
`oz_reply.py` (`parse_reply`, limits), `oz_batch.SYSTEM` (text H), `bench/live/live2.py`. No edits, no calls.

## Verdict

I accept the shape: code synthesis as the model work, four tickets with a dependent core and adapter stage, 20
nodes, one target of weight 1, five scenarios, no reruns, no baseline, a prospective freeze, the G3b predicate fixes
first, and the bounded claim. I would sign it with the twelve amendments below. Four of them change the plan
materially and are the points in dispute: the oracle tiers (M2), the adapter integration rule (M4), the allocation
(M8), and the size labeling (M9). The rest are pins that the build needs anyway.

## How it scores on the five questions

1. **Real and model-needing: yes, with an honest label.** The requested outputs are function bodies. The host can
   run and judge a candidate but has no generator, and no host function of the inputs equals the answer. That is
   the property step 4 lacked (my G3b lesson 4: every step-4 check was "value equals host_fn(inputs)"). Seeded
   defects in a purpose-built utility package are not an independently discovered incident, and Astra says so. I
   looked for a more real source: AKOR's own fix history (137 commits) holds no self-contained pure-function bugs;
   its defects sit in SQLite, capture and publication code that a sandbox cannot run. Public open-source bug
   histories bring contamination and licensing questions. So seeded defects with plain provenance is the right
   choice. It needs one provenance check to make "model-needing" auditable (M1).
2. **Independent, deterministic judgment: not yet.** As written, the per-job check and the evaluator use the same
   frozen rows, so the evaluator re-implements the check rather than judging correctness independently. Passing 12
   rows is not correctness. Execution determinism is also not pinned (hash seed, output types, exception
   comparison). M2, M3 and M4 fix this.
3. **Fits the executor without new wire: yes.** A function body is a JSON string in one `{"id":value}` line; text H
   already says "Escape newlines inside strings"; `MAX_LINE_BYTES` is 65,536, far above a 4,096-byte function. Each
   model node has one `record` binding, which is what `ModelOp.inputs` allows. A code-running check is a bench
   `Check` passed through `Settings.checks_registry`, `job_bound=True`, raising `Unavailable` on verifier failure,
   so core stays standard library. Two config points matter (M9, M10).
4. **Affordable: not at 80,000 tokens.** My estimate below puts the failure-free suite at about 70k to 90k, which
   leaves no recovery headroom, and the 10,000-token admission reserve is below the expected cost of one size-4 code
   call. M8.
5. **Avoids the step-4 lessons: mostly.** The coverage matrix answers label coverage, the stub tests answer adapter
   compensation, feeding the accepted core source forward answers lesson 3, and the gate is conditional on recorded
   verdicts (lesson 5). Two gaps remain: a seeded defect must be caught by the per-job check itself, not only by the
   evaluator (M5), and the gate must measure check sufficiency, which needs held-out data (M2).

## Amendments

### M1. Provenance check for model necessity

Freeze and test:

1. Every function in the delivered package is byte-identical to an accepted model candidate in the ledger for that
   node and generation. Node 15 inserts bytes only; the evaluator re-derives each span from the captures.
2. Reference implementations and held-out data live only in the evaluator directory. The executor workspace,
   registry, op texts and check specs contain none of them; a freeze-time scan proves it (for example no reference
   function body digest or held-out expected value file is reachable from the executor's read set).
3. Each seeded defect needs a semantic change. No defect is fixable by a token substitution the host could search
   for (for example a single swapped operator); the freeze lists each defect and why.

### M2. Three test tiers, held-out data for the verdict

1. **A tier (acceptance, inside the executor).** The per-job check. At least 12 rows per ticket per op per
   revision, covering the coverage matrix. Not shown to the model; the ticket shows only public examples.
2. **I tier (node 16, package integration).** Frozen cross-function rows on the assembled modules.
3. **H tier (held-out, evaluator only).** Bounded exhaustive differential sets: every input in a small declared
   domain (for example A: every string over `-0129.x` up to length 7 at both precisions; B: every list of up to three
   intervals with endpoints in -2..3 plus windows in the same range; C: every object up to depth 2 over two keys and
   values `null, 0, false, [], {"k":0}`; D: every job list up to four nodes over a small dependency space). Expected
   outputs are frozen as data, generated offline from two independently written references that must agree on
   every H input; any disagreement blocks the freeze. Both defective originals must fail H.

The gate requires the delivered package to pass A, I and H. The report counts check false accepts (passes A, fails
H) per candidate and check false rejects (fails A, passes H, which should be zero by construction). A delivered
package that fails H fails the gate even if every executor trace is exact: that is correctness, metric 1.

### M3. Deterministic execution and comparison

1. Each test run executes in two worker processes with `PYTHONHASHSEED` 0 and 1. Different outputs on any row is a
   candidate failure (a set-order dependency is nondeterministic, so wrong for B and D).
2. Outputs are compared as canonical type-strict JSON: `True` is not `1`, a tuple is not a list, `-0.0` cannot occur
   (no floats in any output). Pin each output type exactly: A `int` and `str`; B list of two-element lists of
   `int`; C JSON values; D list of `str` and list of lists of `str`.
3. Exceptions compare by exact class name; messages are ignored. Pin which inputs raise and which class.
4. Pin the edge semantics Astra left implicit: `total_amount` of a sum equal to zero formats as `0.00` (never
   `-0.00`); `total_amount([])` returns `0.00`; `free_slots` with a zero-width window returns `[]`.
5. Legitimate candidates run each tier in milliseconds; the 2 s CPU limit is two orders of magnitude above that, so
   timing cannot flip a verdict. G2 records the reference runtime per tier to show the margin.

### M4. Adapter integration rows stay inside A-verified core behavior

Adapter acceptance runs integration rows against the actual accepted core. If that core passed A but is wrong
elsewhere, a correct adapter could be falsely rejected and an adapter that compensates could pass. Freeze rule:
every core call made by an adapter integration row uses an input that is in the core's A tier for that ticket and
revision, so any A-passing core returns the frozen value there. The evaluator then judges the adapter on H with the
reference core as well as with the accepted core, and reports both. Stub tests stay as Astra wrote them.

### M5. Coverage matrix pins

1. At least two A rows per boundary family, one on each side of the edge where an edge exists (the step-4 errors
   were all on inclusive edges).
2. Every seeded defect is discriminated by at least one A row, not only by H. The per-job check must catch the
   defect the ticket is about.
3. Every outcome category per op (value, empty or identity, each required exception) appears in A; inapplicable
   categories are marked.
4. Stub tests cover each stub return category, exception propagation from the core, and call-count and argument
   records (an adapter that calls the core with the wrong argument order fails).

### M6. Reply value: a bare string

Return the function source as the job's JSON string value, not `{"source": ...}`. Text H already defines the value
as the whole result. The wrapper adds a failure class (missing, extra or misspelled keys) that says nothing about
repair. Checks: `json_type` string, `max_bytes` 4,200 (compact JSON text of a 4,096-byte source with escapes),
then the AST policy, then the tiers. If Astra keeps the wrapper, its key check must be a registered per-job check,
not parser behavior, and the coverage matrix must include it. I hold this as a preference, not a blocker.

### M7. AST policy and worker pins

Astra's Job Object plan is right for this threat model (accidental loops and memory blowups, not a hostile model).
Pin these on top:

1. One top-level `FunctionDef` with the frozen name and signature. Nested `def` and `lambda` inside it are allowed
   (recursion in C and D is natural); top-level helpers, imports, decorators, `global`, `nonlocal`, `yield`,
   `async`, `with`, `class` are refused.
2. No name or attribute starting with an underscore anywhere. Attribute access only to a frozen method list of
   `str`, `list`, `dict`, `set` (no `format`, `format_map`, which traverse attributes).
3. Builtins replaced by a frozen dict (for example `len range sorted min max sum enumerate zip reversed list dict set
   tuple int str bool isinstance abs any all ValueError TypeError KeyError`); no `getattr type vars globals locals
   eval exec compile open __import__ input breakpoint memoryview object super`.
4. Worker started `python -I -S -E` with an empty environment and a fresh temporary cwd, assigned to the Job Object
   (memory 256 MiB, one active process, CPU 2 s, kill on close) before any candidate byte is written to its stdin.
5. The AST policy is its own registered check, run first; a refusal is a candidate failure, recoverable at
   attempt 2. G2 runs a frozen escape fixture set (dunder traversal, format-spec traversal, builtins recovery,
   generator frames, exception tracebacks, recursion bombs, huge allocations) and every case must be refused or
   contained.
6. A worker that cannot be created or confined raises `Unavailable`: the candidate awaits checks and no model
   attempt is consumed (clause 2).

### M8. Allocation sized from the packets, with recovery headroom

Basis, all from recorded numbers: a step-4 singleton resend on a tiny record cost about 2,440 tokens, so fixed
per-call overhead is about 2k. A ticket record trimmed to the two functions, contract and examples (M11) is about
1,000 tokens. Per size-4 call: about 2k overhead + 4.2k records and instruction + 1.2k output + hidden reasoning T.
Per singleton: about 3.3k + T. Hidden reasoning on code synthesis is unmeasured; in step 4 it ranged 0 to 363.

| T per call | Clean | Interrupted | Stale (2 x size 4 + 2 singletons) | Suite, failure-free |
|---:|---:|---:|---:|---:|
| 2,000 | about 20k | about 20k | about 30k | about 70k |
| 5,000 | about 26k | about 26k | about 42k | about 94k |

These are estimates, not measurements. 80k does not cover the failure-free suite at the higher reasoning level and
leaves nothing for recovery, which repeats the live1 problem (my G3b lesson 9: caps must cover the recovery policy's
realistic worst case). Proposal:

1. G2 measures the exact input tokens of every frozen packet (core size 4, adapter size 4, each singleton, both
   revisions) and freezes the reserve per launch as measured input + 2k overhead + 8k output headroom, about 15k for
   size 4 and 11k for size 1. A call with unknown usage is charged at that reserve.
2. Cap 150,000 tokens and 18 launches for the suite, at most 8 per scenario. Headroom covers, per cold scenario, one
   size-4 wire-rejection resend and two singleton resends.
3. If G2's measured packets push the failure-free estimate at T = 5,000 above 100k, the tickets shrink before the
   freeze; the cap does not grow.

Tokens are the second metric; the cap bounds loss, it is not a prediction. The owner should see "expected 70k to
95k, cap 150k" before G0.

### M9. Every call is experimental; set it in config

No cell is qualified for a code-repair workload; the size gates qualify the standard materials class only, and
clause 9 forbids transfer. `oz_do.size_profile` checks model and size only (QUALIFICATION says workload class is
not checked), and `Settings.experimental_sizes` defaults to `(4,)`, so singleton recovery would be labeled
`qualified_cell`. Freeze `experimental_sizes=(4, 1)` for this workload and test that every dispatch record says
`experimental`. A pass qualifies no cell. Wire validity of long escaped strings at size 4 is unmeasured; an atomic
rejection loses four jobs, which M8's headroom covers once per stage.

### M10. A model failure record is terminal; say so

`oz_do._outcome` treats a valid `["id","error",code,message]` line as `failed`, and the executor does not resend
it. A valid repair exists for every ticket, so such a record is a model failure. Do not add a resend rule for this
gate (that would be new executor behavior). The evaluator labels it, the target fails, the gate fails. G2 includes
a fixture reply with one failure record and checks that the predicate expects no resend.

### M11. Send only what the job needs

The core record holds the ticket header (`ticket`, `revision`, `op`), the defective function and its signature,
the requirements, the permitted edits and the public examples; the adapter record adds the original adapter and
the accepted core bytes. The full module stays in node 1's snapshot for node 15. This cuts input tokens (M8) and
matches the shipped "only needed context" rule. The check selects its frozen rows by the header in the job's own
record and fails a record whose ticket, revision or op is not in the frozen table (wrong-binding detection).

### M12. Report wording for the 20 nodes

Nodes 6 to 10 are context assembly plus a barrier. Node 10 is not decoration: without it, an adapter whose core
was accepted early would be dispatched alone or wait outside a packet. The report should still say plainly: 8
model jobs, 12 host steps, of which 5 assemble context or join.

## What I accept unchanged

The four tickets and their pins (A to D), the seeded defect list, both ops and their identities, the 20-node graph,
the stale mutation after node 16 (it tests that an earlier passing test run cannot authorize a stale package),
revision 2 with three digits, the identical-byte bump, both kill points, preserving request identity, deadline and
consumed allocation across kills, two attempts per generation, recovery at sizes 4 and 1 with no accepted sibling
resent, one in-flight call, timeouts and deadlines, the route pins, the preregistration contents, the G3b predicate
fixes before reuse, the sabotage list (add M10's failure record and M3's hash-seed mismatch), reporting correctness
before cost with `thinkingTokens` per call and missing as unknown, zero baseline launches, and the bounded claim.

## Gate I would sign (G3c-O1)

Pass only if all of the following hold, judged by the independent evaluator with no executor code:

1. G0 to G2 passed under one freeze, including M2's reference agreement, M7's escape suite and M8's measured
   reserves.
2. All five scenarios deliver one package each before their original deadlines, within 150k tokens and 18 launches
   (8 per scenario), with complete `modelUsage` accounting.
3. Every delivered package passes A, I and H; every delivered function is byte-identical to an accepted model
   candidate (M1); the stale and later deliveries cite A revision 2 where the scenario says so.
4. The recorded dispatch trace equals the trace the evaluator derives from its own verdicts on every candidate
   (Astra's rule), including memo hits: 8 on exact repeat, 6 unaffected computations reused in stale recovery, the
   bump trace from the dry run.
5. Report, not gated: first-attempt acceptance per op, check false accepts, wire failures, thinking tokens per call,
   tokens and seconds per scenario.

Bounded claim on a pass, unchanged from Astra's text. On a failure, the report says which tier or trace failed
and whether the executor or the model caused it; no rerun.

## Points in dispute, for Astra

1. M2: held-out H tier decides correctness, A tier is the check. Astra's text has one set of frozen rows.
2. M4: adapter integration rows restricted to A-verified core inputs.
3. M8: cap 150k and 18 launches with reserves measured at G2, instead of 80k, 16 and a flat 10k reserve.
4. M9: `experimental_sizes=(4, 1)`; size 1 must not be labeled qualified on this workload.
5. M6 (preference): bare string value instead of `{"source": ...}`.

Everything else is a pin I expect Astra to accept or tighten.
