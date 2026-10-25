"""A4.14 fail closed execution (docs/design/ozmap-replication-2026-10-24/amendment-4-14-fail-closed.md) and the
round 3 closure items fixed with it (closure-ledger.md). Each test asserts A4.14.1 behavior: a stopped cell is
interrupted for good, its records are preserved and scored, nothing is rerun, dependent cells are interrupted, and no
further cell is admitted unless containment of the stopped cell's outstanding work is established.

Fakes and temporary directories only: no real `codex` or `claude` is resolved or spawned, live mode runs the harness'
own fakes through the real lifecycle code, and no real baseline, run directory, experiment ledger or Codex session
directory is touched. The sealed reviewer ASTs are never read.
"""
import base64
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from bench.ozmap_rep import config, events, gates, isolation, procs, rulings, run, score, workload
from bench.ozmap_rep.tests.test_council_r1 import (Live, attempts, fake_opts, go, sha, stream, write_auth,
                                                  settled_annex, write_d6_annexes)
from bench.ozmap_rep.tests.test_council_r2 import EXECUTED, REFUSED, inject, stamp

CELL = 'codex-materials-cold-A'


@pytest.fixture
def live(tmp_path, monkeypatch):
    return Live(tmp_path, monkeypatch)


def interrupted(run_dir, cell_id):
    path = Path(run_dir) / 'cells' / cell_id / 'INTERRUPTED.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def state(run_dir, cell_id):
    return json.loads((Path(run_dir) / 'cells' / cell_id / 'state.json').read_text(encoding='utf-8'))['state']


def dead_pid():
    p = subprocess.Popen([sys.executable, '-c', 'pass'])
    p.wait()
    return p.pid


def crashed_marker(tmp_path, cell_id, slot, prepared, *, pid, phase='spawned', batch='r1.b01', supervised=True,
                   runner_pid=None):
    """A marker as a dead runner leaves it, in a cell left running (the crash case of A4.14.1)."""
    cell_dir = tmp_path / 'run' / 'cells' / cell_id
    (cell_dir / 'inflight').mkdir(parents=True, exist_ok=True)
    spec = run.spec_by_id(cell_id)
    marker = {'call_id': f'{cell_id}.{batch}.t0', 'attempt_uid': f'uid-{batch}', 'cell': cell_id,
              'backend': spec['backend'], 'workload': spec['workload'], 'wave': spec['wave'], 'arm': spec['arm'],
              'allocation': spec['allocation'], 'batch': batch, 'try': 0, 'reason': 'nominal', 'kind': 'nominal',
              'slot': slot, 'mode': 'fake', 'group': 'dead.g1', 'marker': 'call', 'role': 'call', 'phase': phase,
              'prepared_sha': prepared, 'pid': pid, 'started_at': stamp(), 'job_ids': [], 'records': {},
              'runner_pid': runner_pid or dead_pid(), 'runner_invocation': 'dead-invocation',
              'supervision': {'supervised': supervised, 'mechanism': 'job_object'}}
    (cell_dir / 'inflight' / f"{marker['call_id']}.json").write_text(json.dumps(marker), encoding='utf-8')
    (cell_dir / 'state.json').write_text(json.dumps({'state': 'running', 'cell': cell_id, 'invocations': [
        {'invocation': 'dead-invocation', 'pid': marker['runner_pid']}]}), encoding='utf-8')
    return marker


def refreshed_home(tmp_path, slot, text):
    """A worker home as a killed call leaves it: prepared from the baseline, then its auth.json refreshed."""
    base = tmp_path / 'baseline'
    prepared = sha(base / 'auth.json')
    home = tmp_path / 'run' / 'homes' / f'worker-{slot}'
    home.mkdir(parents=True, exist_ok=True)
    write_auth(home, text)
    (home / 'state.sqlite').write_text('runtime', encoding='utf-8')
    return prepared, sha(home / 'auth.json')


# ============================================================ A4.14.1: interrupted, preserved, never rerun

def test_a414_a_stopped_cell_is_interrupted_and_never_resumed_or_rerun(tmp_path):
    """Replaces the acceptance resume test and test_cli_cell_is_resumable_and_never_repeats_a_completed_call."""
    assert go(tmp_path, CELL, stop_after=2) == config.EXIT_INTERRUPTED
    rows = attempts(tmp_path / 'run', CELL)
    assert len(rows) == 2 and state(tmp_path / 'run', CELL) == 'interrupted'
    rec = interrupted(tmp_path / 'run', CELL)
    assert rec and rec['contained'] is True and not rec['crash']
    assert go(tmp_path, CELL) == config.EXIT_CELL_INTERRUPTED
    assert go(tmp_path, CELL) == config.EXIT_CELL_INTERRUPTED
    assert attempts(tmp_path / 'run', CELL) == rows, 'nothing is rerun and no record changes'
    rep = score.score_run(tmp_path / 'run')
    assert CELL in rep['validity']['interrupted'] and not rep['validity']['invalid_cells']


