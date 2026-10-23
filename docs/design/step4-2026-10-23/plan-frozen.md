# Step 4 preregistration: `inspection-handoff-20/v1` (frozen before the first counted call)

Plan: [README.md](README.md), signed in [03](03-astra-r2-signed-plan.md) as amended by [04](04-opus-r2-sign.md).
Label: executor conformance gate. Until the owner decides O1, a pass is reported as "conformance passed", not as the
real-workflow criterion met.

Freeze: `bench/step4/inspection-handoff-20-v1/freeze.json`, digest printed by the G0 command below. It pins the graph,
operation texts, checks, sources and the revision 2 correction, expected values, route, scenarios, fault hooks,
budgets, both baseline prompts, and the digests of every executor, adapter, harness and evaluator file (CRLF
normalized). Any change to those files needs `freeze --write` and a new G2 run before G3. An executor bug found in G3
means fix, refreeze and rerun all of G3; spent tokens stay charged.

## Route

Sonnet 5.5 (`claude-sonnet-5-5`), default effort, `claude -p` with no tools through `examples/claude_cli_adapter.py`,
Claude CLI 2.1.306, OZ/1g system text H and parser unchanged, durable runner, `oz1g-selective-v1`, two attempts per
job generation, packets of 4 or 1 only (size 4 labeled experimental composition, size 1 the qualified Sonnet cell).
The route identity in every computation key is the adapter argv plus script digest, model, effort, CLI version, wire
and parser digests. The CLI version is checked before the run and before every launch; a change blocks. The actual
model is read from the retained envelope's `modelUsage` before any candidate is accepted; a missing or other model
refuses the call's candidates. Memo namespaces are `live-*` for G3 and `fixture-*` for G2.

## Commands (PowerShell, repo root)

```powershell
$env:TIKTOKEN_CACHE_DIR = ".token-cache"; $env:PYTHONIOENCODING = "utf-8"
# G0: every digest must match ("frozen": true)
.venv/Scripts/python.exe bench/step4/step4.py freeze
# G1: full regression plus the focused suite
.venv/Scripts/python.exe -m unittest discover -s tests
# G2: zero-token dry gate (fixture adapter), must print "pass": true
.venv/Scripts/python.exe bench/step4/step4.py dry --workspace .oz-runtime/step4-dry
# G3: five live scenarios in order, with C3 and C5 checks (paid)
$env:STEP4_LIVE_CONFIRM = "1"
.venv/Scripts/python.exe bench/step4/step4.py live --workspace .oz-runtime/step4-live1 --prefix live1
# The one permitted model-reply-failure rerun, same workspace and caps (example: stale)
.venv/Scripts/python.exe bench/step4/step4.py live --workspace .oz-runtime/step4-live1 --prefix live1 --only stale --rerun 1
# G4: baseline arm, four calls (paid)
.venv/Scripts/python.exe bench/step4/step4.py baseline --workspace .oz-runtime/step4-live1
```

Reports: `report-live-live1.json` and `baseline-live.json` in the workspace; each flow also writes
`flows/<request_id>/execution-record.json`. The workspace's SQLite files are the authority.

## Expected launches (G3)

| Scenario | Request | Launches | Packets | Memo hits | Notes |
|---|---|---:|---|---:|---|
| clean | `live1-clean` | 3 | 4, 4, 4 | 0 | cold namespace |
| exact repeat | `live1-repeat` | 0 | none | 12 | clean namespace, new request identity, own publication intent |
| interrupted | `live1-interrupt` | 3 | 4, 4, 4 | 0 | cold; hard exit at `worker.after_capture` (first call), then at `flow.publish.after_manifest`, then the same command again |
| stale input | `live1-stale` | 5 | 4, 4, 1, 1, 4 | 6 | cold; A becomes 12.55 mm right after node 11 commits |
| revision bump | `live1-bump` | 0 | none | 20 | clean namespace; A gets revision 2 with identical bytes at the same hook |
| **Total** | | **11** | | | about 28.5k estimated tokens |

Caps: executor 60,000 tokens and 16 launches for the whole workspace, 8 launches per scenario, 5,000-token admission
reserve per launch (a call with unknown usage is charged at the reserve), 3,600 s per scenario deadline that resume
never resets, 300 s per call, one in-flight call in quota group `claude-cli` (per-user `~/.akor/quota.sqlite`). Baseline
20,000 tokens and 5 launches, admission headroom 6,000 until the first call is measured, then the largest measured
call. The four-hour envelope is the operator's to watch; the harness records start and finish times.

## G3 pass, per scenario

Delivered before its deadline with one delivery; the independent evaluator (`bench/step4/evaluator.py`) passes on the
delivered bytes; launches, packet sizes and memo hits equal the table (`pass`), or extra launches are no more than
the recorded reply rejections (`pass_with_recorded_rejections`); every launch has exactly one ledger call. Interrupted:
both kills hit their boundary, the first capture is recovered without a new call, the manifest is reconciled on
resume. Stale (C3): no packet after the mutation holds the old A bytes; dispatch order after it is extract_A, bounds_A,
then the four classifications; B, C and D extract and bounds are memo hits whose computation keys equal the first
run's; old A acceptances stay as history and the delivery cites A revision 2. C5, zero calls, each on an isolated
copy of the clean state: handoff bytes identical across clean, repeat and interrupted and differing only in A's
revision for the bump; a route change plans 12 misses; an added acceptance-only bounds check revalidates the four
stored candidates with no launch; revoking the clean bounds_B entry plans exactly one miss.

Accounting: usage comes only from `modelUsage`. A call without it is unknown usage, which keeps correctness but
blocks a within-budget pass and an exact cost comparison.

## G4

Calls in order: revision 1 three times, revision 2 once, each one `claude -p` with `baseline/system.txt` and the frozen
prompt, captured by the durable runner. The same evaluator scores the JSON only; Markdown, durable publication and
crash recovery are outside baseline coverage. Report the four measured calls apart from any five-scenario projection;
repeat, revision bump and interruption costs for the baseline are counterfactual estimates.

## Choices the plan left open

1. Revision bump: only A advances (same hook and record as the stale run), so cases 4 and 5 differ only in A's bytes.
2. Model checks are job-bound host checks computed from each job's own record (`mat_fields`, `mat_bounds`,
   `mat_classify`); the strengthened C5 check is `max_bytes` 64 on bounds.
3. Node 6 joins extractions into `key=value; ...` text, so accepted extractions reproduce the source bytes.
4. A pending memo revalidation (verifier outage) blocks the whole stage request rather than dispatching around it.
5. The flow request ID names the scenario; a rerun appends `-r<N>` and gets a fresh cold namespace when the scenario's
   namespace is its own.

## Refreeze after independent review (2026-10-23, before any live call)

An independent review of 404f04b found seven defects (in-stage launches not counted toward the caps, a publish race
that blocked the flow, direct source reads missing from a node's read set, a weak evaluator digest check, a freeze
check that did not verify its own digest, an ungated live entry point, a plan-only route mismatch). All were fixed
with failing tests first (491 tests), the dry gate passes again (11 launches, six sabotage cases caught), and the
freeze digest above was replaced: previously 3ccadb65, now 49115f95. No live call had been made under either digest.
