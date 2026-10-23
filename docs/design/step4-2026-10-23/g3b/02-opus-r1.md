# Step 4 G3 failure: Opus 5.5 round 1 proposal

Short answer. Live1 stays failed; nothing about it is rescored. Rerunning the same freeze with fresh tokens would be a
lottery, not a fix: the failure is decided by whether Sonnet chooses to think on one packet, and it chose not to on 2
of 3. G3 conflated two claims, executor conformance and model accuracy on an unqualified composition. I propose a new
preregistration, `inspection-handoff-20/v1` workflow unchanged byte for byte, with a gate G3b that predicts the
executor's dispatch trace exactly *conditional on the recorded per-member check verdicts*, a counter unit that matches
the frozen recovery policy, a budget sized for that policy's realistic worst case, and no rerun clause. Model
reliability on the size-4 classify composition is reported as a measured rate, and optionally probed separately. The
lessons for the language are about hidden reasoning, qualification coverage, feeding checked intermediates forward,
and host-computable ops.

## 1. What the evidence says (checked myself, from the retained envelopes)

### 1.1 Correctness tracks hidden thinking, not wording

Every classify call in live1, from `.oz-runtime/step4-live1/do/*/captures/*.envelope`, `modelUsage.thinkingTokens`:

| Call | Prompt sha256 | Members | Thinking | Output | Edge cases right |
|---|---|---:|---:|---:|---|
| clean classify | `33ffc1fc` | 4 | 79 | 140 | 2 of 2 |
| interrupt classify | `33ffc1fc` (byte-identical to clean) | 4 | 0 | 61 | 0 of 2 |
| stale classify | `48ecc5b0` (A is rev 2) | 4 | 0 | 61 | 0 of 1 (C) |
| interrupt resend A | `0eda850a` | 1 | 51 | 72 | 1 of 1 |
| interrupt resend C | `dfa9a565` | 1 | 58 | 79 | 1 of 1 |
| stale resend C | `dfa9a565` | 1 | 62 | 83 | 1 of 1 |
| baseline b1 to b4 | four frozen prompts | whole package | 266 to 363 | 1,228 to 1,341 | all |

Facts:
0. `results.md` says the three resends cost "about 4.8k". That is interrupt's two resends (12,860 minus 8,049). All
   three singleton resends total 7,341 tokens by `modelUsage` (2,440, 2,448, 2,453). Worth correcting in the record.
1. Clean and interrupt sent the same system bytes (`d941a86d`) and the same prompt bytes (`33ffc1fc`). One reply
   thought for 79 tokens and was right; the other thought for 0 and answered `outside` for both inclusive edges.
   This is not an executor fault and not a wording difference. It is sampling of adaptive thinking at default effort.
2. Every wrong answer had 0 thinking. Every right answer on an edge case had thinking above 0.
3. The goal already says "inclusive". The information is in the packet; without reasoning the model applies a strict
   comparison. A "boundary wording fix" would change model-visible text on a hypothesis the data does not support.
4. The extract and bounds packets ran with 0 thinking and were always right. Copying fields and doing one subtraction
   are easy without reasoning; a two-sided inclusive comparison at the edge is not.

### 1.2 The failing packets were the unqualified composition

C1 labeled the homogeneous size-4 stages (four records, one op) experimental. The qualified Sonnet size-4 cell
(`bench/live/data/gate_sonnet_4.jsonl`) is one record with ops e, b, m, v in one reply: the model writes the bounds
line before the classify line, so the interval is in its own output when it classifies. The step 4 DAG splits those
across a validation barrier, and `classify_*` reads `checked_intervals /records/X`, the raw record, not
`/bounds/X`. The checked interval exists on the host and is not passed on. The model is asked to redo arithmetic the
host has already verified, with no scratch.

The size-1 resends used the qualified size-1 cell and were right 3 of 3.

### 1.3 The pilots could not have seen this

The brief's fact is true but blind. I recomputed the records from `live11.make_records` for every pilot reply:

