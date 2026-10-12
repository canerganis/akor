"""Live validity of reply-contract wordings on OZ/9 packets (Sonnet). Inline-q variants drop q from the body."""
import json, os, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, '.')
import run_live as L
import oz_batch
A = oz_batch.REPLY_CONTRACT
C = {'A': A,
     'K2': 'Reply only JSON array ["{q}","result",...]: one nonblank result per j, in order; [1,"text"]=retryable, [2,"text"]=permanent failure.',
     'K3': 'Reply only JSON array ["{q}",result per j in order]; result "text", or [1,"text"] retryable / [2,"text"] permanent failure.'}
OUT = L.LIVE / 'data' / 'contract.jsonl'
names = os.environ.get('NAMES', 'A,K2,K3').split(',')
seq = 100
done = set()
if OUT.exists():
    for line in OUT.read_text(encoding='utf-8').splitlines():
        r = json.loads(line); done.add((r['rep'], r['domain'], r['n'], r['arm'])); seq = max(seq, r['seq'] + 1)
plan = [(rep, dom, n, k) for rep in range(int(os.environ.get('REPS', '2'))) for dom in ('materials', 'code')
        for n in (1, 4) for k in random.Random(f'{rep}{dom}{n}').sample(names, len(names))]
for rep, dom, n, k in plan:
    if (rep, dom, n, k) in done:
        continue
    q = L.b36(seq)
    ids, text, _, mode = L.packets09(dom, n, q, False)
    if k != 'A':
        text = text.replace(A, C[k].replace('{q}', q)).replace(f',"q":"{q}"', '').replace(f'"q":"{q}",', '')
    ptok = L.count(text)
    r = L.call(text)
    value, strict = L.parse(r['text'])
    try:
        L.validate_reply(value, ids, q); valid, err = True, ''
    except Exception as exc:
        valid, err = False, str(exc)[:80]
    rec = {'seq': seq, 'rep': rep, 'domain': dom, 'n': n, 'arm': k, 'mode': mode, 'packet_o200k': ptok, 'strict_json': strict,
           'valid': valid, 'error': err, **r}
    with OUT.open('a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(seq, dom, n, k, ptok, 'valid' if valid else 'INVALID', repr(r['text'][:60]), 'out', r['out'], flush=True)
    seq += 1
