"""oz host: the step 6 host for the A/B/C kill pilot (amendment 2, council 2 and council 3). Standard library only.

One ArmHost per (arm, backend, workload) runs one arm:
  A  ordinary pooled map: every job goes to the model in pooled batches.
  B  rules with producer-local fallback: bootstrap (shared), rule phase, then fallback and audit jobs pooled only
     within one producer.
  C  identical rules with pooled fallback across producers.

Topology. Producers hand submissions to the host (submit(); the intake is persisted in the host ledger with conflict
detection). The host owns one oz_spool.Spool and one oz_spool.Scheduler (OS host lock, fencing epoch, slots, 64-record
batches, durable reservation before launch). Every job the host sends to a model (A's jobs, the bootstrap, fallbacks,
audits) is submitted to that spool and drained by the Scheduler; the rule phase runs before any of it is submitted, so
covered jobs never enter a batch. Rule rows and imported bootstrap rows are delivered by the host itself with zero
calls. collect(producer, submission) returns every delivered row.

Sealed wave (council 3, B12). Before any call run_wave checks that every dataset id occurs once in the wave, that the
intake is complete when expected_intake is set (the pilot: 4 producers x 64 jobs), and seals or verifies the wave
manifest in the experiment store (dataset id -> operation, input hash, producer, key): A, B and C consume the same data.

Durable wave plan (council 3, B4 and Opus A). Every dispatch round (bootstrap, r1, r2, r3) is persisted in the ledger
before anything is submitted: item id, original job, kind, pool, spool submission and delivery id, round. Spool
submission names derive from the round and the producer submission only, never from the set of jobs still open. A
restart loads every persisted plan first, reconciles the attempts it already made, and re-submits exactly the stored
round (the spool treats the identical payload as a no-op), so a job already sent is never sent again under a new
request. A job that is not in the stored round is not added to it (plan_closed, incomplete). New requests exist only for
the explicit retries: the audit retry round r2, the rule-8 round r3 and a new bootstrap try after a proven-unlaunched
(refused) attempt.

Execution authority (council 3, B5). The settlement generation of every job a round will settle (ordinary, fallback,
bootstrap) is claimed before its round is dispatched, recorded in the ledger, and the answer is settled with exactly
that generation; audits never claim (they settle nothing and must not fence a staged rule commit). A model answer that
fails a pinned check is a terminal failure (oz_rulephase settlement state failed).

Physical calls. launch(view) builds one oz.do/1 request whose request_id is the spool's request id (derived from the
batch id) and runs it in a child process (ChildLauncher: `python oz_host.py --child SPEC`, an explicit isolated env,
the host never touches os.environ) or in process for callable fake adapters (InProcessLauncher). execute() caps the
request at one physical call through oz_do's admit hook. Every request sets max_attempts 1 (A2.1). Before anything is
parsed, the child's stdout, stderr, exit code and timeout flag are written under the physical attempt id. The child's
timeout is the request's call_timeout_seconds plus a fixed margin; on timeout the whole process tree is killed
(taskkill /T on Windows, the child's own session elsewhere). Before every launch: the launch gate, the route check
(oz_route.verify of the frozen route in the real launch env, council 3 B11), the budget reservation and, when given, an
experiment-wide physical slot (SlotPool) are taken, in that order; a refusal launches nothing.

Ledgers (ledger.sqlite per host; append-only where it matters, council 3 B6, B7, B10).
  attempts     one row per physical attempt id: membership, bucket, FIRST raw evidence and elapsed (immutable once
               written, a trigger refuses any change) and an outcome: unlaunched (refused before launch), no_call (the
               child completed and the core ledger shows no call), physical (at least one call), unresolved. An
               unresolved outcome blocks complete accounting.
  events       launched, captured, failed, refused, not_started, reconciled, reconcile_failed: every step, with the
               evidence hashes of reconciliation children, never overwriting the first evidence.
  calls        one immutable row per physical call id read from the core ledger (run_dir/calls.jsonl) after every
               child, also when the child returned nothing (Opus B): usage (unknown stays unknown, never zero) and the
               call's job membership from call_start.job_map. The adapter capture is reconciled with it.
  allocations  one immutable row per (call, job, basis), membership from call_start.job_map (B7): share 1/n over the
               jobs the call really carried; "imported" rows charge the shared bootstrap analytically.
  plan, authority, deliveries (the first delivery of every terminal row with its wall and monotonic time: resume
               never re-times a delivery), violations (every efficiency or evidence violation event, never erased by a
               retry), timeline (phase start and end, wall and monotonic, per process session).
A conflicting duplicate insert into calls, allocations, plan or deliveries is a hard error (or, for a delivery, a
recorded violation that keeps the first row).

Budget (budget.sqlite per experiment). Frozen call caps per backend and bucket plus the global cap, frozen at first use;
a reservation per request id (one physical call at most) is taken atomically before the child starts.

Shared bootstrap (oz_rulephase.ExperimentStore). The frozen assignment (16 jobs from each of the 4 producers) binds as
soon as it is persisted, before any record exists (B2): those 64 jobs are bootstrap_pending until the one bootstrap
is recorded, never normal fallback; only the reconciliation of the existing invocation or a new try after a proven-
unlaunched attempt may resolve them. The claiming arm checks the packet before launch (exactly 64 records, one batch,
the input estimate including the shim text under max_input_tokens), dispatches it, settles all 64 answers through its
own settlement boundary and only then writes the immutable record (B3): status ok needs one physical call carrying all
64, a valid side file, no memo and 64 settled answers; every attempt (refused tries included), call, settlement and
failure reason is in the record. The importing arm verifies binding_key, assignment hash, worker hash and the payload of
every assigned dataset id before it imports (B12, Opus 4), settles the recorded answers through its own boundary, and
inherits the record's invalidity. Imports are idempotent and run on every resume (Opus 3).

Audits. One evaluation wave = all producers' submissions of one wave name; the population and the min(32, covered)
selection are persisted in the experiment store before dispatch, so B and C audit the same ids. A memo-served audit is
inconclusive and a permanent efficiency violation (B10).

Several operations. op may be {op id: op text}: one host then runs every operation of its workload.

Rule delivery (DRIVER rule 8, confirmed by council 3). With rule_delivery="after_audits" (default) covered jobs are
settled only after the wave's audits are decided; if a disagreement quarantined the rule, those undelivered rows fall
back to the model. Delivered rows always stay as recorded.

Timing (B8). Durations are monotonic within one process session (wall clock across sessions). The report keeps the
measured makespan (first intake to last terminal delivery), the charged makespan (an importing arm adds the shared
bootstrap's recorded elapsed and drops only its own wait for it), every phase duration, and the summed physical call
seconds as a separate metric; dry_run adds the replay projection as its own field.

Pilot entry (B9). ArmHost(pilot=config) refuses to run without a complete frozen configuration (check_pilot): global
and backend caps equal to the frozen budget, an experiment-wide slot pool of the frozen size, frozen batch limits and
call timeouts, the frozen route of the backend with the launch-time route check, and the declared usage semantics.

Reports never say "correct": accepted_by_checks is runtime acceptance; gold scoring is a separate offline step.
dry_run(matrix, recorded_usage) runs A/B/C with replay adapters and zero external calls.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback

from oz import Error
from oz_registry import canonical, digest
from oz_reply import USAGE_FIELDS, dumps, loads
import oz_rulephase as rp
import oz_spool

ARMS = ('A', 'B', 'C')
KINDS = ('bootstrap', 'fallback', 'audit', 'ordinary')
PROFILE = 'oz1g-selective-v1'
GOAL = 'Apply the operation to each referenced file independently.'
INPUT_POLICY = 'strip-one-terminal-newline/1'
MAX_REF_BYTES = 65536
MAX_INLINE = 65536
EXECUTION_SCHEMA = 'oz.host.execution/1'
REPORT_SCHEMA = 'oz.host.report/1'
CORRECTNESS = ('not assessed: accepted_by_checks means runtime acceptance (every applicable pinned check passed, and '
               'for rule rows rule provenance); audits measure agreement with a blind model answer; gold scoring is a '
               'separate offline step')
HOST_FILE = Path(__file__).resolve()
EXAMPLES = HOST_FILE.parent / 'examples'
BOOTSTRAP_ENV = ('OZ_BOOTSTRAP_ATTEMPT', 'OZ_BOOTSTRAP_DIR')


def _b32(identity) -> str:
    return base64.b32encode(hashlib.sha256(canonical(identity)).digest()).decode('ascii').rstrip('=').lower()


def _name_ok(label: str, value) -> str:
    if not isinstance(value, str) or not oz_spool.NAME_RE.match(value):
        raise Error(f'{label} must be 1..64 characters of [A-Za-z0-9_-]')
    return value


def subname(submission: str, tag: str) -> str:
    """A spool submission name derived from a producer submission and a round tag (at most 64 characters)."""
    name = f'{submission}-{tag}'
    return name if len(name) <= 64 else 's' + _b32(['sub', submission, tag])[:40] + '-' + tag[:20]


def apply_input_policy(text: str) -> tuple:
    """(resolved text, removed suffix): exactly one terminal CRLF, else one LF, is removed (D2)."""
    for suffix in ('\r\n', '\n'):
        if text.endswith(suffix):
            return text[:-len(suffix)], suffix
    return text, ''


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def child_env(*, model: str, effort: str, extra: dict | None = None, base=None) -> dict:
    """The explicit environment of one child process: the base environment (default a copy of os.environ, read only)
    without any OZ_BOOTSTRAP* variable, OZ_ENVELOPE_PATH, OZ_MODEL or OZ_EFFORT, then OZ_MODEL and OZ_EFFORT set
    explicitly, then `extra` (only the bootstrap child gets OZ_BOOTSTRAP_ATTEMPT and OZ_BOOTSTRAP_DIR). os.environ is
    never modified."""
    source = dict(os.environ if base is None else base)
    drop = ('OZ_ENVELOPE_PATH', 'OZ_MODEL', 'OZ_EFFORT')
    env = {k: v for k, v in source.items() if not k.upper().startswith('OZ_BOOTSTRAP') and k.upper() not in drop}
    env.update(PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    if model is not None:
        env['OZ_MODEL'] = model
    if effort is not None:
        env['OZ_EFFORT'] = effort
    for key, value in (extra or {}).items():
        env[key] = str(value)
    return env


def _shim():
    if str(EXAMPLES) not in sys.path:
        sys.path.insert(0, str(EXAMPLES))
    import bootstrap_shim
    return bootstrap_shim


# --------------------------------------------------------------------------------------------- one execution

def _ledger_calls(run: Path) -> list:
    """[{call_id, outcome, usage, elapsed_ms, jobs}] from a run's calls.jsonl, in first-seen order."""
    calls = {}
    file = run / 'calls.jsonl'
    for line in (file.read_text(encoding='utf-8').splitlines() if file.exists() else ()):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        entry = calls.setdefault(record.get('call_id'), {'call_id': record.get('call_id'), 'outcome': None,
                                                          'usage': None, 'elapsed_ms': None, 'jobs': []})
        if record.get('event') == 'call_start':
            entry['jobs'] = [m.get('inbox_job_id') for m in record.get('job_map') or [] if isinstance(m, dict)]
        else:
            raw = (record.get('usage') or {}).get('raw')
            entry.update(outcome=record.get('outcome'), usage=raw if isinstance(raw, dict) else None,
                         elapsed_ms=record.get('elapsed_ms'))
    return [c for c in calls.values() if c['call_id']]


def _job_calls(run: Path) -> dict:
    """job id -> physical call id of its latest candidate, from the run's inbox."""
    import sqlite3
    file = run / 'inbox.sqlite'
    found = {}
    if not file.exists():
        return found
    try:
        db = sqlite3.connect(f'file:{file.as_posix()}?mode=ro', uri=True, timeout=10)
        try:
            for job, call in db.execute('SELECT c.job, d.call_id FROM candidates c JOIN dispatches d ON '
                                        'd.receipt=c.receipt ORDER BY c.seq'):
                if call:
                    found[job] = call
        finally:
            db.close()
    except sqlite3.Error:
        return {}
    return found


def _error(outcome: dict) -> str:
    if outcome['status'] == 'failed':
        return f"{outcome.get('code')}: {outcome.get('message')}"
    detail = outcome.get('reason') or outcome['status']
    return detail + (f": {outcome['last_error']}" if outcome.get('last_error') else '')


def execute(spec: dict, adapter) -> dict:
    """Run one oz.do/1 request with at most spec["max_calls"] physical calls in total for its request id (calls already
    in the run's ledger count, so a re-dispatch resumes and never calls again). Returns a JSON-safe summary."""
    import oz_do
    from oz_workspace import Workspace
    root = Path(spec['workspace']).resolve()
    request = spec['request']
    space = Workspace(root)
    req = oz_do.normalize(request, allow=root, config=space.config)
    run = root / 'do' / req['request_id']
    before = {c['call_id'] for c in _ledger_calls(run)}
    left = [max(0, int(spec.get('max_calls', 1)) - len(before))]

    def admit(size):
        if left[0] <= 0:
            return {'reason': 'call_cap', 'detail': 'this request already used its one physical call'}
        left[0] -= 1
        return None

    result = oz_do.do(request, workspace=root, adapter=adapter, allow=root, admit=admit, route=spec.get('route'),
                      experimental_sizes=tuple(spec.get('experimental_sizes') or ()))
    run = root / result['run']['run_dir']
    calls = _ledger_calls(run)
    by_job = _job_calls(run)
    jobs = {}
    for mid, outcome in result['jobs'].items():
        entry = {'status': outcome['status'], 'call_id': by_job.get(mid)}
        if outcome['status'] == 'accepted':
            value = loads((root / outcome['value_file']).read_text(encoding='utf-8')) if 'value_file' in outcome \
                else outcome['value']
            entry['value_text'] = dumps(value, ensure_ascii=False, separators=(',', ':'))
            entry['memo'] = bool((outcome.get('evidence') or {}).get('memo_entry'))
        else:
            entry['error'] = _error(outcome)
        jobs[mid] = entry
    return {'schema': EXECUTION_SCHEMA, 'request_id': result['run']['request_id'], 'run_dir': result['run']['run_dir'],
            'status': result['status'], 'blocker': result['blocker'], 'jobs': jobs, 'calls': calls,
            'new_calls': [c['call_id'] for c in calls if c['call_id'] not in before]}


def _publish(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{os.getpid()}.{threading.get_ident()}.tmp')
    with open(temp, 'wb') as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


def _write_raw(evidence_dir: Path, raw: dict) -> dict:
    """Durably write the child's raw streams and exit evidence before anything is parsed; returns their hashes."""
    _publish(evidence_dir / 'stdout.bin', raw['stdout'])
    _publish(evidence_dir / 'stderr.bin', raw['stderr'])
    meta = {'exit_code': raw['exit_code'], 'timed_out': raw['timed_out'],
            'stdout_sha256': hashlib.sha256(raw['stdout']).hexdigest(),
            'stderr_sha256': hashlib.sha256(raw['stderr']).hexdigest()}
    _publish(evidence_dir / 'exit.json', json.dumps(meta).encode('utf-8'))
    return meta


CHILD_MARGIN = 120.0  # seconds a child may take beyond the request's call timeout (oz_do's own work, journaling)
DEFAULT_CALL_TIMEOUT = 300.0  # oz_do's default call_timeout_seconds


def child_timeout(limits: dict) -> float:
    """The child's wall timeout, tied to the request's call_timeout_seconds (council 3, Opus 7)."""
    return float((limits or {}).get('call_timeout_seconds', DEFAULT_CALL_TIMEOUT)) + CHILD_MARGIN


def _kill_tree(proc) -> None:
    """Kill the child and every process it started: taskkill /T on Windows, the child's own session elsewhere."""
    if os.name == 'nt':
        try:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)], capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


