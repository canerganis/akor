# A4.13: preparation and review call caps (2026-10-24)

Reason. A4.5 gives Astra 4, Opus 4 and Fable 4 preparation and review calls, global 114. Signing Amendment 4 already used Astra 4 of 4 and Opus 3 of 4 (review, two sign rounds). The orchestration chosen by the driver needs more review calls than that: blind acceptance tests written from A4 before the build (Sonnet), the A4.8 expressibility review (Opus), a council of three per round for up to four rounds (Astra spec lens, Opus code lens, Opus red team), deadlock escalation from round two (Fable and Astra each propose, then Astra critiques), a freeze sign-off (Astra), one runner subagent per live cell plus a diagnosis call when a cell fails, and result reviews (Astra, Opus). These calls never reach a backend under test and add nothing to any measured cell.

A4.13.1. The A4.5 preparation and review caps become Astra 20, Opus 40, Fable 4 and Sonnet 40. The Sonnet scope covers acceptance tests, test writing, live cell runners and resume calls. Evaluation caps stay at Codex 62 and Sonnet evaluation 40. The global cap is 206. These are cumulative caps from the start of the replication; counters are not reset. Amendment 4 review and signing calls, the A4.13 drafting call and the A4.13 signing calls count against the respective caps. The revision takes effect when both signatures are complete. It does not retroactively authorize earlier cap overruns.
A4.13.2. Every preparation and review call is logged with the agent, its task role and its category. A separate agent session, a resume call or a diagnosis call is counted separately when it is a new call. The result report shows actual totals per category and per agent. If the next call would exceed any cap, the workflow stops. Only signature exchanges for a new prospective revision may then take place; they are logged and counted in the new totals. No other work restarts before both signatures are complete.
A4.13.3. Preparation and review calls are reported separately from evaluation cost and enter no performance or cost computation of a measured cell. They remain subject to the call caps and to protocol compliance audit. Calls to a backend under test launched by a runner are evaluation calls and count against the evaluation caps, costs and applicable gates. A preparation or review label does not change these obligations.
A4.13.4. Baseline authentication home: C:\Users\can02\.ozmap_rep\baseline, outside the repo and outside every worker and working directory. The owner performs the A4.2 seeding `codex login` there.

Drafted by the driver; A4.13.1 to A4.13.3 are Astra A's replacement text (given in Turkish, translated by the driver, raw output in the scratchpad file a413-astra.md).

Signed: Astra A (scratchpad a413b-astra.md)
Signed: Opus B (fresh subagent, 2026-10-24)

## A4.13 revision 1 (2026-10-25)

Reason. The ledger shows Opus 37 of 40 (10 reconstructed, 27 logged), with ruling signatures, freeze, live diagnosis and result reviews still ahead.
A4.13r1.1. The Opus preparation and review cap becomes 70; Astra 20, Fable 4, Sonnet 40 unchanged; global 236. Counters stay cumulative. Effective when both signatures are complete; no retroactive authorization. Evaluation caps and gates unchanged.
A4.13r1.2. Subagents that only relay evidence packs to Astra may run on Sonnet and count as Sonnet preparation and review calls, not evaluation calls.

Astra A signed the driver draft ("Signed: Astra A", scratchpad a413r1-astra.md). Opus B gave the text above as replacement; it only clarifies the draft (exact counts, cumulative counting, effective date, no retroactive authorization, relay calls are not evaluation calls) and changes no number. Signed: Opus B (by replacement text).
