"""Step-2 integration pilot (docs/design/brainstorm-2026-10-22/pilot-plan.md).

Same 16 materials jobs per seed, four ways:
  H   one OZ/1g call with all 16 jobs
  J   one plain JSON call with all 16 jobs (0.8-exec, the batched control)
  P   16 plain JSON calls, one job each (one call per job), run one after another
  Q   16 OZ/1g calls, one job each (the H body cut to that job's op and ref)
  S   one orchestrator call that must spawn one subagent per job (Agent tool), then reply in the 0.8 format
Tokens are summed from modelUsage, which includes subagents; the CLI's `usage` field covers only the last
turn. Every reply is judged strictly by the same oracles; nothing is repaired. Calls go through bench/harness.py
(pinned subagent model, model check, shared caps in OUT.ledger.sqlite: MAX_LAUNCHES, MAX_TOKENS, RESERVE). An S call
counts as delegated only when each job went to one subagent whose call succeeded (delegation_ok).
Usage: OUT=pilot2_sonnet.jsonl python bench/live/pilot2.py
"""
import hashlib, json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import live11 as M
import run_live as L
from bench import harness as HX
import oz_reply

N = int(os.environ.get('N', '16'))
lo, hi = map(int, os.environ.get('SEEDS', '3005-3007').split('-'))
SEEDS = list(range(lo, hi + 1))
ARMS = os.environ.get('ARMS', 'H,J,P,S').split(',')
MODEL = L.MODEL_IDS[os.environ.get('MODEL', 'sonnet')]
OUT = M.X.V.LIVE / 'data' / os.environ.get('OUT', 'pilot2_sonnet.jsonl')
LEDGER = HX.Ledger(OUT.with_suffix('.ledger.sqlite'), max_launches=int(os.environ.get('MAX_LAUNCHES', '800')),
                   max_tokens=int(os.environ.get('MAX_TOKENS', '8000000')), reserve=int(os.environ.get('RESERVE', '600000')))
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
    """One live call through bench/harness.py: pinned model for subagents too, a call that used another model or has
    no result is a failure, and missing usage stays None. Fields kept from the first pilots."""
    c = HX.run_charged(LEDGER, lambda: HX.call(system or L.SYSTEM, prompt, model=MODEL, kind='live', tools=tools,
                                                cwd=L.LIVE))
    if c is None:
        raise SystemExit(f'stopped before a launch: {LEDGER.refusal()}')
    u = c['usage'] or {}
    return {'text': c['text'], 'is_error': bool(c['failure']), 'failure': c['failure'], 'wall_s': c['seconds'],
            'api_ms': c['api_ms'], 'in': u.get('input_tokens'), 'in_uncached': u.get('uncached_input_tokens'),
            'cache_read': u.get('cached_input_tokens'), 'cache_write': u.get('cache_write_tokens'),
            'out': u.get('output_tokens'), 'thinking': u.get('thinking_tokens'), 'model': ','.join(c['models']),
            'spawns': c['spawns'], 'turns': c['turns'], 'delegations': c['delegations']}


def delegation_ok(delegations, n) -> bool:
    """True when every subagent call came back without error and names exactly one message ID, and the calls cover
    the n IDs once each."""
    named = [set(re.findall(r'\bma_\d{2}\b', json.dumps(d['input'], ensure_ascii=False))) for d in delegations]
    return (all(d['ok'] for d in delegations) and all(len(x) == 1 for x in named)
            and sorted(x.pop() for x in named) == [f'ma_{i + 1:02d}' for i in range(n)])


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
    if arm == 'Q':
        # One OZ/1g call per job: the same body cut to that job's op and ref.
        system, user, _, native = M.ARMS['H'](N)
        body = json.loads(user)
        out = []
        for block in body['jobs']:
            op = body['ops'][block[0]]
            for job, ref in block[1:]:
                one = dict(body, ops=[op], refs=[body['refs'][ref]], jobs=[[0, [job, 0]]])
                text = json.dumps(one, ensure_ascii=False, separators=(',', ':'))
                out.append((system, text, '', lambda reply, job=job: M.stage1g_flat(reply, [job], header=True), native, [job]))
        out.sort(key=lambda c: js.index(c[5][0]))
        return out
    system, user, dec, native = M.ARMS['0.8-exec'](N)
    if arm == 'J':
        return [(system, user, '', dec, native, js)]
    if arm == 'S':
        return [(system, S_TEXT + user, 'Agent', dec, native, js)]
    ids = [f'ma_{i + 1:02d}' for i in range(N)]
    out = []
    for i in range(N):
        def dec1(reply, i=i):
            r = L.results08(oz_reply.loads(reply), [ids[i]])
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
            err, ok = ('call: ' + r['failure'], 0) if r['failure'] else judge(dec, r['text'], js, native)
            d = r.pop('delegations')
            rec = {'seq': seq, 'part': k, 'seed': seed, 'arm': a, 'valid': not err, 'error': err, 'jobs_passed': ok,
                   'jobs': len(js), 'manifest': man['sha256'], **r,
                   **({'delegation_ok': delegation_ok(d, len(js)),
                       'delegations': [[x['id'], x['ok'], x['input']] for x in d]} if a == 'S' else {})}
            with OUT.open('a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            print(seq, k, seed, a, 'ok' if not err else 'FAIL ' + err, f'{ok}/{len(js)}', 'in', r['in'], 'out', r['out'],
                  'spawns', r.get('spawns'), 'wall', r['wall_s'], flush=True)


if __name__ == '__main__':
    main()
