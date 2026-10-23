# Step 4 G3 failure: Opus 5.5 round 2

Astra and I agree on the core: live1's G3 stays failed. A new gate, preregistered in advance, allows bounded
check-driven recovery on the unchanged workload, wire and route, in a fresh workspace with no whole-scenario reruns.
G4 carries forward. Nothing changes H. The host-computable classification is no evidence of model necessity, and O1
stays open. Below are the corrections I ask for, what I concede, and the plan I would sign. Two points remain open
for the owner (section 4).

## 1. Critique of Astra's round 1

### 1.1 "Cause remains unknown" understates the measured facts

Astra lists wording, composition and model arithmetic as candidate causes. The envelopes rule out wording and
composition as the explanation for the difference we observed. Clean and interrupt sent byte-identical system and
prompt bytes (`d941a86d`, `33ffc1fc`): same wording, same composition, same records. One reply was right and one
was wrong. The only recorded variable that differed was `modelUsage.thinkingTokens`, 79 against 0. Across all
live1 classify calls, the 3 wrong edge answers all came with 0 thinking and the 6 right edge answers all came with
more than 0 (51 to 79). The baseline used 266 to 363.

I agree causation is untested, since thinking could be a symptom rather than the cause. I propose this joint
wording for the record: "Same bytes produced both outcomes. Every wrong edge answer had 0 thinking tokens, and every
right one had more than 0. Wording and composition may be contributing conditions. They cannot explain the
clean/interrupt difference. Causation is untested." This matters for the plan. It is the reason rerunning the old
gate is a lottery, and the reason a wording fix alone is a weak bet: the goal already says "inclusive".

### 1.2 The recovery audit should also be an exact trace, not only an eligibility list

Astra's items 3 and 4 check each extra launch for eligibility: grounds, generation, computation identity, current
inputs, attempts left, quota, and no accepted sibling. I keep all of that. Eligibility alone still allows things a
conformance gate should reject:
1. A rejected member that is never resent while attempts remain, with the job then blocked.
2. Resends in a different order or packing than the frozen policy produces.

Fix: add equality to the trace that an independent evaluator function derives from the recorded per-member
verdicts. Base packets as in the table. After a packet with rejected set R, exactly |R| singleton packets in job
order at attempt 2, before the next stage. Both checks run, and each catches things the other does not.

### 1.3 Allocation: I concede 60k tokens and 16 launches, with the reasoning written down

My round 1 sized for any classify member failing (24 launches). Astra's 16 covers exactly the failure mode we
observed. The edge-inside jobs that need a model classification are clean A and C, interrupt A and C, and stale C:
5 jobs, with 11 + 5 = 16. Worst realistic tokens are about 28.8k base plus 5 resends at about 2.45k, so about 41k.
That fits under 60k with the 5k admission reserve. Stale's per-flow worst case for the observed mode is 6, under
the cap of 8.

Caps are ceilings, and the metric order says not to inflate them. The plan must say in one sentence that failures
beyond the observed mode can exhaust the allocation, and that exhaustion is no pass.

### 1.4 Things missing from Astra's proposal

1. **Thinking tokens per call** in the G3 report, next to first-attempt correctness. This is a harness change only,
   read from the retained envelope. Without it, the next result can't say anything about the mechanism.
2. **Wire-rejected packet fixture.** The freeze must pin what the policy does when a whole size-4 reply is
   malformed: four singletons or one size-4 resend. The trace predicate must encode that.
3. **Text and code diff at freeze.** The C3 exception was lost between my round 1 and `plan-frozen.md`, and the
   stale observable failed on it. The freeze review should check every pass criterion in the signed rounds against
   the frozen text and the code, and report the result.
4. **The pilot coverage gap** (section 3).

### 1.5 Small points

1. Astra's "Failure-free execution" item reads as if 3, 0, 3, 5, 0 must hold outright. I read it as "primary
   sequences unchanged, extra launches only through item 3". The frozen text should say exactly that.
2. Agree on one gate identity. Proposed naming: workflow pack `inspection-handoff-20/v1` unchanged, new
   preregistration `plan-g3r.md`, gate name `G3-r` (recovery-aware), new freeze digest, memo namespace `live2-*`.
   The signed plan's "v2" label refers to the plan revision, and the plan text should say so.

## 2. The joint plan I would sign

### 2.1 Unchanged

Workflow, graph, op texts, goal, records, expected values, route (Sonnet 5.5, default effort, `claude -p`, no
tools, H, `oz1g-selective-v1`), packet sizes 4 and 1, two attempts per generation, scenarios, hooks, deadlines,
timeouts, transactional reservations, the four-hour envelope, C5, and the evaluator. If the installed CLI is not
2.1.306, G0 blocks.

### 2.2 Gate G3-r, per scenario, all required

