# Ruling P5: startup manifest and effective instruction context

Slot P5 of config.REQUIRED_RULINGS (bench/ozmap_rep/rulings.py). Source: council-build-deadlock-r2-joint.md (sha256 fae12460cd9e64fe76716ad7b612f1f2e51663a4258eccda31ebfbca9b5c4324), lines 231 to 243, copied byte for byte below.

Status: signed by Astra A as prospective protocol text (joint decision, section 3). Opus B confirmation by diff is pending, and this file is not bound in config.SIGNED_RULINGS. A binding needs this file countersigned (the line naming Opus B as signer) and its new sha256 recorded in the slot.

## Ruling text (verbatim)

### P5 (A4.2)

> P5. Include `--enable skip_host_skill_discovery` in the frozen arguments and verify its effective behavior for the pinned execution route.
>
> Vendor startup instruction files may be created only at canonical relative paths with contents, file types, origins and permitted roles enumerated in a manifest approved by both signatories before freeze. Reject path escapes, symlinks, junction substitutions, changed contents and unapproved instruction-bearing files. Mutable runtime artifacts require separately specified roles and validation rules.
>
> File creation permission does not authorize instruction loading. Certification requires pinned implementation analysis or request-boundary evidence establishing the complete effective instruction sources, including base-instruction assembly, project instructions, skills and other injected context. A rollout inventory qualifies only if its completeness and faithful correspondence to that effective request are established for the pinned route. Provenance labels and message hashes alone are insufficient.
>
> Compare the established effective context with the approved base instructions and exact harness input, allowing only explicitly frozen serialization. Any additional or unexplained instruction source, changed authorized content or missing completeness evidence prevents certification and dependent evaluation launch.
>
> Freeze must approve deterministic manifests and the verification procedure. Execution-only evidence may be collected during already authorized telemetry after its prerequisites pass; it cannot retrospectively authorize previously unapproved context. Including bundled skill instructions requires a separate prospective amendment. Residual-risk disclosure does not waive exclusion.
>
> Signed: Astra A

## Open point for Opus B (verbatim, lines 266 to 276; not part of the signed text)

### D2. Instruction exclusion evidence (S11, P5)

Fable: the telemetry rollout's model input inventory compared with the base instructions and the harness stdin; "Any
additional input item ... is a third source and fails certification, whatever the filenames in the home."

Astra: "A rollout's `response_item` inventory is insufficient without proof that it exhaustively represents the
effective model request, including assembled base instructions and injected context."

Operative: Astra's P5. Open evidence: proof that the 0.160.0 rollout records the complete effective request
(pinned implementation analysis or request boundary evidence). Both agree that without it the live path stays stopped
(Fable P5 draft: "If (b) cannot be produced, the live path stays stopped").

## Open point for Opus B (verbatim, lines 291 to 305; not part of the signed text)

### D4. Origin of the startup manifest (S12, S11)

Fable: "One local no auth exec probe is not needed before the freeze: the telemetry's own probe (already budgeted)
produces the startup inventory of the frozen argv, and the telemetry refuses the charged worker call if that inventory
is not covered."

Astra: "A probe that first reveals an unknown inventory cannot authorize that inventory during the same frozen run.
Stop, approve the annex and refreeze before dependent execution, retaining all prior debits."

Operative: Astra's rule. Driver note: Fable's own design references a manifest "frozen by hash" and "taken from the
probe home of the frozen argv", which only works if the manifest exists before freeze. Two ways to satisfy both: (a) a
pre freeze no auth exec probe with the final argv (it makes no model request; whether it counts against the telemetry
allowance of 4 needs Opus B's ruling), or (b) Astra's stop, approve and refreeze path after the telemetry probe. The
existing `cliprobe/home` inventory (F5) predates `--enable skip_host_skill_discovery` and the dropped `--ephemeral`, so
it cannot serve as the manifest.

## Annexes

| kind | path | sha256 |
|---|---|---|
| startup_manifest | bench/ozmap_rep/startup-manifest.json | 60d3fe06a980be59358c50ea9dcc3676ea3a43f7731085f7182d2715d10a6e3f |
| effective_context_evidence | docs/design/ozmap-replication-2026-10-24/rulings/P5-effective-context-evidence.json | 622b373e36b52bb06a0a862941d6625626dd98668afadcc168634914e38a1bd2 |

## Open before binding

The effective context annex has the verdict not_established and records blocking findings P5-E1 to P5-E3 (the default context assembly of the pinned binary lists the owner profile skills, the CODEX_HOME system skills and multi_agent instructions; the renderer ignores the frozen flags). D2 and D4 stay open.

## Countersignature

Opus B: pending (confirmation by diff of the ruling text above).
