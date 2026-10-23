I retain **three arms of six calls**, with explicit inequality wording separated from supplying checked intervals. This is a diagnostic probe, not qualification or evidence that an error rate is zero.

**Status:** Astra’s proposed preregistration, pending Opus’s agreement and a durable freeze. No new model calls were made. The read-only workspace prevents saving the freeze, capturing a run, or committing changes.

**1. Correct the historical denominator**

I checked the retained classification envelopes. The brief conflates wrong members with failing calls:

| Historical calls | Calls containing errors | Entirely correct calls |
|---|---:|---:|
| Size-4 classification | 3 | 3 |
| Singleton recovery | 0 | 4 |
| Total | **3** | **7** |

The three failing calls contained **four wrong member answers**. All three reported zero thinking tokens; all seven correct calls reported positive thinking tokens. The association remains, but the historical claim must say **three failing calls and seven correct calls**, not four and six. Sources: retained [live1 captures](.oz-runtime/step4-live1/do) and [live2 captures](.oz-runtime/step4-live2/do).

**2. Freeze three nested interventions**

All arms use the original revision-1 records, four jobs in their original order, unchanged goal, byte-identical H, and the existing `oz1g-header` parser.

| Arm | Operation and inputs | Comparison |
|---|---|---|
| A: control | Exact live1 clean classify request | Reproduce the frozen composition |
| B: inequalities | Original record refs; explicit arithmetic and inclusive inequalities | B versus A tests the wording intervention |
| C: checked intervals | Original records plus one checked interval ref per job; same explicit comparison | C versus B tests supplying and directing use of checked intermediates |

Control source: [1.request.json](.oz-runtime/step4-live1/do/live1-clean-classify-dcdace0917e7/captures/1.request.json). Its ledger records:

```text
H:
d941a86d530ab0fe1d90dc1fb9d957bd95da1bfa8d150d17e320debcef50ea06

Control prompt:
33ffc1fc5280fb625b135871c515e4f702a662f421912a27a86a71c12adfd1c2
```

Freeze B’s operation text exactly as:

```text
If uncertainty is unknown, return unknown. Otherwise compute lower = length - uncertainty and upper = length + uncertainty from the record. Return inside if lower >= 12.48 mm AND upper <= 12.52 mm; outside otherwise. Equality at either limit is inside.
```

Freeze C’s operation text exactly as:

```text
The first ref is the measurement record. The second ref is its host-checked interval: [lower,upper], or unknown. If the interval is unknown, return unknown. Otherwise use its endpoints directly. Return inside if lower >= 12.48 mm AND upper <= 12.52 mm; outside otherwise. Equality at either limit is inside.
```

C retains original refs 0 through 3 and appends:

```json
[
  ["12.48 mm","12.52 mm"],
  ["12.44 mm","12.50 mm"],
  ["12.50 mm","12.52 mm"],
  "unknown"
]
```

Its job block is:

```json
[[0,["classify_A",0,4],["classify_B",1,5],["classify_C",2,6],["classify_D",3,7]]]
```

Expected labels are `inside, outside, inside, unknown`. A and C are the boundary-positive members; B and D guard against an indiscriminate `inside` response.

C tests **checked interval data plus instructions to use it**, not a pure ref-only effect. Retaining the records avoids simultaneously testing removal of source context. No fourth arm is warranted within this small allocation.

**3. Allocation and execution**

- Six blocks, each containing one call per arm. Freeze this order:  
  `ABC | BCA | CAB | ACB | CBA | BAC`.
- Exactly 18 launch slots, sequential fresh processes. No memo reuse, conversation continuation, retries, replacement calls, or outcome-dependent extension.
- `claude -p`, Sonnet 5.5, default effort, with the existing adapter’s tools-disabled and settings-isolation options. No effort arm.
- Pin CLI version, requested and reported model identity, adapter, parser, environment settings affecting effort, and exact request bytes before launch. A route mismatch blocks or terminates the run; it is not silently pooled.
- New allocation and evidence namespace, independent of live1/live2. Freeze the plan, complete requests, schedule, oracle, accounting rules, runner, and scorer before the first counted call.
- Planning estimate: approximately **48k tokens**. Allocate a **60k-token admission ceiling**, 18 launches, a 5k reservation before each call, 300 seconds per call, and two hours overall.

The ceiling exceeds the outline’s estimate because intervention costs are unmeasured and reservations need headroom. It does not authorize additional calls. Reservations are admission controls, not provider-enforced token limits; any overrun remains reported expenditure.

