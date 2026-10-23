**Binding decision: run a 32-call, single-seed kill pilot. Freeze the following protocol before execution.**

1. **Runner: `codex exec` only.** Pin model, reasoning setting and CLI version across arms.  
   Changing backend does not confound a comparison when every arm uses that backend; it limits transfer to Sonnet.  
   Preserve Claude quota. Sonnet confirmation requires a later preregistration; this pilot cannot establish improvement over the historical 91.6-token result.

2. **Compilation: fuse one “rule or none” slot into the bootstrap batch; prohibit revision.**  
   This gives learning a chance to decline cheaply on BoolQ, although its prompt and reasoning overhead must still be measured.  
   A “revise” slot violates the no-repair constraint and introduces adaptive search. Audit failure quarantines the artifact; subsequent jobs use ordinary fallback.

3. **Admission: 64 independently labeled cases per workload, hidden from synthesis.** Use 48 representative cases and 16 predetermined challenge cases; require zero errors among covered cases and coverage of at least 32 cases. Otherwise reject the rule.  
   Model agreement can reproduce shared mistakes; independent labels test the proposed transformation against something external.  
   This is a bounded admission screen, not certification. Evaluation gold remains offline; report human labeling effort and charge model-assisted preparation.

4. **Audit: 32 covered jobs per rule per run, or all covered jobs if fewer; always blind.** Freeze uniform seeded selection and use identical audit IDs in B and C.  
   This offers stronger detection than roughly twelve audits over 192 later jobs; unused batch capacity is not free reasoning.  
   Do not taper during this pilot. Agreement with an auditing model cannot establish a gold-error confidence bound; disagreement quarantines future reuse without erasing emitted errors.

5. **Pooling: all eligible residuals sharing contract, check, permission and worker hashes.** Flush at 64 records or a frozen one-second deadline.  
   “Under 64” describes where pooling helps, not a separate eligibility condition: full batches dispatch immediately and compatible tails combine.  
   Preserve producer identity and consumer acceptance; include queue waiting in makespan.

6. **Budget and arms: 32 physical calls maximum, one seed, three arms, width four throughout.** A: ordinary pooled `oz map`; B: rules with producer-local fallback; C: identical rules with pooled fallback.

   Use 256 fresh materials jobs and 256 frozen BoolQ jobs. Four scripted producers each submit 64 jobs simultaneously. For each workload, the shared candidate bootstrap answers 16 jobs per producer and proposes one rule; the remaining 192 jobs exercise reuse. Charge the bootstrap’s full tokens and elapsed time independently to B and C. Run their residuals separately; disable exact-result memoization.

   Allocation: one telemetry call, two bootstrap calls, eight A calls, at most eight B residual calls, six C residual calls, seven failure/retry slots. No model-assisted setup outside this ceiling.

   Width four prevents a serial baseline from manufacturing a speed win; shared bootstrap isolates pooling using the same artifact.  
   One seed can kill this design economically; passing warrants replication, not a general performance headline.

7. **Ordered kill criteria:**
   - **Safety:** any incorrect rule-origin materials answer released as accepted kills admission, whether audited or not.
   - **Validity:** missing inclusive usage, hidden-reasoning accounting, leakage or budget overrun makes efficiency **unvalidated**.
   - **Materials:** C must preserve gold correctness, reduce cold tokens/correct-job by ≥25%, and cold makespan by ≥10% versus A.
   - **BoolQ:** C must introduce no additional gold errors and stay within 10% cold token and time overhead versus A.
   - **Pooling:** C must use fewer tokens than B without worse correctness or makespan; otherwise drop pooling from the claimed contribution.

