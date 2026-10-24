# Independent expressibility review (A4.6, A4.8)

Reviewer: a fresh Opus instance (claude-opus-5-5), 2026-10-24. Not a signatory of Amendment 4 or A4.13, not the author of
the operations, not a backend under test. This review is one Opus review call under A4.13; the driver logs it in
call-ledger.jsonl. The reviewer made no further model calls.

Blindness. This file describes the content of the four operations. It belongs to the same blind set as
`bench/ozmap_rep/ops/` and must not enter any evidence pack sent to Astra before scoring. It contains no AST content.

## Inputs reviewed

| artifact | SHA-256 |
|---|---|
| `bench/ozmap_rep/ops/ops.md` | `7e82a4b2a9ec88e3406831e8576ced3e2d51e9720ecfe853de757aab7c172cc0` |
| `bench/ozmap_rep/ops/oracle.py` | `94725a6aee4a280578ca7bd8522252ebd8331c09b1a760663ad9a022910e50d3` |
| `bench/ozmap_rep/ops/data.py` | `bdc8a19b76aefd95b8ef8d69abddda65425a150176df21c42c7936fe9927bd0c` |
| `bench/ozmap_rep/ops/test_ops.py` | `e34a34de362a6425d081a5258a00017df226fe67aecd2bac775fb89e710d08c9` |
| `oz_rule.py` (interpreter, `evaluate`, `validate`, `admit`) | `8a9897c66c7518031fe50d3124101ad7cd35b39a2f7946eadef5612cc8e77e8c` |

Also read: `docs/design/ozmap-2026-10-24/bootstrap-spec-excerpt.txt` (what the learner sees),
`docs/design/ozmap-2026-10-24/oz-rule-1-spec.md`, `docs/design/ozmap-2026-10-24/oz-rule-1-amendment-1.md`, and the
D2 input policy in `oz_registry.apply_input_policy`. Repo HEAD at review: `b1d41ff`.

## Criterion

A4.6: an operation is rule shaped when the frozen oz-rule/1 AST language can express a nontrivial, input determined
solution on a specified domain. The domain used here is the operation's own written contract in `ops.md`, not a
carve-out chosen to make a rule fit. Classification is made from the contract and the language only; it does not
depend on any learner output. Where an operation is classified rule shaped, the reviewer wrote a solution AST, checked
it with the real interpreter and sealed it (hashes below).

Common domain for every operation: one record text in the `ops.md` grammar after the D2 input policy (one terminal LF
or CRLF removed), parseable by `field` (segments separated by `"; "`, one `=` per segment, unique keys, values without
`;`, `=`, CR or LF), with every numeral the operation reads inside the interpreter's input numeral limits (at most 38
digits, at most 12 fractional digits). The generated workload stays well inside this: at most 3 fractional digits.

## Per operation classification

### `verdict`: rule shaped

| item | value |
|---|---|
| permitted inputs | the job's own resolved text; fields `grade`, `yield`, `uts` |
| outputs | string: `pass`, `fail`, `unknown` |
| domain | common domain; `grade` any label, `yield` and `uts` each a numeral with unit `MPa` or `N/mm2`, or `unknown` |
| guards | exact equality with `unknown`; grade membership in the five table labels decided by equality before any table access, so the table lookup can never abstain on a listed grade; the unit read from the second space separated piece and the numeral parsed with that exact unit, so any other unit, a missing space or a malformed numeral abstains; missing fields and malformed records abstain through `field` |

Reason. The contract is a fixed five row table plus two inclusive comparisons. The language has exact string equality,
`lookup` over at most 32 literal entries, exact decimal parsing with an exact unit suffix, and inclusive `le`. The two
units are synonyms with no conversion, so selecting the unit lexically and parsing the same numeral is exact. The
precedence of rule 1 maps to an outer conditional order. Nothing needs multiplication, division or iteration.

Sealed AST: 1,008 bytes, 68 nodes, depth 11 (limits 2,048, 128, 16), worst observed steps 2,117 of 32,768.

### `margin`: rule shaped

| item | value |
|---|---|
| permitted inputs | the job's own resolved text; fields `yield`, `uts` |
| outputs | string: an integer, one space, `MPa`, or `unknown` |
| domain | common domain; `yield` and `uts` each a numeral with unit `MPa` or `N/mm2`, or `unknown` |
| guards | exact equality with `unknown` for each field; unit selection and exact unit parsing as for `verdict` |

Reason. The contract is one exact subtraction and a fixed format. `fmt` with 0 places and unit `MPa` rounds half to
even, emits no decimal point, keeps the sign and suppresses negative zero, which is exactly rule 2 and rule 3 of
`ops.md`. Subtraction is exact, and its result stays far inside the 38 digit and 12 place result limits on the domain.

Sealed AST: 437 bytes, 32 nodes, depth 9, worst observed steps 1,047.

### `temp_class`: rule shaped

| item | value |
|---|---|
| permitted inputs | the job's own resolved text; field `temp` |
| outputs | string: `cold`, `room`, `hot`, `unknown` |
| domain | common domain; `temp` a numeral with unit `C` or `degC`, or `unknown` |
| guards | exact equality with `unknown`; unit selection and exact unit parsing as above |

