# Deadlock round 2: Fable's proposed solutions (2026-10-24)

Author: Fable (claude-fable-5-1), co-solver for the council build deadlock, logged in call-ledger.jsonl as one Fable
call (Fable 2 of 4 after this entry). Target: `bench/ozmap_rep/` at commit 5fc191a (red team round 2 committed, council
round 1 fixes in place). Inputs: amendment-4.md, amendment-4-13-caps.md, owner-decisions.md, build-notes.md,
council-build-astra-r2.md, council-build-opus-r2.md, council-build-redteam-r2.md, the round 1 reviews, the harness
source and the red team round 2 tests. The sealed reviewer ASTs were not read. No model call and no Codex model call
was made. The only CLI commands run were local `codex login status` and `codex features list` invocations against an
empty temporary CODEX_HOME in the scratchpad (no auth.json, no network request possible, nothing written into the
owner home) plus `grep -a` over the pinned `codex.exe` string table. The owner home, the baseline, the live run
directory and the experiment ledger were not touched.

Format: one merged solution per cluster of blockers, each with the code change or predicate, the fail closed
condition, the regression tests, and where a ruling is needed the replacement text ready to sign. Section 1 lists the
new local facts the solutions rest on, because several of them change what the council thought was possible.

## 1. New local evidence (no model request)

| fact | how established | consequence |
|---|---|---|
| F1. `-c cli_auth_credentials_store="file"` is accepted by codex-cli 0.160.0. A bogus value is refused with `unknown variant, expected one of file, keyring, auto, ephemeral`. | `codex -c cli_auth_credentials_store="file" login status` with an empty CODEX_HOME: exit 0, "Not logged in" | The CLI has a pinned configuration knob that selects the credential source. `file` means auth.json under CODEX_HOME and nothing else. This is the "pinned implementation evidence" item 1 asks for, carried on the hash frozen argv. |
| F2. `--disable secret_auth_storage` is accepted and `features list` then shows `secret_auth_storage stable false`. | local `features list` | B4 (b) resolves to "supported": add it to the frozen disable list. |
| F3. `--enable skip_host_skill_discovery` (and `-c features.skip_host_skill_discovery=true`) is accepted and `features list` shows it `true`. | local `features list` | A CLI switch exists for P5 (B6 named it). Whether it suppresses the `skills/.system/*` write is only observable with an exec; see S11. |
| F4. `login status` and `features list` with an empty home write nothing into CODEX_HOME. | listing of the probe home after both commands: empty | B1 (b) as written does not work: `record_features` yields no startup inventory. The startup inventory comes from an exec. The telemetry's no auth exec probe (already step 3 of the telemetry) is the local preflight, see S11 and S12. |
| F5. The exec probe home of the build (scratchpad `cliprobe/home`) holds `skills/.system/.codex-system-skills.marker`, `skills/.system/<name>/SKILL.md`, `agents/openai.yaml`, `references/*.md`, `scripts/*.py`, plus `goals_1.sqlite`, `logs_2.sqlite`, `memories_1.sqlite`, `queue_1.sqlite` (with shm and wal) and `installation_id`. | listing, names only | The startup inventory is enumerable and hashable; a manifest with exact names and hashes is feasible. |
| F6. The exact Code Mode notice is `Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.` | archived probe stream in the scratchpad | P4 can pin the complete message, exact match, not a prefix. |
| F7. `--ephemeral` means exactly "Run without persisting session files to disk" (`codex exec --help`). | help text | Dropping it changes one thing: a rollout file appears under `CODEX_HOME/sessions/`. The worker home is rebuilt before and emptied after every call, so the rollout never reaches a later call. |
| F8. A 0.160.0 rollout's `session_meta` carries `creator_account_id`, `cli_version`, `base_instructions.{text, provenance{type, model}}`; its `event_msg token_count` events carry `rate_limits.primary.{used_percent, window_minutes, resets_at}` and `limit_id`, each event with its own `timestamp`. The owner's primary limit has `window_minutes 10080` (a weekly window). | key inventory of the owner's own newest rollouts (keys and quota numbers only) | A rollout is an attributable, timestamped quota observation and a record of the base instruction provenance. This is the P3 source that needs no extra model call, and part of the P5 evidence. |
| F9. The string table of the pinned binary names `cli_auth_credentials_store`, `keyring_backend`, `file_storage`, `secret_auth_storage`, `skip_host_skill_discovery`, `Reconnecting... `, `Falling back from WebSockets to HTTPS transport.` and the Code Mode format. | `grep -a` | The texts and switches used below exist in this exact build. |

## 2. Merged solutions

### S1. Authentication source: items 1, B4, RT2.6 (A4.2)

