"""JSON configuration updates with merge-patch semantics."""


def merge_patch(base, patch):
    def copy_value(value):
        if isinstance(value, dict):
            out = {}
            for key in value:
                out[key] = copy_value(value[key])
            return out
        if isinstance(value, list):
            out = []
            for item in value:
                out.append(copy_value(item))
            return out
        return value
    if not isinstance(patch, dict):
        return copy_value(patch)
    if isinstance(base, dict):
        result = copy_value(base)
    else:
        result = {}
    for key in patch:
        value = patch[key]
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


def apply_revisions(base, revisions):
    def copy_value(value):
        if isinstance(value, dict):
            out = {}
            for key in value:
                out[key] = copy_value(value[key])
            return out
        if isinstance(value, list):
            out = []
            for item in value:
                out.append(copy_value(item))
            return out
        return value
    if not isinstance(revisions, list):
        raise ValueError('revisions must be a list')
    seqs = set()
    for revision in revisions:
        if not isinstance(revision, dict) or 'seq' not in revision or 'patch' not in revision:
            raise ValueError('invalid revision')
        seq = revision['seq']
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            raise ValueError('invalid seq')
        if seq in seqs:
            raise ValueError('duplicate seq')
        seqs.add(seq)
    if not revisions:
        return copy_value(base)
    current = base
    for revision in sorted(revisions, key=lambda r: r['seq']):
        current = merge_patch(current, revision['patch'])
    return current