Every launched slot counts, including failures. Missing accounting stops further launches pending reconciliation. An interrupted or incomplete allocation is reported as incomplete, with no full-arm selection decision.

**4. Scoring and accounting**

The **call is the replication unit**. Four siblings do not constitute four independent trials.

Report for each arm:

- Entirely correct, strictly accepted, on-time calls out of six.
- Calls with an A or C boundary misclassification.
- Correct members out of 24, including boundary members out of 12.
- Separate counts for semantic errors, atomic wire rejection, valid model error lines, process failures, and deadline misses.
- Total tokens, tokens per correct on-time member, and call durations. Failed calls remain in the numerator. A zero denominator yields undefined cost per success.

Use an independent frozen oracle against the preserved raw reply. No malformed-reply salvage. Wire-invalid calls earn zero accepted work; readable fragments are not counted as correct results.

For every `modelUsage` entry:

```text
call_tokens =
  inputTokens
  + cacheReadInputTokens
  + cacheCreationInputTokens
  + outputTokens
```

Sum across all entries. Record `thinkingTokens` separately; do not add it again to output tokens. Preserve the raw counters, envelope, stdout/stderr, exit status, timestamps, request digests, and unique call ID. Missing thinking is **unknown**, never zero. Missing required usage counters means incomplete accounting, never substitution from CLI `usage`.

This measures classification first-attempt cost. It does **not** measure recovery-inclusive workflow savings.

**5. Hidden reasoning analysis**

Prespecify three strata within each arm: `thinkingTokens = 0`, `> 0`, and unknown. Cross-tabulate each against whole-call correctness and boundary errors; publish the per-call rows.

Interpretation is fixed:

- A correct zero-thinking call contradicts “positive thinking is necessary.”
- An incorrect positive-thinking call contradicts “positive thinking is sufficient.”
- Perfect separation would reproduce an association, not establish causation.
- If an arm lacks either observed thinking stratum, its within-arm association is unassessable.
- If an intervention changes both correctness and thinking, this probe cannot distinguish reasoning mediation from other effects of the changed packet.

Thinking is an observed post-intervention variable. Do not adjust it away in the primary arm comparison or claim that it “explains” the outcome causally. An effort intervention would require a separate design and still would not directly randomize realized thinking tokens.

**6. Decision rule**

| Completed result | Consequence |
|---|---|
| A exhibits a boundary error; B or C achieves 6/6 entirely correct, on-time calls with complete accounting | Nominate that intervention for a separately frozen workflow evaluation and composition qualification |
| Both B and C meet that criterion | Prefer lower measured total tokens, then elapsed time, as the candidate for follow-up; do not claim equal underlying reliability |
| A has no boundary errors | Failure mechanism was not reproduced; no demonstrated correction and no workflow change |
| Candidate has any failure | It did not eliminate observed failures in this probe; report counts, without selecting it under the zero-failure rule |
| Allocation, route, oracle, or accounting is incomplete | No selection decision |

Even a successful candidate supports only: **“No classification failures were observed in six repetitions of this frozen packet.”**

No result here removes host checks, changes G3/G3b verdicts, closes O1, qualifies a composition, or authorizes a shipped wire change. A successful candidate changes the **next experimental workflow proposal**, with a new operation version and computation identity. Operational adoption requires the subsequent recovery-inclusive measurement and applicable qualification.

**7. Implementation boundary and agreement**

The current host barrier already produces checked bounds, but classification receives the records. C can expose those existing bounds without changing H. However, the current [`mat_classify` check](bench/step4/workflow.py) requires exactly one record ref. C therefore needs an explicit bench check supporting its two-ref contract, including record-to-interval consistency, plus an independent scorer. Simply attaching another ref would not work with the existing check.

Before live execution, require offline fixtures for inclusive equality, outside intervals, unknown uncertainty, mismatched checked intervals, atomic parser rejection, missing accounting, missing thinking, and duplicate ledger records. Any implementation must also pass the repository regression suite.

I agree with Opus’s three-arm scale. I do not accept “correctness tracks hidden thinking, not wording” as an established conclusion. Wording has not yet been experimentally contrasted, and thinking remains observational. Opus’s agreement to these exact interventions and decision rules is outstanding.

Continuation: implement the bench-only harness, verify it, obtain Opus’s concurrence, freeze and commit only those changes, then execute the fresh allocation. No files were changed or committed here.