Closes 1, B4, RT2.6.

Code.

1. `config.FROZEN_AUTH_ARGS = ['-c', 'cli_auth_credentials_store="file"']`, appended to the canonical argv right after
   the effort argument, and `secret_auth_storage` added to `DISABLE_FEATURES`. `isolation.argv_check` accepts exactly
   this `-c` pair (like `PROJECT_DOC_ARG`) and reports it missing as a problem. `verify_launch` fails when the pair is
   absent. Fail closed: a launch without `cli_auth_credentials_store="file"` is refused before any charge.
2. `TelemetryRun.arm` adds `worker_path_login_status`: for each slot k in 0..3, with the worker home directory present
   but emptied (no auth.json) and `CODEX_HOME` at `homes/worker-<k>`, run `login status` (local, no model request) and
   record the state. Done once before the exec probe and once after the plain call, eight results. `isolation.
   telemetry_certificate` requires all eight to be `not_logged_in`. A CLI that reads a per path keyring credential
   would answer `logged_in` for a worker path with an emptied home and fail certification.
3. `telemetry_certificate` also requires `call.argv_sha256 == frozen argv_sha256` and `call.auth_source == {'store':
   'file', 'codex_home': <worker path>, 'auth_sha256': <prepared hash>}` recorded by `prepare_call` from the argv and
   the prepared home. Metadata only, no token text. Together with the empty home 401 probe this binds the certificate
   to the execution route's configured credential source, not to an inference from two observations.
4. RT2.6 token identity. `isolation.token_hashes(auth_path)` returns `{access: sha256, refresh: sha256, id: sha256}`
   of the token strings (never the strings). `wave_gate` and `TelemetryRun.arm` compare the baseline's hashes with
   those of `Path.home()/.codex/auth.json` and of `os.environ.get('CODEX_HOME')/auth.json` when set. Any equal hash
   refuses with exit 11 and the reseed command `CODEX_HOME=~/.ozmap_rep/baseline codex login`. `bind_identity`
   records the baseline token hashes at first dispatch in `experiment.json`; `reconcile` and `recover_inflight`
   append the new hashes on every propagation or observed reseed to `evidence/auth-lineage.jsonl`, so a later swap is
   visible. The scorer reports a baseline hash change without a lineage row as an isolation problem.

Tests. `test_s1_keyring_style_auth_for_a_worker_path_does_not_certify` (fake CLI answers `logged_in` for an emptied
`homes/worker-2`; certificate fails, no charged call after the probe). `test_s1_argv_without_file_store_is_refused`.
`test_s1_owner_shared_refresh_token_is_refused_at_the_wave_gate_and_in_telemetry` (the red team's RT2.6 test passes;
exit 11 with the reseed command; no attempt row). `test_s1_lineage_rows_follow_every_propagation`.

No ruling needed: A4.2 already asks for every available disable option and for telemetry that establishes the
credential source. The argv change happens before the freeze.

### S2. Recovery, raw streams and captured executions: items 3, B3, RT2.1 (A4.2, A4.3, A4.11)

Closes 3, B3, RT2.1.

Code.

1. Raw streams to files. `spawn` opens `D/homes/raw-<slot>/<call id>.stdout` and `.stderr` for writing and passes the
   handles to `Popen`; stdin stays a pipe. `D/homes/` already falls under the token rule (nothing outside the baseline
   and the worker homes may hold token text; `redact` runs before anything leaves it). `after_group` reads the two raw
   files, redacts, writes `D/captures/<id>.*`, appends the attempt, then deletes the raw files. A dead runner no longer
   kills the child through a closed pipe and leaves a complete stream.
2. Phase ordering in `after_group` for each call: write `cells/<cell>/calls/<id>.json`, write both captures, then
   append the attempt row, then mark the marker `recorded`. Recovery relies on this order.
3. `recover_inflight` reconciles durable evidence before classifying an orphan, in this order: (a) if `attempts.jsonl`
   has the row, nothing to do; (b) else if both captures exist and hash to the stdout and stderr of the raw files when
   those still exist, or the raw files are gone, judge the capture with `judge_codex` or `judge_sonnet` (exit code
   unknown, `timed_out False`) and append the attempt row with that outcome, `recovered_from: 'capture'`, usage decoded
   as in `after_group`, `elapsed_s None`, `ended_at` the capture mtime; (c) else if the raw files exist and the child
   pid is not alive, redact them into captures and proceed as (b) with `recovered_from: 'raw_stream'`; (d) only when
   no stream exists is the row `interrupted`, and then `events.verdict` is `uncertain` with reason `no capture`, so the
   scorer lists it under leakage (strict reading pending P2, see S14). A terminal outcome recovered under (b) or (c)
   is read back by `run_batches` and never resent.
