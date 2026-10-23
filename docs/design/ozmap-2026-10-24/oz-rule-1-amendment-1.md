**oz-rule/1 amendment 1**

This amendment supersedes conflicting text in oz-rule/1 and the signed joint record. Other gates, budgets and defaults remain unchanged. Step 4 remains on HOLD until the fixes for steps 1 to 3 pass.

**D1. Rule adoption.** Introduce `rule_provenance/1`, registered as job bound and restricted to host rule adoption. At commit, the host MUST reevaluate the exact admitted AST bytes against this job’s immutable resolved input, obtain `status:"value"`, and require identical result type and canonical value. Admission, bindings and quarantine state MUST remain valid in the committing transaction. Implement separate `adopt_rule`; preserve `adopt_memo` and existing settlement, lease, epoch and computation fencing.

This proves computational provenance and repeatability, not meaningful input dependence, semantic correctness, generalization or absence of encoded constants. Admission and blind audits remain mandatory. Every pinned consumer check MUST also pass; unavailable checks await verification. Evaluation gold MUST NOT enter execution. Model fallback MUST NOT require agreement with the rule. This amendment authorizes provenance for the four supplied materials contracts, never arbitrary operations sharing their IDs.

**D2. Input.** The host MUST remove exactly one terminal CRLF, otherwise one terminal LF, before resolving text for models, rules and checks. It MUST perform no other normalization. Receipts MUST retain raw and resolved hashes, removed suffix and policy version. The package MUST pin selection of one text reference belonging to the job. Admission uses this same policy and requires distinct resolved texts. Direct `evaluate` remains literal. Remaining newlines can still cause `field` to abstain.

**D3. Steps.** Charge one on node entry. Process arguments left to right, charging each literal string when reached and every successful child’s string or list bytes when returned to its parent. Charge the node’s own string or list result again before returning. Lists contribute member UTF8 bytes. Charge complete implicit input before access by `input` or `field`, all lookup table strings before matching, and final serialization. Unselected branches cost nothing. A failed child contributes no operand bytes; stop immediately without parent result or serialization charges, retaining earlier charges. The first charge exceeding 32768 yields `limit` with steps saturated at 32768.

Each expression below is wrapped in `{"lang":"oz-rule/1","expr":EXPR}`:

1. Input `""`; `["if",["bool",true],["s","x"],["s","y"]]` returns `{"status":"value","type":"string","value":"x","steps":10}`.
2. Input `"a=b"`; `["cat",["require",["bool",true],["list",["s","x"]]],["list",["field","z"]]]` returns `{"status":"abstain","reason":"missing","steps":18}`.
3. Input exactly 8192 ASCII `x` characters; `["require",["bool",true],["input"]]` returns `{"status":"abstain","reason":"limit","steps":32768}`.

**D4. Decimals.** Strip coefficient trailing zeros without rounding, increasing the exponent accordingly; canonical zero has coefficient zero and exponent zero. Require coefficient length ≤38 and `max(0,−exponent) ≤12`. Input numeral limits remain separate.

Using the same wrapper and empty input:

1. `["add",["d","99999999999999999999999999999999999999"],["d","1"]]` returns `{"status":"value","type":"decimal","value":"100000000000000000000000000000000000000","steps":83}`.
2. `["add",["d","99999999999999999999999999999999999999"],["d","2"]]` returns `{"status":"abstain","reason":"number","steps":42}`.

**D5. Field keys.** Validation MUST require a literal string key, without applying record key grammar to it. Parse and validate the entire record first; malformed records yield `input`, otherwise absent keys yield `missing`.

**D6. Trusted admission.** An owner approved host registry MUST supply immutable operation contracts, consumer and provenance check definitions, implementation versions and digests, permissions, input policy and route definitions. Producers and candidates MUST NOT supply executable callbacks or eligibility flags.

The resolver MUST recompute artifact SHA256 hashes and compare them against a frozen trusted manifest, verify independent label provenance, and recompute the dataset hash from complete ordered cases, including IDs, original text, typed labels and partitions. For case and identity hashes, `canonical(x)` means UTF8 encoding of Python `json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)`; duplicate keys and invalid Unicode MUST be rejected.

Eligibility requires a declared deterministic contract and authorized input bound checking, including D1 where explicitly authorized before bootstrap. BoolQ and authorization by `one_of` alone MUST fail; shape checks cannot establish eligibility. D1 authorization satisfies the bootstrap input check requirement.

