# Size gates at 1, 4 and 16 jobs: results

Plan and addendum: [size-gates-plan.md](size-gates-plan.md). Claude CLI 2.1.306, default effort, OZ/1g unchanged,
standard materials workload, strict parser, deterministic oracles.

| Cell | Calls | Replies accepted | All jobs correct | Tokens per verified job | Gate |
|---|---:|---:|---:|---:|---|
| Sonnet 5.5, 1 job (rerun, all four operations) | 12 | 12/12 | 12/12 | 2,384.8 | pass |
| Sonnet 5.5, 4 jobs | 10 | 10/10 | 10/10 | 660.0 | pass |
| Sonnet 5.5, 16 jobs | 10 | 10/10 | 10/10 | 219.5 | pass |
| Opus 5.5, 1 job (rerun) | 12 | 11/12 | 11/12 | 2,575.1 | **fail** |
| Opus 5.5, 4 jobs | 10 | 10/10 | 10/10 | 672.4 | pass |
| Opus 5.5, 16 jobs | 10 | 10/10 | 10/10 | 206.1 | pass |
| Haiku 5.5, 1 job (rerun) | 12 | 12/12 | 12/12 | 2,622.8 | pass |
| Haiku 5.5, 4 jobs | 10 | 10/10 | 10/10 | 796.5 | pass |
| Haiku 5.5, 16 jobs | 10 | 10/10 | 10/10 | 282.5 | pass |

The first size-1 run (10/10 on every model) was voided before the rerun because it exercised only one operation.

The Opus size-1 failure is the same one seen in pilot arm Q: a short reasoning line before the `OZ/1g` header
(`12.55–12.57, outside.` then the header and a correct record). The parser rejects it, as it must. One job per call
is therefore unsupported on Opus 5.5; `oz do` must not send Opus a one-job packet.

Haiku passed size 1 here, but in the exploratory arm Q it got 46 of 48 values right; the qualification gate is met,
and that earlier evidence is a reason to watch the cell in production monitoring.

Scope: each pass qualifies the standard workload class only, at CLI 2.1.306. Cost per verified job falls steeply
with size (Sonnet 2,385 at 1 job, 660 at 4, 220 at 16, 92 at 64 from the pilot), so a caller should batch whenever it
can wait for work to accumulate.

Data: `bench/live/data/gate_{model}_{4,16}.jsonl`, `gate1_{model}.jsonl`, voided `gate_{model}_1.jsonl`.
