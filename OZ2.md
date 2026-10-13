# OZ/2: combined meanings and persistent transport

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

For the current 0.4.0 workspace, automatic packing, transfer of predecessor results and the Worker adapter, see the [usage guide](USAGE.md). The language contract below is kept; the queue API was extended in a backward-compatible way.

Package 0.3.0. The [OZ/1](OZ.md) atoms are kept; `r` can now also read a procedure as a source. Capital ASCII letters are macros only if they are defined in the channel vocabulary. A channel without macros rejects a `V` message.

## Meaning macros

```python
from oz import Atom, Codebook, Macro

book = Codebook([
    Macro("V", (Atom("r", 0), Atom("a", 0), Atom("t", 14))),
    Macro("P", (Atom("r", 13), Atom(">", 12))),
])
```

The `0` in the definition is the placeholder of the single parameter; it is not a valid reference on the wire. The vocabulary is bound with `Channel(..., codebook=book)`.

| Message | Full expansion |
|---|---|
| `V7` | `r7a7t14` |
| `V` | `r7a7t14` if the active reference is 7 |
| `P` | `r13>12` |
| `VP` | `r7a7t14r13>12` if the active reference is 7 |
| `V+8.` | Expand the macro; report the success of the existing test report 8; report the step completion |

A macro consists of 2 to 16 base work atoms: `a`, `r`, `t`, `>`. Nested macros, literals, evidence and status atoms are not accepted into a definition. A bare `V` hides no claim of success, approval or completion. Fixed references must exist and be of the correct type. A definition that asks for both a patch and a procedure from the same parameter is rejected.

The frame limit including the full expansion is 64 atoms; the wire limit is 8192 UTF-8 bytes. An unknown macro is not guessed. Giving an argument to a macro without parameters, such as `P7`, is an error. The operation order does not change; repeated jobs are not deleted on their own. New information that is not in the vocabulary is carried verbatim with `:full text`.

The vocabulary, the atom type rules, the goal, the full reference contents, the active reference, session/task/revision and routing are bound to the channel fingerprint. Changing a definition requires a new channel. The fingerprint provides no authentication or encryption; it is carried by the trusted host. Giving only the hashes of the references does not mean the model is assumed to know the content.

## Encoder and receiver input

`Channel.encode` takes the exact meaning tree. It creates bounded candidates for the base spellings, dropping the active reference and exactly matching macros. The default is 256 candidates, the upper limit 4096. The fully explicit spelling and the byte-shortest candidate are always evaluated. The tokenizer counts each full message; the decision is not approximated by summing part costs.

There is no guarantee of the fewest tokens over all possible spellings. Without a counter, only the byte length is used. With several counters, the highest count and then the total are minimized; this is not a dollar cost optimization.

`oz_batch.render` combines 1 to 64 independent messages that belong to the same channel. Plain text, short text that preserves meaning, compact JSON with an operation contract, OZ with a vocabulary and base OZ with a vocabulary are measured. Each is tried with reference objects and with reference arrays that have defined fields.

The text, source, status, numbers, units and uncertainty of a reference stay exactly the same. Literal messages are escaped with JSON and separated as data; a `V` or line breaks inside them are not new commands. The task goal, the active reference, the required sources and the vocabulary are included in the measurement of every candidate. The earlier API context is not assumed to be kept free; in a single input the shared source is present once.

```python
from oz_batch import render

packet = render(channel, [("j1", "V"), ("j2", "P")],
                counters=[count_for_model], max_tokens=1200)
packet.text          # Receiver model input
packet.tokens        # Total for each counter
packet.alternatives  # Cost of the other full input options
packet.wires         # Optimized message bodies
```

`count_for_model` is the target tokenizer counter. `max_tokens` applies to each counter and `max_bytes` to the whole input. A packet that does not fit raises an error; the content is not truncated. The host must prepare a smaller packet. The sender instructions, history, replies, thinking, tools and provider wrappers are measured separately.

## Persistent transport and agent dependencies

`oz_runtime.Inbox(path)` uses SQLite/WAL. A separate thread/process must open its own `Inbox` connection. Do not share a single connection between threads.

