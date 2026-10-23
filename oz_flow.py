"""Manual graph executor over the shared service layer (foundation record clauses 1 and 3 to 7; step 4).

A flow is one admitted OZ9 graph ({v, base, nodes:[{id, op, in, after}], outputs}) with its own authoritative SQLite
(flows/<request_id>/flow.sqlite): the request, the persisted node descriptors, the source store, node acceptances,
effect intents, deliveries and an ordered event log. Model nodes never run here: ready model nodes of one operation
form one `oz do` request (oz1g-selective-v1, durable runner, per-job checks, memo, quota reservation, admission), so
dispatch, capture, acceptance and accounting stay in the existing inbox, worker and ledger. Host nodes run registered
host operations; model output never selects an operation, a check, a destination or a budget.

Freshness. Sources live in the flow database as (name, revision, sha256, bytes); a host command adds a revision in one
transaction. Every node acceptance records the acceptances it consumed and the source revisions it cites (its whole
read-set). It commits in one transaction only if every cited revision and every consumed acceptance is still current,
and a node is usable only while its latest acceptance is current. Old acceptances stay as history. The delivery row
commits in the same conditional transaction as the publishing node's acceptance.

Effects. A publishing node gets one stable intent per (request, node, generation) holding the exact artifact bytes
and a deterministic local destination. Files are published (temporary file, fsync, rename) before the delivery that
references them commits; a matching existing file is reconciled, a conflicting one blocks.

Resume. Running the same request again reopens the same database: the original deadline, consumed launches and
accepted history stay; nothing is repaired by hand. Standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Callable

from oz import Error
from oz_accept import SELECTIVE
from oz_batch import J
from oz_do import _accounting, do
from oz_memo import MemoStore
from oz_reply import RawJSON, dumps, loads
from oz_runner import publish
import oz_fault

GRAPH_VERSION = 1
REQUEST_SCHEMA = 'oz.flow/1'
RESULT_SCHEMA = 'oz.flow.result/1'
NODE_ID = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,63}')
REQUEST_ID = re.compile(r'[A-Za-z0-9_-]{1,32}')
MAX_NODES = 256
HOST_MARGIN = 60


class HostError(Error):
    """A host operation refused its inputs; the node is blocked with this reason."""


class SupersededIntent(Exception):
    """A publishing node's stored intent was built from source revisions that are no longer the ones it cites now."""


@dataclass(frozen=True)
class HostOp:
    name: str
    version: int
    inputs: frozenset
    run: Callable
    effect: str | None = None

    @property
    def identity(self):
        return f'{self.name}@{self.version}'


@dataclass(frozen=True)
class ModelOp:
    """A model operation. By default it binds one text input, record. inputs given as a tuple are ordered: each job
    sends them as its refs in that order (one row, the shipped first-use packer lays them out). values names the
    inputs sent in the opt-in JSON value form of `oz do` refs ({"value": ...}); the others must be nonblank text. An
    ordered or value-form operation hashes its input order and value forms into its identity as well."""
    name: str
    version: int
    goal: str
    instruction: str
    checks: tuple = ()
    memo: bool = True
    inputs: frozenset | tuple = frozenset({'record'})
    values: frozenset = frozenset()

    @property
    def ref_order(self) -> tuple:
        return tuple(self.inputs) if isinstance(self.inputs, tuple) else tuple(sorted(self.inputs))

    @property
    def single(self) -> bool:
        """The shipped form: one text input, sent as the job's one ref."""
        return len(self.ref_order) == 1 and not self.values

    @property
    def identity(self):
        parts = [self.goal, self.instruction]
        if not self.single:
            parts += [list(self.ref_order), sorted(self.values)]
        return f'{self.name}@{self.version}:sha256:' + _sha(J(parts))


def _sha(text) -> str:
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode('utf-8')).hexdigest()


# ---- admission (clause 6) ----

def _binding_nodes(binding, where) -> list:
    if not isinstance(binding, dict) or len(binding) == 0:
        raise Error(f'{where}: a binding is {{"lit"}}, {{"ref","path"}}, {{"node","path"}} or {{"list"}}')
    keys = set(binding)
    if keys == {'lit'}:
        return []
    if keys <= {'ref', 'path'} and 'ref' in keys or keys <= {'node', 'path'} and 'node' in keys:
        if 'path' in binding and (not isinstance(binding['path'], str)
                                  or binding['path'] and not binding['path'].startswith('/')):
            raise Error(f'{where}: path must be a JSON Pointer')
        name = binding.get('ref', binding.get('node'))
        if not isinstance(name, str) or not name:
            raise Error(f'{where}: binding target must be a name')
        return [name] if 'node' in binding else []
    if keys == {'list'} and isinstance(binding['list'], list):
        return [n for b in binding['list'] for n in _binding_nodes(b, where)]
    raise Error(f'{where}: unknown binding form')


