"""Zero-token fixture caller for the code-review dry gate: stands in for `claude -p ... --output-format stream-json`.

The scenario file named by CR_FIXTURE_CALLER (outside the workspace) scripts what a caller does, step by step, in the
workspace it is started in, and writes a stream-json transcript with per-message usage and a final result envelope:
  {"steps": [{"cat": [paths]} | {"oz": <oz.do/1 request>}, ...],
   "answer": "<final text>" | {"from_oz": {"<module path>": "<job ID>"}} | null,
   "final": "success" | "max_turns" | "none" (no result event), "usage": {per-message usage, a counter may be left
   out to stand for missing usage}, "sleep": seconds,
   "log": "<file that gets one line per invocation>"}
A {"cat": ...} step reads the files and returns their text; an {"oz": ...} step runs the `oz` shim's command from PATH
(its export lines and exec line) with the request on stdin, exactly as Bash would.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

if '--version' in sys.argv:
    print('0.0.0 (fixture caller)')
    sys.exit(0)
prompt = sys.stdin.buffer.read().decode('utf-8')
sc = json.loads(Path(os.environ['CR_FIXTURE_CALLER']).read_text(encoding='utf-8'))
if sc.get('log'):
    with open(sc['log'], 'a', encoding='utf-8') as f:
        f.write('%s\n' % os.getcwd())
usage = sc.get('usage') or {'input_tokens': 1500, 'cache_read_input_tokens': 6000,
                            'cache_creation_input_tokens': 0, 'output_tokens': 300}
oz_out = None


def emit(event):
    sys.stdout.write(json.dumps(event) + '\n')
    sys.stdout.flush()
    time.sleep(sc.get('sleep', 0))


def run_oz(request):
    shim = next(Path(d) / 'oz' for d in os.environ['PATH'].split(os.pathsep) if (Path(d) / 'oz').is_file())
    env, argv = dict(os.environ), None
    for line in shim.read_text(encoding='utf-8').splitlines():
        if line.startswith('export '):
            key, _, value = shlex.split(line[7:])[0].partition('=')
            env[key] = value
        elif line.startswith('exec '):
            argv = [a for a in shlex.split(line)[1:] if a != '$@']
    text = json.dumps(request)
    proc = subprocess.run(argv + ['do', '--adapter', 'adapter.json'], input=text.encode('utf-8'),
                          capture_output=True, env=env)
    return "oz do --adapter adapter.json <<'EOF'\n%s\nEOF" % text, proc.stdout.decode('utf-8')


emit({'type': 'system', 'subtype': 'init'})
n = 0
for step in sc.get('steps', []):
    if 'cat' in step:
        command = 'cat ' + ' '.join(step['cat'])
        result = ''.join(Path(p).read_text(encoding='utf-8') for p in step['cat'])
    else:
        command, result = run_oz(step['oz'])
        oz_out = json.loads(result) if result.strip() else None
    emit({'type': 'assistant', 'message': {'id': 'msg%d' % n, 'content': [
        {'type': 'tool_use', 'id': 'tu%d' % n, 'name': 'Bash', 'input': {'command': command}}], 'usage': usage}})
    emit({'type': 'user', 'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'tu%d' % n,
                                                    'content': result}]}})
    n += 1
answer = sc.get('answer')
if isinstance(answer, dict):
    answer = json.dumps({path: oz_out['jobs'][job]['value'] for path, job in answer['from_oz'].items()})
final = sc.get('final', 'success')
if final == 'success':
    emit({'type': 'assistant', 'message': {'id': 'msg%d' % n, 'content': [{'type': 'text', 'text': answer or ''}],
                                           'usage': usage}})
    n += 1
if final != 'none':
    total = lambda k: usage.get(k, 0) * n
    counters = {'inputTokens': total('input_tokens'), 'cacheReadInputTokens': total('cache_read_input_tokens'),
                'cacheCreationInputTokens': total('cache_creation_input_tokens'),
                'outputTokens': total('output_tokens')}
    counters.pop(sc.get('drop_counter'), None)
    emit({'type': 'result', 'subtype': 'success' if final == 'success' else 'error_max_turns',
          'is_error': final != 'success', 'num_turns': n, 'result': (answer or '') if final == 'success' else '',
          'modelUsage': {'claude-sonnet-5-5': counters}})
