# Sizing pilot preregistration: Opus 5.5

**SIGN with five changes.** The scope (pilot only, no ranking), fixtures, oracle, measurements, the 250k cap and the
quota admission rule are right.

1. **The turn cap biases against arm I, and the per-run cap cannot hold three turns at a 12k fill.**
   1. Arm I must read three files by path. If it reads one per turn, that is four turns with the answer, so a
      three-turn cap truncates I while D (write request, run `oz do`, answer) fits.
   2. Each turn re-reads about 16k to 18k tokens of fill, so three turns already come close to the 60k per-run cap.
   3. Change: **fill about 6,000 o200k tokens**, and **at most 5 caller turns in both arms**. That fill still
      exercises the cache path (write on turn 1, reads after). Turn count and worker cost do not depend on fill size,
      and cost per turn at 60k and 120k is arithmetic from the measured slope.
   4. Keep 60k per run and 250k total. Report truncation as incomplete.

2. **Identical text in both arms.** Arm D needs `oz do` usage text that arm I would not otherwise get. Give both arms
   the same task text, including the same `oz do` usage snippet, with only the one requirement line different
   (inline review, or forced delegation). A run that breaks its arm's rule (I calls `oz do`, or D reviews a file
   inline) is recorded as a protocol violation, not scored as its arm.

3. **No per-job checks in D for this pilot.** Witness execution as an `oz do` acceptance check would give D retries
   that I cannot have, so the arms would no longer be single-shot equivalents. D uses `oz do` with `max_attempts` 1
   and no checks. The oracle stays evaluator-only in both arms. A check-enabled D arm is a separate, later cell.

4. **Freeze the byte facts the oracle depends on.**
   1. LF line endings and 1-based line numbers, identical in what the caller reads and what `oz do` packs.
   2. Witnesses are pure: no I/O, no randomness, the sandbox's CPU and wall limits. A witness that times out counts
      as unproven.
   3. Size the expected findings JSON offline against `oz do`'s 4,096-byte inline result limit. If it can exceed it,
      D needs an extra artifact read turn, and the plan must say so.

5. **Two accounting sources, both required.** The caller's `modelUsage` does not include the nested `oz do` worker,
   which is a separate `claude -p` process. Worker tokens come from the `oz do` call ledger and envelopes, and caller
   tokens from the caller envelope. A run with either missing is inconclusive. Total equals caller plus worker plus
   paid preparation.
