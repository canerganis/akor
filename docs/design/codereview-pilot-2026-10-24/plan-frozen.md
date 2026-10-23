# Code-review sizing pilot: frozen run plan

Status: frozen at digest `a62bd3910ff90408861a555bc0e378f16b7ba0d36c57322a5e873a1c9f1d46f5` (`bench/codereview/freeze.json`,
CLI 2.1.306), not run, and **not yet runnable**: the witness domain specification is provisional until Astra answers
the questions under "Witness domains". Until then `pilot.py run` refuses before admission and nothing is recorded. The
answers will change the oracle, so the digest and the four commands below change with them.

Sizing pilot only, as signed in [02](02-astra-pilot-prereg.md) with the five binding changes of
[03](03-opus-changes.md), accepted in [04](04-astra-accept.md). No ranking, no winner, no adoption decision. Nothing
was paid to prepare it. This revision answers Astra's review of the first harness (five findings, all fixed with
failing tests first).

## What the digest pins

| Item | Value |
|---|---|
| Fixtures | `bench/codereview/fixtures/codereview-v1`, Astra revision 1 (seed A2 span 25-26, seed span rule in WITNESS_FORMAT.md). Every file hashed; SHA256SUMS sha256 `0cdd88aa206d1feb5db0e0a34ad91cf73df9ba42dd833b50ab1a3d21fe7e87a8`. Authorship record: [fixtures-as-authored-by-astra.txt](fixtures-as-authored-by-astra.txt), original plus the appended revision |
| Fill | `bench/codereview/fill.txt`, sha256 `1458027af83c200d6219b160db201e672e1a469c80780cbe0f6e541eb41ed22a`, 5,865 o200k tokens: two recorded pilot_k2 sessions of the unrelated materials task (`C-art-J-64-7203`, `B-art-J-16-7001`, J arm, no `oz`), screened for answer material: no hit |
| Caller | `claude -p`, claude-sonnet-5-5, default effort, Bash only, pilot_k2 system prompt and flags plus `--max-turns 5`, a fresh run root per run |
| Prompts | fill prefix, then six task lines; I and D differ only in the requirement line (byte diff test); both carry the same `oz do` usage line. Input sha256: A-I `ac52803b...`, A-D `9233fdfa...`, B-D `7a0f9c42...`, B-I `f587ed65...` |
| Runtime snapshot | committed runtime from the git objects at `47992b4867b49b053eb868ad51d3d020fae19653` (oz.py, oz_accept, oz_batch, oz_cli, oz_do, oz_fault, oz_memo, oz_reply, oz_runner, oz_runtime, oz_worker, oz_workspace, bench/live/k2_wrap.py, examples/claude_cli_adapter.py), the pilot's cr_adapter.py and fixture_worker.py, tiktoken 0.14.0, tiktoken_ext, regex 2026.9.29 and the o200k cache: every file pinned in freeze.json |
| Oracle | `bench/codereview/oracle.py` and `eval_worker.py`, evaluator-only, witnesses run in the O1 sandbox (`bench/o1/sandbox.py` imported unchanged, pinned `579417ae...`) |
| Harness | pilot.py, oracle.py, eval_worker.py, verify.py, fixture_caller.py, pilot_k2.py, run_live.py, sandbox.py (working tree; the runtime is pinned separately, so edits of oz*.py, k2_wrap.py or claude_cli_adapter.py by another session move neither the digest nor a run); the base interpreter version and CLI version are checked against freeze.json before every run |

## Schedule

Four runs, one at a time: A-I, A-D, B-D, B-I. No automatic retries. A finished run is never repeated.

## Arms

1. I: the caller reviews all three modules itself and must not run `oz do`.
2. D: the caller must not read or review any module. It runs one `oz do` call with one job per module, each job
   referencing its module and WITNESS_FORMAT.md by path, `max_attempts` 1, no checks. Three jobs in one packet is an
   experimental size, so the usage line's request template carries `"allow_experimental": true`.
3. Protocol violations are recorded and the run is not scored as its arm: I ran `oz do`; D made no worker call or
   more than one, dispatched a request with `max_attempts` other than 1 or with a profile or checks, did not pass each
   module by path in exactly one of three jobs, or let module content reach the caller.

