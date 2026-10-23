`oz-rule/1` is an opt-in, deterministic language for computing one complete job result. MUST, MUST NOT and MAY are normative.

**Representation and types.** An AST has exactly this shape:

```json
{"lang":"oz-rule/1","expr":NODE}
```

JSON MUST use valid UTF-8, without BOM, duplicate object keys, trailing content or unpaired surrogates. Unknown tags, extra elements and extra keys are invalid. Types are `string`, `decimal`, `bool` and `list<string>`. There is no implicit conversion, null, variable binding or reference.

The following table defines every node. `X`, `Y`, `C`, `A` and `B` denote child nodes. Lowercase parameters are literal JSON values. Variadic nodes accept zero or more children.

| Exact node shape | Types and semantics |
|---|---|
| `["s",s]` | Literal string |
| `["d",s]` | Decimal literal parsed from string |
| `["bool",b]` | Literal JSON boolean |
| `["input"]` | Own input text as string |
| `["field",key]` | Extract exact string value |
| `["split",X,separator]` | String → list; literal, nonempty separator; retain empty pieces |
| `["at",X,index]` | List → string; nonnegative integer index; missing index abstains |
| `["num",X,unit]` | String → decimal; exact unit parsing |
| `["add",X,Y]` | Decimal addition |
| `["sub",X,Y]` | Decimal subtraction |
| `["fmt",X,places,unit]` | Decimal → formatted string |
| `["eq",X,Y]` | Matching scalar types → bool |
| `["le",X,Y]` | Decimals → bool, inclusive comparison |
| `["if",C,A,B]` | Boolean condition; evaluate only selected branch |
| `["require",C,X]` | Boolean condition; false abstains; true evaluates X |
| `["lookup",X,[[key,value],...]]` | String → string; exact match; absent key abstains |
| `["list",X,...]` | String children → list |
| `["cat",X,...]` | List children → concatenated list |

Lookup keys and values MUST be literal strings; keys MUST be unique. Tables have at most 32 entries. `index` and `places` are JSON integers; `places` is between 0 and 12.

Validation checks all branches. Static type sets propagate through conditionals, whose branches MAY differ in type. Every possible operand type MUST satisfy its consumer. Thus a conditional returning string or list is valid at the root but invalid as an addition operand.

Loops, recursion, regex, imports, executable code, tools, I/O and access to other jobs or host state are unavailable. Host iteration over bounded lists is permitted.

**Text and numbers.** `field` parses the entire input into segments separated by literal `"; "`. Each segment contains exactly one `"="`. Keys begin with an ASCII lowercase letter or underscore and continue with those characters or digits. Values are nonempty and contain no semicolon, equals sign, CR or LF. Duplicate keys or malformed segments abstain. Missing requested keys abstain. Additional keys are allowed. No trimming, normalization or case folding occurs.

Other nodes do not require record syntax. Field extraction alone does not validate a value as numeric.

Decimal grammar is an optional ASCII minus, an integer part, and an optional decimal point followed by digits. The integer part is either `0` or begins with digits `1` through `9`. Only ASCII digits are accepted. Exponents, plus signs, whitespace, NaN and infinity are forbidden. Input numerals have at most 38 digits total and 12 fractional digits.

`num` with empty unit parses the entire string. Otherwise it requires the exact suffix consisting of one ASCII space followed by `unit`, removes it, then parses the remaining numeral. There is no unit conversion.

Arithmetic MUST use Decimal with exact addition, subtraction and comparison, never binary floating point. Results exceeding 38 coefficient digits or scale 12 after removing insignificant zeros abstain. Implementations MUST prevent ambient Decimal settings from introducing rounding.

`fmt` rounds using decimal ROUND_HALF_EVEN, emits exactly `places` fractional digits, suppresses negative zero, and appends one space plus the nonempty unit. Empty units append nothing. No exponent or grouping separator is emitted. Comparisons use unrounded values.

Extracted strings retain their exact characters, including numeric lexemes: `12.50 mm` remains `12.50 mm`. Decimal results themselves do not retain lexical spelling.

**Failure and resource bounds.** Bounds apply independently to each evaluation:

| Resource | Maximum |
|---|---:|
| Original AST JSON bytes, including whitespace | 2,048 |
| Expression depth, root counted as 1 | 16 |
| Node occurrences across all branches | 128 |
| Input UTF-8 bytes | 8,192 |
| Any intermediate string bytes | 8,192 |
| Any list elements | 64 |
| Serialized result value bytes | 4,096 |
| Steps | 32,768 |

