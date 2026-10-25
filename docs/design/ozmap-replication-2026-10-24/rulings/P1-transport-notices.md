# Ruling P1: transport notices

Slot P1 of config.REQUIRED_RULINGS (bench/ozmap_rep/rulings.py). Source: council-build-deadlock-r2-joint.md (sha256 fae12460cd9e64fe76716ad7b612f1f2e51663a4258eccda31ebfbca9b5c4324), lines 187 to 193, copied byte for byte below.

Status: signed by Astra A as prospective protocol text (joint decision, section 3). Opus B confirmation by diff is pending, and this file is not bound in config.SIGNED_RULINGS. A binding needs this file countersigned (the line naming Opus B as signer) and its new sha256 recorded in the slot.

## Ruling text (verbatim)

### P1 (A4.3)

> P1. For the frozen codex-cli 0.160.0 route, `SIGNED_TRANSPORT_NOTICES = []`. Neither `Reconnecting... ` nor `Falling back from WebSockets to HTTPS transport.` receives a transport exception through prefix matching or structural constraints alone.
>
> A nonempty registry requires a prospective ruling approved by both signatories, containing complete event fixtures, complete outer and item schemas, and fully anchored message grammars with explicitly bounded variable fields. Authentication failures, execution evidence and unresolved execution uncertainty retain their existing dispositions.
>
> Signed: Astra A

## Open point for Opus B (verbatim, lines 278 to 289; not part of the signed text)

### D3. Transport notices (P1)

Fable: prefix match on `Reconnecting... ` and `Falling back from WebSockets to HTTPS transport.` with structural
constraints and the no tool item condition closes item 32.

Astra: `SIGNED_TRANSPORT_NOTICES = []`; a nonempty registry needs complete fixtures and fully anchored grammars.

Operative: Astra's P1 (strict). Cost to name for Opus B: with an empty registry every reconnect or fallback event makes
its call uncertain under A4.3, which enters experiment wide leakage. If such events are frequent on this route the
strict choice can void the experiment. The way out both texts allow is an archived fixture set from existing captures
with an anchored grammar (Fable's strings have no variable fields, so the grammar may be the exact full message),
approved by both signatories before freeze.

## Annexes

None required: rulings.ANNEXES_REQUIRED lists none for this slot.

## Countersignature

Opus B: pending (confirmation by diff of the ruling text above).
