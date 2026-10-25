"""Red team round 2 against the replication harness (bench/ozmap_rep) after the council round 1 fixes (c345c4b).

Every test here is expected to FAIL on c345c4b and to pass once the finding it names is fixed. Findings and fixes:
docs/design/ozmap-replication-2026-10-24/council-build-redteam-r2.md.

Fakes and temporary directories only: no real `codex` or `claude` is resolved or spawned (live mode runs the harness'
own fakes through the real lifecycle code and refuses any other launch), no real baseline, run directory, experiment
ledger, owner home or Codex session directory is read or written, and the sealed reviewer ASTs are never touched.
"""
import datetime as dt
import io
import json
import os
from pathlib import Path
import shutil
import sys
import time

import pytest

from bench.ozmap_rep import config, isolation, run, score, usage, workload


# ------------------------------------------------------------------------------------------------------- helpers

def stream(*evts):
    return '\n'.join(json.dumps(e) for e in evts) + '\n'


def fake_opts(tmp_path, **kw):
    workload.fake_answer_table()
    base = tmp_path / 'baseline'
    if not (base / 'auth.json').exists():
        run.synthetic_baseline(base)
    return run.Options(tmp_path / 'run', mode='fake', baseline=base, out=io.StringIO(), **kw)


def attempts(run_dir, cell_id=None):
    return [r for r in run.jsonl(Path(run_dir) / 'attempts.jsonl') if cell_id is None or r.get('cell') == cell_id]


class Live:
    """Live mode on the harness' own fakes (the same construction as tests/test_council_r1.py::Live): the real gates,
    lifecycle, isolation, reconciliation, budget and scoring, with the executables, the canonical run directory, the
    freeze check, the tokenizer and the session readings replaced. Every directory and the ledger are temporary."""

    def __init__(self, tmp_path, monkeypatch):
        self.tmp, self.mp = tmp_path, monkeypatch
        self.run_dir = tmp_path / 'live'
        self.base = tmp_path / 'baseline'
        run.synthetic_baseline(self.base)
        self.ledger = tmp_path / 'ledger.jsonl'
        self.fakebin = tmp_path / 'fakebin'
        self.sessions = tmp_path / 'sessions'
        self.current = self.run_dir
        self.touch_sessions()
        monkeypatch.setattr(run, 'live_run_dir', lambda: self.current)
        monkeypatch.setattr(run, 'verify_freeze', lambda: [])
        # A4.12, RT3.3: live mode reads the owner sessions only; the test's sessions directory stands in for them
        monkeypatch.setattr(config, 'CODEX_SESSIONS_DEFAULT', self.sessions)
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

        def spawn(run_dir, launch, stdin_text, env, cwd, external, timeout=config.CALL_TIMEOUT_S):
            exe = Path(launch[0]).resolve()
            assert (fakebin / 'fake').resolve() in exe.parents, f'refusing a non fake executable {exe}'
            directive = {'cell': 'live', 'n': 0, 'call_id': f'{Path(cwd).name}-{time.monotonic_ns()}', 'fail': False,
                         'refresh': False, 'bootstrap_ops': None}
            (fakebin / 'fake' / 'directives' / f'{Path(cwd).name}.json').write_text(json.dumps(directive),
                                                                                  encoding='utf-8')
            return original_spawn(run_dir, [sys.executable, *launch], stdin_text, env, cwd, external, timeout)

        def run_local(argv, env, cwd, on_start=None, timeout=120):
            assert (fakebin / 'fake').resolve() in Path(argv[0]).resolve().parents
            return original_local([sys.executable, *argv], env, cwd, on_start, timeout)

        monkeypatch.setattr(run, 'spawn', spawn)
        monkeypatch.setattr(run, 'run_local', run_local)

    def touch_sessions(self, percent=10.0):
        folder = self.sessions / '2026' / '10' / '24'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / 'rollout-test.jsonl'
        # P3 repair: an attributable owner reading (account, bucket and event timestamp of the baseline account)
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        account = ((json.loads((self.base / 'auth.json').read_text(encoding='utf-8')).get('tokens') or {})
                   .get('account_id'))
        rows = [{'timestamp': stamp, 'type': 'session_meta', 'payload': {'creator_account_id': account,
                                                                          'cli_version': '0.160.0'}},
                {'timestamp': stamp, 'type': 'event_msg', 'payload': {'type': 'token_count', 'rate_limits': {
                    'limit_id': 'codex', 'primary': {'used_percent': percent, 'window_minutes': 10080}}}}]
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        now = time.time() + 1
        os.utime(path, (now, now))

    def opts(self, **kw):
        workload.fake_answer_table()
        return run.Options(self.current, mode='live', baseline=self.base, sessions_dir=self.sessions,
                           claude_percent=50.0, live_ledger=self.ledger, out=io.StringIO(), **kw)

    def telemetry(self):
        self.touch_sessions()
        return run.TelemetryRun(self.opts()).run()

    def cell(self, cell_id, **kw):
        self.touch_sessions()
        return run.CellRun(run.spec_by_id(cell_id), self.opts(**kw)).run()

    def supersede(self, new_run_dir):
        """What `run freeze --new-run-dir D2 --disposition <file>` leaves behind: freeze.json names D2 and a recorded
        council disposition (build notes, reading 7). Only temporary files are written."""
        disposition = self.tmp / 'disposition.md'
        disposition.write_text('council disposition: superseded run directory (red team fixture)\n', encoding='utf-8')
        freeze = self.tmp / 'freeze.json'
        freeze.write_text(json.dumps({'live_run_dir': str(new_run_dir), 'disposition': str(disposition)}),
                          encoding='utf-8')
        self.mp.setattr(config, 'FREEZE_FILE', freeze)
        self.current = new_run_dir


