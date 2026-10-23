# Packaging final diff review (962a87b): Opus 5.5

**SIGN.** No blocking finding. All five contract changes are built and tested. `tests.test_oz_manual` passes 48 of
48 and the full suite passes 807 of 807 (run here, 341 s). `oz_flow`, `oz_do` and `bench` are untouched, and the
O1 freeze test holds.

## Deviations judged

1. **Read-only opening (`mode=ro`, or `mode=ro&immutable=1` at rest, retried on a changed stamp): accepted.** All
   three databases (flow, inbox, memo) run in WAL mode, so committed data reaches the main file only through a
   checkpoint, and uncommitted data never does. The read can go two ways:
   1. A writer appears during an immutable read. Then either `-wal` exists when the read ends (`_at_rest` is false,
      so the read is retried with `mode=ro` and normal locking), or the writer checkpointed and closed (the main file's
      mtime changes, so the read is retried). A torn or old view is discarded, never returned.
   2. A hard-killed writer leaves `-wal` and `-shm` behind. I reproduced this: a child process wrote 100 rows and
      exited without closing. The facade read went through `mode=ro`, returned all 100 rows and created nothing.

   Residual risk (low): on a filesystem with coarse mtimes (FAT or exFAT at 2 s, some network shares), a checkpoint
   that leaves the size unchanged inside one tick could escape the stamp. NTFS and ext4 are fine. One line in USAGE
   would cover it.
2. **`run.lock` left in place; `revise` takes no lock: accepted.** The OS releases the lock when its holder dies, and
   a test kills a holder. `revise` is one `BEGIN IMMEDIATE` transaction, and `Flow.current()` drops any acceptance
   that cites an older revision, so a revision during a run cannot be delivered as current.
3. **`revise` needs an already imported source: accepted.** It fails with the explicit `unknown source X` from
   `Flow.bump_source`, and the docstring says so.
4. **`oz.manual.status/1` with extra fields, `artifacts(target=None, generation=None)`, plain read after `revise`
   raises `stale`: accepted.** This matches what I asked for. The plain read refuses a stale delivery, and a read
   pinned to a generation reports `superseded` with `superseded_by` and `stale_sources`.
5. **One example directory for the fixture and O1: accepted.** The pin test, the "example never imports bench" test,
   the O1 freeze test and the Windows-only skip with a named reason are all present.

## Findings (all low, none block)

1. When `-wal` exists but `-shm` is missing (a copied or hand-cleaned workspace), a `mode=ro` read creates `-shm`. I
   reproduced it. This breaks "a read creates nothing" only in that abnormal state. Document it, or fall back to
   `immutable=1` only when no writer can exist, which the facade cannot know.
2. `status` computes `deadline_remaining_seconds` with `time.time()`, while `Flow` accepts an injected clock. This is
   harmless in production; tests with a fake clock would see a wrong remaining time.
3. `oz_manual` imports the private `oz_do._accounting`. That is fine today, and the read-only usage test pins the
   numbers to `flow_usage`. Any rename in `oz_do` must update the facade.
4. `status` reads the flow database and each stage inbox as separate snapshots, not one atomic view across files.
   This is acceptable for a status read. One sentence in the docstring would cover it.
