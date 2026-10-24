"""Regression tests for the council build round 1 blockers (docs/design/ozmap-replication-2026-10-24/
council-build-*-r1.md). One section per blocker id. Fakes and temporary directories only: no real `codex` or
`claude` is resolved or spawned, live mode runs the harness' own fakes through the real lifecycle code, and no real
baseline, run directory, experiment ledger or Codex session directory is touched.
"""
import base64
import datetime as dt
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import pytest

from bench.ozmap_rep import (bootstrap, config, events, gates, isolation, prompts, quota, redact, run, score, usage,
                             workload)

HERE = Path(__file__).resolve().parent
UNKNOWN_ONLY = (b'{"lang":"oz-rule/1","expr":["if",["eq",["field","temp"],["s","unknown"]],["s","unknown"],'
                b'["require",["eq",["s","a"],["s","b"]],["s","x"]]]}')


# ======================================================================================================= helpers

def stream(*evts):
    return '\n'.join(json.dumps(e) for e in evts) + '\n'


def ok_stream(text='OZ/1g', **extra_usage):
    usage_ = {'input_tokens': 100, 'cached_input_tokens': 0, 'output_tokens': 10, 'reasoning_output_tokens': 2}
    usage_.update(extra_usage)
    return stream({'type': 'thread.started', 'thread_id': 't'}, {'type': 'turn.started'},
                  {'type': 'item.completed', 'item': {'id': 'm', 'type': 'agent_message', 'text': text}},
                  {'type': 'turn.completed', 'usage': usage_})


def fake_opts(tmp_path, run_dir=None, **kw):
    workload.fake_answer_table()
    base = tmp_path / 'baseline'
    if not (base / 'auth.json').exists():
        run.synthetic_baseline(base)
    return run.Options(run_dir or tmp_path / 'run', mode='fake', baseline=base, out=io.StringIO(), **kw)


def go(tmp_path, cell_id, **kw):
    return run.CellRun(run.spec_by_id(cell_id), fake_opts(tmp_path, **kw)).run()


def attempts(run_dir, cell_id=None):
    return [r for r in run.jsonl(Path(run_dir) / 'attempts.jsonl') if cell_id is None or r.get('cell') == cell_id]


def sha(path):
    return isolation.sha256_file(path)


