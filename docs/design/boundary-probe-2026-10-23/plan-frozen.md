# Boundary probe: frozen plan as implemented

Design: [01](01-astra-r1.md) as amended by [02](02-opus-r1.md) and the signed [03](03-astra-r2-signed.md). This file
records what `bench/probe/boundary.py` does, so the run can be judged against it. Nothing here is a model result.

## Identity

| Item | Value |
|---|---|
| Freeze digest | `520c98e895a6bc0dfb5781cc23d66bd2a1633d11bbdc98141387755428714ac2` (short: 520c98e8) |
| Harness | `bench/probe/boundary.py` (standard library only), tests in `tests/test_boundary_probe.py` |
| Evidence namespace | `bench/probe/boundary-evidence/` (independent of live1 and live2) |
| Route | `claude -p`, `claude-sonnet-5-5`, default effort, CLI 2.1.306, no tools, settings isolated, text H, strict OZ/1g header parser |

The digest is the sha256 of the canonical JSON printed by `freeze`: route and argv, H hash, per-arm op text and prompt
hash, record hashes, C intervals, expected labels, schedule, caps, decision rules, and the line-ending-normalized
sha256 of `boundary.py`, `examples/claude_cli_adapter.py`, `workflow.json`, and design files 01, 02 and 03. Any edit to
the harness changes the digest; `run --expect` refuses a different one.

Frozen file digests at this freeze:

| File | sha256 |
|---|---|
| bench/probe/boundary.py | `078f49a8e09a21f8cc9d675595aa245b95c4976b094b41aa70f3863851166652` |
| examples/claude_cli_adapter.py | `deba48b9d68cb3717f642ece195a9aeec656225c926224386eb3ee887b3dd7fa` |
| bench/step4/inspection-handoff-20-v1/workflow.json | `69f220a8ce22c73e53957103669250dce11f499f52a17ef87a4941096f0057ab` |
| 01-astra-r1.md | `c2922d02ab12adc25daabfccb3db51d6326fe23a3ff5cc70f8b1d4f33c8b42d1` |
| 02-opus-r1.md | `cc1fb9be0fb0d706e958cb3d219d3ea5f39642fb6183618cdb62a38c055cee94` |
| 03-astra-r2-signed.md | `463f8ce0d7e3873c58478f43a0bd8e7c4785fb0af538fbbe816ba26fa027026c` |

## Commands (PowerShell, repo root)

```powershell
$env:TIKTOKEN_CACHE_DIR = ".token-cache"; $env:PYTHONIOENCODING = "utf-8"
# Full suite (must stay green)
.venv/Scripts/python.exe -m unittest discover -s tests
# Prints the digest above and re-proves the reconstruction (zero tokens)
.venv/Scripts/python.exe bench/probe/boundary.py freeze
# Zero-token dry run on fixture replies; must end with DRY OK
.venv/Scripts/python.exe bench/probe/boundary.py dry
# The 18 counted calls, paid, resumable (rerun the same command to resume)
.venv/Scripts/python.exe bench/probe/boundary.py run --expect 520c98e895a6bc0dfb5781cc23d66bd2a1633d11bbdc98141387755428714ac2
# Tables and the decision from the retained evidence (zero tokens; also written by run)
.venv/Scripts/python.exe bench/probe/boundary.py report
```

`run` takes `--out DIR` (default `bench/probe/boundary-evidence`) and `--acknowledge-halt` (below). `dry` writes to
`.oz-runtime/boundary-dry` and never starts a process.

## Material

Every arm sends text H (sha256 `d941a86d…`, imported from `oz_batch.SYSTEM` and checked against the hash) as
`--system-prompt` and one packet on stdin. The packet is compact JSON `{"v","goal","ops","refs","jobs"}` with the
goal of `workflow.json` and the stale records A (12.55 ± 0.02), B (12.47 ± 0.03), C (12.51 ± 0.01), D (uncertainty
unknown). Expected labels: classify_A outside, classify_B outside, classify_C inside, classify_D unknown.