def test_a414_a_cell_whose_prerequisite_is_interrupted_is_interrupted_without_running(tmp_path, monkeypatch):
    original = run.CellRun.after_group

    def crash(self, group):
        raise KeyboardInterrupt('runner killed after the bootstrap call')
    monkeypatch.setattr(run.CellRun, 'after_group', crash)
    with pytest.raises(KeyboardInterrupt):
        go(tmp_path, 'codex-materials-bootstrap')
    monkeypatch.setattr(run.CellRun, 'after_group', original)
    for cid in ('codex-materials-cold-B', 'codex-materials-cold-C', 'codex-materials-warm-C'):
        assert go(tmp_path, cid) == config.EXIT_INTERRUPTED, cid
        assert interrupted(tmp_path / 'run', cid)['reason'].startswith('prerequisite')
        assert attempts(tmp_path / 'run', cid) == []
        assert go(tmp_path, cid) == config.EXIT_CELL_INTERRUPTED
    assert interrupted(tmp_path / 'run', 'codex-materials-bootstrap')['crash'] is True
    assert go(tmp_path, 'codex-materials-cold-A') == 0, 'an independent cell is admitted after containment'


@pytest.mark.parametrize('kind', ['ok', 'refused', 'executed'])
@pytest.mark.parametrize('crash_at', ['attempt_row', 'captures'])
def test_a414_a_crash_mid_record_preserves_the_call_unsettled_and_never_resends(tmp_path, monkeypatch, kind,
                                                                                crash_at):
    """Replaces test_item3_a_crash_between_capture_call_record_and_attempt_row_never_resends (council round 2):
    without in flight recovery the call is never judged again; its state is unsettled, which is uncertainty whether a
    tool executed, so the cell is invalid, not merely interrupted (A4.14.1, A4.3)."""
    target = f'{CELL}.r1.b02.t0'
    monkeypatch.setattr(run, 'spawn', inject('r1.b02', {'ok': [], 'refused': REFUSED, 'executed': EXECUTED}[kind]))
    original_append, original_captures = run._append, run.write_captures
    st = {}

    def append(run_dir, name, row):
        if crash_at == 'attempt_row' and name == 'attempts.jsonl' and row.get('call_id') == target and not st:
            st['killed'] = True
            raise KeyboardInterrupt('runner killed after the capture, before the attempt row')
        return original_append(run_dir, name, row)

    def captures(run_dir, call_id, stdout, stderr, meta):
        if crash_at == 'captures' and call_id == target and not st:
            st['killed'] = True
            raise KeyboardInterrupt('runner killed after the call record, before the captures')
        return original_captures(run_dir, call_id, stdout, stderr, meta)

    monkeypatch.setattr(run, '_append', append)
    monkeypatch.setattr(run, 'write_captures', captures)
    with pytest.raises(KeyboardInterrupt):
        go(tmp_path, CELL)
    monkeypatch.setattr(run, '_append', original_append)
    monkeypatch.setattr(run, 'write_captures', original_captures)
    assert go(tmp_path, CELL) == config.EXIT_CELL_INTERRUPTED
    rows = [r for r in attempts(tmp_path / 'run', CELL) if r['batch'] == 'r1.b02']
    assert [r['outcome'] for r in rows] == ['unsettled'], 'the batch was resent or judged again'
    rec = interrupted(tmp_path / 'run', CELL)
    assert rec['crash'] and rec['contained'], rec
    assert (tmp_path / 'run' / 'cells' / CELL / 'inflight' / f'{target}.json').exists(), 'marker preserved'
    rep = score.score_run(tmp_path / 'run')
    assert any(target in p for p in rep['validity']['leakage'])
    assert CELL in rep['validity']['invalid_cells'] and CELL not in rep['validity']['interrupted']
    assert rep['cells']['codex/materials/cold/A']['state'] == 'invalid'


def test_a414_an_orphan_without_any_stream_is_unsettled_leakage_and_its_usage_stays_incomplete(tmp_path,
                                                                                            monkeypatch):
    """Replaces test_b3_an_orphan_without_any_stream_is_uncertain_leakage (council round 2)."""
    target = f'{CELL}.r1.b01.t0'
    original = run.CellRun.after_group

    def crash(self, group):
        for c in group:
            if c['call_id'] == target:
                for p in run.raw_paths(self.run_dir, c['slot'], c['call_id']):
                    p.unlink()
        raise KeyboardInterrupt('runner killed; the raw stream of one call is gone')
    monkeypatch.setattr(run.CellRun, 'after_group', crash)
    with pytest.raises(KeyboardInterrupt):
        go(tmp_path, CELL)
    monkeypatch.setattr(run.CellRun, 'after_group', original)
    assert go(tmp_path, CELL) == config.EXIT_CELL_INTERRUPTED
    rows = {r['call_id']: r for r in attempts(tmp_path / 'run', CELL)}
    assert len(rows) == 4 and all(r['outcome'] == 'unsettled' for r in rows.values())
    assert rows[target]['events']['verdict'] == 'uncertain' and rows[target]['kind'] == 'nominal'
    assert not any(r['try'] for r in rows.values()), 'nothing is retried'
    rep = score.score_run(tmp_path / 'run')
    assert any(target in p for p in rep['validity']['leakage'])
    cell = rep['cells']['codex/materials/cold/A']
    assert cell['usage'] == 'incomplete' and cell['state'] == 'invalid'
    obs = rep['unknown_usage_observation']['codex/materials/cold/A']
    assert obs['attempts_with_unknown_usage'] == 4 and 'not an established bound' in obs['label']


