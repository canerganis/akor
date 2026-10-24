# Implementer notes for council 2 (steps 4 and 5, commit 1dced66)

Core runtime is hash-frozen by experiment freeze records, so everything lives in new modules.

Step 4 (Opus implementer): examples/bootstrap_shim.py wraps the real adapter; without OZ_BOOTSTRAP it is a
passthrough; first call creates an O_EXCL marker so exactly one physical call carries the bootstrap; appends the
858-char instruction (SHA256-pinned), a spec excerpt, contracts with eligibility, envelope shape; strict envelope
parse; durably publishes raw reply, rules, status before stdout; malformed envelope -> fixed non-OZ/1g reply with
real usage (worker logs invalid_response, tokens kept). oz_rulephase.py: own SQLite rule store with triggers
(immutable AST, bindings, admission, provenance; admitted -> quarantined only); binding key = 6 registry hashes +
interpreter (oz-rule/1 + sha256 of oz_rule.py) + input policy + worker_hash + map contract hash; registry resolved
with claimed worker_hash; a binding with any stored entry is never re-learned. adopt_rule: BEGIN IMMEDIATE, re-read
status/binding/AST hash, re-hash resolved input, re-evaluate AST, require same type and canonical value. Consumer
checks: registry checks + map --check via oz_accept.run_checks; inconclusive = failure -> fallback. Audits:
min(32, covered), ordered by sha256(canonical([seed, path])), persisted per (producer, submission, rule,
covered-set hash), D8 audit names, appended to residual oz_do requests; disagreement quarantines in one
transaction. Rows: phase, call_kind; receipt: calls_by_kind, call_ledger, accepted_by_checks vs correctness note.

Points the implementer could not meet as written (core frozen), for the language owner to rule on:
1. adopt_rule lives in the rule store, not oz_runtime.Inbox; rule jobs never enter an oz_do inbox, so leases,
   epochs and settlement fencing do not apply; atomicity is the rule-store transaction plus a results primary key.
2. "Unavailable checks await verification": inconclusive falls back to the model; no awaiting state.
3. One shared bootstrap answering 16 jobs per producer for 4 producers needs the step 5 spool; today one bootstrap
   per producer submission; arm B (producer-local fallback) is not a separate mode yet.
4. Bootstrap jobs that fail (all of them after a malformed envelope) are retried by oz_do's ordinary retry
   (max_attempts 2) as passthrough calls tagged residual: a fresh model answer, not envelope repair. Allowed?
Readings to rule on: the spec excerpt shown to the model is the language part only (no worked E/B/M/V ASTs, no
conformance vectors, no admission text, no D3 to D5 text) so the designer's rules cannot leak; AST bytes are the
compact re-serialization of the parsed envelope object; an audit whose model job failed or was memo-served is
inconclusive and does not quarantine; unresolved audit is pending, decided on resume; interpreter version is the
sha256 of oz_rule.py; the owner must freeze the registry route equal to the shim adapter's route.

Step 5 (Sonnet implementer): oz_spool.py: submit() atomic fragments; one drainer with an O_EXCL lock (pid, epoch,
token; stale if pid dead, lease over 6 h, or unreadable; takeover via guard file; LockLost on token change);
groups by canonical hash of full bindings; exact 64-record chunks, remainder flushes when the oldest waited
max_wait; states reserved -> dispatched -> captured -> delivered, capture written before state; a capture is never
re-dispatched; dispatched without capture re-dispatched up to 2 attempts then dispatch_abandoned; D8 ids with a
collision registry; per-row submitted/dispatched/delivered times. Dispatch is sequential: the caller owns the
pilot's concurrency of four. Not yet wired into oz_map.
