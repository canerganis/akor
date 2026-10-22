# Caller-cost experiment: preregistration as implemented

Implements the signed plan ([03](03-astra-r2-signed-plan.md), [04](04-opus-r2-sign.md)). Harness:
`bench/live/pilot_k2.py`, bench `oz` wrapper `bench/live/k2_wrap.py`, recording worker adapter
`bench/live/k2_adapter.py`, offline G0 tests `tests/test_pilot_k2.py`. Commit this file before the first counted call.

**Frozen digest:** `6b5e75cbd86d66118c40ce9f9461ba7d37bd95bc714f7c7e90ac11ebf50f657a`

The digest covers every counted run's system text, prompt, tool set, workspace files (sha256), expected values and
input digest, the K0 and K1 texts, the caller argv, timeout, model, oracle version, block C budget, and the
line-ending-normalized source of `pilot_k2.py`, `k2_wrap.py`, `k2_adapter.py` and the bench modules they import.
`python bench/live/pilot_k2.py plan` prints it. If anything changes after the smokes, rerun `plan`, put the new digest
here and commit before the first counted call. The CLI version, git HEAD and sha256 of the core files (`oz*.py`,
`examples/claude_cli_adapter.py`) are recorded at the first counted run; `run` stops before any later run if the CLI
version or a core file differs.

## Fixed conditions

| Item | Value |
|---|---|
| Caller and worker model | `claude-sonnet-5-5` (worker via `examples/claude_cli_adapter.py`, `OZ_MODEL`) |
| Caller command | `claude -p --model claude-sonnet-5-5 --system-prompt <pilot SYSTEM> --tools Bash --allowedTools Bash --setting-sources '' --strict-mcp-config --no-session-persistence --output-format stream-json --verbose`, prompt on stdin |
| Tools | Bash only, every arm, J included |
| Effort | default (no `--effort` flag), every arm |
| Concurrency | 1, schedule order below |
| Workspace | fresh temp directory per run; caller cwd is the workspace |
| Caller wall limit | 1,800 s, every arm |
| Worker limits | `oz do` defaults (deadline 600 s, call timeout 300 s, 2 attempts); workspace `max_tokens` 2,048 in A and B as in arm K, 100,000 in C (set by the harness in `oz.json`, not in the caller text) |
| Retries of a run | none; failed and timed-out runs count with their tokens |
| Extension | none; three seeds per cell, disagreement leaves a gate unmet |

## Arms

| Arm | Caller text | `oz` on PATH |
|---|---|---|
| J | the task only | none |
| K0 | `pilot_k.K_TEXT` unchanged (request file, `oz do request.json --adapter adapter.json`) | wrapper in legacy mode: real `oz_cli` output, invocation archived |
| K1f | K1 text, full mode | wrapper: one `oz do` call, request on stdin, full result printed and published to `results.json` |
| K1r | K1 text, receipt mode | wrapper with `--receipt`: full result only in `results.json`, receipt of at most 2,048 bytes printed |

K1 text (K1f; K1r differs only in ` --receipt` after `adapter.json` and in the mode sentence):

```text
You have the `oz` command. It runs many small independent jobs in one batched model call. Do not answer any job yourself. Run `oz do --adapter adapter.json` exactly once, in a single Bash call in the current directory, with the request JSON on stdin through a quoted heredoc (<<'EOF' ... EOF). Do not write the request to a file and do not print it. Request format (JSON): {"model":"claude-sonnet-5-5","goal":"<the goal>","ops":{"<name>":"<instruction for the job, written for one reference>"},"refs":{"<name>":"<reference text>"},"jobs":[["<message ID>","<op name>","<ref name>"],...]}. When a reference is held in a file, give {"path":"<file path>"} as its value instead of its text. One job per message ID; an op is an instruction shared by jobs that ask the same thing of different references. jobs[<ID>].status is accepted, failed or unresolved, and jobs[<ID>].value is the result. The command prints the full result JSON and also saves it, unchanged, to results.json in the current directory.
```

K1r mode sentence: `The command saves the full result JSON to results.json in the current directory and prints only a short receipt:
status, counts, the IDs not accepted, and the file path and SHA-256. Read results.json only for what the task needs.`
Reply contract only, appended to K1: `Report accepted values with status 0, failed jobs with status 2 and unresolved jobs
with status 1, in the reply format stated at the end.`

## Workload and contracts