def write_auth(directory, marker, days=20, last_refresh=None):
    exp = int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)).timestamp())
    b64 = lambda d: base64.urlsafe_b64encode(d).rstrip(b'=').decode()  # noqa: E731
    token = '.'.join([b64(b'{"alg":"none"}'), b64(json.dumps({'exp': exp, 'm': marker}).encode()), b64(b'x')])
    doc = {'auth_mode': 'chatgpt', 'tokens': {'id_token': 'x', 'access_token': token,
                                              'refresh_token': f'REFRESH-{marker}-0123456789'},
           'last_refresh': last_refresh or dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')}
    Path(directory).mkdir(parents=True, exist_ok=True)
    (Path(directory) / 'auth.json').write_text(json.dumps(doc), encoding='utf-8')
    return Path(directory) / 'auth.json'


class Live:
    """Live mode on the harness' own fakes: the real gates, lifecycle, isolation, reconciliation and scoring, with
    the executables, the canonical run directory, the freeze check, the tokenizer and the session readings replaced
    for the test. The experiment ledger and every directory are temporary."""

    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.run_dir = tmp_path / 'live'
        self.base = tmp_path / 'baseline'
        run.synthetic_baseline(self.base)
        self.ledger = tmp_path / 'ledger.jsonl'
        self.fakebin = tmp_path / 'fakebin'
        self.sessions = tmp_path / 'sessions'
        self.touch_sessions()
        self.mutate = None  # callable(raw, env, cwd, launch) -> raw, applied after a fake call
        self.before = None  # callable(env, cwd, launch), applied before a fake call
        monkeypatch.setattr(run, 'live_run_dir', lambda: self.run_dir)
        monkeypatch.setattr(run, 'verify_freeze', lambda: [])
        monkeypatch.setattr(run, 'freeze_sha256', lambda: 'f' * 64)
        monkeypatch.setattr(run.tokenizer, 'vocabulary_ok', lambda: True)
        monkeypatch.setattr(run.tokenizer, 'count', lambda texts: [max(1, len(t) // 4) for t in texts])
        fakebin = self.fakebin

        class FakeExecutables(run.Executables):
            def __init__(self, opts, backend):
                saved = (opts.mode, opts.run_dir)
                opts.mode, opts.run_dir = 'fake', fakebin
                try:
                    super().__init__(opts, backend)
                finally:
                    opts.mode, opts.run_dir = saved

        monkeypatch.setattr(run, 'Executables', FakeExecutables)
        original_spawn, original_local = run.spawn, run.run_local
        live = self

        def spawn(run_dir, launch, stdin_text, env, cwd, external, timeout=config.CALL_TIMEOUT_S):
            if not external:  # a fake mode cell in the same test runs unchanged
                return original_spawn(run_dir, launch, stdin_text, env, cwd, external, timeout)
            exe = Path(launch[0]).resolve()
            assert (fakebin / 'fake').resolve() in exe.parents, f'refusing a non fake executable {exe}'
            directive = {'cell': 'live', 'n': 0, 'call_id': f'{Path(cwd).name}-{time.monotonic_ns()}', 'fail': False,
                         'refresh': False, 'bootstrap_ops': None}
            (fakebin / 'fake' / 'directives' / f'{Path(cwd).name}.json').write_text(json.dumps(directive),
                                                                                  encoding='utf-8')
            if live.before:
                live.before(env, cwd, launch)
            raw = original_spawn(run_dir, [sys.executable, *launch], stdin_text, env, cwd, external, timeout)
            if live.mutate:
                raw = live.mutate(raw, env, cwd, launch)
            return raw

        def run_local(argv, env, cwd, on_start=None, timeout=120):
            assert (fakebin / 'fake').resolve() in Path(argv[0]).resolve().parents
            return original_local([sys.executable, *argv], env, cwd, on_start, timeout)

        monkeypatch.setattr(run, 'spawn', spawn)
        monkeypatch.setattr(run, 'run_local', run_local)

    def touch_sessions(self, percent=10.0):
        """An owner reading of the same account timestamped now (council round 2, P3: the event time covers the
        calls before it; the file time is never used)."""
        folder = self.sessions / '2026' / '10' / '24'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'rollout-test.jsonl'
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        path.write_text(json.dumps({'timestamp': stamp, 'type': 'event_msg', 'payload': {'rate_limits': {
            'primary': {'used_percent': percent}}}}) + '\n', encoding='utf-8')
        now = time.time() + 1
        os.utime(path, (now, now))

    def opts(self, run_dir=None, **kw):
        workload.fake_answer_table()
        return run.Options(run_dir or self.run_dir, mode='live', baseline=self.base, sessions_dir=self.sessions,
                           claude_percent=50.0, live_ledger=self.ledger, out=io.StringIO(), **kw)

    def telemetry(self):
        self.touch_sessions()
        return run.TelemetryRun(self.opts()).run()

    def cell(self, cell_id, **kw):
        self.touch_sessions()
        return run.CellRun(run.spec_by_id(cell_id), self.opts(**kw)).run()


@pytest.fixture
def live(tmp_path, monkeypatch):
    return Live(tmp_path, monkeypatch)


def full_certificate(**over):
    paths = {str(k): 'not_logged_in' for k in range(config.SLOTS)}
    doc = {'auth_read_from_codex_home': True, 'sandbox_clean_home': True, 'reconciled': True,
           'exec_probe': {'outcome': 'auth_failure', 'reply': False, 'usage_present': False, 'home': 'worker',
                          'account_metadata_kept': True, 'runtime_files': ['state.sqlite']},
           'login_status': {'worker_paths_before': dict(paths), 'worker_paths_after': dict(paths),
                            'worker_home': 'logged_in'},
           'call': {'outcome': 'ok', 'stream_verdict': 'plain', 'home_listing_before': ['auth.json'],
                    'workdir_listing_before': [], 'instruction_sources': [], 'runtime_files': ['state.sqlite'],
                    'auth_source': {'store': 'file', 'home': 'worker', 'auth_sha256': 'a' * 64}}}
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(doc.get(k), dict):
            doc[k] = dict(doc[k], **v)
        else:
            doc[k] = v
    return doc


# ================================================================== item 1: telemetry certificate evidence

def test_item1_booleans_alone_never_certify():
    assert isolation.telemetry_checks({'auth_read_from_codex_home': True, 'sandbox_clean_home': True}) == []
    assert isolation.telemetry_certificate({'auth_read_from_codex_home': True, 'sandbox_clean_home': True})
    assert isolation.telemetry_certificate(full_certificate()) == []


def test_item1_a_startup_instruction_source_with_the_same_listing_and_reply_fails_certification():
    doc = full_certificate(call={'runtime_files': ['state.sqlite', 'skills/.system/imagegen/SKILL.md']})
    assert doc['call']['home_listing_before'] == ['auth.json'] and doc['call']['stream_verdict'] == 'plain'
    assert any('instruction bearing' in p for p in isolation.telemetry_certificate(doc))
    doc = full_certificate(call={'runtime_files': ['AGENTS.md']})
    assert isolation.telemetry_certificate(doc)


def test_item1_an_alternative_credential_lookup_fails_certification():
    doc = full_certificate(exec_probe={'outcome': 'ok', 'reply': True, 'usage_present': True})
    assert any('alternative credential' in p for p in isolation.telemetry_certificate(doc))
    doc = full_certificate(login_status={'worker_paths_after': {'0': 'not_logged_in', '1': 'logged_in',
                                                                '2': 'not_logged_in', '3': 'not_logged_in'}})
    assert any('worker path' in p for p in isolation.telemetry_certificate(doc))
    doc = full_certificate(call={'auth_source': {'store': 'keyring', 'home': 'worker', 'auth_sha256': 'a'}})
    assert any('file credential store' in p for p in isolation.telemetry_certificate(doc))


def test_item1_live_telemetry_through_the_lifecycle_certifies_a_clean_route(live):
    assert live.telemetry() == config.EXIT_OK
    rows = run.jsonl(live.run_dir / 'evidence' / 'telemetry.jsonl')
    assert len(rows) == 1 and rows[0]['passed'] is True
    cert = rows[0]['certificate']
    assert cert['exec_probe']['outcome'] == 'auth_failure' and cert['exec_probe']['home'] == 'worker'
    assert set(cert['login_status']['worker_paths_before'].values()) == {'not_logged_in'}
    assert set(cert['login_status']['worker_paths_after'].values()) == {'not_logged_in'}
    assert cert['call']['home_listing_before'] == ['auth.json'] and cert['reconciled'] is True
    assert run.telemetry_problems(live.run_dir) == []
    tel = attempts(live.run_dir, 'telemetry')
    assert [a['expected_outcome'] for a in tel] == ['auth_failure', 'ok'] and all(a['kind'] == 'telemetry' for a in tel)
    assert [r['call_id'] for r in run.jsonl(live.ledger)] == [a['call_id'] for a in tel]
    assert live.telemetry() == config.EXIT_ALREADY


def test_item1_live_telemetry_with_a_startup_skill_file_is_not_certified(live):
    def before(env, cwd, launch):
        home = Path(env['CODEX_HOME'])
        if (home / 'auth.json').exists():
            (home / 'skills' / '.system' / 'x').mkdir(parents=True, exist_ok=True)
            (home / 'skills' / '.system' / 'x' / 'SKILL.md').write_text('a bundled skill', encoding='utf-8')
    live.before = before
    assert live.telemetry() == config.EXIT_TELEMETRY
    assert run.telemetry_problems(live.run_dir)


def test_item1_live_telemetry_with_an_alternative_credential_source_is_not_certified(live):
    """Council round 2, item 1: a credential store keyed by the account metadata of auth.json. The probe home keeps
    the baseline's account metadata but its tokens are unaccepted; a CLI that looks credentials up by account (here:
    a store outside CODEX_HOME holding the valid baseline document) still authenticates, the probe gets a reply, and
    the route is never certified. No charged call follows the probe."""
    store = live.tmp / 'account-keyed-store'
    store.mkdir()
    shutil.copyfile(live.base / 'auth.json', store / 'auth.json')

    def before(env, cwd, launch):
        doc = json.loads((Path(env['CODEX_HOME']) / 'auth.json').read_text(encoding='utf-8'))
        if doc['tokens']['access_token'].split('.')[2].startswith('scrambled'):
            env['CODEX_HOME'] = str(store)  # credentials found by account, not from the prepared file
    live.before = before
    assert live.telemetry() == config.EXIT_TELEMETRY
    assert any('ended' in p for p in run.telemetry_failures(live.run_dir))
    tel = attempts(live.run_dir, 'telemetry')
    assert [a['role'] for a in tel] == ['probe'], 'no charged telemetry call after the failed probe'


def test_item1_a_credential_keyed_by_a_worker_path_is_not_certified(live, monkeypatch):
    """B4: `login status` at an emptied worker path that still reports logged in (a store keyed by the CODEX_HOME
    path) fails certification, before and after the call."""
    original = run.run_local

    def run_local(argv, env, cwd, on_start=None, timeout=120):
        code, out, err = original(argv, env, cwd, on_start, timeout)
        if 'login' in argv and Path(env['CODEX_HOME']).name == 'worker-2' and \
                not (Path(env['CODEX_HOME']) / 'auth.json').exists():
            return 0, 'Logged in using ChatGPT\n', ''
        return code, out, err
    monkeypatch.setattr(run, 'run_local', run_local)
    assert live.telemetry() == config.EXIT_TELEMETRY
    rows = run.jsonl(live.run_dir / 'evidence' / 'telemetry.jsonl')
    assert rows and any('worker path' in p for p in rows[-1]['problems'])


# ======================================================================== item 2, RT1.2, C1: guards before state

def test_item2_a_second_runner_of_any_cell_exits_before_touching_state(tmp_path, monkeypatch):
    first_in = threading.Event()
    release = threading.Event()
    original = run.CellRun._guarded

    def slow(self):
        first_in.set()
        release.wait(20)
        return original(self)

    monkeypatch.setattr(run.CellRun, '_guarded', slow)
    codes = {}
    t = threading.Thread(target=lambda: codes.setdefault('a', go(tmp_path, 'codex-materials-cold-A')), daemon=True)
    t.start()
    assert first_in.wait(20)
    monkeypatch.setattr(run.CellRun, '_guarded', original)
    for cid in ('codex-materials-cold-A', 'sonnet-materials-cold-A', 'codex-boolq-cold-A'):
        assert go(tmp_path, cid) == config.EXIT_BUSY
    release.set()
    t.join(120)
    assert codes['a'] == 0
    rows = attempts(tmp_path / 'run')
    assert {r['cell'] for r in rows} == {'codex-materials-cold-A'} and len(rows) == 4


def test_item2_a_features_probe_owns_its_slot_and_reconciles(live, monkeypatch):
    assert live.telemetry() == 0
    taken = []
    original_acquire, original_prepare = run.Slots.acquire, isolation.Isolation.prepare

    def acquire(self, *a, **k):
        slot = original_acquire(self, *a, **k)
        taken.append(slot)
        return slot

    def prepare(self, slot, lock_timeout=None, scrambled=False):
        assert slot in taken, f'worker {slot} rebuilt without owning its slot'
        return original_prepare(self, slot, lock_timeout, scrambled)

    monkeypatch.setattr(run.Slots, 'acquire', acquire)
    monkeypatch.setattr(isolation.Isolation, 'prepare', prepare)
    assert live.cell('codex-materials-cold-A') == 0
    feat = json.loads((live.run_dir / 'evidence' / 'features-codex-materials-cold-A.json').read_text(encoding='utf-8'))
    assert feat['features']
    rows = run.jsonl(live.run_dir / 'evidence' / 'auth-reconcile.jsonl')
    assert any(any(c.startswith('probe-features') for c in r['calls']) for r in rows)


# ===================================================================== item 3, B3: recovery and reconciliation

def orphan_marker(tmp_path, cell_id, slot, prepared, pid=None, batch='r1.b01', role='call'):
    cell_dir = tmp_path / 'run' / 'cells' / cell_id
    (cell_dir / 'inflight').mkdir(parents=True, exist_ok=True)
    spec = run.spec_by_id(cell_id)
    marker = {'call_id': f'{cell_id}.{batch}.t0', 'cell': cell_id, 'backend': spec['backend'],
              'workload': spec['workload'], 'wave': spec['wave'], 'arm': spec['arm'],
              'allocation': spec['allocation'], 'batch': batch, 'try': 0, 'reason': 'nominal', 'kind': 'nominal',
              'slot': slot, 'mode': 'fake', 'group': 'dead.g1', 'marker': 'call', 'role': role,
              'prepared_sha': prepared, 'pid': pid, 'started_at': '2026-10-24T00:00:00Z', 'job_ids': [],
              'records': {}}
    (cell_dir / 'inflight' / f"{marker['call_id']}.json").write_text(json.dumps(marker), encoding='utf-8')
    return marker


def killed_call_with_refresh(tmp_path, slot, marker_text):
    """A worker home as a killed call leaves it: prepared from the baseline, then its auth.json refreshed."""
    base = tmp_path / 'baseline'
    prepared = sha(base / 'auth.json')
    home = tmp_path / 'run' / 'homes' / f'worker-{slot}'
    home.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(base / 'auth.json', home / 'auth.json')
    write_auth(home, marker_text)
    (home / 'state.sqlite').write_text('runtime', encoding='utf-8')
    return prepared, sha(home / 'auth.json')


def test_item3_one_refreshed_worker_of_a_killed_call_is_propagated_on_resume(tmp_path):
    fake_opts(tmp_path)
    prepared, refreshed = killed_call_with_refresh(tmp_path, 1, 'KILLED-CALL')
    orphan_marker(tmp_path, 'codex-materials-cold-A', 1, prepared, pid=999999)
    assert go(tmp_path, 'codex-materials-cold-A') == 0
    assert sha(tmp_path / 'baseline' / 'auth.json') == refreshed, 'the refreshed token was destroyed, not propagated'
    rows = attempts(tmp_path / 'run', 'codex-materials-cold-A')
    assert [r['outcome'] for r in rows if r['batch'] == 'r1.b01'] == ['interrupted', 'ok']
    assert not (tmp_path / 'run' / 'codex-stop.json').exists()


def test_item3_two_changed_workers_of_killed_calls_stop_codex_and_keep_the_baseline(tmp_path):
    fake_opts(tmp_path)
    before = sha(tmp_path / 'baseline' / 'auth.json')
    p1, _ = killed_call_with_refresh(tmp_path, 1, 'KILLED-1')
    p2, _ = killed_call_with_refresh(tmp_path, 2, 'KILLED-2')
    orphan_marker(tmp_path, 'codex-materials-cold-A', 1, p1, pid=999998, batch='r1.b01')
    orphan_marker(tmp_path, 'codex-materials-cold-A', 2, p2, pid=999997, batch='r1.b02')
    assert go(tmp_path, 'codex-materials-cold-A') == config.EXIT_AUTH_STOP
    assert (tmp_path / 'run' / 'codex-stop.json').exists()
    assert sha(tmp_path / 'baseline' / 'auth.json') == before
    assert len(attempts(tmp_path / 'run')) == 2 and all(r['outcome'] == 'interrupted'
                                                        for r in attempts(tmp_path / 'run'))


def test_item3_a_recorded_child_still_running_stops_the_resume_without_touching_anything(tmp_path):
    fake_opts(tmp_path)
    prepared, refreshed = killed_call_with_refresh(tmp_path, 1, 'STILL-RUNNING')
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        orphan_marker(tmp_path, 'codex-materials-cold-A', 1, prepared, pid=child.pid)
        assert go(tmp_path, 'codex-materials-cold-A') == config.EXIT_INTERRUPTED
        home = tmp_path / 'run' / 'homes' / 'worker-1'
        assert sha(home / 'auth.json') == refreshed and (home / 'state.sqlite').exists()
        assert list((tmp_path / 'run' / 'cells' / 'codex-materials-cold-A' / 'inflight').glob('*.json'))
        assert attempts(tmp_path / 'run') == []
    finally:
        child.kill()
        child.wait()
    assert go(tmp_path, 'codex-materials-cold-A') == 0
    assert sha(tmp_path / 'baseline' / 'auth.json') == refreshed


def test_item3_a_crash_just_before_reconciliation_is_reconciled_on_resume(tmp_path, monkeypatch):
    original = run.CellRun.reconcile
    state = {'n': 0}

    def crash(self, workers):
        state['n'] += 1
        if state['n'] == 1:
            raise KeyboardInterrupt('runner killed just before reconciliation')
        return original(self, workers)

    monkeypatch.setattr(run.CellRun, 'reconcile', crash)
    with pytest.raises(KeyboardInterrupt):
        go(tmp_path, 'codex-materials-cold-A', fake_refresh=1)
    markers = list((tmp_path / 'run' / 'cells' / 'codex-materials-cold-A' / 'inflight').glob('*.json'))
    assert markers, 'markers stay until the reconciliation is done'
    before = sha(tmp_path / 'baseline' / 'auth.json')
    assert go(tmp_path, 'codex-materials-cold-A') == 0
    after = (tmp_path / 'baseline' / 'auth.json').read_bytes()
    assert sha(tmp_path / 'baseline' / 'auth.json') != before and b'SECRET-FAKE-REFRESHED' in after
    assert len({r['call_id'] for r in attempts(tmp_path / 'run')}) == len(attempts(tmp_path / 'run'))


def test_item3_a_marker_without_pid_on_a_started_home_is_ambiguous_and_stops_codex(tmp_path):
    fake_opts(tmp_path)
    prepared, _ = killed_call_with_refresh(tmp_path, 1, 'NO-PID')
    orphan_marker(tmp_path, 'codex-materials-cold-A', 1, prepared, pid=None)
    assert go(tmp_path, 'codex-materials-cold-A') == config.EXIT_AUTH_STOP
    assert 'ambiguous' in json.loads((tmp_path / 'run' / 'codex-stop.json').read_text(encoding='utf-8'))['reason']


# ======================================================================== item 4, B4: telemetry lifecycle

def test_item4_a_failed_telemetry_attempt_blocks_evaluation_even_after_a_passing_retry(live):
    live.mutate = lambda raw, env, cwd, launch: dict(raw, stdout=raw['stdout'] + json.dumps(
        {'type': 'item.completed', 'item': {'id': 'e', 'type': 'error', 'message': 'surprise'}}) + '\n') \
        if (Path(env['CODEX_HOME']) / 'auth.json').exists() else raw
    assert live.telemetry() == config.EXIT_TELEMETRY
    live.mutate = None
    assert live.telemetry() == config.EXIT_TELEMETRY, 'a retry after a failure is refused'
    assert live.cell('codex-materials-cold-A') == config.EXIT_TELEMETRY
    assert attempts(live.run_dir, 'codex-materials-cold-A') == []


def test_item4_telemetry_auth_failure_with_changed_credentials_stops_codex_without_propagating(live):
    before = sha(live.base / 'auth.json')

    def mutate(raw, env, cwd, launch):
        home = Path(env['CODEX_HOME'])
        if (home / 'auth.json').exists():
            write_auth(home, 'CHANGED-ON-AUTH-FAILURE')
            return dict(raw, stdout=stream({'type': 'turn.started'}, {'type': 'turn.failed', 'error': {
                'message': 'Your access token could not be refreshed. Please log out and sign in again.'}}),
                exit_code=1)
        return raw
    live.mutate = mutate
    assert live.telemetry() in (config.EXIT_AUTH_STOP, config.EXIT_TELEMETRY)
    assert (live.run_dir / 'codex-stop.json').exists()
    assert sha(live.base / 'auth.json') == before
    assert live.cell('codex-materials-cold-A') == config.EXIT_AUTH_STOP


def test_item4_forced_propagation_failure_leaves_no_certificate(live, monkeypatch):
    def mutate(raw, env, cwd, launch):
        home = Path(env['CODEX_HOME'])
        if (home / 'auth.json').exists():
            write_auth(home, 'REFRESHED-DURING-TELEMETRY')
        return raw
    live.mutate = mutate

    def refuse(self, slot, lock_timeout=30.0, expected_baseline_sha256=None):
        raise isolation.StaleAuth('forced propagation failure')
    monkeypatch.setattr(isolation.Isolation, 'propagate', refuse)
    assert live.telemetry() != 0
    rows = run.jsonl(live.run_dir / 'evidence' / 'telemetry.jsonl')
    assert rows and not any(r['passed'] for r in rows)
    assert (live.run_dir / 'codex-stop.json').exists()


def test_item4_a_crash_during_the_telemetry_call_keeps_it_charged_and_blocks_evaluation(live, monkeypatch):
    original = run.TelemetryRun.after_group
    state = {'n': 0}

    def crash(self, group):
        state['n'] += 1
        if state['n'] == 2:
            raise KeyboardInterrupt('runner killed during the telemetry call')
        return original(self, group)

    monkeypatch.setattr(run.TelemetryRun, 'after_group', crash)
    with pytest.raises(KeyboardInterrupt):
        live.telemetry()
    monkeypatch.setattr(run.TelemetryRun, 'after_group', original)
    assert live.cell('codex-materials-cold-A') == config.EXIT_TELEMETRY
    tel = attempts(live.run_dir, 'telemetry')
    # council round 2 (item 3, B3): the dead runner's call is judged from its raw stream, never lost as interrupted
    assert [a['outcome'] for a in tel] == ['auth_failure', 'ok'] and tel[1]['recovered_from'] == 'raw_stream'
    assert len(run.jsonl(live.ledger)) == 2


def test_b4_the_scorer_keeps_telemetry_out_of_evaluation_leakage(live):
    assert live.telemetry() == 0
    path = live.run_dir / 'attempts.jsonl'
    rows = run.jsonl(path)
    rows[-1]['events']['verdict'] = 'uncertain'
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    rep = score.score_run(live.run_dir)
    assert rep['validity']['leakage'] == []
    assert len(rep['telemetry']['calls']) == 2


# ============================================================ item 5, B1, RT1.4: authentication failure detection

def test_b1_the_real_401_capture_is_an_authentication_failure():
    out = (HERE / 'fixtures' / 'exec-noauth2.out').read_text(encoding='utf-8')
    raw = {'stdout': out, 'stderr': '', 'exit_code': 1, 'timed_out': False}
    assert run.judge_codex(raw)[0] == 'auth_failure'
    assert events.classify_stream(out)['verdict'] == 'uncertain', 'without a signed ruling the stream stays uncertain'


@pytest.mark.parametrize('timed_out', [True, False])
@pytest.mark.parametrize('extra', ['uncertain', 'plain'])
def test_item5_auth_failure_is_detected_whatever_the_timeout_or_event_verdict(timed_out, extra):
    evts = [{'type': 'turn.started'}, {'type': 'error', 'message': 'unexpected status 401 Unauthorized: Missing bearer'}]
    if extra == 'uncertain':
        evts.append({'type': 'item.started', 'item': {'id': 'c', 'type': 'command_execution', 'status': 'in_progress'}})
    raw = {'stdout': stream(*evts), 'stderr': '', 'exit_code': None if timed_out else 1, 'timed_out': timed_out}
    assert run.judge_codex(raw)[0] == 'auth_failure'


def test_b1_a_cell_meeting_the_real_401_stream_stops_codex(tmp_path, monkeypatch):
    out = (HERE / 'fixtures' / 'exec-noauth2.out').read_text(encoding='utf-8')
    original = run.spawn

    def spawn(*a, **k):
        raw = original(*a, **k)
        return dict(raw, stdout=out, exit_code=1)
    monkeypatch.setattr(run, 'spawn', spawn)
    assert go(tmp_path, 'codex-materials-cold-A') == config.EXIT_AUTH_STOP
    assert (tmp_path / 'run' / 'codex-stop.json').exists()
    assert all(r['outcome'] == 'auth_failure' for r in attempts(tmp_path / 'run'))
    assert len(attempts(tmp_path / 'run')) == 4, 'no retry of an authentication failure'


def test_b1_a_signed_transport_notice_would_be_a_transport_event(monkeypatch):
    """P1 (council round 2): a signed transport notice matches its complete message exactly; a prefix never does."""
    out = (HERE / 'fixtures' / 'exec-noauth2.out').read_text(encoding='utf-8')
    monkeypatch.setattr(config, 'SIGNED_TRANSPORT_NOTICES', ('Falling back from WebSockets to HTTPS transport.',
                                                             'Reconnecting... ', 'unexpected status 401'))
    assert events.classify_stream(out)['verdict'] == 'uncertain', 'prefixes are never a transport exception'
    messages = tuple(events.error_messages(out))
    monkeypatch.setattr(config, 'SIGNED_TRANSPORT_NOTICES', messages)
    cls = events.classify_stream(out)
    assert cls['verdict'] == 'plain' and cls['transport_notices']


def test_item5_propagation_against_a_reseeded_baseline_is_refused_and_keeps_the_newer_baseline(tmp_path):
    base = tmp_path / 'baseline'
    run.synthetic_baseline(base)
    iso = isolation.Isolation(base, tmp_path / 'run', tmp_path / 'ev')
    prepared = iso.prepare(0)
    write_auth(Path(prepared['home']), 'WORKER-REFRESH')
    write_auth(base, 'OWNER-RESEED')  # the owner reseeds while the call runs
    reseeded = sha(base / 'auth.json')
    fin = iso.finish(0, prepared_sha256=prepared['auth_sha256'])
    verdict = isolation.reconcile_generations(iso.baseline_sha256(), {0: {
        'sha256': fin['worker_auth_sha256'], 'prepared': prepared['auth_sha256'], 'auth_failure': False}})
    assert verdict['action'] == 'stop_codex' and 'baseline changed' in verdict['reason']
    with pytest.raises(isolation.StaleAuth):
        iso.propagate(0, expected_baseline_sha256=prepared['auth_sha256'])
    assert sha(base / 'auth.json') == reseeded


def test_item5_an_unchanged_worker_after_a_reseed_is_not_a_change():
    v = isolation.reconcile_generations('new', {0: {'sha256': 'old', 'prepared': 'old', 'auth_failure': False}})
    assert v['action'] == 'continue'
    v = isolation.reconcile_generations('base', {0: {'sha256': 'base', 'prepared': 'base', 'auth_failure': True}})
    assert v['action'] == 'stop_codex'


# =========================================================================== item 6: secrets never leave homes

def test_item6_auth_sentinels_in_stdout_stderr_and_error_fields_never_reach_an_artifact(tmp_path, monkeypatch):
    original = run.spawn

    def spawn(run_dir, launch, stdin_text, env, cwd, external, timeout=config.CALL_TIMEOUT_S):
        raw = original(run_dir, launch, stdin_text, env, cwd, external, timeout)
        doc = json.loads((Path(env['CODEX_HOME']) / 'auth.json').read_text(encoding='utf-8'))
        access, refresh = doc['tokens']['access_token'], doc['tokens']['refresh_token']
        extra = json.dumps({'type': 'item.completed', 'item': {'id': 'e', 'type': 'error',
                                                               'message': f'leak {access} {refresh}'}})
        return dict(raw, stdout=raw['stdout'] + extra + '\n', stderr=raw['stderr'] + f' token={access} rt={refresh}')

    monkeypatch.setattr(run, 'spawn', spawn)
    base = tmp_path / 'baseline'
    write_auth(base, 'SENTINEL-ACCESS-7')
    doc = json.loads((base / 'auth.json').read_text(encoding='utf-8'))
    secrets = [doc['tokens']['access_token'], doc['tokens']['refresh_token']]
    go(tmp_path, 'codex-materials-cold-A')
    run_dir = tmp_path / 'run'
    for p in run_dir.rglob('*'):
        if p.is_file() and not any(part in ('homes', 'auth') for part in p.relative_to(run_dir).parts):
            text = p.read_bytes().decode('utf-8', 'replace')
            for s in secrets:
                assert s not in text, f'credential material in {p}'
    rows = attempts(run_dir)
    assert rows and all(r['credential_disclosure'] for r in rows)
    rep = score.score_run(run_dir)
    assert rep['validity']['isolation'] == 'failed'


def test_item6_redaction_keeps_a_hash_record():
    text, rec = redact.redact('a eyJhbGciOiJub25lIn0.eyJleHAiOjF9.c2ln b', set())
    assert 'eyJ' not in text and rec['redactions'] == 1 and len(rec['original_sha256']) == 64


# =============================================================== item 7: executable and instruction checks

def test_item7_a_swapped_executable_between_launch_groups_stops_before_the_next_spawn(tmp_path, monkeypatch):
    original = run.CellRun.after_group

    def swap(self, group):
        original(self, group)
        exe = Path(self.exe.exe)
        exe.write_text(exe.read_text(encoding='utf-8') + '\n# swapped\n', encoding='utf-8')

    monkeypatch.setattr(run.CellRun, 'after_group', swap)
    assert go(tmp_path, 'codex-materials-cold-A', fake_fail=1) == config.EXIT_FREEZE
    assert len(attempts(tmp_path / 'run')) == 4, 'the retry group was never spawned'


def test_item7_a_changed_launcher_payload_stops_the_launch(tmp_path, monkeypatch):
    original = run.CellRun.after_group

    def payload(self, group):
        original(self, group)
        (Path(self.exe.exe).parent / 'codex-code-mode-host.bin').write_bytes(os.urandom(16))

    monkeypatch.setattr(run.CellRun, 'after_group', payload)
    assert go(tmp_path, 'codex-materials-cold-A', fake_fail=1) == config.EXIT_FREEZE


def test_item7_an_unreadable_ancestor_fails_closed(tmp_path, monkeypatch):
    work = tmp_path / 'a' / 'b' / 'slot-0'
    work.mkdir(parents=True)
    denied = (tmp_path / 'a' / 'AGENTS.md')
    real_stat = os.stat

    def stat(p, *a, **k):
        if Path(p) == denied:
            raise PermissionError(13, 'denied')
        return real_stat(p, *a, **k)

    monkeypatch.setattr(os, 'stat', stat)
    found, unreadable = isolation.instruction_scan(work)
    assert denied in unreadable and denied in isolation.instruction_sources(work)


def test_item7_env_values_that_select_config_sources_are_checked(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    env = isolation.child_env(home, {'PATH': os.environ.get('PATH', '')})
    assert isolation.env_selection_problems(env, home) == []
    env['HOME'] = str(Path.home())
    assert isolation.env_selection_problems(env, home)


# ========================================================================= item 8: every disable option is used

def test_item8_every_supported_required_disable_option_is_in_the_frozen_argv():
    doc = json.loads(config.CLI_FLAGS_FILE.read_text(encoding='utf-8'))
    args, unsupported = run.cli_flags()
    disabled = {args[i + 1] for i, a in enumerate(args[:-1]) if a == '--disable'}
    for name in config.DISABLE_FEATURES:
        if name in doc['supported']:
            assert name in disabled or name in config.SIGNED_OMITTED_DISABLES, name
    assert 'code_mode_host' in disabled
    assert not set(config.SIGNED_OMITTED_DISABLES), 'no signed exception exists yet'


# ===================================================================== item 9, RT1.1, RT1.5: run identity and mode

def test_item9_mode_is_required_and_fake_refuses_the_live_dir_and_the_real_baseline(tmp_path):
    o = run.Options(tmp_path / 'r', mode=None, out=io.StringIO())
    assert run.CellRun(run.spec_by_id('codex-materials-cold-A'), o).run() == config.EXIT_USAGE
    o = run.Options(config.LIVE_RUN_DIR_DEFAULT, mode='fake', baseline=tmp_path / 'b', out=io.StringIO())
    assert run.mode_problem(o)
    o = run.Options(tmp_path / 'r', mode='fake', baseline=config.BASELINE_DEFAULT, out=io.StringIO())
    assert run.mode_problem(o)
    signed = tmp_path / 'signed'
    signed.mkdir()
    (signed / 'auth.json').write_text(json.dumps({'tokens': {'access_token': 'eyJhbGciOiJSUzI1NiJ9.e30.c2ln'}}),
                                      encoding='utf-8')
    assert run.mode_problem(run.Options(tmp_path / 'r', mode='fake', baseline=signed, out=io.StringIO()))
    assert all('--mode live' in s['live_command'] for s in run.cell_specs())


def test_item9_live_after_a_fake_bootstrap_and_a_mode_change_on_resume_fail_before_dispatch(live, tmp_path):
    fake = fake_opts(tmp_path, run_dir=live.run_dir)
    assert run.CellRun(run.spec_by_id('codex-materials-bootstrap'), fake).run() == config.EXIT_USAGE,         'fake mode refuses the live run directory'
    mixed = tmp_path / 'mixed'
    assert run.CellRun(run.spec_by_id('codex-materials-bootstrap'), fake_opts(tmp_path, run_dir=mixed)).run() == 0
    live.run_dir = mixed  # the frozen live run directory now holds a fake bootstrap
    assert live.cell('codex-materials-cold-C') == config.EXIT_IDENTITY
    assert live.telemetry() == config.EXIT_IDENTITY
    assert all(a['mode'] == 'fake' for a in attempts(mixed))


def test_item9_a_second_directory_for_the_same_experiment_fails_before_dispatch(live):
    assert live.telemetry() == 0
    other = live.tmp / 'second'
    code = run.CellRun(run.spec_by_id('sonnet-materials-cold-A'), live.opts(run_dir=other)).run()
    assert code == config.EXIT_IDENTITY and attempts(other) == []
    (live.run_dir / 'attempts.jsonl').unlink()  # an emptied run directory is detected through the ledger
    assert live.cell('sonnet-materials-cold-A') == config.EXIT_IDENTITY


def test_rt1_1_reports_distinguish_simulation_from_evaluation(tmp_path):
    assert go(tmp_path, 'codex-materials-cold-A') == 0
    rep = score.score_run(tmp_path / 'run')
    assert rep['mode'].startswith('simulation') and rep['validity']['simulation']


# ======================================================================= item 10: freeze binding, artifact chain

def scored_problems(run_dir):
    rep = score.score_run(run_dir)
    return rep, rep['validity']['artifact_problems']


def test_item10_the_artifact_chain_of_a_clean_run_verifies(tmp_path):
    assert go(tmp_path, 'codex-materials-cold-A') == 0
    assert scored_problems(tmp_path / 'run')[1] == []


@pytest.mark.parametrize('what', ['capture', 'answer', 'call', 'usage'])
def test_item10_altered_artifacts_are_detected_and_claims_withheld(tmp_path, what):
    assert go(tmp_path, 'codex-materials-cold-A') == 0
    run_dir = tmp_path / 'run'
    cid = attempts(run_dir)[0]['call_id']
    if what == 'capture':
        p = run_dir / 'captures' / f'{cid}.stdout'
        p.write_bytes(p.read_bytes().replace(b'OZ/1g', b'OZ/1h', 1))
    elif what == 'answer':
        p = run_dir / 'cells' / 'codex-materials-cold-A' / 'result.json'
        doc = json.loads(p.read_text(encoding='utf-8'))
        jid = next(iter(doc['answers']))
        doc['answers'][jid]['answer'] = 'tampered'
        p.write_text(json.dumps(doc), encoding='utf-8')
    elif what == 'call':
        p = run_dir / 'cells' / 'codex-materials-cold-A' / 'calls' / f'{cid}.json'
        doc = json.loads(p.read_text(encoding='utf-8'))
        doc['answers'][next(iter(doc['answers']))] = 'tampered'
        p.write_text(json.dumps(doc), encoding='utf-8')
    else:
        rows = run.jsonl(run_dir / 'attempts.jsonl')
        rows[0]['usage_raw']['input_tokens'] -= 1
        (run_dir / 'attempts.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    rep, problems = scored_problems(run_dir)
    assert problems
    assert gates.magnitude(dict(rep, validity=dict(rep['validity'], simulation=[])), 'codex')['status'] == 'invalid'


def test_item10_an_altered_admission_record_is_detected(tmp_path):
    assert go(tmp_path, 'codex-materials-bootstrap') == 0
    p = tmp_path / 'run' / 'cells' / 'codex-materials-bootstrap' / 'result.json'
    doc = json.loads(p.read_text(encoding='utf-8'))
    doc['rules']['temp_class'] = {'proposed': True, 'ast_b64': base64.b64encode(UNKNOWN_ONLY).decode(),
                                  'ast_sha256': 'x', 'bytes': len(UNKNOWN_ONLY),
                                  'admission': {'status': 'accepted', 'reasons': []}}
    p.write_text(json.dumps(doc), encoding='utf-8')
    problems = scored_problems(tmp_path / 'run')[1]
    assert any('admission record' in x or 'bootstrap capture holds' in x for x in problems)


def test_item10_a_frozen_input_changed_after_binding_is_detected(live, monkeypatch):
    assert live.telemetry() == 0
    bound = json.loads((live.run_dir / 'experiment.json').read_text(encoding='utf-8'))
    freeze = {'files': {'bench/ozmap_rep/ops/oracle.py': '0' * 64}, 'classification_sha256': 'x'}
    (live.run_dir / 'freeze.json').write_text(json.dumps(freeze), encoding='utf-8')
    bound['freeze_sha256'] = sha(live.run_dir / 'freeze.json')
    (live.run_dir / 'experiment.json').write_text(json.dumps(bound), encoding='utf-8')
    rep = score.score_run(live.run_dir)
    assert any('oracle.py' in p for p in rep['validity']['freeze_problems'])


def test_item10_the_freeze_cannot_be_replaced_after_dispatch(tmp_path, monkeypatch):
    bound = tmp_path / 'live'
    bound.mkdir()
    (bound / 'experiment.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(run, 'live_run_dir', lambda: bound)
    written = []
    monkeypatch.setattr(run, '_write_json', lambda path, obj: written.append(path))
    assert run.freeze_command() == config.EXIT_FREEZE and written == []


def test_item10_the_freeze_covers_the_harness_tests_and_the_certificate_envelopes():
    names = run._freeze_files()
    assert 'bench/ozmap_rep/tests/test_council_r1.py' in names and 'bench/ozmap_rep/tests/test_rule_path.py' in names
    assert 'bench/ozmap_rep/redteam/test_redteam_r1.py' in names
    assert any(n.endswith('telemetry-1/captures/1.envelope') for n in names)


# ======================================================================= item 11, RT1.3: monotonic tool evidence

def tool(id_, status, **kw):
    item = {'type': 'command_execution', 'status': status, **kw}
    if id_ is not None:
        item['id'] = id_
    return item


@pytest.mark.parametrize('evts,want', [
    ([('item.completed', tool('c', 'completed', exit_code=0)), ('item.updated', tool('c', 'declined'))], 'executed'),
    ([('item.started', tool(None, 'in_progress')), ('item.completed', tool(None, 'declined'))], 'uncertain'),
    ([('item.completed', tool('', 'declined'))], 'uncertain'),
    ([('item.completed', tool('c', 'declined')),
      ('item.completed', {'id': 'c', 'type': 'file_change', 'status': 'declined'})], 'uncertain'),
])
def test_item11_execution_evidence_is_sticky_and_ambiguous_ids_are_conservative(evts, want):
    out = stream(*[{'type': t, 'item': i} for t, i in evts])
    assert events.classify_stream(out)['verdict'] == want


def test_item11_an_unknown_top_level_error_is_never_plain():
    out = stream({'type': 'turn.started'}, {'type': 'error', 'message': 'something new'},
                 {'type': 'item.completed', 'item': {'id': 'm', 'type': 'agent_message', 'text': 'x'}})
    assert events.classify_stream(out)['verdict'] == 'uncertain'
    assert events.classify_stream('not json\n' + ok_stream())['verdict'] == 'uncertain'


# ====================================================================== item 13: retry only the infra predicate

@pytest.mark.parametrize('case', ['executed', 'refused', 'answer'])
@pytest.mark.parametrize('how', ['timeout', 'nonzero'])
def test_item13_timeout_or_nonzero_exit_never_makes_a_terminal_call_retryable(case, how):
    if case == 'executed':
        out = stream({'type': 'item.completed', 'item': tool('c', 'completed', exit_code=0)})
    elif case == 'refused':
        out = stream({'type': 'item.completed', 'item': tool('c', 'declined')})
    else:
        out = ok_stream()
    raw = {'stdout': out, 'stderr': '', 'exit_code': None if how == 'timeout' else 3, 'timed_out': how == 'timeout'}
    assert run.judge_codex(raw)[0] == {'executed': 'executed', 'refused': 'refused', 'answer': 'ok'}[case]
    envelope = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'OZ/1g', 'num_turns': 1, 'permission_denials': [],
                'modelUsage': {config.SONNET_MODEL: {'inputTokens': 1, 'outputTokens': 1, 'cacheReadInputTokens': 0,
                                     'cacheCreationInputTokens': 0}}}
    raw = {'stdout': json.dumps(envelope), 'stderr': '', 'exit_code': 1, 'timed_out': how == 'timeout'}
    assert run.judge_sonnet(raw)[0] == 'ok'


def test_item13_a_timed_out_call_with_a_delivered_reply_is_never_sent_again(tmp_path, monkeypatch):
    original = run.spawn
    monkeypatch.setattr(run, 'spawn', lambda *a, **k: dict(original(*a, **k), timed_out=True, exit_code=None))
    assert go(tmp_path, 'codex-materials-cold-A') == 0
    assert len(attempts(tmp_path / 'run')) == 4


# ========================================================================== item 14: makespan includes local work

def test_item14_local_processing_delays_reach_the_gated_makespan(tmp_path, monkeypatch):
    original = prompts.parse_answers

    def slow(reply, mapping):
        time.sleep(0.4)
        return original(reply, mapping)

    monkeypatch.setattr(prompts, 'parse_answers', slow)
    assert go(tmp_path, 'codex-materials-cold-A') == 0
    cell = score.score_run(tmp_path / 'run')['cells']['codex/materials/cold/A']
    assert cell['makespan_s'] >= cell['child_makespan_s'] + 4 * 0.4 - 0.05


# ===================================================================== item 15: bootstrap completion, settled cells

def test_item15_malformed_bootstrap_answers_are_a_completion_failure_and_proposals_stay_observations(tmp_path,
                                                                                                   monkeypatch):
    original = prompts.parse_bootstrap

    def bad(reply, ops):
        _, rules_ = original(reply, ops)
        entry = {'ast_b64': base64.b64encode(UNKNOWN_ONLY).decode(), 'ast_sha256': 'x', 'bytes': len(UNKNOWN_ONLY)}
        return 'not an OZ reply', dict(rules_, temp_class=entry)

    monkeypatch.setattr(prompts, 'parse_bootstrap', bad)
    assert go(tmp_path, 'codex-materials-bootstrap') == config.EXIT_INCOMPLETE
    cell = tmp_path / 'run' / 'cells' / 'codex-materials-bootstrap'
    assert (cell / 'SETTLED.json').exists() and not (cell / 'DONE.json').exists()
    res = json.loads((cell / 'result.json').read_text(encoding='utf-8'))
    assert res['status'] == 'malformed'
    assert res['rules']['temp_class']['admission']['status'] == 'not_evaluated'
    assert go(tmp_path, 'codex-materials-bootstrap') == config.EXIT_INCOMPLETE
    assert len(attempts(tmp_path / 'run')) == 1, 'a terminal outcome is never resent'
    assert go(tmp_path, 'codex-materials-cold-C') == config.EXIT_REQUIRES
    rep = score.score_run(tmp_path / 'run')
    assert rep['validity']['bootstrap']['codex/materials']['completion_failure'] is True


def test_item15_a_refused_batch_settles_the_cell_incomplete(tmp_path, monkeypatch):
    original = run.spawn
    calls = {'n': 0}

    def spawn(*a, **k):
        raw = original(*a, **k)
        calls['n'] += 1
        if calls['n'] == 1:
            return dict(raw, stdout=stream({'type': 'item.completed', 'item': tool('c', 'declined')}) + raw['stdout'])
        return raw
    monkeypatch.setattr(run, 'spawn', spawn)
    assert go(tmp_path, 'codex-materials-cold-A') == config.EXIT_INCOMPLETE
    cell = tmp_path / 'run' / 'cells' / 'codex-materials-cold-A'
    assert (cell / 'SETTLED.json').exists() and not (cell / 'DONE.json').exists()
    assert len(attempts(tmp_path / 'run')) == 4
    g = score.score_run(tmp_path / 'run')['cells']['codex/materials/cold/A']
    assert g['state'] != 'complete'


# ======================================================================== item 16: classification before launch

@pytest.mark.parametrize('change', ['missing_op', 'bad_field', 'bad_time', 'future'])
def test_item16_an_invalid_classification_stops_launch_and_blocks_claims(tmp_path, monkeypatch, change):
    doc = json.loads(config.CLASSIFICATION_FILE.read_text(encoding='utf-8'))
    if change == 'missing_op':
        doc['operations'].pop('elong')
    elif change == 'bad_field':
        doc['operations']['verdict']['rule_shaped'] = 'yes'
    elif change == 'bad_time':
        doc['classified_at'] = 'yesterday'
    else:
        doc['classified_at'] = '2999-01-01T00:00:00Z'
    path = tmp_path / 'classification.json'
    path.write_text(json.dumps(doc), encoding='utf-8')
    monkeypatch.setattr(config, 'CLASSIFICATION_FILE', path)
    R, problems = bootstrap.validate_classification()
    assert R is None and problems
    assert go(tmp_path, 'codex-materials-cold-A') == config.EXIT_CLASSIFICATION
    assert attempts(tmp_path / 'run') == []
    rep = score.score_run(tmp_path / 'run')
    assert rep['validity']['classification_problems'] and rep['R'] == []


def test_item16_a_valid_empty_R_is_not_an_invalid_classification(tmp_path):
    doc = json.loads(config.CLASSIFICATION_FILE.read_text(encoding='utf-8'))
    for e in doc['operations'].values():
        e['rule_shaped'] = False
    path = tmp_path / 'c.json'
    path.write_text(json.dumps(doc), encoding='utf-8')
    assert bootstrap.validate_classification(path) == (set(), [])


def test_item16_the_classification_hash_is_bound_to_the_freeze():
    import inspect
    assert 'bench/ozmap_rep/classification.json' in run._freeze_files()
    assert "'classification_sha256'" in inspect.getsource(run.verify_freeze)


# ===================================================================== item 17: unresolved audits are explicit

def test_item17_an_unanswered_audit_makes_the_comparison_inconclusive(tmp_path, monkeypatch):
    assert go(tmp_path, 'codex-materials-bootstrap') == 0
    p = tmp_path / 'run' / 'cells' / 'codex-materials-bootstrap' / 'result.json'
    doc = json.loads(p.read_text(encoding='utf-8'))
    doc['rules']['temp_class'] = {'proposed': True, 'ast_b64': base64.b64encode(UNKNOWN_ONLY).decode(),
                                  'ast_sha256': 't', 'bytes': 1, 'admission': {'status': 'accepted', 'reasons': []}}
    p.write_text(json.dumps(doc), encoding='utf-8')
    original = run.CellRun.run_batches

    def drop_audits(self, batches, round_no, **kw):
        out = original(self, batches, round_no, **kw)
        covered = [j['id'] for b in batches for j in b if j['op'] == 'temp_class']
        for res in out.values():
            for jid in list(res.get('answers') or {}):
                if jid in covered:
                    res['answers'].pop(jid)
        return out

    monkeypatch.setattr(run.CellRun, 'run_batches', drop_audits)
    assert go(tmp_path, 'codex-materials-cold-C') == 0
    res = json.loads((tmp_path / 'run' / 'cells' / 'codex-materials-cold-C' / 'result.json').read_text(
        encoding='utf-8'))
    assert res['unresolved_audits']
    cell = score.score_run(tmp_path / 'run')['cells']['codex/materials/cold/C']
    assert cell['unresolved_audits'] > 0
    s = {'cells': {'x': cell}}
    assert gates._incomplete(cell)
    del s


# ======================================================================== item 18, B2: validity before magnitude

def passing_r():
    sys.path.insert(0, str(HERE.parent / 'acceptance'))
    import ozrep_helpers
    s = ozrep_helpers.passing_summary()
    base = {'jobs': 100, 'unresolved': 0, 'usage': 'complete', 'state': 'complete', 'evidence': 'complete'}
    s['R_cells']['codex/warm/A'] = dict(base, correct=100, tokens=440000, makespan_s=160.0)
    s['R_cells']['codex/warm/C'] = dict(base, correct=100, tokens=100000, makespan_s=100.0)
    return s


@pytest.mark.parametrize('inject', ['isolation', 'bootstrap', 'rule_error', 'simulation', 'artifact'])
def test_b2_no_positive_magnitude_survives_an_invalid_prerequisite(inject):
    s = passing_r()
    assert gates.magnitude(s, 'codex')['status'] == 'pass'
    if inject == 'isolation':
        s['validity']['isolation'] = 'failed'
    elif inject == 'bootstrap':
        s['validity']['bootstrap']['codex/materials']['efficiency_valid'] = False
    elif inject == 'rule_error':
        s['cells']['codex/materials/warm/C']['rule_errors'] = 3
    elif inject == 'simulation':
        s['validity']['simulation'] = ['fake']
    else:
        s['validity']['artifact_problems'] = ['x']
    m = gates.magnitude(s, 'codex')
    assert m['status'] == 'invalid' and m['label'] is None and not m['direction_replicated']


def test_item18_boolq_and_pooling_gates_respect_the_safety_kill():
    s = passing_r()
    assert gates.boolq_gate(s)['pass'] and gates.pooling_gate(s)['pass']
    s['cells']['sonnet/materials/warm/C']['rule_errors'] = 1
    assert not gates.boolq_gate(s)['pass'] and not gates.pooling_gate(s)['pass']


def test_item18_an_established_safety_kill_blocks_every_later_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(run.CellRun, 'rule_errors', lambda self, result: ['j-wrong'])
    assert go(tmp_path, 'codex-materials-cold-A') == config.EXIT_SAFETY_KILL
    assert (tmp_path / 'run' / 'safety-kill.json').exists()
    monkeypatch.undo()
    n = len(attempts(tmp_path / 'run'))
    for cid in ('sonnet-materials-cold-A', 'codex-boolq-cold-A'):
        assert go(tmp_path, cid) == config.EXIT_SAFETY_KILL
    assert len(attempts(tmp_path / 'run')) == n


# =============================================================================== item 19: certificate authority

def cert_copy(tmp_path, mutate):
    repo = tmp_path / 'repo'
    doc = json.loads(config.CERTIFICATE_FILE.read_text(encoding='utf-8'))
    for src in doc['sources']:
        dst = repo / src['envelope']
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(config.REPO / src['envelope'], dst)
    mutate(doc, repo)
    path = tmp_path / 'cert.json'
    path.write_text(json.dumps(doc), encoding='utf-8')
    return path, repo


def test_item19_the_archived_certificate_verifies_against_its_sources():
    assert usage.certificate_authority() == [] and usage.cache_certified_for_route() is True


@pytest.mark.parametrize('how', ['missing', 'altered', 'trace', 'pair'])
def test_item19_a_broken_source_or_a_substituted_pair_leaves_positive_cache_unverified(tmp_path, how):
    def mutate(doc, repo):
        env = repo / doc['sources'][0]['envelope']
        if how == 'missing':
            env.unlink()
        elif how == 'altered':
            env.write_bytes(env.read_bytes().replace(b'29694', b'29695', 1))
        elif how == 'trace':
            doc['decoder_trace']['capture_decoder_sha256'] = '0' * 64
        else:
            doc['calls'] = [{'input': 50000, 'cached': 100}, {'input': 50000, 'cached': 0}]
    path, repo = cert_copy(tmp_path, mutate)
    assert usage.certificate_authority(path, repo)
    raw = {'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 5, 'reasoning_output_tokens': 0}
    certified = not usage.certificate_authority(path, repo)
    assert usage.decode_codex(raw, cache_certified=certified)['status'] == 'unverified'
    zero = dict(raw, cached_input_tokens=0)
    assert usage.decode_codex(zero, cache_certified=certified)['status'] == 'complete'


# ================================================================================ item 23: the amendment chain

def test_item23_caps_follow_the_signed_a4_13_text():
    text = (config.REPO / 'docs' / 'design' / 'ozmap-replication-2026-10-24' / 'amendment-4-13-caps.md').read_text(
        encoding='utf-8')
    assert 'Astra 20, Opus 40, Fable 4 and Sonnet 40' in text and 'The global cap is 206' in text
    assert 'Signed: Astra A' in text and 'Signed: Opus B' in text
    assert config.PREP_CAPS == {'astra': 20, 'opus': 40, 'fable': 4, 'sonnet': 40} and config.GLOBAL_CAP == 206
    assert 'Codex 62 and Sonnet evaluation 40' in text
    assert config.EVAL_CAPS['codex']['total'] == 62 and config.EVAL_CAPS['sonnet']['total'] == 40


# ========================================================================= changes: C4, C7, C21, quota readings

def test_c4_a_stale_codex_reading_after_live_calls_refuses_the_next_codex_cell(live):
    assert live.telemetry() == 0
    path = next(live.sessions.rglob('*.jsonl'))
    old = time.time() - 3600
    os.utime(path, (old, old))
    code = run.CellRun(run.spec_by_id('codex-materials-cold-A'), live.opts()).run()
    assert code == config.EXIT_QUOTA


def test_c7_positive_cache_write_counter_is_unverified(tmp_path, monkeypatch):
    original = run.spawn

    def spawn(*a, **k):
        raw = original(*a, **k)
        return dict(raw, stdout=raw['stdout'].replace('"reasoning_output_tokens"',
                                                      '"cache_write_input_tokens": 5, "reasoning_output_tokens"'))
    monkeypatch.setattr(run, 'spawn', spawn)
    assert go(tmp_path, 'codex-materials-cold-A') == 0
    assert all(a['usage_status'] == 'unverified' for a in attempts(tmp_path / 'run'))


def test_c21_known_violations_survive_a_missing_counter():
    out = usage.decode_codex_checked({'input_tokens': 10, 'cached_input_tokens': 11, 'output_tokens': 3})
    assert out['status'] == 'invalid'
    out = usage.decode_codex_checked({'input_tokens': 10, 'cached_input_tokens': 1, 'output_tokens': 3})
    assert out['status'] == 'incomplete'


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 'x', -1])
def test_c22_nonfinite_or_malformed_quota_readings_stop(value):
    assert quota.claude_gate(value)['ok'] is False


# ========================================================================= end to end: a live cell after telemetry

def test_live_cell_after_a_certified_telemetry_completes_and_scores_as_evaluation(live):
    assert live.telemetry() == 0
    assert live.cell('codex-materials-cold-A') == 0
    rep = score.score_run(live.run_dir)
    assert rep['mode'] == 'evaluation' and rep['validity']['simulation'] == []
    assert rep['validity']['artifact_problems'] == []
    assert len(run.jsonl(live.ledger)) == 2 + 4
