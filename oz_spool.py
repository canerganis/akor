"""Producer spool and scheduler for `oz map` on SQLite (council 2 rewrite of build step 5, D7 and D8).

One database file holds everything. Producers only call Spool.submit and Spool.collect. Exactly one host process
per spool owns a Scheduler, which pools pending jobs into batches, reserves them durably, launches them on a bounded
number of worker threads, captures what launch returned and then delivers it.

Tables
  meta            schema version and the host fencing epoch
  producers       casefolded producer name -> the one exact spelling allowed (Windows names are case-insensitive)
  bindings        bindings hash -> canonical bindings JSON (validated and re-hashed on every read)
  submissions     (producer, submission) -> payload hash; a different payload for the same id is a conflict
  ids             delivery id -> identity; a second identity for one id is a collision, never a silent merge
  jobs            one row per job: host-issued delivery id, producer, submission, key, op, text, dataset_id,
                  bindings hash, and, once pooled, batch id and position (the reference mapping)
  batches         request id (derived from batch id, so a re-dispatch can never ask for a second call) and state
  attempts        one physical launch attempt per row: reserved -> launched -> captured -> delivered, or unknown
  results         exactly one delivered row per job, with all five timestamps
  rejections      foreign or conflicting result ids and captures, kept as a record

Identity (D8): delivery id = 'j' + lowercase unpadded base32 of sha256(canonical([producer, submission, op, key])),
53 characters. Producers never choose ids. Producer names that differ only by case are rejected.

Host lock. An OS lock (msvcrt.locking on Windows, fcntl.flock elsewhere) on '<db>.host.lock' is held for the life of
the process, so a live holder is never displaced by a timeout and a dead one releases it automatically. Acquiring the
lock increments a fencing epoch row. Every mutating scheduler transaction re-reads that row inside BEGIN IMMEDIATE
and raises Fenced when it is no longer the holder's epoch. Dispatch authorization (the launched mark) is such a
transaction.

Attempt states and crash recovery
  reserved   durable before anything is launched. After a crash it is simply launched (provably unlaunched).
  launched   durable just before launch() is called. After a crash, or when launch raises anything but
             LaunchNotStarted, or when it returns something unusable, the outcome is unknown: the attempt becomes
             'unknown' and is NEVER relaunched automatically (amendment 2, A2.1). Scheduler.reconcile(attempt_id,
             capture) resolves it with a real capture, or reconcile(..., provably_unlaunched=True) voids it and
             reserves a fresh attempt for the same batch.
  captured   the capture is durable. Recovery delivers it, never launches again.
  delivered  all result rows exist. Terminal.
Delivery is one transaction that inserts a result row per job (primary key = delivery id), so each row is delivered
exactly once. A row that already exists with a different payload is rejected and recorded.
"""

import base64
import hashlib
import json
import os
import queue
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from oz_registry import RegistryError, canonical

SCHEMA = 'oz.spool/2'
NAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
BINDING_KEYS = ('contract_hash', 'check_hash', 'permission_hash', 'worker_hash', 'input_policy')
JOB_KEYS = ('key', 'op', 'text', 'dataset_id')
_DEVICE = {'con', 'prn', 'aux', 'nul'} | {f'com{i}' for i in range(10)} | {f'lpt{i}' for i in range(10)}


class SpoolError(Exception):
    pass


class SubmissionConflict(SpoolError):
    pass


class ProducerCollision(SpoolError):
    pass


class IdCollision(SpoolError):
    pass


class HostLocked(SpoolError):
    pass


class Fenced(SpoolError):
    pass


class LaunchNotStarted(Exception):
    """Raise from launch() when the call provably never started; the attempt goes back to 'reserved'."""


# ---- identity and validation ----

def _b32(data: bytes) -> str:
    return base64.b32encode(hashlib.sha256(data).digest()).decode('ascii').lower().rstrip('=')


def delivery_id(producer, submission, op, key):
    """D8 compact name: 'j' plus 52 base32 characters, 53 in all."""
    return 'j' + _b32(canonical([producer, submission, op, key]))


def bindings_hash(bindings):
    return hashlib.sha256(canonical(bindings)).hexdigest()


def batch_id_of(group_hash, ids):
    return 'b' + _b32(canonical([group_hash, sorted(ids)]))


def request_id_of(batch_id):
    return 'q' + _b32(canonical(['request', batch_id]))


def attempt_id_of(batch_id, n):
    return 'a' + _b32(canonical([batch_id, n]))


def _jdump(value) -> str:
    return canonical(value).decode('utf-8')


