"""Offline scorer of a replication run directory (A4.6, A4.7, A4.10, A4.11). Standard library only.

    python -m bench.ozmap_rep.score <run dir>

Reads only the run directory (attempts.jsonl, cells/, prompts/, captures/, evidence/, preparation.json, the run bound
freeze and experiment record) plus the frozen code, gold oracle and preparation ledger, makes no external call and
runs no CLI, and rewrites report.json and report.md deterministically.

Accounting frozen before evaluation (A4.11): a cell's tokens are the charged tokens (inclusive input + output, A4.7)
of every physical call charged to it, failed and refused calls included; the shared bootstrap call is charged fully
to both cold B and cold C. Shared call tokens are attributed to operations in proportion to the call's records of
each operation (gates.attribute_tokens), so audit and fallback costs stay with the operation whose jobs they served
and nothing is dropped. Telemetry calls are reported separately and never enter a cell (B4).

Makespan (council round 1, item 14): the real submission to resolution time of the cell's work, the sum of its work
windows (each invocation from the start of its work to the written result, local preparation, parsing, admission,
rule execution, audits, delivery and launch skew included), plus the bootstrap cell's windows for cold B and C. The
child execution time (sum over launch groups of the longest call) is reported separately and never gated.

Fail closed execution (A4.14.1): the preserved records of every stopped cell are scored like any other. A leakage or
isolation signal, a demonstrated accounting failure or an unsettled call (uncertainty whether a tool executed) makes a
stopped cell invalid, not merely interrupted; only a stopped cell without such a finding is reported interrupted, which
leaves its comparisons inconclusive (A4.3, A4.11). A run stop (containment not established) fails isolation.

Claims need the artifact chain (item 10): every capture hashes to its attempt, the attempt's outcome, usage and
answers are derived again from the capture, the cell's answers come from those calls (or from the bootstrap, or from
the admitted rule applied again), admission records are reproduced, the launch identity matches the run bound freeze,
and for a live run the frozen inputs still match the freeze bound to the run. A simulation (fake mode) is never
evidence.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path
import sys

from . import bootstrap, config, gates, prompts, rules, workload
from . import events as events_mod
from .run import _read_json, cell_specs, jsonl

SCHEMA = 'ozmap-rep/1'
RETRYABLE_OUTCOMES = ('infrastructure_failure', 'not_launched')
NON_EVALUATION = ('telemetry', 'features')


def _canon(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _groups_makespan(attempts):
    """Child execution time: sum over launch groups (calls launched together on the four slots) of the longest call
    in the group. Reported only; the gated makespan is the work window time."""
    groups = {}
    for a in attempts:
        groups.setdefault(a.get('group') or a.get('call_id'), []).append(float(a.get('elapsed_s') or 0.0))
    return round(sum(max(v) for v in groups.values()), 3) if groups else 0.0


def _windows(run_dir, cid):
    return jsonl(Path(run_dir) / 'cells' / cid / 'windows.jsonl')


def _t(value):
    from .run import _parse_time
    return _parse_time(value)


def _union(intervals):
    total, cur = 0.0, None
    for start, end in sorted(intervals):
        if cur is None or start > cur[1]:
            if cur is not None:
                total += (cur[1] - cur[0]).total_seconds()
            cur = [start, end]
        else:
            cur[1] = max(cur[1], end)
    if cur is not None:
        total += (cur[1] - cur[0]).total_seconds()
    return total


def _window_spans(run_dir, ids, rows):
    """The gated makespan of a cell (council round 2, item 14): the union of its work windows (each opened before
    the invocation's work and closed after its result was delivered; overlapping windows merge, never sum), with a
    lower and an upper bound when a crashed invocation's window was closed with bounds (A4.14.1). Every attempt must start inside a window; an open
    window without a close, a missing window or an attempt outside every window makes the evidence incomplete."""
    exact, lower, upper, problems = [], [], [], []
    bounded = False
    for cid in ids:
        rows_w = _windows(run_dir, cid)
        opens = {r.get('invocation'): r for r in rows_w if r.get('event') == 'open'}
        closes = {r.get('invocation'): r for r in rows_w if r.get('event') == 'close'}
        for inv, o in opens.items():
            start = _t(o.get('started_at'))
            c = closes.get(inv)
            if start is None or c is None:
                problems.append(f'{cid}: a work window without a close ({inv})')
                continue
            if c.get('reconstructed'):
                lo, hi = _t(c.get('ended_at_lower')), _t(c.get('ended_at_upper'))
                if lo is None or hi is None or lo < start or hi < lo:
                    problems.append(f'{cid}: a bounded work window without consistent bounds ({inv})')
                    continue
                bounded = True
                lower.append((start, lo))
                upper.append((start, hi))
                exact.append((start, hi))
            else:
                end = _t(c.get('ended_at'))
                if end is None or end < start:
                    problems.append(f'{cid}: a work window with an inconsistent end ({inv})')
                    continue
                exact.append((start, end))
                lower.append((start, end))
                upper.append((start, end))
        legacy = [r for r in rows_w if r.get('event') is None]
        if legacy:
            problems.append(f'{cid}: work windows without open and close records')
    if rows and not exact:
        problems.append('no work window covers the cell')
    for a in rows:
        st = _t(a.get('started_at'))
        if st is None or not any(s <= st <= e for s, e in upper):
            problems.append(f"{a.get('call_id')}: the attempt is outside every work window")
    out = {'exact': _union(exact) if exact else None, 'lower': _union(lower) if lower else None,
           'upper': _union(upper) if upper else None, 'problems': problems,
           'timing': 'bounded' if bounded else 'exact'}
    if out['exact'] is None:
        out['exact'] = 0.0
    return out


def _attempt_ops_tokens(a, field='charged_tokens'):
    recs = a.get('records') or {}
    return gates.attribute_tokens(int(a.get(field) or 0), {op: n for op, n in sorted(recs.items())})


def _evidence_ok(run_dir, a):
    p = Path(run_dir) / 'prompts' / f"{a['call_id']}.txt"
    if not p.exists() or prompts.sha256(p.read_text(encoding='utf-8')) != a.get('prompt_sha256'):
        return False
    launch = _read_json(Path(run_dir) / 'evidence' / 'launch' / f"{a['call_id']}.json")
    if a.get('cell') not in NON_EVALUATION and (launch is None or launch.get('problems')):
        return False
    return True


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _norm_sha(path):
    data = Path(path).read_bytes()
    if str(path).endswith(('.py', '.md', '.json', '.txt')):
        data = data.replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------------------------------------- artifact chain

def _capture_text(run_dir, cid):
    out_path, err_path = Path(run_dir) / 'captures' / f'{cid}.stdout', Path(run_dir) / 'captures' / f'{cid}.stderr'
    if not out_path.exists() or not err_path.exists():
        return None
    return out_path.read_bytes().decode('utf-8'), err_path.read_bytes().decode('utf-8')


def _derive(run_dir, a):
    """(problems, derived) of one attempt from its capture: the judged outcome, reply, usage and verdict."""
    from . import run as run_mod
    cid = a['call_id']
    text = _capture_text(run_dir, cid)
    if text is None:
        return [f'{cid}: capture missing'], None
    stdout, stderr = text
    problems = []
    if prompts.sha256(stdout) != a.get('stdout_sha256'):
        problems.append(f'{cid}: stdout capture does not hash to its attempt')
    if a.get('stderr_sha256') is not None and prompts.sha256(stderr) != a.get('stderr_sha256'):
        problems.append(f'{cid}: stderr capture does not hash to its attempt')
    raw = {'stdout': stdout, 'stderr': stderr, 'exit_code': a.get('exit_code'), 'timed_out': a.get('timed_out')}
    judge = run_mod.judge_codex if a.get('backend') == 'codex' else run_mod.judge_sonnet
    outcome, reply, usage_raw, cls, _ = judge(raw)
    return problems, {'outcome': outcome, 'reply': reply, 'usage_raw': usage_raw, 'cls': cls}


ACCOUNTING_FIELDS = ('usage', 'usage_status', 'reasoning_issue', 'additive_tokens', 'charged_tokens',
                     'cache_certified', 'visible_tokens')


def _rejudge(run_dir, a, derived=None, counts=None, live=False, proposals=None):
    """Problems found by deriving an attempt's outcome, verdict, every accounting field (council round 2, item 10:
    decoded usage, usage status, reasoning certification, additive and charged tokens, cache certification) and its
    answers and bootstrap proposals again from its capture, with the frozen predicates evaluated by the scorer."""
    from . import run as run_mod
    from . import usage as usage_mod
    run_dir = Path(run_dir)
    cid = a['call_id']
    if derived is None:
        problems, derived = _derive(run_dir, a)
    else:
        problems, derived = derived
    if derived is None:
        return problems
    problems = list(problems)
    outcome, reply, usage_raw, cls = derived['outcome'], derived['reply'], derived['usage_raw'], derived['cls']
    want = a.get('outcome')
    derived_outcome = ('ok' if want in ('malformed', 'malformed_reply', 'malformed_answers') else want)
    if want == 'unsettled':
        # A4.14.1 (Astra council round 3, item 10): the stream of a killed child without complete terminal evidence
        # is recorded unsettled and uncertain, whatever the partial stream alone would judge; only a delivered
        # terminal outcome in the capture would contradict that
        if outcome in ('ok', 'refused', 'executed', 'auth_failure'):
            problems.append(f'{cid}: the capture judges {outcome!r}, the attempt says unsettled')
    elif outcome != derived_outcome:
        problems.append(f'{cid}: the capture judges {outcome!r}, the attempt says {want!r}')
    if want != 'unsettled' and cls['verdict'] != (a.get('events') or {}).get('verdict'):
        problems.append(f'{cid}: the capture event verdict differs from the attempt')
    if _canon(usage_raw) != _canon(a.get('usage_raw')):
        problems.append(f'{cid}: the attempt usage does not derive from the capture')
    certified = usage_mod.cache_certified_for_route() if a.get('backend') == 'codex' else None
    count = (lambda texts: [(counts or {}).get(t) for t in texts]) if counts is not None else None
    if live and a.get('backend') == 'codex' and isinstance(reply, str) and (counts or {}).get(reply) is None:
        problems.append(f'{cid}: the pinned tokenizer is unavailable to the scorer; reasoning certification cannot be '
                        f'reproduced')
    acct = run_mod.account_usage(a.get('backend'), usage_raw, reply, certified, count=count)
    for field in ACCOUNTING_FIELDS:
        if _canon(acct[field]) != _canon(a.get(field)):
            problems.append(f'{cid}: {field} does not derive from the capture with the frozen predicates')
    call = _read_json(run_dir / 'cells' / a.get('cell', '') / 'calls' / f'{cid}.json')
    if call is None:
        problems.append(f'{cid}: parsed call record missing')
        return problems
    if a.get('cell') in NON_EVALUATION:
        return problems
    if outcome != 'ok':
        if call.get('answers'):
            problems.append(f'{cid}: answers recorded for a call without an accepted reply')
        return problems
    ids = list(a.get('job_ids') or [])
    mapping = dict(zip(prompts.packet_ids(len(ids)), ids))
    text = reply
    if a.get('bootstrap'):
        try:
            text, proposed = prompts.parse_bootstrap(reply, prompts.bootstrap_config(a.get('workload'))['ops'])
        except prompts.Malformed:
            text, proposed = None, None
        if _canon(proposed) != _canon(call.get('rules')):
            problems.append(f'{cid}: the recorded bootstrap proposals are not the bytes the capture holds')
        if proposals is not None:
            proposals[cid] = proposed
    answers = prompts.parse_answers(text, mapping)[0] if isinstance(text, str) else {}
    if _canon(answers) != _canon(call.get('answers') or {}):
        problems.append(f'{cid}: the recorded answers do not derive from the capture')
    return problems



def _input_problems(run_dir, a):
    """Astra council round 3, item 16: the job ids, their order and the per operation records of an evaluation
    attempt are reconstructed from the frozen workload and must reproduce the prompt that was sent (its hash is
    checked against the prompt file by _evidence_ok); `records` decides the attribution of the call's costs to R."""
    cid = a.get('call_id')
    ids = list(a.get('job_ids') or [])
    if not ids or a.get('cell') in NON_EVALUATION:
        return []
    try:
        by_id = {j['id']: j for j in workload.jobs_for(a.get('workload'), a.get('wave'))}
    except (RuntimeError, ValueError, KeyError) as exc:
        return [f'{cid}: the frozen workload cannot be loaded to reconstruct its input ({type(exc).__name__})']
    if any(j not in by_id for j in ids):
        return [f'{cid}: job ids outside the frozen workload of its wave']
    jobs = [by_id[j] for j in ids]
    problems = []
    records = {op: sum(1 for j in jobs if j['op'] == op) for op in sorted({j['op'] for j in jobs})}
    if _canon(records) != _canon(a.get('records') or {}):
        problems.append(f'{cid}: the per operation records do not derive from its job ids')
    inp = prompts.model_input(jobs, a.get('workload'), bootstrap=bool(a.get('bootstrap')))
    if prompts.sha256(prompts.prompt_record(inp)) != a.get('prompt_sha256'):
        problems.append(f'{cid}: its job ids do not reproduce the prompt that was sent')
    return problems


