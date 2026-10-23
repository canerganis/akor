"""Reference 1 for ticket C (evaluator only)."""


def merge_patch(base, patch):
    def clone(value):
        if isinstance(value, dict):
            return {k: clone(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clone(v) for v in value]
        return value
    if not isinstance(patch, dict):
        return clone(patch)
    result = clone(base) if isinstance(base, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


def apply_revisions(base, revisions):
    def clone(value):
        if isinstance(value, dict):
            return {k: clone(v) for k, v in value.items()}
        if isinstance(value, list):
            return [clone(v) for v in value]
        return value
    seen = []
    for revision in revisions:
        seq = revision['seq']
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1 or seq in seen:
            raise ValueError('invalid sequence')
        seen.append(seq)
    if not revisions:
        return clone(base)
    current = base
    for revision in sorted(revisions, key=lambda r: r['seq']):
        current = merge_patch(current, revision['patch'])
    return current
