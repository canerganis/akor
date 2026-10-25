# Harness interface fixed by the acceptance tests

The tests in this directory were written from `docs/design/ozmap-replication-2026-10-24/amendment-4.md` (A4.x) and
`amendment-4-13-caps.md` (A4.13.x) before the harness exists. This file fixes the interface the harness must have.
The builder implements it; a test that needs a different shape is a defect of this file and is changed here first,
never silently in the tests.

Package: `bench.ozmap_rep` (namespace or regular package, run from the repository root). Standard library only,
except for reuse of frozen modules (`examples/`, `bench/ozmap/*`, `bench/ozmap_rep/ops`). Frozen files are never
edited (test_a4_1).

## Guard: how the suite goes from skipped to red

`conftest.harness(name)` imports `bench.ozmap_rep.<name>`.

* `bench/ozmap_rep/run.py` is the sentinel. While it does not exist, `harness()` skips ("harness not built") so that
  `python -m pytest bench/ozmap_rep/acceptance --collect-only -q` collects cleanly, and `test_harness_exists`
  fails, so the suite is red from the start.
* Once `run.py` exists, a missing module, a failed import or a missing attribute is a failure, never a skip.
* `OZMAP_REP_STRICT=1` turns the not-built skip into a failure as well.

## Layout of a run directory `D`

```
D/auth/baseline/auth.json        default baseline (tests pass --baseline explicitly)
D/homes/worker-0..3/             worker CODEX_HOME, rebuilt before every Codex call
D/work/slot-0..3/                empty working directories (the -C argument)
D/evidence/                      isolation evidence, hashes only, outside homes and work dirs
D/attempts.jsonl                 every attempt, append only, refused and failed ones included
D/prompts/<call_id>.txt          the complete text of every model-bound prompt
D/fake_calls.jsonl               fake mode only: one line per fake CLI invocation (schema below)
D/cells/<cell id>/state.json     {"state": "pending|running|interrupted|incomplete|complete", ...}
D/cells/<cell id>/DONE.json      present exactly when the cell completed
D/report.json, D/report.md       written by the scorer
```

## `bench.ozmap_rep.run` (CLI and `main(argv) -> int`)

* `python -m bench.ozmap_rep.run plan --list-cells` prints one JSON object per line, one line per cell, nothing else
  on stdout, exit 0. Keys: `id`, `command`, `backend`, `workload`, `wave`, `arm`, `nominal_calls`, `requires`.
  16 cells: for `codex` and `sonnet` on `materials`: `<b>-materials-bootstrap`, `-cold-A`, `-cold-B`, `-cold-C`,
  `-warm-A`, `-warm-C`; for `codex` on `boolq`: `codex-boolq-bootstrap`, `-cold-A`, `-cold-B`, `-cold-C`.
  `command` is exactly `python -m bench.ozmap_rep.run cell <id>`. `nominal_calls` follows A4.5. `requires` lists
  cell ids that must be complete first: cold B and C and warm C require their backend/workload bootstrap cell.
* `python -m bench.ozmap_rep.run cell <id> [--run-dir D] [--mode fake|live] [--baseline P]
  [--codex-sessions-dir P] [--claude-weekly-percent X] [--stop-after N] [--fake-fail N] [--fake-refresh K]`.
  A4.14.1 (fail closed, replaces resumption): a cell runs once; an interrupted cell is never resumed or rerun and
  is refused with 19, a cell whose prerequisite was interrupted is interrupted without running (75), and 20 means
  the run is stopped because containment of outstanding work was not established. Exit codes: 0 complete,
  3 cell already complete (refuses, makes no call), 4 required cell not complete (no call), 5 budget or reserve
  exhausted or cell incomplete, 10 quota stop (Codex primary used_percent >= 80 or Claude weekly >= 99, before any
  call), 11 baseline authentication gate failed (A4.2, before any call), 75 interrupted (`--stop-after`).
  `--mode fake` uses fake `codex` and `claude` executables owned by the harness, never a real CLI. `--stop-after N`
  stops with 75 after N fake calls of this invocation. `--fake-fail N` makes the first N fake calls of this
  invocation fail with an infrastructure error (nonzero exit, no reply). `--fake-refresh K` makes the K-th fake
  Codex call of this invocation rewrite its worker `auth.json` with new content (token refresh simulation).
  In live mode the quota, baseline expiry and isolation gates run before the first spawn.
