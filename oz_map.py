"""oz map: one operation over every file a glob matches, expanded into ordinary oz.do/1 requests (no new engine).

The host expands the glob into jobs [id, op, ref] in sorted path order: one {"path"} reference per file, the operation
text as the single op, and "profile": "oz1g-selective-v1" so that pinned per-job checks (oz_accept) and plan-only work.
More than oz_do.MAX_JOBS files become consecutive requests in the same order; their results are merged. Everything
else (leases, retries, checks, accounting, run directories under workspace/do/) is oz_do. A job id and a request id
derive from the relative path and the work, so resubmitting the same map resumes it and never repays settled jobs.

Results are JSONL, one line per job in input order. "accepted" means the job passed its pinned host checks (or, with
none, only the wire format); it is never a claim that the value is correct.

--learn (build step 4; off by default, and with it off every request, row and receipt is exactly as before). It needs
--registry MANIFEST (an owner-approved oz_registry manifest whose operation ID is --op), --audit-seed N and an adapter
wrapped by examples/bootstrap_shim.py (bootstrap_claude_adapter.json or bootstrap_codex_adapter.json). The flow:
 1. Bootstrap. When the rule store (oz_rulephase, <workspace>/map/rules.sqlite) has no entry for the full bindings, the
    first --bootstrap-size valid jobs (default: one packet, max_jobs_per_call or the workspace batch size, at most 64)
    form one oz_do request run with OZ_BOOTSTRAP set; the shim makes exactly one physical call carry the bootstrap
    instruction, returns the envelope's answers as the ordinary reply and writes the proposed rules to a side file
    keyed by the call's receipt. Each candidate is admitted through the registry (oz_registry resolve + oz_rule.admit)
    and recorded admitted or rejected. A malformed envelope is a failed bootstrap: no rule, no repair; the worker's
    ordinary retry of those jobs is a passthrough call tagged residual.
 2. Rule phase (D1). For every other valid job an admitted rule is evaluated on the job's resolved input; a value that
    passes every pinned consumer check (registry and --check) is committed in the rule store by adopt_rule, which
    re-evaluates the exact AST bytes and re-validates admission, bindings and quarantine state in the same
    transaction. Those rows read source "rule" and make no call; they never pass through oz_do, so never reach memo
    storage. An abstain, a failed or inconclusive check or a refused commit falls back to the model.
 3. Residual and audits. Fallback jobs plus min(32, covered) blind audit jobs (own D8 identities linked to the
    originals; the packet carries only the instruction and the input) run through ordinary oz_do requests, audits in
    the same calls. A disagreement quarantines the rule for future jobs; emitted rule rows stay as recorded.
Every physical call is tagged bootstrap, residual or audit in rows (call_kind) and in the receipt (calls_by_kind,
call_ledger). The receipt keeps runtime acceptance (accepted_by_checks) apart from correctness, which needs gold.

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
 * Rule results (step 4) are settled outside oz_do, in the rule store, so a rule result can never reach memo storage
   (the earlier `rule:` skip inside oz_do's memo publish is dropped; oz_do is frozen and stays untouched).
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
        new_submission=False, identity=None, limits=None, clock=time.monotonic, rule_registry=None, audit_seed=None,
        bootstrap_size=None, rule_store=None, rule_hooks=None, **options) -> dict:
    """Expand the glob and run (or plan) the requests. options go to oz_do.do (registry, route, memo and so on).
    With learn (and not plan_only) the run goes through _learn_run: rule_registry is the oz_registry.Registry,
    audit_seed the frozen audit seed, bootstrap_size the bootstrap job count, rule_store the rule store path
    (default <workspace>/map/rules.sqlite) and rule_hooks test hooks ({"evaluate", "before_commit"}).
    identity is oz_route.build(...) (the CLI always supplies it; READING: this function stays usable without it for
    fake-adapter tests, and then rows carry worker_hash null). limits may hold deadline_seconds, call_timeout_seconds,
    max_jobs_per_call and max_input_tokens. Everything oz_do validates about the operation is validated for ALL
    chunks before the first dispatch; a file that cannot be used is a failed row, never an abort.
    Returns {"rows", "receipt", "requests", "plans"}; rows are the JSONL records in input order."""
    if learn and not plan_only:
        return _learn_run(pattern, op_text=op_text, op=op, goal=goal, checks=checks, model=model, effort=effort,
                          workspace=workspace, adapter=adapter, allow_experimental=allow_experimental,
                          producer=producer, new_submission=new_submission, identity=identity, limits=limits,
                          clock=clock, rule_registry=rule_registry, audit_seed=audit_seed,
                          bootstrap_size=bootstrap_size, rule_store=rule_store, rule_hooks=rule_hooks, **options)
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


# --------------------------------------------------------------------------------------------- --learn (step 4)

SHIM = 'bootstrap_shim.py'
CALL_KINDS = ('bootstrap', 'residual', 'audit')
CORRECTNESS = ('not assessed: accepted means runtime acceptance (pinned checks, and for rule rows rule provenance); '
               'audits measure agreement with a blind model answer, not gold correctness')


def is_bootstrap_adapter(adapter) -> bool:
    """True for an adapter JSON whose argv runs examples/bootstrap_shim.py, or a callable marked bootstrap_shim."""
    if isinstance(adapter, (str, Path)):
        try:
            spec = json.loads(Path(adapter).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return False
        argv = spec.get('argv') if isinstance(spec, dict) else None
        return isinstance(argv, list) and any(isinstance(a, str) and Path(a).name == SHIM for a in argv)
    return getattr(adapter, 'bootstrap_shim', False) is True


def audit_names(producer: str, submission: str, op: str, path: str, original: str) -> tuple:
    """(job name, reference name) of the blind audit of one covered job: a distinct D8 identity linked to the
    original job name. Same 53-character form as every other name."""
    return (_name('j', ['audit', producer, submission, op, path, original]),
            _name('r', ['audit-ref', producer, submission, op, path, original]))


def _gate(batch, *, root, adapter, model, allow_experimental, options) -> None:
    """The size gate of run(), for the requests of one learn phase, before that phase dispatches anything."""
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


def _call_table(run: Path) -> dict:
    """call_id -> {receipt, jobs, outcome, usage} from the run's call ledger (call_start carries the job map)."""
    calls = {}
    file = run / 'calls.jsonl'
    for line in (file.read_text(encoding='utf-8').splitlines() if file.exists() else ()):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        entry = calls.setdefault(record.get('call_id'), {'receipt': record.get('batch_id'), 'jobs': [
            m.get('inbox_job_id') for m in record.get('job_map') or [] if isinstance(m, dict)], 'outcome': None,
            'usage': None})
        if record.get('event') != 'call_start':
            raw = (record.get('usage') or {}).get('raw')
            entry['outcome'] = record.get('outcome')
            entry['usage'] = raw if isinstance(raw, dict) else None
    return calls