4. Process identity. `_mark_spawned` failures are no longer suppressed: `execute` writes the marker phase `spawning`
   before `Popen`; after `Popen`, if the marker with the pid cannot be written, it kills the process tree, waits for
   termination (`pid_alive` false within 60 s), records `outcome 'spawn_unrecorded'` and calls `codex_stop`. A spawn
   or `communicate` exception also kills the tree and establishes termination; if termination cannot be established
   the marker stays, `codex_stop` is written and the call is neither retried nor recorded as ended. A marker in phase
   `spawning` without a pid is ambiguous: `recover_inflight` stops Codex (the child may have started), whatever the
   home shows. "Never prepared" is only a marker in phase `prepared` whose worker home does not exist.
5. Scorer. `score_run` judges every capture in `D/captures`, including those of interrupted or recovered attempts, and
   puts any `executed` or `uncertain` verdict into `leakage`; `_rejudge` runs for recovered rows (exit code not
   compared when the row says unknown).

Tests. `test_s2_crash_after_capture_before_attempt_row_recovers_ok_refused_and_executed_without_resend` (three
variants; the batch is not resent; the executed one lands in leakage: this subsumes RT2.1). `test_s2_runner_death_mid_
stream_leaves_a_complete_raw_file_that_recovery_judges`. `test_s2_orphan_without_any_stream_is_uncertain_no_capture`.
`test_s2_pid_journal_failure_with_a_live_child_stops_codex_and_keeps_the_home`. `test_s2_communicate_exception_with_a_
live_child_is_not_retryable`. `test_s2_spawning_marker_without_pid_is_ambiguous`.

Build notes: live cells and telemetry are launched detached (`run_in_background`), never in a foreground shell whose
limit is below `CALL_TIMEOUT_S`.

### S3. Probe authentication and features inventory: item 5 (A4.2)

Closes 5 and Opus C3.

Code. `worker_probe` passes `auth_failure = auth_failure_detected(out, err) or login_state(out + err) == 'unknown'`
(for the login probe) to `reconcile`, so a probe reporting authentication failure stops Codex and the baseline is kept.
`record_features` requires exit code 0, at least one parsed row, every name in `DISABLE_FEATURES` present in the
output, and `enabled_tool_features == ['unified_exec']` (the frozen expectation from `cli-flags.json`), else it raises
`Stop(EXIT_FREEZE)` before any charged call and writes the record with `ok: false`. `score_run` requires a features
record with `ok: true` per Codex cell, not mere existence.

Tests. `test_s3_features_probe_auth_failure_with_a_changed_worker_leaves_the_baseline_and_stops_codex`.
`test_s3_failed_or_empty_features_response_blocks_launch`. `test_s3_unexpected_enabled_tool_feature_blocks_launch`.

### S4. Credential redaction: item 6 (A4.2)

Closes 6 and Opus C5.

Code. `prepare_call` stores `c['secrets'] = redact.secrets_from_auth(prepared home auth.json)` in memory (the strings
of the prepared document, never persisted). `after_group` redacts with the union of `c['secrets']`, the worker's
auth.json after the call (read before `finish` removes anything) and the baseline now; redaction happens before
`finish` and before `reconcile`, as today, but no longer depends on files that a reseed or propagation may have
replaced. `worker_probe` captures the prepared secrets the same way before running the command. `redact.merge` keeps
per channel records: `{'stdout': r1, 'stderr': r2, 'redactions': n, 'kinds': [...]}` with each channel's
`original_sha256`; the scorer accepts this shape and requires an `original_sha256` per redacted channel. Sonnet
captures go through `redact` with the generic patterns (C5).

Tests. `test_s4_prepared_opaque_refresh_token_is_redacted_after_worker_refresh_and_baseline_reseed` (child echoes the
prepared refresh token, worker refreshes, baseline reseeded before capture processing; no artifact holds the token,
the per channel original hash is kept). `test_s4_probe_disclosure_is_redacted_with_the_prepared_secrets`.

### S5. Executable identity at every dispatch boundary: item 7 (A4.2)

Closes 7.

