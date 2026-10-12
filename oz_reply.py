"""OZ/9 replies, receipts, adapter capabilities and provider usage (wire stage-1d).

A reply is raw model text in one of two modes (docs/design/stage-1d-astra.md). jsonl: one
[id,result] array per line, id being the packet job ID. value: one result line for the single
job. Acceptance is atomic: the whole reply is accepted or none of it. Lines are split on LF with
only ASCII space, tab and CR stripped at both ends and blank lines ignored; byte-identical repeats
count once (recorded as duplicate_lines); an unknown or conflicting ID, a malformed line, more than
2N non-blank lines or an ID set that is not exactly the expected set rejects everything. Nothing
is repaired or merged. The host, not the model, decides routing: an ID written by the model proves
nothing about the answer next to it, so the ledger records binding "declared" (jsonl) or "host"
(value) and semantic_verified false. regroup() folds the accepted results and the slots the host
filled itself back into inbox jobs. Receipts stay host-side: the adapter request carries one per
call attempt to correlate the reply; they are not authentication or proof.
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
STRIP = ' \t\r'
BINDINGS = {'jsonl': 'declared', 'value': 'host'}
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

    accepted maps packet job ID -> result value (empty when rejected); received counts the lines that
    parsed as JSON; duplicate_lines counts byte-identical repeated lines that were tolerated;
    violations lists {line, reason} (1-based, capped, line 0 for the whole text);
    rejection is the reason the whole reply was refused, else None.
    """
    expected: int
    accepted: dict
    received: int
    violations: tuple
    rejection: str | None = None
    duplicate_lines: int = 0


def _rejected(n: int, received: int, bad: dict, reason: str, duplicates: int = 0) -> Parsed:
    violations = tuple({'line': number, 'reason': bad[number]} for number in sorted(bad))[:MAX_VIOLATIONS]
    return Parsed(n, {}, received, violations or ({'line': 0, 'reason': reason},), reason, duplicates)


def parse_reply(text: object, ids, mode: str = 'jsonl') -> Parsed:
    """Judge a reply for the expected packet job IDs (one ID in value mode, where lines carry no ID)."""
    if mode not in BINDINGS:
        raise Error('reply mode must be jsonl or value')
    ids = tuple(ids)
    n = len(ids)
    if mode == 'value' and n != 1:
        raise Error('value mode expects exactly one job')
    if not isinstance(text, str):
        raise Error('reply must be raw text')
    if len(text.encode('utf-8', 'surrogatepass')) > MAX_LINE_BYTES * n + CAPTURE_SLACK:
        return _rejected(n, 0, {}, 'reply exceeds the total capture limit')
    lines = [(number, raw.strip(STRIP)) for number, raw in enumerate(text.split('\n'), 1)]
    lines = [(number, line) for number, line in lines if line]
    if len(lines) > 2 * n:
        return _rejected(n, 0, {}, f'more than {2 * n} non-blank lines')
    if not lines:
        return _rejected(n, 0, {}, 'reply has no result line')
    bad, received, rows = {}, 0, []
    for number, line in lines:
        if len(line.encode('utf-8', 'surrogatepass')) > MAX_LINE_BYTES:
            bad[number] = f'line exceeds {MAX_LINE_BYTES} bytes'
            continue
        try:
            value = loads(line)
        except (ValueError, RecursionError, Error):
            bad[number] = 'malformed JSON line'
            continue
        received += 1
        if mode == 'jsonl':
            if not isinstance(value, list) or len(value) != 2:
                bad[number] = 'line must be a two-element [id,result] array'
                continue
            if not isinstance(value[0], str) or value[0] not in ids:
                bad[number] = 'unknown or non-string id'
                continue
            key, result = value
        else:
            key, result = ids[0], value
        try:
            _store(result)
        except (ValueError, UnicodeEncodeError):
            bad[number] = 'result is not storable or exceeds its size limit'
            continue
        rows.append((number, key, line, result))
    if bad:
        return _rejected(n, received, bad, 'a malformed or unknown line rejects the whole reply')
    seen = {}
    for number, key, line, result in rows:
        if seen.setdefault(key, (line, result))[0] != line:
            bad[number] = f'conflicting lines for id {key}' if mode == 'jsonl' else 'conflicting result lines'
    duplicates = len(rows) - len(seen)
    if bad:
        return _rejected(n, received, bad, 'conflicting lines reject the whole reply', duplicates)
    if set(seen) != set(ids):
        return _rejected(n, received, {}, 'the reply does not cover exactly the expected jobs', duplicates)
    return Parsed(n, {key: result for key, (_, result) in seen.items()}, received, (), None, duplicates)


@dataclass(frozen=True)
class Regrouped:
    """outcomes maps inbox job ID -> (status, text); status is ok, failed or retry.

    values maps the ID of every ok job to the compact JSON of its accepted native value
    (single slot: the value; several slots: {"results":[...]}), which is what dependents receive.
    """
    outcomes: dict
    parsed: Parsed
    values: dict = field(default_factory=dict)


def regroup(text: object, job_map, host_slots=(), mode: str = 'jsonl') -> Regrouped:
    """Parse a reply with one slot per job_map entry, then fold all slots into one outcome per inbox job.

    job_map lists (inbox job ID, atom index) per model slot; host_slots lists (inbox job ID, atom index,
    value) for slots the host filled itself. A single-slot job keeps its value. A multi-slot job stores
    {"results":[...]} in atom order. The reply is accepted whole or rejected whole: after a rejection every
    model job is ('retry', reason).
    """
    job_map = tuple(job_map)
    parsed = parse_reply(text, slot_ids(job_map), mode) if job_map else Parsed(0, {}, 0, ())
    groups = {}
    for pid, (mid, atom) in zip(slot_ids(job_map), job_map):
        groups.setdefault(mid, []).append((atom, pid, True))
    for mid, atom, value in host_slots:
        groups.setdefault(mid, []).append((atom, value, False))
    outcomes, values = {}, {}
    for mid, slots in groups.items():
        slots.sort(key=lambda slot: slot[0])
        if any(model and pid not in parsed.accepted for _, pid, model in slots):
            outcomes[mid] = ('retry', RETRY_REASON)
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


def validate_response(value: object, job_map, host_slots=(), mode: str = 'jsonl') -> tuple[Regrouped, dict]:
    """Adapter response {"reply": "<raw text>", "usage":...}; usage comes from provider accounting."""
    if not isinstance(value, dict) or 'reply' not in value or set(value) - {'reply', 'usage'}:
        raise Error('adapter response must be {"reply":...,"usage":...}')
    usage = validate_usage(value.get('usage', {}))
    return regroup(value['reply'], job_map, host_slots, mode), usage


def encode_reply(results: dict, ids=None) -> str:
    """Build jsonl reply text from {packet job ID: result value}, e.g. for test adapters: one line per ID."""
    return '\n'.join(_json([mid, results[mid]]) for mid in (results if ids is None else ids))
