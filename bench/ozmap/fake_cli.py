"""Fake `codex` and `claude` executables for the oz map dry run (council 3 close, N2). Standard library; no model call.

`pilot.py dry` runs the live driver unchanged: the same ArmHost, Scheduler, SlotPool, settlement, registry file, route
verification, launch gate, oz_quota and ChildLauncher children. Only the PATH differs: a directory holding these two
executables comes first, so the real adapters (codex_cli_adapter.py, claude_map_adapter.py) run them instead of the
real CLIs. The route check sees their hashes, so a dry route can never pass as a live route and the other way round.

Each fake is a real executable: on Windows the console launcher that pip's script maker uses (distlib t64.exe), a
shebang naming this interpreter and a zip holding __main__.py (the FAKE program below), the same structure as every
console script in a virtual environment; elsewhere an executable Python script. The fake reads replay.json next to it:
  answers  {sha256 of a referenced input text: the answer value} (the dry run's perfect model: oracle and dataset gold)
  rules    {operation: exact oz-rule/1 AST JSON text}; any other requested operation gets "none"
  samples  {"codex" | "claude": {"call": [usage samples], "bootstrap": [usage samples]}} recorded real usage
  leak     optional {"codex": true} / {"claude": true}: the fake also reports a tool event (tests only)
A sample is chosen by the content of the call (the sorted input hashes), so a run is deterministic; an identical
codex prompt seen again reports a larger cached_input_tokens with the same input_tokens (cache reuse, inclusive
accounting), which is what paired telemetry looks for. Every call writes one JSON log file under log/ with its argv,
the complete text it received, the isolation it observed (codex: an empty -C directory outside any repo; claude:
`--tools ''` and `--strict-mcp-config`), the sample and its recorded elapsed seconds. The fake never sleeps.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

FAKE = r'''import hashlib, json, os, sys, time, uuid
from pathlib import Path

HERE = Path(sys.argv[0]).resolve().parent
CRLF, LF = chr(13) + chr(10), chr(10)
NAME = Path(sys.argv[0]).name.lower().split('.')[0]
CONFIG = json.loads((HERE / 'replay.json').read_text(encoding='utf-8'))
sys.path[:0] = [CONFIG['repo'], os.path.join(CONFIG['repo'], 'examples')]
from oz_reply import Failure, encode_reply
import bootstrap_shim


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def inside_repo(path):
    probe = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(probe, '.git')) or os.path.isfile(os.path.join(probe, 'pyproject.toml')):
            return True
        parent = os.path.dirname(probe)
        if parent == probe:
            return False
        probe = parent


def fail(message, text):
    log({'cli': NAME, 'error': message, 'text': text, 'argv': sys.argv[1:]})
    raise SystemExit('fake: ' + message)


def body_of(text):
    """The OZ/1g packet: the last JSON object of the text that has jobs and refs."""
    cut = len(text)
    while True:
        at = text.rfind('\n\n', 0, cut)
        start = at + 2 if at >= 0 else 0
        try:
            body = json.loads(text[start:])
            if isinstance(body, dict) and 'jobs' in body and 'refs' in body:
                return body
        except ValueError:
            pass
        if at < 0:
            fail('no OZ/1g packet in the input', text)
        cut = at


def reply_for(system, prompt_text):
    body = body_of(prompt_text)
    answers, keys, misses = {}, [], 0
    for block in body['jobs']:
        for row in block[1:]:
            text = body['refs'][row[1]]
            key = sha(text)
            keys.append(key)
            if key in CONFIG['answers']:
                answers[row[0]] = CONFIG['answers'][key]
            else:
                answers[row[0]] = Failure('unknown_input', 'the fake has no answer for this input')
                misses += 1
    reply = encode_reply(answers)
    bootstrap = bootstrap_shim.INSTRUCTION in system
    if bootstrap:
        marker = 'Requested operations (the OZ/1g op instruction for each is in the packet ops): '
        line = system[system.index(marker) + len(marker):].split('\n', 1)[0]
        ops = json.loads(line)
        rules = ','.join(json.dumps(op) + ':' + CONFIG['rules'].get(op, json.dumps('none')) for op in ops)
        reply = ('{"host":"oz-bootstrap/1","answers":' + json.dumps(reply, ensure_ascii=False) + ',"rules":{'
                 + rules + '}}')
    return reply, bootstrap, sorted(keys), misses


def sample(kind, keys):
    pool = CONFIG['samples'][NAME][kind] or CONFIG['samples'][NAME]['call']
    index = int(sha(json.dumps(keys)), 16) % len(pool)
    return index, pool[index]


def log(entry):
    folder = HERE / 'log'
    folder.mkdir(exist_ok=True)
    path = folder / f'{time.time_ns():020d}-{uuid.uuid4().hex[:8]}.json'
    with open(path, 'x', encoding='utf-8') as f:
        json.dump(entry, f, ensure_ascii=False)


def codex(argv):
    if argv == ['--version']:
        print('codex-cli fake-replay/1')
        return 0
    if not argv or argv[0] != 'exec':
        sys.stderr.write('fake codex: only exec and --version')
        return 2
    workdir = argv[argv.index('-C') + 1] if '-C' in argv else None
    isolated = (workdir is not None and os.path.isdir(workdir) and not os.listdir(workdir)
                and not inside_repo(workdir) and os.path.realpath(os.getcwd()) == os.path.realpath(workdir))
    text = sys.stdin.buffer.read().decode('utf-8')
    plain = text.replace(CRLF, LF)  # the adapter writes stdin in text mode (CRLF on Windows)
    reply, bootstrap, keys, misses = reply_for(plain, plain)
    index, s = sample('bootstrap' if bootstrap else 'call', keys)
    folder = HERE / 'log'
    prompt_sha = sha(text)
    repeat = sum(1 for p in folder.glob('*.json')
                 if json.loads(p.read_text(encoding='utf-8')).get('prompt_sha256') == prompt_sha) \
        if folder.is_dir() else 0
    cached = min(s['input_tokens'], s['cached_input_tokens'] + repeat * max(1, s['input_tokens'] // 4))
    usage = {'input_tokens': s['input_tokens'], 'cached_input_tokens': cached,
             'cache_write_input_tokens': s.get('cache_creation_input_tokens', 0), 'output_tokens': s['output_tokens'],
             'reasoning_output_tokens': s['reasoning_output_tokens']}
    events = [{'type': 'thread.started', 'thread_id': 'fake'}, {'type': 'turn.started'}]
    if (CONFIG.get('leak') or {}).get('codex'):
        events.append({'type': 'item.completed', 'item': {'id': 'item_1', 'type': 'command_execution',
                                                          'command': 'cat ../../bench/ozmap/registry.json'}})
    events += [{'type': 'item.completed', 'item': {'id': 'item_2', 'type': 'agent_message', 'text': reply}},
               {'type': 'turn.completed', 'usage': usage}]
    log({'cli': 'codex', 'argv': argv, 'text': text, 'prompt_sha256': prompt_sha, 'bootstrap': bootstrap,
         'keys': keys, 'misses': misses, 'sample': index, 'elapsed_seconds': s.get('elapsed_seconds', 0.0),
         'usage': usage, 'repeat': repeat, 'workdir': workdir, 'isolated': isolated})
    sys.stdout.write(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in events))
    return 0


def claude(argv):
    if argv == ['--version']:
        print('2.1.306 (Claude Code, fake replay)')
        return 0
    system = argv[argv.index('--system-prompt') + 1] if '--system-prompt' in argv else ''
    model = argv[argv.index('--model') + 1] if '--model' in argv else 'unknown'
    tools = argv[argv.index('--tools') + 1] if '--tools' in argv else None
    disabled = tools == '' and '--strict-mcp-config' in argv and '--setting-sources' in argv
    prompt = sys.stdin.buffer.read().decode('utf-8')
    reply, bootstrap, keys, misses = reply_for(system, prompt.replace(CRLF, LF))
    index, s = sample('bootstrap' if bootstrap else 'call', keys)
    raw = s['raw']
    leak = (CONFIG.get('leak') or {}).get('claude')
    envelope = {'type': 'result', 'subtype': 'success', 'is_error': False, 'num_turns': 2 if leak else 1,
                'result': reply, 'permission_denials': [{'tool_name': 'Read'}] if leak else [],
                'modelUsage': {model: {'inputTokens': raw['in_uncached'], 'cacheReadInputTokens': raw['cache_read'],
                                       'cacheCreationInputTokens': raw['cache_write'], 'outputTokens': raw['out']}}}
    log({'cli': 'claude', 'argv': [a if a != system else '<system>' for a in argv], 'text': system + '\n\n' + prompt,
         'prompt_sha256': sha(prompt), 'bootstrap': bootstrap, 'keys': keys, 'misses': misses, 'sample': index,
         'elapsed_seconds': s.get('elapsed_seconds', 0.0), 'usage': envelope['modelUsage'][model],
         'tools_disabled': disabled})
    sys.stdout.write(json.dumps(envelope, ensure_ascii=False))
    return 0


sys.exit(codex(sys.argv[1:]) if NAME == 'codex' else claude(sys.argv[1:]))
'''

ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _launcher() -> bytes:
    """The console launcher pip writes in front of every Windows console script (distlib t64.exe)."""
    import importlib.util
    spec = importlib.util.find_spec('pip')
    if spec is None or not spec.origin:
        raise RuntimeError('the Windows fake CLIs need pip (its distlib console launcher t64.exe) in this interpreter')
    path = Path(spec.origin).parent / '_vendor' / 'distlib' / 't64.exe'
    if not path.is_file():
        raise RuntimeError(f'the console launcher {path} is missing')
    return path.read_bytes()


def _program(python: str) -> bytes:
    if os.name == 'nt':
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as zf:
            zf.writestr(zipfile.ZipInfo('__main__.py', ZIP_TIME), FAKE.encode('utf-8'))
        quoted = f'"{python}"' if ' ' in python else python
        return _launcher() + b'#!' + quoted.encode('utf-8') + b'\n' + stream.getvalue()
    return f'#!{python}\n'.encode('utf-8') + FAKE.encode('utf-8')


def build(directory, *, answers: dict, rules: dict, samples: dict, repo, leak=None, python=None) -> dict:
    """Write replay.json and the two fake executables into directory. Returns {name: executable path}."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    config = {'repo': str(Path(repo).resolve()), 'answers': answers, 'rules': rules, 'samples': samples,
              'leak': leak or {}}
    (directory / 'replay.json').write_text(json.dumps(config, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    program = _program(python or sys.executable)
    out = {}
    for name in ('codex', 'claude'):
        path = directory / (name + ('.exe' if os.name == 'nt' else ''))
        path.write_bytes(program)
        if os.name != 'nt':
            path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        out[name] = str(path)
    return out


def env_with(directory, base=None) -> dict:
    """base (default os.environ) with the fake directory first on PATH."""
    env = dict(os.environ if base is None else base)
    env['PATH'] = str(Path(directory).resolve()) + os.pathsep + env.get('PATH', '')
    return env


def calls(directory) -> list:
    """Every logged fake call, in order."""
    folder = Path(directory) / 'log'
    return [json.loads(p.read_text(encoding='utf-8')) for p in sorted(folder.glob('*.json'))] if folder.is_dir() \
        else []


def key_of(texts) -> list:
    """The content key the fake logs for a call: sorted sha256 of the referenced input texts."""
    return sorted(hashlib.sha256(t.encode('utf-8')).hexdigest() for t in texts)
