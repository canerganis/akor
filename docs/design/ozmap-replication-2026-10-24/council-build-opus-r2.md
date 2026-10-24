# Council round 2: Opus code correctness review of bench/ozmap_rep (2026-10-24)

Reviewer: fresh Opus workflow subagent (claude-opus-5-5, effort high, code correctness lens), logged in
call-ledger.jsonl as `council-build-code-reviewer-r2`. No model call and no Codex call was made. Every check below
used local code, fakes or the archived probe captures. The sealed reviewer ASTs were not read. Reviewed at commit
c345c4b against amendment-4.md, amendment-4-13-caps.md, owner-decisions.md, build-notes.md and the three round 1
reviews.

Verdict: **do not freeze yet.** The round 1 fixes are sound and I found no regression in them. Four code blockers
remain (B1 to B4), each a small fix, and four rulings must be signed before `run freeze` (B5 to B8). Two of the code
blockers (B1, B2) are traps that would spend telemetry or evaluation calls and leave the live run directory unusable.

## What I ran

| check | result |
|---|---|
| `python -m pytest bench/ozmap_rep -q` | 467 passed (166 s) |
| `python -m bench.ozmap_rep.run dry --run-dir <scratchpad>/rep/dry-r2/D` | exit 0: 16 of 16 cells complete, 52 fake calls, 0 external calls, no real CLI resolved, every cell within its A4.4 bound (cold B 5 of 8, cold C 4 of 4, warm C 5 of 5); report mode "simulation (never evidence)", artifact chain clean, no claim permitted |
| `git diff --stat 1aad1f8 -- bench/ozmap_rep/acceptance/` and `git status` on it | empty: no acceptance file changed since 1aad1f8; round 1 accepted no test change, so none was expected |
| frozen paths (`bench/ozmap/`, `bench/ozmap_rep/ops/`, `oz_*.py`, `examples/`) | unchanged in git since 1aad1f8 |
| full repository suite | not rerun; round 1 reports the same 50 failures and 3 collection errors outside `bench/ozmap_rep/` (tiktoken missing in the system interpreter) |
| local probes | certificate authority true, replay fixtures all ok, pinned tokenizer available, classification valid (R = margin, temp_class, verdict), baseline wave gate ok (exp 2026-11-03T15:18:43Z, 236 h left), baseline inventory clean, `freeze.json` absent (expected) |
| `startup_instruction_files(['skills/.system/imagegen/SKILL.md', ...])` | returns the skill file: the telemetry certificate cannot pass today (B1, B6) |
| `ledger_problems` on a ledger row without attempt or marker | reports a permanent problem (B2) |

## Disputes

`disputes.md` does not exist and build-notes.md reports none. Nothing to rule on; the acceptance suite stands as
written.

## Blockers

**B1 BLOCKER (A4.2, A4.3, A4.5: nothing stops a freeze and a telemetry run that are certain to fail).** The harness
correctly applies the strict reading while P1, P4 and P5 are unsigned, but no code refuses to proceed. With
`code_mode_host` disabled every exec emits the error item "Code Mode is unavailable ...", so the telemetry call is
judged `uncertain`, its outcome differs from `expected_outcome: ok`, and `telemetry_failures` blocks the run directory
for good. Independently, the CLI writes `skills/.system/*` at startup, which `startup_instruction_files` flags, so the
certificate fails even if the stream were plain. Running `freeze` then `telemetry --mode live` today spends 2 of the 4
Codex telemetry calls (A4.5), poisons the canonical run directory, and leaves one more telemetry attempt in the whole
experiment, after a new freeze and a council disposition.
Fix: (a) `freeze_command` refuses unless every pending slot is settled: `code_mode_host` either sits in
`SIGNED_OMITTED_DISABLES` or its notice is in a new signed notice slot (see B5), `SIGNED_STARTUP_FILES` covers every
name of the known startup inventory or B6 is signed otherwise, and P1, P2, P3 each have a recorded signed decision (an
explicit "strict" decision counts). (b) `telemetry` runs a local preflight first: `record_features` on a worker home
(no model request) already produces the startup runtime inventory; refuse before any charged call when
`startup_instruction_files` of that inventory is non empty. (c) Add `SIGNED_CLI_NOTICES` to config and treat an
`item.completed` error item with exactly `{id, type, message}` whose message starts with a signed notice like a
`KNOWN_NOTICES` entry in `events.classify_stream`; today a P4 ruling that keeps the disable has no code path, and
filing that notice under `SIGNED_TRANSPORT_NOTICES` would be wrong. Tests: freeze refuses with the current empty
slots; telemetry refuses with no charged call when the features probe shows `skills/.system/x/SKILL.md`; a signed CLI
notice item is plain.

