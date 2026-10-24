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

None. No acceptance test was found to contradict Amendment 4, so `disputes.md` was not created. Round 1: no council
blocker was judged wrong, so `disputes.md` still does not exist (see the round 1 section).

Round 2: `disputes.md` now holds two entries. D-R2-1: the red team test RT2.1 asserts a resend of a call whose capture
shows execution, which blocker 3, the joint decision and A4.3 forbid (its leakage assertion holds). D-R2-2: the joint
decision drops `--ephemeral`, which the normative A4.2 argument list and the blind acceptance suite keep; it stays
until Opus B rules on P3.

## Clause map (A4.x to code)

Paths are relative to `bench/ozmap_rep/`. Line numbers are those of commit 4839d99; after the council round 1 fixes the function names are authoritative and the round 1 section at the end of this file supersedes any row it contradicts.

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

## Council build round 1 fixes (2026-10-24)

Implementer: one fresh Opus workflow subagent (claude-opus-5-5), logged in call-ledger.jsonl as
`implementer-council-r1-fixes`. No model call and no Codex call was made; every live mode path was exercised with the
harness' own fakes. Inputs: council-build-astra-r1.md, council-build-opus-r1.md, council-build-redteam-r1.md. Frozen
code (`bench/ozmap/`, `oz_*.py`, `examples/`), Fable's `ops/`, the acceptance suite and the red team tests are
unchanged. The red team tests pass without edits.

### Test results after the fixes

| suite | result |
|---|---|
| `python -m pytest bench/ozmap_rep -q` (acceptance, ops, red team, harness tests) | 467 passed |
| red team round 1 alone | 16 passed |
| new regression tests `tests/test_council_r1.py` (one or more per blocker) | 90 passed |
| dry run `python -m bench.ozmap_rep.run dry --run-dir <D>` | exit 0: 16 of 16 cells complete, 52 fake calls, 0 external calls; scored as simulation, artifact chain clean |
| `python -m pytest -q --continue-on-collection-errors` (full repository) | 1,728 passed, 50 failed, 1 skipped, 3 collection errors; the failures and errors are exactly the files listed under the build test results above (missing tiktoken in the system interpreter), none in `bench/ozmap_rep/` |

### Blocker dispositions