Code. `freeze_record` writes an explicit companion manifest per backend: for the native `codex.exe`, the resolved
path and sha256 of `codex.exe`, `codex-code-mode-host.exe` (same directory), `../codex-resources/codex-command-runner.
exe`, and every `.dll` beside the executable, each named explicitly. `executable_identity(exe, manifest)` hashes
exactly the manifest's paths and returns `unreadable` for any that cannot be read. For a wrapper (a `.cmd`, `.ps1` or
shell shim, or a symlink), the identity includes the resolved target (`Path.resolve()`, shim parsed for its target
line) and the target's own manifest; a shim that cannot be parsed fails closed. `Executables.verify` is called in
`prepare_call` for every call and again inside `execute` immediately before `Popen` (hash of the executable and the
manifest, compared with the frozen identity); a mismatch there does not spawn, records `outcome 'not_launched'` with
the reason, and raises `Stop(EXIT_FREEZE)` for the group. Build notes document the pinned companion manifest and the
fail closed rule for an uninspectable manifest.

Tests. `test_s5_executable_changed_after_group_verification_before_a_later_spawn_is_refused`.
`test_s5_wrapper_target_changed_in_a_subdirectory_is_refused`. `test_s5_unreadable_manifest_member_fails_closed`.

### S6. Physical call identity, ledger timing and replacement directories: items 9, RT2.2, B2, RT2.3 (A4.1, A4.5)

Closes 9, RT2.2, B2, RT2.3.

Code.

1. Globally unique physical identity. `bind_identity` assigns `run_id = sha256(resolved run_dir + freeze sha256)[:12]`
   stored in `experiment.json`; call ids become `<run_id>.<cell>.<batch>.t<try>`. Markers, attempts, captures, prompts,
   launch evidence and ledger rows all carry the run id inside the call id, so a replacement directory can never
   collide with a superseded one.
2. Live budget from the ledger alone. In live mode `CellRun.budget` counts the experiment ledger only, deduplicated by
   `(run_dir, call_id)`; `attempts.jsonl` is used for state, never for the live charge count. The scorer reports
   ledger totals per allocation across all run directories and flags any allocation above nominal plus reserve and
   any telemetry count above 4, whatever directory the calls came from.
3. One experiment lock beside the ledger. `exclusive(config.LIVE_LEDGER_DEFAULT.parent / 'experiment.lock')` is taken
   by every live runner (cells, telemetry, features) in addition to the per cell lock, so competing old and new
   runners cannot reserve independently.
4. Ledger rows after the group is prepared (B2 preferred option). `prepare_call` no longer appends to the ledger.
   `run_batches` appends one ledger row per member after every member of the group is prepared and immediately before
   the threads start, under the experiment lock. `abandon` therefore never leaves a ledger row behind. A crash between
   the ledger append and the attempt rows leaves markers, which recovery turns into attempts (S2), so ledger and
   attempts reconcile. As a second line, `abandon` appends an attempt row `outcome 'not_launched'`, `kind` as charged,
   no capture, for any member whose ledger row already exists (defensive; should not happen), and the scorer accepts
   `not_launched` without a capture and keeps it out of usage.
5. Replacement directories carry disposition. The disposition file named by `freeze --disposition` must list the
   superseded run directories and, per cell, one of `carry` (terminal outcomes are imported read only) or `void`
   (with a reason signed by both signatories). `freeze_record` hashes the disposition into `freeze.json`. In the new
   directory, `_preflight` refuses a cell whose superseded disposition is `carry` and which has `DONE.json`,
   `SETTLED.json` or any terminal batch outcome in a superseded directory (exit 3 or 5; nothing resent), and
   `score_run` loads every superseded directory's attempts, `codex-stop.json`, `safety-kill.json` and captures into
   the validity section (leakage, accounting, isolation) of the new report. Prior invalidating evidence is never
   omitted by changing directories.

Tests. `test_s6_migration_after_telemetry_failure_keeps_every_old_and_new_call_counted` (subsumes RT2.2).
`test_s6_repeating_a_terminal_batch_through_a_replacement_directory_is_refused`. `test_s6_competing_old_and_new_
runners_cannot_reserve_independently`. `test_s6_abandoned_group_leaves_no_ledger_row_and_the_next_cell_passes_ledger_
problems` (subsumes RT2.3). `test_s6_superseded_leakage_reaches_the_new_report`.

### S7. Scorer reconstruction: item 10 (A4.1, A4.7, A4.8)

Closes 10.

