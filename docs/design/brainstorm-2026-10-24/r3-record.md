
---
# Round 3, task for Astra A (high effort): write the joint decision record

Above: the pack, all round 2 texts, Astra B's binding decisions (03-astra-B-decisions) and Opus A's reuse map
(03-opus-A-reuse). Write the joint record that Astra and Opus will sign. English, at most 1,000 words, no dashes as
punctuation. Sections:
1. Decision in three sentences (what we build, what is claimed new and what is not, citing GenCache, 2607.13407,
   Sema, DocETL, LOTUS honestly).
2. Design: `oz map` surface, guarded whole-job rules, admission, audits, pooling; what reuses existing code and what
   is new (from the reuse map; reuse only where it genuinely fits, as the owner asked).
3. Kill pilot protocol, frozen parameters.
4. Resolve this new issue explicitly: Opus A found a recorded Codex call with 28,652 input tokens, so the Codex
   fixed call cost may be about ten times Claude's ~2,400. A pilot on `codex exec` would then inflate the value of
   eliminating calls and would not transfer to Sonnet. Also BoolQ cannot adopt a rule because `adopt_memo` needs a
   job-bound check. Decide: keep codex, switch to Sonnet within the 60% Claude cap (46% now; one 64-job Sonnet call
   is about 6k tokens), or run the decisive cells on Sonnet and the rest on codex. Give the budget.
5. Build order (from the reuse map), each step testable without model calls.
6. Ordered kill criteria and the headline we may publish only if the pilot passes.
7. Disagreements that remain, with who holds which view.
