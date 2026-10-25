# Result review: fresh Opus reviewer (2026-10-25)

Reviewed: `replication-result.md` (untracked, as of 18:57Z) against A4.1 to A4.12, A4.13 (revisions 1 and 2) and A4.14.
Raw data: `C:\ozmap_rep\runs\replication` (`attempts.jsonl`, `cells/*/result.json`, `cells/*/windows.jsonl`,
`cells/*/state.json`, DONE and INTERRUPTED files, `captures/`, `evidence/`). I recomputed from that data without
`score.py`. Gold came from `bench.ozmap_rep.workload.gold` (the frozen oracle), compared by exact string equality.
Tokens came from per attempt `charged_tokens` and `additive_tokens`, with the shared bootstrap charged in full to cold B and C.
Makespan is the sum of the cell's `windows.jsonl` close `elapsed_s`, plus the bootstrap window for cold B and C.
Per operation tokens are split in proportion to each call's `records`. I did not read the sealed directory or ops
content. Script: scratchpad `rev/recompute.py`.

Verdict: **conditional**, no BLOCKER under A4.14.2. Every headline number reproduces. The invalid verdict is correct and
conservative. Changes C1 to C9 should be applied before the result is signed.

## Recomputed numbers

| Cell | Correct | Wrong | Unresolved | Rule | Calls | Tokens | Tokens per correct | Makespan s | Match |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Codex materials cold A | 256 | 0 | 0 | 0 | 4 | 68,889 | 269.10 | 39.48 | yes |
| Codex materials cold B | 256 | 0 | 0 | 142 | 5 | 83,445 | 325.96 | 132.03 | yes |
| Codex materials cold C | 256 | 0 | 0 | 142 | 3 | 57,664 | 225.25 | 143.69 | yes |
| Codex materials warm A | 256 | 0 | 0 | 0 | 4 | 68,975 | 269.43 | 19.99 | yes |
| Codex materials warm C | 256 | 0 | 0 | 192 | 2 | 32,821 | 128.21 | 24.91 | yes |
| Sonnet materials cold A | 256 | 0 | 0 | 0 | 4 | 42,521 | 166.10 | 17.83 | yes |
| Sonnet materials cold B | 256 | 0 | 0 | 0 | 5 | 56,209 | 219.57 | 42.36 | yes |
| Sonnet materials cold C | 256 | 0 | 0 | 0 | 4 | 50,978 | 199.13 | 42.45 | yes |
| Sonnet materials warm A | 256 | 0 | 0 | 0 | 4 | 42,805 | 167.21 | 20.08 | yes |
| Sonnet materials warm C | 256 | 0 | 0 | 0 | 4 | 42,597 | 166.39 | 18.42 | yes |
| Codex BoolQ cold A | 0 | 0 | 256 | 0 | 4 | 87,608 | n/a | 235.05 | yes |
| Codex BoolQ cold B | 225 | 17 | 14 | 0 | 5 | 100,600 | 447.11 | 87.17 | yes |
| Codex BoolQ cold C | 224 | 15 | 17 | 0 | 4 | 89,301 | 398.67 | 95.56 | yes |

Gate ratios (mine / result): Codex cold tokens 0.8371 / 0.8371, warm tokens 0.4758 / 0.4758, warm makespan 1.2463 /
1.2470, cold makespan 3.6391 / 3.6391. Sonnet 1.1989 / 1.1989, 0.9951 / 0.9951, 0.9175 / 0.9172, 2.3813 / 2.3825. BoolQ
tokens 1.0193 / 1.0193, makespan 0.4066 / 0.4065. Pooling tokens 0.6910 / 0.6910, makespan 1.0883 / 1.0882. The
makespan differences (at most 0.012 s per cell) come from my invocation windows against the scorer's submission to
resolution work windows. No gate outcome changes.

Additive sensitivity: Codex cold 0.6783, warm 0.4758. Sonnet cold 1.2414, warm 1.6392. BoolQ tokens 1.1333. All match.
Sonnet `input_tokens` is inclusive of cache reads in `usage_raw` (warm C b00: input 7,878, cached 7,876, creation 0), so
the charged figures are right and the additive view double counts cache. Calling it sensitivity only is correct.

