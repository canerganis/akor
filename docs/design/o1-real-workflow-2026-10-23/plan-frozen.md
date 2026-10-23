# G3c-O1 preregistration: `repair-handoff-20/v1` (frozen before the first counted call)

Plan: [README.md](README.md); the signed text is [01](01-astra-r1.md) as amended by [02](02-opus-r1.md) M1 to M12,
accepted in [03](03-astra-r2-signed.md) with its three technical conditions, and [04](04-opus-r2-sign.md) with its
clarification on completion limits. This file records what the build does, so the live run can be judged against it.
Nothing here is a model result. The defects are seeded in a purpose-built utility package; they are not independently
discovered bug reports, and a pass is not evidence of repairing a production incident.

## Identity

| Item | Value |
|---|---|
| Gate | G3c-O1, one binding label `pass_g3c` |
| Workflow | `repair-handoff-20/v1`, target `repair_package`, weight 1 |
| Freeze record | `bench/o1/repair-handoff-20-v1/freeze.json` |
| Freeze digest | `32333561a3472b1030d4222b2b19bcf5b0968451d9f0a4959a6f75b05dff309e` (short: 32333561; replaces 53609b83 after the ticket B wording fix required for G0, which replaced c6ee1c4b after the executor fix) |
| Route | Sonnet 5.5 (`claude-sonnet-5-5`), default effort, `claude -p` with no tools through `examples/claude_cli_adapter.py`, CLI 2.1.306, OZ/1g text H and parser unchanged, `oz1g-selective-v1`, durable runner |
| Sizes | packets of 4 and 1, both labeled experimental (`experimental_sizes=(4, 1)`, M9); a pass qualifies no cell |
| Workspace | fresh `.oz-runtime/o1-live1`, request prefix `live1`, memo namespaces `live-live1-*` |

The freeze pins every frozen file (tickets, originals, policy, A and I tiers, coverage, defects, workflow.json,
graph.json, held-out data, both references, the fixture answers), the code (executor, adapter, harness, worker,
evaluator, predicate) and design files 01 to 04, with CRLF normalized. Any change needs `freeze --write`, a new G2 run
and a new review before G3c.

## Files

| Path | Role |
|---|---|
| `bench/o1/repair-handoff-20-v1/` | the frozen pack the executor reads: `tickets/` (A rev 1 and 2, B, C, D; exact ticket bytes with the exact model records and replacement spans), `originals/` (the defective modules), `policy.json`, `tier_a.json`, `tier_i.json`, `coverage.json`, `defects.json`, `workflow.json`, `graph.json`, `freeze.json` |
| `bench/o1/workflow.py` | host operations and the per-job checks (`o1_source`, `o1_policy`, `o1_tier_a`) |
| `bench/o1/sandbox.py`, `sandbox_worker.py` | the controlled launcher, Job Object and confined worker |
| `bench/o1/gate.py` | the exact-trace predicate with independent member verdicts |
| `bench/o1/evaluator/` | evaluator only: `evaluator.py`, its own worker `eval_worker.py`, references `ref1/` and `ref2/`, H domains `heldout.py` and frozen outcomes `heldout.json`, and the build-time generator `build.py` |
| `bench/o1/fixture_adapter.py`, `bench/o1/fixture/` | the zero-token adapter and its answers (a third valid implementation, neither reference) |
| `bench/o1/o1.py`, `o1_dry.py` | the harness: freeze, measure, dry gate, guarded live run |
| `tests/test_o1.py` | focused tests |

## The workload

Four tickets, each a core function and the adapter that calls it. Model jobs return one Python function as a bare JSON
string (M6). The host can run and judge code; it has no generator, answer table or reference substitution in its read
set (a G2 scan checks the exact text and the AST of every reference function and the held-out digests against the
frozen pack, `workflow.py`, the sandbox files and every `oz*.py`).

