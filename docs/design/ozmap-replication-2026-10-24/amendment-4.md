# Amendment 4: clean replication (final, signed by Astra A, 2026-10-24)

Round 3: Astra A revision after Opus B blocker S3 (authentication refresh on token age, not per call, on codex-cli 0.160.0). gpt-6-astra, effort high, codex-cli 0.160.0. Unedited output below. Astra integrated all S3 replacements verbatim; a diff against round 2 shows only those replacements plus a new S3 disposition entry, which the driver requested as part of the output format. Opus B signature pending. Driver note: this revision was one more Astra call, so the Astra preparation count stated in A4.5 (2, written before round 2) is now 4, leaving 0 of the cap of 4. Any further Astra preparation call needs a prospective signed revision.

**A4.1. Scope and precedence.** This amendment governs a new replication and supersedes conflicting isolation, budget, bootstrap validity, cache certification and workload provisions in the signed record and signoffs. Other provisions remain unchanged. The pilot remains invalid. Freeze amendments, manifests, classifications, accounting predicates and executable checks before evaluation calls. Preserve every attempt and failure. Signing approves this protocol, not satisfaction of its execution prerequisites.

**A4.2. Codex isolation and authentication.** Use four numbered worker `CODEX_HOME` directories and corresponding empty working directories. Reconstruct each worker home before each call from an authentication only baseline. Never copy the owner’s home wholesale. Exclude plugins, skills, memories, histories, sessions, hooks, `AGENTS.md`, user configuration and instruction files. Inventory generated runtime files, propagate authentication changes securely, then remove runtime state before reuse. Keep evidence outside model accessible directories.

Seed the baseline with an owner performed `codex login` while `CODEX_HOME` points at the baseline, so it shares no refresh token with the owner’s home or the running Codex app. Never seed it by copying the owner’s `auth.json`. Restrict use of this authentication lineage to the replication workers and its serialized telemetry refresh calls.

The pinned CLI refreshes ChatGPT authentication on token age, not per call: on codex-cli 0.160.0 the owner's home kept last_refresh 2026-10-15T18:40Z through more than 200 sessions over nine days, with a ten day access token lifetime. A telemetry call therefore cannot be relied on to refresh. At the start of each wave, read the exp claim of the baseline access token locally and log only the timestamp. A wave launches only when exp is at least 48 hours away. Otherwise the owner performs a fresh `codex login` with `CODEX_HOME` pointing at the baseline. This reseeds the baseline under a new lineage and is not a restore. Record the new auth.json hash, last_refresh and exp before considering the wave for launch. A missing or unreadable exp prevents launch. No model call is made to force a refresh.

No telemetry call is spent on authentication refresh. The four Codex telemetry calls in A4.5 remain available for the checks in this clause and for other telemetry.

Calls run concurrently on the frozen four host slots, one worker home per slot. For evaluation calls, the authentication lock covers reconstruction and propagation, not execution. A concurrent wave launches only under the exp gate above, so no worker is expected to refresh mid wave.

After every call, including failures, compare worker and baseline `auth.json` hashes. Log hashes only. If a worker’s `auth.json` hash differs from the baseline after a call, launch nothing further until every in flight call has ended. Keep the baseline unchanged while those calls finish and inspect every worker’s authentication result. If exactly one worker changed and no call reported an authentication failure, propagate its authentication under the lock before another reconstruction, then resume subject to the launch prerequisites. Otherwise stop Codex evaluation, preserve every record and treat affected cells as interrupted under A4.11. An authentication failure without a changed worker also stops Codex evaluation under the same disposition. Never restore an older token snapshot.

Telemetry must establish that the pinned CLI reads authentication from `CODEX_HOME`, not an OS credential store, and that its read only sandbox starts with clean home state. Failure of either check stops evaluation.

Freeze an allowlisted environment and accepted arguments:

`exec --ignore-user-config --ignore-rules --ephemeral --skip-git-repo-check --json -s read-only -C <numbered empty dir>`

Add every available disable option for plugins, apps, memories, hooks, `multi_agent`, `skill_search`, `browser_use`, `computer_use`, `image_generation`, `view_image` and other tool features, plus `-c project_doc_max_bytes=0` if accepted. Record unsupported options.

Before each wave, record effective features using `codex features list` with the same home and applicable configuration arguments. Features that cannot be disabled, including observed `unified_exec`, do not block launch; A4.3 governs their events.

Before every call, verify baseline inventory, executable and argument hashes, environment, empty working directory and effective instruction sources, including ancestors. Mismatch prevents launch. If instruction discovery cannot be contained, use an isolated account or container. Clean homes and sandbox restrictions never excuse tool use.

