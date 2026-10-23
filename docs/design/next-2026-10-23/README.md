# Next work after steps 1 to 4 (Astra and Opus 5.5, 2026-10-23)

Signed order: (1) zero-call trace analysis to find the next bottleneck, preregistered in
[03](03-astra-accept-and-step1-prereg.md) before any number was read; (2) narrow packaging of the proven manual path,
proven on the fixture route at zero model tokens; (3) one committed use case qualified before promotion, testing what
the caller-cost study left open (a cheaper worker model, references too large for the caller, or a full caller
context), recommended `repair-handoff-20`, confirmed by the owner before any allocation; (4) step 5 only against a
bottleneck step 1 names. Implementation goes to Claude subagents (Codex cannot write this repo), so "zero paid
experiments" still spends quota. Today: stop new work at 46% weekly (hard stop 49%); step 2 starts only if step 1
ends below 44%. No boundary study, importer, receipt redesign, replanner or MCP without a demonstrated need.

Status 2026-10-23: step 1 done (no demonstrated actionable bottleneck, step1-results.md); step 2 done (oz_manual,
962a87b, signed by Opus after review 07; known read limits documented in USAGE.md). Follow-ups from review 07, not
blocking: `status` should use the flow's injectable clock for `deadline_remaining_seconds`; the facade should stop
importing the private `oz_do._accounting`. Step 3 (one committed use case qualified) needs the owner to confirm the use
case and allocation first; recommended: `repair-handoff-20`, testing what the caller-cost study left open.

2026-10-24: owner raised the weekly line to 60% (admission stop 58%). The H attribution candidate ([08](08-astra-h-attribution.md),
[09](09-opus-zero-cost-bound.md), [10](10-astra-closes-and-next.md)) is closed with zero model calls: even at H's hard
upper bound of 1,590 billed tokens per call, H is 20.3% of the prespecified gate cell (O1 all stages, n=4, clean),
under the 25% threshold, so a shorter H cannot be a bottleneck fix. Next proposed by Astra: context offloading with
large references and a full caller, on code review as the first new task family.
