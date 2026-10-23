# Step 3 plan, frozen before the first counted call: Haiku 5.5 on `repair-handoff-20/v1`

Signed text: [01 Astra preregistration](01-astra-prereg.md) as amended by [02 Opus: five changes](02-opus-changes.md),
accepted in [03](03-astra-accept.md). This file records what was built to satisfy it and the exact command to run.
Nothing here is a model result. No model call was made to produce it (the only subprocess besides the fixture
adapters is `claude --version`).

## Derived freeze

| Item | Value |
|---|---|
| Derived freeze digest | `8ec891e79e1e012b33a2f4d1ea3da4c0a3454f1db5bde3a13268c631fd1e29b6` (short: 8ec891e7) |
| Base: current O1 freeze | `088815dbd9d1817af64b5b1d7ed96f4631681193ca1784387084e9421f2b1f36` (short: 088815db), `bench/o1/repair-handoff-20-v1/freeze.json`, still holds (`o1.py freeze` prints `frozen: true`) |
| Record | `bench/o1/repair-handoff-20-haiku/freeze.json` |
| Check | `python bench/o1/step3_haiku.py freeze` |
| Diff against the base spec | exactly two paths, `route.model` and `route.alias_map` (the driver computes the diff and refuses any other changed path) |
| `route.model` | `claude-haiku-5-5` (base: `claude-sonnet-5-5`) |
| `route.alias_map` | `{"claude-haiku-5-5": "claude-haiku-5-5"}` (base: the Sonnet identity map) |

Evidence for the alias value: 389 archived Haiku records under `bench/live/data/*haiku*.jsonl` (the size gates at 1, 4
and 16 among them, `gate1_haiku.jsonl`, the live and effort runs) carry `model`, which `bench/live/run_live.py` fills
with the comma-joined `modelUsage` keys of each `claude -p --output-format json` envelope. All 389 read exactly
`claude-haiku-5-5`, none a list. No archived raw O1 envelope exists for Haiku, so this is the same transport and the
same field family, not the O1 adapter's own envelope. If the key were different, `response_check` would refuse every
candidate of the first call and the suite would end at once with one wasted call; the allocation covers that.

### How the derived pack is loaded, and which pinned files that touches

None. No existing file was edited: not `bench/o1/*.py`, not the O1 pack (`workflow.json` and the rest of
`repair-handoff-20-v1/`), not its `freeze.json`, not `examples/claude_cli_adapter.py`, `oz_*.py` or
`bench/step4/g3b.py`. The O1 freeze therefore still reads 088815db. New files only:

| Path | Why |
|---|---|
| `bench/o1/repair-handoff-20-haiku/route.json` | the route overlay: `route.model`, `route.alias_map`, and descriptive evidence |
| `bench/o1/repair-handoff-20-haiku/freeze.json` | the derived digest record (base, overlay, derived values, code, design) |
| `bench/o1/repair-handoff-20-haiku/control-freeze-32333561.json` | byte copy of the control's freeze record (`git show 079a2f9:bench/o1/repair-handoff-20-v1/freeze.json`, same bytes at `6a473a3`, the control run's commit), so the control-match checks need no git |
| `bench/o1/step3_haiku.py` | the driver: loads the O1 modules, applies the overlay to the in-memory spec, swaps in the derived freeze check, forwards every other command to `o1.main` |
| `bench/o1/step3_checks.py` | the zero-call control-match and label checks |
| `bench/o1/step3_replay_adapter.py` | zero-call adapter that answers with the archived Sonnet accepted functions |
| `tests/test_step3_haiku.py` | tests written first for all of the above |

O1 reads the route through `W.spec()`, which caches `workflow.json` in `W._CACHE`; the driver replaces that one cache
entry for the duration of the process (`applied()` restores everything on exit) and replaces `o1.freeze` so the
refusal logic (`live_refusal`) and the flow request's `workflow_digest` carry the derived digest. O1's interrupt
scenario starts child processes with `Path(__file__)`; under the driver that is the driver, so every process of the
suite sees the Haiku route (a test checks the child command line and a child process reports the route).
`bench/o1/o1.py` is not touched, so its own `freeze` and `live` commands still describe the Sonnet suite.

The derived record pins: the base freeze digest and file, the overlay and control copy, the derived values, the three
new code files and design texts 01 to 03. Any drift is reported by `freeze`, and `live` refuses to start.

## Control-match checks (zero calls), HEAD c508aba

Run: `python bench/o1/step3_haiku.py control-match`. The prompt items run the real executor on the fixture transport
with the replay adapter, which answers each job with the control's own archived accepted function
(`bench/o1/live1/candidates.jsonl`), so the adapter packets are rendered from the Sonnet cores. Each scenario run at
HEAD produced the archived ledger's call sequence.

