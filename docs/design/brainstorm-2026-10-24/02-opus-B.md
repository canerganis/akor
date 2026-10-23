# Round 2, Opus B (efficiency and systems)

## 1. The other three proposals

Astra A:
1. `oz-rule/1` AST with `value` or `abstain`: KEEP. Per-job abstention enables residual batching.
2. Labeled holdout for admission: MERGE. The pilot uses labels kept apart from the test jobs. Production admits on model-answered examples and reports that separately.
3. Residuals pooled across producers: KEEP. Each avoided call saves about 2,310 fixed input tokens and about 10 s, which matters only below one full batch.
4. Fixed 5% audit: DROP for a count-based audit (section 4).
5. Hand-written solver baseline: KEEP. It answers the critic.
6. BoolQ within 10%: KEEP. It exposes a cost bug in every plan (section 2).

Astra B:
1. Partial programs: DROP for the pilot. Materials is fully deterministic and BoolQ/RTE fully semantic, so whole and partial programs cannot separate and Astra B's own indistinguishability kill fires. Revisit on bench/codereview.
2. `codex exec`: DROP. It changes model, CLI overhead and telemetry at once.

Opus A:
1. `oz map` surface with one receipt line: KEEP.
2. `--width`: KEEP, and make width 4 the time baseline. Four full lanes keep 91.6 tokens and might cut 256 jobs from about 80 s to about 20 s (guess). Rules must beat that.
3. MCP server and default adapter: KEEP. They are cheap.
4. Rerunning subagent-per-job and agent callers: DROP. Subagent cost is measured (7,931), and caller cost is its own experiment.

## 2. Revised position

Nothing in my mechanism is new alone:

1. Sampled audit: LOTUS sets thresholds from sampled oracle labels.
2. Compile step: arXiv 2607.13407 compiles semantic operators to local code with one call.
3. Batched residual: Trummer, Sema and Continuous Prompts batch rows into one prompt.

What remains new is one runtime that combines four things:

1. Rules that abstain per job.
2. Abstentions from several producers pooled into heterogeneous, host-checked batches.
3. Retry of failed jobs only.
4. An all-in amortization curve of billed tokens, failures included.

One change is now necessary: fuse the compile into the bootstrap call. On 256 BoolQ jobs a separate compile call (about 6k to 7k, guess) adds about 25% to the baseline's roughly 23.5k, failing both Astras' overhead kills. Instead, the first batched call gets a final "rule or none" slot. Declining costs a few output tokens on top of the 2,310 fixed input already paid. A failed audit adds a "revise" slot to the next residual call. No standalone compile call ever runs. Risk: the slot may change the answers, so the pilot compares them with the baseline on identical jobs.

## 3. Convergence

Accept, with three amendments:

1. `--learn` is off by default.
2. Time is compared against `--width 4`.
3. The pilot uses scripted producers.

Guess: cold, about 50 tokens per job over two calls; warm, about 20 over one. Cold is probably slower than width 4, so claim tokens, not time.

## 4. Open choices

1. **Program shape:** a whole program with per-job abstention.
2. **Audit:** 32 audits per rule version per run until 300 clean, then 1/16.
   * 32 audits catch a 5% error rule with 81% probability, and a 10% error rule with 97%.
   * 300 clean audits bound error below 1% at 95% confidence.
   * A 5% sample of 192 gives about 10 audits, which catch 5% error only 40% of the time.
   * About 1.8k tokens, riding the residual call.
3. **Pooling:** yes, when a producer's residual is under 64 jobs and contracts and permissions match.
4. **Public non-rule workload:** BoolQ (used by BatchPrompt); RTE alternate.
5. **Runner:** `claude -p` Sonnet only.
6. **Budget:** 32 calls, two seeds.
   * Materials, per seed: width-4 baseline (4 calls), fused call (1), unpooled residuals (3), pooled residual (1).
   * BoolQ, per seed: baseline (4) plus fused call (1). After the rule declines, its later calls equal baseline calls 2 to 4 and are shared.
   * 4 reserve calls.
   * About 0.2M tokens (guess). Abort at 55% of the Claude weekly quota.

## 5. Most important kill criterion

On materials, kill if rule-answered jobs are wrong on gold more often than the baseline is on the same jobs. The token win on rule-shaped work is near certain; correctness is the open question.
