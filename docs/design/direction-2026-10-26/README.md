# Direction after the oz map replication (2026-10-26)

Owner goal: the fewest tokens for the most effective orchestration, as fast and efficient as possible. The owner
judged the previous sessions off track and asked Claude and Astra to decide the direction together.

Decision (Astra proposed, Claude agreed independently): stop oz map and the replication. No new councils, amendments
or sign-off rounds. Keep OZ/1g stable. Prove that the existing executor delivers more verified work per token and per
second than a competent direct CLI workflow on the same real task, before building anything new.

First step: `bench/o1/compare.py`. Same O1 repair package, same model, CLI flags and evaluator; a cold repair then a
revision of ticket A; arm order reversed between the two pairs. Engineering caps 16 launches, 150k tokens.

Decision rule: AKOR loses cold and wins revisions, target revision-heavy workflows. AKOR loses both, simplify toward
the direct runner before adding features. AKOR wins both, publish the comparison.

Astra's full text: [astra.md](astra.md).
