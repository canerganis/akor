# Opus B sign-off 3 of ruling P5 (2026-10-25)

Signer: Opus B, a fresh Opus workflow subagent (claude-opus-5-5), id opusb3-20261025T035816Z. Ledger row role
opus-b-signoff-3-p5 (Opus 43 of 70). No model call, no Codex model request, no Codex login, no external request. One
local request boundary probe was run against a localhost capture server without auth.json (below). The sealed ASTs and
the ops content were not read. Nothing was committed.

Concurrency note. Astra's sign-off 3 (rulings/signoff-astra-3.md) landed in the ruling file while this review ran:
P5 signed by Astra A. The Opus B line is appended after Astra's.

Scope: blocker OB-P5b of rulings/signoff-opus-2.md after repair commit e29891f, which also answers Astra's P5 blocker
of rulings/signoff-astra-2.md.

Result: P5 signed. OB-P5b is closed in all three parts. One finding on the live serialization (the prewarm
continuation) is a CHANGE, not a blocker: my own probe shows the live serialization carries exactly the approved items.

## Method

Files checked at HEAD e29891f (sha256 on disk equals the annex table of rulings/P5-startup-context.md):

| file | sha256 |
|---|---|
| bench/ozmap_rep/startup-manifest.json | 20ea5c908886ead5a7b5d8eeacb7fd1dbf7f41e105b2637c11f42485da710e26 |
| rulings/P5-effective-context-evidence.json | 3b2f341c479a141dc639bf23f5c127ba9618a97a74f530b510aba514d71a9844 |
| bench/ozmap_rep/effective-context.json | 9f84be5000505407dbc8c232fdf403de8aed2e6200416796d30d3e864d89bfab |
| bench/ozmap_rep/model-catalog.json | 1d39994d11492a3c692c060c621e5c0f01213e18f06fcb5407fcd7d824ebd536 |

The probe scripts in rulings/evidence/p5-probe/ equal the scratch copies they ran from (boundary.py 8e17ff2f,
decode.py b75fc12d, gen_p5.py d8d4d732, as the annex records), and the seven capture files in scratchpad p5c/out hash to
the capture_file_sha256 values the annex records for its six probes and the previous route.

Reruns (scratchpad
C:\Users\can02\AppData\Local\Temp\claude\C--Users-can02-Projects-akor\4bd0413f-bf62-4dbc-94ba-cf58fbdc1707\scratchpad):

1. opusb2_p5b.py, opusb2_p5c.py and opusb2_argv.py unchanged, on the repair 1 captures. They reproduce the earlier
   findings, and opusb2_argv.py now reports for both old probes `argv_check: the route security arguments ... are
   missing or differ`, with the diff showing only the missing `-c model_catalog_json='...model-catalog.json'`. The
   route the earlier evidence came from is refused at HEAD.
2. `python -m pytest bench/ozmap_rep/tests/test_p5_effective_context.py -q -p no:cacheprovider`: 26 passed, none
   skipped. The rejection tests cover an extra instruction item, a changed and a missing item, a changed user item, a
   changed tool schema, unapproved fields and transport changes, every refusal case of certify, the launch and freeze
   bindings and the catalog bundled in the pinned executable.
3. `python -m pytest bench/ozmap_rep -q -x -p no:cacheprovider` at HEAD e29891f with the uncommitted sign-off
   files: 669 passed in 255.89s (scratchpad opusb3/full_suite.txt). The commit touches no acceptance or red team test.
4. opusb3/analyse.py on every capture of the annex: each pinned frame and body compares empty with the approved list
   on its own transport (prewarm frame as websocket_prewarm, full turn frame as websocket, HTTP body as http) and
   fails on the other transports. The unpinned control fails on item 0 (tool schemas) and item 1 (base instructions),
   so the canary does reach the request without the pin.
5. opusb3/raw.py, without effective_context code: the WebSocket turn frame equals the HTTP body item by item once
   ids, metadata passthrough, cwd, date and time zone are removed; the base instructions item (21,769 characters,
   sha256 e1bdd4f8) equals approved item 1; no `can02`, `.agents`, `skills_instructions`, `Projects\akor`,
   `CLAUDE.md` or canary string occurs in any pinned frame or body.

## OB-P5b: closed

1. Model metadata. The pin is in config.ROUTE_SECURITY_ARGS, so isolation.argv_check refuses a route without it
   (rerun 1). In the annex every pinned probe has models_requests 0 and the control 2. effective_context.launch_problems
   runs in isolation.verify_launch before every Codex launch and refuses a catalog file whose hash is not
   MODEL_CATALOG_SHA256 or an approved list captured with another model, CLI version, catalog or route arguments.
   run.freeze_command refuses an executable other than the one the approved list was captured with (fdda5fa3).
2. Live transport. The capture server accepts the WebSocket upgrade and records the frames. See the CHANGE below for
   the serialization a live server's answer to the prewarm produces.
