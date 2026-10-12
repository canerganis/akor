"""Haiku: OZ/9 direct-ids form (meaning written into each job, [N] -> c[N]) on the distinct workload."""
import json, os, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, '.')
import live6 as X
import oz_batch
OUT = X.V.LIVE / 'data' / os.environ.get('OUT', 'live7_haiku.jsonl')


def packet_direct(n):
    goal, C, D, _ = X.V.DOMAINS['materials']
    js = X.V.jobs('materials', n)
    used = sorted({j[1:] for j in js}, key=int)
    jobs = [D[j[0]].replace('c[N]', f'[{j[1:]}]') if 'c[N]' in D[j[0]] else f'[{j[1:]}] ' + D[j[0]] for j in js]
    body = {'c': {k: C[k] for k in used}, 'goal': goal, 'j': jobs}
    return oz_batch.PREAMBLE + ' ' + oz_batch.PROFILES['direct-ids'] + '\n' + oz_batch.REPLY_CONTRACT + '\n' + X.V.J(body) + '\n'


def main():
    seq = 0
    for rep in range(3):
        for n in (32, 64):
            prompt = packet_direct(n)
            r = X.L.call(prompt)
            rec = {'seq': seq, 'rep': rep, 'n': n, 'arm': 'F-direct', 'packet_o200k': X.L.count(prompt), **r}
            with OUT.open('a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            print(seq, n, 'in', r['in'], 'out', r['out'], 'api_ms', r['api_ms'], flush=True)
            seq += 1


if __name__ == '__main__':
    print(packet_direct(4)) if os.environ.get('SHOW') else main()