| Arm | Prompt sha256 | Bytes | Operation text and refs |
|---|---|---|---|
| A | `48ecc5b04ab8c6efdafdb315217a2c1729b1c2c904e52c71648b7abb0f83b0f9` | 905 | The step 4 classify op; refs 0 to 3 are the records. This is the stale packet 48ecc5b0 of live1 and live2; the reconstruction is rebuilt from `workflow.json` and `sources/` and its hash is checked at every freeze, and the committed live1 and live2 ledgers are checked to show it under H. |
| B | `7d8474ea84f52f3e1fad6aa78df2e8e74e7bf6131c8f302c84151403f34e2b9b` | 992 | The B text of 01 verbatim; refs 0 to 3 as in A. |
| C | `68e7833fdf602a2c4fa87e5823371a1c3396c1cc8315e845f6a7449a56254351` | 1137 | The C text of 01 verbatim; refs 0 to 3 plus refs 4 to 7 = `["12.53 mm","12.57 mm"]`, `["12.44 mm","12.50 mm"]`, `["12.50 mm","12.52 mm"]`, `"unknown"`; jobs `[[0,["classify_A",0,4],["classify_B",1,5],["classify_C",2,6],["classify_D",3,7]]]`. |

The C check lives in the harness: `validate_packet` recomputes each interval from its record (Decimal, own code) and
rejects a packet whose second ref does not match, so a mismatched interval cannot be frozen. A test proves it, and
another proves the op texts equal the fenced texts in 01.

## Calls, order and caps

Order, 18 sequential fresh processes, no retries, replacements, continuation or extension:
`ABC | BCA | CAB | ACB | CBA | BAC`, that is slots 1 to 18 = A B C, B C A, C A B, A C B, C B A, B A C.

| Cap | Value | Behavior |
|---|---|---|
| Tokens | 60,000 | Admission: before each launch, tokens spent plus the 5,000 reservation must not exceed 60,000. Spent = known `modelUsage` totals, with a call of unknown usage charged at 5,000. Not provider enforced; an overrun is reported, and the run then stops. |
| Launches | 18 | The schedule has exactly 18 slots; a launched slot always counts. |
| Per call | 300 s | The process is killed at 300 s: outcome `deadline`. |
| Overall | 7,200 s | Measured from the first launch across resumes; no launch after it. |

The command line is the adapter's: `claude -p --model claude-sonnet-5-5 --system-prompt <H> --tools "" --setting-sources "" --strict-mcp-config --no-session-persistence --output-format json`, prompt as UTF-8 on stdin. A test runs the real adapter with a patched `subprocess.run` and compares argv, input and timeout. Before the first launch `run` refuses unless `claude --version` is 2.1.306 and none of these environment variables is set (they can change route or effort): ANTHROPIC_MODEL, ANTHROPIC_DEFAULT_SONNET_MODEL, ANTHROPIC_DEFAULT_OPUS_MODEL, ANTHROPIC_DEFAULT_HAIKU_MODEL, ANTHROPIC_SMALL_FAST_MODEL, CLAUDE_CODE_SUBAGENT_MODEL, CLAUDE_CODE_EFFORT_LEVEL, CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING, MAX_THINKING_TOKENS, CLAUDE_CODE_MAX_OUTPUT_TOKENS, ANTHROPIC_BASE_URL, CLAUDE_CODE_USE_BEDROCK, CLAUDE_CODE_USE_VERTEX.

## Evidence kept per call

`bench/probe/boundary-evidence/ledger.jsonl` (append-only, fsynced: `plan`, then `launch` before the process starts,
then `end`, plus `halt` and `ack`) and `calls/NN-ARM/` with `request.json`, `envelope.json` (raw stdout), `stderr.txt`
and `meta.json` (exit status, timestamps, request digests, unique call id). `report` re-scores every raw envelope
and flags any difference from the recorded evaluation, any changed output, and any duplicate, orphan or missing ledger
record.

## Accounting

