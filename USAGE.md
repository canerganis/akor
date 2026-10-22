# AKOR 0.9.0 usage guide

AKOR manages the message language and the transport. You connect the model or agent system you use. It needs Python 3.10+. Init, send, status and inspect run on the standard library. Token counting uses the optional `tiktoken`.

Packets use the [OZ/9](OZ9.md) language (wire `stage-1g`, design: [docs/design/stage-1g-joint-decision.md](docs/design/stage-1g-joint-decision.md)): one fixed system text and one compact JSON body `{"v":"1g","goal":...,"ops":[...],"refs":[...],"jobs":[...]}`. `goal` is the channel goal, written once. `ops` holds the instruction of each operation in use, once each. `refs` holds each referenced channel record and each accepted predecessor result, once each, in first-use order. `jobs` has one block per operation, `[op_index,[job_id,ref_index,...],...]`: each row is one job, and its inputs are the `refs` entries named by the indices, in row order. A job with no inputs is `[job_id]`. Indices are zero-based. A job ID is a non-empty string that is unique in the packet: the inbox ID for a job with one model slot, `<id>.<atom index>` for each slot of a job with several. Literal text (`oz send --file`) travels as the operation instruction in `ops`. The model returns one JSON record per job, keyed by job ID. `read` and `test` never go to the model: `read` returns an empty string and `test` returns the procedure text unchanged, both filled in by the host. If a packet has no model work left, the adapter is not called at all. A few large calls save the most; `oz run --min-batch` and `--max-wait` are for that (below).

## First working example

From the repo:

```powershell
python -m pip install ".[benchmark]"
oz demo .oz-runtime/trial
oz status --workspace .oz-runtime/trial
oz inspect review --workspace .oz-runtime/trial
```

The demo creates an empty directory. The `read` job finishes on the host and the `propose` job on a local program. The reviewer's job (`read`) waits for their results, then finishes on the host without a model call. A status event is recorded without a model call. The demo program's output says `DEMO receipt only`, so no real work or test is claimed. Instead of running `demo` again in the same directory, inspect the existing state or pick a new empty directory.

The tokenizer may download its vocabulary on first use. That is not a model call. `TIKTOKEN_CACHE_DIR` chooses the cache location. No model key is needed.

## Start with your own source file

```powershell
oz init .oz-runtime/team --goal "Review the source; keep the measurement uncertainty." --source data.txt
cd .oz-runtime/team
oz send r --id read1
oz plan --show-prompt
```

`r` is filled in by the host, so this plan shows `mode: host` and an empty prompt. To see a prompt that reaches a model, use a patch (next example).

For a patch and a test procedure:

```powershell
oz init .oz-runtime/code --goal "Review the patch; the public API must not change." --source change.diff --kind patch --procedure checks.txt
oz send V --id review --workspace .oz-runtime/code
oz plan --show-prompt --workspace .oz-runtime/code
```

`--goal` and `--source` always go together, and `--channel` cannot be combined with them. The procedure file describes the tests to run; AKOR does not run the commands in it. For a patch, `V` is a request to read, review and, if there is a procedure, test. For a source, use `r` when there is no procedure and `V` when there is one.

The input file is read in full as UTF-8, with line endings kept, CRLF included. The source path and the SHA-256 of the raw bytes go into the record. Later changes to the file do not change an existing channel. A new source or revision needs a new channel.

`oz init` writes only into an empty directory. It creates these files:

| File | Content |
|---|---|
| `oz.json` | Channel manifests, tokenizer, input budget and batch size |
| `inbox.sqlite` | Jobs, results, dependencies, attempts and history |
| `START.md` | First commands that fit your channel |
| `.gitignore` | A pattern that keeps local SQLite working files out of commits |

You can use an existing manifest with `oz init DIRECTORY --channel channel.json`. To add a channel without changing the existing ones, use `oz channel-add NAME manifest.json`. `worker` and `reviewer` are channel aliases; you can add channels with your own names. Keeping an old channel unchanged keeps the context of pending jobs intact.

## Messages and dependencies

```powershell
oz send P --id plan1
oz send r1 --to reviewer --id check1 --after plan1
oz send --file new-info.txt --id info1
oz status
oz inspect plan1
```

The first line is for `P` in the default demo channel. In a real source channel, use `r` or `V`, whichever the channel supports. `--after` can be given more than once. Dependencies must be in the same session, task and revision; different recipients are supported.

