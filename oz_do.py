"""oz do: one bounded foreground fan-out over the existing inbox, worker and OZ/1g wire (foundation record clause 10).

A request names a shared goal, operation instructions, reference texts and jobs that apply one operation to listed
references. Each request gets its own run directory, workspace/do/<request_id>/, which is an ordinary AKOR workspace
(oz.json, inbox.sqlite, calls.jsonl), so `oz status`, `oz inspect` and `oz retry` work on it too. References are
loaded by host read jobs whose accepted result is the reference text; each job is a literal operation (the
instruction text) that depends on its references, so the shipped renderer puts the instruction in ops and the texts in
refs. Nothing on the model wire is new: the system text, packet grammar and reply parser are the shipped ones.

Resubmitting the same request (same request_id and work) posts nothing new and never calls a model for a job that
is already settled. The same request_id with different work is refused before anything runs.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from oz import Channel, Error, Reference
from oz_batch import J, valid_id
from oz_reply import ERROR_CODES, USAGE_FIELDS, loads
from oz_runtime import Inbox
from oz_worker import Worker
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
           'deadline_seconds', 'call_timeout_seconds', 'max_jobs_per_call', 'max_input_tokens', 'max_inline_bytes'}
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


def normalize(request: dict, *, allow: Path, config: dict) -> dict:
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
        if isinstance(value, str):
            text, source = value, 'inline'
        elif isinstance(value, dict) and set(value) == {'path'} and isinstance(value['path'], str) and value['path']:
            path = _inside(allow, value['path'])
            try:
                text = path.read_bytes().decode('utf-8')
            except (OSError, UnicodeError):
                raise Error(f'reference {name}: cannot read UTF-8 file {value["path"]}') from None
            source = path.relative_to(allow).as_posix()
        else:
            raise Error(f'reference {name} must be a string or {{"path": "..."}}')
        if not text.strip() or len(text.encode('utf-8')) > MAX_REF_BYTES:
            raise Error(f'reference {name} must be nonblank and at most {MAX_REF_BYTES} UTF-8 bytes')
        texts[name] = {'text': text, 'source': source + '@sha256:' + hashlib.sha256(text.encode('utf-8')).hexdigest()}
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


def _create_run(root: Path, req: dict, config: dict) -> Path:
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
                     after=['ref-' + n for n in uses], max_attempts=req['work']['max_attempts'])
    return run


def _read_refs(box: Inbox, channel: Channel, texts: dict):
    """Host read: the accepted result of ref-<name> is the reference text itself (no model, no adapter)."""
    while True:
        delivery = box.claim(channel, owner='host', kind='work', limit=64, lease_seconds=30)
        if delivery is None:
            return
        box.complete(delivery, {j.id: texts[j.id[4:]]['text'] for j in delivery.jobs})


def _accounting(run: Path) -> dict:
    """Request totals from the run's call ledger (all invocations, failed calls included) and dispatch log."""
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
    calls = list(dict.fromkeys([*starts, *ends]))
    with_usage = [c for c in calls if c in ends and isinstance((ends[c].get('usage') or {}).get('raw'), dict)
                  and {'input_tokens', 'output_tokens'} <= set(ends[c]['usage']['raw'])]
    tokens = {k: sum(ends[c]['usage']['raw'].get(k, 0) for c in with_usage) for k in USAGE_FIELDS}
    coverage = 'complete' if len(with_usage) == len(calls) else 'none' if not with_usage else 'partial'
    count = lambda name: sum(1 for c in calls if profiles.get(c, 'unrecorded') == name)
    return {'calls': len(calls),
            'failed_calls': sum(1 for c in calls if c not in ends or ends[c].get('outcome') not in ('ok', 'job_error')),
            'unfinished_calls': sum(1 for c in calls if c not in ends),
            'experimental_calls': count('experimental'), 'qualified_cell_calls': count('qualified_cell'),
            'usage_coverage': coverage, 'calls_with_usage': len(with_usage),
            'tokens': tokens, 'tokens_scope': 'all calls' if coverage == 'complete' else 'calls with reported usage only'}


