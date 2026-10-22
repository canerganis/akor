**Astra, round 1 — AKOR should become a runtime that turns requested work into verified results with as few model calls as possible.** OZ should remain its compact execution language. The next major gain should come from deciding what needs inference, preserving completed work, and scheduling the remaining inference well.

I take your supplied snapshot as the baseline. Estimates below are hypotheses or conditional calculations, not measured improvements. Older AKOR notes inform the regression cautions only.

1. **Measure complete workflows under deadlines.**

   **Mechanism:** Extend the ledger into a comparison harness with fixed requested deliverables, independent verifiers, deadlines, and quota observations. Compare the previous committed version against each candidate. Separately retain batched plain JSON and one-call-per-job JSON as attribution controls.

   **Expected effect:** No direct execution saving. Its value is preventing optimization of the wrong workload: the current **30.8–42.8% Claude savings** establish a batch-extraction result, while the central question is now dependent work.

   **Cheapest decisive test:** Add one recorded 20-step workflow and a small log-triage fixture. Run a capped paired pilot before expanding across models. Record completed deliverables, total tokens, calls, retries, and elapsed time.

   **Main risk:** Inflating success by splitting work into easy internal steps. Freeze the requested outcomes beforehand; twenty execution steps do not automatically count as twenty useful jobs.

2. **Accept valid jobs independently, with strict validation and selective retries.**

   **Mechanism:** Separate record parsing, semantic verification, and durable acceptance. Scan the complete reply before committing results so duplicate IDs cannot overwrite earlier records. Retry only unresolved jobs. Keep bad headers or unresolvable attribution as whole-reply failures; never repair malformed text silently. Fence late attempts and use idempotency keys for effects.

   **Expected effect:** In the supplied **91/91 accepted Claude replies**, the observed opportunity is zero. Under a fault affecting one of 64 jobs, selective retry eliminates **63/64 repeated job executions**, though the retry’s fixed CLI overhead remains.

   **Cheapest decisive test:** Inject malformed records, duplicates, truncation, and late replies into recorded responses. Demonstrate that independently valid results survive and effects are not duplicated.

   **Main risk:** Confusing parse validity with correctness, or claiming exactly-once external execution. This is foundational reliability work, not an immediate 98% total-token saving.

3. **Offer a more explicit wire profile where compression impairs comprehension.**

   **Mechanism:** Test a uniform object reply:

   `{"id":"w","value":...}` or `{"id":"w","error":[code,message]}`

   Independently test explicit reference labels against positional indices. Keep each invocation on one declared profile, selected by the host from qualification evidence.

   **Expected effect:** I expect little benefit—and some token increase—on already reliable Claude configurations. The opportunity is recovering Codex correctness from **1/10**. Uniform objects directly address the mixed-shape fork; they do not inherently solve index drift or broken framing. I would tolerate several hundred extra tokens per 64-job call if correctness improves, especially against the supplied **~24.5k fixed input overhead**.

   **Cheapest decisive test:** Change reply shape alone and rerun the ten failed-suite cases with an early stop. Test addressing only afterward.

   **Main risk:** Multiplying dialects without proving which failure each solves.

4. **Make verified reuse and deterministic execution the first routing decision.**

   **Mechanism:** Before invoking a model, check whether an existing host operation or a previously verified result can satisfy the request. Memo keys include operation version, input hashes, relevant environment state, and verifier version. Distinguish “previously generated” from “still valid.”

   **Expected effect:** If 20% of otherwise equal-cost calls are safely eliminated, inference token use falls approximately 20%, before lookup and revalidation costs. Savings are smaller when hits merely remove jobs from a batch without eliminating calls. Existing read/test/status execution earns no new credit.

   **Cheapest decisive test:** Replay a real workflow twice, then mutate one source and one dependency. Measure reuse and confirm that precisely the affected results become ineligible.

   **Main risk:** A fast stale answer. Mutable external state requires explicit freshness rules; a content hash alone is insufficient.

