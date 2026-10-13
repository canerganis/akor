# Stage 1g Opus qualification (preregistered 2026-10-13)

Proposed separate, preregistered qualification: text H, parser oz1g-header, on claude-opus-5-5 (claude -p, pinned id, default effort), 64 jobs per call. Owner asked for it after the Claude-only release; Opus was never in the 1g plan.

Cells, concurrency 1, retry 0, manifests hashed before the first call:
1. Standard: 5 calls, data seeds 4005-4009 (fresh; generator and jobs as stage A), each paired with one 0.8-exec call on the same seed, call order shuffled per seed (bench/live/run1g.py with MODEL=opus N=64 SEEDS=4005-4009 BASE=4005,4006,4007,4008,4009). 10 calls.
2. Heterogeneous: P1-P5 rev 3 once each (bench/live/run1g_b.py MODEL=opus PACKETS=1,2,3,4,5 STOP=1). 5 calls. Runs only if cell 1 has no H failure.
Total at most 15 calls.

Gates (fixed now, not reinterpreted afterwards):
- Support: H 10/10 packets accepted and fully correct (5 standard + 5 heterogeneous). Any H failure: Opus not added; recorded as failed.
- Savings claim (separate from support): C_verified(H) <= 0.65 x C_requested(0.8-exec) on the 5 paired seeds, tokens = provider input incl. cache + output, thinking counted once; baseline failures counted in C_requested, not blocking. If support passes but this gate fails, Opus is listed as supported without a savings figure.
- Speed reported (api_ms per verified job vs per requested job), not a gate.
Result goes to README and OZ9 (supported list), docs/design/stage-1g-opus.md, raw data in bench/live/data/live27_*.

## Approvals

- Fable: APPROVE; record the output limit and resolved model id in the manifest (done: output_limit field; model id per call), report Opus thinking tokens per packet.
- Astra: approved as a separate preregistered qualification; savings from pooled totals across the five paired seeds (H tokens / verified jobs vs baseline tokens / 320 requested jobs), labelled benchmark token savings; support scoped to H, oz1g-header, N=64, the pinned model and tested effort.

## Result

Run 2026-10-13, all cells as preregistered (bench/live/data/live27_1g_opus_std.jsonl, live27_1g_opus_het.jsonl, manifests next to them).

- Support: PASS. H 10/10 packets accepted and fully correct (standard seeds 4005-4009: 5/5, 320/320; heterogeneous P1-P5 rev 3: 5/5, 320/320).
- Benchmark token savings (pooled over the five paired seeds): H 26,423 tokens / 320 verified jobs = 82.6 per job; 0.8-exec 46,176 tokens / 320 requested jobs = 144.3 per job; saving 42.8% (gate 35%): PASS. The 0.8-exec baseline was 4/5 fully correct (seed 4007: 63/64), reported, not blocking.
- Speed (reported): 216.8 ms per verified job against 284.3 ms per requested job; median call 14.0 s against 17.9 s.
- Money units (Sonnet price ratios, reported): 205.9 against 332.8 per job.
- Thinking tokens per packet: Opus standard 431 to 645 (mean 571), heterogeneous 301 to 1,936 (mean 870); Sonnet stage A mean 908, stage B mean 1,115.

Opus is added to the supported configurations: claude-opus-5-5, default effort, 64 jobs per call, text H, parser oz1g-header.
