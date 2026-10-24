# Replication harness: red team round 3 (2026-10-25)

Reviewer: one fresh Opus subagent (claude-opus-5-5, high effort), logged in call-ledger.jsonl as `opus / red-team-r3 /
review` (Opus 23 of 40 after the entry; Astra 11, Fable 2, Sonnet 1). Target: `bench/ozmap_rep/` at fc60457 (council
round 2 fixes), before its freeze. Goal: make the harness produce invalid evidence that it does not flag. Method: code
reading, fakes and temporary directories. No `codex` or `claude` was run (the pinned `codex.exe` string table was read
with `grep -a`, never executed), no Codex or model call was made, the real baseline, run directory, experiment ledger
and session files were not read or written, owner profile state was inspected by name and mtime only (never file
content, never token text), and the sealed reviewer ASTs were not read.

Verdict: do not freeze. Three blockers, each with reproducing tests in `bench/ozmap_rep/redteam/test_redteam_r3.py`
(13 tests, all fail on fc60457; the round 1 tests and the round 2 tests other than the disputed RT2.1 still pass).

```
python -m pytest bench/ozmap_rep/redteam -q      14 failed, 21 passed in 33 s
                                                 (13 round 3 tests, plus RT2.1 under dispute D-R2-1)
```

These tests make `python -m pytest bench/ozmap_rep -q` red on purpose until the fixes land.

## Blockers

### RT3.1 The pre-launch instruction check misses the discovery locations of the pinned CLIs, and the live working directories sit under the owner profile (A4.2)

A4.2: "Before every call, verify ... effective instruction sources, including ancestors. Mismatch prevents launch. If
instruction discovery cannot be contained, use an isolated account or container." `isolation.instruction_scan`, used by
`verify_launch` (Codex) and by `prepare_call` (Sonnet), looks for three file names only: `AGENTS.md`,
`AGENTS.override.md`, `CLAUDE.md`. The pinned Codex binary names a wider set of capability locations, with `.git` as
the project root marker:

```
$ grep -a -o "[ -~]\{0,120\}\.agents[/\\\\]skills[ -~]\{0,120\}" .../0.160.0-x86_64-pc-windows-msvc/bin/codex.exe
skills.agents/skillsplugins/cacheexec-server\src\discoverV2\capability_locations.rs
mcp.json.codex.codex/config.toml.codex/agents.codex/hooks.agents.agents/skills.git, projects
```

A skill directory, a project `config.toml`, custom agents, hooks, an MCP server list, or a Claude memory or rule file
(`.claude/CLAUDE.md`, `CLAUDE.local.md`, `.claude/rules/*.md`) in any ancestor of the working directory passes every
pre-launch check:

```
.agents/skills/callister-materials-science/SKILL.md in an ancestor of the working directory passed every pre-launch
check (A4.2): verify_launch [], instruction_scan found [] unreadable []
(same for .codex/skills, .codex/config.toml, .codex/agents, .codex/hooks, mcp.json, .claude/CLAUDE.md,
CLAUDE.local.md, .claude/rules)
```

This is not hypothetical for this machine. The default live run directory is `Path.home()/.ozmap_rep/runs/replication`,
so every live working directory `D/work/slot-<k>` (Codex and Sonnet) has the owner profile `C:\Users\can02` as an
ancestor. That profile holds `.codex` (the owner's Codex home, plugins included), `.claude` (with the owner's global
`CLAUDE.md`) and `.agents/skills` with skills such as `callister-materials-science`, a materials science skill in the
domain of the four tensile-test ops. The harness overrides `HOME` and `USERPROFILE`, which does not redirect a profile
resolved from the OS (Windows known folder), and it never scans the profile. Whether codex-cli 0.160.0 lists user
scope skills from the real profile is not observable without a model call; `skip_host_skill_discovery` is an "under
development" feature whose scope is not established, and the round 2 observation that the exec stream maps only eight
item kinds still stands. The pilot's leak was a skill file in the owner's install; the replication keeps the same
files one ancestor walk away and checks for none of them.

Tests: `test_rt3_1_a_discovery_location_in_an_ancestor_blocks_the_launch` (9 parametrized cases) and
`test_rt3_1_the_live_working_directories_are_not_below_the_owner_profile`.

Fix. Move the live run directory (and with it every worker home and working directory) to a location with no owner
state in any ancestor, for example a dedicated top level directory, or run the cells under an isolated account or
container as A4.2 allows. Extend the ancestor scan to every location the pinned CLIs discover: `.agents/`,
`.codex/` (any content), `mcp.json`, `.claude/` (any content), `CLAUDE.local.md`, `AGENTS*.md`, with a frozen list
derived from the string table and archived with the freeze. Any hit, or any unreadable ancestor, refuses the launch.
P5's effective context annex should state which user scope roots the pinned CLI resolves and how.

### RT3.2 Token separation is exact hash equality, so a stale copy of the owner login passes (A4.2, RT2.6)

The RT2.6 fix compares SHA256 of the baseline's access and refresh token strings with the owner's `~/.codex/auth.json`
and the runner's `CODEX_HOME`. A copy of the owner's `auth.json` taken before the owner's Codex app rotates its tokens
(the same login: same `session_id` and `auth_time` claims, an older access token, a refresh token the owner has since
spent) has different strings and passes:

```
a baseline copied from the owner auth.json before the owner's next token rotation (same login session and auth_time)
passes the token separation check (A4.2, RT2.6)
```

The first worker refresh then presents an already used refresh token of the owner's login family, the case the
pinned CLI reports as "refresh token was already used" and that a rotating authorization server answers by revoking
the family, the owner's current tokens included. This is the owner login breakage RT2.6 was meant to close, reached by
waiting for one ordinary refresh.

