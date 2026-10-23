# Code-review sizing pilot: frozen run plan

Status: frozen, not run. Frozen digest `dee0f6ce3efc68091fe9b74bada03dbf820b15d12ce4a0cac360fc107ece2293`
(`bench/codereview/freeze.json`, CLI 2.1.306). Sizing pilot only, as signed in [02](02-astra-pilot-prereg.md) with the
five binding changes of [03](03-opus-changes.md), accepted in [04](04-astra-accept.md). No ranking, no winner, no
adoption decision. Nothing was paid to prepare it: fixtures, sizing, the fill and the dry gate are offline.

## What the digest pins

| Item | Value |
|---|---|
| Fixtures | `bench/codereview/fixtures/codereview-v1`, Astra revision 1 (seed A2 span 25-26, seed span rule in WITNESS_FORMAT.md). Every file hashed; SHA256SUMS sha256 `0cdd88aa206d1feb5db0e0a34ad91cf73df9ba42dd833b50ab1a3d21fe7e87a8`. Record of authorship: [fixtures-as-authored-by-astra.txt](fixtures-as-authored-by-astra.txt), original plus the appended revision |
| Fill | `bench/codereview/fill.txt`, sha256 `1458027af83c200d6219b160db201e672e1a469c80780cbe0f6e541eb41ed22a`, 5,865 o200k tokens: two recorded pilot_k2 sessions of the unrelated materials task (`C-art-J-64-7203`, `B-art-J-16-7001`, J arm, no `oz`), rendered as plain text, screened for answer material (function names, module lines, classes, witnesses, evaluator words): no hit |
| Caller | `claude -p`, claude-sonnet-5-5, default effort, Bash only, pilot_k2 system prompt and flags plus `--max-turns 5`, fresh workspace and session per run |
| Prompts | fill prefix, then six task lines; I and D differ only in the requirement line (byte diff test). Both carry the same `oz do` usage line. Input sha256: A-I `ac52803b...`, A-D `9233fdfa...`, B-D `7a0f9c42...`, B-I `f587ed65...` |
| Workspace | the pack's three modules and WITNESS_FORMAT.md, an oz workspace (packet budget 32,000 tokens), `adapter.json`, the `oz` shim (bench/live/k2_wrap.py, full mode, archived). Identical in both arms |
| Oracle | `bench/codereview/oracle.py` and `eval_worker.py`, evaluator-only, witnesses run in the O1 sandbox (`bench/o1/sandbox.py` imported unchanged, pinned `579417ae...`) |
| Code | pilot.py, oracle.py, eval_worker.py, verify.py, cr_adapter.py, both fixture programs, pilot_k2.py, k2_wrap.py, run_live.py, sandbox.py, claude_cli_adapter.py |
| Environment | checked before every run against freeze.json: CLI version and the oz core files (oz.py, oz_batch.py, oz_reply.py, oz_runtime.py, oz_worker.py, oz_workspace.py, oz_do.py, oz_cli.py, oz_accept.py, oz_memo.py, oz_flow.py). Any drift refuses the run |

## Schedule

Four runs, one at a time, in this order: A-I, A-D, B-D, B-I (pack A in I/D order, pack B in D/I order). No automatic
retries. A finished run is never repeated.

## Arms

1. I: the caller reviews all three modules itself and must not run `oz do`.
2. D: the caller must not read or review any module. It runs one `oz do` call with one job per module, each job
   referencing its module and WITNESS_FORMAT.md by path, `max_attempts` 1, no checks. Three jobs in one packet is an
   experimental size, so the usage line's request template carries `"allow_experimental": true`.
3. Protocol violations are recorded and the run is not scored as its arm: I ran `oz do`; D made no worker call or
   more than one, dispatched a request with `max_attempts` other than 1 or with a profile or checks, did not pass each
   module by path in exactly one of three jobs, or let module content reach the caller (three or more distinct module
   lines of 16 or more characters in any tool input or result).

## Oracle (exact rules)

Strict JSON final answer: one object keyed by exactly the pack's three module paths, values findings arrays or null.
Anything else (fences, prose, wrong keys) makes every file of the run incorrect. Per finding:

| Category | Rule | Counts as |
|---|---|---|
| invalid | record or witness breaks codereview-witness-v1 | unproven and false positive |
| seeded | witness matches on the reference, the shipped call completes without matching, class equals the seed's, line inside the seed's inclusive span | a seed hit |
| mislocated | the same proof, but no seed with that class and span | false positive; the file is incorrect |
| unseeded | witness runs cleanly, fails on shipped and reference, and passes on a fix registered under `data/pilot/fixes/` after human or Astra review | neither correct nor false positive, reported apart, fixture repaired before later runs |
| unproven | anything else, including timeouts and execution errors; a both-fail witness without a registered fix is listed under review_both_fail | unproven and false positive |

A defective file is correct when its proven findings map exactly onto its seed set. A clean control is correct when
its response without unseeded findings is exactly `[]`. Reported separately: recall, false positives, unproven,
unseeded, review_both_fail. No model scores anything.

## Accounting, truncation, caps

1. Caller tokens come from the caller envelope (`modelUsage`, cache reads and writes at full weight). Worker tokens
   come from the `oz do` call ledgers and must agree with the raw worker envelopes kept by cr_adapter.py. Either
   missing or disagreeing makes the run's accounting inconclusive. Total = caller + worker + paid preparation (0).
2. Kept per run under `bench/codereview/data/pilot/<tag>/`: prompt, spec, meta, raw stream-json transcript, caller
   envelope, stderr, every `oz` invocation with its request bytes and output, every worker packet, reply and envelope,
   ledgers, results.json, workspace digests before and after, the record.
