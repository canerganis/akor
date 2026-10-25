"""Closure round 1 (A4.14.3) regressions for the blockers of closure-astra-r1.md (O1 to O5, N1),
closure-opus-r1.md (N1) and closure-redteam-r1.md (RTC1.1, RTC1.2).

Fakes and temporary directories only: no real `codex` or `claude` is resolved or spawned (live mode runs the harness'
own fakes through the real lifecycle code, as in tests/test_council_r1.Live), no real baseline, run directory,
experiment ledger or Codex session directory is written, and the sealed reviewer ASTs are never touched.
"""
import base64
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys

import pytest

from bench.ozmap_rep import config, isolation, rulings, run, score, usage
from bench.ozmap_rep.tests.test_council_r1 import Live, attempts, go, write_d6_annexes

CELL = 'codex-materials-cold-A'


@pytest.fixture
def live(tmp_path, monkeypatch):
    return Live(tmp_path, monkeypatch)


def _secret(env):
    doc = json.loads((Path(env['CODEX_HOME']) / 'auth.json').read_text(encoding='utf-8'))
    return doc['tokens']['access_token']


# ============================================================================ O1: an ordinary timeout

def _hang_after_turn_started(target='r1.b01.t0'):
    """A spawn wrapper: the target call emits only thread.started and turn.started, then hangs until the harness
    timeout kills its tree (spawn returns timed_out, no exit code)."""
    original = run.spawn

    def spawn(run_dir, launch, stdin_text, env, cwd, external, timeout=config.CALL_TIMEOUT_S):
        raw = original(run_dir, launch, stdin_text, env, cwd, external, timeout)
        directive = json.loads((Path(run_dir) / 'fake' / 'directives' / f'{Path(cwd).name}.json')
                               .read_text(encoding='utf-8'))
        if directive['call_id'].endswith(target):
            lines = raw['stdout'].splitlines()[:2]
            raw = dict(raw, stdout='\n'.join(lines) + '\n', exit_code=None, timed_out=True)
            if getattr(run._TLS, 'raw', None):
                Path(run._TLS.raw[0]).write_bytes(raw['stdout'].encode('utf-8'))
        return raw
    return spawn


def test_o1_a_timed_out_child_without_terminal_evidence_is_unsettled_never_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(run, 'spawn', _hang_after_turn_started())
    code = go(tmp_path, CELL)
    assert code == config.EXIT_AUTH_STOP, 'Codex stops: the timed out call did not settle normally'
    rows = attempts(tmp_path / 'run', CELL)
    hung = [r for r in rows if r['call_id'].endswith('r1.b01.t0')]
    assert len(hung) == 1 and hung[0]['outcome'] == 'unsettled', [(r['call_id'], r['outcome']) for r in rows]
    assert hung[0]['events']['verdict'] == 'uncertain'
    assert not [r for r in rows if r['call_id'].endswith('r1.b01.t1')], 'never retried from the reserve'
    rep = score.score_run(tmp_path / 'run')
    assert CELL in rep['validity']['invalid_cells'] and CELL not in rep['validity']['interrupted']
    assert rep['cell_states'][CELL] == 'invalid'
    assert not [p for p in rep['validity']['artifact_problems'] if hung[0]['call_id'] in p]


def test_o1_a_timed_out_child_that_delivered_its_reply_keeps_its_outcome(tmp_path, monkeypatch):
    original = run.spawn
    monkeypatch.setattr(run, 'spawn', lambda *a, **k: dict(original(*a, **k), timed_out=True, exit_code=None))
    assert go(tmp_path, CELL) == 0
    rows = attempts(tmp_path / 'run', CELL)
    assert rows and all(r['outcome'] == 'ok' for r in rows)


# ============================================================================ O2: guarded local probes

