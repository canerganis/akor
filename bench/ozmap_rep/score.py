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
from pathlib import Path
import sys

from . import bootstrap, config, gates, prompts, rules, workload
from .run import _read_json, cell_specs, jsonl

SCHEMA = 'ozmap-rep/1'
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

def _rejudge(run_dir, a):
    """Problems found by deriving an attempt's outcome, usage and answers again from its capture."""
    from . import run as run_mod
    run_dir = Path(run_dir)
    cid = a['call_id']
    problems = []
    out_path, err_path = run_dir / 'captures' / f'{cid}.stdout', run_dir / 'captures' / f'{cid}.stderr'
    if not out_path.exists() or not err_path.exists():
        return [f'{cid}: capture missing']
    stdout, stderr = out_path.read_bytes().decode('utf-8'), err_path.read_bytes().decode('utf-8')
    if prompts.sha256(stdout) != a.get('stdout_sha256'):
        problems.append(f'{cid}: stdout capture does not hash to its attempt')
    if a.get('stderr_sha256') is not None and prompts.sha256(stderr) != a.get('stderr_sha256'):
        problems.append(f'{cid}: stderr capture does not hash to its attempt')
    raw = {'stdout': stdout, 'stderr': stderr, 'exit_code': a.get('exit_code'), 'timed_out': a.get('timed_out')}
    judge = run_mod.judge_codex if a.get('backend') == 'codex' else run_mod.judge_sonnet
    outcome, reply, usage_raw, cls, _ = judge(raw)
    want = a.get('outcome')
    derived = ('ok' if want in ('malformed', 'malformed_reply', 'malformed_answers') else want)
    if outcome != derived:
        problems.append(f'{cid}: the capture judges {outcome!r}, the attempt says {want!r}')
    if cls['verdict'] != (a.get('events') or {}).get('verdict'):
        problems.append(f'{cid}: the capture event verdict differs from the attempt')
    if _canon(usage_raw) != _canon(a.get('usage_raw')):
        problems.append(f'{cid}: the attempt usage does not derive from the capture')
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
            text, _ = prompts.parse_bootstrap(reply, prompts.bootstrap_config(a.get('workload'))['ops'])
        except prompts.Malformed:
            text = None
    answers = prompts.parse_answers(text, mapping)[0] if isinstance(text, str) else {}
    if _canon(answers) != _canon(call.get('answers') or {}):
        problems.append(f'{cid}: the recorded answers do not derive from the capture')
    return problems


def _rule_asts(results, prefix):
    boot = results.get(f'{prefix}-bootstrap') or {}
    out = {}
    for op, row in (boot.get('rules') or {}).items():
        if row.get('proposed') and (row.get('admission') or {}).get('status') == 'accepted' and row.get('ast_b64'):
            out[op] = base64.b64decode(row['ast_b64'])
    return out


