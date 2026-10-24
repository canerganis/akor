# Council build review: OZ map clean replication, round 3

I do not sign the supplied `fc60457` build. The fixes address several round 2 defects, including recovery of captured terminal outcomes, unique attempt identities and reconstruction of per call accounting. However, process recovery, reservation durability, timing bounds, scoring provenance and certification prerequisites still have gaps. The freeze correctly refuses today, but its readiness validator is not sufficient to establish that the signed conditions have been satisfied. This is a static review of the supplied blind pack. I did not independently rerun tests or verify Git history, read operation content, make evaluation calls, or change files. Paths below are relative to `bench/ozmap_rep/` unless stated otherwise.

1. BLOCKER A4.1 and A4.2, `rulings.py:ruling_problems`, `configuration_problems`, `run.py:freeze_command`, `verify_freeze`. **The current freeze refusal is correct, but its replacement by a passing check would not be sufficient.** The validator checks ruling file hashes and signature strings, then checks that configuration slots are populated. It does not bind the startup manifest, P4 schema and identifier predicate, or P3 source and coverage predicate to the actual approved annexes. A signed P5 text plus a different, nonempty startup manifest can satisfy these checks. D2 and D5 certification are not independently required artifacts.

   **Fix:** introduce a structured approval manifest binding each required ruling to its approved annex hashes and executable predicate configuration. Require the D1 attribution evidence, D2 instruction evidence, P3 source and lifecycle certification, P4 annex and P5 manifest. Verify those bindings at freeze, live verification and offline scoring. P1 through P5 and D1 remain unsigned prerequisites until Opus B confirms the exact texts.

   **Test:** retain valid signed ruling files while substituting each annex or predicate independently. Every substitution, missing certification and changed evidence file must prevent freeze and dependent launch.

2. BLOCKER A4.2, `isolation.py:telemetry_certificate`, `scrambled_auth`, `run.py:TelemetryRun.arm`. **Round 2 item 1 and joint D1 are partially closed.** The file store argument, disabled `secret_auth_storage`, eight emptied worker path statuses and account preserving scrambled token probe address the previous counterexample. However, `auth_source` remains a statement generated from configuration. The required pinned implementation analysis or complete credential access trace is absent.

   **Fix:** obtain and bind evidence establishing exclusive use of the prepared file credentials by the actual authenticated execution route, including its executable and payload identity. A trace must cover relevant alternative credential access mechanisms, not merely record an `auth.json` read. Keep token contents outside evidence.

   **Test:** an account indexed alternative credential source must fail certification. A certificate without the approved attribution artifact, or with a different binary or payload, must fail. D1 remains blocking for launch.

3. BLOCKER A4.2, `isolation.py:startup_manifest`, `startup_instruction_files`, `Isolation.finish`, `run.py:TelemetryRun.arm`. **Round 2 item 33, joint P5, D2 and D4 remain open.** Exact path and content comparison is an improvement, but the loader accepts entries without validating canonical paths, file types, origins or permitted roles. Inventory hashing follows filesystem objects without rejecting symlinks or junction substitutions. The certificate also lacks the required effective instruction context check. Ordinary evaluation inventories are not checked against P5, and their hashes are not durably retained in the attempt evidence.

   **Fix:** validate the full approved manifest schema and filesystem object identity without following unauthorized links. Preserve inventories and enforce the applicable runtime rules on every call. Bind a verification procedure proving complete effective instruction sources and comparing them with approved base instructions and exact harness input. Static evidence may establish this only where it actually proves the relevant behavior.

   **Test:** reject a matching content symlink, a junction escape, changed file type, extra instruction file, an extra effective instruction source, and a violation appearing only during evaluation. Missing request completeness evidence must prevent certification. D2 and the P5 manifest are launch blockers.

