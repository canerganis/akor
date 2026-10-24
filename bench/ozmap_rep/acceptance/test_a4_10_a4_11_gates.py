"""A4.10 success gates and headlines, A4.11 direction, magnitude and verdicts. Pure functions on a summary dict."""
import copy

import pytest

from ozrep_helpers import BACKENDS, harness, need, passing_summary


def gates():
    return harness('gates')


def S():
    return passing_summary()


def set_cell(summary, key, **kw):
    summary['cells'][key].update(kw)
    return summary


# ------------------------------------------------------------------------------------- A4.10 materials gate

@pytest.mark.parametrize('backend', BACKENDS)
def test_a4_10_passing_summary_passes_the_materials_gate(backend):
    out = need(gates(), 'materials_gate')(S(), backend)
    assert out['pass'] is True and out['inconclusive'] is False
    assert out['ratios']['cold_tokens'] == pytest.approx(0.7)
    assert out['ratios']['warm_tokens'] == pytest.approx(0.4)
    assert out['ratios']['warm_makespan'] == pytest.approx(0.8)


def test_a4_10_cold_token_reduction_of_exactly_25_percent_passes_and_less_fails():
    gate = need(gates(), 'materials_gate')
    for tokens, expected in ((75000, True), (75001, False)):
        s = set_cell(S(), 'codex/materials/cold/C', tokens=tokens)
        assert gate(s, 'codex')['pass'] is expected, tokens


def test_a4_10_cold_c_must_preserve_correctness():
    gate = need(gates(), 'materials_gate')
    s = set_cell(S(), 'sonnet/materials/cold/C', correct=255, unresolved=0, jobs=256)
    out = gate(s, 'sonnet')
    assert out['pass'] is False and out['inconclusive'] is False
    assert gate(S(), 'sonnet')['pass'] is True


def test_a4_10_cold_makespan_is_reported_but_not_gated():
    gate = need(gates(), 'materials_gate')
    s = set_cell(S(), 'codex/materials/cold/C', makespan_s=5000.0)
    out = gate(s, 'codex')
    assert out['pass'] is True
    assert out['ratios']['cold_makespan'] == pytest.approx(100.0)


def test_a4_10_warm_c_tokens_at_most_half_of_a():
    gate = need(gates(), 'materials_gate')
    for tokens, expected in ((50000, True), (50001, False)):
        s = set_cell(S(), 'codex/materials/warm/C', tokens=tokens)
        assert gate(s, 'codex')['pass'] is expected, tokens


def test_a4_10_warm_c_makespan_at_most_nine_tenths_of_a():
    gate = need(gates(), 'materials_gate')
    for makespan, expected in ((45.0, True), (45.01, False)):
        s = set_cell(S(), 'sonnet/materials/warm/C', makespan_s=makespan)
        assert gate(s, 'sonnet')['pass'] is expected, makespan


def test_a4_10_tokens_are_per_gold_correct_job_not_per_job():
    gate = need(gates(), 'materials_gate')
    s = S()
    set_cell(s, 'codex/materials/warm/A', correct=128, unresolved=0, tokens=100000)  # A resolves fewer jobs correctly
    set_cell(s, 'codex/materials/warm/C', correct=256, tokens=60000)
    out = gate(s, 'codex')
    assert out['ratios']['warm_tokens'] == pytest.approx((60000 / 256) / (100000 / 128))
    assert out['pass'] is True  # 0.3 per correct job although 0.6 per total tokens


@pytest.mark.parametrize('key', ['codex/materials/cold/A', 'codex/materials/cold/C', 'codex/materials/warm/A',
                                 'codex/materials/warm/C'])
@pytest.mark.parametrize('field,value', [('usage', 'unverified'), ('usage', 'incomplete'), ('state', 'interrupted'),
                                         ('state', 'incomplete'), ('evidence', 'incomplete'), ('unresolved', 3)])
def test_a4_10_success_requires_complete_cells_and_complete_relevant_usage(key, field, value):
    s = set_cell(S(), key, **{field: value})
    out = need(gates(), 'materials_gate')(s, 'codex')
    assert out['pass'] is False and out['inconclusive'] is True


def test_a4_10_other_backends_incomplete_cell_does_not_block_this_backend():
    s = set_cell(S(), 'codex/materials/warm/C', state='interrupted')
    assert need(gates(), 'materials_gate')(s, 'sonnet')['pass'] is True


