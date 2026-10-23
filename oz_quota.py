"""Per-user quota-group reservations (foundation record clause 7): one in-flight call per quota group.

A slot is reserved in a BEGIN IMMEDIATE transaction before a call can launch and released transactionally after its
dispatch is captured. The holder records its run directory, the receipt it is about to use and its coordinator process
identity (PID and creation time). A held slot is reclaimed only under the clause 5 reconciliation rules: the holder's
dispatch is captured, failed or confirmed not launched, or no dispatch was ever journaled for that receipt and the
coordinator that would have launched it is gone. An uncertain or still-launched dispatch keeps its slot: retained
execution uncertainty never disappears because scheduler ownership changes. Rate-limit events and supplied reset
times go into the same database. Standard library only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from oz import Error
from oz_runner import process_alive, process_identity

SETTLED = ('captured', 'failed_call', 'not_launched')


def default_path() -> Path:
    """The per-user database: AKOR_QUOTA_DB, else ~/.akor/quota.sqlite."""
    return Path(os.environ.get('AKOR_QUOTA_DB') or Path.home() / '.akor' / 'quota.sqlite')


class Quota:
    def __init__(self, path=None, *, clock=time.time):
        self.path = Path(path) if path is not None else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('''CREATE TABLE IF NOT EXISTS slots(grp TEXT PRIMARY KEY, token TEXT NOT NULL,
                holder TEXT NOT NULL, acquired_at REAL NOT NULL)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, grp TEXT NOT NULL,
                event TEXT NOT NULL, details TEXT NOT NULL, reset_at REAL, at REAL NOT NULL)''')
        except BaseException:
            self.db.rollback()
            raise
        self.db.commit()

    def close(self):
        self.db.close()

    def _event(self, group, event, details, reset_at=None):
        self.db.execute('INSERT INTO events(grp,event,details,reset_at,at) VALUES (?,?,?,?,?)',
                        (group, event, json.dumps(details, sort_keys=True), reset_at, self.clock()))

    @staticmethod
    def _holder_state(holder: dict) -> str:
        """reclaimable, or why the slot stays held."""
        inbox = Path(holder.get('run_dir', '')) / 'inbox.sqlite'
        row = None
        if inbox.exists():
            db = sqlite3.connect(str(inbox), timeout=10)
            try:
                row = db.execute('SELECT state FROM dispatches WHERE receipt=?', (holder.get('receipt'),)).fetchone()
            except sqlite3.Error:
                row = None
            finally:
                db.close()
        if row is not None:
            return 'reclaimable' if row[0] in SETTLED else 'held_' + row[0]
        captures = Path(holder.get('run_dir', '')) / 'captures'
        if ((captures / f"{holder.get('receipt')}.request.json").exists()
                and not (captures / f"{holder.get('receipt')}.done").exists()):
            return 'held_uncaptured'  # a runner may still be executing this request
        alive = process_alive(holder.get('coordinator'))
        return 'reclaimable' if alive is False else 'held_coordinator_alive' if alive else 'held_unknown_coordinator'

    def acquire(self, group: str, *, run_dir, receipt: str) -> dict:
        """{status: acquired, token} or {status: held, reason, holder}. Never waits; the caller decides."""
        holder = {'run_dir': str(Path(run_dir).resolve()), 'receipt': receipt,
                  'coordinator': process_identity(os.getpid())}
        token = uuid.uuid4().hex
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row = self.db.execute('SELECT * FROM slots WHERE grp=?', (group,)).fetchone()
            if row is not None:
                current = json.loads(row['holder'])
                state = self._holder_state(current)
                if state != 'reclaimable':
                    self._event(group, 'contention', {'holder': current, 'state': state})
                    self.db.commit()
                    return {'status': 'held', 'reason': state, 'holder': current}
                self._event(group, 'reclaimed', {'holder': current})
            self.db.execute('INSERT OR REPLACE INTO slots VALUES (?,?,?,?)', (group, token, json.dumps(holder),
                                                                              self.clock()))
            self._event(group, 'acquired', holder)
        except BaseException:
            self.db.rollback()
            raise
        self.db.commit()
        return {'status': 'acquired', 'token': token, 'group': group}

    def release(self, group: str, token: str) -> bool:
        self.db.execute('BEGIN IMMEDIATE')
        try:
            changed = self.db.execute('DELETE FROM slots WHERE grp=? AND token=?', (group, token)).rowcount == 1
            if changed:
                self._event(group, 'released', {'token': token})
        except BaseException:
            self.db.rollback()
            raise
        self.db.commit()
        return changed

    def rate_limited(self, group: str, details: dict, reset_at: float | None = None) -> None:
        """Record a rate-limit event and a supplied reset time (observed, never inferred)."""
        self.db.execute('BEGIN IMMEDIATE')
        self._event(group, 'rate_limited', details, reset_at)
        self.db.commit()

    def events(self, group: str | None = None) -> list[dict]:
        sql, args = 'SELECT * FROM events', ()
        if group is not None:
            sql, args = sql + ' WHERE grp=?', (group,)
        return [dict(r, details=json.loads(r['details'])) for r in self.db.execute(sql + ' ORDER BY seq', args)]

    def holder(self, group: str) -> dict | None:
        row = self.db.execute('SELECT holder FROM slots WHERE grp=?', (group,)).fetchone()
        return None if row is None else json.loads(row['holder'])


def check_group(group: object) -> str:
    if not isinstance(group, str) or not group:
        raise Error('quota group must be a nonempty string')
    return group