## Isolation and the immutable snapshot (review findings 2 and 5)

Each run gets a run root `%TEMP%\cr-<random>` built at admission:

| Directory | Holds |
|---|---|
| `code/` | the pinned runtime, copied from its sources, each copy re-hashed after writing and made read-only; `SNAPSHOT.json` lists the hashes and is kept with the run |
| `ws/` | the pack's three modules, WITNESS_FORMAT.md, an oz workspace (packet budget 32,000), `adapter.json` |
| `bin/oz` | the shim: base interpreter, `-s`, `code/bench/live/k2_wrap.py`, PYTHONPATH and TIKTOKEN_CACHE_DIR inside `code/` |
| `arc/`, `state/` | invocation, packet and envelope archives; the guard's running total and STOP flag |

The run uses the base interpreter, never the repository's venv. The caller environment drops every variable whose
value names the repository and every PATH entry inside it, plus PYTHON*, OZ_*, CR_* and tiktoken variables. A
concurrent edit of `oz_cli.py` or any other repository file cannot reach a running run, because the run imports only
from `code/` (tested: every oz, tiktoken and regex module the runtime loads resolves inside the run root).

A test performs the derivation a caller could attempt from inside the workspace: cwd and its parents, every
environment variable, every file in the run root (adapter.json, the shim, the snapshot) and every existing file those
texts name, recursively. No repository path appears, and no file in the run root holds answer-key bytes, reference
lines, fixes or hidden witnesses.

Second layer, the tripwire: a run is marked `isolation_breach` when a tool input, with the run root's own paths
removed, still names an absolute drive path, the home directory (`~`, `$HOME`, `%USERPROFILE%`), Claude's session
stores (`.claude`), `akor`, the repository or evaluator files; or when a tool result holds evaluator-only text or
answer-key structure (`"start_line":`, `"hidden_witness":`, `"reference_fix":`, `"reference_file":`, plain or escaped).

Remaining limit: the caller is `claude` running as the user, so the home directory, which the CLI needs for its own
login, is still readable on disk; Claude's session transcripts and project list there name this repository. Only an OS
boundary (another account or a sandbox) closes that route. The tripwire covers it. The worker has no tools.

## Witness domains (review finding 3): provisional, questions for Astra

WITNESS_FORMAT.md requires witness inputs inside each module's documented domain, except when exercising an explicitly
documented rejection rule. `oracle.DOMAINS` implements a frozen validator per function, and a finding whose witness
leaves the domain is `out_of_domain`: never executed, counted as unproven and as a false positive. The strict reading
implemented now rejects Astra's example `rotate_left([], true)` and every boolean where an integer is documented. It
also enforces every stated precondition, and allows a violation only for the two rules that are written as
rejections: sample_stats out-of-range values (ValueError) and page_label absent pages (any allowed exception). These
points are not specified precisely enough to freeze without Astra:

1. Q1. Are the preconditions written as "must be positive" or "nonnegative", "invalid", "distinct" or "start <= end"
   domain limits a witness must satisfy, or documented rejection rules a witness may violate with an exception
   expectation? If the latter, which exception? This covers paging sizes, counts and page numbers;
   sample_stats.latest limit; ranges shape and order; rotation_order round; assign_tasks workers; chunk_tasks size;
   render_settings keys and values.
2. Q2. page_label "reject pages absent from the result set": which exception?
3. Q3. make_header "one allowed delimiter": the allowed set (`,` `;` tab `|`) is written only in code. Is it the
   documented domain?
4. Q4. ranges.contains: the type of `value` is not stated. Integer excluding booleans?
5. Q5. sample_stats "finite numbers": are integers allowed and booleans excluded?
6. Q6. Element domains not stated: paging items; rotation items and tasks ("JSON-compatible"); settings keys in
   overlay and select_prefix; parse_settings text (any string?).

The four hidden witnesses pass the provisional validators (verify.py checks this).

## Oracle (exact rules)

Strict JSON final answer: one object keyed by exactly the pack's three module paths, values findings arrays or null.
Anything else makes every file of the run incorrect. Per finding:

