# Step 2 pilot results (2026-10-22)

Plan: [pilot-plan.md](pilot-plan.md), frozen before the first counted call. Harness: `bench/live/pilot2.py`.
Report: `bench/live/pilot2_report.py`. Data: `bench/live/data/`, including `pilot2_sonnet64.jsonl`.

## Question

How much does the same work cost when it is sent the way pipelines usually send it (one call per job, or one
subagent per job), compared with one batched call in plain JSON and one OZ/1g call?

## Design

Materials extraction and classification jobs from the published benchmark (`bench/live/live11.py`), fresh records per
seed, deterministic oracles, strict scoring (nothing repaired). Four arms on identical jobs: one OZ/1g call, one plain
JSON call, one plain JSON call per job, one orchestrator call that spawns one subagent per job. Tokens are everything
billed, summed from `modelUsage` (uncached input, cache reads, cache writes, output including thinking). Failed calls
count in the cost. 16 jobs per seed on Sonnet 5.5, Opus 5.5 and Haiku 5.5 (seeds 3005 to 3007), then 64 jobs per seed
on Sonnet 5.5 (seeds 3105 to 3107).

Gate result: the preregistered expansion gate passed. At 16 jobs the OZ/1g call had at least as many correct jobs as
the per-job and subagent arms on every model, and fewer tokens per verified job, so the 64-job run was done.

## Results at 16 jobs (3 seeds, 48 jobs per cell)

| Model | Arm | Calls | Replies accepted | Correct jobs | Tokens | Cache reads | Tokens per requested job | Tokens per verified job | Median s per seed |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Sonnet 5.5 | OZ/1g, one call | 3 | 3/3 | 48/48 | 9,626 | 1,206 | 200.5 | 200.5 | 12.9 |
| Sonnet 5.5 | plain JSON, one call | 3 | 3/3 | 48/48 | 11,766 | 0 | 245.1 | 245.1 | 9.9 |
| Sonnet 5.5 | plain JSON, one call per job | 48 | 45/48 | 34/48 | 94,975 | 0 | 1,978.6 | 2,793.4 | 115.5 |
| Sonnet 5.5 | one subagent per job | 3 | 3/3 | 48/48 | 413,597 | 239,918 | 8,616.6 | 8,616.6 | 38.7 |
| Opus 5.5 | OZ/1g, one call | 3 | 3/3 | 48/48 | 9,436 | 1,206 | 196.6 | 196.6 | 9.4 |
| Opus 5.5 | plain JSON, one call | 3 | 3/3 | 48/48 | 11,193 | 0 | 233.2 | 233.2 | 11.4 |
| Opus 5.5 | plain JSON, one call per job | 48 | 32/48 | 25/48 | 93,429 | 0 | 1,946.4 | 3,737.2 | 115.6 |
| Opus 5.5 | one subagent per job | 3 | 3/3 | 48/48 | 395,855 | 204,288 | 8,247.0 | 8,247.0 | 50.0 |
| Haiku 5.5 | OZ/1g, one call | 3 | 3/3 | 48/48 | 13,070 | 1,206 | 272.3 | 272.3 | 12.3 |
| Haiku 5.5 | plain JSON, one call | 3 | 3/3 | 48/48 | 14,442 | 0 | 300.9 | 300.9 | 12.5 |
| Haiku 5.5 | plain JSON, one call per job | 48 | 48/48 | 31/48 | 107,608 | 0 | 2,241.8 | 3,471.2 | 115.1 |
| Haiku 5.5 | one subagent per job | 3 | 3/3 | 39/48 | 371,229 | 179,978 | 7,733.9 | 9,518.7 | 33.5 |

## Results at 64 jobs (Sonnet 5.5, 3 seeds, 192 jobs per cell)

| Arm | Calls | Replies accepted | Correct jobs | Tokens | Cache reads | Tokens per requested job | Tokens per verified job | Median s per seed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| OZ/1g, one call | 3 | 3/3 | 192/192 | 17,591 | 1,809 | 91.6 | 91.6 | 19.9 |
| plain JSON, one call | 3 | 3/3 | 192/192 | 29,018 | 0 | 151.1 | 151.1 | 20.8 |
| plain JSON, one call per job | 192 | 183/192 | 139/192 | 393,935 | 0 | 2,051.7 | 2,834.1 | 491.3 |
| one subagent per job | 3 | 3/3 | 188/192 | 1,491,032 | 794,114 | 7,765.8 | 7,931.0 | 105.1 |

