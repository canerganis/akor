# Replication harness: red team closure round 2 (2026-10-25)

Reviewer: one fresh Opus subagent (claude-opus-5-5, high effort), logged in call-ledger.jsonl as `opus /
closure-redteam-r2 / review` (Opus 32 of 40 after the entry; Astra 15, Fable 2, Sonnet 1; global 50 of 206). Target:
`bench/ozmap_rep/` at 49b4e52 (closure round 1 fixes). Closure round 2 of at most two (A4.14.3). Goal: make the
harness let an invalid, leaked, misaccounted or wrong result reach the result report unflagged, or harm the owner's
Codex login. Method: code reading, the existing fakes and temporary directories. No `codex` or `claude` was run, no
model or Codex call was made, the real baseline, live run directory, experiment ledger, owner home and session files
were not read or written, and the sealed reviewer ASTs were not read.

Verdict: no new BLOCKER under A4.14.2, and no earlier blocker stays open. No red team test was added, so nothing was
committed under "bench/ozmap_rep: red team closure 2". Seven CHANGEs follow (three carried from closure round 1).

```
python -m pytest bench/ozmap_rep -q                          600 passed in 309 s (49b4e52)
python -m bench.ozmap_rep.run dry --run-dir <scratch>        exit 0: 16/16 cells complete, 52 fake calls, 0 external;
                                                             leakage 0, accounting 0, artifact 0, isolation passed,
                                                             no invalid and no interrupted cell
```

## Ledger items

Every entry of closure-ledger.md with this round's status. The launch prerequisite CHANGEs stay CHANGE: `run freeze`
refuses (exit 14) and `verify_freeze` repeats the check before every dispatch, so no live result can exist while they
are missing, and `score._freeze_problems` now checks the rulings bound in the run's freeze again
(`rulings.bound_problems`).

### Closure round 1 items

| item | status | evidence |
|---|---|---|
| O1 (Astra 10) | closed | `CellRun.execute` sets `c['killed']` on `timed_out`; `after_group` turns a killed child with a retryable judged outcome into a spawn failure, recorded `unsettled` with verdict `uncertain`, never retried; `test_o1_*` pass |
| O2 (Astra 12) | closed | `_guarded_probe` and `TelemetryRun.worker_path_logins` run under `Executables.verified_guard` with `recheck()` before each child; `test_o2_*` pass |
| O3 (Astra 13) | closed | `run_local` writes probe streams to `D/homes/raw-<slot>/`; `probe_evidence` records `probe-failures.jsonl`, a disclosure in `probe-disclosures.jsonl`, and `probe-uncertain.jsonl` when completeness is not established; the scorer flags each uncertainty row for its cell and `telemetry_failures` refuses certification; `test_o3_*` pass |
| O4 (Astra 15) | closed | the probe disclosure cell is `invalid` and absent from `validity.interrupted` (extended item 15 test passes) |
| O5 (Astra 32) | closed | `D6` is in `config.REQUIRED_RULINGS` with two bound annexes; readiness, `verify_freeze` and the scorer refuse without it; `test_o5_*` pass. I agree it did not meet A4.14.2 |
| N1 (Astra) | closed | `usage.decode_sonnet` reports present contradictions as `invalid` whatever is missing; `run.sonnet_envelope_violation` keeps a negative envelope counter visible to the decoder; `account_usage` never indexes an absent counter; `test_n1_*` pass |
| N1 (Opus) | closed | per cell attribution by structured fields (`cell_findings`); an unledgered live attempt and duplicate terminal attempts make the stopped cell invalid |
| RTC1.1 | closed | `score_run` attributes every per attempt, per capture, per marker, per probe and per stop record finding to its cell and treats a cell left `running`, holding markers or having attempts as stopped (read only); both `redteam/test_redteam_closure1.py` RTC1.1 tests pass |
| RTC1.2 (RT3.2) | closed | `isolation.login_identity` reads the access token `session_id`, the id token `sid` and `session_id`, and `auth_time`/`pwd_auth_time` with the account id; any shared component refuses and a missing identity on either side refuses; the RTC1.2 test passes |

### Round 3 items

| item | status | note |
|---|---|---|
| Astra 1 | closed | annex binding by `rulings.annex_problems`; D6 annexes added (O5) |
| Astra 2, 3, 5, 32 | CHANGE (launch prerequisites) | agree; 32 is now also enforced (O5) |
| Astra 4 | closed in part, rest CHANGE (launch prerequisite P3) | agree |
| Astra 9 | closed | see R2C5 for the residual unsupervised resume CHANGE (C1 of round 1) |
| Astra 10 | closed | superseded by O1, closed |
| Astra 11 | closed | see R2C3: the reservation abandon unlinks the marker, contrary to its docstring and to the ledger's wording; no unflagged path |
| Astra 12 | closed | superseded by O2, closed |
| Astra 13 | moot under A4.14.1 (crash path), closed (journal path) | superseded by O3, closed |
| Astra 14, 16, 17, 23 | as the ledger states | agree; the 16 and 17 residuals stay CHANGE |
| Astra 15 | closed | superseded by O4, closed |
| Opus B1 | CHANGE | an operational stop; agree |
| Opus B2, B3, B4 | CHANGE (launch prerequisites) | agree |
| RT3.1 | closed | agree |
| RT3.2 | closed | closed by RTC1.2 |
| RT3.3 | closed | agree; see R2C6 for the report line it adds |
| D-R2-1 | closed | RT2.1 asserts the A4.14.1 behavior and passes |
| D-R2-2 | closed (upheld) | no change |

