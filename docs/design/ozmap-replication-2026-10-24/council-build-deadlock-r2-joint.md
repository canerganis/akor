# Deadlock round 2: joint decision of Fable and Astra (2026-10-24)

Driver: a fresh Opus workflow subagent (ledger role council-build-deadlock-joint-driver-r2). Inputs:
council-build-deadlock-r2-fable.md (Fable co-solver proposal), council-build-deadlock-r2-astra.md (Astra co-solver
proposal) and council-build-deadlock-r2-astra-critique.md (Astra's critique of Fable's proposal, one Astra call,
gpt-6-astra, effort high; the prompt carried Fable's file verbatim and Astra's own earlier file; ops content and sealed
ASTs excluded, the ops described only as four independent tensile-test ops). No agent was spawned. Fable was not called
again: Fable's critique of Astra is given below only as quotations from Fable's file. Ledger after this step: Astra 11
of 20, Opus 21 of 40, Fable 2 of 4, Sonnet 1 of 40.

Status of the rulings. Astra A signed the texts in section 3 as prospective protocol text only. Fable is a co-solver,
not a signatory. Every ruling text below needs Opus B confirmation by diff in the next council round before it binds,
and none of them certifies the implementation or the evidence annexes.

## 1. Summary

Agreed on the mechanism of every blocker. Both co-solvers fail closed wherever evidence is missing, so where they
differ the stricter text is the operative one until Opus B rules; Fable's file anticipates this ("If Astra does not sign
that, the fallback in S9 applies and the live path stalls on owner readings, which is the correct fail closed
behaviour").

Agreed changes of position:

1. `--ephemeral` is dropped for worker calls (Fable S9). Astra withdraws her earlier "Retain `--ephemeral`" and signs a
   new P3 with a certified persistence and harvest lifecycle.
2. The bounded retry cost gate is withdrawn (Fable S14: "I withdraw the bounded gate"). Astra's strict P2 holds; the
   retry substitution is shown only as a labeled hypothetical.
3. `code_mode_host` stays disabled; the `SIGNED_OMITTED_DISABLES` alternative is dropped (Fable: "I prefer (3)").
4. Complete group preparation before any ledger reservation (both chose it).
5. Immutable UUIDs replace the path hash run id (section 4, item 2).
6. Fable's headroom fallback for quota is rejected by both (Fable: "`delta` would be a guess, and the gate would
   stall"; Astra P3: "No stale-reading or estimated-headroom exception is authorized").

Still disputed (section 4): authentication source attribution (S1), sufficiency of the rollout input inventory for
instruction exclusion (S11, P5), prefix matching for transport notices (P1), pre freeze versus telemetry probe origin
of the startup manifest (S12), the quota coverage predicate (S9), and the review required before freeze.

No change to the text of Amendment 4 is agreed. Both co-solvers place everything in the pending ruling slots P1 to P5
(Fable S1: "No ruling needed"; Astra: "A4 changes: none").

## 2. Per blocker: agreed solution

Each entry names the Fable section, the matching Astra solution and the joint solution, which is Fable's mechanism with
Astra's required changes unless stated otherwise.

### Items 3, B3, RT2.1: recovery and capture completeness (Fable S2, Astra 1)

Agreed. Raw stdout and stderr go to files under `D/homes/raw-<slot>/` inside the credential boundary (Fable S2.1).
After `Popen` the durable attempt state machine of Astra 1 governs (prepared, reserved, launch_intent, running,
process_terminated, captures_committed, verdict_committed, settled), with process identity of pid plus creation time
plus supervisor or job identity, and a suspended launch on Windows where available. Fable's write order in
`after_group` (call record, captures, attempt row, marker `recorded`) is the order of those states. Recovery inspects
committed captures, parsed records, raw files and process state in that order (Fable S2.3 (a) to (d)), with Astra's
changes:

1. An existing attempt row never exempts its captures from reconstruction; the scorer judges the union of ledger rows,
   attempts, call records and captures (Fable S2.5 and Astra 1 agree).
