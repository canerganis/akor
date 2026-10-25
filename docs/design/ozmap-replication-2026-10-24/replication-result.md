# oz map clean replication: result (2026-10-25)

Run `C:\ozmap_rep\runs\replication` (outside the repo), run id 37dd0e5e-8b06-4a7e-8268-70c1455d41c1, experiment
71c279d3-b11e-4c84-a365-60c1cddea49b, freeze sha256 9ecf1bd2 (freeze commit a662209, Astra A freeze sign-off f49895a,
live run manifest 508198a). Live calls from 2026-10-25T17:15:49Z to 18:49:05Z. Codex: gpt-6.1-sol, effort high,
codex-cli 0.160.0, four isolated worker homes. Sonnet: claude-sonnet-5-5, Claude Code 2.1.306, pilot prompt (A4.9).
Workload: four independently authored tensile-test operations (A4.8), 256 jobs per cell, 64 per operation; Codex BoolQ
256 jobs per cell. R = [margin, temp_class, verdict], fixed before any learner call; elong is outside R. Run ids, CLI
versions and the live window come from the run directory records; the commits are in this branch.

Scored offline with the frozen scorer, `python -m bench.ozmap_rep.score C:\ozmap_rep\runs\replication` (exit 0). Copies
(hashes rechecked against the run directory at finalization):

| file | sha256 |
|---|---|
| `replication-report.json` (= run dir `report.json`) | `de18a44f0ecfb41922c1702483d3b29ed7e26f5b66a6dff4e8671ad2806f5f28` |
| `replication-report.md` (= run dir `report.md`) | `d7da0401c7b156fb801f7d903ca6520836a273f82b5370feedbfeae9a76811c7` |

Result reviews: `result-review-astra.md` (Astra A, do_not_sign with four blockers) and `result-review-opus.md` (fresh
Opus, conditional, no blocker, every headline number recomputed from raw run data without the scorer). Both reviews were
obtained; none is missing. How each finding was handled is listed at the end.

## Verdict under A4.10, A4.11 and A4.14

**Invalid. Every gate and both magnitude checks are invalid; no backend claim, no rule learning claim, no pooling claim
and no cross backend headline is permitted** (scorer claims: permitted False, rule_learning_claim False, pooling_claim
False, cross backend headline False). Safety passed: no accepted rule answer was wrong (safety kill false).

The only invalidating finding type is leakage under A4.3: four findings, all in the Codex BoolQ cold A cell, one per call,
each "tool event verdict uncertain". The same cell also has 0 resolved jobs and unverified usage. Under A4.14.1 an
uncertain tool event makes the cell invalid, not interrupted, and the frozen scorer applies a leakage finding to every
gate of the run (gates._validity). The preserved streams, rechecked by the Opus result reviewer, show 3, 4, 1 and 4 top
level `Reconnecting... n/5` error events and in call b01 one `Falling back from WebSockets to HTTPS transport` item, and
record no tool request, no tool execution and no external read. The harness classed these streams uncertain, and that
classification stands: the stream contents do not establish that no tool ran. Signed ruling P1 set
`SIGNED_TRANSPORT_NOTICES = []` before freeze, so reconnect events have no exception; its cost note to Opus B stated that
a reconnect "enters experiment wide leakage". The verdict stands as scored; this paragraph changes nothing.

A4.11 speaks of invalidating "affected efficiency evidence". Under that narrower reading the materials gates of both
backends would be scored as comparisons and would fail their thresholds (table below). The frozen scorer applies the
experiment wide reading, the verdict stays invalid, and the conclusion is the same under either reading. The cross
backend headline and the Codex BoolQ and pooling gates are invalid under either reading.

On the numbers alone, without the validity failure, no backend meets the combined materials success condition. Both keep
cold correctness and Codex meets the warm token criterion; Codex fails cold tokens and warm makespan, Sonnet fails both
token criteria.

