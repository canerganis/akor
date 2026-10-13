# OZ/2: 0.3.0 verification report

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

11 October 2026. Windows, Python 3.12, tiktoken 0.14.0. [Raw token measurements](oz2-token-counts.json), [live replies and usage](oz2-live.json).

## Functional verification

**99 automatic tests passed.** The earlier 54 tests are kept. New checks: macro expansion, lossless round trip of 250 random legal sequences, rejecting macros that hide evidence/success, fingerprint, budget limit, Unicode/literal escaping, tokenizer cache, persistent reopening, dependency between different agents, lease renewal/expiry, rejecting an old reply, atomically rejecting a missing ACK, and two concurrent connections not taking the same job.

The local demo delivered two jobs together, held the review agent until their ACK and recorded the status message on the host path. The demo ran no tools; its results are synthetic acknowledgement records.

The 0.3.0 package was installed into the project virtual environment. Importing the installed modules from outside the repo, `oz decode`, `oz pack` with two tokenizers and exit code 2 on an insufficient budget were verified. The document links and the Git whitespace check passed.

## Live language comprehension trial

The Codex CLI converted 20 synthetic instructions into OZ/2: **20/20** meaning trees correct. These exact messages were passed to the Claude CLI; decoding by expanding into base operations was **20/20** correct. Success was counted by exact equality of operation order, reference id and literal text. No hidden repair was made.

Old atoms, parametric/fixed macros, macro combination, ending with a test result, failure with a blocker, reading a `not_run` record and a literal containing signs/line endings were tested. This is a syntax/meaning smoke test; it is not real task quality, an unseen large vocabulary or the success rate of a long conversation.

The Codex record reported 26,533 input, of which 7,296 cached input in the detail, 218 output and separately 123 reasoning output. Since the model name was not verified in the stream, it was recorded as the configured default. No tool event was seen.

The Claude record reported 2 normal input, 3,948 cache creation, 5,721 cache read and 1,164 output; the thinking detail was 605. The model id was `claude-opus-5-5`. Output/thinking fields that may include each other were not added up. The wall times were about 15.1 and 15.3 seconds; since the processes/prompts were different, this is not a speed comparison. The CLI startup context remains larger than the message language; the percentages below cannot be applied to total CLI/API cost.

## Batch transport with context included

Six synthetic domains: code, materials measurement, data quality, translation, support and planning. Each domain has 8 independent jobs and 4 host events. Total 72 messages, 48 jobs. Replayed over a real queue, 6 job packets and 24 host events were prepared; **this offline measurement made zero model calls**.

Every representation carried the same task, sources, operation order and message IDs. The vocabulary, field definitions and the needed context were counted in every receiver input. Candidates: plain text, short text, compact JSON with an operation contract, OZ with macros, base OZ; measured with source object/array formats.

| 48 job messages | o200k_base | cl100k_base |
|---|---:|---:|
| Separately, cheapest candidate in each input | 7,334 | 7,330 |
| 6 batched inputs, cheapest candidate in each input | **2,049** | **2,041** |
| Reduction | **72.1%** | **72.2%** |

Removing the repetition of shared context is decisive in the gain. Compact JSON was selected in these eight-message packets; it was not concluded that the alphabet is cheaper under all conditions.

## The same packet, different representations

The eight-message mixed pattern in the materials scenario was expanded to 64 messages with different IDs. The synthetic repetition tests the case where the vocabulary cost is shared; it is not assumed to represent a real workload.

| Full receiver input of 64 messages | o200k_base | cl100k_base |
|---|---:|---:|
| Short text | 1,791 | 1,790 |
| Compact JSON | 1,250 | 1,248 |
| OZ/2 | **814** | **760** |
| Reduction against short text | **54.6%** | **57.5%** |
| Reduction against JSON | **34.9%** | **39.1%** |

All numbers include the vocabulary and task context. In small packets their cost dominates; base OZ can be chosen at 16 messages and OZ with macros at 32/64 messages. The threshold is specific to the fixture/tokenizer.

The wire body alone of the 48 jobs is 228 tokens in base OZ with fully explicit references and 126 tokens with optimized macros: a **44.7%** reduction. This last ratio does not include the vocabulary/context; it is not a natural language or total cost comparison.

## Local encoder cost

On twenty repeated read atoms, the earlier 0.2.0 search counted 4,096 spellings; the new default counts at most 256 candidates and also covers the byte-shortest path. In the median of three runs after warm-up, the old search measured about 18-25 ms and the new search 1.3-1.4 ms. Details are in the raw report.

This small microbenchmark does not include network, model thinking, job time or tokenizer startup. The bounded search may miss a better spelling in a different message; it is not a universal minimum or a general agent speedup.

## Limits and reproduction

The core preserves numbers, units, uncertainty and source fields; it does not prove that a claim is true. Recording a host event without a model does not mean a new decision can also be made without a model. For repeated external effects, adapter idempotency is needed.

The input counts do not include the sender's startup instructions, the model's output/thinking, tool wrappers or the provider's pricing policy. The two tokenizers are not the current tokenizers of all models. A comparison of equal success, correction rounds, total usage and latency with the same models on real tasks has not been made yet.

```powershell
python -m unittest discover -s tests -v
python -X utf8 -m examples.oz2_demo
python -X utf8 oz2_benchmark.py
python -X utf8 oz_live_eval.py --suite oz2 --live
```

`tiktoken==0.14.0` is needed for token measurement. The last command uses real existing CLI accounts. The earlier [OZ/1 report](OZ-RESULTS.md) is the dated measurement of the 0.2.0 release.
