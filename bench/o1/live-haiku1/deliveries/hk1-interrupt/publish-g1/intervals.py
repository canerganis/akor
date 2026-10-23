"""Half-open integer intervals [start, end) and free time inside a window."""


def union_intervals(intervals):
    pairs = []
    for item in intervals:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError('invalid interval')
        start, end = item
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or start > end:
            raise ValueError('invalid interval')
        pairs.append([start, end])
    pairs = sorted(pairs)
    merged = []
    for start, end in pairs:
        if start == end:
            continue
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    return merged


def free_slots(busy, window):
    def check(item):
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError('invalid interval')
        start, end = item
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or start > end:
            raise ValueError('invalid interval')
        return start, end
    ws, we = check(window)
    if not isinstance(busy, list):
        raise ValueError('invalid busy')
    clipped = []
    for item in busy:
        b_start, b_end = check(item)
        lo = max(b_start, ws)
        hi = min(b_end, we)
        if lo < hi:
            clipped.append([lo, hi])
    merged = union_intervals(clipped)
    gaps = []
    cursor = ws
    for m_start, m_end in merged:
        if m_start > cursor:
            gaps.append([cursor, m_start])
        if m_end > cursor:
            cursor = m_end
    if cursor < we:
        gaps.append([cursor, we])
    return gaps
