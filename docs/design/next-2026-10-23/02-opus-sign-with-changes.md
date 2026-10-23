# Next work after steps 1 to 4: Opus 5.5

**SIGN with five changes.** I agree with the order (traces, then packaging, then one qualified use case, then step 5
only against a measured bottleneck), with zero paid experiments today, and with the exclusions (no further boundary
study, no importer, receipt redesign, replanner or MCP without a demonstrated need, no publication or push).

## Changes

1. **Executors.** Codex cannot write the repo on this machine. Wherever the table says Codex implements, builds or
   runs, read Claude subagents: Sonnet or Haiku for implementation and tests, Opus to review the contract and the
   final diff, Astra still owning the interface and the decisions. That work spends the same Claude weekly quota, so
   "zero paid experiments" does not mean zero quota.

2. **Quota line for today.** Stop new work at 46% weekly used, which leaves headroom under the 49% hard stop for
   in-flight subagents and reviews. Step 1 runs first. Step 2 starts only if step 1 ends below 44%, and it stops
   cleanly at 46% with its state committed on a branch.

3. **Step 1: fix the categories before looking.** Name the trace corpus: step 4 live1, live2 and live3, O1 live1,
   adopt-qual, the boundary probe, caller-cost and the pilots, all from `modelUsage`. Before reading the shares,
   freeze the categories:
   1. Per call: system H cache write, cache read, packet input, visible output, thinking.
   2. Per run: failed and resent calls, check-driven work, caller overhead where a caller was measured.
   3. Time: critical path against waiting.
   Also freeze the rule for "actionable": a category that is at least 25% of billed tokens or elapsed time on a
   workload with a model-needed job, and that one variable could move. Without a preset rule the analysis picks its
   bottleneck after seeing the numbers. Two facts are already measured and should be checked first, not rediscovered:
   1. O1 thinking was 584 to 1,186 tokens per size-4 call.
   2. Each call pays about 2,000 tokens of H as cache write or cache read.
   The host-computable scan uses the new authoring rule: any model op whose check recomputes the full answer is
   flagged.

4. **Step 3: compare against the open case, not the settled one.** Caller-cost already settled that a same-model
   caller handing work to `oz do` does not beat inline work on tokens. The cost comparison should target what that
   record left open: a cheaper worker model than the caller, references too large for the caller's context, or a
   caller whose context is full. Recommended use case: O1 `repair-handoff-20`, the only workflow that needs the model,
   with its size-4 and size-1 code-repair cells qualified, since O1 ran them as experimental. The owner confirms the
   use case before any allocation.

5. **Step 4: let step 1 choose the variable.** Drop "effort first". Haiku `--effort medium` already failed on OZ/1g,
   and the boundary question is closed. Effort is a candidate only if step 1 shows thinking as the actionable
   category on a model-needed workload. Scheduling is a candidate only if step 1 shows avoidable waiting.

Step 2 as written is fine. Its proof runs on the fixture route at zero model tokens, from a fresh workspace, with the
full suite (749 tests) green and output defaults unchanged.
