I sign the prospective rulings below as protocol text. I do not sign the current implementation or certify that its launch prerequisites have been met. These solutions use only the supplied pack. I have read no repository files, inspected no operation content, and run no tests or model calls.

Each signature applies to the exact ruling text. Opus B may countersign that text by diff. My signature does not imply Opus B’s acceptance or approve an evidence annex that has not yet been supplied.

1. **Recovery and capture completeness. Closes 3, B3 and RT2.1.**

   **Implementation:** In `run.py`, make `spawn`, `CellRun.execute`, `after_group` and `recover_inflight` use one durable attempt state machine:

   ```text
   prepared
   reserved
   launch_intent
   running
   process_terminated
   captures_committed
   verdict_committed
   settled
   ```

   Record each transition durably before performing an action that depends on it. A local attempt journal may mirror the authoritative experiment ledger, but recovery must reconcile them rather than infer completion from either file alone.

   Redirect child stdout and stderr to distinct restricted raw files. Treat their directory as credential bearing runtime state, outside learner accessible paths except the child’s inherited write handles. Do not depend on pipes whose contents disappear with the runner.

   Before starting model execution, establish durable process identity using PID, process creation time, executable identity and an attempt specific supervisor or job identity. On Windows, a suspended launch can permit identity persistence before execution resumes. If journaling fails, terminate the suspended child and verify termination. If that cannot be established, stop Codex dispatch and preserve its home, raw files and marker.

   A PID alone, an empty home, an absent marker or a `Popen` exception does not prove that no child ran. Cleanup requires established termination of the relevant process tree. An exception after possible spawn enters an ambiguous state until reconciled.

   Recovery must inspect, in order, committed captures, parsed records, raw files and process state. Recompute the verdict from available captures using the frozen classifier. A delivered answer, refusal or execution finding is terminal and cannot be resent. A terminal answer may still leave unresolved jobs or audits, so terminal settlement must remain distinct from successful cell completion.

   Only a proven infrastructure failure without terminal output, execution or unresolved execution uncertainty may use an authorized reserve. Recovery itself creates no retry permission.

   In `score.py:score_run` and `_rejudge`, enumerate the union of authoritative ledger attempts, local attempts, parsed records and captures. Judge every capture, including captures associated with `interrupted`, `not_launched` or otherwise inconsistent records. An execution finding is sticky. Missing or truncated capture evidence after possible launch is `uncertain: no complete capture` and enters the experiment wide leakage disposition.

   **Tests:** Inject crashes after raw output, sanitized capture, parsed record and attempt append for an ordinary answer, refusal and executed tool call. None may be resent. Preserve `test_rt2_1_execution_captured_before_the_runner_died_is_still_leakage`. Test PID journal failure, a live child after a communication exception, PID reuse, a missing PID, a missing raw stream and a partially written stream. No ambiguous case may clean its home or permit another Codex dispatch.

   Launch live runners detached with a lifetime sufficient for the cell. This reduces interruption frequency but is not part of the correctness proof.

2. **Experiment identity, replacement directories and cumulative accounting. Closes 9 and RT2.2.**

   **Implementation:** Give each experiment and run immutable UUIDs. Give every reservation a unique `attempt_uid`, for example an experiment UUID plus a ledger allocated sequence. Keep the logical batch key separate:

   ```text
   experiment_id
   run_id
   attempt_uid
   logical_batch_key
   allocation
   nominal_or_reserve
   retry_reason
   ```

   In live mode, `CellRun.budget()` must reconstruct allocation consumption from the authoritative experiment ledger alone. Local attempt records supply evidence, not additional charges. Duplicate copies of an identical ledger event are idempotent; conflicting records sharing an identity are an accounting failure.

   Place the experiment lock beside that ledger, outside individual run directories. Reservation, budget validation, logical batch disposition and replacement directory activation occur under this same lock. Preserve the existing separate authentication lock.

   `freeze_command` must bind a replacement disposition containing the previous run identities, evidence roots, unresolved attempts, terminal batches, failures and active run identity. Hash and sign the disposition. A replacement cannot repeat terminal batches, reset telemetry allowances, discard previous leakage or remove a failed telemetry disposition. Any permission to continue after a failure must be explicit and cannot erase that failure from reporting.

   The scorer must traverse all experiment evidence referenced by the ledger and disposition. An unavailable predecessor directory or missing required predecessor evidence withholds claims.

   Torn or malformed ledger lines must cause a parse failure, not be silently skipped. Report nominal and reserve consumption separately. A nominal allocation overrun cannot be concealed by unused reserve capacity.

   **Tests:** Preserve `test_rt2_2_a_superseded_run_directory_never_restores_used_nominal_calls`. Exercise identical historical call labels in different runs, repeated telemetry failures, migration after a failed telemetry call, an attempted terminal batch repeat and two competing runners in different directories. Every historical debit must survive, and only one runner may reserve against the experiment.

