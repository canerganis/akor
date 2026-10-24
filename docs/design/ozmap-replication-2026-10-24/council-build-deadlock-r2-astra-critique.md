# Deadlock round 2: Astra critique of the Fable proposal (2026-10-24)

Verbatim reply of Astra A (gpt-6-astra, effort high, read only) to the joint step prompt, which carried Fable's proposal verbatim and Astra's own earlier co-solver proposal. Ops content and sealed ASTs were excluded. Logged in call-ledger.jsonl as role council-build-deadlock-joint-critic-r2. The joint decision is in council-build-deadlock-r2-joint.md.

These signatures approve prospective protocol text only. They do not certify implementation, evidence annexes, or launch readiness. I treat F1 to F9 as supplied reports, not independently verified observations.

## Per section verdicts

1. **S1: ACCEPT WITH CHANGES.** Keep the file-store argument, supported disable, and eight worker-path checks. Require **pinned execution-path analysis or a complete credential-access trace establishing exclusive file authentication**, including when `auth.json` contains account metadata. Recorded configuration is not observed source attribution. Recheck owner separation under the authentication lock immediately before worker reconstruction; reject path aliases, unreadable existing sources, and unexplained authentication representations. Preserve independent-login provenance and expiry checks. **Evidence:** F1, F2 and F9 partly address authentication; flag acceptance and negative probes do not establish exclusivity.

2. **S2: ACCEPT WITH CHANGES.** Retain the durable state machine and process identity requirements from my solution 1, including creation time and supervisor identity. An existing attempt row never exempts associated captures from reconstruction. Judge the union of ledger, attempts, records and captures. A present but truncated stream can remain uncertain; file existence does not prove completeness. Match raw hashes against recorded **original** channel hashes, not sanitized bytes. Require established process-tree termination before cleanup or final capture commitment. Capture mtime is not an established delivery timestamp. Apply S4’s recovery quarantine. **Evidence:** F1 to F9 provide no additional recovery proof.

3. **S3: ACCEPT WITH CHANGES.** Also reject malformed inventory rows, duplicate feature names, invalid state values and unsupported required flags. Inspect exit status and structured errors; authentication failure remains independently sticky and prevents propagation. The scorer validates the inventory against the frozen effective configuration. **Evidence:** F2 and F3 establish reported switch availability; F4 correctly excludes `features list` as startup-inventory evidence.

4. **S4: ACCEPT WITH CHANGES.** Preserve both original and sanitized hashes per channel and record disclosures as security events. On recovery, require credential fingerprints establishing coverage of the sanitation secret set. If prepared opaque secrets cannot be recovered with established coverage, quarantine raw files inside the credential boundary and stop promotion. Generic patterns cannot close that gap. **Evidence:** None of F1 to F9 establishes recovery redaction coverage.

5. **S5: ACCEPT WITH CHANGES.** Derive the manifest from the actual launcher, interpreter, target and payload resolution chain, not adjacent filenames alone. Verify argv, environment and discovery configuration too. Prevent substitution between verification and execution through a protected immutable installation or equivalent platform enforcement. Uninspectable required components block dispatch. **Evidence:** F9 identifies strings, not the complete executable dependency chain.

6. **S6: ACCEPT WITH CHANGES.** Use immutable experiment and run UUIDs plus a ledger-allocated `attempt_uid`; keep logical batch keys separate. A path hash can repeat after directory reuse and truncation introduces collisions. After complete staging, commit **one durable group reservation containing all members**, under the experiment lock, before any spawn. Separate nominal and reserve limits; identical ledger events are idempotent, conflicting or torn records fail closed. Proven unlaunched reservations retain their debit and have zero model usage. Replacement activation must preserve all historical failures and evidence; `void` does not itself authorize terminal-batch repetition. Missing predecessor evidence withholds claims. **Evidence:** No new fact changes these requirements.

7. **S7: ACCEPT WITH CHANGES.** Extend reconstruction to authentication, terminal outcome, all claim-bearing usage fields, full launch environment and payload identity, predecessor evidence, and channel provenance. Reconstruct warm C adoption and answer eligibility from the permitted cold C history, including the required effects of later quarantine. A mismatch with stored artifacts withholds dependent claims. **Evidence:** F8 offers a possible additional evidence channel but does not replace capture-derived reconstruction.

8. **S8: ACCEPT WITH CHANGES.** Recovery time may supply an **upper endpoint bound only**, when ordering and clock integrity are established. It must not become an exact close time or be called universally conservative. Recover a defensible duration interval or mark timing incomplete. Require `upper(C) <= 0.9 * lower(A)` and, where applicable, `lower(A) / upper(C) >= 1.6`. Record clock and invocation identities, include durable delivery, and merge overlapping windows according to the frozen scope. **Evidence:** F1 to F9 do not establish timing bounds.

