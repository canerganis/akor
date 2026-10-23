**Astra preregistration: step 3, cheaper worker on O1**

1. **Worker and cells.** Test only `claude-haiku-5-5`, default effort, through `claude -p`, CLI 2.1.306. O1 packet sizes **4 and 1 remain experimental**. Haiku’s materials gates at 1/4/16 justify trying it, not transferring qualification. Its long OZ/1g thinking makes lower total cost a hypothesis.

2. **Freeze.** Preserve O1 freeze `32333561`, tickets, graph, wire, selective profile, evaluator, recovery rules and deadlines. Record a derived freeze changing only the worker route, with a reviewed diff and passing zero-call dry gates before paid execution. Use a fresh workspace and memo namespace. No effort tuning, model fallback or reply repair.

3. **Comparison.** Run the same complete five-scenario suite against the archived Sonnet O1 control: **all five passed, 55,413 billed tokens, 190 seconds**. Before launch, confirm matching executor, CLI, configuration and accounting scope except the model route. If unmatched, defer and preregister a matched Sonnet rerun before either new arm runs. Do not choose the control after seeing Haiku.

4. **Decision gate.** First require unchanged `pass_g3c` on every scenario: on-time A/I/H-verified deliveries, correct revisions, byte provenance, exact recovery/memo traces and complete accounting within allocation. Only then compare **whole-suite billed tokens, then elapsed time**. Haiku earns the O1 worker place if it passes and uses fewer tokens; equal tokens require lower elapsed time. Report any latency regression. Lower model pricing alone does not pass this gate.

   Count whole-call `modelUsage`, including cache components, reasoning once, failures and retries. Include caller and attributable orchestration wherever present, without double counting covered workers. This O1 comparison has no model caller, so it cannot establish savings over a caller doing the work itself.

5. **Allocation.** One Haiku suite today, no discretionary reruns or additional models: **150,000 tokens, 18 launches maximum, eight per scenario, one call in flight**. Preserve 300 seconds per call, 3,600 seconds per scenario and the four-hour envelope. Eight launches is the failure-free schedule, not a guarantee. Retain the frozen admission reserve, explicitly acknowledging that it is not an enforced billing ceiling.

6. **Stops and claim.** Starting quota is the supplied **42%**. Check quota before each launch and after settlement; all Claude preparation/review calls count. Stop new calls at **46%**, hard stop at **49%**; unavailable quota visibility blocks admission. Stop on freeze drift, unknown billing, exhausted allocation or an unrecoverable gate failure. Preserve evidence; never reset budgets or deadlines. A quota-stopped suite is incomplete, not a pass.

A successful comparison supports only this frozen O1 use case. It does not qualify general coding reliability or promote experimental packet cells automatically.

**No paid calls made. This preregistration must be recorded before execution.**


