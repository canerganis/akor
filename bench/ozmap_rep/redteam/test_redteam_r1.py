"""Red team round 1 against the replication harness (bench/ozmap_rep), before its freeze.

Every test here is expected to FAIL on the harness as built (commit 4839d99) and to pass once the finding it names is
fixed. Findings and fixes: docs/design/ozmap-replication-2026-10-24/council-build-redteam-r1.md.

Fakes and temporary directories only: no real `codex` or `claude` is ever resolved or spawned (the live-mode test
replaces the executables with the harness' own fakes and refuses any other launch), no real baseline, run directory or
Codex session directory is read or written, and the sealed reviewer ASTs are never touched.
"""
import collections
import io
import json
from pathlib import Path
import sys
import threading
import time

import pytest

from bench.ozmap_rep import config, events, run, score, workload

LIVE_RUN_DIR = config.RUNS_DEFAULT / 'replication'


# ------------------------------------------------------------------------------------------------------- helpers

def fake_opts(tmp_path, mode='fake', run_dir=None, **kw):
    workload.fake_answer_table()  # load the workloads once in this thread (in-process runners share the modules)
    base = tmp_path / 'baseline'
    if not (base / 'auth.json').exists():
        run.synthetic_baseline(base)
    return run.Options(run_dir or tmp_path / 'run', mode=mode, baseline=base, out=io.StringIO(), **kw)


def attempts(run_dir, cell_id):
    return [r for r in run.jsonl(Path(run_dir) / 'attempts.jsonl') if r.get('cell') == cell_id]


def stream(*evts):
    return '\n'.join(json.dumps(e) for e in evts) + '\n'


# ============================================================================================ RT1.1: fake meets live

def test_rt1_1_the_plan_command_never_runs_fake_mode_in_the_live_run_dir_with_the_real_baseline():
    """`plan --list-cells` hands every runner `python -m bench.ozmap_rep.run cell <id>`. Parsed exactly as given, that
    command must not be a fake run inside the live run directory, nor a fake run that copies the owner seeded
    baseline auth.json into worker homes."""
    for spec in run.cell_specs():
        args = run.build_parser().parse_args(spec['command'].split()[3:])
        o = run._opts(args)
        assert not (o.mode == 'fake' and o.run_dir == LIVE_RUN_DIR), (
            f"{spec['id']}: the plan command is a FAKE run in the live run directory {o.run_dir}")
        assert not (o.mode == 'fake' and o.baseline == config.BASELINE_DEFAULT), (
            f"{spec['id']}: a fake run reads the real baseline {o.baseline} and copies it into worker homes")


def test_rt1_1_the_scorer_never_accepts_fake_calls_as_evidence(tmp_path):
    """A cell answered by the fake model (gold labels from fake/answers.json) must not score as complete evidence."""
    o = fake_opts(tmp_path)
    assert run.CellRun(run.spec_by_id('sonnet-materials-cold-A'), o).run() == 0
    assert {r['mode'] for r in attempts(o.run_dir, 'sonnet-materials-cold-A')} == {'fake'}
    rep = score.score_run(o.run_dir)
    cell = rep['cells']['sonnet/materials/cold/A']
    problems = [str(p) for k in ('isolation_problems', 'leakage', 'accounting_failures')
                for p in rep['validity'][k]]
    assert cell['evidence'] != 'complete' or any('fake' in p.lower() for p in problems), (
        f"fake calls scored as evidence: state {cell['state']}, evidence {cell['evidence']}, usage {cell['usage']}, "
        f"correct {cell['correct']}/{cell['jobs']}, isolation {rep['validity']['isolation']}, problems {problems}")


# ======================================================================================= RT1.2: two runners, one cell

