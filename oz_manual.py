"""Python facade for the proven manual path: install, run, revise, status, artifacts (packaging contract
docs/design/next-2026-10-23/04, changed by 05, settled by 06).

    from oz_manual import install, run, revise, status, artifacts, SCOPE

    install(request, settings)                          validate and install a flow; executes nothing, starts the deadline
    result = run(request, settings)                     oz_flow.run_flow under an exclusive per-request lock
    revise(request_id, settings, source, data, reason)  a new authoritative source revision; executes nothing
    snapshot = status(request_id, settings)             persisted state, read-only
    delivered = artifacts(request_id, settings, target) the current delivery's files, read-only

`request` is the existing oz.flow/1 request with its OZ9 graph. `settings` is an explicitly constructed
oz_flow.Settings: registries, checks, adapter, route, budgets and destinations stay host-owned. There is no
configuration importer, scheduler, replanner or MCP, and no wire change. This module adds no execution path: run is
oz_flow.run_flow, and install is the first half of it (oz_flow.admit validates a graph and nothing else; install also
persists the flow). Installation starts the original deadline, so time spent between install and run is spent from it.

Reads. status and artifacts open flow.sqlite (and a stage's inbox.sqlite) with SQLite mode=ro. A missing flow is an
explicit FlowNotFound and creates nothing, not even a directory. A database at rest (no write-ahead log or shared-memory
file beside it) is read as an immutable snapshot, because a plain read-only connection would create those two files;
the read is repeated if the file moved while it was being read. Nothing is launched, repaired or republished by a read.

Run lock. oz_flow has no flow-level lock, so two runs of one request id would both execute host nodes and dispatch
stages. run holds an exclusive lock on flows/<request_id>/run.lock for the whole call; a second concurrent run fails
at once with RunInProgress. The operating system releases the lock when its holder dies, so a hard-killed run never
leaves it held. revise is one transaction and takes no lock: a revision made while a run is active is seen by that run's
freshness checks, which refuse a commit that cites an older revision.

Scope. SCOPE is printed to stderr once per process, on the first call of any entry point. Example scripts print their
own route and workflow lines; this module does not guess which example it serves. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

from oz import Error
from oz_flow import Flow, REQUEST_ID, admit, flow_dir, run_flow
from oz_reply import USAGE_FIELDS, loads

try:  # exclusive file locks: POSIX flock, Windows byte-range locking
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
    import msvcrt

__all__ = ('SCOPE', 'install', 'run', 'revise', 'status', 'artifacts', 'ManualError', 'FlowNotFound', 'RunInProgress',
           'ArtifactsUnavailable')
SCOPE = ('scope=manual-graph; acceptance=oz1g-selective-v1; delivery=local-files\n'
         'qualification=experimental; live-model-qualification=not-established-by-packaging')
STATUS_SCHEMA = 'oz.manual.status/1'
ARTIFACTS_SCHEMA = 'oz.manual.artifacts/1'
INSTALL_SCHEMA = 'oz.manual.install/1'
REVISION_SCHEMA = 'oz.manual.revision/1'
LOCK_NAME = 'run.lock'
_announced = False


class ManualError(Error):
    """Base of the facade's named errors."""


class FlowNotFound(ManualError):
    """No installed flow has this request id in this workspace (a read creates nothing)."""


class RunInProgress(ManualError):
    """Another run of the same request id holds the exclusive run lock."""


class ArtifactsUnavailable(ManualError):
    """No committed, current, matching delivery. code is one of not_delivered, stale, missing, conflict."""

    def __init__(self, code: str, message: str, **detail):
        super().__init__(message)
        self.code = code
        self.detail = detail


def _announce():
    global _announced
    if not _announced:
        _announced = True
        print(SCOPE, file=sys.stderr, flush=True)


def _check_id(request_id) -> str:
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise Error('flow request_id must be 1..32 characters of [A-Za-z0-9_-]')
    return request_id


# ---- the run lock ----

class _RunLock:
    def __init__(self, directory: Path, request_id: str):
        self.path = Path(directory) / LOCK_NAME
        self.request_id = request_id
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(self.path, 'a+b')
        try:
            if fcntl is not None:
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.file.close()
            self.file = None
            raise RunInProgress(f'request {self.request_id} is already being run by another process; '
                                f'a request id has one runner at a time') from None
        return self

    def __exit__(self, *_):
        if self.file is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            else:
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.file.close()