def admit(graph: dict, registry: dict, *, effects=()) -> list:
    """Validated, persisted-ready node descriptors in topological order, or Error; nothing is partial."""
    if not isinstance(graph, dict) or set(graph) != {'v', 'base', 'nodes', 'outputs'}:
        raise Error('a graph has exactly v, base, nodes and outputs')
    if graph['v'] != GRAPH_VERSION or type(graph['base']) is not int:
        raise Error('graph v must be 1 and base an integer revision')
    nodes = graph['nodes']
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= MAX_NODES:
        raise Error(f'a graph has 1..{MAX_NODES} nodes')
    by_id = {}
    for node in nodes:
        if not isinstance(node, dict) or set(node) != {'id', 'op', 'in', 'after'}:
            raise Error('every node has exactly id, op, in and after')
        if not isinstance(node['id'], str) or not NODE_ID.fullmatch(node['id']) or node['id'] in by_id:
            raise Error(f'invalid or duplicate node id: {node.get("id")!r}')
        by_id[node['id']] = node
    out = {}
    for node in nodes:
        where = node['id']
        op = registry.get(node['op'])
        if op is None:
            raise Error(f'{where}: operation {node["op"]!r} is not registered')
        if not isinstance(node['in'], dict) or set(node['in']) != set(op.inputs):
            raise Error(f'{where}: inputs must be exactly {sorted(op.inputs)}')
        if not isinstance(node['after'], list) or any(not isinstance(a, str) for a in node['after']):
            raise Error(f'{where}: after lists node ids')
        if isinstance(op, HostOp) and op.effect is not None and op.effect not in effects:
            raise Error(f'{where}: effect {op.effect} is not authorized for this request')
        deps = [d for b in node['in'].values() for d in _binding_nodes(b, where)] + list(node['after'])
        missing = [d for d in deps if d not in by_id]
        if missing:
            raise Error(f'{where}: unknown dependency {missing[0]}')
        if isinstance(op, ModelOp):
            descriptor = {'kind': 'model', 'op': node['op'], 'identity': op.identity, 'checks': list(op.checks),
                          'memo': op.memo, 'goal_sha256': _sha(op.goal), 'instruction_sha256': _sha(op.instruction)}
            if not op.single:
                descriptor.update(refs=list(op.ref_order), values=sorted(op.values))
        else:
            descriptor = {'kind': 'host', 'op': node['op'], 'identity': op.identity, 'effect': op.effect}
        out[where] = dict(descriptor, id=where, bindings=node['in'], deps=sorted(set(deps)),
                          freshness='current_sources_at_commit')
    order, state = [], {}

    def visit(n, path=()):
        if state.get(n) == 'done':
            return
        if state.get(n) == 'open':
            raise Error('graph has a cycle through ' + n)
        state[n] = 'open'
        for d in out[n]['deps']:
            visit(d)
        state[n] = 'done'
        order.append(n)

    for node in nodes:
        visit(node['id'])
    outputs = graph['outputs']
    if not isinstance(outputs, dict) or not outputs or any(v not in by_id for v in outputs.values()):
        raise Error('outputs map target names to node ids')
    return [dict(out[n], index=i) for i, n in enumerate(order)]


def pointer(value, path: str):
    if not path:
        return value
    for raw in path[1:].split('/'):
        part = raw.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', part) and int(part) < len(value):
            value = value[int(part)]
        else:
            raise HostError(f'binding path {path} does not resolve')
    return value


# ---- the flow database ----

SCHEMA = '''
CREATE TABLE IF NOT EXISTS flow(id INTEGER PRIMARY KEY CHECK(id=1), request_id TEXT NOT NULL, request TEXT NOT NULL,
    request_sha256 TEXT NOT NULL, outputs TEXT NOT NULL, created_at REAL NOT NULL, deadline_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY, idx INTEGER NOT NULL, descriptor TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sources(name TEXT NOT NULL, revision INTEGER NOT NULL, sha256 TEXT NOT NULL,
    bytes BLOB NOT NULL, at REAL NOT NULL, PRIMARY KEY(name, revision));
CREATE TABLE IF NOT EXISTS acceptances(seq INTEGER PRIMARY KEY, node TEXT NOT NULL REFERENCES nodes(id),
    generation INTEGER NOT NULL, value TEXT NOT NULL, value_sha256 TEXT NOT NULL, inputs TEXT NOT NULL,
    cites TEXT NOT NULL, evidence TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS effects(intent TEXT PRIMARY KEY, node TEXT NOT NULL, generation INTEGER NOT NULL,
    destination TEXT NOT NULL, files TEXT NOT NULL, state TEXT NOT NULL, detail TEXT, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS deliveries(seq INTEGER PRIMARY KEY, intent TEXT UNIQUE NOT NULL REFERENCES effects(intent),
    target TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, cites TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, at REAL NOT NULL, event TEXT NOT NULL, details TEXT NOT NULL)
'''


