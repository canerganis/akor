# G3b preregistration: `inspection-handoff-20/v1`, recovery-aware live gate (frozen before the first counted call)

Plan: [README.md](README.md), signed in [03](03-astra-r2-signed.md) and signed off in [05](05-opus-r3-sign.md); the exact
trace oracle is argued in [02](02-opus-r1.md) and [04](04-opus-r2.md). This is a prospective gate revision informed by
the live1 failure. Live1's G3 stays failed as preregistered and is not rescored. A pass is reported as "conformance
passed" (executor conformance gate); it is not the owner's real-workflow criterion (O1), and it is not a claim about
model reliability.

## Identity

| Item | Value |
|---|---|
| Gate | G3b, one binding label `pass_g3b` |
| Plan revision | v2 (the signed plan); workflow pack `inspection-handoff-20/v1` unchanged |
| Freeze record | `bench/step4/inspection-handoff-20-v1/freeze-g3b.json` |
| Freeze digest | `02119a179eba62777d41f1358366e258ddf48cdfd96d080307d34c12c5328019` (short: 02119a17) |
| Live1 record, kept intact | `freeze.json` (digest 49115f95), `bench/step4/live1/`, `../results.md` |
| Workspace and prefix | fresh workspace `.oz-runtime/step4-live2`, request prefix `live2`, memo namespaces `live-live2-*` |
| Route | unchanged: Sonnet 5.5 (`claude-sonnet-5-5`), default effort, `claude -p` with no tools, CLI 2.1.306, H, `oz1g-selective-v1`, packets of 4 or 1 |

Unchanged byte for byte against the live1 freeze (a test compares every frozen file digest): workflow.json (graph,
goal, op texts and checks, scenarios and hooks, route, deadlines, expected launches), graph.json, expected.json, the
sources, and both baseline prompts. workflow.json still holds live1's executor budget (60k, 16, 8); the G3b allocation
lives in `g3b.json`. New or changed code is pinned by the new freeze: `g3b.py` (oracle and predicate, standard library
only, imports nothing from the executor), `g3b.json`, `step4.py` (trace and call recording, the verdict wiring, the live
guards), `fixture_adapter.py` (recovery and usage modes for the dry gate). The executor (`oz_flow.py`, `oz_do.py`,
`oz_runtime.py`) and the evaluator are not changed; the gate measures their recovery behavior as it is.

## Command (PowerShell, repo root)

```powershell
$env:TIKTOKEN_CACHE_DIR = ".token-cache"; $env:PYTHONIOENCODING = "utf-8"
# G0: must print "frozen": true with the digest above
.venv/Scripts/python.exe bench/step4/step4.py freeze
# G1: the full suite
.venv/Scripts/python.exe -m unittest discover -s tests
# G2: zero-token dry gate (fixture adapter), must print "pass": true
.venv/Scripts/python.exe bench/step4/step4.py dry --workspace .oz-runtime/step4-dry
# Read-only predicate regression test on the live1 evidence (not a verdict)
.venv/Scripts/python.exe bench/step4/step4.py replay-live1
# G3b: one suite, five scenarios, paid, fresh workspace, no reruns
$env:STEP4_LIVE_CONFIRM = "1"
.venv/Scripts/python.exe bench/step4/step4.py live --workspace .oz-runtime/step4-live2 --prefix live2
```

`live` refuses `--only` and `--rerun`, refuses a workspace that already holds a flow or a memo store, and refuses a
changed freeze or CLI version before any launch. `baseline` refuses to run: G4 carries forward from live1 and G3b
allocates no baseline launches. Reports: `report-live-live2.json` in the workspace, and `flows/<request_id>/execution-record.json`.

## Allocation (ceilings, not estimates)

64,000 tokens and 24 launches for the whole workspace, 10 per scenario, a 5,000-token admission reserve per launch (a
call with unknown usage is charged at the reserve), 3,600 s per scenario deadline that resume never resets, 300 s per
call, one in-flight call in quota group `claude-cli`. Expected spend is about 36k tokens. Failures beyond the observed
mode can exhaust the allocation; exhaustion of tokens, launches, attempts or time is not a pass. At about 2.7k tokens
per call the token cap binds at about 22 launches, before the 24-launch cap. The optional model probe has no
allocation here.

## Recovery policy that the oracle encodes

After a packet whose rejected set is R (a failed per-job check, a wire rejection, or a failed call), the stage resends
exactly R at attempt 2, in job order, before the next stage, in packets of the largest allowed size that fits: one
singleton per rejected member while R has fewer than four members, one size-4 packet when all four members were
rejected. A wire rejection is atomic: a reply that fails the wire yields no candidate for any member, so all four
members of a size-4 packet go back together and come back as one size-4 packet at attempt 2. This is what the frozen
packet sizes (4 and 1) and the unchanged executor do (checked in the dry gate on a wire-rejected size-4 reply), and it
is the pin the signed text left to the freeze. Accepted members are never resent, no member is sent a third time, a
member held by a verifier outage is never resent or regenerated, and a member rejected at attempt 2 leaves the stage
unresolved (no pass).