* `python -m bench.ozmap_rep.run dry --run-dir D` runs every cell in dependency order in fake mode with zero rules
  (fake learner proposes `none`) and the worst permitted audit placement, scores the result, writes
  `D/dry_report.json` with keys `external_calls` (int, must be 0), `fake_calls` (int > 0), `cells`
  ({id: {"state", "physical_calls"}}), `capacity` ({id: {"scheduled_calls", "bound"}} for every non-bootstrap cell)
  and `real_cli_resolved` (list, must be empty), and exits 0. The fake model answers every job with the gold label.
  Dry needs no baseline argument: it creates a synthetic baseline inside D with an access token valid 30 days.
* Every model-bound prompt is written to `D/prompts/`. Learner prompts never contain an admission case text or label.

### Fake behavior (fake mode and dry)

* The fake model answers every job with the gold label. The fake learner (bootstrap) proposes the JSON string
  `none` for every operation, so no rule is admitted (the zero-rule budget case of A4.4).
* `--fake-refresh K`: the K-th fake Codex call of the invocation rewrites `$CODEX_HOME/auth.json` with a document whose
  access token (an unsigned JWT with `exp` 20 days ahead and the claim `marker`) and refresh token contain the text
  `SECRET-FAKE-REFRESHED`, and a `last_refresh` of now. The harness must then propagate it to the baseline and must
  never write that text, or any original token text, anywhere outside the baseline and the worker homes.
* Fake mode runs the same isolation, budget, quota-free scheduling and scoring code as live mode; only the
  executables differ. Baseline expiry (A4.2) is enforced in fake mode too for Codex cells.

### Fake CLI log line (`D/fake_calls.jsonl`)

```
{"cell": str, "n": int, "cli": "codex"|"claude", "argv": [str...], "codex_home": str|null, "home_listing": [str...],
 "workdir": str|null, "workdir_listing": [str...], "env_names": [str...], "stdin_sha256": str}
```
`home_listing` and `workdir_listing` are the directory listings seen by the fake at call time.

## `config`

`OPERATIONS=('verdict','margin','elong','temp_class')`, `SEED:int`, `FROZEN_ARGS`, `ENV_ALLOWLIST`,
`DISABLE_FEATURES`, `CODEX_MODEL='gpt-6.1-sol'`, `CODEX_EFFORT='high'`, `SONNET_MODEL='claude-sonnet-5-5'`,
`ALLOCATIONS` (`{"codex/materials": {...}, "sonnet/materials": {...}, "codex/boolq": {...}}` with keys `cold_A`,
`bootstrap`, `cold_B`, `cold_C`, `warm_A`, `warm_C`; BoolQ has no warm keys), `RESERVE_PER_ALLOCATION=2`,
`RESERVE_REASONS=('infrastructure_retry','audit_overflow')`, `RESERVE_FORBIDDEN=('new_learning','answer_repair',
'new_condition')`, `EVAL_CAPS`, `PREP_CAPS`, `GLOBAL_CAP=236` (A4.13r1.1), `MAX_BATCH=64`, `AUDITS=32`, `SLOTS=4`,
`CODEX_STOP_PERCENT=80`, `CLAUDE_HANDOFF_PERCENT=99`, `EXP_MARGIN_HOURS=48`.

## `isolation`

* `sha256_file(path) -> str`
* `Isolation(baseline, root, evidence, lock=None, frozen_inventory=None)` (paths)
  * `.prepare(slot) -> {"slot","home","workdir","env"}` rebuilds `root/homes/worker-<slot>` containing exactly
    `auth.json` copied from the baseline, makes `root/work/slot-<slot>` an empty directory, builds the child env.
    Logs hashes only to `evidence`.
  * `.finish(slot, auth_failure=False) -> {"slot","worker_auth_sha256","baseline_auth_sha256","auth_changed",
    "auth_failure","runtime_files"}` inventories every generated file in the worker home except `auth.json`
    (relative names), then removes the runtime state (everything except `auth.json`). No contents returned.
  * `.propagate(slot, lock_timeout=30.0) -> {"before","after"}` (hashes) copies the worker `auth.json` over the
    baseline atomically while holding the authentication lock. Raises `StaleAuth` when the worker `last_refresh`
    is older than the baseline's; raises `LockTimeout` if the lock is not obtained in time.
