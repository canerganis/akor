"""A4.9: Sonnet keeps the pilot prompt, with no exploratory prompt condition. Plus learner blindness (A4.8)."""
import hashlib

from ozrep_helpers import REPO, harness, need

PILOT_INSTRUCTION_SHA256 = 'ebb9183a89d8e44c66c9e1ca81fa50407af11449646ecd4be3ea0ae3a032fa87'
PILOT_SPEC_SHA256 = '101d6ae09019c9d91cd267b8c700443db5af9d08dd7176bc59fc101f1816fd14'
CONFIG = {'ops': ['verdict', 'margin', 'elong', 'temp_class'],
          'contracts': {op: f'contract of {op}' for op in ('verdict', 'margin', 'elong', 'temp_class')},
          'eligibility': {op: 'eligible' for op in ('verdict', 'margin', 'elong', 'temp_class')}}


def test_a4_9_instruction_hash_is_the_pilot_value():
    prompts = harness('prompts')
    assert need(prompts, 'INSTRUCTION_SHA256') == PILOT_INSTRUCTION_SHA256
    import bootstrap_shim
    assert hashlib.sha256(bootstrap_shim.INSTRUCTION.encode('utf-8')).hexdigest() == PILOT_INSTRUCTION_SHA256


def test_a4_9_spec_excerpt_the_learner_sees_is_unchanged():
    import bootstrap_shim
    assert bootstrap_shim.SPEC_EXCERPT_SHA256 == PILOT_SPEC_SHA256
    raw = (REPO / 'docs' / 'design' / 'ozmap-2026-10-24' / 'bootstrap-spec-excerpt.txt').read_bytes()
    assert hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() == PILOT_SPEC_SHA256


def test_a4_9_sonnet_bootstrap_system_text_is_the_pilot_template():
    import bootstrap_shim
    prompts = harness('prompts')
    system = 'You are a precise batch worker.'
    assert need(prompts, 'sonnet_bootstrap_system')(system, CONFIG) == bootstrap_shim.system_text(system, CONFIG)


def test_a4_9_sonnet_invocation_flags_are_the_pilot_flags():
    import claude_map_adapter
    prompts = harness('prompts')
    assert tuple(need(prompts, 'SONNET_FLAGS')) == tuple(claude_map_adapter.FLAGS)
    assert prompts.sonnet_argv('claude', 'claude-sonnet-5-5', None, 'SYS') == \
        claude_map_adapter.command('claude', 'claude-sonnet-5-5', None, 'SYS')
    assert prompts.sonnet_argv('claude', 'claude-sonnet-5-5', 'high', 'SYS') == \
        claude_map_adapter.command('claude', 'claude-sonnet-5-5', 'high', 'SYS')


def test_a4_9_no_exploratory_prompt_condition_exists():
    prompts = harness('prompts')
    assert not [n for n in dir(prompts) if 'explor' in n.lower() or 'elicit' in n.lower()]
    cfg = harness('config')
    assert not [n for n in dir(cfg) if 'explor' in n.lower() or 'elicit' in n.lower()]


def test_a4_9_none_is_a_valid_reported_outcome_that_never_changes_the_prompt():
    prompts = harness('prompts')
    before = prompts.INSTRUCTION_SHA256
    harness('bootstrap').assess({'verdict'}, {'verdict': False}, {}, {}, 'ok')  # sonnet "none" is just an outcome
    assert prompts.INSTRUCTION_SHA256 == before


def test_a4_8_learner_prompt_leak_check_finds_admission_texts_and_labels():
    leaks = need(harness('prompts'), 'learner_prompt_leaks')
    admission = {'verdict': [{'text': 'specimen=A-0001; grade=S235; yield=300 MPa; uts=400 MPa', 'gold': 'pass',
                              'op': 'verdict', 'kind': 'representative'}]}
    clean = 'Jobs: specimen=J-0001; grade=S235; yield=100 MPa; uts=200 MPa'
    assert leaks(clean, admission) == []
    dirty = clean + ' specimen=A-0001; grade=S235; yield=300 MPa; uts=400 MPa'
    assert leaks(dirty, admission)
