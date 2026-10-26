"""Measurement-only rescore of the P arm (one call per job) of pilot2_*64.jsonl: a reply the strict decoder
rejected is re-judged on its last {"results": ...} object after removing Markdown fences. Never used by the product;
it separates format failures (prose or a fence around the JSON) from wrong answers.
Usage: N=64 python bench/live/pilot2_lenient.py
"""
import json, re, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import pilot2 as T
def last_obj(t):
    t = re.sub(r'```(?:json)?', '', t)
    for i in [m.start() for m in re.finditer(r'\{', t)]:
        try:
            v, end = json.JSONDecoder().raw_decode(t[i:])
            if isinstance(v, dict) and 'results' in v and not t[i+end:].strip(): return json.dumps(v)
        except ValueError: pass
    return None
for m in ['sonnet','opus','haiku','fable']:
    R=[json.loads(l) for l in open(f'bench/live/data/pilot2_{m}64.jsonl',encoding='utf-8')]
    cache={}
    strict=len_ok=fmt_fail=fmt_fixed=0; tok=0; H=[0,0]
    for r in R:
        if r['arm']=='H': H[0]+=r['in']+r['out']; H[1]+=r['jobs_passed']
        if r['arm']!='P': continue
        tok+=r['in']+r['out']; strict+=r['jobs_passed']
        if r['seed'] not in cache: cache[r['seed']]=T.calls(r['seed'],'P')
        _,_,_,dec,native,js=cache[r['seed']][r['part']]
        if r['error']:
            fmt_fail+=1; t=last_obj(r['text'] or '')
            if t:
                e,ok=T.judge(dec,t,js,native); len_ok+=ok; fmt_fixed+= (not e)
        else: len_ok+=r['jobs_passed']
    h=H[0]/H[1]
    print(m,'P strict',strict,'lenient',len_ok,'format fails',fmt_fail,'recovered',fmt_fixed,
          'tok/verified strict',round(tok/strict),'lenient',round(tok/len_ok),'H',round(h,1),
          'P/H strict',round(tok/strict/h,1),'lenient',round(tok/len_ok/h,1),'per requested',round(tok/192/h,1))
