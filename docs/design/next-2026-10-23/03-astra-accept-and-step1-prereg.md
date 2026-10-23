ACCEPT all five changes, including executor ownership, quota gates, scope exclusions, and the owner’s use-case approval before allocation.

Step 1 preregistration, frozen here before inspecting usage values. Repository files were inspected only for paths and instrumentation. This checkout is read-only, so this registration is recorded in chat.

1. **Corpus.** Include the existing files matching these selectors, with a path and SHA-256 manifest frozen before parsing:
   - `bench/live/data/pilot2_*.jsonl` and `pilot2q_*.jsonl`: batching, orchestration, and single-job controls.
   - `bench/live/data/pilot_k*.jsonl`: initial handoff and caller-cost, including `pilot_k2.jsonl`; include their stored caller transcripts and worker ledgers for attribution.
   - `bench/live/data/live{22,23,24,25,26,27,28,29}_*.jsonl`: OZ/1g protocol and model comparisons.
   - `bench/step4/live{1,2,3}/calls-*.jsonl`: clean, interrupted, and stale execution.
   - `bench/o1/live1/calls-*.jsonl`: model-needed repair workflow.
   - `bench/probe/boundary-evidence/calls/*/envelope.json` and `bench/step4/adopt-qual/calls/*/envelope.json`: historical boundary and qualification controls only.

   Associated manifests, requests, metadata, ledgers, and reports supply provenance and timing, never duplicate observations. Smoke/calibration runs remain a separate descriptive stratum. Exclude fixtures and other live generations. Retain failed calls and missing-accounting records.

2. **Frozen accounting.** Use `modelUsage`, across every reported model. Per call: system H cache write, H cache read, packet input, visible output, thinking, plus explicitly unattributed residuals. Attribute H only where evidence permits. Denominator: input + cache write + cache read + output, each token counted once at full weight. Thinking is an output subset, never added again; missing or inseparable counters remain unknown. Monetary cost is separate.

   Per run: failed and resent calls, check-driven work, and measured caller overhead. These are overlapping attribution tags, not additive token categories. Deduplicate aggregate and child usage.

   Time: end-to-end wall time partitioned into active critical-path work, avoidable waiting, and unresolved time. Do not sum overlapping calls or infer waiting from API latency alone.

3. **Actionable rule.** Within a prespecified workload/model/size/arm/scenario cell, a category must account for **at least 25% of billed tokens or elapsed time**, on a model-needed job, with one named variable plausibly able to move it. Report every cell; no pooled historical percentage can qualify a bottleneck. Unknown attribution cannot establish qualification. Effort qualifies only through thinking; scheduling only through avoidable waiting.

4. **Required output.** Produce the frozen manifest, accounting-completeness table, per-call and per-run breakdowns with denominators and source locators, and a host-computable scan flagging every model op whose check recomputes its full answer. First audit the supplied O1 thinking range of 584–1,186 tokens per size-4 call and approximately 2,000 H tokens per call as prior claims. Finish with all qualifying categories and their single-variable candidates, or **“no demonstrated actionable bottleneck.”** No new model calls or reopening the settled same-model caller comparison.
