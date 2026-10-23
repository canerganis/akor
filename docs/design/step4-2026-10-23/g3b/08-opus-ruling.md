# G3b build deviations: Opus 5.5

1. **ACCEPT the rule, REJECT the stated consequence.** My signed intent was "the sequence the frozen policy
   produces". The unchanged executor packs the largest size that fits (`oz_do.py`, lines 455 to 467). The oracle's
   own `plan_sizes` in `g3b.py` encodes that: size 4 for |R| = 4, singletons for |R| < 4. The oracle reimplements
   it independently rather than importing it, so it stays independent. "One singleton per rejected member" was my
   mis-statement of that policy.

   Two corrections must go into the record:

   1. **The worst-case claim is false.** "Realistic worst case per cold scenario is 6 launches, the 23-launch
      estimate is unreachable" does not hold. With sizes (4, 1) and two attempts, a size-4 stage with |R| = 3 costs
      1 + 3 launches. The policy's worst case is therefore 12 for clean, 12 for interrupt and 16 for stale (above
      the per-flow cap of 10). The caps bind before the policy does, and exhaustion is no pass. This must not appear
      in any record; `plan-frozen.md` does not currently contain it.
   2. **Size-4 recovery is not singleton recovery.** When |R| = 4, recovery reruns the experimental size-4
      composition, not the qualified singleton cell. The text "singleton recovery under the qualified cell" holds
      only for |R| < 4, and `plan-frozen.md` should say so in one sentence.

   `g3b/README.md` line 10 still says "one singleton resend per rejected member". Change it to match
   `plan-frozen.md` ("in packets of the largest allowed size that fits: singletons while |R| < 4, one size-4
   packet when |R| = 4").
2. **ACCEPT.** "Order after the mutation equals the oracle's derived order" is what I signed in round 2. The other
   C3 checks stay: no old A bytes after the mutation, B/C/D reused on identical inputs, and the delivery cites A
   revision 2.
3. **ACCEPT.** This keeps live1's frozen bytes intact. `step4.py`'s `allocation()` reads `g3b.json`. Keep a test
   asserting that no G3b path reads `workflow.json` `budgets.executor`.
4. **ACCEPT.** This is exactly the one-binding-label rule we signed.
5. **ACCEPT.** It implements "one fresh suite, no reruns, no new baseline allocation".
6. **ACCEPT.** This is arithmetic: 22 × 2.7k plus the 5k reserve is about 64k. `plan-frozen.md` already states it,
   and exhaustion is no pass.
7. **ACCEPT.** Both checks are in the signed gate, as items 2 and "exhausted attempts mean no pass".
