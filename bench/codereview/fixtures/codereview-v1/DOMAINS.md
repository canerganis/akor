# codereview-v1 domains

This specification applies to the six shipped modules and their corresponding
references. It changes no module, source line, answer-key span, or reference file.

## Compatibility limitation

The frozen Q5 rule is not fully consistent with the unchanged implementations.
Both sample_stats modules call float(value) before checking the sample bounds.
For example, the integer 10**400 causes OverflowError in every public sample
function, although Q5 requires ValueError for this out-of-range sample.
A 401-digit integer is representable in the strict JSON witness format.

This specification preserves Q5. OverflowError is not an authorized replacement
expectation, and large integers are not silently excluded from the rejection
domain. Consequently, full implementation conformance cannot be asserted.

The four hidden witnesses in answer_key.json are all inside their functions'
normal domains. This was checked by source inspection. Runtime validation was
unavailable because the local Python environment could not start.

## Interpretation

The executable specification below defines every public function's parameter
types, default arguments, and documented rejection predicates.

Classification has three outcomes:

- `normal`: arguments satisfy the types and no documented rejection applies.
- `rejection`: arguments satisfy the types and at least one documented
  rejection applies. The required exception is exactly built-in ValueError.
- `outside`: unsupported types, invalid argument binding, or an unknown function.
  No exception expectation makes such a call an admissible witness.

A rejection may be exercised by a witness exactly when `witness_allowed` is
true. Its expectation must be `{"exception":"ValueError"}`. Exception messages
are irrelevant. When multiple rejection predicates apply, the exception remains
ValueError; no message or validation order is promised.

`witness_allowed` describes domain and JSON-value eligibility only. The complete
record must also pass WITNESS_FORMAT.md, including duplicate-key rejection.
Admissibility alone does not establish a shipped/reference differential.

All types are exact Python built-in types after JSON decoding. Integer
parameters exclude booleans and floats, including integral floats such as 2.0.
Numeric samples accept integers and floats but exclude booleans. Tuples,
custom objects, and non-string dictionary keys are unsupported.

No additional numeric magnitude, string length, list length, or nesting limits
are imposed here. Decoder and sandbox resource limits remain separate execution
constraints.

Nonfinite numeric samples belong to the documented ValueError rejection
contract, but cannot occur in strict JSON witnesses. Nonfinite floats anywhere
else in a recursive JSON value are outside that value's domain.

## Executable domain specification

This block uses Python 3.12 semantics. It does not import or execute fixture
modules. Each SPECS entry identifies a module-relative path and public function.
Parameter order is positional order; all parameters also accept keyword binding.
Only make_header.delimiter has a default.

