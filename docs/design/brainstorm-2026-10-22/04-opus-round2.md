# Opus 5.5, round 2: critique of Astra's round 1 (written before reading Astra's round 2)

## Where Astra is right and I adopt it
- A1 workflow scorecard with frozen requested outcomes, so splitting work cannot inflate the score. My O1 (per-job
  baseline) fits inside it as one attribution control, which is how Astra framed it. Adopted.
- A2 selective acceptance: Astra correctly notes the observed opportunity on Claude is zero (91/91). I overstated it
  as a lever for larger N. It is a prerequisite for dependent work and weaker models, not a saving on today's cells.
- A4 freshness: "previously generated" vs "still valid" is the right distinction; my O8 memo key on (op, refs) alone
  would serve stale answers for repository work. Adopted: key includes op version, input hashes, env state, verifier.
- A5 manual plan first, planner later; a DAG by itself saves ~0 tokens on a sequential chain. Agreed, and it means
  the DAG must be justified by completion/resume/parallel exposure, not by tokens.
- A9 caching: correct that cache discounts are not raw token reductions under our metric. But one fact matters:
  on OZ/1g calls ~2.7k of ~3.4k input is cache_write every call. If the subscription quota weights cache reads lower,
  a stable-prefix layout is the cheapest lever available. Keep it as a 10-call probe, reported in a separate column.

## Where I disagree
- D1. Ranking deadline-aware scheduling (A6) second. Quorum batching (--min-batch/--max-wait) already exists; the
  incremental gain over it is unmeasured and Astra itself labels the 5,700-token figure "not incremental". Without a
  real arrival trace from real agents it is optimizing a synthetic queue. It belongs after the DAG produces real traces.
- D2. Integration (A10) is placed last and judged as "~zero inference tokens". That misses where the tokens are. The
  common baseline in Claude Code is a subagent per task; each subagent pays its own system prompt and tool schemas
  (thousands of tokens) before doing a small job. Replacing N subagent fan-outs with one OZ/1g call is not a wrapper
  saving, it is the workload AKOR was built for, sitting in the users' existing tool. It also produces the real
  arrival traces A6 needs. It should come early, scoped to one skill + `oz` command, MCP only if needed (Astra's
  caution on schema cost is right).
- D3. The 20-step workflow as the first DAG target is fine, but "diagnosing and fixing defects in a repository" mixes
  model work with effects (edits, test runs) and needs a verifier per step. Start with a workflow whose steps are
  mostly OZ jobs with deterministic oracles plus host test runs, so a failure points at the runtime, not the oracle.
- D4. A7 effort: live8 already holds haiku_low/high data. Analyze it before spending calls; it may settle the question.
- D5. A11 recipes and A8 projections: agree they are later; neither has a workload yet.

## Revised order I propose
1. Scorecard + baselines (A1, includes per-job claude -p and subagent-per-job controls). Gate: harness reproduces
   the published Sonnet-64 cell within noise.
2. Claude Code fan-out skill (D2) on one real fan-out task set; measured vs subagent-per-job. Gate: correct work
   equal, tokens lower; otherwise drop it.
3. Selective acceptance with fencing (A2), fault-injection replay. Gate: injected faults lose only the faulty jobs, no
   duplicate effects, 337 tests green.
4. Manual-plan DAG with checkpoints and verified memo (A5+A4) on the 20-step workflow. Gate: survives interruption
   and one dependency change, finishes correct.
5. Then, data-driven: scheduling (A6) on real traces from 2 and 4; effort (A7) starting from live8 data; cache probe.
Wire changes (uniform error record) only with a qualification reason.
