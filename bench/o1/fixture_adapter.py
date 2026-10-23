"""Zero-token fixture adapter for the O1 dry gate (oz.adapter/3). Not a model transport.

It answers each OZ/1g job from the job's own record: the fixture modules in fixture/ hold a third valid implementation
of every function (neither reference), and the record's header names the ticket, revision and function. It writes a
provider-style envelope with modelUsage to OZ_ENVELOPE_PATH when the runner sets it and reduces it with the same
function as examples/claude_cli_adapter.py. Every invocation is appended to invocations.jsonl in OZ_FIXTURE_DIR: the
ground truth of physical launches in the dry gate. mode.json there selects fixture behavior per job ID:
  {"wrong_first": [...]}       the defective function from the record, on the job's first call in this binding only
  {"wrong_always": [...]}      the defective function on every call
  {"wire_reject_first": [...]} the reply omits the job on its first call (a wire-invalid reply), {"wire_reject": [...]}
  {"model_error": [...]}       a valid model failure record ["id","error","unsupported",...] on every call
  {"policy_first": [...]}      a source that imports a module, on the first call (refused by the AST policy)
  {"loop_first": [...]}        a source that never returns, on the first call (stopped by the CPU limit)
  {"rev1_core_for_rev2": true} a revision 1 core answer for a revision 2 record (wrong revision)
  {"usage": {"input": N, "output": M}}, {"thinking": N}, {"no_thinking": true}, {"no_model_usage": true},
  {"model": "other"}, {"sleep": seconds}
"""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('claude_cli_adapter', ROOT / 'examples' / 'claude_cli_adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
HEADER = re.compile(r'O1 repair ticket\nticket: ([A-Z])\nrevision: ([0-9]+)\nop: repair_(core|adapter)@1\n')


def function_source(text: str, name: str) -> str:
    tree = ast.parse(text)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ''.join(text.splitlines(keepends=True)[fn.lineno - 1:fn.end_lineno])


def record_parts(record: str) -> dict:
    m = HEADER.match(record)
    if m is None:
        raise SystemExit('fixture: the record has no header')
    name = re.search(r'^function: (\w+)$', record, re.M).group(1)
    defective = record.split('Defective function:\n', 1)[1].split('\n\nAccepted core function', 1)[0]
    return {'ticket': m.group(1), 'revision': int(m.group(2)), 'op': m.group(3), 'function': name,
            'defective': defective.rstrip('\n') + '\n'}


def fixture_answer(parts: dict, revision=None) -> str:
    rev = revision or parts['revision']
    file = HERE / 'fixture' / (f"{parts['ticket']}_rev{rev}.py" if parts['ticket'] == 'A' else f"{parts['ticket']}.py")
    return function_source(file.read_text(encoding='utf-8'), parts['function'])


def prior_calls(state: Path, binding: str, job: str) -> int:
    log = state / 'invocations.jsonl'
    if not log.exists():
        return 0
    rows = (json.loads(x) for x in log.read_text(encoding='utf-8').splitlines() if x.strip())
    return sum(1 for r in rows if r['binding'] == binding and job in r['ids'])


def answer(record: str, job: str, first: bool, mode: dict):
    """('value', source) or ('error', code, message) or None (omitted from the reply)."""
    parts = record_parts(record)
    if job in mode.get('model_error', []):
        return ('error', 'unsupported', 'the fixture declines this job')
    if job in mode.get('wire_reject', []) or (first and job in mode.get('wire_reject_first', [])):
        return None
    if job in mode.get('wrong_always', []) or (first and job in mode.get('wrong_first', [])):
        return ('value', parts['defective'])
    source = fixture_answer(parts)
    if mode.get('rev1_core_for_rev2') and parts['op'] == 'core' and parts['revision'] == 2:
        source = fixture_answer(parts, 1)
    if first and job in mode.get('policy_first', []):
        head, rest = source.split('\n', 1)
        source = head + '\n    import os\n' + rest
    if first and job in mode.get('loop_first', []):
        head, rest = source.split('\n', 1)
        source = head + '\n    while True:\n        pass\n' + rest
    return ('value', source)


def main():
    request = json.load(sys.stdin)
    state = Path(os.environ.get('OZ_FIXTURE_DIR') or HERE)
    mode_path = state / 'mode.json'
    mode = json.loads(mode_path.read_text(encoding='utf-8')) if mode_path.exists() else {}
    body = json.loads(request['prompt'])
    lines = ['OZ/1g']
    for block in body['jobs']:
        for row in block[1:]:
            first = prior_calls(state, request['binding'], row[0]) == 0
            got = answer(body['refs'][row[1]], row[0], first, mode)
            if got is None:
                continue
            if got[0] == 'error':
                lines.append(json.dumps([row[0], 'error', got[1], got[2]], ensure_ascii=False))
            else:
                lines.append(json.dumps({row[0]: got[1]}, ensure_ascii=False, separators=(',', ':')))
    reply = '\n'.join(lines)
    tokens_in = (len(request['system']) + len(request['prompt'])) // 4
    model = mode.get('model', os.environ.get('OZ_FIXTURE_MODEL', 'fixture-oracle-1'))
    used = mode.get('usage') or {}
    envelope = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': reply,
                'usage': {'input_tokens': 1, 'output_tokens': 1, 'cache_read_input_tokens': 0,
                          'cache_creation_input_tokens': 0},
                'modelUsage': {model: {'inputTokens': used.get('input', tokens_in),
                                       'outputTokens': used.get('output', len(reply) // 4),
                                       'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0}}}
    if not mode.get('no_thinking'):
        envelope['modelUsage'][model]['thinkingTokens'] = mode.get('thinking', 0)
    if mode.get('no_model_usage'):
        del envelope['modelUsage']
    time.sleep(mode.get('sleep', 0))
    raw = json.dumps(envelope).encode('utf-8')
    if os.environ.get('OZ_ENVELOPE_PATH'):
        adapter._publish(os.environ['OZ_ENVELOPE_PATH'], raw)
    with open(state / 'invocations.jsonl', 'a', encoding='utf-8') as log:
        log.write(json.dumps({'binding': request['binding'], 'receipt': request['receipt'], 'ids': request['ids'],
                              'pid': os.getpid(), 'prompt_sha256': hashlib.sha256(
                                  request['prompt'].encode('utf-8')).hexdigest()}) + '\n')
    json.dump(adapter.reduce(envelope), sys.stdout)


if __name__ == '__main__':
    main()
