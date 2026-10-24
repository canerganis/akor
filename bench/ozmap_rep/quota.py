"""A4.12 operational stops: Codex stops at primary used_percent >= 80, the Claude handoff at 99% weekly usage.

Standard library only. The Codex reading is rate_limits.primary.used_percent of the last rate_limits object in the
newest session file (*/*/*/*.jsonl by modification time). An unreadable reading is a stop, never a pass.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

from . import config


def _find_rate_limits(value, depth=0):
    """The rate_limits objects inside one event, in document order."""
    found = []
    if depth > 8:
        return found
    if isinstance(value, dict):
        for k, v in value.items():
            if k == 'rate_limits' and isinstance(v, dict):
                found.append(v)
            else:
                found += _find_rate_limits(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            found += _find_rate_limits(v, depth + 1)
    return found


def newest_session(sessions_dir):
    files = [p for p in Path(sessions_dir).glob('*/*/*/*.jsonl') if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: (p.stat().st_mtime, str(p)))


def codex_primary_used_percent(sessions_dir):
    path = newest_session(sessions_dir)
    if path is None:
        return None
    percent = None
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        for rl in _find_rate_limits(event):
            primary = rl.get('primary')
            value = primary.get('used_percent') if isinstance(primary, dict) else None
            if type(value) in (int, float) and not isinstance(value, bool):
                percent = float(value)
    return percent


def codex_reading_time(sessions_dir):
    """When the newest session file holding a rate limit reading was last written (aware UTC), or None."""
    path = newest_session(sessions_dir)
    if path is None or codex_primary_used_percent(sessions_dir) is None:
        return None
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def codex_gate(sessions_dir) -> dict:
    percent = codex_primary_used_percent(sessions_dir)
    if percent is not None and not math.isfinite(percent):
        percent = None
    if percent is None:
        return {'ok': False, 'percent': None, 'reason': 'Codex primary used_percent unreadable: stop (A4.12)'}
    if percent >= config.CODEX_STOP_PERCENT:
        return {'ok': False, 'percent': percent,
                'reason': f'Codex primary used_percent {percent:g} >= {config.CODEX_STOP_PERCENT}: stop (A4.12)'}
    return {'ok': True, 'percent': percent, 'reason': None}


def claude_gate(weekly_percent) -> dict:
    try:
        value = None if weekly_percent is None else float(weekly_percent)
    except (TypeError, ValueError):
        value = None
    if value is None or not math.isfinite(value) or value < 0:
        return {'ok': False, 'reason': 'Claude weekly usage unknown or not a finite reading: stop (A4.12 handoff rule '
                                       'needs a reading)'}
    if float(weekly_percent) >= config.CLAUDE_HANDOFF_PERCENT:
        return {'ok': False, 'reason': f'Claude weekly usage {float(weekly_percent):g}% >= '
                                       f'{config.CLAUDE_HANDOFF_PERCENT}%: hand off (A4.12)'}
    return {'ok': True, 'reason': None}
