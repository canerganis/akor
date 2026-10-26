"""Summarize pilot2_*.jsonl: tokens per verified job, cache share, wall time per seed, per model and arm."""
import json, statistics, sys
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).parent / 'data'
NAMES = {'H': 'OZ/1g, one call', 'J': 'plain JSON, one call', 'P': 'plain JSON, one call per job',
         'S': 'one subagent per job', 'Q': 'OZ/1g, one call per job'}


def coverage(rows, man) -> dict:
    """{arm: True} when every (seed, part) the manifest schedules is recorded exactly once with the manifest hash:
    H, J and S are one call per seed, P and Q one call per job."""
    seen = defaultdict(list)
    for r in rows:
        seen[(r['seed'], r['arm'])].append(r['part'] if r.get('manifest') == man['sha256'] else -1)  # -1: other run
    ok = defaultdict(lambda: True)
    for seed, arm in man['schedule']:
        want = list(range(man['n'])) if arm in 'PQ' else [0]
        ok[arm] = ok[arm] and sorted(seen.pop((seed, arm), [])) == want
    for _, arm in seen:  # records the manifest does not schedule
        ok[arm] = False
    return ok


def main(files):
    """A call without usage makes its arm inconclusive (no token figure), never a zero. A call whose modelUsage names
    another model (a subagent on a different model) is flagged; its arm is not a clean cell for that model."""
    print('| Model | Arm | Calls | Replies accepted | Correct jobs | Tokens | Cache reads | Tokens per requested job | '
          'Tokens per verified job | x H per requested job | Median s per seed (all jobs) | Flags |')
    print('|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|')
    for f in files:
        R = [json.loads(l) for l in open(f, encoding='utf-8')]
        man = json.loads(f.with_suffix('.manifest.json').read_text(encoding='utf-8'))
        pinned = man['model']
        model = pinned + ('' if pinned.split('-')[1] in f.stem else f' (file {f.name})')  # the manifest names the model
        g = defaultdict(list)
        for r in R:
            g[r['arm']].append(r)
        complete = coverage(R, man)
        h_per_job = None
        for arm in 'HJPQS':
            X = g.get(arm)
            if not X:
                continue
            flags = []
            unknown = sum(1 for r in X if r['in'] is None or r['out'] is None)
            mixed = sum(1 for r in X if r.get('model') and r['model'] != pinned)
            if unknown:
                flags.append(f'{unknown} call(s) without usage: tokens inconclusive')
            if mixed:
                flags.append(f'{mixed} call(s) used another model')
            if not complete[arm]:
                flags.append('incomplete or duplicated calls')
            short = sum(1 for r in X if r.get('spawns') != r['jobs']) if arm == 'S' else 0
            if arm == 'S':
                if short:
                    flags.append(f'{short} call(s) did not spawn one subagent per job')
            tok = None if unknown else sum(r['in'] + r['out'] for r in X)
            cr = sum(r.get('cache_read') or 0 for r in X)
            ok = sum(r['jobs_passed'] for r in X)
            jobs = sum(r['jobs'] for r in X)
            per_seed = defaultdict(float)
            for r in X:
                per_seed[r['seed']] += r['wall_s'] or 0
            per_job = None if tok is None else tok / jobs
            if not complete[arm] or mixed or (arm == 'S' and short):
                per_job_for_ratio = None  # incomplete, another model or wrong delegation: no ratio either way
            else:
                per_job_for_ratio = per_job
            if arm == 'H':
                h_per_job = per_job_for_ratio
            fmt = lambda v: 'n/a' if v is None else f'{v:,.1f}'
            ratio = None if per_job_for_ratio is None or not h_per_job else per_job_for_ratio / h_per_job
            print(f"| {model} | {NAMES[arm]} | {len(X)} | {sum(r['valid'] for r in X)}/{len(X)} | {ok}/{jobs} | "
                  f"{'n/a' if tok is None else f'{tok:,}'} | {cr:,} | {fmt(per_job)} | "
                  f"{fmt(tok / ok if tok is not None and ok else None)} | {fmt(ratio)} | "
                  f"{statistics.median(per_seed.values()):.1f} | {'; '.join(flags)} |")


if __name__ == '__main__':
    main([Path(p) for p in sys.argv[1:]] or sorted(DATA.glob('pilot2_[!s]*.jsonl')) + sorted(DATA.glob('pilot2_sonnet*.jsonl')))
