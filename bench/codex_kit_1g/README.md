# Codex measurement kit, stage 1g, Luna cell

Translated from Turkish by Claude Sonnet 5.5; the original text is in git history (commit 5abbc82).

`docs/design/stage-1g-final-decision.md`, stage D, the "Luna medium-64 5+5" cell. There is one arm: H (the ÖZ/1g text; the first
non-blank line of the reply must be exactly `OZ/1g`). 10 prompts, 64 jobs each:

- 5 standard packets: data seeds 2005 to 2009 (`std_*.txt`), same setup as `bench/live/run1g.py`.
- 5 heterogeneous packets: packets 1 to 5 of `bench/live/hetero1g.py` (`het_p*.txt`): empty array, scalar, object, nested array, job error.

Codex has no separate system field, so the rules go at the start of the prompt under `SYSTEM RULES:` and the packet goes under `INPUT:`.
The correct answers are stored in `oracles/`, so scoring does not rebuild the records.

## Run

From the repo root:

```bash
python bench/codex_kit_1g/run_codex.py --model gpt-6-luna --effort medium
```

```bash
python bench/codex_kit_1g/score.py bench/codex_kit_1g/results_gpt-6-luna_medium.jsonl
```

If it is interrupted, the same command resumes where it stopped. The table has one row per prompt: accepted (the whole reply),
correct jobs / 64, passed (accepted and 64/64), input and output tokens, time (seconds, wall clock). The last line says how many
prompts passed. The gate for this cell is 10/10 passed.

## Manual

Send a prompt file as it is, save the reply unedited as `bench/codex_kit_1g/replies/<same file name>`, then run
`python bench/codex_kit_1g/score.py --replies bench/codex_kit_1g/replies`. The token counts are unknown.

## Reading the results

The reply must be only the `OZ/1g` line and JSONL records. A code block, an explanation or a missing header makes the
whole reply invalid, as it would in the product. The Codex CLI adds about 24,500 input tokens to every call. To regenerate the prompts, run
`.venv/Scripts/python bench/codex_kit_1g/make_prompts.py` (the output should be identical).