* `auth_lock(path, timeout=30.0)` context manager, exclusive across handles and processes (flock or LockFileEx).
* `reconcile_auth(baseline_sha256, workers, in_flight=()) -> {"action": ...}`; `workers` is
  `{slot: {"sha256": str, "auth_failure": bool}}`. Actions: `continue`, `wait` (a change or failure exists while a
  call is in flight), `propagate` (with `slot`), `stop_codex` (with `interrupted=True`).
* `baseline_exp(baseline) -> datetime` (aware, UTC) from the access token `exp`; raises `ExpUnreadable`.
  `wave_gate(baseline, now=None) -> {"ok","exp","hours_left","reason"}`; ok when exp >= now + 48 h. A failing
  reason contains the text `codex login`. Neither return value contains any token material.
* `verify_baseline(baseline, frozen_inventory=None) -> [problem]` (anything besides `auth.json` and the frozen
  inventory is a problem), `child_env(home, base_env) -> dict`, `instruction_sources(workdir) -> [Path]`
  (AGENTS.md, AGENTS.override.md, CLAUDE.md in the directory and every ancestor),
  `codex_argv(exe, model, effort, workdir, disable_options=()) -> list`,
  `argv_check(argv) -> [problem]`, `argv_sha256(argv) -> str` (workdir normalized away),
  `plan_disable_options(supported) -> (args, unsupported)`,
  `verify_launch(*, argv, env, workdir, exe_sha256, frozen) -> [problem]`
  (`frozen = {"argv_sha256","exe_sha256"}`), `telemetry_checks(evidence) -> [problem]`.
* Canonical Codex argv: `[exe, 'exec', '--ignore-user-config', '--ignore-rules', '--ephemeral',
  '--skip-git-repo-check', '--json', '-s', 'read-only', '-C', workdir, '-m', model, '-c',
  'model_reasoning_effort="<effort>"', *disable_options, '-']`; the workdir basename is `slot-0..3`.

## `events`

`classify_stream(stdout) -> {"verdict","efficiency_invalid","counts_as_call","answers_accepted","external_read",
"notices","tool_requests","tool_executions","uncertain"}` with `verdict` in `plain`, `refused`, `executed`,
`uncertain`. Rules (A4.3): a plain CLI notice is an `item.completed` error item with exactly `{id,type,message}` and a
message starting with one of `examples/codex_cli_adapter.KNOWN_NOTICES`. A tool item (`command_execution`,
`file_change`, `mcp_tool_call`, `web_search`, `collab_tool_call`) whose last event has `status: "declined"` and no
`exit_code` and no `aggregated_output` is a request intercepted before execution: verdict `refused`, the call counts,
no external read, no efficiency invalidation, answers not accepted. A tool item with an `exit_code`, an
`aggregated_output`, a `result` or status `completed` is an execution: verdict `executed`, `efficiency_invalid`,
`external_read` true. A tool item that is only started, or has an unknown or missing status, or any non-notice error
item, is `uncertain`: efficiency invalid, `external_read` false (not established), answers not accepted.

## `budget`

* `Budget(allocations=config.ALLOCATIONS, caps=config.EVAL_CAPS, log=None)`:
  `.charge(backend, workload, allocation, reason='nominal', outcome=None) -> {"kind": "nominal"|"reserve"}`;
  telemetry is `charge('codex', 'telemetry', 'telemetry')` (caps: Codex 4, Sonnet 2). A `nominal` charge beyond the
  allocation raises `BudgetExceeded`. A charge whose reason is in `RESERVE_REASONS` after the allocation is used
  draws from that allocation's own two reserve calls; a reason in `RESERVE_FORBIDDEN` raises `ReserveMisuse`
  (a subclass of `BudgetExceeded`); a third reserve call raises `BudgetExceeded`. Unused capacity of another
  allocation never covers an overrun. Every charge, including refused and failed outcomes, stays counted.
  `.physical_total(backend)`, `.analytic_calls(backend, workload, allocation)` (the bootstrap call is charged fully
  to both `cold_B` and `cold_C`), `.attempts` (tuple, append only).
