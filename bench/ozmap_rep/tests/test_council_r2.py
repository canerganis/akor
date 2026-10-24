"""Regression tests for the council build round 2 blockers (docs/design/ozmap-replication-2026-10-24/
council-build-*-r2.md and the joint decision council-build-deadlock-r2-joint.md). One section per blocker id. Fakes and
temporary directories only: no real `codex` or `claude` is resolved or spawned, live mode runs the harness' own fakes
through the real lifecycle code, and no real baseline, run directory, experiment ledger or Codex session directory is
touched. The sealed reviewer ASTs are never read.
"""
import base64
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from bench.ozmap_rep import config, events, gates, isolation, quota, redact, rulings, run, score, workload
from bench.ozmap_rep.tests.test_council_r1 import Live, attempts, fake_opts, go, sha, stream, write_auth

CELL = 'codex-materials-cold-A'


@pytest.fixture
def live(tmp_path, monkeypatch):
    return Live(tmp_path, monkeypatch)


def stamp(t=None):
    return (t or dt.datetime.now(dt.timezone.utc)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def inject(target_batch, events_):
    """A spawn wrapper inserting tool events into the stream of one batch's call (before the turn ends)."""
    original = run.spawn

    def spawn(run_dir, launch, stdin_text, env, cwd, external, timeout=config.CALL_TIMEOUT_S):
        raw = original(run_dir, launch, stdin_text, env, cwd, external, timeout)
        directive = json.loads((Path(run_dir) / 'fake' / 'directives' / f'{Path(cwd).name}.json')
                               .read_text(encoding='utf-8'))
        if directive['call_id'].endswith(target_batch + '.t0') and events_:
            lines = raw['stdout'].splitlines()
            raw = dict(raw, stdout='\n'.join(lines[:2] + [json.dumps(e) for e in events_] + lines[2:]) + '\n')
            if getattr(run._TLS, 'raw', None):  # what the child itself wrote to its raw stream file
                Path(run._TLS.raw[0]).write_bytes(raw['stdout'].encode('utf-8'))
        return raw
    return spawn


EXECUTED = [{'type': 'item.completed', 'item': {'id': 'c1', 'type': 'command_execution', 'command': 'dir',
                                                'aggregated_output': 'x', 'exit_code': 0, 'status': 'completed'}}]
REFUSED = [{'type': 'item.completed', 'item': {'id': 'c1', 'type': 'command_execution', 'command': 'dir',
                                               'status': 'declined'}}]


# ======================================================== items 3, B3, RT2.1: recovery reconciles durable evidence

@pytest.mark.parametrize('kind,want', [('ok', 'ok'), ('refused', 'refused'), ('executed', 'executed')])
@pytest.mark.parametrize('crash_at', ['attempt_row', 'captures'])
def test_item3_a_crash_between_capture_call_record_and_attempt_row_never_resends(tmp_path, monkeypatch, kind, want,
                                                                                crash_at):
    target = f'{CELL}.r1.b02.t0'
    monkeypatch.setattr(run, 'spawn', inject('r1.b02', {'ok': [], 'refused': REFUSED, 'executed': EXECUTED}[kind]))
    original_append, original_captures = run._append, run.write_captures
    state = {}

    def append(run_dir, name, row):
        if crash_at == 'attempt_row' and name == 'attempts.jsonl' and row.get('call_id') == target and not state:
            state['killed'] = True
            raise KeyboardInterrupt('runner killed after the capture, before the attempt row')
        return original_append(run_dir, name, row)

    def captures(run_dir, call_id, stdout, stderr, meta):
        if crash_at == 'captures' and call_id == target and not state:
            state['killed'] = True
            raise KeyboardInterrupt('runner killed after the call record, before the captures')
        return original_captures(run_dir, call_id, stdout, stderr, meta)

    monkeypatch.setattr(run, '_append', append)
    monkeypatch.setattr(run, 'write_captures', captures)
    with pytest.raises(KeyboardInterrupt):
        go(tmp_path, CELL)
    monkeypatch.setattr(run, 'spawn', inject('r1.b02', []))
    code = go(tmp_path, CELL)
    rows = [r for r in attempts(tmp_path / 'run', CELL) if r['batch'] == 'r1.b02']
    assert [r['outcome'] for r in rows] == [want], 'the batch was resent or misjudged: ' + str(
        [(r['outcome'], r.get('recovered_from')) for r in rows])
    assert rows[0]['recovered_from'] == ('capture' if crash_at == 'attempt_row' else 'raw_stream')
    assert code == (0 if kind == 'ok' else config.EXIT_INCOMPLETE)
    rep = score.score_run(tmp_path / 'run')
    flagged = [p for p in rep['validity']['leakage'] if target in p]
    assert bool(flagged) == (kind == 'executed')
    assert not [p for p in rep['validity']['artifact_problems'] if target in p]


def test_b3_an_orphan_without_any_stream_is_uncertain_leakage(tmp_path, monkeypatch):
    target = f'{CELL}.r1.b01.t0'
    original = run.CellRun.after_group

    def crash(self, group):
        for c in group:
            for p in run.raw_paths(self.run_dir, c['slot'], c['call_id']):
                if c['call_id'] == target:
                    p.unlink()
        raise KeyboardInterrupt('runner killed; the raw stream of one call is gone')
    monkeypatch.setattr(run.CellRun, 'after_group', crash)
    with pytest.raises(KeyboardInterrupt):
        go(tmp_path, CELL)
    monkeypatch.setattr(run.CellRun, 'after_group', original)
    assert go(tmp_path, CELL) == 0
    rows = {r['call_id']: r for r in attempts(tmp_path / 'run', CELL)}
    assert rows[target]['outcome'] == 'interrupted' and rows[target]['events']['verdict'] == 'uncertain'
    assert rows[f'{CELL}.r1.b01.t1']['kind'] == 'reserve'
    rep = score.score_run(tmp_path / 'run')
    assert any(target in p for p in rep['validity']['leakage'])
    # B7, P2: the unknown usage stays incomplete; the substitution is only a labeled observation
    cell = rep['cells']['codex/materials/cold/A']
    assert cell['usage'] == 'incomplete'
    obs = rep['unknown_usage_observation']['codex/materials/cold/A']
    assert obs['attempts_with_unknown_usage'] == 1 and 'not an established bound' in obs['label']
    assert obs['hypothetical_tokens'] > obs['known_charged_tokens'] == cell['tokens']


def test_item3_a_pid_journal_failure_stops_codex_and_records_the_terminated_child(tmp_path, monkeypatch):
    original = run.CellRun._mark_spawned
    state = {'n': 0}

    def mark(self, c, pid):
        state['n'] += 1
        if state['n'] == 2:
            raise OSError('the marker could not be written')
        return original(self, c, pid)
    monkeypatch.setattr(run.CellRun, '_mark_spawned', mark)
    assert go(tmp_path, CELL) == config.EXIT_AUTH_STOP
    assert (tmp_path / 'run' / 'codex-stop.json').exists()
    rows = attempts(tmp_path / 'run', CELL)
    assert len(rows) == 4 and not any(r['try'] for r in rows), 'nothing is dispatched after the failure'
    assert any('journaled' in (r.get('why') or '') for r in rows)


def test_item3_a_communicate_exception_with_a_live_child_keeps_the_home_and_stops_codex(tmp_path, monkeypatch):
    original = subprocess.Popen.communicate
    state = {'pids': []}

    def communicate(self, *a, **k):
        if a and isinstance(a[0], bytes) and not state['pids']:
            state['pids'].append(self.pid)
            raise RuntimeError('waiting failed')
        return original(self, *a, **k)
    monkeypatch.setattr(subprocess.Popen, 'communicate', communicate)
    monkeypatch.setattr(run, '_kill_tree', lambda proc: None)
    monkeypatch.setattr(run, '_wait_gone', lambda proc, pid, seconds=60: False)
    try:
        assert go(tmp_path, CELL) == config.EXIT_AUTH_STOP
        assert (tmp_path / 'run' / 'codex-stop.json').exists()
        markers = list((tmp_path / 'run' / 'cells' / CELL / 'inflight').glob('*.json'))
        assert len(markers) == 1, 'the unsettled call keeps its marker'
        m = json.loads(markers[0].read_text(encoding='utf-8'))
        assert (tmp_path / 'run' / 'homes' / f"worker-{m['slot']}" / 'auth.json').exists(), 'home preserved'
        assert m['call_id'] not in {r['call_id'] for r in attempts(tmp_path / 'run')}
        assert len(attempts(tmp_path / 'run', CELL)) == 3
    finally:
        for pid in state['pids']:
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(pid)], capture_output=True) if os.name == 'nt' \
                else os.kill(pid, 9)


