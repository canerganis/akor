"""A4.8: the independent operations replace the original materials operations; task counts and admission design."""
import collections

import pytest

from ozrep_helpers import harness, need

NEW_OPS = ('verdict', 'margin', 'elong', 'temp_class')
OLD_OPS = ('e', 'b', 'm', 'v')


@pytest.fixture(scope='module')
def wl():
    return need(harness('workload'), 'materials')()


def test_a4_8_configured_operations_are_fables_four():
    cfg = harness('config')
    assert tuple(need(cfg, 'OPERATIONS')) == NEW_OPS
    assert not set(OLD_OPS) & set(cfg.OPERATIONS)


def test_a4_8_every_job_and_case_uses_a_new_operation(wl):
    for wave in ('cold', 'warm'):
        assert {j['op'] for j in wl[wave]} == set(NEW_OPS)
    for op, cases in wl['admission'].items():
        assert op in NEW_OPS and all(c['op'] == op for c in cases)
    assert set(wl['admission']) == set(NEW_OPS)


def test_a4_8_old_pilot_records_do_not_appear(wl):
    for j in wl['cold'] + wl['warm']:
        assert 'physical_validation' not in j['text'] and 'uncertainty=' not in j['text']
        assert j['op'] not in OLD_OPS


def test_a4_8_task_counts_are_preserved(wl):
    assert len(wl['cold']) == 256 and len(wl['warm']) == 256
    for wave in ('cold', 'warm'):
        by_producer = collections.Counter(j['producer'] for j in wl[wave])
        assert by_producer == {'p0': 64, 'p1': 64, 'p2': 64, 'p3': 64}
        by_pair = collections.Counter((j['producer'], j['op']) for j in wl[wave])
        assert set(by_pair.values()) == {16} and len(by_pair) == 16
    assert len(wl['bootstrap_ids']) == 64
    cold = {j['id']: j for j in wl['cold']}
    boot = collections.Counter(cold[i]['producer'] for i in wl['bootstrap_ids'])
    assert boot == {'p0': 16, 'p1': 16, 'p2': 16, 'p3': 16}


def test_a4_8_admission_design_is_preserved(wl):
    for op, cases in wl['admission'].items():
        assert len(cases) == 64
        kinds = collections.Counter(c['kind'] for c in cases)
        assert kinds == {'representative': 48, 'challenge': 16}, (op, kinds)


def test_a4_8_job_ids_and_texts_are_unique_and_the_workloads_are_disjoint(wl):
    ids = [j['id'] for j in wl['cold'] + wl['warm']]
    texts = [j['text'] for j in wl['cold'] + wl['warm']]
    assert len(set(ids)) == 512 and len(set(texts)) == 512
    admission = {c['text'] for cases in wl['admission'].values() for c in cases}
    assert not admission & set(texts), 'admission cases must be independent of the evaluation jobs'


def test_a4_8_gold_comes_from_fables_oracle(wl):
    from bench.ozmap_rep.ops import oracle
    workload = harness('workload')
    gold = need(workload, 'gold')
    for j in wl['cold'][:60] + wl['warm'][:20]:
        assert gold(j) == oracle.gold(j['op'], j['text'])
    for op, cases in wl['admission'].items():
        for c in cases:
            assert c['gold'] == oracle.gold(op, c['text']) == gold(c)


def test_a4_8_job_texts_are_valid_tensile_records(wl):
    from bench.ozmap_rep.ops import oracle
    for j in wl['cold'] + wl['warm']:
        oracle.parse(j['text'])  # must not raise


def test_a4_8_workload_is_deterministic():
    one = need(harness('workload'), 'materials')()
    two = harness('workload').materials()
    assert one['cold'] == two['cold'] and one['admission'] == two['admission']


def test_a4_8_fables_operations_are_not_edited():
    import subprocess
    from ozrep_helpers import REPO
    done = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no', '--',
                           'bench/ozmap_rep/ops'], cwd=str(REPO), capture_output=True, text=True)
    assert done.stdout.strip() == ''