| Ticket | Core | Adapter | Seeded defects (each fails at least one A row; why each needs semantic repair is in `defects.json`) |
|---|---|---|---|
| A amounts | `parse_amount(text)` | `total_amount(texts)` | float arithmetic, rounding of excess precision, float syntax accepted, no nine-digit limit, non-text accepted; adapter divmod formatting of negatives; revision 2 needs three digits |
| B intervals | `union_intervals(intervals)` | `free_slots(busy, window)` | assumes sorted input, touching kept apart, zero-length kept, no validation; adapter does not clip and does not validate |
| C config | `merge_patch(base, patch)` | `apply_revisions(base, revisions)` | mutates base, KeyError on a missing deletion, no deep copies; adapter sorts seq as text, accepts duplicates, bool and non-positive seqs, returns base itself |
| D jobs | `topological_order(jobs)` | `execution_batches(jobs)` | FIFO instead of earliest ready position, duplicate ids, missing dependencies and cycles pass silently; adapter uses min instead of max and input order instead of the returned order |

Revision 2 of A changes precision from two to three fractional digits; its ticket bytes and all its tiers are frozen.
No single substitution of an original (comparison or arithmetic operator, integer constant plus or minus one, and/or,
min/max, dropping a unary not, unwrapping a one-argument call) passes A: 108 mutants checked at G2, none passes.

## Tiers

| Tier | Where | Content |
|---|---|---|
| A | the per-job check `o1_tier_a`, in the executor | 286 rows over ten sets (ticket, revision, operation), at least 12 each, at least two per boundary family, both sides of every edge, every outcome category (C core raises nothing within its contract, marked inapplicable). Adapter rows: core stubs with controlled returns, exceptions and exact call records, plus integration rows on the accepted core whose every core call is an A-tier core input of that revision (M4, built in and tested). The check selects rows by the header of the job's own record and fails a record that is not the frozen one for its ticket, revision and operation (M11). |
| I | node 16, on the assembled module bytes | 8 rows per module and revision |
| H | evaluator only | bounded exhaustive domains with frozen cardinalities (below), expected outcomes from two references that agree on every input |

| H domain | Inputs | Max chunk CPU s (ref1) |
|---|---:|---:|
| A1.core (precision 2) | 9,361 | 0.06 |
| A1.adapter | 820 | 0.06 |
| A2.core (precision 3) | 9,361 | 0.08 |
| A2.adapter | 820 | 0.05 |
| B.core | 9,939 | 0.16 |
| B.adapter | 9,737 | 0.14 |
| C.core | 3,025 | 0.11 |
| C.adapter | 2,000 | 0.13 |
| D.core | 7,598 | 0.22 |
| D.adapter | 7,598 | 0.22 |

Domains run in chunks of 2,500 rows per worker process; the largest chunk used 0.22 s of the 2 s CPU limit with
reference 1 (about nine times margin). An A-tier run takes about 0.1 s per seed. Domain definitions are in
`evaluator/heldout.py`, cardinalities and input digests in `heldout.json`.

Comparison is type-strict canonical JSON (None, bool, int, str, list, object with string keys); tuples, sets and floats
are refused before serialization; exceptions compare by exact class name. Each run executes under hash seeds 0 and 1;
different outputs fail the candidate. Inputs are never mutated; for C the result shares no list or dict with the inputs.

## The code-running worker

`sandbox.py` starts `sandbox_worker.py` from a fresh empty temporary directory with the base interpreter (a venv
redirector would start a second process) and `-P -S -s -B` (no `-I` or `-E`, which ignore `PYTHONHASHSEED`), with an
environment holding only `PYTHONHASHSEED` and `SYSTEMROOT`. The process is assigned to a Job Object (256 MiB process
memory, one active process, 2 s user CPU, die on unhandled exception, kill on close; the limits are read back) and
confirmed inside it before the payload is written. A 5 s wall timeout terminates the job. Layers inside the worker: the
AST policy (`policy.json`: one function with the frozen name and parameters, a node whitelist, no underscore names or
attributes, attributes only from a frozen method list, a forbidden-name list), a frozen builtins dict, and an audit
hook armed after the definitions run and before any candidate call (import, open, compile, exec, socket, os,
subprocess, ctypes and similar events raise). Expected results stay in the parent. A worker that cannot be created,
confined or brought to its ready line raises `Unavailable`: the candidate awaits checks and no model attempt is spent.
A candidate stopped after its ready line (CPU, memory, wall, crash) or refused by the policy fails its check and is
recoverable at attempt 2. Network denial rests on the policy, the builtins and the audit hook; a Job Object cannot
block sockets, so this is language-level confinement plus process limits, not an OS network sandbox.

