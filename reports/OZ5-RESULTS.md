# OZ/5 measurement report

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

Date: **11 October 2026**. Package 0.7.0; `tiktoken 0.14.0`, `o200k_base` and `cl100k_base`. Source: [oz5-token-counts.json](oz5-token-counts.json). Repeat: `python -X utf8 oz5_benchmark.py`.

The measurement is offline: **0 model calls, 0 real code/test executions**. The full receiver input is counted: the operation dictionary, the Form/Base and grammar used, the required source texts, the task ids and the Worker reply contract. The provider message envelope, the sender's initial training/context, the model's output/thinking, tool results and retries are not included in these numbers.

## Comparison

The comparison is OZ/4 optimized on the same data: a search limited to four new macros, target lists, a shared Base search, a same-frame table and text/JSON options. A weak comparison with only long natural language or without macros was not used. A new Form and matrix are accepted only if they do not increase the total cost on any of the selected tokenizers.

| Workload | o200k: OZ/4 → OZ/5 | cl100k: OZ/4 → OZ/5 | Extra reduction |
|---|---:|---:|---:|
| Single read | 188 → 188 | 187 → 187 | 0% |
| 8 different regular tasks | 1,252 → 1,252 | 1,243 → 1,243 | 0% |
| 32 different regular tasks | 1,901 → 1,412 | 1,870 → 1,409 | 24.7-25.7% |
| 64 different regular tasks | 2,743 → **1,524** | 2,680 → **1,521** | **43.3-44.4%** |
| The same 64 tasks, mixed order | 2,743 → 2,314 | 2,680 → 2,311 | 13.8-15.6% |
| 64 tasks with random parameters | 2,745 → 2,456 | 2,692 → 2,453 | 8.9-10.5% |
| 64 tasks suited to macros | 1,875 → 1,524 | 1,810 → 1,521 | 16.0-18.7% |
| 64 copies of the same plan | 857 → 857 | 855 → 855 | 0%; old table |
| Earlier OZ/4: 64 different difference plans | 2,300 → **1,930** | 2,236 → **1,927** | **13.8-16.1%** |
| New literal information | 192 → 192 | 191 → 191 | 0% |

The regular examples carry the read, review and test requests of four modules; each task contains 16 primitive requests. The parameter patterns were deliberately generated to be repeatable; for this reason the gain cannot be generalized to irregular tasks. The control where the order is shuffled while preserving the same ids and meanings, and the control where references/procedures are chosen randomly and independently, were reported separately. The encoder does not change the order of jobs.

The earlier OZ/4 data set was compared unchanged: 64 different plans of 48 requests each. In this data the Form and the Base can be present in the same channel; only the grammar that is used is charged in the packet. If the Base is not used when the matrix is selected, it is not added to the text.

## Local time and accuracy

For 64 regular tasks, the median of five repeats during measurement was about **0.36 seconds for full packing**, **1 millisecond for direct Form filling** and **1 millisecond for expanding the matrix into 64 independent frames**. These are local Python times. Direct filling does not include the tokenizer/candidate search and network/model time. The current raw times are in the JSON report; they can vary with hardware/load.

The full compilation includes the dictionary search and took about 8 seconds on this data set and about 22 seconds on the old OZ/4 example. A ready channel should be reused during communication. Recompiling on every message can erase the speed advantage. `--max-macros 0` skips the new macro search; in this example it gives the same final matrix cost.

All compiled examples were fully expanded to the original primitive operation sequence. A separate unseen-input check of 17 messages contains new parameter values and an operation sequence that does not fit the Form; all expanded losslessly and the suitable old format was selected. This is encoder accuracy; it is not a result that a model understands the compressed input correctly.

**202 tests passed.** In scope: 250 random Form bindings, 113 different column examples, bad/overflowing expansions, old manifest compatibility, CLI export/import, task id and dependent result transfer. Some unit tests use a character counter for the cost selection behavior; the token numbers above are only real tokenizer measurements.

Column encoding, dictionary and template sharing are known techniques. For this implementation there is no claim of worldwide uniqueness, a global token minimum, live model speedup or real coding efficiency. For a stronger result, success, wrong decoding, total tokens and end-to-end time should be measured together on the same real coding tasks.