def test_a414_a_refreshed_worker_of_a_crashed_call_stops_codex_and_is_never_propagated(tmp_path, monkeypatch):
    """Replaces test_item3_one_refreshed_worker_of_a_killed_call_is_propagated_on_resume and
    test_item3_a_crash_just_before_reconciliation_is_reconciled_on_resume (council round 1): after a crash the A4.2
    hash comparison still runs, but a changed worker is never propagated or restored; Codex stops and the home is
    preserved."""
    original = run.CellRun.reconcile

    def crash(self, workers):
        raise KeyboardInterrupt('runner killed just before reconciliation')
    monkeypatch.setattr(run.CellRun, 'reconcile', crash)
    with pytest.raises(KeyboardInterrupt):
        go(tmp_path, CELL, fake_refresh=1)
    monkeypatch.setattr(run.CellRun, 'reconcile', original)
    before = sha(tmp_path / 'baseline' / 'auth.json')
    assert go(tmp_path, 'codex-boolq-cold-A') == config.EXIT_AUTH_STOP
    assert (tmp_path / 'run' / 'codex-stop.json').exists()
    assert sha(tmp_path / 'baseline' / 'auth.json') == before, 'nothing propagated'
    rec = interrupted(tmp_path / 'run', CELL)
    assert rec['contained'] and any(a['changed'] for a in rec['auth'])
    refreshed = [a for a in rec['auth'] if a['changed']]
    home = tmp_path / 'run' / 'homes' / f"worker-{refreshed[0]['slot']}" / 'auth.json'
    assert b'SECRET-FAKE-REFRESHED' in home.read_bytes(), 'the refreshed home is preserved'
    assert go(tmp_path, CELL) == config.EXIT_CELL_INTERRUPTED
    assert go(tmp_path, 'sonnet-materials-cold-A') == 0, 'containment established: other backends continue'


def test_a414_two_changed_workers_of_crashed_calls_stop_codex_and_keep_the_baseline(tmp_path):
    """Replaces test_item3_two_changed_workers_of_killed_calls_stop_codex_and_keep_the_baseline."""
    fake_opts(tmp_path)
    before = sha(tmp_path / 'baseline' / 'auth.json')
    p1, _ = refreshed_home(tmp_path, 1, 'KILLED-1')
    p2, _ = refreshed_home(tmp_path, 2, 'KILLED-2')
    crashed_marker(tmp_path, CELL, 1, p1, pid=dead_pid(), batch='r1.b01')
    crashed_marker(tmp_path, CELL, 2, p2, pid=dead_pid(), batch='r1.b02')
    assert go(tmp_path, CELL) == config.EXIT_CELL_INTERRUPTED
    assert (tmp_path / 'run' / 'codex-stop.json').exists()
    assert sha(tmp_path / 'baseline' / 'auth.json') == before
    assert [r['outcome'] for r in attempts(tmp_path / 'run')] == ['unsettled', 'unsettled']
    assert not (tmp_path / 'run' / 'run-stop.json').exists()


def test_a414_a_child_still_running_prevents_every_further_admission(tmp_path):
    """Replaces test_item3_a_recorded_child_still_running_stops_the_resume_without_touching_anything: outstanding
    work that may still run is not contained, so the run stops and no further cell is admitted, even after the child
    has ended."""
    fake_opts(tmp_path)
    prepared, refreshed = refreshed_home(tmp_path, 1, 'STILL-RUNNING')
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        crashed_marker(tmp_path, CELL, 1, prepared, pid=child.pid)
        assert go(tmp_path, 'sonnet-materials-cold-A') == config.EXIT_RUN_STOPPED
        stop = json.loads((tmp_path / 'run' / 'run-stop.json').read_text(encoding='utf-8'))
        assert 'still running' in stop['reason']
        home = tmp_path / 'run' / 'homes' / 'worker-1'
        assert sha(home / 'auth.json') == refreshed and (home / 'state.sqlite').exists(), 'home preserved'
        assert list((tmp_path / 'run' / 'cells' / CELL / 'inflight').glob('*.json')), 'marker preserved'
    finally:
        child.kill()
        child.wait()
    for cid in (CELL, 'sonnet-materials-cold-A', 'codex-boolq-cold-A'):
        assert go(tmp_path, cid) == config.EXIT_RUN_STOPPED
    assert [r['outcome'] for r in attempts(tmp_path / 'run')] == ['unsettled']
    rep = score.score_run(tmp_path / 'run')
    assert any('the run is stopped' in p for p in rep['validity']['isolation_problems'])
    assert rep['validity']['isolation'] == 'failed'


@pytest.mark.parametrize('how', ['no_pid', 'unsupervised'])
def test_a414_an_unidentified_or_unsupervised_child_stops_the_run(tmp_path, how):
    """Replaces test_item3_a_marker_without_pid_on_a_started_home_is_ambiguous_and_stops_codex and
    test_item3_a_spawning_marker_without_pid_is_kept_and_its_batch_never_resent."""
    fake_opts(tmp_path)
    prepared, _ = refreshed_home(tmp_path, 1, 'NO-PID')
    crashed_marker(tmp_path, CELL, 1, prepared, pid=None if how == 'no_pid' else dead_pid(),
                   phase='spawning' if how == 'no_pid' else 'spawned', supervised=False)
    assert go(tmp_path, CELL) == config.EXIT_RUN_STOPPED
    assert (tmp_path / 'run' / 'run-stop.json').exists() and (tmp_path / 'run' / 'codex-stop.json').exists()
    assert list((tmp_path / 'run' / 'cells' / CELL / 'inflight').glob('*.json')), 'the marker is kept'
    assert [r['outcome'] for r in attempts(tmp_path / 'run')] == ['unsettled']
    rep = score.score_run(tmp_path / 'run')
    assert rep['validity']['leakage'] and CELL in rep['validity']['invalid_cells']


