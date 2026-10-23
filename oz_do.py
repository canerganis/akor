"""oz do: one bounded foreground fan-out over the existing inbox, worker and OZ/1g wire (foundation record clause 10).

A request names a shared goal, operation instructions, reference texts and jobs that apply one operation to listed
references. Each request gets its own run directory, workspace/do/<request_id>/, which is an ordinary AKOR workspace
(oz.json, inbox.sqlite, calls.jsonl), so `oz status`, `oz inspect` and `oz retry` work on it too. References are
loaded by host read jobs whose accepted result is the reference text; each job is a literal operation (the
instruction text) that depends on its references, so the shipped renderer puts the instruction in ops and the texts in
refs. Nothing on the model wire is new: the system text, packet grammar and reply parser are the shipped ones.

Resubmitting the same request (same request_id and work) posts nothing new and never calls a model for a job that
is already settled. The same request_id with different work is refused before anything runs.

"profile": "oz1g-selective-v1" (opt-in; the default stays oz1g-header) pins the selective host acceptance profile and
optional per-operation "checks" on every job (oz_accept), runs the adapter under the durable runner (captures in
<run_dir>/captures), and makes each foreground call a new coordinator epoch that first recovers earlier dispatches.

A reference may also be {"value": <JSON value>} (opt-in; strings and {"path"} keep their meaning): the packet then
carries that JSON value itself in refs (an array as an array, "unknown" as a JSON string), its compact JSON is the
reference text for checks and memo identity, and its source label is "value".
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid
from dataclasses import replace

from oz import Channel, Error, Reference
from oz_accept import HEADER, PROFILES, REGISTRY, SELECTIVE, compute_key, job_inputs, pin, run_checks, summary
from oz_batch import WIRE, J, render, valid_id
from oz_memo import MemoStore, sha256 as text_sha256
from oz_reply import ERROR_CODES, USAGE_FIELDS, RawJSON, loads
from oz_runtime import Inbox
from oz_worker import StdioAdapter, Worker, execution_route
from oz_workspace import Workspace, adapter_from_file

REQUEST_SCHEMA = 'oz.do/1'
RESULT_SCHEMA = 'oz.do.result/1'
# OZ/1g size cells as data: one row per (model, job count per call) with its gate result and evidence. A new gate adds
# rows here; nothing else changes. "pass" rows are qualified, "fail" rows are refused even when experimental work is
# authorized, and any other (model, size) is experimental. oz do checks only the declared model and the packet size:
# the CLI version, effort, adapter and workload class each row was qualified under are not verified at dispatch.
GATES = 'docs/design/foundation-2026-10-23/size-gates-results.md'
SCOPE = 'OZ9.md qualification scope'
CELLS = (
    *(('claude-sonnet-5-5', n, 'pass', GATES if n < 32 else SCOPE) for n in (1, 4, 16, 32, 64)),
    ('claude-opus-5-5', 1, 'fail', GATES + ' (reasoning line before the OZ/1g header)'),
    *(('claude-opus-5-5', n, 'pass', GATES if n < 64 else SCOPE) for n in (4, 16, 64)),
    *(('claude-haiku-5-5', n, 'pass', GATES if n < 64 else SCOPE) for n in (1, 4, 16, 64)),
    ('claude-fable-5-1', 64, 'pass', SCOPE),
)
QUALIFICATION = {'checked': 'declared model and packet size',
                 'not_checked': 'CLI version (gates: 2.1.306), effort (default), adapter, workload class (standard)',
                 'record': GATES}
MAX_JOBS = 256
MAX_REF_BYTES = 65536
MAX_MESSAGE = 300
OPTIONS = {'v', 'request_id', 'goal', 'ops', 'refs', 'jobs', 'max_attempts', 'model', 'allow_experimental',
           'deadline_seconds', 'call_timeout_seconds', 'max_jobs_per_call', 'max_input_tokens', 'max_inline_bytes',
           'profile', 'checks'}
_NO_VALUE = object()  # a text reference (string or file): no JSON value form
FAILURE = re.compile(r'(' + '|'.join(ERROR_CODES) + r'): (.*)', re.S)


def size_profile(model: str | None, size: int, cells=CELLS) -> str:
    """qualified_cell for a passed (model, size) cell, unsupported for a failed one, else experimental."""
    gate = next((row[2] for row in cells if row[0] == model and row[1] == size), None)
    return {'pass': 'qualified_cell', 'fail': 'unsupported'}.get(gate, 'experimental')


def _number(value, low, high, name, integer=False):
    if type(value) not in ({int} if integer else {int, float}) or not low <= value <= high:
        raise Error(f'{name} must be {"an integer " if integer else ""}{low}..{high}')
    return value


def _inside(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if path != root and root not in path.parents:
        raise Error(f'reference path outside the authorized directory: {name}')
    return path


def normalize(request: dict, *, allow: Path, config: dict, registry=None) -> dict:
    """Validated request with file references read inside allow. Raises Error before anything is stored."""
    if not isinstance(request, dict) or set(request) - OPTIONS:
        raise Error('request keys must be among: ' + ', '.join(sorted(OPTIONS)))
    if request.get('v', REQUEST_SCHEMA) != REQUEST_SCHEMA:
        raise Error(f'unsupported request schema; expected {REQUEST_SCHEMA}')
    goal, ops, refs, jobs = (request.get(k) for k in ('goal', 'ops', 'refs', 'jobs'))
    if not isinstance(goal, str) or not goal.strip():
        raise Error('goal must be a nonblank string')
    if (not isinstance(ops, dict) or not ops or any(not valid_id(k) for k in ops)
            or any(not isinstance(v, str) or not v.strip() or len(v.encode('utf-8')) > 8191 for v in ops.values())):
        raise Error('ops maps names ([A-Za-z0-9_-]) to nonblank instruction texts of at most 8191 UTF-8 bytes')
    refs = {} if refs is None else refs
    if not isinstance(refs, dict) or any(not valid_id(k) or len(k) > 60 for k in refs):
        raise Error('refs maps names ([A-Za-z0-9_-], at most 60 characters) to text or {"path": ...}')
    texts = {}
    for name, value in refs.items():
        data = _NO_VALUE
        if isinstance(value, str):
            text, source = value, 'inline'
        elif isinstance(value, dict) and set(value) == {'path'} and isinstance(value['path'], str) and value['path']:
            path = _inside(allow, value['path'])
            try:
                text = path.read_bytes().decode('utf-8')
            except (OSError, UnicodeError):
                raise Error(f'reference {name}: cannot read UTF-8 file {value["path"]}') from None
            source = path.relative_to(allow).as_posix()
        elif isinstance(value, dict) and set(value) == {'value'}:
            # Opt-in JSON value form: the packet carries this value itself (for example ["12.48 mm","12.52 mm"]),
            # not a string holding its JSON text. Its compact JSON is the text, the source label says "value".
            data = value['value']
            try:
                text = J(data)
                data = loads(text)  # the carried value is exactly what the text, its digest and the identity say
            except (Error, TypeError, ValueError, RecursionError):
                raise Error(f'reference {name}: value must be one finite JSON value') from None
            if data is None or isinstance(data, str) and not data.strip():
                raise Error(f'reference {name}: value must not be null or blank')
            source = 'value'
        else:
            raise Error(f'reference {name} must be a string, {{"path": "..."}} or {{"value": <JSON value>}}')
        if not text.strip() or len(text.encode('utf-8')) > MAX_REF_BYTES:
            raise Error(f'reference {name} must be nonblank and at most {MAX_REF_BYTES} UTF-8 bytes')
        texts[name] = {'text': text, 'source': source + '@sha256:' + hashlib.sha256(text.encode('utf-8')).hexdigest()}
        if data is not _NO_VALUE:
            texts[name]['value'] = data
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= MAX_JOBS:
        raise Error(f'jobs must be a list of 1..{MAX_JOBS} jobs')
    rows = []
    for job in jobs:
        if isinstance(job, dict) and set(job) <= {'id', 'op', 'refs'} and {'id', 'op'} <= set(job):
            row = [job['id'], job['op'], *job.get('refs', [])] if isinstance(job.get('refs', []), list) else None
        else:
            row = job if isinstance(job, list) else None
        if (not row or len(row) < 2 or not valid_id(row[0]) or row[1] not in ops
                or any(r not in texts for r in row[2:]) or len(set(row[2:])) != len(row) - 2 or len(row) > 66):
            raise Error('each job is [id, op, ref...] or {"id","op","refs"} with a known op and distinct known refs')
        rows.append([row[0], row[1], *row[2:]])
    ids = [r[0] for r in rows]
    if len(set(ids)) != len(ids):
        raise Error('duplicate job ID')
    clash = set(ids) & {'ref-' + n for n in texts}
    if clash:
        raise Error('job IDs must not equal a reference job ID: ' + ', '.join(sorted(clash)))
    model = request.get('model')
    if model is not None and (not isinstance(model, str) or not model):
        raise Error('model must be a nonempty model ID string')
    if type(request.get('allow_experimental', False)) is not bool:
        raise Error('allow_experimental must be true or false')
    deadline = _number(request.get('deadline_seconds', 600), 1, 3600, 'deadline_seconds')
    request_id = request.get('request_id')
    if request_id is not None and not valid_id(request_id):
        raise Error('request_id must be 1..64 characters of [A-Za-z0-9_-]')
    work = {'goal': goal, 'ops': {k: ops[k] for k in sorted({r[1] for r in rows})},
            'refs': {n: texts[n]['source'] for n in sorted({x for r in rows for x in r[2:]})}, 'jobs': rows,
            'max_attempts': _number(request.get('max_attempts', 2), 1, 10, 'max_attempts', True)}
    profile, checks = request.get('profile', HEADER), request.get('checks')
    if profile not in PROFILES:
        raise Error('profile must be one of ' + ', '.join(PROFILES))
    if checks is not None:
        if profile != SELECTIVE:
            raise Error(f'checks need "profile": "{SELECTIVE}"')
        if not isinstance(checks, dict) or any(k not in ops for k in checks):
            raise Error('checks maps operation names to lists of check specs')
    if profile != HEADER:
        # Only a non-default profile enters the work (and its digest), so default requests keep their identity.
        work['profile'] = profile
        work['checks'] = {k: list(pin(checks[k], registry)) for k in work['ops'] if checks and checks.get(k)}
    forms = sorted(n for n in work['refs'] if 'value' in texts[n])
    if forms:
        # A {"value": ...} ref is a JSON array/object/number on the wire, a text ref a string: the form is part of the
        # work (a file named "value" holding the same text has the same source label). Only requests that use value
        # refs gain this key, so default requests keep their identity.
        work['ref_forms'] = {n: 'value' for n in forms}
    digest = hashlib.sha256(J(work).encode('utf-8')).hexdigest()
    return dict(work=work, texts=texts, sha256=digest, request_id=request_id or 'h' + digest[:16], model=model,
                allow_experimental=request.get('allow_experimental', False), deadline=deadline,
                call_timeout=_number(request.get('call_timeout_seconds', 300), 1, 3600, 'call_timeout_seconds'),
                per_call=_number(request.get('max_jobs_per_call', config['batch_size']), 1, 64,
                                 'max_jobs_per_call', True),
                max_tokens=_number(request.get('max_input_tokens', config['max_tokens']), 1, 1000000,
                                   'max_input_tokens', True),
                max_inline=_number(request.get('max_inline_bytes', 4096), 0, 65536, 'max_inline_bytes', True))


def _channels(req: dict) -> tuple[Channel, Channel]:
    """Host channel for the reference reads and worker channel for the jobs: same session, task and revision."""
    names = list(req['work']['refs'])
    refs = [Reference(i + 1, 'source', req['texts'][n]['text'], req['texts'][n]['source']) for i, n in enumerate(names)]
    # A channel needs an active reference; a request without references gets a placeholder that never reaches a packet.
    refs = refs or [Reference(1, 'reason', 'oz do: this request has no references')]
    base = dict(session='do-' + req['request_id'], task='do', revision=1, sender='caller', goal=req['work']['goal'],
                references=refs, active=1)
    return Channel(recipient='host', **base), Channel(recipient='worker', **base)


def _create_run(root: Path, req: dict, config: dict, registry=None) -> Path:
    """The run directory, created once; an existing one must hold exactly this work."""
    run = root / 'do' / req['request_id']
    run.mkdir(parents=True, exist_ok=True)
    stored = {'v': REQUEST_SCHEMA, 'request_id': req['request_id'], 'sha256': req['sha256'], 'work': req['work']}
    try:
        with (run / 'request.json').open('x', encoding='utf-8') as file:
            file.write(J(stored) + '\n')
    except FileExistsError:
        previous = loads((run / 'request.json').read_text(encoding='utf-8'))
        if previous.get('sha256') != req['sha256']:
            raise Error(f'request_id {req["request_id"]} already names different work; use a new request_id') from None
    refs, work = _channels(req)
    space = dict(version=1, channels={'worker': work.snapshot(), 'refs': refs.snapshot()},
                 encodings=config['encodings'], max_tokens=req['max_tokens'], batch_size=req['per_call'])
    path = run / 'oz.json'
    if not path.exists():
        temp = run / ('oz-' + uuid.uuid4().hex + '.tmp')
        temp.write_text(json.dumps(space, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temp, path)
    with Inbox(run / 'inbox.sqlite') as box:
        names = list(req['work']['refs'])
        for i, name in enumerate(names):
            box.post(refs, 'ref-' + name, f'r{i + 1}', binding=refs.binding, max_attempts=1)
        for mid, op, *uses in req['work']['jobs']:
            box.post(work, mid, ':' + req['work']['ops'][op], binding=work.binding,
                     after=['ref-' + n for n in uses], max_attempts=req['work']['max_attempts'],
                     profile=req['work'].get('profile', HEADER), checks=req['work'].get('checks', {}).get(op),
                     registry=registry)
    return run


def _read_refs(box: Inbox, channel: Channel, texts: dict):
    """Host read: the accepted result of ref-<name> is the reference text itself (no model, no adapter); a
    {"value": ...} reference also keeps its JSON value, which the packet then carries as that value."""
    while True:
        delivery = box.claim(channel, owner='host', kind='work', limit=64, lease_seconds=30)
        if delivery is None:
            return
        box.complete(delivery, {j.id: texts[j.id[4:]]['text'] for j in delivery.jobs},
                     values={j.id: texts[j.id[4:]]['text'] for j in delivery.jobs if 'value' in texts[j.id[4:]]})


def _accounting(run: Path, journal=()) -> dict:
    """Request totals from the run's call ledger (all invocations, failed calls included) and dispatch log. With a
    dispatch journal (oz1g-selective-v1), journaled calls missing from the ledger are counted too, a captured envelope
    supplies usage a crash kept out of the ledger, and an uncertain dispatch keeps the usage coverage incomplete."""
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


def _outcome(mid: str, row: dict | None, blocker: dict | None, now: float, run: Path, root: Path, max_inline: int,
             evidence: dict | None = None):
    if row is None:
        return {'status': 'unresolved', 'reason': 'not_posted'}
    if row['state'] == 'done' and evidence is not None:
        return dict(_outcome(mid, row, blocker, now, run, root, max_inline), evidence=evidence)
    if row['state'] == 'checking':
        return {'status': 'unresolved', 'reason': 'awaiting_checks', 'detail': (row['error'] or '')[:MAX_MESSAGE]}
    if row['state'] == 'quarantined':
        return {'status': 'quarantined', 'reason': (row['error'] or '')[:MAX_MESSAGE], 'attempts': row['attempts']}
    if row['state'] == 'done':
        # The stored bytes of the accepted value, unchanged (clause 12); oz_reply.dumps writes them verbatim.
        value = RawJSON(row['result_json']) if row['result_json'] is not None else row['result']
        text = J(value)
        size = len(text.encode('utf-8'))
        if size <= max_inline:
            return {'status': 'accepted', 'value': value}
        path = run / 'values' / (mid + '.json')
        path.parent.mkdir(exist_ok=True)
        if not path.exists() or path.read_text(encoding='utf-8') != text:
            path.write_text(text, encoding='utf-8')
        return {'status': 'accepted', 'value_file': path.relative_to(root).as_posix(), 'bytes': size,
                'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}
    error = row['error'] or ''
    if row['state'] == 'failed':
        match = FAILURE.fullmatch(error)
        if match:
            return {'status': 'failed', 'code': match.group(1), 'message': match.group(2)[:MAX_MESSAGE]}
        if error.startswith('pinned_computation_mismatch:'):
            return {'status': 'unresolved', 'reason': 'pinned_computation_mismatch', 'last_error': error[:MAX_MESSAGE],
                    'attempts': row['attempts']}
        return {'status': 'unresolved', 'reason': 'attempts_exhausted', 'last_error': error[:MAX_MESSAGE],
                'attempts': row['attempts']}
    if row['state'] == 'leased':
        return ({'status': 'unresolved', 'reason': 'in_flight', 'lease_seconds_left': round(row['deadline'] - now, 1)}
                if row['deadline'] > now else {'status': 'unresolved', 'reason': 'lease_expired'})
    reason = dict(blocker or {'reason': 'not_dispatched'})
    if row['available_at'] > now:
        reason = {'reason': 'backoff'}
    if error:
        reason['last_error'] = error[:MAX_MESSAGE]
    return dict({'status': 'unresolved', 'attempts': row['attempts']}, **reason)


def _render_inputs(channel: Channel, req: dict, mid: str):
    """The model-visible inputs of one job exactly as a packet carries them (the instruction and each reference text,
    cut from the rendered body bytes). Packet siblings do not enter them (the declared independence contract)."""
    row = next(r for r in req['work']['jobs'] if r[0] == mid)
    packet = render(channel, [(mid, ':' + req['work']['ops'][row[1]])], counters=[len],
                    handoffs=[(mid, 'ref-' + n, req['texts'][n].get('value', req['texts'][n]['text']))
                              for n in row[2:]])
    return job_inputs(packet.text, packet.job_map)[mid]


def _provenance(root: Path, entry: dict, key: str, route: dict) -> str | None:
    """None when the entry's provenance is an accepted candidate of a real dispatch on this route with these value
    bytes in its run's authoritative SQLite, else why not."""
    p = entry['provenance']
    if not isinstance(p, dict) or not isinstance(p.get('run_dir'), str):
        return 'provenance missing'
    inbox = (root / p['run_dir']).resolve() / 'inbox.sqlite'
    if root not in inbox.parents or not inbox.exists():
        return 'provenance run not found'
    db = sqlite3.connect(str(inbox), timeout=10)
    try:
        c = db.execute('SELECT value,compute_key,status,receipt FROM candidates WHERE seq=? AND job=?',
                       (p.get('candidate'), p.get('job'))).fetchone()
        d = db.execute('SELECT route FROM dispatches WHERE receipt=?', (p.get('receipt'),)).fetchone()
    except sqlite3.Error:
        return 'provenance unreadable'
    finally:
        db.close()
    if c is None or c[2] != 'accepted' or c[3] != p.get('receipt') or c[1] != key or c[0] != entry['value']:
        return 'provenance does not hold this accepted value'
    if d is None or json.loads(d[0]) != route:
        return 'provenance dispatch ran on another route'
    return None


