"""Distinct-job large batches: 16 generated materials records x 4 codes = 64 distinct jobs.

Oracles are computed with Decimal. Arms 0.8-exec vs F, as in live3.
"""
import json, os, random, sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, '.')
import live2 as V
import live3 as T
import run_live as L

OUT = V.LIVE / 'data' / os.environ.get('OUT', 'live6.jsonl')
rng = random.Random(7)
RECS = {}
for k in range(1, 17):
    length = Decimal('12.40') + Decimal(rng.randint(0, 20)) / 100
    unc = rng.choice(['0.01 mm', '0.02 mm', '0.03 mm', 'unknown'])
    RECS[k] = {'length': f'{length:.2f} mm', 'uncertainty': unc, 'n': str(rng.randint(1, 6)),
               'method': rng.choice(['unknown', 'micrometer', 'caliper']),
               'basis': rng.choice(['unknown', 'expanded', 'resolution']), 'physical_validation': 'not_claimed'}
C = {str(k): '; '.join(f'{f}={v}' for f, v in r.items()) for k, r in RECS.items()}


def oracle(code, k):
    r = RECS[k]
    if code == 'e':
        return list(r.values())
    if code == 'm':
        return [f for f in ('uncertainty', 'method', 'basis') if r[f] == 'unknown']
    if r['uncertainty'] == 'unknown':
        return 'unknown'
    l, u = Decimal(r['length'][:-3]), Decimal(r['uncertainty'][:-3])
    if code == 'b':
        return [f'{l - u:.2f} mm', f'{l + u:.2f} mm']
    return 'inside' if l - u >= Decimal('12.48') and l + u <= Decimal('12.52') else 'outside'


V.DOMAINS['materials'] = (V.MAT_GOAL, C, V.MAT_D, 'ebmv')
V.MAT_C = C
V.jobs = lambda dom, n: [f'{code}{k}' for k in range(1, 17) for code in 'ebmv'][:n]


def check(job, value, native):
    code, k = job[0], int(job[1:])
    want = oracle(code, k)
    if native:
        return value == want
    v, ok = V.jparse(value.strip())
    return value.strip() == want or (ok and v == want)


def main():
    seq, done = 0, set()
    if OUT.exists():
        for line in OUT.read_text(encoding='utf-8').splitlines():
            r = json.loads(line); done.add((r['rep'], r['n'], r['arm'])); seq = max(seq, r['seq'] + 1)
    plan = [(rep, n, a) for rep in range(3) for n in (32, 64) for a in random.Random(f'6{rep}{n}').sample(['0.8-exec', 'F'], 2)]
    for rep, n, arm in plan:
        if (rep, n, arm) in done:
            continue
        js = V.jobs('materials', n)
        if arm == '0.8-exec':
            ids, prompt = V.packet_08('materials', n)
        else:
            prompt = T.packet('materials', n, 'F')
        r = L.call(prompt)
        err, passed = '', [False] * n
        try:
            if arm == '0.8-exec':
                value, _ = L.parse(r['text'])
                outcomes = L.results08(value, ids)
                passed = [outcomes[i][0] == 'ok' and check(j, outcomes[i][1], False) for i, j in zip(ids, js)]
            else:
                passed = [ok and check(j, v, True) for (ok, v), j in zip(T.decode('F', r['text'], n), js)]
        except Exception as exc:  # noqa: BLE001
            err = str(exc)[:100]
        rec = {'seq': seq, 'rep': rep, 'n': n, 'arm': arm, 'packet_o200k': L.count(prompt), 'valid': not err,
               'error': err, 'jobs_passed': sum(passed), 'jobs': n, **r}
        with OUT.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        print(seq, n, arm, 'valid' if not err else 'INVALID ' + err, f'pass {sum(passed)}/{n}', 'in', r['in'], 'out', r['out'],
              'api_ms', r['api_ms'], flush=True)
        seq += 1


if __name__ == '__main__':
    main()
