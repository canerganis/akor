# Step 1 results: zero-call trace analysis (2026-10-23)

Preregistration: [03-astra-accept-and-step1-prereg.md](03-astra-accept-and-step1-prereg.md). No model call was made and nothing was committed. This file is generated: `python bench/analysis/step1_traces.py --md docs/design/next-2026-10-23/step1-results.md` regenerates every number below from the frozen manifest, and `--csv bench/analysis/step1_out` writes the full per-call, per-run and per-cell tables (`per_call.csv` has one row per record with its source locator).

## 1. Conclusion

**No demonstrated actionable bottleneck.**

The rule (prereg item 3) needs a category of at least 25% of billed tokens or elapsed time, inside one workload/model/size/arm/scenario cell, on a model-needed job, movable by one named variable, with known attribution. Of 143 cells, 12 are model-needed (per-stage cells plus the all-stages cells), and all of them are O1 repair cells (`o1-repair-handoff-20/live1`). Every other cell is a materials or heterogeneous-packet job whose check recomputes the full answer, so it is host-computable (section 8) and cannot qualify.

In the O1 cells:

1. Thinking is at most 15.7% of billed tokens in any one cell, below 25%. Effort does not qualify (it qualifies only through thinking).
2. Avoidable waiting is 0 ms demonstrated. No source records a queue or rate-limit wait (section 7), and the dependency order core, adapter is a DAG edge, not waiting. Scheduling does not qualify.
3. Failed, resent or check-driven calls are 0 tokens in O1 (the interrupted call was recovered from its capture and its result was used, so it is not wasted work).
4. Two categories are at or above 25% but cannot qualify. Packet input (27.0% to 54.1%, an estimate) is the job payload itself, with no variable that moves it without changing the job. Fixed per-call input (25.7% to 56.2%) is H plus the CLI's own framing and the corpus cannot separate them, so it is an unattributed residual, which the rule says cannot establish qualification (sections 5.2 and 9).

What the traces do show, outside the rule's reach:

1. Thinking is 27.5% to 58.3% of billed tokens in 9 cells (8 haiku-5-5, 1 sonnet-5-5), but only on host-computable jobs. The movable variable there is not effort, it is moving the job to the host (the authoring rule). They fail the rule only because the job is not model-needed. Workloads: live24_1g_D_haiku64, live24_1g_D_haiku_het, live25_1g_R_haiku, live26_1g_R3_haiku, live26_1g_R3_sonnet, live29_1g_haiku_paired, pilot2-materials-1g.
2. Check-driven rework (resent calls plus the call each resend names) is 32.7% to 100.0% of billed tokens in 8 step4 all-stages cells (step4-inspection-handoff-20/live1, step4-inspection-handoff-20/live2, step4-inspection-handoff-20/live3), again on host-computable jobs.
3. Measured caller overhead is 52.2% to 87.7% of run tokens in the 9 delegating cells of pilot_k2, on materials jobs. This describes the stored runs; the settled same-model comparison is not reopened.
4. The one measurement that would decide the O1 fixed-input question is a split of H from the CLI framing. No call in the corpus varies H alone, so it cannot be made from these traces. It would cost a handful of calls with a cut-down H, which this step may not make.
5. If the fixed per-call input is read as H by definition, then in every O1 cell it is 25.7% to 56.2% and the single variable is H length. Section 9 lists those cells so the decision does not depend on how this report words it.

## 2. Frozen manifest

Digest `8a1836182cdceaadfe63db56e808c8ffb0c1b423de2955b7c8c44048aa438191` (SHA-256 over the lines `<file sha256>  <path>` sorted by path, all 858 entries, raw file bytes). Full list with per-file SHA-256: `bench/analysis/step1_manifest.json`. It was built by `--freeze` from the selectors in the preregistration before any usage value was parsed. Every analysis run re-hashes every file and refuses to continue on a mismatch.

| group | stratum | observation files | provenance files | bytes |
|---|---|---|---|---|
| live22 | main | 1 | 1 | 84,629 |
| live23 | main | 1 | 1 | 14,992 |
| live24 | main | 5 | 5 | 89,696 |
| live25 | main | 2 | 2 | 21,229 |
| live26 | main | 3 | 3 | 24,896 |
| live27 | main | 2 | 2 | 52,279 |
| live28 | main | 1 | 1 | 36,933 |
| live29 | main | 1 | 1 | 36,659 |
| pilot2 | main | 4 | 4 | 277,476 |
| pilot2 | smoke | 1 | 1 | 1,836 |
| pilot2q | main | 3 | 3 | 70,193 |
| pilot_k | main | 3 | 3 | 173,954 |
| pilot_k2-dir | main | 0 | 496 | 2,312,953 |
| pilot_k2-caller | main | 48 | 0 | 2,386,704 |
| pilot_k2-worker | main | 27 | 0 | 203,975 |
| pilot_k | smoke | 2 | 1 | 17,919 |
| pilot_k2-dir | smoke | 0 | 48 | 403,595 |
| pilot_k2-worker | smoke | 3 | 0 | 27,384 |
| pilot_k2-caller | smoke | 4 | 0 | 257,264 |
| o1-live1 | main | 8 | 2 | 394,768 |
| boundary-probe | control | 18 | 57 | 189,626 |
| adopt-qual | control | 9 | 29 | 86,000 |
| step4-live1 | main | 11 | 15 | 198,097 |
| step4-live2 | main | 11 | 2 | 155,306 |
| step4-live3 | main | 11 | 2 | 169,845 |

Observation files supply usage. Provenance files (run manifests, reports, candidates, ledgers, request and metadata files, baseline captures) supply timing, model identity and recovered usage, never a second observation. Smoke runs (`*smoke*`, `pilot_k2_smoke/`) are a separate descriptive stratum and never qualify a bottleneck. The boundary-probe and adopt-qual envelopes are the `control` stratum. `pilot_k2.jsonl` and `pilot_k2_smoke.jsonl` are aggregates of the transcripts and worker ledgers in the directories next to them; they are cross-checked and never added (section 3). Excluded by selector: `deliveries/` under O1 (published artifacts), fixtures, and live2 to live21 plus the gate and effort files. `step4/live1/baseline/captures` are hashed as provenance but not parsed: they are not a selector observation file.

## 3. Accounting completeness

