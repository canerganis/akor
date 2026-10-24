# Replication operations: tensile test records

Written independently of the oz-rule designer. The author read only `docs/design/ozmap-2026-10-24/bootstrap-spec-excerpt.txt`
(what the learner sees) and `bench/ozmap/data.py` (code style). No rule, AST or solution appears in this directory.

## Record type

One job text is one tensile test record in the form `key=value; key=value; ...` (segments separated by `"; "`, one `=`
per segment, keys unique). A record may end with exactly one line terminator (LF or CRLF); it is not part of the record
and is ignored. Keys may appear in any order. Additional keys are ignored.

| key | value | examples |
|---|---|---|
| specimen | specimen identifier, free text without `;` or `=` | `J23-0412`, `J23-0007-B` |
| grade | steel grade label | `S235`, `S275`, `S355`, `S460`, `A36`, `S420`, `unknown` |
| yield | yield strength: numeral, one space, unit `MPa` or `N/mm2`; or `unknown` | `372 MPa`, `372.0 N/mm2` |
| uts | ultimate tensile strength, same form as yield | `541 MPa`, `541.50 MPa` |
| gauge | original gauge length: numeral, one space, `mm`; or `unknown` | `50.00 mm`, `80 mm` |
| final | final gauge length after fracture, same form as gauge | `61.20 mm` |
| temp | test temperature: numeral, one space, unit `C` or `degC`; or `unknown` | `23 C`, `-5.0 degC`, `35.00 C` |
| operator | operator initials, free text | `mk` |

Numerals: optional ASCII minus, integer part (`0` or digits starting 1 to 9), optional `.` and one or more digits.
Trailing fractional zeros are allowed and carry no meaning (`372.0 MPa` equals `372 MPa`). `MPa` and `N/mm2` denote
the same quantity; `C` and `degC` denote the same quantity. No unit conversion ever happens. `unknown` is a legal value
for grade, yield, uts, gauge, final and temp. Gauge is always positive in this study.

Every operation maps one record text to one exact output string. Output strings contain no leading or trailing
whitespace and no line terminator.

## Operation `verdict`: grade acceptance

Minimum strengths by grade (fixed table for this study):

| grade | min yield (MPa) | min uts (MPa) |
|---|---:|---:|
| S235 | 235 | 360 |
| S275 | 275 | 410 |
| S355 | 355 | 470 |
| S460 | 460 | 540 |
| A36 | 250 | 400 |

Rules:
1. If grade is not one of the five table labels (this includes `unknown` and any other label such as `S420`), or if
   yield is `unknown`, or if uts is `unknown`, the output is `unknown`. This takes precedence over any comparison.
2. Otherwise the output is `pass` when yield >= min yield AND uts >= min uts (both inclusive, exact comparison, no
   rounding). Otherwise `fail`.

Outputs: `pass`, `fail`, `unknown`.

Expectation: rule-shaped. A fixed five-row table and two inclusive comparisons.

## Operation `margin`: strength margin

Rules:
1. If yield or uts is `unknown`, the output is `unknown`.
2. Otherwise compute uts minus yield exactly, round to an integer using round half to even (2.5 -> 2, 3.5 -> 4,
   -2.5 -> -2), and output the integer followed by one space and `MPa`.
3. A result that rounds to zero is written `0 MPa`, never `-0 MPa`. Negative margins keep their sign: `-12 MPa`.
   No grouping separators, no decimal point, no plus sign.

Examples: yield `372 MPa`, uts `541 MPa` -> `169 MPa`. yield `355.5 MPa`, uts `358 MPa` -> `2 MPa`.
yield `355.5 MPa`, uts `359 MPa` -> `4 MPa`. yield `400 MPa`, uts `399.6 N/mm2` -> `0 MPa`.

Expectation: rule-shaped. One subtraction and one fixed format; the unit synonym is a lexical nuisance, not arithmetic.

## Operation `elong`: percent elongation from gauge lengths

Rules:
1. If gauge or final is `unknown`, the output is `unknown`.
2. Otherwise compute (final - gauge) / gauge * 100 exactly as a rational number, round to one decimal place using
   round half away from zero (18.25 -> 18.3, -0.25 -> -0.3, 18.24 -> 18.2), and output the number with exactly one
   fractional digit, one space, and `%`.
3. A result that rounds to zero is written `0.0 %`, never `-0.0 %`. Negative values keep their sign: `-0.3 %`.

Examples: gauge `50.00 mm`, final `61.20 mm` -> `22.4 %`. gauge `80.00 mm`, final `94.60 mm` -> `18.3 %` (exact
value 18.25, a tie). gauge `30.00 mm`, final `35.00 mm` -> `16.7 %` (exact value 16.666...). gauge `50 mm`,
final `50.00 mm` -> `0.0 %`.

Expectation: not rule-shaped. The result depends on a division by a per-record value and the excerpt offers no
division or multiplication, so `none` is a legitimate answer.

## Operation `temp_class`: test temperature class

Rules:
1. If temp is `unknown`, the output is `unknown`.
2. Otherwise with t the temperature value in Celsius (unit `C` or `degC`, no conversion):
   `cold` when t < 10, `room` when 10 <= t <= 35, `hot` when t > 35. Both endpoints inclusive for `room`.
   Comparison is exact on the numeral, no rounding: `9.99 C` is `cold`, `35.01 C` is `hot`, `35.00 degC` is `room`.

Outputs: `cold`, `room`, `hot`, `unknown`.

Expectation: rule-shaped. Two inclusive thresholds on one value.

## Edge categories used by data.py

Per operation the job generator mixes: plain records; boundary records (values exactly at a threshold, one unit of the
last digit inside or outside); ties (margin differences ending in .5, elong exact values ending in 5 at the second
decimal); unknowns (the operation's own fields, and for verdict an unlisted or unknown grade); odd spellings (trailing
zeros such as `372.00 MPa`, `50.000 mm`, `23.0 C`, and leading zeros in the specimen identifier); reordered fields;
unit variants (`N/mm2`, `degC`); records with a terminal LF or CRLF. Admission cases come from a separate seed stream
and use specimen identifiers starting with `A` instead of `J`, so no admission text equals any job text.
