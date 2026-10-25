"""A4.4 capacity formulas and A4.5 physical call allocations, reserves, caps and their enforcement."""
import pytest

from ozrep_helpers import harness, need

MATERIALS = {'cold_A': 4, 'bootstrap': 1, 'cold_B': 8, 'cold_C': 4, 'warm_A': 4, 'warm_C': 5}
BOOLQ = {'cold_A': 4, 'bootstrap': 1, 'cold_B': 4, 'cold_C': 3}


def budget_cls():
    return need(harness('budget'), 'Budget')


# ---------------------------------------------------------------------------------------------------- A4.4

def test_a4_4_cold_capacity_for_materials_with_zero_admitted_rules():
    capacity = need(harness('budget'), 'capacity')
    out = capacity(producers=[64] * 4, bootstrap=[16] * 4, audits=32)
    assert out == {'pooled': 4, 'local': 8}


def test_a4_4_warm_capacity_pooled_is_five():
    capacity = need(harness('budget'), 'capacity')
    out = capacity(producers=[64] * 4, bootstrap=[0] * 4, audits=32)
    assert out['pooled'] == 5  # ceil((256 + 32) / 64)


def test_a4_4_arm_a_has_no_bootstrap_and_no_audits():
    capacity = need(harness('budget'), 'capacity')
    assert capacity(producers=[64] * 4, bootstrap=[0] * 4, audits=0) == {'pooled': 4, 'local': 4}


def test_a4_4_boolq_has_no_audits():
    capacity = need(harness('budget'), 'capacity')
    assert capacity(producers=[64] * 4, bootstrap=[16] * 4, audits=0) == {'pooled': 3, 'local': 4}


def test_a4_4_formula_ceilings_and_conservative_local_audit_assignment():
    capacity = need(harness('budget'), 'capacity')
    # pooled: ceil((sum(N_p - b_p) + a) / M); local: sum_p ceil((N_p - b_p + a) / M), full audit allowance per producer
    assert capacity([10, 10], [0, 0], 0, M=64) == {'pooled': 1, 'local': 2}
    assert capacity([64, 64], [0, 0], 1, M=64) == {'pooled': 3, 'local': 4}
    assert capacity([100], [36], 0, M=64) == {'pooled': 1, 'local': 1}
    assert capacity([100], [35], 0, M=64) == {'pooled': 2, 'local': 2}


def test_a4_4_allocations_equal_the_formulas():
    cfg = harness('config')
    capacity = need(harness('budget'), 'capacity')
    alloc = need(cfg, 'ALLOCATIONS')
    mat, boolq = alloc['codex/materials'], alloc['codex/boolq']
    cold = capacity([64] * 4, [16] * 4, 32)
    warm = capacity([64] * 4, [0] * 4, 32)
    assert mat['cold_B'] == cold['local'] and mat['cold_C'] == cold['pooled']
    assert mat['warm_C'] == warm['pooled']
    nb = capacity([64] * 4, [16] * 4, 0)
    assert boolq['cold_B'] == nb['local'] and boolq['cold_C'] == nb['pooled']


# ---------------------------------------------------------------------------------------------------- A4.5

def test_a4_5_allocation_values():
    alloc = need(harness('config'), 'ALLOCATIONS')
    assert alloc['codex/materials'] == MATERIALS
    assert alloc['sonnet/materials'] == MATERIALS
    assert alloc['codex/boolq'] == BOOLQ
    assert sum(MATERIALS.values()) == 26 and sum(BOOLQ.values()) == 12


def test_a4_5_evaluation_caps():
    caps = need(harness('config'), 'EVAL_CAPS')
    assert caps['codex'] == {'nominal': 38, 'telemetry': 4, 'reserve': 20, 'total': 62}
    assert caps['sonnet'] == {'nominal': 26, 'telemetry': 2, 'reserve': 12, 'total': 40}
    assert need(harness('config'), 'RESERVE_PER_ALLOCATION') == 2


def test_a4_5_preparation_caps_and_global_total():
    cfg = harness('config')
    # A4.13r1.1 (signed revision 1): Opus 40 -> 70, global 206 -> 236
    assert need(cfg, 'PREP_CAPS') == {'astra': 20, 'opus': 70, 'fable': 4, 'sonnet': 40}
    assert need(cfg, 'GLOBAL_CAP') == 236
    caps = cfg.EVAL_CAPS
    assert caps['codex']['total'] + caps['sonnet']['total'] + sum(cfg.PREP_CAPS.values()) == 236


def test_a4_5_each_listed_allocation_receives_two_reserve_calls():
    cfg = harness('config')
    alloc = cfg.ALLOCATIONS
    codex_allocs = len(alloc['codex/materials']) + len(alloc['codex/boolq'])
    assert codex_allocs * cfg.RESERVE_PER_ALLOCATION == cfg.EVAL_CAPS['codex']['reserve']
    assert len(alloc['sonnet/materials']) * cfg.RESERVE_PER_ALLOCATION == cfg.EVAL_CAPS['sonnet']['reserve']


