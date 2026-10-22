I ran the same 64 small materials jobs on Claude Sonnet 5.5 four ways and counted every billed token.

One subagent per job: 7,931 tokens per verified job, 105 seconds for the batch. One AKOR call with all 64 jobs: 91.6 tokens per verified job, 20 seconds, and 192 of 192 jobs correct across 3 seeds (the subagents got 188).

Most of that gap is not the language. It comes from running one agent or one call per job instead of one batched call. The fair comparison for AKOR is the same batched call in plain JSON, and there AKOR's own format saves about 39% (91.6 vs 151.1). At 16 jobs the saving was smaller, 10% to 18% depending on the model.

Limits: one task family, 3 seeds, strict deterministic checkers.

The plan was written before the first counted call, and the raw data is in the repo.

github.com/canerganis/akor

#LLM #AIEngineering
