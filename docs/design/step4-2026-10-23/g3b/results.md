# G3b live result: pass

Freeze 02119a17, fresh workspace, one suite, Sonnet 5.5 through `claude -p`, CLI 2.1.306, selective profile.
Evidence: `bench/step4/live2/` (report, every candidate with verdicts, every call ledger).

| Scenario | Launches | Packets | Memo hits | Package verified | pass_g3b |
|---|---:|---|---:|---|---|
| clean | 3 | 4, 4, 4 | 0 | yes | yes |
| exact repeat | 0 | none | 12 | yes | yes |
| interrupted, two hard kills | 3 | 4, 4, 4 | 0 | yes | yes |
| stale input A | 6 | 4, 4, 1, 1, 4, 1 | 6 | yes | yes, recovered |
| identical-byte revision bump | 0 | none | 20 | yes | yes |

Totals: 12 launches, 31,346 tokens, accounting complete (caps 24 and 64,000). In the stale scenario the model again
answered classify_C (12.51 ± 0.01 against [12.48, 12.52]) with "outside"; the host check rejected it and one singleton
resend at attempt 2 answered "inside". The other four scenarios ran at their primary launch counts.

Hidden reasoning, both live runs together (10 classification calls): the four calls that gave a wrong answer all used
0 thinking tokens; the six that were all right used 51 to 79. In live2, clean and interrupted classify used 79 each and
were right; the stale packet used 0 and was wrong; its resend used 64 and was right. An observed association, not an
established cause.

## Independent review of the gate and how this result was checked

A review of the G3b gate (no live access) found that the predicate takes each member's accept or reject verdict from
the executor's own records, while the signed text asks for independently checked verdicts; it reproduced a false pass
when the executor's check wrongly rejects a correct answer. Lower findings: cross-stage launch order is not checked,
duplicate ledger lines with one call ID are merged, unknown candidate statuses pass silently, the generation sabotage
cases test a shape the executor cannot produce, and model error lines are labeled as wire rejections.

For this run those gaps were closed directly from the evidence:
1. `bench/step4/recheck.py` judges every stored candidate against the frozen expected values with no executor code:
   live2 77 candidates (76 accepted, 1 rejected) and live1 79 (76, 3), **0 disagreements** with the executor's verdicts.
2. The live2 ledgers hold exactly 12 `call_start` lines with 12 distinct call IDs, equal to the 12 launches.
3. No wire rejection, model error line, or unknown status occurred; stages ran one after another.

So the pass stands for this run. Before G3b's predicate is reused, the review findings must be fixed in the predicate
(independent verdicts built in, cross-stage order, ledger duplicates, unknown statuses, real regeneration cases, error
line labels).

## What step 4 now shows, and what it does not

Shown on this conformance workflow: dependent model stages with host joins and a validation barrier, exact memo reuse
(0 model tokens for a repeat or an identical-byte revision), hard-kill resume without re-paying a captured call, a stale
source recomputing only what depends on it, and per-job checks catching and repairing wrong model answers before
delivery. Not shown: the owner's real-workflow criterion (O1); every model job here could be done by the host. The
no-orchestration baseline (G4, live1) remains cheaper on a cold run (about 4,000 tokens against about 8,000).
