"""The run CLI: plan --list-cells, resumable cell execution in fake mode, refusal to rerun, gates before any spawn.
Never calls a real CLI: fake mode uses the harness' own fakes and a tripwire directory guards the real names."""
import datetime as dt
import hashlib
import json
import re
import shlex
from pathlib import Path

import pytest

import ozrep_helpers as H
from ozrep_helpers import harness, jsonl, run_cli

CELLS_PER_MATERIALS = ['bootstrap', 'cold-A', 'cold-B', 'cold-C', 'warm-A', 'warm-C']
NOMINAL = {'bootstrap': 1, 'cold-A': 4, 'cold-B': 8, 'cold-C': 4, 'warm-A': 4, 'warm-C': 5}
NOMINAL_BOOLQ = {'bootstrap': 1, 'cold-A': 4, 'cold-B': 4, 'cold-C': 3}
FROZEN_HEAD = ['exec', '--ignore-user-config', '--ignore-rules', '--ephemeral', '--skip-git-repo-check', '--json',
               '-s', 'read-only', '-C']


def need_built():
    harness('run')


def plan_lines():
    need_built()
    done = run_cli(['plan', '--list-cells'], timeout=120)
    assert done.returncode == 0, done.stderr
    lines = [l for l in done.stdout.splitlines() if l.strip()]
    return [json.loads(l) for l in lines], done


class Env:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.run_dir = tmp_path / 'run'
        self.baseline = tmp_path / 'baseline'
        H.write_auth(self.baseline, H.auth_doc(H.now_utc() + dt.timedelta(days=30)))
        self.trip = tmp_path / 'trip'
        self.env = H.make_sentinels(self.trip)

    def cell(self, cell_id, *flags, mode='fake', baseline=None, timeout=600):
        return run_cli(['cell', cell_id, '--run-dir', str(self.run_dir), '--mode', mode,
                        '--baseline', str(baseline or self.baseline), *flags], env=self.env, timeout=timeout)

    def fake_calls(self, cell_id=None):
        rows = jsonl(self.run_dir / 'fake_calls.jsonl')
        return [r for r in rows if cell_id is None or r['cell'] == cell_id]

    def tripped(self):
        return H.tripwire_calls(self.trip)


@pytest.fixture
def env(tmp_path):
    need_built()
    return Env(tmp_path)


# ------------------------------------------------------------------------------------------------ plan

def test_cli_plan_list_cells_prints_one_json_line_per_cell_with_id_and_command():
    cells, done = plan_lines()
    assert len(cells) == 16
    ids = [c['id'] for c in cells]
    assert len(set(ids)) == 16
    for c in cells:
        assert c['command'] == f"python -m bench.ozmap_rep.run cell {c['id']}"
        shlex.split(c['command'])
    expected = {f'{b}-materials-{k}' if k == 'bootstrap' else f'{b}-materials-{k}'
                for b in ('codex', 'sonnet') for k in CELLS_PER_MATERIALS}
    expected |= {f'codex-boolq-{k}' for k in NOMINAL_BOOLQ}
    assert set(ids) == expected
    assert all(l.startswith('{') for l in done.stdout.splitlines() if l.strip()), 'nothing but JSON lines on stdout'


def test_cli_plan_nominal_calls_follow_the_allocations():
    cells, _ = plan_lines()
    by_id = {c['id']: c for c in cells}
    for backend in ('codex', 'sonnet'):
        for key, n in NOMINAL.items():
            assert by_id[f'{backend}-materials-{key}']['nominal_calls'] == n
    for key, n in NOMINAL_BOOLQ.items():
        assert by_id[f'codex-boolq-{key}']['nominal_calls'] == n
    for backend in ('codex', 'sonnet'):
        assert sum(c['nominal_calls'] for c in cells if c['id'].startswith(f'{backend}-materials')) == 26
    assert sum(c['nominal_calls'] for c in cells if c['id'].startswith('codex-')) == 38
    assert sum(c['nominal_calls'] for c in cells if c['id'].startswith('sonnet-')) == 26