**A4.3. Tool events and refusal.** Retain only the narrowly defined plain CLI notice exception from the telemetry notes. A tool request intercepted before execution is a refused call, consuming tokens, time and one call allowance; it does not establish an external read. Actual execution, an external read, or uncertainty whether execution occurred invalidates replication efficiency, even if every answer is refused.

No selective rerun erases failure. Existing infrastructure retry and answer repair restrictions remain.

**A4.4. Capacity formula.** Budget for zero admitted rules. Let \(N_p\) denote producer jobs, \(b_p\) bootstrap jobs, \(a\) maximum additional audit records, and \(M=64\). Reserve pooled nominal capacity

\[
\left\lceil\frac{\sum_p(N_p-b_p)+a}{M}\right\rceil
\]

and local fallback capacity

\[
\sum_p\left\lceil\frac{N_p-b_p+a}{M}\right\rceil.
\]

The local bound conservatively assigns the entire audit allowance to each producer; actual auditing remains 32 jobs per wave. Charge bootstrap separately. For A, \(b_p=a=0\).

Freeze synchronized submission and dispatch supporting full eligible batches. Before launch, exercise the actual scheduler with zero rules and worst permitted audit placement. If deadline flushing exceeds these bounds, revise and sign allocations before evaluation.

**A4.5. Physical call allocations and preparation.** Each materials backend receives nominal allocations: cold A 4, shared bootstrap 1, cold B 8, cold C 4, warm A 4, warm C 5; total 26.

Codex BoolQ receives cold A 4, shared bootstrap 1, B 4 and C 3; total 12. BoolQ has no rule audits. Each listed allocation receives two reserve calls. Shared bootstrap is one physical call, charged fully to both B and C analytically. Unused capacity cannot authorize new learning, repair or conditions.

Caps are:

1. Codex evaluation: 38 nominal, 4 telemetry, 20 reserve; total 62.
2. Sonnet evaluation: 26 nominal, 2 telemetry, 12 reserve; total 40.
3. Fable preparation: 4.
4. Astra preparation and review: 4.
5. Opus preparation and review: 4.
6. Global total: 114.

Reseeding the baseline by owner login makes no model request and consumes no call allowance.

A preparation call is one dispatched subagent or model calling CLI invocation. The driver session is excluded; report its quota separately. Local CLI commands making no model request consume no model call allowance.

Reconciled preparation counts, including this amendment, are Fable 1, Astra 2 and Opus 1, leaving 3, 2 and 3 respectively. Charge the fresh expressibility reviewer to Opus preparation. Record subsequent calls and obtain a prospective signed revision before exceeding any cap. Human coordination consumes no calls; dispatched model assisted coordination does.

**A4.6. Classification and bootstrap errors.** Before learner calls, independently classify each operation from its written contract against the frozen AST language. Record permitted inputs, outputs, guards, a specified domain and reasons a nontrivial input determined solution is expressible. Classification cannot depend on learner success. Let \(R\) contain materials operations classified as rule shaped; do not presume all four qualify.

A bootstrap gold error or matched A disagreement invalidates efficiency only for an operation in \(R\) for which the learner proposed a rule. Every other bootstrap error enters correctness and overhead measurements. Malformed or missing bootstrap output remains a completion failure.

BoolQ is outside \(R\); its checks cannot authorize adoption. Materials operations outside \(R\) are expected to remain model answered. Admission of a rule outside \(R\) is a classification miss, which must be reported without retrospectively changing \(R\). Safety rules still apply.

Evaluate A4.10 on the entire preregistered workload and report results per operation. If \(R\) is empty, materials efficiency is descriptive and no rule learning claim is permitted.

**A4.7. Cache and reasoning certification.** Use archived telemetry run 1, `live-6a518ece47ab`, with `gpt-6.1-sol`, high effort and CLI `0.160.0`, as the live inclusion certificate: both calls recorded input 29,694, with cached input 7,296 and zero. Its plain CLI notices fall under A4.3’s exception.

Before relying on this certificate, archive the pair, route identity and decoder source trace, and establish applicability to the frozen route. A route or decoder change requires renewed certification.

Replay fixtures through that decoder: total input 10,000 with cached input 4,000 must yield uncached input 6,000 and charged inclusive input 10,000; cached input zero must also yield 10,000. Freeze separate output and reasoning fixtures against double counting. Replay certifies arithmetic, not live semantics.

An alternative certificate requires an authoritative provider definition and exact decoder mapping establishing inclusion, together with replay. Repetition alone guarantees no live cache hit.

