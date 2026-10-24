"""A4.2: worker CODEX_HOME reconstruction, working directories, environment, launch verification."""
import hashlib
import json
import os
from pathlib import Path

import ozrep_helpers as H
from ozrep_helpers import harness, need

EXCLUDED = ('plugins', 'skills', 'memories', 'history.jsonl', 'sessions', 'hooks', 'AGENTS.md', 'AGENTS.override.md',
            'config.toml', 'instructions.md', 'rules', 'log', 'prompts')


def make_iso(tmp_path, baseline):
    iso = harness('isolation')
    cls = need(iso, 'Isolation')
    root, evidence = tmp_path / 'run', tmp_path / 'evidence'
    root.mkdir(exist_ok=True)
    evidence.mkdir(exist_ok=True)
    return iso, cls(baseline, root, evidence), root, evidence


def dirty_baseline(baseline):
    """The owner's home is never copied, but a polluted baseline must still yield an auth only worker home."""
    for name in EXCLUDED:
        target = baseline / name
        if name.endswith(('.md', '.toml', '.jsonl')):
            target.write_text('polluted', encoding='utf-8')
        else:
            target.mkdir()
            (target / 'x.txt').write_text('polluted', encoding='utf-8')


def test_a4_2_worker_home_contains_only_auth_json(tmp_path, baseline):
    iso, isolation, root, _ = make_iso(tmp_path, baseline)
    prepared = isolation.prepare(0)
    home = Path(prepared['home'])
    assert sorted(os.listdir(home)) == ['auth.json']
    assert (home / 'auth.json').read_bytes() == (baseline / 'auth.json').read_bytes()
    assert prepared['env']['CODEX_HOME'] == str(home)
    assert home == root / 'homes' / 'worker-0'


def test_a4_2_excluded_items_absent_even_from_a_polluted_baseline(tmp_path, baseline):
    iso, isolation, _, _ = make_iso(tmp_path, baseline)
    dirty_baseline(baseline)
    home = Path(isolation.prepare(1)['home'])
    listing = sorted(os.listdir(home))
    assert listing == ['auth.json'], listing
    for name in EXCLUDED:
        assert not (home / name).exists(), name


def test_a4_2_baseline_inventory_check_reports_extra_items(tmp_path, baseline):
    iso = harness('isolation')
    verify = need(iso, 'verify_baseline')
    assert verify(baseline) == []
    dirty_baseline(baseline)
    problems = verify(baseline)
    assert problems, 'a baseline with plugins, memories or configuration must not pass'
    text = json.dumps(problems)
    for name in ('plugins', 'skills', 'memories', 'config.toml', 'AGENTS.md'):
        assert name in text, name


def test_a4_2_stale_runtime_state_is_removed_before_reuse(tmp_path, baseline):
    iso, isolation, root, _ = make_iso(tmp_path, baseline)
    stale = root / 'homes' / 'worker-2'
    (stale / 'sessions' / '2026').mkdir(parents=True)
    (stale / 'sessions' / '2026' / 'old.jsonl').write_text('{}', encoding='utf-8')
    (stale / 'AGENTS.md').write_text('stale instructions', encoding='utf-8')
    (stale / 'auth.json').write_text('{"stale": true}', encoding='utf-8')
    home = Path(isolation.prepare(2)['home'])
    assert sorted(os.listdir(home)) == ['auth.json']
    assert (home / 'auth.json').read_bytes() == (baseline / 'auth.json').read_bytes()


def test_a4_2_four_numbered_homes_and_empty_working_directories(tmp_path, baseline):
    iso, isolation, root, _ = make_iso(tmp_path, baseline)
    (root / 'work' / 'slot-3').mkdir(parents=True)
    (root / 'work' / 'slot-3' / 'leftover.txt').write_text('x', encoding='utf-8')
    prepared = [isolation.prepare(slot) for slot in range(4)]
    assert len({p['home'] for p in prepared}) == 4
    assert len({p['workdir'] for p in prepared}) == 4
    for slot, p in enumerate(prepared):
        assert Path(p['home']).name == f'worker-{slot}'
        assert Path(p['workdir']).name == f'slot-{slot}'
        assert os.listdir(p['workdir']) == []


def test_a4_2_evidence_lives_outside_model_accessible_directories(tmp_path, baseline):
    iso, isolation, root, evidence = make_iso(tmp_path, baseline)
    prepared = [isolation.prepare(s) for s in range(4)]
    ev = evidence.resolve()
    for p in prepared:
        for d in (Path(p['home']).resolve(), Path(p['workdir']).resolve()):
            assert d != ev and d not in ev.parents and ev not in d.parents
    assert list(evidence.iterdir()), 'prepare must leave hash evidence'


def test_a4_2_generated_runtime_files_inventoried_then_removed(tmp_path, baseline):
    iso, isolation, root, evidence = make_iso(tmp_path, baseline)
    prepared = isolation.prepare(0)
    home = Path(prepared['home'])
    (home / 'sessions').mkdir()
    (home / 'sessions' / 'rollout.jsonl').write_text('{}', encoding='utf-8')
    (home / 'log').mkdir()
    (home / 'log' / 'codex.log').write_text('x', encoding='utf-8')
    done = isolation.finish(0)
    names = {n.replace('\\', '/') for n in done['runtime_files']}
    assert 'sessions/rollout.jsonl' in names and 'log/codex.log' in names
    assert 'auth.json' not in names
    assert not (home / 'sessions').exists() and not (home / 'log').exists()


