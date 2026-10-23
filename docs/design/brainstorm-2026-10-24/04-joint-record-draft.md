## 1. Decision in three sentences

Build `oz map` with optional guarded whole-job rules and pooled fallback, using a standard-library Python core and authenticated CLI workers. The proposed contribution is AKOR’s integration of reusable rules, consumer checks, producer references and complete cost accounting, with global novelty unestablished. We claim neither compilation nor semantic batching as new: [GenCache](https://www.microsoft.com/en-us/research/publication/generative-caching-for-structurally-similar-prompts-and-responses/) reuses response patterns, [2607.13407](https://arxiv.org/abs/2607.13407) compiles semantic operators, [Sema](https://arxiv.org/abs/2603.11622) batches prompts, [DocETL](https://ucbepic.github.io/docetl/operators/map/) provides validated map operations, and [LOTUS](https://arxiv.org/abs/2407.11418) optimizes semantic operators against reference algorithms.

## 2. Design

Proposed surface:

```text
oz map 'refs/*.txt' --ask extract_alloy.oz --check checks.json --learn
```

Learning defaults off. The host expands references into `oz.do/1` jobs; disabling learning retains the same interface.

Rules use a bounded JSON AST returning `value` or `abstain`. No arbitrary Python, partial programs, tool selection or budget control. Keep OZ/1g unchanged; use an opt-in host envelope for the bootstrap artifact alongside ordinary answers.

Admission uses 64 independently labeled cases per workload, hidden from synthesis: 48 representative and 16 predetermined challenges. Require zero covered errors and coverage of at least 32 cases. This screens artifacts; it does not certify correctness.

Blindly audit 32 covered evaluation jobs, or all if fewer, using uniform seeded selection and identical IDs in B and C. Disagreement quarantines future reuse. Preserve every emitted error.

Pool only matching contract, check, permission and worker hashes. Flush at 64 records or one second. Preserve producer identity and consumer acceptance.

Reuse `oz do`, leases, settlement, checks, memo storage/revocation, durable publication, quota slots and accounting infrastructure. Add the interpreter, rule phase, Codex adapter, map expansion and producer spool with one locked drainer. Do not repurpose the fenced workspace coordinator or DAG executor. Preserve numeric lexemes; prevent rule receipts becoming memo entries. Receipts distinguish runtime acceptance from gold correctness.

## 3. Frozen kill pilot

Use seed `20261024`, 256 fresh materials jobs and 256 frozen BoolQ development examples. Freeze dataset hashes, admission sets, challenge cases, prompts, checks, producer assignments, dispatch ordering and backend configuration before calls. Evaluation gold remains inaccessible until scoring.

Four scripted producers submit 64 jobs each simultaneously. Maximum batch size is 64 data records; concurrency is four.

| Arm | Execution |
|---|---|
| A | Ordinary pooled map |
| B | Rules with producer-local fallback |
| C | Identical rules with pooled fallback |

For each workload, one shared bootstrap answers 16 jobs per producer and proposes one rule or `none`. B and C independently incur its full tokens and elapsed time. Their remaining 192 jobs, residuals and audits execute separately. No artifact revision, answer repair or shared baseline continuations.

Disable exact-result memoization. Count unique jobs once. Cold accounting includes bootstrap, admission, queue waits, audits, failures and completion of required checks. Report cumulative costs, coverage, correctness and human preparation effort separately. Any model-assisted preparation consumes the call budget.

## 4. Backend, budget and BoolQ resolution

**Keep `codex exec` throughout.** Pin model, reasoning setting, CLI version and invocation environment identically across arms. Preserve Claude quota: this pilot uses zero Claude calls.

The recorded 28,652 input tokens establish one call’s usage, not a fixed intercept. Nevertheless, substantial CLI overhead could make avoiding calls unusually valuable. Therefore a pass supports only the pinned Codex configuration; it cannot establish improvement over Sonnet’s historical 91.6 tokens or 20 seconds. Sonnet transfer requires a separate matched preregistration.

Cap execution at **32 physical calls**: one telemetry call, two bootstraps, eight A calls, nominally eight B residual calls and six C residual calls, plus seven reserve calls. Audits can exceed nominal residual capacity: 192 fallback jobs plus 32 audits require four pooled calls. Overflow and permitted infrastructure retries consume reserves; exhaustion leaves the experiment incomplete. Never revise a candidate.

Verify usage semantics before evaluation, including whether cached input and reasoning are already included in totals. Count each token once; retain raw telemetry.

Preserve `adopt_memo`’s job-bound requirement. BoolQ with `one_of` cannot adopt a rule; do not inject evaluation labels or manufacture a check to bypass it. BoolQ therefore tests learning-attempt and rejection overhead, **not semantic rule safety**. Materials must have legitimate input-bound checks without evaluation gold.

## 5. Build order

Each step uses fake adapters only:

1. Codex adapter: replay events; verify inclusive usage and failure capture.
2. Map expansion: verify references, producer IDs, planning and receipts.
3. AST and admission: reject unknown nodes; test bounded execution, abstention and independent labels.
4. Rule integration: test zero-call adoption, fallback, quarantine and prevention of memo laundering. Bootstrap answers and artifact must share one physical call.
5. Spool and drainer: test compatible pooling, isolation, count/deadline flushing and crash recovery.
6. Accounting harness: reconcile producer shares with physical calls; replay shared bootstrap charging, audit overflow and budget exhaustion.

Work on `oz-0.9`; commit only validated owned changes. No push.

## 6. Ordered kills and permitted headline

1. **Safety:** any incorrect rule-origin materials answer released as accepted kills admission.
2. **Validity:** leakage, incomplete inclusive usage or budget violation makes efficiency unvalidated.
3. **Materials:** C preserves correctness, reduces cold tokens per gold-correct job by at least 25%, and cold makespan by at least 10% versus A.
4. **BoolQ:** C adds no gold errors and at most 10% cold token and time overhead.
5. **Pooling:** C uses fewer tokens than B without worse correctness or makespan; otherwise withdraw pooling’s contribution claim.

Permitted headline after all gates pass:

> In one preregistered Codex pilot, guarded rules reduced cold tokens per correct materials job by at least 25% and completion time by at least 10% versus pooled batching.

Publish actual figures and configuration. Replication remains required; no caller-agent savings claim.

## 7. Remaining disagreements

Opus B favors Sonnet and a relative error criterion; Astra B favors Codex and zero silently wrong rule outputs. Opus A favors broader replication and bootstrap agreement; both Astras require independent admission labels. This record selects Astra B’s bounded pilot while explicitly narrowing BoolQ and backend claims. Signatures remain pending.

