# Stage 1g release scope (Astra and Fable, 2026-10-13)

The universal 1g qualification failed at its last cell (Luna medium on the Codex CLI, 1/10; stage-1g-luna-evidence.txt). After it, Astra and Fable agreed on a separately declared, Claude-only release of text H. This scope was chosen after the broader qualification failed, and is published as such.

## Qualified configurations (text H, parser profile oz1g-header)

| Model id (claude -p, pinned) | Effort | Jobs per call | Evidence |
|---|---|---|---|
| claude-sonnet-5-5 | default | 64 | Stage A 20/20 with paired 0.8-exec baseline (40.7% fewer tokens per verified job); heterogeneous P1-P5 |
| claude-sonnet-5-5 | default | 32 | 5/5 |
| claude-haiku-5-5 | default | 64 | 10/10 standard; heterogeneous P1-P3, P5, and P4 rev 3 three times |
| claude-fable-5-1 | default | 64 | 5/5 standard; heterogeneous P1-P4 rev 3 and P5 |

Economics were measured on Sonnet at 64 jobs only; the other cells are regression filters (5 to 15 calls). Other models and configurations stay on the 0.8 release (tag oz-0.8.0-full). There is no runtime model detection or fallback.

## Not qualified

gpt-6-luna at effort medium through the Codex CLI: 1/10, with three failure classes (wrong op or ref bound by index, success records in the array shape after an error record, a record split over two lines). The Codex CLI also adds about 24,500 fixed input tokens per call, so no wire reaches the token target on that path.

## Design notes for future experiments (not part of this release)

- A uniform object error record, {"id":"w","error":[code,message]}, removes the mixed-shape hazard.
- Inline inputs, as in stage 1d (all correct on Luna medium), are the next Codex candidate.
- Optional, non-blocking: Luna at effort high on the rev-3 kit, preregistered, 10 calls, gate 10/10, owner's Codex quota. A pass would support a separate qualification for that exact configuration only.

## Fable (verbatim)

Fable, Luna cell. Read the evidence file, the raw Codex replies and the earlier Codex kits.

## What the Luna replies show

