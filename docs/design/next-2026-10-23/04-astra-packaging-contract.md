Package a **Python-first facade in `oz_manual.py`**. Keep every existing CLI command unchanged. The following is the implementation contract, not an already available API.

1. **Public entry points**

   ```python
   from oz_manual import admit, run, status, artifacts

   admit(request, settings)
   result = run(request, settings)
   snapshot = status(request["request_id"], settings)
   result = run(request, settings)  # resume: identical call
   delivered = artifacts(request["request_id"], settings, target="package")
   ```

   `request` uses the existing `oz.flow/1` request and graph forms. `settings` is an explicitly constructed `oz_flow.Settings`; registries, checks, adapter, route, budgets and destinations remain host-owned. No configuration importer.

   - `admit`: validate through existing graph admission, then install without executing nodes or launching an adapter. First admission starts the original deadline. Identical admission is idempotent; changed work under the same request ID fails.
   - `run`: delegate to `oz_flow.run_flow`, including admission when necessary. Return the existing `oz.flow.result/1` result.
   - `status`: read authoritative persisted state without launching, repairing, extending deadlines or creating a missing flow. Report current targets, blocker, revisions, generations, launches and accounting coverage.
   - Resume preserves request identity, deadline, accepted history, consumed budget and delivery intents. Recover completed captures before considering another launch. Uncertain dispatches remain explicitly uncertain.
   - `artifacts`: return the current target’s destination, artifact paths, byte counts, SHA-256 values and citations. Require a committed, current delivery and matching files. Missing, conflicting or stale artifacts fail explicitly. Never republish during a read.

2. **Scope and required labels**

   Support manual finite DAGs of registered host/model operations, existing checks, durable recovery, revision-aware acceptance and local artifact publication. Keep the existing 256-node limit. No wire change, scheduler, replanner, importer or MCP.

   Every facade invocation must print this notice to **stderr**, leaving serialized results clean:

   ```text
   scope=manual-graph; acceptance=oz1g-selective-v1; delivery=local-files
   qualification=experimental; live-model-qualification=not-established-by-packaging
   ```

   The bundled fixture path must additionally print:

   ```text
   route=fixture; model_calls=0; new_billed_tokens=0
   ```

   For the O1 example, print:

   ```text
   workflow=repair-handoff-20/v1; experimental_sizes=1,4
   ```

   Both O1 sizes remain experimental, even where the generic model/size table contains a passing cell. Packaging grants no new qualification. Preserve failed-cell refusal and existing route, quota and deadline checks.

3. **Output compatibility**

   Preserve existing CLI formatting, schemas, exit codes and defaults. In particular:

   - `oz do` remains one compact JSON result, with exact accepted JSON values and the 4096-byte inline default.
   - Existing `oz status` remains content-free by default; `inspect` remains explicit.
   - Flow execution retains its existing result, accounting coverage and artifact references. Keep the internal stage inline limit of 65536 bytes.
   - No automatic narrative, prompt, source, candidate or artifact-body dump. Unknown usage stays unknown. SQLite remains authoritative; `execution-record.json` remains an export.

4. **Zero-token acceptance gate**

   Ship one complete documented fixture example outside `bench/`, including request, registry, settings, source files and fixture adapter. It must require only standard-library Python and an empty workspace. No private setup, copied runtime databases or state repair.

   Add the acceptance command:

   ```text
   python -m unittest tests.test_oz_manual
   ```

   It must exercise that documented public path and establish:

   - Stored fixture replies pass the existing acceptance and independent artifact checks. Capture content and provenance remain distinguishable from newly billed usage.
   - Hard exits at `worker.after_capture` and `flow.publish.after_manifest`, followed by the identical `run` call, recover the capture without another invocation and reconcile publication without duplicate delivery.
   - The existing O1 stale-A mutation invalidates old verification, prevents stale delivery, retains history, reuses unchanged B/C/D inputs and delivers with A revision 2.
   - Repeating completed work makes no new adapter invocation; conflicting request reuse fails.
   - Status and artifact reads cause no execution. Missing or stale delivery cannot appear successful.
   - No provider executable or network call occurs. Fixture invocations and historical capture usage are reported separately from zero new model calls.

   The full baseline suite and focused invariants must also pass. This gate establishes usability and compatibility only.

No files changed or tests executed. Implementation and contract review remain pending under the signed quota gates.


