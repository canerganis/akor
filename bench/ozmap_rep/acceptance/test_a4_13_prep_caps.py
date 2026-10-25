"""A4.13: preparation and review call ledger and caps (Astra 20, Opus 70 under A4.13r1.1, Fable 4, Sonnet 40,
cumulative)."""
import json

import pytest

from ozrep_helpers import REPO, harness, jsonl, need

CAPS = {'astra': 20, 'opus': 70, 'fable': 4, 'sonnet': 40}  # A4.13r1.1 (signed revision 1): Opus 40 -> 70


def ledger(tmp_path):
    return need(harness('budget'), 'PrepLedger')(tmp_path / 'ledger.jsonl')


def test_a4_13_caps_are_configured():
    assert need(harness('config'), 'PREP_CAPS') == CAPS


def test_a4_13_log_line_has_agent_role_category_timestamp_purpose(tmp_path):
    led = ledger(tmp_path)
    led.log('sonnet', 'acceptance-test-writer', 'preparation', 'blind acceptance tests')
    row = jsonl(tmp_path / 'ledger.jsonl')[0]
    for key in ('agent', 'role', 'category', 'timestamp', 'purpose'):
        assert row[key], key
    assert row['agent'] == 'sonnet' and row['category'] == 'preparation'


def test_a4_13_counts_sum_prior_reconstructed_counts_and_new_calls(tmp_path):
    led = ledger(tmp_path)
    led.log('astra', 'reconstructed', 'preparation', 'earlier calls', count=7)
    led.log('opus', 'reconstructed', 'preparation', 'earlier calls', count=10)
    led.log('fable', 'reconstructed', 'preparation', 'earlier calls', count=1)
    led.log('sonnet', 'writer', 'preparation', 'this call')
    assert led.counts() == {'astra': 7, 'opus': 10, 'fable': 1, 'sonnet': 1}


@pytest.mark.parametrize('agent,cap', sorted(CAPS.items()))
def test_a4_13_the_call_that_would_exceed_a_cap_is_refused_and_not_written(tmp_path, agent, cap):
    mod = harness('budget')
    exceeded = need(mod, 'CapExceeded')
    led = ledger(tmp_path)
    led.log(agent, 'bulk', 'review', 'up to the cap', count=cap - 1)
    assert led.would_exceed(agent) is False
    led.log(agent, 'last', 'review', 'the call that reaches the cap')
    assert led.counts()[agent] == cap
    assert led.would_exceed(agent) is True
    with pytest.raises(exceeded):
        led.log(agent, 'one too many', 'review', 'must not be written')
    assert led.counts()[agent] == cap
    assert sum(r.get('count', 1) for r in jsonl(tmp_path / 'ledger.jsonl') if r['agent'] == agent) == cap


def test_a4_13_a_multi_call_entry_cannot_straddle_the_cap(tmp_path):
    exceeded = need(harness('budget'), 'CapExceeded')
    led = ledger(tmp_path)
    led.log('fable', 'x', 'preparation', 'three', count=3)
    assert led.would_exceed('fable', 2) is True and led.would_exceed('fable', 1) is False
    with pytest.raises(exceeded):
        led.log('fable', 'x', 'preparation', 'two more', count=2)


def test_a4_13_counters_are_cumulative_across_ledger_instances(tmp_path):
    first = ledger(tmp_path)
    first.log('opus', 'r', 'review', 'one', count=CAPS['opus'] - 1)  # A4.13r1.1: the cap is no longer 40
    again = need(harness('budget'), 'PrepLedger')(tmp_path / 'ledger.jsonl')
    assert again.counts()['opus'] == CAPS['opus'] - 1
    again.log('opus', 'r', 'review', 'the call that reaches the cap')
    assert first.would_exceed('opus') is True


def test_a4_13_unknown_agent_is_refused(tmp_path):
    led = ledger(tmp_path)
    with pytest.raises((ValueError, KeyError)):
        led.log('gpt-5', 'r', 'review', 'not an allowed preparation agent')


def test_a4_13_the_real_ledger_file_is_well_formed_and_within_caps():
    path = REPO / 'docs' / 'design' / 'ozmap-replication-2026-10-24' / 'call-ledger.jsonl'
    assert path.exists(), 'every preparation and review call is logged here (A4.13.2)'
    totals = {}
    for row in jsonl(path):
        for key in ('agent', 'role', 'category', 'timestamp', 'purpose'):
            assert row.get(key), (key, row)
        totals[row['agent']] = totals.get(row['agent'], 0) + int(row.get('count', 1))
    for agent, n in totals.items():
        assert n <= CAPS[agent], f'{agent}: {n} calls over the cap {CAPS[agent]}'