**B2 BLOCKER (A4.5, RT1.5: one launch check failure mid group makes the live run directory unusable).**
`prepare_call` appends each live charge to the experiment ledger before the group is complete. When a later member's
preparation raises `Stop` (launch verification, baseline inventory, leak check), `abandon` deletes the earlier
members' markers and prompts but their ledger rows stay. `ledger_problems` then finds ledger calls with neither an
attempt nor a marker, so every later live cell exits 15, and the scorer records an accounting failure that withholds
every claim. Verified with a one row ledger: the problem is reported and nothing clears it.
Fix: write the live ledger rows for a group only after every member is prepared, immediately before the threads
start (a crash between that point and the attempts leaves markers, which recovery turns into interrupted attempts as
today). If you prefer to keep the early write, `abandon` must append an `abandoned_unspawned` row to `attempts.jsonl`
(charged, no capture, skipped by `_rejudge` like `interrupted`) so ledger and attempts reconcile. Test: in live mode
with fakes, make the third prepare of a group fail verification; the cell exits incomplete, and the next cell passes
`ledger_problems`.

**B3 BLOCKER (A4.3: an interrupted call is uncertain execution, yet the scorer treats it as clean).** A runner that
dies mid call loses the child's stream: stdout and stderr are pipes, so the child loses its reader and its events are
never seen. Recovery records `interrupted` with no `events`, the scorer's leakage loop only looks at
`events.verdict`, and `_rejudge` skips interrupted rows. A4.3 says "uncertainty whether execution occurred
invalidates replication efficiency". Today such a call costs only that cell's token claim (usage incomplete) while
other cells and the other backend still produce claims, which contradicts the global leakage reading the build
adopted (C10 not adopted). Runner death is not exotic here: `CALL_TIMEOUT_S` is 1200 s and the driver's foreground
limit is 600 s.
Fix: (a) spawn children with stdout and stderr redirected to files in a per slot raw directory treated like a worker
home for the token rule (for example `D/homes/raw-<slot>/`), never pipes. A dead runner then leaves a complete stream
and the child is not killed by a broken pipe. In `after_group` read, redact, write to `captures/`, then delete the raw
files. In `recover_inflight`, judge an orphan from its raw files when they exist (the call can be accepted like any
other, and its batch is not resent). (b) An orphan without a readable raw stream is listed in leakage as "uncertain: no
capture" unless the B7 ruling says otherwise. (c) build-notes: live cells are launched detached (run_in_background),
never in a foreground shell with a limit below the cell's duration. Tests: kill the runner while a fake child is
mid stream; recovery judges the completed raw stream and redacts it; with the raw file removed, the scorer lists the
call under leakage.

**B4 BLOCKER (A4.2: the telemetry does not establish CODEX_HOME authentication at the worker paths).** The pinned
CLI lists `secret_auth_storage` as stable and enabled. As far as I know the upstream auth storage keys its OS keyring
entry by a hash of the canonical CODEX_HOME path, so a keyring credential is per path. The certificate's empty home
checks run `login status` in `homes/probe-empty`, a path no worker uses, so they prove nothing about
`homes/worker-<k>`, where the calls run and where a refresh could be written to the keyring and read back on the next
call while the reconstructed auth.json is ignored. Reconciliation would catch an auth.json that disappears, but not a
CLI that reads a keyring credential for that path.
Fix: (a) In telemetry, before the exec probe and again after the plain call, for each of the four worker paths: remove
the worker home content, leave the directory empty, run `login status` with CODEX_HOME at that path (local, no model
request), and require "not logged in"; record the result per slot in the certificate and make
`telemetry_certificate` require all eight. (b) Check locally whether `--disable secret_auth_storage` is accepted. If it
is, add it to the frozen disable list before freeze (it narrows the credential sources and A4.2 already asks for every
available disable); otherwise record it as unsupported. Test: a fake CLI that reports logged in for a worker path with
an empty home fails certification.

