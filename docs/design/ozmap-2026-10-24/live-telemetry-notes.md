# Live telemetry: what happened and two changes (2026-10-24)

Run 1 (freeze 092e098): both calls rejected as "tool use in the event stream". The flagged items were four
`item.completed` events of type `error` holding only a message: Codex config and startup warnings from the owner's
~/.codex/config.toml (an ignored key, an unstable feature, a hook timeout). No tool, command, file or web item.
Usage: call 1 input 29694 cached 7296 output 43 reasoning 25; call 2 input 29694 cached 0 output 43 reasoning 25.
Fix 1 (commit after 092e098): an error item with only id, type and a string message is a CLI notice, not leakage;
any other field, nested message or other item event stays leakage.

Run 2 (freeze 3e234b4): leakage clean; rejected because input changed 29694 -> 29692 and cached did not grow (0, 0).
Cause: each call ran in a new random temp directory and Codex writes its working directory into the prompt, so the
two requests were not byte-identical.
Fix 2: the working directory is now the first free numbered slot `oz-codex-empty-<k>` under the system temp area,
held by an OS lock and emptied before each call, so sequential identical requests see the same path.
Fix 3 (rule): certify_codex required cached_input_tokens to GROW on the repeat. Run 1 shows the cache hit can also
fall on an identical repeat (7296 -> 0) with input unchanged. Under exclusive accounting input_tokens would move by
exactly the cached difference in either direction, so the rule now requires equal input totals and DIFFERENT cached
counts. Equal cached counts still certify nothing.

Reasoning inclusion on live data: output 43, reasoning 25, visible reply 12 tokens, residual 6 (recorded 4 to 6),
output minus visible 31 > 8: passes the sign-off 3 predicate.

Spend so far: 4 Codex telemetry calls (about 119k input tokens), all recorded in bench/ozmap/runs/live-6a518ece47ab
and live-538bcde9a80b; they count as preparation cost in the report.

Run 3 (freeze 33f8604): requests identical (input 29686 both, same workdir oz-codex-empty-0, equal system and
prompt hashes); reasoning inclusion passed on both calls (residual 6); rejected only because cached was 0 on both,
so cache inclusion could not be shown. Across six live Codex calls the cache hit occurred once (7296). The driver
will not repeat telemetry hoping for a cache hit (cost, and choosing runs by outcome).
Proposed rule (for Astra): when a Codex call reports cached_input_tokens = 0, inclusive and exclusive readings give
the same total, so its usage is complete without cache certification; a call with cached_input_tokens > 0 is
"usage unverified" unless the paired telemetry certified cache inclusion for the frozen route, and makes its cell's
evidence incomplete. Reasoning inclusion stays certified per call by the sign-off 3 predicate (applied to every
Codex call, not only telemetry). The live run no longer refuses for missing cache certification alone.
Spend so far: 6 Codex telemetry calls across three run directories (about 178k input tokens).