| Item | Expected (archived control) | At HEAD | Result |
|---|---|---|---|
| Core size-4 prompt, clean, interrupt, stale | `ed27d59c` under system `d941a86d` | `ed27d59c` under `d941a86d` in all three; submitted digest and byte count equal | MATCH |
| Stale core A singleton | `3fb652d8` | `3fb652d8` | MATCH |
| Adapter prompts from the archived Sonnet cores | `1c08ef8e` (clean), `1c628a20` (interrupt), `1ca7cc03` (stale x4), `4157a4b8` (stale A singleton) | all four reproduced, submitted digests and byte counts equal | MATCH |
| Stage run ids (hash of op identity, nodes, texts, generations) | the eight archived ledger names, e.g. `live1-clean-repair_core-e6bf96abe284` | identical names and order in all three scenarios | MATCH |
| Adapter script digest | `deba48b9d68c...` | same | MATCH |
| Effort and other route fields | `default`; control `workflow.json` digest `0a9f58bb...` | same digest, derived route equals base route except model and alias_map | MATCH |
| Parser and wire fields | `oz1g-header/1@sha256:dc58230288900c0e;wire-H-sha256:d941a86d530ab0fe`, `oz_reply.py` and `oz_batch.py` digests | same strings and digests | MATCH |
| Wire system text H | `d941a86d` in every archived call | `d941a86d` from `oz_batch.SYSTEM` and from every replay call | MATCH |
| Route identity (effort, cli_version, adapter, parser) | recomputed from the control's pinned digests | equal to `route('live')` under the derived freeze, model aside | MATCH |
| `claude --version` | 2.1.306 | 2.1.306 | MATCH |
| Accounting scope | adapter `usage_from_envelope` and `reduce` (whole-call `modelUsage`), `o1.totals_of`, `calls_of`, `thinking_tokens`, `ledger_audit`, `oz_flow.flow_usage`, `stage_launches`, `oz_do._accounting` (sha256 of each function source at `079a2f9`), and eight pinned files | every function digest equal, no scope file changed | MATCH |
| Executor paths | files changed since the control freeze are exactly `oz_do.py`, `oz_flow.py`, `oz_runtime.py`, `bench/step4/g3b.py`, and no O1 model operation uses ordered or value inputs | same four, no ordered or value O1 operation | MATCH |

All twelve items MATCH, so the archived Sonnet control stays the control and no matched Sonnet rerun is needed. The
preregistered note stands: Haiku's adapter packets carry Haiku's own accepted cores, so the adapter-stage input bytes
differ by construction. That is the treatment, not a mismatch.

The replay route made the written diff review optional. It is kept here anyway, because it covers what a prompt
replay cannot: the four files changed since the control freeze (`git diff 079a2f9..HEAD`), and why each change is
dormant for O1.

| File | Change | Why O1 does not reach it |
|---|---|---|
| `oz_do.py` | opt-in `{"value": ...}` reference form in `normalize`; `ref_forms` enters the work only when a value ref is used; `_read_refs` passes `values` only for value refs; `_render_inputs` reads `.get('value', text)` | O1 refs are text only; the default request identity is unchanged (run ids equal) |
| `oz_runtime.py` | `Inbox.complete(..., values=None)` stores `result_json` from `values`, default none | default stores `NULL` as before; the only caller passing values is the value-ref path |
| `oz_flow.py` | `ModelOp.inputs` may be an ordered tuple and `values` names value-form inputs; `identity`, descriptors and `_stage_request` change only when `not op.single`; `_model_input`, `_stage_pins` (`inputs_json`), raw-pointer helpers; stage submissions also record `inputs_json`; pin comparison uses canonical J | every O1 model op is single and value-free (checked by the executor-paths item); op identity, stage request and run ids are byte-identical (run ids MATCH); `inputs_json` is a new journal field, not wire; the blank-input message and rule are unchanged |
| `bench/step4/g3b.py` | pack name read from a global, `expected_text` ordered refs from `model_refs`, `baseline` flag in `suite_verdict` | step 4 packs only; O1's gate imports its reply parser (`parse_reply`, untouched) and nothing else changed there |

## Experimental labels with a Haiku model id (zero calls)

`python bench/o1/step3_haiku.py labels`: under the derived live route (model `claude-haiku-5-5`, route fields as the
control's), the real executor on the fixture transport (its envelope reports the Haiku id, so the response check
passes) sends clean `[4, 4]` and stale `[4, 4, 1, 1]`. Result: **PASS**. All six dispatches at size 4 (4) and size 1 (2)
are labeled `experimental`, the O1 gate's `every_dispatch_experimental` holds, and both scenarios pass `pass_g3c` on
the fixture. Negative control: the same flows with `experimental_sizes` naming neither size label every dispatch
`qualified_cell`, which is what `oz_do.CELLS` gives `claude-haiku-5-5` at sizes 1 and 4.

## Derived dry gate (fixture route)

