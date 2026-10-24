"""oz map clean replication runner (Amendment 4). Standard library only.

    python -m bench.ozmap_rep.run plan --list-cells               the 16 cells, one JSON line each
    python -m bench.ozmap_rep.run cell <id> --mode fake|live ...  run or resume one cell (--mode is required)
    python -m bench.ozmap_rep.run dry --run-dir D                 every cell in fake mode, zero rules, then the scorer
    python -m bench.ozmap_rep.run telemetry --mode live ...       the A4.2 telemetry certificate (live only)
    python -m bench.ozmap_rep.run freeze | verify-freeze          hash the frozen inputs before evaluation calls (A4.1)
    python -m bench.ozmap_rep.run features --mode live            record `codex features list` for a worker home (A4.2)

Cells and allocations follow A4.5; isolation A4.2; tool events A4.3; capacity A4.4; bootstrap validity A4.6; usage
A4.7; operations A4.8; Sonnet A4.9; stops A4.12. build-notes.md maps every clause to the code.

Run state. Every physical call is one line in D/attempts.jsonl (append only, failures included), its complete prompt
is D/prompts/<call id>.txt, its redacted raw output D/captures/<call id>.*, its parsed outcome
D/cells/<cell>/calls/<call id>.json. Before a call starts, D/cells/<cell>/inflight/<call id>.json is written with the
prepared authentication hash; right after the spawn it gains the child pid. A marker is removed only after the call's
authentication was reconciled (A4.2). On resume, every marker of the run directory is recovered before anything else:
a recorded child that is still running stops the resume, every Codex worker is inventoried and reconciled, and a
marker without an attempt line becomes an interrupted attempt (it consumed its allowance; its batch may be retried
only from the infrastructure reserve). A batch whose attempt ended with any terminal outcome is never sent again. A
completed cell has D/cells/<cell>/DONE.json, a settled but incomplete one SETTLED.json; neither is ever rerun.

One cell process at a time per run directory (council round 1, item 2): every cell, telemetry and features run holds
an exclusive per cell lock and the experiment lock, both taken without waiting before any state is read.
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
from . import events, isolation, prompts, quota, redact, rules, usage, workload  # noqa: E402
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
RETRYABLE = ('infrastructure_failure', 'interrupted')
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


def bind_identity(run_dir, opts, baseline_sha=None):
    """Write D/experiment.json (mode, freeze identity, baseline lineage) before the first attempt; live runs also
    archive the authorized freeze as D/freeze.json. Never rewritten."""
    run_dir = Path(run_dir)
    path = run_dir / 'experiment.json'
    if path.exists():
        return _read_json(path)
    doc = {'schema': 'ozmap-rep.experiment/1', 'experiment': EXPERIMENT, 'mode': opts.mode,
           'run_dir': str(run_dir.resolve()), 'created_at': _now(),
           'freeze_sha256': freeze_sha256() if opts.mode == 'live' else None,
           'baseline_auth_sha256': baseline_sha, 'live_ledger': str(opts.live_ledger) if opts.mode == 'live' else None,
           'simulation': opts.mode != 'live'}
    if opts.mode == 'live' and config.FREEZE_FILE.exists():
        shutil.copyfile(config.FREEZE_FILE, run_dir / 'freeze.json')
    _write_json(path, doc)
    return doc


def ledger_problems(run_dir, ledger):
    """The experiment ledger outside every run directory (RT1.5): every live charge ever made must be in this run
    directory's attempts or in flight here, and no live charge may belong to another run directory."""
    rows = jsonl(ledger)
    if not rows:
        return []
    here = str(Path(run_dir).resolve())
    known = {a.get('call_id') for a in jsonl(Path(run_dir) / 'attempts.jsonl')}
    known |= {(_read_json(p, {}) or {}).get('call_id') for p in Path(run_dir).glob('cells/*/inflight/*.json')}
    problems = []
    other = sorted({r.get('run_dir') for r in rows if r.get('run_dir') != here})
    disposition = (_read_json(config.FREEZE_FILE, {}) or {}).get('disposition')
    if other and not (disposition and Path(disposition).is_file()):
        problems.append(f'the experiment ledger holds live calls of other run directories: {other[:3]}')
    missing = sorted(r.get('call_id') for r in rows if r.get('run_dir') == here and r.get('call_id') not in known)
    if missing:
        problems.append(f'live calls in the experiment ledger are missing from this run directory: {missing[:5]}')
    return problems


# ================================================================================================ processes

_TLS = threading.local()


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