Chart: [pilot_subagents.svg](../../assets/pilot_subagents.svg).

## What it shows

At 64 jobs on Sonnet 5.5, the OZ/1g call cost 91.6 tokens per verified job. One subagent per job cost 7,931.0, which
is 86.6 times more (7,931.0 / 91.6). One plain JSON call per job cost 2,834.1, which is 30.9 times more. Batched plain
JSON cost 151.1, which is 1.65 times more.

Time for the whole 64 jobs, median per seed: 19.9 s for OZ/1g, 20.8 s for batched JSON, 105.1 s for subagents (5.3
times slower than OZ/1g) and 491.3 s for per-job calls (24.7 times slower).

At 16 jobs the subagent arm cost 35.0 to 43.0 times more tokens per verified job than OZ/1g (Haiku 35.0, Opus 41.9,
Sonnet 43.0), and per-job calls cost 12.7 to 19.0 times more (Haiku 12.7, Sonnet 13.9, Opus 19.0). OZ/1g got 48/48 on
all three models.

Correctness: OZ/1g and batched JSON were fully correct in every cell. Per-job calls got 34/48, 25/48 and 31/48 at 16
jobs and 139/192 at 64 jobs. Subagents got 48/48 on Sonnet and Opus, 39/48 on Haiku and 188/192 at 64 jobs.

## Attribution

The large gaps against one call per job and one subagent per job are differences between execution strategies, mostly
from batching and orchestration overhead. They are not caused by the OZ language. Sending the jobs in one call instead
of many calls or many subagents removes repeated prompts, repeated reference material and orchestration turns,
whatever the format of the reply.

OZ's own contribution is only the gap to batched plain JSON, the control that already has the batching benefit:

| Setting | Plain JSON, one call | OZ/1g, one call | OZ saves |
|---|---:|---:|---:|
| 16 jobs, Sonnet 5.5 | 245.1 | 200.5 | about 18% |
| 16 jobs, Opus 5.5 | 233.2 | 196.6 | about 16% |
| 16 jobs, Haiku 5.5 | 300.9 | 272.3 | about 10% |
| 64 jobs, Sonnet 5.5 | 151.1 | 91.6 | about 39% |

Tokens per verified job; the saving is 1 minus OZ/1g over plain JSON. Median wall time did not separate the two
batched arms in a consistent direction at 16 jobs (Sonnet 12.9 s vs 9.9 s, Opus 9.4 s vs 11.4 s, Haiku 12.3 s vs
12.5 s), and at 64 jobs it was 19.9 s vs 20.8 s.

## Limits

1. One task family: materials extraction and classification with deterministic oracles. Nothing here says anything
   about other kinds of work.
2. Three seeds per cell.
3. 16 jobs is outside the qualified OZ/1g cells. Those 9 replies (3 models times 3 seeds) are experimental and are not
   added to the 91 qualified replies. All 9 parsed and were fully correct, but they are reported separately.
4. The per-job arm used plain JSON, not single-job OZ.
5. Most per-job failures were the right value with explanation prose appended, which the strict checker rejects.
   Per requested job (so failed jobs do not shrink the denominator) the per-job arm cost 1,978.6, 1,946.4 and 2,241.8
   tokens at 16 jobs and 2,051.7 at 64 jobs. Against OZ/1g that is 8.2 to 9.9 times at 16 jobs and 22.4 times at 64
   jobs, so the gap stays large with that effect removed (about 10x or more at 16 jobs for Sonnet and Opus, 8.2x for
   Haiku).
6. Subagent parallelism is decided by Claude Code, not by the harness. The orchestrator was told to spawn one subagent
   per job, and the wall time reflects however it scheduled them.
7. Per-job calls ran sequentially (concurrency 1), so their wall time is an upper bound. A parallel runner would be
   faster in wall time, with the same token cost.
8. Cache reads are counted at full weight. No price weighting is applied. Cache reads are shown in their own column.
9. The CLI `usage` field covers only the last turn, so it is not used. All tokens come from `modelUsage`, which covers
   the whole call including subagents. For the 162 single-call records both agree.
