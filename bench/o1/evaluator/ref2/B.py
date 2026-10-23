"""Reference 2 for ticket B (evaluator only), written apart from reference 1."""


def union_intervals(intervals):
    checked = []
    for item in intervals:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError('interval must be [start, end]')
        start = item[0]
        end = item[1]
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
            raise ValueError('endpoints must be integers')
        if start > end:
            raise ValueError('reversed interval')
        if start < end:
            checked.append((start, end))
    checked.sort()
    result = []
    for start, end in checked:
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def free_slots(busy, window):
    def bad(item):
        return (not isinstance(item, list) or len(item) != 2
                or any(isinstance(v, bool) or not isinstance(v, int) for v in item) or item[0] > item[1])
    if bad(window):
        raise ValueError('invalid window')
    for item in busy:
        if bad(item):
            raise ValueError('invalid interval')
    lo = window[0]
    hi = window[1]
    inside = [[max(s, lo), min(e, hi)] for s, e in busy if max(s, lo) < min(e, hi)]
    covered = union_intervals(inside)
    out = []
    edges = [lo] + [p for pair in covered for p in pair] + [hi]
    for k in range(0, len(edges), 2):
        if edges[k] < edges[k + 1]:
            out.append([edges[k], edges[k + 1]])
    return out
