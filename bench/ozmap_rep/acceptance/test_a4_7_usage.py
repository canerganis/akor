"""A4.7: cache and reasoning certification, replay fixtures, additive sensitivity reading."""
import hashlib
import importlib
import json

import pytest

from ozrep_helpers import REPO, harness, need

ROUTE = {'model': 'gpt-6.1-sol', 'effort': 'high', 'cli_version': 'codex-cli 0.160.0'}


def decode(raw, certified=False):
    return need(harness('usage'), 'decode_codex')(raw, cache_certified=certified)


def raw(input_tokens=10000, cached=4000, output=500, reasoning=300):
    return {'input_tokens': input_tokens, 'cached_input_tokens': cached, 'output_tokens': output,
            'reasoning_output_tokens': reasoning}


# ------------------------------------------------------------------------------------- replay fixtures

def test_a4_7_replay_cached_4000_of_10000_gives_uncached_6000_and_charged_input_10000():
    out = decode(raw(10000, 4000), certified=True)
    assert out['uncached_input_tokens'] == 6000
    assert out['charged_input_tokens'] == 10000
    assert out['status'] == 'complete' and out['problems'] == []


def test_a4_7_replay_cached_zero_gives_charged_input_10000():
    out = decode(raw(10000, 0))
    assert out['uncached_input_tokens'] == 10000 and out['charged_input_tokens'] == 10000
    assert out['status'] == 'complete', 'zero cached input needs no inclusion certificate'


def test_a4_7_cached_never_changes_the_charged_input():
    assert decode(raw(10000, 4000), True)['charged_input_tokens'] == decode(raw(10000, 0))['charged_input_tokens']


def test_a4_7_output_and_reasoning_are_not_double_counted():
    out = decode(raw(10000, 0, output=500, reasoning=300))
    assert out['charged_output_tokens'] == 500
    assert out['reasoning_output_tokens'] == 300
    assert out['charged_tokens'] == 10500
    out = decode(raw(10000, 0, output=500, reasoning=0))
    assert out['charged_tokens'] == 10500, 'reasoning counted or not, the charge is input + output'
    assert decode(raw(10000, 0, output=500, reasoning=500))['charged_tokens'] == 10500


def test_a4_7_reasoning_above_output_is_invalid():
    out = decode(raw(10000, 0, output=100, reasoning=101))
    assert out['status'] == 'invalid' and out['problems']


@pytest.mark.parametrize('cached,input_tokens', [(10001, 10000), (-1, 10000), (5, -5)])
def test_a4_7_every_call_must_satisfy_0_le_cached_le_input(cached, input_tokens):
    out = decode(raw(input_tokens, cached), certified=True)
    assert out['status'] == 'invalid' and out['problems']


def test_a4_7_cached_equal_to_input_is_allowed():
    assert decode(raw(10000, 10000), certified=True)['status'] == 'complete'


def test_a4_7_positive_cached_without_certification_is_usage_unverified():
    out = decode(raw(10000, 4000), certified=False)
    assert out['status'] == 'unverified'
    assert out['charged_input_tokens'] == 10000, 'execution continues and the reading stays inclusive'


@pytest.mark.parametrize('missing', ['input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens'])
def test_a4_7_a_missing_counter_is_never_read_as_zero(missing):
    r = raw()
    del r[missing]
    assert decode(r, True)['status'] == 'incomplete'


def test_a4_7_additive_input_accounting_is_a_separate_sensitivity_reading():
    additive = need(harness('usage'), 'additive_tokens')
    assert additive(raw(10000, 4000, 500, 300)) == 14500
    assert additive(raw(10000, 0, 500, 300)) == 10500
    assert decode(raw(10000, 4000, 500, 300), True)['charged_tokens'] == 10500


# ---------------------------------------------------------------------------- reasoning predicate (sign-off 5)

