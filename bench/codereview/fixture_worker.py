"""Zero-token fixture worker for the code-review dry gate (oz.adapter/3 program). Not a model transport.

argv: [scenario.json]. The scenario maps module paths to the value each job returns ({"values": {path: value}}, a
value {"error": [code, message]} gives a model failure record) and module paths to the sha256 of their text
({"texts": {path: sha256}}); "drop_counter" leaves one modelUsage counter out; a job's module is the reference whose text has one of those digests. It writes a
provider-style envelope with modelUsage to OZ_ENVELOPE_PATH (set by cr_adapter.py) and prints the reduced response
through the same function as examples/claude_cli_adapter.py.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent   # the run root's code/ snapshot, which holds examples/claude_cli_adapter.py
spec = importlib.util.spec_from_file_location('claude_cli_adapter', HERE / 'examples' / 'claude_cli_adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def texts_of(refs):
    """The packet's refs by the key a job row uses: an object's keys, or a list's 0-based indices."""
    if isinstance(refs, dict):
        return {str(k): v for k, v in refs.items()}
    return {str(i): v for i, v in enumerate(refs)}


def main():
    scenario = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    request = json.load(sys.stdin)
    body = json.loads(request['prompt'])
    refs = texts_of(body.get('refs') or {})
    by_sha = {sha: path for path, sha in scenario['texts'].items()}
    lines = ['OZ/1g']
    for block in body['jobs']:
        for row in block[1:]:
            module = None
            for key in row[1:]:
                text = refs.get(str(key))
                if isinstance(text, str):
                    module = by_sha.get(hashlib.sha256(text.encode('utf-8')).hexdigest(), module)
            value = scenario['values'].get(module) if module else None
            if module is None or (isinstance(value, dict) and 'error' in value):
                code, message = value['error'] if module else ('missing_data', 'no module reference')
                lines.append(json.dumps([row[0], 'error', code, message]))
            else:
                lines.append(json.dumps({row[0]: value}, ensure_ascii=False, separators=(',', ':')))
    reply = '\n'.join(lines)
    usage = scenario.get('usage', {'input': 4000, 'output': 900})
    counters = {'inputTokens': usage['input'], 'outputTokens': usage['output'], 'cacheReadInputTokens': 0,
                'cacheCreationInputTokens': 0}
    counters.pop(scenario.get('drop_counter'), None)          # stands for a provider envelope with missing usage
    envelope = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': reply,
                'modelUsage': {'fixture-worker-1': counters}}
    raw = json.dumps(envelope).encode('utf-8')
    if os.environ.get('OZ_ENVELOPE_PATH'):
        adapter._publish(os.environ['OZ_ENVELOPE_PATH'], raw)
    json.dump(adapter.reduce(envelope), sys.stdout)


if __name__ == '__main__':
    main()