Each evaluated node costs one step, plus the UTF-8 bytes of its string operands and literal string parameters, excluding its opcode, plus its string result bytes. Lists contribute the bytes of all their strings. `input` and `field` additionally consume the complete input as an implicit operand. Lookup charges every table string. Final serialization charges its byte length. Charges are logical and MUST remain identical with caching. Exceeding the budget stops evaluation.

Except for lazy branches, children evaluate left to right. Any evaluated failure propagates immediately. Missing fields, malformed records, invalid numbers, unit mismatches, type failures, failed guards, absent lookups, indexing failures, resource exhaustion and interpreter errors yield abstain. No partial output, exception or guessed replacement may escape.

Empty lists, false, zero, `"unknown"` and `"none"` are ordinary values. Only the explicit abstain result denotes failure.

**Evaluation and admission.** `evaluate(ast,text)` accepts AST JSON bytes and one input string. It returns exactly one of:

```json
{"status":"value","type":"string","value":"inside","steps":123}
{"status":"abstain","reason":"missing","steps":123}
```

`type` may also be `decimal`, `bool` or `list`. Decimal values serialize as normalized decimal strings without exponent or insignificant fractional zeros; zero is `"0"`. Other values use their corresponding JSON types. Serialization is compact, preserves Unicode characters, and escapes controls, quotes and backslashes.

Reasons are `invalid_ast`, `limit`, `input`, `missing`, `number`, `unit`, `type`, `guard`, `lookup`, `index` or `internal`. Invalid ASTs abstain before execution with zero steps. Step accounting saturates at the budget.

`admit(ast,labeled_cases)` receives AST bytes and a trusted package containing operation ID, contract and check definitions, contract/check/permission/worker hashes, dataset hash, provenance, and exactly 64 distinct labeled cases. Cases contain ID, text, expected typed value and partition: 48 representative, 16 predetermined challenges. Labels MUST be independently prepared and hidden from synthesis.

Admission first validates syntax, bounds, types, provenance and eligibility. It then evaluates all cases and applies the authorized consumer check. Coverage counts every value result, including incorrect or rejected values. A covered error is either a label mismatch or check failure. Acceptance requires zero covered errors and coverage of at least 32.

The response contains `status` (`accepted` or `rejected`), reasons, AST hash, binding hashes, coverage, covered errors and ordered per-case evaluation/check outcomes. Invalid candidates have zero coverage and no evaluated cases. AST hashes use the exact admitted bytes. Admission is screening, not certification.

Reuse requires unchanged bindings and a passing consumer check on each value. Abstention or rejection enters fallback. A `one_of` check alone cannot authorize rule reuse; BoolQ is ineligible.

Each wave MUST blindly select 32 covered jobs, or all if fewer, uniformly without replacement using the frozen seed. B and C use identical selected IDs. Receipts retain selection, producer, rule, bindings, runtime acceptance and later correctness separately. Any disagreement quarantines future reuse; emitted errors remain recorded. Rule receipts MUST NOT enter memo storage.

**Bootstrap envelope.** Learning defaults off. When enabled, the host supplies the specification, operation contracts, eligibility and requested operation IDs. One physical call returns ordinary answers and optional artifacts. The host unwraps `answers` into the unchanged OZ/1g parser.

Use this exact instruction, 858 characters:

```text
Answer every bootstrap job using the unchanged OZ/1g contract. Also propose one oz-rule/1 AST or the JSON string "none" for each requested operation. Use only the supplied language specification, operation contract, and visible job inputs. A rule must compute the entire answer from that job's own text, preserve extracted strings, and abstain when required data or computation is invalid. Do not infer missing facts, perform semantic reading, memorize job answers, or use tools. For BoolQ, passage comprehension, or a contract lacking an authorized input-bound check, return "none" for every operation. Do not revise job answers to fit a rule. Return exactly the specified oz-bootstrap/1 JSON envelope, with answers containing the ordinary OZ/1g reply as a string and rules mapping every requested operation to an AST or "none". No prose or additional keys.
```

The exact envelope has these three keys. `answers` is the complete ordinary reply encoded as a JSON string. `rules` has exactly the requested operation keys; each value is an AST object or `"none"`.

```json
{"host":"oz-bootstrap/1","answers":"<ordinary OZ/1g reply>","rules":{"e":"none","b":"none","m":"none","v":"none"}}
```

Malformed envelopes fail bootstrap. No candidate revision or answer repair is permitted.

**Worked ASTs.** E preserves all six fields. B and V reject negative uncertainty. Unknown uncertainty bypasses numeric parsing. M preserves the required field order. V compares both unrounded endpoints inclusively.

E:

