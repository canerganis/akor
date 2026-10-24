"""oz map clean replication runner (Amendment 4). Standard library only.

    python -m bench.ozmap_rep.run plan --list-cells               the 16 cells, one JSON line each
    python -m bench.ozmap_rep.run cell <id> --mode fake|live ...  run or resume one cell (--mode is required)
    python -m bench.ozmap_rep.run dry --run-dir D                 every cell in fake mode, zero rules, then the scorer
    python -m bench.ozmap_rep.run telemetry --mode live ...       the A4.2 telemetry certificate (live only)
    python -m bench.ozmap_rep.run freeze | verify-freeze          hash the frozen inputs before evaluation calls (A4.1)
    python -m bench.ozmap_rep.run features --mode live            record `codex features list` for a worker home (A4.2)

Cells and allocations follow A4.5; isolation A4.2; tool events A4.3; capacity A4.4; bootstrap validity A4.6; usage
A4.7; operations A4.8; Sonnet A4.9; stops A4.12. build-notes.md maps every clause to the code.

Run state. Every physical call is one line in D/attempts.jsonl (append only, failures included) with a globally
unique attempt uid, its complete prompt is D/prompts/<call id>.txt, its sanitized output D/captures/<call id>.* with a
per channel redaction record, its parsed outcome D/cells/<cell>/calls/<call id>.json. A launch group is staged (no
charge written), then reserved as a whole: D/cells/<cell>/inflight/<call id>.json markers in phase `reserved`, then
(live) one experiment ledger row per member. Before Popen a marker turns `spawning`, right after it `spawned` with
the child pid; the child's stdout and stderr go to raw stream files in D/homes/raw-<slot>/ (the credential boundary).
after_group writes the call record, the captures and the attempt row in that order, then marks the marker `recorded`;
a marker is removed only after the call's authentication was reconciled (A4.2). On resume every marker is recovered
before anything else (council round 2, item 3): a recorded child still running stops the resume; a `reserved` marker
becomes a charged `not_launched` attempt; a pid-less `spawning` marker is ambiguous (kept, Codex stops, its batch is
never resent); an orphan is judged from its committed capture or else its raw stream, and only without any stream is it
`interrupted` with an uncertain verdict. A batch whose attempt ended with any terminal outcome is never sent again. A
completed cell has D/cells/<cell>/DONE.json, a settled but incomplete one SETTLED.json; neither is ever rerun.

One cell process at a time per run directory (council round 1, item 2): every cell, telemetry and features run holds
an exclusive per cell lock and the experiment lock, both taken without waiting before any state is read; live runs
also hold the experiment lock beside the authoritative ledger (council round 2, item 9). Live cells and telemetry are
launched detached (run_in_background), never in a foreground shell whose limit is below config.CALL_TIMEOUT_S.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

from . import config

if str(config.REPO) not in sys.path:
    sys.path.insert(0, str(config.REPO))
if str(config.REPO / 'examples') not in sys.path:
    sys.path.insert(0, str(config.REPO / 'examples'))

from . import bootstrap as bootstrap_mod  # noqa: E402
from . import budget as budget_mod  # noqa: E402
from . import events, isolation, prompts, quota, redact, rules, rulings, usage, workload  # noqa: E402
from . import fake_cli, tokenizer  # noqa: E402

COMMAND = 'python -m bench.ozmap_rep.run cell {id}'
LIVE_COMMAND = COMMAND + ' --mode live --claude-weekly-percent <reading>'
EXPERIMENT = 'ozmap-replication-2026-10-24'
# Authentication failures of the pinned CLI (codex-cli 0.160.0): the refresh failure texts of its string table (red
# team RT1.4), the 401 transport errors of the no-auth probe (B1) and the login prompts. Matched only on error
# channels (turn.failed, top level error events, error items, stderr), never on the model's reply text.
AUTH_FAILURE_RE = re.compile(r'status 401|401 Unauthorized|HTTP error: 401|Missing bearer|could not be refreshed|'
                             r'sign in again|Not logged in|invalid_grant|token_expired|refresh_token_reused|'
                             r'Please log ?in|re-?authenticate', re.I)
TERMINAL_OK = ('ok',)
RETRYABLE = ('infrastructure_failure', 'interrupted', 'not_launched')
TELEMETRY_SPEC = {'id': 'telemetry', 'command': None, 'backend': 'codex', 'workload': 'telemetry',
                  'wave': 'telemetry', 'arm': 'telemetry', 'allocation': 'telemetry', 'nominal_calls': 2,
                  'requires': []}


# ================================================================================================ cells and plan

def cell_specs():
    specs = []
    for backend, wl in (('codex', 'materials'), ('codex', 'boolq'), ('sonnet', 'materials')):
        prefix = f'{backend}-{wl}'
        alloc = config.ALLOCATIONS[f'{backend}/{wl}']

        def add(name, wave, arm, allocation, requires):
            cid = f'{prefix}-{name}'
            specs.append({'id': cid, 'command': COMMAND.format(id=cid), 'live_command': LIVE_COMMAND.format(id=cid),
                          'backend': backend, 'workload': wl, 'wave': wave, 'arm': arm, 'allocation': allocation,
                          'nominal_calls': alloc[allocation], 'requires': requires})
        add('bootstrap', 'cold', 'bootstrap', 'bootstrap', [])
        add('cold-A', 'cold', 'A', 'cold_A', [])
        add('cold-B', 'cold', 'B', 'cold_B', [f'{prefix}-bootstrap'])
        add('cold-C', 'cold', 'C', 'cold_C', [f'{prefix}-bootstrap'])
        if wl == 'materials':
            add('warm-A', 'warm', 'A', 'warm_A', [f'{prefix}-cold-A'])
            add('warm-C', 'warm', 'C', 'warm_C', [f'{prefix}-bootstrap', f'{prefix}-cold-C'])
    return specs


def spec_by_id(cell_id):
    for s in cell_specs():
        if s['id'] == cell_id:
            return s
    return None


# ================================================================================================ small helpers

def _now():
    return isolation.now_iso()


def _write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.{threading.get_ident()}.tmp')
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _append(run_dir, name, row):
    path = Path(run_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with isolation.file_lock(Path(run_dir) / 'locks' / (name.replace('/', '_') + '.lock'), timeout=60):
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + '\n')


def _append_file(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with isolation.file_lock(path.with_name(path.name + '.lock'), timeout=60):
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + '\n')


def _same(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except (OSError, TypeError, ValueError):
        return False


def _sha_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _parse_time(value):
    return isolation._parse_time(value)


def chunks(items, n=config.MAX_BATCH):
    return [items[i:i + n] for i in range(0, len(items), n)]


def schedule(fallback_by_producer, audits_by_producer, pooled):
    """The frozen dispatch rule (A4.4): synchronized submission, full eligible batches of at most 64, producer local
    for B, pooled for C. Inputs are job lists in wave order; returns a list of batches."""
    if pooled:
        every = [j for p in config.PRODUCERS for j in fallback_by_producer.get(p, []) + audits_by_producer.get(p, [])]
        return chunks(every)
    out = []
    for p in config.PRODUCERS:
        out += chunks(fallback_by_producer.get(p, []) + audits_by_producer.get(p, []))
    return out


def worst_case_calls(spec):
    """Batches the scheduler dispatches with zero admitted rules and the worst permitted audit placement (the whole
    audit allowance on one producer for local fallback, added to the pool for pooled fallback)."""
    if spec['arm'] == 'bootstrap':
        return 1
    n = config.PER_PRODUCER
    b = config.BOOTSTRAP_PER_PRODUCER if spec['wave'] == 'cold' and spec['arm'] in ('B', 'C') else 0
    a = config.AUDITS if spec['workload'] == 'materials' and spec['arm'] in ('B', 'C') else 0
    if spec['arm'] == 'A':
        return len(schedule({p: ['x'] * n for p in config.PRODUCERS}, {}, pooled=True))
    worst = 0
    for target in config.PRODUCERS:
        fallback = {p: ['f'] * (n - b) for p in config.PRODUCERS}
        audits = {target: ['a'] * a}
        worst = max(worst, len(schedule(fallback, audits, pooled=spec['arm'] == 'C')))
    return worst


# ================================================================================================ run identity

class Busy(Exception):
    pass


@contextlib.contextmanager
def exclusive(path):
    """A non blocking exclusive OS lock: raises Busy at once when another runner (thread or process) holds it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, 'a+b')
    try:
        if not isolation._try_lock(handle):
            raise Busy(f'{path.name} is held by another runner')
        try:
            yield
        finally:
            isolation._unlock(handle)
    finally:
        handle.close()


def live_run_dir():
    """The one run directory live cells may use: freeze.json's live_run_dir, or the default."""
    frozen = _read_json(config.FREEZE_FILE, {}) or {}
    value = frozen.get('live_run_dir')
    return Path(value) if value else config.LIVE_RUN_DIR_DEFAULT


def synthetic_baseline_ok(baseline):
    """True when the baseline's access token is an unsigned JWT (alg none), as every synthetic baseline is."""
    doc = isolation._read_auth(Path(baseline) / isolation.AUTH) or {}
    token = (doc.get('tokens') or {}).get('access_token') if isinstance(doc.get('tokens'), dict) else None
    if not isinstance(token, str) or token.count('.') != 2:
        return False
    head = token.split('.')[0]
    try:
        header = json.loads(base64.urlsafe_b64decode(head + '=' * (-len(head) % 4)).decode('utf-8'))
    except (ValueError, UnicodeError, TypeError):
        return False
    return isinstance(header, dict) and header.get('alg') == 'none'


def mode_problem(opts):
    """Why this mode, run directory and baseline may not run together (RT1.1), or None."""
    if opts.mode not in ('fake', 'live'):
        return ('--mode fake or --mode live is required; the plan command runs live: '
                'add --mode live --claude-weekly-percent <reading>')
    if opts.mode == 'fake':
        if _same(opts.run_dir, live_run_dir()) or _same(opts.run_dir, config.LIVE_RUN_DIR_DEFAULT):
            return 'fake mode refuses the live run directory'
        if _same(opts.baseline, config.BASELINE_DEFAULT):
            return 'fake mode refuses the owner seeded baseline; it uses a synthetic baseline'
        if (Path(opts.baseline) / isolation.AUTH).exists() and not synthetic_baseline_ok(opts.baseline):
            return 'fake mode accepts only a synthetic baseline (an unsigned access token)'
    return None


def identity_problem(run_dir, opts):
    """A run directory is bound to one mode for its whole life (item 9): no mixed fake and live attempts."""
    run_dir = Path(run_dir)
    doc = _read_json(run_dir / 'experiment.json')
    if doc and doc.get('mode') != opts.mode:
        return f"the run directory is bound to mode {doc.get('mode')!r}; {opts.mode!r} is refused"
    modes = {a.get('mode') for a in jsonl(run_dir / 'attempts.jsonl') if a.get('mode')}
    if modes - {opts.mode}:
        return f'the run directory holds attempts of mode {sorted(modes - {opts.mode})}; {opts.mode!r} is refused'
    if opts.mode == 'live' and (run_dir / 'fake').exists():
        return 'the run directory holds fake executables; live mode is refused'
    return None


def freeze_sha256():
    p = config.FREEZE_FILE
    return isolation.sha256_file(p) if p.exists() else None


def experiment_id(ledger):
    """The immutable experiment UUID, written once beside the experiment ledger (council round 2, item 9)."""
    path = Path(ledger).parent / 'experiment-id.json'
    doc = _read_json(path)
    if isinstance(doc, dict) and doc.get('experiment_id'):
        return doc['experiment_id']
    import uuid
    value = str(uuid.uuid4())
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, 'x', encoding='utf-8') as f:
            f.write(json.dumps({'experiment_id': value, 'experiment': EXPERIMENT, 'created_at': _now()}))
    except FileExistsError:
        return (_read_json(path, {}) or {}).get('experiment_id') or value
    return value


def bind_identity(run_dir, opts, baseline_sha=None):
    """Write D/experiment.json (mode, freeze identity, baseline lineage, immutable run and experiment UUIDs) before
    the first attempt; live runs also archive the authorized freeze as D/freeze.json. Never rewritten."""
    import uuid
    run_dir = Path(run_dir)
    path = run_dir / 'experiment.json'
    if path.exists():
        return _read_json(path)
    doc = {'schema': 'ozmap-rep.experiment/2', 'experiment': EXPERIMENT, 'mode': opts.mode,
           'run_dir': str(run_dir.resolve()), 'created_at': _now(), 'run_id': str(uuid.uuid4()),
           'experiment_id': experiment_id(opts.live_ledger) if opts.mode == 'live' else None,
           'freeze_sha256': freeze_sha256() if opts.mode == 'live' else None,
           'baseline_auth_sha256': baseline_sha, 'live_ledger': str(opts.live_ledger) if opts.mode == 'live' else None,
           'simulation': opts.mode != 'live'}
    if opts.mode == 'live':
        try:
            doc['baseline_tokens'] = isolation.token_hashes(Path(opts.baseline) / isolation.AUTH)
        except isolation.IsolationError:
            doc['baseline_tokens'] = None
    if opts.mode == 'live' and config.FREEZE_FILE.exists():
        shutil.copyfile(config.FREEZE_FILE, run_dir / 'freeze.json')
    _write_json(path, doc)
    return doc


def run_id(run_dir):
    return ((_read_json(Path(run_dir) / 'experiment.json', {}) or {}).get('run_id'))


def ledger_rows(ledger):
    """(rows, problems) of the experiment ledger, parsed strictly: a torn or malformed line is an accounting problem,
    an identical repeated event is idempotent, two different events with one attempt uid conflict (item 9)."""
    path = Path(ledger)
    if not path.exists():
        return [], []
    rows, problems, by_uid = [], [], {}
    for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            problems.append(f'experiment ledger line {n} is torn or malformed')
            continue
        if not isinstance(row, dict):
            problems.append(f'experiment ledger line {n} is not an object')
            continue
        uid = row.get('attempt_uid')
        if uid:
            if uid in by_uid:
                if _canon_row(by_uid[uid]) != _canon_row(row):
                    problems.append(f'experiment ledger attempt {uid} is recorded twice with different content')
                continue
            by_uid[uid] = row
        rows.append(row)
    return rows, problems


def _canon_row(row):
    return json.dumps({k: v for k, v in row.items() if k != 'at'}, sort_keys=True)


def predecessor_dirs(run_dir, ledger):
    """Every other run directory the experiment ledger holds live calls of (superseded directories)."""
    rows, _ = ledger_rows(ledger)
    here = str(Path(run_dir).resolve())
    return sorted({r.get('run_dir') for r in rows if r.get('run_dir') and r.get('run_dir') != here})


def ledger_problems(run_dir, ledger):
    """The experiment ledger outside every run directory (RT1.5, council round 2 item 9): every live charge of this
    run directory must be in its attempts or in flight here (by attempt uid), the ledger must parse, and live charges
    of other run directories need a recorded disposition bound to the freeze."""
    rows, problems = ledger_rows(ledger)
    if not rows:
        return problems
    here = str(Path(run_dir).resolve())
    attempts = jsonl(Path(run_dir) / 'attempts.jsonl')
    known = {a.get('attempt_uid') or a.get('call_id') for a in attempts}
    for p in Path(run_dir).glob('cells/*/inflight/*.json'):
        m = _read_json(p, {}) or {}
        known.add(m.get('attempt_uid') or m.get('call_id'))
    other = sorted({r.get('run_dir') for r in rows if r.get('run_dir') != here})
    disposition = (_read_json(config.FREEZE_FILE, {}) or {}).get('disposition')
    if other and not (disposition and Path(disposition).is_file()):
        problems.append(f'the experiment ledger holds live calls of other run directories: {other[:3]}')
    missing = sorted(r.get('call_id') for r in rows if r.get('run_dir') == here
                     and (r.get('attempt_uid') or r.get('call_id')) not in known)
    if missing:
        problems.append(f'live calls in the experiment ledger are missing from this run directory: {missing[:5]}')
    return problems


def superseded_terminal_batches(run_dir, ledger, cell_id):
    """(terminal batch keys, problems) of a cell in every superseded run directory: a replacement directory never
    repeats a batch that ended terminally elsewhere, and missing predecessor evidence is a problem (item 9)."""
    terminal, problems = set(), []
    for d in predecessor_dirs(run_dir, ledger):
        path = Path(d) / 'attempts.jsonl'
        if not path.exists():
            problems.append(f'predecessor run directory {d} has no readable attempts (evidence missing)')
            continue
        for a in jsonl(path):
            if a.get('cell') == cell_id and a.get('outcome') not in RETRYABLE:
                terminal.add(a.get('batch'))
    return sorted(t for t in terminal if t), problems


# ================================================================================================ processes

_TLS = threading.local()
ACTIVE_INVOCATIONS = set()