**B5 BLOCKER (prospective ruling P1 and P4, A4.3: CLI and transport notices).** Without these, one transient
reconnect, and with `code_mode_host` disabled every call, makes the whole run invalid. Recommended text for Astra A
and Opus B: "On codex-cli 0.160.0, (1) a top level event with exactly {type, message} whose message starts with
`Reconnecting... ` and (2) an item.completed error item with exactly {id, type, message} whose message starts with
`Falling back from WebSockets to HTTPS transport.` are transport events, not tool activity, provided the stream holds
no tool item; they are recorded per call. (3) `--disable code_mode_host` stays in the frozen arguments and the error
item with exactly {id, type, message} whose message starts with `Code Mode is unavailable because code-mode host is
disabled` is a plain CLI notice under A4.3. No other text is added." Keeping the disable and naming the exact notice
is closer to A4.2 ("every available disable option") than omitting the option. Implement (1) and (2) in
`SIGNED_TRANSPORT_NOTICES`, (3) in the new `SIGNED_CLI_NOTICES` (B1 c); the authentication check keeps running first,
so a 401 inside a reconnect text still stops Codex.

**B6 BLOCKER (prospective ruling P5, A4.2: bundled skills written at startup).** The certificate cannot pass while
`SIGNED_STARTUP_FILES` is empty. A ruling must state the evidence on which `skills/.system/*` is accepted as not an
effective instruction source. Recommended: before freeze, the harness records the startup inventory from the local
features probe (names and hashes); the telemetry call's `input_tokens` is compared with the same call's expected
prompt size, and the ruling accepts the listed names only if the call's input tokens stay within a stated margin
of a reference reading taken without those files (or if the pinned CLI accepts `skip_host_skill_discovery` or an
equivalent switch, use it and record it). If no such evidence can be produced without extra model calls, the ruling
must say so plainly and name the residual risk in the report. Implement as names plus hashes, not patterns, so a
changed skill file blocks certification.

