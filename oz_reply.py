"""OZ/9 replies, receipts, adapter capabilities and provider usage.

A reply is raw model text, one JSON array per line: [i,value] on success and
[i,null,error] on failure, where i is the zero-based index of an item in the
prompt's j list (OZ9.md 3). parse_reply() accepts each index that has exactly one
valid line and never repairs a line; a fence, prose or any other non-array line
invalidates the whole reply. regroup() folds accepted items and the slots the host
filled itself back into inbox jobs; a job with any unaccepted item is retried alone.
Receipts stay host-side: the adapter request carries one per call attempt to
correlate the reply; they are not authentication or proof.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

from oz import Error

PROTOCOL = 'oz.adapter/3'
LANGUAGE = 'OZ/9'
USAGE_FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_creation_input_tokens',
                'output_tokens', 'reasoning_output_tokens')
MAX_RESULT_BYTES = 65536
MAX_LINE_BYTES = 65536
MAX_ERROR_BYTES = 1024
CAPTURE_SLACK = 4096
MAX_VIOLATIONS = 20
INDEX_TOKEN = re.compile(r'0|[1-9][0-9]*')
FIRST_TOKEN = re.compile(r'\s*\[\s*(-?[0-9][0-9.eE+-]*)')
RETRY_REASON = 'adapter_invalid_reply (Error)'


def loads(text: str):
    """Strict JSON: duplicate object keys and NaN/Infinity are errors."""
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise Error('duplicate JSON key')
            obj[key] = value
        return obj
    def constant(_):
        raise Error('non-finite JSON value')
    return json.loads(text, object_pairs_hook=unique, parse_constant=constant)


def check_capabilities(value: object) -> dict:
    """Fail before claim/call when the adapter cannot speak what will be sent."""
    if (not isinstance(value, dict) or set(value) != {'protocols', 'languages'}
            or any(not isinstance(value[k], list) or any(not isinstance(v, str) for v in value[k]) for k in value)):
        raise Error('adapter capabilities need protocols and languages lists')
    if PROTOCOL not in value['protocols'] or LANGUAGE not in value['languages']:
        raise Error(f'adapter does not support {PROTOCOL} and {LANGUAGE}')
    return value


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _store(value) -> str:
    """Stored text: a string as is, any other JSON value as compact JSON text.

    A blank string would be an empty stored result, which the inbox refuses, so it is
    stored as its JSON text instead. Raises ValueError or UnicodeEncodeError when the
    value cannot be stored or is over the size limit.
    """
    text = value if isinstance(value, str) and value.strip() else _json(value)
    if len(text.encode('utf-8')) > MAX_RESULT_BYTES:
        raise ValueError('result exceeds 65536 bytes')
    return text


@dataclass(frozen=True)
class Parsed:
    """Per-index outcome of one reply text.

    accepted maps index -> ('ok', value) or ('failed', reason); received counts the
    lines that parsed as a JSON array; violations lists {line, reason} (1-based, capped,
    line 0 for the whole text). envelope is the reason the whole reply was invalidated, else None.
    """
    expected: int
    accepted: dict
    received: int
    violations: tuple
    envelope: str | None = None


def _canonical_index(line: str, row: list):
    """The index of a parsed array line, only when its raw token is a canonical nonnegative integer."""
    if not row or type(row[0]) is not int:
        return None
    match = FIRST_TOKEN.match(line)
    return row[0] if match and INDEX_TOKEN.fullmatch(match.group(1)) else None


def parse_reply(text: object, n: int) -> Parsed:
    if not isinstance(text, str):
        raise Error('reply must be raw text, one JSON array per line')
    if len(text.encode('utf-8', 'surrogatepass')) > MAX_LINE_BYTES * n + CAPTURE_SLACK:
        reason = 'reply exceeds the total capture limit'
        return Parsed(n, {}, 0, ({'line': 0, 'reason': reason},), reason)
    received, bad, valid, seen, envelope = 0, {}, {}, {}, None
    for number, line in enumerate(text.split('\n'), 1):
        if line.endswith('\r'):
            line = line[:-1]
        if not line.strip():
            continue
        if len(line.encode('utf-8', 'surrogatepass')) > MAX_LINE_BYTES:
            bad[number] = f'line exceeds {MAX_LINE_BYTES} bytes'
            continue
        if not line.lstrip().startswith('['):
            envelope = envelope or 'a fence, prose or non-array line invalidates the whole reply'
            bad[number] = 'not a JSON array line'
            continue
        try:
            row = loads(line)
        except (ValueError, RecursionError, Error):
            bad[number] = 'malformed array line'
            continue
        received += 1
        index = _canonical_index(line, row)
        if index is None:
            bad[number] = 'index is not a canonical nonnegative integer'
            continue
        if index >= n:
            bad[number] = 'index out of range'
            continue
        seen.setdefault(index, []).append(number)
        if len(row) not in (2, 3):
            bad[number] = 'array needs 2 or 3 elements'
        elif len(row) == 3 and (row[1] is not None or not isinstance(row[2], str) or not row[2].strip()):
            bad[number] = 'failure needs null and a nonblank error string'
        else:
            try:
                if len(row) == 3 and len(row[2].encode('utf-8')) > MAX_ERROR_BYTES:
                    raise ValueError('error exceeds 1024 bytes')
                _store(row[1] if len(row) == 2 else row[2])
            except (ValueError, UnicodeEncodeError):
                bad[number] = 'result is not storable or exceeds its size limit'
            else:
                valid[number] = row
    accepted = {}
    for index, numbers in seen.items():
        if len(numbers) > 1:
            for number in numbers:
                bad[number] = f'duplicate lines for index {index}'
        elif numbers[0] in valid:
            row = valid[numbers[0]]
            accepted[index] = ('ok', row[1]) if len(row) == 2 else ('failed', row[2])
    violations = tuple({'line': number, 'reason': bad[number]} for number in sorted(bad))[:MAX_VIOLATIONS]
    return Parsed(n, {} if envelope else accepted, received, violations, envelope)


@dataclass(frozen=True)
class Regrouped:
    """outcomes maps inbox job ID -> (status, text); status is ok, failed or retry."""
    outcomes: dict
    parsed: Parsed


def regroup(text: object, job_map, host_slots=()) -> Regrouped:
    """Parse a reply with one slot per j item, then fold all slots into one outcome per inbox job.

    job_map lists (inbox job ID, atom index) per j item; host_slots lists (inbox job ID, atom index,
    value) for slots the host filled itself. A single-slot job keeps its value. A multi-slot job stores
    {"results":[...]} in atom order; if any slot failed, the job fails with the local-index reasons. A
    job with an unaccepted model slot is ('retry', reason) and does not affect the other jobs.
    """
    job_map = tuple(job_map)
    parsed = parse_reply(text, len(job_map))
    groups = {}
    for index, (mid, atom) in enumerate(job_map):
        groups.setdefault(mid, []).append((atom, index, True))
    for mid, atom, value in host_slots:
        groups.setdefault(mid, []).append((atom, value, False))
    outcomes = {}
    for mid, slots in groups.items():
        slots.sort(key=lambda slot: slot[0])
        if any(model and index not in parsed.accepted for _, index, model in slots):
            outcomes[mid] = ('retry', RETRY_REASON)
            continue
        parts = [parsed.accepted[index] if model else ('ok', index) for _, index, model in slots]
        failed = [f'{n}: {value}' for n, (status, value) in enumerate(parts) if status != 'ok']
        try:
            if len(parts) == 1:
                status, value = parts[0]
                outcomes[mid] = (status, _store(value))
            elif failed:
                outcomes[mid] = ('failed', _store('; '.join(failed)))
            else:
                outcomes[mid] = ('ok', _store(_json({'results': [value for _, value in parts]})))
        except (ValueError, UnicodeEncodeError):
            outcomes[mid] = ('retry', RETRY_REASON)
    return Regrouped(outcomes, parsed)


def validate_usage(value: object) -> dict:
    """Normalized provider usage; subsets are never added twice, missing is unknown."""
    if not isinstance(value, dict) or set(value) - set(USAGE_FIELDS):
        raise Error('usage allows only ' + ', '.join(USAGE_FIELDS))
    if any(type(n) is not int or n < 0 for n in value.values()):
        raise Error('usage counts must be nonnegative integers')
    total = value.get('input_tokens')
    subsets = [value[k] for k in ('cached_input_tokens', 'cache_creation_input_tokens') if k in value]
    if total is not None and sum(subsets) > total:
        raise Error('cached and cache-creation input exceed total input')
    if 'output_tokens' in value and value.get('reasoning_output_tokens', 0) > value['output_tokens']:
        raise Error('reasoning output exceeds total output')
    return dict(value)


def validate_response(value: object, job_map, host_slots=()) -> tuple[Regrouped, dict]:
    """Adapter response {"reply": "<raw text>", "usage":...}; usage comes from provider accounting."""
    if not isinstance(value, dict) or 'reply' not in value or set(value) - {'reply', 'usage'}:
        raise Error('adapter response must be {"reply":...,"usage":...}')
    usage = validate_usage(value.get('usage', {}))
    return regroup(value['reply'], job_map, host_slots), usage


def encode_reply(outcomes: dict, ids) -> str:
    """Build reply text from (status, text) pairs, e.g. for test adapters: one line per ID."""
    lines = []
    for i, mid in enumerate(ids):
        status, text = outcomes[mid]
        lines.append(_json([i, text]) if status == 'ok' else _json([i, None, text]))
    return '\n'.join(lines)