class Flow:
    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        with self.tx():
            for statement in SCHEMA.split(';'):
                if statement.strip():
                    self.db.execute(statement)

    def close(self):
        self.db.close()

    def tx(self):
        flow = self

        class _Tx:
            def __enter__(self):
                flow.db.execute('BEGIN IMMEDIATE')

            def __exit__(self, kind, *_):
                if kind is None:
                    flow.db.commit()
                else:
                    flow.db.rollback()
        return _Tx()

    def event(self, event: str, **details) -> int:
        return self.db.execute('INSERT INTO events(at,event,details) VALUES (?,?,?)',
                               (self.clock(), event, J(details))).lastrowid

    def events(self) -> list:
        return [dict(r, details=json.loads(r['details'])) for r in self.db.execute('SELECT * FROM events ORDER BY seq')]

    # Admission: the whole graph and request are installed in one transaction, once per request id.
    def install(self, request: dict, descriptors: list, outputs: dict, deadline_seconds: float) -> bool:
        text = J(request)
        digest = _sha(text)
        with self.tx():
            row = self.db.execute('SELECT request_sha256 FROM flow WHERE id=1').fetchone()
            if row is not None:
                if row['request_sha256'] != digest:
                    raise Error('request_id already names a different flow request; use a new request_id')
                return False
            now = self.clock()
            self.db.execute('INSERT INTO flow VALUES (1,?,?,?,?,?,?)', (request['request_id'], text, digest,
                                                                          J(outputs), now, now + deadline_seconds))
            self.db.executemany('INSERT INTO nodes(id,idx,descriptor) VALUES (?,?,?)',
                                [(d['id'], d['index'], J(d)) for d in descriptors])
            self.event('admitted', nodes=len(descriptors), request_sha256=digest)
        return True

    def info(self) -> dict:
        row = self.db.execute('SELECT * FROM flow WHERE id=1').fetchone()
        return None if row is None else dict(row, request=loads(row['request']), outputs=json.loads(row['outputs']))

    def descriptors(self) -> list:
        return [dict(json.loads(r['descriptor']), generation=r['generation'])
                for r in self.db.execute('SELECT * FROM nodes ORDER BY idx')]

    # Sources: the authoritative store (C4). Files are imported once; the file system is not the authority.
    def import_source(self, name: str, data: bytes) -> int:
        with self.tx():
            row = self.db.execute('SELECT MAX(revision) FROM sources WHERE name=?', (name,)).fetchone()[0]
            if row is not None:
                return row
            self.db.execute('INSERT INTO sources VALUES (?,?,?,?,?)', (name, 1, _sha(data), data, self.clock()))
            self.event('source_imported', name=name, revision=1, sha256=_sha(data))
        return 1

    def bump_source(self, name: str, data: bytes, *, reason: str) -> int:
        """A new authoritative revision in one transaction (identical bytes still make a new revision)."""
        with self.tx():
            row = self.db.execute('SELECT MAX(revision) FROM sources WHERE name=?', (name,)).fetchone()[0]
            if row is None:
                raise Error('unknown source ' + name)
            self.db.execute('INSERT INTO sources VALUES (?,?,?,?,?)', (name, row + 1, _sha(data), data, self.clock()))
            self.event('source_revised', name=name, revision=row + 1, sha256=_sha(data), reason=reason)
        return row + 1

    def revisions(self) -> dict:
        return {r['name']: r['rev'] for r in self.db.execute(
            'SELECT name, MAX(revision) AS rev FROM sources GROUP BY name')}

    def source(self, name: str, revision: int | None = None) -> dict:
        sql = 'SELECT * FROM sources WHERE name=? ' + ('AND revision=?' if revision else 'ORDER BY revision DESC')
        row = self.db.execute(sql + ' LIMIT 1', (name, revision) if revision else (name,)).fetchone()
        if row is None:
            raise HostError('unknown source ' + name)
        return dict(row)

    # Acceptances and currency.
    def latest(self) -> dict:
        out = {}
        for row in self.db.execute('SELECT * FROM acceptances ORDER BY seq'):
            out[row['node']] = dict(row, inputs=json.loads(row['inputs']), cites=json.loads(row['cites']),
                                    evidence=json.loads(row['evidence']))
        return out

    def current(self) -> dict:
        """{node: acceptance} for nodes whose latest acceptance still holds: every cited revision is current and every
        consumed acceptance is that dependency's current one."""
        revs, latest, out = self.revisions(), self.latest(), {}
        for d in self.descriptors():
            a = latest.get(d['id'])
            if (a is not None and all(revs.get(s) == r for s, r in a['cites'].items())
                    and all(out.get(dep, {}).get('seq') == seq for dep, seq in a['inputs'].items())
                    and set(a['inputs']) == set(d['deps'])):
                out[d['id']] = a
        return out

    def _fresh(self, inputs: dict, cites: dict) -> str | None:
        revs = self.revisions()
        stale = [s for s, r in cites.items() if revs.get(s) != r]
        if stale:
            return 'stale source revision: ' + ', '.join(sorted(stale))
        current = self.current()
        moved = [dep for dep, seq in inputs.items() if current.get(dep, {}).get('seq') != seq]
        return 'superseded input: ' + ', '.join(sorted(moved)) if moved else None

    def commit(self, node: str, generation: int, value: str, inputs: dict, cites: dict, evidence: dict,
               delivery: dict | None = None) -> str:
        """committed, or the reason nothing changed. The whole read-set is checked inside the transaction."""
        with self.tx():
            row = self.db.execute('SELECT generation FROM nodes WHERE id=?', (node,)).fetchone()
            if row is None or row['generation'] != generation:
                self.event('commit_refused', node=node, reason='generation superseded')
                return 'generation superseded'
            why = self._fresh(inputs, cites)
            if why is not None:
                self.event('commit_refused', node=node, generation=generation, reason=why)
                return why
            seq = self.db.execute('INSERT INTO acceptances(node,generation,value,value_sha256,inputs,cites,evidence,at) '
                                  'VALUES (?,?,?,?,?,?,?,?)', (node, generation, value, _sha(value), J(inputs),
                                                               J(cites), J(evidence), self.clock())).lastrowid
            if delivery is not None:
                self.db.execute('INSERT INTO deliveries(intent,target,manifest_sha256,cites,at) VALUES (?,?,?,?,?)',
                                (delivery['intent'], delivery['target'], delivery['manifest_sha256'], J(cites),
                                 self.clock()))
                self.db.execute("UPDATE effects SET state='delivered' WHERE intent=?", (delivery['intent'],))
                self.event('delivered', node=node, intent=delivery['intent'], target=delivery['target'])
            self.event('accepted', node=node, generation=generation, seq=seq, cites=cites)
        return 'committed'

    def regenerate(self, node: str, *, reason: str | None = None) -> int:
        with self.tx():
            self.db.execute('UPDATE nodes SET generation=generation+1 WHERE id=?', (node,))
            generation = self.db.execute('SELECT generation FROM nodes WHERE id=?', (node,)).fetchone()[0]
            if reason is None:
                self.event('regenerated', node=node, generation=generation)
            else:
                self.event('regenerated', node=node, generation=generation, reason=reason)
        return generation

    def deliveries(self) -> list:
        return [dict(r, cites=json.loads(r['cites'])) for r in self.db.execute('SELECT * FROM deliveries ORDER BY seq')]

    def effects(self) -> list:
        return [dict(r, files=json.loads(r['files'])) for r in self.db.execute('SELECT * FROM effects')]

    def intent(self, intent: str, node: str, generation: int, destination: str, files: dict) -> dict:
        """The stable intent: created once with its exact bytes; a retry gets the stored one back."""
        with self.tx():
            row = self.db.execute('SELECT * FROM effects WHERE intent=?', (intent,)).fetchone()
            if row is None:
                self.db.execute('INSERT INTO effects VALUES (?,?,?,?,?,?,?,?)',
                                (intent, node, generation, destination, J(files), 'intent', None, self.clock()))
                self.event('effect_intent', intent=intent, destination=destination,
                           files={k: v['sha256'] for k, v in files.items()})
                row = self.db.execute('SELECT * FROM effects WHERE intent=?', (intent,)).fetchone()
        return dict(row, files=json.loads(row['files']))

    def effect_state(self, intent: str, state: str, detail=None):
        with self.tx():
            self.db.execute('UPDATE effects SET state=?,detail=? WHERE intent=? AND state!=?',
                            (state, None if detail is None else J(detail), intent, 'delivered'))
            self.event('effect_' + state, intent=intent, detail=detail)