def _model_row(base, result, request, index, job, path, receipt, root, calls, op) -> dict:
    """One row for a job that went through oz_do: the same fields and branches as run()."""
    outcome = result['jobs'][job[0]]
    line = dict(base, id=job[0], request=index, request_id=result['run']['request_id'], path=path,
                status=outcome['status'], logical_job={'op': op, 'path': path},
                reference={'name': job[2], 'path': path, 'input': receipt}, call_id=calls.get(job[0]))
    if outcome['status'] == 'unresolved' and outcome.get('reason') == 'input_budget':
        line['status'] = 'failed'
        line['error'] = (f"input_budget: this job alone exceeds max_input_tokens "
                         f"{outcome.get('max_input_tokens')}; raise --max-input-tokens")
        line['source'] = 'model'
    elif outcome['status'] == 'accepted':
        if 'value_file' in outcome:
            line['value'] = loads((root / outcome['value_file']).read_text(encoding='utf-8'))
        else:
            line['value'] = outcome['value']
        memo = (outcome.get('evidence') or {}).get('memo_entry')
        line['source'] = 'memo' if memo else 'model'
    else:
        line['error'] = _error(outcome)
        line['source'] = 'model'
    return line


def _learn_run(pattern: str, *, op_text, op, goal, checks, model, effort, workspace, adapter, allow_experimental,
               producer, new_submission, identity, limits, clock, rule_registry, audit_seed, bootstrap_size,
               rule_store, rule_hooks, **options) -> dict:
    """run() with --learn: bootstrap, admission, rule phase, residual plus audits (module docstring)."""
    import oz_rulephase as rp
    from oz_accept import pin

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
    if rule_registry is None:
        raise Error('--learn needs --registry MANIFEST (an owner-approved oz-rule/1 registry)')
    if type(audit_seed) is not int or isinstance(audit_seed, bool):
        raise Error('--learn needs a frozen integer --audit-seed')
    if not identity or not identity.get('worker_hash'):
        raise Error('--learn needs the full worker identity (route and worker_hash, D7)')
    if bootstrap_size is not None and (type(bootstrap_size) is not int or not 1 <= bootstrap_size <= 64):
        raise Error('--bootstrap-size must be an integer 1..64 (one physical call)')
    if adapter is None:
        raise Error('--learn needs an adapter wrapped by examples/bootstrap_shim.py; pass --adapter')
    if not is_bootstrap_adapter(adapter):
        raise Error('--learn needs an adapter wrapped by examples/bootstrap_shim.py (for example '
                    'examples/bootstrap_claude_adapter.json); this adapter cannot carry the bootstrap')
    hooks = dict(rule_hooks or {})
    space = Workspace(root)
    registry = options.get('registry') or REGISTRY
    worker = identity['worker_hash']
    if 'route' not in options:
        options['route'] = identity['do_route']
    receipts, invalid, texts = {}, {}, {}
    for path in paths:
        try:
            receipts[path], texts[path] = read_input(path, root)
        except Error as exc:
            invalid[path] = str(exc)
    pinned = list(pin(specs, registry)) if specs else []
    map_contract = hashlib.sha256(canonical({'op': op, 'op_text': op_text, 'goal': goal, 'checks': pinned,
                                             'profile': PROFILE}).encode('utf-8')).hexdigest()
    store = rp.RuleStore(Path(rule_store) if rule_store is not None else root / 'map' / 'rules.sqlite')
    try:
        learner = rp.Learner(store, rule_registry, op, worker_hash=worker, map_contract=map_contract,
                             map_input_policy=INPUT_POLICY)
        per_call = limits.get('max_jobs_per_call') or space.config['batch_size']
        size = bootstrap_size or min(int(per_call), 64)
        context = hashlib.sha256(canonical({'op': op, 'op_text': op_text, 'goal': goal, 'checks': specs,
                                            'model': model, 'effort': effort, 'worker_hash': worker,
                                            'input_policy': INPUT_POLICY, 'profile': PROFILE,
                                            'learn': {'binding_key': learner.key, 'audit_seed': audit_seed,
                                                      'bootstrap_size': size, 'glob': pattern}}).encode('utf-8')
                                 ).hexdigest()
        key = lambda path: canonical([op, path])
        owner = Ownership(root).issue(producer, context, {key(p): receipts[p]['raw_sha256'] if p in receipts else None
                                                          for p in paths}, new=new_submission)
        for path in [p for p in receipts if key(p) in owner['changed']]:
            del receipts[path]
            invalid[path] = ('payload_changed: this input differs from the one first sent under this submission; '
                             'pass --new-submission to send it as a new job')
        valid = [p for p in paths if p in receipts]
        names = names_for(paths, op, owner['producer'], owner['submission'])
        base = {'producer': owner['producer'], 'submission': owner['submission'], 'worker_hash': worker}
        return _learn_phases(rp, store, learner, paths=paths, valid=valid, invalid=invalid, receipts=receipts,
                             texts=texts, names=names, base=base, owner=owner, op=op, op_text=op_text, goal=goal,
                             checks=checks, pinned=pinned, model=model, root=root, adapter=adapter,
                             allow_experimental=allow_experimental, limits=limits, size=size, audit_seed=audit_seed,
                             hooks=hooks, options=options, space=space, registry=registry, started=started,
                             clock=clock)
    finally:
        store.close()


