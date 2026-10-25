"""Rewrite each captured zstd body as its decoded JSON text (Python 3.14 compression.zstd)."""
import base64, json, sys
from compression import zstd
p = sys.argv[1]
r = json.load(open(p, encoding='utf-8'))
for c in r['captured']:
    enc = {k.lower(): v for k, v in c['headers'].items()}.get('content-encoding')
    if enc == 'zstd' and c.get('body_b64'):
        c['body'] = zstd.decompress(base64.b64decode(c['body_b64'])).decode('utf-8')
        c['decoded_from'] = 'zstd'
json.dump(r, open(p, 'w', encoding='utf-8'), indent=1)