def test_a414_a_reserved_marker_after_a_crash_is_a_charged_not_launched_attempt(tmp_path):
    """Replaces test_b2_a_reserved_marker_becomes_a_charged_not_launched_attempt (council round 2)."""
    fake_opts(tmp_path)
    crashed_marker(tmp_path, CELL, 1, None, pid=None, phase='reserved')
    assert go(tmp_path, CELL) == config.EXIT_CELL_INTERRUPTED
    rows = attempts(tmp_path / 'run', CELL)
    assert [r['outcome'] for r in rows] == ['not_launched'] and rows[0]['kind'] == 'nominal'
    assert interrupted(tmp_path / 'run', CELL)['contained'] is True
    assert not (tmp_path / 'run' / 'run-stop.json').exists()
    rep = score.score_run(tmp_path / 'run')
    assert rep['validity']['leakage'] == [], 'a call proven never started is no leakage'
    assert not any('without an attempt' in p for p in rep['validity']['accounting_failures'])


def test_a414_a_child_whose_tree_cannot_be_ended_keeps_its_records_and_stops_the_run(tmp_path, monkeypatch):
    """Replaces test_item3_a_communicate_exception_with_a_live_child_keeps_the_home_and_stops_codex: the unsettled
    call keeps its marker, home and raw stream, its accounting obligation is recorded as an unsettled attempt, Codex
    stops, containment is not established and no further cell is admitted."""
    original = subprocess.Popen.communicate
    st = {'pids': []}

    def communicate(self, *a, **k):
        if a and isinstance(a[0], bytes) and not st['pids']:
            st['pids'].append(self.pid)
            raise RuntimeError('waiting failed')
        return original(self, *a, **k)
    original_gone = procs.Tree.gone
    monkeypatch.setattr(subprocess.Popen, 'communicate', communicate)
    monkeypatch.setattr(procs.Tree, 'kill', lambda self: None)
    monkeypatch.setattr(procs.Tree, 'gone', lambda self, seconds=60.0: False if self.proc is not None and
                        self.proc.pid in st['pids'] else original_gone(self, seconds))
    assert go(tmp_path, CELL) == config.EXIT_AUTH_STOP
    assert (tmp_path / 'run' / 'codex-stop.json').exists() and (tmp_path / 'run' / 'run-stop.json').exists()
    markers = [json.loads(p.read_text(encoding='utf-8'))
               for p in (tmp_path / 'run' / 'cells' / CELL / 'inflight').glob('*.json')]
    unsettled = [m for m in markers if m.get('tree_gone') is False]
    assert len(unsettled) == 1, markers
    m = unsettled[0]
    assert (tmp_path / 'run' / 'homes' / f"worker-{m['slot']}" / 'auth.json').exists(), 'home preserved'
    rows = {r['call_id']: r for r in attempts(tmp_path / 'run', CELL)}
    assert len(rows) == 4 and rows[m['call_id']]['outcome'] == 'unsettled'
    monkeypatch.setattr(subprocess.Popen, 'communicate', original)
    assert go(tmp_path, 'sonnet-materials-cold-A') == config.EXIT_RUN_STOPPED
    rep = score.score_run(tmp_path / 'run')
    assert CELL in rep['validity']['invalid_cells']


def test_a414_a_crash_after_the_last_call_leaves_a_bounded_window_and_an_interrupted_cell(tmp_path, monkeypatch):
    """Replaces test_item14_a_crash_before_the_window_closes_keeps_the_work_in_the_gated_makespan (council round 2):
    the crashed invocation's window is closed with bounds only, the cell is interrupted (its comparisons
    inconclusive) and never rerun; with no finding in its records it is not invalid."""
    original = run.CellRun.rule_errors
    st = {}

    def crash(self, result):
        if not st:
            st['done'] = True
            raise KeyboardInterrupt('runner killed after the last attempt, before the window was closed')
        return original(self, result)
    monkeypatch.setattr(run.CellRun, 'rule_errors', crash)
    with pytest.raises(KeyboardInterrupt):
        go(tmp_path, CELL)
    rows = attempts(tmp_path / 'run', CELL)
    assert go(tmp_path, CELL) == config.EXIT_CELL_INTERRUPTED
    windows = run.jsonl(tmp_path / 'run' / 'cells' / CELL / 'windows.jsonl')
    assert any(w.get('reconstructed') and w.get('ended') == 'crashed' for w in windows)
    rep = score.score_run(tmp_path / 'run')
    cell = rep['cells']['codex/materials/cold/A']
    assert cell['timing'] == 'bounded' and cell['makespan_upper_s'] >= max(float(r['elapsed_s']) for r in rows)
    assert cell['state'] == 'interrupted' and CELL in rep['validity']['interrupted']
    assert attempts(tmp_path / 'run', CELL) == rows


def test_a414_a_leakage_signal_stops_the_cell_before_any_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(run, 'spawn', inject('r1.b01', EXECUTED))
    assert go(tmp_path, CELL, fake_fail=1) == config.EXIT_INTERRUPTED
    rows = attempts(tmp_path / 'run', CELL)
    assert len(rows) == 4 and not any(r['try'] for r in rows), 'the infrastructure failure is not retried'
    assert 'leakage signal' in interrupted(tmp_path / 'run', CELL)['reason']
    assert go(tmp_path, CELL) == config.EXIT_CELL_INTERRUPTED
    rep = score.score_run(tmp_path / 'run')
    assert CELL in rep['validity']['invalid_cells']