def memo_lookup(store: MemoStore, namespace: str, key: str, route: dict, inputs, checks, registry, root: Path):
    """(decision, entry, detail) for one consumer job (clause 4): hit (detail: verdicts), pending (a check is
    inconclusive; the hit waits and nothing is dispatched for it) or miss (detail: why each entry was refused).
    Integrity, revocation, route, provenance and the consumer's own pinned checks, rerun on the stored value against
    the consumer's inputs, must all hold for a hit."""
    refused = []
    for entry in store.entries(namespace, key):
        why = ('revoked: ' + entry['revoked'] if entry['revoked'] else
               'integrity: value digest mismatch' if text_sha256(entry['value']) != entry['value_sha256'] else
               'route mismatch' if entry['route'] != route else _provenance(root, entry, key, route))
        if why is None:
            verdicts = run_checks(entry['value'], inputs, checks, registry)
            if any(v['verdict'] == 'inconclusive' for v in verdicts):
                return 'pending', entry, verdicts
            if all(v['verdict'] == 'pass' for v in verdicts) and any(v['job_bound'] for v in verdicts):
                return 'hit', entry, verdicts
            why = 'revalidation failed: ' + ', '.join(v['check'] for v in verdicts if v['verdict'] != 'pass')
        refused.append({'entry': entry['id'], 'reason': why})
    return 'miss', None, refused


