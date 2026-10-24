"""Offline scorer of a replication run directory (A4.6, A4.7, A4.10, A4.11). Standard library only.

    python -m bench.ozmap_rep.score <run dir>

Reads only the run directory (attempts.jsonl, cells/, prompts/, evidence/, preparation.json) plus the frozen code and
gold oracle, makes no external call, and rewrites report.json and report.md deterministically.

Accounting frozen before evaluation (A4.11): a cell's tokens are the charged tokens (inclusive input + output, A4.7)
of every physical call charged to it, failed and refused calls included; the shared bootstrap call is charged fully
to both cold B and cold C. Shared call tokens are attributed to operations in proportion to the call's records of
each operation (gates.attribute_tokens), so audit and fallback costs stay with the operation whose jobs they served
and nothing is dropped. A cell's makespan is the harness' own schedule: the sum over its launch groups (at most four
concurrent calls on the four slots) of the longest call in the group, plus the bootstrap's for cold B and C.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

from . import bootstrap, config, gates, prompts, workload
from .run import _read_json, cell_specs, jsonl

SCHEMA = 'ozmap-rep/1'


def _canon(v):
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _groups_makespan(attempts):
    """Sum over launch groups (calls launched together on the four slots) of the longest call in the group."""
    groups = {}
    for a in attempts:
        groups.setdefault(a.get('group') or a.get('call_id'), []).append(float(a.get('elapsed_s') or 0.0))
    return round(sum(max(v) for v in groups.values()), 3)


def _attempt_ops_tokens(a):
    recs = a.get('records') or {}
    return gates.attribute_tokens(int(a.get('charged_tokens') or 0), {op: n for op, n in sorted(recs.items())})


def _evidence_ok(run_dir, a):
    p = Path(run_dir) / 'prompts' / f"{a['call_id']}.txt"
    if not p.exists() or prompts.sha256(p.read_text(encoding='utf-8')) != a.get('prompt_sha256'):
        return False
    launch = _read_json(Path(run_dir) / 'evidence' / 'launch' / f"{a['call_id']}.json")
    if a.get('cell') != 'telemetry' and (launch is None or launch.get('problems')):
        return False
    return True


def score_run(run_dir, write=False) -> dict:
    run_dir = Path(run_dir)
    attempts = jsonl(run_dir / 'attempts.jsonl')
    specs = {s['id']: s for s in cell_specs()}
    states = {cid: (_read_json(run_dir / 'cells' / cid / 'state.json', {}) or {}).get('state', 'pending')
              for cid in specs}
    results = {cid: _read_json(run_dir / 'cells' / cid / 'result.json', {}) or {} for cid in specs}
    by_cell = {cid: [a for a in attempts if a.get('cell') == cid] for cid in specs}
    first_call = min((a.get('started_at') for a in attempts if a.get('started_at')), default=None)
    try:
        R = sorted(bootstrap.load_R(first_learner_call=first_call))
        r_problem = None
    except bootstrap.ClassificationError as exc:
        R, r_problem = [], str(exc)
    admission = workload.materials()['admission']

    # ------------------------------------------------------------------------------------------- validity
    leakage, accounting, isolation_problems = [], [], []
    for a in attempts:
        ev = a.get('events') or {}
        if ev.get('verdict') in ('executed', 'uncertain'):
            leakage.append(f"{a['call_id']}: tool event verdict {ev['verdict']} (A4.3)")
        if (a.get('usage') or {}).get('status') == 'invalid':
            accounting.append(f"{a['call_id']}: usage invalid ({'; '.join(a['usage'].get('problems') or [])})")
        if a.get('backend') == 'codex' and a.get('cell') != 'telemetry' and not _evidence_ok(run_dir, a):
            isolation_problems.append(f"{a['call_id']}: launch evidence missing or not clean")
    for p in sorted((run_dir / 'prompts').glob('*.txt')) if (run_dir / 'prompts').exists() else []:
        if prompts.learner_prompt_leaks(p.read_text(encoding='utf-8'), admission):
            leakage.append(f'{p.stem}: admission material in a model-bound prompt (A4.8)')
    if (run_dir / 'codex-stop.json').exists():
        isolation_problems.append('Codex evaluation stopped by authentication reconciliation (A4.2)')
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
        status = res.get('status') or ('missing' if states[f'{prefix}-bootstrap'] != 'complete' else 'ok')
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
    def cell_summary(main):
        spec = specs[main]
        prefix = f"{spec['backend']}-{spec['workload']}"
        ids = [main] + ([f'{prefix}-bootstrap'] if spec['wave'] == 'cold' and spec['arm'] in ('B', 'C') else [])
        rows = [a for cid in ids for a in by_cell[cid]]
        jobs = workload.jobs_for(spec['workload'], spec['wave'])
        answers = results[main].get('answers') or {}
        ops = {}
        correct = unresolved = rule_errors = 0
        for j in jobs:
            o = ops.setdefault(j['op'], {'jobs': 0, 'correct': 0, 'unresolved': 0, 'tokens': 0})
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
        for a in rows:
            for op, t in _attempt_ops_tokens(a).items():
                if op in ops:
                    ops[op]['tokens'] += t
                else:
                    first = sorted(ops)[0]
                    ops[first]['tokens'] += t
        tokens = sum(int(a.get('charged_tokens') or 0) for a in rows)
        usage_ok = bool(rows) and all(a.get('usage_status') == 'complete' for a in rows)
        state = states[main]
        for cid in ids[1:]:
            if states[cid] != 'complete':
                state = states[cid]
        evidence_ok = state == 'complete' and all(_evidence_ok(run_dir, a) for a in rows if a.get('cell') != 'telemetry')
        makespan = sum(_groups_makespan(by_cell[cid]) for cid in ids)
        return {'jobs': len(jobs), 'correct': correct, 'unresolved': unresolved, 'tokens': tokens,
                'additive_tokens': sum(int(a.get('additive_tokens') or 0) for a in rows),
                'makespan_s': round(makespan, 3), 'usage': 'complete' if usage_ok else 'incomplete'
                if any(a.get('usage_status') == 'incomplete' for a in rows) or not rows else 'unverified',
                'evidence': 'complete' if evidence_ok else 'incomplete', 'state': state, 'rule_errors': rule_errors,
                'physical_calls': len(rows), 'rule_answers': sum(1 for r in answers.values()
                                                                 if r.get('source') == 'rule'),
                'ops': {op: {k: v[k] for k in ('jobs', 'correct', 'tokens')} for op, v in sorted(ops.items())}
                if spec['workload'] == 'materials' else {}, '_ops_unresolved': {op: v['unresolved']
                                                                               for op, v in ops.items()}}

    cells, r_cells = {}, {}
    for cid, spec in specs.items():
        if spec['arm'] == 'bootstrap':
            continue
        key = f"{spec['backend']}/{spec['workload']}/{spec['wave']}/{spec['arm']}"
        c = cell_summary(cid)
        if spec['workload'] == 'materials':
            sub = [op for op in R if op in c['ops']]
            r_cells[f"{spec['backend']}/{spec['wave']}/{spec['arm']}"] = {
                'jobs': sum(c['ops'][op]['jobs'] for op in sub), 'correct': sum(c['ops'][op]['correct'] for op in sub),
                'unresolved': sum(c['_ops_unresolved'][op] for op in sub),
                'tokens': sum(c['ops'][op]['tokens'] for op in sub), 'makespan_s': c['makespan_s'],
                'usage': c['usage'], 'state': c['state'], 'evidence': c['evidence']}
        c.pop('_ops_unresolved')
        cells[key] = c

    isolation_state = 'passed' if not isolation_problems else 'failed'
    summary = {'cells': cells, 'R': R, 'R_cells': r_cells,
               'validity': {'isolation': isolation_state, 'isolation_problems': isolation_problems,
                            'leakage': leakage, 'accounting_failures': accounting, 'interrupted': interrupted,
                            'bootstrap': boot_validity}}
    evaluated = gates.evaluate(summary)

    budget = {}
    for b in ('codex', 'sonnet'):
        rows = [a for a in attempts if a.get('backend') == b]
        budget[b] = {k: sum(1 for a in rows if a.get('kind') == k) for k in ('nominal', 'reserve', 'telemetry')}
        budget[b]['total'] = len(rows)
        budget[b]['caps'] = config.EVAL_CAPS[b]
    additive = json.loads(json.dumps(summary))
    for c in additive['cells'].values():
        c['tokens'] = c['additive_tokens']
    sensitivity_gates = gates.evaluate(additive)
    provenance = {'calls': [{k: a.get(k) for k in ('call_id', 'cell', 'kind', 'outcome', 'started_at', 'ended_at',
                                                   'prompt_sha256', 'stdin_sha256', 'system_sha256', 'stdout_sha256',
                                                   'auth', 'runtime_files', 'group')}
                            for a in attempts],
                  'sealed_reviewer_artifacts': {op: e.get('sealed_ast_sha256') for op, e in
                                                (_read_json(config.CLASSIFICATION_FILE, {}) or {}).get(
                                                    'operations', {}).items() if e.get('sealed_ast_sha256')},
                  'classification_sha256': prompts.sha256(config.CLASSIFICATION_FILE.read_text(encoding='utf-8')),
                  'registry_manifest_sha256': (results.get('codex-materials-bootstrap') or {}).get(
                      'registry_manifest_sha256'),
                  'isolation_events': len(jsonl(run_dir / 'evidence' / 'isolation.jsonl')),
                  'launch_records': len(list((run_dir / 'evidence' / 'launch').glob('*.json')))
                  if (run_dir / 'evidence' / 'launch').exists() else 0}
    from . import usage as usage_mod
    prep = _read_json(run_dir / 'preparation.json', {}) or {}
    report = {'schema': SCHEMA, 'cells': cells, 'per_operation': evaluated['per_operation'], 'budget': budget,
              'validity': summary['validity'], 'gates': evaluated, 'claims': evaluated['claims'],
              'magnitude': evaluated['magnitude'], 'R': R, 'R_cells': r_cells, 'R_problem': r_problem,
              'bootstrap': boot_detail, 'preparation': prep,
              'cell_states': dict(sorted(states.items())),
              'sensitivity': {k: {'charged_tokens': c['tokens'], 'additive_tokens': c['additive_tokens']}
                              for k, c in cells.items()},
              'sensitivity_gates': {'materials': {b: {k: g[k] for k in ('pass', 'ratios')}
                                                  for b, g in sensitivity_gates['materials'].items()},
                                    'boolq': {k: sensitivity_gates['boolq'][k] for k in ('pass', 'ratios')},
                                    'pooling': {k: sensitivity_gates['pooling'][k] for k in ('pass', 'ratios')},
                                    'magnitude': sensitivity_gates['magnitude'],
                                    'reading': 'additive input accounting: input + cached + output (A4.7)'},
              'decoder_replay': usage_mod.replay_fixtures(), 'decoder_sha256': usage_mod.decoder_sha256(),
              'provenance': provenance,
              'makespan_rule': 'sum over launch groups of the longest call (four slots), plus the bootstrap for '
                               'cold B and C'}
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
             f"Schema {r['schema']}. R = {r['R']}. Isolation: {r['validity']['isolation']}. "
             f"Safety kill: {r['gates']['safety_kill']}.", '', '## Cells', '',
             '| Cell | State | Jobs | Correct | Unresolved | Tokens | Tokens per correct | Makespan s | Usage | '
             'Evidence | Calls | Rule answers |',
             '|---|---|---:|---:|---:|---:|---:|---:|---|---|---:|---:|']
    for k, c in sorted(r['cells'].items()):
        tpc = c['tokens'] / c['correct'] if c['correct'] else None
        lines.append(f"| {k} | {c['state']} | {c['jobs']} | {c['correct']} | {c['unresolved']} | {c['tokens']} | "
                     f"{_fmt(tpc, 1)} | {_fmt(c['makespan_s'], 1)} | {c['usage']} | {c['evidence']} | "
                     f"{c['physical_calls']} | {c['rule_answers']} |")
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
    lines += ['', '## Validity', '', f"- leakage: {len(r['validity']['leakage'])}",
              f"- accounting failures: {len(r['validity']['accounting_failures'])}",
              f"- interrupted cells: {r['validity']['interrupted']}"]
    for k, v in sorted(r['bootstrap'].items()):
        lines.append(f"- bootstrap {k}: status {v['status']}, efficiency valid {v['efficiency_valid']}, proposed "
                     f"{sorted(op for op, p in v['proposed'].items() if p)}, admitted {v['admitted']}, measured "
                     f"errors {v['measured_errors']}")
    lines += ['', '## Budget (physical calls)', '']
    for b, v in sorted(r['budget'].items()):
        lines.append(f"- {b}: nominal {v['nominal']}, reserve {v['reserve']}, telemetry {v['telemetry']}, total "
                     f"{v['total']} of {v['caps']['total']}")
    prep = r.get('preparation') or {}
    lines += ['', '## Preparation and review calls (A4.13, reported separately)', '',
              f"- counts {prep.get('counts')}, caps {prep.get('caps')}", '']
    return '\n'.join(lines)


def convergence(run_dir, sealed_dir) -> dict:
    """A4.8, after scoring only: whether a learner AST is byte identical (or JSON identical) to the sealed reviewer
    AST of the same operation. Reported as an observation. Never called by score_run; it reads the sealed directory
    only when the driver passes it explicitly after the report exists."""
    run_dir, sealed_dir = Path(run_dir), Path(sealed_dir)
    if not (run_dir / 'report.json').exists():
        raise RuntimeError('convergence is reported only after scoring (report.json missing)')
    out = {}
    for prefix in ('codex-materials', 'sonnet-materials'):
        res = _read_json(run_dir / 'cells' / f'{prefix}-bootstrap' / 'result.json', {}) or {}
        for op, row in (res.get('rules') or {}).items():
            sealed = sealed_dir / f'{op}.ast.json'
            if not row.get('proposed') or not sealed.exists():
                out[f'{prefix}/{op}'] = {'learner_proposed': bool(row.get('proposed')), 'sealed': sealed.exists()}
                continue
            import base64
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
    print(f"scored {argv[0]}: {len(report['cells'])} cells, headline {report['claims']['cross_backend_headline']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
