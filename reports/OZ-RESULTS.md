# OZ/1 verification and cost results

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

11 October 2026. Windows, Python 3.12, tiktoken 0.14.0. Package version 0.2.0.

## Working result

The OZ/1 parser, typed reference check, channel fingerprint, short representation selection, receiver input selection and the path that splits out host events are ready. Together with the earlier AKOR/1 core, **54 automatic tests passed**.

In the live pilot, the Codex CLI converted 12 synthetic instructions into OZ messages. These messages were sent unchanged to the Claude CLI. Encoding was **12/12** and independent decoding was **12/12** correct. Exact numbers, references, the inference/observation distinction, test success/failure, completion and a plain text example were tested. The result is a grammar/meaning classification trial; it is not proof of a productivity gain on real software tasks or of general model reliability.

## Message size

| Message | Meaning | o200k_base | cl100k_base |
|---|---|---:|---:|
| `a` | Review operation defined on the active patch | 1 | 1 |
| `?3` | Request source 3 | 2 | 2 |
| `+8.` | Test report 8 passed; step done | 3 | 3 |
| `~10` | Hypothesis 10 is an inference | 2 | 2 |
| `!11` | Blocked because of reason 11 | 2 | 2 |

In the separate 11-example token fixture, the OZ message bodies totaled **34 tokens**, and their English equivalents that spell out all the meaning rules took **154 tokens**: a **77.9% reduction** in these message bodies alone. This comparison was not made against the best human abbreviation. The vocabulary, source definitions, system prompt and tools are not included in this percentage. The 12 examples of the real CLI trial and this 11-example token fixture are different measurements.

The vocabulary/grammar alone took **261-262 tokens**. In all the short receiver inputs where the vocabulary is needed, plain text came out cheaper and the automatic selector chose it. The `:` escape used for a new numeric piece of information could add one token to plain text; the selector does not hide this cost either.

When 16 review requests were combined into a single input, the symbolic text, including the needed narrow vocabulary and grammar, took **154-155 tokens** and the plain equivalents took **272 tokens**. This is a measurement of batch representation in the same call; it does not mean the shared context is free across different API calls. The source and task context are held fixed and excluded in this particular amortization table.

## Host path that produces no tokens

After `?`, `+`, `-`, `!`, `.`, `/` messages are verified, they can turn directly into a host event. A second model call is not required just to record status, to queue a source request or to report completion. In this case no extra inference call belonging to the receiver is made. When a new decision or work is needed, the host still calls the model. The tokens spent by the sender and the cost of producing the evidence are not counted as zero.

This mechanism returns a suggestion; it does not automatically approve completion, test correctness or tool permission. The reduction in total calls in a real orchestrator has not been measured yet.

## The limit shown by real CLI use

The reported input of the Codex call was **26,257 tokens** (7,296 of them in the cached input field) and its output was **110 tokens**. The reasoning output field showed 56 separately. We did not add these up in a way that counts ambiguous provider fields twice. No tool execution event was seen.

The Claude call reported 2 normal tokens and **9,489 cache-creation tokens** on input and **392 tokens** on output; the thinking detail field was 166. The model usage record showed `claude-opus-5-5`. Because the Codex model name could not be verified from the result stream, only the configured CLI default was left in the report.

The wall times were about 12.5 and 10.8 seconds; since the models, prompts and system loads were different, these are not a speedup comparison. The CLI system/tool/plugin startup context can be much larger than the short messages. For this reason we do not present the 77.9% message shrinkage as a saving in total CLI cost.

## Reproduction and next evaluation

Token counting: `python oz_benchmark.py`. Live pilot: `python oz_live_eval.py --live`. Tests: `python -m unittest discover -s tests -v`.

Raw outputs: [oz-token-counts.json](oz-token-counts.json), [oz-live.json](oz-live.json). The pilot replies were compared automatically with the expected operation/reference sequences; no hidden repair was made to failed examples.

The next measurement should compare the OZ, short natural language and JSON paths with the same models on real orchestration tasks. Under equal task success, source accuracy and constraint preservation, the total input/output/thinking tokens, correction rounds and wall time are decisive. This first release makes no claim of a universal smallest language or a guaranteed speedup.
