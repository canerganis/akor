**Council 2 verdict: HOLD before step 6.** Steps 4 and 5 are not conformant. This is a static review against the supplied record and local specification, not a test certification. No files changed or model calls made.

**1. BLOCKERs**

1. `oz_rulephase.py`, `RuleStore.adopt_rule`, `Learner.attempt`: a results primary key prevents duplicate insertion but provides no lease, epoch or computation fencing. Resume returns existing results without validating current ownership, input or bindings. Introduce an authoritative job settlement record with immutable payload and binding hashes, execution generation and competing rule/model settlement. Atomically verify authority, admission, quarantine, interpreter and complete pinned check evidence before settlement. Validate identity on resume. Preserve previous emissions as historical results.

2. `oz_rulephase.py`, `Learner.attempt`: inconclusive checks become ordinary fallback. Preserve an explicit `awaiting_verification` state. Fallback may compute an independent answer, but acceptance still requires every applicable pinned check to pass. The adoption boundary must reject missing, incomplete or nonpassing check evidence itself, rather than trusting its caller.

3. `oz_map.py`, `_learn_phases`; `oz_rulephase.py`, `RuleStore.wave`: bootstrap and audit scope are wrong. Reserve one experiment bootstrap containing exactly 16 jobs from each producer. Share its immutable answers and candidate artifacts between B and C, with independent subsequent execution state. Select `min(32, covered)` audits across the complete evaluation wave using frozen dataset identities, not separately per producer or filesystem path. Persist the complete eligible population and identical B/C selections before dispatch.

4. `oz_spool.py`, `DrainLock.acquire`, `heartbeat`, `release`, `_Drainer._dispatch`: lock creation exposes an empty file that another drainer immediately treats as stale. Heartbeat can overwrite a successor’s lock after checking the old token. A displaced drainer can capture and deliver after its dispatch returns. Replace this protocol with a process lifetime OS lock; prohibit takeover of a live holder merely because time elapsed. Fence every state mutation and dispatch authorization. Recover remote attempts through durable attempt identities, not lock ownership assumptions.

5. `oz_spool.py`, `submit`, `_pending_by_group`, `_deliver`: concurrent conflicting submissions can both pass the existence check and overwrite each other. Use transactional insertion or atomic exclusive publication with payload comparison. Require host issued identities and a validated binding schema; recompute hashes on read and compare full bindings. Carry request and reference mappings. Reject foreign result IDs and conflicting duplicate deliveries instead of silently discarding them.

6. `oz_spool.py`, `_Drainer.step`, `_dispatch`; `oz_map.py`, dispatch integration: blocking sequential calls prevent four concurrent launches and delay other groups’ one second deadlines. Keep one scheduling owner with four execution slots, deadline handling independent of completion, and durable reservations before launch. Integrate all arms through the spool. Use isolated subprocess environments because `_environ` is unsafe for concurrent calls.

7. `examples/bootstrap_shim.py`, `main.call_real`, `handle`, `_claim`; `oz_map.py`, `_learn_phases`: raw child stdout is lost on nonzero exit, successful stderr is discarded, and decoding exceptions bypass side publication. Capture complete raw streams, exit and timeout evidence under an allocated physical attempt ID before parsing. Reconcile marker creation, launch and capture separately. Require successful ordinary answer parsing and settlement before declaring bootstrap success; envelope status alone is insufficient.

8. `oz_rulephase.py`, `spec_excerpt`; `examples/bootstrap_shim.py`, `parse_envelope`, identity forwarding: supply effective amended semantics, preserve original AST bytes and enforce their 2,048 byte limit. Compact reserialization currently erases whitespace and can change numeric spellings. Reject invalid Unicode explicitly. Route identity must cover the shim, underlying adapter, executable dependencies and canonical configuration; forwarding the underlying identity alone is insufficient.

**2. Rulings**

The four unmet points:

1. **REQUIRE CHANGE.** A separate database is acceptable placement, not an exemption from D1 fencing. Implement blocker 1 without changing frozen core bytes, or explicitly reopen that freeze. Do not silently weaken settlement guarantees.

