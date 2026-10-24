"""Producer spool and single locked drainer for `oz map` (build step 5, amendment 1 D7 and D8).

Why not the workspace queue: take_over fences older coordinators, so several producers cannot each drain. Here
producers only publish fragment files; exactly one process holds the drain lock and turns fragments into batches.

Layout under spool_dir
  fragments/<producer>.<submission>.json   one atomically published fragment per submission (kept as the payload record)
  batches/<batch_id>.json                  batch state: reserved -> dispatched -> captured -> delivered
  captures/<batch_id>.json                 what dispatch returned, written before the state moves to captured
  results/<producer>/<submission>.json     per-submission result file, merged idempotently by delivery id
  ids.json                                 delivery id -> identity, for collision detection
  drain.lock                               {pid, epoch, token} of the one drainer

Pooling: fragments are merged only when their full bindings (contract, check, permission, worker_hash, input policy,
anything else the caller puts there) are canonically equal. A group flushes when it holds max_records pending records
(full chunks of exactly max_records) or when its oldest pending record has waited max_wait seconds.

Delivery ids (D8): 'j' + lowercase unpadded base32 of sha256(canonical([producer, submission, op, key])), 53 characters.
Chunk boundaries never enter an id. Every result keeps producer, submission, job key, op, delivery id and a nullable
physical call id.

Crash recovery rule (documented, tested at every boundary). Each batch persists its state atomically:
  reserved    batch file exists, dispatch not started. Restart: dispatch it.
  dispatched  state written just before dispatch() is called. Restart: if captures/<id>.json exists the capture is
              adopted (no second call); if not, the call outcome is unknown and the batch is re-dispatched exactly
              once more per restart (attempts counter). So dispatch is at-least-once only when no capture exists;
              after max_attempts the batch is captured as failed rows instead of looping.
  captured    capture file is durable. Restart: deliver, never dispatch again.
  delivered   all result files hold the batch's rows. Terminal.
Delivery merges by delivery id and never overwrites an existing row, so a crash in the middle of delivery and a
restart yield each row exactly once. The capture file is the source of truth: it wins over a stale state value.

Lock staleness rule: the lock file is created with O_EXCL and holds owner pid, epoch and a random token. A lock is
stale when its owner pid is not alive, or when the owner looks alive but its epoch is older than hard_lease seconds
(guards against pid reuse; a healthy drainer refreshes the epoch every iteration, so only a hung one trips it).
Takeover goes through a short-lived guard file (also O_EXCL, itself expired after guard_ttl) so that two racing
takers cannot both win; the winner re-reads the lock under the guard before replacing it. A drainer re-checks its
token every iteration and raises LockLost if it was taken over.
"""

import base64
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

from oz_registry import RegistryError, canonical

SCHEMA = 'oz.spool/1'
NAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
STATES = ('reserved', 'dispatched', 'captured', 'delivered')


class SpoolError(Exception):
    pass


class LockHeld(SpoolError):
    pass


class LockLost(SpoolError):
    pass


# ---- identity ----

def _b32(data: bytes) -> str:
    return base64.b32encode(hashlib.sha256(data).digest()).decode('ascii').lower().rstrip('=')


def delivery_id(producer, submission, op, key):
    """D8 compact name: 'j' plus 52 base32 characters, 53 in all."""
    return 'j' + _b32(canonical([producer, submission, op, key]))


def bindings_hash(bindings):
    return hashlib.sha256(canonical(bindings)).hexdigest()


def _batch_id(group_hash, ids):
    return 'b' + _b32(canonical([group_hash, sorted(ids)]))


# ---- files ----

