"""oz map: one operation over every file a glob matches, expanded into ordinary oz.do/1 requests (no new engine).

The host expands the glob into jobs [id, op, ref] in sorted path order: one {"path"} reference per file, the operation
text as the single op, and "profile": "oz1g-selective-v1" so that pinned per-job checks (oz_accept) and plan-only work.
More than oz_do.MAX_JOBS files become consecutive requests in the same order; their results are merged. Everything
else (leases, retries, checks, accounting, run directories under workspace/do/) is oz_do. A job id and a request id
derive from the relative path and the work, so resubmitting the same map resumes it and never repays settled jobs.

Results are JSONL, one line per job in input order. "accepted" means the job passed its pinned host checks (or, with
none, only the wire format); it is never a claim that the value is correct. --learn is only recorded; rule learning is
not implemented yet.

oz-rule/1 amendment 1 (D2, D7, D8, D9):
 * D2: oz_map itself reads each file (containment and size checks included), removes exactly one terminal CRLF, else
   one LF, and passes the resolved text to oz_do as an inline string reference. oz_do is never told about the policy.
   Rows and the receipt keep path, raw hash, resolved hash, removed suffix and the policy version. The packet text is
   the same as for a path reference; only the reference source label reads "inline@sha256:<resolved>".
 * D7: --model and --effort are required, passed to the adapter as OZ_MODEL / OZ_EFFORT, reconciled with the adapter's
   own reported identity before dispatch (oz_route), and every row and the receipt carry the worker_hash.
 * D8: the host issues and persists a producer ID and a submission ID (workspace map/ownership.json). A job is named by
   "j" and a reference by "r" plus the lowercase unpadded base32 of SHA256(canonical(identity tuple)): 53 characters,
   so chunk boundaries never define identity, and name collisions are detected. Every row keeps producer, submission,
   logical job, request, reference mapping and a nullable physical call ID.
 * Rule results (step 4) will be settled outside oz_do, so a rule result can never reach memo storage (the earlier
   `rule:` skip inside oz_do's memo publish is dropped; oz_do is frozen and stays untouched).
 * D9: a file that cannot be read or is empty or oversized becomes a failed row; valid siblings still run. A job over
   the input token budget is isolated as a failed row. A pathlike --ask value that names no file fails before dispatch.
"""
from __future__ import annotations

import base64
import contextlib
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from oz import Error
from oz_batch import valid_id
from oz_do import CELLS, MAX_JOBS, MAX_REF_BYTES, REGISTRY, do, normalize, size_profile
from oz_reply import dumps, loads
from oz_route import build as build_route, canonical
from oz_workspace import Workspace

OP = 'map'
GOAL = 'Apply the operation to each referenced file independently.'
PROFILE = 'oz1g-selective-v1'
ADAPTER = Path(__file__).resolve().parent / 'examples' / 'claude_map_adapter.json'
MAX_INLINE = 65536  # oz_do's largest inline value; a bigger value is read back from its value_file
INPUT_POLICY = 'strip-one-terminal-newline/1'
OWNERSHIP = Path('map') / 'ownership.json'
LIMITS = ('deadline_seconds', 'call_timeout_seconds', 'max_jobs_per_call', 'max_input_tokens')


def expand(pattern: str, allow: Path) -> list:
    """Sorted relative POSIX paths of the files the glob matches inside allow. A match outside allow is an error."""
    if not isinstance(pattern, str) or not pattern.strip():
        raise Error('glob must be a nonblank string')
    allow = Path(allow).resolve()
    found = set()
    for name in glob.glob(pattern, root_dir=allow, recursive=True):
        path = (allow / name).resolve()
        if path != allow and allow not in path.parents:
            raise Error(f'matched path outside the authorized directory: {name}')
        if path.is_file():
            found.add(path.relative_to(allow).as_posix())
    if not found:
        raise Error(f'no files match {pattern!r} inside {allow}')
    return sorted(found)


def _name(prefix: str, identity: list) -> str:
    """prefix + lowercase unpadded base32 of SHA256(canonical(identity)): 1 + 52 = 53 characters (amendment D8)."""
    digest = hashlib.sha256(canonical(identity).encode('utf-8')).digest()
    return prefix + base64.b32encode(digest).decode('ascii').rstrip('=').lower()


