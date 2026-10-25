"""Opus B 3: independent raw checks (no effective_context code): base instructions from the pinned catalog,
WebSocket full turn vs HTTP body vs incremental union, and owner markers in every frame."""
import hashlib, json, re
from pathlib import Path
R = Path(r'C:\Users\can02\Projects\akor')
P = Path(r'C:\Users\can02\AppData\Local\Temp\claude\C--Users-can02-Projects-akor\4bd0413f-bf62-4dbc-94ba-cf58fbdc1707\scratchpad')
cat = json.loads((R / 'bench/ozmap_rep/model-catalog.json').read_text(encoding='utf-8'))
m = [x for x in cat['models'] if x.get('slug') == 'gpt-6.1-sol'][0]
appr = json.loads((R / 'bench/ozmap_rep/effective-context.json').read_text(encoding='utf-8'))
def strip(it):
    it = {k: v for k, v in it.items() if k not in ('id', 'internal_chat_message_metadata_passthrough')}
    return json.dumps(it, sort_keys=True, ensure_ascii=False)
def body(path, kind):
    d = json.loads(Path(path).read_text(encoding='utf-8'))
    out = []
    for c in d['captured']:
        for f in c.get('ws_frames', []):
            if f['opcode'] == 1:
                out.append(('ws', json.loads(f['text'])))
        if c['method'] == 'POST' and c['path'].endswith('/responses'):
            out.append(('http', json.loads(c['body'])))
    return d, out
d1, ws = body(P / 'p5c/out/ws_no_auth.json', 'ws')
d2, ht = body(P / 'p5c/out/http_no_auth.json', 'http')
d3, inc = body(P / 'opusb3/out/ws_prewarm_ok_no_auth.json', 'ws')
full = ws[1][1]['input']; http = ht[0][1]['input']
base = full[1]['content'][0]['text']
print('base instructions chars', len(base), 'sha', hashlib.sha256(base.encode()).hexdigest()[:16])
for k in ('base_instructions',):
    v = m.get(k)
    print('catalog', k, type(v).__name__, len(v) if isinstance(v, str) else '', 'equal' if v == base else 'not equal')
mm = m.get('model_messages') or {}
print('catalog instructions_template present', isinstance(mm.get('instructions_template'), str))
print('approved item 1 sha', appr['items'][1]['content'][0]['sha256'][:16])
def envnorm(s, cwd):
    s = s.replace(cwd, '{cwd}')
    s = re.sub(r'<current_date>[^<]*</current_date>', '', s)
    return re.sub(r'<timezone>[^<]*</timezone>', '', s)
def norm(items, cwd):
    out = []
    for it in items:
        s = strip(it)
        out.append(envnorm(s, json.dumps(cwd)[1:-1]) if 'environment_context' in s else s)
    return out
a = norm(full, d1['workdir']); b = norm(http, d2['workdir'])
u = norm(inc[0][1]['input'] + inc[1][1]['input'], d3['workdir'])
print('ws full turn == http body (raw, ids and metadata stripped):', a == b)
print('incremental union == ws full turn (raw):', u == a)
blob = json.dumps([x[1] for x in ws + ht + inc], ensure_ascii=False)
for pat in [r'can02', r'\.agents', r'skills_instructions', r'Projects\\akor', r'CLAUDE\.md', r'P5_MODELS_CANARY']:
    print('pattern', pat, len(re.findall(pat, blob)))
print('incremental frame previous_response_id', inc[1][1].get('previous_response_id'), 'tools in delta', any(i.get('type') == 'additional_tools' for i in inc[1][1]['input']))