Code. `_rejudge` recomputes from the capture and the frozen predicates: `usage.decode_codex_checked` with
`cache_certified_for_route()` evaluated by the scorer itself, `usage.reasoning_inclusion` with the pinned tokenizer
(the scorer refuses to verify a live run when the tokenizer is unavailable, like the runner), the `cache_write`
rule, `usage.additive_tokens`, `charged_tokens`, `usage_status`, `reasoning_issue` and `cache_certified`, and
compares every field with the attempt row; any difference is an artifact problem. Bootstrap: `interpret` stores
`raw_proposal_b64` (the exact bytes of each proposal as cut from the reply) in the call record; `_rejudge` re-parses the
capture, compares the proposal bytes and `ast_b64` byte for byte, and `_cell_chain` reproduces the admission record
from the capture derived bytes, not from `result.json`. Rule answer eligibility: `run_BC` writes `cells/<cell>/audits.
jsonl` (op, audited job, audit call id, disposition, delivered at); `_cell_chain` checks that every rule answer's
operation had no quarantine or inconclusive audit recorded before that answer was delivered, and rejudges each audit
disposition from the audit call's capture. Launch identity: for every live attempt `_evidence_ok` compares
`evidence/launch/<id>.json` `exe_sha256`, `argv_sha256` and the companion manifest with `D/freeze.json`.

Tests. One test per alteration, each must withhold every claim without touching the capture:
`test_s7_altered_charged_tokens`, `_usage_status`, `_additive_tokens`, `_reasoning_issue`, `_cache_certified`,
`_proposal_to_another_admissible_ast`, `_launch_identity`, `_audit_disposition`.

### S8. Timing windows: item 14 (A4.10, A4.11)

Closes 14.

Code. `_run_locked` appends an `open` row to `cells/<cell>/windows.jsonl` before `arm()` (invocation id, started_at)
and a `close` row after `result.json`, `DONE.json` or `SETTLED.json` are written (the defined delivery boundary).
`recover_inflight` closes any `open` row without a `close` row of a dead invocation with `ended_at` = the recovery
time and `reconstructed: true`; the recovery time is later than every piece of that invocation's work, so the
reconstruction is conservative (it can only lengthen the window). `score.cell_summary` sums the closed windows and
requires that every attempt's `[started_at, ended_at]` of the cell lies inside some window; otherwise `evidence` is
`incomplete` and the comparison inconclusive. `child_makespan_s` stays as the descriptive statistic.

Tests. `test_s8_crash_after_last_successful_attempt_before_window_persistence_keeps_the_work_in_gated_makespan`.
`test_s8_attempt_outside_every_window_makes_the_cell_inconclusive`.

### S9. Codex quota observation: items 31, B8, RT2.5 (A4.12), ruling P3

Closes 31, B8, RT2.5.

The conflict. Item 31 forbids a model call made solely to obtain a reading, B8 shows that with `--ephemeral` only an
owner home model call refreshes the reading, and Astra's draft keeps `--ephemeral`. F7 and F8 resolve it: dropping
`--ephemeral` for worker calls makes every evaluation call write a rollout into the worker home that carries the
account id, the CLI version and timestamped `rate_limits` readings. The harness harvests it before `finish` removes
the home. No model call is added, the observation is attributable, and it covers every completed group by
construction. Isolation cost of dropping the flag: one session file in a home that is rebuilt before and emptied after
every call, holding the prompt and the reply (already in the capture) and no token text. The harness records from it
only hashes, counts, timestamps and quota numbers.

Code.

1. `FROZEN_ARGS` loses `--ephemeral`; `argv_check` and the freeze follow. `Isolation.finish` gains a `harvest` step
   before removal: read `sessions/**/*.jsonl` of the worker home, extract `session_meta.creator_account_id` (sha256
   only), `cli_version`, `base_instructions.provenance`, the last `rate_limits` object with its event timestamp, and
   the input item inventory of the turn (role, sha256, byte length of every `response_item` message that is model
   input). Append to `evidence/quota-observations.jsonl` and `evidence/instruction-context.jsonl`. The rollout content
   itself is removed with the home.
2. `quota.observations(run_dir, sessions_dir)` merges the worker harvests with the owner session readings. Each
   observation is `{percent, timestamp, account_sha256, source}`. Only observations whose `account_sha256` equals the
   baseline's account hash (the `chatgpt_account_id` claim of the baseline access token, hashed, recorded at first
   dispatch) count. The event timestamp is used; file mtime is never read for freshness (RT2.5). A reading whose
   latest `rate_limits` is malformed, non numeric, negative, above 100 or without a parseable timestamp is `None`
   and blocks; an earlier value is never substituted.
3. `CellRun.codex_quota_gate` runs before every synchronized dispatch group (not only at cell start): the newest
   qualifying observation must have a timestamp at or after the end of the last live Codex attempt of the experiment
   (every completed group covered), and `percent < 80`. Otherwise the group is not launched and the cell exits 10
   with the reason. After telemetry, the telemetry call's own rollout is the covering observation, so the first
   evaluation cell is not refused.

Proposed ruling P3 (replacement for the pending slot; Astra A and Opus B sign by diff).

