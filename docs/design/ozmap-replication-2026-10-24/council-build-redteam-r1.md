# Replication harness: red team round 1 (2026-10-24)

Reviewer: one fresh Opus subagent (claude-opus-5-5, high effort), logged in call-ledger.jsonl as `opus / red-team /
review`. Target: `bench/ozmap_rep/` at commit 4839d99, before its freeze. Goal: make the harness produce invalid
evidence that it does not flag. Method: code reading plus fakes and temporary directories only. No real `codex` or
`claude` was run (the pinned `codex.exe` string table was read with `grep -a`, never executed), no Codex or model call
was made, the real baseline, run directory and session files were not touched, and the sealed reviewer ASTs were not
read.

Verdict: do not freeze. Six blockers. RT1.1 to RT1.5 each have a reproducing test in
`bench/ozmap_rep/redteam/test_redteam_r1.py` (16 tests, all fail on 4839d99). RT1.6 is backed by a command transcript.

```
python -m pytest bench/ozmap_rep/redteam -q      16 failed in 16.5 s (expected until fixed)
```

Note: these tests make `python -m pytest bench/ozmap_rep -q` red on purpose until the fixes land.

## Blockers

### RT1.1 Fake mode lands in the live run directory and scores as evidence (A4.1, A4.2, A4.10)

`plan --list-cells` gives every runner the command `python -m bench.ozmap_rep.run cell <id>`. That command has no
`--mode`, the default mode is `fake`, and the default run directory is the live one (`~/.ozmap_rep/runs/replication`)
in both modes. A runner that copies the plan command therefore runs the fake model inside the live run directory: it
appends fake attempts to the live `attempts.jsonl`, writes `DONE.json` (so the live cell later refuses to run, exit 3),
and writes the gold table of every job to `D/fake/answers.json` next to the live worker homes. Fake mode also reads the
real baseline by default and copies its `auth.json` into the worker homes of whatever run directory it is given.

The scorer never looks at the attempt `mode`. A fake answered cell scores as clean evidence:

```
state complete, evidence complete, usage complete, correct 256/256, isolation passed, problems []
```

Tests: `test_rt1_1_the_plan_command_never_runs_fake_mode_in_the_live_run_dir_with_the_real_baseline`,
`test_rt1_1_the_scorer_never_accepts_fake_calls_as_evidence`.

Fix. (1) `cell` requires an explicit `--mode`; the plan command carries `--mode live`. (2) Fake mode refuses the live
run directory and any baseline other than a synthetic one inside D. (3) The scorer adds a validity problem for any
attempt whose mode is not `live`, any spawn with `external: false`, and any `D/fake/` directory, and the report states
the mode. The dry report keeps its own fake label.

### RT1.2 Two runners of one cell duplicate calls, invent interruptions and double count tokens, unflagged (A4.1, A4.5, A4.7)

Nothing stops a second runner of the same cell while the first is alive (for example a resume runner started after a
runner subagent timed out while its python child kept running). Sonnet cells take no lock at all. Codex cells take the
`codex-cells` lock only after `recover_inflight`, the budget build, `Executables` (which rewrites `D/fake/answers.json`)
and `record_features` (which rebuilds worker home 0 and `work/slot-0` without the slot lock, under a call that may be
in flight there, so a refreshed `auth.json` in that home would be overwritten and lost).

Sonnet, two runners of `sonnet-materials-cold-A`: every batch is sent twice and the scorer reports the doubled cell
as clean.

```
8 physical calls for an allocation of 4 (+2 reserve); call ids r1.b00.t0 to r1.b03.t0 each recorded twice
cell: state complete, evidence complete, usage complete, tokens 30310 (2 x 15155), physical_calls 8, correct 256
validity: isolation passed, leakage [], accounting_failures [], interrupted []; budget sonnet nominal 8
```

In other runs of the same test the runners crash on each other's files (`PermissionError` on the shared
`inflight/<call id>.json.tmp`), because both use the same call ids.

Codex, second runner of `codex-materials-cold-A` started while the first has four calls in flight: all four live
calls become phantom `interrupted` attempts carrying the same call ids as the real ones, the first runner's in-flight
markers are deleted, the allocation is charged twice and the cell's usage turns incomplete.

Tests: `test_rt1_2_two_runners_of_one_sonnet_cell_never_send_a_batch_twice`,
`test_rt1_2_a_second_codex_runner_never_declares_a_live_call_interrupted`.

