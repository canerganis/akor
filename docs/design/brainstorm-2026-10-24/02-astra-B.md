**My vote: amend the pair, and withdraw partial programs from version one.** `oz map` is a useful surface; guarded reusable rules must earn their complexity against that surface with compilation disabled.

1. **Cross-critique**

   **Astra A**
   - **KEEP** the bounded AST, independent admission holdout, abstention and versioned provenance: these separate execution safety from semantic correctness.
   - **MERGE** residual pooling into the existing queue: a second scheduler would add complexity without establishing a new mechanism.
   - **DROP** the projected 46.3-token headline: coverage, residual-call cost and arrival timing remain assumptions; measure the matched baseline directly.

   **Opus A**
   - **KEEP** host expansion, reference chaining and compact receipts: these directly target repeated coordinator work.
   - **MERGE** `oz map` as the common surface for both experimental arms, so interface savings cannot masquerade as rule-engine savings.
   - **DROP** MCP and width-four execution from the first pilot: neither is necessary to test inference elimination.
   - **DROP** subagent-per-job as the decisive comparator: beating an already-defeated baseline does not establish progress beyond current AKOR.

   **Opus B**
   - **KEEP** batching audits together with residuals: otherwise fixed call overhead can consume the savings.
   - **DROP** 98% agreement with model-generated labels as sufficient admission: it measures imitation and can preserve correlated errors.
   - **DROP** scaled baseline timing and synthetic GenCache costs: neither captures actual scheduling, reasoning or failures.
   - **DROP** the “55-token floor”: a two-point fit is a local extrapolation, not an architectural bound.

2. **Revised position and novelty**

   I overstated the value of partial programs. Named semantic questions introduce intermediate contracts, context-selection errors and potentially sequential model rounds before demonstrating useful savings.

   Compilation itself is occupied by [GenCache](https://www.microsoft.com/en-us/research/wp-content/uploads/2025/09/GenCache_NeurIPS25.pdf) and [compilation-based semantic operators](https://arxiv.org/abs/2607.13407); optimized prompt batching is also explicit in [Sema](https://arxiv.org/abs/2603.11622).

   What remains new **relative to the supplied AKOR inventory** is reusable transformations across distinct inputs, exposed through reference-based submission and integrated with existing consumer checks, leases and selective fallback. Global novelty remains unestablished. The credible contribution is a measured implementation under authenticated CLI constraints.

3. **Convergence**

   **Accept with amendment:** build `oz map` over optional guarded whole-program rules and pooled residuals. Keep the same interface when compilation is disabled.

   A few command-line arguments do not establish low setup cost. Contracts, examples, admission labels and templates are part of the work; report human preparation separately and charge every model-assisted preparation call.

   Receipts must distinguish “accepted by runtime checks” from “correct against evaluation gold.” Multiple consumers receiving one answer still count as one unique solved job.

4. **Resolved choices**

   - **Program:** whole program returning `value` or `abstain`; defer named semantic questions.
   - **Audit:** seeded random **1/16 of covered outputs**, rounded up per nonempty wave. Audit blindly, without showing the candidate answer. Disagreement quarantines future reuse; it cannot erase previous errors.
   - **Pooling:** **yes**, across producers sharing authorization, contract and worker configuration, subject to a frozen maximum wait. Never pool merely because output schemas match.
   - **Public workload:** **BoolQ**, 256 frozen examples, as a negative control; report it separately from materials.
   - **Runner:** **`codex exec` only** for the kill pilot. Make no comparison claiming improvement over historical Sonnet numbers.
   - **Budget:** **20 calls maximum**: eight baseline evaluation calls, eight candidate residual/audit calls, two synthesis calls and two reserved failed-call retries. No candidate repair or uncounted model setup.

   Use 256 fresh materials jobs and 256 BoolQ jobs, each arriving in four 64-job waves from four scripted producers. Freeze separate training/admission sets, boundary cases, prompts, arrivals and checks. Disable exact-result memoization. Both arms use identical concurrency. This pilot measures engine economics; scripted producers cannot establish caller-agent savings.

5. **Most important kill criterion**

   **Kill the engine if it fails cold, quality-preserving dominance over `oz map` alone:** by job 256, require at least 25% fewer billed tokens per gold-correct materials job and 10% shorter makespan, with zero silent materials errors. Count compilation, audits, failures and hidden reasoning. Missing usage means unvalidated.

   BoolQ must add no errors and stay within 10% total token and time overhead, including compilation. Failure leaves an ergonomics improvement, not the requested efficiency breakthrough.

