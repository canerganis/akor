# Council 2: Opus review of build steps 4 and 5 (commit 1dced66)

All 88 tests pass (22 s, Windows 11). The real spec_excerpt() holds no worked AST, vector or E/B/M/V field name. D1 adoption, the triggers and memo isolation look correct.

## BLOCKERs

1. **Audit waves are per producer submission, not per evaluation wave.** oz_map.py:757-761 and oz_rulephase.py:310-331 select min(32, covered) per (producer, submission, rule). Four producers give up to 128 audits per wave, not 32, breaking the record's four pooled calls and C's allocation of 7. Selection uses path strings; D8 requires frozen dataset IDs. Fix: `wave(wave_id, rule, seed, dataset_ids)` with primary key (wave_id, rule), wave_id = canonical([backend, workload, wave]); select over the union of covered dataset IDs across producers; B and C read one persisted row.

2. **Bootstrap claim races across producers.** oz_map.py:653-654 tests `not store.rules(key)` outside any transaction, and the `bootstraps` primary key (oz_rulephase.py:84-86) includes producer and submission. Two producers on one key both bootstrap: a candidate revision and a second charge. Fix: table `learning(binding_key PRIMARY KEY, owner, request_id, state)` claimed under BEGIN IMMEDIATE; losers fall back or wait. In the pilot only the drainer bootstraps.

3. **OZ_BOOTSTRAP can reach a non-bootstrap call.** oz_map.py:629-631 sets it in os.environ for the whole process, and bootstrap_shim.py:180-182 claims the marker for any request. Under concurrent dispatch a residual call that starts first becomes the bootstrap. Fix: the config lists the bootstrap job IDs and the shim passes through unless `set(request['ids']) <= set(config['job_ids'])`. Pass environment per child process.

4. **Bootstrap retries are tagged residual.** oz_map.py:833-838 tags only the receipt that wrote a side file. After a malformed envelope or a failed job check, oz_do's retry calls in the bootstrap run count as residual. Step 6 charges the bootstrap to both B and C, so these tokens would land in C alone and bias gate 5. Fix: tag every call in the bootstrap run_dir as `bootstrap` (subkind `retry`). Set `efficiency_valid: false` on any bootstrap status other than ok (kill 2).

5. **Incomplete audits do not block reuse.** In oz_map.py:798-804, inconclusive and pending audits neither quarantine nor block anything. A wave with zero conclusive audits still feeds warm reuse. Fix: after the reserve retry, a wave is `audited` only when every selected audit is conclusive. Otherwise warm reuse is refused and efficiency is invalid.

## SHOULD-FIX

1. Windows: os.replace fails with PermissionError while another process has the target open (oz_spool.py:97, 288; reads at 104-108). Polling producers can crash delivery. Retry PermissionError, bounded, on writes and reads.
2. Windows: names are case-insensitive, so producers `P1` and `p1` share fragments and results files (oz_spool.py:53, 157, 446). Reject names that collide after casefold, and device names.
3. pid_alive (oz_spool.py:181-201) reads GetLastError through windll. Use `WinDLL('kernel32', use_last_error=True)` and store the process creation time in the lock; a reused pid holds a dead lock for 6 h.
4. heartbeat (oz_spool.py:279-288) is a separate read and write, so a woken drainer can overwrite a new owner's token. Write it under the guard file.
5. Assert that the bootstrap plan is exactly one packet (oz_map.py:671-675). The gate ignores the shim's ~7 kB addition; include it.
6. Leakage lint before the bootstrap. The registry contract is free form (oz_registry.py:383). Assert the augmented prompt holds no admission text, label or worked AST, and bootstrap inputs are disjoint from admission texts by resolved hash.
7. Failed calls: oz_map.py:854 adds `tokens or 0`. Reconcile failed call usage from the OZ_ENVELOPE_PATH captures; partial usage is invalid, never zero.
8. bootstrap_shim.py:241-249 drops the real stdout on failure. Relay it (D9).
9. Rows from the same wave that the run has not yet returned stay accepted after a disagreement (oz_map.py:866-878). Ask Astra whether they may fall back (lower kill 1 risk).
10. oz_rulephase.py:338 uses time.time, not self.clock.

Open points 1 and 2 are acceptable; point 4 only with BLOCKER 4.

## Test gaps

1. A system_text test against the real spec_excerpt(); the current one uses 'SPEC'.
2. Two producer processes racing one binding key; a residual dispatched while OZ_BOOTSTRAP is set.
3. A wave across four producers selects exactly 32; B and C selections are equal.
4. Pending audit on resume; inconclusive audit; cross-process quarantine during adoption.
5. Bootstrap split by the input budget; retry tagging and accounting.
6. Spool: reader open during replace, case collisions, multi-process submit, crash after a real oz_do call (no second call).
7. Failed call usage reconciliation.

## Step 6 design

1. **Topology.** Run one drainer host per (backend, workload, arm). It owns the rule store, bootstrap, rule phase, audits and every oz_do call; producers only submit and collect. The spool bindings are learner.key plus arm and backend, so arms never pool. In B, the bindings also include the producer.
2. **Shared bootstrap.** After all four fragments arrive (bounded wait), take each producer's 16 jobs by frozen assignment, not arrival, as one 64-record batch. For Codex, the call runs once and B and C import the same admitted row, matched by source and AST hash.
3. **Rule phase before chunking.** Covered jobs are delivered as rule rows with zero calls. Fallback plus audit jobs go to the chunk queue, filled to exactly 64.
4. **Concurrency four.** Dispatch up to four reserved batches at once. Each is a child process running one oz_do request with request_id derived from batch_id, so re-dispatch resumes oz_do's capture instead of calling again. Cap slots with an oz_quota group of 4; heartbeat on its own thread.
5. **Accounting.** The physical ledger has one row per call_id, built from calls.jsonl plus the envelope captures: kind, input, cached, output, reasoning, elapsed, outcome. The allocation ledger has rows of (arm, backend, workload, wave, kind, call_id, share). The bootstrap gets share 1 in B and in C and physical count 1. Pooled calls split producer shares by records. Invariants: every call_id has exactly one kind; allocations equal physical calls plus the listed bootstrap double charge. Reserve each batch against the frozen allocation (Codex 37, Sonnet 13) before dispatch. Audits and retries use the reserve; exhaustion stops launches (incomplete). Check the 55% Claude threshold per Sonnet launch.
6. **Dry run.** Use a replay adapter that serves recorded usage from historical raw captures and makes zero model calls. Assert allocations, 32 audits per wave, equal B and C selections, reconciliation, and identical ledgers under crash injection. Freeze its hash.
7. **Yield.** Fill chunks to 64 to amortize the ~24k Codex intercept; audits ride in residual chunks; pool C remainders. Disable memo, use one workspace per arm and a seeded arm order; report uncached input. High warm coverage leaves one call (fallbacks plus 32 audits), the clearest route past the warm gates.