| group | stratum | kind | counter source (first clause) | records | uncached in | cache write | cache read | total in | output | thinking | wall or in-flight | api ms | no denominator | failed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| live22 | main | run | CLI result.usage via run_live.call (run_live.py:119-127) | 25 | 25 | 25 | 25 | 25 | 25 | 25 | 25 | 25 | 0 | 0 |
| live23 | main | run | CLI result.usage via run_live.call (run_live.py:119-127) | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 5 | 0 | 0 |
| live24 | main | run | CLI result.usage via run_live.call (run_live.py:119-127) | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 30 | 0 | 0 |
| live25 | main | run | CLI result.usage via run_live.call (run_live.py:119-127) | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 0 | 0 |
| live26 | main | run | CLI result.usage via run_live.call (run_live.py:119-127) | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 8 | 0 | 0 |
| live27 | main | run | CLI result.usage via run_live.call (run_live.py:119-127) | 15 | 15 | 15 | 15 | 15 | 15 | 15 | 15 | 15 | 0 | 0 |
| live28 | main | run | CLI result.usage via run_live.call (run_live.py:119-127) | 10 | 10 | 10 | 10 | 10 | 10 | 10 | 10 | 10 | 0 | 0 |
| live29 | main | run | CLI result.usage via run_live.call (run_live.py:119-127) | 10 | 10 | 10 | 10 | 10 | 10 | 10 | 10 | 10 | 0 | 0 |
| pilot2 | main | run | runner-summed modelUsage over every reported model incl. subagents (pi | 372 | 372 | 372 | 372 | 372 | 372 | 372 | 372 | 372 | 0 | 28 |
| pilot2 | smoke | run | runner-summed modelUsage over every reported model incl. subagents (pi | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| pilot2q | main | run | runner-summed modelUsage over every reported model incl. subagents (pi | 144 | 144 | 144 | 144 | 144 | 144 | 144 | 144 | 144 | 0 | 7 |
| pilot_k | smoke | run | runner-summed modelUsage (pilot_k.py:78-81) | 1 | 0 | 0 | 0 | 1 | 1 | 0 | 1 | 0 | 0 | 0 |
| pilot_k | main | run | runner-summed modelUsage (pilot_k.py:78-81) | 6 | 0 | 0 | 0 | 6 | 6 | 0 | 6 | 0 | 0 | 0 |
| pilot_k2-caller | main | caller | raw modelUsage (all turns, all models) | 48 | 48 | 48 | 48 | 48 | 48 | 48 | 48 | 48 | 0 | 0 |
| pilot_k2-worker | main | worker | adapter call ledger (from envelope modelUsage) | 27 | 27 | 27 | 27 | 27 | 27 | 0 | 27 | 0 | 0 | 0 |
| pilot_k2-worker | smoke | worker | adapter call ledger (from envelope modelUsage) | 3 | 3 | 3 | 3 | 3 | 3 | 0 | 3 | 0 | 0 | 0 |
| pilot_k2-caller | smoke | caller | raw modelUsage (all turns, all models) | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 0 | 0 |
| o1-live1 | main | call | adapter call ledger (from envelope modelUsage) | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 7 | 0 | 0 | 0 |
| o1-live1 | main | call | recovered usage from bench/o1/live1/report-live-live1.json (envelope n | 1 | 0 | 0 | 0 | 1 | 1 | 1 | 0 | 0 | 0 | 0 |
| step4-live1 | main | call | adapter call ledger (from envelope modelUsage) | 14 | 13 | 13 | 13 | 13 | 13 | 0 | 13 | 0 | 1 | 0 |
| step4-live2 | main | call | adapter call ledger (from envelope modelUsage) | 11 | 11 | 11 | 11 | 11 | 11 | 11 | 11 | 0 | 0 | 0 |
| step4-live2 | main | call | recovered usage from bench/step4/live2/report-live-live2.json (envelop | 1 | 0 | 0 | 0 | 1 | 1 | 1 | 0 | 0 | 0 | 0 |
| step4-live3 | main | call | adapter call ledger (from envelope modelUsage) | 11 | 11 | 11 | 11 | 11 | 11 | 11 | 11 | 0 | 0 | 0 |
| step4-live3 | main | call | recovered usage from bench/step4/live3/report-live-live3.json (envelop | 1 | 0 | 0 | 0 | 1 | 1 | 1 | 0 | 0 | 0 | 0 |
| boundary-probe | control | envelope | raw modelUsage | 18 | 18 | 18 | 18 | 18 | 18 | 18 | 18 | 18 | 0 | 7 |
| adopt-qual | control | envelope | raw modelUsage | 9 | 9 | 9 | 9 | 9 | 9 | 9 | 9 | 9 | 0 | 1 |

Counts are records with the counter known. A record with no denominator has no known total input or output. The sources differ in what they retained:

1. Raw `modelUsage` retained and summed over every reported model here: caller transcripts (`result.modelUsage`) and control envelopes. Thinking is `modelUsage.thinkingTokens`.
2. Runner-summed `modelUsage` (`pilot2.py:66-71`), stored as flat fields: pilot2 and pilot2q. `modelUsage` itself was not kept, so it cannot be re-derived here.
3. CLI `result.usage` through `run_live.call` (`run_live.py:119-127`): live22 to live29. This is not `modelUsage`. It equals it for a single tool-less turn, but the turn count was not stored, so that equality is assumed, not shown. Counters are used as stored and the source is named in every row.
4. Adapter call ledgers (step4, O1, worker ledgers), which derive usage from the envelope's `modelUsage` (`examples/claude_cli_adapter.py:16-30`) but do not record thinking. Thinking for step4 live2 and live3 and for O1 comes from `thinking_tokens_per_call` in the run report (`bench/step4/step4.py:416-438`, `bench/o1/o1.py:363-397`), which read the retained CLI envelope; the envelopes are not in the corpus. step4 live1 has no thinking at all.
5. Old `pilot_k_*.jsonl` rows hold only total input and output (caller plus worker). Cache write, cache read and thinking are unknown.

Missing-accounting records, retained as such:

| locator | run | stage | size | what is known |
|---|---|---|---|---|
| bench/o1/live1/calls-live1-interrupt-repair_core-e6bf96abe284.jsonl (line 1 call_start) | o1-live1:interrupt | repair_core | 4 | total in 5311, out 2258 recovered from the run report; cache split and wall unknown |
| bench/step4/live1/calls-live1-interrupt-extract-5c8f8123fe4f.jsonl (line 1 call_start) | step4-live1:interrupt | extract | 4 | nothing (no call_end, no report row): excluded from every denominator |
| bench/step4/live2/calls-live2-interrupt-extract-5c8f8123fe4f.jsonl (line 1 call_start) | step4-live2:interrupt | extract | 4 | total in 2543, out 171 recovered from the run report; cache split and wall unknown |
| bench/step4/live3/calls-live3-interrupt-extract-5c8f8123fe4f.jsonl (line 1 call_start) | step4-live3:interrupt | extract | 4 | total in 2541, out 171 recovered from the run report; cache split and wall unknown |

Deduplication checks (aggregate versus child usage):

1. `pilot_k2.jsonl` aggregates against transcripts plus worker ledgers: 48 of 48 runs match exactly on caller and worker input and output (4 smoke runs have no aggregate row). The aggregate rows are not added; only the children are.
2. The caller transcript's per-message usage is a child of its `result.modelUsage` aggregate; only `modelUsage` is used. Worker calls run in separate processes, so caller `modelUsage` and worker ledger usage do not overlap and are added.
3. Duplicate call identities across ledger files: 0.
4. Run report `totals.tokens_known` against the sum of ledger calls (plus recovered usage):

| run | report tokens_known | ledger sum | result |
|---|---|---|---|
| o1-live1 | 55,413 | 55,413 | match |
| step4-live1 | 36,146 | 33,437 | ledger lacks 2,709 |
| step4-live2 | 31,346 | 31,346 | match |
| step4-live3 | 31,309 | 31,309 | match |

   The step4 live1 difference is the killed interrupt-extract call, which has no recovery row in that report.

## 4. Corpus totals and denominators

| group | stratum | records | with denominator | denominator (in+out) | input | output | thinking (where known) | records with thinking |
|---|---|---|---|---|---|---|---|---|
| live22 | main | 25 | 25 | 158,303 | 99,751 | 58,552 | 22,169 | 25 |
| live23 | main | 5 | 5 | 28,905 | 17,463 | 11,442 | 5,573 | 5 |
| live24 | main | 30 | 30 | 221,643 | 98,181 | 123,462 | 88,094 | 30 |
| live25 | main | 8 | 8 | 62,349 | 27,880 | 34,469 | 25,369 | 8 |
| live26 | main | 8 | 8 | 70,873 | 29,213 | 41,660 | 30,380 | 8 |
| live27 | main | 15 | 15 | 100,659 | 67,871 | 32,788 | 10,419 | 15 |
| live28 | main | 10 | 10 | 74,633 | 50,088 | 24,545 | 8,066 | 10 |
| live29 | main | 10 | 10 | 111,173 | 49,723 | 61,450 | 45,199 | 10 |
| pilot2 | main | 372 | 372 | 3,477,802 | 3,243,158 | 234,644 | 67,209 | 372 |
| pilot2 | smoke | 1 | 1 | 152,151 | 145,409 | 6,742 | 949 | 1 |
| pilot2q | main | 144 | 144 | 354,371 | 336,196 | 18,175 | 13,894 | 144 |
| pilot_k | smoke | 1 | 1 | 16,229 | 13,637 | 2,592 | 0 | 0 |
| pilot_k | main | 6 | 6 | 201,404 | 174,665 | 26,739 | 0 | 0 |
| pilot_k2-caller | main | 48 | 48 | 1,071,578 | 979,216 | 92,362 | 9,768 | 48 |
| pilot_k2-worker | main | 27 | 27 | 196,374 | 144,346 | 52,028 | 0 | 0 |
| pilot_k2-worker | smoke | 3 | 3 | 39,445 | 32,141 | 7,304 | 0 | 0 |
| pilot_k2-caller | smoke | 4 | 4 | 146,617 | 137,283 | 9,334 | 850 | 4 |
| o1-live1 | main | 8 | 8 | 55,413 | 42,743 | 12,670 | 5,956 | 8 |
| step4-live1 | main | 14 | 13 | 33,437 | 32,213 | 1,224 | 0 | 0 |
| step4-live2 | main | 12 | 12 | 31,346 | 30,021 | 1,325 | 222 | 12 |
| step4-live3 | main | 12 | 12 | 31,309 | 30,024 | 1,285 | 182 | 12 |
| boundary-probe | control | 18 | 18 | 48,730 | 46,746 | 1,984 | 690 | 18 |
| adopt-qual | control | 9 | 9 | 25,506 | 24,193 | 1,313 | 768 | 9 |

Total denominator: main 6,281,572, smoke 354,442, control 74,236 tokens, 790 records, 143 cells.

## 5. Audit of the two prior claims

### 5.1 O1 thinking, 584 to 1,186 tokens per size-4 call

| scenario | op | locator (ledger) | thinking | output | billed in+out | thinking / output | thinking / billed | thinking source |
|---|---|---|---|---|---|---|---|---|
| clean | repair_adapter | bench/o1/live1/calls-live1-clean-repair_adapter-d5b952610976.jsonl (line 2 call_end) | 904 | 1870 | 8535 | 48.3% | 10.6% | bench/o1/live1/report-live-live1.json thinking_tokens_per_ca |
| clean | repair_core | bench/o1/live1/calls-live1-clean-repair_core-e6bf96abe284.jsonl (line 2 call_end) | 673 | 1801 | 7112 | 37.4% | 9.5% | bench/o1/live1/report-live-live1.json thinking_tokens_per_ca |
| interrupt | repair_adapter | bench/o1/live1/calls-live1-interrupt-repair_adapter-e9b423c50f7b.jsonl (line 2 call_end) | 858 | 1860 | 8479 | 46.1% | 10.1% | bench/o1/live1/report-live-live1.json thinking_tokens_per_ca |
| interrupt | repair_core | bench/o1/live1/calls-live1-interrupt-repair_core-e6bf96abe284.jsonl (line 1 call_start) | 1172 | 2258 | 7569 | 51.9% | 15.5% | bench/o1/live1/report-live-live1.json thinking_tokens_per_ca |
| stale | repair_adapter | bench/o1/live1/calls-live1-stale-repair_adapter-02020e6adf2d.jsonl (line 2 call_end) | 584 | 1579 | 8193 | 37.0% | 7.1% | bench/o1/live1/report-live-live1.json thinking_tokens_per_ca |
| stale | repair_core | bench/o1/live1/calls-live1-stale-repair_core-e6bf96abe284.jsonl (line 2 call_end) | 1186 | 2265 | 7574 | 52.4% | 15.7% | bench/o1/live1/report-live-live1.json thinking_tokens_per_ca |

Verdict: **CONFIRMED**. All 6 size-4 O1 calls carry a thinking value, minimum 584, maximum 1,186. The values come from the O1 run report (`bench/o1/live1/report-live-live1.json`, `thinking_tokens_per_call`), not from the call ledgers, which do not record thinking; the report read the retained envelope, which is outside the corpus. Report input and output tokens equal the ledger's for every joined call. Size-1 O1 calls: 133, 446.

### 5.2 About 2,000 H tokens per call as cache write or cache read

Measured: per-call input that does not scale with the prompt. For each ledger group the billed input total is regressed on the call's own prompt-size estimate (o200k tokens, from the ledger); the intercept is the per-call input paid whatever the packet.

| fit group | model | calls | intercept (tokens per call) | slope (billed per estimated token) | R squared |
|---|---|---|---|---|---|
| o1-repair-handoff-20 | sonnet-5-5 | 7 | 2,188 | 1.469 | 1.0000 |
| pilot_k2-B-art | sonnet-5-5 | 12 | 1,566 | 1.352 | 0.9999 |
| pilot_k2-B-reply | sonnet-5-5 | 6 | 1,567 | 1.354 | 0.9999 |
| step4-inspection-handoff-20 | sonnet-5-5 | 22 | 2,174 | 1.504 | 0.9981 |
| step4-inspection-handoff-20 | unrecorded | 13 | 2,179 | 1.486 | 0.9980 |

Per-call fixed input in the 42 step4 and O1 ledger calls with a regression: minimum 2,166, maximum 2,199, mean 2,178. Of it, 55.5% was paid as cache read and 44.5% as cache write over those calls (assuming the fixed input is the cached prefix, which the counters cannot confirm). The H text itself is 1590 bytes (system sha `d941a86d`; o200k estimate 372 tokens, an estimate not a billed count).

Verdict: **PARTLY SUPPORTED, NOT AS H.** About 2,000 tokens of fixed input per call is real and stable (2,166 to 2,199). It is not H. A token covers at least one byte, so H cannot exceed 1,590 billed tokens, and its o200k estimate is 372. The rest of the fixed input, at least 576 tokens, is the CLI's own request framing, which the same calls pay with `--tools ''`, an empty settings source and a custom `--system-prompt`. A 603-token block is the smallest cache read in the corpus (`cr = 603` in 19 of 42 ledger calls, and in 144 of 144 pilot2q calls whose system text was cut down per call), so it is read whatever H says and is CLI framing, not H. The corpus has no call that varies H alone, so the H share of the fixed input is bounded (0 to 1,590 tokens) but not measured.

Other fixed intercepts for context (different system prompts, so not comparable): pilot_k2-B-art sonnet-5-5 1,566; pilot_k2-B-reply sonnet-5-5 1,567.

## 6. Per-call breakdowns

Denominator per call = uncached input + cache write + cache read + output, each once. Thinking is a subset of output. Visible output = output minus thinking. Packet input is the regression estimate described in 5.2 (slope times the call's own estimate). Fixed input is the remainder of the billed input: H plus CLI framing, inseparable. `unknown` means the corpus does not have the counter. Flat per-run families (pilot2, pilot2q, live22 to live29, old pilot_k) have one record per process and are in `per_call.csv` with their line locators; the cell tables in section 7 aggregate them.

### 6.1 O1 repair (the only model-needed workload)

| locator | scenario | stage | members | input | cache write | cache read | output | thinking | denominator | visible out | packet in (est) | fixed in | in-flight ms | tags and outcome |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bench/o1/live1/calls-live1-clean-repair_adapter-d5b952610976.jsonl (line 2 call_end) | clean | repair_adapter | 4 | 6,665 | 6,060 | 603 | 1,870 | 904 | 8,535 | 966 | 4,473 | 2,192 | 20,172 | ok |
| bench/o1/live1/calls-live1-clean-repair_core-e6bf96abe284.jsonl (line 2 call_end) | clean | repair_core | 4 | 5,311 | 4,706 | 603 | 1,801 | 673 | 7,112 | 1,128 | 3,116 | 2,195 | 18,921 | ok |
| bench/o1/live1/calls-live1-interrupt-repair_adapter-e9b423c50f7b.jsonl (line 2 call_end) | interrupt | repair_adapter | 4 | 6,619 | 6,014 | 603 | 1,860 | 858 | 8,479 | 1,002 | 4,435 | 2,184 | 22,766 | ok |
| bench/o1/live1/calls-live1-interrupt-repair_core-e6bf96abe284.jsonl (line 1 call_start) | interrupt | repair_core | 4 | 5,311 | unknown | unknown | 2,258 | 1,172 | 7,569 | 1,086 | 3,116 | 2,195 | unknown | no call_end; capture recovered, no |
| bench/o1/live1/calls-live1-stale-repair_adapter-02020e6adf2d.jsonl (line 2 call_end) | stale | repair_adapter | 4 | 6,614 | 6,009 | 603 | 1,579 | 584 | 8,193 | 995 | 4,434 | 2,180 | 17,797 | ok |
| bench/o1/live1/calls-live1-stale-repair_adapter-d2f02022776f.jsonl (line 2 call_end) | stale | repair_adapter | 1 | 3,649 | 3,044 | 603 | 264 | 133 | 3,913 | 131 | 1,450 | 2,199 | 11,343 | ok |
| bench/o1/live1/calls-live1-stale-repair_core-3de137948b1a.jsonl (line 2 call_end) | stale | repair_core | 1 | 3,265 | 2,660 | 603 | 773 | 446 | 4,038 | 327 | 1,092 | 2,173 | 11,000 | ok |
| bench/o1/live1/calls-live1-stale-repair_core-e6bf96abe284.jsonl (line 2 call_end) | stale | repair_core | 4 | 5,309 | 650 | 4,657 | 2,265 | 1,186 | 7,574 | 1,079 | 3,116 | 2,193 | 18,281 | ok |

### 6.2 step4-live1 (host-computable, not model-needed)

| locator | scenario | stage | members | input | cache write | cache read | output | thinking | denominator | visible out | packet in (est) | fixed in | in-flight ms | tags and outcome |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bench/step4/live1/calls-live1-clean-bounds-483cadf03a6e.jsonl (line 2 call_end) | clean | bounds | 4 | 2,550 | 1,945 | 603 | 101 | unknown | 2,651 | unknown | 373 | 2,177 | 6,828 | ok |
| bench/step4/live1/calls-live1-clean-classify-dcdace0917e7.jsonl (line 2 call_end) | clean | classify | 4 | 2,545 | 1,940 | 603 | 140 | unknown | 2,685 | unknown | 364 | 2,181 | 6,969 | ok |
| bench/step4/live1/calls-live1-clean-extract-5c8f8123fe4f.jsonl (line 2 call_end) | clean | extract | 4 | 2,542 | 2,540 | 0 | 171 | unknown | 2,713 | unknown | 365 | 2,177 | 7,297 | ok |
| bench/step4/live1/calls-live1-interrupt-bounds-483cadf03a6e.jsonl (line 2 call_end) | interrupt | bounds | 4 | 2,555 | 654 | 1,899 | 101 | unknown | 2,656 | unknown | 373 | 2,182 | 5,579 | ok |
| bench/step4/live1/calls-live1-interrupt-classify-dcdace0917e7.jsonl (line 2 call_end) | interrupt | classify | 4 | 2,546 | 654 | 1,890 | 61 | unknown | 2,607 | unknown | 364 | 2,182 | 6,734 | rejected-in-part check-driven ok |
| bench/step4/live1/calls-live1-interrupt-classify-dcdace0917e7.jsonl (line 4 call_end) | interrupt | classify | 1 | 2,368 | 1,763 | 603 | 72 | unknown | 2,440 | unknown | 186 | 2,182 | 6,969 | resent check-driven ok |
| bench/step4/live1/calls-live1-interrupt-classify-dcdace0917e7.jsonl (line 6 call_end) | interrupt | classify | 1 | 2,369 | 1,764 | 603 | 79 | unknown | 2,448 | unknown | 187 | 2,182 | 10,125 | resent check-driven ok |
| bench/step4/live1/calls-live1-interrupt-extract-5c8f8123fe4f.jsonl (line 1 call_start) | interrupt | extract | 4 | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown | no call_end (killed or unrecorded) |
| bench/step4/live1/calls-live1-stale-bounds-483cadf03a6e.jsonl (line 2 call_end) | stale | bounds | 4 | 2,552 | 651 | 1,899 | 101 | unknown | 2,653 | unknown | 373 | 2,179 | 6,703 | ok |
| bench/step4/live1/calls-live1-stale-bounds-5aebf77f0821.jsonl (line 2 call_end) | stale | bounds | 1 | 2,375 | 1,770 | 603 | 34 | unknown | 2,409 | unknown | 199 | 2,176 | 6,906 | ok |
| bench/step4/live1/calls-live1-stale-classify-bee726232b6b.jsonl (line 2 call_end) | stale | classify | 4 | 2,540 | 1,935 | 603 | 61 | unknown | 2,601 | unknown | 364 | 2,176 | 7,437 | rejected-in-part check-driven ok |
| bench/step4/live1/calls-live1-stale-classify-bee726232b6b.jsonl (line 4 call_end) | stale | classify | 1 | 2,370 | 654 | 1,714 | 83 | unknown | 2,453 | unknown | 187 | 2,183 | 7,531 | resent check-driven ok |
| bench/step4/live1/calls-live1-stale-extract-5c8f8123fe4f.jsonl (line 2 call_end) | stale | extract | 4 | 2,540 | 652 | 1,886 | 171 | unknown | 2,711 | unknown | 365 | 2,175 | 6,782 | ok |
| bench/step4/live1/calls-live1-stale-extract-5cb7ec8788f8.jsonl (line 2 call_end) | stale | extract | 1 | 2,361 | 1,756 | 603 | 49 | unknown | 2,410 | unknown | 192 | 2,169 | 6,125 | ok |

### 6.3 step4-live2 (host-computable, not model-needed)

| locator | scenario | stage | members | input | cache write | cache read | output | thinking | denominator | visible out | packet in (est) | fixed in | in-flight ms | tags and outcome |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bench/step4/live2/calls-live2-clean-bounds-483cadf03a6e.jsonl (line 2 call_end) | clean | bounds | 4 | 2,551 | 650 | 1,899 | 101 | 0 | 2,652 | 101 | 378 | 2,173 | 6,204 | ok |
| bench/step4/live2/calls-live2-clean-classify-dcdace0917e7.jsonl (line 2 call_end) | clean | classify | 4 | 2,543 | 651 | 1,890 | 140 | 79 | 2,683 | 61 | 369 | 2,174 | 6,843 | ok |
| bench/step4/live2/calls-live2-clean-extract-5c8f8123fe4f.jsonl (line 2 call_end) | clean | extract | 4 | 2,540 | 652 | 1,886 | 171 | 0 | 2,711 | 171 | 370 | 2,170 | 6,734 | ok |
| bench/step4/live2/calls-live2-interrupt-bounds-483cadf03a6e.jsonl (line 2 call_end) | interrupt | bounds | 4 | 2,559 | 658 | 1,899 | 101 | 0 | 2,660 | 101 | 378 | 2,181 | 6,953 | ok |
| bench/step4/live2/calls-live2-interrupt-classify-dcdace0917e7.jsonl (line 2 call_end) | interrupt | classify | 4 | 2,545 | 653 | 1,890 | 140 | 79 | 2,685 | 61 | 369 | 2,176 | 6,438 | ok |
| bench/step4/live2/calls-live2-interrupt-extract-5c8f8123fe4f.jsonl (line 1 call_start) | interrupt | extract | 4 | 2,543 | unknown | unknown | 171 | 0 | 2,714 | 171 | 370 | 2,173 | unknown | no call_end; capture recovered, no |
| bench/step4/live2/calls-live2-stale-bounds-483cadf03a6e.jsonl (line 2 call_end) | stale | bounds | 4 | 2,553 | 652 | 1,899 | 101 | 0 | 2,654 | 101 | 378 | 2,175 | 6,328 | ok |
| bench/step4/live2/calls-live2-stale-bounds-5aebf77f0821.jsonl (line 2 call_end) | stale | bounds | 1 | 2,377 | 655 | 1,720 | 34 | 0 | 2,411 | 34 | 202 | 2,175 | 7,297 | ok |
| bench/step4/live2/calls-live2-stale-classify-bee726232b6b.jsonl (line 2 call_end) | stale | classify | 4 | 2,543 | 651 | 1,890 | 61 | 0 | 2,604 | 61 | 369 | 2,174 | 7,047 | rejected-in-part check-driven ok |
| bench/step4/live2/calls-live2-stale-classify-bee726232b6b.jsonl (line 4 call_end) | stale | classify | 1 | 2,367 | 651 | 1,714 | 85 | 64 | 2,452 | 21 | 190 | 2,177 | 5,953 | resent check-driven ok |
| bench/step4/live2/calls-live2-stale-extract-5c8f8123fe4f.jsonl (line 2 call_end) | stale | extract | 4 | 2,540 | 652 | 1,886 | 171 | 0 | 2,711 | 171 | 370 | 2,170 | 7,359 | ok |
| bench/step4/live2/calls-live2-stale-extract-5cb7ec8788f8.jsonl (line 2 call_end) | stale | extract | 1 | 2,360 | 648 | 1,710 | 49 | 0 | 2,409 | 49 | 194 | 2,166 | 6,813 | ok |

### 6.4 step4-live3 (host-computable, not model-needed)

| locator | scenario | stage | members | input | cache write | cache read | output | thinking | denominator | visible out | packet in (est) | fixed in | in-flight ms | tags and outcome |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bench/step4/live3/calls-live3-clean-bounds-483cadf03a6e.jsonl (line 2 call_end) | clean | bounds | 4 | 2,552 | 1,947 | 603 | 101 | 0 | 2,653 | 101 | 378 | 2,174 | 6,610 | ok |
| bench/step4/live3/calls-live3-clean-classify-dcdace0917e7.jsonl (line 2 call_end) | clean | classify | 4 | 2,545 | 1,940 | 603 | 156 | 95 | 2,701 | 61 | 369 | 2,176 | 8,578 | ok |
| bench/step4/live3/calls-live3-clean-extract-5c8f8123fe4f.jsonl (line 2 call_end) | clean | extract | 4 | 2,542 | 2,540 | 0 | 171 | 0 | 2,713 | 171 | 370 | 2,172 | 7,046 | ok |
| bench/step4/live3/calls-live3-interrupt-bounds-483cadf03a6e.jsonl (line 2 call_end) | interrupt | bounds | 4 | 2,551 | 650 | 1,899 | 101 | 0 | 2,652 | 101 | 378 | 2,173 | 8,062 | ok |
| bench/step4/live3/calls-live3-interrupt-classify-dcdace0917e7.jsonl (line 2 call_end) | interrupt | classify | 4 | 2,543 | 651 | 1,890 | 148 | 87 | 2,691 | 61 | 369 | 2,174 | 6,891 | ok |
| bench/step4/live3/calls-live3-interrupt-extract-5c8f8123fe4f.jsonl (line 1 call_start) | interrupt | extract | 4 | 2,541 | unknown | unknown | 171 | 0 | 2,712 | 171 | 370 | 2,171 | unknown | no call_end; capture recovered, no |
| bench/step4/live3/calls-live3-stale-bounds-483cadf03a6e.jsonl (line 2 call_end) | stale | bounds | 4 | 2,552 | 651 | 1,899 | 101 | 0 | 2,653 | 101 | 378 | 2,174 | 7,610 | ok |
| bench/step4/live3/calls-live3-stale-bounds-5aebf77f0821.jsonl (line 2 call_end) | stale | bounds | 1 | 2,376 | 1,771 | 603 | 34 | 0 | 2,410 | 34 | 202 | 2,174 | 5,484 | ok |
| bench/step4/live3/calls-live3-stale-classify-bee726232b6b.jsonl (line 2 call_end) | stale | classify | 4 | 2,546 | 1,941 | 603 | 61 | 0 | 2,607 | 61 | 369 | 2,177 | 7,250 | rejected-in-part check-driven ok |
| bench/step4/live3/calls-live3-stale-classify-bee726232b6b.jsonl (line 4 call_end) | stale | classify | 1 | 2,370 | 1,765 | 603 | 21 | 0 | 2,391 | 21 | 190 | 2,180 | 7,281 | resent check-driven ok |
| bench/step4/live3/calls-live3-stale-extract-5c8f8123fe4f.jsonl (line 2 call_end) | stale | extract | 4 | 2,540 | 652 | 1,886 | 171 | 0 | 2,711 | 171 | 370 | 2,170 | 8,609 | ok |
| bench/step4/live3/calls-live3-stale-extract-5cb7ec8788f8.jsonl (line 2 call_end) | stale | extract | 1 | 2,366 | 1,761 | 603 | 49 | 0 | 2,415 | 49 | 194 | 2,172 | 6,859 | ok |

### 6.5 Control envelopes (boundary probe and adopt-qual, control stratum)

| locator | workload | arm | cell | cache write | cache read | output | thinking | denominator | wall ms | api ms | outcome |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bench/probe/boundary-evidence/calls/01-A/envelope.json | boundary-probe | A | block1 | 2,541 | 0 | 61 | 0 | 2,604 | 8,550 | 3,192 | failed |
| bench/probe/boundary-evidence/calls/02-B/envelope.json | boundary-probe | B | block1 | 1,986 | 603 | 163 | 102 | 2,754 | 8,429 | 3,967 | ok |
| bench/probe/boundary-evidence/calls/03-C/envelope.json | boundary-probe | C | block1 | 2,056 | 603 | 61 | 0 | 2,722 | 6,464 | 1,552 | ok |
| bench/probe/boundary-evidence/calls/04-B/envelope.json | boundary-probe | B | block2 | 653 | 1,930 | 151 | 90 | 2,736 | 6,765 | 2,878 | ok |
| bench/probe/boundary-evidence/calls/05-C/envelope.json | boundary-probe | C | block2 | 655 | 2,007 | 61 | 0 | 2,725 | 6,703 | 1,692 | ok |
| bench/probe/boundary-evidence/calls/06-A/envelope.json | boundary-probe | A | block2 | 654 | 1,890 | 61 | 0 | 2,607 | 6,402 | 2,047 | failed |
| bench/probe/boundary-evidence/calls/07-C/envelope.json | boundary-probe | C | block3 | 652 | 2,007 | 61 | 0 | 2,722 | 7,182 | 2,120 | ok |
| bench/probe/boundary-evidence/calls/08-A/envelope.json | boundary-probe | A | block3 | 654 | 1,890 | 61 | 0 | 2,607 | 6,866 | 2,040 | failed |
| bench/probe/boundary-evidence/calls/09-B/envelope.json | boundary-probe | B | block3 | 654 | 1,930 | 185 | 124 | 2,771 | 13,423 | 9,730 | ok |
| bench/probe/boundary-evidence/calls/10-A/envelope.json | boundary-probe | A | block4 | 652 | 1,890 | 125 | 0 | 2,669 | 8,495 | 4,485 | failed |
| bench/probe/boundary-evidence/calls/11-C/envelope.json | boundary-probe | C | block4 | 653 | 2,007 | 61 | 0 | 2,723 | 5,546 | 1,569 | ok |
| bench/probe/boundary-evidence/calls/12-B/envelope.json | boundary-probe | B | block4 | 649 | 1,930 | 178 | 117 | 2,759 | 7,436 | 2,817 | ok |
| bench/probe/boundary-evidence/calls/13-C/envelope.json | boundary-probe | C | block5 | 650 | 2,007 | 61 | 0 | 2,720 | 6,240 | 1,498 | ok |
| bench/probe/boundary-evidence/calls/14-B/envelope.json | boundary-probe | B | block5 | 655 | 1,930 | 166 | 105 | 2,753 | 6,732 | 2,416 | ok |
| bench/probe/boundary-evidence/calls/15-A/envelope.json | boundary-probe | A | block5 | 649 | 1,890 | 61 | 0 | 2,602 | 6,390 | 1,869 | failed |
| bench/probe/boundary-evidence/calls/16-B/envelope.json | boundary-probe | B | block6 | 651 | 1,930 | 193 | 0 | 2,776 | 6,301 | 2,491 | failed |
| bench/probe/boundary-evidence/calls/17-A/envelope.json | boundary-probe | A | block6 | 654 | 1,890 | 61 | 0 | 2,607 | 7,305 | 1,966 | failed |
| bench/probe/boundary-evidence/calls/18-C/envelope.json | boundary-probe | C | block6 | 651 | 2,007 | 213 | 152 | 2,873 | 7,590 | 2,373 | ok |
| bench/step4/adopt-qual/calls/01-q4/envelope.json | adopt-qual | q4 | size4 | 2,680 | 0 | 175 | 114 | 2,857 | 6,509 | 1,856 | ok |
| bench/step4/adopt-qual/calls/02-q4/envelope.json | adopt-qual | q4 | size4 | 2,077 | 603 | 187 | 126 | 2,869 | 6,985 | 2,226 | ok |
| bench/step4/adopt-qual/calls/03-q4/envelope.json | adopt-qual | q4 | size4 | 2,092 | 603 | 203 | 143 | 2,900 | 7,380 | 2,376 | ok |
| bench/step4/adopt-qual/calls/04-q4/envelope.json | adopt-qual | q4 | size4 | 2,089 | 603 | 188 | 128 | 2,882 | 7,366 | 3,613 | ok |
| bench/step4/adopt-qual/calls/05-q4/envelope.json | adopt-qual | q4 | size4 | 2,074 | 603 | 182 | 121 | 2,861 | 12,354 | 6,846 | ok |
| bench/step4/adopt-qual/calls/06-q4/envelope.json | adopt-qual | q4 | size4 | 2,075 | 603 | 61 | 0 | 2,741 | 9,920 | 3,713 | ok |
| bench/step4/adopt-qual/calls/07-q4/envelope.json | adopt-qual | q4 | size4 | 2,095 | 603 | 196 | 136 | 2,896 | 8,626 | 4,453 | ok |
| bench/step4/adopt-qual/calls/08-q4/envelope.json | adopt-qual | q4 | size4 | 2,093 | 603 | 60 | 0 | 2,758 | 6,114 | 1,445 | ok |
| bench/step4/adopt-qual/calls/09-q4/envelope.json | adopt-qual | q4 | size4 | 2,076 | 603 | 61 | 0 | 2,742 | 8,984 | 3,777 | failed |

### 6.6 Caller-cost runs (pilot_k2): per-run breakdown

One row per run (caller transcript plus its worker ledger calls). Caller overhead is tagged only on delegating arms (K0, K1f, K1r); in arm J the caller does the work itself. This is a description of the stored runs, not a re-test of the settled same-model comparison.

| run | stratum | arm | jobs | worker calls | caller tokens | worker tokens | run denominator | caller share | caller thinking | wall ms | active ms | unresolved ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pilot_k2/A-reply-J-16-3005 | main | J | 16 | 0 | 5,193 | 0 | 5,193 | n/a (no delegation) | 343 | 11,560 | 7,427 | 4,133 |
| pilot_k2/A-reply-J-16-3006 | main | J | 16 | 0 | 5,101 | 0 | 5,101 | n/a (no delegation) | 245 | 9,310 | 5,032 | 4,278 |
| pilot_k2/A-reply-J-16-3007 | main | J | 16 | 0 | 5,140 | 0 | 5,140 | n/a (no delegation) | 292 | 8,940 | 5,081 | 3,859 |
| pilot_k2/A-reply-J-64-3105 | main | J | 64 | 0 | 10,713 | 0 | 10,713 | n/a (no delegation) | 596 | 17,750 | 12,743 | 5,007 |
| pilot_k2/A-reply-J-64-3106 | main | J | 64 | 0 | 10,892 | 0 | 10,892 | n/a (no delegation) | 765 | 19,270 | 13,395 | 5,875 |
| pilot_k2/A-reply-J-64-3107 | main | J | 64 | 0 | 10,771 | 0 | 10,771 | n/a (no delegation) | 597 | 17,840 | 13,565 | 4,275 |
| pilot_k2/A-reply-K0-64-3105 | main | K0 | 64 | 1 | 24,453 | 5,549 | 30,002 | 81.5% | 225 | 40,620 | 35,044 | 5,576 |
| pilot_k2/A-reply-K0-64-3106 | main | K0 | 64 | 1 | 37,397 | 5,521 | 42,918 | 87.1% | 289 | 43,980 | 36,860 | 7,120 |
| pilot_k2/A-reply-K0-64-3107 | main | K0 | 64 | 1 | 46,482 | 5,572 | 52,054 | 89.3% | 411 | 54,640 | 47,194 | 7,446 |
| pilot_k2/A-reply-K1f-64-3105 | main | K1f | 64 | 1 | 26,444 | 5,544 | 31,988 | 82.7% | 308 | 48,170 | 41,133 | 7,037 |
| pilot_k2/A-reply-K1f-64-3106 | main | K1f | 64 | 1 | 26,254 | 5,482 | 31,736 | 82.7% | 263 | 45,530 | 40,253 | 5,277 |
| pilot_k2/A-reply-K1f-64-3107 | main | K1f | 64 | 1 | 26,543 | 5,521 | 32,064 | 82.8% | 376 | 45,120 | 40,435 | 4,685 |
| pilot_k2/B-art-J-16-7001 | main | J | 16 | 0 | 14,986 | 0 | 14,986 | n/a (no delegation) | 176 | 15,380 | 9,510 | 5,870 |
| pilot_k2/B-art-J-16-7002 | main | J | 16 | 0 | 14,888 | 0 | 14,888 | n/a (no delegation) | 150 | 15,250 | 8,882 | 6,368 |
| pilot_k2/B-art-J-16-7003 | main | J | 16 | 0 | 15,092 | 0 | 15,092 | n/a (no delegation) | 226 | 13,700 | 8,608 | 5,092 |
| pilot_k2/B-art-J-64-7101 | main | J | 64 | 0 | 25,586 | 0 | 25,586 | n/a (no delegation) | 113 | 14,620 | 8,868 | 5,752 |
| pilot_k2/B-art-J-64-7102 | main | J | 64 | 0 | 47,572 | 0 | 47,572 | n/a (no delegation) | 132 | 734,500 | 15,193 | 719,307 |
| pilot_k2/B-art-J-64-7103 | main | J | 64 | 0 | 25,975 | 0 | 25,975 | n/a (no delegation) | 216 | 15,970 | 9,913 | 6,057 |
| pilot_k2/B-art-K1f-16-7001 | main | K1f | 16 | 1 | 11,673 | 3,204 | 14,877 | 78.5% | 0 | 22,910 | 17,429 | 5,481 |
| pilot_k2/B-art-K1f-16-7002 | main | K1f | 16 | 1 | 11,621 | 2,908 | 14,529 | 80.0% | 0 | 21,770 | 15,559 | 6,211 |
| pilot_k2/B-art-K1f-16-7003 | main | K1f | 16 | 1 | 11,626 | 3,083 | 14,709 | 79.0% | 0 | 21,700 | 16,219 | 5,481 |
| pilot_k2/B-art-K1f-64-7101 | main | K1f | 64 | 1 | 21,172 | 5,523 | 26,695 | 79.3% | 118 | 34,860 | 28,383 | 6,477 |
| pilot_k2/B-art-K1f-64-7102 | main | K1f | 64 | 1 | 21,224 | 5,772 | 26,996 | 78.6% | 128 | 36,000 | 29,397 | 6,603 |
| pilot_k2/B-art-K1f-64-7103 | main | K1f | 64 | 1 | 21,606 | 5,561 | 27,167 | 79.5% | 337 | 36,590 | 30,741 | 5,849 |
| pilot_k2/B-art-K1r-16-7001 | main | K1r | 16 | 1 | 17,477 | 2,984 | 20,461 | 85.4% | 33 | 23,110 | 16,893 | 6,217 |
| pilot_k2/B-art-K1r-16-7002 | main | K1r | 16 | 1 | 17,300 | 2,879 | 20,179 | 85.7% | 24 | 24,810 | 19,242 | 5,568 |
| pilot_k2/B-art-K1r-16-7003 | main | K1r | 16 | 1 | 17,285 | 2,965 | 20,250 | 85.4% | 0 | 23,560 | 17,605 | 5,955 |
| pilot_k2/B-art-K1r-64-7101 | main | K1r | 64 | 1 | 39,431 | 5,385 | 44,816 | 88.0% | 0 | 39,730 | 32,599 | 7,131 |
| pilot_k2/B-art-K1r-64-7102 | main | K1r | 64 | 1 | 39,387 | 5,572 | 44,959 | 87.6% | 204 | 40,000 | 33,223 | 6,777 |
| pilot_k2/B-art-K1r-64-7103 | main | K1r | 64 | 1 | 39,201 | 5,544 | 44,745 | 87.6% | 144 | 39,840 | 32,831 | 7,009 |
| pilot_k2/B-reply-J-16-7001 | main | J | 16 | 0 | 9,361 | 0 | 9,361 | n/a (no delegation) | 202 | 12,640 | 6,695 | 5,945 |
| pilot_k2/B-reply-J-16-7002 | main | J | 16 | 0 | 9,259 | 0 | 9,259 | n/a (no delegation) | 117 | 11,360 | 6,171 | 5,189 |
| pilot_k2/B-reply-J-16-7003 | main | J | 16 | 0 | 9,322 | 0 | 9,322 | n/a (no delegation) | 143 | 11,090 | 6,162 | 4,928 |
| pilot_k2/B-reply-J-64-7101 | main | J | 64 | 0 | 17,826 | 0 | 17,826 | n/a (no delegation) | 434 | 20,940 | 14,621 | 6,319 |
| pilot_k2/B-reply-J-64-7102 | main | J | 64 | 0 | 17,887 | 0 | 17,887 | n/a (no delegation) | 407 | 20,120 | 14,718 | 5,402 |
| pilot_k2/B-reply-J-64-7103 | main | J | 64 | 0 | 17,898 | 0 | 17,898 | n/a (no delegation) | 449 | 21,300 | 16,433 | 4,867 |
| pilot_k2/B-reply-K1f-16-7001 | main | K1f | 16 | 1 | 12,117 | 2,942 | 15,059 | 80.5% | 56 | 25,300 | 19,211 | 6,089 |
| pilot_k2/B-reply-K1f-16-7002 | main | K1f | 16 | 1 | 12,082 | 2,949 | 15,031 | 80.4% | 47 | 27,360 | 21,596 | 5,764 |
| pilot_k2/B-reply-K1f-16-7003 | main | K1f | 16 | 1 | 12,077 | 3,152 | 15,229 | 79.3% | 0 | 28,010 | 21,280 | 6,730 |
| pilot_k2/B-reply-K1f-64-7101 | main | K1f | 64 | 1 | 34,718 | 5,736 | 40,454 | 85.8% | 0 | 43,200 | 37,921 | 5,279 |
| pilot_k2/B-reply-K1f-64-7102 | main | K1f | 64 | 1 | 23,381 | 5,708 | 29,089 | 80.4% | 201 | 43,020 | 37,127 | 5,893 |
| pilot_k2/B-reply-K1f-64-7103 | main | K1f | 64 | 1 | 23,295 | 5,436 | 28,731 | 81.1% | 229 | 44,080 | 36,767 | 7,313 |
| pilot_k2/C-art-J-64-7201 | main | J | 64 | 0 | 35,374 | 0 | 35,374 | n/a (no delegation) | 190 | 16,230 | 11,020 | 5,210 |
| pilot_k2/C-art-J-64-7202 | main | J | 64 | 0 | 58,357 | 0 | 58,357 | n/a (no delegation) | 295 | 24,170 | 17,547 | 6,623 |
| pilot_k2/C-art-J-64-7203 | main | J | 64 | 0 | 36,311 | 0 | 36,311 | n/a (no delegation) | 152 | 17,750 | 11,188 | 6,562 |
| pilot_k2/C-art-K1r-64-7201 | main | K1r | 64 | 1 | 28,805 | 28,638 | 57,443 | 50.1% | 72 | 39,910 | 33,546 | 6,364 |
| pilot_k2/C-art-K1r-64-7202 | main | K1r | 64 | 1 | 36,018 | 28,694 | 64,712 | 55.7% | 63 | 39,410 | 31,711 | 7,699 |
| pilot_k2/C-art-K1r-64-7203 | main | K1r | 64 | 1 | 29,005 | 28,550 | 57,555 | 50.4% | 0 | 38,470 | 32,276 | 6,194 |
| pilot_k2_smoke/smoke-A-reply-K0-64-2999-20261023T014204 | smoke | K0 | 64 | 1 | 37,490 | 5,511 | 43,001 | 87.2% | 306 | 54,480 | 47,687 | 6,793 |
| pilot_k2_smoke/smoke-B-art-K1f-64-2999-20261023T014042 | smoke | K1f | 64 | 1 | 21,404 | 5,459 | 26,863 | 79.7% | 231 | 35,260 | 29,752 | 5,508 |
| pilot_k2_smoke/smoke-C-art-J-64-2999-20261023T014017 | smoke | J | 64 | 0 | 58,500 | 0 | 58,500 | n/a (no delegation) | 140 | 23,950 | 18,436 | 5,514 |
| pilot_k2_smoke/smoke-C-art-K1r-64-2999-20261023T014117 | smoke | K1r | 64 | 1 | 29,223 | 28,475 | 57,698 | 50.6% | 173 | 46,860 | 39,557 | 7,303 |

### 6.7 Ledger runs (step4 and O1): per-run breakdown

Failed or resent, check-driven and caller-overhead tokens are overlapping tags, never added to each other or to the categories. No ledger run has a caller.

| run | calls | calls without denominator | denominator | failed or resent tokens | check-driven tokens | span ms | active ms | unresolved ms | note |
|---|---|---|---|---|---|---|---|---|---|
| o1-live1:clean | 2 | 0 | 15,647 | 0 | 0 | 39,840 | 39,083 | 757 | span first start to last end; run end-to-end wall (incl. hos |
| o1-live1:interrupt | 2 | 0 | 16,048 | 0 | 0 | unknown | unknown | unknown | a call has no end timestamp: span unknown |
| o1-live1:stale | 4 | 0 | 23,718 | 0 | 0 | 61,808 | 58,408 | 3,400 | span first start to last end; run end-to-end wall (incl. hos |
| step4-live1:clean | 3 | 0 | 8,049 | 0 | 0 | 21,367 | 21,117 | 250 | span first start to last end; run end-to-end wall (incl. hos |
| step4-live1:interrupt | 5 | 1 | 10,151 | 7,495 | 7,495 | unknown | unknown | unknown | a call has no end timestamp: span unknown |
| step4-live1:stale | 6 | 0 | 15,237 | 5,054 | 5,054 | 42,214 | 41,482 | 732 | span first start to last end; run end-to-end wall (incl. hos |
| step4-live2:clean | 3 | 0 | 8,046 | 0 | 0 | 20,013 | 19,767 | 246 | span first start to last end; run end-to-end wall (incl. hos |
| step4-live2:interrupt | 3 | 0 | 8,059 | 0 | 0 | unknown | unknown | unknown | a call has no end timestamp: span unknown |
| step4-live2:stale | 6 | 0 | 15,241 | 5,056 | 5,056 | 41,608 | 40,831 | 777 | span first start to last end; run end-to-end wall (incl. hos |
| step4-live3:clean | 3 | 0 | 8,067 | 0 | 0 | 22,476 | 22,241 | 235 | span first start to last end; run end-to-end wall (incl. hos |
| step4-live3:interrupt | 3 | 0 | 8,055 | 0 | 0 | unknown | unknown | unknown | a call has no end timestamp: span unknown |
| step4-live3:stale | 6 | 0 | 15,187 | 4,998 | 4,998 | 43,725 | 43,057 | 668 | span first start to last end; run end-to-end wall (incl. hos |

## 7. Per-cell token and time breakdowns

A cell is workload, model, size (jobs per call), arm, scenario, stratum. Every cell is listed. Shares are of the cell's billed tokens; a value followed by `*` is partial (some call in the cell lacks the counter). `unknown` means no call has it. `fixed` and `packet` need a prompt-size estimate and a regression with R squared of at least 0.99 and at least 5 calls; otherwise the whole input is `unsplit`. Tags (failed or resent, check-driven, caller overhead) overlap the categories and each other and are never added.

| workload | model | jobs/call | arm | scenario | stratum | model-needed | calls | denominator | thinking | visible out | packet (est) | fixed (H+CLI) | input unsplit | failed or resent | check-driven | caller overhead |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| live22_1g_A_H | sonnet-5-5 | 64 | H | std | main | no | 20 | 111,368 | 16.3% | 23.7% | unknown | unknown | 60.0% | 0.0% | 0.0% | 0.0% |
| live22_1g_A_H | sonnet-5-5 | 64 | 0.8-exec | std | main | no | 5 | 46,935 | 8.6% | 21.2% | unknown | unknown | 70.2% | 0.0% | 0.0% | 0.0% |
| live23_1g_B_H | sonnet-5-5 | 64 | H | het | main | no | 5 | 28,905 | 19.3% | 20.3% | unknown | unknown | 60.4% | 0.0% | 0.0% | 0.0% |
| live24_1g_D_fable64 | fable-5-1 | 64 | H | std | main | no | 5 | 27,398 | 14.8% | 24.2% | unknown | unknown | 60.9% | 0.0% | 0.0% | 0.0% |
| live24_1g_D_fable_het | fable-5-1 | 64 | H | het | main | no | 5 | 29,254 | 19.4% | 21.0% | unknown | unknown | 59.6% | 0.0% | 0.0% | 0.0% |
| live24_1g_D_haiku64 | haiku-5-5 | 64 | H | std | main | no | 10 | 92,668 | 50.1% | 14.3% | unknown | unknown | 35.7% | 0.0% | 0.0% | 0.0% |
| live24_1g_D_haiku_het | haiku-5-5 | 64 | H | het | main | no | 5 | 52,869 | 56.0% | 11.3% | unknown | unknown | 32.7% | 0.0% | 0.0% | 0.0% |
| live24_1g_D_sonnet32 | sonnet-5-5 | 32 | H | std | main | no | 5 | 19,454 | 12.2% | 17.2% | unknown | unknown | 70.6% | 0.0% | 0.0% | 0.0% |
| live25_1g_R_haiku | haiku-5-5 | 64 | H | het | main | no | 4 | 38,829 | 52.6% | 11.7% | unknown | unknown | 35.7% | 0.0% | 0.0% | 0.0% |
| live25_1g_R_sonnet | sonnet-5-5 | 64 | H | het | main | no | 4 | 23,520 | 21.0% | 19.4% | unknown | unknown | 59.6% | 0.0% | 0.0% | 0.0% |
| live26_1g_R3_fable | fable-5-1 | 64 | H | het | main | no | 4 | 23,509 | 20.9% | 19.4% | unknown | unknown | 59.7% | 0.0% | 0.0% | 0.0% |
| live26_1g_R3_haiku | haiku-5-5 | 64 | H | het | main | no | 3 | 39,340 | 58.3% | 12.8% | unknown | unknown | 28.9% | 0.0% | 0.0% | 0.0% |
| live26_1g_R3_sonnet | sonnet-5-5 | 64 | H | het | main | no | 1 | 8,024 | 31.4% | 20.9% | unknown | unknown | 47.7% | 0.0% | 0.0% | 0.0% |
| live27_1g_opus_het | opus-5-5 | 64 | H | het | main | no | 5 | 28,060 | 15.5% | 21.1% | unknown | unknown | 63.4% | 0.0% | 0.0% | 0.0% |
| live27_1g_opus_std | opus-5-5 | 64 | 0.8-exec | std | main | no | 5 | 46,176 | 7.0% | 21.2% | unknown | unknown | 71.8% | 0.0% | 0.0% | 0.0% |
| live27_1g_opus_std | opus-5-5 | 64 | H | std | main | no | 5 | 26,423 | 10.8% | 25.2% | unknown | unknown | 64.0% | 0.0% | 0.0% | 0.0% |
| live28_1g_fable_paired | fable-5-1 | 64 | 0.8-exec | std | main | no | 5 | 46,822 | 8.2% | 21.0% | unknown | unknown | 70.9% | 0.0% | 0.0% | 0.0% |
| live28_1g_fable_paired | fable-5-1 | 64 | H | std | main | no | 5 | 27,811 | 15.2% | 24.0% | unknown | unknown | 60.8% | 0.0% | 0.0% | 0.0% |
| live29_1g_haiku_paired | haiku-5-5 | 64 | H | std | main | no | 5 | 45,473 | 48.7% | 14.5% | unknown | unknown | 36.8% | 0.0% | 0.0% | 0.0% |
| live29_1g_haiku_paired | haiku-5-5 | 64 | 0.8-exec | std | main | no | 5 | 65,700 | 35.1% | 14.7% | unknown | unknown | 50.2% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | haiku-5-5 | 16 | H | std | main | no | 3 | 13,070 | 32.0% | 7.8% | unknown | unknown | 60.3% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | haiku-5-5 | 16 | J | std | main | no | 3 | 14,442 | 27.5% | 10.2% | unknown | unknown | 62.3% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | haiku-5-5 | 1 | P | std | main | no | 48 | 107,608 | 14.2% | 2.8% | unknown | unknown | 83.0% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | haiku-5-5 | 16 | S | std | main | no | 3 | 371,229 | 4.3% | 5.4% | unknown | unknown | 90.3% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | opus-5-5 | 16 | H | std | main | no | 3 | 9,436 | 6.6% | 10.7% | unknown | unknown | 82.7% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | opus-5-5 | 16 | J | std | main | no | 3 | 11,193 | 7.2% | 13.2% | unknown | unknown | 79.6% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | opus-5-5 | 1 | P | std | main | no | 48 | 93,429 | 1.3% | 4.5% | unknown | unknown | 94.3% | 33.5% | 0.0% | 0.0% |
| pilot2-materials-1g | opus-5-5 | 16 | S | std | main | no | 3 | 395,855 | 0.5% | 5.0% | unknown | unknown | 94.5% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | sonnet-5-5 | 16 | S | std | smoke | no | 1 | 152,151 | 0.6% | 3.8% | unknown | unknown | 95.6% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | sonnet-5-5 | 16 | H | std | main | no | 3 | 9,626 | 7.6% | 10.5% | unknown | unknown | 81.9% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | sonnet-5-5 | 16 | J | std | main | no | 3 | 11,766 | 11.0% | 12.6% | unknown | unknown | 76.4% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | sonnet-5-5 | 1 | P | std | main | no | 240 | 488,910 | 1.5% | 4.2% | unknown | unknown | 94.3% | 5.3% | 0.0% | 0.0% |
| pilot2-materials-1g | sonnet-5-5 | 16 | S | std | main | no | 3 | 413,597 | 0.2% | 3.9% | unknown | unknown | 95.9% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | sonnet-5-5 | 64 | H | std | main | no | 3 | 17,591 | 16.3% | 22.6% | unknown | unknown | 61.1% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | sonnet-5-5 | 64 | J | std | main | no | 3 | 29,018 | 8.5% | 20.8% | unknown | unknown | 70.7% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | sonnet-5-5 | 64 | S | std | main | no | 3 | 1,491,032 | 0.5% | 4.4% | unknown | unknown | 95.0% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | haiku-5-5 | 1 | Q | std | main | no | 48 | 126,394 | 9.9% | 1.1% | unknown | unknown | 88.9% | 0.0% | 0.0% | 0.0% |
| pilot2-materials-1g | opus-5-5 | 1 | Q | std | main | no | 48 | 113,307 | 0.5% | 1.3% | unknown | unknown | 98.2% | 14.5% | 0.0% | 0.0% |
| pilot2-materials-1g | sonnet-5-5 | 1 | Q | std | main | no | 48 | 114,670 | 0.7% | 1.2% | unknown | unknown | 98.1% | 0.0% | 0.0% | 0.0% |
| pilot_k-pilot_k_smoke | sonnet-5-5 | 16 | K | n/a | smoke | no | 1 | 16,229 | unknown | unknown | unknown | unknown | 84.0% | 0.0% | 0.0% | 0.0% |
| pilot_k-pilot_k_sonnet16 | sonnet-5-5 | 16 | K | n/a | main | no | 3 | 48,059 | unknown | unknown | unknown | unknown | 84.4% | 0.0% | 0.0% | 0.0% |
| pilot_k-pilot_k_sonnet64 | sonnet-5-5 | 64 | K | n/a | main | no | 3 | 153,345 | unknown | unknown | unknown | unknown | 87.4% | 0.0% | 0.0% | 0.0% |
| pilot_k2-A-reply | sonnet-5-5 | 16 | J | n/a | main | no | 3 | 15,434 | 5.7% | 9.6% | unknown | unknown | 84.7% | 0.0% | 0.0% | 0.0% |
| pilot_k2-A-reply | sonnet-5-5 | 64 | J | n/a | main | no | 3 | 32,376 | 6.0% | 18.6% | unknown | unknown | 75.3% | 0.0% | 0.0% | 0.0% |
| pilot_k2-A-reply | sonnet-5-5 | 64 | K0 | n/a | main | no | 6 | 124,974 | 0.7%* | 8.5%* | unknown | unknown | 85.0% | 0.0% | 0.0% | 86.7% |
| pilot_k2-A-reply | sonnet-5-5 | 64 | K1f | n/a | main | no | 6 | 95,788 | 1.0%* | 12.8%* | unknown | unknown | 78.7% | 0.0% | 0.0% | 82.7% |
| pilot_k2-B-art | sonnet-5-5 | 16 | J | n/a | main | no | 3 | 44,966 | 1.2% | 4.8% | unknown | unknown | 94.0% | 0.0% | 0.0% | 0.0% |
| pilot_k2-B-art | sonnet-5-5 | 64 | J | n/a | main | no | 3 | 99,133 | 0.5% | 3.2% | unknown | unknown | 96.3% | 0.0% | 0.0% | 0.0% |
| pilot_k2-B-art | sonnet-5-5 | 16 | K1f | n/a | main | no | 6 | 44,115 | 0.0%* | 5.0%* | 4.0%* | 10.7%* | 74.2%* | 0.0% | 0.0% | 79.2% |
| pilot_k2-B-art | sonnet-5-5 | 64 | K1f | n/a | main | no | 6 | 80,858 | 0.7%* | 6.2%* | 5.9%* | 5.8%* | 72.3%* | 0.0% | 0.0% | 79.2% |
| pilot_k2-B-art | sonnet-5-5 | 16 | K1r | n/a | main | no | 6 | 60,890 | 0.1%* | 4.4%* | 2.9%* | 7.7%* | 81.0%* | 0.0% | 0.0% | 85.5% |
| pilot_k2-B-art | sonnet-5-5 | 64 | K1r | n/a | main | no | 6 | 134,520 | 0.3%* | 4.7%* | 3.5%* | 3.5%* | 82.8%* | 0.0% | 0.0% | 87.7% |
| pilot_k2-B-reply | sonnet-5-5 | 16 | J | n/a | main | no | 3 | 27,942 | 1.7% | 6.2% | unknown | unknown | 92.2% | 0.0% | 0.0% | 0.0% |
| pilot_k2-B-reply | sonnet-5-5 | 64 | J | n/a | main | no | 3 | 53,611 | 2.4% | 11.7% | unknown | unknown | 85.9% | 0.0% | 0.0% | 0.0% |
| pilot_k2-B-reply | sonnet-5-5 | 16 | K1f | n/a | main | no | 6 | 45,319 | 0.2%* | 7.9%* | 4.0%* | 10.4%* | 72.0%* | 0.0% | 0.0% | 80.0% |
| pilot_k2-B-reply | sonnet-5-5 | 64 | K1f | n/a | main | no | 6 | 98,274 | 0.4%* | 10.9%* | 4.9%* | 4.8%* | 71.5%* | 0.0% | 0.0% | 82.8% |
| pilot_k2-C-art | sonnet-5-5 | 64 | J | n/a | main | no | 3 | 130,042 | 0.5% | 2.8% | unknown | unknown | 96.7% | 0.0% | 0.0% | 0.0% |
| pilot_k2-C-art | sonnet-5-5 | 64 | K1r | n/a | main | no | 6 | 179,710 | 0.1%* | 2.7%* | unknown | unknown | 92.7% | 0.0% | 0.0% | 52.2% |
| pilot_k2-A-reply | sonnet-5-5 | 64 | K0 | n/a | smoke | no | 2 | 43,001 | 0.7%* | 7.8%* | unknown | unknown | 85.9% | 0.0% | 0.0% | 87.2% |
| pilot_k2-B-art | sonnet-5-5 | 64 | K1f | n/a | smoke | no | 2 | 26,863 | 0.9%* | 5.9%* | unknown | unknown | 84.6% | 0.0% | 0.0% | 79.7% |
| pilot_k2-C-art | sonnet-5-5 | 64 | J | n/a | smoke | no | 1 | 58,500 | 0.2% | 3.0% | unknown | unknown | 96.8% | 0.0% | 0.0% | 0.0% |
| pilot_k2-C-art | sonnet-5-5 | 64 | K1r | n/a | smoke | no | 2 | 57,698 | 0.3%* | 3.1%* | unknown | unknown | 92.1% | 0.0% | 0.0% | 50.6% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | 4 | repair_adapter | clean | main | yes | 1 | 8,535 | 10.6% | 11.3% | 52.4% | 25.7% | unknown | 0.0% | 0.0% | 0.0% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | 4 | * (all stages) | clean | main | yes | 2 | 15,647 | 10.1% | 13.4% | 48.5% | 28.0% | unknown | 0.0% | 0.0% | 0.0% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | 4 | repair_core | clean | main | yes | 1 | 7,112 | 9.5% | 15.9% | 43.8% | 30.9% | unknown | 0.0% | 0.0% | 0.0% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | 4 | repair_adapter | interrupt | main | yes | 1 | 8,479 | 10.1% | 11.8% | 52.3% | 25.8% | unknown | 0.0% | 0.0% | 0.0% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | 4 | * (all stages) | interrupt | main | yes | 2 | 16,048 | 12.6% | 13.0% | 47.1% | 27.3% | unknown | 0.0% | 0.0% | 0.0% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | 4 | repair_core | interrupt | main | yes | 1 | 7,569 | 15.5% | 14.3% | 41.2% | 29.0% | unknown | 0.0% | 0.0% | 0.0% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | 4 | repair_adapter | stale | main | yes | 1 | 8,193 | 7.1% | 12.1% | 54.1% | 26.6% | unknown | 0.0% | 0.0% | 0.0% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | 4 | * (all stages) | stale | main | yes | 2 | 15,767 | 11.2% | 13.2% | 47.9% | 27.7% | unknown | 0.0% | 0.0% | 0.0% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | 1 | repair_adapter | stale | main | yes | 1 | 3,913 | 3.4% | 3.3% | 37.1% | 56.2% | unknown | 0.0% | 0.0% | 0.0% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | 1 | * (all stages) | stale | main | yes | 2 | 7,951 | 7.3% | 5.8% | 32.0% | 55.0% | unknown | 0.0% | 0.0% | 0.0% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | 1 | repair_core | stale | main | yes | 1 | 4,038 | 11.0% | 8.1% | 27.0% | 53.8% | unknown | 0.0% | 0.0% | 0.0% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | 4 | repair_core | stale | main | yes | 1 | 7,574 | 15.7% | 14.2% | 41.1% | 29.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 4 | bounds | clean | main | no | 1 | 2,651 | unknown | unknown | 14.1% | 82.1% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 4 | * (all stages) | clean | main | no | 3 | 8,049 | unknown | unknown | 13.7% | 81.2% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 4 | classify | clean | main | no | 1 | 2,685 | unknown | unknown | 13.6% | 81.2% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 4 | extract | clean | main | no | 1 | 2,713 | unknown | unknown | 13.5% | 80.2% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 4 | bounds | interrupt | main | no | 1 | 2,656 | unknown | unknown | 14.0% | 82.2% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 4 | * (all stages) | interrupt | main | no | 3 | 5,263 | 0.0%* | 0.0%* | 14.0%* | 82.9%* | 0.0%* | 49.5%* | 49.5%* | 0.0%* |
| step4-inspection-handoff-20/live1 | unrecorded | 4 | classify | interrupt | main | no | 1 | 2,607 | unknown | unknown | 14.0% | 83.7% | unknown | 100.0% | 100.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 1 | classify | interrupt | main | no | 2 | 4,888 | unknown | unknown | 7.6% | 89.3% | unknown | 100.0% | 100.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 1 | * (all stages) | interrupt | main | no | 2 | 4,888 | unknown | unknown | 7.6% | 89.3% | unknown | 100.0% | 100.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 4 | extract | interrupt | main | no | 1 | 0 | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown |
| step4-inspection-handoff-20/live1 | unrecorded | 4 | bounds | stale | main | no | 1 | 2,653 | unknown | unknown | 14.1% | 82.1% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 4 | * (all stages) | stale | main | no | 3 | 7,965 | unknown | unknown | 13.8% | 82.0% | unknown | 32.7% | 32.7% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 1 | bounds | stale | main | no | 1 | 2,409 | unknown | unknown | 8.3% | 90.3% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 1 | * (all stages) | stale | main | no | 3 | 7,272 | unknown | unknown | 7.9% | 89.8% | unknown | 33.7% | 33.7% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 4 | classify | stale | main | no | 1 | 2,601 | unknown | unknown | 14.0% | 83.7% | unknown | 100.0% | 100.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 1 | classify | stale | main | no | 1 | 2,453 | unknown | unknown | 7.6% | 89.0% | unknown | 100.0% | 100.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 4 | extract | stale | main | no | 1 | 2,711 | unknown | unknown | 13.5% | 80.2% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live1 | unrecorded | 1 | extract | stale | main | no | 1 | 2,410 | unknown | unknown | 8.0% | 90.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 4 | bounds | clean | main | no | 1 | 2,652 | 0.0% | 3.8% | 14.2% | 82.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 4 | * (all stages) | clean | main | no | 3 | 8,046 | 1.0% | 4.1% | 13.9% | 81.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 4 | classify | clean | main | no | 1 | 2,683 | 2.9% | 2.3% | 13.7% | 81.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 4 | extract | clean | main | no | 1 | 2,711 | 0.0% | 6.3% | 13.6% | 80.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 4 | bounds | interrupt | main | no | 1 | 2,660 | 0.0% | 3.8% | 14.2% | 82.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 4 | * (all stages) | interrupt | main | no | 3 | 8,059 | 1.0% | 4.1% | 13.8% | 81.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 4 | classify | interrupt | main | no | 1 | 2,685 | 2.9% | 2.3% | 13.7% | 81.1% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 4 | extract | interrupt | main | no | 1 | 2,714 | 0.0% | 6.3% | 13.6% | 80.1% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 4 | bounds | stale | main | no | 1 | 2,654 | 0.0% | 3.8% | 14.2% | 82.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 4 | * (all stages) | stale | main | no | 3 | 7,969 | 0.0% | 4.2% | 14.0% | 81.8% | unknown | 32.7% | 32.7% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 1 | bounds | stale | main | no | 1 | 2,411 | 0.0% | 1.4% | 8.4% | 90.2% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 1 | * (all stages) | stale | main | no | 3 | 7,272 | 0.9% | 1.4% | 8.0% | 89.6% | unknown | 33.7% | 33.7% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 4 | classify | stale | main | no | 1 | 2,604 | 0.0% | 2.3% | 14.2% | 83.5% | unknown | 100.0% | 100.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 1 | classify | stale | main | no | 1 | 2,452 | 2.6% | 0.9% | 7.7% | 88.8% | unknown | 100.0% | 100.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 4 | extract | stale | main | no | 1 | 2,711 | 0.0% | 6.3% | 13.6% | 80.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | 1 | extract | stale | main | no | 1 | 2,409 | 0.0% | 2.0% | 8.1% | 89.9% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 4 | bounds | clean | main | no | 1 | 2,653 | 0.0% | 3.8% | 14.2% | 82.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 4 | * (all stages) | clean | main | no | 3 | 8,067 | 1.2% | 4.1% | 13.8% | 80.9% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 4 | classify | clean | main | no | 1 | 2,701 | 3.5% | 2.3% | 13.6% | 80.6% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 4 | extract | clean | main | no | 1 | 2,713 | 0.0% | 6.3% | 13.6% | 80.1% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 4 | bounds | interrupt | main | no | 1 | 2,652 | 0.0% | 3.8% | 14.2% | 82.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 4 | * (all stages) | interrupt | main | no | 3 | 8,055 | 1.1% | 4.1% | 13.9% | 80.9% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 4 | classify | interrupt | main | no | 1 | 2,691 | 3.2% | 2.3% | 13.7% | 80.8% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 4 | extract | interrupt | main | no | 1 | 2,712 | 0.0% | 6.3% | 13.6% | 80.1% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 4 | bounds | stale | main | no | 1 | 2,653 | 0.0% | 3.8% | 14.2% | 82.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 4 | * (all stages) | stale | main | no | 3 | 7,971 | 0.0% | 4.2% | 14.0% | 81.8% | unknown | 32.7% | 32.7% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 1 | bounds | stale | main | no | 1 | 2,410 | 0.0% | 1.4% | 8.4% | 90.2% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 1 | * (all stages) | stale | main | no | 3 | 7,216 | 0.0% | 1.4% | 8.1% | 90.5% | unknown | 33.1% | 33.1% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 4 | classify | stale | main | no | 1 | 2,607 | 0.0% | 2.3% | 14.1% | 83.5% | unknown | 100.0% | 100.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 1 | classify | stale | main | no | 1 | 2,391 | 0.0% | 0.9% | 7.9% | 91.2% | unknown | 100.0% | 100.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 4 | extract | stale | main | no | 1 | 2,711 | 0.0% | 6.3% | 13.6% | 80.0% | unknown | 0.0% | 0.0% | 0.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | 1 | extract | stale | main | no | 1 | 2,415 | 0.0% | 2.0% | 8.0% | 89.9% | unknown | 0.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | A | block1 | control | no | 1 | 2,604 | 0.0% | 2.3% | unknown | unknown | 97.7% | 100.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | B | block1 | control | no | 1 | 2,754 | 3.7% | 2.2% | unknown | unknown | 94.1% | 0.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | C | block1 | control | no | 1 | 2,722 | 0.0% | 2.2% | unknown | unknown | 97.8% | 0.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | B | block2 | control | no | 1 | 2,736 | 3.3% | 2.2% | unknown | unknown | 94.5% | 0.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | C | block2 | control | no | 1 | 2,725 | 0.0% | 2.2% | unknown | unknown | 97.8% | 0.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | A | block2 | control | no | 1 | 2,607 | 0.0% | 2.3% | unknown | unknown | 97.7% | 100.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | C | block3 | control | no | 1 | 2,722 | 0.0% | 2.2% | unknown | unknown | 97.8% | 0.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | A | block3 | control | no | 1 | 2,607 | 0.0% | 2.3% | unknown | unknown | 97.7% | 100.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | B | block3 | control | no | 1 | 2,771 | 4.5% | 2.2% | unknown | unknown | 93.3% | 0.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | A | block4 | control | no | 1 | 2,669 | 0.0% | 4.7% | unknown | unknown | 95.3% | 100.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | C | block4 | control | no | 1 | 2,723 | 0.0% | 2.2% | unknown | unknown | 97.8% | 0.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | B | block4 | control | no | 1 | 2,759 | 4.2% | 2.2% | unknown | unknown | 93.5% | 0.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | C | block5 | control | no | 1 | 2,720 | 0.0% | 2.2% | unknown | unknown | 97.8% | 0.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | B | block5 | control | no | 1 | 2,753 | 3.8% | 2.2% | unknown | unknown | 94.0% | 0.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | A | block5 | control | no | 1 | 2,602 | 0.0% | 2.3% | unknown | unknown | 97.7% | 100.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | B | block6 | control | no | 1 | 2,776 | 0.0% | 7.0% | unknown | unknown | 93.0% | 100.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | A | block6 | control | no | 1 | 2,607 | 0.0% | 2.3% | unknown | unknown | 97.7% | 100.0% | 0.0% | 0.0% |
| boundary-probe | sonnet-5-5 | 4 | C | block6 | control | no | 1 | 2,873 | 5.3% | 2.1% | unknown | unknown | 92.6% | 0.0% | 0.0% | 0.0% |
| adopt-qual | sonnet-5-5 | 4 | q4 | size4 | control | no | 9 | 25,506 | 3.0% | 2.1% | unknown | unknown | 94.9% | 10.8% | 0.0% | 0.0% |

### 7.1 Time partition

End-to-end wall is partitioned into active critical-path work, avoidable waiting and unresolved time, per run, then summed per cell without summing overlapping calls. Active = model API time plus measured pre-request harness time for single-process runs; for ledger runs the union of call in-flight intervals; for caller runs the caller's API and pre-request time plus the union of its nested worker calls. Avoidable waiting = measured queue or proven avoidable idle time. No source records one: queued turns nonzero in 0 records, rate-limit events by status {'allowed': 53}, so it is 0 ms demonstrated everywhere. Unresolved = wall minus active: process start and exit, CLI internals, host work and gaps between calls, none of which any source attributes. Ledger runs have no end-to-end wall in the corpus (the run report holds only the whole live run), so their wall is the span from the first call start to the last call end and host work outside that span is not in it. Runs missing a timestamp or API split are counted in `runs unknown` and excluded from the sums.

| workload | model | jobs/call | arm | scenario | stratum | runs | runs unknown | wall s (known runs) | active | avoidable waiting | unresolved |
|---|---|---|---|---|---|---|---|---|---|---|---|
| live22_1g_A_H | sonnet-5-5 | 64 | H | std | main | 20 | 0 | 337.0 | 75.5% | 0.0% | 24.5% |
| live22_1g_A_H | sonnet-5-5 | 64 | 0.8-exec | std | main | 5 | 0 | 91.5 | 75.7% | 0.0% | 24.3% |
| live23_1g_B_H | sonnet-5-5 | 64 | H | het | main | 5 | 0 | 79.6 | 79.6% | 0.0% | 20.4% |
| live24_1g_D_fable64 | fable-5-1 | 64 | H | std | main | 5 | 0 | 117.0 | 85.1% | 0.0% | 14.9% |
| live24_1g_D_fable_het | fable-5-1 | 64 | H | het | main | 5 | 0 | 132.1 | 88.0% | 0.0% | 12.0% |
| live24_1g_D_haiku64 | haiku-5-5 | 64 | H | std | main | 10 | 0 | 226.9 | 85.3% | 0.0% | 14.7% |
| live24_1g_D_haiku_het | haiku-5-5 | 64 | H | het | main | 5 | 0 | 131.6 | 87.6% | 0.0% | 12.4% |
| live24_1g_D_sonnet32 | sonnet-5-5 | 32 | H | std | main | 5 | 0 | 53.8 | 66.3% | 0.0% | 33.7% |
| live25_1g_R_haiku | haiku-5-5 | 64 | H | het | main | 4 | 0 | 91.6 | 85.7% | 0.0% | 14.3% |
| live25_1g_R_sonnet | sonnet-5-5 | 64 | H | het | main | 4 | 0 | 62.6 | 81.0% | 0.0% | 19.0% |
| live26_1g_R3_fable | fable-5-1 | 64 | H | het | main | 4 | 0 | 97.3 | 85.6% | 0.0% | 14.4% |
| live26_1g_R3_haiku | haiku-5-5 | 64 | H | het | main | 3 | 0 | 95.3 | 89.0% | 0.0% | 11.0% |
| live26_1g_R3_sonnet | sonnet-5-5 | 64 | H | het | main | 1 | 0 | 25.0 | 80.4% | 0.0% | 19.6% |
| live27_1g_opus_het | opus-5-5 | 64 | H | het | main | 5 | 0 | 91.6 | 82.0% | 0.0% | 18.0% |
| live27_1g_opus_std | opus-5-5 | 64 | 0.8-exec | std | main | 5 | 0 | 108.9 | 83.5% | 0.0% | 16.5% |
| live27_1g_opus_std | opus-5-5 | 64 | H | std | main | 5 | 0 | 86.6 | 80.1% | 0.0% | 19.9% |
| live28_1g_fable_paired | fable-5-1 | 64 | 0.8-exec | std | main | 5 | 0 | 135.7 | 88.7% | 0.0% | 11.3% |
| live28_1g_fable_paired | fable-5-1 | 64 | H | std | main | 5 | 0 | 119.4 | 84.2% | 0.0% | 15.8% |
| live29_1g_haiku_paired | haiku-5-5 | 64 | H | std | main | 5 | 0 | 111.7 | 83.9% | 0.0% | 16.1% |
| live29_1g_haiku_paired | haiku-5-5 | 64 | 0.8-exec | std | main | 5 | 0 | 119.4 | 85.9% | 0.0% | 14.1% |
| pilot2-materials-1g | haiku-5-5 | 16 | H | std | main | 3 | 0 | 37.7 | 60.7% | 0.0% | 39.3% |
| pilot2-materials-1g | haiku-5-5 | 16 | J | std | main | 3 | 0 | 36.9 | 61.8% | 0.0% | 38.2% |
| pilot2-materials-1g | haiku-5-5 | 1 | P | std | main | 48 | 0 | 344.8 | 34.5% | 0.0% | 65.5% |
| pilot2-materials-1g | haiku-5-5 | 16 | S | std | main | 3 | 0 | 99.8 | 100.0% | 0.0% | 0.0% |
| pilot2-materials-1g | opus-5-5 | 16 | H | std | main | 3 | 0 | 28.5 | 52.1% | 0.0% | 47.9% |
| pilot2-materials-1g | opus-5-5 | 16 | J | std | main | 3 | 0 | 34.0 | 59.4% | 0.0% | 40.6% |
| pilot2-materials-1g | opus-5-5 | 1 | P | std | main | 48 | 0 | 342.9 | 34.5% | 0.0% | 65.5% |
| pilot2-materials-1g | opus-5-5 | 16 | S | std | main | 3 | 0 | 151.7 | 100.0% | 0.0% | 0.0% |
| pilot2-materials-1g | sonnet-5-5 | 16 | S | std | smoke | 1 | 0 | 46.2 | 100.0% | 0.0% | 0.0% |
| pilot2-materials-1g | sonnet-5-5 | 16 | H | std | main | 3 | 0 | 36.7 | 59.5% | 0.0% | 40.5% |
| pilot2-materials-1g | sonnet-5-5 | 16 | J | std | main | 3 | 0 | 31.4 | 53.7% | 0.0% | 46.3% |
| pilot2-materials-1g | sonnet-5-5 | 1 | P | std | main | 240 | 0 | 1,873.5 | 39.2% | 0.0% | 60.8% |
| pilot2-materials-1g | sonnet-5-5 | 16 | S | std | main | 3 | 0 | 118.5 | 100.0% | 0.0% | 0.0% |
| pilot2-materials-1g | sonnet-5-5 | 64 | H | std | main | 3 | 0 | 59.7 | 74.1% | 0.0% | 25.9% |
| pilot2-materials-1g | sonnet-5-5 | 64 | J | std | main | 3 | 0 | 64.2 | 70.9% | 0.0% | 29.1% |
| pilot2-materials-1g | sonnet-5-5 | 64 | S | std | main | 3 | 0 | 321.4 | 100.0% | 0.0% | 0.0% |
| pilot2-materials-1g | haiku-5-5 | 1 | Q | std | main | 48 | 0 | 351.3 | 32.4% | 0.0% | 67.6% |
| pilot2-materials-1g | opus-5-5 | 1 | Q | std | main | 48 | 0 | 327.8 | 31.1% | 0.0% | 68.9% |
| pilot2-materials-1g | sonnet-5-5 | 1 | Q | std | main | 48 | 0 | 346.7 | 33.3% | 0.0% | 66.7% |
| pilot_k-pilot_k_smoke | sonnet-5-5 | 16 | K | n/a | smoke | 1 | 1 | unknown | unknown | unknown | unknown |
| pilot_k-pilot_k_sonnet16 | sonnet-5-5 | 16 | K | n/a | main | 3 | 3 | unknown | unknown | unknown | unknown |
| pilot_k-pilot_k_sonnet64 | sonnet-5-5 | 64 | K | n/a | main | 3 | 3 | unknown | unknown | unknown | unknown |
| pilot_k2-A-reply | sonnet-5-5 | 16 | J | n/a | main | 3 | 0 | 29.8 | 58.8% | 0.0% | 41.2% |
| pilot_k2-A-reply | sonnet-5-5 | 64 | J | n/a | main | 3 | 0 | 54.9 | 72.4% | 0.0% | 27.6% |
| pilot_k2-A-reply | sonnet-5-5 | 64 | K0 | n/a | main | 3 | 0 | 139.2 | 85.5% | 0.0% | 14.5% |
| pilot_k2-A-reply | sonnet-5-5 | 64 | K1f | n/a | main | 3 | 0 | 138.8 | 87.8% | 0.0% | 12.2% |
| pilot_k2-B-art | sonnet-5-5 | 16 | J | n/a | main | 3 | 0 | 44.3 | 60.9% | 0.0% | 39.1% |
| pilot_k2-B-art | sonnet-5-5 | 64 | J | n/a | main | 3 | 0 | 765.1 | 4.4% | 0.0% | 95.6% |
| pilot_k2-B-art | sonnet-5-5 | 16 | K1f | n/a | main | 3 | 0 | 66.4 | 74.1% | 0.0% | 25.9% |
| pilot_k2-B-art | sonnet-5-5 | 64 | K1f | n/a | main | 3 | 0 | 107.5 | 82.4% | 0.0% | 17.6% |
| pilot_k2-B-art | sonnet-5-5 | 16 | K1r | n/a | main | 3 | 0 | 71.5 | 75.2% | 0.0% | 24.8% |
| pilot_k2-B-art | sonnet-5-5 | 64 | K1r | n/a | main | 3 | 0 | 119.6 | 82.5% | 0.0% | 17.5% |
| pilot_k2-B-reply | sonnet-5-5 | 16 | J | n/a | main | 3 | 0 | 35.1 | 54.2% | 0.0% | 45.8% |
| pilot_k2-B-reply | sonnet-5-5 | 64 | J | n/a | main | 3 | 0 | 62.4 | 73.4% | 0.0% | 26.6% |
| pilot_k2-B-reply | sonnet-5-5 | 16 | K1f | n/a | main | 3 | 0 | 80.7 | 77.0% | 0.0% | 23.0% |
| pilot_k2-B-reply | sonnet-5-5 | 64 | K1f | n/a | main | 3 | 0 | 130.3 | 85.8% | 0.0% | 14.2% |
| pilot_k2-C-art | sonnet-5-5 | 64 | J | n/a | main | 3 | 0 | 58.1 | 68.4% | 0.0% | 31.6% |
| pilot_k2-C-art | sonnet-5-5 | 64 | K1r | n/a | main | 3 | 0 | 117.8 | 82.8% | 0.0% | 17.2% |
| pilot_k2-A-reply | sonnet-5-5 | 64 | K0 | n/a | smoke | 1 | 0 | 54.5 | 87.5% | 0.0% | 12.5% |
| pilot_k2-B-art | sonnet-5-5 | 64 | K1f | n/a | smoke | 1 | 0 | 35.3 | 84.4% | 0.0% | 15.6% |
| pilot_k2-C-art | sonnet-5-5 | 64 | J | n/a | smoke | 1 | 0 | 23.9 | 77.0% | 0.0% | 23.0% |
| pilot_k2-C-art | sonnet-5-5 | 64 | K1r | n/a | smoke | 1 | 0 | 46.9 | 84.4% | 0.0% | 15.6% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | run | all stages | clean | main | 1 | 0 | 39.8 | 98.1% | 0.0% | 1.9% |
| o1-repair-handoff-20/live1 | sonnet-5-5 | run | all stages | interrupt | main | 1 | 1 | unknown | unknown | unknown | unknown |
| o1-repair-handoff-20/live1 | sonnet-5-5 | run | all stages | stale | main | 1 | 0 | 61.8 | 94.5% | 0.0% | 5.5% |
| step4-inspection-handoff-20/live1 | unrecorded | run | all stages | clean | main | 1 | 0 | 21.4 | 98.8% | 0.0% | 1.2% |
| step4-inspection-handoff-20/live1 | unrecorded | run | all stages | interrupt | main | 1 | 1 | unknown | unknown | unknown | unknown |
| step4-inspection-handoff-20/live1 | unrecorded | run | all stages | stale | main | 1 | 0 | 42.2 | 98.3% | 0.0% | 1.7% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | run | all stages | clean | main | 1 | 0 | 20.0 | 98.8% | 0.0% | 1.2% |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | run | all stages | interrupt | main | 1 | 1 | unknown | unknown | unknown | unknown |
| step4-inspection-handoff-20/live2 | sonnet-5-5 | run | all stages | stale | main | 1 | 0 | 41.6 | 98.1% | 0.0% | 1.9% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | run | all stages | clean | main | 1 | 0 | 22.5 | 99.0% | 0.0% | 1.0% |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | run | all stages | interrupt | main | 1 | 1 | unknown | unknown | unknown | unknown |
| step4-inspection-handoff-20/live3 | sonnet-5-5 | run | all stages | stale | main | 1 | 0 | 43.7 | 98.5% | 0.0% | 1.5% |
| boundary-probe | sonnet-5-5 | 4 | A | block1 | control | 1 | 0 | 8.6 | 43.6% | 0.0% | 56.4% |
| boundary-probe | sonnet-5-5 | 4 | B | block1 | control | 1 | 0 | 8.4 | 47.8% | 0.0% | 52.2% |
| boundary-probe | sonnet-5-5 | 4 | C | block1 | control | 1 | 0 | 6.5 | 25.0% | 0.0% | 75.0% |
| boundary-probe | sonnet-5-5 | 4 | B | block2 | control | 1 | 0 | 6.8 | 43.5% | 0.0% | 56.5% |
| boundary-probe | sonnet-5-5 | 4 | C | block2 | control | 1 | 0 | 6.7 | 26.2% | 0.0% | 73.8% |
| boundary-probe | sonnet-5-5 | 4 | A | block2 | control | 1 | 0 | 6.4 | 33.0% | 0.0% | 67.0% |
| boundary-probe | sonnet-5-5 | 4 | C | block3 | control | 1 | 0 | 7.2 | 30.4% | 0.0% | 69.6% |
| boundary-probe | sonnet-5-5 | 4 | A | block3 | control | 1 | 0 | 6.9 | 30.6% | 0.0% | 69.4% |
| boundary-probe | sonnet-5-5 | 4 | B | block3 | control | 1 | 0 | 13.4 | 73.0% | 0.0% | 27.0% |
| boundary-probe | sonnet-5-5 | 4 | A | block4 | control | 1 | 0 | 8.5 | 53.5% | 0.0% | 46.5% |
| boundary-probe | sonnet-5-5 | 4 | C | block4 | control | 1 | 0 | 5.5 | 29.5% | 0.0% | 70.5% |
| boundary-probe | sonnet-5-5 | 4 | B | block4 | control | 1 | 0 | 7.4 | 38.8% | 0.0% | 61.2% |
| boundary-probe | sonnet-5-5 | 4 | C | block5 | control | 1 | 0 | 6.2 | 25.0% | 0.0% | 75.0% |
| boundary-probe | sonnet-5-5 | 4 | B | block5 | control | 1 | 0 | 6.7 | 36.8% | 0.0% | 63.2% |
| boundary-probe | sonnet-5-5 | 4 | A | block5 | control | 1 | 0 | 6.4 | 30.3% | 0.0% | 69.7% |
| boundary-probe | sonnet-5-5 | 4 | B | block6 | control | 1 | 0 | 6.3 | 40.6% | 0.0% | 59.4% |
| boundary-probe | sonnet-5-5 | 4 | A | block6 | control | 1 | 0 | 7.3 | 27.7% | 0.0% | 72.3% |
| boundary-probe | sonnet-5-5 | 4 | C | block6 | control | 1 | 0 | 7.6 | 32.1% | 0.0% | 67.9% |
| adopt-qual | sonnet-5-5 | 4 | q4 | size4 | control | 9 | 0 | 74.2 | 41.5% | 0.0% | 58.5% |

42 of 93 time cells have unresolved time at or above 25% of wall. It is unattributed by construction, so it cannot qualify. None of the O1 time cells reach it (1.9%, 5.5% unresolved; the interrupt run has no end timestamp for its killed call).

Outlier kept in the sums: `bench/live/data/pilot_k2/B-art-J-64-7102/transcript.jsonl` (line 31 result.modelUsage), wall 734.5 s against 15.2 s of API time; 2 result events (modelUsage is cumulative, the last is used); largest gap between recorded events 596 s. It is unresolved time with no recorded cause and it alone takes its cell's unresolved share to 95.6%.

## 8. Host-computable scan

Every model operation in the corpus workloads, with its checks. A flag means a check recomputes the operation's full answer from the same input, so the host can produce the answer without a model call and the model call only costs tokens.

| scope | model op | model nodes in graph | checks | flag: check recomputes the full answer | why | locator |
|---|---|---|---|---|---|---|
| step4/inspection-handoff-20-v1 | model.extract@1 | 4 | mat_fields | FLAGGED | mat_fields: v == [r[f] for f in FIELDS]: the answer is a pure function of the ref text | bench/step4/inspection-handoff-20-v1/workflow.json model_ops; check at bench/step4/workflow.py:158 |
| step4/inspection-handoff-20-v1 | model.bounds@1 | 4 | mat_bounds | FLAGGED | mat_bounds: v == bounds_of(r): Decimal arithmetic on the ref | bench/step4/inspection-handoff-20-v1/workflow.json model_ops; check at bench/step4/workflow.py:160 |
| step4/inspection-handoff-20-v1 | model.classify@1 | 4 | mat_classify | FLAGGED | mat_classify: v == status_of(bounds_of(r)): Decimal arithmetic on the ref | bench/step4/inspection-handoff-20-v1/workflow.json model_ops; check at bench/step4/workflow.py:161 |
| step4/inspection-handoff-20-v2 | model.extract@1 | 4 | mat_fields | FLAGGED | mat_fields: v == [r[f] for f in FIELDS]: the answer is a pure function of the ref text | bench/step4/inspection-handoff-20-v2/workflow.json model_ops; check at bench/step4/workflow.py:158 |
| step4/inspection-handoff-20-v2 | model.bounds@1 | 4 | mat_bounds | FLAGGED | mat_bounds: v == bounds_of(r): Decimal arithmetic on the ref | bench/step4/inspection-handoff-20-v2/workflow.json model_ops; check at bench/step4/workflow.py:160 |
| step4/inspection-handoff-20-v2 | model.classify@2 | 4 | mat_classify_interval | FLAGGED | mat_classify_interval: interval recomputed from the record and label from the goal limits | bench/step4/inspection-handoff-20-v2/workflow.json model_ops; check at bench/step4/workflow.py:162 |
| step4/inspection-handoff-20-v3 | model.extract@1 | 4 | mat_fields | FLAGGED | mat_fields: v == [r[f] for f in FIELDS]: the answer is a pure function of the ref text | bench/step4/inspection-handoff-20-v3/workflow.json model_ops; check at bench/step4/workflow.py:158 |
| step4/inspection-handoff-20-v3 | model.bounds@1 | 4 | mat_bounds | FLAGGED | mat_bounds: v == bounds_of(r): Decimal arithmetic on the ref | bench/step4/inspection-handoff-20-v3/workflow.json model_ops; check at bench/step4/workflow.py:160 |
| step4/inspection-handoff-20-v3 | host.classify | 4 | (host op) | no | already a host operation (v3): no model call | bench/step4/inspection-handoff-20-v3/graph.json |
| o1/repair-handoff-20-v1 | model.repair_core@1 | 4 | json_type, o1_source, o1_policy, o1_tier_a | no | no check recomputes the answer: json_type: structural type test; o1_source: byte-length test of the candidate source; o1_policy: AST policy test of the candidate; does not produce the answer; o1_tier_a: runs the candidate against executable expected rows; the host can judge code but not write it | bench/o1/repair-handoff-20-v1/workflow.json model_ops; check at oz_accept registry |
| o1/repair-handoff-20-v1 | model.repair_adapter@1 | 4 | json_type, o1_source, o1_policy, o1_tier_a | no | no check recomputes the answer: json_type: structural type test; o1_source: byte-length test of the candidate source; o1_policy: AST policy test of the candidate; does not produce the answer; o1_tier_a: runs the candidate against executable expected rows; the host can judge code but not write it | bench/o1/repair-handoff-20-v1/workflow.json model_ops; check at oz_accept registry |
| pilot/1g materials jobs (pilot2, pilot2q, live22-29 H and 0.8-exec arms, pilot_k2 blocks A-C) | materials.e (extract six fields) | n/a | live6.check oracle (strict compare to expected) | FLAGGED | the oracle compares to the value the host derives from the ref text; the job is exactly computable | bench/live/live2.py:31 (MAT_D), oracle bench/live/live6.py:45 |
| pilot/1g materials jobs (pilot2, pilot2q, live22-29 H and 0.8-exec arms, pilot_k2 blocks A-C) | materials.b (interval bounds) | n/a | live6.check oracle (strict compare to expected) | FLAGGED | the oracle compares to the value the host derives from the ref text; the job is exactly computable | bench/live/live2.py:31 (MAT_D), oracle bench/live/live6.py:45 |
| pilot/1g materials jobs (pilot2, pilot2q, live22-29 H and 0.8-exec arms, pilot_k2 blocks A-C) | materials.m (missing field names) | n/a | live6.check oracle (strict compare to expected) | FLAGGED | the oracle compares to the value the host derives from the ref text; the job is exactly computable | bench/live/live2.py:31 (MAT_D), oracle bench/live/live6.py:45 |
| pilot/1g materials jobs (pilot2, pilot2q, live22-29 H and 0.8-exec arms, pilot_k2 blocks A-C) | materials.v (inside/outside/unknown) | n/a | live6.check oracle (strict compare to expected) | FLAGGED | the oracle compares to the value the host derives from the ref text; the job is exactly computable | bench/live/live2.py:31 (MAT_D), oracle bench/live/live6.py:45 |
| live23-live29 heterogeneous 64-job packets | hetero1g families P1-P5 | n/a | judge() against expected | FLAGGED | module docstring: each expected result follows from the op text and the refs alone, no judgment | bench/live/hetero1g.py:1-5 |
| boundary-probe and adopt-qual (classification arms A, B, C, q4) | classify | n/a | mat_classify / member-wise compare | FLAGGED | classification of a Decimal interval against fixed limits | bench/step4/workflow.py mat_classify; bench/probe/boundary.py |

14 of 17 rows are flagged. The only unflagged model operations are the two O1 repair ops, whose checks run the candidate code against executable expected rows; the host can judge code but not write it. The step4 v3 pack already moved classification to the host (`host.classify@1`); extract and bounds are still model operations in v3 and are flagged here. Code-domain pilot jobs (`pefv`) are not in this corpus.

## 9. Actionable rule applied to every cell

216 (cell, category) pairs have a share of at least 25%. Disposition by reason (a pair can have several):

| reason it does not qualify | pairs |
|---|---|
| not a model-needed job (host-computable) | 192 |
| no single named variable moves it (deliverable or payload or inseparable residual) | 155 |
| unattributed (no split evidence) | 81 |
| unattributed residual (H plus CLI framing, inseparable) | 61 |
| stratum control: descriptive/control only | 26 |
| estimate (regression) | 12 |
| stratum smoke: descriptive/control only | 9 |
| attribution partial | 9 |
| qualifies | 0 |

Time categories (93 time cells, section 7.1): avoidable waiting at or above 25% in 0 cells (it is 0 ms everywhere). Unresolved time is at or above 25% in 42 cells and in 0 of the O1 time cells; it is unattributed, so it cannot qualify under any reading. Scheduling therefore has no demonstrated target.

### 9.1 Pairs at or above 25% in model-needed cells (all of them)

| cell | category | share | attribution | single variable | why not |
|---|---|---|---|---|---|
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_adapter; clean | packet_in | 52.4% | known | none | estimate (regression); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_adapter; clean | fixed_in | 25.7% | known | none | unattributed residual (H plus CLI framing, inseparable); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; * (all stages); clean | packet_in | 48.5% | known | none | estimate (regression); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; * (all stages); clean | fixed_in | 28.0% | known | none | unattributed residual (H plus CLI framing, inseparable); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_core; clean | packet_in | 43.8% | known | none | estimate (regression); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_core; clean | fixed_in | 30.9% | known | none | unattributed residual (H plus CLI framing, inseparable); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_adapter; interrupt | packet_in | 52.3% | known | none | estimate (regression); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_adapter; interrupt | fixed_in | 25.8% | known | none | unattributed residual (H plus CLI framing, inseparable); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; * (all stages); interrupt | packet_in | 47.1% | known | none | estimate (regression); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; * (all stages); interrupt | fixed_in | 27.3% | known | none | unattributed residual (H plus CLI framing, inseparable); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_core; interrupt | packet_in | 41.2% | known | none | estimate (regression); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_core; interrupt | fixed_in | 29.0% | known | none | unattributed residual (H plus CLI framing, inseparable); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_adapter; stale | packet_in | 54.1% | known | none | estimate (regression); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_adapter; stale | fixed_in | 26.6% | known | none | unattributed residual (H plus CLI framing, inseparable); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; * (all stages); stale | packet_in | 47.9% | known | none | estimate (regression); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; * (all stages); stale | fixed_in | 27.7% | known | none | unattributed residual (H plus CLI framing, inseparable); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=1; repair_adapter; stale | packet_in | 37.1% | known | none | estimate (regression); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=1; repair_adapter; stale | fixed_in | 56.2% | known | none | unattributed residual (H plus CLI framing, inseparable); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=1; * (all stages); stale | packet_in | 32.0% | known | none | estimate (regression); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=1; * (all stages); stale | fixed_in | 55.0% | known | none | unattributed residual (H plus CLI framing, inseparable); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=1; repair_core; stale | packet_in | 27.0% | known | none | estimate (regression); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=1; repair_core; stale | fixed_in | 53.8% | known | none | unattributed residual (H plus CLI framing, inseparable); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_core; stale | packet_in | 41.1% | known | none | estimate (regression); no single named variable moves it (deliverable or payload or inseparable residual) |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_core; stale | fixed_in | 29.0% | known | none | unattributed residual (H plus CLI framing, inseparable); no single named variable moves it (deliverable or payload or inseparable residual) |

### 9.2 Thinking, failed or resent, check-driven and caller overhead at or above 25% in the other cells

| cell | stratum | category | share | attribution | why not |
|---|---|---|---|---|---|
| live24_1g_D_haiku64; haiku-5-5; n=64; H; std | main | thinking | 50.1% | known | not a model-needed job (host-computable) |
| live24_1g_D_haiku_het; haiku-5-5; n=64; H; het | main | thinking | 56.0% | known | not a model-needed job (host-computable) |
| live25_1g_R_haiku; haiku-5-5; n=64; H; het | main | thinking | 52.6% | known | not a model-needed job (host-computable) |
| live26_1g_R3_haiku; haiku-5-5; n=64; H; het | main | thinking | 58.3% | known | not a model-needed job (host-computable) |
| live26_1g_R3_sonnet; sonnet-5-5; n=64; H; het | main | thinking | 31.4% | known | not a model-needed job (host-computable) |
| live29_1g_haiku_paired; haiku-5-5; n=64; H; std | main | thinking | 48.7% | known | not a model-needed job (host-computable) |
| live29_1g_haiku_paired; haiku-5-5; n=64; 0.8-exec; std | main | thinking | 35.1% | known | not a model-needed job (host-computable) |
| pilot2-materials-1g; haiku-5-5; n=16; H; std | main | thinking | 32.0% | known | not a model-needed job (host-computable) |
| pilot2-materials-1g; haiku-5-5; n=16; J; std | main | thinking | 27.5% | known | not a model-needed job (host-computable) |
| pilot2-materials-1g; opus-5-5; n=1; P; std | main | failed_resent | 33.5% | known | not a model-needed job (host-computable) |
| pilot_k2-A-reply; sonnet-5-5; n=64; K0; n/a | main | caller_overhead | 86.7% | known | not a model-needed job (host-computable) |
| pilot_k2-A-reply; sonnet-5-5; n=64; K1f; n/a | main | caller_overhead | 82.7% | known | not a model-needed job (host-computable) |
| pilot_k2-B-art; sonnet-5-5; n=16; K1f; n/a | main | caller_overhead | 79.2% | known | not a model-needed job (host-computable) |
| pilot_k2-B-art; sonnet-5-5; n=64; K1f; n/a | main | caller_overhead | 79.2% | known | not a model-needed job (host-computable) |
| pilot_k2-B-art; sonnet-5-5; n=16; K1r; n/a | main | caller_overhead | 85.5% | known | not a model-needed job (host-computable) |
| pilot_k2-B-art; sonnet-5-5; n=64; K1r; n/a | main | caller_overhead | 87.7% | known | not a model-needed job (host-computable) |
| pilot_k2-B-reply; sonnet-5-5; n=16; K1f; n/a | main | caller_overhead | 80.0% | known | not a model-needed job (host-computable) |
| pilot_k2-B-reply; sonnet-5-5; n=64; K1f; n/a | main | caller_overhead | 82.8% | known | not a model-needed job (host-computable) |
| pilot_k2-C-art; sonnet-5-5; n=64; K1r; n/a | main | caller_overhead | 52.2% | known | not a model-needed job (host-computable) |
| pilot_k2-A-reply; sonnet-5-5; n=64; K0; n/a | smoke | caller_overhead | 87.2% | known | stratum smoke: descriptive/control only; not a model-needed job (host-computable) |
| pilot_k2-B-art; sonnet-5-5; n=64; K1f; n/a | smoke | caller_overhead | 79.7% | known | stratum smoke: descriptive/control only; not a model-needed job (host-computable) |
| pilot_k2-C-art; sonnet-5-5; n=64; K1r; n/a | smoke | caller_overhead | 50.6% | known | stratum smoke: descriptive/control only; not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=4; * (all stages); interrupt | main | failed_resent | 49.5% | partial | not a model-needed job (host-computable); attribution partial |
| step4-inspection-handoff-20/live1; unrecorded; n=4; * (all stages); interrupt | main | check_driven | 49.5% | partial | not a model-needed job (host-computable); attribution partial |
| step4-inspection-handoff-20/live1; unrecorded; n=4; classify; interrupt | main | failed_resent | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=4; classify; interrupt | main | check_driven | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=1; classify; interrupt | main | failed_resent | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=1; classify; interrupt | main | check_driven | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=1; * (all stages); interrupt | main | failed_resent | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=1; * (all stages); interrupt | main | check_driven | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=4; * (all stages); stale | main | failed_resent | 32.7% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=4; * (all stages); stale | main | check_driven | 32.7% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=1; * (all stages); stale | main | failed_resent | 33.7% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=1; * (all stages); stale | main | check_driven | 33.7% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=4; classify; stale | main | failed_resent | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=4; classify; stale | main | check_driven | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=1; classify; stale | main | failed_resent | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live1; unrecorded; n=1; classify; stale | main | check_driven | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live2; sonnet-5-5; n=4; * (all stages); stale | main | failed_resent | 32.7% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live2; sonnet-5-5; n=4; * (all stages); stale | main | check_driven | 32.7% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live2; sonnet-5-5; n=1; * (all stages); stale | main | failed_resent | 33.7% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live2; sonnet-5-5; n=1; * (all stages); stale | main | check_driven | 33.7% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live2; sonnet-5-5; n=4; classify; stale | main | failed_resent | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live2; sonnet-5-5; n=4; classify; stale | main | check_driven | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live2; sonnet-5-5; n=1; classify; stale | main | failed_resent | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live2; sonnet-5-5; n=1; classify; stale | main | check_driven | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live3; sonnet-5-5; n=4; * (all stages); stale | main | failed_resent | 32.7% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live3; sonnet-5-5; n=4; * (all stages); stale | main | check_driven | 32.7% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live3; sonnet-5-5; n=1; * (all stages); stale | main | failed_resent | 33.1% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live3; sonnet-5-5; n=1; * (all stages); stale | main | check_driven | 33.1% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live3; sonnet-5-5; n=4; classify; stale | main | failed_resent | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live3; sonnet-5-5; n=4; classify; stale | main | check_driven | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live3; sonnet-5-5; n=1; classify; stale | main | failed_resent | 100.0% | known | not a model-needed job (host-computable) |
| step4-inspection-handoff-20/live3; sonnet-5-5; n=1; classify; stale | main | check_driven | 100.0% | known | not a model-needed job (host-computable) |
| boundary-probe; sonnet-5-5; n=4; A; block1 | control | failed_resent | 100.0% | known | stratum control: descriptive/control only; not a model-needed job (host-computable) |
| boundary-probe; sonnet-5-5; n=4; A; block2 | control | failed_resent | 100.0% | known | stratum control: descriptive/control only; not a model-needed job (host-computable) |
| boundary-probe; sonnet-5-5; n=4; A; block3 | control | failed_resent | 100.0% | known | stratum control: descriptive/control only; not a model-needed job (host-computable) |
| boundary-probe; sonnet-5-5; n=4; A; block4 | control | failed_resent | 100.0% | known | stratum control: descriptive/control only; not a model-needed job (host-computable) |
| boundary-probe; sonnet-5-5; n=4; A; block5 | control | failed_resent | 100.0% | known | stratum control: descriptive/control only; not a model-needed job (host-computable) |
| boundary-probe; sonnet-5-5; n=4; B; block6 | control | failed_resent | 100.0% | known | stratum control: descriptive/control only; not a model-needed job (host-computable) |
| boundary-probe; sonnet-5-5; n=4; A; block6 | control | failed_resent | 100.0% | known | stratum control: descriptive/control only; not a model-needed job (host-computable) |

Input categories at or above 25% in the host-computable cells (packet, fixed, unsplit) are in `per_cell.csv`. They are not model-needed, so none can qualify.

### 9.3 Final list

Qualifying categories: none. **No demonstrated actionable bottleneck.**

Conditional reading (not a qualification): if Astra defines the fixed per-call input as H, these O1 cells are at or above 25% and the single variable would be H length (the system text) or, for the size-1 cells, batch size (jobs per call):

| cell | fixed per-call input share |
|---|---|
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_adapter; clean | 25.7% |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; * (all stages); clean | 28.0% |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_core; clean | 30.9% |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_adapter; interrupt | 25.8% |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; * (all stages); interrupt | 27.3% |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_core; interrupt | 29.0% |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_adapter; stale | 26.6% |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; * (all stages); stale | 27.7% |
| o1-repair-handoff-20/live1; sonnet-5-5; n=1; repair_adapter; stale | 56.2% |
| o1-repair-handoff-20/live1; sonnet-5-5; n=1; * (all stages); stale | 55.0% |
| o1-repair-handoff-20/live1; sonnet-5-5; n=1; repair_core; stale | 53.8% |
| o1-repair-handoff-20/live1; sonnet-5-5; n=4; repair_core; stale | 29.0% |

## 10. Ambiguities resolved and gaps

1. Model-needed. The preregistration says qualification needs a model-needed job but not how that is decided. I used the host-computable scan: a job is model-needed only if no check recomputes its full answer. By that test the only model-needed workload is O1 repair, which matches the signed note that O1 is the only workflow that needs the model.
2. Control and smoke strata. Item 1 says the boundary and adopt-qual envelopes are 'historical boundary and qualification controls only' and smoke runs are 'a separate descriptive stratum'. I report their cells but they cannot qualify. They would fail the model-needed condition anyway, because classification is host-computable.
3. H attribution. The corpus never varies H alone, so H cannot be separated from the CLI's own request framing. I split billed input into packet input (regression slope on the ledger's own prompt estimate, an estimate from measured totals) and a fixed remainder labelled H plus CLI framing, which I treat as an unattributed residual. The prereg's rule that unknown attribution cannot qualify is applied to it. If Astra reads that remainder as H, section 9.3 lists the cells.
4. Cache read versus cache write inside the fixed input is shown only at whole-call level (section 5.2). A per-call split of H into cache write and cache read would assume the system block precedes the packet, which the counters cannot confirm.
5. Counter source. live22 to live29 hold CLI `usage` counters, not `modelUsage`; pilot2 holds runner-summed `modelUsage`; ledgers hold adapter counters derived from `modelUsage`. Each is used as stored and named in every row. The runner passes `--tools ''`, so one turn is expected and `usage` should equal `modelUsage`, but `num_turns` was not stored, so that is an expectation, not a check.
6. Thinking for step4 live2, live3 and O1 comes from the run report, joined to the ledger by scenario, receipt, stage, attempt and member count (and tokens where the first join was not unique). step4 live1 has no thinking source. Calls that were killed and recovered (no `call_end`) have total input and output from the report and no cache split.
7. Tags. 'Failed' = a call_end with a nonzero exit, timeout or non-ok outcome, an errored or invalid flat run, or an envelope whose evaluation was not entirely correct. 'Resent' = attempt above 1 or a `retry_of`. 'Check-driven' = resent calls and the original call each resend names in `retry_of` (the call ledger's own validation is structural and shows no rejection, so the origin is identified through the resend); its tokens are counted whole although only the rejected members were wasted. A call killed and recovered from its capture is not failed (its result was used). Caller overhead = all caller tokens on delegating arms.
8. Time. Ledger runs have no recorded end-to-end wall, so their wall is the call span; the whole live run's start and finish are in the report but cover all scenarios together. Avoidable waiting is 0 because no source records a queue or backoff, and independent-call serialization is a replay hypothesis (the step4 and O1 stages are DAG-ordered: bounds needs the extracted fields, classification needs the checked interval, adapter needs the accepted core), not a measurement.
9. Smoke strata are in the corpus tables under their own stratum and in no share used for a conclusion.
10. Digest scope. The manifest digest covers all 858 entries, observation and provenance, over raw bytes. A checkout that rewrites line endings would change it.