# ---- execution ----

@dataclass
class HostContext:
    flow: Flow
    node: str
    generation: int
    reads: dict = field(default_factory=dict)
    request: dict = field(default_factory=dict)

    def read_source(self, name: str, path: Path | None = None) -> dict:
        """Current source (importing the frozen file once when the store has none); recorded in the read-set."""
        if path is not None:
            self.flow.import_source(name, Path(path).read_bytes())
        row = self.flow.source(name)
        self.reads[name] = row['revision']
        return {'name': name, 'revision': row['revision'], 'sha256': row['sha256'], 'bytes': row['bytes']}


@dataclass
class Settings:
    """Host-side execution settings for one flow (never from the request or model output)."""
    workspace: Path
    adapter: object
    registry: dict
    checks_registry: dict
    route: dict
    model: str
    memo_store: Path | None = None
    namespace: str | None = None
    quota: object = None
    quota_group: str = 'claude-cli'
    budget: dict = field(default_factory=dict)
    budget_scope: Path | None = None
    route_check: Callable | None = None
    response_check: Callable | None = None
    packet_sizes: tuple = (4, 1)
    experimental_sizes: tuple = (4,)
    max_input_tokens: int = 100000


def flow_dir(workspace: Path, request_id: str) -> Path:
    return Path(workspace) / 'flows' / request_id


def _resolve(binding, values, ctx):
    if 'lit' in binding:
        return binding['lit']
    if 'node' in binding:
        return pointer(values[binding['node']], binding.get('path', ''))
    if 'ref' in binding:
        source = ctx.read_source(binding['ref'])
        return pointer(source['bytes'].decode('utf-8'), binding.get('path', ''))
    return [_resolve(b, values, ctx) for b in binding['list']]


def stage_launches(run: Path) -> list:
    """Journaled dispatches of a stage run that may have launched a process (all but confirmed non-execution)."""
    path = Path(run) / 'inbox.sqlite'
    if not path.exists():
        return []
    db = sqlite3.connect(str(path), timeout=10)
    db.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in db.execute("SELECT receipt,state,created_at,members,packet,route,process,call_id,"
                                            "response,outcome FROM dispatches WHERE state!='not_launched' "
                                            "ORDER BY created_at")]
    finally:
        db.close()
    for row in rows:
        row['response'] = json.loads(row['response']) if row['response'] else None
    return rows


def flow_usage(workspace: Path, request_id: str) -> dict:
    """Launches and tokens of one flow, from its stage runs' journals and ledgers (durable, resume-safe). A run is
    known from its stage_submitted event, written before the call starts, so launches made inside a running stage,
    including in-stage retries and a stage killed mid-call, count at the moment of the next admission."""
    fd = flow_dir(workspace, request_id)
    runs = set()
    if (fd / 'flow.sqlite').exists():
        f = Flow(fd / 'flow.sqlite')
        try:
            runs = {e['details']['run_dir'] for e in f.events()
                    if e['event'] in ('stage_submitted', 'stage') and e['details'].get('run_dir')}
        finally:
            f.close()
    launches, tokens, unknown, calls = 0, 0, 0, []
    for rel in sorted(runs):
        run = Path(workspace) / rel
        journal = stage_launches(run)
        launches += len(journal)
        acc = _accounting(run, journal)
        tokens += acc['tokens'].get('input_tokens', 0) + acc['tokens'].get('output_tokens', 0)
        unknown += max(0, len(journal) - acc['calls_with_usage'])
        calls.append({'run_dir': rel, 'launches': len(journal), 'accounting': acc})
    return {'launches': launches, 'tokens_known': tokens, 'calls_without_usage': unknown, 'runs': calls}


def _admission(flow: Flow, settings: Settings, request_id: str, call_timeout: float):
    budget = settings.budget

    def admit(size):
        remaining = flow.info()['deadline_at'] - flow.clock()
        if remaining < call_timeout + HOST_MARGIN:
            return {'reason': 'deadline_admission', 'remaining_seconds': round(remaining, 1)}
        scope = settings.budget_scope or settings.workspace
        flows = sorted(p.name for p in (Path(scope) / 'flows').glob('*') if (p / 'flow.sqlite').exists())
        usage = {f: flow_usage(scope, f) for f in flows}
        mine = usage.get(request_id, {'launches': 0})
        total_launches = sum(u['launches'] for u in usage.values())
        reserve = budget.get('reserve_per_launch', 5000)
        planned = (sum(u['tokens_known'] for u in usage.values())
                   + reserve * (sum(u['calls_without_usage'] for u in usage.values()) + 1))
        if 'max_launches' in budget and total_launches + 1 > budget['max_launches']:
            return {'reason': 'launch_cap', 'launches': total_launches, 'cap': budget['max_launches']}
        if 'max_launches_per_flow' in budget and mine['launches'] + 1 > budget['max_launches_per_flow']:
            return {'reason': 'flow_launch_cap', 'launches': mine['launches'], 'cap': budget['max_launches_per_flow']}
        if 'max_tokens' in budget and planned > budget['max_tokens']:
            return {'reason': 'token_cap', 'planned_with_reserve': planned, 'cap': budget['max_tokens']}
        if settings.route_check is not None:
            why = settings.route_check()
            if why is not None:
                return {'reason': 'route_changed', 'detail': why}
        return None
    return admit


