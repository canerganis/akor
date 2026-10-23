"""Fixture answers for ticket C: a third valid implementation the zero-token adapter returns."""


def merge_patch(base, patch):
    def dup(v):
        if isinstance(v, dict):
            return dict([(k, dup(x)) for k, x in v.items()])
        if isinstance(v, list):
            return list(map(dup, v))
        return v
    if not isinstance(patch, dict):
        return dup(patch)
    merged = dup(base) if isinstance(base, dict) else {}
    for name, change in patch.items():
        if change is None:
            if name in merged:
                merged.pop(name)
            continue
        merged[name] = merge_patch(merged.get(name), change)
    return merged


def apply_revisions(base, revisions):
    def dup(v):
        if isinstance(v, dict):
            return dict([(k, dup(x)) for k, x in v.items()])
        if isinstance(v, list):
            return list(map(dup, v))
        return v
    numbers = set()
    for rev in revisions:
        n = rev['seq']
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise ValueError('bad sequence')
        if n in numbers:
            raise ValueError('duplicate sequence')
        numbers.add(n)
    state = dup(base)
    if len(revisions) == 0:
        return state
    state = base
    for rev in sorted(revisions, key=lambda item: item['seq']):
        state = merge_patch(state, rev['patch'])
    return state
