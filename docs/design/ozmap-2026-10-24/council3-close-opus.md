# Council 3 close, Opus member (static read of 3afdbf7)

Run here: `pilot.py plan` (54 allocated, 44 nominal, matrix fits), `pilot.py dry` (0 external calls, 44 physical, reconciliation ok, every cell complete, real BoolQ), `tests.test_oz_host_council3 tests.test_ozmap_pilot` 82 OK. No freeze.json or routes.json; an untracked identity.json appeared during this review from another session.

## Blockers

| Blocker | State | Evidence (file:line) |
|---|---|---|
| B1 bootstrap config | CLOSED | oz_host.py:1639, used 1393; real bootstrap child asserted in tests/test_oz_host.py:403 |
| B2 no replacement for pending bootstrap | CLOSED | oz_host.py:1664 rows stay bootstrap_pending; 1993 failed answers terminal |
| B3 one packet, settle before record | CLOSED | oz_host.py:1915 packet check, 1950 settlement, 1962 status ok, 1688 importer inherits invalidity |
| B4 durable plan | CLOSED | oz_host.py:1233 stored round, 1282 plan_closed, 144 names from round only |
| B5 authority | CLOSED | oz_host.py:1249 claim before dispatch; oz_rulephase.py:573, 790, 515 fenced resume and mark_awaiting |
| B6 append-only accounting | CLOSED | oz_host.py:482 first evidence trigger, 655, 676, 1429 parent reads calls.jsonl |
| B7 membership allocation | CLOSED | oz_host.py:1289, 2070 |
| B8 timing | CLOSED | oz_host.py:2160 charged makespan, 1509 first delivery kept |
| B9 caps, slots, shutdown | PARTIAL | check_pilot 913, SlotPool 372, Budget.reserve 862, oz_spool.py:503 close waits; oz_quota is never called (see N3) |
| B10 evidence derivation | CLOSED | oz_host.py:2109 persisted violations, 2117 awaiting, 1817 memo audit, 2137 spool rejections |
| B11 route at launch | CLOSED | oz_host.py:1407 via 1340; oz_route.py:391 env reaches probe, 424 verify |
| B12 sealed wave | CLOSED | oz_host.py:1147, 1171, 1872, 2317 barrier |
| Opus A resume | CLOSED | as B4; oz_rulephase.py:496 check failure is terminal |
| Opus B missing calls | CLOSED | oz_host.py:1429, 1486 |
| Opus 3 import crash | CLOSED | oz_host.py:1862 import on every resume, 719 idempotent |
| Opus 4 import identity | CLOSED | oz_host.py:1872 |
| Opus 5 elapsed | CLOSED | oz_host.py:676 never writes elapsed; trigger 482 |
| Opus 6 Sonnet B | CLOSED | pilot.py:76 (owner decision 2, amendment 3) |
| Opus 7 process tree | CLOSED | oz_host.py:302, 307, 358 |

Core frozen modules unchanged.

## Readiness questions

Wrong rule answer accepted. Possible by design when it passes checks and escapes the audits; rule rows wait for the audit decision (oz_host.py:1786), adopt_rule rechecks admission and provenance in one transaction (oz_rulephase.py:589), and gate 1 counts every accepted rule gold error (score.py:115). Correct.

Charging. Bootstrap is physical for the owner and imported in full for the other arm; audits, retries and failed calls are charged from calls.jsonl. Unknown usage is never zero: the cell turns efficiency invalid. So one failed Codex call voids gate 2, since its usage goes only to OZ_ENVELOPE_PATH, which the host never sets.

Caps. Cannot be exceeded: every launch reserves bucket and global cap first (oz_host.py:1410), request ids are unique per arm (1188), execute admits one call per request (250), reconciliation runs with cap 0.

Freeze guard. `run --live` and `telemetry` refuse without freeze.json, on any hash, dataset or plan drift, without approval, and without verified telemetry (pilot.py:871, 975).

Data. BoolQ hashes to the recorded 0c86a504 (3270 rows, byte-exact). Materials are deterministic from data.py, pinned at freeze by dataset_digests.

Oracle. Imports only decimal and re; matches MAT_D; ties and undefined records excluded.

Codex model. gpt-6.1-sol, medium matches ~/.codex/config.toml, the replayed ledger (pilot.py:104) and HANDOFF (Sol 6.1 medium 96/96 and 192/192; Luna excluded; Astra owns the language, so is rightly not the worker). The record pins only model, effort and CLI version. Acceptable.

Expected verdict. The dry projection fails gate 4 (time 4.76) and gate 3 warm makespan (0.954, 1.0); amendment 3 accepts this.

## New blockers

N1. Gold and hidden material are readable by the Codex worker. `codex exec -s read-only` (codex_cli_adapter.py:177) may read any file; its cwd is the adapter directory (oz_workspace.py:108), which holds the worked ASTs (bootstrap_shim.py:96). The repo holds BoolQ labels (bench/ozmap/data/boolq-superglue-val.jsonl) and admission labels (registry.json). This breaks A2.2 and "gold inaccessible until scoring". Nothing detects tool use: parse_events (codex_cli_adapter.py:57) ignores non-message items, and the manifest writes `gold_accessed_during_run: False` as a constant (pilot.py:993). Sonnet is safe (`--tools ''`).

N2. The dry run is not the live path. It uses oz_host.dry_run (2340) instead of pilot.run_live, InProcessLauncher with CallableShim (2388), no route check or launch gate, in-memory manifests instead of registry.json (pilot.py:555), and max_wait 0 (pilot.py:582). Only refusal tests cover run_live (tests/test_ozmap_pilot.py:493).

N3. Amendment 3 keeps oz_quota binding; the live gate checks only the global cap (pilot.py:904).

Minor: the freeze omits the interpreter (pilot.py:765); verify_freeze accepts a partial file set (797); the telemetry inclusive check passes with zero cache (960).

## Verdict: HOLD

Minimal list:
1. N1: run Codex in an empty temp cwd outside the repo. Make any non agent_message item in the event stream a leakage violation that invalidates efficiency. Derive gold_accessed_during_run from that check.
2. N2: one driver function shared by run_live and dry, executed with ChildLauncher, registry.json, route check and launch gate against fake `codex` and `claude` executables replaying recorded usage. Freeze the hash of its output.
3. N3: route Sonnet launches through oz_quota, or record a written Astra ruling that Budget plus SlotPool satisfies it.
4. Set OZ_ENVELOPE_PATH per attempt and keep failed call usage as evidence. Add the interpreter to the freeze. Require the full file set in verify_freeze.

Then identity, freeze, dry, sign.
