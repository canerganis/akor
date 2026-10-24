# Council 3, Opus member (static read of 43bb009; tests.test_oz_host 17 OK at that commit)

Verdict: HOLD. Two confirmed blockers and one infeasible matrix cell.

## Council 2 blockers
Astra 1 to 6 closed (settlement fencing, awaiting_verification, shared bootstrap and wave audits, OS host lock, transactional submit, four-slot scheduler with per-child env). Astra 7 partly closed: bootstrap "ok" only requires oz_do acceptance (ArmHost._bootstrap); a failed registry settlement in _bootstrap_row does not invalidate efficiency. Astra 8 closed for AST bytes; ruling 6 partly closed: ArmHost trusts identity['do_route'] and never recomputes adapter_hash before a launch. Opus B1 to B5 closed. Core frozen modules: diff empty.

## New findings (line numbers at 43bb009)
1. BLOCKER A, resume replaces answers: the spool submission tag comes from the keys of the current group (oz_host.py:708); run_wave (920 to 929) and _rule_arm re-dispatch every unsettled job; settle_model's failed path leaves the settlement open. A crash during settlement or a second run_wave sends unsettled and check-failed jobs under a new submission and a new physical call.
2. BLOCKER B, calls missing from the ledger: Ledger.finished stores no calls when the child returns no execution (430 to 440); reconcile_unknown continues if the reconcile child fails (823 to 831). The call is in calls.jsonl and the budget but not in tokens, while usage reads complete.
3. Fix before freeze: a crash between admit_side and _import_allocations (1147 to 1153) makes the resumed arm skip importing the shared bootstrap charge; C cold tokens understated.
4. Fix before freeze: _bootstrap imports the record without comparing binding_key, assignment_sha256 or worker_hash with the importing host.
5. Minor: reconcile_unknown passes elapsed=None (831), overwriting the attempt's elapsed time.
6. Sonnet B cell cannot fit: A 8 + C 3 + B 4 = 15 > 13; the revised allocation is not frozen.
7. Suspected: on timeout only the python child is killed; on Windows the CLI child may keep spending. ChildLauncher's 3600 s default is not tied to call_timeout_seconds.
8. Suspected: committed submit accepts only self.op; multi-operation workloads need the unfinished WIP; freeze must be on a clean tree.

## Freeze record must pin
Clean commit and SHA256 of host, spool, rulephase, map, route, shim, oz_rule.py and every core module; spec excerpt and instruction hashes; adapter JSONs and oz_route.build output per backend, interpreter path and version; registry manifest, admission labels, 16 challenges per operation, check specs; every dataset file and ids per producer and wave; seed 20261024, bootstrap assignments, arm order, audit selection rule; caps JSON with the Sonnet B decision; host parameters (slots, max_records, max_wait, rule_delivery, audit_retry, timeouts, deadline, max_input_tokens, experimental_sizes); dry-run output hash; sealed gold and scorer hashes.

## Fixes proposed
Terminal check-failed settlement; submissions named by round and frozen population; parent reads run_dir/calls.jsonl and treats launched attempts without call records as unknown usage; idempotent allocation import with identity assertion; keep original elapsed; recompute adapter_hash in launch_gate; kill the process tree on timeout; dry_run with real caps; tests for settlement-window and import crashes.
