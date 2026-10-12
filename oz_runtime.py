"""SQLite-backed OZ inbox with dependency gating and renewable delivery attempts.

Exactly-once insertion, at-least-once delivery. External tool effects must use
their own idempotency keys. This module never executes tools or contacts models.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import time
from typing import Callable, Iterable
import uuid

from oz import Channel, Error, TokenMeter, _dump
from oz_batch import PREVIEW_RECEIPT, Batch, BudgetError, render, valid_id


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
            '''
            for statement in schema.split(';'):
                if statement.strip():
                    self.db.execute(statement)
            columns = {r['name'] for r in self.db.execute('PRAGMA table_info(jobs)')}
            if 'available_at' not in columns:
                self.db.execute('ALTER TABLE jobs ADD COLUMN available_at REAL NOT NULL DEFAULT 0')
            if 'result_json' not in columns:
                self.db.execute('ALTER TABLE jobs ADD COLUMN result_json TEXT')
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
             after: Iterable[str] = (), max_attempts: int = 2) -> bool:
        """Return False for an identical retry; reject ID reuse with new meaning."""
        atoms = channel.accept(wire, binding=binding)
        if not valid_id(mid) or type(max_attempts) is not int or not 1 <= max_attempts <= 100:
            raise Error('invalid message ID or retry limit')
        after = tuple(after)
        if len(after) > 64 or any(not valid_id(i) or i == mid for i in after) or len(set(after)) != len(after):
            raise Error('invalid dependencies')
        identity = _dump([binding, [vars(a) for a in atoms], sorted(after), max_attempts])
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
            self.db.execute('''INSERT INTO jobs(id,binding,wire,identity,kind,max_attempts)
                               VALUES (?,?,?,?,?,?)''', (mid, binding, wire, identity, kind, max_attempts))
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
                error='delivery lease expired' WHERE id=?''', (state, row['id']))
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

        Only direct predecessors that are done. The record is the accepted JSON value (result_json);
        a job settled without one yields its stored result text as a string. Unverified agent data."""
        links = []
        for mid in ids:
            rows = self.db.execute('''SELECT p.id,p.result,p.result_json FROM dependencies d JOIN jobs p ON p.id=d.prior
                WHERE d.job=? AND p.state='done' ORDER BY d.rowid''', (mid,)).fetchall()
            links.extend((mid, r['id'], r['result'] if r['result_json'] is None else json.loads(r['result_json']))
                         for r in rows)
        return links

    def claim_prepared(self, channel: Channel, *, owner: str, counters, receipt: str, limit: int = 64,
                       max_tokens: int | None = None, max_bytes: int = 262144,
                       lease_seconds: float = 60, context_policy: str = 'needed') -> tuple[Delivery, Batch] | None:
        """Measure outside the write lock, then atomically reserve the selected jobs.

        A budget failure consumes no attempts. Concurrent changes trigger a fresh
        plan, at most four times; only reserved jobs receive a lease/attempt.
        """
        if not valid_id(owner) or type(lease_seconds) not in {int, float} or not 0 < lease_seconds <= 86400:
            raise Error('invalid delivery options')
        if receipt == PREVIEW_RECEIPT:
            # A real call needs a fresh receipt; the zero receipt is for previews only.
            raise Error('claim requires a fresh receipt, not the preview receipt')
        counters = tuple(counters)
        for _ in range(4):
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
                    continue
                self._lease(plan.jobs, token, owner, lease_seconds)
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
                error=?,lease=NULL,owner=NULL,deadline=NULL WHERE lease=?''', (permanent, reason, delivery.lease))
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
                    lease=NULL,owner=NULL,deadline=NULL WHERE id=?''',
                                (state, outcome.text if state == 'done' else None,
                                 outcome.value if state == 'done' else None,
                                 '' if state == 'done' else outcome.text,
                                 self.clock() + retry_delay if state == 'pending' else 0, row['id']))
                self._event(row['id'], state, outcome=outcome.status)
            self.db.execute('INSERT INTO runs(binding,at,ids,report) VALUES (?,?,?,?)',
                            (delivery.binding, self.clock(), _dump([j.id for j in delivery.jobs]), report_text))

    def requeue(self, mid: str, *, extra_attempts: int = 1):
        if type(extra_attempts) is not int or not 1 <= extra_attempts <= 100:
            raise Error('extra_attempts must be 1..100')
        with self._transaction():
            row = self.db.execute('SELECT state,attempts,max_attempts FROM jobs WHERE id=?', (mid,)).fetchone()
            if row is None or row['state'] != 'failed':
                raise Error('only a failed job can be requeued; completed jobs need a new ID')
            self.db.execute('''UPDATE jobs SET state='pending',available_at=0,error='',
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
