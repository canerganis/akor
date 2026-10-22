# Effort probe on OZ/1g, Haiku 5.5, 64 jobs: result

Plan: [effort-plan.md](effort-plan.md). Data: `bench/live/data/effort_haiku_default.jsonl`, `effort_haiku_medium.jsonl`.

| Haiku 5.5, 64 jobs, seeds 3205 to 3209 | Replies accepted | Correct jobs | Tokens per verified job | Mean thinking | Median s |
|---|---:|---:|---:|---:|---:|
| default effort | 5/5 | 320/320 | 133.0 | 3,548 | 21.8 |
| `--effort medium` | 5/5 | 304/320 | 138.0 | 3,355 | 21.2 |

Gate: not passed. Medium kept every reply parseable but one reply (seed 3209) got all 16 jobs of one operation
wrong, and total tokens per verified job were higher, not lower. Thinking fell only 5%, far less than on the older
native-JSON wire (live12, about 35%). Default effort stays for Haiku.

The 16 wrong values all have one shape: the model copied `length=12.44 mm` where the operation asks for the value
`12.44 mm`. The same misreading appeared once in the one-call-per-job pilot arm on Sonnet. It points at the
operation's wording ("containing the ref's length, ...") rather than at effort; an authoring fix would need its own
test and is not part of this probe.