def test_o2_every_local_probe_runs_under_the_guarded_identity_check(live, monkeypatch):
    events_ = []
    original_guard = run.Executables.verified_guard
    original_local = run.run_local

    def guard(self, live):
        events_.append('verified')
        g = original_guard(self, live)
        exit_ = g.__exit__

        def leave(*exc):
            events_.append('released')
            return exit_(*exc)
        g.__exit__ = leave
        return g

    def local(argv, env, cwd, on_start=None, timeout=120):
        events_.append('probe')
        return original_local(argv, env, cwd, on_start, timeout)
    monkeypatch.setattr(run.Executables, 'verified_guard', guard)
    monkeypatch.setattr(run, 'run_local', local)
    assert live.telemetry() == 0
    assert live.cell(CELL) == 0
    depth, seen = 0, 0
    for e in events_:
        depth += {'verified': 1, 'released': -1}.get(e, 0)
        if e == 'probe':
            seen += 1
            assert depth >= 1, f'a local probe ran outside the guarded identity check: {events_}'
    assert seen >= 2 + config.SLOTS and depth == 0


def test_o2_a_manifest_changed_after_the_group_check_refuses_the_probe_before_it_runs(live, monkeypatch):
    assert live.telemetry() == 0
    original_local = run.run_local
    ran = []
    monkeypatch.setattr(run.Executables, 'recheck', lambda self: ['an executable manifest file changed after the '
                                                                   'launch group was verified'])
    monkeypatch.setattr(run, 'run_local', lambda *a, **k: ran.append(a) or original_local(*a, **k))
    assert live.cell(CELL) == config.EXIT_FREEZE
    assert ran == [], 'the features probe never started'
    assert not list((live.run_dir / 'cells' / CELL / 'inflight').glob('*.json')), 'no marker of a probe never run'


# ============================================================================ O3: probe output survives a failure

def test_o3_run_local_keeps_the_output_a_probe_emitted_before_waiting_failed(tmp_path, monkeypatch):
    raw = (tmp_path / 'homes' / 'raw-0' / 'p.stdout', tmp_path / 'homes' / 'raw-0' / 'p.stderr')
    original = subprocess.Popen.communicate

    def communicate(self, *a, **k):
        if k.get('timeout') is not None:
            import time
            time.sleep(1.5)
            raise RuntimeError('waiting failed')
        return original(self, *a, **k)
    monkeypatch.setattr(subprocess.Popen, 'communicate', communicate)
    run._TLS.probe_raw = tuple(str(p) for p in raw)
    try:
        with pytest.raises(run.SpawnFailure) as info:
            run.run_local([sys.executable, '-c', 'import sys, time; print("bearer SECRET-PROBE-TOKEN", flush=True); '
                                                 'sys.stderr.write("auth error\\n"); sys.stderr.flush(); time.sleep(30)'],
                          None, tmp_path)
    finally:
        run._TLS.probe_raw = None
    exc = info.value
    assert exc.terminated and not exc.never_ran
    assert exc.raw and 'SECRET-PROBE-TOKEN' in exc.raw[0] and 'auth error' in exc.raw[1]
    assert raw[0].exists(), 'the raw stream stays inside the credential boundary'


def _failing_probe(terminated, leak=True):
    def local(argv, env, cwd, on_start=None, timeout=120):
        if 'features' not in argv:
            return run_local_original(argv, env, cwd, on_start, timeout)
        text = ('bearer ' + _secret(env) + '\n') if leak else 'partial\n'
        paths = getattr(run._TLS, 'probe_raw', None)
        assert paths, 'the probe streams go to files inside the credential boundary'
        Path(paths[0]).parent.mkdir(parents=True, exist_ok=True)
        Path(paths[0]).write_text(text, encoding='utf-8')
        Path(paths[1]).write_text('', encoding='utf-8')
        raise run.SpawnFailure('waiting for the probe raised RuntimeError', terminated, 4242,
                               (text, '') if terminated else None)
    run_local_original = run.run_local
    return local


