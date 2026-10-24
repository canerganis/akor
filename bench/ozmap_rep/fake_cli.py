"""Harness-owned fake `codex` and `claude` executables for fake mode and the dry run (never a real CLI).

build(run_dir) writes run_dir/fake/codex.py and run_dir/fake/claude.py plus the answer table (sha256 of each job's
resolved text -> gold). The runner spawns them with the same argv, stdin, environment, working directory and
isolation it uses live; only the executable differs. Each fake reads the directive the runner wrote for its slot
(cell, call number, injected failure, injected token refresh, bootstrap operations), records what it saw (argv, the
CODEX_HOME and working directory listings, environment names and the stdin hash) in run_dir/fake/records, and answers
every job with its gold label. A bootstrap reply is the oz-bootstrap/1 envelope proposing "none" for every operation
(the zero-rule case of A4.4). Usage is synthetic and consistent with the reasoning predicate: output = visible reply
tokens + 40 reasoning tokens, cached input 0.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import config

FAKE_REASONING = 40

COMMON = r'''
import base64, datetime, hashlib, json, os, sys
CFG = json.loads(__CFG__)
sys.path.insert(0, CFG['repo'])


def sha(data):
    return hashlib.sha256(data).hexdigest()


def listing(d):
    return sorted(os.listdir(d)) if d and os.path.isdir(d) else []


def publish(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def directive_for(workdir):
    with open(os.path.join(CFG['directives'], os.path.basename(workdir) + '.json'), encoding='utf-8') as f:
        return json.load(f)


def answer_reply(body):
    with open(CFG['answers'], encoding='utf-8') as f:
        table = json.load(f)
    lines = ['OZ/1g']
    for block in body['jobs']:
        for row in block[1:]:
            pid, ref = row[0], row[1]
            key = sha(body['refs'][ref].encode('utf-8'))
            if key in table:
                lines.append(json.dumps({pid: table[key]}, ensure_ascii=False, separators=(',', ':')))
            else:
                lines.append(json.dumps([pid, 'error', 'missing_data', 'fake: unknown job']))
    return '\n'.join(lines)


def reply_for(text, directive):
    body = json.loads(text.rsplit('\n', 1)[-1])
    reply = answer_reply(body)
    ops = directive.get('bootstrap_ops')
    if ops:
        reply = json.dumps({'host': 'oz-bootstrap/1', 'answers': reply, 'rules': {op: 'none' for op in ops}},
                           ensure_ascii=False, separators=(',', ':'))
    return reply


def visible(reply):
    from bench.ozmap_rep import tokenizer
    n = tokenizer.count([reply])[0]
    return n if n is not None else max(1, len(reply) // 4)
'''

CODEX = COMMON + r'''

def refresh(home):
    mark = 'SECRET-FAKE-' + 'REFRESHED'  # assembled at run time so the fake's own source never holds the marker
    exp = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=20)).timestamp())
    b64 = lambda d: base64.urlsafe_b64encode(d).rstrip(b'=').decode()
    claims = {'exp': exp, 'marker': mark + '-ACCESS'}
    token = '.'.join([b64(b'{"alg":"none"}'), b64(json.dumps(claims).encode()), b64(b'sig')])
    doc = {'auth_mode': 'chatgpt', 'tokens': {'id_token': 'x.y.z', 'access_token': token,
                                              'refresh_token': mark + '-REFRESH'},
           'last_refresh': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')}
    with open(os.path.join(home, 'auth.json'), 'w', encoding='utf-8') as f:
        json.dump(doc, f)


NO_AUTH = 'unexpected status 401 Unauthorized: Missing bearer or basic authentication in header'


def local_command(argv, home):
    """The local subcommands the harness runs (no model request): login status and features list."""
    authed = bool(home) and os.path.isfile(os.path.join(home, 'auth.json'))
    if 'login' in argv and 'status' in argv:
        sys.stdout.write('Logged in using ChatGPT\n' if authed else 'Not logged in\n')
        return 0 if authed else 1
    if 'features' in argv and 'list' in argv:
        disabled = {argv[i + 1] for i, a in enumerate(argv[:-1]) if a == '--disable'}
        enabled = {argv[i + 1] for i, a in enumerate(argv[:-1]) if a == '--enable'}
        for name in CFG['features']:
            on = name == 'unified_exec' or name not in disabled
            sys.stdout.write(f'{name:<40} stable             {str(on).lower()}\n')
        on = 'skip_host_skill_discovery' in enabled
        sys.stdout.write(f'{"skip_host_skill_discovery":<40} under development  {str(on).lower()}\n')
        return 0
    return None


def accepted(home):
    """The fake server's view of the home's credentials: tokens it never issued (a scrambled signature) fail."""
    try:
        with open(os.path.join(home, 'auth.json'), encoding='utf-8') as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return False
    token = (doc.get('tokens') or {}).get('access_token') or ''
    return not (token.count('.') == 2 and token.split('.')[2].startswith('scrambled'))


def write_rollout(home, directive):
    """Without --ephemeral the pinned CLI persists a session rollout in CODEX_HOME (P3, Fable F7 and F8)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    folder = os.path.join(home, 'sessions', now.strftime('%Y'), now.strftime('%m'), now.strftime('%d'))
    os.makedirs(folder, exist_ok=True)
    rows = [{'timestamp': stamp, 'type': 'session_meta', 'payload': {'cli_version': '0.160.0'}},
            {'timestamp': stamp, 'type': 'event_msg', 'payload': {'type': 'token_count', 'rate_limits': {
                'primary': {'used_percent': 10.0, 'window_minutes': 10080}}}}]
    with open(os.path.join(folder, 'rollout-fake.jsonl'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(json.dumps(r) for r in rows) + '\n')


def main():
    argv = list(sys.argv)
    home = os.environ.get('CODEX_HOME')
    local = local_command(argv, home)
    if local is not None:
        return local
    stdin = sys.stdin.buffer.read()
    workdir = argv[argv.index('-C') + 1] if '-C' in argv else os.getcwd()
    directive = directive_for(workdir)
    if not (home and os.path.isfile(os.path.join(home, 'auth.json'))) or not accepted(home):
        out = [{'type': 'thread.started', 'thread_id': 'fake-noauth'}, {'type': 'turn.started'},
               {'type': 'error', 'message': 'Reconnecting... 1/5 (' + NO_AUTH + ')'},
               {'type': 'turn.failed', 'error': {'message': NO_AUTH}}]
        sys.stdout.write('\n'.join(json.dumps(e) for e in out) + '\n')
        return 1
    publish(os.path.join(CFG['records'], directive['call_id'] + '.json'),
            {'cell': directive['cell'], 'n': directive['n'], 'cli': 'codex', 'argv': argv, 'codex_home': home,
             'home_listing': listing(home), 'workdir': workdir, 'workdir_listing': listing(workdir),
             'env_names': sorted(os.environ), 'stdin_sha256': sha(stdin)})
    if directive.get('fail'):
        sys.stderr.write('fake codex: injected infrastructure failure')
        return 1
    text = stdin.decode('utf-8')
    reply = reply_for(text, directive)
    if directive.get('refresh') and home:
        refresh(home)
    if '--ephemeral' not in argv and home:
        write_rollout(home, directive)
    vis = visible(reply)
    usage = {'input_tokens': max(1, len(text) // 4), 'cached_input_tokens': 0,
             'output_tokens': vis + __REASONING__, 'reasoning_output_tokens': __REASONING__}
    out = [{'type': 'thread.started', 'thread_id': 'fake-' + directive['call_id']}, {'type': 'turn.started'},
           {'type': 'item.completed', 'item': {'id': 'item_0', 'type': 'reasoning', 'text': ''}},
           {'type': 'item.completed', 'item': {'id': 'item_1', 'type': 'agent_message', 'text': reply}},
           {'type': 'turn.completed', 'usage': usage}]
    sys.stdout.write('\n'.join(json.dumps(e, ensure_ascii=False) for e in out) + '\n')
    return 0


sys.exit(main())
'''

CLAUDE = COMMON + r'''

def main():
    argv = list(sys.argv)
    stdin = sys.stdin.buffer.read()
    workdir = os.getcwd()
    directive = directive_for(workdir)
    publish(os.path.join(CFG['records'], directive['call_id'] + '.json'),
            {'cell': directive['cell'], 'n': directive['n'], 'cli': 'claude', 'argv': argv, 'codex_home': None,
             'home_listing': [], 'workdir': workdir, 'workdir_listing': listing(workdir),
             'env_names': sorted(os.environ), 'stdin_sha256': sha(stdin)})
    if directive.get('fail'):
        sys.stderr.write('fake claude: injected infrastructure failure')
        return 1
    text = stdin.decode('utf-8')
    reply = reply_for(text, directive)
    system = argv[argv.index('--system-prompt') + 1] if '--system-prompt' in argv else ''
    model = argv[argv.index('--model') + 1] if '--model' in argv else 'unknown'
    usage = {'inputTokens': max(1, (len(text) + len(system)) // 4), 'cacheReadInputTokens': 0,
             'cacheCreationInputTokens': 0, 'outputTokens': max(1, len(reply) // 4)}
    sys.stdout.write(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': reply,
                                 'num_turns': 1, 'permission_denials': [], 'modelUsage': {model: usage}},
                                ensure_ascii=False))
    return 0


sys.exit(main())
'''


def build(run_dir, answers) -> dict:
    """Write the fakes and the answer table under run_dir/fake; returns their paths."""
    root = Path(run_dir) / 'fake'
    for sub in ('directives', 'records'):
        (root / sub).mkdir(parents=True, exist_ok=True)
    table = root / 'answers.json'
    table.write_text(json.dumps(answers, sort_keys=True), encoding='utf-8')
    cfg = json.dumps({'repo': str(config.REPO), 'directives': str(root / 'directives'),
                      'records': str(root / 'records'), 'answers': str(table),
                      'features': list(config.DISABLE_FEATURES)})
    paths = {}
    for name, template in (('codex', CODEX), ('claude', CLAUDE)):
        source = template.replace('__CFG__', repr(cfg)).replace('__REASONING__', str(FAKE_REASONING))
        path = root / f'{name}.py'
        if not path.exists() or path.read_text(encoding='utf-8') != source:
            path.write_text(source, encoding='utf-8')
        paths[name] = path
    return {'codex': paths['codex'], 'claude': paths['claude'], 'directives': root / 'directives',
            'records': root / 'records', 'root': root}


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