5. **Build the resumable DAG executor before optimizing planner syntax.**

   **Mechanism:** Start with a host-validated, versioned plan containing operations, dependencies, typed result references, verification requirements, and budgets. Implement checkpoints and dependency invalidation. First execute a manually authored plan; then let a planner produce the same structure. Permit one bounded replan initially, affecting only the unfinished or invalidated portion. The planner cannot weaken the requested acceptance criteria.

   **Expected effect:** A healthy, strictly sequential workflow may save **approximately zero tokens** merely by becoming a DAG. The gain is reliable completion, reuse, and exposing parallel work. Do not count leases and inbox resume again: those already exist.

   **Cheapest decisive test:** Record the owner-required **20-step real workflow**, such as diagnosing and fixing defects in a small repository against frozen independent tests. Interrupt it, change a dependency, and force one replan.

   **Main risk:** Building a general workflow platform before demonstrating one useful workflow. The first plan format can be ordinary JSON; compact it after measuring its contribution.

6. **Schedule compatible work across workflows, with deadline-aware batching.**

   **Mechanism:** Batch ready jobs from multiple workflows within the same authorized context. Account for remaining deadline, downstream work, batch failure history, and model compatibility. Dispatch critical-path jobs promptly; wait only when doing so can plausibly improve completed work.

   **Expected effect:** Consolidating eight eligible Claude calls into two removes roughly **6 × 950 = 5,700 fixed CLI tokens**, before changes in payload and reasoning. That is an illustrative bound, not an incremental claim over today’s quorum batching. Truly sequential chains may gain nothing.

   **Cheapest decisive test:** Replay an arrival trace mixing short chains and independent jobs. Compare the existing `--min-batch/--max-wait` policy with the candidate under the same deadline.

   **Main risk:** Saving tokens while reducing completed work through waiting, oversized batches, or starvation. The primary score must override the temptation to fill batches.

7. **Optimize model effort and answer requirements as carefully as input size.**

   **Mechanism:** Qualify operation-specific combinations of model, supported effort setting, and required output. Request only information the consumer needs, including necessary evidence. Route from measured correctness and cost; escalate failed verification within a fixed budget.

   **Expected effect:** The supplied Haiku result contains about **6,000 thinking tokens per call**. If a qualified configuration halved that without hurting correctness, it would save approximately **47 tokens/job at 64 jobs**, about one-third of its reported 142.1 tokens/job. This is conditional arithmetic, not evidence that effort can safely be halved. Existing Opus results already show why model size is a poor efficiency proxy here.

   **Cheapest decisive test:** One paired configuration change on the existing oracle suite, followed by a small held-out task set. Count escalation calls.

   **Main risk:** Repeating the Luna outcome: cheap-looking output with inadequate reasoning. Shorter visible answers do not establish lower hidden reasoning.

8. **Send source projections, with explicit requests for missing context.**

   **Mechanism:** Let operations declare required fields or source regions. The host supplies those projections with source hashes and locators. A model can request specified missing context, subject to a bounded expansion policy.

   **Expected effect:** If removable source material represents 40% of total tokens and projection removes half, the ceiling is **20% total-token saving before expansion costs**. It may save virtually nothing on the existing compact extraction fixtures. Expansion is worthwhile only when expected avoided input exceeds the extra call and reasoning cost.

   **Cheapest decisive test:** Use log-triage cases containing much irrelevant material, plus cases where the decisive clue lies outside the initial projection. Measure both savings and missed evidence.

   **Main risk:** Confident conclusions from incomplete context. Keep broad-context controls and require locatable evidence.

