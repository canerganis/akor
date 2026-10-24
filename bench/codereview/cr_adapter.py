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
  2. Unknown spend stops the run (review 2, finding 1): an unreadable or malformed guard state, an earlier envelope
     that is empty, unreadable or lacks a strict counter, or a request whose size cannot be bounded refuses the launch
     and writes STATE/STOP; a call that returns without an envelope holding strict counters writes STATE/STOP after it,
     so nothing further is launched. The harness guard treats that STOP as a 'usage' stop. Nothing is read as zero.
  3. The delegate gets OZ_ENVELOPE_PATH=DIR/envelopes/NNNN.json, where examples/claude_cli_adapter.py publishes the raw
     CLI envelope (modelUsage included) before it prints its reduced response.
DIR/packets.jsonl gets one line per call: the request, its sha256, the raw delegate stdout, the exit code, the elapsed
time, the envelope file name, any guard refusal and whether the call's usage is known.
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


def strict(mu):
    """Summed counters of a modelUsage object, or None when it is missing, empty, or any entry lacks a counter or
    holds a non-integer, negative or boolean value."""
    if not isinstance(mu, dict) or not mu:
        return None
    total = 0
    for entry in mu.values():
        if not isinstance(entry, dict):
            return None
        for key in COUNTERS:
            value = entry.get(key)
            if type(value) is not int or value < 0:
                return None
            total += value
    return total


def envelope_total(path: Path):
    """Strict token total of one kept envelope, or None when it is empty, unreadable or not strict."""
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return strict(data.get('modelUsage')) if isinstance(data, dict) else None


def spent(envelopes: Path, own: Path):
    """Worker tokens already spent in this run, or None when any earlier envelope's usage is unknown."""
    total = 0
    for path in envelopes.glob('*.json'):
        if path == own:
            continue
        value = envelope_total(path)
        if value is None:
            return None
        total += value
    return total


def _count(value) -> bool:
    return type(value) is int and value >= 0


def refusal(state: Path, envelopes: Path, own: Path, request):
    """(reason, unknown) for a call that must not launch, or (None, False). unknown marks a refusal for unknown
    spend, which also stops the run."""
    if (state / 'STOP').exists():
        return 'stop flag set by the harness guard', False
    try:
        run = json.loads((state / 'run.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return 'no readable guard state', True
    if not isinstance(run, dict) or not all(_count(run.get(k)) for k in ('caller_tokens', 'cap', 'worker_out')):
        return 'malformed guard state', True
    if not isinstance(request, dict) or not all(isinstance(request.get(k, ''), str) for k in ('system', 'prompt')):
        return 'the request size cannot be bounded', True
    already = spent(envelopes, own)
    if already is None:
        return 'an earlier worker call has unknown usage', True
    bound = sum(len(request.get(k, '').encode('utf-8')) for k in ('system', 'prompt')) + run['worker_out']
    if run['caller_tokens'] + already + bound > run['cap']:
        return 'call bound %d would cross the run cap %d' % (bound, run['cap']), False
    return None, False


def stop(state: Path) -> None:
    try:
        (state / 'STOP').write_text('usage', encoding='utf-8')
    except OSError:
        pass


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
    refused, unknown = refusal(state, envelopes, envelope, request)
    if unknown:
        stop(state)
    usage_known = True
    if refused:
        envelope.write_text(json.dumps({'refused_by_guard': refused, 'modelUsage': {'guard-refusal': dict.fromkeys(
            COUNTERS, 0)}}), encoding='utf-8')
        stdout, stderr, code = json.dumps({'reply': '', 'usage': ZERO}).encode('utf-8'), b'', 0
    else:
        envelope.unlink()
        proc = subprocess.run(delegate, input=raw, capture_output=True, env=dict(os.environ,
                                                                                    OZ_ENVELOPE_PATH=str(envelope)))
        stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
        usage_known = envelope.exists() and envelope_total(envelope) is not None
        if not usage_known:
            stop(state)
    entry = {'time': time.time(), 'elapsed_s': round(time.monotonic() - started, 3),
             'request_sha256': hashlib.sha256(raw).hexdigest(), 'request': request,
             'request_raw': None if request is not None else raw.decode('utf-8', 'replace'),
             'exit': code, 'stdout': stdout.decode('utf-8', 'replace'),
             'stderr_tail': stderr.decode('utf-8', 'replace')[-2000:],
             'envelope': envelope.name if envelope.exists() else None, 'refused_by_guard': refused,
             'usage_known': usage_known}
    with (archive / 'packets.jsonl').open('a', encoding='utf-8') as file:
        file.write(json.dumps(entry, ensure_ascii=False) + '\n')
    sys.stdout.buffer.write(stdout)
    sys.stdout.flush()
    sys.stderr.buffer.write(stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