Fix. (1) The first action of `CellRun.run` is a non blocking exclusive per cell lock (`D/locks/cell-<id>.lock`); a
second runner exits at once with its own exit code, before the DONE check, `recover_inflight`, the budget, the fakes and
`record_features`. (2) `record_features` and `telemetry` take the `codex-cells` lock and the slot lock of the slot they
prepare. (3) The scorer adds an accounting failure for a repeated call id, more than one terminal attempt per batch, or
an allocation charged above nominal plus reserve.

### RT1.3 Execution evidence can be erased by a later event of the same item (A4.3)

`classify_stream` keeps only the last event per tool item id. An item that completed with `exit_code` 0 and
`aggregated_output` (an external read) and is followed by an `item.updated` of the same id with status `declined` is
classified `refused`: `external_read` false, `efficiency_invalid` false. The pinned CLI is not expected to emit that
order, but this classifier is the only defence against the failure that invalidated the pilot, and the fix is one
line.

Test: `test_rt1_3_execution_evidence_is_never_erased_by_a_later_event_of_the_same_item`.

Fix. Aggregate per item over every event: executed if any event shows execution evidence; a status that goes back
after execution evidence is at least uncertain.

### RT1.4 The pinned CLI's own authentication failures are retried, not stopped (A4.2)

`AUTH_FAILURE_RE` matches none of the refresh failure messages in the pinned `codex.exe` string table, for example
"Your access token could not be refreshed because your refresh token was already used. Please log out and sign in
again." (five messages, all ending in "sign in again"; the binary does not contain `refresh_token_reused`, `401
Unauthorized` or `Please log in` at all). `judge_codex` returns `infrastructure_failure` for each, the batch is retried
from the reserve with the same dead lineage, and Codex evaluation is not stopped, against A4.2 ("An authentication
failure without a changed worker also stops Codex evaluation").

Test: `test_rt1_4_a_refresh_failure_of_the_pinned_cli_is_an_authentication_failure` (5 messages, on the stream and on
stderr: 10 cases).

Fix. Match the pinned CLI's texts (`could not be refreshed`, `sign in again`, `Not logged in`, `401`, `invalid_grant`,
`token_expired`), and run the authentication check before the tool event verdict as well, so that an authentication
error surfaced as an error item still stops Codex while the call stays uncertain under A4.3.

### RT1.5 A fresh run directory is a fresh budget (A4.1, A4.3, A4.5)

Every cap and allocation is counted from `D/attempts.jsonl` of whatever `--run-dir` the runner passes. The same live
cell run into a second directory gets a full new allocation, and the scorer of either directory shows a complete
clean cell. That is a selective rerun which erases the first attempt from the scored evidence. Shown in live mode (real
harness code; freeze check passed, executables replaced by the harness' own fakes, any other launch refused):

```
8 live physical calls for sonnet-materials-cold-A across two run directories (4 + 4); allocation 4 + 2 reserve
```

Test: `test_rt1_5_a_second_live_run_directory_never_grants_a_fresh_allocation`.

Fix. One canonical live run directory, fixed in `freeze.json`, or an append only live ledger outside every run
directory (for example `~/.ozmap_rep/live-calls.jsonl`, written under a lock at every live charge and counted in full by
`Budget`). Live cells refuse any other run directory; the scorer flags ledger calls that are missing from the scored
run directory.

### RT1.6 The Codex stop gate cannot see the replication's own Codex use (A4.12)

The gate reads the newest file under `~/.codex/sessions`. Worker calls run with `CODEX_HOME` set to the worker home and
with `--ephemeral`, so no replication call ever writes a session file there, and the worker home is wiped after each
call. The `exec --json` stream carries no rate limits either (archived 0.160.0 stream of live run 1, telemetry-1: only
`turn.started`, nine `item.completed`, `turn.completed`). The reading therefore only moves when the owner or the driver
makes a Codex call in the owner's home. Up to 62 replication calls of `gpt-6.1-sol` at high effort run against a
frozen reading, and the 80% stop can be passed without the harness noticing.

```
$ python -c "...codex_argv, child_env, Options.sessions_dir..."
ephemeral in frozen argv: True
child CODEX_HOME: D\homes\worker-0
gate reads: C:\Users\can02\.codex\sessions
$ grep -o 'turn\.[a-z]*\|rate_limits\|used_percent\|item\.[a-z]*' .../live-6a518ece47ab/telemetry/ws/do/telemetry-1/captures/1.envelope | sort | uniq -c
      9 item.completed
      1 turn.completed
      1 turn.started