| id | fix | where |
|---|---|---|
| 1 | Live cells need `telemetry_certificate`, not the two booleans: an exec probe on the frozen argv with an empty CODEX_HOME must end in an authentication failure without reply or usage; `login status` with an empty home must say not logged in before and after the call; the call itself must be plain with a home of exactly auth.json, an empty workdir, no reachable instruction file, and no instruction bearing file among the runtime files written at startup (less `SIGNED_STARTUP_FILES`, empty); the certificate is published only after reconciliation. `telemetry_checks` keeps its boolean interface (acceptance) | `isolation.telemetry_certificate`, `run.TelemetryRun`, `run.telemetry_problems` |
| 2, RT1.2, C1 | Every cell, telemetry and features run takes a non blocking per cell lock and the experiment lock before reading any state (second runner: exit 16, no call); prerequisites are checked under them; one cell process per run directory makes budget reservation atomic; features and login probes own their slot, write an in-flight marker and are reconciled | `run.exclusive`, `CellRun.run`, `_guarded`, `worker_probe` |
| 3, B3 | Markers carry the prepared auth hash (baseline generation) and, right after the spawn, the child pid and creation time; they are removed only after the group is reconciled. Recovery runs first, experiment wide: a recorded child still running stops the resume (exit 75, nothing touched); every Codex worker is finished and reconciled against its generation; a marker without pid on a home showing a started CLI is ambiguous and stops Codex; only then are orphans recorded as interrupted | `run.recover_inflight`, `isolation.reconcile_generations`, `CellRun.after_group` |
| 4, B4, C2, C3 | Telemetry runs through the same locks, recovery, gates (wave gate, inventory, Codex stop, quota, freeze, canonical run directory, ledger), slots, markers, budget, ledger, redaction, reconciliation and stop as evaluation, on its own allocation. Every result is appended to `evidence/telemetry.jsonl`; any failed or interrupted telemetry attempt blocks evaluation and further telemetry in that run directory for good; the scorer reports telemetry separately | `run.TelemetryRun`, `score.score_run` |
| 5 | Authentication failure is detected first, on the error channels only (turn.failed, top level errors, error items, stderr), whatever the timeout or event verdict; propagation is checked against the prepared generation under the lock, so a worker change after an owner reseed stops Codex and keeps the newer baseline | `run.judge_codex`, `Isolation.propagate(expected_baseline_sha256=)` |
| 6 | stdout and stderr are redacted before judging and before anything is written (token strings of the baseline, the worker and the probe home, plus JWT, API key and bearer shapes); a redaction record with the original hash is kept and the attempt is a credential disclosure, which fails isolation | `redact.py`, `CellRun.after_group`, `worker_probe` |
| 7 | The executable and its launcher payload (files named after it, libraries) are hashed before every launch group and compared with the frozen identity; verify_freeze checks the version found now; CODEX_HOME, HOME and USERPROFILE must be the worker home and no other value may point into an owner configuration directory; instruction discovery fails closed on unreadable locations | `isolation.executable_identity`, `Executables.verify`, `isolation.instruction_scan`, `env_selection_problems` |
| 8 | `code_mode_host` is disabled (its `--disable` is accepted). See pending ruling P4 | `cli-flags.json` |
| 9, RT1.1, RT1.5 | `--mode` is required at run time (exit 2 without it); the plan keeps the exact `command` of the acceptance interface and adds `live_command`; fake mode refuses the live run directory, the owner seeded baseline and any baseline with a signed token; `D/experiment.json` binds mode, freeze hash and baseline lineage at the first dispatch; mixed modes are refused (exit 15); live cells run only in the frozen live run directory and every live charge is also written to the experiment ledger `~/.ozmap_rep/runs/live-calls.jsonl`, which Budget counts in full, so a new or emptied directory gets no fresh allocation; reports say simulation or evaluation | `run.mode_problem`, `identity_problem`, `bind_identity`, `ledger_problems`, `CellRun.budget` |
| 10 | `run freeze` refuses once a live run is bound (a new freeze needs `--new-run-dir` and `--disposition`); live runs archive the freeze as `D/freeze.json`; freeze globs add `tests/`, `tests/fixtures/`, `redteam/` and the certificate envelopes; the scorer verifies the artifact chain (capture hashes, outcome, events, usage and answers derived again from captures, cell answers against their calls, rule answers recomputed, admission records reproduced, launch evidence) and, for live runs, the frozen inputs against the run bound freeze; any problem withholds every claim | `run.freeze_command`, `score._rejudge`, `_cell_chain`, `_freeze_problems` |
| 11, RT1.3 | Tool items are aggregated over all events (execution sticky); missing ids, and one id seen with two item types, are uncertain; every top level `error` is uncertain unless a signed transport notice names it; a non JSON stdout line is uncertain | `events.classify_stream` |
| 13, C6 | Order in judge: authentication failure, tool verdict, delivered reply (turn completed) accepted even after a timeout or nonzero exit, and only then the infrastructure predicate (no reply delivered) is retryable. Sonnet parses the envelope even after a timeout | `run.judge_codex`, `judge_sonnet` |
| 14 | Gated makespan is the sum of the cell's work windows (submission to resolution of each invocation, local work and launch skew included), plus the bootstrap windows for cold B and C; `child_makespan_s` reports the old statistic | `CellRun._window`, `score.cell_summary` |
| 15 | Bootstrap answers that are malformed or missing make the call `malformed_answers` and the bootstrap a completion failure; proposals are kept with admission `not_evaluated`; a cell with any terminal unsuccessful outcome writes `SETTLED.json`, returns 5 and is never rerun; only an all ok cell writes `DONE.json` | `CellRun.interpret`, `run_bootstrap`, `_run_locked` |
| 16 | `validate_classification` requires every operation, valid fields and a timestamp no later than now and the first learner call, before any dispatch (exit 18) and in the scorer; an invalid classification gives no R and blocks materials claims; its hash is in the freeze | `bootstrap.validate_classification`, `CellRun.gates` |
| 17 | Unanswered audits are listed in `unresolved_audits`; a cell or R subset with one is incomplete, so affected comparisons are inconclusive; no repair call | `CellRun.run_BC`, `gates._incomplete` |
| 18, B2 | `magnitude` returns invalid with reasons before any ratio when any A4.10 validity problem or a safety kill exists; BoolQ and pooling gates include the kill; an accepted incorrect rule answer writes `D/safety-kill.json` and every later dispatch exits 17 | `gates.magnitude`, `CellRun._run_locked`, `CellRun.gates` |
| 19 | Pair validity stays `Certificate.valid`; authority is `certificate_authority`: authorized run and pair, route, decoder hash, capture decoder trace (hash of the frozen capture adapter), and every source envelope present, hashing to its record, on the certificate's route and decoding to the stated pair | `usage.certificate_authority` |
| 23 | A4.13 (`amendment-4-13-caps.md`, signed by Astra A and Opus B before the build, commit b1d41ff) authorizes the caps 20, 40, 4, 40 and global 206; the round 1 review calls are within them (ledger below). A test checks config against the signed text | `tests/test_council_r1.py::test_item23_*` |
| B1 | (a) done (item 5); a replay of `cliprobe/exec-noauth2.out` (copied to `tests/fixtures/`) is an authentication failure and stops Codex. (b) needs a ruling: P1 | `config.SIGNED_TRANSPORT_NOTICES` (empty) |
| B5 | Not changed: needs a ruling, P2. Until then any retry or interruption leaves that cell's usage incomplete, so it forfeits the cell's token claims | |
| RT1.4 | The pinned CLI's refresh failure texts and the 401 texts are matched | `run.AUTH_FAILURE_RE` |
| RT1.6 | Interim (C4): a live Codex cell launches only when the owner session reading is newer than the end of the last live Codex call; the full fix needs a ruling, P3 | `CellRun.codex_quota_gate`, `quota.codex_reading_time` |