3. Truncation is reported as incomplete: `error_max_turns`, a sixth model call, the run cap, the 1,800 s wall timeout,
   or no result envelope.
4. Run cap 60,000 tokens: an in-run guard kills the caller's process tree once per-message caller usage plus worker
   ledger usage reaches it. The guard acts on reported usage, so a run can overshoot by at most one model call. A run
   with incomplete accounting is charged max(60,000, observed).
5. Total cap 250,000 tokens including paid preparation: a run is admitted only if spent plus its full 60,000 fits.

## Admission (before launch, never after)

The weekly quota figure is read just before each run and passed as `--quota-before`. The run is refused, and the
refusal recorded in `attempts.jsonl` with nothing launched, when any of these holds:

1. the reading is missing or not a number;
2. an earlier admitted run has no after-reading (`quota-after`);
3. spent plus 60,000 exceeds 250,000;
4. before + factor x 60,000 + 1 point of display rounding reaches 58%. The factor starts at 2 points per 55,000 tokens
   (2.18 points for a full run, so the first run needs a reading below 54.82%) and rises to the largest observed
   (after - before) / total of a settled run. It never falls on a rounded zero. 60% is the ceiling, not headroom.

## Findings size against the inline limit

Expected per-file `oz do` values: 168, 149, 2, 164, 152 and 2 bytes. The largest single finding is 166 bytes, so 24
fit under the 4,096-byte inline limit. No artifact read turn is expected. If a value is larger, `oz do` writes it to
`value_file`, the usage line says so, and reading it costs a caller turn inside the five.

## Dry gate (zero tokens, fixture caller and fixture worker)

`pilot.py dry` passes all eight scenarios with 0 rejudge mismatches:

| Scenario | Exercises | Result |
|---|---|---|
| I-clean | arm I end to end, perfect answer | valid, 3/3 correct |
| D-mixed | arm D end to end; mislocated, unproven and clean-control false positive | valid, 1/3, FP 3, unproven 2 |
| D-violation | D caller reads a module | protocol_violation, not scored as arm |
| I-truncated | `error_max_turns` after five calls | truncated, 0/3, cost recorded |
| I-malformed | fenced findings JSON | answer invalid, 0/3 |
| D-unseeded | a real unseeded defect with a registered fix | unseeded, 3/3, FP 0 |
| I-oz-violation | arm I runs `oz do` | protocol_violation |
| I-cap | usage past 60,000 | killed by the guard, charged 76,500 |

## Run procedure

From the repository root in Git Bash, with `<repo>` the repository path. Read the weekly figure just before each run
and put it in place of `PCT`; after each run, read it again and settle it.

1. Check: `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/verify.py`
   and `.venv/Scripts/python.exe bench/codereview/pilot.py freeze` must print ALL PASS and freeze holds.
2. Run 1 (A-I):
   `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/pilot.py run --expect dee0f6ce3efc68091fe9b74bada03dbf820b15d12ce4a0cac360fc107ece2293 --quota-before PCT`
   then `.venv/Scripts/python.exe bench/codereview/pilot.py quota-after --percent PCT`
3. Run 2 (A-D):
   `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/pilot.py run --expect dee0f6ce3efc68091fe9b74bada03dbf820b15d12ce4a0cac360fc107ece2293 --quota-before PCT`
   then `.venv/Scripts/python.exe bench/codereview/pilot.py quota-after --percent PCT`
4. Run 3 (B-D):
   `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/pilot.py run --expect dee0f6ce3efc68091fe9b74bada03dbf820b15d12ce4a0cac360fc107ece2293 --quota-before PCT`
   then `.venv/Scripts/python.exe bench/codereview/pilot.py quota-after --percent PCT`
5. Run 4 (B-I):
   `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/pilot.py run --expect dee0f6ce3efc68091fe9b74bada03dbf820b15d12ce4a0cac360fc107ece2293 --quota-before PCT`
   then `.venv/Scripts/python.exe bench/codereview/pilot.py quota-after --percent PCT`
6. `pilot.py report` prints the per-run table (caller turns, caller tokens, cache reads and writes, worker tokens,
   total, time, correctness, recall, false positives, unproven) and the fill-slope estimates for 60k and 120k fills.
   `pilot.py rejudge` rebuilds every record from its raw data and must report 0 mismatches.

Each `run` command runs the next unrecorded run of the schedule. After a crash, the same command first rebuilds a run
whose raw data was kept (never re-running it) or records an attempt without raw data as aborted, charged 60,000; that
run is repeated only after its after-reading is settled. Stop at once if a reading reaches 58%, if admission refuses,
or if a run shows an isolation breach or an unseeded review item.

## Notes and deviations

1. The evaluator storage is on the same disk as the workspace. It is unreachable by layout (the workspace and every
   worker packet hold none of its bytes, tested), the caller environment carries no repository variables, and a
   tripwire marks a run `isolation_breach` when a tool input names the repository or evaluator files or a tool result
   holds evaluator-only text. This is bench-grade, not an OS boundary. The worker has no tools.
2. "Valid unseeded" needs a passing fix (01, item 6). The oracle cannot judge a both-fail witness's expectation, so
   without a registered fix it stays unproven and goes to review; otherwise a clean control could hide a false
   positive behind any wrong expectation.
3. Literal 02 rule for defective files: unproven extra findings do not make a defective file incorrect; they count as
   false positives and unproven.
4. The `--max-turns` flag is not listed in `claude --help` for 2.1.306 but the option parser accepts it; the in-run
   guard enforces five model calls independently.
