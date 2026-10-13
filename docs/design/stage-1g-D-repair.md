# Stage 1g, stage D repair (frozen 2026-10-13)

Joint decision: documented re-measurement of 1g's defective cells (Astra round 2, Fable round 2 on stage D). H text, parser, goal lines, gates unchanged.
Audit rule (Fable): every expected result must follow from the op text plus the listed refs with no outside knowledge.
Arithmetic on numbers written in the op text counts as following from the op text; facts about the world do not.

## Audit of all five packets (no calls)

Defective (needs a fact outside the op text and refs):
- P1 op 4, months with more than 31 days (passed on all models, defective all the same)
- P2 op 0 days in a week, op 1 is 91 prime (arithmetic, but the number property is not stated; refused), op 2 symbol of sodium
- P3 op 0 days of jan/feb/mar, op 1 primes below 10 and evens (refused)
- P4 op 1 first three letters of the alphabet (also ambiguous letter case; passed)
Kept: P1 op 3 (integers strictly between 7 and 8: arithmetic on the op text), P4 op 0 (multiplication table of numbers in the op text), all of P5 (each op states its data or condition and its code).

## Replacement op texts (expected values, data, seeds and job IDs unchanged; only these texts change)

P1 op 4
- old: List the English month names that have more than 31 days, as a JSON array of strings.
- new: From the JSON array [["jan",31],["feb",28],["mar",31]] of [month, days] pairs, return the months whose days exceed 31, as a JSON array of strings.
- expected: []

P2 op 0
- old: Return the number of days in a week as a JSON integer.
- new: Return the number of elements of the JSON array [1,2,3,4,5,6,7], as a JSON integer.
- expected: 7

P2 op 1
- old: Return true if 91 is a prime number, otherwise false, as a JSON boolean.
- new: Return false if 7 times 13 equals 91, otherwise true, as a JSON boolean.
- expected: false

P2 op 2
- old: Return the chemical symbol of sodium as a JSON string.
- new: Return the first two characters of the string "Natrium", as a JSON string.
- expected: "Na"

P3 op 0
- old: Return a JSON object that maps "jan", "feb" and "mar" to their numbers of days in a non-leap year, as integers.
- new: Return a JSON object that maps "jan", "feb" and "mar" to the integers 31, 28 and 31 respectively.
- expected: {"jan": 31, "feb": 28, "mar": 31}

P3 op 1
- old: Return a JSON object whose key "primes" is the number of primes below 10 and whose key "evens" is the number of even integers from 1 to 10, both as integers.
- new: Of the integers 1 to 10 inclusive, return a JSON object whose key "primes" is how many of them are in the list [2,3,5,7] and whose key "evens" is how many of them are even, both as integers.
- expected: {"primes": 4, "evens": 5}

P4 op 1
- old: Return a JSON array of [letter, position] pairs for the first three letters of the English alphabet, in order, positions starting at 1.
- new: Return a JSON array of [character, position] pairs for the characters of the string "abc", in order, positions starting at 1.
- expected: [["a", 1], ["b", 2], ["c", 3]]

## Calls

Changed packets P1, P2, P3, P4 re-run on Sonnet 5.5, Haiku 5.5, Fable 5.1 (12 calls), then Luna medium from a regenerated kit: 5 std (2005-2009) + 5 hetero (10 calls, owner). Total 22.
Inherited, labelled inherited: stage A (20 H + 5 baseline), Sonnet P5 from stage B, Haiku and Fable P5 from stage D, D standard cells (Haiku 10, Fable 5, Sonnet-32 5).
Gates: B 5/5 on Sonnet (P5 inherited + 4 new); D 40/40 (20 standard inherited + Haiku and Fable P5 inherited + 8 new + Luna 10). Stop at the first invalid reply or wrong job; no extra attempts this round, no switch to G. All pass: adopt H.

## Approvals

- Fable: every op APPROVE, P3 op 1 with "inclusive" added; audit misses none; plan APPROVE (22 calls). Verified locally that rev 2 differs from rev 1 only in the listed op texts.
- Astra: every op APPROVE; plan APPROVE, order Sonnet P1-P4, Haiku P1-P4, Fable P1-P4, then Luna 10 from the regenerated kit; this is a separate qualification run, the original 1g qualification stays failed. Astra then ACCEPTED Fable's "inclusive" text, which is the frozen text above.
- Spec note (Astra's wording, separate from the test): a refs-only goal requires missing_data when a needed external fact is in neither the op nor the refs; whether a zero-ref op may use model knowledge is decided by the goal.

Runner: PACKETS=1,2,3,4 STOP=1 ARM=H python bench/live/run1g_b.py per model. Luna: bench/codex_kit_1g regenerated from rev 2 (oracles unchanged).