def job_name(producer: str, submission: str, op: str, path: str) -> str:
    """Compact delivery name of the logical job (producer, submission, op, path)."""
    return _name('j', ['job', producer, submission, op, path])


def ref_name(producer: str, submission: str, path: str) -> str:
    """Compact reference name; it carries the same producer and submission namespace as the job."""
    return _name('r', ['ref', producer, submission, path])


def names_for(paths, op: str, producer: str, submission: str) -> dict:
    """{path: (job name, reference name)}. Raises Error when two distinct identities collide on a name (never
    truncates). Fits oz_do: valid_id allows 64 characters, reference names 60, and 'ref-'+name is 57."""
    jobs, refs, out = {}, {}, {}
    for path in paths:
        job, ref = job_name(producer, submission, op, path), ref_name(producer, submission, path)
        for table, name, who in ((jobs, job, ['job', op, path]), (refs, ref, ['ref', path])):
            if table.setdefault(name, who) != who:
                raise Error(f'identity name collision on {name}: {table[name]} and {who}')
        out[path] = (job, ref)
    return out


def check_specs(raw, op: str):
    """The list of check specs for op from a checks file value: a list, or a mapping that must contain op."""
    if isinstance(raw, dict):
        if op not in raw:
            raise Error(f'checks file has no entry for operation {op!r}; it maps operation names to check spec lists')
        raw = raw[op]
    if not isinstance(raw, list) or not raw or any(not isinstance(spec, dict) for spec in raw):
        raise Error('checks must be a nonempty list of check specs (objects), or map the operation name to that list')
    return raw


def requests(paths, *, op: str, text: str, goal: str, names: dict, texts: dict, checks=None, model=None,
             allow_experimental=False, limits=None) -> list:
    """oz.do/1 requests for the paths: consecutive chunks of at most MAX_JOBS, in order. names is names_for(...);
    texts maps each path to its resolved text (read_input), carried as an inline string reference."""
    if not valid_id(op):
        raise Error('operation name must be 1..64 characters of [A-Za-z0-9_-]')
    if checks is not None:
        checks = check_specs(checks, op)
    out = []
    for start in range(0, len(paths), MAX_JOBS):
        chunk = paths[start:start + MAX_JOBS]
        request = {'v': 'oz.do/1', 'goal': goal, 'ops': {op: text},
                   'refs': {names[p][1]: texts[p] for p in chunk},
                   'jobs': [[names[p][0], op, names[p][1]] for p in chunk],
                   'profile': PROFILE, 'allow_experimental': bool(allow_experimental),
                   'max_inline_bytes': MAX_INLINE}
        if checks:
            request['checks'] = {op: checks}
        if model:
            request['model'] = model
        request.update(limits or {})
        out.append(request)
    return out


def apply_input_policy(text: str) -> tuple:
    """(resolved text, removed suffix): exactly one terminal CRLF, else one LF, is removed; nothing else changes."""
    for suffix in (chr(13) + chr(10), chr(10)):
        if text.endswith(suffix):
            return text[:-len(suffix)], suffix
    return text, ''


def read_input(path: str, root: Path) -> tuple:
    """(receipt, resolved text) for a readable, contained, nonblank, in-limit UTF-8 file, else an Error.
    receipt = {policy, raw_sha256, resolved_sha256, removed}; the hashes are over the UTF-8 bytes."""
    root = Path(root).resolve()
    full = (root / path).resolve()
    if full != root and root not in full.parents:
        raise Error(f'path outside the authorized directory: {path}')
    try:
        raw = full.read_bytes().decode('utf-8')
    except (OSError, UnicodeError):
        raise Error(f'cannot read UTF-8 file {path}') from None
    text, removed = apply_input_policy(raw)
    if not text.strip() or len(text.encode('utf-8')) > MAX_REF_BYTES:
        raise Error(f'file {path} must be nonblank and at most {MAX_REF_BYTES} UTF-8 bytes')
    return {'policy': INPUT_POLICY, 'raw_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            'resolved_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'removed': removed}, text


