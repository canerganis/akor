# oz-rule/1 amendment 2 and the step 6 architecture (after council 2)

Sources: council2-astra.md (Astra A, language owner; amendment 2 text quoted verbatim below) and council2-opus.md.
Driver: Claude Opus 5.5. Where the driver decided something Astra has not ruled on, it is marked DRIVER and goes to
council 3 for confirmation.

## Amendment 2 (Astra A, verbatim)

A2.1 Bootstrap failure: "A malformed bootstrap envelope or failed bootstrap answer MUST NOT trigger replacement
answers or artifact revision. Preserve the failed attempt and invalidate efficiency. Infrastructure recovery MAY
resume an existing invocation or retry a provably unlaunched attempt; every actual launch consumes budget. Unknown
outcomes remain unresolved until reconciled."

A2.2 Spec shown to the model: "Bootstrap synthesis MUST receive the complete effective language semantics, including
D3 through D5, evaluation result representation and resource bounds. Worked E/B/M/V ASTs, conformance vectors and
admission labels MUST remain hidden. Admission procedures MAY be omitted." Pin this effective excerpt.

A2.3 Pilot matrix: "add Sonnet materials B; retain Codex BoolQ and both backends' materials warm A/C waves. Keep the
global 50 call cap, backend allocations and existing gates. Freeze a revised reserve allocation before calls. If this
expanded matrix cannot fit, report incomplete evidence rather than silently omit cells or increase authorization."

Owner note (2026-10-24): the owner lifted the Claude token limit until this build and pilot are finished, so the
record's "abort at 55% weekly" no longer binds Claude launches; the 50-call cap and every gate still do.

## Council 2 rulings to implement (summary; council2-astra.md is normative)

1. Authoritative settlement record per job: immutable payload and binding hashes, execution generation, one winner
   between rule and model settlement, identity validated on resume, earlier emissions kept as history.
2. `awaiting_verification` state: an unavailable check never becomes acceptance; fallback may answer but acceptance
   still needs every applicable pinned check to pass; the adoption boundary itself rejects missing evidence.
3. One experiment bootstrap per backend and workload: exactly 16 jobs from each of the 4 producers (64), immutable
   answers and candidate artifacts shared by B and C, which then run independently. Audits: min(32, covered) per
   evaluation wave across all producers, selected on frozen dataset identities, population and B/C-identical
   selection persisted before dispatch.
4. Exact AST bytes: the original JSON slice for each op is extracted from the envelope, limited to 2,048 bytes,
   hashed, admitted and re-evaluated as those exact bytes; invalid Unicode rejected.
5. Route identity covers the shim, the underlying adapter, their executable dependency closure and configuration,
   recomputed and reconciled before dispatch.
6. Raw evidence: complete stdout, stderr, exit and timeout captured under an allocated physical attempt id before
   parsing, also on failure; bootstrap success requires the ordinary answers to parse and settle.
7. Inconclusive or pending audits block a completed-evidence claim and block warm reuse until resolved (Opus B5).
8. DRIVER: after an audit disagreement quarantines a rule, every rule row of that wave not yet delivered to its
   producer falls back to the model (lowers kill-criterion-1 risk); rows already delivered stay recorded.

## Architecture

```
producers (scripted) --submit--> spool.sqlite <--- one host process per arm (A, B or C) and backend
                                                   |  owns: scheduler (4 slots), rule store, bootstrap,
                                                   |        audits, physical attempt ledger
                                                   +--> child process per physical call: oz_do request
                                                        (isolated env; request_id derived from batch_id,
                                                         so a re-dispatch never makes a second call)
```

### Interfaces (binding for all three work items)

1. **Spool** (`oz_spool.py`, rewritten on SQLite):
   - `Spool(path)`; `submit(producer, submission, jobs, bindings)` in one transaction; jobs are
     `{key, op, text, dataset_id}`; conflicting resubmission raises; host-issued identities only; bindings schema
     `{contract_hash, check_hash, permission_hash, worker_hash, input_policy}` validated and hashed on read.
   - Host lock: an OS file lock held for the process lifetime (`msvcrt.locking` on Windows, `fcntl.flock` on POSIX);
     no time-based takeover of a live holder; every state mutation checks the host's fencing epoch in the same
     transaction.
   - `Scheduler(spool, launch, *, slots=4, max_records=64, max_wait=1.0, clock=monotonic)`: one scheduling owner,
     deadlines independent of completions, durable reservation before each launch, `launch(batch) -> attempt`
     runs in a worker thread, results captured then delivered exactly once; foreign or conflicting results rejected.
   - `collect(producer, submission)`; `queue_report()`.
2. **Shim** (`examples/bootstrap_shim.py`): enabled only when the child process env has
   `OZ_BOOTSTRAP_ATTEMPT=<attempt id>` and `OZ_BOOTSTRAP_DIR`; claims `<dir>/<attempt id>.claim` with O_EXCL; writes
   `<dir>/<attempt id>.json`:
   `{"attempt_id","status","exit_code","timed_out","stdout_b64","stderr_b64","envelope_ok","answers_reply",
     "rules":{op: {"none": true} | {"ast_b64": "<exact slice bytes>", "ast_sha256": "...", "bytes": n}}}`
   before writing its own stdout; on any failure it still writes the file. The effective spec excerpt is a pinned
   file `docs/design/ozmap-2026-10-24/bootstrap-spec-excerpt.txt` with its SHA256 checked at load.
3. **Host** (`oz_host.py`, new) and `oz_rulephase.py`, `oz_map.py`: the host runs one arm on one backend: drains the
   spool through the Scheduler, runs the shared bootstrap (or imports it for B/C from a frozen bootstrap record),
   settles rule jobs through the authoritative settlement record, sends fallback and audit jobs in child `oz_do`
   processes, writes a physical attempt ledger and an allocation ledger (job membership per call: bootstrap,
   fallback, audit), and reports per arm: gold-free receipts, queue time, makespan, coverage.
   `oz_map` stays the single-user command and becomes a thin client of the same code path.
