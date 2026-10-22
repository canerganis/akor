"""Step-2 integration pilot (docs/design/brainstorm-2026-10-22/pilot-plan.md).

Same 16 materials jobs per seed, four ways:
  H   one OZ/1g call with all 16 jobs
  J   one plain JSON call with all 16 jobs (0.8-exec, the batched control)
  P   16 plain JSON calls, one job each (one call per job), run one after another
  S   one orchestrator call that must spawn one subagent per job (Agent tool), then reply in the 0.8 format
Tokens are summed from modelUsage, which includes subagents; the CLI's `usage` field covers only the last
turn. Every reply is judged strictly by the same oracles; nothing is repaired.
Usage: OUT=pilot2_sonnet.jsonl python bench/live/pilot2.py
"""
import hashlib, json, os, re, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import live11 as M
import run_live as L

N = int(os.environ.get('N', '16'))
lo, hi = map(int, os.environ.get('SEEDS', '3005-3007').split('-'))
SEEDS = list(range(lo, hi + 1))
ARMS = os.environ.get('ARMS', 'H,J,P,S').split(',')
MODEL = L.MODEL_IDS[os.environ.get('MODEL', 'sonnet')]
OUT = M.X.V.LIVE / 'data' / os.environ.get('OUT', 'pilot2_sonnet.jsonl')
S_TEXT = ('Orchestrate the jobs below. For each message ID, spawn exactly one subagent with the Agent tool '
          '(subagent_type general-purpose) and give it the goal, that one message and the reference it names. '
          'Do not answer any job yourself; use only what the subagents return. When all are back, reply with the '
          'final JSON only, in the format stated at the end.\n\n')


def single(text, i):
    """The 0.8 packet trimmed to message i and the one reference it names."""
    lines = text.rstrip('\n').split('\n')
    msgs = lines[5:-1]
    msg = msgs[i]
    k = int(re.search(r'[Rr]eference (\d+)', msg).group(1))
    refs = [r for r in json.loads(lines[3]) if r[0] == k]
    return '\n'.join(lines[:3] + [json.dumps(refs, ensure_ascii=False, separators=(',', ':')), lines[4], msg, lines[-1]]) + '\n'


def run(prompt, system=None, tools=''):
    """claude -p with stream-json so subagent spawns can be counted; tokens from modelUsage."""
    start = time.monotonic()
    cmd = [L.CLAUDE, '-p', '--model', MODEL, '--system-prompt', system or L.SYSTEM, '--tools', tools,
           '--setting-sources', '', '--strict-mcp-config', '--no-session-persistence',
           '--output-format', 'stream-json', '--verbose']
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8', cwd=L.LIVE, timeout=900)
    except subprocess.TimeoutExpired:
        return {'text': '', 'is_error': True, 'wall_s': round(time.monotonic() - start, 2), 'in': None, 'out': None,
                'call_error': 'timeout'}
    wall = time.monotonic() - start
    final, spawns = None, 0
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get('type') == 'assistant' and not ev.get('parent_tool_use_id'):
            spawns += sum(1 for b in ev['message'].get('content', []) if b.get('type') == 'tool_use' and b.get('name') in ('Agent', 'Task'))
        if ev.get('type') == 'result':
            final = ev
    if final is None:
        return {'text': '', 'is_error': True, 'wall_s': round(wall, 2), 'in': None, 'out': None, 'call_error': 'no result'}
    mu = final.get('modelUsage') or {}
    tot = lambda f: sum(m.get(f, 0) for m in mu.values())
    return {'text': final.get('result', ''), 'is_error': final.get('is_error'), 'wall_s': round(wall, 2),
            'api_ms': final.get('duration_api_ms'), 'in': tot('inputTokens') + tot('cacheReadInputTokens') + tot('cacheCreationInputTokens'),
            'in_uncached': tot('inputTokens'), 'cache_read': tot('cacheReadInputTokens'), 'cache_write': tot('cacheCreationInputTokens'),
            'out': tot('outputTokens'), 'thinking': tot('thinkingTokens'), 'model': ','.join(mu), 'spawns': spawns,
            'turns': final.get('num_turns'), 'usage_last_turn_in': sum((final.get('usage') or {}).get(f, 0) for f in
                                                                         ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'))}


def judge(dec, reply, js, native):
    try:
        flat = dec(reply)
        return '', sum(g and M.X.check(j, v, native) for (g, v), j in zip(flat, js))
    except Exception as exc:  # noqa: BLE001
        return str(exc)[:200], 0


def calls(seed, arm):
    """[(system, prompt, tools, decoder, native, job ids)] for one arm on one seed."""
    M.use_records(M.make_records(seed))
    js = M.X.V.jobs('materials', N)
    if arm == 'H':
        system, user, dec, native = M.ARMS['H'](N)
        return [(system, user, '', dec, native, js)]
    system, user, dec, native = M.ARMS['0.8-exec'](N)
    if arm == 'J':
        return [(system, user, '', dec, native, js)]
    if arm == 'S':
        return [(system, S_TEXT + user, 'Agent', dec, native, js)]
    ids = [f'ma_{i + 1:02d}' for i in range(N)]
    out = []
    for i in range(N):
        def dec1(reply, i=i):
            r = L.results08(json.loads(reply), [ids[i]])
            return [(r[ids[i]][0] == 'ok', r[ids[i]][1])]
        out.append((system, single(user, i), '', dec1, native, [js[i]]))
    return out


def main():
    plan = [(s, a) for s in SEEDS for a in ARMS]
    h = hashlib.sha256()
    for s, a in plan:
        for system, prompt, tools, *_ in calls(s, a):
            h.update(json.dumps([s, a, system, prompt, tools], ensure_ascii=False).encode('utf-8'))
    man = {'model': MODEL, 'n': N, 'schedule': plan, 'sha256': h.hexdigest(), 'concurrency': 1, 'reply_retry': 0}
    OUT.with_suffix('.manifest.json').write_text(json.dumps(man, indent=1), encoding='utf-8')
    print('manifest', man['sha256'], flush=True)
    for seq, (seed, a) in enumerate(plan):
        for k, (system, prompt, tools, dec, native, js) in enumerate(calls(seed, a)):
            r = run(prompt, system, tools)
            err, ok = judge(dec, r['text'], js, native)
            rec = {'seq': seq, 'part': k, 'seed': seed, 'arm': a, 'valid': not err, 'error': err, 'jobs_passed': ok,
                   'jobs': len(js), 'manifest': man['sha256'], **r}
            with OUT.open('a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            print(seq, k, seed, a, 'ok' if not err else 'FAIL ' + err, f'{ok}/{len(js)}', 'in', r['in'], 'out', r['out'],
                  'spawns', r.get('spawns'), 'wall', r['wall_s'], flush=True)


if __name__ == '__main__':
    main()