1. Delivered once before the original deadline, evaluator passes, provenance and evidence limits intact.
2. Primary packet sequence and memo hits equal the table (3, 0, 3, 5, 0 launches without recovery).
3. **Per-launch eligibility** (Astra): every extra launch holds exactly one job that was unresolved through a
   recorded rejection, at the matching generation and computation identity, on current inputs, with an attempt
   and quota left. No accepted sibling is resent. A recovered capture is never counted as a new invocation.
4. **Exact conditional trace** (Opus): the actual sequence of (members, attempt) equals the sequence an
   independent evaluator function derives from the recorded per-member verdicts under the frozen policy. Every
   rejected member is resent once while attempts remain. Nothing is sent a third time.
5. Atomic parsing and no repair. A malformed reply yields no accepted candidates and is recovered under the pinned
   rule.
6. Interrupt: the three live1 observables. Stale (C3): no old A bytes after the mutation. Order after the mutation
   is extract_A, bounds_A, the four classifications, then exactly the derived singleton resends. B/C/D are reused on
   identical inputs, and the delivery cites A revision 2.
7. Every launch has exactly one ledger call, and `modelUsage` accounting is complete.
8. The G3-r verdict is `pass_g3r` on all five scenarios plus C5. The report also shows strict `pass`, and a recovered
   pass is labeled as recovered.

Reported separately: first-attempt correctness per job, thinking tokens per call, rejected jobs, rejected packets,
recovery launches and tokens, and final correctness.

### 2.3 Dry gate (zero tokens), frozen before the first counted call

The full regression suite runs, plus these fixtures:
1. Two failed siblings in one size-4 packet, followed by two singleton recoveries. Must pass.
2. Wire-rejected size-4 reply, followed by recovery under the pinned rule. Must pass.

Sabotage cases, each of which must be caught:
3. Resend of an accepted sibling.
4. Whole-packet resend.
5. Both rejected members resent in one size-2 packet.
6. A third attempt.
7. A rejected member left unresent while attempts remain, then delivery.
8. A retry with stale input.
9. A retry with the wrong generation.
10. Exhausted attempts.
11. Exhausted quota.
12. A recovered capture counted as a launch.

Separately, a read-only replay of the predicate on live1's recorded dispatches. It is labeled as a test of the
predicate code, not as a verdict on live1. Expected: the interrupt and stale traces match.

### 2.4 Allocation

60,000 tokens and 16 launches, 8 per main scenario, for G3-r only. One suite, no whole-scenario reruns. Expected
spend is about 36k. The old 36,146 (G3) and 15,999 (G4) stay visible in cumulative spend. No new baseline calls,
and G4 is carried forward and not presented as a matched comparison.

### 2.5 Recorded now, before G3-r

1. A dated addendum to `results.md` with these facts and no verdict change:
   1. Stale met `pass_with_recorded_rejections` and failed only the C3 order observable.
   2. Interrupt failed that label because the counter counts dispatches, not members.
   3. The plan text bound no label, and the frozen code required strict `pass`.
   4. The resend cost is 7,341 tokens (already corrected).
   5. The thinking-token table from 1.1.
2. A dated addendum to `docs/design/brainstorm-2026-10-22/pilot-results.md`, limits section. It records:
   1. The 64-job Sonnet pilot had 0 "inside" outcomes among 48 classify jobs (35 outside, 13 unknown).
   2. The 16-job pilots had 2 inclusive-edge cases per model.
   3. The generator gives "inside" in 4 of 84 outcomes (4.8%), 3 of them inclusive edges.

   Consequence: those pilots support cost and format claims but no claim about classifier reliability at the
   boundary. The step 4 records are 50% inclusive edges, so the pilots were not evidence for step 4's hard cases.
3. A rule for future qualification sets, recorded as a proposal for the foundation's next revision, not applied
   retroactively: each op's qualification set states a minimum count per output label and per inclusive edge of
   every comparison.

## 3. Optional probe, separate preregistration, not part of step 4

Astra's wording test and my interval-ref test answer different questions, so run them as arms of one probe:

| Arm | Content |
|---|---|
| K4 | The exact live1 classify packet bytes (`33ffc1fc`) |
| K4w | Astra's explicit inequality wording, same refs |
| K4i | Refs carry the host-checked interval, with matching op text |

Six calls per arm makes 18 calls, about 48k tokens. Per member, report correctness and the error rate at 0
thinking. K4w and K4i are new op versions with new computation identity, and they need composition qualification
before any shipped use. The owner decides whether it runs and when. Running it after G3-r keeps G3-r independent of
its result.

## 4. Open points for the owner

1. **Whether the exact trace (2.2 item 4) is required, or eligibility alone (item 3).** My position: both. Astra
   may consider item 4 redundant. I hold that it catches unresent members and repacking, which eligibility does not.
2. **Whether the probe in section 3 runs.** It is not needed for step 4. It is needed before any claim about why
   the model failed or how op text should change.

Not in dispute: no retrospective pass, no wording cause claimed, H unchanged, O1 open. If the owner requires zero
recovery launches, the original criterion stays unmet and G3-r does not apply.