| Category | Rule | Counts as |
|---|---|---|
| invalid | record or witness breaks codereview-witness-v1 | unproven and false positive |
| out_of_domain | the witness leaves its function's documented domain (above) | unproven and false positive; not executed |
| seeded | witness matches on the reference, the shipped call completes without matching, class equals the seed's, line inside the seed's inclusive span | a seed hit |
| mislocated | the same proof, but no seed with that class and span | false positive; the file is incorrect |
| unseeded | runs cleanly, fails on shipped and reference, passes on a fix registered under `data/pilot/fixes/` after human or Astra review | neither correct nor false positive, reported apart |
| unproven | anything else, including timeouts and execution errors; a both-fail witness without a registered fix goes to review_both_fail | unproven and false positive |

A defective file is correct when its proven findings map exactly onto its seed set. A clean control is correct when
its response without unseeded findings is exactly `[]`. No model scores anything.

## Accounting (review finding 4)

1. Caller: the final envelope's `modelUsage` gives the total only when every entry holds all four counters
   (inputTokens, cacheReadInputTokens, cacheCreationInputTokens, outputTokens) as non-negative integers and the total
   is not below the per-message lower bound. A missing, null, boolean or negative counter is never read as zero; the
   run's accounting is then incomplete.
2. The per-message lower bound (the largest usage seen per message ID) is always reported.
3. Worker: the `oz do` ledgers, which must agree exactly with the raw worker envelopes kept by cr_adapter.py, each
   envelope held to the same counter rule. Missing or disagreeing makes the run's accounting incomplete.
4. Total = caller + worker + paid preparation (0). Caches count at full weight.

## Caps (review finding 1): exact rule

Let R be the run's billed tokens so far: per-message caller usage plus worker ledger usage. The guard evaluates R on
every caller stream event and every 0.25 s.

1. Caller calls. At each caller message k that asks for a tool, the next caller call is allowed only if
   R + B(k) <= 60,000 and k < 5, where B(k) = the input of k (uncached + cache read + cache write) + the output of k
   + 8,000 per tool use in k + 8,000. Otherwise the guard writes STOP and kills the caller's process tree at once,
   before the tool result exists, so no further caller call is requested. R >= 60,000 stops the run at any time.
2. Worker calls. cr_adapter.py launches a worker call only when STOP is absent and caller tokens + worker tokens
   already spent + (UTF-8 bytes of the packet's system and prompt, a sound input bound since every token covers at
   least one byte) + 8,000 <= 60,000. A refused call is not made; it is recorded with zero usage and a refusal
   envelope.
3. Overshoot. A run can pass 60,000 only through one call that is already in flight when the guard stops (the kill
   racing a tool that finishes first), or through allowances exceeded by actual usage. The race allowance is
   RACE = 40,000 (one call with a context up to 24,000 plus 16,000 of tool results and output), so the hard per-run
   bound is RUN_RESERVE = 100,000.
4. Admission reserves RUN_RESERVE: a run is admitted only if spent + 100,000 <= 250,000, where spent charges each
   recorded run its total (or, with incomplete accounting, max(100,000, its lower bound)) and each admitted attempt
   without a record 100,000. The 250,000 total cannot be crossed as long as no single run passes 100,000. Practical
   effect: run 4 is admitted only if runs 1 to 3 were charged 150,000 or less together.
5. The quota projection uses the same reserve: before + factor x 100,000 + 1 point of rounding must stay below 58%
   (factor 2 points per 55,000 tokens, rising with observed movement, never falling), so the first run needs a
   reading below 53.36%. Unsettled or missing readings refuse. 60% is the ceiling.

## Truncation

Reported as incomplete: `error_max_turns`, the guard's `turns` or `cap` stop, the 1,800 s wall timeout, or no
result envelope. A truncated or refused run is recorded with its cost (refusals with 0, nothing launched).

## Findings size against the inline limit

Expected per-file `oz do` values: 168, 149, 2, 164, 152 and 2 bytes. The largest finding is 166 bytes, so 24 fit
under the 4,096-byte inline limit. No artifact read turn is expected.

## Dry gate (zero tokens, fixture caller and fixture worker, the same run-root code path)