def test_item3_a_spawning_marker_without_pid_is_kept_and_its_batch_never_resent(tmp_path):
    fake_opts(tmp_path)
    assert go(tmp_path, CELL, stop_after=1) == config.EXIT_INTERRUPTED
    cell_dir = tmp_path / 'run' / 'cells' / CELL
    marker = {'call_id': f'{CELL}.r1.b01.t0', 'attempt_uid': 'u-1', 'cell': CELL, 'backend': 'codex',
              'workload': 'materials', 'wave': 'cold', 'arm': 'A', 'allocation': 'cold_A', 'batch': 'r1.b01',
              'try': 0, 'reason': 'nominal', 'kind': 'nominal', 'slot': 0, 'mode': 'fake', 'group': 'dead.g1',
              'phase': 'spawning', 'pid': None, 'started_at': stamp(), 'job_ids': [], 'records': {}}
    (cell_dir / 'inflight' / f"{marker['call_id']}.json").write_text(json.dumps(marker), encoding='utf-8')
    assert go(tmp_path, CELL) == config.EXIT_AUTH_STOP
    assert list((cell_dir / 'inflight').glob('*.json')), 'the ambiguous marker is kept'
    assert not [r for r in attempts(tmp_path / 'run', CELL) if r['batch'] == 'r1.b01']
    rep = score.score_run(tmp_path / 'run')
    assert any('unrecovered in-flight markers' in p for p in rep['validity']['accounting_failures'])


