# AKOR brainstorm, 2026-10-22: "develop it with full force"

## Mandate (from the owner)
You have full authority over the OZ language and AKOR's direction. Change or extend anything, as long as it
serves the criteria: minimum tokens, maximum correct work, maximum speed for agents talking to agents
(orchestration). Teaching the language once may cost more; later calls must get cheaper (judge amortized cost per
verified job and break-even N). Every change is measured against the previous committed version; regressions get
fixed or reverted. Constraints: no API key and no direct API adapter (only authenticated `claude -p` and `codex exec`);
subscription quotas and a deadline are the real budget. Metric order (OZ9.md section 1): (1) max independently
correct requested work before the deadline within quotas, (2) min total billed tokens incl. hidden reasoning and failed
calls, (3) min elapsed time.

## Participants
Astra (gpt-6-astra, language owner) and Opus 5.5 (Claude, implementer and critic). Each proposes independently first,
then critiques the other's proposal, then both converge on one joint plan.

## Where AKOR is today (branch oz-0.9, public repo github.com/canerganis/akor, 337 tests)
- Shipped wire OZ/1g (system text H, verbatim in OZ9.md 2.1): body {v,goal,ops,refs,jobs}; jobs grouped
  [op_index,[job_id,ref_index,...],...]; reply line "OZ/1g" then {"id":value} or ["id","error",code,message] per job;
  strict atomic whole-reply acceptance, nothing repaired, one batch retry.
- Host: SQLite inbox with deps, leases, retries, resume; host executes reads/tests/status events with zero model calls;
  --min-batch/--max-wait quorum batching; append-only ledger calls.jsonl.
- Live, preregistered, paired against plain JSON with the same 64 jobs in one call (billed tokens incl. ~950 CLI
  overhead and hidden reasoning, failed calls counted):
  Sonnet 5.5 146.7 -> 87.0 tokens/verified job (-40.7%, 20/20 replies), Opus 5.5 144.3 -> 82.6 (-42.8%),
  Fable 5.1 146.3 -> 86.9 (-40.6%), Haiku 5.5 205.3 -> 142.1 (-30.8%; Haiku thinks ~6k output tokens/call in both arms).
  91/91 Claude replies accepted on the final wire. Median time per call also lower on all four.
- Offline o200k packet for 64 jobs: plain JSON 3268, OZ/1g 1471.
- Qualified only on Claude via claude -p. Codex/Luna medium failed (1/10): index drift with 0 reasoning tokens,
  mixed record shape fork ([ after an error record), record split over lines. Codex CLI adds ~24.5k fixed input
  tokens per call, so wire savings barely move Codex totals.

## What is NOT done (from the owner-approved build order, 2026-10-12)
1. Done: single named-ops form, strict validation, call ledger.
2. Partly done: host executes deterministic ops (read/test/status). Per-job acceptance with idempotent retries is
   not done: acceptance is all-or-nothing per reply, one bad line re-runs 64 jobs.
3. Not done: resumable DAG executor with checkpoints, versioned result memo, bounded replanning, planner wire.
   OZ9.md sections 7-9 specify plan-as-data, a planner wire, checkpoints and replanning; none is implemented.
   The owner's judging criterion for step 3: a recorded 20-step real workflow.
Deferred earlier: progressive cached block, ref projections, sampled verification.

## Known weak spots / facts
- Savings need batching: 1 to 4 jobs per call gain nothing (fixed per-call overhead dominates; CLI alone ~950 tokens).
  Real agent traffic is often small, sequential, dependent calls, not 64 independent ready jobs.
- Thinking tokens do not shrink with the packet (Haiku case); output/reasoning is now the dominant cost on several models.
- Benchmark covers one task family (structured extraction/classification with oracles). README roadmap lists code
  review, log triage, and a comparison against one-call-per-job pipelines (the way most pipelines actually run;
  likely a much larger saving than vs. batched plain JSON, but unmeasured).
- Index addressing needs a reasoning model; uniform object error record {"id":"w","error":[code,message]} was
  proposed by Astra to remove the mixed-shape fork, not adopted.
- Prompt caching through claude -p: the ledger records cache use; it is unclear how much of system text H and the
  CLI overhead is already cache-read at a discount, and whether stable prefixes are exploited deliberately.
- Adoption: public repo, ~1 star; X posts with low reach. It is also the owner's portfolio project
  (AI Engineer + Materials Engineer roles). Integration surface today: `oz` CLI + Python; no MCP server, no
  Claude Code subagent/skill integration, no library hook for existing frameworks.

## The question
What should AKOR become next, and in what order, to get the largest gain on the metric above (and secondarily
real-world usefulness/adoption)? Diverge first: 8 to 12 distinct ideas, spanning wire/language, host/runtime,
planning/DAG, measurement, and integration/distribution. For each: the mechanism, the expected measurable effect
(with your estimate and what it is based on), the cheapest decisive test, and the main risk. Then rank your top 3
and say what you would deliberately NOT do. Be concrete; cite the facts above where you rely on them.