3. Decision. certify needs every request of every pinned probe to equal the approved list, with a control that shows
   the canary, a clean owner scan and no external request; the annex records verdict `established`, empty
   verdict_reasons and eight empty comparisons. describe compares every top level field except prompt_cache_key and
   client_metadata (whose key set and non identifier values are also compared), refuses unknown item, metadata and
   content fields, and varies the environment context only in cwd (a numbered slot), date and time zone.
   rulings.annex_problems refuses the evidence when its approved_context_sha256 is not the approved list on disk or
   its catalog hash is not the pinned one. Astra's P5 blocker (the decision ignored the comparison) is answered by the
   same code.

P5-E3 is accepted as vendor context under the condition of signoff-opus-2.md, which now holds: the multi_agent items,
the collaboration tools and the exec tool are pinned by the item hashes of the approved list.

## CHANGE OB-P5c: the live WebSocket serialization is the prewarm continuation

The capture server answers the prewarm frame with an error event and closes the connection, so the CLI opens a second
connection and sends the full turn (7 items). A live server answers the prewarm with a completed response. The pinned
binary carries the continuation path in its strings (`ResponseCreateWsRequest`, `previous_response_id`,
`incremental`, `after_prewarm`, `codex.websocket.continuation`, `connection_reused`; scratchpad codex-strings.txt).

Reproduction: rulings/evidence/opusb3-p5/boundary_ok.py is boundary.py with one change: with `P5_WS=prewarm_ok` it
answers a frame carrying `generate: false` with `response.created` and `response.completed` (id
`resp_p5_prewarm_opusb3`, no output, zero usage) and keeps the connection open. Command, run from the scratchpad copy
with no auth.json in the worker home (no P5_SCRAMBLED):

    P5_WS=prewarm_ok python boundary_ok.py <scratchpad>/opusb3/out ws_prewarm_ok_no_auth
    ws_prewarm_ok_no_auth exit 1 elapsed 0.3 captured 1 [('GET', '/v1/responses', 0, 2)] proxied [] remote []

The CLI sends both frames on the one connection. Frame 2 carries `previous_response_id: resp_p5_prewarm_opusb3` and
five input items (permissions and collaboration mode, multi_agent role, multi_agent mode, environment context, user
item), with neither the tools item nor the base instructions. certify's transports refuse it (`top level fields differ:
['previous_response_id']`, `2 approved item(s) missing`, and so on; opusb3/analyse.py). The frames are in
rulings/evidence/opusb3-p5/ws_prewarm_ok_no_auth.frames.json (sha256 460c6f1a).

Why it is not a blocker (A4.14.2). The effective context of that call is the prewarm input plus the continuation input,
and opusb3/union.py shows that sum equals the approved list item by item: describe(prewarm) items plus
describe(continuation without previous_response_id) items == approved items (7 of 7), the continuation's top level
fields equal the approved ones, its client metadata keys and values equal the approved websocket entry, and the user
item is the exact stdin. opusb3/raw.py shows the same without effective_context code. The CLI builds the same input
on both paths; only the split over frames differs. No unapproved content reaches a result through it.

Change: freeze the continuation as a third WebSocket serialization in effective_context.TRANSPORTS (previous_response_id
equal to the id the prewarm answer gave, input equal to the approved items after the prewarm prefix, no generate
field), add a pinned `P5_WS=prewarm_ok` probe to gen_p5.py so certify compares that path too, and correct the sentence
of the ruling and the annex that names the turn frame on a second connection as the live transport.

## Other changes (not blockers)

1. Live server answers the probe could not reproduce: GET /backend-api/wham/accounts/check and
   /backend-api/wham/settings/user (requested between the prewarm and the turn frame) were answered 404 on the
   scrambled probes, and the prewarm answer of a live server may carry headers the probe does not send. I found no
   path from those answers into the request (the strings name only a CodexUserSettingsResponse struct), so this is a
   disclosure for the annex's residual, not a finding.
2. Earlier change 1 of signoff-opus-2.md still stands: rulings.ruling_problems matches signatures as substrings, and
   the verbatim block of P5 contains `> Signed: Astra A`. Until that is fixed, binding P5 must wait for Astra's own
   line on the repair 2 annexes; this signature does not stand in for it.
3. effective_context._SLOT accepts any path ending in a numbered slot directory, so the environment comparison does
   not by itself tie the cwd to the harness root (verify_launch does). Consider anchoring it to config's run root.
4. Earlier changes 2 and 3 of signoff-opus-2.md (no started_at harvest check; run.py account_metadata_kept, cmdkey
   record, P4 survey label) still stand.

## Signature

The signature covers the P5 ruling text (verbatim block unchanged), the startup manifest 20ea5c90, the effective
context evidence 3b2f341c, the approved effective context 9f84be50 and the pinned catalog 1d39994d, with change OB-P5c
open. A changed annex, approved list or catalog needs a new Opus B line.

Signed: Opus B P5
