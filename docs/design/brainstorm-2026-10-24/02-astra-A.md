**Accept the pair, but narrow the engine and the claims.** Build `oz map` over guarded whole-job rules with pooled fallback. Defer partial programs until whole-job abstention demonstrably leaves valuable work unexploited.

1. **Cross-critique**

   **Astra B**
   - **KEEP** restricted primitives, consumer contracts and explicit abstention: these make executable artifacts inspectable and bounded.
   - **DROP for v1** named semantic questions inside partial programs: they introduce continuation state, intermediate schemas and additional failure paths before we know whether whole-job rules pay.
   - **MERGE** cumulative cold/warm accounting and the handwritten reference: both expose whether compilation earns its setup cost.
   - **DROP** the 56-call pilot: a smaller ablation can kill the initial mechanism.

   **Opus A**
   - **KEEP** `oz map`, host expansion and reference-only stage handoffs: these directly address orchestration friction.
   - **MERGE** compact receipts, but distinguish “accepted by checks” from “independently correct.”
   - **DEFER** MCP and width-four execution: useful packaging and acceleration, but neither establishes the rule engine’s benefit.
   - **DROP** constant caller-cost and subagent-replacement headlines until measured; inline execution remains a serious competitor.

   **Opus B**
   - **KEEP** batching audits together with unresolved jobs and charging compilation across subsequent work.
   - **DROP** 98% agreement with teacher outputs as semantic admission: shared mistakes can pass perfectly.
   - **MERGE** independent admission labels and revocation, while retaining every previously emitted error in the results.
   - **DROP** scaled baselines and hypothetical GenCache costs as headline evidence: execute matched baselines; label calculations separately.

2. **Revised position and novelty**

   Compilation is already explicit in [compilation-based semantic operators](https://arxiv.org/abs/2607.13407); [Sema](https://arxiv.org/abs/2603.11622) already combines semantic execution with prompt batching. [GenCache](https://www.microsoft.com/en-us/research/wp-content/uploads/2025/09/GenCache_NeurIPS25.pdf) also evaluates reuse inside agent workflows. Therefore, neither “compile plus batch” nor “for agents” establishes novelty.

   What remains new **relative to the supplied AKOR state** is a portable, consumer-bound rule artifact integrated with its existing acceptance and handoff machinery: producers submit references; the host executes admitted rules, pools unresolved work and preserves provenance. Global novelty remains unestablished. The contribution must be a measured implementation advantage.

3. **Convergence**

   **Accept with amendments.** `oz map` is the surface; guarded rules are an optional execution strategy underneath it. Ordinary batching remains available through the same surface, enabling a clean comparison.

   Keep OZ/1g unchanged. Put rule metadata in an opt-in host manifest. Every rule returns `value` or `abstain`; receipts record input digest, rule/interpreter/contract versions and execution source. Preserve numeric lexemes across handoffs. Rules cannot choose destinations, tools or budgets.

4. **Resolved choices and experiment**

   - **Program:** whole-job guarded rules. No named semantic questions in v1.
   - **Audit:** seeded **1/16 of rule-covered jobs**, selected independently of predicted answers. Audit disagreement quarantines the rule; agreement is not correctness certification.
   - **Pooling:** **yes**, only across matching contracts, permission boundaries and worker configurations, with a fixed maximum wait. Preserve producer IDs and consumer-specific acceptance.
   - **Public workload:** **BoolQ**, 64 untouched evaluation examples, alongside 256 fresh materials cases including predetermined boundary cases. Synthesis and independently labeled admission sets remain separate.
   - **Runtime:** **`codex exec` only** for the kill pilot. No additional Claude quota consumption; no claim against historical Sonnet performance.
   - **Budget:** **20 calls maximum**: two synthesis calls, fifteen evaluation calls, three failure/retry slots. No candidate repair; exceeding the cap leaves the experiment incomplete.

   Use one frozen seed and three arms: A, ordinary `oz map`; B, rules with producer-local residual batches; C, identical rules with pooled residuals. Each arm processes all 320 evaluation jobs, batch size at most 64, width one. Charge full synthesis to both B and C. Include audits, failures, hidden reasoning and queue time; missing usage invalidates efficiency claims.

   Require C to reduce materials cold tokens/correct-job and makespan by 25%, with BoolQ cold overhead at most 10%. Scripted producers cannot establish caller-agent savings.

5. **Most important kill criterion**

   **Any incorrect rule-origin materials answer released as accepted kills the current admission design.** Gold labels remain offline until scoring. Neither aggregate accuracy nor later revocation erases that failure.

