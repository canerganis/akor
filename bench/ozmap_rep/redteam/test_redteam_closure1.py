"""Red team closure round 1 (A4.14.3) against the replication harness (bench/ozmap_rep) at 14a8359.

Every test here is expected to FAIL on 14a8359 and to pass once the finding it names is fixed. Findings and fixes:
docs/design/ozmap-replication-2026-10-24/closure-redteam-r1.md.

Fakes and temporary directories only: no real `codex` or `claude` is resolved or spawned (live mode runs the harness'
own fakes through the real lifecycle code, as in tests/test_council_r1.Live), no real baseline, run directory,
experiment ledger, owner home or Codex session directory is read or written, and the sealed reviewer ASTs are never
touched.
"""
import base64
import datetime as dt
import json
from pathlib import Path

import pytest

from bench.ozmap_rep import config, isolation, run, score
from bench.ozmap_rep.tests.test_council_r1 import Live, go
from bench.ozmap_rep.tests.test_council_r2 import EXECUTED, inject

CELL = 'codex-materials-cold-A'


@pytest.fixture
def live(tmp_path, monkeypatch):
    return Live(tmp_path, monkeypatch)


# ===================================================================== RTC1.1: per cell validity of stopped cells

def test_rtc1_1_a_cell_stopped_by_its_probe_disclosure_is_invalid_not_interrupted(live, monkeypatch):
    """A4.14.1: an isolation signal makes the cell invalid, not merely interrupted; A4.14.2: a path that labels a
    detected validity failure as interrupted is a BLOCKER. The features probe of the cell discloses credential
    material: the harness records it (evidence/probe-disclosures.jsonl, scoped to the cell) and stops the cell, the
    scorer lists it as an isolation problem, yet score.py attributes findings to a stopped cell only by its call ids
    and marker names. The probe runs before any call, so the cell has no call id, and the disclosure line names the
    cell, not a call: the report lists the cell under "stopped cells interrupted, no finding"."""
    assert live.telemetry() == 0
    original = run.run_local

    def leaky(argv, env, cwd, on_start=None, timeout=120):
        code, out, err = original(argv, env, cwd, on_start, timeout)
        if 'features' in argv:
            doc = json.loads((Path(env['CODEX_HOME']) / 'auth.json').read_text(encoding='utf-8'))
            err = err + '\ndebug: bearer ' + doc['tokens']['access_token'] + '\n'
        return code, out, err
    monkeypatch.setattr(run, 'run_local', leaky)
    assert live.cell(CELL) == config.EXIT_AUTH_GATE
    rep = score.score_run(live.run_dir)
    assert any(f'probe of {CELL}' in p for p in rep['validity']['isolation_problems']), 'control: detected'
    assert CELL not in rep['validity']['interrupted'], (
        'a cell stopped by its own isolation signal is labeled "interrupted, no finding" (A4.14.1, A4.14.2)')
    assert CELL in rep['validity']['invalid_cells']
    assert rep['cell_states'][CELL] == 'invalid'


def test_rtc1_1_a_crashed_cell_scored_before_any_later_admission_gets_its_validity(tmp_path, monkeypatch):
    """A4.14.1: "The scorer then applies A4.3 and A4.11 to the preserved records of every stopped cell". A cell is
    stopped by stop_cell only through crash_scan, which runs when a later cell is admitted. When the runner dies after
    recording an executed tool event (the last cell of a wave, or the driver scores right after the crash), the
    scorer sees the cell in state `running`: the per cell block of score_run considers only state `interrupted`, so the
    detected leakage of that cell is never applied to it (not in invalid_cells, its state stays `running`)."""
    monkeypatch.setattr(run, 'spawn', inject('r1.b01', EXECUTED))

    def crash(self, workers):
        raise KeyboardInterrupt('runner killed just before reconciliation')
    monkeypatch.setattr(run.CellRun, 'reconcile', crash)
    with pytest.raises(KeyboardInterrupt):
        go(tmp_path, CELL)
    rep = score.score_run(tmp_path / 'run')
    assert any(p.startswith(f'{CELL}.r1.b01.t0: tool event verdict executed') for p in rep['validity']['leakage']), \
        'control: the leakage is detected'
    assert CELL in rep['validity']['invalid_cells'], (
        'a crashed cell with detected leakage is not given its A4.14.1 validity when scored before a later admission')
    assert rep['cell_states'][CELL] == 'invalid'


# =========================================================== RTC1.2: login identity outside the access token

def _b64(obj):
    raw = obj if isinstance(obj, bytes) else json.dumps(obj, sort_keys=True).encode('utf-8')
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _jwt(claims):
    return '.'.join([_b64({'alg': 'RS256', 'typ': 'JWT'}), _b64(claims), _b64(b'sig')])


def _doc(*, session, auth_time, iat, jti, refresh, last_refresh):
    """An auth.json whose login identity is carried by the id token (sid, auth_time) only: the access token has no
    `session_id` claim."""
    exp = int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=9)).timestamp())
    auth = {'chatgpt_account_id': 'acct-redteam', 'chatgpt_plan_type': 'pro', 'user_id': 'user-redteam'}
    access = _jwt({'exp': exp, 'iat': iat, 'jti': jti, 'https://api.openai.com/auth': auth,
                   'scp': ['openid', 'offline_access']})
    id_token = _jwt({'exp': iat + 3600, 'iat': iat, 'auth_time': auth_time, 'sid': session, 'email': 'r@t.example',
                     'https://api.openai.com/auth': auth})
    return {'auth_mode': 'chatgpt', 'OPENAI_API_KEY': None, 'last_refresh': last_refresh,
            'tokens': {'id_token': id_token, 'access_token': access, 'refresh_token': refresh,
                       'account_id': 'acct-redteam'}}


def _write(directory, doc):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'auth.json').write_text(json.dumps(doc), encoding='utf-8')
    return directory / 'auth.json'


def test_rtc1_2_a_stale_copy_of_the_owner_login_passes_when_the_access_token_has_no_session_claim(tmp_path):
    """RT3.2 was closed by comparing the access token `session_id`. isolation.login_identity returns {} when that
    claim is absent, and token_separation_problems then compares nothing (`if my_login and their_login and ...`), so
    a missing identity is treated as different, the opposite of the round 2 joint rule ("an unexplained credential
    representation is never treated as different"). The login identity is still present in the id token (sid,
    auth_time), which the check ignores. A baseline copied from the owner auth.json before the owner's next rotation
    passes, and its first worker refresh replays a refresh token the owner already spent (the RT3.2 harm to the
    owner's login)."""
    owner = _write(tmp_path / 'owner' / '.codex', _doc(
        session='authsess_owner', auth_time=1760000000, iat=1761200000, jti='after-rotation',
        refresh='rt_owner_after_rotation', last_refresh='2026-10-15T18:40:00Z'))
    separate = _write(tmp_path / 'separate-baseline', _doc(
        session='authsess_baseline', auth_time=1761300000, iat=1761300000, jti='baseline-login',
        refresh='rt_baseline_own', last_refresh='2026-10-24T15:18:00Z')).parent
    assert isolation.token_separation_problems(separate, [owner]) == [], 'control: a separate login must pass'
    stale = _write(tmp_path / 'stale-copy-baseline', _doc(
        session='authsess_owner', auth_time=1760000000, iat=1760900000, jti='before-rotation',
        refresh='rt_owner_before_rotation', last_refresh='2026-10-07T09:00:00Z')).parent
    assert isolation.token_separation_problems(stale, [owner]), (
        'a stale copy of the owner login passes token separation when the access token carries no session_id '
        '(A4.2, RT2.6, RT3.2)')