def test_a4_10_isolation_must_have_passed():
    s = S()
    s['validity']['isolation'] = 'failed'
    for backend in BACKENDS:
        assert need(gates(), 'materials_gate')(s, backend)['pass'] is False


def test_a4_10_applicable_bootstrap_validity_is_required_per_backend():
    s = S()
    s['validity']['bootstrap']['codex/materials'] = {'efficiency_valid': False, 'completion_failure': False}
    g = gates()
    assert g.materials_gate(s, 'codex')['pass'] is False
    assert g.materials_gate(s, 'sonnet')['pass'] is True
    s = S()
    s['validity']['bootstrap']['sonnet/materials'] = {'efficiency_valid': True, 'completion_failure': True}
    assert g.materials_gate(s, 'sonnet')['pass'] is False


def test_a4_10_safety_kill_on_any_accepted_incorrect_rule_answer():
    g = gates()
    assert need(g, 'safety_kill')(S()) is False
    s = set_cell(S(), 'codex/materials/cold/C', rule_errors=1)
    assert g.safety_kill(s) is True
    assert g.materials_gate(s, 'codex')['pass'] is False
    claims = g.claims(s)
    assert claims['codex']['permitted'] is False and claims['cross_backend_headline'] is False


# ------------------------------------------------------------------------------------- A4.10 BoolQ gate

def test_a4_10_boolq_passes_with_no_added_errors_and_at_most_ten_percent_overhead():
    out = need(gates(), 'boolq_gate')(S())
    assert out['pass'] is True


def test_a4_10_boolq_c_must_add_no_gold_errors():
    s = set_cell(S(), 'codex/boolq/cold/C', correct=239)
    assert need(gates(), 'boolq_gate')(s)['pass'] is False
    s = set_cell(S(), 'codex/boolq/cold/C', correct=241)  # fewer errors than A is fine
    assert gates().boolq_gate(s)['pass'] is True


def test_a4_10_boolq_token_overhead_boundary_is_ten_percent():
    g = gates()
    assert g.boolq_gate(set_cell(S(), 'codex/boolq/cold/C', tokens=110000))['pass'] is True
    assert g.boolq_gate(set_cell(S(), 'codex/boolq/cold/C', tokens=110001))['pass'] is False


def test_a4_10_boolq_makespan_overhead_boundary_is_ten_percent():
    g = gates()
    assert g.boolq_gate(set_cell(S(), 'codex/boolq/cold/C', makespan_s=66.0))['pass'] is True
    assert g.boolq_gate(set_cell(S(), 'codex/boolq/cold/C', makespan_s=66.01))['pass'] is False


@pytest.mark.parametrize('arm', ['A', 'C'])
def test_a4_10_boolq_incomplete_cell_is_inconclusive(arm):
    s = set_cell(S(), f'codex/boolq/cold/{arm}', usage='unverified')
    out = need(gates(), 'boolq_gate')(s)
    assert out['pass'] is False and out['inconclusive'] is True


# ------------------------------------------------------------------------------------- A4.10 pooling gate

def test_a4_10_pooling_codex_cold_c_must_beat_b_in_tokens_without_worse_correctness_or_makespan():
    g = gates()
    assert need(g, 'pooling_gate')(S())['pass'] is True
    assert g.pooling_gate(set_cell(S(), 'codex/materials/cold/C', tokens=90000))['pass'] is False  # not fewer
    assert g.pooling_gate(set_cell(S(), 'codex/materials/cold/C', correct=255))['pass'] is False
    assert g.pooling_gate(set_cell(S(), 'codex/materials/cold/C', makespan_s=100.01))['pass'] is False
    assert g.pooling_gate(set_cell(S(), 'codex/materials/cold/C', makespan_s=100.0))['pass'] is True


def test_a4_10_pooling_incomplete_b_cell_is_inconclusive():
    out = need(gates(), 'pooling_gate')(set_cell(S(), 'codex/materials/cold/B', usage='unverified'))
    assert out['pass'] is False and out['inconclusive'] is True


# ------------------------------------------------------------------------------------- A4.10 claims