class ChildLauncher:
    """Each physical attempt is a child process `python oz_host.py --child SPEC` running one oz_do request with the
    adapter JSON file, under the explicit env the host built. The timeout is spec["child_timeout"] (the host ties it to
    call_timeout_seconds), else the constructor's, else oz_do's default call timeout plus CHILD_MARGIN. On timeout the
    whole process tree is killed, so a CLI grandchild cannot keep spending."""

    def __init__(self, adapter, *, timeout: float | None = None, python: str | None = None):
        self.adapter = Path(adapter).resolve()
        self.timeout, self.python = timeout, python or sys.executable

    def __call__(self, spec: dict, env: dict, evidence_dir: Path) -> tuple:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        out = evidence_dir / 'execution.json'
        timeout = float(spec.get('child_timeout') or self.timeout or DEFAULT_CALL_TIMEOUT + CHILD_MARGIN)
        spec = dict(spec, adapter=str(self.adapter), out=str(out))
        spec_file = evidence_dir / 'spec.json'
        _publish(spec_file, json.dumps(spec, ensure_ascii=False).encode('utf-8'))
        options = dict(env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                       cwd=str(HOST_FILE.parent))
        if os.name == 'nt':
            options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options['start_new_session'] = True
        try:
            proc = subprocess.Popen([self.python, str(HOST_FILE), '--child', str(spec_file)], **options)
        except OSError as exc:
            raise oz_spool.LaunchNotStarted(f'cannot start the child process: {exc}') from None
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            raw = {'exit_code': proc.returncode, 'timed_out': False, 'stdout': stdout, 'stderr': stderr}
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                stdout, stderr = b'', b''
            raw = {'exit_code': None, 'timed_out': True, 'stdout': stdout or b'', 'stderr': stderr or b'',
                   'tree_killed': True}
        meta = _write_raw(evidence_dir, raw)
        execution = None
        if raw['exit_code'] == 0 and out.exists():
            execution = json.loads(out.read_text(encoding='utf-8'))
        return execution, meta


