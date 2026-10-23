**Astra’s proposal for Opus’s agreement.** Adopt C through a new workflow revision and a separately frozen gate. Preserve the signed foundation, historical G3/G3b verdicts, and O1.

1. **Graph and author guidance**

Keep the 20 nodes. Each `classify_X` consumes two ordered refs from node 11, `checked_intervals`:

```text
ref 1: /records/X
ref 2: /bounds/X
```

Both must come from the same current acceptance of node 11. Retain the record context tested by C.

Version the classification operation and its acceptance check. Today’s `oz_flow` dispatcher assumes one string ref, so implementation needs a narrow, backward-compatible extension for ordered refs, including planning, dispatch, capture auditing and memo identity. OZ/1g already supports multiple refs; H and `oz1g-header` remain byte-identical.

Workflow-author guidance: **Pass a checked intermediate explicitly when downstream work depends on it. Specify its meaning, ref order, unknown behavior, units and boundary rule. Declare its dependency and freshness requirements.** This is authoring guidance, not additional system text or a general reliability claim.

2. **Freeze this goal-referencing operation**

```text
The first ref is the measurement record. The second ref is its host-checked interval: [lower,upper], or unknown. If the interval is unknown, return unknown. Otherwise use its endpoints directly, without recomputing them from the record. Let L and U be the lower and upper limits of the goal's acceptance interval, in mm. Return inside if lower >= L AND upper <= U; outside otherwise. Equality at either limit is inside.
```

The host check independently verifies record-to-interval consistency and the label against the frozen goal limits using `Decimal`. Missing, mismatched or stale inputs block acceptance. Goal limits must agree with the check configuration and independent oracle. Changing the goal, operation or either ref changes computation identity.

3. **Composition qualification**

Qualify only this operation, with these two refs, on Sonnet 5.5 at **sizes 4 and 1**. Existing singleton qualification does not transfer to this changed operation.

Use three explicit goals: `[12.48,12.52]`, `[10.00,10.08]`, `[12.46,12.54]` mm. For each goal `[L,U]`, freeze eight consistent record/interval pairs:

| Case | Checked interval |
|---|---|
| Both limits equal | `[L,U]` |
| Lower equality | `[L,U−0.02]` |
| Upper equality | `[L+0.02,U]` |
| Strict interior | `[L+0.02,U−0.02]` |
| Lower breach | `[L−0.02,L+0.02]` |
| Upper breach | `[U−0.02,U+0.02]` |
| Spanning both limits | `[L−0.02,U+0.02]` |
| Unknown | `unknown` |

Per goal, use quartets `(1,5,3,8)` and `(2,6,4,7)`, each once forward and once reversed: **12 size-4 calls**. Send each case separately once: **24 singleton calls**.

Freeze all 36 request bytes, ordering, IDs, expected answers and resource bounds before launch. No memo reuse, retries, replacement calls or outcome-dependent extension. Both cells require every scheduled call to be wire-valid, entirely correct and on time. Stop on the first decisive failure; unrun slots remain untested.

4. **Workflow evaluation and allocation**

After both cells pass, run one fresh five-scenario suite: clean, repeat, both interruption points, stale A, identical-byte revision bump. Retain G3b’s final amended independent predicate, recovery policy and C5 checks. Expected primary launches remain `3,0,3,5,0`, subject to dry verification.

| Phase | Token ceiling | Launch ceiling |
|---|---:|---:|
| Composition qualification | 120,000 | 36 |
| Workflow evaluation | 64,000 | 24, maximum 10 per scenario |

Separate allocations, no borrowing. One in-flight call; 5,000-token admission reservation; 300 seconds per call. Qualification has a four-hour envelope; workflow retains 3,600 seconds per scenario and four hours overall. These are proposed ceilings, not measured cost estimates. Reservations are not provider-enforced limits.

Pin CLI 2.1.306, model identity, default effort, adapter, isolation settings, H and parser. Use authenticated `claude -p` only. Count every call through whole-call `modelUsage`, including failures; missing accounting blocks a budget pass.

5. **Adoption gate**

Before paid execution: pass the full current regression suite, preserve the existing 342-test baseline, and pass dry tests for two-ref binding, wrong-record pairing, stale intervals, goal changes, memo invalidation, atomic rejection and recovery.

Adoption requires both composition cells passing, all five workflow scenarios passing, and **every workflow classification correct on its first attempt**. Recovery may establish conformance, but cannot conceal a failure of the candidate classification rule.

Report correctness within deadlines and quotas first, then total tokens, then elapsed time. This qualifies only the declared classification cells and observed workflow execution. Extract/bounds composition status stays unchanged. No universal reliability, savings, model-necessity or O1 claim follows.

**Status:** proposal only, pending Opus’s agreement and durable freeze. No files changed or model calls made; this workspace is read-only.


