"""Frozen stage-1g decision test (docs/design/stage-1g-final-decision.md), stage A.

Sonnet 5.5, 64 jobs, candidate arm 20 calls on data seeds 1005-1024, 0.8-exec 5 calls on 1005, 1009, 1013, 1017,
1021, paired order shuffled, concurrency 1, no reply retry. The arm stops at its second failed packet.
Before the first call the manifest (texts, packets, settings, schedule) is hashed and written next to the data.
Usage: ARM=H OUT=live22_1g_A_H.jsonl python bench/live/run1g.py
Stage D: MODEL=haiku N=64 SEEDS=2005-2014 BASE= ARM=H OUT=... (the second-failure stop still applies)
"""
import hashlib, json, os, random, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import live11 as M
import run_live as L

ARM = os.environ['ARM']
N = int(os.environ.get('N', '64'))
lo, hi = map(int, os.environ.get('SEEDS', '1005-1024').split('-'))
SEEDS = list(range(lo, hi + 1))
# Stage D cells run without baseline: BASE= (empty).
BASE = {int(s) for s in os.environ.get('BASE', '1005,1009,1013,1017,1021').split(',') if s}
OUT = M.X.V.LIVE / 'data' / os.environ['OUT']


def schedule():
    plan = []
    for seed in SEEDS:
        arms = [ARM] + (['0.8-exec'] if seed in BASE else [])
        random.Random(f'1g-A-{seed}').shuffle(arms)
        plan += [(seed, a) for a in arms]
    return plan


def manifest(plan):
    h = hashlib.sha256()
    for seed, a in plan:
        M.use_records(M.make_records(seed))
        system, user, _, _ = M.ARMS[a](N)
        h.update(json.dumps([seed, a, system, user], ensure_ascii=False).encode('utf-8'))
    return {'arm': ARM, 'n': N, 'model': L.MODEL_IDS[os.environ.get('MODEL', 'sonnet')], 'effort': os.environ.get('EFFORT'),
            'schedule': plan, 'sha256': h.hexdigest(),
            'cli_version': subprocess.run([L.CLAUDE, '--version'], capture_output=True, text=True).stdout.strip(), 'reply_retry': 0, 'concurrency': 1, 'timeout_s': 300, 'output_limit': 'claude -p default (no --max-tokens); a truncated reply is a failure',
            'note': 'seeds drive the data generator only; provider sampling is uncontrolled; claude -p transport '
                    'retries on HTTP errors are not configurable here and never resample a completed reply'}


def main():
    plan = schedule()
    man = manifest(plan)
    OUT.with_suffix('.manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8')
    print('manifest', man['sha256'], flush=True)
    fails = 0
    for seq, (seed, a) in enumerate(plan):
        if a == ARM and fails >= int(os.environ.get('STOP', '2')):
            continue
        M.use_records(M.make_records(seed))
        system, user, dec, native = M.ARMS[a](N)
        r = L.call(user, system=system)
        js = M.X.V.jobs('materials', N)
        err, ok = '', 0
        try:
            flat = dec(r['text'])
            ok = sum(g and M.X.check(j, v, native) for (g, v), j in zip(flat, js))
        except Exception as exc:  # noqa: BLE001
            err = str(exc)[:200]
        passed = not err and ok == N
        if a == ARM and not passed:
            fails += 1
        rec = {'seq': seq, 'seed': seed, 'n': N, 'arm': a, 'effort': os.environ.get('EFFORT'),
               'packet_o200k': L.count((system or '') + user), 'valid': not err, 'error': err,
               'jobs_passed': ok, 'jobs': N, 'passed': passed, 'manifest': man['sha256'], **r}
        with OUT.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        print(seq, seed, a, r.get('model'), 'PASS' if passed else 'FAIL ' + (err or f'{ok}/{N}'),
              'in', r['in'], 'out', r['out'], 'api_ms', r['api_ms'], flush=True)
    print('arm failures', fails, flush=True)


if __name__ == '__main__':
    main()