| Gate (A4.10) | Codex | Sonnet | Threshold |
|---|---:|---:|---|
| cold C correctness preserved | yes | yes | equal to A |
| cold C/A tokens per correct job | 0.8371 | 1.1989 | at most 0.75 |
| warm C/A tokens per correct job | 0.4758 | 0.9951 | at most 0.5 |
| warm C/A makespan | 1.2470 | 0.9172 | at most 0.9 |
| cold C/A makespan (reported, not gated) | 3.6391 | 2.3825 | none |
| scorer verdict | invalid | invalid | |

BoolQ (scorer verdict invalid): C/A tokens 1.0193, makespan 0.4065. The added gold error condition cannot be verified:
the A reference has 0 resolved jobs (256 unresolved), so C's 15 wrong answers have nothing to be compared against. These
ratios form no valid performance comparison; they describe the cost of an A cell whose four calls ended with no accepted
answer in a total makespan of 235.0 s. Pooling (verdict invalid): Codex cold C/B tokens 0.6910, makespan 1.0882; the
gate needs C better than B in tokens without worse makespan, so on the numbers it would fail on makespan.

A4.11 magnitude on R: the scorer returns status invalid (reason leakage) and computes no ratio. The A/C figures below are
descriptive only, computed by the driver from the scorer's `R_cells` and recomputed independently by the Opus result
reviewer from raw records (Codex warm A 51,731 against 51,729 tokens, per call rounding). They are not a magnitude
result and not a claim.

| R subset, warm | A tokens per correct | C tokens per correct | A/C tokens | A/C makespan (ref lower / test upper) |
|---|---:|---:|---:|---:|
| Codex | 269.42 | 62.43 | 4.3154 | 0.8019 |
| Sonnet | 167.20 | 166.39 | 1.0049 | 1.0903 |

As threshold arithmetic only: the Codex token figure meets the direction threshold, the makespan figure does not.

## What was measured (gold scored, all reported regardless of the verdict)

Tokens are charged tokens; cold B and C carry the shared bootstrap in full (A4.5). Every row matches the scorer report
and the Opus reviewer's recomputation.

| Cell | State | Correct / 256 | Unresolved | Rule answers | Calls | Tokens | Tokens per correct | Makespan s |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Codex materials cold A | complete | 256 | 0 | 0 | 4 | 68,889 | 269.1 | 39.5 |
| Codex materials cold B | complete | 256 | 0 | 142 | 5 | 83,445 | 326.0 | 132.0 |
| Codex materials cold C | complete | 256 | 0 | 142 | 3 | 57,664 | 225.2 | 143.7 |
| Codex materials warm A | complete | 256 | 0 | 0 | 4 | 68,975 | 269.4 | 20.0 |
| Codex materials warm C | complete | 256 | 0 | 192 | 2 | 32,821 | 128.2 | 24.9 |
| Sonnet materials cold A | complete | 256 | 0 | 0 | 4 | 42,521 | 166.1 | 17.8 |
| Sonnet materials cold B | complete | 256 | 0 | 0 | 5 | 56,209 | 219.6 | 42.4 |
| Sonnet materials cold C | complete | 256 | 0 | 0 | 4 | 50,978 | 199.1 | 42.5 |
| Sonnet materials warm A | complete | 256 | 0 | 0 | 4 | 42,805 | 167.2 | 20.1 |
| Sonnet materials warm C | complete | 256 | 0 | 0 | 4 | 42,597 | 166.4 | 18.4 |
| Codex BoolQ cold A | invalid | 0 | 256 | 0 | 4 | 87,608 | n/a | 235.0 |
| Codex BoolQ cold B | complete | 225 | 14 | 0 | 5 | 100,600 | 447.1 | 87.2 |
| Codex BoolQ cold C | complete | 224 | 17 | 0 | 4 | 89,301 | 398.7 | 95.6 |