def test_a4_2_child_environment_is_allowlisted(tmp_path):
    iso = harness('isolation')
    child_env = need(iso, 'child_env')
    home = str(tmp_path / 'home')
    base = {'PATH': os.environ.get('PATH', ''), 'CODEX_HOME': 'C:/owner/.codex', 'OPENAI_API_KEY': 'k',
            'CODEX_API_KEY': 'k2', 'ANTHROPIC_API_KEY': 'k3', 'GITHUB_TOKEN': 't', 'MY_SECRET': 's',
            'CODEX_SANDBOX_NETWORK_DISABLED': '1', 'SYSTEMROOT': os.environ.get('SYSTEMROOT', 'C:/Windows')}
    env = child_env(home, base)
    assert env['CODEX_HOME'] == home
    for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'ANTHROPIC_API_KEY', 'GITHUB_TOKEN', 'MY_SECRET',
                 'CODEX_SANDBOX_NETWORK_DISABLED'):
        assert name not in env, name
    cfg = harness('config')
    allowed = set(need(cfg, 'ENV_ALLOWLIST')) | {'CODEX_HOME'}
    assert set(env) <= allowed, sorted(set(env) - allowed)


def test_a4_2_instruction_sources_include_ancestors(tmp_path):
    iso = harness('isolation')
    sources = need(iso, 'instruction_sources')
    work = tmp_path / 'a' / 'b' / 'slot-0'
    work.mkdir(parents=True)
    assert [p for p in sources(work) if Path(p).resolve().is_relative_to(tmp_path.resolve())] == []
    (tmp_path / 'a' / 'AGENTS.md').write_text('rules', encoding='utf-8')
    (work / 'CLAUDE.md').write_text('rules', encoding='utf-8')
    found = {Path(p).resolve() for p in sources(work)}
    assert (tmp_path / 'a' / 'AGENTS.md').resolve() in found
    assert (work / 'CLAUDE.md').resolve() in found


def _frozen(iso, exe, argv):
    return {'argv_sha256': iso.argv_sha256(argv), 'exe_sha256': hashlib.sha256(exe.read_bytes()).hexdigest()}


def test_a4_2_verify_launch_blocks_on_any_mismatch(tmp_path, baseline):
    iso, isolation, root, _ = make_iso(tmp_path, baseline)
    cfg = harness('config')
    exe = tmp_path / 'codex-fake'
    exe.write_bytes(b'#!fake')
    prepared = isolation.prepare(0)
    argv = iso.codex_argv(str(exe), cfg.CODEX_MODEL, cfg.CODEX_EFFORT, prepared['workdir'])
    frozen = _frozen(iso, exe, argv)
    ok = iso.verify_launch(argv=argv, env=prepared['env'], workdir=prepared['workdir'],
                           exe_sha256=frozen['exe_sha256'], frozen=frozen)
    assert ok == []
    # executable hash mismatch
    assert iso.verify_launch(argv=argv, env=prepared['env'], workdir=prepared['workdir'],
                             exe_sha256='0' * 64, frozen=frozen)
    # argument mismatch
    bad = argv[:-1] + ['--dangerously-bypass-approvals-and-sandbox', '-']
    assert iso.verify_launch(argv=bad, env=prepared['env'], workdir=prepared['workdir'],
                             exe_sha256=frozen['exe_sha256'], frozen=frozen)
    # environment mismatch
    env = dict(prepared['env'], OPENAI_API_KEY='k')
    assert iso.verify_launch(argv=argv, env=env, workdir=prepared['workdir'],
                             exe_sha256=frozen['exe_sha256'], frozen=frozen)
    # non-empty working directory
    (Path(prepared['workdir']) / 'x.txt').write_text('x', encoding='utf-8')
    assert iso.verify_launch(argv=argv, env=prepared['env'], workdir=prepared['workdir'],
                             exe_sha256=frozen['exe_sha256'], frozen=frozen)


def test_a4_2_verify_launch_blocks_on_ancestor_instruction_file(tmp_path, baseline):
    iso, isolation, root, _ = make_iso(tmp_path, baseline)
    cfg = harness('config')
    exe = tmp_path / 'codex-fake'
    exe.write_bytes(b'#!fake')
    prepared = isolation.prepare(0)
    argv = iso.codex_argv(str(exe), cfg.CODEX_MODEL, cfg.CODEX_EFFORT, prepared['workdir'])
    frozen = _frozen(iso, exe, argv)
    (root / 'AGENTS.md').write_text('instructions in an ancestor', encoding='utf-8')
    problems = iso.verify_launch(argv=argv, env=prepared['env'], workdir=prepared['workdir'],
                                 exe_sha256=frozen['exe_sha256'], frozen=frozen)
    assert problems and 'AGENTS.md' in json.dumps(problems)


def test_a4_2_telemetry_checks_stop_on_credential_store_or_dirty_home():
    iso = harness('isolation')
    checks = need(iso, 'telemetry_checks')
    assert checks({'auth_read_from_codex_home': True, 'sandbox_clean_home': True}) == []
    assert checks({'auth_read_from_codex_home': False, 'sandbox_clean_home': True})
    assert checks({'auth_read_from_codex_home': True, 'sandbox_clean_home': False})
    assert checks({})  # missing evidence is a failure, not a pass
