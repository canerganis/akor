# Step 3: a cheaper worker (Haiku 5.5) on repair-handoff-20 (Astra and Opus 5.5, 2026-10-23; owner approved step 3)

Rounds: [01 Astra preregistration](01-astra-prereg.md), [02 Opus: five changes](02-opus-changes.md),
[03 Astra accepts](03-astra-accept.md).

One Haiku 5.5 suite of O1's five scenarios at a derived freeze from 088815db that changes only `route.model` and
`route.alias_map`. Control: the archived Sonnet O1 live result (all five pass, 55,413 tokens, 190 s) only if zero-call
checks show it still matches at HEAD (core packet digests ed27d59c and 3fb652d8 under H d941a86d, adapter digests from
the archived cores or a written diff review, same adapter digest, effort, parser, wire and accounting scope, CLI
2.1.306); otherwise a matched Sonnet rerun is preregistered first. Gate: pass_g3c on every scenario, then fewer
whole-suite billed tokens, then lower elapsed time. Sizes 4 and 1 stay experimental (checked with model
claude-haiku-5-5). Allocation 150,000 tokens, 18 launches, 8 per scenario. Quota read before (start only below 45%)
and after; 46% mid-suite stops it as incomplete; 49% hard stop. A pass supports this frozen use case only.
[Frozen plan with the derived digest, control-match results, label check, dry result and the live command](plan-frozen.md).
Status: signed; derived freeze 8ec891e7 built from 088815db (route.model and route.alias_map only, no pinned file
edited); all twelve control-match items MATCH; sizes 4 and 1 label experimental under claude-haiku-5-5; derived dry
gate passes; the paid suite has not been run.
