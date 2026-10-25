"""Generate the P5 annexes from the request boundary probes on the frozen route (repair 2, blockers P5 and OB-P5b).

Probes (boundary.py, every one with the final frozen argv of the harness, which now pins the model catalog with
`-c model_catalog_json=<bench/ozmap_rep/model-catalog.json>`, plus only the localhost base URL overrides):

* ws_no_auth, ws_scrambled_auth: the capture server accepts the WebSocket upgrade (the live transport: the frozen
  model has prefer_websockets) and records every frame; /models would be answered with a canary catalog;
* http_no_auth, http_scrambled_auth: the upgrade is refused, so the CLI falls back to POST /v1/responses;
* ws_multiline_stdin: a multi line stdin with CRLF, a tab, JSON and a trailing newline, to show the user item is the
  exact stdin bytes;
* control_unpinned_scrambled_auth: the same argv without the catalog pin, /models answered with the canary catalog:
  the canary reaches the base instructions and the tool schemas change, so the probe sees a metadata change.

The decision is bench/ozmap_rep/effective_context.certify: `established` only when every captured request (turn and
prewarm, both transports, both auth modes) equals the approved effective context (bench/ozmap_rep/effective-context
.json) item by item, no pinned probe requested /models, the control shows the canary, and the owner content scan and
the external request check are clean. GEN_PROPOSE=1 first writes the candidate approved list from the ws_no_auth turn
frame (the signatories approve it by hash); without it the approved file must exist and is never rewritten.
GEN_REUSE=1 regenerates from the saved captures without probing again. Reads out/frozen.json (the capture of the
route before the skills overrides) as the before evidence and manifest-head.json (the startup manifest of commit
db05882). No model call: the capture server answers the model request with an error."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(r'C:\Users\can02\Projects\akor')
sys.path.insert(0, str(REPO))
from bench.ozmap_rep import config, effective_context, isolation, run  # noqa: E402

PY314 = r'C:\Users\can02\AppData\Local\Programs\Python\Python314\python.exe'
OUT = HERE / 'out'
RULINGS = REPO / 'docs' / 'design' / 'ozmap-replication-2026-10-24' / 'rulings'
MULTILINE = ('HARNESS_INPUT_MARKER_7f3a multi line\n\n{"records": [{"id": 1, "text": "caf\u00e9 \\"q\\""}]}\r\n'
             '  indented line\t\nlast line\n')
PROBES = [  # label, environment
    ('ws_no_auth', {}),
    ('ws_scrambled_auth', {'P5_SCRAMBLED': '1'}),
    ('http_no_auth', {'P5_WS': 'refuse'}),
    ('http_scrambled_auth', {'P5_WS': 'refuse', 'P5_SCRAMBLED': '1'}),
    ('ws_multiline_stdin', {'P5_PROMPT': MULTILINE}),
    ('control_unpinned_scrambled_auth', {'P5_SCRAMBLED': '1', 'P5_UNPIN': '1'}),
]


def sh(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def st(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def probe(label, extra_env):
    env = {k: v for k, v in os.environ.items() if not k.startswith('P5_')}
    env.update(extra_env)
    subprocess.run([sys.executable, str(HERE / 'boundary.py'), str(OUT), label], check=True, env=env, cwd=HERE,
                   timeout=400)
    subprocess.run([PY314, str(HERE / 'decode.py'), str(OUT / f'{label}.json')], check=True, timeout=120)
    return json.loads((OUT / f'{label}.json').read_text(encoding='utf-8'))


def requests_of(rec):
    """Every model request of a probe: each complete WebSocket text message (turn or prewarm) and each POST
    /responses body, in capture order."""
    out = []
    for c in rec['captured']:
        if c.get('websocket') == 'accepted':
            msg = ''
            for f in c.get('ws_frames') or []:
                if f['opcode'] in (0, 1):
                    msg += f['text'] or ''
                    if f['fin']:
                        body = json.loads(msg)
                        out.append({'transport': 'websocket_prewarm' if body.get('generate') is False else 'websocket',
                                    'body': body, 'text': msg})
                        msg = ''
        elif c['method'] == 'POST' and c['path'].split('?')[0].endswith('/responses'):
            out.append({'transport': 'http', 'body': json.loads(c['body']), 'text': c['body']})
    return out


def models_requests(rec):
    return sum(1 for c in rec['captured'] if c['method'] == 'GET' and c['path'].split('?')[0].endswith('/models'))


EXE = isolation.executable_identity(shutil.which('codex'))


def strings_of(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings_of(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings_of(v)


def items_of(body):
    out = []
    for i, it in enumerate(body.get('input') or []):
        meta = it.get('internal_chat_message_metadata_passthrough') or {}
        if it.get('type') == 'additional_tools':
            def walk(tools, prefix=''):
                res = []
                for t in tools:
                    name = prefix + str(t.get('name'))
                    res.append({'name': name, 'type': t.get('type'), 'description_chars': len(t.get('description') or ''),
                                'description_sha256': st(t.get('description') or '')})
                    if t.get('tools'):
                        res += walk(t['tools'], name + '.')
                return res
            out.append({'index': i, 'type': 'additional_tools', 'role': it.get('role'),
                        'tools_sha256': st(effective_context.canonical(it.get('tools'))), 'tools': walk(it['tools'])})
            continue
        content = []
        for c in it.get('content') or []:
            text = c.get('text') or ''
            m = re.match(r'\s*(<[^>\n]{1,60}>)', text)
            content.append({'type': c.get('type'), 'chars': len(text), 'sha256': st(text),
                            'opening_tag': m.group(1) if m else None})
        out.append({'index': i, 'type': it.get('type'), 'role': it.get('role'),
                    'content_item_kinds': meta.get('content_item_kinds'), 'content': content})
    return out


# ------------------------------------------------------------------------------------------- owner content scan
HOME = Path.home()
OWNER_ROOTS = [HOME / '.agents', HOME / '.codex' / 'AGENTS.md', HOME / '.codex' / 'AGENTS.override.md',
               HOME / '.codex' / 'memories', HOME / '.codex' / 'skills', HOME / '.codex' / 'rules',
               HOME / '.codex' / 'prompts', HOME / '.codex' / 'plugins', HOME / '.codex' / 'config.toml',
               HOME / '.claude' / 'CLAUDE.md', HOME / 'AGENTS.md', HOME / 'CLAUDE.md', REPO / 'AGENTS.md',
               REPO / 'CLAUDE.md']
TEXT_SUFFIXES = {'.md', '.txt', '.toml', '.json', '.yaml', '.yml', '.py', '.js', '.ts', '.sh', '.ps1', ''}
VENDOR = {e['path']: e['sha256'] for e in json.loads((HERE / 'manifest-head.json').read_text(encoding='utf-8'))['files']}
SYSTEM = HOME / '.codex' / 'skills' / '.system'


def vendor_file(p):
    """True when an owner file is a byte identical copy of a file the pinned binary writes into an empty CODEX_HOME
    (the previous startup manifest, captured from the pinned CLI in a fresh home)."""
    try:
        rel = 'skills/.system/' + p.relative_to(SYSTEM).as_posix()
    except ValueError:
        return False
    return VENDOR.get(rel) == sh(p)


def owner_lines():
    files, lines = [], {}
    roots_seen = {}
    for root in OWNER_ROOTS:
        paths = [root] if root.is_file() else sorted(p for p in root.rglob('*') if p.is_file()) if root.is_dir() else []
        roots_seen[str(root).replace(str(HOME), '~')] = len(paths)
        for p in paths:
            if p.suffix.lower() not in TEXT_SUFFIXES or p.stat().st_size > 2_000_000:
                continue
            try:
                text = p.read_text(encoding='utf-8')
            except (OSError, UnicodeError):
                continue
            files.append(p)
            rel = str(p).replace(str(HOME), '~')
            for line in text.splitlines():
                line = line.strip()
                if len(line) >= 40:
                    lines.setdefault(line, set()).add(rel)
    return files, lines, roots_seen


def skill_descriptions():
    out = {}
    for root in (HOME / '.agents' / 'skills', HOME / '.codex' / 'skills'):
        for p in root.rglob('SKILL.md') if root.is_dir() else []:
            try:
                text = p.read_text(encoding='utf-8')
            except (OSError, UnicodeError):
                continue
            m = re.search(r'^description:\s*(.+)$', text, re.M)
            name = re.search(r'^name:\s*(.+)$', text, re.M)
            if m:
                out[str(p.parent).replace(str(HOME), '~')] = (name.group(1).strip() if name else p.parent.name,
                                                              m.group(1).strip().strip('"\''))
    return out


MARKERS = ('.agents', '<skills_instructions>', str(HOME), str(HOME).replace('\\', '/'), HOME.name)


def scan(body_text, lines, descs):
    hits = sorted(line for line in lines if line in body_text)
    vendor = {line for line in hits if all(vendor_file(Path(src.replace('~', str(HOME), 1))) for src in lines[line])}
    desc_hits = sorted(k for k, (_, d) in descs.items() if len(d) >= 20 and d[:80] in body_text)
    markers = {m: body_text.count(m) for m in MARKERS + ('skills_instructions', 'memories', 'AGENTS.md')}
    return [h for h in hits if h not in vendor], sorted(vendor), desc_hits, markers


def main():
    old = json.loads((OUT / 'frozen.json').read_text(encoding='utf-8'))
    recs = {}
    for label, extra in PROBES:
        recs[label] = (json.loads((OUT / f'{label}.json').read_text(encoding='utf-8'))
                       if os.environ.get('GEN_REUSE') == '1' else probe(label, extra))
    disable_args = run.cli_flags()[0]
    reqs = {label: requests_of(rec) for label, rec in recs.items()}

    if os.environ.get('GEN_PROPOSE') == '1':
        turn = [r for r in reqs['ws_no_auth'] if r['transport'] == 'websocket']
        pre = [r for r in reqs['ws_no_auth'] if r['transport'] == 'websocket_prewarm']
        http = [r for r in reqs['http_no_auth'] if r['transport'] == 'http']
        assert len(turn) == len(pre) == len(http) == 1, [r['transport'] for r in reqs['ws_no_auth']]
        assert recs['ws_no_auth']['prompt'] == recs['http_no_auth']['prompt']
        source = {'probes': ['ws_no_auth', 'http_no_auth'], 'captured_at': recs['ws_no_auth']['at'],
                  'turn_frame_sha256': st(turn[0]['text']), 'prewarm_frame_sha256': st(pre[0]['text']),
                  'http_body_sha256': st(http[0]['text']),
                  'capture_files_sha256': {k: sh(OUT / f'{k}.json') for k in ('ws_no_auth', 'http_no_auth')}}
        candidate = effective_context.approve(
            {'websocket': turn[0]['body'], 'websocket_prewarm': pre[0]['body'], 'http': http[0]['body']},
            recs['ws_no_auth']['prompt'], source=source, executable_sha256=EXE['sha256'], disable_args=disable_args)
        candidate['about'] = (
            'P5 approved effective context of the frozen route (repair 2, blockers P5 and OB-P5b): every item of the '
            'model request in order, by sha256 of its exact text (developer items, tool schemas as canonical JSON, the '
            'environment context with its working directory, date and time zone as placeholders) and the user item '
            'as the exact stdin bytes. effective_context.context_problems compares a captured request with it; '
            'effective_context.launch_problems checks its bindings before every Codex launch. Built from the '
            'ws_no_auth turn frame of the request boundary probe; it carries the approval only once both signatories '
            'bind the P5 effective context evidence that names its sha256.')
        candidate['item_preview'] = [
            {'index': i, 'kinds': d.get('kinds'), 'type': d.get('type'), 'role': d.get('role'),
             'opening': [(c.get('text') or '')[:100] for c in (it.get('content') or [])]
             if d.get('kinds') != [effective_context.USER_KIND] else ['<stdin>'],
             'tools': [t.get('name') for t in it.get('tools') or []] if 'tools' in it else None}
            for i, (d, it) in enumerate(zip(candidate['items'], turn[0]['body']['input']))]
        Path(config.EFFECTIVE_CONTEXT_FILE).write_bytes(
            (json.dumps(candidate, indent=1, ensure_ascii=False) + '\n').encode('utf-8'))
    approved = effective_context.load()
    approved_sha = sh(config.EFFECTIVE_CONTEXT_FILE)

    files, lines, roots_seen = owner_lines()
    descs = skill_descriptions()
    scans, owner_findings = {}, []
    pinned_labels = [lab for lab, _ in PROBES if not lab.startswith('control')]
    for label in pinned_labels + ['previous_route']:
        rs = reqs[label] if label != 'previous_route' else \
            [{'transport': 'http', 'body': json.loads(c['body'])} for c in old['captured']
             if c['method'] == 'POST' and c['path'].endswith('/responses')]
        text = '\n'.join(s for r in rs for s in strings_of(r['body']))
        hits, vendor_hits, desc_hits, markers = scan(text, lines, descs)
        scans[label] = {'hits': hits, 'vendor_hits': vendor_hits, 'desc_hits': desc_hits, 'markers': markers,
                        'bodies': [r['body'] for r in rs]}
        if label != 'previous_route':
            owner_findings += hits + desc_hits + [m for m in MARKERS if markers.get(m)]
    external = [x for lab in recs for x in recs[lab]['proxied'] + recs[lab]['non_loopback_connections']]

    canary = recs['control_unpinned_scrambled_auth']['canary'].strip()
    probes = []
    for label, _ in PROBES:
        rec = recs[label]
        probes.append({'label': label, 'pinned': not rec['unpinned'], 'control': label.startswith('control'),
                       'stdin': rec['prompt'], 'models_requests': models_requests(rec),
                       'canary_in_request': any(canary in r['text'] for r in reqs[label]),
                       'argv_problems': rec['frozen_argv_check_before_probe_args'], 'requests': reqs[label]})
    decision = effective_context.certify(probes, approved, owner_findings=owner_findings, external=external)
    established = decision['verdict'] == 'established'
    control = next(p for p in probes if p['control'])
    control_problems = [effective_context.context_problems(r['body'], approved, control['stdin'], r['transport'])
                        for r in control['requests']]

    def boundary_block(label):
        rec = recs[label]
        return {
            'argv': rec['argv'], 'probe_args_added': rec['probe_args'], 'unpinned': rec['unpinned'],
            'ws_mode': rec['ws_mode'], 'models_mode': rec['models_mode'],
            'frozen_argv_check': rec['frozen_argv_check_before_probe_args'],
            'exit_code': rec['exit_code'], 'elapsed_s': rec['elapsed_s'],
            'stdin_sha256': st(rec['prompt']), 'stdin_chars': len(rec['prompt']),
            'requests': [{'method': c['method'], 'path': c['path'], 'body_bytes': len(c.get('body_b64') or '') * 3 // 4,
                          'bearer_source': c.get('bearer_source'),
                          'websocket': c.get('websocket') or ('refused' if {k.lower(): v for k, v in
                                                                              c['headers'].items()}.get('upgrade')
                                                              == 'websocket' else None),
                          'ws_frames': [{'opcode': f['opcode'], 'bytes': f['bytes']} for f in c.get('ws_frames') or []],
                          'models_answer': c.get('models_answer')}
                         for c in rec['captured']],
            'models_requests': models_requests(rec),
            'model_requests': [{'transport': r['transport'], 'sha256': st(r['text']), 'chars': len(r['text']),
                                'top_level_keys': sorted(r['body']), 'model': r['body'].get('model'),
                                'reasoning': r['body'].get('reasoning'),
                                'instructions_field_chars': len(r['body'].get('instructions') or ''),
                                'tools_field': r['body'].get('tools'), 'items': items_of(r['body'])}
                               for r in reqs[label]],
            'external_requests': rec['proxied'], 'non_loopback_connections': rec['non_loopback_connections'],
            'home_after': [e['path'] for e in rec['home_after']],
            'capture_file_sha256': sh(OUT / f"{rec['label']}.json"),
        }

    doc = {
        'about': 'P5 effective context evidence (annex effective_context_evidence), regenerated 2026-10-25 for repair 2 '
                 '(blockers P5 of Astra A and OB-P5b of Opus B): request boundary probes of the frozen exec argv of the '
                 'harness (isolation.codex_argv with config.ROUTE_SECURITY_ARGS, which now pins the model catalog, and '
                 'the disable options of cli-flags.json) in fresh worker homes built by the harness isolation code, '
                 'with only `-c openai_base_url=<localhost capture server>` added (and `-c chatgpt_base_url=<same '
                 'server>` for the scrambled auth variants). The capture server accepts the WebSocket upgrade and '
                 'records every frame (the live transport), or refuses it so the CLI posts over HTTP; it answers every '
                 'model request with an error, so no model is called, and it answers /models with a canary catalog. '
                 'Every other connection is routed to a localhost proxy that refuses it, and the process tree TCP '
                 'connections are polled. Text is recorded by length and sha256; the full captures stay outside the '
                 'repository (capture_file_sha256).',
        'verdict': decision['verdict'],
        'verdict_rule': 'effective_context.certify: established only if every captured model request of every pinned '
                        'probe (WebSocket turn and prewarm frames and HTTP bodies, no auth and scrambled ChatGPT auth, '
                        'one and multi line stdin) equals the approved effective context item by item '
                        '(effective_context.context_problems is empty), no pinned probe requested /models or carried '
                        'the canary, the unpinned control did carry it, the owner content scan found nothing and no '
                        'request left the loopback interface',
        'verdict_reasons': decision['reasons'],
        'comparisons': decision['comparisons'],
        'approved_context': {'path': 'bench/ozmap_rep/effective-context.json', 'sha256': approved_sha},
        'approved_context_sha256': approved_sha,
        'model_catalog': {'path': 'bench/ozmap_rep/model-catalog.json', 'sha256': sh(config.MODEL_CATALOG_FILE),
                          'origin': 'the model catalog bundled in the pinned executable, byte for byte (a JSON object '
                                    'starting `{` `"models": [`, found once in codex.exe; sha256 of the executable '
                                    'below)'},
        'model_catalog_sha256': sh(config.MODEL_CATALOG_FILE),
        'captured_at': recs['ws_no_auth']['at'],
        'cli_version': config.CODEX_CLI_VERSION,
        'executable_sha256': EXE['sha256'],
        'route_security_args': list(config.ROUTE_SECURITY_ARGS),
        'disable_args': disable_args,
        'closes': {
            'OB-P5b-1 (model metadata)': (
                'pinned by `-c model_catalog_json=<bench/ozmap_rep/model-catalog.json>`: no pinned probe requested '
                f'/models ({sum(p["models_requests"] for p in probes if not p["control"])} requests), while the '
                f'unpinned control requested it {control["models_requests"]} times and its request carried the canary '
                f'({control["canary_in_request"]}); the control differs from the approved list in '
                f'{sorted({x for ps in control_problems for x in ps})}'),
            'OB-P5b-2 (live transport)': (
                'the capture server accepted the WebSocket upgrade; the CLI sent a prewarm frame (generate false, the '
                'approved prefix of tools and base instructions) and a turn frame on a second connection; the turn '
                'frame equals the HTTP fallback body item by item, with `type: response.create` as the only transport '
                'field (effective_context.TRANSPORTS)'),
            'OB-P5b-3 and P5 (decision)': (
                'the verdict is effective_context.certify (item by item equality with the approved list); '
                'harness_input below is checked, not described'),
            'P5-E1': 'owner ~/.agents/skills listed in the request on the previous route (previous_route); closed by '
                     '`-c skills.include_instructions=false` (repair 1)',
            'P5-E2': 'bundled CODEX_HOME skills/.system: closed by `-c skills.bundled.enabled=false` (repair 1)',
            'P5-E3': 'multi_agent role and mode developer items, the collaboration tools and the exec tool stay in the '
                     'request although multi_agent, multi_agent_v2 and code_mode_host are disabled: vendor content of '
                     'the pinned binary, now pinned by the item hashes of the approved list (Opus B accepts them on '
                     'that condition, signoff-opus-2.md); a model call to any of those tools stays an A4.3 event',
        },
        'request_boundary': {
            'external_requests': external,
            'proxy_honoured': 'control of repair 1: with the plugins feature enabled the same probe sends CONNECT '
                              'chatgpt.com:443, github.com:443 and api.github.com:443 to the refusing proxy, so the CLI '
                              'honours the proxy variables and a request outside loopback would have been recorded',
            'probes': {label: boundary_block(label) for label, _ in PROBES},
            'previous_route': {'capture_file_sha256': sh(OUT / 'frozen.json'),
                               'line_hits': len(scans['previous_route']['hits']),
                               'skill_description_hits': len(scans['previous_route']['desc_hits'])},
        },
        'provider_block_analysis': {
            'change': '`-c openai_base_url` only replaces the base URL of the built in provider `openai`; '
                      'model_provider stays openai and no provider block is added',
            'differential': 'the no auth and the scrambled ChatGPT auth probes, over both transports, produce the '
                            'approved items; only the environment context working directory differs (comparisons)',
            'residual': 'none for model metadata: the catalog is pinned and the CLI sends no /models request. The '
                        'request content on the live route travels over TLS to the vendor and is not observable by '
                        'the harness; effective_context.launch_problems checks per call what determines it (the '
                        'executable, the argv with the catalog pin, the catalog bytes, the approved list), and an '
                        'empty home and working directory are checked by isolation.verify_launch as before',
        },
        'owner_content_scan': {
            'method': 'every distinct stripped line of at least 40 characters of every text file (<= 2 MB) under the '
                      'owner instruction roots, and every owner SKILL.md description, searched as substrings of all '
                      'string values of every captured model request of the pinned probes; owner files are read, '
                      'never changed',
            'roots_files': roots_seen,
            'files_read': len(files),
            'lines_checked': len(lines),
            'skill_descriptions_checked': len(descs),
            'hits': sorted({h for lab in pinned_labels for h in scans[lab]['hits']})[:50],
            'vendor_copy_overlap': {
                'rule': 'a matching line is not owner content when every owner file that holds it is a byte identical '
                        'copy of a file the pinned binary writes into an empty CODEX_HOME (~/.codex/skills/.system, '
                        'checked by sha256 against the startup manifest of commit db05882)',
                'lines': len({h for lab in pinned_labels for h in scans[lab]['vendor_hits']}),
                'sources': sorted({src for lab in pinned_labels for line in scans[lab]['vendor_hits']
                                   for src in lines[line]}),
            },
            'skill_description_hits': sorted({h for lab in pinned_labels for h in scans[lab]['desc_hits']}),
            'owner_path_markers': {m: sum(scans[lab]['markers'].get(m, 0) for lab in pinned_labels) for m in MARKERS},
        },
        'vendor_items_disclosed': [
            'model.base_instructions developer item (the base instructions travel as the first developer message; the '
            'request instructions field is absent)',
            'permissions.instructions and collaboration_mode.instructions developer item',
            'multi_agent.role_instructions and multi_agent.mode_instructions developer items',
            'additional_tools developer item: namespace functions (exec, wait, request_user_input, '
            'request_user_input_async) and namespace collaboration (followup_task, interrupt_agent, list_agents, '
            'send_message, spawn_agent, wait_agent). The top level tools field is absent',
            'environments.environment_context user item (working directory, shell, date, time zone, read only '
            'filesystem profile)',
        ],
        'harness_input': {
            'rule': 'the prompt arrives as one user item whose single input_text is exactly the stdin bytes '
                    '(effective_context.USER_KIND, compared byte for byte by context_problems)',
            'checked': {label: {'stdin_sha256': st(recs[label]['prompt']), 'equal': not any(
                'stdin' in x for k, v in decision['comparisons'].items() if k.startswith(label + '[') for x in v)}
                for label in pinned_labels},
        },
        'probe_scripts': {name: sh(HERE / name) for name in ('boundary.py', 'decode.py', 'gen_p5.py')},
        'probe_scripts_location': 'docs/design/ozmap-replication-2026-10-24/rulings/evidence/p5-probe/ (run from a '
                                  'scratch copy: they write their captures next to themselves)',
    }
    (RULINGS / 'P5-effective-context-evidence.json').write_bytes(
        (json.dumps(doc, indent=1, ensure_ascii=False) + '\n').encode('utf-8'))

    # ------------------------------------------------------------------------------------------ startup manifest
    inventories = {f'exec_{label}': recs[label]['home_after'] for label in pinned_labels}
    instruction = sorted({e['path'] for inv in inventories.values() for e in inv
                          if e['type'] == 'file' and isolation._matches(e['path'], config.INSTRUCTION_BEARING)})
    old_manifest = json.loads((HERE / 'manifest-head.json').read_text(encoding='utf-8'))
    manifest = {
        'about': old_manifest['about'],
        'cli_version': config.CODEX_CLI_VERSION,
        'executable_sha256': EXE['sha256'],
        'capture': {
            'captured_at': recs['ws_no_auth']['at'],
            'method': 'regenerated 2026-10-25 (P5 repair 2) from the request boundary probes of the frozen exec argv, '
                      'which now pins the model catalog: inventory of the worker home after each pinned probe; the '
                      'route carries skills.bundled.enabled=false, so the pinned CLI writes no skills/.system file',
            'route_security_args': list(config.ROUTE_SECURITY_ARGS),
            'disable_args': disable_args,
            'inventories': {k: [{kk: e.get(kk) for kk in ('path', 'type', 'bytes', 'sha256') if kk in e} for e in v
                                if e['path'] != 'auth.json']
                            for k, v in inventories.items()},
            'instruction_bearing_files_written': instruction,
            'previous_manifest_sha256': sh(HERE / 'manifest-head.json'),
        },
        'files': [],
        'mutable_runtime_artifacts': old_manifest['mutable_runtime_artifacts'],
    }
    assert not instruction, instruction
    Path(config.STARTUP_MANIFEST_FILE).write_bytes(
        (json.dumps(manifest, indent=1, ensure_ascii=False) + '\n').encode('utf-8'))
    print('verdict', doc['verdict'], 'reasons', decision['reasons'][:5], 'external', external,
          'models', {p['label']: p['models_requests'] for p in probes},
          'canary', {p['label']: p['canary_in_request'] for p in probes}, 'lines', len(lines), 'files', len(files))
    return doc


main()
