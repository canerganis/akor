**1. Diagnosis.** AKOR has already harvested the easy win: batching takes 7,931 tokens/job to 151.1; OZ reaches 91.6. Queues, DAGs and memoization already exist. Arm K’s 798.7 tokens/job, with 81–89% spent by the caller, shows that coordination remains expensive even with file references. Parallelism buys elapsed time, not inherently fewer tokens; streaming buys earlier delivery, not necessarily higher throughput.

The dangerous shortcut is learning rules from benchmark examples and calling passing outputs “verified.” Format checks cannot establish semantic correctness. Delivering one result to multiple agents must not inflate completed-job counts.

**My bet: partial programs with explicit model questions**, with a deliberately limited efficiency claim.

**2. Prior-art collision check.** [GenCache](https://www.microsoft.com/en-us/research/wp-content/uploads/2025/09/GenCache_NeurIPS25.pdf) already synthesizes, validates and reuses programs, including inside agent workflows: “compile once” is not novel. [Plan Caching](https://arxiv.org/abs/2506.14852) reuses adaptable plans. [Batch prompting](https://arxiv.org/abs/2301.08721) amortizes calls; [TOON](https://github.com/toon-format/spec) compresses representation; [routers](https://arxiv.org/abs/2406.18665) select models; provider [batching](https://platform.claude.com/docs/en/build-with-claude/batch-processing) discounts asynchronous requests and [caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) reuses prefixes.

[LOTUS](https://arxiv.org/abs/2407.11418) also offers declarative semantic operators and optimized execution. Neither “a few lines” nor mixing deterministic and semantic processing establishes novelty.

The defensible addition is narrower: an AKOR contract for sharing bounded executable transformations and unresolved semantic requests between agents, with per-consumer checks and measured compilation amortization. That is new relative to the supplied repo scan; global novelty remains unestablished.

**3. Proposal.** Build a restricted partial-program interpreter plus residual batching. A model proposes a program using field access, literal splitting, decimal arithmetic, comparisons, tables and named semantic questions. The host executes deterministic parts and batches unresolved questions through existing CLI workers.

Contracts pin allowed primitives, question templates, input domains, checks and budgets. Generated programs cannot introduce tools or destinations. No Python `eval`, arbitrary loops or unrestricted regex. A guard failure abstains. Each program has a version, provenance and revocation handle; consumers retain their own acceptance checks.

Proposed syntax:

```sh
oz skill build alloy.contract.json --examples training.jsonl
oz submit incoming.jsonl --skill alloy --consumers screening,report
oz run --cli claude --audit 0.05
```

The contract and tests are real setup work, charged explicitly. Producers submit references; the existing executor handles delivery without repeatedly waking a coordinator. An agent still pays its initial submission turn.

Audit samples detect disagreements; they do not certify unseen cases. Purely semantic tasks can fall back entirely. Their lack of speedup must remain visible.

**4. Expected gain.** The old result implies 5,862.4 tokens per 64 jobs and 192 jobs/minute. An illustrative linear model is \(T(m)=2,400+54.1m\), fitted from the supplied totals; its extrapolation is unvalidated.

**Guess:** compilation and setup cost 6,000 tokens/20 seconds; 75% of items run locally; each subsequent wave sends 16 residuals plus three audit items, taking 13 seconds, with negligible host overhead. Four waves then cost approximately **77 tokens/job and 72 seconds for 256 jobs: 213 jobs/minute**, assuming unchanged correctness.

But the first 64 cost approximately **147 tokens/job and 33 seconds**. This loses cold. If the requirement means beating 91.6/20 on the first untouched batch, this proposal does not meet it.

These are scenario calculations, not predictions. Hidden reasoning may erase the assumed residual-call savings.

**5. Smallest preregistrable experiment.** Freeze three arms: A, current OZ batching; B, a GenCache-style whole-program surrogate using the same restricted primitives; C, partial programs plus residual batching. B is not a reproduction of GenCache. Include a handwritten deterministic solver as a host-only reference on materials.

Use 256 previously unseen materials records and 256 public [SuperGLUE RTE](https://arxiv.org/abs/1905.00537) entailment pairs, each in four 64-item waves. RTE is the non-rule-shaped negative control. Freeze separate training examples, input-order seeds, contracts, prompts and checker hashes. Evaluation labels never enter compilation, runtime acceptance or fallback decisions. Include predetermined format/boundary changes in materials.

Run two order seeds. A needs 16 calls; B and C each allow four compilation calls and sixteen residual/audit calls: **56 calls maximum**, failures included, no post-hoc repairs. Any extra model-assisted setup consumes that same cap. Use `codex exec` for this kill pilot: **zero additional Claude calls**. This cannot validate the Sonnet-specific projection; that requires a separately quota-admitted replication. Call counts alone cannot guarantee staying below Claude’s 60% limit.

Count compilation, caller interaction, audits, failures and hidden reasoning; publish cache categories separately. Report unique gold-correct jobs, errors, coverage, cumulative tokens, makespan and jobs/minute after every wave. Missing usage makes efficiency unvalidated.

Kill C if, in either seed, it adds any materials error, exceeds A’s RTE error count, or fails to save 15% tokens and 10% elapsed time on materials by wave four. Also kill if RTE overhead exceeds 5%. An indistinguishable B/C result kills the claimed methodological distinction. This pilot can reject the idea; it cannot establish population-level reliability.

**6. Headline and strongest critic.** Target headline, only if subsequently measured on Sonnet: **“AKOR completes 256 new verified jobs below 80 tokens each and above 210 jobs/minute, including compilation.”**

Strongest critic: “This is GenCache-style automation around an easy workload; your semantic control merely demonstrates when the optimization stops helping.”