Changes adopted: C5 (live Codex gates need the pinned tokenizer), C7 (a positive `cache_write_input_tokens` makes
usage unverified), C9 (live isolation needs a passing telemetry certificate, a wave gate row, a features record and an
auth record per Codex attempt), C11, item 20 (sensitivity recomputes R totals from additive costs), item 21
(`decode_codex_checked` keeps known violations visible when a counter is missing; `decode_codex` itself is unchanged,
so the certified decoder hash holds), item 22 (finite quota readings; the report shows current preparation counts,
physical, telemetry and analytical token views and warm increments), red team observations 2, 3 and 9. Not adopted:
C10 (leakage stays global: the stricter reading, as the reviewer allowed).

### Pending prospective rulings (needed before the freeze)

Each needs Astra A and Opus B signatures; none is implemented beyond an empty signed slot in `config.py`. Until
signed, the harness applies the strict reading, and P1, P4 and P5 make a live run unable to produce valid efficiency
evidence.

* P1 (B1 b, item 11). Whether the 0.160.0 transport texts (`Falling back from WebSockets to HTTPS transport.`,
  `Reconnecting... `) are transport events. Today every such event is uncertain, so one transient reconnect
  invalidates replication efficiency. A signed ruling fills `config.SIGNED_TRANSPORT_NOTICES`.
* P4 (item 8). With `code_mode_host` disabled every exec emits `Code Mode is unavailable...` as an error item, which is
  uncertain under A4.3, so every live Codex call would invalidate efficiency. A ruling must either define that notice
  as allowed or sign the omission of the option (`config.SIGNED_OMITTED_DISABLES`).
* P5 (item 1). The CLI writes bundled skills (`skills/.system/*`) into CODEX_HOME at startup. They are instruction
  bearing names, so the telemetry certificate cannot pass until a ruling either accepts named startup files
  (`config.SIGNED_STARTUP_FILES`) on stated evidence or names other evidence of the effective instruction sources.
* P2 (B5). Bounded accounting of failed or interrupted attempts with unknown usage, as proposed in Opus B5. Today any
  retry forfeits the cell's token claims.
