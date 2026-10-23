# Brainstorm 2026-10-24: the next AKOR, clearly different from prior work

Participants: Astra A and Astra B (gpt-6-astra, Codex), Opus A and Opus B (Claude Opus 5.5). Research by Sonnet 5.5
(prior art, web), Luna (gpt-6-luna, web) and Haiku 5.5 (repo scan). Driver and synthesis: Claude (Opus 5.5).

## Owner's goal (2026-10-24, translated)

Design a next step that is different from what was done before, makes orchestration between agents easier, gives
maximum work for minimum tokens, gets more out of a call than our previous results, and gets attention.

## Constraints

1. No API key, no direct API adapter: only authenticated `claude -p` and `codex exec`.
2. Standard-library Python core. Branch `oz-0.9`, no push without owner approval.
3. Every claim is measured preregistered, billed tokens, hidden reasoning and failed calls counted, nothing repaired.
4. Claude weekly quota hard stop at 60% (46% now). Codex at 8%.
5. Astra owns the language/wire; Claude implements and measures.

## What we have measured (all on materials extraction/classification jobs with deterministic oracles)

Tokens per verified job, 64 jobs, Sonnet 5.5, 3 seeds (docs/design/brainstorm-2026-10-22/pilot-results.md):

| Strategy | Correct | Tokens / verified job | Median time |
|---|---:|---:|---:|
| one subagent per job | 188/192 | 7,931 | 105 s |
| one plain JSON call per job | 139/192 | 2,834 | 491 s, sequential |
| one plain JSON call, all jobs | 192/192 | 151.1 | 21 s |
| one AKOR (OZ/1g) call, all jobs | 192/192 | 91.6 | 20 s |

Other facts:
- Format alone vs batched JSON: 41% to 43% (Sonnet, Opus, Fable), 31% (Haiku). Haiku cost is dominated by hidden
  reasoning (about 5,700 output tokens per 64-job call vs about 2,200 for Sonnet), which the packet does not shrink.
- Per call fixed cost dominates single-job calls: about 2,400 tokens per one-job call in either format.
- Arm K: a caller agent handing 64 jobs to `oz do` costs 798.7 per verified job vs 7,931 for subagent-per-job, but
  151.1 when the caller does the work inline in one reply. 81% to 89% of K's tokens are the caller rewriting jobs
  and rereading its context across tool turns. Caller-cost follow-up: same result with files and 4 KB references.
- Prompt cache: on OZ/1g calls about 2.7k of 3.4k input is cache write every call; little reuse across calls.
- Runtime already has: SQLite inbox with leases, per-job acceptance and selective retry, memo store with compute keys
  and freshness, model-free routing for reads/tests/status, a 20-step DAG executor with checkpoints and resume
  (O1 passed: 5 scenarios incl. hard kills, stale input, memo hits at 0 model tokens). See research-haiku.md.
- Reach so far: repo public since 2026-10-13, about 1 star, posts in 5 X communities with tens of views.

## Ideas already on the table (from the owner chat, not yet agreed)

1. Compile once, run without the model: the model writes a reusable rule (preferably in a small safe rule language
   the host interprets, not arbitrary Python), the host verifies it on examples and runs it on all later jobs;
   unresolved jobs fall back to the model; random samples are cross-checked. Risk: our benchmark tasks are exactly
   rule-shaped, so gains there may be inflated; needs a fuzzy task too.
2. Parallel batches over the existing lease model.
3. Streaming acceptance: deliver each record as it arrives so downstream agents start early.
4. Head-to-head benchmark against prior art (naive batch prompting, TOON, LLMLingua) on public datasets, not only ours.
5. Cache-aware packet layout.

## Question for this brainstorm

What single direction (or tightly coupled pair) should AKOR build next so that it (a) is clearly not "batch
prompting", (b) makes cross-agent orchestration easier for a user in a few lines, (c) gives more verified work per
token and per second than our 91.6 tokens / 20 s result, and (d) has a headline result worth sharing, all within
the constraints above? Include the smallest preregistrable experiment that would prove or kill it.
