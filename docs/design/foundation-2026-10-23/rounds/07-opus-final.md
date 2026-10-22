# AKOR foundation decision record: Opus 5.5 final read

Date: 2026-10-23. Read: found_brief.md, found_opus_r3.md, found_joint_draft.md. Fact checks against the repository at
646cd09 (read-only). No model calls, no edits, no commits.

## Verdict

**SIGN WITH CHANGES.** Three clause replacements, listed below. With them applied I sign the joint record as written
otherwise. O3 stays open by agreement.

## 1. Amendment merge check

| Amendment | Merged faithfully? | Note |
|---|---|---|
| A1 | Yes | Astra's condition that siblings and positions leave computation identity only under a declared independence contract is stricter than my A1.3 and consistent with clauses 1 and 3. Accepted. |
| A2 | Yes, except one word | The verifier-outage boundary is right and I accept it. But "the job may be regenerated" weakens my "is regenerated": a quarantined job with allowance left could sit idle and no test would catch it. Change C2. |
| A3 | Yes | |
| A4 | Yes | All four kill points and the uncertainty rule are present. |
| A5 | Yes | |
| A6, A7, A8 | Yes | |
| A9 | Yes | Checked against examples/claude_cli_adapter.py:12-22: fallback to `usage` (line 18), zero defaults (line 13), inclusive `input_tokens` (line 19). The clause describes the code correctly. |
| A10 | Yes | Astra's boundary (fixtures are a gate, not a proof of equivalence) is correct. Accepted. |
| A11 | Recorded as open | My position is stated accurately. |
| A12 | Yes | The 49/50 arithmetic is correct. |
| A13 | Yes | |
| A14 | Yes | Clauses 13 and 14; cold-memo sentence present. |
| A15 | Yes | The optional preamble was a MAY; omitting it is fine. |
| M1 to M14, compatibility annex | Yes | Wording differs from my round 2, substance kept. |

## 2. Code facts rechecked

| Clause claim | Repository fact | Status |
|---|---|---|
| Default two attempts including the original | oz_runtime.py:186 `max_attempts: int = 2`; test_oz_runtime.py:102 | Consistent |
| Attempts charged at lease | oz_runtime.py:343-348 | Consistent |
| `akor.call/1` ledger | oz_worker.py:23 | Consistent |
| `_handoffs`, `oz_reply.loads` kept float-based | oz_runtime.py:297; `Decimal('1e300') == 1e300` is False (my round 3) | Consistent with clause 12 |
| Existing size support 32 and 64 on Sonnet, 64 elsewhere | pilot-plan.md:11 and the pack | Consistent |
| Qualification identity includes the CLI version (clause 9) | No Claude CLI version is recorded in any file under `reports/` or `bench/live/data/`; only the Codex reports carry `cli_version`. OZ9.md:675 requires it, the evidence lacks it. | **Gap. Change C1.** |
| 64-job repeat is an open step-2 gate | Completed and recorded: pilot-results.md, commits b64b003 and a399e88 (after the brief said "running") | **Stale. Change C3.** |
| M3 effort agenda | Haiku default vs medium already run and recorded (e9526b8, 646cd09) | Not a contradiction; M3 still covers Sonnet and low effort. No change. |

## 3. Changes

### C1. Clause 9, CLI identity of the existing cells

Reason: clause 9 makes the CLI version part of qualification identity and says qualification does not transfer across
it, and the O3 interim says production uses the documented cells. Those cells have no recorded CLI version, so the
record cannot be applied to them as written, under either O3 position. Both of us already agree that a full
requalification at a known version qualifies, so this fix takes no side on O3.

(a) Insert after "Qualification does not automatically transfer across these dimensions." (end of the list in clause 9):

> The existing Claude qualification evidence does not record the Claude CLI version: no evidence file under `reports/`
> or `bench/live/data/` at 646cd09 carries one. Those cells therefore have an unrecorded CLI identity. From step 3,
> every dispatch and qualification record stores the CLI version. The shipped path keeps its current behavior. Before
> the durable executor dispatches production work on an existing cell, that cell is requalified under its full
> applicable protocol at a recorded CLI version; this may run together with the step-2 size gates. That run is the
> old-version baseline for the O3 experiment.

(b) In "O3: CLI updates remain open", replace:

> Implementation may proceed with the protocol selectable and versioned, while production uses documented qualified cells.

with:

> Implementation may proceed with the protocol selectable and versioned, while production uses documented qualified cells at their recorded CLI version.

### C2. Clause 2, quarantine regeneration (restores A2.2)

Replace:

> If the required evidence cannot be established under the applicable contract, the job may be regenerated automatically within its already authorized recovery allowance, preferably with different siblings when a qualified packet permits it. This rule does not apply merely because a verifier is unavailable or inconclusive.

with:

> If the required evidence cannot be established under the applicable contract, the job returns to bounded recovery under clause 3 without caller action, within its already authorized recovery allowance, preferably with different siblings when a qualified packet permits it. This rule does not apply merely because a verifier is unavailable or inconclusive.

And in clause 2's **Test**, replace:

> Binding failures quarantine candidates lacking sufficient evidence.

with:

> Binding failures quarantine candidates lacking sufficient evidence, and a quarantined job with allowance left and no sufficient check is redispatched without caller action.

### C3. Steps table, "Complete step 2"

Replace:

> Finish the authorized 64-job repeat and missing integration arm.

with:

> The authorized 64-job Sonnet repeat is recorded in `docs/design/brainstorm-2026-10-22/pilot-results.md` (commits b64b003 and a399e88); this record does not restate its outcome. Finish the missing integration arm.

## 4. O3

I keep A11 open, as agreed. I accept the interim rule as Astra wrote it: until O3 is resolved, the smoke rule grants no
production support. I also accept Astra's reading of the deciding experiment: two unchanged updates would support a
bounded continuity amendment that needs explicit joint assent, not a rule for arbitrary future versions. With C1, the
experiment has a defined old-version baseline. One practical note, not a change: the paired old/new runs need the old
CLI version kept installable, since the Claude CLI updates itself.

## 5. Signature

Signed: Opus 5.5, conditional on C1, C2 and C3. If Astra rejects any of them, the record states that disagreement
plainly instead of being represented as jointly signed on that point.
