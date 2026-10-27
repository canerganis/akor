"""Gates of the frozen stage-1g test (docs/design/stage-1g-final-decision.md) for one stage-A data file.

Tokens per call = provider input (uncached + cache write + cache read) + output; thinking is inside output, counted once.
C_requested = all tokens / requested jobs; C_verified = all tokens / jobs in fully correct accepted packets.
Usage: python bench/live/gates1g.py live22_1g_A_H.jsonl
"""
import json, statistics, sys
from pathlib import Path

rows = [json.loads(l) for l in (Path(__file__).parent / 'data' / sys.argv[1]).open(encoding='utf-8')]
arms = {}
for r in rows:
    arms.setdefault(r['arm'], []).append(r)


def price(r):
    """Relative money units at Sonnet list ratios: input 1, cache write 1.25, cache read 0.1, output 5."""
    return r['in_uncached'] + 1.25 * r['cache_write'] + 0.1 * r['cache_read'] + 5 * r['out']


def stats(rs):
    """Raises when any counter is unknown: a gate is never computed from a zero that stands for missing usage."""
    keys = ('in', 'out', 'in_uncached', 'cache_write', 'cache_read', 'api_ms')
    missing = sum(1 for r in rs if any(type(r.get(k)) is not int or r[k] < 0 for k in keys))
    if missing:
        raise SystemExit(f'{missing} call(s) without complete usage or API time: gates are inconclusive')
    tok = sum(r['in'] + r['out'] for r in rs)
    money = sum(price(r) for r in rs)
    ms = sum(r['api_ms'] for r in rs)
    req = sum(r['jobs'] for r in rs)
    ver = sum(r['jobs'] for r in rs if r['passed'])
    return {'calls': len(rs), 'passed': sum(r['passed'] for r in rs), 'tokens': tok, 'C_requested': tok / req,
            'C_verified': tok / ver if ver else float('inf'), 'money_requested': money / req,
            'money_verified': money / ver if ver else float('inf'), 'ms_requested': ms / req,
            'ms_verified': ms / ver if ver else float('inf'),
            'api_ms_mean': statistics.mean(r['api_ms'] for r in rs), 'api_ms_median': statistics.median(r['api_ms'] for r in rs),
            'in_mean': statistics.mean(r['in'] for r in rs), 'out_mean': statistics.mean(r['out'] for r in rs)}


base = stats(arms.pop('0.8-exec'))
(name, cand_rows), = arms.items()
cand = stats(cand_rows)
for k, s in (('0.8-exec', base), (name, cand)):
    print(k, {a: round(b, 2) if isinstance(b, float) else b for a, b in s.items()})
fails = cand['calls'] - cand['passed']
saving = 1 - cand['C_verified'] / base['C_requested']
print(f'acceptance gate: {cand["passed"]}/{cand["calls"]} (at most 1 failure) ->', 'PASS' if fails <= 1 else 'FAIL')
print(f'token gate: C_verified {cand["C_verified"]:.1f} <= 0.65 x {base["C_requested"]:.1f} = {0.65 * base["C_requested"]:.1f}'
      f' (saving {saving:.1%}) ->', 'PASS' if saving >= 0.35 else 'FAIL')
print(f'speed gate: {cand["ms_verified"]:.1f} <= {base["ms_requested"]:.1f} ms per job ->',
      'PASS' if cand['ms_verified'] <= base['ms_requested'] else 'FAIL')
print(f'money gate: {cand["money_verified"]:.1f} <= {base["money_requested"]:.1f} units per job ->',
      'PASS' if cand['money_verified'] <= base['money_requested'] else 'FAIL')
print('baseline packets fully correct:', f'{base["passed"]}/{base["calls"]} (reported, not a gate)')
