"""OZ/9 replies, receipts, adapter capabilities and provider usage.

A reply is [q, r0, r1, ...]: r_i answers the i-th delivered job and is a
string (success) or [1|2, string] (retryable or permanent failure). Receipts
correlate a reply with one call attempt; they are not authentication or proof.
"""
from __future__ import annotations

from oz import Error

PROTOCOL = 'oz.adapter/3'
LANGUAGE = 'OZ/9'
USAGE_FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_creation_input_tokens',
                'output_tokens', 'reasoning_output_tokens')
STATUS = {0: 'ok', 1: 'retry', 2: 'failed'}


def check_capabilities(value: object) -> dict:
    """Fail before claim/call when the adapter cannot speak what will be sent."""
    if (not isinstance(value, dict) or set(value) != {'protocols', 'languages'}
            or any(not isinstance(value[k], list) or any(not isinstance(v, str) for v in value[k]) for k in value)):
        raise Error('adapter capabilities need protocols and languages lists')
    if PROTOCOL not in value['protocols'] or LANGUAGE not in value['languages']:
        raise Error(f'adapter does not support {PROTOCOL} and {LANGUAGE}')
    return value


def _text(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        return len(value.encode('utf-8')) <= 65536
    except UnicodeEncodeError:
        return False


def validate_reply(value: object, ids, receipt: str) -> dict:
    """Whole-reply validation; any defect rejects every result."""
    ids = tuple(ids)
    if not isinstance(value, list) or len(value) != len(ids) + 1 or value[0] != receipt:
        raise Error('reply must be [q, one result per delivered job]')
    outcomes = {}
    for mid, item in zip(ids, value[1:]):
        if _text(item):
            outcomes[mid] = ('ok', item)
        elif (isinstance(item, list) and len(item) == 2 and type(item[0]) is int
                and item[0] in (1, 2) and _text(item[1])):
            outcomes[mid] = (STATUS[item[0]], item[1])
        else:
            raise Error('each result must be a nonblank string or [1|2, nonblank string]')
    return outcomes


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


def validate_response(value: object, ids, receipt: str) -> tuple[dict, dict]:
    """Adapter response {"reply":..., "usage":...}; usage comes from provider accounting."""
    if not isinstance(value, dict) or 'reply' not in value or set(value) - {'reply', 'usage'}:
        raise Error('adapter response must be {"reply":...,"usage":...}')
    usage = validate_usage(value.get('usage', {}))
    return validate_reply(value['reply'], ids, receipt), usage


def encode_reply(outcomes: dict, ids, receipt: str) -> list:
    """Build a valid reply from (status, text) pairs, e.g. for test adapters."""
    codes = {v: k for k, v in STATUS.items()}
    return [receipt, *(outcomes[mid][1] if outcomes[mid][0] == 'ok' else [codes[outcomes[mid][0]], outcomes[mid][1]]
                       for mid in ids)]