def _required_audits(spec, asts, jobs, boot_ids):
    """The audit sample the frozen rule phase draws for a B or C cell from the jobs the admitted rules cover."""
    import oz_rulephase
    covered = []
    for j in jobs:
        if j['id'] in boot_ids or j['op'] not in asts:
            continue
        value, _ = rules.apply(j['op'], asts[j['op']], j['text'])
        if value is not None:
            covered.append(j['id'])
    if not covered:
        return set()
    return set(oz_rulephase.select_audits(sorted(covered), config.SEED, config.AUDITS))


def _rule_asts(results, prefix, boot_props=None):
    """The admitted rule ASTs of a backend, taken from the capture derived bootstrap proposals (item 10) when they
    are known; a result.json AST that differs from the captured proposal is never used."""
    boot = results.get(f'{prefix}-bootstrap') or {}
    props = (boot_props or {}).get(f'{prefix}-bootstrap')
    out = {}
    for op, row in (boot.get('rules') or {}).items():
        if row.get('proposed') and (row.get('admission') or {}).get('status') == 'accepted' and row.get('ast_b64'):
            if props is not None:
                entry = (props or {}).get(op) or {}
                if entry.get('ast_b64') != row.get('ast_b64'):
                    continue
            out[op] = base64.b64decode(row['ast_b64'])
    return out


def _model_answers(run_dir, cid, calls_ok):
    """{job id: (answer, call id)} of every verified call record of a cell."""
    out = {}
    for p in sorted((Path(run_dir) / 'cells' / cid / 'calls').glob('*.json')):
        if p.stem not in calls_ok:
            continue
        rec = _read_json(p, {}) or {}
        for jid, v in (rec.get('answers') or {}).items():
            out[jid] = (v, p.stem)
    return out