## Graph

Twenty nodes: `snapshot` (1); `core_A` to `core_D` (2 to 5, one size-4 frontier); `ctx_A` to `ctx_D` (6 to 9, adapter
context from the ticket and the accepted core); `contexts` (10, the join); `adapter_A` to `adapter_D` (11 to 14, one
size-4 frontier); `assemble` (15, original bytes with the two declared spans replaced by the accepted bytes, a newline
added only when a source lacks one); `integration` (16, I tier); `patch` (17) and `report` (18, verification report and
provenance), a host fan-out; `verify` (19, rebuilds the package from the patch, checks the report, provenance and
integration evidence bind the same bytes and that every ticket is still the current source revision); `publish` (20,
durable local publication). Eight model jobs and twelve host steps, of which five assemble context or join (M12).

## Commands (PowerShell, repo root)

```powershell
$env:TIKTOKEN_CACHE_DIR = ".token-cache"; $env:PYTHONIOENCODING = "utf-8"
# G0: every digest must match ("frozen": true, digest above)
.venv/Scripts/python.exe bench/o1/o1.py freeze
# G1: the full suite plus the focused tests
.venv/Scripts/python.exe -m unittest discover -s tests
# G2: zero-token dry gate, must print "pass": true
.venv/Scripts/python.exe bench/o1/o1.py dry --workspace .oz-runtime/o1-dry
# G3c-O1: one suite, five scenarios, paid, fresh workspace, no reruns
$env:O1_LIVE_CONFIRM = "1"
.venv/Scripts/python.exe bench/o1/o1.py live --workspace .oz-runtime/o1-live1 --prefix live1
```

`live` refuses without `O1_LIVE_CONFIRM`, refuses a workspace that already holds a flow or a memo store, and refuses a
changed freeze or another CLI version before any launch; the CLI version is rechecked before every launch. There is no
option to run one scenario or to rerun one. Report: `report-live-live1.json` in the workspace, plus
`flows/<request_id>/execution-record.json`; the workspace's SQLite files are the authority.

## Allocation (ceilings, not estimates)

150,000 tokens and 18 launches for the whole suite, at most 8 per scenario, one in-flight call in quota group
`claude-cli`, 300 s per call, 3,600 s per scenario deadline that resume never resets, four-hour suite envelope. No
planner, filler jobs, cross-run batching, model switching or effort change.

Reserve per launch: 17,358 tokens (17,334 before the ticket B fix), measured at G2 with the workspace tokenizer (o200k_base; Claude's own counts
differ and the live run records `modelUsage`). The largest frozen packet is the size-4 adapter packet: 3,378 input
tokens with the fixture cores, 7,334 with each accepted core at the 4,096-byte limit; reserve = 7,334
+ 2,000 overhead + 8,000 output headroom. The executor's admission takes one reserve for every launch, so singletons
are charged at the size-4 reserve (conservative). A call with unknown usage is charged at the reserve. The route sets
no output limit (`claude -p` runs with no output-limit flag), so per 04 the reserve is measured input plus declared
headroom and not a bound on a call; any actual overrun of the allocation prevents an overall pass.

Measured packets (input tokens, system text H plus packet): core x4 2,493; adapter x4 3,378 (fixture cores); singletons core A 1,112 (rev 2: 1,115), B 1,149,
C 1,194, D 1,189; adapter A 1,374 (rev 2: 1,374), B 1,439, C 1,385, D 1,418.

## Expected spend

Failure-free schedule: 8 launches (clean 2, repeat 0, interrupt 2, stale 4, bump 0). Per call: measured input + 2,000
overhead + fixture-sized output + T hidden reasoning (unmeasured on this workload).

| T per call | Expected suite tokens |
|---:|---:|
| 0 | 40,860 |
| 2,000 | 56,860 |
| 5,000 | 80,860 |

