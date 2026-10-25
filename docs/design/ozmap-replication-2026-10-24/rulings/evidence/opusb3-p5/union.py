"""Opus B 3: is prewarm items + incremental turn items equal to the approved list (content), and which fields differ."""
import json, sys
from pathlib import Path
sys.path.insert(0, r'C:\Users\can02\Projects\akor')
from bench.ozmap_rep import effective_context as ec
p = Path(sys.argv[1])
d = json.loads(p.read_text(encoding='utf-8'))
frames = json.loads((p.parent / (p.stem + '.frames.json')).read_text(encoding='utf-8'))
pre, turn = frames[0], frames[1]
appr = ec.load()
dp, pp = ec.describe(pre, d['prompt'], 'websocket_prewarm')
t2 = dict(turn); prev = t2.pop('previous_response_id')
dt, pt = ec.describe(t2, d['prompt'], 'websocket')
print('describe problems', pp, pt)
union = dp['items'] + dt['items']
print('prewarm + delta items == approved items:', union == appr['items'], len(union), len(appr['items']))
print('turn top level (without previous_response_id) == approved:', dt['top_level'] == appr['top_level'])
if dt['top_level'] != appr['top_level']:
    a, b = appr['top_level'], dt['top_level']
    print('   diff', {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)})
print('turn client metadata keys', dt['client_metadata']['keys'])
print('approved websocket client metadata keys', appr['client_metadata']['websocket']['keys'])
print('metadata values turn', dt['client_metadata']['values'])
print('metadata values approved', appr['client_metadata']['websocket']['values'])
print('previous_response_id', prev)
print('user item is exact stdin:', dt['items'][-1])