> P3 (A4.12). Worker calls run without `--ephemeral`, so each call writes a session rollout into its worker home. Before
> the home is emptied, the harness records from that rollout only metadata: the hash of the account id, the CLI
> version, the base instruction provenance, the hash and length of every model input item, and the last rate limit
> reading with its event timestamp. Before each synchronized dispatch group the harness requires a quota observation
> attributable to the baseline account whose event timestamp is not earlier than the end of every previously completed
> replication call, and whose primary used percent is a finite number in [0, 100) below 80. Unknown, stale, malformed
> or out of range observations prevent dispatch. File modification times are never used. No model call is made solely
> to obtain a reading. Owner home readings of the same account may also serve as observations.

Fallback if Astra insists on `--ephemeral`: the same gate with owner readings only, which stalls after telemetry until
the driver's next Astra review call in the owner home, and a frozen headroom `percent + n * delta < 80` where `n` is the
number of live Codex calls since the reading and `delta` is a per call increment the owner must supply from observed
data. I do not recommend it: `delta` would be a guess, and the gate would stall.

Tests. `test_s9_unrelated_events_after_an_old_reading_do_not_refresh_it` (RT2.5). `test_s9_malformed_latest_reading_
blocks_and_never_falls_back`. `test_s9_reading_of_another_account_is_ignored`. `test_s9_crossing_80_between_groups_
stops_the_next_group`. `test_s9_worker_rollout_harvest_records_only_metadata_and_the_home_is_emptied`.

### S10. CLI notice and transport events: items 32, B5, B1 (c) (A4.3), rulings P1 and P4

Closes 32, B5, B1 (c).

Code. `config.SIGNED_CLI_NOTICES = ('Code Mode is unavailable because code-mode host is disabled. Code mode will fail
closed; enable `features.code_mode_host` and install `codex-code-mode-host`.',)`, exact match of the complete message.
`events._signed_cli_notice(event)`: `item.completed`, item keys exactly `{id, type, message}`, `type == 'error'`,
`message in SIGNED_CLI_NOTICES`. `classify_stream` treats it like a `KNOWN_NOTICES` entry (recorded under `notices`).
`config.SIGNED_TRANSPORT_NOTICES = ('Reconnecting... ', 'Falling back from WebSockets to HTTPS transport.')`, prefix
match, with the existing structural constraints (top level `{type, message}` for the first, error item with exactly
`{id, type, message}` for the second), and a new constraint in `classify_stream`: a transport notice is accepted only
when the stream holds no tool item of any kind; otherwise it stays uncertain. `judge_codex` keeps the authentication
check first, so a 401 inside a reconnect text still stops Codex. `code_mode_host` stays in `DISABLE_FEATURES`.

Proposed ruling P1 plus P4 (one text).

> P1 and P4 (A4.3, A4.2). On codex-cli 0.160.0: (1) a top level event with exactly the fields `type` and `message`
> whose message starts with `Reconnecting... `, and (2) an `item.completed` error item with exactly the fields `id`,
> `type` and `message` whose message starts with `Falling back from WebSockets to HTTPS transport.`, are transport
> events, not tool activity, provided the same stream holds no tool item; they are counted and recorded per call. (3)
> `--disable code_mode_host` stays in the frozen arguments, and the `item.completed` error item with exactly the fields
> `id`, `type` and `message` whose message is exactly `Code Mode is unavailable because code-mode host is disabled.
> Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.` is a plain CLI
> notice. Authentication failures keep their stop disposition and are judged first. Any tool item, any other error
> text and any altered schema keep their A4.3 disposition. No other text is added.

Alternative if (3) is not signed: `SIGNED_OMITTED_DISABLES['code_mode_host'] = <ruling file>` and the sidecar
`codex-code-mode-host.exe` stays pinned in the companion manifest (S5). I prefer (3): it keeps every available disable.

Tests. `test_s10_approved_cli_notice_is_plain`. `test_s10_notice_with_an_extra_field_is_uncertain`. `test_s10_notice_
variant_text_is_uncertain`. `test_s10_notice_with_a_tool_item_keeps_the_tool_verdict`. `test_s10_transport_notice_
with_a_tool_item_is_uncertain`. `test_s10_401_inside_a_reconnect_is_an_auth_failure`.

### S11. Bundled startup files and the effective instruction context: items 33, B6, B1 (b), the instruction half of item 1 (A4.2), ruling P5

Closes 33, B6, B1 (b).

The evidence question. Astra's item 33 is right that filename patterns and input token counts do not prove that
`skills/.system/*` are not an effective instruction source. Two pieces of execution path evidence are available
without a model call beyond the telemetry already planned:

