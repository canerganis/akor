# Stage 1g Haiku paired savings run (preregistered 2026-10-13)

Owner request. Same design as stage-1g-opus.md and stage-1g-fable-paired.md, applied to claude-haiku-5-5 (claude -p, pinned id, default effort), 64 jobs per call. Haiku's support is already qualified; this run measures paired savings only. An earlier unpaired comparison suggested about 25%, below the 35% gate, so the measured figure is published whatever it is, with the gate result stated.

- 5 AKOR calls on fresh data seeds 6005-6009, each paired with one plain JSON call on the same seed, order shuffled per seed, concurrency 1, retry 0, manifest hashed before the first call (bench/live/run1g.py MODEL=haiku N=64 SEEDS=6005-6009 BASE=6005,6006,6007,6008,6009). 10 calls.
- Reported: pooled tokens per verified job (AKOR) against tokens per requested job (plain JSON), gate 35%; speed and money units.

## Result

(pending)
