# OZ/encoding measurement

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

This offline benchmark counts the full receiver input with real tokenizers on the existing OZ/2 synthetic scenarios. No model or tool call is made.

| Scenario | First auto dictionary packet |
|---|---:|
| code | 32 |
| materials | 32 |
| data | 32 |
| translation | 32 |
| support | 32 |
| planning | 32 |

`Auto` does not use a single threshold. It compares every full JSON/dictionary input on all selected tokenizers; it requires no regression on any tokenizer, at least one strict saving and the `min_savings` value. The crossover in the table is only the first packet observed for these synthetic fixtures.

## Materials scaling scenario

| Job count | o200k JSON | o200k dictionary | o200k auto | cl100k JSON | cl100k dictionary | cl100k auto | Selected auto mode |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 563 | 677 | 563 | 563 | 675 | 563 | json/tuples |
| 4 | 602 | 703 | 602 | 602 | 698 | 602 | json/tuples |
| 8 | 684 | 753 | 684 | 684 | 744 | 684 | json/tuples |
| 16 | 821 | 839 | 821 | 821 | 823 | 821 | json/tuples |
| 32 | 1095 | 953 | 953 | 1095 | 951 | 951 | oz_base/tuples+table |
| 64 | 1643 | 1177 | 1177 | 1643 | 1175 | 1175 | oz_base/tuples+table |

## Method and limits

- Six old OZ/2 scenarios and packets of 1, 4, 8, 16, 32, 64 tasks were used. For each row, the ID, wire text, context and, if needed, the dictionary were counted in the full receiver input.
- `off` measures only compact JSON candidates; `on` measures only OZ/1/2 dictionary candidates. `auto` compares the full inputs and selects the result that meets the gate conditions.
- The largest measured packet is 64 jobs; runtime input budgets apply separately. The token counts belong only to the `tiktoken` tokenizers.
- This measurement is not a claim about live model savings, task accuracy, latency or general performance.

The raw counts for all scenarios and the assumptions are in `OZ-ENCODING-RESULTS.json`.
