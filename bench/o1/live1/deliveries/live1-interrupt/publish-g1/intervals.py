"""Half-open integer intervals [start, end) and free time inside a window."""


def union_intervals(intervals):
    if not isinstance(intervals, list):
        raise ValueError('bad intervals')
    for iv in intervals:
        if not isinstance(iv, list) or len(iv) != 2:
            raise ValueError('bad interval')
        for x in iv:
            if isinstance(x, bool) or not isinstance(x, int):
                raise ValueError('bad endpoint')
        if iv[0] > iv[1]:
            raise ValueError('bad order')
    items = sorted([[iv[0], iv[1]] for iv in intervals if iv[0] < iv[1]])
    merged = []
    for s, e in items:
        if merged and s <= merged[-1][1]:
            if e > merged[-1][1]:
                merged[-1][1] = e
        else:
            merged.append([s, e])
    return merged


def free_slots(busy, window):
    def ok(iv):
        if not isinstance(iv, list) or len(iv) != 2:
            return False
        for x in iv:
            if isinstance(x, bool) or not isinstance(x, int):
                return False
        return iv[0] <= iv[1]
    if not ok(window) or not isinstance(busy, list):
        raise ValueError('bad input')
    for iv in busy:
        if not ok(iv):
            raise ValueError('bad input')
    ws, we = window
    clipped = []
    for iv in busy:
        s = max(iv[0], ws)
        e = min(iv[1], we)
        if s < e:
            clipped.append([s, e])
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
