"""A4.6: classification and bootstrap errors. Standard library only.

R is read from the frozen classification (classification.json, transcribed from the independent expressibility
review) and never derived from learner output. A bootstrap gold error or a matched A disagreement invalidates
efficiency only for an operation in R for which the learner proposed a rule; every other bootstrap error is returned
as a measured error for correctness and overhead. Malformed or missing bootstrap output is a completion failure.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import config

RULE_FIELDS = ('inputs', 'outputs', 'guards', 'domain', 'reasons')


class ClassificationError(Exception):
    pass


def _time(value):
    if isinstance(value, dt.datetime):
        stamp = value
    else:
        try:
            stamp = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except ValueError:
            raise ClassificationError(f'unreadable timestamp {value!r}') from None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def assess(R, proposed, gold_errors, disagreements, status='ok') -> dict:
    R = set(R or ())
    proposed = dict(proposed or {})
    gold_errors = {k: int(v) for k, v in (gold_errors or {}).items() if v}
    disagreements = {k: int(v) for k, v in (disagreements or {}).items() if v}
    invalid = sorted(op for op in set(gold_errors) | set(disagreements)
                     if op in R and op in config.OPERATIONS and proposed.get(op) is True)
    measured = {op: n for op, n in gold_errors.items()}
    completion_failure = status != 'ok'
    return {'efficiency_invalid_ops': invalid,
            'efficiency_valid': not invalid and not completion_failure,
            'completion_failure': completion_failure,
            'measured_errors': measured,
            'measured_disagreements': dict(disagreements),
            'rule_learning_claim_allowed': bool(R)}


def load_R(path=None, first_learner_call=None) -> set:
    path = Path(path or config.CLASSIFICATION_FILE)
    doc = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(doc, dict) or 'classified_at' not in doc or not isinstance(doc.get('operations'), dict):
        raise ClassificationError('classification must be {classified_at, operations}')
    classified = _time(doc['classified_at'])
    if first_learner_call is not None and classified > _time(first_learner_call):
        raise ClassificationError('the classification is later than the first learner call')
    R = set()
    for op, entry in doc['operations'].items():
        if op not in config.OPERATIONS:
            raise ClassificationError(f'{op} is not a materials operation')
        if not isinstance(entry, dict) or type(entry.get('rule_shaped')) is not bool:
            raise ClassificationError(f'{op}: rule_shaped must be a boolean')
        if entry['rule_shaped']:
            missing = [f for f in RULE_FIELDS if not entry.get(f)]
            if missing:
                raise ClassificationError(f'{op}: a rule shaped operation needs {missing}')
            R.add(op)
    return R


def admission_report(R, admitted) -> dict:
    """Admitted operations outside R are classification misses; R itself never changes."""
    R = set(R or ())
    return {'R': sorted(R), 'classification_misses': sorted(set(admitted or ()) - R),
            'admitted_in_R': sorted(set(admitted or ()) & R)}
