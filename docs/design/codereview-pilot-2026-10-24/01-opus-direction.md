# Context offloading with code review: Opus 5.5

**SIGN with six changes.** The direction is right. Caller-cost left exactly two cases open: references too large
for the caller's context, and a caller whose context is already full. Offloading is the one place where delegation
can win on tokens, because every caller turn re-reads its whole context. I also agree with: same Sonnet first, fixtures
and sizes offline, ranking by correct work, then caller-plus-worker billed tokens, then time, log triage only if
justified, the cost cap frozen after sizing, and admission below 58%.

## Changes to the design

1. **Two pairs are a sizing pilot, not a decision.** Caller-cost needed three agreeing pairs per cell (M14), and
   caller turn counts varied a lot (J at 553, 912 and 567 tokens per job on one cell). Use the two reversed pairs only
   to size costs and catch harness faults. The ranking run is preregistered afterwards with at least three pairs per
   cell and the M14 agreement rule.

2. **Freeze what "full caller" means.**
   1. The fill is a fixed byte prefix: a recorded, unrelated prior session, identical in both arms, with no answers in
      it.
   2. Use two fill levels, for example about 60k and about 120k tokens, as cells. Size them with the measured slope of
      1.35 to 1.5 billed tokens per o200k-estimated token, not the raw estimate.
   3. The task text is identical except for one line: arm D may use `oz do`.
   4. Report caller turns per run. Turn count is the mechanism, and it must be visible.

3. **Forced delegation first; selective delegation later.** "Selective" adds the caller's own judgment as a second
   variable. In the first cells arm D delegates every review job, with references passed by path. A selective arm
   comes only after forced delegation shows a token difference worth refining.

## The code review oracle (deterministic, independent, no judge model)

4. **Seeded defects with executable witnesses.**
   1. Freshly written modules, not famous public bugs, to avoid memorized answers. Each module carries a reference
      test suite it passes in full.
   2. Defects come from a frozen class list (off-by-one, wrong comparison, missing guard, wrong exception, resource
      leak, unescaped input, and so on). Each seed has:
      1. a file and an exact line span;
      2. a class ID;
      3. a hidden witness test that fails on the defective code and passes on the reference;
      4. a frozen reference fix.
   3. Clean control modules with zero seeds measure false positives. About a third of the modules are clean.
   4. Distractors (style or refactor-only differences) must not be reported.
   5. Everything is frozen and hashed before the first call.

5. **The model must prove each finding, and the host runs the proof.**
   1. Output is strict JSON per file: `[{file, line, class, witness}]`, where `witness` is a call with arguments and
      an expected result in a frozen mini-format.
   2. A finding counts only if both hold:
      1. its witness fails on the defective module and passes on the reference fix, executed by the host in the O1
         sandbox;
      2. its line falls inside a seed's frozen span.
   3. A job (one file) is correct only if its proven findings equal its seed set exactly. A clean file must return
      an empty list.
   4. Recall, false positives and unproven findings are reported separately. No partial credit is counted as correct
      work.
   5. This keeps the oracle objective: whether a witness passes is executed, not judged.

6. **Unseeded real bugs and independence.**
   1. A finding outside every seed with a valid witness, one that fails on the shipped module and passes on a model
      or reference fix, is a real unseeded defect.
   2. The rule for it is frozen in advance: it is reported apart and counts neither as correct nor as a false
      positive, and the fixture is repaired before any later run.
   3. Independence works as in O1:
      1. The workflow's per-job acceptance check is witness execution only. Verifying a proof is not computing the
         answer, so the job stays model-needed under the authoring rule.
      2. The answer key (spans, classes, witnesses) is evaluator-only and imports no executor code.
      3. No model ever scores anything.
   4. Fixture authorship goes to a different model or tier than the one under test where possible, and the plan says
      which.

## Allocation

The weekly percentage is not a token count. Admission reads the actual quota figure before every run and projects
with a conservative factor taken from today's measured deltas (percent per billed token). It refuses any run whose
projection would cross 58%. The sizing pilot gets its own small cap, frozen after the offline sizing, and does not
borrow from the ranking run.
