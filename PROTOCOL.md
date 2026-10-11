# AKOR/1 specification

Status: experimental, version 0.1.0. This file defines the language independently of the Python reference implementation. It does not claim a novel underlying compression algorithm or universal model compatibility.

## 1. Agent wire record

```text
operation SP task SP sender ">" recipient SP json-object
```

The record is a single UTF-8 line, at most 8192 bytes. Header spaces are single ASCII spaces. IDs match `[A-Za-z][A-Za-z0-9_-]{0,31}` and are case-sensitive. A JSON string may contain escaped newlines; a raw newline cannot occur in a record. Markdown fences, comments, duplicate JSON keys, nonfinite numbers and unknown fields are invalid. JSON object field order is not significant for parsing; send compact JSON. A transport retry must reuse the same field order and values to match the reference relay's canonical identity check.

The JSON body always includes `v`, an integer from 1 to 2147483647: the task revision, not the protocol version. `refs` is an optional list of at most 32 unique reference IDs. All required text fields must be nonempty strings. Unknown operations and enum values fail validation.

| Operation | Required fields besides `v` | Additional rules |
|---|---|---|
| `do` | `goal` | Delegation request; no implicit tool authorization |
| `fact` | `claim`, `state` | `state`: observed/inferred/unknown; observed needs refs |
| `ask` | `q` | Resolve ambiguity before dependent work |
| `need` | `ids` | 1–32 unique reference IDs; these may be unknown |
| `offer` | `change` | Proposal, not an applied change |
| `review` | `on`, `verdict`, `reason` | `on`: transport message ID; verdict: pass/fail |
| `block` | `why` | Work cannot proceed; host resolves the dependency |
| `done` | `result`, `check` | check: passed/failed/not_run; passed/failed needs refs |
| `stop` | `why` | Stop request; host decides termination policy |

Natural-language strings can be in any language. Preserve exact numbers, units, negations, constraints, identifiers and uncertainty. The syntax is reversible; shortening the natural-language content is not automatically lossless. Never replace precise evidence with a vague summary solely to meet a token budget.

## 2. Host packets and identity

The host binds the protocol version and authenticates each peer through its own adapter. One `Hub` instance represents one isolated session. The agent cannot assign transport IDs, replace reference definitions, or authenticate itself using its own `sender` field. The adapter passes its known identity to `post(..., sender=...)` and assigns a stable message ID such as `m1`.

```text
AKOR/1
ref R1 "Task goal, constraints and current decisions."
ref R2 "Pinned source excerpt including file/revision/units."
seen m1 offer T1 lead>coder {"v":1,"change":"Use 5 seconds per attempt."}
m2 review T1 coder>lead {"v":1,"on":"m1","verdict":"pass","reason":"Preserves retries."}
```

`ref ID JSON-string` is a host-only definition. `seen ID record` is host-only historical context; it is not new work and must not be executed again. Ordinary packet records prepend a transport message ID. The model emits only agent records, never packet wrappers. The Python CLI parses agent records, not whole host packets. Use the API's `Packet.render()` for outgoing host packets.

There is no wildcard recipient or broadcast in v1. Use explicit routing. Authentication, privacy, authorized membership and operating-system permissions belong to the adapter, not to the text language. Host-only prefixes are presentation boundaries, not protection against semantic prompt injection.

## 3. References and context retention

References are immutable within a session. `add_ref("R1", text)` records a SHA-256 digest locally. Repeating exactly the same definition is allowed; different content requires a new ID. The digest is not repeatedly injected into model text and does not prove the source's truth. There are no implicit nested references: each definition must contain the necessary excerpt, or the message must name all required refs explicitly. Maximum definition size: 65536 UTF-8 bytes.

`set_task(task, revision, context_refs)` binds one or more immutable references containing the task's goal, constraints and current decisions. The host must keep this brief sufficient for the next assigned step; the relay cannot infer omitted dependencies from prose. Every prepared message includes missing task refs and message refs. A review also includes the original offer/done in `seen`, plus its refs, so a stateless recipient can understand what was reviewed.

Default `prepare(peer)` assumes no retained references. `retained_refs` may omit definitions only when the adapter knows those exact definitions are present in the actual context supplied to that model call. A prior ACK is insufficient. Clear retention assumptions after truncation, summarization, process restart, model-context reset or session change. A retained conversation may still be counted and billed by the provider on every call; retention is not free tokens.

