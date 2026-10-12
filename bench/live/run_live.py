"""Live A/B pilot: 0.8 rows vs OZ/9 vs OZ/9 + RESULTS_RULE on Sonnet via `claude -p`.

Run from the repo root with the .venv python. Billed usage comes from the CLI's own
usage report (input + cache creation + cache read = raw input). Every call is
sequential; arm order is shuffled per (domain, n, rep) so drift hits all arms.
"""
import json, os, random, re, shutil, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, '.')
import tiktoken
import oz_batch
from oz2_benchmark import WORK, scenario
try:
    from oz_reply import validate_reply  # removed in the JSONL wire; only old arms use it
except ImportError:
    validate_reply = None

LIVE = Path(__file__).parent
SYSTEM = 'You are a worker agent in a multi-agent orchestration. Do what the packet asks and reply exactly in its format.'
CLAUDE = shutil.which('claude')
enc = tiktoken.get_encoding('o200k_base')
count = lambda s: len(enc.encode(s, disallowed_special=()))
SIZES = [int(x) for x in os.environ.get('SIZES', '1,4,16').split(',')]
REPS = int(os.environ.get('REPS', '3'))
OUT = LIVE / 'data' / os.environ.get('OUT', 'results.jsonl')


def b36(n):
    s = ''
    while n:
        n, d = divmod(n, 36)
        s = '0123456789abcdefghijklmnopqrstuvwxyz'[d] + s
    return s


def packets09(dom, n, receipt, rule):
    ch = scenario(dom)
    ids = [f'{dom[:2]}_{i + 1:02d}' for i in range(n)]
    b = oz_batch.render(ch, list(zip(ids, (WORK[i % len(WORK)] for i in range(n)))), counters=[count],
                        receipt=receipt, results_rule=rule)
    return ids, b.text, b.tokens[0], b.mode


def parse(text):
    """Strict JSON, and a lenient retry that strips one Markdown fence."""
    try:
        return json.loads(text), True
    except ValueError:
        m = re.fullmatch(r'\s*```(?:json)?\s*(.*?)\s*```\s*', text, re.S)
        if m:
            try:
                return json.loads(m.group(1)), False
            except ValueError:
                pass
    return None, False


def results08(value, ids):
    if not isinstance(value, dict) or not isinstance(value.get('results'), list):
        raise ValueError('no results')
    out = {}
    for row in value['results']:
        if (not isinstance(row, list) or len(row) != 3 or row[0] not in ids or row[0] in out
                or row[1] not in (0, 1, 2) or not isinstance(row[2], str) or not row[2].strip()):
            raise ValueError('bad row')
        out[row[0]] = ({0: 'ok', 1: 'retry', 2: 'failed'}[row[1]], row[2])
    if set(out) != set(ids):
        raise ValueError('missing ids')
    return out


def call_codex(prompt, model):
    """Codex CLI (read-only sandbox, ephemeral). Usage from the turn.completed event."""
    start = time.monotonic()
    effort = os.environ.get('EFFORT', 'medium')
    wd = LIVE / 'codexwd'
    wd.mkdir(exist_ok=True)
    try:
        proc = subprocess.run([shutil.which('codex'), 'exec', '-m', model, '-c', f'model_reasoning_effort="{effort}"',
                               '-s', 'read-only', '--skip-git-repo-check', '--ephemeral', '--json', '-'],
                              input=prompt, capture_output=True, text=True, encoding='utf-8', cwd=wd, timeout=600)
        events = [json.loads(l) for l in proc.stdout.splitlines() if l.startswith('{')]
        text = [e['item']['text'] for e in events if e.get('type') == 'item.completed'
                and e['item'].get('type') == 'agent_message'][-1]
        u = [e['usage'] for e in events if e.get('type') == 'turn.completed'][-1]
    except Exception as exc:  # noqa: BLE001
        return {'text': '', 'is_error': True, 'wall_s': round(time.monotonic() - start, 2), 'api_ms': None,
                'ttft_ms': None, 'in': None, 'in_uncached': None, 'cache_read': None, 'cache_write': None,
                'out': None, 'call_error': type(exc).__name__}
    wall = time.monotonic() - start
    return {'text': text, 'is_error': False, 'wall_s': round(wall, 2), 'api_ms': round(wall * 1000), 'ttft_ms': None,
            'in': u['input_tokens'], 'in_uncached': u['input_tokens'] - u.get('cached_input_tokens', 0),
            'cache_read': u.get('cached_input_tokens', 0), 'cache_write': u.get('cache_write_input_tokens', 0),
            'out': u['output_tokens'], 'reasoning': u.get('reasoning_output_tokens')}


