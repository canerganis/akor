# O1 G3c live result: pass

`repair-handoff-20/v1`, freeze 32333561 (executor at 50e8ef5, G0 granted by Opus, fix review approved by Astra), fresh
workspace, one suite, Sonnet 5.5 through `claude -p`, CLI 2.1.306, selective profile, sizes 4 and 1 as experimental.
Evidence: `bench/o1/live1/` (report, all 56 candidates, call ledgers, delivered packages).

| Scenario | Launches | Packets | Memo hits | Delivered and verified on A, I and H | pass_g3c |
|---|---:|---|---:|---|---|
| clean | 2 | 4, 4 | 0 | yes | yes, strict |
| exact repeat | 0 | none | 8 | yes | yes |
| interrupted, two hard kills | 2 | 4, 4 | 0 | yes | yes, strict |
| stale ticket A (revision 2 after node 16) | 4 | 4, 4, 1, 1 | 6 | yes | yes, strict |
| identical-byte revision bump | 0 | none | 16 | yes | yes |

Totals: 8 launches, 55,413 tokens (cap 150,000; preregistered estimate 56,860 at 2,000 hidden-reasoning tokens per
call), accounting complete, 190 s for the suite. Every model job was accepted on its first attempt: 56 candidates,
all accepted; no resend, no wire failure, no check false accept or false reject; every delivered function is
byte-identical to an accepted candidate and passes the per-job tier A, the integration tier I and the evaluator-only
exhaustive tier H against two agreeing references.

Hidden reasoning per call: 133 to 1,186 thinking tokens (size-4 core and adapter packets 584 to 1,186; the stale
singletons 133 and 446). Unlike the boundary classification in step 4, every code-repair call reasoned.

What this establishes: the step 4 executor, on a workflow whose model jobs genuinely need a model (writing function
bodies to repair seeded defects), delivered verified packages under clean runs, an exact repeat, two hard kills, a
stale input and an identical-byte revision, with exact traces, memo reuse at 0 model tokens and complete accounting.
That meets the owner's real-workflow criterion (O1) for this workload, within its stated scope: seeded defects rather
than real bug reports, one model, one suite, sizes 4 and 1 unqualified.
