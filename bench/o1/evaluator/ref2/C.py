"""Reference 2 for ticket C (evaluator only), written apart from reference 1."""


def merge_patch(base, patch):
    def copy_json(value):
        if isinstance(value, list):
            return [copy_json(item) for item in value]
        if isinstance(value, dict):
            out = {}
            for key in value:
                out[key] = copy_json(value[key])
            return out
        return value
    if isinstance(patch, dict):
        target = copy_json(base) if isinstance(base, dict) else {}
        for key in patch:
            change = patch[key]
            if change is None:
                if key in target:
                    del target[key]
            elif isinstance(change, dict):
                target[key] = merge_patch(target[key] if key in target else None, change)
            else:
                target[key] = copy_json(change)
        return target
    return copy_json(patch)


def apply_revisions(base, revisions):
    def copy_json(value):
        if isinstance(value, list):
            return [copy_json(item) for item in value]
        if isinstance(value, dict):
            out = {}
            for key in value:
                out[key] = copy_json(value[key])
            return out
        return value
    order = {}
    for revision in revisions:
        seq = revision['seq']
        if isinstance(seq, bool) or not isinstance(seq, int) or seq <= 0:
            raise ValueError('sequence must be a positive integer')
        if seq in order:
            raise ValueError('duplicate sequence')
        order[seq] = revision['patch']
    if len(order) == 0:
        return copy_json(base)
    current = base
    for seq in sorted(order):
        current = merge_patch(current, order[seq])
    return current