def test_a414_a_crashed_telemetry_call_is_unsettled_and_blocks_evaluation(live, monkeypatch):
    """Replaces the recovery assertion of test_item4_a_crash_during_the_telemetry_call_keeps_it_charged_and_blocks_
    evaluation (council round 1): the dead runner's telemetry call is unsettled, never judged from its raw stream."""
    original = run.TelemetryRun.after_group
    st = {'n': 0}

    def crash(self, group):
        st['n'] += 1
        if st['n'] == 2:
            raise KeyboardInterrupt('runner killed during the telemetry call')
        return original(self, group)
    monkeypatch.setattr(run.TelemetryRun, 'after_group', crash)
    with pytest.raises(KeyboardInterrupt):
        live.telemetry()
    monkeypatch.setattr(run.TelemetryRun, 'after_group', original)
    assert live.cell(CELL) == config.EXIT_TELEMETRY
    tel = attempts(live.run_dir, 'telemetry')
    assert [a['outcome'] for a in tel] == ['auth_failure', 'unsettled']
    assert len(run.jsonl(live.ledger)) == 2
    assert live.telemetry() == config.EXIT_CELL_INTERRUPTED


# =============================================================== containment before admission, run stop

def test_a414_a_run_stop_admits_no_cell_of_any_backend(tmp_path):
    fake_opts(tmp_path)
    (tmp_path / 'run').mkdir(parents=True, exist_ok=True)
    run.write_run_stop(tmp_path / 'run', CELL, 'test: outstanding work not contained')
    for cid in (CELL, 'sonnet-materials-cold-A', 'codex-boolq-bootstrap'):
        assert go(tmp_path, cid) == config.EXIT_RUN_STOPPED
    assert attempts(tmp_path / 'run') == []


# ========================================================== Astra council round 3 items fixed with A4.14

def test_item10_a_killed_child_without_terminal_evidence_is_unsettled_not_retried(tmp_path, monkeypatch):
    original = subprocess.Popen.communicate
    st = {'pids': []}

    def communicate(self, *a, **k):
        if a and isinstance(a[0], bytes) and not st['pids']:
            st['pids'].append(self.pid)
            raise RuntimeError('waiting failed')
        return original(self, *a, **k)
    monkeypatch.setattr(subprocess.Popen, 'communicate', communicate)
    assert go(tmp_path, CELL) == config.EXIT_AUTH_STOP
    rows = attempts(tmp_path / 'run', CELL)
    killed = [r for r in rows if 'waiting for the child raised' in (r.get('why') or '')]
    assert len(killed) == 1 and killed[0]['outcome'] == 'unsettled', [(r['outcome'], r.get('why')) for r in rows]
    assert killed[0]['events']['verdict'] == 'uncertain'
    assert not any(r['try'] for r in rows), 'never retried'
    assert interrupted(tmp_path / 'run', CELL)['contained'] is True, 'the killed tree was shown gone'
    rep = score.score_run(tmp_path / 'run')
    assert any(killed[0]['call_id'] in p for p in rep['validity']['leakage'])
    assert not [p for p in rep['validity']['artifact_problems'] if killed[0]['call_id'] in p]


def test_item9_a_sibling_refresh_is_never_propagated_beside_a_call_that_did_not_settle(tmp_path, monkeypatch):
    original = subprocess.Popen.communicate
    st = {'n': 0}

    def communicate(self, *a, **k):
        if a and isinstance(a[0], bytes):
            st['n'] += 1
            if st['n'] == 2:
                raise RuntimeError('waiting failed')
        return original(self, *a, **k)
    monkeypatch.setattr(subprocess.Popen, 'communicate', communicate)
    code = go(tmp_path, CELL, fake_refresh=1)
    assert code == config.EXIT_AUTH_STOP
    assert b'SECRET-FAKE-REFRESHED' not in (tmp_path / 'baseline' / 'auth.json').read_bytes(), 'propagated'
    rows = run.jsonl(tmp_path / 'run' / 'evidence' / 'auth-reconcile.jsonl')
    assert rows and rows[-1]['action'] == 'stop_codex'


def test_item9_a_descendant_that_outlives_its_parent_is_ended_with_the_tree():
    tree = procs.Tree()
    code = ('import subprocess, sys; subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], '
            'stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)')
    try:
        proc = tree.start([sys.executable, '-c', code], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)
        assert tree.supervised, tree.problem
        tree.resume()
        proc.communicate(timeout=60)
        assert tree.active() == 1, 'the grandchild outlived its parent'
        tree.kill()
        assert tree.gone(20) and tree.active() == 0
    finally:
        tree.close()