`python bench/o1/step3_haiku.py dry --workspace .oz-runtime/hk-dry`: **PASS** (exit 0, `pass: true`). The report records the derived freeze (`frozen: true`, digest 8ec891e7, base 088815db,
no problems). All five scenarios `pass_g3c` on the fixture (clean 2 launches, repeat 0, interrupt 2, stale 4, bump 0),
the interrupt scenario's kills at both boundaries ran through the driver's child processes, and every dry block
passes: freeze, five scenarios, within allocation (8 launches, 23,391 fixture tokens, accounting complete), recovery,
sabotage, gate sabotage, escape suite, seeds, oracle, feasibility, measured (reserve 17,358 equals the frozen one).
The fixture route does not read `route.model`, so the dry gate proves the machinery under the derived freeze, not the
Haiku model identity; the alias map and labels are covered by the route, label and response-check tests above.

## The live command (one Haiku suite; paid; run it once)

Before: read the weekly Claude usage figure now. Start only if it is below 45%. Re-check the freeze and CLI, then run
from the repo root in PowerShell, in the foreground, with a fresh workspace (the harness refuses a used one):

```powershell
Set-Location <repo root>
$env:TIKTOKEN_CACHE_DIR = "<repo root>\.token-cache"
$env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python.exe bench\o1\step3_haiku.py freeze          # must print frozen: true, digest 8ec891e7...
claude --version                                                 # must print 2.1.306
$env:O1_LIVE_CONFIRM = "1"
.venv\Scripts\python.exe bench\o1\step3_haiku.py live --workspace .oz-runtime\hk1 --prefix hk1 --quota-before <WEEKLY_PERCENT_READ_NOW>
```

After it finishes (or stops), read the weekly figure again and record it:

```powershell
.venv\Scripts\python.exe bench\o1\step3_haiku.py quota-after --workspace .oz-runtime\hk1 --prefix hk1 --percent <WEEKLY_PERCENT_READ_AFTER>
```

`live` refuses without `O1_LIVE_CONFIRM`, without a numeric `--quota-before` below 45, on a changed derived or base
freeze, on another CLI version, and on a workspace that already holds a flow or a memo store. There is no option to
rerun one scenario. `--quota-before` and `quota-after` are bookkeeping in the driver (written to
`.oz-runtime/hk1/quota-hk1.json`), not a per-launch hook: the pinned harness has none, as 02 change 5 states. The
report is `.oz-runtime/hk1/report-live-hk1.json`; the workspace's SQLite files are the authority. Workspace
`.oz-runtime/hk1` is 17 characters of path under the repo, shorter than the control's `.oz-runtime/o1-live1`; the
request prefix is `hk1` and the memo namespaces are `live-hk1-*`, so no Sonnet entry can be hit.

## Allocation and stops (unchanged from 01 and the O1 pack)

150,000 tokens, 18 launches at most, 8 per scenario, one call in flight, 300 s per call, 3,600 s per scenario, four-hour
envelope. The failure-free schedule is 8 launches (clean 2, repeat 0, interrupt 2, stale 4, bump 0); 8 launches is the
failure-free schedule, not a guarantee. The admission reserve per launch (17,358) is headroom, not an enforced billing
ceiling. One suite, no discretionary rerun, no second model, no effort tuning, no fallback, no reply repair.

Quota rule:

1. Read the weekly figure before the suite. Start only below 45%. The 42% supplied in 01 is the starting figure; every
   Claude preparation and review call counts against it.
2. Record the figure after the suite (`quota-after`).
3. If monitoring sees 46% while the suite is running, stop it and report the suite as incomplete, not a pass.
4. At 49% stop everything (hard stop).
5. Also stop on freeze drift, unknown billing, an exhausted allocation or an unrecoverable gate failure. Keep the
   evidence. Never reset a budget or deadline.

## Decision gate (from 01, restated)

`pass_g3c` unchanged on every scenario first. Only then whole-suite billed tokens (whole-call `modelUsage` including
cache components, reasoning once, failures and retries), then elapsed time; equal tokens need lower elapsed time.
Control: the archived Sonnet O1 suite, all five pass, 55,413 tokens, 190.3 s, 8 launches, 56 of 56 first-attempt
acceptances. Both arms are one suite each; report the token difference as measured on those two suites only. A pass
supports this frozen O1 use case only: there is no model caller in this comparison, no general coding claim and no
automatic promotion of the experimental size-4 and size-1 cells.

## Before running, in order

1. `python bench/o1/o1.py freeze` prints 088815db and `step3_haiku.py freeze` prints 8ec891e7, both `frozen: true`.
2. `python bench/o1/step3_haiku.py control-match` exits 0 (all MATCH) and `labels` exits 0.
3. Full test suite green.
4. Weekly figure read and below 45%.

## Launch record, 2026-10-23

The owner approved the paid run. Before launch the Claude weekly figure read **45%**. The preregistered rule says start
only below 45%, so the suite was **not started**. Nothing was spent on model calls. It starts unchanged at this freeze
(8ec891e7) once the weekly figure reads below 45% (the weekly window resets 2026-10-27 09:00 UTC), after re-running
`freeze`, the control-match check and `claude --version`.
