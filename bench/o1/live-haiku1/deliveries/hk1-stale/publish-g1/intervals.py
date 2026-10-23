"""Half-open integer intervals [start, end) and free time inside a window."""


def union_intervals(intervals):
    if not isinstance(intervals, list):
        raise ValueError('intervals must be a list')
    for item in intervals:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError('invalid interval')
        start, end = item
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int) or start > end:
            raise ValueError('invalid interval')
    pairs = []
    for item in intervals:
        if item[0] < item[1]:
            pairs.append([item[0], item[1]])
    pairs.sort()
    merged = []
    for start, end in pairs:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    return merged


def free_slots(busy, window):
    if not isinstance(window, list) or len(window) != 2:
        raise ValueError('invalid window')
    ws, we = window
    if isinstance(ws, bool) or isinstance(we, bool) or not isinstance(ws, int) or not isinstance(we, int) or ws > we:
        raise ValueError('invalid window')
    if not isinstance(busy, list):
        raise ValueError('invalid busy')
    for item in busy:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError('invalid interval')
        s, e = item
        if isinstance(s, bool) or isinstance(e, bool) or not isinstance(s, int) or not isinstance(e, int) or s > e:
            raise ValueError('invalid interval')
    clipped = []
    for item in busy:
        lo = max(item[0], ws)
        hi = min(item[1], we)
        if lo < hi:
            clipped.append([lo, hi])
    merged = union_intervals(clipped)
    gaps = []
    cursor = ws
    for s, e in merged:
        if s > cursor:
            gaps.append([cursor, s])
        cursor = max(cursor, e)
    if cursor < we:
        gaps.append([cursor, we])
    return gaps