Every call must satisfy \(0\leq cached\leq input\). Positive cached input without applicable certification makes usage unverified and dependent token comparisons incomplete; execution may continue. Zero cached input needs no inclusion certificate. Preserve signoff 5’s per call reasoning certification and freeze its executable predicate. Report token gates under additive input accounting as a sensitivity check.

**A4.8. Independent operations and review.** Fable’s four existing, tested operations replace the original materials operations throughout bootstrap, admission, cold and warm evaluation. Preserve task counts and admission design. Their existing test results do not substitute for independent review.

Fable supplies contracts, executable gold oracles and generators. A fresh Opus reviewer, distinct from both signatories, the author and evaluated backends, validates oracle correctness and expressibility. It may produce a solution AST, sealed, hash committed and stored outside all learner accessible directories before learner calls. Astra remains blind to operation content until scoring.

Audit timestamped artifacts, access manifests, learner prompt hashes, isolation attestations and sealed reviewer artifacts. Independently checked admission labels and evaluation gold remain inaccessible to synthesis. Report convergence between reviewer and learner ASTs after scoring as an observation.

Claims may establish synthesis for independently authored operations from the frozen prompt, not novel reasoning, absence of training familiarity or general semantic correctness.

**A4.9. Sonnet.** Preserve Sonnet’s pilot prompt, complete cold A, B and C, and warm A and C. Add no exploratory prompt condition. Report `none` as an outcome; it never authorizes prompt changes after inspection.

**A4.10. Success and headlines.** Require complete cells, complete relevant usage, passed isolation and applicable bootstrap validity, and no safety kill.

For each backend, materials C must preserve correctness and reduce cold tokens per gold correct job by at least 25%. Warm C must use at most 0.5 times A’s tokens per correct job and 0.9 times A’s makespan. Report cold makespan without gating.

BoolQ C must add no gold errors relative to A and at most 10% cold token and makespan overhead. Codex cold C must beat B in tokens without worse correctness or makespan for a pooling contribution claim.

A backend meeting every applicable gate may claim its result for independently authored operations, provided \(R\) is nonempty for a rule learning claim. The cross backend headline requires every gate across both backends, including Codex BoolQ and pooling gates, and must identify this replication and its independent workloads.

**A4.11. Direction, magnitude and verdicts.** Compute magnitude on the preregistered jobs belonging to \(R\), with equal correctness, all those jobs resolved in both arms and certified accounting. Freeze attribution of shared costs and audits before evaluation; never omit costs merely because their answers are excluded from this subset.

Replication of direction requires A4.10’s warm gates on this subset. Report unrounded A/C ratios for tokens per gold correct job and makespan. Say “at least the pilot magnitude” only when these ratios reach 4.4 and 1.6 respectively. Otherwise say “smaller than the pilot”, explicitly identifying each missed threshold. Label all such claims as results on \(R\), using new operations; whole workload claims still require A4.10.

An accepted incorrect rule answer triggers the safety kill. Leakage or demonstrated accounting failure invalidates affected efficiency evidence. Missing jobs, uncertified usage or interruption make affected comparisons inconclusive. Completed valid comparisons missing performance thresholds fail those gates. Never extrapolate unfinished cells.

**A4.12. Operational stops and disposition.** Retain quota reservations, the 99% Claude handoff and Codex stop at primary usage of at least 80%. The owner’s suspension of the 55% guard lasts through the replication report. Report preparation, warm increments, cumulative costs and driver quota separately. Cap exhaustion is not completion.

All three prior blockers are incorporated. B4.3, B4.5, B4.8, B4.9 and B4.10 are accepted. B4.7 is accepted except that nonmodel CLI invocations are excluded because this budget counts physical model calls.

### Blocker disposition

**S1: Integrated.** A4.2 preserves concurrent execution on the frozen four host slots and limits the evaluation authentication lock to reconstruction and propagation. Unexpected authentication changes halt further launches until reconciliation, with ambiguous changes or authentication failures treated as interruptions under A4.11.

**S2: Integrated.** A4.2 requires a separate owner performed baseline login and gates each wave on at least 48 hours of remaining baseline access token lifetime, with reseeding by owner login otherwise. A4.2 and A4.5 explicitly cap telemetry refresh calls at four within the existing shared four call telemetry allocation, requiring a prospective signed revision before exceeding either limit.

**S3: Integrated.** All proposed replacements are incorporated verbatim. A4.2 gates wave launch on baseline access token expiry and permits reseeding by owner login when fewer than 48 hours remain. No model call is made to force authentication refresh, and owner login consumes no call allowance. These provisions supersede the retained S2 disposition sentence describing telemetry refresh caps. All other amendment text remains unchanged.

Signed: Astra A
