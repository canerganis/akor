# Astra sign-off 3 of ruling P5 (2026-10-25)

Request: one Astra call (gpt-6-astra, high effort, read-only, evidence pack without ops content or sealed ASTs) after repair commit e29891f, made through a Sonnet relay under A4.13r1.2. The pack held A4.14, the P5 ruling file with annexes, signoff-astra-2.md, the repair diff, effective_context.py, the approved effective context, the 26 rejection tests (re-run before the call: 26 passed), the annex without the raw captures, and gen_p5.py. Pack file: scratchpad rep/signoff3-prompt.md.

Result: P5 signed by Astra A. No blocker. Output below is verbatim (scratchpad file signoff3-out.md).

## Verbatim Astra output

Signed: Astra A P5

Evidence: The previous blocker is closed. `gen_p5.py` now obtains its verdict from `effective_context.certify`, requiring every captured request to match the approved instructions, tool schemas and exact stdin. The catalog is pinned; WebSocket turn/prewarm and HTTP captures match, while the unpinned control demonstrates sensitivity to metadata changes. Annex, executable and launch checks bind the evidence to the approved route. The supplied pack reports 26 passing tests, including the requested rejection cases.

This signature covers the supplied P5 ruling and repair-2 annexes, including the named effective context and catalog. Review is pack-only; tests were not independently rerun. It does not approve D5 or replace Opus B’s required countersignature.