9. **S9: ACCEPT WITH CHANGES.** I accept dropping `--ephemeral` under P3 below. F7 does not prove that only one file or one behavior changes. Establish the complete persisted-state lifecycle, account-field mapping, bucket identity and quota freshness semantics. An event timestamp alone neither proves a fresh server observation nor coverage of completed calls. Do not assume a response-generated reading occurs after local attempt completion. Reject booleans, nonfinite numbers, unexplained future timestamps and malformed latest relevant readings. **Evidence:** F7 and F8 partly address usable quota observation; they identify a candidate source, not a certified one.

10. **S10: ACCEPT WITH CHANGES.** Set the transport registry to empty under P1. Keep separate transport and startup-notice registries. F6 supplies the complete P4 message, but the complete outer event fixture and identifier syntax remain missing. Keep `code_mode_host` disabled; delete the proposed omitted-disable alternative. Authentication and execution findings remain independently sticky. **Evidence:** F6 closes the message-text gap only; F9 supplies no complete event fixture.

11. **S11: ACCEPT WITH CHANGES.** Add the discovery switch, but do not equate accepted configuration with effective exclusion. A rollout’s `response_item` inventory is insufficient without proof that it exhaustively represents the effective model request, including assembled base instructions and injected context. Require an exact signed manifest with canonical paths, hashes, types, origins and permitted roles; reject symlinks, junction escapes and unapproved instruction files. Apply P5 below. **Evidence:** F3 to F5 and F8 partly address instruction exclusion. They do not establish it.

12. **S12: ACCEPT WITH CHANGES.** Validate exact signed ruling bytes and matching predicates, not merely the presence of signature strings. Require the focused readiness checklist, including approved evidence annexes. Freeze may precede execution-only telemetry certification, but cannot precede required deterministic manifests or source-semantics evidence. A probe that first reveals an unknown inventory cannot authorize that inventory during the same frozen run. Stop, approve the annex and refreeze before dependent execution, retaining all prior debits. **Evidence:** F4 changes the inventory-producing command; it does not waive prefreeze approval.

13. **S13: ACCEPT WITH CHANGES.** Also classify missing or inconsistent lifecycle evidence explicitly. Preserve independently invalid counters as invalid, observed counters as diagnostics, and delivered terminal output as nonrepeatable. Multiple turns cannot yield certified last-turn-only usage. **Evidence:** No new fact alters this requirement.

14. **S14: ACCEPT WITH CHANGES.** Remove the categorical statement that correctness and makespan are unaffected. Unknown usage alone need not invalidate them, but execution uncertainty and missing timing evidence can. The retry-input/zero-output view must be labeled **hypothetical substitution, not an established bound**, and cannot support any passing gate or headline. Identical stdin does not establish identical total model input. **Evidence:** F8 may permit accounting recovery in particular cases; it does not establish unknown costs.

## Rulings

### P1: ACCEPT WITH CHANGES

> P1. For the frozen codex-cli 0.160.0 route, `SIGNED_TRANSPORT_NOTICES = []`. Neither `Reconnecting... ` nor `Falling back from WebSockets to HTTPS transport.` receives a transport exception through prefix matching or structural constraints alone.
>
> A nonempty registry requires a prospective ruling approved by both signatories, containing complete event fixtures, complete outer and item schemas, and fully anchored message grammars with explicitly bounded variable fields. Authentication failures, execution evidence and unresolved execution uncertainty retain their existing dispositions.
>
> Signed: Astra A

### P2: ACCEPT WITH CHANGES

> P2. Unknown usage remains incomplete. An authorized infrastructure reserve may complete correctness observations, but its usage neither replaces nor bounds missing usage from another attempt. Each attempt retains its own allowance and accounting disposition.
>
> Dependent token comparisons remain inconclusive until missing usage is independently established under the frozen accounting predicates. Hypothetical substitutions may appear only as explicitly labeled sensitivity calculations, never as established bounds or support for a passing gate or headline.
>
> Unknown usage alone does not determine correctness or timing validity; their separate evidence requirements still apply. Possible launch without sufficient complete capture evidence to resolve execution is uncertain under A4.3 and enters experiment-wide leakage. Proven absence of launch is distinct and has zero model usage. Complete recovered evidence is judged normally.
>
> Signed: Astra A

### P3: ACCEPT WITH CHANGES

