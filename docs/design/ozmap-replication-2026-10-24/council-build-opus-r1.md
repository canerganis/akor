# Council round 1: Opus code correctness review of bench/ozmap_rep (2026-10-24)

Reviewer: fresh Opus subagent (claude-opus-5-5, effort high, code correctness lens), logged in call-ledger.jsonl. No
model call and no Codex call was made; every replay below used local captures or fakes. The sealed reviewer ASTs were
not read. Reviewed against amendment-4.md, amendment-4-13-caps.md and build-notes.md at commit 4839d99.

Verdict: **do not freeze yet.** Five blockers. Four are code fixes of a few lines each; B1 (part b) and B5 need a short
prospective signed ruling (Astra A, Opus B) before `run freeze`, because the harness follows A4 literally and the literal
reading would make the live run invalid or inconclusive on events that are not leakage.

## What I ran

| check | result |
|---|---|
| `python -m pytest bench/ozmap_rep -q` | 361 passed (90 s) |
| `python -m pytest -q --continue-on-collection-errors` (full repository) | stopped by my 590 s time limit at about 61%; the 3 collection errors and the failures seen up to there sit in files outside `bench/ozmap_rep/` named in build-notes (tiktoken missing in the system interpreter); not rerun |
| `python -m bench.ozmap_rep.run dry --run-dir <scratchpad>/rep/dry-r1/D` | exit 0, 16 of 16 cells complete, 52 fake calls, 0 external calls, every cell within its A4.4 bound |
| `git diff 1aad1f8 -- bench/ozmap_rep/acceptance/` and `git status` on that directory | empty: no acceptance file changed or added since 1aad1f8; no earlier council round exists, so none was expected |
| frozen paths (`bench/ozmap/`, `oz_*.py`, `bench/ozmap_rep/ops/`) | unchanged in git since 1aad1f8; only pilot run artifacts are untracked under bench/ozmap/runs |
| certificate envelopes | both tracked in git, both hash to the recorded envelope_sha256, decoder hash matches, replay fixtures all ok |
| replay of the build's own no-auth probe (`scratchpad/rep/cliprobe/exec-noauth2.out`) through `run.judge_codex` | `uncertain`, not `auth_failure` (B1) |
| `gates.magnitude` on a summary with isolation failed, bootstrap invalid and a rule error | `pass`, "at least the pilot magnitude" (B2) |
| fake cell `codex-materials-cold-A` with `fake_fail=1` | retry succeeds, 256 of 256 correct, cell usage `incomplete` (B5) |

## Disputes

`disputes.md` does not exist and build-notes.md reports none. Nothing to rule on. The acceptance suite stands as written.

## Blockers

