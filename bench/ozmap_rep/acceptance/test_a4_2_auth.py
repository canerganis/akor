"""A4.2: authentication hash sync under a lock, no auth contents in logs, reconciliation, wave expiry gate."""
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

import ozrep_helpers as H
from ozrep_helpers import harness, need


def make_iso(tmp_path, baseline):
    iso = harness('isolation')
    root, evidence = tmp_path / 'run', tmp_path / 'evidence'
    root.mkdir(exist_ok=True)
    evidence.mkdir(exist_ok=True)
    return iso, need(iso, 'Isolation')(baseline, root, evidence, lock=tmp_path / 'auth.lock'), root, evidence


def refreshed(doc_exp, last_refresh, token='SECRET-ROTATED-ACCESS-999'):
    doc = H.auth_doc(doc_exp, last_refresh=last_refresh, refresh='SECRET-ROTATED-REFRESH-888')
    doc['tokens']['access_token'] = H.make_jwt(doc_exp, {'rot': token})
    return doc


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_a4_2_unchanged_worker_auth_reports_no_change(tmp_path, baseline):
    iso, isolation, _, _ = make_iso(tmp_path, baseline)
    isolation.prepare(0)
    done = isolation.finish(0)
    assert done['auth_changed'] is False
    assert done['worker_auth_sha256'] == done['baseline_auth_sha256'] == sha(baseline / 'auth.json')


def test_a4_2_changed_worker_auth_is_detected_by_hash_and_synced_to_baseline(tmp_path, baseline):
    iso, isolation, _, _ = make_iso(tmp_path, baseline)
    prepared = isolation.prepare(1)
    new_exp = H.now_utc() + dt.timedelta(days=20)
    (Path(prepared['home']) / 'auth.json').write_text(json.dumps(refreshed(new_exp, '2026-10-24T12:00:00Z')),
                                                     encoding='utf-8')
    worker_hash = sha(Path(prepared['home']) / 'auth.json')
    before = sha(baseline / 'auth.json')
    done = isolation.finish(1)
    assert done['auth_changed'] is True and done['worker_auth_sha256'] == worker_hash
    assert sha(baseline / 'auth.json') == before, 'finish alone must not touch the baseline'
    result = isolation.propagate(1)
    assert result['before'] == before and result['after'] == worker_hash
    assert sha(baseline / 'auth.json') == worker_hash
    # the next reconstruction starts from the propagated baseline
    nxt = isolation.prepare(2)
    assert sha(Path(nxt['home']) / 'auth.json') == worker_hash


def test_a4_2_never_restores_an_older_token_snapshot(tmp_path, baseline):
    iso, isolation, _, _ = make_iso(tmp_path, baseline)
    stale = need(iso, 'StaleAuth')
    prepared = isolation.prepare(0)
    older = refreshed(H.now_utc() + dt.timedelta(days=10), '2026-10-01T00:00:00Z')
    (Path(prepared['home']) / 'auth.json').write_text(json.dumps(older), encoding='utf-8')
    before = sha(baseline / 'auth.json')
    isolation.finish(0)
    with pytest.raises(stale):
        isolation.propagate(0)
    assert sha(baseline / 'auth.json') == before


HOLDER = chr(10).join([
    "import sys, time, pathlib",
    "from bench.ozmap_rep import isolation as i",
    "with i.auth_lock(sys.argv[1]):",
    "    pathlib.Path(sys.argv[2]).write_text('1')",
    "    end = time.time() + 60",
    "    while not pathlib.Path(sys.argv[3]).exists() and time.time() < end:",
    "        time.sleep(0.05)",
    ""])


class Holder:
    """A separate process holding the authentication lock until released."""

    def __init__(self, tmp_path):
        self.lock = tmp_path / 'auth.lock'
        self.ready, self.release = tmp_path / 'ready', tmp_path / 'release'
        self.proc = subprocess.Popen([sys.executable, '-c', HOLDER, str(self.lock), str(self.ready),
                                      str(self.release)], cwd=str(H.REPO))
        end = time.time() + 30
        while not self.ready.exists() and time.time() < end:
            time.sleep(0.05)
        assert self.ready.exists(), 'lock holder did not start'

    def let_go(self):
        self.release.write_text('1')
        self.proc.wait(timeout=30)


def test_a4_2_propagation_waits_for_the_authentication_lock_and_times_out(tmp_path, baseline):
    iso, isolation, _, _ = make_iso(tmp_path, baseline)
    lock_timeout = need(iso, 'LockTimeout')
    prepared = isolation.prepare(0)
    new_exp = H.now_utc() + dt.timedelta(days=20)
    (Path(prepared['home']) / 'auth.json').write_text(json.dumps(refreshed(new_exp, '2026-10-24T12:00:00Z')),
                                                     encoding='utf-8')
    worker_hash = sha(Path(prepared['home']) / 'auth.json')
    isolation.finish(0)
    before = sha(baseline / 'auth.json')
    holder = Holder(tmp_path)
    try:
        with pytest.raises(lock_timeout):
            isolation.propagate(0, lock_timeout=0.5)
        assert sha(baseline / 'auth.json') == before, 'a timed out propagation must not write'
    finally:
        holder.let_go()
    assert isolation.propagate(0, lock_timeout=10)['after'] == worker_hash
    assert sha(baseline / 'auth.json') == worker_hash