If a sender resends because no answer came, it must use **the same `--id`**. The same ID with the same meaning creates no new job. Without `--id`, a new short random ID is generated and printed, and every call counts as a new job. `--file` sends the text as a literal operation: the text becomes the instruction in `ops`, unchanged, and the job has no references of its own (only predecessor results, if any). A frame is limited to 8192 UTF-8 bytes; add larger sources as channel references.

The results of predecessor jobs go into the dependent job's own input. Only the successful result records of direct predecessors are used, in the order the `--after` options were given. A record is a JSON value, not a string holding JSON: the value itself for one slot, `{"results":[...]}` for several slots (results stored before this version go out as strings). Each predecessor result is written once in `refs`, and the job lists its index after its own record, in dependency declaration order. A failed predecessor blocks the dependent job, which is not sent with missing input. The worker sees no separate dependency syntax. These results are **unverified agent data**, not new authority or evidence. Numbers and uncertainty are not summarized automatically. If the results do not fit the budget, the job waits. The low-level `Delivery.prepare` shows only its own frames; for automatic handoff use `Inbox.plan`, `claim_prepared` or `Worker`.

## Connect your own agent program

`adapter.json`:

```json
{"argv":["python","my_agent.py"],"protocols":["oz.adapter/3"],"languages":["OZ/9"]}
```

`protocols` and `languages` are the versions the program can speak. With an unsupported version, nothing is claimed and the run stops. Arguments are a list; they are not interpreted as a shell command string. The working directory is the directory of the adapter JSON file. `init`, `send`, `plan` and `status` never run the adapter. To run it explicitly:

```powershell
oz run --adapter adapter.json --max-calls 4 --timeout 120
```

The program reads one UTF-8 JSON object from stdin:

```json
{
  "protocol":"oz.adapter/3",
  "language":"OZ/9",
  "binding":"...",
  "receipt":"2a",
  "ids":["plan1","plan2"],
  "attempts":[1,1],
  "system":"The fixed system text...",
  "prompt":"The one-line JSON body that carries the jobs...",
  "prompt_tokens":[312]
}
```

Give your model only the `system` (system instruction) and `prompt` (user message) fields. `prompt_tokens` is the combined measurement of the two. `ids`, `attempts` and `receipt` are host metadata and do not belong in the prompt. `receipt` is a short counter renewed on every attempt; it ties a reply to that call and is not authentication. Stdout must contain only the JSON below; stderr may be used for diagnostics:

```json
{
  "reply":"OZ/1g\n{\"a\":\"Result text\"}\n{\"b\":[\"12.48 mm\",\"12.52 mm\"]}\n[\"c\",\"error\",\"missing_data\",\"Source is missing.\"]",
  "usage":{"input_tokens":312,"output_tokens":44,"cached_input_tokens":0}
}
```

`reply` is the model's raw text answer (parsing JSON is not the adapter's job). It is the line `OZ/1g`, then exactly one line per job. A success is a one-member object `{"id":value}` whose value is the whole result and can be any JSON value. A job failure is the four-element array `["id","error",code,message]`, where `code` is `missing_data`, `invalid_data`, `conflict` or `unsupported` and `message` is a non-blank string. The two are told apart by line shape, so a value like `["error",...]` inside a success is ordinary data. `id` is the job ID of the request and is compared exactly. A job with several slots (such as `V`) expands into several results; the host collects the model's results and its own (`read`, `test`) in slot order and stores them as `{"results":[...]}`.

Acceptance is atomic for the whole reply. Lines are split on LF (CRLF is accepted, one final line end is optional); empty lines and lines of only spaces and tabs are skipped. The first other line must be exactly `OZ/1g`, optionally followed by spaces or tabs. A missing or repeated header, a code fence, extra text, a malformed or truncated line, an object with duplicate keys, a non-finite number, an unknown or repeated ID (even byte for byte identical), a line that is neither a one-member object nor a four-element error array, a bad error code or message, or an ID set that does not exactly match the expected one rejects the whole reply. Nothing is repaired and no result is published; every job is retried with a new receipt. Line order is free. A valid job failure is not a rejection: that job becomes `failed` permanently (the reason is `"<code>: <message>"`, visible with `inspect`), and successes and failures are recorded in the same transaction. For a job with several slots, if any slot reports an error, the job becomes `failed` with the reason of the first failing slot. A job whose predecessor is `failed` is not sent and stays `waiting`. A line can be at most 65536 bytes, and the whole reply at most `65536 × job count + 4096` bytes. On an adapter error or timeout, all jobs are retried too. Line errors appear in `calls.jsonl` under `validation.violations`; valid job failures appear as `failed_results` with `outcome: job_error`.

