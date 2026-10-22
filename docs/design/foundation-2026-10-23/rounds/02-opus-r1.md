# AKOR foundation decisions, round 1: Opus 5.5

Independent round 1, written before reading Astra's round 1. Date: 2026-10-23.

Read: found_pack.md, OZ9.md, docs/design/brainstorm-2026-10-22 (README, pilot plan, 00 and 02 to 05), the core code
(oz.py, oz_batch.py, oz_reply.py, oz_runtime.py, oz_worker.py, oz_workspace.py, oz_cli.py), the shipped Claude adapter
(examples/claude_cli_adapter.py), the live runners (bench/live/run_live.py, bench/live/pilot2.py) and the step-2 pilot
data in the working tree. No model was called and no repository file was changed.

Conventions: MUST, MUST NOT, SHOULD and MAY as in OZ9 1. "Keeps OZ9 x.y" means that clause stands unchanged. File
references are to branch oz-0.9 at 3cebfda. Token counts are billed tokens from provider usage unless stated.

## 0. Evidence the pack did not contain

### 0.1 The step-2 pilot has finished

The pack says the pilot is running. Its three data files are complete in the working tree (57 records per model),
not yet committed or reviewed. I recomputed them offline with `bench/live/pilot2_report.py`.

| Model | Arm | Correct jobs | Tokens per verified job | Median s per 16 jobs |
|---|---|---:|---:|---:|
| Sonnet 5.5 | H: OZ/1g, one call | 48/48 | 200.5 | 12.9 |
| Sonnet 5.5 | J: plain JSON, one call | 48/48 | 245.1 | 9.9 |
| Sonnet 5.5 | P: one call per job | 34/48 | 2,793.4 | 115.5 |
| Sonnet 5.5 | S: one subagent per job | 48/48 | 8,616.6 | 38.7 |
| Opus 5.5 | H | 48/48 | 196.6 | 9.4 |
| Opus 5.5 | J | 48/48 | 233.2 | 11.4 |
| Opus 5.5 | P | 25/48 | 3,737.2 | 115.6 |
| Opus 5.5 | S | 48/48 | 8,247.0 | 50.0 |
| Haiku 5.5 | H | 48/48 | 272.3 | 12.3 |
| Haiku 5.5 | J | 48/48 | 300.9 | 12.5 |
| Haiku 5.5 | P | 31/48 | 3,471.2 | 115.1 |
| Haiku 5.5 | S | 39/48 | 9,518.7 | 33.5 |

Both preregistered gates resolve. Attribution: H beats J on every model (18.2%, 15.7% and 9.5% fewer tokens per
verified job), so that part is OZ's. Everything beyond it (about 13x to 19x against P, 35x to 43x against S) is
batching. Expansion: H's correct jobs are at least P's and S's on every model at lower cost, so the frozen rule calls
for the 64-job Sonnet repeat.

Four findings matter for the foundation more than the headline:

1. Fixed cost per call. A one-job call (P) costs a median 1,837 to 1,865 input tokens. A 16-job plain JSON call costs
   2,970 to 2,998, so plain JSON adds about 75 input tokens per job; a 16-job OZ/1g call costs 2,603 to 2,629, about
   50 per job if its fixed part equals P's. Output on H is 34 to 105 tokens per job including thinking.
2. One-job calls leave the format. In P, Sonnet returned 3 unparseable and 11 parseable but wrong replies of 48, Opus
   16 and 7, Haiku 0 and 17. The wrong ones carry an explanation instead of the bare value
   (`"unknown: uncertainty is unknown, so ..."`). Batch size changes model behavior.
3. Subagents cost about 6.4k to 7.9k input tokens per job (S median input per run divided by 16), including the
   orchestrator. Even after charging the orchestrator a generous 40k per run, about 5k per job remains.
4. The incumbent is at-least-once too: Opus spawned 17 subagents for 16 jobs on two of three seeds.

### 0.2 Code facts that bind the decisions

| Fact | Where | Decision |
|---|---|---|
| Whole-reply acceptance is the only acceptance layer; the ledger always writes `semantic_verified: false`. | oz_reply.py:122-239, oz_worker.py:290-292 | D2 |
| The 64 KB per-result limit is enforced inside the wire parser. | oz_reply.py:165-171 | D2.4 |
| The receipt is allocated before claim and attempts are charged at lease, before any process exists. | oz_worker.py:190-191, oz_runtime.py:343-348 | D3.2 |
| Fencing is a batch lease token plus deadline; a settle after expiry raises and the paid reply is dropped. | oz_runtime.py:367-377 | D3.3 |
| Adapter stdout is a pipe; the raw reply is never stored (sha256 only); the ledger is JSONL written outside the SQLite transaction. | oz_worker.py:54-96, 151-160, 248 | D5 |
| Packet compatibility is the channel binding, a hash over a random session, goal, refs and codebook. | oz.py:274-277, oz_runtime.py:226-234 | D7 |
| Predecessor results are re-serialized from floats: `{"len":12.50,"u":0.020}` reaches dependents as `{"len":12.5,"u":0.02}`. I ran this through `regroup` on the current code. | oz_reply.py:48-53, 228-236; oz_runtime.py:297-308 | D12 |
| The shipped Claude adapter and the live runner read the CLI's last-turn `usage` and drop thinking. | examples/claude_cli_adapter.py:11-15, bench/live/run_live.py:120 | D8 |
| Insertion is exactly once by caller ID plus an identity digest. | oz_runtime.py:185-214 | Kept, D1.5 |
| No graph, registry, memo, dedup or effect execution exists; `process_host` only records events. | oz_worker.py:314-326 | D3.5, D4, D6 are new code |

## 1. Six laws

These are the physics the decisions follow. Each is a measurement or a definition.

**L1 Cost.** On `claude -p`, T(call) ≈ F + Σ over jobs of (m_in + m_out) + R. F ≈ 1.8k input tokens (CLI overhead,
system text, framing), m_in ≈ 50 and m_out ≈ 35 to 105 per job on OZ/1g, R is reasoning that does not scale with
jobs. A subagent costs about 5k to 8k per job. Teaching is paid per call (H is inside F); amortization comes from
batch width, not from sessions. Order of levers: calls and subagents removed per verified job, then reasoning on
small models (thinking is 80% of Haiku's H output, 38% to 42% on Opus and Sonnet), then packet compactness (10% to
18% over batched JSON).

**L2 Identity.** The call is the unit of cost. The job is the unit of identity, acceptance, retry and reuse. The
packet is transport.

