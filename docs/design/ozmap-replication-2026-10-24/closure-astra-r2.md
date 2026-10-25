This is a static review of F2 against A4, A4.13 and A4.14. I did not execute the harness or inspect operation content. Section D reports 534 passing tests; that supports the covered scenarios but does not cover the paths below.

**1. Closure table**

Paths are relative to `bench/ozmap_rep/`. For earlier CHANGE items, `closed` means no outstanding BLOCKER under A4.14.2. It does not mean the execution prerequisite is satisfied.

| Item | Disposition | Evidence |
|---|---|---|
| O1, Astra 10 | closed | `CellRun.execute` marks ordinary timeouts as killed. `after_group` converts a retryable incomplete outcome to `unsettled`, prevents retry and stops the cell. Complete terminal outcomes remain preserved. The two O1 regressions cover this distinction. |
| O2, Astra 12 | closed | `worker_probe` and `worker_path_logins` now hold `verified_guard`; both perform a protected `recheck` before their children. The O2 regressions check guard coverage and refusal before launch. |
| O3, Astra 13 | open | The handled `SpawnFailure` path now preserves evidence, but `_guarded_probe` still deletes its durable marker before recording a detected disclosure. A crash in that interval leaves the disclosure only in raw files that `score_run` does not inspect. Precise path below. |
| O4, Astra 15 | closed | Recorded probe disclosures now enter `cell_findings` through their structured `cell` field. The extended item 15 test and unchanged RTC1.1 disclosure test require `invalid` and exclusion from `interrupted`. O3 concerns the earlier evidence publication boundary. |
| O5, Astra 32 | closed | D6 is required by `REQUIRED_RULINGS`, with two bound annexes, content checks and classification and operations bindings. `_freeze_problems` also invokes `bound_problems`. This closes the bypass; it does not establish that the annexes have been completed. |
| Astra closure N1, round 3 CHANGE 22 | closed | `decode_sonnet` preserves present contradictions despite missing counters. `account_usage` avoids missing counter indexing. `judge_sonnet` recovers negative counter evidence from envelopes rejected by the adapter. Decoder and envelope regressions cover the reported cases. |
| Opus closure N1 | closed | Structured attribution replaces message matching for the reported evaluation cell findings. Regressions cover unledgered attempts, duplicate terminal attempts and probe disclosures. The additional telemetry omission is N1 below. |
| RTC1.1 | closed | Both reported evaluation cell cases are addressed: probe disclosures are attributed structurally, and crashed cells can receive validity without a later admission. N1 below identifies the remaining telemetry scope gap. |
| RTC1.2, RT3.2 | closed | `login_identity` reads access and identity token components; shared components refuse separation, and an existing credential document without identity also refuses. The original stale copy reproduction remains unchanged and is reported passing. |
| Astra 1 | closed | Existing annex binding remains; F2 extends it to D6 and adds scoring checks against the run bound ruling records. |
| Astra 2 | closed | D1 and its attribution annex remain required by readiness. Their absence is a launch prerequisite CHANGE. |
| Astra 3, Opus B3 | closed | P5 requires the manifest and effective context annex. Their absence still blocks readiness. Actual procedure implementation remains required before countersigning; see C1. |
| Astra 4, Opus B4 | closed | Latest malformed quota observations remain rejected. P3 and its source annex remain required. The separation gate relocation does not bypass those requirements. |
| Astra 5 | closed | P4 annex and configuration consistency remain required; F2 introduces no omission of that gate. |
| Astra 9 | closed | Evaluation process supervision and the prohibition on sibling authentication propagation after an unsettled group remain. See C3 for the distinct worker path probe containment omission. |
| Astra 11 | closed | Both ledger directions and allocation checks remain. F2 adds structured attribution for their identified cell findings. |
| Astra 14 | closed | Reservation still checks the prepared generation, inventory and expiry under the authentication lock. |
| Astra 16 | closed | Prompt reconstruction, cost attribution, audit sample and warm eligibility checks remain. Their artifact findings now receive structured cell attribution. The earlier launch evidence reconstruction CHANGE remains. |
| Astra 17, recovery component | moot under A4.14.1 | No recovery or resumed comparison is restored. |
| Astra 17, rounding component | closed | Outward rounding remains unchanged. |
| Astra 23 | closed | Independent Sonnet lifecycle and route checks remain. Model prefix precision remains a CHANGE, not a newly demonstrated bypass in F2. |
| Opus B1 | closed | Missing quota coverage still stops execution. An attended observation plan or prospective amendment remains necessary. |
| Opus B2 | closed | Required ruling slots and annexes remain enforced, now including D6. |
| RT3.1 | closed | Ancestor discovery checks and placement outside the owner profile remain. Effective user scope context remains subject to P5. |
| RT3.3 | closed | Live mode still requires the owner sessions directory and records observation provenance. |
| D-R2-1 | closed | No resend or recovery path is restored. |
| D-R2-2 | closed | `--ephemeral` remains required. |

**Remaining O3 BLOCKER: the normal probe completion path can lose a detected disclosure at a crash boundary**

