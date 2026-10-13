# Stage 1g repair-run failure: joint decision (Astra and Fable, 2026-10-13)

Translated from Turkish by Claude Sonnet 5.5; the original text is in git history (commit 5abbc82).

Evidence: stage-1g-R-evidence.txt. Zero-call check (Claude, Fable): the raw Haiku rev-2 lines are {"r_438":["u6","u4"]}, rev 1 {"r_438":[["u6","u4"]]}; the model dropped the outer array, the parser removed nothing.

## Frozen decision

- This round: no adoption, 0.8-exec stays; the remaining 14 calls were not run.
- Diagnosis both sign: no wire defect shown; op 5's wording allowed a flat reading; a wire or context effect is not excluded. Astra withdrew its 12-call 2x2 diagnostic (needs a new 0.8 builder, 0.8 carries values as strings, 3 calls per cell cannot attribute).
- Op authoring rule (language): state the result shape; where nesting or wrapping matters, give a literal example. Second shape audit (Fable): only P4 op 5 was ambiguous.
- P4 op 5, rev 3 (Astra's final call, text B): Return a JSON array of arrays containing exactly one inner array, [first ref's `id`, second ref's `id`]; for ids "u1" and "u2" the result is [["u1","u2"]]. Oracle unchanged; rev 3 differs from rev 2 only in this op (verified).
- Pre-registration: a parser rejection or wrong record shape is a contract failure; a wrong value on an op whose shape and data are stated literally is a correctness failure; either closes the round and is not reinterpreted afterwards; no parser tolerance, no auto-wrapping, no G.
- Haiku stays in the gate at default effort unless the owner decides otherwise before the hash.
- Next round, concurrency 1, retry 0, stop at first failure: Sonnet P4 rev 3 (1), Haiku P4 rev 3 three times, all must pass, no stop between them (3, Astra's final call), Fable P1-P3 and P4 rev 3 (4), Luna 5 std + 5 hetero from the regenerated kit (10). 18 calls. Inherited and labelled: Sonnet and Haiku P1-P3 rev 2 (identical to rev 3), all P5 cells, all standard cells, stage A economics. All pass: adopt H.

## Round 1, Fable (verbatim)

Fable, repair-run failure. Read the R evidence, compared Haiku's two P4 replies (live24 rev 1, live25 rev 2) job by job.

## Diagnosis

1. Same wire, same system text, same op 5 text, same refs, same model, two calls: rev 1 gave [["u6","u4"]] for all 10 op-5 jobs, rev 2 gave ["u6","u4"] for all 10. Both replies have the same output order, the same header, the same record shapes, and all 54 other jobs identical and correct. The only textual difference between the calls is op 1 (the alphabet fix), which Haiku answered correctly both times.
2. The record carried a legal two-element array as the whole value; nothing merged with the record container (the 1f flatten was [id,a,b,...]; here the object record is intact and the value lost one nesting level). A wire defect would show in the record, not inside the value.
3. All-or-nothing per op block: the model chose a reading of op 5 once, in thinking, and replicated it ten times. The op text invites that: "a JSON array holding exactly one pair, [first ref's `id`, second ref's `id`]" shows the inner pair in brackets, and a reader can take the bracket as the result template. Sonnet (twice), Fable and Haiku rev 1 read it nested; Haiku rev 2 read it flat.
4. So: op shape ambiguity times sampling, under 8k to 9k thinking tokens. Not wire. The existing two calls already separate wire from op: identical wire with two outcomes means the variance is in the reading of the op. A 0.8-exec control would not add separation: one call per wire is the same one-sample problem, a rate needs about 20 calls per wire, and whatever the rate, the op gets fixed anyway. Also 0.8-exec has no builder for these packets. No calls on that.

## What it means for the language

Nothing in the 1g wire or H text is implicated; the parser, header and record contract held in every call of A, B, D and R. What failed is the test's second audit class, which the first audit did not cover: result shape must be stated unambiguously, with a literal example where nesting matters. Spec consequence, an authoring rule for ops rather than a wire change: "state the result shape; where nesting or wrapping matters, give a literal example." Two observations for the owner, not gates: under default effort Haiku 5.5 spends 3k to 9k thinking tokens per 64-job packet here (P4: 10k output and 30 s, vs Sonnet 3.8k and 19 s), so Haiku is neither the cheap nor the stable model for this wire; and an all-or-nothing 64x5x4 correctness gate on hand-written ops measures op authoring as much as the wire, so every round will be exposed to one interpretive slip per op block. For this round the frozen rule stands: no adoption, 0.8-exec stays.

## Next step

Second audit, no calls: every op of P1 to P5 checked for shape ambiguity. I did it: only op 5 has the "array holding one pair" construction; op 1 and op 4 ("array of [x,y] pairs"), the P3 objects, the P1 string arrays, the P2 scalars and the P5 codes are explicit. Op 5 rev 3, expected unchanged [["u6","u4"]]:
"Return a JSON array of arrays containing exactly one inner array, [first ref's `id`, second ref's `id`]; for ids "u1" and "u2" the result is [["u1","u2"]]."
Astra and I approve the text, hash, then: P4 rev 3 on Sonnet, Haiku, Fable (3 calls); Fable P1 to P3 rev 2 (3 calls, never run); Luna 10 from a regenerated kit. 16 calls. Inherited and labelled: Sonnet and Haiku P1 to P3 rev 2, all P5 cells, all standard cells, stage A economics. Gates unchanged, stop at first failure, no G. All pass: adopt H.

Pre-registered for that round, so the next slip is not re-argued: a parser rejection or a wrong record shape is a wire failure; a wrong value on an op whose shape and data are stated literally is also a failure and is not reinterpreted. If the owner wants Haiku out of the adoption gate or run at a lower effort, that is a separate decision to take before the hash, not after a result.


## Round 1, Astra (verbatim)

**My decision: H is not adopted in this round; 0.8-exec stays. Extra call budget for this round: 0.** The remaining 14 calls are not run.

This is the error of **losing the nested array form in the output value**. The root cause has not been isolated yet:

- **Op 5 and the oracle are consistent:** the outer array that says "exactly one pair" requires `[[id1,id2]]`. Turning the expected value into a flat array would be wrong.
- **No general wire failure was shown:** the reply was accepted, the other 54 jobs and the other nested arrays are correct. But parser acceptance does not rule out an effect of H on the model's interpretation.
- **Pure model noise is not proven either:** the earlier successes show that the error was not unavoidable. Because the surrounding context changed with the revision, the earlier pass is not an exact repeat. The ten wrong jobs are not ten independent failures; **they are the same wrong interpretation spreading to ten jobs in a single call.**
- 8,422 thinking tokens point to an expensive failure; they do not explain the cause of the error.

**Next step: a separate, pre-frozen diagnostic experiment, without redesigning the language.**

First the chain raw reply → parser output → oracle must be checked with **0 model calls**. Did the model drop the outer array, or did the parser remove it? Is there a rule in the H text that conflicts with the op? If the parser removes it, the implementation bug is solved first and the model experiment below is not needed.

If the raw reply confirms the error, I propose a **ceiling of 12 Haiku calls**:

| Wire | Current op 5 | Explicit structural op 5 |
|---|---:|---:|
| 0.8-exec | 3 | 3 |
| H | 3 | 3 |

The only experimental op change:

> Return [[a,b]] as JSON, where a is the first ref's id and b is the second ref's id.

The full 64-job P4 is kept. The jobs, the order of refs, the IDs, the oracle, the goal and the model settings are kept equivalent; only the wire and the op wording change. Each cell gets three independent calls; the order is balanced. The earlier failed call is not part of these numbers.

This is a **new diagnostic experiment**, not a continuation of the failed adoption round. It does not stop on a wrong result to complete the comparison; it ends after the fixed 12 calls and no extra attempt is opened.

How to read the results:

- If the explicit op improves both wires: evidence for **fragility of the op wording**.
- If, under matched conditions, the problem is concentrated in H: evidence for a **wire/context effect**.
- If the effect of the op change varies with the wire: there is an **interaction**.
- If the results are mixed or the error does not repeat: the cause stays **uncertain**. Three repeats do not prove reliability.

For now I do not propose new language syntax, automatic outer-array insertion or parser tolerance. Correcting afterwards does not meet the goal of producing the correct result on the first attempt.

The **40.7% saving in Stage A stays a finding within its own scope**. For adoption, first-attempt accuracy, total `input + output` and latency must be measured together on the same verified job; the cost of failed calls must be included. Thinking is included in the output count that is given, so it must not be added again.

This is **my independent assessment, to be passed to Fable as it is**; a joint agreement has not formed yet. I could not read the local records because of the sandbox error; the decision rests on the evidence you shared.


## Round 2, Fable (summary of its signed position)

Agrees: no adoption, 0 calls this round; no implementation bug; skip the 2x2 (3 calls per cell cannot attribute; no 0.8 builder; 0.8 stringifies values; both outcomes lead to fixing op 5); op 5 text A with the field marked; pre-registration as above; Haiku stays unless the owner decides before the hash; 18 calls with Haiku P4 three times.

## Round 2, Astra (verbatim)

**I accept Fable's repair plan: 0 calls in this evaluation; at most 16 calls in the new, frozen round.** H is not adopted yet; 0.8-exec stays.

- **Diagnosis:** The model dropped the outer array; the parser did not remove it. The wording of op 5 is a reasonable explanation, but getting two different results on the same wire does not rule out a wire/context effect. We can agree on "no wire defect was shown".
- **Experiment:** I withdraw the 12-call diagnostic experiment I proposed. It is not worth it at this stage because it needs a new 0.8 builder and an equivalence audit, because of the limits of a small sample, and because op 5 is being fixed anyway.
- **Op 5:** I approve Fable's text with the literal example as it is:

> Return a JSON array of arrays containing exactly one inner array, [first ref's `id`, second ref's `id`]; for ids "u1" and "u2" the result is [["u1","u2"]].

The oracle does not change. The op writing rule of the language: **State the result shape explicitly; if nesting or wrapping matters, give a literal example.**

- **Pre-registration:** A parser rejection or a wrong record shape is a contract failure; a wrong value in an op whose shape and data are stated explicitly is an accuracy failure. Both close the round; a failure is not erased after the result by saying "it was ambiguous". These alone are not a causal diagnosis.
- **Haiku:** It stays in the adoption gate with the current/default effort. Removing it or changing the effort requires **the owner's explicit decision before the hash**. The 3k-9k thinking cost is reported; the earlier economy finding is not generalized to Haiku.

**The exact next step:** Claude should record Fable's second shape audit; update op 5, renew the Luna kit, and hash the texts/oracle/settings and the inherited cells with labels. Then, in order:

1. P4 rev 3: Sonnet, Haiku, Fable, **3 calls**
2. Fable P1-P3 rev 2, **3 calls**
3. Luna renewed kit, **10 calls**

The gates do not change; stop at the first failure, no G. If all pass, H is adopted.

The decision rests on the shared evidence; local file reading was blocked by the sandbox error.


## Final call, Astra

op5: B
haiku_p4: 3
