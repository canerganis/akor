# Stage 1g Haiku paired savings run (preregistered 2026-10-13)

Owner request. Same design as stage-1g-opus.md and stage-1g-fable-paired.md, applied to claude-haiku-5-5 (claude -p, pinned id, default effort), 64 jobs per call. Haiku's support is already qualified; this run measures paired savings only. An earlier unpaired comparison suggested about 25%, below the 35% gate, so the measured figure is published whatever it is, with the gate result stated.

- 5 AKOR calls on fresh data seeds 6005-6009, each paired with one plain JSON call on the same seed, order shuffled per seed, concurrency 1, retry 0, manifest hashed before the first call (bench/live/run1g.py MODEL=haiku N=64 SEEDS=6005-6009 BASE=6005,6006,6007,6008,6009). 10 calls.
- Reported: pooled tokens per verified job (AKOR) against tokens per requested job (plain JSON), gate 35%; speed and money units.

## Result

Run 2026-10-13 as preregistered (bench/live/data/live29_1g_haiku_paired.jsonl and its manifest).

- AKOR 5/5 accepted and fully correct (320/320); plain JSON 5/5 (320/320).
- Benchmark token savings (pooled): AKOR 45,473 tokens / 320 verified jobs = 142.1 per job; plain JSON 65,700 / 320 = 205.3; saving 30.8%, below the 35% gate: FAIL. Haiku thinks heavily on both formats (mean output 5,747 against 6,543 tokens per call), so most of the saving comes from input.
- Speed (reported): 293.1 ms per verified job against 320.7; median call 18.5 s against 21.0 s. Money units: 505.7 against 640.0 per job.
- Owner decision: Haiku is shown in the savings table with its measured 30.8%, labelled as below the other three models, with the reason (long thinking in both formats).
