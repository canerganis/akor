# Research note (Luna, gpt-6-luna, web search)

## 1. Reusable program, rule and plan generation

- **GenCache (NeurIPS 2025):** An LLM generates a Python program from prompts with similar structure; the program produces the answer for later prompts without a model call. It validates with example prompts and also with ValidLLM, and falls back to the LLM if the prompt structure fails a regex check or the cache misses. On synthetic prompts, token savings of at least 35% per request, and 73% in some settings, are reported. [Paper PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2025/09/GenCache_NeurIPS25.pdf) [Savings results](https://www.microsoft.com/en-us/research/wp-content/uploads/2025/09/GenCache_NeurIPS25.pdf)

- **Test-Time Plan Caching (2025):** Extracts structured plan templates from completed agent executions; on a match, a small model adapts the plan to the context, and if there is no match the large planner steps in. On two data-intensive reasoning tests, average cost drops by 46.62%, while application performance is reported as 96.67% of the best baseline; the output was evaluated with a GPT-4o judge. This method reuses the plan; it does not run the job without a model call. [Paper and results](https://arxiv.org/abs/2506.14852)

- **MiniCache (July 2026):** Converts Program-of-Thought programs into parameterized cache objects; on a cache hit, a small model extracts the variables. Up to 3.1× lower latency and 2.8× higher throughput are reported on WebShop, Formula and CodeTAT-QA. This is not fully model-free: the small model also runs on the hit path. The accuracy check and the conditions for falling back to the target model are not described in the abstract, so this is **UNVERIFIED**. [Paper abstract](https://arxiv.org/abs/2607.20507)

- **Inference:** WebRuleBench is an open benchmark that generates a CSS/XPath/regex rule from one page layout example, runs the rule on other pages without an LLM, and measures accuracy/generalization against human-labeled results. However, the page I reviewed is not a results paper; the savings measurement and the fall-back-to-model behavior on production failure are **UNVERIFIED**. [Project and method](https://github.com/erdincuzun/WebRuleBench)

## 2. Agent orchestration: measurements and automatic batching

- **Published comparisons:** AgentRace measures per-task tokens and latency across LangChain, AutoGen, CrewAI and other frameworks; for example, on HumanEval repeats AutoGen used about 0.9 thousand total tokens, LangChain 7.5 to 8.8 thousand, and CrewAI 10.9 to 11.7 thousand. This work is a paper with anonymous authors; since different agent strategies and tool behaviors affect the comparison, the numbers should not be read as "fixed framework overhead". [Paper PDF](https://agent-race.github.io/AgentRace.pdf)

- **Official SDK/protocol behavior:** The OpenAI Agents SDK leaves parallel agent execution in code (e.g. `asyncio.gather`) to the developer; it does not promise automatic cross-agent batching for multiple independent model inputs. LangChain's model `.batch()` call also parallelizes independent model requests. The JSON-RPC batch standard allows multiple RPC messages in one request; this is not the same as grouping LLM jobs into a single model call. [OpenAI orchestration guide](https://openai.github.io/openai-agents-python/multi_agent/) [LangChain batch guide](https://docs.langchain.com/oss/python/langchain/models) [JSON-RPC batch](https://www.jsonrpc.org/specification#batch)

- **Claude Agent SDK, A2A and MCP:** Claude's multi-agent documentation describes parallel agent sessions with separate contexts; it offers no per-task token comparison. A2A is the standard for agent-to-agent communication, MCP the standard for application/tool and data communication; on their own they do not prove measured token savings or automatic job batching. **UNVERIFIED:** I found no comparable, published per-task token/latency measurement for these three. [Claude multi-agent](https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration) [A2A/MCP distinction](https://www.axios.com/2026/08/17/a2a-agentic-ai-foundation-open-ai-standards)

## 3. Post-2026 work combining the four features

**UNVERIFIED:** I found no work published after mid-2026 that I could verify as offering, together, a cross-agent job queue, batch processing, per-job verification and compiling repeated work into a program with no model call. Close pieces exist: GenCache program generation/validation/fallback; the plan-cache work on agent workflows; MiniCache's reusable program cache. But none of them shows all four features together in its sources. [GenCache](https://www.microsoft.com/en-us/research/wp-content/uploads/2025/09/GenCache_NeurIPS25.pdf) [Plan caching](https://arxiv.org/abs/2506.14852) [MiniCache](https://arxiv.org/abs/2607.20507)

## Gaps nobody covers

- Discovering and compiling repeated job classes in a **cross-agent queue**.
- Reporting the correctness and fallback outcome of **every job** in a batch separately.
- Defining, with formal bounds, the inputs on which compiled programs are safely valid.
- Experimentally separating the gain from batching from the gain from program compilation on the same job set.
