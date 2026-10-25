# Owner decisions for the oz map replication (2026-10-24)

Recorded by the driver (Claude Opus 5.5) from the owner's own words in chat.

1. Launch guard. Claude weekly usage was 62% at the start, above the record's 55% launch threshold, which applied
   again once the pilot report was written (07da2df). Asked whether to suspend it, the owner chose "Serbest, devam"
   (free, continue). Effect: the 55% launch and abort threshold does not apply to the replication until its result
   report is written. The quota handoff rule at 99% Claude weekly and the Codex stop line (primary used_percent >= 80)
   still apply.
2. Scope. "clean replicationu başlat" (start the clean replication): the replication named in
   docs/design/ozmap-2026-10-24/pilot-result.md, "What follows": isolated CODEX_HOME, per-arm budgets sized for the
   no-rule case, the bootstrap gold-error rule scoped to rule-shaped tasks, cache-inclusion evidence that does not
   depend on a lucky cache hit, and operations written independently of the language designer.
3. Closure stop (A4.14.3). Closure round 2 ended with two A4.14.2 blockers (O3: probe marker removed before the disclosure record is written; N1: a stopped telemetry cell gets no validity disposition), down from 25 in build round 3. A4.14.3 stops the workflow for the owner. The owner had said "En mantıklı şekilde hallet işte işleri" (handle things in the most sensible way) and earlier "Sorunları çöz" (solve the problems). The driver reads this as the owner's decision: fix exactly these two blockers, then a fresh Opus verifies only them with reproducing tests and the full suite; no new review round, no other change. Any new blocker found by that check stops the workflow again.
