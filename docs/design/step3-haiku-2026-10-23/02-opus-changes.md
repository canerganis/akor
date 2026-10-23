# Step 3, cheaper worker on O1: Opus 5.5 on Astra's preregistration

**SIGN with five changes.** I agree with the design: Haiku 5.5 only, an unchanged suite and gate, `pass_g3c` before
tokens before time, 150k tokens and 18 launches, no tuning or fallback, and the narrow claim. Two of the five changes
are factual and must be fixed before G0 (1 and 2). Three are pins (3 to 5). All checks here are read-only and made no
model call.

## Changes required

1. **Base freeze.** Item 2 says to preserve O1 freeze `32333561`. That cannot be done. The control ran at 32333561
   (executor 50e8ef5 plus the ticket B fix, 079a2f9). Since then 34f5850, 18eeee8 and 2747f32 edited files that
   freeze pins (`oz_do.py`, `oz_flow.py`, `oz_runtime.py`, `bench/step4/g3b.py`), and O1 now holds at `088815db`.
   The derived freeze starts from 088815db. Its reviewed diff touches only `route.model` and `route.alias_map` in
   `workflow.json`, plus the derived digest and record. Any other changed byte needs a new review.

2. **Show the control is matched before G0, with zero calls.** The O1 addenda say "default paths unchanged", but that
   rests on dry-gate passes, not on byte identity. Facts from the control's ledgers (`bench/o1/live1/calls-*.jsonl`):
   system H `d941a86d`, core size-4 prompt `ed27d59c` (the same in clean, interrupt and stale), stale core A
   singleton `3fb652d8`, adapter prompts `1c08ef8e`, `1c628a20`, `1ca7cc03` and `4157a4b8`. Installed CLI:
   2.1.306. Required at HEAD under the derived freeze:
   1. The core size-4 packet and both revision core singletons render byte-identical to `ed27d59c` and `3fb652d8`,
      with system `d941a86d`.
   2. Rendering the adapter packets from the archived Sonnet accepted cores reproduces the four adapter prompt
      digests. If the harness cannot do this without editing pinned code, record that, and rely on a written review
      of the `079a2f9..HEAD` diff of the four executor files showing that every change is behind value refs or
      ordered inputs, which O1 never uses.
   3. Same adapter script digest, effort, CLI, parser and wire fields in the route identity as the control, model
      aside.
   4. The same accounting scope: `modelUsage` whole call, and the same `totals_of` definition.

   Any mismatch means unmatched. Astra's defer rule then applies, and a matched Sonnet rerun is preregistered before
   either arm runs. Note what the control cannot match: Haiku's adapter packets carry Haiku's own accepted cores, so
   the adapter-stage input bytes differ by construction. That is part of the treatment, not a mismatch.

3. **Labels with a Haiku model ID.** `oz_do.CELLS` marks Haiku sizes 1 and 4 as `pass` on the materials class, so
   without `experimental_sizes=(4, 1)` every Haiku dispatch would read `qualified_cell`. The dry gate runs under
   `fixture-oracle-1`, which never hits that cell. Add a zero-call check that, with model `claude-haiku-5-5` and
   the derived settings, sizes 4 and 1 both label `experimental`.

4. **Model identity.** `response_check` refuses every candidate whose envelope's `modelUsage` keys are not exactly
   the route model after `alias_map`. Confirm Haiku's raw `modelUsage` key from an archived Haiku envelope
   (`bench/live/data/gate1_haiku.jsonl` shows `claude-haiku-5-5`), and freeze the alias map from that evidence. A
   wrong key would refuse every candidate and waste the suite.

5. **Quota stops.** "Check quota before each launch" has no hook in the pinned harness, and adding one changes code
   outside the route diff. The suite is automatic and short (control: 190 s, 8 launches). Instead: read the weekly
   figure before the suite, start only below 45%, and record it again after. If unattended monitoring sees 46%
   mid-suite, stop and report the suite as incomplete. The 49% hard stop is unchanged. If Astra wants a per-launch
   check, it goes into the derived freeze diff and through its own review and dry gate.

## Accepted as written

Haiku only, default effort; sizes 4 and 1 experimental and nothing transferred; fresh workspace and memo namespace
(the route is in every computation key, so no Sonnet entry can hit); no effort tuning, fallback or repair; the same
five scenarios and `pass_g3c`; tokens then elapsed time; whole-call accounting with failures and retries; 150k and
18 launches, 8 per scenario, one call in flight, deadlines kept; the reserve stated as admission headroom, not a
ceiling; the stop list; the claim limited to this frozen use case with no caller and no general coding claim.

One reporting note, not a change: both arms are one suite each. Report the token difference as measured on those two
suites only. The control had 56 of 56 first-attempt acceptances, so any Haiku recovery cost shows up directly in the
comparison.
