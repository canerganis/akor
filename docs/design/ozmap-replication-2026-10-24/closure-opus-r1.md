# Closure round 1: Opus B, code correctness lens (2026-10-25)

Reviewer: fresh Opus workflow subagent (claude-opus-5-5), logged in call-ledger.jsonl as role
`closure-code-reviewer-r1` (Opus 29 of 40 after this call). Reviewed: branch oz-0.9 at 14a8359 against
amendment-4.md, amendment-4-13-caps.md, amendment-4-14-fail-closed.md, build-notes.md and closure-ledger.md. No model
call and no Codex call was made; only the harness' own fakes and temporary directories were used. The sealed reviewer
ASTs were not read. Nothing in bench/ozmap, the core oz_* modules or bench/ozmap_rep/ops was touched.

## Item 0: the integrated A4.14 text

A4.14 confirmed: Opus B

The three Opus B replacements are integrated verbatim: validity before interruption (A4.14.1, "A leakage or isolation
signal, a demonstrated accounting failure, or uncertainty about whether a tool executed ... makes the cell invalid
under A4.3 and A4.11, not merely interrupted. Only cells with no such finding are marked interrupted."), the rubric
addition (last sentence of A4.14.2) and the removal limit (last sentence of A4.14.4). A4.14.4 still says a replaced
test asserts "the cell is marked interrupted"; A4.14.1 and A4.14.5 decide that this applies only to a stopped cell
without a validity finding, so no text change is needed.

## Runs made by this review

| check | result |
|---|---|
| `python -m pytest bench/ozmap_rep -q -p no:cacheprovider` | 570 passed (4 min 34 s), exit 0 |
| `python -m bench.ozmap_rep.run dry --run-dir <scratch>/dry` | exit 0: 16 of 16 cells complete, 52 fake calls, 0 external calls; report: isolation passed, leakage 0, accounting failures 0, artifact problems 0, no interrupted or invalid cell |
| `rulings.readiness_problems()` on the working tree | 8 problems: P1 to P5 and D1 unsettled, P4 notice predicate inactive, no approved P5 startup manifest; `run freeze` therefore refuses |
| reproduction file (scratchpad `closure-opus-r1/repro/test_closure_r1_repro.py`) | 2 failed, both reproduce N1 below |

Acceptance tests (A4.14.4). `git diff 1aad1f8 HEAD -- bench/ozmap_rep/acceptance` touches only `INTERFACE.md` (the
resumability sentence replaced by the A4.14.1 sentence, exit codes 19 and 20 added) and
`test_cli_plan_and_cells.py`, where `test_cli_cell_is_resumable_and_never_repeats_a_completed_call` is replaced by
`test_cli_cell_interrupted_is_never_resumed_or_rerun`, which asserts what A4.14.4 requires (interrupted, records
preserved, nothing rerun, the dependent warm A cell interrupted without running) and is listed in the build notes
table. No other acceptance assertion changed. This is within A4.14.4.

## New BLOCKER under A4.14.2

### N1. A stopped cell with a detected validity failure is reported "interrupted, no finding"

Rule: A4.14.1 makes a stopped cell with a leakage or isolation signal or a demonstrated accounting failure invalid,
not merely interrupted; A4.14.2 says any path that labels a detected validity failure as interrupted is a BLOCKER.

Code path: `score.score_run`, the block after `# A4.14.1: the preserved records of every stopped cell decide its
validity first` (score.py, the `invalid_cells` loop). A finding is attributed to a stopped cell only when its text
contains one of the cell's call ids in one of three exact positions (`p.startswith(f'{i}:')`, `f' {i}:' in p`,
`f'{i} ' in p`) or names one of its in-flight marker files. Findings that the scorer itself writes in other shapes are
never attributed:

* `a {probe} probe of {cell}: credential material was redacted from its output (A4.2)` (keyed by cell id; the item 15
  isolation signal, raised before any charged call, so the cell has no call id at all);
* `live attempts missing from the experiment ledger: ['<call id>']` (the call id is inside a list repr, followed by a
  quote, so none of the three patterns matches; the item 11 accounting failure);
* `{cell} {batch}: {n} terminal attempts` and `{b}/{w} {allocation}: {n} physical calls above nominal plus reserve`
  (keyed by cell or allocation);
* `{cid}: no passing wave gate record`, `{cid}: no features record`, `{cid}: the features record did not pass` (live,
  keyed by cell id);
* `Codex evaluation stopped by authentication reconciliation (A4.2)` when `codex-stop.json` names the stopped cell.

The run wide gates still return `invalid` (isolation failed or accounting failures present), but `validity.interrupted`,
`cell_states` and report.md ("stopped cells interrupted, no finding: [...]") state that the cell has no finding, and
`validity.invalid_cells` omits it.

Reproduction (fakes and temporary directories only; both fail at 14a8359):

```
test_probe_disclosure_cell_is_labeled_interrupted_without_finding
  isolation failed
  interrupted ['codex-materials-cold-A']
  invalid_cells {}
  cell_states interrupted
  AssertionError: a cell stopped by an isolation signal must be invalid

test_unledgered_attempt_of_a_stopped_cell_is_labeled_interrupted_without_finding
  (live fixture, sonnet-materials-cold-A with stop_after=2, then one of its ledger rows removed)
  accounting ["live attempts missing from the experiment ledger: ['sonnet-materials-cold-A.r1.b00.t0']"]
  interrupted ['sonnet-materials-cold-A']
  invalid_cells {}
  AssertionError: a stopped cell with an accounting failure must be invalid
```

