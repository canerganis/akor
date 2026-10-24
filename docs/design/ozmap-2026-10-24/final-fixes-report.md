# Final pre-freeze fixes (commit 29d45af), implementer report

Suite: 1389 OK (2 skipped), zero model calls, zero network. Frozen core files unchanged. Tests named below are in
tests/test_ozmap_close.py unless noted.

- N1 Codex isolation: every `codex exec` runs with a fresh empty mkdtemp directory checked to be outside any repo, as
  both `-C` and the process cwd, deleted afterwards. `leakage()` flags any event that is not thread/turn start or end,
  a top-level error, or an agent_message/reasoning item (unknown types flagged). Such a call exits 86, no reply; the
  capture keeps leakage and usage. The host records every envelope in an immutable table, refuses that call's answers
  (`tool_use_leakage`), marks efficiency invalid; `gold_accessed_during_run` is derived from all envelopes.
  Claude: argv pinned with `--tools ''`, `--setting-sources ''`, `--strict-mcp-config`; `num_turns != 1` or any
  permission denial exits 86 and keeps the envelope. Tests test_n1_*.
- N2 one driver: `pilot.drive(ctx)` is the only driver for `run --live` and `dry`: same ArmHost, Scheduler, SlotPool,
  settlement, registry file, route verify, launch gate, oz_quota, frozen max_wait 1.0, ChildLauncher children. Dry
  differs only by fake codex.exe/claude.exe (bench/ozmap/fake_cli.py, deterministic bytes) first on PATH, refuses if a
  real CLI resolves; freeze records the dry output sha256 (two runs gave the same hash). Tests test_n2_*.
- N3/B9 quota: every launch (telemetry, retries, bootstrap) reserves an oz_quota slot via QuotaStore; order gate,
  route, slot, quota, budget; refusal releases everything. 99% stop: no programmatic Claude usage source, so
  telemetry and run need `--claude-weekly PCT` recorded per session; `pilot.py quota --percent` appends readings;
  launches refuse without a reading for the batch or at >= 99%. Tests test_n3_*.
- B9 tree kill: child assigned to a Windows job object (process group on POSIX); kill and poll until 0 active
  processes; `tree_killed` True only after that; an unconfirmed tree keeps slot and quota, attempt unresolved,
  violation `process_tree_unverified`. Tests test_b9_*.
- Telemetry: two identical requests; Codex certified only if both are on the frozen Codex worker hash, no leakage,
  equal system and prompt hashes, all components present as counts, input_tokens unchanged on the repeat while
  cached grows. Core calls read after failures; unresolved usage listed. Semantics per backend; Codex never certifies
  Sonnet. Tests test_telemetry_*.
- B4 resume after quarantine restores the staged r3 continuation. B5 replayed rounds reuse the original persisted
  grants. B6 `_attribute` hard-errors on differing request, membership or usage component; compatible observations
  fold into an immutable call_observations table with a resolved view. B8 charged makespan = measured makespan + the
  imported bootstrap's elapsed, nothing subtracted; interrupted spans kept; score uses it and reports measured
  makespan separately. B10 audit completeness reads every persisted audit row of the wave. B11 dependency closure
  read from the launched interpreter (every loaded module with path and sha256, interpreter sha256 and version),
  frozen; unversioned or declared-external dependencies and callable route checks refused in pilots. B12 BoolQ
  admission separated from evaluation by id, text and passage (two shared-passage admission rows replaced by a seeded
  draw; evaluation unchanged); every prompt the fake CLIs received is scanned for worked ASTs and admission material.
- Extras: per-child OZ_ENVELOPE_PATH (plus harvesting oz_runner's per-receipt captures); failed-call usage folded from
  its envelope; freeze records the interpreter; verify_freeze needs the full file set.

Dry run (fake CLIs, 0 external calls): 44 physical calls (Codex 29 incl. 2 telemetry, Sonnet 15), reconciliation ok,
telemetry ok, no leakage, evidence complete in every cell. Projected verdict "killed: materials efficiency gate
failed" (warm makespan ratio 1.0 under the replay assumption that every call takes a 64-job call's time); BoolQ time
4.758 (fails), tokens 1.044; safety, validity, pooling pass.

Open decisions for the language owner: D1 usage_components per backend (Codex input, cached, output, reasoning;
Sonnet input, cached, cache_creation, output, because the Claude CLI reports no separate reasoning count); D2 Sonnet
usage semantics "adapter-constructed inclusive, not telemetry-certified" (Sonnet telemetry allocation is 0).
