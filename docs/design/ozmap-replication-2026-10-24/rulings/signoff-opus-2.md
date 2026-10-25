# Opus B sign-off 2 of rulings P3, P5 and D1 (2026-10-25)

Signer: Opus B, a fresh Opus workflow subagent (claude-opus-5-5), id opusb2-20261025T033012Z. Ledger row role
opus-b-signoff-2-rulings (Opus 42 of 70). No model call, no Codex call, no CLI run. The sealed ASTs and the ops content
were not read. Nothing was committed.

Scope: the blockers OB-P3, OB-P5 and OB-D1 of rulings/signoff-opus.md after repair commit 62285ac.

Result: P3 signed (OB-P3 closed; D5 and the freshness rule not approved). D1 signed (OB-D1 closed by owner decision 4).
P5 not signed: OB-P5 is closed as written, and one new A4.14.2 blocker OB-P5b stands, which agrees with Astra's P5
blocker of rulings/signoff-astra-2.md and adds the live route mechanism.

Concurrency note. Astra's sign-off 2 (rulings/signoff-astra-2.md) landed in the three ruling files while this review
ran: P3 and D1 signed, P5 blocked. The Opus B lines are appended after Astra's.

## Method

Diff. The verbatim blocks still equal council-build-deadlock-r2-joint.md (sha256 fae12460, unchanged): P3 lines 205 to
217 and 307 to 321, P5 231 to 243, 266 to 276 and 291 to 305, D1 251 to 264. The annex tables match the files on disk:
P3 manifest 3646deac, P5 startup manifest c5a6c741, P5 context evidence 56395a2b, D1 attribution evidence 4f8e7b49.

Tests. `python -m pytest bench/ozmap_rep -q -x -p no:cacheprovider` at HEAD 62285ac with the uncommitted sign-off edits:
643 passed in 254.60s (scratchpad opusb2_full_suite.txt). The acceptance tree differs from 1aad1f8 by the A4.14.4 replacement listed earlier and by the cap
constants of the signed A4.13r1.1 (Opus 70, global 236) in INTERFACE.md, test_a4_13_prep_caps.py and
test_a4_4_a4_5_budget.py, which build-notes.md lists. No other acceptance assertion changed.

Reproductions (scratchpad
C:\Users\can02\AppData\Local\Temp\claude\C--Users-can02-Projects-akor\4bd0413f-bf62-4dbc-94ba-cf58fbdc1707\scratchpad):
opusb_repro.py and opusb_d1.py (the earlier ones, rerun unchanged), opusb2_repro.py (corrected harvested cases,
signature and binding checks), opusb2_p5b.py, opusb2_p5c.py and opusb2_argv.py (the captured P5 request bodies).

## P3 quota observation: signed

OB-P3 is closed. Every row of the earlier table now blocks (opusb_repro.py, P3_coverage_gate): owner reading without
creator_account_id, limit_id `codex_other_bucket`, window_minutes 300, no event timestamp, three days old. The
harvested row of the earlier script also blocked there, but through the stale owner reading; opusb2_repro.py isolates
it with a fresh owner reading: a harvested reading without an account hash blocks ("carries no account hash") and one
of another bucket blocks, while the attributable control passes at 12%. The code paths are quota.attribution_problem
and the two calls in quota.coverage_gate. rulings.annex_problems refuses the slot while the manifest records
`not_established` (opusb2_repro.py, P3_with_both_lines), so no live dispatch depends on the open point.

The signature covers the ruling text and the annex 3646deac as it stands, with `not_established`. Like Astra's, it
does not approve D5 or the 60 minute freshness rule. A new manifest needs a new Opus B line.

D5 (Opus B position for the manifest, not part of this signature):

1. The harness keeps `--ephemeral` on worker calls (config.py, P3 note), so no worker rollout exists and form (i) of
   the predicate is unused. If `--ephemeral` is dropped later, form (i) does not cover the attempt that produced the
   reading: the reading is response generated, so the attempt's last request is not inside it. Opus B does not
   accept form (i) as coverage of its own attempt.
2. Form (ii) as implemented compares the owner token_count EVENT timestamp with the attempt's end. That event is
   written after the owner's own request, which may have been sent before the attempt ended. opusb2_repro.py,
   owner_turn_started_before_attempt_end_event_after: an owner turn that started 20 minutes before the attempt ended,
   with its token_count event one minute after the end, covers the attempt (ok at 10%). For an established manifest,
   Opus B requires the owner reading's request start (the turn start event of the same owner turn) to be later than
   the attempt's ended_at or ended_at_upper; a turn without such an event does not cover.
3. The freshness rule of 60 minutes is acceptable to Opus B as a selection bound together with point 2.
4. Consequence to disclose: without independently authorized owner calls between groups, the strict predicate stops
   the run after the first group. That is a stop under A4.14.1, not a validity risk.

## D1 authentication source attribution: signed

OB-D1 is closed. Owner decision 4 amends the operative text to the differential reading, so a binding no longer
applies a reading other than the signed one. Checks:

