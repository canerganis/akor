"""Memo store: reusable accepted candidates, revocation and recorded reuse decisions (foundation record clause 4).

One SQLite file per workspace. An entry is an accepted candidate of a memo-eligible operation, keyed by its reuse
namespace and computation key (K_compute, which includes the pinned execution route), with its value bytes, the route,
the checks it was accepted under and its provenance (run directory, receipt, candidate row). An entry is never a
current acceptance by itself: a consumer turns it into one only after integrity, provenance, revocation and its own
pinned checks pass (oz_do). Every lookup outcome is recorded as a decision. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import time

from oz import Error
from oz_batch import J

SCHEMA = '''
CREATE TABLE IF NOT EXISTS entries(
    id INTEGER PRIMARY KEY, namespace TEXT NOT NULL, compute_key TEXT NOT NULL, value TEXT NOT NULL,
    value_sha256 TEXT NOT NULL, stored TEXT NOT NULL, route TEXT NOT NULL, checks TEXT NOT NULL,
    verdicts TEXT NOT NULL, provenance TEXT NOT NULL, at REAL NOT NULL,
    UNIQUE(namespace, compute_key, value_sha256, provenance));
CREATE INDEX IF NOT EXISTS entry_keys ON entries(namespace, compute_key, id);
CREATE TABLE IF NOT EXISTS revocations(entry INTEGER PRIMARY KEY REFERENCES entries(id), reason TEXT NOT NULL,
    at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS decisions(
    seq INTEGER PRIMARY KEY, namespace TEXT NOT NULL, compute_key TEXT NOT NULL, consumer TEXT NOT NULL,
    decision TEXT NOT NULL, entry INTEGER, reason TEXT, at REAL NOT NULL)
'''


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class MemoStore:
    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            for statement in SCHEMA.split(';'):
                if statement.strip():
                    self.db.execute(statement)
        except BaseException:
            self.db.rollback()
            raise
        self.db.commit()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def publish(self, namespace: str, compute_key: str, *, value: str, stored: str, route: dict, checks, verdicts,
                provenance: dict) -> int:
        """Store an accepted candidate once; returns its entry id (an identical entry is not duplicated)."""
        if not isinstance(namespace, str) or not namespace or not isinstance(compute_key, str):
            raise Error('memo entries need a namespace and a computation key')
        args = (namespace, compute_key, value, sha256(value), stored, J(route), J(list(checks)), J(list(verdicts)),
                J(provenance), self.clock())
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('''INSERT OR IGNORE INTO entries(namespace,compute_key,value,value_sha256,stored,route,checks,
                verdicts,provenance,at) VALUES (?,?,?,?,?,?,?,?,?,?)''', args)
            row = self.db.execute('SELECT id FROM entries WHERE namespace=? AND compute_key=? AND value_sha256=? '
                                  'AND provenance=?', (namespace, compute_key, args[3], args[8])).fetchone()
        except BaseException:
            self.db.rollback()
            raise
        self.db.commit()
        return row['id']

    def revoke(self, entry: int, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise Error('revocation needs a reason')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if self.db.execute('SELECT 1 FROM entries WHERE id=?', (entry,)).fetchone() is None:
                raise Error('unknown memo entry')
            self.db.execute('INSERT OR IGNORE INTO revocations VALUES (?,?,?)', (entry, reason, self.clock()))
        except BaseException:
            self.db.rollback()
            raise
        self.db.commit()

    def entries(self, namespace: str | None = None, compute_key: str | None = None) -> list[dict]:
        """Entries, newest first, with their revocation (None when not revoked)."""
        sql = ('SELECT e.*, r.reason AS revoked FROM entries e LEFT JOIN revocations r ON r.entry=e.id WHERE 1=1')
        args = []
        for column, value in (('namespace', namespace), ('compute_key', compute_key)):
            if value is not None:
                sql += f' AND e.{column}=?'
                args.append(value)
        out = []
        for row in self.db.execute(sql + ' ORDER BY e.id DESC', args):
            d = dict(row)
            for key in ('route', 'checks', 'verdicts', 'provenance'):
                d[key] = json.loads(d[key])
            out.append(d)
        return out

    def record(self, namespace: str, compute_key: str, consumer: str, decision: str, *, entry: int | None = None,
               reason: str | None = None) -> None:
        self.db.execute('INSERT INTO decisions(namespace,compute_key,consumer,decision,entry,reason,at) '
                        'VALUES (?,?,?,?,?,?,?)', (namespace, compute_key, consumer, decision, entry, reason,
                                                   self.clock()))

    def decisions(self) -> list[dict]:
        return [dict(r) for r in self.db.execute('SELECT * FROM decisions ORDER BY seq')]