@pytest.fixture
def live(tmp_path, monkeypatch):
    return Live(tmp_path, monkeypatch)


# ============================================== RT2.1: a capture with execution evidence hidden behind `interrupted`

def test_rt2_1_execution_captured_before_the_runner_died_is_still_leakage(tmp_path, monkeypatch):
    """after_group writes D/captures/<call id>.stdout before it appends the attempt line. A runner killed in between
    (a runner subagent timeout, a crash in _append) leaves the capture. A4.3: actual execution invalidates
    replication efficiency; leakage is global.

    A4.14.4 replacement (the original asserted a resumed run that recovered the call and completed the cell): under
    A4.14.1 the crashed cell is stopped, never resumed or rerun; the call is recorded `unsettled` (its state was never
    settled), its batch is never resent, the capture that shows execution stays leakage and the cell is invalid, not
    merely interrupted."""
    cell = 'codex-materials-cold-A'
    target = f'{cell}.r1.b03.t0'
    o = fake_opts(tmp_path)
    cmd = 'type C:\\Users\\can02\\Projects\\akor\\bench\\ozmap_rep\\ops\\oracle.py'
    executed = [{'type': 'item.started', 'item': {'id': 'c1', 'type': 'command_execution', 'command': cmd,
                                                  'aggregated_output': '', 'exit_code': None,
                                                  'status': 'in_progress'}},
                {'type': 'item.completed', 'item': {'id': 'c1', 'type': 'command_execution', 'command': cmd,
                                                    'aggregated_output': 'def gold(op, text):', 'exit_code': 0,
                                                    'status': 'completed'}}]
    original_spawn, original_append = run.spawn, run._append

    def spawn(run_dir, launch, stdin_text, env, cwd, external, timeout=config.CALL_TIMEOUT_S):
        raw = original_spawn(run_dir, launch, stdin_text, env, cwd, external, timeout)
        directive = json.loads((Path(run_dir) / 'fake' / 'directives' / f'{Path(cwd).name}.json')
                               .read_text(encoding='utf-8'))
        if directive['call_id'] == target:
            lines = raw['stdout'].splitlines()
            raw = dict(raw, stdout='\n'.join(lines[:2] + [json.dumps(e) for e in executed] + lines[2:]) + '\n')
        return raw

    killed = {}

    def append(run_dir, name, row):
        if name == 'attempts.jsonl' and row.get('call_id') == target and not killed:
            killed['at'] = row['call_id']
            raise KeyboardInterrupt('runner killed after the capture, before the attempt line')
        return original_append(run_dir, name, row)

    slots = []
    original_slots_init = run.Slots.__init__

    def slots_init(self, run_dir):
        original_slots_init(self, run_dir)
        slots.append(self)

    monkeypatch.setattr(run, 'spawn', spawn)
    monkeypatch.setattr(run, '_append', append)
    monkeypatch.setattr(run.Slots, '__init__', slots_init)
    with pytest.raises(KeyboardInterrupt):
        run.CellRun(run.spec_by_id(cell), o).run()
    for s in slots:  # the dead process' slot handles (a real death closes them)
        for k in list(s.held):
            s.release(k)
    capture = (o.run_dir / 'captures' / f'{target}.stdout').read_text(encoding='utf-8')
    assert '"command_execution"' in capture and '"exit_code": 0' in capture

    assert run.CellRun(run.spec_by_id(cell), fake_opts(tmp_path)).run() == config.EXIT_CELL_INTERRUPTED
    outcomes = {r['call_id']: r['outcome'] for r in attempts(o.run_dir, cell)}
    assert outcomes[target] == 'unsettled' and f'{cell}.r1.b03.t1' not in outcomes, 'the batch was resent'
    assert (o.run_dir / 'cells' / cell / 'INTERRUPTED.json').exists()
    rep = score.score_run(o.run_dir)
    assert cell in rep['validity']['invalid_cells'], 'a stopped cell with execution evidence is invalid'
    assert run.CellRun(run.spec_by_id(cell), fake_opts(tmp_path)).run() == config.EXIT_CELL_INTERRUPTED
    flagged = [p for k in ('leakage', 'artifact_problems') for p in rep['validity'][k] if target in p]
    assert flagged, (f'{target} executed `{cmd}` (its capture holds the command_execution item with exit_code 0) but '
                     f"the report flags nothing: leakage {rep['validity']['leakage']}, artifact problems "
                     f"{rep['validity']['artifact_problems'][:3]}, cell state {rep['cells']['codex/materials/cold/A']['state']}")