3. **Atomic group preparation and abandonment. Closes B2 and RT2.3.**

   **Implementation:** Choose complete group preparation before reservation.

   `prepare_call()` should create staged preparation evidence without charging the live ledger. Prepare and validate every member first. Then, under the experiment lock, revalidate shared prerequisites and commit one durable group reservation containing all member identities before starting any child.

   A failure during staging removes only proven unlaunched staging state. It leaves no orphan charge. Catch `IsolationError` as well as `Stop`, record the reason and return the defined incomplete status.

   Reservation does not replace the final per child verification required by item 7. If a member fails that final verification after reservation, append a terminal `not_launched` disposition with evidence that execution never began. Retain the conservative allocation debit. Report it separately from observed physical model dispatches.

   For preexisting charged rows, `abandon()` must append an explicit disposition rather than delete their only marker. Use `not_launched` only where absence of execution is established. Otherwise use the ambiguous launch path from solution 1.

   A proven unlaunched call has zero model usage. An ambiguous launch has unknown usage. Neither label permits skipping a capture that actually exists.

   **Tests:** Preserve `test_rt2_3_an_abandoned_launch_group_never_bricks_the_live_run`. Fail the third preparation, crash immediately after group reservation, and fail one member’s final launch verification. Subsequent valid work must pass ledger reconciliation, while all committed debits and actual launches remain accounted for.

4. **Authentication route certification. Closes 1 and B4, jointly with solution 5 for effective instructions.**

   **Implementation:** Expand `isolation.py:telemetry_certificate` to require a frozen authentication route manifest containing:

   * Exact executable, wrapper and payload identities.
   * Effective authentication configuration and supported disable options.
   * Credential paths and access types.
   * Evidence establishing which source supplies authentication to the execution route.
   * A trace or pinned implementation analysis bound to the actual launched payload.
   * Effective instruction discovery evidence under P5.

   Positive execution with `auth.json` and negative execution without it are necessary observations, not sufficient source attribution.

   Test `--disable secret_auth_storage` locally. If supported, include it in the frozen configuration and verify that it is effective. If unsupported, record that result. Neither accepting a flag nor reporting a feature as disabled independently proves exclusive file authentication.

   Perform the eight local `login status` checks proposed in B4: each actual worker path, empty, before and after the telemetry sequence. Require the frozen, structurally recognized “not logged in” result. Do this only after establishing that no child still uses the directory and after preserving required authentication reconciliation evidence. These checks make no model request.

   Certification must reject a route that reads account metadata from `auth.json` and then obtains credentials from a credential store. Checks at a separate `probe-empty` path cannot substitute for checks at worker paths.

   **Tests:** Simulate account indexed credential store authentication that passes both original positive and negative probes. It must fail certification. Test a credential store entry specific to one worker path, unsupported disable flags, a changed authentication branch and an incomplete access trace.

   **Minimal missing evidence:** The pack supplies no implementation or access evidence establishing exclusive authentication for the pinned execution route. Collect that evidence locally, bound to the actual binary and payload. Until then, the certificate remains false and evaluation cannot launch.

