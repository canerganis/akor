"""JSON configuration updates with merge-patch semantics."""


def merge_patch(base, patch):
    def cp(v):
        if isinstance(v, dict):
            return {k: cp(x) for k, x in v.items()}
        if isinstance(v, list):
            return [cp(x) for x in v]
        return v
    if not isinstance(patch, dict):
        return cp(patch)
    result = cp(base) if isinstance(base, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


def apply_revisions(base, revisions):
    def cp(v):
        if isinstance(v, dict):
            return {k: cp(x) for k, x in v.items()}
        if isinstance(v, list):
            return [cp(x) for x in v]
        return v
    if not isinstance(revisions, list):
        raise ValueError('bad')
    seen = set()
    for r in revisions:
        if not isinstance(r, dict) or 'seq' not in r or 'patch' not in r:
            raise ValueError('bad')
        s = r['seq']
        if isinstance(s, bool) or not isinstance(s, int) or s < 1 or s in seen:
            raise ValueError('bad')
        seen.add(s)
    current = cp(base)
    for r in sorted(revisions, key=lambda x: x['seq']):
        current = merge_patch(current, r['patch'])
    return current