2. Raw files are matched against the recorded original channel hashes, not sanitized bytes.
3. A present but truncated stream can stay uncertain; file existence does not prove completeness.
4. Cleanup and final capture commitment require established process tree termination.
5. Capture mtime is not a delivery timestamp; a recovered row records `ended_at` as unknown or as a bound (see S8).
6. Redaction recovery quarantine of S4 applies.

Fable's process identity rules (S2.4: `spawning` before `Popen`, kill and wait on journal failure, `spawning` without a
pid is ambiguous and stops Codex) are kept. Tests: the union of both lists, including PID reuse and a partially
written stream from Astra 1.

### Items 9, RT2.2: experiment identity and cumulative accounting (Fable S6.1 to S6.3 and S6.5, Astra 2)

Agreed, with Astra's identity scheme. `experiment_id` and `run_id` are immutable UUIDs written at first dispatch;
every reservation gets a ledger allocated `attempt_uid`; the logical batch key stays separate. Fable's live budget from
the ledger alone, the experiment lock beside the ledger, and the disposition file hashed into `freeze.json` stay.
Astra's changes: torn or malformed ledger lines fail parsing, identical events are idempotent and conflicting ones are
an accounting failure, nominal and reserve consumption are reported separately, `void` does not by itself authorize
repeating a terminal batch, and missing predecessor evidence withholds claims.

### B2, RT2.3: group preparation and abandonment (Fable S6.4, Astra 3)

Agreed. All members are staged without a ledger charge; then, under the experiment lock, shared prerequisites are
revalidated and one durable group reservation with every member identity is committed before any spawn.
`IsolationError` is caught alongside `Stop`. A member that fails its final per child verification after reservation
gets a terminal `not_launched` row with evidence that execution never began; it keeps its allocation debit and has zero
model usage (Fable's "keeps it out of usage" and Astra's "retain the conservative allocation debit" are the same
rule). `not_launched` is used only where absence of execution is established; otherwise the ambiguous launch path of
item 3 applies.

### Items 1, B4, RT2.6: authentication source and owner token separation (Fable S1, Astra 4 and 6)

Agreed parts: `-c cli_auth_credentials_store="file"` on the frozen argv and enforced by `argv_check` and
`verify_launch`; `secret_auth_storage` added to `DISABLE_FEATURES`; eight `login status` checks at the actual worker
paths, emptied, before the exec probe and after the plain call, run only after no child uses the directory; token hash
comparison of the baseline with the owner home and the runner's `CODEX_HOME` before telemetry, at every wave gate and
under the authentication lock immediately before worker reconstruction; equal access or refresh hash refuses with exit
11 and `CODEX_HOME=~/.ozmap_rep/baseline codex login`; lineage rows in `evidence/auth-lineage.jsonl`. Astra's additions
are agreed: canonical path resolution and alias rejection, an unreadable existing source or unexplained credential
representation is never treated as different, and the 48 hour expiry gate and owner login provenance are preserved.
Whether this set is sufficient attribution is disputed (section 4, D1).

### Item 5: probe authentication and features inventory (Fable S3, Astra 7)

Agreed. Fable S3 plus Astra's additions: reject malformed rows, duplicate feature names, invalid state values and
unsupported required flags; authentication failure is sticky and prevents propagation; the scorer validates the record
against the frozen expectation. `features list` is not a startup inventory source (F4, accepted by Astra).

### Item 6: credential redaction (Fable S4, Astra 8)

Agreed. Fable S4 plus Astra's per channel record (`attempt_uid`, channel, `original_sha256`, `sanitized_sha256`,
redaction count, categories) and the missing secret policy: if the prepared secret set is lost in recovery and coverage
cannot be established from recorded fingerprints, the raw files stay quarantined inside the credential boundary and
promotion stops. A detected disclosure stays a recorded security event.

### Item 7: executable identity (Fable S5, Astra 9)