def spawn(run_dir, launch, stdin_text, env, cwd, external, timeout=config.CALL_TIMEOUT_S):
    """Run one child; every spawn is logged in D/spawns.jsonl with whether it is an external model CLI. Right after
    the process starts, the launching thread's on_start hook records its pid in the in-flight marker."""
    _append(run_dir, 'spawns.jsonl', {'exe': Path(launch[1] if not external else launch[0]).name,
                                      'external': bool(external), 'at': _now()})
    t0 = time.monotonic()
    start = _now()
    proc = subprocess.Popen(launch, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=str(cwd), env=env)
    hook = getattr(_TLS, 'on_start', None)
    if hook is not None:
        with contextlib.suppress(Exception):
            hook(proc.pid)
    timed_out = False
    try:
        out, err = proc.communicate(stdin_text.encode('utf-8'), timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        out, err = proc.communicate()
    return {'stdout': out.decode('utf-8', 'replace'), 'stderr': err.decode('utf-8', 'replace'),
            'exit_code': None if timed_out else proc.returncode, 'timed_out': timed_out,
            'started_at': start, 'ended_at': _now(), 'elapsed_s': round(time.monotonic() - t0, 3)}


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

    def acquire(self, exclude=(), timeout=120):
        end = time.monotonic() + timeout
        while True:
            for k in range(config.SLOTS):
                if k in self.held or k in exclude:
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
        """Hash the executable and every file beside it now; returns the problems against the frozen identity."""
        ident = isolation.executable_identity(self.exe)
        self.identity, self.exe_sha256 = ident, ident['sha256']
        want = self.frozen.get('identity') or {}
        problems = []
        if not want:
            problems.append('no frozen executable identity')
        if ident['sha256'] != self.frozen.get('exe_sha256'):
            problems.append('executable hash differs from the frozen executable hash')
        if want and ident['payload'] != want.get('payload'):
            problems.append('launcher payload beside the executable differs from the frozen payload')
        if want and not _same(ident['path'], want.get('path')):
            problems.append('the resolved executable path differs from the frozen path')
        return problems


# ================================================================================================ judging

def _turn_usage(stdout):
    found = None
    for line in stdout.splitlines():
        if not line.startswith('{'):
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get('type') == 'turn.completed':
            found = e.get('usage')
    return found


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


def recover_inflight(run_dir, opts, say=None, iso=None):
    """Experiment wide recovery before anything else (council round 1, items 3 and B3). Every marker of the run
    directory is either an orphan (no attempt line: the runner died with the call in flight) or a recorded call whose
    reconciliation did not finish. A recorded child that is still running stops the resume and nothing is touched.
    Every Codex worker of a marker is then inventoried (finish) and reconciled against the baseline generation it was
    prepared from: one changed worker is propagated, more than one, an authentication failure or any ambiguity
    stops Codex evaluation; the newer baseline is never replaced. Only then are orphans recorded as interrupted
    attempts and the markers removed. Returns the recovery record."""
    run_dir = Path(run_dir)
    markers = []
    for path in sorted(run_dir.glob('cells/*/inflight/*.json')):
        m = _read_json(path)
        markers.append((path, m if isinstance(m, dict) else {'call_id': None, 'unreadable': True}))
    if not markers:
        return None
    attempts = jsonl(run_dir / 'attempts.jsonl')
    by_call = {a.get('call_id'): a for a in attempts if a.get('call_id')}
    alive = [m for _, m in markers if m.get('call_id') not in by_call and pid_alive(m.get('pid'), m.get('pid_created'))]
    if alive:
        raise Stop(config.EXIT_INTERRUPTED, 'calls recorded in flight are still running (pids '
                   f"{sorted(m.get('pid') for m in alive)}); resume after they have ended (nothing was touched)")
    record = {'at': _now(), 'markers': [m.get('call_id') for _, m in markers], 'action': 'none', 'ambiguous': []}
    fins = {}
    codex = [(p, m) for p, m in markers if m.get('backend') == 'codex']
    if codex:
        iso = iso or isolation.Isolation(opts.baseline, run_dir, run_dir / 'evidence',
                                         frozen_inventory=isolation.load_inventory(), base_env=opts.base_env)
        workers, ambiguous = {}, []
        for _, m in codex:
            cid, slot = m.get('call_id'), m.get('slot')
            if m.get('unreadable'):
                ambiguous.append('an unreadable in-flight marker')
                continue
            if not isinstance(slot, int) or isinstance(slot, bool):
                ambiguous.append(f'{cid}: no slot recorded')
                continue
            home = iso.home(slot)
            orphan = cid not in by_call
            if orphan and not m.get('pid'):
                if _home_shows_start(home, m.get('prepared_sha') or iso.baseline_sha256()):
                    ambiguous.append(f'{cid}: no child pid recorded, but the worker home shows a started CLI')
                elif not home.exists():
                    continue  # never prepared: nothing to reconcile
            if slot in workers:
                ambiguous.append(f'slot {slot}: more than one unreconciled marker')
                continue
            if not home.exists():
                ambiguous.append(f'{cid}: worker home missing after a spawn')
                continue
            fin = iso.finish(slot, prepared_sha256=m.get('prepared_sha'))
            fins[cid] = fin
            row = by_call.get(cid) or {}
            failure = row.get('outcome') == 'auth_failure' and m.get('role') != 'probe'
            workers[slot] = {'sha256': fin['worker_auth_sha256'], 'prepared': m.get('prepared_sha'),
                             'auth_failure': failure, 'call_id': cid}
        base = iso.baseline_sha256()
        verdict = isolation.reconcile_generations(base, workers, ambiguous)
        record.update(action=verdict['action'], ambiguous=ambiguous, baseline_auth_sha256=base,
                      workers={str(s): {k: w.get(k) for k in ('sha256', 'prepared', 'auth_failure', 'call_id')}
                               for s, w in workers.items()})
        if verdict['action'] == 'propagate':
            try:
                iso.propagate(verdict['slot'], expected_baseline_sha256=workers[verdict['slot']]['prepared'])
            except isolation.IsolationError as exc:
                verdict = {'action': 'stop_codex', 'reason': f'propagation refused: {exc}'}
                record['action'] = 'stop_codex'
        if verdict['action'] == 'stop_codex':
            _write_json(run_dir / 'codex-stop.json', {'reason': 'recovery: ' + verdict.get('reason', ''),
                                                      'cell': None, 'at': _now()})
        _append(run_dir, 'evidence/auth-reconcile.jsonl', dict(record, recovery=True, reason=verdict.get('reason')))
    attempts_now = {a.get('call_id') for a in jsonl(run_dir / 'attempts.jsonl')}
    for _, m in markers:
        cid = m.get('call_id')
        if not cid or m.get('marker') == 'probe' or cid in attempts_now:
            continue
        fin = fins.get(cid)
        row = {k: v for k, v in m.items() if k not in ('phase',)}
        row.update(outcome='interrupted', ended_at=_now(), elapsed_s=None, usage_status='incomplete',
                   charged_tokens=0, note='the runner ended while the call was in flight',
                   auth=None if fin is None else {k: fin[k] for k in ('worker_auth_sha256', 'baseline_auth_sha256',
                                                                        'auth_changed', 'auth_failure')},
                   runtime_files=None if fin is None else len(fin['runtime_files']))
        _append(run_dir, 'attempts.jsonl', row)
    _append(run_dir, 'evidence/recovery.jsonl', record)
    for path, _ in markers:
        with contextlib.suppress(OSError):
            path.unlink()
    if say:
        say(f"recovered {len(markers)} in-flight marker(s): {record['action']}")
    return record


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

    # ------------------------------------------------------------------------------------------- state

    def state(self, state, **extra):
        doc = _read_json(self.dir / 'state.json', {}) or {}
        doc.update(extra, state=state, cell=self.spec['id'], updated_at=_now())
        doc.setdefault('invocations', [])
        _write_json(self.dir / 'state.json', doc)

    def say(self, text):
        self.opts.out.write(text.rstrip() + '\n')

    # ------------------------------------------------------------------------------------------- gates

    def codex_quota_gate(self):
        g = quota.codex_gate(self.opts.sessions_dir)
        if not g['ok'] or not config.QUOTA_FRESH_AFTER_LAST_CODEX_CALL:
            return g
        ends = [_parse_time(a.get('ended_at')) for a in jsonl(self.run_dir / 'attempts.jsonl')
                if a.get('backend') == 'codex' and a.get('mode') == 'live' and a.get('ended_at')]
        ends = [e for e in ends if e is not None]
        if not ends:
            return g
        reading = quota.codex_reading_time(self.opts.sessions_dir)
        if reading is None or reading <= max(ends):
            return {'ok': False, 'percent': g['percent'],
                    'reason': 'the Codex usage reading is older than the last Codex evaluation call (worker calls '
                              'never update the owner session files): refresh it with a Codex session in the owner '
                              'home, then resume (A4.12)'}
        return g

    def gates(self):
        opts = self.opts
        if (self.run_dir / 'safety-kill.json').exists():
            raise Stop(config.EXIT_SAFETY_KILL, 'a safety kill is established for this run (A4.11); no further dispatch')
        if self.codex:
            gate = isolation.wave_gate(opts.baseline)
            _append(self.run_dir, 'evidence/wave-gates.jsonl', {'cell': self.spec['id'], 'ok': gate['ok'],
                                                               'exp': gate['exp'], 'hours_left': gate['hours_left'],
                                                               'at': _now()})
            if not gate['ok']:
                raise Stop(config.EXIT_AUTH_GATE, 'baseline authentication gate failed (A4.2): ' + gate['reason'])
            problems = isolation.verify_baseline(opts.baseline, isolation.load_inventory())
            if problems:
                raise Stop(config.EXIT_AUTH_GATE, f'baseline inventory check failed (A4.2): {problems[:5]}; '
                                                  f'reseed with: CODEX_HOME={opts.baseline} codex login')
            if (self.run_dir / 'codex-stop.json').exists():
                raise Stop(config.EXIT_AUTH_STOP, 'Codex evaluation is stopped for this run (A4.2 reconciliation)')
        if opts.mode == 'live':
            g = quota.claude_gate(opts.claude_percent)
            if not g['ok']:
                raise Stop(config.EXIT_QUOTA, g['reason'])
            if self.codex:
                g = self.codex_quota_gate()
                if not g['ok']:
                    raise Stop(config.EXIT_QUOTA, g['reason'])
            if not _same(self.run_dir, live_run_dir()):
                raise Stop(config.EXIT_IDENTITY, f'live cells run only in the frozen live run directory '
                                                 f'{live_run_dir()} (A4.1, A4.5); another directory needs a new '
                                                 f'freeze and a recorded council disposition')
            problems = ledger_problems(self.run_dir, opts.live_ledger)
            if problems:
                raise Stop(config.EXIT_IDENTITY, f'experiment ledger check failed: {problems}')
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
        """Every physical call of the run directory, plus (live) every charge of the experiment ledger."""
        b = budget_mod.Budget()
        seen = set()
        rows = jsonl(self.run_dir / 'attempts.jsonl')
        if self.opts.mode == 'live':
            rows = rows + jsonl(self.opts.live_ledger)
        for a in rows:
            cid = a.get('call_id')
            if cid in seen:
                continue
            seen.add(cid)
            b._attempts.append({k: a.get(k) for k in ('backend', 'workload', 'allocation', 'reason', 'kind',
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
        latest attempt is terminal are taken from disk and never sent again."""
        prior = self.prior_attempts()
        results, pending = {}, []
        for idx, jobs in enumerate(batches):
            key = self.batch_key(round_no, idx)
            mine = [a for a in prior if a.get('batch') == key]
            last = mine[-1] if mine else None
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
            if not self.interrupted:
                problems = self.exe.verify()
                if problems:
                    raise Stop(config.EXIT_FREEZE, f'executable verification before the launch group failed (A4.2): '
                                                   f'{problems}')
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
                if self.opts.mode == 'live' and self.codex:
                    g = quota.codex_gate(self.opts.sessions_dir)
                    if not g['ok']:
                        self.interrupted = (config.EXIT_QUOTA, g['reason'])
                        waiting.append(item)
                        continue
                try:
                    prepared = self.prepare_call(key, jobs, tries, reason, bootstrap)
                except Stop:
                    self.abandon(group)
                    raise
                if prepared is None:
                    results[key] = {'outcome': 'budget_exhausted', 'answers': {}, 'job_ids': [j['id'] for j in jobs]}
                    continue
                group.append(prepared)
            if group:
                threads = [threading.Thread(target=self.execute, args=(c,), daemon=True) for c in group]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                self.after_group(group)
            pending = []
            for c in group:
                if c['outcome'] in RETRYABLE and not self.interrupted:
                    pending.append((c['batch'], c['jobs'], c['try'] + 1, 'infrastructure_retry'))
                else:
                    results[c['batch']] = c['output']
            if self.interrupted:
                for item in waiting:
                    results.setdefault(item[0], {'outcome': 'not_launched', 'answers': {},
                                                 'job_ids': [j['id'] for j in item[1]]})
                for c in group:
                    if c['outcome'] in RETRYABLE:
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
        """Everything before the spawn, in the launching thread: the model input, the leak check, the slot, the
        worker home reconstruction and launch verification (Codex), the budget charge (also in the experiment ledger
        when live) and the in-flight marker. Returns None when the budget refuses the call."""
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
            if self.codex:
                prepared = self.iso.prepare(slot)
                argv = isolation.codex_argv(self.exe.exe, config.CODEX_MODEL, config.CODEX_EFFORT,
                                            prepared['workdir'], self.exe.disable_args)
                env, workdir, stdin = self.launch_env(prepared), prepared['workdir'], inp['stdin_codex']
                problems = self.verify_codex_launch(argv, env, workdir)
                prepared_sha = prepared['auth_sha256']
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
                prepared_sha = None
            evidence = {'call_id': call_id, 'cell': spec['id'], 'slot': slot, 'argv_sha256': isolation.argv_sha256(argv),
                        'exe_sha256': self.exe.exe_sha256, 'exe_identity': self.exe.identity,
                        'frozen': {k: v for k, v in self.exe.frozen.items() if k != 'identity'},
                        'env_names': sorted(env), 'workdir': str(workdir), 'problems': problems,
                        'prompt_sha256': prompts.sha256(record), 'stdin_sha256': prompts.sha256(stdin), 'at': _now(),
                        'instruction_sources': [str(p) for p in isolation.instruction_sources(workdir)],
                        'home_listing': listing_before, 'workdir_listing': workdir_before, 'role': self.role}
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
            prompt_path = self.run_dir / 'prompts' / f'{call_id}.txt'
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(record, encoding='utf-8')
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
            marker = {'call_id': call_id, 'cell': spec['id'], 'backend': self.backend, 'workload': self.workload,
                      'wave': spec['wave'], 'arm': spec['arm'], 'allocation': spec['allocation'], 'batch': key,
                      'try': tries, 'reason': reason, 'kind': charged['kind'], 'slot': slot, 'mode': self.opts.mode,
                      'group': self.current_group, 'marker': 'call', 'role': self.role, 'phase': 'prepared',
                      'prepared_sha': prepared_sha, 'exe_sha256': self.exe.exe_sha256, 'pid': None,
                      'started_at': _now(), 'job_ids': [j['id'] for j in jobs],
                      'records': {op: sum(1 for j in jobs if j['op'] == op) for op in sorted({j['op'] for j in jobs})},
                      'prompt_sha256': prompts.sha256(record), 'stdin_sha256': prompts.sha256(stdin),
                      'system_sha256': prompts.sha256(inp['system']), 'bootstrap': bootstrap}
            _write_json(self.dir / 'inflight' / f'{call_id}.json', marker)
            if self.opts.mode == 'live':
                _append_file(self.opts.live_ledger, {'call_id': call_id, 'run_dir': str(self.run_dir.resolve()),
                                                     'backend': self.backend, 'workload': self.workload,
                                                     'allocation': spec['allocation'], 'reason': reason,
                                                     'kind': charged['kind'], 'outcome': 'launched', 'at': _now()})
            launch = self.exe.prefix + list(argv) if self.opts.mode == 'fake' else list(argv)
            return {'call_id': call_id, 'batch': key, 'try': tries, 'jobs': jobs, 'inp': inp, 'slot': slot,
                    'launch': launch, 'env': env, 'workdir': workdir, 'stdin': stdin, 'marker': marker,
                    'prepared_sha': prepared_sha, 'bootstrap': bootstrap, 'outcome': None, 'output': None,
                    'role': self.role, 'home_listing_before': listing_before, 'workdir_listing_before': workdir_before,
                    'instruction_sources': evidence['instruction_sources']}
        except Stop:
            if self.codex:
                with contextlib.suppress(Exception):
                    self.iso.finish(slot)
            self.slots.release(slot)
            raise

    def verify_codex_launch(self, argv, env, workdir):
        return isolation.verify_launch(argv=argv, env=env, workdir=workdir, exe_sha256=self.exe.exe_sha256,
                                       frozen=self.exe.frozen)

    def abandon(self, group):
        """Calls prepared but never spawned (a later launch check failed): nothing reached a CLI, so their markers go
        and their in-memory budget charges are never written; slots and worker homes are released. A live charge
        already in the experiment ledger stays there (it is counted, conservatively)."""
        for c in group:
            with contextlib.suppress(OSError):
                (self.dir / 'inflight' / f"{c['call_id']}.json").unlink()
            with contextlib.suppress(OSError):
                (self.run_dir / 'prompts' / f"{c['call_id']}.txt").unlink()
            if self.codex:
                with contextlib.suppress(Exception):
                    self.iso.finish(c['slot'], prepared_sha256=c['prepared_sha'])
            self.slots.release(c['slot'])

    def _mark_spawned(self, c, pid):
        c['marker'].update(pid=pid, pid_created=process_created(pid), phase='spawned', spawned_at=_now())
        _write_json(self.dir / 'inflight' / f"{c['call_id']}.json", c['marker'])

    def execute(self, c):
        _TLS.on_start = lambda pid: self._mark_spawned(c, pid)
        try:
            c['raw'] = spawn(self.run_dir, c['launch'], c['stdin'], c['env'], c['workdir'],
                             external=self.opts.mode == 'live')
        except Exception as exc:  # noqa: BLE001  (any spawn failure is recorded, never lost with its marker)
            c['raw'] = {'stdout': '', 'stderr': f'spawn failed: {type(exc).__name__}', 'exit_code': None,
                        'timed_out': False, 'started_at': _now(), 'ended_at': _now(), 'elapsed_s': 0.0}
        finally:
            _TLS.on_start = None

    def secrets(self, c):
        if not self.codex:
            return set()
        return redact.secrets_from_auth(self.opts.baseline / isolation.AUTH, self.iso.home(c['slot']) / isolation.AUTH,
                                        c['env'].get('CODEX_HOME') and Path(c['env']['CODEX_HOME']) / isolation.AUTH)

    def after_group(self, group):
        """Judge every call of a finished launch group on its redacted output, record its attempt, then reconcile
        authentication (A4.2). Slots and in-flight markers are released only after the reconciliation, so a runner
        that dies before it leaves the markers for recovery."""
        judged = []
        for c in group:
            raw = dict(c['raw'])
            secrets = self.secrets(c)
            raw['stdout'], r1 = redact.redact(raw['stdout'], secrets)
            raw['stderr'], r2 = redact.redact(raw['stderr'], secrets)
            c['raw'], c['redaction'] = raw, redact.merge(r1, r2)
            judged.append((c,) + tuple((judge_codex if self.codex else judge_sonnet)(raw)))
        replies = [r for _, o, r, *_ in judged if isinstance(r, str)]
        counts = iter(tokenizer.count(replies)) if self.codex and replies else iter(())
        workers = {}
        for c, outcome, reply, usage_raw, cls, why in judged:
            visible = next(counts) if self.codex and isinstance(reply, str) else None
            fin = None
            if self.codex:
                fin = self.iso.finish(c['slot'], auth_failure=outcome == 'auth_failure',
                                      prepared_sha256=c['prepared_sha'])
                c['fin'] = fin
                workers[c['slot']] = {'sha256': fin['worker_auth_sha256'], 'prepared': c['prepared_sha'],
                                      'auth_failure': fin['auth_failure'] and c.get('role') != 'probe',
                                      'call_id': c['call_id']}
            output = self.interpret(c, outcome, reply)
            outcome = output['outcome']
            if self.codex:
                dec = usage.decode_codex_checked(usage_raw, cache_certified=self.cache_certified)
                issue = None
                if dec['status'] != 'incomplete':
                    issue = usage.reasoning_inclusion(usage_raw, visible)
                status = dec['status']
                if issue and status == 'complete':
                    status = 'unverified'
                if status == 'complete' and isinstance(usage_raw, dict) and \
                        (usage_raw.get('cache_write_input_tokens') or 0) > 0:
                    status = 'unverified'
                    dec = dict(dec, problems=list(dec['problems']) + ['cache_write_input_tokens positive: its '
                                                                      'relation to input_tokens is uncertified'])
                additive = usage.additive_tokens(usage_raw) if dec['status'] not in ('incomplete',) and \
                    dec.get('charged_tokens') is not None else None
            else:
                dec = usage.decode_sonnet(usage_raw)
                issue, status, additive = None, dec['status'], None
                if dec['status'] != 'incomplete':
                    additive = usage_raw['input_tokens'] + usage_raw['cached_input_tokens'] + usage_raw['output_tokens']
            captures = self.run_dir / 'captures'
            captures.mkdir(parents=True, exist_ok=True)
            # bytes, so the capture hashes exactly like the text the attempt was judged on (no newline translation)
            (captures / f"{c['call_id']}.stdout").write_bytes(c['raw']['stdout'].encode('utf-8'))
            (captures / f"{c['call_id']}.stderr").write_bytes(c['raw']['stderr'].encode('utf-8'))
            marker = {k: v for k, v in c['marker'].items() if k != 'phase'}
            row = dict(marker, outcome=outcome, why=why, exit_code=c['raw']['exit_code'],
                       timed_out=c['raw']['timed_out'], started_at=c['raw']['started_at'],
                       ended_at=c['raw']['ended_at'], elapsed_s=c['raw']['elapsed_s'],
                       stdout_sha256=prompts.sha256(c['raw']['stdout']),
                       stderr_sha256=prompts.sha256(c['raw']['stderr']), events={
                           'verdict': cls['verdict'], 'efficiency_invalid': cls['efficiency_invalid'],
                           'external_read': cls['external_read'], 'notices': len(cls['notices']),
                           'tool_requests': cls['tool_requests'], 'tool_executions': cls['tool_executions'],
                           'uncertain': cls['uncertain'][:20],
                           'transport_notices': len(cls.get('transport_notices') or [])},
                       usage_raw=usage_raw, usage=dec, usage_status=status, reasoning_issue=issue,
                       visible_tokens=visible, cache_certified=self.cache_certified if self.codex else None,
                       charged_tokens=dec.get('charged_tokens') or 0, additive_tokens=additive,
                       redaction=c['redaction'], credential_disclosure=bool(c['redaction']['redactions']),
                       auth=None if fin is None else {k: fin[k] for k in ('worker_auth_sha256', 'baseline_auth_sha256',
                                                                           'auth_changed', 'auth_failure')},
                       runtime_files=None if fin is None else len(fin['runtime_files']))
            if c.get('expected_outcome'):
                row['expected_outcome'] = c['expected_outcome']
            _write_json(self.dir / 'calls' / f"{c['call_id']}.json", output)
            _append(self.run_dir, 'attempts.jsonl', row)
            if self.opts.mode == 'fake':
                rec = _read_json(self.exe.fakes['records'] / f"{c['call_id']}.json")
                if rec is None:
                    rec = {'cell': self.spec['id'], 'n': c['marker'].get('try'), 'cli': self.backend,
                           'argv': c['launch'][1:], 'codex_home': None, 'home_listing': [], 'workdir': None,
                           'workdir_listing': [], 'env_names': [], 'stdin_sha256': prompts.sha256(c['stdin'])}
                _append(self.run_dir, 'fake_calls.jsonl', rec)
            c['marker']['phase'] = 'recorded'
            _write_json(self.dir / 'inflight' / f"{c['call_id']}.json", c['marker'])
            c['outcome'], c['output'], c['row'] = outcome, output, row
        try:
            if self.codex and workers:
                self.reconcile(workers)
            # markers go only once the group is reconciled; a runner that dies before keeps them for recovery
            for c in group:
                with contextlib.suppress(OSError):
                    (self.dir / 'inflight' / f"{c['call_id']}.json").unlink()
        finally:
            for c in group:
                self.slots.release(c['slot'])

    def reconcile(self, workers):
        """A4.2 after every call, failures included: each worker is compared with the baseline generation it was
        prepared from; one changed worker is propagated under the lock against that generation, anything else that
        changed authentication, or any authentication failure, stops Codex evaluation."""
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
        """The parsed output of one call: answers keyed by job id (and, for a bootstrap, the proposed rules). A
        bootstrap whose envelope parses but whose answers are malformed or incomplete is `malformed_answers`: a
        completion failure (A4.6); its proposals stay observations."""
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
            with exclusive(self.run_dir / 'locks' / f"cell-{spec['id']}.lock"), \
                    exclusive(self.run_dir / 'locks' / 'experiment.lock'):
                return self._guarded()
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
                                           frozen_inventory=isolation.load_inventory(), base_env=opts.base_env)
        bind_identity(self.run_dir, opts, self.iso.baseline_sha256() if self.iso else None)
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

    def _window(self, started, t0, ended_how):
        """A work window: real submission to resolution time of this invocation's work on the cell, local work
        (preparation, parsing, admission, rule execution, audits, delivery) and launch skew included (item 14)."""
        row = {'invocation': self.invocation, 'started_at': started, 'ended_at': _now(),
               'elapsed_s': round(time.monotonic() - t0, 3), 'calls': self.invocation_calls, 'ended': ended_how}
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
        t0, started = time.monotonic(), _now()
        try:
            result = self.arm()
        except Stop as stop:
            self._window(started, t0, 'stopped')
            self.state('incomplete', reason=stop.reason)
            self.say(f"{spec['id']}: {stop.reason}")
            return stop.code
        window = self._window(started, t0, 'returned')
        result.update(cell=spec['id'], spec=spec, mode=opts.mode, last_window=window)
        exhausted = [k for k, v in result.get('batches', {}).items() if v in ('budget_exhausted',)]
        killed = self.rule_errors(result)
        _write_json(self.dir / 'result.json', result)
        if killed:
            _write_json(self.run_dir / 'safety-kill.json', {'cell': spec['id'], 'rule_errors': len(killed),
                                                            'jobs': killed[:20], 'at': _now()})
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
        in-flight marker and reconciled like a call (council C2). Returns (exit code, stdout, stderr)."""
        slot = self.slots.acquire()
        try:
            prepared = self.iso.prepare(slot)
            marker, path, on_start = self.probe_marker(name, slot, prepared['auth_sha256'])
            problems = self.exe.verify()
            if problems:
                raise Stop(config.EXIT_FREEZE, f'executable verification before {name} failed: {problems}')
            try:
                code, out, err = run_local([self.exe.exe, *self.exe.disable_args, *args] if name == 'features'
                                           else [self.exe.exe, *args], prepared['env'], prepared['workdir'], on_start)
            finally:
                fin = self.iso.finish(slot, prepared_sha256=prepared['auth_sha256'])
                self.reconcile({slot: {'sha256': fin['worker_auth_sha256'], 'prepared': prepared['auth_sha256'],
                                       'auth_failure': False, 'call_id': marker['call_id']}})
                with contextlib.suppress(OSError):
                    path.unlink()
            secrets = redact.secrets_from_auth(self.opts.baseline / isolation.AUTH)
            out, _ = redact.redact(out, secrets)
            err, _ = redact.redact(err, secrets)
            return code, out, err, fin
        finally:
            self.slots.release(slot)

    def record_features(self):
        """A4.2: before each wave, the effective features from `codex features list` with a reconstructed worker
        home and the frozen disable options (a local command; no model request)."""
        code, out, _, fin = self.worker_probe('features', ['features', 'list'])
        rows = {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[-1] in ('true', 'false'):
                rows[parts[0]] = parts[-1] == 'true'
        argv = [*self.exe.disable_args, 'features', 'list']
        _write_json(self.run_dir / 'evidence' / f"features-{self.spec['id']}.json",
                    {'cell': self.spec['id'], 'argv_sha256': hashlib.sha256(json.dumps(argv).encode()).hexdigest(),
                     'exit_code': code, 'features': rows, 'enabled_tool_features':
                         sorted(k for k in config.DISABLE_FEATURES if rows.get(k)),
                     'runtime_files': fin['runtime_files'], 'at': _now()})


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
    machinery as evaluation calls (council round 1, items 1 and 4, B4), on its own telemetry allocation:

    1. `login status` with an empty CODEX_HOME (local, no model request): must say not logged in.
    2. `login status` with a reconstructed worker home (local): must say logged in.
    3. the frozen exec argv with an empty CODEX_HOME (a charged telemetry call): must end in an authentication
       failure without a reply or usage, so the exec route has no credential source but CODEX_HOME.
    4. the frozen exec argv with a reconstructed worker home on a neutral one job packet (a charged telemetry call):
       must deliver a plain reply; its startup runtime files are inventoried by name.
    5. `login status` with an empty CODEX_HOME again: the call left no credential in an OS store.
    The certificate is published (evidence/telemetry.jsonl, telemetry.json) only after the call was reconciled."""

    def __init__(self, opts):
        CellRun.__init__(self, dict(TELEMETRY_SPEC), opts)
        self.probe_home = None
        self.expected = 'ok'
        self.last_call = {}
        self.last_fin = None
        self.reconciled_all = True

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

    def launch_env(self, prepared):
        if self.role == 'probe':
            return isolation.child_env(self.probe_home, self.opts.base_env)
        return prepared['env']

    def verify_codex_launch(self, argv, env, workdir):
        if self.role != 'probe':
            return CellRun.verify_codex_launch(self, argv, env, workdir)
        problems = list(isolation.argv_check(argv))
        if isolation.argv_sha256(argv) != self.exe.frozen.get('argv_sha256'):
            problems.append('argument hash differs from the frozen argument hash')
        if self.exe.exe_sha256 != self.exe.frozen.get('exe_sha256'):
            problems.append('executable hash differs from the frozen executable hash')
        if os.listdir(self.probe_home):
            problems.append('the probe home is not empty')
        if os.listdir(workdir):
            problems.append('working directory is not empty')
        found, unreadable = isolation.instruction_scan(workdir)
        if found or unreadable:
            problems.append('instruction files or unreadable locations reachable')
        return problems

    def interpret(self, c, outcome, reply):
        out = CellRun.interpret(self, c, outcome, reply)
        out['outcome'] = outcome
        return out

    def fresh_probe_home(self):
        home = self.run_dir / 'homes' / 'probe-empty'
        shutil.rmtree(home, ignore_errors=True)
        home.mkdir(parents=True)
        self.probe_home = home
        return home

    def empty_login(self):
        home = self.fresh_probe_home()
        problems = self.exe.verify()
        if problems:
            raise Stop(config.EXIT_FREEZE, f'executable verification failed: {problems}')
        code, out, err = run_local([self.exe.exe, 'login', 'status'], isolation.child_env(home, self.opts.base_env),
                                   self.run_dir)
        listing = sorted(p.relative_to(home).as_posix() for p in home.rglob('*'))
        shutil.rmtree(home, ignore_errors=True)
        return login_state(out + '\n' + err), listing

    def arm(self):
        doc = {'schema': 'ozmap-rep.telemetry/2', 'at': _now(), 'login_status': {}, 'problems': []}
        doc['login_status']['empty_home_before'], doc['probe_home_files_before'] = self.empty_login()
        code, out, err, _ = self.worker_probe('login', ['login', 'status'])
        doc['login_status']['worker_home'] = login_state(out + '\n' + err)
        self.role, self.expected = 'probe', 'auth_failure'
        self.fresh_probe_home()
        probe = self.run_batches([[{'id': 'telemetry-j00', 'op': 'telemetry'}]], 1)
        probe_out = probe.get(self.batch_key(1, 0), {})
        probe_row = next((a for a in reversed(self.prior_attempts()) if a.get('batch') == self.batch_key(1, 0)), {})
        files = sorted(p.relative_to(self.probe_home).as_posix() for p in self.probe_home.rglob('*'))
        shutil.rmtree(self.probe_home, ignore_errors=True)
        doc['exec_probe_empty_home'] = {'outcome': probe_out.get('outcome'), 'call_id': probe_row.get('call_id'),
                                        'reply': bool(probe_out.get('answers')),
                                        'usage_present': probe_row.get('usage_raw') is not None,
                                        'probe_home_files_after': files}
        if probe_out.get('outcome') == 'auth_failure' and not self.interrupted:
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
                           'runtime_files': fin.get('runtime_files'), 'usage_status': row.get('usage_status'),
                           'auth_changed': fin.get('auth_changed')}
            doc['login_status']['empty_home_after'], _ = self.empty_login()
        else:
            doc['problems'].append('the empty home exec probe did not end in an authentication failure; the '
                                   'telemetry call was not made')
        doc['reconciled'] = not (self.run_dir / 'codex-stop.json').exists() and self.reconciled_all
        clean = doc.get('call') or {}
        doc['auth_read_from_codex_home'] = (doc['login_status'].get('empty_home_before') == 'not_logged_in'
                                            and doc['login_status'].get('worker_home') == 'logged_in'
                                            and doc['exec_probe_empty_home']['outcome'] == 'auth_failure')
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
    run.arm = arm
    run._run_locked = lambda spec, o: (arm(), config.EXIT_OK)[1]
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
                                 'startup_files': list(config.SIGNED_STARTUP_FILES)}}
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
                'tokenizer', 'interpreter', 'live_run_dir', 'signed_exceptions'):
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
    tok = now.get('tokenizer') or {}
    if not tok.get('vocabulary_ok'):
        problems.append('the pinned tokenizer vocabulary is unavailable')
    return problems


def freeze_command(new_run_dir=None, disposition=None):
    """Write freeze.json. Refused once a live run is bound to the current freeze (A4.1: the freeze cannot be replaced
    after dispatch), unless a new, unused live run directory and a recorded council disposition are named."""
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
