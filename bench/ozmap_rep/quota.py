"""A4.12 operational stops: Codex stops at primary used_percent >= 80, the Claude handoff at 99% weekly usage.

Standard library only. The owner reading is the LAST rate_limits object of the newest session file (*/*/*/*.jsonl,
newest by modification time; the modification time only selects the file and is never freshness evidence). The latest
reading is validated after it is selected: a malformed latest reading blocks and an older valid one is never
substituted (P3, council round 2 item 31). A value must be a finite number in [0, 100] and not a boolean.

Council round 2 (items 31, B8, RT2.5; Astra's P3, signed by Astra A, Opus B confirmation pending): before every
synchronized Codex dispatch group, including telemetry, every previously completed live Codex attempt that could have
consumed the baseline account's quota must be covered by an observation: either the harvested reading of that
attempt's own worker rollout (only present when worker calls persist sessions, which needs P3 countersigned) or an
owner reading of the same account whose EVENT timestamp is later than the attempt's end. The gate takes the highest
percentage among the covering readings and the latest owner reading. An unreadable, malformed, out of range, future
dated or other account reading blocks; nothing is estimated and no model call is made to obtain a reading.

P3 repair (2026-10-25, blockers P3 and OB-P3): every reading the gate uses, owner or harvested, must carry an account
hash equal to the baseline account hash (a missing hash on either side blocks: the reading is not attributable), the
bucket of the source manifest (limit_id `codex`, primary window 10080 minutes) and an event timestamp. The latest owner
reading must exist and satisfy the manifest's freshness rule (event timestamp at most
config.QUOTA_OWNER_MAX_AGE_MINUTES before the gate time), and a harvested reading must not predate the start of the
attempt it covers.

D5 and the freshness rule (implementer, 2026-10-25; Opus B position 2 and 3 of rulings/signoff-opus-2.md, Astra's
"do not assume a response generated reading occurs after local attempt completion"): an observation covers a completed
attempt only when the session that produced it started after the attempt ended. Codex takes rate_limits from the
x-codex-primary-* response headers of a request, so a reading reflects at most what the server had accounted when
that request started. A reading never covers the attempt whose own rollout it came from, and a concurrent sibling is
never covered by another worker of its group, because both sessions started before either ended. The floor is the
session_meta event timestamp of the rollout (not the turn start), so a snapshot cached from an earlier turn of a long
session cannot cover an attempt that ended after the session started; the turn start event (task_started) of the
reading's turn must also exist. The latest owner reading stays mandatory and must be at most
config.QUOTA_OWNER_MAX_AGE_MINUTES old (selection bound).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path

from . import config

FUTURE_SKEW = dt.timedelta(minutes=5)


def _find_rate_limits(value, depth=0):
    """The rate_limits objects inside one event, in document order."""
    found = []
    if depth > 8:
        return found
    if isinstance(value, dict):
        for k, v in value.items():
            if k == 'rate_limits':
                found.append(v)  # a malformed (non object) latest reading is selected, then rejected (Astra r3, 4)
            else:
                found += _find_rate_limits(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            found += _find_rate_limits(v, depth + 1)
    return found


def _parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = dt.datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return stamp


def valid_percent(value):
    """A used_percent value as a float, or None: booleans, non numbers, non finite values and values outside
    [0, 100] are not readings."""
    if isinstance(value, bool) or type(value) not in (int, float):
        return None
    value = float(value)
    if not math.isfinite(value) or value < 0 or value > 100:
        return None
    return value


def _account_from(event):
    payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
    if event.get('type') != 'session_meta' and payload.get('type') != 'session_meta':
        return None
    for key in ('creator_account_id', 'account_id', 'chatgpt_account_id'):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return hashlib.sha256(value.encode('utf-8')).hexdigest()
    return None


def read_file(path) -> dict:
    """The latest rate limit reading of one session file: {percent (None when malformed), timestamp (event time or
    None), reason, account_sha256, cli_version, source}. Lines that are not JSON events are skipped; the LAST
    rate_limits object is the reading, whatever an earlier one said."""
    out = {'percent': None, 'timestamp': None, 'reason': 'no rate limit reading', 'account_sha256': None,
           'cli_version': None, 'source': str(path), 'found': False, 'limit_id': None, 'window_minutes': None,
           'session_started_at': None, 'turn_started_at': None}
    try:
        lines = Path(path).read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        out['reason'] = 'session file unreadable'
        return out
    last = None
    session_started = None  # the event timestamp of the first session_meta event (D5 coverage floor)
    turn_started = None  # the event timestamp of the latest task_started event so far
    for line in lines:
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        payload_type = event.get('payload', {}).get('type') if isinstance(event.get('payload'), dict) else None
        if event.get('type') == 'session_meta' and session_started is None:
            session_started = ('stamp', _parse_time(event.get('timestamp')))
        if event.get('type') == 'event_msg' and payload_type == 'task_started':
            turn_started = _parse_time(event.get('timestamp'))
        account = _account_from(event)
        if account:
            out['account_sha256'] = account
            payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
            if isinstance(payload.get('cli_version'), str):
                out['cli_version'] = payload['cli_version'][:40]
        found = _find_rate_limits(event)
        if found:
            last = (event, found[-1], turn_started)
    out['session_started_at'] = session_started[1] if session_started else None
    if last is None:
        return out
    event, rl, out['turn_started_at'] = last
    out['found'] = True
    primary = rl.get('primary') if isinstance(rl, dict) else None
    value = valid_percent(primary.get('used_percent')) if isinstance(primary, dict) else None
    out['percent'] = value
    out['limit_id'] = rl.get('limit_id') if isinstance(rl, dict) and isinstance(rl.get('limit_id'), str) else None
    window = primary.get('window_minutes') if isinstance(primary, dict) else None
    out['window_minutes'] = window if type(window) is int else None
    out['reason'] = None if value is not None else 'the latest rate limit reading is malformed or out of range'
    out['timestamp'] = _parse_time(event.get('timestamp'))
    return out


def newest_session(sessions_dir):
    files = [p for p in Path(sessions_dir).glob('*/*/*/*.jsonl') if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: (p.stat().st_mtime, str(p)))


def latest_reading(sessions_dir) -> dict:
    path = newest_session(sessions_dir)
    if path is None:
        return {'percent': None, 'timestamp': None, 'reason': 'no session file', 'account_sha256': None,
                'source': None, 'found': False, 'limit_id': None, 'window_minutes': None}
    return read_file(path)


def codex_primary_used_percent(sessions_dir):
    return latest_reading(sessions_dir)['percent']


def codex_reading_time(sessions_dir):
    """The EVENT timestamp of the latest owner reading (aware UTC), or None. Never the file modification time."""
    r = latest_reading(sessions_dir)
    return r['timestamp'] if r['percent'] is not None else None


def codex_gate(sessions_dir) -> dict:
    percent = codex_primary_used_percent(sessions_dir)
    if percent is None:
        return {'ok': False, 'percent': None, 'reason': 'Codex primary used_percent unreadable: stop (A4.12)'}
    if percent >= config.CODEX_STOP_PERCENT:
        return {'ok': False, 'percent': percent,
                'reason': f'Codex primary used_percent {percent:g} >= {config.CODEX_STOP_PERCENT}: stop (A4.12)'}
    return {'ok': True, 'percent': percent, 'reason': None}


def harvest_rollout(path) -> list:
    """P3 harvest of one worker rollout before the worker home is emptied: the last rate limit reading with its event
    timestamp, the account hash and the CLI version only (never prompts, replies or token text)."""
    r = read_file(path)
    if not r['found']:
        return []
    return [{'percent': r['percent'], 'timestamp': _iso(r['timestamp']), 'reason': r['reason'],
             'account_sha256': r['account_sha256'], 'cli_version': r['cli_version'], 'limit_id': r['limit_id'],
             'window_minutes': r['window_minutes'], 'session_started_at': _iso(r['session_started_at']),
             'turn_started_at': _iso(r['turn_started_at']), 'source': Path(path).name}]


def _iso(stamp):
    return stamp.strftime('%Y-%m-%dT%H:%M:%S.%fZ') if stamp else None


def needs_coverage(attempt) -> bool:
    """Whether a live Codex attempt could have consumed the baseline account's quota: every launched call except the
    telemetry probe that carried unaccepted tokens and ended in an authentication failure (it could not authenticate
    as the account) and a call proven not launched."""
    if attempt.get('backend') != 'codex' or attempt.get('mode') != 'live':
        return False
    if attempt.get('outcome') == 'not_launched':
        return False
    if attempt.get('role') == 'probe' and attempt.get('outcome') == 'auth_failure':
        return False
    return True


def attribution_problem(reading, account_sha256):
    """Why a reading is not attributable to the baseline account and its quota bucket (P3 source manifest,
    account_field_mapping and bucket_identity), or None. Both account hashes must be present and equal; limit_id must
    be config.QUOTA_LIMIT_ID and the primary window config.QUOTA_WINDOW_MINUTES."""
    if not account_sha256:
        return 'the baseline account hash is unknown, so no reading is attributable'
    theirs = reading.get('account_sha256')
    if not theirs:
        return 'the reading carries no account hash (not attributable to the baseline account)'
    if theirs != account_sha256:
        return 'the reading belongs to another account'
    if reading.get('limit_id') != config.QUOTA_LIMIT_ID:
        return f'the reading is not of the {config.QUOTA_LIMIT_ID} bucket (limit_id {reading.get("limit_id")!r})'
    window = reading.get('window_minutes')
    if type(window) is not int or window != config.QUOTA_WINDOW_MINUTES:
        return f'the reading is not of the {config.QUOTA_WINDOW_MINUTES} minute primary window (window {window!r})'
    return None


def _floor_problem(reading, now=None):
    """Why a reading cannot cover a completed attempt (D5): 'missing' without a session start or a turn start event
    of its own turn, 'inconsistent' when either lies in the future or after the reading itself, else None."""
    session, turn, stamp = reading.get('session_started_at'), reading.get('turn_started_at'), reading.get('timestamp')
    if session is None or turn is None or stamp is None:
        return 'missing'
    now = now or dt.datetime.now(dt.timezone.utc)
    if session > now + FUTURE_SKEW or turn > now + FUTURE_SKEW or session > turn or turn > stamp:
        return 'inconsistent'
    return None


def coverage_gate(attempts, sessions_dir, harvested=None, account_sha256=None, now=None) -> dict:
    """The P3 gate before a synchronized Codex dispatch group. attempts: every attempt of the experiment so far;
    harvested: {attempt key: [observation]} from worker rollouts. Returns {ok, percent, reason, uncovered}."""
    now = now or dt.datetime.now(dt.timezone.utc)
    harvested = harvested or {}
    owner = latest_reading(sessions_dir)
    # red team round 3 (RT3.3): every gate row names the file the owner reading came from, its account hash and its
    # event timestamp, so the scorer and a reviewer can tell which reading released a group
    base = {'ok': False, 'percent': None, 'reason': None, 'uncovered': [], 'owner_reading_at': None,
            'owner_source': owner.get('source'), 'owner_account_sha256': owner.get('account_sha256'),
            'sessions_dir': str(Path(sessions_dir))}
    readings = []
    if not owner['found']:
        return dict(base, reason='Codex primary used_percent unreadable (no owner reading of the baseline account): '
                                 'stop (A4.12, P3)')
    if owner['percent'] is None:
        return dict(base, reason=f"Codex owner reading invalid ({owner['reason']}): stop (A4.12, P3)")
    if owner['timestamp'] is None:
        return dict(base, reason='Codex owner reading carries no event timestamp: stop (A4.12, P3)')
    if owner['timestamp'] > now + FUTURE_SKEW:
        return dict(base, reason='Codex owner reading has an unexplained future timestamp: stop (A4.12, P3)')
    problem = attribution_problem(owner, account_sha256)
    if problem:
        return dict(base, reason=f'Codex owner reading: {problem}: stop (A4.12, P3)')
    if owner['timestamp'] < now - dt.timedelta(minutes=config.QUOTA_OWNER_MAX_AGE_MINUTES):
        return dict(base, reason=f'Codex owner reading is stale (event timestamp more than '
                                 f'{config.QUOTA_OWNER_MAX_AGE_MINUTES} minutes before the gate, P3 freshness rule): '
                                 f'stop (A4.12, P3)')
    readings.append(owner['percent'])
    base['owner_reading_at'] = owner['timestamp'].strftime('%Y-%m-%dT%H:%M:%SZ')
    # D5: the pool of observations that may cover a completed attempt. Each entry names the attempt whose rollout it
    # came from (None for the owner reading) and its floor: the session start, valid only with a turn start event of
    # the reading's own turn, neither in the future nor after the reading itself.
    pool = []
    problem = _floor_problem(owner, now)
    if problem == 'inconsistent':
        return dict(base, reason='Codex owner reading: its session or turn start is in the future or after the '
                                 'reading: stop (A4.12, P3)')
    if problem is None:
        pool.append({'from': None, 'floor': owner['session_started_at'], 'percent': owner['percent'],
                     'source': 'owner'})
    keys = {}
    for a in attempts:
        keys[a.get('attempt_uid') or a.get('call_id')] = a
    for key, own in sorted(harvested.items(), key=lambda kv: str(kv[0])):
        a = keys.get(key) or {}
        label = a.get('call_id') or key
        for o in [o for o in own or [] if isinstance(o, dict)]:
            stamp = _parse_time(o.get('timestamp'))
            if o.get('percent') is None or valid_percent(o.get('percent')) is None or stamp is None:
                return dict(base, reason=f'{label}: its harvested quota reading is malformed: stop (P3)')
            if stamp > now + FUTURE_SKEW:
                return dict(base, reason=f'{label}: its harvested reading has an unexplained future timestamp: '
                                         f'stop (P3)')
            problem = attribution_problem(o, account_sha256)
            if problem:
                return dict(base, reason=f'{label}: harvested reading: {problem}: stop (P3)')
            started = _parse_time(a.get('started_at'))
            if started is not None and stamp < started - FUTURE_SKEW:
                return dict(base, reason=f'{label}: its harvested reading predates the attempt it came from: '
                                         f'stop (P3)')
            # every valid harvested reading raises the gate percent, whether or not it covers anything
            readings.append(float(o['percent']))
            entry = {'timestamp': stamp, 'session_started_at': _parse_time(o.get('session_started_at')),
                     'turn_started_at': _parse_time(o.get('turn_started_at'))}
            problem = _floor_problem(entry, now)
            if problem == 'inconsistent':
                return dict(base, reason=f'{label}: its harvested reading has a session or turn start in the future '
                                         f'or after the reading: stop (P3)')
            if problem is None:
                pool.append({'from': key, 'floor': entry['session_started_at'], 'percent': float(o['percent']),
                             'source': f'rollout of {label}'})
    uncovered, covered_by = [], {}
    for a in attempts:
        if not needs_coverage(a):
            continue
        key = a.get('attempt_uid') or a.get('call_id')
        end = _parse_time(a.get('ended_at')) or _parse_time(a.get('ended_at_upper'))
        cover = None
        if end is not None:
            # strict: the covering session started after the attempt ended; a reading never covers its own attempt
            later = [o for o in pool if o['from'] != key and o['floor'] > end]
            cover = max(later, key=lambda o: o['floor']) if later else None
        if cover is None:
            uncovered.append(a.get('call_id'))
            continue
        readings.append(cover['percent'])
        covered_by[a.get('call_id')] = cover['source']
    base['covered_by'] = dict(list(covered_by.items())[:50])
    if uncovered:
        return dict(base, uncovered=uncovered[:20],
                    reason=f'no quota observation covers the completed live Codex calls {uncovered[:5]} (A4.12, P3, '
                           f'D5: a reading of the same account from a session that started after the call ended is '
                           f'needed; a reading from the own rollout of the call or from a concurrent sibling never covers '
                           f'it, and file modification times never count)')
    if not readings:
        return dict(base, reason='Codex primary used_percent unreadable: stop (A4.12)')
    percent = max(readings)
    if percent >= config.CODEX_STOP_PERCENT:
        return dict(base, percent=percent,
                    reason=f'Codex primary used_percent {percent:g} >= {config.CODEX_STOP_PERCENT}: stop (A4.12)')
    return dict(base, ok=True, percent=percent)


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
