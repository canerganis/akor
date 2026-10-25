# Ruling P4: CLI notice annex

Slot P4 of config.REQUIRED_RULINGS (bench/ozmap_rep/rulings.py). Source: council-build-deadlock-r2-joint.md (sha256 fae12460cd9e64fe76716ad7b612f1f2e51663a4258eccda31ebfbca9b5c4324), lines 219 to 229, copied byte for byte below.

Status: signed by Astra A as prospective protocol text (joint decision, section 3). Opus B confirmation by diff is pending, and this file is not bound in config.SIGNED_RULINGS. A binding needs this file countersigned (the line naming Opus B as signer) and its new sha256 recorded in the slot.

## Ruling text (verbatim)

### P4 (A4.3, A4.2)

> P4. Keep `code_mode_host` disabled. The sole candidate startup-notice message is exactly:
>
> ``Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.``
>
> Recognition additionally requires an `item.completed` event matching a complete outer-schema fixture approved by both signatories, with an error item containing exactly `id`, `type` and `message`, and an identifier matching the approved identifier syntax. F6 completes the message text, not the event annex. Until the fixture and identifier syntax are approved, this notice exception remains inactive.
>
> Additional fields, appended text and message variants do not qualify. Authentication failures, accompanying tool activity and unresolved execution evidence retain their dispositions.
>
> Signed: Astra A

## Annexes

| kind | path | sha256 |
|---|---|---|
| cli_notice_annex | docs/design/ozmap-replication-2026-10-24/rulings/P4-cli-notice-annex.json | 70b8b55a59cddfd8037948eabf59d9d394f96f77bf9389d7a85013df63a7e693 |

Supporting evidence (not an annex slot):

* docs/design/ozmap-replication-2026-10-24/rulings/evidence/P4-outer-event-fixture.json (sha256 8ec2ef717c153f709ebcb13d5978181484c228a1f65e7cfef3f53c30963f19e3)
* docs/design/ozmap-replication-2026-10-24/rulings/evidence/P4-exec-noauth.out (sha256 a73dc474d77594c2bed848746918c150f3feb917b78a3b4db429312dcfcb9ed4)

## Open before binding

The annex fills the outer event keys and the identifier syntax from the archived stream. The fixture and the identifier syntax still need approval by both signatories; until then the notice exception stays inactive (config.SIGNED_CLI_NOTICES, SIGNED_CLI_NOTICE_EVENT_KEYS and SIGNED_CLI_NOTICE_ID_RE stay empty).

## Countersignature

Opus B: pending (confirmation by diff of the ruling text above).
