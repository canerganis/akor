"""Re-score saved live6-style replies with the same fence rule for both arms."""
import json, re, sys, statistics as st
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, '.')
import live6 as X
FENCE = re.compile(r'\s*```(?:json)?\s*(.*?)\s*```\s*', re.S)
rows = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
OV = int(sys.argv[2])
def score(r, lenient):
    text = r['text']
    fenced = bool(FENCE.fullmatch(text))
    if lenient and fenced:
        text = FENCE.fullmatch(text).group(1)
    js = X.V.jobs('materials', r['n'])
    try:
        if r['arm'] == '0.8-exec':
            value = json.loads(text)
            ids = [f'ma_{i + 1:02d}' for i in range(r['n'])]
            out = X.L.results08(value, ids)
            return True, fenced, sum(out[i][0] == 'ok' and X.check(j, out[i][1], False) for i, j in zip(ids, js))
        dec = X.T.decode('F', text, r['n'])
        return True, fenced, sum(ok and X.check(j, v, True) for (ok, v), j in zip(dec, js))
    except Exception:
        return False, fenced, 0
for lenient in (False, True):
    print('lenient (one fence stripped for both arms)' if lenient else 'strict (no fence allowed for either arm)')
    for n in (32, 64):
        for a in ('0.8-exec', 'F'):
            v = [r for r in rows if r['arm'] == a and r['n'] == n]
            s = [score(r, lenient) for r in v]
            I = sum(r['in'] for r in v); O = sum(r['out'] for r in v)
            print(f"  n={n} {a:8} valid {sum(x[0] for x in s)}/{len(v)} fenced {sum(x[1] for x in s)} jobs {sum(x[2] for x in s)}/{n*len(v)} "
                  f"in/call {I/len(v):.0f} out/call {O/len(v):.0f} total/call {(I+O)/len(v):.0f} median {st.median(r['api_ms'] for r in v)/1000:.1f}s")
