# Council round 3: Opus code correctness review of bench/ozmap_rep (2026-10-24)

Reviewer: fresh Opus workflow subagent (claude-opus-5-5, effort high, code correctness lens), logged in
call-ledger.jsonl as `council-build-code-reviewer-r3`. No model call and no Codex call was made. Every check used local
code, the harness' own fakes, archived captures, and metadata reads of the baseline and the owner's newest session
file (hashes, timestamps and percentages only; no token text was printed). The sealed reviewer ASTs were not read.
Reviewed at commit fc60457 against amendment-4.md, amendment-4-13-caps.md, owner-decisions.md, build-notes.md,
disputes.md, the round 2 reviews and the round 2 joint decision. I am not Opus B: the rulings section below is advice
to the signatories, not a signature.

Verdict: **do not freeze yet.** The round 2 fixes are sound and I found no regression in them; the freeze refusal
works and keeps the run from spending calls on a certain failure. Four blockers remain. B1 is the important one: as
the code stands (A4.2 `--ephemeral` kept, P3 coverage required), the live run needs 10 to 12 fresh owner quota readings
and cannot finish unattended inside the A4.13 caps. B2 and B3 are the open annexes and the missing effective context
check that guards against the pilot's own failure mode. B4 is a small P3 compliance fix.

## What I ran

| check | result |
|---|---|
| `python -m pytest bench/ozmap_rep -q` | 532 passed, 1 failed (266 s): the disputed red team test RT2.1, on its resend assertions only (D-R2-1) |
| RT2.1 with the assertions proposed in D-R2-1 (scratch copy, leakage assertion unchanged) | passed: resumed run exit 5, target `executed` with `recovered_from: capture`, no `r1.b03.t1` attempt, `SETTLED.json` written, target listed in leakage |
| `python -m bench.ozmap_rep.run dry --run-dir <scratchpad>/rep/r3review/dry/D` | exit 0 in 20 s: 16 of 16 cells complete, 52 fake calls, 0 external calls, no real CLI resolved, within every A4.4 bound (cold B 5 of 8, cold C 4 of 4, warm C 5 of 5); report: leakage 0, accounting 0, artifact problems 0, isolation passed, mode simulation, no claim permitted |
| `python -m pytest -q --continue-on-collection-errors --ignore=bench/ozmap_rep` (rest of the repository) | see the last line of this table |
| `git diff --stat 1aad1f8 HEAD -- bench/ozmap_rep/acceptance` and `git status` on it | empty: no acceptance file changed since 1aad1f8; no earlier round accepted a test change, so none was expected |
| frozen paths (`bench/ozmap/`, `bench/ozmap_rep/ops/`, `oz_*.py`, `examples/`) and `bench/ozmap_rep/redteam/` | unchanged since 1aad1f8 (red team: since 5fc191a) and clean in the working tree |
| `rulings.readiness_problems()` | 8 problems: P1, P2, P3, P4, P5, D1 unsettled, P4 predicate inactive, no startup manifest; `run freeze` refuses (exit 14) as intended |
| local probes | baseline wave gate ok (exp 2026-11-03T15:18:43Z, 233.9 h left), baseline inventory clean, token separation clean, baseline account hash equals the owner session `creator_account_id` hash, owner reading 41.0% at 2026-10-24T20:02:39Z (primary window 10080 min), pinned tokenizer available, classification valid (R = margin, temp_class, verdict), certificate authority clean |
| archived pilot streams (`bench/ozmap/runs`) | 35 files hold `turn.completed`; none holds `Reconnecting...`, `Falling back from WebSockets` or `Code Mode is unavailable` |

Full repository run (outside `bench/ozmap_rep`, 742 s): 1,261 passed, 50 failed, 1 skipped, 3 collection errors. These
are the same files and counts the build notes list (test_oz_flow 30, test_g3b 8, test_ozmap_close 4, test_oz_map 3,
test_ozmap_pilot 3, test_oz_do 1, test_host_classify 1; collection errors in test_codereview_pilot, test_pilot2,
test_pilot_k2). They come from the system interpreter not having tiktoken, and none of them imports the harness.

