"""D5 and the P3 freshness rule (implementer, 2026-10-25): the strict causal coverage predicate of quota.coverage_gate.

An observation covers a completed live Codex attempt only when the session that produced it started after the attempt
ended (Opus B, rulings/signoff-opus-2.md, D5 points 1 to 3; Astra A: do not assume a response generated reading
occurs after local attempt completion, and one concurrent worker's reading does not cover its siblings). The latest
owner reading stays mandatory and at most 60 minutes old. Fakes in temporary directories and sanitized real owner
rollouts (tests/fixtures/p3-rollouts, INDEX.json names each source and its sha256) only: no `codex` is spawned, no
model call is made and the real Codex session directory is never read.
"""
import datetime as dt
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from bench.ozmap_rep import config, quota

NOW = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.timezone.utc)
ACCOUNT = 'acct-fixture-baseline'
ACCOUNT_SHA = hashlib.sha256(ACCOUNT.encode()).hexdigest()
FIXTURES = Path(__file__).parent / 'fixtures' / 'p3-rollouts'


def at(minutes):
    return NOW + dt.timedelta(minutes=minutes)


def stamp(t):
    return t.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def rollout(path, session_at, turns, account=ACCOUNT, meta_stamp=True):
    """One rollout: session_meta at session_at, then for each turn (start, [(reading time, percent)]) a task_started
    event (unless start is None) and its token_count readings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {'type': 'session_meta', 'payload': {'cli_version': '0.160.0', 'originator': 'codex_exec'}}
    if account:
        meta['payload']['creator_account_id'] = account
    if meta_stamp:
        meta['timestamp'] = stamp(session_at)
    rows = [meta]
    for start, reads in turns:
        if start is not None:
            rows.append({'timestamp': stamp(start), 'type': 'event_msg', 'payload': {'type': 'task_started'}})
        for when, percent in reads:
            rows.append({'timestamp': stamp(when), 'type': 'event_msg', 'payload': {
                'type': 'token_count',
                'rate_limits': {'limit_id': 'codex', 'primary': {'used_percent': percent, 'window_minutes': 10080}}}})
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    return path


def owner(root, session_at, turns, **kw):
    rollout(root / '2026' / '10' / '25' / 'rollout-owner.jsonl', session_at, turns, **kw)
    return root


def attempt(call_id, start, end, **kw):
    return dict({'call_id': call_id, 'attempt_uid': 'u-' + call_id, 'backend': 'codex', 'mode': 'live',
                 'outcome': 'ok', 'started_at': stamp(start), 'ended_at': stamp(end) if end else None}, **kw)


def worker(tmp_path, call_id, session_at, reads):
    """The harvest of one worker rollout, as Isolation.finish records it."""
    path = rollout(tmp_path / 'homes' / call_id / 'sessions' / '2026' / '10' / '25' / 'rollout-w.jsonl', session_at,
                   [(session_at, reads)])
    return quota.harvest_rollout(path)


def gate(root, attempts, harvested=None, now=NOW):
    return quota.coverage_gate(attempts, root, harvested, account_sha256=ACCOUNT_SHA, now=now)


# ============================================================================== D5 with fakes

def test_d5_opus_b_repro_an_owner_turn_that_started_before_the_end_never_covers(tmp_path):
    """opusb2_repro.py, owner_turn_started_before_attempt_end_event_after: an owner turn that started 20 minutes
    before the attempt ended, with its token_count event one minute after the end, returned ok at 10%."""
    a = attempt('a', at(-30), at(-10))
    g = gate(owner(tmp_path, at(-30), [(at(-30), [(at(-9), 10.0)])]), [a])
    assert g['ok'] is False and g['uncovered'] == ['a'], g


def test_d5_an_owner_session_that_started_after_the_end_covers(tmp_path):
    a = attempt('a', at(-30), at(-10))
    g = gate(owner(tmp_path, at(-9), [(at(-9), [(at(-8), 10.0)])]), [a])
    assert g['ok'] is True and g['percent'] == 10.0 and g['covered_by'] == {'a': 'owner'}


def test_d5_an_equal_timestamp_does_not_cover(tmp_path):
    a = attempt('a', at(-30), at(-10))
    assert gate(owner(tmp_path, at(-10), [(at(-10), [(at(-8), 10.0)])]), [a])['ok'] is False


def test_d5_a_later_turn_of_a_session_that_started_before_the_end_does_not_cover(tmp_path):
    """A long session may re-emit a snapshot cached from an earlier turn, so the floor is the session start."""
    a = attempt('a', at(-30), at(-10))
    root = owner(tmp_path, at(-40), [(at(-40), [(at(-39), 9.0)]), (at(-5), [(at(-4), 10.0)])])
    assert gate(root, [a])['ok'] is False


def test_d5_a_reading_without_a_turn_start_or_session_timestamp_does_not_cover(tmp_path):
    a = attempt('a', at(-30), at(-10))
    assert gate(owner(tmp_path, at(-9), [(None, [(at(-8), 10.0)])]), [a])['ok'] is False
    assert gate(owner(tmp_path, at(-9), [(at(-9), [(at(-8), 10.0)])], meta_stamp=False), [a])['ok'] is False
    # with no completed attempt the same reading releases the first group (the telemetry group)
    assert gate(tmp_path, [])['ok'] is True


@pytest.mark.parametrize('session_at,turn_at', [(at(-5), at(-6)), (at(-5), at(-3)), (at(20), at(20))])
def test_d5_an_inconsistent_session_or_turn_start_blocks(tmp_path, session_at, turn_at):
    """Session after turn, turn after the reading, or both in the future: the file is not trusted at all."""
    g = gate(owner(tmp_path, session_at, [(turn_at, [(at(-4), 10.0)])]), [])
    assert g['ok'] is False and 'session or turn start' in g['reason'], g


def test_d5_a_worker_reading_never_covers_its_own_attempt(tmp_path):
    a = attempt('a', at(-30), at(-10))
    harvested = {'u-a': worker(tmp_path, 'a', at(-30), [(at(-11), 12.0)])}
    g = gate(owner(tmp_path, at(-50), [(at(-50), [(at(-20), 10.0)])]), [a], harvested)
    assert g['ok'] is False and g['uncovered'] == ['a']


def test_d5_concurrent_siblings_never_cover_each_other(tmp_path):
    """One synchronized group of two slots: each session started before the other attempt ended."""
    a, b = attempt('a', at(-30), at(-10)), attempt('b', at(-30), at(-12))
    harvested = {'u-a': worker(tmp_path, 'a', at(-30), [(at(-11), 12.0)]),
                 'u-b': worker(tmp_path, 'b', at(-30), [(at(-13), 12.0)])}
    g = gate(owner(tmp_path, at(-50), [(at(-50), [(at(-20), 10.0)])]), [a, b], harvested)
    assert g['ok'] is False and sorted(g['uncovered']) == ['a', 'b']


def test_d5_a_later_group_covers_the_earlier_one_but_never_itself(tmp_path):
    """Sequential groups: sessions of group 2 started after group 1 ended cover group 1; group 2 stays uncovered until
    an owner session starts after it. This is the disclosed consequence (Opus B, D5 point 4): without an
    independently authorized owner call after the last group, the next group does not launch."""
    g1 = [attempt('a', at(-40), at(-30)), attempt('b', at(-40), at(-31))]
    g2 = [attempt('c', at(-29), at(-15)), attempt('d', at(-29), at(-16))]
    harvested = {'u-a': worker(tmp_path, 'a', at(-40), [(at(-31), 20.0)]),
                 'u-b': worker(tmp_path, 'b', at(-40), [(at(-32), 20.0)]),
                 'u-c': worker(tmp_path, 'c', at(-29), [(at(-16), 21.0)]),
                 'u-d': worker(tmp_path, 'd', at(-29), [(at(-17), 22.0)])}
    g = gate(owner(tmp_path / 'o1', at(-50), [(at(-50), [(at(-45), 19.0)])]), g1 + g2, harvested)
    assert g['ok'] is False and sorted(g['uncovered']) == ['c', 'd']
    g = gate(owner(tmp_path / 'o2', at(-5), [(at(-5), [(at(-4), 23.0)])]), g1 + g2, harvested)
    assert g['ok'] is True and g['percent'] == 23.0
    assert g['covered_by']['a'] in ('owner', 'rollout of c', 'rollout of d') and g['covered_by']['c'] == 'owner'


def test_d5_the_gate_percent_is_the_maximum_of_every_valid_reading(tmp_path):
    """A harvested reading that covers nothing still raises the gate percent (no reading is discarded)."""
    a = attempt('a', at(-30), at(-10))
    harvested = {'u-a': worker(tmp_path, 'a', at(-30), [(at(-11), 80.0)])}
    g = gate(owner(tmp_path, at(-9), [(at(-9), [(at(-8), 10.0)])]), [a], harvested)
    assert g['ok'] is False and g['percent'] == 80.0 and '>= 80' in g['reason']


def test_d5_an_unsettled_attempt_without_an_end_is_never_covered(tmp_path):
    a = attempt('a', at(-30), None, outcome='unsettled')
    assert gate(owner(tmp_path, at(-1), [(at(-1), [(at(-1), 10.0)])]), [a])['ok'] is False


def test_d5_a_recovered_attempt_uses_its_end_upper_bound(tmp_path):
    a = attempt('a', at(-30), None, outcome='crashed', ended_at_upper=stamp(at(-5)))
    assert gate(owner(tmp_path / 'x', at(-6), [(at(-6), [(at(-4), 10.0)])]), [a])['ok'] is False
    assert gate(owner(tmp_path / 'y', at(-4), [(at(-4), [(at(-3), 10.0)])]), [a])['ok'] is True


def test_d5_the_telemetry_probe_that_failed_authentication_needs_no_cover(tmp_path):
    probe = attempt('p', at(-30), at(-29), role='probe', outcome='auth_failure')
    assert gate(owner(tmp_path, at(-50), [(at(-50), [(at(-20), 10.0)])]), [probe])['ok'] is True


def test_d5_harvest_records_the_session_and_turn_of_the_selected_reading(tmp_path):
    path = rollout(tmp_path / 'r.jsonl', at(-40), [(at(-40), [(at(-39), 9.0)]), (at(-5), [(at(-4), 10.0)])])
    [obs] = quota.harvest_rollout(path)
    assert obs['percent'] == 10.0 and obs['session_started_at'] == stamp(at(-40))
    assert obs['turn_started_at'] == stamp(at(-5)) and obs['timestamp'] == stamp(at(-4))


# ============================================================================== freshness rule

def test_freshness_a_covering_owner_reading_older_than_60_minutes_blocks(tmp_path):
    limit = config.QUOTA_OWNER_MAX_AGE_MINUTES
    assert limit == 60
    a = attempt('a', at(-200), at(-190))
    g = gate(owner(tmp_path / 'x', at(-189), [(at(-189), [(at(-limit - 1), 10.0)])]), [a])
    assert g['ok'] is False and 'stale' in g['reason']
    assert gate(owner(tmp_path / 'y', at(-189), [(at(-189), [(at(-limit + 1), 10.0)])]), [a])['ok'] is True


def test_freshness_fresh_worker_readings_never_replace_the_owner_reading(tmp_path):
    a = attempt('a', at(-30), at(-10))
    harvested = {'u-a': worker(tmp_path, 'a', at(-30), [(at(-11), 12.0)])}
    g = gate(tmp_path / 'none', [a], harvested)
    assert g['ok'] is False and 'no owner reading' in g['reason']


# ============================================================================== preserved real owner rollouts

def real(tmp_path, *names):
    """Copy sanitized real rollouts into a sessions tree, newest last (modification time selects the file only)."""
    root = tmp_path / 'sessions'
    folder = root / '2026' / '10' / '25'
    folder.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names):
        shutil.copy(FIXTURES / name, folder / ('rollout-' + name))
        os.utime(folder / ('rollout-' + name), (1_000_000 + i, 1_000_000 + i))
    return root


def utc(text):
    return dt.datetime.fromisoformat(text.replace('Z', '+00:00'))


def test_real_fixture_index_names_every_source_and_keeps_no_content():
    index = json.loads((FIXTURES / 'INDEX.json').read_text(encoding='utf-8'))
    assert {f['fixture'] for f in index['files']} == {p.name for p in FIXTURES.glob('*.jsonl')}
    for p in FIXTURES.glob('*.jsonl'):
        for line in p.read_text(encoding='utf-8').splitlines():
            e = json.loads(line)
            assert set(e) <= {'timestamp', 'type', 'payload'}
            assert set(e['payload']) <= {'type', 'rate_limits', 'cli_version', 'originator', 'creator_account_id'}
            assert e['payload'].get('creator_account_id') in (None, ACCOUNT, 'acct-fixture-other')


def test_real_exec_rollout_semantics_of_codex_cli_0_160_0():
    """codex exec 0.160.0: session_meta and task_started open the turn, the only reading is the token_count after the
    last response item of the turn, limit codex, window 10080, account present."""
    r = quota.read_file(FIXTURES / 'exec-0322.jsonl')
    assert r['cli_version'] == '0.160.0' and r['account_sha256'] == ACCOUNT_SHA
    assert r['limit_id'] == 'codex' and r['window_minutes'] == 10080 and r['percent'] == 44.0
    assert r['session_started_at'] <= r['turn_started_at'] < r['timestamp']
    assert r['timestamp'] - r['turn_started_at'] > dt.timedelta(minutes=1)


def test_real_an_attempt_ending_inside_an_owner_turn_is_not_covered_by_it(tmp_path):
    """The real exec turn of 03:22:34 to 03:23:58: an attempt that ended at 03:23:00 lies inside it. The event time
    rule of the bound manifest (reading after the end) covered it; D5 does not, and the next real owner session
    (03:58:57) does."""
    a = attempt('a', utc('2026-10-25T03:10:00Z'), utc('2026-10-25T03:23:00Z'))
    g = gate(real(tmp_path / 'one', 'exec-0322.jsonl'), [a], now=utc('2026-10-25T03:24:30Z'))
    assert g['ok'] is False and g['uncovered'] == ['a']
    g = gate(real(tmp_path / 'two', 'exec-0322.jsonl', 'exec-0358.jsonl'), [a], now=utc('2026-10-25T04:00:00Z'))
    assert g['ok'] is True and g['percent'] == 44.0 and g['covered_by'] == {'a': 'owner'}


def test_real_a_long_desktop_session_never_covers_an_attempt_that_ended_during_it(tmp_path):
    """The real desktop session (0.164.0-alpha, 34 readings from 06:01:12 to 06:05:12, 44 then 45)."""
    root = real(tmp_path, 'desktop-0601.jsonl')
    a = attempt('a', utc('2026-10-25T05:50:00Z'), utc('2026-10-25T06:03:00Z'))
    g = gate(root, [a], now=utc('2026-10-25T06:06:00Z'))
    assert g['ok'] is False and g['uncovered'] == ['a']
    early = attempt('e', utc('2026-10-25T05:50:00Z'), utc('2026-10-25T06:00:00Z'))
    assert gate(root, [early], now=utc('2026-10-25T06:06:00Z'))['percent'] == 45.0


def test_real_readings_never_decrease_within_one_reset_window():
    seen = []
    for p in sorted(FIXTURES.glob('*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            e = json.loads(line)
            rl = e['payload'].get('rate_limits')
            if isinstance(rl, dict):
                seen.append((e['timestamp'], rl['primary']['resets_at'], rl['primary']['used_percent']))
    seen.sort()
    by_window = {}
    for _, window, percent in seen:
        assert percent >= by_window.get(window, 0.0)
        by_window[window] = percent
    assert len(by_window) == 2, 'the fixtures span one window reset (resets_at moved, used_percent fell to 0)'


def test_real_freshness_of_the_newest_real_reading(tmp_path):
    root = real(tmp_path, 'exec-0358.jsonl', 'exec-1502.jsonl')
    a = attempt('a', utc('2026-10-25T14:00:00Z'), utc('2026-10-25T15:00:00Z'))
    assert gate(root, [a], now=utc('2026-10-25T16:02:00Z'))['ok'] is True
    g = gate(root, [a], now=utc('2026-10-25T16:03:00Z'))
    assert g['ok'] is False and 'stale' in g['reason']
