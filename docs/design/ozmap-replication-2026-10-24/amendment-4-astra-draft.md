# Amendment 4: clean replication (Astra A draft, 2026-10-24)

Model gpt-6-astra, effort high, codex-cli 0.160.0. Unedited output.

**A4.1. Scope and precedence.** This amendment governs a new replication. It supersedes the conflicting isolation, budget, bootstrap validity, cache certification and workload provisions in the signed record and sign offs. Everything else remains unchanged. The pilot remains invalid; this amendment cannot rehabilitate its results. Freeze all amendments, manifests and executable checks before replication calls. Preserve every attempt and failure.

**A4.2. Codex isolation.** Use a dedicated run directory containing four numbered worker `CODEX_HOME` directories. Before each call, reconstruct its worker home from an authentication only baseline. Permit only the authentication material required by the pinned CLI. Never copy the owner’s home wholesale.

Exclude plugins, skills, memories, histories, sessions, hooks, `AGENTS.md`, user configuration, instruction files and configuration overrides. Runtime files created during a call must be inventoried and removed before the next call. Keep evidence outside the model’s accessible directories.

Launch with an allowlisted environment and frozen CLI arguments. Exclude inherited instruction, configuration, resume and plugin settings. Use an empty, stable working directory and verify every instruction discovery location, including ancestors. If the CLI cannot prevent discovery outside these directories, use an isolated account or container that can.

Before **every** call, the driver must verify the baseline inventory, executable and argument hashes, environment allowlist, empty working directory, disabled tool execution and effective instruction sources. A mismatch prevents launch. Authentication contents must never enter logs.

**A4.3. Tool events and refusal.** Retain the narrowly defined plain CLI notice exception from the telemetry notes. A tool request intercepted before execution is a refused call, consuming tokens, time and one call allowance. It does not establish an external read. Actual execution, an external read, or inability to establish whether execution occurred invalidates replication efficiency, even if all answers are refused. A clean home does not excuse tool use.

No selective rerun may erase this failure. Existing restrictions on infrastructure retries and answer repair remain.

**A4.4. Capacity formula.** Budget for zero admitted rules. Let \(N_p\) be producer \(p\)’s jobs, \(b_p\) its bootstrap jobs, \(a\) the maximum additional audit records, and \(M=64\).

For pooled execution, reserve nominal capacity

\[
\left\lceil(\sum_p(N_p-b_p)+a)/M\right\rceil.
\]

For local fallback, conservatively reserve

\[
\sum_p\left\lceil(N_p-b_p+a)/M\right\rceil.
\]

The local formula intentionally allows the entire audit allowance at each producer. Actual auditing remains 32 jobs per wave, not 32 per producer. Charge bootstrap separately. For A, both \(b_p\) and \(a\) are zero.

These bounds assume full eligible batches. Freeze synchronized producer submission and dispatch procedures that satisfy this assumption. Before launch, exercise the actual scheduler with no rules and worst permitted audit placement. If deadline flushing exceeds these bounds, revise and sign the allocation before evaluation.

**A4.5. Physical call allocations.** Each materials backend receives the following nominal capacities: cold A 4, shared bootstrap 1, cold B 8, cold C 4, warm A 4, warm C 5. Total: 26.

Codex BoolQ receives cold A 4, shared bootstrap 1, B 4 and C 3. Total: 12. BoolQ has no rule audits.

Give each listed allocation its own reserve of two calls. Unused capacity cannot justify new learning, answer repair or another experimental condition. Shared bootstrap is one physical call, but B and C each incur its full accounting cost.

Caps are:

| Backend or activity | Nominal | Telemetry | Reserve | Total |
|---|---:|---:|---:|---:|
| Codex evaluation | 38 | 4 | 20 | 62 |
| Sonnet evaluation | 26 | 2 | 12 | 40 |
| Fable preparation |  |  |  | 4 |
| Astra preparation and review |  |  |  | 4 |
| Opus preparation and review |  |  |  | 4 |
| **Global** |  |  |  | **114** |

Preparation includes already commissioned replication work and this amendment. Reconcile its actual physical calls before freezing. If those allowances are already exceeded, obtain a prospective revised cap before evaluation. Human coordination does not consume calls; model assisted coordination does.

**A4.6. Bootstrap gold errors.** Classify operations before generation and calls. An operation is rule shaped only if an independent reviewer establishes from its written contract that the frozen AST language can express a nontrivial, input determined solution on a specified domain. Record permitted inputs, outputs, guards and reasons for expressibility without writing a solution AST. Classification cannot depend on learner success.

