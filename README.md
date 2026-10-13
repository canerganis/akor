<div align="center">

# AKOR

**Fewer tokens per finished job when AI agents hand work to each other.**

AKOR packs the ready work of many agents into one compact call, keeps deterministic work off the model,
and accepts an answer only when every job in it is accounted for.

![Python](https://img.shields.io/badge/python-3.10%2B-2a78d6)
![Dependencies](https://img.shields.io/badge/core%20dependencies-none-2a78d6)
![Tests](https://img.shields.io/badge/tests-336%20passing-1a7f4b)
![Protocol](https://img.shields.io/badge/wire-%C3%96Z%2F9%20stage%201g-52514e)
![License](https://img.shields.io/badge/license-MIT-52514e)

<img src="docs/assets/flow.svg" alt="Ready jobs from several agents are packed into one call; the model answers one record per job, keyed by job ID; the host checks the whole reply before it delivers anything." width="100%">

</div>

## Why

Multi-agent setups spend most of their tokens on overhead: every call repeats the same rules, the same context
and a verbose reply format, and a malformed answer forces a retry. AKOR attacks that overhead and nothing else.
The work itself, the quality checks and the correctness bar stay the same.

On a live, pre-registered benchmark where every job is checked by a deterministic oracle, AKOR used
**40.7% fewer total tokens per verified job** than its own JSON-based predecessor (0.8) on Claude Sonnet 5.5
with 64 jobs per call, with every reply accepted on the first try and every job correct.

| Sonnet 5.5, 64 jobs per call | Calls | Replies accepted | Correct jobs | Tokens per call | Median time |
|---|---:|---:|---:|---:|---:|
| AKOR 0.8 | 5 | 5/5 | 320/320 | 9,387 | 13.8 s |
| AKOR (stage 1g) | 20 | **20/20** | **1280/1280** | **5,568** | **12.5 s** |

Tokens are everything that was billed: the prompt, the CLI's own fixed overhead (about 950 tokens per call), the
visible answer and hidden reasoning. Per verified job: 87.0 tokens against 146.7.

The same wire was then checked on other models for breakage (no paired baseline there, so no savings claim):

| Model, jobs per call | Calls | Replies accepted | Correct jobs | Tokens per call | Median time |
|---|---:|---:|---:|---:|---:|
| Haiku 5.5, 64 | 10 | 10/10 | 640/640 | 9,267 | 20.3 s |
| Fable 5.1, 64 | 5 | 5/5 | 320/320 | 5,480 | 19.5 s |
| Sonnet 5.5, 32 | 5 | 5/5 | 160/160 | 3,891 | 7.0 s |

Plus five stress packets per model whose results are all empty arrays, scalars, objects, nested arrays or
genuine job failures. Across all 71 Claude calls on the final wire, the parser accepted every reply. Haiku 5.5
thinks much longer on this wire than Sonnet (up to 10k output tokens per 64-job packet), so it is not the cheaper
model here. Raw data, manifests and the harness are in [`bench/`](bench/); every decision is in [`docs/design/`](docs/design/).

### Supported models

This release is qualified for the tested Claude configurations only: `claude-sonnet-5-5` (32 and 64 jobs per
call), `claude-haiku-5-5` and `claude-fable-5-1` (64 jobs per call), all through `claude -p` at default effort.
The broader qualification, which also covered a Codex model, failed: GPT-6 Luna at medium effort through the
Codex CLI got 1 of 10 packets right, binding jobs to the wrong operation or input and slipping out of the reply
format. For other models, use the 0.8 release (tag `oz-0.8.0-full`). The scope was chosen after that failure and
is recorded as such in [`docs/design/stage-1g-release-scope.md`](docs/design/stage-1g-release-scope.md).

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
| **One call, many jobs** | Ready jobs are packed into one packet (64 by default). The goal, each operation and each shared input are written once, not once per job; jobs refer to them by index. `--min-batch` and `--max-wait` let small jobs wait briefly for a bigger, cheaper call. |
| **Deterministic work stays on the host** | Reading, test requests and status events never reach a model. A batch made only of such work completes with zero model calls. |
| **One record per job, keyed by ID** | The model answers `OZ/1g`, then `{"job_id":result}` per job, or `["job_id","error",code,message]` for a job it cannot do. Results bind to IDs, never to line positions. |
| **Strict, atomic acceptance** | The whole reply is checked before anything is delivered: header, one record per expected ID, no extras, strict JSON. Nothing is repaired. A malformed reply sends its batch back once (two attempts by default); a valid error record fails only its own job. |
| **Inputs are data, never instructions** | Shared inputs travel in `refs`, which the worker is told are data. The worker has no tools and may not claim execution or verification. |
| **Durable queue** | SQLite inbox with dependencies, retries, leases and resume. Exactly-once insertion, at-least-once delivery. |
| **Every call on the books** | An append-only ledger (`calls.jsonl`) records tokens, cache use, time, validation and retries for each call. |
| **Provider-neutral** | Adapters are plain stdin/stdout programs. Works with `claude -p` and `codex exec` logins. |
| **Small core** | Python 3.10+, standard library only. `tiktoken` is optional for token counting. |

A packet body and its reply (from [`docs/design/stage-1g-astra.md`](docs/design/stage-1g-astra.md), shortened):

```json
{"v":"1g","goal":"Prepare an evidence-limited inspection handoff. The numerical acceptance interval is [12.48,12.52] mm, inclusive.",
 "ops":["Return a compact JSON array of strings containing the ref's length, uncertainty, n, method, basis, physical_validation, in that order.",
        "Return inside if the entire length +/- uncertainty interval lies within the goal's acceptance interval; outside otherwise."],
 "refs":["length=12.53 mm; uncertainty=0.01 mm; n=4; method=micrometer; basis=unknown; physical_validation=not_claimed",
         "length=12.54 mm; uncertainty=0.02 mm; n=5; method=micrometer; basis=unknown; physical_validation=not_claimed"],
 "jobs":[[0,["e1",0],["e2",1]],[1,["v1",0],["v2",1]]]}
```

```text
OZ/1g
{"e1":["12.53 mm","0.01 mm","4","micrometer","unknown","not_claimed"]}
{"e2":["12.54 mm","0.02 mm","5","micrometer","unknown","not_claimed"]}
{"v1":"outside"}
{"v2":"outside"}
```

## How it was built and measured

The wire format was designed by one model (GPT-6 Astra), reviewed and co-designed by another (Claude Fable 5.1),
and implemented and measured by a third (Claude Opus 5.5). When a test failed, the designer and the reviewer each
proposed a fix from the same evidence and argued until they agreed; the transcripts are in
[`docs/design/`](docs/design/). Every candidate went through the same gate: a plan, thresholds and call budget
frozen and hashed before the first call, fresh records every repetition, deterministic oracles for every job,
strict validation as in the product, and failed calls counted in the cost.

That gate caught real problems along the way, and they are on record:

- An earlier reply format (stage 1f) lost 3 of 3 live calls to a slip in the first visible characters: typographic
  quotes, or a result array flattened into its record. The fix was a separate record shape per success
  (`{"id":value}`) and a fixed header line before the first record.
- A model alias that silently pointed at an older model, and a test harness that repaired replies the product
  would reject.
- Two defects in our own stress packets: jobs that needed outside facts under a goal that said "answer from the
  supplied refs only", and one job whose wording allowed a flat or a nested reading. The wire carried every one of
  those answers correctly; the packets were fixed, re-approved and re-run. Two authoring rules came out of it:
  state the result shape, with a literal example when nesting matters, and let the goal say whether a job may use
  knowledge that is not in its refs.

The full specification is in [`OZ9.md`](OZ9.md).

## Limits

- Savings come from batching. With 1 to 4 jobs per call there is no gain; the fixed per-call overhead dominates.
- The paired savings figure is for Sonnet 5.5 at 64 jobs on one task family with oracles. Other models were
  checked for correctness, not for savings; your workload may differ, and [`bench/`](bench/) lets you measure it.
- Acceptance is all or nothing per reply: one malformed line costs a retry of the whole batch. On the final wire
  that did not happen in 71 calls, which bounds the per-call failure rate (about 4% at 95% confidence), it does
  not prove it is zero.
- Codex-based models are not supported by this wire (see Supported models; kit and raw replies in
  [`bench/codex_kit_1g`](bench/codex_kit_1g/)). The Codex CLI also adds about 24,500 fixed input tokens per call, so
  no reply format reaches large savings on that path.

## Related work

AKOR combines known ideas and measures them strictly. Batch prompting ([Cheng et al. 2023](https://arxiv.org/abs/2301.08721))
showed large savings from answering several samples in one call. LLMCompiler ([Kim et al. 2024](https://arxiv.org/abs/2312.04511))
plans function calls as a dependency graph. LDP ([2026](https://arxiv.org/html/2603.08852v1)) and BabelTele
([2026](https://arxiv.org/abs/2606.19857)) report 37% to 44% fewer tokens from structured or compressed agent messages.
[Protocol Compression Changes Which Party Pays](https://arxiv.org/abs/2609.06129) shows that compression can raise total
cost through parsing failures, which is why every AKOR result counts failed calls. These works use different
baselines, so their numbers are not directly comparable.

## Documentation

- [`OZ9.md`](OZ9.md): the protocol and host design, normative.
- [`docs/design/`](docs/design/): every wire stage, review, debate and live evidence, in order.
- [`USAGE.md`](USAGE.md): command-line guide.
- [`bench/`](bench/): live measurement harness, raw results and the Codex kits.
- [`docs/HISTORY.md`](docs/HISTORY.md): earlier releases 0.4 to 0.9.

## License

MIT, see [`LICENSE`](LICENSE).
