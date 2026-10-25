# Closure round 2 targeted verification (owner decision 3)

Reviewer: fresh Opus workflow subagent, logged in call-ledger.jsonl as `closure-verify-r2` (Opus total 35 of 40).
Scope: only whether commit 4fee739 (`bench/ozmap_rep: closure round 2 fixes (owner decision 3)`) closes O3 and N1, and
whether it changes anything outside those fixes. This is not a general review. No model or Codex call was made, the
sealed ASTs were not read, bench/ozmap, the core oz_* modules and bench/ozmap_rep/ops were not touched.

## Verdict

| item | disposition |
|---|---|
| O3 (Astra 13, probe marker removed before the disclosure record) | closed |
| N1 (a stopped telemetry cell had no validity) | closed |

No open blocker. One CHANGE under A4.14.2 (not a blocker) is recorded below.

## Commit scope

`git show --stat 4fee739`: four files, `bench/ozmap_rep/run.py` (13 lines), `bench/ozmap_rep/score.py` (16 lines),
the new `bench/ozmap_rep/tests/test_closure_r2.py` (178 lines) and `closure-ledger.md` (51 lines). The run.py hunk
touches only the normal completion path of `CellRun._guarded_probe`. The score.py hunks touch only the stopped cell
inventory in `score_run` and the state check in `convergence`. No acceptance, red team, earlier test, ops, bench/ozmap or
core oz_* file changed in this commit.

## O3: closed

`_guarded_probe` now computes `disclosed`, appends the record to `evidence/probe-disclosures.jsonl` and only then calls
`path.unlink()` on the probe marker; `Stop(EXIT_AUTH_GATE, interrupt=True)` follows the unlink, and the raw stream files
are removed only on the non disclosed path. Every crash window is therefore covered:

1. Before the disclosure write (after finish or reconciliation, or in the write itself): the marker stays, and
   `score_run` flags it as "local probes ended in an unknown state" attributed to its cell directory, which also puts the
   cell in the stopped inventory (inflight marker), so the cell is invalid.
2. After the write, before the unlink: both the marker and the disclosure record flag the cell.
3. After the unlink, before the raise: the disclosure record flags the cell (structured `cell` field) and the cell's
   state.json is `running`, so it is stopped and invalid. The raw stream is kept.

The SpawnFailure path already recorded through `probe_evidence` before its unlink and is unchanged.

Mutation check: with the parent commit's run.py in an exported copy of 4fee739 (score.py at 4fee739), both O3 tests fail
(`the probe marker is kept through every failure before the disclosure record` and `assert [False] == [True]`); with the
fixed run.py they pass.

## N1: closed

`score_run` now adds `telemetry` and `features` to `states` when their `cells/<id>` directory exists (`complete` for
DONE.json, `incomplete` for SETTLED.json, otherwise the state.json state) before the stopped cell loop, so a stopped
telemetry cell receives `cell_findings['telemetry']`, becomes `invalid`, enters `invalid_cells` and is reported in
`cell_states`. `specs`, `results`, `by_cell`, the cell summaries, `R_cells` and the gates still read the sixteen
evaluation cells only; the later `states[...]` reads (lines 806 and 857 to 860) use evaluation cell ids only.
`convergence` filters NON_EVALUATION out of `cell_states`. Gates do not read `validity['interrupted']`.

Mutation check: with the parent commit's score.py (run.py at 4fee739), the three N1 tests fail; with the fixed score.py
they pass.

## CHANGE (A4.14.2, not a blocker)

A successful standalone `features` command is now reported as an interrupted administrative cell. The `features`
entry point replaces `_run_locked` with a function that returns `EXIT_OK` without writing DONE.json or a final state, so
`cells/features/state.json` stays `running` (written by `_guarded`). The new N1 loop then classifies it as stopped, and
with no finding it becomes `interrupted`. Reproduced in an exported copy with the harness' Live fakes: telemetry exit 0,
`run.features(...)` exit 0, then `score_run` gives `state.json` `running`, no DONE.json,
`cell_states['features'] == 'interrupted'`, `validity['interrupted'] == ['features']`, `invalid_cells` empty, isolation
passed. Worst outcome: a spurious interrupted label on a completed administrative cell in the report; no gate,
validity verdict or convergence check reads it, and no invalid result is hidden. Suggested fix, if the owner wants it:
have the `features` entry point write DONE.json (or `state('complete')`) on success.

## Tests

| command | result |
|---|---|
| `python -m pytest bench/ozmap_rep/tests/test_closure_r2.py -q` at 4fee739 | 5 passed |
| same, parent run.py only (exported copy) | 2 failed (both O3), 3 passed |
| same, parent score.py only (main checkout, score.py restored to 4fee739 right after; `git status` clean for bench/ozmap_rep) | 3 failed (all N1), 2 passed |
| `python -m pytest bench/ozmap_rep -q` at 4fee739 | 605 passed in 252 s, exit 0 |
