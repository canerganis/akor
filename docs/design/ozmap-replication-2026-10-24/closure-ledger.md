# Closure ledger: round 3 blockers under A4.14 (2026-10-25)

Scope: every BLOCKER raised in the round 3 council files (council-build-astra-r3.md items 1 to 33, council-build-opus-r3.md
B1 to B4, council-build-redteam-r3.md RT3.1 to RT3.3) and the two round 2 disputes they ruled on. Each entry has one
disposition:

* **closed**: fixed in code, with the commit and the regression tests named;
* **moot under A4.14.1**: the defect lived in in flight recovery, resume or rerun machinery that A4.14.1 removed;
* **CHANGE under A4.14.2**: the item cannot let an invalid, leaked, misaccounted or wrong result reach the result report
  unflagged and cannot harm the owner's own Codex login or accounts; the reason is given;
* **open**: still a BLOCKER.

Commit: the commit with the message `bench/ozmap_rep: fail closed execution per A4.14` (branch oz-0.9; its hash is in
the driver's step record). Tests: `bench/ozmap_rep/tests/test_a414_fail_closed.py` unless another file is named.
"Launch prerequisite" below means a ruling or annex that `rulings.readiness_problems` requires: `run freeze` refuses
(exit 14) and `verify_freeze`, which every live cell and telemetry run calls before any dispatch, repeats the check, so
no live call can be made, and therefore no evaluation result can exist, while the prerequisite is missing. Such items
are CHANGE under A4.14.2, but they stay required before the freeze.

## Summary

| item | disposition |
|---|---|
| Astra 1 | closed |
| Astra 2 | CHANGE (launch prerequisite D1) |
| Astra 3 | CHANGE (launch prerequisite P5, D2) |
| Astra 4 | closed in part; rest CHANGE (launch prerequisite P3) |
| Astra 5 | CHANGE (launch prerequisite P4) |
| Astra 9 | closed |
| Astra 10 | closed (Opus B: remained a BLOCKER) |
| Astra 11 | closed |
| Astra 12 | closed |
| Astra 13 | moot under A4.14.1 for the crash path; closed for the journal path |
| Astra 14 | closed |
| Astra 15 | closed (Opus B: remained a BLOCKER) |
| Astra 16 | closed in part; launch environment reconstruction CHANGE |
| Astra 17 | moot under A4.14.1 for recovery bounds; rounding closed |
| Astra 23 | closed |
| Astra 32 | CHANGE (launch prerequisite D6, a review step) |
| Opus B1 | CHANGE |
| Opus B2 | CHANGE (launch prerequisite) |
| Opus B3 | CHANGE (launch prerequisite P5, D2) |
| Opus B4 | CHANGE (launch prerequisite P3) |
| RT3.1 | closed |
| RT3.2 | closed (Opus B: remained a BLOCKER) |
| RT3.3 | closed |
| D-R2-1 | closed |
| D-R2-2 | closed (upheld, no change) |

No item is open.

## Astra, council round 3

**1. Freeze readiness does not bind the approved annexes. Closed.** `rulings.annex_problems` (called from
`ruling_problems`) requires each ruling slot to bind its annexes (`ANNEXES_REQUIRED`: P3 quota source manifest, P4 CLI
notice annex, P5 startup manifest and effective context evidence, D1 attribution evidence) as `{path, sha256}`; each
file must hash to its value, the hash must appear in the countersigned ruling text, the startup manifest annex must be
the file the harness reads (`config.STARTUP_MANIFEST_FILE`), and the P4 annex must equal the configured notice
predicate (`rulings.cli_notice_config`). `rulings.record` binds the annexes into `freeze.json`, so `verify_freeze`
detects a later change. Tests: `test_item1_readiness_binds_each_ruling_to_its_approved_annexes` (each annex
substituted on its own, a changed predicate and a missing binding each block); `tests/test_council_r2.py::
test_b1_readiness_needs_countersigned_ruling_bytes_and_a_matching_configuration` extended with annexes, its round 2
assertions unchanged. The annexes themselves remain signatory work (P1 to P5, D1 are unsigned).

**2. D1 attribution evidence absent. CHANGE (launch prerequisite D1).** `auth_source` stays a configuration statement;
the D1 ruling with its `attribution_evidence` annex is now a required, hash bound readiness input (item 1). Until it
is signed the freeze refuses and no live call can happen, so no result exists that the gap could corrupt.

**3. P5 manifest schema, link substitution, effective instruction context. CHANGE (launch prerequisite P5, D2).** The
startup manifest is absent, so `startup_instruction_files` accepts nothing and the telemetry certificate cannot pass;
the P5 ruling now has to bind both the manifest and the `effective_context_evidence` annex (item 1) before the freeze.
The effective context check Opus B3 describes is the verification procedure that annex has to define; it is not yet
implemented and must be, with the annex, before the freeze. While P5 is unsettled no live call can be made.

**4. P3 quota source: account, bucket, timestamps, malformed latest reading. Closed in part; the rest CHANGE (launch
prerequisite P3).** Closed: a malformed latest `rate_limits` value that is not an object is now selected and rejected,
never skipped in favor of an earlier reading (`quota._find_rate_limits`, `read_file`); every gate row records the
source file, its account hash and the sessions directory; live mode reads only the owner sessions (RT3.3). Tests:
`test_item4_a_malformed_scalar_latest_reading_blocks_and_never_falls_back`, red team RT3.3. CHANGE: required account
and bucket attribution and first group freshness need the P3 source manifest (account from `session_meta`, bucket
`window_minutes` and `limit_id`), which is the P3 annex now bound by readiness; the quota gate concerns the A4.12
operational stop, not the validity of a result, and while P3 is unsettled no live call can happen.

**5. P4 annex missing. CHANGE (launch prerequisite P4).** `code_mode_host` stays disabled and the notice predicate
inactive, so every exec would be uncertain; readiness refuses until the P4 annex is approved and equals the configured
predicate (item 1).

**9. Process tree termination and sibling propagation. Closed.** Every child (model call or local probe) runs in a
supervised process tree (`procs.Tree`): on Windows it is created suspended, assigned to a kill on close job object
without breakaway, journaled, then resumed, so no descendant outlives its call or its runner, and termination is
established by the job's active process count, not by the parent pid. `spawn` and `run_local` kill and wait out any
descendant that survives the parent, and a tree whose end cannot be established is unsettled. `after_group` never
propagates a sibling's refreshed authentication when any member of the group did not settle normally: the baseline
stays unchanged and Codex stops. Recorded markers are covered by the A4.14.1 containment check (`marker_containment`).
Tests: `test_item9_a_descendant_that_outlives_its_parent_is_ended_with_the_tree`,
`test_item9_a_sibling_refresh_is_never_propagated_beside_a_call_that_did_not_settle`,
`test_a414_a_child_still_running_prevents_every_further_admission`,
`test_a414_an_unidentified_or_unsupervised_child_stops_the_run`.

**10. Stream existence treated as recovery evidence. Closed** (Opus B: remained a BLOCKER). The recovery path
(`_recover_stream`, `recover_inflight`) is removed: after a crash no stream is promoted or judged again; a dispatched
call without its attempt row is recorded `unsettled`, an uncertain call state, which makes the cell invalid
(`run.stop_cell`, `score_run`). In the running process, a child that had to be killed (journal failure, wait exception)
and whose stream lacks complete terminal evidence is recorded `unsettled` with an uncertain verdict, never a retryable
infrastructure failure; a delivered terminal outcome keeps its outcome and is not resent. Tests:
`test_item10_a_killed_child_without_terminal_evidence_is_unsettled_not_retried`,
`test_a414_a_crash_mid_record_preserves_the_call_unsettled_and_never_resends` (six cases),
`test_a414_an_orphan_without_any_stream_is_unsettled_leakage_and_its_usage_stays_incomplete`, red team RT2.1 as
replaced.

**11. Reservation durability, ledger reconciliation, predecessor stops. Closed.** A reservation that fails after its
first marker keeps every reserved member as a charged `not_launched` attempt with its ledger row (`CellRun.abandon`);
the A4.14.1 stop records the ledger row of any reserved or dispatched marker that lacks one (`_ensure_ledger_row`); the
scorer checks both directions (ledger rows missing from attempts, and live attempts missing from the ledger); a
replacement directory refuses dispatch while a superseded directory holds a safety kill or a run stop
(`predecessor_stops`) and never reruns a cell that already dispatched there (`predecessor_cell_calls`). Tests:
`test_item11_a_failed_ledger_append_inside_a_reservation_keeps_every_debit`,
`test_item11_a_live_attempt_missing_from_the_ledger_is_an_accounting_failure`,
`tests/test_council_r2.py::test_item9_a_replacement_directory_never_repeats_a_terminal_batch` (unchanged), red team
RT2.2 (unchanged).

**12. Executable hashed before the write guard. Closed.** `Executables.verified_guard` hashes the manifest, takes the
write guard, hashes again under the guard and requires the same identity; the per child statistics are taken under the
guard. Test: `test_item12_a_manifest_changed_while_the_guard_is_taken_is_refused`.

**13. Local probe crash path. Moot under A4.14.1 for the crash path; closed for the journal path.** Recovery of probe
markers is removed: after a crash a probe marker is part of the stopped cell, its home's authentication is compared with
the prepared generation (a change stops Codex, nothing is propagated or erased) and its containment is checked like a
call's. `run_local` no longer suppresses a pid journal failure: it ends the supervised tree and raises; the probe is
reconciled as an authentication failure (Codex stops) and the cell stops. Test:
`test_item13_a_probe_whose_pid_cannot_be_journaled_stops_codex_and_propagates_nothing`.

**14. Expiry gate not bound to the reserved generation. Closed.** `reserve_group` reads, under the authentication lock,
the baseline hash, the 48 hour wave gate and the inventory of the generation the members were prepared from, records
them in `evidence/reservation-gates.jsonl`, and refuses the group (nothing launched, the reseed kept) on any failure.
Test: `test_item14_a_baseline_reseeded_after_the_gate_with_a_short_expiry_is_refused_at_reservation`.

**15. Probe disclosures not consumed. Closed** (Opus B: remained a BLOCKER). A probe disclosure is recorded with per
channel original and sanitized hashes, stops the cell (A4.14.1 isolation signal), blocks telemetry certification and
evaluation (`telemetry_failures`), and fails isolation in the scorer; the scorer also checks every capture's own
redaction record, whatever the attempt's disclosure flag says. Tests:
`test_item15_a_probe_disclosure_fails_isolation_and_certification`,
`test_item15_a_capture_redaction_is_isolation_failure_whatever_the_attempt_flag_says`.

**16. Scorer trusts records, job ids and audits. Closed in part; launch environment reconstruction CHANGE.** Closed: the
scorer rebuilds each evaluation attempt's prompt from its job ids and the frozen workload (order included) and requires
the recorded prompt hash, recomputes the per operation `records` that attribute costs to R, derives the required audit
sample from the covered jobs with the frozen rule phase and compares it with the recorded audit set, and allows warm C
rule answers only for operations cold C adopted. Admission dispositions were already reproduced from capture derived
bytes. Tests: `test_item16_the_scorer_reconstructs_records_and_job_order_from_the_prompt` (two cases),
`test_item16_a_deleted_audit_is_detected`, `test_item16_warm_C_reuses_only_a_rule_cold_C_adopted`. CHANGE: the full
reconstruction of the launch environment and channel evidence; the runner verifies the environment before every launch
and a launch record with problems already fails `_evidence_ok`, so only a later edit of preserved evidence by hand
could hide a difference, which is tampering after the fact, not a path of the harness.

**17. Recovery timing bounds and rounding. Moot under A4.14.1 for recovery bounds; rounding closed.** Recovery no
longer closes windows of live work; a crashed invocation's window is closed with bounds only after containment, and a
crashed cell is interrupted, so its makespan never gates. Makespan bounds now round outward (lower bound down, upper
bound up to the millisecond). Tests: `test_a414_a_crash_after_the_last_call_leaves_a_bounded_window_and_an_interrupted_
cell`, `test_item17_makespan_bounds_round_outward`.

**23. Sonnet route identity delegated to the adapter. Closed.** `events.classify_claude` now requires, independent of
the parent's `OZ_MODEL`, exactly one turn, a permission denial list and usage of the frozen Sonnet model only; missing
or other evidence is uncertain. Test: `test_item23_the_sonnet_route_is_checked_by_the_harness_itself` (four cases, with
`OZ_MODEL` emptied).

**32. D6 focused verification. CHANGE (launch prerequisite, review step).** The focused verification and the
operation dependent attestation are workflow steps before the freeze (A4.14.3 closure rounds); they are not code paths
that can let a result through.

## Opus, council round 3

**B1. With `--ephemeral` the live run cannot finish unattended. CHANGE.** The worst outcome is a stopped cell: the
quota gate refuses the next group before any charge. Under A4.14.1 this is sharper than before, because a cell that
stops after its first group is interrupted for good and its comparisons are inconclusive. Before live waves the
signatories need either the narrow A4.2 revision Opus B1 describes (omit `--ephemeral` under the P3 lifecycle, so each
attempt is covered by its own rollout reading) or a recorded attended reading plan.

**B2. Countersignatures and annexes before the freeze. CHANGE (launch prerequisite).** Readiness refuses with every P1
to P5 and D1 slot unsettled, and now also requires the bound annexes (Astra 1).

**B3. No effective instruction context check. CHANGE (launch prerequisite P5, D2).** As Astra 3: the P5 ruling must bind
the effective context evidence and its verification procedure before the freeze; the procedure is implemented with
that annex.

**B4. Quota account and bucket identity. CHANGE (launch prerequisite P3).** As Astra 4.

## Red team, round 3

**RT3.1. Discovery locations and the live directories below the owner profile. Closed.** `isolation.instruction_scan`
refuses a launch when `.agents`, `.codex`, `.claude`, `mcp.json`, `.mcp.json`, `CLAUDE.local.md` or `AGENTS.local.md`
exists in the working directory or any ancestor (besides AGENTS.md, AGENTS.override.md and CLAUDE.md everywhere); the
owner profile directories (Path.home() and the OS known folder profile) are excluded from the extended walk only,
because the live run directory now defaults to `<system drive>\ozmap_rep\runs\replication`, outside the profile, and
`run freeze` refuses a live run directory below a profile. Tests: `redteam/test_redteam_r3.py::
test_rt3_1_a_discovery_location_in_an_ancestor_blocks_the_launch` (nine cases),
`test_rt3_1_the_live_working_directories_are_not_below_the_owner_profile`. Whether the pinned CLI resolves user scope
skills from the OS profile is the P5 effective context question (Astra 3).

**RT3.2. Token separation by exact hash only. Closed** (Opus B: remained a BLOCKER). `token_separation_problems` also
compares the login session (`isolation.login_identity`, the access token `session_id`, hashed), so a stale copy of the
owner login is refused; an owner Codex home that exists but holds no auth.json, or whose configuration names a keyring
or auto credential store, is an unexplained representation and refuses. Checked on this machine, hashes only: the
baseline and the owner home carry different sessions and the check passes. Tests:
`redteam/test_redteam_r3.py::test_rt3_2_a_rotated_copy_of_the_owner_login_is_not_a_separate_login`,
`test_rt3_2_an_owner_credential_outside_auth_json_is_never_treated_as_separate`.

**RT3.3. The quota stop reads a named sessions directory. Closed.** In live mode any sessions directory other than
`config.CODEX_SESSIONS_DEFAULT` is refused (in the gates and in the quota gate itself), every gate row records the
source file, account hash and directory, and the report lists any group released on a reading outside the owner
sessions. The two Live test fixtures now point `CODEX_SESSIONS_DEFAULT` at their temporary sessions, as the red team
fix prescribes. Test: `redteam/test_redteam_r3.py::test_rt3_3_the_live_quota_stop_reads_the_owner_sessions_not_a_
named_directory`.

## Round 2 disputes

**D-R2-1 (RT2.1 resend assertions). Closed.** Both reviewers accepted dropping the resend; A4.14.4 then replaced the
test's recovery expectations: `redteam/test_redteam_r2.py::test_rt2_1_execution_captured_before_the_runner_died_is_
still_leakage` now asserts the crashed cell is refused (exit 19), the call is `unsettled`, no `.t1` exists, the capture
stays leakage and the cell is invalid.

**D-R2-2 (`--ephemeral`). Closed, upheld.** The acceptance assertions and A4.2 keep the flag; nothing changed (see B1).

# Closure round 1 blockers (A4.14.3, 2026-10-25)

Scope: every BLOCKER of closure round 1: closure-astra-r1.md (O1 to O5 and the new N1), closure-opus-r1.md (N1) and
closure-redteam-r1.md (RTC1.1, RTC1.2). Where an item reopens a round 3 entry above, this section supersedes that
entry. Commit: the commit with the message `bench/ozmap_rep: closure round 1 fixes` (branch oz-0.9; its hash is in the
driver's step record). Tests: `bench/ozmap_rep/tests/test_closure_r1.py` unless another file is named. The red team
tests (`bench/ozmap_rep/redteam/`) and the acceptance tests are unchanged; `redteam/test_redteam_closure1.py` now passes.

| item | disposition |
|---|---|
| O1 (Astra 10) | closed |
| O2 (Astra 12) | closed |
| O3 (Astra 13) | closed |
| O4 (Astra 15) | closed |
| O5 (Astra 32) | closed; judged not to meet A4.14.2 (reason below), fixed because it was cheap |
| N1 (Astra, CHANGE 22 raised) | closed |
| N1 (Opus) | closed |
| RTC1.1 | closed |
| RTC1.2 (RT3.2) | closed |

No closure round 1 item is open.

**O1. An ordinary timeout hid execution uncertainty. Closed.** `CellRun.execute` marks every child that `spawn`
returns with `timed_out` as a killed child (`c['killed']`). In `after_group` a killed child whose judged outcome is
retryable (no complete terminal outcome) is handled like every other killed child: it becomes a spawn failure, its
outcome is `unsettled` with the verdict `uncertain`, it is never retried from the reserve, the group propagates no
authentication and the cell stops (Codex: `codex-stop.json`; Sonnet: interrupted). A complete terminal outcome (a
delivered reply, a tool verdict, an authentication failure) is kept. The scorer already accepts `unsettled` against a
capture that judges a retryable outcome, so no artifact problem appears, and the call is leakage, so the cell is
invalid. Tests: `test_o1_a_timed_out_child_without_terminal_evidence_is_unsettled_never_retried` (a child that emits only
`thread.started` and `turn.started` and is killed by the timeout), `test_o1_a_timed_out_child_that_delivered_its_reply_
keeps_its_outcome`; `tests/test_council_r1.py::test_item13_a_timed_out_call_with_a_delivered_reply_is_never_sent_again`
unchanged.

**O2. Local probes outside the guarded identity check. Closed.** `worker_probe` takes `Executables.verified_guard`
(hash, write guard, hash again under the guard, same identity required) after preparing its home and holds it until
the probe's tree has ended and the probe is reconciled; `exe.recheck()` runs immediately before the child, and a failure
refuses the probe before it starts (its marker is removed, nothing ran). `TelemetryRun.worker_path_logins` holds one
verified guard across its whole probe group with a recheck before each child. The guard is required to be held in live
mode, as for launch groups (`live=self.opts.mode == 'live'`); on Windows it is taken in fake mode too. Tests:
`test_o2_every_local_probe_runs_under_the_guarded_identity_check` (every features, login and worker path probe of a
telemetry run and a cell runs inside an entered guard), `test_o2_a_manifest_changed_after_the_group_check_refuses_the_
probe_before_it_runs`.

**O3. Uncertain probe output could vanish. Closed.** `run_local` writes a probe's stdout and stderr to raw stream
files inside the credential boundary (`D/homes/raw-<slot>/<probe id>.std*`, named by `_TLS.probe_raw`), so a
`SpawnFailure` carries what the probe emitted once its tree is shown gone. `CellRun.probe_evidence` sanitizes that
output with the prepared and current secrets, records `evidence/probe-failures.jsonl` (sanitized hashes and redaction
counts per channel, never text), records a disclosure in it as a probe disclosure, and, when output completeness cannot
be established (tree end not established, or no readable raw stream), records `evidence/probe-uncertain.jsonl` with the
cell id. The scorer turns each uncertainty row into an isolation problem attributed to the cell (invalid), and
`telemetry_failures` refuses certification on it. The raw files are kept on any failure or disclosure and deleted only
after a probe settled cleanly. A child shown never resumed emitted nothing and keeps its own disposition (no row).
Tests: `test_o3_run_local_keeps_the_output_a_probe_emitted_before_waiting_failed` (a real child, `communicate`
raising), `test_o3_a_probe_that_did_not_settle_leaves_its_evidence_and_makes_the_cell_invalid` (tree gone with a
disclosure, tree end not established).

**O4. A probe disclosure cell reported interrupted without finding. Closed** (with N1 Opus and RTC1.1 below).
`tests/test_a414_fail_closed.py::test_item15_a_probe_disclosure_fails_isolation_and_certification` now also requires
the cell state `invalid` and the cell absent from `validity.interrupted`.

**O5. D6 not an enforced launch prerequisite. Closed; judged not to meet A4.14.2.** Reason: the attestation reviews
preparation artifacts (oracle, classification, contracts, cases); with D6 absent no harness path turns a detected or
detectable validity failure into an unflagged result, and a wrong oracle is not something the harness can detect at
all, which is why the protocol puts it in a review step. The fix was cheap, so it was made: `config.REQUIRED_RULINGS`
now includes `D6`, and `rulings.ANNEXES_REQUIRED['D6']` requires two bound annexes, `focused_verification` (every item
of the D6 checklist of the round 2 joint decision with verdict `pass`) and `operation_attestation` (oracle correctness,
classification, contract extraction, consumer checks, the 48 representative and 16 challenge cases with those counts,
sealing and access chronology, each `pass`; an attestor recorded as independent of the implementer; bound to the
current `classification.json` hash and to the hash of every file of `bench/ozmap_rep/ops`). Each annex is hash bound in
the countersigned ruling text like the other annexes, so `freeze_command` refuses (exit 14) and `verify_freeze`
refuses every live dispatch while D6 is missing, unsigned, changed or no longer bound to the files it attests. The
scorer checks the rulings bound in the run's `freeze.json` again (`rulings.bound_problems`, called by
`_freeze_problems`), so a run bound without D6 has freeze problems and no claim. Tests: `test_o5_d6_is_a_required_
ruling_with_its_two_annexes`, `test_o5_the_attestation_must_cover_every_item_and_bind_the_classification_and_
operations`, `test_o5_the_scorer_checks_the_rulings_the_run_bound_freeze_binds`; the readiness fixtures of
`test_item1_readiness_binds_each_ruling_to_its_approved_annexes` and `tests/test_council_r2.py::test_b1_readiness_needs_
countersigned_ruling_bytes_and_a_matching_configuration` now bind valid D6 annexes (`tests/test_council_r1.write_d6_
annexes`), their assertions unchanged. The annexes themselves remain signatory and reviewer work.

**N1 (Astra). Demonstrated Sonnet accounting violations only incomplete. Closed.** `usage.decode_sonnet` detects present
contradictions (any negative counter, `cached_input_tokens > input_tokens`) independently of completeness, keeps both
findings (`problems` lists the missing counter and the contradiction, `incomplete` is set) and returns `invalid`, which
takes precedence. Fields are filled only for present counters. `account_usage` no longer indexes counters an invalid
partial usage lacks. On the frozen route the adapter reports an envelope with a negative counter as unknown usage, so
the harness also reads the envelope (`run.sonnet_envelope_violation`): with a negative counter in `modelUsage` it keeps
the present counter sums (a missing counter stays absent, never zero) and the decoder judges them invalid; the scorer
derives the same through `judge_sonnet`. A cache contradiction cannot arise through the adapter (its input includes the
cache reads), so that case is covered at the decoder. Tests: `test_n1_a_demonstrated_sonnet_accounting_violation_is_
invalid_whatever_else_is_missing` (six cases: negative counters and cache contradictions, each with and without missing
fields), `test_n1_complete_and_merely_incomplete_sonnet_usage_are_unchanged`, `test_n1_a_negative_sonnet_counter_makes_
the_stopped_cell_invalid` (end to end through the envelope).

**N1 (Opus) and RTC1.1. Findings attributed by text; crashed cells never given their validity. Closed.** `score_run`
now attributes each finding where it is produced, by the structured cell field of its record (`cell_findings`): per
attempt findings (leakage, usage, launch evidence, authentication record, credential disclosure, input and rejudge
artifact problems) by the attempt's cell; repeated call ids by the cells of that id; duplicate terminal attempts by the
cell of the key; allocation overcounts (run and experiment ledger) to every cell of that allocation; unledgered live
attempts and ledger rows missing from the run directory by their cells; capture redactions and capture verdicts by the
capture's cell; lost markers and open probes by their cell directory; probe disclosure and probe uncertainty rows by
their `cell`; wave gate and features findings by cell id; `codex-stop.json` and `run-stop.json` by their `cell` field;
the cell chain by its cell. A cell is stopped when it is neither complete nor settled and holds `INTERRUPTED.json`, was
left `running`, holds markers or has attempts (the `crash_scan` predicate, read only; the scorer never writes
`INTERRUPTED.json`). A stopped cell with any attributed finding is `invalid`; one without is `interrupted`. Tests:
`redteam/test_redteam_closure1.py::test_rtc1_1_a_cell_stopped_by_its_probe_disclosure_is_invalid_not_interrupted` and
`test_rtc1_1_a_crashed_cell_scored_before_any_later_admission_gets_its_validity` (unchanged, now pass); the two Opus
reproductions as `test_item15_a_probe_disclosure_fails_isolation_and_certification` (extended) and
`test_n1_a_stopped_cell_with_an_unledgered_live_attempt_is_invalid`; `test_n1_a_stopped_cell_with_duplicate_terminal_
attempts_is_invalid`; controls `test_rtc1_1_a_stopped_cell_without_any_finding_stays_interrupted` and `test_rtc1_1_a_
codex_stop_names_its_cell_and_makes_it_invalid`.

**RTC1.2. A missing login identity treated as a different login. Closed.** `isolation.login_identity` now reads every
place the identity appears: the access token `session_id` (top level or in the auth claim), the id token `sid` or
`session_id`, and `auth_time` and `pwd_auth_time` from either token together with the account id; it returns sorted
hashes only. `token_separation_problems` refuses when the baseline and an owner file share any session hash or any
authentication time hash, and returns a problem when an existing owner auth.json or the baseline yields no identity at
all; the exact token hash comparison is kept. Checked on this machine, hashes and booleans only: the baseline and the
owner home share the account id (expected) and no session, `sid`, `auth_time` or `pwd_auth_time`; the check passes.
Harness fixtures now carry a login session: `run.synthetic_baseline` a random `session_id`, the fake CLI's refresh keeps
the session of the login it refreshes (as a real refresh does), and `tests/test_council_r1.write_auth` a session per
marker. The live separation gate in `CellRun.gates` now runs right after the Claude quota stop instead of before it
(still before every other live check and every dispatch; `Isolation.prepare` repeats it under the authentication
lock), so the acceptance test `test_cli_codex_quota_stop_at_80_percent_happens_before_any_call`, whose baseline
fixture carries no identity, still ends with the quota stop. Tests: `redteam/test_redteam_closure1.py::test_rtc1_2_a_
stale_copy_of_the_owner_login_passes_when_the_access_token_has_no_session_claim` (unchanged, now passes), `test_rtc1_2_
a_login_without_any_identity_is_never_treated_as_separate`, `test_rtc1_2_any_shared_identity_component_refuses` (three
cases), `test_rtc1_2_login_identity_holds_hashes_only`; `redteam/test_redteam_r3.py` RT3.2 tests unchanged.

## Closure round 1 verification

| command | result |
|---|---|
| `python -m pytest bench/ozmap_rep -q` | 600 passed (acceptance, ops, red team with the closure 1 tests, harness tests) |
| dry run `python -m bench.ozmap_rep.run dry --run-dir <D>` | exit 0: 16 of 16 cells complete, 52 fake calls, 0 external calls; report: leakage 0, accounting failures 0, artifact problems 0, isolation passed, no stopped or invalid cell |
