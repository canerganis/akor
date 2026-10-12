<div align="center">

# AKOR

**Fewer tokens per finished job when AI agents hand work to each other.**

AKOR packs the ready work of many agents into one compact call, keeps deterministic work off the model,
and accepts every answer line on its own, so one bad line never costs a whole batch.

![Python](https://img.shields.io/badge/python-3.10%2B-2a78d6)
![Dependencies](https://img.shields.io/badge/core%20dependencies-none-2a78d6)
![Tests](https://img.shields.io/badge/tests-296%20passing-1a7f4b)
![Protocol](https://img.shields.io/badge/wire-%C3%96Z%2F9-52514e)

<img src="docs/assets/flow.svg" alt="Ready jobs from several agents are packed into one call; the model answers one line per job; each line is accepted on its own and a broken line sends only its own job back." width="100%">

</div>

## Why

Multi-agent setups spend most of their tokens on overhead: every call repeats the same rules, the same context
and a verbose reply format, and one malformed answer forces a full retry. AKOR attacks that overhead and nothing
else. The work itself, the quality checks and the correctness bar stay the same.

On a live benchmark where every job is checked by a deterministic oracle, AKOR used **35% to 47% fewer total
tokens** than its own JSON-based predecessor (0.8) at 32 to 64 jobs per call, across Opus, Sonnet and Fable,
with every job correct and faster answers.

<img src="docs/assets/results.svg" alt="Bar chart of total-token savings versus AKOR 0.8 for the same verified work." width="100%">

| 64 jobs per call | Correct jobs | Total tokens vs 0.8 | Median time (0.8 to AKOR) |
|---|---:|---:|---:|
| Opus 5.5 | 192/192 | **-47%** | 18.4 s to 13.4 s |
| Sonnet 5.5 | 320/320 | **-47%** | 14.7 s to 11.0 s |
| Fable 5.1 | 192/192 | **-45%** | 23.9 s to 18.6 s |
| Haiku 5.5 | 320/320 | **-33%** | 19.5 s to 17.4 s |

Totals include everything that was billed: the prompt, the CLI's own fixed overhead (about 950 tokens per call),
the visible answer and hidden reasoning. Raw data and the harness are in [`bench/`](bench/).

## Quick start

```bash
pip install .
oz demo ./demo
oz status --workspace ./demo
```

<img src="docs/assets/demo.gif" alt="Terminal session: create a workspace, send a job, inspect the packet that reaches the model, run the demo and check status." width="100%">

Connect a real agent with the bundled `claude -p` adapter ([`examples/claude_cli_adapter.py`](examples/claude_cli_adapter.py)),
or any program that reads one JSON request on stdin and prints one JSON reply. No API key is needed; AKOR uses
the CLI login you already have.

```bash
oz init team --kind patch --source fix.diff --procedure checks.txt
oz send V --id review --workspace team
oz run --adapter adapter.json --workspace team --min-batch 32 --max-wait 30
```

## What makes it work

| | |
|---|---|
| **One call, many jobs** | Ready jobs are packed into one packet (64 by default). Rules, operation definitions and shared inputs are written once, not once per job. `--min-batch` and `--max-wait` let small jobs wait briefly for a bigger, cheaper call. |
| **Deterministic work stays on the host** | Reading, test requests and status events never reach a model. A batch made only of such work completes with zero model calls. |
| **One line per job, accepted per line** | The worker answers `[i,value]` or `[i,null,"reason"]` per line. Valid lines are kept; a missing, broken or duplicated line retries only its own job, at most twice. |
| **Inputs are data, never instructions** | References and predecessor results travel as `{"input":…,"prior":[…]}`. The worker is told it has no tools and may not claim execution or verification. |
| **Durable queue** | SQLite inbox with dependencies, retries, leases and resume. Exactly-once insertion, at-least-once delivery. |
| **Every call on the books** | An append-only ledger (`calls.jsonl`) records tokens, cache use, time, validation and retries for each call. |
| **Provider-neutral** | Adapters are plain stdin/stdout programs. Works with `claude -p` and `codex exec` logins. |
| **Small core** | Python 3.10+, standard library only. `tiktoken` is optional for token counting. |

A packet as the model sees it (from `oz plan --show-prompt`):

```json
{"goal":"Review the timeout patch; keep the public API.",
 "d":{"audit":"Review the supplied patch for defects and unintended public-API changes. …"},
 "c":{"0":{"input":"--- a/retry.py … TIMEOUT = 5  # seconds per attempt"}},
 "j":["audit 0"]}
```

The job `V` asked for three steps (read, audit, test). Read and test ran on the host, so one job reached the model.

## How it was built and measured

The wire format (ÖZ/9) was designed by one model and implemented and measured by another. Every proposal went
through the same gate: a live run against a baseline doing the same work, fresh records every repetition,
deterministic oracles for every job, strict validation as in the product, and failed calls counted.

That gate caught real problems along the way: a model alias that silently pointed at an older model, a test
harness that repaired replies the product would reject, and a compressed reply format that looked 55% cheaper
offline but cost more live because of parsing failures. The full specification is in [`OZ9.md`](OZ9.md).

## Limits

- Savings come from batching. With 1 to 4 jobs per call there is no gain; the fixed per-call overhead dominates.
- Mixed, sparse workloads save less: 28% on Sonnet 5.5 and 11% on Haiku 5.5 for 64 jobs across 3 domains.
- Numbers come from one task family with oracles (field extraction, interval arithmetic, code repair, log reading). Your workload may differ; [`bench/`](bench/) lets you measure it.
- Codex-based models are measured separately ([`bench/codex_kit`](bench/codex_kit/)); the Codex CLI adds about 24,500 fixed tokens per call.

## Related work

AKOR combines known ideas and measures them strictly. Batch prompting ([Cheng et al. 2023](https://arxiv.org/abs/2301.08721))
showed large savings from answering several samples in one call. LLMCompiler ([Kim et al. 2024](https://arxiv.org/abs/2312.04511))
plans function calls as a dependency graph. LDP ([2026](https://arxiv.org/html/2603.08852v1)) and BabelTele
([2026](https://arxiv.org/abs/2606.19857)) report 37% to 44% fewer tokens from structured or compressed agent messages.
[Protocol Compression Changes Which Party Pays](https://arxiv.org/abs/2609.06129) shows that compression can raise total
cost through parsing failures, the failure mode AKOR's per-line acceptance is built to contain. These works use
different baselines, so their numbers are not directly comparable.

## Documentation

- [`OZ9.md`](OZ9.md): the protocol and host design, normative.
- [`USAGE.md`](USAGE.md): command-line guide (Turkish).
- [`bench/`](bench/): live measurement harness, raw results and the Codex kit.
- [`docs/HISTORY.tr.md`](docs/HISTORY.tr.md): earlier releases 0.4 to 0.9 (Turkish).
