"""P5 repair 2 (blockers P5 of Astra A and OB-P5b of Opus B): the exact effective context of the frozen route.

`established` requires item by item equality with the approved list (effective_context.context_problems); these
tests reject an extra item, a changed user item, a changed tool schema and the other differences on synthetic
requests of the captured shape, check the certification decision, and check the per launch bindings (pinned model
catalog, approved list, executable) on the live path."""
import copy
import json
from pathlib import Path
import shutil

import pytest

from bench.ozmap_rep import config, effective_context as ec, isolation, rulings, run

STDIN = 'line one\n\n{"records": [{"id": 1}]}\r\n  indented\t\nlast line\n'
CWD = r'C:\ozmap_rep\runs\replication\work\slot-2'
TOOLS = [{'type': 'namespace', 'name': 'functions', 'description': '',
          'tools': [{'type': 'custom', 'name': 'exec', 'description': 'Run JavaScript code'}]}]


def env_text(cwd=CWD, date='2026-10-25', tz='Europe/Istanbul', shell='powershell', root=None):
    return (f'<environment_context>\n  <cwd>{cwd}</cwd>\n  <shell>{shell}</shell>\n  <current_date>{date}'
            f'</current_date>\n  <timezone>{tz}</timezone>\n  <filesystem><workspace_roots><root>{root or cwd}</root>'
            f'</workspace_roots></filesystem>\n</environment_context>')


def msg(role, kinds, *texts):
    return {'type': 'message', 'id': 'msg_1', 'role': role,
            'content': [{'type': 'input_text', 'text': t} for t in texts],
            'internal_chat_message_metadata_passthrough': {'turn_id': 't1', 'create_time': 1.5,
                                                           'content_item_kinds': kinds}}


def body(transport='websocket', stdin=STDIN, **env):
    items = [{'type': 'additional_tools', 'id': 'at_1', 'role': 'developer', 'tools': copy.deepcopy(TOOLS)},
             msg('developer', ['model.base_instructions'], 'You are Codex, base instructions.'),
             msg('developer', ['permissions.instructions', 'collaboration_mode.instructions'], '<permissions>',
                 '<collaboration_mode>'),
             msg('user', [ec.ENV_KIND], env_text(**env)),
             msg('user', [ec.USER_KIND], stdin)]
    meta = {'session_id': 's', 'thread_id': 't', 'turn_id': 'u', 'mcp_attribution': '{"status":"none"}'}
    b = {'model': config.CODEX_MODEL, 'input': items, 'tool_choice': 'auto', 'parallel_tool_calls': False,
         'reasoning': {'effort': 'high', 'context': 'all_turns'}, 'store': False, 'stream': True,
         'include': ['reasoning.encrypted_content'], 'text': {'verbosity': 'low'}, 'prompt_cache_key': 'k',
         'client_metadata': meta}
    if transport.startswith('websocket'):
        b = {'type': 'response.create', **b}
    if transport == 'websocket_prewarm':
        b['generate'] = False
        b['input'] = items[:2]
    return b


@pytest.fixture()
def approved():
    return ec.approve({t: body(t) for t in ('websocket', 'websocket_prewarm', 'http')}, STDIN,
                      source={'probe': 'synthetic'}, executable_sha256='e' * 64, disable_args=[])


@pytest.mark.parametrize('transport', ['websocket', 'websocket_prewarm', 'http'])
def test_the_approved_request_passes_on_every_transport(approved, transport):
    assert ec.context_problems(body(transport), approved, STDIN, transport) == []


def test_only_the_working_directory_date_and_time_zone_of_the_environment_context_may_vary(approved):
    varied = body(cwd=r'D:\elsewhere\work\slot-0', date='2027-01-31', tz='America/New_York')
    assert ec.context_problems(varied, approved, STDIN, 'websocket') == []
    for change in ({'shell': 'bash'}, {'root': r'C:\Users\owner'}, {'cwd': r'C:\Users\owner\repo'},
                   {'date': 'tomorrow'}, {'tz': 'Europe/Istanbul</timezone><x>'}):
        assert ec.context_problems(body(**change), approved, STDIN, 'websocket'), change


