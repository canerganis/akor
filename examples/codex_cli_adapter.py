"""oz.adapter/3 stdio adapter: the request's system and prompt go to stdin of `codex exec`, the reply is its final agent message.

`codex exec` has no system flag, so the system text is prepended to the prompt. The run is read-only, ephemeral and
outside any git repo check; the JSONL event stream on stdout is parsed and only the last agent_message becomes the reply.
Model and effort come from OZ_MODEL and OZ_EFFORT, or from `--model` and `--effort` on the adapter's own command line.

Accounting: usage comes only from the final `turn.completed` event. Recorded runs (bench/codex_kit*/results_*.jsonl)
show that Codex `input_tokens` already INCLUDES `cached_input_tokens`: the same prompt reports the same `input_tokens`
(26786) with `cached_input_tokens` 0 in one run and 7296 in another, and cached is never above input in 82 recorded
calls. So the counters are passed through unchanged (cached is a subset of input, which is also what the worker's
validate_usage assumes) and nothing is added twice. `reasoning_output_tokens` was never above `output_tokens` in
those records, so it is treated as a subset of output; the data cannot prove that, the worker rejects a response
where it is larger. `cache_write_input_tokens` maps to the worker's `cache_creation_input_tokens`. When there is no
turn.completed event, or a counter is missing or not a count, the call's usage is unknown and the response carries no
`usage`; a missing counter is never read as zero.

A non-zero `codex` exit, a failed turn (`turn.failed`) or a missing agent message ends this adapter with a non-zero
exit, so the worker records adapter_exit_<code>; a timeout exits 124; a missing `codex` executable exits 127 with an
explicit diagnostic. A top-level `error` event alone is a recoverable event (for example a reconnect notice): it never
overrides a turn that completed with an agent message. It is only quoted in the diagnostic when no message arrived.

Identity (amendment D7): `--identity` prints one JSON line with the effective backend, model, effort, `codex --version`
and the frozen command-line flags, then exits without any model call, so the host can reconcile the route before
dispatch.

Isolation (council 3 close, Opus N1): every `codex exec` runs in a fresh EMPTY temporary working directory outside any
repository (`-C <dir>`, also its process cwd, plus `--skip-git-repo-check`), created per call and removed afterwards,
so the worker's root holds no gold, admission label or worked AST. The sandbox stays read-only. Because a read-only
sandbox can still read files by absolute path, the event stream is also checked: any JSON event that is not a turn
event, a thread start, a top-level error notice, or an agent_message/reasoning item (a command, file read or change,
MCP tool call, web search, plan or any unknown item) is a leakage violation. Such a call exits EXIT_LEAKAGE (86) with
`oz-leakage:` on stderr and no reply, so its answers are never accepted; the capture keeps the usage and lists every
violating event under "leakage", and the host marks the run's efficiency invalid.

Raw capture: when the runner sets OZ_ENVELOPE_PATH (as for the Claude adapter), a JSON document with the raw codex
stdout (JSONL), stderr, exit status, timeout flag, effective model and effort, `codex --version` and the usage of the
last turn.completed is published there atomically BEFORE the exit code is acted on, so a failed or timed-out call
still keeps its telemetry. On a non-zero exit the usage stays in the capture and is echoed on stderr as
`oz-usage-not-accepted`; it is never put in a response, so the failed call is not accepted.
"""
import json, os, shutil, subprocess, sys, tempfile

REQUIRED = ('input_tokens', 'cached_input_tokens', 'output_tokens')
OPTIONAL = (('cache_write_input_tokens', 'cache_creation_input_tokens'),
            ('reasoning_output_tokens', 'reasoning_output_tokens'))


def usage_from_event(event):
    """Normalized usage from a turn.completed event's usage object, or None when it is unknown."""
    raw = event.get('usage') if isinstance(event, dict) else None
    if not isinstance(raw, dict):
        return None
    usage = {}
    for key in REQUIRED:
        if type(raw.get(key)) is not int or raw[key] < 0:
            return None
        usage[key] = raw[key]
    for key, name in OPTIONAL:
        if key in raw:
            if type(raw[key]) is not int or raw[key] < 0:
                return None
            usage[name] = raw[key]
    return usage


