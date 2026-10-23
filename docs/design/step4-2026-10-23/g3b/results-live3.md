# G3b live3 on the patched executor: fail (model accuracy, not executor behavior)

Freeze 040cfd41 (commit 50e8ef5), fresh workspace, one suite. Evidence: `bench/step4/live3/`.

| Scenario | Launches | Packets | Memo hits | pass_g3b |
|---|---:|---|---:|---|
| clean | 3 | 4, 4, 4 | 0 | yes |
| exact repeat | 0 | none | 12 | yes |
| interrupted | 3 | 4, 4, 4 | 0 | yes |
| stale input A | 6 | 4, 4, 1, 1, 4, 1 | 6 | **no** |
| identical-byte bump | 0 | none | 20 | yes |

Totals: 12 launches, 31,309 tokens, accounting complete. Suite verdict: **fail**.

The stale scenario: classify_C (12.51 ± 0.01 against [12.48, 12.52], correct answer "inside") was answered "outside"
on attempt 1 and again on its resend at attempt 2; both calls used 0 hidden-reasoning tokens. The allowance was spent,
the job ended exhausted, and no package was delivered, so `delivered_once_on_time_verified`, `no_unresolved_stage` and
the stale observables fail. Every executor-side check passed: the exact trace equals the derived one, independent
verdicts agree (`bench/step4/recheck.py`: 77 candidates, 0 disagreements), recovery eligibility, launch caps, one
ledger call per launch, complete usage.

So the patched executor behaved exactly as specified, and the gate failed on the known boundary error that the
boundary probe reproduced 6 of 6 times on this exact packet. Across all live classification calls so far, every wrong
answer (5 calls) came from a call with 0 hidden-reasoning tokens. The signed adoption plan
(docs/design/boundary-adoption-2026-10-23) targets exactly this failure; it waits for O1 under the agreed sequencing.
Per the rules there is no rerun of this suite.