The first test is `tests/test_a414_fail_closed.py::test_item15_a_probe_disclosure_fails_isolation_and_certification`
with one more assertion; the second follows `test_item11_a_live_attempt_missing_from_the_ledger_is_an_accounting_failure`
on a stopped cell.

Fix: attribute findings to cells structurally where each finding is produced, not by matching strings afterwards.
Keep a `cell_findings: dict[cell id, list]` and add to it at each producer: per attempt findings by `a['cell']`
(leakage, usage, launch evidence, credential disclosure, unledgered live attempts, artifact problems of that call),
probe disclosure rows by `r['cell']`, duplicate terminal attempts by `k[0]`, allocation overcounts to every cell of
that backend, workload and allocation, wave gate and features findings by `cid`, `codex-stop.json` and
`run-stop.json` by their `cell` field, open probe and lost markers by the cell directory they sit in. A stopped cell
with any entry is invalid. Add the two reproductions above as regression tests, plus one for duplicate terminal
attempts in a stopped cell.

## Open and disputed items from closure-ledger.md

| item | ruling | note |
|---|---|---|
| Astra 1 | closed | `rulings.annex_problems` binds each annex by path and sha256 into the ruling text and freeze.json; test passes |
| Astra 2 | CHANGE, agreed | readiness refuses while D1 is unsettled (checked above) |
| Astra 3, Opus B3 | CHANGE, agreed, with C1 | see C1: signing the P5 annex alone would unlock the freeze before the verification procedure exists |
| Astra 4, Opus B4 | closed in part, rest CHANGE, agreed | malformed latest reading is selected and rejected; P3 unsettled blocks the freeze |
| Astra 5 | CHANGE, agreed | P4 inactive, readiness refuses |
| Astra 9 | closed | `procs.Tree` job object, `after_group` propagates nothing when any group member did not settle (read in run.py) |
| Astra 10 | closed | recovery is gone; a killed child whose outcome would be retryable becomes `unsettled` with an uncertain verdict (`after_group`, the `spawn_failure and outcome in RETRYABLE` branch); the scorer counts `unsettled` as leakage. My earlier BLOCKER is withdrawn |
| Astra 11 | closed for the harness; per cell labeling is N1 | both ledger directions are checked run wide; a stopped cell carrying the failure is still labeled interrupted (N1) |
| Astra 12 | closed | |
| Astra 13 | moot under A4.14.1 for the crash path; closed for the journal path | |
| Astra 14 | closed | |
| Astra 15 | closed for isolation and certification; per cell labeling is N1 | disclosures fail isolation and telemetry certification; my earlier BLOCKER on consumption is withdrawn |
| Astra 16 | closed in part; reconstruction CHANGE, agreed | a hand edit of preserved evidence is tampering, outside A4.14.2 |
| Astra 17 | moot for recovery bounds; rounding closed | |
| Astra 23 | closed | |
| Astra 32 | CHANGE, agreed | review step before the freeze |
| Opus B1 | CHANGE, agreed | worst outcome is an interrupted cell; the A4.2 revision or an attended reading plan is still required before live waves |
| Opus B2 | CHANGE, agreed | readiness refuses |
| RT3.1 | closed | |
| RT3.2 | closed, with C2 | session comparison plus exact hashes; my earlier BLOCKER is withdrawn because the baseline and owner logins on this machine both carry a session claim and differ |
| RT3.3 | closed | |
| D-R2-1 | closed | the rewritten RT2.1 test asserts exit 19, `unsettled`, no `.t1`, leakage, cell invalid |
| D-R2-2 | closed, upheld | |

## CHANGE items

C1 (P5 effective context). `rulings.readiness_problems` checks that the P5 annexes are bound and hash consistent, but
nothing in code requires the effective context verification procedure that the closure ledger says "is not yet
implemented and must be, with the annex, before the freeze". Once P5 is countersigned the freeze would open without
it. Add a readiness check that the procedure is implemented (for example a function the telemetry certificate calls,
whose absence is a readiness problem), so a signature cannot stand in for code.

C2 (RT3.2 degraded comparison). `isolation.token_separation_problems` compares login sessions only when both sides
carry a `session_id` claim (`if my_login and their_login and my_login == their_login`). If a future token format drops
the claim, the check silently falls back to exact token hashes, which a rotated copy passes. Fail closed: when the
owner auth.json exists and either side lacks a login identity, report a problem.

C3 (crash then score). `score_run` treats only `state == 'interrupted'` as stopped. A run directory scored right after
a crash, before any further admission ran `crash_scan`, keeps the crashed cell in state `running`; its lost markers
and captured streams are still judged run wide (accounting failure, leakage), so nothing passes unflagged, but the cell
is labeled `running`. Score a `running` cell, or any cell with markers, attempts and no stop file, as stopped, using
the same attribution as N1.

C4 (cell id prefixes). With N1 fixed by structure this disappears; if string matching stays, note that a cell id is a
prefix of its call ids, so matching on the cell id needs a delimiter (`.` or `:`) to avoid one cell's findings
matching another's call ids in future cell names.

## Verdict

One BLOCKER (N1), with reproducing tests. Every earlier item is closed, moot under A4.14.1 or a CHANGE whose worst
outcome is a refused freeze or an interrupted cell. After N1 is fixed with its regression tests, I expect to sign in
closure round 2.
