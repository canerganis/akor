# Boundary probe: results

Freeze 520c98e8, 18 of 18 calls, 48,730 tokens (ceiling 60,000), Sonnet 5.5 through `claude -p`, CLI 2.1.306, OZ/1g
text H unchanged, every arm on the exact stale classify packet (48ecc5b0). Full report and raw envelopes:
`bench/probe/boundary-evidence/` (report.md).

| Arm | Entirely correct calls | Calls with the boundary error (classify_C) | Correct members | Thinking tokens per call | Tokens per correct member |
|---|---:|---:|---:|---|---:|
| A, frozen packet | 0/6 | 5 | 15/24 | 0, 0, 0, 0, 0, 0 | 1,046.4 |
| B, explicit inequality wording | 5/6 | 0 | 20/24 | 0, 90, 102, 105, 117, 124 | 827.5 |
| C, B plus the host-checked interval as a ref | **6/6** | **0** | **24/24** | 0, 0, 0, 0, 0, 152 | **686.9** |

One A call and one B call were rejected at the wire (malformed reply); both count in the cost. Fisher exact tests,
descriptive only: B vs A p = 0.015, C vs A p = 0.002.

Decision under the preregistered rule: the contrast floor held (A failed 6 of 6), and C met the criterion alone, so C
is nominated for a separately frozen workflow evaluation and composition qualification. Claim ceiling: no
classification failure was observed in six repetitions of this frozen packet. Nothing here changes G3, G3b, O1, H or
any qualification.

What it teaches:
1. The error is real and reproducible: the frozen packet failed every time, always at zero hidden reasoning.
2. Hidden reasoning is not what fixes it. C was right six times out of six while five of those calls used no hidden
   reasoning at all. Explicit wording (B) mostly worked by pushing the model to reason (90 to 124 tokens), and it cost
   more. "Positive thinking is necessary" is contradicted by C's zero-thinking correct calls.
3. Passing a host-checked intermediate forward, instead of making the model re-derive it, gave the best correctness
   and the lowest cost per correct answer. That is a design rule for workflows and possibly for the language; a
   goal-referencing version of the C operation needs its own qualification before use.

Run note: the harness refuses to run while `ANTHROPIC_BASE_URL` is set. In this session it held the default endpoint
(`https://api.anthropic.com`), so the run was started with that variable removed; the route is the same.