```python
from oz_runtime import Inbox

with Inbox("agent-inbox.sqlite") as inbox:
    inbox.post(channel, "job1", "V", binding=channel.binding)
    inbox.post(channel, "job2", "P", binding=channel.binding, after=["job1"])
    delivery = inbox.claim(channel, owner="worker", lease_seconds=120)
    if delivery:
        packet = delivery.prepare(channel, counters=[count_for_model], max_tokens=1200)
        # replies = your_provider(packet.text)
        # After validating and processing the reply, with ID -> result text:
        # inbox.complete(delivery, {"job1": replies["job1"]})
```

This is an adapter example; the `channel`, the tokenizer and the provider call come from your application. Full local demo: [oz2_demo.py](examples/oz2_demo.py). Making sure the sources and the vocabulary are present in the sender model's real context is also the adapter's job.

| API | Behavior |
|---|---|
| `post(..., after=[...])` | Resolves, checks type/status, saves persistently |
| `claim(..., kind="work")` | Atomically delivers jobs whose dependencies are finished |
| `claim(..., kind="host")` | Delivers only status/source request events |
| `complete(delivery, {id: result})` | Records all results and ACKs in the same transaction |
| `retry(delivery, reason)` | Re-queues on a transient error; marks as failed if the limit is reached |
| `retry(..., permanent=True)` | Records a permanent failure |
| `renew(delivery, lease_seconds=...)` | Extends the time of a delivery that is still valid |
| `inspect(id)` | Returns status, attempts, result, error and the expected predecessors |
| `channel(binding)` | Restores the registered channel and verifies the fingerprint |

A message ID is unique across the whole `Inbox`. If the same ID and meaning are sent again, `False` is returned and no new record is opened. If `V` and `r7a7t14` are equivalent, it is the same resend. If the ID is the same but the meaning, channel, predecessors or attempt limit differ, it is rejected. The same text under different IDs is kept as separate jobs.

Dependencies point to messages added earlier in the same session/task/revision. The sender/receiver can differ: a reviewing agent can wait for a working agent. Forward references and self-dependency are rejected; this insertion order cannot create a cycle. A predecessor being `done` is the adapter's result record and ACK; it is not a confirmation of correctness. A failed predecessor holds the dependent job; `inspect(...)["waiting_for"]` shows the reason. The repair decision is the host's.

A delivery carries a random lease id, an owner and an expiry time. Two connections cannot take the same pending job together. When the time expires, the next `claim` reopens the job; the ACK of the old reply is rejected. There are three attempts by default; a timeout also consumes an attempt. On a long model call, `renew` is needed in time. A budget error must be fixed before the model call.

If a job and a status are in the same frame (`V+8.`), the status is not applied first; the whole frame stays in work delivery, in order. Status-only frames are in the host queue; recording them does not ask for a model call. `/` does not stop the task without a host decision; `+` does not prove the source is correct.

**Delivery is at least once.** A process can close after running an external tool without writing the ACK. A redelivery can repeat the external effect; the tool adapter must use the message ID as an idempotency key. The queue is not authorization, source correctness, network security or a task quality check. The SQLite file keeps the task content in plain form; external sharing is managed by the host.

## Portable manifest and CLI

`channel.snapshot()` returns JSON data; `Channel.from_snapshot(...)` verifies it again. [Example channel](examples/oz2-channel.json).

```powershell
oz prompt --channel examples/oz2-channel.json
oz decode --channel examples/oz2-channel.json V
oz pack --channel examples/oz2-channel.json --messages examples/oz2-messages.json --encoding o200k_base --max-tokens 1200
```

`decode` and `prompt` have no dependencies. Optional tokenizer for `pack`: `python -m pip install ".[benchmark]"`. None of them runs the model/tools. A bad frame, manifest or budget produces exit code 2.

## Verification

```powershell
python -m unittest discover -s tests -v
python -X utf8 -m examples.oz2_demo
python -X utf8 oz2_benchmark.py
python -X utf8 oz_live_eval.py --suite oz2 --live
```

The last command consumes real model usage on the existing Codex and Claude CLI accounts; it sends only synthetic examples. Without `--live` it prints the prompt. It creates no key and changes no global settings. [Results](reports/OZ2-RESULTS.md).

Because 0.3.0 also added the type rules to the fingerprint, resynchronization with 0.2.0 channel ids is needed. OZ/1 and AKOR/1 syntax is supported; the earlier reports are dated 0.2.0 evidence.
