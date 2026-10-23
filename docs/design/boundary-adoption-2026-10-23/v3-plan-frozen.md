# Step 4 v3: host classification, frozen plan as implemented

Decision: [decision-host-classify.md](decision-host-classify.md), from Astra's [round 05](05-astra-next.md) and Opus's
[round 06](06-opus-next.md). This file records what the code does and what the zero-token gate showed. Nothing here is
a model result: no model was called to build or gate it, and no paid run is allocated.

## Identity

| Item | Value |
|---|---|
| Freeze digest | `2e1202f587ed30a8abe79c0501c348851d5283fe542315ecaab2e9e1860a211a` (short: 2e1202f5) |
| Freeze record | `bench/step4/inspection-handoff-20-v3/freeze.json` (pack files, code, the v2 case file it reads, design files 01 to 06 and the decision, the plan record) |
| Workflow | `inspection-handoff-20/v3`, pack `bench/step4/inspection-handoff-20-v3/` (20 nodes; v1's sources and expected values byte for byte) |
| Harness | `bench/step4/v3.py` (freeze, dry, run-flow) and `bench/step4/host_classify.py` (the operation, the graph rule, the per-pack module copies) |
| Operation | `host.classify@1`, inputs `interval` and `limits`; no `model.classify` operation or node |
| Route | none paid: the fixture oracle adapter only. The `route` block in `workflow.json` is inert and marked so; `run-flow --kind live` is refused |
| Beside, untouched | v1 and v2 packs, their freezes (`freeze.json`, `freeze-g3b.json`, v2 `freeze.json`) and every v1 and v2 harness file hold their digests |

The digest is the sha256 of the canonical JSON of two parts, CRLF normalized. Files: every pack file; the executor and
adapter (`oz.py`, `oz_batch.py`, `oz_reply.py`, `oz_accept.py`, `oz_runtime.py`, `oz_worker.py`, `oz_runner.py`,
`oz_do.py`, `oz_memo.py`, `oz_quota.py`, `oz_flow.py`, `oz_fault.py`, `oz_workspace.py`,
`examples/claude_cli_adapter.py`); the step 4 harness (`workflow.py`, `evaluator.py`, `fixture_adapter.py`, `g3b.py`,
`step4.py`, `packs.py`) plus `host_classify.py` and `v3.py`; v2's `qual.json` (read only, for the 24 cases); design
files 01 to 06 and the decision. Plan: workflow id, operation and its inputs, the structured limits, the goal, the
model operations, the node count, expected launches, packets and memo hits per scenario, the allocation, the fixture
and recovery case names and the rules. `freeze` regenerates the plan record and compares it with the stored one.

## What was built

1. **The operation.** `host.classify@1` reads `interval` (node 11's `/bounds/X`: two two-decimal mm strings, or
   `unknown`) and `limits` (exactly `{lower, upper, unit: mm, inclusive: true}`, the structure `workflow.json` stores).
   It returns `inside` exactly when `lower <= interval_low` and `interval_high <= upper` in `Decimal`, `outside`
   otherwise, `unknown` when the interval is unknown. A malformed interval (wrong shape, one decimal, no unit,
   inverted) or malformed limits (extra or missing key, other unit, `inclusive` not true, lower not below upper) raises
   `HostError` and blocks the node; bad limits are refused even when the interval is unknown. Nothing is repaired.
2. **The graph.** The four `classify_X` nodes keep their ids and position, so the graph keeps 20 nodes. Each binds
   `interval = {node: checked_intervals, path: /bounds/X}` and `limits = {lit: <workflow.json limits>}`, with no extra
   edge. `handoff_rows` still consumes `classify_A..D` in record order. `host_classify.graph_problems` refuses any
   other shape (another record's interval, another node, a changed literal, a model classify node, a missing node, an
   ordering edge) and a spec that lists `model.classify`.
3. **Same dependencies as the rest of the pack.** The classify nodes depend on node 11 (`checked_intervals`), which
   recomputes every bound on the host. A node commit is checked against the source revisions it cites and the
   acceptances it consumed, so a classification computed from a node 11 that has moved is refused at commit and
   recomputed (fixture 11). `host.handoff_rows` still recomputes each label from the checked interval and the pack's
   `LOWER` and `UPPER` and refuses a row that disagrees: an independent second host check of the same rule.
4. **No harness file was edited.** `packs.load` builds v3 copies of `workflow.py`, `g3b.py` and `step4.py`;
   `host_classify.py` registers the operation and the graph rule in the v3 `workflow.py` copy only, binds the v3
   `step4.py` copy to the three v3 copies, and builds the v3 `evaluator.py` copy by executing the file under the v2
   key (its table has no v3 entry) and then binding `FROZEN` and `WORKFLOW` to v3. `v3.py` patches the v3 `step4.py`
   copy as `adopt.py` does: the freeze, the run-flow entry point, a flow request that refuses a graph or limits
   problem, and the stale-input observables (their expected primary list loses the classify stage and gains a check that
   the four host classifications cite revision 2 only). The executor (`oz_*.py`) is unchanged.
5. **The G3b predicate, unchanged.** `g3b.json` for v3 lists only the extract and bounds stages (stale revised from
   stage 2) and no `model_refs`. The predicate's trace oracle, eligibility audit and exact-trace comparison run on the
   v3 copy as before. The allocation (`max_tokens` 40000, `max_launches` 16, per flow 10) is a dry-gate cap only.

## Expected launches (frozen)

| Scenario | Primary packets | Launches | Memo hits | Against v2 |
|---|---|---|---|---|
| clean | 4, 4 | 2 | 0 | no size-4 classify packet (v2: 3 launches) |
| repeat | none | 0 | 8 | the 4 classify hits are gone (v2: 12) |
| interrupt | 4, 4 | 2 | 0 | v2: 3 |
| stale | 4, 4, 1, 1 | 4 | 6 | v2: 5 (extract and bounds of A rerun; the classify packet is gone) |
| bump | none | 0 | 16 | v2: 20 |

## Dry results (zero tokens)

Commands, from the repository root, in the foreground:

```
python bench/step4/v3.py freeze
python bench/step4/v3.py dry --workspace .oz-runtime/hc-dry
```

`freeze` reports `frozen: true`, digest 2e1202f5. `dry` exits 0 with `pass: true` in about 23 seconds.

| Item | Result |
|---|---|
| Five scenarios under `pass_g3b` | all pass, all strict (launches 2, 0, 2, 4, 0; packets and memo hits as in the table; no recovery used) |
| Totals | 8 launches, accounting complete (the 5163 tokens are the fixture adapter's byte-derived figure, not model tokens) |
| C5 subset | byte identity across clean, repeat and interrupt, with bump differing only in the revision; a route change misses exactly the 8 model jobs; revocation of one bounds entry misses exactly one; a strengthened bounds check revalidates the retained candidates with no launch |
| Recovery cases | wrong answers in both model stages (packets 4, 1, 4, 1); a wire-rejected extract packet (4, 4, 4); stale with rejections before and after the mutation (4, 1, 4, 1, 1, 1); interrupt with recovery (4, 4, 1, 1); a second-attempt failure ends unresolved with the exact derived trace (4, 4, 1) |

Host classification fixtures, all passing:

1. Structured limits, goal, template, constants, handoff document, Markdown line and the evaluator's own copy agree; a
   goal, limit or graph literal that disagrees is refused.
2. The graph rule refuses another record's interval; run anyway, the host row check refuses the row (blocker at
   `handoff_rows`).
3. No classify job in any dispatch of the five scenarios; all four classify nodes are `host` kind with identity
   `host.classify@1`; the registry has no `model.classify`.
4. Equality at both limits is inside (unit, and delivered A and C in the clean package).
5. 0.01 breaches on either side are outside.
6. The 24 frozen cases of v2's qualification (three goals) agree with both the operation and the integer oracle.
7. Unknown stays unknown, in the operation and in the delivered record D with its follow-up.
8. 15 malformed intervals and limits are refused by the operation; a flow whose limits are malformed blocks at
   `classify_A` with `host_refused` and no launch.
9. Changed limits change the labels (wider and narrower limits match the oracle); a spec or a graph literal changed
   alone is refused by the graph rule.
10. A graph with widened literal limits is refused by the graph rule; run anyway, the row check stops it at
    `handoff_rows`; with that check given the same change, the package is delivered and the independent evaluator
    reports B's status.
11. Node 11 superseded after the classify host operation computed and before it committed: the commit is refused
    (`stale source revision: A`), the classification is recomputed on the new interval, and the delivery cites A
    revision 2 and passes the evaluator.
12. In the stale scenario the four host classifications cite revision 2 only.
13. The host operation, an integer-hundredths oracle and the fixture adapter's Decimal oracle agree on 10,800 intervals
    over 36 limit pairs; the oracle also agrees with every frozen expected status.
14. For all five delivered packages, each status equals the oracle's label of the delivered interval and the
    independent evaluator reports no error.
15. Six sabotaged operations (strict at the lower limit, strict at the upper limit, upper limit only, lower limit only,
    width only, previous interval kept) are each stopped by the host row check, and each is also caught by the
    evaluator when the row check shares the bug.

The focused tests are in `tests/test_host_classify.py` (22 tests, including a grid of 3,696 intervals against an
independent integer oracle and the whole dry gate).

## Notes and limits

1. The dry gate shows the host path is exact and its dependencies hold. It is not evidence about any model. v1's G3b
   live2 pass stays the live evidence for v1; v2's records stay as recorded (size-4 cell failed, size-1 untested, not
   adopted). Extract and bounds are unchanged and still experimental compositions.
2. Host code is not error-free by being host code: the operation, node 11 and the row check are tested, and the
   evaluator reads only frozen expected values. A bug shared by both host implementations is the case fixtures 10 and
   15 cover through the evaluator.
3. The graph literal for the limits is a second copy of `workflow.json`'s limits. The freeze and `flow_request` refuse
   a disagreement; the executor itself would run a valid graph with other limits (fixture 10 shows what then stops it).
4. A later live claim about v3 needs its own preregistration, allocation and the 49% stop line.
