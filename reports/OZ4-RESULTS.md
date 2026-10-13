# OZ/4 verification: 11 October 2026

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

Package 0.6.0; tiktoken 0.14.0; `o200k_base` and `cl100k_base` were given to the selector together. Run: `python -X utf8 oz4_benchmark.py`. [Raw counts and times](oz4-token-counts.json).

**Real model calls: 0. Real code changes/test executions: 0.** This report measures the lossless transport and the input cost of synthetic code review requests. It does not measure the task success of code agents.

## New language unit

`^` means requesting the same program that is bound to the channel. In the example it carries 48 primitive operation requests as **1 command token** on both tokenizers. The definition of the base, the vocabulary and the sources is not included in this single token. In the full packet measurements they are all counted separately.

## Strong comparison

At the start the OZ/3 macros exist. The compiler first improves the absolute representation with existing macros, new macros, target lists, short text, JSON and, where suitable, a shared frame table. Then it tries the OZ/4 shared program + difference representation. An increase in cost on either tokenizer is not accepted.

An additional check is an explicit template table that defines exactly the same frames once. This simple method is strong on repeated messages; it prevents OZ/4 from claiming a big success only over repetition. It was also added to the production selector. The id of each message and its separate result obligation are preserved.

| Workload | Best absolute/table, o200k → OZ/4 choice | Best absolute/table, cl100k → OZ/4 choice |
|---|---:|---:|
| Single small read | 189 → 189 | 188 → 188 |
| Single 48-step plan | 846 → 846 | 844 → 844 |
| 8 different 48-step plans | 1,150 → 1,140 | 1,141 → 1,129 |
| 32 different 48-step plans | 2,200 → 1,739 | 2,168 → 1,705 |
| 64 different 48-step plans | **3,351 → 2,300** | **3,289 → 2,236** |
| 64 copies of the same plan, control | 1,239 → 1,239 | 1,238 → 1,238 |
| New free text | 194 → 194 | 193 → 193 |

The additional saving for 64 different plans is **31.36% / 32.02%**. The plans largely share the same sequence; the test procedure and another read step differ. There are 3,072 operation requests in total; these are not 3,072 jobs that were carried out. That all 64 plans are distinct is verified in the data generation. This structure is a workload for which the difference language is suitable; the same gain should not be expected on random and fully independent tasks.

In the control with 64 copies of the same plan, OZ/4 was not selected; the **cheaper shared table** was selected. The final cost shown is the result of a selector that does not force the format. On small messages too, the old format is kept because the Base definition does not pay for itself.

## Cost scope

In each packet, the needed full Base, grammar, macro definitions, the full text of the sources, the task ids and the Worker reply contract are counted. It is not assumed that the source/schema cache is free on the model side. Provider carrier fields, the sender's training/initial vocabulary, model generation/reasoning tokens, tool outputs and retries are not included. So these figures cannot be used as a total API bill or an end-to-end speed gain.

## Local times and tests

The vocabulary/macro search for 64 plans took tens of seconds in this run; the exact time is in the raw JSON. Redoing this preparation on every message does not make a fast communication path. The intent is to reuse a compiled channel at the same source and vocabulary revision.

With a compiled channel, the full repacking of 64 frames took about **774 ms** in the median of three runs, and the exact decoding alone about **2.94 ms**. The packing includes counting the tokens of each candidate and building the full context. These are small local timings of this machine; they are not network/model latency or a controlled speedup measurement against the previous release.

**179 unit/integration tests passed.** New coverage: lossless expansion of 250 random edit sequences; original coordinates; simultaneous reference swap; literal/evidence/success reports not being allowed into edits; the 64 operation/16 edit limit; rejection of a broken/old context; SQLite reopening; deduplicating equivalent messages by the same id; transferring the real result text to dependent jobs through the Worker. The test adapter explicitly produces a synthetic acknowledgement notice.

For OZ/4, comprehension in live models, real coding success, result quality or end-to-end total cost was not measured. There is no worldwide uniqueness, perfect orchestration or global minimum token guarantee.