```

Fix (needs a prospective signed revision of A4.2, since `--ephemeral` is a frozen argument). Drop `--ephemeral` for
workers; in `Isolation.finish`, before cleanup, read the last `rate_limits.primary.used_percent` from the worker's
`sessions/*/*/*/*.jsonl` (log the number only) and gate the next launch group on the larger of that reading and the
owner reading. The worker home is rebuilt before every call, so the session file never reaches a later call. If the
council keeps `--ephemeral`, the alternative is a headroom rule: a Codex cell launches only when the owner reading plus
a stated worst case increase for that cell stays below 80, with the increase measured on the telemetry call.

## Observations (not blocking, recommended before the freeze)

1. `judge_codex` tests `timed_out` before the event verdict. A call that executed a tool and then timed out is an
   infrastructure failure and its batch is retried. The scorer still flags the attempt row as leakage, so nothing is
   hidden, but judging the events first is cleaner.
2. A runner killed after writing `captures/` and `calls/` but before appending the attempt line leaves a marker that
   resume records as `interrupted` with no events. Any execution evidence in that capture is never judged; the cell
   becomes inconclusive, not invalid. The scorer should re-judge every file in `D/captures` against the attempts.
3. The classifier and the frozen adapter skip stdout lines that do not start with `{`. A non empty non JSON line should
   be uncertain.
4. `unified_exec` stays enabled and the read only sandbox can read the repository, `~/.codex` and the baseline. The
   defence is detection only. A usage tripwire would add an independent channel: each tool round trip resends the
   context, so a call whose `input_tokens` exceed the prompt's own token count by a set margin should be uncertain.
   If a tool call ever prints a token, `D/captures/<id>.stdout` holds token text: an executed verdict should quarantine
   its capture.
5. `record_features` and the telemetry `codex login status` probes load authentication but only run `finish`, never the
   reconciliation. If either refreshes, the new token is discarded and the baseline lineage dies.
6. The wave gate bounds only `exp`. If the pinned CLI refreshes on `last_refresh` age while `exp` is still 48 h away,
   all four concurrent workers refresh together (stop, plus reuse of one refresh token four times). The telemetry
   record should state the refresh trigger, or the gate should also bound `last_refresh` age.
7. `secret_auth_storage` is enabled. The telemetry check shows where authentication is read from, not where a refresh
   is written. Worth one line in the telemetry evidence.
8. `telemetry` makes a live Codex call without `verify_freeze`.
9. `score.convergence` requires only that `report.json` exists, which any partial scoring creates. It should require
   all 16 cells complete.
10. An inconclusive audit still releases that wave's rule answers (build notes, interpretation 7). The scorer's safety
    kill catches wrong ones, but the council should confirm this reading of A4.11.
11. The Sonnet route keeps the owner's HOME and APPDATA and relies on `--setting-sources ''` to exclude CLAUDE.md,
    memories, plugins and skills (A4.9 keeps the pilot flags). Its input token count on the first live call is the only
    check.

## Attacks that held

1. Admission texts in learner prompts: checked before every launch and again by the scorer; job and admission streams
   use different specimen prefixes; the `Expectation:` paragraphs are stripped; `classification.json` holds hashes only.
2. Launch verification: strict argv check and hash, environment allowlist (no API keys, no owner `CODEX_HOME`), worker
   home holding only `auth.json`, empty working directory equal to `-C`, instruction files searched in every ancestor.
3. Usage decoding: a missing counter is never zero, `cached <= input` and `reasoning <= output` are enforced, positive
   cached input without the certificate is unverified, replay fixtures pass, telemetry tokens stay out of the cells.
4. Budget within one run directory and one runner: nominal beyond the allocation raises, the reserve only takes the two
   listed reasons, and the global caps equal the sums of the allocations.
5. Authentication reconciliation: more than one changed worker stops Codex, propagation refuses an older
   `last_refresh`, a deleted worker `auth.json` stops Codex, and no code path writes `~/.codex`.
6. Refused, executed and uncertain calls are terminal; only infrastructure failures retry, and earlier attempt rows are
   never removed, so a retry does not erase a leakage flag.
7. Sealed ASTs are read only by `score.convergence`, only when the driver passes their directory.