def pid_alive(pid, created=None):
    """Whether a process with this pid is running (and, on Windows, was created at `created`)."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            if code.value != 259:  # STILL_ACTIVE
                return False
            if created is not None and process_created(pid) not in (None, created):
                return False  # the pid was reused by another process
            return True
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def process_created(pid):
    """The creation time of a process (Windows FILETIME as an int), or None."""
    if os.name != 'nt':
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        handle = k32.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            c, e, k, u = (wintypes.FILETIME() for _ in range(4))
            if not k32.GetProcessTimes(handle, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
                return None
            return (c.dwHighDateTime << 32) | c.dwLowDateTime
        finally:
            k32.CloseHandle(handle)
    except (OSError, AttributeError, ValueError):
        return None


def _kill_tree(proc):
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True, timeout=60)
        else:
            proc.kill()
    except (OSError, subprocess.SubprocessError):
        pass


class SpawnFailure(Exception):
    """A child that was started but whose call cannot be settled normally (council round 2, item 3): its pid could
    not be journaled, or waiting for it raised. `terminated` says whether termination of its process tree was
    established; `raw` holds what its raw stream files contain when it was."""

    def __init__(self, reason, terminated, pid=None, raw=None):
        Exception.__init__(self, reason)
        self.reason, self.terminated, self.pid, self.raw = reason, terminated, pid, raw


def _wait_gone(proc, pid, seconds=60):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            if proc is not None and proc.poll() is None:
                time.sleep(0.1)
                continue
        except OSError:
            pass
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


def _read_raw(paths):
    out = []
    for p in paths:
        try:
            out.append(Path(p).read_bytes().decode('utf-8', 'replace'))
        except OSError:
            out.append('')
    return out


def spawn(run_dir, launch, stdin_text, env, cwd, external, timeout=config.CALL_TIMEOUT_S):
    """Run one child; every spawn is logged in D/spawns.jsonl with whether it is an external model CLI.

    Council round 2 (items 3, B3): when the launching thread names a raw stream directory (_TLS.raw, inside D/homes,
    the credential boundary), the child's stdout and stderr go to files there, not to pipes, so a runner that dies
    leaves the complete stream for recovery. Right after the process starts, the thread's on_start hook journals its
    pid in the in-flight marker; when that fails, or waiting for the child raises, its process tree is killed and
    SpawnFailure says whether termination was established. Exceptions before the process exists propagate."""
    _append(run_dir, 'spawns.jsonl', {'exe': Path(launch[1] if not external else launch[0]).name,
                                      'external': bool(external), 'at': _now()})
    raw = getattr(_TLS, 'raw', None)
    t0 = time.monotonic()
    start = _now()
    files = []
    if raw is not None:
        Path(raw[0]).parent.mkdir(parents=True, exist_ok=True)
        files = [open(raw[0], 'wb'), open(raw[1], 'wb')]
    try:
        proc = subprocess.Popen(launch, stdin=subprocess.PIPE,
                                stdout=files[0] if files else subprocess.PIPE,
                                stderr=files[1] if files else subprocess.PIPE, cwd=str(cwd), env=env)
    except BaseException:
        for f in files:
            f.close()
        raise
    hook = getattr(_TLS, 'on_start', None)
    if hook is not None:
        try:
            hook(proc.pid)
        except BaseException as exc:  # noqa: BLE001  (the pid could not be journaled: kill and establish the end)
            _kill_tree(proc)
            gone = _wait_gone(proc, proc.pid)
            for f in files:
                f.close()
            raise SpawnFailure(f'the child pid could not be journaled: {type(exc).__name__}', gone, proc.pid,
                               _read_raw(raw) if raw and gone else None) from None
    timed_out = False
    try:
        try:
            out, err = proc.communicate(stdin_text.encode('utf-8'), timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            out, err = proc.communicate()
    except SpawnFailure:
        raise
    except BaseException as exc:  # noqa: BLE001  (waiting raised with a child that may still run)
        _kill_tree(proc)
        gone = _wait_gone(proc, proc.pid)
        for f in files:
            f.close()
        raise SpawnFailure(f'waiting for the child raised {type(exc).__name__}', gone, proc.pid,
                           _read_raw(raw) if raw and gone else None) from None
    for f in files:
        f.close()
    if raw is not None:
        stdout, stderr = _read_raw(raw)
    else:
        stdout, stderr = out.decode('utf-8', 'replace'), err.decode('utf-8', 'replace')
    return {'stdout': stdout, 'stderr': stderr, 'exit_code': None if timed_out else proc.returncode,
            'timed_out': timed_out, 'started_at': start, 'ended_at': _now(),
            'elapsed_s': round(time.monotonic() - t0, 3), 'pid': proc.pid}


def run_local(argv, env, cwd, on_start=None, timeout=120):
    """A local CLI command (no model request) whose pid is recorded like a call's."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=str(cwd), env=env)
    if on_start is not None:
        with contextlib.suppress(Exception):
            on_start(proc.pid)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        out, err = proc.communicate()
    return proc.returncode, out.decode('utf-8', 'replace'), err.decode('utf-8', 'replace')


# ================================================================================================ options, slots

class Options:
    def __init__(self, run_dir, mode='fake', baseline=None, sessions_dir=None, claude_percent=None, stop_after=None,
                 fake_fail=0, fake_refresh=None, base_env=None, out=None, live_ledger=None):
        self.run_dir = Path(run_dir)
        self.mode = mode
        if baseline:
            self.baseline = Path(baseline)
        elif mode == 'fake':
            self.baseline = self.run_dir / 'auth' / 'baseline'
        else:
            self.baseline = config.BASELINE_DEFAULT
        self.default_baseline = not baseline
        self.sessions_dir = Path(sessions_dir) if sessions_dir else config.CODEX_SESSIONS_DEFAULT
        self.claude_percent = claude_percent
        self.stop_after = stop_after
        self.fake_fail = fake_fail or 0
        self.fake_refresh = fake_refresh
        self.base_env = dict(os.environ if base_env is None else base_env)
        self.out = out or sys.stderr
        self.live_ledger = Path(live_ledger) if live_ledger else config.LIVE_LEDGER_DEFAULT


class Slots:
    """The experiment-wide pool of four physical slots: one OS lock file per slot. Every worker operation (a call, a
    features probe, a login status probe) owns its slot for its whole duration, reconciliation included."""

    def __init__(self, run_dir):
        self.dir = Path(run_dir) / 'slots'
        self.dir.mkdir(parents=True, exist_ok=True)
        self.held = {}

    def acquire(self, exclude=(), timeout=120, only=None):
        end = time.monotonic() + timeout
        while True:
            for k in range(config.SLOTS):
                if k in self.held or k in exclude or (only is not None and k != only):
                    continue
                handle = open(self.dir / f'slot-{k}.lock', 'a+b')
                if isolation._try_lock(handle):
                    self.held[k] = handle
                    return k
                handle.close()
            if time.monotonic() >= end:
                raise Stop(config.EXIT_BUSY, 'no free slot (another runner holds them)')
            time.sleep(0.05)

    def release(self, k):
        handle = self.held.pop(k, None)
        if handle is not None:
            isolation._unlock(handle)
            handle.close()


# ================================================================================================ executables

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_real(name, base_env, run_dir):
    found = shutil.which(name, path=base_env.get('PATH') or os.environ.get('PATH'))
    _append(run_dir, 'resolved.jsonl', {'name': name, 'path': found, 'at': _now()})
    return found


def cli_flags():
    doc = _read_json(config.CLI_FLAGS_FILE, {}) or {}
    supported = set(doc.get('supported') or [])
    return isolation.plan_disable_options(supported)


class Executables:
    """The executable and the frozen identity every launch group is verified against. Fake mode freezes the
    harness' own fakes at the start of the invocation; live mode verifies the real CLI against freeze.json. The
    executable and its launcher payload are hashed again before every launch group (verify)."""

    def __init__(self, opts, backend):
        self.opts, self.backend = opts, backend
        self.disable_args, self.unsupported = cli_flags()
        if opts.mode == 'fake':
            answers = workload.fake_answer_table()
            self.fakes = fake_cli.build(opts.run_dir, answers)
            self.exe = str(self.fakes['codex' if backend == 'codex' else 'claude'])
            self.prefix = [sys.executable]
            ident = isolation.executable_identity(self.exe)
            probe = isolation.codex_argv(self.exe, config.CODEX_MODEL, config.CODEX_EFFORT,
                                         opts.run_dir / 'work' / 'slot-0', self.disable_args)
            self.frozen = {'argv_sha256': isolation.argv_sha256(probe), 'exe_sha256': ident['sha256'],
                           'identity': ident}
        else:
            self.fakes = None
            name = 'codex' if backend == 'codex' else 'claude'
            found = resolve_real(name, opts.base_env, opts.run_dir)
            if not found:
                raise RuntimeError(f'{name} executable not found')
            self.exe = str(Path(found).resolve())
            self.prefix = []
            frozen = _read_json(config.FREEZE_FILE, {}) or {}
            fb = frozen.get(backend) or {}
            self.frozen = {'argv_sha256': (frozen.get('codex') or {}).get('argv_sha256'),
                           'exe_sha256': fb.get('exe_sha256'), 'identity': fb.get('identity')}
        self.exe_sha256 = self.frozen.get('exe_sha256')
        self.identity = None

    def verify(self):
        """Hash the executable and its explicit companion manifest now (council round 2, item 7); returns the problems
        against the frozen identity and records the file sizes and times every later per child check compares."""
        try:
            ident = isolation.executable_identity(self.exe)
        except OSError as exc:
            self.identity = None
            return [f'the executable cannot be inspected (fail closed): {type(exc).__name__}']
        self.identity, self.exe_sha256 = ident, ident['sha256']
        problems = isolation.identity_problems(ident, self.frozen.get('identity'))
        if ident['sha256'] != self.frozen.get('exe_sha256'):
            problems.append('executable hash differs from the frozen executable sha256 field')
        self.verified_stats = isolation.file_stats(isolation.identity_files(ident))
        return sorted(set(problems))

    def guard(self):
        """The write guard over every manifest file (Windows), held from the group's verification until its children
        have ended. Live mode requires it; fake mode records whether it was obtained."""
        files = isolation.identity_files(self.identity) if self.identity else [Path(self.exe)]
        return isolation.WriteGuard(files)

    def recheck(self):
        """The per child check immediately before Popen: the resolved path and the size and time of every manifest
        file are those verified for the group (the write guard keeps their contents fixed in between)."""
        if not self.identity:
            return ['the executable was not verified for this launch group']
        problems = []
        if not _same(Path(self.exe).resolve(), self.identity['path']):
            problems.append('the executable path resolves elsewhere than at verification')
        now = isolation.file_stats(isolation.identity_files(self.identity))
        if now != getattr(self, 'verified_stats', None):
            problems.append('an executable manifest file changed after the launch group was verified')
        return problems


# ================================================================================================ judging

def _turn_usage(stdout):
    """The usage of the stream's one turn.completed event; None (usage incomplete) when there is none or more than
    one, so a second turn never hides the first turn's tokens (RT2.4)."""
    found = events.turn_usages(stdout)
    return found[0] if len(found) == 1 else None


def account_usage(backend, usage_raw, reply, cache_certified, count=None):
    """Every accounting field of one call derived from its captured usage with the frozen predicates (A4.7): the
    decoded usage, the usage status, the reasoning issue, the additive tokens, the visible reply tokens and the
    charged tokens. The runner, recovery and the scorer all use this function, so a recorded field that the capture
    does not give is an artifact problem (council round 2, item 10). `count` counts visible reply tokens."""
    if backend == 'codex':
        visible = None
        if isinstance(reply, str):
            visible = (count or tokenizer.count)([reply])[0]
        dec = usage.decode_codex_checked(usage_raw, cache_certified=cache_certified)
        issue = None
        if dec['status'] != 'incomplete':
            issue = usage.reasoning_inclusion(usage_raw, visible)
        status = dec['status']
        if issue and status == 'complete':
            status = 'unverified'
        cache_write = isinstance(usage_raw, dict) and (usage_raw.get('cache_write_input_tokens') or 0) > 0
        if status == 'complete' and cache_write:
            status = 'unverified'
            dec = dict(dec, problems=list(dec['problems']) + ['cache_write_input_tokens positive: its relation to '
                                                              'input_tokens is uncertified'])
        additive = usage.additive_tokens(usage_raw) if dec['status'] != 'incomplete' and \
            dec.get('charged_tokens') is not None else None
    else:
        visible, issue = None, None
        dec = usage.decode_sonnet(usage_raw)
        status, additive = dec['status'], None
        if dec['status'] != 'incomplete':
            additive = usage_raw['input_tokens'] + usage_raw['cached_input_tokens'] + usage_raw['output_tokens']
    return {'usage': dec, 'usage_status': status, 'reasoning_issue': issue, 'additive_tokens': additive,
            'visible_tokens': visible, 'charged_tokens': dec.get('charged_tokens') or 0,
            'cache_certified': cache_certified if backend == 'codex' else None}


def auth_failure_detected(stdout, stderr):
    """Authentication failure from the error channels only, independent of the event verdict, timeout and exit."""
    return any(AUTH_FAILURE_RE.search(t or '') for t in events.error_messages(stdout) + [stderr or ''])


def judge_codex(raw):
    """(outcome, reply, usage raw, event verdict, why) of one Codex call. Order (council round 1, items 5 and 13, B1,
    RT1.4): an authentication failure first, whatever else happened; then a tool event verdict (executed, uncertain,
    refused), which is terminal whatever the timeout or exit code; then a delivered reply (the turn completed), which
    is accepted even after a timeout or a nonzero exit, so it is never sent again; only then the frozen
    infrastructure predicate (no reply delivered), the one retryable outcome."""
    import codex_cli_adapter
    stdout, stderr = raw.get('stdout') or '', raw.get('stderr') or ''
    cls = events.classify_stream(stdout)
    reply, _, failure = codex_cli_adapter.parse_events(stdout)
    usage_raw = _turn_usage(stdout)
    if auth_failure_detected(stdout, stderr):
        return 'auth_failure', None, usage_raw, cls, 'authentication failure'
    if cls['verdict'] in ('executed', 'uncertain', 'refused'):
        return cls['verdict'], None, usage_raw, cls, None
    clean_exit = raw.get('exit_code') == 0 and not raw.get('timed_out')
    delivered = isinstance(reply, str) and failure is None and (events.turn_completed(stdout) or clean_exit)
    if delivered:
        why = None
        if raw.get('timed_out'):
            why = 'timed out after the reply was delivered'
        elif raw.get('exit_code') != 0:
            why = f'exit {raw.get("exit_code")} after the reply was delivered'
        return 'ok', reply, usage_raw, cls, why
    if raw.get('timed_out'):
        return 'infrastructure_failure', None, usage_raw, cls, 'timeout'
    return 'infrastructure_failure', None, usage_raw, cls, (failure or f'exit {raw.get("exit_code")}')[:300]


def judge_sonnet(raw):
    """The Sonnet equivalent: the envelope is classified even after a timeout or a nonzero exit, and a delivered
    result is accepted, so a refusal, a tool use or a delivered answer is never retried."""
    import claude_cli_adapter
    try:
        data = json.loads(raw.get('stdout') or '')
    except ValueError:
        data = None
    if not isinstance(data, dict):
        why = 'timeout' if raw.get('timed_out') else f'exit {raw.get("exit_code")}'
        return 'infrastructure_failure', None, None, events.classify_claude({}), why
    cls = events.classify_claude(data)
    usage_raw = claude_cli_adapter.usage_from_envelope(data)
    if cls['verdict'] != 'plain':
        return cls['verdict'], None, usage_raw, cls, None
    if isinstance(data.get('result'), str) and not data.get('is_error'):
        why = None
        if raw.get('timed_out'):
            why = 'timed out after the result was delivered'
        elif raw.get('exit_code') != 0:
            why = f'exit {raw.get("exit_code")} after the result was delivered'
        return 'ok', data['result'], usage_raw, cls, why
    return 'infrastructure_failure', None, usage_raw, cls, f'exit {raw.get("exit_code")}'


def login_state(text):
    t = (text or '').lower()
    if 'not logged in' in t:
        return 'not_logged_in'
    if 'logged in' in t:
        return 'logged_in'
    return 'unknown'


# ================================================================================================ recovery

class Stop(Exception):
    def __init__(self, code, reason):
        Exception.__init__(self, reason)
        self.code, self.reason = code, reason


def _home_shows_start(home, prepared_sha):
    home = Path(home)
    if not home.exists():
        return False
    others = [p for p in home.rglob('*') if p.relative_to(home).as_posix() != isolation.AUTH]
    if others:
        return True
    auth = home / isolation.AUTH
    return auth.exists() and prepared_sha is not None and isolation.sha256_file(auth) != prepared_sha


def raw_paths(run_dir, slot, call_id):
    d = Path(run_dir) / 'homes' / f'raw-{slot}'
    return d / f'{call_id}.stdout', d / f'{call_id}.stderr'