def parse_events(stdout):
    """(reply text or None, usage or None, failure message or None) from the JSONL event stream."""
    reply = usage = failure = None
    for line in stdout.splitlines():
        if not line.startswith('{'):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get('type')
        item = event.get('item')
        if kind == 'item.completed' and isinstance(item, dict) and item.get('type') == 'agent_message':
            reply = item.get('text')
        elif kind == 'turn.completed':
            usage = usage_from_event(event)
        elif kind == 'turn.failed':
            error = event.get('error')
            failure = str(error.get('message') if isinstance(error, dict) else error)
    return reply, usage, failure


# Events a pure text completion may emit. Anything else in the JSON stream is tool, command, file or web activity.
ALLOWED_EVENTS = ('thread.started', 'turn.started', 'turn.completed', 'turn.failed', 'error')
ITEM_EVENTS = ('item.started', 'item.updated', 'item.completed')
ALLOWED_ITEMS = ('agent_message', 'reasoning')
EXIT_LEAKAGE = 86


def leakage(stdout):
    """Every event of the stream that is not plain text generation: [{"line", "type", "item_type"}]. Lines that are not
    JSON objects are not events (codex prints none on stdout with --json) and are ignored here."""
    found = []
    for n, line in enumerate((stdout or '').splitlines()):
        if not line.startswith('{'):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get('type')
        if kind in ALLOWED_EVENTS:
            continue
        item = event.get('item')
        item_type = item.get('type') if isinstance(item, dict) else None
        if kind in ITEM_EVENTS and item_type in ALLOWED_ITEMS:
            continue
        found.append({'line': n, 'type': kind if isinstance(kind, str) else repr(kind),
                      'item_type': item_type if isinstance(item_type, str) else repr(item_type)})
    return found


def last_error(stdout):
    """The message of the last top-level `error` event, or None. It is a diagnostic only, never a failure by itself."""
    found = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line) if line.startswith('{') else None
        except ValueError:
            continue
        if isinstance(event, dict) and event.get('type') == 'error':
            found = str(event.get('message'))
    return found


def reduce(stdout):
    """The adapter response for one event stream: the raw reply text, plus usage only when it is known."""
    reply, usage, failure = parse_events(stdout)
    if failure is not None:
        raise RuntimeError('codex turn failed: ' + failure)
    if not isinstance(reply, str):
        error = last_error(stdout)
        raise RuntimeError('codex produced no agent message' + (f' (last error event: {error})' if error else ''))
    response = {'reply': reply}
    if usage is not None:
        response['usage'] = usage
    return response


def option(argv, flag, env, default):
    if flag in argv and argv.index(flag) + 1 < len(argv):
        return argv[argv.index(flag) + 1]
    return os.environ.get(env, default)


def _publish(path, data):
    temp = path + '.tmp'
    with open(temp, 'wb') as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


def _text(value):
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return value or ''


def codex_version(exe):
    """The `codex --version` output (first 200 characters), or a marker saying why it is unknown."""
    try:
        done = subprocess.run([exe, '--version'], capture_output=True, text=True, encoding='utf-8', timeout=30,
                              stdin=subprocess.DEVNULL)
        return (done.stdout.strip() or done.stderr.strip() or 'unknown')[:200]
    except (OSError, subprocess.SubprocessError) as exc:
        return f'unknown ({type(exc).__name__})'


FLAGS = ('-s', 'read-only', '--skip-git-repo-check', '--ephemeral', '--json', '-C', '<fresh-empty-temp-dir>',
         'tool-events=leakage-exit-86')
MISSING = 'codex executable not found on PATH; install the Codex CLI or fix PATH'


def identity(model, effort, exe):
    """The effective route identity this adapter would dispatch with (no model call)."""
    return {'backend': 'codex', 'model': model, 'effort': effort, 'effort_applicable': True,
            'cli_version': codex_version(exe), 'flags': list(FLAGS)}


def capture_record(*, model, effort, version, stdout, stderr, exit_code, timed_out, workdir=None):
    """The durable raw capture, one JSON document: raw codex stdout (the JSONL event stream), stderr, exit status,
    timeout flag, the effective model and effort, `codex --version`, the usage read from turn.completed (kept even
    when the exit code is non-zero; acceptance is decided by the exit code, not by this field), the isolated working
    directory and every leakage event of the stream."""
    _, usage, _ = parse_events(stdout)
    return {'adapter': 'codex_cli_adapter', 'backend': 'codex', 'model': model, 'effort': effort, 'codex_version': version,
            'exit_code': exit_code, 'timed_out': timed_out, 'stdout': stdout, 'stderr': stderr, 'usage': usage,
            'workdir': workdir, 'leakage': leakage(stdout)}


