# Round 3, Opus B: sign with two blockers

I withdraw two positions: the relative error criterion (zero rule-origin errors stands) and my "revise" slot, which is adaptive search. Build steps 2 to 6 may start now. The blockers must be in the record before the pilot freeze.

## BLOCKER 1: Codex-only cannot answer the owner's goal

On these materials jobs Codex costs 417 to 455 tokens per job at 64 per call (bench/codex_kit, codex_kit_1g), and 24k to 25k of each call is a fixed floor. A 50% Codex win still lands near 220, a regression next to the README's 91.6.

Add to section 4:

> Add one Sonnet 5.5 cell on `claude -p` for materials. It runs arms A and C with the same four producers at width 4, covering the cold wave and the warm wave. It uses 13 calls: A 8, C 3, reserve 2. That is about 70k tokens (guess, from 5.9k measured per 64-job call). Reserve the calls through `oz_quota` and abort at 55% Claude weekly. Only this cell is compared with 91.6 tokens / 20 s.

## BLOCKER 2: the cold makespan gate fails by construction

At width 4, A finishes in one call time. Cold C needs the bootstrap call and then the residual call, two sequential call times, about 2x A on either backend.

Replace kill 3:

> **Materials:** C preserves correctness and cuts cold all-in tokens per gold-correct job by at least 25% versus A. Cold makespan is reported, not gated. After admission, each producer submits 64 more fresh jobs (warm wave: A 4 calls, C 1 call). C's warm makespan must be at most 0.9x A's, and its warm tokens per correct job at most 0.5x A's.

Section 4 cap: "37 physical calls".

## The 25% threshold

Keep it. On either backend it means C saved at least one of A's four calls; on Sonnet that needs rules covering about half of the 192 later jobs (guess).

## SHOULD-FIX 1: the BoolQ gate is toothless on Codex

On Codex, 91% of each call is floor, so the 10% gate leaves about 10k tokens of slack.

Replace kill 4:

> **BoolQ:** C adds no gold errors and at most 10% overhead versus A in both cold all-in tokens and floor-adjusted tokens. Floor-adjusted means tokens minus calls times F. F is the telemetry call: the same instructions with one job.

## SHOULD-FIX 2: the fused bootstrap is sound with three limits

Replace the bootstrap sentence in section 3:

> The shared bootstrap answers 16 jobs per producer, with one "rule or none" slot per operation and each AST capped at 2 KB. Its answers are scored against gold and against A's answers on the same 64 jobs. A gold error or a disagreement with A caused by the slot makes the efficiency result unvalidated.

Why: a single rule lets one of four operations veto the rest, the slot may shift answers, and the cap bounds decode time.

Verdict: SIGN once both BLOCKER replacements are adopted.
