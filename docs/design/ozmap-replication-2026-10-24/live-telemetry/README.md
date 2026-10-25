# Live telemetry, 2026-10-25

Run directory `C:\ozmap_rep\runs\replication`, bound to the freeze committed in a662209 (`bench/ozmap_rep: replication freeze`, 83 files, codex-cli 0.160.0). The files here are copies of the run's evidence. They hold hashes and metadata only; a scan against the baseline and owner credential strings found none.

Command: `python -m bench.ozmap_rep.run telemetry --mode live --claude-weekly-percent 77`, exit 0, output `{"telemetry": true, "problems": []}`. Then `features --mode live`, exit 0.

## Gates before the calls

Claude weekly all models 77% (line 95%). Codex primary used_percent 2% (line 80%). Baseline access token exp 2026-11-03T15:18:43Z, 214 h away (line 48 h), last_refresh 2026-10-24T15:18:41Z, baseline auth.json sha256 30086a4b... (`wave-gates.jsonl`). `verify-freeze` reported no problems before and after.

## Calls (A4.5 telemetry allowance: 2 of 4 Codex telemetry calls used)

1. `telemetry.r1.b00.t0`, role probe: the frozen exec argv at a worker path whose auth.json keeps the baseline account metadata with tokens no server accepts. Outcome `auth_failure` as expected, no reply, no usage. Its stream verdict is `uncertain` because of the error events a failed authentication produces; that is the expected shape of the probe.
2. `telemetry.r2.b00.t0`, role call: the frozen exec argv with a reconstructed worker home on the neutral one job packet. Outcome `ok`, reply `OZ/1g {"j00":"ok"}`, stream verdict `plain`, usage status `unverified`.

## Checks

| Check | Result | Evidence |
|---|---|---|
| Authentication read from the CODEX_HOME file, not an OS credential store | pass. `login status` at the four emptied worker paths said not logged in before the probe and after the call, logged in with the reconstructed worker home; the probe with unaccepted tokens failed authentication; the call ran with store `file` at a worker home | `telemetry.json` (`auth_read_from_codex_home: true`, `login_status`, `exec_probe`, `call.auth_source`) |
| Read-only sandbox starts in a clean home | pass. Worker home held exactly `auth.json` at launch, working directory empty, no reachable instruction source, stream plain | `telemetry.json` (`sandbox_clean_home: true`) |
| Auth hash sync | pass. Every reconciliation (login probe, call, features) found the worker auth.json equal to the baseline hash, action `continue`; no auth rewrite in the probe or the call; baseline unchanged | `auth-reconcile.jsonl`, `auth-lineage.jsonl` |
| No tool or file items in the event streams | pass. Both calls: `tool_requests` and `tool_executions` empty, `external_read` false. Item types: probe `error` only; call `error` (2 plain CLI notices: the under development feature warning and the code mode host notice) and one `agent_message` | `attempts.jsonl` (`events`) |
| Startup runtime files | pass. No instruction bearing runtime file outside the approved startup manifest, in the probe or after the call | `telemetry.json` (`runtime_files`, `runtime_hashes`) |
| Reconciled before certification | pass | `telemetry.json` (`reconciled: true`) |

## Features

`codex features list` with a reconstructed worker home (`features-features.json`): the only enabled tool feature is `unified_exec`, which A4.2 says does not block launch; A4.3 governs its events.

## Owner login

`~/.codex/auth.json` sha256 238c7c1fa6522a24db4080c8ce0c2ba740346784e87d853e064714508ca61013 before and after, mtime 2026-10-15 21:40:16 +0300 unchanged. `codex login status` with the default CODEX_HOME said `Logged in using ChatGPT` before and after.
