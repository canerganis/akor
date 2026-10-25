# Opus B sign-off of ruling P3 under owner decision 5 (2026-10-25)

Signer: Opus B, a fresh Opus workflow subagent (claude-opus-5-5). Ledger row role opus-b-signoff-p3-decision5 (Opus 47
of 70). No model call, no Codex model request, no Codex login, no external request, no credential content read or
printed. The sealed ASTs and the ops content were not read. Nothing was committed.

Scope: ruling P3 after commit 6f053f8 (static headroom bound, owner decision 5 in owner-decisions.md item 5, commit
cd83fe4). Question: does the bound P3 manifest's `freshness_and_causal_coverage.status` `established` follow from the
evidence, and does the live gate implement decision 5.

Result: P3 signed. No A4.14.2 blocker. Three CHANGE items below.

## Files checked at HEAD 6f053f8

| file | sha256 on disk | config.SIGNED_RULINGS P3 |
|---|---|---|
| rulings/P3-quota-observation.md (before this sign-off line) | 51fd66026901e0cfc92dd653952c35af53601be986dfcafd2abf61765478363e | equal |
| rulings/P3-quota-source-manifest.json | 5ee1f954de3d639b3c80377b69d55f461980e9ac1c483d4870da6bdd89123a71 | equal |

Appending the Opus B line changes the ruling file hash, so the driver has to rebind the P3 `sha256` in
config.SIGNED_RULINGS to the new bytes (sha256 after the appended section: 020d1986569ebda4a672396507433d7aad550346e5d07f7f34dd6c99392612e3). The
annex hash is unchanged.

## Reproductions

1. scratchpad opusb_repro.py, P3_coverage_gate cases (D5 gate, now informational): control ok at 10; owner reading
   without account hash, other limit_id, other window, no timestamp, three days old and a harvested reading without
   account hash all `ok: false`. `binding_with_not_established_annexes` now reports P3 annex status `established` and
   no ruling problem for the slot.
2. The same cases replayed against quota.headroom_gate, the live gate (scratchpad opusb_p3/repro_headroom.py): m read
   from the bound manifest is 0.21 with no problem; control ok (U0 10, C 62, bound 36.04); every invalid owner case
   and the unattributed harvested reading stop with the owner_problem or attribution reason; U0 53.95 passes (bound
   79.99), U0 53.96 stops (bound 80.00, strict inequality); a boolean or 101 percent stops; with one call ended before
   the owner session started and one after, C is 61 and reflected 1.
3. New and affected tests: test_p3_headroom.py, test_council_r1.py, test_ruling_repairs.py, test_p3_d5_coverage.py, 182
   passed. Full suite bench/ozmap_rep (acceptance and red team included): 729 passed (scratchpad
   opusb_p3_full_suite.txt).

## Independent check of the m evidence (scratchpad opusb_p3/verify_m.py, read only)

* All 15 INDEX.json source hashes equal the real owner rollout files.
* Every attributable baseline reading of 2026-10-24 across all owner rollouts (355 readings, any session start, any
  date directory, not only the fixture window): none lies strictly between 08:44:12.712 (33, the lower bracket) and
  14:40:17.595 (35, the upper bracket). The lower bracket is the last reading before the first pilot reservation
  (12:57:37.570), the upper is the first reading from a session started (14:40:11.945) after the last latest possible
  end (14:11:58.193). Both carry resets_at 1793382106. No reading decreased within one window that day.
* Pilot completeness: the codex reservations of the four pilot budget.sqlite files (2, 2, 29, 2) equal the fixture
  calls per run (35). Every fixture call is gpt-6.1-sol, effort high, codex-cli 0.160.0, timeout 1320 s; the longest
  elapsed time is 83.9 s.
* estimate_m on the fixtures gives m 0.21 (largest bound: output share, 0.2077), equal to the manifest.

The decision 5 elements the manifest must record are present: the bound (rule, factor 2, stop 80), m with its method,
sources, assumptions and estimate, C at launch 62 equal to EVAL_CAPS codex total, and the U0 limit at launch 53.96.
`established` follows from this evidence. The pre-cell gate (run.CellRun.gates) and the reservation gate
(run.CellRun.reserve_group, under the authentication lock) both call codex_quota_gate, which calls headroom_gate with
the owner_problem check first, so the D5 owner reading check stays a gate as decision 5 requires.

## CHANGE items (not blockers under A4.14.2)

C1. U0 at launch. Decision 5 says P3 is established when the manifest records U0 at launch. A hash bound annex cannot
hold a value measured after binding, so the manifest records the establishment reading (0.0), the launch limit 53.96
and a pointer to the `pre-cell` row of the telemetry cell in evidence/quota-gates.jsonl. This is the only non circular
reading, and the gate enforces and records it. The result report should cite that row (u0, owner_reading_at, bound) as
the launch U0. Worst case of omitting it: a missing provenance line, not a wrong result.

C2. Accounting lag in C. quota.unreflected_allowance counts a call as contained in U0 when it ended strictly before
the owner reading's session started. Server side lag is not measured (the manifest says so). The margin covers it: the
gate allows 2 x m = 0.42 points per call against a pilot mean of 0.086 and a pilot maximum of 0.21. Even if the whole
rise to 37 seen by 14:59 on 2026-10-24 were lagged pilot consumption, m would be (4 + 1) x 0.0692 = 0.35, still below
0.42. Worst case: the 80 line is approached sooner than estimated; the next gate's fresh U0 still stops at 80.

C3. Row level count. unreflected_allowance counts reflected attempts per attempts.jsonl row, not per attempt_uid as the
budget does; min(reflected, charged) bounds it. Only a duplicated row of a call that ended after the floor could lower
C, and I found no writer that duplicates a row (the stop handler checks the known uids). A dedupe by attempt_uid would
make this explicit.

## What this signature covers

The ruling text including the section "Owner decision 5" and the annex 5ee1f954 with status `established` under that
decision. It does not approve D5 as a launch gate (it stays informational) and does not reopen my earlier D5 position
in rulings/signoff-opus-2.md.

Signed: Opus B P3
