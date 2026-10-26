# Morning report, night of 2026-10-26

Owner asked Claude and Astra to choose the direction and build toward the fewest tokens, most effective and fastest
orchestration. Branch oz-0.9, local commits only, nothing pushed. Claude weekly quota stayed at about 78-80%.

## What we did

1. Stopped oz map and the replication ceremony ([README.md](README.md), [astra.md](astra.md)).
2. Compared the unchanged AKOR executor with one competent direct `claude -p` call on the O1 code repair package.
   AKOR lost: cold 1.58x tokens and 1.60x time, revision 1.40x and 1.73x, every delivery verified
   ([results-1.md](results-1.md)). Cause: two serial model stages per delivery.
3. Astra designed OZ/F1, a one-call wire with same-reply dependencies (`oz_fuse.py`). It reached parity on tokens
   (0.99-1.06x) but was 7-20% slower: input fell 14%, hidden reasoning rose 50-90% ([results-2.md](results-2.md)).
4. Measured the fixed cost of a `claude -p` call: 1,916 input tokens for an empty task (this CLI configuration).
5. Pooling jobs from four producers into one call: about 40% fewer tokens when jobs arrive together
   ([results-3.md](results-3.md)). With staggered burst arrivals the frozen gate failed on accuracy (30, 29 vs 31, 31
   of 32) and latency (up to 1.25x); sparse arrivals passed but saved nothing ([results-4.md](results-4.md)).
6. OZ/1g in a pooled call: no consistent accuracy, token or speed advantage over a plain JSON prompt.

Every runner was reviewed by Astra before live calls; each review found real defects, all fixed before spending.
Code added: `bench/o1/compare.py`, `oz_fuse.py`, `akor_pool.py`, `bench/pool/pool.py`, `bench/pool/pool2.py`.
Frozen modules untouched. Live evidence: `bench/o1/cmp-live1`, `cmp-live2`, `bench/pool/live`, `bench/pool/live2`.

## What holds

- For small model jobs through `claude -p`, the number of calls is the main cost lever; each call carries about
  1.9k fixed input tokens.
- Batching ready jobs captures that saving. A plain queue gets all of it.
- The compact wires and the executor did not show added performance value over plain JSON in these tests.

## Decision for you

Astra and Claude agree: retire the "compact language makes agents faster and cheaper" identity and reposition AKOR
as an experimental orchestration toolkit that publishes its comparative evidence, negative results first. Or end
active development. Astra's exact README text and the list of claims to retract are in
[astra-close.md](astra-close.md). The README on GitHub still shows the old headline; nothing public was changed.
