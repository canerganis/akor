"""Owner decision 5 (ruling P3): the static Codex headroom bound U0 + 2 x C x m < 80.

U0 is the fresh owner reading (the D5 owner reading check: valid, attributable to the baseline account and bucket, at
most 60 minutes old), C the Codex call allowance under A4.5 not reflected in U0, m the largest per call increase
recorded in the bound P3 manifest. Fakes in temporary directories and the sanitized evidence of
tests/fixtures/p3-headroom (INDEX.json names each source and its sha256) only: no `codex` is spawned, no model call is
made and the real Codex session directory is never read.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from bench.ozmap_rep import config, quota, rulings

from bench.ozmap_rep.tests.test_p3_d5_coverage import ACCOUNT_SHA, NOW, at, attempt, owner, stamp

EVIDENCE = Path(__file__).parent / 'fixtures' / 'p3-headroom'
MANIFEST = config.REPO / config.SIGNED_RULINGS['P3']['annexes']['quota_source_manifest']['path']


def fresh(tmp_path, percent, minutes=-5):
    """An owner reading of the baseline account taken `minutes` from NOW, in a session that started a minute before."""
    return owner(tmp_path / 'sessions', at(minutes - 1), [(at(minutes - 1), [(at(minutes), percent)])])


def hgate(root, remaining, m, **kw):
    return quota.headroom_gate(root, ACCOUNT_SHA, remaining, m, now=kw.pop('now', NOW), **kw)


# --------------------------------------------------------------------------------------------- the bound itself

def test_the_bound_passes_below_80(tmp_path):
    g = hgate(fresh(tmp_path, 20.0), 62, 0.21)
    assert g['ok'] is True, g
    assert g['u0'] == 20.0 and g['remaining_calls'] == 62 and g['m'] == 0.21 and g['factor'] == 2
    assert g['bound'] == pytest.approx(20.0 + 2 * 62 * 0.21)
    assert g['owner_source'] and g['owner_reading_at']


def test_the_bound_fails_at_or_above_80_while_u0_is_below_80(tmp_path):
    # 54 + 2 x 62 x 0.21 = 80.04: U0 alone is far below the stop line, the bound is not
    g = hgate(fresh(tmp_path, 54.0), 62, 0.21)
    assert g['ok'] is False and 'headroom bound' in g['reason'] and g['bound'] >= 80, g
    # exactly 80 also stops (strict inequality)
    g = hgate(fresh(tmp_path, 40.0), 50, 0.4)
    assert g['bound'] == pytest.approx(80.0) and g['ok'] is False


def test_the_bound_tightens_as_the_allowance_is_used(tmp_path):
    root = fresh(tmp_path, 54.0)
    assert hgate(root, 62, 0.21)['ok'] is False
    assert hgate(root, 30, 0.21)['ok'] is True


def test_u0_at_or_above_80_stops_even_with_no_calls_left(tmp_path):
    g = hgate(fresh(tmp_path, 80.0), 0, 0.21)
    assert g['ok'] is False and '>= 80' in g['reason']


@pytest.mark.parametrize('m', [None, 0, 0.0, -0.1, float('nan'), float('inf'), True, '0.21'])
def test_a_missing_or_invalid_m_stops(tmp_path, m):
    g = hgate(fresh(tmp_path, 1.0), 62, m)
    assert g['ok'] is False and 'm (the largest per call increase)' in g['reason'], g


@pytest.mark.parametrize('remaining', [None, -1, True, 3.0])
def test_an_unknown_allowance_stops(tmp_path, remaining):
    g = hgate(fresh(tmp_path, 1.0), remaining, 0.21)
    assert g['ok'] is False and 'allowance' in g['reason'], g


# ------------------------------------------------------------------- the D5 owner reading check stays a gate

def test_a_stale_u0_stops(tmp_path):
    root = fresh(tmp_path, 1.0, minutes=-(config.QUOTA_OWNER_MAX_AGE_MINUTES + 1))
    g = hgate(root, 62, 0.21)
    assert g['ok'] is False and 'stale' in g['reason'], g
    # control: the same reading 59 minutes old passes
    assert hgate(fresh(tmp_path, 1.0, minutes=-59), 62, 0.21)['ok'] is True


def test_no_owner_reading_stops(tmp_path):
    (tmp_path / 'sessions').mkdir()
    g = hgate(tmp_path / 'sessions', 62, 0.21)
    assert g['ok'] is False and 'unreadable' in g['reason']


def test_an_owner_reading_of_another_account_stops(tmp_path):
    root = owner(tmp_path / 'sessions', at(-6), [(at(-6), [(at(-5), 1.0)])], account='acct-other')
    g = hgate(root, 62, 0.21)
    assert g['ok'] is False and 'another account' in g['reason']


def test_a_future_owner_reading_stops(tmp_path):
    g = hgate(fresh(tmp_path, 1.0, minutes=30), 62, 0.21)
    assert g['ok'] is False and 'future' in g['reason']


def test_a_valid_harvested_reading_raises_u0_and_a_malformed_one_stops(tmp_path):
    root = fresh(tmp_path, 10.0)
    good = {'percent': 60.0, 'timestamp': stamp(at(-2)), 'account_sha256': ACCOUNT_SHA, 'limit_id': 'codex',
            'window_minutes': 10080}
    g = hgate(root, 62, 0.21, harvested={'u-a': [good]})
    assert g['u0'] == 60.0 and g['u0_owner'] == 10.0 and g['ok'] is False  # 60 + 26.04 >= 80
    g = hgate(root, 62, 0.21, harvested={'u-a': [dict(good, percent=True)]})
    assert g['ok'] is False and 'malformed' in g['reason']


# ----------------------------------------------------------------- C counts calls the owner reading cannot hold

def test_calls_after_the_owner_reading_stay_in_c(tmp_path):
    root = fresh(tmp_path, 10.0, minutes=-5)  # session started at -6
    before = attempt('a', at(-30), at(-20))
    after = attempt('b', at(-4), at(-2))
    g = hgate(root, None, 0.21, cap=62, charged=2, attempts=[before, after])
    assert g['ok'] is True and g['reflected_calls'] == 1 and g['remaining_allowance'] == 60
    assert g['remaining_calls'] == 61
    assert g['bound'] == pytest.approx(10.0 + 2 * 61 * 0.21)


def test_without_cap_and_charge_the_allowance_is_unknown(tmp_path):
    g = hgate(fresh(tmp_path, 1.0), None, 0.21)
    assert g['ok'] is False and 'allowance' in g['reason']


def test_unreflected_allowance_without_a_floor_is_the_whole_cap():
    a = attempt('a', at(-30), at(-20))
    assert quota.unreflected_allowance(62, 1, [a], None)['remaining_calls'] == 62
    assert quota.unreflected_allowance(62, 1, [a], at(-10))['remaining_calls'] == 61
    # an unsettled attempt (no end) is never reflected; a reflected count never exceeds the charge
    assert quota.unreflected_allowance(62, 0, [a, attempt('b', at(-30), None)], at(-10))['remaining_calls'] == 62


# ---------------------------------------------------------------------------- m from the bound P3 manifest

def test_the_bound_manifest_records_m_and_establishes_p3():
    m, problem = quota.headroom_m()
    assert problem is None and m == 0.21
    doc = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert doc['freshness_and_causal_coverage']['status'] == 'established'
    assert 'owner decision 5' in doc['freshness_and_causal_coverage']['basis']
    bound = doc['headroom_bound']
    assert bound['factor'] == config.QUOTA_HEADROOM_FACTOR == 2 and bound['stop_percent'] == 80
    assert bound['C_at_launch'] == config.EVAL_CAPS['codex']['total']
    assert bound['U0_limit_at_launch'] == pytest.approx(80 - 2 * 62 * 0.21)
    assert bound['sources']['pilot_runs'] and bound['method']['estimate']['m'] == m
    assert not [p for p in rulings.ruling_problems() if 'ruling P3' in p]


def test_m_is_recomputed_from_the_preserved_evidence():
    calls = json.loads((EVIDENCE / 'pilot-calls.json').read_text(encoding='utf-8'))['calls']
    est = quota.estimate_m(sorted(EVIDENCE.glob('owner-*.jsonl')), calls, ACCOUNT_SHA)
    doc = json.loads(MANIFEST.read_text(encoding='utf-8'))
    assert est == doc['headroom_bound']['method']['estimate']
    assert est['calls'] == 35 and {c['route']['model'] for c in calls} == {config.CODEX_MODEL}
    assert est['interval']['lower']['percent'] == 33.0 and est['interval']['upper']['percent'] == 35.0
    assert est['interval']['upper']['session_started_at'] > est['interval']['last_call_latest_end']
    assert est['m'] >= max(est['per_call_upper_bounds'].values())


def test_the_evidence_index_names_every_fixture():
    index = json.loads((EVIDENCE / 'INDEX.json').read_text(encoding='utf-8'))
    names = {r['fixture'] for r in index['owner_rollouts']}
    assert names == {p.name for p in EVIDENCE.glob('owner-*.jsonl')}
    assert all(len(r['source_sha256']) == 64 for r in index['owner_rollouts'])
    for p in EVIDENCE.glob('owner-*.jsonl'):
        for line in p.read_text(encoding='utf-8').splitlines():
            e = json.loads(line)
            assert set(e['payload']) <= {'type', 'rate_limits', 'cli_version', 'originator', 'creator_account_id'}


def test_a_manifest_without_m_stops(tmp_path):
    doc = json.loads(MANIFEST.read_text(encoding='utf-8'))
    del doc['headroom_bound']['m']
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(doc), encoding='utf-8')
    m, problem = quota.headroom_m(path)
    assert m is None and 'records no m' in problem
    path.write_text(json.dumps(dict(doc, headroom_bound=dict(doc['headroom_bound'], m=False))), encoding='utf-8')
    assert quota.headroom_m(path)[0] is None
    path.write_text(json.dumps(dict(doc, headroom_bound=dict(doc['headroom_bound'], m=0.21, factor=1))),
                    encoding='utf-8')
    assert quota.headroom_m(path)[0] is None
    assert quota.headroom_m(tmp_path / 'absent.json')[0] is None


def test_estimate_m_refuses_a_window_reset_or_a_missing_bracket(tmp_path):
    calls = [{'call_id': 'c', 'reserved_at': stamp(at(-60)), 'timeout_s': 60.0, 'usage': None}]
    lower = owner(tmp_path / 'a', at(-120), [(at(-120), [(at(-90), 10.0)])])
    rows = [json.loads(line) for line in next(lower.rglob('*.jsonl')).read_text(encoding='utf-8').splitlines()]
    for r in rows:
        if r['payload'].get('rate_limits'):
            r['payload']['rate_limits']['primary']['resets_at'] = 1000
    first = tmp_path / 'lower.jsonl'
    first.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    for r in rows:
        if r.get('type') == 'session_meta':
            r['timestamp'] = stamp(at(-10))
        elif r['payload'].get('rate_limits'):
            r['timestamp'] = stamp(at(-5))
            r['payload']['rate_limits']['primary'].update(used_percent=12.0, resets_at=1000)
        else:
            r['timestamp'] = stamp(at(-10))
    second = tmp_path / 'upper.jsonl'
    second.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    est = quota.estimate_m([first, second], calls, ACCOUNT_SHA)
    assert est['rise'] == 2.0 and est['m'] == 3.0
    with pytest.raises(ValueError, match='brackets'):
        quota.estimate_m([first], calls, ACCOUNT_SHA)
    text = second.read_text(encoding='utf-8').replace('"resets_at": 1000', '"resets_at": 900000')
    second.write_text(text, encoding='utf-8')
    with pytest.raises(ValueError, match='reset'):
        quota.estimate_m([first, second], calls, ACCOUNT_SHA)
    with pytest.raises(ValueError, match='brackets'):
        quota.estimate_m([first, second], calls, hashlib.sha256(b'other').hexdigest())


def test_the_d5_coverage_is_recorded_for_information_only(tmp_path):
    root = fresh(tmp_path, 10.0, minutes=-5)
    uncovered = attempt('late', at(-4), at(-2))
    g = hgate(root, None, 0.21, cap=62, charged=1, attempts=[uncovered])
    assert g['ok'] is True and g['d5_uncovered_informational'] == ['late']
    assert quota.coverage_gate([uncovered], root, None, ACCOUNT_SHA, NOW)['ok'] is False


# ------------------------------------------------------------------- the live harness: launch and every cell

from bench.ozmap_rep import run  # noqa: E402
from bench.ozmap_rep.tests.test_council_r1 import Live  # noqa: E402


def launched(live):
    return [a['call_id'] for a in run.jsonl(live.run_dir / 'attempts.jsonl') if a.get('outcome') != 'not_launched'
            and a.get('role') != 'probe']


def test_live_launch_is_refused_when_the_bound_fails(tmp_path, monkeypatch):
    """The telemetry cell is the launch: U0 = 60 is below the stop line, 60 + 2 x 62 x 0.21 is not."""
    live = Live(tmp_path, monkeypatch)
    live.touch_sessions(percent=60.0)
    code = run.TelemetryRun(live.opts()).run()
    rows = run.jsonl(live.run_dir / 'evidence' / 'quota-gates.jsonl')
    assert code == config.EXIT_QUOTA and not launched(live)
    assert rows and rows[0]['group'] == 'pre-cell' and rows[0]['u0'] == 60.0 and 'headroom bound' in rows[0]['reason']


def test_live_launch_is_refused_without_m(tmp_path, monkeypatch):
    live = Live(tmp_path, monkeypatch)
    monkeypatch.setattr(run.quota, 'headroom_m', lambda: (None, 'the P3 quota source manifest records no m '
                                                                 '(headroom_bound.m): stop (P3, owner decision 5)'))
    code = live.telemetry()
    rows = run.jsonl(live.run_dir / 'evidence' / 'quota-gates.jsonl')
    assert code == config.EXIT_QUOTA and not launched(live)
    assert 'records no m' in rows[0]['reason']


def test_live_launch_records_u0_and_the_bound(tmp_path, monkeypatch):
    live = Live(tmp_path, monkeypatch)
    assert live.telemetry() == 0
    rows = run.jsonl(live.run_dir / 'evidence' / 'quota-gates.jsonl')
    pre = [r for r in rows if r.get('group') == 'pre-cell']
    groups = [r for r in rows if r.get('group') != 'pre-cell']
    assert pre and pre[0]['ok'] and pre[0]['u0'] == 10.0 and pre[0]['m'] == 0.21
    assert pre[0]['remaining_calls'] == config.EVAL_CAPS['codex']['total']
    assert groups and all(r['ok'] and r['rule'] == 'owner decision 5 static headroom bound' for r in groups)
