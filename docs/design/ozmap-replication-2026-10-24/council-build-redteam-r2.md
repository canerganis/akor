# Replication harness: red team round 2 (2026-10-24)

Reviewer: one fresh Opus subagent (claude-opus-5-5, high effort), logged in call-ledger.jsonl as `opus / red-team-r2 /
review` (Opus 19 of 40 after the entry). Target: `bench/ozmap_rep/` at commit c345c4b (council round 1 fixes), before
its freeze. Goal: make the harness produce invalid evidence that it does not flag. Method: code reading plus fakes and
temporary directories only. No real `codex` or `claude` was run (the `codex.exe` string table was read with `grep -a`,
never executed), no Codex or model call was made, the real baseline, run directory, experiment ledger, owner home and
session files were not touched, and the sealed reviewer ASTs were not read.

Verdict: do not freeze. Six blockers, each with a reproducing test in `bench/ozmap_rep/redteam/test_redteam_r2.py`
(6 tests, all fail on c345c4b; the round 1 red team tests still pass).

```
python -m pytest bench/ozmap_rep/redteam/test_redteam_r2.py -q      6 failed in 10.7 s (expected until fixed)
```

These tests make `python -m pytest bench/ozmap_rep -q` red on purpose until the fixes land.

## Blockers

### RT2.1 A tool execution captured before a runner death is hidden behind `interrupted` (A4.3, A4.11)

`CellRun.after_group` writes `D/captures/<call id>.stdout` and the parsed call record before it appends the attempt
line. A runner killed in that window (a runner subagent timeout, an exception in `_append`) leaves the capture. On
resume, `recover_inflight` records the call as `interrupted` with no event verdict, the batch is retried from the
reserve and the cell completes. The scorer skips `_rejudge` for every interrupted attempt and its capture check only
looks for captures with no attempt line at all, so the capture is never judged. A call that executed a tool, the
failure that invalidated the pilot, disappears from `leakage`; because leakage is global (C10), the other cells'
claims would stand.

```
codex-materials-cold-A.r1.b03.t0 executed `type ...\ops\oracle.py` (its capture holds the command_execution item
with exit_code 0) but the report flags nothing: leakage [], artifact problems [], cell state complete
```

Test: `test_rt2_1_execution_captured_before_the_runner_died_is_still_leakage`.

Fix. The scorer judges every capture in `D/captures`, interrupted attempts included, and puts any executed or
uncertain verdict into `leakage`. Recovery may also judge an orphan's capture when one exists and record its event
verdict on the interrupted row, so the runner's own stop logic sees it too.

### RT2.2 A superseded run directory gives back the nominal calls it used (A4.5, A4.1, RT1.5)

Build notes, reading 7, says the live calls of a superseded directory "stay in the experiment ledger and keep
counting against every allocation and cap". `CellRun.budget()` merges `D/attempts.jsonl` with the ledger and
deduplicates by call id alone. Call ids are deterministic (`<cell>.<batch>.t<try>`) and restart in every run
directory. As soon as the new directory records its own copy of a call id, the superseded call with that id stops
counting, and the allocation is granted again on the next invocation. Two stopped runs and a disposition are enough:

```
6 nominal live calls charged to sonnet/materials cold_A (nominal allocation 4) across the superseded and the new run
directory (2 + 4); exit codes 5, 0; D2 report: state complete, calls 4, accounting failures []
```

The same arithmetic lets repeated telemetry failures (each needs a new directory) exceed the telemetry cap of 4, and
the scorer of the new directory shows a clean complete cell: the selective rerun RT1.5 was meant to close.

Test: `test_rt2_2_a_superseded_run_directory_never_restores_used_nominal_calls`.

Fix. In live mode the budget counts the experiment ledger alone (every live charge is written there), deduplicated by
`(run_dir, call_id)`, never by call id; or call ids carry the run directory identity. The scorer reports the ledger
totals per allocation across all run directories and flags any allocation above nominal plus reserve.

### RT2.3 One abandoned launch group makes every later live dispatch refuse, for good (A4.1, A4.5)

`prepare_call` appends the live charge to the experiment ledger when a call is prepared. If a later call of the same
launch group fails its launch verification (an `AGENTS.md` appearing in an ancestor such as the user profile, a
baseline reseed in mid group), `abandon()` removes the earlier calls' markers and prompts but leaves their ledger rows,
and no attempt line is ever written for them. From then on `ledger_problems()` reports "live calls in the experiment
ledger are missing from this run directory" and every live cell of both backends exits 15:

```
after one abandoned launch group every live cell refuses: {'codex-materials-cold-A': 15, 'sonnet-materials-cold-A': 15}
```

The remaining cells are lost and the run can continue only under a new freeze, where RT2.2 applies.

Test: `test_rt2_3_an_abandoned_launch_group_never_bricks_the_live_run`.

Fix. `abandon()` appends an attempt line per abandoned call (outcome `not_launched`, kind as charged, no capture),
so the ledger and the attempts agree and the conservative charge stays counted; the scorer accepts `not_launched`
without a capture, counts it in the budget view and keeps it out of usage. Alternatively verify every call of a group
before charging any of them.

### RT2.4 A second turn in one exec stream drops the first turn's tokens (A4.7)

