"""Pooling under staggered arrivals, and the reasoning control (Astra decision astra-pool-2.md, 2026-10-26).

Experiment 1 (arrivals): four producers arrive at frozen offsets, each with 8 BoolQ jobs.
  D  each producer sends its own 8 jobs in one direct call at its arrival.
  P  each producer submits to akor_pool.Pool (FIFO, at most 32 jobs, 500 ms wait from the oldest job), plain format.
  Profiles: burst 0/0.1/0.3/0.45 s (questions 8-15 of each producer), sparse 0/2/5/9 s (questions 16-23).
Experiment 2 (format control, questions 24-31, all producers at t0, pooled):
  P-default plain format, default effort; P-high plain format, --effort high; A-default OZ/1g, default effort.
Latency of a producer = its arrival to the delivery of its last answer, waits and retries included.
Caps shared by every run: 36 launches, 250,000 tokens (bench/harness.py ledger next to the workspace).

    python bench/pool/pool2.py arrivals --profile burst|sparse --order D,P --workspace DIR [--kind live]
    python bench/pool/pool2.py format --order Pd,Ph,A --workspace DIR [--kind live]
Live runs need POOL_LIVE_CONFIRM=1.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for p in (str(ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import akor_pool  # noqa: E402
from bench import harness as H  # noqa: E402
import oz_batch  # noqa: E402
import pool as P1  # noqa: E402
from bench.ozmap import data  # noqa: E402

PROFILES = {'burst': ((0.0, 0.1, 0.3, 0.45), slice(8, 16)), 'sparse': ((0.0, 2.0, 5.0, 9.0), slice(16, 24))}
FORMAT_SLICE = slice(24, 32)
MAX_LAUNCHES = 36
MAX_TOKENS = 250_000
MAX_JOBS, MAX_WAIT = 32, 0.5
RESERVE = 20_000  # tokens held for a call in flight until its usage is known


def workload(sl: slice):
    q = data.boolq()
    jobs, gold = {}, {}
    for p in data.PRODUCERS:
        jobs[p] = []
        for j in q['waves']['cold'][p][sl]:
            jid = f'{p}{j["key"]}'
            jobs[p].append((jid, j['text']))
            gold[jid] = 'yes' if q['labels'][j['dataset_id']] else 'no'
    return jobs, gold


def Ledger(path: Path):
    """Shared caps (bench/harness.py): a launch needs room for itself and every call in flight; any call without usage
    stops all launches."""
    return H.Ledger(path, max_launches=MAX_LAUNCHES, max_tokens=MAX_TOKENS, reserve=RESERVE)


def make_send(fmt: str, kind: str, gold: dict, ledger: Ledger, calls: list, ws: Path, tag: str, effort=None):
    """send(batch) -> {id: answer} through one claude -p call; records every launch."""
    lock = threading.Lock()

    def send(batch):
        ids = [jid for jid, _ in batch]
        if fmt == 'oz':
            system, prompt, parse = oz_batch.SYSTEM, P1.oz_packet(batch), P1.oz_parse
        else:
            system, prompt, parse = P1.DIRECT_SYSTEM, P1.direct_prompt(batch), P1.direct_parse
        c = H.run_charged(ledger, lambda: P1.call(system, prompt, kind, lambda: P1.fixture_answers(batch, gold, fmt),
                                                  effort=effort))
        if c is None:
            with lock:
                calls.append({'tag': tag, 'jobs': len(ids), 'refused': True, 'usage': None})
            raise RuntimeError('engineering cap reached')
        record = {'tag': tag, 'jobs': len(ids), 'usage': c['usage'], 'failure': c['failure'],
                  'started': c['started'], 'ended': c['ended']}
        with lock:  # concurrent batches: one file name and one record each
            n = len(calls)
            calls.append(record)
        (ws / 'calls').mkdir(parents=True, exist_ok=True)
        (ws / 'calls' / f'{tag}-{n}.json').write_text(json.dumps({'system': system, 'prompt': prompt,
                                                                  'envelope': c['envelope']}), encoding='utf-8')
        answers = parse(c['text'], ids) if not c['failure'] else {}
        if not answers:
            record['rejected'] = True
        return answers
    return send


def summarize(arm: str, calls: list, delivered: dict, arrivals: dict, jobs: dict, gold: dict) -> dict:
    """Token figures only for a complete arm (every job answered, no refused launch, usage on every call); the
    makespan covers every attempt and is None when a job was never answered."""
    refused = sum(1 for c in calls if c.get('refused'))
    launched = [c for c in calls if not c.get('refused')]
    t = H.total(c['usage'] for c in launched)
    complete = not refused and len(delivered) == len(gold)
    pub = lambda k: t[k] if complete else None
    latency = {}
    for p, items in jobs.items():
        times = [delivered[jid][1] for jid, _ in items if jid in delivered]
        latency[p] = round(max(times) - arrivals[p], 2) if len(times) == len(items) else None
    t0 = min(arrivals.values())
    ends = [c['ended'] for c in launched] + [t for _, t in delivered.values()]
    return {'arm': arm, 'calls': len(launched), 'refused_launches': refused, 'complete': complete,
            'rejected_calls': sum(1 for c in launched if c.get('rejected')),
            **{k: pub(k) for k in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'thinking_tokens', 'tokens')},
            'calls_without_usage': t['calls_without_usage'], 'thinking_unknown': t['thinking_unknown'],
            'tokens_known_calls_only': t['tokens_known_calls_only'],  # partial: diagnostics only
            'answered': len(delivered), 'jobs': len(gold),
            'correct': sum(1 for jid, (v, _) in delivered.items() if v == gold[jid]),
            'makespan_seconds': round(max(ends) - t0, 2) if complete and ends else None,
            'run_seconds': round(max(ends, default=t0) - t0, 2),
            'producer_latency_seconds': latency,
            'worst_producer_latency_seconds': None if None in latency.values() else max(latency.values())}


def run_direct(jobs, gold, offsets, kind, ledger, ws, tag) -> dict:
    """D: each producer one call of its own jobs at its arrival (one retry of an unusable reply)."""
    calls, delivered, arrivals, lock = [], {}, {}, threading.Lock()
    send = make_send('direct', kind, gold, ledger, calls, ws, tag)
    start = time.time()

    def producer(p, offset):
        time.sleep(max(0.0, start + offset - time.time()))
        arrivals[p] = time.time()
        for _ in range(2):
            try:
                answers = send(jobs[p])
            except RuntimeError:
                return
            if answers:
                now = time.time()
                with lock:
                    delivered.update({jid: (answers[jid], now) for jid, _ in jobs[p]})
                return
    threads = [threading.Thread(target=producer, args=(p, o)) for p, o in zip(data.PRODUCERS, offsets)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return summarize('D', calls, delivered, arrivals, jobs, gold)


def run_pooled(arm, jobs, gold, offsets, kind, ledger, ws, tag, fmt='direct', effort=None) -> dict:
    calls, delivered, arrivals, lock = [], {}, {}, threading.Lock()
    pool = akor_pool.Pool(make_send(fmt, kind, gold, ledger, calls, ws, tag, effort), max_jobs=MAX_JOBS,
                          max_wait=MAX_WAIT)
    start = time.time()
    futures = []

    def done(jid):
        def cb(f):
            if f.exception() is None:
                with lock:
                    delivered[jid] = (f.result(), time.time())
        return cb
    for p, offset in sorted(zip(data.PRODUCERS, offsets), key=lambda x: x[1]):
        time.sleep(max(0.0, start + offset - time.time()))
        arrivals[p] = time.time()
        for jid, text in jobs[p]:
            f = pool.submit(jid, text)
            f.add_done_callback(done(jid))
            futures.append(f)
    pool.close()
    out = summarize(arm, calls, delivered, arrivals, jobs, gold)
    out['pool_batches'] = [{'jobs': len(c['ids']), 'attempt': c['attempt'], 'queued_seconds': c['queued_seconds']}
                           for c in pool.calls]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    a = sub.add_parser('arrivals')
    a.add_argument('--profile', choices=sorted(PROFILES), required=True)
    a.add_argument('--order', default='D,P')
    f = sub.add_parser('format')
    f.add_argument('--order', default='Pd,Ph,A')
    for s in (a, f):
        s.add_argument('--workspace', required=True, type=Path)
        s.add_argument('--kind', choices=('fixture', 'live'), default='fixture')
        s.add_argument('--ledger', type=Path)
    args = ap.parse_args(argv)
    if args.kind == 'live' and not os.environ.get(P1.LIVE_ENV):
        print(f'live runs paid calls: set {P1.LIVE_ENV}=1 to proceed', file=sys.stderr)
        return 2
    ws = args.workspace.resolve()
    ws.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(args.ledger or ws.parent / 'pool2-ledger.sqlite')
    order = args.order.split(',')
    rows = []
    if args.command == 'arrivals':
        if sorted(order) != ['D', 'P']:
            ap.error('--order names D and P')
        offsets, sl = PROFILES[args.profile]
        jobs, gold = workload(sl)
        for arm in order:
            rows.append(run_direct(jobs, gold, offsets, args.kind, ledger, ws / arm, arm) if arm == 'D' else
                        run_pooled('P', jobs, gold, offsets, args.kind, ledger, ws / arm, arm))
    else:
        if sorted(order) != ['A', 'Pd', 'Ph']:
            ap.error('--order names Pd, Ph and A')
        jobs, gold = workload(FORMAT_SLICE)
        offsets = (0.0,) * len(data.PRODUCERS)
        for arm in order:
            fmt, effort = {'Pd': ('direct', None), 'Ph': ('direct', 'high'), 'A': ('oz', None)}[arm]
            rows.append(run_pooled(arm, jobs, gold, offsets, args.kind, ledger, ws / arm, arm, fmt, effort))
    for r in rows:
        print(r['arm'], f"{r['correct']}/{r['jobs']}", r['calls'], 'calls', 'n/a (incomplete or unknown usage)' if r['tokens'] is None else r['tokens'], 'tokens', 'makespan',
              r['makespan_seconds'], 'worst', r['worst_producer_latency_seconds'], flush=True)
    (ws / 'pool2.json').write_text(json.dumps({'command': args.command, 'profile': getattr(args, 'profile', None),
                                               'order': order, 'kind': args.kind, 'rows': rows,
                                               'ledger': ledger.state()}, indent=1) + '\n', encoding='utf-8')
    ok = all(r['complete'] and r['calls_without_usage'] == 0 for r in rows)
    return 0 if ok else 3


if __name__ == '__main__':
    sys.exit(main())
