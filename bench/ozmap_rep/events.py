"""A4.3: tool events and refusal, judged on the `codex exec --json` event stream. Standard library only.

Only the narrow plain CLI notice exception of the pilot telemetry notes is retained: an `item.completed` error item
with exactly {id, type, message} whose message starts with one of codex_cli_adapter.KNOWN_NOTICES. A tool request
intercepted before execution (status declined, no exit code, no output, no result) is a refused call: it counts, its
answers are not accepted, it establishes no external read and does not by itself invalidate efficiency. An execution,
or uncertainty whether one occurred, invalidates efficiency.

Council round 1 (items 11, RT1.3, B1): tool items are aggregated over every event they appear in, so execution
evidence is never erased by a later event; a tool event without a usable item id is its own item and at least
uncertain; a top level `error` event is uncertain unless a signed ruling names it (config.SIGNED_TRANSPORT_NOTICES,
empty until one is signed); a non empty stdout line that is not a JSON event is uncertain.

Council round 2: more than one `turn.started` or `turn.completed` in one exec stream is uncertain (RT2.4); signed
transport notices match the complete message only, and only in a stream without any tool item (P1); a signed CLI
notice (P4) is an `item.completed` error item matching the approved outer schema, item schema, identifier syntax and
complete message exactly, inactive until both signatories approve the annex (config.SIGNED_CLI_NOTICES).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

_EXAMPLES = Path(__file__).resolve().parent.parent.parent / 'examples'
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))
import codex_cli_adapter  # noqa: E402  (frozen; KNOWN_NOTICES and notice() are reused, never copied)

from . import config  # noqa: E402

TOOL_ITEMS = ('command_execution', 'file_change', 'mcp_tool_call', 'web_search', 'collab_tool_call')
TEXT_ITEMS = ('agent_message', 'reasoning')
TURN_EVENTS = ('thread.started', 'turn.started', 'turn.completed', 'turn.failed')
ITEM_EVENTS = ('item.started', 'item.updated', 'item.completed')
KNOWN_NOTICES = codex_cli_adapter.KNOWN_NOTICES


def _present(item, key):
    """A field counts as evidence of execution only when it carries a value (None and '' are absent)."""
    return key in item and item[key] is not None and item[key] != ''


def _executed(item):
    return (_present(item, 'exit_code') or _present(item, 'aggregated_output') or _present(item, 'result')
            or item.get('status') == 'completed')


def _tool_verdict(item):
    """The verdict of a single item snapshot (kept for callers that judge one event)."""
    if _executed(item):
        return 'executed'
    if item.get('status') == 'declined':
        return 'refused'
    return 'uncertain'


def _aggregate(snapshots):
    """(verdict, notes) of one tool item over every event it appeared in. Execution evidence in any event is sticky.
    A status that moves away from execution already shown adds an uncertainty note. Without execution evidence the
    item is refused only when its last event is a decline; anything else is uncertain."""
    notes = []
    if any(_executed(it) for it in snapshots):
        seen = False
        for it in snapshots:
            if _executed(it):
                seen = True
            elif seen:
                notes.append('status went back after execution evidence')
                break
        return 'executed', notes
    if snapshots[-1].get('status') == 'declined':
        return 'refused', notes
    return 'uncertain', notes


def _id_of(item):
    value = item.get('id')
    if isinstance(value, bool) or not isinstance(value, (str, int)) or value == '':
        return None
    return str(value)


def _signed_transport(message):
    """P1: a complete signed transport message, matched exactly (no prefix, no variable part)."""
    notices = tuple(config.SIGNED_TRANSPORT_NOTICES)
    return bool(notices) and isinstance(message, str) and message in notices


def signed_cli_notice(event):
    """P4: an `item.completed` event whose keys are exactly the approved outer schema, with an error item of exactly
    {id, type, message}, an identifier matching the approved syntax and a message equal to a signed notice. Always
    False until config.SIGNED_CLI_NOTICES, SIGNED_CLI_NOTICE_EVENT_KEYS and SIGNED_CLI_NOTICE_ID_RE are all set."""
    import re
    notices = tuple(config.SIGNED_CLI_NOTICES)
    keys, id_re = config.SIGNED_CLI_NOTICE_EVENT_KEYS, config.SIGNED_CLI_NOTICE_ID_RE
    if not notices or not keys or not id_re or not isinstance(event, dict):
        return False
    item = event.get('item')
    return (event.get('type') == 'item.completed' and set(event) == set(keys) and isinstance(item, dict)
            and set(item) == {'id', 'type', 'message'} and item.get('type') == 'error'
            and isinstance(item.get('id'), str) and re.fullmatch(id_re, item['id']) is not None
            and isinstance(item.get('message'), str) and item['message'] in notices)


def _transport_item(event):
    """B1 part (b): an item.completed error item with exactly {id, type, message} whose message starts with a signed
    transport notice. Always False while config.SIGNED_TRANSPORT_NOTICES is empty."""
    item = event.get('item') if isinstance(event, dict) else None
    return (event.get('type') == 'item.completed' and isinstance(item, dict)
            and set(item) == {'id', 'type', 'message'} and item.get('type') == 'error'
            and _signed_transport(item.get('message')))


def classify_stream(stdout) -> dict:
    notices, requests, executions, uncertain, top_errors, transport = [], [], [], [], [], []
    tools, types_by_id, order = {}, {}, []
    anonymous = 0
    turns = {'turn.started': 0, 'turn.completed': 0}
    transport_lines = []
    for n, line in enumerate((stdout or '').splitlines()):
        if not line.strip():
            continue
        if not line.startswith('{'):
            uncertain.append({'line': n, 'reason': 'stdout line that is not a JSON event'})
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
            if kind in turns:
                turns[kind] += 1
            continue
        if kind == 'error':
            message = event.get('message')
            top_errors.append(str(message)[:300])
            if set(event) == {'type', 'message'} and _signed_transport(message):
                transport.append(message[:300])
                transport_lines.append(n)
            else:
                uncertain.append({'line': n, 'reason': 'top level error event outside any signed exception'})
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
            elif signed_cli_notice(event):
                notices.append(item['message'])
            elif _transport_item(event):
                transport.append(item['message'][:300])
                transport_lines.append(n)
            else:
                uncertain.append({'line': n, 'reason': 'error item outside the plain CLI notice exception'})
            continue
        if itype in TOOL_ITEMS:
            iid = _id_of(item)
            if iid is None:
                anonymous += 1
                key = (itype, f'<no id {anonymous}>')
                uncertain.append({'line': n, 'item_type': itype, 'reason': 'tool event without a usable item id'})
            else:
                key = (itype, iid)
                first = types_by_id.setdefault(iid, itype)
                if first != itype:
                    uncertain.append({'line': n, 'id': iid, 'reason': f'item id seen as {first} and as {itype}'})
            if key not in tools:
                order.append(key)
                tools[key] = []
            tools[key].append(item)
            continue
        uncertain.append({'line': n, 'reason': f'unknown item type {itype!r}'})
    for key in order:
        seq = tools[key]
        verdict, notes = _aggregate(seq)
        row = {'item_type': key[0], 'id': key[1], 'status': seq[-1].get('status'), 'events': len(seq)}
        if verdict == 'executed':
            executions.append(row)
            uncertain.extend(dict(row, reason=note) for note in notes)
        elif verdict == 'refused':
            requests.append(row)
        else:
            uncertain.append(dict(row, reason='tool item without a decisive final status'))
    for kind, count in sorted(turns.items()):
        if count > 1:
            uncertain.append({'reason': f'more than one {kind} in one exec stream ({count})'})
    if transport_lines and order:
        uncertain.extend({'line': n, 'reason': 'transport notice in a stream that holds a tool item (P1)'}
                         for n in transport_lines)
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
            'transport_errors': top_errors, 'transport_notices': transport, 'turns': turns}


def turn_usages(stdout) -> list:
    """The usage object of every turn.completed event of a stream, in order (RT2.4)."""
    out = []
    for line in (stdout or '').splitlines():
        if not line.startswith('{'):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get('type') == 'turn.completed':
            out.append(event.get('usage'))
    return out


def error_messages(stdout) -> list:
    """Every text on the error channels of a stream (turn.failed, top level error events, error items), for the
    authentication check that runs independently of the event verdict. Agent message text is never included."""
    out = []
    for line in (stdout or '').splitlines():
        if not line.startswith('{'):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get('type')
        if kind == 'error':
            out.append(str(event.get('message')))
        elif kind == 'turn.failed':
            err = event.get('error')
            out.append(str(err.get('message') if isinstance(err, dict) else err))
        elif kind in ITEM_EVENTS and isinstance(event.get('item'), dict) and event['item'].get('type') == 'error':
            out.append(str(event['item'].get('message')))
    return out


def turn_completed(stdout) -> bool:
    """True when the stream holds a turn.completed event (the model's reply was delivered and the turn ended)."""
    for line in (stdout or '').splitlines():
        if line.startswith('{'):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get('type') == 'turn.completed':
                return True
    return False


def classify_claude(data) -> dict:
    """The Sonnet equivalent from the Claude result envelope (claude_map_adapter.tool_use): a permission denial alone
    is a refused request; more than one turn or another model is uncertain."""
    import claude_map_adapter
    found = claude_map_adapter.tool_use(data) if isinstance(data, dict) else ['envelope is not an object']
    # Astra council round 3, item 23: the harness checks the route itself, independent of the adapter's OZ_MODEL
    # environment variable: one completed turn, a permission denial list and usage of the frozen Sonnet model only.
    # Missing or malformed lifecycle evidence never qualifies as a plain call.
    if isinstance(data, dict):
        if type(data.get('num_turns')) is not int or data.get('num_turns') != 1:
            found.append(f"num_turns missing or not 1 ({data.get('num_turns')!r})")
        if not isinstance(data.get('permission_denials'), list):
            found.append('no permission denial list in the envelope')
        models = data.get('modelUsage')
        if not isinstance(models, dict) or not models:
            found.append('modelUsage missing or empty')
        else:
            found += [f'model other than the frozen Sonnet model: {name}' for name in sorted(models)
                      if not str(name).startswith(config.SONNET_MODEL)]
        found = list(dict.fromkeys(found))
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
            'tool_requests': denials, 'tool_executions': [], 'uncertain': other, 'transport_errors': [],
            'transport_notices': [], 'turns': {}}
