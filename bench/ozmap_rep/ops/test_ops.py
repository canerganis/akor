"""Tests for ops.md: every rule has a hand-computed expectation (never derived by calling gold), plus determinism
and uniqueness of the generators. Run: python -m pytest bench/ozmap_rep/ops -q"""
import pytest

from . import data, oracle

BASE = ('specimen=J23-0412; grade={grade}; yield={y}; uts={u}; gauge={g}; final={f}; temp={t}; operator=mk')


def rec(grade='S355', y='372 MPa', u='541 MPa', g='50.00 mm', f='61.20 mm', t='23 C'):
    return BASE.format(grade=grade, y=y, u=u, g=g, f=f, t=t)


# ------------------------------------------------------------------------------------------------- verdict

@pytest.mark.parametrize('grade,y,u,expected', [
    ('S355', '372 MPa', '541 MPa', 'pass'),
    ('S355', '355 MPa', '470 MPa', 'pass'),           # both endpoints inclusive
    ('S355', '354.9 MPa', '470 MPa', 'fail'),         # yield one tenth below
    ('S355', '355 MPa', '469 MPa', 'fail'),           # uts below
    ('S235', '235.00 MPa', '360.0 MPa', 'pass'),      # trailing zeros carry no meaning
    ('S275', '275 N/mm2', '410 N/mm2', 'pass'),       # unit synonym, no conversion
    ('S460', '460 MPa', '539.9 MPa', 'fail'),
    ('A36', '250 MPa', '400 MPa', 'pass'),
    ('A36', '249 MPa', '450 MPa', 'fail'),
    ('S420', '600 MPa', '700 MPa', 'unknown'),        # grade not in the table
    ('unknown', '372 MPa', '541 MPa', 'unknown'),
    ('S355', 'unknown', '541 MPa', 'unknown'),
    ('S355', '372 MPa', 'unknown', 'unknown'),
    ('S355', 'unknown', '100 MPa', 'unknown'),        # unknown wins over a failing uts
])
def test_verdict(grade, y, u, expected):
    assert oracle.gold('verdict', rec(grade=grade, y=y, u=u)) == expected


# -------------------------------------------------------------------------------------------------- margin

@pytest.mark.parametrize('y,u,expected', [
    ('372 MPa', '541 MPa', '169 MPa'),
    ('355.5 MPa', '358 MPa', '2 MPa'),                # 2.5 -> 2 half to even
    ('355.5 MPa', '359 MPa', '4 MPa'),                # 3.5 -> 4 half to even
    ('400 MPa', '399.6 N/mm2', '0 MPa'),              # -0.4 -> 0, never -0
    ('400 MPa', '400.4 MPa', '0 MPa'),
    ('400 MPa', '400 MPa', '0 MPa'),
    ('400.0 MPa', '400.00 MPa', '0 MPa'),
    ('412 MPa', '400 MPa', '-12 MPa'),                # negative keeps its sign
    ('400 MPa', '397.5 MPa', '-2 MPa'),               # -2.5 -> -2 half to even
    ('400 MPa', '396.5 MPa', '-4 MPa'),               # -3.5 -> -4
    ('300.25 MPa', '420.75 MPa', '120 MPa'),          # 120.5 -> 120
    ('300.25 MPa', '421.75 MPa', '122 MPa'),          # 121.5 -> 122
    ('372 N/mm2', '541 N/mm2', '169 MPa'),            # output unit is always MPa
    ('unknown', '541 MPa', 'unknown'),
    ('372 MPa', 'unknown', 'unknown'),
])
def test_margin(y, u, expected):
    assert oracle.gold('margin', rec(y=y, u=u)) == expected


# --------------------------------------------------------------------------------------------------- elong

@pytest.mark.parametrize('g,f,expected', [
    ('50.00 mm', '61.20 mm', '22.4 %'),               # 11.20 / 50 * 100 = 22.4 exactly
    ('80.00 mm', '94.60 mm', '18.3 %'),               # 18.25 tie -> half away from zero
    ('80.00 mm', '94.20 mm', '17.8 %'),               # 17.75 tie -> 17.8
    ('40.00 mm', '47.30 mm', '18.3 %'),               # 18.25 tie
    ('80.00 mm', '79.80 mm', '-0.3 %'),               # -0.25 tie -> away from zero
    ('30.00 mm', '35.00 mm', '16.7 %'),               # 16.666... repeating
    ('60.00 mm', '70.00 mm', '16.7 %'),
    ('70.00 mm', '75.00 mm', '7.1 %'),                # 7.142857...
    ('90.00 mm', '101.00 mm', '12.2 %'),              # 12.222...
    ('50 mm', '50.00 mm', '0.0 %'),
    ('50.00 mm', '50.02 mm', '0.0 %'),                # 0.04 -> 0.0
    ('50.00 mm', '49.98 mm', '0.0 %'),                # -0.04 -> 0.0, never -0.0
    ('50.00 mm', '49.95 mm', '-0.1 %'),               # -0.1 exactly
    ('80 mm', '96.000 mm', '20.0 %'),                 # mixed spellings
    ('50.00 mm', '48.00 mm', '-4.0 %'),
    ('unknown', '61.20 mm', 'unknown'),
    ('50.00 mm', 'unknown', 'unknown'),
])
def test_elong(g, f, expected):
    assert oracle.gold('elong', rec(g=g, f=f)) == expected