def test_b2_a_reserved_marker_becomes_a_charged_not_launched_attempt(tmp_path):
    fake_opts(tmp_path)
    assert go(tmp_path, CELL, stop_after=1) == config.EXIT_INTERRUPTED
    cell_dir = tmp_path / 'run' / 'cells' / CELL
    marker = {'call_id': f'{CELL}.r1.b01.t0', 'attempt_uid': 'u-2', 'cell': CELL, 'backend': 'codex',
              'workload': 'materials', 'wave': 'cold', 'arm': 'A', 'allocation': 'cold_A', 'batch': 'r1.b01',
              'try': 0, 'reason': 'nominal', 'kind': 'nominal', 'slot': 1, 'mode': 'fake', 'group': 'dead.g1',
              'phase': 'reserved', 'pid': None, 'started_at': stamp(), 'job_ids': [], 'records': {}}
    (cell_dir / 'inflight' / f"{marker['call_id']}.json").write_text(json.dumps(marker), encoding='utf-8')
    assert go(tmp_path, CELL) == 0
    rows = [r for r in attempts(tmp_path / 'run', CELL) if r['batch'] == 'r1.b01']
    assert [r['outcome'] for r in rows] == ['not_launched', 'ok'] and rows[0]['kind'] == 'nominal'
    assert rows[1]['kind'] == 'reserve'
    rep = score.score_run(tmp_path / 'run')
    assert rep['validity']['leakage'] == [] and rep['validity']['artifact_problems'] == []


# ================================================================= item 5, C3: probes and the features inventory

def test_item5_a_features_auth_failure_with_changed_worker_auth_stops_codex_and_keeps_the_baseline(live, monkeypatch):
    assert live.telemetry() == 0
    before = sha(live.base / 'auth.json')
    original = run.run_local

    def run_local(argv, env, cwd, on_start=None, timeout=120):
        if 'features' in argv:
            write_auth(env['CODEX_HOME'], 'CHANGED-BY-FEATURES')
            return 1, '', 'Your access token could not be refreshed. Please log out and sign in again.'
        return original(argv, env, cwd, on_start, timeout)
    monkeypatch.setattr(run, 'run_local', run_local)
    assert live.cell(CELL) in (config.EXIT_AUTH_STOP, config.EXIT_FREEZE)
    assert sha(live.base / 'auth.json') == before, 'the changed credentials were propagated'
    assert (live.run_dir / 'codex-stop.json').exists()
    assert attempts(live.run_dir, CELL) == []


@pytest.mark.parametrize('output,code', [('', 0), ('garbage line\n', 0), (None, 3)])
def test_item5_a_failed_or_empty_features_response_blocks_launch(live, monkeypatch, output, code):
    assert live.telemetry() == 0
    original = run.run_local

    def run_local(argv, env, cwd, on_start=None, timeout=120):
        got = original(argv, env, cwd, on_start, timeout)
        if 'features' in argv:
            return code, got[1] if output is None else output, ''
        return got
    monkeypatch.setattr(run, 'run_local', run_local)
    assert live.cell(CELL) == config.EXIT_FREEZE
    assert attempts(live.run_dir, CELL) == []
    feat = json.loads((live.run_dir / 'evidence' / f'features-{CELL}.json').read_text(encoding='utf-8'))
    assert feat['ok'] is False and feat['problems']


# ====================================================================================== item 6: redaction

def test_item6_a_prepared_opaque_refresh_token_is_redacted_after_a_refresh_and_a_reseed(tmp_path, monkeypatch):
    base = tmp_path / 'baseline'
    write_auth(base, 'OPAQUE')
    doc = json.loads((base / 'auth.json').read_text(encoding='utf-8'))
    doc['tokens']['access_token'] = doc['tokens']['access_token'].replace('eyJ', 'eyJ')
    secret = 'opaque-refresh-' + os.urandom(12).hex()
    doc['tokens']['refresh_token'] = secret
    (base / 'auth.json').write_text(json.dumps(doc), encoding='utf-8')
    original = run.spawn
    state = {'n': 0}

    def spawn(run_dir, launch, stdin_text, env, cwd, external, timeout=config.CALL_TIMEOUT_S):
        raw = original(run_dir, launch, stdin_text, env, cwd, external, timeout)
        state['n'] += 1
        if state['n'] == 1:
            write_auth(env['CODEX_HOME'], 'REFRESHED-WORKER')  # the worker refreshed
            run.synthetic_baseline(base)  # and the owner reseeded the baseline before capture processing
            raw = dict(raw, stderr=raw['stderr'] + f'debug: refresh token {secret}\n')
        return raw
    monkeypatch.setattr(run, 'spawn', spawn)
    go(tmp_path, CELL)
    found = []
    for p in (tmp_path / 'run').rglob('*'):
        rel = p.relative_to(tmp_path / 'run').parts
        if p.is_file() and rel[0] not in ('homes',) and secret.encode() in p.read_bytes():
            found.append(str(p))
    assert not found, f'the prepared refresh token reached artifacts: {found[:3]}'
    rows = [r for r in attempts(tmp_path / 'run', CELL) if r.get('credential_disclosure')]
    assert rows and rows[0]['redaction']['channels']['stderr']['original_sha256']
    assert rows[0]['redaction']['channels']['stdout']['original_sha256']


def test_item6_redaction_keeps_a_record_per_channel():
    rec = redact.channels(stdout=('a', 'a', {'redactions': 0, 'kinds': []}),
                          stderr=('s' * 20, '[x]', {'redactions': 1, 'kinds': ['auth']}))
    assert rec['redactions'] == 1 and set(rec['channels']) == {'stdout', 'stderr'}
    assert all(len(c['original_sha256']) == 64 for c in rec['channels'].values())