**There is no reply mode.** `--reply-mode` and `reply_mode` are gone; the one format is the reply above. In `calls.jsonl`, `validation.binding` is always `declared` and `semantic_verified` is always `false`: an ID written by the model does not prove that the answer next to it belongs to that job, and does not show it was computed from the right input. Checking content needs a task-specific validator. `--context full` is gone; only `needed` exists.

Results are stored as the value's JSON text; a string result is stored as is. `usage` is an optional provider report; if it is absent, it is treated as unknown. Cached input is not added again to normal input. The system text, the reply contract and predecessor outputs count toward the local input budget. In a workspace, every model call is appended to `calls.jsonl` (`akor.call/1`) as `call_start` and `call_end` lines; unknown values stay `null`.

A ready-made example: [examples/claude_cli_adapter.py](examples/claude_cli_adapter.py) runs the request through `claude -p`. The `system` field goes in as `--system-prompt` and `prompt` goes to stdin. The model is chosen by the `OZ_MODEL` environment variable (default `claude-sonnet-5-5`; use the full model ID, because the `haiku` alias goes to the old Haiku 4.5). In `adapter.json`, give the Python path and this file as `argv`.

To connect an existing framework from Python without a subprocess:

```python
from oz_worker import Worker

def adapter(request):
    text = existing_agent(request["system"], request["prompt"])  # Your own existing agent call.
    return {"reply": text}  # Raw model text: the OZ/1g line, then one JSON record per job.

worker = Worker(inbox, channel, adapter, counters=[count_for_model], max_tokens=2048,
                capabilities={"protocols": ["oz.adapter/3"], "languages": ["OZ/9"]})
report = worker.run_once()
```

`existing_agent`, `inbox`, `channel` and the tokenizer come from your own application. The required JSON contract is in the `system` text. A Python callable must enforce its own timeout in your provider client; an arbitrary Python function is not forcibly stopped. The stdio adapter terminates the process tree it started on timeout. The stdio output size is checked after capture; this is not a memory quota or a tool sandbox.

## One call for a fan-out: `oz do`

`oz do` is the default entry point for an agent. One command takes a whole request, runs it to completion or to its deadline in the foreground, and prints one compact JSON result. It uses the same inbox, worker, adapter contract, ledger and OZ/1g wire as `send` and `run`; nothing on the model wire is new.

```powershell
oz do request.json --workspace . --adapter adapter.json
Get-Content request.json | oz do --adapter adapter.json
```

The workspace must already exist (`oz init`); it supplies the tokenizer and the defaults. The same call from Python returns the same result: `from oz_do import do; do(request, workspace=".", adapter="adapter.json")`. Accepted values keep the exact bytes the model wrote (`12.50` stays `12.50`), so in Python they are `oz_reply.RawJSON` objects that compare like their decoded values; serialize a result with `oz_reply.dumps`, not `json.dumps`.

The request (`oz.do/1`):

```json
{
  "request_id": "batch-17",
  "goal": "Prepare an evidence-limited inspection handoff. The interval is [12.48,12.52] mm.",
  "ops": {"extract": "Extract the length and its uncertainty.", "bounds": "Check the length against the interval."},
  "refs": {"c1": "length=12.50 mm; uncertainty=0.02 mm", "c2": {"path": "data/sample2.txt"}},
  "jobs": [["e1", "extract", "c1"], ["b1", "bounds", "c1"], ["e2", "extract", "c2"]],
  "model": "claude-sonnet-5-5",
  "allow_experimental": false,
  "deadline_seconds": 600
}
```