1. The amended text asks for the scrambled case before the charged call and the valid case on the live route.
   isolation.telemetry_certificate requires `exec_probe.outcome == auth_failure` with no reply, no usage, a worker
   home and kept account metadata (lines 998 to 1003), and the telemetry call `outcome == ok` with the file store at a
   worker home (lines 1012 to 1017). run.py TelemetryRun.arm makes the charged call only after the probe ended in
   auth_failure.
2. The annex records status `complete`, and rulings.ANNEX_STATUS refuses anything else.
3. The request boundary claims reproduce from the captured probes: with the scrambled auth.json all 15 captured
   requests carry bearer_source `prepared_access_token`; with the empty home none of the 8 carries an authorization
   header.
4. opusb2_repro.py: with both lines present, D1 binds with no problem (D1_with_both_lines).

## P5 startup manifest and effective context: not signed (OB-P5b)

OB-P5 as written is closed. The skills instructions item and the bundled skills are gone from the request, and
rulings.annex_problems refuses an effective context annex whose verdict is not `established` or whose route security
arguments differ from config.ROUTE_SECURITY_ARGS. My own inspection of the captured bodies (opusb2_p5b.py,
opusb2_p5c.py, opusb2_argv.py):

1. The probe argv minus the probe arguments equals isolation.codex_argv at HEAD with run.cli_flags() disable options,
   and argv_check returns no problem. argv_check refuses the route without `skills.include_instructions=false`.
2. The no auth POST /v1/responses body (sha256 81a4bed5, 58,091 bytes) holds seven input items: additional_tools,
   base instructions (21,769 characters), permissions, multi_agent_role, multi_agent_mode, environment_context, and
   the user item, whose text equals the stdin prompt exactly. No `instructions` field, `tools` null.
3. No `.agents`, `skills_instructions`, owner profile path, `Projects\akor` or skill name occurs. The `SKILL.md`,
   `AGENTS.md` and `orchestra` hits are generic vendor text in the base instructions and the exec tool description.
   The scrambled body has the same item structure.
4. The home after each probe holds only sqlite state, installation_id and tmp/arg0 files;
   isolation.startup_instruction_files flags none, so the empty startup manifest suffices.

Blocker OB-P5b (A4.14.2). The request boundary evidence comes from a route that differs from the live route in two
inputs that shape the request, and nothing on the live path checks the effective context. An unapproved base
instruction or tool set can therefore reach every Codex result without a flag, which P5 says prevents certification.

Evidence:

1. Model metadata. In final_scrambled.json, captured[0] and captured[2] are `GET /v1/models?client_version=0.160.0`,
   both answered 404 by the capture server. On the live route the server answers with the real catalog. The pinned
   binary carries `base_instructions` (14 occurrences) and `model_catalog_json` (21) in its strings
   (scratchpad codex-strings.txt), and the annex itself records that a live /models response "could change the vendor
   base instructions or tools" (provider_block_analysis.residual).
2. Transport. Both final probes first try `GET /v1/responses` with a WebSocket upgrade (7 tries, 404) and only then
   POST the body over HTTP. P4-exec-noauth.out shows the live route uses the WebSocket transport first. The captured
   body is the HTTP fallback; the frame the live route sends was never captured.
3. Decision. gen_p5.py line 241 sets `established` from the absence of owner content alone, as Astra found. The
   annex's item hashes are not compared with anything, and isolation.telemetry_certificate takes no request
   content input.

Fix:

1. Pin the model metadata on the frozen route, for example `-c model_catalog_json=<frozen catalog>` if the pinned
   CLI then sends no /models request or ignores its answer (prove by probe). Otherwise answer /models in the boundary
   probe with a catalog fetched once with the baseline credential (a GET, no model call) and freeze that catalog's
   hash.
2. Capture the request on the transport the live route uses: let the capture server accept the WebSocket upgrade and
   record the first frame, or prove by probe that a frozen `supports_websockets=false` setting yields the captured
   HTTP body.
3. Make `established` require item by item equality with the approved list (sha256 of every developer item, the tool
   schemas and the exact stdin user item; only the environment context's cwd, date and time zone may vary), with
   rejection tests for an extra item, a changed user item and a changed tool schema, as Astra asks.

P5-E3 (vendor multi_agent items and the collaboration and exec tools on a route that disables them): Opus B accepts
them as vendor context once they are pinned by the item hashes of fix 3. A model call to any of those tools stays an
A4.3 event and fails closed.

## Changes (not blockers)

1. rulings.ruling_problems matches signatures as substrings. The verbatim blocks of P3 and P5 contain
   `> Signed: Astra A`, so the Astra check is met before Astra signs anything (opusb2_repro.py, signature_substrings:
   P5 has no Astra line outside the quote, and P5_with_only_an_opus_line binds with no problem). Match a signature only
   as its own line outside the quoted block, and bind each line to the annex hashes it covers, so a later annex
   change cannot inherit an older signature.
2. quota.coverage_gate skips the harvest age check when an attempt has no started_at (opusb2_repro.py,
   harvested_without_started_at_and_day_old_reading: ok). Block instead. Unreachable while `--ephemeral` is kept.
3. Earlier changes 1 to 3 of signoff-opus.md still stand (run.py hardcodes `account_metadata_kept: True`; record
   `cmdkey /list` target names after telemetry; label the P4 survey basis).
