"""Harness tests beyond the blind acceptance suite: the rule path (admitted rule, blind audits, quarantine and
overflow fallback, warm reuse), in-flight recovery after a dead runner, and the A4.4 worst-case schedule.

The rules used here are deliberately not solutions: one answers only `unknown` records and abstains on everything
else, the other answers a constant. Neither comes from the sealed reviewer ASTs."""
import base64
import json
from pathlib import Path

import pytest

from bench.ozmap_rep import config, run, workload

UNKNOWN_ONLY = (b'{"lang":"oz-rule/1","expr":["if",["eq",["field","temp"],["s","unknown"]],["s","unknown"],'
                b'["require",["eq",["s","a"],["s","b"]],["s","x"]]]}')
CONSTANT_ROOM = b'{"lang":"oz-rule/1","expr":["s","room"]}'


def opts(tmp_path, **kw):
    base = tmp_path / 'baseline'
    if not (base / 'auth.json').exists():
        run.synthetic_baseline(base)
    return run.Options(tmp_path / 'run', mode='fake', baseline=base, **kw)


def go(tmp_path, cell_id, **kw):
    return run.CellRun(run.spec_by_id(cell_id), opts(tmp_path, **kw)).run()


def inject_rule(tmp_path, ast, op='temp_class', prefix='codex-materials'):
    """Mark a rule as proposed and admitted in a completed bootstrap result (the fake learner proposes none)."""
    path = tmp_path / 'run' / 'cells' / f'{prefix}-bootstrap' / 'result.json'
    doc = json.loads(path.read_text(encoding='utf-8'))
    doc['rules'][op] = {'proposed': True, 'ast_b64': base64.b64encode(ast).decode(), 'ast_sha256': 'test',
                        'bytes': len(ast), 'admission': {'status': 'accepted', 'reasons': []}}
    path.write_text(json.dumps(doc), encoding='utf-8')


def result(tmp_path, cell_id):
    return json.loads((tmp_path / 'run' / 'cells' / cell_id / 'result.json').read_text(encoding='utf-8'))


def attempts(tmp_path, cell_id=None):
    rows = run.jsonl(tmp_path / 'run' / 'attempts.jsonl')
    return [r for r in rows if cell_id is None or r['cell'] == cell_id]


def test_adopted_rule_answers_covered_jobs_after_agreeing_audits(tmp_path):
    assert go(tmp_path, 'codex-materials-bootstrap') == 0
    inject_rule(tmp_path, UNKNOWN_ONLY)
    assert go(tmp_path, 'codex-materials-cold-C') == 0
    res = result(tmp_path, 'codex-materials-cold-C')
    covered = res['covered']
    assert covered > 0
    assert res['rule_status'] == {'temp_class': 'adopted'}
    assert set(res['audits'].values()) == {'agree'} and len(res['audits']) == min(32, covered)
    rule_rows = [r for r in res['answers'].values() if r['source'] == 'rule']
    assert len(rule_rows) == covered and all(r['answer'] == 'unknown' for r in rule_rows)
    jobs = {j['id']: j for j in workload.jobs_for('materials', 'cold')}
    assert all(row['answer'] == workload.gold(jobs[jid]) for jid, row in res['answers'].items())
    # audits ride in the pooled residual batches, never in extra calls
    assert len(attempts(tmp_path, 'codex-materials-cold-C')) <= config.ALLOCATIONS['codex/materials']['cold_C']
    # warm C reuses only an adopted rule
    assert go(tmp_path, 'codex-materials-cold-A') == 0
    assert go(tmp_path, 'codex-materials-warm-C') == 0
    warm = result(tmp_path, 'codex-materials-warm-C')
    assert warm['rules_applied'] == ['temp_class'] and warm['covered'] > 0


def test_disagreeing_audit_quarantines_the_rule_and_falls_back(tmp_path):
    assert go(tmp_path, 'codex-materials-bootstrap') == 0
    inject_rule(tmp_path, CONSTANT_ROOM)
    assert go(tmp_path, 'codex-materials-cold-C') == 0
    res = result(tmp_path, 'codex-materials-cold-C')
    assert res['rule_status'] == {'temp_class': 'quarantined'}
    assert 'disagree' in res['audits'].values()
    assert res['overflow_jobs'] > 0
    assert not [r for r in res['answers'].values() if r['source'] == 'rule'], 'no rule answer after quarantine'
    jobs = {j['id']: j for j in workload.jobs_for('materials', 'cold')}
    assert len(res['answers']) == 256
    assert all(row['answer'] == workload.gold(jobs[jid]) for jid, row in res['answers'].items())
    rows = attempts(tmp_path, 'codex-materials-cold-C')
    overflow = [r for r in rows if r['batch'].startswith('r2.')]
    assert overflow and all(r['reason'] == 'audit_overflow' for r in overflow)
    assert len(rows) <= config.ALLOCATIONS['codex/materials']['cold_C'] + config.RESERVE_PER_ALLOCATION
    # a quarantined rule is never reused warm
    assert go(tmp_path, 'codex-materials-warm-C') == 0
    assert result(tmp_path, 'codex-materials-warm-C')['rules_applied'] == []