## Disputes

**D-R2-1 (RT2.1 resend assertions): accept the proposed test change.** The three assertions (`interrupted`, a resend
`r1.b03.t1` that ends `ok`, exit 0) describe the defect RT2.1 was written to expose, not required behavior: A4.3 ("No
selective rerun erases failure"), A4.5 (unused capacity cannot authorize repair), round 2 blocker 3 and the joint
decision ("never resent") all forbid resending a call whose capture shows execution. Replace them exactly as asked:
`outcomes[target] == 'executed'`, the target row has `recovered_from == 'capture'`, no attempt `r1.b03.t1`, the resumed
run returns `config.EXIT_INCOMPLETE`; keep the leakage assertion. I ran that version against fc60457 and it passes.
The change touches `redteam/` only, not `acceptance/`.

**D-R2-2 (`--ephemeral`): uphold the acceptance tests and A4.2 as written, for now.** A4.2 is normative and names
`--ephemeral` in the frozen argument list; a ruling slot cannot amend it, and the joint decision itself says "No change
to the text of Amendment 4 is agreed". Dropping the flag needs a prospective A4.2 revision signed by Astra A and Opus
B. I accept the change of the three acceptance assertions named in D-R2-2 (`test_a4_2_argv.py` FROZEN_HEAD and its
removal mutation, `test_cli_plan_and_cells.py` FROZEN_HEAD) on that condition only, in the same commit that signs the
revision and removes the flag from `config.FROZEN_ARGS`. B1 explains why I recommend the signatories make that revision.

## Blockers

**B1 BLOCKER (A4.2, A4.12, A4.13, P3: with `--ephemeral` the live run cannot finish unattended within the caps).**
`quota.coverage_gate` runs before every synchronized Codex group and requires every earlier live Codex attempt of the
experiment (except the scrambled probe) to be covered by its own rollout reading or by an owner reading with a later
event timestamp. With `--ephemeral` there is no worker rollout, so every group after the first needs a new owner
session event after the previous group ended. The plan has 10 Codex evaluation groups when every cell fits in four
calls (the dry run) and 12 when cold B and warm C need their fifth call for audits (two groups of at most four slots
each), and the first group must also cover the telemetry call: 10 to 12 readings. P3 forbids adding a call to obtain one, so each must come from an independently
authorized Astra call or from the owner's own Codex use. Astra has 9 of 20 left (ledger), and at least 3 are already
needed for the annex countersignatures, the freeze sign-off and the result review. Mechanically the code is safe (the
gate raises `Stop(EXIT_QUOTA)` in `reserve_group`, the group is abandoned before any charge, the cell resumes later),
but the run stalls after every group. Separately, without a rollout the harness has no source at all for the P5
effective context evidence (B3).
Fix: the signatories sign a narrow A4.2 revision: worker calls omit `--ephemeral` under the P3 lifecycle (each home
starts clean, serves one attempt, the rollout stays in `D/homes`, metadata is harvested, the home is emptied after
established termination). A4.2 already requires generated runtime files to be "inventoried ... then removed", which a
rollout is; only the literal argument changes. In the same commit: `config.FROZEN_ARGS` loses the flag, the acceptance
assertions change as accepted above, `cli-flags.json` is re-verified with the final argv, and the startup manifest is
taken with the final argv (B2). Coverage then comes from each attempt's own reading (`valid_own` in `coverage_gate`,
already implemented and tested). If the revision is not signed, the driver must record a reading plan (owner Codex use
between groups) and treat the run as attended; nothing in the code needs to change for that path.