def test_cli_plan_dependencies_make_the_shared_bootstrap_a_prerequisite():
    cells, _ = plan_lines()
    by_id = {c['id']: c for c in cells}
    for prefix in ('codex-materials', 'sonnet-materials', 'codex-boolq'):
        assert by_id[f'{prefix}-bootstrap']['requires'] == []
        for arm in ('cold-B', 'cold-C'):
            assert f'{prefix}-bootstrap' in by_id[f'{prefix}-{arm}']['requires']
        assert by_id[f'{prefix}-cold-A']['requires'] == []
    for backend in ('codex', 'sonnet'):
        assert f'{backend}-materials-bootstrap' in by_id[f'{backend}-materials-warm-C']['requires']
    for c in cells:
        assert set(c['requires']) <= set(by_id)


def test_cli_plan_cells_carry_backend_workload_wave_and_arm():
    cells, _ = plan_lines()
    by_id = {c['id']: c for c in cells}
    c = by_id['codex-materials-cold-B']
    assert (c['backend'], c['workload'], c['wave'], c['arm']) == ('codex', 'materials', 'cold', 'B')
    c = by_id['codex-boolq-cold-C']
    assert (c['backend'], c['workload'], c['wave'], c['arm']) == ('codex', 'boolq', 'cold', 'C')


# ------------------------------------------------------------------------------------------------ cell runs

def test_cli_cell_unknown_id_is_a_usage_error_without_calls(env):
    done = env.cell('codex-materials-nonsense')
    assert done.returncode == 2
    assert env.fake_calls() == [] and env.tripped() == []


def test_cli_cell_completes_in_fake_mode_with_the_nominal_number_of_calls(env):
    done = env.cell('codex-materials-cold-A')
    assert done.returncode == 0, done.stderr + done.stdout
    assert (env.run_dir / 'cells' / 'codex-materials-cold-A' / 'DONE.json').exists()
    assert len(env.fake_calls('codex-materials-cold-A')) == 4
    attempts = [a for a in jsonl(env.run_dir / 'attempts.jsonl')]
    assert len(attempts) == 4
    assert len(list((env.run_dir / 'prompts').glob('*.txt'))) == 4
    assert env.tripped() == []


def test_cli_cell_refuses_to_rerun_a_completed_cell(env):
    assert env.cell('codex-materials-cold-A').returncode == 0
    before = env.fake_calls()
    again = env.cell('codex-materials-cold-A')
    assert again.returncode == 3
    assert env.fake_calls() == before, 'a completed cell must make no further call'
    assert len(jsonl(env.run_dir / 'attempts.jsonl')) == 4


def test_cli_cell_refuses_to_start_before_its_required_cells_are_complete(env):
    done = env.cell('codex-materials-cold-B')
    assert done.returncode == 4
    assert env.fake_calls() == []
    assert not (env.run_dir / 'cells' / 'codex-materials-cold-B' / 'DONE.json').exists()


def test_cli_cell_runs_after_its_bootstrap_cell_completes(env):
    assert env.cell('codex-materials-bootstrap').returncode == 0
    assert len(env.fake_calls('codex-materials-bootstrap')) == 1
    done = env.cell('codex-materials-cold-C')
    assert done.returncode == 0, done.stderr
    assert 3 <= len(env.fake_calls('codex-materials-cold-C')) <= 4  # bounded by the pooled capacity


def test_cli_cell_is_resumable_and_never_repeats_a_completed_call(env):
    first = env.cell('codex-materials-cold-A', '--stop-after', '2')
    assert first.returncode == 75
    state = json.loads((env.run_dir / 'cells' / 'codex-materials-cold-A' / 'state.json').read_text(encoding='utf-8'))
    assert state['state'] == 'interrupted'
    assert not (env.run_dir / 'cells' / 'codex-materials-cold-A' / 'DONE.json').exists()
    assert len(env.fake_calls('codex-materials-cold-A')) == 2
    second = env.cell('codex-materials-cold-A')
    assert second.returncode == 0, second.stderr
    rows = env.fake_calls('codex-materials-cold-A')
    assert len(rows) == 4, 'two calls before the interruption plus the two that were missing'
    hashes = [r['stdin_sha256'] for r in rows]
    assert len(set(hashes)) == 4, 'no prompt may be sent twice'
    assert env.cell('codex-materials-cold-A').returncode == 3
    assert len(env.fake_calls()) == 4


