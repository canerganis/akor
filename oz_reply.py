"""OZ/8 replies, receipts, adapter capabilities and provider usage.

Replies are positional lanes: v[i] answers the i-th delivered job. Receipts
correlate a reply with one call attempt; they are not authentication or proof.
"""
from __future__ import annotations

import uuid

from oz import Error

PROTOCOL = 'oz.adapter/3'
LANGUAGE = 'OZ/8'
USAGE_FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_creation_input_tokens',
                'output_tokens', 'reasoning_output_tokens')
STATUS = {0: 'ok', 1: 'retry', 2: 'failed'}


def new_receipt() -> str:
    return uuid.uuid4().hex[:16]


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
    if not isinstance(value, dict) or set(value) != {'q', 's', 'v'} or value['q'] != receipt:
        raise Error('reply receipt or schema mismatch')
    texts, statuses = value['v'], value['s']
    if not isinstance(texts, list) or len(texts) != len(ids) or not all(_text(t) for t in texts):
        raise Error('reply needs exactly one nonblank result per delivered job')
    if type(statuses) is int:
        statuses = [statuses] * len(ids)
    if (not isinstance(statuses, list) or len(statuses) != len(ids)
            or any(type(s) is not int or s not in STATUS for s in statuses)):
        raise Error('every result requires an explicit valid status')
    return {mid: (STATUS[s], t) for mid, s, t in zip(ids, statuses, texts)}


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


def encode_reply(outcomes: dict, ids, receipt: str) -> dict:
    """Build a valid reply from (status, text) pairs, e.g. for test adapters."""
    codes = {v: k for k, v in STATUS.items()}
    statuses = [codes[outcomes[mid][0]] for mid in ids]
    return {'q': receipt, 's': statuses[0] if len(set(statuses)) == 1 else statuses,
            'v': [outcomes[mid][1] for mid in ids]}
