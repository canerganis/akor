# Opus B sign-off: ruling D6 (focused verification before freeze)

Reviewer: Opus B, fresh Opus workflow subagent (claude-opus-5-5). Not the implementer of bench/ozmap_rep or of bench/ozmap_rep/ops. No model call, no Codex request; ops content and sealed ASTs not read (the attestation was checked through rulings.d6_problems and rulings.ops_manifest hashes only). Commit checked: 6e3a7ef (bench/ozmap_rep identical to 909d669). Claude weekly all models 77 percent at the start of this review.

Verdict: sign. No A4.14.2 blocker.

Signed: Opus B D6

## Checks

1. Ruling text by diff. Lines 9 to 20 of D6-review-before-freeze.md equal lines 323 to 334 of council-build-deadlock-r2-joint.md byte for byte (Python split on LF, list equality True; no CR in the ruling file). The joint decision hashes to fae12460cd9e64fe76716ad7b612f1f2e51663a4258eccda31ebfbca9b5c4324, the value the ruling names. The operative text is Astra's checklist as one focused verification call, the stricter position.
2. Annex hashes. D6-focused-verification.json is 36954f40da0d37c91c9ebbfb955ea50dfec838864987e9029b3b5dd5d737486a and D6-operation-attestation.json is 9098722ef623a501d60fdc7d91afa31cdd3418f51db154797afef21537772a71, both as named in the ruling text.
3. rulings checks at 6e3a7ef: `rulings.d6_problems('focused_verification', ...)` and `rulings.d6_problems('operation_attestation', ...)` both return []; the attestation `ops_sha256` equals `rulings.ops_manifest()` and `classification_sha256` equals the hash of config.CLASSIFICATION_FILE; removing the `recovery` item makes d6_problems report it. `rulings.readiness_problems()` reports only the unbound D6 slot. config.SIGNED_RULINGS binds P1 to P5 and D1.
4. Simulated binding of the signed file (sha256 f3ad285ce9b5d8a190e9811352abdf497db2bcec48b4283f0ea8c99d30f8c850 with this sign-off appended, both annexes by the hashes above): `rulings.readiness_problems(slots=...)` returns [] and `rulings.bound_problems(rulings.record(slots))` returns []. Both signature substrings `Signed: Astra A` and `Signed: Opus B` are present.
5. D6 tests: test_o5_d6_is_a_required_ruling_with_its_two_annexes, test_o5_the_attestation_must_cover_every_item_and_bind_the_classification_and_operations and test_o5_the_scorer_checks_the_rulings_the_run_bound_freeze_binds pass.
6. Full suite at 6e3a7ef: `python -m pytest bench/ozmap_rep -q` gives 737 passed in 265.07s, 0 failed, 0 skipped.
7. Checklist rerun at 6e3a7ef. Each of the 16 recorded selections (paths plus -k) was collected at HEAD and every collected test passed in the full suite run: rulings_and_annexes 13, authentication 99, instruction_exclusion 34, executable_binding 35, quota_semantics 40, redaction_recovery 14, timing_bounds 19, independent_scoring 133, atomic_reservations 53, identities 27, recovery 59, predecessor_evidence 6, acceptance_suite_unchanged 288, red_team_reproductions 6, new_regressions 77, fake_replacement_and_recovery_exercise 30. None missing, none failed.
8. Dry run at 6e3a7ef: `python -m bench.ozmap_rep.run dry --run-dir <scratch>` exits 0, 16/16 cells complete, 52 fake calls, 0 external calls; report validity isolation passed, leakage 0, accounting_failures 0, artifact_problems 0, freeze_problems 0, classification_problems 0, interrupted 0, no invalid cell.

## CHANGE notes (not blockers under A4.14.2)

C1. The focused verification record is stamped at 708e0a7 for 15 of its 16 items, and bench/ozmap_rep changed after that (62285ac, e29891f, 4b15cc5, 6f053f8, 1bb148b, 909d669: P3 headroom gate in run.codex_quota_gate and quota.py, P5 effective context in isolation.verify_launch and run.freeze_command, D1 repairs). Its code_read and finding texts therefore describe the earlier code in places; quota_semantics still describes the replaced coverage gate rather than the owner decision 5 headroom bound. Not a blocker: every selection now collects more tests (instruction_exclusion 31 to 34, executable_binding 33 to 35, quota_semantics 37 to 40, atomic_reservations 52 to 53, identities 23 to 27) and all pass at 6e3a7ef; the P3 and P5 changes were reviewed and signed under their own rulings. Suggested: record the 6e3a7ef rerun as an addendum outside the bound annex, so the annex hash stays unchanged.
C2. The acceptance_suite_unchanged finding says only INTERFACE.md and test_cli_plan_and_cells.py changed since 1aad1f8. At 6e3a7ef test_a4_13_prep_caps.py and test_a4_4_a4_5_budget.py also changed (62285ac, 7a18323). Those edits only update the cap constants to the signed A4.13 revisions 1 and 2 and are listed in build-notes.md; no other assertion changed.
C3. acceptance/INTERFACE.md still says `GLOBAL_CAP=236` (A4.13r1.1) while config.GLOBAL_CAP is 246 under A4.13r2.1. Documentation only.
C4. The atomic_reservations observation in the record (abandon docstring says the reserved marker stays, the code removes it) stands; worst case is a flagged accounting failure, so a CHANGE.

## Binding

config.SIGNED_RULINGS may now bind D6 to D6-review-before-freeze.md at its signed sha256 (f3ad285ce9b5d8a190e9811352abdf497db2bcec48b4283f0ea8c99d30f8c850 as of this sign-off; recompute if the file changes again) with annexes focused_verification 36954f40da0d37c91c9ebbfb955ea50dfec838864987e9029b3b5dd5d737486a and operation_attestation 9098722ef623a501d60fdc7d91afa31cdd3418f51db154797afef21537772a71.
