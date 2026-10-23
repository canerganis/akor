# Round 1, Opus B (lens: efficiency and systems)

## 1. Diagnosis

The 91.6 decomposed (`pilot2_sonnet64.jsonl`, arm H, 3 calls). Per call: 3,581 input (2,976 cache write, 603 cache
read) and 2,282 output, 957 of it hidden reasoning. Per job: 46.5 write, 9.4 read, 35.7 output (15.0 thinking).

A two point fit against the 16-job cell (my arithmetic) gives about 2,310 fixed input tokens per call, about 20 input
and 35 output per added job, and about 9.6 s fixed plus 0.16 s per job of wall time. Arm Q agrees: a one-job call has
6.9 s median wall but 1.9 s API time, so about 5 s per call is CLI process overhead.

1. Any design that keeps the model on every job has a floor near 55 tokens per job, even with infinite batches.
   Batch size, format and thinking cuts can win at most about 1.7x over 91.6.
2. Seconds are decode-bound (about 10 s decode plus 10 s fixed for 64 jobs) and the runtime is sequential.
3. The caller costs more than the worker. In arm K (seed 3105) the caller billed 37,127 tokens over 3 turns, the
   worker 5,518: 87% caller. One caller turn (about 11k) costs as much as about 120 worker jobs.
4. Cache layout cannot move the headline: AKOR counts cache reads at full weight (pilot limit 8). It changes price
   and time to first token only.

## 2. Prior-art collision check

GenCache already has the core: the LLM writes a program from similar prompts, it is validated, and misses fall back
to the LLM per request. Plan Caching keeps a small model on the hit path. FrugalGPT and RouteLLM are cascades between
models, and cheap tier plus expensive fallback is their idea. Batch prompting packs without validation or retry.
TOON is irrelevant on a path with no model. Provider batch and caching cut price, not calls or output tokens.

New in mine, narrowly: the cascade's miss path and its audit go through batched, host-checked OZ calls instead of
per-request calls, measured all-in over repeated runs. That has a price: a GenCache-style miss costs about 2,389
tokens (arm Q's per-job cost), a batched miss about 55 to 92. The safe rule language and revocation through MemoStore
are engineering, not research. The rest is not new.

## 3. Proposal: learn once, audit by batch

1. The first 64 jobs of an op go through a normal OZ/1g call; the host keeps the accepted answers (no gold labels).
2. One compile call asks for a rule in a small host-interpreted language: field lookup, regex capture, unit
   normalization, comparison, table lookup, if/else, no loops or I/O.
3. The host replays the rule on held-out examples and keeps it only at 98% or more agreement with the model's own
   answers; otherwise it abstains and the op stays on the batched path.
4. The kept rule goes into MemoStore, keyed by op, schema and teaching hash.
5. Later jobs run on the rule. Each run sends a random 1/16 of rule outputs plus every unresolved job as one batched
   OZ call. A disagreement revokes the rule.

What the user writes (placeholder syntax; Astra owns the wire):

```
op extract_measurement
learn rule  audit=1/16  agree>=0.98
jobs @jobs.jsonl
```

The caller takes one turn per run, so its 11k is spread over the whole run.

## 4. Expected gain (guesses unless marked)

For 1,024 materials jobs: bootstrap 5.9k (measured), compile call about 7k (guess), four audit calls at about 3.2k.
That is about 26k, or about 25 tokens per verified job, roughly 3.6x better than 91.6. A later run reusing the stored
rule might cost 5 to 10 per job. Wall: one audit call (about 10 s) per 256 jobs instead of four 20 s calls, so
roughly 1,500 against 192 jobs per minute. On non-rule work the gain is zero and the cost is one compile call.

## 5. Smallest preregistrable experiment

Sonnet 5.5, 3 seeds, fresh records.

Workloads:

1. The materials ops (rule-shaped).
2. WebRuleBench (public). Its gold labels must be confirmed before freezing, or a named substitute is used.
3. BoolQ (public, not rule-shaped), 256 jobs.

Arms:

1. B: OZ/1g in batches of 64, measured on 128 jobs per seed and scaled linearly (B is a sum of identical calls).
2. C: learn once, audit by batch, four rounds of 256.
3. G: GenCache-style per-miss fallback, computed from C's misses times arm Q's 2,389, not run.

Metrics: all billed tokens per gold-verified job, failed and compile calls and thinking included. Also wall time,
jobs per minute, rule coverage, audit disagreements and errors that went undetected.

Kill criteria:

1. Materials or WebRuleBench: C costs more than 0.5x B on any seed, or C's accuracy is more than 1 point below B's.
2. BoolQ: C costs more than 1.15x B, meaning the abstain gate failed to fire cheaply.
3. Any round where the rule's gold error rate exceeds B's without revocation.

Budget: about 70 calls, about 0.35M tokens (guess). Stop at 55% Claude weekly.

## 6. Headline and critic

Headline: "After one teaching call, AKOR ran 1,024 verified extraction jobs at about 25 tokens each, and declined to
compile a reading-comprehension task for the price of one call."

Critic: "GenCache with a regex language on a benchmark built to be rule-shaped. A 1/16 audit is statistics, not
per-job verification, and an engineer could write that regex without a model."
