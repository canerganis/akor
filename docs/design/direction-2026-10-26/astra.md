**Decision: stop `oz map` development and further replication now. Make the existing executor prove that it improves useful work under subscription limits. Keep OZ/1g stable.**

The replication’s invalid verdict stands, but transport classification is not the decisive issue: even without it, neither backend met the combined efficiency thresholds. Another amendment would not fix that. The learned rules are an interesting observation, not a product priority. [Replication result](../ozmap-replication-2026-10-24/replication-result.md)

The original build order was broadly right. We already have substantial executor functionality: O1 delivered verified repairs with recovery and reuse. **The missing evidence is comparative value:** O1 had no baseline; the earlier inspection baseline was cheaper cold. We should close that gap before building more machinery. [O1 result](../o1-real-workflow-2026-10-23/results.md) · [Inspection comparison](../step4-2026-10-23/results.md)

**What success means**

Maximize independently verified user deliverables completed before a fixed deadline, within separate Claude and Codex quota limits. Internal jobs, graph nodes and accepted syntax are not deliverables.

For equal completed work, compare actual subscription consumption and elapsed time; use total tokens as the tie-break. Report tradeoffs explicitly—half the tokens with slower delivery is not an unconditional win.

Record:

- Provider quota readings before and after each arm, with timestamps and any concurrent account activity.
- End-to-end elapsed time, failures, retries, unresolved targets and human intervention.
- All attributable CLI usage, including orchestration, reasoning and cache categories, without double counting.

**Tokens are not a conversion formula for subscription quota.** If quota readings are too coarse or delayed, report the quota comparison as inconclusive. Track development/review consumption separately from runtime consumption so the project’s own overhead stays visible.

**Today’s concrete step**

Claude implements **one small comparison runner**, reusing O1’s fixtures and independent evaluator. Codex handles inspection, dry verification and result analysis.

Compare two ways to deliver the same repaired package:

1. A competent direct CLI workflow: one request for the whole package, local checks, bounded corrective retry.
2. The existing AKOR executor, unchanged.

Use the same backend, model, effort, source information and acceptance checks. Run two paired sequences with reversed arm order: **cold repair, then one changed-input revision**. Both arms retain their own previous artifacts; do not force the direct workflow to forget its work. No injected failures today.

Use Sonnet for this small comparison to avoid making a new adapter the prerequisite. Set a five-minute deadline per delivery, a combined ceiling of 16 worker invocations and 150,000 reported tokens, and stop earlier if quota requires it. These are engineering caps, not quota guarantees. From the supplied 78% Claude reading, stop new work at 90%, reserving three percentage points within today’s approximately 15-point allowance; 95% remains the owner’s absolute stop line.

The output today is one comparison table and a decision. Two pairs provide a directional result, not a general performance claim. If AKOR loses cold and wins revisions, target revision-heavy workflows. If it loses both, simplify toward the direct runner before adding features.

**Explicitly rejected:** another rule-learning campaign; language redesign without a measured bottleneck; new councils and repeated sign-offs; benchmarking against deliberately wasteful per-job calls; treating cache hits or token reductions as demonstrated quota savings; broad release claims from seeded repairs.

This is my decision for Claude to implement and challenge—not a claim that Claude has already agreed. Repository inspected read-only; no edits or live model calls made.


