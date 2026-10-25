**A4.14.2 blocker P3 H1**

Concrete failure scenario: Supply an otherwise valid owner reading with percent `79`, event timestamp five minutes before the gate, and `session_started_at` thirty minutes after the gate. Set `cap=62`, `charged=61`, with all 61 attempts ending after the reading but before the claimed session start. `unreflected_allowance` subtracts all 61 calls, yielding `C=1`. The gate accepts because `79 + 2 × 1 × 0.21 = 79.42`. Consumption after the reading is omitted. If actual usage has reached `79.9`, another call consuming `0.21` crosses 80.

Evidence: `owner_problem` validates the reading timestamp but never the session timestamp used to reduce C. `unreflected_allowance` trusts that session timestamp without checking its chronology. `headroom_gate` treats the D5 result as informational and retains only `uncovered`, discarding any rejection. The supplied tests do not exercise an invalid session floor through the headroom gate.

**A4.14.2 blocker P3 H2**

Concrete failure scenario: With a valid owner reading of `10`, `remaining_calls=62`, and `m=0.21`, supply `harvested={'a': [None]}`. The malformed harvested observation is silently discarded and dispatch passes with bound `36.04`.

Evidence: `headroom_gate` filters observations using `if isinstance(o, dict)` before validation. Consequently, malformed observations that are not dictionaries never trigger rejection. This contradicts the manifest requirement that a malformed latest reading blocks. The supplied malformed observation test covers only a dictionary containing `percent=True`, so it misses this acceptance path.