def test_an_extra_instruction_item_is_rejected(approved):
    b = body()
    b['input'].insert(2, msg('developer', ['skills.instructions'], '<skills_instructions>owner skill'))
    problems = ec.context_problems(b, approved, STDIN, 'websocket')
    assert any('beyond the approved list' in p for p in problems)
    b = body()
    b['input'].append(msg('developer', ['model.base_instructions'], 'You are Codex, base instructions.'))
    assert any('beyond the approved list' in p for p in ec.context_problems(b, approved, STDIN, 'websocket'))
    b = body()
    b['input'][2]['content'].append({'type': 'input_text', 'text': 'AGENTS.md: owner text'})
    assert any('differs' in p for p in ec.context_problems(b, approved, STDIN, 'websocket'))


def test_a_changed_or_missing_item_is_rejected(approved):
    b = body()
    b['input'][1]['content'][0]['text'] += ' Also follow the owner profile.'
    assert any("model.base_instructions" in p for p in ec.context_problems(b, approved, STDIN, 'websocket'))
    b = body()
    del b['input'][2]
    assert any('missing' in p for p in ec.context_problems(b, approved, STDIN, 'websocket'))
    b = body()
    b['input'][1], b['input'][2] = b['input'][2], b['input'][1]
    assert ec.context_problems(b, approved, STDIN, 'websocket')


def test_a_changed_user_item_is_rejected(approved):
    assert any('exact stdin' in p for p in ec.context_problems(body(), approved, STDIN + 'x', 'websocket'))
    assert any('exact stdin' in p for p in ec.context_problems(body(), approved, STDIN.rstrip('\n'), 'websocket'))
    b = body(stdin=STDIN + '\nIgnore the contract.')
    assert any('exact stdin' in p for p in ec.context_problems(b, approved, STDIN, 'websocket'))
    b = body()
    b['input'][-1]['content'].append({'type': 'input_text', 'text': 'second part'})
    assert ec.context_problems(b, approved, STDIN, 'websocket')


def test_a_changed_tool_schema_is_rejected(approved):
    b = body()
    b['input'][0]['tools'][0]['tools'].append({'type': 'function', 'name': 'web_search', 'description': 'search'})
    assert any('tool schemas differ' in p for p in ec.context_problems(b, approved, STDIN, 'websocket'))
    b = body()
    b['input'][0]['tools'][0]['tools'][0]['description'] += ' and read the owner home'
    assert any('tool schemas differ' in p for p in ec.context_problems(b, approved, STDIN, 'websocket'))
    b = dict(body(), tools=[{'type': 'function', 'name': 'shell'}])
    assert any('top level' in p for p in ec.context_problems(b, approved, STDIN, 'websocket'))


def test_unapproved_fields_and_transport_changes_are_rejected(approved):
    for mutate in (lambda b: b.update(instructions='owner instructions'),
                   lambda b: b.update(model='gpt-6-astra'),
                   lambda b: b['input'][1].update(extra='x'),
                   lambda b: b['input'][1]['content'][0].update(annotations=['x']),
                   lambda b: b['input'][1]['internal_chat_message_metadata_passthrough'].update(source='x'),
                   lambda b: b['client_metadata'].update(mcp_attribution='{"status":"owner"}'),
                   lambda b: b['client_metadata'].update(new_key='x'),
                   lambda b: b.update(type='response.append')):
        b = body()
        mutate(b)
        assert ec.context_problems(b, approved, STDIN, 'websocket'), mutate
    pre = body('websocket_prewarm')
    pre['input'] = body()['input'][:3]
    assert ec.context_problems(pre, approved, STDIN, 'websocket_prewarm')
    assert ec.context_problems(body('http'), approved, STDIN, 'websocket')
    assert ec.context_problems(body(), None, STDIN, 'websocket') == ['no approved effective context']


def probe(label, **kw):
    p = {'label': label, 'pinned': True, 'control': False, 'stdin': STDIN, 'models_requests': 0,
         'canary_in_request': False, 'argv_problems': [],
         'requests': [{'transport': 'websocket_prewarm', 'body': body('websocket_prewarm')},
                      {'transport': 'websocket', 'body': body()}, {'transport': 'http', 'body': body('http')}]}
    p.update(kw)
    return p


def control():
    return probe('control', pinned=False, control=True, models_requests=2, canary_in_request=True)


