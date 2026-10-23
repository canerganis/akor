# Council 1, Opus review of steps 1 to 3

Tests: the three files pass with system pytest (76 passed, 96 subtests; the venv lacks pytest). The interpreter is sound: no eval, depth checked before recursion, 1000 deep JSON abstains as `invalid_ast`, arithmetic uses a local trapped context.

## BLOCKERs

**B1. Route identity and model label (fix before step 4).** `oz_map.py:69` puts `--model` into the request only. Both adapters read `OZ_MODEL` (`examples/claude_cli_adapter.py:55`, `examples/codex_cli_adapter.py:92`), and `execution_route` (`oz_worker.py:602`) records `adapter: "StdioAdapter"`, `effort: null` for every backend. So Claude and Codex runs share one route, and `size_profile` (`oz_do.py:504`) can label a Codex call `qualified_cell` from a Sonnet label. Rule keys and worker-hash pooling would mix backends. Fix: in `oz_map.command`, require `--model` and `--effort`, set `OZ_MODEL`/`OZ_EFFORT` for the adapter process, and pass `route={'adapter': sha256(adapter JSON + script bytes), 'model', 'effort', 'cli_version'}` into `do()`.

**B2. Codex raw telemetry is not retained.** `examples/codex_cli_adapter.py:94-105` never writes `OZ_ENVELOPE_PATH` though the runner keeps that file (`oz_runner.py:151,165`). Record section 4 requires raw telemetry, and a failed turn loses its usage, so coverage goes partial and the validity kill fires. Fix: right after `subprocess.run`, publish `proc.stdout` atomically to `OZ_ENVELOPE_PATH` (reuse the Claude adapter's `_publish`), before the return code check.

**B3. Rule input text versus files (decision before step 4, Astra owns the spec).** `field` abstains on `"length=12.50 mm\n"` and on CRLF (probed). `oz map` reads whole files, so every file ending in a newline gives zero coverage and C looks like A plus overhead. Freeze fixtures without a final LF and test it, or let the spec strip exactly one final LF.

## SHOULD-FIX

1. Receipt totals are run cumulative (`_accounting` reads the whole ledger) while `seconds` is per invocation. A resumed map that made zero calls reports `calls=1 tokens=110` (probed). Report `calls_new` and `tokens_new` too, so a resumed arm is not double counted.
2. One unreadable or empty file raises and aborts the whole map (`oz_map.py:102`). Above 256 files, chunk 1 spends calls before chunk 2 fails. Normalize all chunks first; make bad files failed rows.
3. `--ask` (`oz_map.py:157`): a mistyped filename silently becomes the paid instruction. Add `--ask-file`, or refuse a value that looks like a path and does not exist.
4. A checks dict without the op (`oz_map.py:165`) silently runs unchecked; raise.
5. No pass-through for `deadline_seconds` (600), `max_input_tokens` (workspace default 2048), `max_jobs_per_call`, `call_timeout_seconds`. One job above 2048 tokens blocks the rest with `input_budget`.
6. Codex adapter: a top-level `error` event marks failure even when `turn.completed` and a message follow (`codex_cli_adapter.py:66`). Fail only on `turn.failed` or no message. A missing `codex` gives a TypeError; print a clear error.
7. `oz_rule.admit(eligible=True)` (`oz_rule.py:573`) trusts the caller. Derive eligibility from the package's check specs (a job-bound check is required, `one_of` alone refused) and default to rejection. Also `dataset_hash` is never compared with the cases: hash the canonical cases and reject a mismatch, or the preregistered hash proves nothing.
8. Inclusive usage: the data agrees (cached never above input in 82 calls; one same-prompt pair at 26786 with cached 0 and 7296), as do OpenAI semantics, but it rests on one pair. Spend the telemetry call on one prompt sent twice and assert equal `input_tokens` with higher cached.

## Step 4 and 5 integration risks

1. The memo hook only runs when `memo is not None` (`oz_do.py:472`), and the pilot disables memoization. Add a separate `rules=` hook.
2. `adopt_memo` needs a passing job-bound check (`oz_runtime.py:987`). Checks in `oz map` are per operation, so `expect` cannot be used and only `quoted_span` remains. Computed outputs (B, V, M give `12.48 mm`, `inside`) are absent from the input and can never adopt; only E-like extraction can. Check offline before any call: the 25% gate may rest on E alone.
3. An adopted job is `done`, so audits need their own job IDs (`a-<id>`).
4. `_memo_publish` already skips rule receipts only by accident (`box.dispatch` returns None, `oz_do.py:620`). Add an explicit `rule:` skip and a test. Evidence recognizes only `memo:` (`oz_do.py:550`), and `oz_map.py:116` needs `source: "rule"`.
5. Decimal results serialize as JSON strings (`oz_rule.py:500`). Decide whether OZ/1g carries them as strings or numbers before `json_type` checks see them.
6. Job IDs and ref names depend only on the path (`oz_map.py:50,63`). Two producers mapping `refs/a.txt` collide in a pooled request. Prefix both with the producer ID; ref names cap at 60 characters and are already 53.
7. One added file shifts every later chunk and request ID; resume per job, not per chunk.

## Test gaps

Resume makes zero calls (claimed, untested). Symlink escape, backslash glob, bad file in chunk 2, checks dict missing the op. Adapter: an `error` event followed by success, `codex` missing from PATH, envelope written, and a replay of all recorded bench usage through `validate_usage`. Rule: trailing LF and CRLF pinned, `dataset_hash` mismatch, eligibility derived from checks.

## Pilot improvements

1. Zero-call dry run of the A/B/C harness with a fake adapter replaying recorded Codex usage; assert producer shares sum to `calls.jsonl` and exhaustion stops launches.
2. Before the bootstrap, evaluate the worked E, B, M, V ASTs on the frozen admission set with the real pinned checks. If none reaches coverage 32 with a job-bound pass, save the 50 calls.
3. Report uncached input separately. Pooling raises cache hits.
4. Order arms per wave by the frozen seed so drift hits all arms.
5. Publish per-job JSONL with source (model, rule, audit), audit selection and route hashes.
