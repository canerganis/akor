"""Recording oz.adapter/3 wrapper for pilot_k2: keeps every worker packet and reply, then delegates unchanged.

adapter.json argv: [python, k2_adapter.py, --archive, DIR, --, <delegate argv...>]
The request bytes from oz go to the delegate's stdin untouched; the delegate's stdout and exit code are passed back
untouched. DIR/packets.jsonl gets one line per call: the request (system, prompt, ids, ...), its sha256, the raw
delegate stdout, the exit code and the elapsed time.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def main(argv):
    if len(argv) < 4 or argv[0] != '--archive' or argv[2] != '--':
        sys.stderr.write('usage: k2_adapter.py --archive DIR -- DELEGATE...\n')
        return 2
    archive, delegate = Path(argv[1]), argv[3:]
    raw = sys.stdin.buffer.read()
    started = time.monotonic()
    proc = subprocess.run(delegate, input=raw, capture_output=True)
    try:
        request = json.loads(raw.decode('utf-8'))
    except ValueError:
        request = None
    entry = {'time': time.time(), 'elapsed_s': round(time.monotonic() - started, 3),
             'request_sha256': hashlib.sha256(raw).hexdigest(), 'request': request,
             'request_raw': None if request is not None else raw.decode('utf-8', 'replace'),
             'exit': proc.returncode, 'stdout': proc.stdout.decode('utf-8', 'replace'),
             'stderr_tail': proc.stderr.decode('utf-8', 'replace')[-2000:]}
    archive.mkdir(parents=True, exist_ok=True)
    with (archive / 'packets.jsonl').open('a', encoding='utf-8') as file:
        file.write(json.dumps(entry, ensure_ascii=False) + '\n')
    sys.stdout.buffer.write(proc.stdout)
    sys.stdout.flush()
    sys.stderr.buffer.write(proc.stderr)
    return proc.returncode


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