def _cell_chain(run_dir, cid, spec, results, calls_ok, boot_props=None):
    """Problems of a cell's answers against the calls that produced them, the bootstrap and the rules; the bootstrap
    admission records are reproduced from the capture derived proposal bytes; audit dispositions are derived again
    from the verified audit calls, and no rule answer may come from an operation whose audit disagreed or stayed
    inconclusive (council round 2, item 10)."""
    run_dir = Path(run_dir)
    problems = []
    res = results.get(cid) or {}
    prefix = f"{spec['backend']}-{spec['workload']}"
    jobs = {j['id']: j for j in workload.jobs_for(spec['workload'], spec['wave'])} if spec['arm'] != 'telemetry' \
        else {}
    asts = _rule_asts(results, prefix, boot_props) if spec['workload'] == 'materials' else {}
    if spec['wave'] == 'warm' and spec['arm'] == 'C':
        # item 16: warm C may reuse only a rule cold C adopted (an audit that agreed), never one bootstrap accepted
        cold = (results.get(f'{prefix}-cold-C') or {}).get('rule_status') or {}
        asts = {op: ast for op, ast in asts.items() if cold.get(op) == 'adopted'}
    cache = {}
    for jid, row in (res.get('answers') or {}).items():
        src, call_id = row.get('source'), row.get('call_id')
        if src in ('model', 'bootstrap'):
            if not call_id:
                problems.append(f'{cid}/{jid}: a {src} answer without its call')
                continue
            owner = call_id.split('.r')[0]
            if call_id not in cache:
                cache[call_id] = _read_json(run_dir / 'cells' / owner / 'calls' / f'{call_id}.json') or {}
            if call_id not in calls_ok:
                problems.append(f'{cid}/{jid}: answer from {call_id}, which has no verified attempt')
            if _canon((cache[call_id].get('answers') or {}).get(jid)) != _canon(row.get('answer')):
                problems.append(f'{cid}/{jid}: the answer differs from its call record')
        elif src == 'rule':
            op = (jobs.get(jid) or {}).get('op')
            if op not in asts:
                problems.append(f'{cid}/{jid}: a rule answer without an admitted rule')
                continue
            value, _ = rules.apply(op, asts[op], jobs[jid]['text'])
            if _canon(value) != _canon(row.get('answer')):
                problems.append(f'{cid}/{jid}: the rule answer is not what the admitted rule gives')
        else:
            problems.append(f'{cid}/{jid}: unknown answer source {src!r}')
    if spec['arm'] in ('B', 'C') and spec['workload'] == 'materials' and res:
        boot_ids = set(workload.bootstrap_ids(spec['workload'])) if spec['wave'] == 'cold' else set()
        want = _required_audits(spec, asts, list(jobs.values()), boot_ids)
        if want != set((res.get('audits') or {}).keys()):
            problems.append(f'{cid}: the recorded audit set is not the frozen audit sample of the covered jobs '
                            f'({len(res.get("audits") or {})} recorded, {len(want)} required)')
    if spec['arm'] in ('B', 'C') and res.get('audits') is not None:
        model = _model_answers(run_dir, cid, calls_ok)
        bad_ops = set()
        for jid, disposition in sorted((res.get('audits') or {}).items()):
            job = jobs.get(jid)
            op = (job or {}).get('op')
            if job is None or op not in asts:
                problems.append(f'{cid}/{jid}: an audit of a job without an admitted rule')
                continue
            value, _ = rules.apply(op, asts[op], job['text'])
            again = 'inconclusive' if jid not in model else \
                'agree' if _canon(model[jid][0]) == _canon(value) else 'disagree'
            if again != disposition:
                problems.append(f'{cid}/{jid}: the audit disposition {disposition!r} is not reproduced ({again!r})')
            if again != 'agree':
                bad_ops.add(op)
        for jid, row in (res.get('answers') or {}).items():
            if row.get('source') == 'rule' and (jobs.get(jid) or {}).get('op') in bad_ops:
                problems.append(f'{cid}/{jid}: a rule answer of an operation whose audit did not agree')
    if spec['arm'] == 'bootstrap':
        props = (boot_props or {}).get(cid)
        for op, row in (res.get('rules') or {}).items():
            adm = row.get('admission') or {}
            if not row.get('proposed') or adm.get('status') in (None, 'not_evaluated') or \
                    spec['workload'] != 'materials':
                continue
            entry = (props or {}).get(op) if props is not None else None
            if props is not None and (entry or {}).get('ast_b64') != row.get('ast_b64'):
                problems.append(f'{cid}/{op}: the admitted proposal is not the bytes the bootstrap capture holds')
                continue
            again = rules.summary(rules.admit(op, base64.b64decode(row.get('ast_b64') or '')))
            if again.get('status') != adm.get('status'):
                problems.append(f'{cid}/{op}: the admission record is not reproduced ({again.get("status")} vs '
                                f'{adm.get("status")})')
    return problems


def _launch_problems(run_dir, a, bound):
    """Item 10: a live Codex attempt's launch identity against the freeze bound to the run."""
    launch = _read_json(Path(run_dir) / 'evidence' / 'launch' / f"{a['call_id']}.json") or {}
    codex = (bound or {}).get('codex') or {}
    problems = []
    if launch.get('exe_sha256') != codex.get('exe_sha256'):
        problems.append(f"{a['call_id']}: the launched executable is not the run bound freeze's")
    if launch.get('argv_sha256') != codex.get('argv_sha256'):
        problems.append(f"{a['call_id']}: the launch argv is not the run bound freeze's")
    ident = launch.get('exe_identity') or {}
    want = codex.get('identity') or {}
    if (ident.get('payload') or {}) != (want.get('payload') or {}) or ident.get('targets') != want.get('targets'):
        problems.append(f"{a['call_id']}: the launched companion manifest is not the run bound freeze's")
    return problems


def _freeze_problems(run_dir, experiment):
    """For a live run: the freeze bound to the run (D/freeze.json, hash in experiment.json) and the frozen inputs now
    (file hashes only: no executable is run here)."""
    run_dir = Path(run_dir)
    bound = run_dir / 'freeze.json'
    if not bound.exists():
        return ['no freeze bound to this run (D/freeze.json missing)']
    problems = []
    if _file_sha(bound) != (experiment or {}).get('freeze_sha256'):
        problems.append('the run bound freeze does not match the freeze recorded at the first dispatch')
    doc = _read_json(bound, {}) or {}
    for rel, digest in sorted((doc.get('files') or {}).items()):
        path = config.REPO / rel
        if not path.exists() or _norm_sha(path) != digest:
            problems.append(f'{rel} differs from the run bound freeze')
    if doc.get('classification_sha256') and _file_sha(config.CLASSIFICATION_FILE) != doc['classification_sha256']:
        problems.append('classification differs from the run bound freeze')
    wl = hashlib.sha256(json.dumps(workload.materials(), sort_keys=True).encode()).hexdigest()
    if doc.get('workload_sha256') != wl:
        problems.append('workload differs from the run bound freeze')
    if doc.get('registry_manifest_sha256') != rules.manifest_sha256():
        problems.append('registry manifest differs from the run bound freeze')
    # closure round 1 (O5): the bound rulings, D6 with its focused verification and independent operation
    # attestation included, are checked again at scoring
    from . import rulings as rulings_mod
    problems += rulings_mod.bound_problems((doc.get('signed_exceptions') or {}).get('rulings'))
    return problems


# ------------------------------------------------------------------------------------------------- scoring