def _cell_chain(run_dir, cid, spec, results, calls_ok):
    """Problems of a cell's answers against the calls that produced them, the bootstrap and the rules."""
    run_dir = Path(run_dir)
    problems = []
    res = results.get(cid) or {}
    prefix = f"{spec['backend']}-{spec['workload']}"
    jobs = {j['id']: j for j in workload.jobs_for(spec['workload'], spec['wave'])} if spec['arm'] != 'telemetry' \
        else {}
    asts = _rule_asts(results, prefix) if spec['workload'] == 'materials' else {}
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
    if spec['arm'] == 'bootstrap':
        for op, row in (res.get('rules') or {}).items():
            adm = row.get('admission') or {}
            if not row.get('proposed') or adm.get('status') in (None, 'not_evaluated') or \
                    spec['workload'] != 'materials':
                continue
            again = rules.summary(rules.admit(op, base64.b64decode(row.get('ast_b64') or '')))
            if again.get('status') != adm.get('status'):
                problems.append(f'{cid}/{op}: the admission record is not reproduced ({again.get("status")} vs '
                                f'{adm.get("status")})')
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
    for a in attempts:
        ev = a.get('events') or {}
        if ev.get('verdict') in ('executed', 'uncertain'):
            leakage.append(f"{a['call_id']}: tool event verdict {ev['verdict']} (A4.3)")
        if (a.get('usage') or {}).get('status') == 'invalid':
            accounting.append(f"{a['call_id']}: usage invalid ({'; '.join(a['usage'].get('problems') or [])})")
        if a.get('backend') == 'codex' and not _evidence_ok(run_dir, a):
            isolation_problems.append(f"{a['call_id']}: launch evidence missing or not clean")
    for a in all_attempts:
        if a.get('credential_disclosure'):
            isolation_problems.append(f"{a['call_id']}: credential material was redacted from its output (A4.2)")
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
    seen, terminal = {}, {}
    for a in all_attempts:
        cid = a.get('call_id')
        seen[cid] = seen.get(cid, 0) + 1
        if a.get('outcome') not in ('infrastructure_failure', 'interrupted'):
            key = (a.get('cell'), a.get('batch'))
            terminal[key] = terminal.get(key, 0) + 1
    accounting += [f'{cid}: call id recorded {n} times' for cid, n in sorted(seen.items(), key=str) if n > 1]
    accounting += [f'{k[0]} {k[1]}: {n} terminal attempts' for k, n in sorted(terminal.items(), key=str) if n > 1]
    charged = {}
    for a in attempts:
        key = (a.get('backend'), a.get('workload'), a.get('allocation'))
        charged[key] = charged.get(key, 0) + 1
    for (b, w, al), n in sorted(charged.items(), key=str):
        nominal = config.ALLOCATIONS.get(f'{b}/{w}', {}).get(al)
        if nominal is not None and n > nominal + config.RESERVE_PER_ALLOCATION:
            accounting.append(f'{b}/{w} {al}: {n} physical calls above nominal {nominal} plus reserve')
    markers = sorted(p.name for p in run_dir.glob('cells/*/inflight/*.json'))
    if markers:
        accounting.append(f'unrecovered in-flight markers (charged calls without attempts): {markers[:5]}')
    ledger_path = experiment.get('live_ledger')
    if ledger_path:
        here = str(run_dir.resolve())
        known = {a.get('call_id') for a in all_attempts}
        lost = sorted(r.get('call_id') for r in jsonl(ledger_path)
                      if r.get('run_dir') == here and r.get('call_id') not in known)
        if lost:
            accounting.append(f'experiment ledger calls missing from the run directory: {lost[:5]}')

    for p in sorted((run_dir / 'prompts').glob('*.txt')) if (run_dir / 'prompts').exists() else []:
        if prompts.learner_prompt_leaks(p.read_text(encoding='utf-8'), admission):
            leakage.append(f'{p.stem}: admission material in a model-bound prompt (A4.8)')
    if (run_dir / 'codex-stop.json').exists():
        isolation_problems.append('Codex evaluation stopped by authentication reconciliation (A4.2)')
    live = experiment.get('mode') == 'live'
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
                isolation_problems.append(f'{cid}: no passing wave gate record')
            if not (run_dir / 'evidence' / f'features-{cid}.json').exists():
                isolation_problems.append(f'{cid}: no features record')
            for a in rows:
                if a.get('outcome') != 'interrupted' and not a.get('auth'):
                    isolation_problems.append(f"{a['call_id']}: no authentication record")

    # artifact chain (item 10)
    verified = set()
    for a in all_attempts:
        if a.get('outcome') == 'interrupted':
            continue
        found = _rejudge(run_dir, a)
        artifact += found
        if not found:
            verified.add(a['call_id'])
    recorded = {a.get('call_id') for a in all_attempts}
    if (run_dir / 'captures').exists():
        for p in sorted((run_dir / 'captures').glob('*.stdout')):
            if p.stem not in recorded:
                artifact.append(f'{p.stem}: a capture without an attempt line')
    for cid, spec in specs.items():
        if results.get(cid):
            artifact += _cell_chain(run_dir, cid, spec, results, verified)
    freeze_problems = _freeze_problems(run_dir, experiment) if live else []
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
        usage_ok = bool(rows) and all(a.get('usage_status') == 'complete' for a in rows)
        state = states[main]
        for cid in ids[1:]:
            if states[cid] != 'complete':
                state = states[cid]
        evidence_ok = state == 'complete' and all(_evidence_ok(run_dir, a) for a in rows)
        evidence = 'complete' if evidence_ok else 'incomplete'
        if any(cid in sim_cells for cid in ids):
            evidence = 'simulation'
        windows = [w for cid in ids for w in _windows(run_dir, cid)]
        if windows:
            makespan = sum(float(w.get('elapsed_s') or 0.0) for w in windows)
        else:
            makespan = sum(_groups_makespan(by_cell[cid]) for cid in ids)
            if rows:
                evidence = 'incomplete' if evidence == 'complete' else evidence
        child = sum(_groups_makespan(by_cell[cid]) for cid in ids)
        return {'jobs': len(jobs), 'correct': correct, 'unresolved': unresolved, 'tokens': tokens,
                'additive_tokens': sum(int(a.get('additive_tokens') or 0) for a in rows),
                'makespan_s': round(makespan, 3), 'child_makespan_s': round(child, 3),
                'usage': 'complete' if usage_ok else 'incomplete'
                if any(a.get('usage_status') == 'incomplete' for a in rows) or not rows else 'unverified',
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
                    'makespan_s': c['makespan_s'], 'usage': c['usage'], 'state': c['state'],
                    'evidence': c['evidence']}
            rk = f"{spec['backend']}/{spec['wave']}/{spec['arm']}"
            r_cells[rk] = dict(base, tokens=sum(ops[op]['tokens'] for op in sub))
            r_cells_additive[rk] = dict(base, tokens=sum(ops[op]['additive'] for op in sub))
        cells[key] = c

    isolation_state = 'passed' if not isolation_problems else 'failed'
    validity = {'isolation': isolation_state, 'isolation_problems': isolation_problems, 'leakage': leakage,
                'accounting_failures': accounting, 'interrupted': interrupted, 'bootstrap': boot_validity,
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
                  'artifact_chain_verified_calls': len(verified), 'experiment': experiment or None}
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
              'sensitivity': {k: {'charged_tokens': c['tokens'], 'additive_tokens': c['additive_tokens']}
                              for k, c in cells.items()},
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
        lines.append(f"- {b} materials: pass {g['pass']}, inconclusive {g['inconclusive']}, ratios "
                     + ', '.join(f'{k} {_fmt(v, 4)}' for k, v in sorted(g['ratios'].items())))
    for name in ('boolq', 'pooling'):
        g = r['gates'][name]
        lines.append(f"- {name}: pass {g['pass']}, inconclusive {g['inconclusive']}, ratios "
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
    if any(st != 'complete' for st in (report.get('cell_states') or {}).values()) or not report.get('cell_states'):
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
