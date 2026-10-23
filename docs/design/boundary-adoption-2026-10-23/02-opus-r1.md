# Adopting probe arm C: Opus 5.5 round 1

I agree with the shape of Astra's proposal: a new workflow revision, a fresh qualification of the changed operation
at sizes 4 and 1, then a fresh five-scenario suite under G3b's amended predicate, with first-attempt correctness of
every classification as the adoption condition. I keep these as written:

1. 20 nodes; each `classify_X` takes `/records/X` and `/bounds/X` from one current acceptance of node 11, record
   context retained.
2. A versioned classify operation and a versioned two-ref check, with Decimal recomputation of record to interval and
   of the label against the frozen goal limits; missing, mismatched or stale inputs block acceptance.
3. Goal, operation and both refs inside computation identity. (`ModelOp.identity` already hashes goal and
   instruction; the memo key must add both ref texts in order.)
4. Existing singleton qualification does not transfer; extract and bounds stay experimental compositions.
5. No memo reuse, retries, replacements or outcome-dependent extension; one call in flight; 5,000 reservation;
   300 s per call; pinned CLI 2.1.306, model, default effort, adapter, isolation, H and parser; `modelUsage` only.
6. Separate allocations without borrowing; workflow evaluation at 64,000 tokens, 24 launches, 10 per scenario.
7. The claim ceiling: the declared cells and the observed suite only; no reliability, savings, model-necessity or O1
   claim.
8. The author guidance, as guidance. Its evidence line should say where it comes from: one probe, one packet, six
   calls per arm.

What I checked in the code changes four things. Two of them block signature until settled, two are amendments to
the case table.

## 1. Blocking: O1's freeze pins the executor

`docs/design/o1-real-workflow-2026-10-23/plan-frozen.md` says the O1 freeze pins "the code (executor, adapter,
harness, worker, evaluator, predicate)", and any change needs `freeze --write`, a new G2 run and a new review before
G3c. The executor is `oz_flow.py`. The ordered-refs extension Astra describes edits `oz_flow.py` (today
`ModelOp.inputs` is `frozenset({'record'})`, `_run_stage` and `_plan` resolve only `bindings['record']`, and
`_stage_request` emits `'jobs': [[n, op.name, n]]`, one ref per job). Building it now would break O1's freeze while
another agent is building that gate.

**Rule:** no edit to `oz_flow.py`, `oz_do.py`, `oz_batch.py` or any other file O1's freeze pins until O1's live
gate has run and its results are committed, or until the owner and both designers decide to refreeze O1. The bench
pack, check, evaluator and qualification harness for this adoption may be drafted earlier in their own directory,
but nothing in it is frozen before the executor change lands.

## 2. Blocking: the packet bytes the workflow will send are not the bytes probe C sent

Probe C's packet (`bench/probe/boundary-evidence/calls/03-C/request.json`) has two properties the workflow path
does not reproduce today:

1. **Value form.** C sent each interval as a JSON array value, `["12.53 mm","12.57 mm"]`, and the unknown case as the
   string `"unknown"`. In the flow path a model input must resolve to nonblank text (`_run_stage`: "a model input must
   be nonblank text"), and `oz do` accepts a ref only as a string or `{"path"}`. Node 11 stores bounds as lists, so
   the natural implementation would send the interval as the JSON text `["12.48 mm","12.52 mm"]` inside a JSON
   string, double encoded. That is a different input from C.
2. **Layout.** C put records at refs 0 to 3 and intervals at 4 to 7, jobs `["classify_A",0,4]` and so on. The shipped
   packer assigns ref indices by first use in job order, so the workflow will most likely interleave record and
   interval refs. Changing the shipped packer to match C is out of scope.

Neither is necessarily harmful, but each is a change between the evidence and the adopted operation, on top of the
goal-referencing change. The proposal does not name them, so they would be settled by the build instead of by the
plan.

**Rule:**
1. Settle the value form before freeze. My preference is C's form, the interval as a JSON value, because it is the
   form with evidence; that extends `oz do`'s ref values, not only the dispatcher, and the plan must say so. I would
   also sign the text form (the compact JSON text of the checked interval as a string ref) if the plan names it as a
   deviation from C. Either way the decision is written down, not inherited.
2. Accept the shipped packer's layout; do not change the packer.
3. Generate every qualification request through the workflow's own planning and packing code, not by hand. The dry
   gate must show that the clean-scenario classify packet built by the executor under the fixture route has the same
   goal, op text, value form and layout rule as the qualification packets, and print one of each in the freeze
   record. Qualification then covers the bytes the workflow will send.

## 3. Operation text: change one thing

Probe C's text differs from Astra's goal-referencing text in two places: the L and U substitution, and the added
clause "without recomputing them from the record". The substitution is necessary; the clause is a second wording
change with no evidence behind it. I would freeze C's text with the substitution only:

```text
The first ref is the measurement record. The second ref is its host-checked interval: [lower,upper], or unknown. If the interval is unknown, return unknown. Otherwise use its endpoints directly. Let L and U be the lower and upper limits of the goal's acceptance interval, in mm. Return inside if lower >= L AND upper <= U; outside otherwise. Equality at either limit is inside.
```

Not blocking: if Astra keeps the clause, I sign, since the qualification tests the frozen text either way.

The goal string is part of the cell. Qualification goals use the workflow's exact goal sentence with only the two
numbers replaced. Store the limits once as structured data in `workflow.json` (lower, upper, unit, inclusive) and
test that the goal sentence, the check, `LOWER` and `UPPER` in `bench/step4/workflow.py`, `handoff_document` and the
independent evaluator all agree with it. Today those constants are hard-coded in three places.

A hypothesis for later, not for this gate: passing the goal limits as a host ref would apply the same "pass the
checked intermediate" idea to the goal. It would add a node and a third ref, so it is a separate design.

## 4. Case table: two amendments

Astra's eight cases at goal `[12.48,12.52]` give a strict interior of `[L+0.02,U-0.02]` = `[12.50,12.50]`, a record
with `uncertainty=0.00 mm`. That is a degenerate zero-width record, a different record shape from every one the
workflow sends, and not what "strict interior" is meant to test.

The table also has no disjoint outside case, yet the workflow's stale scenario sends exactly one: A rev 2,
`[12.53,12.57]`. As written, a passing qualification would not cover a member the adopted workflow sends. Spanning
both limits is the case the workflow never sends.

**Amendments:**
1. **Required.** Strict interior becomes `[L+0.01,U-0.01]`: `[12.49,12.51]`, `[10.01,10.07]`, `[12.47,12.53]`.
2. **Required.** Spanning both limits is replaced by disjoint above, `[U+0.01,U+0.05]`: `[12.53,12.57]` (the exact
   stale A), `[10.09,10.13]`, `[12.55,12.59]`. The quartets keep Astra's numbering.
3. **Preferred, not blocking.** Breaches by 0.01, one unit at the recorded precision, instead of 0.02:
   lower `[L-0.01,L+0.01]`, upper `[U-0.01,U+0.01]`. The observed failure was equality read as outside; explicit
   inclusive wording could push the opposite error, a near miss read as inside, and the tightest breach is the test
   for it.

Resulting table (every interval two decimals, every record consistent, records carry frozen n, method and basis with
some unknown fields, as the workflow's do):

| Case | Interval | Label |
|---|---|---|
| 1 Both limits equal | `[L,U]` | inside |
| 2 Lower equality | `[L,U-0.02]` | inside |
| 3 Upper equality | `[L+0.02,U]` | inside |
| 4 Strict interior | `[L+0.01,U-0.01]` | inside |
| 5 Lower breach | `[L-0.01,L+0.01]` (or Astra's 0.02) | outside |
| 6 Upper breach | `[U-0.01,U+0.01]` (or Astra's 0.02) | outside |
| 7 Disjoint above | `[U+0.01,U+0.05]` | outside |
| 8 Unknown | `unknown` | unknown |

Goal `[12.46,12.54]` keeps its value: its lower equality, upper equality and interior intervals are outside under
`[12.48,12.52]`, so a model that ignores the goal fails there. Quartets `(1,5,3,8)` and `(2,6,4,7)` each mix inside,
outside and, in the first, unknown. Job IDs use the workflow's form, `classify_A` to `classify_D` by position.

## 5. Execution order and the estimate

Astra freezes the order but does not state it. I would run the size-4 cell first (goal by goal, each quartet forward
then reversed), then the 24 singletons in a frozen permutation. The size-4 cell is the composition the workflow
mostly uses and the one the probe nominated; a failure there ends the attempt before about 60k tokens of singletons.

Estimate from measured numbers, for the record (the ceilings stay as proposed):

| Phase | Basis | Estimate | Ceiling |
|---|---|---:|---:|
| Size-4 cell, 12 calls | probe C: 2,720 to 2,873 tokens per call, mean 2,748 | about 33k | |
| Singleton cell, 24 calls | size gates: Sonnet 1 job 2,385 per call, plus a longer op and a second ref | about 60k | |
| Qualification total | | about 93k | 120,000 / 36 |
| Workflow suite | G3b live2: 31,346 for 12 launches including one classify resend | about 30k | 64,000 / 24 |

Paid exposure at the ceilings is 184,000 tokens, in addition to O1's 150,000. The owner should see both numbers
against the weekly quota before either live run.

## 6. Gate details to add

1. Both qualification cells also require route `ok` and complete accounting on every call; a route mismatch is
   terminal, as in the probe.
2. A failure in either cell ends this adoption attempt. A second attempt is a new preregistration, not a resume.
3. The independent evaluator and G3b's amended predicate (refreeze `d89ac55c`) are updated to the two-ref semantics in
   their own code, with no executor import; the read-only recheck of every stored candidate runs as in live2.
4. Dry fixtures add: an interval from a different record, an interval from an older node 11 generation, a goal whose
   limits disagree with the structured config, the value-form and layout check of section 2, and a memo miss when
   only the interval ref changes.
5. Report thinking tokens per call descriptively, as in the probe, and a descriptive table of classify-stage tokens
   against G3b live2 (primary call plus resends). No savings claim follows from it.
6. Cell scope in the result: Sonnet 5.5, CLI 2.1.306, default effort, this op text, this goal template with
   two-decimal mm limits, two-decimal intervals, the frozen value form and layout, sizes 4 and 1.

## 7. The plan I would sign

| Item | Value |
|---|---|
| Sequencing | After O1's live gate is committed, or after an agreed O1 refreeze. Nothing O1 pins is edited before then |
| Workflow | `inspection-handoff-20/v2`; 20 nodes; `classify_X` binds `record = /records/X`, `interval = /bounds/X` of node 11, ordered |
| Operation | `model.classify` version 2, text in section 3; check `mat_classify_interval@1` (new name, `mat_classify` left as is) |
| Goal limits | One structured source in `workflow.json`; goal sentence, check, constants, handoff document and evaluator tested against it |
| Packet bytes | Value form decided in the plan (my preference: JSON value as in C); shipped packer layout; qualification requests generated by the workflow's packing code |
| Qualification | Sonnet 5.5, sizes 4 and 1, goals `[12.48,12.52]`, `[10.00,10.08]`, `[12.46,12.54]`, eight cases per goal as in section 4; 12 size-4 calls first, then 24 singletons; every call wire-valid, entirely correct, on time, route ok, accounting complete; stop at the first failure |
| Workflow suite | After both cells pass: clean, repeat, both interruption points, stale A, identical-byte bump; G3b amended predicate and C5 checks; expected primary launches 3, 0, 3, 5, 0 after dry verification |
| Allocation | Qualification 120,000 tokens, 36 launches, four hours. Workflow 64,000, 24, 10 per scenario, 3,600 s per scenario, four hours. No borrowing |
| Adoption | Both cells pass, all five scenarios pass, every workflow classification right on its first attempt |
| Pre-run | Full regression suite green, Astra's dry tests plus section 6 item 4, freeze record with sample packets |
| Claim | The declared cells and the observed suite only. Extract and bounds unchanged. No reliability, savings, model-necessity or O1 claim |

## 8. Points in dispute

1. **Sequencing against O1's freeze** (section 1). Blocking.
2. **Packet value form and layout are unnamed** (section 2). Blocking until the plan names them; I sign either value
   form once named.
3. **Degenerate interior and the missing disjoint case** (section 4, amendments 1 and 2). Blocking, because the second
   leaves a workflow member outside the qualified families.
4. **The extra clause in the op text** and **0.01 breaches**. Preferences; I sign without them.