Agreed. Fable's explicit companion manifest for `codex.exe` (code mode host, command runner, every adjacent `.dll`)
and verification in `prepare_call` and immediately before `Popen`, with Astra's changes: the manifest follows the
actual launcher, interpreter, target and payload resolution chain; argv, environment and discovery configuration are
verified too; substitution between verification and execution is closed by a protected immutable installation or
equivalent platform enforcement; an uninspectable component blocks dispatch.

### Item 10: scorer reconstruction (Fable S7, Astra 10)

Agreed. Fable S7 plus Astra's extensions: reconstruction also covers authentication verdicts, terminal outcome, the
full launch environment and payload identity, predecessor evidence and channel provenance, and warm C eligibility from
the permitted cold C history including later quarantine effects. A mismatch withholds dependent claims; the report is
never silently corrected.

### Item 14: timing windows (Fable S8, Astra 12)

Agreed on Astra's semantics. Fable's `open` and `close` rows in `windows.jsonl` are kept. A window closed by recovery
does not get an exact `ended_at`: the recovery time is an upper endpoint bound, used only when ordering and clock
integrity are established, and the last durable work timestamp of that invocation is the lower endpoint bound. Gates
apply the bounds against the claim: warm makespan passes only if `upper(C) <= 0.9 * lower(A)`, and the magnitude timing
gate only if `lower(A) / upper(C) >= 1.6`. Overlapping windows merge under the frozen scope; they are never summed as
sequential. Fable's file called the recovery time conservative because "it can only lengthen the window"; Astra
showed that lengthening a reference A window improves C's comparison, and Fable's file gives no counter argument, so
the point is closed.

### Items 31, B8, RT2.5: quota observation (Fable S9, Astra 13, ruling P3)

Agreed: worker calls drop `--ephemeral`; each worker home starts clean, serves one attempt and is emptied after harvest;
the rollout stays inside the credential boundary; only metadata is harvested; observations use event timestamps, never
mtimes; the latest relevant reading is validated before use and a malformed latest reading blocks without fallback;
values must be finite numbers in [0, 100], booleans rejected; the gate runs before every synchronized dispatch group
including telemetry; at least 80 stops. Signed text: P3 in section 3. The coverage predicate is open (D5).

### Items 32, B5: CLI notices and transport events (Fable S10, Astra 14, rulings P1 and P4)

Agreed for P4: `code_mode_host` stays disabled, the complete message text of F6 is the sole candidate, exact match.
The P4 annex still needs the archived complete outer event fixture and the identifier syntax, approved by both
signatories; until then the notice exception is inactive and the notice makes a stream uncertain. P1 is disputed
(D3); the operative text is Astra's strict empty registry.

### Items 33, B6: startup files and instruction context (Fable S11, Astra 5, ruling P5)

Agreed parts: `--enable skip_host_skill_discovery` on the frozen argv; `SIGNED_STARTUP_FILES` replaced by an exact
manifest (canonical relative path, sha256, file type, origin, permitted role) frozen by hash; symlinks, junction
escapes, extra and changed files rejected; file creation never authorizes loading; an additional input item fails
certification; filename patterns and token counts establish nothing. Sufficiency of the rollout inventory is disputed
(D2); the operative text is Astra's P5.

### B1: freeze refusal and telemetry preflight (Fable S12, Astra 16)

Agreed: `config.SIGNED_RULINGS` names ruling files, `freeze_command` refuses (exit 14) unless every ruling exists and
the configuration matches it, and the ruling files and hashes go into `freeze.json`. Astra's change is agreed: the
validator checks the exact signed ruling bytes (hash against the countersigned diff) and the matching predicates, not
the presence of `Signed:` lines. Freeze readiness and live telemetry certification are separate gates. The origin of
the startup manifest is disputed (D4).

### RT2.4: two turns in one stream (Fable S13, Astra 11)

Agreed. Fable S13 plus Astra's additions: missing or inconsistent lifecycle evidence is an explicit incomplete
disposition, independently invalid counters stay invalid, all observed counters are kept as diagnostics, and a
delivered terminal answer is never resent.