def score_run(run_dir, write=False) -> dict:
    run_dir = Path(run_dir)
    all_attempts = jsonl(run_dir / 'attempts.jsonl')
    attempts = [a for a in all_attempts if a.get('cell') not in NON_EVALUATION]
    telemetry_rows = [a for a in all_attempts if a.get('cell') in NON_EVALUATION]
    specs = {s['id']: s for s in cell_specs()}
    states = {cid: (_read_json(run_dir / 'cells' / cid / 'state.json', {}) or {}).get('state', 'pending')
              for cid in specs}
    results = {cid: _read_json(run_dir / 'cells' / cid / 'result.json', {}) or {} for cid in specs}
    by_cell = {cid: [a for a in attempts if a.get('cell') == cid] for cid in specs}
    experiment = _read_json(run_dir / 'experiment.json') or {}
    first_call = min((a.get('started_at') for a in attempts if a.get('started_at')), default=None)
    R_set, class_problems = bootstrap.validate_classification(first_learner_call=first_call)
    R = sorted(R_set) if R_set is not None else []
    r_problem = '; '.join(class_problems) if class_problems else None
    admission = workload.materials()['admission']

    # ------------------------------------------------------------------------------------------- validity
    leakage, accounting, isolation_problems, simulation, artifact = [], [], [], [], []
    # Closure round 1 (O4, RTC1.1): every finding is attributed to its cells where it is produced, by the structured
    # cell field of the record it comes from, never by matching message text against call ids or marker names
    cell_findings = {}

    def flag(target, message, *cells):
        target.append(message)
        for c in cells:
            if c:
                cell_findings.setdefault(c, []).append(message)

    def flag_all(target, messages, *cells):
        for m in messages:
            flag(target, m, *cells)

    call_cell = {a.get('call_id'): a.get('cell') for a in all_attempts}
    for a in attempts:
        ev = a.get('events') or {}
        c = a.get('cell')
        if ev.get('verdict') in ('executed', 'uncertain'):
            flag(leakage, f"{a['call_id']}: tool event verdict {ev['verdict']} (A4.3)", c)
        if a.get('outcome') == 'unsettled' and ev.get('verdict') not in ('executed', 'uncertain'):
            flag(leakage, f"{a['call_id']}: unsettled call state, uncertain whether a tool executed (A4.14.1, A4.3)",
                 c)
        if a.get('raw_mismatch'):
            flag(leakage, f"{a['call_id']}: the recovered capture differs from the raw stream (uncertain, A4.3)", c)
        if (a.get('usage') or {}).get('status') == 'invalid':
            flag(accounting, f"{a['call_id']}: usage invalid ({'; '.join(a['usage'].get('problems') or [])})", c)
        if a.get('backend') == 'codex' and not _evidence_ok(run_dir, a):
            flag(isolation_problems, f"{a['call_id']}: launch evidence missing or not clean", c)
    for a in all_attempts:
        if a.get('credential_disclosure'):
            flag(isolation_problems, f"{a['call_id']}: credential material was redacted from its output (A4.2)",
                 a.get('cell'))
        if a.get('mode') != 'live':
            simulation.append(f"{a.get('call_id')}: mode {a.get('mode')!r}")
    if any(not s.get('external') for s in jsonl(run_dir / 'spawns.jsonl')):
        simulation.append('spawns of harness fakes (external false)')
    if (run_dir / 'fake').exists():
        simulation.append('the run directory holds fake executables (D/fake)')
    if experiment.get('simulation') or (experiment and experiment.get('mode') != 'live'):
        simulation.append(f"the run is bound to mode {experiment.get('mode')!r}")
    simulation = sorted(set(simulation))[:50] if simulation else []

    # RT1.2: repeated call ids, more than one terminal attempt per batch, an allocation above nominal plus reserve
    seen, seen_cells, terminal = {}, {}, {}
    for a in all_attempts:
        cid = a.get('call_id')
        seen[cid] = seen.get(cid, 0) + 1
        seen_cells.setdefault(cid, set()).add(a.get('cell'))
        if a.get('outcome') not in RETRYABLE_OUTCOMES:
            key = (a.get('cell'), a.get('batch'))
            terminal[key] = terminal.get(key, 0) + 1
    for cid, n in sorted(seen.items(), key=str):
        if n > 1:
            flag(accounting, f'{cid}: call id recorded {n} times', *sorted(seen_cells[cid], key=str))
    for k, n in sorted(terminal.items(), key=str):
        if n > 1:
            flag(accounting, f'{k[0]} {k[1]}: {n} terminal attempts', k[0])
    charged, charged_cells = {}, {}
    for a in attempts:
        key = (a.get('backend'), a.get('workload'), a.get('allocation'))
        charged[key] = charged.get(key, 0) + 1
        charged_cells.setdefault(key, set()).add(a.get('cell'))
    for (b, w, al), n in sorted(charged.items(), key=str):
        nominal = config.ALLOCATIONS.get(f'{b}/{w}', {}).get(al)
        if nominal is not None and n > nominal + config.RESERVE_PER_ALLOCATION:
            flag(accounting, f'{b}/{w} {al}: {n} physical calls above nominal {nominal} plus reserve',
                 *sorted(charged_cells[(b, w, al)], key=str))
    # A4.14.1: markers stay preserved with a stopped cell; a call marker without its attempt row is a charged call
    # whose accounting was not recorded, and a probe marker is a local probe in an unknown state
    recorded_uids = {a.get('attempt_uid') or a.get('call_id') for a in all_attempts}
    lost_markers, open_probes, lost_cells, probe_cells = [], [], set(), set()
    for mp in sorted(run_dir.glob('cells/*/inflight/*.json')):
        m = _read_json(mp)
        owner = mp.parent.parent.name
        if not isinstance(m, dict):
            lost_markers.append(mp.name)
            lost_cells.add(owner)
        elif m.get('marker') == 'probe':
            open_probes.append(mp.name)
            probe_cells.add(owner)
        elif (m.get('attempt_uid') or m.get('call_id')) not in recorded_uids:
            lost_markers.append(mp.name)
            lost_cells.add(owner)
    if lost_markers:
        flag(accounting, f'in-flight markers without an attempt (charged calls whose accounting is not recorded): '
                         f'{lost_markers[:5]}', *sorted(lost_cells))
    if open_probes:
        flag(isolation_problems, f'local probes ended in an unknown state (A4.14.1): {open_probes[:5]}',
             *sorted(probe_cells))
    stop_doc = _read_json(run_dir / 'run-stop.json')
    if stop_doc:
        flag(isolation_problems, f"the run is stopped: containment of outstanding work was not established "
                                 f"(A4.14.1): {str(stop_doc.get('reason'))[:200]}",
             stop_doc.get('cell') if isinstance(stop_doc, dict) else None)
    # Astra council round 3, item 15: every probe disclosure fails isolation, and every capture's own redaction
    # record is checked, whatever the attempt's disclosure flag says
    for r in jsonl(run_dir / 'evidence' / 'probe-disclosures.jsonl'):
        flag(isolation_problems, f"a {r.get('probe')} probe of {r.get('cell')}: credential material was redacted "
                                 f"from its output (A4.2)", r.get('cell'))
    # closure round 1 (O3): a local probe whose output completeness could not be established
    for r in jsonl(run_dir / 'evidence' / 'probe-uncertain.jsonl'):
        flag(isolation_problems, f"a {r.get('probe')} probe of {r.get('cell')}: its output could not be established "
                                 f"complete, so a credential disclosure cannot be excluded (A4.2, A4.14.1)",
             r.get('cell'))
    flagged = {a.get('call_id') for a in all_attempts if a.get('credential_disclosure')}
    for mp in sorted((run_dir / 'captures').glob('*.meta.json')) if (run_dir / 'captures').exists() else []:
        meta = _read_json(mp, {}) or {}
        red = meta.get('redaction') if isinstance(meta.get('redaction'), dict) else {}
        if (red.get('redactions') or 0) > 0 and meta.get('call_id') not in flagged:
            flag(isolation_problems, f"{meta.get('call_id')}: its capture record shows redacted credential material "
                                     f"the attempt does not flag (A4.2)",
                 meta.get('cell') or call_cell.get(meta.get('call_id')))
    ledger_path = experiment.get('live_ledger')
    experiment_view = None
    if ledger_path:
        from .run import ledger_rows, predecessor_dirs
        here = str(run_dir.resolve())
        rows_l, bad_lines = ledger_rows(ledger_path)
        accounting += bad_lines
        known = {a.get('attempt_uid') or a.get('call_id') for a in all_attempts}
        lost_rows = [r for r in rows_l
                     if r.get('run_dir') == here and (r.get('attempt_uid') or r.get('call_id')) not in known]
        lost = sorted(r.get('call_id') for r in lost_rows)
        if lost:
            flag(accounting, f'experiment ledger calls missing from the run directory: {lost[:5]}',
                 *sorted({r.get('cell') or call_cell.get(r.get('call_id')) for r in lost_rows}, key=str))
        # Astra council round 3, item 11: and the reverse, a live attempt whose debit the ledger lacks
        in_ledger = {r.get('attempt_uid') for r in rows_l if r.get('attempt_uid')}
        unledgered_rows = [a for a in all_attempts if a.get('mode') == 'live'
                           and a.get('attempt_uid') and a.get('attempt_uid') not in in_ledger]
        unledgered = sorted(a.get('call_id') for a in unledgered_rows)
        if unledgered:
            flag(accounting, f'live attempts missing from the experiment ledger: {unledgered[:5]}',
                 *sorted({a.get('cell') for a in unledgered_rows}, key=str))
        # experiment wide (item 9, RT2.2): every allocation and the telemetry cap over every run directory
        totals, total_cells = {}, {}
        for r in rows_l:
            k = (r.get('backend'), r.get('workload'), r.get('allocation'), r.get('kind'))
            totals[k] = totals.get(k, 0) + 1
            if r.get('run_dir') == here:
                total_cells.setdefault(k[:3], set()).add(r.get('cell') or call_cell.get(r.get('call_id')))
        for (b, w, al, kind), n in sorted(totals.items(), key=str):
            nominal = config.ALLOCATIONS.get(f'{b}/{w}', {}).get(al)
            over = sorted(total_cells.get((b, w, al), set()) | charged_cells.get((b, w, al), set()), key=str)
            if kind == 'nominal' and nominal is not None and n > nominal:
                flag(accounting, f'experiment ledger: {b}/{w} {al}: {n} nominal calls above the allocation {nominal}',
                     *over)
            if kind == 'reserve' and n > config.RESERVE_PER_ALLOCATION:
                flag(accounting, f'experiment ledger: {b}/{w} {al}: {n} reserve calls above the reserve', *over)
        for b, cap in config.EVAL_CAPS.items():
            tel = sum(n for (bb, _, _, kind), n in totals.items() if bb == b and kind == 'telemetry')
            if tel > cap['telemetry']:
                flag(accounting, f'experiment ledger: {b} telemetry calls {tel} above the cap {cap["telemetry"]}',
                     *sorted({r.get('cell') for r in rows_l if r.get('backend') == b
                              and r.get('kind') == 'telemetry' and r.get('run_dir') == here}, key=str))
        # prior invalidating evidence is never omitted by changing directories (item 9)
        predecessors = predecessor_dirs(run_dir, ledger_path)
        for d in predecessors:
            prev = Path(d)
            if not (prev / 'attempts.jsonl').exists():
                accounting.append(f'predecessor run directory {d}: attempts missing (evidence withheld)')
                continue
            for a in jsonl(prev / 'attempts.jsonl'):
                if a.get('cell') in NON_EVALUATION:
                    continue
                ev = a.get('events') or {}
                if ev.get('verdict') in ('executed', 'uncertain') or a.get('raw_mismatch'):
                    flag(leakage, f"superseded {prev.name}: {a.get('call_id')}: tool event verdict "
                                  f"{ev.get('verdict')} (A4.3)", a.get('cell'))
            for p in sorted((prev / 'captures').glob('*.stdout')) if (prev / 'captures').exists() else []:
                meta = _read_json(p.with_name(p.stem + '.meta.json'), {}) or {}
                if meta.get('cell') in NON_EVALUATION:
                    continue
                v = events_mod.classify_stream(p.read_bytes().decode('utf-8', 'replace'))['verdict'] \
                    if not str(meta.get('cell', '')).startswith('sonnet') else None
                if v in ('executed', 'uncertain'):
                    flag(leakage, f'superseded {prev.name}: {p.stem}: capture verdict {v} (A4.3)', meta.get('cell'))
            if (prev / 'codex-stop.json').exists():
                isolation_problems.append(f'superseded {prev.name}: Codex evaluation was stopped (A4.2)')
            if (prev / 'safety-kill.json').exists():
                accounting.append(f'superseded {prev.name}: a safety kill was established (A4.11)')
        experiment_view = {'ledger_calls': len(rows_l), 'predecessors': predecessors,
                           'by_allocation': {'/'.join(str(x) for x in k): n for k, n in sorted(totals.items(),
                                                                                              key=str)}}

    for p in sorted((run_dir / 'prompts').glob('*.txt')) if (run_dir / 'prompts').exists() else []:
        if prompts.learner_prompt_leaks(p.read_text(encoding='utf-8'), admission):
            flag(leakage, f'{p.stem}: admission material in a model-bound prompt (A4.8)',
                 call_cell.get(p.stem) or next((c for c in specs if p.stem.startswith(f'{c}.')), None))
    if (run_dir / 'codex-stop.json').exists():
        codex_stop = _read_json(run_dir / 'codex-stop.json')
        flag(isolation_problems, 'Codex evaluation stopped by authentication reconciliation (A4.2)',
             codex_stop.get('cell') if isinstance(codex_stop, dict) else None)
    live = experiment.get('mode') == 'live'
    live_mode = live
    if live:
        from .run import telemetry_problems
        tel = telemetry_problems(run_dir)
        if tel:
            isolation_problems.append(f'telemetry certificate not established: {tel[:3]}')
        gates_ok = {r.get('cell') for r in jsonl(run_dir / 'evidence' / 'wave-gates.jsonl') if r.get('ok')}
        for cid, rows in by_cell.items():
            if specs[cid]['backend'] != 'codex' or not rows:
                continue
            if cid not in gates_ok:
                flag(isolation_problems, f'{cid}: no passing wave gate record', cid)
            feat = _read_json(run_dir / 'evidence' / f'features-{cid}.json')
            if not feat:
                flag(isolation_problems, f'{cid}: no features record', cid)
            elif feat.get('ok') is not True:
                flag(isolation_problems, f'{cid}: the features record did not pass (A4.2)', cid)
            bound_freeze = _read_json(run_dir / 'freeze.json', {}) or {}
            for a in rows:
                if a.get('outcome') not in ('not_launched',):
                    flag_all(isolation_problems, _launch_problems(run_dir, a, bound_freeze), cid)
                if a.get('outcome') not in ('interrupted', 'not_launched', 'unsettled') and not a.get('auth'):
                    flag(isolation_problems, f"{a['call_id']}: no authentication record", cid)

    # artifact chain (item 10)
    verified, proposals, derived = set(), {}, {}
    for a in all_attempts:
        has_capture = _capture_text(run_dir, a['call_id']) is not None
        if a.get('outcome') == 'not_launched' or (a.get('outcome') in ('interrupted', 'unsettled')
                                                  and not has_capture):
            continue
        derived[a['call_id']] = _derive(run_dir, a)
    replies = sorted({d[1]['reply'] for d in derived.values() if d[1] and isinstance(d[1]['reply'], str)
                      and d[1]['reply']})
    from . import tokenizer as tokenizer_mod
    counts = dict(zip(replies, tokenizer_mod.count(replies))) if replies else {}
    for a in all_attempts:
        if a.get('cell') not in NON_EVALUATION and a.get('outcome') != 'not_launched':
            flag_all(artifact, _input_problems(run_dir, a), a.get('cell'))
        if a['call_id'] not in derived:
            continue
        found = _rejudge(run_dir, a, derived=derived[a['call_id']], counts=counts, live=live_mode,
                         proposals=proposals)
        flag_all(artifact, found, a.get('cell'))
        if not found:
            verified.add(a['call_id'])
    # Every capture is judged, those of stopped cells included (council round 2, RT2.1; A4.14.1): execution or
    # uncertainty in any captured evaluation stream is leakage, whatever its attempt row says.
    recorded = {a.get('call_id'): a for a in all_attempts}
    if (run_dir / 'captures').exists():
        for p in sorted((run_dir / 'captures').glob('*.stdout')):
            row = recorded.get(p.stem)
            meta = _read_json(p.with_name(p.stem + '.meta.json'), {}) or {}
            cell = (row or {}).get('cell') or meta.get('cell') \
                or next((c for c in specs if p.stem.startswith(f'{c}.')), None)
            if row is None:
                flag(artifact, f'{p.stem}: a capture without an attempt line', cell)
            if cell in NON_EVALUATION:
                continue
            backend = (row or {}).get('backend') or (specs.get(cell) or {}).get('backend', 'codex')
            if backend != 'codex':
                continue
            verdict = events_mod.classify_stream(p.read_bytes().decode('utf-8', 'replace'))['verdict']
            if verdict in ('executed', 'uncertain'):
                note = f'{p.stem}: captured stream verdict {verdict} (A4.3)'
                if not any(x.startswith(f'{p.stem}: tool event verdict {verdict}') for x in leakage):
                    flag(leakage, note, cell)
                elif cell:
                    cell_findings.setdefault(cell, []).append(note)
    boot_props = {}
    for cid, spec in specs.items():
        if spec['arm'] == 'bootstrap':
            done = [a for a in by_cell[cid] if a.get('outcome') not in RETRYABLE_OUTCOMES]
            if done and done[-1]['call_id'] in proposals:
                boot_props[cid] = proposals[done[-1]['call_id']]
            elif done:
                boot_props[cid] = {}
    for cid, spec in specs.items():
        if results.get(cid):
            flag_all(artifact, _cell_chain(run_dir, cid, spec, results, verified, boot_props), cid)
    freeze_problems = _freeze_problems(run_dir, experiment) if live else []
    # A4.14.1: the preserved records of every stopped cell decide its validity first. A cell is stopped when it is
    # neither complete nor settled and holds a stop record, was running, holds markers or has attempts (the crash_scan
    # predicate, read only: a cell the runner left `running` by a crash is scored as stopped before any later
    # admission writes its INTERRUPTED.json). Its findings are the structured entries attributed to it above.
    invalid_cells, stopped = {}, []
    attempt_cells = {a.get('cell') for a in all_attempts}
    # closure round 2 (N1): every administrative cell that ran (telemetry, features) is in the same stopped cell
    # validity inventory, so a stopped one gets its own findings. It stays outside every evaluation performance
    # computation (specs, results, by_cell, the cell summaries and the gates read evaluation cells only).
    for cid in NON_EVALUATION:
        cdir = run_dir / 'cells' / cid
        if cdir.is_dir():
            if (cdir / 'DONE.json').exists():
                states[cid] = 'complete'
            elif (cdir / 'SETTLED.json').exists():
                states[cid] = 'incomplete'
            else:
                states[cid] = (_read_json(cdir / 'state.json', {}) or {}).get('state', 'pending')
    for cid, st in states.items():
        cdir = run_dir / 'cells' / cid
        if (cdir / 'DONE.json').exists() or (cdir / 'SETTLED.json').exists() or st in ('complete',):
            continue
        if (cdir / 'INTERRUPTED.json').exists() or st in ('interrupted', 'running') \
                or any(cdir.glob('inflight/*.json')) or cid in attempt_cells:
            stopped.append(cid)
    for cid in stopped:
        if cell_findings.get(cid):
            invalid_cells[cid] = sorted(set(cell_findings[cid]))[:10]
            states[cid] = 'invalid'
        else:
            states[cid] = 'interrupted'
    interrupted = sorted(cid for cid, st in states.items() if st == 'interrupted')

    # ------------------------------------------------------------------------------------------- bootstrap
    boot_validity, boot_detail = {}, {}
    for key in ('codex/materials', 'sonnet/materials', 'codex/boolq'):
        backend, wl = key.split('/')
        prefix = f'{backend}-{wl}'
        res = results[f'{prefix}-bootstrap']
        cold_a = results[f'{prefix}-cold-A'].get('answers') or {}
        jobs = {j['id']: j for j in workload.jobs_for(wl, 'cold')}
        gold_errors, disagreements = {}, {}
        for jid, row in (res.get('answers') or {}).items():
            op = jobs[jid]['op']
            if _canon(row['answer']) != _canon(workload.gold(jobs[jid])):
                gold_errors[op] = gold_errors.get(op, 0) + 1
            other = cold_a.get(jid)
            if other is not None and _canon(other['answer']) != _canon(row['answer']):
                disagreements[op] = disagreements.get(op, 0) + 1
        proposed = {op: bool(r.get('proposed')) for op, r in (res.get('rules') or {}).items()}
        status = res.get('status') or 'missing'
        if states[f'{prefix}-bootstrap'] != 'complete':
            status = status if status != 'ok' else 'incomplete'
        out = bootstrap.assess(set(R) if wl == 'materials' else set(), proposed, gold_errors, disagreements, status)
        admitted = sorted(op for op, r in (res.get('rules') or {}).items()
                          if (r.get('admission') or {}).get('status') == 'accepted')
        boot_validity[key] = {'efficiency_valid': out['efficiency_valid'],
                              'completion_failure': out['completion_failure']}
        boot_detail[key] = dict(out, status=status, proposed=proposed, admitted=admitted,
                                classification=bootstrap.admission_report(R, admitted) if wl == 'materials' else None,
                                rules={op: {k: r.get(k) for k in ('proposed', 'ast_sha256', 'bytes', 'admission')}
                                       for op, r in (res.get('rules') or {}).items()})

    # ------------------------------------------------------------------------------------------- cells
    sim_cells = {a.get('cell') for a in all_attempts if a.get('mode') != 'live'}

    def cell_summary(main):
        spec = specs[main]
        prefix = f"{spec['backend']}-{spec['workload']}"
        ids = [main] + ([f'{prefix}-bootstrap'] if spec['wave'] == 'cold' and spec['arm'] in ('B', 'C') else [])
        rows = [a for cid in ids for a in by_cell[cid]]
        jobs = workload.jobs_for(spec['workload'], spec['wave'])
        by_id = {j['id']: j for j in jobs}
        answers = results[main].get('answers') or {}
        ops = {}
        correct = unresolved = rule_errors = 0
        for j in jobs:
            o = ops.setdefault(j['op'], {'jobs': 0, 'correct': 0, 'unresolved': 0, 'tokens': 0, 'additive': 0,
                                         'unresolved_audits': 0})
            o['jobs'] += 1
            row = answers.get(j['id'])
            if row is None:
                unresolved += 1
                o['unresolved'] += 1
                continue
            ok = _canon(row['answer']) == _canon(workload.gold(j))
            correct += ok
            o['correct'] += ok
            if row.get('source') == 'rule' and not ok:
                rule_errors += 1
        open_audits = list(results[main].get('unresolved_audits') or [])
        for jid in open_audits:
            op = (by_id.get(jid) or {}).get('op')
            if op in ops:
                ops[op]['unresolved_audits'] += 1
        for a in rows:
            for field, target in (('charged_tokens', 'tokens'), ('additive_tokens', 'additive')):
                for op, t in _attempt_ops_tokens(a, field).items():
                    ops[op if op in ops else sorted(ops)[0]][target] += t
        tokens = sum(int(a.get('charged_tokens') or 0) for a in rows)
        used = [a for a in rows if a.get('outcome') != 'not_launched']
        usage_ok = bool(used) and all(a.get('usage_status') == 'complete' for a in used)
        state = states[main]
        for cid in ids[1:]:
            if states[cid] != 'complete':
                state = states[cid]
        evidence_ok = state == 'complete' and all(_evidence_ok(run_dir, a) for a in rows)
        evidence = 'complete' if evidence_ok else 'incomplete'
        if any(cid in sim_cells for cid in ids):
            evidence = 'simulation'
        span = _window_spans(run_dir, ids, rows)
        makespan, lower, upper = span['exact'], span['lower'], span['upper']
        if span['problems']:
            if evidence == 'complete':
                evidence = 'incomplete'
            makespan = makespan if makespan is not None else sum(_groups_makespan(by_cell[cid]) for cid in ids)
        child = sum(_groups_makespan(by_cell[cid]) for cid in ids)
        return {'jobs': len(jobs), 'correct': correct, 'unresolved': unresolved, 'tokens': tokens,
                'additive_tokens': sum(int(a.get('additive_tokens') or 0) for a in rows),
                'makespan_s': round(makespan, 3), 'child_makespan_s': round(child, 3),
                # outward rounding (Astra council round 3, item 17): the reference arm's lower bound rounds down
                # and the tested arm's upper bound up, so rounding never helps a gate
                'makespan_lower_s': None if lower is None else math.floor(lower * 1000) / 1000,
                'makespan_upper_s': None if upper is None else math.ceil(upper * 1000) / 1000,
                'timing': span['timing'], 'timing_problems': span['problems'][:5],
                'usage': 'complete' if usage_ok else 'incomplete'
                if any(a.get('usage_status') == 'incomplete' for a in used) or not used else 'unverified',
                'evidence': evidence, 'state': state, 'rule_errors': rule_errors,
                'unresolved_audits': len(open_audits),
                'physical_calls': len(rows), 'rule_answers': sum(1 for r in answers.values()
                                                                 if r.get('source') == 'rule'),
                'ops': {op: {k: v[k] for k in ('jobs', 'correct', 'tokens')} for op, v in sorted(ops.items())}
                if spec['workload'] == 'materials' else {}, '_ops': ops}

    cells, r_cells, r_cells_additive = {}, {}, {}
    for cid, spec in specs.items():
        if spec['arm'] == 'bootstrap':
            continue
        key = f"{spec['backend']}/{spec['workload']}/{spec['wave']}/{spec['arm']}"
        c = cell_summary(cid)
        ops = c.pop('_ops')
        if spec['workload'] == 'materials':
            sub = [op for op in R if op in ops]
            base = {'jobs': sum(ops[op]['jobs'] for op in sub), 'correct': sum(ops[op]['correct'] for op in sub),
                    'unresolved': sum(ops[op]['unresolved'] for op in sub),
                    'unresolved_audits': sum(ops[op]['unresolved_audits'] for op in sub),
                    'makespan_s': c['makespan_s'], 'makespan_lower_s': c['makespan_lower_s'],
                    'makespan_upper_s': c['makespan_upper_s'], 'usage': c['usage'], 'state': c['state'],
                    'evidence': c['evidence']}
            rk = f"{spec['backend']}/{spec['wave']}/{spec['arm']}"
            r_cells[rk] = dict(base, tokens=sum(ops[op]['tokens'] for op in sub))
            r_cells_additive[rk] = dict(base, tokens=sum(ops[op]['additive'] for op in sub))
        cells[key] = c

    isolation_state = 'passed' if not isolation_problems else 'failed'
    quota_problems = []
    if live:
        owner_dir = str(config.CODEX_SESSIONS_DEFAULT)
        for g in jsonl(run_dir / 'evidence' / 'quota-gates.jsonl'):
            src = str(g.get('owner_source') or '')
            if g.get('ok') and not src.startswith(owner_dir):
                quota_problems.append(f"group {g.get('group')}: released on a reading outside the owner sessions "
                                      f"({src or 'no source recorded'}) (A4.12, RT3.3)")
    validity = {'isolation': isolation_state, 'isolation_problems': isolation_problems, 'leakage': leakage,
                'accounting_failures': accounting, 'interrupted': interrupted, 'invalid_cells': invalid_cells,
                'bootstrap': boot_validity,
                'simulation': simulation, 'freeze_problems': freeze_problems, 'artifact_problems': artifact[:200],
                'classification_problems': class_problems}
    summary = {'cells': cells, 'R': R, 'R_cells': r_cells, 'validity': validity}
    evaluated = gates.evaluate(summary)

    budget = {}
    for b in ('codex', 'sonnet'):
        rows = [a for a in all_attempts if a.get('backend') == b]
        budget[b] = {k: sum(1 for a in rows if a.get('kind') == k) for k in ('nominal', 'reserve', 'telemetry')}
        budget[b]['total'] = len(rows)
        budget[b]['caps'] = config.EVAL_CAPS[b]
    additive = json.loads(json.dumps(summary))
    for c in additive['cells'].values():
        c['tokens'] = c['additive_tokens']
    additive['R_cells'] = json.loads(json.dumps(r_cells_additive))
    sensitivity_gates = gates.evaluate(additive)
    provenance = {'calls': [{k: a.get(k) for k in ('call_id', 'cell', 'kind', 'outcome', 'started_at', 'ended_at',
                                                   'prompt_sha256', 'stdin_sha256', 'system_sha256', 'stdout_sha256',
                                                   'auth', 'runtime_files', 'group', 'mode')}
                            for a in all_attempts],
                  'sealed_reviewer_artifacts': {op: e.get('sealed_ast_sha256') for op, e in
                                                (_read_json(config.CLASSIFICATION_FILE, {}) or {}).get(
                                                    'operations', {}).items() if e.get('sealed_ast_sha256')},
                  'classification_sha256': prompts.sha256(config.CLASSIFICATION_FILE.read_text(encoding='utf-8')),
                  'registry_manifest_sha256': (results.get('codex-materials-bootstrap') or {}).get(
                      'registry_manifest_sha256'),
                  'isolation_events': len(jsonl(run_dir / 'evidence' / 'isolation.jsonl')),
                  'launch_records': len(list((run_dir / 'evidence' / 'launch').glob('*.json')))
                  if (run_dir / 'evidence' / 'launch').exists() else 0,
                  'artifact_chain_verified_calls': len(verified), 'experiment': experiment or None,
                  'experiment_ledger': experiment_view}
    from . import usage as usage_mod
    from .budget import PrepLedger
    prep = dict(_read_json(run_dir / 'preparation.json', {}) or {})
    prep['current_counts'] = PrepLedger(config.LEDGER_FILE).counts()
    prep['current_total'] = sum(prep['current_counts'].values())
    telemetry = [{k: a.get(k) for k in ('call_id', 'cell', 'role', 'outcome', 'expected_outcome', 'charged_tokens',
                                        'usage_status', 'started_at')} for a in telemetry_rows]
    tel_tokens = sum(int(a.get('charged_tokens') or 0) for a in telemetry_rows)
    physical_tokens = sum(int(a.get('charged_tokens') or 0) for a in all_attempts)
    report = {'schema': SCHEMA, 'mode': 'evaluation' if live else 'simulation (never evidence)',
              'cells': cells, 'per_operation': evaluated['per_operation'], 'budget': budget,
              'validity': validity, 'gates': evaluated, 'claims': evaluated['claims'],
              'magnitude': evaluated['magnitude'], 'R': R, 'R_cells': r_cells, 'R_problem': r_problem,
              'bootstrap': boot_detail, 'preparation': prep, 'telemetry': {'calls': telemetry, 'tokens': tel_tokens},
              'cost_views': {'physical_tokens_all_calls': physical_tokens, 'telemetry_tokens': tel_tokens,
                             'evaluation_physical_tokens': physical_tokens - tel_tokens,
                             'analytical_cell_tokens': {k: c['tokens'] for k, c in cells.items()},
                             'warm_increment_tokens': {b: {arm: (cells.get(f'{b}/materials/warm/{arm}') or {}).get(
                                 'tokens') for arm in ('A', 'C')} for b in ('codex', 'sonnet')},
                             'note': 'analytical cell tokens charge the shared bootstrap fully to cold B and C; the '
                                     'physical total counts it once'},
              'cell_states': dict(sorted(states.items())),
              'quota_gate_problems': quota_problems[:20],
              'sensitivity': {k: {'charged_tokens': c['tokens'], 'additive_tokens': c['additive_tokens']}
                              for k, c in cells.items()},
              'unknown_usage_observation': _unknown_usage_observation(specs, by_cell),
              'sensitivity_gates': {'materials': {b: {k: g[k] for k in ('pass', 'ratios')}
                                                  for b, g in sensitivity_gates['materials'].items()},
                                    'boolq': {k: sensitivity_gates['boolq'][k] for k in ('pass', 'ratios')},
                                    'pooling': {k: sensitivity_gates['pooling'][k] for k in ('pass', 'ratios')},
                                    'magnitude': sensitivity_gates['magnitude'],
                                    'reading': 'additive input accounting: input + cached + output (A4.7), R totals '
                                               'recomputed from additive attempt costs'},
              'decoder_replay': usage_mod.replay_fixtures(), 'decoder_sha256': usage_mod.decoder_sha256(),
              'provenance': provenance,
              'makespan_rule': 'sum of the cell work windows (submission to resolution, local work included), plus '
                               'the bootstrap windows for cold B and C; child_makespan_s reports the child execution '
                               'time only'}
    if write:
        (run_dir / 'report.json').write_text(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + '\n',
                                             encoding='utf-8')
        (run_dir / 'report.md').write_text(render_md(report), encoding='utf-8')
    return report


