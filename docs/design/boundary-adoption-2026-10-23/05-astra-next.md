**Astra’s decision: move step 4 classification to a registered host operation. Allocate zero new paid calls now.**

1. **Preserve the failed result.** Attempt 1 stays closed: size 4 failed, size 1 untested, suite not run, adoption not passed. No rerun or retrospective pass.

2. **Version the workflow change.** Compute `inside` exactly when `lower_limit <= interval_low` and `interval_high <= upper_limit`, using Decimal and the current checked interval. Preserve unknown handling, input validation, freshness and goal-limit dependencies. Verify equality at both boundaries, breaches, changed limits, stale inputs and independent oracle agreement. Host migration does not itself complete step 4.

3. **Language guidance:** default to host execution when a registered total function already computes the answer from available inputs. Require an explicit experimental reason to retain such a model operation. Feed checked intermediates forward where model interpretation remains necessary, but describe this as input discipline, not a reliability guarantee. No wire change is needed.

4. **Evidence wording:** zero thinking is associated with the observed failures; causation is unestablished, and nonzero thinking is not a correctness certificate. Preserve boundary, label and composition coverage requirements. Avoid “host means zero error”; implementation and dependency correctness still require verification.

Close this adoption attempt, leave the broader model-capability question unresolved, and spend the remaining quota elsewhere. Any later model experiment needs a distinct hypothesis, new preregistration, explicit allocation and the 49% stop line. This is my decision for comparison with Opus, not a claim of joint agreement.
