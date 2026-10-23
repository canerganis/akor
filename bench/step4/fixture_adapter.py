"""Zero-token oracle fixture adapter for the step 4 dry gate (oz.adapter/3). Not a model transport.

It answers each OZ/1g job from the packet itself (Decimal arithmetic on the job's own record), writes a provider-style
envelope with modelUsage to OZ_ENVELOPE_PATH when the runner sets it, and reduces that envelope with the same
function as examples/claude_cli_adapter.py. Every invocation is appended to invocations.jsonl in OZ_FIXTURE_DIR (default: beside this file): that
log is the ground truth of physical launches in the dry gate. mode.json there selects sabotage behavior:
  {"stale_classify_A": true}  classify answers for a record with length 12.55 mm come from the old record (12.50 mm)
  {"model": "other-model"}     the envelope reports another model
  {"wire_reject": ["job"]}     the reply omits that job (wire-invalid reply)
  {"no_model_usage": true}     the envelope has no modelUsage (usage and model identity unknown)
  {"sleep": seconds}           wait before answering (external-kill fixtures)
"""
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('claude_cli_adapter', ROOT / 'examples' / 'claude_cli_adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)

FIELDS = ('length', 'uncertainty', 'n', 'method', 'basis', 'physical_validation')


def fields(text):
    return dict(p.split('=', 1) for p in text.split('; '))


def bounds(f):
    if f['uncertainty'] == 'unknown':
        return 'unknown'
    length, u = Decimal(f['length'][:-3]), Decimal(f['uncertainty'][:-3])
    return [f'{length - u:.2f} mm', f'{length + u:.2f} mm']


def classify(f):
    b = bounds(f)
    if b == 'unknown':
        return 'unknown'
    return 'inside' if Decimal(b[0][:-3]) >= Decimal('12.48') and Decimal(b[1][:-3]) <= Decimal('12.52') else 'outside'


def answer(instruction, record, mode):
    f = fields(record)
    if instruction.startswith('Return a compact JSON array of strings'):
        return [f[k] for k in FIELDS]
    if instruction.startswith('Return a compact JSON array [length-uncertainty'):
        return bounds(f)
    if instruction.startswith('Return inside if'):
        if mode.get('stale_classify_A') and f['length'] == '12.55 mm':
            f = dict(f, length='12.50 mm')
        return classify(f)
    raise SystemExit('fixture: unknown instruction')


def baseline_reply(prompt):
    """The no-orchestration arm's document, computed by the fixture from the prompt's records (dry gate only)."""
    lines = prompt.splitlines()
    records = json.loads(next(x for x in lines if x.startswith('[{"record"')))
    evidence = json.loads(next(x for x in lines if x.startswith('"evidence": '))[len('"evidence": '):])
    rows = []
    for r in records:
        f = fields(r['text'])
        b = bounds(f)
        status = classify(f)
        missing = [k for k in ('uncertainty', 'method', 'basis') if f[k] == 'unknown']
        ups = [{'category': 'missing_metadata', 'field': k} for k in missing]
        ups += [{'category': 'numerical_review'}] if status == 'outside' else []
        ups += [{'category': 'uncertainty_required'}] if b == 'unknown' else []
        rows.append({'record': r['record'], 'source': {'name': r['record'], 'revision': r['revision'],
                                                       'sha256': r['sha256']},
                     'measurement': {k: f[k] for k in FIELDS}, 'interval': b, 'status': status, 'missing': missing,
                     'follow_ups': ups})
    return json.dumps({'schema': 'akor.inspection-handoff/1', 'workflow': 'inspection-handoff-20/v1',
                       'acceptance_interval': {'lower': '12.48 mm', 'upper': '12.52 mm', 'inclusive': True},
                       'physical_validation': 'not_claimed', 'evidence': evidence, 'records': rows})


def main():
    request = json.load(sys.stdin)
    state = Path(os.environ.get('OZ_FIXTURE_DIR') or HERE)
    mode_path = state / 'mode.json'
    mode = json.loads(mode_path.read_text(encoding='utf-8')) if mode_path.exists() else {}
    lines = ['OZ/1g'] if request.get('binding') != 'baseline' else [baseline_reply(request['prompt'])]
    for block in (json.loads(request['prompt'])['jobs'] if request.get('binding') != 'baseline' else []):
        body = json.loads(request['prompt'])
        instruction = body['ops'][block[0]]
        for row in block[1:]:
            if row[0] in mode.get('wire_reject', []):
                continue
            record = body['refs'][row[1]]
            lines.append(json.dumps({row[0]: answer(instruction, record, mode)}, ensure_ascii=False,
                                    separators=(',', ':')))
    reply = '\n'.join(lines)
    tokens_in = (len(request['system']) + len(request['prompt'])) // 4
    model = mode.get('model', os.environ.get('OZ_FIXTURE_MODEL', 'fixture-oracle-1'))
    envelope = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': reply,
                'usage': {'input_tokens': 1, 'output_tokens': 1, 'cache_read_input_tokens': 0,
                          'cache_creation_input_tokens': 0},
                'modelUsage': {model: {'inputTokens': tokens_in, 'outputTokens': len(reply) // 4,
                                       'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0}}}
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
