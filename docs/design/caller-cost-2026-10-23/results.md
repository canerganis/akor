# Caller-cost experiment: results (48 counted runs, frozen digest 6b5e75cb)

Plan: [plan-frozen.md](plan-frozen.md); signed design: [README.md](README.md). Sonnet 5.5 as caller and worker,
Claude CLI 2.1.306, Bash-only callers, fresh workspaces, strict seed-bound oracles. `pilot_k2.py rejudge` re-judged
every stored run with 0 mismatches. Data and full transcripts: `bench/live/data/pilot_k2.jsonl`, `pilot_k2/`.

Tokens per verified job, per seed (J: the caller does the work itself; K0: archived skill text; K1f: new skill text,
full `oz do` output; K1r: new skill text, bounded receipt plus artifact):

| Cell | J | K0 | K1f | K1r |
|---|---|---|---|---|
| A, caller holds the jobs, answers in reply, 16 | 325, 319, 321 | | | |
| A, same, 64 | 167, 170, 168 | 469, 671, 813 | 500, 496, 501 | |
| B, references in files, answers in reply, 16 | 585, 579, 583 | | 941, 939, 952 | |
| B, same, 64 | 279, 280, 280 | | 632, 455, 449 | |
| B, files, artifact plus follow-up, 16 | 937, 931, 943 | | 930, 908, 919 | 1,279, 1,261, 1,266 |
| B, same, 64 | 400, failed, 406 | | 417, 422, 425 | 700, 703, 699 |
| C, 4 KB references in files, artifact plus follow-up, 64 | 553, 912, 567 | | | 898, 1,011, 899 |

Every K run and every J run but one had all jobs correct. The failed J run (B, artifact, 64, seed 7102): a Bash
command hung until its time limit, and the caller then wrote a sentence before the JSON answer, which the strict
checker rejects; all its tokens count, with zero verified jobs.

Gates (preregistered):
- G1, adopt the new skill text: **fail**. K1f was steadier and cheaper at the median (500 vs 671) but not cheaper on
  every paired seed (seed 3105: 500 vs 469).
- G2, build the receipt into `oz do`: **fail**. The receipt cost more than the full output on every pair (median
  67% more at 64), because the caller then reads the artifact for the follow-up step.
- G3, importer: **deferred**. The request-writing share is far under 25% (upper bound 0.07%, o200k estimate 12%).
- M14 winners (three agreeing pairs required): J in five cells, K1f in one (B, artifact, 16 jobs: 919 vs 937, a 2%
  margin), two undecided (B, artifact, 64, where J's failed run breaks the agreement).

What this settles: with the same worker model as the caller, handing work to `oz do` does not save tokens against
the caller doing it inline in one batched reply, on these workloads, even when the inputs live in files or the
references are 4 KB each. The integration is still 9 to 10 times cheaper than one subagent per job (arm K), and it
gives durable retries, resume, per-job checks and a separate worker; those are its reasons to exist, not tokens.
Untested here and still open: a cheaper worker model on a different quota, much larger references, and callers whose
context is too full to hold the work.