**Expected 56,860 to 80,860 tokens for a failure-free suite, cap 150,000.** These are estimates, not predictions; the
cap bounds loss. The failure-free estimate at T = 5,000 is under the 100,000 shrink threshold (M8.3), so the tickets
were not shrunk. The ceilings do not guarantee that every possible recovery fits: with recovery in every cold scenario
at T = 5,000 the token cap can bind before the launch cap, and exhaustion means no pass.

## Expected launches

| Scenario | Request | Launches | Packets | Memo hits | Notes |
|---|---|---:|---|---:|---|
| clean | `live1-clean` | 2 | 4, 4 | 0 | cold namespace |
| exact repeat | `live1-repeat` | 0 | none | 8 | clean namespace, new request identity |
| interrupted | `live1-interrupt` | 2 | 4, 4 | 0 | hard exit at `worker.after_capture` (first call), then at `flow.publish.after_manifest`, then the same command |
| stale A | `live1-stale` | 4 | 4, 4, 1, 1 | 6 | ticket A revision 2 right after node 16 commits; core A and adapter A again, B to D by memo |
| identical-byte bump | `live1-bump` | 0 | none | 16 | clean namespace; A gets a new source revision with identical bytes at the same hook |

The bump trace is frozen from the dry run: memo lookups core A to D hit, adapter A to D hit, then the same eight again
after the bump; acceptances: nodes 1 to 16 at generation 1, nodes 1 to 16 at generation 2, then nodes 17 to 20 once.

## Recovery policy the oracle encodes

After a packet whose rejected set R holds check rejections, wire rejections or failed calls, the stage resends exactly
R at attempt 2, in job order, before the next stage: one size-4 packet when all four members of a size-4 packet are
pending (a wire rejection is atomic, so always), else one singleton per member. Accepted siblings are never resent, no
member is sent a third time, a member held by a verifier outage is never resent or regenerated, a valid model failure
record is terminal (no resend; the target fails, M10), and a member rejected at attempt 2 leaves the stage unresolved.

## pass_g3c, per scenario (all required; judged by `gate.py` and the evaluator, no executor flag)

1. Delivered once before the original deadline; the evaluator verifies the delivered package: every module equals the
   original with the two spans replaced by the accepted candidates byte for byte (the candidates are the value lines
   of the preserved captures that the evaluator itself judged accepted, or memo values found in their provenance
   capture); each function passes A against its exact record; each module passes I; each core passes H and each
   adapter passes H with its accepted core; the patch equals the evaluator's own unified diff; `provenance.json` cites
   the expected ticket revisions (A revision 2 in the stale scenario) and states the seeded provenance. The adapter
   on H with the reference core is reported, not gated.
2. The primary packet sequence and memo hits equal the table; for the bump, the lookup and acceptance traces too.
3. Independent verdicts: every capture re-parsed, every value line judged against its exact recorded input, rejected
   candidates included; any disagreement with the executor (false acceptance or false rejection), an unknown status,
   a non-atomic wire rejection, a missing capture or a memo value absent from its provenance capture fails.
4. Recovery eligibility per launch (grounds, attempt, generation, computation identity, the exact current record,
   launch order, scenario cap) and the exact dispatch trace equal to the one derived from the independent verdicts.
5. No unresolved stage; at most 8 launches; one ledger call per launch and complete `modelUsage` accounting.
6. Every dispatch labeled experimental (the killed first call of the interrupted scenario may be unrecorded).
7. Interrupted: both kills at their boundaries, the first capture recovered without a new call, the manifest
   reconciled on resume, the original deadline kept. Stale: no packet after the mutation carries an old A record, the
   old package verification is invalidated and never delivered, B to D reassociate by memo hits on identical inputs,
   the old A acceptances stay as history.

G3c-O1 passes on `pass_g3c` for all five scenarios, a held freeze, totals within 150,000 tokens and 18 launches with
complete accounting, and the suite inside its envelope. Reported apart, never part of the verdict: first-attempt
acceptance per operation, recovery launches and tokens, wire failures, check false accepts (passes A, fails H) and
false rejects (fails A, passes H), thinking tokens per call (unknown is never zero), tokens and seconds per scenario.

