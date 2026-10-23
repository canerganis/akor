"""JSON configuration updates with merge-patch semantics."""


def merge_patch(base, patch):
    """Apply patch to base and return the merged configuration."""
    if not isinstance(patch, dict):
        return patch
    result = base if isinstance(base, dict) else {}
    for key, value in patch.items():
        if value is None:
            del result[key]
        elif isinstance(value, dict):
            result[key] = merge_patch(result.get(key), value)
        else:
            result[key] = value
    return result


def apply_revisions(base, revisions):
    """Apply the revision patches in sequence order."""
    current = base
    for revision in sorted(revisions, key=lambda r: str(r['seq'])):
        current = merge_patch(current, revision['patch'])
    return current