Reason. Two inclusive thresholds on one exact decimal. `t < 10` is the negation of `le(10, t)` and `10 <= t <= 35`
is two `le` tests, so all three classes and both inclusive endpoints are exact. Negative values and `-0` parse under
the decimal grammar.

Sealed AST: 428 bytes, 34 nodes, depth 9, worst observed steps 816.

### `elong`: not rule shaped

| item | value |
|---|---|
| permitted inputs | would be fields `gauge`, `final` |
| outputs | string: one decimal place, one space, `%`, or `unknown` |
| domain | common domain; `gauge` and `final` numerals with unit `mm` (gauge positive), or `unknown` |
| guards | not applicable |

Reason. The answer is `(final - gauge) / gauge * 100`, a division by a per record value, rounded half away from zero.
The frozen language has `add` and `sub` only. Every decimal an AST can produce is, within each branch of a finite
conditional tree, an integer linear combination of numerals parsed from the input or from literal or looked up strings.
No such combination equals a quotient by an input value in general, and `split` with a literal separator gives no
character or digit level access that could emulate long division within 128 nodes and no loops. A finite table cannot
replace the division either: `lookup` holds at most 32 exact string keys, and keying on raw lengths would memorize
answers, which the bootstrap instruction forbids and A4.6 does not count as nontrivial. `fmt` also rounds half to even,
not half away from zero.

Carve-out considered and rejected. For gauge exactly 50 the quotient is `2 * (final - gauge)`, which `add` can express,
and a rule could return `unknown` for unknown inputs and abstain elsewhere. That is a domain chosen to fit the language,
not the contract's domain. It would also fail the existing admission design: over the 64 `elong` admission cases for
seeds 0, 1, 2 and 20261024 it covers only 6 unknown cases plus 1 to 5 cases with gauge 50, so 7 to 11 of the 32 needed,
across 27 to 32 distinct gauge values. `none` is the right learner answer here. If a learner rule for `elong` is admitted
anyway, A4.6 requires reporting it as a classification miss, without changing R.

## Result

R = [`verdict`, `margin`, `temp_class`]. `elong` is outside R and is expected to stay model answered.

## Verification with the real interpreter

Each sealed AST passes `oz_rule.validate`. It was evaluated with `oz_rule.evaluate` on texts resolved by the D2 policy and
compared with `oracle.gold`:

| check | verdict | margin | temp_class |
|---|---|---|---|
| `admission_cases(seed, 256)`, 64 cases of the op, seeds 0, 1, 2, 7, 42, 20261024: coverage, covered errors | 64/64, 0 per seed | 64/64, 0 per seed | 64/64, 0 per seed |
| `jobs(seed, 400)`, 100 jobs of the op, same seeds | 100/100, 0 errors per seed | 100/100, 0 | 100/100, 0 |
| stress: admission and jobs, seeds 0 to 299 | 38,400 cases, 0 abstain, 0 errors | 38,400, 0, 0 | 38,400, 0, 0 |
| hand built edges (thresholds, `N/mm2`, trailing zeros, half ties, `-0`, 12 place values, unknowns, unlisted and miscased grades) | 315, 0 mismatches | 315, 0 | 315, 0 |

Out of grammar records (unit `kPa` or `F`, missing fields, no space before the unit, `+5`, `1e3`) abstain for all three.
The full `oz_rule.admit` path was not run, because the registry package for these operations does not exist yet; the
check above reproduces its case loop (value results, exact typed label match, coverage at least 32) without consumer
checks. Eligibility (an authorized input bound check, D1 `rule_provenance/1`) is a registry matter for the build, not
part of expressibility.

## Oracle review notes

The oracle matches `ops.md` on every rule tested: grade table and precedence, half to even for `margin` with negative zero
suppressed, half away from zero (`ROUND_HALF_UP` in Python Decimal) for `elong` with exact ties, inclusive `room`
endpoints. `test_ops.py` passes (66 tests). Two boundary observations, neither reachable from `data.py`:

1. The oracle parser accepts a value containing `;` not followed by a space, which `ops.md` and `field` exclude; on such a
   record the oracle answers and a rule abstains, so the only effect is fallback.
2. When the governing `unknown` value appears together with a malformed other field (for example `grade=S420` with a
   malformed `uts`, or `yield=unknown` with a malformed `uts` for `margin`), the oracle raises ValueError (outside the
   study) while the sealed rules answer `unknown`, following the precedence wording of rule 1. No job or admission case
   has this shape.

## Sealed reviewer artifacts

Stored outside the repo and outside every learner accessible directory, in the session scratchpad directory `rep/sealed`.
Content is not reproduced here.

| file | SHA-256 |
|---|---|
| `verdict.ast.json` | `5171571e0099d340ee7d367b0aa0eeeb83a8d6beb8953b45a69da5277ff31cce` |
| `margin.ast.json` | `3ac7ac7ee6689e33a49aec22841c78c51ade0c5d22d6e2a47417a0ec0bd7e0a8` |
| `temp_class.ast.json` | `1c96db2d161600f70a62bef1f4726fac8984001b607dabe3bbe416dc59448ebd` |
| `build_asts.py` (generator of the three files) | `0edb78fbd28509746c8557858b9cf4675c2360807080d6cfd2668bd7846d2d46` |

There is no sealed AST for `elong`. Convergence between these ASTs and learner ASTs is reported after scoring as an
observation only (A4.8).