def _stage_request(flow_rid, op, nodes, texts, generations, deadline, call_timeout, model, max_input_tokens):
    """The `oz do` request of one stage. A one-input operation sends ref n (the node's text) for job n, as shipped. An
    ordered operation sends refs n-<input> in its declared order (value-form inputs as {"value": ...}) for job n."""
    digest = _sha(J([op.identity, nodes, [texts[n] for n in nodes], [generations[n] for n in nodes]]))
    if op.single:
        refs, jobs = {n: texts[n] for n in nodes}, [[n, op.name, n] for n in nodes]
    else:
        refs, jobs = {}, []
        for n in nodes:
            names = [f'{n}-{k}' for k in op.ref_order]
            for k, name, value in zip(op.ref_order, names, texts[n]):
                refs[name] = {'value': value} if k in op.values else value
            jobs.append([n, op.name, *names])
    return {'request_id': f'{flow_rid}-{op.name}-{digest[:12]}', 'goal': op.goal, 'ops': {op.name: op.instruction},
            'refs': refs, 'jobs': jobs, 'model': model,
            'allow_experimental': True, 'profile': SELECTIVE, 'checks': {op.name: list(op.checks)} if op.checks else {},
            'max_attempts': 2, 'max_jobs_per_call': 4, 'max_input_tokens': max_input_tokens,
            'max_inline_bytes': 65536, 'deadline_seconds': deadline, 'call_timeout_seconds': call_timeout}


def _value_text(value) -> str:
    return value.text if isinstance(value, RawJSON) else J(value)


def _model_input(op, bindings: dict, values: dict, ctx):
    """The resolved model-visible input of one job: the record text of a one-input operation, else the list of its
    inputs in declared order. Text inputs must be nonblank text; value-form inputs a nonblank JSON value. Raises
    HostError (the stage is blocked with binding_failed, nothing is dispatched)."""
    out = []
    for name in op.ref_order:
        value = _resolve(bindings[name], values, ctx)
        if name in op.values:
            if value is None or isinstance(value, str) and not value.strip():
                raise HostError('a model value input must be a nonblank JSON value')
            try:
                J(value)
            except (TypeError, ValueError, Error):
                raise HostError('a model value input must be a nonblank JSON value') from None
        elif not isinstance(value, str) or not value.strip():
            raise HostError('a model input must be nonblank text')
        out.append(value)
    return out[0] if op.single else out


def run_flow(request: dict, settings: Settings, *, plan_only=False) -> dict:
    """Admit (once) and execute one flow request to delivery, a blocker or its original deadline."""
    if not isinstance(request, dict) or not REQUEST_ID.fullmatch(str(request.get('request_id', ''))):
        raise Error('flow request_id must be 1..32 characters of [A-Za-z0-9_-]')
    rid = request['request_id']
    descriptors = admit(request['graph'], settings.registry, effects=request.get('effects', ()))
    deadline_seconds = float(request.get('deadline_seconds', 3600))
    call_timeout = float(request.get('call_timeout_seconds', 300))
    fd = flow_dir(settings.workspace, rid)
    flow = Flow(fd / 'flow.sqlite')
    try:
        if plan_only:
            return _plan(flow, request, settings, descriptors)
        flow.install(request, descriptors, request['graph']['outputs'], deadline_seconds)
        with flow.tx():
            flow.event('invocation', plan_only=False)
        return _execute(flow, request, settings, call_timeout)
    finally:
        flow.close()


def _execute(flow: Flow, request: dict, settings: Settings, call_timeout: float) -> dict:
    rid = request['request_id']
    registry = settings.registry
    descriptors = {d['id']: d for d in flow.descriptors()}
    order = [d['id'] for d in sorted(descriptors.values(), key=lambda d: d['index'])]
    admit_call = _admission(flow, settings, rid, call_timeout)
    memo_store = MemoStore(settings.memo_store) if settings.memo_store is not None else None
    blocker = None
    refused = set()  # model commits refused in this invocation: (node, generation, value digest)
    try:
        while True:
            info = flow.info()
            remaining = info['deadline_at'] - flow.clock()
            current = flow.current()
            pending = [n for n in order if n not in current]
            if not pending:
                break
            if remaining <= 0:
                blocker = {'reason': 'deadline'}
                break
            ready = [n for n in pending if all(d in current for d in descriptors[n]['deps'])]
            if not ready:
                blocker = {'reason': 'no_ready_node', 'pending': pending}
                break
            values = {n: loads(a['value']) for n, a in current.items()}
            host = [n for n in ready if descriptors[n]['kind'] == 'host']
            if host:
                blocker = _run_host(flow, request, settings, descriptors[host[0]], current, values)
            else:
                op_name = descriptors[ready[0]]['op']
                group = [n for n in ready if descriptors[n]['op'] == op_name]
                blocker = _run_stage(flow, request, settings, registry[op_name], group, descriptors, current, values,
                                     remaining, call_timeout, admit_call, memo_store, refused)
            if blocker is not None:
                break
    finally:
        if memo_store is not None:
            memo_store.close()
    if blocker is not None:
        with flow.tx():
            flow.event('blocked', **blocker)
    result = _result(flow, request, settings, blocker)
    (flow.path.parent / 'execution-record.json').write_text(J(export(flow, settings.workspace)) + '\n',
                                                            encoding='utf-8')
    return result


def _generation(flow: Flow, node: str, descriptors: dict) -> int:
    """A node that has history but no current acceptance starts a new logical generation."""
    latest = flow.latest()
    generation = descriptors[node]['generation']
    if node in latest and latest[node]['generation'] == generation:
        generation = flow.regenerate(node)
        descriptors[node]['generation'] = generation
    return generation


