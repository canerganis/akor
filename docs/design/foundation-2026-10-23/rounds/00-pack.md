# AKOR foundation decisions, 2026-10-22: the architecture "physics" for the next phase

## Mandate (owner)
Astra and Opus 5.5 write AKOR's foundational architecture decisions together. Full authority over the language and
the runtime design, judged by: (1) max independently correct requested work before the deadline within subscription
quotas, (2) min total billed tokens incl. hidden reasoning and failed calls, (3) min elapsed time. Teaching once may
cost more; later calls must get cheaper. No API key, only authenticated `claude -p` (and `codex exec`). The owner wants
a solid foundation: decisions that later steps can build on without being reopened, each with its reason and the test
that would prove it wrong. The owner will share the result publicly, so it must be comprehensive and high quality.

## Signed joint plan (this morning, both of you)
1 freeze evaluation; 2 16-job pilot (per-job calls, subagent-per-job, batched JSON, OZ/1g; running now);
3 selective acceptance and fencing; 4 manual 20-step executor with checkpoints and freshness-verified memo;
5 optimize from evidence one variable at a time (effort first); 6 package, optional bounded replanning, MCP only on need.

## New facts since then
- Step 1: every published tokens-per-verified-job figure reproduces exactly from raw data
  (Sonnet 87.0/146.7, Opus 82.6/144.8 per verified (144.3 per requested), Fable 86.9/146.3, Haiku 142.1/205.3);
  input = uncached + cache_read + cache_write on every record; thinking is inside output, counted once.
- Accounting defect found: the `usage` field of `claude -p --output-format json` covers only the LAST turn. For a
  tool-using call it under-reports; `modelUsage` aggregates the whole call including subagents. Smoke: an orchestrator
  spawning 16 subagents for 16 materials jobs: usage said ~21k input, modelUsage 145k input + 6.7k output
  (92k cache reads, 53k cache writes), 46 s, 16 spawns, 15/16 correct. One OZ/1g call for 16 such jobs is ~0.8k
  packet tokens plus ~1k CLI overhead plus output.
- Older effort data (live12, earlier native-JSON wire, 64 jobs, 5 calls per cell): Haiku medium 320/320 with output
  3230 (thinking 2352) vs high 4469 (3590); Haiku low 3/5 replies valid. Sonnet medium 320/320 output 1593 vs high
  1737; Sonnet low 4/5 valid. No effort data exists on the OZ/1g wire; Haiku default on OZ/1g: output 6110, thinking 4753.

## What the code is today (Python stdlib, ~3.1k lines core)
- oz_workspace.py: SQLite inbox, jobs with deps, leases, retries, resume; exactly-once insertion, at-least-once
  delivery. oz_worker.py / oz_batch.py: build OZ/1g packets, call adapter (stdin/stdout program), strict atomic parse.
  oz_runtime.py: host ops (read, test, status). Ledger calls.jsonl per call. No graph planner, no memo, no
  checkpointed DAG, no per-job acceptance, no effect fencing.
- OZ9.md (attached verbatim below) is the normative spec; its sections 7-9 (plan as data, planner wire,
  checkpoints/replanning) are specification only, unimplemented and unmeasured.

## The task
Write the foundation decision record for AKOR's next phase. Cover at least these decision areas, and add any you
judge foundational:
D1 units and identities: request, job, node, attempt, effect, result; what is content-addressed and what is not.
D2 acceptance semantics: per-record vs per-reply; which failures stay reply-level; how correctness (oracle/verifier)
   differs from parse validity; how valid-looking wrong records (index drift) are handled.
D3 retries and fencing: attempt identity, late replies, idempotency of effects, at-least-once vs exactly-once claims.
D4 memo and freshness: key, what invalidates, when a memo hit counts as verified work.
D5 state and checkpoints: what is durable, crash points, resume semantics.
D6 plan/graph format: what a node declares (op, inputs, deps, verifier, budget), who may author it (human, planner),
   admission rules, what a replan may and may not change.
D7 scheduling contract: ready set, batching across workflows, deadline, fairness; what the scheduler may optimize.
D8 accounting: the single source of truth for tokens (modelUsage), cache columns, failed calls, quota observations.
D9 the model boundary: what stays fixed in the OZ/1g wire, what may change, and the rule for changing it.
D10 integration surface: CLI, Python API, Claude Code skill, MCP; which is the primary contract.
For each decision: the decision, alternatives rejected and why, the invariant it guarantees, the test that would
falsify it, and its cost (tokens, latency, code). Then list open questions that need measurement, not opinion.
Write in English. Be concrete and normative (MUST/SHOULD). Do not repeat OZ9.md where it already holds; say
"keeps OZ9 x.y" and spend the words on what is new or changed.
