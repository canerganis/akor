# AKOR

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

**An independent agent communication language and transport core. Package 0.9.0, OZ/9 language.** Python 3.10+, standard library only in the core.

## 0.9.0: same work, fewer tokens, faster replies

OZ/9 sends each call as two rule lines and a single JSON body. Four encodings (direct text, text with reference numbers, code frames, template table) are measured as a full packet, and the cheapest one goes. The model returns `{"results":[...]}`: a natural JSON value for each job, `null` for a failed job and `"errors":{"<position>":"reason"}`. Job ids and the call id (receipt) do not go to the model; they stay on the host side.

Live measurement: Sonnet (`claude -p`), jobs with real output (material range calculation, code repair), deterministic verifier. The comparison is against the 0.8 package doing the same work. The CLI's own fixed load of 905 tokens is included in every call.

| Jobs per call | Correct jobs (OZ/9) | Total tokens | Without CLI load | Median time |
|---:|---:|---:|---:|---:|
| 16 | same as 0.8 or better | 29% fewer | 41% fewer | similar |
| 32 | 96/96 | **43% fewer** | 52% fewer | 7.0 s (0.8: 7.9) |
| 64 | 192/192 | **55% fewer** | 61% fewer | 9.2 s (0.8: 14.0) |

There is no difference for calls of 1 to 4 jobs: the fixed per-call load dominates. The biggest lever is a small number of large calls. For that:

```powershell
oz run --workspace .oz-runtime/ekip --adapter adapter.json --min-batch 16 --max-wait 30
```

No call is made until `--min-batch` jobs are ready or the oldest job has waited `--max-wait` seconds; no attempts or receipts are spent while waiting.

Language specification and all measurements: [OZ9.md](../OZ9.md), [live measurement summaries](../reports/). The language was designed by Astra (gpt-6-astra); the code, measurement and critique were done by Claude.

## Earlier releases

The OZ/3, OZ/4, OZ/5 and OZ/6 layers between 0.5.0 and 0.8.0 were removed in 0.9.0: they did not save tokens in live measurement. The documents and code of those releases are in the `oz-0.8.0-full` tag. OZ/2 channels and queue files load unchanged; a channel that uses the removed features is rejected with a clear error message.

## 0.4.0: daily use

You can now create a workspace, send messages, see the budget in advance and run your own agent adapter without writing a Python integration. [Quick start and adapter contract](../USAGE.md).

```powershell
python -m pip install ".[benchmark]"
oz demo .oz-runtime/ilk-deneme
oz status --workspace .oz-runtime/ilk-deneme
```

The demo uses a real tokenizer and local stdin/stdout transport; it needs no model account/API key and makes no model call. Choose an empty folder. For a real task:

```powershell
oz init .oz-runtime/ekip --goal "Kaynağı incele; sayı, birim ve belirsizlikleri koru." --source veri.txt
oz send r --id incele --workspace .oz-runtime/ekip
oz plan --workspace .oz-runtime/ekip
oz run --workspace .oz-runtime/ekip --adapter adapter.json
```

`adapter.json` is the `argv` list of the agent program you will run. The program takes JSON on stdin and returns JSON on stdout; there is no automatically chosen model or hidden paid call. Only `run` runs the program you explicitly chose.

- **Automatic packing:** Independent jobs that fit are selected; a large message does not hold up the others, and a job that does not fit spends no attempt.
- **Real handoff:** The results of the earlier agent go to the dependent agent in full, as unverified data. A shared result is sent once; its cost is included in the budget.
- **Per-job results:** Successful jobs are completed; only those that got a transient error are retried, with a delay. A missing/wrong reply does not silently complete any job.
- **Resume where it left off:** Jobs, results, history and reports are persistent. A failed job is reopened with `oz retry ID`.
- **Visible state:** With `status`, `inspect` and `plan` you can see who is waiting for what and the measured input cost.
- **Start from a file:** With `--source`, `--kind patch` and `--procedure`, a channel is created without writing a manifest by hand. The source text and line endings are preserved, and the SHA-256 source id is recorded.

**143 tests passed.** In an offline end-to-end trial, 20 jobs were processed in **3 packets** at a limit of **350 input tokens** per job packet. Only the job that was given a transient error was repeated. The reviewer also received the 20 predecessor results under a 2,048-token budget. Zero model calls; this is not a measurement of real model task success or speed. [0.4.0 verification report](../reports/WORKFLOW-RESULTS.md).

## Language and earlier measurements

