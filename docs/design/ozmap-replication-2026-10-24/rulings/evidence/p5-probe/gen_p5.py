"""Generate the P5 annexes from the request boundary probe on the frozen route.

Runs (1) the no auth exec probe with the final frozen argv (config.ROUTE_SECURITY_ARGS now carries the two skills
overrides) and only `-c openai_base_url=<localhost capture server>` added, (2) the same with an auth.json holding the
baseline account metadata and scrambled tokens (ChatGPT auth mode, chatgpt_base_url also pointed at localhost).
Reads the earlier capture of the previous route (out/frozen.json, captured with boundary.py before the skills
overrides entered config.ROUTE_SECURITY_ARGS) as the before evidence. Writes
docs/.../rulings/P5-effective-context-evidence.json and bench/ozmap_rep/startup-manifest.json. Text is recorded by
length and sha256; the full captures stay in the scratch directory the scripts run from (their sha256 is recorded).
Needs manifest-head.json (the startup manifest of commit db05882) next to it. No model call: the capture server
answers the model request with HTTP 400. GEN_REUSE=1 regenerates from the saved captures without probing again."""
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
from bench.ozmap_rep import config, isolation, run  # noqa: E402

PY314 = r'C:\Users\can02\AppData\Local\Programs\Python\Python314\python.exe'
OUT = HERE / 'out'
RULINGS = REPO / 'docs' / 'design' / 'ozmap-replication-2026-10-24' / 'rulings'


def sh(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def st(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def probe(label, scrambled=False):
    env = dict(os.environ)
    env.pop('P5_MODEL_OVERRIDE', None)
    env.pop('P5_ENABLE', None)
    if scrambled:
        env['P5_SCRAMBLED'] = '1'
    else:
        env.pop('P5_SCRAMBLED', None)
    subprocess.run([sys.executable, str(HERE / 'boundary.py'), str(OUT), label], check=True, env=env, cwd=HERE,
                   timeout=400)
    subprocess.run([PY314, str(HERE / 'decode.py'), str(OUT / f'{label}.json')], check=True, timeout=120)
    return json.loads((OUT / f'{label}.json').read_text(encoding='utf-8'))


def model_request(rec):
    posts = [c for c in rec['captured'] if c['method'] == 'POST' and c['path'].endswith('/responses')]
    assert len(posts) == 1, [c['path'] for c in rec['captured']]
    return posts[0], json.loads(posts[0]['body'])


EXE = isolation.executable_identity(shutil.which('codex'))
EXE_PATH = None
for f in isolation.identity_files(EXE):
    if str(f).lower().endswith('codex.exe'):
        EXE_PATH = Path(f)
EXE_BYTES = EXE_PATH.read_bytes() if EXE_PATH else b''


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
                        'tools_sha256': st(json.dumps(it.get('tools'), sort_keys=True)), 'tools': walk(it['tools'])})
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


def scan(body_text, files, lines, descs):
    hits = sorted(line for line in lines if line in body_text)
    vendor = {line for line in hits if all(vendor_file(Path(src.replace('~', str(HOME), 1))) for src in lines[line])}
    return [h for h in hits if h not in vendor], sorted(vendor), *_scan_rest(body_text, descs)


def _scan_rest(body_text, descs):
    desc_hits = sorted(k for k, (_, d) in descs.items() if len(d) >= 20 and d[:80] in body_text)
    markers = {m: body_text.count(m) for m in ('.agents', 'skills_instructions', str(HOME), str(HOME).replace('\\', '/'),
                                               HOME.name, '<skills_instructions>', 'memories', 'AGENTS.md')}
    return desc_hits, markers