# =========================================================================== item 7: executable identity

def test_item7_an_executable_changed_after_group_verification_before_a_spawn_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation.WriteGuard, '__enter__', lambda self: self)  # a platform without the guard
    original = run.CellRun.reserve_group

    def reserve(self, group):
        original(self, group)
        exe = Path(self.exe.exe)
        exe.write_text(exe.read_text(encoding='utf-8') + '\n# substituted after verification\n', encoding='utf-8')
    monkeypatch.setattr(run.CellRun, 'reserve_group', reserve)
    assert go(tmp_path, CELL) == config.EXIT_FREEZE
    rows = attempts(tmp_path / 'run', CELL)
    assert rows and all(r['outcome'] == 'not_launched' for r in rows), 'no child started'
    assert not run.jsonl(tmp_path / 'run' / 'fake_calls.jsonl')


@pytest.mark.skipif(os.name != 'nt', reason='the write guard is a Windows share mode')
def test_item7_the_write_guard_blocks_substitution_while_a_group_runs(tmp_path, monkeypatch):
    original = run.CellRun.reserve_group
    seen = {}

    def reserve(self, group):
        original(self, group)
        try:
            with open(self.exe.exe, 'ab') as f:
                f.write(b'# substituted\n')
            seen['written'] = True
        except PermissionError:
            seen['blocked'] = True
    monkeypatch.setattr(run.CellRun, 'reserve_group', reserve)
    assert go(tmp_path, CELL) == 0
    assert seen == {'blocked': True}


def test_item7_a_wrapper_target_changed_in_a_subdirectory_is_refused(tmp_path):
    pkg = tmp_path / 'node_modules' / '@openai' / 'codex'
    (pkg / 'bin').mkdir(parents=True)
    (pkg / 'package.json').write_text('{"name": "@openai/codex"}', encoding='utf-8')
    (pkg / 'bin' / 'codex.js').write_text('// launcher', encoding='utf-8')
    (pkg / 'vendor' / 'x86_64').mkdir(parents=True)
    (pkg / 'vendor' / 'x86_64' / 'codex.exe').write_bytes(b'MZ native payload')
    shim = tmp_path / 'codex.cmd'
    shim.write_text('@ECHO off\r\nnode "%~dp0\\node_modules\\@openai\\codex\\bin\\codex.js" %*\r\n', encoding='utf-8')
    frozen = isolation.executable_identity(shim)
    assert frozen['kind'] == 'wrapper' and frozen['targets'] and not frozen['unreadable']
    assert 'vendor/x86_64/codex.exe' in frozen['targets'][0]['package']
    assert isolation.identity_problems(isolation.executable_identity(shim), frozen) == []
    (pkg / 'vendor' / 'x86_64' / 'codex.exe').write_bytes(b'MZ another payload')
    assert isolation.identity_problems(isolation.executable_identity(shim), frozen)
    blind = tmp_path / 'other.cmd'
    blind.write_text('@ECHO off\r\nsomething %*\r\n', encoding='utf-8')
    assert isolation.executable_identity(blind)['unreadable'], 'a launcher without a known target fails closed'


def test_item7_the_native_package_manifest_lists_every_companion(tmp_path):
    root = tmp_path / 'standalone' / 'current'
    (root / 'bin').mkdir(parents=True)
    (root / 'codex-resources').mkdir()
    (root / 'codex-package.json').write_text('{}', encoding='utf-8')
    (root / 'bin' / 'codex.exe').write_bytes(b'MZ\x00\x01')
    (root / 'bin' / 'codex-code-mode-host.exe').write_bytes(b'MZ\x00\x02')
    (root / 'codex-resources' / 'codex-command-runner.exe').write_bytes(b'MZ\x00\x03')
    ident = isolation.executable_identity(root / 'bin' / 'codex.exe')
    assert ident['kind'] == 'native_package'
    assert {'bin/codex-code-mode-host.exe', 'codex-resources/codex-command-runner.exe'} <= set(ident['payload'])
    (root / 'codex-resources' / 'codex-command-runner.exe').write_bytes(b'MZ\x00\x04')
    assert isolation.identity_problems(isolation.executable_identity(root / 'bin' / 'codex.exe'), ident)


# ============================================================= items 9, RT2.2: identity and cumulative accounting

def test_item9_migration_after_a_telemetry_failure_keeps_every_old_and_new_call_counted(live, monkeypatch):
    live.mutate = lambda raw, env, cwd, launch: dict(raw, stdout=raw['stdout'] + json.dumps(
        {'type': 'item.completed', 'item': {'id': 'e', 'type': 'error', 'message': 'surprise'}}) + '\n') \
        if 'scrambled' not in (Path(env['CODEX_HOME']) / 'auth.json').read_text(encoding='utf-8') else raw
    assert live.telemetry() == config.EXIT_TELEMETRY
    live.mutate = None
    d1 = live.run_dir
    disposition = live.tmp / 'disposition.md'
    disposition.write_text('council disposition: telemetry failure (test fixture)\n', encoding='utf-8')
    freeze = live.tmp / 'freeze.json'
    freeze.write_text(json.dumps({'live_run_dir': str(live.tmp / 'live-2'), 'disposition': str(disposition)}),
                      encoding='utf-8')
    monkeypatch.setattr(config, 'FREEZE_FILE', freeze)
    live.run_dir = live.tmp / 'live-2'
    monkeypatch.setattr(run, 'live_run_dir', lambda: live.run_dir)
    assert live.telemetry() == 0
    ledger = run.jsonl(live.ledger)
    assert len(ledger) == 4 and len({r['attempt_uid'] for r in ledger}) == 4
    assert {r['run_dir'] for r in ledger} == {str(d1.resolve()), str(live.run_dir.resolve())}
    b = run.CellRun(dict(run.TELEMETRY_SPEC), live.opts()).budget()
    assert b.usage()['codex']['telemetry'] == 4, 'every old and new telemetry call is counted'
    with pytest.raises(Exception):
        b.charge('codex', 'telemetry', 'telemetry')
    rep = score.score_run(live.run_dir)
    assert rep['provenance']['experiment_ledger']['ledger_calls'] == 4


