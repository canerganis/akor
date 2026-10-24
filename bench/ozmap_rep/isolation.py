"""A4.2: Codex isolation and authentication. Standard library only.

Worker CODEX_HOME directories are rebuilt before every call from an authentication only baseline (only auth.json is
ever copied), working directories are emptied, the child environment is allowlisted, and every launch is verified
against the frozen executable and argument hashes. Authentication changes are detected by hash, reconciled and
propagated under an exclusive lock. Only hashes and file names are ever logged; no token text leaves the baseline and
the worker homes.
"""
from __future__ import annotations

import base64
import contextlib
import datetime as dt
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time

from . import config

AUTH = 'auth.json'
INSTRUCTION_NAMES = ('AGENTS.md', 'AGENTS.override.md', 'CLAUDE.md')
SLOT_RE = re.compile(r'slot-[0-9]+\Z')
LOGIN_HINT = 'the owner must run: CODEX_HOME={baseline} codex login'


class IsolationError(Exception):
    pass


class LockTimeout(IsolationError):
    pass


class StaleAuth(IsolationError):
    pass


class ExpUnreadable(IsolationError):
    pass


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


# ------------------------------------------------------------------------------------------------------- locking

def _try_lock(handle) -> bool:
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(handle):
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextlib.contextmanager
def file_lock(path, timeout=30.0, poll=0.02):
    """Exclusive OS lock on `path` across handles, threads and processes (LockFileEx through msvcrt, or flock).
    Raises LockTimeout when it is not obtained within `timeout` seconds (None waits forever)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, 'a+b')
    end = None if timeout is None else time.monotonic() + timeout
    try:
        while not _try_lock(handle):
            if end is not None and time.monotonic() >= end:
                raise LockTimeout(f'lock {path.name} not obtained within {timeout:g} s')
            time.sleep(poll)
        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()


def auth_lock(path, timeout=30.0):
    """The authentication lock (A4.2): covers reconstruction and propagation, never execution."""
    return file_lock(path, timeout)


# ------------------------------------------------------------------------------------------------ auth documents

def _read_auth(path):
    try:
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _parse_time(value):
    if not isinstance(value, str):
        return None
    text = value.strip().replace('Z', '+00:00')
    try:
        stamp = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return stamp


def baseline_exp(baseline) -> dt.datetime:
    """The exp claim of the baseline access token as an aware UTC datetime. Raises ExpUnreadable (whose message never
    holds token text) when the file, the token or the claim is missing or malformed."""
    doc = _read_auth(Path(baseline) / AUTH)
    if doc is None:
        raise ExpUnreadable('baseline auth.json missing or not a JSON object')
    tokens = doc.get('tokens')
    token = tokens.get('access_token') if isinstance(tokens, dict) else None
    if not isinstance(token, str) or token.count('.') != 2:
        raise ExpUnreadable('baseline access token missing or not a JWT')
    try:
        payload = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)).decode('utf-8'))
    except (ValueError, UnicodeError, TypeError):
        raise ExpUnreadable('baseline access token payload unreadable') from None
    exp = claims.get('exp') if isinstance(claims, dict) else None
    if type(exp) not in (int, float) or isinstance(exp, bool):
        raise ExpUnreadable('baseline access token has no numeric exp claim')
    try:
        return dt.datetime.fromtimestamp(exp, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise ExpUnreadable('baseline access token exp out of range') from None


def wave_gate(baseline, now=None) -> dict:
    """A4.2 wave launch gate: ok only when the baseline access token exp is at least 48 hours away. Returns only the
    timestamp, the hours left and a reason (with the reseeding command on failure); never token material."""
    now = now or dt.datetime.now(dt.timezone.utc)
    hint = LOGIN_HINT.format(baseline=Path(baseline))
    try:
        exp = baseline_exp(baseline)
    except ExpUnreadable as exc:
        return {'ok': False, 'exp': None, 'hours_left': None, 'reason': f'{exc}; {hint}'}
    hours = (exp - now).total_seconds() / 3600.0
    if exp >= now + dt.timedelta(hours=config.EXP_MARGIN_HOURS):
        return {'ok': True, 'exp': exp.strftime('%Y-%m-%dT%H:%M:%SZ'), 'hours_left': round(hours, 2), 'reason': None}
    return {'ok': False, 'exp': exp.strftime('%Y-%m-%dT%H:%M:%SZ'), 'hours_left': round(hours, 2),
            'reason': f'baseline access token expires in {hours:.1f} h, less than {config.EXP_MARGIN_HOURS} h; '
                      f'{hint}'}


def auth_record(baseline) -> dict:
    """What A4.2 records after a reseed: the auth.json hash, last_refresh and exp. No token text."""
    path = Path(baseline) / AUTH
    doc = _read_auth(path)
    try:
        exp = baseline_exp(baseline).strftime('%Y-%m-%dT%H:%M:%SZ')
    except ExpUnreadable:
        exp = None
    return {'auth_sha256': sha256_file(path) if path.exists() else None,
            'last_refresh': (doc or {}).get('last_refresh') if isinstance((doc or {}).get('last_refresh'), str)
            else None, 'exp': exp}


def load_inventory(path=None):
    path = Path(path or config.BASELINE_INVENTORY_FILE)
    if not path.exists():
        return []
    return list(json.loads(path.read_text(encoding='utf-8')).get('allowed', []))


def verify_baseline(baseline, frozen_inventory=None) -> list:
    """Problems with the baseline inventory: auth.json must exist; anything else must match the frozen inventory
    (relative posix paths or fnmatch patterns). Names only, never contents."""
    baseline = Path(baseline)
    allowed = list(frozen_inventory or [])
    problems = []
    if not (baseline / AUTH).is_file():
        problems.append({'problem': 'missing', 'path': AUTH})
    if not baseline.is_dir():
        return problems or [{'problem': 'missing', 'path': str(baseline)}]
    for path in sorted(baseline.rglob('*')):
        rel = path.relative_to(baseline).as_posix()
        if rel == AUTH:
            continue
        if any(fnmatch.fnmatchcase(rel, pattern) for pattern in allowed):
            continue
        problems.append({'problem': 'not in the frozen baseline inventory', 'path': rel})
    return problems


# ---------------------------------------------------------------------------------------------- environment, argv

def child_env(home, base_env, extra=()) -> dict:
    """The allowlisted child environment of a Codex call. CODEX_HOME, HOME and USERPROFILE are the worker home."""
    allow = {k.upper() for k in config.ENV_ALLOWLIST} | {k.upper() for k in extra}
    env = {}
    for key, value in (base_env or {}).items():
        if key.upper() in allow and key.upper() not in ('HOME', 'USERPROFILE', 'CODEX_HOME'):
            env[key] = value
    env['CODEX_HOME'] = str(home)
    env['HOME'] = str(home)
    env['USERPROFILE'] = str(home)
    return env


def sonnet_env(base_env) -> dict:
    """The child environment of a Sonnet call: the allowlist plus the profile directories its login needs."""
    allow = {k.upper() for k in config.ENV_ALLOWLIST + config.SONNET_ENV_EXTRA}
    return {k: v for k, v in (base_env or {}).items() if k.upper() in allow}


def instruction_scan(workdir) -> tuple:
    """(found, unreadable): instruction files Codex or Claude could discover (AGENTS.md, AGENTS.override.md and
    CLAUDE.md in the working directory and every ancestor), and the locations whose state could not be read. An
    unreadable location is never treated as absent (council round 1, item 7)."""
    found, unreadable = [], []
    here = Path(workdir).resolve()
    for d in [here, *here.parents]:
        for name in INSTRUCTION_NAMES:
            p = d / name
            try:
                os.stat(p)
            except (FileNotFoundError, NotADirectoryError):
                continue
            except OSError:
                unreadable.append(p)
                continue
            found.append(p)
    return found, unreadable


def instruction_sources(workdir) -> list:
    """Instruction files reachable from the working directory, plus every location that could not be read (fail
    closed: an unreadable ancestor blocks the launch like an instruction file would)."""
    found, unreadable = instruction_scan(workdir)
    return found + unreadable


def effort_arg(effort) -> str:
    return f'model_reasoning_effort="{effort}"'


def codex_argv(exe, model, effort, workdir, disable_options=()) -> list:
    return [str(exe), *config.FROZEN_ARGS, str(workdir), '-m', model, '-c', effort_arg(effort), *disable_options, '-']


def plan_disable_options(supported) -> tuple:
    """(args, unsupported): `--disable <f>` for every DISABLE_FEATURES entry the pinned CLI supports, plus
    `-c project_doc_max_bytes=0` when accepted; everything else is recorded as unsupported."""
    supported = set(supported)
    args, unsupported = [], []
    for name in config.DISABLE_FEATURES:
        if name in supported:
            args += ['--disable', name]
        else:
            unsupported.append(name)
    if config.PROJECT_DOC_OPTION in supported:
        args += ['-c', config.PROJECT_DOC_ARG]
    else:
        unsupported.append(config.PROJECT_DOC_OPTION)
    return args, unsupported


def argv_check(argv) -> list:
    """Problems of an argv against the frozen form; [] when it is exactly the canonical argv with accepted disable
    options. argv[0] (the executable) is verified separately by hash."""
    problems = []
    argv = [str(a) for a in argv]
    head = config.FROZEN_ARGS
    if len(argv) < 1 + len(head) + 6:
        return ['argv too short']
    if argv[1:1 + len(head)] != head:
        problems.append('frozen argument head differs')
    i = 1 + len(head)
    workdir = argv[i]
    if not SLOT_RE.fullmatch(Path(workdir).name):
        problems.append('working directory is not a numbered slot directory')
    rest = argv[i + 1:]
    if rest[:4] != ['-m', config.CODEX_MODEL, '-c', effort_arg(config.CODEX_EFFORT)]:
        problems.append('model or effort differs from the frozen route')
    tail = rest[4:]
    if not tail or tail[-1] != '-':
        problems.append('prompt must come from stdin (-) as the last argument')
    options = tail[:-1]
    if len(options) % 2:
        problems.append('unpaired option')
    seen = set()
    for j in range(0, len(options) - 1, 2):
        flag, value = options[j], options[j + 1]
        if flag == '--disable' and value in config.DISABLE_FEATURES and value not in seen:
            seen.add(value)
        elif flag == '-c' and value == config.PROJECT_DOC_ARG and value not in seen:
            seen.add(value)
        else:
            problems.append(f'argument not in the frozen list: {flag} {value}')
    return problems


def argv_sha256(argv) -> str:
    """SHA256 of the argv with the working directory (the value after -C) normalized away."""
    argv = [str(a) for a in argv]
    out = list(argv)
    if '-C' in out:
        k = out.index('-C')
        if k + 1 < len(out):
            out[k + 1] = '<workdir>'
    return hashlib.sha256(json.dumps(out, ensure_ascii=False).encode('utf-8')).hexdigest()


def verify_launch(*, argv, env, workdir, exe_sha256, frozen) -> list:
    """Every pre-launch check of A4.2: executable and argument hashes, allowlisted environment, a worker home that
    holds only auth.json, an empty working directory equal to the -C argument, and no instruction file in the working
    directory or any ancestor. Any problem prevents the launch."""
    problems = list(argv_check(argv))
    if argv_sha256(argv) != frozen.get('argv_sha256'):
        problems.append('argument hash differs from the frozen argument hash')
    if exe_sha256 != frozen.get('exe_sha256'):
        problems.append('executable hash differs from the frozen executable hash')
    allowed = {k.upper() for k in config.ENV_ALLOWLIST} | {'CODEX_HOME'}
    extra = sorted(k for k in env if k.upper() not in allowed)
    if extra:
        problems.append(f'environment outside the allowlist: {extra}')
    home = env.get('CODEX_HOME')
    if not home or not Path(home).is_dir():
        problems.append('CODEX_HOME missing')
    else:
        listing = sorted(os.listdir(home))
        if listing != [AUTH]:
            problems.append(f'worker home holds more than auth.json: {listing}')
        problems += env_selection_problems(env, home)
    if argv and not Path(str(argv[0])).is_absolute():
        problems.append('the executable is not an absolute path (PATH would select it)')
    work = Path(workdir)
    if not work.is_dir():
        problems.append('working directory missing')
    elif os.listdir(work):
        problems.append('working directory is not empty')
    if '-C' in argv:
        k = list(argv).index('-C')
        if k + 1 < len(argv) and Path(str(argv[k + 1])).resolve() != work.resolve():
            problems.append('-C argument is not the prepared working directory')
    found, unreadable = instruction_scan(work)
    if found:
        problems.append(f'instruction files reachable from the working directory: {[str(p) for p in found]}')
    if unreadable:
        problems.append(f'instruction locations that could not be read (fail closed): {[str(p) for p in unreadable]}')
    return problems


def env_selection_problems(env, home) -> list:
    """Environment values that select executables or configuration sources (council round 1, item 7): CODEX_HOME,
    HOME and USERPROFILE must all be the worker home, and no value may point into an owner Codex or Claude
    configuration directory or the baseline."""
    problems = []
    want = Path(home).resolve()
    for key in ('CODEX_HOME', 'HOME', 'USERPROFILE'):
        value = next((v for k, v in env.items() if k.upper() == key), None)
        if value is None or Path(value).resolve() != want:
            problems.append(f'{key} is not the worker home')
    owner = []
    for o in (Path.home() / '.codex', Path.home() / '.claude', config.BASELINE_DEFAULT):
        try:
            owner.append(o.resolve())
        except OSError:
            continue
    for key, value in env.items():
        if key.upper() in ('PATH', 'PATHEXT'):
            # PATH only resolves helper programs; the pinned CLI itself is installed under ~/.codex/packages and is
            # launched by its absolute, hash verified path (argv[0]), never through PATH.
            continue
        for part in str(value).split(os.pathsep):
            if not part:
                continue
            try:
                rp = Path(part).resolve()
            except (OSError, ValueError):
                continue
            if any(rp == o or o in rp.parents for o in owner):
                problems.append(f'{key} points into an owner configuration directory or the baseline')
    return sorted(set(problems))


def executable_identity(exe) -> dict:
    """The executable that will actually run, hashed now: its resolved path, its SHA256 and the SHA256 of its launcher
    payload, every file beside it named after it or loaded by it (codex-code-mode-host.exe, libraries). Council round 1, item 7: computed
    before every launch group, never cached from runner start."""
    real = Path(exe).resolve()
    payload = {}
    stem = real.stem.lower()
    try:
        siblings = sorted(p for p in real.parent.iterdir() if p.is_file() and p != real
                          and (p.name.lower().startswith((stem + '-', stem + '_', stem + '.'))
                               or p.suffix.lower() in ('.dll', '.so', '.dylib', '.node')))
    except OSError:
        siblings = []
    for p in siblings:
        try:
            payload[p.name] = sha256_file(p)
        except OSError:
            payload[p.name] = None
    return {'path': str(real), 'sha256': sha256_file(real), 'payload': payload}


def telemetry_checks(evidence) -> list:
    """A4.2: telemetry must establish that the pinned CLI reads authentication from CODEX_HOME (not an OS credential
    store) and that its read only sandbox starts with clean home state. Missing evidence is a failure. This is the
    boolean summary; telemetry_certificate() is what live cells require."""
    evidence = evidence or {}
    problems = []
    if evidence.get('auth_read_from_codex_home') is not True:
        problems.append('telemetry did not establish that authentication is read from CODEX_HOME')
    if evidence.get('sandbox_clean_home') is not True:
        problems.append('telemetry did not establish that the read only sandbox starts with clean home state')
    return problems


def _matches(rel, patterns):
    return any(fnmatch.fnmatchcase(rel, pat) or fnmatch.fnmatchcase(Path(rel).name, pat) for pat in patterns)


def startup_instruction_files(runtime_files) -> list:
    """Runtime files written by the CLI that could carry instructions (names only), less the signed exceptions."""
    return sorted(rel for rel in (runtime_files or ())
                  if _matches(rel, config.INSTRUCTION_BEARING) and not _matches(rel, config.SIGNED_STARTUP_FILES))


def telemetry_certificate(evidence) -> list:
    """Council round 1, item 1: certification from evidence tied to the pinned execution path, never from the two
    booleans alone. Everything is metadata (no token text).

    Authentication: the frozen exec argv with an empty CODEX_HOME ended in an authentication failure without a reply
    or usage (no alternative credential source on the exec route); `login status` with an empty home reported not
    logged in before and after the call (the call left no credential in an OS store) and logged in with the worker
    home. Instructions: the worker home held exactly auth.json at launch, the working directory was empty, no
    instruction file was reachable, the stream was plain, and no instruction bearing file appeared among the runtime
    files written at startup (less config.SIGNED_STARTUP_FILES). Lifecycle: the call was reconciled before the
    certificate was published."""
    ev = evidence or {}
    problems = list(telemetry_checks(ev))
    probe = ev.get('exec_probe_empty_home') if isinstance(ev.get('exec_probe_empty_home'), dict) else {}
    if probe.get('outcome') != 'auth_failure' or probe.get('reply') or probe.get('usage_present') is not False:
        problems.append('the exec route with an empty CODEX_HOME did not end in an authentication failure without a '
                        'reply or usage (an alternative credential source is not excluded)')
    status = ev.get('login_status') if isinstance(ev.get('login_status'), dict) else {}
    for key in ('empty_home_before', 'empty_home_after'):
        if status.get(key) != 'not_logged_in':
            problems.append(f'login status with an empty home ({key}) did not report not logged in')
    if status.get('worker_home') != 'logged_in':
        problems.append('login status with the reconstructed worker home did not report logged in')
    call = ev.get('call') if isinstance(ev.get('call'), dict) else {}
    if call.get('outcome') != 'ok' or call.get('stream_verdict') != 'plain':
        problems.append('the telemetry call with the reconstructed worker home did not deliver a plain reply')
    if call.get('home_listing_before') != [AUTH]:
        problems.append('the worker home did not hold exactly auth.json at launch')
    if call.get('workdir_listing_before') != []:
        problems.append('the working directory was not empty at launch')
    if call.get('instruction_sources') != []:
        problems.append('instruction files or unreadable locations were reachable from the working directory')
    runtime = call.get('runtime_files')
    if not isinstance(runtime, list):
        problems.append('no runtime file inventory after the call')
    else:
        found = startup_instruction_files(runtime)
        if found:
            problems.append('instruction bearing files were written at startup and no signed ruling accepts them: '
                            f'{found[:10]}')
    if ev.get('reconciled') is not True:
        problems.append('the telemetry call was not reconciled before certification')
    return problems


# ------------------------------------------------------------------------------------------------ reconciliation

def reconcile_auth(baseline_sha256, workers, in_flight=()) -> dict:
    """A4.2 after-call reconciliation. workers: {slot: {"sha256", "auth_failure"}} of the calls that ended since the
    last reconciliation, all prepared from the same baseline. Returns {"action": continue | wait | propagate | stop_codex}."""
    changed = sorted(s for s, w in workers.items() if w.get('sha256') != baseline_sha256)
    failures = sorted(s for s, w in workers.items() if w.get('auth_failure'))
    if not changed and not failures:
        return {'action': 'continue'}
    if in_flight:
        return {'action': 'wait', 'changed': changed, 'failures': failures}
    if failures:
        return {'action': 'stop_codex', 'interrupted': True, 'reason': 'authentication failure', 'changed': changed,
                'failures': failures}
    if len(changed) == 1:
        return {'action': 'propagate', 'slot': changed[0]}
    return {'action': 'stop_codex', 'interrupted': True, 'reason': 'more than one worker changed authentication',
            'changed': changed, 'failures': failures}


def reconcile_generations(baseline_sha256, workers, ambiguous=()) -> dict:
    """A4.2 reconciliation against the baseline generation each worker was prepared from (council round 1, items 3
    and 5). workers: {slot: {"sha256", "prepared", "auth_failure"}}. A worker equal to the current baseline or to its
    prepared generation is unchanged (or already propagated). A worker that changed while the baseline itself moved
    (an owner reseed, another propagation) is a conflict: Codex stops and the newer baseline is kept. Otherwise the
    A4.2 rule: an authentication failure stops Codex; exactly one changed worker is propagated (against its prepared
    generation); more than one stops Codex. Any ambiguity stops Codex."""
    if ambiguous:
        return {'action': 'stop_codex', 'interrupted': True, 'reason': f'ambiguous recovery: {list(ambiguous)[:5]}'}
    changed, conflicts = [], []
    for slot, w in sorted(workers.items()):
        prepared = w.get('prepared') or baseline_sha256
        if w.get('sha256') is not None and w.get('sha256') in (baseline_sha256, prepared):
            continue
        (changed if prepared == baseline_sha256 else conflicts).append(slot)
    failures = sorted(s for s, w in workers.items() if w.get('auth_failure'))
    if failures:
        return {'action': 'stop_codex', 'interrupted': True, 'reason': 'authentication failure', 'changed': changed,
                'failures': failures}
    if conflicts:
        return {'action': 'stop_codex', 'interrupted': True, 'reason': 'a worker changed authentication while the '
                'baseline changed too (reseed or another propagation); the newer baseline is kept',
                'conflicts': conflicts}
    if not changed:
        return {'action': 'continue'}
    if len(changed) == 1:
        return {'action': 'propagate', 'slot': changed[0]}
    return {'action': 'stop_codex', 'interrupted': True, 'reason': 'more than one worker changed authentication',
            'changed': changed}


# --------------------------------------------------------------------------------------------------- Isolation

class Isolation:
    """Worker homes root/homes/worker-<k>, empty working directories root/work/slot-<k>, hash-only evidence."""

    def __init__(self, baseline, root, evidence, lock=None, frozen_inventory=None, base_env=None):
        self.baseline = Path(baseline)
        self.root = Path(root)
        self.evidence = Path(evidence)
        self.lock = Path(lock) if lock is not None else self.baseline.parent / (self.baseline.name + '.auth.lock')
        self.frozen_inventory = list(frozen_inventory or [])
        self.base_env = dict(os.environ if base_env is None else base_env)
        self._log_lock = threading.Lock()
        self.evidence.mkdir(parents=True, exist_ok=True)

    def home(self, slot) -> Path:
        return self.root / 'homes' / f'worker-{slot}'

    def workdir(self, slot) -> Path:
        return self.root / 'work' / f'slot-{slot}'

    def _log(self, record):
        record = dict(record, at=now_iso())
        line = json.dumps(record, sort_keys=True) + '\n'
        with self._log_lock:
            with open(self.evidence / 'isolation.jsonl', 'a', encoding='utf-8') as f:
                f.write(line)

    def baseline_sha256(self):
        path = self.baseline / AUTH
        return sha256_file(path) if path.exists() else None

    def prepare(self, slot, lock_timeout=None) -> dict:
        """Rebuild the worker home (auth.json only, copied from the baseline) and empty the working directory, under
        the authentication lock. Logs hashes only."""
        home, work = self.home(slot), self.workdir(slot)
        with auth_lock(self.lock, timeout=lock_timeout):
            source = self.baseline / AUTH
            if not source.is_file():
                raise IsolationError('baseline auth.json is missing')
            data = source.read_bytes()
            shutil.rmtree(home, ignore_errors=True)
            if home.exists():
                raise IsolationError(f'worker home {home.name} could not be removed')
            home.mkdir(parents=True)
            (home / AUTH).write_bytes(data)
            shutil.rmtree(work, ignore_errors=True)
            if work.exists():
                raise IsolationError(f'working directory {work.name} could not be emptied')
            work.mkdir(parents=True)
            digest = hashlib.sha256(data).hexdigest()
        self._log({'event': 'prepare', 'slot': slot, 'baseline_auth_sha256': digest, 'worker_auth_sha256': digest,
                   'home_listing': sorted(os.listdir(home)), 'workdir_listing': sorted(os.listdir(work))})
        return {'slot': slot, 'home': str(home), 'workdir': str(work), 'env': child_env(home, self.base_env),
                'auth_sha256': digest}

    def finish(self, slot, auth_failure=False, prepared_sha256=None) -> dict:
        """Inventory every generated runtime file in the worker home (names only), compare the worker auth.json hash
        with the baseline, then remove the runtime state (everything except auth.json)."""
        home = self.home(slot)
        worker = home / AUTH
        worker_sha = sha256_file(worker) if worker.exists() else None
        base_sha = prepared_sha256 or self.baseline_sha256()
        runtime = []
        if home.exists():
            for p in sorted(home.rglob('*')):
                rel = p.relative_to(home).as_posix()
                if rel != AUTH and p.is_file():
                    runtime.append(rel)
            for p in list(home.iterdir()):
                if p.name == AUTH:
                    continue
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    try:
                        p.unlink()
                    except OSError:
                        pass
        out = {'slot': slot, 'worker_auth_sha256': worker_sha, 'baseline_auth_sha256': base_sha,
               'auth_changed': worker_sha != base_sha, 'auth_failure': bool(auth_failure), 'runtime_files': runtime}
        self._log(dict(out, event='finish', runtime_file_count=len(runtime)))
        return out

    def propagate(self, slot, lock_timeout=30.0, expected_baseline_sha256=None) -> dict:
        """Copy the worker auth.json over the baseline atomically under the authentication lock. Never restores an
        older snapshot: a worker whose last_refresh is older than the baseline's raises StaleAuth. With
        expected_baseline_sha256 (the baseline generation the worker was prepared from), a baseline that changed in
        the meantime (an owner reseed, another propagation) raises StaleAuth and is never replaced."""
        worker = self.home(slot) / AUTH
        with auth_lock(self.lock, timeout=lock_timeout):
            before = self.baseline_sha256()
            if expected_baseline_sha256 is not None and before != expected_baseline_sha256:
                raise StaleAuth('the baseline changed since this worker was prepared; the newer baseline is kept')
            new_doc, old_doc = _read_auth(worker), _read_auth(self.baseline / AUTH)
            if new_doc is None:
                raise StaleAuth('worker auth.json unreadable; nothing propagated')
            new_t, old_t = _parse_time(new_doc.get('last_refresh')), _parse_time((old_doc or {}).get('last_refresh'))
            if old_t is not None and (new_t is None or new_t < old_t):
                raise StaleAuth('worker authentication is older than the baseline; never restored')
            data = worker.read_bytes()
            temp = self.baseline / (AUTH + '.propagate.tmp')
            with open(temp, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.baseline / AUTH)
            after = self.baseline_sha256()
        self._log({'event': 'propagate', 'slot': slot, 'before': before, 'after': after})
        return {'before': before, 'after': after}
