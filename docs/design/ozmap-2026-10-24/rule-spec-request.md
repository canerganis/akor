You are Astra A, AKOR language owner (high effort). The signed record (below) asks for an opt-in rule language,
`oz-rule/1`: a bounded JSON AST that the host interprets, returning a value or abstain. Write its normative spec.

Target workload (the pilot's materials ops). Each job gets one record text like:
  length=12.50 mm; uncertainty=0.02 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed
Goal: acceptance interval [12.48,12.52] mm inclusive. Ops:
  e: compact JSON array of strings with length, uncertainty, n, method, basis, physical_validation in that order, values exact.
  b: [length-uncertainty,length+uncertainty] as strings with two decimals and unit mm; if uncertainty unknown, "unknown".
  m: JSON array of field names whose values are unknown, in order uncertainty, method, basis.
  v: "inside" if the whole length +/- uncertainty interval lies within the acceptance interval, "outside" otherwise,
     "unknown" if uncertainty unknown.
BoolQ (passage + yes/no question) is the non-rule control: a correct spec makes the model answer "none" there.

Requirements:
1. Node set: exact JSON shapes for each node, typed (string, decimal, bool, list), with Decimal arithmetic and exact
   formatting (no float), literal field extraction from `key=value; ...` text, splitting on literal separators,
   comparisons, conditionals, finite lookup tables, list construction. No loops, recursion, regex, imports, I/O, or
   access outside the job's own input text.
2. Abstain semantics: every failure path (missing field, unparseable number, unit mismatch, type error) yields
   abstain, never an exception or a guess. Define when the rule result counts as abstain vs value.
3. Bounds: max 2 KB UTF-8 per AST, max depth, max node count, max output size, and a step budget.
4. Lossless numerics: preserve lexemes (12.50 stays 12.50) when a field is passed through; define formatting.
5. Envelope: how the bootstrap call asks for "rule or none" per op without changing OZ/1g (the record says an opt-in
   host envelope / result slot); give the exact instruction text for the model, under 1,200 characters, and the
   exact reply shape.
6. Admission and audit interface: inputs and outputs of `admit(ast, labeled_cases)` and `evaluate(ast, text)`.
7. Worked examples: one valid AST for each of e, b, m, v, and three invalid ASTs with the rejection reason.
8. Conformance tests: 15 to 25 one-line test vectors (input text, AST ref, expected value or abstain).
English, at most 1,800 words plus the JSON examples. No dashes as punctuation.

--- signed record ---
# 04-joint-record-final

## 1. Decision in three sentences

Build `oz map` with optional guarded whole-job rules and pooled fallback, using a standard-library Python core and authenticated CLI workers. The proposed contribution is AKOR’s integration of reusable rules, consumer checks, producer references and complete accounting; global novelty remains unestablished. We claim neither compilation nor semantic batching as new, given [GenCache](https://www.microsoft.com/en-us/research/publication/generative-caching-for-structurally-similar-prompts-and-responses/), [semantic operator compilation](https://arxiv.org/abs/2607.13407), [Sema](https://arxiv.org/abs/2603.11622), [DocETL](https://ucbepic.github.io/docetl/operators/map/) and [LOTUS](https://arxiv.org/abs/2407.11418).

## 2. Design

```text
oz map 'refs/*.txt' --ask extract_alloy.oz --check checks.json --learn
```

Learning defaults off. The host expands references into `oz.do/1` jobs; disabling learning preserves the interface.

Rules use a bounded JSON AST returning `value` or `abstain`. Exclude arbitrary Python, partial programs, tool selection and budget control. Preserve OZ/1g; bootstrap artifacts use an optional host envelope.

Each candidate requires 64 independently labeled admission cases for its operation, hidden from synthesis: 48 representative and 16 predetermined challenges. Require zero covered errors and coverage of at least 32. Admission screens artifacts, not correctness certification.

Blindly audit 32 covered jobs per evaluation wave, or all if fewer, using uniform seeded selection and identical selected IDs in B and C. Disagreement quarantines future reuse. Preserve every emitted error.

Pool only matching contract, check, permission and worker hashes. Flush at 64 records or one second. Preserve producer identity and consumer acceptance.

Reuse `oz do`, leases, settlement, checks, memo storage/revocation, durable publication, quota slots and accounting. Add the interpreter, rule phase, Codex adapter, map expansion and producer spool with one locked drainer. Do not repurpose the fenced coordinator or DAG executor. Preserve numeric lexemes and prevent rule receipts entering memo storage. Receipts distinguish runtime acceptance from gold correctness.

## 3. Frozen kill pilot

Use seed `20261024`, 256 fresh materials jobs and 256 frozen BoolQ development examples. Freeze dataset hashes, admission labels, challenges, prompts, checks, assignments, ordering and backend configuration before calls. Evaluation gold remains inaccessible until scoring.

Four scripted producers simultaneously submit 64 jobs each. Maximum batch size is 64 records; concurrency is four.

| Arm | Execution |
|---|---|
| A | Ordinary pooled map |
| B | Rules with producer-local fallback |
| C | Identical rules with pooled fallback |

Within each backend and workload, one bootstrap answers 16 jobs per producer and proposes one rule or `none` per operation. Each AST is capped at 2 KB of UTF-8 JSON. Answers and artifacts share one physical call.

Codex B and C independently incur the shared bootstrap’s full tokens and elapsed time. Their remaining 192 jobs, residuals and audits execute separately. No candidate revision, answer repair or shared baseline continuations.

Score bootstrap answers against gold and A’s answers for the same 64 jobs. Any gold error or disagreement invalidates efficiency conservatively; this comparison cannot establish that the artifact slot caused a disagreement.

After admission, materials producers each submit 64 additional fresh jobs to A and C on both backends. Freeze these warm datasets beforehand. Reuse unchanged rules; prohibit further learning.

Disable exact-result memoization. Count unique jobs once per arm and wave. Cold accounting includes bootstrap, admission, queues, audits, failures and required checks. Report warm increments, cumulative costs, coverage, correctness and human preparation separately. Model-assisted preparation consumes calls.

## 4. Backend, budget and BoolQ resolution

Run Codex through `codex exec`. Add a Sonnet 5.5 materials cell through `claude -p`, covering A and C, cold and warm waves, with four producers and concurrency four. Pin model, reasoning, CLI version and invocation environment within each backend across arms.

Historical records report roughly 24k to 25k Codex input tokens per call. These are configuration-specific observations, not a proven fixed intercept. Only the Sonnet cell may be contextualized against the historical 91.6 tokens and 20 seconds; causal improvement requires its matched A comparison.

Cap execution at **50 physical calls**:

| Backend | Allocation |
|---|---|
| Codex: 37 | Telemetry 1, bootstraps 2, A 12, B residuals 8, C residuals 7, reserve 7 |
| Sonnet: 13 | A 8, C 3, reserve 2 |

Sonnet C’s nominal three calls are bootstrap, cold residual and warm residual. Its approximately 70k-token estimate is provisional. Reserve Claude calls through `oz_quota`; do not launch work projected to reach 55% weekly usage, and abort further launches at that threshold.

Audits, overflow, additional telemetry, preparation and permitted infrastructure retries consume reserves. For example, 192 residual jobs plus 32 audits require four pooled calls. Exhaustion leaves the experiment incomplete.

Verify inclusive usage semantics before evaluation. Count cached input and reasoning exactly once and retain raw telemetry. Report call counts and token components; do not treat one-job telemetry as a validated removable floor.

Preserve `adopt_memo`’s job-bound requirement. BoolQ with `one_of` cannot adopt rules. Never inject evaluation labels or manufacture checks. BoolQ measures learning-attempt and rejection overhead, not semantic rule safety. Materials require legitimate input-bound checks.

## 5. Build order

Use fake adapters only:

1. Codex adapter: replay events, inclusive usage and failures.
2. Map expansion: references, producer IDs, planning and receipts.
3. AST/admission: unknown-node rejection, bounds, abstention and independent labels.
4. Integration: zero-call adoption, fallback, quarantine, memo isolation and fused bootstrap.
5. Spool/drainer: compatible pooling, isolation, count/deadline flushing and crash recovery.
6. Accounting: producer shares, physical calls, bootstrap charging, audit overflow and exhaustion.

Work on `oz-0.9`. Commit only validated owned changes. No push.

## 6. Ordered kills and permitted headline

1. **Safety:** any incorrect rule-origin materials answer released as accepted kills admission.
2. **Validity:** leakage, incomplete usage, bootstrap failure or budget violation invalidates efficiency.
3. **Materials:** on each backend, C preserves correctness and reduces cold tokens per gold-correct job by at least 25%. Report cold makespan without gating. Warm C requires at most 0.9× A’s makespan and 0.5× its tokens per correct job.
4. **BoolQ:** C adds no gold errors and at most 10% cold token and time overhead.
5. **Pooling:** Codex C uses fewer cold tokens than B without worse correctness or makespan; otherwise withdraw pooling’s contribution claim.

After all gates pass:

> In preregistered Codex and Sonnet pilots, guarded rules reduced cold tokens per correct materials job by at least 25%, with warm completion time reduced by at least 10%.

Publish actual figures and configurations. Replication remains required. No caller-agent savings claim.

## 7. Remaining disagreements

Both blockers are integrated. The requested 37-call global cap is rejected.
It covers Codex with the warm wave; Sonnet adds 13.

The floor-adjusted BoolQ gate is rejected.
One-job telemetry includes variable work and cannot identify a fixed floor.

The fused bootstrap safeguard is integrated conservatively.
Any disagreement invalidates efficiency because slot-specific causation is unidentified.

Signed: Astra A (gpt-6-astra), date 2026-10-24  
Opus B: signature conditional on blockers 1 and 2 as integrated above.

