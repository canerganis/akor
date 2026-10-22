# Caller-side cost of `oz do`: Opus 5.5 round 2

**SIGN.** I accept Astra's round 2 plan as written: 45 counted runs, or 48 with the K0 rerun. That includes no adaptive
extension, the G1 rule of no additional Bash calls, the receipt bound tested with long IDs and paths, G3 reported as a
token estimate or upper bound, Haiku excluded, and 4 KB only. I also accept the wording change on point 1: "J won the
archived comparison; J winning the matched comparison is the prediction."

No points disputed. Two notes for the harness, neither of which changes the plan:

1. **The K0 rerun is likely triggered.** Commit 430f660 (lossless values, on oz-0.9) changes `oz do`'s value path after
   the archived K runs, so the archived K0 is probably not comparable under Astra's rule. Budget for 48 runs and decide
   during the smoke by diffing the `oz do` output shape and the worker packet against the archived ones.
2. **One step of the oracle chain could not be checked.** No transcript or packet from the archived K runs was kept,
   so the comparability check in note 1 can compare only the request shape and the token sizes, not the bytes.

## Frozen continuation task (artifact plus continuation contract)

**Task text (same for J and K):** After `results.json` holds a top-level `jobs` map `{"<message ID>": {"status":
"accepted"|"failed"|"unresolved", "value": <JSON>}}` covering every message ID, reply only with the JSON
`{"outside":[...],"unknown":[...],"not_accepted":[...]}`. These are, in message order, the IDs whose value is
exactly the string `outside`, the IDs whose value is exactly the string `unknown`, and the IDs whose status is not
`accepted`.

**Oracle:** For each run, the records of that run's own seed give every ID's expected value. The strict per-job oracle
judges each `jobs[id].value` in the file. The final reply must decode strictly (no extra keys, no prose). Its three
lists must equal exactly, in order, the lists computed from the expected values, with every expected-accepted ID absent
from `not_accepted`. Verified jobs are the file's jobs that pass the per-job oracle, but only when the reply matches.
A wrong or missing reply, or a missing or malformed file, scores the run 0 verified jobs, with all its tokens counted.