def test_item11_a_failed_ledger_append_inside_a_reservation_keeps_every_debit(live, monkeypatch):
    """Opus council round 3, C5, and Astra item 11: a reservation that fails after its first marker keeps each
    reserved member as a charged `not_launched` attempt with its ledger row; both directions of the ledger reconcile
    and later cells are not refused."""
    assert live.telemetry() == 0
    original = run._append_file
    st = {'n': 0}

    def append_file(path, row):
        if Path(path) == live.ledger and row.get('cell') == CELL and row.get('outcome') == 'reserved' \
                and not row.get('recorded_at_stop'):
            st['n'] += 1
            if st['n'] == 2:
                raise isolation.LockTimeout('ledger lock held by another process')
        return original(path, row)
    monkeypatch.setattr(run, '_append_file', append_file)
    code = live.cell(CELL)
    monkeypatch.setattr(run, '_append_file', original)
    assert code == config.EXIT_INCOMPLETE
    rows = attempts(live.run_dir, CELL)
    assert len(rows) == 4 and {r['outcome'] for r in rows} == {'not_launched'}
    ledger = [r for r in run.jsonl(live.ledger) if r.get('cell') == CELL]
    assert {r['attempt_uid'] for r in ledger} == {r['attempt_uid'] for r in rows}
    assert run.ledger_problems(live.run_dir, live.ledger) == []
    assert live.cell(CELL) == config.EXIT_CELL_INTERRUPTED
    assert live.cell('sonnet-materials-cold-A') == 0


def test_item11_a_live_attempt_missing_from_the_ledger_is_an_accounting_failure(live):
    assert live.cell('sonnet-materials-cold-A') == 0
    rows = run.jsonl(live.ledger)
    live.ledger.write_text(''.join(json.dumps(r) + '\n' for r in rows[1:]), encoding='utf-8')
    rep = score.score_run(live.run_dir)
    assert any('missing from the experiment ledger' in p for p in rep['validity']['accounting_failures'])


def test_item12_a_manifest_changed_while_the_guard_is_taken_is_refused(tmp_path, monkeypatch):
    original = isolation.executable_identity
    st = {'n': 0}

    def identity(exe):
        ident = original(exe)
        st['n'] += 1
        if st['n'] == 3:  # the second hash of the first launch group, taken under the guard
            ident = dict(ident, sha256='0' * 64)
        return ident
    monkeypatch.setattr(isolation, 'executable_identity', identity)
    assert go(tmp_path, CELL) == config.EXIT_FREEZE
    assert attempts(tmp_path / 'run', CELL) == [] and run.jsonl(tmp_path / 'run' / 'fake_calls.jsonl') == []


def test_item14_a_baseline_reseeded_after_the_gate_with_a_short_expiry_is_refused_at_reservation(tmp_path,
                                                                                               monkeypatch):
    original = run.CellRun.prepare_call
    st = {}

    def prepare(self, *a, **k):
        if not st:
            st['done'] = True
            exp = int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).timestamp())
            b64 = lambda d: base64.urlsafe_b64encode(d).rstrip(b'=').decode()  # noqa: E731
            token = '.'.join([b64(b'{"alg":"none"}'), b64(json.dumps({'exp': exp}).encode()), b64(b'x')])
            doc = {'auth_mode': 'chatgpt', 'tokens': {'id_token': 'x', 'access_token': token,
                                                      'refresh_token': 'RESEEDED-SHORT'},
                   'last_refresh': stamp()}
            (self.opts.baseline / 'auth.json').write_text(json.dumps(doc), encoding='utf-8')
        return original(self, *a, **k)
    monkeypatch.setattr(run.CellRun, 'prepare_call', prepare)
    assert go(tmp_path, CELL) == config.EXIT_AUTH_GATE
    assert attempts(tmp_path / 'run', CELL) == [] and run.jsonl(tmp_path / 'run' / 'fake_calls.jsonl') == []
    assert b'RESEEDED-SHORT' in (tmp_path / 'baseline' / 'auth.json').read_bytes(), 'the reseed is kept'
    assert run.jsonl(tmp_path / 'run' / 'evidence' / 'reservation-gates.jsonl')[-1]['ok'] is False


def test_item15_a_probe_disclosure_fails_isolation_and_certification(live, monkeypatch):
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
    assert interrupted(live.run_dir, CELL), 'the isolation signal stops the cell'
    rows = run.jsonl(live.run_dir / 'evidence' / 'probe-disclosures.jsonl')
    assert rows and rows[0]['redaction']['channels']['stderr']['original_sha256'] != \
        rows[0]['redaction']['channels']['stderr']['sanitized_sha256']
    assert run.telemetry_problems(live.run_dir)
    rep = score.score_run(live.run_dir)
    assert rep['validity']['isolation'] == 'failed'
    assert any('probe' in p for p in rep['validity']['isolation_problems'])
    # closure round 1 (O4): the cell stopped by its probe disclosure is invalid, never "interrupted, no finding"
    assert rep['cell_states'][CELL] == 'invalid'
    assert CELL in rep['validity']['invalid_cells'] and CELL not in rep['validity']['interrupted']


def test_item15_a_capture_redaction_is_isolation_failure_whatever_the_attempt_flag_says(tmp_path):
    assert go(tmp_path, CELL) == 0
    meta = sorted((tmp_path / 'run' / 'captures').glob('*.meta.json'))[0]
    doc = json.loads(meta.read_text(encoding='utf-8'))
    doc['redaction'] = dict(doc.get('redaction') or {}, redactions=1)
    meta.write_text(json.dumps(doc), encoding='utf-8')
    rep = score.score_run(tmp_path / 'run')
    assert rep['validity']['isolation'] == 'failed'


