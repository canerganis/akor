"""A4.2: the frozen argument list, disable options and the pinned route constants."""
import hashlib

import pytest

from ozrep_helpers import harness, need

FROZEN_HEAD = ['exec', '--ignore-user-config', '--ignore-rules', '--ephemeral', '--skip-git-repo-check', '--json',
               '-s', 'read-only', '-C']


def argv_for(slot=0, disable=()):
    iso, cfg = harness('isolation'), harness('config')
    return iso.codex_argv('codex', cfg.CODEX_MODEL, cfg.CODEX_EFFORT, f'/tmp/run/work/slot-{slot}', disable)


def test_a4_2_route_constants_are_the_pinned_ones():
    cfg = harness('config')
    assert need(cfg, 'CODEX_MODEL') == 'gpt-6.1-sol'
    assert need(cfg, 'CODEX_EFFORT') == 'high'
    assert need(cfg, 'SONNET_MODEL') == 'claude-sonnet-5-5'
    assert need(cfg, 'SLOTS') == 4


def test_a4_2_frozen_arguments_are_exactly_the_specified_list():
    cfg = harness('config')
    assert list(need(cfg, 'FROZEN_ARGS')) == FROZEN_HEAD
    argv = argv_for()
    assert argv[1:1 + len(FROZEN_HEAD)] == FROZEN_HEAD
    assert argv[1 + len(FROZEN_HEAD)].endswith('slot-0')
    assert argv[-1] == '-'


def test_a4_2_canonical_argv_passes_the_check():
    iso = harness('isolation')
    check = need(iso, 'argv_check')
    disable = ['--disable', 'plugins', '--disable', 'memories', '-c', 'project_doc_max_bytes=0']
    assert check(argv_for()) == []
    assert check(argv_for(3, disable)) == []


@pytest.mark.parametrize('mutation', [
    lambda a: a + ['--dangerously-bypass-approvals-and-sandbox'],
    lambda a: [x if x != 'read-only' else 'workspace-write' for x in a],
    lambda a: [x for x in a if x != '--ephemeral'],
    lambda a: [x for x in a if x != '--ignore-user-config'],
    lambda a: [x for x in a if x != '--ignore-rules'],
    lambda a: a[:-1] + ['--full-auto', '-'],
    lambda a: a[:-1] + ['--add-dir', '/home/owner', '-'],
    lambda a: a[:-1] + ['-c', 'sandbox_mode="danger-full-access"', '-'],
    lambda a: a[:-1] + ['-c', 'model_providers.x.base_url="http://evil"', '-'],
    lambda a: [x if not x.endswith('slot-0') else '/home/owner/repo' for x in a],
    lambda a: [x if x != 'gpt-6.1-sol' else 'gpt-6-astra' for x in a],
    lambda a: [x if x != 'model_reasoning_effort="high"' else 'model_reasoning_effort="low"' for x in a],
])
def test_a4_2_unaccepted_arguments_are_rejected(mutation):
    iso = harness('isolation')
    assert need(iso, 'argv_check')(mutation(argv_for())), 'an argument outside the frozen list must be reported'


def test_a4_2_argument_hash_ignores_only_the_working_directory():
    iso = harness('isolation')
    h = need(iso, 'argv_sha256')
    assert h(argv_for(0)) == h(argv_for(1)) == h(argv_for(3))
    assert h(argv_for(0)) != h(argv_for(0, ['--disable', 'plugins']))
    assert len(h(argv_for(0))) == 64


def test_a4_2_disable_options_use_every_supported_feature_and_record_unsupported():
    iso, cfg = harness('isolation'), harness('config')
    plan = need(iso, 'plan_disable_options')
    features = list(need(cfg, 'DISABLE_FEATURES'))
    for name in ('plugins', 'apps', 'memories', 'hooks', 'multi_agent', 'skill_search', 'browser_use',
                 'computer_use', 'image_generation', 'view_image'):
        assert name in features, name
    supported = {'plugins', 'memories', 'hooks', 'view_image', 'project_doc_max_bytes'}
    args, unsupported = plan(supported)
    joined = ' '.join(args)
    for name in ('plugins', 'memories', 'hooks', 'view_image'):
        assert f'--disable {name}' in joined, name
    assert 'project_doc_max_bytes=0' in joined
    for name in ('apps', 'multi_agent', 'skill_search', 'browser_use', 'computer_use', 'image_generation'):
        assert name in unsupported and name not in joined
    # everything the plan produces is accepted by the argument check
    assert iso.argv_check(iso.codex_argv('codex', cfg.CODEX_MODEL, cfg.CODEX_EFFORT, '/tmp/run/work/slot-0',
                                         args)) == []


def test_a4_2_project_doc_option_omitted_when_not_accepted():
    iso = harness('isolation')
    args, unsupported = need(iso, 'plan_disable_options')({'plugins'})
    assert 'project_doc_max_bytes=0' not in ' '.join(args)
    assert 'project_doc_max_bytes' in unsupported