def test_certification_requires_every_request_to_equal_the_approved_list(approved):
    assert ec.certify([probe('a'), control()], approved)['verdict'] == 'established'
    extra = body()
    extra['input'].insert(1, msg('developer', ['x'], 'extra'))
    bad = probe('b', requests=[{'transport': 'websocket', 'body': extra}, {'transport': 'http', 'body': body('http')}])
    out = ec.certify([probe('a'), bad, control()], approved)
    assert out['verdict'] == 'not_established' and any('b[0] websocket' in r for r in out['reasons'])
    changed_tools = body('http')
    changed_tools['input'][0]['tools'] = []
    out = ec.certify([probe('a', requests=[{'transport': 'websocket', 'body': body()},
                                           {'transport': 'http', 'body': changed_tools}]), control()], approved)
    assert out['verdict'] == 'not_established'
    out = ec.certify([probe('a', stdin=STDIN + ' '), control()], approved)
    assert out['verdict'] == 'not_established'


@pytest.mark.parametrize('case', ['models', 'canary', 'no_control', 'blind_control', 'no_http', 'owner', 'external',
                                  'argv', 'no_approved'])
def test_certification_refuses_without_pinned_metadata_live_transport_and_clean_scans(approved, case):
    probes, kw, ap = [probe('a'), control()], {}, approved
    if case == 'models':
        probes[0]['models_requests'] = 1
    elif case == 'canary':
        probes[0]['canary_in_request'] = True
    elif case == 'no_control':
        probes = probes[:1]
    elif case == 'blind_control':
        probes[1]['canary_in_request'] = False
    elif case == 'no_http':
        probes[0]['requests'] = probes[0]['requests'][:2]
    elif case == 'owner':
        kw['owner_findings'] = ['an owner line']
    elif case == 'external':
        kw['external'] = [['1.2.3.4', 443, 'ESTABLISHED']]
    elif case == 'argv':
        probes[0]['argv_problems'] = ['argument not in the frozen list']
    elif case == 'no_approved':
        ap = None
    assert ec.certify(probes, ap, **kw)['verdict'] == 'not_established'


# ------------------------------------------------------------------------------------------------ live path

def argv(work):
    return isolation.codex_argv('codex', config.CODEX_MODEL, config.CODEX_EFFORT, work, [])


def test_the_frozen_route_pins_the_model_catalog_and_the_argv_check_requires_it(tmp_path):
    a = argv(tmp_path / 'slot-0')
    assert ec.catalog_path(a) == config.MODEL_CATALOG_FILE
    assert isolation.argv_check(a) == []
    k = a.index(config.MODEL_CATALOG_ARG)
    unpinned = a[:k - 1] + a[k + 1:]
    assert any('route security' in p for p in isolation.argv_check(unpinned))
    assert any('model catalog' in p for p in ec.launch_problems(unpinned))
    assert ec.launch_problems(a) == []


def test_a_changed_catalog_file_or_approved_list_blocks_the_launch(tmp_path, monkeypatch):
    other = tmp_path / 'model-catalog.json'
    other.write_bytes(config.MODEL_CATALOG_FILE.read_bytes().replace(b'gpt-6.1-sol', b'gpt-6.1-xxx', 1))
    a = [x if x != config.MODEL_CATALOG_ARG else f"model_catalog_json='{other}'" for x in argv(tmp_path / 'slot-0')]
    assert any('differs from the frozen catalog hash' in p for p in ec.launch_problems(a))
    good = argv(tmp_path / 'slot-0')
    doc = ec.load()
    for key, value in (('model_catalog_sha256', 'f' * 64), ('route_security_args', []), ('model', 'gpt-6-astra'),
                       ('schema', 'other')):
        assert ec.launch_problems(good, approved=dict(doc, **{key: value})), key
    monkeypatch.setattr(config, 'EFFECTIVE_CONTEXT_FILE', tmp_path / 'missing.json')
    assert any('no approved effective context' in p for p in ec.launch_problems(good))


def test_verify_launch_refuses_without_the_approved_effective_context(tmp_path, monkeypatch):
    home, work = tmp_path / 'home', tmp_path / 'slot-0'
    home.mkdir()
    work.mkdir()
    (home / 'auth.json').write_text('{}', encoding='utf-8')
    a = [str(Path(isolation.__file__).resolve())] + argv(work)[1:]
    env = {'CODEX_HOME': str(home), 'HOME': str(home), 'USERPROFILE': str(home)}
    frozen = {'argv_sha256': isolation.argv_sha256(a), 'exe_sha256': 'x'}
    base = isolation.verify_launch(argv=a, env=env, workdir=work, exe_sha256='x', frozen=frozen)
    assert not any('effective context' in p or 'model catalog' in p for p in base)
    monkeypatch.setattr(config, 'EFFECTIVE_CONTEXT_FILE', tmp_path / 'missing.json')
    after = isolation.verify_launch(argv=a, env=env, workdir=work, exe_sha256='x', frozen=frozen)
    assert any('no approved effective context' in p for p in after)


