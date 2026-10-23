# Brainstorm 2026-10-24: `oz map` with guarded rules (Astra A, Astra B, Opus A, Opus B)

Participants: Astra A (language owner) and Astra B (devil's advocate), both gpt-6-astra through `codex exec`;
Opus A (orchestration and attention) and Opus B (efficiency and systems), both Claude Opus 5.5. Research: Sonnet 5.5
(prior art, two passes), Luna (gpt-6-luna, web search), Haiku 5.5 (repo scan). Driver: Claude Opus 5.5.
Effort: Astra round 1 xhigh, everything after it high.

Owner's goal: a next step that is clearly different from prior work, makes orchestration between agents easier, gives
more verified work per token and per second than our 91.6 tokens / 20 s result, and is worth sharing.

## Outcome

Build `oz map` (one line: input glob, job template, checks, output) over optional guarded whole-job rules. With
`--learn`, the first batched call also proposes a small rule per operation in a bounded JSON AST that returns a value
or abstains. The host admits it only on an independent labeled set, runs it without the model on later jobs, audits a
blind seeded sample, quarantines it on any disagreement, and sends everything the rule abstains on, pooled across
producers, through ordinary OZ/1g calls. The OZ/1g wire does not change.

What is not new, and the record says so: compiling LLM work into code (GenCache, arXiv 2607.13407), batching many rows
into one prompt (batch prompting, Sema), validated map operators (DocETL), optimized semantic operators (LOTUS). What
the record claims is the combination inside an agent runtime: several producers on one queue, per-job host checks,
pooled residuals, and complete cost accounting with compilation charged. Global novelty is not established.

## How it got there

1. Round 1 ([01-*](.)): three of four proposals converged on guarded rules plus batched fallback; Opus A proposed the
   `oz map` surface. Luna found GenCache, which already covers "compile once", so every participant narrowed its
   novelty claim.
2. Round 2 ([02-*](.)): all four accepted `oz map` over guarded rules. Partial programs with named semantic questions
   were deferred; agreement with the model's own answers was dropped as an admission test.
3. Round 3: Astra B settled the open choices ([03-astra-B-decisions.md](03-astra-B-decisions.md)); Opus A mapped
   reuse against the code ([03-opus-A-reuse.md](03-opus-A-reuse.md)): `oz do`, leases, settlement, checks and the memo
   store fit with under 15 changed core lines; the fenced workspace coordinator, the DAG executor and host-only routing
   do not fit and are not reused. About 700 new lines, mostly new modules.
4. Astra A drafted the record; Opus B raised two blockers ([04-opus-B-sign.md](04-opus-B-sign.md)): a Codex-only
   pilot cannot beat the published Sonnet result because Codex calls carry a 24k to 25k token floor, and a cold
   makespan gate fails by construction. Both were integrated into the final record
   ([05-joint-record.md](05-joint-record.md)).

## Kill pilot (frozen in the record)

Seed 20261024. 256 fresh materials jobs and 256 BoolQ development examples (the task that is not rule-shaped), four
scripted producers, concurrency four. Arms: A ordinary pooled map, B rules with producer-local fallback, C rules with
pooled fallback. A Sonnet 5.5 materials cell (A and C, cold and warm waves) is the only one compared with 91.6 / 20 s.
Budget: 50 physical calls (Codex 37, Sonnet 13, about 70k Sonnet tokens, a guess), abort Claude launches at 55% weekly.

Kills, in order: any wrong rule answer released as accepted; leakage or incomplete accounting; cold tokens per correct
materials job not at least 25% lower than A on each backend, or warm C above 0.9x A's makespan or 0.5x its tokens; any
BoolQ gold error added or more than 10% BoolQ overhead; pooling not cheaper than B.

## Remaining disagreements

Astra A rejected Opus B's floor-adjusted BoolQ gate (one-job telemetry cannot identify a fixed floor) and the 37-call
global cap (the Sonnet cell adds 13). Opus B's signature is conditional on blockers 1 and 2 as integrated.

## Files

`00-pack.md` question and evidence; `research-*.md` research notes; `01` to `05` rounds verbatim; `r*-common.md`,
`r3-*.md` the instructions each round received; `api-skeleton.md` the module signatures given to Astra, who cannot
read the repo from the Codex sandbox.