@pytest.mark.parametrize('terminated', [True, False])
def test_o3_a_probe_that_did_not_settle_leaves_its_evidence_and_makes_the_cell_invalid(live, monkeypatch,
                                                                                    terminated):
    assert live.telemetry() == 0
    monkeypatch.setattr(run, 'run_local', _failing_probe(terminated))
    assert live.cell(CELL) == config.EXIT_AUTH_STOP
    ev = live.run_dir / 'evidence'
    failures = run.jsonl(ev / 'probe-failures.jsonl')
    assert failures and failures[0]['cell'] == CELL and failures[0]['output_complete'] is terminated
    if terminated:
        rows = run.jsonl(ev / 'probe-disclosures.jsonl')
        assert rows and rows[0]['cell'] == CELL, 'the disclosure in the output of the failed probe is recorded'
        assert not run.jsonl(ev / 'probe-uncertain.jsonl')
    else:
        rows = run.jsonl(ev / 'probe-uncertain.jsonl')
        assert rows and rows[0]['cell'] == CELL, 'output completeness not established: an isolation uncertainty'
    assert run.telemetry_problems(live.run_dir)
    text = (ev / 'probe-failures.jsonl').read_text(encoding='utf-8')
    assert _secret({'CODEX_HOME': str(live.base)}) not in text, 'evidence holds hashes only'
    rep = score.score_run(live.run_dir)
    assert rep['validity']['isolation'] == 'failed'
    assert rep['cell_states'][CELL] == 'invalid'
    assert CELL in rep['validity']['invalid_cells'] and CELL not in rep['validity']['interrupted']


# ============================================================================ N1 (Astra): Sonnet accounting

@pytest.mark.parametrize('raw', [
    {'input_tokens': -1, 'cached_input_tokens': 0, 'output_tokens': 1},
    {'input_tokens': -1, 'output_tokens': 1},
    {'input_tokens': 10, 'cached_input_tokens': 0, 'output_tokens': -3},
    {'cached_input_tokens': -2},
    {'input_tokens': 5, 'cached_input_tokens': 9, 'output_tokens': 1},
    {'input_tokens': 5, 'cached_input_tokens': 9},
])
def test_n1_a_demonstrated_sonnet_accounting_violation_is_invalid_whatever_else_is_missing(raw):
    dec = usage.decode_sonnet(raw)
    assert dec['status'] == 'invalid', dec
    missing = any(k not in raw for k in ('input_tokens', 'cached_input_tokens', 'output_tokens'))
    assert bool(dec.get('incomplete')) is missing
    if missing:
        assert any('missing' in p for p in dec['problems']), 'both findings are kept'
    acct = run.account_usage('sonnet', raw, 'x', None)  # never indexes a counter the usage lacks
    assert acct['usage_status'] == 'invalid'
    if missing:
        assert acct['additive_tokens'] is None


def test_n1_complete_and_merely_incomplete_sonnet_usage_are_unchanged():
    assert usage.decode_sonnet({'input_tokens': 5, 'cached_input_tokens': 1, 'output_tokens': 2})['status'] == \
        'complete'
    assert usage.decode_sonnet({'input_tokens': 5, 'output_tokens': 2})['status'] == 'incomplete'
    assert usage.decode_sonnet(None)['status'] == 'incomplete'


def test_n1_a_negative_sonnet_counter_makes_the_stopped_cell_invalid(tmp_path, monkeypatch):
    original = run.spawn
    cid = 'sonnet-materials-cold-A'

    def spawn(run_dir, launch, stdin_text, env, cwd, external, timeout=config.CALL_TIMEOUT_S):
        raw = original(run_dir, launch, stdin_text, env, cwd, external, timeout)
        try:
            doc = json.loads(raw['stdout'])
        except ValueError:
            return raw
        for m in (doc.get('modelUsage') or {}).values():
            m['inputTokens'] = -1
        return dict(raw, stdout=json.dumps(doc))
    monkeypatch.setattr(run, 'spawn', spawn)
    go(tmp_path, cid)
    rows = attempts(tmp_path / 'run', cid)
    assert rows and rows[0]['usage_status'] == 'invalid', [r.get('usage') for r in rows[:1]]
    rep = score.score_run(tmp_path / 'run')
    assert rep['validity']['accounting_failures']
    assert rep['cell_states'][cid] == 'invalid' and cid not in rep['validity']['interrupted']


