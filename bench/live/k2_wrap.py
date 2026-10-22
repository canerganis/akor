"""Bench `oz` wrapper for the caller-cost experiment (docs/design/caller-cost-2026-10-23, rounds 03 and 04).

pilot_k2.py puts a shell shim named `oz` on the caller's PATH that runs:
    python k2_wrap.py --archive DIR [--legacy] <the caller's arguments>

`oz do [REQUEST|-] --adapter A [--workspace W] [--allow D] [--receipt]` runs oz_do.do() once, then publishes the full
result atomically to results.json in the current directory (temp file, fsync, os.replace) with a sha256 sidecar
results.json.sha256. Without --receipt it prints the full result, byte for byte what `oz do` prints. With --receipt it
prints an oz.do.receipt/1 object of at most RECEIPT_BYTES UTF-8 bytes (see receipt()). Exit codes are oz do's: 0 when
every job is accepted, 3 otherwise, 2 on an error (nothing is published then).

--legacy (arm K0) and every command other than `do` delegate to oz_cli.main unchanged. Every invocation is archived
under DIR (argv, raw request bytes, stdout, stderr, exit code, published digest) so each run keeps every request.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

RECEIPT_SCHEMA = 'oz.do.receipt/1'
RECEIPT_BYTES = 2048
MAX_LISTED = 32
# Explicit byte budgets for every variable-length field (JSON-encoded size, quotes included). With these, the fixed
# part of a receipt stays under 1,500 bytes for any input (tests/test_pilot_k2.py checks adversarial inputs), which
# leaves room for at least eight 64-character job IDs.
PATH_BYTES = 256          # artifact path; longer paths keep their tail behind '...'
ID_BYTES = 66             # request_id (valid IDs are at most 64 characters)
SHORT_BYTES = 34          # status, evidence scope, usage coverage, count keys
REASON_BYTES = 50         # blocker reason
BLOCKER_KEYS = 3          # blocker fields besides reason, sorted by name
BLOCKER_KEY_BYTES = 34
BLOCKER_VALUE_BYTES = 66
COUNT_KEYS = 4


def J(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def size(value):
    return len(J(value).encode('utf-8'))


def fit(text, budget, tail=False):
    """(text, truncated): text whose JSON encoding fits budget bytes; a cut keeps the head (or tail) plus '...'."""
    text = text if isinstance(text, str) else J(text)
    if size(text) <= budget:
        return text, False
    lo, hi = 0, len(text)
    while lo < hi:   # the longest kept part that fits
        mid = (lo + hi + 1) // 2
        cut = '...' + text[len(text) - mid:] if tail else text[:mid] + '...'
        lo, hi = (mid, hi) if size(cut) <= budget else (lo, mid - 1)
    return ('...' + text[len(text) - lo:] if tail else text[:lo] + '...'), True


def _int(value):
    return value if type(value) is int else None


def receipt(result, path, nbytes, sha256):
    """oz.do.receipt/1 for a do() result whose full JSON was published at path (nbytes bytes, sha256).

    Fields: status, job count, counts by status, non-accepted IDs in job order (as many complete IDs as fit, at most
    32, plus total and omitted counts), artifact path/bytes/sha256, request_id and request sha256, evidence scope,
    accounting coverage and token totals, blocker, and the names of any truncated fields. No values. At most
    RECEIPT_BYTES UTF-8 bytes for any input."""
    truncated = []

    def short(name, value, budget=SHORT_BYTES, tail=False):
        if value is None:
            return None
        text, cut = fit(value, budget, tail)
        if cut:
            truncated.append(name)
        return text

    jobs = result.get('jobs') if isinstance(result.get('jobs'), dict) else {}
    counts = {}
    for i, (key, value) in enumerate(sorted((result.get('counts') or {}).items())):
        if i == COUNT_KEYS:
            truncated.append('counts')
            break
        counts[short('counts', key)] = _int(value)
    pending = [mid for mid, out in jobs.items() if not (isinstance(out, dict) and out.get('status') == 'accepted')]
    run = result.get('run') if isinstance(result.get('run'), dict) else {}
    acc = result.get('accounting') if isinstance(result.get('accounting'), dict) else {}
    tokens = acc.get('tokens') if isinstance(acc.get('tokens'), dict) else {}
    blocker = result.get('blocker')
    if isinstance(blocker, dict):
        small = {'reason': short('blocker', blocker.get('reason'), REASON_BYTES)}
        extra = sorted(k for k in blocker if k != 'reason')
        if len(extra) > BLOCKER_KEYS:
            truncated.append('blocker')
        for key in extra[:BLOCKER_KEYS]:
            value = blocker[key]
            if not (value is None or type(value) in (int, bool) or isinstance(value, float)):
                value = short('blocker', value, BLOCKER_VALUE_BYTES)
            small[short('blocker', str(key), BLOCKER_KEY_BYTES)] = value
        blocker = small
    elif blocker is not None:
        blocker = short('blocker', blocker, REASON_BYTES)
    evidence = result.get('evidence') if isinstance(result.get('evidence'), dict) else {}
    out = {'schema': RECEIPT_SCHEMA,
           'status': short('status', result.get('status')),
           'jobs': len(jobs),
           'counts': counts,
           'not_accepted': {'total': len(pending), 'listed': [], 'omitted': len(pending)},
           'artifact': {'path': short('artifact.path', str(path), PATH_BYTES, tail=True), 'bytes': _int(nbytes),
                        'sha256': short('artifact.sha256', sha256, 66)},
           'request': {'request_id': short('request.request_id', run.get('request_id'), ID_BYTES),
                       'sha256': short('request.sha256', run.get('request_sha256'), 66)},
           'evidence': short('evidence', evidence.get('scope')),
           'accounting': {'usage_coverage': short('accounting', acc.get('usage_coverage')),
                          'calls': _int(acc.get('calls')), 'failed_calls': _int(acc.get('failed_calls')),
                          'input_tokens': _int(tokens.get('input_tokens')),
                          'output_tokens': _int(tokens.get('output_tokens'))},
           'blocker': blocker,
           'truncated': sorted(set(truncated))}
    listed = out['not_accepted']['listed']
    for mid in pending[:MAX_LISTED]:
        if not isinstance(mid, str) or len(mid) > 64:
            break   # job IDs come from a validated request; anything else is not listed
        listed.append(mid)
        out['not_accepted']['omitted'] = len(pending) - len(listed)
        if size(out) > RECEIPT_BYTES:
            listed.pop()
            out['not_accepted']['omitted'] = len(pending) - len(listed)
            break
    if size(out) > RECEIPT_BYTES:   # unreachable with the budgets above; never print an oversized receipt
        raise AssertionError('receipt over budget')
    return J(out)


def publish(path, data):
    """Write data to path atomically (same-directory temp file, fsync, os.replace); returns its sha256 hex.
    On any failure the previous file, if any, is left as it was and the temp file is removed."""
    path = Path(path)
    temp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        with open(temp, 'xb') as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temp.unlink()
        raise
    digest = hashlib.sha256(data).hexdigest()
    side = path.with_name(path.name + '.sha256')
    stemp = side.with_name(f'.{side.name}.{uuid.uuid4().hex}.tmp')
    stemp.write_bytes(f'{digest}  {path.name}\n'.encode('ascii'))
    os.replace(stemp, side)
    return digest


class Archive:
    """One directory per invocation under root: argv.json, request.bin, stdout.txt, stderr.txt, meta.json."""

    def __init__(self, root):
        self.dir = None
        if root:
            base = Path(root)
            base.mkdir(parents=True, exist_ok=True)
            for i in range(10000):
                try:
                    (base / f'{i:04d}').mkdir()
                    self.dir = base / f'{i:04d}'
                    break
                except FileExistsError:
                    continue

    def put(self, name, data):
        if self.dir is not None:
            (self.dir / name).write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))


def _do_args(argv):
    p = argparse.ArgumentParser(prog='oz do', add_help=False)
    p.add_argument('request', nargs='?', default='-')
    p.add_argument('--workspace', type=Path, default=Path('.'))
    p.add_argument('--adapter', type=Path, required=True)
    p.add_argument('--allow', type=Path)
    p.add_argument('--receipt', action='store_true')
    p.add_argument('--out', default='results.json')
    return p.parse_args(argv)


def run_do(argv, stdin, stdout, stderr, archive):
    """The `do` command in full or receipt mode; returns the exit code."""
    from oz import Error
    from oz_do import do
    from oz_reply import dumps
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            args = _do_args(argv)
    except SystemExit:
        stderr.write('oz: usage: oz do [REQUEST|-] --adapter ADAPTER [--workspace W] [--allow D] [--receipt]\n')
        return 2
    try:
        raw = stdin.read() if args.request == '-' else Path(args.request).read_bytes()
    except OSError as exc:
        stderr.write(f'oz: {exc}\n')
        return 2
    archive.put('request.bin', raw)
    try:
        result = do(raw.decode('utf-8'), workspace=args.workspace, adapter=args.adapter, allow=args.allow)
    except (Error, OSError, ValueError, TypeError, sqlite3.Error) as exc:
        stderr.write(f'oz: {exc}\n')
        return 2
    body = dumps(result, ensure_ascii=False, separators=(',', ':'))
    data = (body + '\n').encode('utf-8')
    try:
        digest = publish(args.out, data)
    except OSError as exc:
        stderr.write(f'oz: cannot publish {args.out}: {exc}\n')
        return 2
    archive.put('published.json', J({'path': args.out, 'bytes': len(data), 'sha256': digest}))
    stdout.write((receipt(result, args.out, len(data), digest) if args.receipt else body) + '\n')
    return 0 if result['counts'].get('accepted', 0) == len(result['jobs']) else 3


def main(argv=None, stdin=None, stdout=None, stderr=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    stdin = stdin if stdin is not None else sys.stdin.buffer
    out_real, err_real = stdout or sys.stdout, stderr or sys.stderr
    root, legacy = None, False
    while argv and argv[0] in ('--archive', '--legacy'):
        if argv[0] == '--archive':
            root, argv = argv[1], argv[2:]
        else:
            legacy, argv = True, argv[1:]
    archive = Archive(root)
    archive.put('argv.json', J({'argv': argv, 'legacy': legacy, 'cwd': os.getcwd(), 'time': time.time()}))
    out, err = io.StringIO(), io.StringIO()
    started = time.monotonic()
    if argv[:1] == ['do'] and not legacy:
        code = run_do(argv[1:], stdin, out, err, archive)
    else:
        import oz_cli
        raw = None
        if argv[:1] == ['do']:   # keep the request bytes for the archive, then hand them to oz_cli unchanged
            p = argparse.ArgumentParser(add_help=False)
            p.add_argument('request', nargs='?', default='-')
            for flag in ('--workspace', '--adapter', '--allow'):
                p.add_argument(flag)
            try:
                source = p.parse_known_args(argv[1:])[0].request
            except SystemExit:
                source = '-'
            if source == '-':
                raw = stdin.read()
            else:
                with contextlib.suppress(OSError):
                    archive.put('request.bin', Path(source).read_bytes())
        if raw is not None:
            archive.put('request.bin', raw)
        fake_in = io.TextIOWrapper(io.BytesIO(raw or b''), encoding='utf-8')
        saved = sys.stdin
        sys.stdin = fake_in
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = oz_cli.main(argv)
                except SystemExit as exc:   # argparse errors
                    code = exc.code if isinstance(exc.code, int) else 2
        finally:
            sys.stdin = saved
    archive.put('stdout.txt', out.getvalue())
    archive.put('stderr.txt', err.getvalue())
    archive.put('meta.json', J({'exit': code, 'mode': 'legacy' if legacy or argv[:1] != ['do'] else
                                ('receipt' if '--receipt' in argv else 'full'),
                                'elapsed_s': round(time.monotonic() - started, 3)}))
    out_real.write(out.getvalue())
    err_real.write(err.getvalue())
    out_real.flush()
    return code


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
