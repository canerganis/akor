**Council 1 verdict: HOLD before step 4.** This is a static review against the signed record and supplied specification. Runtime probes could not execute because Python was unavailable in this shell.

**1. BLOCKERs**

1. **Admission does not enforce eligibility or bindings.** In `oz_rule.py`, `_package_problem` accepts arbitrary nonempty hashes and provenance without contract or check definitions. `admit(..., eligible=True)` can accept a BoolQ constant rule with an always true callback. Require a trusted package resolver that supplies definitions, verifies their hashes and provenance, and derives eligibility. Explicitly reject BoolQ and contracts authorized only by `one_of`. Resolve the consumer check from its pinned definition rather than accepting an unrelated callable. Perform these validations before evaluating any cases.

2. **Step accounting is incorrect.** In `oz_rule.py`, `_Run.ev`, `if` and successful `require` omit the selected child’s string or list bytes as operands and as results. For `["if",["bool",true],["s","x"],["s","y"]]`, the total must be 10, not 8. Nested guards can consequently bypass the budget. Charge each node upon entry, literal parameters when processed, every evaluated string operand, and its returned string bytes. Preserve lazy branches and immediate failure propagation. Add exact accounting vectors for strings, lists, failed children and saturation.

3. **Arithmetic rejects permitted results.** In `oz_rule.py`, `_in_range` counts expanded decimal notation instead of normalized coefficient digits. Adding one to 38 nines produces `1E+38`, whose coefficient has one digit, but currently abstains. Inspect the normalized Decimal tuple: require at most 38 coefficient digits and `max(0, -exponent) <= 12`. Keep input numeral limits separate. Correct the existing test that expects this carry to fail.

4. **A supplied check can silently disappear.** In `oz_map.py`, `command`, `checks.get(args.op, [])` converts a missing operation key into unchecked execution. Require that a mapping contain the requested operation and that its value be a valid check list. Reject a missing key before any dispatch.

5. **Producer identity is absent from step 2.** In `oz_map.py`, `requests` and `run`, path IDs identify files but not producer submissions. Add a stable producer identity and submission identity to host metadata and receipts, retaining the mapping through request chunks. Namespace delivery identity by producer and submission while preserving explicit resume semantics. Include request and job references in every result row so step 5 can pool work without losing ownership or conflating submissions.

6. **Raw telemetry is discarded.** In `examples/codex_cli_adapter.py`, `main` reduces stdout and drops it; nonzero exits also discard any usable usage events. Add a durable capture path tied to the physical call identity, retaining stdout, stderr, exit status and timeout evidence before reduction. Preserve failure usage separately from acceptance. Keep cached input included exactly once. Unsupported reasoning accounting must remain explicitly unverified until the telemetry gate resolves it.

**2. SHOULD-FIX**

In `oz_map.py`, `requests`, expose experimental authorization explicitly rather than always setting `allow_experimental=True`. Using the selective profile for this new command is acceptable provided existing `oz do` defaults remain unchanged.

In `run`, distinguish current invocation accounting from cumulative request accounting. `oz_do._accounting` returns historical totals, whereas `seconds` measures only this invocation. A resumed map must not present historical tokens against near zero elapsed time.

In `admit`, retain each complete typed evaluation result and check outcome, not merely match booleans. Validate decimal labels as canonical decimal values and retain the operation identity with bindings.

In adapter `main`, freeze the effective model, effort, CLI version and invocation environment. Reconcile those with the host’s declared worker binding before dispatch.

The default goal and visibly inactive `--learn` are acceptable scaffolding through step 3.

**3. `oz_rule.py` conformance and READING rulings**

The interpreter is **not conformant yet**, despite substantial correct parsing, typing, lazy evaluation and Decimal isolation.

1. Decimal point requires a following digit: **ACCEPT**, explicitly required.
2. Arithmetic bounds count plain notation digits: **OVERRIDE**, use normalized coefficient digits.
3. Malformed decimal literals invalidate the AST: **ACCEPT**, including unreachable branches.
4. Impossible field keys invalidate the AST: **OVERRIDE**. The node accepts a literal string key; record key grammar constrains input records. A valid record lacking that key must yield `missing`.
5. Equality requires identical singleton scalar type sets: **ACCEPT**. Every possible operand combination must have matching types.
6. Malformed or duplicate record segments yield `input`: **ACCEPT**.
7. Result size includes serialized value quotes and brackets: **ACCEPT**.
8. Distinct cases require distinct IDs and input texts: **ACCEPT**, preventing repeated inputs from inflating coverage.

**4. Improvements to steps 4 through 6 and the pilot**

Compile each admitted AST once and cache parsed records while preserving logical charges. Run consumer checks before publication; keep rule receipts outside memo storage. Atomically quarantine future reuse on disagreement.

Implement one locked drainer with compatible queues, flushing at 64 records or one second from the oldest waiting item. Replay crashes around reservation, dispatch, capture and delivery to verify attribution and duplicate prevention.

Maintain one physical call ledger plus separate arm allocations. Charge the shared bootstrap fully to B and C without counting it twice against the physical cap. Reserve audit overflow before launching.

Freeze independent boundary cases and accounting oracles before calls. Report coverage, emitted errors, fallback correctness, token components, queue time and makespan separately. Preserve the signed gates and treat exhaustion or incomplete usage as incomplete evidence.