```json
{"lang":"oz-rule/1","expr":["list",["field","length"],["field","uncertainty"],["field","n"],["field","method"],["field","basis"],["field","physical_validation"]]}
```

B:

```json
{"lang":"oz-rule/1","expr":["if",["eq",["field","uncertainty"],["s","unknown"]],["s","unknown"],["require",["le",["d","0"],["num",["field","uncertainty"],"mm"]],["list",["fmt",["sub",["num",["field","length"],"mm"],["num",["field","uncertainty"],"mm"]],2,"mm"],["fmt",["add",["num",["field","length"],"mm"],["num",["field","uncertainty"],"mm"]],2,"mm"]]]]}
```

M:

```json
{"lang":"oz-rule/1","expr":["cat",["if",["eq",["field","uncertainty"],["s","unknown"]],["list",["s","uncertainty"]],["list"]],["if",["eq",["field","method"],["s","unknown"]],["list",["s","method"]],["list"]],["if",["eq",["field","basis"],["s","unknown"]],["list",["s","basis"]],["list"]]]}
```

V:

```json
{"lang":"oz-rule/1","expr":["if",["eq",["field","uncertainty"],["s","unknown"]],["s","unknown"],["require",["le",["d","0"],["num",["field","uncertainty"],"mm"]],["if",["le",["d","12.48"],["sub",["num",["field","length"],"mm"],["num",["field","uncertainty"],"mm"]]],["if",["le",["add",["num",["field","length"],"mm"],["num",["field","uncertainty"],"mm"]],["d","12.52"]],["s","inside"],["s","outside"]],["s","outside"]]]]}
```

Compact E, B, M and V occupy 162, 356, 289 and 420 bytes respectively. Their depths are 2, 7, 4 and 8.

Three invalid ASTs follow. Their rejection reasons are, respectively, unknown node, incompatible addition operand and duplicate lookup key. Evaluation returns `invalid_ast`.

```json
{"lang":"oz-rule/1","expr":["eval","1+1"]}
{"lang":"oz-rule/1","expr":["add",["s","1"],["d","2"]]}
{"lang":"oz-rule/1","expr":["lookup",["input"],[["a","x"],["a","y"]]]}
```

**Conformance.** Auxiliary references T and L are:

```json
{"lang":"oz-rule/1","expr":["at",["split",["input"],"|"],1]}
{"lang":"oz-rule/1","expr":["lookup",["input"],[["A","alpha"],["B","beta"]]]}
```

Each vector is `[input,AST reference,expected value]`. The object `{"status":"abstain"}` requires abstention. These 24 vectors test evaluation, not admission.

```jsonl
["length=12.50 mm; uncertainty=0.02 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed","E",["12.50 mm","0.02 mm","3","unknown","unknown","not_claimed"]]
["length=12.500 mm; uncertainty=0.020 mm; n=03; method=x; basis=y; physical_validation=not_claimed","E",["12.500 mm","0.020 mm","03","x","y","not_claimed"]]
["length=12.50 mm; uncertainty=0.02 mm; method=x; basis=y; physical_validation=not_claimed","E",{"status":"abstain"}]
["length=12.50 mm; uncertainty=0.02 mm","B",["12.48 mm","12.52 mm"]]
["uncertainty=unknown","B","unknown"]
["length=12.50 mm","B",{"status":"abstain"}]
["length=twelve mm; uncertainty=0.02 mm","B",{"status":"abstain"}]
["length=12.50 cm; uncertainty=0.02 mm","B",{"status":"abstain"}]
["length=12.50 mm; uncertainty=-0.02 mm","B",{"status":"abstain"}]
["length=12.505 mm; uncertainty=0.010 mm","B",["12.50 mm","12.52 mm"]]
["length=12.50 mm; uncertainty=0.02 mm","V","inside"]
["length=12.49 mm; uncertainty=0.02 mm","V","outside"]
["length=12.51 mm; uncertainty=0.02 mm","V","outside"]
["length=12.48 mm; uncertainty=0 mm","V","inside"]
["uncertainty=unknown","V","unknown"]
["length=12.50 mm; length=12.51 mm; uncertainty=0.02 mm","V",{"status":"abstain"}]
["uncertainty=0.02 mm; method=unknown; basis=unknown","M",["method","basis"]]
["uncertainty=0.02 mm; method=caliper; basis=repeatability","M",[]]
["uncertainty=unknown; method=unknown; basis=unknown","M",["uncertainty","method","basis"]]
["uncertainty=Unknown; method=caliper; basis=repeatability","M",[]]
["a||b","T",""]
["a","T",{"status":"abstain"}]
["A","L","alpha"]
["C","L",{"status":"abstain"}]
```

