# Opus B sign-off of rulings P1 to P5 and D1 (2026-10-25)

Signer: Opus B, a fresh Opus workflow subagent (claude-opus-5-5), id opusb-20261025T020225Z. Ledger row role
opus-b-signoff-rulings (Opus 40 of 70). No model or Codex call was made. The sealed ASTs and the ops content were not
read. Nothing was committed.

Result: P1, P2 and P4 signed. P3, P5 and D1 not signed, with blockers OB-P3, OB-P5 and OB-D1 under A4.14.2.

## Method

Diff. Each ruling file's quoted block was compared as bytes with the cited line ranges of
council-build-deadlock-r2-joint.md (sha256 fae12460cd9e64fe76716ad7b612f1f2e51663a4258eccda31ebfbca9b5c4324, unchanged
since fc60457). Every range was found verbatim with blank lines on both sides: P1 187 to 193 and 278 to 289, P2 195 to
203, P3 205 to 217 and 307 to 321, P4 219 to 229, P5 231 to 243, 266 to 276 and 291 to 305, D1 251 to 264. Every line
of the joint section 3 texts also occurs in council-build-deadlock-r2-astra-critique.md, as the joint file claims.

Tests. The full `python -m pytest bench/ozmap_rep` suite passes at HEAD d0d84d9: 605 passed. The acceptance tree
differs from 1aad1f8 only by the A4.14.4 replacement of
`test_cli_cell_is_resumable_and_never_repeats_a_completed_call`, which build-notes.md lists. Reproductions with tmp
dirs and monkeypatched config, no CLI: scratchpad files opusb_repro.py and opusb_d1.py in
C:\Users\can02\AppData\Local\Temp\claude\C--Users-can02-Projects-akor\4bd0413f-bf62-4dbc-94ba-cf58fbdc1707\scratchpad.

Concurrency note. Astra's sign-off (rulings/signoff-astra.md) landed in the same files while this review ran. Astra
signed P1, P2, P4, P5 and D1 and blocked P3. The Opus B lines are appended after Astra's.

## P1 transport notices: signed

The text matches. config.SIGNED_TRANSPORT_NOTICES is `()`, and on the archived no auth stream every `Reconnecting...`
event is uncertain. Ruling on D3: the strict empty registry stands. If reconnects are frequent, the cost is a stopped or
invalid cell that is flagged as such. A4.14.1 already fails closed on that, so it is a CHANGE.

## P2 unknown usage: signed

The text matches and the ruling has no annex.

## P3 quota observation: not signed (OB-P3)

The text matches and I accept it. I do not sign because the bound annex records causal coverage as `not_established`.
Also, a P3 binding with both signatures makes rulings.ruling_problems return no P3 problem, since no code reads the
annex status. quota.coverage_gate then admits readings that the P3 text and the annex tell it to reject. With
`account_sha256` set to the baseline hash and no prior attempts (the telemetry group), the gate returned ok at 10% in
every one of these cases (opusb_repro.py, P3_coverage_gate):

| case | P3 or annex rule broken | gate |
|---|---|---|
| owner rollout without creator_account_id | "a reading without an account hash is not attributable" | ok |
| limit_id `codex_other_bucket` | bucket identity limit_id codex, "bucket mismatches" rejected | ok |
| primary.window_minutes 300 | bucket identity window_minutes 10080 | ok |
| reading event without timestamp | "Reject missing evidence" and timestamp semantics | ok |
| reading three days old | "stale or unestablished coverage", freshness behavior | ok |
| harvested worker reading without account hash | account attribution | ok (12%) |

The code paths are quota.py lines 199 and 214 (account checked only when both hashes are present). read_file never
reads limit_id or window_minutes. An owner timestamp of None is appended to `readings`. The first group has no
freshness bound at all. The worst case is dispatch past the owner's 80% stop on a reading from another bucket, another
account or an old session, which harms the owner's account. Fix: require both hashes and equality. Reject limit_id
other than `codex` and window_minutes other than 10080. Reject a missing timestamp. Add the freshness rule to the
manifest, signed with D5, and enforce it. Add a regression test for each row. Make rulings.annex_problems refuse a P3
annex whose `freshness_and_causal_coverage.status` is not `established`.

D5 (Opus B position, not a signature): a reading from inside an attempt does not causally cover that attempt's last
request. The driver's per attempt predicate is acceptable only if the manifest states the lag as a known residual and
both signatories accept it. No estimated headroom is allowed. Until then, P3 stays blocked.

## P4 CLI notice annex: signed

The text matches. Checks of the annex against its claims:

1. P4-cli-notice-annex.json hashes to 70b8b55a and equals the shape of rulings.cli_notice_config().
2. The fixture line equals line 2 of evidence/P4-exec-noauth.out (line sha256 18b6a7a9). That file equals the
   scratchpad cliprobe stream byte for byte.
3. A recount of the 37 surveyed streams gives 180 item events. All have outer keys exactly {item, type}, all ids are
   item_<n>, and the Code Mode notice occurs once.
4. With the annex configured, events.signed_cli_notice accepts the fixture. It rejects appended text, a prefix, an
   extra outer key, an extra item key, `item_01`, `msg_0`, an integer id and a trailing newline in the id.
5. The frozen prefix list codex_cli_adapter.KNOWN_NOTICES does not match the Code Mode text, so the notice is inactive
   until config is set.

Opus B approves outer event keys `["item", "type"]` and identifier syntax `item_(?:0|[1-9][0-9]*)` under re.fullmatch,
the same scope as Astra's P4 note. If the frozen argv emits another schema, the notice is uncertain, which fails
closed. That is a CHANGE.

## P5 startup manifest and effective context: not signed (OB-P5)

The text matches and I accept it. Startup manifest check: its 49 `skills/.system` entries match, path and sha256, the
files in scratchpad rep/cliprobe/home, with no extra file. As the manifest itself says (D4), that home predates the
final argv.

Blocker. The bound effective_context_evidence annex has verdict `not_established` and finding P5-E1: the pinned
binary's default assembly lists 45 owner skills from `~/.agents/skills` even though CODEX_HOME, HOME and USERPROFILE
point at the worker home. A P5 binding with both signatures passes rulings.ruling_problems with no P5 problem
(opusb_repro.py, binding_with_not_established_annexes), and rulings.configuration_problems only checks that the
manifest exists. isolation.telemetry_certificate inspects only CODEX_HOME runtime files (the 49 manifest files pass
unflagged) and working directory instruction sources. Nothing reads the annex verdict or the owner profile skill root.
So once Opus B signs, the freeze and the telemetry certificate can pass while owner skills and system skills are in the
model context. That is unflagged leakage into every Codex result. Astra's P5 signature relies on "dependent evaluation
must stay closed", which no code enforces. Fix: make rulings.annex_problems refuse an effective_context_evidence annex
whose verdict is not `established`. Close P5-E1 to E3 with request boundary evidence for the final argv. One cheap
route: the no auth exec probe with only a localhost provider base URL, capturing the full request body with no
external request, plus implementation analysis that the provider block does not change instruction assembly. Then
regenerate the startup manifest from that probe.

D4 ruling: route (a). A pre freeze no auth exec probe with the final argv makes no accepted model request and consumes
no quota. It is a preparation probe logged in the call ledger and does not count against the telemetry allowance of 4.
D2: Astra's position holds, so a rollout inventory alone does not qualify.

## D1 authentication source attribution: not signed (OB-D1)

The text matches. Annex claims reproduce: codex.exe sha256 fdda5fa3, all seven static string counts, and one Codex
credential target `secrets|0218800dc2c5837c.codex`. 0218800dc2c5837c is the first 16 hex of sha256 over the extended
path of the owner `~\.codex`. The baseline path gives 841add2be2e6febe, which has no entry.

Opus B position: the differential on the exec route attributes the credential to the prepared auth.json without a
Process Monitor trace. The three cases are an empty home (401, missing bearer), a scrambled token auth.json with the
baseline account metadata (required auth_failure), and a valid file (success). Astra signed D1 on the unchanged strict
requirement and states that the probe does not substitute. The signatories disagree.

Blocker. With both signature lines, rulings.ruling_problems returns no D1 problem (opusb_d1.py), and
isolation.telemetry_certificate never reads the attribution annex. Binding D1 would therefore apply Opus B's reading
while the signed text says the certificate stays false without a trace. A run would be reported as certified against
its own ruling. I removed the Opus B signature line from D1-auth-attribution.md. Fix: the owner decides D1 under
A4.14.3, or one signatory adopts the other's text. Under the strict text, rulings.annex_problems must also refuse a D1
annex whose status is not complete.

## Changes (not blockers)

1. run.py TelemetryRun.arm hardcodes `account_metadata_kept: True`. Derive it from the prepared probe auth document.
2. After telemetry, record `cmdkey /list` target names (no secrets) to show that no credential target appeared for the
   baseline or worker paths.
3. The P4 annex survey counts command_execution 2 across started and completed events, while the outer key count is per
   event. Label the basis.