A pass supports only: "AKOR completed and recovered a recorded 20-step code-repair workflow, using model-generated
repairs, independent per-job checks, current-source validation and memo reuse, within the registered deadlines and
allocation." It does not establish general coding reliability, a new qualification or token superiority. No baseline.

## Zero-token dry gate (G2) at this freeze

Result at freeze 53609b83 (after the executor fix): **`pass`: true**, every block. At c6ee1c4b it was false on
`interrupt_with_recovery` only (see the resolved finding below).

1. Five scenarios, all `pass_g3c` and strict: clean 2 launches (4, 4), repeat 0 with 8 memo hits, interrupted 2 (4, 4)
   with both kills, stale 4 (4, 4, 1, 1) with 6 memo hits, bump 0 with 16 memo hits and the frozen traces. 8 launches,
   23,331 fixture tokens, accounting complete; every delivered package verified on A, I and H with byte provenance; no
   check false accepts or false rejects.
2. Recovery fixtures, 15 of 15 pass: two cores rejected (4, 1, 1, 4); three adapters rejected (4, 4, 1, 1, 1); four
   rejected, one size-4 resend; a wire-rejected size-4 reply resent whole; a policy refusal then repair; a CPU-limit
   stop then repair; stale with an adapter rejection on both sides of the mutation; a second-attempt failure (no
   pass, no third attempt); a verifier outage (held, no resend, no pass); a model failure record (terminal, no resend,
   no pass); a wrong-revision core (rejected twice, no pass); `interrupt_with_recovery` (4, 1, 1, 4, kills at both
   boundaries). Added with the fix, strengthening only: a wire-invalid reply inside the killed call
   (`interrupt_wire_rejected`, 4, 4, 4, pass), a failure record inside it (`interrupt_model_failure`, 4, terminal,
   no pass), and a second invocation after an exhausted adapter (`second_attempt_fails_then_reinvoked`, 4, 4, 1, no
   third attempt, no pass).
3. Executor sabotage, 7 of 7 caught: corrupted patch refused at node 19; a revision change between export and commit
   refused, recomputed and delivered at A revision 2; a fixture value forged under a live-like key refused by
   provenance; missing usage; a check that falsely rejects a correct adapter (independent verdicts disagree); a check
   that accepts everything with a defective core (disagreement, package fails A and H); singleton recovery labeled
   qualified when size 1 is left out of the experimental sizes.
4. Predicate sabotage, 20 of 20 caught: accepted-sibling resend, unsupported packet size, third attempt, skipped
   recovery, false rejection, false acceptance, wrong revision accepted, stale input after the mutation, verifier
   outage regeneration and resend, model failure resent, wire rejection resent as singletons, non-atomic wire
   rejection, launch beyond the scenario cap, forged memo provenance, stale package delivered, missing usage, a
   dispatch labeled qualified, a recovered capture counted as another launch, a duplicate ledger record.
5. Escape suite, 26 of 26: 18 forms refused by both policy implementations and by the worker; recursion bomb, huge
   allocation, doubling string, CPU loop and big power contained; both audit hooks refuse import, open, compile, exec,
   socket, os, subprocess and ctypes events once armed; process confinement (limits read back, a second process
   refused inside the job, two-variable environment, temporary cwd, launcher flags).
6. Seeds, 5 of 5: seeds 0 and 1 honored (same seed same hash, different seeds differ), set order differs, a candidate
   right only under seed 0 rejected by both the check and the evaluator, a tuple output and True for 1 rejected.
7. Oracle checks, 9 of 9: frozen pack equals its generator and both references agree on every A, I and H input; the
   fixture implementation and reference 2 pass A, I and H, every original fails; wrong-function binding, wrong
   revision, type confusion, input mutation and adapter compensation detected; references and held-out data absent
   from the executor read set (38 files scanned); none of 108 single-substitution mutants of the originals passes A.
8. Feasibility, 3 of 3: two adapter rejections in every cold scenario at live-sized usage (15 launches, 120,735
   tokens, admitted); a scenario that exhausts its 8 launches is refused (no pass); a token reserve refuses the third
   launch (no pass).

## Resolved finding: rejections inside the recovered capture of an interrupted call

