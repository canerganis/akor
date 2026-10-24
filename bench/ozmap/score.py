"""Offline gold scoring and the ordered kill gates of the oz map pilot (joint record 3 to 6). Standard library.

Gold is computed here, after execution, by oracle.py (materials) and the BoolQ dataset labels; nothing in this module
runs during a pilot call. Inputs are the per cell files pilot.py run writes (cells/<backend>-<workload>-<wave>-<arm>
.json with the host report and every delivered row), budget.json and manifest.json.

Per job: correct (accepted by the host's checks and equal to gold), incorrect (accepted, not equal) or unresolved
(not accepted: failed, unresolved, awaiting verification). Rule-origin errors are incorrect rows with source "rule";
fallback errors are incorrect rows of phase "fallback". Tokens are the host's charged tokens (input plus output; the
shared bootstrap is charged in full to each of B and C); makespan is the host's charged makespan: the measured span
from the first intake to the last delivery, plus, for the arm that imported the shared bootstrap, that bootstrap's
complete recorded elapsed (never a bootstrap subtraction). The dry run scores its replay projection instead. Summed
physical call seconds are an extra metric only and never replace makespan (amendment 3 sections 2 and 3).

Gates, in order (record 6):
  1 safety      any incorrect rule-origin materials answer released as accepted kills admission
  2 validity    leakage, incomplete usage, bootstrap failure (or a bootstrap answer that is a gold error or disagrees
                with A on the same job) or a budget violation invalidates efficiency
  3 materials   per backend: C preserves correctness (gold-correct count >= A's) and cold tokens per gold-correct job
                <= 0.75 x A's; warm C makespan <= 0.9 x A's and tokens per gold-correct job <= 0.5 x A's
  4 boolq       C adds no gold errors (not-correct count <= A's), at most 1.10 x A's total charged tokens and at most
                1.10 x A's measured makespan (amendment 3 section 2; frozen text in GATE_TEXTS)
  5 pooling     Codex C uses fewer cold tokens than B without worse correctness or makespan; otherwise the pooling
                contribution claim is withdrawn
The headline is permitted only when all five pass (record: "After all gates pass").
"""
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def _sibling(name):
    """Load bench/ozmap/<name>.py as module ozmap_<name> (other bench folders have their own oracle.py, score.py and
    data modules, so the plain names would collide in one interpreter)."""
    import importlib.util
    key = 'ozmap_' + name
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, HERE / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


data = _sibling('data')
oracle = _sibling('oracle')

BACKENDS = ('codex', 'sonnet')
MATERIALS, BOOLQ = 'materials', 'boolq'
COLD_CUT, WARM_TIME, WARM_TOKENS, BOOLQ_OVERHEAD = 0.75, 0.9, 0.5, 1.10
GLOBAL_CAP = 54
# Exact freeze texts of amendment 3 (sections 2 and 3). The gates below implement them; the freeze records them.
GATE_TEXTS = {
    'boolq': ('On the frozen Codex BoolQ cold evaluation, C MUST have no more gold errors than A, consume at most 1.10 '
              'times A’s total charged tokens, and have at most 1.10 times A’s measured makespan. C’s '
              'accounting MUST include the complete shared bootstrap charge and all required residual work. Makespan '
              'MUST include required admission, checking, queueing and completion costs. No bootstrap subtraction, '
              'floor adjustment or substitution of summed physical call seconds is permitted.'),
    'materials_warm': ('For each backend independently, warm C MUST preserve correctness, have measured makespan at '
                       'most 0.90 times matched warm A, and consume at most 0.50 times A’s tokens per gold '
                       'correct job. Score actual live measurements using the frozen timing boundaries and accounting '
                       'rules.'),
}
TIMING = {'makespan': 'first intake submission of the wave to the last terminal delivery of the arm (monotonic within '
                      'one host process, wall clock across processes)',
          'charged_makespan': 'makespan; the arm that imported the shared bootstrap adds its recorded elapsed (claim '
                              'to final settlement of the 64 answers) and drops only its own wait for that bootstrap',
          'summed_call_seconds': 'sum of the physical attempts’ elapsed; reported separately, never a gate input',
          'dry_run': 'replay projection: recorded elapsed per call list-scheduled on the slots'}
