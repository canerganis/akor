# Boundary adoption: frozen plan as implemented

Design: Opus's section 7 in [02](02-opus-r1.md), signed by Astra with explicit decisions in
[03](03-astra-r2-signed.md), signed off with build notes in [04](04-opus-r2-sign.md). This file records what the code
does, so the paid runs can be judged against it. Nothing here is a model result: no model was called to build it.

## Identity

| Item | Value |
|---|---|
| Freeze digest | `ed082d4da16d4e045f0c2e9d34c8c01fb2fb82289fdb0e71c49a48c6b4ddf0f7` (short: ed082d4d) |
| Freeze record | `bench/step4/inspection-handoff-20-v2/freeze.json` (files, the 36 request digests, the three sample packets) |
| Workflow | `inspection-handoff-20/v2`, pack `bench/step4/inspection-handoff-20-v2/` (20 nodes, v1's sources and expected values byte for byte) |
| Harness | `bench/step4/adopt.py` (freeze, dry, qualify, suite, report), `bench/step4/packs.py` (per-pack module copies) |
| Operation | `model.classify` version 2, inputs `record`, `interval` (ordered), `interval` in JSON value form; check `mat_classify_interval@1` |
| Route | Sonnet 5.5 (`claude-sonnet-5-5`), default effort, `claude -p` with no tools, CLI 2.1.306, text H (`d941a86d`), strict OZ/1g header parser, `oz1g-selective-v1` in the suite |
| Qualification evidence | `bench/step4/adopt-qual/` (ledger, per-call request, envelope, stderr, meta, report) |
| Suite workspace and prefix | fresh `.oz-runtime/ad1`, prefix `ad1`, memo namespaces `live-ad1-*` |

The digest is the sha256 of the canonical JSON of two parts. Files: every pack file, the executor and adapter
(`oz.py`, `oz_batch.py`, `oz_reply.py`, `oz_accept.py`, `oz_runtime.py`, `oz_worker.py`, `oz_runner.py`, `oz_do.py`,
`oz_memo.py`, `oz_quota.py`, `oz_flow.py`, `oz_fault.py`, `oz_workspace.py`, `examples/claude_cli_adapter.py`), the
step 4 harness (`workflow.py`, `evaluator.py`, `fixture_adapter.py`, `g3b.py`, `step4.py`, `packs.py`, `adopt.py`),
`bench/probe/boundary.py` (its parser, accounting and call runner are reused) and design files 01 to 04, all with
CRLF normalized. Qualification: route and argv, H's hash, the operation, the limits and goal template, the three goal
sentences, the 24 cases, the 36 slots (cell, goal, cases, expected labels, prompt sha256 and bytes), both
allocations, the rules and the sample packets. `freeze` regenerates the 36 packets through the packer and compares
them; `qualify --expect` refuses any other digest, and every launch re-checks its request against the frozen sha256.

## What was built

1. **`oz do` JSON value refs (opt-in).** A ref may be `{"value": <JSON value>}`. The packet then carries the value
   itself (an interval as an array, `"unknown"` as a JSON string), as probe arm C sent it; its compact JSON is the
   reference text for checks and memo identity; its source label is `value`. Strings and `{"path"}` keep their
   meaning, so the default request digest, packet and behavior are unchanged. `Inbox.complete` gained an optional
   `values` argument that stores the value as the ref job's accepted JSON value (`oz_runtime.py`).
2. **Ordered model inputs (`oz_flow.py`).** `ModelOp.inputs` given as a tuple is ordered; `values` names the inputs
   sent in the value form. Such an operation sends refs `<node>-record` and `<node>-interval` in that order for job
   `<node>`; the shipped first-use packer lays them out (record and interval interleaved per job). Planning (`_plan`),
   dispatch (`_run_stage`), stage pins and the stage request identity carry the list. A one-input operation is
   byte-for-byte the shipped path. The operation identity of an ordered or value-form operation also hashes the input
   order and value forms; the memo compute key covers both refs' exact bytes in order (oz_accept, unchanged).
3. **Structured limits.** `workflow.json` of v2 stores `limits` (`lower` 12.48, `upper` 12.52, `unit` mm, `inclusive`
   true) and `goal_template`. In the v2 copy of `workflow.py`, `LOWER`, `UPPER`, the handoff document's
   `acceptance_interval` and the Markdown line derive from them; `limits_problems` refuses a goal sentence, template,
   unit, inclusion flag or constant that disagrees, and `registry()` refuses to build. The evaluator keeps its own copy
   (`ACCEPTANCE_INTERVAL`), tested equal. v1's constants are unchanged and tested equal to the same numbers.
4. **`mat_classify_interval@1`.** Exactly one slot with exactly two refs; the record parses; the interval equals the
   one recomputed from that record with `Decimal` (so a missing, malformed, double-encoded, other-record or older
   interval fails); the label equals the frozen limits' verdict on that interval, inclusive at both limits.
5. **The graph.** `classify_X` binds `record = /records/X` and `interval = /bounds/X` of `checked_intervals`;
   `graph_problems` refuses anything else. Both refs resolve from the same current acceptance of node 11, and a
   classification commit is refused when node 11 has moved since (fixture 3 below).
6. **The amended predicate on two refs (`g3b.py`, own code, no executor import).** The v2 `g3b.json` lists
   `model_refs: {"classify": ["record", "interval"]}`; `expected_text` then returns the frozen record and its frozen
   interval at the revision in force (from `expected.json`), so `stale_input`, `input_changed` and the exact trace see
   both refs. `step4.trace_of` records a two-ref job's refs as a list. Everything else in the predicate is unchanged.
7. **Qualification.** 24 frozen cases (`qual.json`), the frozen run order, packets generated by
   `oz_flow._stage_request` and `oz do` (normalizer, inbox, ref reads, planner, renderer, sizes 4 and 1) under an
   in-process capturing adapter; calls as in the probe (`B.call_argv`, H on `--system-prompt`, packet on stdin, raw
   evidence, `modelUsage` only), scored with the probe's strict parser against each slot's frozen labels.

## Packet contract (value form and layout, as signed)

Records are JSON strings, intervals are JSON values (`["12.48 mm","12.52 mm"]`, or the string `"unknown"`),
interleaved per job in first-use order, one block, rows `[classify_X, 2k, 2k+1]` with X by position. The dry gate
checks that the clean scenario's classify packet, built by the executor in the flow under the fixture route, is byte
for byte the packet the qualification generator builds for the same inputs (sha256 `81e73866e9bb5d3a…`), and the same
for the stale scenario's classify packet; every qualification packet passes `packet_problems`.

Size-4 sample (slot 1, goal 1, cases 1, 5, 3, 8; 1,206 bytes):

```json
{"v":"1g","goal":"Prepare an evidence-limited inspection handoff. The numerical acceptance interval is [12.48,12.52] mm, inclusive. Interval inclusion is arithmetic only, not physical validation.","ops":["The first ref is the measurement record. The second ref is its host-checked interval: [lower,upper], or unknown. If the interval is unknown, return unknown. Otherwise use its endpoints directly. Let L and U be the lower and upper limits of the goal's acceptance interval, in mm. Return inside if lower >= L AND upper <= U; outside otherwise. Equality at either limit is inside."],"refs":["length=12.50 mm; uncertainty=0.02 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed",["12.48 mm","12.52 mm"],"length=12.48 mm; uncertainty=0.01 mm; n=1; method=caliper; basis=resolution; physical_validation=not_claimed",["12.47 mm","12.49 mm"],"length=12.51 mm; uncertainty=0.01 mm; n=1; method=caliper; basis=resolution; physical_validation=not_claimed",["12.50 mm","12.52 mm"],"length=12.50 mm; uncertainty=unknown; n=4; method=micrometer; basis=unknown; physical_validation=not_claimed","unknown"],"jobs":[[0,["classify_A",0,1],["classify_B",2,3],["classify_C",4,5],["classify_D",6,7]]]}
```

Size-1 sample (slot 13, goal 1, case 1; 758 bytes):

```json
{"v":"1g","goal":"Prepare an evidence-limited inspection handoff. The numerical acceptance interval is [12.48,12.52] mm, inclusive. Interval inclusion is arithmetic only, not physical validation.","ops":["The first ref is the measurement record. The second ref is its host-checked interval: [lower,upper], or unknown. If the interval is unknown, return unknown. Otherwise use its endpoints directly. Let L and U be the lower and upper limits of the goal's acceptance interval, in mm. Return inside if lower >= L AND upper <= U; outside otherwise. Equality at either limit is inside."],"refs":["length=12.50 mm; uncertainty=0.02 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed",["12.48 mm","12.52 mm"]],"jobs":[[0,["classify_A",0,1]]]}
```

Clean-fixture classify packet (the workflow's own clean inputs A to D; 1,207 bytes):

```json
{"v":"1g","goal":"Prepare an evidence-limited inspection handoff. The numerical acceptance interval is [12.48,12.52] mm, inclusive. Interval inclusion is arithmetic only, not physical validation.","ops":["The first ref is the measurement record. The second ref is its host-checked interval: [lower,upper], or unknown. If the interval is unknown, return unknown. Otherwise use its endpoints directly. Let L and U be the lower and upper limits of the goal's acceptance interval, in mm. Return inside if lower >= L AND upper <= U; outside otherwise. Equality at either limit is inside."],"refs":["length=12.50 mm; uncertainty=0.02 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed",["12.48 mm","12.52 mm"],"length=12.47 mm; uncertainty=0.03 mm; n=5; method=micrometer; basis=expanded; physical_validation=not_claimed",["12.44 mm","12.50 mm"],"length=12.51 mm; uncertainty=0.01 mm; n=1; method=caliper; basis=resolution; physical_validation=not_claimed",["12.50 mm","12.52 mm"],"length=12.50 mm; uncertainty=unknown; n=4; method=micrometer; basis=unknown; physical_validation=not_claimed","unknown"],"jobs":[[0,["classify_A",0,1],["classify_B",2,3],["classify_C",4,5],["classify_D",6,7]]]}
```

## The 24 cases

Goals: 1 `[12.48,12.52]`, 2 `[10.00,10.08]`, 3 `[12.46,12.54]` mm, each the workflow's goal sentence with only the two
numbers replaced. Cases: 1 both limits equal `[L,U]`, 2 lower equality `[L,U-0.02]`, 3 upper equality `[L+0.02,U]`,
4 strict interior `[L+0.01,U-0.01]`, 5 lower breach `[L-0.01,L+0.01]`, 6 upper breach `[U-0.01,U+0.01]`, 7 disjoint
above `[U+0.01,U+0.05]`, 8 unknown. Every record is consistent (length the midpoint, uncertainty half the width, two
decimals) and carries the n, method and basis of one of the workflow's records; g1c1 is A rev 1, g1c3 is C, g1c7 is
the stale A rev 2 and g1c8 is D, byte for byte. Every 0.01-breach record (uncertainty 0.01 mm) parses and recomputes
on the host (checked by `case_problems` and dry fixture 6).

| Case | Record | Interval | Label |
|---|---|---|---|
| g1c1 | length=12.50 mm; uncertainty=0.02 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed | [12.48 mm, 12.52 mm] | inside |
| g1c2 | length=12.49 mm; uncertainty=0.01 mm; n=5; method=micrometer; basis=expanded; physical_validation=not_claimed | [12.48 mm, 12.50 mm] | inside |
| g1c3 | length=12.51 mm; uncertainty=0.01 mm; n=1; method=caliper; basis=resolution; physical_validation=not_claimed | [12.50 mm, 12.52 mm] | inside |
| g1c4 | length=12.50 mm; uncertainty=0.01 mm; n=5; method=micrometer; basis=expanded; physical_validation=not_claimed | [12.49 mm, 12.51 mm] | inside |
| g1c5 | length=12.48 mm; uncertainty=0.01 mm; n=1; method=caliper; basis=resolution; physical_validation=not_claimed | [12.47 mm, 12.49 mm] | outside |
| g1c6 | length=12.52 mm; uncertainty=0.01 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed | [12.51 mm, 12.53 mm] | outside |
| g1c7 | length=12.55 mm; uncertainty=0.02 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed | [12.53 mm, 12.57 mm] | outside |
| g1c8 | length=12.50 mm; uncertainty=unknown; n=4; method=micrometer; basis=unknown; physical_validation=not_claimed | unknown | unknown |
| g2c1 | length=10.04 mm; uncertainty=0.04 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed | [10.00 mm, 10.08 mm] | inside |
| g2c2 | length=10.03 mm; uncertainty=0.03 mm; n=5; method=micrometer; basis=expanded; physical_validation=not_claimed | [10.00 mm, 10.06 mm] | inside |
| g2c3 | length=10.05 mm; uncertainty=0.03 mm; n=1; method=caliper; basis=resolution; physical_validation=not_claimed | [10.02 mm, 10.08 mm] | inside |
| g2c4 | length=10.04 mm; uncertainty=0.03 mm; n=5; method=micrometer; basis=expanded; physical_validation=not_claimed | [10.01 mm, 10.07 mm] | inside |
| g2c5 | length=10.00 mm; uncertainty=0.01 mm; n=1; method=caliper; basis=resolution; physical_validation=not_claimed | [9.99 mm, 10.01 mm] | outside |
| g2c6 | length=10.08 mm; uncertainty=0.01 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed | [10.07 mm, 10.09 mm] | outside |
| g2c7 | length=10.11 mm; uncertainty=0.02 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed | [10.09 mm, 10.13 mm] | outside |
| g2c8 | length=10.04 mm; uncertainty=unknown; n=4; method=micrometer; basis=unknown; physical_validation=not_claimed | unknown | unknown |
| g3c1 | length=12.50 mm; uncertainty=0.04 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed | [12.46 mm, 12.54 mm] | inside |
| g3c2 | length=12.49 mm; uncertainty=0.03 mm; n=5; method=micrometer; basis=expanded; physical_validation=not_claimed | [12.46 mm, 12.52 mm] | inside |
| g3c3 | length=12.51 mm; uncertainty=0.03 mm; n=1; method=caliper; basis=resolution; physical_validation=not_claimed | [12.48 mm, 12.54 mm] | inside |
| g3c4 | length=12.50 mm; uncertainty=0.03 mm; n=5; method=micrometer; basis=expanded; physical_validation=not_claimed | [12.47 mm, 12.53 mm] | inside |
| g3c5 | length=12.46 mm; uncertainty=0.01 mm; n=1; method=caliper; basis=resolution; physical_validation=not_claimed | [12.45 mm, 12.47 mm] | outside |
| g3c6 | length=12.54 mm; uncertainty=0.01 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed | [12.53 mm, 12.55 mm] | outside |
| g3c7 | length=12.57 mm; uncertainty=0.02 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed | [12.55 mm, 12.59 mm] | outside |
| g3c8 | length=12.50 mm; uncertainty=unknown; n=4; method=micrometer; basis=unknown; physical_validation=not_claimed | unknown | unknown |

Goal 3's cases 2, 3 and 4 are outside under goal 1's limits, so a model that ignores the goal fails there.

## Frozen run order (36 calls, size 4 first)

Goals in the listed order; per goal quartet one `(1,5,3,8)` forward and reversed, then quartet two `(2,6,4,7)` forward
and reversed (12 size-4 calls); then singletons by case in the order 1, 5, 3, 8, 2, 6, 4, 7, each across goals 1, 2,
3 (24 calls). Job IDs `classify_A` to `classify_D` by position.

| Slot | Cell | Goal | Cases | Expected | Prompt sha256 |
|---|---|---|---|---|---|
| 1 | size4 | 1 | 1, 5, 3, 8 | inside, outside, inside, unknown | 24531e9f02c8 |
| 2 | size4 | 1 | 8, 3, 5, 1 | unknown, inside, outside, inside | b69a3698d8a4 |
| 3 | size4 | 1 | 2, 6, 4, 7 | inside, outside, inside, outside | 8fb9da3f4f8f |
| 4 | size4 | 1 | 7, 4, 6, 2 | outside, inside, outside, inside | b079d95e10e1 |
| 5 | size4 | 2 | 1, 5, 3, 8 | inside, outside, inside, unknown | f18558cc5988 |
| 6 | size4 | 2 | 8, 3, 5, 1 | unknown, inside, outside, inside | 4f401f24c0a9 |
| 7 | size4 | 2 | 2, 6, 4, 7 | inside, outside, inside, outside | 08a60086051b |
| 8 | size4 | 2 | 7, 4, 6, 2 | outside, inside, outside, inside | 2cc69bb81d91 |
| 9 | size4 | 3 | 1, 5, 3, 8 | inside, outside, inside, unknown | 201cea6eb2bf |
| 10 | size4 | 3 | 8, 3, 5, 1 | unknown, inside, outside, inside | cc728f336a6f |
| 11 | size4 | 3 | 2, 6, 4, 7 | inside, outside, inside, outside | 38c968f12b66 |
| 12 | size4 | 3 | 7, 4, 6, 2 | outside, inside, outside, inside | d7fbf495f740 |
| 13 | size1 | 1 | 1 | inside | 249fd097c858 |
| 14 | size1 | 2 | 1 | inside | cf34ffa51c42 |
| 15 | size1 | 3 | 1 | inside | 84f5bac1544d |
| 16 | size1 | 1 | 5 | outside | 124afdff5c58 |
| 17 | size1 | 2 | 5 | outside | affc3a0e447f |
| 18 | size1 | 3 | 5 | outside | c5de12768fc9 |
| 19 | size1 | 1 | 3 | inside | a30e4bad162a |
| 20 | size1 | 2 | 3 | inside | 01a7773d3ede |
| 21 | size1 | 3 | 3 | inside | f97f76610056 |
| 22 | size1 | 1 | 8 | unknown | ab86a7570711 |
| 23 | size1 | 2 | 8 | unknown | 2d597e7387fe |
| 24 | size1 | 3 | 8 | unknown | 46d410644c53 |
| 25 | size1 | 1 | 2 | inside | e3a9a3d5648d |
| 26 | size1 | 2 | 2 | inside | f23dffe16798 |
| 27 | size1 | 3 | 2 | inside | 9300452d4109 |
| 28 | size1 | 1 | 6 | outside | 831d87565a33 |
| 29 | size1 | 2 | 6 | outside | fd277cc29185 |
| 30 | size1 | 3 | 6 | outside | b601f24d2652 |
| 31 | size1 | 1 | 4 | inside | ba5f398e2264 |
| 32 | size1 | 2 | 4 | inside | f278169e292b |
| 33 | size1 | 3 | 4 | inside | fe1148ac76b8 |
| 34 | size1 | 1 | 7 | outside | cdb747712b06 |
| 35 | size1 | 2 | 7 | outside | 5a04f067f7f3 |
| 36 | size1 | 3 | 7 | outside | 247f6b685507 |

## Gates

| Gate | What it covers | Command |
|---|---|---|
| G0 | The freeze holds: every pinned file, the regenerated 36 packets and the samples equal the record | `adopt.py freeze` |
| G1 | The full suite, including `tests/test_ref_values.py` (value refs, ordered inputs) and `tests/test_adopt.py` (limits, check, cases, order, packets, scoring, run loop, verdict, guards, predicate, dry gate) | `unittest discover -s tests` |
| G2 | Zero-token dry gate: the qualification run loop on fixtures, the v2 suite through step4's own dry gate on the v2 copies, and the adoption fixtures | `adopt.py dry` |
| G3q | Qualification: both cells, every call passing | `adopt.py qualify --expect ed082d4d…` |
| G3s | The five-scenario suite under the amended G3b predicate, after G3q passed | `adopt.py suite` |
| Adoption | Both cells pass, all five scenarios `pass_g3b`, and every workflow classification right on its first attempt (exactly 12: clean 4, interrupt 4, stale 4) | printed by `suite` and `report` |

A qualification call passes when it is wire-valid (the probe's strict parser: header, one line per ID, no salvage),
every member is exactly its frozen label, it finished within 300 s, its route is `ok` (the `modelUsage` keys are
exactly `claude-sonnet-5-5`) and its accounting is complete (every `modelUsage` counter present). The first call that
does not pass writes a terminal halt: the attempt has failed, nothing resumes it, unrun slots stay untested, and a
second attempt is a new preregistration. An unfinished launch (the harness died during a call) is a terminal halt
and counts as a failed call of its cell. A cell is `pass` only when all its scheduled calls passed; `report`
re-scores every retained envelope and any change, re-scoring difference or ledger damage makes the verdict
`incomplete`. Thinking tokens are reported per call (unknown is never zero), descriptively.

The suite is G3b's predicate as amended (d89ac55c), with the two-ref expected inputs, the recovery policy, the C5
checks and the expected primary launches 3, 0, 3, 5, 0 (verified in G2). It refuses unless the freeze holds, the
qualification evidence at this digest passes both cells, the CLI is 2.1.306 and the workspace is fresh.

## Allocations (ceilings, separate, no borrowing)

| Phase | Tokens | Launches | Time | Other |
|---|---:|---:|---|---|
| Qualification | 120,000 | 36 | 300 s per call, 14,400 s from the first launch | one call in flight, 5,000 admission reserve, unknown usage charged at 5,000 |
| Suite | 64,000 | 24, at most 10 per scenario | 300 s per call, 3,600 s per scenario, 14,400 s suite envelope | one call in flight (quota group `claude-cli`), 5,000 reserve |

Paid exposure at the ceilings is 184,000 tokens. O1's live run is done and spent 55,413 of its 150,000 (its signed
exposure made the 334,000 figure); the owner should still see 184,000 against the weekly quota before either run.

Expected spend, from measured numbers and not a prediction: size-4 cell about 33,000 (probe arm C 2,720 to 2,873 per
call on a 1,137-byte packet; these are 1,206 to 1,219 bytes), singleton cell about 58,000 to 60,000 (Sonnet size-1
gate 2,385 per call plus the longer op and a second ref; 758 to 761 bytes), qualification about 93,000; suite about
29,000 to 31,000 (G3b live3: 31,309 tokens for 12 launches; 11 launches expected here without recovery). About
122,000 in all if nothing fails.

## Commands (PowerShell, repo root)

```powershell
$env:TIKTOKEN_CACHE_DIR = ".token-cache"; $env:PYTHONIOENCODING = "utf-8"
# G0: must print "frozen": true with the digest above
.venv/Scripts/python.exe bench/step4/adopt.py freeze
# G1: the full suite
.venv/Scripts/python.exe -m unittest discover -s tests
# G2: zero-token dry gate, must print "pass": true
.venv/Scripts/python.exe bench/step4/adopt.py dry --workspace .oz-runtime/ad-dry
# G3q: the 36 qualification calls (paid). The probe harness refuses while ANTHROPIC_BASE_URL or any route or effort
# variable is set; remove them from this shell first.
Remove-Item Env:ANTHROPIC_BASE_URL -ErrorAction SilentlyContinue
$env:ADOPT_LIVE_CONFIRM = "1"
.venv/Scripts/python.exe bench/step4/adopt.py qualify --expect ed082d4da16d4e045f0c2e9d34c8c01fb2fb82289fdb0e71c49a48c6b4ddf0f7
# G3s: only after both cells passed; one suite, fresh workspace, no reruns (paid)
.venv/Scripts/python.exe bench/step4/adopt.py suite --workspace .oz-runtime/ad1 --prefix ad1
# Verdicts, thinking tokens and classify-stage tokens next to G3b live2 (zero tokens)
.venv/Scripts/python.exe bench/step4/adopt.py report --workspace .oz-runtime/ad1 --prefix ad1
```

`qualify` writes `bench/step4/adopt-qual/report.json`; the suite writes `report-live-ad1.json` and
`report-adopt-ad1.json` in its workspace and `flows/<request_id>/execution-record.json`. Rerunning `qualify` after a
halt launches nothing.

## Zero-token dry gate (G2) at this freeze

Result: **`pass`: true** (about one minute, no process except the fixture adapter and the interrupted scenario's
hard-killed `adopt.py run-flow` invocations).

1. Qualification run loop on fixture replies: all 36 pass with the 12 size-4 calls first and exactly the frozen
   prompts; a resume launches nothing; a wrong label at slot 5 stops after 5 launches (size-4 `fail`, size-1
   `untested`); a wire rejection at slot 20 fails only the singleton cell; route mismatch, missing accounting, a
   deadline and a reply past 300 s are each terminal; the token ceiling admits 4 calls of 30,000; the four-hour
   envelope stops before slot 6; an unfinished launch is terminal and fails its cell; a wrong digest launches nothing.
2. The v2 suite (step4's own dry gate on the v2 copies): clean 3, repeat 0, interrupt 3, stale 5, bump 0 launches
   (11, packets 4,4,4 / none / 4,4,4 / 4,4,1,1,4 / none, memo hits 0, 12, 0, 6, 20), all `pass_g3b`, strict; C5 four
   of four; recovery fixtures 11 of 11 (including the atomic wire rejection of a size-4 classify packet and a
   second-attempt failure); executor sabotage 6 of 6; G3b sabotage 21 of 21; feasibility 4 of 4. 7,336 fixture
   tokens, accounting complete. The G4 baseline smoke does not apply (v2 has no baseline arm; `g3b.json` says so).
3. Adoption fixtures, each on an isolated copy of the clean state: the limits agree with every consumer and a goal
   that disagrees is refused; an interval bound from another record (`classify_A` interval `/bounds/B`) is flagged by
   the graph check and, run through the executor anyway, is rejected twice by `mat_classify_interval` and blocks
   delivery; an older node 11 generation (A bumped to rev 2 between the classify dispatch and its commit) has every
   classify commit refused, the classifications run again on the current interval and the delivery cites A rev 2;
   a memo miss when only the interval ref changes (A miss, B, C, D hits); a goal change changes the identity and
   misses all four; the clean and stale classify packets equal the generator's byte for byte; the 0.01-breach records
   recompute and the two-ref check accepts right labels and refuses a wrong label, a wrong pairing and a stale
   interval; a stale trace carrying the old interval with the new record is a `stale_input` finding.
4. On fixtures, the adoption verdict is `adopted` when both cells pass and the suite passes with 12 first-attempt
   classifications accepted.

## Freezes this build changed

The executor changes (`oz_flow.py`, `oz_do.py`, `oz_runtime.py`) and the pack-aware harness files (`workflow.py`,
`g3b.py`, `evaluator.py`, `fixture_adapter.py`, `step4.py`) are pinned by older freezes. Each was rewritten with its
own `freeze --write` after its own dry gate passed unchanged on the new code; the old records stay in git and every
verdict stands for the freeze it was made under.

| Freeze | Was | Now | Re-run at the new freeze |
|---|---|---|---|
| G3b (`freeze-g3b.json`) | 040cfd41 | `97943a557df63f1fceb355e3586644a87c8c74ca31ba8b6a269e17e7c7aeae0a` | `step4.py dry` pass (11 launches, recovery 11/11, sabotage 6/6, G3b sabotage 21/21, C5 4/4, baseline smoke); `replay-live1` and `replay-live2`: all traces match, all independent verdicts agree |
| O1 (`bench/o1/repair-handoff-20-v1/freeze.json`) | 32333561 | `0aa5ecf6cb453c195654679c8b7902768a0aff1a909263968100abfae386c933` | `o1.py dry` every block passes (clean 2, repeat 0, interrupt 2, stale 4, bump 0) |
| Probe (`boundary.py`) | 520c98e8 | unchanged | nothing it pins was edited |

O1's live G3c result (pass, 8 launches, 55,413 tokens) stands for freeze 32333561 and is not rerun; no file under
`bench/o1/live1/` was touched. G3b live2 and live3 stand for 02119a17 and 040cfd41.

## Build decisions and deviations

1. v2 is a new pack directory; v1 stays byte for byte (its live records, the probe freeze and the G3b freeze pin it).
   `workflow.py`, `g3b.py` and `evaluator.py` read their pack from a module global set by `packs.load` before their
   code runs, so the v1 modules other harnesses import are untouched; the v2 suite runs on a copy of `step4.py` with
   its workflow, predicate and evaluator rebound (`packs.harness`).
2. The plan names the `oz do` and dispatcher extensions; the value form also needs the inbox to store a ref job's
   JSON value (`Inbox.complete(..., values=)`, opt-in, default unchanged).
3. Qualification packets are generated without the workflow check pinned on the request: `mat_classify_interval`
   checks the workflow's own limits, while goals 2 and 3 have others, and the packet bytes do not depend on checks.
   The clean and stale packets are generated with the check pinned and equal the executor's flow packets.
4. Qualification calls are not `oz do` calls: they follow the probe (fresh `claude -p` per call, raw evidence, the
   probe's strict parser), so there is no memo, retry, recovery or acceptance check on that path. The operation,
   goal sentence, value form, layout and IDs are the workflow's (checked byte for byte above).
5. Every non-passing qualification call is terminal, including incomplete accounting and an unfinished launch (the
   probe allowed an acknowledged continuation; here any failure ends the attempt). No `claude-cli` quota slot is taken
   for qualification calls; they run one at a time in one process.
6. Ordered refs are named `<node>-record` and `<node>-interval` in the stage request; job IDs are unchanged. An
   ordered or value-form operation's identity also hashes its input order and value forms.
7. Case records take n, method and basis from the four workflow records (profiles A, B, C, D); case 8 uses D's.
8. The adoption verdict counts first attempts: exactly 12 classifications (clean 4, interrupt 4, stale 4), all
   accepted. A pass that needed a resend fails adoption even when `pass_g3b` holds.
9. The O1 freeze file was rewritten by `o1.py freeze --write` (its own path for a pinned-file change). The live record
   and results under `bench/o1/` are unchanged.

## Claim scope

The declared cells only: Sonnet 5.5, CLI 2.1.306, default effort, this op text, this goal template with two-decimal mm
limits, two-decimal intervals, the frozen value form and layout, sizes 4 and 1; and the one observed suite. Extract
and bounds stay experimental compositions. No reliability, savings, model-necessity or O1 claim follows. The author
guidance (pass a checked intermediate explicitly) cites one probe, one packet, six calls per arm.