def test_cli_cell_infrastructure_failures_draw_on_the_two_reserve_calls(env):
    done = env.cell('codex-materials-cold-A', '--fake-fail', '2')
    assert done.returncode == 0, done.stderr
    assert len(env.fake_calls('codex-materials-cold-A')) == 6  # 4 nominal + 2 reserve, failures included
    attempts = jsonl(env.run_dir / 'attempts.jsonl')
    assert len(attempts) == 6 and sum(1 for a in attempts if a.get('outcome') != 'ok') >= 2


def test_cli_cell_exhausted_reserve_leaves_the_cell_incomplete_not_completed(env):
    done = env.cell('codex-materials-cold-A', '--fake-fail', '3')
    assert done.returncode == 5
    assert len(env.fake_calls('codex-materials-cold-A')) == 6, 'never more than allocation plus two reserve calls'
    assert not (env.run_dir / 'cells' / 'codex-materials-cold-A' / 'DONE.json').exists()
    state = json.loads((env.run_dir / 'cells' / 'codex-materials-cold-A' / 'state.json').read_text(encoding='utf-8'))
    assert state['state'] == 'incomplete'
    assert len(jsonl(env.run_dir / 'attempts.jsonl')) == 6, 'every failed attempt stays on record'


# ------------------------------------------------------------------------------------------------ what the fake saw

def test_cli_codex_calls_use_the_frozen_arguments_and_clean_homes(env):
    assert env.cell('codex-materials-cold-A').returncode == 0
    iso = harness('isolation')
    homes = {str(env.run_dir / 'homes' / f'worker-{i}') for i in range(4)}
    works = {str(env.run_dir / 'work' / f'slot-{i}') for i in range(4)}
    rows = env.fake_calls('codex-materials-cold-A')
    assert rows
    for r in rows:
        assert r['cli'] == 'codex'
        argv = r['argv']
        assert iso.argv_check(argv) == [], argv
        i = argv.index('exec')
        assert argv[i:i + len(FROZEN_HEAD)] == FROZEN_HEAD
        assert Path(argv[i + len(FROZEN_HEAD)]).resolve() == Path(r['workdir']).resolve()
        assert str(Path(r['codex_home'])) in homes or str(Path(r['codex_home']).resolve()) in {
            str(Path(h).resolve()) for h in homes}
        assert Path(r['workdir']).resolve() in {Path(w).resolve() for w in works}
        assert r['home_listing'] == ['auth.json'], 'worker home holds only authentication at call time'
        assert r['workdir_listing'] == []
        assert not any(n in r['env_names'] for n in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'ANTHROPIC_API_KEY'))


def test_cli_sonnet_calls_use_the_pilot_flags(env):
    done = env.cell('sonnet-materials-cold-A')
    assert done.returncode == 0, done.stderr
    import claude_map_adapter
    rows = env.fake_calls('sonnet-materials-cold-A')
    assert len(rows) == 4
    for r in rows:
        assert r['cli'] == 'claude'
        argv = r['argv']
        assert '--strict-mcp-config' in argv and '--no-session-persistence' in argv
        j = argv.index('--tools')
        assert argv[j + 1] == ''
        k = argv.index('--setting-sources')
        assert argv[k + 1] == ''
        assert 'claude-sonnet-5-5' in argv