The pilot materials workload (`live11.make_records(seed)`, 0.8 brief packet, IDs `ma_01`...). 16 jobs use
references 1 to 4, 64 jobs use references 1 to 16.

| Block | Input | Prompt change against the pilot packet |
|---|---|---|
| A | caller holds the work | none (J prompt equals pilot2 arm J byte for byte) |
| B | `refs/N.txt` holds the pilot reference text (no trailing newline) | the `Refs` header and JSON lines become `References: the text of reference N is the content of the UTF-8 file refs/N.txt in the current directory.` |
| C | `refs/N.txt` of exactly 4,096 ASCII bytes | as B |

Block C files: seeded filler lines (`random.Random("k2-filler/<seed>/<k>")`, a fixed 30-word vocabulary with no
digits, `=`, `;`, field names or field values), the record line once on its own line after a seeded number of filler
lines, then filler cut to the exact size and ended with a period. 16 references at 64 jobs. J and K see the same
files and the same task text. Block C is outside the qualified workload class (`workload_class` in each record).

Reply contract: the pilot's last line, judged by the pilot's strict oracle (`json.loads`, `results08`, per-job check:
the exact word or JSON text equal to the expected value).

Artifact contract: the pilot's last line becomes `Deliver the results in the file results.json in the current
directory.` followed by the round 04 continuation text verbatim.

## Seeds

| Cell | Seeds |
|---|---|
| A, 16 jobs | 3005, 3006, 3007 (archived, pairs with pilot J and arm K) |
| A, 64 jobs | 3105, 3106, 3107 (archived) |
| B, 16 jobs (reply and artifact) | 7001, 7002, 7003 (fresh, unused in any stored record) |
| B, 64 jobs (reply and artifact) | 7101, 7102, 7103 (fresh) |
| C, 64 jobs | 7201, 7202, 7203 (fresh) |
| Calibration smokes | 2999 |

## Counted runs: 48

K0 rerun included: commit 430f660 changed the `oz do` value path after the archived K runs, and the core files are
changing again, so the archived K0 is not a comparable baseline under round 03.

| Block, contract | Arms and sizes | Runs |
|---|---|---:|
| A, reply | K0 at 64 | 3 |
| A, reply | J at 16 and 64, K1f at 64 | 9 |
| B, reply | J and K1f at 16 and 64 | 12 |
| B, artifact | J, K1f, K1r at 16 and 64 | 18 |
| C, artifact | J and K1r at 64 | 6 |

Run order (all arms of one seed back to back; arm order per seed from `random.Random("k2/<block>/<contract>/<n>/<seed>")`):

| # | Block, contract, n | Seed | Arm order |
|---|---|---|---|
| 0 to 2 | A reply 16 | 3005, 3006, 3007 | J |
| 3 to 5 | A reply 64 | 3105 | K1f, K0, J |
| 6 to 8 | A reply 64 | 3106 | J, K0, K1f |
| 9 to 11 | A reply 64 | 3107 | K1f, J, K0 |
| 12 to 17 | B reply 16 | 7001, 7002, 7003 | K1f J; K1f J; J K1f |
| 18 to 23 | B reply 64 | 7101, 7102, 7103 | K1f J; J K1f; K1f J |
| 24 to 32 | B art 16 | 7001, 7002, 7003 | K1r J K1f; J K1f K1r; J K1f K1r |
| 33 to 41 | B art 64 | 7101, 7102, 7103 | K1r J K1f; K1r J K1f; J K1f K1r |
| 42 to 47 | C art 64 | 7201, 7202, 7203 | J K1r; J K1r; K1r J |

## Commands

Every command runs from the repo root with `TIKTOKEN_CACHE_DIR=.token-cache PYTHONIOENCODING=utf-8` and without a
`MODEL` variable in the environment.

```text
# offline G0 (no model calls)
TIKTOKEN_CACHE_DIR=.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m unittest discover -s tests
.venv/Scripts/python.exe bench/live/pilot_k2.py plan

# excluded calibration smokes, seed 2999, one per arm type (records in bench/live/data/pilot_k2_smoke.jsonl)
.venv/Scripts/python.exe bench/live/pilot_k2.py smoke J C art 64
.venv/Scripts/python.exe bench/live/pilot_k2.py smoke K1f B art 64
.venv/Scripts/python.exe bench/live/pilot_k2.py smoke K1r C art 64
.venv/Scripts/python.exe bench/live/pilot_k2.py smoke K0 A reply 64