def _outcome(mid: str, row: dict | None, blocker: dict | None, now: float, run: Path, root: Path, max_inline: int):
    if row is None:
        return {'status': 'unresolved', 'reason': 'not_posted'}
    if row['state'] == 'done':
        value = json.loads(row['result_json']) if row['result_json'] is not None else row['result']
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


def do(request, *, workspace='.', adapter=None, allow=None, clock=time.monotonic) -> dict:
    """Run one oz do request to completion or its deadline and return the compact result (see USAGE.md).

    request is a dict or JSON text. adapter is the adapter JSON file (as for `oz run`) or a callable adapter with a
    capabilities attribute; a callable is not interrupted at the deadline. allow is the directory reference paths
    must resolve inside (default: the workspace root)."""
    started = clock()
    if isinstance(request, str):
        request = loads(request)
    space = Workspace(Path(workspace))
    root = space.root
    allow = Path(allow).resolve() if allow is not None else root
    req = normalize(request, allow=allow, config=space.config)
    if adapter is None:
        raise Error('an explicit adapter is required (adapter JSON file or callable)')
    run = _create_run(root, req, space.config)
    runspace = Workspace(run)
    refs, work = runspace.channel('refs'), runspace.channel('worker')
    ids = [r[0] for r in req['work']['jobs']]
    calls, blocker = [], None
    with runspace.inbox() as box:
        _read_refs(box, refs, req['texts'])
        counters = runspace.counters()
        callable_adapter = not isinstance(adapter, (str, Path))
        worker = Worker(box, work, adapter if callable_adapter else adapter_from_file(Path(adapter), timeout=1),
                        counters=counters, owner='do', batch_size=req['per_call'], timeout=req['call_timeout'],
                        max_tokens=req['max_tokens'], retry_delay=0, ledger_path=run / 'calls.jsonl',
                        tokenizer=space.config['encodings'][0])
        while True:
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
            profile = size_profile(req['model'], size)
            if profile == 'unsupported' or profile == 'experimental' and not req['allow_experimental']:
                blocker = {'reason': ('unsupported_size' if profile == 'unsupported'
                                      else 'experimental_size_not_authorized'), 'size': size, 'model': req['model']}
                break
            if not callable_adapter:
                worker.adapter = adapter_from_file(Path(adapter), timeout=min(req['call_timeout'], remaining))
            report = worker.run_once()
            if report['status'] in ('idle', 'waiting'):
                break
            entry = {'jobs': size, 'profile': profile, 'status': report['status']}
            if report.get('error_code'):
                entry['error_code'] = report['error_code']
            calls.append(entry)
            if report.get('call_id'):
                with (run / 'do.jsonl').open('a', encoding='utf-8') as file:
                    file.write(J({'call_id': report['call_id'], 'jobs': size, 'profile': profile,
                                  'model': req['model']}) + '\n')
        rows = box.records(ids)
        now = box.clock()
    jobs = {mid: _outcome(mid, rows.get(mid), blocker, now, run, root, req['max_inline']) for mid in ids}
    counts = {}
    for outcome in jobs.values():
        counts[outcome['status']] = counts.get(outcome['status'], 0) + 1
    accounting = _accounting(run)
    return {'schema': RESULT_SCHEMA,
            'status': 'complete' if 'unresolved' not in counts else 'incomplete',
            'counts': counts,
            'jobs': jobs,
            'evidence': {'scope': 'model_declared', 'checks_run': 0, 'id_binding': 'declared'},
            'calls': calls,
            'accounting': accounting,
            # What a qualified_cell label covers, shown only when one was used.
            'qualification': QUALIFICATION if accounting['qualified_cell_calls'] else None,
            'blocker': blocker,
            'run': {'workspace': str(root), 'run_dir': run.relative_to(root).as_posix(), 'request_id': req['request_id'],
                    'request_sha256': req['sha256'], 'binding': work.binding, 'model': req['model'],
                    'elapsed_seconds': round(clock() - started, 3)}}