4. BLOCKER A4.12, `quota.py:_find_rate_limits`, `read_file`, `coverage_gate`, `run.py:CellRun.codex_quota_gate`. **Round 2 item 31 and joint D5 are only partially closed.** Event timestamps replace file modification times, percentages are constrained, and the gate runs before each group. Nevertheless, missing account identity is accepted, quota bucket identity is not checked, and a worker reading is accepted without validating its causal coverage or future timestamp. A malformed latest `rate_limits` value that is not a dictionary is skipped, allowing an earlier reading to survive. The first group can use an undated observation, contrary to P3’s missing evidence rule.

   **Fix:** bind and implement the approved P3 source manifest. Require established account and bucket attribution, timestamp semantics, freshness and causal coverage for owner and worker observations. Select malformed latest candidate events before validation rather than skipping them. Reject unestablished coverage, including at the first group.

   **Test:** reject missing account attribution, wrong bucket, undated first reading, future worker reading, timestamped cached data, a malformed latest scalar `rate_limits`, and a sibling reading that does not cover another completed attempt. D5 remains blocking.

5. BLOCKER A4.2 and A4.3, `events.py:signed_cli_notice`, `config.py:SIGNED_CLI_NOTICES`, `rulings.py:configuration_problems`. **Round 2 item 32 and joint P4 are implemented as an inactive mechanism, not closed as a launch prerequisite.** The complete message comparison and exact schema predicate are appropriate. The approved outer event fixture and identifier syntax are still missing, and both signatures are required.

   **Fix:** archive and approve the complete event annex, bind its exact predicate configuration under item 1, and keep `code_mode_host` disabled.

   **Test:** the approved fixture must be plain. Added fields, changed identifiers, appended text and message variants must not qualify. Accompanying tool events must retain their own verdict. The P4 annex remains blocking because the stated route otherwise emits an uncertain event on every execution.

6. OK A4.3, A4.7 and A4.11, `events.py:_signed_transport`, `classify_stream`, `score.py:_unknown_usage_observation`, `gates.py:evaluate`. **Joint P1 and P2 are correctly reflected in the principal predicates.** The transport registry remains empty. Hypothetical retry substitution is labeled and is not supplied to the gates. Unknown usage is not replaced by retry usage. Neither strict policy inherently prevents a valid run, although P1 makes a qualifying reconnect invalidate efficiency and P2 leaves affected token comparisons inconclusive. Their required countersignatures remain covered by item 1. Incomplete stream recovery still needs item 10.

7. OK A4.3 and A4.5, `run.py:recover_inflight`, `CellRun.run_batches`, `score.py:score_run`, `redteam/test_redteam_r2.py:test_rt2_1_execution_captured_before_the_runner_died_is_still_leakage`. **D-R2-1: accept the proposed test change.** An executed call recovered from its committed capture must not be converted into a retryable interruption.

   Replace the resumed `EXIT_OK` assertion with `EXIT_INCOMPLETE`. Replace the target’s `interrupted` assertion with `executed`. Replace the successful `.t1` assertion with an assertion that `.t1` is absent. Add `recovered_from == 'capture'` for the target row. Preserve the existing leakage detection assertion. The supplied failure reflects obsolete retry expectations, not a reason to restore the resend behavior.

8. OK A4.2 and A4.12, `config.py:FROZEN_ARGS`, `isolation.py:argv_check`, `acceptance/test_a4_2_argv.py`, `acceptance/test_cli_plan_and_cells.py`. **D-R2-2: uphold the current acceptance assertions for this build.** Keeping `--ephemeral` conforms to the currently bilateral A4.2 text. No assertion changes are authorized now.

   My P3 permission to omit the flag is substantively a prospective exception to A4.2’s argument list and persistence restriction. The joint document’s statement that no A4 change is involved must be corrected. P3 says “may omit”, so retention remains permissible if certified owner observations satisfy its quota requirements. Omission requires both signatures and the certified lifecycle and source manifest first. A later activation commit must explicitly revise the frozen head assertions and the removal mutation for the authorized route, while testing that uncertified omission still fails.