def plan_sizes(misses: int, sizes) -> list:
    """Packet sizes for misses jobs: the largest allowed size that fits, repeatedly (no padding, no other sizes)."""
    out = []
    while misses > 0:
        fit = max((s for s in sizes if s <= misses), default=None) if sizes else misses
        if fit is None:
            return out + [misses]
        out.append(fit)
        misses -= fit
    return out


def do(request, *, workspace='.', adapter=None, allow=None, clock=time.monotonic, route=None, registry=None,
       memo=None, quota=None, admit=None, response_check=None, packet_sizes=None, experimental_sizes=(),
       plan_only=False) -> dict:
    """Run one oz do request to completion or its deadline and return the compact result (see USAGE.md).

    request is a dict or JSON text. adapter is the adapter JSON file (as for `oz run`) or a callable adapter with a
    capabilities attribute; a callable is not interrupted at the deadline. allow is the directory reference paths
    must resolve inside (default: the workspace root).

    Host-side options (Python only, never read from the request; all off by default, so the shipped behavior is
    unchanged), each needing "profile": "oz1g-selective-v1" except route and registry: route pins further
    execution-route fields (effort, cli_version, adapter, parser) next to the request's model; registry is the check
    registry. memo = {"store": MemoStore, "namespace": str, "ops": [op names]} makes those operations memo-eligible
    (clause 4): an eligible job whose computation already has an accepted entry is accepted without a call once
    integrity, provenance and its own pinned checks hold, and every accepted call result is published. quota =
    {"store": oz_quota.Quota, "group": str} reserves the quota-group slot before each call. admit(size) returns None
    or a blocker before each call (budget, deadline, route rechecks). response_check(dispatch) may refuse every
    candidate of a captured call (for example an unexpected model in the retained envelope). packet_sizes limits
    packets to those job counts (the largest that fits); experimental_sizes are labeled experimental even where a
    qualified cell exists (a packet composition the gate did not sample). plan_only makes the memo decisions and the
    packet plan without storing, posting, accepting or calling anything."""
    started = clock()
    if isinstance(request, str):
        request = loads(request)
    space = Workspace(Path(workspace))
    root = space.root
    allow = Path(allow).resolve() if allow is not None else root
    registry = REGISTRY if registry is None else registry
    req = normalize(request, allow=allow, config=space.config, registry=registry)
    if adapter is None and not plan_only:
        raise Error('an explicit adapter is required (adapter JSON file or callable)')
    selective = req['work'].get('profile') == SELECTIVE
    if (memo is not None or quota is not None or packet_sizes or plan_only) and not selective:
        raise Error(f'memo, quota, packet sizes and plan-only need "profile": "{SELECTIVE}"')
    if packet_sizes is not None and (not packet_sizes or any(type(n) is not int or not 1 <= n <= 64
                                                             for n in packet_sizes)):
        raise Error('packet_sizes must list job counts 1..64')
    route_fields = dict({'model': req['model']}, **(route or {}))
    if plan_only:
        return _plan_only(req, root, route_fields, registry, memo, packet_sizes, clock() - started, adapter)
    run = _create_run(root, req, space.config, registry)
    runspace = Workspace(run)
    refs, work = runspace.channel('refs'), runspace.channel('worker')
    ids = [r[0] for r in req['work']['jobs']]
    calls, blocker = [], None
    memo_report = {}

    def file_adapter(timeout):
        made = adapter_from_file(Path(adapter), timeout=timeout)
        # The selective profile runs the adapter under the durable runner (clause 5).
        return replace(made, capture_dir=run / 'captures') if selective else made

    with runspace.inbox() as box:
        _read_refs(box, refs, req['texts'])
        counters = runspace.counters()
        callable_adapter = not isinstance(adapter, (str, Path))
        worker = Worker(box, work, adapter if callable_adapter else file_adapter(1),
                        counters=counters, owner='do', batch_size=req['per_call'], timeout=req['call_timeout'],
                        max_tokens=req['max_tokens'], retry_delay=0, ledger_path=run / 'calls.jsonl',
                        tokenizer=space.config['encodings'][0],
                        # Each selective foreground call is a new coordinator epoch: an older one cannot commit.
                        epoch=box.take_over() if selective else None, route=route_fields, registry=registry,
                        response_check=response_check)
        if memo is not None:
            # Earlier dispatches are reconciled first, so a captured reply is adopted rather than replaced by a memo.
            worker.recover()
            blocker = _memo_phase(box, work, req, root, run, worker, memo, registry, memo_report)
        while blocker is None:
            if selective:
                worker.recover()
            remaining = req['deadline'] - (clock() - started)
            plan = box.plan(work, counters=counters, limit=req['per_call'], max_tokens=req['max_tokens'],
                            receipt=box.next_receipt())
            if not plan.jobs:
                if plan.deferred:
                    blocker = {'reason': 'input_budget', 'max_input_tokens': req['max_tokens']}
                break
            if remaining < 1:
                blocker = {'reason': 'deadline'}
                break
            size = len(plan.packet.job_map)
            if packet_sizes:
                fit = max((n for n in packet_sizes if n <= size), default=None)
                if fit is None:
                    blocker = {'reason': 'unsupported_size', 'size': size, 'model': req['model']}
                    break
                worker.options['limit'] = fit
                if fit != size:
                    plan = box.plan(work, counters=counters, limit=fit, max_tokens=req['max_tokens'],
                                    receipt=box.next_receipt())
                    size = len(plan.packet.job_map)
            profile = 'experimental' if size in experimental_sizes else size_profile(req['model'], size)
            if profile == 'unsupported' or profile == 'experimental' and not req['allow_experimental']:
                blocker = {'reason': ('unsupported_size' if profile == 'unsupported'
                                      else 'experimental_size_not_authorized'), 'size': size, 'model': req['model']}
                break
            if admit is not None:
                blocker = admit(size)
                if blocker is not None:
                    break
            if not callable_adapter:
                worker.adapter = file_adapter(min(req['call_timeout'], remaining))
            slot, receipt = None, box.next_receipt()
            if quota is not None:
                slot = quota['store'].acquire(quota['group'], run_dir=run, receipt=receipt)
                if slot['status'] != 'acquired':
                    blocker = {'reason': 'quota_slot_held', 'detail': slot['reason']}
                    break
            report = worker.run_once()
            if slot is not None:
                held = box.dispatch(receipt)
                # Released only once the call is reconciled; an uncertain call keeps its slot (clauses 5 and 7).
                if held is None or held['state'] in ('captured', 'failed_call', 'not_launched'):
                    quota['store'].release(quota['group'], slot['token'])
            if report['status'] == 'fenced':
                blocker = {'reason': 'coordinator_superseded'}
                break
            if report['status'] in ('idle', 'waiting'):
                break
            entry = {'jobs': size, 'profile': profile, 'status': report['status']}
            if report.get('error_code'):
                entry['error_code'] = report['error_code']
            if report.get('response_check'):
                entry['response_check'] = report['response_check']
            calls.append(entry)
            if report.get('call_id'):
                with (run / 'do.jsonl').open('a', encoding='utf-8') as file:
                    file.write(J({'call_id': report['call_id'], 'jobs': size, 'profile': profile,
                                  'model': req['model']}) + '\n')
        if memo is not None:
            _memo_publish(box, req, root, run, memo)
        rows = box.records(ids)
        now = box.clock()
        journal = box.dispatches() if selective else []
        evidence, checks_run = {}, 0
        for c in (box.candidates() if selective else []):
            checks_run += len(c['verdicts'])
            if c['status'] == 'accepted' and c['job'] in rows:
                evidence[c['job']] = {'profile': SELECTIVE, 'summary': summary(c['verdicts']),
                                      'checks': [f"{v['check']}@{v['version']}" for v in c['verdicts']]}
                if c['receipt'].startswith('memo:'):
                    evidence[c['job']]['memo_entry'] = c['receipt'][5:]
    jobs = {mid: _outcome(mid, rows.get(mid), blocker, now, run, root, req['max_inline'], evidence.get(mid))
            for mid in ids}
    counts = {}
    for outcome in jobs.values():
        counts[outcome['status']] = counts.get(outcome['status'], 0) + 1
    accounting = _accounting(run, journal)
    result = {'schema': RESULT_SCHEMA,
              'status': 'complete' if 'unresolved' not in counts else 'incomplete',
              'counts': counts,
              'jobs': jobs,
              'evidence': ({'scope': 'per_job_checks', 'profile': SELECTIVE, 'checks_run': checks_run,
                            'id_binding': 'declared'} if selective else
                           {'scope': 'model_declared', 'checks_run': 0, 'id_binding': 'declared'}),
              'calls': calls,
              'accounting': accounting,
              # What a qualified_cell label covers, shown only when one was used.
              'qualification': QUALIFICATION if accounting['qualified_cell_calls'] else None,
              'blocker': blocker,
              'run': {'workspace': str(root), 'run_dir': run.relative_to(root).as_posix(),
                      'request_id': req['request_id'], 'request_sha256': req['sha256'], 'binding': work.binding,
                      'model': req['model'], 'elapsed_seconds': round(clock() - started, 3)}}
    if memo is not None:
        result['memo'] = memo_report
    return result


