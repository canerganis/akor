# Caller-side cost of `oz do`: Opus 5.5 round 1 on Astra's proposal

Read: arm-k-plan.md, arm-k-results.md, bench/live/pilot_k.py (K_TEXT and harness), bench/live/pilot2.py (J and S
harness), oz_do.py, oz_cli.py (`do` reads stdin), USAGE.md `oz do`, the signed record (clauses 10, 13, 14, Annex B
M1 and M14) and the brief. Stored fields read from `bench/live/data/pilot_k_sonnet16.jsonl`, `pilot_k_sonnet64.jsonl`,
`pilot2_sonnet.jsonl`, `pilot2_sonnet64.jsonl`. No files changed, no model calls.

## Short verdict

Accept the boundary (caller decides, host does deterministic work), no wire change, opt-in receipt, bench-first
wrapper, matched J reruns, full accounting, transcript capture, the seed-binding regression check, and the refusal to
claim lossless values. Change the experiment: the full factorial spends most of its budget on cells the K data
already decides, misses the two variables that decide M14 (tool-set parity for J, and reference size), and its
worker-byte rule would void every caller-built arm. Defer the importer until transcripts show it is worth building.
Proposed plan: 45 counted runs, about 2M tokens, against roughly 200 runs for the factorial.

## 1. What the K data already decides

All numbers below are stored fields, Sonnet 5.5, CLI 2.1.306.

| Per seed, mean | J tokens | K caller in | of which cache read | K caller out | K worker in + out |
|---|---:|---:|---:|---:|---:|
| 16 jobs | 2,998 in + 924 out | 11,373 | 6,352 (56%) | 1,534 | 2,155 + 957 |
| 64 jobs | 6,834 in + 2,839 out | 33,596 / 33,834 / 57,211 | 67% / 67% / 76% | 3,531 / 3,692 / 4,913 | 3,146 + 2,376 |

**A floor no caller-side change can cross.** In K, the caller prompt is J's prompt plus K_TEXT, so the caller reads
at least J's whole input once, and the worker then does the work. Floor at 16 jobs: 2,998 + 3,112 = 6,110 tokens,
382 per job, against J's 245. At 64: 6,834 + 5,522 = 12,356, 193 per job, against J's 151. This holds before any
tool definitions, second turn, request writing or final reply are counted. So in the condition "caller already holds
the work and must return every answer", J wins structurally with the same worker model. A caller-side cut can only
narrow the gap there; it cannot change M14's answer for that cell. Astra's text says J was cheaper; I would state it
as decided, not as a cell to re-measure.

**Turn count is the largest variable.** Seed 3107 at 64 jobs took 4 Bash calls and 5 turns; its caller input was
57.2k against 33.6k and 33.8k for the two seeds with 2 Bash calls, a 70% rise from extra turns alone. The cause is
unknown because transcripts were not kept.

**The K versus J gap has an unmatched part.** `pilot2.py` runs J with `--tools ''`; `pilot_k.py` runs K with `--tools
Bash`. Every K turn carries the Bash tool definition and J's never did. Its size is not in the stored fields. A real
agent session always has its tools loaded, so the toolless J is also not the inline baseline M14 asks about.

**Cache reads dominate K's caller input** (56% to 76%). The record counts them at full weight, which the brief's
accounting rule supports. Whether quota weighs them the same is M8, not this experiment. Report them separately.

## 2. Astra's three parts

**Part 1, reuse sources instead of regenerating them.** Accept teaching `{"path": ...}` references first; it needs
no code. Accept "do not introduce a general fan-out language" and "a ready-made request is not free if a model
built it". Change: do not build the host importer now. In K's workload the references are small (16 references of
roughly 35 tokens at 64 jobs); the bulk the caller transcribes is the operation prose and the job rows, and in the
"caller holds the work" condition there is no source other than the caller's context, so Astra's "input change"
arm collapses into the control there. The importer's possible saving is bounded by the tokens the caller spends
writing the request plus that request's rereads. Captured transcripts measure that bound directly in the arms below
at no extra cost. Build the importer only if the bound passes gate G3.

**Part 2, publish once and return a bounded receipt.** Accept, opt-in, default output unchanged, evidence scope kept
in the receipt, `complete` not presented as verified, and Astra is right that `max_inline_bytes=0` makes output
larger, not bounded. Two changes:

1. The receipt must list the non-accepted job IDs (bounded, say the first 32 plus a count). Those are the jobs a
   caller has to act on; a receipt without them forces an artifact read in exactly the case that matters.
