**amendment 3**

**1. Owner decisions accepted.** The owner decisions supersede conflicting provisions in signed section 4 and amendment 2.

The Claude 55% weekly launch guard is suspended for the oz map build and kill pilot, ending when the pilot report is written. The 99% quota handoff rule and `oz_quota` reservation discipline remain binding. This exception does not remove physical call caps.

The freeze MUST record:

| Backend | Telemetry | Bootstraps | A | B residuals | C residuals | Reserve | Total |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Codex | 1 | 2 | 12 | 8 | 7 | 7 | 37 |
| Sonnet | 0 | 1 | 8 | 4 | 2 | 2 | 17 |
| Global | 1 | 3 | 20 | 12 | 9 | 9 | 54 |

Codex’s second telemetry invocation consumes one of its seven reserve calls, leaving six for other reserve purposes. Sonnet B has four dedicated calls; it MUST NOT consume the two reserve calls as its nominal allocation.

Audits, overflow, additional telemetry, preparation and permitted infrastructure retries consume the applicable reserves. Reserve before every launch. Exhaustion leaves evidence incomplete; it does not authorize omitted cells or exceeding a cap.

**2. BoolQ ruling: retain the gate and accept the projected failure.**

The serial bootstrap is a real latency cost of attempting learning before refusing rules. Makespan measures that intended overhead. Structural difficulty satisfying the threshold is not a measurement defect. Replacing makespan with summed call seconds, or removing its threshold, would change the acceptance criterion to accommodate the architecture.

Exact freeze text:

> On the frozen Codex BoolQ cold evaluation, C MUST have no more gold errors than A, consume at most 1.10 times A’s total charged tokens, and have at most 1.10 times A’s measured makespan. C’s accounting MUST include the complete shared bootstrap charge and all required residual work. Makespan MUST include required admission, checking, queueing and completion costs. No bootstrap subtraction, floor adjustment or substitution of summed physical call seconds is permitted.

Record the supplied replay projections of approximately 1.04 for tokens and 4.8 for makespan, with approximately 2 under the uninflated bootstrap assumption. These establish projected failure under those timing assumptions, not a measured live failure or a universal bound across possible call durations.

Summed physical call seconds MAY be reported separately. They cannot rescue this gate. If live BoolQ fails, the signed “all gates pass” headline remains unavailable.

**3. Materials warm ruling: retain the signed gate.**

Exact freeze text:

> For each backend independently, warm C MUST preserve correctness, have measured makespan at most 0.90 times matched warm A, and consume at most 0.50 times A’s tokens per gold correct job. Score actual live measurements using the frozen timing boundaries and accounting rules.

Charging every replayed call the duration of a 64 job call cannot resolve the benefit of smaller warm calls. The projected 0.95 and 1.0 ratios therefore do not establish architectural impossibility. The approximately 0.54 scaling scenario is sensitivity analysis, not validation. Neither projection changes the thresholds.

**4. Additional freeze requirements.**

Record this amendment’s precedence and hash, the owner decisions, revised allocations, unchanged full matrix, and explicit timing boundaries. Update stale planner assumptions that assign Sonnet B to reserves or enforce the 55% guard.

Count a shared bootstrap once physically while charging its full cost to each applicable B and C comparison. Keep measured makespan, replay projections and summed call seconds distinct.

Preserve the dry run’s source records and assumptions, including its estimated bootstrap and use of materials usage samples for BoolQ. Preserve every failed gate. Safety, validity, pooling, the no revision rule and remaining claim restrictions are unchanged.

