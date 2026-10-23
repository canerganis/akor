"""Utilities for closed integer ranges in job manifests.

Each range is a two-item list [start, end], with start <= end.
Endpoints and offsets are integers, excluding booleans. Other endpoint
types are outside the contract. Results never alias input range lists.
"""


def _validated(ranges: list[list[int]]) -> list[list[int]]:
    result: list[list[int]] = []
    for pair in ranges:
        if len(pair) != 2:
            raise ValueError("each range needs two endpoints")
        start, end = pair
        if start > end:
            raise ValueError("range endpoints are reversed")
        result.append([start, end])
    return result


def compact_ranges(ranges: list[list[int]]) -> list[list[int]]:
    """Sort and merge overlapping or adjacent closed integer ranges."""
    ordered = sorted(_validated(ranges))
    merged: list[list[int]] = []
    for start, end in ordered:
        if not merged:
            merged.append([start, end])
            continue
        previous = merged[-1]
        if start <= previous[1]:
            previous[1] = max(previous[1], end)
        else:
            merged.append([start, end])
    return merged


def covered_count(ranges: list[list[int]]) -> int:
    """Count distinct integers covered by the input ranges."""
    total = 0
    for start, end in compact_ranges(ranges):
        width = end - start + 1
        total += width
    return total


def contains(ranges: list[list[int]], value: int) -> bool:
    """Test membership after validating every supplied range."""
    checked = _validated(ranges)
    return any(start <= value <= end for start, end in checked)


def shift_ranges(ranges: list[list[int]], offset: int) -> list[list[int]]:
    """Translate endpoints, preserving the original range order."""
    checked = _validated(ranges)
    shifted = []
    for start, end in checked:
        shifted.append([start + offset, end + offset])
    return shifted


def bounding_range(ranges: list[list[int]]) -> list[int] | None:
    """Return the smallest enclosing range, or None for no ranges."""
    checked = _validated(ranges)
    if not checked:
        return None
    return [min(pair[0] for pair in checked), max(pair[1] for pair in checked)]