class SlotPool:
    """Experiment-wide physical call slots (council 3, B9): `slots` OS file locks in one directory, shared by every
    host, thread and process of the experiment. acquire() blocks until one lock is free; a dead process releases its
    lock automatically. The slot count is frozen in slots.json at first use."""

    def __init__(self, directory, slots: int):
        if type(slots) is not int or not 1 <= slots <= 16:
            raise Error('the experiment-wide slot count is 1..16')
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        meta = self.dir / 'slots.json'
        try:
            fd = os.open(str(meta), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(json.dumps({'slots': slots}))
        except FileExistsError:
            pass
        frozen = json.loads(meta.read_text(encoding='utf-8'))['slots']
        if frozen != slots:
            raise Error(f'the experiment-wide slot count is frozen at {frozen}, not {slots}')
        self.slots = slots

    def acquire(self, poll: float = 0.02):
        while True:
            for k in range(self.slots):
                try:
                    return oz_spool.HostLock(self.dir / f'slot{k}.lock').acquire()
                except oz_spool.HostLocked:
                    continue
            time.sleep(poll)

    @staticmethod
    def release(lock) -> None:
        lock.release()


class InProcessLauncher:
    """For callable (fake) adapters: the same execute() in this process. The adapter sees the child env only through
    bind_env(env), or, for a bootstrap_shim.CallableShim, a CallableShim rebuilt with env=env."""

    def __init__(self, adapter):
        self.adapter = adapter

    def bind(self, env: dict):
        adapter = self.adapter
        if hasattr(adapter, 'bind_env'):
            return adapter.bind_env(env)
        if getattr(adapter, 'bootstrap_shim', False) is True and hasattr(adapter, 'real'):
            return type(adapter)(adapter.real, env=env)
        return adapter

    def __call__(self, spec: dict, env: dict, evidence_dir: Path) -> tuple:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        try:
            execution = execute(spec, self.bind(env))
            raw = {'exit_code': 0, 'timed_out': False, 'stdout': json.dumps(execution).encode('utf-8'), 'stderr': b''}
        except Exception:
            execution = None
            raw = {'exit_code': 1, 'timed_out': False, 'stdout': b'',
                   'stderr': traceback.format_exc().encode('utf-8', 'replace')}
        return execution, _write_raw(evidence_dir, raw)


def child_main(spec_file: str) -> int:
    spec = json.loads(Path(spec_file).read_text(encoding='utf-8'))
    try:
        execution = execute(spec, spec['adapter'])
    except Exception:
        sys.stderr.write(traceback.format_exc())
        return 1
    _publish(Path(spec['out']), json.dumps(execution, ensure_ascii=False).encode('utf-8'))
    sys.stdout.write(json.dumps({'ok': True, 'request_id': execution['request_id']}))
    return 0


# ----------------------------------------------------------------------------------------------------- stores

def _db(path: Path, schema: str):
    import sqlite3
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    with rp._Tx(db):
        for statement in schema.split(';\n'):
            if statement.strip():
                db.execute(statement)
    return db


def _keep(table: str, what: str = 'rows') -> str:
    return (f"CREATE TRIGGER IF NOT EXISTS {table}_immutable BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} {what} are immutable'); END;\n"
            f"CREATE TRIGGER IF NOT EXISTS {table}_keep BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} {what} are kept'); END;\n")


LEDGER_TABLES = '''
CREATE TABLE IF NOT EXISTS intake(
    producer TEXT NOT NULL, submission TEXT NOT NULL, wave TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
    submitted_at REAL NOT NULL, mono REAL, session TEXT, PRIMARY KEY(producer, submission));
CREATE TABLE IF NOT EXISTS attempts(
    attempt_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, batch_id TEXT NOT NULL, arm TEXT NOT NULL,
    backend TEXT NOT NULL, workload TEXT NOT NULL, wave TEXT NOT NULL, round TEXT NOT NULL, group_kind TEXT NOT NULL,
    kinds TEXT NOT NULL, records TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('launched','captured','failed',
    'refused')), launches INTEGER NOT NULL, bucket TEXT, exit_code INTEGER, timed_out INTEGER, stdout_sha256 TEXT,
    stderr_sha256 TEXT, evidence_dir TEXT, call_ids TEXT, elapsed REAL, started_at REAL, ended_at REAL, error TEXT,
    outcome TEXT CHECK(outcome IS NULL OR outcome IN ('unlaunched','no_call','physical','unresolved')),
    mono_start REAL, mono_end REAL, session TEXT);
CREATE TRIGGER IF NOT EXISTS attempts_first_evidence BEFORE UPDATE OF exit_code, timed_out, stdout_sha256,
    stderr_sha256, evidence_dir, elapsed, started_at, ended_at, mono_start, mono_end ON attempts
    WHEN OLD.stdout_sha256 IS NOT NULL OR OLD.state = 'refused'
    BEGIN SELECT RAISE(ABORT, 'the first evidence and elapsed of an attempt are immutable'); END;
CREATE TRIGGER IF NOT EXISTS attempts_outcome BEFORE UPDATE OF outcome ON attempts
    WHEN OLD.outcome IN ('unlaunched','no_call','physical') AND NEW.outcome IS NOT OLD.outcome
    BEGIN SELECT RAISE(ABORT, 'a resolved attempt outcome never changes'); END;
CREATE TRIGGER IF NOT EXISTS attempts_keep BEFORE DELETE ON attempts BEGIN SELECT RAISE(ABORT, 'attempts are kept'); END;
CREATE TABLE IF NOT EXISTS events(
    seq INTEGER PRIMARY KEY, attempt_id TEXT NOT NULL, event TEXT NOT NULL, at REAL NOT NULL, mono REAL,
    session TEXT, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calls(
    call_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, request_id TEXT NOT NULL, outcome TEXT, usage TEXT,
    usage_known INTEGER NOT NULL, input_tokens INTEGER, cached_input_tokens INTEGER, cache_creation_input_tokens INTEGER,
    output_tokens INTEGER, reasoning_output_tokens INTEGER, elapsed_ms INTEGER, jobs TEXT);
CREATE TABLE IF NOT EXISTS allocations(
    seq INTEGER PRIMARY KEY, arm TEXT NOT NULL, backend TEXT NOT NULL, workload TEXT NOT NULL, wave TEXT NOT NULL,
    attempt_id TEXT NOT NULL, call_id TEXT NOT NULL, job TEXT NOT NULL, original TEXT NOT NULL, producer TEXT NOT NULL,
    dataset_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('bootstrap','fallback','audit','ordinary')),
    share REAL NOT NULL, basis TEXT NOT NULL CHECK(basis IN ('physical','imported')), UNIQUE(call_id, job, basis));
CREATE TABLE IF NOT EXISTS plan(
    wave TEXT NOT NULL, round TEXT NOT NULL, item_id TEXT NOT NULL, seq INTEGER NOT NULL, kind TEXT NOT NULL,
    pool TEXT NOT NULL, original TEXT NOT NULL, producer TEXT NOT NULL, submission TEXT NOT NULL,
    spool_sub TEXT NOT NULL, delivery TEXT NOT NULL, key TEXT NOT NULL, op TEXT NOT NULL, dataset_id TEXT NOT NULL,
    text_sha256 TEXT NOT NULL, group_kind TEXT NOT NULL, extra TEXT NOT NULL, at REAL NOT NULL,
    PRIMARY KEY(wave, round, item_id));
CREATE TABLE IF NOT EXISTS authority(
    seq INTEGER PRIMARY KEY, job TEXT NOT NULL, generation INTEGER NOT NULL, wave TEXT NOT NULL, round TEXT NOT NULL,
    item_id TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS deliveries(
    job TEXT PRIMARY KEY, wave TEXT NOT NULL, producer TEXT NOT NULL, submission TEXT NOT NULL, row TEXT NOT NULL,
    sha256 TEXT NOT NULL, at REAL NOT NULL, mono REAL, session TEXT);
CREATE TABLE IF NOT EXISTS violations(
    seq INTEGER PRIMARY KEY, wave TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('efficiency_invalid','incomplete')),
    reason TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS timeline(
    seq INTEGER PRIMARY KEY, wave TEXT NOT NULL, phase TEXT NOT NULL, edge TEXT NOT NULL CHECK(edge IN ('start','end')),
    at REAL NOT NULL, mono REAL, session TEXT);
''' + ''.join(_keep(t) for t in ('events', 'calls', 'allocations', 'plan', 'authority', 'deliveries', 'violations',
                                 'timeline'))


def _usage_columns(usage) -> tuple:
    known = isinstance(usage, dict) and {'input_tokens', 'output_tokens'} <= set(usage)
    return (1 if known else 0, *[(usage.get(k) if isinstance(usage, dict) else None) for k in USAGE_FIELDS])


def _span(a, b) -> float | None:
    """Seconds from stamp a to stamp b ({at, mono, session}): monotonic within one process session, else wall."""
    if a is None or b is None:
        return None
    if a.get('session') and a.get('session') == b.get('session') and a.get('mono') is not None \
            and b.get('mono') is not None:
        return b['mono'] - a['mono']
    return b['at'] - a['at']


class Ledger:
    """The host's attempt, event, call, allocation, plan, authority, delivery, violation and timeline ledger."""

    def __init__(self, path):
        self.db = _db(Path(path), LEDGER_TABLES)
        self.lock = threading.RLock()

    def close(self):
        self.db.close()

    def tx(self):
        return rp._Tx(self.db)

    # intake
    def add_intake(self, producer, submission, wave, jobs, at, mono=None, session=None) -> None:
        payload = canonical({'wave': wave, 'jobs': jobs}).decode('utf-8')
        with self.lock, self.tx() as db:
            row = db.execute('SELECT sha256 FROM intake WHERE producer=? AND submission=?',
                             (producer, submission)).fetchone()
            if row is not None:
                if row[0] != _sha(payload):
                    raise oz_spool.SubmissionConflict(f'submission {producer}/{submission} exists with another payload')
                return
            db.execute('INSERT INTO intake VALUES (?,?,?,?,?,?,?,?)', (producer, submission, wave, payload,
                                                                      _sha(payload), at, mono, session))

    def intake(self, wave) -> list:
        return [dict(producer=r['producer'], submission=r['submission'], submitted_at=r['submitted_at'],
                     stamp={'at': r['submitted_at'], 'mono': r['mono'], 'session': r['session']},
                     jobs=json.loads(r['payload'])['jobs'])
                for r in self.db.execute('SELECT * FROM intake WHERE wave=? ORDER BY producer, submission', (wave,))]

    def waves(self) -> list:
        return [r[0] for r in self.db.execute('SELECT DISTINCT wave FROM intake ORDER BY wave')]

    # events
    def _event(self, db, attempt_id, event, data, at, mono=None, session=None) -> None:
        db.execute('INSERT INTO events(attempt_id, event, at, mono, session, data) VALUES (?,?,?,?,?,?)',
                   (attempt_id, event, at, mono, session, json.dumps(data, sort_keys=True, default=str)))

    def event(self, attempt_id, event, data, at, mono=None, session=None) -> None:
        with self.lock, self.tx() as db:
            self._event(db, attempt_id, event, data, at, mono, session)

    def events(self, attempt_id=None) -> list:
        rows = (self.db.execute('SELECT * FROM events ORDER BY seq') if attempt_id is None else
                self.db.execute('SELECT * FROM events WHERE attempt_id=? ORDER BY seq', (attempt_id,)))
        return [dict(r, data=json.loads(r['data'])) for r in rows]

    # attempts and calls
    def launched(self, *, attempt_id, request_id, batch_id, arm, backend, workload, wave, round_, group_kind, kinds,
                 records, bucket, evidence_dir, at, mono=None, session=None) -> None:
        with self.lock, self.tx() as db:
            row = db.execute('SELECT launches FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
            if row is None:
                db.execute("INSERT INTO attempts(attempt_id, request_id, batch_id, arm, backend, workload, wave, round, "
                           "group_kind, kinds, records, state, launches, bucket, evidence_dir, started_at, mono_start, "
                           "session) VALUES (?,?,?,?,?,?,?,?,?,?,?,'launched',1,?,?,?,?,?)",
                           (attempt_id, request_id, batch_id, arm, backend, workload, wave, round_, group_kind,
                            json.dumps(kinds), json.dumps(records), bucket, str(evidence_dir), at, mono, session))
            else:
                db.execute("UPDATE attempts SET launches=launches+1, state='launched' WHERE attempt_id=?",
                           (attempt_id,))
            self._event(db, attempt_id, 'launched', {'bucket': bucket, 'records': len(records)}, at, mono, session)

    def refused(self, *, attempt_id, request_id, batch_id, arm, backend, workload, wave, round_, group_kind, kinds,
                records, at, error, mono=None, session=None) -> None:
        with self.lock, self.tx() as db:
            db.execute("INSERT OR IGNORE INTO attempts(attempt_id, request_id, batch_id, arm, backend, workload, wave, "
                       "round, group_kind, kinds, records, state, launches, started_at, ended_at, error, outcome, "
                       "mono_start, mono_end, session) VALUES (?,?,?,?,?,?,?,?,?,?,?,'refused',0,?,?,?,'unlaunched',"
                       "?,?,?)",
                       (attempt_id, request_id, batch_id, arm, backend, workload, wave, round_, group_kind,
                        json.dumps(kinds), json.dumps(records), at, at, error, mono, mono, session))
            # An attempt whose earlier launch never started (LaunchNotStarted) and that is now refused before launch.
            db.execute("UPDATE attempts SET state='refused', outcome='unlaunched', error=? WHERE attempt_id=? AND "
                       "state='launched' AND stdout_sha256 IS NULL AND outcome IS NULL", (error, attempt_id))
            self._event(db, attempt_id, 'refused', {'error': error}, at, mono, session)

    @staticmethod
    def _call_values(c, attempt_id, request_id) -> tuple:
        return (c['call_id'], attempt_id, request_id, c.get('outcome'),
                json.dumps(c['usage'], sort_keys=True) if c.get('usage') is not None else None,
                *_usage_columns(c.get('usage')), c.get('elapsed_ms'),
                json.dumps(c['jobs']) if c.get('jobs') is not None else None)

    def _attribute(self, db, attempt_id, request_id, core_calls) -> list:
        """Insert the core-ledger calls of this request not yet in the ledger, attributed to this attempt. A call
        already recorded with complete usage and different content is a hard error; one recorded incomplete (usage
        unknown) stays as first recorded and the later observation becomes an event."""
        mine = []
        for c in core_calls or []:
            values = self._call_values(c, attempt_id, request_id)
            row = db.execute('SELECT * FROM calls WHERE call_id=?', (c['call_id'],)).fetchone()
            if row is None:
                db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', values)
                mine.append(c['call_id'])
                continue
            if row['request_id'] != request_id:
                raise Error(f"call {c['call_id']} is recorded under request {row['request_id']}, not {request_id}")
            if row['attempt_id'] == attempt_id:
                mine.append(c['call_id'])
            if tuple(row)[3:] != values[3:]:
                if row['usage_known'] and values[5]:
                    raise Error(f"conflicting duplicate of call {c['call_id']}: a complete call record differs")
                self._event(db, row['attempt_id'], 'call_observation', {'call_id': c['call_id'], 'later': c},
                            time.time())
        return mine

    def _outcome(self, db, attempt_id, outcome) -> None:
        db.execute("UPDATE attempts SET outcome=? WHERE attempt_id=? AND (outcome IS NULL OR outcome='unresolved')",
                   (outcome, attempt_id))

    def _call_ids(self, db, attempt_id) -> list:
        return [r[0] for r in db.execute('SELECT call_id FROM calls WHERE attempt_id=? ORDER BY rowid', (attempt_id,))]

    def finished(self, attempt_id, *, meta, execution, core_calls, elapsed, at, mono=None, session=None,
                 error=None) -> list:
        """The first capture of an attempt: its raw evidence and elapsed (written once), its core-ledger calls and its
        outcome. Returns the call ids attributed to it."""
        with self.lock, self.tx() as db:
            request_id = db.execute('SELECT request_id FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()[0]
            db.execute('UPDATE attempts SET state=?, exit_code=?, timed_out=?, stdout_sha256=?, stderr_sha256=?, '
                       'elapsed=?, ended_at=?, mono_end=?, error=? WHERE attempt_id=? AND stdout_sha256 IS NULL',
                       ('captured' if execution is not None else 'failed', meta['exit_code'], int(meta['timed_out']),
                        meta['stdout_sha256'], meta['stderr_sha256'], elapsed, at, mono, error, attempt_id))
            self._attribute(db, attempt_id, request_id, core_calls)
            calls = self._call_ids(db, attempt_id)
            db.execute('UPDATE attempts SET call_ids=? WHERE attempt_id=?', (json.dumps(calls), attempt_id))
            self._outcome(db, attempt_id, 'physical' if calls else 'no_call' if execution is not None else
                          'unresolved')
            self._event(db, attempt_id, 'captured' if execution is not None else 'failed',
                        {'meta': meta, 'core_calls': [c['call_id'] for c in core_calls or []],
                         'capture_calls': [c['call_id'] for c in (execution or {}).get('calls') or []],
                         'error': error}, at, mono, session)
            return calls

    def reconciled(self, attempt_id, *, meta, execution, core_calls, evidence_dir, at, mono=None,
                   session=None) -> list:
        """A reconciliation child's result as its own event (its evidence never replaces the first); calls it reveals
        are attributed to the attempt and the outcome resolved where the evidence allows."""
        with self.lock, self.tx() as db:
            row = db.execute('SELECT request_id FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
            if row is None:
                raise Error(f'no ledger attempt {attempt_id} to reconcile')
            self._attribute(db, attempt_id, row[0], core_calls)
            calls = self._call_ids(db, attempt_id)
            db.execute('UPDATE attempts SET call_ids=? WHERE attempt_id=?', (json.dumps(calls), attempt_id))
            if calls:
                self._outcome(db, attempt_id, 'physical')
            elif execution is not None:
                self._outcome(db, attempt_id, 'no_call')
            self._event(db, attempt_id, 'reconciled' if execution is not None else 'reconcile_failed',
                        {'meta': meta, 'evidence_dir': str(evidence_dir),
                         'core_calls': [c['call_id'] for c in core_calls or []]}, at, mono, session)
            return calls

    def attempt(self, attempt_id) -> dict | None:
        row = self.db.execute('SELECT * FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        for k in ('kinds', 'records', 'call_ids'):
            out[k] = json.loads(out[k]) if out[k] else ([] if k != 'kinds' else {})
        out['calls'] = [self.call(c) for c in out['call_ids']]
        return out

    def attempts(self, wave=None) -> list:
        rows = (self.db.execute('SELECT attempt_id FROM attempts ORDER BY started_at, rowid') if wave is None else
                self.db.execute('SELECT attempt_id FROM attempts WHERE wave=? ORDER BY started_at, rowid', (wave,)))
        return [self.attempt(r[0]) for r in rows.fetchall()]

    def call(self, call_id) -> dict | None:
        row = self.db.execute('SELECT * FROM calls WHERE call_id=?', (call_id,)).fetchone()
        if row is None:
            return None
        return dict(row, usage=json.loads(row['usage']) if row['usage'] else None,
                    jobs=json.loads(row['jobs']) if row['jobs'] else None)

    # allocations
    def allocate(self, rows) -> None:
        """Insert allocation rows; an identical duplicate is a no-op, a conflicting one a hard error (B6)."""
        keys = ('arm', 'backend', 'workload', 'wave', 'attempt_id', 'call_id', 'job', 'original', 'producer',
                'dataset_id', 'kind', 'share', 'basis')
        with self.lock, self.tx() as db:
            for r in rows:
                have = db.execute('SELECT * FROM allocations WHERE call_id=? AND job=? AND basis=?',
                                  (r['call_id'], r['job'], r['basis'])).fetchone()
                if have is not None:
                    if any(have[k] != r[k] for k in keys if k != 'share') or abs(have['share'] - r['share']) > 1e-12:
                        raise Error(f"conflicting duplicate allocation of call {r['call_id']} to {r['job']}")
                    continue
                db.execute('INSERT INTO allocations(' + ', '.join(keys) + ') VALUES (' + ','.join('?' * len(keys))
                           + ')', tuple(r[k] for k in keys))

    def allocations(self, wave=None) -> list:
        rows = (self.db.execute('SELECT * FROM allocations ORDER BY seq') if wave is None else
                self.db.execute('SELECT * FROM allocations WHERE wave=? ORDER BY seq', (wave,)))
        return [dict(r) for r in rows]

    # plan and authority
    PLAN_KEYS = ('wave', 'round', 'item_id', 'seq', 'kind', 'pool', 'original', 'producer', 'submission', 'spool_sub',
                 'delivery', 'key', 'op', 'dataset_id', 'text_sha256', 'group_kind', 'extra')

    def add_plan(self, rows, at) -> None:
        """Persist one round's plan before dispatch; identical rows are a no-op, a different row a hard error."""
        with self.lock, self.tx() as db:
            for r in rows:
                have = db.execute('SELECT * FROM plan WHERE wave=? AND round=? AND item_id=?',
                                  (r['wave'], r['round'], r['item_id'])).fetchone()
                if have is not None:
                    if any(have[k] != r[k] for k in self.PLAN_KEYS):
                        raise Error(f"plan item {r['item_id']} of {r['wave']}/{r['round']} exists differently")
                    continue
                db.execute('INSERT INTO plan(' + ', '.join(self.PLAN_KEYS) + ', at) VALUES ('
                           + ','.join('?' * (len(self.PLAN_KEYS) + 1)) + ')',
                           (*[r[k] for k in self.PLAN_KEYS], at))

    def plan(self, wave=None, round_=None) -> list:
        if wave is None:
            rows = self.db.execute('SELECT * FROM plan ORDER BY wave, round, seq')
        elif round_ is None:
            rows = self.db.execute('SELECT * FROM plan WHERE wave=? ORDER BY round, seq', (wave,))
        else:
            rows = self.db.execute('SELECT * FROM plan WHERE wave=? AND round=? ORDER BY seq', (wave, round_))
        return [dict(r) for r in rows]

    def authorize(self, rows, at) -> None:
        with self.lock, self.tx() as db:
            for r in rows:
                db.execute('INSERT INTO authority(job, generation, wave, round, item_id, at) VALUES (?,?,?,?,?,?)',
                           (r['job'], r['generation'], r['wave'], r['round'], r['item_id'], at))

    def authority(self, job=None) -> list:
        rows = (self.db.execute('SELECT * FROM authority ORDER BY seq') if job is None else
                self.db.execute('SELECT * FROM authority WHERE job=? ORDER BY seq', (job,)))
        return [dict(r) for r in rows]

    # deliveries
    STABLE = ('status', 'source', 'value_text', 'error', 'phase')

    def deliver(self, job, wave, row, stamp) -> tuple:
        """(row as first delivered, conflict): the first terminal delivery of a job is kept with its time; a later
        delivery with a different payload is a conflict (recorded by the caller), never a replacement."""
        text = json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)
        with self.lock, self.tx() as db:
            have = db.execute('SELECT * FROM deliveries WHERE job=?', (job,)).fetchone()
            if have is None:
                db.execute('INSERT INTO deliveries VALUES (?,?,?,?,?,?,?,?,?)',
                           (job, wave, row['producer'], row['submission'], text, _sha(text), stamp['at'],
                            stamp.get('mono'), stamp.get('session')))
                return row, False
        first = json.loads(have['row'])
        return first, any(first.get(k) != row.get(k) for k in self.STABLE)

    def deliveries(self, wave) -> list:
        return [dict(r, row=json.loads(r['row']))
                for r in self.db.execute('SELECT * FROM deliveries WHERE wave=? ORDER BY rowid', (wave,))]

    # violations and timeline
    def violate(self, wave, kind, reason, at) -> None:
        with self.lock, self.tx() as db:
            db.execute('INSERT INTO violations(wave, kind, reason, at) VALUES (?,?,?,?)', (wave, kind, reason, at))

    def violations(self, wave) -> dict:
        out = {'efficiency_invalid': [], 'incomplete': []}
        for r in self.db.execute('SELECT kind, reason FROM violations WHERE wave=? ORDER BY seq', (wave,)):
            if r['reason'] not in out[r['kind']]:
                out[r['kind']].append(r['reason'])
        return out

    def phase(self, wave, phase, edge, at, mono, session) -> None:
        with self.lock, self.tx() as db:
            db.execute('INSERT INTO timeline(wave, phase, edge, at, mono, session) VALUES (?,?,?,?,?,?)',
                       (wave, phase, edge, at, mono, session))

    def timeline(self, wave) -> list:
        return [dict(r) for r in self.db.execute('SELECT * FROM timeline WHERE wave=? ORDER BY seq', (wave,))]

    def phase_seconds(self, wave) -> dict:
        """{phase: seconds} summed over every closed start..end span (monotonic within a session)."""
        out, open_ = {}, {}
        for r in self.timeline(wave):
            key = (r['phase'], r['session'])
            if r['edge'] == 'start':
                open_[key] = r
            elif key in open_:
                out[r['phase']] = out.get(r['phase'], 0.0) + (_span(open_.pop(key), r) or 0.0)
        return {k: round(v, 6) for k, v in out.items()}


BUDGET_TABLES = '''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reservations(
    key TEXT PRIMARY KEY, backend TEXT NOT NULL, bucket TEXT NOT NULL, arm TEXT NOT NULL, kind TEXT NOT NULL,
    at REAL NOT NULL);
CREATE TRIGGER IF NOT EXISTS reservations_keep BEFORE DELETE ON reservations
    BEGIN SELECT RAISE(ABORT, 'reservations are kept'); END
'''


class Budget:
    """Frozen per-backend call caps by bucket plus a global cap, shared by every host of an experiment. caps None and
    nothing frozen yet means unlimited (single-user oz map); once frozen, caps never change. A pilot host refuses an
    unfrozen budget (check_pilot)."""

    def __init__(self, path, *, caps: dict | None = None, global_cap: int | None = None, clock=time.time):
        self.db = _db(Path(path), BUDGET_TABLES)
        self.clock = clock
        frozen = {'caps': caps, 'global_cap': global_cap}
        with rp._Tx(self.db) as db:
            row = db.execute("SELECT value FROM meta WHERE key='caps'").fetchone()
            if row is None and caps is not None:
                db.execute("INSERT INTO meta VALUES ('caps', ?)", (json.dumps(frozen, sort_keys=True),))
            elif row is not None and caps is not None and json.loads(row[0]) != json.loads(json.dumps(frozen)):
                raise Error('the frozen budget caps differ from these; caps are frozen before the first call')
        row = self.db.execute("SELECT value FROM meta WHERE key='caps'").fetchone()
        self.frozen = json.loads(row[0]) if row else None
        self.lock = threading.Lock()

    def close(self):
        self.db.close()

    def reserve(self, key: str, *, backend: str, buckets, arm: str, kind: str) -> str | None:
        """The bucket that holds this reservation (idempotent per key), or None when every bucket is exhausted."""
        with self.lock, rp._Tx(self.db) as db:
            row = db.execute('SELECT bucket FROM reservations WHERE key=?', (key,)).fetchone()
            if row is not None:
                return row[0]
            chosen = None
            if self.frozen is None:
                chosen = buckets[0]
            else:
                total = db.execute('SELECT COUNT(*) FROM reservations').fetchone()[0]
                cap = self.frozen['global_cap']
                if cap is None or total < cap:
                    for bucket in buckets:
                        limit = (self.frozen['caps'].get(backend) or {}).get(bucket, 0)
                        used = db.execute('SELECT COUNT(*) FROM reservations WHERE backend=? AND bucket=?',
                                          (backend, bucket)).fetchone()[0]
                        if used < limit:
                            chosen = bucket
                            break
            if chosen is not None:
                db.execute('INSERT INTO reservations VALUES (?,?,?,?,?,?)', (key, backend, chosen, arm, kind,
                                                                             self.clock()))
            return chosen

    def reserved(self, keys) -> set:
        """The keys among these that hold a reservation."""
        keys = list(keys)
        found = set()
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            found |= {r[0] for r in self.db.execute(
                'SELECT key FROM reservations WHERE key IN (' + ','.join('?' * len(chunk)) + ')', chunk)}
        return found

    def usage(self) -> dict:
        used = {}
        for r in self.db.execute('SELECT backend, bucket, COUNT(*) FROM reservations GROUP BY backend, bucket'):
            used.setdefault(r[0], {})[r[1]] = r[2]
        total = sum(n for b in used.values() for n in b.values())
        return {'frozen': self.frozen, 'used': used, 'total': total}


# ------------------------------------------------------------------------------------------ pilot configuration

PILOT_SCHEMA = 'oz.host.pilot/1'
PILOT_KEYS = ('schema', 'mode', 'global_cap', 'caps', 'slots', 'max_records', 'max_wait', 'intake', 'limits',
              'usage_semantics', 'routes')
PILOT_LIMITS = ('call_timeout_seconds', 'deadline_seconds', 'max_input_tokens')


def check_pilot(config, *, backend, budget, slot_pool, slots, max_records, max_wait, identity, launcher, limits,
                route_check) -> None:
    """Refuse (Error) a pilot host whose frozen configuration is missing or does not match what it would run with
    (council 3, B9): caps and global cap frozen in the budget, the experiment-wide slot pool, batch limits, call
    timeouts, intake shape, the backend's frozen route (the whole oz_route.build result) and, for a live run, a child
    launcher with the launch-time route check."""
    problems = []
    if not isinstance(config, dict) or config.get('schema') != PILOT_SCHEMA:
        raise Error(f'pilot launch refused: the frozen configuration must be a {PILOT_SCHEMA} object')
    missing = [k for k in PILOT_KEYS if k not in config]
    if missing:
        raise Error('pilot launch refused: the frozen configuration lacks ' + ', '.join(missing))
    if config['mode'] not in ('live', 'dry'):
        problems.append('mode is live or dry')
    caps, cap = config['caps'], config['global_cap']
    if type(cap) is not int or not isinstance(caps, dict) or any(
            not isinstance(b, dict) or any(type(n) is not int or n < 0 for n in b.values()) for b in caps.values()):
        problems.append('caps and global_cap must be integers per backend and bucket')
    else:
        if sum(n for b in caps.values() for n in b.values()) > cap:
            problems.append('the bucket allocations exceed the global cap')
        if backend not in caps:
            problems.append(f'no frozen caps for backend {backend}')
    if budget is None or budget.frozen != json.loads(json.dumps({'caps': caps, 'global_cap': cap})):
        problems.append('the experiment budget is not frozen with exactly these caps and global cap')
    if slot_pool is None or getattr(slot_pool, 'slots', None) != config['slots']:
        problems.append(f"the experiment-wide slot pool of {config['slots']} physical slots is missing")
    if slots != config['slots']:
        problems.append(f"host slots {slots} differ from the frozen {config['slots']}")
    if max_records != config['max_records'] or max_wait != config['max_wait']:
        problems.append('max_records or max_wait differ from the frozen values')
    intake = config['intake']
    if not isinstance(intake, dict) or set(intake) != {'producers', 'per_producer'}:
        problems.append('intake must be {producers, per_producer}')
    frozen_limits = config['limits']
    if not isinstance(frozen_limits, dict) or any(k not in frozen_limits for k in PILOT_LIMITS):
        problems.append('limits must freeze ' + ', '.join(PILOT_LIMITS))
    elif dict(limits) != frozen_limits:
        problems.append('the host limits differ from the frozen limits')
    route = (config['routes'] or {}).get(backend) if isinstance(config['routes'], dict) else None
    if not isinstance(route, dict) or route.get('worker_hash') != identity.get('worker_hash'):
        problems.append(f'the frozen route of {backend} (oz_route.build result) is missing or names another worker')
    if not isinstance(config['usage_semantics'], str) or not config['usage_semantics']:
        problems.append('usage_semantics must be declared')
    if config['mode'] == 'live':
        if not isinstance(launcher, ChildLauncher):
            problems.append('a live pilot launches child processes only')
        if route_check is None:
            problems.append('a live pilot needs the launch-time route check')
    if problems:
        raise Error('pilot launch refused: ' + '; '.join(problems))

# --------------------------------------------------------------------------------------------------- the host

TERMINAL = ('accepted', 'failed')
SETTLING = ('ordinary', 'fallback', 'bootstrap')


class ArmHost:
    """One arm (A, B or C) on one backend and workload. See the module docstring."""

    def __init__(self, *, arm, backend, experiment_dir, launcher, op, op_text, model, effort, identity,
                 workload=None, goal=GOAL, checks=None, registry=None, seed=None, budget=None,
                 producers_expected=rp.BOOTSTRAP_PRODUCERS, bootstrap_per_producer=rp.BOOTSTRAP_PER_PRODUCER,
                 slots=4, max_records=64, max_wait=1.0, rule_delivery='after_audits', audit_retry=True,
                 allow_experimental=False, experimental_sizes=(), limits=None, do_workspace=None, rule_store=None,
                 wall=time.time, clock=time.monotonic, bootstrap_wait=1800.0, hooks=None, owner=None, base_env=None,
                 expected_intake=None, slot_pool=None, route_check=None, pilot=None, usage_semantics='unverified'):
        from oz_accept import pin
        if arm not in ARMS:
            raise Error('arm must be A, B or C')
        if rule_delivery not in ('after_audits', 'immediate'):
            raise Error('rule_delivery is after_audits or immediate')
        if not isinstance(identity, dict) or not isinstance(identity.get('worker_hash'), str):
            raise Error('the host needs the full worker identity (route and worker_hash, D7)')
        if not 1 <= max_records <= 64 or not 1 <= slots <= 16:
            raise Error('max_records is 1..64 and slots 1..16')
        self.arm, self.backend = arm, _name_ok('backend', backend)
        # One operation (op, op_text), or several in one workload (op = {op id: op text}, op_text None).
        if isinstance(op, dict):
            if op_text is not None or not op or any(not isinstance(k, str) or not k or not isinstance(v, str)
                                                    for k, v in op.items()):
                raise Error('op is an operation id with op_text, or a nonempty {op id: op text} map without op_text')
            ops = dict(op)
        else:
            ops = {op: op_text}
        self.ops = ops
        self.multi = len(ops) > 1
        if not self.multi:
            [(op, op_text)] = ops.items()
        else:
            op = op_text = None
        self.launcher, self.op, self.op_text, self.goal = launcher, op, op_text, goal
        self.model, self.effort, self.identity = model, effort, identity
        self.worker = identity['worker_hash']
        self.check_specs = list(checks) if checks else None
        self.pinned = list(pin(self.check_specs)) if self.check_specs else []
        self.registry, self.seed = registry, seed
        self.producers_expected, self.per_producer = producers_expected, bootstrap_per_producer
        self.rule_delivery, self.audit_retry = rule_delivery, audit_retry
        self.allow_experimental, self.experimental_sizes = allow_experimental, tuple(experimental_sizes)
        self.limits = dict(limits or {})
        self.max_records = max_records
        self.wall, self.clock, self.bootstrap_wait = wall, clock, bootstrap_wait
        self.hooks = dict(hooks or {})
        self.base_env = base_env
        self.slot_pool, self.route_check, self.pilot = slot_pool, route_check, pilot
        self.usage_semantics = usage_semantics
        self.expected_intake = expected_intake if pilot is None else pilot.get('intake')
        self.session = os.urandom(8).hex()
        self.map_contract = (digest({'ops': ops, 'goal': goal, 'checks': self.pinned, 'profile': PROFILE})
                             if self.multi else
                             digest({'op': op, 'op_text': op_text, 'goal': goal, 'checks': self.pinned,
                                     'profile': PROFILE}))
        self.learners = {}
        self.experiment_dir = Path(experiment_dir).resolve()
        self.learner = self.store = self.scheduler = self.spool = self.ledger = self.budget = None
        self._owner_arg = owner
        self._own_budget = False
        self._groups, self._items, self._rows, self._gen = {}, {}, {}, {}
        self._wave, self._wave_jobs, self._jobs_cache = None, {}, {}
        self.experiment = rp.ExperimentStore(self.experiment_dir / 'experiment.sqlite', clock=wall)
        try:
            self._setup(arm, backend, workload, registry, seed, op, rule_store, do_workspace, budget, slots,
                        max_records, max_wait, clock, wall)
            if pilot is not None:
                check_pilot(pilot, backend=self.backend, budget=self.budget, slot_pool=slot_pool, slots=slots,
                            max_records=max_records, max_wait=max_wait, identity=identity, launcher=launcher,
                            limits=self.limits, route_check=route_check)
                if usage_semantics != pilot['usage_semantics']:
                    raise Error('pilot launch refused: usage_semantics differs from the frozen configuration')
            if producers_expected * bootstrap_per_producer > max_records and arm in ('B', 'C'):
                raise Error('the bootstrap must fit one batch: producers x per producer exceeds max_records')
        except BaseException:
            self.close()
            raise

    def _setup(self, arm, backend, workload, registry, seed, op, rule_store, do_workspace, budget, slots,
               max_records, max_wait, clock, wall):
        if arm in ('B', 'C'):
            if registry is None:
                raise Error(f'arm {arm} needs an owner-approved oz_registry.Registry')
            if type(seed) is not int or isinstance(seed, bool):
                raise Error(f'arm {arm} needs a frozen integer seed')
        self.workload = _name_ok('workload', workload) if workload is not None else None
        if registry is not None:
            probe_dir = self.experiment_dir / 'arms'
            path = Path(rule_store) if rule_store is not None else None
            if path is None and self.workload is None:
                raise Error('give workload (or rule_store) for an arm with a registry')
            if self.multi and self.workload is None:
                raise Error('give workload for a host with several operations')
            self.store = rp.RuleStore(path or probe_dir / f'{backend}-{self.workload}-{arm}' / 'rules.sqlite',
                                      clock=wall)
            self.learners = {o: rp.Learner(self.store, registry, o, worker_hash=self.worker,
                                           map_contract=self.map_contract, map_input_policy=INPUT_POLICY,
                                           map_pinned=self.pinned) for o in self.ops}
            self.learner = None if self.multi else self.learners[self.op]
            if self.workload is None:
                self.workload = 'k' + self.learner.key[:24]
        elif self.workload is None:
            self.workload = 'k' + self.map_contract[:24]
        self.learn_key = (None if not self.learners else self.learner.key if self.learner is not None else
                          digest({o: lr.key for o, lr in self.learners.items()}))
        self.name = f'{self.backend}-{self.workload}-{arm}'
        self.owner = self._owner_arg or self.name
        self.arm_dir = self.experiment_dir / 'arms' / self.name
        self.arm_dir.mkdir(parents=True, exist_ok=True)
        self.boot_dir = self.experiment_dir / 'bootstrap' / f'{self.backend}-{self.workload}'
        self.side_dir = self.boot_dir / 'side'
        if do_workspace is None:
            do_workspace = self.arm_dir / 'ws'
            if not (do_workspace / 'oz.json').exists():
                from oz_workspace import initialize
                initialize(do_workspace)
        self.do_workspace = Path(do_workspace).resolve()
        self.ledger = Ledger(self.arm_dir / 'ledger.sqlite')
        self._own_budget = budget is None
        self.budget = budget if budget is not None else Budget(self.experiment_dir / 'budget.sqlite')
        self.settle_bindings = digest([self.learn_key if self.learn_key else self.map_contract, arm, backend,
                                       self.workload])
        self.spool = oz_spool.Spool(self.arm_dir / 'spool.sqlite', clock=wall)
        self.scheduler = oz_spool.Scheduler(self.spool, self._launch, slots=slots, max_records=max_records,
                                            max_wait=max_wait, clock=clock, fault=self.hooks.get('spool_fault'))

    def close(self):
        for thing in (self.scheduler, self.spool, self.ledger, self.experiment, self.store,
                      self.budget if self._own_budget else None):
            close = getattr(thing, 'close', None) if thing is not None else None
            if close is not None:
                try:
                    close()
                except Exception:
                    pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ------------------------------------------------------------------------------------------- helpers

    def _stamp(self) -> dict:
        return {'at': self.wall(), 'mono': self.clock(), 'session': self.session}

    def _phase(self, phase, edge, wave=None) -> None:
        s = self._stamp()
        self.ledger.phase(wave or self._wave, phase, edge, s['at'], s['mono'], s['session'])

    def _violate(self, kind, reason, wave=None) -> None:
        self.ledger.violate(wave or self._wave, kind, reason, self.wall())

    # ------------------------------------------------------------------------------------------- intake

    def submit(self, producer: str, submission: str, jobs, *, wave: str) -> list:
        """A producer submission for one wave (jobs exactly {key, op, text, dataset_id}). Returns the job names."""
        _name_ok('producer', producer)
        _name_ok('submission', submission)
        jobs = oz_spool._validate_jobs(jobs)
        if any(j['op'] not in self.ops for j in jobs):
            raise Error(f'this host runs operation {self.op!r} only' if not self.multi else
                        f'this host runs operations {sorted(self.ops)} only')
        s = self._stamp()
        self.ledger.add_intake(producer, submission, wave, jobs, s['at'], s['mono'], s['session'])
        return [oz_spool.delivery_id(producer, submission, j['op'], j['key']) for j in jobs]

    def collect(self, producer: str, submission: str) -> list:
        return [r for r in self._rows.values() if r['producer'] == producer and r['submission'] == submission]

    def _jobs(self, wave) -> list:
        out, seen = [], {}
        for sub in self.ledger.intake(wave):
            for j in sub['jobs']:
                if j['dataset_id'] in seen:
                    raise Error(f"dataset id {j['dataset_id']!r} occurs twice in wave {wave} ({seen[j['dataset_id']]} "
                                f"and {sub['producer']}/{sub['submission']}); a sealed wave binds each id once")
                seen[j['dataset_id']] = f"{sub['producer']}/{sub['submission']}"
                resolved, removed = apply_input_policy(j['text'])
                bad = not resolved.strip() or len(resolved.encode('utf-8')) > MAX_REF_BYTES
                receipt = {'policy': INPUT_POLICY, 'raw_sha256': _sha(j['text']), 'resolved_sha256': _sha(resolved),
                           'removed': removed}
                out.append({'name': oz_spool.delivery_id(sub['producer'], sub['submission'], j['op'], j['key']),
                            'producer': sub['producer'], 'submission': sub['submission'], 'key': j['key'],
                            'op': j['op'], 'dataset_id': j['dataset_id'], 'text': resolved, 'receipt': receipt,
                            'submitted_at': sub['submitted_at'], 'stamp': sub['stamp'], 'invalid': bad, 'wave': wave,
                            'payload_sha256': digest({'op': j['op'], 'op_text': self.ops[j['op']], 'goal': self.goal,
                                                      'dataset_id': j['dataset_id'], 'receipt': receipt})})
        return out

    def _job(self, wave, name) -> dict:
        if wave not in self._jobs_cache:
            self._jobs_cache[wave] = {j['name']: j for j in self._jobs(wave)}
        job = self._jobs_cache[wave].get(name)
        if job is None:
            raise Error(f'the persisted plan of wave {wave} names job {name}, which is not in the intake')
        return job

    def _seal(self, wave, jobs) -> str:
        """Check the intake shape and seal or verify the wave manifest before any call (B12)."""
        if self.expected_intake:
            want_p, want_n = self.expected_intake['producers'], self.expected_intake['per_producer']
            per = {}
            for j in jobs:
                per[j['producer']] = per.get(j['producer'], 0) + 1
            if len(per) != want_p or any(n != want_n for n in per.values()):
                raise Error(f'wave {wave} needs exactly {want_p} producers with {want_n} jobs each before any call '
                            f'(have {dict(sorted(per.items()))})')
        manifest = {j['dataset_id']: {'op': j['op'], 'input_sha256': j['receipt']['raw_sha256'],
                                      'producer': j['producer'], 'key': j['key']} for j in jobs}
        return self.experiment.seal_wave(self.backend, self.workload, wave, manifest)

    # ---------------------------------------------------------------------------------------- dispatch

    def _bindings(self, group_kind: str, pool: str, wave: str, round_: str) -> dict:
        return {'contract_hash': digest([self.map_contract, self.arm, self.backend, self.workload, group_kind, pool,
                                         wave, round_]),
                'check_hash': digest(self.pinned), 'permission_hash': digest({}), 'worker_hash': self.worker,
                'input_policy': INPUT_POLICY}

    def _plan_row(self, wave, round_, seq, item, group_kind) -> dict:
        spool_sub = subname(item['submission'], round_)
        extra = {k: item[k] for k in ('reason', 'audit_job') if k in item}
        return {'wave': wave, 'round': round_, 'item_id': item['id'], 'seq': seq, 'kind': item['kind'],
                'pool': item['pool'], 'original': item['job']['name'], 'producer': item['producer'],
                'submission': item['submission'], 'spool_sub': spool_sub,
                'delivery': oz_spool.delivery_id(item['producer'], spool_sub, item['job']['op'], item['key']),
                'key': item['key'], 'op': item['job']['op'], 'dataset_id': item['dataset_id'],
                'text_sha256': _sha(item['text']), 'group_kind': group_kind,
                'extra': json.dumps(extra, sort_keys=True)}

    def _register(self, row) -> dict:
        """The in-memory item of one persisted plan row (its job from the intake), registered for launch."""
        job = self._job(row['wave'], row['original'])
        if _sha(job['text']) != row['text_sha256']:
            raise Error(f"plan item {row['item_id']}: the job text differs from the persisted plan")
        item = {'id': row['item_id'], 'job': job, 'kind': row['kind'], 'pool': row['pool'],
                'producer': row['producer'], 'submission': row['submission'], 'key': row['key'],
                'text': job['text'], 'dataset_id': row['dataset_id'], 'spool_sub': row['spool_sub'],
                'delivery': row['delivery'], 'round': row['round'], 'wave': row['wave'],
                'group_kind': row['group_kind'], **json.loads(row['extra'])}
        bindings = self._bindings(row['group_kind'], row['pool'], row['wave'], row['round'])
        item['bindings'] = bindings
        self._groups[oz_spool.bindings_hash(bindings)] = {'kind': row['group_kind'], 'pool': row['pool'],
                                                          'wave': row['wave'], 'round': row['round']}
        self._items[row['delivery']] = item
        return item

    def _load_plans(self) -> None:
        """Every persisted plan item of every wave, so a restart can launch, reconcile and allocate them (B4)."""
        for row in self.ledger.plan():
            if row['delivery'] not in self._items:
                self._register(row)

    def _dispatch(self, wave: str, round_: str, items: list, group_kind: str = 'dispatch') -> dict:
        """Persist the round's plan (or load the stored one), claim settlement authority, submit to the spool, drain,
        reconcile unknown attempts without a second call, allocate from call membership.
        Returns {item id: (result or None, spool row or None)}."""
        if not items:
            return {}
        stored = self.ledger.plan(wave, round_)
        extras = []
        if stored:
            wanted = {i['id']: i for i in items}
            planned_ids = {r['item_id'] for r in stored}
            for r in stored:
                mine = wanted.get(r['item_id'])
                if mine is not None and (mine['kind'], mine['pool'], mine['job']['name']) != \
                        (r['kind'], r['pool'], r['original']):
                    raise Error(f"plan item {r['item_id']} of {wave}/{round_} changed identity on resume")
            extras = [i for i in items if i['id'] not in planned_ids]
        else:
            stored = [self._plan_row(wave, round_, n, i, group_kind) for n, i in enumerate(items)]
            self.ledger.add_plan(stored, self.wall())
        planned = [self._register(r) for r in stored]
        # Execution authority before dispatch (B5): the generation every answer of this round will settle with.
        if self.store is not None:
            grants = []
            for item in planned:
                if item['kind'] in SETTLING:
                    generation = self.store.claim(item['job']['name'])
                    self._gen[item['job']['name']] = generation
                    if generation is not None:
                        grants.append({'job': item['job']['name'], 'generation': generation, 'wave': wave,
                                       'round': round_, 'item_id': item['id']})
            self.ledger.authorize(grants, self.wall())
        groups = {}
        for item in planned:
            groups.setdefault((item['pool'], item['producer'], item['spool_sub']), []).append(item)
        subs = []
        for (pool, producer, spool_sub), its in groups.items():
            jobs = [{'key': i['key'], 'op': i['job']['op'], 'text': i['text'], 'dataset_id': i['dataset_id']}
                    for i in its]
            ids = list(self.spool.submit(producer, spool_sub, jobs, its[0]['bindings']))
            if ids != [i['delivery'] for i in its]:
                raise Error(f'spool delivery ids of {producer}/{spool_sub} differ from the persisted plan')
            subs.append((producer, spool_sub))
        self._phase('dispatch:' + round_, 'start', wave)
        self.scheduler.run(until_idle=True, poll=0.02)
        self.reconcile_unknown()
        self._phase('dispatch:' + round_, 'end', wave)
        rows = {}
        for producer, spool_sub in subs:
            rows.update(self.spool.collect(producer, spool_sub)['results'])
        out = {}
        for item in planned:
            row = rows.get(item['delivery'])
            out[item['id']] = (row['result'] if row else None, row)
        self._allocate(wave, {i['delivery'] for i in planned})
        for item in extras:
            out[item['id']] = ({'status': 'unresolved', 'error': f'plan_closed: not in the persisted {round_} plan',
                                'call_id': None}, None)
        if extras:
            self._violate('incomplete', f'plan_closed:{round_}', wave)
        return out

    def _allocate(self, wave, deliveries: set) -> None:
        """Allocation rows from the physical calls' persisted call_start.job_map membership (B7)."""
        rows = []
        for a in self.ledger.attempts():
            if not set(a['records']) & deliveries:
                continue
            for call in a['calls']:
                members = list(call.get('jobs') or [])
                if not members:
                    self._violate('incomplete', 'call_membership_unknown:' + call['call_id'], wave)
                    continue
                for m in members:
                    item = self._items.get(m)
                    if item is None:
                        self._violate('incomplete', 'call_member_not_planned:' + call['call_id'], wave)
                        continue
                    rows.append({'arm': self.arm, 'backend': self.backend, 'workload': self.workload,
                                 'wave': item['wave'], 'attempt_id': a['attempt_id'], 'call_id': call['call_id'],
                                 'job': m, 'original': item['job']['name'], 'producer': item['job']['producer'],
                                 'dataset_id': item['dataset_id'], 'kind': item['kind'], 'share': 1.0 / len(members),
                                 'basis': 'physical'})
        self.ledger.allocate(rows)

    def _request(self, request_id: str, records: list) -> dict:
        op_of = {r['id']: self._items[r['id']]['job']['op'] for r in records}
        present = [o for o in self.ops if o in set(op_of.values())]
        request = {'v': 'oz.do/1', 'request_id': request_id, 'goal': self.goal,
                   'ops': {o: self.ops[o] for o in present},
                   'refs': {'r' + r['id'][1:]: r['text'] for r in records},
                   'jobs': [[r['id'], op_of[r['id']], 'r' + r['id'][1:]] for r in records], 'profile': PROFILE,
                   'allow_experimental': bool(self.allow_experimental), 'max_inline_bytes': MAX_INLINE,
                   'max_attempts': 1, 'max_jobs_per_call': len(records),
                   'max_input_tokens': self.limits.get('max_input_tokens', 1000000)}
        if self.model:
            request['model'] = self.model
        for key in ('deadline_seconds', 'call_timeout_seconds'):
            if key in self.limits:
                request[key] = self.limits[key]
        if self.check_specs:
            request['checks'] = {o: self.check_specs for o in present}
        return request

    def _spec(self, request: dict, max_calls: int) -> dict:
        return {'workspace': str(self.do_workspace), 'request': request, 'max_calls': max_calls,
                'route': self.identity.get('do_route'), 'experimental_sizes': list(self.experimental_sizes),
                'child_timeout': child_timeout(self.limits)}

    def _core_calls(self, request_id) -> list:
        """The physical calls of a request from the core ledger (run_dir/calls.jsonl), read by the parent itself."""
        return _ledger_calls(self.do_workspace / 'do' / request_id)

    def _verify_route(self, env) -> str | None:
        """None when the recomputed route in this launch env equals the frozen worker hash (B11), else the reason."""
        check = self.route_check if self.route_check is not None else self.hooks.get('route_verify')
        if check is None:
            return None
        try:
            if callable(check):
                check(env)
            else:
                import oz_route
                frozen = check['frozen']
                expected = frozen['worker_hash'] if isinstance(frozen, dict) else frozen
                if expected != self.worker:
                    return f'route_unverified: the frozen route {expected[:12]} is not this host worker'
                oz_route.verify(frozen, {k: check[k] for k in ('adapter', 'model', 'effort') if k in check}, env=env,
                                **({'run': check['run']} if 'run' in check else {}))
        except Exception as exc:  # any failure blocks the launch
            return 'route_unverified: ' + str(exc)[:300]
        return None

    def _check_config(self, config) -> dict:
        shim = _shim()
        shim.validate_config(config)
        if config['ops'] != list(self.ops):
            raise Error(f"bootstrap config ops {config['ops']} are not this host's operations {list(self.ops)}")
        return config

    def _launch(self, view: dict) -> dict:
        """The Scheduler's launch: gate, route check, budget reservation, slot, then one child for one oz_do request."""
        group = self._groups.get(view['bindings_hash'])
        records = view['records']
        if group is None or any(r['id'] not in self._items for r in records):
            raise oz_spool.LaunchNotStarted('the persisted plan of this batch is not loaded yet')
        aid, rid = view['attempt_id'], view['request_id']
        items = [self._items[r['id']] for r in records]
        kinds = {}
        for item in items:
            kinds[item['kind']] = kinds.get(item['kind'], 0) + 1
        common = dict(attempt_id=aid, request_id=rid, batch_id=view['batch_id'], arm=self.arm, backend=self.backend,
                      workload=self.workload, wave=group['wave'], round_=group['round'], group_kind=group['kind'],
                      kinds=kinds, records=[r['id'] for r in records])

        def refuse(reason):
            s = self._stamp()
            self.ledger.refused(**common, at=s['at'], mono=s['mono'], session=s['session'], error=reason)
            return {'results': {r['id']: {'status': 'unresolved', 'error': reason, 'call_id': None} for r in records},
                    'call_id': None}

        buckets = (['bootstrap', self.arm, 'reserve'] if group['kind'] == 'bootstrap' else
                   [self.arm, 'reserve'] if not group['round'].startswith(('r2', 'r3')) else ['reserve', self.arm])
        try:
            extra = None
            if group['kind'] == 'bootstrap':
                config = self._check_config(self._bootstrap_config())
                self.side_dir.mkdir(parents=True, exist_ok=True)
                _publish(self.side_dir / f'{aid}.config.json', json.dumps(config, ensure_ascii=False).encode('utf-8'))
                extra = {'OZ_BOOTSTRAP_ATTEMPT': aid, 'OZ_BOOTSTRAP_DIR': str(self.side_dir)}
            env = child_env(model=self.model, effort=self.effort, extra=extra, base=self.base_env)
            spec = self._spec(self._request(rid, records), 1)
        except Exception as exc:  # nothing was launched: a proven-unlaunched refusal
            return refuse(f'prelaunch_failed: {type(exc).__name__}: {str(exc)[:200]}')
        # The launch gate (for example oz_quota) and the route check run before the reservation: a refusal consumes
        # no budget. The 55% weekly guard is suspended (owner decision 1, amendment 3); caps still bind.
        gate = self.hooks.get('launch_gate')
        refusal = gate(view) if gate is not None else None
        if refusal:
            return refuse(refusal)
        mismatch = self._verify_route(env)
        if mismatch:
            return refuse(mismatch)
        bucket = self.budget.reserve(rid, backend=self.backend, buckets=buckets, arm=self.arm, kind=group['kind'])
        if bucket is None:
            return refuse('budget_exhausted')
        lock = self.slot_pool.acquire() if self.slot_pool is not None else None
        evidence = self.arm_dir / 'attempts' / aid
        try:
            s = self._stamp()
            self.ledger.launched(**common, bucket=bucket, evidence_dir=evidence, at=s['at'], mono=s['mono'],
                                 session=s['session'])
            started = self.clock()
            try:
                execution, meta = self.launcher(spec, env, evidence)
            except oz_spool.LaunchNotStarted as exc:
                self.ledger.event(aid, 'not_started', {'error': str(exc)}, self.wall(), self.clock(), self.session)
                raise
            elapsed = self.clock() - started
        finally:
            if lock is not None:
                self.slot_pool.release(lock)
        core = self._core_calls(rid)
        s = self._stamp()
        self.ledger.finished(aid, meta=meta, execution=execution, core_calls=core, elapsed=elapsed, at=s['at'],
                             mono=s['mono'], session=s['session'],
                             error=None if execution is not None else f"child exit {meta['exit_code']}")
        if execution is not None:
            # The adapter capture (the child's call list and every job's call id) against the core ledger the parent
            # read itself.
            core_ids = {c['call_id'] for c in core}
            captured = {c['call_id'] for c in execution.get('calls') or []}
            per_job = {j.get('call_id') for j in (execution.get('jobs') or {}).values() if j.get('call_id')}
            if captured != core_ids or not per_job <= core_ids:
                self._violate('incomplete', 'ledger_capture_mismatch:' + aid, group['wave'])
        if 'after_execute' in self.hooks:
            self.hooks['after_execute'](view, execution)
        if execution is None:
            raise RuntimeError(f"child for {rid} failed (exit {meta['exit_code']}, timed_out {meta['timed_out']})")
        return self._capture(records, execution)

    @staticmethod
    def _capture(records, execution) -> dict:
        results = {r['id']: execution['jobs'].get(r['id'], {'status': 'unresolved', 'error': 'missing_from_run',
                                                            'call_id': None}) for r in records}
        calls = execution.get('calls') or []
        return {'results': results, 'call_id': calls[0]['call_id'] if calls else None}

    def reconcile_unknown(self) -> list:
        """Resolve unknown attempts by resuming their oz_do request with a zero call cap (never a second call). Every
        reconciliation child is its own ledger event, also when it fails (Opus B); the core ledger of the request is
        read either way. Returns the attempt ids it resolved."""
        done = []
        for entry in self.spool.unresolved():
            rid = oz_spool.request_id_of(entry['batch_id'])
            mapping = self.spool.request_map(rid)
            records = []
            for j in sorted(mapping['jobs'], key=lambda x: x['position']):
                item = self._items.get(j['delivery_id'])
                if item is None:
                    records = None
                    break
                records.append({'id': j['delivery_id'], 'text': item['text']})
            if not records:
                continue
            if self.ledger.attempt(entry['attempt_id']) is None:
                # The host stopped after the spool's launched mark and before its own launched record, which precedes
                # every child start: provably unlaunched, so the same request may be launched again (A2.1).
                self.scheduler.reconcile(entry['attempt_id'], provably_unlaunched=True)
                continue
            n = len([e for e in self.ledger.events(entry['attempt_id']) if e['event'].startswith('reconcile')])
            evidence = self.arm_dir / 'attempts' / f"{entry['attempt_id']}-reconcile{n + 1}"
            env = child_env(model=self.model, effort=self.effort, base=self.base_env)
            launch = self.hooks.get('reconcile_launcher') or self.launcher
            try:
                execution, meta = launch(self._spec(self._request(rid, records), 0), env, evidence)
            except Exception as exc:
                execution, meta = None, {'exit_code': None, 'timed_out': False, 'error': repr(exc)[:300]}
            s = self._stamp()
            self.ledger.reconciled(entry['attempt_id'], meta=meta, execution=execution,
                                   core_calls=self._core_calls(rid), evidence_dir=evidence, at=s['at'],
                                   mono=s['mono'], session=s['session'])
            if execution is None:
                continue
            self.scheduler.reconcile(entry['attempt_id'], self._capture(records, execution))
            done.append(entry['attempt_id'])
        return done

    # --------------------------------------------------------------------------------------------- rows

    def _row(self, job, **fields) -> dict:
        row = {'id': job['name'], 'producer': job['producer'], 'submission': job['submission'], 'key': job['key'],
               'op': job['op'], 'dataset_id': job['dataset_id'], 'arm': self.arm, 'worker_hash': self.worker,
               'reference': {'input': job['receipt']}, 'status': 'failed', 'source': 'model', 'phase': None,
               'call_id': None, 'attempt_id': None, 'request_id': None, 'call_kind': None}
        row.update(fields)
        queued = row.pop('_queued_at', None)
        resumed = row.pop('resumed', False)
        if row['status'] in TERMINAL:
            s = self._stamp()
            row['delivered_at'] = s['at']
            row['queue_s'] = round((queued if queued is not None else s['at']) - job['submitted_at'], 6)
            first, conflict = self.ledger.deliver(job['name'], job['wave'], row, s)
            if conflict:
                self._violate('efficiency_invalid', 'redelivery_conflict', job['wave'])
            resumed = resumed or first is not row
            row = dict(first)
        else:
            row['delivered_at'] = row['queue_s'] = None  # not delivered: the producer has no final row yet
        row['resumed'] = bool(resumed)
        self._rows[job['name']] = row
        if 'after_row' in self.hooks:
            self.hooks['after_row'](row)
        return row

    def _model_row(self, job, result, srow, *, phase, kind, reason=None) -> dict:
        base = {'phase': phase, 'call_kind': kind}
        if reason is not None:
            base['fallback_reason'] = reason
        if srow is not None:
            base.update(call_id=(result or {}).get('call_id') or srow.get('call_id'), attempt_id=srow['attempt_id'],
                        request_id=srow['request_id'], _queued_at=srow['reserved_at'])
        if self.store is not None:
            s = self.store.settlement(job['name'])
            if s is not None and s['state'] in ('settled', 'failed'):
                return self._resumed_row(job, base)
        if result is None:
            return self._row(job, status='unresolved', error='attempt_unknown: outcome not reconciled', **base)
        if result.get('status') != 'accepted':
            return self._row(job, status='unresolved' if result.get('status') == 'unresolved' else 'failed',
                             error=result.get('error') or result.get('status'), **base)
        if result.get('memo'):
            base['memo'] = True
            self._violate('efficiency_invalid', 'memo_served', job['wave'])
        if self.store is None:
            return self._row(job, status='accepted', value_text=result['value_text'], **base)
        return self._settle_model(job, result['value_text'], base, self._gen.get(job['name']))

    def _settle_model(self, job, value_text, base, generation=None) -> dict:
        """Settle with the generation claimed before dispatch (B5); an import claims before it evaluates."""
        if generation is None:
            generation = self.store.claim(job['name'])
            if generation is None:
                return self._resumed_row(job, base)
            self.ledger.authorize([{'job': job['name'], 'generation': generation, 'wave': job['wave'],
                                    'round': base.get('phase') or 'settle', 'item_id': 'settle:' + job['name']}],
                                  self.wall())
        checks = self.learners[job['op']].evidence(value_text, job['text'], self.ops[job['op']])
        state, detail = self.store.settle_model(job['name'], generation=generation,
                                                payload_sha256=job['payload_sha256'],
                                                bindings_sha256=self.settle_bindings, value_text=value_text,
                                                checks=checks, phase=base['phase'], call_id=base.get('call_id'))
        if state == 'settled':
            return self._row(job, status='accepted', value_text=value_text, checks=checks, **base)
        if state == 'awaiting_verification':
            return self._row(job, status='awaiting_verification', value_text=None, error=detail, **base)
        if state == 'refused' and str(detail).startswith(('already_settled', 'already_failed')):
            return self._resumed_row(job, base)
        if state == 'refused':
            return self._row(job, status='unresolved', error='settlement_refused: ' + str(detail), **base)
        return self._row(job, status='failed', error=detail, **base)

    def _resumed_row(self, job, base=None) -> dict:
        """The row of a job whose settlement is already final (resume): its first delivery when there is one."""
        s = self.store.verify_identity(job['name'], payload_sha256=job['payload_sha256'],
                                       bindings_sha256=self.settle_bindings)
        if s['winner'] == 'rule':
            return self._rule_row(job, self.store.result(job['name']), resumed=True)
        emissions = self.store.emissions(job['name'])
        fields = dict(base or {'phase': None, 'call_kind': None})
        fields.pop('_queued_at', None)
        if s['state'] == 'failed':
            last = [e for e in emissions if e['outcome'] == 'failed'][-1]
            fields.setdefault('call_id', last['call_id'])
            fields['phase'] = fields.get('phase') or last['phase']
            return self._row(job, status='failed', error=last['reason'], resumed=True, **fields)
        emission = next(e for e in emissions if e['seq'] == s['emission'])
        fields.setdefault('call_id', emission['call_id'])
        fields['phase'] = fields.get('phase') or emission['phase']
        return self._row(job, status='accepted', value_text=emission['value'], checks=emission['checks'],
                         resumed=True, **fields)

    def _rule_row(self, job, result, *, resumed=False) -> dict:
        return self._row(job, status='accepted', source='rule', phase='rule', value_text=result['value'],
                         rule={'id': result['rule'], 'type': result['type'], 'steps': result['steps'],
                               'ast_sha256': result['provenance']['ast_sha256'], 'binding_key': result['binding_key'],
                               'checks': [f"{c['id']}:{c['verdict']}" for c in result['checks']],
                               'provenance': result['provenance']['check']}, resumed=resumed)

    # ---------------------------------------------------------------------------------------------- run

    def run_wave(self, wave: str, *, learn: bool = True) -> dict:
        """Process every intake submission of this wave and return the arm report for it."""
        jobs = self._jobs(wave)
        if not jobs:
            raise Error(f'no submissions for wave {wave}')
        self._jobs_cache[wave] = {j['name']: j for j in jobs}
        manifest_sha = self._seal(wave, jobs)
        self._wave, self._wave_jobs = wave, self._jobs_cache[wave]
        self._phase('wave', 'start')
        # Restart: load every persisted plan and reconcile the attempts already made before anything new (B4).
        self._load_plans()
        self.reconcile_unknown()
        notes = {'bootstrap': None, 'audits': None, 'quarantine_fallbacks': 0, 'state': [],
                 'manifest_sha256': manifest_sha}
        valid = []
        for job in jobs:
            if job['invalid']:
                self._row(job, status='failed', error='input_invalid: blank or over the reference size limit',
                          phase='input')
            else:
                valid.append(job)
        if self.store is not None:
            for job in valid:
                self.store.open_job(job['name'], payload_sha256=job['payload_sha256'],
                                    bindings_sha256=self.settle_bindings,
                                    required=self.learners[job['op']].required)
        if self.arm == 'A':
            items = []
            for j in valid:
                if self.store is not None and self.store.settlement(j['name'])['state'] in ('settled', 'failed'):
                    self._resumed_row(j)
                else:
                    items.append(self._item(j, 'ordinary', 'pool'))
            results = self._dispatch(wave, 'r1', items)
            for item in items:
                self._model_row(item['job'], *results[item['id']], phase='ordinary', kind='ordinary')
        else:
            self._rule_arm(wave, valid, learn, notes)
        self._phase('wave', 'end')
        return self.report(wave, jobs, notes)

    def _bootstrap_config(self) -> dict:
        """The shim's oz.bootstrap.config/2: the one learner's, or every operation's contract and eligibility."""
        if not self.multi:
            return self.learner.bootstrap_config()
        return {'schema': rp.CONFIG_SCHEMA, 'ops': list(self.learners),
                'contracts': {o: lr.contract for o, lr in self.learners.items()},
                'eligibility': {o: lr.eligible for o, lr in self.learners.items()}}

    def _item(self, job, kind, pool, *, key=None, submission=None, tag=None) -> dict:
        return {'id': (tag or kind) + ':' + job['name'], 'job': job, 'kind': kind, 'pool': pool,
                'producer': job['producer'], 'submission': submission or job['submission'],
                'key': key or job['key'], 'text': job['text'], 'dataset_id': job['dataset_id']}

    def _pool(self, job) -> str:
        return job['producer'] if self.arm == 'B' else 'pool'

    def _rule_arm(self, wave, jobs, learn, notes) -> None:
        store, learners = self.store, self.learners
        # 1. Shared bootstrap. The frozen assignment binds before any record exists (B2); a learning wave whose
        # bootstrap is not recorded yet stops here with every job pending, never with fallback replacements.
        found = self.experiment.bootstrap(self.backend, self.workload)
        known = found['record'] if found and found['record'] else None
        record, fresh = None, False
        if learn and (known is None or known.get('wave') == wave):
            record, assignment = self._bootstrap(wave, jobs)
            if record is None:
                boot = {d for ids in assignment.values() for d in ids}
                for job in jobs:
                    if store.settlement(job['name'])['state'] in ('settled', 'failed'):
                        self._resumed_row(job)
                    elif job['dataset_id'] in boot:
                        self._row(job, status='unresolved', phase='bootstrap', call_kind='bootstrap',
                                  error='bootstrap_pending: the frozen bootstrap assignment holds this job until '
                                        'the one bootstrap is recorded (A2.1)')
                    else:
                        self._row(job, status='unresolved', phase='rule',
                                  error='waiting_for_bootstrap: the rule phase needs the recorded bootstrap')
                notes['state'].append('bootstrap_pending')
                return
            fresh = True
        elif learn or known is not None:
            record = known
        boot_ids = set()
        if record is not None and fresh:
            boot_ids = set(record['jobs'])
            notes['bootstrap'] = {k: record.get(k) for k in ('status', 'attempt_id', 'efficiency_valid', 'owner')}
            notes['bootstrap']['imported'] = record.get('owner') != self.owner
            notes['bootstrap']['elapsed'] = record.get('elapsed_seconds') or 0.0
            notes['bootstrap']['one_call'] = record.get('one_call')
            if not record.get('efficiency_valid'):
                self._violate('efficiency_invalid', 'bootstrap_' + str(record.get('status')))
        rest = []
        for job in jobs:
            if job['dataset_id'] in boot_ids:
                self._bootstrap_row(job, record)
            else:
                rest.append(job)
        self._phase('rule_phase', 'start')
        warm = not fresh
        active = {}
        for o, lr in learners.items():
            rule = store.active(lr.key)
            entries = store.rules(lr.key)
            reuse, why = store.reusable(rule['id']) if rule else (False, None)
            without = ('no_admitted_rule' if not entries else 'quarantined' if any(e['status'] == 'quarantined'
                                                                                   for e in entries)
                       else 'rule_rejected')
            active[o] = (rule, reuse, why, without)
            if rule and warm and not reuse:
                self._violate('efficiency_invalid', 'warm_reuse_blocked:' + (f'{o}:' if self.multi else '') + why)
        staged, covered, fallback = {}, {}, []
        for job in rest:
            s = store.settlement(job['name'])
            if s['state'] in ('settled', 'failed'):
                row = self._resumed_row(job)
                if row['source'] == 'rule':
                    covered[job['name']] = (job, row['value_text'])
                continue
            rule, reuse, why, without = active[job['op']]
            if rule is None:
                fallback.append((job, without))
                continue
            if warm and not reuse:
                fallback.append((job, why))
                continue
            generation = store.claim(job['name'])
            self.ledger.authorize([{'job': job['name'], 'generation': generation, 'wave': wave, 'round': 'rule',
                                    'item_id': 'rule:' + job['name']}], self.wall())
            d = learners[job['op']].attempt(
                rule, job=job['name'], text=job['text'], resolved_sha256=job['receipt']['resolved_sha256'],
                op_text=self.ops[job['op']], owner={'producer': job['producer'], 'submission': job['submission'],
                                                    'operation': job['op'], 'path': job['key']},
                generation=generation, payload_sha256=job['payload_sha256'], bindings_sha256=self.settle_bindings,
                stage=self.rule_delivery == 'after_audits', evaluate=self.hooks.get('evaluate', rp.oz_rule.evaluate),
                before_commit=self.hooks.get('before_commit'))
            if d['decision'] == 'staged':
                staged[job['name']] = (job, d)
                covered[job['name']] = (job, rp.oz_rule.canonical_value_text(d['first']))
            elif d['decision'] == 'rule':
                self._rule_row(job, d['row'], resumed=d.get('resumed', False))
                covered[job['name']] = (job, d['row']['value'])
            else:
                fallback.append((job, d['reason']))
        self._phase('rule_phase', 'end')
        # 3. Audits over the whole evaluation wave, selected on frozen dataset ids and persisted before dispatch.
        audit_items = []
        live = {o: a[0] for o, a in active.items() if a[0] is not None}
        if covered and live:
            by_dataset = {j['dataset_id']: (j, v) for j, v in covered.values() if j['op'] in live}
            wave_key = rp.wave_id(self.backend, self.workload, wave)
            rule_key = (live[self.op]['ast_sha256'] if not self.multi else
                        digest(sorted([o, r['ast_sha256']] for o, r in live.items())))
            selection = self.experiment.audit_wave(wave_key, rule_key, self.seed, sorted(by_dataset))
            if selection['mismatch']:
                self._violate('incomplete', 'audit_population_mismatch')
            chosen = [d for d in selection['selection'] if d in by_dataset]
            rows = []
            for d in chosen:
                job, value = by_dataset[d]
                audit_sub = subname(job['submission'], 'audit')
                item = self._item(job, 'audit', self._pool(job), submission=audit_sub, tag='audit')
                item['audit_job'] = oz_spool.delivery_id(job['producer'], audit_sub, job['op'], job['key'])
                rows.append({'audit_job': item['audit_job'], 'wave_id': wave_key, 'original_job': job['name'],
                             'rule': live[job['op']]['id'], 'producer': job['producer'],
                             'submission': job['submission'], 'dataset_id': d, 'rule_value': value})
                audit_items.append(item)
            store.add_audits(rows)
            audit_items = [i for i in audit_items if store.audit(i['audit_job'])['verdict'] in ('pending',
                                                                                                'inconclusive')]
            notes['audits'] = {'wave_id': wave_key, 'population': len(by_dataset), 'selected': len(chosen)}
        # 4. Fallback plus audits in shared batches (B: per producer; C: pooled).
        items = [dict(self._item(job, 'fallback', self._pool(job)), reason=reason) for job, reason in fallback]
        open_audits = [i for i in audit_items if store.audit(i['audit_job'])['verdict'] == 'pending']
        results = self._dispatch(wave, 'r1', items + open_audits)
        for item in items:
            self._model_row(item['job'], *results[item['id']], phase='fallback', kind='fallback',
                            reason=item['reason'])
        self._phase('audit_decision', 'start')
        retry = self._decide_audits(open_audits, results)
        retry += [i for i in audit_items if i not in open_audits]  # inconclusive before a restart: its retry
        self._phase('audit_decision', 'end')
        if retry and self.audit_retry:
            again = [dict(i, id='retry:' + i['id'], submission=subname(i['job']['submission'], 'audit2'))
                     for i in retry]
            self._decide_audits(again, self._dispatch(wave, 'r2', again))
        # 5. Deliver staged rule rows; a rule quarantined meanwhile makes the undelivered rows fall back (rule 8).
        late = []
        for name, (job, d) in staged.items():
            got = learners[job['op']].commit(d, evaluate=self.hooks.get('evaluate', rp.oz_rule.evaluate),
                                             before_commit=self.hooks.get('before_commit'))
            if got['decision'] == 'rule':
                self._rule_row(job, got['row'])
            else:
                late.append((job, got['reason']))
        if late:
            notes['quarantine_fallbacks'] = sum(1 for _, r in late if r.endswith('quarantined'))
            items = [dict(self._item(job, 'fallback', self._pool(job), tag='late',
                                     submission=subname(job['submission'], 'late')), reason=reason)
                     for job, reason in late]
            results = self._dispatch(wave, 'r3', items)
            for item in items:
                self._model_row(item['job'], *results[item['id']], phase='fallback', kind='fallback',
                                reason=item['reason'])

    def _decide_audits(self, items, results) -> list:
        """Record each audit verdict (a disagreement quarantines in the same transaction); returns the inconclusive.
        A memo-served audit is inconclusive and a permanent efficiency violation (B10)."""
        retry = []
        for item in items:
            result, srow = results.get(item['id'], (None, None))
            original = self.store.audit(item['audit_job'])
            meta = {'call_id': (result or {}).get('call_id'), 'attempt_id': srow['attempt_id'] if srow else None}
            if result is None or result.get('status') == 'unresolved':
                continue  # stays pending: blocks the completed-evidence claim and warm reuse
            if result.get('status') != 'accepted':
                verdict, model_value, detail = 'inconclusive', None, result.get('error') or result.get('status')
            elif result.get('memo'):
                verdict, model_value, detail = 'inconclusive', None, 'memo: no blind model answer'
                self._violate('efficiency_invalid', 'memo_served_audit')
            else:
                model_value = result['value_text']
                same = canonical(loads(model_value)) == canonical(loads(original['rule_value']))
                verdict, detail = ('agree' if same else 'disagree'), None
            got = self.store.decide_audit(item['audit_job'], verdict, model_value=model_value, detail=detail, **meta)
            if got['audit']['verdict'] == 'inconclusive':
                retry.append(item)
        return retry

    # ------------------------------------------------------------------------------------------ bootstrap

    def _bootstrap(self, wave, jobs) -> tuple:
        """(record or None, frozen assignment): claim and run (or resume) the one shared bootstrap, or wait for and
        import the recorded one. None means pending: unknown, not yet launched, or another arm still running it."""
        by_producer = {}
        for job in jobs:
            by_producer.setdefault(job['producer'], []).append(job['dataset_id'])
        assignment = self.experiment.assignment(self.backend, self.workload, by_producer, self.seed,
                                                per_producer=self.per_producer, expected=self.producers_expected)
        state, row = self.experiment.claim_bootstrap(self.backend, self.workload, self.owner)
        if state == 'wait':
            self._phase('bootstrap_wait', 'start')
            deadline = self.clock() + self.bootstrap_wait
            while self.clock() < deadline:
                row = self.experiment.bootstrap(self.backend, self.workload)
                if row['state'] == 'recorded':
                    break
                time.sleep(0.05)
            self._phase('bootstrap_wait', 'end')
            if row['state'] != 'recorded':
                return None, assignment
        elif state in ('run', 'resume'):
            if self._run_bootstrap(wave, jobs, assignment) is None:
                return None, assignment
        record = self.experiment.bootstrap(self.backend, self.workload)['record']
        if record['owner'] != self.owner:
            self._verify_import(record, jobs, assignment)
        self._phase('bootstrap_import', 'start')
        for o, lr in self.learners.items():
            lr.admit_side(record['side'], source=f"bootstrap:{record['attempt_id']}:{o}",
                          provenance={'experiment': str(self.experiment.path), 'backend': self.backend,
                                      'workload': self.workload, 'attempt_id': record['attempt_id'],
                                      'side_sha256': record['side_sha256'], 'status': record['status'],
                                      'imported': record['owner'] != self.owner})
        if record['owner'] != self.owner:
            self._import_allocations(wave, jobs, record)
        self._phase('bootstrap_import', 'end')
        return record, assignment

    def _payloads(self, jobs, ids) -> dict:
        by = {j['dataset_id']: j for j in jobs}
        return {d: {'op': by[d]['op'], 'payload_sha256': by[d]['payload_sha256'],
                    'input_sha256': by[d]['receipt']['raw_sha256']} for d in sorted(ids) if d in by}

    def _verify_import(self, record, jobs, assignment) -> None:
        """Refuse (Error) to import a bootstrap recorded under another binding, assignment, worker or payload (B12)."""
        problems = []
        if record.get('binding_key') != self.learn_key:
            problems.append('binding_key')
        if record.get('assignment_sha256') != _sha(json.dumps(assignment, sort_keys=True)):
            problems.append('assignment_sha256')
        if record.get('worker_hash') != self.worker:
            problems.append('worker_hash')
        ids = {d for v in assignment.values() for d in v}
        if record.get('payloads') != self._payloads(jobs, ids) or set(record.get('jobs') or {}) != ids:
            problems.append('dataset-id payloads')
        if problems:
            raise Error('refusing to import the shared bootstrap: it differs in ' + ', '.join(problems))

    def _bootstrap_input(self, items) -> int:
        """A conservative input estimate of the bootstrap packet (UTF-8 bytes of the shim text, operations, goal and
        every record; a token is never shorter than one byte for these tokenizers)."""
        shim = _shim()
        system = shim.system_text('', self._bootstrap_config())
        return (len(system.encode('utf-8')) + len(self.goal.encode('utf-8'))
                + sum(len(t.encode('utf-8')) for t in self.ops.values())
                + sum(len(i['text'].encode('utf-8')) + 200 for i in items))

    def _bootstrap_round(self, wave) -> str:
        """The current bootstrap try: a new try only after every attempt of the last one was refused before launch
        (proven unlaunched, A2.1)."""
        tries = sorted({r['round'] for r in self.ledger.plan(wave) if r['round'].startswith('bootstrap')},
                       key=lambda r: int(r.split('-')[1]) if '-' in r else 1)
        if not tries:
            return 'bootstrap'
        last = tries[-1]
        attempts = [a for a in self.ledger.attempts(wave) if a['round'] == last]
        if attempts and all(a['outcome'] == 'unlaunched' for a in attempts):
            return f'bootstrap-{len(tries) + 1}'
        return last

    def _run_bootstrap(self, wave, jobs, assignment) -> dict | None:
        """Dispatch the one bootstrap packet, settle all its answers, then write the immutable record (B3)."""
        by_dataset = {j['dataset_id']: j for j in jobs}
        items = [self._item(by_dataset[d], 'bootstrap', 'bootstrap', tag='boot',
                            submission=subname(by_dataset[d]['submission'], 'boot'))
                 for p in sorted(assignment) for d in assignment[p]]
        expected = self.producers_expected * self.per_producer
        if len(items) != expected or len(items) > self.max_records:
            raise Error(f'the bootstrap packet must be exactly {expected} records in one batch, got {len(items)}')
        size, limit = self._bootstrap_input(items), self.limits.get('max_input_tokens', 1000000)
        if size > limit:
            raise Error(f'the bootstrap packet (about {size} input units with the shim text) exceeds max_input_tokens '
                        f'{limit}; refused before launch')
        round_ = self._bootstrap_round(wave)
        self._phase('bootstrap', 'start')
        results = self._dispatch(wave, round_, items, group_kind='bootstrap')
        if any(results[i['id']][0] is None for i in items):
            self._phase('bootstrap', 'end')
            return None  # unknown outcome: unresolved until reconciled (A2.1)
        attempts = [a for a in self.ledger.attempts(wave) if a['round'].startswith('bootstrap')]
        current = [a for a in attempts if a['round'] == round_]
        if not current or all(a['outcome'] == 'unlaunched' for a in current):
            self._phase('bootstrap', 'end')
            return None  # provably unlaunched (refused): nothing recorded, a later run may try again
        if any(a['outcome'] in (None, 'unresolved') for a in current):
            self._phase('bootstrap', 'end')
            return None
        aid = current[0]['attempt_id']
        calls = [c for a in current for c in a['calls']]
        deliveries = {r['delivery'] for r in self.ledger.plan(wave, round_)}
        one_call = (len(current) == 1 and len(calls) == 1 and set(calls[0].get('jobs') or []) == deliveries)
        side_file = self.side_dir / f'{aid}.json'
        side_bytes = side_file.read_bytes() if side_file.exists() else None
        side = json.loads(side_bytes.decode('utf-8')) if side_bytes else None
        answers, settled = {}, {}
        for item in items:
            result, srow = results[item['id']]
            answers[item['dataset_id']] = {'status': result.get('status'), 'value_text': result.get('value_text'),
                                           'error': result.get('error'), 'call_id': result.get('call_id'),
                                           'memo': bool(result.get('memo'))}
        # Final host settlement of every answer before anything is recorded (council 3, B3).
        rows = {d: self._bootstrap_answer_row(by_dataset[d], answers[d], aid, None) for d in answers}
        for d, row in rows.items():
            settled[d] = {'status': row['status'], 'error': row.get('error')}
        failures = sorted({f"{d}:{s['status']}:{s['error']}" for d, s in settled.items() if s['status'] != 'accepted'})
        if side is None:
            status = 'missing'
        elif side.get('status') != 'ok' or side.get('envelope_ok') is not True:
            status = 'failed'
        elif not one_call:
            status = 'not_one_call'
        elif any(a['memo'] for a in answers.values()):
            status = 'memo_served'
        elif all(s['status'] == 'accepted' for s in settled.values()):
            status = 'ok'
        else:
            status = 'answers_failed'
        self._phase('bootstrap', 'end')
        call_rows = [dict(c, datasets=sorted(self._items[m]['dataset_id'] for m in (c.get('jobs') or [])
                                             if m in self._items)) for c in calls]
        record = {'backend': self.backend, 'workload': self.workload, 'owner': self.owner, 'wave': wave,
                  'binding_key': self.learn_key, 'binding_keys': {o: lr.key for o, lr in self.learners.items()},
                  'worker_hash': self.worker, 'assignment': assignment,
                  'assignment_sha256': _sha(json.dumps(assignment, sort_keys=True)), 'attempt_id': aid,
                  'request_id': current[0]['request_id'], 'jobs': answers, 'settlements': settled,
                  'payloads': self._payloads(jobs, answers), 'side': side,
                  'side_sha256': hashlib.sha256(side_bytes).hexdigest() if side_bytes else None,
                  'attempt': current[0], 'attempts': attempts, 'calls': call_rows, 'one_call': one_call,
                  'failures': failures, 'elapsed_seconds': self.ledger.phase_seconds(wave).get('bootstrap', 0.0),
                  'status': status, 'efficiency_valid': status == 'ok'}
        self.experiment.record_bootstrap(self.backend, self.workload, self.owner, record)
        return record

    def _bootstrap_answer_row(self, job, answer, attempt_id, record) -> dict:
        """One bootstrap job's row through this host's settlement boundary; a failed answer stays failed (A2.1)."""
        s = self.store.settlement(job['name'])
        base = {'phase': 'bootstrap', 'call_kind': 'bootstrap', 'call_id': answer.get('call_id'),
                'attempt_id': attempt_id, 'request_id': (record or {}).get('request_id'),
                'imported': record is not None and record['owner'] != self.owner}
        if s['state'] in ('settled', 'failed'):
            return self._resumed_row(job, base)
        if answer.get('memo'):
            base['memo'] = True
            self._violate('efficiency_invalid', 'memo_served_bootstrap', job['wave'])
        if answer['status'] != 'accepted':
            return self._row(job, status='failed', error='bootstrap_answer_failed: ' + str(answer.get('error')),
                             **base)
        generation = self._gen.get(job['name']) if record is None else None
        return self._settle_model(job, answer['value_text'], base, generation)

    def _import_allocations(self, wave, jobs, record) -> None:
        """The shared bootstrap's calls charged analytically in full to this arm (basis imported), by the recorded
        call membership. Idempotent: it runs again on every resume (Opus 3)."""
        mine = {j['dataset_id']: j for j in jobs}
        rows = []
        for call in record.get('calls') or []:
            members = call.get('datasets') or []
            for d in members:
                job = mine.get(d)
                if job is None:
                    continue
                rows.append({'arm': self.arm, 'backend': self.backend, 'workload': self.workload, 'wave': wave,
                             'attempt_id': record['attempt_id'], 'call_id': call['call_id'], 'job': job['name'],
                             'original': job['name'], 'producer': job['producer'], 'dataset_id': d,
                             'kind': 'bootstrap', 'share': 1.0 / len(members), 'basis': 'imported'})
        self.ledger.allocate(rows)

    def _bootstrap_row(self, job, record) -> dict:
        """A bootstrap job's row from the shared record, settled here, never replaced (A2.1)."""
        if record['owner'] == self.owner:
            s = self.store.settlement(job['name'])
            if s['state'] in ('settled', 'failed'):
                return self._resumed_row(job, {'phase': 'bootstrap', 'call_kind': 'bootstrap',
                                               'attempt_id': record['attempt_id'],
                                               'request_id': record.get('request_id'), 'imported': False})
        row = self._bootstrap_answer_row(job, record['jobs'][job['dataset_id']], record['attempt_id'], record)
        theirs = (record.get('settlements') or {}).get(job['dataset_id'])
        if theirs is not None and theirs['status'] != row['status']:
            self._violate('incomplete', 'bootstrap_settlement_differs:' + job['dataset_id'])
        return row

    # --------------------------------------------------------------------------------------------- report

    def _record(self) -> dict:
        return (self.experiment.bootstrap(self.backend, self.workload) or {}).get('record') or {}

    def reconcile(self, wave: str) -> dict:
        """Accounting reconciliation of one wave: every attempt has a resolved outcome; every physical call's shares sum
        to 1 over exactly the jobs its call_start.job_map carried; allocated calls exist; imported calls are the
        bootstrap record's; charged = physical + imported. Planned, dispatched and accepted counts are kept apart."""
        problems = []
        allocations = self.ledger.allocations(wave)
        attempts = self.ledger.attempts(wave)
        launched = [a for a in attempts if a['outcome'] != 'unlaunched']
        physical = {c['call_id']: c for a in launched for c in a['calls'] if c}
        imported_calls = {c['call_id']: c for c in self._record().get('calls') or []}
        unresolved = [a['attempt_id'] for a in launched if a['outcome'] in (None, 'unresolved')]
        for aid in unresolved:
            problems.append(f'attempt {aid} has no resolved physical outcome')
        # Every reservation of this host's requests belongs to a ledger attempt (B6).
        requests = {r['request_id'] for r in self.ledger.db.execute('SELECT request_id FROM attempts')}
        conn = self.spool._connect()
        try:
            mine = {r[0] for r in conn.execute('SELECT request_id FROM batches')}
        finally:
            conn.close()
        for key in sorted(self.budget.reserved(mine) - requests):
            problems.append(f'reservation {key} has no ledger attempt')
        shares, members = {}, {}
        for a in allocations:
            key = (a['call_id'], a['basis'])
            shares[key] = shares.get(key, 0.0) + a['share']
            if a['basis'] == 'physical':
                members.setdefault(a['call_id'], set()).add(a['job'])
                if a['call_id'] not in physical:
                    problems.append(f"allocated physical call {a['call_id']} is not in the ledger")
            if a['basis'] == 'imported' and a['call_id'] not in imported_calls:
                problems.append(f"imported call {a['call_id']} is not in the bootstrap record")
        for key, total in shares.items():
            if abs(total - 1.0) > 1e-9:
                problems.append(f'call {key[0]} ({key[1]}) shares sum to {total}')
        for cid, call in physical.items():
            if set(call.get('jobs') or []) != members.get(cid, set()):
                problems.append(f'call {cid} carried {len(call.get("jobs") or [])} jobs but '
                                f'{len(members.get(cid, ()))} are allocated')
        imported = sorted({a['call_id'] for a in allocations if a['basis'] == 'imported'})
        planned = sum(len(a['records']) for a in launched)
        dispatched = sum(len(c.get('jobs') or []) for c in physical.values())
        return {'ok': not problems, 'problems': problems, 'physical_calls': len(physical),
                'imported_calls': len(imported), 'charged_calls': len(physical) + len(imported),
                'unresolved_attempts': unresolved, 'membership': {'planned': planned, 'dispatched': dispatched},
                'physical': physical, 'imported': {c: imported_calls[c] for c in imported if c in imported_calls}}

    def report(self, wave, jobs, notes) -> dict:
        rows = [self._rows[j['name']] for j in jobs]
        rec = self.reconcile(wave)
        attempts = self.ledger.attempts(wave)
        tokens = {'physical': _tokens(rec['physical'].values()), 'imported': _tokens(rec['imported'].values())}
        tokens['charged'] = _add_tokens(tokens['physical'], tokens['imported'])
        tokens['semantics'] = self.usage_semantics
        by_kind = {}
        for a in self.ledger.allocations(wave):
            slot = by_kind.setdefault(a['kind'], {'jobs': 0, 'calls': set(), 'share_calls': 0.0})
            slot['jobs'] += 1
            slot['calls'].add(a['call_id'])
            slot['share_calls'] += a['share']
        by_kind = {k: {'jobs': v['jobs'], 'calls': len(v['calls']), 'share_calls': round(v['share_calls'], 6)}
                   for k, v in by_kind.items()}
        audits = {'selected': 0, 'agree': 0, 'disagree': 0, 'inconclusive': 0, 'pending': 0, 'population': 0}
        quarantined = False
        if self.store is not None:
            if notes['audits']:
                audits.update(population=notes['audits']['population'])
                for a in self.store.audits(notes['audits']['wave_id']):
                    audits['selected'] += 1
                    audits[a['verdict']] += 1
            quarantined = any(r['status'] == 'quarantined' for lr in self.learners.values()
                              for r in self.store.rules(lr.key))
        # Evidence completeness, derived from settlement, audits, launch reconciliation and accounting together, plus
        # every persisted violation event of this wave (a retry never erases one; B10).
        persisted = self.ledger.violations(wave)
        invalid, incomplete = list(persisted['efficiency_invalid']), list(persisted['incomplete'])
        state = list(notes['state'])
        if audits['pending'] or audits['inconclusive']:
            state.append('audits_unresolved')
        unknown = [r for r in rows if r['status'] == 'unresolved']
        if unknown:
            state.append(f'{len(unknown)} jobs unresolved')
        awaiting = [r for r in rows if r['status'] == 'awaiting_verification']
        if awaiting:
            state.append(f'{len(awaiting)} jobs awaiting_verification')
        refused = [a for a in attempts if a['state'] == 'refused']
        for reason in sorted({a['error'] for a in refused}):
            state.append(reason)
        if rec['unresolved_attempts']:
            state.append(f"{len(rec['unresolved_attempts'])} launches without a resolved physical outcome")
        if not rec['ok']:
            state.append('reconciliation_failed')
        charged = tokens['charged']
        if rec['charged_calls'] and charged['usage'] != 'complete':
            invalid.append('usage_' + charged['usage'])
            state.append('usage_incomplete')
        if self.pilot is not None and charged["components_missing"]:
            state.append('usage_components_unknown:' + ','.join(sorted(charged['components_missing'])))
        if self.pilot is not None and self.usage_semantics == 'unverified':
            state.append('usage_semantics_unverified')
        mine = {a['attempt_id'] for a in attempts}
        known = {a['attempt_id'] for a in self.ledger.attempts()}
        for r in self.spool.rejections():
            if r['reason'] != 'unknown_outcome' and (r['attempt_id'] in mine or r['attempt_id'] not in known):
                state.append('spool_rejection:' + r['reason'])
        if any(r.get('memo') for r in rows) and 'memo_served' not in invalid:
            invalid.append('memo_served')
        for reason in state:
            if reason not in incomplete:
                incomplete.append(reason)
        fallback_rows = [r for r in rows if r['phase'] == 'fallback']
        reasons = {}
        for r in fallback_rows:
            reasons[r.get('fallback_reason')] = reasons.get(r.get('fallback_reason'), 0) + 1
        queue = [r['queue_s'] for r in rows if r.get('queue_s') is not None]
        # Timing (B8): measured makespan from the first intake to the last terminal delivery; an importing arm is
        # charged the shared bootstrap's recorded elapsed in full and drops only its own wait for it.
        intake = [s['stamp'] for s in self.ledger.intake(wave)]
        delivered = [{'at': d['at'], 'mono': d['mono'], 'session': d['session']} for d in self.ledger.deliveries(wave)
                     if d['job'] in {j['name'] for j in jobs}]
        first = min(intake, key=lambda s: s['at']) if intake else None
        last = max(delivered, key=lambda s: s['at']) if delivered else None
        measured = max(0.0, _span(first, last) or 0.0)
        phases = self.ledger.phase_seconds(wave)
        boot = notes['bootstrap'] or {}
        charged_makespan = measured
        if boot.get('imported'):
            charged_makespan = measured - phases.get('bootstrap_wait', 0.0) + float(boot.get('elapsed') or 0.0)
        count = lambda **kv: sum(1 for r in rows if all(r.get(k) == v for k, v in kv.items()))
        accepted_with_call = sum(1 for r in rows if r['status'] == 'accepted' and r.get('call_id'))
        report = {
            'schema': REPORT_SCHEMA, 'arm': self.arm, 'backend': self.backend, 'workload': self.workload, 'wave': wave,
            'manifest_sha256': notes.get('manifest_sha256'),
            'jobs': len(rows), 'accepted_by_checks': count(status='accepted'), 'failed': count(status='failed'),
            'awaiting_verification': len(awaiting), 'unresolved': len(unknown),
            'by_source': {s: count(status='accepted', source=s) for s in ('rule', 'model')},
            'rule_hits': count(status='accepted', source='rule'),
            'coverage': round(count(status='accepted', source='rule') / len(rows), 6) if rows else 0.0,
            'fallback': len(fallback_rows), 'fallback_reasons': reasons,
            'abstains': sum(n for r, n in reasons.items() if str(r).startswith('abstain:')),
            'audits': audits, 'quarantined': quarantined, 'quarantine_fallbacks': notes['quarantine_fallbacks'],
            'calls': {'physical': rec['physical_calls'], 'imported': rec['imported_calls'],
                      'charged': rec['charged_calls'], 'attempts': len(attempts), 'refused': len(refused),
                      'by_kind': by_kind,
                      'membership': dict(rec['membership'], accepted_with_call=accepted_with_call)},
            'tokens': tokens, 'bootstrap': notes['bootstrap'],
            'queue_seconds': {'mean': round(sum(queue) / len(queue), 6) if queue else 0.0,
                              'max': round(max(queue), 6) if queue else 0.0},
            'measured_makespan_seconds': round(measured, 6), 'makespan_seconds': round(measured, 6),
            'charged_makespan_seconds': round(charged_makespan, 6), 'phase_seconds': phases,
            'summed_call_seconds': round(sum(a['elapsed'] or 0.0 for a in attempts), 6),
            'budget': self.budget.usage(),
            'reconciliation': {k: rec[k] for k in ('ok', 'problems', 'physical_calls', 'imported_calls',
                                                   'charged_calls', 'unresolved_attempts', 'membership')},
            'efficiency_valid': not invalid, 'efficiency_invalid': invalid,
            'evidence': 'incomplete' if incomplete else 'complete', 'incomplete': incomplete,
            'correctness': CORRECTNESS}
        _publish(self.arm_dir / 'reports' / f'{_b32([wave])[:16]}.json',
                 json.dumps(report, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8'))
        return report


def _tokens(calls) -> dict:
    """Token totals over calls. A call without input and output tokens is a call without usage; a known call that
    lacks a component leaves that component unknown (counted in components_missing, never taken as zero). Field
    presence never establishes inclusive cached or reasoning accounting (B10): the host reports its declared usage
    semantics beside these totals."""
    out = dict.fromkeys(USAGE_FIELDS, 0)
    missing = dict.fromkeys(USAGE_FIELDS, 0)
    known = unknown = 0
    for c in calls:
        usage = c.get('usage')
        if isinstance(usage, dict) and {'input_tokens', 'output_tokens'} <= set(usage):
            known += 1
            for k in USAGE_FIELDS:
                if isinstance(usage.get(k), int) and not isinstance(usage.get(k), bool):
                    out[k] += usage[k]
                else:
                    missing[k] += 1
        else:
            unknown += 1
    out['tokens'] = out['input_tokens'] + out['output_tokens']
    out['calls_with_usage'], out['calls_without_usage'] = known, unknown
    out['components_missing'] = {k: n for k, n in missing.items() if n}
    out['usage'] = 'n/a' if not known + unknown else 'complete' if not unknown else 'none' if not known else 'partial'
    return out


def _add_tokens(a, b) -> dict:
    out = {k: a[k] + b[k] for k in (*USAGE_FIELDS, 'tokens', 'calls_with_usage', 'calls_without_usage')}
    out['components_missing'] = {k: a['components_missing'].get(k, 0) + b['components_missing'].get(k, 0)
                                 for k in set(a['components_missing']) | set(b['components_missing'])}
    unknown, known = out['calls_without_usage'], out['calls_with_usage']
    out['usage'] = 'n/a' if not known + unknown else 'complete' if not unknown else 'none' if not known else 'partial'
    return out


# ------------------------------------------------------------------------------------------------- dry run

CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}


class ReplayAdapter:
    """A fake model behind bootstrap_shim.CallableShim: answers each job with answer(text), proposes `rules` (exact
    AST JSON text per op, or "none") in the oz-bootstrap/1 envelope when the system text carries the bootstrap
    instruction, and serves recorded usage samples in order (bootstrap samples for the bootstrap call). Zero external
    calls. Every call is logged with its job ids and sample."""
    capabilities = CAPS

    def __init__(self, answer, rules=None, samples=None, bootstrap_samples=None, envelope=None):
        self.answer, self.rules = answer, dict(rules or {})
        self.samples = list(samples or [{'input_tokens': 100, 'output_tokens': 10}])
        self.bootstrap_samples = list(bootstrap_samples or self.samples)
        self.envelope = envelope
        self.log, self.lock, self.n, self.nb = [], threading.Lock(), 0, 0

    def __call__(self, req):
        shim = _shim()
        body = json.loads(req['prompt'])
        answers = {}
        for block in body['jobs']:
            for row in block[1:]:
                answers[row[0]] = self.answer(body['refs'][row[1]])
        from oz_reply import encode_reply
        reply = encode_reply(answers)  # an oz_reply.Failure answer becomes that job's error line
        bootstrap = shim.INSTRUCTION in req['system']
        with self.lock:
            if bootstrap:
                sample = self.bootstrap_samples[self.nb % len(self.bootstrap_samples)]
                self.nb += 1
            else:
                sample = self.samples[self.n % len(self.samples)]
                self.n += 1
            self.log.append({'ids': list(req.get('ids') or answers), 'bootstrap': bootstrap, 'sample': sample})
        if bootstrap:
            if self.envelope is not None:
                reply = self.envelope(reply)
            else:
                rules = ','.join(json.dumps(op) + ':' + (json.dumps('none') if ast == 'none' else ast)
                                 for op, ast in self.rules.items())
                reply = '{"host":"oz-bootstrap/1","answers":' + json.dumps(reply, ensure_ascii=False) + \
                        ',"rules":{' + rules + '}}'
        return {'reply': reply, 'usage': {k: sample[k] for k in USAGE_FIELDS if k in sample}}

    def calls(self, bootstrap=None) -> list:
        return [e for e in self.log if bootstrap is None or e['bootstrap'] == bootstrap]


def identity_for(route: dict) -> dict:
    """The host identity for a frozen route (D7): worker_hash and the oz_do route pins."""
    import oz_route
    return {'route': route, 'worker_hash': oz_route.worker_hash(route),
            'do_route': {'adapter': route['adapter_hash'], 'model': route['model'], 'effort': route['effort'],
                         'cli_version': route['cli_version']}}


def _project(attempts, log, slots) -> float:
    """Projected seconds of a host wave: each round's recorded call elapsed list-scheduled over the slots."""
    elapsed = {}
    for entry in log:
        elapsed[frozenset(entry['ids'])] = float(entry['sample'].get('elapsed_seconds', 0.0))
    rounds = {}
    for a in attempts:
        if a['state'] == 'refused' or not a['call_ids']:
            continue
        rounds.setdefault(a['round'], []).append(elapsed.get(frozenset(a['records']), 0.0))
    total = 0.0
    for name in sorted(rounds, key=lambda r: ('bootstrap', 'r1', 'r2', 'r3').index(r) if r in
                       ('bootstrap', 'r1', 'r2', 'r3') else 9):
        finish = [0.0] * slots
        for seconds in rounds[name]:
            k = finish.index(min(finish))
            finish[k] += seconds
        total += max(finish)
    return total


def arm_order(seed: int, backend: str, workload: str, arms) -> list:
    """The frozen seeded arm order within one cell."""
    return sorted(arms, key=lambda a: (hashlib.sha256(canonical([seed, backend, workload, a])).hexdigest(), a))


def submit_barrier(host, wave_name, producers: dict, submission) -> None:
    """The scripted producers start together: one thread per producer, released by one barrier, each submitting its
    whole submission (council 3, B12: the four producers start from a common barrier in dry run and live)."""
    barrier = threading.Barrier(len(producers))
    errors = []

    def run(producer, jobs):
        try:
            barrier.wait(timeout=60)
            host.submit(producer, submission(producer), jobs, wave=wave_name)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(p, js), name=f'producer-{p}')
               for p, js in sorted(producers.items())]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise errors[0]


def dry_run(matrix: dict, recorded_usage: dict) -> dict:
    """Run the matrix with replay adapters at zero external calls; report the would-be numbers and budget use.

    matrix: {"seed": int, "caps": {backend: {bucket: n}}, "global_cap": n, "experiment_dir": optional path,
             "slots": 4, "max_wait": seconds, "intake": optional {"producers", "per_producer"},
             "pilot": optional frozen configuration (mode "dry"), "usage_semantics": optional,
             "cells": [{"backend", "workload", "registry" (oz_registry.Registry),
             "op" (an id, or {op id: op text} for several), "op_text" (None for several), "goal" (optional),
             "model", "effort", "route", "checks" (optional), "answer" (text -> value),
             "rules" ({op: exact AST JSON text or "none"}), "arms": ["A", "B", "C"],
             "waves": [{"name", "learn": bool, "arms": optional subset, "producers": {producer: [jobs]}}]}]}
    recorded_usage: {backend: {"call": [usage samples], "bootstrap": [samples]}}; a sample holds usage fields and
             optionally "elapsed_seconds".
    Every host of the experiment shares one budget and one experiment-wide slot pool of `slots`; the producers of
    each wave submit concurrently from a common barrier."""
    import tempfile
    shim = _shim()
    temp = None
    root = matrix.get('experiment_dir')
    if root is None:
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = temp.name
    root = Path(root)
    seed = matrix['seed']
    budget = Budget(root / 'budget.sqlite', caps=matrix.get('caps'), global_cap=matrix.get('global_cap'))
    slots = matrix.get('slots', 4)
    pool = SlotPool(root / 'slots', slots)
    pilot = matrix.get('pilot')
    out = {'schema': 'oz.host.dryrun/1', 'cells': [], 'external_calls': 0}
    hosts, adapters = [], []
    try:
        for cell in matrix['cells']:
            usage = recorded_usage.get(cell['backend']) or {}
            order = arm_order(seed, cell['backend'], cell['workload'], cell['arms'])
            cell_out = {'backend': cell['backend'], 'workload': cell['workload'], 'arm_order': order, 'waves': []}
            arm_hosts = {}
            for arm in order:
                adapter = ReplayAdapter(cell['answer'], cell.get('rules'), usage.get('call'), usage.get('bootstrap'),
                                        envelope=cell.get('envelope'))
                adapters.append(adapter)
                extra = {}
                if pilot is not None:
                    extra = dict(pilot=pilot, limits=pilot['limits'], max_records=pilot['max_records'],
                                 usage_semantics=pilot['usage_semantics'])
                else:
                    extra = dict(expected_intake=matrix.get('intake'),
                                 usage_semantics=matrix.get('usage_semantics', 'unverified'))
                host = ArmHost(arm=arm, backend=cell['backend'], workload=cell['workload'], experiment_dir=root,
                               launcher=InProcessLauncher(shim.CallableShim(adapter)), op=cell['op'],
                               op_text=cell.get('op_text'), goal=cell.get('goal', GOAL), model=cell['model'],
                               effort=cell['effort'],
                               identity=cell.get('identity') or identity_for(cell['route']),
                               checks=cell.get('checks'), registry=cell.get('registry'),
                               seed=seed if arm != 'A' else None, budget=budget, slots=slots, slot_pool=pool,
                               max_wait=matrix.get('max_wait', 0.05) if pilot is None else pilot['max_wait'],
                               allow_experimental=True,
                               producers_expected=cell.get('producers_expected', rp.BOOTSTRAP_PRODUCERS),
                               bootstrap_per_producer=cell.get('bootstrap_per_producer', rp.BOOTSTRAP_PER_PRODUCER),
                               **extra)
                hosts.append(host)
                arm_hosts[arm] = (host, adapter)
            for wave in cell['waves']:
                wave_out = {'name': wave['name'], 'learn': wave.get('learn', True), 'arms': {}}
                for arm in [a for a in order if a in (wave.get('arms') or order)]:
                    host, adapter = arm_hosts[arm]
                    submit_barrier(host, wave['name'], wave['producers'],
                                   lambda p, w=wave['name'], a=arm: f's{w}{a}{p}'[:64])
                    before = len(adapter.log)
                    report = host.run_wave(wave['name'], learn=wave.get('learn', True))
                    log = adapter.log[before:]
                    attempts = host.ledger.attempts(wave['name'])
                    projected = _project(attempts, log, slots)
                    boot = report['bootstrap'] or {}
                    if boot.get('imported'):
                        projected += float(boot.get('projected_elapsed') or _boot_elapsed(usage))
                    report['projected_makespan_seconds'] = round(projected, 3)
                    report['replayed_calls'] = len(log)
                    report['replayed_call_seconds'] = round(sum(float(e['sample'].get('elapsed_seconds', 0.0))
                                                                for e in log), 3)
                    wave_out['arms'][arm] = report
                cell_out['waves'].append(wave_out)
            out['cells'].append(cell_out)
        out['budget'] = budget.usage()
        out['physical_calls'] = sum(len([c for a in h.ledger.attempts() for c in a['call_ids']]) for h in hosts)
        out['replayed_calls'] = sum(len(a.log) for a in adapters)
        cap = (matrix.get('global_cap'))
        refused = sum(r['calls']['refused'] for c in out['cells'] for w in c['waves'] for r in w['arms'].values())
        out['fits'] = refused == 0 and (cap is None or out['physical_calls'] <= cap)
        out['evidence'] = 'complete' if all(r['evidence'] == 'complete' for c in out['cells'] for w in c['waves']
                                            for r in w['arms'].values()) and out['fits'] else 'incomplete'
        out['reconciliation'] = _global_reconciliation(out)
        return out
    finally:
        for host in hosts:
            host.close()
        budget.close()
        if temp is not None:
            temp.cleanup()


def _boot_elapsed(usage) -> float:
    samples = usage.get('bootstrap') or usage.get('call') or []
    return float(samples[0].get('elapsed_seconds', 0.0)) if samples else 0.0


def _global_reconciliation(out) -> dict:
    """Physical calls are counted once; the analytic charge adds every imported bootstrap in full."""
    physical = imported = charged = 0
    for c in out['cells']:
        for w in c['waves']:
            for r in w['arms'].values():
                physical += r['calls']['physical']
                imported += r['calls']['imported']
                charged += r['calls']['charged']
    return {'physical_calls': physical, 'imported_calls': imported, 'charged_calls': charged,
            'ok': charged == physical + imported and physical == out['physical_calls'] == out['replayed_calls']}


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        raise SystemExit(child_main(sys.argv[2]))
    sys.stderr.write('usage: oz_host.py --child SPEC_FILE (the host launches it; there is no other entry point)\n')
    raise SystemExit(2)
