# codereview-witness-v1

This file defines the frozen witness syntax for codereview-v1.

## Finding record

A per-file response is a JSON array of finding objects. Each object has
exactly these four keys:

- `file`: the exact module path relative to fixtures/codereview-v1,
  using forward slashes, for example `packA/example.py`.
- `line`: a positive JSON integer, excluding booleans, identifying a
  1-based physical line in the shipped module. Blank lines count.
- `class`: exactly `off_by_one` or `missing_guard`.
- `witness`: an object with the schema below.

A clean-file response is exactly `[]`. Markdown fences and explanatory
text are not part of an oracle response. Examples here use fictitious
functions and do not disclose fixture answers.

## Witness schema

Every witness has exactly four keys:

    {
      "function": "lookup",
      "args": [["first", "second"], 1],
      "kwargs": {},
      "expected": {"return": "second"}
    }

- `function` is the name of a public, synchronous function defined
  directly in the target module. It must be a Python identifier and
  must not start with an underscore. Dotted paths are forbidden.
- `args` is a JSON array of positional arguments.
- `kwargs` is a JSON object of keyword arguments. Its keys must be
  Python identifiers and must not start with an underscore.
- `expected` is an object with exactly one key: either `return` or
  `exception`. Neither additional keys nor both keys are permitted.

An exception expectation looks like this:

    {
      "function": "lookup",
      "args": [[], -1],
      "kwargs": {},
      "expected": {"exception": "ValueError"}
    }

The allowed exception names are exactly `ValueError`, `TypeError`,
`IndexError`, `KeyError`, `ZeroDivisionError`, and `OverflowError`.
They denote the corresponding built-in types. Matching requires exact
type identity, not a subclass match; messages and tracebacks are ignored.

The entire record must be strict JSON. Reject duplicate object keys,
NaN, Infinity, and nonfinite values after numeric decoding. Use Python
3.12 JSON decoding semantics for ordinary integers and finite floats.
Arguments and expected returns may contain only JSON values: null,
booleans, numbers, strings, arrays and objects with string keys.

## Execution and equality

1. Validate the record and witness schema before loading either module.
2. Resolve the file against an explicit fixture allowlist. Do not use a
   submitted path or function name to import arbitrary code.
3. Run the shipped and reference calls in separate fresh O1 sandbox
   processes, with the same limits. Decode independent copies of args
   and kwargs for each call. Invoke function(*args, **kwargs) once.
4. A return expectation matches only a normal return that is recursively
   equal to the expected JSON value. Require exact Python types at every
   node: bool differs from int, int differs from float, and tuple differs
   from list. Compare list order and length; compare dictionary key sets
   and values while ignoring insertion order. Compare finite floats by
   numeric equality, so positive and negative zero compare equal.
5. An exception expectation matches only the exact allowed exception
   raised by the target call. Import errors, invalid function selection,
   invalid binding of args/kwargs, timeouts, process failures and resource
   limits are execution errors, not successful exception expectations.
   Prevalidate binding with inspect.signature(function).bind(*args, **kwargs).
6. A witness proves a differential only when the reference expectation
   matches and the shipped expectation does not. A different normal
   return or a target-call exception can establish a shipped mismatch.
   Infrastructure failures cannot establish a mismatch.

Inputs must meet each module's documented domain, except when exercising
an explicitly documented rejection rule. Behavior on unsupported input
types is not a fixture defect.

A seeded finding additionally needs the frozen class and a reported
line within the seed's inclusive span. A submitted witness need not be
identical to the hidden witness. Multiple symptoms caused by one seed
still represent one seed. A real defect outside the frozen seeds must
be reported separately and repaired before later runs, as preregistered.

## Seed span rule

This rule applies to every seed. Spans are inclusive, 1-based physical
line ranges [start_line, end_line] in the shipped file. Replacements
and deletions must affect only shipped lines within that range.

An insertion after k shipped lines is inside the span exactly when
start_line - 1 <= k <= end_line. Thus insertions immediately before
start_line, between lines in the span, and immediately after end_line
all count as inside. At the beginning of the file k is 0; at the end
k is the shipped file's physical line count. Every line in an inserted
block belongs to the same insertion boundary. Every reference edit
must satisfy this rule for its seed.

This edit-containment rule does not expand the accepted finding lines:
a finding must still name an existing shipped line within the inclusive
span. An adjacent line outside the span is not accepted merely because
it borders an allowed insertion boundary.

## Layout and isolation

Each pack directory contains exactly its three reviewable modules.
Only the selected pack and this format specification belong in the
review environment. Keep answer_key.json, ref/, tests/, and the hash
manifest in evaluator-only storage inaccessible to callers and workers.
A directory label alone does not enforce isolation.

answer_key.json uses paths relative to fixtures/codereview-v1.
Its hidden_witness values use this exact witness schema. Seed spans
refer to shipped files, never reference files. Clean modules have
seeds: [] and use the shipped file as their reference.

The reference test loader imports fixture modules and Python standard
library modules only. It imports no executor code. Each test file is
the complete supplied suite for its corresponding module.

From fixtures/codereview-v1, run all reference suites with:

    python -B -m unittest discover -s tests -p "test_*.py"

FIXTURE_IMPLEMENTATION defaults to reference. Set it to shipped to run
the identical suites against the reviewable versions. Unknown mode
values fail rather than selecting an implementation implicitly.

## Bytes, validation and pilot scope

Save every supplied file as UTF-8 without a BOM, with LF line endings
and exactly one final LF. SHA256SUMS hashes those exact bytes for every
other supplied file. It does not hash itself. Freeze its hash separately
in the host's preregistered run manifest.

Author verification used Python 3.12.12 and in-memory module loading:
24 reference test methods passed; all four hidden witnesses mismatched
on shipped code and matched on reference code. Both clean-control
suites passed against their shipped bytes. The file-based support
loader was syntax-checked; filesystem discovery was not executed.

These artifacts supply fixtures, reference suites, fixes and witnesses.
They do not constitute the full pilot freeze: caller prompts, the
unrelated fill prefix, evaluator implementation, sandbox configuration,
accounting and admission checks must also be frozen before model calls.
No pilot model calls or ranking runs were performed during authoring.
