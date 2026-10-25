# Ruling D1: authentication source attribution

Slot D1 of config.REQUIRED_RULINGS (bench/ozmap_rep/rulings.py). Source: council-build-deadlock-r2-joint.md (sha256 fae12460cd9e64fe76716ad7b612f1f2e51663a4258eccda31ebfbca9b5c4324), lines 251 to 264, copied byte for byte below.

Status: a disputed point of the joint decision (section 4); the operative text is the stricter position stated in it. Opus B confirmation by diff is pending, and this file is not bound in config.SIGNED_RULINGS. A binding needs this file countersigned (the line naming Opus B as signer) and its new sha256 recorded in the slot.

## Ruling text (verbatim)

### D1. Authentication source attribution (S1)

Fable: the file store argument, the eight worker path checks and the recorded `auth_source` "together with the empty
home 401 probe ... binds the certificate to the execution route's configured credential source, not to an inference
from two observations", and "No ruling needed".

Astra: "Recorded configuration is not observed source attribution." Required: "binary-and-payload-bound implementation
analysis or a complete credential-access trace demonstrating that the actual authenticated execution route uses only
the prepared file credentials, including the account-indexed credential-store counterexample."

Operative: Astra's requirement; `telemetry_certificate` stays false until that evidence exists. For Opus B: decide
whether a local credential access trace of the pinned `codex.exe` (for example a file and registry access monitor
during the empty home 401 probe and during telemetry, no extra model call) is acceptable evidence; it is the cheapest
item that would close D1.

## Annexes

| kind | path | sha256 |
|---|---|---|
| attribution_evidence | docs/design/ozmap-replication-2026-10-24/rulings/D1-attribution-evidence.json | 8da49d334124a6e6f31560072672be0eeaf885f5410da3ab6a0daefc5130e209 |

## Open before binding

The attribution annex is partial: no complete credential access trace exists. Opus B rules whether this evidence with the telemetry scrambled token probe closes D1.

## Countersignature

Opus B: pending (confirmation by diff of the ruling text above).
