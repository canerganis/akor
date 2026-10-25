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
import re
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.ozmap import data  # noqa: E402
import oz_batch  # noqa: E402
import oz_reply  # noqa: E402

MODEL = 'claude-sonnet-5-5'
JOBS = 8
TIMEOUT = 300
RETRIES = 1
MAX_LAUNCHES = 8
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


def usage_of(envelope):
    mu = envelope.get('modelUsage') if isinstance(envelope, dict) else None
    if not isinstance(mu, dict) or not mu:
        return None
    keys = ('inputTokens', 'cacheReadInputTokens', 'cacheCreationInputTokens', 'outputTokens')
    if any(type(e.get(k)) is not int for e in mu.values() for k in keys):
        return None
    s = {k: sum(e[k] for e in mu.values()) for k in keys}
    return {'input_tokens': s['inputTokens'] + s['cacheReadInputTokens'] + s['cacheCreationInputTokens'],
            'cached_input_tokens': s['cacheReadInputTokens'], 'output_tokens': s['outputTokens'],
            'thinking_tokens': sum(e.get('thinkingTokens') or 0 for e in mu.values())}


def call(system: str, prompt: str, kind: str, fixture_text, effort: str | None = None) -> dict:
    started = time.time()
    envelope, failure = None, None
    if kind == 'fixture':
        text = fixture_text()
        envelope = {'result': text, 'modelUsage': {MODEL: {
            'inputTokens': (len(system) + len(prompt)) // 4, 'cacheReadInputTokens': 0,
            'cacheCreationInputTokens': 0, 'outputTokens': len(text) // 4, 'thinkingTokens': 0}}}
    else:
        try:
            proc = subprocess.run([shutil.which('claude'), '-p', '--model', MODEL, '--system-prompt', system,
                                   '--tools', '', '--setting-sources', '', '--strict-mcp-config',
                                   '--no-session-persistence', '--output-format', 'json']
                                  + (['--effort', effort] if effort else []),
                                  input=prompt, capture_output=True, text=True, encoding='utf-8', timeout=TIMEOUT)
            envelope = json.loads(proc.stdout)
        except subprocess.TimeoutExpired:
            failure = 'timeout'
        except ValueError:
            failure = 'unreadable envelope'
    if isinstance(envelope, dict) and sorted(envelope.get('modelUsage') or {}) != [MODEL]:
        failure = 'unexpected model(s): ' + ', '.join(sorted(envelope.get('modelUsage') or {}))
    return {'text': '' if failure or not isinstance(envelope, dict) else envelope.get('result', ''),
            'usage': usage_of(envelope), 'failure': failure, 'started': started, 'ended': time.time(),
            'envelope': envelope}


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

def run_group(items, fmt: str, kind: str, gold, launches: list, ws: Path, tag: str) -> dict:
    """Send one group in one call (plus at most RETRIES retries of an unusable reply). {id: (answer, arrival)}."""
    ids = [jid for jid, _ in items]
    system, prompt, parse = ((oz_batch.SYSTEM, oz_packet(items), oz_parse) if fmt == 'oz'
                             else (DIRECT_SYSTEM, direct_prompt(items), direct_parse))
    for attempt in range(1 + RETRIES):
        if len(launches) >= MAX_LAUNCHES:
            return {}
        c = call(system, prompt, kind, lambda: fixture_answers(items, gold, fmt))
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


def run_arm(arm: str, jobs, gold, kind: str, ws: Path, launches: list) -> dict:
    t0 = time.time()
    by_producer = {p: [(jid, text) for q, jid, text in jobs if q == p] for p in data.PRODUCERS}
    results = {}
    if arm == 'D':
        with cf.ThreadPoolExecutor(len(by_producer)) as pool:
            futures = [pool.submit(run_group, items, 'direct', kind, gold, launches, ws, f'D-{p}')
                       for p, items in by_producer.items()]
            for f in futures:
                results.update(f.result())
    else:
        results = run_group([(jid, text) for _, jid, text in jobs], 'oz' if arm == 'A' else 'direct', kind, gold,
                            launches, ws, arm)
    mine = [x for x in launches if x['group'] == arm or x['group'].startswith(arm + '-')]
    known = [x['usage'] for x in mine if x['usage']]
    latency = {}
    for p, items in by_producer.items():
        arrivals = [results[jid][1] for jid, _ in items if jid in results]
        latency[p] = round(max(arrivals) - t0, 2) if len(arrivals) == len(items) else None
    correct = sum(1 for jid in gold if jid in results and results[jid][0] == gold[jid])
    return {'arm': arm, 'calls': len(mine), 'rejected_calls': sum(1 for x in mine if x.get('rejected')),
            'calls_without_usage': len(mine) - len(known),
            'input_tokens': sum(u['input_tokens'] for u in known),
            'cached_input_tokens': sum(u['cached_input_tokens'] for u in known),
            'output_tokens': sum(u['output_tokens'] for u in known),
            'thinking_tokens': sum(u['thinking_tokens'] for u in known),
            'tokens': sum(u['input_tokens'] + u['output_tokens'] for u in known),
            'answered': len(results), 'correct': correct, 'jobs': len(gold),
            'makespan_seconds': round(max((x['ended'] for x in mine), default=t0) - t0, 2),
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
    for arm in order:
        row = run_arm(arm, jobs, gold, args.kind, ws, launches)
        rows.append(row)
        print(arm, f"{row['correct']}/{row['jobs']} correct", row['calls'], 'calls', row['tokens'], 'tokens',
              row['makespan_seconds'], 's makespan, worst producer', row['worst_producer_latency_seconds'], flush=True)
        (ws / 'pool.json').write_text(json.dumps({'kind': args.kind, 'model': MODEL, 'order': order, 'rows': rows,
                                                  'launches': launches}, indent=1) + '\n', encoding='utf-8')
    complete = all(r['answered'] == r['jobs'] for r in rows) and len(launches) <= MAX_LAUNCHES
    # A call without usage makes the token comparison inconclusive, never a zero.
    conclusive = all(r['calls_without_usage'] == 0 for r in rows)
    if not conclusive:
        print('INCONCLUSIVE: at least one call has no usage', flush=True)
    return 0 if complete and conclusive else 3


if __name__ == '__main__':
    sys.exit(main())
