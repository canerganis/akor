# Step 3 result: Haiku 5.5 passes every scenario but does not earn the worker place

Derived freeze dd6bf974 (route changed to `claude-haiku-5-5`, owner budget amendment recorded before launch), fresh
workspace, one suite. Weekly quota 46% before and after. Evidence: `bench/o1/live-haiku1/`.

| repair-handoff-20/v1 | Scenarios passing pass_g3c | Launches | Billed tokens | Elapsed | Thinking per size-4 call |
|---|---:|---:|---:|---:|---|
| Sonnet 5.5 (archived control, matches on all 12 checks) | 5/5 | 8 | 55,413 | 190 s | 584 to 1,186 |
| Haiku 5.5 | 5/5 | 8 | **94,319** | **303 s** | **5,869 to 7,968** |

Haiku wrote every function correctly on its first attempt: no resend, every delivery verified on the A, I and H tiers.
But the preregistered gate asks a cheaper worker to pass and then use fewer whole-suite billed tokens. Haiku used 70%
more tokens and 60% more time, almost all of it hidden reasoning (six to seven times Sonnet's per call). Verdict:
**Haiku does not earn the O1 worker place**; Sonnet stays. Lower per-token pricing is outside this metric and the gate
said so in advance.

Consistent with every earlier measurement in this repo: Haiku 5.5 reasons at length by default (step 1g: about 6,000
output tokens per 64-job packet), so on the token metric it is not the cheaper model. One suite per arm; the
comparison holds for these two suites only.
