# Round 3: reuse map (Opus A)

`oz do` is already the engine. One `oz map` call expands to one `oz.do/1` request: `ops` holds the template, `refs`
one `{"path"}` per file, `jobs` `[[id, op, ref]]` (oz_do.py:89, at most 256 jobs). Rules use the memo hook.
Only pooling does not fit the existing queue.

## Components

| Component | Verdict | Where | Minimal change | Size |
|---|---|---|---|---|
| Leases, settlement in one run | reuse as is | oz_runtime.py:362 `claim_prepared`, :808 `settle_dispatch`, :861 `_apply` | none | 0 |
| Shared queue across producers | do not reuse | oz_runtime.py:287 `waiting`, oz_workspace.py:177 `Workspace.run` | new spool and drainer (note 3) | ~120 |
| Per-job checks and acceptance | reuse as is | oz_accept.py:210 `run_checks`, :240 `decide`, :140 `REGISTRY` | new check `oz_rule_ast` for the compile job | ~15 |
| Admission on a labeled set | reuse as is | oz_accept.py `expect` check (`BUILTIN`, :127) | rule per example, `expect` pinned to the label | ~40 |
| Rule store | reuse as is | oz_memo.py:66 `publish`, :85 `revoke`, :114 `record` | namespace `rule:<contract sha>`, value = AST | 0 |
| Rule hit adoption | reuse with change | oz_runtime.py:980 `adopt_memo` | receipt prefix parameter, `memo:` or `rule:` | ~6 |
| Rule phase | reuse with change | oz_do.py:472 memo hook, :577 `_memo_phase` as template | `_rule_phase`: evaluate, check, adopt or abstain; audits stay on the model path | ~70 |
| Laundering guard | reuse with change | oz_do.py:616 `_memo_publish` skips `memo:` | also skip `rule:`; oz_do.py:549 evidence gets `rule_entry` | ~3 |
| Model-free host routing | do not reuse | oz_batch.py:265 host slots, oz_worker.py:543 `_host_only` | none: they fill packet slots, and a rule must stay out of the packet | 0 |
| DAG executor and handoffs | do not reuse | oz_flow.py:132 `admit`, :686 `_execute`; oz_runtime.py:348 `_handoffs` | none: `map` has a fixed shape; `--from` later is a second request | 0 |
| Claude adapter | reuse as is | examples/claude_cli_adapter.py | none | 0 |
| Codex adapter | new | bench/codex_kit_1g/run_codex.py:15 as model | system prepended to stdin, usage from `turn.completed` | ~60 |
| Durable runner, quota slot | reuse as is | oz_runner.py:91 `publish`, oz_quota.py:80 `acquire` | none | 0 |
| Ledger and accounting | reuse with change | oz_worker.py:555 `_call_end`, oz_do.py:250 `_accounting` | per-producer split by job share; compile, work, audit tags | ~40 |
| CLI | reuse with change | oz_cli.py:28 `main`; adapter required at :55, oz_do.py:439 | `map` subcommand, default adapter, JSONL output, one-line receipt | ~75 |

Notes:
1. Codex telemetry is not a blocker: USAGE_MAP (oz_worker.py:30) already expects `cached_input_tokens` and
   `reasoning_output_tokens`, and bench/codex_kit/results_gpt-6-astra_high.jsonl records both. That record had
   28,652 input tokens, so the Codex call floor may be far above Claude's. Whether `input_tokens` includes cached
   tokens is UNVERIFIED.
2. `adopt_memo` refuses a hit unless some job-bound check passes (oz_runtime.py:987). Keep it: `--learn`
   then works only on ops with `quoted_span` or `expect`, so a BoolQ op checked by `one_of` never adopts a rule.
3. Not the workspace queue: `take_over` (oz_runtime.py:622) fences older coordinators, so producers cannot each
   drain; that path also lacks memo, quota and accounting. Producers publish fragments atomically
   (oz_runner.py:91); one drainer holding `_RunLock` (oz_manual.py:99, moved to a neutral module) merges fragments
   with equal contract hash (goal, ops, checks, model) into one `do()` request, IDs prefixed per producer, flushing
   at 64 jobs or after the wait.
4. Compile is a one-job `do()` request whose value is the AST. `oz_rule.py` (~180 lines) follows Astra's grammar.

## Dead weight for this design

Freeze, do not delete; O1 evidence and tests use some.
1. oz_flow.py (1,082 lines), oz_manual.py (502): off the map path.
2. oz_manual.py:223 `_accounting` duplicates oz_do.py:250; a parity test keeps them equal.
3. The header-profile workspace commands `send`, `plan`, `run`, `events` (oz_cli.py:57 to 77, oz_workspace.py:177).
4. Size cells (oz_do.py:50): no Codex rows, so Codex calls are labeled experimental.
5. Old protocol: akor.py, benchmark.py, demo.py, oz2_benchmark.py, examples/oz2_* (tests/test_akor.py imports akor).

## Build order (fake adapters only, no model calls)

1. Codex adapter. Test: a fake `codex` replays recorded events; usage maps with reasoning tokens. ~60 lines.
2. `oz map` expansion, default adapter, results writer. Test: `plan_only` (oz_do.py:628), then a fake adapter.
   ~150.
3. `oz_rule.py`, `oz_rule_ast`, labeled admission. Test: unknown nodes refused, every path yields value or abstain.
   ~235.
4. Rule store, rule phase, audits. Test: hit adopted at zero calls, abstain dispatched, audit
   disagreement revokes, `rule:` receipts never published as memo. ~80.
5. Spool, drainer, pooling. Test: two scripted producers share one fake call; flush by count and by wait. ~120.
6. Attribution and replay harness. Test: producer shares sum to calls.jsonl totals. ~40.

About 700 lines in all, mostly new modules; the existing core changes by fewer than 15.