**B1 BLOCKER (A4.2, A4.3: a real authentication failure is judged `uncertain`).** On codex-cli 0.160.0 a 401 emits
the item `{"type":"error","message":"Falling back from WebSockets to HTTPS transport. unexpected status 401 ..."}`
before `turn.failed`. `events.classify_stream` files that item as uncertain, and `run.judge_codex` returns the event
verdict before it tests `AUTH_FAILURE_RE` (run.py:309 to 313). Replaying the build's own probe capture gives
`uncertain`; removing only that line gives `auth_failure`. Consequences in a live run with an expired or revoked
token: (1) `finish` gets `auth_failure=False`, `reconcile_auth` sees nothing, and the A4.2 stop ("An authentication
failure without a changed worker also stops Codex evaluation") never fires; (2) each failing call is terminal, so the
batches are lost without retry; (3) the scorer lists every such call as leakage, which invalidates replication
efficiency for the whole run. The same item in an otherwise successful call (a transient WebSockets failure that HTTPS
recovers) also invalidates the run, although no tool item exists.
Fix: (a) in `judge_codex`, decide authentication failure first and independently of item classification: match
`AUTH_FAILURE_RE` against the `turn.failed` error message and the top level `error` events (and stderr), return
`auth_failure` and keep the event verdict in the row for the record. Add a harness test that replays
`cliprobe/exec-noauth2.out` and expects `auth_failure` and a Codex stop. (b) Before freeze, obtain a prospective
signed clarification of A4.3 (Astra A, Opus B) on that one item: an `item.completed` error item with exactly
`{id, type, message}` whose message starts with `Falling back from WebSockets to HTTPS transport.` is a transport
event, not tool activity, like the top level `error` events. Implement it as a separate `TRANSPORT_NOTICES` tuple in
`events.py` (the frozen `codex_cli_adapter.KNOWN_NOTICES` stays untouched) and record such items in the attempt row.
Without (b), (a) still stops Codex correctly, but the run is invalid the first time the fallback appears. The pilot
captures contain no reconnect or fallback event, so it is rare when authenticated, which is why it must be decided now
and not after it is seen.

**B2 BLOCKER (A4.10, A4.11: the magnitude ignores isolation, bootstrap validity and the safety kill).**
`gates.magnitude` checks only leakage and accounting failures (gates.py:159). A4.11 says direction "requires A4.10's
warm gates on this subset", and A4.10 requires passed isolation, applicable bootstrap validity and no safety kill; A4.6
makes a bootstrap gold error on a proposed R rule invalidate efficiency. Probe: with `isolation: failed`,
`bootstrap.codex/materials.efficiency_valid: False` and a rule error in warm C, `magnitude` returns status `pass`,
`direction_replicated: True`, label "at least the pilot magnitude", and report.md prints it.
Fix: at the top of `magnitude`, return `status: invalid` (with the reasons) when `safety_kill(summary)` is true or
`_validity(summary, backend, 'materials')` is non-empty, before computing ratios. Add tests for each of the three
conditions.

**B3 BLOCKER (A4.2 after every call; resumable cells: a dead runner's call is never reconciled).**
`recover_inflight` (run.py:409) writes an `interrupted` attempt and deletes the marker, but never runs `iso.finish` on
the marker's slot and never reconciles. The next `prepare` on that slot `rmtree`s the worker home, so a refreshed
auth.json written by the killed call is destroyed while the baseline keeps the rotated refresh token. A4.2 requires
the hash comparison "after every call, including failures" and forbids restoring an older snapshot, which is what
reusing the baseline then amounts to. Second, Windows does not kill a child with its parent: when the driver's 10 minute
foreground limit or any crash kills the runner, `codex.exe` keeps running in that worker home, the OS slot lock is
released, and a resumed runner reconstructs the same home under a live process (or fails in `prepare` with an
uncaught `IsolationError`).
Fix: write the child pid and the prepared auth hash into the in-flight marker right after `Popen`. On recovery, before
any `prepare`: if a recorded pid is still alive, refuse to resume (exit 75, "call still running") or kill its tree and
record that; then for every orphan Codex marker run `iso.finish(slot, prepared_sha256=marker hash)` and feed all of
them to `reconcile_auth` (propagate one changed worker, otherwise `codex_stop`). Do this inside the Codex cell lock
(see C1). Add a test: a marker whose worker auth.json differs from the baseline leads to propagation on resume, two
such markers lead to a Codex stop.

**B4 BLOCKER (A4.2 telemetry failure, A4.3 scoring: a failed telemetry attempt either slips through or poisons the
run).** `telemetry()` overwrites `evidence/telemetry.json`, and `gates()` reads only that file, so a failed check
followed by a passing retry (four telemetry calls are allowed) lets evaluation launch, although A4.2 says "Failure of
either check stops evaluation". Meanwhile `score_run` iterates every attempt, telemetry rows included, so a telemetry
call judged `uncertain` (for example the B1 item) is counted as evaluation leakage and invalidates every gate of a run
that then completes cleanly. Both behaviours are wrong at once.
Fix: append every telemetry result to `evidence/telemetry.jsonl` and keep `telemetry.json` as the latest. Live cells
refuse when any telemetry attempt in the run directory failed; a further attempt needs a new run directory and a
recorded council disposition. In the scorer, exclude rows with `cell == 'telemetry'` from evaluation leakage and
accounting, and report them in a separate telemetry section. Telemetry also has no in-flight marker, so a crash
between spawn and the attempt row loses a charged call from the budget: write a marker as cells do.

**B5 BLOCKER (A4.7, A4.11: one transient infrastructure failure makes the cell's token comparison inconclusive).**
A failed attempt without `turn.completed` has usage `incomplete`, and `cell_summary` marks the cell usage incomplete
when any row is incomplete (score.py:146), so every gate on that cell becomes inconclusive even after the reserve retry
succeeds. Verified: `codex-materials-cold-A` with one injected failure ends 256 of 256 correct, usage `incomplete`.
The same holds for every recovered `interrupted` attempt. This follows A4.11 ("uncertified usage ... inconclusive")
literally, but it makes the A4.5 infrastructure reserve useless for any token claim, and 50 to 60 live calls make one
transient failure likely.
Fix: a prospective signed ruling before freeze, implemented as a frozen predicate. Proposal: a failed or interrupted
attempt whose usage is unknown is bounded, not certified: the gate is evaluated at the bound least favourable to the
claim (unknown cost counted as 0 tokens in the reference arm A or B, and as the input plus output tokens of the
successful retry of the same batch, which has the same prompt, in the arm under test), reported as `bounded`, and a
gate that passes at that bound passes. Without a ruling the harness behaviour is correct but the council should say
plainly that any retry forfeits that cell's token claims.

## Changes

**C1 CHANGE (lock order, double launch, slot deadlock).** In `run()` the Codex cell lock is taken after `gates()`,
`recover_inflight()`, `budget()` and `record_features()` (run.py:871 to 905). A second Codex cell process that waits on
the lock skips a `codex-stop.json` written meanwhile and reuses a budget snapshot taken before the other process's
calls; two processes of the same cell would each mark the other's live markers as interrupted. Separately, `Slots.acquire`
takes a group's slots one at a time and blocks: two concurrent cell processes (Sonnet with Codex, or two Sonnet cells)
can each hold two slots and spin forever. Fix: take one run directory lock (one cell process at a time) at the very
start of `run()` and of `telemetry()`, before any gate or recovery, and re-check `codex-stop.json` before every Codex
launch in `run_batches`. Document that cells run strictly one at a time.

**C2 CHANGE (record_features and telemetry bypass slots and reconciliation).** `record_features` prepares worker 0 and
`telemetry` workers 0 and 1 without holding the slot locks, and both discard the `finish` result, so an auth change
caused by `features list` or `login status` is neither compared nor propagated. Fix: acquire the slot through `Slots`,
and pass every `finish` result to `reconcile_auth` exactly as calls do.

**C3 CHANGE (telemetry pre-launch checks).** `telemetry()` does not run `verify_baseline` against the frozen inventory
(A4.2 "before every call") and does not check `codex-stop.json`. Add both, plus `verify_freeze`.

**C4 CHANGE (A4.12 Codex stop is blind during the run).** Workers run `--ephemeral` in their own homes and the
`exec --json` stream carries no `rate_limits` (checked in the run 1 envelope), so the newest file under
`~/.codex/sessions` never reflects evaluation calls and the 80% stop cannot trigger from them. Fix: record the session
file name and mtime with every reading in `quota.jsonl`; refuse a live Codex cell when the newest session file is older
than the end of the last Codex evaluation attempt, with a message that the driver must refresh the reading (from the
Codex app's own status) and pass it in. State this limit in build-notes.

**C5 CHANGE (tokenizer precheck).** If the pinned vocabulary or the `.venv` interpreter is unavailable, every Codex
call becomes `unverified` (pilot failure 3 again), and nothing checks this before launch; `verify_freeze` computes
`tokenizer.record()` but never compares it. Fix: live `gates()` requires `tokenizer.count(['probe'])` to return an int
and `vocabulary_ok()`; `verify_freeze` compares the tokenizer record.

**C6 CHANGE (timeout before event verdict).** `judge_codex` returns `infrastructure_failure` on timeout before looking
at the events (run.py:307), so a timed out call whose partial stream shows a tool execution is retried. The scorer still
counts the leakage, but A4.3 makes such a call terminal. Fix: test the event verdict first.

**C7 CHANGE (unknown counter).** The live stream has `cache_write_input_tokens`, which `decode_codex` ignores. If it is
ever positive, its relation to `input_tokens` is uncertified. Fix: in `after_group` (not in `decode_codex`, so the
certified decoder hash stays valid) mark usage `unverified` when that counter is present and positive.

**C8 CHANGE (fake and live share a run directory).** `cell` defaults to fake mode and both modes default to
`~/.ozmap_rep/runs/replication`. One forgotten `--mode live` writes fake cells with `DONE.json` into the live directory;
the live cell then exits 3 ("already complete") and the scorer scores fake answers. Fix: fake mode refuses the default
live directory; `DONE.json` records the mode; live cells refuse a directory containing any fake attempt; the scorer
reports isolation failed on mixed modes.

**C9 CHANGE (scorer isolation evidence).** `isolation: passed` needs only clean launch records and no codex stop. It
should also require, for a live run, a passing telemetry record (B4), an ok wave gate row for every Codex cell, an
`auth` record on every Codex evaluation attempt and a features record for every Codex cell.

**C10 CHANGE (leakage scope, needs a frozen ruling).** Any leakage or accounting failure anywhere invalidates every
backend's gates and magnitude (`_validity`, `magnitude`). A4.11 says leakage invalidates "affected efficiency
evidence"; A4.3 says "replication efficiency". Recommend a ruling, frozen before evaluation, that leakage in one
backend invalidates that backend's claims and the cross backend headline, not the other backend's per backend claim.
If the council prefers the global reading, keep the code and record the interpretation in build-notes.

**C11 CHANGE (freeze coverage).** Add the two certificate envelopes and `bench/ozmap_rep/tests/*.py` to the freeze, and
compare the tokenizer record and interpreter in `verify_freeze`.

**C12 CHANGE (bundled system skills, optional).** The CLI writes `skills/.system/*` into each worker home at startup;
whether they reach the model context is unobserved. If a telemetry call is spare, run one in a throwaway home without
`--ephemeral` and inventory its rollout (instructions, skill list) by name, so the isolation claim rests on evidence
rather than on the input token count.

## OK

**O1 OK (isolation core).** Worker homes are rebuilt from the baseline auth.json only, under the lock; launch
verification checks executable and argument hashes, the env allowlist, a home holding only auth.json, an empty `-C`
directory and instruction files in every ancestor; runtime files are inventoried by name and removed.

**O2 OK (auth safety).** Nothing reads or copies `~/.codex/auth.json`; only the baseline and worker homes hold token
text; `baseline_exp` and `wave_gate` log the exp timestamp only; propagation is atomic, under the lock, and refuses an
older `last_refresh`; the gate fails closed on a missing or unreadable exp and names the owner's `codex login`.

**O3 OK (budgets).** Allocations, reserves and caps match A4.5 and A4.13. I checked the zero rule and worst audit
placement by hand including the round 2 quarantine fallback: cold B at most 8, cold C at most 4, warm C at most 5, which
matches A4.4 and the dry run. Interrupted attempts keep their charge.

**O4 OK (gold error scoping).** `bootstrap.assess` invalidates only for ops in R with a proposed rule; other errors are
measured; malformed or missing output is a completion failure; BoolQ is never in R. The effect is backend wide for
materials, which I accept as the conservative reading of A4.6.

**O5 OK (cache certification).** The certificate pair is archived in git, its envelope hashes and decoder hash
verify, the applicability check binds model, effort, CLI version and decoder, replay fixtures pass, positive cached
input without the certificate is `unverified`, and the additive sensitivity reading is reported.

**O6 OK (gates arithmetic).** Thresholds are exact fractions (0.75, 0.5, 0.9, 1.10, 4.4, 1.6), ratios unrounded,
cold makespan not gated, bootstrap charged fully to cold B and C, BoolQ and pooling gates as written.

**O7 OK (resumable cells, apart from B3).** Terminal batches are read back and never resent, batch composition is
deterministic, `DONE.json` blocks reruns, requirements are enforced, first attempts precede retries.

**O8 OK (learner material).** The "Expectation:" paragraphs are stripped (verified on the rendered elong text), packet
ids are neutral, admission texts are checked before every launch and again by the scorer, R comes from the frozen
classification dated before the first learner call.

Signed: Opus council reviewer, code correctness lens, round 1.