BoolQ B had 17 and C 15 wrong answers. Under additive input accounting (A4.7 sensitivity, figures recomputed by the Opus
reviewer) Codex cold C/A tokens are 0.6783 and warm 0.4758, both inside the token thresholds; Sonnet cold 1.2414, warm
1.6392; BoolQ tokens 1.1333. No combined success condition holds under sensitivity either: Codex still fails warm
makespan. Sonnet `input_tokens` already include cache reads, so the additive view double counts cache for Sonnet.

### Per operation (tokens per correct job, every operation 64 of 64 correct in every materials cell)

Split in proportion to each call's records; the Opus reviewer's recomputation matches to 0.1 token per correct.

| Cell | elong | margin | temp_class | verdict |
|---|---:|---:|---:|---:|
| Codex cold A | 269.1 | 269.1 | 269.1 | 269.1 |
| Codex cold B | 637.2 | 191.6 | 235.1 | 239.9 |
| Codex cold C | 392.2 | 133.0 | 184.8 | 191.0 |
| Codex warm A | 269.5 | 269.4 | 269.4 | 269.4 |
| Codex warm C | 325.5 | 54.2 | 65.9 | 67.2 |
| Sonnet cold A | 166.1 | 166.1 | 166.1 | 166.1 |
| Sonnet cold B | 216.3 | 213.9 | 223.1 | 225.0 |
| Sonnet cold C | 194.7 | 192.5 | 203.5 | 205.7 |
| Sonnet warm A | 167.2 | 167.2 | 167.2 | 167.2 |
| Sonnet warm C | 166.4 | 166.4 | 166.4 | 166.4 |

Arm measurements, under the invalid verdict and with no causal attribution:
1. **Codex proposed rules for exactly R** (margin, temp_class, verdict) in one bootstrap call and proposed none for
   elong, with no classification miss. All three were admitted (coverage 64, 0 covered errors, rechecked by the Opus
   reviewer). Rule answers: 142 in cold B, 142 in cold C and 192 in warm C, with zero gold errors.
2. **Warm C measured fewer Codex tokens per correct job than warm A and a longer makespan.** Whole workload 128.2 against
   269.4 tokens per correct job; on R 62.4 against 269.4. Warm C makespan 24.9 s against A's 20.0 s. Warm C made two
   model calls: b00 carried 48 elong jobs plus 16 R audits (22.11 s), b01 16 elong jobs plus 16 R audits (12.77 s). The
   slowest warm C call was slower than every warm A call (at most 18.02 s).
3. **Cold Codex C, bootstrap included, measured 225.2 against A's 269.1 tokens per correct job** (16.3% fewer; the gate
   needs 25%) at 3.6391 times A's makespan. Cold C/B tokens 0.6910, makespan 1.0882.
4. **Sonnet proposed no rule** for any operation, including the three in R, as in the pilot (`pilot-result.md`). Its B
   and C arms therefore measure batching plus bootstrap overhead. Warm C/A tokens 0.9951, makespan 0.9172. All 256 warm
   C jobs resolved; in the pilot warm C left 192 unresolved. `none` is reported as an outcome (A4.9).
5. **BoolQ:** Codex proposed no rule; the bootstrap had 3 gold errors, which enter correctness only (A4.6).

## Convergence with the sealed reviewer ASTs (A4.8, observation only)

Unsealed after scoring. The files in the scratchpad `rep/sealed` match the hashes in `expressibility-review.md` and
`SHA256SUMS`: verdict 5171571e, margin 3ac7ac7e, temp_class 1c96db2d, generator build_asts.py 0edb78fb.

| Operation | Learner AST | Sealed AST | Byte identical | JSON identical | Admitted |
|---|---|---|---|---|---|
| margin | 437 bytes, 3ac7ac7e | 437 bytes, 3ac7ac7e | yes | yes | yes |
| temp_class | 428 bytes, 1c96db2d | 428 bytes, 1c96db2d | yes | yes | yes |
| verdict | 1,278 bytes, 2149df6b | 1,008 bytes, 5171571e | no | no | yes |
| elong | not proposed | none (not rule shaped) | n/a | n/a | n/a |