def _learn_phases(rp, store, learner, *, paths, valid, invalid, receipts, texts, names, base, owner, op, op_text,
                  goal, checks, pinned, model, root, adapter, allow_experimental, limits, size, audit_seed, hooks,
                  options, space, registry, started, clock) -> dict:
    producer, submission = owner['producer'], owner['submission']
    run_dirs, done = [], {}
    fresh = {'calls': 0, 'failed_calls': 0, 'tokens': 0}
    cumulative = {'calls': 0, 'failed_calls': 0, 'tokens': 0}
    coverage, cumulative_coverage = set(), set()
    side_receipts = {}  # run dir -> {receipt: side record}
    sent = []
    index = [0]

    def dispatch(request, env=None):
        normal = normalize(request, allow=root, config=space.config, registry=registry)
        run_dir = root / 'do' / normal['request_id']
        before = _ledger(run_dir)
        if env:
            with _environ(**env):
                result = do(request, workspace=root, adapter=adapter, allow=root, **options)
        else:
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
        run_dirs.append((root / result['run']['run_dir'], before))
        position = index[0]
        index[0] += 1
        return result, position

    # 1. Bootstrap: only when the store has no entry for these bindings (or this submission already started one).
    learn = {'eligible': learner.eligible, 'binding_key': learner.key, 'operation': op, 'audit_seed': audit_seed,
             'bootstrap': {'status': 'not_needed', 'jobs': 0, 'size': size}}
    if learner.ineligible_reason:
        learn['ineligible'] = learner.ineligible_reason
    record = store.bootstrap(producer, submission, learner.key)
    boot = list(record['paths']) if record else valid[:size] if valid and not store.rules(learner.key) else []
    boot_texts = dict(texts)
    for path in boot:
        if path in receipts:
            continue
        if path in paths:
            raise Error(f'bootstrap input {path} changed or became unreadable since this submission started; '
                        'pass --new-submission')
        # A bootstrap job outside this expansion: its request is rebuilt exactly (it resumes with no call), but it
        # gets no row in this invocation.
        try:
            boot_texts[path] = read_input(path, root)[1]
        except Error:
            raise Error(f'bootstrap input {path} is no longer readable; pass --new-submission') from None
    if boot:
        names = dict(names, **{p: (job_name(producer, submission, op, p), ref_name(producer, submission, p))
                               for p in boot if p not in names})
        [request] = requests(boot, op=op, text=op_text, goal=goal, names=names, texts=boot_texts, checks=checks,
                             model=model, allow_experimental=allow_experimental,
                             limits=dict(limits, max_jobs_per_call=len(boot)))
        _gate([request], root=root, adapter=adapter, model=model, allow_experimental=allow_experimental,
              options=options)
        normal = normalize(request, allow=root, config=space.config, registry=registry)
        if record is None:
            # Recorded before the call, so a resumed submission rebuilds exactly this bootstrap request.
            record = store.record_bootstrap(producer, submission, learner.key, normal['request_id'], boot)
        sent.append(request)
        side_dir = root / 'do' / normal['request_id'] / 'bootstrap'
        side_dir.mkdir(parents=True, exist_ok=True)
        config_file = side_dir / 'config.json'
        if not config_file.exists():
            config = learner.bootstrap_config(side_dir)
            temp = side_dir / ('config-' + uuid.uuid4().hex + '.tmp')
            temp.write_text(json.dumps(config, ensure_ascii=False, sort_keys=True), encoding='utf-8')
            os.replace(temp, config_file)
        result, position = dispatch(request, env={'OZ_BOOTSTRAP': str(config_file)})
        run_dir = root / result['run']['run_dir']
        table = _call_table(run_dir)
        by_receipt = {entry['receipt']: call for call, entry in table.items()}
        sides = rp.read_side_files(side_dir)
        side_receipts[run_dir] = {s['receipt']: s for s in sides}
        provenance = {'producer': producer, 'submission': submission, 'request_id': result['run']['request_id'],
                      'run_dir': result['run']['run_dir'], 'config_sha256': hashlib.sha256(
                          config_file.read_bytes()).hexdigest()}
        if sides:
            for side in sides:
                learner.admit_side(side, source=f"{result['run']['request_id']}:{side['receipt']}:{op}",
                                   provenance=dict(provenance, receipt=side['receipt'],
                                                   call_id=by_receipt.get(side['receipt']), side_file=side['file'],
                                                   raw_reply_sha256=side.get('raw_reply_sha256'),
                                                   status=side.get('status')))
        elif (side_dir / 'attempted').exists():
            learner.admit_side(None, source=f"{result['run']['request_id']}:missing:{op}", provenance=provenance)
        side = sides[0] if sides else None
        learn['bootstrap'] = {'status': 'failed' if side is None or side.get('status') != 'ok' else 'ok',
                              'envelope': side.get('status') if side else 'missing', 'jobs': len(boot), 'size': size,
                              'request_id': result['run']['request_id'],
                              'receipt': side['receipt'] if side else None,
                              'call_id': by_receipt.get(side['receipt']) if side else None}
        calls = _call_ids(run_dir, {job[0] for job in request['jobs']})
        by_ref = {names[p][1]: p for p in boot}
        for job in request['jobs']:
            path = by_ref[job[2]]
            if path in receipts:
                done[path] = dict(_model_row(base, result, request, position, job, path, receipts[path], root, calls,
                                             op), phase='bootstrap')

    # 2. Rule phase (D1): every other valid job; a committed rule result is kept as recorded.
    entries = store.rules(learner.key)
    rule = store.active(learner.key)
    learn['rule'] = ({'id': rule['id'], 'ast_sha256': rule['ast_sha256'], 'status_at_start': 'admitted'} if rule else
                     {'id': None, 'status_at_start': entries[-1]['status'] if entries else 'none'})
    admission = next((e['admission'] for e in reversed(entries)), None)
    if admission is not None:
        learn['admission'] = {k: admission.get(k) for k in ('status', 'reasons', 'coverage', 'covered_errors')}
    without = ('no_admitted_rule' if not entries else 'quarantined' if any(e['status'] == 'quarantined' for e in entries)
               else 'rule_rejected')
    fallback, covered, reasons = [], {}, {}
    boot_set = set(boot)
    for path in valid:
        if path in boot_set:
            continue
        job = names[path][0]
        owner_row = {'producer': producer, 'submission': submission, 'operation': op, 'path': path}
        present = store.result(job)
        if present is not None:
            covered[path] = present
            continue
        if rule is None:
            fallback.append(path)
            reasons[path] = without
            continue
        decision = learner.attempt(rule, job=job, text=texts[path], resolved_sha256=receipts[path]['resolved_sha256'],
                                   op_text=op_text, map_pinned=pinned, owner=owner_row,
                                   evaluate=hooks.get('evaluate', rp.oz_rule.evaluate),
                                   before_commit=hooks.get('before_commit'))
        if decision['decision'] == 'rule':
            covered[path] = decision['row']
        else:
            fallback.append(path)
            reasons[path] = decision['reason']

    # 3. Audits: one persisted blind selection per wave and rule, riding in the residual calls.
    selected = []
    for rule_id in sorted({row['rule'] for row in covered.values()}):
        mine = [p for p, row in covered.items() if row['rule'] == rule_id]
        wave = store.wave(producer, submission, rule_id, audit_seed, mine)
        selected += [(p, rule_id) for p in wave['selected']]
    audit_of = {}
    rnames, rtexts, keys = {}, {}, []
    taken = {n for pair in names.values() for n in pair}
    for path in fallback:
        keys.append(path)
        rnames[path], rtexts[path] = names[path], texts[path]
    for path, rule_id in selected:
        pair = audit_names(producer, submission, op, path, names[path][0])
        if pair[0] in taken or pair[1] in taken:
            raise Error(f'identity name collision on audit of {path}')
        taken.update(pair)
        slot = 'audit:' + path
        keys.append(slot)
        rnames[slot], rtexts[slot] = pair, texts[path]
        audit_of[pair[0]] = {'path': path, 'rule': rule_id, 'original': names[path][0]}
    residual = requests(keys, op=op, text=op_text, goal=goal, names=rnames, texts=rtexts, checks=checks,
                        model=model, allow_experimental=allow_experimental, limits=limits) if keys else []
    sent.extend(residual)
    fallback_of = {names[p][0]: p for p in fallback}
    if residual:
        _gate(residual, root=root, adapter=adapter, model=model, allow_experimental=allow_experimental,
              options=options)
    audits = []
    for request in residual:
        result, position = dispatch(request)
        run_dir = root / result['run']['run_dir']
        calls = _call_ids(run_dir, {job[0] for job in request['jobs']})
        for job in request['jobs']:
            if job[0] in audit_of:
                info = audit_of[job[0]]
                path = info['path']
                line = _model_row(base, result, request, position, job, path, receipts[path], root, calls, op)
                rule_value = covered[path]['value']
                existing = store.audit(job[0])
                if existing is not None:
                    verdict, detail, model_value = existing['verdict'], existing['detail'], existing['model_value']
                elif line['status'] == 'unresolved':
                    # Not settled yet (deadline, quota, budget): nothing is recorded, a resumed run decides it.
                    verdict, detail, model_value = 'pending', line.get('error') or line['status'], None
                elif line['status'] != 'accepted':
                    verdict, detail, model_value = 'inconclusive', line.get('error') or line['status'], None
                elif line['source'] == 'memo':
                    verdict, detail, model_value = 'inconclusive', 'memo: no blind model answer', None
                else:
                    model_value = rp.value_text_of(line['value'])
                    verdict = 'agree' if model_value == rule_value else 'disagree'
                    detail = None
                record = {'audit_job': job[0], 'original_job': info['original'], 'rule': info['rule'],
                          'producer': producer, 'submission': submission, 'path': path, 'verdict': verdict,
                          'rule_value': rule_value, 'model_value': model_value, 'detail': detail,
                          'call_id': line['call_id'], 'request_id': result['run']['request_id']}
                quarantined = False
                if existing is None and verdict != 'pending':
                    if verdict == 'disagree':
                        quarantined = store.quarantine(info['rule'], {'audit_job': job[0], 'path': path,
                                                                      'rule_value': rule_value,
                                                                      'model_value': model_value}, record)
                    else:
                        store.record_audit(record)
                audits.append(dict(record, row=line, quarantined_now=quarantined))
            else:
                path = fallback_of[job[0]]
                done[path] = dict(_model_row(base, result, request, position, job, path, receipts[path], root,
                                             calls, op), phase='fallback', fallback_reason=reasons[path])

    # 4. Call tags (accounting hooks for step 6): every physical call is bootstrap, residual or audit.
    audit_jobs = set(audit_of)
    ledger, kinds = [], {}
    for run_dir, before in run_dirs:
        sides = side_receipts.get(run_dir, {})
        for call, entry in _call_table(run_dir).items():
            if entry['receipt'] in sides:
                kind = 'bootstrap'
            elif entry['jobs'] and all(j in audit_jobs for j in entry['jobs']):
                kind = 'audit'
            else:
                kind = 'residual'
            usage = entry['usage'] or {}
            tokens = (usage['input_tokens'] + usage['output_tokens']
                      if {'input_tokens', 'output_tokens'} <= set(usage) else None)
            kinds[call] = kind
            ledger.append({'call_id': call, 'kind': kind, 'run_dir': run_dir.relative_to(root).as_posix(),
                           'receipt': entry['receipt'], 'jobs': len(entry['jobs']),
                           'audit_jobs': sum(1 for j in entry['jobs'] if j in audit_jobs),
                           'outcome': entry['outcome'], 'tokens': tokens, 'new': call not in before})
    by_kind = {k: {'calls': 0, 'new_calls': 0, 'tokens': 0, 'new_tokens': 0, 'failed_calls': 0,
                   'usage': 'n/a'} for k in CALL_KINDS}
    for entry in ledger:
        slot = by_kind[entry['kind']]
        slot['calls'] += 1
        slot['new_calls'] += entry['new']
        slot['failed_calls'] += entry['outcome'] not in ('ok', 'job_error')
        slot['tokens'] += entry['tokens'] or 0
        slot['new_tokens'] += (entry['tokens'] or 0) if entry['new'] else 0
        known = entry['tokens'] is not None
        slot['usage'] = ('complete' if known else 'none') if slot['usage'] == 'n/a' else \
            slot['usage'] if slot['usage'] == ('complete' if known else 'none') else 'partial'
    for line in list(done.values()) + [a['row'] for a in audits]:
        line['call_kind'] = kinds.get(line['call_id'])
    for audit in audits:
        audit['call_kind'] = kinds.get(audit['call_id'])

    # 5. Rows in input order; rule rows carry source "rule", no call and the rule identity.
    audit_by_path = {a['path']: a for a in audits}
    for path, row in covered.items():
        audit = audit_by_path.get(path)
        line = dict(base, id=names[path][0], request=None, request_id=None, path=path, status='accepted',
                    value=loads(row['value']), source='rule', logical_job={'op': op, 'path': path},
                    reference={'name': names[path][1], 'path': path, 'input': receipts[path]}, call_id=None,
                    phase='rule', call_kind=None,
                    rule={'id': row['rule'], 'type': row['type'], 'steps': row['steps'],
                          'ast_sha256': row['provenance']['ast_sha256'], 'binding_key': row['binding_key'],
                          'checks': [f"{c['check']}@{c['version']}:{c['verdict']}" for c in row['checks']],
                          'provenance': row['provenance']['check']},
                    audit=None if audit is None else {'job': audit['audit_job'], 'verdict': audit['verdict'],
                                                      'call_id': audit['call_id']})
        done[path] = line

    def failed_row(path, message):
        text = message if message.startswith('payload_changed') else f'input_invalid: {message}'
        return dict(base, id=names[path][0], request=None, request_id=None, path=path, status='failed',
                    error=text, source='model', logical_job={'op': op, 'path': path},
                    reference={'name': names[path][1], 'path': path, 'input': None}, call_id=None, phase='input',
                    call_kind=None)

    rows = [done[p] if p in done else failed_row(p, invalid[p]) for p in paths]
    final = store.rule(learn['rule']['id']) if learn['rule']['id'] is not None else None
    verdicts = [a['verdict'] for a in audits]
    learn.update({
        'rule_hits': sum(1 for r in rows if r['source'] == 'rule'),
        'fallback': len(fallback),
        'abstains': sum(1 for p in fallback if reasons[p].startswith('abstain:')),
        'check_failures': sum(1 for p in fallback if reasons[p].startswith('check_')),
        'commit_refusals': sum(1 for p in fallback if reasons[p].startswith('commit_refused:')),
        'fallback_reasons': {r: sum(1 for p in fallback if reasons[p] == r) for r in sorted(set(reasons.values()))},
        'audits': {'selected': len(selected), 'agree': verdicts.count('agree'),
                   'disagree': verdicts.count('disagree'), 'inconclusive': verdicts.count('inconclusive'),
                   **({'pending': verdicts.count('pending')} if 'pending' in verdicts else {}), 'seed': audit_seed},
        'quarantined': bool(final and final['status'] == 'quarantined'),
    })
    if final is not None:
        learn['rule']['status_at_end'] = final['status']
    accepted = sum(1 for r in rows if r['status'] == 'accepted')
    receipt = dict(base, jobs=len(rows), accepted_by_checks=accepted, failed=len(rows) - accepted,
                   invalid_inputs=len(invalid), resumed=owner['resumed'], input_policy=INPUT_POLICY,
                   calls=fresh['calls'], failed_calls=fresh['failed_calls'], tokens=fresh['tokens'],
                   usage=_coverage(coverage), scope='this invocation',
                   cumulative=dict(cumulative, usage=cumulative_coverage.pop() if len(cumulative_coverage) == 1
                                   else 'partial' if cumulative_coverage else 'n/a',
                                   scope='all invocations of these runs'),
                   requests=len(run_dirs), seconds=round(clock() - started, 3),
                   checks='pinned' if checks else 'none', learn=learn, calls_by_kind=by_kind, call_ledger=ledger,
                   accepted_by_source={s: sum(1 for r in rows if r['status'] == 'accepted' and r['source'] == s)
                                       for s in ('model', 'memo', 'rule')},
                   correctness=CORRECTNESS)
    return {'rows': rows, 'receipt': receipt, 'requests': sent, 'learn': True,
            'audits': [{k: v for k, v in a.items() if k != 'row'} for a in audits]}


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
    info = receipt.get('learn')
    if isinstance(info, dict):
        kinds = receipt['calls_by_kind']
        audits = info['audits']
        text += (f" learn=on bootstrap={info['bootstrap']['status']} rule={info['rule'].get('status_at_end') or 'none'} "
                 f"rule_hits={info['rule_hits']} fallback={info['fallback']} abstains={info['abstains']} "
                 f"check_failures={info['check_failures']} audits={audits['selected']} "
                 f"(agree={audits['agree']} disagree={audits['disagree']} inconclusive={audits['inconclusive']}) "
                 f"quarantined={'yes' if info['quarantined'] else 'no'} "
                 + ' '.join(f"{k}_calls={kinds[k]['new_calls']}" for k in CALL_KINDS))
        return text
    return text + (' learn=requested (no rule phase ran)' if learn else '')


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
    learning = {}
    if args.learn and not args.plan:
        if args.registry is None or args.audit_seed is None:
            raise Error('--learn needs --registry MANIFEST and --audit-seed N')
        import oz_registry
        try:
            learning['rule_registry'] = oz_registry.Registry(args.registry, expected_sha256=args.registry_sha256)
        except oz_registry.RegistryError as exc:
            raise Error(f'registry {args.registry}: {exc}') from None
        learning.update(audit_seed=args.audit_seed, bootstrap_size=args.bootstrap_size)
    elif not args.learn and (args.registry or args.audit_seed is not None or args.bootstrap_size is not None):
        raise Error('--registry, --audit-seed and --bootstrap-size need --learn')
    with _environ(OZ_MODEL=args.model, OZ_EFFORT=args.effort):
        identity = build_route(adapter, model=args.model, effort=args.effort)
        result = run(args.glob, op_text=text, op=args.op, goal=goal, checks=checks, model=args.model,
                     effort=args.effort, workspace=args.workspace, adapter=adapter, plan_only=args.plan,
                     learn=args.learn, allow_experimental=args.allow_experimental, producer=args.producer,
                     new_submission=args.new_submission, identity=identity, limits=limits, **learning)
    if args.plan:
        print(dumps({'schema': 'oz.map.plan/1',
                     'learn': 'on (the plan lists the requests without rule coverage)' if args.learn else 'off',
                     'jobs': result['receipt']['jobs'], 'requests': result['requests'], 'plans': result['plans'],
                     'producer': result['receipt']['producer'], 'submission': result['receipt']['submission'],
                     'route': identity['route'], 'worker_hash': identity['worker_hash'],
                     'invalid_inputs': result['receipt']['invalid_inputs'], 'calls': 0},
                    ensure_ascii=False, separators=(',', ':')))
        return 0
    out = args.out or Path('results.jsonl')
    write_rows(result['rows'], out)
    if result.get('audits') is not None:
        write_rows(result['audits'], Path(out).with_name(Path(out).stem + '.audits.jsonl'))
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
    p.add_argument('--learn', action='store_true',
                   help='Experimental oz-rule/1 learning: bootstrap, admission, rule phase, blind audits (default off)')
    p.add_argument('--registry', type=Path, help='With --learn: owner-approved oz-registry/1 manifest (JSON file)')
    p.add_argument('--registry-sha256', help='With --learn: expected SHA256 of the manifest file bytes')
    p.add_argument('--audit-seed', type=int, help='With --learn: frozen integer seed of the blind audit selection')
    p.add_argument('--bootstrap-size', type=int,
                   help='With --learn: jobs answered by the one bootstrap call, 1..64 (default: one packet)')
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