**L3 Truth.** The host decides binding, acceptance and accounting. Model text is a claim, and every accepted value
carries the scope of the checks that actually ran.

**L4 Boundary.** Model-visible bytes change only through versioning and qualification. Host behavior changes through
tests and paired measurement.

**L5 Durability.** Anything that cost tokens is durable before it is interpreted, so a crash never forces paying twice
for the same reply.

**L6 Context.** A byte placed in a calling agent's context is paid again on every later turn of that session (the
pilot orchestrator's last turn alone read 20k to 49k tokens). Bulk inputs and outputs stay host-side; the agent reads
only what it must.

## 2. Decisions

### D1. Units and identities

**Decision.**

D1.1 Six units:

| Unit | What it is | Identity | Content-addressed | Lifecycle |
|---|---|---|---|---|
| Request | One caller submission: a run with targets, deadline and budgets. | `run_id`, host-generated; optional caller `request_key` | No | Targets fixed at start (keeps OZ9 1: requested work defined before measurement) |
| Node | A named application of one registered op in a run graph. | (`run_id`, `node_id`) | No, a name | Immutable after install; retired, never edited |
| Job | A node whose inputs are fully resolved: the exact computation. | job key K (D1.3) | Yes | Immutable |
| Attempt | One dispatch: one packet for model jobs, one handler call for host jobs. | receipt: host counter, allocated before spawn, never reused (keeps OZ9 9.2) | No | Append-only states (D5.2) |
| Effect | One externally visible change made by a host op. | E = sha256(op@version, resolved inputs, target scope, preimage digests) | Yes | Intent and outcome records, append-only |
| Result | An accepted value or valid job failure for a K, with acceptance evidence. | (K, sha256 of the value bytes) | Yes | Immutable; revocable (D4.3), never edited |

A packet is a transport container identified by its attempt's receipt. A wire job ID is a packet-local label chosen
by the host and resolved only through the dispatch record; nothing parses it for meaning (keeps OZ9 2.2: results
bind to the exact ID).

D1.2 Requested work is defined only by targets and their weights (keeps OZ9 1 and 7.3). In `oz do` (D10) each
submitted job is a target of weight 1.