def capture_paths(run_dir, call_id):
    d = Path(run_dir) / 'captures'
    return d / f'{call_id}.stdout', d / f'{call_id}.stderr', d / f'{call_id}.meta.json'


def write_captures(run_dir, call_id, stdout, stderr, meta):
    """The sanitized capture of one call and its per channel redaction record (bytes, so the capture hashes exactly
    like the text the call was judged on)."""
    out, err, mp = capture_paths(run_dir, call_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(stdout.encode('utf-8'))
    err.write_bytes(stderr.encode('utf-8'))
    _write_json(mp, meta)


def sanitize(stdout, stderr, secrets):
    """(clean stdout, clean stderr, per channel redaction record) (council round 2, item 6)."""
    clean_out, r1 = redact.redact(stdout or '', secrets)
    clean_err, r2 = redact.redact(stderr or '', secrets)
    rec = redact.channels(stdout=(stdout or '', clean_out, r1), stderr=(stderr or '', clean_err, r2))
    return clean_out, clean_err, rec


def attempt_row(marker, outcome, why, raw, cls, usage_raw, acct, redaction, fin, extra=None):
    """The attempts.jsonl row of one judged call (after_group and recovery build it the same way)."""
    base = {k: v for k, v in marker.items() if k not in ('phase', 'secret_fingerprints', 'mapping', 'ops')}
    row = dict(base, outcome=outcome, why=why, exit_code=raw.get('exit_code'), timed_out=raw.get('timed_out'),
               started_at=raw.get('started_at') or marker.get('started_at'), ended_at=raw.get('ended_at'),
               elapsed_s=raw.get('elapsed_s'), stdout_sha256=prompts.sha256(raw['stdout']),
               stderr_sha256=prompts.sha256(raw['stderr']), events={
                   'verdict': cls['verdict'], 'efficiency_invalid': cls['efficiency_invalid'],
                   'external_read': cls['external_read'], 'notices': len(cls['notices']),
                   'tool_requests': cls['tool_requests'], 'tool_executions': cls['tool_executions'],
                   'uncertain': cls['uncertain'][:20], 'turns': cls.get('turns'),
                   'transport_notices': len(cls.get('transport_notices') or [])},
               usage_raw=usage_raw, usage=acct['usage'], usage_status=acct['usage_status'],
               reasoning_issue=acct['reasoning_issue'], visible_tokens=acct['visible_tokens'],
               cache_certified=acct['cache_certified'], charged_tokens=acct['charged_tokens'],
               additive_tokens=acct['additive_tokens'], redaction=redaction,
               credential_disclosure=bool(redaction.get('redactions')),
               auth=None if fin is None else {k: fin[k] for k in ('worker_auth_sha256', 'baseline_auth_sha256',
                                                                   'auth_changed', 'auth_failure')},
               runtime_files=None if fin is None else len(fin['runtime_files']))
    row.update(extra or {})
    return row


def _recovered_call(m):
    ids = list(m.get('job_ids') or [])
    mapping = m.get('mapping') or dict(zip(prompts.packet_ids(len(ids)), ids))
    return {'call_id': m.get('call_id'), 'jobs': [{'id': j} for j in ids], 'inp': {'mapping': mapping,
                                                                                     'ops': m.get('ops')},
            'bootstrap': bool(m.get('bootstrap'))}


def not_launched_row(marker, reason):
    """A reserved call proven never started (no Popen): it keeps its allocation debit, has zero model usage and no
    capture (council round 2, B2, RT2.3)."""
    base = {k: v for k, v in marker.items() if k not in ('phase', 'secret_fingerprints', 'mapping', 'ops')}
    return dict(base, outcome='not_launched', why=reason, exit_code=None, timed_out=False, ended_at=_now(),
                elapsed_s=0.0, usage_raw=None, usage={'status': 'not_launched', 'problems': []},
                usage_status='not_launched', charged_tokens=0, additive_tokens=0, credential_disclosure=False,
                events={'verdict': 'not_launched', 'uncertain': []}, auth=None, runtime_files=None)


def _recover_stream(run_dir, m, secrets_now, recovered_at):
    """(raw dict, redaction record, how) of an orphan from its durable stream, in order: committed captures, then the
    raw stream files of its slot; (None, None, reason) when neither can be used. Raw streams are promoted only when
    every secret fingerprint recorded at preparation is covered by the secrets available now; otherwise they stay
    quarantined inside the credential boundary (council round 2, items 3 and 6)."""
    cid = m.get('call_id')
    slot = m.get('slot')
    out_p, err_p, meta_p = capture_paths(run_dir, cid)
    if out_p.exists() and err_p.exists():
        meta = _read_json(meta_p, {}) or {}
        raw = {'stdout': out_p.read_bytes().decode('utf-8', 'replace'),
               'stderr': err_p.read_bytes().decode('utf-8', 'replace')}
        rec = meta.get('redaction') or {'redactions': 0, 'kinds': []}
        if isinstance(slot, int) and not isinstance(slot, bool):
            raws = raw_paths(run_dir, slot, cid)
            originals = _read_raw(raws) if raws[0].exists() else None
            chans = rec.get('channels') or {}
            if originals is not None and any(
                    prompts.sha256(text) != (chans.get(ch) or {}).get('original_sha256')
                    for ch, text in zip(('stdout', 'stderr'), originals)):
                raw['raw_mismatch'] = True
        return raw, rec, 'capture'
    if isinstance(slot, int) and not isinstance(slot, bool):
        r_out, r_err = raw_paths(run_dir, slot, cid)
        if r_out.exists() or r_err.exists():
            want = set(m.get('secret_fingerprints') or [])
            have = {isolation.sha256_text(x) for x in secrets_now}
            if want - have:
                return None, None, 'raw stream quarantined: the prepared secrets are not all available to redact it'
            stdout, stderr = _read_raw((r_out, r_err))
            clean_out, clean_err, rec = sanitize(stdout, stderr, secrets_now)
            return {'stdout': clean_out, 'stderr': clean_err}, rec, 'raw_stream'
    return None, None, 'no capture and no raw stream'


def recover_inflight(run_dir, opts, say=None, iso=None):
    """Experiment wide recovery before anything else (council rounds 1 and 2, items 3, B3, RT2.1, 14). Each marker:

    * a child recorded alive (pid and creation time) stops the resume; nothing is touched;
    * `reserved` (no Popen was ever called): a `not_launched` attempt, charged, zero usage;
    * `spawning` without a pid: the process identity is ambiguous; Codex stops, the marker, the home and any raw
      stream are preserved and no attempt is written (the scorer reports the unrecovered marker);
    * an orphan (no attempt row) of a started child: judged from its committed capture, else from its raw stream
      files, exactly as after_group judges a call; the terminal outcome is kept and never resent. Only without any
      usable stream is it `interrupted`, with the event verdict `uncertain` (no capture), which is leakage (P2);
    * a recorded call whose reconciliation did not finish: reconciled.

    Every Codex worker of a marker is inventoried and reconciled against the baseline generation it was prepared
    from; open timing windows of dead invocations are closed with bounds. Returns the recovery record."""
    run_dir = Path(run_dir)
    close_dead_windows(run_dir)
    markers = []
    for path in sorted(run_dir.glob('cells/*/inflight/*.json')):
        m = _read_json(path)
        markers.append((path, m if isinstance(m, dict) else {'call_id': None, 'unreadable': True}))
    if not markers:
        return None
    attempts = jsonl(run_dir / 'attempts.jsonl')
    by_key = {(a.get('attempt_uid') or a.get('call_id')): a for a in attempts}

    def key(m):
        return m.get('attempt_uid') or m.get('call_id')

    alive = [m for _, m in markers if key(m) not in by_key and pid_alive(m.get('pid'), m.get('pid_created'))]
    if alive:
        raise Stop(config.EXIT_INTERRUPTED, 'calls recorded in flight are still running (pids '
                   f"{sorted(m.get('pid') for m in alive)}); resume after they have ended (nothing was touched)")
    now = _now()
    record = {'at': now, 'markers': [m.get('call_id') for _, m in markers], 'action': 'none', 'ambiguous': [],
              'recovered': {}}
    iso = iso or isolation.Isolation(opts.baseline, run_dir, run_dir / 'evidence',
                                     frozen_inventory=isolation.load_inventory(), base_env=opts.base_env)
    keep = set()
    ambiguous, other_ambiguous = [], []
    for path, m in markers:
        if m.get('unreadable'):
            ambiguous.append('an unreadable in-flight marker')
            keep.add(path)
        elif m.get('marker') != 'probe' and m.get('phase') not in ('reserved', 'prepared') and not m.get('pid') \
                and key(m) not in by_key:
            # `spawning` (or a marker without a phase) and no journaled pid: the child may have started, and
            # nothing can establish that it ended (council round 2, item 3)
            (ambiguous if m.get('backend') == 'codex' else other_ambiguous).append(
                f"{m.get('call_id')}: no journaled pid for a call that may have started (phase {m.get('phase')!r}); "
                f"the marker, the worker home and any raw stream are kept")
            keep.add(path)
    record['kept'] = other_ambiguous
    workers, fins = {}, {}
    for path, m in markers:
        if path in keep or m.get('backend') != 'codex':
            continue
        cid, slot = m.get('call_id'), m.get('slot')
        if not isinstance(slot, int) or isinstance(slot, bool):
            ambiguous.append(f'{cid}: no slot recorded')
            keep.add(path)
            continue
        home = iso.home(slot)
        if not home.exists():
            if m.get('phase') in ('reserved', 'prepared'):
                continue  # never started: nothing to reconcile
            ambiguous.append(f'{cid}: worker home missing after a spawn')
            continue
        if slot in workers:
            ambiguous.append(f'slot {slot}: more than one unreconciled marker')
            continue
        fin = iso.finish(slot, prepared_sha256=m.get('prepared_sha'))
        fins[key(m)] = fin
        row = by_key.get(key(m)) or {}
        workers[slot] = {'sha256': fin['worker_auth_sha256'], 'prepared': m.get('prepared_sha'),
                         'auth_failure': row.get('outcome') == 'auth_failure' and m.get('role') != 'probe',
                         'call_id': cid, 'probe': m.get('role') == 'probe'}
    secrets_now = redact.secrets_from_auth(Path(opts.baseline) / isolation.AUTH,
                                           *[iso.home(s) / isolation.AUTH for s in range(config.SLOTS)])
    quarantined = []
    for path, m in markers:
        if path in keep:
            continue
        cid = m.get('call_id')
        if not cid or m.get('marker') == 'probe' or key(m) in by_key:
            continue
        fin = fins.get(key(m))
        if m.get('phase') in ('reserved', 'prepared'):
            row = not_launched_row(m, 'recovery: the call was reserved but never started (no Popen)')
            _append(run_dir, 'attempts.jsonl', row)
            record['recovered'][cid] = 'not_launched'
            continue
        raw, redaction, how = _recover_stream(run_dir, m, secrets_now, now)
        if raw is None:
            if how.startswith('raw stream quarantined'):
                quarantined.append(cid)
            row = dict({k: v for k, v in m.items() if k not in ('phase', 'secret_fingerprints', 'mapping', 'ops')},
                       outcome='interrupted', ended_at=None, ended_at_upper=now, elapsed_s=None,
                       usage_status='incomplete', charged_tokens=0, note='the runner ended while the call was in '
                       f'flight; {how}', recovered_from=None,
                       events={'verdict': 'uncertain', 'efficiency_invalid': True,
                               'uncertain': [{'reason': f'possible launch without a capture: {how} (A4.3, P2)'}]},
                       auth=None if fin is None else {k: fin[k] for k in ('worker_auth_sha256', 'baseline_auth_sha256',
                                                                            'auth_changed', 'auth_failure')},
                       runtime_files=None if fin is None else len(fin['runtime_files']))
            _append(run_dir, 'attempts.jsonl', row)
            record['recovered'][cid] = 'interrupted'
            continue
        raw.update(exit_code=None, timed_out=False, started_at=m.get('spawned_at') or m.get('started_at'),
                   ended_at=None, elapsed_s=None)
        judge = judge_codex if m.get('backend') == 'codex' else judge_sonnet
        outcome, reply, usage_raw, cls, why = judge(raw)
        c = _recovered_call(m)
        output = CellRun.interpret(None, c, outcome, reply)
        if m.get('cell') in ('telemetry', 'features'):
            output['outcome'] = outcome
        acct = account_usage(m.get('backend'), usage_raw, reply, usage.cache_certified_for_route()
                             if m.get('backend') == 'codex' else None)
        if how == 'raw_stream':
            write_captures(run_dir, cid, raw['stdout'], raw['stderr'],
                           {'call_id': cid, 'cell': m.get('cell'), 'redaction': redaction, 'recovered': True})
        cell_dir = run_dir / 'cells' / str(m.get('cell'))
        if not (cell_dir / 'calls' / f'{cid}.json').exists():
            _write_json(cell_dir / 'calls' / f'{cid}.json', output)
        row = attempt_row(m, output['outcome'], why, raw, cls, usage_raw, acct, redaction, fin,
                          extra={'recovered_from': how, 'ended_at_upper': now,
                                 'raw_mismatch': bool(raw.get('raw_mismatch')),
                                 'note': 'recovered after the runner ended: exit code and end time unknown'})
        if m.get('expected_outcome'):
            row['expected_outcome'] = m['expected_outcome']
        _append(run_dir, 'attempts.jsonl', row)
        record['recovered'][cid] = output['outcome']
        if outcome == 'auth_failure' and m.get('role') != 'probe':
            for w in workers.values():
                if w['call_id'] == cid:
                    w['auth_failure'] = True
        for p in raw_paths(run_dir, m.get('slot'), cid) if isinstance(m.get('slot'), int) else ():
            with contextlib.suppress(OSError):
                p.unlink()
    if quarantined:
        ambiguous.append(f'raw streams quarantined (redaction coverage not established): {quarantined[:5]}')
    if any(m.get('backend') == 'codex' for _, m in markers) or ambiguous:
        reconcile_workers = {s: w for s, w in workers.items() if not w.get('probe')}
        base = iso.baseline_sha256()
        verdict = isolation.reconcile_generations(base, reconcile_workers, ambiguous)
        record.update(action=verdict['action'], ambiguous=ambiguous, baseline_auth_sha256=base,
                      workers={str(s): {k: w.get(k) for k in ('sha256', 'prepared', 'auth_failure', 'call_id')}
                               for s, w in workers.items()})
        if verdict['action'] == 'propagate':
            try:
                iso.propagate(verdict['slot'], expected_baseline_sha256=workers[verdict['slot']]['prepared'])
                lineage(run_dir, iso.baseline, 'propagated', slot=verdict['slot'])
            except isolation.IsolationError as exc:
                verdict = {'action': 'stop_codex', 'reason': f'propagation refused: {exc}'}
                record['action'] = 'stop_codex'
        if verdict['action'] == 'stop_codex':
            _write_json(run_dir / 'codex-stop.json', {'reason': 'recovery: ' + verdict.get('reason', ''),
                                                      'cell': None, 'at': _now()})
        _append(run_dir, 'evidence/auth-reconcile.jsonl', dict(record, recovery=True, reason=verdict.get('reason')))
    _append(run_dir, 'evidence/recovery.jsonl', record)
    for path, _ in markers:
        if path in keep:
            continue
        with contextlib.suppress(OSError):
            path.unlink()
    if say:
        say(f"recovered {len(markers) - len(keep)} in-flight marker(s): {record['action']}"
            + (f'; {len(keep)} kept (ambiguous)' if keep else ''))
    return record


def lineage(run_dir, baseline, event, **extra):
    """evidence/auth-lineage.jsonl: the baseline's token hashes (never the strings) at first dispatch, after every
    propagation and whenever a gate sees a changed baseline (council round 2, RT2.6 and C2)."""
    try:
        hashes = isolation.token_hashes(Path(baseline) / isolation.AUTH)
    except isolation.IsolationError:
        hashes = None
    row = dict(extra, event=event, at=_now(), tokens=hashes, **isolation.auth_record(baseline))
    _append(run_dir, 'evidence/auth-lineage.jsonl', row)
    return row


# ------------------------------------------------------------------------------------------------ timing windows

def _window_rows(run_dir, cid):
    return jsonl(Path(run_dir) / 'cells' / cid / 'windows.jsonl')


def close_dead_windows(run_dir):
    """Close every timing window opened by an invocation that ended without closing it (council round 2, item 14):
    the upper end bound is now (the recovery time), the lower end bound the last durable work timestamp of that
    invocation (its attempts' ends or starts, else the window start). Never an exact end."""
    run_dir = Path(run_dir)
    for wfile in sorted(run_dir.glob('cells/*/windows.jsonl')):
        cid = wfile.parent.name
        rows = jsonl(wfile)
        closed = {r.get('invocation') for r in rows if r.get('event') == 'close'}
        for r in rows:
            if r.get('event') != 'open' or r.get('invocation') in closed or r.get('invocation') in ACTIVE_INVOCATIONS:
                continue
            inv = r.get('invocation')
            stamps = [r.get('started_at')]
            for a in jsonl(run_dir / 'attempts.jsonl'):
                if a.get('cell') == cid and str(a.get('group') or '').startswith(f'{inv}.'):
                    stamps += [a.get('started_at'), a.get('ended_at')]
            stamps = [s for s in stamps if _parse_time(s) is not None]
            lower = max(stamps, key=_parse_time) if stamps else r.get('started_at')
            _append(run_dir, f'cells/{cid}/windows.jsonl', {
                'event': 'close', 'invocation': inv, 'reconstructed': True, 'ended_at': None,
                'ended_at_lower': lower, 'ended_at_upper': _now(), 'ended': 'recovered'})


# ================================================================================================ the cell runner

class CellRun:
    def __init__(self, spec, opts):
        self.spec, self.opts = spec, opts
        self.run_dir = opts.run_dir
        self.dir = self.run_dir / 'cells' / spec['id']
        self.backend, self.workload = spec['backend'], spec['workload']
        self.codex = self.backend == 'codex'
        self.launched = 0
        self.invocation_calls = 0
        self.interrupted = None
        self.lock = threading.Lock()
        self.invocation = f'{os.getpid()}-{int(time.time() * 1000)}-{id(self) % 10000}'
        self.group_seq = 0
        self.current_group = None
        self.iso = None
        self.slots = None
        self.exe = None
        self.budget_obj = None
        self.cache_certified = None
        self.role = 'call'
        self.scrambled_probe = False
        self.run_uid = None
        self.expected = None

    # ------------------------------------------------------------------------------------------- state

    def state(self, state, **extra):
        doc = _read_json(self.dir / 'state.json', {}) or {}
        doc.update(extra, state=state, cell=self.spec['id'], updated_at=_now())
        doc.setdefault('invocations', [])
        _write_json(self.dir / 'state.json', doc)

    def say(self, text):
        self.opts.out.write(text.rstrip() + '\n')

    # ------------------------------------------------------------------------------------------- gates

    def harvested_observations(self):
        out = {}
        for r in jsonl(self.run_dir / 'evidence' / 'quota-observations.jsonl'):
            out.setdefault(r.get('attempt_uid') or r.get('call_id'), []).append(r)
        return out

    def experiment_attempts(self):
        """The attempts of this run directory and (live) of every superseded run directory of the experiment."""
        rows = list(jsonl(self.run_dir / 'attempts.jsonl'))
        if self.opts.mode == 'live':
            for d in predecessor_dirs(self.run_dir, self.opts.live_ledger):
                rows += jsonl(Path(d) / 'attempts.jsonl')
        return rows

    def codex_quota_gate(self):
        """The P3 gate before every synchronized Codex dispatch group (council round 2, items 31, B8, RT2.5): every
        completed live Codex call of the experiment covered by an observation with an event timestamp after it (or
        its own rollout reading), the latest owner reading valid, the highest covering percentage below 80."""
        return quota.coverage_gate(self.experiment_attempts(), self.opts.sessions_dir, self.harvested_observations(),
                                   isolation.account_sha256(self.opts.baseline))

    def owner_auth(self):
        return isolation.owner_auth_paths(self.opts.base_env) if self.opts.mode == 'live' else []

    def separation_gate(self):
        """A4.2 (RT2.6): the baseline shares no token with the owner home or the runner's CODEX_HOME (live)."""
        problems = isolation.token_separation_problems(self.opts.baseline, self.owner_auth())
        if problems:
            raise Stop(config.EXIT_AUTH_GATE, f'baseline token separation check failed (A4.2): {problems[:3]}; '
                                              + isolation.LOGIN_HINT.format(baseline=self.opts.baseline))

    def gates(self):
        opts = self.opts
        if (self.run_dir / 'safety-kill.json').exists():
            raise Stop(config.EXIT_SAFETY_KILL, 'a safety kill is established for this run (A4.11); no further dispatch')
        if self.codex:
            gate = isolation.wave_gate(opts.baseline)
            record = isolation.auth_record(opts.baseline)
            previous = [r for r in jsonl(self.run_dir / 'evidence' / 'wave-gates.jsonl') if r.get('auth_sha256')]
            changed = bool(previous) and previous[-1].get('auth_sha256') != record['auth_sha256']
            _append(self.run_dir, 'evidence/wave-gates.jsonl', dict(record, cell=self.spec['id'], ok=gate['ok'],
                                                                    hours_left=gate['hours_left'],
                                                                    baseline_changed=changed, at=_now()))
            if changed and opts.mode == 'live':
                lineage(self.run_dir, opts.baseline, 'observed_baseline_change', cell=self.spec['id'])
            if not gate['ok']:
                raise Stop(config.EXIT_AUTH_GATE, 'baseline authentication gate failed (A4.2): ' + gate['reason'])
            problems = isolation.verify_baseline(opts.baseline, isolation.load_inventory())
            if problems:
                raise Stop(config.EXIT_AUTH_GATE, f'baseline inventory check failed (A4.2): {problems[:5]}; '
                                                  f'reseed with: CODEX_HOME={opts.baseline} codex login')
            if opts.mode == 'live':
                self.separation_gate()
            if (self.run_dir / 'codex-stop.json').exists():
                raise Stop(config.EXIT_AUTH_STOP, 'Codex evaluation is stopped for this run (A4.2 reconciliation)')
        if opts.mode == 'live':
            g = quota.claude_gate(opts.claude_percent)
            if not g['ok']:
                raise Stop(config.EXIT_QUOTA, g['reason'])
            if not _same(self.run_dir, live_run_dir()):
                raise Stop(config.EXIT_IDENTITY, f'live cells run only in the frozen live run directory '
                                                 f'{live_run_dir()} (A4.1, A4.5); another directory needs a new '
                                                 f'freeze and a recorded council disposition')
            problems = ledger_problems(self.run_dir, opts.live_ledger)
            if problems:
                raise Stop(config.EXIT_IDENTITY, f'experiment ledger check failed: {problems}')
            if self.spec['arm'] != 'telemetry':
                terminal, missing = superseded_terminal_batches(self.run_dir, opts.live_ledger, self.spec['id'])
                if missing or terminal:
                    raise Stop(config.EXIT_IDENTITY, f"{self.spec['id']}: a superseded run directory holds terminal "
                                                     f'batches {terminal[:5]} or lacks evidence {missing[:2]}; a '
                                                     f'replacement directory never repeats them (A4.3, item 9)')
            problems = verify_freeze()
            if problems:
                raise Stop(config.EXIT_FREEZE, f'freeze verification failed (A4.1): {problems[:5]}')
            bound = _read_json(self.run_dir / 'experiment.json')
            if bound and bound.get('freeze_sha256') != freeze_sha256():
                raise Stop(config.EXIT_FREEZE, 'freeze.json was replaced after this run was bound to it (A4.1)')
            if self.codex:
                if tokenizer.count(['probe'])[0] is None or not tokenizer.vocabulary_ok():
                    raise Stop(config.EXIT_FREEZE, 'the pinned tokenizer is unavailable; every call would be '
                                                   'unverified (sign-off 5 predicate)')
                if self.spec['arm'] != 'telemetry':
                    problems = telemetry_problems(self.run_dir)
                    if problems:
                        raise Stop(config.EXIT_TELEMETRY, f'telemetry certificate not established (A4.2): '
                                                          f'{problems[:5]}')
        _, problems = bootstrap_mod.validate_classification()
        if problems:
            raise Stop(config.EXIT_CLASSIFICATION, f'classification invalid (A4.6): {problems[:5]}')

    # ------------------------------------------------------------------------------------------- resume

    def prior_attempts(self):
        return [a for a in jsonl(self.run_dir / 'attempts.jsonl') if a.get('cell') == self.spec['id']]

    def budget(self):
        """Every physical call charged so far (council round 2, item 9, RT2.2). Fake: this run directory's attempts.
        Live: the experiment ledger (every run directory) plus this run directory's attempts, deduplicated by the
        attempt's globally unique uid, so no superseded call stops counting when a call id repeats."""
        b = budget_mod.Budget()
        seen = set()
        here = str(self.run_dir.resolve())
        rows = [dict(a, run_dir=a.get('run_dir') or here) for a in jsonl(self.run_dir / 'attempts.jsonl')]
        if self.opts.mode == 'live':
            ledger, _ = ledger_rows(self.opts.live_ledger)
            rows = ledger + rows
        for a in rows:
            k = a.get('attempt_uid') or (a.get('run_dir'), a.get('call_id'))
            if k in seen:
                continue
            seen.add(k)
            b._attempts.append({k2: a.get(k2) for k2 in ('backend', 'workload', 'allocation', 'reason', 'kind',
                                                         'outcome')})
        return b

    # ------------------------------------------------------------------------------------------- calls

    def batch_key(self, round_no, idx):
        return f'r{round_no}.b{idx:02d}'

    def stop_reason(self):
        if (self.run_dir / 'safety-kill.json').exists():
            return config.EXIT_SAFETY_KILL, 'safety kill established (A4.11)'
        if self.codex and (self.run_dir / 'codex-stop.json').exists():
            return config.EXIT_AUTH_STOP, 'Codex evaluation stopped (A4.2)'
        return None

    def run_batches(self, batches, round_no, bootstrap=False, first_reason='nominal'):
        """Execute every batch (list of job lists) of one round; returns {batch key: call output}. Batches whose
        latest attempt is terminal are taken from disk and never sent again.

        One launch group (council round 2, items 7, B2, RT2.3): verify the executable and its manifest and hold the
        write guard; stage every member (no ledger charge); reserve the whole group under the experiment lock
        (shared prerequisites revalidated, markers, then ledger rows) before any spawn; each child gets a final
        check immediately before Popen; the guard is released when every child has ended."""
        prior = self.prior_attempts()
        results, pending = {}, []
        kept = {(_read_json(p, {}) or {}).get('batch') for p in self.dir.glob('inflight/*.json')}
        for idx, jobs in enumerate(batches):
            key = self.batch_key(round_no, idx)
            mine = [a for a in prior if a.get('batch') == key]
            last = mine[-1] if mine else None
            if key in kept:
                # an ambiguous in-flight marker kept by recovery: the call may have run, so it is never resent
                results[key] = {'outcome': 'interrupted', 'answers': {}, 'job_ids': [j['id'] for j in jobs]}
                self.interrupted = self.interrupted or (config.EXIT_INTERRUPTED, f'{key}: an ambiguous in-flight '
                                                        'marker is kept (process identity not established)')
                continue
            if last is not None and last['outcome'] not in RETRYABLE:
                results[key] = _read_json(self.dir / 'calls' / f"{last['call_id']}.json", {}) or {}
                results[key].setdefault('outcome', last['outcome'])
                continue
            pending.append((key, jobs, len(mine), first_reason if not mine else 'infrastructure_retry'))
        # First attempts before retries, so a retry never takes a nominal call another batch still needs.
        pending.sort(key=lambda item: (item[2] > 0, item[0]))
        while pending:
            group, waiting = [], []
            self.group_seq += 1
            self.current_group = f'{self.invocation}.r{round_no}.g{self.group_seq}'
            stop = self.stop_reason()
            if stop and not self.interrupted:
                self.interrupted = stop
            guard = None
            if not self.interrupted:
                problems = self.exe.verify()
                if problems:
                    raise Stop(config.EXIT_FREEZE, f'executable verification before the launch group failed (A4.2): '
                                                   f'{problems}')
                guard = self.exe.guard().__enter__()
                if self.opts.mode == 'live' and not guard.held:
                    guard.__exit__(None, None, None)
                    raise Stop(config.EXIT_FREEZE, f'the executable write guard could not be held (A4.2, item 7): '
                                                   f'{guard.problems[:3] or ["no platform guard"]}')
            try:
                for item in pending:
                    if len(group) >= config.SLOTS:
                        waiting.append(item)
                        continue
                    key, jobs, tries, reason = item
                    if self.opts.stop_after is not None and self.launched >= self.opts.stop_after:
                        self.interrupted = (config.EXIT_INTERRUPTED, f'--stop-after {self.opts.stop_after} reached')
                        waiting.append(item)
                        continue
                    if self.interrupted:
                        waiting.append(item)
                        continue
                    try:
                        prepared = self.prepare_call(key, jobs, tries, reason, bootstrap)
                    except (Stop, isolation.IsolationError) as exc:
                        self.abandon(group)
                        if isinstance(exc, Stop):
                            raise
                        raise Stop(config.EXIT_INCOMPLETE, f'{key}: isolation error while preparing (A4.2): {exc}')
                    if prepared is None:
                        results[key] = {'outcome': 'budget_exhausted', 'answers': {},
                                        'job_ids': [j['id'] for j in jobs]}
                        continue
                    group.append(prepared)
                if group:
                    try:
                        self.reserve_group(group)
                    except (Stop, isolation.IsolationError) as exc:
                        self.abandon(group)
                        if isinstance(exc, Stop):
                            raise
                        raise Stop(config.EXIT_INCOMPLETE, f'isolation error while reserving (A4.2): {exc}')
                    threads = [threading.Thread(target=self.execute, args=(c,), daemon=True) for c in group]
                    for t in threads:
                        t.start()
                    for t in threads:
                        t.join()
            finally:
                if guard is not None:
                    guard.__exit__(None, None, None)
            if group:
                self.after_group(group)
            pending = []
            for c in group:
                if c.get('unsettled'):
                    continue
                if c['outcome'] in RETRYABLE and not self.interrupted:
                    pending.append((c['batch'], c['jobs'], c['try'] + 1, 'infrastructure_retry'))
                else:
                    results[c['batch']] = c['output']
            if self.interrupted:
                for item in waiting:
                    results.setdefault(item[0], {'outcome': 'not_launched', 'answers': {},
                                                 'job_ids': [j['id'] for j in item[1]]})
                for c in group:
                    if c.get('unsettled'):
                        results.setdefault(c['batch'], {'outcome': 'interrupted', 'answers': {},
                                                        'job_ids': [j['id'] for j in c['jobs']]})
                    elif c['outcome'] in RETRYABLE:
                        results[c['batch']] = c['output']
                break
            pending = waiting + pending
            if not group and pending:
                break
        return results

    def model_input(self, jobs, bootstrap):
        return prompts.model_input(jobs, self.workload, bootstrap=bootstrap)

    def charge(self, reason):
        allocation = self.spec['allocation']
        return self.budget_obj.charge(self.backend, self.workload, allocation, reason=reason, outcome='launched')

    def launch_env(self, prepared):
        return prepared['env']

    def prepare_call(self, key, jobs, tries, reason, bootstrap):
        """Stage one call in the launching thread, before its group is reserved: the model input, the leak check, the
        slot, the worker home reconstruction (under the authentication lock, after the token separation check) and
        launch verification (Codex), and the in-memory budget charge. Nothing is written to the experiment ledger
        and no in-flight marker exists yet. Returns None when the budget refuses the call."""
        import uuid
        spec = self.spec
        call_id = f"{spec['id']}.{key}.t{tries}"
        inp = self.model_input(jobs, bootstrap)
        record = prompts.prompt_record(inp)
        leaks = prompts.learner_prompt_leaks(record, workload.materials()['admission'])
        if leaks:
            raise Stop(config.EXIT_INCOMPLETE, f'{call_id}: admission material in a model-bound prompt (A4.8)')
        if self.codex:
            problems = isolation.verify_baseline(self.opts.baseline, isolation.load_inventory())
            if problems:
                raise Stop(config.EXIT_AUTH_GATE, f'{call_id}: baseline inventory check failed (A4.2): {problems[:5]}')
        slot = self.slots.acquire()
        try:
            listing_before = workdir_before = None
            secrets, fingerprints = set(), []
            if self.codex:
                try:
                    prepared = self.iso.prepare(slot, scrambled=self.role == 'probe' and self.scrambled_probe)
                except isolation.IsolationError as exc:
                    if 'token separation' in str(exc):
                        raise Stop(config.EXIT_AUTH_GATE, f'{call_id}: {exc}') from None
                    raise
                argv = isolation.codex_argv(self.exe.exe, config.CODEX_MODEL, config.CODEX_EFFORT,
                                            prepared['workdir'], self.exe.disable_args)
                env, workdir, stdin = self.launch_env(prepared), prepared['workdir'], inp['stdin_codex']
                problems = self.verify_codex_launch(argv, env, workdir)
                prepared_sha = prepared['auth_sha256']
                base_sha = prepared['baseline_auth_sha256']
                secrets, fingerprints = prepared['secrets'], prepared['secret_fingerprints']
                listing_before = sorted(os.listdir(env['CODEX_HOME']))
                workdir_before = sorted(os.listdir(workdir))
            else:
                workdir = self.run_dir / 'work' / f'slot-{slot}'
                shutil.rmtree(workdir, ignore_errors=True)
                workdir.mkdir(parents=True)
                argv = prompts.sonnet_argv(self.exe.exe, config.SONNET_MODEL, config.SONNET_EFFORT, inp['system'])
                env, stdin = isolation.sonnet_env(self.opts.base_env), inp['body']
                problems = []
                if os.listdir(workdir):
                    problems.append('working directory is not empty')
                found, unreadable = isolation.instruction_scan(workdir)
                if found or unreadable:
                    problems.append(f'instruction files or unreadable locations reachable: '
                                    f'{[str(p) for p in found + unreadable]}')
                if self.exe.exe_sha256 != self.exe.frozen.get('exe_sha256'):
                    problems.append('executable hash differs from the frozen executable hash')
                prepared_sha = base_sha = None
            evidence = {'call_id': call_id, 'cell': spec['id'], 'slot': slot, 'argv_sha256': isolation.argv_sha256(argv),
                        'exe_sha256': self.exe.exe_sha256, 'exe_identity': self.exe.identity,
                        'frozen': {k: v for k, v in self.exe.frozen.items() if k != 'identity'},
                        'env_names': sorted(env), 'workdir': str(workdir), 'problems': problems,
                        'prompt_sha256': prompts.sha256(record), 'stdin_sha256': prompts.sha256(stdin), 'at': _now(),
                        'instruction_sources': [str(p) for p in isolation.instruction_sources(workdir)],
                        'home_listing': listing_before, 'workdir_listing': workdir_before, 'role': self.role,
                        'auth_source': {'store': 'file', 'home': 'worker', 'auth_sha256': prepared_sha}
                        if self.codex else None}
            _write_json(self.run_dir / 'evidence' / 'launch' / f'{call_id}.json', evidence)
            if problems:
                raise Stop(config.EXIT_INCOMPLETE, f'{call_id}: launch verification failed (A4.2): {problems}')
            try:
                charged = self.charge(reason)
            except budget_mod.BudgetExceeded as exc:
                self.say(f'{call_id}: not launched: {exc}')
                if self.codex:
                    self.iso.finish(slot, prepared_sha256=prepared_sha)
                self.slots.release(slot)
                return None
            self.launched += 1
            self.invocation_calls += 1
            n = len(self.prior_attempts()) + 1 + sum(1 for _ in self.dir.glob('inflight/*.json'))
            fail = self.invocation_calls <= self.opts.fake_fail
            refresh = self.codex and self.opts.fake_refresh is not None and \
                self.invocation_calls == self.opts.fake_refresh
            if self.opts.mode == 'fake':
                _write_json(self.exe.fakes['directives'] / f'slot-{slot}.json',
                            {'cell': spec['id'], 'n': n, 'call_id': call_id, 'fail': fail, 'refresh': refresh,
                             'bootstrap_ops': inp['ops'] if bootstrap else None})
            marker = {'call_id': call_id, 'attempt_uid': str(uuid.uuid4()), 'run_id': self.run_uid,
                      'cell': spec['id'], 'backend': self.backend, 'workload': self.workload,
                      'wave': spec['wave'], 'arm': spec['arm'], 'allocation': spec['allocation'], 'batch': key,
                      'try': tries, 'reason': reason, 'kind': charged['kind'], 'slot': slot, 'mode': self.opts.mode,
                      'group': self.current_group, 'marker': 'call', 'role': self.role, 'phase': 'reserved',
                      'prepared_sha': prepared_sha, 'baseline_sha_at_prepare': base_sha,
                      'exe_sha256': self.exe.exe_sha256, 'pid': None,
                      'started_at': _now(), 'job_ids': [j['id'] for j in jobs], 'mapping': inp['mapping'],
                      'ops': inp['ops'], 'secret_fingerprints': fingerprints,
                      'records': {op: sum(1 for j in jobs if j['op'] == op) for op in sorted({j['op'] for j in jobs})},
                      'prompt_sha256': prompts.sha256(record), 'stdin_sha256': prompts.sha256(stdin),
                      'system_sha256': prompts.sha256(inp['system']), 'bootstrap': bootstrap}
            if getattr(self, 'expected', None) and self.spec['arm'] == 'telemetry':
                marker['expected_outcome'] = self.expected
            launch = self.exe.prefix + list(argv) if self.opts.mode == 'fake' else list(argv)
            return {'call_id': call_id, 'batch': key, 'try': tries, 'jobs': jobs, 'inp': inp, 'slot': slot,
                    'launch': launch, 'env': env, 'workdir': workdir, 'stdin': stdin, 'marker': marker,
                    'prepared_sha': prepared_sha, 'bootstrap': bootstrap, 'outcome': None, 'output': None,
                    'role': self.role, 'home_listing_before': listing_before, 'workdir_listing_before': workdir_before,
                    'instruction_sources': evidence['instruction_sources'], 'secrets': secrets, 'record': record,
                    'auth_source': evidence['auth_source']}
        except BaseException:
            if self.codex:
                with contextlib.suppress(Exception):
                    self.iso.finish(slot)
            self.slots.release(slot)
            raise

    def verify_codex_launch(self, argv, env, workdir):
        return isolation.verify_launch(argv=argv, env=env, workdir=workdir, exe_sha256=self.exe.exe_sha256,
                                       frozen=self.exe.frozen)

    def reserve_group(self, group):
        """One durable reservation of a fully staged group before any spawn (council round 2, B2, RT2.3): under the
        experiment lock the shared prerequisites are revalidated (stops, the baseline the members were prepared from,
        token separation, the Codex quota observation), then every member's in-flight marker (phase `reserved`) and
        prompt are written, then (live) its experiment ledger row. A crash after a marker leaves a `reserved` marker,
        which recovery turns into a charged `not_launched` attempt and a ledger row."""
        stop = self.stop_reason()
        if stop:
            raise Stop(stop[0], stop[1])
        if self.codex:
            now = self.iso.baseline_sha256()
            if any(c['marker'].get('baseline_sha_at_prepare') != now for c in group):
                raise Stop(config.EXIT_AUTH_STOP, 'the baseline changed while the launch group was prepared (a reseed '
                                                  'or a propagation); nothing was launched (A4.2)')
            if self.opts.mode == 'live':
                self.separation_gate()
                g = self.codex_quota_gate()
                _append(self.run_dir, 'evidence/quota-gates.jsonl', dict(g, group=self.current_group, at=_now()))
                if not g['ok']:
                    raise Stop(config.EXIT_QUOTA, g['reason'])
        for c in group:
            prompt_path = self.run_dir / 'prompts' / f"{c['call_id']}.txt"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(c['record'], encoding='utf-8')
            _write_json(self.dir / 'inflight' / f"{c['call_id']}.json", c['marker'])
        if self.opts.mode == 'live':
            for c in group:
                m = c['marker']
                _append_file(self.opts.live_ledger, {
                    'attempt_uid': m['attempt_uid'], 'run_id': m['run_id'], 'call_id': m['call_id'],
                    'run_dir': str(self.run_dir.resolve()), 'backend': self.backend, 'workload': self.workload,
                    'allocation': self.spec['allocation'], 'reason': m['reason'], 'kind': m['kind'],
                    'cell': self.spec['id'], 'batch': m['batch'], 'outcome': 'reserved', 'at': _now()})

    def abandon(self, group):
        """Calls staged but never reserved (a later member or a shared prerequisite failed): nothing reached a CLI and
        nothing was written to the experiment ledger, so their markers and prompts go, their in-memory charges are
        dropped with this invocation, and slots and worker homes are released (council round 2, B2, RT2.3)."""
        for c in group:
            with contextlib.suppress(OSError):
                (self.dir / 'inflight' / f"{c['call_id']}.json").unlink()
            with contextlib.suppress(OSError):
                (self.run_dir / 'prompts' / f"{c['call_id']}.txt").unlink()
            if self.codex:
                with contextlib.suppress(Exception):
                    self.iso.finish(c['slot'], prepared_sha256=c['prepared_sha'])
            self.slots.release(c['slot'])

    def _write_marker(self, c):
        _write_json(self.dir / 'inflight' / f"{c['call_id']}.json", c['marker'])

    def _mark_spawned(self, c, pid):
        c['marker'].update(pid=pid, pid_created=process_created(pid), phase='spawned', spawned_at=_now())
        self._write_marker(c)

    def final_check(self, c):
        """The per child check immediately before Popen (items 7 and 3): the executable and its manifest are those
        verified for the group, the worker home holds exactly auth.json and the working directory is empty."""
        problems = list(self.exe.recheck())
        if self.codex:
            home = Path(c['env'].get('CODEX_HOME') or '')
            if not home.is_dir() or sorted(os.listdir(home)) != [isolation.AUTH]:
                problems.append('the worker home no longer holds exactly auth.json')
        if not Path(c['workdir']).is_dir() or os.listdir(c['workdir']):
            problems.append('the working directory is no longer empty')
        return problems

    def execute(self, c):
        _TLS.on_start = lambda pid: self._mark_spawned(c, pid)
        _TLS.raw = tuple(str(p) for p in raw_paths(self.run_dir, c['slot'], c['call_id']))
        try:
            problems = self.final_check(c)
            if problems:
                c['not_launched'] = f'final check before the spawn failed: {problems}'
                return
            try:
                c['marker'].update(phase='spawning', spawning_at=_now())
                self._write_marker(c)
            except Exception as exc:  # noqa: BLE001  (no Popen yet: established not launched)
                c['not_launched'] = f'the spawning marker could not be written: {type(exc).__name__}'
                return
            try:
                c['raw'] = spawn(self.run_dir, c['launch'], c['stdin'], c['env'], c['workdir'],
                                 external=self.opts.mode == 'live')
            except SpawnFailure as exc:
                if exc.terminated:
                    out, err = exc.raw if exc.raw else ('', '')
                    c['raw'] = {'stdout': out, 'stderr': err + f'\n[harness] {exc.reason}', 'exit_code': None,
                                'timed_out': False, 'started_at': c['marker'].get('spawning_at'), 'ended_at': _now(),
                                'elapsed_s': None}
                    c['spawn_failure'] = exc.reason
                else:
                    c['unsettled'] = exc.reason
            except Exception as exc:  # noqa: BLE001  (Popen raised: no process exists)
                c['not_launched'] = f'the child could not be started: {type(exc).__name__}'
        finally:
            _TLS.on_start = None
            _TLS.raw = None

    def secrets(self, c):
        """The credential strings to redact: those prepared for the call (kept in memory since preparation), the
        worker's auth.json now and the baseline now, so a refresh or a reseed never loses an emitted token."""
        if not self.codex:
            return set()
        return set(c.get('secrets') or ()) | redact.secrets_from_auth(
            self.opts.baseline / isolation.AUTH, self.iso.home(c['slot']) / isolation.AUTH,
            c['env'].get('CODEX_HOME') and Path(c['env']['CODEX_HOME']) / isolation.AUTH)

    def after_group(self, group):
        """Judge every call of a finished launch group on its sanitized output, record it, then reconcile
        authentication (A4.2). Per call, in this order (recovery relies on it): sanitize with the prepared and current
        secrets, judge, inventory and harvest the worker home, write the parsed call record, the captures with their
        per channel redaction record, the attempt row, then mark the marker `recorded` and delete the raw stream.
        Slots and markers are released only after the reconciliation. An unsettled child (termination not
        established) keeps its marker, its home and its raw stream, and stops Codex."""
        judged = []
        for c in group:
            if c.get('unsettled'):
                continue
            if c.get('not_launched'):
                row = not_launched_row(c['marker'], c['not_launched'])
                _append(self.run_dir, 'attempts.jsonl', row)
                c['outcome'], c['row'] = 'not_launched', row
                c['output'] = {'outcome': 'not_launched', 'answers': {}, 'job_ids': [j['id'] for j in c['jobs']],
                               'call_id': c['call_id']}
                continue
            raw = dict(c['raw'])
            raw['stdout'], raw['stderr'], c['redaction'] = sanitize(raw.get('stdout'), raw.get('stderr'),
                                                                    self.secrets(c))
            c['raw'] = raw
            judged.append((c,) + tuple((judge_codex if self.codex else judge_sonnet)(raw)))
        replies = [r for _, o, r, *_ in judged if isinstance(r, str)]
        counts = dict(zip(replies, tokenizer.count(replies))) if self.codex and replies else {}
        workers = {}
        for c, outcome, reply, usage_raw, cls, why in judged:
            fin = None
            if self.codex:
                fin = self.iso.finish(c['slot'], auth_failure=outcome == 'auth_failure',
                                      prepared_sha256=c['prepared_sha'])
                c['fin'] = fin
                for obs in fin.get('quota_observations') or []:
                    _append(self.run_dir, 'evidence/quota-observations.jsonl',
                            dict(obs, attempt_uid=c['marker']['attempt_uid'], call_id=c['call_id']))
                if c.get('role') != 'probe':
                    workers[c['slot']] = {'sha256': fin['worker_auth_sha256'], 'prepared': c['prepared_sha'],
                                          'auth_failure': fin['auth_failure'], 'call_id': c['call_id']}
            output = self.interpret(c, outcome, reply)
            outcome = output['outcome']
            acct = account_usage(self.backend, usage_raw, reply, self.cache_certified,
                                 count=lambda texts: [counts.get(t) for t in texts])
            if c.get('spawn_failure'):
                why = (why + '; ' if why else '') + c['spawn_failure']
            _write_json(self.dir / 'calls' / f"{c['call_id']}.json", output)
            write_captures(self.run_dir, c['call_id'], c['raw']['stdout'], c['raw']['stderr'],
                           {'call_id': c['call_id'], 'cell': self.spec['id'], 'redaction': c['redaction'],
                            'attempt_uid': c['marker']['attempt_uid']})
            row = attempt_row(c['marker'], outcome, why, c['raw'], cls, usage_raw, acct, c['redaction'], fin)
            if c['marker'].get('expected_outcome'):
                row['expected_outcome'] = c['marker']['expected_outcome']
            _append(self.run_dir, 'attempts.jsonl', row)
            if self.opts.mode == 'fake':
                rec = _read_json(self.exe.fakes['records'] / f"{c['call_id']}.json")
                if rec is None:
                    rec = {'cell': self.spec['id'], 'n': c['marker'].get('try'), 'cli': self.backend,
                           'argv': c['launch'][1:], 'codex_home': None, 'home_listing': [], 'workdir': None,
                           'workdir_listing': [], 'env_names': [], 'stdin_sha256': prompts.sha256(c['stdin'])}
                _append(self.run_dir, 'fake_calls.jsonl', rec)
            c['marker']['phase'] = 'recorded'
            self._write_marker(c)
            for p in raw_paths(self.run_dir, c['slot'], c['call_id']):
                with contextlib.suppress(OSError):
                    p.unlink()
            c['outcome'], c['output'], c['row'] = outcome, output, row
        failures = [c for c in group if c.get('spawn_failure') or c.get('unsettled')]
        try:
            if self.codex and workers:
                self.reconcile(workers)
            for c in group:
                if c.get('not_launched') and self.codex:
                    with contextlib.suppress(Exception):
                        self.iso.finish(c['slot'], prepared_sha256=c['prepared_sha'])
            # markers go only once the group is reconciled; a runner that dies before keeps them for recovery
            for c in group:
                if c.get('unsettled'):
                    continue
                with contextlib.suppress(OSError):
                    (self.dir / 'inflight' / f"{c['call_id']}.json").unlink()
        finally:
            for c in group:
                self.slots.release(c['slot'])
        for c in failures:
            reason = f"{c['call_id']}: {c.get('unsettled') or c.get('spawn_failure')}"
            if c.get('unsettled'):
                reason += ' (termination of the child not established; its marker, home and raw stream are kept)'
            if self.codex:
                self.codex_stop(reason)
            else:
                self.interrupted = (config.EXIT_INTERRUPTED, reason)
        not_launched = [c for c in group if c.get('not_launched')]
        if not_launched and not self.interrupted:
            why = not_launched[0]['not_launched']
            code = config.EXIT_FREEZE if 'executable' in why else config.EXIT_INCOMPLETE
            self.interrupted = (code, f"{not_launched[0]['call_id']}: not launched: {why}")

    def reconcile(self, workers):
        """A4.2 after every call, failures included: each worker is compared with the baseline generation it was
        prepared from; one changed worker is propagated under the lock against that generation, anything else that
        changed authentication, or any authentication failure, stops Codex evaluation. Probe homes (scrambled
        tokens) never take part: they are never propagated."""
        base = self.iso.baseline_sha256()
        verdict = isolation.reconcile_generations(base, workers)
        row = {'cell': self.spec['id'], 'baseline_auth_sha256': base, 'action': verdict['action'],
               'reason': verdict.get('reason'),
               'workers': {str(s): {'sha256': w['sha256'], 'prepared': w.get('prepared'),
                                    'auth_failure': w['auth_failure']} for s, w in workers.items()},
               'calls': sorted(w['call_id'] for w in workers.values()), 'at': _now()}
        ok = True
        if verdict['action'] == 'propagate':
            try:
                self.iso.propagate(verdict['slot'], expected_baseline_sha256=workers[verdict['slot']]['prepared'])
                if self.opts.mode == 'live':
                    lineage(self.run_dir, self.opts.baseline, 'propagated', slot=verdict['slot'],
                            cell=self.spec['id'])
            except isolation.IsolationError as exc:
                row.update(action='stop_codex', reason=f'propagation refused: {exc}')
                self.codex_stop(f'propagation refused: {exc}')
                ok = False
        elif verdict['action'] == 'stop_codex':
            self.codex_stop(verdict.get('reason', 'authentication reconciliation'))
            ok = False
        _append(self.run_dir, 'evidence/auth-reconcile.jsonl', row)
        return ok

    def codex_stop(self, reason):
        _write_json(self.run_dir / 'codex-stop.json', {'reason': reason, 'cell': self.spec['id'], 'at': _now()})
        self.interrupted = (config.EXIT_AUTH_STOP, 'Codex evaluation stopped (A4.2): ' + reason)

    def interpret(self, c, outcome, reply):
        """The parsed output of one call: answers keyed by job id (and, for a bootstrap, the proposed rules with the
        exact proposal bytes cut from the reply). A bootstrap whose envelope parses but whose answers are malformed or
        incomplete is `malformed_answers`: a completion failure (A4.6); its proposals stay observations."""
        out = {'outcome': outcome, 'answers': {}, 'failed': {}, 'job_ids': [j['id'] for j in c['jobs']],
               'call_id': c['call_id'], 'rejection': None}
        if outcome != 'ok':
            return out
        mapping = c['inp']['mapping']
        if c['bootstrap']:
            try:
                answers_reply, proposed = prompts.parse_bootstrap(reply, c['inp']['ops'])
            except prompts.Malformed as exc:
                out.update(outcome='malformed', rejection='envelope malformed: ' + str(exc)[:200])
                return out
            out['rules'] = proposed
            reply = answers_reply
        answers, failed, rejection = prompts.parse_answers(reply, mapping)
        out.update(answers=answers, failed=failed, rejection=rejection)
        if rejection and not c['bootstrap']:
            out['outcome'] = 'malformed_reply'
        elif c['bootstrap'] and (rejection or len(answers) < len(mapping)):
            out['outcome'] = 'malformed_answers'
        return out

    # ------------------------------------------------------------------------------------------- arms

    def jobs(self):
        return list(workload.jobs_for(self.workload, self.spec['wave']))

    def run_A(self):
        by_p = {p: [j for j in self.jobs() if j['producer'] == p] for p in config.PRODUCERS}
        batches = schedule(by_p, {}, pooled=False)
        results = self.run_batches(batches, 1)
        answers = {}
        for out in results.values():
            for jid, v in (out.get('answers') or {}).items():
                answers[jid] = {'answer': v, 'source': 'model', 'call_id': out.get('call_id')}
        return {'answers': answers, 'batches': {k: v.get('outcome') for k, v in results.items()},
                'scheduled_calls': len(batches)}

    def run_bootstrap(self):
        ids = workload.bootstrap_ids(self.workload)
        by_id = {j['id']: j for j in self.jobs()}
        batch = [by_id[i] for i in ids]
        results = self.run_batches([batch], 1, bootstrap=True)
        out = results.get(self.batch_key(1, 0), {})
        status = {'ok': 'ok', 'malformed': 'malformed', 'malformed_answers': 'malformed',
                  'budget_exhausted': 'missing', 'not_launched': 'missing', 'infrastructure_failure': 'missing',
                  'interrupted': 'missing'}.get(out.get('outcome'), out.get('outcome') or 'missing')
        answers = {jid: {'answer': v, 'source': 'bootstrap', 'call_id': out.get('call_id')}
                   for jid, v in (out.get('answers') or {}).items()}
        rule_doc = {}
        for op, entry in (out.get('rules') or {}).items():
            row = {'proposed': 'none' not in entry, 'ast_sha256': entry.get('ast_sha256'), 'bytes': entry.get('bytes'),
                   'ast_b64': entry.get('ast_b64')}
            if row['proposed']:
                if status != 'ok':
                    row['admission'] = {'status': 'not_evaluated',
                                        'reasons': ['bootstrap completion failure (A4.6): kept as an observation']}
                elif self.workload == 'materials':
                    resp = rules.admit(op, rules.decode(entry))
                    row['admission'] = rules.summary(resp)
                    _write_json(self.dir / 'admission' / f'{op}.json', resp)
                else:
                    row['admission'] = {'status': 'rejected', 'reasons': ['ineligible: BoolQ (A4.6)']}
            rule_doc[op] = row
        return {'answers': answers, 'status': status, 'rules': rule_doc, 'call_outcome': out.get('outcome'),
                'batches': {self.batch_key(1, 0): out.get('outcome')},
                'answers_rejection': out.get('rejection'), 'registry_manifest_sha256': rules.manifest_sha256(),
                'scheduled_calls': 1}

    def admitted_rules(self):
        prefix = f"{self.backend}-{self.workload}"
        boot = _read_json(self.run_dir / 'cells' / f'{prefix}-bootstrap' / 'result.json', {}) or {}
        out = {}
        if self.workload != 'materials' or boot.get('status', 'ok') != 'ok':
            return out, boot
        for op, row in (boot.get('rules') or {}).items():
            if row.get('proposed') and (row.get('admission') or {}).get('status') == 'accepted':
                out[op] = base64.b64decode(row['ast_b64'])
        if self.spec['wave'] == 'warm':
            cold = _read_json(self.run_dir / 'cells' / f'{prefix}-cold-C' / 'result.json', {}) or {}
            status = cold.get('rule_status') or {}
            out = {op: ast for op, ast in out.items() if status.get(op) == 'adopted'}
        return out, boot

    def run_BC(self):
        pooled = self.spec['arm'] == 'C'
        rule_set, boot = self.admitted_rules()
        jobs = self.jobs()
        answers = {}
        boot_ids = set(workload.bootstrap_ids(self.workload)) if self.spec['wave'] == 'cold' else set()
        for jid, a in (boot.get('answers') or {}).items():
            if jid in boot_ids:
                answers[jid] = dict(a)
        rest = [j for j in jobs if j['id'] not in boot_ids]
        covered, fallback = {}, []
        for j in rest:
            if j['op'] in rule_set:
                value, _ = rules.apply(j['op'], rule_set[j['op']], j['text'])
                if value is not None:
                    covered[j['id']] = value
                    continue
            fallback.append(j)
        audit_ids = set()
        if covered:
            import oz_rulephase
            audit_ids = set(oz_rulephase.select_audits(sorted(covered), config.SEED, config.AUDITS))
        by_id = {j['id']: j for j in jobs}
        fb = {p: [j for j in fallback if j['producer'] == p] for p in config.PRODUCERS}
        au = {p: [j for j in rest if j['id'] in audit_ids and j['producer'] == p] for p in config.PRODUCERS}
        batches = schedule(fb, au, pooled=pooled)
        results = self.run_batches(batches, 1)
        model = {}
        for out in results.values():
            for jid, v in (out.get('answers') or {}).items():
                model[jid] = (v, out.get('call_id'))
        audits, quarantined, inconclusive = {}, set(), set()
        for jid in sorted(audit_ids):
            op = by_id[jid]['op']
            if jid not in model:
                audits[jid] = 'inconclusive'
                inconclusive.add(op)
            elif _canon(model[jid][0]) == _canon(covered[jid]):
                audits[jid] = 'agree'
            else:
                audits[jid] = 'disagree'
                quarantined.add(op)
        overflow = [j for j in rest if j['id'] in covered and by_id[j['id']]['op'] in quarantined
                    and j['id'] not in audit_ids]
        results2 = {}
        if overflow and not self.interrupted:
            fb2 = {p: [j for j in overflow if j['producer'] == p] for p in config.PRODUCERS}
            results2 = self.run_batches(schedule(fb2, {}, pooled=pooled), 2, first_reason='audit_overflow')
            for out in results2.values():
                for jid, v in (out.get('answers') or {}).items():
                    model[jid] = (v, out.get('call_id'))
        for j in rest:
            jid = j['id']
            if jid in covered and j['op'] not in quarantined:
                answers[jid] = {'answer': covered[jid], 'source': 'rule', 'call_id': None,
                                'audit': audits.get(jid)}
            elif jid in model:
                answers[jid] = {'answer': model[jid][0], 'source': 'model', 'call_id': model[jid][1],
                                'audit': audits.get(jid)}
        rule_status = {}
        for op in rule_set:
            rule_status[op] = 'quarantined' if op in quarantined else 'inconclusive' if op in inconclusive \
                else 'adopted'
        return {'answers': answers, 'batches': {k: v.get('outcome') for k, v in {**results, **results2}.items()},
                'rules_applied': sorted(rule_set), 'covered': len(covered), 'audits': audits,
                'unresolved_audits': sorted(j for j, v in audits.items() if v == 'inconclusive'),
                'rule_status': rule_status, 'scheduled_calls': len(batches) + len(results2),
                'overflow_jobs': len(overflow)}

    # ------------------------------------------------------------------------------------------- driver

    def run(self) -> int:
        spec, opts = self.spec, self.opts
        problem = mode_problem(opts)
        if problem:
            self.say(f"{spec['id']}: {problem} (no call made)")
            return config.EXIT_USAGE
        self.run_dir.mkdir(parents=True, exist_ok=True)
        try:
            with contextlib.ExitStack() as stack:
                stack.enter_context(exclusive(self.run_dir / 'locks' / f"cell-{spec['id']}.lock"))
                stack.enter_context(exclusive(self.run_dir / 'locks' / 'experiment.lock'))
                if opts.mode == 'live':
                    # one experiment lock beside the authoritative ledger (council round 2, item 9): runners of an
                    # old and a new run directory can never reserve independently
                    stack.enter_context(exclusive(Path(opts.live_ledger).parent / 'experiment.lock'))
                ACTIVE_INVOCATIONS.add(self.invocation)
                try:
                    return self._guarded()
                finally:
                    ACTIVE_INVOCATIONS.discard(self.invocation)
        except Busy as exc:
            self.say(f"{spec['id']}: another runner is active in this run directory ({exc}); no call made")
            return config.EXIT_BUSY

    def _preflight(self):
        """Checks every invocation repeats under the locks before touching state (DONE, SETTLED, requirements)."""
        spec = self.spec
        if (self.dir / 'DONE.json').exists():
            self.say(f"{spec['id']}: already complete; refusing to rerun (no call made)")
            return config.EXIT_ALREADY
        if (self.dir / 'SETTLED.json').exists():
            self.say(f"{spec['id']}: settled incomplete; terminal outcomes are never resent (no call made)")
            return config.EXIT_INCOMPLETE
        missing = [r for r in spec['requires'] if not (self.run_dir / 'cells' / r / 'DONE.json').exists()]
        if missing:
            self.say(f"{spec['id']}: required cells not complete: {missing} (no call made)")
            return config.EXIT_REQUIRES
        return None

    def _guarded(self):
        spec, opts = self.spec, self.opts
        code = self._preflight()
        if code is not None:
            return code
        problem = identity_problem(self.run_dir, opts)
        if problem:
            self.say(f"{spec['id']}: {problem} (no call made)")
            return config.EXIT_IDENTITY
        if opts.mode == 'fake' and opts.default_baseline and not (opts.baseline / isolation.AUTH).exists():
            synthetic_baseline(opts.baseline)
        try:
            recover_inflight(self.run_dir, opts, self.say)
            self.gates()
        except Stop as stop:
            self.say(f"{spec['id']}: {stop.reason}")
            return stop.code
        self.dir.mkdir(parents=True, exist_ok=True)
        for sub in ('prompts', 'captures', 'evidence', 'cells'):
            (self.run_dir / sub).mkdir(parents=True, exist_ok=True)
        self.budget_obj = self.budget()
        self.slots = Slots(self.run_dir)
        try:
            self.exe = Executables(opts, self.backend)
        except RuntimeError as exc:
            self.say(f"{spec['id']}: {exc}")
            return config.EXIT_INCOMPLETE
        self.cache_certified = usage.cache_certified_for_route() if self.codex else None
        if self.codex:
            self.iso = isolation.Isolation(opts.baseline, self.run_dir, self.run_dir / 'evidence',
                                           frozen_inventory=isolation.load_inventory(), base_env=opts.base_env,
                                           owner_auth=self.owner_auth())
        bound = bind_identity(self.run_dir, opts, self.iso.baseline_sha256() if self.iso else None)
        self.run_uid = (bound or {}).get('run_id')
        if self.codex and opts.mode == 'live' and not (self.run_dir / 'evidence' / 'auth-lineage.jsonl').exists():
            lineage(self.run_dir, opts.baseline, 'first_dispatch', cell=spec['id'])
        if self.codex and opts.mode == 'live' and spec['arm'] != 'telemetry':
            try:
                self.record_features()
            except Stop as stop:
                self.say(f"{spec['id']}: {stop.reason}")
                return stop.code
            if self.interrupted:
                self.say(f"{spec['id']}: {self.interrupted[1]}")
                return self.interrupted[0]
        doc = _read_json(self.dir / 'state.json', {}) or {}
        invocations = doc.get('invocations', []) + [{'mode': opts.mode, 'started_at': _now(), 'pid': os.getpid(),
                                                     'invocation': self.invocation,
                                                     'claude_weekly_percent': opts.claude_percent}]
        self.state('running', invocations=invocations, spec=spec)
        if opts.mode == 'live':
            _append(self.run_dir, 'evidence/quota.jsonl', {
                'cell': spec['id'], 'claude_weekly_percent': opts.claude_percent,
                'codex_primary_used_percent': quota.codex_primary_used_percent(opts.sessions_dir)
                if self.codex else None, 'codex_reading_at': str(quota.codex_reading_time(opts.sessions_dir))
                if self.codex else None, 'at': _now()})
        return self._run_locked(spec, opts)

    def _window_open(self):
        """Durably open this invocation's timing window before any work (council round 2, item 14)."""
        self._t0, self._started = time.monotonic(), _now()
        _append(self.run_dir, f"cells/{self.spec['id']}/windows.jsonl",
                {'event': 'open', 'invocation': self.invocation, 'started_at': self._started, 'pid': os.getpid()})

    def _window(self, ended_how):
        """Close the work window after the result delivery boundary (result.json and DONE or SETTLED written): real
        submission to resolution time of this invocation's work on the cell, local work (preparation, parsing,
        admission, rule execution, audits, delivery) and launch skew included (item 14)."""
        row = {'event': 'close', 'invocation': self.invocation, 'started_at': self._started, 'ended_at': _now(),
               'elapsed_s': round(time.monotonic() - self._t0, 3), 'calls': self.invocation_calls,
               'ended': ended_how}
        _append(self.run_dir, f"cells/{self.spec['id']}/windows.jsonl", row)
        return row

    def rule_errors(self, result):
        jobs = {j['id']: j for j in self.jobs()} if self.workload in ('materials', 'boolq') else {}
        errors = []
        for jid, row in (result.get('answers') or {}).items():
            if row.get('source') == 'rule' and jid in jobs and _canon(row['answer']) != _canon(workload.gold(jobs[jid])):
                errors.append(jid)
        return sorted(errors)

    def arm(self):
        if self.spec['arm'] == 'A':
            return self.run_A()
        if self.spec['arm'] == 'bootstrap':
            return self.run_bootstrap()
        return self.run_BC()

    def _run_locked(self, spec, opts):
        self._window_open()
        try:
            result = self.arm()
        except Stop as stop:
            self.state('incomplete', reason=stop.reason)
            self._window('stopped')
            self.say(f"{spec['id']}: {stop.reason}")
            return stop.code
        result.update(cell=spec['id'], spec=spec, mode=opts.mode)
        exhausted = [k for k, v in result.get('batches', {}).items() if v in ('budget_exhausted',)]
        killed = self.rule_errors(result)
        _write_json(self.dir / 'result.json', result)
        if killed:
            _write_json(self.run_dir / 'safety-kill.json', {'cell': spec['id'], 'rule_errors': len(killed),
                                                            'jobs': killed[:20], 'at': _now()})
        code = self._settle(spec, opts, result, exhausted, killed)
        self._window('returned')
        return code

    def _settle(self, spec, opts, result, exhausted, killed):
        if self.interrupted:
            code, reason = self.interrupted
            self.state('interrupted', reason=reason)
            self.say(f"{spec['id']}: interrupted: {reason}")
            return code
        if exhausted:
            self.state('incomplete', reason=f'allocation and reserve exhausted for batches {exhausted}')
            self.say(f"{spec['id']}: incomplete: allocation and reserve exhausted ({exhausted})")
            return config.EXIT_INCOMPLETE
        physical = len(self.prior_attempts())
        bad = {k: v for k, v in result.get('batches', {}).items() if v != 'ok'}
        if spec['arm'] == 'bootstrap' and result.get('status') != 'ok':
            bad.setdefault('bootstrap', result.get('status'))
        if bad:
            _write_json(self.dir / 'SETTLED.json', {'cell': spec['id'], 'settled_at': _now(), 'physical_calls': physical,
                                                    'terminal_outcomes': bad})
            self.state('incomplete', settled=True, reason=f'terminal unsuccessful outcomes {bad}; never resent')
            self.say(f"{spec['id']}: settled incomplete: {bad}")
            return config.EXIT_INCOMPLETE
        _write_json(self.dir / 'DONE.json', {'cell': spec['id'], 'completed_at': _now(), 'physical_calls': physical,
                                             'mode': opts.mode})
        self.state('complete', physical_calls=physical)
        self.say(f"{spec['id']}: complete ({physical} physical calls)")
        if killed:
            self.say(f"{spec['id']}: safety kill: {len(killed)} accepted incorrect rule answers (A4.11)")
            return config.EXIT_SAFETY_KILL
        return config.EXIT_OK

    # ------------------------------------------------------------------------------------------- probes

    def probe_marker(self, name, slot, prepared_sha):
        marker = {'call_id': f'probe-{name}-{self.invocation}', 'cell': self.spec['id'], 'backend': 'codex',
                  'marker': 'probe', 'role': 'probe', 'slot': slot, 'prepared_sha': prepared_sha, 'pid': None,
                  'mode': self.opts.mode, 'started_at': _now()}
        path = self.dir / 'inflight' / f"{marker['call_id']}.json"
        _write_json(path, marker)

        def on_start(pid):
            marker.update(pid=pid, pid_created=process_created(pid), phase='spawned')
            _write_json(path, marker)
        return marker, path, on_start

    def worker_probe(self, name, args):
        """A local CLI command (no model request) with a reconstructed worker home, owning its slot, recorded by an
        in-flight marker and reconciled like a call (council C2). Its output is redacted with the secrets prepared
        for it, and its error channels are inspected BEFORE reconciliation: an authentication failure is sticky, stops
        Codex and is never propagated (council round 2, items 5 and 6). Returns (exit code, stdout, stderr, finish)."""
        slot = self.slots.acquire()
        try:
            try:
                prepared = self.iso.prepare(slot)
            except isolation.IsolationError as exc:
                raise Stop(config.EXIT_AUTH_GATE if 'token separation' in str(exc) else config.EXIT_INCOMPLETE,
                           f'{name} probe: {exc}') from None
            marker, path, on_start = self.probe_marker(name, slot, prepared['auth_sha256'])
            problems = self.exe.verify()
            if problems:
                raise Stop(config.EXIT_FREEZE, f'executable verification before {name} failed: {problems}')
            secrets = set(prepared['secrets'])
            try:
                code, out, err = run_local([self.exe.exe, *config.ROUTE_SECURITY_ARGS, *self.exe.disable_args, *args]
                                           if name == 'features' else [self.exe.exe, *config.ROUTE_SECURITY_ARGS[:2],
                                                                       *args],
                                           prepared['env'], prepared['workdir'], on_start)
            finally:
                secrets |= redact.secrets_from_auth(self.iso.home(slot) / isolation.AUTH,
                                                    self.opts.baseline / isolation.AUTH)
                fin = None
            out, r1 = redact.redact(out, secrets)
            err, r2 = redact.redact(err, secrets)
            failure = auth_failure_detected(out, err)
            if name == 'login' and login_state(out + '\n' + err) != 'logged_in':
                failure = True
            fin = self.iso.finish(slot, auth_failure=failure, prepared_sha256=prepared['auth_sha256'])
            self.reconcile({slot: {'sha256': fin['worker_auth_sha256'], 'prepared': prepared['auth_sha256'],
                                   'auth_failure': failure, 'call_id': marker['call_id']}})
            if r1.get('redactions') or r2.get('redactions'):
                _append(self.run_dir, 'evidence/probe-disclosures.jsonl',
                        {'probe': name, 'cell': self.spec['id'], 'redaction': redact.merge(r1, r2), 'at': _now()})
            with contextlib.suppress(OSError):
                path.unlink()
            return code, out, err, fin
        finally:
            self.slots.release(slot)

    def record_features(self):
        """A4.2: before each wave, the effective features from `codex features list` with a reconstructed worker
        home and the frozen disable options (a local command; no model request). Council round 2 (item 5, C3): the
        command must succeed and give a structurally valid inventory (one row per feature, no duplicate, a boolean
        state), every frozen disable option must be listed and off except the recorded `stays_enabled` features,
        skip_host_skill_discovery must be on, and no authentication failure may appear; otherwise the cell is refused
        before any charged call."""
        code, out, err, fin = self.worker_probe('features', ['features', 'list'])
        rows, problems, dup = {}, [], []
        for line in out.splitlines():
            parts = line.split()
            if not parts:
                continue
            if len(parts) < 3 or parts[-1] not in ('true', 'false'):
                problems.append(f'unparseable features line: {line[:80]!r}')
                continue
            if parts[0] in rows:
                dup.append(parts[0])
            rows[parts[0]] = parts[-1] == 'true'
        expected_on = set((_read_json(config.CLI_FLAGS_FILE, {}) or {}).get('stays_enabled') or {})
        if code != 0:
            problems.append(f'features list exited {code}')
        if not rows:
            problems.append('features list gave no feature inventory')
        if dup:
            problems.append(f'duplicate feature names: {sorted(set(dup))[:5]}')
        flags = self.exe.disable_args
        disabled = [flags[i + 1] for i in range(len(flags) - 1) if flags[i] == '--disable']
        missing = sorted(n for n in disabled if n not in rows)
        if rows and missing:
            problems.append(f'disabled features missing from the inventory: {missing[:5]}')
        enabled = sorted(k for k in disabled if rows.get(k))
        if sorted(set(enabled) - expected_on):
            extra = sorted(set(enabled) - expected_on)
            problems.append(f'features still enabled beyond the frozen expectation: {extra}')
        if rows and rows.get('skip_host_skill_discovery') is not True:
            problems.append('skip_host_skill_discovery is not enabled')
        if auth_failure_detected(out, err):
            problems.append('features list reported an authentication failure')
        argv = [*config.ROUTE_SECURITY_ARGS, *self.exe.disable_args, 'features', 'list']
        _write_json(self.run_dir / 'evidence' / f"features-{self.spec['id']}.json",
                    {'cell': self.spec['id'], 'argv_sha256': hashlib.sha256(json.dumps(argv).encode()).hexdigest(),
                     'exit_code': code, 'features': rows, 'enabled_tool_features': enabled, 'ok': not problems,
                     'problems': problems, 'runtime_files': fin['runtime_files'], 'at': _now()})
        if problems:
            raise Stop(config.EXIT_FREEZE, f'features record invalid before any charged call (A4.2): {problems[:5]}')


def _canon(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


# ================================================================================================ telemetry

def telemetry_failures(run_dir):
    """Every telemetry attempt that did not end as expected and every telemetry record that did not pass."""
    run_dir = Path(run_dir)
    problems = []
    for a in jsonl(run_dir / 'attempts.jsonl'):
        if a.get('cell') == 'telemetry' and a.get('outcome') != a.get('expected_outcome'):
            problems.append(f"telemetry attempt {a.get('call_id')} ended {a.get('outcome')!r}, expected "
                            f"{a.get('expected_outcome')!r}")
    for r in jsonl(run_dir / 'evidence' / 'telemetry.jsonl'):
        if not r.get('passed'):
            problems.append(f"telemetry record at {r.get('at')} failed: {(r.get('problems') or [])[:3]}")
    return problems


def telemetry_problems(run_dir):
    """Why live Codex cells may not launch on this run directory's telemetry (A4.2, B4): every telemetry attempt
    must have ended as expected, every telemetry record must have passed, and the latest must satisfy the full
    certificate. One failure stops evaluation in this run directory for good."""
    run_dir = Path(run_dir)
    rows = jsonl(run_dir / 'evidence' / 'telemetry.jsonl')
    problems = telemetry_failures(run_dir)
    if problems:
        return problems + ['a telemetry failure stops evaluation in this run directory; going further needs a new run '
                           'directory and a recorded council disposition']
    if not rows:
        return ['no telemetry certificate in this run directory (run `telemetry --mode live` first)']
    return isolation.telemetry_certificate(rows[-1].get('certificate'))


class TelemetryRun(CellRun):
    """The A4.2 telemetry certificate, through the same reservation, isolation, capture, reconciliation and stop
    machinery as evaluation calls (council rounds 1 and 2, items 1, 4, 33, B1, B4), on its own telemetry allocation:

    1. `login status` at each of the four worker paths, emptied (local, no model request): must say not logged in,
       so no credential is keyed by a worker path.
    2. `login status` with a reconstructed worker home (local): must say logged in.
    3. the frozen exec argv at a worker path whose auth.json keeps the baseline's account metadata but carries
       tokens no server accepts (a charged telemetry call): must end in an authentication failure without a reply or
       usage, so no credential store keyed by account data from auth.json supplies credentials. Its startup runtime
       inventory (names and hashes) is the local preflight of the next step.
    4. preflight: when that inventory holds an instruction bearing file the approved startup manifest does not list by
       path and hash (P5), the telemetry refuses before the charged worker call.
    5. the frozen exec argv with a reconstructed worker home on a neutral one job packet (a charged telemetry call):
       must deliver a plain reply; its runtime files are inventoried by name and hash.
    6. `login status` at the four emptied worker paths again: the call left no credential keyed by a worker path.
    The certificate is published (evidence/telemetry.jsonl, telemetry.json) only after the call was reconciled."""

    def __init__(self, opts):
        CellRun.__init__(self, dict(TELEMETRY_SPEC), opts)
        self.expected = 'ok'
        self.last_call = {}
        self.last_fin = None
        self.probe_fin = None
        self.reconciled_all = True
        self.scrambled_probe = True

    def _preflight(self):
        if self.opts.mode != 'live':
            self.say('telemetry runs live only; fake mode cannot establish properties of the real CLI')
            return config.EXIT_USAGE
        return None

    def model_input(self, jobs, bootstrap):
        body = json.dumps({'v': '1g', 'goal': 'Telemetry check.', 'ops': ['Return the JSON string ok.'],
                           'refs': ['x'], 'jobs': [[0, ['j00', 0]]]}, separators=(',', ':'))
        return {'system': prompts.SYSTEM, 'body': body, 'stdin_codex': prompts.SYSTEM + '\n\n' + body,
                'mapping': {'j00': 'telemetry-j00'}, 'ops': None}

    def charge(self, reason):
        return self.budget_obj.charge('codex', 'telemetry', 'telemetry', reason='nominal', outcome='launched')

    def interpret(self, c, outcome, reply):
        out = CellRun.interpret(self, c, outcome, reply)
        out['outcome'] = outcome
        return out

    def worker_path_logins(self):
        """`login status` at every worker path with the path emptied (B4), each under its own slot, so no child uses
        the directory; the directory is emptied again afterwards. Local commands, no model request."""
        out = {}
        problems = self.exe.verify()
        if problems:
            raise Stop(config.EXIT_FREEZE, f'executable verification failed: {problems}')
        for k in range(config.SLOTS):
            slot = self.slots.acquire(only=k)
            try:
                home = self.iso.empty_home(k)
                code, o, e = run_local([self.exe.exe, *config.ROUTE_SECURITY_ARGS[:2], 'login', 'status'],
                                       isolation.child_env(home, self.opts.base_env), self.run_dir)
                out[str(k)] = login_state(o + '\n' + e)
                self.iso.empty_home(k)
            finally:
                self.slots.release(slot)
        return out

    def arm(self):
        doc = {'schema': 'ozmap-rep.telemetry/3', 'at': _now(), 'login_status': {}, 'problems': []}
        doc['login_status']['worker_paths_before'] = self.worker_path_logins()
        code, out, err, _ = self.worker_probe('login', ['login', 'status'])
        doc['login_status']['worker_home'] = login_state(out + '\n' + err)
        self.role, self.expected = 'probe', 'auth_failure'
        probe = self.run_batches([[{'id': 'telemetry-j00', 'op': 'telemetry'}]], 1)
        probe_out = probe.get(self.batch_key(1, 0), {})
        probe_row = next((a for a in reversed(self.prior_attempts()) if a.get('batch') == self.batch_key(1, 0)), {})
        pfin = self.probe_fin or {}
        doc['exec_probe'] = {'outcome': probe_out.get('outcome'), 'call_id': probe_row.get('call_id'),
                             'reply': bool(probe_out.get('answers')),
                             'usage_present': probe_row.get('usage_raw') is not None, 'home': 'worker',
                             'account_metadata_kept': True, 'runtime_files': pfin.get('runtime_files'),
                             'runtime_hashes': pfin.get('runtime_hashes'),
                             'auth_rewritten': pfin.get('auth_changed')}
        startup = isolation.startup_instruction_files(pfin.get('runtime_files') or [], pfin.get('runtime_hashes'))
        if probe_out.get('outcome') != 'auth_failure':
            doc['problems'].append('the exec probe with unaccepted tokens did not end in an authentication failure; '
                                   'the telemetry call was not made')
        elif startup:
            doc['problems'].append(f'preflight: the startup inventory of the frozen argv holds instruction bearing '
                                   f'files the approved startup manifest does not list: {startup[:10]}; the charged '
                                   f'telemetry call was not made (B1, P5)')
        elif not self.interrupted:
            self.role, self.expected = 'call', 'ok'
            call = self.run_batches([[{'id': 'telemetry-j00', 'op': 'telemetry'}]], 2)
            call_out = call.get(self.batch_key(2, 0), {})
            row = next((a for a in reversed(self.prior_attempts()) if a.get('batch') == self.batch_key(2, 0)), {})
            fin = self.last_fin or {}
            doc['call'] = {'call_id': row.get('call_id'), 'outcome': call_out.get('outcome'),
                           'stream_verdict': (row.get('events') or {}).get('verdict'),
                           'home_listing_before': self.last_call.get('home_listing_before'),
                           'workdir_listing_before': self.last_call.get('workdir_listing_before'),
                           'instruction_sources': self.last_call.get('instruction_sources'),
                           'auth_source': self.last_call.get('auth_source'),
                           'argv_sha256': (_read_json(self.run_dir / 'evidence' / 'launch' /
                                                      f"{row.get('call_id')}.json", {}) or {}).get('argv_sha256'),
                           'runtime_files': fin.get('runtime_files'), 'runtime_hashes': fin.get('runtime_hashes'),
                           'usage_status': row.get('usage_status'), 'auth_changed': fin.get('auth_changed')}
            doc['login_status']['worker_paths_after'] = self.worker_path_logins()
        doc['reconciled'] = not (self.run_dir / 'codex-stop.json').exists() and self.reconciled_all
        clean = doc.get('call') or {}
        befores = doc['login_status'].get('worker_paths_before') or {}
        doc['auth_read_from_codex_home'] = (bool(befores) and all(v == 'not_logged_in' for v in befores.values())
                                            and doc['login_status'].get('worker_home') == 'logged_in'
                                            and doc['exec_probe']['outcome'] == 'auth_failure')
        doc['sandbox_clean_home'] = (clean.get('home_listing_before') == [isolation.AUTH]
                                     and clean.get('stream_verdict') == 'plain' and clean.get('outcome') == 'ok')
        doc['problems'] += isolation.telemetry_certificate(doc)
        passed = not doc['problems'] and not self.interrupted
        record = {'at': doc['at'], 'passed': passed, 'problems': doc['problems'], 'certificate': doc}
        _append(self.run_dir, 'evidence/telemetry.jsonl', record)
        _write_json(self.run_dir / 'evidence' / 'telemetry.json', doc)
        self.say(json.dumps({'telemetry': passed, 'problems': doc['problems']}))
        return {'answers': {}, 'batches': {}, 'telemetry': passed, 'scheduled_calls': 2}

    def prepare_call(self, key, jobs, tries, reason, bootstrap):
        c = CellRun.prepare_call(self, key, jobs, tries, reason, bootstrap)
        if c is not None:
            c['expected_outcome'] = self.expected
            self.last_call = c
        return c

    def reconcile(self, workers):
        ok = CellRun.reconcile(self, workers)
        self.reconciled_all = self.reconciled_all and ok
        return ok

    def after_group(self, group):
        CellRun.after_group(self, group)
        for c in group:
            if c.get('role') == 'call':
                self.last_fin = c.get('fin')
            elif c.get('role') == 'probe':
                self.probe_fin = c.get('fin')

    def _run_locked(self, spec, opts):
        failures = telemetry_failures(self.run_dir)
        if failures:
            self.say(f'telemetry refused: {failures[:3]}')
            return config.EXIT_TELEMETRY
        if not telemetry_problems(self.run_dir):
            self.say('telemetry already certified for this run directory (no call made)')
            return config.EXIT_ALREADY
        try:
            result = self.arm()
        except Stop as stop:
            self.say(f'telemetry: {stop.reason}')
            _append(self.run_dir, 'evidence/telemetry.jsonl', {'at': _now(), 'passed': False,
                                                               'problems': [stop.reason], 'certificate': None})
            return stop.code
        if self.interrupted:
            return self.interrupted[0]
        return config.EXIT_OK if result['telemetry'] else config.EXIT_TELEMETRY


def telemetry(opts) -> int:
    return TelemetryRun(opts).run()


def features(opts) -> int:
    """Record `codex features list` with a reconstructed worker home (live only), under the same locks."""
    if opts.mode != 'live':
        print('features records the real CLI; use --mode live', file=sys.stderr)
        return config.EXIT_USAGE
    run = TelemetryRun(opts)
    run.spec = dict(TELEMETRY_SPEC, id='features')
    run.dir = run.run_dir / 'cells' / 'features'

    def arm():
        run.record_features()
        return {'answers': {}, 'batches': {}, 'telemetry': True}
    def locked(spec, o):
        try:
            arm()
        except Stop as stop:
            run.say(f'features: {stop.reason}')
            return stop.code
        return config.EXIT_OK
    run.arm = arm
    run._run_locked = locked
    return run.run()


# ================================================================================================ freeze

FREEZE_GLOBS = ('bench/ozmap_rep/*.py', 'bench/ozmap_rep/*.json', 'bench/ozmap_rep/certificate/*.json',
                'bench/ozmap_rep/ops/*.py', 'bench/ozmap_rep/ops/ops.md', 'bench/ozmap_rep/acceptance/*.py',
                'bench/ozmap_rep/acceptance/INTERFACE.md', 'bench/ozmap_rep/tests/*.py',
                'bench/ozmap_rep/tests/fixtures/*', 'bench/ozmap_rep/redteam/*.py')
FREEZE_FILES = ('oz_rule.py', 'oz_registry.py', 'oz_batch.py', 'oz_reply.py', 'oz_rulephase.py', 'oz.py',
                'examples/bootstrap_shim.py', 'examples/claude_map_adapter.py', 'examples/claude_cli_adapter.py',
                'examples/codex_cli_adapter.py', 'docs/design/ozmap-2026-10-24/bootstrap-spec-excerpt.txt',
                'bench/ozmap/pilot.py', 'bench/ozmap/data.py', 'bench/ozmap/data/boolq-superglue-val.jsonl',
                'docs/design/ozmap-replication-2026-10-24/amendment-4.md',
                'docs/design/ozmap-replication-2026-10-24/amendment-4-13-caps.md',
                'docs/design/ozmap-replication-2026-10-24/expressibility-review.md')


def _freeze_files():
    names = set(FREEZE_FILES)
    for pattern in FREEZE_GLOBS:
        names |= {p.relative_to(config.REPO).as_posix() for p in config.REPO.glob(pattern) if p.is_file()}
    cert = _read_json(config.CERTIFICATE_FILE, {}) or {}
    names |= {s['envelope'] for s in cert.get('sources') or [] if isinstance(s, dict) and s.get('envelope')}
    names.discard('bench/ozmap_rep/freeze.json')
    return sorted(names)


def freeze_record(base_env=None):
    env = dict(os.environ if base_env is None else base_env)
    files = {}
    for rel in _freeze_files():
        data = (config.REPO / rel).read_bytes()
        if rel.endswith(('.py', '.md', '.json', '.txt')):
            data = data.replace(b'\r\n', b'\n')
        files[rel] = hashlib.sha256(data).hexdigest()
    disable, unsupported = cli_flags()
    out = {'schema': 'ozmap-rep.freeze/2', 'files': files, 'registry_manifest_sha256': rules.manifest_sha256(),
           'disable_options': disable, 'unsupported_options': unsupported, 'tokenizer': tokenizer.record(),
           'workload_sha256': hashlib.sha256(json.dumps(workload.materials(), sort_keys=True).encode()).hexdigest(),
           'classification_sha256': isolation.sha256_file(config.CLASSIFICATION_FILE),
           'interpreter': sys.executable, 'live_run_dir': str(live_run_dir()),
           'signed_exceptions': {'transport_notices': list(config.SIGNED_TRANSPORT_NOTICES),
                                 'omitted_disables': dict(config.SIGNED_OMITTED_DISABLES),
                                 'cli_notices': list(config.SIGNED_CLI_NOTICES),
                                 'cli_notice_event_keys': config.SIGNED_CLI_NOTICE_EVENT_KEYS and
                                 sorted(config.SIGNED_CLI_NOTICE_EVENT_KEYS),
                                 'cli_notice_id_re': config.SIGNED_CLI_NOTICE_ID_RE,
                                 'startup_manifest_sha256': isolation.sha256_file(config.STARTUP_MANIFEST_FILE)
                                 if config.STARTUP_MANIFEST_FILE.exists() else None,
                                 'rulings': rulings.record()},
           'route_security_args': list(config.ROUTE_SECURITY_ARGS)}
    for name, backend in (('codex', 'codex'), ('claude', 'sonnet')):
        exe = shutil.which(name, path=env.get('PATH'))
        if exe:
            exe = str(Path(exe).resolve())
            version = subprocess.run([exe, '--version'], capture_output=True, text=True, encoding='utf-8',
                                     errors='replace', timeout=60).stdout.strip()[:200]
            ident = isolation.executable_identity(exe)
            out[backend] = {'exe': exe, 'exe_sha256': ident['sha256'], 'identity': ident, 'version': version}
    if 'codex' in out:
        argv = isolation.codex_argv(out['codex']['exe'], config.CODEX_MODEL, config.CODEX_EFFORT, 'slot-0', disable)
        out['codex']['argv_sha256'] = isolation.argv_sha256(argv)
    return out


def verify_freeze():
    frozen = _read_json(config.FREEZE_FILE)
    if not frozen:
        return ['bench/ozmap_rep/freeze.json is missing (run `python -m bench.ozmap_rep.run freeze` after sign-off)']
    now = freeze_record()
    problems = [f'{k} changed' for k in sorted(set(frozen.get('files', {})) | set(now['files']))
                if frozen.get('files', {}).get(k) != now['files'].get(k)]
    for key in ('registry_manifest_sha256', 'disable_options', 'workload_sha256', 'classification_sha256',
                'tokenizer', 'interpreter', 'live_run_dir', 'signed_exceptions', 'route_security_args'):
        if frozen.get(key) != now.get(key):
            problems.append(f'{key} changed')
    if (frozen.get('codex') or {}).get('version') != config.CODEX_CLI_VERSION:
        problems.append('the frozen Codex CLI is not codex-cli 0.160.0')
    if (now.get('codex') or {}).get('version') != config.CODEX_CLI_VERSION:
        problems.append('the Codex CLI found now is not codex-cli 0.160.0')
    for backend in ('codex', 'sonnet'):
        f, n = frozen.get(backend) or {}, now.get(backend) or {}
        if f.get('exe_sha256') != n.get('exe_sha256'):
            problems.append(f'{backend} executable changed')
        if (f.get('identity') or {}).get('payload') != (n.get('identity') or {}).get('payload'):
            problems.append(f'{backend} launcher payload changed')
        if f.get('version') != n.get('version'):
            problems.append(f'{backend} version changed')
        if isolation.identity_problems(n.get('identity') or {}, f.get('identity') or {}) and n.get('identity'):
            problems.append(f'{backend} executable identity (companion manifest or launcher targets) changed')
    if frozen.get('disposition'):
        d = Path(frozen['disposition'])
        if not d.is_file() or isolation.sha256_file(d) != frozen.get('disposition_sha256'):
            problems.append('the recorded disposition changed or is missing since the freeze')
    tok = now.get('tokenizer') or {}
    if not tok.get('vocabulary_ok'):
        problems.append('the pinned tokenizer vocabulary is unavailable')
    problems += [f'freeze readiness: {p}' for p in rulings.readiness_problems(now.get('disable_options'))]
    return problems


def freeze_command(new_run_dir=None, disposition=None):
    """Write freeze.json. Refused (exit 14) while a pending ruling slot is unsettled or the configuration does not
    match the rulings (council round 2, B1: a freeze and a telemetry run certain to fail would spend telemetry calls
    and block the run directory for good). Refused once a live run is bound to the current freeze (A4.1: the freeze
    cannot be replaced after dispatch), unless a new, unused live run directory and a recorded council disposition
    are named; the disposition is hashed into the freeze."""
    ready = rulings.readiness_problems()
    if ready:
        print('refused: the freeze is not ready (B1): ' + '; '.join(ready), file=sys.stderr)
        return config.EXIT_FREEZE
    target = live_run_dir()
    bound = (target / 'experiment.json').exists() or bool(jsonl(config.LIVE_LEDGER_DEFAULT))
    if bound:
        if not new_run_dir or not disposition or not Path(disposition).is_file():
            print(f'refused: a live run is bound to the current freeze ({target}); a new freeze needs '
                  f'--new-run-dir <unused dir> and --disposition <recorded council disposition>', file=sys.stderr)
            return config.EXIT_FREEZE
        if Path(new_run_dir).exists() and any(Path(new_run_dir).iterdir()):
            print(f'refused: {new_run_dir} is not an unused directory', file=sys.stderr)
            return config.EXIT_FREEZE
    rec = freeze_record()
    if new_run_dir:
        rec['live_run_dir'] = str(Path(new_run_dir).resolve())
        rec['disposition'] = str(disposition)
        rec['disposition_sha256'] = isolation.sha256_file(disposition)
    _write_json(config.FREEZE_FILE, rec)
    print(f'wrote {config.FREEZE_FILE} ({len(rec["files"])} files)')
    return 0


# ================================================================================================ dry

def synthetic_baseline(directory):
    """An authentication only baseline whose access token (an unsigned JWT with no secret) is valid 30 days."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    exp = int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)).timestamp())
    b64 = lambda d: base64.urlsafe_b64encode(d).rstrip(b'=').decode()  # noqa: E731
    token = '.'.join([b64(b'{"alg":"none"}'), b64(json.dumps({'exp': exp, 'synthetic': True}).encode()), b64(b'x')])
    doc = {'auth_mode': 'chatgpt', 'tokens': {'id_token': 'synthetic', 'access_token': token,
                                              'refresh_token': 'synthetic'},
           'last_refresh': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    (directory / 'auth.json').write_text(json.dumps(doc), encoding='utf-8')
    return directory


def snapshot_preparation(run_dir):
    led = budget_mod.PrepLedger(config.LEDGER_FILE)
    _write_json(Path(run_dir) / 'preparation.json', {'counts': led.counts(), 'caps': config.PREP_CAPS,
                                                     'global_cap': config.GLOBAL_CAP, 'at': _now(),
                                                     'ledger': 'docs/design/ozmap-replication-2026-10-24/call-ledger.jsonl'})


def dry(run_dir, base_env=None, out=None) -> int:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = out or sys.stderr
    baseline = run_dir / 'auth' / 'baseline'
    if not (baseline / 'auth.json').exists():
        synthetic_baseline(baseline)
    if not (run_dir / 'preparation.json').exists():
        snapshot_preparation(run_dir)
    codes = {}
    for spec in cell_specs():
        opts = Options(run_dir, mode='fake', baseline=baseline, base_env=base_env, out=out)
        codes[spec['id']] = CellRun(spec, opts).run()
    from . import score
    score.score_run(run_dir, write=True)
    attempts = jsonl(run_dir / 'attempts.jsonl')
    cells, capacity = {}, {}
    for spec in cell_specs():
        st = _read_json(run_dir / 'cells' / spec['id'] / 'state.json', {}) or {}
        physical = sum(1 for a in attempts if a.get('cell') == spec['id'])
        cells[spec['id']] = {'state': st.get('state'), 'physical_calls': physical, 'exit_code': codes[spec['id']]}
        if spec['arm'] != 'bootstrap':
            res = _read_json(run_dir / 'cells' / spec['id'] / 'result.json', {}) or {}
            scheduled = max(physical, res.get('scheduled_calls') or 0, worst_case_calls(spec))
            capacity[spec['id']] = {'scheduled_calls': scheduled, 'bound': spec['nominal_calls'],
                                    'run_calls': physical, 'worst_case_zero_rules_worst_audits':
                                        worst_case_calls(spec)}
    spawns = jsonl(run_dir / 'spawns.jsonl')
    resolved = [r for r in jsonl(run_dir / 'resolved.jsonl')]
    report = {'external_calls': sum(1 for s in spawns if s.get('external')),
              'fake_calls': len(jsonl(run_dir / 'fake_calls.jsonl')), 'cells': cells, 'capacity': capacity,
              'real_cli_resolved': [r['name'] for r in resolved if r.get('path')], 'zero_rules': True,
              'mode': 'simulation (fake executables; never evidence)',
              'within_bounds': all(c['scheduled_calls'] <= c['bound'] for c in capacity.values())}
    _write_json(run_dir / 'dry_report.json', report)
    ok = (report['external_calls'] == 0 and not report['real_cli_resolved'] and report['within_bounds']
          and all(c['state'] == 'complete' for c in cells.values()))
    out.write(f"dry: {report['fake_calls']} fake calls, {report['external_calls']} external calls, "
              f"{sum(1 for c in cells.values() if c['state'] == 'complete')}/16 cells complete\n")
    return 0 if ok else 1


# ================================================================================================ CLI

def build_parser():
    p = argparse.ArgumentParser(prog='python -m bench.ozmap_rep.run', description=__doc__.split('\n')[0])
    sub = p.add_subparsers(dest='command', required=True)
    plan = sub.add_parser('plan')
    plan.add_argument('--list-cells', action='store_true')
    cell = sub.add_parser('cell')
    cell.add_argument('id')
    for q in (cell, sub.add_parser('telemetry'), sub.add_parser('features')):
        q.add_argument('--run-dir', default=None)
        q.add_argument('--mode', choices=('fake', 'live'), default=None)
        q.add_argument('--baseline', default=None)
        q.add_argument('--codex-sessions-dir', default=None)
        q.add_argument('--claude-weekly-percent', type=float, default=None)
    cell.add_argument('--stop-after', type=int, default=None)
    cell.add_argument('--fake-fail', type=int, default=0)
    cell.add_argument('--fake-refresh', type=int, default=None)
    d = sub.add_parser('dry')
    d.add_argument('--run-dir', required=True)
    fz = sub.add_parser('freeze')
    fz.add_argument('--new-run-dir', default=None)
    fz.add_argument('--disposition', default=None)
    sub.add_parser('verify-freeze')
    return p


def _opts(args):
    if args.run_dir:
        run_dir = Path(args.run_dir)
    elif args.mode == 'fake':
        run_dir = config.RUNS_DEFAULT / 'fake'
    else:
        run_dir = live_run_dir()
    return Options(run_dir, mode=args.mode, baseline=args.baseline, sessions_dir=args.codex_sessions_dir,
                   claude_percent=args.claude_weekly_percent, stop_after=getattr(args, 'stop_after', None),
                   fake_fail=getattr(args, 'fake_fail', 0), fake_refresh=getattr(args, 'fake_refresh', None))


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if args.command == 'plan':
        for s in cell_specs():
            print(json.dumps({k: s[k] for k in ('id', 'command', 'live_command', 'backend', 'workload', 'wave', 'arm',
                                                 'nominal_calls', 'requires', 'allocation')}))
        return 0
    if args.command == 'cell':
        spec = spec_by_id(args.id)
        if spec is None:
            print(f'unknown cell {args.id!r}; see `plan --list-cells`', file=sys.stderr)
            return config.EXIT_USAGE
        opts = _opts(args)
        problem = mode_problem(opts)
        if problem:
            print(f'{args.id}: {problem} (no call made)', file=sys.stderr)
            return config.EXIT_USAGE
        opts.run_dir.mkdir(parents=True, exist_ok=True)
        if not (opts.run_dir / 'preparation.json').exists():
            snapshot_preparation(opts.run_dir)
        return CellRun(spec, opts).run()
    if args.command == 'dry':
        return dry(args.run_dir)
    if args.command == 'telemetry':
        return telemetry(_opts(args))
    if args.command == 'features':
        return features(_opts(args))
    if args.command == 'freeze':
        return freeze_command(args.new_run_dir, args.disposition)
    if args.command == 'verify-freeze':
        problems = verify_freeze()
        print(json.dumps({'ok': not problems, 'problems': problems}, indent=1))
        return 0 if not problems else config.EXIT_FREEZE
    return config.EXIT_USAGE


if __name__ == '__main__':
    sys.exit(main())