def test_a4_5_nominal_use_up_to_the_allocation_then_refuse():
    exceeded = need(harness('budget'), 'BudgetExceeded')
    b = budget_cls()()
    for n in range(8):
        assert b.charge('codex', 'materials', 'cold_B')['kind'] == 'nominal'
    with pytest.raises(exceeded):
        b.charge('codex', 'materials', 'cold_B')  # a ninth nominal call is not authorized
    assert b.physical_total('codex') == 8


def test_a4_5_reserve_is_two_per_allocation_and_only_for_infrastructure():
    mod = harness('budget')
    exceeded, misuse = need(mod, 'BudgetExceeded'), need(mod, 'ReserveMisuse')
    b = budget_cls()()
    for _ in range(4):
        b.charge('codex', 'materials', 'cold_C')
    assert b.charge('codex', 'materials', 'cold_C', reason='infrastructure_retry')['kind'] == 'reserve'
    assert b.charge('codex', 'materials', 'cold_C', reason='audit_overflow')['kind'] == 'reserve'
    with pytest.raises(exceeded):
        b.charge('codex', 'materials', 'cold_C', reason='infrastructure_retry')
    assert b.physical_total('codex') == 6


@pytest.mark.parametrize('reason', ['new_learning', 'answer_repair', 'new_condition'])
def test_a4_5_unused_capacity_cannot_authorize_learning_repair_or_conditions(reason):
    mod = harness('budget')
    misuse = need(mod, 'ReserveMisuse')
    b = budget_cls()()
    for _ in range(4):
        b.charge('codex', 'materials', 'cold_C')
    with pytest.raises(misuse):
        b.charge('codex', 'materials', 'cold_C', reason=reason)
    with pytest.raises(misuse):  # not even while the allocation still has nominal room
        b.charge('codex', 'materials', 'warm_C', reason=reason)
    assert b.physical_total('codex') == 4


def test_a4_5_overrun_is_not_covered_by_another_allocations_unused_capacity():
    exceeded = need(harness('budget'), 'BudgetExceeded')
    b = budget_cls()()
    for _ in range(8):
        b.charge('codex', 'materials', 'cold_B')
    for _ in range(2):
        b.charge('codex', 'materials', 'cold_B', reason='infrastructure_retry')
    with pytest.raises(exceeded):  # cold_A (4), warm_C (5) and the rest are untouched, but not transferable
        b.charge('codex', 'materials', 'cold_B', reason='infrastructure_retry')


def test_a4_5_telemetry_caps_codex_four_sonnet_two():
    exceeded = need(harness('budget'), 'BudgetExceeded')
    b = budget_cls()()
    for _ in range(4):
        b.charge('codex', 'telemetry', 'telemetry')
    with pytest.raises(exceeded):
        b.charge('codex', 'telemetry', 'telemetry')
    for _ in range(2):
        b.charge('sonnet', 'telemetry', 'telemetry')
    with pytest.raises(exceeded):
        b.charge('sonnet', 'telemetry', 'telemetry')


def test_a4_5_boolq_allocations_are_codex_only_and_have_no_warm_wave():
    exceeded = need(harness('budget'), 'BudgetExceeded')
    b = budget_cls()()
    for name in ('warm_A', 'warm_C'):
        with pytest.raises((exceeded, KeyError, ValueError)):
            b.charge('codex', 'boolq', name)
    with pytest.raises((exceeded, KeyError, ValueError)):
        b.charge('sonnet', 'boolq', 'cold_A')


def test_a4_5_whole_nominal_plan_fits_the_caps():
    b = budget_cls()()
    for key, allocs in (('codex/materials', MATERIALS), ('sonnet/materials', MATERIALS), ('codex/boolq', BOOLQ)):
        backend, workload = key.split('/')
        for name, n in allocs.items():
            for _ in range(n):
                b.charge(backend, workload, name)
    assert b.physical_total('codex') == 38 and b.physical_total('sonnet') == 26


def test_a4_5_shared_bootstrap_is_one_physical_call_charged_to_both_b_and_c():
    b = budget_cls()()
    b.charge('codex', 'materials', 'bootstrap')
    for _ in range(8):
        b.charge('codex', 'materials', 'cold_B')
    for _ in range(4):
        b.charge('codex', 'materials', 'cold_C')
    assert b.physical_total('codex') == 13
    assert b.analytic_calls('codex', 'materials', 'cold_B') == 9
    assert b.analytic_calls('codex', 'materials', 'cold_C') == 5
    assert b.analytic_calls('codex', 'materials', 'cold_A') == 0


def test_a4_5_failed_calls_consume_allocation_and_stay_on_record():
    b = budget_cls()()
    b.charge('codex', 'materials', 'cold_A', outcome='infrastructure_failure')
    b.charge('codex', 'materials', 'cold_A', outcome='refused')
    assert b.physical_total('codex') == 2
    assert [a['outcome'] for a in b.attempts] == ['infrastructure_failure', 'refused']