# ===================================== RT2.2: a superseded run directory gives back the nominal calls it already used

def test_rt2_2_a_superseded_run_directory_never_restores_used_nominal_calls(live):
    """Build notes, reading 7: after a new freeze (--new-run-dir, --disposition) the live calls of the superseded
    directory "stay in the experiment ledger and keep counting against every allocation and cap". CellRun.budget()
    merges D/attempts.jsonl with the ledger and deduplicates by call id alone, but call ids are deterministic
    (<cell>.<batch>.t<try>) and restart in every run directory. Once the new directory has recorded its own copy of
    a call id, the superseded call with the same id stops counting: the allocation is granted again. The scorer of
    the new directory then shows a complete cell within its allocation."""
    cell = 'sonnet-materials-cold-A'
    nominal = run.spec_by_id(cell)['nominal_calls']
    d1 = live.run_dir
    assert live.cell(cell, stop_after=2) == config.EXIT_INTERRUPTED  # the runner stops after two live calls
    assert len(attempts(d1, cell)) == 2
    d2 = live.tmp / 'live-2'
    live.supersede(d2)  # council disposition: the run continues in a new live directory
    first = live.cell(cell)  # 2 nominal calls left: b00 and b01 run, b02 and b03 are refused by the budget
    second = live.cell(cell)  # the resume: the ledger copies of b00.t0 and b01.t0 now dedupe with D2's own rows
    ledger = run.jsonl(live.ledger)
    used = sum(1 for r in ledger if r.get('allocation') == 'cold_A' and r.get('kind') == 'nominal')
    rep = score.score_run(d2)
    assert used <= nominal, (
        f'{used} nominal live calls charged to sonnet/materials cold_A (nominal allocation {nominal}) across the '
        f'superseded and the new run directory ({len(attempts(d1, cell))} + {len(attempts(d2, cell))}); exit codes '
        f"{first}, {second}; D2 report: state {rep['cells']['sonnet/materials/cold/A']['state']}, calls "
        f"{rep['cells']['sonnet/materials/cold/A']['physical_calls']}, accounting failures "
        f"{rep['validity']['accounting_failures']}")