def preflight(path: str, *, op: str, root: Path, config: dict, registry=None) -> tuple:
    """(receipt, None) for a usable file under the input policy, else (None, message). The resolved text is checked
    again by oz_do.normalize on a one-job request, so the file is judged as the dispatch will judge it."""
    del op, config, registry
    try:
        return read_input(path, root)[0], None
    except Error as exc:
        return None, str(exc)


class Ownership:
    """Host-issued producer and submission IDs, persisted in <workspace>/map/ownership.json (amendment D8).

    A producer name maps to one producer ID for the life of the workspace. A new invocation gets a new submission ID,
    unless an earlier submission of the producer has the same context (operation, instruction, goal, checks, model,
    effort, worker identity, input policy): that one is resumed and keeps its ID. READING: D8 says resume "retains IDs
    and verifies unchanged payloads per job", so the file set may change between a submission and its resume; each job
    keeps its identity while its own input bytes are unchanged, and a job whose input changed is not re-sent under the
    old identity (it fails with payload_changed until --new-submission). A job that never dispatched (its input was
    invalid) records no payload and may be fixed in place."""

    def __init__(self, root: Path):
        self.file = Path(root) / OWNERSHIP
        try:
            self.state = json.loads(self.file.read_text(encoding='utf-8'))
        except FileNotFoundError:
            self.state = {'schema': 'oz.map.ownership/1', 'producers': {}}
        except (OSError, ValueError):
            raise Error(f'cannot read {self.file}; refusing to issue new identities over an unreadable record') from None
        if not isinstance(self.state, dict) or not isinstance(self.state.get('producers'), dict):
            raise Error(f'{self.file} is not an ownership record')

    def issue(self, name: str, context: str, payloads: dict, *, new=False, persist=True) -> dict:
        """{"producer", "submission", "resumed", "changed": set of job keys} for this invocation.
        payloads maps a job key (canonical [op, path]) to the SHA256 of its raw input, or None when it is invalid."""
        producer = self.state['producers'].setdefault(name, {'producer': 'p' + uuid.uuid4().hex[:16],
                                                             'submissions': []})
        found = None if new else next((x for x in reversed(producer['submissions']) if x['context'] == context), None)
        resumed = found is not None
        if found is None:
            found = {'submission': 's' + uuid.uuid4().hex[:16], 'context': context, 'jobs': {}}
            producer['submissions'].append(found)
        changed = set()
        for key, digest in payloads.items():
            known = found['jobs'].get(key)
            if known is not None and digest is not None and known != digest:
                changed.add(key)
            elif digest is not None:
                found['jobs'][key] = digest
            else:
                found['jobs'].setdefault(key, None)
        if persist:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            temp = self.file.with_name(self.file.name + '.' + uuid.uuid4().hex + '.tmp')
            temp.write_text(json.dumps(self.state, ensure_ascii=False, sort_keys=True) + chr(10), encoding='utf-8')
            os.replace(temp, self.file)
        return {'producer': producer['producer'], 'submission': found['submission'], 'resumed': resumed,
                'changed': changed}


def _error(outcome: dict) -> str:
    if outcome['status'] == 'failed':
        return f"{outcome['code']}: {outcome['message']}"
    detail = outcome.get('reason') or outcome['status']
    return detail + (f": {outcome['last_error']}" if outcome.get('last_error') else '')


def _ledger(run: Path) -> dict:
    """call_id -> (outcome, raw usage or None) from the run's call ledger; a started call without an end has outcome None."""
    calls = {}
    file = run / 'calls.jsonl'
    for line in (file.read_text(encoding='utf-8').splitlines() if file.exists() else ()):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        call = record.get('call_id')
        if record.get('event') == 'call_start':
            calls.setdefault(call, (None, None))
        else:
            raw = (record.get('usage') or {}).get('raw')
            calls[call] = (record.get('outcome'), raw if isinstance(raw, dict) else None)
    return calls


def _delta(before: dict, after: dict) -> dict:
    """Calls, failed calls and tokens of the calls that are new in the ledger."""
    new = [c for c in after if c not in before]
    counted = [after[c][1] for c in new if after[c][1] and {'input_tokens', 'output_tokens'} <= set(after[c][1])]
    return {'calls': len(new), 'failed_calls': sum(1 for c in new if after[c][0] not in ('ok', 'job_error')),
            'tokens': sum(u['input_tokens'] + u['output_tokens'] for u in counted),
            'usage': 'n/a' if not new else 'complete' if len(counted) == len(new) else 'none' if not counted
            else 'partial'}


