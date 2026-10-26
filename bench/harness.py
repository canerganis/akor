"""Shared measurement harness for live benches (2026-10-27).

One place for the rules every bench review kept re-finding:
  usage    a call whose usage is missing, malformed or negative has usage None, never zero; a run with such a call
           is inconclusive for tokens. Missing reasoning counters give thinking_tokens None, not zero.
  model    every model in modelUsage must be the pinned model; subagents are forced onto it
           (CLAUDE_CODE_SUBAGENT_MODEL plus CLAUDE_CODE_SUBAGENT_MODEL_FORCE). Any other model makes the call a failure
           with no usable reply (its tokens still count). This is a pure-model cell rule: housekeeping on another model
           would also fail the call, which is the intended conservative reading.
  failure  a timeout, an unreadable stream, a non-zero exit, is_error or any exception while calling is a recorded
           failure with no reply, never a lost attempt.
  ledger   launches and tokens are capped across threads and processes sharing one SQLite file. Each launch is a
           durable reservation; it reserves `reserve` tokens until settled with real usage. A reservation left
           unsettled longer than `stale_after` seconds (its process died) counts as a call without usage, and any call
           without usage stops all later launches. The token cap is soft: the CLI has no per-call token ceiling, so
           every call in flight can exceed its reserve; the overshoot is bounded by the calls outstanding at once (one
           call for sequential runs) and is reported in state(), not hidden.

    c = call(system, prompt, model='claude-sonnet-5-5', kind='live', fixture=lambda: '...')
    c['text'], c['usage'], c['failure'], c['spawns'], c['seconds']
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
import uuid

MODEL_IDS = {'sonnet': 'claude-sonnet-5-5', 'opus': 'claude-opus-5-5', 'haiku': 'claude-haiku-5-5',
             'fable': 'claude-fable-5-1'}
USAGE_KEYS = ('inputTokens', 'cacheReadInputTokens', 'cacheCreationInputTokens', 'outputTokens')


def _count(v) -> bool:
    return type(v) is int and v >= 0


def usage_of(model_usage) -> dict | None:
    """Totals over every model in modelUsage, or None when any counter is missing, not an int or negative."""
    if not isinstance(model_usage, dict) or not model_usage:
        return None
    if any(not isinstance(e, dict) or not _count(e.get(k)) for e in model_usage.values() for k in USAGE_KEYS):
        return None
    s = {k: sum(e[k] for e in model_usage.values()) for k in USAGE_KEYS}
    thinking = [e.get('thinkingTokens') for e in model_usage.values()]
    return {'input_tokens': s['inputTokens'] + s['cacheReadInputTokens'] + s['cacheCreationInputTokens'],
            'uncached_input_tokens': s['inputTokens'], 'cached_input_tokens': s['cacheReadInputTokens'],
            'cache_write_tokens': s['cacheCreationInputTokens'], 'output_tokens': s['outputTokens'],
            'thinking_tokens': sum(thinking) if all(_count(t) for t in thinking) else None}


def tokens(usage) -> int | None:
    return None if usage is None else usage['input_tokens'] + usage['output_tokens']


def _read_stream(stdout: str):
    """(final result event or None, unique top-level Agent/Task tool calls) from stream-json output. Events are
    split on LF only: U+2028 and friends may appear inside JSON strings."""
    final, spawned = None, set()
    for line in stdout.split('\n'):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get('type') == 'assistant' and not ev.get('parent_tool_use_id'):
            content = (ev.get('message') or {}).get('content') if isinstance(ev.get('message'), dict) else None
            for b in content if isinstance(content, list) else []:
                if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') in ('Agent', 'Task'):
                    spawned.add(b.get('id') or f'anon-{len(spawned)}')
        if ev.get('type') == 'result':
            final = ev
    return final, len(spawned)


def _text(out) -> str:
    if out is None:
        return ''
    return out.decode('utf-8', 'replace') if isinstance(out, bytes) else out


def call(system: str, prompt: str, *, model: str, kind: str = 'fixture', fixture=None, tools: str = '',
         effort: str | None = None, timeout: float = 900, cwd=None) -> dict:
    """One claude -p call with the AKOR route's flags. Returns text, usage, failure, models, spawns, turns, api_ms,
    started, ended, seconds, envelope and raw (stdout tail kept when there is no result event). text is '' whenever
    failure is set. Never raises for a live call; a bad `kind` is a programming error and raises."""
    if kind not in ('fixture', 'live'):
        raise ValueError(f'kind must be fixture or live, not {kind!r}')
    started = time.time()
    envelope, failure, spawns, raw = None, None, 0, ''
    if kind == 'fixture':
        text = fixture() if fixture else ''
        envelope = {'type': 'result', 'result': text, 'is_error': False, 'num_turns': 1, 'modelUsage': {model: {
            'inputTokens': (len(system) + len(prompt)) // 4, 'cacheReadInputTokens': 0,
            'cacheCreationInputTokens': 0, 'outputTokens': len(text) // 4, 'thinkingTokens': 0}}}
    else:
        cmd = [shutil.which('claude') or 'claude', '-p', '--model', model, '--system-prompt', system, '--tools', tools,
               '--setting-sources', '', '--strict-mcp-config', '--no-session-persistence',
               '--output-format', 'stream-json', '--verbose'] + (['--effort', effort] if effort else [])
        env = dict(os.environ, CLAUDE_CODE_SUBAGENT_MODEL=model, CLAUDE_CODE_SUBAGENT_MODEL_FORCE='1')
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8',
                                  errors='replace', cwd=cwd, env=env, timeout=timeout)
            envelope, spawns = _read_stream(proc.stdout)
            if envelope is None:
                failure, raw = f'no result event (exit {proc.returncode})', (proc.stdout + proc.stderr)[-4000:]
            elif proc.returncode:
                failure = f'exit {proc.returncode}'
        except subprocess.TimeoutExpired as exc:
            failure, raw = 'timeout', _text(exc.stdout)[-4000:]
            envelope, spawns = _read_stream(_text(exc.stdout))
        except Exception as exc:  # noqa: BLE001  any launch error is a recorded failed attempt
            failure = f'{type(exc).__name__}: {exc}'[:300]
    mu = envelope.get('modelUsage') if isinstance(envelope, dict) else None
    seen = sorted(mu) if isinstance(mu, dict) else []
    if isinstance(envelope, dict) and not failure:
        if envelope.get('is_error'):
            failure = 'is_error'
        elif seen != [model]:
            failure = 'unexpected model(s): ' + ', '.join(seen)
        elif not isinstance(envelope.get('result'), str):
            failure = 'no result text'
    ended = time.time()
    ok_env = isinstance(envelope, dict)
    return {'text': '' if failure or not ok_env else envelope['result'], 'usage': usage_of(mu), 'failure': failure,
            'models': seen, 'spawns': spawns, 'turns': envelope.get('num_turns') if ok_env else None,
            'api_ms': envelope.get('duration_api_ms') if ok_env else None, 'started': started, 'ended': ended,
            'seconds': round(ended - started, 2), 'envelope': envelope, 'raw': raw}


class Ledger:
    """Shared launch and token caps in one SQLite file (see the module docstring for the rules)."""

    def __init__(self, path: Path, *, max_launches: int, max_tokens: int, reserve: int, stale_after: float = 1800):
        self.path, self.max_launches, self.max_tokens = Path(path), max_launches, max_tokens
        self.reserve_tokens, self.stale_after = reserve, stale_after
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS launch (id TEXT PRIMARY KEY, created REAL NOT NULL, '
                        'settled INTEGER NOT NULL DEFAULT 0, tokens INTEGER, unknown INTEGER NOT NULL DEFAULT 0)')

    def _db(self):
        con = sqlite3.connect(self.path, timeout=60, isolation_level=None)
        con.execute('PRAGMA busy_timeout = 60000')
        return _Tx(con)

    def _state(self, con) -> dict:
        stale = time.time() - self.stale_after
        launches, tokens_, unknown, pending, stale_n = con.execute(
            'SELECT COUNT(*), COALESCE(SUM(tokens), 0), COALESCE(SUM(unknown), 0), '
            'COALESCE(SUM(settled = 0 AND created >= ?), 0), COALESCE(SUM(settled = 0 AND created < ?), 0) '
            'FROM launch', (stale, stale)).fetchone()
        return {'launches': launches, 'tokens': tokens_, 'calls_without_usage': unknown + stale_n,
                'in_flight': pending, 'stale_unsettled': stale_n, 'overshoot': max(0, tokens_ - self.max_tokens)}

    def state(self) -> dict:
        with self._db() as con:
            return self._state(con)

    def _refusal(self, s) -> str | None:
        if s['calls_without_usage']:
            return f"{s['calls_without_usage']} call(s) without usage; token caps cannot be enforced"
        if s['launches'] >= self.max_launches:
            return f'launch cap {self.max_launches} reached'
        if s['tokens'] + (s['in_flight'] + 1) * self.reserve_tokens > self.max_tokens:
            return f'token cap {self.max_tokens} reached'
        return None

    def refusal(self) -> str | None:
        return self._refusal(self.state())

    def reserve(self) -> str | None:
        """A durable reservation id for one launch, or None when a cap or a call without usage forbids it."""
        with self._db() as con:
            con.execute('BEGIN IMMEDIATE')
            if self._refusal(self._state(con)):
                return None
            rid = uuid.uuid4().hex
            con.execute('INSERT INTO launch (id, created) VALUES (?, ?)', (rid, time.time()))
            return rid

    def charge(self, rid: str, usage) -> None:
        """Settle one reservation with its real usage (None when unknown). Settling twice is an error."""
        n = tokens(usage)
        with self._db() as con:
            con.execute('BEGIN IMMEDIATE')
            cur = con.execute('UPDATE launch SET settled = 1, tokens = ?, unknown = ? WHERE id = ? AND settled = 0',
                              (n, int(n is None), rid))
            if cur.rowcount != 1:
                raise RuntimeError(f'reservation {rid} unknown or already settled')


class _Tx:
    """Context manager: commit on success, roll back on error, always close."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        return self.con

    def __exit__(self, exc_type, *_):
        try:
            if self.con.in_transaction:
                self.con.execute('ROLLBACK' if exc_type else 'COMMIT')
        finally:
            self.con.close()


def run_charged(ledger: Ledger, fn):
    """Reserve one launch, run fn() -> call record, settle it with the record's usage (None if fn raised).
    Returns the record, or None when the ledger refused the launch."""
    rid = ledger.reserve()
    if rid is None:
        return None
    usage = None
    try:
        c = fn()
        usage = c.get('usage')
        return c
    finally:
        ledger.charge(rid, usage)


def total(usages) -> dict:
    """Sums over calls with known usage plus the count without; conclusive only when every call has usage."""
    usages = list(usages)
    known = [u for u in usages if u is not None]
    out = {k: sum(u[k] for u in known) for k in ('input_tokens', 'cached_input_tokens', 'output_tokens')}
    th = [u['thinking_tokens'] for u in known]
    out.update(thinking_tokens=sum(t for t in th if t is not None), thinking_unknown=sum(t is None for t in th),
               tokens=sum(tokens(u) for u in known), calls=len(usages), calls_without_usage=len(usages) - len(known),
               conclusive=len(known) == len(usages))
    return out