5. **Bundled startup files and instruction exclusion. Closes 33 and B6, and the instruction component of 1.**

   **Implementation:** Replace any filename pattern allowance in `SIGNED_STARTUP_FILES` with an exact manifest containing canonical relative path, content hash, file type, origin and permitted role. Reject symlinks, junction escapes, additional files and changed contents.

   `startup_instruction_files()` should return unauthorized instruction sources after applying the signed manifest and its evidence requirements. An allowed creation event is not an allowed instruction load.

   Bind discovery configuration and execution path evidence to `telemetry_certificate`. A local feature command establishes what it created during that command; it does not establish what `exec` later discovers or injects.

   An accepted `skip_host_skill_discovery` equivalent can contribute evidence only when its effective behavior is established for the pinned route. Flag recognition alone is insufficient. An input token margin may identify anomalies, but cannot establish exclusion. Equal token counts can conceal changed instruction content.

   **P5 proposed ruling:**

   > P5. For the frozen replication route, creation of vendor startup files is permitted only for individual paths and contents enumerated in a manifest approved by both signatories before freeze. The manifest shall identify each file’s origin and permitted role and shall be bound to the executable, payload, effective configuration and instruction discovery evidence.
   >
   > Permission to create a file does not authorize reading it as a skill, loading its instructions or injecting its contents into model context. Certification requires evidence establishing the effective instruction sources of the execution route. Filename patterns, a clean initial directory listing, a plain model reply and input token counts, individually or together, do not establish instruction exclusion.
   >
   > A discovery disabling option is evidence only when its effective behavior is established for the pinned route. Any changed file, additional instruction source, unexplained discovery path or unavailable required evidence prevents certification and launch.
   >
   > If bundled skill instructions are to be included, a separate prospective amendment must identify and authorize that context. A residual risk disclosure does not waive A4.2.
   >
   > Signed: Astra A

   **Tests:** Change an allowed file’s contents, add another instruction source, redirect an allowed path through a junction, and inject bundled instructions while preserving the initial listing and producing a plain reply with unchanged input token counts. All must fail certification.

   **Minimal missing evidence:** Collect the exact startup inventory and evidence for the `exec` instruction discovery and injection path. The supplied pack cannot populate or approve that manifest. Keep the launch stop until both signatories approve the evidence annex.

6. **Owner token separation. Closes RT2.6.**

   **Implementation:** Add `Isolation.verify_distinct_auth_lineage()` and call it before telemetry, at every wave gate, and immediately before worker reconstruction under the authentication lock.

   Read only the specifically identified authentication sources for the owner’s default home and the runner’s original `CODEX_HOME`, if set. Resolve canonical paths and reject aliases between those homes and the baseline or workers.

   Compare the baseline’s refresh and access token hashes with those of the owner and runner. Equal refresh or access token hashes refuse launch with exit 11 and the baseline login instruction. Record hashes only. Never copy or write owner credentials.

   An unreadable existing source, unsupported authentication representation or unexplained credential store source cannot be treated as “different.” An absent source needs an explicit absent disposition supported by the authentication source inventory.

   Record the baseline authentication file hash, token hashes, `last_refresh`, `exp` and lineage identifier before first dispatch and after every reseed. Preserve the 48 hour expiry gate. Unequal hashes are necessary evidence of separation, but do not replace the required owner performed independent login provenance.

   **Tests:** Preserve `test_rt2_6_a_baseline_sharing_the_owner_refresh_token_never_reaches_a_worker`. Test equal refresh tokens with different access tokens, equal access tokens, path aliases, unreadable owner authentication, a baseline swap after the wave gate and a correctly documented independent baseline login. Every prohibited case must stop before worker copying or a charged model call.

7. **Local probe errors and feature validity. Closes 5.**

   **Implementation:** In `worker_probe`, inspect stdout, stderr, exit status and structured error fields before authentication reconciliation. Authentication failures must be retained independently of other verdicts. Pass the actual `auth_failure` value to `Isolation.propagate`.

   On authentication failure, preserve the baseline, stop further Codex launches and reconcile remaining workers only after all in flight calls end. Do not propagate changed credentials from the failed probe.

   `record_features()` must require successful command completion, a nonempty structurally valid inventory, unique feature names and valid status values. Compare effective feature states with the frozen route expectation, including unsupported disables. Unexpected enabled tool features or an invalid response block dispatch.

   Scoring must validate the probe evidence and frozen comparison, not merely the existence of a feature record.

   **Tests:** Return authentication failure while modifying worker credentials from both `features list` and `login status`. The baseline must remain unchanged. Test nonzero exit, empty output, malformed records, duplicate feature names and an unexpected enabled feature. All must block launch without a model request.

