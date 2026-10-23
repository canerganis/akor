# Research brief for Luna (gpt-6-luna, web search on)

Context: AKOR is an open-source runtime for agent-to-agent work on Claude through `claude -p`. Measured (preregistered,
billed tokens, 64 small structured jobs, Claude Sonnet 5.5): one plain JSON call per job 2,834 tokens per verified job,
one subagent per job 7,931, one batched plain JSON call 151, one AKOR call 91.6. Most of that gap is batching.
We want the next version to be clearly different from prior work, so critics cannot say "this is just batch prompting".

Research question (use live web search, prefer 2025 and 2026 sources, give a URL for every claim):

1. Systems where an LLM writes a reusable program, rule set, parser or DSL once, and a host then executes it on many
   inputs without calling the model (program synthesis for data tasks, "LLM as compiler", distillation of prompts into
   code, rule induction, regex/extractor synthesis, cached plans, agent workflow memoization, "plan caching").
   For each: what it does, measured savings, how it verifies correctness, how it falls back to the model.
2. Token and latency overhead of multi-agent orchestration frameworks (LangGraph, CrewAI, AutoGen/AG2, OpenAI Agents
   SDK, Claude Agent SDK subagents, Google A2A, MCP). Any published measurements of tokens per task, and any
   framework that batches work across agents automatically.
3. Anything published after mid-2026 that already combines: cross-agent job queue, batching, per-job verification,
   and compiling repeated work into model-free code.

Output: a Markdown report, at most 900 words, sections 1 to 3, then "Gaps nobody covers" (3 to 6 bullets). Mark
anything you could not verify with a source as UNVERIFIED. Do not invent papers or numbers.
