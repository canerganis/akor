# Brief for Astra and Opus 5.5: what is wanted and the limits (applies to every round from here)

## What is wanted
1. One joint foundation decision record for AKOR's next phase that steps 3 to 6 of the signed plan can build on
   without reopening it. Its structure, scope and content are yours to decide.
2. It must be implementable from today's code (SQLite inbox, atomic parser, ledger) without breaking the 342-test
   suite or the shipped wire, and every decision must be checkable by a test or a measurement.
3. Agreement between you. Where you still disagree, say so plainly rather than papering over it.

## Limits
1. Metric order is fixed: correct requested work before the deadline within quotas, then total billed tokens
   (hidden reasoning and failed calls included), then elapsed time. No decision may trade correctness for tokens.
2. Transport: `claude -p` (and `codex exec`) logins only. No API key, no direct API adapter, no hosted service.
3. The shipped OZ/1g wire (system text H, parser profile oz1g-header) stays byte-identical for the qualified Claude
   cells. Any wire change is a new profile and needs its own preregistered qualification before it ships.
4. Core stays Python standard library. New dependencies only in bench or optional extras.
5. Nothing is repaired: no rescue of malformed replies, no lenient parsing presented as correct work.
6. Accounting comes from `modelUsage` (whole call, subagents included); the CLI `usage` field is last-turn only.
7. Evidence rule: a claim about savings, reliability or model behavior cites a measured fact from the packs or is
   marked as a hypothesis with its test. Do not cite numbers that are not in the evidence.
8. English, no em dashes (it will be published). Claude relays your texts to each other verbatim.

## New evidence for round 2 (pilot at 16 jobs, 3 seeds, strict oracles, tokens from modelUsage)
| Model | OZ/1g one call | plain JSON one call | one call per job | one subagent per job |
|---|---|---|---|---|
| Sonnet 5.5 tokens per verified job (correct) | 200.5 (48/48) | 245.1 (48/48) | 2,793 (34/48) | 8,617 (48/48) |
| Opus 5.5 | 196.6 (48/48) | 233.2 (48/48) | 3,737 (25/48) | 8,247 (48/48) |
| Haiku 5.5 | 272.3 (48/48) | 300.9 (48/48) | 3,471 (31/48) | 9,519 (39/48) |
Median seconds per 16 jobs: OZ/1g 9 to 13; subagent arm 34 to 50; per-job calls run sequentially about 115.
Per-job calls lost correctness mostly by answering the right value with appended explanation prose, which the
strict checker rejects; per requested job they still cost about 10x OZ/1g. 162 single-call records: CLI `usage`
equals `modelUsage` for every one; only multi-turn calls differ. A 64-job Sonnet repeat is running.
