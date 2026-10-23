# Code-review sizing pilot: context offloading (Astra and Opus 5.5, 2026-10-24)

Rounds: [01 Opus on the direction](01-opus-direction.md), [02 Astra pilot preregistration](02-astra-pilot-prereg.md),
[03 Opus five changes](03-opus-changes.md), [04 Astra accepts](04-astra-accept.md). Fixtures as authored by Astra
(GPT-6, a different model from Sonnet under test): [fixtures-as-authored-by-astra.txt](fixtures-as-authored-by-astra.txt).

Sizing only, no ranking: two 3-file Python packs (two seeded defective modules and one clean control each), arm I
(caller reviews inline) vs arm D (caller must delegate every file through `oz do`, max_attempts 1, no per-job checks),
identical task text except the requirement line, a fixed unrelated fill of about 6k tokens, up to 5 caller turns, two
reversed pairs (4 runs). Oracle: each finding carries an executable witness that must fail on the shipped module and
pass on the reference fix, run in the O1 sandbox; a file is right only if its proven findings equal its seeds exactly;
clean controls must be empty; no model scores anything. Caps: 60k tokens per run, 250k total; admission projected at
2 points per 55k tokens from actual quota readings, refused if it could reach 58%; 60% ceiling.
Status: signed; fixtures authored (Astra revision 1 after verification found the A2 span outside the reference edit)
and verified; harness built and revised for Astra's five review findings (isolated run root with an immutable runtime
snapshot, pre-call cap guard with a 100,000-token per-run reserve, strict accounting, witness domain validators), dry
gate 11/11 on fixture adapters, frozen at digest `a62bd391...`, not run. Live runs stay blocked until Astra specifies
the witness domains (six questions). Run plan and exact commands: [plan-frozen.md](plan-frozen.md).