8. **Credential redaction across refresh and recovery. Closes 6.**

   **Implementation:** `prepare_call()` and `worker_probe()` must retain prepared credential values in protected memory until capture sanitation finishes. Before reconciliation can replace any source, collect the union of prepared values and all observed postcall credential values.

   Sanitize both channels before promoting them from restricted raw storage to evidence storage. Apply the same treatment to probes and generic credential detection to Sonnet captures. A detected disclosure remains a recorded security event; redaction does not erase that finding.

   `redact.merge()` must preserve channel specific evidence:

   ```text
   attempt_uid
   channel
   original_sha256
   sanitized_sha256
   redaction_count
   redaction_categories
   ```

   Never include matched token text in logs, exceptions, fixtures or redaction metadata. Hash original bytes before sanitation.

   Recovery needs an explicit missing secret policy. If the original in memory set is lost, reconstruct it only from still available credential sources whose recorded fingerprints establish coverage. If coverage cannot be established, retain raw files within the restricted credential boundary, block evidence promotion and stop the affected recovery. Generic token patterns alone cannot certify removal of unknown opaque tokens.

   This avoids introducing a persistent copy of old authentication material merely for redaction. An independently surviving supervisor may retain the prepared secret set in memory, but its survival cannot be assumed.

   **Tests:** Emit a prepared opaque refresh token, refresh the worker and reseed the baseline before processing. No ordinary evidence artifact may contain the token, and both original channel hashes must survive. Repeat with runner death and lost prepared values; the raw stream must remain quarantined rather than be exported as sanitized evidence.

9. **Executable identity at dispatch. Closes 7.**

   **Implementation:** `isolation.py:executable_identity` must describe the actual resolution chain: launcher, interpreter where applicable, resolved target, required package payload and companion manifest. A sibling filename heuristic is insufficient.

   Call `Executables.verify()` immediately before each child spawn in `CellRun.execute`, including telemetry. Verify the resolved executable, payload, arguments, environment and relevant discovery configuration against the bound freeze.

   Close the verification to execution race through an immutable protected launch installation or platform enforced handles and permissions that prevent replacement during launch. A second hash followed by an unconstrained path lookup is not a complete fix.

   For native distributions, freeze a documented companion manifest and verify the installation against it. If the actual target or required payload cannot be inspected, refuse dispatch.

   **Tests:** Change the executable after group verification, replace a wrapper’s target in a subdirectory, alter a required package file and substitute a path between verification and spawn. Each must prevent execution or produce an immediately detected identity failure that withholds claims.

10. **Independent scoring reconstruction. Closes 10.**

   **Implementation:** Make `_rejudge` reconstruct, from sanitized captures and frozen predicates, every derived field used in a claim:

   ```text
   event and authentication verdicts
   terminal outcome
   raw usage counters
   inclusive and uncached input
   output and reasoning accounting
   charged and additive tokens
   cache and reasoning certification
   usage completeness and validity
   answer and proposal provenance
   ```

   Compare reconstructed values with stored records. A mismatch is an artifact problem and withholds dependent claims. Do not silently correct the report while presenting the artifact chain as valid.

   Preserve the exact captured bootstrap proposal bytes and their location in the captured response. Admission must derive its AST from that proposal using the frozen parser. A canonical AST hash may supplement, but cannot replace, provenance to the original response. Reproduce classification application, admission, audit decisions, quarantine and adoption chronology.

   `_cell_chain` must check eligibility at the time each answer was produced. Warm C may use only rules actually adopted through the permitted cold C path. A rule later quarantined cannot leave an answer retrospectively eligible without the prescribed audit disposition.

   `_freeze_problems` must compare each actual launch manifest against the run’s bound freeze, including executable resolution, payload, exact argument vector and environment. Normalize only the numbered slot substitutions explicitly authorized by the freeze.

   Include predecessor evidence from solution 2 and channel provenance from solution 8.

   **Tests:** Independently alter charged tokens, usage status, additive attribution, reasoning certification, cache certification, a proposal to another admissible AST, executable identity, arguments, audit disposition and warm C adoption history. Each alteration must withhold claims without modifying the original capture.

