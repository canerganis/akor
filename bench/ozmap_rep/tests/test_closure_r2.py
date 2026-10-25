"""Closure round 2 (A4.14.3) regressions for the two blockers the owner asked to fix (owner decision 3): O3 (the probe
marker was removed before the probe disclosure was recorded) and N1 (a stopped telemetry cell got no validity).

Fakes and temporary directories only: no real `codex` or `claude` is resolved or spawned (live mode runs the harness'
own fakes through the real lifecycle code, as in tests/test_council_r1.Live), no real baseline, run directory,
experiment ledger or Codex session directory is written, and the sealed reviewer ASTs are never touched.
"""
import json
from pathlib import Path

import pytest

from bench.ozmap_rep import config, run, score
from bench.ozmap_rep.tests.test_council_r1 import Live

CELL = 'codex-materials-cold-A'


@pytest.fixture
def live(tmp_path, monkeypatch):
    return Live(tmp_path, monkeypatch)


def _token(home):
    doc = json.loads((Path(home) / 'auth.json').read_text(encoding='utf-8'))
    return doc['tokens']['access_token']


# ============================================================================ O3: disclosure recorded before unlink

def test_o3_a_crash_between_reconcile_and_the_disclosure_write_leaves_the_cell_invalid(live, monkeypatch):
    """The first features probe of an evaluation cell emits credential material, redaction detects it, the probe home
    is reconciled, and the runner dies before the disclosure record is written. The probe marker must still be there
    (the scorer attributes it to its cell as an isolation uncertainty) and the raw stream inside the credential
    boundary must be kept, so the cell is invalid, never interrupted or unclassified."""
    assert live.telemetry() == 0
    original_local = run.run_local
    leaked = []

    def leaky(argv, env, cwd, on_start=None, timeout=120):
        code, out, err = original_local(argv, env, cwd, on_start, timeout)
        if 'features' in argv:
            secret = _token(env['CODEX_HOME'])
            leaked.append(secret)
            err = err + '\ndebug: bearer ' + secret + '\n'
            paths = getattr(run._TLS, 'probe_raw', None)
            if paths:  # what the raw stream file holds for this child
                with open(paths[1], 'a', encoding='utf-8') as f:
                    f.write('\ndebug: bearer ' + secret + '\n')
        return code, out, err
    monkeypatch.setattr(run, 'run_local', leaky)

    order = []
    original_reconcile = run.CellRun.reconcile

    def reconcile(self, workers):
        result = original_reconcile(self, workers)
        if any(str(w.get('call_id', '')).startswith('probe-features-') for w in workers.values()):
            order.append('reconciled')
        return result
    monkeypatch.setattr(run.CellRun, 'reconcile', reconcile)

    original_append = run._append

    def append(run_dir, name, row):
        if name == 'evidence/probe-disclosures.jsonl':
            order.append('disclosure')
            raise KeyboardInterrupt('runner killed after reconciliation, before the disclosure record')
        return original_append(run_dir, name, row)
    monkeypatch.setattr(run, '_append', append)

    with pytest.raises(KeyboardInterrupt):
        live.cell(CELL)
    assert order == ['reconciled', 'disclosure'], f'the crash is injected after reconciliation: {order}'
    monkeypatch.setattr(run, '_append', original_append)

    markers = sorted((live.run_dir / 'cells' / CELL / 'inflight').glob('probe-features-*.json'))
    assert markers, 'the probe marker is kept through every failure before the disclosure record'
    marker = json.loads(markers[0].read_text(encoding='utf-8'))
    raw = [Path(p) for p in marker.get('raw') or []]
    assert raw and all(p.exists() for p in raw), 'the raw probe stream stays inside the credential boundary'
    assert leaked and leaked[0] in raw[1].read_text(encoding='utf-8'), 'the raw evidence of the disclosure is kept'
    assert not run.jsonl(live.run_dir / 'evidence' / 'probe-disclosures.jsonl')

    rep = score.score_run(live.run_dir)
    assert rep['validity']['isolation'] == 'failed'
    assert rep['cell_states'][CELL] == 'invalid'
    assert CELL in rep['validity']['invalid_cells'] and CELL not in rep['validity']['interrupted']
    assert any('unknown state' in p for p in rep['validity']['invalid_cells'][CELL])

    # a later admission stops the crashed cell; its marker and raw stream are preserved and it stays invalid
    run.crash_scan(live.run_dir)
    assert (live.run_dir / 'cells' / CELL / 'INTERRUPTED.json').exists()
    assert markers[0].exists() and all(p.exists() for p in raw)
    rep = score.score_run(live.run_dir)
    assert rep['cell_states'][CELL] == 'invalid'
    assert CELL in rep['validity']['invalid_cells'] and CELL not in rep['validity']['interrupted']