```python
import inspect
import math
import re


def integer(value):
    return type(value) is int


def number(value):
    return type(value) in (int, float)


def string(value):
    return type(value) is str


def strict_json(value):
    if value is None or type(value) in (bool, int, str):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(strict_json(item) for item in value)
    if type(value) is dict:
        return all(
            type(key) is str and strict_json(item)
            for key, item in value.items()
        )
    return False


def list_of(predicate):
    return lambda value: (
        type(value) is list and all(predicate(item) for item in value)
    )


def identifier(value):
    return (
        type(value) is str
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is not None
    )


def string_map(value):
    return (
        type(value) is dict
        and all(
            type(key) is str and type(item) is str
            for key, item in value.items()
        )
    )


def identifier_map(value):
    return string_map(value) and all(identifier(key) for key in value)


def bad_sample(value):
    # Check integer bounds directly, without float conversion overflow.
    return (
        (type(value) is float and not math.isfinite(value))
        or not (-1000000 <= value <= 1000000)
    )


def bad_ranges(ranges):
    return any(
        len(pair) != 2 or pair[0] > pair[1]
        for pair in ranges
    )


def bad_settings_text(text):
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not identifier(key.strip()):
            return True
    return False


JSON_LIST = list_of(strict_json)
STRING_LIST = list_of(string)
SAMPLE_LIST = list_of(number)
RANGE_LIST = list_of(list_of(integer))

TYPES = {
    "int": integer,
    "str": string,
    "json_list": JSON_LIST,
    "string_list": STRING_LIST,
    "sample_list": SAMPLE_LIST,
    "range_list": RANGE_LIST,
    "string_map": string_map,
    "identifier_map": identifier_map,
}


def negative(name):
    return (
        name + " < 0",
        lambda arguments: arguments[name] < 0,
    )


def nonpositive(name):
    return (
        name + " <= 0",
        lambda arguments: arguments[name] <= 0,
    )


BAD_SAMPLES = (
    "nonfinite or out-of-range sample",
    lambda a: any(bad_sample(value) for value in a["values"]),
)

BAD_RANGES = (
    "inner list length != 2 or start > end",
    lambda a: bad_ranges(a["ranges"]),
)

DUPLICATE_WORKERS = (
    "duplicate workers",
    lambda a: len(set(a["workers"])) != len(a["workers"]),
)


def entry(parameters, rejections=(), defaults=None):
    return {
        "parameters": parameters,
        "rejections": rejections,
        "defaults": {} if defaults is None else defaults,
    }


SPECS = {
    ("packA/paging.py", "page_count"): entry(
        {"item_count": "int", "page_size": "int"},
        (nonpositive("page_size"), negative("item_count")),
    ),
    ("packA/paging.py", "get_page"): entry(
        {"items": "json_list", "page_number": "int", "page_size": "int"},
        (nonpositive("page_size"), negative("page_number")),
    ),
    ("packA/paging.py", "page_for_index"): entry(
        {"item_index": "int", "page_size": "int"},
        (nonpositive("page_size"), negative("item_index")),
    ),
    ("packA/paging.py", "page_sizes"): entry(
        {"item_count": "int", "page_size": "int"},
        (nonpositive("page_size"), negative("item_count")),
    ),
    ("packA/paging.py", "page_label"): entry(
        {"page_number": "int", "item_count": "int", "page_size": "int"},
        (
            nonpositive("page_size"),
            negative("item_count"),
            negative("page_number"),
            (
                "absent page",
                lambda a: (
                    a["page_size"] > 0
                    and a["item_count"] >= 0
                    and a["page_number"] >= 0
                    and a["page_number"] >= (
                        (a["item_count"] + a["page_size"] - 1)
                        // a["page_size"]
                    )
                ),
            ),
        ),
    ),

    ("packA/sample_stats.py", "mean"): entry(
        {"values": "sample_list"}, (BAD_SAMPLES,),
    ),
    ("packA/sample_stats.py", "spread"): entry(
        {"values": "sample_list"}, (BAD_SAMPLES,),
    ),
    ("packA/sample_stats.py", "latest"): entry(
        {"values": "sample_list", "limit": "int"},
        (negative("limit"), BAD_SAMPLES),
    ),
    ("packA/sample_stats.py", "describe"): entry(
        {"values": "sample_list"}, (BAD_SAMPLES,),
    ),
    ("packA/sample_stats.py", "centered"): entry(
        {"values": "sample_list"}, (BAD_SAMPLES,),
    ),

    ("packA/labels.py", "slug"): entry(
        {"label": "str"},
    ),
    ("packA/labels.py", "unique_labels"): entry(
        {"labels": "string_list"},
    ),
    ("packA/labels.py", "make_header"): entry(
        {"labels": "string_list", "delimiter": "str"},
        (
            (
                "unsupported string delimiter",
                lambda a: a["delimiter"] not in (",", ";", "\t", "|"),
            ),
        ),
        {"delimiter": ","},
    ),
    ("packA/labels.py", "label_map"): entry(
        {"labels": "string_list"},
    ),
    ("packA/labels.py", "is_slug"): entry(
        {"value": "str"},
    ),

    ("packB/ranges.py", "compact_ranges"): entry(
        {"ranges": "range_list"}, (BAD_RANGES,),
    ),
    ("packB/ranges.py", "covered_count"): entry(
        {"ranges": "range_list"}, (BAD_RANGES,),
    ),
    ("packB/ranges.py", "contains"): entry(
        {"ranges": "range_list", "value": "int"}, (BAD_RANGES,),
    ),
    ("packB/ranges.py", "shift_ranges"): entry(
        {"ranges": "range_list", "offset": "int"}, (BAD_RANGES,),
    ),
    ("packB/ranges.py", "bounding_range"): entry(
        {"ranges": "range_list"}, (BAD_RANGES,),
    ),

    ("packB/rotation.py", "rotate_left"): entry(
        {"items": "json_list", "offset": "int"},
    ),
    ("packB/rotation.py", "rotation_order"): entry(
        {"workers": "string_list", "round_number": "int"},
        (negative("round_number"), DUPLICATE_WORKERS),
    ),
    ("packB/rotation.py", "assign_tasks"): entry(
        {"tasks": "json_list", "workers": "string_list"},
        (
            ("empty workers", lambda a: len(a["workers"]) == 0),
            DUPLICATE_WORKERS,
        ),
    ),
    ("packB/rotation.py", "chunk_tasks"): entry(
        {"tasks": "json_list", "size": "int"},
        (nonpositive("size"),),
    ),
    ("packB/rotation.py", "interleave"): entry(
        {"left": "json_list", "right": "json_list"},
    ),

    ("packB/settings.py", "parse_settings"): entry(
        {"text": "str"},
        (
            (
                "nonblank noncomment line lacks '=' or a valid stripped key",
                lambda a: bad_settings_text(a["text"]),
            ),
        ),
    ),
    ("packB/settings.py", "render_settings"): entry(
        {"settings": "string_map"},
        (
            (
                "invalid identifier key",
                lambda a: any(
                    not identifier(key) for key in a["settings"]
                ),
            ),
            (
                "outer whitespace in value",
                lambda a: any(
                    value != value.strip()
                    for value in a["settings"].values()
                ),
            ),
            (
                "line boundary in value",
                lambda a: any(
                    value != "" and value.splitlines() != [value]
                    for value in a["settings"].values()
                ),
            ),
        ),
    ),
    ("packB/settings.py", "overlay"): entry(
        {"base": "identifier_map", "updates": "identifier_map"},
    ),
    ("packB/settings.py", "select_prefix"): entry(
        {"settings": "identifier_map", "prefix": "str"},
    ),
}


def classify(module, function, args, kwargs):
    """Classify a decoded call without executing its target function."""
    outside = {"kind": "outside", "witness_allowed": False}

    if type(module) is not str or type(function) is not str:
        return outside
    spec = SPECS.get((module, function))
    if spec is None:
        return outside
    if type(args) is not list or type(kwargs) is not dict:
        return outside
    if not all(type(key) is str for key in kwargs):
        return outside

    signature = inspect.Signature([
        inspect.Parameter(
            name,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=spec["defaults"].get(name, inspect.Parameter.empty),
        )
        for name in spec["parameters"]
    ])
    try:
        bound = signature.bind(*args, **kwargs)
    except TypeError:
        return outside
    bound.apply_defaults()
    arguments = bound.arguments

    if not all(
        TYPES[type_name](arguments[name])
        for name, type_name in spec["parameters"].items()
    ):
        return outside

    rejected = [
        description
        for description, predicate in spec["rejections"]
        if predicate(arguments)
    ]
    eligible = strict_json(args) and strict_json(kwargs)
    if rejected:
        return {
            "kind": "rejection",
            "witness_allowed": eligible,
            "expected": {"exception": "ValueError"},
            "rules": rejected,
        }
    return {"kind": "normal", "witness_allowed": eligible}
```

