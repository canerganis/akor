# Code-review sizing pilot: frozen run plan

Status: frozen at digest `c635880f27dce6e52081defe0b17b24183337f0bc6e5c3d18bce7b49a2a615e1` (`bench/codereview/freeze.json`,
CLI 2.1.306), not run, runnable. The witness domains are frozen: Astra answered the six questions as a new
evaluator file, `DOMAINS.md` (Astra revision 2), which changes no module, span or reference.

Sizing pilot only, as signed in [02](02-astra-pilot-prereg.md) with the five binding changes of
[03](03-opus-changes.md), accepted in [04](04-astra-accept.md). No ranking, no winner, no adoption decision. Nothing
was paid to prepare it. It answers Astra's review of the first harness (five findings, all fixed with failing tests first)
and takes the domain specification from DOMAINS.md. Astra's second review left three findings open (caps, the
accounting lower bound, the init import path); each is fixed below with failing tests first, and the structural limit
on output is stated as such.

## What the digest pins

| Item | Value |
|---|---|
| Fixtures | `bench/codereview/fixtures/codereview-v1`, Astra revision 1 (seed A2 span 25-26, seed span rule in WITNESS_FORMAT.md) and revision 2 (DOMAINS.md). Every file hashed; SHA256SUMS sha256 `883a91c0133e0fd650c621be551965b21e767057f2434d451e3627c2755d779d`. Authorship record: [fixtures-as-authored-by-astra.txt](fixtures-as-authored-by-astra.txt), original plus the two appended revisions |
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

The workspace init (`oz_cli init`) runs as `python -s -P -c ...` with its cwd set to the run root (second review,
finding 3). Before, it ran with the harness's cwd, the repository root, and `python -c` puts its cwd on `sys.path`
ahead of PYTHONPATH, so the init imported working-tree modules. The test now intercepts the init call setup() makes,
from the repository as cwd, and probes with exactly its interpreter flags, cwd and environment: every oz module
resolves inside the run root and nothing resolves inside the repository. Every other subprocess of a run already
starts from a script inside `code/` with its cwd in `ws/`.

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

## Witness domains (review finding 3): DOMAINS.md, frozen

WITNESS_FORMAT.md admits only witness inputs inside each module's documented domain, except when they exercise a
documented rejection. Astra's `DOMAINS.md` states that domain as one executable Python block (`SPECS` per function,
`classify`). The oracle runs that block itself, so every rule is a line of DOMAINS.md, not a transcription. Before
loading, it checks that the block imports only inspect, math and re and holds only imports, definitions and
assignments. A witness is admitted when `classify` gives:

1. `normal` with `witness_allowed`: any codereview-witness-v1 expectation;
2. `rejection` with `witness_allowed`: only `{"exception": "ValueError"}`.

Anything else is `out_of_domain`: never executed, counted as unproven and as a false positive. This covers outside
calls (types, booleans or floats for integers, binding, unknown functions), calls that are not JSON-eligible, and a
rejection with another expectation.

verify.py checks the specification against the fixture, and all four checks pass:

1. SPECS names exactly the public functions of every module, with each parameter order and default as written in
   both the shipped and the reference module.
2. All four hidden witnesses are `normal` and still prove.
3. A sweep runs 1,381 generated admitted calls against the reference implementations: 592 normal, 789 rejections.
   Every rejection raises exactly ValueError, every normal call returns, and there are 0 contradictions.
4. The only mismatches are 9 calls with a sample of 10**400, which raise OverflowError. DOMAINS.md acknowledges this
   case itself under "Compatibility limitation" and keeps the ValueError rule. Such a witness is admitted but can
   never be proven, because the reference does not match it, so it cannot earn credit.

## Oracle (exact rules)

Strict JSON final answer: one object keyed by exactly the pack's three module paths, values findings arrays or null.
Anything else makes every file of the run incorrect. Per finding:

| Category | Rule | Counts as |
|---|---|---|
| invalid | record or witness breaks codereview-witness-v1 | unproven and false positive |
| out_of_domain | DOMAINS.md does not admit the witness (above) | unproven and false positive; not executed |
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
   envelope held to the same counter rule. Missing or disagreeing makes the run's accounting incomplete. A run the
   guard stopped for unknown usage is incomplete whatever its files hold.