def test_a4_2_reconstruction_runs_under_the_authentication_lock(tmp_path, baseline):
    import threading
    iso, isolation, _, _ = make_iso(tmp_path, baseline)
    holder = Holder(tmp_path)
    done = threading.Event()
    thread = threading.Thread(target=lambda: (isolation.prepare(3), done.set()), daemon=True)
    try:
        thread.start()
        assert not done.wait(1.0), 'prepare must wait while another process holds the authentication lock'
    finally:
        holder.let_go()
    assert done.wait(30), 'prepare must proceed once the lock is released'


def test_a4_2_no_auth_contents_in_logs_evidence_or_output(tmp_path, baseline, caplog, capsys):
    iso, isolation, _, evidence = make_iso(tmp_path, baseline)
    caplog.set_level('DEBUG')
    prepared = isolation.prepare(0)
    new_exp = H.now_utc() + dt.timedelta(days=20)
    (Path(prepared['home']) / 'auth.json').write_text(json.dumps(refreshed(new_exp, '2026-10-24T12:00:00Z')),
                                                     encoding='utf-8')
    results = [isolation.finish(0)]
    results.append(isolation.propagate(0))
    results.append(iso.wave_gate(baseline))
    results.append(iso.reconcile_auth('a' * 64, {0: {'sha256': 'b' * 64, 'auth_failure': False}}))
    blob = json.dumps(results, default=str)
    out = capsys.readouterr()
    haystack = '\n'.join([blob, caplog.text, out.out, out.err] + list(H.tree_text(evidence).values()))
    for secret in (H.SECRET_ACCESS_MARK, H.SECRET_REFRESH, 'SECRET-ROTATED-ACCESS-999', 'SECRET-ROTATED-REFRESH-888',
                   json.loads((baseline / 'auth.json').read_text(encoding='utf-8'))['tokens']['access_token']):
        assert secret not in haystack, f'auth material leaked: {secret[:20]}'


@pytest.mark.parametrize('workers,in_flight,expected', [
    ({0: ('A', False), 1: ('A', False)}, (), 'continue'),
    ({0: ('B', False), 1: ('A', False)}, (), 'propagate'),
    ({0: ('B', False), 1: ('A', False)}, (1,), 'wait'),
    ({0: ('A', True), 1: ('A', False)}, (), 'stop_codex'),
    ({0: ('B', False), 1: ('C', False)}, (), 'stop_codex'),
    ({0: ('B', True), 1: ('A', False)}, (), 'stop_codex'),
    ({0: ('B', False), 1: ('A', True)}, (), 'stop_codex'),
])
def test_a4_2_reconcile_auth_actions(workers, in_flight, expected):
    iso = harness('isolation')
    reconcile = need(iso, 'reconcile_auth')
    base = 'A' * 8
    table = {s: {'sha256': h * 8, 'auth_failure': f} for s, (h, f) in workers.items()}
    out = reconcile(base, table, in_flight=in_flight)
    assert out['action'] == expected
    if expected == 'propagate':
        assert out['slot'] == 0
    if expected == 'stop_codex':
        assert out.get('interrupted') is True


def test_a4_2_wave_gate_requires_48_hours_of_access_token_life(tmp_path):
    iso = harness('isolation')
    gate = need(iso, 'wave_gate')
    now = dt.datetime(2026, 10, 24, 12, 0, tzinfo=dt.timezone.utc)

    def at(delta):
        d = tmp_path / f'b{int(delta.total_seconds())}'
        H.write_auth(d, H.auth_doc(now + delta))
        return gate(d, now=now)

    ok = at(dt.timedelta(hours=48))
    assert ok['ok'] is True
    assert at(dt.timedelta(days=10))['ok'] is True
    short = at(dt.timedelta(hours=47, minutes=59))
    assert short['ok'] is False and 'codex login' in short['reason']
    assert at(dt.timedelta(hours=-1))['ok'] is False


def test_a4_2_wave_gate_missing_or_unreadable_exp_prevents_launch(tmp_path):
    iso = harness('isolation')
    gate = need(iso, 'wave_gate')
    now = dt.datetime(2026, 10, 24, 12, 0, tzinfo=dt.timezone.utc)
    missing = tmp_path / 'missing'
    missing.mkdir()
    assert gate(missing, now=now)['ok'] is False
    garbage = tmp_path / 'garbage'
    H.write_auth(garbage, {'tokens': {'access_token': 'not-a-jwt', 'refresh_token': 'r'}})
    out = gate(garbage, now=now)
    assert out['ok'] is False and 'codex login' in out['reason']
    nojson = tmp_path / 'nojson'
    nojson.mkdir()
    (nojson / 'auth.json').write_text('{{{', encoding='utf-8')
    assert gate(nojson, now=now)['ok'] is False
    noexp = tmp_path / 'noexp'
    import base64
    payload = base64.urlsafe_b64encode(b'{"sub":"x"}').rstrip(b'=').decode()
    H.write_auth(noexp, {'tokens': {'access_token': f'h.{payload}.s', 'refresh_token': 'r'}})
    assert gate(noexp, now=now)['ok'] is False


def test_a4_2_wave_gate_logs_only_the_timestamp(tmp_path, baseline):
    iso = harness('isolation')
    out = need(iso, 'wave_gate')(baseline)
    text = json.dumps(out, default=str)
    assert H.SECRET_ACCESS_MARK not in text and H.SECRET_REFRESH not in text
    assert out['ok'] is True and out['hours_left'] > 48