Sonnet proposed nothing, so it has no convergence row. The scorer's own `convergence()` refuses to run because one
evaluation cell is not complete; the comparison above repeats its logic (base64 decoded learner bytes against the
stripped sealed file, then a JSON comparison) on the bootstrap result. The Opus reviewer independently decoded the
learner ASTs and confirmed the learner sizes and hashes, 273 JSON values (objects, arrays and scalars) in the learner
verdict AST, and the margin and temp_class hash equality with `expressibility-review.md`. The sealed verdict AST has 214
JSON values by the driver's count (68 AST nodes in `expressibility-review.md` counts a different unit); that figure, the
33,765 byte bootstrap prompt, the 40 byte prefix scan and the 2 CLI notices are driver checks that no reviewer repeated.

Two of three Codex rules are byte identical to the ASTs an Opus reviewer wrote and sealed before any learner call; the
verdict rule differs and was admitted on its own cases. For this run the bootstrap call's event stream is plain (no tool
request, execution or external read), it ran in an isolated worker home under the frozen argv, and no sealed AST, nor
its first 40 bytes, occurs in the bootstrap prompt. The reviewer (Opus) and the learner (gpt-6.1-sol) are from different
model families and the operations were written by neither. One hypothesis to test is that for one subtraction with a
fixed format and for two inclusive thresholds the frozen language admits essentially one minimal canonical AST. This
run does not test it, and per A4.8 nothing here supports a claim beyond synthesis from the frozen prompt.

## Validity items

1. Isolation: passed, 0 problems, 86 isolation events, 51 launch records, artifact chain verified for all 51 calls.
2. Leakage: 4 findings, all Codex BoolQ cold A (above). Telemetry probe r1 also has event verdict uncertain (11 top level
   error events, 0 turns completed); the scorer counts no leakage for it because it is outside every cell, it is the
   designed authentication failure probe whose disposition P1 keeps, and no turn completed.
3. Accounting failures: 0. Decoder sha256 815e2aae and the six passing replay fixtures (A4.7) are from the harness
   record; no reviewer reran them.
4. Usage: complete for every evaluation call except the four BoolQ cold A calls (unverified). Codex nominal calls
   carried 46,080 cached input tokens under the archived live-6a518ece47ab certificate; Sonnet 38,154.
5. Authentication: no worker auth.json changed after any call (hash comparison per call). One auth failure, the
   designed telemetry probe r1, whose expected outcome was auth_failure. 23 reconcile records, 14 wave gates, every wave
   with at least 212 h of baseline token life.
6. Bootstrap validity: efficiency valid for codex/materials, sonnet/materials and codex/boolq; no completion failure.
7. Classification: no problem, no miss; R admitted exactly.
8. Simulation, freeze problems and artifact problems: none. Quota gates: no problem, but two pre cell gates for
   codex-materials-cold-A refused at 17:28:54Z and 17:31:33Z because the owner reading was stale under the P3 freshness
   rule. No call was dispatched; the cell's `state.json` has one invocation, 17:32:29Z, after the owner reading probe at
   17:32:16Z. The gates failed closed as designed; the cell was not relaunched.
9. Safety kill: false.

## Interrupted and stopped cells

| Cell | Harness record | Scorer state | Reason |
|---|---|---|---|
| codex-boolq-cold-A | INTERRUPTED.json, exit 75, 18:03:27Z, contained | invalid | A4.14.1 stop on leakage signals; validity before interruption makes it invalid |
| features (administrative) | INTERRUPTED.json, exit 75, crash, 17:23:41Z, contained | interrupted, no finding | the runner ended without settling the cell; no model call was recorded |

Nothing was resumed or rerun. No cell depends on either, so no dependent cell was interrupted. All other sixteen
evaluation and administrative cells have DONE.json. `cells/telemetry/state.json` still says `state: running` (last
updated 17:15:47Z) although `cells/telemetry/DONE.json` exists and both telemetry calls settled; DONE.json is the
authoritative record and that state.json was never closed.

