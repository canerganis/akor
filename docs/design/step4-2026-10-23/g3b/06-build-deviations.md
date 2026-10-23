G3b build report, deviations from the signed text (builder: Sonnet; nothing run live; executor unchanged):
1. Fully rejected size-4 packet: the signed text says one singleton resend per rejected member. The unchanged executor sends one size-4 packet at attempt 2 when all four members are pending (packet sizes 4 and 1, largest that fits). Wire rejection is atomic, so a wire-rejected size-4 reply always returns all four together. The oracle therefore derives one size-4 resend when |R| = 4 and singletons when |R| < 4, and "wire rejection resent as singletons" is a sabotage case. Consequence: realistic worst case per cold scenario is 6 launches, Opus's 23-launch estimate is unreachable.
2. The old stale-order observable is replaced by "order after mutation equals the oracle's derived order".
3. Allocation lives in a new g3b.json; workflow.json stays byte-identical (its old 60k/16/8 block is unused).
4. pass_with_recorded_rejections is retired; legacy strict count-based "pass" is reported separately; pass_g3b binds.
5. live refuses --only, --rerun, a non-fresh workspace, and baseline (no new allocation).
6. At about 2.7k tokens per call the 64k token cap binds near 22 launches, before the 24-launch cap.
7. Added explicit checks: attempt-1 packet sequence and memo hits equal the table; no stage ends unresolved.
Dry gate passes; 16 predicate sabotage cases caught (size-2 resend, skipped resend, reorder and singleton-resend-of-wire-rejection caught only by the exact trace); live1 read-only replay gives pass_g3b on all five (interrupt and stale as recovered), labeled not a verdict.
