# Semantic operator systems vs AKOR (research, 2026-10-24)

Figures are the authors' own claims from abstracts or papers. Anything I could not confirm is marked UNVERIFIED.

## LOTUS (Stanford/Berkeley)
- Authors: Patel, Jha, Guestrin, Zaharia. Paper: https://arxiv.org/html/2407.11418v3 (VLDB 2025: https://www.vldb.org/pvldb/vol18/p4171-patel.pdf).
- User writes: Pandas-style DataFrame calls with semantic operators (filter, join, map, group-by, top-k) and natural-language criteria.
- Batching rows per call: no. The paper says rows are processed independently; vLLM serves requests at batch size 64 for throughput. Aggregation is the exception (hierarchical reduce packs several tuples per prompt).
- Verification per output: no. Guarantees are statistical, at operator level: a cheap proxy (small LLM or embeddings) plus an oracle LLM, with thresholds learned from sampled oracle labels, targeting recall/precision with probability 1-delta.
- Compiles to model-free code: no. Code synthesis appears only as related work/future work.
- Savings: up to 1,000x speedup over gold algorithms; about 1,000x fewer LLM calls on a BioDEX join; fact-checking 91.0% accuracy in 190 s vs FacTool 80.9% in 5,396 s (about 28x).
- Target: data pipelines over tables.

## DocETL (Berkeley)
- Authors: Shankar, Chambers, Shah, Parameswaran, Wu. Paper: https://arxiv.org/abs/2410.12189v3. Docs: https://ucbepic.github.io/docetl/concepts/operators/.
- User writes: a declarative pipeline of operators (Map, Reduce, Filter, Resolve, Equijoin, Rank, Extract, Cluster, plus Split, Gather, Unnest, Sample, TopK, Code).
- Batching rows per call: no evidence. Docs say operations run in parallel via multithreading. Batch-in-prompt behaviour not confirmed (UNVERIFIED).
- Verification: yes, per output. An operator can carry a `validate` field of Python assertions with `num_retries_on_validate_failure`, plus "gleaning" (LLM validator, regenerate with feedback; docs warn it at least doubles LLM calls). The optimizer also uses agent-generated validation prompts to judge plans.
- Model-free code: a `Code` operator exists for user-written Python. The system does not generate it from a model (UNVERIFIED beyond the docs page).
- Savings: the goal is accuracy, not cost. 25 to 80% more accurate than baselines (arXiv v3 abstract; VLDB listing says 21 to 80%: https://vldb.org/pvldb/volumes/18/paper/DocETL%3A%20Agentic%20Query%20Rewriting%20and%20Evaluation%20for%20Complex%20Document%20Processing). Follow-up MOAR adds cost: 27% higher accuracy than Abacus, matching its best accuracy at 55% of cost (https://arxiv.org/abs/2512.02289v2).
- Target: document-processing data pipelines.

## Palimpzest (MIT)
- Authors: Liu, Russo, Cafarella and others. Paper: https://arxiv.org/abs/2405.14696v2 (CIDR 2025: https://mail.vldb.org/cidrdb/papers/2025/p12-liu.pdf).
- User writes: a declarative program over unstructured data collections.
- Batching rows per call: not stated in the abstract. UNVERIFIED.
- Verification: not described per output. The optimizer samples to estimate quality.
- Model-free code: the abstract does not mention code synthesis. I recall earlier versions having a code-synthesis option, but could not confirm (UNVERIFIED).
- Savings: one plan 3.3x faster and 2.9x cheaper than baseline; with parallelism up to 90.3x speedup at 9.1x lower cost vs single-threaded GPT-4, F1 within 83.5% of it.
- Target: data pipelines.

## Close relatives
- Abacus (inside Palimpzest): cost-based optimizer, objective like "max quality under cost cap". Options: model selection, mixture-of-agents, reduced context, critique-and-refine, filter reordering. Paper describes no code synthesis and no multi-row request batching. Claims 18.7 to 39.2% better quality, up to 23.6x lower cost and 4.2x lower latency than the next best (BioDEX: $0.80 vs $18.9 for LOTUS). https://arxiv.org/html/2505.14661v2
- Compilation-based execution of semantic operators (Dong, Wang, July 2026, vision paper): LLM called once at compile time to turn a filter/map/join spec into deterministic local code. Reports reduced time and LLM calls, no numbers on the abstract page; quality loss is acknowledged as approximation; verification and batching not described. https://arxiv.org/abs/2607.13407
- Sema (March 2026): SemaSQL on DuckDB, adaptive execution with operator reordering, fusion and prompt batching; 2 to 10x faster than three baselines, details of batching and quality metrics not on abstract page. https://arxiv.org/abs/2603.11622
- Semantic join batching (Trummer, Oct 2025): packs row blocks from both tables into one prompt, sized to context window. https://arxiv.org/pdf/2510.08489
- Continuous Prompts (Dec 2025): batching as stream operator optimization, notes quality loss as batch grows. https://arxiv.org/pdf/2512.03389
- NOVAS26 workshop paper: optimal in-prompt batch size, claims up to 14x lower operator latency. https://www.vldb.org/2026/Workshops/VLDB-Workshops-2026/NOVAS/NOVAS26_23.pdf (only seen via search summary; UNVERIFIED in detail).
- ELT-Bench-style systems: not found as a distinct optimizer. UNVERIFIED.
- None of the above targets agent-to-agent orchestration. All are data-pipeline systems.

## What remains new for AKOR
- Multi-agent job queue as the input: jobs arrive from several independent agents, not from one user's dataset or query.
- Packing up to 64 heterogeneous jobs per call as a first-class runtime feature. LOTUS does not batch rows in a prompt, and the batching papers target homogeneous rows of one operator.
- Host-side check of every individual answer, with retry limited to failed jobs. LOTUS and Palimpzest give statistical or sampled guarantees; only DocETL validates per output, per operator, with full-operator retries (retry granularity UNVERIFIED).
- Chained stages (`oz map`) with host-side verification between stages, as a one-line command rather than a Python or YAML pipeline.
- "Compile once" as an agent-facing rule the host runs, with checks gating it. The 2026 compilation paper is closest, but it is a vision paper with no verification story.
- Amortized token accounting across calls (teach once, later calls cheaper) is not a metric in these systems.