def _unknown_usage_observation(specs, by_cell):
    """P2 (A4.7, A4.11): a labeled sensitivity calculation, never an established bound and never consulted by the
    gates. For each cell whose usage is incomplete, the charged tokens with each attempt of unknown usage counted as
    the input tokens of the next attempt of the same batch with zero output (the joint decision's hypothetical
    substitution). Dependent token comparisons stay inconclusive whatever it shows."""
    out = {}
    for cid, spec in specs.items():
        rows = by_cell.get(cid) or []
        unknown = [a for a in rows if a.get('outcome') != 'not_launched' and a.get('usage_status') == 'incomplete']
        if not unknown:
            continue
        extra = 0
        for a in unknown:
            later = [b for b in rows if b.get('batch') == a.get('batch') and (b.get('try') or 0) > (a.get('try') or 0)
                     and isinstance(b.get('usage_raw'), dict)]
            extra += int(later[0]['usage_raw'].get('input_tokens') or 0) if later else 0
        known = sum(int(a.get('charged_tokens') or 0) for a in rows)
        key = f"{spec['backend']}/{spec['workload']}/{spec['wave']}/{spec['arm']}"
        out[key] = {'attempts_with_unknown_usage': len(unknown), 'known_charged_tokens': known,
                    'hypothetical_tokens': known + extra,
                    'label': 'hypothetical substitution, not an established bound (P2); never used by any gate'}
    return out


