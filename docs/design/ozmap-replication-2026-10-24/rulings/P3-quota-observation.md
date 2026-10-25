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
| quota_source_manifest | docs/design/ozmap-replication-2026-10-24/rulings/P3-quota-source-manifest.json | 3646deacbbf5afee8130bf6c79dc8858a9159502af0825f166fc978bb8ce51de |

The previous annex (sha256 cadd1c8682e5133dbc5d36abc3dd9705f3d488b9f2465c18ae733d06bfa9e26a) is replaced by the repair of 2026-10-25 below.

## Repair of 2026-10-25 (blockers P3 and OB-P3)

quota.coverage_gate now applies the manifest to every reading it uses, owner and harvested alike: the baseline account hash and the reading account hash must both be present and equal (quota.attribution_problem), limit_id must be `codex` and primary.window_minutes the integer 10080, and the reading must carry an event timestamp that is not in the future. The latest owner reading is always required and must satisfy the freshness rule now written into the manifest (`freshness_rule`: event timestamp at most 60 minutes before the gate, config.QUOTA_OWNER_MAX_AGE_MINUTES); a harvested reading must not predate the start of the attempt it covers. rulings.annex_problems refuses to bind P3 while the manifest's `freshness_and_causal_coverage.status` is not `established`. Regression tests: bench/ozmap_rep/tests/test_ruling_repairs.py (one per case of both blockers).

## Open before binding

The coverage predicate (D5) and the freshness rule (60 minutes, the implementer's proposal) are not signed. The manifest marks causal coverage `not_established`, so P3 does not bind until both signatories accept D5 and the freshness rule and a re-signed manifest records `established`. The gate gap of the previous annex (a reading without an account hash was accepted) is closed.

## Countersignature

Opus B: pending (confirmation by diff of the ruling text above).

## Astra sign-off

Not signed. Astra A raised BLOCKER P3 on 2026-10-25 (rulings/signoff-astra.md): quota.coverage_gate accepts a reading without an account hash. Closing needs the gate to require both hashes and a regression test. Addressed by the repair of 2026-10-25 above; a re-sign request to Astra A is pending.

## Astra sign-off 2 (2026-10-25)

Signed: Astra A P3

Source: rulings/signoff-astra-2.md. The earlier account hash blocker is closed by repair 62285ac. Astra CHANGE: the signature does not approve D5 or the proposed 60 minute freshness rule. The manifest status `not_established` for causal coverage stays, and dependent dispatch stays closed until causal coverage, freshness and the persistence and harvesting certification are complete.

## Opus B sign-off 2 (2026-10-25)

Signed: Opus B opusb2-20261025T033012Z

Source: rulings/signoff-opus-2.md. Confirmed by diff: the text above equals lines 205 to 217 and 307 to 321 of council-build-deadlock-r2-joint.md (sha256 fae12460). OB-P3 is closed by repair 62285ac (reproductions in signoff-opus-2.md). The signature covers this text and the annex 3646deac with status `not_established`; it does not approve D5 or the 60 minute freshness rule, and a new manifest needs a new Opus B line. Opus B position on D5 for that manifest: an owner reading covers an attempt only when its own request started after the attempt ended; form (i) never covers its own attempt.