# ============================== RT2.3: one transient launch check failure makes every later live dispatch refuse

def test_rt2_3_an_abandoned_launch_group_never_bricks_the_live_run(live, monkeypatch):
    """prepare_call appends a live charge to the experiment ledger as soon as a call is prepared. When a later call of
    the same launch group fails its launch verification (an AGENTS.md appearing in an ancestor, a baseline reseed
    mid group), abandon() removes the earlier calls' markers and prompts but leaves their ledger rows, and no attempt
    line is ever written for them. From then on ledger_problems() finds "live calls in the experiment ledger are
    missing from this run directory" and every live cell of every backend refuses with exit 15, for good: the
    remaining cells are lost and the run can only continue under a new freeze (where RT2.2 applies)."""
    assert live.telemetry() == config.EXIT_OK
    original = run.CellRun.verify_codex_launch
    seen = {'n': 0}

    def flaky(self, argv, env, workdir):
        if self.spec['id'] == 'codex-materials-cold-A':
            seen['n'] += 1
            if seen['n'] == 2:
                return ['simulated transient launch problem: AGENTS.md reachable from an ancestor']
        return original(self, argv, env, workdir)

    monkeypatch.setattr(run.CellRun, 'verify_codex_launch', flaky)
    assert live.cell('codex-materials-cold-A') == config.EXIT_INCOMPLETE
    monkeypatch.setattr(run.CellRun, 'verify_codex_launch', original)  # the ancestor file is gone again
    codes = {cid: live.cell(cid) for cid in ('codex-materials-cold-A', 'sonnet-materials-cold-A')}
    assert config.EXIT_IDENTITY not in codes.values(), (
        f'after one abandoned launch group every live cell refuses: {codes}; ledger rows without attempts: '
        f"{run.ledger_problems(live.run_dir, live.ledger)}")


# ====================================================== RT2.4: a second turn in one exec stream drops tokens

def test_rt2_4_a_stream_with_two_turns_never_drops_the_first_turns_tokens():
    """_turn_usage (and the frozen adapter's parse_events) keep only the LAST turn.completed usage, and nothing
    counts turns: classify_stream skips every turn event. A stream with two turns is judged `ok`, usage `complete`,
    charged with the second turn's tokens only. The scorer re-derives usage with the same function, so the omission
    is invisible. Any stream with more than one turn must be uncertain or its usage incomplete."""
    u1 = {'input_tokens': 30000, 'cached_input_tokens': 0, 'output_tokens': 900, 'reasoning_output_tokens': 300}
    u2 = {'input_tokens': 120, 'cached_input_tokens': 0, 'output_tokens': 30, 'reasoning_output_tokens': 10}
    out = stream({'type': 'thread.started', 'thread_id': 't'}, {'type': 'turn.started'},
                 {'type': 'item.completed', 'item': {'id': 'm1', 'type': 'agent_message', 'text': 'OZ/1g'}},
                 {'type': 'turn.completed', 'usage': u1},
                 {'type': 'turn.started'},
                 {'type': 'item.completed', 'item': {'id': 'm2', 'type': 'agent_message', 'text': 'OZ/1g'}},
                 {'type': 'turn.completed', 'usage': u2})
    outcome, reply, usage_raw, cls, _ = run.judge_codex({'stdout': out, 'stderr': '', 'exit_code': 0,
                                                         'timed_out': False})
    dec = usage.decode_codex_checked(usage_raw, cache_certified=True)
    real = u1['input_tokens'] + u1['output_tokens'] + u2['input_tokens'] + u2['output_tokens']
    hidden = outcome == 'ok' and cls['verdict'] == 'plain' and dec['status'] == 'complete' and \
        (dec['charged_tokens'] or 0) < real
    assert not hidden, (f'two turns judged {outcome!r}, verdict {cls["verdict"]!r}, usage {dec["status"]!r}, charged '
                        f'{dec["charged_tokens"]} of {real} tokens')


