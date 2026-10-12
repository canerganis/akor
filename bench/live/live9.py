"""Effort sweep: 0.8-exec vs an OZ form at one effort level (EFFORT env), distinct workload, 32/64 jobs."""
import json, os, random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, '.')
import live6 as X
import live8 as R

OUT = X.V.LIVE / 'data' / os.environ['OUT']
FORM = os.environ.get('FORM', 'R1')


def prompt_for(arm, n):
    if arm == '0.8-exec':
        return X.V.packet_08('materials', n)[1]
    if arm == 'F':
        return X.T.packet('materials', n, 'F')
    return R.packet(arm, n)


def main():
    seq = 0
    arms = ['0.8-exec', FORM]
    for rep in range(int(os.environ.get('REPS', '3'))):
        for n in (32, 64):
            for arm in random.Random(f'9{rep}{n}').sample(arms, 2):
                p = prompt_for(arm, n)
                r = X.L.call(p)
                rec = {'seq': seq, 'rep': rep, 'n': n, 'arm': arm, 'effort': os.environ.get('EFFORT'),
                       'packet_o200k': X.L.count(p), **r}
                with OUT.open('a', encoding='utf-8') as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                print(seq, n, arm, 'in', r['in'], 'out', r['out'], 'api_ms', r['api_ms'], flush=True)
                seq += 1


if __name__ == '__main__':
    main()
