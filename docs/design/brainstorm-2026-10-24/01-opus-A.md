# Round 1: Opus A (lens: orchestration ease and attention)

## 1. Diagnosis

The worker side is nearly solved: one OZ/1g call does 64 jobs at 91.6 tokens per verified job in 20 s. What
remains is the caller and the surface.

1. The caller is the cost. In arm K (798.7 per verified job) 81% to 89% of tokens were the caller rewriting jobs and
   rereading context. Caller-cost showed a same-model caller answering inline (J: 167 at 64 jobs, cell A) beats
   handing work to `oz do` (K1f: about 500). Anything that keeps the caller writing or reading payloads loses.
2. The baseline people actually run is one subagent per job: 7,931 per verified job, 105 s. That is the number a
   stranger recognises from their own bill.
3. Friction: `oz_do.do()` needs an explicit adapter, flat modules, no MCP server, sequential execution
   (oz_do.py:476) although the inbox supports concurrent leases.
4. Attention: about 1 star, tens of views.

## 2. Prior-art collision check

1. Batch prompting (Cheng et al., BatchPrompt): packing is the same idea; not new. They lack per-job checks and
   selective retry, but AKOR already has those.
2. TOON, routers, cascades: no collision; I propose no format or model choice.
3. GenCache, Plan Caching: reuse generated programs or plans. I compile nothing, so I claim none of that novelty.
4. Provider batch and caching: still one request per job, no validation, unavailable without an API key.
5. LangChain `.batch()`, Agents SDK `asyncio.gather` (Luna): parallel fan out, not fan in.
6. Closest collision, absent from the notes: LOTUS semantic operators, DocETL, Palimpzest offer map and filter over
   data via API. Whether they pack rows per call or verify per row is UNVERIFIED and must be checked first.

New, strictly: a fan-in primitive callable from inside a subscription CLI agent, where the host expands jobs from a
template and a file glob so caller cost is constant in N, and stage outputs pass by reference so the caller never
reads them.

## 3. Proposal: `oz map` with reference passing

1. The caller writes one line: input glob, job template (an OZ packet with a `{file}` slot; Astra owns the wire),
   checks, output path. The host expands, packs up to 64 per call, checks each job, retries only failures, and
   prints one receipt line: verified count, failed IDs, calls, billed tokens, path.
2. `--from results.jsonl` chains stages on the artifact. G2 failed because the caller read the artifact; here only
   the final receipt reaches it.
3. `--width 4` runs four packed calls at once over the existing leases.
4. Zero setup: the adapter defaults to `claude -p` or `codex exec` on PATH; a stdlib stdio MCP server exposes the
   same `oz_map` tool to Claude Code and Codex with one config line.

```
oz map 'refs/*.txt' --ask extract_alloy.oz --check schema,sum100 --width 4 --out alloys.jsonl
oz map --from alloys.jsonl --ask classify_family.oz --check enum --out families.jsonl
```

Python: `oz.map("refs/*.txt", ask="extract_alloy.oz", check=["schema"])`. In Claude Code, one CLAUDE.md line: "for
many similar jobs, call oz_map instead of spawning subagents".

## 4. Expected gain (guesses unless cited)

1. Worker tokens stay near 91.6 (measured); parallelism does not lower them.
2. Caller tokens become a constant, guess 5k to 15k per session. End to end, guess 170 to 320 per verified job at
   N=64 and under 150 at N=256: well under arm K and subagent-per-job, but maybe not under J at 64. The bet is that J
   degrades at N=256 (long reply, context reread, position errors).
3. Wall time: guess 25 to 40 s at N=256 with width 4 versus about 80 s sequential. Jobs per minute: about 192
   measured for one call; guess 400 to 600 at width 4 if CLI rate limits allow.

## 5. Smallest preregistrable experiment

Arms: S (Claude Code caller, one subagent per job), J (inline), M (`oz map`, width 1), M4 (width 4). Sonnet 5.5
caller and worker, fresh workspaces, three seeds.

Workloads:
1. Materials extraction (rule-shaped, existing oracle), N=64 and 256.
2. BoolQ dev, fixed-seed sample, gold labels, exact match (public, not rule-shaped), N=64 and 256.
3. bench/codereview fixtures with host-run witnesses (fuzzy), N=16.

S runs only at N=16 on workload 1 (about 127k tokens per run at the measured 7,931).

Metrics: caller plus worker billed tokens per verified job; caller tokens versus N (the mechanism); caller turns;
wall time; jobs per minute; per-position error on BoolQ.

Kill criteria, frozen in advance:
1. M caller tokens grow more than 25% from N=64 to N=256: the constant-cost claim dies.
2. J at N=256 is all-correct and cheaper than M on two of three paired seeds on workloads 1 and 2: the token claim
   dies; `oz map` survives only as ergonomics.
3. M is not at least 5x cheaper than S at N=16 on all three seeds: the headline dies.

Budget: about 200 CLI calls (my unsized count). One-seed sizing pilot first; hard abort at 55% Claude weekly.
Codex is not used for runs.

## 6. Headline and strongest critic

Headline: "Replace 64 Claude Code subagents with one line: same verified answers, a fraction of the billed tokens,
and the orchestrator's cost does not grow with the number of jobs."

Critic: "Subagent-per-job is a straw man, and your own data says answering inline is cheaper. You built `xargs` for
prompts." The N=256 cell answers it. If J holds up there, we say so.
