"""A4.10 success gates and headlines, A4.11 direction, magnitude and verdicts. Pure functions on a summary dict.

Standard library only. Ratios are compared exactly (fractions.Fraction of the recorded numbers) and reported
unrounded. Tokens per gold correct job is tokens / correct. Nothing here mutates its input.
"""
from __future__ import annotations

import copy
from fractions import Fraction

from . import config

PILOT_TOKENS, PILOT_MAKESPAN = Fraction(44, 10), Fraction(16, 10)
SCOPE = ('results on R (the operations classified rule shaped before any learner call), using new operations '
         'written independently of the language designer; whole workload claims still require A4.10')


def _F(x):
    return Fraction(x) if not isinstance(x, Fraction) else x


def _tpc(cell):
    if not cell.get('correct'):
        return None
    return Fraction(int(cell['tokens'])) / int(cell['correct'])


def _ratio(num, den):
    if num is None or den is None or den == 0:
        return None
    return num / den


def _span(cell, side='exact'):
    """A cell's makespan for a comparison (council round 2, item 14). A window closed after a crash has only bounds,
    so the arm under test uses its upper bound and the reference arm its lower bound: lengthening a reference window
    never helps the arm under test. Exact windows give equal bounds."""
    if side == 'test' and cell.get('makespan_upper_s') is not None:
        return _F(cell['makespan_upper_s'])
    if side == 'ref' and cell.get('makespan_lower_s') is not None:
        return _F(cell['makespan_lower_s'])
    return _F(cell['makespan_s'])


def _f(x):
    return None if x is None else float(x)


def _incomplete(cell):
    """A cell that cannot support a comparison: not complete, usage or evidence not complete, an unresolved job, or
    an unresolved required audit (council round 1, item 17)."""
    return (cell is None or cell.get('state') != 'complete' or cell.get('usage') != 'complete'
            or cell.get('evidence', 'complete') != 'complete' or int(cell.get('unresolved', 0)) > 0
            or int(cell.get('unresolved_audits', 0)) > 0)


def _validity(summary, backend, workload):
    v = summary.get('validity', {})
    problems = []
    if v.get('isolation') != 'passed':
        problems.append('isolation not passed')
    boot = (v.get('bootstrap') or {}).get(f'{backend}/{workload}')
    if not boot or not boot.get('efficiency_valid') or boot.get('completion_failure'):
        problems.append(f'bootstrap {backend}/{workload} not valid')
    if v.get('leakage'):
        problems.append('leakage')
    if v.get('accounting_failures'):
        problems.append('accounting failures')
    # council round 1: simulation is never evidence (RT1.1, item 9), claims need the run bound freeze and the artifact
    # chain (item 10) and a valid classification (item 16)
    if v.get('simulation'):
        problems.append('simulation (fake executables), not evaluation')
    if v.get('freeze_problems'):
        problems.append('run bound freeze not verified')
    if v.get('artifact_problems'):
        problems.append('artifact chain not verified')
    if workload == 'materials' and v.get('classification_problems'):
        problems.append('classification invalid')
    return problems


def safety_kill(summary) -> bool:
    return any(int(c.get('rule_errors', 0)) > 0 for k, c in summary.get('cells', {}).items() if '/materials/' in k)


def _verdict(inconclusive, ok, validity, kill):
    """A4.11 and A4.14.1: a detected validity failure (or a safety kill) is reported invalid before anything is
    called inconclusive, so a stopped cell's leak or accounting failure is never labeled interrupted or inconclusive
    (A4.14.2)."""
    if validity or kill:
        return 'invalid'
    if inconclusive:
        return 'inconclusive'
    return 'pass' if ok else 'fail'


def _result(keys, cells, checks, validity, ratios, kill=False):
    inconclusive = any(_incomplete(cells.get(k)) for k in keys)
    ok = not inconclusive and all(checks.values()) and not validity and not kill
    return {'pass': ok, 'inconclusive': inconclusive, 'checks': checks, 'validity_problems': validity,
            'verdict': _verdict(inconclusive, ok, validity, kill), 'ratios': {k: _f(v) for k, v in ratios.items()}}