def _run_host(flow, request, settings, d, current, values) -> dict | None:
    node = d['id']
    generation = _generation(flow, node, {node: d})
    op = settings.registry[d['op']]
    ctx = HostContext(flow, node, generation, request=request)
    inputs_acc = {dep: current[dep]['seq'] for dep in d['deps']}
    cites = {}
    for dep in d['deps']:
        cites.update(current[dep]['cites'])
    try:
        # Deferred input validation: bindings resolve only now, against current accepted values.
        inputs = {k: _resolve(b, values, ctx) for k, b in d['bindings'].items()}
        value = op.run(inputs, ctx)
    except HostError as exc:
        with flow.tx():
            flow.event('host_refused', node=node, generation=generation, reason=str(exc))
        return {'reason': 'host_refused', 'node': node, 'detail': str(exc)}
    cites.update(ctx.reads)
    delivery = None
    if op.effect is not None:
        try:
            value, delivery = _publish(flow, request, settings, d, generation, value, current, cites)
        except SupersededIntent as exc:
            _supersede(flow, settings, d, exc.args[0], 'sources moved since the stored intent was built')
            return None
        except HostError as exc:
            return {'reason': 'effect_blocked', 'node': node, 'detail': str(exc)}
    text = _value_text(value)
    oz_fault.point('flow.before_commit')
    status = flow.commit(node, generation, text, inputs_acc, cites, {'op': d['identity']}, delivery=delivery)
    if status == 'committed':
        oz_fault.point('flow.committed:' + node)
    elif delivery is not None:
        # A refused commit leaves exported files that no delivery names. The intent is closed and the node starts a
        # new generation, so the next attempt builds new artifacts under a new intent identity from current sources.
        _supersede(flow, settings, d, delivery['intent'], status)
    return None


def _supersede(flow: Flow, settings: Settings, d: dict, intent: str, reason: str):
    """Close an undelivered intent, set its files aside (never at a delivery destination) and regenerate the node."""
    row = next((e for e in flow.effects() if e['intent'] == intent), None)
    flow.effect_state(intent, 'superseded', {'reason': reason})
    if row is not None:
        target = Path(settings.workspace) / row['destination']
        aside = target.with_name(target.name + '.superseded')
        try:
            if target.exists() and not aside.exists():
                target.rename(aside)
        except OSError:
            pass
    d['generation'] = flow.regenerate(d['id'])


def _publish(flow, request, settings, d, generation, value, current, cites):
    """Clause 3 effect protocol for a local publication sink: stable intent, immutable files, reconciliation."""
    node = d['id']
    files = value.get('files') if isinstance(value, dict) else None
    if not isinstance(files, dict) or not files or any(not isinstance(t, str) for t in files.values()):
        raise HostError('a publishing operation returns {"files": {name: text}}')
    rid = request['request_id']
    intent_id = f'{rid}:{node}:g{generation}'
    destination = Path('deliveries') / rid / f'{node}-g{generation}'
    existing = {e['intent']: e for e in flow.effects()}.get(intent_id)
    if existing is None:
        artifacts = {name: {'sha256': _sha(text), 'text': text} for name, text in sorted(files.items())}
        manifest = {'schema': 'akor.delivery-manifest/1', 'workflow': request.get('workflow'),
                    'workflow_digest': request.get('workflow_digest'), 'request_id': rid, 'intent': intent_id,
                    'created_at': round(flow.clock(), 3), 'destination': destination.as_posix(),
                    'artifacts': {k: v['sha256'] for k, v in artifacts.items()},
                    'sources': {s: {'revision': r, 'sha256': flow.source(s, r)['sha256']}
                                for s, r in sorted(cites.items())},
                    'acceptances': {n: {'seq': a['seq'], 'generation': a['generation'], 'evidence': a['evidence']}
                                    for n, a in sorted(current.items())}}
        text = J(manifest) + '\n'
        artifacts['manifest.json'] = {'sha256': _sha(text), 'text': text}
    else:
        artifacts = existing['files']
        if any(artifacts.get(k, {}).get('sha256') != _sha(t) for k, t in files.items()):
            stored = json.loads(artifacts['manifest.json']['text'])['sources']
            now = {s: {'revision': r, 'sha256': flow.source(s, r)['sha256']} for s, r in sorted(cites.items())}
            if existing['state'] != 'delivered' and stored != now:
                raise SupersededIntent(intent_id)  # legitimately different inputs, not a nondeterministic recompute
            flow.effect_state(intent_id, 'conflict', {'reason': 'recomputed artifacts differ from the intent'})
            raise HostError('recomputed artifacts differ from the stable intent')
    record = flow.intent(intent_id, node, generation, destination.as_posix(), artifacts)
    target_dir = Path(settings.workspace) / record['destination']
    target_dir.mkdir(parents=True, exist_ok=True)
    reconciled = []
    # The manifest goes last: its presence means every artifact it names was published first.
    for name in sorted(record['files'], key=lambda k: k == 'manifest.json'):
        item = record['files'][name]
        path = target_dir / name
        if path.exists():
            if _sha(path.read_bytes()) != item['sha256']:
                flow.effect_state(intent_id, 'conflict', {'file': name})
                raise HostError(f'{name} exists at the destination with other content')
            reconciled.append(name)
        else:
            publish(path, item['text'].encode('utf-8'))
    flow.effect_state(intent_id, 'exported', {'reconciled': reconciled})
    oz_fault.point('flow.publish.after_manifest')
    outputs = request['graph']['outputs']
    target = next((t for t, n in outputs.items() if n == node), node)
    result = {'intent': intent_id, 'destination': record['destination'],
              'artifacts': {k: v['sha256'] for k, v in record['files'].items()}}
    return result, {'intent': intent_id, 'target': target, 'manifest_sha256': record['files']['manifest.json']['sha256']}


def _stage_pins(flow: Flow, op_name: str) -> dict:
    """(node, generation) -> the stage submission that first carried that logical job (its full membership, texts and
    generations, as recorded at submission). Submissions recorded without texts pin nothing."""
    pins = {}
    for e in flow.events():
        x = e['details']
        if e['event'] != 'stage_submitted' or x.get('op') != op_name or 'texts' not in x:
            continue
        for node in x['members']:
            pins.setdefault((node, x['generations'][node]), x)
    return pins