* P3 (RT1.6). Dropping `--ephemeral` to read worker rate limits, or a headroom rule. Today only the freshness gate
  above holds, and within one cell the reading can go stale.

### Readings where A4 is silent (the stricter validity reading)

1. One cell process per run directory; a second runner exits 16 at once instead of waiting.
2. A spawn exception, or a marker whose termination cannot be established, stops Codex rather than being treated as
   a call that never started.
3. The empty home exec probe in telemetry reaches the provider without credentials, so it is charged as a telemetry
   call (two of the four telemetry calls per attempt) although no model can serve it.
4. A settled cell with a terminal unsuccessful outcome does not satisfy a `requires` dependency, so cold B and C never
   run after a failed bootstrap (they would be inconclusive anyway).
5. A delivered reply after a timeout or nonzero exit is accepted, not retried and not discarded, so no answer is
   repaired and no batch is sent twice.
6. The red team asked for `--mode live` inside the plan command; the acceptance interface fixes that command exactly,
   so `--mode` is required at run time instead and the plan adds `live_command`. The red team asked fake mode to accept
   only a synthetic baseline inside D; acceptance tests pass a baseline outside D, so fake mode accepts any baseline
   whose access token is unsigned and refuses the owner seeded one.
7. A telemetry failure needs a new run directory, which needs a new freeze (`--new-run-dir`, `--disposition`). Live
   calls of the superseded directory stay in the experiment ledger and keep counting against every allocation and cap.
8. The launcher payload is the set of files beside the executable named after it or loaded by it (for codex-cli
   0.160.0: `codex-code-mode-host.exe`), so unrelated programs in the same directory do not block a launch.

New exit codes (harness additions to INTERFACE.md): 15 run identity or directory refused, 16 another runner active,
17 safety kill established, 18 classification invalid.

### Preparation calls after this step

Astra 8 of 20, Opus 16 of 40, Fable 1 of 4, Sonnet 1 of 40 (ledger sums, this implementer included). Evaluation calls
so far: 0 Codex, 0 Sonnet. Driver quota at the start of this step: Claude weekly all models 65%.


## Council build round 2 fixes (2026-10-24)

Implementer: one fresh Opus workflow subagent (claude-opus-5-5), logged in call-ledger.jsonl as role
`implementer-council-r2-fixes`. It made no model call and no Codex model call. The only CLI commands it ran were local:
`codex --disable secret_auth_storage --enable skip_host_skill_discovery -c cli_auth_credentials_store="file" features
list` and `codex -c cli_auth_credentials_store="file" login status` with an empty temporary CODEX_HOME (Fable F1 to F3
reproduced; the home stayed empty), and `codex --version` while the new write guard held every file of the pinned
package (the binary launched; a write to it was refused). Inputs: the round 2 reviews (council-build-opus-r2.md,
council-build-astra-r2.md, council-build-redteam-r2.md), the joint decision council-build-deadlock-r2-joint.md and the
two co-solver files. The sealed reviewer ASTs were not read.

### Test results after the fixes

| suite | result |
|---|---|
| `python -m pytest bench/ozmap_rep -q` | 532 passed, 1 failed: the disputed red team test RT2.1 (disputes.md D-R2-1) |
| blind acceptance tests alone (`bench/ozmap_rep/acceptance`, unedited) | 288 passed |
| red team tests (`bench/ozmap_rep/redteam`, unedited) | 21 passed, RT2.1 failed on its three disputed assertions only; its leakage assertion holds |
| new regressions `bench/ozmap_rep/tests/test_council_r2.py` | 59 passed |
| dry run `python -m bench.ozmap_rep.run dry --run-dir <D>` | exit 0: 16 of 16 cells complete, 52 fake calls, 0 external calls, within every A4.4 bound, report with 0 leakage, 0 accounting failures, 0 artifact problems |

Harness tests of round 1 changed where round 2 changed the semantics they pinned (all in `tests/`, none in
`acceptance/` or `redteam/`): the certificate fixture uses the new telemetry evidence; the account keyed credential
store replaces the empty home detour; the Live fixture's owner reading carries an event timestamp; the telemetry crash
test now expects the call judged from its raw stream; the signed transport notice test checks exact matching; the
dead runner test uses a spawned marker with a journaled pid (a pid-less marker is now ambiguous).