4. Total = caller + worker + paid preparation (0). Caches count at full weight.
5. Lower bound (second review, finding 2): the caller and the worker are disjoint spends, and each is taken at the
   largest of its independent sources. Lower bound = max(caller per-message usage, caller final modelUsage) +
   max(worker ledgers, raw worker envelopes), where an incomplete modelUsage contributes every counter it holds as a
   non-negative integer. Each record lists the four sources (`lower_bound_sources`). A run with incomplete accounting
   is charged max(101,000, lower bound); a preserved 120,000-token worker envelope with no ledger completion is
   therefore charged at least 120,000 plus the caller's bound (tested).
6. Malformed shapes never raise (re-review of the second review). Every usage shape other than the strict one, on
   either side, is recorded as incomplete accounting with its lower bound and charged max(101,000, lower bound): usage
   or modelUsage that is not an object, a non-object modelUsage entry, a counter that is null, boolean, negative, a
   string, a float or another non-integer, a missing counter, and unreadable or non-object transcript or ledger lines.
   A caller message without strict usage makes the caller's accounting incomplete even when the final total is
   whole. A worker call counts as having usage only when its ledger `usage.raw` holds input_tokens,
   cached_input_tokens, cache_creation_input_tokens and output_tokens as non-negative integers. The ledgers are read
   by the pilot's own strict reader (`read_ledgers`, shared with the live guard), not by pilot_k2.worker_usage, and
   pilot_k2.parse_stream, which is pinned by another freeze and left unedited, only ever sees a transcript reduced to
   valid shapes; it supplies turns, tool calls and the final text, never accounting. The same record function serves
   the first record, `rejudge` and crash recovery, and a property-style test runs 178 malformed shapes through the
   first record and through recovery.
7. The transcript must be read whole (third review). Any line of the recorded transcript that is blank, not JSON or
   not an object, a transcript that is not UTF-8, an unterminated final line, or an event shape accounting cannot
   trust makes the caller's accounting incomplete, charged max(101,000, lower bound), on the first record and on
   recovery. The rejected shapes are: a message that is not an object, a caller message without a non-empty string
   id, content that is not a list of objects (a user message may also carry a string), and a block `id`,
   `tool_use_id`, `text` or `thinking` that is present but not a string. Before such a transcript reaches
   pilot_k2.parse_stream, those non-string ids and fields are removed, so an id like `["m1"]` can no longer raise an
   unhashable-key error. Each record lists the problems (`caller.transcript_problems`). The live guard applies the
   same rule to every newline-terminated stream line and stops with reason `usage`. Only an unterminated final line
   at the end of the stream is left alone, because it may still be in flight. All 52 recorded transcripts under
   `bench/live/data` pass this check, and each corrupt case has its own test, which corrupts only the transcript of an
   otherwise complete 5,900-token run, on the first record and on recovery.

## Caps (review finding 1, second review finding 1): exact rule

Structural limit, stated plainly: `claude -p` on CLI 2.1.306 has no option that limits a call's output tokens (its
help lists none; `--max-budget-usd` is a dollar budget, not an output bound, and is not used). The harness therefore
cannot bound the output of any single call, caller or worker. Every output figure below is a margin over measured
evidence, not an enforced limit. What the harness does enforce: it launches no further call once the known spend or
its allowance reaches the cap, it stops the run at the first stream message whose usage takes it to the cap, and it
stops on any unknown spend.

Measured evidence: the largest single-call output of claude-sonnet-5-5 recorded in this repository is 4,235 output
tokens (`bench/live/data/live17_het_sonnet.jsonl`, a tool-free `claude -p` call, 2,510 of them thinking). Sources
scanned: the 614 single-call rows in `bench/live/data/*.jsonl` (rows with subagent spawns, which sum many calls, are
excluded); the pilot_k2 caller turns (largest 1,383), single-turn envelopes (2,768) and `oz do` ledgers (2,813); the
`bench/o1/live1` ledgers (2,265). A test re-derives the 4,235 from the data and checks the allowances against it.

Let R be the run's billed tokens so far: per-message caller usage plus worker usage, the latter the larger of the
ledgers and the raw envelopes. The guard evaluates R on every caller stream event and every 0.25 s.