| Pilot (Sonnet, OZ/1g) | Classify jobs | inside, inclusive edge | inside, interior | outside | unknown | wrong |
|---|---:|---:|---:|---:|---:|---:|
| 16 jobs, arm H, 3 seeds | 12 | 2 | 0 | 8 | 2 | 0 |
| 64 jobs, arm H, 3 seeds | 48 | **0** | 0 | 35 | 13 | 0 |
| 16 jobs, arm Q (one call per job) | 12 | 2 | 0 | 8 | 2 | 0 |

At 64 jobs there was not a single `inside` case. A classifier that always answers `outside` unless uncertainty is
unknown would have scored 100%. The generator makes `inside` 4 of 84 outcomes (4.8%), and 3 of those 4 are inclusive
edges. The step 4 records, frozen from `live2.MAT_C`, are 2 of 4 inclusive edges (50%). The pilots measured cost and
format compliance; they never measured the classifier's hard branch.

A scan of every OZ/1g reply in `bench/live/data/` that carries the record's extraction and its classification in the
same reply finds 25 Sonnet edge-inside cases (live21: 9, live22: 13, live24: 1, pilot2: 2), 0 wrong, and none with
0 thinking. So the historical record has no counterexample to "edge cases need some thinking", and no case of the
step 4 setting (classify alone, no bounds in the reply). This is consistent with the hypothesis; it does not prove it.

### 1.4 The preregistration had two defects that the record should state

These do not change live1's verdict. They are why the gate measured the wrong thing, and v2 must fix them.

1. **Two labels, no binding.** `plan-frozen.md` defines `pass` and `pass_with_recorded_rejections` but never says
   which one G3 requires. The frozen code (`step4.py` line 789) requires strict `pass` for every scenario. The code
   is the frozen authority, so live1 fails. The plan text should have said so.
2. **Counter unit does not match the recovery policy.** `reply_rejections` counts dispatches that left any member
   pending. The frozen policy allows packets of 4 or 1 only, so one reply with k rejected members costs k singleton
   launches. Interrupt had 1 rejecting dispatch and 2 rejected members, hence 2 extra launches, hence
   `pass_with_recorded_rejections: false`. Stale had 1 and 1, hence `true`.
3. **C3 observable stricter than its source.** My round 1 C3 item 2 said "unless a recorded reply rejection explains
   an extra call". The frozen text dropped that clause and `singletons_then_classify` requires the exact list, so the
   stale observable failed on the classify_C resend while every other C3 check passed (no old A bytes after the
   mutation, B/C/D reused on identical inputs, A history kept, delivery cites rev 2). The freeze review did not catch
   the divergence.
4. `results.md` says both scenarios failed "the gate". Accurate for strict `pass`. It should add, as a factual note:
   stale satisfied `pass_with_recorded_rejections` and failed the C3 order observable; interrupt failed both because
   of the counter unit. No verdict changes.

### 1.5 Why "same freeze, new allocation" is a lottery

G3 needs three uncached size-4 classify packets (clean, interrupt, stale) to be fully right. Observed: 1 of 3 right.
Treating that as a rate (n = 3, a hypothesis, not a measurement), P(all three right) is about (1/3)^3, under 4%. Even
at a generous 70% per packet it is 34%. A pass obtained that way would say nothing new about the executor, and
choosing to rerun until it passes is the forking-paths problem the evidence rule exists to prevent.

## 2. Proposal: preregister G3b, run it fresh

### 2.1 What stays fixed

Workflow, graph, op texts and goal (frozen from `bench/live/live2.py`), records, expected values, route (Sonnet 5.5,
default effort, `claude -p`, no tools, unchanged H, `oz1g-selective-v1`), packet sizes 4 and 1, `max_attempts` 2,
scenarios and hooks, C5 checks, evaluator, baseline arm. No wire change, so no new qualification. Keeping op text and
composition byte-identical is deliberate: the run then measures the executor on the same model behavior that failed,
instead of engineering the model task until the gate passes.

### 2.2 What changes: the gate predicate

**G3b per scenario, all required:**
1. Delivered before the deadline, one delivery, evaluator passes on the delivered bytes, ledger has exactly one call
   per launch, accounting complete.
