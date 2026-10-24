# Disputes (oz map clean replication build)

Opened by the implementer of the council build round 2 fixes (fresh Opus workflow subagent, 2026-10-24). Each entry
names the conflicting texts, the evidence and the change asked for. Nothing in a disputed test or blocker was changed
or weakened; the implementation follows the text named as governing until a ruling exists.

## D-R2-1. Red team test RT2.1 asserts a resend that blocker 3 and A4.3 forbid

Test: `bench/ozmap_rep/redteam/test_redteam_r2.py::test_rt2_1_execution_captured_before_the_runner_died_is_still_leakage`.

The test kills the runner after the capture of `codex-materials-cold-A.r1.b03.t0` (whose stream holds an executed
`command_execution` item) and before its attempt row, resumes, and then asserts three things besides the leakage:

1. `outcomes[target] == 'interrupted'`,
2. `outcomes['codex-materials-cold-A.r1.b03.t1'] == 'ok'` (the batch is resent from the reserve),
3. the resumed cell returns `EXIT_OK`.

Conflicting texts:

* Council round 2 blocker 3 (Astra item 3): "Reconcile durable captures and parsed outputs before assigning
  interruption or retry eligibility; keep terminal outcomes", with the test "crash between capture, call record and
  attempt append for ok, refused, executed calls (none resent)".
* Joint decision of the round 2 deadlock (items 3, B3, RT2.1, Fable S2.3, agreed): "A terminal outcome recovered under
  (b) or (c) is read back by `run_batches` and never resent."
* A4.3: "No selective rerun erases failure. Existing infrastructure retry and answer repair restrictions remain." An
  executed call is not an infrastructure failure, so an infrastructure retry of it is outside the reserve's purpose
  (A4.5: unused capacity cannot authorize repair).

Evidence (the fixed harness, this commit): the resumed run judges the committed capture, records the target with
outcome `executed` and `recovered_from: capture`, never sends `r1.b03.t1`, settles the cell (`SETTLED.json`, exit 5),
and the report lists the target in `validity.leakage` twice (its tool event verdict, and `raw_mismatch` because the
test changes the stream after the child wrote its raw file). The test's leakage assertion, its purpose, holds; only the
three assertions above fail. `tests/test_council_r2.py::test_item3_a_crash_between_capture_call_record_and_attempt_row_never_resends`
covers the same crash for ok, refused and executed streams at both crash points.

Asked: replace assertions 1 to 3 with `outcomes[target] == 'executed'`, the target row `recovered_from == 'capture'`,
no attempt `r1.b03.t1`, and the resumed run returning `config.EXIT_INCOMPLETE`; keep the leakage assertion unchanged.

## D-R2-2. The joint decision drops `--ephemeral`, which A4.2 names in the frozen arguments

Joint decision (council-build-deadlock-r2-joint.md, section 1 item 1 and items 31, B8, RT2.5): "`--ephemeral` is dropped
for worker calls", with Astra's P3 ("Codex worker calls may omit `--ephemeral` ... solely with a certified per-attempt
persistence and harvesting lifecycle"), signed by Astra A only and pending Opus B confirmation by diff.

Conflicting texts:

* A4.2 (normative, signed by Astra A and Opus B): "Freeze an allowlisted environment and accepted arguments:
  `exec --ignore-user-config --ignore-rules --ephemeral --skip-git-repo-check --json -s read-only -C <numbered empty dir>`",
  and "Exclude ... sessions".
* The joint decision itself: "No change to the text of Amendment 4 is agreed".
* The blind acceptance suite derived from A4: `acceptance/test_a4_2_argv.py` (`FROZEN_HEAD` and the `--ephemeral`
  removal mutation) and `acceptance/test_cli_plan_and_cells.py` (`FROZEN_HEAD`, checked on every fake call's argv).
* Council round 2 blocker 31 as relayed to this step: "keep --ephemeral".

Disposition in this commit (A4 precedence): `--ephemeral` stays in `config.FROZEN_ARGS`. The rest of P3 is implemented
(event timestamps only, latest reading validated before use, per attempt coverage, account mismatch rejection, the gate
before every dispatch group including telemetry, worker rollout harvest whenever a rollout exists), so the only effect
of keeping the flag is that, after the first Codex group, a live dispatch needs an owner reading of the same account
timestamped after the last completed live Codex call. P3 counts the driver's independently authorized Astra calls in
the owner home as such readings and forbids adding a call for quota, so the live run proceeds only as fast as those
readings appear. The fake CLI already writes a rollout whenever `--ephemeral` is absent, and the harvest is tested
(`test_item31_a_worker_rollout_reading_covers_its_own_attempt`).

Asked: Opus B's ruling on P3 states whether it amends A4.2's argument list. If it does, the ruling also accepts the
change of the three acceptance assertions named above, and `config.FROZEN_ARGS` loses `--ephemeral` in the same commit.
