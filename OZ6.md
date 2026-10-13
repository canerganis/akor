# OZ/6: two-way short communication

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

OZ/5 compresses the shared workflow and its parameters. OZ/6 adds a **short reply format** to it: the agent can answer without rewriting the task id and the same status code in every result. The full result text, error details and uncertainty are preserved. Package version 0.8.0.

## Structure of the reply

Let the task order that the trusted adapter knows for that delivery be `["incele", "test", "oner"]`:

```json
{"q":"0123456789abcdef","s":0,"v":["İnceleme sonucu","Test sonucu","Öneri metni"]}
```

`q` is the reply id for that call, 16 lowercase hexadecimal characters; the model returns the value given in the prompt exactly. The positions in the `v` array are bound to the delivery order. `s:0` means that **status 0 is explicitly reported for all results**. A missing field is not success.

If the statuses differ:

```json
{"q":"0123456789abcdef","s":[0,1,2],"v":["İnceleme sonucu","Geçici hata nedeni","Kalıcı hata nedeni"]}
```

The status codes do not change: `0` is a completion report, `1` is a retryable error, `2` is a permanent error. Each task needs one non-empty result. If an `s` list is used, its length must also match the task count exactly. A boolean, an unknown status, a missing or extra result or a wrong `q` makes the whole reply invalid. An invalid reply does not unlock dependent tasks.

This does not prove that a result is correct. The agent's "completed" report and the actual verification of the test/evidence stay separate. If a model swaps the places of two result texts and returns the right number of values, a format check alone cannot detect it; a separate meaning check is needed. `q` catches wrong reply matching across calls; it is not an authentication signature.

## Transport

```powershell
oz plan --workspace .oz-runtime/ekip --reply-mode lanes --show-prompt
oz run --workspace .oz-runtime/ekip --adapter adapter.json --reply-mode lanes
```

`lanes` is chosen explicitly. The existing `rows` behavior is the default; old adapters are not silently moved to the new contract. A `lanes` request carries `oz.adapter/2`, `receipt`, the ordered `ids`, `prompt` and the measured input tokens. The adapter must pass the `prompt` text to the model, then parse and return the model's short JSON reply. Optional provider `usage` information can be added in the same format as the earlier contract.

Every call/retry produces a new `q`. The real `q` and the reply grammar are **counted in the input budget before jobs are taken from the queue**. No free text is added afterwards. The `plan` preview and `run` use different reply ids; the real run is measured again. Only tasks that got a transient error are retried; completed sibling tasks are not sent again.

Python:

```python
worker = Worker(inbox, channel, adapter, counters=counters, reply_mode="lanes")
result = worker.run_once()
```

`oz_reply.validate_lanes(reply, delivered_ids, receipt)` converts a validated reply into the old `results` rows. `encode_lanes` does the reverse. If the adapter shortens the old long reply after getting it from the model, **the model's output tokens are not saved**; for that, the model must produce the short format directly.

`oz compile --worker` still measures the default rows reply contract. The real input budget for using `lanes` must be measured separately with `plan/run --reply-mode lanes` or `reply_contract(receipt)`. For a single job, the new contract and reply id can increase the total cost; do not look only at the shortness of the body.

## Measurement scope

Total efficiency is evaluated **by the cost of all calls per successful job**: input, output, tools and retries are tracked together. If the provider reports thinking tokens inside output and cache tokens inside input, they are not added a second time. Local vocabulary measurements alone are not live cost/speedup. The CLI system and tool context can be much larger than the protocol text.

The local and live verification of this version is run by Luna subagents. The results are reported separately: [reply format](reports/OZ-REPLY-RESULTS.md), [OZ/5 comprehension](reports/OZ5-LIVE-LANGUAGE.md), [code repair pilot](reports/OZ5-LIVE-CODING.md). Failed/missing attempts and compliance with the strict output contract are kept separate from meaning equivalence.