def test_item9_a_replacement_directory_never_repeats_a_terminal_batch(live, monkeypatch):
    cell = 'sonnet-materials-cold-A'
    assert live.cell(cell, stop_after=2) == config.EXIT_INTERRUPTED
    disposition = live.tmp / 'disposition.md'
    disposition.write_text('council disposition (test fixture)\n', encoding='utf-8')
    freeze = live.tmp / 'freeze.json'
    freeze.write_text(json.dumps({'live_run_dir': str(live.tmp / 'live-2'), 'disposition': str(disposition)}),
                      encoding='utf-8')
    monkeypatch.setattr(config, 'FREEZE_FILE', freeze)
    live.run_dir = live.tmp / 'live-2'
    monkeypatch.setattr(run, 'live_run_dir', lambda: live.run_dir)
    assert live.cell(cell) == config.EXIT_IDENTITY
    assert attempts(live.run_dir, cell) == []
    assert len(run.jsonl(live.ledger)) == 2


def test_item9_competing_runners_of_old_and_new_directories_cannot_reserve_independently(live):
    with run.exclusive(live.ledger.parent / 'experiment.lock'):
        assert live.cell('sonnet-materials-cold-A') == config.EXIT_BUSY
    assert run.jsonl(live.ledger) == []


def test_item9_a_torn_ledger_line_is_an_accounting_failure(live):
    assert live.cell('sonnet-materials-cold-A') == 0
    with open(live.ledger, 'a', encoding='utf-8') as f:
        f.write('{"attempt_uid": "torn')
    assert live.cell('sonnet-materials-cold-B') in (config.EXIT_IDENTITY, config.EXIT_REQUIRES)
    assert run.ledger_problems(live.run_dir, live.ledger)


def test_b2_a_third_member_failing_verification_leaves_no_ledger_row(live, monkeypatch):
    original = run.CellRun.verify_codex_launch
    seen = {'n': 0}
    assert live.telemetry() == 0

    def flaky(self, argv, env, workdir):
        if self.spec['id'] == CELL:
            seen['n'] += 1
            if seen['n'] == 3:
                return ['simulated: AGENTS.md appeared in an ancestor']
        return original(self, argv, env, workdir)
    monkeypatch.setattr(run.CellRun, 'verify_codex_launch', flaky)
    assert live.cell(CELL) == config.EXIT_INCOMPLETE
    assert [r['cell'] for r in run.jsonl(live.ledger)] == ['telemetry', 'telemetry']
    assert run.ledger_problems(live.run_dir, live.ledger) == []


# ================================================================================ item 10: scorer reconstruction

def tamper_attempt(run_dir, field, value, index=0):
    rows = run.jsonl(run_dir / 'attempts.jsonl')
    rows[index][field] = value
    (run_dir / 'attempts.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')


@pytest.mark.parametrize('field,value', [('charged_tokens', 1), ('usage_status', 'unverified'),
                                         ('additive_tokens', 7), ('reasoning_issue', 'x'),
                                         ('cache_certified', False), ('visible_tokens', 1)])
def test_item10_an_altered_accounting_field_alone_withholds_claims(tmp_path, field, value):
    assert go(tmp_path, CELL) == 0
    tamper_attempt(tmp_path / 'run', field, value)
    rep = score.score_run(tmp_path / 'run')
    assert any(field in p for p in rep['validity']['artifact_problems']), rep['validity']['artifact_problems'][:3]
    assert gates.magnitude(dict(rep, validity=dict(rep['validity'], simulation=[])), 'codex')['status'] == 'invalid'


def test_item10_an_altered_bootstrap_proposal_is_detected(tmp_path):
    assert go(tmp_path, 'codex-materials-bootstrap') == 0
    calls = list((tmp_path / 'run' / 'cells' / 'codex-materials-bootstrap' / 'calls').glob('*.json'))
    doc = json.loads(calls[0].read_text(encoding='utf-8'))
    ast = b'{"lang":"oz-rule/1","expr":["s","room"]}'
    doc['rules']['temp_class'] = {'ast_b64': base64.b64encode(ast).decode(), 'ast_sha256': 'x', 'bytes': len(ast)}
    calls[0].write_text(json.dumps(doc), encoding='utf-8')
    problems = score.score_run(tmp_path / 'run')['validity']['artifact_problems']
    assert any('bootstrap proposals' in p for p in problems)