def _memo_phase(box, work, req, root, run, worker, memo, registry, report) -> dict | None:
    """Memo lookups for the request's unsettled eligible jobs before any dispatch; each hit is adopted in its own
    conditional transaction and every decision is recorded. Returns a blocker when a hit is pending revalidation."""
    store, namespace, ops = memo['store'], memo['namespace'], set(memo['ops'])
    ids = [r[0] for r in req['work']['jobs']]
    rows = box.records(ids)
    contracts = box.contracts(ids)
    route = worker._route()
    blocker = None
    for mid, op, *_ in req['work']['jobs']:
        if op not in ops or rows[mid]['state'] == 'done':
            continue
        inputs = _render_inputs(work, req, mid)
        key = compute_key(req['work']['goal'], inputs, route)
        decision, entry, detail = memo_lookup(store, namespace, key, route, inputs, contracts[mid][1], registry, root)
        reason = None
        if decision == 'hit':
            state = box.adopt_memo(mid, entry=str(entry['id']), compute_key=key, value=entry['value'],
                                   text=entry['stored'], verdicts=detail, inputs=inputs, epoch=worker.epoch)
            if state != 'done':
                decision, reason = 'refused', state
        elif decision == 'pending':
            blocker = blocker or {'reason': 'memo_revalidation_pending', 'job': mid}
        else:
            reason = J(detail) if detail else 'no entry'
        store.record(namespace, key, run.relative_to(root).as_posix() + ':' + mid, decision,
                     entry=entry['id'] if entry else None, reason=reason)
        report[mid] = {'decision': decision, 'compute_key': key, 'entry': entry['id'] if entry else None,
                       'inputs_sha256': text_sha256(J([s['refs'] for s in inputs.slots]))}
        if reason is not None:
            report[mid]['reason'] = reason
    return blocker


