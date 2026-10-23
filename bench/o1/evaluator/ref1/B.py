"""Reference 1 for ticket B (evaluator only)."""


def union_intervals(intervals):
    def valid(item):
        return (isinstance(item, list) and len(item) == 2
                and all(isinstance(v, int) and not isinstance(v, bool) for v in item)
                and item[0] <= item[1])
    for item in intervals:
        if not valid(item):
            raise ValueError('invalid interval')
    pieces = sorted([item[0], item[1]] for item in intervals if item[0] < item[1])
    merged = []
    for start, end in pieces:
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1][1] = end
        else:
            merged.append([start, end])
    return merged


def free_slots(busy, window):
    def valid(item):
        return (isinstance(item, list) and len(item) == 2
                and all(isinstance(v, int) and not isinstance(v, bool) for v in item)
                and item[0] <= item[1])
    if not valid(window):
        raise ValueError('invalid window')
    for item in busy:
        if not valid(item):
            raise ValueError('invalid interval')
    low, high = window
    clipped = []
    for start, end in busy:
        a = max(start, low)
        b = min(end, high)
        if a < b:
            clipped.append([a, b])
    gaps = []
    cursor = low
    for start, end in union_intervals(clipped):
        if start > cursor:
            gaps.append([cursor, start])
        if end > cursor:
            cursor = end
    if cursor < high:
        gaps.append([cursor, high])
    return gaps