`run._turn_usage` (like the frozen adapter's `parse_events`) keeps only the last `turn.completed` usage, and nothing
counts turns: `classify_stream` skips every turn event. A two turn stream is judged `ok`, verdict `plain`, usage
`complete`, and is charged the second turn only. The scorer re-derives usage with the same function, so the omission
is invisible.

```
two turns judged 'ok', verdict 'plain', usage 'complete', charged 150 of 31050 tokens
```

The pinned CLI normally runs one turn per exec, but `goals` and other turn level features are enabled in the recorded
features list, and the cost of the guard is two lines.

Test: `test_rt2_4_a_stream_with_two_turns_never_drops_the_first_turns_tokens`.

Fix. More than one `turn.started` or `turn.completed` in a stream makes the call uncertain (A4.3) and its usage
incomplete, in `judge_codex` and therefore in `_rejudge`.

### RT2.5 The RT1.6 interim freshness gate reads a file mtime, not a reading (A4.12)

The interim fix lets a live Codex cell launch only when the owner reading is newer than the end of the last live Codex
call. `quota.codex_reading_time` returns the session file's mtime. Any later write to that file without a new
`rate_limits` event (a resumed owner session appending a user message, `touch`) passes the gate while the newest
reading is from before the replication's calls:

```
the only rate limit reading (79%) is two hours older than the last live Codex call, yet the freshness gate passes on
the file mtime: {'ok': True, 'percent': 79.0, 'reason': None}
```

Test: `test_rt2_5_the_codex_quota_freshness_gate_needs_a_new_reading_not_a_new_mtime`.

Fix. Use the `timestamp` of the event that holds the last `rate_limits` (a missing or unparseable timestamp is not
fresh). P3 still has to be ruled; this only makes the interim gate mean what build-notes says.

### RT2.6 A baseline that shares the owner's refresh token is used without a check (A4.2)

A4.2 requires a baseline that "shares no refresh token with the owner's home" and forbids seeding it by copying the
owner's `auth.json`. Nothing checks it. A baseline seeded with a copy of `~/.codex/auth.json` passes the wave gate,
the inventory, telemetry and every launch check, and its refresh token then goes to up to four concurrent workers. The
first worker refresh rotates the token the owner's Codex app also holds, and the owner's login fails with "refresh
token was already used", the exact message in the pinned string table.

```
a baseline holding the owner refresh token (copied ~/.codex/auth.json) was used by worker calls
['telemetry.r2.b00.t0', 'codex-materials-cold-A.r1.b00.t0', ...]; exit codes {'telemetry': 0, 'cell': 0}
```

Test: `test_rt2_6_a_baseline_sharing_the_owner_refresh_token_never_reaches_a_worker`.

Fix. At the wave gate and in telemetry, compare the SHA256 of the baseline refresh token (and of the access token)
with those of the owner's `auth.json` (`Path.home()/.codex/auth.json`, and `CODEX_HOME` of the runner if set); equal
hashes refuse with exit 11 and the reseeding command. Log hashes only, never token text. Record the baseline's own
hashes at the first dispatch so a later swap is visible.

## Observations (not blocking, recommended before the freeze)

1. The exec `--json` stream of 0.160.0 maps only eight item kinds (`agent_message`, `reasoning`,
   `command_execution`, `file_change`, `mcp_tool_call`, `collab_tool_call`, `web_search`, `todo_list`, from the
   string table next to `exec\src\lib.rs`), while the core item list also has `dynamic_tool_call`, `image_view`,
   `image_generation`, `context_compaction`, `sub_agent_activity` and others. A tool with no exec mapping would leave
   no event, and the harness has no independent tripwire. Round 1 observation 4 (input tokens far above the prompt's
   own count make the call uncertain) is still the cheapest independent channel.
2. Sonnet: `claude_map_adapter.tool_use` treats a missing `num_turns` or `permission_denials` as plain, and reads
   `OZ_MODEL` from the runner's own environment: with `OZ_MODEL=''` a second model in `modelUsage` is never flagged.
   Both were confirmed with `run.judge_sonnet`. The harness could require `num_turns == 1` and pin the model name
   itself.
3. `jsonl()` silently skips unparseable lines in `attempts.jsonl`, the ledger and every evidence file. A torn append
   would drop attempts from the budget and the scorer; captures and the ledger check catch most cases, but the
   scorer should report any unparseable evidence line.
4. `_cell_chain` checks warm C rule answers against every rule accepted at bootstrap, not only those adopted in cold
   C. The runner filters correctly, so this matters only for a tampered result, but the check is cheap.
5. Telemetry and features probes are charged and reconciled, but a probe that refreshes is reconciled with
   `auth_failure: False` always; an authentication failure printed by `login status` is never treated as one.

## Attacks that held

1. Round 1 findings RT1.1 to RT1.5: fake mode cannot enter the live directory, a second runner exits 16 before any
   state is read, execution evidence is sticky, the pinned refresh failure texts stop Codex, a fresh directory without
   a disposition is refused.
2. Learner prompts: admission texts are checked before launch and by the scorer; the bootstrap prompt carries
   contracts only.
3. Rule origin answers: every accepted rule answer is compared with gold in the runner (safety kill file, exit 17 for
   every later dispatch) and again in the scorer; quarantine and audit fallback never release an unaudited answer as
   model origin.
4. Owner home: no code path writes `~/.codex`; Codex children get the worker home as `CODEX_HOME`, `HOME` and
   `USERPROFILE`; fake mode refuses a signed token or the owner seeded baseline.
5. Sealed ASTs: read only by `score.convergence`, which requires a report with all sixteen cells complete.
6. Telemetry: a failed telemetry attempt blocks evaluation in that directory; the certificate needs a plain reply,
   an empty home exec failure and clean listings.