def _memo_publish(box, req, root, run, memo):
    """Publish every accepted candidate of a real dispatch of a memo-eligible operation (never a memo hit again)."""
    ops = set(memo['ops'])
    op_of = {r[0]: r[1] for r in req['work']['jobs']}
    for c in box.candidates(status='accepted'):
        if c['receipt'].startswith('memo:') or op_of.get(c['job']) not in ops or c['compute_key'] is None:
            continue
        d = box.dispatch(c['receipt'])
        if d is None:
            continue
        memo['store'].publish(memo['namespace'], c['compute_key'], value=c['value'], stored=c['stored'],
                              route=d['route'], checks=c['checks'], verdicts=c['verdicts'],
                              provenance={'run_dir': run.relative_to(root).as_posix(),
                                          'request_id': req['request_id'], 'receipt': c['receipt'],
                                          'candidate': c['seq'], 'job': c['job']})


def _plan_only(req, root, route, registry, memo, packet_sizes, elapsed, adapter=None) -> dict:
    """Memo decisions and the packet plan for a request, with nothing stored, posted, accepted or called. The route is
    computed as the worker computes it: a caller-pinned adapter identity, else the adapter's own name (an adapter JSON
    file runs as a StdioAdapter); with no adapter at all the identity stays unknown."""
    _, work = _channels(req)
    named = StdioAdapter if isinstance(adapter, (str, Path)) else adapter
    route = execution_route(route, named) if named is not None else {
        'adapter': route.get('adapter'), 'model': route.get('model'), 'effort': route.get('effort'),
        'cli_version': route.get('cli_version'), 'wire': WIRE,
        **({'parser': route['parser']} if route.get('parser') is not None else {})}
    checks = req['work'].get('checks', {})
    decisions, misses = {}, 0
    for mid, op, *_ in req['work']['jobs']:
        inputs = _render_inputs(work, req, mid)
        key = compute_key(req['work']['goal'], inputs, route)
        if memo is not None and op in set(memo['ops']):
            decision, entry, detail = memo_lookup(memo['store'], memo['namespace'], key, route, inputs,
                                                  checks.get(op, []), registry, root)
        else:
            decision, entry, detail = 'miss', None, 'not memo-eligible'
        decisions[mid] = {'decision': decision, 'compute_key': key, 'entry': entry['id'] if entry else None}
        if decision != 'hit':
            decisions[mid]['reason'] = detail
        misses += decision != 'hit'
    return {'schema': RESULT_SCHEMA, 'status': 'planned',
            'plan': {'memo': decisions, 'misses': misses, 'packets': plan_sizes(misses, packet_sizes), 'launched': 0},
            'run': {'request_id': req['request_id'], 'request_sha256': req['sha256'], 'model': req['model'],
                    'elapsed_seconds': round(elapsed, 3)}}
