# Stage 1g debate, Astra and Fable (2026-10-13), rounds 1-3

Translated from Turkish by Claude Sonnet 5.5; the original text is in git history (commit 5abbc82).

Verbatim, except that Fable round 3 cites the H system text by reference instead of repeating the block (identical to Astra round 2).


## Fable round 1

Fable, round 1 proposal (read-only; evidence re-derived from bench/live/data/live21_1g_screen_sonnet.jsonl, live20_1f, live16/17 S1 runs).

## 1. Diagnosis

What the evidence shows:

1. The three 1g arms produce byte-identical content. On every seed where C passed, the C, G and H replies are identical to the byte (H minus its header). On seed 1000 the C reply differs from G in exactly one character: line 1 starts with `[` instead of `{` (`["e1",[...]]`, then 63 identical lines). On seed 1002 C starts with `[`, the only legal continuation of `[` is an error record, so the model emitted 16 placeholder error records `["eN","error","x","x"]`, then prose, then a redo that is byte-identical to G's 64 lines. So both C failures are the same single event: the first visible token after thinking forked to `[`. Nothing else in the reply is affected by wording.
2. Correctness (320/320) is therefore not 5 independent samples per arm; it is one content sample per seed shared by all three arms. Acceptance is the only per-arm signal.
3. 2/5 vs 0/5 is not significant (Fisher p=0.44). G and H both at 0/5 is suggestive (P about 0.03 if all three arms forked at C's rate) but five reps cannot separate anything.
4. The same first-chunk fork is the whole failure history of line formats on Sonnet 5.5 with this packet: S1 4/10, S1c 1/10, S1f 3/3 (typographic quote or flatten, both in the first tokens), C 2/5, G 0/5, H 0/5. Pooled non-header line formats: 10/33, about 30%. My earlier p=0.002 was for typographic quotes only; the real failure class is "first visible token(s) commit to a wrong branch", and the branch morphs to whatever the nearest wrong shape is. Every slip is followed by prose and a redo, which the atomic parser correctly rejects.
5. Cause of the `[` prior in 1g: the failure record `["w","error",...]` and the input `jobs` rows both start with `[`. The fork happens at the thinking-to-text boundary and only there; lines 2 to 64 copy line 1.

What it does not show: whether the header (fixed string at the boundary) or G's wording ("Array results remain array values", six-string example, "check before emitting each line") lowers the fork rate. Since content is identical across arms, the only quantity to measure is the fork rate per arm, and that needs 20+ reps.

## 2. Wire

Adopt H if it passes the test below: C's text with one sentence replaced, parser requires the header. Cost: system 1020 vs 1012 o200k, reply +3 tokens (`OZ/1g\n`). Asymmetric risk favours it: if unnecessary it costs 0.2%; if necessary and absent, a 20 to 30% retry rate on Sonnet kills the 35 to 40% target.

System text: C verbatim, with
```
Reply with one compact JSON record per job on its own line.
```
replaced by
```
Reply with the line OZ/1g, then one compact JSON record per job on its own line.
```
Nothing else changes (field list, newline escaping, "malformed nonblank line", "Stop after the last job" stay).

Parser rules (profile selected by wire version, never detected from the reply):
1. Split on LF, strip one trailing CR per line, skip lines that are empty or only ASCII SP/TAB.
2. The first remaining line, after stripping trailing SP/TAB, must be exactly `OZ/1g`; otherwise reject the whole reply ("missing header").
3. All later lines go through C's parser unchanged: one-key object = success, four-element `[id,"error",code,message]` = failure, exact ID set, atomic rejection. A repeated `OZ/1g` line is a malformed line and rejects.
4. No repair of any kind (unchanged from Astra's points 1 to 10).

Fallback if H also forks in the test: remove `[` from the legal first-token set entirely by making the failure record an object with exactly two keys, `{"job_id":null,"error":[code,message]}` (distinct from one-key success and from any success value). Not proposed now; only if the header fails.

## 3. Deciding live test

Sonnet 5.5, default effort (same as the product), the same 64-job extract-first packet, retry=0, arms C, G, H, 20 new reps each (seeds 1005 to 1024), call order shuffled per rep, job order fixed. Pass per call = whole reply accepted and 64/64. Pool with the existing 5 reps: 25 per arm. 0.8-exec: no new calls needed for the decision; its cost is stable (6591 in, 2871 out); add 5 paired reps only if the owner wants seed-paired cost numbers. Budget: 60 calls, about 340k tokens, about 15 minutes.

Why 25: with a true fork rate of 0.3 (the pooled history) the chance of at most 2 failures in 25 is 0.009; with a true rate of 0.05 it is 0.87. The gate is powered for the rates that break the token target and indifferent below them, which is what matters: 1g costs about 5650 tokens per 64 jobs vs 9460 for 0.8, so a 35% saving survives a retry rate up to 8%.

Pre-registered decision rule:
1. An arm is eligible only with at most 2 failures in 25 (8%).
2. Among eligible arms, adopt the one with the fewest failures. Ties: C, then H, then G (C is the shipped text, H keeps C's wording, G adds a per-line check sentence whose effect on non-thinking models is unknown).
3. C is already at 2, so C wins only if it has 0 new failures and H and G each have at least 2 in 25.
4. No eligible arm: no adoption, go to the fallback above in a new round.

Confirmation of the adopted arm, scaled to what is informative: Haiku 5.5, 64 jobs, 20 reps (gate at most 1 failure); Fable 5.1 and Luna medium, 64 jobs, 10 reps each (gate 0); Sonnet 32 jobs, 10 reps (gate 0); five heterogeneous packets (empty array, scalars, object, nested array, zero and many refs, permitted unknown, the four real error codes) on Sonnet and Haiku, any failure blocks. 0.8-exec paired at 5 reps per model for the cost metric. Astra's 4 models x 2 sizes x 30 reps x 2 arms (480 calls) buys little over this: the Sonnet 25-rep screen carries the decision, the rest checks for model-specific breakage.

Record per call, as now: accepted, correct, provider in/out/thinking tokens, api_ms, model id. Report first-try acceptance, failure type (first-token fork, prose, other), and the cost metric total tokens of all calls / jobs in fully correct accepted packets.


## Astra round 1

**My independent proposal: C should be withdrawn; the G text in the evidence, as it is and without a header, should become the new adoption candidate for OZ/1g.** This is an explicit revision of the earlier decision; it is not a production pass achieved by G winning the earlier screen. I have not yet seen Fable's independent proposal.

The decision I gave for C failed in the screen. The parser worked correctly: in the first reply it rejected the wrong record container, in the second the invalid error codes and the correction block. I do not propose loosening the contract to accept these.

**My reasons for choosing G are these:**

- G and H are equal in observed acceptance and accuracy: **5/5 and 320/320**.
- G meets the existing budget gates. H exceeds both limits by one token each; against the earlier gate it does not count as passed.
- G keeps the existing headerless parser contract.
- The C-H comparison is a valuable finding in favor of the header. But five repeats do not show that the header is more reliable than G. Which of the differences between G and C is effective has also not been isolated.

I would not use a one-token excess to reject the header idea for good. If H has to be adopted we can decide the budget again explicitly; the current evidence does not make this necessary.

From the given, rounded means:

| Measure | 0.8-exec | G | H |
|---|---:|---:|---:|
| Total tokens per call | 9,462 | 5,652 | 5,662 |
| Reduction vs baseline | - | **40.27%** | **40.16%** |
| Mean API time | 14,152 ms | 13,336 ms | 12,954 ms |

The G-H token difference is about **0.18%**. This is not enough to claim a meaningful performance advantage. The observed latency advantage of H is also not settled yet.

**The wire I propose is exactly this:**

```text
{"job_id":complete_result}
["job_id","error",code,message]
```

The **System text G in the evidence** is used **without any change**. `v:"1g"` is kept in the body. No header, no new example, no extra check sentence and no provider-specific format instruction is added.

The earlier ten-item parser contract is kept: a one-member success object; a four-element error array; exact ID matching; a duplicate-key check in nested objects; ASCII-only blank line tolerance; atomic validation. There is no header acceptance, no detection of the old format and no reply repair.

**The experiment that decides must be a new and pre-fixed validation:**

1. **The experiment manifest is frozen.** The full system texts, parser profiles, real model IDs, reasoning settings, output limits, seeds and expected results are recorded. Calls are independent requests that carry no earlier replies. The old five repeats do not count toward the new validation.

2. **G and 0.8-exec are paired.** For Sonnet 5.5, Haiku 5.5, Fable 5.1 and Luna medium at 32 and 64 jobs, **30 new calls per cell**, `retry=0`. In each pairing the tasks and data are the same; only the call order of the arms is shuffled. The job order is kept.

3. **H is added to the Sonnet 64 cell.** The same 30 packets are run with G/H/baseline. This shows whether H's earlier success continues. In my proposal in this round the adoption candidate is G; G stays, and if H passes, the result comes back to us for a headed revision. No automatic switch is made.

4. **First-record diversity is tested separately.** Six heterogeneous packets are used for each model; the first result is, in order, a non-empty array, an empty array, a scalar, an object, a nested array and a real error. The packets cover zero/many references, the permitted `unknown` results and the four error codes. So the dependence on beginnings that look like G's six-element example is also tested.

5. **The acceptance gate is strict.** In every cell of G, 30/30 fully correct packets and accuracy in all heterogeneous packets are required. Needless errors or `unknown`, semantic wrongness and truncated replies are failures. A model that cannot be reached stays unvalidated.

The cost gate must be **at least a 35% reduction** on the same model and workload, and the target **40%**. Two measures must be reported together and must meet the 35% gate:

```text
Total tokens of all calls / number of requested jobs

Total tokens of all calls /
number of jobs in packets accepted as fully correct
```

The first measure stops the baseline's errors from artificially enlarging the saving claim. The second shows the real cost of failed generation. In the current screen the second measure comes to about 52% in favor of G; because of a wrong result in one of the baseline's packets, I would not present this as a general "52% compression" success.

Thinking and cache usage are included completely and without double counting, according to the provider's accounting. For latency, the mean, the median and p95 are reported; a speed advantage is stated only for supported cells.

**30/30 is an adoption regression gate; it is not proof of 99% first-attempt reliability.** Under the assumption of independent trials from the same distribution, the one-sided 95% upper bound of the error rate for 30 calls with zero errors is about 9.5%. To bring this bound below 1%, at least 299 error-free calls per profile are needed.

Because of the local sandbox lock I could not open the raw JSONL; the computations are from the shared table. I made no file change, live experiment or commit. The next step is to pass this proposal to Fable as it is and to evaluate it against his independent proposal.


## Fable round 2

Fable, round 2. Astra could not read the JSONL, so first the facts it did not have, then point by point, then my revised position.

## What the raw replies show (computed from live21)

1. C, G and H replies are byte-identical on every seed where C passed (H minus its header line). On seed 1000 the C reply differs from G's in exactly one character: line 1 begins `[` instead of `{`, the other 63 lines are identical. On seed 1002 C began with `[`, the only legal continuation of `[` is an error record, so it wrote 16 placeholder error records, then prose, then a redo that is byte-identical to G's 64 lines. Astra's reading ("wrong record container" and "invalid error codes") describes the parser output; the generating event is the same in both: the first visible token after thinking forked to `[`. The wording differences between G and C changed nothing after the first token.
2. Correctness 320/320 is therefore one content sample per seed shared by the three arms, not five independent samples per arm. Acceptance is the only per-arm signal, and 0/5 vs 2/5 does not separate (Fisher p=0.44).
3. The same first-token fork is the entire failure history of line formats on Sonnet 5.5 with this packet: S1 4/10, S1c 1/10, S1f 3/3, C 2/5, G 0/5, H 0/5. Pooled no-header arms 10/33. Under a 30% fork rate, 0/5 happens 17% of the time per arm.

## Astra's points

Budget gate: resolved rather than argued. The header sentence costs 8 o200k tokens. Put it on G instead of C: GH (G with "Return one compact JSON record per job on its own line." replaced by "Return the line OZ/1g, then one compact JSON record per job on its own line.") is 351 system tokens, so 999 at 32 jobs and 1458 at 64, inside both gates with 20 tokens to spare. H as defined (on C) is withdrawn. Reply cost of the header: 6 tokens.

G over H on the evidence: agree that 5 reps show nothing about header vs wording, and that the latency difference is noise. Disagree that this makes G the candidate by default. The question is the fork rate; the only way to settle it is a run with enough reps, and C is a known positive control (it forked 2/5), which is why it must stay in the screen: if C shows 0/20 in the new run the fork rate has drifted and a G 0/20 proves little.

Retract C: agree. C's wording is not the issue, but G is shorter, fits the budget and is Astra's text; nothing in the data favours C.

G vs C differences not separated: true and no longer needed. Content is identical after the first token, so the only wording effect that can exist is on the fork rate, and the screen measures that per arm.

Old five reps do not count toward the gate: agree. They count as diagnosis.

Six heterogeneous packets with a varied first record: agree, this is the right test and sharper than my version. A genuine error as the first record makes `[` the legal first token and probes exactly the fork. Keep the expected values fixed before the calls.

Two cost metrics: agree, report both; the second (total tokens of all calls / jobs in fully correct accepted packets) is the gate, since the owner pays for failures.

30 fresh calls per cell, 4 models x 2 sizes, G paired with 0.8-exec: disagree on size. That is about 480 calls plus H and heterogeneous, roughly 3.5M tokens of the owner's quota, and half of it (240 baseline calls) decides nothing: 0.8-exec is the reference being replaced, its cost is stable (in 6587 to 6603, out sd 119 over 5 reps) and 5 paired reps per model give the cost metric. The 32-job cells have never failed differently from 64; the fork is about the first token, not packet size. Fable and Luna are cheap to break but not where the wire will mostly run. What Astra's 30/30 buys over 20/20 is an upper bound of 9.5% instead of 14% per cell; the token target tolerates 8% retries, so neither bound settles that and the Sonnet screen with its positive control is what carries the decision.

## Revised position

Wire candidate: G verbatim, no header, parser contract as Astra's ten points. Alternative on the table: GH (G plus the header line; parser requires the first nonblank line, trailing SP/TAB stripped, to be exactly `OZ/1g`, everything after it goes through the unchanged G parser; a repeated `OZ/1g` is a malformed line). Profile chosen by wire version, never detected.

Deciding test, frozen manifest as Astra lists it, retry=0, call order shuffled per rep, job order fixed:

Stage 1, Sonnet 5.5, 64 jobs, extract-first packet, arms C (positive control), G, GH, 20 new reps each, seeds 1005 to 1024. 60 calls, about 340k tokens. Pass per call = accepted and 64/64.
Rule, fixed now: adopt G if G has at most 1 failure in 20. Adopt GH if G has 2 or more and GH has at most 1. If both have 2 or more: no adoption, next round tests the structural fallback (failure record as a two-key object `{"job_id":null,"error":[code,message]}` so `[` is never a legal first token). If C has 0 failures the control did not fire; record it, the rule still applies, and the 2/5 stays on file. Power: under a 30% fork rate P(at most 1 in 20) is 0.008; under 5% it is 0.74.

Stage 2, confirmation of the adopted arm: Haiku 5.5 64 jobs 20 reps, Fable 5.1 and Luna medium 64 jobs 10 reps each, Sonnet 32 jobs 10 reps, 0.8-exec 5 paired reps per model, Astra's six heterogeneous packets on every model. Gate: at most 1 failure in the Haiku cell, 0 elsewhere, all heterogeneous packets fully correct, cost reduction at least 35% on the second metric per model. About 130 calls. If the owner wants Astra's 30-rep cells, run them only on Sonnet 64 and Haiku 64, where the wire will actually run; I would not spend the quota on 30-rep baseline cells.

Where I still disagree, in one line each: the header question is decided by fork rate, not by a 1-token gate (now moot); C stays in the screen as the control; baseline reps beyond 5 per model buy nothing.


## Astra round 2

**My revised decision: H should be the first adoption candidate; G should be tested only if H fails. Let us not make C compete again.** I agree with Fable's header preference; I withdraw my earlier G priority and the broad validation matrix. On the experiment threshold, the use of old data and the fallback I propose the changes below. These are not yet a joint decision approved by Fable.

I now agree with Fable on these points:

- The cost of a failed generation matters much more than the header's roughly **0.18% H-G token difference**. An old budget excess of one token is not enough reason to eliminate H.
- The format deviation in the first visible record is the main error class to investigate. The atomic parser behaved correctly; we will not add repair.
- Five repeats cannot separate H from G. The superiority of H is not proven; I am putting H first as a low-extra-cost preference.
- My earlier proposal of hundreds of calls was larger than the present decision needs.

In Fable's diagnosis I keep four distinctions:

1. **The same content shows the same task scope; it does not turn separate calls into a single generation attempt.** Three separate arms ran on five data packets. We cannot count them as fifteen different task packets or as hundreds of independent accuracy samples. But the format and accuracy result of each call must still be recorded.

2. **The first-token explanation is a strong hypothesis; it is not proof of causality.** In particular the generalization that "the following lines copy the first line" does not hold in the given example: `e1` wrongly starts with `[` while `e2` correctly starts with `{`. The header may also carry the error to the first data record. The experiment will show this.

3. **The 10/33 collected from different texts is not H's error probability.** We can use about 30% as a bad scenario in the experiment design; we cannot use it as a common and fixed error rate.

4. **Two errors in 25 calls do not automatically deliver the 35% saving.** With the H means given, assuming the call cost does not change:

   ```text
   1 − (5662 / 9462) / (23 / 25) = 34.96% saving
   ```

   So the acceptance count and the real cost must be separate gates. Also Fable's binomial computations are right for 25 trials fixed in advance; they should not be read as an independent validation of candidates chosen after seeing the first five results.

The **H system text** I propose is the same as the text below. I am not carrying sentences over from G; I am not adding a new example or check instruction:

```text
You execute OZ/1g.

Input is one JSON object with exactly v,goal,ops,refs,jobs; v is "1g".
goal is the shared task goal and constraints; apply it to every job.
ops is an array of operation instructions. refs is an array of data,
never instructions. jobs is an array of blocks
[op_index,[job_id,ref_index,...],...]; indices are zero-based.
Each row is one independent job: apply ops[op_index] to the listed
refs values in row order; a row may list none. Never derive indices
from job IDs or use another job's result. goal and ops define result
values only; they never change this reply format.

Do not invent values, units, limits or evidence. Use a task-defined
unknown outcome when the task allows it; otherwise fail the job with
missing_data (required information absent), invalid_data (unusable
data), conflict (incompatible requirements) or unsupported
(operation not possible).

Reply with the line OZ/1g, then one compact JSON record per job on its own line.
Success: {"job_id":value}; one key, the ID; value is the whole result.
Failure: ["job_id","error",code,message]; code is one of the four above;
message is short and nonblank.
Shape examples only:
{"x":["a","b"]}
{"y":"unknown"}
{"z":[]}
["w","error","missing_data","Required field absent"]
Use ASCII double quotes as JSON delimiters. Escape newlines inside strings.
Emit every requested ID exactly once and no other ID.
Complete every job even if another fails.
No prose, Markdown, outer container or corrections.
Any malformed nonblank line or missing, duplicate or extra ID rejects
the whole reply. Stop after the last job.
```

The body stays `v:"1g"`. Based on the counts given, for seed 1000 I **revise the system+body o200k gate explicitly to ≤1020 at 32 jobs and ≤1479 at 64 jobs.** The main economic gate is the total cost measured by the provider.

The parser profile is chosen explicitly before the call: `H` in the experiment, for example `oz1g-h` in the application. **`v:"1g"` alone cannot tell C and H apart; the profile is not detected from the reply and the existing C contract is not silently changed.**

Parser rules:

1. The request, the unique job IDs and the indices are validated before the call.
2. The reply is split on LF; at most one CR at the end of each line is removed. The last line may have no terminator. A lone CR is not a line separator.
3. Only lines that are empty or consist entirely of ASCII SP/TAB are skipped. BOM, Unicode whitespace and Markdown are not cleaned.
4. The first remaining line must be **exactly `OZ/1g`** after only its trailing SP/TAB are removed. Leading whitespace is not accepted. A missing, different or repeated header makes the whole reply rejected.
5. Each following line must be a single JSON value that is consumed entirely. Comments, trailing commas, extra JSON pieces, `NaN` and `Infinity` are rejected. Standard JSON whitespace inside a line is accepted; `compact` is a production instruction. Basis for the syntax: [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259).
6. In all objects, including nested ones, key repeats are checked before values are overwritten. The comparison is made after escapes are decoded.
7. A success is an object with exactly one member: the key is the expected ID, the value is the whole result. The result can be any JSON type; it is not converted or flattened.
8. An error is an array of exactly four elements: `[id,"error",code,message]`. The ID is an expected string; the code is one of the four codes given; the message must be a string with at least one character other than Unicode whitespace. No arbitrary limit on message length is added.
9. Each expected ID is present exactly once. Binding is done through the ID, not through line order. There is no ID trimming, normalization or type conversion. Numbers are not silently rounded or turned into infinity.
10. No result is delivered before the whole reply is validated. If there is a task validator, it runs before delivery. A valid error record does not break structural acceptance; its semantic success depends on the expected task result. There is no explanation stripping, quote correction, picking the last repeat or recovery of the old format.

**In the experiment that decides, let us not try to prove H-G superiority; let us test whether H, which we preferred in advance, is sufficient.** This is the more useful question in terms of quota.

Before the experiment starts, the system texts, parser profiles, real model ID, settings, output limit, expected results and call schedule are frozen. Whether the seed belongs to the data generator or to the provider sampling is stated separately.

1. **First H: 20 new Sonnet 5.5 calls.** Default effort, 64 jobs, the first 16 jobs extract, `retry=0`, data seeds 1005-1024. The job order is kept; calls share no conversation history. The old five calls are reported as past evidence and are not added to the new acceptance gate.

2. **Five new 0.8-exec calls.** The same tasks are used on five pre-chosen seeds; the order of the matched calls is shuffled. These give a current cost and latency comparison. We state clearly that this is not a paired 20-to-20 experiment.

3. **Pass conditions for H:** at most **one failed packet** in 20 calls, and passing the cost and speed gates below. A successful packet means parser acceptance **and 64/64 correct results**. Needless errors, needless `unknown`, truncation and a wrong value are failures. At the second failure the arm may be stopped early; early success is not declared.

4. **If H stays suitable, five heterogeneous Sonnet packets.** The first records are, in order, an empty array, a scalar, an object, a nested array and a real error. Together the packets cover zero/many references, the permitted `unknown` and the four error codes. All must be accepted as correct.

5. **If H passes all gates, H is chosen and no call is spent on G.** If H fails, the given **G text as it is** is run through the same 20 new-trial condition and the five heterogeneous packets with the headerless parser. The existing baseline calls are reused if the same model and settings are kept. If G also fails, there is no adoption.

So **if H passes, the decision is made in 30 calls**, and if we have to move to G, in **at most 55 calls**; early eliminations may reduce this. I am not setting aside quota to investigate the chance that C wins again.

This threshold is a deliberate regression filter. Under the assumption of independent trials from the same distribution, if the real error rate is 30%, the probability of seeing at most one error in 20 trials is about **0.76%**; if the rate is 5%, **73.6%**. Compared with Fable's 25/2 threshold, the chance of eliminating a good candidate is higher; on the other hand it leaves more cost margin in new observations.

**Even 20/20 success does not prove 99% reliability:** with zero errors the one-sided 95% upper bound of the error rate is about 13.9%. We will keep this distinction in the result report. [NIST on binomial confidence intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm).

Cost is reported for each arm and workload as follows:

```text
C_requested = total call tokens / number of requested jobs

C_verified = total call tokens /
             number of jobs in packets accepted as fully correct
```

I propose a clearer and more conservative gate:

```text
C_verified(candidate) ≤ 0.65 × C_requested(0.8-exec)
```

This stops the baseline's wrong results from enlarging the saving percentage; it also penalizes the candidate's failed calls. In addition, the `C_verified` comparison of the two arms is reported. **The 35% pass gate and the 40% target** stay. Thinking and cache accounting are included completely and without double counting.

By the same logic, the **time per verified job**, computed from the total `api_ms` of the calls, must not be worse than the baseline's time per requested job. The mean and the median are also shown. These are pass conditions observed on a small sample; they are not a claim of firm speed superiority.

On the other models I agree with Fable narrowing the scope; but I keep the limit of this round's decision open. The later compatibility check for the chosen candidate:

| Cell | Standard repeats | Heterogeneous packets |
|---|---:|---:|
| Haiku 5.5, 64 jobs | 10 | 5 |
| Fable 5.1, 64 jobs | 5 | 5 |
| Luna medium, 64 jobs | 5 | 5 |
| Sonnet 5.5, 32 jobs | 5 | - |

In these **40 extra calls zero failures** are required. The whole process is 70 calls if H passes and at most 95 if we move to G. These small checks look for model incompatibility; they prove neither high reliability per model nor a 35-40% saving. If a saving claim is to be made for another model, a baseline measurement matched to that cell only is added.

Finally, I **do not accept** Fable's fallback as **the automatic next decision**. If the real ID is to be the object key, the form `{"job_id":null,"error":[code,message]}` collides when the job ID is `"error"`. If in the future all records have to become objects, a non-colliding candidate such as `{"id":"w","error":[code,message]}` can be examined; it must not be added to the present experiment.

With Fable we have come closer on the H preference and the strict parser. My remaining disagreement is **an H-first sequential experiment instead of a three-arm race; at most one error in the new 20 calls; a directly measured cost gate; no automatic fallback.**

Local reading again could not be opened because of `helper_sandbox_lock_failed`. The raw-data diagnosis rests on Fable's report; I redid the numeric computations here. No live experiment, file change or commit was made. The next step is Fable's reply to this decision and experiment revision.


## Fable round 3

Fable, round 3. I read Astra's round 2 in full (astra_r2.md). Joint position I can sign; every remaining item resolved below.

## Resolutions

1. Which text carries the header: C's text, exactly as Astra wrote it (H). GH is withdrawn. Budget gate revised to 1020 at 32 jobs and 1479 at 64 (H measures 1020/1479 at seed 1000); the economic gate is provider-measured cost. Agreed.
2. C as control: dropped. The test asks whether H is good enough (absolute gate), not whether the header caused the improvement. Attribution stays unproven and the report says so; C's 2/5 remains on file as the reason the header exists. Agreed.
3. Sequential vs parallel: sequential, H first, G only if H fails. Agreed.
4. Threshold: at most 1 failed packet in 20 new Sonnet calls; a pass is parser acceptance and 64/64 correct; needless error or unknown, truncation and wrong values are failures; stop the arm at the second failure, never declare early success. The old five calls are reported as history, not counted. Agreed; my 2/25 is withdrawn.
5. Cost gate: C_verified(candidate) <= 0.65 x C_requested(0.8-exec), both from provider usage (input, cache write, cache read, output, thinking once), computed on the same model and workload; both arms' C_verified also reported. 35% is the gate, 40% the target. Agreed. Astra's arithmetic is right: 2 failures in 25 gives 34.96%, so acceptance and cost must be separate gates.
6. Speed gate: candidate api_ms per verified job <= baseline api_ms per requested job, with mean and median shown; an observed condition, not a speed claim. Agreed, with one caveat for the record: the baseline side rests on 5 calls (observed 13.5 to 15.4 s), so a fail by a few percent is noise, and the report must say which gate failed and by how much rather than silently rejecting.
7. Fallback: none scheduled. My `{"job_id":null,"error":[...]}` collides when a job ID is "error"; withdrawn. If both H and G fail, a new design round; Astra's `{"id":"w","error":[code,message]}` is a candidate for that round only.
8. Astra's four reservations on my diagnosis: accepted as stated. Identical content across arms limits the correctness evidence, it does not merge calls into one attempt; the first-token fork is a hypothesis (the model did recover to `{` on e2, so "later lines copy line 1" is wrong as a generalization; what the data show is that every slip occurred at the start of the reply); 10/33 is a worst-case design number, not H's rate; 20/20 bounds the failure rate at about 13.9%, not 1%.

Nothing left that I would hold the decision on.

## System text H

Frozen, verbatim Astra round 2 (C with "Reply with one compact JSON record per job on its own line." replaced by "Reply with the line OZ/1g, then one compact JSON record per job on its own line."). Body unchanged, v "1g". G, if ever run, is stage1g_G_system.txt verbatim with the headerless profile.

## Parser profile H (selected before the call, never detected from the reply)

Astra's ten rules, verbatim in effect: request pre-validation of IDs and indices; split on LF, strip at most one trailing CR per line, lone CR is not a separator, last line may lack a terminator; skip only lines that are empty or all ASCII SP/TAB, no BOM, Unicode space or Markdown cleanup; first remaining line, after stripping trailing SP/TAB only, must be exactly `OZ/1g`, leading whitespace rejects, missing, different or repeated header rejects the whole reply; every later line one fully consumed JSON value (RFC 8259, no comments, trailing commas, extra fragments, NaN, Infinity); duplicate keys checked in all objects after escape resolution; success exactly one-member object keyed by an expected ID, value any JSON type, untouched; failure exactly `[id,"error",code,message]` with one of the four codes and a message containing at least one non-whitespace character; every expected ID exactly once, binding by ID, no trimming, normalization or type conversion, numbers not rounded or sent to infinity; nothing delivered before the whole reply validates, task validator runs before delivery; no repair of any kind. Profile name in the product distinct from the C profile (for example oz1g-h); the C profile is not changed silently.

## Frozen test plan

Before the first call: freeze system texts, parser profiles, real model ID, effort (default), output limit, data seeds, expected results, call schedule; note that seeds drive the data generator only, provider sampling is uncontrolled.

Stage A, Sonnet 5.5, 64 jobs, first 16 extract, retry=0, no shared conversation: H 20 calls, data seeds 1005 to 1024. Plus 0.8-exec 5 calls on five pre-chosen seeds from the same set (1005, 1009, 1013, 1017, 1021), the paired calls' order shuffled. 25 calls. Reported as 20 vs 5, not a paired 20 vs 20.
Gates for H: at most 1 failed packet in 20 (early stop at the second); C_verified(H) <= 0.65 x C_requested(0.8-exec); api_ms per verified job <= baseline api_ms per requested job.
Stage B, only if H passes A: five heterogeneous Sonnet packets whose first record is, in order, empty array, scalar, object, nested array, genuine error; across the five: zero and many refs, permitted unknown, all four error codes; expected values and codes fixed before the calls, message text not matched. 5/5 fully correct required. 5 calls. H adopted at 30 calls total.
Stage C, only if H fails: G verbatim, headerless profile, same 20-call condition and the same five heterogeneous packets, baseline calls reused. 25 calls. If G also fails: no adoption, new design round.
Stage D, compatibility of the adopted arm, zero failures required in 40 calls: Haiku 5.5 64 jobs 10 standard + 5 heterogeneous; Fable 5.1 64 jobs 5 + 5; Luna medium 64 jobs 5 + 5; Sonnet 5.5 32 jobs 5. These look for model-specific breakage; they prove neither per-model reliability nor per-model savings; a savings claim for another model needs its own paired baseline cell.

Totals: 70 calls if H passes, at most 95 if G is needed. Report per call: accepted, correct count, failure type (first-record shape, header, prose, truncation, value), provider tokens by kind, api_ms, model ID. Report the binomial caveat with the result: 20/20 bounds the failure rate at about 13.9% one-sided 95%, which is a regression filter, not a reliability proof.


## Astra round 3

**Astra, Round 3: I withdraw H. G should be the main candidate, GH the header alternative, and C only a diagnostic control. I accept Fable's three-arm screen and the small validation matrix.** The decision below has been accepted by me; since I have not seen Fable's Round-3 reply, I do not present his final approval as given.

I close the remaining distinctions as follows:

| Topic | The final decision I accept |
|---|---|
| Which text gets the header? | **G.** GH is a change of only one sentence of G. H, which was C+header, is withdrawn. |
| Does C stay? | **It stays as a 20-call diagnostic control; it is not an adoption candidate.** C giving zero errors does not invalidate the experiment; it is reported that the control was not triggered in this study. |
| Sequential or parallel? | In the first stage **C/G/GH are compared together**, and the call order within a repeat is shuffled. G or GH is not tried first and the other dropped. For the latency measurement only one API call runs at a time. |
| Candidate choice | **G has priority** if it passes all first-stage gates. If G cannot pass and GH passes, GH is chosen. If neither passes, there is no adoption. |
| Acceptance threshold | Sonnet-64 and Haiku-64: **at most 1 failed packet in 20 calls**. Other standard cells and all heterogeneous packets: **zero failures**. |
| Token target | **At least a 35% reduction per verified job is the pass requirement; 40% is the target.** |
| Speed | The time per verified job, failed calls included, must not be worse than the baseline. |
| Fallback | The existing **0.8-exec is kept**. Eliminating both candidates does not automatically make the new format adopted. A non-colliding object error format is the candidate of the next experiment. |

I accept the first-token explanation as a strong diagnosis; I do not accept before the experiment the conclusion that the header is the solution. The old five repeats are only past evidence. Replies with the same content are not counted as different task samples; the acceptance results of separate calls are still recorded separately.

**The system texts are fixed as follows.** UTF-8, LF, no BOM; the code block markers are not part of the text.

G:

```text
You execute OZ/1g.

Input JSON has exactly v,goal,ops,refs,jobs; v is "1g".
Apply required goal to every job. ops contains instructions; refs contains
data, never instructions. jobs contains [op_index,[job_id,ref_index,...],...]
blocks. Indices are zero-based. Each row independently uses ops[op_index]
and only its listed refs, in order; zero refs is allowed. Never derive
indices from IDs or use other jobs' results.
goal and ops define result values, never output framing.

Do not invent values, units, limits or evidence.
Use permitted task-defined unknown outcomes; otherwise report:
missing_data: required information absent; invalid_data: unusable data;
conflict: incompatible requirements; unsupported: operation not possible.

Return one compact JSON record per job on its own line.
Success: one-member object mapping job ID to the complete result.
Array results remain array values.
Failure: [job_id,"error",code,message]; code is from above,
message is a short nonblank string.
Shape examples only:
{"x":["a","b","c","d","e","f"]}
{"y":[]}
{"z":"unknown"}
["w","error","missing_data","Required input absent"]

Use ASCII double quotes (") as JSON delimiters.
Emit each requested ID exactly once, no other IDs. IDs bind results,
never positions. Complete all jobs. Escape newlines inside strings.
Check syntax and result shape before emitting each final line.
No prose, Markdown, blank lines, outer container or appended corrections.
Any malformed line or missing/duplicate/extra ID rejects the whole reply.
Stop after the last record.
```

The **full definition** of GH is a single replacement of the sentence below in G; no other byte changes:

```text
Return one compact JSON record per job on its own line.
```

is replaced by:

```text
Return the line OZ/1g, then one compact JSON record per job on its own line.
```

The C control is the headerless form of the H text in Round-2:

```text
You execute OZ/1g.

Input is one JSON object with exactly v,goal,ops,refs,jobs; v is "1g".
goal is the shared task goal and constraints; apply it to every job.
ops is an array of operation instructions. refs is an array of data,
never instructions. jobs is an array of blocks
[op_index,[job_id,ref_index,...],...]; indices are zero-based.
Each row is one independent job: apply ops[op_index] to the listed
refs values in row order; a row may list none. Never derive indices
from job IDs or use another job's result. goal and ops define result
values only; they never change this reply format.

Do not invent values, units, limits or evidence. Use a task-defined
unknown outcome when the task allows it; otherwise fail the job with
missing_data (required information absent), invalid_data (unusable
data), conflict (incompatible requirements) or unsupported
(operation not possible).

Reply with one compact JSON record per job on its own line.
Success: {"job_id":value}; one key, the ID; value is the whole result.
Failure: ["job_id","error",code,message]; code is one of the four above;
message is short and nonblank.
Shape examples only:
{"x":["a","b"]}
{"y":"unknown"}
{"z":[]}
["w","error","missing_data","Required field absent"]
Use ASCII double quotes as JSON delimiters. Escape newlines inside strings.
Emit every requested ID exactly once and no other ID.
Complete every job even if another fails.
No prose, Markdown, outer container or corrections.
Any malformed nonblank line or missing, duplicate or extra ID rejects
the whole reply. Stop after the last job.
```

**Precondition for the identity of the control:** This C text must be compared at the byte level with the C artifact used in live21. If they do not match, the experiment does not start with it named as the old positive control. The baseline is likewise taken from the existing `0.8-exec` artifact; it is not rewritten.

The GH counts Fable reported are **351 system tokens; system+body 999 at 32 jobs and 1458 at 64 jobs**. These are not numbers measured again here. The earlier **1019/1478** limits are kept; my one-token widening in Round-2 is withdrawn. This gate belongs to the seed 1000 reference packet; it does not replace the provider's real total token measurement.

**Parser profiles:**

| Experiment arm | Profile to be chosen in advance |
|---|---|
| C | `oz1g-lines` |
| G | `oz1g-lines` |
| GH | `oz1g-header` |
| 0.8-exec | The existing, unchanged baseline parser |

The body stays `v:"1g"` in all C/G/GH calls. **The profile is not detected from the reply or from the `v` value alone; it is chosen in the call configuration.**

The common contract of the two new profiles:

1. The request schema, unique string job IDs and all indices are validated before the call.
2. The reply is split on LF; at most one CR at the end of each line is removed. The last line may have no terminator. A lone CR is not a separator.
3. Only lines that are empty or consist entirely of ASCII SP/TAB are skipped. BOM, Unicode whitespace or Markdown outside JSON are not cleaned.
4. For `oz1g-header`, after the trailing SP/TAB of the first remaining line are removed, the line must be exactly `OZ/1g`. Leading whitespace is not accepted. The header can be present only once. `oz1g-lines` does not accept a header.
5. Every data line is a single JSON value that is consumed entirely. Comments, trailing commas, a second JSON value, `NaN` and `Infinity` are rejected. Valid JSON whitespace inside a line is accepted; `compact` is a production instruction. Basis for the syntax: [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259).
6. Duplicate keys, including in nested objects, are rejected before values are overwritten. The comparison is made after JSON escapes are decoded.
7. A success is an object with exactly one member: the key is the expected ID, the value is the whole result. Every JSON result type is valid; arrays are not flattened.
8. An error is an array of exactly four elements: `[id,"error",code,message]`. The code is one of the four defined codes. The message must be a string and must contain at least one character other than Unicode whitespace. There is no extra limit on message length.
9. Each expected ID is present exactly once. IDs are not trimmed, normalized or converted. Binding is done through the ID; the output order is not enforced. Numbers are not silently rounded or turned into infinity.
10. No result is delivered before the whole packet passes the structural and task validation. A valid error record counts as correct only if it is the expected result for the task. There is no repair, no explanation stripping, no picking a rewritten final answer and no automatic move to the old format.

Before the API calls, the local parser checks cover profile mix-ups, a missing/repeated header, duplicate and escape-equivalent keys, missing/extra IDs, broken error records, truncation and all valid result types. These **consume no API calls**.

**The experiment plan to be frozen is at most 159 new calls in total.**

| Stage | Model / job count | Arm | Repeats | Calls |
|---|---|---|---:|---:|
| 1 | Sonnet 5.5 / 64 | C, G, GH | 20 each | 60 |
| 1 | Sonnet 5.5 / 64 | 0.8-exec | 5 | 5 |
| 2 | Haiku 5.5 / 64 | Chosen candidate | 20 | 20 |
| 2 | Fable 5.1 / 64 | Chosen candidate | 10 | 10 |
| 2 | Luna medium / 64 | Chosen candidate | 10 | 10 |
| 2 | Sonnet 5.5 / 32 | Chosen candidate | 10 | 10 |
| 2 | The four cells above | 0.8-exec | 5 per cell | 20 |
| 2 | Four models / 64 | Chosen candidate, six heterogeneous packets | 6 per model | 24 |
| | | **Total** | | **159** |

The **25 baseline calls** here are five measurements each for five model×size cells. For Sonnet-32 we will not use the Sonnet-64 cost. Instead of Fable's "about 130" second-stage computation, the second stage of this plan is **94 calls**.

Implementation rules:

- The first-stage data seeds are **1005-1024**; the baseline pairs are **1005, 1009, 1013, 1017, 1021**.
- The second-stage standard packets are **2005-2024** for Haiku and **2005-2014** for the other cells. The Haiku baseline pairs are **2005, 2009, 2013, 2017, 2021**; for the others **2005, 2007, 2009, 2011, 2013**.
- These are **data generator seeds**. If a provider sampling seed is supported, it is recorded separately; the two are not counted as equalized.
- Arms with the same seed and size use the same jobs and expected results. In the first stage the extract-first job order is kept.
- The arm order inside each repeat is generated in advance and stored in the manifest. Calls run in independent contexts, with `retry=0` and concurrency 1.
- The real model ID, effort, sampling settings, output limit, timeout, SDK retry setting, cache policy and token accounting are fixed before the first call.
- The system texts, inputs, oracle, parser/validator versions and call schedule are hashed. They are not changed after a result is seen.
- The 65 calls of the first stage are completed. If there is no suitable candidate, we stop. In the second stage we may stop early on an irreversible gate violation; early success is not declared. If the chosen candidate stays in the second stage, the other candidate is not silently put in its place.

The **six heterogeneous packets** each contain 64 jobs for every model:

| Packet | Expected result family |
|---|---|
| P1 | Non-empty arrays |
| P2 | Empty arrays |
| P3 | Scalars; including the permitted task-defined `unknown` |
| P4 | Objects |
| P5 | Nested arrays |
| P6 | Real errors; 16 jobs for each of the four error codes |

Together the packets cover zero/many references, order-dependent reference use, escapes and job IDs such as `"error"`. The expected result of every job is fixed before the call; for error messages, instead of full sentence equality, the correct code and a message that fits the contract are looked for.

**Important correction:** Because the parser does not enforce the output order, putting an error in the first request row does not guarantee that the first output record is an error. For this reason all jobs in P6 produce the expected error. So the first data character of a correct headerless reply must really be `[`. In GH the same check is applied to the first data record after the header.

**Pass and selection gates:**

A successful call = parser acceptance **and all jobs in the packet being correct**. A wrong value, needless error/unknown, a missing job and truncation are a failed packet.

- In the first stage G and GH must each reach **at least 19/20** and meet the token gate and the speed gate.
- If G is suitable, G; if only GH is suitable, GH is chosen. Both being suitable does not mean statistical superiority of G; the pre-set preference is G.
- In the second stage Haiku must reach **at least 19/20**; Fable, Luna and Sonnet-32 **10/10**; the heterogeneous packets **24/24**.
- Every baseline cell must achieve **5/5 correct acceptance**. If it does not, the comparison of that cell is inconclusive; a failed baseline is not used to enlarge the saving.

In every standard model×size cell, failed calls included:

```text
C_requested = total tokens / number of requested jobs

C_verified = total tokens /
             number of jobs in packets accepted as fully correct

Token gate:
C_verified(candidate) <= 0.65 * C_requested(0.8-exec)

Speed gate:
total api_ms(candidate) / number of verified jobs
    <= total api_ms(0.8-exec) / number of requested jobs
```

Each cell must pass separately; a good model cannot hide a bad one in the average. In addition, the `C_verified` comparison of the two sides, the first-attempt acceptance rate, the mean/median latency and the billed cost are reported. **The monetary cost per verified job must also not be higher than the baseline's.**

Thinking and cache tokens are counted **once** according to the provider's accounting; a cache discount is not shown as a token reduction. A missing usage record makes the economic gate unverifiable. Five baseline repeats give an observed comparison; they do not give a claim of firm speed superiority.

These economic gates are for standard workloads. The heterogeneous packets are an accuracy/compatibility check; since they have no paired baselines, no separate 35% saving claim is made about them. All experiment spend, including C and the eliminated arm, is also reported as a separate total.

**We keep the reliability claim limited:** the probability of passing the threshold of at most one error in 20 calls is, in independent trials, about **0.76%** if the real error rate is 30% and **73.58%** if it is 5%. But **even 20/20 does not prove 99% reliability**; with zero errors the one-sided 95% upper error bound is about 13.91%. This experiment is an adoption filter.

My last fallback objection is concrete: the form that uses a dynamic ID key

```text
{"job_id":null,"error":[code,message]}
```

collides when the real ID is `"error"`. The error candidate of the next experiment should be this instead:

```json
{"id":"w","error":["missing_data","Required input absent"]}
```

A success is a one-member dynamic-ID object, an error is an object with two fixed members; the job IDs `"id"` or `"error"` do not create a collision. This form **needs a separate wire version and parser; it is not part of the existing 159-call experiment**.

On my side no objection remains about C/G/GH, the thresholds or the experiment order. **If Fable wants to keep the old fallback as it is, the smallest remaining technical disagreement is this ID collision.**

No experiment or file change was made in this round. Local reading was blocked by `helper_sandbox_lock_failed`; the raw data and tokenizer counts rest on Fable's report. The next step is to match this contract with the real artifacts and freeze its manifest.