HEADLINE = ('In preregistered Codex and Sonnet pilots, guarded rules reduced cold tokens per correct materials job by '
            'at least 25%, with warm completion time reduced by at least 10%.')


# --------------------------------------------------------------------------------------------------- gold

def gold_table():
    """{dataset id: (op, gold value)} for every evaluation job (materials always, BoolQ when available)."""
    out = {}
    mat = data.materials()
    for wave in data.WAVES:
        for jobs in mat['waves'][wave].values():
            for j in jobs:
                out[j['dataset_id']] = (j['op'], oracle.gold(j['op'], j['text']))
    q = data.boolq()
    if q['available']:
        for did, answer in q['labels'].items():
            out[did] = (data.BOOLQ_OP, oracle.gold(data.BOOLQ_OP, '', answer))
    return out


def classify(row, gold):
    """correct / incorrect / unresolved for one delivered row."""
    if row.get('status') != 'accepted' or row.get('value_text') is None:
        return 'unresolved'
    try:
        value = json.loads(row['value_text'])
    except ValueError:
        return 'incorrect'
    return 'correct' if oracle.matches(value, gold) else 'incorrect'


def score_cell(rows, report, gold, *, makespan=None):
    """Stats of one (backend, workload, wave, arm) cell from its rows and host report."""
    counts = {'correct': 0, 'incorrect': 0, 'unresolved': 0}
    rule_errors = fallback_errors = rule_hits = 0
    per_job = {}
    for row in rows:
        _, g = gold[row['dataset_id']]
        verdict = classify(row, g)
        counts[verdict] += 1
        per_job[row['dataset_id']] = {'verdict': verdict, 'source': row.get('source'), 'phase': row.get('phase'),
                                      'value_text': row.get('value_text')}
        if row.get('status') == 'accepted' and row.get('source') == 'rule':
            rule_hits += 1
            if verdict == 'incorrect':
                rule_errors += 1
        if verdict == 'incorrect' and row.get('phase') == 'fallback':
            fallback_errors += 1
    return summarize(len(rows), counts, rule_errors=rule_errors, fallback_errors=fallback_errors, rule_hits=rule_hits,
                     report=report, makespan=makespan, per_job=per_job)


def summarize(jobs, counts, *, rule_errors, fallback_errors, rule_hits, report, makespan=None, per_job=None,
              summed_call_seconds=None):
    tokens = report['tokens']['charged']
    span = makespan if makespan is not None else report.get('charged_makespan_seconds', report.get('makespan_seconds'))
    correct = counts['correct']
    out = {'jobs': jobs, **counts, 'rule_errors': rule_errors, 'fallback_errors': fallback_errors,
           'rule_hits': rule_hits, 'coverage': round(rule_hits / jobs, 6) if jobs else 0.0,
           'tokens': tokens['tokens'], 'input_tokens': tokens['input_tokens'],
           'cached_input_tokens': tokens.get('cached_input_tokens', 0), 'output_tokens': tokens['output_tokens'],
           'usage': tokens['usage'],
           'tokens_per_correct': round(tokens['tokens'] / correct, 3) if correct else None,
           'makespan_s': round(float(span), 3),
           'summed_call_seconds': round(float(summed_call_seconds if summed_call_seconds is not None else
                                              report.get('summed_call_seconds') or 0.0), 3),
           'jobs_per_min': round(jobs / (span / 60.0), 3) if span else None,
           'correct_per_min': round(correct / (span / 60.0), 3) if span else None,
           'physical_calls': report['calls']['physical'], 'charged_calls': report['calls']['charged'],
           'evidence': report.get('evidence'), 'efficiency_valid': report.get('efficiency_valid'),
           'efficiency_invalid': report.get('efficiency_invalid', []), 'incomplete': report.get('incomplete', [])}
    if per_job is not None:
        out['per_job'] = per_job
    return out


# ----------------------------------------------------------------------------------------------------- gates

def _cell(summary, backend, workload, wave, arm):
    return summary['cells'].get(f'{backend}/{workload}/{wave}/{arm}')


def _ratio(a, b):
    return None if a is None or b in (None, 0) else round(a / b, 6)