1. F3: `--enable skip_host_skill_discovery` is accepted. Add it to the frozen argv (`FROZEN_FEATURE_ARGS`). Whether
   it suppresses the write of `skills/.system/*` is observed by the telemetry's no auth exec probe (step 3, already
   charged as telemetry, no model served): `probe_home_files_after` is the startup inventory of the frozen argv.
2. F8 with S9: the telemetry call's rollout lists every model input item of the turn. The harness compares them with
   what it sent: the base instructions (provenance recorded) and the harness stdin (sha256 equal to `stdin_sha256`).
   Any additional input item (a skills instruction block, an AGENTS.md, a developer message) is a third source and
   fails certification, whatever the filenames in the home.

Code. `TelemetryRun.arm` refuses the charged worker call (before any charge beyond the probe) when
`startup_instruction_files(probe_home_files_after)` is non empty and not covered by the signed manifest (B1 b, using
the probe as preflight since F4 shows `features list` writes nothing). `config.SIGNED_STARTUP_FILES` becomes a path to
`bench/ozmap_rep/startup-files.json`: exact relative names with sha256 per file, taken from the probe home of the
frozen argv, frozen by hash; `startup_instruction_files` subtracts a name only when its hash matches. The certificate
additionally requires `instruction_context.input_items == [base_instructions, stdin]` with the stdin hash equal to the
call's `stdin_sha256` and `base_instructions.provenance` recorded, and `runtime_files` of the call matching the
manifest names. `verify_freeze` checks the manifest hash.

Proposed ruling P5.

> P5 (A4.2). The frozen arguments include `--enable skip_host_skill_discovery`. Vendor startup files that the pinned
> CLI writes into CODEX_HOME may be accepted only when (a) they are enumerated by exact relative name and SHA256 in
> the frozen startup manifest taken from the telemetry probe home, (b) the telemetry call's session record shows the
> model input of the turn to consist of exactly the base instructions, whose provenance is recorded, and the harness
> stdin, whose hash equals the frozen prompt record, and (c) the same inventory appears after the telemetry call.
> Creating a file does not authorize loading it. Filename patterns and input token counts alone establish nothing. A
> changed hash, an additional input item or an unlisted instruction bearing file fails certification and stops the
> live path. If (b) cannot be produced, the live path stays stopped and the report names the residual risk.

Tests. `test_s11_changed_permitted_file_contents_fail_certification`. `test_s11_another_instruction_source_in_the_
rollout_fails_certification` (an extra developer item with an unchanged listing and a plain reply). `test_s11_
instruction_bearing_startup_file_blocks_the_charged_telemetry_call` (no attempt row for the worker call).
`test_s11_features_list_is_not_a_preflight` (documents F4).

### S12. Freeze refusal until the slots are settled: B1 (a)

Closes B1 (a).

Code. `config.SIGNED_RULINGS = {'P1P4': <path>, 'P2': <path>, 'P3': <path>, 'P5': <path>}` naming files under
`docs/design/ozmap-replication-2026-10-24/`. `freeze_command` refuses (exit 14) unless every file exists, contains the
lines `Signed: Astra A` and `Signed: Opus B`, and the configuration matches the ruling: `code_mode_host` in
`SIGNED_OMITTED_DISABLES` or its notice in `SIGNED_CLI_NOTICES`; `SIGNED_TRANSPORT_NOTICES` non empty or an explicit
strict decision file; the startup manifest present or an explicit strict decision; P2 and P3 decision files present.
An explicit "strict" decision is a signed file that says so. `freeze_record` includes the ruling files and their
hashes under `signed_exceptions.rulings`.

Tests. `test_s12_freeze_refuses_with_empty_slots`. `test_s12_freeze_refuses_when_a_ruling_lacks_a_signature`.
`test_s12_freeze_accepts_with_all_rulings_and_matching_config`.

### S13. Two turns in one stream: RT2.4 (A4.7)

Closes RT2.4.

Code. `classify_stream` counts `turn.started` and `turn.completed`; more than one of either adds an uncertain entry
`more than one turn in one exec stream`, so the verdict is at least `uncertain`. `_turn_usage` returns `None` when
more than one `turn.completed` is present, so usage is `incomplete`. `_rejudge` inherits both.

Test. The red team's `test_rt2_4_a_stream_with_two_turns_never_drops_the_first_turns_tokens` passes.

### S14. Unknown usage after retries and interruptions: B7, ruling P2 (A4.7, A4.11)

Closes B7 and B3 (b).