# ============================================ RT2.5: the RT1.6 interim freshness gate reads an mtime, not a reading

def test_rt2_5_the_codex_quota_freshness_gate_needs_a_new_reading_not_a_new_mtime(tmp_path):
    """The interim fix for RT1.6 lets a live Codex cell launch only when the owner reading is newer than the last live
    Codex call. codex_reading_time() returns the session FILE's mtime, so any later write to that file (a resumed
    owner session appending a user message, the Codex app touching it, `touch`) passes the gate while the newest
    rate_limits reading in it is from before the replication's calls. The reading's own event timestamp is in the
    file and is ignored."""
    now = dt.datetime.now(dt.timezone.utc)
    stamp = lambda t: t.strftime('%Y-%m-%dT%H:%M:%S.%fZ')  # noqa: E731
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    (run_dir / 'attempts.jsonl').write_text(json.dumps({'call_id': 'x', 'backend': 'codex', 'mode': 'live',
                                                        'ended_at': stamp(now - dt.timedelta(minutes=10))}) + '\n',
                                            encoding='utf-8')
    sessions = tmp_path / 'sessions' / '2026' / '10' / '24'
    sessions.mkdir(parents=True)
    path = sessions / 'rollout-owner.jsonl'
    old = {'timestamp': stamp(now - dt.timedelta(hours=2)), 'type': 'event_msg',
           'payload': {'type': 'token_count', 'rate_limits': {'primary': {'used_percent': 79.0}}}}
    later = {'timestamp': stamp(now), 'type': 'response_item',
             'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'hi'}]}}
    path.write_text(json.dumps(old) + '\n' + json.dumps(later) + '\n', encoding='utf-8')
    cr = run.CellRun(run.spec_by_id('codex-materials-cold-A'),
                     run.Options(run_dir, mode='live', baseline=tmp_path / 'b', sessions_dir=tmp_path / 'sessions',
                                 claude_percent=50.0, live_ledger=tmp_path / 'l.jsonl', out=io.StringIO()))
    gate = cr.codex_quota_gate()
    assert not gate['ok'], ('the only rate limit reading (79%) is two hours older than the last live Codex call, '
                            f'yet the freshness gate passes on the file mtime: {gate}')


# ======================================== RT2.6: a baseline that shares the owner's lineage is used without a check

def test_rt2_6_a_baseline_sharing_the_owner_refresh_token_never_reaches_a_worker(live, monkeypatch, tmp_path):
    """A4.2: the baseline must share no refresh token with the owner's home ("Never seed it by copying the owner's
    auth.json"). Nothing checks it. A baseline seeded by a copy of ~/.codex/auth.json passes the wave gate, the
    inventory, telemetry and every launch check, and its refresh token is then used by up to four concurrent workers:
    the first worker refresh rotates the token the owner's Codex app also holds, and the owner's login fails with
    "refresh token was already used". The check needs only hashes of the two refresh tokens, never their text."""
    owner = tmp_path / 'owner'
    (owner / '.codex').mkdir(parents=True)
    shutil.copyfile(live.base / 'auth.json', owner / '.codex' / 'auth.json')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: owner))
    codes = {'telemetry': live.telemetry(), 'cell': live.cell('codex-materials-cold-A')}
    used = [a['call_id'] for a in attempts(live.run_dir) if a.get('role') != 'probe' and a.get('outcome') != 'interrupted']
    assert not used, (f'a baseline holding the owner refresh token (copied ~/.codex/auth.json) was used by worker calls '
                      f'{used[:5]}; exit codes {codes}')