`goal`, `ops`, `refs` and `jobs` are required (`refs` may be empty). A job is `[id, op, ref...]` or `{"id","op","refs"}`; it applies one operation to its references in the listed order, and a job may list none. A reference is inline text or `{"path": ...}`, a UTF-8 file read byte for byte that must resolve inside the authorized directory (the workspace, or `--allow DIR`). Optional: `request_id` (default: derived from the work's SHA-256), `max_attempts` (2), `model`, `allow_experimental` (false), `deadline_seconds` (600, at most 3600), `call_timeout_seconds` (300), `max_jobs_per_call` (the workspace `batch_size`), `max_input_tokens` (the workspace `max_tokens`; raise it for large packets) and `max_inline_bytes` (4096). Unknown keys are refused. The adapter always comes from the command line, never from the request.

The model sees exactly the shipped packet: `goal`, the instruction texts in `ops`, the reference texts in `refs` (each once), and the jobs grouped by operation, under the job IDs you gave.

The result (`oz.do.result/1`):

```json
{"schema":"oz.do.result/1","status":"complete","counts":{"accepted":2,"failed":1},
 "jobs":{"e1":{"status":"accepted","value":["12.50 mm","0.02 mm"]},
         "b1":{"status":"accepted","value_file":"do/batch-17/values/b1.json","bytes":5120,"sha256":"..."},
         "e2":{"status":"failed","code":"missing_data","message":"No uncertainty given"}},
 "evidence":{"scope":"model_declared","checks_run":0,"id_binding":"declared"},
 "calls":[{"jobs":3,"profile":"experimental","status":"received"}],
 "accounting":{"calls":1,"failed_calls":0,"unfinished_calls":0,"experimental_calls":1,"qualified_cell_calls":0,
               "usage_coverage":"complete","calls_with_usage":1,"tokens":{"input_tokens":1840,"output_tokens":96,"...":0},
               "tokens_scope":"all calls"},
 "qualification":null,"blocker":null,
 "run":{"workspace":"...","run_dir":"do/batch-17","request_id":"batch-17","request_sha256":"...","binding":"...",
        "model":"claude-sonnet-5-5","elapsed_seconds":41.2}}
```

A job is `accepted` (with `value`, or `value_file` when it is larger than `max_inline_bytes`), `failed` (a valid job failure reported by the model) or `unresolved` with a `reason`: `deadline`, `in_flight` (an earlier attempt still holds the lease), `attempts_exhausted`, `backoff`, `input_budget`, `experimental_size_not_authorized` or `unsupported_size`. Accepted values are what the model declared: no check ran, and the ID binding is declared, not proven. `calls` lists this invocation's calls; `accounting` covers every call of the request across invocations, failed and unfinished calls included, from the adapter's reported usage. When a call reported no usage, `usage_coverage` is `partial` or `none` and the token sums cover only the calls that reported it. Exit code 0 means every job was accepted, 3 means some job failed or is unresolved, 2 is a request or configuration error.

**Resubmission.** Run the same request again after a timeout or a crash. The same `request_id` with the same work posts no new job and makes no call for a job that is already settled; only unfinished jobs are sent. A job whose call was interrupted stays `in_flight` until its lease (call timeout plus 30 seconds) ends, so a crashed call is not blindly replayed. The same `request_id` with different work is refused before anything runs. Execution options (deadline, model, experimental authorization, output limits) may change between submissions.

**Sizes.** Every call is labeled with its job count and a profile. `qualified_cell` means the declared `model` passed the size gate for exactly that job count: Sonnet 5.5 at 1, 4, 16, 32 and 64; Opus 5.5 at 4, 16 and 64; Haiku 5.5 at 1, 4, 16 and 64; Fable 5.1 at 64 ([size gates](docs/design/foundation-2026-10-23/size-gates-results.md), [OZ9.md](OZ9.md)). `oz do` checks only the declared model and the size; the CLI version, effort, adapter and workload class those cells were qualified under are not verified, and the `qualification` field says so whenever a qualified label is used. Any other size, or no declared model, is `experimental` and is sent only with `"allow_experimental": true`; otherwise the jobs stay unresolved with a blocker and no call is made. A failed gate (Opus 5.5 at 1 job) is never sent. The cells are one table, `oz_do.CELLS`; a new gate adds rows there.

Each request has its own run directory, `do/<request_id>/`, which is an ordinary workspace: `oz status --workspace do/batch-17`, `oz inspect e1 --workspace do/batch-17` and `oz retry` work on it, and its `calls.jsonl` is the call ledger. References are loaded by host read jobs named `ref-<name>`, so a job ID may not take that form.

## Per-job checks: profile `oz1g-selective-v1` (opt-in)

The default acceptance profile is `oz1g-header`: a wire-valid reply commits every job, a rejected reply retries every job. `oz1g-selective-v1` keeps the same system text, packet and parser (a malformed, truncated or mismatched reply still yields nothing), then judges each job's value on its own with host checks pinned to that job:

```json
{"profile": "oz1g-selective-v1",
 "checks": {"extract": [{"check": "quoted_span"}], "bounds": [{"check": "one_of", "values": ["in", "out"]}]}}
```

Add these two keys to an `oz do` request (or pass `profile=` and `checks=` to `Inbox.post`). Registered checks: `json_type` (`types`), `max_bytes` (`bytes`), `one_of` (`values`), `quoted_span` (the value, or its string member `field`, occurs verbatim in one of the job's own references) and `expect` (`value`, a host oracle). The last two are job-bound. A job that fails a check retries alone, within its attempts. A failed job-bound check marks the reply suspect: its other jobs commit only with their own passing job-bound check; the rest are quarantined and redispatched while attempts remain, else reported `quarantined`. A verifier that is unavailable leaves the job `unresolved` with reason `awaiting_checks` and spends no model call; the next `oz do` rechecks it. Accepted jobs carry `evidence` (`checked` or `declared`, plus the checks that ran).

With this profile, `oz do` runs the adapter under `oz_runner.py`, which publishes `do/<request_id>/captures/<receipt>.done` atomically, and journals every dispatch (intent, launch with PID and creation time, capture, or `uncertain`) in the run's SQLite inbox. A rerun after a crash reuses a published capture without a new call, adopts a late reply only into a job that is still unresolved, never overwrites an accepted result, and reports dispatches it cannot reconcile under `accounting.unreconciled_dispatches` with usage left unknown. The profile's reliability and savings are not yet measured.

## Budget, retries and visibility

In `oz.json`, `max_tokens` is the upper bound on the receiver's input. `encodings` are the target tokenizer names; with more than one, the limit applies to each. `batch_size` sets how many ready jobs are scanned at most (1 to 64). The defaults are 2048 tokens and 64 jobs. Ready jobs are collected into one call without waiting.

`plan` has no side effects: it uses no attempt or lease. The full packet is tried first; if it does not fit, a bounded greedy selection is made. One large job does not block smaller independent jobs. This is not a mathematical optimum over all possible packets. Text of jobs that do not fit the budget is never truncated and no attempt is spent.

Every model call carries a fixed load (the system instruction, tool definitions). To spread that load over more jobs:

```powershell
oz run --adapter adapter.json --min-batch 16 --max-wait 30
```

If fewer than `--min-batch` jobs are ready and the oldest ready job is younger than `--max-wait` seconds, `run` returns `waiting` without a call; no attempt or receipt is spent. The default `--min-batch 1` means calling without waiting. The measured savings are reported in the [README](README.md) and [OZ9.md](OZ9.md).

`run` makes one adapter call by default; `--max-calls` raises the cap. It stops when the queue is empty or a call returns an adapter error or a transient failure; it never starts a background loop. New jobs get 2 attempts by default (counting the first; change it with `oz send --max-attempts`). The default two-second wait after a transient failure is stored durably. Packets that need no model (only `read` and `test`) finish without an adapter with status `host_completed`, and they do not count against `--max-calls`. When the time comes, call `run` again.

```powershell
oz status
oz status --json
oz inspect plan1
oz retry plan1 --extra-attempts 1
oz events
```

`retry` reopens only a failed job; running a completed job again needs a new ID. `events` only records host events; it does not carry out a stop request, run tools or verify success. By default `status` does not show result texts; `inspect` opens the content and the event history. `status` lists up to `--limit` jobs (default 100) and prints a `More: --after-seq N` line when there are more.

`ready`: ready; `waiting`: a predecessor is pending; `backoff`: waiting for the retry time; `leased`: delivered; `expired`: the lease ran out; `failed`: attempt limit reached or a permanent error; `done`: the host accepted the result and ACKed it. `done` is not an independent confirmation that the claim about the outside world is true.

CLI exit codes: **0 success or empty**, **2 configuration, input or budget error**, **3 adapter error, rejected reply or a job that ended `failed`**. The free text of a provider exception is not recorded; codes such as `adapter_timeout`, `adapter_invalid_json`, `adapter_invalid_reply` and `adapter_exit_N` are shown instead. The adapter must check that the tokenizer matches the real target model.

A SQLite v1 queue is upgraded to v2 inside a transaction on first open; jobs and results are kept. Several workers can claim different jobs at the same time through separate SQLite connections. Delivery is at least once: if an external effect happens and the process ends before the ACK, the job can arrive again. Idempotency by message ID is still needed on the tool side.