R subset (proportional to records): Codex warm A 51,731 vs scorer 51,729 (per call rounding), warm C 11,987. A/C
tokens 4.315, makespan 19.976 / 24.909 = 0.8020. Sonnet A/C tokens 32,104 / 31,948 = 1.0049. The per operation table
matches to 0.1 token per correct in every cell.

Costs: 51 physical calls, 766,570 charged tokens. Codex nominal 29 calls, 539,464 tokens, 19,580 reasoning tokens,
46,080 cached tokens (cold A b01 16,128; BoolQ B b00, B b01 and C b00 9,984 each, all `cache_certified`). Sonnet 20
calls, 215,587 tokens, 38,154 cached. Telemetry 2 calls, 11,519 tokens. Live window 17:15:49Z to 18:49:05Z. All match.

Other checks that hold. BoolQ bootstrap: 3 gold errors. Learner ASTs decoded from the bootstrap `result.json`: margin
437 bytes, 3ac7ac7e; temp_class 428 bytes, 1c96db2d; verdict 1,278 bytes, 2149df6b, 273 JSON values. The margin and
temp_class hashes equal the sealed hashes in `expressibility-review.md` lines 153 and 154. All three were admitted with
coverage 64 and 0 covered errors, and elong was not proposed. Sonnet proposed nothing. Rule answers total
142 + 142 + 192 = 476 with 0 gold errors. No attempt has a tool request, tool execution or external read. No
`auth_changed` on any Codex call. The only auth failure is the designed telemetry probe r1. No retries (`try` 0
everywhere), no timeouts, and cached never exceeds input. BoolQ cold A streams have 3, 4, 1 and 4 `Reconnecting...`
error events, and b01 has one `Falling back from WebSockets to HTTPS transport` item. Every call ends with
`turn.completed` and an agent message, and the cell's `result.json` keeps 0 answers. There are 86 isolation records,
51 launch records, 23 reconcile records and 14 wave gates, all with at least 212 h of token life. Every Codex cell has a
features record with `ok` true and only `unified_exec` enabled. The ledger's first 72 rows hash to 6b1154ff, and the
per agent and per category counts match the result's table.

## Findings

No BLOCKER. Nothing here lets an invalid, leaked, misaccounted or wrong result through unflagged. The one validity
failure is reported as invalid, not interrupted. Both stopped cells are scored.

**C1 (CHANGE, A4.11 wording).** "What follows" item 2 says R token savings "(4.3x warm) are close to the pilot's 4.4x".
A4.11 allows only "at least the pilot magnitude" or "smaller than the pilot", with each missed threshold named, and
only for a valid comparison. Replace it with: descriptive only, the run is invalid, and the ratios are smaller than the
pilot (tokens 4.3154 below 4.4, makespan 0.8019 below 1.6, direction not replicated on makespan).

**C2 (CHANGE, factual).** Reading 2 says warm C "needs a full model call for 64 elong jobs plus its audits, and that
call alone (22.1 s)". In `attempts.jsonl`, b00 carries 48 elong plus 16 R audits (22.11 s) and b01 carries 16 elong plus
16 R audits (12.77 s). Fix the description. The conclusion that the slowest warm C call was slower than every warm A
call (at most 18.02 s) stands.

**C3 (CHANGE, scope of the leakage verdict).** The result applies the BoolQ cold A leakage to every gate, including
Sonnet and Codex materials. That matches the frozen scorer (`gates._validity`) and the experiment wide reading in the P1
cost note and P2. A4.11, however, reads "invalidates affected efficiency evidence". Under that narrower reading, the
materials gates of both backends would be valid comparisons that fail their thresholds (Codex: cold tokens 0.8371 and
warm makespan 1.2470; Sonnet: every token gate). Add one sentence saying so and that the conclusion does not change. The
cross backend headline and the Codex BoolQ and pooling gates stay invalid under either reading.

**C4 (CHANGE, quota statement).** "Codex primary used 3% during the live cells" is inexact. `evidence/quota.jsonl`
reads 2% at telemetry and features, 3% from the materials bootstrap through BoolQ cold A, and 4% at BoolQ cold B and C.