In `interrupt_with_recovery` the first core call is killed right after its capture, and that capture holds two
rejected members (core_B, core_C). On resume the executor adopts the capture, accepts core_A and core_D, but leaves
core_B and core_C leased (`in_flight`, lease still running), so that invocation ends blocked
(`model_jobs_unresolved`). The next invocation submits core_B and core_C as a new stage request whose attempt counters
start again at 1: four singleton launches where the signed policy derives two, in effect a third model call for the
same job generation. The gate reports `exact_trace` and `primary_sequence` failed, as it should. G3b never exercised
this path (its rejections were in later stages, not in the killed call). The executor's recovery behavior was not
changed and the oracle was not bent to accept it. The failure-free interrupted scenario is not affected.

Decision (Astra and Opus, independently): fix the executor, change no rule. Two defects, both fixed:

1. `oz_runtime.py`, `settle_dispatch`: every `oz do` call takes a new coordinator epoch, and the in-lease test also
   required the epoch that opened the dispatch, so a coordinator settling a dead coordinator's completed capture
   adopted accepts but left rejected, quarantined, wire-rejected, failed and awaiting members leased until the
   lease ran out. Now a member still leased under that dispatch's unexpired lease takes the in-lease effect
   whichever epoch opened it (the originating epoch stays provenance; a capture never releases a newer attempt's
   lease; header members keep the shipped rule).
2. `oz_flow.py`, `_run_stage`: the stage request id hashed the pending subset, so a partly committed stage was
   resubmitted as a new request with a fresh inbox and attempts reset (also reachable without any kill, by invoking
   a flow again after an exhausted job, a failure record or a verifier outage). Now a logical job (flow, node,
   generation) keeps the stage request it was first submitted in, and a resumed flow resubmits that request with
   its original membership and the current deadline. Changed inputs under the same generation open an explicit
   new generation (`regenerated`, reason `inputs_changed`); a model commit refused twice with the same value blocks
   with `commit_refused` instead of looping.

Tests added first and failing at ec4f74b: `ResumeInsideTheLeaseTests` (11, `tests/test_oz_selective.py`),
`StageIdentityTests` (8, `tests/test_oz_flow.py`), `ResumeTests` (4, `tests/test_o1.py`). Re-run after the fix,
zero tokens: the full suite, `step4.py freeze --write` (G3b record 040cfd41) with `step4.py dry`, `replay-live1` and
`replay-live2`, then `o1.py freeze --write` (53609b83) and `o1.py dry` (above). Astra requires a newly
preregistered full G3b live suite on the patched executor before any claim of patched-executor conformance, and
then this O1 G3c suite; Opus agrees. Neither live run has been made.

## Choices the signed text left to the build

1. The evaluator runs code in its own worker (`eval_worker.py`) with its own policy check, value encoding, stubs and
   comparison; it shares only the launcher and Job Object (`sandbox.run`), so the confinement is the frozen one.
2. One reserve for every launch (the size-4 adapter upper bound): the executor's admission takes a single reserve, and
   changing it would change the executor.
