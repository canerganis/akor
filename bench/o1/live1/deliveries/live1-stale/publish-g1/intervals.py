"""Half-open integer intervals [start, end) and free time inside a window."""


def union_intervals(intervals):
    if not isinstance(intervals, list):
        raise ValueError('bad')
    for iv in intervals:
        if not isinstance(iv, list) or len(iv) != 2:
            raise ValueError('bad')
        for v in iv:
            if isinstance(v, bool) or not isinstance(v, int):
                raise ValueError('bad')
        if iv[0] > iv[1]:
            raise ValueError('bad')
    items = sorted([[a[0], a[1]] for a in intervals if a[0] < a[1]])
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
        for v in iv:
            if isinstance(v, bool) or not isinstance(v, int):
                return False
        return iv[0] <= iv[1]
    if not ok(window) or not isinstance(busy, list):
        raise ValueError('bad')
    for iv in busy:
        if not ok(iv):
            raise ValueError('bad')
    ws, we = window
    clipped = []
    for iv in busy:
        a = max(iv[0], ws)
        b = min(iv[1], we)
        if a < b:
            clipped.append([a, b])
    gaps = []
    cursor = ws
    for s, e in union_intervals(clipped):
        if s > cursor:
            gaps.append([cursor, s])
        cursor = max(cursor, e)
    if cursor < we:
        gaps.append([cursor, we])
    return gaps