### B7: unknown usage (Fable S14, Astra 15, ruling P2)

Agreed on Astra's P2 (section 3). Fable's `unknown_usage_observation` block stays, labeled "hypothetical substitution,
not an established bound", never consulted by `gates.evaluate`. Fable's sentence "correctness and makespan comparisons
of that cell are unaffected" is removed: unknown usage alone does not invalidate them, but their own evidence
requirements still apply.

## 3. Ruling texts signed by Astra A (need Opus B confirmation by diff)

These supersede both co-solver drafts of P1 to P5, including Astra's earlier P3 "Retain `--ephemeral`". Copied verbatim
from council-build-deadlock-r2-astra-critique.md.

### P1 (A4.3)

> P1. For the frozen codex-cli 0.160.0 route, `SIGNED_TRANSPORT_NOTICES = []`. Neither `Reconnecting... ` nor `Falling back from WebSockets to HTTPS transport.` receives a transport exception through prefix matching or structural constraints alone.
>
> A nonempty registry requires a prospective ruling approved by both signatories, containing complete event fixtures, complete outer and item schemas, and fully anchored message grammars with explicitly bounded variable fields. Authentication failures, execution evidence and unresolved execution uncertainty retain their existing dispositions.
>
> Signed: Astra A

### P2 (A4.7, A4.11)

> P2. Unknown usage remains incomplete. An authorized infrastructure reserve may complete correctness observations, but its usage neither replaces nor bounds missing usage from another attempt. Each attempt retains its own allowance and accounting disposition.
>
> Dependent token comparisons remain inconclusive until missing usage is independently established under the frozen accounting predicates. Hypothetical substitutions may appear only as explicitly labeled sensitivity calculations, never as established bounds or support for a passing gate or headline.
>
> Unknown usage alone does not determine correctness or timing validity; their separate evidence requirements still apply. Possible launch without sufficient complete capture evidence to resolve execution is uncertain under A4.3 and enters experiment-wide leakage. Proven absence of launch is distinct and has zero model usage. Complete recovered evidence is judged normally.
>
> Signed: Astra A

### P3 (A4.12)

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

### P4 (A4.3, A4.2)

> P4. Keep `code_mode_host` disabled. The sole candidate startup-notice message is exactly:
>
> ``Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.``
>
> Recognition additionally requires an `item.completed` event matching a complete outer-schema fixture approved by both signatories, with an error item containing exactly `id`, `type` and `message`, and an identifier matching the approved identifier syntax. F6 completes the message text, not the event annex. Until the fixture and identifier syntax are approved, this notice exception remains inactive.
>
> Additional fields, appended text and message variants do not qualify. Authentication failures, accompanying tool activity and unresolved execution evidence retain their dispositions.
>
> Signed: Astra A

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

## 4. Points still disputed

Fable's positions are quotations from council-build-deadlock-r2-fable.md; Fable was not asked again. Astra's positions
are from council-build-deadlock-r2-astra-critique.md. In every case the operative text until Opus B rules is the
stricter one, so the launch stop holds either way.

### D1. Authentication source attribution (S1)

Fable: the file store argument, the eight worker path checks and the recorded `auth_source` "together with the empty
home 401 probe ... binds the certificate to the execution route's configured credential source, not to an inference
from two observations", and "No ruling needed".

Astra: "Recorded configuration is not observed source attribution." Required: "binary-and-payload-bound implementation
analysis or a complete credential-access trace demonstrating that the actual authenticated execution route uses only
the prepared file credentials, including the account-indexed credential-store counterexample."

Operative: Astra's requirement; `telemetry_certificate` stays false until that evidence exists. For Opus B: decide
whether a local credential access trace of the pinned `codex.exe` (for example a file and registry access monitor
during the empty home 401 probe and during telemetry, no extra model call) is acceptable evidence; it is the cheapest
item that would close D1.

### D2. Instruction exclusion evidence (S11, P5)

Fable: the telemetry rollout's model input inventory compared with the base instructions and the harness stdin; "Any
additional input item ... is a third source and fails certification, whatever the filenames in the home."

