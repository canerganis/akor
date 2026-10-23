"""Half-open integer intervals [start, end) and free time inside a window."""


def union_intervals(intervals):
    if not isinstance(intervals, list):
        raise ValueError('invalid')
    for iv in intervals:
        if not isinstance(iv, list) or len(iv) != 2:
            raise ValueError('invalid')
        a = iv[0]
        b = iv[1]
        if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, int) or not isinstance(b, int):
            raise ValueError('invalid')
        if a > b:
            raise ValueError('invalid')
    items = sorted([[iv[0], iv[1]] for iv in intervals if iv[0] < iv[1]])
    merged = []
    for start, end in items:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def free_slots(busy, window):
    def ok(iv):
        return isinstance(iv, list) and len(iv) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in iv) and iv[0] <= iv[1]
    if not ok(window) or not isinstance(busy, list) or not all(ok(iv) for iv in busy):
        raise ValueError('invalid')
    ws, we = window
    clipped = []
    for iv in busy:
        s = max(iv[0], ws)
        e = min(iv[1], we)
        if s < e:
            clipped.append([s, e])
    gaps = []
    cursor = ws
    for s, e in union_intervals(clipped):
        if s > cursor:
            gaps.append([cursor, s])
        cursor = max(cursor, e)
    if cursor < we:
        gaps.append([cursor, we])
    return gaps