**C5 (CHANGE, disclosure).** `evidence/quota-gates.jsonl` has two refused pre cell gates for codex-materials-cold-A,
at 17:28:54Z and 17:31:33Z: the owner reading was stale under the P3 freshness rule. No call was dispatched and no cell
invocation was recorded (`state.json` has one invocation, 17:32:29Z, after the owner reading probe at 17:32:16Z). The
gates failed closed as designed, but "quota gate problems: none" should mention these two refusals so nobody reads a
relaunch into the three wave gate rows for that cell.

**C6 (CHANGE, record consistency).** `cells/telemetry/state.json` still says `state: running` (updated 17:15:47Z), while
`cells/telemetry/DONE.json` exists and both telemetry calls settled. Note that DONE.json is the authoritative record and
that state.json was never closed for this cell.

**C7 (CHANGE, A4.13.2 compliance, highest priority of the changes).** The result admits that runner and scoring
subagents are missing from the ledger. The durable records bound the gap: 18 cell invocations, one per cell including
telemetry and features (`cells/*/state.json`). If one runner subagent served each cell and the runners were Opus, Opus
would be at least 53 + 18 = 71 before the scoring and review calls, which is over the cap of 70. If they were Sonnet,
the total is at least 22 of 40 and within the cap. Find the runner model and dispatch count in the workflow's durable
record, add the rows, and state plainly whether a cap was exceeded and when. Under A4.13.3 these calls enter no cell
computation, so this is not a result BLOCKER. It is still a protocol compliance finding that A4.12 ("cap exhaustion is
not completion") and A4.13.2 require reporting.

**C8 (CHANGE, completeness).** Telemetry probe r1 also has event verdict `uncertain` (11 top level error events, 0
turns completed, expected outcome auth_failure). The scorer counts no leakage for it. Add one line explaining why:
it is outside every cell, it is the designed authentication failure probe whose disposition P1 keeps, and no turn
completed. Without that line, "Leakage: 4 findings" looks like it skipped a fifth uncertain stream.

**C9 (CHANGE, unit).** "273 vs 214 JSON nodes" counts JSON values (I get 273 for the learner verdict AST by counting
every object, array and scalar). `expressibility-review.md` gives the sealed verdict as 68 AST nodes. Name the unit
so the two documents do not look inconsistent. I did not verify 214, because the sealed file is out of scope here.

## Claims checked against the amendments

1. Verdict invalid, no claim permitted (A4.10, A4.11, A4.14.1): correct. BoolQ cold A is invalid, not interrupted,
   as A4.14.1 and A4.14.2 require. The INTERRUPTED.json exit 75 and `contained: true` are preserved, and nothing was
   rerun.
2. Gate numbers on their own (A4.10): correct. Codex fails cold tokens (0.8371 above 0.75) and warm makespan (1.2470
   above 0.9). Sonnet fails cold and warm tokens. The pooling makespan is 1.0882, worse than B.
3. A4.11 magnitude: the scorer status is invalid with no ratio, and the result's descriptive table is labelled as not
   a claim. See C1 for the one sentence that drifts from that.
4. Bootstrap errors (A4.6): BoolQ's 3 bootstrap errors enter correctness only, and there was no materials bootstrap
   error. Correct.
5. Classification (A4.6): Codex proposed and admitted exactly R and there is no miss. Correct.
6. Convergence (A4.8): reported after scoring as an observation, with the claim limited to synthesis from the frozen
   prompt. Correct. The margin and temp_class hash equality holds against the committed expressibility review.
7. Sonnet `none` reported as an outcome with no prompt change (A4.9): correct.
8. Budgets (A4.5): Codex 31 of 62 (nominal 29 of 38, reserve 0, telemetry 2 of 4), Sonnet 20 of 40. Per allocation
   use stays within A4.5 (BoolQ B 4 of 4, C 3 of 3). Correct.
9. Authentication (A4.2): the exp gate held at every wave and no worker hash changed. Correct.
10. Preparation counts (A4.13): the logged counts are correct. See C7 for the unlogged ones.

Signed: Opus (fresh result reviewer, 2026-10-25). This call is logged in `call-ledger.jsonl` as opus, result-review,
review, 18:57:40Z.