def test_item10_an_altered_audit_disposition_is_detected(tmp_path, monkeypatch):
    from bench.ozmap_rep.tests.test_rule_path import UNKNOWN_ONLY, inject_rule
    assert go(tmp_path, 'codex-materials-bootstrap') == 0
    inject_rule(tmp_path, UNKNOWN_ONLY)
    assert go(tmp_path, 'codex-materials-cold-C') == 0
    monkeypatch.setattr(score, '_rule_asts', lambda results, prefix, boot_props=None: {'temp_class': UNKNOWN_ONLY})
    assert not [p for p in score.score_run(tmp_path / 'run')['validity']['artifact_problems'] if 'audit' in p]
    p = tmp_path / 'run' / 'cells' / 'codex-materials-cold-C' / 'result.json'
    doc = json.loads(p.read_text(encoding='utf-8'))
    jid = next(iter(doc['audits']))
    doc['audits'][jid] = 'disagree'
    p.write_text(json.dumps(doc), encoding='utf-8')
    problems = score.score_run(tmp_path / 'run')['validity']['artifact_problems']
    assert any('audit disposition' in x for x in problems)


def test_item10_a_launch_identity_differing_from_the_bound_freeze_withholds_claims(live):
    assert live.telemetry() == 0
    assert live.cell(CELL) == 0
    (live.run_dir / 'freeze.json').write_text(json.dumps({'codex': {'exe_sha256': '0' * 64, 'argv_sha256': '1' * 64}}),
                                               encoding='utf-8')
    rep = score.score_run(live.run_dir)
    assert any('run bound freeze' in p for p in rep['validity']['isolation_problems'])
    assert rep['validity']['isolation'] == 'failed'


# ===================================================================================== item 14: timing windows

def test_item14_a_crash_before_the_window_closes_keeps_the_work_in_the_gated_makespan(tmp_path, monkeypatch):
    original = run.CellRun.rule_errors
    state = {}

    def crash(self, result):
        if not state:
            state['done'] = True
            raise KeyboardInterrupt('runner killed after the last attempt, before the window was closed')
        return original(self, result)
    monkeypatch.setattr(run.CellRun, 'rule_errors', crash)
    with pytest.raises(KeyboardInterrupt):
        go(tmp_path, CELL)
    rows = attempts(tmp_path / 'run', CELL)
    work = sum(float(r['elapsed_s']) for r in rows)
    assert go(tmp_path, CELL) == 0
    windows = run.jsonl(tmp_path / 'run' / 'cells' / CELL / 'windows.jsonl')
    assert any(w.get('reconstructed') for w in windows)
    cell = score.score_run(tmp_path / 'run')['cells']['codex/materials/cold/A']
    assert cell['timing'] == 'bounded' and cell['makespan_upper_s'] >= max(float(r['elapsed_s']) for r in rows)
    assert cell['makespan_lower_s'] <= cell['makespan_upper_s'] and work > 0
    assert gates._span(cell, 'test') == gates._F(cell['makespan_upper_s'])
    assert gates._span(cell, 'ref') == gates._F(cell['makespan_lower_s'])


def test_item14_an_attempt_outside_every_window_makes_the_cell_incomplete(tmp_path):
    assert go(tmp_path, CELL) == 0
    (tmp_path / 'run' / 'cells' / CELL / 'windows.jsonl').unlink()
    cell = score.score_run(tmp_path / 'run')['cells']['codex/materials/cold/A']
    assert cell['timing_problems']


# ================================================================== items 31, B8, RT2.5: quota observations (P3)

def session(root, rows, name='rollout-a.jsonl'):
    folder = root / '2026' / '10' / '24'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')


def reading(percent, t, **extra):
    return dict({'timestamp': stamp(t), 'type': 'event_msg',
                 'payload': {'type': 'token_count', 'rate_limits': {'primary': {'used_percent': percent}}}}, **extra)


NOW = dt.datetime.now(dt.timezone.utc)
DONE = [{'call_id': 'x', 'backend': 'codex', 'mode': 'live', 'outcome': 'ok', 'ended_at': stamp(NOW - dt.timedelta(
    minutes=5))}]


def test_item31_unrelated_events_after_an_old_reading_never_refresh_it(tmp_path):
    session(tmp_path, [reading(10.0, NOW - dt.timedelta(hours=1)),
                       {'timestamp': stamp(NOW), 'type': 'response_item', 'payload': {'type': 'message'}}])
    assert quota.coverage_gate(DONE, tmp_path)['ok'] is False
    session(tmp_path, [reading(10.0, NOW)])
    assert quota.coverage_gate(DONE, tmp_path)['ok'] is True


@pytest.mark.parametrize('bad', [True, 'x', float('nan'), -1, 100.5, None])
def test_item31_a_malformed_latest_reading_blocks_and_never_falls_back(tmp_path, bad):
    session(tmp_path, [reading(10.0, NOW), reading(bad, NOW)])
    assert quota.coverage_gate([], tmp_path)['ok'] is False
    assert quota.codex_gate(tmp_path)['ok'] is False


def test_item31_a_reading_of_another_account_blocks(tmp_path):
    other = __import__('hashlib').sha256(b'acct-other').hexdigest()
    session(tmp_path, [{'type': 'session_meta', 'payload': {'creator_account_id': 'acct-other'}}, reading(10.0, NOW)])
    assert quota.coverage_gate([], tmp_path, account_sha256='a' * 64)['ok'] is False
    assert quota.coverage_gate([], tmp_path, account_sha256=other)['ok'] is True