11. **Multiple turns in one execution stream. Closes RT2.4.**

   **Implementation:** In `judge_codex`, count `turn.started` and `turn.completed` events before extracting usage. More than one of either makes the stream uncertain and its accounting incomplete. Apply the same guard through `_rejudge`.

   `_turn_usage` must never silently select the last completion. Preserve all observed counters for diagnostics, but do not claim a certified sum without a separately established interpretation of those counters.

   Missing or inconsistent turn lifecycle evidence also requires an explicit incomplete disposition. Preserve any delivered answer as terminal, so accounting uncertainty cannot authorize resending it. Independently demonstrated invalid counters remain invalid rather than being downgraded to merely incomplete.

   **Tests:** Preserve `test_rt2_4_a_stream_with_two_turns_never_drops_the_first_turns_tokens`. Test two starts, two completions, a duplicated completion, a missing completion and an otherwise valid single turn. The two turn example cannot report complete usage of 150.

12. **Durable timing coverage. Closes 14.**

   **Implementation:** Open and flush a work window before the first included operation in `_run_locked`. Record its scope, clock source, process or boot identity and start timestamp. Include retries, required local processing, reconciliation and result persistence according to one frozen timing definition.

   Close the window only after the defined result delivery boundary, including durable result persistence. A resume must reconcile an open window before creating another. It cannot substitute a short reconstruction window for earlier work.

   Where reliable timestamps establish the complete interval, recover it. Otherwise record a duration interval or mark timing incomplete. A longer estimated duration is not automatically conservative: increasing reference A’s time can make C look better.

   If bounded timing is used, apply the bounds against the claim. For example:

   ```text
   warm makespan pass requires upper(C) <= 0.9 * lower(A)
   magnitude timing pass requires lower(A) / upper(C) >= 1.6
   ```

   Without defensible bounds, affected comparisons remain inconclusive. Do not sum overlapping synchronized windows as if they were sequential.

   **Tests:** Crash after the final successful attempt but before window close, and after result persistence but before close persistence. Test runner restart, overlapping groups and a wall clock discontinuity. Earlier call durations and applicable local work must remain covered, and uncertainty in A must never improve a passing comparison.

13. **Quota freshness and its available source. Closes 31, B8 and RT2.5.**

   **Implementation:** Replace the separate percentage and file time lookups with one `quota.py` observation parser returning:

   ```text
   source identity and hash
   account and quota bucket identity
   observation timestamp
   primary used_percent
   freshness and coverage evidence
   parse status
   ```

   Use the timestamp of the quota observation, never file modification time. Select the latest relevant observation event before validating its value. A malformed latest observation cannot cause fallback to an older valid value.

   Reject nonnumeric values, booleans, NaN, infinity and percentages outside `[0, 100]`. Reject missing or unparseable timestamps, unexplained future timestamps, account mismatches and unestablished quota bucket association.

   Apply the same gate immediately before every synchronized Codex dispatch group, including telemetry. The source must establish that its reading covers all previously completed replication groups. A recent timestamp on a cached value is insufficient.

   **P3 proposed ruling:**

   > P3. Retain `--ephemeral`. Before each synchronized Codex dispatch group, require an authoritative quota observation attributable to the replication account and applicable primary quota bucket. Its source, account association, timestamp semantics and freshness behavior shall be documented and approved in a frozen source manifest.
   >
   > The observation must cover all previously completed replication groups. Use the observation timestamp and the source’s established coverage semantics, not file modification time or the timestamp of an unrelated event. Unknown, stale, malformed, mismatched or out of range observations prevent dispatch. Primary usage of at least 80 percent stops Codex dispatch.
   >
   > No additional model call is authorized solely to obtain a quota observation. A local command making no model request may obtain an observation if its authority and freshness are established. An already authorized substantive preparation or review call may supply incidental quota evidence only when it satisfies the same source, account and coverage requirements and is counted under its actual A4.13 category. It must not be added, repeated or relabeled solely to refresh quota evidence.
   >
   > This ruling creates no quota reading allowance and no stale reading or headroom exception. If no qualifying observation is available, Codex remains stopped.
   >
   > Signed: Astra A

   This rejects B8 option a and option c. Option b is acceptable only for an independently required, authorized and correctly counted substantive call. It is not a scheduling requirement or a workaround that spends review calls to refresh quota.

   **Tests:** Preserve `test_rt2_5_the_codex_quota_freshness_gate_needs_a_new_reading_not_a_new_mtime`. Test unrelated appended events, malformed latest readings, another account, a different quota bucket, negative values, NaN, a cached observation with a recent wrapper timestamp and crossing 80 between groups. Every affected dispatch must stop.

   **Minimal missing evidence:** The pack identifies no demonstrated source that supplies qualifying observations after ephemeral groups without an additional model call. Collect local evidence for an available authoritative source, or establish incidental evidence from an already required call. Until then, P3 is signed as a rule but its operational prerequisite remains unsatisfied.