# ============================================================================ N1 (Opus), RTC1.1: structured attribution

def test_n1_a_stopped_cell_with_an_unledgered_live_attempt_is_invalid(live):
    cid = 'sonnet-materials-cold-A'
    assert live.cell(cid, stop_after=2) == config.EXIT_INTERRUPTED
    rows = run.jsonl(live.ledger)
    mine = [r for r in rows if r.get('cell') == cid]
    assert mine
    live.ledger.write_text(''.join(json.dumps(r) + '\n' for r in rows if r is not mine[0]), encoding='utf-8')
    rep = score.score_run(live.run_dir)
    assert any('missing from the experiment ledger' in p for p in rep['validity']['accounting_failures'])
    assert cid in rep['validity']['invalid_cells'] and cid not in rep['validity']['interrupted']


def test_n1_a_stopped_cell_with_duplicate_terminal_attempts_is_invalid(tmp_path):
    assert go(tmp_path, CELL, stop_after=2) == config.EXIT_INTERRUPTED
    path = tmp_path / 'run' / 'attempts.jsonl'
    rows = run.jsonl(path)
    first = next(r for r in rows if r.get('cell') == CELL and r['outcome'] == 'ok')
    dup = dict(first, call_id=first['call_id'][:-1] + '7', attempt_uid=(first.get('attempt_uid') or 'u') + '-dup')
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(dup) + '\n')
    rep = score.score_run(tmp_path / 'run')
    want = f"{CELL} {first['batch']}: 2 terminal attempts"
    assert want in rep['validity']['accounting_failures']
    assert want in rep['validity']['invalid_cells'].get(CELL, [])
    assert rep['cell_states'][CELL] == 'invalid'


def test_rtc1_1_a_stopped_cell_without_any_finding_stays_interrupted(tmp_path):
    assert go(tmp_path, CELL, stop_after=2) == config.EXIT_INTERRUPTED
    rep = score.score_run(tmp_path / 'run')
    assert CELL in rep['validity']['interrupted'] and CELL not in rep['validity']['invalid_cells']


def test_rtc1_1_a_codex_stop_names_its_cell_and_makes_it_invalid(tmp_path):
    assert go(tmp_path, CELL, stop_after=2) == config.EXIT_INTERRUPTED
    (tmp_path / 'run' / 'codex-stop.json').write_text(json.dumps({'reason': 'x', 'cell': CELL}), encoding='utf-8')
    rep = score.score_run(tmp_path / 'run')
    assert CELL in rep['validity']['invalid_cells']


# ============================================================================ RTC1.2: login identity everywhere

def _b64(obj):
    raw = obj if isinstance(obj, bytes) else json.dumps(obj, sort_keys=True).encode('utf-8')
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _jwt(claims):
    return '.'.join([_b64({'alg': 'RS256', 'typ': 'JWT'}), _b64(claims), _b64(b'sig')])


def _auth(directory, *, access=None, ident=None, refresh='rt'):
    exp = int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=9)).timestamp())
    tokens = {'access_token': _jwt(dict({'exp': exp}, **(access or {}))), 'refresh_token': refresh,
              'id_token': _jwt(ident) if ident is not None else 'x.y.z', 'account_id': 'acct'}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'auth.json').write_text(json.dumps({'auth_mode': 'chatgpt', 'tokens': tokens}), encoding='utf-8')
    return directory / 'auth.json'