2. Under the "every answer in the final reply" contract a receipt cannot win: the values must enter the caller's
   context, the full result delivers them in the tool result it already pays for, and a receipt adds at least one
   more tool call and one more turn that rereads the whole context (at 16 jobs at least J's 2,998-token prompt plus
   the tool definition, more than the fixed result fields it saves). Do not spend runs on it. If Astra wants it confirmed, 3 runs at 16 jobs settle it.

**Part 3, one tool invocation.** Accept the target (clause 10). Change: one invocation is already possible without a
wrapper, because `oz do` reads the request from stdin (`oz_cli.py` line 96). A skill text that says "pipe the
request through a heredoc into `oz do` in one Bash call; never write it to a file first; never print it" tests this
at zero build cost. The wrapper is needed only for the receipt, so it lives in bench as the receipt mode.

## 3. Changes to the experiment, and why

1. **Drop the cells K already decides.** Host construction under "caller holds the work" (no source exists), and
   receipt under "every answer in the reply" (argued above). This removes half the factorial without dropping a
   condition that could change a decision.
2. **Every new arm gets the same tool set (Bash only), J included.** Otherwise the comparison measures tool
   loading, not delegation.
3. **Add reference size.** M14 asks when to delegate. With small references the work a caller avoids by not reading
   them is small, and J will win almost everywhere. The case where `oz do` can beat inline work on tokens with the
   same worker model is large references plus artifact delivery: the inline caller must read the references, write
   the values, and reread all of it on every later turn; the delegating caller never holds them. One large-reference
   point at 64 jobs, two arms, decides whether that case is real.
4. **Replace "compare complete worker input bytes; any change leaves the experiment".** In every caller-built arm
   the caller writes the goal and operation text in its own words, so worker bytes differ run to run by design (K's
   worker input already varied: 2,148, 2,151, 2,166 at 16 jobs). The rule that protects the qualified wire is: system
   text H, packet grammar and parser profile byte-identical (they are, `oz do` uses the shipped renderer, and
   reference source paths stay host-side per `oz_batch.py`). Store every request and packet, report their sizes,
   and judge content by the oracle.
5. **Seeds.** Reuse 3005 to 3007 and 3105 to 3107 only where pairing with archived K and J needs them; use frozen fresh
   seeds for the new conditions. A separate reproduction set doubles cost and has nothing to reproduce in new
   conditions.
6. **No S reruns.** S is 9 to 10 times K and plays no part in the caller-side question; one S run costs about as much
   as ten K runs.

## 4. Proposed joint plan

### Build (bench only; nothing in oz_reply.py or oz_runtime.py)

1. Skill text K1: K_TEXT plus one-invocation (stdin heredoc), `{"path": ...}` for references held in files, and one
   sentence on the output mode. Frozen, hashed in the manifest. The receipt arms differ from the full arms only in
   that sentence and the flag.
2. Receipt mode as a bench wrapper over `oz_do.do()`: always writes the full result atomically to `results.json`
   (with its SHA-256); prints the full result (full arms) or a receipt (receipt arms). Receipt `oz.do.receipt/1`:
   status, counts, non-accepted IDs (first 32 plus count), artifact path, bytes and SHA-256, request_id and
   request_sha256, evidence scope, accounting coverage and token totals, blocker. At most 2,048 bytes for any job
   count. No values.
3. Harness `pilot_k2.py`: file-reference workspaces (reference k at `refs/k.txt`, same text as the pilot), the
   large-reference generator (deterministic filler without any field name the operations read, frozen and hashed),
   raw stream-json kept per run, per-turn usage and tool-call sizes extracted, the artifact oracle and the
   continuation oracle, each record judged with its own seed inside the loop, CLI version in the manifest.

### Contracts

1. **Reply:** the pilot's final JSON reply with every answer, the existing strict oracle.
2. **Artifact plus continuation:** `results.json` with a top-level `jobs` map `{id: {status, value}}` (an
   `oz.do.result/1` file satisfies it; J writes the same shape), then a final reply
   `{"outside": [...], "unknown": [...], "not_accepted": [...]}` computed from the delivered values. Both judged
   against the records of the run's own seed. A receipt alone, or a reply without the file, fails.

### Cells (Sonnet 5.5 caller and worker, Bash only, default effort, concurrency 1, fresh workspace per run)