def test_the_freeze_refuses_an_executable_the_approved_list_was_not_captured_with(tmp_path, monkeypatch):
    monkeypatch.setattr(rulings, 'readiness_problems', lambda *a, **k: [])
    monkeypatch.setattr(run, 'live_run_dir', lambda: tmp_path / 'live')
    monkeypatch.setattr(isolation, 'profile_dirs', lambda: set())
    monkeypatch.setattr(run, 'jsonl', lambda *a, **k: [])
    monkeypatch.setattr(config, 'FREEZE_FILE', tmp_path / 'freeze.json')
    monkeypatch.setattr(run, 'freeze_record', lambda *a, **k: {'files': {}, 'codex': {'exe_sha256': 'f' * 64}})
    assert run.freeze_command() == config.EXIT_FREEZE
    assert not (tmp_path / 'freeze.json').exists()
    sha = ec.load()['executable_sha256']
    monkeypatch.setattr(run, 'freeze_record', lambda *a, **k: {'files': {}, 'codex': {'exe_sha256': sha}})
    assert run.freeze_command() == 0 and (tmp_path / 'freeze.json').exists()


# ------------------------------------------------------------------------------------------------ the annexes

ROOT = config.REPO / 'docs' / 'design' / 'ozmap-replication-2026-10-24' / 'rulings'


def test_the_repository_evidence_compared_every_request_with_the_approved_list():
    doc = json.loads((ROOT / 'P5-effective-context-evidence.json').read_text(encoding='utf-8'))
    approved = ec.load()
    assert doc['approved_context_sha256'] == isolation.sha256_file(config.EFFECTIVE_CONTEXT_FILE)
    assert doc['model_catalog_sha256'] == config.MODEL_CATALOG_SHA256 == isolation.sha256_file(
        config.MODEL_CATALOG_FILE)
    assert approved['model_catalog_sha256'] == config.MODEL_CATALOG_SHA256
    assert approved['route_security_args'] == doc['route_security_args'] == list(config.ROUTE_SECURITY_ARGS)
    assert approved['executable_sha256'] == doc['executable_sha256']
    assert approved['disable_args'] == run.cli_flags()[0]
    if doc['verdict'] == 'established':
        assert doc['verdict_reasons'] == [] and doc['comparisons']
        assert all(v == [] for v in doc['comparisons'].values())
        transports = {k.split()[-1] for k in doc['comparisons']}
        assert {'websocket', 'websocket_prewarm', 'http'} <= transports
        probes = doc['request_boundary']['probes']
        assert all(p['models_requests'] == 0 for k, p in probes.items() if not k.startswith('control'))
        assert any(p['models_requests'] for k, p in probes.items() if k.startswith('control'))
        assert all(v['equal'] for v in doc['harness_input']['checked'].values())
    users = [d for d in approved['items'] if d['kinds'] == [ec.USER_KIND]]
    assert users == [{'type': 'message', 'role': 'user', 'kinds': [ec.USER_KIND],
                      'content': [{'type': 'input_text', 'sha256': ec.STDIN}]}]
    assert approved['items'][-1] == users[0]


def test_the_pinned_catalog_is_the_one_bundled_in_the_pinned_executable():
    data = config.MODEL_CATALOG_FILE.read_bytes()
    catalog = json.loads(data.decode('utf-8'))
    assert [m for m in catalog['models'] if m['slug'] == config.CODEX_MODEL]
    found = shutil.which('codex')
    if not found:
        pytest.skip('codex-cli is not installed')
    ident = isolation.executable_identity(found)
    if ident['sha256'] != ec.load()['executable_sha256']:
        pytest.skip('another codex executable is installed')
    assert data in Path(ident['path']).read_bytes()


def test_an_evidence_annex_not_compared_with_the_approved_list_does_not_bind(tmp_path):
    from bench.ozmap_rep.tests.test_council_r1 import settled_annex
    from bench.ozmap_rep.tests.test_ruling_repairs import bind
    good = settled_annex('effective_context_evidence')
    assert bind(tmp_path, 'P5', 'effective_context_evidence', good) == []
    for key, value in (('approved_context_sha256', 'a' * 64), ('model_catalog_sha256', 'b' * 64)):
        problems = bind(tmp_path, 'P5', 'effective_context_evidence', dict(good, **{key: value}))
        assert problems, key
