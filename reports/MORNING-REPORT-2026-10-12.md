# Morning report, 12 October 2026

Translated from Turkish by Claude Sonnet 5.5; the original is in git history (commit 5abbc82).

Branch `oz-0.9`, last commit `3f07723`. No push, no merge to main. 198 tests green.

## Short result

The target was met on calls of 32 and 64 jobs. In the live measurement with Sonnet, OZ/9 reduced total tokens by **43% (32 jobs)** and **55% (64 jobs)** compared with 0.8 doing the same work. All jobs passed the verifier (96/96 and 192/192), and the replies came faster (at 64 jobs the median was 9.2 s, 0.8 had 14.0 s).

There is no gain on calls of 1 to 4 jobs. The Claude CLI adds its own fixed load of 905 tokens to every call; this load dominates in a small call. At 16 jobs there is a 29% reduction in total and 41% without the CLI load.

## What happened overnight

1. **The offline target was met but the live one was not.** The request packet had shrunk by 38% at 1 job and 55% at 64 jobs with o200k. In the first live Sonnet test, though, total tokens came out 9% higher than 0.8, and the calls were slow too. There were two reasons. First, Sonnet misunderstood the compressed reply contract: 5 of 8 replies were invalid. Second, the model was rewriting the reference text word for word on "read" jobs.
2. **The comparison was not fair.** The 0.8 package did no work at 16 jobs; it only copied the codes back. So the old comparison at 16 jobs was invalid.
3. **Astra designed a real test set.** It contains a material range calculation and code repair, and the expected results are checked deterministically. It also added a 0.8 arm that really does the work. I set this up as the harness.
4. **The reply format changed.** Results are now natural JSON values and errors are in a separate map. With this format the valid reply rate went from 13/18 to 36/36. The receipt is no longer in the packet; it stays on the host side.
5. **Batching was added.** Astra's first priority was batching: `oz run --min-batch N --max-wait S`. Off by default.
6. **The spec and documents were updated.** Astra rewrote OZ9.md to match the code one to one. README and USAGE were updated for 0.9.

## Live measurements (Sonnet, `claude -p`, no tools)

Comparison with the 0.8 arm doing the same work. "Total" also includes the CLI's fixed load of 905 tokens.

| Measurement | Correct jobs | Total tokens | Without CLI load | Median time |
|---|---:|---:|---:|---:|
| Mixed 1/4/16 jobs, 18 calls | 124/126 (0.8: 123) | 17% fewer | 30% fewer | 3.1 s (0.8: 3.1) |
| 16 different jobs | similar to 0.8 | 29% fewer | 41% fewer | similar |
| 32 different jobs | 96/96 | **43% fewer** | 52% fewer | 7.0 s (0.8: 7.9) |
| 64 different jobs | 192/192 | **55% fewer** | 61% fewer | 9.2 s (0.8: 14.0) |

Proposals that were measured and rejected:
- **Astra's output rule:** it added 18 tokens to the request and did not reduce the output live.
- **Shortened reply contracts:** they either produced longer outputs (35 tokens against 36) or more invalid replies live.
- **Astra's "e" job clarification:** the new text led to an empty reply in all arms, 0.8 included.

Details: [OZ9.md](../OZ9.md) section 10 and `reports/OZ9-LIVE-*.txt`.

## My own decisions

- **Safety wording:** The header Astra merged did not have "no tool permissions". I added it back based on its own rule, and Astra confirmed.
- **Receipt:** Instead of a 16-character random receipt I used a short counter. The random receipt took about 7 tokens each in the request and in the reply. Later the receipt was removed from the packet entirely.
- **Writing tests:** 22 of the OZ/9 tests Luna wrote were faulty; I fixed them. On your instruction I had Sonnet subagents write the later tests, and I reviewed all of them and ran them myself.
- **My measurement error:** In the measurements I had used a fixed and cheap receipt, so the first tables showed the cost slightly lower than it was. I found the error and fixed it.

## Matters that need your decision

1. **Default batch.** The measurements clearly support large calls. `--min-batch` is currently off by default (1) and the batch upper limit is 16. Do you want to make the default 32 and bring the quorum in explicitly? The cost of this is waiting time.
2. **cl100k and other models.** The release gate in the spec asks for a live measurement with cl100k and verification on other models. cl100k is OpenAI's tokenizer; to measure it a GPT model is needed. You told me not to give work to Luna. Which model should be used, or should this step be skipped?
3. **Merge.** Is `oz-0.9` ready to go into main? I did not merge and did not push.

## Quota

Claude weekly 90%, Codex weekly 33%. No handoff was needed.
