"""Half-open integer intervals [start, end) and free time inside a window."""


def union_intervals(intervals):
    if not isinstance(intervals, list):
        raise ValueError('intervals must be a list')
    checked = []
    for item in intervals:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError('invalid interval')
        start = item[0]
        end = item[1]
        if isinstance(start, bool) or isinstance(end, bool):
            raise ValueError('invalid interval')
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError('invalid interval')
        if start > end:
            raise ValueError('invalid interval')
        if start < end:
            checked.append([start, end])
    checked = sorted(checked)
    merged = []
    for start, end in checked:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    return merged


def free_slots(busy, window):
    if not isinstance(window, list) or len(window) != 2:
        raise ValueError('invalid window')
    ws = window[0]
    we = window[1]
    if isinstance(ws, bool) or isinstance(we, bool) or not isinstance(ws, int) or not isinstance(we, int) or ws > we:
        raise ValueError('invalid window')
    if not isinstance(busy, list):
        raise ValueError('invalid busy')
    clipped = []
    for item in busy:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError('invalid interval')
        start = item[0]
        end = item[1]
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int) or start > end:
            raise ValueError('invalid interval')
        lo = max(start, ws)
        hi = min(end, we)
        if lo < hi:
            clipped.append([lo, hi])
    merged = union_intervals(clipped)
    gaps = []
    cursor = ws
    for b_start, b_end in merged:
        if b_start > cursor:
            gaps.append([cursor, b_start])
        cursor = b_end
    if cursor < we:
        gaps.append([cursor, we])
    return gaps