def _coverage(values: set) -> str:
    values = set(values) - {'n/a'}
    return values.pop() if len(values) == 1 else 'n/a' if not values else 'partial'


def _call_ids(run_dir: Path, ids) -> dict:
    """job id -> physical call id of the job's latest candidate (accepted or not), from the run's authoritative SQLite.
    A job with no dispatched candidate (memo hit, wire failure, never dispatched) has no entry, so its call id is null."""
    file = run_dir / 'inbox.sqlite'
    found = {}
    if not file.exists():
        return found
    try:
        db = sqlite3.connect(f'file:{file.as_posix()}?mode=ro', uri=True, timeout=10)
        try:
            for job, call in db.execute('SELECT c.job, d.call_id FROM candidates c JOIN dispatches d ON '
                                        'd.receipt=c.receipt ORDER BY c.seq'):
                if job in ids and call:
                    found[job] = call
        finally:
            db.close()
    except sqlite3.Error:
        return {}
    return found


def run(pattern: str, *, op_text: str, op: str = OP, goal: str = GOAL, checks=None, model=None, effort=None,
        workspace='.', adapter=None, plan_only=False, learn=False, allow_experimental=False, producer='default',
        new_submission=False, identity=None, limits=None, clock=time.monotonic, **options) -> dict:
    """Expand the glob and run (or plan) the requests. options go to oz_do.do (registry, route, memo and so on).
    identity is oz_route.build(...) (the CLI always supplies it; READING: this function stays usable without it for
    fake-adapter tests, and then rows carry worker_hash null). limits may hold deadline_seconds, call_timeout_seconds,
    max_jobs_per_call and max_input_tokens. Everything oz_do validates about the operation is validated for ALL
    chunks before the first dispatch; a file that cannot be used is a failed row, never an abort.
    Returns {"rows", "receipt", "requests", "plans"}; rows are the JSONL records in input order."""
    started = clock()
    root = Path(workspace).resolve()
    paths = expand(pattern, root)
    if not valid_id(producer):
        raise Error('producer must be 1..64 characters of [A-Za-z0-9_-]')
    if not valid_id(op):
        raise Error('operation name must be 1..64 characters of [A-Za-z0-9_-]')
    specs = check_specs(checks, op) if checks is not None else None
    limits = dict(limits or {})
    if set(limits) - set(LIMITS):
        raise Error('limits take ' + ', '.join(LIMITS))
    space = Workspace(root)
    registry = options.get('registry') or REGISTRY
    worker = identity['worker_hash'] if identity else None
    if identity and 'route' not in options:
        options['route'] = identity['do_route']
    # Per-file preflight (D9): an unreadable, empty, invalid or oversized file is a failed row and its siblings run.
    receipts, invalid, texts = {}, {}, {}
    for path in paths:
        try:
            receipts[path], texts[path] = read_input(path, root)
        except Error as exc:
            invalid[path] = str(exc)
    context = hashlib.sha256(canonical({'op': op, 'op_text': op_text, 'goal': goal, 'checks': specs, 'model': model,
                                        'effort': effort, 'worker_hash': worker, 'input_policy': INPUT_POLICY,
                                        'profile': PROFILE}).encode('utf-8')).hexdigest()
    key = lambda path: canonical([op, path])
    owner = Ownership(root).issue(producer, context, {key(p): receipts[p]['raw_sha256'] if p in receipts else None
                                                      for p in paths}, new=new_submission, persist=not plan_only)
    for path in [p for p in receipts if key(p) in owner['changed']]:
        del receipts[path]
        invalid[path] = ('payload_changed: this input differs from the one first sent under this submission; '
                         'pass --new-submission to send it as a new job')
    valid = [p for p in paths if p in receipts]
    names = names_for(paths, op, owner['producer'], owner['submission'])
    batch = requests(valid, op=op, text=op_text, goal=goal, names=names, texts=texts, checks=checks, model=model,
                     allow_experimental=allow_experimental, limits=limits)
    normal = [normalize(r, allow=root, config=space.config, registry=registry) for r in batch]
    if adapter is None:
        adapter = ADAPTER
        if not adapter.exists() and not plan_only:
            raise Error('default adapter examples/claude_map_adapter.json not found; pass --adapter')
    base = {'producer': owner['producer'], 'submission': owner['submission'], 'worker_hash': worker}

    def failed_row(path, message):
        text = message if message.startswith('payload_changed') else f'input_invalid: {message}'
        return dict(base, id=names[path][0], request=None, request_id=None, path=path, status='failed',
                    error=text, source='model', logical_job={'op': op, 'path': path},
                    reference={'name': names[path][1], 'path': path, 'input': None}, call_id=None)

    if plan_only:
        plans = [do(r, workspace=root, adapter=adapter, plan_only=True, **options) for r in batch]
        return {'rows': [], 'requests': batch, 'plans': plans, 'learn': learn,
                'receipt': dict(base, jobs=len(paths), requests=len(batch), calls=0, resumed=owner['resumed'],
                                invalid_inputs=len(invalid),
                                planned_packets=[n for p in plans for n in p['plan']['packets']])}
    sizes = sorted({n for r in batch for n in do(r, workspace=root, adapter=adapter, plan_only=True,
                                                 **options)['plan']['packets']})
    kinds = {n: 'experimental' if n in options.get('experimental_sizes', ()) else size_profile(model, n, CELLS)
             for n in sizes}
    refused = [n for n, kind in kinds.items() if kind == 'unsupported']
    if refused:
        raise Error(f'packet sizes {refused} are unsupported for model {model!r} (failed size gate); nothing was run')
    experimental = [n for n, kind in kinds.items() if kind == 'experimental']
    if experimental and not allow_experimental:
        raise Error(f'packet sizes {experimental} are experimental for model {model!r} (no passed size gate); '
                    'pass --allow-experimental to run them. Nothing was run')
    done, coverage, cumulative_coverage = {}, set(), set()
    fresh = {'calls': 0, 'failed_calls': 0, 'tokens': 0}
    cumulative = {'calls': 0, 'failed_calls': 0, 'tokens': 0}
    for index, request in enumerate(batch):
        before = _ledger(root / 'do' / normal[index]['request_id'])
        result = do(request, workspace=root, adapter=adapter, allow=root, **options)
        delta = _delta(before, _ledger(root / result['run']['run_dir']))
        for name in fresh:
            fresh[name] += delta[name]
        coverage.add(delta['usage'])
        accounting = result['accounting']
        cumulative['calls'] += accounting['calls']
        cumulative['failed_calls'] += accounting['failed_calls']
        cumulative['tokens'] += accounting['tokens']['input_tokens'] + accounting['tokens']['output_tokens']
        cumulative_coverage.add(accounting['usage_coverage'])
        by_ref = {names[p][1]: p for p in valid}
        calls = _call_ids(root / result['run']['run_dir'], {row[0] for row in request['jobs']})
        for row in request['jobs']:
            outcome = result['jobs'][row[0]]
            path = by_ref[row[2]]
            line = dict(base, id=row[0], request=index, request_id=result['run']['request_id'], path=path,
                        status=outcome['status'], logical_job={'op': op, 'path': path},
                        reference={'name': row[2], 'path': path, 'input': receipts[path]},
                        call_id=calls.get(row[0]))
            if outcome['status'] == 'unresolved' and outcome.get('reason') == 'input_budget':
                # The planner defers only a job that alone exceeds the token budget (siblings were dispatched).
                line['status'] = 'failed'
                line['error'] = (f"input_budget: this job alone exceeds max_input_tokens "
                                 f"{outcome.get('max_input_tokens')}; raise --max-input-tokens")
                line['source'] = 'model'
            elif outcome['status'] == 'accepted':
                if 'value_file' in outcome:
                    line['value'] = loads((root / outcome['value_file']).read_text(encoding='utf-8'))
                else:
                    line['value'] = outcome['value']
                memo = (result['jobs'][row[0]].get('evidence') or {}).get('memo_entry')
                line['source'] = 'memo' if memo else 'model'
            else:
                line['error'] = _error(outcome)
                line['source'] = 'model'
            done[path] = line
    rows = [done[p] if p in done else failed_row(p, invalid[p]) for p in paths]
    accepted = sum(1 for r in rows if r['status'] == 'accepted')
    receipt = dict(base, jobs=len(rows), accepted_by_checks=accepted, failed=len(rows) - accepted,
                   invalid_inputs=len(invalid), resumed=owner['resumed'], input_policy=INPUT_POLICY,
                   calls=fresh['calls'], failed_calls=fresh['failed_calls'], tokens=fresh['tokens'],
                   usage=_coverage(coverage), scope='this invocation',
                   cumulative=dict(cumulative, usage=cumulative_coverage.pop() if len(cumulative_coverage) == 1
                                   else 'partial' if cumulative_coverage else 'n/a',
                                   scope='all invocations of these runs'),
                   requests=len(batch), seconds=round(clock() - started, 3),
                   checks='pinned' if checks else 'none')
    return {'rows': rows, 'receipt': receipt, 'requests': batch, 'learn': learn}


