# Step 2 pilot plan (frozen before the first counted call, 2026-10-22)

Question: how much does the same work cost when it is sent the way pipelines usually send it (one call per job,
or one subagent per job), compared with one batched call in plain JSON and one OZ/1g call?

## Design

- Workload: the materials task family from the published benchmark (`bench/live/live11.py`), 16 jobs per seed,
  fresh records per seed, deterministic oracles. Seeds 3005, 3006, 3007.
- Models: `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-haiku-5-5`, through `claude -p`, default effort.
  OZ/1g is qualified at 32 and 64 jobs; 16 is outside the qualified cells, so an OZ/1g failure here is reported as
  a finding, not explained away.
- Arms, all on identical jobs, one model per run, concurrency 1 inside a run:
  - **H**: one OZ/1g call with 16 jobs.
  - **J**: one plain JSON call with 16 jobs (the 0.8-exec packet, the batched control).
  - **P**: 16 plain JSON calls, one job each (the same packet trimmed to that job and its one reference).
  - **S**: one orchestrator call with only the Agent tool, told to spawn one general-purpose subagent per job and
    reply in the plain JSON format. Spawns are counted from the event stream.
- Tokens: everything billed, summed from `modelUsage` (main loop plus subagents): uncached input, cache reads,
  cache writes, output including thinking. Cache reads are also shown as a separate column; no price weighting
  is applied. Smoke run (seed 2999, arm S, not counted): 16 spawns, 15/16 correct, 152k tokens; it also showed that
  the CLI's `usage` field covers only the last turn, so it is not used.
- Scoring: strict, nothing repaired. A job counts when its reply parses and the oracle accepts the value; a job
  reported as failed by the model does not count. Failed calls count in the cost.
- Metric: tokens per verified job, then median wall time per seed for the whole 16 jobs (P is summed over its 16
  sequential calls; S runs its subagents however Claude Code schedules them, which is reported as such).

## Gates

1. Attribution: savings are credited to OZ only where H beats J. The rest is credited to batching.
2. Expansion: if H's correct jobs are at least those of P and S on every model and H's tokens per verified job
   are lower, repeat the comparison at 64 jobs on Sonnet (H, J, P, S, seeds 3105 to 3107).
3. Anything else is published as measured, with the gate result stated.
