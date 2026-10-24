# oz map kill pilot: result (2026-10-24)

Freeze 88a82e2 (54 files, dry output b66a0c52), signed by Astra (sign-offs 3 to 5) and Opus. Run
`bench/ozmap/runs/live-bb76c7b0f329`, scored offline against gold by `bench/ozmap/score.py` (report.md and
report.json in the run directory). Codex: gpt-6.1-sol, effort high, codex-cli 0.160.0. Sonnet: claude-sonnet-5-5,
Claude Code 2.1.306. 4 scripted producers x 64 jobs per wave, concurrency 4, batches of at most 64.

## Verdict under the preregistered rules

**Invalid: efficiency is not evaluable (validity failed). No headline is permitted.**

Validity failed for three recorded reasons:
1. One Codex BoolQ arm A call ran a shell command that read a plugin file from the owner's Codex install
   (`~/.codex/plugins/.../using-superpowers/SKILL.md`). The leakage detector caught it, the call's 64 answers were
   refused (74 BoolQ A jobs unresolved), and the run manifest cannot attest that nothing outside the prompt was read.
   The file is not gold or pilot material; the rule treats any tool use as a validity failure anyway.
2. The BoolQ bootstrap answered 5 of its 64 jobs wrongly against gold, and the record makes any bootstrap gold error
   invalidate efficiency. The rule was written for rule-shaped tasks; on BoolQ, ordinary model errors trigger it.
3. Several Codex calls reported cached input above zero, while the paired telemetry could not certify cache
   inclusion (the cache hit on the identical telemetry pair was 0 both times). Under sign-off 5 those calls are
   "usage unverified", so every Codex cell except materials cold A is evidence-incomplete for token claims.

Safety passed: no wrong rule-origin answer was accepted.

## What was measured (gold scored, all reported regardless of the verdict)

| Cell | Correct / 256 | Rule coverage | Tokens per correct job | Makespan s | Correct per minute |
|---|---:|---:|---:|---:|---:|
| Codex materials cold A (ordinary) | 256 | 0 | 584.4 | 52.0 | 295 |
| Codex materials cold B (rules, local fallback) | 256 | 0.75 | 641.0 | 130.5 | 118 |
| Codex materials cold C (rules, pooled fallback) | 256 | 0.75 | 292.1 | 117.3 | 131 |
| Codex materials warm A | 256 | 0 | 583.3 | 54.8 | 280 |
| Codex materials warm C | 256 | 1.00 | 131.5 | 33.4 | 459 |
| Sonnet materials cold A | 256 | 0 | 252.0 | 44.8 | 343 |
| Sonnet materials cold B | 255 | 0 | 284.5 | 86.0 | 178 |
| Sonnet materials cold C | 256 | 0 | 276.8 | 91.3 | 168 |
| Sonnet materials warm A | 252 | 0 | 264.6 | 49.0 | 309 |
| Sonnet materials warm C | 63 (192 unresolved) | 0 | 260.2 | 42.3 | 89 |
| Codex BoolQ cold A | 168 (74 unresolved) | 0 | 1291.2 | 81.4 | 124 |
| Codex BoolQ cold B | 223 | 0 | 925.0 | 134.3 | 100 |
| Codex BoolQ cold C | 225 | 0 | 783.0 | 128.5 | 105 |

Reading, with the caveats above:
1. **Codex learned rules for all four materials operations** (e, b, m, v) in one bootstrap call, all four passed
   admission on 64 independent labeled cases each, and the rules then answered 192 cold and 256 warm jobs per arm
   with zero errors against gold. Warm C needed one model call for 32 blind audits instead of four calls.
2. **Warm, the mechanism does what it was built for:** 131.5 vs 583.3 tokens per correct job (4.4x fewer) and 33.4 vs
   54.8 s (1.6x faster, 459 vs 280 correct jobs per minute), with equal correctness. These two numbers are the
   pilot's main finding; formally they are unavailable as a claim because of item 3 above.
3. **Cold, rules halve the tokens but cost time:** 292 vs 584 tokens per correct job, but 117 vs 52 s, because the
   bootstrap must finish before rule jobs and residuals run. Pooling helped: C used 2.2x fewer tokens than B.
4. **Sonnet proposed no rule** ("none" for all four operations), so its B and C arms are ordinary batching plus the
   bootstrap overhead. Sonnet warm C left 192 jobs unresolved: its frozen budget gave warm C one call, which assumed
   rules would cover the wave. That allocation was a design error, recorded here rather than repaired.
5. **BoolQ:** Codex correctly proposed no rule. C and B were not slower per token than A, but A's numbers are
   distorted by the refused leaking call, so the BoolQ comparison says little. The time cost of the bootstrap shows
   (128 vs 81 s).

## An unresolved observation

The four rules Codex proposed are **byte-identical to the worked ASTs in Astra's specification**
(docs/design/ozmap-2026-10-24/oz-rule-1-spec.md), which were hidden from the model. Checked: the bootstrap call's
event stream has no tool, command or file item (only CLI notices, one reply and 1,249 reasoning tokens); it ran in an
empty directory outside the repo; the spec excerpt shown to the model contains no worked AST and no hint such as the
negative-uncertainty guard; the owner's Codex memory files do not mention oz-rule. The most likely explanation is
that the language is narrow enough that a model of the same family converges on the designer's minimal program, but
this run cannot rule out another channel. Any claim about "learning" must say so, and a replication with
independently written operations is needed before the rule-learning result is taken at face value.

## Preparation cost

8 Codex telemetry calls in four run directories, 237,874 tokens in total (listed in report.md), plus the dry runs at
zero external calls. Telemetry attempts 1 to 3 led to three fixes signed by Astra: recognized CLI notices are not
leakage, a fixed numbered working directory, and the zero-cache rule.

## What follows

- The mechanism works where it applies: on Codex, learned rules with zero errors cut warm cost 4.4x and time 1.6x.
  This is the shareable direction, but only after a clean, valid replication.
- Fixes for a replication: isolate Codex from the owner's plugins and skills (a dedicated CODEX_HOME), size
  each arm's budget for the no-rule case, scope the bootstrap gold-error rule to rule-shaped tasks, and obtain
  cache-inclusion evidence that does not depend on a lucky cache hit.
- Test rule learning on operations written independently of the language designer, and on Sonnet with a prompt
  that elicits rules (Sonnet declined every operation here).
