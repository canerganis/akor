"""Summarize pilot2_*.jsonl: tokens per verified job, cache share, wall time per seed, per model and arm.

Only records carrying the manifest's hash count. A cell gets per-job figures and a ratio only when it is complete,
every counter is a non-negative int, every call reports exactly the pinned model, S calls proved one successful
subagent per job, and the file's ledger (when there is one) has no launch without a record."""
import json, sqlite3, statistics, sys
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).parent / 'data'
NAMES = {'H': 'OZ/1g, one call', 'J': 'plain JSON, one call', 'P': 'plain JSON, one call per job',
         'S': 'one subagent per job', 'Q': 'OZ/1g, one call per job'}


def coverage(rows, man) -> dict:
    """{arm: True} when every (seed, part) the manifest schedules is recorded exactly once with the manifest hash:
    H, J and S are one call per seed, P and Q one call per job. Records of other runs are ignored (main flags them)."""
    seen = defaultdict(list)
    for r in rows:
        if r.get('manifest') == man['sha256']:
            seen[(r['seed'], r['arm'])].append(r['part'])
    ok = defaultdict(lambda: True)
    for seed, arm in man['schedule']:
        want = list(range(man['n'])) if arm in 'PQ' else [0]
        ok[arm] = ok[arm] and sorted(seen.pop((seed, arm), [])) == want
    for _, arm in seen:  # records the manifest does not schedule
        ok[arm] = False
    return ok


def _count(v) -> bool:
    return type(v) is int and v >= 0


def price(r):
    """Relative money units at Claude list ratios: uncached input 1, cache write 1.25, cache read 0.1, output 5."""
    parts = (r.get('in_uncached'), r.get('cache_write'), r.get('cache_read'), r.get('out'))
    return None if not all(_count(v) for v in parts) else parts[0] + 1.25 * parts[1] + 0.1 * parts[2] + 5 * parts[3]


def ledger_gap(f, rows) -> int | None:
    """Launches in the file's ledger without a record (a call paid for but never written), or None with no ledger."""
    path = f.with_suffix('.ledger.sqlite')
    if not path.exists():
        return None
    con = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
    try:
        return max(0, con.execute('SELECT COUNT(*) FROM launch').fetchone()[0] - rows)
    finally:
        con.close()


def main(files):
    """A call without usage makes its arm inconclusive (no token figure), never a zero. Any flag withholds the
    per-job figures and the ratio of that cell."""
    print('| Model | Arm | Calls | Replies accepted | Correct jobs | Tokens | Cache reads | Tokens per requested job | '
          'Tokens per verified job | Seed range per verified job | Cost units per verified job | x H per requested job | '
          'Median s per seed (all jobs) | Median API s per seed | Flags |')
    print('|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|')
    for f in files:
        R = [json.loads(l) for l in f.read_text(encoding='utf-8').split('\n') if l.strip()]  # LF only
        man = json.loads(f.with_suffix('.manifest.json').read_text(encoding='utf-8'))
        pinned = man['model']
        model = pinned + ('' if pinned.split('-')[1] in f.stem else f' (file {f.name})')  # the manifest names the model
        gap = ledger_gap(f, len(R))
        g, other = defaultdict(list), defaultdict(int)
        for r in R:
            if r.get('manifest') == man['sha256']:
                g[r['arm']].append(r)
            else:
                other[r['arm']] += 1
        complete = coverage(R, man)
        h_per_job = None
        for arm in 'HJPQS':
            X = g.get(arm)
            if not X:
                continue
            flags = []
            unknown = sum(1 for r in X if not (_count(r.get('in')) and _count(r.get('out'))))
            mixed = sum(1 for r in X if r.get('model') != pinned)  # missing or empty model counts too
            if other[arm]:
                flags.append(f'{other[arm]} record(s) from another run ignored')
            if gap:
                flags.append(f'{gap} ledger launch(es) without a record')
            if unknown:
                flags.append(f'{unknown} call(s) without usage: tokens inconclusive')
            if mixed:
                flags.append(f'{mixed} call(s) used another model')
            if not complete[arm]:
                flags.append('incomplete or duplicated calls')
            short = sum(1 for r in X if r.get('delegation_ok') is not True) if arm == 'S' else 0
            if short:
                flags.append(f'{short} call(s) without proven one-subagent-per-job delegation')
            tok = None if unknown else sum(r['in'] + r['out'] for r in X)
            cr = None if not all(_count(r.get('cache_read')) for r in X) else sum(r['cache_read'] for r in X)
            ok = sum(r['jobs_passed'] for r in X)
            jobs = sum(r['jobs'] for r in X)
            per_seed, api_seed, seed_tok, seed_ok = (defaultdict(float), defaultdict(float), defaultdict(int),
                                                     defaultdict(int))
            for r in X:
                per_seed[r['seed']] += r['wall_s'] if isinstance(r.get('wall_s'), (int, float)) else float('nan')
                api_seed[r['seed']] += r['api_ms'] / 1000 if _count(r.get('api_ms')) else float('nan')
                seed_ok[r['seed']] += r['jobs_passed']
                if tok is not None:
                    seed_tok[r['seed']] += r['in'] + r['out']
            money = [price(r) for r in X]
            eligible = complete[arm] and not mixed and not unknown and not short and not gap
            fmt = lambda v: 'n/a' if v is None else f'{v:,.1f}'
            per_job = tok / jobs if eligible else None  # every per-job figure needs a clean cell
            per_ver = tok / ok if eligible and ok else None
            spread = [seed_tok[s] / seed_ok[s] if seed_ok[s] else float('inf') for s in per_seed] if eligible else []
            cost = sum(money) / ok if eligible and ok and None not in money else None
            if arm == 'H':
                h_per_job = per_job
            ratio = None if per_job is None or not h_per_job else per_job / h_per_job
            med = lambda d: 'n/a' if not d or any(v != v for v in d.values()) else f'{statistics.median(d.values()):.1f}'
            print(f"| {model} | {NAMES[arm]} | {len(X)} | {sum(r['valid'] for r in X)}/{len(X)} | {ok}/{jobs} | "
                  f"{'n/a' if tok is None else f'{tok:,}'} | {'n/a' if cr is None else f'{cr:,}'} | {fmt(per_job)} | "
                  f"{fmt(per_ver)} | {f'{min(spread):,.1f} to {max(spread):,.1f}' if spread else 'n/a'} | "
                  f"{fmt(cost)} | {fmt(ratio)} | {med(per_seed)} | {med(api_seed)} | {'; '.join(flags)} |")


if __name__ == '__main__':
    main([Path(p) for p in sys.argv[1:]] or sorted(DATA.glob('pilot2_[!s]*.jsonl')) + sorted(DATA.glob('pilot2_sonnet*.jsonl')))