## Preparation and review calls (A4.13.2)

The ledger `call-ledger.jsonl` has 74 rows (the first 72 hash to 6b1154ff; rows 73 and 74 log the two result reviews).
Its count sums: Astra 27 (14 preparation, 13 review), Opus 54 (24, 30), Fable 2 (1, 1), Sonnet 4 (2, 2), Codex owner
reading probes 2, total 89.

The ledger is incomplete. The workflow's durable subagent records (metadata and transcripts of the three workflow runs
and of the driver's own subagents, under the session's `subagents` directory) and the owner side Codex session files
show dispatches with no ledger row:

| Agent | Unlogged work dispatches | Unlogged halt helpers | Ledger | Lower bound | Cap |
|---|---:|---:|---:|---:|---:|
| Opus | 16 | 11 | 54 | 70 (81 with halt helpers) | 70 |
| Sonnet | 25 | 0 | 4 | 29 | 40 |
| Astra | 1 | 0 | 27 | 28 | 30 |
| Fable | 1 | 0 | 2 | 3 | 4 |

Opus work dispatches without a row: the first implementer dispatch and a second deadlock round 3 Astra driver dispatch
(build workflow), closure fixes 1 and 2 and the part 2 telemetry-freeze step, the Opus B A4.14 signature, p5-repair,
rulings-bind-1, p3-headroom, the Opus B D6 signature, three BoolQ cold A diagnosis calls, the driver's workflow
orchestration review (18:29Z to 18:35Z), the scoring subagent and this finalization subagent. Halt helpers are the eleven
workflow subagents that wrote halt entries. Sonnet: 18 live cell runner dispatches (two each for codex-materials-cold-A
and codex-boolq-cold-C), live-plan, commit-live-manifest and five Astra relays (p5, P3 repair 1, D6, freeze sign-off,
result review). Astra: a gpt-6-astra session at 18:29:24Z, beside the orchestration review. Fable: the round 3 co-solver
dispatch that was replaced by Opus on the owner's instruction. Astra's count could be one higher if an eighth Astra
session between 14:40Z and 15:16Z on 2026-10-24 belongs to the replication; the reconstructed row counts seven.

Cap compliance, in the order revisions took effect:

1. **Opus 40 (A4.13) was exceeded before revision 1 took effect.** Counting work dispatches only, the 41st Opus call
   completed at 2026-10-25T00:49:45Z (part 2 telemetry-freeze), and at least 43 Opus calls had completed when the
   revision 1 Opus B signature completed at 01:33:37Z. Revision 1 does not authorize earlier overruns (A4.13r1.1). This
   is an open protocol compliance finding.
2. Opus 70 (revision 1): work dispatches reach 70 with this finalization, at the cap; counting the halt helpers as
   separate agent sessions under A4.13.2 gives 81, over the cap. Open finding.
3. Astra 20 (until revision 2 completed at 15:03:03Z on 2026-10-25): the ledger reaches 20 with the revision 1
   signature, and the revision 2 signature is a permitted signature exchange under A4.13.2; with the possible eighth
   pre-build session the count before revision 2 would be 21. Astra 30 (revision 2): 28 at least, within the cap.
4. Sonnet 40 and Fable 4: within the caps.
5. Global (206, then 236, then 246; it includes evaluation calls): known calls are 132 preparation and review (143 with
   halt helpers) plus 51 evaluation calls, 183 (194), within every global cap. The ledger alone gives 87 + 51 = 138
   without the result reviews, a lower bound.

These calls enter no cell computation (A4.13.3), so the scored verdict does not change. The workflow did not stop when
the Opus 40 cap was exceeded because the ledger it checked had no rows for these dispatches. The two owner reading
probes are small Codex calls from the owner's default home to refresh the P3 quota reading; they are not evaluation
calls. Runner summaries for some cells pointed at the pilot run directory `bench/ozmap/runs/live-bb76c7b0f329`; the
durable records in the replication run directory supersede them.

## Run costs