# ---------------------------------------------------------------------------------------------- temp_class

@pytest.mark.parametrize('t,expected', [
    ('23 C', 'room'),
    ('10 C', 'room'), ('35 C', 'room'), ('10.0 C', 'room'), ('35.00 degC', 'room'),
    ('9.99 C', 'cold'), ('9 C', 'cold'), ('-5.0 degC', 'cold'), ('-40 C', 'cold'), ('0 C', 'cold'),
    ('35.01 C', 'hot'), ('36 C', 'hot'), ('200 C', 'hot'), ('35.1 degC', 'hot'),
    ('unknown', 'unknown'),
])
def test_temp_class(t, expected):
    assert oracle.gold('temp_class', rec(t=t)) == expected


# -------------------------------------------------------------------------------------------- record shape

def test_terminal_newline_and_reorder_do_not_change_results():
    text = rec()
    for ending in ('\n', '\r\n'):
        assert oracle.gold('margin', text + ending) == '169 MPa'
        assert oracle.gold('elong', text + ending) == '22.4 %'
    shuffled = 'temp=23 C; final=61.20 mm; operator=mk; uts=541 MPa; specimen=J23-0412; gauge=50.00 mm; yield=372 MPa; grade=S355'
    assert oracle.gold('verdict', shuffled) == 'pass'
    assert oracle.gold('temp_class', shuffled) == 'room'
    # a second terminal newline is part of the record and makes it malformed
    with pytest.raises(ValueError):
        oracle.gold('margin', text + '\n\n')


def test_extra_keys_ignored_and_malformed_rejected():
    assert oracle.gold('margin', rec() + '; machine=ZW-100') == '169 MPa'
    for bad in ('specimen=J1; yield=372 MPa; uts=541 MPa; yield=1 MPa', 'specimen=J1; yield=372MPa; uts=541 MPa',
                'specimen=J1; yield=0372 MPa; uts=541 MPa', 'specimen=J1; yield=372 psi; uts=541 MPa',
                'specimen=J1; yield=372 MPa;uts=541 MPa', 'specimen=J1; yield=372 MPa; uts=541 MPa; empty='):
        with pytest.raises(ValueError):
            oracle.gold('margin', bad)
    with pytest.raises(ValueError):
        oracle.gold('verdict', 'specimen=J1; yield=372 MPa; uts=541 MPa')   # grade missing
    with pytest.raises(ValueError):
        oracle.gold('nope', rec())


# ----------------------------------------------------------------------------------------------- generators

def test_jobs_deterministic_unique_and_well_formed():
    a, b = data.jobs(7, 120), data.jobs(7, 120)
    assert a == b
    assert len(a) == 120
    texts = [j['text'] for j in a]
    assert len(set(texts)) == len(texts)
    assert len({oracle.strip_terminator(t) for t in texts}) == len(texts)
    assert len({j['id'] for j in a}) == len(a)
    assert {j['op'] for j in a} == set(oracle.OPS)
    for j in a:
        assert set(j) == {'id', 'op', 'text'}
        assert 80 <= len(j['text']) <= 250
        oracle.gold(j['op'], j['text'])      # every job is a legal record
    assert data.jobs(8, 120) != a


def test_jobs_cover_every_category_and_every_output():
    n = 4 * 11 * 3
    jobs, cats = data.jobs(11, n), data.job_categories(11, n)
    seen = {op: set() for op in oracle.OPS}
    outputs = {op: set() for op in oracle.OPS}
    for j, c in zip(jobs, cats):
        seen[j['op']].add(c)
        outputs[j['op']].add(oracle.gold(j['op'], j['text']))
    for op in oracle.OPS:
        assert seen[op] == set(data.PLANS[op])
    assert outputs['verdict'] == {'pass', 'fail', 'unknown'}
    assert outputs['temp_class'] == {'cold', 'room', 'hot', 'unknown'}
    assert 'unknown' in outputs['margin'] and '0 MPa' in outputs['margin']
    assert 'unknown' in outputs['elong'] and '0.0 %' in outputs['elong']
    assert any(t.endswith('\n') for t in (j['text'] for j in jobs))
    assert any('N/mm2' in j['text'] for j in jobs) and any('degC' in j['text'] for j in jobs)


def test_admission_deterministic_disjoint_and_labeled():
    adm = data.admission_cases(7, 80)
    assert adm == data.admission_cases(7, 80)
    assert len(adm) == 80
    texts = [c['text'] for c in adm]
    assert len(set(texts)) == len(texts)
    for c in adm:
        assert set(c) == {'text', 'op', 'gold'}
        assert c['gold'] == oracle.gold(c['op'], c['text'])
        assert 'specimen=A' in c['text']
    job_texts = {oracle.strip_terminator(j['text']) for j in data.jobs(7, 400)}
    assert not job_texts & {oracle.strip_terminator(t) for t in texts}