def materials_gate(summary, backend) -> dict:
    cells = summary.get('cells', {})
    keys = [f'{backend}/materials/{w}/{a}' for w in ('cold', 'warm') for a in ('A', 'C')]
    if any(k not in cells for k in keys):
        return {'pass': False, 'inconclusive': True, 'checks': {}, 'validity_problems': ['missing cells'],
                'ratios': {'cold_tokens': None, 'cold_makespan': None, 'warm_tokens': None, 'warm_makespan': None}}
    ca, cc, wa, wc = (cells[k] for k in keys)
    ratios = {'cold_tokens': _ratio(_tpc(cc), _tpc(ca)), 'cold_makespan': _ratio(_span(cc, 'test'), _span(ca, 'ref')),
              'warm_tokens': _ratio(_tpc(wc), _tpc(wa)),
              'warm_makespan': _ratio(_span(wc, 'test'), _span(wa, 'ref'))}
    checks = {'cold_correctness_preserved': int(cc['correct']) >= int(ca['correct']),
              'warm_correctness_preserved': int(wc['correct']) >= int(wa['correct']),
              'cold_tokens_at_most_0.75': ratios['cold_tokens'] is not None and ratios['cold_tokens'] <= Fraction(3, 4),
              'warm_tokens_at_most_0.5': ratios['warm_tokens'] is not None and ratios['warm_tokens'] <= Fraction(1, 2),
              'warm_makespan_at_most_0.9': ratios['warm_makespan'] is not None
              and ratios['warm_makespan'] <= Fraction(9, 10)}
    kill = any(int(cells[k].get('rule_errors', 0)) > 0 for k in cells if k.startswith(f'{backend}/materials/'))
    return _result(keys, cells, checks, _validity(summary, backend, 'materials'), ratios, kill or safety_kill(summary))


def boolq_gate(summary) -> dict:
    cells = summary.get('cells', {})
    keys = ['codex/boolq/cold/A', 'codex/boolq/cold/C']
    if any(k not in cells for k in keys):
        return {'pass': False, 'inconclusive': True, 'checks': {}, 'validity_problems': ['missing cells'],
                'ratios': {'tokens': None, 'makespan': None}}
    a, c = cells[keys[0]], cells[keys[1]]
    err_a, err_c = int(a['jobs']) - int(a['correct']), int(c['jobs']) - int(c['correct'])
    ratios = {'tokens': _ratio(Fraction(int(c['tokens'])), Fraction(int(a['tokens']))),
              'makespan': _ratio(_span(c, 'test'), _span(a, 'ref'))}
    checks = {'no_added_gold_errors': err_c <= err_a,
              'tokens_at_most_1.10': ratios['tokens'] is not None and ratios['tokens'] <= Fraction(11, 10),
              'makespan_at_most_1.10': ratios['makespan'] is not None and ratios['makespan'] <= Fraction(11, 10)}
    return _result(keys, cells, checks, _validity(summary, 'codex', 'boolq'), ratios, safety_kill(summary))


def pooling_gate(summary) -> dict:
    cells = summary.get('cells', {})
    keys = ['codex/materials/cold/B', 'codex/materials/cold/C']
    if any(k not in cells for k in keys):
        return {'pass': False, 'inconclusive': True, 'checks': {}, 'validity_problems': ['missing cells'],
                'ratios': {'tokens': None, 'makespan': None}}
    b, c = cells[keys[0]], cells[keys[1]]
    ratios = {'tokens': _ratio(Fraction(int(c['tokens'])), Fraction(int(b['tokens']))),
              'makespan': _ratio(_span(c, 'test'), _span(b, 'ref'))}
    checks = {'tokens_below_B': int(c['tokens']) < int(b['tokens']),
              'correctness_not_worse': int(c['correct']) >= int(b['correct']),
              'makespan_not_worse': _span(c, 'test') <= _span(b, 'ref')}
    return _result(keys, cells, checks, _validity(summary, 'codex', 'materials'), ratios, safety_kill(summary))


