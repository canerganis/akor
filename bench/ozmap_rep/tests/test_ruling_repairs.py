"""Regression tests for the ruling repairs of 2026-10-25 (blockers P3, OB-P3, OB-P5 and OB-D1 of the ruling sign-off,
docs/design/ozmap-replication-2026-10-24/rulings/signoff-astra.md and signoff-opus.md; owner decision 4). One test per
case named in the blockers. Temporary directories only: no real `codex` is spawned, no real baseline or Codex session
directory is touched, and the sealed reviewer ASTs are never read.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from bench.ozmap_rep import config, isolation, quota, rulings
from bench.ozmap_rep.tests.test_council_r1 import settled_annex

NOW = dt.datetime.now(dt.timezone.utc)
ACCOUNT = 'acct-baseline'
ACCOUNT_SHA = hashlib.sha256(ACCOUNT.encode()).hexdigest()
OTHER_SHA = hashlib.sha256(b'acct-other').hexdigest()


def stamp(t):
    return t.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def owner_session(root, percent=10.0, at=NOW, account=ACCOUNT, limit_id='codex', window=10080, timestamp=True):
    """One owner rollout: a session_meta naming the account (or none) and one token_count reading."""
    folder = root / '2026' / '10' / '25'
    folder.mkdir(parents=True, exist_ok=True)
    meta = {'type': 'session_meta', 'payload': {'cli_version': '0.160.0'}}
    if account is not None:
        meta['payload']['creator_account_id'] = account
    rl = {'primary': {'used_percent': percent}}
    if limit_id is not None:
        rl['limit_id'] = limit_id
    if window is not None:
        rl['primary']['window_minutes'] = window
    event = {'type': 'event_msg', 'payload': {'type': 'token_count', 'rate_limits': rl}}
    if timestamp:
        event['timestamp'] = stamp(at)
    (folder / 'rollout-owner.jsonl').write_text(json.dumps(meta) + '\n' + json.dumps(event) + '\n', encoding='utf-8')
    return root


def gate(root, attempts=(), harvested=None, account=ACCOUNT_SHA):
    return quota.coverage_gate(list(attempts), root, harvested, account_sha256=account, now=NOW)


# ======================================================================= P3 and OB-P3: quota.coverage_gate

def test_p3_control_an_attributable_fresh_owner_reading_passes(tmp_path):
    g = gate(owner_session(tmp_path))
    assert g['ok'] is True and g['percent'] == 10.0


def test_p3_an_owner_reading_without_an_account_hash_blocks(tmp_path):
    """Astra A, P3: a rollout with no creator_account_id (the 0.163.0-alpha rollouts) is not attributable."""
    g = gate(owner_session(tmp_path, account=None))
    assert g['ok'] is False and 'no account hash' in g['reason']


def test_p3_an_unknown_baseline_account_hash_blocks(tmp_path):
    g = gate(owner_session(tmp_path), account=None)
    assert g['ok'] is False and 'baseline account hash is unknown' in g['reason']


def test_p3_an_owner_reading_of_another_account_blocks(tmp_path):
    g = gate(owner_session(tmp_path, account='acct-other'))
    assert g['ok'] is False and 'another account' in g['reason']


@pytest.mark.parametrize('limit_id', ['codex_other_bucket', None])
def test_p3_an_owner_reading_of_another_bucket_blocks(tmp_path, limit_id):
    g = gate(owner_session(tmp_path, limit_id=limit_id))
    assert g['ok'] is False and 'bucket' in g['reason']


@pytest.mark.parametrize('window', [300, None, '10080'])
def test_p3_an_owner_reading_of_another_window_blocks(tmp_path, window):
    g = gate(owner_session(tmp_path, window=window))
    assert g['ok'] is False and 'window' in g['reason']


def test_p3_an_owner_reading_without_an_event_timestamp_blocks(tmp_path):
    g = gate(owner_session(tmp_path, timestamp=False))
    assert g['ok'] is False and 'no event timestamp' in g['reason']


def test_p3_an_owner_reading_three_days_old_blocks(tmp_path):
    g = gate(owner_session(tmp_path, at=NOW - dt.timedelta(days=3)))
    assert g['ok'] is False and 'stale' in g['reason']


def test_p3_the_freshness_rule_is_the_manifest_limit(tmp_path):
    limit = config.QUOTA_OWNER_MAX_AGE_MINUTES
    assert gate(owner_session(tmp_path, at=NOW - dt.timedelta(minutes=limit - 1)))['ok'] is True
    assert gate(owner_session(tmp_path, at=NOW - dt.timedelta(minutes=limit + 1)))['ok'] is False
    manifest = json.loads((config.REPO / 'docs' / 'design' / 'ozmap-replication-2026-10-24' / 'rulings' /
                           'P3-quota-source-manifest.json').read_text(encoding='utf-8'))
    rule = manifest['freshness_rule']
    assert rule['owner_reading_max_age_minutes'] == limit
    assert manifest['bucket_identity']['limit_id'] == config.QUOTA_LIMIT_ID
    assert manifest['bucket_identity']['window_minutes'] == config.QUOTA_WINDOW_MINUTES


def test_p3_no_owner_reading_blocks_even_when_harvested_readings_cover_every_attempt(tmp_path):
    attempt = {'call_id': 'x', 'attempt_uid': 'u1', 'backend': 'codex', 'mode': 'live', 'outcome': 'ok',
               'ended_at': stamp(NOW - dt.timedelta(minutes=5))}
    harvested = {'u1': [harvested_reading()]}
    g = gate(tmp_path / 'none', [attempt], harvested)
    assert g['ok'] is False and 'no owner reading' in g['reason']


def harvested_reading(**change):
    out = {'percent': 12.0, 'timestamp': stamp(NOW - dt.timedelta(minutes=6)), 'account_sha256': ACCOUNT_SHA,
           'limit_id': 'codex', 'window_minutes': 10080}
    out.update(change)
    return out


ATTEMPT = {'call_id': 'x', 'attempt_uid': 'u1', 'backend': 'codex', 'mode': 'live', 'outcome': 'ok',
           'started_at': stamp(NOW - dt.timedelta(minutes=8)), 'ended_at': stamp(NOW - dt.timedelta(minutes=5))}


def covered(tmp_path, reading):
    # the owner reading is fresh but older than the attempt's end, so only the harvested reading can cover it
    return gate(owner_session(tmp_path, at=NOW - dt.timedelta(minutes=20)), [ATTEMPT], {'u1': [reading]})


# test_p3_control_an_attributable_harvested_reading_covers_its_attempt: encoded form (i) of the D5 predicate (the
# reading of an attempt's own rollout covers it), which Opus B rejected (rulings/signoff-opus-2.md, D5 point 1);
# replaced by the two tests below.

def test_p3_control_an_attributable_harvested_reading_never_covers_its_own_attempt(tmp_path):
    g = covered(tmp_path, harvested_reading(session_started_at=ATTEMPT['started_at'],
                                            turn_started_at=ATTEMPT['started_at']))
    assert g['ok'] is False and g['uncovered'] == ['x'], g


def test_p3_control_a_later_attributable_harvested_reading_covers_the_attempt(tmp_path):
    # y is marked not launched so that only x needs coverage here; tests/test_p3_d5_coverage.py covers chains
    later = {'call_id': 'y', 'attempt_uid': 'u2', 'backend': 'codex', 'mode': 'live', 'outcome': 'not_launched'}
    start = stamp(NOW - dt.timedelta(minutes=4))
    g = gate(owner_session(tmp_path, at=NOW - dt.timedelta(minutes=20)), [ATTEMPT, later],
             {'u2': [harvested_reading(timestamp=stamp(NOW - dt.timedelta(minutes=3)), session_started_at=start,
                                       turn_started_at=start)]})
    assert g['ok'] is True and g['percent'] == 12.0 and g['covered_by'] == {'x': 'rollout of y'}, g


@pytest.mark.parametrize('change,why', [
    ({'account_sha256': None}, 'no account hash'),
    ({'account_sha256': OTHER_SHA}, 'another account'),
    ({'limit_id': 'codex_other_bucket'}, 'bucket'),
    ({'limit_id': None}, 'bucket'),
    ({'window_minutes': 300}, 'window'),
    ({'timestamp': None}, 'malformed'),
    ({'timestamp': stamp(NOW + dt.timedelta(hours=1))}, 'future'),
    ({'timestamp': stamp(NOW - dt.timedelta(days=3))}, 'predates the attempt'),
])
def test_p3_a_harvested_reading_that_is_not_attributable_blocks(tmp_path, change, why):
    """Opus B, OB-P3: a harvested worker reading with no account hash returned ok at 12%."""
    g = covered(tmp_path, harvested_reading(**change))
    assert g['ok'] is False and why in g['reason'], g['reason']


def test_p3_read_file_records_the_bucket_of_the_reading(tmp_path):
    owner_session(tmp_path, window=300, limit_id='codex_other_bucket')
    r = quota.latest_reading(tmp_path)
    assert r['limit_id'] == 'codex_other_bucket' and r['window_minutes'] == 300


def test_p3_harvest_keeps_the_bucket_for_the_gate(tmp_path):
    path = owner_session(tmp_path) / '2026' / '10' / '25' / 'rollout-owner.jsonl'
    [obs] = quota.harvest_rollout(path)
    assert obs['limit_id'] == 'codex' and obs['window_minutes'] == 10080 and obs['account_sha256'] == ACCOUNT_SHA


# ======================================================================= annex status (OB-P3, OB-P5, OB-D1)

def bind(tmp_path, name, kind, doc):
    """A countersigned tmp ruling binding one annex document, as opusb_repro.py built it."""
    annex = tmp_path / f'{kind}.json'
    annex.write_text(json.dumps(doc), encoding='utf-8')
    digest = isolation.sha256_file(annex)
    entry = {'annexes': {kind: {'path': str(annex), 'sha256': digest}}}
    text = f'{name} ruling\n{kind} {digest}\nSigned: Astra A\nSigned: Opus B\n'
    # only the problems of this annex (P5 also requires the startup manifest, which other tests cover)
    return [p for p in rulings.annex_problems(name, entry, text) if f'annex {kind}' in p]


def p5_doc(verdict):
    return dict(settled_annex('effective_context_evidence'), verdict=verdict,
                route_security_args=list(config.ROUTE_SECURITY_ARGS))


@pytest.mark.parametrize('status', ['not_established', 'pending_signature', None])
def test_ob_p3_a_quota_manifest_without_established_causal_coverage_does_not_bind(tmp_path, status):
    doc = {'freshness_and_causal_coverage': {'status': status}}
    problems = bind(tmp_path, 'P3', 'quota_source_manifest', doc)
    assert any('freshness_and_causal_coverage.status' in p for p in problems)
    assert bind(tmp_path, 'P3', 'quota_source_manifest', settled_annex('quota_source_manifest')) == []


def test_ob_p3_the_repository_manifest_is_refused_until_coverage_is_established():
    path = config.REPO / 'docs' / 'design' / 'ozmap-replication-2026-10-24' / 'rulings' / 'P3-quota-source-manifest.json'
    doc = json.loads(path.read_text(encoding='utf-8'))
    status = doc['freshness_and_causal_coverage']['status']
    digest = isolation.sha256_file(path)
    problems = rulings.annex_problems('P3', {'annexes': {'quota_source_manifest': {
        'path': str(path), 'sha256': digest}}}, f'{digest}\nSigned: Astra A\nSigned: Opus B\n')
    assert (problems == []) == (status == 'established')


@pytest.mark.parametrize('verdict', ['not_established', 'partial', None])
def test_ob_p5_an_effective_context_annex_that_is_not_established_does_not_bind(tmp_path, verdict):
    problems = bind(tmp_path, 'P5', 'effective_context_evidence', p5_doc(verdict))
    assert any("verdict" in p for p in problems)
    assert bind(tmp_path, 'P5', 'effective_context_evidence', p5_doc('established')) == []


def test_ob_p5_an_effective_context_annex_of_other_route_arguments_does_not_bind(tmp_path):
    doc = dict(p5_doc('established'), route_security_args=list(config.ROUTE_SECURITY_ARGS[:4]))
    problems = bind(tmp_path, 'P5', 'effective_context_evidence', doc)
    assert any('route security arguments' in p for p in problems)


@pytest.mark.parametrize('status', ['partial', 'partial: static evidence only', None])
def test_ob_d1_an_attribution_annex_that_is_not_complete_does_not_bind(tmp_path, status):
    problems = bind(tmp_path, 'D1', 'attribution_evidence', {'status': status})
    assert any('status' in p for p in problems)
    assert bind(tmp_path, 'D1', 'attribution_evidence', settled_annex('attribution_evidence')) == []


# ======================================================================= OB-P5: owner skills off the frozen route

def test_ob_p5_the_frozen_route_turns_skill_instructions_and_bundled_skills_off(tmp_path):
    args = list(config.ROUTE_SECURITY_ARGS)
    for key in ('skills.include_instructions=false', 'skills.bundled.enabled=false'):
        k = args.index(key)
        assert args[k - 1] == '-c'
    work = tmp_path / 'slot-0'
    argv = isolation.codex_argv('codex', config.CODEX_MODEL, config.CODEX_EFFORT, work, [])
    assert isolation.argv_check(argv) == []
    for key in ('skills.include_instructions=false', 'skills.bundled.enabled=false'):
        bad = list(argv)
        k = bad.index(key)
        del bad[k - 1:k + 1]
        assert any('route security' in p for p in isolation.argv_check(bad)), key


def test_ob_p5_an_empty_approved_startup_manifest_counts_as_approved(tmp_path, monkeypatch):
    manifest = tmp_path / 'startup-manifest.json'
    monkeypatch.setattr(config, 'STARTUP_MANIFEST_FILE', manifest)
    assert isolation.startup_manifest_present() is False
    assert any('startup manifest' in p for p in rulings.configuration_problems([]))
    manifest.write_text(json.dumps({'files': []}), encoding='utf-8')
    assert isolation.startup_manifest_present() is True
    assert not any('startup manifest' in p for p in rulings.configuration_problems([]))
    assert isolation.startup_instruction_files(['skills/.system/x/SKILL.md'], {}) == ['skills/.system/x/SKILL.md']


def test_ob_p5_the_repository_annexes_were_captured_on_the_frozen_route():
    """The effective context evidence and the startup manifest record the route security arguments and the disable
    options the harness uses now, and the evidence holds no owner content finding."""
    root = config.REPO / 'docs' / 'design' / 'ozmap-replication-2026-10-24' / 'rulings'
    doc = json.loads((root / 'P5-effective-context-evidence.json').read_text(encoding='utf-8'))
    from bench.ozmap_rep import run
    assert doc['route_security_args'] == list(config.ROUTE_SECURITY_ARGS)
    assert doc['disable_args'] == run.cli_flags()[0]
    if doc['verdict'] == 'established':
        scan = doc['owner_content_scan']
        assert scan['hits'] == [] and scan['lines_checked'] > 0
        assert doc['request_boundary']['external_requests'] == []
    manifest = json.loads(Path(config.STARTUP_MANIFEST_FILE).read_text(encoding='utf-8'))
    assert manifest['capture']['route_security_args'] == list(config.ROUTE_SECURITY_ARGS)