**Clauses:** A4.2, A4.14.1, A4.14.2 and A4.14.5.

**Current path and input state:** In F2, `run.py:CellRun._guarded_probe`, consider the first features probe of an evaluation cell, before any evaluation attempt:

1. The probe finishes and its raw stdout or stderr contains credential material.
2. `redact.redact` detects the disclosure.
3. `iso.finish` and `reconcile` complete with unchanged authentication and no authentication failure.
4. `path.unlink()` removes the probe marker.
5. The runner crashes before `_append(..., 'evidence/probe-disclosures.jsonl', ...)`.

The new raw files survive because their deletion occurs later. However, no durable disclosure record or probe marker remains.

In `score.py:score_run`, probe evidence is consumed from disclosure and uncertainty JSONL records and from outstanding markers. Captured model streams are inspected separately. There is no scan of these surviving probe raw files. Thus the cell receives no disclosure finding. If its state qualifies as stopped, it becomes `interrupted`; otherwise the first probe can leave it outside stopped cell classification altogether.

This is a precise crash interval in the current producer ordering, not hypothetical editing of preserved evidence. The handled exception regressions do not cover it.

**Minimal fix:** Persist the sanitized disclosure or clean completion evidence before removing the durable probe marker. Keep the marker through every failure before that publication. A scorer encountering an unfinished probe must attribute uncertainty to its cell. Add a crash injection between reconciliation and disclosure publication and require `invalid`, with raw evidence preserved.

**2. New BLOCKERs**

**N1. Stopped telemetry cells are excluded from the new validity disposition loop**

**Claim:** F2 can record a stopped telemetry cell’s isolation failure while never assigning that cell the validity A4.14.1 requires. This is the telemetry counterpart of RTC1.1’s omitted cell disposition.

**Clauses:** A4.14.1, A4.14.2 and A4.14.5.

**Precise path and input state:**

1. In `run.py:TelemetryRun.worker_path_logins`, a resumed worker path login probe raises `SpawnFailure` with `terminated=False` and no complete raw output.
2. The new `probe_evidence` call writes `probe-failures.jsonl` and `probe-uncertain.jsonl`, both attributed to `self.spec['id']`, which is `telemetry`.
3. `worker_path_logins` raises `Stop(..., interrupt=True)`. `TelemetryRun._run_locked` passes that to `conclude`, which writes `cells/telemetry/INTERRUPTED.json`.
4. In `score.py:score_run`, the uncertainty row correctly calls `flag(..., r.get('cell'))`, producing `cell_findings['telemetry']`.
5. However, `specs` and `states` are constructed exclusively from `cell_specs()`, the 16 evaluation cells. The stopped cell loop iterates only `states.items()`. Consequently it never examines the telemetry stop record or applies `cell_findings['telemetry']`.

The report can therefore contain the global isolation finding while omitting the stopped telemetry cell from `cell_states`, `invalid_cells` and its required stopped cell disposition. A global failure does not cure this omission, for the same reason it did not cure RTC1.1.

This finding does not claim that telemetry costs should enter evaluation metrics or that evaluation gates pass.

**Minimal fix:** Include telemetry and any other executed administrative cell in the stopped cell validity inventory, while continuing to exclude them from evaluation performance computations. Add a regression for the path above requiring telemetry state `invalid`, preservation of its evidence and exclusion from `interrupted`.

**3. CHANGEs**

**C1. Before freeze:** Complete and countersign P1 through P5, D1, D2 evidence through P5, and both D6 annexes. Missing required bindings refuse readiness. Annex approval must also verify that the promised executable procedures exist; hash binding alone establishes document identity.

**C2. Before freeze:** D6 must verify oracle correctness, classification, contract extraction, consumer checks, all 48 representative and 16 challenge cases, reviewer independence under A4.8, and sealing and access chronology. Those semantic checks cannot be established from this blind pack.

**C3. Before further admission:** `worker_path_logins` creates an in memory marker but never journals it through `probe_marker` or passes an `on_start` callback. After its uncontained `SpawnFailure`, `stop_cell` can see no outstanding marker and report containment. Persist supervision and process identity, and require a run stop when termination is unestablished. The supplied failure path already records global invalidity, so I do not assert a separate unflagged result BLOCKER.

**C4. Before live execution:** Record the attended quota observation plan or obtain the prospective A4.2 amendment. Keep `--ephemeral` until an approved revision changes it consistently.

**C5. Retained:** Resolve the matched job correctness interpretation, especially BoolQ’s added errors, before freeze. Retain expected job coverage checks, legitimate unresolved audit handling, explicit Sonnet identity mapping and preparation reporting by role and category.

**C6. Verification wording:** The O1 timeout regression modifies a completed fake capture to represent a timeout; it does not itself exercise an actual timeout kill. Describe that coverage accurately and retain a process level timeout check.

O3 remains open and N1 meets the explicit stopped cell validity rubric. Under A4.14.3, this second closure round ends with the workflow stopped for the owner.

Verdict: DO NOT SIGN