def _publish(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp')
    with open(temp, 'wb') as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


def _write_json(path: Path, value):
    _publish(path, canonical(value))


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None


def _paths(spool_dir):
    root = Path(spool_dir)
    return root, root / 'fragments', root / 'batches', root / 'captures', root / 'results'


def _name(label, value):
    if type(value) is not str or not NAME_RE.match(value):
        raise SpoolError(f'{label} must match {NAME_RE.pattern}')
    return value


# ---- producer side ----

def submit(spool_dir, producer, submission, jobs, bindings, *, clock=time.time):
    """Atomically publish a fragment and return {delivery_id: job_key} in job order.

    jobs: list of {'key': str, 'op': str (optional, default ''), 'text': str}. bindings: JSON object holding contract
    hash, check hash, permission hash, worker_hash and input policy (at least those; extras also bind pooling).
    The file appears fully written or not at all. Resubmitting the same (producer, submission) with identical
    payload is a no-op; a changed payload for that id raises (D8: new submissions get new ids).
    """
    _name('producer', producer)
    _name('submission', submission)
    if type(bindings) is not dict or not bindings:
        raise SpoolError('bindings must be a non-empty object')
    if not isinstance(jobs, (list, tuple)) or not jobs:
        raise SpoolError('jobs must be a non-empty list')
    entries, seen = [], set()
    try:
        canonical(bindings)
        for seq, job in enumerate(jobs):
            if type(job) is not dict or type(job.get('key')) is not str or type(job.get('text')) is not str:
                raise SpoolError('each job needs string key and text')
            op = job.get('op', '')
            if type(op) is not str:
                raise SpoolError('job op must be a string')
            if (op, job['key']) in seen:
                raise SpoolError(f'duplicate logical job {op!r}/{job["key"]!r}')
            seen.add((op, job['key']))
            entries.append({'seq': seq, 'key': job['key'], 'op': op, 'text': job['text'],
                            'id': delivery_id(producer, submission, op, job['key'])})
    except RegistryError as exc:
        raise SpoolError(f'not canonical JSON: {exc}') from None
    fragment = {'schema': SCHEMA, 'producer': producer, 'submission': submission, 'bindings': bindings,
                'bindings_hash': bindings_hash(bindings), 'jobs': entries}
    _, fragments, *_ = _paths(spool_dir)
    path = fragments / f'{producer}.{submission}.json'
    existing = _read_json(path)
    if existing is not None:
        same = {k: v for k, v in existing.items() if k != 'submitted_at'} == fragment
        if not same:
            raise SpoolError(f'submission {producer}/{submission} already exists with a different payload')
    else:
        fragment['submitted_at'] = clock()
        _write_json(path, fragment)
    return {e['id']: e['key'] for e in entries}


def collect(spool_dir, producer, submission):
    """Read a producer's result file: {'results': {delivery_id: row}, 'complete': bool}. Never blocks."""
    _, fragments, _, _, results = _paths(spool_dir)
    fragment = _read_json(fragments / f'{producer}.{submission}.json')
    if fragment is None:
        raise SpoolError(f'unknown submission {producer}/{submission}')
    got = (_read_json(results / producer / f'{submission}.json') or {}).get('results', {})
    return {'results': got, 'complete': all(j['id'] in got for j in fragment['jobs'])}


# ---- lock ----

def pid_alive(pid):
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return kernel.GetLastError() == 5  # access denied means it exists
        try:
            code = ctypes.c_ulong()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class DrainLock:
    """Exclusive drainer lock: lock file with owner pid and epoch, stale takeover as described in the module doc."""

    def __init__(self, spool_dir, *, clock=time.time, pid=None, alive=pid_alive, hard_lease=6 * 3600.0, guard_ttl=30.0):
        self.path = Path(spool_dir) / 'drain.lock'
        self.guard = Path(spool_dir) / 'drain.lock.guard'
        self.clock, self.alive = clock, alive
        self.pid = os.getpid() if pid is None else pid
        self.hard_lease, self.guard_ttl = hard_lease, guard_ttl
        self.token = uuid.uuid4().hex
        self.held = False

    def _body(self):
        return canonical({'pid': self.pid, 'epoch': self.clock(), 'token': self.token})

    def _create(self):
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, 'wb') as file:
            file.write(self._body())
            file.flush()
            os.fsync(file.fileno())
        return True

    def _stale(self, info):
        if info is None or type(info.get('pid')) is not int:
            return True  # unreadable or half-written lock content
        if not self.alive(info['pid']):
            return True
        return self.clock() - float(info.get('epoch', 0)) > self.hard_lease

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._create():
            self.held = True
            return self
        try:
            info = json.loads(self.path.read_text(encoding='utf-8'))
        except (FileNotFoundError, ValueError):
            info = None
        if not self._stale(info):
            raise LockHeld(f'drainer already running (pid {info.get("pid")})')
        try:  # takeover guard: one taker at a time
            fd = os.open(self.guard, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except FileExistsError:
            try:
                if time.time() - self.guard.stat().st_mtime > self.guard_ttl:
                    self.guard.unlink()
            except OSError:
                pass
            raise LockHeld('another process is taking over the stale lock') from None
        try:
            try:
                again = json.loads(self.path.read_text(encoding='utf-8'))
            except (FileNotFoundError, ValueError):
                again = None
            if again != info and not self._stale(again):
                raise LockHeld('lock was refreshed during takeover')
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            if not self._create():
                raise LockHeld('lost the race for the lock')
            self.held = True
        finally:
            try:
                self.guard.unlink()
            except OSError:
                pass
        return self

    def heartbeat(self):
        """Refresh the epoch; raise LockLost if someone else owns the lock now."""
        try:
            info = json.loads(self.path.read_text(encoding='utf-8'))
        except (FileNotFoundError, ValueError):
            info = None
        if not info or info.get('token') != self.token:
            self.held = False
            raise LockLost('drain lock was taken over')
        _write_json(self.path, {'pid': self.pid, 'epoch': self.clock(), 'token': self.token})

    def release(self):
        if not self.held:
            return
        self.held = False
        try:
            info = json.loads(self.path.read_text(encoding='utf-8'))
            if info.get('token') == self.token:
                self.path.unlink()
        except (OSError, ValueError):
            pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()


# ---- drainer ----

class _Drainer:
    def __init__(self, spool_dir, dispatch, max_records, max_wait, clock, fault, max_attempts, lock):
        (self.root, self.fragments, self.batches, self.captures, self.results) = _paths(spool_dir)
        self.dispatch, self.max_records, self.max_wait = dispatch, max_records, max_wait
        self.clock, self.fault, self.max_attempts, self.lock = clock, fault, max_attempts, lock
        self.batch_ids = []  # batches handled by this drain call, for the caller

    def at(self, point, batch_id=None):
        if self.fault is not None:
            self.fault(point, batch_id)

    # identity registry with collision detection
    def _register(self, identities):
        path = self.root / 'ids.json'
        known = _read_json(path) or {}
        changed = False
        for did, identity in identities.items():
            old = known.get(did)
            if old is not None and old != identity:
                raise SpoolError(f'delivery id collision {did}: {old} vs {identity}')
            if old is None:
                known[did] = identity
                changed = True
        if changed:
            _write_json(path, known)

    def _batch_path(self, batch_id):
        return self.batches / f'{batch_id}.json'

    def _save(self, batch):
        _write_json(self._batch_path(batch['batch_id']), batch)

    def _pending_by_group(self):
        reserved = set()
        for path in self.batches.glob('b*.json'):
            reserved.update(r['id'] for r in _read_json(path)['records'])
        groups = {}
        for path in sorted(self.fragments.glob('*.json')):
            frag = _read_json(path)
            if frag is None:
                continue
            for job in frag['jobs']:
                if job['id'] in reserved:
                    continue
                groups.setdefault(frag['bindings_hash'], {'bindings': frag['bindings'], 'records': []})
                groups[frag['bindings_hash']]['records'].append({
                    'id': job['id'], 'producer': frag['producer'], 'submission': frag['submission'],
                    'key': job['key'], 'op': job['op'], 'text': job['text'],
                    'submitted_at': frag['submitted_at'], 'seq': job['seq']})
        for group in groups.values():
            group['records'].sort(key=lambda r: (r['submitted_at'], r['producer'], r['submission'], r['seq']))
        return groups

    def _reserve(self, group_hash, bindings, records):
        self._register({r['id']: [r['producer'], r['submission'], r['op'], r['key']] for r in records})
        batch = {'schema': SCHEMA, 'batch_id': _batch_id(group_hash, [r['id'] for r in records]),
                 'state': 'reserved', 'bindings_hash': group_hash, 'bindings': bindings, 'attempts': 0,
                 'reserved_at': self.clock(), 'dispatched_at': None, 'captured_at': None, 'delivered_at': None,
                 'call_id': None, 'records': records}
        self._save(batch)
        self.at('after_reserve', batch['batch_id'])
        return batch

    def _unfinished(self):
        out = []
        for path in self.batches.glob('b*.json'):
            batch = _read_json(path)
            if batch['state'] != 'delivered':
                out.append(batch)
        out.sort(key=lambda b: (b['reserved_at'], b['batch_id']))
        return out

    def _capture_path(self, batch_id):
        return self.captures / f'{batch_id}.json'

    def _run(self, batch):
        bid = batch['batch_id']
        self.batch_ids.append(bid)
        capture = _read_json(self._capture_path(bid))
        if capture is not None and batch['state'] in ('reserved', 'dispatched'):
            batch['state'] = 'captured'  # the capture file wins over a stale state value
            batch['captured_at'] = capture['captured_at']
            batch['call_id'] = capture.get('call_id')
            self._save(batch)
        if batch['state'] in ('reserved', 'dispatched'):
            self._dispatch(batch)
            capture = _read_json(self._capture_path(bid))
        if batch['state'] == 'captured':
            self._deliver(batch, capture)

    def _dispatch(self, batch):
        bid = batch['batch_id']
        if batch['attempts'] >= self.max_attempts:
            rows = {r['id']: {'error': 'dispatch_abandoned', 'attempts': batch['attempts']} for r in batch['records']}
            self._capture(batch, rows, None)
            return
        batch['attempts'] += 1
        batch['state'] = 'dispatched'
        if batch['dispatched_at'] is None:
            batch['dispatched_at'] = self.clock()
        self._save(batch)
        self.at('after_dispatch_state', bid)
        self.lock.heartbeat()
        view = {'batch_id': bid, 'bindings': batch['bindings'], 'attempt': batch['attempts'],
                'records': [{k: r[k] for k in ('id', 'producer', 'submission', 'key', 'op', 'text')}
                            for r in batch['records']]}
        try:
            ret = self.dispatch(view)
        except Exception:
            self.at('dispatch_failed', bid)
            raise  # outcome unknown: state stays dispatched, next drain re-dispatches until max_attempts
        self.at('after_dispatch_call', bid)
        call_id = None
        if type(ret) is dict and set(ret) == {'results', 'call_id'}:
            ret, call_id = ret['results'], ret['call_id']
        if type(ret) is not dict:
            raise SpoolError('dispatch must return {delivery_id: result}')
        rows = {r['id']: ret.get(r['id'], {'error': 'missing_result'}) for r in batch['records']}
        self._capture(batch, rows, call_id)

    def _capture(self, batch, rows, call_id):
        bid = batch['batch_id']
        now = self.clock()
        _write_json(self._capture_path(bid), {'batch_id': bid, 'captured_at': now, 'call_id': call_id, 'rows': rows})
        self.at('after_capture_file', bid)
        batch['state'], batch['captured_at'], batch['call_id'] = 'captured', now, call_id
        self._save(batch)
        self.at('after_capture_state', bid)

    def _deliver(self, batch, capture):
        bid = batch['batch_id']
        now = self.clock()
        by_sub = {}
        for rec in batch['records']:
            by_sub.setdefault((rec['producer'], rec['submission']), []).append(rec)
        for n, ((producer, submission), recs) in enumerate(sorted(by_sub.items())):
            path = self.results / producer / f'{submission}.json'
            doc = _read_json(path) or {'schema': SCHEMA, 'producer': producer, 'submission': submission, 'results': {}}
            for rec in recs:
                if rec['id'] in doc['results']:
                    continue  # exactly once: a crashed delivery never rewrites a row
                disp = batch['dispatched_at']
                doc['results'][rec['id']] = {
                    'producer': producer, 'submission': submission, 'key': rec['key'], 'op': rec['op'],
                    'delivery_id': rec['id'], 'batch_id': bid, 'call_id': capture.get('call_id'),
                    'result': capture['rows'][rec['id']],
                    'submitted_at': rec['submitted_at'], 'dispatched_at': disp, 'delivered_at': now,
                    'queue_s': disp - rec['submitted_at'], 'turnaround_s': now - rec['submitted_at']}
            _write_json(path, doc)
            if n == 0 and len(by_sub) > 1:
                self.at('mid_delivery', bid)
        self.at('after_delivery_files', bid)
        batch['state'], batch['delivered_at'] = 'delivered', now
        self._save(batch)
        self.at('after_delivery_state', bid)

    def step(self):
        """One pass. Returns (progressed, next_deadline or None)."""
        self.lock.heartbeat()
        progressed = False
        for batch in self._unfinished():
            self._run(batch)
            progressed = True
        deadline = None
        now = self.clock()
        for gh, group in sorted(self._pending_by_group().items()):
            recs = group['records']
            while len(recs) >= self.max_records:
                self._run(self._reserve(gh, group['bindings'], recs[:self.max_records]))
                recs = recs[self.max_records:]
                progressed = True
            if recs:
                due = recs[0]['submitted_at'] + self.max_wait
                if now >= due:
                    self._run(self._reserve(gh, group['bindings'], recs))
                    progressed = True
                else:
                    deadline = due if deadline is None else min(deadline, due)
        return progressed, deadline


def drain(spool_dir, dispatch, *, max_records=64, max_wait=1.0, clock=time.time, sleep=time.sleep,
          once=False, fault=None, max_attempts=2, lock=None):
    """Hold the drain lock and run until nothing is pending (or one pass with once=True).

    dispatch(batch) gets {'batch_id', 'bindings', 'attempt', 'records': [{id, producer, submission, key, op, text}]}
    and returns {delivery_id: result} or {'results': {...}, 'call_id': ...}. It is called once per batch, and again
    only after a crash or exception left a dispatched batch without a capture (see module doc). Raises LockHeld if
    another live drainer owns the lock. Returns {'batches': [batch ids handled], 'pending': bool}.
    """
    if max_records < 1 or max_wait < 0:
        raise SpoolError('max_records must be >= 1 and max_wait >= 0')
    root, fragments, batches, captures, results = _paths(spool_dir)
    for d in (fragments, batches, captures, results):
        d.mkdir(parents=True, exist_ok=True)
    own = lock is None
    lock = DrainLock(spool_dir, clock=clock) if own else lock
    if own:
        lock.acquire()
    try:
        drainer = _Drainer(spool_dir, dispatch, max_records, max_wait, clock, fault, max_attempts, lock)
        while True:
            progressed, deadline = drainer.step()
            if once:
                return {'batches': drainer.batch_ids, 'pending': deadline is not None}
            if deadline is None:
                if not progressed:
                    return {'batches': drainer.batch_ids, 'pending': False}
                continue
            sleep(max(0.0, deadline - clock()))
    finally:
        if own:
            lock.release()


def queue_report(spool_dir):
    """Per-record queue times and makespan from delivered rows: submit -> dispatch -> delivery."""
    *_, results = _paths(spool_dir)
    rows = []
    for path in sorted(results.glob('*/*.json')):
        rows.extend(_read_json(path)['results'].values())
    if not rows:
        return {'records': 0}
    return {'records': len(rows),
            'max_queue_s': max(r['queue_s'] for r in rows),
            'mean_queue_s': sum(r['queue_s'] for r in rows) / len(rows),
            'max_turnaround_s': max(r['turnaround_s'] for r in rows),
            'makespan_s': max(r['delivered_at'] for r in rows) - min(r['submitted_at'] for r in rows)}