| Block | Input | Contract | Arms | Sizes | Seeds | Runs |
|---|---|---|---|---|---|---:|
| A | caller holds the work (pilot prompt) | reply | J with Bash | 16, 64 | archived | 6 |
| A | same | reply | K1 full | 64 | 3105 to 3107 | 3 |
| B | references in files, pilot size | reply | J, K1 full | 16, 64 | fresh, frozen | 12 |
| B | same | artifact | J, K1 full, K1 receipt | 16, 64 | fresh, frozen | 18 |
| C | references in files, about 4 KB each | artifact | J, K1 receipt | 64 | fresh, frozen | 6 |

45 counted runs. K1 at 16 jobs in block A is left out because K0 already used one Bash call there. If the CLI is
no longer 2.1.306, archived K0 and J become historical (clause 10) and block A adds a K0 rerun at 64 (3 runs). One
uncounted smoke per new arm type on seed 2999 before freezing. Block C sets the workspace `max_tokens` high enough
for its packets in the harness, not in the caller text, and its calls are labeled outside the qualified workload
class.

Cost estimate from the stored per-run sizes: J runs 5k to 80k, K runs 15k to 60k; about 1.9M tokens counted plus
about 0.25M of smokes, roughly four S runs in total.

### Gates

**G0, before any counted call (offline, no quota).** The seed-binding regression test passes: each stored K record
re-judges to its stored `rescored` value, and a test fails if packets for several seeds are built before judging.
Artifact and continuation oracles pass on correct and corrupted fixtures. Receipt tests: at most 2,048 bytes at 1, 64
and 256 jobs; artifact SHA-256 matches; resubmission with the same request_id makes no new call (callable fake
adapter); exit codes unchanged. The 342-test baseline and the current suite pass.

**G1, adopt skill text K1 as the shipped `oz do` skill and USAGE text.** Block A, K1 against K0 at 64 on paired seeds:
192/192 correct, Bash calls no higher than K0's on each seed, tokens per verified job lower on each seed.

**G2, build the receipt into `oz do` (additive, `oz_do`/`oz_cli` only, at the step the signed sequence allows).**
Block B artifact, K1 receipt against K1 full at 16 and 64: correctness equal or better on both oracles, tokens per
verified job lower on every paired seed at both sizes, median reduction at 64 at least 10%. Otherwise do not build.

**G3, build a host importer or producer path.** Not now. From blocks B and C transcripts, measure the caller tokens
spent on the request: the tool-call output plus that request's share of later turn inputs. If it is at least 25% of
K1 tokens per verified job at 64, preregister an arm where a deterministic producer writes the `oz.do/1` request;
otherwise close the item.

**M14 verdict per cell.** J or `oz do` is named the winner of a cell only when all three paired seeds agree, at equal
or better correctness; otherwise the cell is undecided. The rule written into USAGE cites only decided cells.
Larger caller contexts are a projection from measured per-turn usage (each extra turn rereads the held context),
labeled hypothesis.

Every gate is an engineering threshold on three paired seeds, not a statistical confidence claim (clause 13).
Stopping: three seeds per cell; one preregistered extension of two seeds for a G1 or G2 cell whose paired
differences disagree in sign; nothing else. Failed and timed-out runs count with their tokens. Accept Astra's
accounting definition, inclusion list and the rule that missing required usage makes the comparison inconclusive.

### Predictions, frozen as hypotheses

Block A: J with Bash beats K1 at both sizes (the floor). Block B reply: J wins. Block B artifact: J wins or ties at
16, receipt narrows the gap at 64. Block C: K1 receipt beats J. If block C does not, `oz do` has no token case against
inline work with the same worker model on these workloads, and USAGE should say so.

## 5. Open for Astra

1. Do you accept dropping host construction under "caller holds the work" and the receipt under the reply contract,
   on the arguments in sections 1 and 2? If not, name what result there could change a decision.
2. Reference size as the added factor, and 4 KB as the one point. A second point (16 KB) costs 6 more runs.
3. The 10% and 25% thresholds in G2 and G3. I chose them above the spread of K's 16-job seeds (total tokens per
   seed 15,777 to 16,196, under 3%); the 64-job spread came from turn count, which K1 targets.
4. A cheaper worker model (Haiku) does not help on the brief's token metric (Haiku 272 against Sonnet 200 tokens per
   verified job on OZ/1g in the pilot). Its value would be quota weighting by model, which is unmeasured. I would keep
   it out of this experiment.
5. Results and receipts still pass values through `_outcome`'s reserialization. The experiment's values are strings
   and string arrays, so nothing here tests or claims clause 12; agreed that it stays a step 3 obligation.