9. BLOCKER A4.2 and A4.3, `run.py:CellRun.after_group`, `recover_inflight`, `_wait_gone`, `_kill_tree`. **Round 2 item 3 and the joint process termination solution are not fully closed.** `after_group()` excludes an unsettled child from `workers` and can propagate another worker’s changed authentication before processing the unsettled failure. That changes the baseline while a sibling may still be running. `_wait_gone()` establishes parent disappearance, not process tree termination. Recovery’s initial alive check also excludes markers already represented by attempt rows.

   **Fix:** establish termination for every relevant process tree before reconciliation, propagation, cleanup or slot reuse. If any child is unsettled, preserve the baseline and relevant homes, retain markers and stop Codex. Use a supervised process tree identity or equivalent enforceable lifecycle. Check recorded markers as well as orphan markers.

   **Test:** one worker refreshes while another remains alive after a communication failure. The baseline must remain unchanged. Also test a recorded parent with a surviving descendant and PID reuse. No home cleanup or new launch may occur before termination is established.

10. BLOCKER A4.3, A4.7 and A4.11, `run.py:_recover_stream`, `recover_inflight`, `judge_codex`. **The captured terminal outcome fix closes the original resend example, but stream existence is still treated as sufficient recovery evidence.** `spawn()` creates raw files before `Popen`. A terminated child can leave empty files or a syntactically valid prefix. Recovery promotes those files and `judge_codex()` can classify them as a plain infrastructure failure, permitting retry without recording execution uncertainty. The joint decision explicitly rejected file existence as proof of completeness.

   **Fix:** distinguish complete terminal evidence from empty, truncated or lifecycle incomplete streams. A possible launch whose execution cannot be resolved must remain uncertain under P2 and A4.3. Preserve partial counters as diagnostics. Complete recovered terminal outcomes must remain nonretryable.

   **Test:** recover empty raw files, a stream ending after `turn.started`, a truncated final event and a complete terminal stream. The first three must not become clean infrastructure failures; the last must retain its terminal outcome without resend.

11. BLOCKER A4.1, A4.3 and A4.5, `run.py:CellRun.reserve_group`, `recover_inflight`, `ledger_problems`, `superseded_terminal_batches`. **Round 2 item 9 and joint B2 are partially closed.** UUIDs, experiment locking and staging before reservation fix the reported ordinary paths. Reservation is still multiple marker writes followed by multiple ledger appends. A crash between them leaves reserved markers that recovery converts to charged attempts without adding the missing ledger rows. `ledger_problems()` checks ledger rows missing from attempts, but not the reverse. Replacement accounting can consequently omit those debits. Replacement dispatch also checks terminal batches for the requested cell but does not enforce predecessor stop and safety kill state before launching other cells.

   **Fix:** commit a durable group reservation journal before spawning, recover every member idempotently into the authoritative ledger, and verify both directions of ledger reconciliation. Preserve predecessor markers, relevant stops and safety kills in launch gates, not only in the report.

   **Test:** crash after each marker and ledger append, recover, then migrate directories. Every reserved UID must remain counted exactly once. A predecessor safety kill or unresolved potentially running child must block replacement dispatch.

12. BLOCKER A4.2, `run.py:Executables.verify`, `guard`, `recheck`, `CellRun.run_batches`. **Round 2 item 7 and the joint executable binding solution are partially closed.** The explicit package manifest improves coverage. However, hashing and collection of file statistics happen before acquiring the write guard. A substitution after hashing but before statistics collection can become the recorded statistics baseline; subsequent checks compare those statistics while the guard protects the substituted bytes.

   **Fix:** acquire protection and then verify the protected files’ contents against the frozen identity, retrying or refusing if manifest discovery changed. Keep protection until all relevant children terminate. Apply the same protection to local credential and feature probes. An unsupported launcher or interpreter resolution chain must fail closed.

   **Test:** substitute a manifest member between its hash read and statistics collection, including a replacement preserving size and timestamp. No child may start. Retain the existing wrapper target and write denial tests.