2. **Conditional exact trace.** An independent pure function in the evaluator (not oz_flow code, so the executor does
   not judge itself) takes the recorded per-member verdicts of each dispatch (check pass, check fail, wire
   rejection) and returns the dispatch sequence the frozen policy must produce: the base packets of the table, and
   after any packet with rejected set R, exactly |R| size-1 packets, one per rejected member, in job order, attempt
   2, before the next stage. The actual sequence of (members, attempt) must equal it. Memo hits must equal the table.
   With no rejections this reduces to the live1 table, so the strict case is a special case, not a weaker one.
3. No member resent that was not rejected, no rejected member left unresent while attempts remain, no member sent a
   third time. A job that exhausts two attempts makes the scenario fail as "model, unresolved"; no rerun clause.
4. Interrupt: the three live1 observables unchanged. Stale (C3): no old A bytes after the mutation; dispatch order
   after it equals extract_A, bounds_A, the four classifications, then the singleton resends the predicate derives;
   B/C/D reused on identical inputs; A history kept and delivery cites rev 2.
5. The report states per scenario both `pass` (strict, informative) and `pass_g3b` (the gate), and the plan text says
   in one sentence that `pass_g3b` on all five scenarios plus the C5 checks is G3. One label binds the gate.

**Why this is not moving the goalposts.** Live1 keeps its failed verdict and its tokens stay charged. The new
predicate is derived from the recovery policy signed before live1 (sizes 4 or 1, unresolved-only recovery, two
attempts), it is stricter than a launch count on the axis an executor controls (which members go back, how many, in
what order, at which attempt), and it stops grading the executor on a property it does not control (whether Sonnet
thinks on a given packet). The claim stays "conformance passed", not model reliability and not O1.

**Dry gate additions (G2, zero tokens), frozen before G3b:**
1. Fixture reply with two wrong members in one size-4 packet: predicate expects two singleton resends; the executor
   must match.
2. Sabotage, each must be caught: resend the whole packet of 4; resend a correct member; resend both rejected
   members as one size-2 packet; send a rejected member a third time; skip a resend and deliver.
3. Replay the predicate, read-only, on live1's recorded verdicts and dispatches. Expected: interrupt and stale
   traces match. This is a test of the predicate on real data, labeled as such, and it is not a pass of live1.

### 2.3 Budget (fresh allocation, owner decision)

Measured in live1: a size-4 packet costs about 2.68k tokens (clean, 8,049 for 3), a singleton about 2.35k to 2.45k.

| Scenario | Base launches | Worst realistic (all four classify members resent) | Tokens, expected (live1 resend rate) | Tokens, worst realistic |
|---|---:|---:|---:|---:|
| clean | 3 | 7 | about 10.5k | about 17.9k |
| repeat | 0 | 0 | 0 | 0 |
| interrupt | 3 | 7 | about 10.5k | about 17.9k |
| stale | 5 | 9 | about 15k | about 22.6k |
| bump | 0 | 0 | 0 | 0 |
| total | 11 | 23 | about 36k | about 58.4k |

Proposed caps: **64k tokens, 24 launches, 10 per flow**, 5k admission reserve per launch unchanged, fresh workspace
and memo namespace `live2-*`, fresh quota group check. Expected spend is about 36k, the live1 figure. If CLI
2.1.306 is no longer installed, G0 blocks as the freeze requires; a new CLI version is a new route and gets noted,
since thinking allocation may differ.

Keeping the size-4 classify composition is the right call under the metric order. Correctness is guaranteed by the
checks either way. On tokens, size 4 plus expected resends (about 2.7k plus 2/3 of 1.5 singletons, about 5.1k) beats
four qualified singletons (about 9.6k), even at live1's failure rate.

### 2.4 Optional model probe (separate preregistration, does not gate step 4)

If the owner wants the language lesson measured rather than asserted, freeze before its first call:
1. K4: the exact live1 clean classify packet bytes (`33ffc1fc`), 8 calls.
2. K4i: classify@2, the same four jobs, each ref carrying the checked interval (`/bounds/X`) and an op text that
   compares that interval to the goal's inclusive bounds, 8 calls.
Record per call: thinking tokens, per-member correctness, tokens. About 2.7k per call, so about 44k tokens, 16
launches. Report the edge-case error rate per arm with its counts, and the error rate conditional on thinking = 0.
K4i is a new op version and would need the per-composition qualification before any shipped use. Running it after
G3b keeps G3b independent of its result.