def _name(label, value):
    if type(value) is not str or not NAME_RE.match(value):
        raise SpoolError(f'{label} must match {NAME_RE.pattern}')
    if value.casefold() in _DEVICE:
        raise SpoolError(f'{label} {value!r} is a reserved device name')
    return value


def validate_bindings(bindings):
    """Exactly {contract_hash, check_hash, permission_hash, worker_hash, input_policy}; returns the bindings."""
    if type(bindings) is not dict or set(bindings) != set(BINDING_KEYS):
        raise SpoolError(f'bindings must be an object with exactly the keys {list(BINDING_KEYS)}')
    for k in BINDING_KEYS[:4]:
        v = bindings[k]
        if type(v) is not str or not v or len(v) > 256 or v != v.strip():
            raise SpoolError(f'bindings.{k} must be a non-empty string without surrounding space')
    policy = bindings['input_policy']
    if type(policy) not in (str, dict) or not policy:
        raise SpoolError('bindings.input_policy must be a non-empty string or object')
    try:
        canonical(bindings)
    except RegistryError as exc:
        raise SpoolError(f'bindings are not canonical JSON: {exc}') from None
    return bindings


def _validate_jobs(jobs):
    if not isinstance(jobs, (list, tuple)) or not jobs:
        raise SpoolError('jobs must be a non-empty list')
    out, seen = [], set()
    for job in jobs:
        if type(job) is not dict or set(job) != set(JOB_KEYS):
            raise SpoolError(f'each job must be an object with exactly the keys {list(JOB_KEYS)} (ids are host-issued)')
        for k in JOB_KEYS:
            if type(job[k]) is not str:
                raise SpoolError(f'job.{k} must be a string')
        if not job['key'] or not job['dataset_id']:
            raise SpoolError('job.key and job.dataset_id must be non-empty')
        if (job['op'], job['key']) in seen:
            raise SpoolError(f'duplicate logical job {job["op"]!r}/{job["key"]!r}')
        seen.add((job['op'], job['key']))
        out.append({k: job[k] for k in JOB_KEYS})
    return out


# ---- host lock ----