def _run_stage(flow, request, settings, op, group, descriptors, current, values, remaining, call_timeout, admit_call,
               memo_store, refused=None) -> dict | None:
    """One model stage. A logical job (flow, node, generation) belongs to exactly one stage request for as long as it
    lives (foundation clauses 1 to 3): a pending job that was already submitted is resubmitted under that same request,
    with its original membership, so its attempt allowance, terminal failure record, awaiting candidate and any
    adoptable capture stay where they are; only the stage deadline is the current one. A job whose resolved input
    changed under the same generation gets an explicit new generation (event regenerated, reason inputs_changed) and a
    new stage. Pending jobs without a submission form a new stage."""
    rid = request['request_id']
    refused = set() if refused is None else refused
    texts, inputs_acc, cites, generations = {}, {}, {}, {}
    for node in group:
        d = descriptors[node]
        ctx = HostContext(flow, node, 0)  # one read-set per node: sources it reads itself are its own citations
        try:
            text = _model_input(op, d['bindings'], values, ctx)
        except HostError as exc:
            return {'reason': 'binding_failed', 'node': node, 'detail': str(exc)}
        texts[node] = text
        inputs_acc[node] = {dep: current[dep]['seq'] for dep in d['deps']}
        cites[node] = {}
        for dep in d['deps']:
            cites[node].update(current[dep]['cites'])
        cites[node].update(ctx.reads)
        generations[node] = _generation(flow, node, descriptors)
    pins = _stage_pins(flow, op.name)
    pinned = {}
    for node in group:
        stage = pins.get((node, generations[node]))
        if stage is not None and stage['texts'][node] != texts[node]:
            # Clause 1: changed inputs need an explicit new logical job, never a silent reuse or replacement.
            generations[node] = flow.regenerate(node, reason='inputs_changed')
            descriptors[node]['generation'] = generations[node]
            stage = None
        if stage is not None:
            pinned[node] = stage
    deadline = max(1, min(3600, int(remaining)))
    if pinned:
        stage = pinned[next(n for n in group if n in pinned)]
        group = [n for n in group if pinned.get(n) is stage]
        req = _stage_request(rid, op, stage['members'], stage['texts'], stage['generations'], deadline, call_timeout,
                             settings.model, settings.max_input_tokens)
        if req['request_id'] != stage['request_id']:
            return {'reason': 'stage_identity_changed', 'stage': stage['request_id'], 'nodes': group}
        submission = {'resumed': True}
    else:
        req = _stage_request(rid, op, group, texts, generations, deadline, call_timeout, settings.model,
                             settings.max_input_tokens)
        submission = {'members': group, 'texts': {n: texts[n] for n in group},
                      'generations': {n: generations[n] for n in group}}
    run_dir = Path('do') / req['request_id']
    before = {d['receipt'] for d in stage_launches(Path(settings.workspace) / run_dir)}
    with flow.tx():
        flow.event('stage_submitted', op=op.name, nodes=group, request_id=req['request_id'],
                   run_dir=run_dir.as_posix(), **submission)
    memo = ({'store': memo_store, 'namespace': settings.namespace, 'ops': [op.name]}
            if op.memo and memo_store is not None and settings.namespace else None)
    quota = {'store': settings.quota, 'group': settings.quota_group} if settings.quota is not None else None
    result = do(req, workspace=settings.workspace, adapter=settings.adapter, route=settings.route,
                registry=settings.checks_registry, memo=memo, quota=quota, admit=admit_call,
                response_check=settings.response_check, packet_sizes=settings.packet_sizes,
                experimental_sizes=settings.experimental_sizes)
    launched = [d for d in stage_launches(Path(settings.workspace) / run_dir) if d['receipt'] not in before]
    with flow.tx():
        flow.event('stage', op=op.name, nodes=group, request_id=req['request_id'], run_dir=run_dir.as_posix(),
                   calls=result['calls'], blocker=result['blocker'], memo=result.get('memo'),
                   dispatched=[{'receipt': d['receipt'], 'jobs': [m['id'] for m in json.loads(d['members'])],
                                'packet_sha256': _sha(d['packet'])} for d in launched],
                   counts=result['counts'])
    accepted = _stage_evidence(Path(settings.workspace) / run_dir)
    unresolved = {}
    for node in group:
        outcome = result['jobs'][node]
        if outcome['status'] != 'accepted':
            unresolved[node] = outcome
            continue
        value = outcome['value']
        evidence = dict(accepted.get(node, {}), request_id=req['request_id'], run_dir=run_dir.as_posix())
        oz_fault.point('flow.before_commit')
        text = _value_text(value)
        status = flow.commit(node, generations[node], text, inputs_acc[node], cites[node], evidence)
        if status == 'committed':
            oz_fault.point('flow.committed:' + node)
            continue
        # A refused commit is retried once from the same accepted candidate with freshly resolved inputs (a changed
        # input opens a new generation above); the same refusal again blocks instead of looping.
        key = (node, generations[node], _sha(text))
        if key in refused:
            return {'reason': 'commit_refused', 'node': node, 'generation': generations[node], 'detail': status,
                    'stage': req['request_id']}
        refused.add(key)
    if unresolved:
        return {'reason': 'model_jobs_unresolved', 'stage': req['request_id'], 'jobs': unresolved,
                'stage_blocker': result['blocker']}
    return None


def _stage_evidence(run: Path) -> dict:
    out = {}
    path = run / 'inbox.sqlite'
    if not path.exists():
        return out
    db = sqlite3.connect(str(path), timeout=10)
    db.row_factory = sqlite3.Row
    try:
        for c in db.execute("SELECT job,receipt,compute_key,accept_key,verdicts FROM candidates "
                            "WHERE status='accepted' ORDER BY seq"):
            out[c['job']] = {'receipt': c['receipt'], 'compute_key': c['compute_key'], 'accept_key': c['accept_key'],
                             'checks': [f"{v['check']}@{v['version']}:{v['verdict']}"
                                        for v in json.loads(c['verdicts'])]}
    finally:
        db.close()
    return out


