"""JSON configuration updates with merge-patch semantics."""


def merge_patch(base, patch):
    def clone(v):
        if isinstance(v, dict):
            return {k: clone(x) for k, x in v.items()}
        if isinstance(v, list):
            return [clone(x) for x in v]
        return v
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
    def clone(v):
        if isinstance(v, dict):
            return {k: clone(x) for k, x in v.items()}
        if isinstance(v, list):
            return [clone(x) for x in v]
        return v
    if not isinstance(revisions, list):
        raise ValueError('invalid')
    seen = set()
    for r in revisions:
        if not isinstance(r, dict) or 'seq' not in r or 'patch' not in r:
            raise ValueError('invalid')
        s = r['seq']
        if isinstance(s, bool) or not isinstance(s, int) or s < 1 or s in seen:
            raise ValueError('invalid')
        seen.add(s)
    current = clone(base)
    for revision in sorted(revisions, key=lambda r: r['seq']):
        current = merge_patch(current, revision['patch'])
    return current