13. BLOCKER A4.2, `run.py:run_local`, `CellRun.worker_probe`, `probe_marker`, `recover_inflight`. **Round 2 item 5 is closed for ordinary probe returns, but the crash path remains unsafe.** `run_local()` suppresses PID journal exceptions and does not provide the model call path’s durable raw capture and termination handling. Recovery exempts local probe markers from the ambiguous PID rule and skips reconstruction of their output. A probe that changed authentication and reported failure before a runner crash can therefore be reconciled without that failure.

   **Fix:** give local probes the same durable process identity, protected output recovery and termination guarantees. Reconstruct authentication failure before reconciliation. A missing PID after possible startup must stop Codex and preserve state.

   **Test:** crash a feature or login probe after it changes authentication and emits an authentication failure. Also fail its PID journal while it remains alive. Neither case may propagate authentication, erase its home or permit another dispatch.

14. BLOCKER A4.2, `run.py:CellRun.gates`, `reserve_group`, `isolation.py:Isolation.prepare`. **The expiry gate is not bound to the generation actually reserved.** A reseed after `gates()` but before preparation can supply a different baseline to every member. `reserve_group()` verifies agreement with that new hash but does not establish that its token passed the 48 hour gate. A local probe propagation can likewise change the baseline after the recorded wave check.

   **Fix:** validate inventory, token separation and expiry for the actual prepared baseline generation at reservation under the authentication lock. Record that generation’s hash, `last_refresh` and expiry. A later generation change must prevent dispatch.

   **Test:** replace the baseline after the initial gate with a distinct token expiring in one hour, then prepare all members from it. Reservation must fail without launching or overwriting the reseed.

15. BLOCKER A4.2, `run.py:CellRun.secrets`, `worker_probe`, `redact.py:channels`, `score.py:score_run`. **Round 2 item 6 is substantially improved but not fully closed.** Prepared credentials are retained and ordinary captures receive per channel hashes. However, local probe disclosures are only appended to `probe-disclosures.jsonl`. The scorer never reads that file, and certification does not reject it. A successful feature probe can disclose a credential on stderr, be sanitized, and still leave isolation reported as passed.

   **Fix:** make every probe disclosure a persistent isolation failure consumed by telemetry certification and scoring. Preserve per channel original and sanitized hashes for probes as well. Validate capture metadata against attempts rather than trusting only the attempt’s disclosure boolean.

   **Test:** emit a prepared opaque token on stderr while returning a valid feature inventory or successful login status. No token may escape the credential boundary, and isolation and certification must fail even if the attempt disclosure flag is later altered.

16. BLOCKER A4.1, A4.7 and A4.8, `score.py:_rejudge`, `_attempt_ops_tokens`, `_cell_chain`, `_rule_asts`, `_launch_problems`. **Round 2 item 10 is partially closed.** The shared accounting function correctly reconstructs the listed per call fields, and captured proposal bytes are checked. Important inputs to claims remain trusted: `records` controls allocation of costs to R, `job_ids` supplies the answer mapping, and the recorded audit dictionary supplies the set of audits checked. Deleting an audit avoids its verification. Warm C eligibility still comes from bootstrap acceptance without enforcing permitted cold C history. Full launch environment and channel provenance reconstruction promised by the joint decision is absent.

   **Fix:** reconstruct requested jobs and operation counts from the frozen schedule and captured prompt, derive the required audit set independently, enforce cold C eligibility for warm C, reproduce complete admission dispositions, and validate the required launch and channel evidence. Do not silently repair mismatches.

   **Test:** independently alter only `records`, reorder `job_ids`, delete an audit, substitute a bootstrap accepted but cold quarantined rule into warm C, alter admission metadata, and change launch environment evidence. Each mutation must withhold dependent claims.

