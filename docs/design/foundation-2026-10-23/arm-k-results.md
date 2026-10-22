# Arm K: a caller agent using `oz do`, results

Plan: [arm-k-plan.md](arm-k-plan.md). Caller and worker Sonnet 5.5, Claude CLI 2.1.306. J and S are the pilot's
matched controls (same caller system prompt, job text, seeds, oracles).

| Sonnet 5.5, caller included | Correct jobs | Tokens per verified job | Caller share of tokens | Median s per seed |
|---|---:|---:|---:|---:|
| 16 jobs, J: caller does the work itself in one reply | 48/48 | 245.1 | 100% | 9.9 |
| 16 jobs, K: caller hands the jobs to `oz do` | 48/48 | 1,001.2 | 81% | 27.8 |
| 16 jobs, S: caller spawns one subagent per job | 48/48 | 8,616.6 | n/a | 38.7 |
| 64 jobs, J | 192/192 | 151.1 | 100% | 20.8 |
| 64 jobs, K | 192/192 | 798.7 | 89% | 52.4 |
| 64 jobs, S | 188/192 | 7,931.0 | n/a | 105.1 |

Every K run used one `oz do` worker call; callers used one Bash call at 16 jobs and two to four at 64.

What it shows:
1. Handing a fan-out to `oz do` costs 9 to 10 times less than one subagent per job, and finishes 1.4 to 2 times faster.
2. When the caller already holds every job and the reference text, doing the work itself in one batched reply is
   cheaper still, by 4 to 5 times. `oz do` pays for the caller rewriting the jobs into a request and rereading its
   context across tool turns; that is 81% to 89% of K's tokens. This is the next integration cost to cut (foundation
   record M1, M14), for example references passed as file paths and results kept out of the caller's context.
3. `oz do` is the right tool when the work should not stay in the caller: a cheaper or different worker model,
   durable retries and resume, or a caller context that must stay small. That trade is now measured, not assumed.

Scoring note: the first scoring of these runs used the wrong seed's records for every seed except the last, a harness
bug (`pilot_k.py` built all packets before judging). The stored raw replies were re-judged with each record's own seed
(`pilot_k.py rescore`, field `rescored`); no model call was repeated and no reply was changed.
Data: `bench/live/data/pilot_k_sonnet16.jsonl`, `pilot_k_sonnet64.jsonl`.