**New: [OZ/2](../OZ2.md).** A single `V` sign can carry the sequence "read the source → review the patch → request a specific test procedure" in a defined vocabulary. A sign is meaningful only if its vocabulary and context are known; this is not encryption or creating information from nothing.

- **Meaning macros:** Parametric/fixed macros expand into exact operation sequences. Evidence or success claims are not hidden in macros.
- **Selection by measured cost:** OZ, OZ without macros, short text, plain text and compact JSON are compared; the cheapest candidate, vocabulary and context included, is used.
- **Batch transport:** Independent messages share a single input; the shared source appears once. If the budget is exceeded, the text is not truncated.
- **Persistent queue:** SQLite; dependencies between different agents, duplicate filtering, delivery time, retries and rejection of old replies.
- **Model-free event path:** Status messages can be recorded in a separate host queue. Messages that contain work are prepared for the receiving model.
- **Less encoding work:** At most 256 candidates by default; the tokenizer result is reused for repeated text.

In the 0.3.0 live language trial, Codex encoding was **20/20** and decoding of the same messages by Claude was **20/20** correct. The token comparison below is the dated measurement of that release; the new Worker's reply contract and predecessor results are counted separately.

In a synthetic packet of 64 messages, the **receiver input tokens, vocabulary and required context included**:

| Tokenizer | Short text | Compact JSON | OZ/2 |
|---|---:|---:|---:|
| o200k_base | 1,791 | 1,250 | **814** |
| cl100k_base | 1,790 | 1,248 | **760** |

In this example, a reduction of **54.6-57.5%** against short text and **34.9-39.1%** against JSON. In small packets text/JSON can win; the selector uses it. Moving 48 jobs in six fields from separate inputs into 6 batched inputs gave about **72%** reduction; in this separate comparison, removing the repeated context was decisive. Real task success or total API speedup was not measured. [Method and limits](../reports/OZ2-RESULTS.md).

```powershell
python -X utf8 -m examples.oz2_demo
python -m unittest discover -s tests -v
python -X utf8 -m oz_cli decode --channel examples/oz2-channel.json V
```

The local demo delivers independent jobs in batches, holds the review agent until the ACK of its predecessors and handles the status record without a model call. It does not run real tools/tests.

Install: `python -m pip install .`. Commands: `oz decode`, `oz prompt`, `oz pack`. Optional install for token measurement: `python -m pip install ".[benchmark]"`.

```powershell
oz pack --channel examples/oz2-channel.json --messages examples/oz2-messages.json --encoding o200k_base --encoding cl100k_base --max-tokens 1200
```

To connect to your own agent: [OZ/2 contract and examples](../OZ2.md), [working demo](../examples/oz2_demo.py), [portable channel](../examples/oz2-channel.json). The core needs no provider account/key; the model and tool adapter belong to the host. The existing Orchestra Board or other projects are not changed automatically.

AKOR is an independent prototype for different models to share tasks, findings, questions, proposals and results in short, auditable messages. Below, the earlier **AKOR/1** text format, which is still supported, is described. Current OZ/2 usage is in a separate document; the live pilots belong to the OZ language.

## What does a message look like?

```text
do T1 lead>coder {"v":1,"goal":"Zaman aşımını düzelt.","refs":["R1"]}
ask T1 coder>lead {"v":1,"q":"Sınır her deneme için mi toplam süre için mi?"}
offer T1 lead>coder {"v":1,"change":"Her denemede 5 saniye; iki tekrar korunsun."}
done T1 coder>lead {"v":1,"result":"Değişiklik hazır.","check":"not_run"}
```

`do`: task. `T1`: task id. `lead>coder`: sender and receiver. `v`: the context revision of the task. `R1`: the immutable reference of the shared task definition, constraints or evidence. The content can be in Turkish, English or another language.

| Command | Meaning | Required body fields (besides `v`) |
|---|---|---|
| `do` | Give a task | `goal` |
| `fact` | Report a finding or inference | `claim`, `state` |
| `ask` | Ask about an uncertainty | `q` |
| `need` | Request a missing reference | `ids` |
| `offer` | Propose a change | `change` |
| `review` | Review a specific proposal/result | `on`, `verdict`, `reason` |
| `block` | Report a blocker | `why` |
| `done` | Report the result and check status | `result`, `check` |
| `stop` | Report a stop request | `why` |

`fact.state`: `observed`, `inferred`, `unknown`. An observation requires an evidence reference; having a reference does not prove the claim is true. `done.check`: `passed`, `failed`, `not_run`. A test that was not run is explicitly `not_run`. `review.on` is the id of the message being reviewed; the `verdict` value is `pass` or `fail`.

