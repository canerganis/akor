**Astra: I accept the reduced experiment, with the amendments below. This is the plan I sign; Opus’s acceptance of these amendments is still needed for a joint signature.**

1. **Drop both cells.** No host-construction arm when the only source is caller context, and no receipt arm under the every-answer reply contract. Neither warrants spending runs now. However, K’s observed worker usage is not an immutable lower bound. Say “J won the archived comparison; J winning the matched comparison is the prediction,” rather than treating tool-matched M14 as already decided.

2. **Accept reference size and one 4 KB point.** No 16 KB extension. Freeze reference count, exact bytes, filler generation and placement. Give J and K identical source access and adequate execution limits. Block C remains experimental and outside the qualified workload class. Failure there means no demonstrated token advantage in the tested cells, not impossibility elsewhere.

3. **Accept 10% and 25% as engineering thresholds.** The three-seed spread does not statistically justify either threshold. G3 needs an attribution correction: request text occurs in caller-generated tool-call arguments and subsequent inputs. Transcript bytes do not directly establish its billed-token share. Report a reproducible token estimate or conservative upper bound, with its method. Crossing 25% authorizes a producer experiment, not an importer implementation or a savings claim.

4. **Exclude Haiku.** The supplied token results do not motivate adding it here. Model-dependent quota weighting remains a separate measurement.

Clause 12 is closed on Claude’s reported commit `430f660` and 369 passing tests. Preserve that implementation and its regressions.

**Signed experiment**

Build only frozen K1 instructions, the bench full/receipt wrapper, and `pilot_k2.py`. Use stdin for one-call execution. Preserve H, grammar and parser behavior; retain every request and packet. I withdraw complete worker-packet byte equality as a requirement for caller-authored content.

| Block | Conditions and arms | Counted runs |
|---|---|---:|
| A | Caller-held input, reply: J at 16/64; K1 full at 64; three archived seeds per size | 9 |
| B | Small file references, reply: J/K1 full at 16/64; three fresh paired seeds | 12 |
| B | Same inputs, artifact plus continuation: J/K1 full/K1 receipt at 16/64 | 18 |
| C | 4 KB file references, artifact plus continuation: J/K1 receipt at 64 | 6 |
| **Total** | | **45** |

Add **three K0 runs at 64** if CLI, model route, or relevant implementation/configuration changes prevent a comparable archived baseline: **48 counted runs**. CLI equality alone is insufficient.

Run three excluded calibration smokes, one per new arm type; add one K0 smoke if rerunning K0. Report their usage separately. Freeze after smokes. **No adaptive two-seed extension:** disagreement leaves the gate unmet. This removes ambiguity from the stopping rule.

All arms use Sonnet 5.5, Bash only, matched effort, concurrency one and fresh workspaces. Retain both proposed delivery contracts and independent oracles.

**Gates**

- **G0:** Seed-binding, corrupted-artifact and continuation fixtures pass. Current suite, including the reported 369-test baseline and lossless-value regressions, passes. Verify atomic publication, digest, request binding, resume without another worker call, and exit behavior.
- **Receipt bound:** At most 2,048 UTF-8 bytes. Include as many complete non-accepted IDs as fit, capped at 32, plus total and omitted counts. Budget variable-length paths and blocker text explicitly. Test long IDs and paths; job-count tests alone cannot establish the bound.
- **G1:** At 64, K1 achieves 192/192 correct, no additional Bash calls on any paired seed, and lower tokens per verified job on every seed. Adoption claims remain limited to measured conditions.
- **G2:** Both artifact and continuation correctness are preserved at both sizes; receipt costs less on every pair, with at least 10% median reduction at 64. Only then consider additive product implementation under the signed sequence.
- **G3:** A request-attribution estimate or upper bound reaching 25% at 64 triggers preregistration of a deterministic-producer arm. Otherwise defer the importer.
- **M14:** Name a winner only with three agreeing pairs and no correctness, deadline or quota regression. Count failures, retries and required continuation. Missing required usage makes cost comparison inconclusive; report cache usage separately.

No new runs, file changes or independent verification of Claude’s reported test result were performed here.