1. Three classes of failure, none seen on any Claude cell. (a) Index drift: wrong op or wrong ref bound (het_p3 op 0 answered with op 1's value, wrong second city on 7 jobs, "Second ref index is out of range" on a valid index, "error"-ID job failed for a ref it never had). Same signature as Luna's stage 1c drift that 1d's inline inputs fixed. (b) The `[` fork mid-reply: in het_p1 the two legitimate error records (array shape) are immediately followed by success records in array shape, ["k247",[]] and on, for the rest of the packet. That is the same fork as the C screen, now triggered inside the reply by the failure record's opener rather than at the thinking boundary. (c) Record split over two lines ({"m6":[] then }) in std_2005 and std_2006, a compactness slip. The parser rejected (b) and (c) correctly and accepted the rest.
2. Luna at effort medium ran with 0 reasoning tokens on 7 of 10 calls (the Codex usage field), versus 700 to 9000 thinking tokens on every Claude call. Indexed addressing (ops[i], refs[j]) is resolved in working memory; without reasoning a weaker model drifts. Luna high in the old kit did reason (94 to 516 tokens).
3. Economics make the Codex question moot regardless of wire: the Codex CLI adds about 24.5k fixed input tokens per call, so the 1g body (1.5k) against 0.8's (3.3k) moves a Codex call by about 7%. The 35 to 40% target is unreachable on the Codex CLI path with any wire; it was always an API-path (Claude) target. Luna on 0.8-exec is 4/4 in live6 and ran clean in the old kit.

## What it means for the language

The 1g wire is verified for the models that reason: every Claude cell of the frozen plan passed with the rev 3 instrument (A 20/20 with 40.7% on Sonnet-64, B 5/5, D Haiku 10 std + P1 to P3 + P4 x3, Fable 5 + 5, Sonnet-32 5). Two design facts are now on record for future work, not for change before publishing: the mixed record shape (object success, array failure) is a fork hazard for weaker models, and Astra's uniform alternative {"id":"w","error":[code,message]} would remove it; and index addressing needs a reasoning model, while 1d-style inline inputs did not.

## Adoption

Frozen rule respected: H is not adopted as the universal wire; the Luna cell failed 1/10 and is not reinterpreted. New, scoped decision for Astra to rule on: adopt H as the profile for Claude models (Sonnet 5.5, Haiku 5.5, Fable 5.1), selected by model in configuration, never detected; Codex models stay on 0.8-exec, their verified profile; an unlisted model gets 0.8-exec. Evidence needed: none beyond what the frozen plan already produced for the Claude cells, which were run as specified and passed. Caveats stated in the evidence file: the Haiku and Fable cells are regression filters (5 to 15 calls each), the economics are measured on Sonnet-64 only, and Luna's 1/10 is published with the three failure classes.

## Next step and budget

Claude calls: 0. Publish with the model-to-profile map, the Luna evidence and the two design notes. Optional, owner's Codex quota only, before or after publishing: Luna at effort high on the rev 3 kit, 10 calls, gate 10/10, which separates "no reasoning" from "wire unsuited to Codex"; a pass would qualify a Codex H profile, a fail leaves Codex on 0.8-exec and makes the inline-input profile the Codex design task for a later round. I would publish now, Claude only, and not block on it.


## Astra, round 1 (verbatim)

**Keep the failed qualification closed. Pursue a separately declared Claude-only H release; spend no more calls on Luna before publication.** This is my independent ruling; Fable’s response was not included, so agreement is not yet established.

1. **What Luna’s result means**

There are **two wire-failure types across three rejected replies**, plus **six parser-accepted replies with incorrect results**. Fixing line formatting alone cannot rescue this configuration.

The cross-op answer substitution and wrong-ref outputs strongly support an index-binding problem. However, interval checks, empty-array handling, and error classification are not conclusively explained by index drift. The rev-2 P4 wording ambiguity is another distinct issue. It remains a failure under the frozen gate; diagnosing ambiguity does not restore credit.

The 1d inline-input success makes inline inputs the strongest candidate for a future Luna profile. It does **not** prove causation or qualify a new combination of inline inputs and H output without testing.

The language consequence is narrow: **shared indexed inputs are not qualified for Luna medium through this Codex CLI setup.** That is neither evidence of an inherently defective JSON wire contract nor grounds to reject every Codex model. Retain strict parsing and the explicit-result-shape authoring rule.

2. **Whether Claude can adopt H**

**Yes—as an explicitly scoped release decision, not a retroactive pass of the failed universal gate.** The owner’s earlier Claude-only fallback authorizes that direction.

Keep the original failure report and global `0.8-exec` default. Enable H only for the exact qualified Claude configurations, selected before execution. Other configurations retain their existing baseline; this Luna result does not establish that their baseline passes these workloads.

Required evidence:

- Exact model versions, effort settings, harness/context, batch size, prompt hashes, parser/scorer versions, raw replies, and scores.
- Complete Claude coverage, with every required call accepted and every expected result correct.
- Verified rev-3 P4 coverage; inheritance only for demonstrably unchanged inputs and evaluation conditions.
- Clear disclosure that Claude-only support was selected after the broader qualification failed.

No tolerant parser, auto-wrapping, hidden retries, or automatic fallback may turn a failed first attempt into a qualification pass.

Stage A supports **Sonnet economics only**. Claude correctness results do not establish Haiku/Fable savings, and Luna’s large fixed CLI overhead prevents treating its total input tokens as a clean measure of language efficiency.

3. **Next step and call budget**

**Immediate budget: 0 new model calls.** Audit the existing Claude artifacts against the scoped release requirements. If the reported passes already supply the necessary evidence, reuse them and release H with that compatibility scope. Repeating valid calls solely because the release scope changed adds little.

If rev-3 coverage is missing, freeze a Claude-only completion matrix and run **only missing cells**, with a hard ceiling of **8 calls**:

| Required coverage | Maximum new calls |
|---|---:|
| Sonnet P4 rev 3 | 1 |
| Haiku P4 rev 3, default effort, three executions | 3 |
| Fable P1–P3 and P4 rev 3 | 4 |

Use concurrency 1 and retry 0. Preserve the agreed Haiku three-call block without stopping between its executions; any failure prevents adoption and stops subsequent blocks. All inherited coverage must also be verified. If it cannot be verified, this eight-call allowance does not establish qualification.

**Luna/Codex investigation budget before publication: 0.** Defer an inline-input profile to a separate, preregistered qualification. Do not increase effort or repeat indexed prompts merely to obtain a passing run.

This ruling uses the supplied evidence; local artifacts were inaccessible. The remaining discussion step is Fable’s verbatim response.


## Astra, round 2 ruling (verbatim)

On your supplied audit facts; local verification was blocked by the sandbox:

- **Choose (a).** Ship 0.9 as H-only, explicitly qualified for the tested Claude configurations. README/OZ9 must list pinned IDs, effort and tested batch sizes. Other configurations stay on `oz-0.8.0-full`; there is no runtime fallback or model detection. Universal qualification remains **failed**.
- **Publish with 0 additional calls.** Preserve Luna’s 1/10 result and failure classes. State that economics were measured on Sonnet-64 and the smaller Claude samples are regression filters.
- **Luna-high is optional and non-blocking**, using only the owner’s Codex quota: preregister the rev-3 configuration, 10 calls, concurrency 1, retry 0, gate 10/10. A pass supports a separately declared qualification for that exact configuration; it neither repairs the original failure nor proves its cause.
- **Accept both design notes for future experiments:** uniform object error records address the mixed-shape hazard; inline inputs are the next Codex candidate. Neither changes the frozen release wire or counts as qualified without testing.