Per `modelUsage` entry: `inputTokens + cacheReadInputTokens + cacheCreationInputTokens + outputTokens`, summed over
entries. `thinkingTokens` is kept separately and never added. A missing or non-integer required counter makes the
call's accounting incomplete (never zero, never taken from the CLI `usage`). A missing `thinkingTokens` in any entry
makes thinking unknown (never zero). Model identity is the set of `modelUsage` keys: exactly the requested model is
`ok`, anything else is `mismatch`, absent is `unknown`.

## Stops

* Accounting incomplete after a call: the run halts. A plain rerun refuses; `run --expect ... --acknowledge-halt`
  records an acknowledgement and continues. Selection is still withheld (see Decision).
* A launch without an end record (the process died): counted as launched and as unknown usage, never retried; a
  rerun refuses until `--acknowledge-halt` closes it as a failed call.
* Route mismatch: terminal. The run never continues, not even with `--acknowledge-halt`.
* Any cap above.

## Scoring (independent of the executor)

The strict parser in the harness requires the first nonblank line to be exactly `OZ/1g` and every later nonblank
line to be one JSON value: a one-member `{"id":value}` or a four-element `[id,"error",code,message]` with a valid code
and nonblank message. Duplicate keys, non-finite numbers, unknown, missing or repeated ids, fences or prose reject the
whole reply with no salvage. A member is right only if its value is exactly the expected string.

Call outcomes (one each, in this priority): `deadline`, `process_failure` (nonzero exit, unparseable envelope,
`is_error`, non-success subtype, no result text), `wire_rejected` (zero accepted work), `model_error` (valid reply with
at least one error line), `semantic` (at least one wrong value), `correct`. A call is **entirely correct** if its
outcome is `correct` and it finished within 300 s. The **boundary member** is classify_C only (the one record whose
interval sits on the inclusive limit); a boundary error is classify_C answered wrongly in a strictly accepted reply
(a wrong value or an error line). Wire-rejected calls have no readable members and so no boundary error.

## Reports

Per arm: entirely correct calls of 6, calls with a boundary error, correct members of 24 and boundary members of 6,
counts of semantic, model error, wire rejected, process failure and deadline calls, total known tokens and calls with
unknown tokens, tokens per correct on-time member (failed calls stay in the numerator; zero denominator prints
undefined), and call durations. Two-sided Fisher exact tests of B against A and C against A on entirely correct calls
(6 against 6), descriptive only. Thinking strata `= 0`, `> 0` and unknown per arm against whole-call correctness and
boundary errors, with the known values and a flag when a stratum is empty. Per-call rows with input, cache read,
cache write, output, total, route and seconds, so the order effect on the cache is visible.

## Decision rule as implemented

| Completed result | Verdict |
|---|---|
| Fewer than 6 finished calls in any arm, an unfinished launch, any call whose route is not `ok`, any call with incomplete accounting, or any evidence problem | `incomplete`: no selection decision |
| A has no boundary error | `not_reproduced`: no demonstrated correction, no workflow change |
| A has a boundary error but is not entirely correct on at least 3 of 6 calls | `insufficient_contrast`: nothing selected, counts reported |
| Neither B nor C is entirely correct on 6 of 6 | `no_candidate`: counts reported |
| Exactly one of B, C is 6 of 6 | `nominate` that arm for a separately frozen workflow evaluation and composition qualification |
| Both are 6 of 6 | `nominate` the one with lower total tokens, then lower total elapsed time; equal on both gives `tie` and no preference |

The only claim a nominated arm supports: "No classification failures were observed in six repetitions of this frozen
packet." No result changes G3, G3b, O1, H or any qualification; B and C hard-code 12.48 and 12.52, so a
goal-referencing version of a winner needs its own qualification.

## Zero-token verification before the run

`freeze` (this digest), `dry` (nine fixture replies through the real scoring path: pass, wrong label, malformed,
missing usage, missing thinking, model error line, code fence, duplicate id, wrong model; then seven run scenarios:
mixed schedule with resume, accounting halt and acknowledgement, terminal route mismatch, token ceiling, overall time
cap, orphaned launch, wrong digest), and the unit tests.
