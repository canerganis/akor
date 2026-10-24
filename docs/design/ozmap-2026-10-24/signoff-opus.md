# Opus sign-off, oz map pilot (61d4d64)

Lines are at 61d4d64. `pilot.py dry`: 0 external calls, 44 physical (Codex 29 incl. 2 telemetry, Sonnet 15), reconciliation ok, telemetry ok, codex isolated 29/29, claude tools disabled 15/15, no leakage, evidence complete, output sha256 a014294e. `tests.test_ozmap_close tests.test_ozmap_pilot`: 83 OK, 1 skipped. No model call, no network, no git change.

## Items

| Item | State | Evidence |
|---|---|---|
| N1 Codex | CLOSED | codex_cli_adapter.py:221 empty dir outside any repo, :256 `-C`, :259 cwd, :264 removed; :91,97 event whitelist, :277 exit 86, no reply; oz_host.py:1898 answers refused, :1958 efficiency invalid; pilot.py:1022 flag derived |
| N1 Claude | CLOSED | claude_map_adapter.py:21 no tools, settings or MCP; :42,77 exit 86 |
| N2 one driver | CLOSED | pilot.py:950 drive, used by dry :1106 and run_live :1588; ChildLauncher :985, others refused oz_host.py:1351; real CLI refused pilot.py:1087 |
| N3 quota | CLOSED | oz_host.py:1834 gate, :1845 oz_quota before budget, :1356,1364 mandatory; pilot.py:667 no reading refuses, :671 99% stop; telemetry :832,844 |
| B9 tree kill | CLOSED | oz_host.py:553 verified only by gone(), :559,1869 slot and quota kept, :1883 violation, :1912 reap; pilot.py:862 |
| Envelope per child | CLOSED | oz_host.py:1820, pilot.py:835 |
| Interpreter, full file set | CLOSED | pilot.py:1389, :1415 |
| Zero cache telemetry | CLOSED | pilot.py:797,800 |

Can a child still read the repo? Not unseen. Codex is read-only, not read-free, and loads the owner's ~/.codex config (node_repl, graft, context7, valency MCP, plugins, AGENTS.md). A read by absolute path or MCP is possible, but it shows as a non-whitelisted event, the call yields no answer and the run turns invalid. Prompts carry no repo path; env paths such as OZ_ENVELOPE_PATH need a tool event to use. Claude has no tools. Dry is the live driver: only executables, the fresh route, registry and closure build, and the temp quota store differ. No launch without a reading; the one ungated child is the zero-call reconcile (oz_host.py:1972). A killed tree is released only after verification.

Residuals, not blocking:
1. One stray Codex tool call voids gate 2 for the whole spend. An isolated CODEX_HOME would cut that risk but changes the route; owner's call.
2. oz_host.py:402,553: if Windows job assignment fails, a normal exit gives verified None and releases. Mode here is `job`. Treat None as unverified in pilots.
3. Claude's cwd is examples/ (oz_workspace.py:108); harmless without tools.
4. The 99% reading is taken once per batch; start well below 99 or append readings with `pilot.py quota`. The Codex 20% stop is not in code.
5. freeze (pilot.py:1469) does not refuse on dry telemetry not ok or isolation counts below call counts.

## D1, usage components

Agree. All 12 recorded Sol medium calls report input, cached, output and reasoning (cache_write rightly optional, input includes it). Sonnet's four fields come from four raw modelUsage counters, nothing fabricated. Add one check: the adapter sums every modelUsage entry, so flag any entry besides the pinned model.

## D2, Sonnet semantics

Agree. Anthropic reports input, cache read and cache creation as disjoint counters, so inclusion holds by construction (claude_cli_adapter.py:29) and the charge is input plus output once (oz_host.py:2786). Freeze the formula text (pilot.py:139).

## Verdict: SIGN on the Opus items at 61d4d64

The working tree now holds uncommitted edits to pilot.py, oz_host.py, fake_cli.py and test_ozmap_close.py (reasoning inclusion via tiktoken, Astra's open item). They are outside this sign. Before freeze, telemetry and live run:
1. Commit them from a clean tree (freeze refuses dirty frozen files).
2. On that commit, dry telemetry still ok and these tests green.
3. Pin the cached o200k file's sha256 in the freeze so tiktoken never fetches it.
