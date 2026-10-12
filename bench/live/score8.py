import json, re, sys, statistics as st, tiktoken
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, '.')
import live6 as X
FENCE = re.compile(r'\s*```(?:json)?\s*(.*?)\s*```\s*', re.S)
enc = tiktoken.get_encoding('o200k_base')
tag = sys.argv[1]
rows = [json.loads(l) for l in open(X.V.LIVE / 'data' / f'live8_{tag}.jsonl', encoding='utf-8')]
base = {}
for f in (f'live6_{tag}.jsonl', f'live7_{tag}.jsonl'):
    p = X.V.LIVE / f
    if p.exists():
        rows += [json.loads(l) for l in open(p, encoding='utf-8')]
def score(r):
    t = r['text']; m = FENCE.fullmatch(t); t = m.group(1) if m else t
    js = X.V.jobs('materials', r['n'])
    try:
        if r['arm'] == '0.8-exec':
            ids = [f'ma_{i + 1:02d}' for i in range(r['n'])]
            out = X.L.results08(json.loads(t), ids)
            return True, sum(out[i][0] == 'ok' and X.check(j, out[i][1], False) for i, j in zip(ids, js))
        return True, sum(ok and X.check(j, v, True) for (ok, v), j in zip(X.T.decode('F', t, r['n']), js))
    except Exception:
        return False, 0
print(f'{tag}: arm | valid | correct | packet | in/call | billed out | visible out | hidden ratio | total | vs 0.8 | median')
for n in (32, 64):
    b = None
    for a in ('0.8-exec', 'F', 'F-direct', 'R1', 'R2', 'R3'):
        v = [r for r in rows if r['arm'] == a and r['n'] == n and r['in'] is not None]
        if not v: continue
        s = [score(r) for r in v]
        I = sum(r['in'] for r in v) / len(v); O = sum(r['out'] for r in v) / len(v)
        vis = sum(len(enc.encode(r['text'])) for r in v) / len(v)
        pk = sum(r.get('packet_o200k', 0) for r in v) / len(v)
        if a == '0.8-exec': b = I + O
        print(f"  n={n} {a:8} | {sum(x[0] for x in s)}/{len(v)} | {sum(x[1] for x in s)}/{n*len(v)} | {pk:.0f} | {I:.0f} | {O:.0f} | {vis:.0f} | {O/vis:.1f}x | {I+O:.0f} | {(I+O)/b-1:+.0%} | {st.median(r['api_ms'] for r in v)/1000:.1f}s")