def test_scorer_counts_rule_answers_and_no_safety_kill_for_a_correct_rule(tmp_path):
    for cid in ('codex-materials-bootstrap',):
        assert go(tmp_path, cid) == 0
    inject_rule(tmp_path, UNKNOWN_ONLY)
    for cid in ('codex-materials-cold-A', 'codex-materials-cold-C'):
        assert go(tmp_path, cid) == 0
    from bench.ozmap_rep import score
    rep = score.score_run(tmp_path / 'run')
    cell = rep['cells']['codex/materials/cold/C']
    assert cell['rule_answers'] > 0 and cell['rule_errors'] == 0 and cell['correct'] == 256
    assert rep['gates']['safety_kill'] is False
    assert sum(v['tokens'] for v in cell['ops'].values()) == cell['tokens']


def test_dead_runner_in_flight_call_is_recorded_once_and_retried_from_the_reserve(tmp_path):
    assert go(tmp_path, 'codex-materials-cold-A', stop_after=1) == config.EXIT_INTERRUPTED
    cell_dir = tmp_path / 'run' / 'cells' / 'codex-materials-cold-A'
    # simulate a runner that died after launching the second batch: a marker without an attempt line
    marker = {'call_id': 'codex-materials-cold-A.r1.b01.t0', 'cell': 'codex-materials-cold-A', 'backend': 'codex',
              'workload': 'materials', 'wave': 'cold', 'arm': 'A', 'allocation': 'cold_A', 'batch': 'r1.b01',
              'try': 0, 'reason': 'nominal', 'kind': 'nominal', 'slot': 1, 'mode': 'fake', 'group': 'dead.g1',
              'started_at': '2026-10-24T00:00:00Z', 'job_ids': [], 'records': {}}
    (cell_dir / 'inflight').mkdir(exist_ok=True)
    (cell_dir / 'inflight' / 'codex-materials-cold-A.r1.b01.t0.json').write_text(json.dumps(marker), encoding='utf-8')
    assert go(tmp_path, 'codex-materials-cold-A') == 0
    rows = attempts(tmp_path, 'codex-materials-cold-A')
    assert [r['outcome'] for r in rows if r['batch'] == 'r1.b01'] == ['interrupted', 'ok']
    retry = [r for r in rows if r['batch'] == 'r1.b01'][-1]
    assert retry['reason'] == 'infrastructure_retry' and retry['kind'] == 'reserve'
    assert len({r['call_id'] for r in rows}) == len(rows), 'no call id is ever recorded twice'
    assert go(tmp_path, 'codex-materials-cold-A') == config.EXIT_ALREADY


def test_worst_case_schedule_stays_within_the_a4_4_bounds():
    for spec in run.cell_specs():
        if spec['arm'] != 'bootstrap':
            assert run.worst_case_calls(spec) <= spec['nominal_calls'], spec['id']


def test_sonnet_bootstrap_system_fits_the_windows_command_line():
    from bench.ozmap_rep import prompts
    m = workload.materials()
    boot = [j for j in m['cold'] if j['id'] in set(m['bootstrap_ids'])]
    inp = prompts.model_input(boot, 'materials', bootstrap=True)
    argv = prompts.sonnet_argv(r'C:\Users\x\.local\bin\claude.EXE', config.SONNET_MODEL, None, inp['system'])
    import subprocess
    assert len(subprocess.list2cmdline(argv)) < 32767


def test_learner_material_never_contains_the_classification_or_hidden_pilot_asts():
    import bootstrap_shim
    from bench.ozmap_rep import prompts
    m = workload.materials()
    inp = prompts.model_input(m['cold'][:64], 'materials', bootstrap=True)
    text = prompts.prompt_record(inp)
    bootstrap_shim.check_hidden(text)
    for word in ('Expectation', 'rule-shaped', 'not rule-shaped', 'legitimate answer', 'Edge categories'):
        assert word not in text, word