* `capacity(producers, bootstrap, audits, M=64) -> {"pooled","local"}` (A4.4 formulas).
* `PrepLedger(path)`: `.log(agent, role, category, purpose, timestamp=None, count=1)` appends a JSON line with keys
  `agent, role, category, timestamp, purpose, count`; `.counts() -> {agent: n}` (summed `count`);
  `.would_exceed(agent, n=1) -> bool`; `.log` raises `CapExceeded` instead of writing when over `PREP_CAPS`.

## `usage`

* `decode_codex(raw, cache_certified=False) -> {"input_tokens","cached_input_tokens","uncached_input_tokens",
  "output_tokens","reasoning_output_tokens","charged_input_tokens","charged_output_tokens","charged_tokens",
  "status","problems"}`; `status` is `complete`, `unverified` (cached > 0 without certification), `invalid`
  (cached > input, a negative count, reasoning > output) or `incomplete` (a required counter missing).
  `charged_input_tokens = input_tokens` (inclusive), `charged_tokens = input + output`.
* `additive_tokens(raw) -> int` is the sensitivity reading `input + cached + output`.
* `reasoning_inclusion(usage, visible)` returns exactly what `bench.ozmap.pilot.reasoning_inclusion` returns.
* `decoder_sha256() -> str` (sha256 of the source text of `decode_codex`).
* `Certificate.from_pair(pair)` with `pair = {"run","route":{"model","effort","cli_version"},"decoder_sha256",
  "calls":[{"input","cached"},{"input","cached"}]}`; `.valid` (equal inputs, different cached counts, cached <=
  input), `.applies(route, decoder_sha256) -> bool`. `load_archived_certificate(path=None)` reads
  `bench/ozmap_rep/certificate/cache-certificate.json`.

## `bootstrap`

* `assess(R, proposed, gold_errors, disagreements, status='ok') -> {"efficiency_invalid_ops","efficiency_valid",
  "completion_failure","measured_errors","rule_learning_claim_allowed"}`. `R` is a set of materials ops,
  `proposed` `{op: bool}` (learner proposed a rule), `gold_errors` and `disagreements` `{op: int}`. Efficiency is
  invalidated only for an op in `R` with a proposed rule and a gold error or an A disagreement. Every other error is
  returned in `measured_errors` and counts toward correctness and overhead. `status != 'ok'` (malformed or missing
  output) is a `completion_failure` and makes efficiency invalid.
* `load_R(path, first_learner_call=None) -> set`: reads the frozen classification JSON
  `{"classified_at": iso, "operations": {op: {"rule_shaped": bool, "inputs", "outputs", "guards", "domain",
  "reasons"}}}`; raises `ClassificationError` when a rule shaped op lacks any of those fields or when
  `classified_at` is later than `first_learner_call`.
* `admission_report(R, admitted) -> {"R","classification_misses"}` (admitted ops outside R are misses; R unchanged).

## `workload`

`materials(seed=config.SEED) -> {"cold": [job], "warm": [job], "admission": {op: [case]}, "bootstrap_ids": [id]}`.
A job is `{"id","op","text","producer"}`; 256 cold and 256 warm jobs, 4 producers x 64, 16 per op per producer, op
from `config.OPERATIONS` only, `bootstrap_ids` the first 16 jobs of each producer (64). Each op has 64 admission
cases `{"text","op","gold","kind"}` with `kind` `representative` (48) or `challenge` (16). `gold(job_or_case) -> str`
equals `bench.ozmap_rep.ops.oracle.gold`.

## `prompts`

`INSTRUCTION_SHA256` (the pilot value), `sonnet_bootstrap_system(system, config)` equal to
`examples/bootstrap_shim.system_text(system, config)`, `SONNET_FLAGS` equal to `claude_map_adapter.FLAGS`,
`sonnet_argv(exe, model, effort, system)` equal to `claude_map_adapter.command(...)`,
`learner_prompt_leaks(prompt, admission) -> [text]` (admission texts or labels found in a prompt).

## `gates`

Summary shape (also what `score` builds):