1. Unknown spend stops. A caller message whose usage lacks any of the four counters, or holds a null, boolean,
   negative or non-integer one; a finished ledger line that cannot be read or a call_end without integer input and
   output counts; or a written envelope that is unreadable or lacks a strict counter: the guard writes STOP and kills
   the caller's process tree at once (stop reason `usage`). Nothing is read as zero. The run is charged
   max(101,000, lower bound).
2. Caller calls. R >= 60,000 stops the run at once, so it stops at the first message whose usage takes it to the
   cap. At each caller message k that asks for a tool, the next caller call is allowed only if R + B(k) <= 60,000
   and k < 5, where B(k) = the input of k (uncached + cache read + cache write) + the output of k + 8,000 per tool
   use in k + 9,000 (OUT_ALLOW). Otherwise the guard writes STOP and kills the caller's process tree at once, before
   the tool result exists, so no further caller call is requested.
3. Worker calls. cr_adapter.py launches a worker call only when STOP is absent and caller tokens + worker tokens
   already spent + (UTF-8 bytes of the packet's system and prompt, a sound input bound since every token covers at
   least one byte) + 9,000 (WORKER_OUT_ALLOW) <= 60,000. It refuses and writes STOP when the guard state is
   unreadable or malformed, when any earlier envelope is empty, unreadable or not strict, or when the request's size
   cannot be bounded; and it writes STOP after a call that returns without an envelope holding strict counters. The
   guard treats that STOP as a `usage` stop. A refused call is not made; it is recorded with zero usage and a refusal
   envelope.
4. Allowances. OUT_ALLOW = WORKER_OUT_ALLOW = 9,000, twice the measured 4,235 rounded up to a thousand. TOOL_ALLOW =
   8,000 per tool result and RACE_CONTEXT = 24,000 remain assumptions, not measurements and not enforced.
5. Overshoot. A run can pass 60,000 through one call already in flight when the guard stops (the kill racing a tool
   that finishes first), or through a call whose actual output or tool result exceeds its allowance. The race
   reserve is RACE = 24,000 + 8,000 + 9,000 = 41,000, so the per-run reserve is RUN_RESERVE = 101,000. This is a
   reserve, not a hard bound: since output cannot be limited, a run can exceed it, and that is visible in its record
   (charged at its lower bound when larger) and is a stop condition.
6. Admission reserves RUN_RESERVE: a run is admitted only if spent + 101,000 <= 250,000, where spent charges each
   recorded run its total (or, with incomplete accounting, max(101,000, its lower bound)) and each admitted attempt
   without a record 101,000. Practical effect: run 4 is admitted only if runs 1 to 3 were charged 149,000 or less
   together.
7. The quota projection uses the same reserve: before + factor x 101,000 + 1 point of rounding must stay below 58%
   (factor 2 points per 55,000 tokens, rising with observed movement, never falling), so the first run needs a
   reading of 53.32% or less (edge 53.327). Unsettled or missing readings refuse. 60% is the ceiling.

## Truncation

Reported as incomplete: `error_max_turns`, the guard's `turns`, `cap` or `usage` stop, the 1,800 s wall timeout, or no
result envelope. A truncated or refused run is recorded with its cost (refusals with 0, nothing launched).

## Findings size against the inline limit

Expected per-file `oz do` values: 168, 149, 2, 164, 152 and 2 bytes. The largest finding is 166 bytes, so 24 fit
under the 4,096-byte inline limit. No artifact read turn is expected.

## Dry gate (zero tokens, fixture caller and fixture worker, the same run-root code path)

`pilot.py dry` passes all fourteen scenarios with 0 rejudge mismatches (inside the gate and as a separate
`pilot.py rejudge` of the dry directory):

