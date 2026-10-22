# Opus 5.5, round 1 (written before reading Astra's round 1)

Extra facts I pulled from bench/live/data before writing (same for Astra in round 2):
- Opus 5.5, 64 jobs, live27: plain JSON in 6634 / out 2600 (think 642); OZ/1g in 3383 / out 1901 (think 571).
  Output is now ~36% of an OZ/1g call and shrank only 27%, while input shrank 49%.
- Haiku 5.5, live29: OZ/1g in 3361, out 6110 of which thinking 4753, time to first token 16.9 s of 23.4 s.
- Prompt cache: on OZ/1g calls cache_read is 482 to 603 tokens (about system text H); the other ~2.7k of input is
  cache_write every call. Nothing of goal/ops/refs is reused across calls even when they repeat.

## Ideas

O1. Measure against what people actually run: one call (or one subagent) per job. Mechanism: same 64 jobs, arm
    "per-job claude -p" and arm "Claude Code Task subagent per job". Expected: very large saving (each claude -p call
    pays ~950 CLI tokens plus system text; a subagent pays its whole system prompt), plausibly -80..-95% per verified
    job and large wall-time gains. Test: preregistered 64 jobs x 3 reps, Sonnet. Risk: looks like a straw man unless
    both baselines are shown. Cheapest, and it changes the README headline from "-41% vs batched JSON" to the number
    users care about.

O2. AKOR as the fan-out engine inside Claude Code: an MCP server (or skill + `oz` command) exposing "batch these
    N small tasks", so an orchestrating agent replaces N subagents or N sequential tool loops with one checked OZ/1g
    call. Expected: largest real-world token and time saving, and the first adoption surface that reaches users where
    they already are. Test: a recorded Claude Code session that fans out 20-60 small tasks, before/after, billed tokens.
    Risk: integration work; MCP tool schemas add their own fixed tokens to the orchestrator context.

O3. Cache-aware packet layout. Mechanism: order the prompt so everything stable across calls (H, goal, ops, shared
    refs) forms a byte-identical prefix and the per-call part (jobs, new refs) comes last; send the prefix as the
    system/appended system text so claude -p cache reads it. Expected: on a run of K calls with the same goal/ops,
    input billed at cache-read rates for most of the packet; under the token-count metric no change, under
    quota/cost metric a large change. Test: 10 calls same goal/ops, compare cache_read share. Risk: our metric
    counts raw tokens equally, so this only shows up if we also report a cost-weighted column; must decide what the
    owner's quota actually charges.

O4. Shrink the output side. Output is now the larger lever on Opus/Sonnet and dominant on Haiku. Mechanisms to
    explore (Astra's call on the form): host-assigned short IDs, default-value elision (only emit records that differ
    from an op-declared default, with an explicit count line for checking), typed op results so the host renders
    units/strings and the model emits only the varying atom. Expected: -20..-40% output tokens on extraction-style
    jobs. Test: offline count of reply bytes, then live paired. Risk: elision weakens the "every ID exactly once"
    check that made 91/91 possible.

O5. Per-job acceptance (build order step 2 remainder). Mechanism: accept valid records, re-queue only bad or missing
    IDs; keep atomic acceptance only where a reply is structurally broken (header missing, ID swap suspicion).
    Expected: retry cost goes from 64 jobs to the few broken ones; matters most on weaker models and larger N
    (enables N=128/256 safely). Test: fault-injection replay on recorded replies plus Luna/Haiku-low runs. Risk:
    partial acceptance can hide systematic drift (Luna index drift produced valid-looking wrong records); needs a
    drift guard (e.g., echo of one ref-derived field per op, sampled oracle).

O6. Larger N and adaptive batch size. 64 was chosen, not optimized. Mechanism: measure 128/256 on Sonnet/Opus;
    the CLI overhead and H amortize further. Expected: another -5..-10% per job if accuracy holds. Test: 5 calls each.
    Risk: thinking grows with N (Haiku); with atomic acceptance a failure costs more, so it depends on O5.

O7. Thinking control. Haiku spends 4.7k thinking tokens on 64 easy jobs. Mechanism: measure effort low/none for
    claude -p where available, and whether a packet that pre-resolves indices (refs inlined into each job row for
    models without much reasoning) lets low effort stay correct. Expected: Haiku per-job cost could drop 40-60%.
    Test: live8 data already has haiku_low/high files; analyze before spending calls. Risk: correctness drops; index
    drift seen on Luna with 0 reasoning.

O8. DAG executor (build order step 3), but scoped to what pays: wavefront execution where each wave's ready nodes
    from many agents are batched into one OZ/1g call, with memo of identical (op, refs) results across waves and runs.
    Expected: makes AKOR useful for dependent multi-step work, the common real case, and memo hits are free jobs.
    Test: the owner's recorded 20-step real workflow. Risk: the biggest build; planner wire adds a model call that must
    be paid back.

O9. Second task family in the public benchmark (code review findings, log triage), from the README roadmap.
    Expected: shows the savings generalize or exposes where they do not. Risk: oracles are harder; keep deterministic.

O10. Uniform error record {"id":"w","error":[code,message]} (Astra's earlier note). Removes the array/object fork that
    broke Luna. Small, cheap, opens the Codex/Luna qualification later. Risk: re-qualification calls on all Claude cells.

## My top 3
1. O1 + O2 together: measure against per-job calls and subagents, then ship the Claude Code fan-out integration.
   That is where the saving is largest and where users are.
2. O5 then O6: per-job acceptance with a drift guard, then larger N.
3. O4: output-side compression, designed by Astra, gated on keeping 100% acceptance.

## Deliberately not now
Codex/Luna qualification (CLI overhead makes the target unreachable there), more wire stages that only shave input
on the existing benchmark, and the full planner wire before a wavefront executor proves its value on the 20-step
workflow.
