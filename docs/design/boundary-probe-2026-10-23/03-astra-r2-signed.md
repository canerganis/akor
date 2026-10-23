**I sign the all-stale design.** I withdraw rev-1 as the sole packet and reject the mixed compromise because four decision-bearing calls per arm weaken an already small probe. Stale is the better diagnostic target given the supplied observations. However, 2/2 failures do not establish a failure probability of at least 0.5. Both probability arguments are conditional illustrations, not power estimates.

I accept the additions:

- **Contrast floor:** A must fail on at least 3/6 calls, with the original boundary-error requirement retained. Zero boundary errors means “not reproduced”; reproduced errors below the floor mean “insufficient contrast.” An eligible candidate must be fully correct on 6/6 calls. Keep the original tie-break.
- **Fisher tests:** report two-sided B versus A and C versus A tests descriptively, without significance or efficacy claims.
- **Thinking and cache:** report per-arm thinking distributions, unknowns explicitly, and per-call cache reads/writes. Preserve the fixed thinking-stratum interpretation. Any shift in thinking is an association, not evidence of mediation.
- **Constants:** accept hard-coded limits for this diagnostic. A goal-referencing version requires separate qualification.
- **Denominator:** accept the supplied audit’s correction: three failing calls containing four wrong member answers; seven fully correct calls.

**Final signed plan:** exact stale control `48ecc5b0`; unchanged B operation; unchanged C operation and job block with the supplied checked stale intervals. Expected labels: `outside, outside, inside, unknown`. Six calls per arm in `ABC BCA CAB ACB CBA BAC` order, using the stated pinned route, unchanged H, parser, fixtures, independent scorer, regression checks, C two-ref check, and pre-run freeze.

Retain the 60k-token ceiling, 18-launch maximum, 5k pre-call reservation, 300-second call limit, and two-hour limit. Reservations are sequential, not a guarantee that all 18 calls fit. Any incomplete arm prevents selection; no retries, replacements, or extension.

Claim ceiling: “No classification failures were observed in six repetitions of this frozen packet.” No result changes G3, G3b, O1, H, or qualification.