### Blocker dispositions

| id | disposition | where | tests (`tests/test_council_r2.py` unless named) |
|---|---|---|---|
| 1, B4 | The argv carries `-c cli_auth_credentials_store="file"` and `--enable skip_host_skill_discovery` (config.ROUTE_SECURITY_ARGS, required by `argv_check`); `secret_auth_storage` is disabled. Telemetry runs `login status` at all four worker paths, emptied, before the exec probe and after the call, and replaces the empty home exec probe by a probe at a worker path whose auth.json keeps the baseline's account metadata with tokens no server accepts (`isolation.scrambled_auth`): a credential store keyed by account data from auth.json would answer it. The certificate requires all eight statuses not logged in, that probe ending in an authentication failure, and the call's recorded file store at a prepared worker home. Telemetry stays at two charged calls per attempt. Attribution by implementation analysis or an access trace (D1) is a freeze prerequisite (rulings.py), not a runtime predicate | `TelemetryRun`, `isolation.telemetry_certificate` | `test_item1_an_argv_without_the_file_credential_store_is_refused`; r1 file: `test_item1_live_telemetry_with_an_alternative_credential_source_is_not_certified` (account keyed store), `test_item1_a_credential_keyed_by_a_worker_path_is_not_certified` |
| 3, B3, RT2.1 | Raw stdout and stderr go to `D/homes/raw-<slot>/` files (the credential boundary). Markers move `reserved`, `spawning` (before Popen), `spawned` (pid and creation time), `recorded`. after_group writes the call record, the captures with a per channel redaction record, the attempt row, then `recorded`, then deletes the raw files. Recovery judges an orphan from its capture, else its raw stream (promoted only when every prepared secret fingerprint is covered, else quarantined and Codex stops), keeps the terminal outcome and never resends it; only without a stream is it `interrupted` with an uncertain verdict. A pid journal failure or an exception while waiting kills the process tree; with termination established the call is judged from its raw stream and Codex stops; without it the marker, home and raw stream stay, the attempt is not recorded, Codex stops and the batch is never resent. A pid-less marker that may have started is ambiguous. The scorer judges every capture | `spawn`, `CellRun.execute`, `after_group`, `recover_inflight`, `score_run` | `test_item3_a_crash_between_capture_call_record_and_attempt_row_never_resends` (ok, refused, executed at two crash points), `test_b3_an_orphan_without_any_stream_is_uncertain_leakage`, `test_item3_a_pid_journal_failure_stops_codex_and_records_the_terminated_child`, `test_item3_a_communicate_exception_with_a_live_child_keeps_the_home_and_stops_codex`, `test_item3_a_spawning_marker_without_pid_is_kept_and_its_batch_never_resent` |
| 5, C3 | `worker_probe` inspects the probe's error channels (and, for `login status`, the login state) before reconciliation; an authentication failure is sticky and stops Codex, nothing is propagated. `record_features` requires exit 0, a structurally valid inventory (no duplicate, boolean states), every frozen disable option listed and off except `stays_enabled`, `skip_host_skill_discovery` on, and no authentication failure; otherwise exit 14 before any charged call; the record carries `ok`, which the scorer requires | `worker_probe`, `record_features`, `score_run` | `test_item5_a_features_auth_failure_with_changed_worker_auth_stops_codex_and_keeps_the_baseline`, `test_item5_a_failed_or_empty_features_response_blocks_launch` |
| 6, C5 | The prepared credential strings stay in memory from preparation (`Isolation.prepare` returns them; only their sha256 fingerprints reach the marker) and are united with the worker's and the baseline's current ones; sanitizing happens before reconciliation; `redact.channels` keeps a record per channel with original and sanitized sha256; probe output is redacted with its prepared secrets and disclosures are logged; Sonnet captures go through the generic patterns | `CellRun.secrets`, `run.sanitize`, `redact.channels` | `test_item6_a_prepared_opaque_refresh_token_is_redacted_after_a_refresh_and_a_reseed`, `test_item6_redaction_keeps_a_record_per_channel` |
| 7 | `isolation.executable_identity` records an explicit companion manifest: for the standalone 0.160.0 install every file of the package root (`codex-package.json`: bin/codex.exe, bin/codex-code-mode-host.exe, codex-resources/*, codex-path/rg.exe; 44 files besides codex.exe), for a launcher script its parsed targets and their package trees (fail closed when no target is found), for anything else the files named after it. Every launch group is verified once and the Windows write guard (`isolation.WriteGuard`, FILE_SHARE_READ only) is held over every manifest file until the group's children have ended; live mode refuses without it; each child gets a final check (path and size and time of every manifest file) immediately before Popen and a mismatch records `not_launched` and stops with exit 14 | `Executables.verify`, `guard`, `recheck`, `CellRun.final_check` | `test_item7_an_executable_changed_after_group_verification_before_a_spawn_is_refused`, `test_item7_the_write_guard_blocks_substitution_while_a_group_runs`, `test_item7_a_wrapper_target_changed_in_a_subdirectory_is_refused`, `test_item7_the_native_package_manifest_lists_every_companion` |
| 9, RT2.2 | `experiment.json` carries immutable `run_id` and `experiment_id` UUIDs (the experiment id is written once beside the ledger); every reservation gets an `attempt_uid`. The live budget counts the experiment ledger (every run directory) plus this directory's attempts, deduplicated by attempt uid. Live runners also hold `experiment.lock` beside the ledger. The ledger parses strictly (torn lines, conflicting duplicates). A replacement directory refuses a cell whose batches ended terminally in a superseded directory or whose predecessor evidence is missing (telemetry excepted). The freeze hashes the disposition. The scorer reports ledger totals per allocation and the telemetry cap over all directories and imports superseded leakage, stops and safety kills | `CellRun.budget`, `ledger_rows`, `superseded_terminal_batches`, `freeze_command`, `score_run` | `test_item9_migration_after_a_telemetry_failure_keeps_every_old_and_new_call_counted`, `test_item9_a_replacement_directory_never_repeats_a_terminal_batch`, `test_item9_competing_runners_of_old_and_new_directories_cannot_reserve_independently`, `test_item9_a_torn_ledger_line_is_an_accounting_failure`; red team RT2.2 |
| B2, RT2.3 | A group is staged without any charge, then reserved as a whole under the locks: shared prerequisites revalidated (stops, the baseline each member was prepared from, token separation, the Codex quota gate), markers in phase `reserved`, then the ledger rows. `IsolationError` is caught with `Stop`. A member failing its final check after the reservation gets a charged `not_launched` row with zero usage; a `reserved` marker found by recovery becomes one too | `run_batches`, `reserve_group`, `abandon` | `test_b2_a_third_member_failing_verification_leaves_no_ledger_row`, `test_b2_a_reserved_marker_becomes_a_charged_not_launched_attempt`; red team RT2.3 |
| 10 | The scorer derives every accounting field again from the capture with the frozen predicates (`run.account_usage`, shared with the runner and recovery: decoded usage, usage status, reasoning issue with the pinned tokenizer, additive and charged tokens, cache certification evaluated by the scorer, visible tokens), compares bootstrap proposals byte for byte with the capture, takes admitted ASTs and reproduces admission from the capture derived bytes, derives audit dispositions again from verified calls and refuses rule answers of an operation whose audit did not agree, and compares each live Codex launch identity (executable, argv, companion manifest) with the run bound freeze | `score._rejudge`, `_cell_chain`, `_launch_problems` | `test_item10_an_altered_accounting_field_alone_withholds_claims` (six fields), `test_item10_an_altered_bootstrap_proposal_is_detected`, `test_item10_an_altered_audit_disposition_is_detected`, `test_item10_a_launch_identity_differing_from_the_bound_freeze_withholds_claims` |
| 14 | `windows.jsonl` holds an `open` row before any work and a `close` row after the result delivery boundary (result.json and DONE or SETTLED written). Recovery closes an open window of a dead invocation with `ended_at_lower` (its last durable work timestamp) and `ended_at_upper` (the recovery time), never an exact end. The scorer takes the union of windows (overlaps merge), gives lower and upper makespans, and makes the evidence incomplete for an unclosed window or an attempt outside every window. Gates use the upper bound for the arm under test and the lower bound for the reference arm (warm: `upper(C) <= 0.9 * lower(A)`; magnitude: `lower(A) / upper(C)`) | `CellRun._window_open`, `_window`, `close_dead_windows`, `score._window_spans`, `gates._span` | `test_item14_a_crash_before_the_window_closes_keeps_the_work_in_the_gated_makespan`, `test_item14_an_attempt_outside_every_window_makes_the_cell_incomplete` |
| 31, B8, RT2.5 | P3 implemented except the dropped flag (disputes.md D-R2-2): the owner reading is the last rate_limits object of the newest session file, validated after selection (no fallback), finite, in [0, 100], not a boolean, not future dated, not another account; its EVENT timestamp is the only freshness evidence. Before every synchronized Codex dispatch group, telemetry included, every completed live Codex call of the experiment must be covered by its own harvested rollout reading or an owner reading timestamped after its end; the highest covering percentage must be below 80. The telemetry probe with unaccepted tokens needs no coverage (it cannot authenticate as the account). Worker rollouts are harvested by `Isolation.finish` (metadata only) | `quota.coverage_gate`, `CellRun.codex_quota_gate`, `reserve_group` | `test_item31_*` (unrelated events, malformed latest reading, other account, crossing 80 between groups, own rollout coverage, probe exemption); red team RT2.5 |
| 32, B5 | P1 (Astra, operative): `SIGNED_TRANSPORT_NOTICES` stays empty and matching is exact, never a prefix, and never in a stream with a tool item. P4: `code_mode_host` stays disabled; `events.signed_cli_notice` accepts only an `item.completed` event with exactly the approved outer keys, an error item of exactly {id, type, message}, an identifier matching the approved syntax and the complete approved message; inactive until `SIGNED_CLI_NOTICES`, `SIGNED_CLI_NOTICE_EVENT_KEYS` and `SIGNED_CLI_NOTICE_ID_RE` are filled from the approved annex. The candidate message is archived as `config.P4_CANDIDATE_NOTICE` (Fable F6) | `events.classify_stream`, `config` | `test_item32_*`, `test_b5_transport_notices_never_match_a_prefix_and_never_with_a_tool_item` |
| 33, B6 | P5 (Astra, operative): `--enable skip_host_skill_discovery` on the argv; startup files are accepted only by exact path AND sha256 from the approved manifest `bench/ozmap_rep/startup-manifest.json` (absent: nothing accepted); `Isolation.finish` hashes every runtime file; the certificate checks the probe and the call inventories. The effective context evidence (D2) is a freeze prerequisite | `isolation.startup_instruction_files`, `startup_manifest`, `TelemetryRun.arm` | `test_item33_startup_files_need_an_approved_manifest_entry_by_path_and_hash`; r1 file: `test_item1_live_telemetry_with_a_startup_skill_file_is_not_certified` |
| B1 | `rulings.py`: `freeze_command` refuses with exit 14 until every slot of `config.REQUIRED_RULINGS` (P1, P2, P3, P4, P5, D1) names a ruling file whose exact bytes hash to the recorded value and carry both signatures, and the configuration matches (the P4 notice predicate active while `code_mode_host` is disabled, an approved startup manifest present). `verify_freeze` repeats the readiness check, so live cells refuse too; `freeze.json` binds the ruling files, the CLI notice slots, the startup manifest hash and the route security arguments. Telemetry refuses the charged worker call when the probe's startup inventory holds an instruction bearing file the manifest does not list | `rulings.py`, `freeze_command`, `verify_freeze`, `TelemetryRun.arm` | `test_b1_*` |
| B7 | P2 (Astra, operative): unknown usage stays incomplete; a possible launch without a usable stream is uncertain and leakage; a proven not launched call has zero usage. The report carries `unknown_usage_observation`, labeled a hypothetical substitution and never read by `gates.evaluate` | `score._unknown_usage_observation` | `test_b3_an_orphan_without_any_stream_is_uncertain_leakage` |
| RT2.4 | More than one `turn.started` or `turn.completed` makes the stream uncertain, and `_turn_usage` returns no usage (incomplete); the scorer inherits both | `events.classify_stream`, `run._turn_usage` | `test_rt2_4_two_turns_are_uncertain_and_their_usage_incomplete`; red team RT2.4 |
| RT2.6 | SHA256 of the baseline's access and refresh tokens (and API key) against the owner's `~/.codex/auth.json` and the runner's CODEX_HOME: at every Codex cell gate, before every group reservation and under the authentication lock before every worker reconstruction (live). Equal hashes, an unreadable owner document or a baseline at an owner path refuse with exit 11 and `CODEX_HOME=~/.ozmap_rep/baseline codex login`. `evidence/auth-lineage.jsonl` records token hashes at first dispatch, after every propagation and on every observed baseline change; wave gate rows carry hash, last_refresh and exp (C2) | `isolation.token_separation_problems`, `CellRun.separation_gate`, `run.lineage` | `test_rt2_6_*`; red team RT2.6 |

CHANGE items adopted: C1 (isolation errors become a stop with an INTERFACE.md code), C2, C3, C5. Not adopted in this
step: C4 (per job added errors for the correctness gates), Astra 15 (completion by job coverage), 21 (Sonnet
contradictions behind missing counters) and 22 (preparation breakdowns); none is a blocker and each keeps its round 2
text for the next round.

### Readings where A4 is silent (the stricter validity reading)

Readings 1 to 8 of round 1 stand, with these changes and additions.

1. Reading 2 (spawn exceptions) is now implemented as stated: an exception after the child exists never makes a call
   retryable; Codex stops. An exception before Popen (no process) is a proven `not_launched`, retryable only from the
   reserve.
2. Reading 7 (replacement directories): a replacement directory never repeats a batch that ended terminally in a
   superseded directory; carrying terminal outcomes into the new directory is not implemented, so such a cell is
   refused there (exit 15). Telemetry is the exception, because certifying the new directory is the purpose of the
   migration; its cap counts over every directory.
3. Reading 8 (launcher payload) is replaced by the explicit manifest of item 7.
4. `--ephemeral` stays (A4.2 text and the acceptance suite over the joint decision, disputes.md D-R2-2).
5. Quota coverage for the first Codex group of an experiment is vacuous: the latest owner reading needs only a valid
   percentage below 80 then, with or without a timestamp. Every later group needs coverage by event timestamps.
6. A pid-less Sonnet marker that may have started is kept and its batch is never resent, without stopping Codex.
7. The token separation check compares access and refresh tokens and API keys, not id tokens (an owner login always
   issues new access and refresh tokens; id token equality alone proves nothing).
8. A recovered capture that differs from its raw stream file is uncertain and enters leakage.

### Pending rulings and evidence (the freeze refuses until they are settled)

`python -m bench.ozmap_rep.run freeze` refuses today with these readiness problems (rulings.readiness_problems):
P1, P2, P3, P4, P5 and D1 are not settled (the texts in the joint decision section 3 are signed by Astra A only and
need Opus B confirmation by diff, then their files and hashes go into `config.SIGNED_RULINGS`); the P4 notice
predicate is inactive while `code_mode_host` is disabled (it needs the archived outer event fixture and identifier
syntax approved by both signatories); there is no approved startup manifest (P5; D4 decides whether it comes from a pre
freeze no auth exec probe with the final argv or from the stop, approve and refreeze path). D1 needs implementation
analysis or a credential access trace of the pinned binary; D2 needs proof that the rollout records the complete
effective request; D3, D5 and D6 are for Opus B as written in the joint decision.

### Preparation calls after this step

Astra 11 of 20, Opus 22 of 40, Fable 2 of 4, Sonnet 1 of 40 (ledger sums, this implementer included). Evaluation calls
so far: 0 Codex, 0 Sonnet. Driver quota at the start of this step: Claude weekly all models 68%; Codex primary 41%.
