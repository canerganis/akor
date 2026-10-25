"""Build the owner decision 5 evidence for m (ruling P3): sanitized owner rollouts around the pilot window and the
metadata of every physical Codex call of the pilot run directories.

Owner rollouts: every owner session of the baseline account whose session started on 2026-10-24 between 08:00 and
15:20 UTC and that holds a rate limit reading. Only session_meta (CLI fields, account id replaced by
acct-fixture-baseline after a hash comparison), task_started, task_complete and token_count events (timestamp and
rate_limits) survive; no prompt, reply, instruction or token text is kept.

Pilot calls: every call id listed in `new_calls` of an execution.json of a Codex attempt or telemetry run under
bench/ozmap/runs/live-* (read only; bench/ozmap is frozen), with the reservation time from that run directory's
budget.sqlite, the child timeout of its spec.json, the outcome, the elapsed time and the token usage counts.

Run from the repo root: python bench/ozmap_rep/tests/fixtures/p3-headroom/build.py
"""
import glob
import hashlib
import json
import os
import sqlite3
import sys
import datetime as dt
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO))
from bench.ozmap_rep import config, isolation  # noqa: E402

OUT = Path(__file__).resolve().parent
SESSIONS = Path.home() / '.codex' / 'sessions'
RUNS = REPO / 'bench' / 'ozmap' / 'runs'
WINDOW = ('2026-10-24T08:00', '2026-10-24T15:20')


def sanitize(path, base):
    rows, meta_start, readings = [], None, 0
    for line in path.read_bytes().decode('utf-8', 'replace').splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        pl = e.get('payload') if isinstance(e.get('payload'), dict) else {}
        t = e.get('type')
        if t == 'session_meta':
            a = pl.get('creator_account_id')
            if not a:
                return None, None, 0
            acct = 'acct-fixture-baseline' if hashlib.sha256(a.encode()).hexdigest() == base else 'acct-fixture-other'
            keep = {k: pl[k] for k in ('cli_version', 'originator') if k in pl}
            keep['creator_account_id'] = acct
            meta_start = meta_start or e.get('timestamp')
            rows.append({'timestamp': e.get('timestamp'), 'type': t, 'payload': keep})
        elif t == 'event_msg' and pl.get('type') in ('task_started', 'task_complete'):
            rows.append({'timestamp': e.get('timestamp'), 'type': t, 'payload': {'type': pl['type']}})
        elif t == 'event_msg' and pl.get('type') == 'token_count' and pl.get('rate_limits') is not None:
            readings += 1
            rows.append({'timestamp': e.get('timestamp'), 'type': t,
                         'payload': {'type': 'token_count', 'rate_limits': pl.get('rate_limits')}})
    return rows, meta_start, readings


def owner_rollouts(base):
    index = []
    for p in sorted(SESSIONS.glob('2026/10/24/*.jsonl')):
        rows, start, readings = sanitize(p, base)
        if not rows or not start or not readings or not (WINDOW[0] <= start <= WINDOW[1]):
            continue
        name = 'owner-' + start[11:19].replace(':', '') + '.jsonl'
        (OUT / name).write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in rows), encoding='utf-8')
        index.append({'fixture': name, 'source': 'owner ~/.codex/sessions/' + p.relative_to(SESSIONS).as_posix(),
                      'source_sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'session_started_at': start,
                      'readings': readings})
    return index


def pilot_calls():
    calls = []
    for run in sorted(RUNS.glob('live-*')):
        db = sqlite3.connect(str(run / 'budget.sqlite'))
        reserved = {k: float(at) for k, at in db.execute("select key, at from reservations where backend='codex'")}
        db.close()
        for ex in sorted(glob.glob(str(run / '**' / 'execution.json'), recursive=True)):
            ex = Path(ex)
            rel = ex.relative_to(RUNS).as_posix()
            if 'sonnet' in rel:
                continue
            spec = json.loads((ex.parent / 'spec.json').read_text(encoding='utf-8'))
            if spec.get('route', {}).get('model') != config.CODEX_MODEL:
                continue
            doc = json.loads(ex.read_text(encoding='utf-8'))
            key = spec['request']['request_id']
            new = set(doc.get('new_calls') or [])
            for c in doc.get('calls') or []:
                if c.get('call_id') not in new:
                    continue
                u = c.get('usage')
                usage = None if not isinstance(u, dict) else {k: u.get(k) for k in (
                    'input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens')}
                at = dt.datetime.fromtimestamp(reserved[key], dt.timezone.utc)
                calls.append({'call_id': c['call_id'], 'run': run.name, 'source': rel, 'reservation': key,
                              'reserved_at': at.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
                              'timeout_s': float(spec['child_timeout']), 'route': spec['route'],
                              'outcome': c.get('outcome'), 'elapsed_ms': c.get('elapsed_ms'), 'usage': usage})
    return calls


def main():
    base = isolation.account_sha256(config.BASELINE_DEFAULT)
    index = owner_rollouts(base)
    calls = pilot_calls()
    (OUT / 'pilot-calls.json').write_text(json.dumps({'about': 'every physical Codex call of the pilot run '
                                                      'directories bench/ozmap/runs/live-* (build.py)',
                                                      'calls': calls}, indent=1) + '\n', encoding='utf-8')
    (OUT / 'INDEX.json').write_text(json.dumps({'about': __doc__, 'owner_rollouts': index,
                                                'pilot_calls': {'fixture': 'pilot-calls.json', 'count': len(calls)}},
                                               indent=1) + '\n', encoding='utf-8')
    print(json.dumps({'owner_rollouts': len(index), 'calls': len(calls)}))


if __name__ == '__main__':
    main()