`pilot.py dry` passes all eleven scenarios with 0 rejudge mismatches:

| Scenario | Exercises | Result |
|---|---|---|
| I-clean | arm I end to end | valid, 3/3 |
| D-mixed | arm D end to end; mislocated, unproven, clean-control false positive | valid, 1/3, FP 3, unproven 2 |
| D-violation | D caller reads a module | protocol_violation |
| I-truncated | `error_max_turns` | truncated, cost recorded |
| I-malformed | fenced findings JSON | answer invalid, 0/3 |
| D-unseeded | a real unseeded defect with a registered fix | unseeded, 3/3, FP 0 |
| I-oz-violation | arm I runs `oz do` | protocol_violation |
| I-cap | a call whose allowance would cross 60,000 | stopped after the first call, charged 100,000 |
| D-worker-cap | a worker call reports 70,900 tokens | stopped by the timer before any further caller call, charged 100,000 |
| I-missing-counter | the caller envelope lacks cacheReadInputTokens | inconclusive accounting, lower bound 15,600, charged 100,000 |
| I-out-of-domain | `rotate_left([], true)` reported for seed B2 | out_of_domain, no seed credit, 2/3 |

## Run procedure (blocked until the domain specification is frozen)

From the repository root in Git Bash, with `<repo>` the repository path. Read the weekly figure just before each run
and put it in place of `PCT`; after each run, read it again and settle it.

1. Check: `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/verify.py`
   and `.venv/Scripts/python.exe bench/codereview/pilot.py freeze` must print ALL PASS and freeze holds.
2. Run 1 (A-I):
   `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/pilot.py run --expect a62bd3910ff90408861a555bc0e378f16b7ba0d36c57322a5e873a1c9f1d46f5 --quota-before PCT`
   then `.venv/Scripts/python.exe bench/codereview/pilot.py quota-after --percent PCT`
3. Run 2 (A-D):
   `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/pilot.py run --expect a62bd3910ff90408861a555bc0e378f16b7ba0d36c57322a5e873a1c9f1d46f5 --quota-before PCT`
   then `.venv/Scripts/python.exe bench/codereview/pilot.py quota-after --percent PCT`
4. Run 3 (B-D):
   `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/pilot.py run --expect a62bd3910ff90408861a555bc0e378f16b7ba0d36c57322a5e873a1c9f1d46f5 --quota-before PCT`
   then `.venv/Scripts/python.exe bench/codereview/pilot.py quota-after --percent PCT`
5. Run 4 (B-I):
   `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/pilot.py run --expect a62bd3910ff90408861a555bc0e378f16b7ba0d36c57322a5e873a1c9f1d46f5 --quota-before PCT`
   then `.venv/Scripts/python.exe bench/codereview/pilot.py quota-after --percent PCT`
6. `pilot.py report` prints the per-run table (caller turns, caller tokens, cache reads and writes, worker tokens,
   total, lower bound, charged, time, correctness, recall, false positives, unproven) and the fill-slope estimates for
   60k and 120k fills. `pilot.py rejudge` rebuilds every record from its raw data and must report 0 mismatches.

Each `run` command runs the next unrecorded run of the schedule. After a crash, the same command first rebuilds a run
whose raw data was kept (never re-running it) or records an attempt without raw data as aborted, charged 100,000;
that run is repeated only after its after-reading is settled. Stop at once if a reading reaches 58%, if admission
refuses, or if a run shows an isolation breach or an unseeded review item.

## Notes and deviations

1. "Valid unseeded" needs a passing fix (01, item 6). Without a registered fix a both-fail witness stays unproven and
   goes to review; otherwise a clean control could hide a false positive behind any wrong expectation.
2. Literal 02 rule for defective files: unproven extra findings do not make a defective file incorrect; they count as
   false positives and unproven.
3. The 8,000-token allowances and RACE are frozen assumptions about one Bash result and one call's output; they are
   not enforced by the CLI. A run that passes 100,000 anyway is visible in its record and would be a stop condition.
4. `--max-turns` is not listed in `claude --help` for 2.1.306, but the option parser accepts it. The guard enforces
   five model calls independently, before the sixth starts.
