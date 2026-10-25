# Ruling P3: quota observation source

Slot P3 of config.REQUIRED_RULINGS (bench/ozmap_rep/rulings.py). Source: council-build-deadlock-r2-joint.md (sha256 fae12460cd9e64fe76716ad7b612f1f2e51663a4258eccda31ebfbca9b5c4324), lines 205 to 217, copied byte for byte below.

Status: signed by Astra A as prospective protocol text (joint decision, section 3). Opus B confirmation by diff is pending, and this file is not bound in config.SIGNED_RULINGS. A binding needs this file countersigned (the line naming Opus B as signer) and its new sha256 recorded in the slot.

## Ruling text (verbatim)

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

## Open point for Opus B (verbatim, lines 307 to 321; not part of the signed text)

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

## Annexes

| kind | path | sha256 |
|---|---|---|
| quota_source_manifest | docs/design/ozmap-replication-2026-10-24/rulings/P3-quota-source-manifest.json | cadd1c8682e5133dbc5d36abc3dd9705f3d488b9f2465c18ae733d06bfa9e26a |

## Open before binding

The coverage predicate (D5) is not signed. The annex records it as implemented and marks causal coverage not established. It also records a gate gap: quota.coverage_gate accepts an owner reading that carries no account hash, which the manifest treats as not attributable.

## Countersignature

Opus B: pending (confirmation by diff of the ruling text above).

## Astra sign-off

Not signed. Astra A raised BLOCKER P3 on 2026-10-25 (rulings/signoff-astra.md): quota.coverage_gate accepts a reading without an account hash. Closing needs the gate to require both hashes and a regression test.