3. "Exact input tokens" are o200k_base counts of system text H plus packet, the workspace tokenizer.
4. The H gate is core H plus adapter H with the accepted core (the package's behavior); adapter H with the reference
   core is reported (03, M4: "report these separately").
5. A verifier outage at node 16 refuses that host step (the flow blocks); a host node has no awaiting state.
6. The worker process starts before its Job Object assignment and blocks on stdin; the assignment is confirmed before
   any payload byte is written. It is not created suspended.
7. A valid model failure record is terminal in the derivation (M10); G3b's derivation would expect a resend, so
   `gate.py` has its own derivation and reuses only g3b's executor-free reply parser and capture reader.
8. Record format: each model record is frozen text in the ticket (core) or a frozen prefix plus the accepted core
   (adapter), so the check and the evaluator verify records by string equality, not by re-rendering.

Status: built through G2 at freeze 32333561; G0 granted by Opus; ready for the single G3c live run.
contract, which has not happened yet. G1 is green. G2 passes after the executor fix. Before G3c: review of the fix
and a newly preregistered G3b live suite on the patched executor. No model call has been made.

## Addendum 2026-10-23: G0 granted by Opus after the ticket B wording fix (freeze 32333561)

Opus's G0 review of the built contract (record `o1_g0_opus.md` in the session scratchpad; summary here) agreed to
everything except one defect: ticket B's adapter requirement said "an interval [ws, we] under the same rule" without
stating the rule, which only the core record (not shown to the adapter job) contained, while frozen A rows demand
ValueError for malformed windows. The requirement now states the rule in full ("a two-element list [start, end] of ints
(a bool is not an int here) with start <= end"); no row changed. `build.py` regenerated ticket B, `measure` gave a
reserve of 17,358 (adapter x4 upper bound 7,358 input tokens), `workflow.json` was updated to it, `freeze --write` gave
32333561, and `dry` passed every block again (five scenarios, recovery, sabotage, gate sabotage, escape, seeds, oracle,
feasibility, measured). Opus counts this as its G0 agreement since the diff touches only that ticket text and its
derived files. The fix review (50e8ef5) was approved by Astra. Both preconditions for the paid G3c run are met.

Notes from the same review: `run-flow --kind live` exists as the subprocess entry for the interrupted scenario, behind
`O1_LIVE_CONFIRM`, the freeze and the CLI check; any use outside the suite must be reported. Reserves and expected spend
use o200k_base counts; the live report should compare `modelUsage` input with the o200k estimate per packet.


## Addendum 2026-10-23: refreeze after the boundary adoption build (new freeze digest `0aa5ecf6cb453c195654679c8b7902768a0aff1a909263968100abfae386c933`, short 0aa5ecf6)

O1's live G3c result (pass; `results.md`, `bench/o1/live1/`) was made at freeze 32333561 and stands for it; nothing
under `bench/o1/live1/` changed and nothing is rerun. The boundary adoption
(`docs/design/boundary-adoption-2026-10-23/plan-frozen.md`) then edited files this freeze pins: `oz_flow.py`,
`oz_do.py` and `oz_runtime.py` (opt-in ordered model inputs and `oz do` JSON value refs; the default paths O1 uses are
unchanged) and `bench/step4/g3b.py` (a pack-aware copy for v2; v1 behavior unchanged). `o1.py dry` passed every block
on the new code before the refreeze (clean 2, repeat 0, interrupt 2, stale 4, bump 0; recovery, sabotage, gate
sabotage, escape, seeds, oracle, feasibility, measured; only the freeze check failed, as expected), then
`o1.py freeze --write` gave the digest above (the 32333561 record is kept in git), and `dry` passed again with the
freeze held. This refreeze is a record of the code state, not a new O1 gate.

## Addendum 2026-10-23: refreeze after the review fixes to the opt-in executor changes (new freeze digest `31706661ac36a234e9df2f69f67751dae2767e45f22cf6a0daa16dc0f4e0609d`, short 31706661)

`oz_do.py` (the ref form of a `{"value": ...}` ref enters the request identity; requests without value refs keep
theirs) and `oz_flow.py` (resume compares stage inputs as canonical serialized bytes, not Python equality) changed; the
default paths O1 uses are unchanged. `o1.py freeze --write` gave the digest above (the 0aa5ecf6 record is kept in git)
and `o1.py dry` passed every block with the freeze held (clean 2, repeat 0, interrupt 2, stale 4, bump 0). This
refreeze is a record of the code state, not a new O1 gate. No model call was made.

## Addendum 2026-10-23: refreeze after the lossless value refs (new freeze digest `088815dbd9d1817af64b5b1d7ed96f4631681193ca1784387084e9421f2b1f36`, short 088815db)

`oz_do.py` (the carried value of a `{"value": ...}` ref is the validated text as `RawJSON`) and `oz_flow.py` (a
value-form input from an upstream node keeps its accepted bytes; the stage submission records `inputs_json`) changed;
the default paths O1 uses are unchanged. `o1.py freeze --write` gave the digest above (the 31706661 record is kept in
git) and `o1.py dry` passed every block with the freeze held (clean 2, repeat 0, interrupt 2, stale 4, bump 0). This
refreeze is a record of the code state, not a new O1 gate. No model call was made.
