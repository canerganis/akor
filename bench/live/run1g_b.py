"""Frozen stage-1g decision test (docs/design/stage-1g-final-decision.md), stage B (also the heterogeneous part of C).

The five heterogeneous 64-job packets of bench/live/hetero1g.py (data seeds 3001-3005), once each in order P1..P5, one arm,
concurrency 1, no reply retry, no early stop. Before the first call the manifest (texts, packets, expected results,
settings, program hashes) is hashed and written next to the data. MODEL passes through to run_live.call.
Usage: ARM=H OUT=live22_1g_B_H.jsonl python bench/live/run1g_b.py   (ARM=G: G system text, no header)
"""
import hashlib, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import live11 as M
import run_live as L
import hetero1g as HG

ARM = os.environ['ARM']
assert ARM in ('H', 'G'), ARM
HEADER = ARM == 'H'
SYSTEM = M.ARMS['H'](HG.N)[0] if HEADER else M.G_SYSTEM
OUT = M.X.V.LIVE / 'data' / os.environ['OUT']
KS = range(1, 6)


def manifest():
    h = hashlib.sha256()
    for k in KS:
        body, ids, expected = HG.packet(k)
        h.update(json.dumps([3000 + k, ARM, SYSTEM, body, ids, expected], ensure_ascii=False).encode('utf-8'))
    for f in (HG.__file__, __file__):
        h.update(Path(f).read_bytes())
    return {'arm': ARM, 'header': HEADER, 'n': HG.N, 'model': L.MODEL_IDS.get(os.environ.get('MODEL', 'sonnet'), os.environ.get('MODEL', 'sonnet')),
            'effort': os.environ.get('EFFORT'), 'schedule': [[3000 + k, k] for k in KS], 'sha256': h.hexdigest(),
            'reply_retry': 0, 'concurrency': 1, 'timeout_s': 300,
            'note': 'seeds drive the data generator only; provider sampling is uncontrolled; claude -p transport '
                    'retries on HTTP errors are not configurable here and never resample a completed reply'}


def main():
    man = manifest()
    OUT.with_suffix('.manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8')
    print('manifest', man['sha256'], flush=True)
    for seq, k in enumerate(KS):
        body, ids, expected = HG.packet(k)
        r = L.call(body, system=SYSTEM)
        ok, n, err = HG.judge(r['text'], ids, expected, HEADER)
        passed = ok and n == HG.N
        rec = {'seq': seq, 'seed': 3000 + k, 'packet': k, 'arm': ARM, 'effort': os.environ.get('EFFORT'),
               'packet_o200k': L.count(SYSTEM + body), 'valid': ok, 'error': err, 'jobs_passed': n, 'jobs': HG.N,
               'passed': passed, 'manifest': man['sha256'], **r}
        with OUT.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        print(seq, 3000 + k, ARM, r.get('model'), 'PASS' if passed else 'FAIL ' + (err or f'{n}/{HG.N}'),
              'in', r['in'], 'out', r['out'], 'api_ms', r['api_ms'], flush=True)


if __name__ == '__main__':
    main()