| Scenario | Exercises | Result |
|---|---|---|
| I-clean | arm I end to end | valid, 3/3 |
| D-mixed | arm D end to end; mislocated, unproven, clean-control false positive | valid, 1/3, FP 3, unproven 2 |
| D-violation | D caller reads a module | protocol_violation |
| I-truncated | `error_max_turns` | truncated, cost recorded |
| I-malformed | fenced findings JSON | answer invalid, 0/3 |
| D-unseeded | a real unseeded defect with a registered fix | unseeded, 3/3, FP 0 |
| I-oz-violation | arm I runs `oz do` | protocol_violation |
| I-cap | a call whose allowance would cross 60,000 | stopped after the first call, charged 101,000 |
| D-worker-cap | a worker call reports 70,900 tokens | stopped by the timer before any further caller call, charged 101,000 |
| I-missing-usage | a caller stream message lacks cache_creation_input_tokens | `usage` stop at that message, charged 101,000 |
| D-worker-no-usage | the worker envelope lacks outputTokens | cr_adapter.py sets STOP, `usage` stop, charged 101,000 |
| I-missing-counter | the caller envelope lacks cacheReadInputTokens | inconclusive accounting, lower bound 15,600, charged 101,000 |
| I-out-of-domain | `rotate_left([], true)` reported for seed B2 | out_of_domain, no seed credit, 2/3 |
| I-rejection-witness | `page_count(3, 0)` with ValueError, and with a return expectation | the first admitted and executed (unproven), the second out_of_domain; 3/3, FP 2 |

## Run procedure

From the repository root in Git Bash, with `<repo>` the repository path. Read the weekly figure just before each run
and put it in place of `PCT`; after each run, read it again and settle it.

1. Check: `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/verify.py`
   and `.venv/Scripts/python.exe bench/codereview/pilot.py freeze` must print ALL PASS and freeze holds.
2. Run 1 (A-I):
   `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/pilot.py run --expect c635880f27dce6e52081defe0b17b24183337f0bc6e5c3d18bce7b49a2a615e1 --quota-before PCT`
   then `.venv/Scripts/python.exe bench/codereview/pilot.py quota-after --percent PCT`
3. Run 2 (A-D):
   `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/pilot.py run --expect c635880f27dce6e52081defe0b17b24183337f0bc6e5c3d18bce7b49a2a615e1 --quota-before PCT`
   then `.venv/Scripts/python.exe bench/codereview/pilot.py quota-after --percent PCT`
4. Run 3 (B-D):
   `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/pilot.py run --expect c635880f27dce6e52081defe0b17b24183337f0bc6e5c3d18bce7b49a2a615e1 --quota-before PCT`
   then `.venv/Scripts/python.exe bench/codereview/pilot.py quota-after --percent PCT`
5. Run 4 (B-I):
   `TIKTOKEN_CACHE_DIR=<repo>/.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/codereview/pilot.py run --expect c635880f27dce6e52081defe0b17b24183337f0bc6e5c3d18bce7b49a2a615e1 --quota-before PCT`
   then `.venv/Scripts/python.exe bench/codereview/pilot.py quota-after --percent PCT`
6. `pilot.py report` prints the per-run table (caller turns, caller tokens, cache reads and writes, worker tokens,
   total, lower bound, charged, time, correctness, recall, false positives, unproven) and the fill-slope estimates for
   60k and 120k fills. `pilot.py rejudge` rebuilds every record from its raw data and must report 0 mismatches.

Each `run` command runs the next unrecorded run of the schedule. After a crash, the same command first rebuilds a run
whose raw data was kept (never re-running it) or records an attempt without raw data as aborted, charged 101,000;
that run is repeated only after its after-reading is settled. Stop at once if a reading reaches 58%, if admission
refuses, or if a run shows an isolation breach or an unseeded review item.

## Notes and deviations

1. "Valid unseeded" needs a passing fix (01, item 6). Without a registered fix a both-fail witness stays unproven and
   goes to review; otherwise a clean control could hide a false positive behind any wrong expectation.
2. Literal 02 rule for defective files: unproven extra findings do not make a defective file incorrect; they count as
   false positives and unproven.
3. No call's output can be bounded by this harness (structural limit above). OUT_ALLOW and WORKER_OUT_ALLOW are
   margins over the measured 4,235; TOOL_ALLOW and RACE_CONTEXT are frozen assumptions about one Bash result and one
   racing call's context. None is enforced by the CLI. A run that passes 101,000 anyway is visible in its record, is
   charged at its lower bound, and is a stop condition.
4. `--max-turns` is not listed in `claude --help` for 2.1.306, but the option parser accepts it. The guard enforces
   five model calls independently, before the sixth starts.