14. **Transport diagnostics and the Code Mode startup notice. Closes 32 and B5.**

   **Implementation:** Keep separate `SIGNED_TRANSPORT_NOTICES` and `SIGNED_CLI_NOTICES` registries. Bind each entry to the pinned route, complete outer schema, exact item fields and complete message grammar.

   Do not use unrestricted `startswith` matching. Where a transport message has variable fields, use a fully anchored grammar with enumerated field types and limits. Reject arbitrary suffixes, extra fields and unapproved variants.

   Authentication detection runs independently and cannot be suppressed by notice classification. Tool execution and unresolved execution evidence remain sticky across the entire stream.

   **P1 proposed ruling:**

   > P1. For codex-cli 0.160.0 on the frozen route, only the reconnect and WebSockets fallback diagnostics represented by complete event fixtures and fully specified message grammars approved by both signatories before freeze may receive the transport notice exception.
   >
   > Matching requires the complete approved event schema and complete approved message grammar. Unrestricted prefix matching is prohibited. Variable fields are permitted only where their types and bounds are explicitly enumerated in the signed fixture manifest.
   >
   > The transport notice exception requires a stream containing no tool item. It does not establish the absence of execution through any other evidence channel. Authentication failures retain their stop disposition. Actual execution, external reads and unresolved execution uncertainty retain their A4.3 dispositions. Other errors remain uncertain.
   >
   > An empty approved fixture manifest means strict classification with no transport notice exception.
   >
   > Signed: Astra A

   **P4 proposed ruling:**

   > P4. Keep `code_mode_host` disabled in the frozen arguments. An `item.completed` event may be classified as a plain CLI startup notice only when its outer schema matches the approved fixture, its error item contains exactly the approved `id`, `type` and `message` fields, and its complete message equals an approved pinned diagnostic stating that Code Mode is unavailable because its host is disabled.
   >
   > The complete diagnostic and permitted identifier syntax shall be archived and approved by both signatories before freeze. Prefixes and paraphrases do not authorize a match. Additional fields, additional text and unapproved message variants do not qualify.
   >
   > This exception applies only to the specified notice. It does not exempt accompanying tool activity, execution failures, authentication failures or other errors.
   >
   > Signed: Astra A

   **Tests:** Accept the complete approved fixtures. Reject altered outer schemas, extra item fields, malformed IDs, appended text, message variants and authentication errors inside transport diagnostics. Accompanying executed tool evidence must still invalidate efficiency.

   **Minimal missing evidence:** The pack gives message prefixes, not the full approved fixtures. Extract complete diagnostics from existing archived captures or a demonstrated local command requiring no model request. Do not spend a new model call merely to populate the fixtures. P4 cannot authorize a notice until its annex is complete and approved.

