"""Run from the extracted 0.8 tree: emit 0.8 packets (rows reply contract) as JSON."""
import json, sys
sys.path.insert(0, sys.argv[1])
import tiktoken
from oz2_benchmark import WORK, scenario
from oz_batch import render
from oz_worker import RESPONSE_CONTRACT
enc = tiktoken.get_encoding('o200k_base'); c = lambda s: len(enc.encode(s, disallowed_special=()))
out = []
for dom in ('materials', 'code'):
    ch = scenario(dom)
    for n in map(int, sys.argv[2].split(',')):
        ids = [f'{dom[:2]}_{i + 1:02d}' for i in range(n)]
        b = render(ch, list(zip(ids, (WORK[i % len(WORK)] for i in range(n)))), counters=[c], response_contract=RESPONSE_CONTRACT)
        out.append({'arm': '0.8', 'domain': dom, 'n': n, 'ids': ids, 'prompt': b.text, 'tokens': b.tokens[0], 'mode': b.mode})
json.dump(out, sys.stdout, ensure_ascii=False)