**B2 BLOCKER (P1 to P5, D1: countersignatures and annexes before `run freeze`).** Verified: the freeze refuses with
eight readiness problems. Needed, in order: Opus B confirmation by diff of the P1 to P5 texts in
council-build-deadlock-r2-joint.md section 3; the P4 annex (complete outer event fixture of the Code Mode notice and
the identifier syntax); the P5 startup manifest and effective context evidence (B3); the P3 source manifest (B4); a D1
decision. Cheapest path, no model call: one pre freeze exec probe with the final argv, an empty CODEX_HOME and no
auth.json (as the implementer ran during the build; it ends in `401 Missing bearer`, so no model can serve it).
Archive its stream and home. It yields (a) the P4 fixture: in `tests/fixtures/exec-noauth2.out` error items already
have outer keys exactly `{type, item}`, item keys `{id, type, message}` and ids of the form `item_<n>`, and the probe
adds the Code Mode event itself; (b) the P5 startup inventory with sha256 per file; (c) without `--ephemeral`, the
rollout's `session_meta.base_instructions` and input items for B3. The ruling must state that this probe makes no
model request and consumes no model call allowance (A4.5: "Local CLI commands making no model request consume no model
call allowance"), and that it is logged in the ledger as a local probe. Build notes reading 3 charges the telemetry no
auth probe as telemetry; the ruling should say whether that reading stays for telemetry.

**B3 BLOCKER (A4.2, P5, D2: no code verifies the effective instruction context).** `telemetry_certificate` checks file
names and hashes in the worker home and the working directory. Whether bundled `skills/.system/*` or any other text
reaches the model is never checked; P5 requires "the complete effective instruction sources". This is the pilot's
failure mode: a skill file in reach led Codex to run a shell command, which invalidated the pilot. `unified_exec`
stays enabled and the read only sandbox still allows reads, so once a skill reaches the context a tool call, and with
it leakage, is likely.
Fix (with B1): in `Isolation.finish`, harvest from the worker rollout, as hashes only, `session_meta.base_instructions`
and every input `response_item` before the first model output (item type, role, sha256 of the content). Add an
approved context manifest (from the B2 probe): base instructions hash, the frozen serialization items (environment
context, permissions text) by hash, and the harness input as exactly the stdin hash. `telemetry_certificate` requires
an exact match for the telemetry call; I recommend the same check on every evaluation call, where a mismatch makes the
call `uncertain` (leakage). Completeness of the rollout against the real request is still the D2 question: settle it by
analysis of the open source codex-cli 0.160.0 rollout recorder (local reading, no model call; fetching the source needs
the owner's permission), or by the signatories accepting the rollout plus the token count cross check as stated
evidence. Tests: an extra developer item, a changed base instructions hash and a missing rollout each fail
certification.

**B4 BLOCKER (P3 as operative: missing evidence and bucket identity pass the quota gate).** In `quota.coverage_gate`,
an owner reading or a harvested reading without an account hash passes the account check
(`if account_sha256 and o.get('account_sha256') and ...`), and no reading is checked for bucket identity: nothing
reads `window_minutes` or `limit_id`. P3 says "Reject missing evidence ... account or bucket mismatches". Today both
sources carry `creator_account_id` (verified: equal to the baseline account hash), so this does not bite yet, but a CLI
or app update could drop the field silently.
Fix: require `account_sha256` present and equal to the baseline account hash for owner and harvested readings; record
`primary.window_minutes` (10080 now) and `limit_id` in `read_file` and `harvest_rollout` and require equality with
values frozen in the P3 source manifest. Tests: owner reading without account blocks; harvested reading with window
300 blocks.

## Changes

**C1 CHANGE (recovery skips reconciliation of real home probes).** In `recover_inflight`, `workers[slot]['probe']` is
`m.get('role') == 'probe'`, which is true both for the scrambled telemetry exec probe (marker `call`, role `probe`) and
for `worker_probe` markers (features and login status, marker `probe`), whose homes hold the real baseline auth.json.
After a crash during such a probe a rotated auth.json is never propagated, and the next `prepare` deletes it. Fix:
write `scrambled: true` into the marker of the scrambled probe and exclude only those from reconciliation; test with a
dead runner during `features` whose home auth.json changed.

**C2 CHANGE (D1 evidence: pin the differential probe to one path).** The scrambled probe and the telemetry call take
the first free slot each, which is usually but not necessarily the same. The differential argument (same path, same
account metadata, only token bytes differ, outcome flips from authentication failure to a reply) is the strongest D1
evidence available without a trace. Fix: `slots.acquire(only=0)` for both, record the slot in `exec_probe` and `call`,
require equality in `telemetry_certificate`.

**C3 CHANGE (Codex auto update can stall the run).** Live mode resolves `codex` through PATH
(`AppData/Local/Programs/OpenAI/Codex/bin/codex.EXE`, which resolves into
`~/.codex/packages/standalone/releases/0.160.0-x86_64-pc-windows-msvc`). The install auto updates
(`auto-update-version`, two releases kept). A re pointed junction between groups makes every later cell exit 14 and
forces a new freeze. Fix: in live mode take the executable from `freeze.json` (`codex.exe`, the release path) and
verify it there; operationally the owner pauses Codex app updates for the run.

**C4 CHANGE (tests touch the real experiment directory).** `~/.ozmap_rep/runs/experiment.lock` exists, created
2026-10-24 20:40Z during the round 2 fixes. Live mode tests that do not pass `live_ledger` (red team r1 line 249, the
acceptance CLI tests run with `mode='live'`) take that lock. The identity gate stops them before any ledger write, but
a suite run during the live run would make a live cell exit 16, or fail itself. Fix: pass a temporary `live_ledger` in
`redteam/` and `tests/`; operationally, never run the suite while a live cell runs (the acceptance tests stay frozen).

**C5 CHANGE (a ledger row can survive an abandoned group).** `reserve_group` writes markers, then one ledger row per
member. A `LockTimeout` (an `IsolationError`) on the second ledger append is caught in `run_batches`, `abandon` deletes
the markers and prompts, and the first row stays. `ledger_problems` then refuses every later live cell with exit 15 and
the scorer records an accounting failure. Fix: once any ledger row of the group is written, `abandon` turns the
group's markers into charged `not_launched` attempts instead of deleting them; test with a ledger lock held during
the second append.

**C6 CHANGE (round 2 C4 still open: correctness gates compare counts).** `boolq_gate` and the materials gates compare
correct counts; A4.10 says BoolQ C "must add no gold errors relative to A". Freeze one reading before `run freeze`
(per job added errors, or the count reading recorded as the frozen interpretation) and report per job added errors in
every gate either way.

**C7 CHANGE (P1 record).** The joint decision's driver note says the transport strings have no variable fields. The
archived fixture shows they do: `Reconnecting... 2/5 (unexpected status ..., cf-ray: ..., request id: ...)` and
`Falling back from WebSockets to HTTPS transport. unexpected status ...`. An exact match registry can never match
them; a nonempty registry would need the anchored grammar Astra's P1 asks for. Correct the note in the countersigned
record.

## Advice to Opus B on the pending rulings (not a signature)

1. P1: confirm the strict empty registry. In 35 archived pilot stream files no reconnect or fallback text appears, so
   its expected cost is low, and C7 shows exact matching could not help anyway.
2. P2: confirm. It is implemented as written (`interrupted` without a stream is uncertain leakage, proven not launched
   has zero usage, `unknown_usage_observation` is never read by the gates). Name the cost in the result report: any
   infrastructure retry in warm A or warm C makes that backend's warm token gate inconclusive.
3. P3: confirm together with the A4.2 revision of B1 and a source manifest: source is the last `token_count` event's
   `rate_limits.primary` in the attempt's own rollout; account is `session_meta.creator_account_id` hashed, required
   and equal to the baseline; bucket is `window_minutes` 10080 and the observed `limit_id`; coverage is per attempt by
   its own reading (D5 as the driver note proposes), with the maximum over all covering readings and the latest owner
   reading below 80.
4. P4: confirm, with the annex from the B2 probe (outer keys `{type, item}`, id `item_[0-9]+`, the complete F6 text).
5. P5: confirm, with the B2 manifest and the B3 context check as the verification procedure.
6. D1: the differential probe (C2) together with the file store argument, `secret_auth_storage` off and the eight
   empty path logins refutes the account indexed counterexample directly, since the probe keeps every account field
   and only the token bytes differ. I recommend accepting it as attribution evidence; a file and registry access trace
   remains a stronger option if Astra keeps her requirement.
7. D4: the pre freeze no auth probe of B2, with Astra's stop, approve and refreeze rule for any inventory the
   telemetry then shows outside the manifest.
8. D6: this review covers the code lens of Astra's checklist (rulings and annexes, authentication, executable binding,
   quota semantics, redaction recovery, timing bounds, independent scoring, atomic reservations, identities, recovery,
   predecessor evidence, the unchanged acceptance suite, the red team reproductions, the dry run). Instruction
   exclusion and quota semantics are not closed (B3, B4).

## OK

**O1 OK (round 2 fixes).** Raw streams to files in `D/homes/raw-<slot>`, the marker phases (`reserved`, `spawning`,
`spawned`, `recorded`), the write order in `after_group`, recovery from capture then raw stream with fingerprint
coverage and quarantine, never resending a terminal outcome, kill and wait on a pid journal failure, staged groups
reserved as a whole, `not_launched` rows with zero usage, immutable run and experiment UUIDs, strict ledger parsing,
superseded directory refusal, the write guard and per child recheck, the companion manifest, and the timing windows
with bounds (upper for the arm under test, lower for the reference) are implemented as the joint decision states and
are covered by tests.

**O2 OK (auth safety).** Only the baseline, the worker homes and `D/homes` hold token text; evidence keeps hashes; the
probe home gets unaccepted tokens with the baseline's account metadata and is never propagated; propagation checks the
prepared generation and `last_refresh`; token separation from `~/.codex/auth.json` and the runner's CODEX_HOME is
checked under the authentication lock before every reconstruction; the wave gate reads exp locally, fails closed and
names `CODEX_HOME=~/.ozmap_rep/baseline codex login`. Nothing copies the owner's auth.json.

**O3 OK (budgets).** Allocations, two reserves per allocation, caps (Codex 38, 4, 20, 62; Sonnet 26, 2, 12, 40), the
reserve reasons and the A4.13 caps (20, 40, 4, 40, global 206) match the signed text; live budgets count the
experiment ledger deduplicated by attempt uid; the dry run stays within every A4.4 bound. Ledger at the time of
writing (this review and the other round 3 council calls included): Astra 11 of 20, Opus 25 of 40, Fable 2 of 4,
Sonnet 1 of 40. Evaluation calls so far: 0 Codex, 0 Sonnet.

**O4 OK (gold error scoping).** `bootstrap.assess` invalidates efficiency only for an operation in R with a proposed
rule; BoolQ is never in R, so the pilot's second invalidation cannot recur; malformed or missing output is a completion
failure; classification misses are reported without changing R.

**O5 OK (cache certification).** The archived pair, its envelopes and the decoder hash verify; certificate authority
is separate from pair validity; positive cached input without authority and positive `cache_write_input_tokens` are
unverified; the scorer derives every accounting field again from the capture.

**O6 OK (scoring gates).** Exact fractions, unrounded ratios, cold makespan reported without a gate, bootstrap charged
fully to cold B and C, magnitude invalid before any ratio on any validity problem or safety kill, inconclusive on
incomplete cells, usage, evidence, timing or open audits, simulation never evidence, run bound freeze and artifact
chain required for claims, leakage experiment wide including superseded directories.

**O7 OK (resumable cells).** Terminal batches are read back and never resent; a quota or isolation stop between
groups abandons the staged group without a charge and the cell resumes; DONE and SETTLED cells are never rerun; unmet
requirements refuse; an ambiguous kept marker blocks its batch.

## Before the freeze

1. Signatories: the A4.2 revision of B1 (or a recorded reading plan), the P1 to P5 confirmations and the annexes of
   B2, D1.
2. Implementer: B3, B4, C1 to C7 with regression tests; RT2.1 changed as accepted; acceptance changed only with the
   signed A4.2 revision; acceptance and red team suites otherwise unchanged.
3. The pre freeze no auth probe, `run freeze`, then telemetry, launched detached.

Signed: Opus council reviewer, code correctness lens, round 3.