**B7 BLOCKER (prospective ruling P2, A4.7, A4.11: one retry makes a cell's token gate inconclusive).** Unchanged from
round 1 B5: any infrastructure retry or interrupted attempt leaves the cell's usage incomplete, so every token gate on
that cell is inconclusive, and with about 55 live calls one transient failure is likely. Sign the bounded rule
proposed in round 1 B5 (unknown cost counted as 0 tokens in the reference arm and as the successful retry's input
plus output tokens in the arm under test, reported as `bounded`), and in the same ruling decide B3 (b): whether an
orphan without a readable stream counts as uncertain execution. With B3 (a) in place that case becomes rare.

**B8 BLOCKER (prospective ruling P3, A4.12: the live run stalls after the first Codex call).** `codex_quota_gate`
refuses a live Codex cell unless the newest owner session file is newer than the last live Codex attempt. Worker
calls run `--ephemeral` in their own homes, so only an owner home Codex session can refresh it, and that is a model
call (a driver Astra call or a trivial `codex exec`) that no allocation or A4.13 cap names. Telemetry already ends a
live Codex call, so the first evaluation cell is refused until such a call is made, and so is every later Codex cell.
The ruling must name the reading source and its accounting: either (a) a small Codex "quota reading" allowance in the
owner home, counted under A4.13 with its own cap (about 10: one per Codex cell), or (b) acceptance of the driver's
Astra calls between cells as readings, counted as Astra review calls, or (c) a headroom rule (for example, launch
only below 70% with the last reading at most N hours old) that tolerates staleness within one wave. The code change
is then one predicate in `quota.py` plus a log line.

## Changes

**C1 CHANGE (uncaught isolation errors).** `prepare_call` catches only `Stop`. `Isolation.prepare` raises
`IsolationError` when a worker home or working directory cannot be removed, which is plausible on Windows when a
lingering process holds a file. The exception escapes `_run_locked`, the runner exits 1 with a traceback (not an
INTERFACE.md code) and `state.json` stays `running`. Fix: catch `IsolationError` in `prepare_call` and in
`worker_probe`, abandon the group as for `Stop`, and raise `Stop(EXIT_INCOMPLETE, ...)`.

**C2 CHANGE (A4.2 reseed record).** A4.2 asks to record the new auth.json hash, last_refresh and exp before a wave is
considered after a reseed. `wave-gates.jsonl` rows carry only exp and hours left. Add `isolation.auth_record(baseline)`
(hash, last_refresh, exp; no token text) to every wave gate row, and note in the row when the hash differs from the
previous row.

**C3 CHANGE (features record never blocks).** `record_features` writes the effective state but launches whatever it
shows. Compare `enabled_tool_features` with the frozen expectation (`unified_exec` only, from `cli-flags.json`) and
require exit code 0; any difference refuses the cell before a charged call. With a hash frozen executable a difference
means remote configuration or a probe failure, and both should stop.

**C4 CHANGE (correctness comparisons are counts).** `boolq_gate` checks `err_c <= err_a` and the materials gates
compare correct counts, so C may break one job and fix another. A4.10 says BoolQ C "must add no gold errors relative
to A". Report per job added errors (jobs wrong in C and right in A) for every gate, and either gate BoolQ on that
stricter reading or record the count reading as the frozen interpretation before freeze.

**C5 CHANGE (redaction for Sonnet).** Sonnet captures are written unredacted. Apply the generic credential patterns
(JWT, API key, bearer) to Sonnet stdout and stderr as well and mark any hit as a credential disclosure.

## OK

**O1 OK (round 1 fixes).** Locks are taken without waiting before any state is read; recovery runs first, refuses on
a live recorded child, reconciles every Codex marker against its prepared generation and stops Codex on ambiguity;
markers survive until reconciliation; authentication failure is judged first on the error channels only; propagation
checks the prepared generation and `last_refresh`; telemetry goes through the evaluation lifecycle and publishes only
after reconciliation; any failed telemetry blocks evaluation; tool evidence is sticky; a delivered reply is never
resent; settled versus complete cells, classification validation, unresolved audits, validity before magnitude and
the persistent safety kill are implemented and tested.

**O2 OK (auth safety).** Only the baseline and worker homes hold token text; evidence keeps hashes and names; the
wave gate reads exp locally, fails closed and names `CODEX_HOME=~/.ozmap_rep/baseline codex login`; nothing reads or
copies `~/.codex/auth.json`; fake mode refuses the owner baseline and the live run directory.

**O3 OK (budgets).** Allocations, two reserves per allocation, caps (Codex 38, 4, 20, 62; Sonnet 26, 2, 12, 40), the
reserve reasons, the experiment ledger counted in full and the A4.13 caps (20, 40, 4, 40, global 206) match the
signed text. The dry run stays within every A4.4 bound.

**O4 OK (gold error scoping).** `bootstrap.assess` invalidates efficiency only for an operation in R with a proposed
rule; other bootstrap errors are measured; malformed or missing output is a completion failure; BoolQ is never in R;
admitted operations outside R are reported as classification misses. Applying an invalid operation to the whole
backend's materials gates is the conservative reading round 1 accepted.

**O5 OK (cache certification).** The archived pair, its envelopes and the decoder hash verify, certificate authority
is separate from pair validity, replay fixtures pass, positive cached input without authority and positive
`cache_write_input_tokens` are unverified, and partial counter violations stay visible.

**O6 OK (scoring gates).** Exact fractions, unrounded ratios, cold makespan not gated, bootstrap charged fully to cold
B and C, magnitude invalid before any ratio on any validity problem or safety kill, inconclusive on incomplete cells,
usage, evidence or open audits, simulation never evidence, run bound freeze and artifact chain required for claims.

**O7 OK (resumable cells, apart from B2 and B3).** Terminal batches are read back and never resent, first attempts
precede retries, round 2 overflow is derived deterministically from round 1 on resume, DONE and SETTLED are never
rerun, unmet requirements refuse.

## Before the freeze

1. Fix B1 to B4 and C1 to C5, with regression tests; acceptance and red team suites unchanged.
2. Rulings B5 to B8 signed by Astra A and Opus B (prospective revisions under A4.13.2), implemented in the signed
   slots, then `run freeze`.
3. Operational: every live cell and telemetry run is launched detached; the driver passes a fresh Claude weekly
   reading on each command.

Preparation calls after this review (ledger sums): Astra 8 of 20, Opus 17 of 40, Fable 1 of 4, Sonnet 1 of 40.
Evaluation calls so far: 0 Codex, 0 Sonnet.

Signed: Opus council reviewer, code correctness lens, round 2.
