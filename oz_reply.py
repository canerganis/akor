"""OZ/9 replies, receipts, adapter capabilities and provider usage (wire stage-1f).

A reply is raw model text, one compact JSON array per packet job (docs/design/stage-1f-astra.md): [id,value]
for a success, [id,"error",code,message] for a job failure, id being the packet job ID. Acceptance is atomic:
the whole reply is accepted or none of it. Lines are split on LF (CRLF accepted, one trailing line end optional);
a blank line, a malformed line, an unknown, duplicate or missing ID, a line of any other length than two or four,
or a bad error code or message rejects everything. Nothing is repaired or merged. Valid successes and valid job failures are committed together.
The host, not the model, decides routing: an ID written by the model proves nothing about the answer next to it,
so the ledger records binding "declared" and semantic_verified false. regroup() folds the accepted results, the
job failures and the slots the host filled itself back into inbox jobs. Receipts stay host-side: the adapter
request carries one per call attempt to correlate the reply; they are not authentication or proof.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math

from oz import Error

PROTOCOL = 'oz.adapter/3'
LANGUAGE = 'OZ/9'
USAGE_FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_creation_input_tokens',
                'output_tokens', 'reasoning_output_tokens')
MAX_RESULT_BYTES = 65536
MAX_LINE_BYTES = 65536
CAPTURE_SLACK = 4096
MAX_VIOLATIONS = 20
BINDING = 'declared'
ERROR_CODES = ('missing_data', 'invalid_data', 'conflict', 'unsupported')
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
    def number(token):
        value = float(token)
        if not math.isfinite(value):
            raise Error('non-finite JSON value')
        return value
    return json.loads(text, object_pairs_hook=unique, parse_constant=constant, parse_float=number)


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


def slot_ids(job_map) -> tuple[str, ...]:
    """Packet job ID of every model slot: the inbox job ID for a job with one model slot,
    "<inbox ID>.<atom index>" for each model slot of a job with several."""
    counts = {}
    for mid, _ in job_map:
        counts[mid] = counts.get(mid, 0) + 1
    return tuple(mid if counts[mid] == 1 else f'{mid}.{atom}' for mid, atom in job_map)


@dataclass(frozen=True)
class Parsed:
    """Outcome of one reply text, accepted or rejected as a whole.

    accepted maps packet job ID -> result value and failed maps packet job ID -> (code, message) for a valid
    job failure; both are empty when the reply is rejected. received counts the lines that parsed as JSON;
    violations lists {line, reason} (1-based, capped, line 0 for the whole text); rejection is the reason
    the whole reply was refused, else None.
    """
    expected: int
    accepted: dict
    received: int
    violations: tuple
    rejection: str | None = None
    failed: dict = field(default_factory=dict)


def _rejected(n: int, received: int, bad: dict, reason: str) -> Parsed:
    violations = tuple({'line': number, 'reason': bad[number]} for number in sorted(bad))[:MAX_VIOLATIONS]
    return Parsed(n, {}, received, violations or ({'line': 0, 'reason': reason},), reason)


def _encodable(text: str) -> bool:
    try:
        text.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def parse_reply(text: object, ids) -> Parsed:
    """Judge a reply for the expected packet job IDs: exactly those IDs, each once, in any order."""
    ids = tuple(ids)
    n = len(ids)
    if not isinstance(text, str):
        raise Error('reply must be raw text')
    if len(text.encode('utf-8', 'surrogatepass')) > MAX_LINE_BYTES * n + CAPTURE_SLACK:
        return _rejected(n, 0, {}, 'reply exceeds the total capture limit')
    lines = text.split('\n')
    if lines[-1] == '':
        lines.pop()
    if not lines:
        return _rejected(n, 0, {}, 'reply has no result line')
    bad, received, seen = {}, 0, {}
    for number, line in enumerate(lines, 1):
        line = line[:-1] if line.endswith('\r') else line
        if not line.strip(' \t'):
            bad[number] = 'blank line'
            continue
        if len(line.encode('utf-8', 'surrogatepass')) > MAX_LINE_BYTES:
            bad[number] = f'line exceeds {MAX_LINE_BYTES} bytes'
            continue
        try:
            value = loads(line)
        except (ValueError, RecursionError, Error):
            bad[number] = 'malformed JSON line'
            continue
        received += 1
        if not isinstance(value, list) or len(value) not in (2, 4):
            bad[number] = 'line must be a two-element [id,value] or four-element [id,"error",code,message] array'
            continue
        key = value[0]
        if not isinstance(key, str) or key not in ids:
            bad[number] = 'unknown or non-string id'
            continue
        if key in seen:
            bad[number] = f'duplicate id {key}'
            continue
        if len(value) == 2:
            try:
                _store(value[1])
            except (ValueError, UnicodeEncodeError):
                bad[number] = 'result is not storable or exceeds its size limit'
                continue
            seen[key] = (True, value[1])
            continue
        _, marker, code, message = value
        if not isinstance(marker, str) or marker != 'error':
            bad[number] = 'a four-element line must have "error" as its second element'
        elif not isinstance(code, str) or code not in ERROR_CODES:
            bad[number] = 'error code must be one of ' + ', '.join(ERROR_CODES)
        elif not isinstance(message, str) or not message.strip() or not _encodable(message):
            bad[number] = 'error message must be a nonblank string'
        else:
            seen[key] = (False, (code, message))
    if bad:
        return _rejected(n, received, bad, 'a malformed or unknown line rejects the whole reply')
    if set(seen) != set(ids):
        return _rejected(n, received, {}, 'the reply does not cover exactly the expected jobs')
    return Parsed(n, {k: v for k, (ok, v) in seen.items() if ok}, received, (), None,
                  {k: v for k, (ok, v) in seen.items() if not ok})


@dataclass(frozen=True)
class Regrouped:
    """outcomes maps inbox job ID -> (status, text); status is ok, failed or retry.

    values maps the ID of every ok job to the compact JSON of its accepted native value
    (single slot: the value; several slots: {"results":[...]}), which is what dependents receive.
    A failed job's text is "<code>: <message>" of its first failing slot (atom order).
    """
    outcomes: dict
    parsed: Parsed
    values: dict = field(default_factory=dict)


def regroup(text: object, job_map, host_slots=()) -> Regrouped:
    """Parse a reply with one slot per job_map entry, then fold all slots into one outcome per inbox job.

    job_map lists (inbox job ID, atom index) per model slot; host_slots lists (inbox job ID, atom index,
    value) for slots the host filled itself. A single-slot job keeps its value. A multi-slot job stores {"results":[...]} in atom order and
    fails when any of its slots reported a job error. The reply is accepted whole or rejected whole: after a
    rejection every model job is ('retry', reason).
    """
    job_map = tuple(job_map)
    parsed = parse_reply(text, slot_ids(job_map)) if job_map else Parsed(0, {}, 0, ())
    groups = {}
    for pid, (mid, atom) in zip(slot_ids(job_map), job_map):
        groups.setdefault(mid, []).append((atom, pid, True))
    for mid, atom, value in host_slots:
        groups.setdefault(mid, []).append((atom, value, False))
    outcomes, values = {}, {}
    for mid, slots in groups.items():
        slots.sort(key=lambda slot: slot[0])
        if any(model and pid not in parsed.accepted and pid not in parsed.failed for _, pid, model in slots):
            outcomes[mid] = ('retry', RETRY_REASON)
            continue
        failure = next((parsed.failed[pid] for _, pid, model in slots if model and pid in parsed.failed), None)
        if failure is not None:
            outcomes[mid] = ('failed', f'{failure[0]}: {failure[1]}')
            continue
        parts = [parsed.accepted[pid] if model else pid for _, pid, model in slots]
        try:
            if len(parts) == 1:
                outcomes[mid] = ('ok', _store(parts[0]))
                values[mid] = _json(parts[0])
            else:
                combined = _json({'results': parts})
                outcomes[mid] = ('ok', _store(combined))
                values[mid] = combined
        except (ValueError, UnicodeEncodeError):
            outcomes[mid] = ('retry', RETRY_REASON)
    return Regrouped(outcomes, parsed, values)


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


@dataclass(frozen=True)
class Failure:
    """A job failure for encode_reply."""
    code: str
    message: str


def encode_reply(results: dict, ids=None) -> str:
    """Build reply text from {packet job ID: result value}, e.g. for test adapters: one line per ID.

    A Failure value becomes the error line [id,"error",code,message]."""
    def line(mid):
        value = results[mid]
        return _json([mid, 'error', value.code, value.message] if isinstance(value, Failure) else [mid, value])
    return '\n'.join(line(mid) for mid in (results if ids is None else ids))
