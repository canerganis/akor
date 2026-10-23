"""Recording and gating oz.adapter/3 wrapper for the code-review pilot. Runs from the run root's snapshot.

adapter.json argv: [python, cr_adapter.py, --archive, DIR, --state, STATE, --, <delegate argv...>]
Like bench/live/k2_adapter.py, the request bytes from oz go to the delegate's stdin untouched and the delegate's stdout
and exit code come back untouched. In addition:

  1. Gate before launch (review fix 1): no delegate is started when STATE/STOP exists or when the run's caller tokens
     (STATE/run.json, kept current by the harness guard) plus the worker tokens already spent (the envelopes kept here)
     plus a sound bound of this call (the UTF-8 bytes of the packet's system and prompt texts, since a token covers at
     least one byte, plus run.json's worker output allowance) would exceed run.json's cap. A refused call prints a
     response with an empty reply and zero usage (nothing was called) and keeps a refusal envelope, so the ledger and
     the envelopes still agree.
  2. The delegate gets OZ_ENVELOPE_PATH=DIR/envelopes/NNNN.json, where examples/claude_cli_adapter.py publishes the raw
     CLI envelope (modelUsage included) before it prints its reduced response.
DIR/packets.jsonl gets one line per call: the request, its sha256, the raw delegate stdout, the exit code, the elapsed
time, the envelope file name and any guard refusal.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ZERO = {'input_tokens': 0, 'cached_input_tokens': 0, 'cache_creation_input_tokens': 0, 'output_tokens': 0}
COUNTERS = ('inputTokens', 'cacheReadInputTokens', 'cacheCreationInputTokens', 'outputTokens')


def spent(envelopes: Path) -> int:
    total = 0
    for path in envelopes.glob('*.json'):
        try:
            mu = json.loads(path.read_text(encoding='utf-8')).get('modelUsage') or {}
        except (OSError, ValueError):
            continue
        for entry in mu.values():
            total += sum(v for k, v in entry.items() if k in COUNTERS and type(v) is int)
    return total


def refusal(state: Path, envelopes: Path, request) -> str | None:
    if (state / 'STOP').exists():
        return 'stop flag set by the harness guard'
    try:
        run = json.loads((state / 'run.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return 'no readable guard state'
    if not isinstance(request, dict):
        return None
    bound = sum(len(str(request.get(k) or '').encode('utf-8')) for k in ('system', 'prompt')) + run['worker_out']
    if run['caller_tokens'] + spent(envelopes) + bound > run['cap']:
        return 'call bound %d would cross the run cap %d' % (bound, run['cap'])
    return None


def main(argv):
    if len(argv) < 6 or argv[0] != '--archive' or argv[2] != '--state' or argv[4] != '--':
        sys.stderr.write('usage: cr_adapter.py --archive DIR --state STATE -- DELEGATE...\n')
        return 2
    archive, state, delegate = Path(argv[1]), Path(argv[3]), argv[5:]
    envelopes = archive / 'envelopes'
    envelopes.mkdir(parents=True, exist_ok=True)
    for n in range(100000):
        envelope = envelopes / f'{n:04d}.json'
        try:
            envelope.open('x').close()
            break
        except FileExistsError:
            continue
    raw = sys.stdin.buffer.read()
    started = time.monotonic()
    try:
        request = json.loads(raw.decode('utf-8'))
    except ValueError:
        request = None
    refused = refusal(state, envelopes, request)
    if refused:
        envelope.write_text(json.dumps({'refused_by_guard': refused, 'modelUsage': {'guard-refusal': dict.fromkeys(
            COUNTERS, 0)}}), encoding='utf-8')
        stdout, stderr, code = json.dumps({'reply': '', 'usage': ZERO}).encode('utf-8'), b'', 0
    else:
        envelope.unlink()
        proc = subprocess.run(delegate, input=raw, capture_output=True, env=dict(os.environ,
                                                                                    OZ_ENVELOPE_PATH=str(envelope)))
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
    entry = {'time': time.time(), 'elapsed_s': round(time.monotonic() - started, 3),
             'request_sha256': hashlib.sha256(raw).hexdigest(), 'request': request,
             'request_raw': None if request is not None else raw.decode('utf-8', 'replace'),
             'exit': code, 'stdout': stdout.decode('utf-8', 'replace'),
             'stderr_tail': stderr.decode('utf-8', 'replace')[-2000:],
             'envelope': envelope.name if envelope.exists() else None, 'refused_by_guard': refused}
    with (archive / 'packets.jsonl').open('a', encoding='utf-8') as file:
        file.write(json.dumps(entry, ensure_ascii=False) + '\n')
    sys.stdout.buffer.write(stdout)
    sys.stdout.flush()
    sys.stderr.buffer.write(stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
