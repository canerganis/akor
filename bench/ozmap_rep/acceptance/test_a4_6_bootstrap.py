"""A4.6: classification, the bootstrap gold-error rule scoped to R and to ops with a proposed rule."""
import json

import pytest

from ozrep_helpers import harness, need

R = {'verdict', 'margin', 'temp_class'}


def assess(**kw):
    args = dict(R=R, proposed={}, gold_errors={}, disagreements={}, status='ok')
    args.update(kw)
    return need(harness('bootstrap'), 'assess')(**args)


def test_a4_6_gold_error_on_an_r_op_with_a_proposed_rule_invalidates_that_op():
    out = assess(proposed={'verdict': True}, gold_errors={'verdict': 1})
    assert out['efficiency_invalid_ops'] == ['verdict']
    assert out['efficiency_valid'] is False


def test_a4_6_matched_a_disagreement_invalidates_the_same_way():
    out = assess(proposed={'margin': True}, disagreements={'margin': 2})
    assert out['efficiency_invalid_ops'] == ['margin'] and out['efficiency_valid'] is False


def test_a4_6_only_the_affected_op_is_invalidated():
    out = assess(proposed={'verdict': True, 'margin': True, 'temp_class': True}, gold_errors={'margin': 3})
    assert out['efficiency_invalid_ops'] == ['margin']


def test_a4_6_error_on_an_r_op_without_a_proposed_rule_does_not_invalidate():
    out = assess(proposed={'verdict': False}, gold_errors={'verdict': 4})
    assert out['efficiency_invalid_ops'] == [] and out['efficiency_valid'] is True
    assert out['measured_errors'] == {'verdict': 4}


def test_a4_6_error_outside_r_enters_correctness_and_overhead_not_validity():
    # elong is outside R even though the learner proposed a rule for it
    out = assess(proposed={'elong': True}, gold_errors={'elong': 5}, disagreements={'elong': 1})
    assert out['efficiency_invalid_ops'] == [] and out['efficiency_valid'] is True
    assert out['measured_errors'].get('elong') == 5


def test_a4_6_boolq_bootstrap_errors_never_invalidate_efficiency():
    out = assess(R=set(), proposed={'boolq': False}, gold_errors={'boolq': 5})
    assert out['efficiency_valid'] is True and out['measured_errors'] == {'boolq': 5}
    out = assess(R=R, proposed={'boolq': True}, gold_errors={'boolq': 5})  # boolq is never in R
    assert out['efficiency_invalid_ops'] == [] and out['efficiency_valid'] is True


@pytest.mark.parametrize('status', ['malformed', 'missing', 'timeout'])
def test_a4_6_malformed_or_missing_bootstrap_output_is_a_completion_failure(status):
    out = assess(status=status)
    assert out['completion_failure'] is True and out['efficiency_valid'] is False


def test_a4_6_empty_r_allows_no_rule_learning_claim():
    assert assess(R=set())['rule_learning_claim_allowed'] is False
    assert assess()['rule_learning_claim_allowed'] is True


def classification(**override):
    op = {'rule_shaped': True, 'inputs': 'record text', 'outputs': 'pass|fail|unknown', 'guards': 'unknown grade',
          'domain': 'five grades', 'reasons': 'fixed table and two comparisons'}
    ops = {'verdict': dict(op), 'margin': dict(op), 'elong': {**op, 'rule_shaped': False,
                                                            'reasons': 'division by a per-record value'},
           'temp_class': dict(op)}
    ops.update(override)
    return {'classified_at': '2026-10-24T10:00:00Z', 'operations': ops}


def write(tmp_path, doc):
    path = tmp_path / 'classification.json'
    path.write_text(json.dumps(doc), encoding='utf-8')
    return path


def test_a4_6_r_is_the_set_of_rule_shaped_ops_not_all_four(tmp_path):
    load_r = need(harness('bootstrap'), 'load_R')
    assert load_r(write(tmp_path, classification())) == {'verdict', 'margin', 'temp_class'}


@pytest.mark.parametrize('missing', ['inputs', 'outputs', 'guards', 'domain', 'reasons'])
def test_a4_6_a_rule_shaped_op_needs_inputs_outputs_guards_domain_and_reasons(tmp_path, missing):
    mod = harness('bootstrap')
    bad = classification()
    del bad['operations']['verdict'][missing]
    with pytest.raises(need(mod, 'ClassificationError')):
        mod.load_R(write(tmp_path, bad))


def test_a4_6_classification_cannot_come_after_learner_calls(tmp_path):
    mod = harness('bootstrap')
    path = write(tmp_path, classification())
    assert mod.load_R(path, first_learner_call='2026-10-24T12:00:00Z')
    with pytest.raises(need(mod, 'ClassificationError')):
        mod.load_R(path, first_learner_call='2026-10-24T09:00:00Z')


def test_a4_6_admission_outside_r_is_a_reported_miss_and_r_is_unchanged():
    report = need(harness('bootstrap'), 'admission_report')(R, {'verdict', 'elong'})
    assert report['classification_misses'] == ['elong']
    assert set(report['R']) == R
    assert need(harness('bootstrap'), 'admission_report')(R, {'verdict'})['classification_misses'] == []
