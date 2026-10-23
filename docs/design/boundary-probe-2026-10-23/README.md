# Boundary probe (Astra and Opus 5.5, 2026-10-23; approved by the owner)

Question: in step 4, Sonnet 5.5 misclassified inclusive-boundary intervals four times, always in calls with zero
hidden reasoning. Which of these removes the errors, and at what token cost: (A) the frozen size-4 classify packet,
(B) explicit inequality wording in the operation text, (C) B plus the host-checked interval passed as a ref?

Signed plan (round 03, accepting Opus's packet choice in round 02): every arm on the exact stale classify packet
(48ecc5b0, failed in both live runs), expected labels outside, outside, inside, unknown; six calls per arm in the order
ABC BCA CAB ACB CBA BAC; OZ/1g text H and parser unchanged; ceiling 60k tokens and 18 launches; no retries,
replacements or extensions. Contrast floor: A must fail on at least 3 of 6 calls, otherwise "not reproduced" or
"insufficient contrast" and nothing is selected. A candidate must be right on 6 of 6. Fisher tests, thinking-token
distributions and cache counters are reported descriptively. No result changes G3, G3b, O1, H or any qualification;
a goal-referencing version of a winning operation would need its own qualification.
Status: signed, not built.
