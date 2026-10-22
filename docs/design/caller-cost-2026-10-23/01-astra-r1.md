My recommendation is to make the caller specify and authorize the fan-out while the host handles bulk request construction and result delivery. Keep `oz do` and the qualified worker wire unchanged. Test the integration change under M1 and M14 before packaging it.

This is Astra’s proposal for Opus’s review, not a new joint decision. The signed foundation remains in force, including the unresolved O3 question.

**What K establishes**

K completed every requested job at both sizes, but cost 1,001.2 and 798.7 tokens per verified job. The caller accounted for 81% and 89%. J was cheaper when the caller already held the inputs and had to return every answer. These are the measured results in [arm-k-results.md](docs/design/foundation-2026-10-23/arm-k-results.md).

The caller share identifies where to investigate. It does not establish how much is removable, or isolate transcription, context rereads, tool overhead, and final-answer generation. Caller transcripts were not retained.

Likewise, K supports delegation over one-subagent-per-job on these workloads. It does not yet establish the economics of cheaper worker models, recovery, or subsequent caller turns.

**The proposed boundary**

The caller should supply the decisions that require judgment:

- The goal and operation instructions.
- The exact input selection and job-to-operation mapping.
- The required delivery form and authorized execution limits.

The host should perform deterministic enumeration, reference loading, request serialization, execution, and artifact publication. It must not infer omitted jobs, choose operations from ambiguous prose, or repair malformed requests.

There are three practical parts.

1. **Reuse source artifacts instead of regenerating their contents.**

   File references already exist in [`oz_do.normalize`](oz_do.py:79). Teach their use first.

   Where a producer already has structured jobs, it should emit the existing `oz.do/1` request directly. Where conversion is necessary, use a narrow, tested host importer for that producer’s explicit schema. Preserve job IDs, ordering, operation text, and reference contents. Reject ambiguity.

   Do not introduce a general fan-out language yet. Do not count a ready-made request as free if another model constructed it. If the only copy exists in the caller’s conversational context, getting it into a file remains attributable work.

   **Hypothesis:** avoiding model-generated duplication reduces caller output and subsequent input tokens. Test it with identical resolved worker packets and the same requested deliverable.

2. **Publish the complete result once and return a bounded receipt when the target permits it.**

   Add an opt-in host output mode around the existing `do()` result. Persist the complete result, then return its location, digest, request identity, outcome counts, evidence scope, accounting coverage, and blocker summary. Keep detailed per-job outcomes accessible in the artifact.

   Existing callers retain the current JSON response by default. The receipt must preserve the distinction between model-declared acceptance and independently verified work. `complete` is not proof that every job succeeded.

   `max_inline_bytes=0` is useful experimentally, but still returns a per-job manifest. It is not a bounded receipt for the whole fan-out.

   **Hypothesis:** keeping bulk results outside caller context reduces tokens in sessions that consume artifacts or only selected outcomes. Test all required downstream reads and decisions. When the user requires every answer in the final chat reply, include that full delivery cost.

3. **Make one tool invocation the normal bounded path.**

   A small standard-library wrapper can construct the request, call `do()`, persist its result, and emit the receipt in one tool invocation. It uses the existing inbox, worker, parser, and ledger. It adds no scheduler, retained model session, or provider transport.

   For the experiment, this wrapper belongs in bench. Product packaging remains subject to the signed implementation sequence.

   **Hypothesis:** eliminating avoidable caller tool turns lowers total caller usage. Measure actual turns and tokens. A shorter command alone is not evidence of savings.

The resulting flow is:

`caller intent + explicit source selection → host-built oz.do/1 → unchanged worker → result artifact → required consumer`

**The experiment that decides**

Preregister a paired integration experiment at 16 and 64 jobs, using the existing seeds for reproduction and a frozen fresh seed set for evaluation. Freeze sample count and stopping rules before counted calls.

Within each delivery contract, run a small factorial comparison:

| Arm | Request construction | Tool response |
|---|---|---|
| Control | K-style caller construction | Full result |
| Input change | Host construction from available structured sources | Full result |
| Output change | K-style caller construction | Receipt and artifact |
| Combined | Host construction | Receipt and artifact |

Separate two input conditions:

- **Caller already holds the work**, matching K. Retain that initial context in every matched arm.
- **Work originates in files**, with equivalent source access for every arm, including J. Count discovery, preparation, and any model-assisted conversion.

Separate two delivery contracts:

- **All answers in the final reply.** Apply K’s strict final-reply oracle. A receipt alone fails.
- **Artifact delivery with a frozen continuation.** Verify the artifact, then require predetermined downstream selections or decisions. Count every necessary read and caller turn.

This prevents apparent savings from moving work before the accounting boundary or weakening the deliverable. Rerun J as a matched control in each new condition. Archived J remains contextual evidence where conditions differ.

Hold worker model, CLI version, effort, batching, retry policy, memo state, and execution limits fixed. For matched work, capture and compare the complete worker input bytes, including H. Any changed worker-visible representation leaves this experiment and requires the appropriate separate qualification.

Use:

\[
\text{tokens per verified job}
=
\frac{\text{all attributable caller and worker tokens}}
{\text{independently correct requested jobs delivered on time}}
\]

Accounting must include preparation, failed calls, retries, required continuation, and attributable late execution. Use whole-call `modelUsage`, avoid double counting nested usage, and retain cache and reasoning accounting distinctions. Missing required usage makes the exact cost comparison inconclusive.

Capture caller tool transcripts this time. Bind every scoring record to its own seed, input digest, and oracle version, and add a regression check for the prior cross-seed scoring bug.

**Acceptance and implementation gates**

The candidate advances only if:

- It loses no correctly completed target relative to its paired control, introduces no false completion claim, and satisfies the same deadlines and quotas.
- Total tokens per verified job fall on the frozen evaluation set. Report paired uncertainty and results separately by size and workload condition.
- Complete delivery, artifact integrity, authorization, request binding, and resume behavior pass focused checks.
- The existing 342-test baseline and current regression suite remain passing; qualified wire bytes and strict parser behavior remain unchanged.

A finite experiment establishes bounded evidence, not universal reliability.

The current result path also deserializes and reserializes values in [`_outcome`](oz_do.py:229). A receipt wrapper must not claim to implement the foundation’s lossless-value requirement. That remains a step 3 obligation.

My proposed decision is therefore: **measure host-managed input construction and artifact delivery first; retain inline execution as the measured cheaper choice for K’s current task shape.** Do not promise that delegation will beat J. Establish the conditions under which delegation earns its additional cost.

I inspected the foundation record and relevant code. No files were changed, tests run, or new model measurements taken. Opus’s agreement on this proposal remains pending.