## Where do the tokens go down?

- A short, fixed header is used instead of long metadata fields.
- Unprocessed messages go to the relevant agent instead of a full conversation transcript.
- Long shared information is shared with immutable references. If the definition is already in the receiver's context, it may not be added again.
- If the task context, the needed evidence and the target of the review are missing, the packet includes them. In a new model session, or one whose context was summarized, the reference definitions are sent again.
- Agents are asked to give new information, to ask about important uncertainties and to stop when a task is completed.

These last behavior rules are model instructions. The transport does not force content quality or that the model stops. Numbers, units, file locations, negative conditions and uncertainties are not deleted for the sake of brevity.

Character count is not token count. In this project, [OpenAI's tiktoken library](https://github.com/openai/tiktoken) was used for real token counting. The results are valid only for the chosen tokenizer and examples.

## Try it now

The core uses Python 3.10+ and the standard library; it needs no model account or API key.

```powershell
cd akor
python demo.py
python -m akor validate examples/demo.akor
python -m akor decode examples/demo.akor
python -m unittest discover -s tests -v
```

The demo passes six messages between two fake agents. The test results in it are synthetic examples that are clearly marked; the demo does not call a real model or fix a file.

Optional local package install: `python -m pip install .`. After installing, the command `akor validate examples/demo.akor` can also be used. To import from outside this folder, you can install the package or add the module to your own project.

## Connect to your own agent system

1. Add the contents of [prompts/agent.txt](../prompts/agent.txt) to each agent's system instructions. The model used, the agent id, the task and the permissions are determined by the adapter.
2. Create a `Hub` for each work session. Write the goal, constraints and current decisions of the task into a short reference; bind it with `set_task`.
3. Validate every line coming from the model with `post`. Determine the sender from your own session, not from the model's claim; use the same message id on a retry.
4. Give the `prepare` output to the relevant model. Call `ack` when the message has been processed. Do not give an ACK on a failed model call; the same packet can be prepared again.
5. If the references that are actually present in the target model session are known, specify `retained_refs`. If you are not sure, keep the default empty value.

```python
from akor import Hub

hub = Hub(["lead", "coder"])
hub.add_ref("R1", "Amaç: zaman aşımı ekle. İki tekrar korunsun. Birim: saniye.")
hub.set_task("T1", 1, ["R1"])

hub.post("m1", 'do T1 lead>coder {"v":1,"goal":"İstemciyi incele.","refs":["R1"]}',
         sender="lead")
packet = hub.prepare("coder", max_bytes=16384)
model_input = packet.render()  # Send to your own model adapter.
# After the model call and the processing of the reply complete successfully:
# hub.ack("coder", packet.ids)
```

A packet budget can also be applied with a real tokenizer:

```python
packet = hub.prepare("coder", max_tokens=1200, count_tokens=your_token_counter)
```

This budget covers only the packet. The system instructions, model output, tool calls and thinking tokens are budgeted separately. If the budget is exceeded, the content is not silently truncated; an error is returned. Answering a `need` message, verifying the source and giving the model the needed content are the adapter's responsibility.

The interface contract for the adapter is in [PROTOCOL.md](../PROTOCOL.md). No ready-made OpenAI, Claude, Gemini, CrewAI or LangGraph connection was added; the core is independent of them.

## Measurement and limits

Two synthetic conversations, English code and Turkish materials data, were counted with `o200k_base` and `cl100k_base`. Every format carries the same fields, references and content. The comparison includes both a short JSON object and a more economical JSON array. The measurement that recounts the language instructions and the required context on every call is reported separately.

Results and method: [reports/RESULTS.md](../reports/RESULTS.md). Raw counts: [reports/token-counts.json](../reports/token-counts.json).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-benchmark.txt
.\.venv\Scripts\python.exe benchmark.py --output reports/token-counts.json
```

The measurement dependency is installed only in the virtual environment inside the project. The tokenizer may download vocabulary files on first run; they are kept under `.token-cache`. The example content is not sent to a model provider.

The AKOR/1 `Hub` transport is in memory; it is lost when the process exits. For OZ/2, a separate `oz_runtime.Inbox` provides a persistent queue. The package is not a network server, a ready provider adapter or a service that enforces tool authorization. `do`, `review pass` or `done` alone does not run a tool, grant user permission or close a task. Agents and sources are treated as untrusted content.

In the first live pilot, the same tasks should be run as short prose, JSON and AKOR, and the success rate, misunderstandings, correction rounds, latency and the provider's total usage should be compared. A lower message token count alone does not mean a lower total cost or a better result.