class HostLock:
    """OS file lock held until release() or process exit; the OS drops it when the process dies."""

    def __init__(self, path):
        self.path = str(path)
        self.fd = None

    def acquire(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == 'nt':
                import msvcrt
                if os.fstat(fd).st_size < 1:
                    os.write(fd, b'\0')
                    os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise HostLocked(f'another host process holds {self.path}') from None
        self.fd = fd
        return self

    def release(self):
        fd, self.fd = self.fd, None
        if fd is None:
            return
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(fd)


class Host:
    """The lock plus the fencing epoch it was issued."""

    def __init__(self, spool):
        self.spool = spool
        self.lock = HostLock(str(spool.path) + '.host.lock').acquire()
        try:
            with spool._tx() as c:
                self.epoch = int(c.execute("SELECT v FROM meta WHERE k='epoch'").fetchone()[0]) + 1
                c.execute("UPDATE meta SET v=? WHERE k='epoch'", (str(self.epoch),))
        except BaseException:
            self.lock.release()
            raise
        self.closed = False

    def check(self, conn):
        """Call inside a BEGIN IMMEDIATE transaction."""
        current = int(conn.execute("SELECT v FROM meta WHERE k='epoch'").fetchone()[0])
        if self.closed or current != self.epoch:
            raise Fenced(f'host epoch {self.epoch} is no longer current ({current})')

    def close(self):
        self.closed = True
        self.lock.release()


# ---- the spool ----

_DDL = (
    "CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS producers(norm TEXT PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS bindings(hash TEXT PRIMARY KEY, body TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS submissions(producer TEXT NOT NULL, sub_norm TEXT NOT NULL, submission TEXT NOT NULL,"
    " payload_hash TEXT NOT NULL, bindings_hash TEXT NOT NULL, njobs INTEGER NOT NULL, submitted_at REAL NOT NULL,"
    " PRIMARY KEY(producer, sub_norm))",
    "CREATE TABLE IF NOT EXISTS ids(id TEXT PRIMARY KEY, identity TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS jobs(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,"
    " producer TEXT NOT NULL, submission TEXT NOT NULL, key TEXT NOT NULL, op TEXT NOT NULL, text TEXT NOT NULL,"
    " dataset_id TEXT NOT NULL, bindings_hash TEXT NOT NULL, submitted_at REAL NOT NULL, ord INTEGER NOT NULL,"
    " batch_id TEXT, position INTEGER, UNIQUE(producer, submission, op, key))",
    "CREATE INDEX IF NOT EXISTS jobs_pending ON jobs(batch_id, seq)",
    "CREATE TABLE IF NOT EXISTS batches(batch_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,"
    " bindings_hash TEXT NOT NULL, state TEXT NOT NULL, size INTEGER NOT NULL, attempt_id TEXT,"
    " reserved_at REAL, launched_at REAL, captured_at REAL, delivered_at REAL)",
    "CREATE TABLE IF NOT EXISTS attempts(attempt_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, n INTEGER NOT NULL,"
    " state TEXT NOT NULL, launches INTEGER NOT NULL DEFAULT 0, epoch INTEGER, reserved_at REAL, launched_at REAL,"
    " captured_at REAL, delivered_at REAL, capture TEXT, capture_hash TEXT, call_id TEXT, error TEXT, reconciled INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS results(job_id TEXT PRIMARY KEY, producer TEXT NOT NULL, submission TEXT NOT NULL,"
    " key TEXT NOT NULL, op TEXT NOT NULL, dataset_id TEXT NOT NULL, batch_id TEXT NOT NULL, attempt_id TEXT NOT NULL,"
    " request_id TEXT NOT NULL, position INTEGER NOT NULL, call_id TEXT, result TEXT NOT NULL, submitted_at REAL,"
    " reserved_at REAL, launched_at REAL, captured_at REAL, delivered_at REAL)",
    "CREATE TABLE IF NOT EXISTS rejections(rid INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, attempt_id TEXT,"
    " job_id TEXT, reason TEXT NOT NULL, detail TEXT)",
)


class Spool:
    """The database. Safe to open from many processes and threads; each operation uses its own connection."""

    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            if not str(self.path).startswith('\\\\'):  # WAL needs shared memory, so never on a network share
                conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('BEGIN IMMEDIATE')
            for stmt in _DDL:
                conn.execute(stmt)
            conn.execute("INSERT OR IGNORE INTO meta(k, v) VALUES('schema', ?)", (SCHEMA,))
            conn.execute("INSERT OR IGNORE INTO meta(k, v) VALUES('epoch', '0')")
            version = conn.execute("SELECT v FROM meta WHERE k='schema'").fetchone()[0]
            conn.execute('COMMIT')
            if version != SCHEMA:
                raise SpoolError(f'spool schema {version!r} is not {SCHEMA!r}')
        finally:
            conn.close()

    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=60.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('PRAGMA busy_timeout=60000')
        return conn

    @contextmanager
    def _tx(self, host=None):
        conn = self._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            if host is not None:
                host.check(conn)
            yield conn
            conn.execute('COMMIT')
        except BaseException:
            try:
                conn.execute('ROLLBACK')
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    def acquire_host(self):
        return Host(self)

    # -- bindings: validated and re-hashed on every read --
    def _bindings(self, conn, h):
        row = conn.execute('SELECT body FROM bindings WHERE hash=?', (h,)).fetchone()
        if row is None:
            raise SpoolError(f'unknown bindings {h}')
        try:
            value = json.loads(row['body'])
            validate_bindings(value)
            ok = bindings_hash(value) == h
        except (ValueError, SpoolError, RegistryError):
            ok = False
        if not ok:
            raise SpoolError(f'bindings {h} are corrupt (schema or hash mismatch)')
        return value

    # -- producer side --
    def submit(self, producer, submission, jobs, bindings):
        """One transaction. Returns {delivery_id: job_key} in job order.

        jobs: [{key, op, text, dataset_id}]. bindings: {contract_hash, check_hash, permission_hash, worker_hash,
        input_policy}. The same (producer, submission) with an identical payload is a no-op; a different payload raises
        SubmissionConflict. Producer or submission names equal after casefold but spelled differently raise.
        """
        _name('producer', producer)
        _name('submission', submission)
        validate_bindings(bindings)
        jobs = _validate_jobs(jobs)
        try:
            bhash = bindings_hash(bindings)
            payload = hashlib.sha256(canonical({'bindings': bindings, 'jobs': jobs})).hexdigest()
            entries = [(delivery_id(producer, submission, j['op'], j['key']), j) for j in jobs]
            identities = {i: _jdump([producer, submission, j['op'], j['key']]) for i, j in entries}
        except RegistryError as exc:
            raise SpoolError(f'not canonical JSON: {exc}') from None
        with self._tx() as c:
            row = c.execute('SELECT name FROM producers WHERE norm=?', (producer.casefold(),)).fetchone()
            if row is not None and row['name'] != producer:
                raise ProducerCollision(f'producer {producer!r} collides with {row["name"]!r} (case-insensitive)')
            existing = c.execute('SELECT submission, payload_hash FROM submissions WHERE producer=? AND sub_norm=?',
                                 (producer, submission.casefold())).fetchone()
            if existing is not None:
                if existing['submission'] != submission:
                    raise ProducerCollision(f'submission {submission!r} collides with {existing["submission"]!r}')
                if existing['payload_hash'] != payload:
                    raise SubmissionConflict(f'submission {producer}/{submission} already exists with a different payload')
                return {r['id']: r['key'] for r in c.execute(
                    'SELECT id, key FROM jobs WHERE producer=? AND submission=? ORDER BY ord', (producer, submission))}
            for ident_id, ident in identities.items():
                c.execute('INSERT OR IGNORE INTO ids(id, identity) VALUES(?, ?)', (ident_id, ident))
                have = c.execute('SELECT identity FROM ids WHERE id=?', (ident_id,)).fetchone()['identity']
                if have != ident:
                    raise IdCollision(f'delivery id collision {ident_id}: {have} vs {ident}')
            now = self.clock()
            c.execute('INSERT OR IGNORE INTO producers(norm, name) VALUES(?, ?)', (producer.casefold(), producer))
            c.execute('INSERT OR IGNORE INTO bindings(hash, body) VALUES(?, ?)', (bhash, _jdump(bindings)))
            c.execute('INSERT INTO submissions VALUES(?, ?, ?, ?, ?, ?, ?)',
                      (producer, submission.casefold(), submission, payload, bhash, len(jobs), now))
            for n, (ident_id, j) in enumerate(entries):
                c.execute('INSERT INTO jobs(id, producer, submission, key, op, text, dataset_id, bindings_hash,'
                          ' submitted_at, ord) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                          (ident_id, producer, submission, j['key'], j['op'], j['text'], j['dataset_id'], bhash, now, n))
            return {i: j['key'] for i, j in entries}

    @staticmethod
    def _row(r):
        out = {k: r[k] for k in r.keys()}
        out['delivery_id'] = out.pop('job_id')
        out['result'] = json.loads(out['result'])
        return out

    def collect(self, producer, submission):
        """{'results': {delivery_id: row}, 'complete': bool, 'jobs': n, 'unknown': [attempt ids]}. Never blocks."""
        with self._tx() as c:
            sub = c.execute('SELECT njobs FROM submissions WHERE producer=? AND sub_norm=?',
                            (producer, str(submission).casefold())).fetchone()
            if sub is None:
                raise SpoolError(f'unknown submission {producer}/{submission}')
            got = {r['job_id']: self._row(r) for r in c.execute(
                'SELECT * FROM results WHERE producer=? AND submission=?', (producer, submission))}
            unknown = [r['attempt_id'] for r in c.execute(
                "SELECT DISTINCT a.attempt_id FROM attempts a JOIN jobs j ON j.batch_id=a.batch_id"
                " WHERE a.state='unknown' AND j.producer=? AND j.submission=?", (producer, submission))]
        return {'results': got, 'complete': len(got) == sub['njobs'], 'jobs': sub['njobs'], 'unknown': unknown}

    def request_map(self, request_id):
        """Request/reference mapping: the batch, its attempts and each job's position for one request id."""
        with self._tx() as c:
            b = c.execute('SELECT * FROM batches WHERE request_id=?', (request_id,)).fetchone()
            if b is None:
                raise SpoolError(f'unknown request {request_id}')
            return {'request_id': request_id, 'batch_id': b['batch_id'], 'state': b['state'],
                    'attempts': [{k: a[k] for k in ('attempt_id', 'n', 'state', 'launches', 'call_id')}
                                 for a in c.execute('SELECT * FROM attempts WHERE batch_id=? ORDER BY n', (b['batch_id'],))],
                    'jobs': [{'delivery_id': j['id'], 'position': j['position'], 'producer': j['producer'],
                              'submission': j['submission'], 'key': j['key'], 'op': j['op']}
                             for j in c.execute('SELECT * FROM jobs WHERE batch_id=? ORDER BY position', (b['batch_id'],))]}

    def unresolved(self):
        with self._tx() as c:
            return [{'attempt_id': a['attempt_id'], 'batch_id': a['batch_id'], 'n': a['n'], 'error': a['error']}
                    for a in c.execute("SELECT * FROM attempts WHERE state='unknown' ORDER BY reserved_at, attempt_id")]

    def rejections(self):
        with self._tx() as c:
            return [{k: r[k] for k in r.keys()} for r in c.execute('SELECT * FROM rejections ORDER BY rid')]

    def queue_report(self):
        """Per-record queue times and makespan from delivered rows, plus counts of what is not delivered."""
        with self._tx() as c:
            rows = c.execute('SELECT * FROM results').fetchall()
            pending = c.execute('SELECT COUNT(*) FROM jobs WHERE batch_id IS NULL').fetchone()[0]
            inflight = c.execute("SELECT COUNT(*) FROM jobs j JOIN batches b ON b.batch_id=j.batch_id"
                                 " WHERE b.state!='delivered'").fetchone()[0]
            unknown = c.execute("SELECT COUNT(*) FROM attempts WHERE state='unknown'").fetchone()[0]
            nbatch = c.execute("SELECT COUNT(*) FROM batches WHERE state='delivered'").fetchone()[0]
        rep = {'records': len(rows), 'batches': nbatch, 'pending': pending, 'in_flight': inflight,
               'unknown_attempts': unknown}
        if rows:
            n = len(rows)
            rep.update({
                'max_queue_s': max(r['reserved_at'] - r['submitted_at'] for r in rows),
                'mean_queue_s': sum(r['reserved_at'] - r['submitted_at'] for r in rows) / n,
                'mean_launch_wait_s': sum(r['launched_at'] - r['reserved_at'] for r in rows) / n,
                'mean_run_s': sum(r['captured_at'] - r['launched_at'] for r in rows) / n,
                'max_turnaround_s': max(r['delivered_at'] - r['submitted_at'] for r in rows),
                'makespan_s': max(r['delivered_at'] for r in rows) - min(r['submitted_at'] for r in rows)})
        return rep


# ---- the scheduler ----

class Scheduler:
    """The one scheduling owner of a spool.

    Construction takes the host lock (raises HostLocked) and a new fencing epoch, then recovers: attempts that were
    launched but never captured become 'unknown'. pump() is one non-blocking pass: harvest finished launches
    (capture, then deliver), reserve every group that is full or past its deadline, launch reserved attempts into free
    slots. Deadlines use `clock` (monotonic) and never wait on completions. launch(batch) runs in a worker thread and
    returns a capture {'results': {delivery_id: result}, 'call_id': str|None} (a bare {delivery_id: result} also works).
    """

    def __init__(self, spool, launch, *, slots=4, max_records=64, max_wait=1.0, clock=time.monotonic, fault=None,
                 retry_limit=3):
        if slots < 1 or max_records < 1 or max_wait < 0:
            raise SpoolError('slots and max_records must be >= 1 and max_wait >= 0')
        self.spool, self.launch = spool, launch
        self.slots, self.max_records, self.max_wait = slots, max_records, max_wait
        self.clock, self.fault, self.retry_limit = clock, fault, retry_limit
        self._lock = threading.RLock()
        self._done = queue.Queue()
        self._wake = threading.Event()
        self._inflight = {}
        self._seen = {}
        self._deadline = None
        self.host = spool.acquire_host()
        try:
            self._recover()
        except BaseException:
            self.host.close()
            raise

    @property
    def epoch(self):
        return self.host.epoch

    def _at(self, point, batch_id=None):
        if self.fault is not None:
            self.fault(point, batch_id)

    def _tx(self):
        return self.spool._tx(self.host)

    def _recover(self):
        with self._tx() as c:
            now = self.spool.clock()
            for a in c.execute("SELECT attempt_id, batch_id FROM attempts WHERE state='launched'").fetchall():
                c.execute("UPDATE attempts SET state='unknown', error='host_restart_without_capture' WHERE attempt_id=?",
                          (a['attempt_id'],))
                c.execute("UPDATE batches SET state='unknown' WHERE batch_id=?", (a['batch_id'],))
                c.execute('INSERT INTO rejections(at, attempt_id, reason, detail) VALUES(?, ?, ?, ?)',
                          (now, a['attempt_id'], 'unknown_outcome', 'launched without capture at host restart'))

    def close(self):
        self.host.close()
        self._wake.set()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # -- states --
    def _set(self, c, attempt_id, state, **cols):
        a = c.execute('SELECT batch_id FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
        cols = dict(cols, state=state)
        c.execute('UPDATE attempts SET ' + ', '.join(f'{k}=?' for k in cols) + ' WHERE attempt_id=?',
                  (*cols.values(), attempt_id))
        bcols = {'state': state}
        for k in ('launched_at', 'captured_at', 'delivered_at'):
            if k in cols:
                bcols[k] = cols[k]
        c.execute('UPDATE batches SET ' + ', '.join(f'{k}=?' for k in bcols) + ' WHERE batch_id=?',
                  (*bcols.values(), a['batch_id']))

    # -- reserve --
    def _reserve_due(self, stats):
        with self._lock:
            now = self.clock()
            with self._tx() as c:
                rows = c.execute('SELECT id, bindings_hash FROM jobs WHERE batch_id IS NULL ORDER BY seq').fetchall()
            groups = {}
            for r in rows:
                groups.setdefault(r['bindings_hash'], []).append(r['id'])
            pending = {r['id'] for r in rows}
            self._seen = {i: t for i, t in self._seen.items() if i in pending}
            for r in rows:
                self._seen.setdefault(r['id'], now)
            deadline = None
            for ghash, ids in sorted(groups.items()):
                while len(ids) >= self.max_records:
                    self._reserve(ghash, ids[:self.max_records])
                    ids = ids[self.max_records:]
                    stats['reserved'] += 1
                if ids:
                    due = min(self._seen[i] for i in ids) + self.max_wait
                    if now >= due:
                        self._reserve(ghash, ids)
                        stats['reserved'] += 1
                    else:
                        deadline = due if deadline is None else min(deadline, due)
            self._deadline = deadline

    def _reserve(self, ghash, ids):
        with self._tx() as c:
            marks = ','.join('?' * len(ids))
            have = [r['id'] for r in c.execute(
                f'SELECT id FROM jobs WHERE batch_id IS NULL AND id IN ({marks}) ORDER BY seq', ids)]
            if have != list(ids):
                raise SpoolError('jobs changed under the scheduler (more than one owner?)')
            self.spool._bindings(c, ghash)  # validated and re-hashed
            now = self.spool.clock()
            bid = batch_id_of(ghash, ids)
            aid = attempt_id_of(bid, 1)
            c.execute('INSERT INTO batches(batch_id, request_id, bindings_hash, state, size, attempt_id, reserved_at)'
                      " VALUES(?, ?, ?, 'reserved', ?, ?, ?)", (bid, request_id_of(bid), ghash, len(ids), aid, now))
            c.execute("INSERT INTO attempts(attempt_id, batch_id, n, state, epoch, reserved_at) VALUES(?, ?, 1, 'reserved', ?, ?)",
                      (aid, bid, self.host.epoch, now))
            for pos, i in enumerate(ids):
                c.execute('UPDATE jobs SET batch_id=?, position=? WHERE id=?', (bid, pos, i))
        self._at('after_reserve', bid)
        return bid

    # -- launch --
    def _launch_free(self, stats):
        with self._lock:
            while len(self._inflight) < self.slots:
                view = self._mark_launched()
                if view is None:
                    return
                self._at('after_launch_mark', view['batch_id'])
                thread = threading.Thread(target=self._worker, args=(view,), daemon=True,
                                          name=f"oz-spool-{view['attempt_id'][:8]}")
                self._inflight[view['attempt_id']] = thread
                stats['launched'] += 1
                thread.start()

    def _mark_launched(self):
        """Dispatch authorization: durable 'launched' mark, fenced, before launch() is called."""
        with self._tx() as c:
            skip = list(self._inflight)
            marks = ','.join('?' * len(skip))
            a = c.execute("SELECT * FROM attempts WHERE state='reserved'" + (f' AND attempt_id NOT IN ({marks})' if skip else '')
                          + ' ORDER BY reserved_at, rowid LIMIT 1', skip).fetchone()
            if a is None:
                return None
            now = self.spool.clock()
            self._set(c, a['attempt_id'], 'launched', launches=a['launches'] + 1, launched_at=now, epoch=self.host.epoch)
            b = c.execute('SELECT * FROM batches WHERE batch_id=?', (a['batch_id'],)).fetchone()
            records = [{'id': j['id'], 'producer': j['producer'], 'submission': j['submission'], 'key': j['key'],
                        'op': j['op'], 'text': j['text'], 'dataset_id': j['dataset_id'], 'position': j['position']}
                       for j in c.execute('SELECT * FROM jobs WHERE batch_id=? ORDER BY position', (a['batch_id'],))]
            return {'batch_id': a['batch_id'], 'attempt_id': a['attempt_id'], 'attempt': a['n'],
                    'request_id': b['request_id'], 'epoch': self.host.epoch, 'bindings_hash': b['bindings_hash'],
                    'bindings': self.spool._bindings(c, b['bindings_hash']), 'records': records}

    def _worker(self, view):
        try:
            item = ('ok', self.launch(view))
        except LaunchNotStarted as exc:
            item = ('unstarted', repr(exc))
        except BaseException as exc:  # noqa: BLE001 - any failure of an already authorized launch is unknown
            item = ('error', repr(exc))
        self._done.put((view, item))
        self._wake.set()

    # -- harvest: capture, then deliver --
    def _harvest(self, stats):
        while True:
            try:
                view, (kind, value) = self._done.get_nowait()
            except queue.Empty:
                return
            with self._lock:
                aid, bid = view['attempt_id'], view['batch_id']
                self._inflight.pop(aid, None)
                self._at('after_launch_call', bid)
                if kind == 'unstarted':
                    self._unstarted(aid, value)
                elif kind == 'error':
                    self._unknown(aid, f'launch raised {value}')
                else:
                    status = self._capture(aid, value)
                    if status in ('captured', 'noop'):
                        stats['captured'] += 1
                        self._at('after_capture', bid)
                        if self._deliver(aid):
                            stats['delivered'] += 1

    def _unstarted(self, aid, detail):
        with self._tx() as c:
            a = c.execute('SELECT * FROM attempts WHERE attempt_id=?', (aid,)).fetchone()
            if a['state'] != 'launched':
                return
            if a['launches'] < self.retry_limit:
                self._set(c, aid, 'reserved', error=detail)
            else:
                self._set(c, aid, 'unknown', error=f'unstarted too often: {detail}')

    def _unknown(self, aid, detail):
        with self._tx() as c:
            a = c.execute('SELECT state FROM attempts WHERE attempt_id=?', (aid,)).fetchone()
            if a['state'] == 'launched':
                self._set(c, aid, 'unknown', error=detail)
                c.execute('INSERT INTO rejections(at, attempt_id, reason, detail) VALUES(?, ?, ?, ?)',
                          (self.spool.clock(), aid, 'unknown_outcome', detail))

    def _capture(self, aid, capture):
        """Validate and durably store a capture. Returns 'captured', 'noop' or 'rejected' (recorded)."""
        with self._tx() as c:
            now = self.spool.clock()
            a = c.execute('SELECT * FROM attempts WHERE attempt_id=?', (aid,)).fetchone()
            if a is None:
                raise SpoolError(f'unknown attempt {aid}')
            expected = [r['id'] for r in c.execute('SELECT id FROM jobs WHERE batch_id=? ORDER BY position', (a['batch_id'],))]

            def reject(reason, detail, job_id=None, unknown=False):
                c.execute('INSERT INTO rejections(at, attempt_id, job_id, reason, detail) VALUES(?, ?, ?, ?, ?)',
                          (now, aid, job_id, reason, str(detail)[:2000]))
                if unknown and a['state'] == 'launched':
                    self._set(c, aid, 'unknown', error=f'{reason}: {str(detail)[:200]}')
                return 'rejected'

            if type(capture) is not dict:
                return reject('invalid_capture', f'capture must be a dict, got {type(capture).__name__}', unknown=True)
            if 'results' in capture and set(capture) <= {'results', 'call_id'}:
                results, call_id = capture['results'], capture.get('call_id')
            else:
                results, call_id = capture, None
            if type(results) is not dict or not all(type(k) is str for k in results) or \
                    (call_id is not None and type(call_id) is not str):
                return reject('invalid_capture', 'results must map ids to values and call_id must be a string', unknown=True)
            foreign = sorted(k for k in results if k not in set(expected))
            if foreign:
                for k in foreign:
                    reject('foreign_result_id', f'id {k} is not part of batch {a["batch_id"]}', job_id=k)
                return reject('capture_rejected', f'{len(foreign)} foreign result id(s); capture not stored', unknown=True)
            rows = {}
            for i in expected:
                if i not in results:
                    rows[i] = {'error': 'missing_result'}
                    continue
                try:
                    canonical(results[i])
                    rows[i] = results[i]
                except RegistryError as exc:
                    reject('invalid_result', exc, job_id=i)
                    rows[i] = {'error': 'invalid_result'}
            body = _jdump({'call_id': call_id, 'rows': rows})
            digest = hashlib.sha256(body.encode('utf-8')).hexdigest()
            if a['state'] in ('captured', 'delivered'):
                if a['capture_hash'] == digest:
                    return 'noop'
                return reject('conflicting_capture', 'a different capture is already stored for this attempt')
            if a['state'] not in ('launched', 'unknown'):
                return reject('capture_without_launch', f'attempt is {a["state"]}')
            self._set(c, aid, 'captured', captured_at=now, capture=body, capture_hash=digest, call_id=call_id)
            return 'captured'

    def _deliver(self, aid):
        with self._tx() as c:
            a = c.execute('SELECT * FROM attempts WHERE attempt_id=?', (aid,)).fetchone()
            if a is None or a['state'] != 'captured':
                return False
            b = c.execute('SELECT * FROM batches WHERE batch_id=?', (a['batch_id'],)).fetchone()
            rows = json.loads(a['capture'])['rows']
            now = self.spool.clock()
            for j in c.execute('SELECT * FROM jobs WHERE batch_id=? ORDER BY position', (a['batch_id'],)).fetchall():
                text = _jdump(rows[j['id']])
                have = c.execute('SELECT result FROM results WHERE job_id=?', (j['id'],)).fetchone()
                if have is not None:
                    if have['result'] != text:
                        c.execute('INSERT INTO rejections(at, attempt_id, job_id, reason, detail) VALUES(?, ?, ?, ?, ?)',
                                  (now, aid, j['id'], 'conflicting_duplicate_delivery', 'row already delivered differently'))
                    continue
                c.execute('INSERT INTO results VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                          (j['id'], j['producer'], j['submission'], j['key'], j['op'], j['dataset_id'], b['batch_id'], aid,
                           b['request_id'], j['position'], a['call_id'], text, j['submitted_at'], b['reserved_at'],
                           a['launched_at'], a['captured_at'], now))
            self._at('before_delivery_commit', b['batch_id'])  # raising here rolls the whole delivery back
            self._set(c, aid, 'delivered', delivered_at=now)
        self._at('after_delivery', a['batch_id'])
        return True

    def _resume(self, stats):
        with self._tx() as c:
            todo = [r['attempt_id'] for r in c.execute("SELECT attempt_id FROM attempts WHERE state='captured' ORDER BY rowid")]
        for aid in todo:
            if self._deliver(aid):
                stats['delivered'] += 1

    # -- public --
    def pump(self):
        """One non-blocking pass. Returns counters plus in_flight and next_deadline (scheduler-clock seconds)."""
        with self._lock:
            if self.host.closed:
                raise Fenced('scheduler is closed')
            stats = {'reserved': 0, 'launched': 0, 'captured': 0, 'delivered': 0}
            self._harvest(stats)
            self._resume(stats)
            self._reserve_due(stats)
            self._launch_free(stats)
            stats['in_flight'] = len(self._inflight)
            stats['next_deadline'] = self._deadline
            return stats

    def idle(self):
        """True when nothing is pending, reserved, in flight or awaiting delivery (unknown attempts do not count)."""
        with self._lock:
            if self._inflight or not self._done.empty():
                return False
            with self._tx() as c:
                return c.execute("SELECT (SELECT COUNT(*) FROM jobs WHERE batch_id IS NULL)"
                                 " + (SELECT COUNT(*) FROM attempts WHERE state IN ('reserved','launched','captured'))").fetchone()[0] == 0

    def run(self, *, until_idle=True, poll=0.05, stop=None):
        """Loop pump() until idle (or until `stop` is set when until_idle is False). Returns when done."""
        while True:
            stats = self.pump()
            if stop is not None and stop.is_set():
                return
            if until_idle and self.idle():
                return
            wait = poll
            if stats['next_deadline'] is not None:
                wait = max(0.0, min(poll, stats['next_deadline'] - self.clock()))
            self._wake.wait(wait)
            self._wake.clear()

    def unresolved(self):
        return self.spool.unresolved()

    def reconcile(self, attempt_id, capture=None, *, provably_unlaunched=False):
        """Resolve an 'unknown' attempt.

        With a capture: validate, store and deliver it (foreign ids reject it, recorded). With
        provably_unlaunched=True and no capture: void the attempt and reserve a fresh one for the same batch, which
        the next pump launches. Returns the final attempt state.
        """
        with self._lock:
            if provably_unlaunched:
                if capture is not None:
                    raise SpoolError('give either a capture or provably_unlaunched, not both')
                with self._tx() as c:
                    a = c.execute('SELECT * FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
                    if a is None or a['state'] != 'unknown':
                        raise SpoolError(f'attempt {attempt_id} is not unknown')
                    nid = attempt_id_of(a['batch_id'], a['n'] + 1)
                    now = self.spool.clock()
                    c.execute("UPDATE attempts SET state='void', reconciled=1 WHERE attempt_id=?", (attempt_id,))
                    c.execute("INSERT INTO attempts(attempt_id, batch_id, n, state, epoch, reserved_at) VALUES(?, ?, ?, 'reserved', ?, ?)",
                              (nid, a['batch_id'], a['n'] + 1, self.host.epoch, now))
                    c.execute("UPDATE batches SET state='reserved', attempt_id=? WHERE batch_id=?", (nid, a['batch_id']))
                return 'void'
            with self._tx() as c:
                a = c.execute('SELECT state FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
            if a is None:
                raise SpoolError(f'unknown attempt {attempt_id}')
            if a['state'] not in ('unknown', 'captured', 'delivered'):
                raise SpoolError(f'attempt {attempt_id} is {a["state"]}, not unknown')
            status = self._capture(attempt_id, capture)
            if status == 'rejected':
                raise SpoolError(f'capture for {attempt_id} rejected and recorded')
            if status == 'captured':
                with self._tx() as c:
                    c.execute('UPDATE attempts SET reconciled=1 WHERE attempt_id=?', (attempt_id,))
            self._at('after_capture', None)
            self._deliver(attempt_id)
            with self._tx() as c:
                return c.execute('SELECT state FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()['state']
