**0. Item 0**

A4.14 confirmed: Astra A

The integrated text includes both requested replacements. This is a static review of the blind evidence and source excerpts, reconciled with section F. I did not execute the harness, independently verify the reported test results, inspect operation content, or make evaluation calls.

**1. Closure table**

Paths below are relative to `bench/ozmap_rep/`. Each row has one disposition. Residual blockers are detailed immediately afterward.

| Item | Disposition | Evidence |
|---|---|---|
| Astra 1 | closed | `annex_problems` binds the specified annex bytes and configuration. D6 remains separately open under item 32. |
| Astra 2 | CHANGE under A4.14.2 | Agree with the D1 launch prerequisite reasoning. Its required attribution annex is now bound. |
| Astra 3 | CHANGE under A4.14.2 | Agree with the P5 and D2 prerequisite reasoning. Their implementation and evidence remain required before approval. |
| Astra 4 | CHANGE under A4.14.2 | Malformed latest observations are rejected. Agree that the remaining P3 requirements belong before freeze. |
| Astra 5 | CHANGE under A4.14.2 | Agree with the P4 prerequisite reasoning. Missing or inconsistent notice approval prevents readiness. |
| Astra 9 | closed | Supervised trees and the group failure branch prevent sibling propagation before established termination. |
| Astra 10 | open | Ordinary timeout termination bypasses the incomplete stream safeguard. See O1. |
| Astra 11 | closed | Stop accounting adds missing ledger rows; scoring checks both directions; predecessor stops block admission. |
| Astra 12 | open | The guarded verification fix covers model launch groups, but local probes remain unguarded. See O2. |
| Astra 13 | open | Recovery propagation is removed, but a terminated local probe can lose its output and receive only interruption treatment. See O3. |
| Astra 14 | closed | Reservation checks expiry and inventory against the prepared baseline generation under the authentication lock. |
| Astra 15 | open | Disclosures now fail global isolation, but the affected stopped cell can still be reported as interrupted with no finding. See O4. |
| Astra 16 | CHANGE under A4.14.2 | The identified attribution, ordering, audit set and warm eligibility checks are added. Agree with the ledger’s remaining evidence reconstruction reasoning. |
| Astra 17 | moot under A4.14.1 | Recovery timing cannot support a resumed comparison. The separate outward rounding correction is present. |
| Astra 23 | closed | Harness checks now require turn, permission and model evidence independently of ambient `OZ_MODEL`. See C4 for identity precision. |
| Astra 32 | open | Readiness does not require D6 or its operation dependent attestation. See O5. |
| Opus B1 | CHANGE under A4.14.2 | Agree. Missing quota coverage stops execution; an attended plan or signed amendment remains necessary. |
| Opus B2 | CHANGE under A4.14.2 | Agree for the specified P1 through P5 and D1 slots and annexes. D6 is separately addressed above. |
| Opus B3 | CHANGE under A4.14.2 | Agree with the unsigned P5 and D2 prerequisite reasoning. |
| Opus B4 | CHANGE under A4.14.2 | Agree with the unsigned P3 prerequisite reasoning. |
| RT3.1 | closed | Extended discovery scan and placement outside the owner profile address the reported ancestor paths. User scope discovery remains a P5 requirement. |
| RT3.2 | closed | Session identity comparison rejects the reported rotated copy; unexplained absent credentials and configured nonfile stores refuse. |
| RT3.3 | closed | Live dispatch refuses a different sessions directory and records observation provenance. |
| D-R2-1 | closed | The replacement assertions prohibit resend and retain execution invalidity. |
| D-R2-2 | closed | `--ephemeral` remains required under the current signed text. |

Every BLOCKER in G1 is represented in this table.

**O1. Astra 10: ordinary timeouts still hide execution uncertainty.**

**Clauses:** A4.3, A4.11, A4.14.1 and A4.14.2.

**Path and input:** A dispatched Codex child emits only `turn.started`, then hangs. In `run.py:spawn`, `TimeoutExpired` kills the tree and returns ordinary raw output with `timed_out=True`. It does not raise `SpawnFailure`. `judge_codex` returns `infrastructure_failure` when no terminal reply or tool verdict exists. In `CellRun.after_group`, conversion of a retryable incomplete stream to `unsettled` requires `c.get('spawn_failure')`, which this path lacks. `run_batches` can therefore retry, and accounting incompleteness produces an inconclusive comparison rather than execution invalidity.

Established process termination does not establish what the terminated process executed before its stream ended.

**Minimal fix:** Apply the incomplete terminal evidence check to every terminated dispatched child, including normal timeout handling. Preserve complete terminal outcomes; otherwise record uncertainty and stop without retry.

**O2. Astra 12: local probes do not use the new protected identity check.**

**Clauses:** A4.2 and A4.14.2.

**Path and input:** `run.py:CellRun.worker_probe` still calls `self.exe.verify()` followed by `run_local`, without `verified_guard`. `TelemetryRun.worker_path_logins` likewise verifies before its unguarded probe loop. Substitute an executable or companion after verification, let that version return acceptable login or feature evidence, then restore the frozen version before the guarded evaluation group. The certificate and feature record can describe the substituted implementation while subsequent launch verification passes.

This is the same runtime substitution boundary item 12 required local probes to close.

**Minimal fix:** Hold `verified_guard(live=True)` across each local probe group, with the protected identity checked immediately before each child and protection retained until tree termination.