def _plan(flow: Flow, request: dict, settings: Settings, descriptors: list) -> dict:
    """Plan-only (C5): for every model stage, the memo decisions and packets a run on this flow's current accepted
    upstream values would need under these settings. Nothing is stored, accepted or launched."""
    if flow.info() is None:
        raise Error('plan-only needs an installed flow')
    latest = flow.latest()
    values = {n: loads(a['value']) for n, a in latest.items()}
    memo_store = MemoStore(settings.memo_store) if settings.memo_store is not None else None
    stages, misses, packets = [], 0, []
    try:
        seen = []
        for d in descriptors:
            if d['kind'] != 'model' or d['op'] in seen:
                continue
            seen.append(d['op'])
            op = settings.registry[d['op']]
            group = [x['id'] for x in descriptors if x['op'] == d['op']]
            ctx = HostContext(flow, group[0], 0)
            texts = {n: _model_input(op, next(x for x in descriptors if x['id'] == n)['bindings'], values, ctx)
                     for n in group}
            req = _stage_request(request['request_id'], op, group, texts, {n: 0 for n in group}, 3600, 300,
                                 settings.model, settings.max_input_tokens)
            memo = ({'store': memo_store, 'namespace': settings.namespace, 'ops': [op.name]}
                    if op.memo and memo_store is not None and settings.namespace else None)
            result = do(req, workspace=settings.workspace, adapter=settings.adapter, route=settings.route,
                        registry=settings.checks_registry, memo=memo, packet_sizes=settings.packet_sizes,
                        plan_only=True)
            stages.append({'op': op.name, 'plan': result['plan']})
            misses += result['plan']['misses']
            packets += result['plan']['packets']
    finally:
        if memo_store is not None:
            memo_store.close()
    return {'schema': RESULT_SCHEMA, 'status': 'planned', 'misses': misses, 'packets': packets, 'launched': 0,
            'stages': stages}


def _result(flow: Flow, request: dict, settings: Settings, blocker) -> dict:
    info = flow.info()
    current = flow.current()
    deliveries = {d['target']: d for d in flow.deliveries()}
    targets = {}
    for target, node in info['outputs'].items():
        d = deliveries.get(target)
        if node in current and d is not None and d['intent'] == loads(current[node]['value']).get('intent'):
            value = loads(current[node]['value'])
            targets[target] = {'status': 'delivered', 'weight': 1, 'destination': value['destination'],
                               'artifacts': value['artifacts'], 'delivered_at': d['at'],
                               'on_time': d['at'] <= info['deadline_at'], 'cites': d['cites']}
        else:
            targets[target] = {'status': 'unresolved', 'weight': 1}
    usage = flow_usage(settings.workspace, request['request_id'])
    return {'schema': RESULT_SCHEMA,
            'status': 'delivered' if all(t['status'] == 'delivered' for t in targets.values()) else 'incomplete',
            'targets': targets, 'blocker': blocker, 'launches': usage['launches'],
            'accounting': {'tokens_known': usage['tokens_known'], 'calls_without_usage': usage['calls_without_usage'],
                           'coverage': 'complete' if usage['calls_without_usage'] == 0 else 'incomplete'},
            'flow': {'request_id': request['request_id'], 'request_sha256': info['request_sha256'],
                     'created_at': info['created_at'], 'deadline_at': info['deadline_at'],
                     'generations': {d['id']: d['generation'] for d in flow.descriptors()},
                     'revisions': flow.revisions()}}


def export(flow: Flow, workspace: Path) -> dict:
    """The execution record: graph and route digests, source revisions, node generations and acceptances, stage
    packets and captures, memo decisions, effects, launches, accounting and delivery timestamps. SQLite stays the
    authority; this is a replayable export."""
    info = flow.info()
    stages = []
    for e in flow.events():
        if e['event'] != 'stage':
            continue
        run = Path(workspace) / e['details']['run_dir']
        dispatches = []
        for d in stage_launches(run):
            capture = run / 'captures' / f"{d['receipt']}.done"
            dispatches.append({'receipt': d['receipt'], 'state': d['state'], 'route': json.loads(d['route']),
                               'members': [m['id'] for m in json.loads(d['members'])], 'packet': d['packet'],
                               'process': json.loads(d['process']) if d['process'] else None,
                               'capture': capture.relative_to(workspace).as_posix() if capture.exists() else None,
                               'capture_sha256': _sha(capture.read_bytes()) if capture.exists() else None})
        stages.append(dict(e['details'], seq=e['seq'], dispatches=dispatches,
                           accounting=_accounting(run, stage_launches(run))))
    return {'schema': 'akor.execution-record/1', 'request_id': info['request_id'],
            'request_sha256': info['request_sha256'], 'graph_sha256': _sha(J(info['request']['graph'])),
            'workflow_digest': info['request'].get('workflow_digest'), 'created_at': info['created_at'],
            'deadline_at': info['deadline_at'],
            'sources': [{k: (v if k != 'bytes' else None) for k, v in dict(r).items() if k != 'bytes'}
                        for r in flow.db.execute('SELECT name,revision,sha256,at FROM sources ORDER BY name,revision')],
            'nodes': [{'id': d['id'], 'op': d['op'], 'identity': d['identity'], 'generation': d['generation']}
                      for d in flow.descriptors()],
            'acceptances': [dict(a, value=None) for a in flow.latest().values()],
            'effects': [dict(e, files={k: v['sha256'] for k, v in e['files'].items()}) for e in flow.effects()],
            'deliveries': flow.deliveries(), 'stages': stages, 'events': flow.events()}
