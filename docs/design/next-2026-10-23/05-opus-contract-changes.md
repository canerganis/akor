# Packaging contract review: Opus 5.5

**SIGN after five changes.** I agree with the rest: a Python facade in `oz_manual.py`, existing CLI commands, schemas,
exit codes and defaults untouched, no wire change, scheduler, replanner, importer or MCP, the 256-node limit, the
scope labels, and a zero-token gate that establishes usability and compatibility only. I checked the contract against
`oz_flow.py` and `oz_do.py` as they are.

## Changes

1. **Add a public `revise`.** The contract promises stale-input behavior on the documented path, but its four entry
   points give no way to add a source revision. Today only bench harnesses call `Flow.bump_source` directly
   (`bench/o1/o1.py:240`, `bench/step4/step4.py:294`, `v3.py:583`). Add
   `revise(request_id, settings, source, data, reason)`, wrapping `Flow.bump_source`, with no execution. The gate
   must also cover the user-level sequence, not only O1's mid-run hook:
   1. Run to delivery.
   2. Call `revise`.
   3. Call `run` again, which publishes a new generation (`<node>-g2`).
   4. Call `artifacts`, which returns g2. A read pinned to g1 reports it as superseded, not as current.

2. **Read paths open the database read-only.** `Flow.__init__` creates the directory, sets WAL and runs the schema
   inside `BEGIN IMMEDIATE`, so `status` or `artifacts` built on `Flow(...)` would create a missing flow and write to
   an existing one. Both must open `flow.sqlite` (and stage `inbox.sqlite`) with SQLite URI `mode=ro`, and return an
   explicit not-found for a missing flow without creating any file. Test: the file set and the database bytes are
   unchanged after `status` and `artifacts`, on both a missing and a delivered flow.

3. **One runner per request ID.** `oz_flow` has no flow-level lock: two `run` calls on one request ID would both
   execute host nodes and dispatch stages, and only publication reconciles. The facade takes an exclusive lock per
   request ID (a lock file under `flows/<id>/`, held for the whole call). A second concurrent `run` fails at once
   with a named error. Test it with two processes.

4. **Scope notice once per process, not on every call.** A library that writes to stderr on every `status` call
   floods any caller that polls. The facade prints the scope notice once per process, on its first call, and exposes
   the same text as `oz_manual.SCOPE`. The `route=fixture` and `workflow=repair-handoff-20/v1` lines are printed by the
   example script, which knows them; the library does not guess which example it is running.

5. **Name the example and its platform.** The gate tests O1's stale-A mutation, so the example is O1-derived. That is
   the right choice under the authoring rule, since O1 is the only workflow that needs a model. But O1's checks run
   model-written code in the Windows Job Object sandbox (`bench/o1/sandbox.py` refuses when `os.name != 'nt'`).
   The contract must:
   1. Label the example and its gate Windows-only, and describe the sandbox as bench-grade confinement, not a security
      boundary.
   2. Never edit `bench/o1` (freeze 32333561 stays valid). The example copies the files it needs into `examples/`, and
      a test pins each copy byte-identical to its frozen source.
   3. Have the gate skip with a named reason off Windows, not fail silently.

## Non-blocking

1. `oz_manual.admit(request, settings)` installs a flow, while `oz_flow.admit(graph, registry)` only validates one.
   I would name the facade function `install`, or document the difference. Astra owns the name.
2. The docs should say that admission starts the deadline, so an `admit` call long before `run` spends deadline time.
   This is the existing `Flow.install` behavior, which is correct.

After these, I review the final diff as signed.
