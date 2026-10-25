# Closure round 2: Opus B, code correctness lens (2026-10-25)

Reviewer: fresh Opus workflow subagent (claude-opus-5-5), logged in call-ledger.jsonl as role
`closure-code-reviewer-r2` (Opus 32 of 40 after this call). Reviewed: branch oz-0.9 at 49b4e52 against
amendment-4.md, amendment-4-13-caps.md, amendment-4-14-fail-closed.md, build-notes.md and closure-ledger.md. This is
closure round 2 of at most two (A4.14.3). No model call and no Codex call was made; only the harness' own fakes and
temporary directories were used. The sealed reviewer ASTs were not read. Nothing in bench/ozmap, the core oz_* modules
or bench/ozmap_rep/ops was touched (`git diff --name-only 1aad1f8 HEAD` lists only bench/ozmap_rep and this design
folder; ops unchanged).

## Item 0: the integrated A4.14 text

A4.14 confirmed: Opus B

The text is unchanged since closure round 1, where it was confirmed with the three Opus B replacements integrated
verbatim (validity before interruption in A4.14.1, the last sentence of A4.14.2, the removal limit in A4.14.4).

## Runs made by this review

| check | result |
|---|---|
| `python -m pytest bench/ozmap_rep -q -p no:cacheprovider` | 600 passed (5 min 5 s), exit 0 |
| `python -m bench.ozmap_rep.run dry --run-dir <scratch>/closure-opus-r2/dry` | exit 0: 16 of 16 cells complete, 52 fake calls, 0 external calls; report: isolation passed, leakage 0, accounting failures 0, artifact problems 0, no stopped, interrupted or invalid cell; every cell state `complete` |
| `rulings.readiness_problems()` on the working tree | 9 problems: P1 to P5, D1 and D6 unsettled, P4 notice predicate inactive, no approved P5 startup manifest; `run freeze` therefore refuses |

Acceptance tests (A4.14.4). `git diff 1aad1f8 HEAD -- bench/ozmap_rep/acceptance` is the same as in closure round 1:
only `INTERFACE.md` (the resumability sentence replaced by the A4.14.1 sentence, exit codes 19 and 20) and
`test_cli_plan_and_cells.py`, where `test_cli_cell_is_resumable_and_never_repeats_a_completed_call` is replaced by
`test_cli_cell_interrupted_is_never_resumed_or_rerun` (interrupted, records preserved, nothing rerun, the dependent warm
A cell interrupted without running), listed in the build notes replacement table. 49b4e52 touches no acceptance or red
team file (`git diff 192e8a6 HEAD -- bench/ozmap_rep/redteam` is empty). Within A4.14.4.

## Closure round 1 items

| item | ruling | evidence read |
|---|---|---|
| N1 (Opus), RTC1.1, O4 | closed | `score.score_run` attributes every per cell finding at its producer through `flag(target, message, *cells)`, so each entry of `cell_findings` is also in a run wide list (leakage, accounting, isolation or artifact) and `gates._validity` turns every gate `invalid`. The stopped predicate (not DONE or SETTLED, and INTERRUPTED, `running`, markers or attempts) matches `crash_scan` read only, so a crashed cell scored before any later admission gets its validity. My two round 1 reproductions are now `test_item15_..._fails_isolation_and_certification` (extended) and `test_n1_a_stopped_cell_with_an_unledgered_live_attempt_is_invalid`; both pass, as do the red team RTC1.1 tests. Call id to cell fallbacks use the `.` delimiter, so my C4 is gone |
| RTC1.2, my C2 | closed | `isolation.login_identity` reads session ids and authentication times from both tokens; `token_separation_problems` refuses a shared component and refuses when either side has no identity, so the degraded exact hash fallback I named in C2 no longer exists |
| O1 (Astra 10) | closed | `CellRun.execute` marks a `timed_out` child `killed`; `after_group` turns a killed child with a retryable outcome into a spawn failure, hence `unsettled`, uncertain, no retry, no propagation for the group, cell stopped. A delivered reply keeps its outcome |
| O2 (Astra 12) | closed | `worker_probe` and `TelemetryRun.worker_path_logins` hold `verified_guard` across the probe and call `exe.recheck()` before each child |
| O3 (Astra 13) | closed | `run_local` writes probe streams to raw files under D/homes; `probe_evidence` records sanitized evidence, disclosures and, when completeness is not established, `probe-uncertain.jsonl`, which `score_run` attributes to the cell (invalid) and `telemetry_failures` refuses |
| O5 (Astra 32) | closed | D6 is in `config.REQUIRED_RULINGS` with two bound annexes; readiness lists it as unsettled above; `_freeze_problems` rechecks the bound rulings |
| N1 (Astra) | closed | `usage.decode_sonnet` reports a negative counter or a cache contradiction as `invalid` whatever is missing, keeps `incomplete`; `account_usage` no longer indexes absent counters; `sonnet_envelope_violation` carries an envelope with a negative counter to the decoder |