## Boundary and string rules

- Paging page numbers are zero based. Positive page sizes and nonnegative
  counts, indices, and page numbers have no additional domain upper bound.
  get_page accepts empty items and pages beyond the final page.
  page_for_index has no item-count constraint.
  page_label rejects every page when item_count is zero.
- Every sample function accepts an empty values list. Normal samples lie in
  the inclusive interval [-1000000, 1000000]. latest accepts zero and arbitrarily
  large nonnegative limits. Invalid samples remain rejections when limit is zero.
- Every label string may be empty or contain arbitrary Unicode, whitespace,
  punctuation, or line boundaries. Labels need not be unique or canonical.
  is_slug returns a boolean for any string; a noncanonical string is not a
  rejection. Slugs retain ASCII letters and digits, lowercase letters, replace
  separator runs between retained characters with a hyphen, omit outer
  separators, and use "item" when nothing remains.
- make_header accepts exactly comma, semicolon, tab, and pipe as delimiters.
  Every other string is a ValueError rejection. Nonstrings are outside.
- Every ranges argument is a list of lists whose elements are integers,
  excluding booleans. Length violations remain exercisable only when these
  element types are correct. Empty inner lists are ValueError rejections;
  an empty outer list is normal. Equal endpoints, negative endpoints,
  unsorted ranges, duplicate ranges, overlaps, and adjacency are normal.
  Valid ranges are closed. Offsets and contains.value may be any integers.
- Rotation offsets may be negative. Empty items, tasks, left, and right lists
  are normal. Their elements may recursively contain null, booleans, integers,
  finite floats, arbitrary strings, lists, and dictionaries with string keys.
  Worker strings may be empty or contain arbitrary Unicode. Duplicate workers
  are determined by exact, case-sensitive string equality.
  rotation_order accepts empty workers for nonnegative rounds.
  assign_tasks rejects empty workers even when tasks is empty.
  chunk_tasks rejects nonpositive size even when tasks is empty.
- Settings identifiers use a full ASCII match of
  [A-Za-z_][A-Za-z0-9_]* and are case-sensitive.
  render_settings permits arbitrary string keys at the type-checking stage,
  then rejects nonidentifiers with ValueError.
  overlay and select_prefix exclude nonidentifier keys from their domains;
  those keys are not documented rejection cases for these two functions.
- overlay and select_prefix values are arbitrary strings, including empty
  strings, outer whitespace, and line boundaries. prefix is any string,
  including an empty string. No stripping or identifier constraint applies
  to prefix.
- parse_settings accepts any string. Python str.splitlines() determines lines.
  Each line is stripped with str.strip(). Blank lines and stripped lines
  beginning with "#" are ignored. Every remaining line must contain "=" and
  have a valid stripped identifier before its first "="; otherwise ValueError
  is required. Values are stripped. Empty values and additional "=" characters
  are allowed. Duplicate keys use the last value. Inline comments and escape
  processing are not implemented.
- render_settings accepts empty values. For each nonempty value, both
  value == value.strip() and value.splitlines() == [value] must hold.
  These predicates use Python's complete whitespace and line-boundary rules,
  not only ASCII spaces or LF. Empty settings dictionaries are normal.

## Expected exceptions

Every rejection listed above permits only exact built-in ValueError.
No documented rejection permits TypeError, IndexError, KeyError,
ZeroDivisionError, or OverflowError as its expected exception.

An unexpected exception on a normal-domain shipped call is a possible defect,
not a reason to exclude the input or change its required reference behavior.
In particular, empty sample lists and empty rotation lists remain normal-domain
inputs despite the shipped missing guards.

No rejection may be used to bypass another argument's type or domain
requirements. For example, a negative page size does not authorize non-JSON
items, and malformed range lengths do not authorize boolean endpoints.
