I sign the revised O1 plan with all four material amendments accepted, plus M6. Three technical corrections must enter the freeze.

1. **M1: Accept.** Preserve candidate bytes and evaluator separation. Document why each defect requires semantic repair; do not claim to prove that no conceivable substitution could repair it.
2. **M2: Accept three tiers.** H decides correctness. **Correction:** freeze explicit domain definitions and cardinalities, then measure their runtime. The illustrative exhaustive domains cannot be assumed to run in milliseconds. Reference disagreement blocks the freeze.
3. **M3: Accept deterministic, type-strict comparison and edge semantics.** **Correction:** `-I` and `-E` ignore `PYTHONHASHSEED`, and an empty environment cannot supply it. Use a controlled launcher that honors seeds 0 and 1 while preserving confinement. G2 must verify this. Reject unsupported output types before JSON serialization, which would otherwise normalize tuples.
4. **M4: Accept.** Adapter acceptance integration uses only core inputs covered by that revision’s A tier. H evaluates adapters with both reference and accepted cores; report these separately.
5. **M5: Accept all coverage pins.** Each seeded defect must fail A.
6. **M6: Accept bare strings.** **Correction:** 4,200 serialized bytes do not safely accommodate 4,096 source bytes after escaping. Enforce 4,096 UTF-8 bytes on the decoded source separately from the existing wire limit.
7. **M7: Accept**, with M3’s launcher correction. Preserve confinement before candidate delivery, the escape fixtures, and `Unavailable` without consuming a model attempt. Measure tier workloads before asserting that the two-second limit has sufficient margin.
8. **M8: Accept 150k tokens, 18 launches, at most eight per scenario.** Measure reserves at G2. Admission must cover the enforced billable completion limit, including reasoning tokens. These ceilings bound spending; they do not guarantee every possible recovery fits. Shrink tickets before freezing if the specified failure-free estimate exceeds 100k.
9. **M9: Accept.** Set `experimental_sizes=(4, 1)` and verify every dispatch label. No qualification transfers or results from this gate.
10. **M10: Accept.** A valid model failure record is terminal, receives no resend, and fails the target.
11. **M11: Accept.** Minimal job records, accepted core bytes forwarded, frozen header validation.
12. **M12: Accept.** Report eight model jobs and twelve host steps, including five context-assembly or join steps.

**Final signed plan:** retain the four tickets, twenty-node graph, five scenarios, recovery rules, deadlines, route pins, prospective freeze, and G3b predicate fixes. No baseline and no reruns. Pass requires G0 through G2, complete usage accounting within the caps, all five deliveries passing A/I/H, candidate-byte provenance, correct revisions, and exact independently derived traces including memo hits. Report correctness before cost, candidate check errors, wire failures, and reasoning usage with missing values marked unknown.

No remaining disagreement on M2, M4, M8, M9 or M6. The runtime, launcher, and byte-limit corrections above are conditions of my signature.