def gate_safety(summary):
    bad = {k: c['rule_errors'] for k, c in summary['cells'].items() if c['rule_errors'] and f'/{MATERIALS}/' in k}
    return {'gate': 1, 'name': 'safety', 'pass': not bad,
            'detail': 'no incorrect rule-origin materials answer was accepted' if not bad else
            f'incorrect rule-origin answers released as accepted: {bad}'}


def gate_validity(summary):
    v = summary.get('validity', {})
    problems = list(v.get('leakage', []))
    for k, c in summary['cells'].items():
        if c['usage'] != 'complete':
            problems.append(f'{k}: usage {c["usage"]}')
        for reason in c.get('efficiency_invalid', []):
            problems.append(f'{k}: {reason}')
    for k, b in sorted((v.get('bootstrap') or {}).items()):
        if b.get('status') != 'ok':
            problems.append(f'bootstrap {k}: status {b.get("status")}')
        if b.get('gold_errors'):
            problems.append(f'bootstrap {k}: {b["gold_errors"]} gold errors')
        if b.get('disagreements'):
            problems.append(f'bootstrap {k}: {b["disagreements"]} disagreements with A')
    budget = v.get('budget') or {}
    if budget.get('total', 0) > GLOBAL_CAP:
        problems.append(f'budget: {budget["total"]} physical calls over the global cap {GLOBAL_CAP}')
    for backend, buckets in (budget.get('over') or {}).items():
        problems.append(f'budget: {backend} over its frozen caps {buckets}')
    return {'gate': 2, 'name': 'validity', 'pass': not problems,
            'detail': 'no leakage, complete usage, bootstraps ok, within budget' if not problems else problems}


def gate_materials(summary):
    out, ok, incomplete = {}, True, False
    for backend in BACKENDS:
        a, c = (_cell(summary, backend, MATERIALS, 'cold', x) for x in 'AC')
        wa, wc = (_cell(summary, backend, MATERIALS, 'warm', x) for x in 'AC')
        if not all((a, c, wa, wc)):
            out[backend] = {'pass': False, 'detail': 'cell missing'}
            ok, incomplete = False, True
            continue
        cold_ratio = _ratio(c['tokens_per_correct'], a['tokens_per_correct'])
        warm_tokens = _ratio(wc['tokens_per_correct'], wa['tokens_per_correct'])
        warm_time = _ratio(wc['makespan_s'], wa['makespan_s'])
        checks = {
            'cold_correctness_preserved': c['correct'] >= a['correct'],
            'cold_tokens_per_correct_ratio<=0.75': cold_ratio is not None and cold_ratio <= COLD_CUT,
            'warm_makespan_ratio<=0.9': warm_time is not None and warm_time <= WARM_TIME,
            'warm_tokens_per_correct_ratio<=0.5': warm_tokens is not None and warm_tokens <= WARM_TOKENS,
            'evidence_complete': all(x['evidence'] == 'complete' for x in (a, c, wa, wc)),
        }
        passed = all(checks.values())
        ok = ok and passed
        incomplete = incomplete or not checks['evidence_complete']
        out[backend] = {'pass': passed, 'checks': checks, 'cold_tokens_ratio': cold_ratio,
                        'cold_makespan_ratio_report_only': _ratio(c['makespan_s'], a['makespan_s']),
                        'warm_tokens_ratio': warm_tokens, 'warm_makespan_ratio': warm_time}
    return {'gate': 3, 'name': 'materials', 'pass': ok, 'incomplete': incomplete and not ok, 'detail': out}


