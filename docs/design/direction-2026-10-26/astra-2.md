**Decision: AKOR becomes a minimal-call executor with verified delivery.** The language serves that executor; reducing total work takes priority over preserving its current structure.

- **Change:** Cold repair requests all four core–adapter pairs together in one call. Joint generation does not imply joint trust: the host checks cores, then adapters against those cores, before accepting the package. Split calls only when generation genuinely requires an intervening external result.
- **Revision:** Request only A’s changed pair in one call; retain verified B–D. Recheck affected dependencies and the final package. Direct already does selective revision, so reuse alone is no advantage.
- **Reduce overhead:** Send shared rules and source context once; request only required artifacts. No model planning, narration, or verification claims. Repair only failed functions and revalidate their dependants.
- **Keep:** Independent A/I/H checks, patch and provenance validation, strict parsing, bounded retries, resume, dependency-aware invalidation, and complete usage accounting. Keep OZ/1g available for workloads where batching earns its cost.
- **Drop:** Mandatory core→adapter model round trips, graph-node-per-call thinking, batch waiting on this small workload, and further rule-learning or language expansion before this gate passes.

**Fusion removes the demonstrated penalty; it does not guarantee superiority.** Beating direct still requires a smaller sufficient request/response and lower host overhead. That remains an experimental hypothesis.

**Rerun acceptance:** Freeze the implementation; use the same runner, evaluator, model/settings, inputs, reversed-order pairs, five-minute deadline, and combined **16-launch / 150,000-token** caps. Preserve each arm’s own revision state. Require all eight deliveries verified on time, complete usage, and AKOR/direct **below 1.00 for both tokens and measured delivery time in each stage in each pair**. Count retries, reasoning and cache categories without double counting. No cherry-picking. Passing supports this workload only; another loss means retain the direct execution path and abandon the superiority claim here.

**README: the unconditional headline does not stand.** Replace it with: **“A compact protocol and runtime for verified agent work.”** Remove blanket promises such as “fewer tokens on every call.” Keep historical 31×/24× and batched-format savings explicitly scoped to their original benchmarks, and prominently disclose this direct-workflow loss. This result does not invalidate those historical measurements.

One correction: [raw rows](../../../bench/o1/cmp-live1/s1-compare.json) give **1.60× cold time using mean paired ratios**, not 1.65×; the ratio of summed times is 1.61×. The decision is unchanged. The runner also excludes final independent evaluation from its timing, so label that metric accurately.

Read-only review completed; no edits or live calls.