The check also passes when there is nothing to compare. The joint decision of the round 2 deadlock requires that "an
unreadable existing source or unexplained credential representation is never treated as different", and
cli-flags.json records `secret_auth_storage` as stable and enabled by default for the owner's own CLI (the frozen argv
disables it for workers only). An owner `~/.codex` with configuration and no `auth.json` (credentials in the OS
store) gives `token_hashes() == {}` and no problem. On this machine `~/.codex/auth.json` was last modified on
2026-10-15 although the owner home runs Codex calls daily, so which store holds the owner's live credential is not
established either.

Tests: `test_rt3_2_a_rotated_copy_of_the_owner_login_is_not_a_separate_login` (with a separate login as a passing
control) and `test_rt3_2_an_owner_credential_outside_auth_json_is_never_treated_as_separate`.

Fix. Compare login identity, not only token strings: the hashes of the access token `session_id` (and
`pwd_auth_time`) and of the id token `auth_time` and `sid` claims; equal values refuse with exit 11 and the reseeding
command. Record those hashes in `auth-lineage.jsonl` at the first dispatch. Treat an owner Codex home without a
readable `auth.json`, or one whose file store cannot be shown to be the live store (for example `secret_auth_storage`
enabled in the owner's configuration), as unexplained: refuse, and let the owner record the provenance of the baseline
login (a fresh `CODEX_HOME=~/.ozmap_rep/baseline codex login`, with its time) instead.

### RT3.3 The live Codex quota stop reads whatever sessions directory the command line names, and records none (A4.12, P3)

`run cell`, `telemetry` and `features` accept `--codex-sessions-dir` in live mode, and the P3 gate reads only that
directory. `evidence/quota.jsonl` and `evidence/quota-gates.jsonl` keep the percentage and the reading time but not the
directory or file, so neither the scorer nor a reviewer can tell which reading released a group. With the owner's
sessions at 85% and a named directory at 10% (for example a test fixture left in a temporary directory, or a typo
pointing at another Codex home), live telemetry launches both charged calls:

```
with the owner reading at 85% the live telemetry launched ['telemetry.r1.b00.t0', 'telemetry.r2.b00.t0'] (exit 0) on a
named sessions directory; quota gate evidence: [{'ok': True, 'percent': 10.0}, {'ok': True, 'percent': 10.0}]
```

The same holds for every live Codex cell. A4.12's 80% stop exists to protect the owner's account, and P3 says no
reading is estimated; here the reading need not be the owner's at all.

Test: `test_rt3_3_the_live_quota_stop_reads_the_owner_sessions_not_a_named_directory`.

Fix. In live mode refuse any sessions directory other than `config.CODEX_SESSIONS_DEFAULT` (tests monkeypatch the
constant, as this test does), and record the resolved source file, its account hash and the event timestamp in every
quota gate row; the scorer checks that every live Codex group has a gate row whose source is under the owner sessions
directory.

## Observations (not blocking, recommended before the freeze)

1. The round 2 `Live` fixture writes session readings without an event timestamp. Since the P3 gate, every live cell
   after telemetry exits 10 before its first call ("no quota observation covers the completed live Codex calls
   ['telemetry.r2.b00.t0']", reproduced with the unchanged fixture). Round 2 tests that assert the absence of a call
   (the cell half of RT2.6) now pass whatever the code under test does. The fixture should write timestamped readings
   after each live call, and those tests should assert that the cell reached its dispatch.
2. `_settle` writes `DONE.json` (or `SETTLED.json`) before `state.json` says `complete`. A runner that dies between the
   two leaves a cell that `_preflight` refuses to rerun forever and that the scorer reports as `running`: the cell is
   lost without a recovery path. Recovery could derive the state from DONE or SETTLED.
3. Round 2 observation 2 is still open: `claude_map_adapter.tool_use` reads `OZ_MODEL` from the process environment of
   the runner and of the scorer, so the second model check depends on ambient state (`OZ_MODEL=''` or a prefix such as
   `claude` disables it), and a missing `num_turns` is plain. The harness can pin `config.SONNET_MODEL` itself.
4. `--baseline` is accepted in live mode. The separation gate refuses the owner home itself, but nothing ties a live
   run to `config.BASELINE_DEFAULT` (A4.13.4 names that path); recording and checking the resolved baseline path in
   `experiment.json` would close it.

## Attacks that held

1. Tool events: every non text item (including `todo_list`, `web_search` without a status, items without an id, items
   without a type), every non JSON line, every unknown event and every second turn is at least uncertain, which is
   leakage. U+2028 and similar separators inside JSON strings split lines and make the call uncertain, never plain;
   the CLI's own escaping prevents a reply from forging an event line.
2. Admission texts: the input policy strips the one terminal newline, so the leak check finds every admission case in
   a packet (checked for all 256 cases, including the 23 with a newline).
3. Rule origin: every released rule answer is compared with gold by the runner (safety kill) and by the scorer
   (`rule_errors` in every materials cell), whether its audit agreed, was inconclusive or was never sampled.
4. Budget: the live budget merges the experiment ledger and the attempts by attempt uid; the scorer checks nominal,
   reserve and telemetry totals across run directories; the ledger path is not a command line option.
5. Accounting: usage needs exactly one `turn.completed`; cached input needs the authorized certificate; a missing
   counter is incomplete and a present violation invalid; a recovered call without a stream is uncertain with zero
   charged tokens and incomplete usage, which keeps every token comparison inconclusive.
6. Locks and recovery: the per cell and experiment locks are non blocking OS locks at byte 0; a live child recorded
   alive stops the resume; a `spawning` marker without a pid is ambiguous and stops Codex.