Position. Astra (item 30) rejects the retry cost as an upper bound because a failed attempt may have consumed more
than its retry. I agree for output: a timed out or dropped call may have produced reasoning tokens we never see. The
input side is bounded (same prompt, same `stdin_sha256`), the output side is not, so a defensible bound does not exist
and I withdraw the bounded gate. What makes the clause bearable is S2 and S9: a runner death no longer loses the
stream (raw files), and a call that delivered `turn.completed` has its usage whatever the exit code. The remaining
unknown cases are provider side failures without `turn.completed`, which are exactly the cases where the cost is
unknowable.

Proposed ruling P2.

> P2 (A4.7, A4.11). Unknown usage remains incomplete. An infrastructure reserve call may complete the correctness
> observation of a batch, but the usage of a later attempt never replaces the missing usage of an earlier one.
> Relevant token comparisons of a cell with an attempt of unknown usage are inconclusive; correctness and makespan
> comparisons of that cell are unaffected. An interrupted attempt whose stream was recovered is judged from the
> stream like any other call. An orphan without a readable stream is uncertain execution under A4.3 and enters
> leakage. The report shows, as a labeled non gating observation, the token gates with the unknown cost counted as the
> input tokens of the successful retry of the same batch and zero output, so readers can see how far the missing
> accounting is from the threshold.

Code. `score.cell_summary` keeps `usage incomplete`; the observation view is a third sensitivity block
`unknown_usage_observation` with the stated substitution, never consulted by `gates.evaluate`. `recover_inflight`
sets `events.verdict 'uncertain'` for an orphan without a stream (S2).

Tests. `test_s14_unknown_usage_keeps_the_token_gate_inconclusive_and_reports_the_observation`.
`test_s14_recovered_stream_usage_is_complete`.

## 3. Conflicts between reviewers, resolved

1. B8 options (a), (b), (c) against item 31 "no extra model call": S9 takes none of them; the reading comes from the
   worker's own rollout, which exists because the call was made anyway. Option (b) remains true as a side effect
   (owner readings of the same account count) and (a) is excluded.
2. B6 input token margin against item 33 "input token counts alone do not prove exclusion": S11 uses the rollout's
   model input inventory and the skill discovery switch, not token counts. Token counts remain a reported observation.
3. B2 two options: S6 takes "ledger after the group is prepared" as primary and keeps the `not_launched` row as a
   defensive second line, so the red team's RT2.3 test and the Opus regression both pass.
4. B7 bounded rule against item 30: S14 adopts Astra's strict text and demotes the bound to a labeled observation.
5. B3 (b) "uncertain: no capture" against P2: S14 rules it uncertain execution; S2 makes it rare.
6. Astra item 31 "retain --ephemeral" against RT1.6 and C12 "drop it": S9 drops it with the isolation analysis in F7
   and the harvest recording metadata only. If Astra does not sign that, the fallback in S9 applies and the live path
   stalls on owner readings, which is the correct fail closed behaviour.

## 4. Implementation order

1. S13 (two lines) and S10 code (notice predicates), with tests; rulings P1 and P4 to signature.
2. S1 (argv: credential store, secret_auth_storage disable, worker path login status, token hash gate).
3. S9 code (drop `--ephemeral`, harvest, observations, per group gate) and S11 code (skill discovery switch, probe as
   preflight, startup manifest, instruction context certificate); rulings P3 and P5 to signature.
4. S2 (raw streams, recovery order, process identity, scorer judges every capture).
5. S6 (run id in call ids, ledger after preparation, experiment lock beside the ledger, disposition import).
6. S3, S4, S5 (probes, redaction, executable identity at each boundary).
7. S7 (scorer reconstruction) and S8 (windows).
8. S14 ruling P2 to signature and the observation block; S12 freeze refusal last, then `run freeze`.

Acceptance and red team suites stay unchanged; every red team round 2 test must pass. One local no auth exec probe is
not needed before the freeze: the telemetry's own probe (already budgeted) produces the startup inventory of the frozen
argv, and the telemetry refuses the charged worker call if that inventory is not covered.

## 5. What I would accept for freeze without another full council round

After S1 to S14 are implemented with the listed tests green and the four ruling files signed by both signatories, I
would accept the freeze on the strength of a code lens pass over S2, S6 and S9 only (recovery order, ledger timing and
the harvest), because those are the three places where a wrong line still produces invalid evidence silently. S3, S4,
S5, S7, S8, S10, S11, S13 and S14 are predicate changes whose tests are the review. The rulings themselves need no
further call once signed by diff.

Residual risks to name in the report whatever is signed: the exec `--json` stream maps eight item kinds and a tool
without an exec mapping would leave no event (red team observation 1; the rollout input inventory of S9 is a second
channel for the telemetry call only); `unified_exec` cannot be disabled on 0.160.0 and A4.3 governs its events.

Signed: Fable (co-solver proposal, not a signatory)