# counted runs (resumable; a run without a record is repeated, its partial files kept aside)
TIKTOKEN_CACHE_DIR=.token-cache PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe bench/live/pilot_k2.py run --expect 6b5e75cbd86d66118c40ce9f9461ba7d37bd95bc714f7c7e90ac11ebf50f657a

# analysis
.venv/Scripts/python.exe bench/live/pilot_k2.py rejudge
.venv/Scripts/python.exe bench/live/pilot_k2.py report
```

Data: `bench/live/data/pilot_k2.jsonl` (one record per run), `pilot_k2.manifest.json`, and per run
`bench/live/data/pilot_k2/<tag>/`: prompt, spec with expected values, raw stream-json transcript, stderr, every `oz`
invocation (`archive/oz/NNNN/`: argv, raw request bytes, stdout, stderr, exit code, published digest), every worker
packet and raw reply (`archive/worker/packets.jsonl`), the `oz do` run directories (request, ledger, dispatch log,
without the SQLite inbox) and `results.json`.

## Scoring

Every judgment reads only the run's own spec, built from its seed (regression test for the pilot_k cross-seed bug).
Each record carries its seed, input sha256 and oracle version `k2-oracle/1`.

1. Tokens: caller `modelUsage` (input, cache read and cache creation at full weight, output) plus worker tokens from
   the `oz do` call ledgers. Cache reads are also reported separately. Missing caller usage or a worker call without
   usage makes the run's cost inconclusive.
2. Tokens per verified job: run total over verified jobs; a run with 0 verified jobs keeps its tokens and counts as
   infinitely expensive in comparisons.
3. Artifact file: strict JSON (no duplicate keys, NaN, BOM or trailing text), a top-level `jobs` object whose keys are
   exactly the message IDs, each entry an object with status `accepted`, `failed` or `unresolved`. Other top-level
   keys and extra entry keys are allowed (an `oz.do.result/1` file qualifies). Otherwise the file is malformed.
4. Per-job value: passes when the entry is accepted and its value equals the expected value as native JSON, or is a
   string the pilot's rule accepts. Same rule for every arm.
5. Continuation reply: strict JSON with exactly the keys `outside`, `unknown`, `not_accepted`, each a list of strings,
   equal in order to the lists from the expected values. Every job has an expected value, so the expected
   `not_accepted` is always empty.
6. Verified jobs (artifact contract): passing file jobs, only when the file is well formed and the reply matches;
   otherwise 0.

## Gates as implemented (`pilot_k2.gates`)

1. **G1:** A, reply, 64: K1f verified 192 of 192; on each seed K1f Bash calls at most K0's and K1f tokens per
   verified job below K0's. K0 is the rerun, or the archived arm K only if no K0 rows exist.
2. **G2:** B, artifact, 16 and 64, K1r against K1f per seed: verified, file jobs passed and reply correctness no worse;
   tokens per verified job lower on every pair at both sizes; median of (1 minus K1r over K1f) at 64 at least 10%.
3. **G3:** per K1f and K1r run at 64 in blocks B and C, request tokens are measured on carrier tool calls (input holds
   `"jobs"` and `"ops"` keys). Upper bound: API output tokens of each carrier's whole message times (1 plus later
   assistant messages), since every later turn rereads it. Estimate: o200k tokens of the carrier text times the run's
   ratio of reported caller output tokens to o200k tokens of everything the caller emitted, same multiplier. Shares
   are over the run's total tokens. The median upper-bound share at least 25% triggers preregistration of a
   deterministic-producer arm; otherwise the importer is deferred. The estimate is reported beside it.
4. **M14:** per cell (J against K1f or K1r), a winner only when all three seed pairs favour it on tokens per verified
   job with no fewer verified jobs and no timeout the other arm did not have; missing usage makes the cell
   inconclusive; otherwise undecided.

Every gate is an engineering threshold on three paired seeds, not a statistical claim.

## Freeze record (2026-10-23)

Smokes (excluded, `bench/live/data/pilot_k2_smoke.jsonl`): J-C-art, K1f-B-art, K1r-C-art, K0-A-reply at 64 jobs on seed
2999, all 64/64; stream-json carried per-message usage. After the smokes the core changed (commits 1e04854 step 3 and
2f4f2f6 review fixes, both opt-in selective path only; the default path `oz do` uses here is unchanged), the digest
above was recomputed unchanged, and the 48 counted runs start at git HEAD 2f4f2f6 with Claude CLI 2.1.306.
