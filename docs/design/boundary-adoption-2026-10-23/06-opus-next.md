# After the failed adoption qualification: Opus 5.5

**Decision:** classification becomes a host operation in step 4. No new model-side attempt. The question is closed
for the workflow, and the evidence is recorded as it stands.

## Why

1. The fault survived every model-side change we paid for. The frozen op failed. Explicit wording helped. Wording plus
   the checked interval was 6 of 6 on one packet, then failed at call 9 on the first goal other than the probe's,
   with the same error (equality at the upper limit read as outside, 0 thinking). One more wording or effort variant
   would be another bet on the same unexplained failure, and each attempt needs a new preregistration and a 120k
   allocation.
2. The metric order puts correctness first. The host computes this label exactly from the checked interval and the
   goal limits in Decimal. It already does so twice: in `mat_classify` and in `op_handoff_rows`. A model step whose
   only safe use is to be rechecked by host code that computes the same answer adds tokens and risk without adding
   correctness.
3. Quota: about 39% used, with a 49% stop line, and O1's gate is still ahead. That gate is where a model is
   actually needed.

## Step 4

1. `inspection-handoff-20/v2`: replace the four `model.classify` nodes with four `host.classify@1` nodes. Each reads
   `/bounds/X` of node 11 and the structured goal limits. The graph keeps 20 nodes. `model.classify` v1 and v2 stay
   in the record and are not deleted.
2. Expected primary launches become 2, 0, 2, 4, 0. Extract and bounds are unchanged, still experimental compositions.
3. Gate: a zero-token dry gate only, with every scenario, the sabotage cases and the independent evaluator. No paid
   suite now. G3b's pass stays the live evidence for v1. Any live claim about v2 waits for a future preregistered run
   and is not needed to make the change.
4. The adoption results stand as recorded. Size-4 cell: fail. Size-1 cell: untested. Adoption: not passed. The probe
   claim stays at "no failures in six repetitions of that frozen packet".

## Language guidance

1. Rule: **if the host can compute a step exactly from checked values, make it a host operation; do not send it to a
   model.** The executor should flag a model op whose check recomputes the full answer from the same inputs. That
   check is the signal.
2. Withdraw the round 1 line "pass a checked intermediate explicitly" as a reliability guideline. Keep it only as an
   observation: it fixed one packet and did not carry over to a new goal.
3. Recorded limit, as a measured fact and not a model rule: Sonnet 5.5 at default effort misread inclusive equality
   in 4 workflow and adoption calls (live1 2, live2 1, adoption 1) and in 5 of the probe's 6 control calls. All of
   them ran at 0 thinking tokens.
   Zero thinking is not sufficient for the error: adoption calls 6 and 8 were right at 0. A cause is not established.
4. An effort or forced-reasoning study is a research question, not a step 4 need. It is not scheduled.