## Expected launches

| Scenario | Request | Primary launches | Primary packets | Memo hits | Notes |
|---|---|---:|---|---:|---|
| clean | `live2-clean` | 3 | 4, 4, 4 | 0 | cold namespace |
| exact repeat | `live2-repeat` | 0 | none | 12 | clean namespace |
| interrupted | `live2-interrupt` | 3 | 4, 4, 4 | 0 | hard exit at `worker.after_capture`, then at `flow.publish.after_manifest`, then the same command again |
| stale input | `live2-stale` | 5 | 4, 4, 1, 1, 4 | 6 | A becomes 12.55 mm right after node 11 commits |
| revision bump | `live2-bump` | 0 | none | 20 | A gets revision 2 with identical bytes |
| Total | | 11 | | | about 36k tokens expected with recovery, 28.5k without |

Extra launches are allowed only as derived resends. Live1's pattern would give 3, 0, 5, 6, 0 launches (14 in all).

## pass_g3b, per scenario (all required)

1. Delivered once before the original deadline, the independent evaluator verifies the delivered bytes.
2. The primary (attempt 1) packet sequence equals the table and memo hits equal the table.
3. Every extra launch is eligible: its member had a recorded rejection at the previous attempt, the same stage, the
   same generation and computation identity, a current input (the frozen source at the revision then in force: A rev 2
   after the mutation, never the old A bytes), an attempt within two, and a launch within the scenario cap of 10. No
   accepted or held member is resent.
4. The exact dispatch trace (stage, members, attempt, in order) equals the sequence `g3b.derive` computes from the
   recorded per-member verdicts under the policy above. Both 3 and 4 run; each catches findings the other does not.
5. Wire rejection is atomic and no reply is repaired.
6. No stage ends unresolved (no second rejection, no held member).
7. Interrupted: both kills hit their boundary, the first capture is recovered without a new call, the manifest is
   reconciled on resume. Stale (C3): no packet after the mutation holds the old A bytes; the order after it is
   extract_A, bounds_A, the four classifications, then exactly the derived resends; B, C and D extract and bounds are
   memo hits on identical inputs; old A acceptances stay as history and the delivery cites A revision 2.
8. Every launch has exactly one ledger call, `modelUsage` accounting is complete, and no scenario exceeds 10 launches.

G3b is `pass_g3b` on all five scenarios plus the four C5 checks (zero calls, each on an isolated copy of the clean
state: byte identity, route change gives 12 misses, strengthened acceptance-only check revalidates with no launch,
revocation of one entry gives one miss), a held freeze, and totals within 64,000 tokens and 24 launches with complete
accounting. The report also shows the strict, count-based `pass` per scenario and labels a pass that needed recovery
as `recovered`. The second label of live1's plan, `pass_with_recorded_rejections`, is retired and is not reported.

Reported separately, never part of the verdict: first-attempt correctness per job, rejected jobs and packets, recovery
launches and tokens, final correctness, and per call (`thinking_tokens_per_call`) the thinking tokens read from the
retained raw CLI envelope's `modelUsage.thinkingTokens` (recorded as unknown, never zero, when absent) next to the
members' verdicts and the call's tokens. The link between absent thinking and the three live1 wrong answers is an
observed association on six calls, not an established cause; clean and interrupt sent byte-identical system and prompt
bytes (`d941a86d`, `33ffc1fc`) and got different classifications. The checks establish the correctness of accepted
outputs under their contract, not guaranteed completion; three packets support no predictive pass probability and no
established token advantage of size 4 over singletons.

## Zero-token dry gate (G2), must pass before the first counted call

Result at freeze 02119a17: `pass: true`. All five scenarios `pass_g3b` and strict (11 launches); C5 four of four;
the six step 4 sabotage cases caught; baseline fixture smoke passes. Recovery fixtures, each through the real executor
and the predicate: two rejected siblings (4, 4, 4, 1, 1), three rejected siblings (4, 4, 4, 1, 1, 1), all four rejected
(one size-4 resend), a wire-rejected size-4 reply in classify and in extract (one size-4 resend each), rejections in
extract and bounds (4, 1, 4, 1, 4), stale with a rejection (4, 4, 1, 1, 4, 1), stale with rejections before and after
the mutation (4, 1, 4, 1, 1, 1, 4), interrupted with two rejections (4, 4, 4, 1, 1), a second-attempt failure (no
pass, no third attempt) and a verifier outage (no pass, no resend). Sixteen sabotage cases, each caught: whole-packet
resend, accepted-member resend, size-2 resend, third attempt, skipped resend then delivery, resends out of order,
wrong generation, other computation, stale input in a resend, old A bytes after the mutation, a launch beyond the
scenario cap, a wire rejection resent as singletons, a non-atomic wire rejection, a verifier outage triggering
regeneration, a verifier outage triggering a resend, and a recovered capture counted as a launch. Reservation
feasibility with live1-sized usage: two rejected members in every cold scenario (17 launches, about 45.6k tokens,
admitted throughout), three rejected members in every cold scenario (20 launches, about 53.6k, admitted throughout), a
scenario that exhausts its 10 launches (refused at the cap, no pass), and a token reserve that refuses the third launch
(no pass). The live1 replay returns matching traces for all five scenarios and is labeled a predicate regression test,
not a verdict on live1.