def main():
    old = json.loads((OUT / 'frozen.json').read_text(encoding='utf-8'))
    if os.environ.get('GEN_REUSE') == '1':
        noauth = json.loads((OUT / 'final_noauth.json').read_text(encoding='utf-8'))
        scr = json.loads((OUT / 'final_scrambled.json').read_text(encoding='utf-8'))
    else:
        noauth = probe('final_noauth')
        scr = probe('final_scrambled', scrambled=True)
    files, lines, roots_seen = owner_lines()
    descs = skill_descriptions()
    results = {}
    for label, rec in (('previous_route', old), ('frozen_route_no_auth', noauth),
                       ('frozen_route_scrambled_auth', scr)):
        post, body = model_request(rec)
        body_text = '\n'.join(strings_of(body))
        hits, vendor_hits, desc_hits, markers = scan(body_text, files, lines, descs)
        results[label] = {'post': post, 'body': body, 'hits': hits, 'desc_hits': desc_hits, 'markers': markers,
                          'vendor_hits': vendor_hits,
                          'rec': rec}
    disable_args = run.cli_flags()[0]

    def boundary_block(label):
        r = results[label]
        rec = r['rec']
        return {
            'argv': rec['argv'], 'probe_args_added': rec['probe_args'],
            'frozen_argv_check': rec['frozen_argv_check_before_probe_args'],
            'exit_code': rec['exit_code'], 'elapsed_s': rec['elapsed_s'],
            'requests': [{'method': c['method'], 'path': c['path'], 'body_bytes': len(c.get('body_b64') or '') * 3 // 4,
                          'bearer_source': c.get('bearer_source'),
                          'websocket_upgrade': {k.lower(): v for k, v in c['headers'].items()}.get('upgrade') == 'websocket'}
                         for c in rec['captured']],
            'external_requests': rec['proxied'], 'non_loopback_connections': rec['non_loopback_connections'],
            'model_request': {'path': r['post']['path'], 'body_sha256': st(r['post']['body']),
                              'body_chars': len(r['post']['body']), 'top_level_keys': sorted(r['body']),
                              'model': r['body'].get('model'), 'reasoning': r['body'].get('reasoning'),
                              'instructions_field_chars': len(r['body'].get('instructions') or ''),
                              'tools_field': r['body'].get('tools'),
                              'items': items_of(r['body'])},
            'owner_content': {'line_hits': len(r['hits']), 'skill_description_hits': r['desc_hits'],
                              'markers': r['markers']},
            'home_after': [e['path'] for e in rec['home_after']],
            'capture_file_sha256': sh(OUT / f"{rec['label']}.json"),
        }

    blocks = {k: boundary_block(k) for k in results}
    final_hits = results['frozen_route_no_auth']['hits'] + results['frozen_route_scrambled_auth']['hits']
    final_desc = (results['frozen_route_no_auth']['desc_hits'] + results['frozen_route_scrambled_auth']['desc_hits'])
    owner_markers_final = {k: v for lab in ('frozen_route_no_auth', 'frozen_route_scrambled_auth')
                           for k, v in results[lab]['markers'].items()
                           if k in ('.agents', '<skills_instructions>', str(HOME), str(HOME).replace('\\', '/'),
                                    HOME.name) and v}
    external = noauth['proxied'] + scr['proxied'] + noauth['non_loopback_connections'] + scr['non_loopback_connections']
    same_items = ([(i['type'], i.get('role'), [(c['chars'], c['sha256']) for c in i.get('content', [])])
                   for i in blocks['frozen_route_no_auth']['model_request']['items'] if i['type'] != 'additional_tools'
                   and 'environments.environment_context' not in (i.get('content_item_kinds') or [])] ==
                  [(i['type'], i.get('role'), [(c['chars'], c['sha256']) for c in i.get('content', [])])
                   for i in blocks['frozen_route_scrambled_auth']['model_request']['items']
                   if i['type'] != 'additional_tools'
                   and 'environments.environment_context' not in (i.get('content_item_kinds') or [])])
    established = not final_hits and not final_desc and not owner_markers_final and not external
    doc = {
        'about': 'P5 effective context evidence (annex effective_context_evidence), regenerated 2026-10-25 from '
                 'request boundary evidence (D4 route a, Opus B fix of OB-P5): the frozen exec argv of the harness '
                 '(isolation.codex_argv with config.ROUTE_SECURITY_ARGS and the disable options of cli-flags.json) '
                 'in a fresh worker home built by the harness isolation code, with only `-c openai_base_url=<localhost '
                 'capture server>` added (and, for the scrambled auth variant, `-c chatgpt_base_url=<same server>`). '
                 'The capture server records every request in full and answers the model request with HTTP 400, so '
                 'no model is called; every other connection is routed through HTTP(S)_PROXY and ALL_PROXY to a '
                 'localhost proxy that refuses it, and the process tree TCP connections are polled. Text is recorded '
                 'by length and sha256; the full captures stay outside the repository (capture_file_sha256).',
        'verdict': 'established' if established else 'not_established',
        'verdict_rule': 'established only if the captured model request of the frozen route (no auth and scrambled '
                        'ChatGPT auth) contains no owner skill, plugin, memory or AGENTS.md content (owner_content_scan) '
                        'and the probes made no external request',
        'verdict_reason': ('the frozen route request carries no line of any owner instruction source, no owner skill '
                           'description, no owner profile path and no skills instructions item; no request left '
                           'the loopback interface') if established else
                          f'owner content or external requests found: hits {final_hits[:5]}, descriptions '
                          f'{final_desc[:5]}, markers {owner_markers_final}, external {external[:5]}',
        'captured_at': noauth['at'],
        'cli_version': config.CODEX_CLI_VERSION,
        'executable_sha256': EXE['sha256'],
        'route_security_args': list(config.ROUTE_SECURITY_ARGS),
        'disable_args': disable_args,
        'closes': {
            'P5-E1': 'owner ~/.agents/skills listed in the request on the previous route (previous_route: '
                     f"{sum('.agents' in k for k in results['previous_route']['desc_hits'])} skill descriptions from "
                     f"~/.agents/skills and {sum('.system' in k for k in results['previous_route']['desc_hits'])} of "
                     f"the bundled skills, a <skills_instructions> "
                     'item of 22156 characters naming the owner profile root). Root cause: the pinned binary resolves '
                     'the user skills root from the OS profile (Windows known folder), not from CODEX_HOME, HOME or '
                     'USERPROFILE; moving the working directory outside the profile does not change it (debug '
                     'prompt-input with the working directory below and outside the profile lists the same root). '
                     '--enable skip_host_skill_discovery does not remove it on the exec route. Closed by '
                     '`-c skills.include_instructions=false` (SkillsConfig.include_instructions of the pinned '
                     'config schema): the skills instructions item is absent from the frozen route request',
            'P5-E2': 'bundled CODEX_HOME skills/.system: closed by `-c skills.bundled.enabled=false` '
                     '(BundledSkillsConfig.enabled): nothing is written under skills/ and nothing is listed',
            'P5-E3': 'multi_agent role and mode developer items and the collaboration tools stay in the request although '
                     'multi_agent and multi_agent_v2 are disabled: vendor content of the pinned binary (verbatim in '
                     'the executable where vendor_provenance says so), not owner content; disclosed below for the '
                     'signatories',
        },
        'request_boundary': {
            'external_requests': external,
            'proxy_honoured': 'control: with the plugins feature enabled the same probe sends CONNECT chatgpt.com:443, '
                              'github.com:443 and api.github.com:443 to the refusing proxy, so the CLI honours the '
                              'proxy variables and a request outside loopback would have been recorded',
            'previous_route': blocks['previous_route'],
            'frozen_route_no_auth': blocks['frozen_route_no_auth'],
            'frozen_route_scrambled_auth': blocks['frozen_route_scrambled_auth'],
            'auth_modes_same_items': same_items,
        },
        'provider_block_analysis': {
            'change': '`-c openai_base_url` only replaces the base URL of the built in provider `openai`; '
                      'model_provider stays openai (the analytics event of the scrambled probe records model_provider '
                      'openai) and no provider block is added',
            'differential': 'the developer and user items of the no auth and the scrambled ChatGPT auth probes are '
                            'identical by sha256 except the environment context, which names the per probe working '
                            'directory (auth_modes_same_items)',
            'residual': 'on the live route the client fetches /models from the provider; the probes answered 404, so '
                        'model metadata a live /models response carries (vendor content, not owner content) could '
                        'change the vendor base instructions or tools. The telemetry certificate keeps its own checks',
        },
        'owner_content_scan': {
            'method': 'every distinct stripped line of at least 40 characters of every text file (<= 2 MB) under the '
                      'owner instruction roots, and every owner SKILL.md description, searched as substrings of all '
                      'string values of the captured model request; owner files are read, never changed',
            'roots_files': roots_seen,
            'files_read': len(files),
            'lines_checked': len(lines),
            'skill_descriptions_checked': len(descs),
            'hits': sorted(set(final_hits))[:50],
            'vendor_copy_overlap': {
                'rule': 'a matching line is not owner content when every owner file that holds it is a byte identical '
                        'copy of a file the pinned binary writes into an empty CODEX_HOME (~/.codex/skills/.system, '
                        'checked by sha256 against the previous startup manifest captured from the pinned CLI)',
                'lines': len(set(results['frozen_route_no_auth']['vendor_hits'])
                             | set(results['frozen_route_scrambled_auth']['vendor_hits'])),
                'sources': sorted({src for lab in ('frozen_route_no_auth', 'frozen_route_scrambled_auth')
                                   for line in results[lab]['vendor_hits'] for src in lines[line]}),
                'found_in_items': sorted({k for lab in ('frozen_route_no_auth', 'frozen_route_scrambled_auth')
                                          for line in results[lab]['vendor_hits']
                                          for it in results[lab]['body'].get('input') or []
                                          if any(line in (c.get('text') or '') for c in it.get('content') or [])
                                          for k in ((it.get('internal_chat_message_metadata_passthrough') or {})
                                                    .get('content_item_kinds') or ['?'])}),
            },
            'skill_description_hits': sorted(set(final_desc)),
            'owner_path_markers': owner_markers_final,
            'previous_route_hits': {'lines': len(results['previous_route']['hits']),
                                    'skill_descriptions': len(results['previous_route']['desc_hits'])},
        },
        'vendor_items_disclosed': [
            'model.base_instructions developer item (the base instructions travel as the first developer message; the '
            'request instructions field is empty)',
            'permissions.instructions and collaboration_mode.instructions developer item',
            'multi_agent.role_instructions and multi_agent.mode_instructions developer items',
            'additional_tools developer item: namespace functions (exec, wait, request_user_input, '
            'request_user_input_async) and namespace collaboration (followup_task, interrupt_agent, list_agents, '
            'send_message, spawn_agent, wait_agent); the exec description lists web search, sports, time and weather '
            'helpers. The top level tools field is empty',
            'environments.environment_context user item (working directory, shell, date, time zone, read only '
            'filesystem profile)',
        ],
        'harness_input': 'the prompt arrives as one user message whose single input_text equals the stdin bytes',
        'debug_prompt_input_note': 'the earlier rendering with `codex debug prompt-input` (captured 20261025T005939Z) '
                                   'ignores -c, --enable and --disable and is superseded by this request boundary '
                                   'evidence',
        'probe_scripts': {name: sh(HERE / name) for name in ('boundary.py', 'decode.py', 'gen_p5.py')},
        'probe_scripts_location': 'docs/design/ozmap-replication-2026-10-24/rulings/evidence/p5-probe/ (run from a '
                                  'scratch copy: they write their captures next to themselves)',
    }
    (RULINGS / 'P5-effective-context-evidence.json').write_bytes(
        (json.dumps(doc, indent=1, ensure_ascii=False) + '\n').encode('utf-8'))

    # ------------------------------------------------------------------------------------------ startup manifest
    inventories = {'exec_no_auth': noauth['home_after'], 'exec_scrambled_auth': scr['home_after']}
    instruction = sorted({e['path'] for inv in inventories.values() for e in inv
                          if e['type'] == 'file' and isolation._matches(e['path'], config.INSTRUCTION_BEARING)})
    old_manifest = json.loads((HERE / 'manifest-head.json').read_text(encoding='utf-8'))
    manifest = {
        'about': old_manifest['about'],
        'cli_version': config.CODEX_CLI_VERSION,
        'executable_sha256': EXE['sha256'],
        'capture': {
            'captured_at': noauth['at'],
            'method': 'regenerated 2026-10-25 from the request boundary probes of the frozen exec argv (P5 effective '
                      'context evidence, D4 route a): inventory of the worker home after each probe; the route now '
                      'carries skills.bundled.enabled=false, so the pinned CLI writes no skills/.system file',
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
    print('verdict', doc['verdict'], 'hits', len(final_hits), 'desc', final_desc, 'markers', owner_markers_final,
          'external', external, 'same_items', same_items, 'lines', len(lines), 'files', len(files),
          'prev desc hits', len(results['previous_route']['desc_hits']))
    return doc


main()
