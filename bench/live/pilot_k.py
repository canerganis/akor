"""Arm K (docs/design/foundation-2026-10-23/arm-k-plan.md): a caller agent hands the pilot's jobs to `oz do`.

The caller is `claude -p` with only the Bash tool, the same system prompt and the same plain JSON job text as pilot
arms J and S, plus a short skill text about `oz do`. It must run `oz do` and reply in the plain JSON result format.
Cost = caller tokens (modelUsage, all turns) + worker tokens (the `oz do` call ledgers under the run's workspace).
Usage: N=16 SEEDS=3005-3007 OUT=pilot_k_sonnet16.jsonl python bench/live/pilot_k.py
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pilot2 as P
import live11 as M
import run_live as L

REPO = Path(__file__).resolve().parents[2]
N = int(os.environ.get('N', '16'))
lo, hi = map(int, os.environ.get('SEEDS', '3005-3007').split('-'))
SEEDS = list(range(lo, hi + 1))
MODEL = L.MODEL_IDS[os.environ.get('MODEL', 'sonnet')]
OUT = M.X.V.LIVE / 'data' / os.environ.get('OUT', 'pilot_k_sonnet16.jsonl')
K_TEXT = (
    'You have the `oz` command. It runs many small independent jobs in one batched model call. Do not answer any '
    'job yourself. Write one request file and run `oz do request.json --adapter adapter.json` once in the current '
    'directory. Request format (JSON): {"model":"%s","goal":"<the goal>","ops":{"<name>":"<instruction for the '
    'job, written for one reference>"},"refs":{"<name>":"<reference text>"},"jobs":[["<message ID>","<op name>",'
    '"<ref name>"],...]}. One job per message ID; an op is an instruction shared by jobs that ask the same thing of '
    'different references. The command prints JSON; jobs[<ID>].status is accepted, failed or unresolved, and '
    'jobs[<ID>].value is the result. Report accepted values with status 0, failed jobs with status 2 and unresolved '
    'jobs with status 1, in the reply format stated at the end.\n\n') % MODEL
OZ_SH = '#!/bin/sh\nexec "%s" -c "import sys, oz_cli; sys.exit(oz_cli.main())" "$@"\n'


def setup(tmp):
    """A fresh oz workspace with an `oz` wrapper on PATH and an adapter file using the repo's Claude adapter."""
    ws = Path(tmp) / 'ws'
    py = Path(sys.executable).resolve()
    env = dict(os.environ, PYTHONPATH=str(REPO), OZ_MODEL=MODEL, TIKTOKEN_CACHE_DIR=str(REPO / '.token-cache'))
    subprocess.run([str(py), '-c', 'import sys, oz_cli; sys.exit(oz_cli.main())', 'init', str(ws)], env=env,
                   check=True, capture_output=True)
    bin_dir = Path(tmp) / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'oz').write_text(OZ_SH % py.as_posix(), encoding='utf-8', newline='\n')
    (ws / 'adapter.json').write_text(json.dumps({'argv': [py.as_posix(), (REPO / 'examples' / 'claude_cli_adapter.py').as_posix()],
                                                 'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}), encoding='utf-8')
    env['PATH'] = str(bin_dir) + os.pathsep + env['PATH']
    return ws, env


def worker_usage(ws):
    calls = inn = out = 0
    for ledger in ws.glob('do/*/calls.jsonl'):
        for line in ledger.read_text(encoding='utf-8').splitlines():
            ev = json.loads(line)
            u = (ev.get('usage') or {}).get('raw') if ev.get('event') == 'call_end' else None
            if u:
                calls += 1
                inn += u.get('input_tokens', 0)
                out += u.get('output_tokens', 0)
    return calls, inn, out


def caller(prompt, ws, env):
    start = time.monotonic()
    cmd = [L.CLAUDE, '-p', '--model', MODEL, '--system-prompt', L.SYSTEM, '--tools', 'Bash', '--allowedTools', 'Bash',
           '--setting-sources', '', '--strict-mcp-config', '--no-session-persistence', '--output-format', 'stream-json', '--verbose']
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8', cwd=ws, env=env, timeout=900)
    final, bash = None, 0
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get('type') == 'assistant':
            bash += sum(1 for b in ev['message'].get('content', []) if b.get('type') == 'tool_use' and b.get('name') == 'Bash')
        if ev.get('type') == 'result':
            final = ev
    mu = (final or {}).get('modelUsage') or {}
    tot = lambda f: sum(m.get(f, 0) for m in mu.values())
    return {'text': (final or {}).get('result', ''), 'wall_s': round(time.monotonic() - start, 2), 'bash_calls': bash,
            'turns': (final or {}).get('num_turns'), 'caller_in': tot('inputTokens') + tot('cacheReadInputTokens') + tot('cacheCreationInputTokens'),
            'caller_cache_read': tot('cacheReadInputTokens'), 'caller_out': tot('outputTokens')}


def main():
    plan = []
    h = hashlib.sha256()
    for seed in SEEDS:
        M.use_records(M.make_records(seed))
        system, user, dec, native = M.ARMS['0.8-exec'](N)
        plan.append((seed, K_TEXT + user, dec, native, M.X.V.jobs('materials', N)))
        h.update(json.dumps([seed, L.SYSTEM, K_TEXT + user], ensure_ascii=False).encode('utf-8'))
    cli = subprocess.run([L.CLAUDE, '--version'], capture_output=True, text=True).stdout.strip()
    man = {'model': MODEL, 'n': N, 'seeds': SEEDS, 'sha256': h.hexdigest(), 'cli_version': cli, 'concurrency': 1}
    OUT.with_suffix('.manifest.json').write_text(json.dumps(man, indent=1), encoding='utf-8')
    print('manifest', man['sha256'], flush=True)
    for seq, (seed, prompt, dec, native, js) in enumerate(plan):
        tmp = tempfile.mkdtemp(prefix='ozk-')
        try:
            ws, env = setup(tmp)
            r = caller(prompt, ws, env)
            calls, w_in, w_out = worker_usage(ws)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        err, ok = P.judge(dec, r['text'], js, native)
        rec = {'seq': seq, 'seed': seed, 'arm': 'K', 'n': N, 'valid': not err, 'error': err, 'jobs_passed': ok, 'jobs': N,
               'worker_calls': calls, 'worker_in': w_in, 'worker_out': w_out,
               'in': r['caller_in'] + w_in, 'out': r['caller_out'] + w_out, 'manifest': man['sha256'], **r}
        with OUT.open('a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        print(seq, seed, 'ok' if not err else 'FAIL ' + err, f'{ok}/{N}', 'caller', r['caller_in'], r['caller_out'],
              'worker', calls, w_in, w_out, 'bash', r['bash_calls'], 'wall', r['wall_s'], flush=True)


if __name__ == '__main__':
    main()
