"""Opus B 3: compare every frame of a probe capture with the approved effective context."""
import json, sys
from pathlib import Path
sys.path.insert(0, r'C:\Users\can02\Projects\akor')
from bench.ozmap_rep import effective_context as ec
p = Path(sys.argv[1])
d = json.loads(p.read_text(encoding='utf-8'))
print('exit', d['exit_code'], 'argv check', d['frozen_argv_check_before_probe_args'], 'remote', d['non_loopback_connections'], 'proxied', d['proxied'])
print('stderr tail:', d['stderr'][-700:].replace('\n', ' | '))
appr = ec.load()
frames = []
for i, c in enumerate(d['captured']):
    print('request', i, c['method'], c['path'], c.get('websocket'), 'prewarm answered', c.get('ws_prewarm_answered'), 'end', c.get('ws_end'))
    for f in c.get('ws_frames', []):
        if f['opcode'] == 1:
            frames.append((i, json.loads(f['text'])))
        else:
            print('   non text frame opcode', f['opcode'], f['bytes'])
    if c['method'] == 'POST' and c['path'].endswith('/responses'):
        frames.append((i, json.loads(c['body'])))
for k, (i, b) in enumerate(frames):
    print('--- frame', k, 'conn', i, 'keys', sorted(b), 'generate', b.get('generate'), 'previous_response_id', b.get('previous_response_id'), 'items', len(b.get('input', [])))
    for it in b.get('input', []):
        print('     ', it.get('type'), it.get('role'), ec.kinds(it))
    for t in ('websocket_prewarm', 'websocket', 'http'):
        print('   vs', t, ec.context_problems(b, appr, d['prompt'], t))
(p.parent / (p.stem + '.frames.json')).write_text(json.dumps([b for _, b in frames], indent=1, ensure_ascii=False), encoding='utf-8')
