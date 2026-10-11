"""OZ/7 replies, receipts, adapter capabilities and provider usage (see OZ7.md).

Receipts correlate a reply with one call attempt; they are not authentication
or proof of completion. The trusted host keeps the ordered job identities.
"""
from __future__ import annotations

import uuid

from oz import Error

PROTOCOL = 'oz.adapter/3'
LANES_FROM = 16
USAGE_FIELDS = ('input_tokens', 'cached_input_tokens', 'cache_creation_input_tokens',
                'output_tokens', 'reasoning_output_tokens')
STATUS = {0: 'ok', 1: 'retry', 2: 'failed'}


def new_receipt() -> str:
    return uuid.uuid4().hex[:16]


def resolve_reply_mode(mode: str, count: int) -> str:
    """auto is host policy on the final packed job count, never negotiated."""
    if mode not in ('rows', 'lanes', 'auto'):
        raise Error('reply_mode must be rows, lanes or auto')
    if mode != 'auto':
        return mode
    return 'lanes' if count >= LANES_FROM else 'rows'


def check_capabilities(value: object, reply_mode: str) -> dict:
    """Fail before claim/call when the adapter cannot speak what may be sent."""
    if (not isinstance(value, dict) or set(value) != {'protocols', 'languages', 'reply_modes'}
            or any(not isinstance(value[k], list) or any(not isinstance(v, str) for v in value[k]) for k in value)):
        raise Error('adapter capabilities need protocols, languages and reply_modes lists')
    needed = {'rows', 'lanes'} if reply_mode == 'auto' else {resolve_reply_mode(reply_mode, 1)}
    if PROTOCOL not in value['protocols'] or 'OZ/7' not in value['languages'] or not needed <= set(value['reply_modes']):
        raise Error(f'adapter does not support {PROTOCOL}, OZ/7 and reply mode(s) ' + ','.join(sorted(needed)))
    return value


def _text(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        return len(value.encode('utf-8')) <= 65536
    except UnicodeEncodeError:
        return False


def validate_reply(value: object, ids, receipt: str, reply_mode: str) -> dict:
    """Whole-reply validation; any defect rejects every result."""
    ids = tuple(ids)
    if reply_mode == 'rows':
        if not isinstance(value, dict) or set(value) != {'q', 'results'} or value['q'] != receipt:
            raise Error('reply receipt or rows schema mismatch')
        if not isinstance(value['results'], list):
            raise Error('rows reply needs a results list')
        outcomes = {}
        for row in value['results']:
            if (not isinstance(row, list) or len(row) != 3 or not isinstance(row[0], str)
                    or row[0] not in ids or row[0] in outcomes or type(row[1]) is not int
                    or row[1] not in STATUS or not _text(row[2])):
                raise Error('invalid, duplicated or unexpected result row')
            outcomes[row[0]] = (STATUS[row[1]], row[2])
        if set(outcomes) != set(ids):
            raise Error('reply is missing delivered IDs')
        return outcomes
    if reply_mode != 'lanes':
        raise Error('validation needs a resolved reply mode')
    if not isinstance(value, dict) or set(value) != {'q', 's', 'v'} or value['q'] != receipt:
        raise Error('reply receipt or lanes schema mismatch')
    texts, statuses = value['v'], value['s']
    if not isinstance(texts, list) or len(texts) != len(ids) or not all(_text(t) for t in texts):
        raise Error('lanes need exactly one nonblank result per delivered ID')
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


def validate_response(value: object, ids, receipt: str, reply_mode: str) -> tuple[dict, dict]:
    """Adapter response {"reply":..., "usage":...}; usage comes from provider accounting."""
    if not isinstance(value, dict) or 'reply' not in value or set(value) - {'reply', 'usage'}:
        raise Error('adapter response must be {"reply":...,"usage":...}')
    usage = validate_usage(value.get('usage', {}))
    return validate_reply(value['reply'], ids, receipt, reply_mode), usage


def encode_reply(outcomes: dict, ids, receipt: str, reply_mode: str) -> dict:
    """Build a valid model reply from (status, text) pairs, e.g. for test adapters."""
    codes = {v: k for k, v in STATUS.items()}
    if reply_mode == 'rows':
        return {'q': receipt, 'results': [[mid, codes[outcomes[mid][0]], outcomes[mid][1]] for mid in ids]}
    statuses = [codes[outcomes[mid][0]] for mid in ids]
    return {'q': receipt, 's': statuses[0] if len(set(statuses)) == 1 else statuses,
            'v': [outcomes[mid][1] for mid in ids]}
