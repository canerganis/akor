ACCEPT.

**Sizing pilot only.** No winner, adoption decision, selective arm, or ranking run is authorized by this preregistration.

1. **Fixtures.** Two fresh three-file Python packs, each containing two defective modules and one clean control. Each defective module has one seed, from the frozen classes `off_by_one` and `missing_guard`. Include harmless style/refactor distractors. Reference modules pass their complete reference suites. Each seed records its exact span, class, hidden executable witness, and reference fix. GPT-6 Astra authors the fixtures; Sonnet 5.5 is under test. Freeze and hash all files, prompts, witnesses, fixes, and evaluator code before calls. The evaluator imports no executor code; its answer key is inaccessible to callers and workers.

2. **Arms.** Same Sonnet version, effort, tools, file access, and final deliverable.
   - **I:** Caller reviews all three files inline.
   - **D:** Caller must delegate every file through `oz do`, passing references by path. Batch the three jobs into one dispatch.
   
   Task text differs only in the line requiring inline review or forced delegation. Both return all findings to the caller’s final answer.

3. **Fill and runs.** Use one fixed byte prefix from a recorded, unrelated session, screened for task answers. Its exact bytes and hash are identical across arms. **Pilot fill: approximately 12,000 o200k-estimated tokens**, budgeted as 16,200–18,000 input tokens per caller turn before task and harness overhead. This is a sizing probe, not evidence about a full caller. Run **two matched pairs, four runs total**: pack A in I/D order, pack B in D/I order. Fresh sessions; no automatic retries. Maximum three caller model turns per run, with truncation reported as incomplete.

4. **Oracle.** Strict JSON per file: `[{file, line, class, witness}]`. Freeze a witness format specifying function, JSON arguments, and expected return or exception. The host executes witnesses in the O1 sandbox. A seeded finding requires the matching class, a line inside its frozen span, and a witness that fails on shipped code and passes on the reference fix. A file is correct only when proven findings exactly equal its seed set; clean controls require `[]`. Report recall, false positives, and unproven findings separately. Valid unseeded defects count neither toward correctness nor as false positives; report separately and repair before later runs. No model scores findings.

5. **Measurements.** Record caller turns; caller and worker input/output tokens separately; cache reads and writes; available reasoning usage without double counting; total billed tokens; elapsed time; and oracle correctness. Include failed calls and paid preparation. Missing accounting makes sizing inconclusive.

6. **Pilot budget and admission.** After offline packet sizing, freeze a cap **no higher than 250,000 total tokens**, including cache reads: at most 10,000 for paid preparation and 60,000 per run. Check affordability before every model call. No borrowing from future ranking allocation.

   Treat **46% as the supplied reading**, then read actual quota before each run and after settlement. Initially project with **2 percentage points per 55,000 tokens**, a conservative allowance over the reported one-point O1 movement. Increase this factor if today’s observed deltas require it; never infer free usage from rounded zero movement. Reserve the run’s entire remaining cap plus quota-display rounding uncertainty. Refuse admission if the projection reaches **58%**; **60% is the ceiling**, not spendable headroom. Unavailable or unsettled readings block admission.

The pilot estimates turn counts, overhead, and cache behavior. A 120k prefix alone implies roughly 162k–180k input tokens per turn, so repeated reads can consume hundreds of thousands per run. Later 60k/120k cells require a separate affordable preregistration, at least three pairs per cell, and M14 agreement.


