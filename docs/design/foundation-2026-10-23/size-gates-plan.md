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
