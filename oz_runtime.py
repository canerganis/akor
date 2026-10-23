"""SQLite-backed OZ inbox with dependency gating and renewable delivery attempts.

Exactly-once insertion, at-least-once delivery. External tool effects must use
their own idempotency keys. This module never executes tools or contacts models.

Jobs pinned to the oz1g-selective-v1 profile (oz_accept) also get a durable dispatch journal (launch intent, launch,
capture, uncertainty), stored candidates with their check verdicts, a coordinator epoch and one conditional
transaction per settlement (foundation record clauses 1 to 3 and 5). Jobs on the default oz1g-header profile keep
the shipped path: claim, settle, retry.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Callable, Iterable
import uuid

from oz import Channel, Error, TokenMeter, _dump
from oz_accept import HEADER, PROFILES, SELECTIVE, accept_key, compute_key, job_inputs, pin
from oz_batch import PREVIEW_RECEIPT, Batch, BudgetError, render, valid_id
from oz_reply import RawJSON, slot_ids


class Fenced(Error):
    """A worker of an obsolete coordinator epoch asked to claim selective work: refused before any attempt is charged."""


@dataclass(frozen=True)
class Job:
    id: str
    wire: str
    attempt: int


@dataclass(frozen=True)
class Delivery:
    binding: str
    lease: str
    owner: str
    kind: str
    jobs: tuple[Job, ...]

    def prepare(self, channel: Channel, **options) -> Batch:
        if channel.binding != self.binding:
            raise Error('delivery channel mismatch')
        if self.kind != 'work':
            raise Error('host events do not require a model input')
        return render(channel, [(j.id, j.wire) for j in self.jobs], **options)


@dataclass(frozen=True)
class Plan:
    jobs: tuple[Job, ...]
    packet: Batch | None
    deferred: tuple[str, ...]


@dataclass(frozen=True)
class Outcome:
    """status ok, retry or failed; text is the stored result or reason. value, for an ok job, is the
    compact JSON of the accepted native value; dependents receive it as a JSON value, never as a string."""
    status: str
    text: str
    value: str | None = None


def _is_json(text: object) -> bool:
    """True when text is one valid JSON document (a result record is stored as its compact text)."""
    try:
        json.loads(text, parse_constant=lambda _: 1 / 0)
        return True
    except (TypeError, ValueError, ZeroDivisionError, RecursionError):
        return False


def _base36(n: int) -> str:
    digits = ''
    while n:
        n, d = divmod(n, 36)
        digits = '0123456789abcdefghijklmnopqrstuvwxyz'[d] + digits
    return digits


class Inbox:
    def __init__(self, path: str | Path = ':memory:', *, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        # Durability must not depend on how SQLite was built (clause 5): FULL syncs the WAL at every commit.
        self.db.execute('PRAGMA synchronous=FULL')
        try:
            self._initialize()
        except BaseException:
            self.db.close()
            raise

    def _initialize(self):
        with self._transaction():
            version = self.db.execute('PRAGMA user_version').fetchone()[0]
            if version not in {0, 1, 2, 3}:
                raise Error('unsupported inbox schema version')
            schema = '''
            CREATE TABLE IF NOT EXISTS channels(binding TEXT PRIMARY KEY, snapshot TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(
                seq INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL,
                binding TEXT NOT NULL REFERENCES channels(binding), wire TEXT NOT NULL,
                identity TEXT NOT NULL, kind TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL, lease TEXT, owner TEXT, deadline REAL,
                result TEXT, error TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS dependencies(
                job TEXT NOT NULL REFERENCES jobs(id), prior TEXT NOT NULL REFERENCES jobs(id),
                PRIMARY KEY(job,prior));
            CREATE INDEX IF NOT EXISTS pending_jobs ON jobs(binding,kind,state,seq);
            CREATE INDEX IF NOT EXISTS leased_jobs ON jobs(lease);
            CREATE TABLE IF NOT EXISTS events(
                seq INTEGER PRIMARY KEY, mid TEXT NOT NULL REFERENCES jobs(id),
                event TEXT NOT NULL, at REAL NOT NULL, details TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS job_events ON events(mid,seq);
            CREATE TABLE IF NOT EXISTS receipts(seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS runs(
                seq INTEGER PRIMARY KEY, binding TEXT NOT NULL, at REAL NOT NULL,
                ids TEXT NOT NULL, report TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS literal_names(
                binding TEXT NOT NULL REFERENCES channels(binding), text TEXT NOT NULL, n INTEGER NOT NULL,
                PRIMARY KEY(binding,text), UNIQUE(binding,n));
            CREATE TABLE IF NOT EXISTS coordinator(id INTEGER PRIMARY KEY CHECK(id=1), epoch INTEGER NOT NULL);
            INSERT OR IGNORE INTO coordinator VALUES (1,1);
            CREATE TABLE IF NOT EXISTS dispatches(
                receipt TEXT PRIMARY KEY, binding TEXT NOT NULL, lease TEXT NOT NULL, owner TEXT NOT NULL,
                epoch INTEGER NOT NULL, call_id TEXT, created_at REAL NOT NULL, deadline REAL NOT NULL, timeout REAL,
                reservation TEXT NOT NULL, reservation_state TEXT NOT NULL, members TEXT NOT NULL,
                job_map TEXT NOT NULL, host_slots TEXT NOT NULL, system_sha256 TEXT NOT NULL, packet TEXT NOT NULL,
                route TEXT NOT NULL, capture_dir TEXT, request_sha256 TEXT, state TEXT NOT NULL, process TEXT,
                response TEXT, error TEXT, captured_at REAL, settled_at REAL, outcome TEXT);
            CREATE TABLE IF NOT EXISTS candidates(
                seq INTEGER PRIMARY KEY, job TEXT NOT NULL REFERENCES jobs(id), receipt TEXT NOT NULL,
                generation INTEGER NOT NULL, compute_key TEXT, value TEXT NOT NULL, stored TEXT NOT NULL,
                inputs TEXT NOT NULL, checks TEXT NOT NULL, verdicts TEXT NOT NULL, status TEXT NOT NULL,
                reason TEXT, suspect INTEGER NOT NULL, at REAL NOT NULL, accept_key TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS one_acceptance ON candidates(job,generation) WHERE status='accepted';
            CREATE INDEX IF NOT EXISTS candidate_jobs ON candidates(job,seq);
            '''
            for statement in schema.split(';'):
                if statement.strip():
                    self.db.execute(statement)
            columns = {r['name'] for r in self.db.execute('PRAGMA table_info(jobs)')}
            if 'available_at' not in columns:
                self.db.execute('ALTER TABLE jobs ADD COLUMN available_at REAL NOT NULL DEFAULT 0')
            if 'result_json' not in columns:
                self.db.execute('ALTER TABLE jobs ADD COLUMN result_json TEXT')
            # Additive columns (no schema version change): the pinned acceptance profile and checks, the logical
            # job generation, the pinned computation key and why a failed job failed (model_failure, exhausted,
            # cancelled; NULL on rows from before these columns).
            for column, decl in (('profile', f"TEXT NOT NULL DEFAULT '{HEADER}'"),
                                 ('checks', "TEXT NOT NULL DEFAULT '[]'"),
                                 ('generation', 'INTEGER NOT NULL DEFAULT 1'), ('compute_key', 'TEXT'),
                                 ('failure_kind', 'TEXT')):
                if column not in columns:
                    self.db.execute(f'ALTER TABLE jobs ADD COLUMN {column} {decl}')
            if version < 3:
                # Literal jobs posted before literal_<n> naming keep inbox order: number them by seq.
                for row in self.db.execute("SELECT binding,wire FROM jobs WHERE substr(wire,1,1)=':' ORDER BY seq").fetchall():
                    self._literal_number(row['binding'], row['wire'][1:])
            self.db.execute('PRAGMA user_version=3')

    def _literal_number(self, binding: str, text: str) -> int:
        """Operation number of a literal text in a channel binding, allocated once and persisted.

        The smallest number not yet used for a different text; call inside a write transaction."""
        row = self.db.execute('SELECT n FROM literal_names WHERE binding=? AND text=?', (binding, text)).fetchone()
        if row is not None:
            return row['n']
        used = {r['n'] for r in self.db.execute('SELECT n FROM literal_names WHERE binding=?', (binding,))}
        n = next(i for i in range(len(used) + 1) if i not in used)
        self.db.execute('INSERT INTO literal_names VALUES (?,?,?)', (binding, text, n))
        return n

    def new_receipt(self) -> str:
        """Next attempt receipt: a never-reused counter in base 36, a few tokens long.

        It only correlates a reply with one call attempt; it is not a secret.
        """
        with self._transaction():
            seq = self.db.execute('INSERT INTO receipts(at) VALUES (?)', (self.clock(),)).lastrowid
        return _base36(seq)

    def next_receipt(self) -> str:
        """The receipt the next attempt will get, for previews with real token counts."""
        row = self.db.execute("SELECT seq FROM sqlite_sequence WHERE name='receipts'").fetchone()
        return _base36((row[0] if row else 0) + 1)

    def _event(self, mid: str, event: str, **details):
        self.db.execute('INSERT INTO events(mid,event,at,details) VALUES (?,?,?,?)',
                        (mid, event, self.clock(), _dump(details)))

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def _transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def post(self, channel: Channel, mid: str, wire: str, *, binding: str,
             after: Iterable[str] = (), max_attempts: int = 2, profile: str = HEADER, checks=None,
             registry=None) -> bool:
        """Return False for an identical retry; reject ID reuse with new meaning.

        profile pins the job's acceptance profile; checks (registered check specs, see oz_accept) need
        oz1g-selective-v1. Both belong to the job's identity: the same ID with another profile or checks is refused."""
        atoms = channel.accept(wire, binding=binding)
        if profile not in PROFILES:
            raise Error('profile must be one of ' + ', '.join(PROFILES))
        pinned = pin(checks, registry)
        if pinned and profile != SELECTIVE:
            raise Error(f'checks require the {SELECTIVE} profile')
        if not valid_id(mid) or type(max_attempts) is not int or not 1 <= max_attempts <= 100:
            raise Error('invalid message ID or retry limit')
        after = tuple(after)
        if len(after) > 64 or any(not valid_id(i) or i == mid for i in after) or len(set(after)) != len(after):
            raise Error('invalid dependencies')
        identity = _dump([binding, [vars(a) for a in atoms], sorted(after), max_attempts]
                         + ([{'profile': profile, 'checks': list(pinned)}] if profile != HEADER else []))
        kind = 'work' if channel.dispatch(wire, binding=binding)['needs_model'] else 'host'
        with self._transaction():
            previous = self.db.execute('SELECT identity FROM jobs WHERE id=?', (mid,)).fetchone()
            if previous:
                if previous['identity'] != identity:
                    raise Error('message ID already has different contents or routing')
                return False
            for dep in after:
                row = self.db.execute('''SELECT c.snapshot FROM jobs j JOIN channels c ON c.binding=j.binding
                                         WHERE j.id=?''', (dep,)).fetchone()
                if row is None or Channel.from_snapshot(json.loads(row['snapshot'])).scope != channel.scope:
                    raise Error('dependency must already exist in the same session, task and revision')
            self.db.execute('INSERT OR IGNORE INTO channels VALUES (?,?)', (binding, _dump(channel.snapshot())))
            self.db.execute('''INSERT INTO jobs(id,binding,wire,identity,kind,max_attempts,profile,checks)
                               VALUES (?,?,?,?,?,?,?,?)''', (mid, binding, wire, identity, kind, max_attempts, profile,
                                                       _dump(list(pinned))))
            self.db.executemany('INSERT INTO dependencies VALUES (?,?)', [(mid, d) for d in after])
            if atoms[0].code == ':':
                self._literal_number(binding, atoms[0].text)
            self._event(mid, 'posted', kind=kind)
        return True

    def _recover(self, binding: str, kind: str):
        expired = self.db.execute('''SELECT id,attempts,max_attempts FROM jobs
            WHERE binding=? AND kind=? AND state='leased' AND deadline<=?''',
                                 (binding, kind, self.clock())).fetchall()
        for row in expired:
            state = 'failed' if row['attempts'] >= row['max_attempts'] else 'pending'
            self.db.execute('''UPDATE jobs SET state=?,lease=NULL,owner=NULL,deadline=NULL,
                error='delivery lease expired',failure_kind=? WHERE id=?''',
                            (state, 'exhausted' if state == 'failed' else None, row['id']))
            self._event(row['id'], 'expired', state=state)

    def _ready(self, channel: Channel, kind: str, limit: int, ids=()):
        only = ' AND j.id IN (' + ','.join('?' for _ in ids) + ')' if ids else ''
        return self.db.execute('''SELECT j.* FROM jobs j
            WHERE j.binding=? AND j.kind=? AND j.available_at<=?
            AND (j.state='pending' OR (j.state='leased' AND j.deadline<=? AND j.attempts<j.max_attempts))
            AND NOT EXISTS (SELECT 1 FROM dependencies d JOIN jobs p ON p.id=d.prior
                            WHERE d.job=j.id AND p.state!='done')'''
            + only + ' ORDER BY j.seq LIMIT ?',
                              (channel.binding, kind, self.clock(), self.clock(), *ids, limit)).fetchall()

    def waiting(self, channel: Channel, *, min_batch: int, max_wait: float) -> bool:
        """True while fewer than min_batch work jobs are ready and the oldest is younger than max_wait.

        Waiting trades latency for fewer calls: each call pays a fixed prompt cost.
        """
        ready = self._ready(channel, 'work', min_batch)
        if not ready or len(ready) >= min_batch:
            return False
        oldest = self.db.execute(
            "SELECT MIN(at) FROM events WHERE event IN ('posted','requeued') AND mid IN ("
            + ','.join('?' for _ in ready) + ')', [r['id'] for r in ready]).fetchone()[0]
        return oldest is not None and self.clock() - oldest < max_wait

    def plan(self, channel: Channel, *, counters, limit: int = 64, max_tokens: int | None = None,
             max_bytes: int = 262144, receipt: str = PREVIEW_RECEIPT, context_policy: str = 'needed') -> Plan:
        """Read-only packing: the largest feasible ordered prefix of ready jobs.

        Every prefix length is measured, longest first, as the complete model
        input (system text and body). Only when even the head job is oversized
        does greedy packing defer it so it cannot block others.
        """
        if type(limit) is not int or not 1 <= limit <= 64:
            raise Error('plan limit must be 1..64')
        meter = TokenMeter(counters)
        if not meter.counters:
            raise Error('planning requires tokenizer counters')
        if max_tokens is not None and (type(max_tokens) is not int or max_tokens < 1):
            raise Error('invalid token budget')
        if type(max_bytes) is not int or max_bytes < 1:
            raise Error('invalid byte budget')
        rows = self._ready(channel, 'work', limit)
        if not rows:
            return Plan((), None, ())
        cached = tuple(lambda s, i=i: meter.counts(s)[i] for i in range(len(meter.counters)))
        literals = {r['text']: r['n'] for r in self.db.execute(
            'SELECT text,n FROM literal_names WHERE binding=?', (channel.binding,))}
        def pack(items):
            return render(channel, [(r['id'], r['wire']) for r in items], counters=cached,
                          max_tokens=max_tokens, max_bytes=max_bytes,
                          receipt=receipt, handoffs=self._handoffs([r['id'] for r in items]),
                          context_policy=context_policy, literals=literals)
        selected, deferred, packet = [], [], None
        for size in range(len(rows), 0, -1):
            try:
                packet = pack(rows[:size])
            except BudgetError:
                continue
            selected = rows[:size]
            break
        else:
            for row in rows:
                try:
                    candidate = pack([*selected, row])
                except BudgetError:
                    deferred.append(row['id'])
                else:
                    selected.append(row)
                    packet = candidate
        return Plan(tuple(Job(r['id'], r['wire'], r['attempts'] + 1) for r in selected),
                    packet, tuple(deferred))

    def _handoffs(self, ids):
        """[job, predecessor, result record] per delivered job, in dependency declaration order.

        Only direct predecessors that are done. The record is the accepted JSON value (result_json) as a RawJSON,
        so the packet carries its stored bytes unchanged (clause 12); a job settled without one yields its stored
        result text as a string. Unverified agent data."""
        links = []
        for mid in ids:
            rows = self.db.execute('''SELECT p.id,p.result,p.result_json FROM dependencies d JOIN jobs p ON p.id=d.prior
                WHERE d.job=? AND p.state='done' ORDER BY d.rowid''', (mid,)).fetchall()
            links.extend((mid, r['id'], r['result'] if r['result_json'] is None else RawJSON(r['result_json']))
                         for r in rows)
        return links

    def claim_prepared(self, channel: Channel, *, owner: str, counters, receipt: str, limit: int = 64,
                       max_tokens: int | None = None, max_bytes: int = 262144,
                       lease_seconds: float = 60, context_policy: str = 'needed',
                       dispatch: dict | None = None) -> tuple[Delivery, Batch] | None:
        """Measure outside the write lock, then atomically reserve the selected jobs.

        A budget failure consumes no attempts. Concurrent changes trigger a fresh
        plan, at most four times; only reserved jobs receive a lease/attempt.

        With dispatch ({epoch, route, call_id, timeout, capture_dir}), a packet holding an oz1g-selective-v1 job
        also gets its launch intent journaled in the same transaction as the lease (clause 5 step 1). Before any attempt is
        charged, a worker of an obsolete epoch is refused (Fenced) and a job whose pinned computation key differs is
        failed on its own (unresolved, reason pinned_computation_mismatch) without blocking the other jobs of the
        channel. Header-only packets journal nothing and are never screened.
        """
        if not valid_id(owner) or type(lease_seconds) not in {int, float} or not 0 < lease_seconds <= 86400:
            raise Error('invalid delivery options')
        if receipt == PREVIEW_RECEIPT:
            # A real call needs a fresh receipt; the zero receipt is for previews only.
            raise Error('claim requires a fresh receipt, not the preview receipt')
        counters = tuple(counters)
        races = 0
        while races < 4:
            with self._transaction():
                self._recover(channel.binding, 'work')
            plan = self.plan(channel, counters=counters, limit=limit, max_tokens=max_tokens,
                             max_bytes=max_bytes, receipt=receipt, context_policy=context_policy)
            if not plan.jobs:
                if plan.deferred:
                    raise BudgetError('no ready job fits the budget; attempts unchanged; increase budget')
                return None
            token = uuid.uuid4().hex
            with self._transaction():
                ready = {r['id']: r for r in self._ready(channel, 'work', len(plan.jobs), tuple(j.id for j in plan.jobs))}
                if any(j.id not in ready or ready[j.id]['state'] != 'pending'
                       or ready[j.id]['attempts'] + 1 != j.attempt for j in plan.jobs):
                    races += 1
                    continue
                if dispatch is not None:
                    # Refused before any attempt is charged: an obsolete epoch (raises Fenced) or a job pinned to
                    # another computation (fails that job alone, then the packet is planned again without it).
                    if self._screen_dispatch(plan, channel.binding, dispatch):
                        continue
                self._lease(plan.jobs, token, owner, lease_seconds)
                if dispatch is not None:
                    self._open_dispatch(plan, channel.binding, token, owner, receipt, dispatch, max_tokens, lease_seconds)
            return Delivery(channel.binding, token, owner, 'work', plan.jobs), plan.packet
        raise Error('queue changed during planning; retry claim_prepared')

    def _lease(self, jobs, token, owner, lease_seconds):
        deadline = self.clock() + lease_seconds
        for job in jobs:
            self.db.execute('''UPDATE jobs SET state='leased',attempts=attempts+1,
                lease=?,owner=?,deadline=? WHERE id=?''', (token, owner, deadline, job.id))
            self._event(job.id, 'claimed', owner=owner, attempt=job.attempt)

    def claim(self, channel: Channel, *, owner: str, kind: str = 'work', limit: int = 8,
              lease_seconds: float = 60) -> Delivery | None:
        if not valid_id(owner) or kind not in {'work', 'host'} or type(limit) is not int or not 1 <= limit <= 64:
            raise Error('invalid delivery options')
        if type(lease_seconds) not in {int, float} or not 0 < lease_seconds <= 86400:
            raise Error('invalid lease duration')
        token = uuid.uuid4().hex
        with self._transaction():
            self._recover(channel.binding, kind)
            rows = self._ready(channel, kind, limit)
            if not rows:
                return None
            jobs = tuple(Job(r['id'], r['wire'], r['attempts'] + 1) for r in rows)
            self._lease(jobs, token, owner, lease_seconds)
        return Delivery(channel.binding, token, owner, kind,
                        jobs)

    def _check(self, delivery: Delivery) -> list[sqlite3.Row]:
        if not isinstance(delivery, Delivery):
            raise Error('invalid delivery')
        rows = self.db.execute('SELECT * FROM jobs WHERE lease=? ORDER BY seq', (delivery.lease,)).fetchall()
        if (not rows or tuple((r['id'], r['wire'], r['attempts']) for r in rows)
                != tuple((j.id, j.wire, j.attempt) for j in delivery.jobs)
                or any(r['binding'] != delivery.binding or r['owner'] != delivery.owner
                       or r['kind'] != delivery.kind or r['state'] != 'leased'
                       or r['deadline'] <= self.clock() for r in rows)):
            raise Error('stale, expired or mismatched delivery; no acknowledgement applied')
        return rows

    def complete(self, delivery: Delivery, results: dict[str, str]) -> None:
        """Atomically record each result and ACK. Result text is a host record, not proof."""
        if (not isinstance(delivery, Delivery) or not isinstance(results, dict)
                or set(results) != {j.id for j in delivery.jobs}
                or any(not isinstance(v, str) or len(v.encode('utf-8')) > 65536 for v in results.values())):
            raise Error('one bounded result string per job is required')
        with self._transaction():
            self._check(delivery)
            self.db.executemany('''UPDATE jobs SET state='done',result=?,result_json=NULL,lease=NULL,owner=NULL,
                deadline=NULL,error='' WHERE id=?''', [(results[j.id], j.id) for j in delivery.jobs])
            for job in delivery.jobs:
                self._event(job.id, 'done')

    def retry(self, delivery: Delivery, reason: str, *, permanent: bool = False) -> None:
        if not isinstance(reason, str) or not reason.strip() or len(reason.encode('utf-8')) > 4096:
            raise Error('retry requires a bounded reason')
        if type(permanent) is not bool:
            raise Error('invalid permanent flag')
        with self._transaction():
            self._check(delivery)
            self.db.execute('''UPDATE jobs SET
                state=CASE WHEN ? OR attempts>=max_attempts THEN 'failed' ELSE 'pending' END,
                failure_kind=CASE WHEN ? THEN 'cancelled' WHEN attempts>=max_attempts THEN 'exhausted' ELSE NULL END,
                error=?,lease=NULL,owner=NULL,deadline=NULL WHERE lease=?''',
                            (permanent, permanent, reason, delivery.lease))
            for job in delivery.jobs:
                self._event(job.id, 'retry_requested', permanent=permanent)

    def settle(self, delivery: Delivery, outcomes: dict[str, Outcome], *, retry_delay: float = 0,
               report: dict | None = None):
        """Per-job outcomes, validated as a whole before any ACK or dependency release."""
        if (not isinstance(delivery, Delivery) or not isinstance(outcomes, dict)
                or set(outcomes) != {j.id for j in delivery.jobs}
                or any(not isinstance(o, Outcome) or o.status not in {'ok', 'retry', 'failed'}
                       or not isinstance(o.text, str) or not o.text.strip()
                       or len(o.text.encode('utf-8')) > 65536
                       or (o.value is not None and (o.status != 'ok' or not _is_json(o.value)))
                       for o in outcomes.values())):
            raise Error('exactly one valid outcome per delivered job is required')
        if type(retry_delay) not in {int, float} or not 0 <= retry_delay <= 86400:
            raise Error('invalid retry delay')
        report_text = _dump(report or {})
        if len(report_text.encode('utf-8')) > 65536:
            raise Error('run report too large')
        with self._transaction():
            rows = self._check(delivery)
            for row in rows:
                outcome = outcomes[row['id']]
                state = ('done' if outcome.status == 'ok' else 'pending'
                         if outcome.status == 'retry' and row['attempts'] < row['max_attempts'] else 'failed')
                self.db.execute('''UPDATE jobs SET state=?,result=?,result_json=?,error=?,available_at=?,
                    lease=NULL,owner=NULL,deadline=NULL,failure_kind=? WHERE id=?''',
                                (state, outcome.text if state == 'done' else None,
                                 outcome.value if state == 'done' else None,
                                 '' if state == 'done' else outcome.text,
                                 self.clock() + retry_delay if state == 'pending' else 0,
                                 None if state != 'failed' else 'model_failure' if outcome.status == 'failed'
                                 else 'exhausted', row['id']))
                self._event(row['id'], state, outcome=outcome.status)
            self.db.execute('INSERT INTO runs(binding,at,ids,report) VALUES (?,?,?,?)',
                            (delivery.binding, self.clock(), _dump([j.id for j in delivery.jobs]), report_text))

    def requeue(self, mid: str, *, extra_attempts: int = 1):
        if type(extra_attempts) is not int or not 1 <= extra_attempts <= 100:
            raise Error('extra_attempts must be 1..100')
        with self._transaction():
            row = self.db.execute('SELECT state,attempts,max_attempts FROM jobs WHERE id=?', (mid,)).fetchone()
            if row is None or row['state'] not in ('failed', 'quarantined'):
                raise Error('only a failed job can be requeued; completed jobs need a new ID')
            if self.db.execute("SELECT 1 FROM events WHERE mid=? AND event='cancelled'", (mid,)).fetchone():
                # cancel() is final; a permanent retry() also reads failure_kind 'cancelled' but stays requeueable.
                raise Error('a cancelled job cannot be requeued; post it under a new ID')
            self.db.execute('''UPDATE jobs SET state='pending',available_at=0,error='',failure_kind=NULL,
                max_attempts=? WHERE id=?''', (max(row['attempts'], row['max_attempts']) + extra_attempts, mid))
            self._event(mid, 'requeued', extra_attempts=extra_attempts)

    def renew(self, delivery: Delivery, *, lease_seconds: float = 60) -> None:
        if type(lease_seconds) not in {int, float} or not 0 < lease_seconds <= 86400:
            raise Error('invalid lease duration')
        with self._transaction():
            self._check(delivery)
            self.db.execute('UPDATE jobs SET deadline=? WHERE lease=?', (self.clock() + lease_seconds, delivery.lease))

    def inspect(self, mid: str) -> dict:
        row = self.db.execute('''SELECT id,binding,wire,kind,state,attempts,max_attempts,
            available_at,deadline,result,error FROM jobs WHERE id=?''', (mid,)).fetchone()
        if row is None:
            raise Error('unknown message ID')
        result = dict(row)
        result['waiting_for'] = [dict(r) for r in self.db.execute('''
            SELECT p.id,p.state FROM dependencies d JOIN jobs p ON p.id=d.prior
            WHERE d.job=? AND p.state!='done' ORDER BY p.seq''', (mid,))]
        return result

    def records(self, ids: Iterable[str]) -> dict[str, dict]:
        """Read-only state, attempts, lease deadline, stored result, accepted JSON value (result_json) and error
        of these jobs; unknown IDs are omitted. Never changes a job."""
        ids = tuple(ids)
        found = {}
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            for row in self.db.execute('SELECT id,state,attempts,max_attempts,available_at,deadline,result,result_json,'
                                       'error FROM jobs WHERE id IN (' + ','.join('?' for _ in chunk) + ')', chunk):
                found[row['id']] = dict(row)
        return {mid: found[mid] for mid in ids if mid in found}

    def list_jobs(self, *, limit: int = 100, after_seq: int = 0) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000 or type(after_seq) is not int or after_seq < 0:
            raise Error('invalid listing limits')
        rows = self.db.execute('''SELECT seq,id FROM jobs WHERE seq>? ORDER BY seq LIMIT ?''',
                               (after_seq, limit)).fetchall()
        result = []
        for row in rows:
            job = self.inspect(row['id'])
            job.pop('wire')
            job.pop('result')
            job.pop('error')
            job['seq'] = row['seq']
            job['availability'] = (('waiting' if job['waiting_for'] else 'backoff'
                                    if job['available_at'] > self.clock() else 'ready')
                                   if job['state'] == 'pending' else
                                   'expired' if job['state'] == 'leased' and job['deadline'] <= self.clock()
                                   else job['state'])
            result.append(job)
        return result

    def history(self, mid: str, *, limit: int = 100) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise Error('invalid history limit')
        self.inspect(mid)
        rows = self.db.execute('''SELECT seq,event,at,details FROM events WHERE mid=?
            ORDER BY seq DESC LIMIT ?''', (mid, limit)).fetchall()
        return [dict(seq=r['seq'], event=r['event'], at=r['at'], details=json.loads(r['details']))
                for r in reversed(rows)]

    def runs(self, *, limit: int = 100) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise Error('invalid run limit')
        rows = self.db.execute('SELECT * FROM runs ORDER BY seq DESC LIMIT ?', (limit,)).fetchall()
        return [dict(seq=r['seq'], binding=r['binding'], at=r['at'], ids=json.loads(r['ids']),
                     report=json.loads(r['report'])) for r in reversed(rows)]

    def channel(self, binding: str) -> Channel:
        row = self.db.execute('SELECT snapshot FROM channels WHERE binding=?', (binding,)).fetchone()
        if row is None:
            raise Error('unknown channel')
        channel = Channel.from_snapshot(json.loads(row['snapshot']))
        if channel.binding != binding:
            raise Error('stored channel binding mismatch; incompatible definitions or damaged database')
        return channel

    def stats(self) -> dict[str, int]:
        return {r['state']: r['n'] for r in self.db.execute('SELECT state,COUNT(*) AS n FROM jobs GROUP BY state')}

    # oz1g-selective-v1 (foundation record clauses 1 to 3 and 5): coordinator epoch, dispatch journal, candidates and
    # one conditional transaction per settlement. Nothing below runs for a packet of oz1g-header jobs.

    def epoch(self) -> int:
        """The current coordinator epoch."""
        return self.db.execute('SELECT epoch FROM coordinator WHERE id=1').fetchone()[0]

    def take_over(self) -> int:
        """Start a new coordinator epoch and return it. Workers of an older epoch can no longer commit directly; the
        current coordinator adopts their captured replies under the clause 3 rules."""
        with self._transaction():
            self.db.execute('UPDATE coordinator SET epoch=epoch+1 WHERE id=1')
            return self.epoch()

    def _selective_packet(self, plan, rows) -> bool:
        return bool(plan.packet.job_map) and not all(rows[j.id]['profile'] == HEADER for j in plan.jobs)

    def _computation_keys(self, plan, route) -> dict:
        packet = plan.packet
        inputs = job_inputs(packet.text, packet.job_map)
        goal = json.loads(packet.text)['goal']
        return {job.id: compute_key(goal, inputs[job.id], route) for job in plan.jobs if job.id in inputs}

    def _screen_dispatch(self, plan, binding, options) -> bool:
        """Checks that must precede the lease of a packet holding a selective job; call inside the lease transaction.

        An epoch other than the current one raises Fenced (nothing is charged, no model call follows). A selective
        job pinned to another computation key is failed with a clear reason (still unresolved, attempts unchanged)
        and True is returned so the caller plans again without it; the other jobs are unaffected."""
        if not isinstance(options, dict):
            return False  # _open_dispatch rejects it and the lease transaction rolls back
        rows = {r['id']: r for r in self.db.execute(
            'SELECT id,profile,compute_key FROM jobs WHERE id IN (' + ','.join('?' for _ in plan.jobs) + ')',
            [j.id for j in plan.jobs])}
        if not self._selective_packet(plan, rows):
            return False
        epoch = options.get('epoch', self.epoch())
        if epoch != self.epoch():
            raise Fenced(f'coordinator epoch {epoch} is obsolete (current {self.epoch()}); nothing claimed')
        keys = self._computation_keys(plan, dict(options.get('route') or {}))
        refused = False
        for job in plan.jobs:
            row = rows[job.id]
            if row['profile'] == SELECTIVE and keys.get(job.id) is not None and row['compute_key'] not in (None, keys[job.id]):
                reason = ('pinned_computation_mismatch: its inputs or execution route differ from the computation this '
                          'job is pinned to; post it as a new job')
                # Failed as exhausted (unresolved): a late capture of the pinned computation may still be adopted.
                self.db.execute("UPDATE jobs SET state='failed',failure_kind='exhausted',error=?,available_at=0,"
                                "lease=NULL,owner=NULL,deadline=NULL WHERE id=?", (reason, job.id))
                self._event(job.id, 'pinned_computation_mismatch')
                refused = True
        return refused

    def _open_dispatch(self, plan, binding, lease, owner, receipt, options, max_tokens, lease_seconds) -> bool:
        """Launch intent and protective reservations, inside the lease transaction (clause 5 step 1)."""
        packet = plan.packet
        rows = {r['id']: r for r in self.db.execute(
            'SELECT id,profile,generation,compute_key FROM jobs WHERE lease=?', (lease,))}
        if not self._selective_packet(plan, rows):
            return False
        if not isinstance(options, dict) or set(options) - {'epoch', 'route', 'call_id', 'timeout', 'capture_dir'}:
            raise Error('dispatch options are epoch, route, call_id, timeout and capture_dir')
        epoch = options.get('epoch', self.epoch())
        route = dict(options.get('route') or {})
        inputs = job_inputs(packet.text, packet.job_map)
        goal = json.loads(packet.text)['goal']
        pids = {}
        for pid, (mid, _) in zip(slot_ids(packet.job_map), packet.job_map):
            pids.setdefault(mid, []).append(pid)
        members = []
        for job in plan.jobs:
            row = rows[job.id]
            key = compute_key(goal, inputs[job.id], route) if job.id in inputs else None
            if row['profile'] == SELECTIVE and key is not None:
                if row['compute_key'] is None:
                    self.db.execute('UPDATE jobs SET compute_key=? WHERE id=?', (key, job.id))
                elif row['compute_key'] != key:
                    raise Error(f'job {job.id} is pinned to another computation (its inputs or execution route '
                                'changed); post it as a new job')
            members.append({'id': job.id, 'generation': row['generation'], 'attempt': job.attempt,
                            'profile': row['profile'], 'compute_key': key, 'packet_ids': pids.get(job.id, [])})
        reservation = {'attempts': {j.id: 1 for j in plan.jobs}, 'max_input_tokens': max_tokens,
                       'submitted_tokens': list(packet.tokens), 'timeout': options.get('timeout')}
        capture = options.get('capture_dir')
        self.db.execute('''INSERT INTO dispatches(receipt,binding,lease,owner,epoch,call_id,created_at,deadline,timeout,
            reservation,reservation_state,members,job_map,host_slots,system_sha256,packet,route,capture_dir,state)
            VALUES (?,?,?,?,?,?,?,?,?,?,'held',?,?,?,?,?,?,?,'intent')''',
                        (receipt, binding, lease, owner, epoch, options.get('call_id'), self.clock(), self.clock() + lease_seconds,
                         options.get('timeout'), _dump(reservation), _dump(members), _dump(packet.job_map),
                         _dump(packet.host_slots), hashlib.sha256(packet.system.encode('utf-8')).hexdigest(),
                         packet.text, _dump(route), None if capture is None else str(capture)))
        for job in plan.jobs:
            self._event(job.id, 'dispatch_intent', receipt=receipt, epoch=epoch)
        return True

    def _dispatch_dict(self, row) -> dict:
        d = dict(row)
        for key in ('reservation', 'members', 'route', 'process', 'response'):
            if d[key] is not None:
                d[key] = json.loads(d[key])
        d['job_map'] = tuple(tuple(x) for x in json.loads(d['job_map']))
        d['host_slots'] = tuple(tuple(x) for x in json.loads(d['host_slots']))
        return d

    def dispatch(self, receipt: str) -> dict | None:
        """The journaled dispatch of a receipt (None for a header-only or host-only packet)."""
        row = self.db.execute('SELECT * FROM dispatches WHERE receipt=?', (receipt,)).fetchone()
        return None if row is None else self._dispatch_dict(row)

    def dispatches(self, *, binding: str | None = None, unsettled: bool = False) -> list[dict]:
        sql, args = 'SELECT * FROM dispatches WHERE 1=1', []
        if binding is not None:
            sql, args = sql + ' AND binding=?', [binding]
        if unsettled:
            sql += ' AND settled_at IS NULL'
        return [self._dispatch_dict(r) for r in self.db.execute(sql + ' ORDER BY created_at, receipt', args)]

    def _journal(self, receipt: str, event: str, sql: str, args) -> bool:
        with self._transaction():
            changed = self.db.execute(sql, args).rowcount == 1
            if changed:
                for member in json.loads(self.db.execute('SELECT members FROM dispatches WHERE receipt=?',
                                                         (receipt,)).fetchone()[0]):
                    self._event(member['id'], event, receipt=receipt)
        return changed

    def dispatch_prepared(self, receipt: str, request_sha256: str) -> bool:
        """Bind the exact adapter request bytes to the dispatch before the call starts."""
        with self._transaction():
            return self.db.execute('UPDATE dispatches SET request_sha256=? WHERE receipt=? AND request_sha256 IS NULL',
                                   (request_sha256, receipt)).rowcount == 1

    def dispatch_launched(self, receipt: str, process: dict | None) -> bool:
        """Confirmed launch with the process identity (PID and creation time) when available (clause 5 step 2)."""
        return self._journal(receipt, 'dispatch_launched',
                             "UPDATE dispatches SET state='launched',process=? WHERE receipt=? AND state='intent'",
                             (None if process is None else _dump(process), receipt))

    def dispatch_captured(self, receipt: str, *, response: dict | None = None, error: str | None = None,
                          executed: bool = True) -> bool:
        """Record the capture before interpretation (clause 5 step 3): captured (a response envelope), failed_call
        (the call ran but left no envelope; its usage is unknown) or not_launched (confirmed non-execution). The
        protective reservation is released only here. The first capture wins; a later one changes nothing."""
        text = None
        if response is not None:
            try:
                text = json.dumps(response, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            except (TypeError, ValueError):
                error = error or 'response_not_serializable'
        state = 'captured' if text is not None else 'failed_call' if executed else 'not_launched'
        return self._journal(receipt, 'dispatch_' + state, '''UPDATE dispatches SET state=?,response=?,error=?,
            captured_at=?,reservation_state='released' WHERE receipt=? AND state IN ('intent','launched','uncertain')''',
                             (state, text, error, self.clock(), receipt))

    def dispatch_uncertain(self, receipt: str) -> bool:
        """No completed capture and no live process: execution may have happened and its usage is unknown. The
        reservation stays held; a later valid capture may still resolve it."""
        return self._journal(receipt, 'dispatch_uncertain', '''UPDATE dispatches SET state='uncertain'
            WHERE receipt=? AND state IN ('intent','launched')''', (receipt,))

    def in_flight(self, receipt: str) -> bool:
        """True until the dispatch's original lease deadline: its call may still be running, even when a job of it
        was meanwhile adopted or cancelled."""
        row = self.db.execute('SELECT deadline FROM dispatches WHERE receipt=?', (receipt,)).fetchone()
        return row is not None and row['deadline'] > self.clock()

    def contracts(self, ids: Iterable[str]) -> dict[str, tuple[str, tuple]]:
        """{job: (pinned profile, pinned checks)}."""
        out = {}
        for mid in ids:
            row = self.db.execute('SELECT profile,checks FROM jobs WHERE id=?', (mid,)).fetchone()
            if row is not None:
                out[mid] = (row['profile'], tuple(json.loads(row['checks'])))
        return out

    def candidates(self, *, job: str | None = None, receipt: str | None = None,
                   status: str | None = None) -> list[dict]:
        """Stored candidates, oldest first: value, inputs, pinned checks, verdicts, status and reason. Candidates are
        history: only an accepted one is the job's result."""
        sql, args = 'SELECT * FROM candidates WHERE 1=1', []
        for column, value in (('job', job), ('receipt', receipt), ('status', status)):
            if value is not None:
                sql += f' AND {column}=?'
                args.append(value)
        out = []
        for row in self.db.execute(sql + ' ORDER BY seq', args):
            d = dict(row)
            for key in ('inputs', 'checks', 'verdicts'):
                d[key] = json.loads(d[key])
            d['suspect'] = bool(d['suspect'])
            out.append(d)
        return out

    def settle_dispatch(self, receipt: str, decisions: dict, *, epoch: int, retry_delay: float = 0,
                        report: dict | None = None, recheck: bool = False) -> dict:
        """Apply per-job decisions for one journaled dispatch in one conditional transaction (clauses 2 and 3).

        decisions maps a member job to {kind, ...}: header (shipped outcome: status, text, value), retry (no candidate
        survives), failure (a valid model-failure record), or a candidate kind accept, reject, await or quarantine
        (text, value, verdicts, inputs, reason, suspect; seq for a stored candidate when recheck is true).

        Nothing commits unless epoch is the current coordinator epoch. A job whose lease is still this dispatch's
        (same epoch, unexpired) follows the in-lease rules; any other job follows the adoption rules: a success commits
        only into a live unresolved job of the same generation and computation, an accepted result is never
        overwritten, a cancelled or model-failed job is never revived, and a late failure decides a job only when no
        execution is in progress and no attempt remains. Settling a dispatch twice changes nothing."""
        if type(retry_delay) not in {int, float} or not 0 <= retry_delay <= 86400:
            raise Error('invalid retry delay')
        report_text = _dump(report or {})
        if len(report_text.encode('utf-8')) > 65536:
            raise Error('run report too large')
        with self._transaction():
            d = self.dispatch(receipt)
            if d is None:
                raise Error('unknown dispatch')
            if epoch != self.epoch():
                return {'status': 'fenced', 'jobs': {}}
            if d['settled_at'] is not None and not recheck:
                return {'status': 'already_settled', 'jobs': {}}
            self._recover(d['binding'], 'work')
            now = self.clock()
            jobs = {}
            for member in d['members']:
                decision = decisions.get(member['id'])
                if decision is None:
                    continue
                row = self.db.execute('SELECT * FROM jobs WHERE id=?', (member['id'],)).fetchone()
                inlease = (not recheck and row['state'] == 'leased' and row['lease'] == d['lease']
                           and row['deadline'] > now and d['epoch'] == epoch)
                jobs[member['id']] = self._apply(row, member, decision, inlease=inlease, recheck=recheck,
                                                 receipt=receipt, retry_delay=retry_delay, now=now)
            if not recheck:
                self.db.execute('UPDATE dispatches SET settled_at=?,outcome=? WHERE receipt=?',
                                (now, _dump(jobs), receipt))
                self.db.execute('INSERT INTO runs(binding,at,ids,report) VALUES (?,?,?,?)',
                                (d['binding'], now, _dump([m['id'] for m in d['members']]), report_text))
        return {'status': 'settled', 'jobs': jobs}

    def _apply(self, row, member, decision, *, inlease, recheck, receipt, retry_delay, now) -> str:
        mid, kind = row['id'], decision['kind']

        def update(**fields):
            self.db.execute('UPDATE jobs SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?',
                            (*fields.values(), mid))

        free = dict(lease=None, owner=None, deadline=None)

        def recover(error):
            # Bounded recovery of the current attempt: back to pending while attempts remain.
            if row['attempts'] < row['max_attempts']:
                update(state='pending', error=error, available_at=now + retry_delay, failure_kind=None, **free)
                return 'pending'
            update(state='failed', error=error, available_at=0, failure_kind='exhausted', **free)
            return 'failed'

        live = (row['state'] in ('pending', 'leased', 'checking', 'quarantined')
                or (row['state'] == 'failed' and row['failure_kind'] == 'exhausted'))
        same = row['generation'] == member['generation'] and row['compute_key'] == member['compute_key']
        if kind == 'header':
            # A job pinned to oz1g-header inside a mixed packet: the shipped outcome, current attempt only.
            if not inlease:
                self._event(mid, 'late_reply_ignored', receipt=receipt)
                return 'stale'
            status = decision['status']
            if status == 'ok':
                update(state='done', result=decision['text'], result_json=decision.get('value'), error='',
                       available_at=0, failure_kind=None, **free)
                state = 'done'
            elif status == 'retry':
                state = recover(decision['text'])
            else:
                update(state='failed', error=decision['text'], available_at=0, failure_kind='model_failure', **free)
                state = 'failed'
            self._event(mid, state, outcome=status, receipt=receipt)
            return state
        if kind == 'retry':
            if inlease:
                state = recover(decision['reason'])
                self._event(mid, state, outcome='retry', receipt=receipt)
                return state
            self._event(mid, 'late_reply_ignored', receipt=receipt)
            return 'stale'
        if kind == 'failure':
            if inlease:
                update(state='failed', error=decision['text'], available_at=0, failure_kind='model_failure', **free)
                self._event(mid, 'failed', outcome='failed', receipt=receipt)
                return 'failed'
            if row['state'] == 'failed' and row['failure_kind'] == 'exhausted' and same:
                update(error=decision['text'], failure_kind='model_failure')
                self._event(mid, 'late_failure_recorded', receipt=receipt)
                return 'failed'
            self._event(mid, 'late_failure_ignored', receipt=receipt)
            return 'ignored'
        if kind not in ('accept', 'reject', 'await', 'quarantine'):
            raise Error('unknown decision kind')
        seq, reason = decision.get('seq'), decision.get('reason')
        if seq is not None and self.db.execute("SELECT 1 FROM candidates WHERE seq=? AND job=? AND receipt=? "
                                               "AND status IN ('awaiting','quarantined')",
                                               (seq, mid, receipt)).fetchone() is None:
            # Another coordinator already decided this candidate: nothing changes (no overwrite, no re-accept).
            self._event(mid, 'late_reply_ignored', receipt=receipt)
            return 'stale'
        status, key, state = {'accept': 'accepted', 'reject': 'rejected', 'await': 'awaiting',
                              'quarantine': 'quarantined'}[kind], None, row['state']
        current = inlease or (recheck and row['state'] == 'checking' and self.db.execute(
            "SELECT 1 FROM candidates WHERE job=? AND status='awaiting' AND seq!=?", (mid, seq)).fetchone() is None)
        if not (live and same):
            status, state = 'superseded', 'stale'
            self._event(mid, 'late_reply_superseded', receipt=receipt)
        elif kind == 'accept':
            key = accept_key(member['compute_key'], decision['value'], row['profile'], json.loads(row['checks']),
                             decision['verdicts'])
            update(state='done', result=decision['text'], result_json=decision['value'], error='', available_at=0,
                   failure_kind=None, **free)
            state = 'done'
            self._event(mid, 'done' if inlease else 'released' if recheck else 'adopted', outcome='ok',
                        receipt=receipt)
        elif kind == 'reject':
            if current:
                state = recover('candidate rejected: ' + reason)
        elif kind == 'await':
            if inlease or row['state'] in ('pending', 'quarantined', 'failed'):
                # A verifier outage holds the candidate; it never spends another model attempt.
                update(state='checking', error=reason, available_at=0, failure_kind=None, **free)
                state = 'checking'
        elif current:
            if row['attempts'] < row['max_attempts']:
                # Quarantined with allowance left: back to bounded recovery without caller action.
                update(state='pending', error='quarantined: ' + reason, available_at=now + retry_delay,
                       failure_kind=None, **free)
                state = 'pending'
            else:
                update(state='quarantined', error=reason, available_at=0, failure_kind=None, **free)
                state = 'quarantined'
        elif row['state'] == 'failed':
            update(state='quarantined', error=reason, failure_kind=None)
            state = 'quarantined'
        if status != 'superseded':
            self._event(mid, 'candidate_' + status, receipt=receipt)
        verdicts = _dump(decision.get('verdicts', []))
        if seq is None:
            self.db.execute('''INSERT INTO candidates(job,receipt,generation,compute_key,value,stored,inputs,checks,
                verdicts,status,reason,suspect,at,accept_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (mid, receipt, member['generation'], member['compute_key'], decision['value'],
                             decision['text'], _dump([dict(s) for s in decision['inputs'].slots]), row['checks'],
                             verdicts, status, reason, int(bool(decision.get('suspect'))), now, key))
        else:
            changed = self.db.execute('''UPDATE candidates SET status=?,reason=?,verdicts=?,suspect=MAX(suspect,?),at=?,
                accept_key=? WHERE seq=? AND status IN ('awaiting','quarantined')''',
                                      (status, reason, verdicts, int(bool(decision.get('suspect'))), now, key,
                                       seq)).rowcount
            if changed != 1:
                raise Error('candidate changed during settlement; nothing applied')
        return state

    def adopt_memo(self, mid: str, *, entry: str, compute_key: str, value: str, text: str, verdicts, inputs,
                   epoch: int) -> str:
        """Accept a memo entry for one unresolved selective job in one conditional transaction (clause 4): the job's
        pinned computation key must equal compute_key (an unpinned job is pinned to it here), verdicts are the job's
        own pinned checks rerun on the stored value against this job's inputs, and the acceptance association is a new
        candidate row with receipt memo:<entry>. A job that is settled, leased by a live dispatch, cancelled or failed
        by the model is never touched. Returns done, or the reason nothing changed. No model call, no attempt."""
        if any(v['verdict'] != 'pass' for v in verdicts) or not any(v['job_bound'] for v in verdicts):
            raise Error('a memo hit needs every pinned check to pass, one of them job-bound')
        with self._transaction():
            if epoch != self.epoch():
                return 'fenced'
            row = self.db.execute('SELECT * FROM jobs WHERE id=?', (mid,)).fetchone()
            if row is None or row['profile'] != SELECTIVE:
                return 'not_selective'
            live = (row['state'] in ('pending', 'checking', 'quarantined')
                    or (row['state'] == 'failed' and row['failure_kind'] == 'exhausted')
                    or (row['state'] == 'leased' and row['deadline'] <= self.clock()))
            if not live:
                return 'not_live'
            if row['compute_key'] not in (None, compute_key):
                return 'pinned_computation_mismatch'
            key = accept_key(compute_key, value, row['profile'], json.loads(row['checks']), verdicts)
            self.db.execute("""UPDATE jobs SET state='done',result=?,result_json=?,error='',available_at=0,
                failure_kind=NULL,lease=NULL,owner=NULL,deadline=NULL,compute_key=? WHERE id=?""",
                            (text, value, compute_key, mid))
            self.db.execute("""INSERT INTO candidates(job,receipt,generation,compute_key,value,stored,inputs,checks,
                verdicts,status,reason,suspect,at,accept_key) VALUES (?,?,?,?,?,?,?,?,?,'accepted',?,0,?,?)""",
                            (mid, 'memo:' + entry, row['generation'], compute_key, value, text,
                             _dump([dict(s) for s in inputs.slots]), row['checks'], _dump(list(verdicts)),
                             'memo hit ' + entry, self.clock(), key))
            self._event(mid, 'memo_hit', entry=entry, compute_key=compute_key)
        return 'done'

    def cancel(self, mid: str, reason: str = 'cancelled') -> None:
        """Cancel an unresolved job: it fails as cancelled, and no late reply can revive it."""
        if not isinstance(reason, str) or not reason.strip() or len(reason.encode('utf-8')) > 4096:
            raise Error('cancel requires a bounded reason')
        with self._transaction():
            row = self.db.execute('SELECT state,failure_kind,lease,deadline FROM jobs WHERE id=?', (mid,)).fetchone()
            if row is None:
                raise Error('unknown message ID')
            if row['state'] == 'done' or (row['state'] == 'failed' and row['failure_kind'] != 'exhausted'):
                raise Error('only an unresolved job can be cancelled')
            if (row['state'] == 'leased' and row['deadline'] > self.clock()
                    and self.db.execute('SELECT 1 FROM dispatches WHERE lease=?', (row['lease'],)).fetchone() is None):
                # A header delivery settles all its jobs together; releasing one would make settle() refuse the
                # whole delivery. A journaled dispatch settles per job and handles a cancelled member.
                raise Error('job is leased in an in-flight delivery; cancel it after the delivery settles or its '
                            'lease expires')
            self.db.execute('''UPDATE jobs SET state='failed',failure_kind='cancelled',error=?,lease=NULL,owner=NULL,
                deadline=NULL WHERE id=?''', (reason, mid))
            self._event(mid, 'cancelled')