Astra: "A rollout's `response_item` inventory is insufficient without proof that it exhaustively represents the
effective model request, including assembled base instructions and injected context."

Operative: Astra's P5. Open evidence: proof that the 0.160.0 rollout records the complete effective request
(pinned implementation analysis or request boundary evidence). Both agree that without it the live path stays stopped
(Fable P5 draft: "If (b) cannot be produced, the live path stays stopped").

### D3. Transport notices (P1)

Fable: prefix match on `Reconnecting... ` and `Falling back from WebSockets to HTTPS transport.` with structural
constraints and the no tool item condition closes item 32.

Astra: `SIGNED_TRANSPORT_NOTICES = []`; a nonempty registry needs complete fixtures and fully anchored grammars.

Operative: Astra's P1 (strict). Cost to name for Opus B: with an empty registry every reconnect or fallback event makes
its call uncertain under A4.3, which enters experiment wide leakage. If such events are frequent on this route the
strict choice can void the experiment. The way out both texts allow is an archived fixture set from existing captures
with an anchored grammar (Fable's strings have no variable fields, so the grammar may be the exact full message),
approved by both signatories before freeze.

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

### D5. Quota coverage predicate (S9, P3)

Fable: "the newest qualifying observation must have a timestamp at or after the end of the last live Codex attempt of
the experiment (every completed group covered)", and "the telemetry call's own rollout is the covering observation".

Astra: coverage must be causal and established by the frozen source manifest; "Do not assume a response-generated
reading occurs after local attempt completion", and one concurrent worker's reading does not cover its siblings.

Driver note: Fable's predicate as written cannot be met by a reading harvested from inside a call, because that
reading is emitted before the call ends; the gate would refuse the first evaluation group. The source manifest under
P3 therefore has to define coverage per attempt, for example: for every attempt of every previously completed group,
the last `rate_limits` event of that attempt's own rollout, with established semantics that it reflects that
attempt's consumption, and the gate uses the maximum `used_percent` across those readings and any later owner
readings of the same account. Neither co-solver has signed such a predicate; it needs both signatories with the P3
annex.

### D6. Review before freeze

Fable: "a code lens pass over S2, S6 and S9 only ... S3, S4, S5, S7, S8, S10, S11, S13 and S14 are predicate changes
whose tests are the review."

Astra: "A code lens pass limited to S2, S6 and S9 is insufficient." Required: focused verification against the
complete closure checklist (countersigned rulings and annexes, authentication, instruction exclusion, executable
binding, quota semantics, redaction recovery, timing bounds, independent scoring, atomic reservations, identities,
recovery, predecessor evidence, the unchanged acceptance suite, all six round 2 red team reproductions, the new
regressions and a fake replacement and recovery exercise). Both agree that no further full council round is needed.

Operative: Astra's checklist, as one focused verification call.

## 5. Evidence still open before launch

| item | status | closes it |
|---|---|---|
| Authentication source attribution | partly (F1, F2, F9) | D1 evidence: pinned implementation analysis or a credential access trace, including the account indexed credential store counterexample |
| Instruction exclusion | partly (F3, F4, F5, F8) | exact startup manifest with the final argv (D4) and proof of rollout completeness or request boundary evidence (D2) |
| P4 notice annex | partly (F6 gives the message) | archived complete outer event fixture and identifier syntax, approved by both signatories |
| P1 transport annex | not needed under the strict registry | only if Opus B wants a nonempty registry (D3) |
| Quota observation source | partly (F7, F8) | P3 source manifest: account and bucket mapping, timestamp and freshness semantics, per attempt coverage predicate (D5), availability before telemetry, harvest lifecycle |

## 6. A4 changes

None agreed. All changes fill the pending ruling slots P1 to P5. Next council round: Opus B confirms or rejects the
section 3 texts by diff and rules on D1 to D6; the freeze validator then hashes the countersigned ruling files.

Driver for both co-solvers: Opus workflow subagent (not a signatory).