9. **Treat caching as a measured execution property.**

   **Mechanism:** Stabilize protocol instructions and reusable operation definitions ahead of changing job data. Compare supported fresh and resumed CLI execution where useful, accounting for growing history and resets. Inspect actual cache-read and cache-write fields.

   **Expected effect:** My initial estimate is **zero incremental benefit until the ledger establishes an avoidable cache miss**. Caching can reduce processing cost and latency without reducing the number of input tokens represented in usage. Anthropic documents prefix reuse and separate cache accounting, but those API mechanics do not establish this subscription’s quota savings. [Prompt-caching documentation](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

   **Cheapest decisive test:** A short repeated-call probe using a stable prefix, then a deliberately changed prefix, through `claude -p`.

   **Main risk:** Assuming “teach once” means permanent free knowledge, or treating cache-price discounts as raw token reductions. Resuming Codex also does not automatically remove its reported fixed context cost.

10. **Make one existing agent workflow adopt AKOR with minimal changes.**

   **Mechanism:** Provide a thin integration exposing submit, await, and retrieve-evidence operations, backed by the existing CLI/Python surface. Ship one complete example—log triage or repository maintenance—with reproducible inputs, an independent verifier, and a ledger. Start with a Claude Code skill or small wrapper; add MCP when an actual integration requires it.

   **Expected effect:** The wrapper alone should save **approximately zero inference tokens**. Its value is exposing real ready-job queues and eliminating repeated orchestration work. A reasonable adoption target is a first verified workflow within fifteen minutes, without API credentials.

   **Cheapest decisive test:** Run the example from a clean project and compare it with its original orchestration script, including setup and prompt overhead.

   **Main risk:** Adding tool schemas and instructions that cost more than the integration saves. A portfolio demo must expose failure and recovery, not just a successful screenshot.

11. **Compile recurring workflows into versioned recipes.**

   **Mechanism:** After a workflow proves useful, preserve its validated plan as a parameterized recipe. Later invocations bind new inputs and check preconditions; planning happens again only when those preconditions fail. The host expands the recipe into ordinary DAG operations, so the model need not repeatedly interpret another compact language.

   **Expected effect:** Potentially **one planning call eliminated per subsequent eligible workflow**. If recipe qualification costs \(S\) additional tokens and each use saves \(P\), strict token break-even occurs after more than \(S/P\) uses. It offers little value for unique tasks.

   **Cheapest decisive test:** Run the same maintenance workflow on five different input sets, including one that violates a recipe precondition. Compare repeated planning with recipe execution.

   **Main risk:** Freezing an accidental assumption into automation. Version the recipe, verify its outputs, and invalidate it when operation semantics change.

**My top three, ranked by expected strategic value:**

1. **The resumable DAG executor, idea 5.** This closes the largest owner-approved gap and makes AKOR useful on dependent work. Its first deliverable is the recorded 20-step workflow, not a sophisticated planner.
2. **Deadline-aware scheduling, idea 6.** It attacks the fixed-call overhead exposed by the supplied measurements and can turn naturally small requests into economical batches.
3. **Qualified effort and output optimization, idea 7.** It targets the cost component that packet compression demonstrably does not control.

Selective acceptance is a prerequisite despite ranking below these in immediate measured upside. Verified memoization should follow the first working DAG closely.

**I would implement in this order:**

- Establish the workflow scorecard and pin the previous committed baseline.
- Add selective acceptance, attempt fencing, and idempotent retry behavior.
- Complete one manually planned 20-step DAG with checkpoints and independent verification.
- Add verified memoization and compare scheduling policies.
- Introduce bounded planning/replanning; test effort optimization in a small separate experiment.
- Package the winning workflow for adoption. Promote wire changes, projections, caching changes, and recipes only when their own tests justify them.

For every experiment, use the owner’s ordering literally: **more independently correct requested work before the deadline; then fewer total tokens; then less time.** Preserve the supplied 337-test baseline and add focused checks for new semantics. Keep separate workload results so an extraction win cannot conceal a workflow regression.

Charge bootstrap instructions, planning, verification calls, failures, retries, and observable reasoning exactly once. Report unavailable usage fields as unknown. If additional teaching costs \(S\) and steady-state savings are \(\Delta>0\) tokens per equally verified job, the first strictly cheaper job count is:

\[
N_{\text{break-even}}=\left\lfloor S/\Delta\right\rfloor+1
\]

Reset that calculation when context must be taught again. If \(\Delta\leq0\), there is no token break-even. Report quota observations separately rather than inventing a token-to-subscription conversion.

**I would deliberately not:**

- Replace the successful Claude wire wholesale to rescue one failing Codex configuration.
- Add clever compression syntax before proving comprehension and total-cost gains.
- Skip independent verification or use sampled checks to inflate “verified jobs.”
- Run speculative model branches, repeated debates, or broad model sweeps without a demonstrated completion benefit.
- Build direct API adapters, a generic framework suite, or a hosted platform.
- Pursue stars through broader claims before demonstrating one reproducible workflow that survives interruption and still finishes correctly.


