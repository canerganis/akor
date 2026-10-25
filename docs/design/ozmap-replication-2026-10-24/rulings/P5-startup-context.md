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
| startup_manifest | bench/ozmap_rep/startup-manifest.json | 20ea5c908886ead5a7b5d8eeacb7fd1dbf7f41e105b2637c11f42485da710e26 |
| effective_context_evidence | docs/design/ozmap-replication-2026-10-24/rulings/P5-effective-context-evidence.json | 3b2f341c479a141dc639bf23f5c127ba9618a97a74f530b510aba514d71a9844 |

Named by the effective context evidence and checked by rulings.annex_problems (not separate annex slots):

| file | path | sha256 |
|---|---|---|
| approved effective context | bench/ozmap_rep/effective-context.json | 9f84be5000505407dbc8c232fdf403de8aed2e6200416796d30d3e864d89bfab |
| pinned model catalog | bench/ozmap_rep/model-catalog.json | 1d39994d11492a3c692c060c621e5c0f01213e18f06fcb5407fcd7d824ebd536 |

The annexes of repair 1 (startup manifest c5a6c741, context evidence 56395a2b) are replaced by those of repair 2 below.

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

## Repair 2 of 2026-10-25 (blockers P5 of Astra A and OB-P5b of Opus B)

Model metadata (OB-P5b fix 1). The frozen route now carries `-c model_catalog_json='<repo>/bench/ozmap_rep/model-catalog.json'` (config.ROUTE_SECURITY_ARGS, enforced by isolation.argv_check). The file is the model catalog bundled in the pinned codex.exe, byte for byte (found once in the executable, sha256 1d39994d). Probe: with the pin no probe sends GET /v1/models (0 requests in 5 pinned probes). Control: the same argv without the pin, with /models answered by the pinned catalog whose instruction template of gpt-6.1-sol starts with a canary, requests /models twice and its request carries the canary in the base instructions item and a changed tool schema. So without the pin a live /models answer would change the effective context, and with the pin the CLI never asks.

Live transport (fix 2). The capture server now accepts the WebSocket upgrade and records every frame. The CLI sends a prewarm frame (`generate: false`, the tools item and the base instructions) on one connection and the turn frame on a second. The turn frame equals the HTTP fallback body item by item; the only transport field is `type: response.create`. Both transports are certified.

Decision (fix 3 and Astra's P5). The verdict is bench/ozmap_rep/effective_context.certify. `established` needs every captured request of every pinned probe (WebSocket turn and prewarm, HTTP, no auth and scrambled ChatGPT auth, a one line and a multi line stdin with CRLF and a trailing newline) to equal the approved effective context (bench/ozmap_rep/effective-context.json) item by item: sha256 of every developer item, the tool schemas as canonical JSON, the environment context with only its working directory (a numbered slot directory, also its workspace root), date and time zone as placeholders, and the user item as the exact stdin bytes. Top level fields and client metadata keys are compared too; only per call identifiers vary. It also needs no /models request and no canary on a pinned probe, a control that shows the canary, a clean owner content scan and no external request. Rejection tests: tests/test_p5_effective_context.py (an extra instruction item, a changed or missing item, a changed user item, a changed tool schema, an unapproved field, each failure case of certify). The evidence records verdict `established` with every comparison empty.

Live path. The request content travels over TLS to the vendor and the harness cannot observe it. isolation.verify_launch now checks before every Codex launch what determines it: the catalog file the argv names hashes to config.MODEL_CATALOG_SHA256, and the approved effective context exists and records the frozen model, CLI version, catalog and route arguments (effective_context.launch_problems). The freeze refuses a Codex executable other than the one the approved list was captured with (effective_context.executable_problems), and every launch checks the executable against the frozen one. rulings.annex_problems refuses an effective context annex that was not compared with the approved list the harness uses now or not captured with the pinned catalog.

Disclosed: the catalog path in the argv lies below the owner profile (the repository); the CLI reads that one file, and no owner path occurs in any captured request. P5-E3 (multi_agent items and the collaboration and exec tools) is now pinned by the item hashes of the approved list, the condition Opus B named in signoff-opus-2.md.

Open before binding: both signatories, on the ruling text, the two annexes above and the approved effective context and catalog they name.

## Astra sign-off 3 (2026-10-25)

Astra A signed P5 after repair commit e29891f (rulings/signoff-astra-3.md), covering this ruling text, the repair 2 annexes and the effective context and catalog they name. It does not approve D5 and does not replace Opus B's countersignature.

Signed: Astra A P5

## Opus B sign-off 3 (2026-10-25)

Opus B signed P5 after repair commit e29891f (rulings/signoff-opus-3.md, opusb3-20261025T035816Z), covering this ruling text, the startup manifest 20ea5c90, the effective context evidence 3b2f341c, the approved effective context 9f84be50 and the pinned catalog 1d39994d. OB-P5b is closed. Change OB-P5c stays open: with a live style answer to the prewarm the CLI sends the turn as a continuation on the same connection (previous_response_id, five items); the prewarm and continuation items together equal the approved list (rulings/evidence/opusb3-p5/), but that serialization is not yet a frozen transport of effective_context.TRANSPORTS. A changed annex, approved list or catalog needs a new Opus B line.

Signed: Opus B P5
