"""Summarize pilot2_*.jsonl: tokens per verified job, cache share, wall time per seed, per model and arm."""
import json, statistics, sys
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).parent / 'data'
NAMES = {'H': 'OZ/1g, one call', 'J': 'plain JSON, one call', 'P': 'plain JSON, one call per job',
         'S': 'one subagent per job'}


def main(files):
    print('| Model | Arm | Calls | Replies accepted | Correct jobs | Tokens | Cache reads | Tokens per requested job | Tokens per verified job | Median s per 16 jobs |')
    print('|---|---|---:|---:|---:|---:|---:|---:|---:|---:|')
    for f in files:
        R = [json.loads(l) for l in open(f, encoding='utf-8')]
        model = f.stem.split('_', 1)[1]
        g = defaultdict(list)
        for r in R:
            g[r['arm']].append(r)
        for arm in 'HJPS':
            X = g.get(arm)
            if not X:
                continue
            tok = sum((r['in'] or 0) + (r['out'] or 0) for r in X)
            cr = sum(r.get('cache_read') or 0 for r in X)
            ok = sum(r['jobs_passed'] for r in X)
            jobs = sum(r['jobs'] for r in X)
            per_seed = defaultdict(float)
            for r in X:
                per_seed[r['seed']] += r['wall_s'] or 0
            print(f"| {model} | {NAMES[arm]} | {len(X)} | {sum(r['valid'] for r in X)}/{len(X)} | {ok}/{jobs} | {tok:,} | "
                  f"{cr:,} | {tok / jobs:,.1f} | {tok / ok if ok else float('nan'):,.1f} | {statistics.median(per_seed.values()):.1f} |")


if __name__ == '__main__':
    main([Path(p) for p in sys.argv[1:]] or sorted(DATA.glob('pilot2_[!s]*.jsonl')) + sorted(DATA.glob('pilot2_sonnet*.jsonl')))