## Round 3 items in the closure ledger

| item | ruling |
|---|---|
| Astra 1 | closed |
| Astra 2 | CHANGE, launch prerequisite D1; readiness refuses (checked) |
| Astra 3, Opus B3 | CHANGE, launch prerequisite P5 and D2; see C1 below, still open as a CHANGE |
| Astra 4, Opus B4 | closed in part; rest CHANGE (P3); readiness refuses |
| Astra 5 | CHANGE (P4); predicate inactive, readiness refuses |
| Astra 9 | closed |
| Astra 10 | closed (O1 above) |
| Astra 11 | closed; the per cell labeling I tied to N1 is fixed |
| Astra 12 | closed (O2 above) |
| Astra 13 | moot under A4.14.1 for the crash path; closed for the journal path and for output loss (O3) |
| Astra 14 | closed |
| Astra 15 | closed; per cell labeling fixed (O4) |
| Astra 16 | closed in part; launch environment reconstruction CHANGE (hand edits of preserved evidence are tampering, outside A4.14.2) |
| Astra 17 | moot under A4.14.1 for recovery bounds; rounding closed |
| Astra 23 | closed |
| Astra 32 | closed (O5) |
| Opus B1 | CHANGE; the A4.2 revision or an attended reading plan is still needed before live waves |
| Opus B2 | CHANGE; readiness refuses |
| RT3.1 | closed |
| RT3.2 | closed (RTC1.2) |
| RT3.3 | closed |
| D-R2-1 | closed |
| D-R2-2 | closed, upheld |

No item is open. I raise no new BLOCKER under A4.14.2: every gate decides validity run wide before inconclusiveness
(`gates._verdict`), every per cell finding is also a run wide finding, and the cases below can at worst stop a cell,
refuse the freeze or leave a label less specific than it could be.

## CHANGE items

C1 (P5 effective context procedure, carried from round 1, not addressed). `rulings.readiness_problems` checks that the
P5 annexes are bound and hash consistent, but no code requires the effective context verification procedure the
closure ledger says must be implemented with the annex. Once P5 is countersigned the freeze would open on the
signature alone. Add a readiness problem that holds until the procedure exists in code and the telemetry certificate
calls it.

C2 (a timed out local probe is treated as settled). In `run_local` a `TimeoutExpired` kills the tree and returns
normally with the killed exit code; a descendant still running after a normal exit is also killed and the probe
returns normally. `_guarded_probe` then reconciles the home as usual, so a refreshed auth.json written by a killed probe
can be propagated. `propagate` refuses an unreadable or older file, and the features probe fails on a nonzero exit, so
no result is affected; but by the O1 rule a probe whose tree had to be killed should propagate nothing and stop Codex.
The same applies to a timed out call that delivered its reply (`c['killed']` without `spawn_failure` still reconciles
normally in `after_group`).

C3 (per cell labels of settled and complete cells). The `invalid_cells` labeling covers stopped cells only. A settled
incomplete or complete cell that carries a finding keeps its state label; the run wide lists and every gate verdict
still say `invalid`, so nothing passes unflagged. Listing every cell with an attributed finding in `invalid_cells`
would make the report read the same way at cell level.

C4 (unattributed run wide findings). Telemetry certificate problems, malformed ledger lines, predecessor `codex-stop`
and safety kill findings and freeze problems are run wide only. That is correct (they belong to no single cell of this
directory), but report.md could say so next to the stopped cell list so "interrupted, no finding" is not read as "no
finding in the run".

## Verdict

No BLOCKER. Every closure round 1 blocker is closed with passing regression tests, every round 3 item is closed, moot
under A4.14.1 or a CHANGE whose worst outcome is a refused freeze or a stopped cell. The launch prerequisites (P1 to P5,
D1, D6, the P4 predicate, the P5 manifest and C1) still keep `run freeze` refusing, as intended.

Signed: Opus B (closure round 2, code correctness lens)