```
{"cells": {"<backend>/<workload>/<wave>/<arm>": {"jobs","correct","unresolved","tokens","makespan_s","usage",
           "evidence","state","rule_errors","ops": {op: {"jobs","correct","tokens"}}}},
 "validity": {"isolation": "passed"|..., "leakage": [], "accounting_failures": [], "interrupted": [],
              "bootstrap": {"<backend>/<workload>": {"efficiency_valid": bool, "completion_failure": bool}}},
 "R": [op...],
 "R_cells": {"<backend>/<wave>/<arm>": {"jobs","correct","unresolved","tokens","makespan_s","usage","state"}}}
```
`usage` and `evidence` are `complete` or something else; `state` is `complete` or something else.
Tokens per gold correct job is `tokens / correct`.

* `materials_gate(summary, backend) -> {"pass","inconclusive","checks","ratios"}` with `ratios` keys
  `cold_tokens` (C over A tokens per correct job), `cold_makespan` (report only), `warm_tokens`, `warm_makespan`.
  The gate needs cells `<b>/materials/{cold,warm}/{A,C}`; a cell with `state != 'complete'`, `usage != 'complete'`,
  `evidence != 'complete'` or `unresolved > 0` makes the gate `inconclusive` (and not passed). Failed isolation,
  an invalid bootstrap for that backend, leakage or accounting failures make it not pass.
* `boolq_gate(summary)` (cells `codex/boolq/cold/{A,C}`), `pooling_gate(summary)` (cells
  `codex/materials/cold/{B,C}`): same keys, same inconclusive rule. C must have gold errors <= A's, tokens <= 1.10 A and
  makespan <= 1.10 A (BoolQ); C tokens < B tokens, correct >= B correct, makespan <= B makespan (pooling).
* `safety_kill(summary) -> bool` (any materials cell with `rule_errors > 0`)
* `attribute_tokens(total, jobs_by_op) -> {op: int}` summing exactly to `total`
* `per_operation(summary) -> {cell key: {op: {"jobs","correct","tokens","tokens_per_correct"}}}`
* `magnitude(summary, backend) -> {"status","token_ratio","makespan_ratio","direction_replicated","label",
  "missed","scope"}`; `status` is `inconclusive` (unequal correctness, an unresolved job, uncertified usage or an
  incomplete or interrupted cell), `invalid` (leakage or accounting failure), `fail` or `pass`. Ratios are A over C
  and unrounded. `label` is `at least the pilot magnitude` only when tokens >= 4.4 and makespan >= 1.6, else
  `smaller than the pilot` with `missed` naming `tokens` and/or `makespan`; `scope` mentions `R` and
  `new operations`.
* `claims(summary) -> {"codex": {"permitted","rule_learning_claim","pooling_claim"}, "sonnet": {"permitted",
  "rule_learning_claim"}, "cross_backend_headline"}`. `permitted` for Codex needs the materials and BoolQ gates,
  for Sonnet the materials gate; both need passed isolation, valid bootstraps, complete cells and no safety kill.
  `rule_learning_claim` additionally needs a nonempty `R`. `pooling_claim` needs the pooling gate. The headline
  needs both backends permitted, the pooling gate and a nonempty `R`.
* `evaluate(summary)` returns one dict with keys `materials` (`{backend: materials_gate}`), `boolq`, `pooling`,
  `safety_kill`, `claims`, `per_operation`, `magnitude` (`{backend: magnitude}`). It does not mutate its input.

## `quota`

`codex_primary_used_percent(sessions_dir) -> float|None` reads `rate_limits.primary.used_percent` of the last
`rate_limits` object in the newest `*/*/*/*.jsonl` (by mtime). `codex_gate(sessions_dir) -> {"ok","percent",
"reason"}` (stop at >= 80; unreadable is not ok). `claude_gate(weekly_percent) -> {"ok","reason"}` (stop at >= 99).

## `score`

`python -m bench.ozmap_rep.score <run dir>` reads only the run directory, makes no external call, rewrites
`report.json` and `report.md` deterministically (same input, same bytes) and exits 0. `report.json` keys: `schema`
(`ozmap-rep/1`), `cells` (summary cells, 13 keys: five materials cells per backend and three Codex BoolQ arms; the
bootstrap call is charged to the B and C cells analytically), `per_operation`, `budget` (`{backend: {"nominal",
"reserve","telemetry","total"}}`, `nominal + reserve + telemetry == total`, all physical calls), `validity`, `gates`
(the `evaluate` dict), `claims`, `magnitude`, `R`, `preparation`.
`score_run(run_dir) -> dict` is the in-process equivalent.