17. BLOCKER A4.10 and A4.11, `run.py:recover_inflight`, `close_dead_windows`, `score.py:_window_spans`, `cell_summary`. **Round 2 item 14 and the joint timing solution are partially closed.** Recovery closes dead invocation windows before checking whether their children remain alive. A first resume can therefore assign an upper endpoint while work is still executing. A later resume preserves that already closed window. `_window_spans()` checks only attempt starts, so it does not detect work ending outside the purported upper bound. Nearest millisecond rounding also occurs before gate evaluation and can change a boundary result.

   **Fix:** establish termination before assigning recovery bounds. Include all established durable work endpoints and validate coverage against the owning invocation. Require defensible clock ordering. Preserve full precision for gates, or use outward rounding of bounds; round only display values.

   **Test:** resume while an orphan child is alive, let it finish, then resume again. Its complete work must fit the final upper bound. Add an attempt ending beyond its window and threshold cases separated by less than a millisecond.

18. CHANGE A4.3 and A4.7, `events.py:classify_stream`, `run.py:_turn_usage`, `account_usage`. **RT2.4 is closed for the reported two turn undercount, but the joint extension is incomplete.** Multiple turns become uncertain and their aggregate usage is incomplete. Returning `None` nevertheless discards observed counters from accounting diagnostics, including independently demonstrable negative counters or other contradictions.

   **Fix:** retain every observed usage object as diagnostics and preserve established invalidity independently of whether an aggregate is certifiable.

   **Test:** combine two completed turns with a negative counter or cached input exceeding input in one turn. The report must retain both the uncertainty and the demonstrated accounting failure.

19. CHANGE A4.6, A4.10 and A4.11, `run.py:CellRun.interpret`, `_settle`. **Round 2 CHANGE 15 remains open, as the build notes acknowledge.** Ordinary per job failures and unresolved audits can still produce `DONE.json` and exit zero because settlement examines batch outcomes rather than required resolution.

   **Fix:** require expected job coverage and required audit resolution for `DONE`. Terminal incomplete results must receive `SETTLED`, remain nonretryable and not satisfy completeness dependencies.

   **Test:** a syntactically valid response with one failed job, and a separate unresolved audit case, must return incomplete and fail a dependent cell’s prerequisite.

20. CHANGE A4.10 and A4.11, `score.py:_cell_chain`, `gates.py:_incomplete`. **Round 2 item 17’s incompleteness protection remains, but the new scorer introduces a disposition mismatch.** The runner retains current wave rule answers when an audit is inconclusive and blocks warm reuse. `_cell_chain()` now treats those same retained answers as artifact violations because the audit did not agree. Missing audit evidence should make the affected comparison inconclusive under the stated policy, rather than manufacture a provenance mismatch.

   **Fix:** align runner and scorer dispositions. Keep unresolved audit observations incomplete, enforce the prohibition on later reuse, and reserve artifact invalidity for actual inconsistencies or unauthorized use.

   **Test:** an unresolved audit must prevent claims and warm reuse without creating an artifact violation solely because the runner retained the permitted current wave observation.

21. CHANGE A4.10, `gates.py:boolq_gate`, `materials_gate`, `pooling_gate`, `score.py:cell_summary`. **Opus C4 remains unadopted.** Aggregate correctness counts cannot identify newly introduced errors offset by corrected errors elsewhere. In particular, the BoolQ check named `no_added_gold_errors` currently establishes only no increase in the total error count.

   **Fix:** report matched job error transitions and use the frozen interpretation of added errors explicitly. For the literal BoolQ requirement, require no C error on a job A answered correctly. Preserve aggregate correctness reporting separately.

   **Test:** A and C each make one error on different jobs. The new error must be reported and must not pass the literal no added error predicate.

22. CHANGE A4.7 and A4.11, `usage.py:decode_sonnet`, `run.py:account_usage`. **Round 2 CHANGE 21 remains open.** Negative counters and contradictions accompanied by a missing counter are still reduced to `incomplete`, hiding demonstrated invalidity.

   **Fix:** collect missing fields and known contradictions independently, with established invalidity taking precedence.

   **Test:** test every negative Sonnet counter and cached input greater than input with missing output. Scoring must retain an accounting failure.