D1.3 Job key. For a model job, K is the sha256 of a canonical, length-prefixed list: `akor.job/1`, the wire digest
(D9.1), the goal bytes, op name, op version, instruction bytes, the exact model-visible bytes of each input in row
order, and the route profile digest (adapter, model id, effort, CLI version). For a host job: `akor.host/1`, op,
version, handler digest, input byte digests, the declared read-set digests or the full snapshot digest when the read
set is unknown, and the environment fingerprint (keeps OZ9 6.1's conservative rule). Excluded: run, node ID, wire ID,
receipt, enqueue time, the packet's sibling jobs, and the acceptance contract, which judges results and does not
define the computation (D4.2 re-checks stored results against the current contract). This changes OZ9 6.1, which
keys on contract versions.

D1.4 Inputs flow by value, not by producer: a downstream K contains the upstream result's bytes, not the upstream
node ID. An upstream recomputation that yields identical bytes leaves every downstream key unchanged (early cutoff).

D1.5 The same `request_key` with the same request digest returns the existing run; with a different digest it is an
error. This mirrors `Inbox.post` and covers an agent that re-issues a timed-out tool call.

**Rejected.**
(a) Node ID as the result identity (today's inbox job ID): it blocks reuse across replans and runs, and makes "the
same mutation under a new ID" detectable only by policy.
(b) The batch as the identity unit (OZ9 3.3, 5.3): it ties acceptance and retry to transport composition.
(c) Content-addressed requests: two identical requests are two units of requested work; reuse belongs to jobs.
(d) Sibling jobs in K: reuse would never happen. Sibling independence is H's rule and qualification tests it with
heterogeneous packets.
(e) Value-canonical numbers in K (JCS style): 12.50 and 12.5 would share a key while the model sees different bytes.
(f) Contract versions in K: every strengthened check would pay for recomputing results that already pass it.

**Invariant.** Two jobs with the same K are interchangeable: any result accepted for K and passing the current
contract is acceptable for every node that resolves to K.

**Falsified by.** Re-running 20 memoized jobs with only excluded fields changed (new node IDs, new wire IDs, different
siblings): if oracle correctness differs beyond the spread of 20 fresh runs of the same K, K omits a behavior-relevant
input. Also: a replan that re-issues a recorded effect under a new node ID and is not refused.

**Cost.** 0 model tokens. About 120 lines (canonical encoder, key functions, columns). Hashing takes microseconds per
job.

**Code today and migration.** `jobs.id` is caller-chosen and serves as node name, wire ID and result handle.
`jobs.identity` (oz_runtime.py:194) deduplicates insertion, but it includes `max_attempts` and dependency names and
excludes predecessor values, so it is not a computation key. The `jobs` table becomes the node table; add `job_key`,
a `results` table keyed by K, and a wire ID map per dispatch.

### D2. Acceptance semantics

**Decision.**

D2.1 Three properties, never conflated:
1. W, wire-valid: the reply passed the oz1g-header parser as a whole (keeps OZ9 3.1, 3.2).
2. C, contract-valid: the record's value passes its op's registered deterministic checks (output schema,
   `max_result_bytes`, declared constraints).
3. V, verified: an independent verifier established acceptability against the job's own resolved inputs. Three
   kinds count: an oracle (recomputation or known answer), a certificate check (a quoted span present at its stated
   offset, tests passing on the produced snapshot) and host execution evidence.

Acceptance requires W and C. The recorded scope is `declared` (W, and the op has no checks), `checked` (W and C) or
`verified` (W, C and V). A model review is review evidence, never V (keeps OZ9 3.3).

D2.2 The reply level stays atomic. Any W failure, transport failure, timeout or adapter error rejects the whole reply,
and no record is accepted, including records that would pass V. H's sentence "Any malformed nonblank line or missing,
duplicate or extra ID rejects the whole reply" stays literally true.

D2.3 Inside a W-valid reply, each record is judged by its own op's checks. The fast local checks (C and local V) of all
records run first, then drift containment (D2.6.4), then one transaction commits every decided record. A passing
record is accepted; a failing record makes only its own job unresolved (retry per D3). A record whose V needs host
execution enters `checking` (keeps OZ9 9.1) and commits alone when its check completes. This changes OZ9 3.3
paragraph 4 and 5.3 paragraph 2, which retry the whole originating batch after an acceptance-check failure.

D2.4 `max_result_bytes` is a C check of the op, not a wire rule. The parser keeps only H's grammar and the total
capture limit (keeps OZ9 3.1).

D2.5 Valid job failure records keep OZ9 3.3: they fail only their job, are terminal for that K and are never retried
blindly. An op MAY declare a check of the claim itself (`missing_data` against the input's declared required fields);
a failed claim check makes the job unresolved like any C failure.

D2.6 Valid-looking wrong records (index drift):
1. Binding is by wire ID through the dispatch record only (keeps OZ9 3.3).
2. Prevention is qualification: a profile qualifies only on oracle-checked heterogeneous packets, and drift observed
   there disqualifies it (D9.2).
3. Runtime detection exists only where checks are input-bound, meaning they read the job's own resolved inputs. The
   host MUST NOT add echo fields to the wire for drift detection (joint decision of 2026-10-22).
4. Containment: if any input-bound check fails in a W-valid reply, the reply is drift-suspect. Its records below
   `verified` are demoted to unresolved and SHOULD be retried with different siblings; its `verified` records stand.
5. Scoring: the benchmark W counts only oracle-correct jobs (keeps the frozen scoring of step 1 and the pilot).

D2.7 Each target declares the minimum scope it accepts: by default `checked` when its terminal op has checks, else
`declared`. Deliverables and `oz status` report scope per target.

**Rejected.**
(a) Salvaging records from W-invalid replies, which the step 3 wording ("verified successes kept" under truncation and
malformed lines) implies. On qualified cells 0 of 100 replies were W-invalid (91 published, 9 in the pilot), so the
rate is at most 3% at 95% confidence (rule of three), and salvage would save at most about 3 tokens per job at 64
jobs. Where W failures do happen (Luna, unqualified), the same configuration produced six parser-accepted replies with
wrong values: a broken reply is evidence against its siblings.
(b) Whole-batch retry after a C or V failure: one wrong record re-runs 63 accepted ones. Retrying one job inside the
next packet costs under 200 tokens; a new call costs at least F.
(c) Parse validity as correctness: Luna's six accepted wrong replies refute it.
(d) Canary jobs or sampled oracles as runtime certification: they spend tokens on unrequested work and certify no
individual record (Astra, round 2).
(e) Echo fields: rejected jointly.

**Invariant.** No record of a W-invalid reply is ever committed. Every committed record passed W and its own C checks,
and its scope names exactly the checks that ran. A C failure never changes a sibling's state, except drift demotion,
which can only lower acceptance.

**Falsified by.** Step 3 fault injection on recorded replies: (1) any commit from a reply with an injected W fault;
(2) one injected wrong value under an oracle check in a W-valid 64-job reply, followed by anything other than exactly
that job retrying; (3) Luna's recorded replies replayed with input-bound checks, leaving a drift record committed
above `declared`. D2.2 is reopened if a qualified cell shows a W-invalid rate above 2% over at least 50 replies, or
when a bucket above 64 jobs is qualified.

**Cost.** 0 tokens on clean replies. Each C or V failure saves a full call minus one row. Drift demotion costs at
most one recomposed packet per suspect reply. Local checks take milliseconds. About 150 lines (contract registry,
check runner, scopes, demotion), plus moving the size check out of the parser.

**Code today and migration.** `parse_reply` and `regroup` (oz_reply.py:122-239) are exactly W and stay. Tests such
as `test_any_bad_line_rejects_the_whole_reply_and_every_job_retries` (tests/test_oz_worker.py:97) remain valid.
C and V are new.

### D3. Retries and fencing

**Decision.**

D3.1 The job is the retry unit. An unresolved job (after a W-invalid reply, a transport failure, a C failure or a
drift demotion) returns to the ready set with its node and K unchanged, and MAY be packed with any compatible ready
jobs. Within a job nothing is combined: its value comes from one record of one reply. This replaces OZ9 3.3 and 5.3
"retry the whole originating batch" and "preserve the original wire job IDs".

D3.2 Attempts are counted per job and charged when the dispatch reaches `spawned` (D5.2), not at claim. Default
`max_attempts = 2` per job (keeps the OZ9 value). Budgets never reset on resume (keeps OZ9 5.4).

D3.3 Commit is a compare-and-set on node state. Pure jobs are fenced by content: a record commits for node n if and
only if n is unresolved and the record's dispatched K equals n's current K, whichever attempt produced it. A late or
journaled reply can therefore complete a still-unresolved pure job; a record for an already accepted node is stored
as `superseded` and its tokens stay counted. Effectful host jobs are fenced by attempt: only the holder of the
current fencing token records an outcome. This narrows OZ9 9.2 "late responses MUST NOT complete newer attempts" to
effectful work.

D3.4 Guarantees, stated once:

| Layer | Guarantee |
|---|---|
| Request submission | Exactly once per `request_key` |
| Graph installation | Exactly once per revision (keeps OZ9 7.2) |
| Model dispatch | At least once until accepted or out of budget; at most `max_attempts` per job |
| Acceptance | At most once per node; immutable after commit |
| Delivery to the caller | At least once; reads are idempotent |
| Writes to private snapshots | Effectively once (content-addressed output) |
| Publication to the user's tree | At most once, preimage-guarded, reconcilable (keeps OZ9 4.3) |
| Registered commands | At most once unless declared idempotent; uncertain becomes `unknown_effect` (keeps OZ9 9.3) |

AKOR claims exactly once only for request submission, graph installation and per-node acceptance.

D3.5 Effects: an intent record holding E and the fencing token is durable before execution; an outcome record
follows. A node whose E equals an unresolved or completed non-idempotent effect is refused at admission and at
dispatch. This makes OZ9 9.3's last rule mechanical instead of a matter of policy.

D3.6 After a W-invalid reply, each affected job's final attempt SHOULD go out in a packet at most half the size of the
failed one, when the profile has a qualified bucket of that size, so one poison job cannot fail a full packet twice.

**Rejected.**
(a) Batch-identical retries: no correctness value once acceptance is per job, and they keep retries from sharing
packets with new work.
(b) Attempt fencing for pure jobs: it discards paid, valid results for the same K.
(c) Exactly-once claims for commands: impossible without the external system's cooperation.
(d) Retrying until success: it hides systematic failure and burns quota.

**Invariant.** Each node receives at most one committed result, never replaced. Every dispatch counts in C and its
usage in T. AKOR never executes a non-idempotent effect twice.

**Falsified by.** (1) Journaled-reply injection: attempt 1's reply delivered after attempt 2 committed must be
superseded; delivered before, it must commit and attempt 2's record must be superseded. Any double commit or overwrite
falsifies D3. (2) A crash between effect intent and outcome, followed by a replan that re-issues the mutation under a
new node ID, must be refused. (3) Ledger dispatch counts must equal the spawned processes in an OS process trace.

**Cost.** Saves one packet per late or recovered reply. Latency: a retried job leaves with the next compatible packet
instead of waiting for a batch-identical retry; the commit is one conditional update. About 80 lines now (conditional
commit, charging at spawn, per-job retry), about 60 more when host effects arrive.

**Code today and migration.** `_check` (oz_runtime.py:367-377) is batch-level attempt fencing by lease token and
deadline; `_lease` charges attempts at claim (oz_runtime.py:343-348); `settle` updates all jobs of a lease together.
`settle` becomes a per-node conditional update keyed by K, and attempt charging moves to the spawn transition.

### D4. Memo and freshness

**Decision.**

D4.1 The memo key is K (D1.3). This keeps OZ9 6.1's components with three specifics: model-job inputs enter as exact
model-visible bytes; the route profile digest includes the CLI version, because hidden CLI instructions are an input
AKOR cannot read (OZ9 6.1's conservative rule for unknown read sets); the contract version is recorded with the entry
instead of keyed.

D4.2 A hit is served only if all of these hold: K matches exactly; the entry is not revoked; the op's current
deterministic checks (C, and V when V is deterministic and local) run on the stored value and pass (extends OZ9 6.3);
the resulting scope meets the consumer's required scope; for host results with evidence, the evidence digests in K are
current. A stored V that needs host execution counts only if it was produced under the current contract version;
otherwise the hit carries the scope the re-run checks establish.

D4.3 Nothing is invalidated by deletion: a change yields a new K and therefore a miss (keeps OZ9 6.3). Explicit
revocation (`oz memo revoke` by K, op version or route profile) makes entries unservable and marks `stale` every
accepted node in open runs whose input chain contains a revoked result digest. Stale targets must be delivered again.

D4.4 Persistence is per workspace, and a workspace is a confidentiality boundary. In-flight coalescing keeps OZ9 6.2.
Only pure ops are memoized across runs; tool-free model ops are pure by construction; commands and repository
mutations are not (keeps OZ9 6.3). A valid job failure is shared within its run (keeps OZ9 6.2) and never persisted
across runs, because it is not completed work (keeps OZ9 6.3) and one wrong `missing_data` must not become permanent.

D4.5 A hit completes requested work when D4.2 holds; it adds nothing to C or T. Every report states memo state;
tokens-per-verified-job claims use a cold memo unless labeled warm; hits are reported by scope.

**Rejected.**
(a) Keying on (op, refs) alone, my round-1 O8: it serves stale answers in repository work (Astra A4).
(b) A default time-to-live: time is not an input of a pure job; a time-dependent op is impure or declares its read
set.
(c) Memoizing only `verified` results: nothing in the materials workload is V at runtime, so the memo would never
fire. Gating by the consumer's scope is enough.
(d) A memo shared across workspaces: it crosses a confidentiality boundary for little gain.
(e) Leaving the CLI version out of K: a silent change of hidden instructions would be served from memo. Including it
costs only recomputation after CLI updates (Q13 can remove it).

**Invariant.** A served hit is byte-identical to a result accepted for the identical computation, passes the current
contract's checks and is not revoked. A hit never completes an effect.

**Falsified by.** The OZ9 12.2 memo gate (exact repeats hit; every tested dependency change misses), plus: an upstream
change that leaves the upstream bytes equal must hit downstream (early cutoff); a strengthened check that the stored
value fails must miss, and one it passes must hit without a call; a revocation must turn its dependent target stale;
a `declared` hit must not satisfy a target requiring `verified`.

**Cost.** Saves the job's marginal tokens, and the whole F when an entire packet is served from memo. One indexed
lookup per job. About 150 lines.

**Code today and migration.** No memo or dedup exists. New tables (`results`, `revocations`); planning consults them
before packing.

### D5. State and checkpoints

**Decision.**

D5.1 One durable store per workspace: SQLite in WAL mode with `synchronous=FULL` set explicitly (today it is the
build default, which happens to be FULL), plus a content-addressed artifact directory written by temp file, fsync and
rename before any row refers to it (keeps OZ9 9.1's ordering rule). The call ledger moves into SQLite;
`calls.jsonl` becomes an export.

D5.2 Every dispatch has a row that moves `prepared → spawned → replied → settled`, or ends `abandoned` or `lost`.
Before spawn: receipt, packet bytes, wire ID map, job keys, route profile, wire digest. At spawn: process ID, spawn
time, attempt charges (D3.2). The adapter's stdout goes to a per-receipt capture file, not only a pipe, so a reply
that completes after a coordinator crash survives. After exit: reply bytes and the usage envelope are stored and the
state becomes `replied` before any parsing. Settling is one transaction: node commits (D3.3), results, memo rows, job
failures, attempt states and the call row.

D5.3 Crash points and resume (extends the checkpoints of OZ9 9.1):

| Crash after | Resume does |
|---|---|
| `prepared`, before spawn | Marks it `abandoned`; no attempt charged, no dispatch counted |
| `spawned`, capture file incomplete | Waits until spawn time plus timeout plus grace, then marks it `lost` (attempts charged, usage null); MAY re-dispatch earlier when the deadline requires it |
| `spawned`, capture file complete | Treats it as `replied` |
| `replied`, before settle | Parses and settles under content fencing; no new call |
| Effect intent without outcome | Reconciles per OZ9 9.3 |
| A capture file that completes after `lost` | Consumes it as a late reply if its jobs are still unresolved (D3.3) |

D5.4 Resume is idempotent and runs automatically whenever a coordinator acquires the run lease (keeps OZ9 11.2).
Budgets, attempts and planner allowances never reset (keeps OZ9 5.4).

D5.5 Stored: raw adapter stdout (bounded), packet and reply bytes, per-model usage, results, acceptance evidence,
effect records, quota events. Not stored: stderr content (digest and length only), environment, credentials (keeps
the practice at oz_worker.py:233-243).

**Rejected.**
(a) A JSONL ledger beside SQLite (today): no atomicity with settle, so a crash between them loses usage or results
without a trace.
(b) Pipe-only capture (today): a coordinator crash during a 10 to 50 s call loses a paid reply.
(c) Re-dispatching every in-flight packet on resume: it pays twice for replies that exist.
(d) Digests without bytes (today's `response_sha256`): rules out audits and re-scoring. Step 1 needed raw data to
reproduce every published figure.

**Invariant.** Every reply that cost tokens is either settled or recoverable from durable bytes. No attempt is charged
for a dispatch that never spawned. After any crash and resume, the store equals the store of some crash-free
execution.

**Falsified by.** The OZ9 12.2 resume gate made specific: kill the coordinator at each crash point above, using a fake
adapter that sleeps, resume, and compare final state and dispatch count with an uninterrupted run. An extra dispatch
for an already replied packet, a lost commit, or an attempt charged without a spawn falsifies D5.

**Cost.** 0 tokens; saves one full call per crash after spawn. Two extra fsynced transactions per call, milliseconds
against calls of about 10 s. Storage of 10 to 30 KB per call. About 120 lines for journal, capture and reconciliation,
about 40 to move the ledger.

**Code today and migration.** The receipt and lease precede the call (oz_worker.py:190-191). A crash between claim
and settle leaves leased jobs that `_recover` (oz_runtime.py:216-224) returns to pending with an attempt spent and
the reply gone. `StdioAdapter` reads pipes with `communicate` (oz_worker.py:54-96). The ledger append
(oz_worker.py:151-160) is outside the transaction.

### D6. Plan and graph format

**Decision.**

D6.1 Keeps OZ9 7.1: plan {v, base, nodes, outputs}; node {id, op, in, after}; four binding forms; no expressions. A
node declares only its op, inputs and ordering. Checks, route, limits, purity and effects belong to the pinned op
version (keeps OZ9 4.1). Budgets and the deadline belong to the run. Priority, weight and required scope belong to
targets (extends OZ9 7.3 with scope).

D6.2 Data-dependent fan-out is a registered host op, `host.map`, not new syntax. Inputs: `over` (a binding to an
array), `op` (a literal registered op name), `as` (a literal input name) and optional `with` (a binding to an object
of fixed inputs). At runtime it installs one child `<id>.<i>` per element in one atomic graph revision. Its own
result is the array of child outcomes in order, each `{"ok":value}` or `{"error":[code,message]}`. Width counts
against the remaining node and dispatch budgets; an array that does not fit fails the map node with
`input_too_large` instead of truncating (keeps OZ9 4.3).

D6.3 Authors: callers (people, scripts, orchestrating agents) submit through `oz submit` or `oz do`; the optional
planner proposes through `oz plan` (keeps OZ9 7.2 and 8). Every proposal passes the same admission. Authority comes
only from the configuration pinned at run start (registry, recipes, routes, budgets, effect scopes), never from the
author or from model text. Workers never author nodes: a worker result can supply the array that `host.map`
iterates over, never an op, route, check or effect.

D6.4 Admission keeps OZ9 7.2 and adds four checks: (a) every model op has a route profile qualified for at least one
bucket (D9.2), unless the run is marked experimental; (b) each target's required scope is reachable by its terminal
op's registered checks, so an impossible plan fails before any call; (c) no new effect key collides with an
unresolved or completed non-idempotent effect; (d) the registry and route configuration digests are pinned into the
run at `oz start`, and later edits affect only new runs.

D6.5 Replanning keeps OZ9 9.4. A replacement node whose K equals an accepted K is served from memo, not recomputed;
effects follow D3.5.

D6.6 The planner of OZ9 8 stays unbuilt until the manual executor completes the 20-step workflow. It is then kept only
if one permitted replan beats the fixed plan on W after its planner tokens are counted (joint step 6).

**Rejected.**
(a) Checks and budgets as node fields: any author, a planner included, could weaken checks node by node, and K would
depend on author choices outside the op.
(b) An expression or template language: OZ9 7.1 excludes it, and one host op covers the measured need, which is
fan-out width.
(c) Widening the frontier through planner calls or orchestrator turns: a planner call costs at least F, an
orchestrator turn re-reads the agent's whole context (L6), and `host.map` costs 0.
(d) Different admission rules per author: when the caller is itself a model, trust in the author cannot be enforced;
rules on content can.

**Invariant.** An installed graph is acyclic, uses only pinned ops, can reach every target at its required scope, and
contains no node that could repeat a non-idempotent effect. Accepted nodes never change across revisions.

**Falsified by.** The OZ9 12.2 graph gate, plus: a planner proposal that lowers a target's scope, uses an op outside
the pinned registry, or re-issues a completed mutation under a new ID gets installed; a `host.map` over 300 items with
256 nodes of budget installs any child.

**Cost.** 0 tokens. Admission and `host.map` expansion are local transactions (milliseconds). About 350 lines for
OZ9 section 7 (installation, admission, binding resolution), none of which exists yet, plus about 80 for `host.map`.

**Code today and migration.** Dependencies are `after` lists among inbox jobs of one channel scope
(oz_runtime.py:192-206); predecessor results reach dependents as refs (`_handoffs`, oz_runtime.py:297-308, and
oz_batch.py:224-259). The jobs and dependencies tables become node and edge tables; handoffs become `node` bindings.

### D7. Scheduling contract

**Decision.**

D7.1 Readiness keeps OZ9 5.1 and adds: every dependency's scope meets the consumer's required input scope (default
`declared`), and no dependency is stale (D4.3).

D7.2 Order keeps OZ9 5.1: memo hits and coalescing, then ready host ops, then model packets. Model jobs group by a
compatibility key, the sha256 of wire digest, goal bytes, route profile, isolation policy and confidentiality scope.
Within a workspace, jobs of different runs with equal keys MAY share a packet; a run marked `isolated` never shares.
Ancestors and descendants never share a packet (keeps OZ9 5.1).

D7.3 Order within a group: caller target priority, then jobs older than 10 × `max_wait` (anti-starvation), then the
longest remaining dependency path, then enqueue order (extends OZ9 5.1). Composition is deterministic for a given
queue state and clock, so experiments replay.

D7.4 Dispatch triggers and budgets keep OZ9 5.2 and 5.4 (target 32, maximum 64, `max_wait` 1 s, one call in flight
per quota group, deadline feasibility from measured tail durations). Packet sizes stay inside the profile's qualified
buckets (D9.2).

D7.5 The scheduler MAY choose packet membership, size, timing and order. It MUST NOT change a job's op, inputs, goal,
route or effort, split a job, reorder dependencies, or dispatch beyond budgets. Routes change only by explicit caller
configuration (keeps OZ9 2: no runtime fallback).

D7.6 Estimates of F, per-job cost and call duration come from the ledger per route profile (rolling median of the last
20 calls), with configured defaults before that.

D7.7 Rate-limit events with reset times go to a per-user quota file that every workspace on the same subscription
honors (extends OZ9 5.4 beyond one workspace).

**Rejected.**
(a) Compatibility equal to the channel binding (today): the binding hashes refs and a random session, so two workflows
can never share a packet.
(b) Online tuning of batch size or concurrency: keeps OZ9 5.2's prohibition.
(c) Scheduler-chosen escalation, such as retrying on a larger model: it changes K and the meaning of acceptance. If
wanted, it is an explicit, recorded caller policy.
(d) Fair share per run: in a single-user system calls per verified job matter more, and aging bounds starvation.

**Invariant.** No packet mixes goals, routes, isolation scopes, or an ancestor with its descendant. Every dispatched
job had all dependencies accepted at sufficient scope.

**Falsified by.** The wavefront test: 16 instances of the 20-step workflow submitted together must finish in about as
many model calls as the critical path has model waves, not about 16 times the number of model steps, with tokens per
verified target below 16 sequential runs and no loss of W or deadline. If the call count stays near 16 × steps,
D7.2 is wrong or the workflow shape cannot batch.

**Cost.** 0 tokens directly; it is the main token lever for dependent work, since each call avoided saves about F. Up
to `max_wait` (1 s) of latency per wave against calls of about 10 s. About 150 lines.

**Code today and migration.** `_ready` (oz_runtime.py:226-234) filters one binding and orders by sequence; `waiting`
(oz_runtime.py:236-247) does quorum waiting for one binding; `Workspace.run` drives one channel per invocation
(oz_workspace.py:166-194).

### D8. Accounting

**Decision.**

D8.1 The adapter MUST return per-model usage aggregated over the whole invocation, with `source` and `scope`. For
Claude: `modelUsage` from the final result object (`source: "claude.modelUsage"`, `scope: "invocation"`). For Codex:
the sum over `turn.completed` events. The CLI's `usage` field covers only the last turn; it MAY be stored as a
diagnostic and MUST NOT enter totals. A route whose adapter cannot report invocation scope is not qualified, and
`oz doctor` checks it.

D8.2 Columns per call and model: uncached input, cache read, cache write, output, and thinking as a subset of output.
T = Σ (uncached + cache read + cache write + output) over every dispatch, including rejected replies, transport
failures, superseded and lost calls, planner and review calls (keeps OZ9 12.1; thinking counted once). Cache columns
are always reported separately; no price or quota weighting enters T.

D8.3 Unknown usage is null. Totals over a set containing a null are lower bounds that state the number of unknown
calls. A spawn failure before any model contact records 0 with `source: "no_contact"` (keeps OZ9 12.1).

D8.4 For packets shared by runs (D7.2), cost is allocated for reporting only: F equally per job, the rest by each
job's share of packet bytes and reply line bytes. Allocation never drives scheduling.

D8.5 Integration claims count the calling agent's tokens in every arm. The pilot's S arm includes its orchestrator;
H and J had none.

D8.6 One-time costs (qualification calls, skill text) are reported apart from per-call costs, with a break-even count.

D8.7 Quota observations are events (time, source, kind such as `rate_limited`, `reset_at` or `usage_percent`, digest
of the raw text), never inferred from tokens (keeps OZ9 5.4 and 12.1).

D8.8 Every published figure is recomputable from stored raw rows by a committed script (the step 1 standard, made
permanent).

**Rejected.**
(a) Last-turn `usage` (examples/claude_cli_adapter.py:11, bench/live/run_live.py:120): correct only for tool-free
single-turn calls, and about 7 times too low on the subagent smoke (21k against 145k input).
(b) Weighting cache reads into T: the quota weighting is unknown; separate columns keep every later weighting
possible.
(c) Treating unknown usage as zero: it favors whichever arm fails.

**Invariant.** T over any set of dispatches equals the sum of provider-reported invocation usage, or is labeled a
lower bound with its count of unknowns.

**Falsified by.** A two-turn tool-using probe whose `modelUsage` disagrees with the sum of its per-turn usage events,
or any published figure that a fresh script cannot recompute from raw rows.

**Cost.** 0 tokens and no added latency: the call row is written inside the settle transaction. About 80 lines
(adapter, calls table, export, report helpers).

**Code today and migration.** The ledger maps adapter usage fields (oz_worker.py:24-26, 308-310). The shipped Claude
adapter reads last-turn `usage` and omits thinking. Its calls are tool-free and single-turn, so its totals match
`modelUsage`, which is why step 1 reproduced exactly; the adapter still has to change before any tool-using route.

### D9. The model boundary

**Decision.**

D9.1 Frozen and digest-pinned: system text H, body fields and their order, the jobs block structure, the reply
grammar, the four error codes, parser profile oz1g-header and exact-string ID binding. The wire digest (sha256 of H's
bytes and the parser profile name) is stored with every dispatch and enters K (keeps OZ9 2 and 3).

D9.2 A route profile is (adapter, model id, effort, wire digest, batch-size bucket), with buckets of 1 to 4, 5 to 16,
17 to 32 and 33 to 64 jobs. Production dispatch uses only qualified profiles (keeps OZ9 2: no detection or fallback).
A bucket qualifies with at least 10 replies over at least 3 fresh seeds, split between its smallest and largest size
and including heterogeneous packets, with 100% W-valid replies, oracle correctness not below the batched-JSON control,
and no oracle-wrong record attributable to a wrong op or ref binding. Economic claims also need the paired trials of
OZ9 12.3. A bucket that has not qualified MAY run only in runs marked experimental, and its results carry
`unqualified_profile` in their scope.

D9.3 What may change without a wire change:

| Class | Examples | Rule |
|---|---|---|
| Host only | Scheduling, retries, acceptance, memo, accounting, storage | Tests and the OZ9 12.2 correctness gates |
| Model-visible data | Goal text, op instructions, ref serialization, ID spelling, packet composition | Op version bump where it enters K; task checks; any claimed gain needs paired measurement |
| Profile | Model, effort, bucket | Profile qualification (D9.2) |
| Wire | H, grammar, codes | D9.4 |

D9.4 A wire change needs a written rationale naming the failure it fixes, offline parser fixtures, and a
preregistered paired live qualification on every cell it will serve, against the incumbent wire, judged on
correctness first and then on T per verified job under OZ9 12.3. Old and new wires coexist; each attempt is pinned to
the wire it was sent with; there is no format detection (keeps OZ9 3.2 rule 10). No wire change is open: on qualified
cells 100 of 100 replies are W-valid, and the costs that remain (F and thinking) are not wire costs (L1).

**Rejected.**
(a) Adopting the uniform error record now: it removes a fork seen only on an unqualified Codex cell, buys nothing on
Claude and costs re-qualification of every cell.
(b) Qualifying a model at one size: the pilot's one-job calls left the format on all three models (0.1, finding 2),
so size is part of the profile.
(c) Runtime fallback to another wire or model: it hides gaps and changes K silently.

**Invariant.** Every model call sends bytes whose wire and profile are qualified for its bucket, or is labeled
experimental, and every reply is parsed by the parser of the wire it was sent with.

**Falsified by.** A qualified profile whose W-valid rate in production falls below 98% over 50 calls, or whose oracle
correctness on a held-out set falls below the batched-JSON control. Either disqualifies the profile pending
re-qualification.

**Cost.** Only qualification calls: about 10 per bucket and model, roughly 2k tokens each in the 1 to 4 bucket and 3k
in the 5 to 16 bucket. No runtime latency beyond a profile lookup. About 40 lines (profile table, digest, refusal).

**Code today and migration.** H is a constant (oz_batch.py:28-60), and `system_sha256` is already in every ledger row
(oz_worker.py:202-209). The qualification scope lives only in prose (OZ9 2, docs/design/stage-1g-release-scope.md);
it becomes a configuration table.

### D10. Integration surface

**Decision.**

D10.1 The primary contract is the `oz` CLI: JSON in, one compact JSON object out (keeps OZ9 11.4), with versioned
schemas (`akor.cli/1`). The Python API exposes the same verbs with the same schemas, is what the CLI calls, and adds
no semantics. On-disk formats (plan, registry, routes, ledger export) are part of the contract.

D10.2 `oz do` is the agent-facing verb. It reads one request from a file or stdin: goal, ops, jobs with optional
dependencies, deadline and required scope. Refs MAY be file paths or globs that the host reads (`host.read`, within
the workspace's read scope), so bulk inputs never pass through the agent's context (L6). It runs to completion and
prints, per job, the value, the error or `unresolved` with a reason, plus scope, call count, T with its columns and
memo hits. Results above a size threshold go to a file, and stdout carries a summary and the path. One fan-out MUST
take exactly one tool call of the calling agent: no polling and no second command to fetch results. Its deadline MUST
fit inside the caller's tool timeout (Claude Code's Bash default is 2 minutes); longer work uses the background flow,
which keeps OZ9 11.2.

D10.3 A Claude Code skill is the teaching layer over `oz do`. It says when to use it (enough independent jobs
answerable from supplied data without tools to beat answering inline, default 4 until Q14 measures it), how to write
the request, how to read results and scopes, and when not to use it (jobs that need tools or exploration, or a bucket
without a qualified profile). The skill makes no model calls of its own.

D10.4 MCP is not built. It is reopened when a target client has no shell tool (Claude Desktop, claude.ai) or when the
CLI path measurably needs more than one agent round trip per fan-out. It would then expose a single tool equivalent to
`oz do`.

**Rejected.**
(a) MCP first: a server lifecycle (a hidden background process on Windows) and tool schemas in every session, for no
capability the CLI lacks.
(b) The multi-verb flow as the agent default: every extra round trip re-reads the agent's whole context (L6), so five
verbs could cost more than the batch saves.
(c) A custom subagent type: it pays the per-subagent system prompt and tool schemas that AKOR exists to remove.
(d) The Python API as the primary contract: it excludes agents and shells that are not Python and hides round trips.
(e) Inlining refs in the request: their bytes would enter the agent's context once as the tool input and then on every
later turn.

**Invariant.** One fan-out costs the calling agent one tool call plus the OZ calls, keeps bulk data out of its
context, and states the scope and cost of everything it returns.

**Falsified by.** Arm K (Q2): a Claude Code orchestrator with the skill and `oz do` on the pilot's 16 jobs against the
pilot's S arm, orchestrator tokens counted on both sides. D10 fails if K's tokens per verified job are not lower than
S's by at least the measured subagent overhead, or if K needs more than one tool round trip per fan-out.

**Cost.** The skill listing is about 100 tokens per session and its body about 1k on first use. The measured saving
against subagent-per-job is about 5k to 8k tokens per job (0.1, finding 3), so the teaching cost breaks even within
the first job. Latency: `oz do` adds one process start to the OZ call; in the pilot one OZ/1g call took 9.4 to 12.9 s
per 16 jobs against 33.5 to 50.0 s for subagents. Code: about 150 lines for `oz do`, about 80 lines of skill text.

**Code today and migration.** The verbs are init, send, plan, run, events, status, inspect, retry and channel-add
(oz_cli.py:30-85). One fan-out needs a channel manifest, a `send` per job, `run`, and an `inspect` per result: one
shell line only by chaining, and no single JSON result. There is no skill.

### D11. One work model (added)

**Decision.** The node and registry model of OZ9 4 and 7 is the only execution model. OZ/1 and OZ/2 frames, channels
and macros become a host-side importer that compiles each frame into nodes over registered ops (keeps OZ9 1's importer
rule). The four instructions in oz_batch.py:62-69 become registered ops (`oz.audit`, `oz.propose`, `oz.observed`,
`oz.inferred`); `r` becomes `host.read`; `t` stays a recorded execution request until `host.exec` exists. A
multi-atom frame compiles to one node per model atom plus a `host.pack` node that assembles today's
`{"results":[...]}`.

**Rejected.** Running the channel inbox and the graph side by side: two acceptance paths, two schedulers, two ledgers,
and every guarantee proven twice.

**Invariant.** Every model job, whatever syntax produced it, passes through one scheduler, one acceptance path and one
ledger.

**Falsified by.** A legacy frame whose compiled nodes produce a different packet body or acceptance outcome than
today's path on the existing fixtures. The 337 tests are the importer's oracle.

**Cost.** 0 tokens and no runtime latency (compilation happens at submission). About 150 lines for the importer;
render and inbox are reshaped, not duplicated.

### D12. Lossless values (added)

**Decision.** JSON numbers keep their source lexeme end to end: parsed into a decimal type that retains the original
text, serialized as the same text. Model-visible bytes are built from stored bytes, never from re-serialized floats,
and K hashes model-visible bytes (D1.3).

**Why.** `oz_reply.loads` parses floats (oz_reply.py:48-53), so `{"len":12.50,"u":0.020}` reaches dependents as
`{"len":12.5,"u":0.02}` (0.2). In measurement data the trailing zeros state resolution, and OZ9 2.2 forbids silent
normalization. This is a defect in shipped code, not a new feature.

**Rejected.** Value canonicalization for keys (JCS), and float round-tripping (today).

**Invariant.** The bytes a dependent model sees for a value equal the bytes its producer emitted.

**Falsified by.** A fixture of numbers with trailing zeros, exponents and 20-digit integers that is not byte-identical
after reply, store and dependent packet.

**Cost.** 0 tokens, no measurable latency, about 40 lines.

## 3. Changes to OZ9 in one place

| OZ9 | Change | Decision |
|---|---|---|
| 2 | Qualification per batch-size bucket; the profile table moves into configuration | D9.2 |
| 3.1, 3.2 | Unchanged; the per-result size limit moves from the parser to acceptance | D2.4 |
| 3.3 | Per-record acceptance inside a W-valid reply; scopes `declared`, `checked`, `verified`; drift containment | D2.1, D2.3, D2.6 |
| 5.1 | Cross-run compatibility key; readiness checks scope and staleness | D7.1, D7.2 |
| 5.3 | The job is the retry unit; retries may share packets with new work | D3.1 |
| 5.4 | Rate-limit events shared across workspaces | D7.7 |
| 6.1 | Inputs as model-visible bytes; CLI version in the route digest; node ID, siblings and contract version excluded | D1.3, D4.1 |
| 6.3 | Hits re-run the current contract's checks; revocation marks dependents stale | D4.2, D4.3 |
| 7.1 | Unchanged; `host.map` added as a registered op | D6.2 |
| 7.2 | Admission adds profile, scope reachability, effect key and config pinning checks | D6.4 |
| 7.3 | Targets declare a required scope and are fixed at start | D2.7, D1.1 |
| 9.1 | Dispatch journal, stdout capture, ledger in SQLite; node states add `stale` and `retired`; records may be `superseded` | D5, D4.3, D3.3 |
| 9.2 | Attempts charged at spawn; pure jobs fenced by content, effectful jobs by attempt | D3.2, D3.3 |
| 10 | Usage with invocation scope and source; stdout to a capture file | D8.1, D5.2 |
| 11 | `oz do`: one round trip, stdin, refs by path | D10.2 |

## 4. Consequences for the signed plan

1. Step 2 is not finished. Its "thin skill + CLI" arm was never run: H and J had no orchestrator, and S did. Arm K
   needs only `oz do` and the skill (D10), which depend on nothing in steps 3 and 4. I propose building them and
   running K before step 3, together with the preregistered 64-job Sonnet expansion, since K measures the largest
   lever found so far.
2. Step 3 builds D2, D3, the dispatch journal of D5, the `modelUsage` adapter of D8 and D12. Its gate "verified
   successes kept" applies inside W-valid replies (D2.2).
3. Step 4 builds the D1 keys, D4, D6, D7 and D11, and runs the wavefront test of D7 next to the interruption and
   invalidation tests.
4. Step 5 starts with effort (Q3). Q1 has to come before any production use of small packets.

## 5. Open questions that need measurement

| # | Question | Measurement | Decision it moves | Budget |
|---|---|---|---|---|
| Q1 | Is OZ/1g valid and correct at 1 to 4 and 5 to 16 jobs? | 10 replies per bucket and model at both bucket ends, oracle-scored; the pilot's 3 replies per model at 16 count | D9.2 buckets; whether `oz do` can serve small fan-outs | about 50 calls, 125k tokens |
| Q2 | Does the skill beat subagents once the orchestrator is counted on both sides? | Arm K on seeds 3005 to 3007, Sonnet first; S data exists | D10 | about 120k tokens |
| Q3 | Which effort minimizes T per verified job on OZ/1g? | Haiku and Sonnet at low and medium against default, at 16 and 64 jobs, 5 paired trials each (OZ9 12.3) | Default effort in route profiles | about 40 calls, 250k tokens |
| Q4 | Does one generic goal with self-contained ops keep correctness? | Same jobs with a per-run goal and with a generic goal, 5 paired trials | Practical reach of cross-run batching (D7.2) | about 10 calls |
| Q5 | Do waves batch across workflow instances? | The D7 wavefront test, 16 instances of the 20-step workflow | Whether the executor saves tokens or only recovers | one run set in step 4 |
| Q6 | How often does drift demotion fire on qualified cells? | Recorded heterogeneous P1 to P5 replies with input-bound checks | D2.6.4; reopen above 2% of replies | 0 calls (replay) |
| Q7 | Do W-invalid rates stay near zero at 64, and are buckets above 64 ever needed? | Ledger W-valid rate over the next 50 replies per cell; frontier widths from arrival traces | D2.2 reopen criterion; bucket list | 0 extra calls |
| Q8 | Does more than one call in flight per quota group cut latency without rate-limit events? | 2 and 4 in flight on the wavefront workload | D7.4 default | within Q5 |
| Q9 | Does the subscription weigh cache reads or writes differently from fresh input? | Matched quota observations at equal raw T with high and low cache share (OZ9 12.1) | Whether a stable-prefix layout is worth a D9 change | owner's quota telemetry |
| Q10 | How stable is F across CLI versions? | Rolling median per CLI version from the ledger | D7.6 estimates; small-batch economics | 0 extra calls |
| Q11 | How much does early cutoff save on a rerun after a dependency change? | Rerun the 20-step workflow after an upstream change that keeps upstream bytes equal, and after one that changes them | D4 value claim | within step 4 |
| Q12 | Is Haiku's subagent correctness gap (39/48 against 48/48) real? | Repeat S on Haiku with 3 more seeds | Public claim only | about 350k tokens; optional |
| Q13 | Do accepted results change across CLI versions for equal K? | Rerun 20 memoized jobs after a CLI update; compare values and oracle correctness | Whether the CLI version can leave K (D4.1) | about 2 calls |
| Q14 | Below which fan-out size should an agent answer inline instead of calling `oz do`? | Same jobs inline and through `oz do`, counting the context re-read over the session's remaining turns | Skill threshold (D10.3) | about 6 runs |