@pytest.mark.parametrize('what', ['records', 'job_order'])
def test_item16_the_scorer_reconstructs_records_and_job_order_from_the_prompt(tmp_path, what):
    assert go(tmp_path, CELL) == 0
    path = tmp_path / 'run' / 'attempts.jsonl'
    rows = run.jsonl(path)
    if what == 'records':
        ops = sorted(rows[0]['records'])
        rows[0]['records'] = dict(rows[0]['records'], **{ops[0]: rows[0]['records'][ops[0]] + 5})
    else:
        ids = rows[0]['job_ids']
        rows[0]['job_ids'] = [ids[1], ids[0]] + ids[2:]
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    problems = score.score_run(tmp_path / 'run')['validity']['artifact_problems']
    assert any(rows[0]['call_id'] in p for p in problems), problems[:3]


def test_item16_a_deleted_audit_is_detected(tmp_path, monkeypatch):
    from bench.ozmap_rep.tests.test_rule_path import UNKNOWN_ONLY, inject_rule
    assert go(tmp_path, 'codex-materials-bootstrap') == 0
    inject_rule(tmp_path, UNKNOWN_ONLY)
    assert go(tmp_path, 'codex-materials-cold-C') == 0
    monkeypatch.setattr(score, '_rule_asts', lambda results, prefix, boot_props=None: {'temp_class': UNKNOWN_ONLY})
    assert not [x for x in score.score_run(tmp_path / 'run')['validity']['artifact_problems'] if 'audit set' in x]
    p = tmp_path / 'run' / 'cells' / 'codex-materials-cold-C' / 'result.json'
    doc = json.loads(p.read_text(encoding='utf-8'))
    if not doc.get('audits'):
        pytest.skip('the injected rule covers no job in this workload')
    doc['audits'].pop(next(iter(doc['audits'])))
    p.write_text(json.dumps(doc), encoding='utf-8')
    problems = score.score_run(tmp_path / 'run')['validity']['artifact_problems']
    assert any('audit set' in x for x in problems)


def test_item17_makespan_bounds_round_outward(tmp_path):
    assert go(tmp_path, CELL) == 0
    cell = score.score_run(tmp_path / 'run')['cells']['codex/materials/cold/A']
    lo, hi = cell['makespan_lower_s'], cell['makespan_upper_s']
    assert lo <= hi
    assert abs(lo * 1000 - round(lo * 1000)) < 1e-6 and abs(hi * 1000 - round(hi * 1000)) < 1e-6
    assert hi >= cell['makespan_s'] - 0.0005 and lo <= cell['makespan_s'] + 0.0005


@pytest.mark.parametrize('change', ['no_turns', 'two_models', 'other_model', 'no_denials'])
def test_item23_the_sonnet_route_is_checked_by_the_harness_itself(monkeypatch, change):
    usage = {'inputTokens': 1, 'outputTokens': 1, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0}
    env = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'OZ/1g', 'num_turns': 1,
           'permission_denials': [], 'modelUsage': {config.SONNET_MODEL: usage}}
    assert events.classify_claude(env)['verdict'] == 'plain'
    monkeypatch.setenv('OZ_MODEL', '')  # the adapter's own model check is disabled by the parent environment
    if change == 'no_turns':
        env.pop('num_turns')
    elif change == 'two_models':
        env['modelUsage'] = dict(env['modelUsage'], **{'claude-haiku-4': usage})
    elif change == 'other_model':
        env['modelUsage'] = {'claude-opus-4': usage}
    else:
        env.pop('permission_denials')
    assert events.classify_claude(env)['verdict'] == 'uncertain'


def test_a414_a_validity_failure_is_never_labeled_inconclusive():
    cell = {'state': 'interrupted', 'usage': 'incomplete', 'jobs': 4, 'correct': 4, 'tokens': 10,
            'makespan_s': 1.0, 'unresolved': 0}
    summary = {'cells': {'codex/boolq/cold/A': dict(cell, state='complete', usage='complete'),
                         'codex/boolq/cold/C': cell},
               'validity': {'isolation': 'passed', 'leakage': ['x: tool event verdict executed'],
                            'bootstrap': {'codex/boolq': {'efficiency_valid': True, 'completion_failure': False}}}}
    g = gates.boolq_gate(summary)
    assert g['inconclusive'] and g['verdict'] == 'invalid'


# ============================================================================ Astra council round 3, item 1

