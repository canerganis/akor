# Brainstorm 2026-10-22: what AKOR builds next (Astra and Opus 5.5)

Participants: Astra (gpt-6-astra, xhigh, language owner) and Opus 5.5 (Claude, implementer and critic).
Format: independent round 1 from the shared pack, cross-critique in round 2, convergence in round 3.
All rounds are kept verbatim in this folder (`00-pack.md` to `05-astra-round3-final.md`).

## Outcome

AKOR's next gain is not more input compression on the existing benchmark. It comes from three places: the real
baseline people run (one call or one subagent per job), dependent multi-step work (the unbuilt DAG executor), and
hidden reasoning, which the packet does not shrink.

Corrections each side accepted:
- Opus overstated the output lever. Visible output is about 25% of an Opus OZ/1g call (1330 of 5284 tokens), so a
  20 to 40% output cut saves 5 to 10% overall. On Haiku, thinking is about half the total; effort comes first.
- Default-value elision and echoed drift-guard fields were dropped: they cannot prove which jobs were done or catch
  index drift. Explicit IDs and independent verification stay.
- Astra moved the thin Claude Code integration earlier: subagent-per-job fan-out is where the tokens are, and it
  yields real arrival traces for scheduling work.
- Memo hits need freshness checks; cache discounts are reported apart from raw tokens; quota weighting stays unknown
  until measured.

## Joint plan (signed by both)

| Step | Decisive test | Gate |
|---|---|---|
| 1. Freeze evaluation; inspect existing evidence | Re-score archived Sonnet-64 and live8 effort data. Freeze requested outcomes, verifiers, deadline, budget. | Accounting discrepancies resolved; thinking counted once; raw tokens reported apart from cache accounting. |
| 2. 16-job integration pilot (thin skill + CLI) | Per-job CLI, subagent-per-job, batched JSON and OZ on identical read-only work, equal concurrency, full orchestration and retry accounting. Capture arrival traces. | Expand to 64 only with equal on-time correctness and lower total tokens. Savings are attributed to OZ only where it beats batched JSON. |
| 3. Selective acceptance and fencing | Inject malformed records, truncation, duplicates, ID swaps, late attempts against oracles. | Verified successes kept, only unresolved jobs retried, no stale commits or duplicate effects, regression suite green. |
| 4. Manual 20-step executor with checkpoints and freshness-verified memo | Deterministic job oracles plus host tests; interrupt and resume, then change a dependency. | Correct final deliverables, correct invalidation, no repeated effects. Recovery benefits reported apart from token savings. |
| 5. Optimize from evidence, one variable at a time | Effort first (from live8), then scheduling on real traces, a 10-call cache-layout probe, typed outputs where justified. | Promote only held-out improvements, counting retries, verification and context costs, with no correctness or deadline loss. |
| 6. Package; optional bounded replanning | One permitted replan against the fixed executor, setup and teaching costs included. | Keep only justified completion benefits. MCP only on demonstrated need; wire changes need qualification evidence. |

Promotion order: correct requested work before the deadline, then total tokens, then elapsed time. Every step is
compared with the previous committed version.

Not now: rescuing Codex/Luna with wire changes, new compression syntax without comprehension and total-cost gains,
sampled verification, direct API adapters, a hosted platform, broader claims before one reproducible workflow
survives interruption.
