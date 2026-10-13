# Stage 1g Fable paired savings run (preregistered 2026-10-13)

Owner request. Same design Astra and Fable approved for Opus (stage-1g-opus.md), applied to claude-fable-5-1 (claude -p, pinned id, default effort), 64 jobs per call. Fable's support is already qualified (release scope); this run only measures paired savings.

- Standard: 5 calls, fresh data seeds 5005-5009, each paired with one plain JSON (0.8-exec) call on the same seed, call order shuffled per seed, concurrency 1, retry 0, manifest hashed before the first call (bench/live/run1g.py MODEL=fable N=64 SEEDS=5005-5009 BASE=5005,5006,5007,5008,5009). 10 calls.
- Savings gate: pooled C_verified(H) <= 0.65 x C_requested(plain JSON), billed tokens incl. cache and output, thinking counted once; baseline failures count in C_requested and do not block. Label: benchmark token savings.
- An H failure here does not remove Fable's support by itself; it is reported and goes to Astra and Fable.

## Result

(pending)