def write_rows(rows: list, out: Path) -> None:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', encoding='utf-8', newline='\n') as file:
        for row in rows:
            file.write(dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')


def receipt_line(receipt: dict, out, learn=False) -> str:
    """One line. "accepted_by_checks" means the pinned host checks passed; it says nothing about correctness."""
    text = (f"oz map: jobs={receipt['jobs']} accepted_by_checks={receipt['accepted_by_checks']} "
            f"(checks={receipt['checks']}; not a correctness claim) failed={receipt['failed']} "
            f"calls={receipt['calls']} tokens={receipt['tokens']} (usage {receipt['usage']}; this invocation) "
            f"cumulative_calls={receipt['cumulative']['calls']} cumulative_tokens={receipt['cumulative']['tokens']} "
            f"(all invocations of these runs) requests={receipt['requests']} seconds={receipt['seconds']} "
            f"producer={receipt['producer']} submission={receipt['submission']} "
            f"worker={(receipt['worker_hash'] or 'none')[:12]} invalid_inputs={receipt['invalid_inputs']} out={out}")
    return text + (' learn=requested (not active yet)' if learn else '')


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        raise Error(f'cannot read UTF-8 file {path}') from None


_PATHLIKE = re.compile(r'\S*[/\\]\S*|\S+\.[A-Za-z0-9]{1,5}')


def pathlike(text: str) -> bool:
    """True for a single token that looks like a file path (a separator or a short extension, no spaces or newlines)."""
    return '\n' not in text and bool(_PATHLIKE.fullmatch(text.strip()))


@contextlib.contextmanager
def _environ(**values):
    """Set adapter-visible variables for the duration of a run (the adapter subprocess inherits os.environ)."""
    old = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def command(args) -> int:
    """The `oz map` command: prints the receipt (or the plan) to stdout. Exit 0 when every job was accepted, else 3."""
    if (args.ask is None) == (args.ask_file is None):
        raise Error('give exactly one of --ask TEXT or --ask-file PATH')
    if args.ask_file is not None:
        if not args.ask_file.is_file():
            raise Error(f'--ask-file {args.ask_file} does not exist')
        text = _read(args.ask_file)
    else:
        text = args.ask
        if pathlike(text) and not Path(text.strip()).exists():
            raise Error(f'--ask {text!r} looks like a file path but no such file exists; '
                        'use --ask-file PATH for a file, or quote the instruction as text')
    if not text.strip():
        raise Error('the operation instruction must not be blank')
    if not args.model or not args.effort:
        raise Error('--model and --effort are required: a worker is identified by its full route, never a model label')
    if args.goal is not None and args.goal_file is not None:
        raise Error('give --goal or --goal-file, not both')
    goal = _read(args.goal_file) if args.goal_file is not None else args.goal or GOAL
    checks = check_specs(loads(_read(args.check)), args.op) if args.check is not None else None
    limits = {k: v for k, v in (('deadline_seconds', args.deadline_seconds),
                                ('call_timeout_seconds', args.call_timeout_seconds),
                                ('max_jobs_per_call', args.max_jobs_per_call),
                                ('max_input_tokens', args.max_input_tokens)) if v is not None}
    adapter = args.adapter or ADAPTER
    if not Path(adapter).exists():
        raise Error(f'adapter file {adapter} not found; pass --adapter')
    with _environ(OZ_MODEL=args.model, OZ_EFFORT=args.effort):
        identity = build_route(adapter, model=args.model, effort=args.effort)
        result = run(args.glob, op_text=text, op=args.op, goal=goal, checks=checks, model=args.model,
                     effort=args.effort, workspace=args.workspace, adapter=adapter, plan_only=args.plan,
                     learn=args.learn, allow_experimental=args.allow_experimental, producer=args.producer,
                     new_submission=args.new_submission, identity=identity, limits=limits)
    if args.plan:
        print(dumps({'schema': 'oz.map.plan/1', 'learn': 'requested (not active yet)' if args.learn else 'off',
                     'jobs': result['receipt']['jobs'], 'requests': result['requests'], 'plans': result['plans'],
                     'producer': result['receipt']['producer'], 'submission': result['receipt']['submission'],
                     'route': identity['route'], 'worker_hash': identity['worker_hash'],
                     'invalid_inputs': result['receipt']['invalid_inputs'], 'calls': 0},
                    ensure_ascii=False, separators=(',', ':')))
        return 0
    out = args.out or Path('results.jsonl')
    write_rows(result['rows'], out)
    print(receipt_line(result['receipt'], out, args.learn))
    return 0 if result['receipt']['failed'] == 0 else 3


def build_parser():
    import argparse
    p = argparse.ArgumentParser(prog='oz-map', description='Apply one operation to every file a glob matches '
                                '(JSONL results, one receipt line)')
    p.add_argument('glob', help='Glob inside the workspace, for example "refs/*.txt"')
    ask = p.add_mutually_exclusive_group(required=True)
    ask.add_argument('--ask', help='Operation instruction as inline text')
    ask.add_argument('--ask-file', type=Path, help='Operation instruction read from this UTF-8 file (must exist)')
    p.add_argument('--allow-experimental', action='store_true',
                   help='Allow packet sizes with no passed size gate for the model (default: refuse before any call)')
    p.add_argument('--op', default='map', help='Operation name used by --check (default: map)')
    p.add_argument('--goal')
    p.add_argument('--goal-file', type=Path)
    p.add_argument('--check', type=Path, help='JSON list of check specs, or {operation: [specs]}')
    p.add_argument('--out', type=Path, help='Results JSONL (default: results.jsonl)')
    p.add_argument('--workspace', type=Path, default=Path('.'), help='Directory containing oz.json; files stay inside it')
    p.add_argument('--adapter', type=Path, help='Adapter JSON file (default: examples/claude_map_adapter.json)')
    p.add_argument('--model', help='Required. Model ID; passed to the adapter and bound into the worker identity')
    p.add_argument('--effort', help='Required. Reasoning effort; passed to the adapter and bound into the worker identity')
    p.add_argument('--producer', default='default', help='Producer name; the host issues and persists its ID (default: default)')
    p.add_argument('--new-submission', action='store_true',
                   help='Issue a new submission ID even when an earlier one has the same operation, goal and route')
    p.add_argument('--deadline-seconds', type=float, help='oz.do deadline_seconds per request (default 600)')
    p.add_argument('--call-timeout-seconds', type=float, help='oz.do call_timeout_seconds (default 300)')
    p.add_argument('--max-jobs-per-call', type=int, help='oz.do max_jobs_per_call (default: workspace batch size)')
    p.add_argument('--max-input-tokens', type=int, help='oz.do max_input_tokens (default: workspace max_tokens)')
    p.add_argument('--plan', action='store_true', help='Print the expanded request and packet plan; no model call')
    p.add_argument('--learn', action='store_true', help='Recorded only; rule learning is not active yet')
    return p


def main(argv=None) -> int:
    """Console entry point (`oz-map` / `python -m oz_map`). Errors print "oz: <message>" to stderr and exit 2."""
    import sys
    args = build_parser().parse_args(argv)
    try:
        return command(args)
    except (Error, OSError, ValueError, TypeError, sqlite3.Error) as exc:
        print(f'oz: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