15. **Unknown usage and orphan execution uncertainty. Closes B7.**

   **Implementation:** Preserve separate usage states such as `complete`, `incomplete`, `unverified` and `invalid`. Never convert unknown cost to zero in a gate total. Reports may show a known subtotal, but must label it incomplete.

   A successful retry adds its own cost. It does not replace the cost of the earlier attempt. Conversely, a recovered interrupted attempt with independently established complete usage need not remain incomplete merely because the runner died.

   **P2 proposed ruling:**

   > P2. Unknown usage remains incomplete. An authorized infrastructure reserve may complete correctness observations, but successful retry usage does not replace or bound missing usage from an earlier attempt. Every attempt retains its own physical allowance and accounting disposition.
   >
   > Relevant token comparisons remain inconclusive until missing usage is independently established through evidence applicable to that attempt and the frozen accounting predicates. A runner interruption alone does not prevent accounting recovery when such evidence exists.
   >
   > No gate may substitute zero for unknown reference cost or substitute a successful retry’s cost as an upper bound for unknown cost in an arm under test. Such values may be shown only as explicitly hypothetical sensitivity calculations and cannot support a passing gate or headline.
   >
   > An attempt that may have launched but lacks sufficient readable capture evidence to resolve execution is uncertain under A4.3 and enters the experiment wide leakage disposition. Proven absence of launch is a distinct disposition. Complete recovered evidence is judged normally regardless of the earlier interruption label.
   >
   > Signed: Astra A

   B7’s proposed retry bound is rejected because the failed attempt may have consumed more than the retry. This is a signed strict resolution, not an unresolved protocol choice.

   **Tests:** Give a failed attempt unknown usage and its retry complete usage; the affected token comparison must remain inconclusive. Recover complete original accounting and verify that both costs are included. Remove the original capture after possible launch and require global leakage. Prove no launch and verify zero model usage without inventing an interrupted execution.

16. **Freeze readiness and telemetry preflight. Closes B1.**

   **Implementation:** Add one `freeze_command` readiness validator used again by live telemetry preflight. Require:

   * Recorded decisions and signatures for P1 through P5. P1 may explicitly select an empty strict registry. P2 uses the strict ruling above.
   * The complete P4 notice fixture for this route.
   * P5’s exact startup manifest and instruction exclusion evidence.
   * Authentication route evidence and distinct baseline lineage.
   * Executable and payload manifests.
   * A documented P3 observation source with established semantics.
   * Clean experiment accounting and any signed replacement disposition.
   * Valid local feature and startup inventory results.

   Keeping `code_mode_host` disabled is the selected solution. There is no permission here to add it to `SIGNED_OMITTED_DISABLES`.

   Before any telemetry reservation, run the local feature, inventory, authentication and quota preflight. A valid P5 manifest may explain specific generated files. Any remaining unauthorized instruction source blocks telemetry before a charged call. The local commands must be established as making no model request.

   Freeze readiness and live telemetry certification are separate. Freeze must not demand a model observation that can only occur afterward, but it must reject known deterministic failures and missing protocol authority. Successful local preflight does not guarantee successful telemetry.

   **Tests:** With each required signature, fixture or evidence manifest absent in turn, freeze must refuse. With an unexpected startup skill, failed features response, shared owner token or stale quota, telemetry must refuse without reserving or dispatching a model call. Test that an allowed file does not authorize a different file with the same name but changed contents.

The ordered implementation plan is:

1. Implement the experiment ledger, global identities, lock and group reservation transaction.
2. Implement durable raw capture, process identity, recovery and terminal batch preservation.
3. Implement redaction ordering and recovery quarantine.
4. Implement authentication lineage checks, probe validation, route certification and exact executable binding.
5. Implement the independent scorer, multiple turn guard and durable timing coverage.
6. Obtain Opus B’s acceptance of the exact P1 through P5 texts. Collect the missing local authentication, instruction, notice and quota evidence, then approve and bind their annexes.
7. Implement freeze readiness and telemetry preflight using those signed predicates.
8. Run the unchanged acceptance suite, all six existing round 2 red team reproductions, the new regressions above and a fake end to end replacement and recovery exercise. Record actual results and remaining unrelated suite failures separately.
9. Update build notes and cumulative preparation reporting, including this co-solver call under its actual dispatched category. Commit only the verified harness and protocol changes. Do not push without authorization.
10. Freeze only when the readiness validator passes. Spend live telemetry calls only within the existing allocation and after its local preflight succeeds.

Once these changes pass the specified local checks, the evidence annexes are complete, and Opus B has countersigned the rulings, I would accept closure of **every supplied blocker without another full council round**. A focused verification against this closure checklist is sufficient.

That acceptance is conditional on faithful implementation. It does not waive missing evidence. Authentication source attribution, instruction exclusion, complete notice fixtures and a usable quota observation source remain unestablished by this pack. If any remains unavailable, the harness must preserve the launch stop.