`admit(ast_bytes,resolved_package)` MUST receive these verified definitions, hashes, operation identity and exactly 64 cases. Unknown bindings, missing provenance, mismatches and unresolved checks MUST reject before case evaluation. Admission MUST resolve checks from pinned registry definitions, validate canonical decimal labels independently of input numeral limits, and retain complete typed results and check outcomes. Existing admission thresholds remain unchanged.

**D7. Route.** Define `worker_hash=SHA256(canonical(route))`, where `route={adapter_hash,backend,model,effort,cli_version,environment_hash}`. The adapter hash MUST cover canonical adapter configuration and a manifest of executable source byte hashes ordered by source path. The environment hash covers frozen nonsecret invocation configuration, including flags and resolved CLI configuration. Effective model, effort, backend and CLI version MUST be reconciled before dispatch; unknown or conflicting identities block dispatch. Map MUST require model and effort explicitly and convey them to the adapter. Rule bindings, pooling, qualification and accounting MUST use this full identity, never a model label alone. Interpreter and input policy revisions MUST also bind rule reuse.

**D8. Ownership.** The host MUST issue and persist producer and submission identities. Delivery identity MUST include producer ID, submission ID and logical job key, including operation. New submissions get new IDs; resume retains IDs and verifies unchanged payloads per job. Chunk boundaries MUST NOT define identity. Reference identities MUST carry the same namespace. Compact names MUST use `j` or `r` plus lowercase unpadded base32 SHA256 of canonical identity tuples, with collision detection, yielding 53 characters. Every result MUST retain producer, submission, logical job, request and reference mappings, plus nullable physical call ID. Audits require distinct job identities linked to originals. Cross arm matching uses frozen dataset IDs, not delivery IDs.

**D9. Additional rulings.** Decimal wire values remain JSON strings; consumer checks MUST see that representation. Rule receipts MUST explicitly identify `source:"rule"` and MUST never enter memo storage. Raw stdout, stderr, exit status and timeout evidence MUST be durably captured under physical call identity before reduction, including failures. Unsupported usage components remain unverified. Experimental execution MUST require explicit authorization; existing `oz do` defaults remain unchanged.

Opus recommendations:

1. ACCEPT: report invocation increments and cumulative calls, tokens and elapsed times separately.
2. ACCEPT: preflight every chunk before dispatch; unreadable, empty or invalid inputs become failed rows without aborting valid siblings.
3. ACCEPT: add `--ask-file`; nonexistent pathlike legacy `--ask` values MUST fail before dispatch.
4. ACCEPT: missing operation keys or invalid check lists MUST fail before dispatch.
5. ACCEPT: expose all four requested limits and isolate oversized jobs.
6. ACCEPT: recoverable error events do not override completed turns; terminal failure, nonzero exit, timeout or missing completed message fails; missing executables receive explicit diagnostics.
7. ACCEPT: D6 replaces caller eligibility and verifies dataset contents.
8. ACCEPT paired telemetry with correction: equal input totals and increased caching are not guaranteed; two invocations consume the telemetry allocation plus one reserve call, and inclusive accounting MUST be verified from raw evidence.

**Build tasks**

**Fix now, steps 1 to 3:** implement D2 through D9 foundations, explicit experimental authorization, trusted admission, raw capture and accounting vectors; replay adapter failures and recorded usage with fake workers.

**Step 4:** implement the independent `rules=` hook, D1 atomic adoption, consumer checks, fallback, fused bootstrap, audits, quarantine and explicit memo exclusion.

**Step 5:** implement one locked drainer, full binding compatibility, ownership mappings, per job resume, flushing at 64 records or one second from the oldest item, and crash recovery around reservation, dispatch, capture and delivery, with duplicate delivery prevention.

**Step 6:** implement physical call and arm allocation ledgers, producer reconciliation, full bootstrap charging separately to B and C with one physical charge, audit reservations and exhaustion enforcement.

**Pilot:** freeze independent boundary and accounting oracles; dry run A/B/C; evaluate E/B/M/V with pinned checks before paid calls; resolve telemetry; freeze seeded arm order; report uncached input, coverage, errors, fallback correctness, queue time, makespan and per job audit provenance. Exhaustion or incomplete usage remains incomplete evidence.

Signed: Astra A, AKOR language owner, 2026-10-24. Language decision only; implementation conformance is not certified.

