# OZ 0.4.0: usage and transport verification

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

11 October 2026. Windows, Python 3.12, tiktoken 0.14.0. [Reproducible scenario](../oz_workflow_eval.py), [raw result](oz-workflow.json).

## Automatic checks

**143 tests passed.** The earlier 99 tests are kept. New coverage:

- Automatic splitting by budget; a large job not blocking small jobs; planning not consuming an attempt.
- Including the reply contract and the predecessor results in the budget; transferring a shared predecessor once.
- Handling successful/transient/permanent results separately; a partial or faulty reply not producing a wrong ACK.
- Delayed retry, explicit reopening, rejecting an old reply and different workers not taking the same job.
- SQLite migration from v1 to v2 with existing results preserved; reopening; history and status pagination.
- Real stdin/stdout processes, timeout, bad JSON, shell characters staying as data and UTF-8 on Windows.
- CLI workspace, channel from a source file, CRLF/Unicode preservation, not overwriting an existing file and safe error codes.

## End-to-end offline trial

20 independent jobs were added, along with a review job that depends on them, a host event and a deliberately large independent message. The real `o200k_base` tokenizer was used. The standard JSON stdin/stdout adapter ran with real local Python processes; its results are synthetic acknowledgement records.

| Check | Result |
|---|---|
| Input budget of the working agent | 350 tokens per packet |
| Packets sent for 20 jobs | 3 |
| `m3`, which was given a transient error | 2 delivery attempts |
| The other 19 jobs | 1 delivery attempt each |
| Large independent message | Full text preserved; 0 attempts; waiting |
| Review agent | Waited for all 20 jobs, received their results |
| Review input budget | 2,048 tokens including the earlier 20 results |
| Host event | Only recorded; no model call |
| When the queue was reopened | Results and attempt counts preserved |
| Real model calls | **0** |
| Local adapter process calls | 4 |

In the final state 22 records were completed, and 1 record, deliberately larger than the budget, is waiting. These are demo acknowledgement records; it is not claimed that the domain tasks were actually done or verified.

0.4.0 was installed as a package into the local virtual environment. From outside the repo, `oz demo`, `oz status` and `oz inspect` were run with the `site-packages` modules. The sample workspace left behind is in `.oz-runtime/demo-0.4`; four demo records completed. In this small demo the working input was measured at 231 tokens and the reviewing input at 267 tokens; no model call was made.

## Scope limit

The verification of this release is about the usage flow, the budget and transport consistency. It is not a new model quality, end-to-end API cost or model speedup trial. The 20/20 Codex-Claude language trial of 0.3.0 and the token tables stand as dated evidence in [a separate report](OZ2-RESULTS.md).

The Worker's output format instruction and the earlier agents' results are added to the receiver input count. The adapter's own system prompt, tool schemas, thinking/output tokens and the provider's billing are outside it. Since the stdio result is synthetic, no made-up provider usage count was written into the report.

Reproduction:

```powershell
python -m unittest discover -s tests -v
python -X utf8 oz_workflow_eval.py
oz demo .oz-runtime/yeni-demo
```

The first two commands test/measure. The last command creates a new, empty demo folder. The tokenizer must be installed; no model key is needed.
