"""A4.3: tool events and refusal, judged on the `codex exec --json` event stream. Standard library only.

Only the narrow plain CLI notice exception of the pilot telemetry notes is retained: an `item.completed` error item
with exactly {id, type, message} whose message starts with one of codex_cli_adapter.KNOWN_NOTICES. A tool request
intercepted before execution (status declined, no exit code, no output, no result) is a refused call: it counts, its
answers are not accepted, it establishes no external read and does not by itself invalidate efficiency. An execution,
or uncertainty whether one occurred, invalidates efficiency.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

_EXAMPLES = Path(__file__).resolve().parent.parent.parent / 'examples'
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))
import codex_cli_adapter  # noqa: E402  (frozen; KNOWN_NOTICES and notice() are reused, never copied)

TOOL_ITEMS = ('command_execution', 'file_change', 'mcp_tool_call', 'web_search', 'collab_tool_call')
TEXT_ITEMS = ('agent_message', 'reasoning')
TURN_EVENTS = ('thread.started', 'turn.started', 'turn.completed', 'turn.failed')
ITEM_EVENTS = ('item.started', 'item.updated', 'item.completed')
KNOWN_NOTICES = codex_cli_adapter.KNOWN_NOTICES


def _present(item, key):
    """A field counts as evidence of execution only when it carries a value (None and '' are absent)."""
    return key in item and item[key] is not None and item[key] != ''


def _tool_verdict(item):
    if _present(item, 'exit_code') or _present(item, 'aggregated_output') or _present(item, 'result') \
            or item.get('status') == 'completed':
        return 'executed'
    if item.get('status') == 'declined':
        return 'refused'
    return 'uncertain'


def classify_stream(stdout) -> dict:
    notices, requests, executions, uncertain, top_errors = [], [], [], [], []
    tools = {}  # item id -> (item type, last item dict)
    order = []
    for n, line in enumerate((stdout or '').splitlines()):
        if not line.startswith('{'):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            uncertain.append({'line': n, 'reason': 'unparseable JSON event'})
            continue
        if not isinstance(event, dict):
            uncertain.append({'line': n, 'reason': 'event is not an object'})
            continue
        kind = event.get('type')
        if kind in TURN_EVENTS:
            continue
        if kind == 'error':  # a top level transport notice; never tool activity by itself
            top_errors.append(str(event.get('message'))[:300])
            continue
        if kind not in ITEM_EVENTS:
            uncertain.append({'line': n, 'reason': f'unknown event type {kind!r}'})
            continue
        item = event.get('item')
        if not isinstance(item, dict):
            uncertain.append({'line': n, 'reason': 'item event without an item object'})
            continue
        itype = item.get('type')
        if itype in TEXT_ITEMS:
            continue
        if itype == 'error':
            if codex_cli_adapter.notice(event):
                notices.append(item['message'])
            else:
                uncertain.append({'line': n, 'reason': 'error item outside the plain CLI notice exception'})
            continue
        if itype in TOOL_ITEMS:
            key = (itype, str(item.get('id')))
            if key not in tools:
                order.append(key)
            tools[key] = item
            continue
        uncertain.append({'line': n, 'reason': f'unknown item type {itype!r}'})
    for key in order:
        item = tools[key]
        verdict = _tool_verdict(item)
        row = {'item_type': key[0], 'id': key[1], 'status': item.get('status')}
        if verdict == 'executed':
            executions.append(row)
        elif verdict == 'refused':
            requests.append(row)
        else:
            uncertain.append(dict(row, reason='tool item without a decisive final status'))
    if executions:
        verdict = 'executed'
    elif uncertain:
        verdict = 'uncertain'
    elif requests:
        verdict = 'refused'
    else:
        verdict = 'plain'
    return {'verdict': verdict, 'efficiency_invalid': verdict in ('executed', 'uncertain'), 'counts_as_call': True,
            'answers_accepted': verdict == 'plain', 'external_read': verdict == 'executed', 'notices': notices,
            'tool_requests': requests, 'tool_executions': executions, 'uncertain': uncertain,
            'transport_errors': top_errors}


def classify_claude(data) -> dict:
    """The Sonnet equivalent from the Claude result envelope (claude_map_adapter.tool_use): a permission denial alone
    is a refused request; more than one turn or another model is uncertain."""
    import claude_map_adapter
    found = claude_map_adapter.tool_use(data) if isinstance(data, dict) else ['envelope is not an object']
    denials = [f for f in found if f.startswith('permission_denials')]
    other = [f for f in found if not f.startswith('permission_denials')]
    if other:
        verdict = 'uncertain'
    elif denials:
        verdict = 'refused'
    else:
        verdict = 'plain'
    return {'verdict': verdict, 'efficiency_invalid': verdict in ('executed', 'uncertain'), 'counts_as_call': True,
            'answers_accepted': verdict == 'plain', 'external_read': False, 'notices': [],
            'tool_requests': denials, 'tool_executions': [], 'uncertain': other, 'transport_errors': []}