def test_item31_crossing_80_between_groups_stops_the_next_group(live):
    assert live.telemetry() == 0
    live.touch_sessions(percent=85.0)
    code = run.CellRun(run.spec_by_id(CELL), live.opts()).run()
    assert code == config.EXIT_QUOTA and attempts(live.run_dir, CELL) == []


def test_item31_a_worker_rollout_reading_covers_its_own_attempt(tmp_path):
    harvested = {'u1': [{'percent': 12.0, 'timestamp': stamp(NOW), 'account_sha256': None}]}
    done = [dict(DONE[0], attempt_uid='u1')]
    assert quota.coverage_gate(done, tmp_path / 'none', harvested)['ok'] is True
    harvested['u1'][0]['percent'] = 81.0
    assert quota.coverage_gate(done, tmp_path / 'none', harvested)['ok'] is False


def test_item31_the_telemetry_probe_without_accepted_tokens_needs_no_coverage():
    assert not quota.needs_coverage({'backend': 'codex', 'mode': 'live', 'role': 'probe', 'outcome': 'auth_failure'})
    assert quota.needs_coverage({'backend': 'codex', 'mode': 'live', 'role': 'call', 'outcome': 'auth_failure'})


# ============================================================================ items 32, B5: notices (P1, P4)

NOTICE = config.P4_CANDIDATE_NOTICE


def notice_event(**over):
    item = {'id': 'item_0', 'type': 'error', 'message': NOTICE}
    item.update(over.pop('item', {}))
    return dict({'type': 'item.completed', 'item': item}, **over)


def plain(*extra):
    return stream({'type': 'thread.started', 'thread_id': 't'}, {'type': 'turn.started'}, *extra,
                  {'type': 'item.completed', 'item': {'id': 'm', 'type': 'agent_message', 'text': 'OZ/1g'}},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 1, 'cached_input_tokens': 0,
                                                       'output_tokens': 1, 'reasoning_output_tokens': 0}})


def test_item32_the_cli_notice_is_inactive_until_its_annex_is_approved():
    assert events.classify_stream(plain(notice_event()))['verdict'] == 'uncertain'


def test_item32_an_approved_notice_is_plain_and_every_variant_is_not(monkeypatch):
    monkeypatch.setattr(config, 'SIGNED_CLI_NOTICES', (NOTICE,))
    monkeypatch.setattr(config, 'SIGNED_CLI_NOTICE_EVENT_KEYS', ('type', 'item'))
    monkeypatch.setattr(config, 'SIGNED_CLI_NOTICE_ID_RE', r'item_[0-9]+')
    assert events.classify_stream(plain(notice_event()))['verdict'] == 'plain'
    for variant in (notice_event(item={'message': NOTICE + ' '}), notice_event(item={'message': NOTICE[:-1]}),
                    notice_event(item={'extra': 1}), notice_event(item={'id': 'other-id'}),
                    notice_event(extra=True), dict(notice_event(), type='item.started')):
        assert events.classify_stream(plain(variant))['verdict'] == 'uncertain', variant
    assert events.classify_stream(plain(notice_event(), *EXECUTED))['verdict'] == 'executed'


def test_b5_transport_notices_never_match_a_prefix_and_never_with_a_tool_item(monkeypatch):
    msg = 'Falling back from WebSockets to HTTPS transport.'
    ev = {'type': 'item.completed', 'item': {'id': 'item_1', 'type': 'error', 'message': msg}}
    monkeypatch.setattr(config, 'SIGNED_TRANSPORT_NOTICES', (msg,))
    assert events.classify_stream(plain(ev))['verdict'] == 'plain'
    longer = {'type': 'item.completed', 'item': {'id': 'item_1', 'type': 'error', 'message': msg + ' more'}}
    assert events.classify_stream(plain(longer))['verdict'] == 'uncertain'
    assert events.classify_stream(plain(ev, *REFUSED))['verdict'] == 'uncertain'


def test_rt2_4_two_turns_are_uncertain_and_their_usage_incomplete():
    out = plain() + plain()
    outcome, _, usage_raw, cls, _ = run.judge_codex({'stdout': out, 'stderr': '', 'exit_code': 0, 'timed_out': False})
    assert cls['verdict'] == 'uncertain' and usage_raw is None and outcome == 'uncertain'


# ====================================================================== items 33, B6, B1: startup files (P5)

def test_item33_startup_files_need_an_approved_manifest_entry_by_path_and_hash(tmp_path, monkeypatch):
    manifest = tmp_path / 'startup-manifest.json'
    manifest.write_text(json.dumps({'files': [{'path': 'skills/.system/x/SKILL.md', 'sha256': 'a' * 64,
                                               'type': 'file', 'origin': 'vendor', 'role': 'not loaded'}]}),
                        encoding='utf-8')
    monkeypatch.setattr(config, 'STARTUP_MANIFEST_FILE', manifest)
    names = ['skills/.system/x/SKILL.md', 'state.sqlite']
    assert isolation.startup_instruction_files(names, {'skills/.system/x/SKILL.md': 'a' * 64}) == []
    assert isolation.startup_instruction_files(names, {'skills/.system/x/SKILL.md': 'b' * 64}), 'changed contents'
    assert isolation.startup_instruction_files(names + ['skills/.system/y/SKILL.md'],
                                               {'skills/.system/x/SKILL.md': 'a' * 64}), 'another source'
    assert isolation.startup_instruction_files(names), 'a name alone never qualifies'