2. **REQUIRE CHANGE.** Implement awaiting verification as specified in blocker 2. Model fallback does not make unavailable checks available.

3. **REQUIRE CHANGE.** Implement shared bootstrap and a distinct B mode before step 6. B isolates fallback by producer; C pools compatible fallback across producers.

4. **OVERRIDE, amendment 2:** “A malformed bootstrap envelope or failed bootstrap answer MUST NOT trigger replacement answers or artifact revision. Preserve the failed attempt and invalidate efficiency. Infrastructure recovery MAY resume an existing invocation or retry a provably unlaunched attempt; every actual launch consumes budget. Unknown outcomes remain unresolved until reconciled.”

The implementer readings:

1. **OVERRIDE, amendment 2:** “Bootstrap synthesis MUST receive the complete effective language semantics, including D3 through D5, evaluation result representation and resource bounds. Worked E/B/M/V ASTs, conformance vectors and admission labels MUST remain hidden. Admission procedures MAY be omitted.” Pin this effective excerpt.

2. **REQUIRE CHANGE.** Extract each original AST JSON slice from the envelope. Apply the byte limit and hash to that slice, and admit and reevaluate those exact bytes.

3. **ACCEPT with qualification.** Failed or memo served audits are inconclusive and do not establish disagreement. They also do not satisfy the audit obligation. Memo service violates the pilot configuration and invalidates efficiency.

4. **ACCEPT with qualification.** Unresolved audits remain pending with unchanged identities and selections on resume. Pending or inconclusive required audits prevent a completed evidence claim.

5. **ACCEPT with qualification.** `sha256(oz_rule.py)` identifies the interpreter only while that file contains all mutable evaluation semantics. Otherwise bind its dependency closure and relevant execution configuration too.

6. **REQUIRE CHANGE.** Registry equality with the shim’s claimed route is insufficient. Recompute and reconcile the complete effective route before dispatch, including wrapper sources.

**3. SHOULD FIX**

Use contract typed canonical comparison for audits rather than serialized spelling alone. Preserve extracted string lexemes and decimal wire strings.

Make rule results undeletable, quarantine metadata immutable after transition, and idempotent inserts verify identical payloads. Record pending audits durably rather than reconstructing their existence from output.

Use monotonic time for scheduling, wall time for timestamps, and explicit platform durability guarantees for atomic file publication. Validate finite limits and cap pilot batches at 64.

**4. Step 6 and pilot**

The harness must exercise A, B and C on both backends. **Amendment 2:** add Sonnet materials B; retain Codex BoolQ and both backends’ materials warm A/C waves. Keep the global 50 call cap, backend allocations and existing gates. Freeze a revised reserve allocation before calls. If this expanded matrix cannot fit, report incomplete evidence rather than silently omit cells or increase authorization.

Four scripted producers must simultaneously submit 64 jobs each. A pools ordinary execution. B and C consume the same shared bootstrap through the spool, then separately execute the remaining 192 jobs, residuals and identical audits. Warm waves add 64 fresh materials jobs per producer, with unchanged rules and no learning.

Implement immutable physical attempt and arm allocation ledgers. Charge the shared bootstrap physically once and fully to each of B and C analytically, including elapsed time. Allocate producer shares reproducibly and reconcile totals. Mixed residual/audit calls need job membership, not one exclusive category.

Reserve calls atomically before every launch, including retries, telemetry, overflow and preparation. Enforce `oz_quota`, projected weekly usage and the 55% stop. Preserve unknown usage as unknown. Verify inclusive cached input and reasoning accounting from raw evidence.

Before authorization, run the entire matrix with fake adapters and zero external calls. Test concurrent submission, competing settlements, quarantine races, lock loss, every crash boundary, audit overflow, bootstrap failure and exhaustion against independent frozen oracles.

Improve efficiency through concurrent dispatch, prompt prefix reuse, compatible residual/audit packing and elimination of redundant admission work. Report gold correct jobs per token and second, cold and warm separately, with queue time, makespan, coverage, fallback errors and complete failure costs. Freeze arm order and scoring before calls; retain every failed gate.