**O3. Astra 13: a local probe’s uncertain output can disappear before scoring.**

**Clauses:** A4.2, A4.14.1 and A4.14.2.

**Path and input:** A resumed feature or login probe emits credential material or an authentication error, then `communicate()` raises. `run.py:run_local` invokes `_end_tree` with `raw=None`; after termination, `SpawnFailure` carries no captured output. `CellRun.worker_probe` handles `exc.terminated` by reconciling as an authentication failure and deleting the marker. `conclude(..., force=True)` then interrupts the cell.

No probe capture or disclosure record survives for the scorer to inspect. The conservative authentication stop protects propagation but does not establish isolation validity.

**Minimal fix:** Preserve probe output within the credential boundary and its sanitized evidence. If output completeness cannot be established, retain a structured isolation uncertainty finding that makes the cell invalid. A proven never resumed child may retain its distinct disposition.

**O4. Astra 15: the disclosure regression does not check the required cell verdict.**

**Clauses:** A4.14.1, A4.14.2 and A4.14.5.

**Path and input:** Use the existing `test_item15_a_probe_disclosure_fails_isolation_and_certification` scenario: telemetry succeeds, then the first feature probe discloses a credential before any evaluation attempt. `worker_probe` removes its marker, records the disclosure and forces interruption.

In `score.py:score_run`, the disclosure correctly enters `isolation_problems`. However, `invalid_cells` associates findings only through attempt identifiers or remaining marker filenames. This cell has neither. It therefore remains in `validity.interrupted`, and `render_md` explicitly lists it under “stopped cells interrupted, no finding.”

Global isolation failure does not cure the contradictory cell disposition prohibited by A4.14.2.

**Minimal fix:** Attribute findings using structured cell identifiers, including probe disclosures, instead of matching message text against attempt identifiers. Extend the existing regression to require cell state `invalid` and absence from `validity.interrupted`.

**O5. Astra 32: D6 is not an enforced launch prerequisite.**

**Clauses:** A4.1, A4.8 and A4.14.2.

**Path and input:** Populate valid signed P1 through P5 and D1 slots, their required annexes and matching configuration, while omitting D6 and its independent operation attestation. `config.REQUIRED_RULINGS` contains no D6 slot; `rulings.ANNEXES_REQUIRED` contains no equivalent attestation requirement. `readiness_problems` can return an empty list, as the new readiness fixture demonstrates without D6. `freeze_command` and subsequent `verify_freeze` consequently have no D6 absence to reject.

A hash consistent classification and oracle can then reach reporting without the independent semantic verification required by the protocol being flagged as missing. Being a workflow step does not make this prerequisite mechanically enforced.

**Minimal fix:** Bind a required D6 verification record and independent operation attestation to the frozen inputs, enforce their presence at freeze and live verification, and verify their bindings during scoring. The blind attestation must cover oracle correctness, classification, contract extraction, consumer checks, the 48 representative and 16 challenge cases, and sealing and access chronology.

**2. New BLOCKERs**

**N1. Demonstrated Sonnet accounting violations remain merely incomplete.**

This was Astra round 3 CHANGE 22. It meets the explicit validity precedence requirement introduced by A4.14.2.

**Clauses:** A4.7, A4.11, A4.14.1 and A4.14.2.

**Path and input:** In the unchanged `usage.py:decode_sonnet`, the initial condition returns `status='incomplete'` for any negative counter, before recording an accounting violation. For example, decoded usage `{input_tokens: -1, cached_input_tokens: 0, output_tokens: 1}` takes that branch. A missing output counter also masks a present `cached_input_tokens > input_tokens` contradiction.

`run.py:account_usage` preserves this incomplete status. `CellRun.anomalies` stops on usage status `invalid`, and `score.py:score_run` records demonstrated accounting failures through that same status. Rejudging uses the same decoder, so it reproduces the omission. With otherwise valid records, the comparison becomes inconclusive rather than invalid.

**Minimal fix:** Detect present contradictions independently of completeness, preserve both findings, and give established invalidity precedence. Update `account_usage` so invalid partial usage does not index missing counters. Test negative counters and cache contradictions both with and without other missing fields.

**3. CHANGEs**

**C1. Before freeze:** Complete and countersign P1 through P5, D1 and the bound D2 evidence, including the promised executable checks. Their current absence correctly prevents readiness; approving annex bytes must not substitute for implementing the procedures they require.

**C2. Before live execution:** Record the attended quota observation plan or obtain the prospective A4.2 amendment. Preserve `--ephemeral` until that amendment is signed and activated consistently.

**C3. Before freeze:** Resolve the existing matched job correctness interpretation, especially BoolQ’s “no added gold errors.” Report error transitions so equal aggregate counts do not conceal changed error locations.

**C4.** Replace Sonnet model prefix acceptance with an explicit frozen identity or alias mapping. Also refuse unexplained missing login session identity rather than treating absence as evidence of independent login lineage.

**C5.** Retain the earlier completeness and audit disposition improvements: `DONE` should require expected resolution, and permitted unresolved audits should remain incomplete without manufactured artifact violations.

**C6.** Preserve observed usage diagnostics for multiple turns, report preparation by role and category, and label token sums containing unknown usage as partial. These supplement, rather than replace, N1.

**C7.** Update historical build descriptions to identify superseded recovery behavior and current paths. Add focused regressions for O1 through O5 and N1 within the remaining closure round.

Verdict: DO NOT SIGN