# AKOR 0.1.0: measurement and verification

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

Date: 11 October 2026. Environment used: Windows, Python 3.12, tiktoken 0.14.0. These are synthetic text token counts; the communication quality of live models and production cost were not measured.

## Result

In two examples and on two tokenizers, AKOR messages used **25.89-32.02%** fewer text tokens than equivalent short JSON objects and **10.89-13.57%** fewer than JSON arrays. When the language instructions and the required context are added to every receiver call, the saving in the input text was **4.70-5.57%** against JSON objects and **3.19-3.76%** against JSON arrays.

This difference shows that a shortened message is not equal to the cost of the total task. The contribution of less repetition and targeted transfer also depends on the workload. No large or universal saving percentage across providers can be drawn from this small experiment.

## Tokens of six messages carrying the same content

| Tokenizer | Example | AKOR | JSON object | JSON array |
|---|---|---:|---:|---:|
| o200k_base | English code | 175 | 253 | 199 |
| o200k_base | Turkish materials data | 211 | 289 | 237 |
| cl100k_base | English code | 172 | 253 | 199 |
| cl100k_base | Turkish materials data | 229 | 309 | 257 |

This table counts only the agent message text. The sender, receiver, task, revision, content and reference fields are the same in all formats. The JSON object uses field names; the JSON array uses the fixed order of the same fields. The natural language content was not shortened only in favor of AKOR.

## Six receiver calls with the language instructions and context

| Tokenizer | Example | AKOR | JSON object | JSON array | AKOR / object saving |
|---|---|---:|---:|---:|---:|
| o200k_base | English code | 3224 | 3414 | 3350 | 5.57% |
| o200k_base | Turkish materials data | 3291 | 3464 | 3410 | 4.99% |
| cl100k_base | English code | 3221 | 3407 | 3341 | 5.46% |
| cl100k_base | Turkish materials data | 3427 | 3596 | 3540 | 4.70% |

Each delivery was counted as a separate, memoryless model call. AKOR's 416-token language instruction was included again every time. The task references, the required source definitions and the target message of the review are present. The JSON comparisons also use the same meaning rules, references and the behavior of sending only the new messages.

In a separate comparison that re-adds the already processed messages of the same receiver, sending only the new messages reduces the AKOR input text by **6.18-8.05%**. This is a deliberately inefficient comparison condition; it does not replace the main JSON comparison.

API message wrappers, tool schemas, thinking tokens, reply generation, failed calls, retries, prices and cache discounts are not in these tables. The first table and the second table are separate accounting views; they cannot be added up and presented as total API consumption. Real tokenization can change with the provider's model and message format. Measurement tool: [tiktoken](https://github.com/openai/tiktoken).

## Verification

- **31 automatic tests passed.** Covered: preservation of Unicode, quotes and line endings; broken input; required evidence references; addressing; missing/changed references; repeated messages; ACK limits; old revisions; budget overflow; review target and context reset.
- The six-message synthetic demo completed.
- The package was installed into the virtual environment inside the project; the installed `akor` command and import were checked from outside the project folder.
- Operation with live models, different providers and different operating systems was **not tested**.
- The tests verify the existence of the reference and the protocol rules; they do not verify the scientific accuracy of the reference, the meaning of natural language or real test execution.

Raw counts and the example/instruction summary: [token-counts.json](token-counts.json). Reproduction: `python benchmark.py --output reports/token-counts.json`; first install the optional dependency in `requirements-benchmark.txt`.

## Note for the live pilot

The next stage is to add an adapter for two or more real models to be chosen and to run the same stored task set as short prose, JSON and AKOR. Total provider consumption, correction rounds and latency should be evaluated together, without the success rate and the preservation of constraints dropping. The current version offers a protocol and a local transport ready for this; it makes no claim of live multi-model compatibility.
