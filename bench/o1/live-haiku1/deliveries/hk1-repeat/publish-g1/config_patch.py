"""JSON configuration updates with merge-patch semantics."""


def merge_patch(base, patch):
    def clone(value):
        if isinstance(value, dict):
            result = {}
            for key in value.keys():
                result[key] = clone(value[key])
            return result
        if isinstance(value, list):
            items = []
            for item in value:
                items.append(clone(item))
            return items
        return value
    if not isinstance(patch, dict):
        return clone(patch)
    if isinstance(base, dict):
        result = clone(base)
    else:
        result = {}
    for key in patch.keys():
        value = patch[key]
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


def apply_revisions(base, revisions):
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
    def clone(value):
        if isinstance(value, dict):
            result = {}
            for key in value.keys():
                result[key] = clone(value[key])
            return result
        if isinstance(value, list):
            items = []
            for item in value:
                items.append(clone(item))
            return items
        return value
    if not revisions:
        return clone(base)
    current = base
    for revision in sorted(revisions, key=lambda r: r['seq']):
        current = merge_patch(current, revision['patch'])
    return current