def test_a4_7_reasoning_predicate_equals_the_signed_pilot_predicate():
    try:
        pilot = importlib.import_module('bench.ozmap.pilot')
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f'pilot module not importable: {exc!r}')
    mine = need(harness('usage'), 'reasoning_inclusion')
    cases = [({'output_tokens': 43, 'reasoning_output_tokens': 25}, 12),
             ({'output_tokens': 43, 'reasoning_output_tokens': 25}, 18),
             ({'output_tokens': 12, 'reasoning_output_tokens': 0}, 12),
             ({'output_tokens': 12, 'reasoning_output_tokens': 4}, 12),
             ({'output_tokens': 50, 'reasoning_output_tokens': 20}, 12),
             ({'output_tokens': 20, 'reasoning_output_tokens': 20}, 12),
             ({'output_tokens': 30, 'reasoning_output_tokens': 10}, None),
             ({'output_tokens': 44, 'reasoning_output_tokens': 24}, 12)]
    for usage, visible in cases:
        assert mine(usage, visible) == pilot.reasoning_inclusion(usage, visible), (usage, visible)


# ------------------------------------------------------------------------------------- certificate

def pair(**over):
    p = {'run': 'live-6a518ece47ab', 'route': dict(ROUTE), 'decoder_sha256': 'd' * 64,
         'calls': [{'input': 29694, 'cached': 7296}, {'input': 29694, 'cached': 0}]}
    p.update(over)
    return p


def cert(p):
    return need(harness('usage'), 'Certificate').from_pair(p)


def test_a4_7_live_run_1_pair_is_a_valid_inclusion_certificate():
    c = cert(pair())
    assert c.valid is True
    assert c.applies(ROUTE, 'd' * 64) is True


@pytest.mark.parametrize('calls', [
    [{'input': 29694, 'cached': 0}, {'input': 29694, 'cached': 0}],
    [{'input': 29694, 'cached': 7296}, {'input': 29694, 'cached': 7296}],
    [{'input': 29694, 'cached': 7296}, {'input': 29688, 'cached': 0}],
    [{'input': 100, 'cached': 200}, {'input': 100, 'cached': 0}],
    [{'input': 29694, 'cached': 7296}],
])
def test_a4_7_repetition_alone_or_a_broken_pair_certifies_nothing(calls):
    assert cert(pair(calls=calls)).valid is False


def test_a4_7_a_route_or_decoder_change_requires_renewed_certification():
    c = cert(pair())
    assert c.applies(dict(ROUTE, model='gpt-6.2-sol'), 'd' * 64) is False
    assert c.applies(dict(ROUTE, effort='low'), 'd' * 64) is False
    assert c.applies(dict(ROUTE, cli_version='codex-cli 0.161.0'), 'd' * 64) is False
    assert c.applies(ROUTE, 'e' * 64) is False


def test_a4_7_decoder_source_trace_is_a_hash_of_the_decoder_source():
    usage = harness('usage')
    digest = need(usage, 'decoder_sha256')()
    assert len(digest) == 64 and int(digest, 16) >= 0
    assert digest == need(usage, 'decoder_sha256')()


def test_a4_7_archived_certificate_exists_and_applies_to_the_frozen_route():
    usage = harness('usage')
    c = need(usage, 'load_archived_certificate')()
    assert c.valid is True
    archive = REPO / 'bench' / 'ozmap_rep' / 'certificate' / 'cache-certificate.json'
    doc = json.loads(archive.read_text(encoding='utf-8'))
    assert doc['run'] == 'live-6a518ece47ab'
    assert [(x['input'], x['cached']) for x in doc['calls']] == [(29694, 7296), (29694, 0)]
    assert (doc['route']['model'], doc['route']['effort']) == ('gpt-6.1-sol', 'high')
    assert '0.160.0' in doc['route']['cli_version']
    assert doc['decoder_sha256'] == usage.decoder_sha256(), 'a decoder change requires renewed certification'
    assert c.applies(doc['route'], usage.decoder_sha256()) is True


def test_a4_7_certificate_makes_positive_cached_input_complete_only_for_the_applicable_route():
    usage = harness('usage')
    c = need(usage, 'load_archived_certificate')()
    route_ok = c.applies(json.loads((REPO / 'bench' / 'ozmap_rep' / 'certificate' /
                                     'cache-certificate.json').read_text(encoding='utf-8'))['route'],
                         usage.decoder_sha256())
    assert route_ok
    assert usage.decode_codex(raw(10000, 4000), cache_certified=route_ok)['status'] == 'complete'
    assert usage.decode_codex(raw(10000, 4000), cache_certified=False)['status'] == 'unverified'
