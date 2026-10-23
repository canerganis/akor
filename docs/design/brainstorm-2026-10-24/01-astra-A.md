**1. Diagnosis**

Build **guarded reusable rules plus a shared queue for unresolved jobs**. More compression alone attacks the wrong remainder: OZ already reaches 91.6 tokens per verified job versus 151.1 for batched JSON. Arm K still costs 798.7; 81–89% comes from callers rewriting jobs and rereading context. Files did not fix that.

The roughly 2,400-token call floor means shrinking four batches without eliminating calls disappoints. Reuse existing leases, acceptance and DAG handoffs. The new mechanism must replace repeated inference. Credit caller savings only when measured.

**2. Prior-art collision check**

[GenCache](https://www.microsoft.com/en-us/research/wp-content/uploads/2025/09/GenCache_NeurIPS25.pdf) already generates, validates and reuses programs, including within agent workflows. Compilation, fallback and agent integration are not novel. [Plan Caching](https://arxiv.org/abs/2506.14852) already reuses structured plans but uses models for adaptation.

[Batch prompting](https://arxiv.org/abs/2301.08721) shares calls; [TOON](https://github.com/toon-format/toon) compresses serialization; [routers](https://arxiv.org/abs/2406.18665) select models; [provider batching](https://platform.claude.com/docs/en/build-with-claude/batch-processing) discounts asynchronous requests, while [prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) reuses prefixes.

The proposed contribution is narrower: a bounded rule artifact admitted under a consumer’s contract, with per-job provenance, abstention and pooled fallback inside AKOR’s executor. This is an engineering combination to benchmark, not an established literature-first claim. A restricted language limits execution authority; it does not prove semantic correctness.

**3. Proposal**

Add an opt-in `oz-rule/1` host manifest, leaving OZ/1g packets unchanged. The model returns a candidate JSON AST through an existing result slot. Its grammar permits bounded literal extraction, field selection, decimal comparisons and finite mappings. No loops, arbitrary regex, imports or I/O. Every path returns `value` or `abstain`; unknown nodes fail admission.

Register one host operation, `evaluate_rule`. The model selects transformations within its pinned grammar, never flow operations, checks, destinations or budgets.

Admission requires an independent labeled holdout. Missing fields, unsupported units and ambiguous matches abstain. Store the admitted rule by content hash with contract, interpreter and check versions; changed versions invalidate reuse.

Proposed syntax, not implemented commands:

```text
family assay contract=assay-v1 checks=assay-v1
compile assay examples=@examples grammar=oz-rule/1
map @agents/assays via=assay fallback=sonnet -> @accepted
```

Pool unresolved jobs across compatible contracts and permissions, preserving IDs and destinations. Commit through existing acceptance/DAG machinery. Receipts identify input digest, rule hash and branch. A fixed 5% sample receives model cross-checks; disagreement quarantines the rule. Agreement is not proof, and earlier errors remain recorded.

**4. Expected gain**

**Illustrative guesses:** 256 fresh materials jobs, 85% rule coverage, 5% auditing of covered jobs, one 6,000-token/20-second compilation, and one residual call costing approximately the current 64-job call.

About 39 unresolved jobs plus 11 audits fit one batch. At 5,862 tokens and 20 seconds per batch, cold cost becomes approximately **46.3 tokens/job, 40 seconds and 384 jobs/minute**; subsequent work approximately **22.9 tokens/job, 20 seconds and 768 jobs/minute**. Four ordinary batches imply 91.6 tokens/job, 80 seconds and 192 jobs/minute.

These exclude unmeasured host and arrival delays. A cold 64-job workload may lose. BoolQ needs its own matched baseline.

**5. Smallest preregistrable experiment**

Freeze one seeded pilot: 256 unseen materials cases, including 32 boundary/drift cases, plus 64 public [BoolQ](https://github.com/google-research-datasets/boolean-questions) development examples. BoolQ requires passage-level semantic judgment and supplies the non-rule-shaped workload. Use separate synthesis/admission examples; remove duplicates and disable exact-result memoization. Test labels remain offline and cannot trigger fallback.

Three arms use identical models, checks, arrivals and maximum batch size 64:

- **A:** Existing pooled OZ/1g.
- **B:** Admitted rules, residuals confined to each producer’s original batch.
- **C:** The same rules, residuals pooled across four producers.

Share frozen candidates between B/C, charging full synthesis cost to each arm’s cold accounting. Producers are scripted replay clients; no caller-agent savings are claimed. Compare materials and BoolQ separately. Include a hand-written materials implementation as the zero-model-token engineering baseline.

Measure billed tokens per independently correct job, accuracy, coverage, silent rule errors, cold makespan, queue-inclusive p95 latency and verified jobs/minute. Count synthesis, audits, cache categories, hidden reasoning, failures and retries. Missing usage telemetry makes cost unvalidated. Runtime acceptance is not ground truth.

Kill the proposal if C introduces any silent materials error, loses more than one BoolQ answer versus A, or fails to reduce both materials tokens/correct-job and makespan by 25%. Require BoolQ post-compilation cost and time within 10% of A; report compilation overhead separately. Reject pooling if C improves neither cost nor makespan over B. These are pilot thresholds, not population guarantees.

Budget: **at most 18 calls**—two syntheses, fifteen evaluation calls, one reserved retry. No candidate repair. Reserve each capped call’s quota debit before launch; never cross 60%. If that bound is unavailable, use matched `codex exec` arms and withhold comparison with historical Sonnet. Otherwise use authenticated `claude -p`; no API keys.

**6. Headline and strongest critic**

Conditional headline: “AKOR completes 256 new agent jobs with fewer tokens and less time than its own 64-job batching baseline, counting compilation and audits.”

Strongest critic: “This is GenCache with a restricted interpreter, and your gains come from automating tasks that should already have ordinary code.”

