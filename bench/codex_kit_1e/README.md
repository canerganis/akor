# Codex measurement kit

Translated from Turkish by Claude Sonnet 5.5; the original text is in git history (commit 5abbc82).

The same job set used on the Claude models: 16 material records × 4 operations, different records in every repeat,
exact correct answers (`oracles/`). Two arms: `0.8-exec` (the old version that does the same job) and `S1e` (the current ÖZ form).
32 and 64 jobs, 3 repeats, 12 prompts in total (`prompts/`).

Codex has no separate system field, so the ÖZ rules go at the start of the prompt under the `SYSTEM RULES:` heading
and the job body goes under `INPUT:`.

## Automatic (recommended)

From the repo root, for each model:

```bash
python bench/codex_kit_1e/run_codex.py --model gpt-6-luna --effort medium
```

```bash
python bench/codex_kit_1e/score.py bench/codex_kit_1e/results_gpt-6-luna_medium.jsonl
```

Run the same for `gpt-6-astra` and Sol (give the model name as Codex knows it). If it is interrupted, the same command
resumes where it stopped. The table shows: valid answers, correct jobs, input, output, total tokens, difference vs 0.8, median time.

## Manual

Send the contents of a prompt file as it is and save the reply, unedited, as `bench/codex_kit_1e/replies/<same file name>`.
Then run:

```bash
python bench/codex_kit_1e/score.py --replies bench/codex_kit_1e/replies
```

Done by hand, the token counts are unknown and only correctness is measured.

## Reading the results

The Codex CLI adds about 24,500 input tokens of its own instructions to every call. So the percentage difference in the
total looks small. Look at correctness and output tokens first. The reply must be JSONL lines only. A reply with a code
block or an explanation counts as invalid, as it would in the product.
