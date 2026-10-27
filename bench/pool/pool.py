"""Cross-producer pooling test (Claude and Astra decision, 2026-10-26): does pooling ready jobs from several
independent producers into fewer calls cut tokens without hurting latency, and what does AKOR add over a plain queue?

Workload: the pinned BoolQ validation sample of bench/ozmap/data.py, the first JOBS questions of each of the four
producers (labels never reach the model; they score only). All jobs arrive at t0; the queue does not wait.
  D  each producer sends its own jobs in one direct claude -p call; the four calls run concurrently.
  P  a plain shared queue sends all jobs in one direct call (same prompt format as D).
  A  the same queue sends all jobs as one OZ/1g packet (oz_batch.SYSTEM, oz_reply.parse_reply), the shipped wire.
Every arm: same model and flags as the AKOR route (no tools), the same operation text, one retry of a call whose reply
is unusable. Producer latency = t0 to the arrival of that producer's last accepted answer.

    python bench/pool/pool.py run --workspace DIR --order D,P,A [--kind fixture|live]
Live runs need POOL_LIVE_CONFIRM=1. Results: DIR/pool.json.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench import harness as H  # noqa: E402
from bench.ozmap import data  # noqa: E402
import oz_batch  # noqa: E402
import oz_reply  # noqa: E402

MODEL = 'claude-sonnet-5-5'
JOBS = 8
TIMEOUT = 300
RETRIES = 1
MAX_LAUNCHES = 8
MAX_TOKENS = 200_000
RESERVE = 20_000  # tokens held for a call in flight until its usage is known
LIVE_ENV = 'POOL_LIVE_CONFIRM'
DIRECT_SYSTEM = 'You answer questions about passages. Reply with one JSON object only, no prose and no Markdown fences.'
GOAL = 'Answer yes/no reading-comprehension questions.'


def workload() -> tuple:
    """([(producer, id, text)], {id: gold "yes"/"no"})."""
    q = data.boolq()
    if not q['available']:
        raise SystemExit(q['reason'])
    jobs, gold = [], {}
    for p in data.PRODUCERS:
        for j in q['waves']['cold'][p][:JOBS]:
            jid = f'{p}{j["key"]}'
            jobs.append((p, jid, j['text']))
            gold[jid] = 'yes' if q['labels'][j['dataset_id']] else 'no'
    return jobs, gold


def call(system: str, prompt: str, kind: str, fixture_text, effort: str | None = None) -> dict:
    """One call through bench/harness.py (model check, usage None when unknown, failures recorded)."""
    return H.call(system, prompt, model=MODEL, kind=kind, fixture=fixture_text, effort=effort, timeout=TIMEOUT)


# ---- reply formats ----

def direct_prompt(items) -> str:
    return (GOAL + ' ' + data.BOOLQ_OP_TEXT + '\nReply with one JSON object mapping every id to its answer: '
            '{"<id>": "yes" | "no"}.\n' + json.dumps({jid: text for jid, text in items}, ensure_ascii=False))


def direct_parse(text: str, ids) -> dict:
    """{id: answer} for a usable reply (every id, each "yes" or "no"), else {}."""
    try:
        value = oz_reply.loads(text.strip())  # strict like OZ/1g: no fence removal, duplicate keys reject
    except (ValueError, RecursionError, oz_reply.Error):
        return {}
    if not isinstance(value, dict) or set(value) != set(ids) or any(v not in ('yes', 'no') for v in value.values()):
        return {}
    return value


def oz_packet(items) -> str:
    body = {'v': oz_batch.VERSION, 'goal': GOAL, 'ops': [data.BOOLQ_OP_TEXT],
            'refs': [text for _, text in items], 'jobs': [[0] + [[jid, i] for i, (jid, _) in enumerate(items)]]}
    oz_batch.validate_packet(body)
    return oz_batch.J(body)


def oz_parse(text: str, ids) -> dict:
    parsed = oz_reply.parse_reply(text, ids)
    if parsed.rejection or parsed.failed:
        return {}
    out = {k: v for k, v in parsed.accepted.items()}
    return out if all(v in ('yes', 'no') for v in out.values()) else {}


def fixture_answers(items, gold, fmt: str) -> str:
    if fmt == 'oz':
        return oz_reply.HEADER + '\n' + '\n'.join(json.dumps({jid: gold[jid]}) for jid, _ in items) + '\n'
    return json.dumps({jid: gold[jid] for jid, _ in items})


# ---- arms ----

def run_group(items, fmt: str, kind: str, gold, launches: list, ws: Path, tag: str, ledger) -> dict:
    """Send one group in one call (plus at most RETRIES retries of an unusable reply). {id: (answer, arrival)}."""
    ids = [jid for jid, _ in items]
    system, prompt, parse = ((oz_batch.SYSTEM, oz_packet(items), oz_parse) if fmt == 'oz'
                             else (DIRECT_SYSTEM, direct_prompt(items), direct_parse))
    for attempt in range(1 + RETRIES):
        c = H.run_charged(ledger, lambda: call(system, prompt, kind, lambda: fixture_answers(items, gold, fmt)))
        if c is None:  # launch cap, token cap or a call without usage
            launches.append({'group': tag, 'attempt': attempt, 'refused': True, 'usage': None, 'jobs': len(ids)})
            return {}
        record = {'group': tag, 'attempt': attempt, 'usage': c['usage'], 'failure': c['failure'],
                  'started': c['started'], 'ended': c['ended'], 'jobs': len(ids)}
        launches.append(record)
        (ws / 'calls').mkdir(parents=True, exist_ok=True)
        (ws / 'calls' / f'{tag}-{attempt}.json').write_text(
            json.dumps({'system': system, 'prompt': prompt, 'envelope': c['envelope']}), encoding='utf-8')
        answers = parse(c['text'], ids) if not c['failure'] else {}
        if answers:
            return {jid: (answers[jid], c['ended']) for jid in ids}
        record['rejected'] = True
    return {}


def run_arm(arm: str, jobs, gold, kind: str, ws: Path, launches: list, ledger) -> dict:
    t0 = time.time()
    by_producer = {p: [(jid, text) for q, jid, text in jobs if q == p] for p in data.PRODUCERS}
    results = {}
    if arm == 'D':
        with cf.ThreadPoolExecutor(len(by_producer)) as pool:
            futures = [pool.submit(run_group, items, 'direct', kind, gold, launches, ws, f'D-{p}', ledger)
                       for p, items in by_producer.items()]
            for f in futures:
                results.update(f.result())
    else:
        results = run_group([(jid, text) for _, jid, text in jobs], 'oz' if arm == 'A' else 'direct', kind, gold,
                            launches, ws, arm, ledger)
    tagged = [x for x in launches if x['group'] == arm or x['group'].startswith(arm + '-')]
    refused = sum(1 for x in tagged if x.get('refused'))
    mine = [x for x in tagged if not x.get('refused')]
    t = H.total(x['usage'] for x in mine)
    complete = not refused and len(results) == len(gold)  # token figures only for a complete arm
    pub = lambda k: t[k] if complete else None
    latency = {}
    for p, items in by_producer.items():
        arrivals = [results[jid][1] for jid, _ in items if jid in results]
        latency[p] = round(max(arrivals) - t0, 2) if len(arrivals) == len(items) else None
    correct = sum(1 for jid in gold if jid in results and results[jid][0] == gold[jid])
    return {'arm': arm, 'calls': len(mine), 'refused_launches': refused, 'complete': complete,
            'rejected_calls': sum(1 for x in mine if x.get('rejected')),
            **{k: pub(k) for k in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'thinking_tokens', 'tokens')},
            'calls_without_usage': t['calls_without_usage'], 'thinking_unknown': t['thinking_unknown'],
            'tokens_known_calls_only': t['tokens_known_calls_only'],  # partial: diagnostics only
            'answered': len(results), 'correct': correct, 'jobs': len(gold),
            'makespan_seconds': round(max((x['ended'] for x in mine), default=t0) - t0, 2) if complete else None,
            'run_seconds': round(max((x['ended'] for x in mine), default=t0) - t0, 2),
            'producer_latency_seconds': latency,
            'worst_producer_latency_seconds': None if None in latency.values() else max(latency.values())}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = p.add_subparsers(dest='command', required=True)
    r = sub.add_parser('run')
    r.add_argument('--workspace', required=True, type=Path)
    r.add_argument('--order', default='D,P,A')
    r.add_argument('--kind', choices=('fixture', 'live'), default='fixture')
    args = p.parse_args(argv)
    if args.kind == 'live' and not os.environ.get(LIVE_ENV):
        print(f'live runs paid calls: set {LIVE_ENV}=1 to proceed', file=sys.stderr)
        return 2
    order = args.order.split(',')
    if sorted(order) != ['A', 'D', 'P']:
        p.error('--order names D, P and A once each')
    ws = args.workspace.resolve()
    ws.mkdir(parents=True, exist_ok=True)
    jobs, gold = workload()
    launches, rows = [], []
    ledger = H.Ledger(ws / 'pool-ledger.sqlite', max_launches=MAX_LAUNCHES, max_tokens=MAX_TOKENS, reserve=RESERVE)
    for arm in order:
        row = run_arm(arm, jobs, gold, args.kind, ws, launches, ledger)
        rows.append(row)
        print(arm, f"{row['correct']}/{row['jobs']} correct", row['calls'], 'calls', 'n/a (unknown usage)' if row['tokens'] is None else row['tokens'], 'tokens',
              row['makespan_seconds'], 's makespan, worst producer', row['worst_producer_latency_seconds'], flush=True)
        (ws / 'pool.json').write_text(json.dumps({'kind': args.kind, 'model': MODEL, 'order': order, 'rows': rows,
                                                  'launches': launches, 'ledger': ledger.state()}, indent=1) + '\n',
                                      encoding='utf-8')
    complete = all(r['complete'] for r in rows)
    # A call without usage makes the token comparison inconclusive, never a zero.
    conclusive = all(r['calls_without_usage'] == 0 for r in rows)
    if not conclusive:
        print('INCONCLUSIVE: at least one call has no usage', flush=True)
    return 0 if complete and conclusive else 3


if __name__ == '__main__':
    sys.exit(main())
