"""Half-open integer intervals [start, end) and free time inside a window."""


def union_intervals(intervals):
    """Merge overlapping or touching intervals and drop empty ones."""
    merged = []
    for start, end in intervals:
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def free_slots(busy, window):
    """Return the gaps inside window that no busy interval covers."""
    start, end = window
    gaps = []
    cursor = start
    for b_start, b_end in union_intervals(busy):
        if b_start > cursor:
            gaps.append([cursor, b_start])
        cursor = b_end
    if cursor < end:
        gaps.append([cursor, end])
    return gaps
