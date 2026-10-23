"""JSON configuration updates with merge-patch semantics."""


def merge_patch(base, patch):
    def copy_value(value):
        if isinstance(value, list):
            return [copy_value(item) for item in value]
        if isinstance(value, dict):
            return {key: copy_value(item) for key, item in value.items()}
        return value
    if not isinstance(patch, dict):
        return copy_value(patch)
    if isinstance(base, dict):
        result = copy_value(base)
    else:
        result = {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


def apply_revisions(base, revisions):
    def copy_value(value):
        if isinstance(value, list):
            return [copy_value(item) for item in value]
        if isinstance(value, dict):
            return {key: copy_value(item) for key, item in value.items()}
        return value
    if not isinstance(revisions, list):
        raise ValueError('invalid revisions')
    seqs = []
    for revision in revisions:
        if not isinstance(revision, dict) or 'seq' not in revision or 'patch' not in revision:
            raise ValueError('invalid revision')
        seq = revision['seq']
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
            raise ValueError('invalid seq')
        seqs.append(seq)
    if len(set(seqs)) != len(seqs):
        raise ValueError('duplicate seq')
    current = base
    for revision in sorted(revisions, key=lambda r: r['seq']):
        current = merge_patch(current, revision['patch'])
    return copy_value(current)