def gate_boolq(summary):
    if summary.get('boolq_available') is False:
        return {'gate': 4, 'name': 'boolq', 'pass': False, 'incomplete': True,
                'detail': 'unavailable: bench/ozmap/data/boolq-superglue-val.jsonl is absent, so the BoolQ cells could not run '
                          '(incomplete evidence)'}
    a, c = (_cell(summary, 'codex', BOOLQ, 'cold', x) for x in 'AC')
    if not (a and c):
        return {'gate': 4, 'name': 'boolq', 'pass': False, 'incomplete': True, 'detail': 'cell missing'}
    errors_a, errors_c = a['jobs'] - a['correct'], c['jobs'] - c['correct']
    tok, time_ = _ratio(c['tokens'], a['tokens']), _ratio(c['makespan_s'], a['makespan_s'])
    checks = {'no_added_gold_errors': errors_c <= errors_a,
              'charged_tokens_ratio<=1.10': tok is not None and tok <= BOOLQ_OVERHEAD,
              'measured_makespan_ratio<=1.10': time_ is not None and time_ <= BOOLQ_OVERHEAD,
              'evidence_complete': a['evidence'] == 'complete' and c['evidence'] == 'complete'}
    return {'gate': 4, 'name': 'boolq', 'pass': all(checks.values()),
            'detail': {'checks': checks, 'token_ratio': tok, 'time_ratio': time_, 'errors_A': errors_a,
                       'errors_C': errors_c,
                       'summed_call_seconds_ratio_report_only': _ratio(c.get('summed_call_seconds'),
                                                                       a.get('summed_call_seconds'))}}


def gate_pooling(summary):
    b, c = (_cell(summary, 'codex', MATERIALS, 'cold', x) for x in 'BC')
    if not (b and c):
        return {'gate': 5, 'name': 'pooling', 'pass': False, 'detail': 'cell missing; pooling claim withdrawn'}
    checks = {'C_tokens<B_tokens': c['tokens'] < b['tokens'], 'C_correct>=B_correct': c['correct'] >= b['correct'],
              'C_makespan<=B_makespan': c['makespan_s'] <= b['makespan_s'],
              'evidence_complete': b['evidence'] == 'complete' and c['evidence'] == 'complete'}
    passed = all(checks.values())
    return {'gate': 5, 'name': 'pooling', 'pass': passed,
            'detail': {'checks': checks, 'B_tokens': b['tokens'], 'C_tokens': c['tokens'],
                       'claim': 'pooling contribution supported' if passed else 'pooling contribution claim withdrawn'}}


def evaluate(summary):
    """The ordered gates, the first kill, and whether the headline is permitted."""
    gates = [gate_safety(summary), gate_validity(summary), gate_materials(summary), gate_boolq(summary),
             gate_pooling(summary)]
    first = next((g for g in gates[:4] if not g['pass']), None)
    all_pass = all(g['pass'] for g in gates)
    if first is not None and first.get('incomplete'):
        verdict = f"incomplete: gate {first['gate']} ({first['name']}) lacks complete evidence"
    elif first is not None:
        verdict = {1: 'killed: admission (an incorrect rule-origin materials answer was accepted)',
                   2: 'invalid: efficiency is not evaluable (validity failed)',
                   3: 'killed: materials efficiency gate failed',
                   4: 'killed: BoolQ overhead gate failed'}[first['gate']]
    elif all_pass:
        verdict = 'all gates pass'
    else:
        verdict = 'gates 1 to 4 pass; pooling contribution claim withdrawn'
    return {'gates': gates, 'verdict': verdict, 'headline_permitted': all_pass,
            'headline': HEADLINE if all_pass else None}


# ---------------------------------------------------------------------------------------------- live runs

def bootstrap_checks(cells, gold):
    """Per backend/workload: bootstrap status, gold errors and disagreements with A on the same 64 jobs."""
    out = {}
    for (backend, workload, wave, arm), cell in cells.items():
        boot = cell['report'].get('bootstrap')
        if arm not in 'BC' or not boot:
            continue
        key = f'{backend}/{workload}'
        a_cell = cells.get((backend, workload, wave, 'A'))
        a_values = {r['dataset_id']: r.get('value_text') for r in (a_cell['rows'] if a_cell else [])}
        rows = [r for r in cell['rows'] if r.get('phase') == 'bootstrap']
        errors = sum(1 for r in rows if classify(r, gold[r['dataset_id']][1]) != 'correct')
        disagree = sum(1 for r in rows if a_cell is not None and a_values.get(r['dataset_id']) is not None
                       and r.get('value_text') is not None
                       and json.loads(a_values[r['dataset_id']]) != json.loads(r['value_text']))
        entry = out.setdefault(key, {'status': boot.get('status'), 'jobs': len(rows), 'gold_errors': 0,
                                     'disagreements': 0})
        entry['gold_errors'] = max(entry['gold_errors'], errors)
        entry['disagreements'] = max(entry['disagreements'], disagree)
        if boot.get('status') != 'ok':
            entry['status'] = boot.get('status')
    return out