def attribute_tokens(total, jobs_by_op) -> dict:
    """Shared tokens split over operations in proportion to their jobs (largest remainder, ties in the given order);
    the parts always sum exactly to total."""
    total = int(total)
    ops = list(jobs_by_op)
    n = sum(int(v) for v in jobs_by_op.values())
    if n == 0:
        out = {op: 0 for op in ops}
        if ops:
            out[ops[0]] = total
        return out
    exact = {op: Fraction(total * int(jobs_by_op[op]), n) for op in ops}
    out = {op: int(exact[op]) for op in ops}
    rest = total - sum(out.values())
    order = sorted(ops, key=lambda op: (-(exact[op] - out[op]), ops.index(op)))
    for op in order[:rest]:
        out[op] += 1
    return out


def per_operation(summary) -> dict:
    out = {}
    for key, cell in summary.get('cells', {}).items():
        ops = cell.get('ops') or {}
        if not ops:
            continue
        out[key] = {op: {'jobs': v['jobs'], 'correct': v['correct'], 'tokens': v['tokens'],
                         'tokens_per_correct': (v['tokens'] / v['correct']) if v['correct'] else None}
                    for op, v in ops.items()}
    return out


def magnitude(summary, backend) -> dict:
    base = {'status': 'inconclusive', 'token_ratio': None, 'makespan_ratio': None, 'direction_replicated': False,
            'label': None, 'missed': [], 'scope': SCOPE}
    # A4.11 direction requires A4.10's gates, so every validity and safety prerequisite of A4.10 applies before any
    # ratio is computed (council round 1, item 18 and B2).
    reasons = _validity(summary, backend, 'materials')
    if safety_kill(summary):
        reasons = reasons + ['safety kill']
    if reasons:
        return dict(base, status='invalid', reasons=reasons)
    rc = summary.get('R_cells', {})
    a, c = rc.get(f'{backend}/warm/A'), rc.get(f'{backend}/warm/C')
    if a is None or c is None or not summary.get('R'):
        return base
    if _incomplete(a) or _incomplete(c) or int(a['correct']) != int(c['correct']) or not int(c['correct']):
        return base
    tpc_a, tpc_c = _tpc(a), _tpc(c)
    if tpc_c in (None, 0) or _span(c, 'test') == 0:
        return base
    token_ratio = tpc_a / tpc_c
    makespan_ratio = _span(a, 'ref') / _span(c, 'test')
    direction = tpc_c <= tpc_a / 2 and _span(c, 'test') <= _span(a, 'ref') * Fraction(9, 10)
    missed = []
    if token_ratio < PILOT_TOKENS:
        missed.append('tokens')
    if makespan_ratio < PILOT_MAKESPAN:
        missed.append('makespan')
    label = 'at least the pilot magnitude' if not missed else 'smaller than the pilot'
    return {'status': 'pass' if direction else 'fail', 'token_ratio': float(token_ratio),
            'makespan_ratio': float(makespan_ratio), 'direction_replicated': bool(direction), 'label': label,
            'missed': missed, 'scope': SCOPE}


def claims(summary) -> dict:
    kill = safety_kill(summary)
    has_r = bool(summary.get('R'))
    mat = {b: materials_gate(summary, b) for b in ('codex', 'sonnet')}
    bq, pool = boolq_gate(summary), pooling_gate(summary)
    codex = mat['codex']['pass'] and bq['pass'] and not kill
    sonnet = mat['sonnet']['pass'] and not kill
    return {'codex': {'permitted': codex, 'rule_learning_claim': codex and has_r,
                      'pooling_claim': codex and pool['pass']},
            'sonnet': {'permitted': sonnet, 'rule_learning_claim': sonnet and has_r},
            'cross_backend_headline': codex and sonnet and pool['pass'] and has_r and not kill}


def evaluate(summary) -> dict:
    s = copy.deepcopy(summary)
    return {'materials': {b: materials_gate(s, b) for b in ('codex', 'sonnet')}, 'boolq': boolq_gate(s),
            'pooling': pooling_gate(s), 'safety_kill': safety_kill(s), 'claims': claims(s),
            'per_operation': per_operation(s), 'magnitude': {b: magnitude(s, b) for b in ('codex', 'sonnet')}}
