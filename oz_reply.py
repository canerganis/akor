"""OZ/6 reply lanes: ordered exact results with explicit shared statuses.

Receipts correlate a reply with a single request; they are not authentication
or proof of completion. The trusted adapter retains the ordered job identities.
"""
from __future__ import annotations

import re

from oz import Error


def _receipt(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{16}', value):
        raise Error('reply receipt must be 16 lowercase hexadecimal characters')
    return value


def _ids(ids):
    from oz_batch import valid_id
    if (not isinstance(ids, (tuple, list)) or not 1 <= len(ids) <= 64
            or any(not valid_id(mid) for mid in ids) or len(set(ids)) != len(ids)):
        raise Error('reply requires 1..64 unique ordered job IDs')
    return tuple(ids)


def reply_contract(receipt: str) -> str:
    receipt = _receipt(receipt)
    return (
        'OZ/6 reply: only JSON {"q":"' + receipt + '","s":0,"v":["result text",...]}. '
        'Echo q exactly. v has one nonempty exact result per delivered ID, in delivered order; '
        'never omit or reorder results. s explicitly gives the status of ALL results, or is '
        'an equally long status list for mixed outcomes: 0=completed, 1=retryable failure, '
        '2=permanent failure. No missing status implies success. Report only actual outcomes; '
        'preserve uncertainty. This response format overrides frame-generation instructions.'
    )


def validate_lanes(value: object, ids, receipt: str) -> dict:
    """Normalize a negotiated lane response; ordinary reply validation follows."""
    ids, receipt = _ids(ids), _receipt(receipt)
    if (not isinstance(value, dict) or not {'q', 's', 'v'} <= set(value)
            or set(value) - {'q', 's', 'v', 'usage'} or value['q'] != receipt):
        raise Error('reply receipt or lane schema mismatch')
    texts, statuses = value['v'], value['s']
    if not isinstance(texts, list) or len(texts) != len(ids):
        raise Error('reply must contain exactly one result per delivered ID')
    if type(statuses) is int:
        statuses = [statuses] * len(ids)
    if (not isinstance(statuses, list) or len(statuses) != len(ids)
            or any(type(s) is not int or s not in {0, 1, 2} for s in statuses)):
        raise Error('every result requires an explicit valid status')
    normalized = {'results': [[mid, status, text] for mid, status, text in zip(ids, statuses, texts)]}
    if 'usage' in value:
        normalized['usage'] = value['usage']
    # Reuse the established per-result size, content and usage checks. The
    # import is deferred to avoid a module cycle when Worker uses this codec.
    from oz_worker import validate_reply
    validate_reply(normalized, ids)
    return normalized


def encode_lanes(value: object, ids, receipt: str) -> dict:
    """Losslessly convert checked legacy rows, in the trusted request order."""
    from oz_worker import validate_reply
    ids, receipt = _ids(ids), _receipt(receipt)
    outcomes, usage = validate_reply(value, ids)
    statuses = [{'ok': 0, 'retry': 1, 'failed': 2}[outcomes[mid].status] for mid in ids]
    result = {'q': receipt, 's': statuses[0] if len(set(statuses)) == 1 else statuses,
              'v': [outcomes[mid].text for mid in ids]}
    if 'usage' in value:
        result['usage'] = usage
    return result