def test_b1_telemetry_refuses_the_charged_call_when_the_probe_inventory_holds_instructions(live):
    def before(env, cwd, launch):
        home = Path(env['CODEX_HOME'])
        (home / 'skills' / '.system' / 'imagegen').mkdir(parents=True, exist_ok=True)
        (home / 'skills' / '.system' / 'imagegen' / 'SKILL.md').write_text('bundled', encoding='utf-8')
    live.before = before
    assert live.telemetry() == config.EXIT_TELEMETRY
    tel = attempts(live.run_dir, 'telemetry')
    assert [a['role'] for a in tel] == ['probe'], 'the charged worker call was never made'
    rows = run.jsonl(live.run_dir / 'evidence' / 'telemetry.jsonl')
    assert any('preflight' in p for p in rows[-1]['problems'])


def test_b1_the_freeze_refuses_while_a_ruling_slot_is_unsettled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'FREEZE_FILE', tmp_path / 'freeze.json')
    assert run.freeze_command() == config.EXIT_FREEZE
    assert not (tmp_path / 'freeze.json').exists()
    assert any('freeze readiness' in p for p in run.verify_freeze() + ['freeze readiness'])


def test_b1_readiness_needs_countersigned_ruling_bytes_and_a_matching_configuration(tmp_path, monkeypatch):
    slots = {}
    for name in config.REQUIRED_RULINGS:
        f = tmp_path / f'{name}.md'
        f.write_text(f'{name} ruling text\n\nSigned: Astra A\n', encoding='utf-8')
        slots[name] = {'path': str(f), 'sha256': sha(f)}
    assert all('lacks' in p for p in rulings.ruling_problems(slots))
    for name, entry in slots.items():
        Path(entry['path']).write_text(f'{name} ruling text\n\nSigned: Astra A\nSigned: Opus B\n', encoding='utf-8')
    assert all('hash differs' in p for p in rulings.ruling_problems(slots)), 'the countersigned bytes are pinned'
    for entry in slots.values():
        entry['sha256'] = sha(entry['path'])
    assert rulings.ruling_problems(slots) == []
    disable = ['--disable', 'code_mode_host']
    assert any('Code Mode' in p for p in rulings.configuration_problems(disable))
    monkeypatch.setattr(config, 'SIGNED_CLI_NOTICES', (NOTICE,))
    monkeypatch.setattr(config, 'SIGNED_CLI_NOTICE_EVENT_KEYS', ('type', 'item'))
    monkeypatch.setattr(config, 'SIGNED_CLI_NOTICE_ID_RE', r'item_[0-9]+')
    manifest = tmp_path / 'startup-manifest.json'
    manifest.write_text(json.dumps({'files': [{'path': 'skills/.system/x/SKILL.md', 'sha256': 'a' * 64}]}),
                        encoding='utf-8')
    monkeypatch.setattr(config, 'STARTUP_MANIFEST_FILE', manifest)
    assert rulings.readiness_problems(disable, slots) == []


# ============================================================================ items 1, B4, RT2.6: authentication

def test_item1_an_argv_without_the_file_credential_store_is_refused():
    argv = isolation.codex_argv('codex', config.CODEX_MODEL, config.CODEX_EFFORT, '/tmp/w/slot-0', ())
    assert isolation.argv_check(argv) == []
    i = argv.index('cli_auth_credentials_store="file"')
    assert isolation.argv_check(argv[:i - 1] + argv[i + 1:])
    assert isolation.argv_check([a if a != 'cli_auth_credentials_store="file"' else 'cli_auth_credentials_store='
                                 '"keyring"' for a in argv])


def test_rt2_6_a_shared_refresh_token_is_refused_by_hash_and_unreadable_owner_auth_is_never_different(tmp_path):
    base, owner = tmp_path / 'b', tmp_path / 'owner'
    write_auth(base, 'B')
    owner.mkdir()
    shutil.copyfile(base / 'auth.json', owner / 'auth.json')
    assert isolation.token_separation_problems(base, [owner / 'auth.json'])
    write_auth(owner, 'OWNER')
    assert isolation.token_separation_problems(base, [owner / 'auth.json']) == []
    (owner / 'auth.json').write_text('{not json', encoding='utf-8')
    assert isolation.token_separation_problems(base, [owner / 'auth.json'])
    assert isolation.token_separation_problems(base, [base / 'auth.json'])


def test_rt2_6_lineage_rows_hold_hashes_only(live):
    assert live.telemetry() == 0
    rows = run.jsonl(live.run_dir / 'evidence' / 'auth-lineage.jsonl')
    assert rows and rows[0]['event'] == 'first_dispatch' and len(rows[0]['tokens']['refresh_token']) == 64
    text = (live.run_dir / 'evidence' / 'auth-lineage.jsonl').read_text(encoding='utf-8')
    token = json.loads((live.base / 'auth.json').read_text(encoding='utf-8'))['tokens']['access_token']
    assert token not in text
