# Ruling D6: focused verification before freeze

Slot D6 of config.REQUIRED_RULINGS (bench/ozmap_rep/rulings.py). Source: council-build-deadlock-r2-joint.md (sha256 fae12460cd9e64fe76716ad7b612f1f2e51663a4258eccda31ebfbca9b5c4324), lines 323 to 334, copied byte for byte below.

Status: a disputed point of the joint decision (section 4); the operative text is the stricter position stated in it. Opus B confirmation by diff is pending, and this file is not bound in config.SIGNED_RULINGS. A binding needs this file countersigned (the line naming Opus B as signer) and its new sha256 recorded in the slot.

## Ruling text (verbatim)

### D6. Review before freeze

Fable: "a code lens pass over S2, S6 and S9 only ... S3, S4, S5, S7, S8, S10, S11, S13 and S14 are predicate changes
whose tests are the review."

Astra: "A code lens pass limited to S2, S6 and S9 is insufficient." Required: focused verification against the
complete closure checklist (countersigned rulings and annexes, authentication, instruction exclusion, executable
binding, quota semantics, redaction recovery, timing bounds, independent scoring, atomic reservations, identities,
recovery, predecessor evidence, the unchanged acceptance suite, all six round 2 red team reproductions, the new
regressions and a fake replacement and recovery exercise). Both agree that no further full council round is needed.

Operative: Astra's checklist, as one focused verification call.

## Annexes

Required: focused_verification and operation_attestation (rulings.ANNEXES_REQUIRED, rulings.d6_problems). Both are produced; a binding of this slot names them by these hashes:

* focused_verification: docs/design/ozmap-replication-2026-10-24/rulings/D6-focused-verification.json, sha256 36954f40da0d37c91c9ebbfb955ea50dfec838864987e9029b3b5dd5d737486a. Every checklist item has the verdict pass. The item rulings_and_annexes was re-verified at 909d669 by an independent Opus verifier: P1 to P5 and D1 are bound with matching ruling and annex hashes, and rulings.readiness_problems() reports only the unbound D6 slot.
* operation_attestation: docs/design/ozmap-replication-2026-10-24/rulings/D6-operation-attestation.json, sha256 9098722ef623a501d60fdc7d91afa31cdd3418f51db154797afef21537772a71. It passes rulings.d6_problems at 909d669 (classification and operation files bound as the harness uses them).

## Open before binding

Astra A and Opus B sign this file; config.SIGNED_RULINGS then binds D6 to the signed bytes with both annexes by the hashes above.

## Countersignature

Opus B: pending (confirmation by diff of the ruling text above).

## Astra sign-off D6 (2026-10-25)

Signed: Astra A D6

Source: rulings/signoff-astra-d6.md. Evidence pack: this ruling, both annexes (operation attestation as hashes, verdicts and counts only), A4.14. Astra confirms the 16 item checklist, 605 passing tests and the 16 cell dry run with zero validity findings; no blocker, no CHANGE notes. Binding still needs the Opus B countersignature and the final signed-file hash recorded with the two annex hashes.

## Opus B sign-off D6 (2026-10-25)

Signed: Opus B D6

Source: rulings/signoff-opus-d6.md. Confirmation by diff: lines 9 to 20 of this file equal lines 323 to 334 of council-build-deadlock-r2-joint.md (sha256 fae12460cd9e64fe76716ad7b612f1f2e51663a4258eccda31ebfbca9b5c4324) byte for byte. Both annexes hash to the values named above and pass rulings.d6_problems at 6e3a7ef. Every checklist selection was rerun at 6e3a7ef and passes (full suite 737 passed, dry run 16/16 cells with zero validity findings). No blocker; CHANGE notes are in the sign-off file.
