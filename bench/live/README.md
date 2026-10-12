# Live measurements

Live A/B runs behind the OZ9.md measurements. Run from the repository root with the
benchmark venv; every call goes through your own logged-in CLI and uses your quota.

```bash
MODEL=sonnet TIKTOKEN_CACHE_DIR=.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/live/live6.py
```

Environment: `MODEL` (`sonnet`, `opus`, `haiku`, `fable` map to pinned 5.5 / 5.1 model ids; or `codex:<model>`),
`EFFORT` (`low`..`max`), `OUT` (file name under `data/`).

| Script | What it measures |
|---|---|
| `run_live.py` | CLI call wrapper and usage capture (Claude `-p` and Codex `exec`) |
| `live2.py` | Astra's real-deliverable workload, oracles and the 0.8-exec baseline |
| `live3.py` | Reply-contract and preamble arms (A, B, S, F, C1, C2) |
| `live6.py` | 32/64 distinct jobs, F frames vs 0.8-exec |
| `live7.py` | Same workload, direct-ids form |
| `live8.py` | Astra's R1/R2/R3 forms for small models |
| `live9.py` | Effort sweep, 0.8-exec vs one form |
| `live11.py` | Joint-plan harness: fresh records per rep, strict parsing, arms up to the current wire (`S1c`) |
| `live13.py` | Heterogeneous workload: 3 domains, 10 operations, 64 sparse jobs |
| `make_codex_kit.py` | Builds `bench/codex_kit` (prompts and oracles for Codex models) |
| `score_model.py`, `score8.py` | Scoring with the deterministic oracles |

`p08.json` holds the 0.8 packets, made by `gen08.py` from `git archive oz-0.8.0-full`.
Raw replies and usage for every call so far are in `data/`.
