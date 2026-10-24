"""The dry run end to end with a counter proving zero external calls, and the offline scorer on its output."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import ozrep_helpers as H
from ozrep_helpers import harness, jsonl, need, run_cli

NOMINAL = {'bootstrap': 1, 'cold-A': 4, 'cold-B': 8, 'cold-C': 4, 'warm-A': 4, 'warm-C': 5}
NOMINAL_BOOLQ = {'bootstrap': 1, 'cold-A': 4, 'cold-B': 4, 'cold-C': 3}
OPS = ('verdict', 'margin', 'elong', 'temp_class')


@pytest.fixture(scope='module')
def dry(tmp_path_factory):
    harness('run')
    base = tmp_path_factory.mktemp('dry')
    trip = base / 'trip'
    env = H.make_sentinels(trip)
    home = base / 'home'
    home.mkdir()
    owner_codex = base / 'owner-codex-home'  # a decoy owner CODEX_HOME that must never be created or read
    env.update({'HOME': str(home), 'USERPROFILE': str(home), 'CODEX_HOME': str(owner_codex),
                'OPENAI_API_KEY': 'must-not-be-read', 'CODEX_API_KEY': 'must-not-be-read'})
    run_dir = base / 'run'
    done = run_cli(['dry', '--run-dir', str(run_dir)], env=env, timeout=1800)
    return {'base': base, 'trip': trip, 'home': home, 'owner': owner_codex, 'run': run_dir, 'done': done, 'env': env,
            'report': json.loads((run_dir / 'dry_report.json').read_text(encoding='utf-8'))
            if (run_dir / 'dry_report.json').exists() else None}


def test_dry_exits_zero_and_writes_its_report(dry):
    assert dry['done'].returncode == 0, dry['done'].stderr[-3000:] + dry['done'].stdout[-3000:]
    assert dry['report'] is not None


def test_dry_makes_zero_external_calls(dry):
    r = dry['report']
    assert r['external_calls'] == 0
    assert r['real_cli_resolved'] == []
    assert H.tripwire_calls(dry['trip']) == [], 'a real codex or claude name on PATH was invoked'


def test_dry_exercises_the_fakes_and_counts_them(dry):
    r = dry['report']
    rows = jsonl(dry['run'] / 'fake_calls.jsonl')
    assert r['fake_calls'] > 0 and r['fake_calls'] == len(rows)
    assert r['fake_calls'] == sum(c['physical_calls'] for c in r['cells'].values())
    assert len(jsonl(dry['run'] / 'attempts.jsonl')) == r['fake_calls']


def test_dry_never_touches_the_owners_codex_home_or_home_directory(dry):
    assert not dry['owner'].exists()
    assert list(dry['home'].iterdir()) == []


def test_dry_completes_all_sixteen_cells_within_their_nominal_allocations(dry):
    cells = dry['report']['cells']
    expected = {f'{b}-materials-{k}': n for b in ('codex', 'sonnet') for k, n in NOMINAL.items()}
    expected |= {f'codex-boolq-{k}': n for k, n in NOMINAL_BOOLQ.items()}
    assert set(cells) == set(expected)
    for cell_id, nominal in expected.items():
        assert cells[cell_id]['state'] == 'complete', cell_id
        assert 1 <= cells[cell_id]['physical_calls'] <= nominal, cell_id
        assert (dry['run'] / 'cells' / cell_id / 'DONE.json').exists()


def test_dry_scheduler_stays_within_the_a4_4_capacity_bounds_with_zero_rules(dry):
    capacity = dry['report']['capacity']
    expected = {f'{b}-materials-{k}': n for b in ('codex', 'sonnet') for k, n in NOMINAL.items() if k != 'bootstrap'}
    expected |= {f'codex-boolq-{k}': n for k, n in NOMINAL_BOOLQ.items() if k != 'bootstrap'}
    assert set(capacity) == set(expected)
    for cell_id, bound in expected.items():
        assert capacity[cell_id]['bound'] == bound, cell_id
        assert capacity[cell_id]['scheduled_calls'] <= bound, cell_id


def test_dry_codex_calls_all_used_the_frozen_arguments_and_clean_homes(dry):
    iso = harness('isolation')
    rows = [r for r in jsonl(dry['run'] / 'fake_calls.jsonl') if r['cli'] == 'codex']
    assert rows
    for r in rows:
        assert iso.argv_check(r['argv']) == [], r['argv']
        assert r['home_listing'] == ['auth.json'] and r['workdir_listing'] == []


def test_dry_prompts_are_recorded_and_hide_admission_material(dry):
    files = list((dry['run'] / 'prompts').glob('*.txt'))
    assert len(files) == dry['report']['fake_calls']
    wl = harness('workload').materials()
    admission = [c['text'] for cases in wl['admission'].values() for c in cases]
    blob = '\n'.join(p.read_text(encoding='utf-8') for p in files)
    assert [t for t in admission if t in blob] == []


# ------------------------------------------------------------------------------------------------ scorer

@pytest.fixture(scope='module')
def report(dry):
    path = dry['run'] / 'report.json'
    assert path.exists(), 'the dry run must score its own output'
    return json.loads(path.read_text(encoding='utf-8'))


def test_score_report_has_the_documented_sections(report):
    assert report['schema'] == 'ozmap-rep/1'
    for key in ('cells', 'per_operation', 'budget', 'validity', 'gates', 'claims', 'magnitude', 'R', 'preparation'):
        assert key in report, key
    assert (Path(H.REPO) / 'bench').exists() and (Path(H.REPO) / 'bench' / 'ozmap_rep').exists()


def test_score_dry_cells_are_gold_correct_and_complete(report):
    cells = report['cells']
    assert len(cells) == 13  # 5 cells x 2 backends materials + 3 BoolQ arms
    for key, c in cells.items():
        assert c['jobs'] == 256 and c['correct'] == 256 and c['unresolved'] == 0, key
        assert c['usage'] == 'complete' and c['state'] == 'complete', key
        assert c['rule_errors'] == 0


def test_score_per_operation_totals_match_the_cell_totals(report):
    for key, c in report['cells'].items():
        if '/materials/' not in key:
            continue
        ops = report['per_operation'][key]
        assert set(ops) == set(OPS), key
        assert sum(v['jobs'] for v in ops.values()) == c['jobs']
        assert sum(v['correct'] for v in ops.values()) == c['correct']
        assert sum(v['tokens'] for v in ops.values()) == c['tokens']


def test_score_budget_section_counts_physical_calls_within_the_caps(report, dry):
    caps = need(harness('config'), 'EVAL_CAPS')
    for backend in ('codex', 'sonnet'):
        b = report['budget'][backend]
        assert b['nominal'] + b['reserve'] + b['telemetry'] == b['total']
        assert b['total'] <= caps[backend]['total']
    total = sum(report['budget'][b]['total'] for b in ('codex', 'sonnet'))
    assert total == dry['report']['fake_calls']


def test_score_with_zero_rules_never_permits_a_headline_and_has_no_safety_kill(report):
    assert report['claims']['cross_backend_headline'] is False
    assert report['gates']['safety_kill'] is False
    assert report['validity']['isolation'] == 'passed'


def test_score_cli_is_offline_and_deterministic(dry):
    path = dry['run'] / 'report.json'
    first = path.read_bytes()
    md_first = (dry['run'] / 'report.md').read_bytes()
    done = subprocess.run([sys.executable, '-m', 'bench.ozmap_rep.score', str(dry['run'])], cwd=str(H.REPO),
                          env={**os.environ, **dry['env']}, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]
    assert path.read_bytes() == first and (dry['run'] / 'report.md').read_bytes() == md_first
    assert H.tripwire_calls(dry['trip']) == []


def test_score_run_in_process_matches_the_written_report(dry, report):
    score = harness('score')
    again = need(score, 'score_run')(dry['run'])
    assert json.loads(json.dumps(again, sort_keys=True, default=str))['schema'] == 'ozmap-rep/1'
    assert again['cells'].keys() == report['cells'].keys()


# ------------------------------------------------------------------------------------------------ in-process counter

def test_dry_in_process_spawns_no_codex_or_claude_outside_its_run_directory(tmp_path, monkeypatch):
    run = harness('run')
    env = H.make_sentinels(tmp_path / 'trip')
    monkeypatch.setenv('PATH', env['PATH'])
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    spawned = []
    real_popen = subprocess.Popen

    class Spy(real_popen):
        def __init__(self, args, *a, **kw):
            first = args[0] if isinstance(args, (list, tuple)) and args else args
            spawned.append(str(first))
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(subprocess, 'Popen', Spy)
    run_dir = tmp_path / 'run'
    code = run.main(['dry', '--run-dir', str(run_dir)])
    assert code == 0
    for first in spawned:
        stem = Path(first.split()[0] if ' ' in first and not Path(first).exists() else first).name.lower()
        stem = stem.split('.')[0]
        if stem in ('codex', 'claude'):
            resolved = Path(shutil.which(first) or first).resolve()
            assert run_dir.resolve() in resolved.parents, f'a model CLI outside the run directory was spawned: {first}'
    report = json.loads((run_dir / 'dry_report.json').read_text(encoding='utf-8'))
    assert report['external_calls'] == 0
    assert H.tripwire_calls(tmp_path / 'trip') == []