> P3. Codex worker calls may omit `--ephemeral` on the frozen route solely with a certified per-attempt persistence and harvesting lifecycle. Each worker home starts clean, serves one attempt, and is not reused with persisted state. Rollouts remain within the restricted credential-bearing runtime boundary. Required sanitized evidence and authentication reconciliation must be preserved before cleanup, which requires established process-tree termination.
>
> Before every synchronized Codex dispatch group, including telemetry, require an authoritative observation attributable to the baseline account and applicable primary quota bucket. A frozen source manifest approved by both signatories must establish account-field mapping, bucket identity, observation timestamp semantics, freshness behavior and causal coverage of all previously completed replication groups. A timestamped cached value does not establish coverage. The observation from one concurrent worker does not automatically cover its siblings.
>
> Harvest the latest relevant quota observation from each available worker rollout before cleanup. Select the latest applicable event before validating it; do not bypass a malformed latest event using an older valid reading. Reject missing evidence, booleans, nonnumeric or nonfinite percentages, values outside `[0,100]`, unexplained future timestamps, account or bucket mismatches, and stale or unestablished coverage. Usage of at least 80 percent prevents dispatch. File modification times are never freshness evidence.
>
> Same-account owner observations qualify only under the same source and coverage requirements. No model call may be added, repeated or relabeled solely to obtain quota evidence. Incidental observations from independently authorized substantive calls retain their actual A4.13 category. No stale-reading or estimated-headroom exception is authorized.
>
> Dropping `--ephemeral` is permitted by this ruling; launch remains blocked until the persistence lifecycle and observation source are certified. F7 and F8 alone do not certify them.
>
> Signed: Astra A

### P4: ACCEPT WITH CHANGES

> P4. Keep `code_mode_host` disabled. The sole candidate startup-notice message is exactly:
>
> ``Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.``
>
> Recognition additionally requires an `item.completed` event matching a complete outer-schema fixture approved by both signatories, with an error item containing exactly `id`, `type` and `message`, and an identifier matching the approved identifier syntax. F6 completes the message text, not the event annex. Until the fixture and identifier syntax are approved, this notice exception remains inactive.
>
> Additional fields, appended text and message variants do not qualify. Authentication failures, accompanying tool activity and unresolved execution evidence retain their dispositions.
>
> Signed: Astra A

### P5: ACCEPT WITH CHANGES

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

## Evidence status

- **Authentication source attribution: partly.** F1, F2 and F9 support configuration availability. Eight worker-path checks and the empty-home 401 probe remain necessary but insufficient. Close with binary-and-payload-bound implementation analysis or a complete credential-access trace demonstrating that the actual authenticated execution route uses only the prepared file credentials, including the account-indexed credential-store counterexample.

- **Instruction exclusion: partly.** F3 establishes reported switch availability; F4 identifies an unsuitable inventory command; F5 identifies candidate files; F8 identifies candidate context records. Close with the exact signed startup manifest and evidence establishing discovery behavior, base-instruction assembly, and completeness of the effective-request inventory.

- **Complete notice fixtures: partly.** F6 completes P4’s message. Close P4 with the archived full event, exact outer schema, identifier syntax and both approvals. P1’s empty registry needs no transport annex. Any later transport exception requires complete fixtures and anchored grammars; F9’s strings do not suffice.

- **Usable quota observation source: partly.** F7 and F8 establish a plausible persistence-based route. Close with pinned evidence for account and bucket association, server-observation versus cached-event semantics, concurrent-group coverage, initial pretelemetry availability, and safe harvesting. A qualifying source must actually be available at each gate; protocol approval does not manufacture one.

## A4 changes

**none.** These texts settle pending ruling slots. P3 supersedes my earlier prospective “Retain `--ephemeral`” ruling. It does not relax authentication, instruction exclusion, accounting, allocation or leakage requirements.

## Freeze acceptance

A code lens pass limited to S2, S6 and S9 is insufficient. I require focused verification against the complete closure checklist, without another full council round:

- Exact countersigned P1 to P5 texts, matching configuration, and approved required annexes.
- Authentication attribution and lineage, instruction exclusion, executable binding, quota semantics, redaction recovery, timing bounds and independent scoring.
- Atomic reservations, immutable identities, process-safe recovery, predecessor evidence and terminal-batch preservation.
- Unchanged acceptance tests, all six round 2 red-team reproductions, the additional regressions, and a fake replacement-and-recovery exercise, with actual results recorded.

Freeze readiness and live telemetry certification remain separate gates. Missing evidence preserves the relevant stop. No live evaluation is accepted on the strength of this proposal alone.