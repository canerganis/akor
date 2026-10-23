# Round 2: Opus A

## 1. Cross-critique

Astra A
1. KEEP `oz-rule/1`, a JSON AST where every path returns `value` or `abstain`: abstain makes the semantic control cheap.
2. KEEP content-hash storage pinned to contract, interpreter and check versions.
3. MERGE the labeled holdout into Opus B's bootstrap: asking users for labels breaks "a few lines". Gold stays offline.
4. KEEP residuals pooled across producers: the cross-agent part, and what LOTUS, DocETL and Palimpzest lack.
5. DROP 18 calls on one seed: caller-cost needed three agreeing pairs.

Astra B
1. MERGE partial programs: reserve the named-question node in the grammar, disabled in pilot 1 (see 4.1).
2. KEEP `codex exec` for the kill pilot: zero Claude quota, all arms matched on one backend.
3. DROP RTE for BoolQ (see 4.4).

Opus B
1. KEEP the floor decomposition (about 2,310 per call, about 55 per job): it caps model-on-every-job gains near 1.7x.
2. KEEP bootstrap from accepted answers and the 98% gate, with a split: compile sees 32 of the first 64 answers, the gate replays the other 32.
3. KEEP audits riding inside the residual call.
4. KEEP arm G computed from arm Q's 2,389 per miss, not run.
5. MERGE "regex capture" into Astra A's bounded extraction; Astra decides.
6. DROP WebRuleBench: gold labels unconfirmed.

## 2. My position after the new prior art

`oz map` as I wrote it collides. DocETL has declarative map stages with per-output validation and retry, Sema batches prompts inside a semantic pipeline, Trummer packs row blocks, and Dong and Wang (2607.13407) propose compiling a semantic operator to local code once. "One line instead of Python or YAML" is ergonomics, not novelty. I drop the claim that fan-in is new.

Still new, as far as the notes show: jobs from several independent agents entering one leased queue, with residuals pooled across them; packing heterogeneous jobs per call combined with a host check per job and retry of failures only; a compiled rule gated by those same checks plus batched audits; and accounting amortized across calls.

## 3. Convergence

Accept, with three amendments.
1. Learning is a flag, not a second tool: `oz map 'refs/*.txt' --ask extract_alloy.oz --check schema,sum100 --learn`. The user sees a rule only when it is revoked.
2. Several agents may call `oz map` on one workspace; the queue flushes at 64 items or a fixed wait. Otherwise pooling has no producers.
3. The engine pilot uses scripted producers and claims nothing about caller cost. Caller-cost claims wait for a later surface check.

## 4. Open choices

1. Whole program with abstain. On materials whole programs should cover most jobs; on BoolQ the named question is the whole job. Neither workload separates the two, so testing partial now fails Astra B's distinction kill by construction.
2. Audit rate: max(1/16, fill the residual call to 64), seeded, uniform. Once the call is paid, an audit item costs about 55 tokens (Opus B's fit).
3. Pooling: yes, only across producers with identical contract, check and permission hashes, flushed at 64 or the deadline. Run pooled; compute unpooled from the backend's per-call fit.
4. BoolQ: 256 seeded dev items, majority-class rate reported. Heavier passages than RTE, used by BatchPrompt, and an "always yes" rule must fail the gate.
5. `codex exec`, every arm rerun there, no comparison with historical Sonnet. One Sonnet confirmation only if it survives and Claude weekly is under 52%. Precondition: one dry call shows `codex exec` reports reasoning tokens; otherwise efficiency is unvalidated. I read "Codex at 8%" as used; if it means remaining, the pilot cannot run there.
6. Budget: at most 56 `codex exec` calls, three seeds. Per seed: materials 4 baseline, 1 compile, 3 pooled residual calls; BoolQ 4, 1, and at most 3 if the gate wrongly admits. Plus 2 calibration, 1 telemetry check, 4 reserved retries: 55. Sonnet confirmation at most 16.

## 5. Most important kill criterion

Any job, in any seed, where the rule's answer is wrong against offline gold yet passed the checks and the audit. AKOR's pitch to agent users is verified work at scale. A silently wrong rule ends that pitch; a weak saving ends one optimisation.
