# Direct CLI workflow vs AKOR executor, O1 repair package (live, 2026-10-26)

Sonnet 5.5 (claude-sonnet-5-5, default effort), Claude Code 2.1.306, `claude -p` with no tools for both arms.
Runner `bench/o1/compare.py` (commits 841c4b4, 32e87b0, reviewed twice by Astra). Raw rows: `bench/o1/cmp-live1/`.
Pair 1 ran direct first, pair 2 AKOR first. Every delivery passed the independent evaluator (tiers A, I, H, patch,
provenance) within five minutes. No failed call, no call without usage. 13 launches, 78,704 tokens in total.

| Pair | Arm | Stage | Calls | Input | of which cache read | Output | Thinking | Total tokens | Seconds |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | direct | cold | 1 | 7,465 | 0 | 3,676 | 1,613 | 11,141 | 28.9 |
| 1 | direct | revision | 1 | 3,512 | 0 | 927 | 462 | 4,439 | 12.2 |
| 1 | AKOR | cold | 3 | 15,054 | 4,546 | 6,094 | 2,873 | 21,148 | 58.2 |
| 1 | AKOR | revision | 2 | 5,396 | 1,206 | 840 | 411 | 6,236 | 22.1 |
| 2 | AKOR | cold | 2 | 10,442 | 4,546 | 3,531 | 1,416 | 13,973 | 33.2 |
| 2 | AKOR | revision | 2 | 5,420 | 2,501 | 840 | 390 | 6,260 | 20.5 |
| 2 | direct | cold | 1 | 7,464 | 6,809 | 3,546 | 1,421 | 11,010 | 27.9 |
| 2 | direct | revision | 1 | 3,515 | 2,860 | 982 | 570 | 4,497 | 12.6 |

AKOR/direct, mean of the two pairs: cold tokens 1.58x, cold time 1.60x; revision tokens 1.40x, revision time 1.73x. Time is the delivery time measured by the runner (calls, local checks, packaging); the final independent evaluation is not included.

Reading. AKOR loses both stages; under the decision rule in [README.md](README.md) the next step is to simplify toward
the direct runner before adding features. The visible cause is structure, not wire size: the executor splits each
ticket into a core stage and an adapter stage that depends on the accepted core, so a delivery costs at least two
serial calls (cold 2 to 3, revision 2), each carrying the fixed prompt again. The direct workflow asks for the
dependent pair in one call and checks it afterwards; Sonnet passed every check on the first try. Pair 1 AKOR cold
needed a third call. Two pairs on one workload are directional, not a general claim.