## Pilot coverage record

The 64-job H pilots had zero inside cases among 48 classifications; the 16-job H and Q sets each included two
inclusive-edge inside cases. The pilots give sparse boundary evidence and no qualification of the isolated size-4
classify composition, which stays experimental. Future qualification freezes minimum counts by label, boundary and
composition. O1 stays open.


Resend packing (agreed by Astra and Opus after the build): a resend of all four members of a size-4 packet reruns the experimental size-4 composition; "singleton recovery" holds only when fewer than four members are rejected. The recovery policy's worst case exceeds the per-scenario cap; the caps bind and exhaustion means no pass.


## Addendum 2026-10-23: predicate changes after the independent review (new freeze digest `d89ac55cc3c245f7257f9bfcb8273c4b6381547f6518e54115e0dfd0145955b2`, short d89ac55c)

The live2 verdict in [results.md](results.md) was established under the predicate frozen at 02119a17 plus the
independent recheck (`bench/step4/recheck.py`, 0 disagreements, and the ledger count). It stands as recorded and is not
rescored. The review findings are closed in the predicate before it is reused; the gate code (`g3b.py`, `step4.py`) is
refrozen at the digest above (`freeze-g3b.json` rewritten; the 02119a17 record is kept in git and in the live2 report).
The workload bytes, the executor and the evaluator are unchanged. No model call was made.

Predicate changes:

1. Independent member verdicts are built into `pass_g3b` (`g3b.judge_dispatch`, standard library only). Each stored
   candidate value is judged against the frozen `expected.json` (job, stage and the revision then in force) with no
   executor code, and the candidate must be the value in the preserved reply. A member with no candidate is classified
   by re-parsing the preserved runner capture (`g3b.capture_reply`, `g3b.parse_reply`, a reimplementation of the
   OZ/1g reply grammar checked against the executor's parser on a corpus in the tests): failed call, wire rejection
   (reply refused whole) or valid model error line. Any disagreement with the executor's recorded verdict, a refusal that
   cannot be re-parsed, a missing capture or missing evidence is a finding and fails the new check
   `independent_verdicts` with the reason (job, executor verdict, independent verdict). A candidate stored out of a reply
   that is refused whole is `wire_rejection_not_atomic`. The trace oracle derives the policy sequence from the
   independent verdicts.
2. Launch order is checked across stages: creation times must be non-decreasing in trace order (`launch_order`; a
   missing time is `launch_order_unrecorded`). Both are `recovery_eligibility` findings.
3. `ledger_audit` counts `call_start` lines per receipt, not distinct call IDs: one call written twice under one ID is a
   ledger problem.
4. A candidate status or verdict label outside the known set (accepted, rejected, awaiting, quarantined) fails
   (`unknown_status`); the harness no longer maps it to `stale`.
5. Labels: a refused reply is `wire_rejected`, a valid per-job error line is `model_error`, a failed call is
   `call_failed`, each as read from the capture. The executor's own columns cannot tell the first two apart, so its
   record is `no_candidate` and agrees with either. All three stay rejections with the same verdict rules (one
   resend at attempt 2). A storability failure of a model line rejects the whole reply in the executor's parser, so it
   is a wire rejection; no separate label is reachable for single-slot jobs.
6. The two generation sabotage cases are replaced: `resend_wrong_generation` is dropped (the executor never changes a
   member's generation or computation inside one stage, so the shape cannot occur; the `generation_mismatch` and
   `identity_mismatch` findings stay as unit-tested defenses) and `verifier_outage_triggers_regeneration` now has the
   real shape (a new run directory and stage index, attempt 1). `resend_other_computation` stays as a defense case.

Dry gate sabotage now has 21 cases, each caught (the 15 earlier cases that remain after the dropped generation case,
plus: executor rejects a correct answer, executor accepts a wrong answer, wire rejection claimed for a valid reply,
unknown candidate status, resend launched after the next stage, one call counted twice under one call ID). The read-only
replay of live1 still returns matching traces and the same verdicts for all five scenarios (a regression test, not a
verdict). The new predicate run read-only on the retained live2 evidence (`step4.py replay-live2`) and, with its preserved
captures re-parsed, on a copy of the live2 workspace gives no finding in the trace audit for any scenario; labeled not a
verdict, since the live2 verdict was established under the old predicate plus the recheck.