23. BLOCKER A4.3, A4.7 and A4.9, `run.py:judge_sonnet`, `events.py:classify_claude`. **The supplied red team observation about Sonnet remains unaddressed.** The harness still delegates route and lifecycle interpretation to the adapter that the pack reports accepts missing turn fields and can suppress the additional model check through the parent’s `OZ_MODEL` environment. The sanitized child environment does not constrain the adapter running in the parent.

   **Fix:** independently require the frozen Sonnet model identity, a supported complete turn envelope and valid tool or permission evidence. Remove dependence on parent environment variables for the evaluated route’s identity. Missing evidence must not qualify as a complete plain call.

   **Test:** vary parent `OZ_MODEL`, add a second model usage entry, and omit or corrupt lifecycle and permission fields. None may produce a complete, plain, certified single route evaluation.

24. CHANGE A4.12 and A4.13, `run.py:snapshot_preparation`, `score.py:score_run`, `render_md`. **Round 2 CHANGE 22 remains open.** Current counts and physical versus analytical views are useful, but preparation breakdowns by role and category, attributable driver quota evidence and cumulative experiment token costs are absent. Unknown usage still appears as zero contribution to numeric totals without a completeness qualification on those totals.

   **Fix:** report those breakdowns, distinguish known partial sums from complete totals, and reconcile costs across directories by attempt UID. Record this review and subsequent preparation calls in the authorized ledger.

   **Test:** append preparation entries after initialization, include predecessor calls and an unknown usage attempt, and verify complete versus partial totals without double counting shared bootstrap.

25. OK A4.4, A4.5 and A4.13, `budget.py:capacity`, `Budget.charge`, `analytic_calls`, `run.py:schedule`, `worst_case_calls`, `config.py:ALLOCATIONS`, `EVAL_CAPS`. **Round 2 items 23 and 24 remain closed at the arithmetic level.** The formulas, nominal allocations, two reserves per allocation, permitted reserve purposes and evaluation caps of Codex 62 and Sonnet 40 conform. Bootstrap is one physical call charged fully to both analytical arms. The supplied scheduler exercise stays within the bounds. Preparation cap authority is supported by the supplied prior review of signed A4.13, rather than independently reverified here. Durable experiment enforcement still needs item 11.

26. OK A4.1 and A4.6, `bootstrap.py:assess`, `validate_classification`, `admission_report`, `run.py:CellRun.run_bootstrap`, `score.py:score_run`. **Round 2 items 16 and 25 remain structurally closed.** Bootstrap error invalidation requires both membership in R and a proposed rule. Other errors remain measured. Malformed bootstrap answers remain completion failures with proposals retained as observations. Classification validation distinguishes invalid classification from valid empty R, and admission outside R is reported without revising R. Semantic classification remains subject to the independent blind attestation.

27. OK A4.7 and A4.11, `usage.py:decode_codex`, `decode_codex_checked`, `certificate_authority`, `Certificate.applies`, `tokenizer.py:count`, `score.py:score_run`. **Round 2 items 19, 20 and 26 remain closed for the stated predicates.** Inclusive input accounting, output reasoning inclusion, missing counter handling, certificate authority and applicability, and pinned tokenizer behavior are preserved. Positive uncertified cache remains unverified. Additive sensitivity rebuilds operation and R totals separately. The scorer now reconstructs per call accounting through `account_usage`; operation attribution remains subject to item 16.

28. OK A4.10 and A4.11, `gates.py:materials_gate`, `boolq_gate`, `pooling_gate`, `magnitude`, `claims`. **Round 2 items 18 and 27 remain closed at the gate level, subject to the evidence defects above and C4.** Materials use tokens per correct job, BoolQ and pooling use total tokens, pooling requires strict token improvement, and cold materials makespan is descriptive. The new bound orientation correctly uses the tested arm’s upper duration and the reference arm’s lower duration. Magnitude is withheld before ratios on invalidity or safety kill. Missing relevant evidence prevents passing claims.

