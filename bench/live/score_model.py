"""Score live6 (0.8-exec, F frames) + live7 (F direct-ids) for one model. One fence stripped for every arm."""
import json, re, sys, statistics as st, tiktoken
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, '.')
import live6 as X
FENCE = re.compile(r'\s*```(?:json)?\s*(.*?)\s*```\s*', re.S)
enc = tiktoken.get_encoding('o200k_base')
tag = sys.argv[1]
rows = [json.loads(l) for l in open(X.V.LIVE / 'data' / f'live6_{tag}.jsonl', encoding='utf-8')]
rows += [json.loads(l) for l in open(X.V.LIVE / 'data' / f'live7_{tag}.jsonl', encoding='utf-8')]
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
print(f'{tag}: arm | valid | correct | in/call | billed out/call | visible out | total/call | vs 0.8 | median')
for n in (32, 64):
    base = None
    for a in ('0.8-exec', 'F', 'F-direct'):
        v = [r for r in rows if r['arm'] == a and r['n'] == n and r['in'] is not None]
        if not v: continue
        s = [score(r) for r in v]
        I = sum(r['in'] for r in v) / len(v); O = sum(r['out'] for r in v) / len(v)
        vis = sum(len(enc.encode(r['text'])) for r in v) / len(v)
        if a == '0.8-exec': base = I + O
        print(f"  n={n} {a:8} | {sum(x[0] for x in s)}/{len(v)} | {sum(x[1] for x in s)}/{n*len(v)} | {I:.0f} | {O:.0f} | {vis:.0f} | {I+O:.0f} | {(I+O)/base-1:+.0%} | {st.median(r['api_ms'] for r in v)/1000:.1f}s")
