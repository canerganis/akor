# Step 2 size gates at 1, 4 and 16 jobs (frozen before the first counted call, 2026-10-23)

Required by the foundation record (steps table, "Complete step 2"): preregistered size gates at 1, 4 and 16 jobs for
the cells `oz do` is meant to use.

Cells: `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-haiku-5-5`, each at 1, 4 and 16 jobs per call, through
`claude -p` at default effort, Claude CLI 2.1.306 (recorded in every manifest, foundation record C1).
Wire: OZ/1g, system text H, parser profile oz1g-header, unchanged.
Workload: the standard materials workload (`bench/live/run1g.py`, ARM=H, BASE empty), fresh records per seed,
deterministic oracles. Seeds 4005 to 4014 (10 calls per cell). Concurrency 1, no reply retry.

Gate per cell: 10 of 10 replies accepted by the product parser and every job correct. A cell stops at its first
failure (STOP=1), because one failure already decides it.

Scope of a pass: the cell is qualified for the standard workload class only, at the recorded CLI version. The
heterogeneous stress packets used for the 64-job cells do not exist at these sizes, so a pass here is narrower than
the existing 64-job qualification and is labeled that way. A fail makes that size unsupported for that model; it
does not permit weaker checks or filler jobs.

Earlier exploratory evidence (pilot arm Q, one OZ/1g call per job, not a qualification): Opus 41/48 replies accepted,
every rejection a reasoning line before the header. It is not counted here.

## Addendum after the first run (2026-10-23, before any rerun call)

All nine cells passed 10/10 (data: `bench/live/data/gate_{model}_{n}.jsonl`). Review found a coverage defect in the
size-1 cells: `jobs('materials', 1)` is always the first operation (field extraction), so the size-1 gate never
exercised the other three operations. Pilot arm Q (exploratory) showed Opus failing exactly on those operations.
The size-1 result is therefore void as a qualification. Sizes 4 and 16 cover all four operations and stand.

Rerun for size 1: `bench/live/pilot2.py` arm Q with N=4, seeds 4105 to 4107, so each seed sends four single-job
OZ/1g calls, one per operation: 12 calls per model, every operation three times. Gate: 12 of 12 replies accepted and
every job correct. Same models, CLI 2.1.306, default effort, concurrency 1.
