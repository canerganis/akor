"""Recording oz.adapter/3 wrapper for the code-review pilot: keeps every worker packet, reply and raw worker envelope.

adapter.json argv: [python, cr_adapter.py, --archive, DIR, --, <delegate argv...>]
Like bench/live/k2_adapter.py, the request bytes from oz go to the delegate's stdin untouched and the delegate's stdout
and exit code come back untouched. In addition the delegate gets OZ_ENVELOPE_PATH=DIR/envelopes/NNNN.json, where
examples/claude_cli_adapter.py publishes the raw CLI envelope (modelUsage included) before it prints its reduced
response. DIR/packets.jsonl gets one line per call: the request, its sha256, the raw delegate stdout, the exit code,
the elapsed time and the envelope file name.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main(argv):
    if len(argv) < 4 or argv[0] != '--archive' or argv[2] != '--':
        sys.stderr.write('usage: cr_adapter.py --archive DIR -- DELEGATE...\n')
        return 2
    archive, delegate = Path(argv[1]), argv[3:]
    (archive / 'envelopes').mkdir(parents=True, exist_ok=True)
    for n in range(100000):
        envelope = archive / 'envelopes' / f'{n:04d}.json'
        try:
            envelope.open('x').close()
            envelope.unlink()
            break
        except FileExistsError:
            continue
    raw = sys.stdin.buffer.read()
    started = time.monotonic()
    env = dict(os.environ, OZ_ENVELOPE_PATH=str(envelope))
    proc = subprocess.run(delegate, input=raw, capture_output=True, env=env)
    try:
        request = json.loads(raw.decode('utf-8'))
    except ValueError:
        request = None
    entry = {'time': time.time(), 'elapsed_s': round(time.monotonic() - started, 3),
             'request_sha256': hashlib.sha256(raw).hexdigest(), 'request': request,
             'request_raw': None if request is not None else raw.decode('utf-8', 'replace'),
             'exit': proc.returncode, 'stdout': proc.stdout.decode('utf-8', 'replace'),
             'stderr_tail': proc.stderr.decode('utf-8', 'replace')[-2000:],
             'envelope': envelope.name if envelope.exists() else None}
    with (archive / 'packets.jsonl').open('a', encoding='utf-8') as file:
        file.write(json.dumps(entry, ensure_ascii=False) + '\n')
    sys.stdout.buffer.write(proc.stdout)
    sys.stdout.flush()
    sys.stderr.buffer.write(proc.stderr)
    return proc.returncode


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
