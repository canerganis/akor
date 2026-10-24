"""oz host: the step 6 host for the A/B/C kill pilot (amendment 2 and council 2). Standard library only.

One ArmHost per (arm, backend, workload) runs one arm:
  A  ordinary pooled map: every job goes to the model in pooled batches.
  B  rules with producer-local fallback: bootstrap (shared), rule phase, then fallback and audit jobs pooled only
     within one producer.
  C  identical rules with pooled fallback across producers.

Topology. Producers hand submissions to the host (submit(); the intake is persisted in the host ledger with conflict
detection). The host owns one oz_spool.Spool and one oz_spool.Scheduler (W2: OS host lock, fencing epoch, 4 slots,
64-record batches, durable reservation before launch). Every job the host sends to a model (A's jobs, the bootstrap,
fallbacks, audits) is submitted to that spool and drained by the Scheduler; the rule phase runs before any of it is
submitted, so covered jobs never enter a batch. Rule rows and imported bootstrap rows are delivered by the host itself
with zero calls. collect(producer, submission) returns every delivered row.

Physical calls. launch(view) builds one oz.do/1 request whose request_id is the spool's request id (derived from the
batch id) and runs it in a child process (ChildLauncher: `python oz_host.py --child SPEC`, an explicit isolated env,
the host never touches os.environ) or in process for callable fake adapters (InProcessLauncher, which passes the same
env dict to the adapter). execute() caps the request at one physical call through oz_do's admit hook, counting calls
already in the run's ledger, so a re-dispatch of the same request resumes oz_do's run and never makes a second call.
Every request sets max_attempts 1: there are no hidden worker retries, and A2.1 forbids replacement answers. Before
anything is parsed, the child's stdout, stderr, exit code and timeout flag are written under the physical attempt id
(attempts/<attempt id>/).

Ledgers (ledger.sqlite per host). attempts: one row per physical attempt id (the spool's), its round, job membership
counts, budget bucket, raw evidence hashes, call ids, elapsed. calls: one immutable row per physical call id with
every usage component (unknown stays unknown, never zero). allocations: one immutable row per (call, job, basis):
job membership with its kind (bootstrap, fallback, audit, ordinary; mixed calls are allowed) and share 1/n of the
call; basis "physical" for this host's own calls and "imported" for the shared bootstrap call charged analytically to
an arm that did not run it. Reconciliation: every call's shares sum to 1 and match its batch size, every allocated call
exists, charged = physical + imported; the bootstrap is charged physically once and in full to each of B and C.

Budget (budget.sqlite per experiment). Frozen call caps per backend and bucket (A, B, C, bootstrap, reserve) plus the
global cap, frozen at first use; a reservation per request id (one physical call at most) is taken atomically in
launch() before the child starts. A bucket falls back to "reserve"; when both are exhausted the batch is not launched,
its jobs are unresolved and the arm's evidence is incomplete.

Shared bootstrap (oz_rulephase.ExperimentStore). B or C, whichever claims first, runs exactly one bootstrap batch of
16 jobs from each of the 4 producers (frozen assignment by seeded hash of dataset ids) with OZ_BOOTSTRAP_ATTEMPT and
OZ_BOOTSTRAP_DIR set in that child's env only, then records the immutable bootstrap record (answers by dataset id, the
shim's side file, the attempt ledger entry, status, efficiency_valid). The other arm imports it. Never re-learned; a
failed bootstrap keeps its failure (no replacement answers, efficiency invalid).

Audits. One evaluation wave = all producers' submissions of one wave name. The population of covered frozen dataset
ids and the min(32, covered) selection are persisted in the experiment store before dispatch, so B and C audit the
same ids; pending audit rows are persisted in the arm's rule store first. Inconclusive audits get one retry (reserve);
pending or inconclusive audits leave the evidence incomplete and block warm reuse.

Rule delivery (DRIVER rule 8). With rule_delivery="after_audits" (default) covered jobs are staged with complete
passing evidence and settled (adopt_rule) only after the wave's audits are decided; if a disagreement quarantined
the rule, adopt_rule refuses and those undelivered rows fall back to the model. "immediate" settles at once; delivered
rows always stay as recorded.

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


class ChildLauncher:
    """Each physical attempt is a child process `python oz_host.py --child SPEC` running one oz_do request with the
    adapter JSON file, under the explicit env the host built."""

    def __init__(self, adapter, *, timeout: float = 3600.0, python: str | None = None):
        self.adapter = Path(adapter).resolve()
        self.timeout, self.python = timeout, python or sys.executable

    def __call__(self, spec: dict, env: dict, evidence_dir: Path) -> tuple:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        out = evidence_dir / 'execution.json'
        spec = dict(spec, adapter=str(self.adapter), out=str(out))
        spec_file = evidence_dir / 'spec.json'
        _publish(spec_file, json.dumps(spec, ensure_ascii=False).encode('utf-8'))
        try:
            done = subprocess.run([self.python, str(HOST_FILE), '--child', str(spec_file)], env=env,
                                  capture_output=True, timeout=self.timeout, stdin=subprocess.DEVNULL,
                                  cwd=str(HOST_FILE.parent))
            raw = {'exit_code': done.returncode, 'timed_out': False, 'stdout': done.stdout, 'stderr': done.stderr}
        except subprocess.TimeoutExpired as exc:
            raw = {'exit_code': None, 'timed_out': True, 'stdout': exc.stdout or b'', 'stderr': exc.stderr or b''}
        except OSError as exc:
            raise oz_spool.LaunchNotStarted(f'cannot start the child process: {exc}') from None
        meta = _write_raw(evidence_dir, raw)
        execution = None
        if raw['exit_code'] == 0 and out.exists():
            execution = json.loads(out.read_text(encoding='utf-8'))
        return execution, meta


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


LEDGER_TABLES = '''
CREATE TABLE IF NOT EXISTS intake(
    producer TEXT NOT NULL, submission TEXT NOT NULL, wave TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
    submitted_at REAL NOT NULL, PRIMARY KEY(producer, submission));
CREATE TABLE IF NOT EXISTS attempts(
    attempt_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, batch_id TEXT NOT NULL, arm TEXT NOT NULL,
    backend TEXT NOT NULL, workload TEXT NOT NULL, wave TEXT NOT NULL, round TEXT NOT NULL, group_kind TEXT NOT NULL,
    kinds TEXT NOT NULL, records TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('launched','captured','failed',
    'refused')), launches INTEGER NOT NULL, bucket TEXT, exit_code INTEGER, timed_out INTEGER, stdout_sha256 TEXT,
    stderr_sha256 TEXT, evidence_dir TEXT, call_ids TEXT, elapsed REAL, started_at REAL, ended_at REAL, error TEXT);
CREATE TABLE IF NOT EXISTS calls(
    call_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, request_id TEXT NOT NULL, outcome TEXT, usage TEXT,
    usage_known INTEGER NOT NULL, input_tokens INTEGER, cached_input_tokens INTEGER, cache_creation_input_tokens INTEGER,
    output_tokens INTEGER, reasoning_output_tokens INTEGER, elapsed_ms INTEGER);
CREATE TRIGGER IF NOT EXISTS calls_immutable BEFORE UPDATE ON calls BEGIN SELECT RAISE(ABORT, 'calls are immutable'); END;
CREATE TRIGGER IF NOT EXISTS calls_keep BEFORE DELETE ON calls BEGIN SELECT RAISE(ABORT, 'calls are kept'); END;
CREATE TABLE IF NOT EXISTS allocations(
    seq INTEGER PRIMARY KEY, arm TEXT NOT NULL, backend TEXT NOT NULL, workload TEXT NOT NULL, wave TEXT NOT NULL,
    attempt_id TEXT NOT NULL, call_id TEXT NOT NULL, job TEXT NOT NULL, original TEXT NOT NULL, producer TEXT NOT NULL,
    dataset_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('bootstrap','fallback','audit','ordinary')),
    share REAL NOT NULL, basis TEXT NOT NULL CHECK(basis IN ('physical','imported')), UNIQUE(call_id, job, basis));
CREATE TRIGGER IF NOT EXISTS allocations_immutable BEFORE UPDATE ON allocations
    BEGIN SELECT RAISE(ABORT, 'allocations are immutable'); END;
CREATE TRIGGER IF NOT EXISTS allocations_keep BEFORE DELETE ON allocations
    BEGIN SELECT RAISE(ABORT, 'allocations are kept'); END
'''


def _usage_columns(usage) -> tuple:
    known = isinstance(usage, dict) and {'input_tokens', 'output_tokens'} <= set(usage)
    return (1 if known else 0, *[(usage.get(k) if isinstance(usage, dict) else None) for k in USAGE_FIELDS])


class Ledger:
    """The host's physical attempt ledger, call ledger, allocation ledger and persisted intake."""

    def __init__(self, path):
        self.db = _db(Path(path), LEDGER_TABLES)
        self.lock = threading.Lock()

    def close(self):
        self.db.close()

    def tx(self):
        return rp._Tx(self.db)

    # intake
    def add_intake(self, producer, submission, wave, jobs, at) -> None:
        payload = canonical({'wave': wave, 'jobs': jobs}).decode('utf-8')
        with self.lock, self.tx() as db:
            row = db.execute('SELECT sha256 FROM intake WHERE producer=? AND submission=?',
                             (producer, submission)).fetchone()
            if row is not None:
                if row[0] != _sha(payload):
                    raise oz_spool.SubmissionConflict(f'submission {producer}/{submission} exists with another payload')
                return
            db.execute('INSERT INTO intake VALUES (?,?,?,?,?,?)', (producer, submission, wave, payload, _sha(payload),
                                                                  at))

    def intake(self, wave) -> list:
        return [dict(producer=r['producer'], submission=r['submission'], submitted_at=r['submitted_at'],
                     jobs=json.loads(r['payload'])['jobs'])
                for r in self.db.execute('SELECT * FROM intake WHERE wave=? ORDER BY producer, submission', (wave,))]

    # attempts and calls
    def launched(self, *, attempt_id, request_id, batch_id, arm, backend, workload, wave, round_, group_kind, kinds,
                 records, bucket, evidence_dir, at) -> None:
        with self.lock, self.tx() as db:
            row = db.execute('SELECT launches FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
            if row is None:
                db.execute("INSERT INTO attempts(attempt_id, request_id, batch_id, arm, backend, workload, wave, round, "
                           "group_kind, kinds, records, state, launches, bucket, evidence_dir, started_at) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?,'launched',1,?,?,?)",
                           (attempt_id, request_id, batch_id, arm, backend, workload, wave, round_, group_kind,
                            json.dumps(kinds), json.dumps(records), bucket, str(evidence_dir), at))
            else:
                db.execute("UPDATE attempts SET launches=launches+1, state='launched' WHERE attempt_id=?",
                           (attempt_id,))

    def refused(self, *, attempt_id, request_id, batch_id, arm, backend, workload, wave, round_, group_kind, kinds,
                records, at, error) -> None:
        with self.lock, self.tx() as db:
            db.execute("INSERT OR IGNORE INTO attempts(attempt_id, request_id, batch_id, arm, backend, workload, wave, "
                       "round, group_kind, kinds, records, state, launches, started_at, ended_at, error) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?,'refused',0,?,?,?)",
                       (attempt_id, request_id, batch_id, arm, backend, workload, wave, round_, group_kind,
                        json.dumps(kinds), json.dumps(records), at, at, error))

    def finished(self, attempt_id, *, meta, execution, elapsed, at, error=None) -> None:
        calls = (execution or {}).get('calls') or []
        with self.lock, self.tx() as db:
            db.execute('UPDATE attempts SET state=?, exit_code=?, timed_out=?, stdout_sha256=?, stderr_sha256=?, '
                       'call_ids=?, elapsed=?, ended_at=?, error=? WHERE attempt_id=?',
                       ('captured' if execution is not None else 'failed', meta['exit_code'], int(meta['timed_out']),
                        meta['stdout_sha256'], meta['stderr_sha256'], json.dumps([c['call_id'] for c in calls]),
                        elapsed, at, error, attempt_id))
            request_id = db.execute('SELECT request_id FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()[0]
            for c in calls:
                if db.execute('SELECT 1 FROM calls WHERE call_id=?', (c['call_id'],)).fetchone() is None:
                    db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                               (c['call_id'], attempt_id, request_id, c['outcome'],
                                json.dumps(c['usage']) if c['usage'] is not None else None,
                                *_usage_columns(c['usage']), c.get('elapsed_ms')))

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
        return None if row is None else dict(row, usage=json.loads(row['usage']) if row['usage'] else None)

    # allocations
    def allocate(self, rows) -> None:
        with self.lock, self.tx() as db:
            for r in rows:
                db.execute('INSERT OR IGNORE INTO allocations(arm, backend, workload, wave, attempt_id, call_id, job, '
                           'original, producer, dataset_id, kind, share, basis) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (r['arm'], r['backend'], r['workload'], r['wave'], r['attempt_id'], r['call_id'], r['job'],
                            r['original'], r['producer'], r['dataset_id'], r['kind'], r['share'], r['basis']))

    def allocations(self, wave=None) -> list:
        rows = (self.db.execute('SELECT * FROM allocations ORDER BY seq') if wave is None else
                self.db.execute('SELECT * FROM allocations WHERE wave=? ORDER BY seq', (wave,)))
        return [dict(r) for r in rows]


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
    nothing frozen yet means unlimited (single-user oz map); once frozen, caps never change."""

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

    def usage(self) -> dict:
        used = {}
        for r in self.db.execute('SELECT backend, bucket, COUNT(*) FROM reservations GROUP BY backend, bucket'):
            used.setdefault(r[0], {})[r[1]] = r[2]
        total = sum(n for b in used.values() for n in b.values())
        return {'frozen': self.frozen, 'used': used, 'total': total}


# --------------------------------------------------------------------------------------------------- the host

class ArmHost:
    """One arm (A, B or C) on one backend and workload. See the module docstring."""

    def __init__(self, *, arm, backend, experiment_dir, launcher, op, op_text, model, effort, identity,
                 workload=None, goal=GOAL, checks=None, registry=None, seed=None, budget=None,
                 producers_expected=rp.BOOTSTRAP_PRODUCERS, bootstrap_per_producer=rp.BOOTSTRAP_PER_PRODUCER,
                 slots=4, max_records=64, max_wait=1.0, rule_delivery='after_audits', audit_retry=True,
                 allow_experimental=False, experimental_sizes=(), limits=None, do_workspace=None, rule_store=None,
                 wall=time.time, clock=time.monotonic, bootstrap_wait=1800.0, hooks=None, owner=None, base_env=None):
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
        self.wall, self.clock, self.bootstrap_wait = wall, clock, bootstrap_wait
        self.hooks = dict(hooks or {})
        self.base_env = base_env
        self.map_contract = digest({'op': op, 'op_text': op_text, 'goal': goal, 'checks': self.pinned,
                                    'profile': PROFILE})
        self.experiment_dir = Path(experiment_dir).resolve()
        self.learner = self.store = self.scheduler = self.spool = self.ledger = self.budget = None
        self._owner_arg = owner
        self._own_budget = False
        self.experiment = rp.ExperimentStore(self.experiment_dir / 'experiment.sqlite', clock=wall)
        try:
            self._setup(arm, backend, workload, registry, seed, op, rule_store, do_workspace, budget, slots,
                        max_records, max_wait, clock, wall)
        except BaseException:
            self.close()
            raise
        self._groups, self._items = {}, {}
        self._rows = {}

    def _setup(self, arm, backend, workload, registry, seed, op, rule_store, do_workspace, budget, slots,
               max_records, max_wait, clock, wall):
        if arm in ('B', 'C'):
            if registry is None:
                raise Error(f'arm {arm} needs an owner-approved oz_registry.Registry')
            if type(seed) is not int or isinstance(seed, bool):
                raise Error(f'arm {arm} needs a frozen integer seed')
        self.workload = _name_ok('workload', workload) if workload is not None else None
        if registry is not None:
            # Arm A with a registry settles its model answers through the same settlement boundary (every applicable
            # pinned check), so accepted_by_checks means the same thing in every arm; it never runs a rule phase.
            # Without a workload name (oz map) the workload derives from the binding key.
            probe_dir = self.experiment_dir / 'arms'
            path = Path(rule_store) if rule_store is not None else None
            if path is None and self.workload is None:
                raise Error('give workload (or rule_store) for an arm with a registry')
            self.store = rp.RuleStore(path or probe_dir / f'{backend}-{self.workload}-{arm}' / 'rules.sqlite',
                                      clock=wall)
            self.learner = rp.Learner(self.store, registry, op, worker_hash=self.worker,
                                      map_contract=self.map_contract, map_input_policy=INPUT_POLICY,
                                      map_pinned=self.pinned)
            if self.workload is None:
                self.workload = 'k' + self.learner.key[:24]
        elif self.workload is None:
            self.workload = 'k' + self.map_contract[:24]
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
        self.settle_bindings = digest([self.learner.key if self.learner else self.map_contract, arm, backend,
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

    # ------------------------------------------------------------------------------------------- intake

    def submit(self, producer: str, submission: str, jobs, *, wave: str) -> list:
        """A producer submission for one wave (jobs exactly {key, op, text, dataset_id}). Returns the job names."""
        _name_ok('producer', producer)
        _name_ok('submission', submission)
        jobs = oz_spool._validate_jobs(jobs)
        if any(j['op'] != self.op for j in jobs):
            raise Error(f'this host runs operation {self.op!r} only')
        self.ledger.add_intake(producer, submission, wave, jobs, self.wall())
        return [oz_spool.delivery_id(producer, submission, j['op'], j['key']) for j in jobs]

    def collect(self, producer: str, submission: str) -> list:
        return [r for r in self._rows.values() if r['producer'] == producer and r['submission'] == submission]

    def _jobs(self, wave) -> list:
        out = []
        for sub in self.ledger.intake(wave):
            for j in sub['jobs']:
                resolved, removed = apply_input_policy(j['text'])
                bad = not resolved.strip() or len(resolved.encode('utf-8')) > MAX_REF_BYTES
                receipt = {'policy': INPUT_POLICY, 'raw_sha256': _sha(j['text']), 'resolved_sha256': _sha(resolved),
                           'removed': removed}
                out.append({'name': oz_spool.delivery_id(sub['producer'], sub['submission'], j['op'], j['key']),
                            'producer': sub['producer'], 'submission': sub['submission'], 'key': j['key'],
                            'op': j['op'], 'dataset_id': j['dataset_id'], 'text': resolved, 'receipt': receipt,
                            'submitted_at': sub['submitted_at'], 'invalid': bad,
                            'payload_sha256': digest({'op': j['op'], 'op_text': self.op_text, 'goal': self.goal,
                                                      'dataset_id': j['dataset_id'], 'receipt': receipt})})
        return out

    # ---------------------------------------------------------------------------------------- dispatch

    def _bindings(self, group_kind: str, pool: str) -> dict:
        return {'contract_hash': digest([self.map_contract, self.arm, self.backend, self.workload, group_kind, pool]),
                'check_hash': digest(self.pinned), 'permission_hash': digest({}), 'worker_hash': self.worker,
                'input_policy': INPUT_POLICY}

    def _dispatch(self, wave: str, round_: str, items: list, group_kind: str = 'dispatch') -> dict:
        """Submit items to the spool (grouped by pool, one spool submission per producer, submission and round),
        drain through the Scheduler, reconcile unknown attempts without a second call, record allocations.
        Returns {item id: (result or None, spool row or None)}."""
        if not items:
            return {}
        groups = {}
        for item in items:
            groups.setdefault((item['pool'], item['producer'], item['submission']), []).append(item)
        subs = []
        for (pool, producer, submission), its in groups.items():
            bindings = self._bindings(group_kind, pool)
            self._groups[oz_spool.bindings_hash(bindings)] = {'kind': group_kind, 'pool': pool, 'wave': wave,
                                                               'round': round_}
            tag = round_ + _b32(sorted(i['key'] for i in its))[:8]
            spool_sub = subname(submission, tag)
            jobs = [{'key': i['key'], 'op': self.op, 'text': i['text'], 'dataset_id': i['dataset_id']} for i in its]
            ids = list(self.spool.submit(producer, spool_sub, jobs, bindings))
            for delivery, item in zip(ids, its):
                item['delivery'] = delivery
                self._items[delivery] = item
            subs.append((producer, spool_sub))
        self.scheduler.run(until_idle=True, poll=0.02)
        self.reconcile_unknown()
        rows = {}
        for producer, spool_sub in subs:
            rows.update(self.spool.collect(producer, spool_sub)['results'])
        out, sizes = {}, {}
        for row in rows.values():
            sizes[row['attempt_id']] = sizes.get(row['attempt_id'], 0) + 1
        allocations = []
        for item in items:
            row = rows.get(item['delivery'])
            out[item['id']] = (row['result'] if row else None, row)
            if row and row.get('call_id'):
                allocations.append({'arm': self.arm, 'backend': self.backend, 'workload': self.workload, 'wave': wave,
                                    'attempt_id': row['attempt_id'], 'call_id': row['call_id'],
                                    'job': item['delivery'], 'original': item['job']['name'],
                                    'producer': item['job']['producer'], 'dataset_id': item['dataset_id'],
                                    'kind': item['kind'], 'share': 1.0 / sizes[row['attempt_id']],
                                    'basis': 'physical'})
        self.ledger.allocate(allocations)
        return out

    def _request(self, request_id: str, records: list) -> dict:
        request = {'v': 'oz.do/1', 'request_id': request_id, 'goal': self.goal, 'ops': {self.op: self.op_text},
                   'refs': {'r' + r['id'][1:]: r['text'] for r in records},
                   'jobs': [[r['id'], self.op, 'r' + r['id'][1:]] for r in records], 'profile': PROFILE,
                   'allow_experimental': bool(self.allow_experimental), 'max_inline_bytes': MAX_INLINE,
                   'max_attempts': 1, 'max_jobs_per_call': len(records),
                   'max_input_tokens': self.limits.get('max_input_tokens', 1000000)}
        if self.model:
            request['model'] = self.model
        for key in ('deadline_seconds', 'call_timeout_seconds'):
            if key in self.limits:
                request[key] = self.limits[key]
        if self.check_specs:
            request['checks'] = {self.op: self.check_specs}
        return request

    def _spec(self, request: dict, max_calls: int) -> dict:
        return {'workspace': str(self.do_workspace), 'request': request, 'max_calls': max_calls,
                'route': self.identity.get('do_route'), 'experimental_sizes': list(self.experimental_sizes)}

    def _launch(self, view: dict) -> dict:
        """The Scheduler's launch: budget reservation, then one child process for one oz_do request."""
        group = self._groups[view['bindings_hash']]
        records = view['records']
        aid, rid = view['attempt_id'], view['request_id']
        items = [self._items[r['id']] for r in records]
        kinds = {}
        for item in items:
            kinds[item['kind']] = kinds.get(item['kind'], 0) + 1
        common = dict(attempt_id=aid, request_id=rid, batch_id=view['batch_id'], arm=self.arm, backend=self.backend,
                      workload=self.workload, wave=group['wave'], round_=group['round'], group_kind=group['kind'],
                      kinds=kinds, records=[r['id'] for r in records])
        buckets = (['bootstrap', self.arm, 'reserve'] if group['kind'] == 'bootstrap' else
                   [self.arm, 'reserve'] if not group['round'].startswith(('r2', 'r3')) else ['reserve', self.arm])
        # launch_gate(view) may refuse a launch (for example oz_quota's projected weekly usage); it runs before the
        # reservation, so a refused launch consumes no budget.
        gate = self.hooks.get('launch_gate')
        refusal = gate(view) if gate is not None else None
        bucket = None if refusal else self.budget.reserve(rid, backend=self.backend, buckets=buckets, arm=self.arm,
                                                          kind=group['kind'])
        if bucket is None:
            self.ledger.refused(**common, at=self.wall(), error=refusal or 'budget_exhausted')
            return {'results': {r['id']: {'status': 'unresolved', 'error': refusal or 'budget_exhausted',
                                          'call_id': None}
                                for r in records}, 'call_id': None}
        extra = None
        if group['kind'] == 'bootstrap':
            self.side_dir.mkdir(parents=True, exist_ok=True)
            config = self.learner.bootstrap_config()
            _publish(self.side_dir / f'{aid}.config.json', json.dumps(config, ensure_ascii=False).encode('utf-8'))
            extra = {'OZ_BOOTSTRAP_ATTEMPT': aid, 'OZ_BOOTSTRAP_DIR': str(self.side_dir)}
        env = child_env(model=self.model, effort=self.effort, extra=extra, base=self.base_env)
        evidence = self.arm_dir / 'attempts' / aid
        self.ledger.launched(**common, bucket=bucket, evidence_dir=evidence, at=self.wall())
        started = self.clock()
        execution, meta = self.launcher(self._spec(self._request(rid, records), 1), env, evidence)
        self.ledger.finished(aid, meta=meta, execution=execution, elapsed=self.clock() - started, at=self.wall(),
                             error=None if execution is not None else f"child exit {meta['exit_code']}")
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
        """Resolve unknown attempts by resuming their oz_do request with a zero call cap (never a second call), then
        handing the capture to Scheduler.reconcile. Returns the attempt ids it resolved."""
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
            evidence = self.arm_dir / 'attempts' / (entry['attempt_id'] + '-reconcile')
            env = child_env(model=self.model, effort=self.effort, base=self.base_env)
            execution, meta = self.launcher(self._spec(self._request(rid, records), 0), env, evidence)
            if execution is None:
                continue
            self.ledger.finished(entry['attempt_id'], meta=meta, execution=execution, elapsed=None, at=self.wall(),
                                 error='reconciled')
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
        row['delivered_at'] = self.wall()
        row['queue_s'] = round(row.pop('_queued_at', row['delivered_at']) - job['submitted_at'], 6)
        self._rows[job['name']] = row
        return row

    def _model_row(self, job, result, srow, *, phase, kind, reason=None) -> dict:
        base = {'phase': phase, 'call_kind': kind}
        if reason is not None:
            base['fallback_reason'] = reason
        if srow is not None:
            base.update(call_id=result.get('call_id') or srow.get('call_id'), attempt_id=srow['attempt_id'],
                        request_id=srow['request_id'], _queued_at=srow['reserved_at'])
        if result is None:
            return self._row(job, status='unresolved', error='attempt_unknown: outcome not reconciled', **base)
        if result.get('status') != 'accepted':
            return self._row(job, status='unresolved' if result.get('status') == 'unresolved' else 'failed',
                             error=result.get('error') or result.get('status'), **base)
        if result.get('memo'):
            base['memo'] = True
        if self.store is None:
            return self._row(job, status='accepted', value_text=result['value_text'], **base)
        return self._settle_model(job, result['value_text'], base)

    def _settle_model(self, job, value_text, base) -> dict:
        generation = self.store.claim(job['name'])
        if generation is None:
            return self._resumed_row(job, base)
        checks = self.learner.evidence(value_text, job['text'], self.op_text)
        state, detail = self.store.settle_model(job['name'], generation=generation,
                                                payload_sha256=job['payload_sha256'],
                                                bindings_sha256=self.settle_bindings, value_text=value_text,
                                                checks=checks, phase=base['phase'], call_id=base.get('call_id'))
        if state == 'settled':
            return self._row(job, status='accepted', value_text=value_text, checks=checks, **base)
        if state == 'awaiting_verification':
            return self._row(job, status='awaiting_verification', value_text=None, error=detail, **base)
        if state == 'refused' and str(detail).startswith('already_settled'):
            return self._resumed_row(job, base)
        return self._row(job, status='failed', error=detail, **base)

    def _resumed_row(self, job, base=None) -> dict:
        """The row of a job whose settlement is already final (resume)."""
        s = self.store.settlement(job['name'])
        if s['winner'] == 'rule':
            return self._rule_row(job, self.store.result(job['name']), resumed=True)
        emission = next(e for e in self.store.emissions(job['name']) if e['seq'] == s['emission'])
        fields = dict(base or {'phase': emission['phase'], 'call_kind': None})
        fields.setdefault('call_id', emission['call_id'])
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
        t0 = self.wall()
        jobs = self._jobs(wave)
        if not jobs:
            raise Error(f'no submissions for wave {wave}')
        notes = {'efficiency_invalid': [], 'incomplete': [], 'bootstrap_seconds': 0.0, 'bootstrap': None,
                 'audits': None, 'quarantine_fallbacks': 0}
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
                                    bindings_sha256=self.settle_bindings, required=self.learner.required)
        if self.arm == 'A':
            items = []
            for j in valid:
                if self.store is not None and self.store.settlement(j['name'])['state'] == 'settled':
                    self._resumed_row(j)
                else:
                    items.append(self._item(j, 'ordinary', 'pool'))
            results = self._dispatch(wave, 'r1', items)
            for item in items:
                self._model_row(item['job'], *results[item['id']], phase='ordinary', kind='ordinary')
        else:
            self._rule_arm(wave, valid, learn, notes)
        return self.report(wave, jobs, notes, t0)

    def _item(self, job, kind, pool, *, key=None, submission=None, tag=None) -> dict:
        return {'id': (tag or kind) + ':' + job['name'], 'job': job, 'kind': kind, 'pool': pool,
                'producer': job['producer'], 'submission': submission or job['submission'],
                'key': key or job['key'], 'text': job['text'], 'dataset_id': job['dataset_id']}

    def _pool(self, job) -> str:
        return job['producer'] if self.arm == 'B' else 'pool'

    def _rule_arm(self, wave, jobs, learn, notes) -> None:
        store, learner = self.store, self.learner
        # 1. Shared bootstrap: only for a learning wave whose bindings have no stored entry (never re-learned).
        record = None
        if learn and not store.rules(learner.key):
            t = self.wall()
            record = self._bootstrap(wave, jobs, notes)
            notes['bootstrap_seconds'] = self.wall() - t
        elif learn:
            found = self.experiment.bootstrap(self.backend, self.workload)
            record = found['record'] if found and found['record'] else None
        # The bootstrap answers belong to the wave that ran it (B and C share the wave name); a later wave reuses the
        # rule and is warm: pending or inconclusive audits of the rule then block its reuse.
        fresh = bool(learn and record and record.get('wave') == wave)
        boot_ids = set(record['jobs']) if fresh else set()
        if record is not None and fresh:
            notes['bootstrap'] = {k: record.get(k) for k in ('status', 'attempt_id', 'efficiency_valid', 'owner')}
            notes['bootstrap']['imported'] = record.get('owner') != self.owner
            notes['bootstrap']['elapsed'] = (record.get('attempt') or {}).get('elapsed') or 0.0
            if not record.get('efficiency_valid'):
                notes['efficiency_invalid'].append('bootstrap_' + str(record.get('status')))
        elif learn and record is None:
            notes['incomplete'].append('bootstrap_unresolved')
        rest = []
        for job in jobs:
            if job['dataset_id'] in boot_ids:
                self._bootstrap_row(job, record)
            else:
                rest.append(job)
        # 2. Rule phase before any chunking.
        rule = store.active(learner.key)
        entries = store.rules(learner.key)
        reuse, why = store.reusable(rule['id']) if rule else (False, None)
        without = ('no_admitted_rule' if not entries else 'quarantined' if any(e['status'] == 'quarantined'
                                                                               for e in entries) else 'rule_rejected')
        warm = not fresh
        if rule and warm and not reuse:
            notes['efficiency_invalid'].append('warm_reuse_blocked:' + why)
        staged, covered, fallback = {}, {}, []
        for job in rest:
            s = store.settlement(job['name'])
            if s['state'] == 'settled':
                row = self._resumed_row(job)
                if row['source'] == 'rule':
                    covered[job['name']] = (job, row['value_text'])
                continue
            if rule is None:
                fallback.append((job, without))
                continue
            if warm and not reuse:
                fallback.append((job, why))
                continue
            generation = store.claim(job['name'])
            d = learner.attempt(rule, job=job['name'], text=job['text'],
                                resolved_sha256=job['receipt']['resolved_sha256'], op_text=self.op_text,
                                owner={'producer': job['producer'], 'submission': job['submission'],
                                       'operation': self.op, 'path': job['key']},
                                generation=generation, payload_sha256=job['payload_sha256'],
                                bindings_sha256=self.settle_bindings, stage=self.rule_delivery == 'after_audits',
                                evaluate=self.hooks.get('evaluate', rp.oz_rule.evaluate),
                                before_commit=self.hooks.get('before_commit'))
            if d['decision'] == 'staged':
                staged[job['name']] = (job, d)
                covered[job['name']] = (job, rp.oz_rule.canonical_value_text(d['first']))
            elif d['decision'] == 'rule':
                self._rule_row(job, d['row'], resumed=d.get('resumed', False))
                covered[job['name']] = (job, d['row']['value'])
            else:
                fallback.append((job, d['reason']))
        # 3. Audits over the whole evaluation wave, selected on frozen dataset ids and persisted before dispatch.
        audit_items = []
        if covered and rule is not None:
            by_dataset = {j['dataset_id']: (j, v) for j, v in covered.values()}
            wave_key = rp.wave_id(self.backend, self.workload, wave)
            selection = self.experiment.audit_wave(wave_key, rule['ast_sha256'], self.seed, sorted(by_dataset))
            if selection['mismatch']:
                notes['incomplete'].append('audit_population_mismatch')
            chosen = [d for d in selection['selection'] if d in by_dataset]
            rows = []
            for d in chosen:
                job, value = by_dataset[d]
                audit_sub = subname(job['submission'], 'audit')
                item = self._item(job, 'audit', self._pool(job), submission=audit_sub, tag='audit')
                item['audit_job'] = oz_spool.delivery_id(job['producer'], audit_sub, self.op, job['key'])
                rows.append({'audit_job': item['audit_job'], 'wave_id': wave_key, 'original_job': job['name'],
                             'rule': rule['id'], 'producer': job['producer'], 'submission': job['submission'],
                             'dataset_id': d, 'rule_value': value})
                audit_items.append(item)
            store.add_audits(rows)
            audit_items = [i for i in audit_items if store.audit(i['audit_job'])['verdict'] == 'pending']
            notes['audits'] = {'wave_id': wave_key, 'population': len(by_dataset), 'selected': len(chosen)}
        # 4. Fallback plus audits in shared batches (B: per producer; C: pooled).
        items = [dict(self._item(job, 'fallback', self._pool(job)), reason=reason) for job, reason in fallback]
        results = self._dispatch(wave, 'r1', items + audit_items)
        for item in items:
            self._model_row(item['job'], *results[item['id']], phase='fallback', kind='fallback',
                            reason=item['reason'])
        retry = self._decide_audits(audit_items, results)
        if retry and self.audit_retry:
            again = [dict(i, id='retry:' + i['id'], submission=subname(i['job']['submission'], 'audit2'))
                     for i in retry]
            self._decide_audits(again, self._dispatch(wave, 'r2', again))
        # 5. Deliver staged rule rows; a rule quarantined meanwhile makes the undelivered rows fall back (rule 8).
        late = []
        for name, (job, d) in staged.items():
            got = learner.commit(d, evaluate=self.hooks.get('evaluate', rp.oz_rule.evaluate),
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
        """Record each audit verdict (a disagreement quarantines in the same transaction); returns the inconclusive."""
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
            else:
                model_value = result['value_text']
                same = canonical(loads(model_value)) == canonical(loads(original['rule_value']))
                verdict, detail = ('agree' if same else 'disagree'), None
            got = self.store.decide_audit(item['audit_job'], verdict, model_value=model_value, detail=detail, **meta)
            if got['audit']['verdict'] == 'inconclusive':
                retry.append(item)
        return retry

    # ------------------------------------------------------------------------------------------ bootstrap

    def _bootstrap(self, wave, jobs, notes) -> dict | None:
        """Claim and run the one shared bootstrap, or wait for and import the recorded one."""
        by_producer = {}
        for job in jobs:
            by_producer.setdefault(job['producer'], []).append(job['dataset_id'])
        assignment = self.experiment.assignment(self.backend, self.workload, by_producer, self.seed,
                                                per_producer=self.per_producer, expected=self.producers_expected)
        state, row = self.experiment.claim_bootstrap(self.backend, self.workload, self.owner)
        if state == 'wait':
            deadline = self.clock() + self.bootstrap_wait
            while self.clock() < deadline:
                row = self.experiment.bootstrap(self.backend, self.workload)
                if row['state'] == 'recorded':
                    break
                time.sleep(0.05)
            if row['state'] != 'recorded':
                return None
        elif state in ('run', 'resume'):
            by_dataset = {j['dataset_id']: j for j in jobs}
            items = [self._item(by_dataset[d], 'bootstrap', 'bootstrap', tag='boot',
                                submission=subname(by_dataset[d]['submission'], 'boot'))
                     for p in sorted(assignment) for d in assignment[p]]
            results = self._dispatch(wave, 'bootstrap', items, group_kind='bootstrap')
            if any(results[i['id']][0] is None for i in items):
                return None  # unknown outcome: unresolved until reconciled (A2.1)
            attempt_ids = sorted({results[i['id']][1]['attempt_id'] for i in items})
            if len(attempt_ids) != 1:
                notes['efficiency_invalid'].append('bootstrap_not_one_call')
            aid = attempt_ids[0]
            attempt = self.ledger.attempt(aid)
            if attempt is None or attempt['state'] == 'refused':
                notes['incomplete'].append('bootstrap_not_launched')
                return None  # provably unlaunched (budget): nothing recorded, a later run may launch it
            side_file = self.side_dir / f'{aid}.json'
            side_bytes = side_file.read_bytes() if side_file.exists() else None
            side = json.loads(side_bytes.decode('utf-8')) if side_bytes else None
            answers = {}
            for item in items:
                result, srow = results[item['id']]
                answers[item['dataset_id']] = {'status': result.get('status'), 'value_text': result.get('value_text'),
                                               'error': result.get('error'), 'call_id': result.get('call_id')}
            if side is None:
                status = 'missing'
            elif side.get('status') != 'ok' or side.get('envelope_ok') is not True:
                status = 'failed'
            elif all(a['status'] == 'accepted' for a in answers.values()):
                status = 'ok'
            else:
                status = 'answers_failed'
            record = {'backend': self.backend, 'workload': self.workload, 'owner': self.owner, 'wave': wave,
                      'binding_key': self.learner.key, 'assignment': assignment,
                      'assignment_sha256': _sha(json.dumps(assignment, sort_keys=True)), 'attempt_id': aid,
                      'request_id': attempt['request_id'] if attempt else None, 'jobs': answers, 'side': side,
                      'side_sha256': hashlib.sha256(side_bytes).hexdigest() if side_bytes else None,
                      'attempt': attempt, 'status': status, 'efficiency_valid': status == 'ok'}
            self.experiment.record_bootstrap(self.backend, self.workload, self.owner, record)
        record = self.experiment.bootstrap(self.backend, self.workload)['record']
        self.learner.admit_side(record['side'], source=f"bootstrap:{record['attempt_id']}:{self.op}",
                                provenance={'experiment': str(self.experiment.path), 'backend': self.backend,
                                            'workload': self.workload, 'attempt_id': record['attempt_id'],
                                            'side_sha256': record['side_sha256'], 'status': record['status'],
                                            'imported': record['owner'] != self.owner})
        if record['owner'] != self.owner:
            self._import_allocations(wave, jobs, record)
        return record

    def _import_allocations(self, wave, jobs, record) -> None:
        """The shared bootstrap call charged analytically in full to this arm (basis imported)."""
        attempt = record.get('attempt') or {}
        mine = {j['dataset_id']: j for j in jobs}
        members = [d for d in record['jobs'] if d in mine]
        rows = []
        for call in attempt.get('calls') or []:
            for d in members:
                job = mine[d]
                rows.append({'arm': self.arm, 'backend': self.backend, 'workload': self.workload, 'wave': wave,
                             'attempt_id': record['attempt_id'], 'call_id': call['call_id'], 'job': job['name'],
                             'original': job['name'], 'producer': job['producer'], 'dataset_id': d,
                             'kind': 'bootstrap', 'share': 1.0 / len(record['jobs']), 'basis': 'imported'})
        self.ledger.allocate(rows)

    def _bootstrap_row(self, job, record) -> dict:
        """A bootstrap job's row from the shared record: settled from the recorded answer, never replaced (A2.1)."""
        s = self.store.settlement(job['name'])
        if s['state'] == 'settled':
            return self._resumed_row(job)
        answer = record['jobs'][job['dataset_id']]
        base = {'phase': 'bootstrap', 'call_kind': 'bootstrap', 'call_id': answer.get('call_id'),
                'attempt_id': record['attempt_id'], 'request_id': record.get('request_id'),
                'imported': record['owner'] != self.owner}
        if answer['status'] != 'accepted':
            return self._row(job, status='failed', error='bootstrap_answer_failed: ' + str(answer.get('error')),
                             **base)
        return self._settle_model(job, answer['value_text'], base)

    # --------------------------------------------------------------------------------------------- report

    def reconcile(self, wave: str) -> dict:
        """Allocation shares sum to 1 per call and match batch membership; allocated calls exist; charged = physical
        + imported."""
        problems = []
        allocations = self.ledger.allocations(wave)
        attempts = [a for a in self.ledger.attempts(wave) if a['state'] != 'refused']
        physical = {c['call_id']: c for a in attempts for c in a['calls'] if c}
        record = (self.experiment.bootstrap(self.backend, self.workload) or {}).get('record') or {}
        imported_calls = {c['call_id']: c for c in (record.get('attempt') or {}).get('calls') or []}
        shares = {}
        for a in allocations:
            key = (a['call_id'], a['basis'])
            shares[key] = shares.get(key, 0.0) + a['share']
            if a['basis'] == 'physical' and a['call_id'] not in physical:
                problems.append(f"allocated physical call {a['call_id']} is not in the ledger")
            if a['basis'] == 'imported' and a['call_id'] not in imported_calls:
                problems.append(f"imported call {a['call_id']} is not in the bootstrap record")
        for key, total in shares.items():
            if abs(total - 1.0) > 1e-9:
                problems.append(f'call {key[0]} ({key[1]}) shares sum to {total}')
        for a in attempts:
            for c in a['call_ids']:
                members = sum(1 for x in allocations if x['call_id'] == c and x['basis'] == 'physical')
                if members != len(a['records']):
                    problems.append(f"call {c} has {members} allocated jobs but {len(a['records'])} records")
        imported = sorted({a['call_id'] for a in allocations if a['basis'] == 'imported'})
        return {'ok': not problems, 'problems': problems, 'physical_calls': len(physical),
                'imported_calls': len(imported), 'charged_calls': len(physical) + len(imported),
                'physical': physical, 'imported': {c: imported_calls[c] for c in imported if c in imported_calls}}

    def report(self, wave, jobs, notes, t0) -> dict:
        rows = [self._rows[j['name']] for j in jobs]
        rec = self.reconcile(wave)
        attempts = self.ledger.attempts(wave)
        tokens = {'physical': _tokens(rec['physical'].values()), 'imported': _tokens(rec['imported'].values())}
        tokens['charged'] = _add_tokens(tokens['physical'], tokens['imported'])
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
            quarantined = any(r['status'] == 'quarantined' for r in self.store.rules(self.learner.key))
        if audits['pending'] or audits['inconclusive']:
            notes['incomplete'].append('audits_unresolved')
        unknown = [r for r in rows if r['status'] == 'unresolved']
        if unknown:
            notes['incomplete'].append(f'{len(unknown)} jobs unresolved')
        refused = [a for a in attempts if a['state'] == 'refused']
        for reason in sorted({a['error'] for a in refused}):
            notes['incomplete'].append(reason)
        if tokens['charged']['usage'] != 'complete' and rec['charged_calls']:
            notes['efficiency_invalid'].append('usage_' + tokens['charged']['usage'])
        if any(r.get('memo') for r in rows):
            notes['efficiency_invalid'].append('memo_served')
        if not rec['ok']:
            notes['incomplete'].append('reconciliation_failed')
        fallback_rows = [r for r in rows if r['phase'] == 'fallback']
        reasons = {}
        for r in fallback_rows:
            reasons[r.get('fallback_reason')] = reasons.get(r.get('fallback_reason'), 0) + 1
        delivered = [r['delivered_at'] for r in rows]
        queue = [r['queue_s'] for r in rows]
        makespan = max(delivered) - min(j['submitted_at'] for j in jobs) if rows else 0.0
        boot = notes['bootstrap'] or {}
        charged_makespan = makespan - notes['bootstrap_seconds'] + (boot.get('elapsed') or 0.0)
        count = lambda **kv: sum(1 for r in rows if all(r.get(k) == v for k, v in kv.items()))
        report = {
            'schema': REPORT_SCHEMA, 'arm': self.arm, 'backend': self.backend, 'workload': self.workload, 'wave': wave,
            'jobs': len(rows), 'accepted_by_checks': count(status='accepted'), 'failed': count(status='failed'),
            'awaiting_verification': count(status='awaiting_verification'), 'unresolved': len(unknown),
            'by_source': {s: count(status='accepted', source=s) for s in ('rule', 'model')},
            'rule_hits': count(status='accepted', source='rule'),
            'coverage': round(count(status='accepted', source='rule') / len(rows), 6) if rows else 0.0,
            'fallback': len(fallback_rows), 'fallback_reasons': reasons,
            'abstains': sum(n for r, n in reasons.items() if str(r).startswith('abstain:')),
            'audits': audits, 'quarantined': quarantined, 'quarantine_fallbacks': notes['quarantine_fallbacks'],
            'calls': {'physical': rec['physical_calls'], 'imported': rec['imported_calls'],
                      'charged': rec['charged_calls'], 'attempts': len(attempts), 'refused': len(refused),
                      'by_kind': by_kind},
            'tokens': tokens, 'bootstrap': notes['bootstrap'],
            'queue_seconds': {'mean': round(sum(queue) / len(queue), 6) if queue else 0.0,
                              'max': round(max(queue), 6) if queue else 0.0},
            'makespan_seconds': round(makespan, 6), 'charged_makespan_seconds': round(charged_makespan, 6),
            'budget': self.budget.usage(), 'reconciliation': {k: rec[k] for k in ('ok', 'problems', 'physical_calls',
                                                                                  'imported_calls', 'charged_calls')},
            'efficiency_valid': not notes['efficiency_invalid'], 'efficiency_invalid': notes['efficiency_invalid'],
            'evidence': 'incomplete' if notes['incomplete'] else 'complete', 'incomplete': notes['incomplete'],
            'correctness': CORRECTNESS}
        _publish(self.arm_dir / 'reports' / f'{_b32([wave])[:16]}.json',
                 json.dumps(report, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8'))
        return report


def _tokens(calls) -> dict:
    out = dict.fromkeys(USAGE_FIELDS, 0)
    known = unknown = 0
    for c in calls:
        usage = c.get('usage')
        if isinstance(usage, dict) and {'input_tokens', 'output_tokens'} <= set(usage):
            known += 1
            for k in USAGE_FIELDS:
                out[k] += usage.get(k, 0)
        else:
            unknown += 1
    out['tokens'] = out['input_tokens'] + out['output_tokens']
    out['calls_with_usage'], out['calls_without_usage'] = known, unknown
    out['usage'] = 'n/a' if not known + unknown else 'complete' if not unknown else 'none' if not known else 'partial'
    return out


def _add_tokens(a, b) -> dict:
    out = {k: a[k] + b[k] for k in (*USAGE_FIELDS, 'tokens', 'calls_with_usage', 'calls_without_usage')}
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


def dry_run(matrix: dict, recorded_usage: dict) -> dict:
    """Run the matrix with replay adapters at zero external calls; report the would-be numbers and budget use.

    matrix: {"seed": int, "caps": {backend: {bucket: n}}, "global_cap": n, "experiment_dir": optional path,
             "slots": 4, "max_wait": seconds, "cells": [{"backend", "workload", "registry" (oz_registry.Registry),
             "op", "op_text", "model", "effort", "route", "checks" (optional), "answer" (text -> value),
             "rules" ({op: exact AST JSON text or "none"}), "arms": ["A", "B", "C"],
             "waves": [{"name", "learn": bool, "arms": optional subset, "producers": {producer: [jobs]}}]}]}
    recorded_usage: {backend: {"call": [usage samples], "bootstrap": [samples]}}; a sample holds usage fields and
             optionally "elapsed_seconds"."""
    import tempfile
    shim = _shim()
    temp = None
    root = matrix.get('experiment_dir')
    if root is None:
        temp = tempfile.TemporaryDirectory()
        root = temp.name
    root = Path(root)
    seed = matrix['seed']
    budget = Budget(root / 'budget.sqlite', caps=matrix.get('caps'), global_cap=matrix.get('global_cap'))
    slots = matrix.get('slots', 4)
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
                host = ArmHost(arm=arm, backend=cell['backend'], workload=cell['workload'], experiment_dir=root,
                               launcher=InProcessLauncher(shim.CallableShim(adapter)), op=cell['op'],
                               op_text=cell['op_text'], model=cell['model'], effort=cell['effort'],
                               identity=identity_for(cell['route']), checks=cell.get('checks'),
                               registry=cell.get('registry'),
                               seed=seed if arm != 'A' else None, budget=budget, slots=slots,
                               max_wait=matrix.get('max_wait', 0.05), allow_experimental=True,
                               producers_expected=cell.get('producers_expected', rp.BOOTSTRAP_PRODUCERS),
                               bootstrap_per_producer=cell.get('bootstrap_per_producer', rp.BOOTSTRAP_PER_PRODUCER))
                hosts.append(host)
                arm_hosts[arm] = (host, adapter)
            for wave in cell['waves']:
                wave_out = {'name': wave['name'], 'learn': wave.get('learn', True), 'arms': {}}
                for arm in [a for a in order if a in (wave.get('arms') or order)]:
                    host, adapter = arm_hosts[arm]
                    for producer, jobs in sorted(wave['producers'].items()):
                        host.submit(producer, f"s{wave['name']}{arm}{producer}"[:64], jobs, wave=wave['name'])
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
