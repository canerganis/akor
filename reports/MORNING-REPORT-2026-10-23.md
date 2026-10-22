# Morning report, 2026-10-23

Branch `oz-0.9`, nothing pushed, nothing posted. Tests: 449 passing. Claude weekly quota at 33% when this was written
(stop line 49%).

## The three overnight goals

1. **Shareable result: done.** Same jobs, four ways, preregistered, strict oracles, all billed tokens
   ([pilot-results.md](../docs/design/brainstorm-2026-10-22/pilot-results.md), chart `docs/assets/pilot_subagents.svg`,
   LinkedIn draft `docs/social/linkedin_pilot.md`). Sonnet 5.5, 64 jobs: one AKOR call 91.6 tokens per verified job,
   192/192, 20 s; one subagent per job 7,931, 188/192, 105 s; batched plain JSON 151.1. Most of the gap is batching and
   orchestration; AKOR's own format adds about 39% over batching at 64 jobs (10% to 18% at 16).
2. **Signed foundation record: done.** Astra and Opus 5.5 wrote it in four rounds, every round kept
   ([foundation-2026-10-23](../docs/design/foundation-2026-10-23/README.md)). One question stays open (O3: what a Claude
   CLI update requires), with the experiment that decides it.
3. **Step 3 code: done.** Lossless values (`12.50` stays `12.50`), opt-in per-job acceptance profile with checks,
   quarantine, fencing, a durable dispatch journal and recovery. An independent review found five bugs in the new path,
   all reproduced, fixed with tests first. The default path is unchanged.

## Also done, all preregistered

| What | Result |
|---|---|
| Size gates at 1, 4, 16 jobs | Sonnet and Haiku pass all; Opus fails at 1 job (writes a reasoning line before the header). A first size-1 run was voided because it covered one operation only. |
| Haiku `--effort medium` on OZ/1g | Fails: 304/320 and more tokens per verified job. Default stays. |
| One OZ/1g call per job | ~2,400 tokens per job in any format; batching is the lever. |
| `oz do` (one-call fan-out) | Built; live 16/16 in both profiles. |
| Arm K, caller agent with `oz do` | 9 to 10x cheaper than one subagent per job; 4 to 5x dearer than the caller doing the work inline. |
| Caller-cost experiment (Astra + Opus plan, 48 runs) | Same-model `oz do` does not beat inline work on tokens, even with file inputs or 4 KB references. USAGE now says when it pays. |

## Mistakes caught and corrected on the record
- `claude -p` `usage` covers only the last turn; all tokens now come from `modelUsage` (adapter fixed).
- Two harness scoring bugs (wrong seed's records); stored replies re-judged, no reply changed; a regression test pins it.
- The voided size-1 gate (coverage), and an over-strong test name in step 3.

## Decisions for you
1. **LinkedIn post:** draft at `docs/social/linkedin_pilot.md`, chart `docs/assets/pilot_subagents.svg`. Post only if you approve.
2. **Push:** many commits since `main`. The new raw transcripts under `bench/live/data/pilot_k2/` contain local Windows
   paths with your user name (118 files). Redact before pushing, or keep as raw evidence?
3. **Next step:** step 4, the 20-step executor, needs a recorded real workflow to judge it. Its design was started
   tonight if quota allowed (see HANDOFF.md).