def _fmt(x, nd=3):
    if x is None:
        return 'n/a'
    if isinstance(x, float):
        return f'{x:.{nd}f}'
    return str(x)


def render_md(r) -> str:
    lines = ['# oz map clean replication: report', '',
             f"Mode: {r['mode']}. Schema {r['schema']}. R = {r['R']}. Isolation: {r['validity']['isolation']}. "
             f"Safety kill: {r['gates']['safety_kill']}.", '', '## Cells', '',
             '| Cell | State | Jobs | Correct | Unresolved | Tokens | Tokens per correct | Makespan s | Child s | '
             'Usage | Evidence | Calls | Rule answers |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|']
    for k, c in sorted(r['cells'].items()):
        tpc = c['tokens'] / c['correct'] if c['correct'] else None
        lines.append(f"| {k} | {c['state']} | {c['jobs']} | {c['correct']} | {c['unresolved']} | {c['tokens']} | "
                     f"{_fmt(tpc, 1)} | {_fmt(c['makespan_s'], 1)} | {_fmt(c['child_makespan_s'], 1)} | "
                     f"{c['usage']} | {c['evidence']} | {c['physical_calls']} | {c['rule_answers']} |")
    lines += ['', '## Gates (A4.10)', '']
    for b, g in sorted(r['gates']['materials'].items()):
        lines.append(f"- {b} materials: verdict {g.get('verdict')}, pass {g['pass']}, ratios "
                     + ', '.join(f'{k} {_fmt(v, 4)}' for k, v in sorted(g['ratios'].items())))
    for name in ('boolq', 'pooling'):
        g = r['gates'][name]
        lines.append(f"- {name}: verdict {g.get('verdict')}, pass {g['pass']}, ratios "
                     + ', '.join(f'{k} {_fmt(v, 4)}' for k, v in sorted(g['ratios'].items())))
    c = r['claims']
    lines += ['', f"Claims: codex {c['codex']}, sonnet {c['sonnet']}, cross backend headline "
                  f"{c['cross_backend_headline']}.", '', '## Magnitude on R (A4.11)', '']
    for b, m in sorted(r['magnitude'].items()):
        lines.append(f"- {b}: status {m['status']}, token ratio {_fmt(m['token_ratio'], 6)}, makespan ratio "
                     f"{_fmt(m['makespan_ratio'], 6)}, label {m['label']}, missed {m['missed']}")
    v = r['validity']
    lines += ['', '## Validity', '', f"- leakage: {len(v['leakage'])}",
              f"- accounting failures: {len(v['accounting_failures'])}",
              f"- stopped cells invalid (A4.14.1): {sorted(v.get('invalid_cells') or {})}",
              f"- stopped cells interrupted, no finding: {v.get('interrupted')}",
              f"- simulation: {len(v['simulation'])}",
              f"- artifact chain problems: {len(v['artifact_problems'])}",
              f"- run bound freeze problems: {len(v['freeze_problems'])}",
              f"- classification problems: {len(v['classification_problems'])}",
              f"- interrupted cells: {v['interrupted']}"]
    for k, b in sorted(r['bootstrap'].items()):
        lines.append(f"- bootstrap {k}: status {b['status']}, efficiency valid {b['efficiency_valid']}, proposed "
                     f"{sorted(op for op, p in b['proposed'].items() if p)}, admitted {b['admitted']}, measured "
                     f"errors {b['measured_errors']}")
    lines += ['', '## Budget (physical calls)', '']
    for b, x in sorted(r['budget'].items()):
        lines.append(f"- {b}: nominal {x['nominal']}, reserve {x['reserve']}, telemetry {x['telemetry']}, total "
                     f"{x['total']} of {x['caps']['total']}")
    t = r['telemetry']
    lines += ['', '## Telemetry (reported separately, never in a cell)', '',
              f"- calls: {len(t['calls'])}, tokens {t['tokens']}"]
    prep = r.get('preparation') or {}
    lines += ['', '## Preparation and review calls (A4.13, reported separately)', '',
              f"- current counts {prep.get('current_counts')}, caps {prep.get('caps')}", '']
    return '\n'.join(lines)