def test_o3_a_detected_probe_disclosure_is_recorded_before_the_marker_goes(live, monkeypatch):
    """The normal path: the disclosure record exists by the time the probe marker is removed."""
    assert live.telemetry() == 0
    original_local = run.run_local

    def leaky(argv, env, cwd, on_start=None, timeout=120):
        code, out, err = original_local(argv, env, cwd, on_start, timeout)
        if 'features' in argv:
            err = err + '\ndebug: bearer ' + _token(env['CODEX_HOME']) + '\n'
        return code, out, err
    monkeypatch.setattr(run, 'run_local', leaky)
    seen = []
    original_unlink = Path.unlink

    def unlink(self, *a, **k):
        if self.name.startswith('probe-features-') and self.suffix == '.json':
            seen.append(bool(run.jsonl(live.run_dir / 'evidence' / 'probe-disclosures.jsonl')))
        return original_unlink(self, *a, **k)
    monkeypatch.setattr(Path, 'unlink', unlink)
    assert live.cell(CELL) == config.EXIT_AUTH_GATE
    assert seen == [True], 'the disclosure record is written before the probe marker is removed'
    rep = score.score_run(live.run_dir)
    assert rep['cell_states'][CELL] == 'invalid' and CELL not in rep['validity']['interrupted']


# ============================================================================ N1: a stopped telemetry cell's validity

def test_n1_a_stopped_telemetry_cell_gets_its_validity_and_stays_out_of_evaluation(live, monkeypatch):
    """A worker path login probe of the telemetry cell does not settle (terminated False, no complete raw output):
    its evidence names the cell `telemetry`, the cell is stopped, and the scorer must give it its validity."""
    original_local = run.run_local
    failed = []

    def local(argv, env, cwd, on_start=None, timeout=120):
        if on_start is None and 'login' in argv and not failed:
            paths = getattr(run._TLS, 'probe_raw', None)
            assert paths, 'the probe streams go to files inside the credential boundary'
            Path(paths[0]).parent.mkdir(parents=True, exist_ok=True)
            Path(paths[0]).write_text('partial\n', encoding='utf-8')
            Path(paths[1]).write_text('', encoding='utf-8')
            failed.append(paths)
            raise run.SpawnFailure('waiting for the probe raised RuntimeError', False, 4242, None)
        return original_local(argv, env, cwd, on_start, timeout)
    monkeypatch.setattr(run, 'run_local', local)
    assert live.telemetry() == config.EXIT_AUTH_STOP
    assert failed, 'control: a worker path login probe failed'
    tdir = live.run_dir / 'cells' / 'telemetry'
    assert (tdir / 'INTERRUPTED.json').exists()
    ev = live.run_dir / 'evidence'
    uncertain = run.jsonl(ev / 'probe-uncertain.jsonl')
    assert uncertain and uncertain[0]['cell'] == 'telemetry'
    assert all(Path(p).exists() for p in uncertain[0]['raw_kept']), 'the raw evidence is preserved'
    assert run.jsonl(ev / 'probe-failures.jsonl')

    rep = score.score_run(live.run_dir)
    assert rep['validity']['isolation'] == 'failed'
    assert rep['cell_states']['telemetry'] == 'invalid'
    assert 'telemetry' in rep['validity']['invalid_cells']
    assert 'telemetry' not in rep['validity']['interrupted']
    assert not [k for k in rep['cells'] if 'telemetry' in k], 'no administrative cell enters the evaluation cells'
    assert not [k for k in rep['R_cells'] if 'telemetry' in k]
    assert all(st == 'pending' for c, st in rep['cell_states'].items() if c != 'telemetry')


def test_n1_a_completed_telemetry_cell_is_complete_and_never_stopped(live):
    assert live.telemetry() == 0
    rep = score.score_run(live.run_dir)
    assert rep['cell_states']['telemetry'] == 'complete'
    assert 'telemetry' not in rep['validity']['interrupted'] and 'telemetry' not in rep['validity']['invalid_cells']


def test_n1_convergence_reads_the_sixteen_evaluation_cells_only(tmp_path):
    states = {s['id']: 'complete' for s in score.cell_specs()}
    (tmp_path / 'report.json').write_text(json.dumps({'cell_states': dict(states, telemetry='incomplete')}),
                                          encoding='utf-8')
    score.convergence(tmp_path, tmp_path / 'sealed')  # admitted past the state check: no RuntimeError
    (tmp_path / 'report.json').write_text(json.dumps({'cell_states': {'telemetry': 'complete'}}), encoding='utf-8')
    with pytest.raises(RuntimeError):
        score.convergence(tmp_path, tmp_path / 'sealed')