# Pin full model ids: the bare 'haiku' alias resolved to claude-haiku-4-5, not 5.5.
MODEL_IDS = {'sonnet': 'claude-sonnet-5-5', 'opus': 'claude-opus-5-5', 'haiku': 'claude-haiku-5-5',
             'fable': 'claude-fable-5-1'}


def call(prompt, system=None):
    if os.environ.get('MODEL', '').startswith('codex:'):
        return call_codex(prompt, os.environ['MODEL'][6:])
    start = time.monotonic()
    try:
        proc = subprocess.run([CLAUDE, '-p', '--model', MODEL_IDS.get(os.environ.get('MODEL', 'sonnet'), os.environ.get('MODEL', 'sonnet')), *(['--effort', os.environ['EFFORT']] if os.environ.get('EFFORT') else []), '--system-prompt', system or SYSTEM, '--tools', '',
                               '--setting-sources', '', '--strict-mcp-config', '--no-session-persistence',
                               '--output-format', 'json'], input=prompt, capture_output=True, text=True,
                              encoding='utf-8', cwd=LIVE, timeout=300)
        data = json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, ValueError) as exc:
        # A hung or unparsable call is a failed attempt; usage is unknown, so it is
        # recorded as such and never as zero-cost success.
        return {'text': '', 'is_error': True, 'wall_s': round(time.monotonic() - start, 2), 'api_ms': None,
                'ttft_ms': None, 'in': None, 'in_uncached': None, 'cache_read': None, 'cache_write': None,
                'out': None, 'call_error': type(exc).__name__}
    wall = time.monotonic() - start
    u = data['usage']
    return {'text': data.get('result', ''), 'is_error': data.get('is_error'), 'wall_s': round(wall, 2),
            'api_ms': data.get('duration_api_ms'), 'ttft_ms': data.get('ttft_ms'),
            'in': u['input_tokens'] + u['cache_creation_input_tokens'] + u['cache_read_input_tokens'],
            'in_uncached': u['input_tokens'], 'cache_read': u['cache_read_input_tokens'],
            'cache_write': u['cache_creation_input_tokens'], 'out': u['output_tokens'],
            'model': ','.join(data.get('modelUsage', {})),
            'thinking': (u.get('output_tokens_details') or {}).get('thinking_tokens')}


def main():
    p08 = {(p['domain'], p['n']): p for p in json.load(open(LIVE / 'p08.json', encoding='utf-8'))}
    seq = int(os.environ.get('RECEIPT_START', '1'))
    plan = []
    for rep in range(REPS):
        for dom in ('materials', 'code'):
            for n in SIZES:
                arms = ['0.8', 'oz9', 'oz9+rule']
                random.Random(f'{rep}{dom}{n}').shuffle(arms)
                plan += [(rep, dom, n, arm) for arm in arms]
    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            done.add((r['rep'], r['domain'], r['n'], r['arm']))
            seq = max(seq, r.get('seq', 0) + 1)
    for rep, dom, n, arm in plan:
        if (rep, dom, n, arm) in done:
            continue
        receipt = b36(seq)
        if arm == '0.8':
            p = p08[(dom, n)]
            ids, prompt, ptok, mode = p['ids'], p['prompt'], p['tokens'], p['mode']
        else:
            ids, prompt, ptok, mode = packets09(dom, n, receipt, arm == 'oz9+rule')
        r = call(prompt)
        value, strict = parse(r['text'])
        valid, err, outcomes = False, '', {}
        try:
            if arm == '0.8':
                outcomes = results08(value, ids)
            else:
                outcomes = validate_reply(value, ids, receipt)
            valid = True
        except Exception as exc:  # noqa: BLE001 - recorded, not raised
            err = str(exc)[:120]
        rec = {'seq': seq, 'rep': rep, 'domain': dom, 'n': n, 'arm': arm, 'mode': mode, 'packet_o200k': ptok,
               'receipt': receipt if arm != '0.8' else None, 'strict_json': strict, 'valid': valid, 'error': err,
               'outcomes': {k: list(v) for k, v in outcomes.items()}, **r}
        with OUT.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        print(seq, dom, n, arm, 'valid' if valid else 'INVALID ' + err, 'in', r['in'], 'out', r['out'],
              'api_ms', r['api_ms'], flush=True)
        seq += 1


if __name__ == '__main__':
    main()
