# Replication harness: red team closure round 1 (2026-10-25)

Reviewer: one fresh Opus subagent (claude-opus-5-5, high effort), logged in call-ledger.jsonl as `opus /
closure-redteam-r1 / review` (Opus 30 of 40 after the entry, counting the parallel closure code reviewer; Astra 13,
Fable 2, Sonnet 1). Target: `bench/ozmap_rep/` at 14a8359 (fail closed execution per A4.14). Closure round 1 of at most
two (A4.14.3). Goal: make the harness let an invalid, leaked, misaccounted or wrong result reach the result report
unflagged, or harm the owner's Codex login. Method: code reading, fakes and temporary directories. No `codex` or
`claude` was run, no model or Codex call was made, the real baseline, run directory, experiment ledger, owner home and
session files were not read or written, and the sealed reviewer ASTs were not read.

Verdict: two new BLOCKERs under A4.14.2 (RTC1.1, RTC1.2), each with failing tests in
`bench/ozmap_rep/redteam/test_redteam_closure1.py` (three tests, all fail on 14a8359). The full suite was green before
the new file was added:

```
python -m pytest bench/ozmap_rep -q                                    570 passed in 274 s (14a8359)
python -m pytest bench/ozmap_rep/redteam/test_redteam_closure1.py -q   3 failed in 5 s
```

## Ledger items

Every entry of closure-ledger.md, with this round's status. "CHANGE" entries the ledger already classified as launch
prerequisites stay CHANGE: `run freeze` refuses and `verify_freeze` repeats the check before any dispatch, so no live
result can exist while they are missing; nothing in this round contradicts that.

| item | status | note |
|---|---|---|
| A4.14 integrated text | confirmed | the code implements A4.14.1 to A4.14.4 as written, except RTC1.1 below |
| Astra 1 | closed | annex binding enforced by `rulings.annex_problems`; tests pass |
| Astra 2, 3, 5, 32 | CHANGE (launch prerequisites) | agree with the ledger |
| Astra 4 | closed in part, rest CHANGE | agree; malformed latest reading is selected and rejected |
| Astra 9 | closed | job object without breakaway; see C1 for one residual CHANGE |
| Astra 10 | closed | a killed child without terminal evidence is `unsettled` (uncertain), never retried |
| Astra 11 | closed | both directions of the ledger check hold; see C2 for one residual CHANGE |
| Astra 12, 14, 23 | closed | tests pass and the code paths match the ledger |
| Astra 13 | moot under A4.14.1 (crash path), closed (journal path) | agree |
| Astra 15 | closed for its scope | the disclosure fails isolation and certification; the stopped cell is mislabeled, which is new (RTC1.1) |
| Astra 16 | closed in part, rest CHANGE | agree |
| Astra 17 | moot under A4.14.1 (recovery bounds), closed (rounding) | agree |
| Opus B1 | CHANGE | agree; it is an operational stop |
| Opus B2, B3, B4 | CHANGE (launch prerequisites) | agree |
| RT3.1 | closed | ancestor walk covers the discovery names; the live run directory default sits outside the profile |
| RT3.2 | open | closed only when the access token carries `session_id`; with the identity in the id token only, a stale copy passes (RTC1.2) |
| RT3.3 | closed | live mode refuses a named sessions directory; gate rows record the source |
| D-R2-1 | closed | RT2.1 asserts the A4.14.1 behavior and passes |
| D-R2-2 | closed (upheld) | no change |

## Blockers

### RTC1.1 A stopped cell with a detected validity failure is labeled interrupted, or is never given its validity (A4.14.1, A4.14.2)

A4.14.1: "A leakage or isolation signal, a demonstrated accounting failure, or uncertainty about whether a tool
executed ... makes the cell invalid under A4.3 and A4.11, not merely interrupted. Only cells with no such finding are
marked interrupted." A4.14.2: "Any path that labels a detected or detectable validity failure as interrupted or
inconclusive, or that lets a stopped cell's records go unscored, is a BLOCKER."

Code path: `score.score_run`, the block after `_freeze_problems` (score.py lines 698 to 711). It looks only at cells whose
`state.json` says `interrupted`, and attributes a finding to such a cell only when the finding text contains one of the
cell's call ids (`{i}:`, ` {i}:`, `{i} `) or one of its in-flight marker file names. Two cases follow.

(a) Cell scoped findings that name the cell, not a call, are never attributed. `worker_probe` records a probe
disclosure as `{'probe', 'cell', ...}` in `evidence/probe-disclosures.jsonl` and stops the cell as an "A4.14.1
isolation signal"; the scorer turns it into `a features probe of <cell>: credential material was redacted from its
output (A4.2)`. The features probe runs in `_guarded` before any call, so the cell has no call id and the line names
the cell id, which is a prefix of call ids, never matched by them. Transcript of the reproducing test (fake live mode):

```
STATE        interrupted
INTERRUPTED  ['codex-materials-cold-A']
INVALID      {}
ISOLATION    ['a features probe of codex-materials-cold-A: credential material was redacted from its output (A4.2)', ...]
report.md    - stopped cells invalid (A4.14.1): []
             - stopped cells interrupted, no finding: ['codex-materials-cold-A']
