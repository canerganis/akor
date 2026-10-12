"""OZ/9 replies, receipts, adapter capabilities and provider usage.

A reply is {"results":[v0, v1, ...], "errors":{"<index>": reason}}: v_i is the
native JSON result of the i-th delivered job, and a job listed in "errors" failed
with result null. Receipts stay host-side: the adapter request carries one per call
attempt to correlate the reply; they are not authentication or proof.
"""
from __future__ import annotations

import json
import re

from oz import Error

PROTOCOL = 'oz.adapter/3'
LANGUAGE = 'OZ/9'
USAGE_FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_creation_input_tokens',
                'output_tokens', 'reasoning_output_tokens')


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


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def validate_reply(value: object, ids) -> dict:
    """Whole-reply validation; any defect rejects every result.

    A string result is stored as is; any other JSON value as compact JSON text.
    """
    ids = tuple(ids)
    if (not isinstance(value, dict) or 'results' not in value or set(value) - {'results', 'errors'}
            or not isinstance(value['results'], list) or len(value['results']) != len(ids)):
        raise Error('reply must be {"results":[one value per delivered job],"errors":{...}}')
    results, errors = value['results'], value.get('errors', {})
    if 'errors' in value and (not isinstance(errors, dict) or not errors):
        raise Error('errors must be a nonempty object when present')
    for key, reason in errors.items():
        if (not re.fullmatch(r'0|[1-9][0-9]*', key) or int(key) >= len(ids)
                or not _text(reason) or results[int(key)] is not None):
            raise Error('each error needs an in-range index, a null result and a nonblank reason')
    outcomes = {}
    for index, (mid, item) in enumerate(zip(ids, results)):
        if str(index) in errors:
            outcomes[mid] = ('failed', errors[str(index)])
            continue
        try:
            text = item if isinstance(item, str) else _json(item)
            text.encode('utf-8')
        except (ValueError, UnicodeEncodeError) as exc:
            raise Error('result is not encodable JSON') from exc
        if len(text.encode('utf-8')) > 65536:
            raise Error('result exceeds 65536 bytes')
        outcomes[mid] = ('ok', text)
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


def validate_response(value: object, ids) -> tuple[dict, dict]:
    """Adapter response {"reply":..., "usage":...}; usage comes from provider accounting."""
    if not isinstance(value, dict) or 'reply' not in value or set(value) - {'reply', 'usage'}:
        raise Error('adapter response must be {"reply":...,"usage":...}')
    usage = validate_usage(value.get('usage', {}))
    return validate_reply(value['reply'], ids), usage


def encode_reply(outcomes: dict, ids) -> dict:
    """Build a valid reply from (status, text) pairs, e.g. for test adapters."""
    reply = {'results': [outcomes[mid][1] if outcomes[mid][0] == 'ok' else None for mid in ids]}
    errors = {str(i): outcomes[mid][1] for i, mid in enumerate(ids) if outcomes[mid][0] != 'ok'}
    if errors:
        reply['errors'] = errors
    return reply
