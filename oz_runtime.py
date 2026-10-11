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

from oz import Channel, Error, _dump
from oz_batch import Batch, render, valid_id


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


class Inbox:
    def __init__(self, path: str | Path = ':memory:', *, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in {0, 1}:
            self.db.close()
            raise Error('unsupported inbox schema version')
        self.db.executescript('''
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
            PRAGMA user_version=1;
        ''')

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
             after: Iterable[str] = (), max_attempts: int = 3) -> bool:
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
        return True

    def claim(self, channel: Channel, *, owner: str, kind: str = 'work', limit: int = 8,
              lease_seconds: float = 60) -> Delivery | None:
        if not valid_id(owner) or kind not in {'work', 'host'} or type(limit) is not int or not 1 <= limit <= 64:
            raise Error('invalid delivery options')
        if type(lease_seconds) not in {int, float} or not 0 < lease_seconds <= 86400:
            raise Error('invalid lease duration')
        now = self.clock()
        token = uuid.uuid4().hex
        with self._transaction():
            self.db.execute('''UPDATE jobs SET
                state=CASE WHEN attempts>=max_attempts THEN 'failed' ELSE 'pending' END,
                lease=NULL,owner=NULL,deadline=NULL,error='delivery lease expired'
                WHERE binding=? AND kind=? AND state='leased' AND deadline<=?''', (channel.binding, kind, now))
            rows = self.db.execute('''SELECT j.* FROM jobs j
                WHERE j.binding=? AND j.kind=? AND j.state='pending'
                AND NOT EXISTS (SELECT 1 FROM dependencies d JOIN jobs p ON p.id=d.prior
                                WHERE d.job=j.id AND p.state!='done')
                ORDER BY j.seq LIMIT ?''', (channel.binding, kind, limit)).fetchall()
            if not rows:
                return None
            self.db.executemany('''UPDATE jobs SET state='leased',attempts=attempts+1,
                lease=?,owner=?,deadline=? WHERE id=?''',
                                [(token, owner, now + lease_seconds, r['id']) for r in rows])
        return Delivery(channel.binding, token, owner, kind,
                        tuple(Job(r['id'], r['wire'], r['attempts'] + 1) for r in rows))

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
            self.db.executemany('''UPDATE jobs SET state='done',result=?,lease=NULL,owner=NULL,
                deadline=NULL,error='' WHERE id=?''', [(results[j.id], j.id) for j in delivery.jobs])

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

    def renew(self, delivery: Delivery, *, lease_seconds: float = 60) -> None:
        if type(lease_seconds) not in {int, float} or not 0 < lease_seconds <= 86400:
            raise Error('invalid lease duration')
        with self._transaction():
            self._check(delivery)
            self.db.execute('UPDATE jobs SET deadline=? WHERE lease=?', (self.clock() + lease_seconds, delivery.lease))

    def inspect(self, mid: str) -> dict:
        row = self.db.execute('SELECT id,binding,wire,kind,state,attempts,result,error FROM jobs WHERE id=?', (mid,)).fetchone()
        if row is None:
            raise Error('unknown message ID')
        result = dict(row)
        result['waiting_for'] = [dict(r) for r in self.db.execute('''
            SELECT p.id,p.state FROM dependencies d JOIN jobs p ON p.id=d.prior
            WHERE d.job=? AND p.state!='done' ORDER BY p.seq''', (mid,))]
        return result

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