def test_rt1_2_two_runners_of_one_sonnet_cell_never_send_a_batch_twice(tmp_path, monkeypatch):
    """A resume runner started while the first runner of the same cell is still alive (a runner subagent that timed
    out while its python child kept running) must not send the cell's batches again. Sonnet cells take no cell lock
    at all, so both runners compute the same pending batches and each charges a fresh in-memory budget."""
    spec = run.spec_by_id('sonnet-materials-cold-A')
    fake_opts(tmp_path)
    inflight = tmp_path / 'run' / 'cells' / spec['id'] / 'inflight'
    second_entered = threading.Event()
    original_batches, original_spawn = run.CellRun.run_batches, run.spawn

    def gated(self, *a, **k):
        # Order only, no change of harness logic: runner 1 starts sending once runner 2 has passed its own setup;
        # runner 2 reads the run state once runner 1's four calls are in flight (markers written, no attempt yet).
        end = time.monotonic() + 10
        if threading.current_thread().name == 'runner-1':
            second_entered.wait(10)
        else:
            second_entered.set()
            while time.monotonic() < end and len(list(inflight.glob('*.json'))) < spec['nominal_calls']:
                time.sleep(0.01)
        return original_batches(self, *a, **k)

    def slow_spawn(*a, **k):  # a fake call that takes one second, like any real model call takes longer
        time.sleep(1.0)
        return original_spawn(*a, **k)

    monkeypatch.setattr(run.CellRun, 'run_batches', gated)
    monkeypatch.setattr(run, 'spawn', slow_spawn)
    codes, crashes = {}, {}

    def runner(n):
        try:
            codes[n] = run.CellRun(spec, fake_opts(tmp_path)).run()
        except Exception as exc:  # recorded, so a crashed runner never passes this test silently
            crashes[n] = repr(exc)

    threads = [threading.Thread(target=runner, args=(n,), name=f'runner-{n}', daemon=True) for n in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(300)
    rows = attempts(tmp_path / 'run', spec['id'])
    per_batch = collections.Counter(r['batch'] for r in rows)
    alloc = spec['nominal_calls'] + config.RESERVE_PER_ALLOCATION
    assert all(n == 1 for n in per_batch.values()), (
        f'batches sent more than once: {dict(per_batch)}; {len(rows)} physical calls for an allocation of '
        f"{spec['nominal_calls']} (+{config.RESERVE_PER_ALLOCATION} reserve), exit codes {codes}, crashes {crashes}")
    assert len(rows) <= alloc
    assert len({r['call_id'] for r in rows}) == len(rows), 'a call id was recorded twice'
    assert not crashes, f'a runner crashed on files of the other runner (same call ids): {crashes}'


def test_rt1_2_a_second_codex_runner_never_declares_a_live_call_interrupted(tmp_path, monkeypatch):
    """CellRun.run() recovers in-flight markers, builds the budget and records features BEFORE it takes the
    codex-cells lock. A second runner of the same Codex cell, started while the first has calls in flight, turns
    every live call into a phantom `interrupted` attempt with the same call id (double counted against the
    allocation, usage incomplete) and deletes the first runner's markers."""
    spec = run.spec_by_id('codex-materials-cold-A')
    fake_opts(tmp_path)
    path = tmp_path / 'run' / 'attempts.jsonl'
    original = run.spawn
    second = {}

    def spawn(*a, **k):
        if 'thread' not in second:
            def runner():
                second['code'] = run.CellRun(spec, fake_opts(tmp_path)).run()
            second['thread'] = threading.Thread(target=runner, daemon=True)
            second['thread'].start()
            end = time.monotonic() + 8
            while time.monotonic() < end and not any(r.get('outcome') == 'interrupted' for r in run.jsonl(path)):
                time.sleep(0.05)
        return original(*a, **k)

    monkeypatch.setattr(run, 'spawn', spawn)
    first = run.CellRun(spec, fake_opts(tmp_path)).run()
    second['thread'].join(300)
    rows = attempts(tmp_path / 'run', spec['id'])
    phantom = [r['call_id'] for r in rows if r['outcome'] == 'interrupted']
    assert not phantom, (f'live calls of the first runner recorded as interrupted by the second: {phantom}; '
                         f'exit codes {first}, {second.get("code")}')
    assert len({r['call_id'] for r in rows}) == len(rows), 'a call id was recorded twice'


# ================================================================================ RT1.3: execution evidence is sticky

def test_rt1_3_execution_evidence_is_never_erased_by_a_later_event_of_the_same_item():
    """The classifier keeps only the last event per tool item id. An item that completed with output (an external
    read) and is later reported declined becomes a `refused` call: no external read, no efficiency invalidation."""
    cmd = 'type C:\\Users\\can02\\Projects\\akor\\bench\\ozmap_rep\\ops\\oracle.py'
    out = stream(
        {'type': 'thread.started', 'thread_id': 't'}, {'type': 'turn.started'},
        {'type': 'item.started', 'item': {'id': 'item_1', 'type': 'command_execution', 'command': cmd,
                                          'aggregated_output': '', 'exit_code': None, 'status': 'in_progress'}},
        {'type': 'item.completed', 'item': {'id': 'item_1', 'type': 'command_execution', 'command': cmd,
                                            'aggregated_output': 'def gold(op, text):', 'exit_code': 0,
                                            'status': 'completed'}},
        {'type': 'item.updated', 'item': {'id': 'item_1', 'type': 'command_execution', 'command': cmd,
                                          'aggregated_output': '', 'exit_code': None, 'status': 'declined'}},
        {'type': 'item.completed', 'item': {'id': 'item_2', 'type': 'agent_message', 'text': 'OZ/1g'}},
        {'type': 'turn.completed', 'usage': {'input_tokens': 10, 'cached_input_tokens': 0, 'output_tokens': 5,
                                             'reasoning_output_tokens': 0}})
    cls = events.classify_stream(out)
    assert cls['verdict'] == 'executed' and cls['external_read'] and cls['efficiency_invalid'], cls


# ===================================================================== RT1.4: the pinned CLI's auth failure messages

# Verbatim from the pinned codex.exe (codex-cli 0.160.0) string table, read with grep -a, never executed.
REFRESH_FAILURES = (
    'Your access token could not be refreshed because your refresh token has expired. Please log out and sign in '
    'again.',
    'Your access token could not be refreshed because your refresh token was already used. Please log out and sign '
    'in again.',
    'Your access token could not be refreshed because your refresh token was revoked. Please log out and sign in '
    'again.',
    'Your access token could not be refreshed. Please log out and sign in again.',
    'Your access token could not be refreshed because you have since logged out or signed in to another account. '
    'Please sign in again.',
)


@pytest.mark.parametrize('where', ['stream', 'stderr'])
@pytest.mark.parametrize('message', REFRESH_FAILURES)
def test_rt1_4_a_refresh_failure_of_the_pinned_cli_is_an_authentication_failure(message, where):
    """A4.2: an authentication failure stops Codex evaluation. AUTH_FAILURE_RE matches none of the pinned CLI's own
    refresh failure messages, so the call is an infrastructure failure and is retried from the reserve."""
    if where == 'stream':
        stdout = stream({'type': 'thread.started', 'thread_id': 't'}, {'type': 'turn.started'},
                        {'type': 'error', 'message': message},
                        {'type': 'turn.failed', 'error': {'message': message}})
        stderr = ''
    else:
        stdout, stderr = '', f'Error: {message}\n'
    outcome = run.judge_codex({'stdout': stdout, 'stderr': stderr, 'exit_code': 1, 'timed_out': False})[0]
    assert outcome == 'auth_failure', f'{outcome!r} for {message!r} ({where})'


# =========================================================================== RT1.5: a fresh run dir is a fresh budget

def test_rt1_5_a_second_live_run_directory_never_grants_a_fresh_allocation(tmp_path, monkeypatch):
    """The live evaluation caps (A4.5) are counted from D/attempts.jsonl of whatever --run-dir the runner passes.
    The same live cell run into a second directory gets a full new allocation, and the scorer of either directory
    shows a clean, complete cell: a selective rerun that erases the first attempt (A4.1, A4.3).

    Live mode here is real harness code with the gates that need the real CLI replaced: freeze verification passes,
    the executables are the harness' own fakes (any other launch raises) and the fake directive is written by the
    spawn shim. Quota: the Claude reading is passed explicitly; a Sonnet cell reads no Codex sessions."""
    spec = run.spec_by_id('sonnet-materials-cold-A')
    monkeypatch.setattr(run, 'verify_freeze', lambda: [])

    class FakeExecutables(run.Executables):
        def __init__(self, opts, backend):
            mode, opts.mode = opts.mode, 'fake'
            try:
                super().__init__(opts, backend)
            finally:
                opts.mode = mode

    monkeypatch.setattr(run, 'Executables', FakeExecutables)
    original = run.spawn

    def spawn(run_dir, launch, stdin_text, env, cwd, external, timeout=config.CALL_TIMEOUT_S):
        fake_root = (Path(run_dir) / 'fake').resolve()
        exe = Path(launch[0]).resolve()
        if fake_root not in exe.parents:
            raise AssertionError(f'refusing to launch a non fake executable: {exe}')
        directive = {'cell': 'x', 'n': 0, 'call_id': f'{Path(cwd).name}-{time.monotonic_ns()}', 'fail': False,
                     'refresh': False, 'bootstrap_ops': None}
        (fake_root / 'directives' / f'{Path(cwd).name}.json').write_text(json.dumps(directive), encoding='utf-8')
        return original(run_dir, [sys.executable, *launch], stdin_text, env, cwd, external, timeout)

    monkeypatch.setattr(run, 'spawn', spawn)
    first, second = tmp_path / 'live-1', tmp_path / 'live-2'
    for d in (first, second):
        run.CellRun(spec, fake_opts(tmp_path, mode='live', run_dir=d, claude_percent=50.0)).run()
    rows = attempts(first, spec['id']) + attempts(second, spec['id'])
    assert {r['mode'] for r in rows} <= {'live'}
    alloc = spec['nominal_calls'] + config.RESERVE_PER_ALLOCATION
    assert len(rows) <= alloc, (
        f"{len(rows)} live physical calls for {spec['id']} across two run directories "
        f"({len(attempts(first, spec['id']))} + {len(attempts(second, spec['id']))}); allocation "
        f"{spec['nominal_calls']} + {config.RESERVE_PER_ALLOCATION} reserve")