29. OK A4.2, A4.3 and A4.5, `run.py:CellRun.run`, `exclusive`, `TelemetryRun`, `telemetry_failures`, `judge_codex`, `judge_sonnet`, `events.py:_aggregate`, `_present`, `config.py:DISABLE_FEATURES`. **Previously closed round 2 items 2, 4, 8, 11, 12 and 13 retain their principal fixes.** Locks precede ordinary cell work. Telemetry uses the common charged lifecycle and retains failures. Supported disabling of `code_mode_host` is represented honestly. Execution evidence is sticky, zero exit status establishes execution, and ordinary terminal replies or tool outcomes are not retried because of a timeout or nonzero exit. These approvals do not cover the recovery and local probe defects identified above.

30. OK A4.2, `isolation.py:token_separation_problems`, `Isolation.prepare`, `Isolation.propagate`, `run.py:CellRun.separation_gate`, `lineage`. **RT2.6 and the corresponding ordinary authentication protections are addressed.** Token hashes are compared against the owner and runner homes, existing unreadable authentication documents cause refusal, reconstruction performs the check under the lock, and evidence records hashes. Propagation checks the prepared baseline generation and rejects older authentication. The harness does not ordinarily write the owner baseline except through propagation. Owner login provenance remains required operational evidence; unequal tokens alone do not prove how the baseline was seeded.

31. CHANGE A4.1, A4.2 and A4.5, `docs/design/ozmap-replication-2026-10-24/build-notes.md`, `run.py`, `isolation.py`. **Round 2 CHANGE 34 is only partially closed.** Of the eight new readings, reading 1 is incomplete for local probes and process trees; reading 2 needs complete reservation and predecessor reconciliation; reading 3 needs protection before content verification; reading 4 correctly retains A4.2’s flag; reading 5 is not justified by strict P3; reading 6 correctly preserves ambiguous Sonnet markers without automatically stopping Codex; reading 7 reasonably excludes id token equality alone; reading 8 conservatively retains raw mismatch as uncertainty.

   **Fix:** revise the dispositions and pending evidence section to match the fixes and rulings in this review. Correct the statement that P3 involves no A4.2 exception, and distinguish historical build descriptions from current artifact locations and predicates.

   **Test:** each documented recovery, reservation, quota and executable guarantee must reference a regression exercising that guarantee, including its crash boundary.

32. BLOCKER A4.1, A4.2 and A4.8, `rulings.py:readiness_problems`, `run.py:freeze_command`, `score.py:provenance` as constructed by `score_run`. **D6 remains a launch prerequisite.** A focused verification must cover the full closure checklist, not just selected code sections. The blind pack also cannot establish oracle correctness, classification semantics, contract extraction, consumer check suitability, challenge coverage or complete sealed artifact access chronology.

   **Fix:** obtain a focused verification record covering the repaired implementation, countersigned rulings and annexes, authentication and instruction evidence, quota semantics, predecessor and recovery behavior, scoring reconstruction and test results. Include an independent attestation bound to frozen hashes confirming the operation dependent properties, the 48 representative and 16 challenge cases, and sealing and access chronology without exposing operation content to Astra.

   **Test:** a fake replacement and recovery exercise plus the unchanged acceptance suite, corrected RT2.1, remaining red team reproductions and new regressions must pass. Missing required attestation or annex must block release. This focused re-review can satisfy the required re-review; another unrestricted full council cycle is unnecessary.

33. OK A4.1 and A4.8, `acceptance/INTERFACE.md`, `acceptance/`, supplied sections D and E. **Round 2 item 35 is supported by the supplied results, with verification limits.** Section D reports all 288 acceptance tests passing unchanged; I did not independently confirm the empty Git diff or rerun them. I find no supplied acceptance expectation requiring reversal under the currently signed A4 and A4.13. RT2.1 is a red team test and requires the specific correction in item 7. The dry run reports 16 complete simulated cells, 52 fake calls and zero external calls. The harness suite and full repository suite are not wholly green. Those results do not establish the missing live certification prerequisites or close the new static findings.

Verdict: DO NOT SIGN (fix the BLOCKER items, re-review required)