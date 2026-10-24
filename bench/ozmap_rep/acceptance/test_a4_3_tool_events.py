"""A4.3: tool events and refusal. Plain CLI notices only; a request intercepted before execution is a refused call;
execution or uncertainty invalidates efficiency."""
import json

import pytest

import ozrep_helpers as H
from ozrep_helpers import harness, need

NOTICE = 'Under-development features enabled: unified_exec. Suppress this warning by ...'


def ev(**kw):
    return json.dumps(kw)


def base(*extra):
    lines = [ev(type='thread.started', thread_id='t1'), ev(type='turn.started')]
    lines += list(extra)
    lines += [ev(type='item.completed', item={'id': 'm', 'type': 'agent_message', 'text': '"yes"'}),
              ev(type='turn.completed', usage={'input_tokens': 100, 'cached_input_tokens': 0, 'output_tokens': 5,
                                               'reasoning_output_tokens': 2})]
    return '\n'.join(lines) + '\n'


def classify(stdout):
    return need(harness('events'), 'classify_stream')(stdout)


def tool_item(kind, **fields):
    return {'id': 'c1', 'type': kind, **fields}


def test_a4_3_plain_stream_is_plain():
    out = classify(base())
    assert out['verdict'] == 'plain'
    assert not out['efficiency_invalid'] and out['answers_accepted'] and out['counts_as_call']


def test_a4_3_plain_cli_notice_exception_is_retained():
    out = classify(base(ev(type='item.completed', item={'id': 'n1', 'type': 'error', 'message': NOTICE})))
    assert out['verdict'] == 'plain' and out['notices'] and not out['efficiency_invalid']


@pytest.mark.parametrize('item', [
    {'id': 'n1', 'type': 'error', 'message': NOTICE, 'extra': 'x'},
    {'id': 'n1', 'type': 'error', 'message': 'something the CLI never printed before'},
    {'id': 'n1', 'type': 'error', 'message': {'nested': NOTICE}},
    {'id': 'n1', 'type': 'error'},
])
def test_a4_3_anything_but_the_narrow_notice_is_not_plain(item):
    out = classify(base(ev(type='item.completed', item=item)))
    assert out['verdict'] != 'plain' and out['efficiency_invalid'] and not out['answers_accepted']


def test_a4_3_tool_request_intercepted_before_execution_is_a_refused_call():
    stream = base(ev(type='item.started', item=tool_item('command_execution', command='cat x', status='in_progress')),
                  ev(type='item.completed', item=tool_item('command_execution', command='cat x',
                                                          status='declined')))
    out = classify(stream)
    assert out['verdict'] == 'refused'
    assert out['counts_as_call'] is True
    assert out['answers_accepted'] is False
    assert out['external_read'] is False, 'an intercepted request does not establish an external read'
    assert out['efficiency_invalid'] is False
    assert out['tool_requests'] and not out['tool_executions']


@pytest.mark.parametrize('kind', ['command_execution', 'file_change', 'mcp_tool_call', 'web_search',
                                  'collab_tool_call'])
def test_a4_3_tool_kinds_declined_are_refused(kind):
    stream = base(ev(type='item.completed', item=tool_item(kind, status='declined')))
    assert classify(stream)['verdict'] == 'refused'


@pytest.mark.parametrize('fields', [
    {'status': 'completed', 'exit_code': 0, 'aggregated_output': 'file contents'},
    {'status': 'completed'},
    {'status': 'failed', 'exit_code': 1, 'aggregated_output': 'cat: x: No such file'},
    {'status': 'declined', 'exit_code': 0},
    {'status': 'declined', 'aggregated_output': 'contents'},
    {'result': {'content': 'x'}},
])
def test_a4_3_actual_execution_invalidates_efficiency_even_if_every_answer_is_refused(fields):
    out = classify(base(ev(type='item.completed', item=tool_item('command_execution', **fields))))
    assert out['verdict'] == 'executed'
    assert out['efficiency_invalid'] is True and out['external_read'] is True
    assert out['answers_accepted'] is False
    assert out['tool_executions']


@pytest.mark.parametrize('item', [
    tool_item('command_execution', command='ls', status='in_progress'),
    tool_item('command_execution', command='ls'),
    tool_item('command_execution', command='ls', status='something-new'),
    tool_item('mcp_tool_call', status='in_progress'),
])
def test_a4_3_uncertainty_whether_execution_occurred_invalidates_efficiency(item):
    event = 'item.started' if item.get('status') == 'in_progress' else 'item.completed'
    out = classify(base(ev(type=event, item=item)))
    assert out['verdict'] == 'uncertain'
    assert out['efficiency_invalid'] is True and out['answers_accepted'] is False
    assert out['external_read'] is False, 'uncertainty is not an established read'
    assert out['uncertain']


def test_a4_3_unknown_item_types_are_uncertain_not_plain():
    out = classify(base(ev(type='item.completed', item={'id': 'x', 'type': 'brand_new_item', 'status': 'completed'})))
    assert out['verdict'] != 'plain'


def test_a4_3_executed_wins_over_refused_in_one_stream():
    stream = base(ev(type='item.completed', item=tool_item('command_execution', status='declined')),
                  ev(type='item.completed', item=tool_item('file_change', status='completed', exit_code=0)))
    assert classify(stream)['verdict'] == 'executed'


def test_a4_3_refused_calls_are_never_erased_by_a_rerun(tmp_path):
    budget = harness('budget')
    cfg = harness('config')
    b = need(budget, 'Budget')()
    b.charge('codex', 'materials', 'cold_A', outcome='refused')
    assert b.physical_total('codex') == 1
    b.charge('codex', 'materials', 'cold_A', outcome='ok')  # the rerun is a second call, not a replacement
    assert b.physical_total('codex') == 2
    assert [a['outcome'] for a in b.attempts] == ['refused', 'ok']
    with pytest.raises(AttributeError):
        b.attempts.append({})  # attempts are an immutable tuple