def _inside_repo(path):
    """True when path or an ancestor holds .git or pyproject.toml (a checkout), or it lies under this adapter's repo."""
    path = os.path.realpath(path)
    here = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    try:
        if os.path.commonpath([os.path.normcase(path), os.path.normcase(here)]) == os.path.normcase(here):
            return True
    except ValueError:
        pass
    probe = path
    while True:
        if os.path.exists(os.path.join(probe, '.git')) or os.path.isfile(os.path.join(probe, 'pyproject.toml')):
            return True
        parent = os.path.dirname(probe)
        if parent == probe:
            return False
        probe = parent


def empty_workdir():
    """A fresh empty directory in the system temp area, outside every repository (else RuntimeError)."""
    path = os.path.realpath(tempfile.mkdtemp(prefix='oz-codex-empty-'))
    if os.listdir(path) or _inside_repo(path):
        shutil.rmtree(path, ignore_errors=True)
        raise RuntimeError(f'the isolated codex working directory {path} is not an empty directory outside any repo')
    return path


def main():
    model = option(sys.argv, '--model', 'OZ_MODEL', 'gpt-6-luna')
    effort = option(sys.argv, '--effort', 'OZ_EFFORT', 'medium')
    exe = shutil.which('codex')
    if exe is None:
        if os.environ.get('OZ_ENVELOPE_PATH'):
            record = capture_record(model=model, effort=effort, version='unknown (codex not found)', stdout='',
                                    stderr=MISSING, exit_code=127, timed_out=False)
            _publish(os.environ['OZ_ENVELOPE_PATH'], json.dumps(record, ensure_ascii=False).encode('utf-8'))
        sys.stderr.write(MISSING)
        sys.exit(127)
    if '--identity' in sys.argv:
        json.dump(identity(model, effort, exe), sys.stdout)
        return
    request = json.load(sys.stdin)
    version = codex_version(exe)
    limit = float(os.environ.get('OZ_CODEX_TIMEOUT', '900'))
    timed_out, code = False, None
    try:
        workdir = empty_workdir()
    except (OSError, RuntimeError) as exc:
        sys.stderr.write(f'codex not launched: {exc}')
        sys.exit(2)
    try:
        try:
            proc = subprocess.run([exe, 'exec', '-m', model, '-c', f'model_reasoning_effort="{effort}"',
                                   '-s', 'read-only', '--skip-git-repo-check', '--ephemeral', '--json', '-C', workdir,
                                   '-'],
                                  input=request['system'] + chr(10) * 2 + request['prompt'], capture_output=True,
                                  text=True, encoding='utf-8', timeout=limit, cwd=workdir)
            stdout, stderr, code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, timed_out = _text(exc.stdout), _text(exc.stderr), True
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    record = capture_record(model=model, effort=effort, version=version, stdout=stdout, stderr=stderr,
                            exit_code=code, timed_out=timed_out, workdir=workdir)
    if os.environ.get('OZ_ENVELOPE_PATH'):
        _publish(os.environ['OZ_ENVELOPE_PATH'], json.dumps(record, ensure_ascii=False).encode('utf-8'))
    if timed_out:
        sys.stderr.write(f'codex timed out after {limit:g} seconds')
        sys.exit(124)
    if record['leakage']:
        sys.stderr.write('oz-leakage: the codex event stream shows tool, command, file or web activity: '
                         + json.dumps(record['leakage'][:20]))
        if record['usage'] is not None:
            sys.stderr.write(chr(10) + 'oz-usage-not-accepted: ' + json.dumps(record['usage']))
        sys.exit(EXIT_LEAKAGE)
    if code:
        _, usage, _ = parse_events(stdout)
        sys.stderr.write(stderr[-2000:])
        if usage is not None:
            sys.stderr.write(chr(10) + 'oz-usage-not-accepted: ' + json.dumps(usage))
        sys.exit(code)
    try:
        response = reduce(stdout)
    except RuntimeError as exc:
        sys.stderr.write(str(exc))
        sys.exit(1)
    json.dump(response, sys.stdout)


if __name__ == '__main__':
    main()