def test_a4_10_all_gates_passing_permits_each_backend_and_the_cross_backend_headline():
    claims = need(gates(), 'claims')(S())
    assert claims['codex'] == {'permitted': True, 'rule_learning_claim': True, 'pooling_claim': True}
    assert claims['sonnet']['permitted'] is True and claims['sonnet']['rule_learning_claim'] is True
    assert claims['cross_backend_headline'] is True


def test_a4_10_backend_claims_are_independent_per_backend():
    g = gates()
    s = set_cell(S(), 'codex/materials/warm/C', tokens=60000)  # Codex fails its warm gate
    claims = g.claims(s)
    assert claims['codex']['permitted'] is False
    assert claims['sonnet']['permitted'] is True and claims['sonnet']['rule_learning_claim'] is True
    assert claims['cross_backend_headline'] is False
    s = set_cell(S(), 'sonnet/materials/cold/C', tokens=80000)  # Sonnet fails its cold gate
    claims = g.claims(s)
    assert claims['sonnet']['permitted'] is False
    assert claims['codex']['permitted'] is True and claims['codex']['rule_learning_claim'] is True
    assert claims['cross_backend_headline'] is False


def test_a4_10_codex_claim_needs_its_boolq_gate_but_sonnet_does_not():
    g = gates()
    s = set_cell(S(), 'codex/boolq/cold/C', correct=200)
    claims = g.claims(s)
    assert claims['codex']['permitted'] is False
    assert claims['sonnet']['permitted'] is True
    assert claims['cross_backend_headline'] is False


def test_a4_10_headline_requires_the_pooling_gate_but_backend_claim_does_not():
    g = gates()
    s = set_cell(S(), 'codex/materials/cold/C', tokens=74000)  # still passes the cold 25% gate against A
    set_cell(s, 'codex/materials/cold/B', tokens=70000)         # but C no longer beats B
    claims = g.claims(s)
    assert claims['codex']['permitted'] is True and claims['codex']['pooling_claim'] is False
    assert claims['cross_backend_headline'] is False


def test_a4_10_empty_r_means_no_rule_learning_claim_and_no_headline():
    g = gates()
    s = S()
    s['R'] = []
    claims = g.claims(s)
    assert claims['codex']['rule_learning_claim'] is False and claims['sonnet']['rule_learning_claim'] is False
    assert claims['cross_backend_headline'] is False


def test_a4_10_evaluate_bundles_gates_and_claims():
    out = need(gates(), 'evaluate')(S())
    for key in ('materials', 'boolq', 'pooling', 'safety_kill', 'claims', 'per_operation', 'magnitude'):
        assert key in out, key


# ------------------------------------------------------------------------------------- per operation

def test_a4_8_attribution_of_shared_costs_never_drops_tokens():
    attribute = need(gates(), 'attribute_tokens')
    for total in (0, 1, 100, 31337):
        out = attribute(total, {'verdict': 64, 'margin': 64, 'elong': 64, 'temp_class': 64})
        assert sum(out.values()) == total and set(out) == {'verdict', 'margin', 'elong', 'temp_class'}
    uneven = attribute(1000, {'verdict': 10, 'margin': 30})
    assert sum(uneven.values()) == 1000 and uneven['margin'] == 750


def test_a4_8_results_are_reported_per_operation():
    s = S()
    ops = ('verdict', 'margin', 'elong', 'temp_class')
    key = 'codex/materials/cold/C'
    s['cells'][key]['ops'] = {op: {'jobs': 64, 'correct': 64, 'tokens': 17500} for op in ops}
    out = need(gates(), 'per_operation')(s)
    assert set(out[key]) == set(ops)
    assert out[key]['verdict']['tokens_per_correct'] == pytest.approx(17500 / 64)
    assert sum(v['tokens'] for v in out[key].values()) == s['cells'][key]['tokens']


# ------------------------------------------------------------------------------------- A4.11

def r_summary(a_tokens, c_tokens, a_span, c_span, jobs=100, correct_a=100, correct_c=100, **kw):
    s = S()
    base = {'jobs': jobs, 'unresolved': 0, 'usage': 'complete', 'state': 'complete', 'evidence': 'complete'}
    s['R_cells']['codex/warm/A'] = {**base, 'correct': correct_a, 'tokens': a_tokens, 'makespan_s': a_span}
    s['R_cells']['codex/warm/C'] = {**base, 'correct': correct_c, 'tokens': c_tokens, 'makespan_s': c_span,
                                    **kw}
    return s