def test_cli_prompts_never_contain_admission_cases(env):
    assert env.cell('codex-materials-bootstrap').returncode == 0
    assert env.cell('codex-materials-cold-A').returncode == 0
    wl = harness('workload').materials()
    texts = [c['text'] for cases in wl['admission'].values() for c in cases]
    prompts = '\n'.join(p.read_text(encoding='utf-8') for p in (env.run_dir / 'prompts').glob('*.txt'))
    assert prompts
    assert [t for t in texts if t in prompts] == []


def test_cli_auth_refresh_in_one_worker_is_synced_to_the_baseline_and_never_logged(env):
    before = hashlib.sha256((env.baseline / 'auth.json').read_bytes()).hexdigest()
    done = env.cell('codex-materials-cold-A', '--fake-refresh', '2')
    assert done.returncode == 0, done.stderr
    after_bytes = (env.baseline / 'auth.json').read_bytes()
    assert hashlib.sha256(after_bytes).hexdigest() != before
    assert b'SECRET-FAKE-REFRESHED' in after_bytes
    secrets = ['SECRET-FAKE-REFRESHED', H.SECRET_ACCESS_MARK, H.SECRET_REFRESH]
    haystacks = [done.stdout, done.stderr]
    haystacks += list(H.tree_text(env.run_dir, skip=[env.run_dir / 'homes', env.run_dir / 'auth']).values())
    for text in haystacks:
        for secret in secrets:
            assert secret not in text, f'auth material found outside the worker homes and baseline: {secret}'
    # hashes only: the evidence directory records the hash change
    assert any(re.search(r'[0-9a-f]{64}', t) for t in H.tree_text(env.run_dir / 'evidence').values())


def test_cli_evidence_is_outside_every_worker_home_and_work_directory(env):
    assert env.cell('codex-materials-cold-A').returncode == 0
    ev = (env.run_dir / 'evidence').resolve()
    assert ev.exists()
    for i in range(4):
        for d in (env.run_dir / 'homes' / f'worker-{i}', env.run_dir / 'work' / f'slot-{i}'):
            assert ev not in d.resolve().parents and d.resolve() not in ev.parents


# ------------------------------------------------------------------------------------------------ gates before spawn

def test_cli_codex_quota_stop_at_80_percent_happens_before_any_call(env):
    sessions = env.tmp / 'sessions'
    folder = sessions / '2026' / '10' / '24'
    folder.mkdir(parents=True)
    (folder / 'rollout-x.jsonl').write_text(json.dumps({'type': 'event_msg', 'payload': {
        'rate_limits': {'primary': {'used_percent': 85.0}}}}) + '\n', encoding='utf-8')
    done = env.cell('codex-materials-cold-A', '--codex-sessions-dir', str(sessions), mode='live')
    assert done.returncode == 10
    assert env.tripped() == [] and env.fake_calls() == []
    assert not (env.run_dir / 'cells' / 'codex-materials-cold-A' / 'DONE.json').exists()


def test_cli_claude_handoff_at_99_percent_happens_before_any_call(env):
    done = env.cell('sonnet-materials-cold-A', '--claude-weekly-percent', '99', mode='live')
    assert done.returncode == 10
    assert env.tripped() == [] and env.fake_calls() == []


@pytest.mark.parametrize('mode', ['live', 'fake'])
def test_cli_baseline_token_expiring_within_48_hours_blocks_the_wave(env, mode):
    short = env.tmp / 'short-baseline'
    H.write_auth(short, H.auth_doc(H.now_utc() + dt.timedelta(hours=10)))
    done = env.cell('codex-materials-cold-A', mode=mode, baseline=short)
    assert done.returncode == 11
    assert 'codex login' in (done.stdout + done.stderr)
    assert env.tripped() == [] and env.fake_calls() == []
    for secret in (H.SECRET_ACCESS_MARK, H.SECRET_REFRESH):
        assert secret not in done.stdout + done.stderr


def test_cli_missing_baseline_blocks_the_wave(env):
    done = env.cell('codex-materials-cold-A', baseline=env.tmp / 'does-not-exist')
    assert done.returncode == 11
    assert 'codex login' in (done.stdout + done.stderr)
    assert env.fake_calls() == []