## 3. What the failure teaches

### Language

1. **Hidden reasoning is an uncontrolled resource and must be a recorded one.** At default effort the model chooses
   per call whether to think, and on identical bytes the answer flipped with that choice. The ledger should carry
   `thinkingTokens` per call (the envelope already has it in `modelUsage`), and reports should show it per stage.
   A composition is only qualified if its correctness holds across the thinking the model actually chose, including
   zero.
2. **Qualification needs branch and boundary coverage.** A classifier op is not qualified until every output label,
   and every inclusive edge of every comparison, appears a minimum number of times in the qualification set. The
   64-job pilot had zero `inside` cases. Proposed rule: per op, at least k cases per label and per edge, stated in
   the qualification freeze.
3. **Feed checked intermediates forward.** When a barrier has verified a value (the interval), downstream model ops
   should receive it as a ref instead of re-deriving it from raw data. The qualified mixed-op cell had that for free
   (bounds written before classify in the same reply); the DAG split removed it. Proposed lint: a model op whose
   instruction recomputes a value a dependency already accepted. Hypothesis until K4i or equivalent measures it.
4. **Host-computable ops should be flagged.** Every model op in this workflow has a job-bound check that equals a
   total host function of its inputs; `mat_classify` is the answer. Outside a conformance gate, the cheapest correct
   classification is a host op at 0 tokens and 0 error. Proposed planner lint: an op whose acceptance check is
   "value equals host_fn(inputs)" is host-computable; warn, and require an explicit reason to keep it a model op.
   This also sharpens O1: this workflow cannot evidence model necessity, by construction.

### Workflow and gates

5. **Separate executor gates from model-accuracy claims.** A fixed launch count silently assumes a model error rate
   of zero. Executor gates should be exact conditional on recorded model verdicts; model reliability should be a
   preregistered rate with a sample size.
6. **Counting units must match the recovery policy.** Members, not dispatches, when the policy resends per member.
7. **One label binds the gate.** If a plan defines several pass labels, the plan text names the one that passes the
   gate, and a test asserts that the report's gate verdict reads that label.
8. **Diff the frozen text against the signed text.** C3 lost its exception between round 1 and the freeze. The
   freeze review should compare every pass criterion in the signed rounds with the frozen text and the code.
9. **Headroom for the recovery policy, not just for estimates.** The "one rerun within the same caps" clause was
   unusable after three resends. Caps should cover the policy's realistic worst case, or the plan should say the
   clause is unlikely to be usable.
10. **The checks paid for themselves.** Three wrong values were caught and fixed for about 7.3k tokens of singleton
    resends (2,440, 2,448 and 2,453 tokens). Without job-bound checks a delivered handoff would have been wrong
    while the baseline arm, with no per-job checks, happened to be right because it thought for 266 to 363 tokens.
    The baseline's correctness here is a sample of 4, not a guarantee; the executor's is checked.
11. **Decomposition shrinks per-call reasoning.** The whole-package baseline thought 266 to 363 tokens and was right
    on every edge; the staged executor's classify packets thought 0 to 79. Splitting work into small stage calls can
    lower the model's own effort below what a subtask needs. This belongs in M14 as a hypothesis: the inline versus
    executor threshold depends on reasoning allocation, not only on fixed per-call cost.

## 4. Points I expect Astra to push on, and my position

1. "Conditional traces make any model behavior pass." No: delivery, evaluator, two-attempt bound and the
   per-member predicate all still bind, and a job that fails twice fails the scenario. What it stops doing is
   failing the executor for the model's choice.
2. "Fix the cause first (classify@2, or effort high)." Effort is part of route identity, raises tokens on every
   stage, and does not remove the variance. classify@2 is a new op version that needs measurement; I keep it in the
   optional probe so G3b is not tuned to pass.
3. "Use singletons for classify, the qualified cell." Correct but costs about 4.5k more per cold scenario for no
   correctness gain, since checks already guarantee correctness. It violates the metric order on tokens.
4. "Report live1 as pass_with_recorded_rejections for stale." No. The frozen code decides; live1 is not rescored.