| Item | Physical calls | Charged tokens |
|---|---:|---:|
| Codex evaluation (nominal) | 29 | 539,464 |
| Codex telemetry | 2 | 11,519 |
| Sonnet evaluation (nominal) | 20 | 215,587 |
| All calls | 51 | 766,570 |

Budget use: Codex 31 of 62 (nominal 29 of 38, reserve 0 of 20, telemetry 2 of 4); Sonnet 20 of 40 (reserve 0). Codex
nominal calls used 19,580 reasoning tokens. Warm increments: Codex A 68,975 and C 32,821; Sonnet A 42,805 and C 42,597.
The shared bootstrap is one physical call per workload (Codex materials 25,760, Codex BoolQ 24,079, Sonnet materials
19,523, from the bootstrap attempt records), counted once in the physical total and in full in both cold B and C. Driver
quota readings: Claude weekly all models 77% at launch and 78% at scoring. Codex primary used_percent in
`evidence/quota.jsonl`: 2% at telemetry and features, 3% from the materials bootstrap through BoolQ cold A, 4% at BoolQ
cold B and C. The owner reading probes are about 29 tokens each by the driver's reading.

## What follows

1. The replication does not establish the pilot result. It is invalid under the preregistered tool event uncertainty
   and leakage disposition (A4.14.1, A4.3), and on the numbers alone neither backend meets its combined materials
   condition, and the pooling gate fails on makespan.
2. Descriptive counts only: Codex proposed 3 rules, for exactly the blind R, and all 3 were admitted; 476 rule answers
   (142 + 142 + 192) across cold B, cold C and warm C had zero gold errors; safety kill false.
3. A further replication needs, before freeze, a ruling that decides with archived reconnect and fallback fixtures and
   anchored grammars under which narrow conditions verified transport notices are an exception; uncertain execution
   stays invalid. It also needs a ledger row for every subagent dispatch, written by the workflow, not by the subagent.
4. Two of three learner ASTs matched the sealed reviewer ASTs byte for byte, with reviewer and learner from different
   model families. A test with operations that admit several distinct minimal ASTs would help test the language
   narrowness hypothesis; it would not by itself separate every other channel.

## Open items

1. Opus cap overruns (above): 40 exceeded before revision 1, 70 reached or exceeded. Resolving them needs a ledger and
   amendment decision, outside this document.
2. The ledger lacks the rows listed above; this document does not edit the ledger.

## Review dispositions

Blockers (Astra): B1 BoolQ added errors, fixed (cannot be verified). B2 Readings 2 and 3, fixed (arm measurements only).
B3 cap claim, fixed (reconciliation above; the claim "no cap was exceeded" is withdrawn, and overruns are listed as
open). B4 What follows 2, fixed (descriptive counts only; mechanism and pilot magnitude conclusions removed).

Astra changes adopted: single validity failure wording; transport cause stated as an observation that does not override
`uncertain`; combined condition wording for the materials gates; BoolQ "235 s of reconnects" and "no information";
sensitivity wording; Reading 2 call description; Reading 3 net reduction; Reading 4 ratios instead of "within noise";
convergence hypothesis wording and unverified driver checks marked; total calls and global cap including evaluation;
What follows 1, 3 and 4. Partly rejected, with reason: R subset figures, sensitivity figures, the per operation table,
admission counts, the validity counts and cached tokens, the interrupted cell records, the ledger hash and the reasoning
token count are kept because the Opus reviewer recomputed them from raw run data; the report hashes were rechecked
against the run directory; the provenance ids are run directory records and branch commits; the pilot comparisons in
Reading 4 are kept because `pilot-result.md` states them. Astra's pack did not contain these sources.

Opus changes: C1 adopted through B4. C2 adopted. C3 adopted. C4 adopted. C5 adopted. C6 adopted. C7 adopted through B3.
C8 adopted. C9 adopted (unit named; the sealed 214 count stays a driver figure).

Finalized 2026-10-25 by an Opus finalization subagent; no further model call was made for this step.
