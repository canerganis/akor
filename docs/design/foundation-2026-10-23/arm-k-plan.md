# Arm K: a caller agent using `oz do` (frozen before the first counted call, 2026-10-23)

Required by the foundation record (clause 10, steps table): measure integration with the caller included.

Caller: `claude-sonnet-5-5` through `claude -p`, only the Bash tool, the same system prompt and the same plain JSON
job text as pilot arms J and S, prefixed by a short skill text about `oz do` (`bench/live/pilot_k.py`, K_TEXT). The
worker is Sonnet 5.5 through the repo's Claude adapter. Claude CLI 2.1.306.
Runs: 16 jobs on seeds 3005 to 3007 and 64 jobs on seeds 3105 to 3107, the pilot's seeds, so arms J (caller does
the work itself in one reply) and S (caller spawns one subagent per job) from the pilot are matched controls:
same caller system prompt, same job text, same model, same oracles. Concurrency 1.
Cost: caller tokens from `modelUsage` (all turns) plus worker tokens from the `oz do` ledgers (adapter-reported
usage from `modelUsage`). Score: the caller's final reply judged by the same strict plain JSON decoder and oracles.

Not run: the multi-command loop (`oz init`, `oz send`, `oz run`): the existing commands cannot express this
workload (named operations over shared references) without `oz do`, so there is no matched multi-command arm.

Reported as measured, no gate. Smoke (seed 2999, not counted): 16/16, one Bash call, caller 13.1k tokens, worker
3.1k tokens, 30 s.
