"""P5 exact effective context (blockers P5 and OB-P5b, fix 3). Standard library only.

The approved effective context (config.EFFECTIVE_CONTEXT_FILE) lists, item by item, the model request the frozen route
sends: the sha256 of every developer item's text, the sha256 of the tool schemas (canonical JSON), the environment
context with only its working directory, date and time zone as placeholders, and the stdin user item as the rule
"exactly the stdin bytes". `context_problems` compares one captured request (HTTP body or WebSocket frame) with that
list; any extra, missing, reordered or changed item, a changed tool schema, a user item that is not the exact stdin, a
changed top level field or an unapproved field is a problem. The only frozen transforms are those of TRANSPORTS (the
WebSocket frame adds `type: response.create`; the prewarm frame also carries `generate: false` and the approved prefix
of PREWARM items) and the per call identifiers of VARIABLE_TOP and VARIABLE_ITEM_KEYS, which carry no model text.

`certify` is the decision the P5 certification generator writes (rulings/evidence/p5-probe/gen_p5.py): `established`
only when every captured request of every probe equals the approved list, no probe fetched /models with the pin, the
unpinned control shows that a /models answer would have reached the request (so the probe would see it), and the
owner content scan and the external request check are clean.

`launch_problems` is the per call check of the live path. The request content itself travels over TLS to the vendor
and is not observable there; what the harness can observe per call is checked: the approved list exists and records
the frozen model, the route arguments and the pinned catalog, and the catalog file the argv names hashes to the pinned
value. The executable binding is checked by the freeze (`executable_problems` on the frozen Codex executable); every
launch then checks the executable against the frozen one.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from . import config

SCHEMA = 'ozmap-rep.effective-context/1'
VARIABLE_TOP = ('prompt_cache_key', 'client_metadata')
# client_metadata carries request identifiers and timestamps (no model text); its key set per transport and the values
# of every other key must equal the approved ones.
VARIABLE_CLIENT_METADATA = ('session_id', 'thread_id', 'turn_id', 'root_turn_id', 'x-codex-installation-id',
                            'x-codex-window-id', 'x-codex-ws-stream-request-start-ms', 'x-codex-turn-metadata')
VARIABLE_ITEM_KEYS = ('id',)
VARIABLE_META_KEYS = ('turn_id', 'create_time')
ITEM_KEYS = ('type', 'id', 'role', 'content', 'tools', 'internal_chat_message_metadata_passthrough')
META = 'internal_chat_message_metadata_passthrough'
TRANSPORTS = {'http': {}, 'websocket': {'type': 'response.create'},
              'websocket_prewarm': {'type': 'response.create', 'generate': False}}
ENV_KIND = 'environments.environment_context'
USER_KIND = 'user.text'
STDIN = '<stdin>'
_SLOT = re.compile(r'(?:.*[\\/])?slot-[0-9]+\Z')
_DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}\Z')
_TZ = re.compile(r'[A-Za-z0-9_+\-/]{1,64}\Z')


def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def kinds(item):
    meta = item.get(META) if isinstance(item.get(META), dict) else {}
    k = meta.get('content_item_kinds')
    return list(k) if isinstance(k, list) else None


def normalize_environment(text):
    """(normalized text, problems): the environment context with its working directory, date and time zone replaced
    by placeholders. The working directory must be a numbered slot directory; every other occurrence of it (the
    workspace root) is replaced too, and nothing else may vary."""
    problems = []
    m = re.search(r'<cwd>([^<>]*)</cwd>', text)
    if not m or not _SLOT.match(m.group(1)):
        problems.append('the environment context names no numbered slot working directory')
        cwd = None
    else:
        cwd = m.group(1)
    out = text.replace(cwd, '{cwd}') if cwd else text
    d = re.search(r'<current_date>([^<>]*)</current_date>', out)
    if d and _DATE.match(d.group(1)):
        out = out.replace(d.group(0), '<current_date>{date}</current_date>')
    elif d:
        problems.append('the environment context date is not a date')
    t = re.search(r'<timezone>([^<>]*)</timezone>', out)
    if t and _TZ.match(t.group(1)):
        out = out.replace(t.group(0), '<timezone>{timezone}</timezone>')
    elif t:
        problems.append('the environment context time zone is not a time zone name')
    return out, problems


def describe_item(item, stdin_text):
    """The approval form of one input item: every field that reaches the model, by sha256."""
    problems = []
    extra = sorted(k for k in item if k not in ITEM_KEYS)
    if extra:
        problems.append(f'unapproved item fields {extra}')
    meta = item.get(META) if isinstance(item.get(META), dict) else {}
    extra_meta = sorted(k for k in meta if k not in VARIABLE_META_KEYS + ('content_item_kinds',))
    if extra_meta:
        problems.append(f'unapproved item metadata {extra_meta}')
    d = {'type': item.get('type'), 'role': item.get('role'), 'kinds': kinds(item)}
    if 'tools' in item:
        d['tools_sha256'] = sha(canonical(item.get('tools')))
    if 'content' in item:
        content = item.get('content') if isinstance(item.get('content'), list) else []
        if not isinstance(item.get('content'), list):
            problems.append('item content is not a list')
        out = []
        for c in content:
            c = c if isinstance(c, dict) else {}
            extra_c = sorted(k for k in c if k not in ('type', 'text'))
            if extra_c:
                problems.append(f'unapproved content fields {extra_c}')
            text = c.get('text') if isinstance(c.get('text'), str) else ''
            if d['kinds'] == [ENV_KIND]:
                text, p = normalize_environment(text)
                problems += p
            if d['kinds'] == [USER_KIND] and stdin_text is not None and text == stdin_text:
                out.append({'type': c.get('type'), 'sha256': STDIN})
            else:
                out.append({'type': c.get('type'), 'sha256': sha(text), 'chars': len(text)})
        d['content'] = out
    return d, problems


def describe(body, stdin_text, transport='http'):
    """(description, problems) of one captured request in the approval form."""
    problems = []
    body = body if isinstance(body, dict) else {}
    fields = TRANSPORTS.get(transport)
    if fields is None:
        return {}, [f'unknown transport {transport!r}']
    for k, v in fields.items():
        if body.get(k) != v:
            problems.append(f'{transport}: field {k} is {body.get(k)!r}, not {v!r}')
    top = {k: v for k, v in body.items() if k not in VARIABLE_TOP and k != 'input' and k not in fields}
    meta = body.get('client_metadata')
    if meta is not None and not isinstance(meta, dict):
        problems.append('client metadata is not an object')
    meta = meta if isinstance(meta, dict) else {}
    items, item_problems = [], []
    for i, it in enumerate(body.get('input') if isinstance(body.get('input'), list) else []):
        d, p = describe_item(it if isinstance(it, dict) else {}, stdin_text)
        items.append(d)
        item_problems += [f'item {i}: {x}' for x in p]
    if not isinstance(body.get('input'), list):
        problems.append('the request has no input list')
    desc = {'top_level': top, 'client_metadata': {'keys': sorted(meta), 'values': {
        k: v for k, v in sorted(meta.items()) if k not in VARIABLE_CLIENT_METADATA}}, 'items': items}
    return desc, problems + item_problems


def approve(requests, stdin_text, *, source, executable_sha256, disable_args):
    """A candidate approved list built from captured requests of one probe, {transport: body} with a `websocket`
    turn frame, a `websocket_prewarm` frame and an `http` body (signatories approve the result by hash). The items
    come from the turn frame; the HTTP body must describe the same items and top level fields, and the prewarm items
    must be a prefix of them."""
    descs = {}
    for transport, body in requests.items():
        desc, problems = describe(body, stdin_text, transport)
        if problems:
            raise ValueError(f'{transport}: {problems}')
        descs[transport] = desc
    turn = descs['websocket']
    users = [d for d in turn['items'] if d['kinds'] == [USER_KIND]]
    if len(users) != 1 or users[0]['content'] != [{'type': 'input_text', 'sha256': STDIN}]:
        raise ValueError('the candidate has no single user item equal to the stdin bytes')
    if descs['http']['items'] != turn['items'] or descs['http']['top_level'] != turn['top_level']:
        raise ValueError('the HTTP body and the WebSocket turn frame differ')
    pre = descs['websocket_prewarm']['items']
    prefix = bool(pre) and pre == turn['items'][:len(pre)] and not any(d['role'] == 'user' for d in pre)
    if not prefix or descs['websocket_prewarm']['top_level'] != turn['top_level']:
        raise ValueError('the prewarm frame is not a developer prefix of the turn frame')
    return {'schema': SCHEMA, 'cli_version': config.CODEX_CLI_VERSION, 'model': config.CODEX_MODEL,
            'executable_sha256': executable_sha256, 'model_catalog_sha256': config.MODEL_CATALOG_SHA256,
            'route_security_args': list(config.ROUTE_SECURITY_ARGS), 'disable_args': list(disable_args),
            'transports': TRANSPORTS, 'variable': {
                'top_level': list(VARIABLE_TOP), 'client_metadata': list(VARIABLE_CLIENT_METADATA),
                'item_keys': list(VARIABLE_ITEM_KEYS), 'item_metadata': list(VARIABLE_META_KEYS),
                'environment_context': 'only the working directory (a numbered slot directory, also named as the '
                                       'workspace root), the date and the time zone',
                'user_item': 'one input_text whose text is exactly the stdin bytes'},
            'prewarm_items': len(pre), 'source': source,
            'top_level': turn['top_level'],
            'client_metadata': {t: d['client_metadata'] for t, d in sorted(descs.items())},
            'items': turn['items']}


def context_problems(body, approved, stdin_text, transport='http') -> list:
    """Every difference between a captured request and the approved list ([] when it is the approved context)."""
    if not isinstance(approved, dict) or approved.get('schema') != SCHEMA or not isinstance(approved.get('items'), list):
        return ['no approved effective context']
    if transport not in (approved.get('transports') or {}) or approved['transports'][transport] != TRANSPORTS[transport]:
        return [f'transport {transport} is not approved']
    desc, problems = describe(body, stdin_text, transport)
    if not desc:
        return problems
    if desc['top_level'] != approved.get('top_level'):
        a, b = approved.get('top_level') or {}, desc['top_level']
        diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k) or (k in a) != (k in b))
        problems.append(f'top level fields differ from the approved list: {diff}')
    if desc['client_metadata'] != (approved.get('client_metadata') or {}).get(transport):
        problems.append('client metadata keys or values differ from the approved list')
    want = approved['items']
    if transport == 'websocket_prewarm':
        want = want[:approved.get('prewarm_items', 0)]
    got = desc['items']
    if len(got) > len(want):
        problems.append(f'{len(got) - len(want)} item(s) beyond the approved list')
    elif len(got) < len(want):
        problems.append(f'{len(want) - len(got)} approved item(s) missing')
    for i, (g, w) in enumerate(zip(got, want)):
        if g == w:
            continue
        what = ('the user item is not the exact stdin' if w.get('kinds') == [USER_KIND] else
                'the tool schemas differ' if 'tools_sha256' in w or 'tools_sha256' in g else
                f'item {w.get("kinds") or w.get("type")} differs')
        problems.append(f'item {i}: {what} from the approved list')
    return problems


def load(path=None):
    try:
        doc = json.loads(Path(path or config.EFFECTIVE_CONTEXT_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def file_sha256(path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def catalog_path(argv):
    """The file the argv's model_catalog_json override names, or None."""
    argv = [str(a) for a in argv or ()]
    for i in range(len(argv) - 1):
        if argv[i] == '-c' and argv[i + 1].startswith('model_catalog_json='):
            value = argv[i + 1].split('=', 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '\'"':
                value = value[1:-1]
            return Path(value)
    return None


def launch_problems(argv, exe_sha256=None, approved=None) -> list:
    """The per call check of the live path (what the harness can observe before a Codex launch)."""
    problems = []
    path = catalog_path(argv)
    if path is None:
        problems.append('the argv does not pin the model catalog (model_catalog_json)')
    elif file_sha256(path) != config.MODEL_CATALOG_SHA256:
        problems.append('the pinned model catalog file is missing or differs from the frozen catalog hash')
    doc = load() if approved is None else approved
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        problems.append('no approved effective context (P5): the request content cannot be compared')
        return problems
    if doc.get('model') != config.CODEX_MODEL or doc.get('cli_version') != config.CODEX_CLI_VERSION:
        problems.append('the approved effective context was captured for another model or CLI version')
    if doc.get('model_catalog_sha256') != config.MODEL_CATALOG_SHA256:
        problems.append('the approved effective context was captured with another model catalog')
    if doc.get('route_security_args') != list(config.ROUTE_SECURITY_ARGS):
        problems.append('the approved effective context was captured with other route security arguments')
    if exe_sha256 is not None:
        problems += executable_problems(exe_sha256, doc)
    return problems


def executable_problems(exe_sha256, approved=None) -> list:
    """The executable binding: the approved effective context was captured with this executable. Checked by the
    freeze (the frozen Codex executable), and per launch the executable is checked against the frozen one
    (isolation.verify_launch), so every live launch runs the executable the approved list was captured with."""
    doc = load() if approved is None else approved
    if not isinstance(doc, dict) or doc.get('schema') != SCHEMA:
        return ['no approved effective context (P5)']
    if doc.get('executable_sha256') != exe_sha256:
        return ['the approved effective context was captured with another executable']
    return []


def certify(probes, approved, owner_findings=(), external=()) -> dict:
    """The P5 verdict from the request boundary probes.

    probes: list of {'label', 'pinned': bool, 'control': bool, 'stdin': str, 'models_requests': int,
    'canary_in_request': bool, 'argv_problems': [...], 'requests': [{'transport', 'body'}]}.
    `established` needs at least one pinned WebSocket and one pinned HTTP probe, every request of every pinned probe
    equal to the approved list, no /models request and no canary on a pinned probe, a control whose request does carry
    the canary, no owner content finding and no external request."""
    reasons, comparisons = [], {}
    pinned = [p for p in probes if p.get('pinned') and not p.get('control')]
    controls = [p for p in probes if p.get('control')]
    transports = {r['transport'] for p in pinned for r in p.get('requests') or ()}
    for need in ('websocket', 'http'):
        if need not in transports:
            reasons.append(f'no pinned probe captured a {need} request')
    if not isinstance(approved, dict) or approved.get('schema') != SCHEMA:
        reasons.append('no approved effective context')
    for p in pinned:
        if p.get('argv_problems'):
            reasons.append(f'{p["label"]}: the probe argv is not the frozen argv: {p["argv_problems"]}')
        if p.get('models_requests'):
            reasons.append(f'{p["label"]}: the CLI requested /models although the catalog is pinned')
        if p.get('canary_in_request'):
            reasons.append(f'{p["label"]}: the /models answer reached the request although the catalog is pinned')
        turns = [r for r in p.get('requests') or () if r['transport'] != 'websocket_prewarm']
        if not turns:
            reasons.append(f'{p["label"]}: no turn request captured')
        for k, r in enumerate(p.get('requests') or ()):
            got = context_problems(r['body'], approved, p.get('stdin'), r['transport'])
            comparisons[f'{p["label"]}[{k}] {r["transport"]}'] = got
            if got:
                reasons.append(f'{p["label"]}[{k}] {r["transport"]}: {got}')
    if not controls:
        reasons.append('no unpinned control probe')
    for p in controls:
        if not p.get('models_requests') or not p.get('canary_in_request'):
            reasons.append(f'{p["label"]}: the unpinned control did not show the /models answer reaching the request, '
                           f'so the probe could not see a metadata change')
    if owner_findings:
        reasons.append(f'owner content in the request: {list(owner_findings)[:5]}')
    if external:
        reasons.append(f'external requests: {list(external)[:5]}')
    return {'verdict': 'not_established' if reasons else 'established', 'reasons': reasons,
            'comparisons': comparisons}
