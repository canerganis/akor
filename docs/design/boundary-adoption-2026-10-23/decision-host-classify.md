# Decision after the failed qualification: classification becomes a host operation (Astra and Opus 5.5, 2026-10-23)

Rounds: [05 Astra](05-astra-next.md), [06 Opus](06-opus-next.md). Both decided independently and agree.

1. The adoption attempt stays closed as recorded: size-4 cell failed, size-1 untested, suite not run, not adopted.
2. Step 4 gets a new pack, `inspection-handoff-20/v3`, where the four classify nodes are host operations
   (`host.classify@1`): inside exactly when lower_limit <= interval_low and interval_high <= upper_limit, in Decimal,
   from node 11's checked interval and the structured goal limits; unknown stays unknown. The graph keeps 20 nodes;
   expected primary launches become 2, 0, 2, 4, 0. The gate is a zero-token dry gate; no paid suite now. v1's G3b live2
   pass stays the live evidence for v1; v2's records stay as they are.
3. Language and authoring guidance: when a registered total function computes a step exactly from checked values, the
   step is a host operation and is not sent to a model; keeping such a model operation needs an explicit experimental
   reason. "Feed a checked intermediate forward" is withdrawn as a reliability rule and kept as an observation (it
   fixed one packet and did not carry to a new goal). No wire change.
4. Evidence wording: Sonnet 5.5 at default effort misread inclusive-limit equality in 6 workflow and adoption calls
   (step 4 live1 2, live2 1, live3 2, adoption 1) and in 5 of the probe's 6 control calls, every one at zero hidden
   reasoning. Zero thinking is associated with these failures but does not by itself produce them (adoption calls 6 and
   8 were right at zero); causation is not established, and nonzero thinking is no correctness certificate.
5. No further paid model experiment on this question is scheduled; any later one needs its own hypothesis,
   preregistration, allocation and the 49% stop line.