def budget_over(budget):
    over = {}
    caps = (budget.get('frozen') or {}).get('caps') or {}
    for backend, used in (budget.get('used') or {}).items():
        for bucket, n in used.items():
            if n > (caps.get(backend) or {}).get(bucket, 0):
                over.setdefault(backend, {})[bucket] = n
    return over


def load_run(run_dir):
    run_dir = Path(run_dir)
    cells = {}
    for f in sorted((run_dir / 'cells').glob('*.json')):
        c = json.loads(f.read_text(encoding='utf-8'))
        cells[(c['backend'], c['workload'], c['wave'], c['arm'])] = c
    budget = json.loads((run_dir / 'budget.json').read_text(encoding='utf-8')) if (run_dir / 'budget.json').exists() \
        else {}
    manifest = json.loads((run_dir / 'manifest.json').read_text(encoding='utf-8')) \
        if (run_dir / 'manifest.json').exists() else {}
    return cells, budget, manifest


def score_run(run_dir):
    cells, budget, manifest = load_run(run_dir)
    gold = gold_table()
    summary = {'cells': {}, 'boolq_available': data.boolq()['available']}
    for (backend, workload, wave, arm), c in sorted(cells.items()):
        summary['cells'][f'{backend}/{workload}/{wave}/{arm}'] = score_cell(c['rows'], c['report'], gold)
    leakage = list(manifest.get('leakage_problems', []))
    if manifest.get('gold_accessed_during_run') is not False:
        leakage.append('the run manifest does not attest that gold stayed inaccessible during execution')
    summary['validity'] = {'leakage': leakage, 'bootstrap': bootstrap_checks(cells, gold),
                           'budget': dict(budget, over=budget_over(budget))}
    return summary


# ------------------------------------------------------------------------------------------------- output

def report_md(summary, result):
    lines = ['# oz map kill pilot report', '', f'Verdict: **{result["verdict"]}**', '']
    if not summary.get('boolq_available', True):
        lines += ['BoolQ: unavailable (bench/ozmap/data/boolq-superglue-val.jsonl is absent); gate 4 cannot pass.',
                  '']
    lines += ['| cell | jobs | correct | incorrect | unresolved | rule errors | fallback errors | coverage | tokens | '
              'tokens/correct | makespan s | correct/min | evidence |', '|' + '---|' * 13]
    for k, c in sorted(summary['cells'].items()):
        lines.append(f"| {k} | {c['jobs']} | {c['correct']} | {c['incorrect']} | {c['unresolved']} | "
                     f"{c['rule_errors']} | {c['fallback_errors']} | {c['coverage']} | {c['tokens']} | "
                     f"{c['tokens_per_correct']} | {c['makespan_s']} | {c['correct_per_min']} | {c['evidence']} |")
    lines += ['', '## Gates (ordered)', '']
    for g in result['gates']:
        lines.append(f"{g['gate']}. {g['name']}: {'PASS' if g['pass'] else 'FAIL'}. {json.dumps(g['detail'])}")
    lines += ['', 'Headline permitted: ' + ('yes. ' + result['headline'] if result['headline_permitted'] else 'no'), '',
              'Correctness here is gold scoring after the run; the host receipts only state runtime acceptance.', '']
    return '\n'.join(lines)


def write(summary, out_dir):
    result = evaluate(summary)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slim = {'cells': {k: {x: y for x, y in c.items() if x != 'per_job'} for k, c in summary['cells'].items()},
            **{k: v for k, v in summary.items() if k != 'cells'}}
    (out_dir / 'report.json').write_text(json.dumps({'summary': slim, 'result': result,
                                                     'per_job': {k: c.get('per_job') for k, c in
                                                                 summary['cells'].items()}},
                                                    indent=1, sort_keys=True), encoding='utf-8')
    (out_dir / 'report.md').write_text(report_md(summary, result), encoding='utf-8')
    return result


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description='Score an oz map pilot run against gold and evaluate the gates.')
    p.add_argument('run_dir')
    args = p.parse_args(argv)
    result = write(score_run(args.run_dir), args.run_dir)
    print(result['verdict'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
