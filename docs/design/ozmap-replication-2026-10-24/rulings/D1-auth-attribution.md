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

## Astra countersignature

Signed: Astra A D1 (2026-10-25, rulings/signoff-astra.md)

Opus B ruling and confirmation by diff (2026-10-25): the text above equals lines 251 to 264 of council-build-deadlock-r2-joint.md (sha256 fae12460cd9e64fe76716ad7b612f1f2e51663a4258eccda31ebfbca9b5c4324) byte for byte. Ruling on D1: a complete credential access trace (Process Monitor or similar) is not required. Attribution is established by the differential on the actual route: the telemetry certificate runs the frozen exec argv at a worker path with auth.json holding the baseline account metadata and tokens no server accepts, and requires an authentication failure without reply or usage before the charged call (isolation.telemetry_certificate, run.py TelemetryRun.arm). A source keyed by account metadata or by path would authenticate that probe; a source keyed by token bytes can only hold tokens from the prepared auth.json. With the file store argument and the secret_auth_storage disable enforced by argv_check and verify_launch, this closes D1. telemetry_certificate stays false whenever the probe does not end in an authentication failure. Annex checked: the codex.exe sha256 and the seven static string counts reproduce; the only Codex entry of the Windows credential store is secrets|0218800dc2c5837c.codex, and 0218800dc2c5837c is the first 16 hex of sha256 over \?\<owner home>\.codex (the baseline path gives 841add2be2e6febe, which has no entry). This position relaxes the operative requirement stated by Astra. Astra A signed this file on the unchanged strict requirement and rejected the probe as a substitute (rulings/signoff-astra.md, D1 CHANGE note), so the signatories disagree on what the slot means.

Not signed by Opus B (rulings/signoff-opus.md, blocker OB-D1): with both signature lines present, rulings.ruling_problems treats the slot as settled, and isolation.telemetry_certificate never consults the attribution annex, so the certificate would pass on the probe alone, which is Opus B's reading and not the signed strict one. The dispute goes to the owner under A4.14.3, or one signatory adopts the other's text.
