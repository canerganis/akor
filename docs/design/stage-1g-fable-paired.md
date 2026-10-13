# Stage 1g Fable paired savings run (preregistered 2026-10-13)

Owner request. Same design Astra and Fable approved for Opus (stage-1g-opus.md), applied to claude-fable-5-1 (claude -p, pinned id, default effort), 64 jobs per call. Fable's support is already qualified (release scope); this run only measures paired savings.

- Standard: 5 calls, fresh data seeds 5005-5009, each paired with one plain JSON (0.8-exec) call on the same seed, call order shuffled per seed, concurrency 1, retry 0, manifest hashed before the first call (bench/live/run1g.py MODEL=fable N=64 SEEDS=5005-5009 BASE=5005,5006,5007,5008,5009). 10 calls.
- Savings gate: pooled C_verified(H) <= 0.65 x C_requested(plain JSON), billed tokens incl. cache and output, thinking counted once; baseline failures count in C_requested and do not block. Label: benchmark token savings.
- An H failure here does not remove Fable's support by itself; it is reported and goes to Astra and Fable.

## Result

Run 2026-10-13 as preregistered (bench/live/data/live28_1g_fable_paired.jsonl and its manifest).

- H 5/5 accepted and fully correct (320/320); plain JSON 5/5 (320/320).
- Benchmark token savings (pooled): H 27,811 tokens / 320 verified jobs = 86.9 per job; plain JSON 46,822 / 320 requested = 146.3; saving 40.6% (gate 35%): PASS.
- Speed (reported): 314.0 ms per verified job against 375.8; median call 18.7 s against 23.4 s.
- Money units (reported): 227.7 against 342.8 per job.
