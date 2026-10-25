# Opus B sign-off of ruling P3 after repair commit 1bb148b (2026-10-25)

Reviewer: Opus B (fresh Opus workflow subagent). Scope: closure of Astra A blockers P3-H1 and P3-H2
(rulings/signoff-astra-p3.md) after P3 signature repair 1 (commit 1bb148b), rerun of the P3 tests and the full
harness suite. No model call, no Codex request. Sealed ASTs and bench/ozmap_rep/ops content were not read.
Claude weekly all models 76% before the review. Call logged in call-ledger.jsonl (Opus 49 of 70 after this call).

Verdict: Signed: Opus B P3

## Previous blockers

**P3-H1 closed.** quota.session_floor_problem now rejects an owner reading whose session start lies after the gate
time, after the reading, or out of order with its turn start, and headroom_gate applies it before
unreflected_allowance uses the session start to reduce C. The D5 rejection reason is kept as
d5_reason_informational.

* Regression tests `test_p3_h1_an_invalid_session_floor_rejects_the_owner_reading[30]`, `[-3]` and
  `test_p3_h1_the_d5_rejection_reason_is_kept` pass on 1bb148b.
* Against the unfixed gate (quota.headroom_gate of 1bb148b^ loaded from `git show 1bb148b^:bench/ozmap_rep/quota.py`
  and patched in by a pytest plugin) all three fail, so the tests exercise the defect.
* Astra's exact scenario on the live gate (reading 79 at gate minus 5 minutes, session start at gate plus 30 minutes,
  cap 62, charged 61, all 61 calls ending after the reading) now stops with "its session start lies after the gate
  time". Controls: a session start equal to the reading keeps all 61 late calls in C (C 62, bound 36.04 at U0 10);
  61 calls that ended before a valid session start are reflected (C 1, bound 10.42).
* A missing session start leaves the floor None, so C is the whole cap. That is conservative.

**P3-H2 closed.** headroom_gate validates every harvested observation; a value that is not a dict, or a harvest entry
that is not a list, stops.

* Regression tests `test_p3_h2_a_harvested_observation_that_is_not_a_dict_stops[None, x, 5, [None], True]` pass on
  1bb148b and all five fail against the unfixed gate.
* Astra's exact scenario (U0 10, C 62, m 0.21, harvested `{'a': [None]}`) now stops. Variants `(None,)`, `[{}]` and
  `{'percent': 5}` in place of the list also stop. An empty or None harvest entry carries no reading and passes,
  which matches the manifest (only a malformed reading blocks).

Regression run against the unfixed gate: 8 failed, 33 deselected. On 1bb148b: 8 passed.

## P3 tests and full suite

* test_p3_headroom.py, test_p3_d5_coverage.py, acceptance/test_a4_12_quota.py: 80 passed, 1 failed in the working
  tree. The failure is `test_the_bound_manifest_records_m_and_establishes_p3`: rulings.ruling_problems reports
  "P3-quota-observation.md is not the countersigned text (hash differs)". Cause: the uncommitted "Opus B sign-off P3"
  append of the previous review. The committed bytes hash to 51fd6602..., the value in config.SIGNED_RULINGS; the
  working copy hashes to 586ba00a....
* Full suite bench/ozmap_rep with rulings._sha pointed at the committed P3 ruling bytes (plugin in the scratchpad,
  nothing in the repo changed): 737 passed.

## CHANGE items (no blocker)

1. The P3 ruling hash in config.SIGNED_RULINGS must be rebound after the signature appends (the previous Opus B
   section and this one), or ruling_problems keeps P3 unbound. Worst outcome is a refused launch, which fails closed.
2. headroom_gate calls `(harvested or {}).items()`, so a harvested argument that is not a dict raises instead of
   returning a stop reason. The only caller (run.py harvested_observations) always builds a dict and an exception
   stops the gate, so this fails closed.
3. unreflected_allowance counts codex attempt rows ending before the floor, capped at charged, without deduplicating
   by attempt_uid. I found no writer path that appends two rows for one attempt (the stop path keys on the known
   set), so this is a hardening note: dedupe by attempt_uid before counting.

No new A4.14.2 blocker: nothing found lets the gate release a Codex call whose bound or U0 reaches 80.