def convergence(run_dir, sealed_dir) -> dict:
    """A4.8, after scoring only: whether a learner AST is byte identical (or JSON identical) to the sealed reviewer
    AST of the same operation. Reported as an observation. Never called by score_run; it reads the sealed directory
    only when the driver passes it explicitly after a complete report exists (all sixteen cells complete)."""
    run_dir, sealed_dir = Path(run_dir), Path(sealed_dir)
    report = _read_json(run_dir / 'report.json')
    if not report:
        raise RuntimeError('convergence is reported only after scoring (report.json missing)')
    # closure round 2 (N1): administrative cells in cell_states are not among the sixteen evaluation cells
    evaluation_states = {c: st for c, st in (report.get('cell_states') or {}).items() if c not in NON_EVALUATION}
    if any(st != 'complete' for st in evaluation_states.values()) or not evaluation_states:
        raise RuntimeError('convergence is reported only after all sixteen cells are complete and scored')
    out = {}
    for prefix in ('codex-materials', 'sonnet-materials'):
        res = _read_json(run_dir / 'cells' / f'{prefix}-bootstrap' / 'result.json', {}) or {}
        for op, row in (res.get('rules') or {}).items():
            sealed = sealed_dir / f'{op}.ast.json'
            if not row.get('proposed') or not sealed.exists():
                out[f'{prefix}/{op}'] = {'learner_proposed': bool(row.get('proposed')), 'sealed': sealed.exists()}
                continue
            learner = base64.b64decode(row['ast_b64'])
            ref = sealed.read_bytes().strip()
            try:
                same_json = json.loads(learner) == json.loads(ref)
            except ValueError:
                same_json = False
            out[f'{prefix}/{op}'] = {'learner_proposed': True, 'sealed': True, 'byte_identical': learner == ref,
                                     'json_identical': same_json,
                                     'admitted': (row.get('admission') or {}).get('status') == 'accepted'}
    (run_dir / 'convergence.json').write_text(json.dumps(out, indent=1, sort_keys=True) + chr(10), encoding='utf-8')
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print('usage: python -m bench.ozmap_rep.score <run dir>', file=sys.stderr)
        return 2
    report = score_run(argv[0], write=True)
    print(f"scored {argv[0]} ({report['mode']}): {len(report['cells'])} cells, headline "
          f"{report['claims']['cross_backend_headline']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
