"""Sanitize owner rollouts into P3 fixtures: only event timestamps, event types, the session_meta CLI fields with the
account id replaced, task_started/task_complete markers and token_count rate_limits survive. No prompt, reply,
instruction or token text is kept."""
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, r'C:\Users\can02\Projects\akor')
from bench.ozmap_rep import isolation, config
base = isolation.account_sha256(config.BASELINE_DEFAULT)
src = Path.home() / '.codex' / 'sessions'
out = Path(r'C:\Users\can02\Projects\akor\bench\ozmap_rep\tests\fixtures\p3-rollouts')
index = []
for rel, name in [(a.split('=')[0], a.split('=')[1]) for a in sys.argv[1:]]:
    p = src / rel
    raw = p.read_bytes()
    rows = []
    for line in raw.decode('utf-8', 'replace').splitlines():
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
            acct = None if not a else ('acct-fixture-baseline' if hashlib.sha256(a.encode()).hexdigest() == base
                                       else 'acct-fixture-other')
            keep = {k: pl[k] for k in ('cli_version', 'originator') if k in pl}
            if acct:
                keep['creator_account_id'] = acct
            rows.append({'timestamp': e.get('timestamp'), 'type': t, 'payload': keep})
        elif t == 'event_msg' and pl.get('type') in ('task_started', 'task_complete'):
            rows.append({'timestamp': e.get('timestamp'), 'type': t, 'payload': {'type': pl['type']}})
        elif t == 'event_msg' and pl.get('type') == 'token_count':
            rows.append({'timestamp': e.get('timestamp'), 'type': t,
                         'payload': {'type': 'token_count', 'rate_limits': pl.get('rate_limits')}})
        else:
            rows.append({'timestamp': e.get('timestamp'), 'type': t, 'payload': {'type': pl.get('type')}})
    (out / name).write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in rows), encoding='utf-8')
    index.append({'fixture': name, 'source': 'owner ~/.codex/sessions/' + rel, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                  'events': len(rows)})
(out / 'INDEX.json').write_text(json.dumps({'about': __doc__, 'baseline_account': 'acct-fixture-baseline replaces the baseline creator_account_id (hash compared, never printed)', 'files': index}, indent=1) + '\n', encoding='utf-8')
print(json.dumps(index, indent=1))