`need` requests an unknown or unavailable definition. The relay delivers the request; it does not retrieve files, browse links or invent missing definitions. The host resolves the source and supplies a new packet or revised task context. Unknown IDs in `refs`, unlike `need.ids`, are rejected.

## 4. Delivery, retries and revision changes

`post(message_id, record, sender=known_peer)` checks structure, peers, task revision and reference availability. Identical retries under the same message ID return successfully without queueing again. Conflicting reuse fails. IDs are session-scoped and must not be regenerated for each retry. The reference relay treats differently ordered JSON body fields as a conflicting retry; adapters should reuse the original record.

`prepare(peer)` returns unacknowledged messages only. It does not mark them processed. `ack(peer, ids)` is allowed only for messages previously prepared for that peer; it is idempotent. An invalid ACK batch is rejected atomically. An empty inbox renders an empty string: do not call the model for it.

Only ACK after successful model processing and handling its output. A failed call can retry the same messages. This offers at-least-once delivery, not transactional or exactly-once tool execution. External side effects need separate idempotency controls. The in-memory reference implementation is not thread-safe, durable or distributed.

A review must target a delivered `offer` or `done` addressed to the reviewer, at the same task and revision, and return to the original sender. This binds the review to a specific item; it does not establish reviewer independence or validate the reasoning.

Changing task context requires a higher revision and processing the task's pending messages first. Older new submissions then fail. An identical retry of an already recorded message remains a no-op after revision advancement. Do not ACK unprocessed work just to advance a revision. If a task must be abandoned, the host can archive/discard that session and create a new one; v1 has no queue-cancellation API.

## 5. Budgets and repair

`prepare(max_tokens=N, count_tokens=callable)` requires a real tokenizer supplied by the adapter. A byte limit is separate from a token limit. Exceeding either limit fails before changing delivery state; it never truncates constraints, evidence, or negations. Limits cover packet text only, not the bootstrap, model output, tool schemas or reasoning.

The adapter should reserve budget for these other components, avoid unnecessary recipients, and stop repeated no-progress rounds. Repeated schema errors should produce one concise repair request naming the invalid field; if the model still fails, fall back to explicit natural language or stop. Fallback requests, repair responses and protocol prompts must be counted in real evaluations. The Python relay does not automatically loop or retry a model.

## 6. Minimal adapter contract

The runtime is model-neutral. An OpenAI/Claude/Gemini/local-model adapter can implement the same sequence:

1. Establish a supported version and peer identity before sending tasks. Unsupported versions must be rejected; automatic negotiation is outside v1.
2. Supply `prompts/agent.txt`, peer identity, and `Packet.render()` as appropriately separated system/user inputs for that provider.
3. Parse every complete output line using `parse`. Never execute arbitrary returned text.
4. Authorize the requested action independently. Validate evidence, ownership and tool permissions in the host.
5. Assign stable transport IDs, route valid records, and ACK processed input only after output handling succeeds.
6. Keep active decisions in task context; record provider-reported input/output/reasoning/cached usage where available.

For non-Python implementations, port this grammar, validation rules and delivery semantics. JSON records or arrays may also be used internally; custom punctuation is not essential to the routing and context-reuse design.

## 7. Evaluation boundary

The bundled tests verify parsing, reference integrity, targeted routing, retries, stale revisions, ACK boundaries and budget handling. They do not prove models follow the language. Evidence labels and review results are assertions by agents until independently checked.

The token experiment uses two synthetic conversations with equal content and two explicit encodings. It compares AKOR, compact JSON objects, and compact JSON arrays, with identical delta routing and reference definitions. Bootstrap cost is separately visible and included on every stateless delivery. The replay experiment adds previously processed messages for the same recipient and is labeled as an inefficient ablation.

Before deployment, use held-out tasks and multiple models. Compare task accuracy, preservation of constraints, parser errors, missing evidence, repair rounds, latency and total provider usage against concise natural language and JSON. Keep a protocol only if savings survive quality and repair costs. See [tiktoken's documentation](https://github.com/openai/tiktoken) for tokenizer behavior; text-token counts are not universal provider bills.