```

The same text matching misses every other finding the scorer writes with the cell id (`<cell>: no passing wave gate
record`, `<cell>: no features record`, `<cell>: the features record did not pass (A4.2)`) and the run level stops that
carry a `cell` field (`codex-stop.json`, `run-stop.json`).

(b) A crashed cell is stopped by `stop_cell` only through `crash_scan`, which runs when a later cell is admitted. When
the runner dies after recording an executed tool event and the run is scored before another admission (the last cell
of a wave, or a driver that scores right after the crash), the cell's state is `running`, the per cell block skips it,
and its detected leakage is never applied to it. Transcript:

```
STATE     running
INVALID   {}
LEAKAGE   ['codex-materials-cold-A.r1.b01.t0: tool event verdict executed (A4.3)']
```

The gate verdicts are `invalid` in both cases, because `gates._validity` reads the run wide lists. The defect is the
per cell outcome A4.14.1 prescribes: the report states that the stopped cell had no finding (a) or gives it no validity
at all (b), which A4.14.2 names a BLOCKER outright.

Tests: `test_rtc1_1_a_cell_stopped_by_its_probe_disclosure_is_invalid_not_interrupted`,
`test_rtc1_1_a_crashed_cell_scored_before_any_later_admission_gets_its_validity`.

Fix: attribute findings by structure, not by substring. Keep a `{cell: [findings]}` map while building the lists (each
attempt by its `cell`, each capture by its meta or attempt `cell`, each probe disclosure by its `cell`, each marker by
its directory, `codex-stop.json` and `run-stop.json` by their `cell`, the per cell live checks by `cid`). Treat as
stopped every cell whose state is neither `complete` nor `settled` and that has attempts, markers or a stop file (the
`crash_scan` predicate, read only), and mark it invalid when its map entry is non empty. The scorer must not write
`INTERRUPTED.json`; it only reads.

### RTC1.2 Token separation treats a missing login identity as a different login (A4.2, RT3.2)

RT3.2 was closed by `isolation.login_identity`, which hashes the access token claim `session_id` (or the same claim
inside `https://api.openai.com/auth`). When neither is present it returns `{}`, and `token_separation_problems`
compares nothing: `if my_login and their_login and my_login == their_login` (isolation.py line 832). A missing identity
is therefore treated as a different login, the opposite of the round 2 joint rule the RT3.2 fix cites ("an unexplained
credential representation is never treated as different"). The identity is still present in the id token (`sid`,
`auth_time`), which the check never reads.

Harm: a baseline copied from the owner's auth.json before the owner's next rotation (same login, older access token, a
refresh token the owner already spent) passes token separation whenever the access token lacks `session_id`. The first
worker refresh then replays a spent refresh token of the owner's own login, the reuse RT3.2 described, which a rotating
authorization server answers by revoking the login family, the owner's current tokens included. The claim layout is
chosen by the authorization server at each `codex login`, not by the pinned CLI, so the ledger's check of the current
tokens on this machine does not cover a later reseed.

Test: `test_rtc1_2_a_stale_copy_of_the_owner_login_passes_when_the_access_token_has_no_session_claim` (the control,
a separate login with its own `sid`, passes).

Fix: derive the login identity from every place it appears (access token `session_id`, id token `sid`, and
`auth_time` or `pwd_auth_time` together with the account id), compare on any shared component, and return a problem
when the owner auth.json exists and either side yields no identity at all. Keep the exact token hash comparison.

## Changes (A4.14.2: worst outcome is a stopped, interrupted or invalid cell, or none)

* **C1. An unsupervised child is resumed.** When `AssignProcessToJobObject` fails, `procs.Tree.start` records
  `supervised False` but `spawn` and `run_local` still call `tree.resume()`, so a real model call runs whose
  descendants cannot be established. The result is flagged (the call ends `unsettled`, uncertain, the cell invalid, the
  run stopped), but one evaluation call is spent for nothing. Refuse to resume: when `tree.supervised` is False, kill the
  suspended child and record it `not_launched` (`never_ran`).
* **C2. `CellRun.abandon` unlinks a reserved marker even when its `not_launched` row could not be appended** (both
  writes are under `contextlib.suppress(Exception)`). In live mode the ledger row from `reserve_group` still exposes the
  debit to the scorer; if that append failed too, the reservation leaves no trace. No call was launched, so no cost is
  lost, but keep the marker whenever the row append fails so the A4.14.1 stop records it.
* **C3. `Isolation.propagate` checks only that the worker auth.json parses and is not older.** A worker document
  without tokens and a newer `last_refresh` replaces the baseline. The 48 hour gate at the next reservation refuses
  the group, so no result is affected, and under the no restore rule the old refresh token is probably spent anyway;
  still, require `tokens.access_token` and `tokens.refresh_token` before replacing the baseline.
* **C4. Report wording.** `render_md` prints both "stopped cells interrupted, no finding" and "interrupted cells" from
  the same list; after the RTC1.1 fix keep one line.

## Checked and found sound

* Gate verdicts: every finding in `invalid_cells` comes from a run wide list that `gates._validity` reads, so no per
  cell defect turns a gate to `pass`; `_verdict` reports `invalid` before `inconclusive`.
* Captures of stopped cells are judged whatever their attempt rows say; a capture without an attempt line is an artifact
  problem; a marker without an attempt row is an accounting failure; probe markers are isolation problems.
* `after_group` propagates nothing when any member did not settle normally; `reconcile_generations` refuses on any
  authentication failure, any conflict and more than one changed worker; a deleted worker auth.json makes
  `propagate` raise.
* Nothing in the harness writes below `Path.home() / '.codex'`; the owner auth.json and sessions are read for hashes and
  quota readings only, and `env_selection_problems` refuses any environment value pointing into the owner configuration or
  the baseline.