def test_item1_readiness_binds_each_ruling_to_its_approved_annexes(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'SIGNED_CLI_NOTICES', (config.P4_CANDIDATE_NOTICE,))
    monkeypatch.setattr(config, 'SIGNED_CLI_NOTICE_EVENT_KEYS', ('type', 'item'))
    monkeypatch.setattr(config, 'SIGNED_CLI_NOTICE_ID_RE', r'item_[0-9]+')
    manifest = tmp_path / 'startup-manifest.json'
    manifest.write_text(json.dumps({'files': [{'path': 'skills/.system/x/SKILL.md', 'sha256': 'a' * 64}]}),
                        encoding='utf-8')
    monkeypatch.setattr(config, 'STARTUP_MANIFEST_FILE', manifest)
    files = {'quota_source_manifest': tmp_path / 'p3.json', 'cli_notice_annex': tmp_path / 'p4.json',
             'startup_manifest': manifest, 'effective_context_evidence': tmp_path / 'p5-context.json',
             'attribution_evidence': tmp_path / 'd1.json', **write_d6_annexes(tmp_path / 'd6')}
    files['cli_notice_annex'].write_text(json.dumps(rulings.cli_notice_config()), encoding='utf-8')
    for k in ('quota_source_manifest', 'effective_context_evidence', 'attribution_evidence'):
        files[k].write_text(json.dumps(settled_annex(k)), encoding='utf-8')
    slots = {}
    for name in config.REQUIRED_RULINGS:
        kinds = rulings.ANNEXES_REQUIRED.get(name, ())
        annexes = {k: {'path': str(files[k]), 'sha256': sha(files[k])} for k in kinds}
        f = tmp_path / f'{name}.md'
        f.write_text(f'{name} ruling\n' + ''.join(f'{k} sha256 {a["sha256"]}\n' for k, a in annexes.items())
                     + 'Signed: Astra A\nSigned: Opus B\n', encoding='utf-8')
        slots[name] = {'path': str(f), 'sha256': sha(f), 'annexes': annexes}
    disable = ['--disable', 'code_mode_host']
    assert rulings.readiness_problems(disable, slots) == []
    # an annex substituted after signing, each one on its own, blocks the freeze
    for kind, path in files.items():
        saved = path.read_bytes()
        path.write_bytes(saved + b' ')
        assert any(kind in p for p in rulings.readiness_problems(disable, slots)), kind
        path.write_bytes(saved)
    assert rulings.readiness_problems(disable, slots) == []
    # a configured predicate that is not the approved annex blocks it too
    monkeypatch.setattr(config, 'SIGNED_CLI_NOTICE_ID_RE', r'item_[0-9a-z]+')
    assert any('CLI notice predicate' in p for p in rulings.readiness_problems(disable, slots))
    monkeypatch.setattr(config, 'SIGNED_CLI_NOTICE_ID_RE', r'item_[0-9]+')
    # a missing annex binding blocks it
    slots['D1'] = {k: v for k, v in slots['D1'].items() if k != 'annexes'}
    assert any('attribution_evidence' in p for p in rulings.readiness_problems(disable, slots))


def test_item13_a_probe_whose_pid_cannot_be_journaled_stops_codex_and_propagates_nothing(live, monkeypatch):
    assert live.telemetry() == 0
    before = sha(live.base / 'auth.json')
    original = run.CellRun.probe_marker

    def probe_marker(self, name, slot, prepared_sha):
        marker, path, on_start = original(self, name, slot, prepared_sha)

        def failing(pid):
            raise OSError('the probe marker could not be written')
        return marker, path, failing
    monkeypatch.setattr(run.CellRun, 'probe_marker', probe_marker)
    assert live.cell(CELL) == config.EXIT_AUTH_STOP
    assert (live.run_dir / 'codex-stop.json').exists()
    assert sha(live.base / 'auth.json') == before, 'nothing propagated'
    assert attempts(live.run_dir, CELL) == []
    assert interrupted(live.run_dir, CELL), 'the probe failure stops the cell'
    assert not (live.run_dir / 'run-stop.json').exists(), 'the probe tree was ended before it ran'


def test_item4_a_malformed_scalar_latest_reading_blocks_and_never_falls_back(tmp_path):
    from bench.ozmap_rep import quota
    folder = tmp_path / 'sessions' / '2026' / '10' / '25'
    folder.mkdir(parents=True)
    rows = [{'timestamp': stamp(), 'type': 'event_msg',
             'payload': {'type': 'token_count', 'rate_limits': {'primary': {'used_percent': 10.0}}}},
            {'timestamp': stamp(), 'type': 'event_msg', 'payload': {'type': 'token_count', 'rate_limits': 5}}]
    (folder / 'rollout.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    g = quota.coverage_gate([], tmp_path / 'sessions')
    assert not g['ok'] and g['owner_source'].endswith('rollout.jsonl')


def test_item16_warm_C_reuses_only_a_rule_cold_C_adopted(tmp_path, monkeypatch):
    from bench.ozmap_rep.tests.test_rule_path import UNKNOWN_ONLY, inject_rule
    assert go(tmp_path, 'codex-materials-bootstrap') == 0
    inject_rule(tmp_path, UNKNOWN_ONLY)
    assert go(tmp_path, 'codex-materials-cold-C') == 0
    assert go(tmp_path, 'codex-materials-warm-C') == 0
    warm = json.loads((tmp_path / 'run' / 'cells' / 'codex-materials-warm-C' / 'result.json').read_text(
        encoding='utf-8'))
    if not any(r.get('source') == 'rule' for r in warm['answers'].values()):
        pytest.skip('the injected rule was not adopted in this workload')
    # the injected rule is not in the bootstrap capture; stand in for an admitted rule the capture holds
    monkeypatch.setattr(score, '_rule_asts', lambda results, prefix, boot_props=None: {'temp_class': UNKNOWN_ONLY})
    cold_path = tmp_path / 'run' / 'cells' / 'codex-materials-cold-C' / 'result.json'
    assert not [p for p in score.score_run(tmp_path / 'run')['validity']['artifact_problems']
                if 'warm-C' in p and 'rule answer' in p]
    cold = json.loads(cold_path.read_text(encoding='utf-8'))
    cold['rule_status'] = {op: 'quarantined' for op in cold['rule_status']}
    cold_path.write_text(json.dumps(cold), encoding='utf-8')
    problems = score.score_run(tmp_path / 'run')['validity']['artifact_problems']
    assert any('warm-C' in p and 'without an admitted rule' in p for p in problems), problems[:3]
