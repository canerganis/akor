"""Reply judges for the retired wires S1c and S1d, kept only so recorded Codex runs can still be scored.

The product parser (oz_reply.parse_reply) speaks stage 1f only. These two functions reproduce what the
product parser accepted at stage 1c (commit 3ea6989) and stage 1d (commit 8ac429c), so the recorded
results_*.jsonl files score exactly as they did when they were measured. Each returns
(valid, values): valid is False when the reply as a whole counted as invalid, values maps the expected
key (zero-based index for S1c, packet job ID for S1d) to the accepted result value.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from oz import Error  # noqa: E402
from oz_reply import loads, _store, MAX_LINE_BYTES, CAPTURE_SLACK  # noqa: E402

MAX_ERROR_BYTES = 1024
INDEX_TOKEN = re.compile(r'0|[1-9][0-9]*')
FIRST_TOKEN = re.compile(r'\s*\[\s*(-?[0-9][0-9.eE+-]*)')


def _too_long(text, n):
    return len(text.encode('utf-8', 'surrogatepass')) > MAX_LINE_BYTES * n + CAPTURE_SLACK


def judge_s1c(text, n):
    """Stage 1c: JSONL, lines [i,value] or [i,null,"reason"] by zero-based index, per-index acceptance.

    A line that does not start with "[" (fence, prose) rejects the whole reply; any other bad line, and
    every copy of a repeated index, only drops that index. A job failure counts as received, not as a value.
    """
    if _too_long(text, n):
        return False, {}
    items, envelope = [], False
    for number, line in enumerate(text.split('\n'), 1):
        line = line[:-1] if line.endswith('\r') else line
        if not line.strip():
            continue
        if len(line.encode('utf-8', 'surrogatepass')) <= MAX_LINE_BYTES and not line.lstrip().startswith('['):
            envelope = True
        else:
            items.append((number, line))
    bad, valid, seen = set(), {}, {}
    for number, line in items:
        if len(line.encode('utf-8', 'surrogatepass')) > MAX_LINE_BYTES:
            bad.add(number)
            continue
        try:
            row = loads(line)
        except (ValueError, RecursionError, Error):
            bad.add(number)
            continue
        match = FIRST_TOKEN.match(line)
        if not row or type(row[0]) is not int or not (match and INDEX_TOKEN.fullmatch(match.group(1))):
            bad.add(number)
            continue
        if row[0] >= n:
            bad.add(number)
            continue
        seen.setdefault(row[0], []).append(number)
        if len(row) not in (2, 3):
            bad.add(number)
        elif len(row) == 3 and (row[1] is not None or not isinstance(row[2], str) or not row[2].strip()):
            bad.add(number)
        else:
            try:
                if len(row) == 3 and len(row[2].encode('utf-8')) > MAX_ERROR_BYTES:
                    raise ValueError
                _store(row[1] if len(row) == 2 else row[2])
            except (ValueError, UnicodeEncodeError):
                bad.add(number)
            else:
                valid[number] = row
    accepted = {}
    for index, numbers in seen.items():
        if len(numbers) == 1 and numbers[0] in valid:
            row = valid[numbers[0]]
            accepted[index] = ('ok', row[1]) if len(row) == 2 else ('failed', row[2])
    if envelope or not accepted:
        return False, {}
    return True, {i: v for i, (status, v) in accepted.items() if status == 'ok'}


def judge_s1d(text, ids):
    """Stage 1d: JSONL, lines [id,value] by packet job ID, atomic acceptance.

    Blank lines are ignored, ASCII space/tab/CR stripped at both ends, byte-identical repeats count once, a
    conflicting repeat, an unknown ID, a malformed line, more than 2N lines or an ID set that is not exactly
    the expected set rejects everything.
    """
    ids = tuple(ids)
    n = len(ids)
    if _too_long(text, n):
        return False, {}
    lines = [raw.strip(' \t\r') for raw in text.split('\n')]
    lines = [line for line in lines if line]
    if not lines or len(lines) > 2 * n:
        return False, {}
    seen = {}
    for line in lines:
        if len(line.encode('utf-8', 'surrogatepass')) > MAX_LINE_BYTES:
            return False, {}
        try:
            row = loads(line)
        except (ValueError, RecursionError, Error):
            return False, {}
        if not isinstance(row, list) or len(row) != 2 or not isinstance(row[0], str) or row[0] not in ids:
            return False, {}
        try:
            _store(row[1])
        except (ValueError, UnicodeEncodeError):
            return False, {}
        if seen.setdefault(row[0], (line, row[1]))[0] != line:
            return False, {}
    if set(seen) != set(ids):
        return False, {}
    return True, {k: v for k, (_, v) in seen.items()}