## Attacks tried that found no BLOCKER

* **Per cell labels of stopped cells.** Every finding source in `score_run` was traced to `flag` with a cell. Not
  attributed: experiment ledger torn lines (`bad_lines`), `simulation`, `freeze_problems`, classification problems and
  superseded directory stop files. Each is run wide, enters the list `gates._validity` reads, and makes every gate
  `invalid` before `inconclusive` (`gates._verdict`); none is one of the A4.14.1 per cell signals (leakage, isolation,
  demonstrated accounting failure, unsettled call) of a cell in this run. A torn ledger line that also swallows a stop
  time ledger row still leaves the live attempt unledgered, which is attributed to its cell.
* **Torn `attempts.jsonl` rows.** `run.jsonl` drops a malformed line silently (R2C2). Every way a row can be lost is
  backstopped: a dispatched call keeps its marker until it is recorded and reconciled (a lost row is a lost marker,
  attributed), a captured call has a capture without an attempt line (artifact problem, attributed, and the capture is
  judged for leakage), and a live call has its ledger row (missing from the run directory, attributed).
* **Event stream splitting.** `classify_stream` splits with `str.splitlines`, which also breaks at U+0085, U+2028 and
  U+2029 that a JSON writer leaves unescaped. This can only add `uncertain` lines (an unparseable fragment), never hide
  a tool item: verdict `uncertain`, leakage, the cell invalid. It is a false positive, R2C1.
* **Owner login.** Nothing writes below `Path.home() / '.codex'`; `codex login` is never run; the owner `auth.json`,
  `config.toml` and sessions are read for hashes, the credential store setting and quota readings only. Token
  separation runs at every live gate, at every reservation and under the authentication lock at every `prepare`, and
  now refuses a missing identity and any shared session or authentication time. A refused or failed reconciliation
  never propagates, so the baseline (a separate login) is the only credential a worker can spend.
* **Timeouts and probes.** A timed out Codex child without terminal evidence is unsettled; one that delivered its turn
  keeps its outcome, and any tool item its stream holds still decides the verdict. A probe whose `run_local` wait times
  out returns normally with partial output, which can only fail the features or login check (a stop), not pass it.
* **Answer chain.** Model, bootstrap and rule answers are rederived from verified captures and the capture derived
  bootstrap proposal bytes; audits and the frozen audit sample are recomputed; warm C reuses only rules cold C adopted.

## Changes (A4.14.2: worst outcome is a stopped, interrupted or invalid cell, or none)

* **R2C1. Stream lines are split at Unicode line separators.** `events.classify_stream`, `turn_usages`,
  `error_messages` and `turn_completed` use `splitlines()`. A plain reply whose agent message contains U+2028 (the
  model controls it; serde_json leaves it unescaped) is judged `uncertain`:

  ```
  >>> events.classify_stream(<thread.started, turn.started, agent_message "answer more", turn.completed>)
  verdict 'uncertain', uncertain [{'line': 2, 'reason': 'unparseable JSON event'},
                                  {'line': 3, 'reason': 'stdout line that is not a JSON event'}]
  ```

  The cell then becomes invalid for leakage that did not happen. Split on `'\n'` only (and strip a trailing `'\r'`),
  in these four functions; keep every other rule.
* **R2C2. `run.jsonl` drops malformed lines silently** and uses `splitlines()` as well; a row written with
  `ensure_ascii=False` that holds U+2028 is lost. Every loss is backstopped today (see above), but the scorer should
  read `attempts.jsonl` and the evidence files strictly, as `ledger_rows` reads the ledger, and report a torn line as
  an accounting or isolation finding; split on `'\n'`.
* **R2C3. `CellRun.abandon` unlinks a reserved marker** (run.py lines 1715 to 1716) although its docstring says "its
  marker stays" and the ledger (Astra 11) says the reservation keeps every member. With the `not_launched` row append
  suppressed on failure the reservation can leave no trace; nothing was launched, so no cost is lost. Keep the marker
  when the row append fails (this is C2 of round 1), and correct the docstring.
* **R2C4. Stop reasons are not evidence the scorer reads.** A `Stop` raised mid cell by `prepare_call` or
  `reserve_group` (token separation, baseline change, wave gate) reaches only `INTERRUPTED.json`, which the scorer
  does not read, so the stopped cell is labeled "interrupted, no finding". None of these reasons is a validity signal
  of an earlier call of the cell (the separation compares the current files, the earlier calls used the separate
  baseline it had accepted), so the label is correct today. Record each authentication or isolation stop as a
  structured `evidence/stops.jsonl` category so a later stop reason that is a validity signal cannot be lost.
* **R2C5 (C1 carried). An unsupervised child is resumed.** `procs.Tree.start` records `supervised False` on a refused
  job assignment, and `spawn` and `run_local` still call `resume()`. The call ends unsettled and the run stops, so it is
  flagged, but one evaluation call is spent. Kill the suspended child and record it `not_launched` instead.
* **R2C6 (C3 carried). `Isolation.propagate` checks only that the worker `auth.json` parses and is not older.** Require
  `tokens.access_token` and `tokens.refresh_token` before replacing the baseline. Since RTC1.2 a tokenless baseline
  also fails token separation at the next `prepare`, so this remains a stop, not a harm.
* **R2C7 (C4 carried). Report wording.** `render_md` prints "stopped cells interrupted, no finding" and "interrupted
  cells" from the same list; keep one. The RT3.3 `quota_gate_problems` are listed in `report.json` only; add one line
  to `report.md`.
