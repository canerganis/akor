# Replication harness: build notes (2026-10-24)

Implementer: one fresh Opus subagent (claude-opus-5-5), logged in call-ledger.jsonl. It made no model call and no
Codex call. Every CLI command it ran was local (`codex --version`, `codex exec --help`, `codex features list`,
`codex login status` and one frozen `codex exec` argv against an empty CODEX_HOME without auth.json, which ended with
401 Missing bearer, so no model request could be served). Harness: `bench/ozmap_rep/` (standard library only). Frozen
pilot code (`bench/ozmap/`, `oz_*.py`, `examples/`) and Fable's `bench/ozmap_rep/ops/` are imported, never edited.
The sealed reviewer ASTs were not read; `classification.json` holds only their hashes, copied from the committed review.

Blindness. Everything under `bench/ozmap_rep/` (operations, classification, registry builder, harness) and this file
describe the operations. None of it may enter an Astra evidence pack before scoring; describe the operations to Astra
only as "four independent tensile-test ops".

## Test results

| suite | result |
|---|---|
| `python -m pytest bench/ozmap_rep -q` (blind acceptance, Fable's ops tests, harness tests) | 361 passed |
| blind acceptance tests alone (`bench/ozmap_rep/acceptance`, unedited) | 288 passed, 0 failed, 0 disputed |
| `python -m pytest -q` (full repository) | 1,622 passed; 50 failed and 3 collection errors, all outside `bench/ozmap_rep/` and all from the missing tiktoken in the system interpreter (below) |
| dry run `python -m bench.ozmap_rep.run dry --run-dir <D>` | exit 0: 16 of 16 cells complete, 52 fake calls, 0 external calls, no real CLI resolved, every cell within its A4.4 bound |

Full suite. Plain `python -m pytest -q` stops at collection with three errors that predate this build:
`tests/test_codereview_pilot.py`, `tests/test_pilot2.py` and `tests/test_pilot_k2.py` import `bench/live/run_live.py`,
which imports `tiktoken`, and the system interpreter (Python 3.12 without tiktoken) lacks it. With
`--continue-on-collection-errors` the run gives 1,622 passed, 50 failed, 1 skipped, 3 collection errors. Every failure
is outside `bench/ozmap_rep/` (tests/test_oz_flow.py 30, test_g3b.py 8, test_ozmap_close.py 4, test_oz_map.py 3,
test_ozmap_pilot.py 3, test_oz_do.py 1, test_host_classify.py 1) and comes from the same environment gap: 42 of them
raise `ModuleNotFoundError: tiktoken` and the rest assert on results that need the tokenizer (an unresolved
`tiktoken` import in a route closure, `reasoning_unverified` instead of `usage_unverified`). The repository `.venv`,
which the pilot used, has tiktoken 0.14.0 but no pytest. None of these tests imports the new harness. The harness
itself never needs tiktoken in the calling interpreter (see A4.7 below).

## Open disputes

None. No acceptance test was found to contradict Amendment 4, so `disputes.md` was not created.

## Clause map (A4.x to code)

Paths are relative to `bench/ozmap_rep/`. Line numbers are those of this commit.

| clause | what | where |
|---|---|---|
| A4.1 | frozen material untouched, every attempt and failure kept (append only `attempts.jsonl`, refused and failed calls included) | `run.py:120` `_append`, `run.py:622` `after_group`; acceptance `test_a4_1_scope.py` |
| A4.1 | freeze of amendments, manifests, classification, accounting predicates and checks before evaluation calls; live cells refuse without a verified freeze | `run.py:1061` to `run.py:1124` (`freeze_record`, `verify_freeze`), gate at `run.py:395` |
| A4.2 | four numbered worker homes and empty working directories, rebuilt before every call from auth.json only, under the authentication lock | `isolation.py:396` `Isolation`, `isolation.py:426` `prepare` |
| A4.2 | runtime files inventoried by name, then removed; worker and baseline auth.json hashes compared after every call, failures included | `isolation.py:450` `finish`, `run.py:622` |
| A4.2 | reconciliation: nothing launched while a call is in flight (launch groups), one changed worker propagated under the lock, otherwise Codex evaluation stops and the cell is interrupted; an older snapshot is never restored | `isolation.py:376` `reconcile_auth`, `isolation.py:478` `propagate`, `run.py:691` `reconcile`, `run.py:708` `codex_stop` |
| A4.2 | one Codex cell process at a time, so reconciliation sees every call that ended | `run.py:903` |
| A4.2 | wave gate on the baseline access token exp (at least 48 h, timestamp only logged, missing or unreadable exp blocks, failure names the owner's `codex login`) | `isolation.py:138` `baseline_exp`, `isolation.py:162` `wave_gate`, `run.py:375` |
| A4.2 | baseline inventory verified at the wave gate and before every call | `isolation.py:199` `verify_baseline`, `baseline-inventory.json`, `run.py:375`, `run.py:523` |
| A4.2 | allowlisted environment (CODEX_HOME, HOME and USERPROFILE point at the worker home) | `config.py:46` `ENV_ALLOWLIST`, `isolation.py:221` `child_env` |
| A4.2 | frozen arguments, disable options, argument check and hash, launch verification (executable hash, argument hash, environment, home holding only auth.json, empty working directory equal to `-C`, instruction files in the directory and every ancestor) | `config.py:29` `FROZEN_ARGS`, `config.py:33` `DISABLE_FEATURES`, `isolation.py:260` to `isolation.py:360`, `run.py:511` `prepare_call` |
| A4.2 | `codex features list` recorded before each live wave with the worker home and the disable options | `run.py:947` `record_features` |
| A4.2 | telemetry checks: authentication read from CODEX_HOME and a clean sandbox home; failure stops live evaluation | `isolation.py:362` `telemetry_checks`, `run.py:966` `telemetry`, gate at `run.py:400` |
| A4.3 | event stream classification: the narrow CLI notice exception, refused requests, executions, uncertainty | `events.py:41` `classify_stream`, `events.py:109` (Sonnet), `run.py:300` `judge_codex` |
| A4.3 | no selective rerun: a refused, executed, uncertain or malformed call is terminal for its batch; only infrastructure failures retry, from the reserve | `run.py:52` `RETRYABLE`, `run.py:436` `run_batches` |
| A4.4 | capacity formulas | `budget.py:27` `capacity` |
| A4.4 | frozen dispatch (synchronized submission, full batches of at most 64, producer local for B, pooled for C) and the zero rule, worst audit placement exercise | `run.py:132` `schedule`, `run.py:144` `worst_case_calls`, dry report `capacity` (`run.py:1147`) |
| A4.5 | allocations, two reserve calls per allocation, reasons, caps (Codex 62, Sonnet 40), no transfer between allocations, forbidden reasons | `config.py:53` to `config.py:65`, `budget.py:38` `Budget.charge` |
| A4.5 | shared bootstrap: one physical call, charged fully to cold B and cold C | `budget.py:100` `analytic_calls`, `score.py:116` `cell_summary` |
| A4.6 | frozen classification before learner calls; R = verdict, margin, temp_class | `classification.json`, `bootstrap.py:51` `load_R`, `score.py:54` |
| A4.6 | bootstrap error scope (R, proposed rule), measured errors, completion failure, classification misses | `bootstrap.py:34` `assess`, `bootstrap.py:73` `admission_report`, `score.py:88` to `score.py:113` |
| A4.7 | inclusive decoder, 0 <= cached <= input, unverified without certificate, missing counter never zero, additive sensitivity reading | `usage.py:26` `decode_codex`, `usage.py:62` `additive_tokens` |
| A4.7 | archived live run 1 certificate, route and decoder source trace, applicability check, replay fixtures | `certificate/cache-certificate.json`, `usage.py:101` `Certificate`, `usage.py:132` `replay_fixtures`, `usage.py:164` |
| A4.7 | sign-off 5 per call reasoning predicate (imported from the pilot) with the pinned tokenizer | `usage.py:90`, `tokenizer.py:73`, applied at `run.py:647` |
| A4.7 | token gates under additive accounting as a sensitivity check | `score.py:196` `sensitivity_gates` |
| A4.8 | Fable's operations, task counts (4 producers x 64 per wave, 16 per operation per producer, 64 bootstrap jobs) and admission design (64 cases, 48 representative, 16 challenge) | `workload.py:47`, `workload.py:113` `gold` |
| A4.8 | registry and admission through the frozen oz_registry and oz_rule; rule values only with every consumer check passing | `rules.py:62` `manifest`, `rules.py:94` `admit`, `rules.py:110` `apply` |
| A4.8 | learner prompts never carry admission texts (checked before every launch and again by the scorer) | `prompts.py:178`, `run.py:519`, `score.py:81` |
| A4.8 | provenance audit: prompt files and hashes, launch and isolation evidence, timestamps, sealed artifact hashes; convergence only after scoring | `score.py:197` `provenance`, `score.py:287` `convergence` |
| A4.9 | Sonnet keeps the pilot instruction, template and flags; no exploratory condition | `prompts.py:38`, `prompts.py:42`, `config.py:24` |
| A4.10 | materials, BoolQ and pooling gates, inconclusive on incomplete cells, usage or evidence, per backend and cross backend claims | `gates.py:73`, `gates.py:92`, `gates.py:108`, `gates.py:184` |
| A4.11 | magnitude on R, unrounded ratios, labels, missed thresholds, inconclusive and invalid states, safety kill | `gates.py:155` `magnitude`, `gates.py:62` `safety_kill` |
| A4.12 | Codex stop at primary used_percent >= 80 (before every live Codex launch), Claude handoff at 99%, quota readings recorded | `quota.py:63`, `quota.py:73`, `run.py:388`, `run.py:470` |
| A4.13 | preparation ledger with caps, cumulative, refused unwritten when over a cap | `budget.py:115` `PrepLedger`, `config.py:64` |
| A4.13.4 | baseline home `~/.ozmap_rep/baseline` | `config.py:77` |

## Codex CLI flags (codex-cli 0.160.0)

Recorded in `cli-flags.json` (method, results, observations).

| item | status |
|---|---|
| `--ignore-user-config`, `--ignore-rules`, `--ephemeral`, `--skip-git-repo-check`, `--json`, `-s read-only`, `-C`, `-m`, `-c`, `--disable` | all exist in `codex exec --help`; the full frozen argv is accepted |
| plugins, apps, memories, hooks, multi_agent, skill_search, browser_use, computer_use, image_generation, view_image | disabled (features list shows false) |
| other tool features: shell_tool, unified_exec_tty, browser_use_external, browser_use_full_cdp_access, in_app_browser, remote_plugin, plugin_sharing, recommended_plugins, skill_mcp_dependency_install, tool_suggest, tool_call_mcp_elicitation, sleep_tool, multi_agent_v2, shell_snapshot, workspace_dependencies | disabled |
| unified_exec | `--disable` accepted but stays true (recorded, does not block launch, A4.3 governs its events) |
| code_mode_host | not used: disabling it makes every exec emit an error item ("Code Mode is unavailable...") that is not a frozen notice, so A4.3 would make every call uncertain; code_mode itself is off |
| `-c project_doc_max_bytes=0` | accepted, no unrecognized setting notice |

Observations for the council (none changes A4, each is recorded in `cli-flags.json`):
1. At startup the CLI writes bundled system skills (`skills/.system/*`), sqlite state and `installation_id` into
   CODEX_HOME. They are inventoried and removed after every call. Whether bundled skills reach the model context is
   not observable without a model call; the telemetry input token count is the evidence.
2. `secret_auth_storage` is a stable, enabled feature and not a tool feature. With an empty CODEX_HOME,
   `codex login status` says "Not logged in" and an exec request carries no bearer, so no credential store fallback
   was seen for an empty home. The A4.2 telemetry check must still establish it for a reconstructed worker home.
3. A WebSockets to HTTPS fallback emits the error item "Falling back from WebSockets to HTTPS transport...", which is
   not a frozen notice: a live call that hits it is uncertain under A4.3.
4. The CLI refuses PATH helper binaries when CODEX_HOME is under the system temp directory, so live runs default to
   `~/.ozmap_rep/runs/replication`.

## Allowlisted environment

Codex children receive only `PATH, PATHEXT, SYSTEMROOT, SYSTEMDRIVE, WINDIR, COMSPEC, TEMP, TMP, LANG, LC_ALL, TZ,
NUMBER_OF_PROCESSORS, PROCESSOR_ARCHITECTURE, OS`, plus CODEX_HOME, HOME and USERPROFILE set to the worker home. No API
key, no owner CODEX_HOME, no APPDATA. Sonnet children (pilot route, owner's Claude login) receive the same list with
HOME and USERPROFILE unchanged, plus APPDATA and LOCALAPPDATA; API keys are never passed. Each launch records the
environment names in `evidence/launch/<call id>.json`.

## Per wave features record

Live only: before each Codex cell, `codex <disable options> features list` runs with a freshly reconstructed worker
home (a local command, no model request) and `evidence/features-<cell>.json` keeps every feature state plus the list of
tool features still enabled. With a synthetic baseline the probe reported 154 features and only `code_mode_host` and
`unified_exec` enabled among the listed tool features. Fake mode records nothing here, because a fake cannot establish
properties of the real CLI.

## Preparation call reconciliation (A4.13)

| agent | from the documents | ledger (conservative) | notes |
|---|---:|---:|---|
| Fable | 1 | 1 | operations in `bench/ozmap_rep/ops/` |
| Astra | 6 | 7 | A4 rounds 1 to 3 (A4.5 driver note: 4 after round 3), A4.13 drafting and signing (`a413-astra.md`, `a413b-astra.md`); the ledger keeps the driver's conservative 7 |
| Opus | 4 + 2 | 12 | A4 review and two sign rounds (A4.13: "Opus 3 of 4"), the A4.13 signature; plus this workflow's expressibility reviewer and this implementer, both logged now; the ledger's reconstructed 10 counts every relay subagent as one call |
| Sonnet | 1 | 1 | blind acceptance tests |

Totals after this build: Astra 7 of 20, Opus 12 of 40, Fable 1 of 4, Sonnet 1 of 40. Evaluation calls so far: 0
Codex, 0 Sonnet. Driver quota at the start of this step: Claude weekly all models 63%.

## Provenance audit artifacts (per run directory D)

| artifact | content |
|---|---|
| `D/attempts.jsonl` | one line per physical call: cell, batch, try, allocation, reason, kind (nominal, reserve, telemetry), outcome, timestamps, elapsed, launch group, prompt, stdin, system and stdout hashes, event verdict, raw and decoded usage, reasoning check, auth hashes before and after, runtime file count |
| `D/prompts/<call id>.txt` | the complete model-bound text |
| `D/captures/<call id>.stdout`, `.stderr` | raw CLI output |
| `D/evidence/launch/<call id>.json` | argv and executable hashes, frozen hashes, environment names, working directory, instruction sources, verification problems |
| `D/evidence/isolation.jsonl` | prepare, finish and propagate events with hashes and runtime file names only |
| `D/evidence/auth-reconcile.jsonl`, `wave-gates.jsonl`, `quota.jsonl`, `features-<cell>.json`, `telemetry.json` | reconciliation actions, exp timestamps, quota readings, features, telemetry checks |
| `D/cells/<cell>/state.json`, `result.json`, `calls/`, `admission/`, `DONE.json` | resumable state, settled answers with their source (bootstrap, model, rule), audits, rule status, admission responses |
| `D/report.json`, `report.md` | scorer output, including `provenance` (per call hashes, sealed reviewer artifact hashes, classification and registry hashes) |

No file outside the baseline and the worker homes ever holds token text: evidence keeps hashes and names only, and the
fake refresh marker is assembled at run time so the fake's own source never holds it (acceptance test).

## Run state, resumption and retries

1. A cell with `DONE.json` refuses to run (exit 3, no call). A cell whose required cells are not complete refuses
   (exit 4).
2. Before each spawn the runner writes `cells/<cell>/inflight/<call id>.json`; after the call it appends the attempt
   and removes the marker. On resume, a marker without an attempt is recorded once as an `interrupted` attempt (it
   consumed its allowance) and its batch may be retried only from the infrastructure reserve.
3. A batch whose latest attempt has any terminal outcome (ok, refused, executed, uncertain, malformed) is read back
   from disk and never sent again. First attempts are launched before retries, so a retry never takes a nominal call
   another batch still needs.
4. Retries: only infrastructure failures (nonzero exit, no reply, timeout) and interrupted calls, reason
   `infrastructure_retry`, at most the allocation's two reserve calls. Fallback after a quarantine uses reason
   `audit_overflow` (remaining nominal capacity first, then the reserve). Nothing else can draw on the reserve.
5. Exit codes: 0 complete, 2 usage, 3 already complete, 4 requirements, 5 incomplete, 10 quota stop, 11 baseline gate,
   12 Codex stopped by authentication reconciliation, 13 telemetry checks not passed, 14 freeze not verified, 75
   interrupted. 12 to 14 are additions to INTERFACE.md.

## Interpretations the council may want to check

1. Makespan is the harness' own schedule: the sum over launch groups (at most four concurrent calls) of the longest
   call, plus the bootstrap's for cold B and C. It ignores time spent waiting for slots held by other processes.
2. A tool item field counts as evidence of execution only when it has a value (`null` and empty string are absent),
   so a declined command with `exit_code: null, aggregated_output: ""` is a refused request.
3. Top level `error` events (reconnect notices) are transport events, not tool activity; error items stay under the
   narrow notice exception.
4. BoolQ overhead and the pooling comparison use total tokens; materials gates use tokens per gold correct job.
   Warm correctness is checked as well as cold correctness.
5. Admission challenge cases: the first 16 cases of an operation whose generator category is not a plain record.
6. The goal is the "Record type" section of `ops.md`; each operation's instruction and contract is its section with
   the author's "Expectation:" paragraph removed, so no classification hint reaches the learner. All four materials
   operations are shown as eligible (the registry permits rule provenance for each), so eligibility does not leak R.
7. An inconclusive audit (no model answer for the audited job) lets this wave deliver the rule's answers but stops
   reuse in the warm wave; a disagreeing audit quarantines the operation's rule and its covered jobs fall back.
8. A bootstrap whose envelope parses but whose OZ/1g answers are malformed keeps its rules; its 64 answers are
   unresolved.
9. Fake mode enforces the baseline exp gate and inventory but not the quota, telemetry, freeze or features steps,
   which concern the real CLI. Live cells require all of them.
10. The reasoning predicate counts visible reply tokens with tiktoken 0.14.0 and the pinned vocabulary file from the
    pilot freeze, in process when available, otherwise through the repository `.venv` interpreter.

## Before evaluation calls

1. Council review of this build, then `python -m bench.ozmap_rep.run freeze` (writes `bench/ozmap_rep/freeze.json`)
   with the freeze sign-off.
2. Baseline gate at the time of this build: exp 2026-11-03T15:18:43Z, about 238 hours left, inventory matches
   `baseline-inventory.json`. The gate is read again at the start of every wave.
3. `python -m bench.ozmap_rep.run telemetry --mode live --claude-weekly-percent <pct>` (one Codex telemetry call of
   four) must pass before any live Codex cell.
4. Cells in plan order, one Codex cell process at a time:
   `python -m bench.ozmap_rep.run cell <id> --mode live --claude-weekly-percent <pct>`.