# ---- read-only access ----

def _stamp(path: Path):
    st = path.stat()
    return st.st_mtime_ns, st.st_size


def _at_rest(path: Path) -> bool:
    return not (path.with_name(path.name + '-wal').exists() or path.with_name(path.name + '-shm').exists())


def _connect_ro(path: Path):
    """(connection, stamp or None). With a write-ahead log or shared-memory file present the connection is a plain
    mode=ro one (it creates nothing). At rest it is an immutable snapshot, and the returned stamp lets the caller
    detect that the file moved underneath the read."""
    path = Path(path).resolve()
    uri = path.as_uri()
    if _at_rest(path):
        stamp = _stamp(path)
        db = sqlite3.connect(uri + '?mode=ro&immutable=1', uri=True, timeout=30)
    else:
        stamp = None
        db = sqlite3.connect(uri + '?mode=ro', uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db, stamp


def _read(path: Path, fn):
    """fn(connection) on a read-only connection; repeated while an immutable snapshot was disturbed."""
    path = Path(path).resolve()
    for _ in range(10):
        db, stamp = _connect_ro(path)
        try:
            try:
                out = fn(db)
            except sqlite3.DatabaseError:
                if stamp is None or (_at_rest(path) and _stamp(path) == stamp):
                    raise
                continue
        finally:
            db.close()
        if stamp is None or (_at_rest(path) and _stamp(path) == stamp):
            return out
    raise ManualError(f'{path.name} kept changing while it was read; try again')


class _ReadFlow(Flow):
    """oz_flow.Flow's read methods over a read-only connection. Flow.__init__ creates the directory, sets WAL and runs
    the schema in a write transaction, so the facade never constructs a Flow to look at one."""

    def __init__(self, path, *, db=None, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.db = db if db is not None else _connect_ro(self.path)[0]

    def tx(self):
        raise ManualError('a read-only flow cannot write')

    def event(self, event: str, **details) -> int:
        raise ManualError('a read-only flow cannot write')


def _flow_read(path: Path, fn):
    return _read(path, lambda db: fn(_ReadFlow(path, db=db)))


def _flow_file(settings, request_id: str) -> Path:
    _check_id(request_id)
    path = flow_dir(settings.workspace, request_id) / 'flow.sqlite'
    if not path.is_file():
        raise FlowNotFound(f'no flow named {request_id} in {Path(settings.workspace)}')
    return path


def _stage_launches(run: Path) -> list:
    """oz_flow.stage_launches over a read-only connection (same rows, same order, nothing written)."""
    path = Path(run) / 'inbox.sqlite'
    if not path.exists():
        return []
    rows = _read(path, lambda db: [dict(r) for r in db.execute(
        "SELECT receipt,state,created_at,members,packet,route,process,call_id,response,outcome FROM dispatches "
        "WHERE state!='not_launched' ORDER BY created_at")])
    for row in rows:
        row['response'] = json.loads(row['response']) if row['response'] else None
    return rows


def _accounting(run: Path, journal=()) -> dict:
    """The request accounting for one run directory, recomputed here from the same two files (calls.jsonl and
    do.jsonl) plus the dispatch journal. Files are only read; the parity test pins it to oz_flow.flow_usage."""
    starts, ends = {}, {}
    ledger = run / 'calls.jsonl'
    for line in (ledger.read_text(encoding='utf-8').splitlines() if ledger.exists() else ()):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        (starts if record.get('event') == 'call_start' else ends)[record.get('call_id')] = record
    profiles = {}
    log = run / 'do.jsonl'
    for line in (log.read_text(encoding='utf-8').splitlines() if log.exists() else ()):
        try:
            record = json.loads(line)
            profiles[record['call_id']] = record['profile']
        except (ValueError, KeyError, TypeError):
            continue
    calls = list(dict.fromkeys([*starts, *ends, *(d['call_id'] for d in journal if d['call_id'])]))
    raw = {c: ends[c]['usage']['raw'] for c in calls if c in ends
           and isinstance((ends[c].get('usage') or {}).get('raw'), dict)}
    for d in journal:
        usage = (d['response'] or {}).get('usage') if isinstance(d['response'], dict) else None
        if d['call_id'] and d['call_id'] not in raw and d['state'] == 'captured' and isinstance(usage, dict):
            raw[d['call_id']] = usage
    with_usage = [c for c in calls if c in raw and {'input_tokens', 'output_tokens'} <= set(raw[c])]
    tokens = {k: sum(raw[c].get(k, 0) for c in with_usage) for k in USAGE_FIELDS}
    coverage = 'complete' if len(with_usage) == len(calls) else 'none' if not with_usage else 'partial'
    count = lambda name: sum(1 for c in calls if profiles.get(c, 'unrecorded') == name)
    extra = {}
    if journal:
        states = {}
        for d in journal:
            states[d['state']] = states.get(d['state'], 0) + 1
        extra = {'dispatches': states, 'unreconciled_dispatches': states.get('uncertain', 0) + states.get('intent', 0)
                 + states.get('launched', 0)}
    return dict({'calls': len(calls),
            'failed_calls': sum(1 for c in calls if c not in ends or ends[c].get('outcome') not in ('ok', 'job_error')),
            'unfinished_calls': sum(1 for c in calls if c not in ends),
            'experimental_calls': count('experimental'), 'qualified_cell_calls': count('qualified_cell'),
            'usage_coverage': coverage, 'calls_with_usage': len(with_usage),
            'tokens': tokens, 'tokens_scope': 'all calls' if coverage == 'complete' else 'calls with reported usage only'},
                **extra)


def _usage_of(workspace, runs) -> dict:
    launches, tokens, unknown, unreconciled, calls = 0, 0, 0, 0, []
    for rel in sorted(runs):
        run = Path(workspace) / rel
        journal = _stage_launches(run)
        launches += len(journal)
        acc = _accounting(run, journal)
        tokens += acc['tokens'].get('input_tokens', 0) + acc['tokens'].get('output_tokens', 0)
        unknown += max(0, len(journal) - acc['calls_with_usage'])
        unreconciled += acc.get('unreconciled_dispatches', 0)
        calls.append({'run_dir': rel, 'launches': len(journal), 'accounting': acc})
    return {'launches': launches, 'tokens_known': tokens, 'calls_without_usage': unknown, 'runs': calls,
            'unreconciled_dispatches': unreconciled}


def _run_dirs(flow: Flow) -> set:
    return {e['details']['run_dir'] for e in flow.events()
            if e['event'] in ('stage_submitted', 'stage') and e['details'].get('run_dir')}


def _usage(workspace, request_id: str) -> dict:
    """oz_flow.flow_usage without writing: launches and tokens of one flow, from its stage journals and ledgers."""
    path = flow_dir(workspace, request_id) / 'flow.sqlite'
    runs = _flow_read(path, _run_dirs) if path.exists() else set()
    out = _usage_of(workspace, runs)
    out.pop('unreconciled_dispatches')
    return out


# ---- entry points ----

def install(request: dict, settings) -> dict:
    """Validate the request through graph admission and install the flow, executing nothing and launching no adapter.
    The first installation starts the original deadline. Installing the same request again changes nothing; changed
    work under an installed request id fails."""
    _announce()
    request_id, descriptors, deadline = _admitted(request, settings)
    flow = Flow(flow_dir(settings.workspace, request_id) / 'flow.sqlite')
    try:
        created = flow.install(request, descriptors, request['graph']['outputs'], deadline)
        info = flow.info()
    finally:
        flow.close()
    return {'schema': INSTALL_SCHEMA, 'request_id': request_id, 'installed': created,
            'request_sha256': info['request_sha256'], 'nodes': len(descriptors), 'created_at': info['created_at'],
            'deadline_at': info['deadline_at']}


def _admitted(request, settings):
    if not isinstance(request, dict) or not REQUEST_ID.fullmatch(str(request.get('request_id', ''))):
        raise Error('flow request_id must be 1..32 characters of [A-Za-z0-9_-]')
    if not isinstance(request.get('graph'), dict):
        raise Error('a flow request carries a graph')
    descriptors = admit(request['graph'], settings.registry, effects=request.get('effects', ()))
    return request['request_id'], descriptors, float(request.get('deadline_seconds', 3600))


def run(request: dict, settings) -> dict:
    """oz_flow.run_flow under the exclusive per-request lock: admission when needed, then execution to delivery, a
    blocker or the original deadline. Resuming is the identical call. Returns the oz.flow.result/1 result."""
    _announce()
    request_id, _, _ = _admitted(request, settings)
    with _RunLock(flow_dir(settings.workspace, request_id), request_id):
        return run_flow(request, settings)


def revise(request_id: str, settings, source: str, data: bytes, reason: str) -> dict:
    """Add a source revision (Flow.bump_source) in one transaction; identical bytes still make a new revision. Nothing
    executes. The source must already be in the flow's store, which a run puts there when a host node first reads it."""
    _announce()
    path = _flow_file(settings, request_id)
    if not isinstance(source, str) or not source:
        raise Error('revise needs a source name')
    if not isinstance(data, (bytes, bytearray)):
        raise Error('revise data is bytes')
    if not isinstance(reason, str) or not reason.strip():
        raise Error('revise needs a reason')
    flow = Flow(path)
    try:
        if flow.info() is None:
            raise FlowNotFound(f'no flow named {request_id} in {Path(settings.workspace)}')
        revision = flow.bump_source(source, bytes(data), reason=reason)
        digest = flow.source(source, revision)['sha256']
    finally:
        flow.close()
    return {'schema': REVISION_SCHEMA, 'request_id': request_id, 'source': source, 'revision': revision,
            'sha256': digest, 'reason': reason}


def _targets(info, current, deliveries) -> dict:
    by_target = {d['target']: d for d in deliveries}
    targets = {}
    for target, node in info['outputs'].items():
        d = by_target.get(target)
        if node in current and d is not None and d['intent'] == loads(current[node]['value']).get('intent'):
            value = loads(current[node]['value'])
            targets[target] = {'status': 'delivered', 'weight': 1, 'destination': value['destination'],
                               'artifacts': value['artifacts'], 'delivered_at': d['at'],
                               'on_time': d['at'] <= info['deadline_at'], 'cites': d['cites']}
        else:
            targets[target] = {'status': 'unresolved', 'weight': 1}
    return targets


def _blocker(events: list):
    """The blocker recorded by the latest invocation, if it ended blocked; None for a finished, interrupted or
    not-yet-run flow (an interruption leaves no record, so it is not invented here)."""
    last_run = max((e['seq'] for e in events if e['event'] == 'invocation'), default=0)
    for e in reversed(events):
        if e['event'] == 'blocked' and e['seq'] > last_run:
            return e['details']
    return None


def status(request_id: str, settings, clock=time.time) -> dict:
    """The persisted state of one flow, read-only: current targets, the latest invocation's blocker, source
    revisions, node generations, launches and accounting coverage. Never launches, repairs, extends a deadline or
    creates a flow. The remaining deadline is read from clock, the flow's own injectable clock (time.time by default)."""
    _announce()
    path = _flow_file(settings, request_id)

    def look(flow):
        info = flow.info()
        if info is None:
            raise FlowNotFound(f'no flow named {request_id} in {Path(settings.workspace)}')
        current = flow.current()
        descriptors = flow.descriptors()
        events = flow.events()
        return {'info': info, 'current': current, 'deliveries': flow.deliveries(), 'descriptors': descriptors,
                'revisions': flow.revisions(), 'events': events, 'runs': _run_dirs(flow)}

    seen = _flow_read(path, look)
    info = seen['info']
    usage = _usage_of(settings.workspace, seen['runs'])
    targets = _targets(info, seen['current'], seen['deliveries'])
    delivered = all(t['status'] == 'delivered' for t in targets.values())
    return {'schema': STATUS_SCHEMA, 'request_id': request_id, 'status': 'delivered' if delivered else 'incomplete',
            'targets': targets, 'blocker': _blocker(seen['events']), 'launches': usage['launches'],
            'accounting': {'tokens_known': usage['tokens_known'], 'calls_without_usage': usage['calls_without_usage'],
                           'coverage': 'complete' if usage['calls_without_usage'] == 0 else 'incomplete',
                           'unreconciled_dispatches': usage['unreconciled_dispatches']},
            'flow': {'request_id': request_id, 'request_sha256': info['request_sha256'],
                     'created_at': info['created_at'], 'deadline_at': info['deadline_at'],
                     'deadline_remaining_seconds': round(info['deadline_at'] - clock(), 3),
                     'generations': {d['id']: d['generation'] for d in seen['descriptors']},
                     'revisions': seen['revisions'],
                     'nodes': {'total': len(seen['descriptors']), 'current': len(seen['current'])}}}


def artifacts(request_id: str, settings, target: str | None = None, generation: int | None = None) -> dict:
    """The files of a delivery, read-only: destination, artifact paths, byte counts, SHA-256 values and the source
    citations. Without generation it is the target's current delivery, which must be committed, current and matched
    by the files on disk (ArtifactsUnavailable otherwise: not_delivered, stale, missing, conflict). With generation it
    reads that delivery of the target and reports it as superseded when it is no longer the current one. Artifact
    bodies are never returned and nothing is republished."""
    _announce()
    path = _flow_file(settings, request_id)
    if generation is not None and (type(generation) is not int or generation < 1):
        raise Error('generation is a positive integer')

    def look(flow):
        info = flow.info()
        if info is None:
            raise FlowNotFound(f'no flow named {request_id} in {Path(settings.workspace)}')
        return {'info': info, 'current': flow.current(), 'deliveries': flow.deliveries(),
                'effects': {e['intent']: e for e in flow.effects()}, 'revisions': flow.revisions()}

    seen = _flow_read(path, look)
    outputs = seen['info']['outputs']
    if target is None:
        if len(outputs) != 1:
            raise Error('this flow has several targets; name one of ' + ', '.join(sorted(outputs)))
        target = next(iter(outputs))
    if target not in outputs:
        raise Error(f'unknown target {target}; the targets are ' + ', '.join(sorted(outputs)))
    node = outputs[target]
    current = seen['current']
    held = loads(current[node]['value']).get('intent') if node in current else None
    delivered = [d for d in seen['deliveries'] if d['target'] == target]
    if generation is None:
        if held is None:
            if delivered:
                raise ArtifactsUnavailable(
                    'stale', f'the delivery of target {target} is no longer current (its sources or inputs changed); '
                             f'run the request again', last_intent=delivered[-1]['intent'])
            raise ArtifactsUnavailable('not_delivered', f'target {target} has no delivery yet')
        intent = held
    else:
        intent = f'{request_id}:{node}:g{generation}'
    delivery = next((d for d in delivered if d['intent'] == intent), None)
    effect = seen['effects'].get(intent)
    if delivery is None or effect is None or effect['state'] != 'delivered':
        raise ArtifactsUnavailable('not_delivered', f'target {target} has no committed delivery ' + (
            f'for generation {generation}' if generation is not None else 'that matches its current acceptance'))
    manifest = effect['files'].get('manifest.json')
    if manifest is None or manifest['sha256'] != delivery['manifest_sha256']:
        raise ArtifactsUnavailable('conflict', f'the stored manifest of {intent} does not match its delivery')
    workspace = Path(settings.workspace)
    listed, missing, conflicting = [], [], []
    for name in sorted(effect['files']):
        item = effect['files'][name]
        file = workspace / effect['destination'] / name
        if not file.is_file():
            missing.append(name)
            continue
        if _sha_file(file) != item['sha256']:
            conflicting.append(name)
            continue
        listed.append({'name': name, 'path': (Path(effect['destination']) / name).as_posix(),
                       'bytes': len(item['text'].encode('utf-8')), 'sha256': item['sha256']})
    if conflicting or missing:
        code = 'conflict' if conflicting else 'missing'
        raise ArtifactsUnavailable(code, f'delivered files of {intent} do not match the delivery: '
                                         f'missing {missing or "none"}, changed {conflicting or "none"}',
                                   missing=missing, conflicting=conflicting)
    is_current = held == intent
    sources = json.loads(manifest['text'])['sources']
    stale = {s: {'cited': r, 'current': seen['revisions'].get(s)} for s, r in sorted(delivery['cites'].items())
             if seen['revisions'].get(s) != r}
    result = {'schema': ARTIFACTS_SCHEMA, 'request_id': request_id, 'target': target, 'node': node,
              'generation': effect['generation'], 'intent': intent,
              'status': 'current' if is_current else 'superseded', 'current': is_current,
              'destination': effect['destination'], 'artifacts': listed, 'manifest_sha256': delivery['manifest_sha256'],
              'citations': {s: {'revision': v['revision'], 'sha256': v['sha256']} for s, v in sources.items()},
              'delivered_at': delivery['at']}
    if not is_current:
        newer = seen['effects'].get(held) if held else None
        result['superseded_by'] = (None if newer is None else {'intent': held, 'generation': newer['generation']})
        result['stale_sources'] = stale
    return result


def _sha_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