The four eligible materials operations are rule shaped. BoolQ is not: its answer requires semantic judgment beyond the permitted input bound rule contract, and its checks cannot authorize adoption.

For rule shaped operations, retain bootstrap gold error and matched A disagreement as efficiency validity failures, including when the learner proposes `none`. For BoolQ, ordinary bootstrap errors and disagreements enter correctness and overhead measurements without invalidating efficiency. Malformed or missing bootstrap output remains a completion failure. Any incorrect rule origin answer released as accepted still triggers the safety kill.

**A4.7. Cache certification.** No evidence supplied establishes a CLI probe that guarantees a **live** cache hit. Repetition cannot provide that guarantee. Do not promise one or sample until a favorable pair appears.

Replace mandatory paired live certification with a frozen route contract audit plus deterministic positive cache replay. Trace the exact CLI usage decoder to an authoritative provider definition establishing whether input includes cached tokens. Archive the definition, route identity and decoder mapping.

The guaranteed positive reading comes from an injected fixture through that same decoder: total input 10,000, cached input 4,000, and uncached input 6,000. Inclusive accounting must report 10,000, not 14,000 or 6,000. A second fixture with cached input zero must also report 10,000. Freeze output and reasoning fixtures separately to verify no double counting.

Replay certifies implementation arithmetic only. The authoritative route definition certifies live field semantics. Both are required for this alternative. Valid paired live evidence remains acceptable under the existing equal input, different cached count test.

Zero cached input needs no cache inclusion certificate. Positive cached input without either certification path makes that call usage unverified and its dependent cells incomplete for token claims. Execution may continue. Retain per call reasoning certification exactly as sign off 5 requires. Freeze its executable predicate before launch.

**A4.8. Independent operations.** Fable’s four operations replace the original four throughout materials bootstrap, admission, cold and warm evaluation. Mixing them would weaken the independence test. Preserve the original task counts and admission design.

Neither the designer nor another preparation agent may produce a hidden worked AST for these operations. Fable supplies contracts, executable gold oracles and generators only. An independent reviewer validates oracle correctness and expressibility; Astra remains blind until scoring.

Replace byte identity comparison with a provenance audit: timestamped artifacts, access manifests, exact learner prompt hashes, isolation attestations and evidence that no reference AST existed before learner output. Independently checked admission labels and evaluation gold remain inaccessible to synthesis.

A successful claim may say the backend synthesized rules for independently authored operations from the frozen prompt. It cannot establish novel reasoning, exclude all training familiarity or certify general semantic correctness.

**A4.9. Sonnet.** Keep Sonnet’s pilot prompt unchanged, with complete A, B and C cold cells and A and C warm cells. Add no exploratory prompt cell in this replication. This preserves the backend comparison and makes failure to propose rules informative. Report `none` as an outcome, not a reason to change prompts after inspection.

**A4.10. Success and headline.** Require complete cells, complete relevant usage, passed isolation and bootstrap validity, and no safety kill.

On each backend, materials C must preserve correctness and reduce cold tokens per gold correct job by at least 25%. Warm C must use at most 0.5 times A’s tokens per correct job and 0.9 times A’s makespan. Report cold makespan without gating.

BoolQ C must add no gold errors relative to A and add at most 10% cold token and makespan overhead. Codex cold C must outperform B in tokens without worse correctness or makespan for the pooling contribution claim.

Only all gates permit the signed record’s cross backend headline, updated to identify this replication and its independent workloads.

**A4.11. Pilot magnitude and verdicts.** Replication of the reported Codex warm magnitude requires equal correctness, all 256 jobs resolved in both arms, certified accounting, and unrounded A/C ratios of at least 4.4 for tokens per correct job and 1.6 for makespan. Report actual ratios. This is replication on new operations, not an exact workload rerun.

An accepted incorrect rule answer kills safety. Leakage or failed accounting invalidates affected efficiency evidence. A completed valid comparison missing a performance gate fails that gate. Missing jobs, uncertified usage or interruption make the affected comparison inconclusive. Never extrapolate unfinished cells.

**A4.12. Operational stops.** Retain quota reservations, the 99% Claude handoff and Codex stop at primary usage of at least 80%. The owner’s suspension of the 55% guard lasts through the replication report. Report preparation, warm increments and cumulative costs separately. No cap exhaustion may be described as successful completion.

**Open for Opus**

1. Authoritative cache semantics available for the frozen Codex route.
2. Scheduler validation of the conservative call bounds.
3. Independent expressibility review without reference ASTs.
4. Preparation call reconciliation before freeze.
5. Agreement on magnitude replication versus the broader headline.