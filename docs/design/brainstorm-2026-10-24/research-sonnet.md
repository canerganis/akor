# Prior art research (Sonnet 5.5, 2026-10-24)

Figures are the authors' own unless stated. Anything not checked against a primary source is marked UNVERIFIED.

## 1. Batch prompting

- Cheng, Kasai, Yu, "Batch Prompting" (EMNLP 2023 Industry): claims up to 5x token and time savings at 6 samples per batch on Codex, across ten datasets. https://arxiv.org/abs/2301.08721
- Accuracy falls as batch size grows. A significant drop appears at batch size 6 on four of five datasets. Longer inputs degrade faster (WikiTQ). Results vary by task (GSM8K rose at b=3, then fell to 49.7 at b=6; AQuA fell from 46.1 to 42.1). https://arxiv.org/html/2301.08721
- Order and grouping: similar or diverse grouping did not beat random. The authors suspect earlier items, which have no gold outputs, propagate errors to later items. Each item carries an "[index]" so outputs can be parsed back. https://arxiv.org/html/2301.08721
- Bad answers: the paper describes no retry or validation strategy. Limits section says savings need prompts much longer than outputs and recommends piloting on a subset. https://arxiv.org/html/2301.08721
- Lin et al., BatchPrompt (Microsoft, ICLR 2024): finds quality depends on item position and order, and proposes Batch Permutation and Ensembling plus self-reflection early stopping. At batch size 32 it reports 15.7% of the LLM calls and 18.6% to 30.8% of the tokens with competitive accuracy on BoolQ, QQP, RTE. https://arxiv.org/html/2309.00384v3
- Note: BatchPrompt's ensembling spends extra votes (repeat calls with permuted order) to buy accuracy back. Tasks are three classification sets, not structured agent jobs.

## 2. Compact formats and prompt compression

- TOON: the widely quoted 30 to 60% savings come from large uniform arrays. An enterprise analysis cites 15% on semi-uniform logs and 60.7% on uniform object arrays. https://www.architectureandgovernance.com/applications-technology/token-economics-and-serialisation-strategy-evaluating-toon-for-enterprise-llm-integration/
- Independent benchmark (Matveev, arXiv 2603.03306): headings cover a "prompt tax" and a constrained decoding trade-off. A secondary summary says plain JSON had best accuracy and constrained-decoding JSON used fewest tokens on simple structures. I could not decode the PDF text, so treat the detail as UNVERIFIED. https://arxiv.org/pdf/2603.03306
- Practitioner comparisons: CSV beats TOON by about 30% on flat tables; nesting erodes the benefit; models have not seen TOON in training so examples add overhead. https://thenote.app/post/en/toon-vs-json-a-reality-check-when-it-saves-tokens-and-when-it-doesnt-asr52ih4iq (blog, UNVERIFIED claims)
- LLMLingua: up to 20x compression with a 1.5 point drop on GSM8K, BBH, ShareGPT, Arxiv-March23. https://arxiv.org/abs/2310.05736
- LongLLMLingua: 17.1% gain at 4x on long-context QA (project page). https://www.microsoft.com/en-us/research/project/llmlingua/
- LLMLingua-2: BERT-level token classifier distilled from GPT-4; 3x to 6x faster than LLMLingua. https://arxiv.org/abs/2403.12968
- Gap: I found no benchmark of these compressors on agent job payloads or tool outputs. Compression is lossy and unvalidated; it targets context, not output tokens.

## 3. Routing and cascades

- FrugalGPT (Chen, Zaharia, Zou): cascade matches GPT-4 with up to 98% cost reduction, or +4% accuracy at equal cost. Best case on selected tasks. https://arxiv.org/abs/2305.05176
- RouteLLM (Ong et al., ICLR 2025): abstract says routers cut cost "by over 2x" in cases without quality loss, using human preference data. https://arxiv.org/abs/2406.18665 . A secondary source claims over 85% on MT-Bench at 95% of GPT-4 quality (UNVERIFIED): https://neuraltrust.ai/es/blog/llm-model-routing
- Both route between models for open-ended queries. Neither routes around the model for deterministic work.

## 4. Provider features

- Anthropic Message Batches: 50% of standard price, asynchronous, each request handled independently, most batches finish under 1 hour. https://platform.claude.com/docs/en/build-with-claude/batch-processing
- Anthropic prompt caching: write 1.25x (5 min) or 2x (1 h); read 0.1x, or 0.05x on Opus 5.5 and Sonnet 5.5; minimum 512 tokens on Sonnet 5.5. Stacks with batch discount. Does not reduce output tokens or output speed; uncached tokens bill in full. https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- OpenAI Batch: 50% off, 24h window (often faster), up to 50,000 requests or 200 MB per batch. https://developers.openai.com/api/docs/guides/batch
- OpenAI prompt caching: automatic above 1,024 tokens; cookbook cites up to 80% latency cut on prompts over 10,000 tokens; discount was 50% at launch, larger on newer models (UNVERIFIED). https://developers.openai.com/cookbook/examples/prompt_caching101
- What they do not reduce: one request per job still pays per-call output framing and a separate response. Batch APIs add latency, not fewer calls. Caching reduces only repeated prefix input. None validates answers or retries selectively.

## 5. Agent communication languages and token-efficient protocols

- EcoLANG (EMNLP 2025 Findings): induces a concise language for agents in social simulation. Source via ACL Anthology listing (UNVERIFIED details): https://aclanthology.org/people/ling-yan
- Beyond Natural Language (2024): letting LLMs choose a structured format cut multi-agent tokens by up to 72.7% with effectiveness maintained. Best case. https://arxiv.org/abs/2402.18439
- Cut the Crap (2024), AgentDropout (2025), SafeSieve (2025): prune agents or links to save tokens. https://arxiv.org/pdf/2410.02506 , https://papers.cool/arxiv/2503.18891
- DALA (arXiv 2511.13193): agents bid for speaking turns by message value. https://arxiv.org/abs/2511.13193
- Machine-language tokens (arXiv 2507.21454): learned embedding-level protocol for wireless links. https://arxiv.org/html/2507.21454v1
- Most of these shrink dialogue between chatting agents. I found no project that queues, packs, validates and retries jobs on a stock API. MCP and A2A were not searched (UNVERIFIED either way).

## Weak points of prior work AKOR could beat

- Accuracy falls with batch size (significant at 6, Cheng et al.), yet AKOR packs 64. Publish an accuracy curve to 64 with per-position error rates. https://arxiv.org/html/2301.08721
- Position effects are known but only mitigated by costly ensembling (BatchPrompt). AKOR can shuffle or position-balance retries without extra full votes. https://arxiv.org/html/2309.00384v3
- No batch-prompting paper handles one bad answer. Host validation plus retry of only failed jobs is a clear gap. https://arxiv.org/html/2301.08721
- Benchmarks are classification sets, not agent jobs. A structured agent-job benchmark with billed tokens per verified job is novel.
- TOON savings shrink on small, nested or short prompts and add a prompt tax. Measure format cost net of the teaching overhead. https://arxiv.org/pdf/2603.03306
- Compressors (LLMLingua) are lossy, unvalidated, and untested on agent payloads; AKOR's compact format is lossless and checked.
- Routers and cascades choose between models; none skips the model for reads and tests. https://arxiv.org/abs/2305.05176
- Batch and cache discounts leave per-call count and output tokens untouched; Message Batches adds delay. Packing cuts calls and works at low latency, and stacks with caching. https://platform.claude.com/docs/en/build-with-claude/prompt-caching
