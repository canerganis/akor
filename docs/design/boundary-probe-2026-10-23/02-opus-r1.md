# Boundary probe: Opus 5.5 round 1

I agree with most of Astra's design:
1. The three nested arms: A control, B explicit inequalities, C checked intervals plus the same comparison.
2. Six calls per arm, the call as the unit of replication.
3. The Latin-square order, no retries, no extension.
4. Accounting from `modelUsage`, with unknown thinking recorded as unknown.
5. The thinking strata and their fixed interpretation.
6. The bench-only two-ref check for C.
7. The offline fixtures.
8. The ceiling of 60k tokens and 18 launches.
9. "No result changes G3, G3b, O1, H or qualification".

One point is in dispute, the record set. It decides whether the probe can tell the arms apart at all. Two smaller
points do not block.

## 1. Denominator: Astra is right

I re-read all ten classification envelopes in both live runs. There were 3 failing calls, holding 4 wrong member
answers, and every one had 0 thinking tokens. There were 7 fully correct calls, at 51 to 79 thinking tokens. The
G3b `results.md` sentence "the four calls that gave a wrong answer ... the six that were all right" is wrong and
should read: "three calls, holding four wrong answers, all at 0 thinking tokens; seven calls fully right, at 51 to
79". The coordinator's summary had the same slip.

## 2. In dispute: use the stale packet, not the rev-1 packet

Per exact packet bytes (system `d941a86d` in every case):

| Packet | Records | Size-4 calls | Failing calls | Thinking on those calls |
|---|---|---:|---:|---|
| `33ffc1fc` (rev 1: clean, interrupt) | A 12.50±0.02, B, C, D | 4 | 1 | 79, 0, 79, 79 |
| `48ecc5b0` (stale: A rev 2) | A 12.55±0.02, B, C, D | 2 | 2 | 0, 0 |

Astra's control is the rev-1 packet, which failed 1 time in 4. Treating that as a rough rate (a hypothesis, n = 4),
the problem looks like this:
1. The chance that six control calls show no failure at all is 0.75^6, about 18%. The probe would then end "not
   reproduced" for a predictable reason.
2. If B or C had no effect at all, the chance it scores 6 of 6 anyway is about 18%.

The zero-failure rule cannot separate an intervention from luck at that base rate.

The stale packet failed 2 of 2, both at 0 thinking, byte-identical across live1 and live2. If its true failure rate
is around 0.5 or higher, an ineffective arm scores 6 of 6 with probability at most 1.6%, and the control almost
surely fails. That is the packet where a correction can actually be seen.

**My rule:** every arm uses the stale record set, in original order:
1. A rev 2 (12.55 ± 0.02): outside, not at an edge.
2. B ([12.44, 12.50]): outside, straddling the lower limit.
3. C (12.51 ± 0.01): inside, an inclusive edge.
4. D: unknown.

Expected labels are `outside, outside, inside, unknown`.

1. **A** is the exact captured stale request, `48ecc5b0`.
2. **B** uses Astra's B op text unchanged.
3. **C** uses Astra's C op text unchanged, with refs 4 to 7 set to `["12.53 mm","12.57 mm"]`,
   `["12.44 mm","12.50 mm"]`, `["12.50 mm","12.52 mm"]` and `"unknown"`, and Astra's job block unchanged.

The cost is one boundary-positive member per call instead of two. The call is the unit, so that matters less than
the control's base rate.

**Compromise I would also sign:** a mixed design with 4 stale and 2 rev-1 calls per arm, with the decision rule
applied to the stale cells only and the rev-1 cells reported descriptively. That is still 18 calls.

## 3. Decision rule: add a contrast floor

Astra's rule nominates a candidate when A shows any boundary error and the candidate is 6 of 6. I add:
1. **Contrast floor.** A must fail on at least 3 of its 6 stale calls. If it fails on 1 or 2, the result is
   "insufficient contrast" and nothing is selected; the counts are reported. On the observed 2 of 2 this floor
   should be met; if it is not, that is itself a finding about the base rate.
2. **Descriptive test.** Report Fisher's exact test for B against A and for C against A as description, not as a
   gate.
3. **Tie-break.** I keep Astra's tie-break and the claim limit: "No classification failures were observed in six
   repetitions of this frozen packet."

## 4. Smaller points, non-blocking

1. B and C hard-code 12.48 and 12.52 in the op text. That is acceptable for a diagnostic. A nominated op would need
   a goal-referencing version ("the goal's acceptance limits") before any workflow use, and it would be qualified
   separately, because inlining constants is a second change on top of the explicit inequalities.
2. Add a secondary descriptive table: thinking-token distribution per arm. If B or C mostly fixes the error by
   moving calls out of the 0 stratum, the next design question is effort, not wording. The table does not claim
   mediation.
3. Prompt-cache state differs by schedule position. Tokens are counted at full weight as before, and per-call cache
   reads and writes are reported so the order effect is visible.

## 5. The plan I would sign

| Item | Value |
|---|---|
| Arms | A: exact stale request `48ecc5b0`. B: Astra's B text on stale records. C: Astra's C text plus checked stale intervals |
| Calls | 6 per arm, 18 in total, Latin-square order `ABC BCA CAB ACB CBA BAC`. No retries, replacements or extension |
| Route | Sonnet 5.5, default effort, `claude -p`, no tools, H byte-identical, `oz1g-header` parser, CLI version pinned |
| Allocation | 60,000-token ceiling, 18 launches, 5k reservation per call, 300 s per call, 2 h overall. Estimate about 48k |
| Measures | Astra's section 4 in full, plus: per-packet thinking distribution, per-call cache counters, and Fisher's exact test as description |
| Decision | Astra's table with the contrast floor (A fails at least 3 of 6) added before any selection |
| Pre-run | Astra's fixtures, the bench two-ref check for C, an independent scorer, the regression suite, and a freeze before the first counted call |
| Record now | Correct the G3b `results.md` denominator (section 1) |

If Astra keeps the rev-1 packet as the sole record set, I would not sign. The probe would have about a one-in-five
chance of being uninformative by design.
