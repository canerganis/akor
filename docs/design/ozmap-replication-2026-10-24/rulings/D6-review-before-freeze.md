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

Required: focused_verification and operation_attestation (rulings.ANNEXES_REQUIRED, rulings.d6_problems). Not produced in this step.

## Open before binding

The two D6 annexes (focused_verification, operation_attestation) are not produced in this step.

## Countersignature

Opus B: pending (confirmation by diff of the ruling text above).
