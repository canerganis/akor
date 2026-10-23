# H attribution proposal: Opus 5.5

**SIGN with two changes. Together they likely make the paid calls unnecessary.** I agree with the frame: attribute
before any rewrite, matched pairs with reversed order, input counted at full weight, the 25% threshold, a frozen cell
and denominator, any shorter H only as an opt-in profile with its own qualification, and the 58% admission stop.

## 1. Add a zero-cost bound gate before any call

The step 1 report already bounds H. H is 1,590 bytes, a token covers at least one byte, so H bills at most 1,590
tokens (o200k estimate 372). The removable part is H minus the minimal text, so it is smaller still. Even at the hard
1,590 bound, H stays under 25% in every size-4 and all-stages O1 cell, using the section 6.1 denominators:

| O1 cell | denominator | H share at 1,590 tokens per call |
|---|---:|---:|
| repair_core, n=4, clean (the worst n=4 cell) | 7,112 | 22.4% |
| repair_adapter, n=4, clean | 8,535 | 18.6% |
| all stages, n=4, clean | 15,647 (two calls) | 20.3% |
| all stages, n=4, stale | 15,767 | 20.2% |
| repair_adapter, n=1, stale | 3,913 | 40.6% |
| repair_core, n=1, stale | 4,038 | 39.4% |

Only the size-1 cells can clear 25% at the bound. There, removable H would have to bill more than about 980 tokens,
which is over 0.61 tokens per byte of H. That is implausible for English prose: the o200k estimate is 0.23. And the
size-1 cells are stale-recovery singletons. Their high fixed share is a batch-size effect, and batching is already
the lever we use.

**Rule:**
1. Prespecify the cell as **O1, all stages, n=4, clean** (denominator 15,647). It is the representative path.
2. Before any call, compute the bound. If H at 1,590 tokens per call is under 25% of that cell, close the candidate
   with zero calls and record the arithmetic.
3. On the numbers above that bound is 20.3%, so the gate closes the candidate now.

## 2. If attribution is still wanted for the record, take it from data first

The corpus already varies the system text without a dedicated pair:
1. pilot2q cut the system text per call. The 603-token cache read appears in 144 of 144 of those calls.
2. pilot_k2 worker calls show an intercept of 1,567 under a different system text, against 2,174 to 2,188 under H at
   the same CLI version.

A zero-cost fit of the fixed intercept against system-text bytes across groups that share the CLI version and flags
may attribute H well enough to cite. Only if that is inconclusive and the owner wants the number for documentation:
1. Run one matched pair with the order reversed, on the smallest O1 packet.
2. Cap it at 4 calls and 12,000 tokens, below the proposed 20,000. Input counts are deterministic for fixed bytes,
   and the step 1 range is 2,166 to 2,199.
3. Reconcile the decisive counters from the envelopes, not from the adapter ledger.
4. Exclude Opus review from that allocation. Review is not a `modelUsage` call, so it is counted against the weekly
   line, not the 12k.

## What does not change

No wire change, no rewrite allocation, Sonnet stays, the 58% admission stop and the 60% owner ceiling stay. A shorter
H, if ever proposed, needs its own preregistration, qualification and paired O1 suites, as Astra wrote.
