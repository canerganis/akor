"""Fixture answers for ticket B: a third valid implementation the zero-token adapter returns."""


def union_intervals(intervals):
    spans = []
    for item in intervals:
        ok = isinstance(item, list) and len(item) == 2
        if ok:
            for v in item:
                if isinstance(v, bool) or not isinstance(v, int):
                    ok = False
        if not ok or item[0] > item[1]:
            raise ValueError('invalid interval')
        if item[0] != item[1]:
            spans.append([item[0], item[1]])
    spans.sort()
    out = []
    for span in spans:
        if out and span[0] <= out[-1][1]:
            out[-1][1] = max(out[-1][1], span[1])
        else:
            out.append(span)
    return out


def free_slots(busy, window):
    for item in [window] + list(busy):
        ok = isinstance(item, list) and len(item) == 2
        if ok:
            for v in item:
                if isinstance(v, bool) or not isinstance(v, int):
                    ok = False
        if not ok or item[0] > item[1]:
            raise ValueError('invalid interval')
    first, last = window[0], window[1]
    parts = []
    for item in busy:
        lo = max(item[0], first)
        hi = min(item[1], last)
        if lo < hi:
            parts.append([lo, hi])
    free = []
    at = first
    for lo, hi in union_intervals(parts):
        if lo > at:
            free.append([at, lo])
        at = max(at, hi)
    if at < last:
        free.append([at, last])
    return free