def test_rtc1_2_a_login_without_any_identity_is_never_treated_as_separate(tmp_path):
    owner = _auth(tmp_path / 'owner', access={'session_id': 'sess_owner'}, refresh='rt_owner')
    blank = _auth(tmp_path / 'blank', refresh='rt_blank').parent
    assert any('no login identity' in p for p in isolation.token_separation_problems(blank, [owner]))
    owner_blank = _auth(tmp_path / 'owner2', refresh='rt_owner2')
    base = _auth(tmp_path / 'base', access={'session_id': 'sess_base'}, refresh='rt_base').parent
    assert any('no login identity' in p for p in isolation.token_separation_problems(base, [owner_blank]))
    assert isolation.token_separation_problems(base, [owner]) == [], 'control: two separate logins pass'


@pytest.mark.parametrize('where', ['access_to_id', 'auth_time', 'pwd_auth_time'])
def test_rtc1_2_any_shared_identity_component_refuses(tmp_path, where):
    if where == 'access_to_id':  # the session moved from the access token to the id token between logins
        o = dict(access={'session_id': 'authsess_same'})
        b = dict(ident={'sid': 'authsess_same'})
    else:
        o = dict(access={'session_id': 'sess_owner', where: 1760000000})
        b = dict(access={'session_id': 'sess_base', where: 1760000000})
    owner = _auth(tmp_path / 'owner', refresh='rt_owner', **o)
    base = _auth(tmp_path / 'base', refresh='rt_base', **b).parent
    assert any('copy of the owner login' in p for p in isolation.token_separation_problems(base, [owner]))


def test_rtc1_2_login_identity_holds_hashes_only(tmp_path):
    path = _auth(tmp_path / 'a', access={'session_id': 'sess_visible'}, ident={'sid': 'sid_visible', 'auth_time': 5})
    text = json.dumps(isolation.login_identity(path))
    assert 'visible' not in text and len(isolation.login_identity(path)['sessions']) == 2


# ============================================================================ O5: D6 is a launch prerequisite

def test_o5_d6_is_a_required_ruling_with_its_two_annexes():
    assert 'D6' in config.REQUIRED_RULINGS
    assert set(rulings.ANNEXES_REQUIRED['D6']) == {'focused_verification', 'operation_attestation'}
    assert any('ruling D6 is not settled' in p for p in rulings.ruling_problems({}))


def test_o5_the_attestation_must_cover_every_item_and_bind_the_classification_and_operations(tmp_path):
    files = write_d6_annexes(tmp_path)
    fv = json.loads(files['focused_verification'].read_text(encoding='utf-8'))
    att = json.loads(files['operation_attestation'].read_text(encoding='utf-8'))
    assert rulings.d6_problems('focused_verification', fv) == []
    assert rulings.d6_problems('operation_attestation', att) == []
    for item in rulings.D6_CHECKLIST:
        bad = json.loads(json.dumps(fv))
        bad['checklist'].pop(item)
        assert rulings.d6_problems('focused_verification', bad), item
    for item in rulings.ATTESTATION_COVERS:
        bad = json.loads(json.dumps(att))
        bad['covers'][item]['verdict'] = 'not verified'
        assert rulings.d6_problems('operation_attestation', bad), item
    for k, n in rulings.ATTESTATION_CASES.items():
        bad = json.loads(json.dumps(att))
        bad['covers'][k]['count'] = n - 1
        assert rulings.d6_problems('operation_attestation', bad), k
    for change in ({'independent': False}, {'attestor': att['implementer']}, {'classification_sha256': '0' * 64},
                   {'ops_sha256': dict(att['ops_sha256'], **{'bench/ozmap_rep/ops/oracle.py': '0' * 64})}):
        assert rulings.d6_problems('operation_attestation', dict(att, **change)), change


def test_o5_the_scorer_checks_the_rulings_the_run_bound_freeze_binds():
    problems = rulings.bound_problems({})
    assert any('binds no ruling D6' in p for p in problems)
    assert len(problems) == len(config.REQUIRED_RULINGS)
