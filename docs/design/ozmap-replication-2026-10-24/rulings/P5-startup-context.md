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
| startup_manifest | bench/ozmap_rep/startup-manifest.json | c5a6c7415061e810490630cda0d08e33b8b45b89480396ec5ae06a51539e87bb |
| effective_context_evidence | docs/design/ozmap-replication-2026-10-24/rulings/P5-effective-context-evidence.json | 56395a2b27acf6869d7a88f282817589461ad58a44ab746596051b32990462b1 |

The previous annexes (startup manifest 60d3fe06a980be59358c50ea9dcc3676ea3a43f7731085f7182d2715d10a6e3f, context evidence 622b373e36b52bb06a0a862941d6625626dd98668afadcc168634914e38a1bd2, rendered with `codex debug prompt-input`) are replaced by the request boundary evidence below.

## Repair of 2026-10-25 (blocker OB-P5)

Request boundary probe (D4 route a, Opus B's fix): the frozen exec argv in a fresh worker home with no auth.json and only `-c openai_base_url=<localhost capture server>` added; the capture server records every request in full and answers the model request with HTTP 400, every other connection goes to a refusing localhost proxy, and the process tree connections are polled. No model call, no external request. Probe scripts: rulings/evidence/p5-probe/.

On the previous route the captured request carried a `<skills_instructions>` item listing the owner's ~/.agents/skills (25 skill descriptions from ~/.agents/skills and the owner profile path) and the 4 bundled CODEX_HOME skills, although `--enable skip_host_skill_discovery` was on. The pinned binary resolves the user skills root from the OS profile, not from CODEX_HOME, HOME or USERPROFILE, and a working directory outside the profile does not change it. The frozen route now also carries `-c skills.include_instructions=false` and `-c skills.bundled.enabled=false` (config.ROUTE_SECURITY_ARGS, enforced by isolation.argv_check). With them the captured request, without auth and with a scrambled ChatGPT auth.json, holds no owner skill, plugin, memory or AGENTS.md content (408,683 owner lines and 52 skill descriptions searched, no hit), and the CLI writes no instruction bearing file into the home, so the startup manifest lists no file. The effective context evidence records verdict `established`; rulings.annex_problems refuses to bind P5 when that verdict is anything else or when the evidence was captured with other route security arguments.

Disclosed vendor items that stay in the request (not owner content): the base instructions, permissions and collaboration mode instructions, multi_agent role and mode instructions, the environment context, and an additional_tools item with the code mode `exec` tool (its description lists web search, sports, time and weather helpers) and the collaboration tools (spawn_agent and others), although multi_agent and code_mode_host are disabled.

## Open before binding

The two added route arguments and the new annexes need both signatories. P5-E3 (vendor multi_agent items and tools on a route that disables them) is disclosed, not removed; whether it is acceptable vendor context is the signatories' call. D2 is answered by request boundary evidence rather than a rollout inventory; D4 follows route (a).

## Countersignature

Opus B: pending (confirmation by diff of the ruling text above).

## Astra countersignature

Astra A signed P5 on 2026-10-25 (rulings/signoff-astra.md) with the previous annexes (60d3fe06, 622b373e). That signature does not cover the route arguments and annexes of the repair above; a re-sign request is pending.

## Astra sign-off 2 (2026-10-25)

Not signed. Astra A raised BLOCKER P5 (rulings/signoff-astra-2.md): the certification generator can produce `established` without checking an exact match with the approved effective context. The decision in evidence/p5-probe/gen_p5.py (line 241) ignores `same_items` and writes the harness input description as a fixed string. Fix requested: make a full comparison of approved base instructions, all additional messages, tool schemas and the harness input a condition of `established`, pin or verify live model metadata, add rejection tests for an extra instruction, a changed input and a tool change. Until then the annex verdict must read `not_established`. Astra's earlier signature (signoff-astra.md) covered the previous annexes only.

## Opus B sign-off 2 (2026-10-25)

Opus B: not signed (rulings/signoff-opus-2.md, blocker OB-P5b, opusb2-20261025T033012Z). OB-P5 as written is closed: the captured request of the frozen route holds no owner content. The new blocker agrees with Astra's P5 blocker: the evidence was captured with /models answered 404 and over the HTTP fallback, while the live route gets the real model catalog (which can carry base instructions) and sends over WebSocket first, and the `established` decision does not compare the request items with an approved list. Fix: pin the model metadata, capture on the live transport, and require item by item equality with rejection tests.