def mag(s, backend='codex'):
    return need(gates(), 'magnitude')(s, backend)


def test_a4_11_pilot_magnitude_requires_4_4_and_1_6_exactly():
    out = mag(r_summary(440000, 100000, 160.0, 100.0))
    assert out['status'] == 'pass' and out['direction_replicated'] is True
    assert out['token_ratio'] == 4.4 and out['makespan_ratio'] == 1.6
    assert out['label'] == 'at least the pilot magnitude' and out['missed'] == []


def test_a4_11_ratios_are_unrounded_and_a_near_miss_is_not_rounded_up():
    out = mag(r_summary(439990, 100000, 160.0, 100.0))
    assert out['token_ratio'] == pytest.approx(4.3999, abs=1e-9) and out['token_ratio'] < 4.4
    assert out['label'] == 'smaller than the pilot' and out['missed'] == ['tokens']


def test_a4_11_each_missed_threshold_is_identified():
    out = mag(r_summary(440000, 100000, 159.0, 100.0))
    assert out['label'] == 'smaller than the pilot' and out['missed'] == ['makespan']
    out = mag(r_summary(300000, 100000, 140.0, 100.0))
    assert out['label'] == 'smaller than the pilot' and sorted(out['missed']) == ['makespan', 'tokens']
    assert out['direction_replicated'] is True


def test_a4_11_direction_needs_the_warm_gates_on_the_subset():
    out = mag(r_summary(190000, 100000, 160.0, 100.0))  # C uses 0.526 of A's tokens per correct job
    assert out['direction_replicated'] is False and out['status'] == 'fail'
    out = mag(r_summary(440000, 100000, 100.0, 100.0))  # no time gain
    assert out['direction_replicated'] is False and out['status'] == 'fail'


def test_a4_11_claims_are_labeled_as_results_on_r_with_new_operations():
    out = mag(r_summary(440000, 100000, 160.0, 100.0))
    assert 'R' in out['scope'] and 'new operations' in out['scope']


@pytest.mark.parametrize('kw', [
    {'correct_c': 99},                       # unequal correctness
    {'unresolved': 1},                       # a job unresolved in C
    {'usage': 'unverified'},                 # uncertified accounting
    {'state': 'interrupted'},                # interrupted cell
])
def test_a4_11_missing_jobs_uncertified_usage_or_interruption_are_inconclusive(kw):
    if 'correct_c' in kw:
        s = r_summary(440000, 100000, 160.0, 100.0, correct_c=kw['correct_c'])
    else:
        s = r_summary(440000, 100000, 160.0, 100.0, **kw)
    out = mag(s)
    assert out['status'] == 'inconclusive'
    assert out['label'] is None, 'never extrapolate unfinished cells'


def test_a4_11_unresolved_job_in_arm_a_is_inconclusive_too():
    s = r_summary(440000, 100000, 160.0, 100.0)
    s['R_cells']['codex/warm/A']['unresolved'] = 2
    assert mag(s)['status'] == 'inconclusive'


@pytest.mark.parametrize('field', ['leakage', 'accounting_failures'])
def test_a4_11_leakage_or_accounting_failure_invalidates_efficiency_evidence(field):
    s = r_summary(440000, 100000, 160.0, 100.0)
    s['validity'][field] = ['codex/materials/warm/C: something'] if field == 'accounting_failures' else \
        ['a tool read']
    assert mag(s)['status'] == 'invalid'
    assert need(gates(), 'materials_gate')(s, 'codex')['pass'] is False


def test_a4_11_accepted_incorrect_rule_answer_is_a_safety_kill_not_a_threshold_miss():
    s = set_cell(r_summary(440000, 100000, 160.0, 100.0), 'codex/materials/warm/C', rule_errors=1)
    assert gates().safety_kill(s) is True


def test_a4_11_completed_valid_comparison_missing_thresholds_fails_rather_than_inconclusive():
    out = mag(r_summary(110000, 100000, 100.0, 100.0))
    assert out['status'] == 'fail'


def test_a4_11_the_summary_is_not_mutated_by_evaluation():
    s = S()
    before = copy.deepcopy(s)
    gates().evaluate(s)
    assert s == before
