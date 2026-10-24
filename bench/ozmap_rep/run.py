"""oz map clean replication runner (Amendment 4). Standard library only.

    python -m bench.ozmap_rep.run plan --list-cells          the 16 cells, one JSON line each
    python -m bench.ozmap_rep.run cell <id> [options]        run or resume one cell (fake or live)
    python -m bench.ozmap_rep.run dry --run-dir D            every cell in fake mode, zero rules, then the scorer
    python -m bench.ozmap_rep.run telemetry --mode live ...  the A4.2 telemetry checks (live only)
    python -m bench.ozmap_rep.run freeze | verify-freeze     hash the frozen inputs before evaluation calls (A4.1)
    python -m bench.ozmap_rep.run features --run-dir D       record `codex features list` for the worker home (A4.2)

Cells and allocations follow A4.5; isolation A4.2; tool events A4.3; capacity A4.4; bootstrap validity A4.6; usage
A4.7; operations A4.8; Sonnet A4.9; stops A4.12. build-notes.md maps every clause to the code.

Run state. Every physical call is one line in D/attempts.jsonl (append only, failures included), its complete prompt
is D/prompts/<call id>.txt, its raw output D/captures/<call id>.*, its parsed outcome D/cells/<cell>/calls/<call id>.json.
Before a call starts, D/cells/<cell>/inflight/<call id>.json is written; a marker without an attempt line on resume
means the runner died with the call in flight: it is recorded as an interrupted attempt (it consumed its allowance) and
the batch may be retried only from the allocation's infrastructure reserve. A batch whose attempt ended with any
terminal outcome is never sent again. A completed cell has D/cells/<cell>/DONE.json and is never rerun.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

from . import config

if str(config.REPO) not in sys.path:
    sys.path.insert(0, str(config.REPO))
if str(config.REPO / 'examples') not in sys.path:
    sys.path.insert(0, str(config.REPO / 'examples'))

from . import budget as budget_mod  # noqa: E402
from . import events, isolation, prompts, quota, rules, usage, workload  # noqa: E402
from . import fake_cli, tokenizer  # noqa: E402

COMMAND = 'python -m bench.ozmap_rep.run cell {id}'
AUTH_FAILURE_RE = re.compile(r'401 Unauthorized|invalid_grant|refresh_token_reused|token_expired|Not logged in|'
                             r'Please log ?in|re-?authenticate', re.I)
TERMINAL_OK = ('ok',)
RETRYABLE = ('infrastructure_failure', 'interrupted')


# ================================================================================================ cells and plan

def cell_specs():
    specs = []
    for backend, wl in (('codex', 'materials'), ('codex', 'boolq'), ('sonnet', 'materials')):
        prefix = f'{backend}-{wl}'
        alloc = config.ALLOCATIONS[f'{backend}/{wl}']

        def add(name, wave, arm, allocation, requires):
            cid = f'{prefix}-{name}'
            specs.append({'id': cid, 'command': COMMAND.format(id=cid), 'backend': backend, 'workload': wl,
                          'wave': wave, 'arm': arm, 'allocation': allocation, 'nominal_calls': alloc[allocation],
                          'requires': requires})
        add('bootstrap', 'cold', 'bootstrap', 'bootstrap', [])
        add('cold-A', 'cold', 'A', 'cold_A', [])
        add('cold-B', 'cold', 'B', 'cold_B', [f'{prefix}-bootstrap'])
        add('cold-C', 'cold', 'C', 'cold_C', [f'{prefix}-bootstrap'])
        if wl == 'materials':
            add('warm-A', 'warm', 'A', 'warm_A', [f'{prefix}-cold-A'])
            add('warm-C', 'warm', 'C', 'warm_C', [f'{prefix}-bootstrap', f'{prefix}-cold-C'])
    return specs


def spec_by_id(cell_id):
    for s in cell_specs():
        if s['id'] == cell_id:
            return s
    return None


# ================================================================================================ small helpers

def _now():
    return isolation.now_iso()


def _write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, path)


def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _append(run_dir, name, row):
    path = Path(run_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with isolation.file_lock(Path(run_dir) / 'locks' / (name + '.lock'), timeout=60):
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + '\n')


def chunks(items, n=config.MAX_BATCH):
    return [items[i:i + n] for i in range(0, len(items), n)]


def schedule(fallback_by_producer, audits_by_producer, pooled):
    """The frozen dispatch rule (A4.4): synchronized submission, full eligible batches of at most 64, producer local
    for B, pooled for C. Inputs are job lists in wave order; returns a list of batches."""
    if pooled:
        every = [j for p in config.PRODUCERS for j in fallback_by_producer.get(p, []) + audits_by_producer.get(p, [])]
        return chunks(every)
    out = []
    for p in config.PRODUCERS:
        out += chunks(fallback_by_producer.get(p, []) + audits_by_producer.get(p, []))
    return out


def worst_case_calls(spec):
    """Batches the scheduler dispatches with zero admitted rules and the worst permitted audit placement (the whole
    audit allowance on one producer for local fallback, added to the pool for pooled fallback)."""
    if spec['arm'] == 'bootstrap':
        return 1
    n = config.PER_PRODUCER
    b = config.BOOTSTRAP_PER_PRODUCER if spec['wave'] == 'cold' and spec['arm'] in ('B', 'C') else 0
    a = config.AUDITS if spec['workload'] == 'materials' and spec['arm'] in ('B', 'C') else 0
    if spec['arm'] == 'A':
        return len(schedule({p: ['x'] * n for p in config.PRODUCERS}, {}, pooled=True))
    worst = 0
    for target in config.PRODUCERS:
        fallback = {p: ['f'] * (n - b) for p in config.PRODUCERS}
        audits = {target: ['a'] * a}
        worst = max(worst, len(schedule(fallback, audits, pooled=spec['arm'] == 'C')))
    return worst


# ================================================================================================ options, slots

class Options:
    def __init__(self, run_dir, mode='fake', baseline=None, sessions_dir=None, claude_percent=None, stop_after=None,
                 fake_fail=0, fake_refresh=None, base_env=None, out=None):
        self.run_dir = Path(run_dir)
        self.mode = mode
        self.baseline = Path(baseline) if baseline else config.BASELINE_DEFAULT
        self.sessions_dir = Path(sessions_dir) if sessions_dir else config.CODEX_SESSIONS_DEFAULT
        self.claude_percent = claude_percent
        self.stop_after = stop_after
        self.fake_fail = fake_fail or 0
        self.fake_refresh = fake_refresh
        self.base_env = dict(os.environ if base_env is None else base_env)
        self.out = out or sys.stderr


class Slots:
    """The experiment-wide pool of four physical slots: one OS lock file per slot, shared by every cell process."""

    def __init__(self, run_dir):
        self.dir = Path(run_dir) / 'slots'
        self.dir.mkdir(parents=True, exist_ok=True)
        self.held = {}

    def acquire(self, exclude=()):
        while True:
            for k in range(config.SLOTS):
                if k in self.held or k in exclude:
                    continue
                handle = open(self.dir / f'slot-{k}.lock', 'a+b')
                if isolation._try_lock(handle):
                    self.held[k] = handle
                    return k
                handle.close()
            time.sleep(0.05)

    def release(self, k):
        handle = self.held.pop(k, None)
        if handle is not None:
            isolation._unlock(handle)
            handle.close()


# ================================================================================================ executables

def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_real(name, base_env, run_dir):
    found = shutil.which(name, path=base_env.get('PATH') or os.environ.get('PATH'))
    _append(run_dir, 'resolved.jsonl', {'name': name, 'path': found, 'at': _now()})
    return found


def cli_flags():
    doc = _read_json(config.CLI_FLAGS_FILE, {}) or {}
    supported = set(doc.get('supported') or [])
    return isolation.plan_disable_options(supported)


class Executables:
    """The executable, its hash and the frozen hashes the launch is verified against. Fake mode freezes the harness'
    own fakes at the start of the invocation; live mode verifies the real CLI against freeze.json."""

    def __init__(self, opts, backend):
        self.opts, self.backend = opts, backend
        self.disable_args, self.unsupported = cli_flags()
        if opts.mode == 'fake':
            answers = workload.fake_answer_table()
            self.fakes = fake_cli.build(opts.run_dir, answers)
            self.exe = str(self.fakes['codex' if backend == 'codex' else 'claude'])
            self.exe_sha256 = _sha(self.exe)
            self.prefix = [sys.executable]
            probe = isolation.codex_argv(self.exe, config.CODEX_MODEL, config.CODEX_EFFORT,
                                         opts.run_dir / 'work' / 'slot-0', self.disable_args)
            self.frozen = {'argv_sha256': isolation.argv_sha256(probe), 'exe_sha256': self.exe_sha256}
        else:
            self.fakes = None
            name = 'codex' if backend == 'codex' else 'claude'
            found = resolve_real(name, opts.base_env, opts.run_dir)
            if not found:
                raise RuntimeError(f'{name} executable not found')
            self.exe = found
            self.exe_sha256 = _sha(found)
            self.prefix = []
            frozen = _read_json(config.FREEZE_FILE, {}) or {}
            self.frozen = {'argv_sha256': (frozen.get('codex') or {}).get('argv_sha256'),
                           'exe_sha256': (frozen.get(backend) or {}).get('exe_sha256')}


# ================================================================================================ one physical call

def _kill_tree(proc):
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True, timeout=60)
        else:
            proc.kill()
    except (OSError, subprocess.SubprocessError):
        pass


def spawn(run_dir, launch, stdin_text, env, cwd, external, timeout=config.CALL_TIMEOUT_S):
    """Run one child; every spawn is logged in D/spawns.jsonl with whether it is an external model CLI."""
    _append(run_dir, 'spawns.jsonl', {'exe': Path(launch[1] if not external else launch[0]).name,
                                      'external': bool(external), 'at': _now()})
    t0 = time.monotonic()
    start = _now()
    proc = subprocess.Popen(launch, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=str(cwd), env=env)
    timed_out = False
    try:
        out, err = proc.communicate(stdin_text.encode('utf-8'), timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        out, err = proc.communicate()
    return {'stdout': out.decode('utf-8', 'replace'), 'stderr': err.decode('utf-8', 'replace'),
            'exit_code': None if timed_out else proc.returncode, 'timed_out': timed_out,
            'started_at': start, 'ended_at': _now(), 'elapsed_s': round(time.monotonic() - t0, 3)}


def _turn_usage(stdout):
    found = None
    for line in stdout.splitlines():
        if not line.startswith('{'):
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get('type') == 'turn.completed':
            found = e.get('usage')
    return found


def judge_codex(raw):
    """(outcome, reply, usage raw, event verdict) of one Codex call."""
    import codex_cli_adapter
    cls = events.classify_stream(raw['stdout'])
    reply, _, failure = codex_cli_adapter.parse_events(raw['stdout'])
    usage_raw = _turn_usage(raw['stdout'])
    text = raw['stdout'] + '\n' + raw['stderr']
    if raw['timed_out']:
        return 'infrastructure_failure', None, usage_raw, cls, 'timeout'
    if cls['verdict'] in ('executed', 'uncertain', 'refused'):
        return cls['verdict'], None, usage_raw, cls, None
    if raw['exit_code'] != 0 or failure is not None or not isinstance(reply, str):
        if AUTH_FAILURE_RE.search(text):
            return 'auth_failure', None, usage_raw, cls, 'authentication failure'
        return 'infrastructure_failure', None, usage_raw, cls, (failure or f'exit {raw["exit_code"]}')[:300]
    return 'ok', reply, usage_raw, cls, None


def judge_sonnet(raw):
    import claude_cli_adapter
    if raw['timed_out']:
        return 'infrastructure_failure', None, None, events.classify_claude({}), 'timeout'
    try:
        data = json.loads(raw['stdout'])
    except ValueError:
        return 'infrastructure_failure', None, None, events.classify_claude({}), f'exit {raw["exit_code"]}'
    cls = events.classify_claude(data)
    usage_raw = claude_cli_adapter.usage_from_envelope(data)
    if cls['verdict'] != 'plain':
        return cls['verdict'], None, usage_raw, cls, None
    if raw['exit_code'] != 0 or not isinstance(data, dict) or not isinstance(data.get('result'), str) \
            or data.get('is_error'):
        return 'infrastructure_failure', None, usage_raw, cls, f'exit {raw["exit_code"]}'
    return 'ok', data['result'], usage_raw, cls, None


# ================================================================================================ the cell runner

class Stop(Exception):
    def __init__(self, code, reason):
        Exception.__init__(self, reason)
        self.code, self.reason = code, reason


class CellRun:
    def __init__(self, spec, opts):
        self.spec, self.opts = spec, opts
        self.run_dir = opts.run_dir
        self.dir = self.run_dir / 'cells' / spec['id']
        self.backend, self.workload = spec['backend'], spec['workload']
        self.codex = self.backend == 'codex'
        self.launched = 0
        self.invocation_calls = 0
        self.interrupted = None
        self.lock = threading.Lock()
        self.invocation = f'{os.getpid()}-{int(time.time() * 1000)}'
        self.group_seq = 0
        self.current_group = None

    # ------------------------------------------------------------------------------------------- state

    def state(self, state, **extra):
        doc = _read_json(self.dir / 'state.json', {}) or {}
        doc.update(extra, state=state, cell=self.spec['id'], updated_at=_now())
        doc.setdefault('invocations', [])
        _write_json(self.dir / 'state.json', doc)

    def say(self, text):
        self.opts.out.write(text.rstrip() + '\n')

    # ------------------------------------------------------------------------------------------- gates

    def gates(self):
        opts = self.opts
        if self.codex:
            gate = isolation.wave_gate(opts.baseline)
            _append(self.run_dir, 'evidence/wave-gates.jsonl', {'cell': self.spec['id'], 'ok': gate['ok'],
                                                               'exp': gate['exp'], 'hours_left': gate['hours_left'],
                                                               'at': _now()})
            if not gate['ok']:
                raise Stop(config.EXIT_AUTH_GATE, 'baseline authentication gate failed (A4.2): ' + gate['reason'])
            problems = isolation.verify_baseline(opts.baseline, isolation.load_inventory())
            if problems:
                raise Stop(config.EXIT_AUTH_GATE, f'baseline inventory check failed (A4.2): {problems[:5]}; '
                                                  f'reseed with: CODEX_HOME={opts.baseline} codex login')
            if (self.run_dir / 'codex-stop.json').exists():
                raise Stop(config.EXIT_AUTH_STOP, 'Codex evaluation is stopped for this run (A4.2 reconciliation)')
        if opts.mode == 'live':
            g = quota.claude_gate(opts.claude_percent)
            if not g['ok']:
                raise Stop(config.EXIT_QUOTA, g['reason'])
            if self.codex:
                g = quota.codex_gate(opts.sessions_dir)
                if not g['ok']:
                    raise Stop(config.EXIT_QUOTA, g['reason'])
            problems = verify_freeze()
            if problems:
                raise Stop(config.EXIT_FREEZE, f'freeze verification failed (A4.1): {problems[:5]}')
            if self.codex:
                tel = _read_json(self.run_dir / 'evidence' / 'telemetry.json', {}) or {}
                problems = isolation.telemetry_checks(tel)
                if problems:
                    raise Stop(config.EXIT_TELEMETRY, f'telemetry checks not passed (A4.2): {problems}')

    # ------------------------------------------------------------------------------------------- resume

    def prior_attempts(self):
        return [a for a in jsonl(self.run_dir / 'attempts.jsonl') if a.get('cell') == self.spec['id']]

    def recover_inflight(self):
        """A marker without an attempt line: the runner died with that call in flight. It consumed its allowance, so
        it is recorded as an interrupted attempt; its batch may only be retried from the infrastructure reserve."""
        done = {a['call_id'] for a in self.prior_attempts()}
        folder = self.dir / 'inflight'
        if not folder.exists():
            return
        for marker in sorted(folder.glob('*.json')):
            m = _read_json(marker, {}) or {}
            if m.get('call_id') and m['call_id'] not in done:
                row = dict(m, outcome='interrupted', ended_at=_now(), elapsed_s=None, usage_status='incomplete',
                           charged_tokens=0, note='runner ended while the call was in flight')
                _append(self.run_dir, 'attempts.jsonl', row)
            marker.unlink()

    def budget(self):
        b = budget_mod.Budget()
        for a in jsonl(self.run_dir / 'attempts.jsonl'):
            b._attempts.append({k: a.get(k) for k in ('backend', 'workload', 'allocation', 'reason', 'kind',
                                                      'outcome')})
        return b

    # ------------------------------------------------------------------------------------------- calls

    def batch_key(self, round_no, idx):
        return f'r{round_no}.b{idx:02d}'

    def run_batches(self, batches, round_no, bootstrap=False, first_reason='nominal'):
        """Execute every batch (list of job lists) of one round; returns {batch key: call output}. Batches whose
        latest attempt is terminal are taken from disk and never sent again."""
        prior = self.prior_attempts()
        results, pending = {}, []
        for idx, jobs in enumerate(batches):
            key = self.batch_key(round_no, idx)
            mine = [a for a in prior if a.get('batch') == key]
            last = mine[-1] if mine else None
            if last is not None and last['outcome'] not in RETRYABLE:
                results[key] = _read_json(self.dir / 'calls' / f"{last['call_id']}.json", {}) or {}
                results[key].setdefault('outcome', last['outcome'])
                continue
            pending.append((key, jobs, len(mine), first_reason if not mine else 'infrastructure_retry'))
        # First attempts before retries, so a retry never takes a nominal call another batch still needs.
        pending.sort(key=lambda item: (item[2] > 0, item[0]))
        exe = self.exe
        while pending:
            group, waiting = [], []
            self.group_seq += 1
            self.current_group = f'{self.invocation}.r{round_no}.g{self.group_seq}'
            for item in pending:
                if len(group) >= config.SLOTS:
                    waiting.append(item)
                    continue
                key, jobs, tries, reason = item
                if self.opts.stop_after is not None and self.launched >= self.opts.stop_after:
                    self.interrupted = (config.EXIT_INTERRUPTED, f'--stop-after {self.opts.stop_after} reached')
                    waiting.append(item)
                    continue
                if self.interrupted:
                    waiting.append(item)
                    continue
                if self.opts.mode == 'live' and self.codex:
                    g = quota.codex_gate(self.opts.sessions_dir)
                    if not g['ok']:
                        self.interrupted = (config.EXIT_QUOTA, g['reason'])
                        waiting.append(item)
                        continue
                try:
                    prepared = self.prepare_call(key, jobs, tries, reason, bootstrap)
                except Stop:
                    self.abandon(group)
                    raise
                if prepared is None:
                    results[key] = {'outcome': 'budget_exhausted', 'answers': {}, 'job_ids': [j['id'] for j in jobs]}
                    continue
                group.append(prepared)
            if group:
                threads = [threading.Thread(target=self.execute, args=(c,), daemon=True) for c in group]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                self.after_group(group)
            pending = []
            for c in group:
                if c['outcome'] in RETRYABLE and not self.interrupted:
                    pending.append((c['batch'], c['jobs'], c['try'] + 1, 'infrastructure_retry'))
                else:
                    results[c['batch']] = c['output']
            if self.interrupted:
                for item in waiting:
                    results.setdefault(item[0], {'outcome': 'not_launched', 'answers': {},
                                                 'job_ids': [j['id'] for j in item[1]]})
                for c in group:
                    if c['outcome'] in RETRYABLE:
                        results[c['batch']] = c['output']
                break
            pending = waiting + pending
            if not group and pending:
                break
        del exe
        return results

    def prepare_call(self, key, jobs, tries, reason, bootstrap):
        """Everything before the spawn, in the launching thread: the model input, the leak check, the slot, the
        worker home reconstruction and launch verification (Codex), the budget charge and the in-flight marker.
        Returns None when the budget refuses the call."""
        spec = self.spec
        call_id = f"{spec['id']}.{key}.t{tries}"
        inp = prompts.model_input(jobs, self.workload, bootstrap=bootstrap)
        record = prompts.prompt_record(inp)
        leaks = prompts.learner_prompt_leaks(record, workload.materials()['admission'])
        if leaks:
            raise Stop(config.EXIT_INCOMPLETE, f'{call_id}: admission material in a model-bound prompt (A4.8)')
        if self.codex:
            problems = isolation.verify_baseline(self.opts.baseline, isolation.load_inventory())
            if problems:
                raise Stop(config.EXIT_AUTH_GATE, f'{call_id}: baseline inventory check failed (A4.2): {problems[:5]}')
        slot = self.slots.acquire()
        try:
            if self.codex:
                prepared = self.iso.prepare(slot)
                argv = isolation.codex_argv(self.exe.exe, config.CODEX_MODEL, config.CODEX_EFFORT,
                                            prepared['workdir'], self.exe.disable_args)
                env, workdir, stdin = prepared['env'], prepared['workdir'], inp['stdin_codex']
                problems = isolation.verify_launch(argv=argv, env=env, workdir=workdir,
                                                   exe_sha256=self.exe.exe_sha256, frozen=self.exe.frozen)
                prepared_sha = prepared['auth_sha256']
            else:
                workdir = self.run_dir / 'work' / f'slot-{slot}'
                shutil.rmtree(workdir, ignore_errors=True)
                workdir.mkdir(parents=True)
                argv = prompts.sonnet_argv(self.exe.exe, config.SONNET_MODEL, config.SONNET_EFFORT, inp['system'])
                env, stdin = isolation.sonnet_env(self.opts.base_env), inp['body']
                problems = []
                if os.listdir(workdir):
                    problems.append('working directory is not empty')
                sources = isolation.instruction_sources(workdir)
                if sources:
                    problems.append(f'instruction files reachable: {[str(p) for p in sources]}')
                if self.exe.exe_sha256 != self.exe.frozen.get('exe_sha256') and self.opts.mode == 'live':
                    problems.append('executable hash differs from the frozen executable hash')
                prepared_sha = None
            evidence = {'call_id': call_id, 'cell': spec['id'], 'slot': slot, 'argv_sha256': isolation.argv_sha256(argv),
                        'exe_sha256': self.exe.exe_sha256, 'frozen': self.exe.frozen, 'env_names': sorted(env),
                        'workdir': str(workdir), 'problems': problems, 'prompt_sha256': prompts.sha256(record),
                        'stdin_sha256': prompts.sha256(stdin), 'at': _now(),
                        'instruction_sources': [str(p) for p in isolation.instruction_sources(workdir)]}
            _write_json(self.run_dir / 'evidence' / 'launch' / f'{call_id}.json', evidence)
            if problems:
                raise Stop(config.EXIT_INCOMPLETE, f'{call_id}: launch verification failed (A4.2): {problems}')
            try:
                charged = self.budget_obj.charge(self.backend, self.workload, spec['allocation'], reason=reason,
                                                 outcome='launched')
            except budget_mod.BudgetExceeded as exc:
                self.say(f'{call_id}: not launched: {exc}')
                if self.codex:
                    self.iso.finish(slot, prepared_sha256=prepared_sha)
                self.slots.release(slot)
                return None
            prompt_path = self.run_dir / 'prompts' / f'{call_id}.txt'
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(record, encoding='utf-8')
            self.launched += 1
            self.invocation_calls += 1
            n = len(self.prior_attempts()) + 1 + sum(1 for _ in self.dir.glob('inflight/*.json'))
            fail = self.invocation_calls <= self.opts.fake_fail
            refresh = self.codex and self.opts.fake_refresh is not None and \
                self.invocation_calls == self.opts.fake_refresh
            if self.opts.mode == 'fake':
                _write_json(self.exe.fakes['directives'] / f'slot-{slot}.json',
                            {'cell': spec['id'], 'n': n, 'call_id': call_id, 'fail': fail, 'refresh': refresh,
                             'bootstrap_ops': inp['ops'] if bootstrap else None})
            marker = {'call_id': call_id, 'cell': spec['id'], 'backend': self.backend, 'workload': self.workload,
                      'wave': spec['wave'], 'arm': spec['arm'], 'allocation': spec['allocation'], 'batch': key,
                      'try': tries, 'reason': reason, 'kind': charged['kind'], 'slot': slot, 'mode': self.opts.mode,
                      'group': self.current_group,
                      'started_at': _now(), 'job_ids': [j['id'] for j in jobs],
                      'records': {op: sum(1 for j in jobs if j['op'] == op) for op in sorted({j['op'] for j in jobs})},
                      'prompt_sha256': prompts.sha256(record), 'stdin_sha256': prompts.sha256(stdin),
                      'system_sha256': prompts.sha256(inp['system']), 'bootstrap': bootstrap}
            _write_json(self.dir / 'inflight' / f'{call_id}.json', marker)
            launch = self.exe.prefix + list(argv) if self.opts.mode == 'fake' else list(argv)
            return {'call_id': call_id, 'batch': key, 'try': tries, 'jobs': jobs, 'inp': inp, 'slot': slot,
                    'launch': launch, 'env': env, 'workdir': workdir, 'stdin': stdin, 'marker': marker,
                    'prepared_sha': prepared_sha, 'bootstrap': bootstrap, 'outcome': None, 'output': None}
        except Stop:
            if self.codex:
                with contextlib.suppress(Exception):
                    self.iso.finish(slot)
            self.slots.release(slot)
            raise

    def abandon(self, group):
        """Calls prepared but never spawned (a later launch check failed): nothing reached a CLI, so their markers go
        and their in-memory budget charges are never written; slots and worker homes are released."""
        for c in group:
            with contextlib.suppress(OSError):
                (self.dir / 'inflight' / f"{c['call_id']}.json").unlink()
            with contextlib.suppress(OSError):
                (self.run_dir / 'prompts' / f"{c['call_id']}.txt").unlink()
            if self.codex:
                with contextlib.suppress(Exception):
                    self.iso.finish(c['slot'], prepared_sha256=c['prepared_sha'])
            self.slots.release(c['slot'])

    def execute(self, c):
        try:
            c['raw'] = spawn(self.run_dir, c['launch'], c['stdin'], c['env'], c['workdir'],
                             external=self.opts.mode == 'live')
        except OSError as exc:
            c['raw'] = {'stdout': '', 'stderr': f'spawn failed: {type(exc).__name__}', 'exit_code': None,
                        'timed_out': False, 'started_at': _now(), 'ended_at': _now(), 'elapsed_s': 0.0}

    def after_group(self, group):
        """Judge every call of a finished launch group, record its attempt, then reconcile authentication (A4.2):
        nothing is launched while a call is in flight, so the whole group is reconciled at once."""
        judged = []
        for c in group:
            raw = c['raw']
            outcome, reply, usage_raw, cls, why = (judge_codex if self.codex else judge_sonnet)(raw)
            judged.append((c, outcome, reply, usage_raw, cls, why))
        replies = [r for _, o, r, *_ in judged if isinstance(r, str)]
        counts = iter(tokenizer.count(replies)) if self.codex and replies else iter(())
        workers = {}
        for c, outcome, reply, usage_raw, cls, why in judged:
            visible = next(counts) if self.codex and isinstance(reply, str) else None
            fin = None
            if self.codex:
                fin = self.iso.finish(c['slot'], auth_failure=outcome == 'auth_failure',
                                      prepared_sha256=c['prepared_sha'])
                workers[c['slot']] = {'sha256': fin['worker_auth_sha256'], 'auth_failure': fin['auth_failure'],
                                      'call_id': c['call_id']}
            output = self.interpret(c, outcome, reply)
            outcome = output['outcome']
            if self.codex:
                dec = usage.decode_codex(usage_raw, cache_certified=self.cache_certified)
                issue = None
                if dec['status'] != 'incomplete':
                    issue = usage.reasoning_inclusion(usage_raw, visible)
                status = dec['status']
                if issue and status == 'complete':
                    status = 'unverified'
                additive = usage.additive_tokens(usage_raw) if dec['status'] != 'incomplete' else None
            else:
                dec = usage.decode_sonnet(usage_raw)
                issue, status, additive = None, dec['status'], None
                if dec['status'] != 'incomplete':
                    additive = usage_raw['input_tokens'] + usage_raw['cached_input_tokens'] + usage_raw['output_tokens']
            captures = self.run_dir / 'captures'
            captures.mkdir(parents=True, exist_ok=True)
            (captures / f"{c['call_id']}.stdout").write_text(c['raw']['stdout'], encoding='utf-8')
            (captures / f"{c['call_id']}.stderr").write_text(c['raw']['stderr'], encoding='utf-8')
            row = dict(c['marker'], outcome=outcome, why=why, exit_code=c['raw']['exit_code'],
                       timed_out=c['raw']['timed_out'], started_at=c['raw']['started_at'],
                       ended_at=c['raw']['ended_at'], elapsed_s=c['raw']['elapsed_s'],
                       stdout_sha256=prompts.sha256(c['raw']['stdout']), events={
                           'verdict': cls['verdict'], 'efficiency_invalid': cls['efficiency_invalid'],
                           'external_read': cls['external_read'], 'notices': len(cls['notices']),
                           'tool_requests': cls['tool_requests'], 'tool_executions': cls['tool_executions'],
                           'uncertain': cls['uncertain'][:20]},
                       usage_raw=usage_raw, usage=dec, usage_status=status, reasoning_issue=issue,
                       visible_tokens=visible, cache_certified=self.cache_certified if self.codex else None,
                       charged_tokens=dec.get('charged_tokens') or 0, additive_tokens=additive,
                       auth=None if fin is None else {k: fin[k] for k in ('worker_auth_sha256', 'baseline_auth_sha256',
                                                                           'auth_changed', 'auth_failure')},
                       runtime_files=None if fin is None else len(fin['runtime_files']))
            _write_json(self.dir / 'calls' / f"{c['call_id']}.json", output)
            _append(self.run_dir, 'attempts.jsonl', row)
            if self.opts.mode == 'fake':
                rec = _read_json(self.exe.fakes['records'] / f"{c['call_id']}.json")
                if rec is None:
                    rec = {'cell': self.spec['id'], 'n': c['marker'].get('try'), 'cli': self.backend,
                           'argv': c['launch'][1:], 'codex_home': None, 'home_listing': [], 'workdir': None,
                           'workdir_listing': [], 'env_names': [], 'stdin_sha256': prompts.sha256(c['stdin'])}
                _append(self.run_dir, 'fake_calls.jsonl', rec)
            with contextlib.suppress(OSError):
                (self.dir / 'inflight' / f"{c['call_id']}.json").unlink()
            self.slots.release(c['slot'])
            c['outcome'], c['output'] = outcome, output
        if self.codex and workers:
            self.reconcile(workers)

    def reconcile(self, workers):
        base = self.iso.baseline_sha256()
        prepared = {w['call_id']: w for w in workers.values()}
        verdict = isolation.reconcile_auth(base, {s: {'sha256': w['sha256'], 'auth_failure': w['auth_failure']}
                                                  for s, w in workers.items()})
        _append(self.run_dir, 'evidence/auth-reconcile.jsonl',
                {'cell': self.spec['id'], 'baseline_auth_sha256': base, 'action': verdict['action'],
                 'workers': {str(s): {'sha256': w['sha256'], 'auth_failure': w['auth_failure']}
                             for s, w in workers.items()}, 'calls': sorted(prepared), 'at': _now()})
        if verdict['action'] == 'propagate':
            try:
                self.iso.propagate(verdict['slot'])
            except (isolation.StaleAuth, isolation.LockTimeout) as exc:
                self.codex_stop(f'propagation refused: {exc}')
        elif verdict['action'] == 'stop_codex':
            self.codex_stop(verdict.get('reason', 'authentication reconciliation'))

    def codex_stop(self, reason):
        _write_json(self.run_dir / 'codex-stop.json', {'reason': reason, 'cell': self.spec['id'], 'at': _now()})
        self.interrupted = (config.EXIT_AUTH_STOP, 'Codex evaluation stopped (A4.2): ' + reason)

    def interpret(self, c, outcome, reply):
        """The parsed output of one call: answers keyed by job id (and, for a bootstrap, the proposed rules)."""
        out = {'outcome': outcome, 'answers': {}, 'failed': {}, 'job_ids': [j['id'] for j in c['jobs']],
               'call_id': c['call_id'], 'rejection': None}
        if outcome != 'ok':
            return out
        mapping = c['inp']['mapping']
        if c['bootstrap']:
            try:
                answers_reply, proposed = prompts.parse_bootstrap(reply, c['inp']['ops'])
            except prompts.Malformed as exc:
                out.update(outcome='malformed', rejection='envelope malformed: ' + str(exc)[:200])
                return out
            out['rules'] = proposed
            reply = answers_reply
        answers, failed, rejection = prompts.parse_answers(reply, mapping)
        out.update(answers=answers, failed=failed, rejection=rejection)
        if rejection and not c['bootstrap']:
            out['outcome'] = 'malformed_reply'
        return out

    # ------------------------------------------------------------------------------------------- arms

    def jobs(self):
        return list(workload.jobs_for(self.workload, self.spec['wave']))

    def run_A(self):
        by_p = {p: [j for j in self.jobs() if j['producer'] == p] for p in config.PRODUCERS}
        batches = schedule(by_p, {}, pooled=False)
        results = self.run_batches(batches, 1)
        answers = {}
        for out in results.values():
            for jid, v in (out.get('answers') or {}).items():
                answers[jid] = {'answer': v, 'source': 'model', 'call_id': out.get('call_id')}
        return {'answers': answers, 'batches': {k: v.get('outcome') for k, v in results.items()},
                'scheduled_calls': len(batches)}

    def run_bootstrap(self):
        ids = workload.bootstrap_ids(self.workload)
        by_id = {j['id']: j for j in self.jobs()}
        batch = [by_id[i] for i in ids]
        results = self.run_batches([batch], 1, bootstrap=True)
        out = results.get(self.batch_key(1, 0), {})
        status = {'ok': 'ok', 'malformed': 'malformed', 'budget_exhausted': 'missing', 'not_launched': 'missing',
                  'infrastructure_failure': 'missing', 'interrupted': 'missing'}.get(out.get('outcome'),
                                                                                    out.get('outcome') or 'missing')
        answers = {jid: {'answer': v, 'source': 'bootstrap', 'call_id': out.get('call_id')}
                   for jid, v in (out.get('answers') or {}).items()}
        rule_doc = {}
        for op, entry in (out.get('rules') or {}).items():
            row = {'proposed': 'none' not in entry, 'ast_sha256': entry.get('ast_sha256'), 'bytes': entry.get('bytes'),
                   'ast_b64': entry.get('ast_b64')}
            if row['proposed']:
                if self.workload == 'materials':
                    resp = rules.admit(op, rules.decode(entry))
                    row['admission'] = rules.summary(resp)
                    _write_json(self.dir / 'admission' / f'{op}.json', resp)
                else:
                    row['admission'] = {'status': 'rejected', 'reasons': ['ineligible: BoolQ (A4.6)']}
            rule_doc[op] = row
        return {'answers': answers, 'status': status, 'rules': rule_doc, 'call_outcome': out.get('outcome'),
                'answers_rejection': out.get('rejection'), 'registry_manifest_sha256': rules.manifest_sha256(),
                'scheduled_calls': 1}

    def admitted_rules(self):
        prefix = f"{self.backend}-{self.workload}"
        boot = _read_json(self.run_dir / 'cells' / f'{prefix}-bootstrap' / 'result.json', {}) or {}
        out = {}
        if self.workload != 'materials':
            return out, boot
        for op, row in (boot.get('rules') or {}).items():
            if row.get('proposed') and (row.get('admission') or {}).get('status') == 'accepted':
                out[op] = base64.b64decode(row['ast_b64'])
        if self.spec['wave'] == 'warm':
            cold = _read_json(self.run_dir / 'cells' / f'{prefix}-cold-C' / 'result.json', {}) or {}
            status = cold.get('rule_status') or {}
            out = {op: ast for op, ast in out.items() if status.get(op) == 'adopted'}
        return out, boot

    def run_BC(self):
        arm, pooled = self.spec['arm'], self.spec['arm'] == 'C'
        rule_set, boot = self.admitted_rules()
        jobs = self.jobs()
        answers = {}
        boot_ids = set(workload.bootstrap_ids(self.workload)) if self.spec['wave'] == 'cold' else set()
        for jid, a in (boot.get('answers') or {}).items():
            if jid in boot_ids:
                answers[jid] = dict(a)
        rest = [j for j in jobs if j['id'] not in boot_ids]
        covered, fallback = {}, []
        for j in rest:
            if j['op'] in rule_set:
                value, _ = rules.apply(j['op'], rule_set[j['op']], j['text'])
                if value is not None:
                    covered[j['id']] = value
                    continue
            fallback.append(j)
        audit_ids = set()
        if covered:
            import oz_rulephase
            audit_ids = set(oz_rulephase.select_audits(sorted(covered), config.SEED, config.AUDITS))
        by_id = {j['id']: j for j in jobs}
        fb = {p: [j for j in fallback if j['producer'] == p] for p in config.PRODUCERS}
        au = {p: [j for j in rest if j['id'] in audit_ids and j['producer'] == p] for p in config.PRODUCERS}
        batches = schedule(fb, au, pooled=pooled)
        results = self.run_batches(batches, 1)
        model = {}
        for out in results.values():
            for jid, v in (out.get('answers') or {}).items():
                model[jid] = (v, out.get('call_id'))
        audits, quarantined, inconclusive = {}, set(), set()
        for jid in sorted(audit_ids):
            op = by_id[jid]['op']
            if jid not in model:
                audits[jid] = 'inconclusive'
                inconclusive.add(op)
            elif _canon(model[jid][0]) == _canon(covered[jid]):
                audits[jid] = 'agree'
            else:
                audits[jid] = 'disagree'
                quarantined.add(op)
        overflow = [j for j in rest if j['id'] in covered and by_id[j['id']]['op'] in quarantined
                    and j['id'] not in audit_ids]
        results2 = {}
        if overflow and not self.interrupted:
            fb2 = {p: [j for j in overflow if j['producer'] == p] for p in config.PRODUCERS}
            results2 = self.run_batches(schedule(fb2, {}, pooled=pooled), 2, first_reason='audit_overflow')
            for out in results2.values():
                for jid, v in (out.get('answers') or {}).items():
                    model[jid] = (v, out.get('call_id'))
        for j in rest:
            jid = j['id']
            if jid in covered and j['op'] not in quarantined:
                answers[jid] = {'answer': covered[jid], 'source': 'rule', 'call_id': None,
                                'audit': audits.get(jid)}
            elif jid in model:
                answers[jid] = {'answer': model[jid][0], 'source': 'model', 'call_id': model[jid][1],
                                'audit': audits.get(jid)}
        rule_status = {}
        for op in rule_set:
            rule_status[op] = 'quarantined' if op in quarantined else 'inconclusive' if op in inconclusive \
                else 'adopted'
        return {'answers': answers, 'batches': {k: v.get('outcome') for k, v in {**results, **results2}.items()},
                'rules_applied': sorted(rule_set), 'covered': len(covered), 'audits': audits,
                'rule_status': rule_status, 'scheduled_calls': len(batches) + len(results2),
                'overflow_jobs': len(overflow)}

    # ------------------------------------------------------------------------------------------- driver

    def run(self) -> int:
        spec, opts = self.spec, self.opts
        if (self.dir / 'DONE.json').exists():
            self.say(f"{spec['id']}: already complete; refusing to rerun (no call made)")
            return config.EXIT_ALREADY
        missing = [r for r in spec['requires'] if not (self.run_dir / 'cells' / r / 'DONE.json').exists()]
        if missing:
            self.say(f"{spec['id']}: required cells not complete: {missing} (no call made)")
            return config.EXIT_REQUIRES
        try:
            self.gates()
        except Stop as stop:
            self.say(f"{spec['id']}: {stop.reason}")
            return stop.code
        self.dir.mkdir(parents=True, exist_ok=True)
        for sub in ('prompts', 'captures', 'evidence', 'cells'):
            (self.run_dir / sub).mkdir(parents=True, exist_ok=True)
        self.recover_inflight()
        self.budget_obj = self.budget()
        self.slots = Slots(self.run_dir)
        try:
            self.exe = Executables(opts, self.backend)
        except RuntimeError as exc:
            self.say(f"{spec['id']}: {exc}")
            return config.EXIT_INCOMPLETE
        self.cache_certified = usage.cache_certified_for_route() if self.codex else None
        if self.codex:
            self.iso = isolation.Isolation(opts.baseline, self.run_dir, self.run_dir / 'evidence',
                                           frozen_inventory=isolation.load_inventory(), base_env=opts.base_env)
            if opts.mode == 'live':
                record_features(self.run_dir, self.iso, self.exe, spec['id'])
        doc = _read_json(self.dir / 'state.json', {}) or {}
        invocations = doc.get('invocations', []) + [{'mode': opts.mode, 'started_at': _now(), 'pid': os.getpid(),
                                                     'invocation': self.invocation,
                                                     'claude_weekly_percent': opts.claude_percent}]
        self.state('running', invocations=invocations, spec=spec)
        if opts.mode == 'live':
            _append(self.run_dir, 'evidence/quota.jsonl', {'cell': spec['id'], 'claude_weekly_percent':
                                                         opts.claude_percent, 'codex_primary_used_percent':
                                                         quota.codex_primary_used_percent(opts.sessions_dir)
                                                         if self.codex else None, 'at': _now()})
        # One Codex cell process at a time: A4.2 reconciliation must see every call that ended since the last one.
        guard = (isolation.file_lock(self.run_dir / 'locks' / 'codex-cells.lock', timeout=None) if self.codex
                 else contextlib.nullcontext())
        with guard:
            return self._run_locked(spec, opts)

    def _run_locked(self, spec, opts):
        try:
            if spec['arm'] == 'A':
                result = self.run_A()
            elif spec['arm'] == 'bootstrap':
                result = self.run_bootstrap()
            else:
                result = self.run_BC()
        except Stop as stop:
            self.state('incomplete', reason=stop.reason)
            self.say(f"{spec['id']}: {stop.reason}")
            return stop.code
        result.update(cell=spec['id'], spec=spec, mode=opts.mode)
        exhausted = [k for k, v in result.get('batches', {}).items() if v in ('budget_exhausted',)]
        if spec['arm'] == 'bootstrap' and result.get('call_outcome') == 'budget_exhausted':
            exhausted.append('bootstrap')
        _write_json(self.dir / 'result.json', result)
        if self.interrupted:
            code, reason = self.interrupted
            self.state('interrupted', reason=reason)
            self.say(f"{spec['id']}: interrupted: {reason}")
            return code
        if exhausted:
            self.state('incomplete', reason=f'allocation and reserve exhausted for batches {exhausted}')
            self.say(f"{spec['id']}: incomplete: allocation and reserve exhausted ({exhausted})")
            return config.EXIT_INCOMPLETE
        physical = len(self.prior_attempts())
        _write_json(self.dir / 'DONE.json', {'cell': spec['id'], 'completed_at': _now(), 'physical_calls': physical})
        self.state('complete', physical_calls=physical)
        self.say(f"{spec['id']}: complete ({physical} physical calls)")
        return config.EXIT_OK


def _canon(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


# ================================================================================================ live extras

def record_features(run_dir, iso, exe, cell_id):
    """A4.2: before each wave, the effective features from `codex features list` with the same worker home and the
    frozen disable options (a local command; no model request)."""
    prepared = iso.prepare(0)
    argv = [exe.exe, *exe.disable_args, 'features', 'list']
    done = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace',
                          env=prepared['env'], cwd=prepared['workdir'], timeout=120)
    iso.finish(0, prepared_sha256=prepared['auth_sha256'])
    rows = {}
    for line in done.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-1] in ('true', 'false'):
            rows[parts[0]] = parts[-1] == 'true'
    _write_json(Path(run_dir) / 'evidence' / f'features-{cell_id}.json',
                {'cell': cell_id, 'argv_sha256': hashlib.sha256(json.dumps(argv[1:]).encode()).hexdigest(),
                 'exit_code': done.returncode, 'features': rows, 'enabled_tool_features':
                     sorted(k for k in config.DISABLE_FEATURES if rows.get(k)), 'at': _now()})


def telemetry(opts) -> int:
    """A4.2 telemetry (live only): (1) `codex login status` with an empty CODEX_HOME and with a reconstructed worker
    home, no model request: authentication must come from the CODEX_HOME file, not an OS credential store; (2) one
    telemetry call (charged to the Codex telemetry allocation) on a neutral one job packet, whose home starts with
    auth.json only, whose working directory is empty and whose event stream is plain."""
    if opts.mode != 'live':
        print('telemetry runs live only; fake mode cannot establish properties of the real CLI', file=sys.stderr)
        return config.EXIT_USAGE
    gate = isolation.wave_gate(opts.baseline)
    if not gate['ok']:
        print(gate['reason'], file=sys.stderr)
        return config.EXIT_AUTH_GATE
    for g in (quota.claude_gate(opts.claude_percent), quota.codex_gate(opts.sessions_dir)):
        if not g['ok']:
            print(g['reason'], file=sys.stderr)
            return config.EXIT_QUOTA
    run_dir = opts.run_dir
    exe = Executables(opts, 'codex')
    iso = isolation.Isolation(opts.baseline, run_dir, run_dir / 'evidence', frozen_inventory=isolation.load_inventory(),
                              base_env=opts.base_env)
    empty = run_dir / 'homes' / 'empty-probe'
    shutil.rmtree(empty, ignore_errors=True)
    empty.mkdir(parents=True)
    env_empty = isolation.child_env(empty, opts.base_env)
    a = subprocess.run([exe.exe, 'login', 'status'], capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=env_empty, timeout=120)
    prepared = iso.prepare(1)
    b = subprocess.run([exe.exe, 'login', 'status'], capture_output=True, text=True, encoding='utf-8',
                       errors='replace', env=prepared['env'], timeout=120)
    iso.finish(1, prepared_sha256=prepared['auth_sha256'])
    shutil.rmtree(empty, ignore_errors=True)
    empty_out, worker_out = (a.stdout + a.stderr).lower(), (b.stdout + b.stderr).lower()
    auth_from_home = 'not logged in' in empty_out and 'logged in' in worker_out and 'not logged in' not in worker_out
    bud = budget_mod.Budget()
    for row in jsonl(run_dir / 'attempts.jsonl'):
        bud._attempts.append(row)
    try:
        bud.charge('codex', 'telemetry', 'telemetry', reason='nominal', outcome='launched')
    except budget_mod.BudgetExceeded as exc:
        print(f'telemetry not launched: {exc}', file=sys.stderr)
        return config.EXIT_INCOMPLETE
    prepared = iso.prepare(0)
    argv = isolation.codex_argv(exe.exe, config.CODEX_MODEL, config.CODEX_EFFORT, prepared['workdir'],
                                exe.disable_args)
    problems = isolation.verify_launch(argv=argv, env=prepared['env'], workdir=prepared['workdir'],
                                       exe_sha256=exe.exe_sha256, frozen=exe.frozen)
    home_before = sorted(os.listdir(prepared['home']))
    if problems:
        iso.finish(0, prepared_sha256=prepared['auth_sha256'])
        print(f'telemetry launch verification failed: {problems}', file=sys.stderr)
        return config.EXIT_TELEMETRY
    body = json.dumps({'v': '1g', 'goal': 'Telemetry check.', 'ops': ['Return the JSON string ok.'], 'refs': ['x'],
                       'jobs': [[0, ['j00', 0]]]}, separators=(',', ':'))
    stdin = prompts.SYSTEM + '\n\n' + body
    call_id = f'telemetry.t{len([r for r in jsonl(run_dir / "attempts.jsonl") if r.get("workload") == "telemetry"])}'
    (run_dir / 'prompts').mkdir(parents=True, exist_ok=True)
    (run_dir / 'prompts' / f'{call_id}.txt').write_text(stdin, encoding='utf-8')
    raw = spawn(run_dir, argv, stdin, prepared['env'], prepared['workdir'], external=True)
    outcome, reply, usage_raw, cls, why = judge_codex(raw)
    fin = iso.finish(0, auth_failure=outcome == 'auth_failure', prepared_sha256=prepared['auth_sha256'])
    visible = tokenizer.count([reply])[0] if isinstance(reply, str) else None
    dec = usage.decode_codex(usage_raw, cache_certified=usage.cache_certified_for_route())
    row = {'call_id': call_id, 'cell': 'telemetry', 'backend': 'codex', 'workload': 'telemetry',
           'allocation': 'telemetry', 'reason': 'nominal', 'kind': 'telemetry', 'outcome': outcome, 'why': why,
           'started_at': raw['started_at'], 'ended_at': raw['ended_at'], 'elapsed_s': raw['elapsed_s'],
           'usage_raw': usage_raw, 'usage': dec, 'visible_tokens': visible,
           'reasoning_issue': usage.reasoning_inclusion(usage_raw, visible) if dec['status'] != 'incomplete' else None,
           'events': {'verdict': cls['verdict'], 'notices': cls['notices'], 'uncertain': cls['uncertain'][:20]},
           'auth': {k: fin[k] for k in ('worker_auth_sha256', 'baseline_auth_sha256', 'auth_changed', 'auth_failure')},
           'prompt_sha256': prompts.sha256(stdin), 'charged_tokens': dec.get('charged_tokens') or 0}
    _append(run_dir, 'attempts.jsonl', row)
    (run_dir / 'captures').mkdir(parents=True, exist_ok=True)
    (run_dir / 'captures' / f'{call_id}.stdout').write_text(raw['stdout'], encoding='utf-8')
    (run_dir / 'captures' / f'{call_id}.stderr').write_text(raw['stderr'], encoding='utf-8')
    clean = home_before == ['auth.json'] and cls['verdict'] == 'plain' and outcome == 'ok' and not problems
    doc = {'auth_read_from_codex_home': bool(auth_from_home), 'sandbox_clean_home': bool(clean),
           'login_status': {'empty_home_reports_not_logged_in': 'not logged in' in empty_out,
                            'worker_home_reports_logged_in': 'logged in' in worker_out
                            and 'not logged in' not in worker_out},
           'call': call_id, 'home_listing_before': home_before, 'runtime_files_after': fin['runtime_files'],
           'stream_verdict': cls['verdict'], 'outcome': outcome, 'at': _now()}
    _write_json(run_dir / 'evidence' / 'telemetry.json', doc)
    if fin['auth_changed']:
        try:
            iso.propagate(0)
        except isolation.IsolationError as exc:
            print(f'propagation refused: {exc}', file=sys.stderr)
    problems = isolation.telemetry_checks(doc)
    print(json.dumps({'telemetry': doc['auth_read_from_codex_home'] and doc['sandbox_clean_home'],
                      'problems': problems}))
    return config.EXIT_OK if not problems else config.EXIT_TELEMETRY


# ================================================================================================ freeze

FREEZE_GLOBS = ('bench/ozmap_rep/*.py', 'bench/ozmap_rep/*.json', 'bench/ozmap_rep/certificate/*.json',
                'bench/ozmap_rep/ops/*.py', 'bench/ozmap_rep/ops/ops.md', 'bench/ozmap_rep/acceptance/*.py',
                'bench/ozmap_rep/acceptance/INTERFACE.md')
FREEZE_FILES = ('oz_rule.py', 'oz_registry.py', 'oz_batch.py', 'oz_reply.py', 'oz_rulephase.py', 'oz.py',
                'examples/bootstrap_shim.py', 'examples/claude_map_adapter.py', 'examples/claude_cli_adapter.py',
                'examples/codex_cli_adapter.py', 'docs/design/ozmap-2026-10-24/bootstrap-spec-excerpt.txt',
                'bench/ozmap/pilot.py', 'bench/ozmap/data.py', 'bench/ozmap/data/boolq-superglue-val.jsonl',
                'docs/design/ozmap-replication-2026-10-24/amendment-4.md',
                'docs/design/ozmap-replication-2026-10-24/amendment-4-13-caps.md',
                'docs/design/ozmap-replication-2026-10-24/expressibility-review.md')


def _freeze_files():
    names = set(FREEZE_FILES)
    for pattern in FREEZE_GLOBS:
        names |= {p.relative_to(config.REPO).as_posix() for p in config.REPO.glob(pattern)}
    names.discard('bench/ozmap_rep/freeze.json')
    return sorted(names)


def freeze_record(base_env=None):
    env = dict(os.environ if base_env is None else base_env)
    files = {}
    for rel in _freeze_files():
        data = (config.REPO / rel).read_bytes()
        if rel.endswith(('.py', '.md', '.json', '.txt')):
            data = data.replace(b'\r\n', b'\n')
        files[rel] = hashlib.sha256(data).hexdigest()
    disable, unsupported = cli_flags()
    out = {'schema': 'ozmap-rep.freeze/1', 'files': files, 'registry_manifest_sha256': rules.manifest_sha256(),
           'disable_options': disable, 'unsupported_options': unsupported, 'tokenizer': tokenizer.record(),
           'workload_sha256': hashlib.sha256(json.dumps(workload.materials(), sort_keys=True).encode()).hexdigest(),
           'interpreter': sys.executable}
    for name, backend in (('codex', 'codex'), ('claude', 'sonnet')):
        exe = shutil.which(name, path=env.get('PATH'))
        if exe:
            version = subprocess.run([exe, '--version'], capture_output=True, text=True, encoding='utf-8',
                                     errors='replace', timeout=60).stdout.strip()[:200]
            out[backend] = {'exe': exe, 'exe_sha256': _sha(exe), 'version': version}
    if 'codex' in out:
        argv = isolation.codex_argv(out['codex']['exe'], config.CODEX_MODEL, config.CODEX_EFFORT, 'slot-0', disable)
        out['codex']['argv_sha256'] = isolation.argv_sha256(argv)
    return out


def verify_freeze():
    frozen = _read_json(config.FREEZE_FILE)
    if not frozen:
        return ['bench/ozmap_rep/freeze.json is missing (run `python -m bench.ozmap_rep.run freeze` after sign-off)']
    now = freeze_record()
    problems = [f'{k} changed' for k in sorted(set(frozen['files']) | set(now['files']))
                if frozen['files'].get(k) != now['files'].get(k)]
    for key in ('registry_manifest_sha256', 'disable_options', 'workload_sha256'):
        if frozen.get(key) != now.get(key):
            problems.append(f'{key} changed')
    if (frozen.get('codex') or {}).get('version') != config.CODEX_CLI_VERSION:
        problems.append('the frozen Codex CLI is not codex-cli 0.160.0')
    for backend in ('codex', 'sonnet'):
        if (frozen.get(backend) or {}).get('exe_sha256') != (now.get(backend) or {}).get('exe_sha256'):
            problems.append(f'{backend} executable changed')
    return problems


# ================================================================================================ dry

def synthetic_baseline(directory):
    """An authentication only baseline whose access token (an unsigned JWT with no secret) is valid 30 days."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    exp = int((dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)).timestamp())
    b64 = lambda d: base64.urlsafe_b64encode(d).rstrip(b'=').decode()  # noqa: E731
    token = '.'.join([b64(b'{"alg":"none"}'), b64(json.dumps({'exp': exp, 'synthetic': True}).encode()), b64(b'x')])
    doc = {'auth_mode': 'chatgpt', 'tokens': {'id_token': 'synthetic', 'access_token': token,
                                              'refresh_token': 'synthetic'},
           'last_refresh': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    (directory / 'auth.json').write_text(json.dumps(doc), encoding='utf-8')
    return directory


def snapshot_preparation(run_dir):
    led = budget_mod.PrepLedger(config.LEDGER_FILE)
    _write_json(Path(run_dir) / 'preparation.json', {'counts': led.counts(), 'caps': config.PREP_CAPS,
                                                     'global_cap': config.GLOBAL_CAP,
                                                     'ledger': 'docs/design/ozmap-replication-2026-10-24/call-ledger.jsonl'})


def dry(run_dir, base_env=None, out=None) -> int:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = out or sys.stderr
    baseline = run_dir / 'auth' / 'baseline'
    if not (baseline / 'auth.json').exists():
        synthetic_baseline(baseline)
    if not (run_dir / 'preparation.json').exists():
        snapshot_preparation(run_dir)
    codes = {}
    for spec in cell_specs():
        opts = Options(run_dir, mode='fake', baseline=baseline, base_env=base_env, out=out)
        codes[spec['id']] = CellRun(spec, opts).run()
    from . import score
    score.score_run(run_dir, write=True)
    attempts = jsonl(run_dir / 'attempts.jsonl')
    cells, capacity = {}, {}
    for spec in cell_specs():
        st = _read_json(run_dir / 'cells' / spec['id'] / 'state.json', {}) or {}
        physical = sum(1 for a in attempts if a.get('cell') == spec['id'])
        cells[spec['id']] = {'state': st.get('state'), 'physical_calls': physical, 'exit_code': codes[spec['id']]}
        if spec['arm'] != 'bootstrap':
            res = _read_json(run_dir / 'cells' / spec['id'] / 'result.json', {}) or {}
            scheduled = max(physical, res.get('scheduled_calls') or 0, worst_case_calls(spec))
            capacity[spec['id']] = {'scheduled_calls': scheduled, 'bound': spec['nominal_calls'],
                                    'run_calls': physical, 'worst_case_zero_rules_worst_audits':
                                        worst_case_calls(spec)}
    spawns = jsonl(run_dir / 'spawns.jsonl')
    resolved = [r for r in jsonl(run_dir / 'resolved.jsonl')]
    report = {'external_calls': sum(1 for s in spawns if s.get('external')),
              'fake_calls': len(jsonl(run_dir / 'fake_calls.jsonl')), 'cells': cells, 'capacity': capacity,
              'real_cli_resolved': [r['name'] for r in resolved if r.get('path')], 'zero_rules': True,
              'within_bounds': all(c['scheduled_calls'] <= c['bound'] for c in capacity.values())}
    _write_json(run_dir / 'dry_report.json', report)
    ok = (report['external_calls'] == 0 and not report['real_cli_resolved'] and report['within_bounds']
          and all(c['state'] == 'complete' for c in cells.values()))
    out.write(f"dry: {report['fake_calls']} fake calls, {report['external_calls']} external calls, "
              f"{sum(1 for c in cells.values() if c['state'] == 'complete')}/16 cells complete\n")
    return 0 if ok else 1


# ================================================================================================ CLI

def build_parser():
    p = argparse.ArgumentParser(prog='python -m bench.ozmap_rep.run', description=__doc__.split('\n')[0])
    sub = p.add_subparsers(dest='command', required=True)
    plan = sub.add_parser('plan')
    plan.add_argument('--list-cells', action='store_true')
    cell = sub.add_parser('cell')
    cell.add_argument('id')
    for q in (cell, sub.add_parser('telemetry'), sub.add_parser('features')):
        q.add_argument('--run-dir', default=None)
        q.add_argument('--mode', choices=('fake', 'live'), default='fake')
        q.add_argument('--baseline', default=None)
        q.add_argument('--codex-sessions-dir', default=None)
        q.add_argument('--claude-weekly-percent', type=float, default=None)
    cell.add_argument('--stop-after', type=int, default=None)
    cell.add_argument('--fake-fail', type=int, default=0)
    cell.add_argument('--fake-refresh', type=int, default=None)
    d = sub.add_parser('dry')
    d.add_argument('--run-dir', required=True)
    sub.add_parser('freeze')
    sub.add_parser('verify-freeze')
    return p


def _opts(args):
    run_dir = Path(args.run_dir) if args.run_dir else config.RUNS_DEFAULT / 'replication'
    return Options(run_dir, mode=args.mode, baseline=args.baseline, sessions_dir=args.codex_sessions_dir,
                   claude_percent=args.claude_weekly_percent, stop_after=getattr(args, 'stop_after', None),
                   fake_fail=getattr(args, 'fake_fail', 0), fake_refresh=getattr(args, 'fake_refresh', None))


def main(argv=None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if args.command == 'plan':
        for s in cell_specs():
            print(json.dumps({k: s[k] for k in ('id', 'command', 'backend', 'workload', 'wave', 'arm',
                                                 'nominal_calls', 'requires', 'allocation')}))
        return 0
    if args.command == 'cell':
        spec = spec_by_id(args.id)
        if spec is None:
            print(f'unknown cell {args.id!r}; see `plan --list-cells`', file=sys.stderr)
            return config.EXIT_USAGE
        opts = _opts(args)
        opts.run_dir.mkdir(parents=True, exist_ok=True)
        if not (opts.run_dir / 'preparation.json').exists():
            snapshot_preparation(opts.run_dir)
        return CellRun(spec, opts).run()
    if args.command == 'dry':
        return dry(args.run_dir)
    if args.command == 'telemetry':
        return telemetry(_opts(args))
    if args.command == 'features':
        opts = _opts(args)
        if opts.mode != 'live':
            print('features records the real CLI; use --mode live', file=sys.stderr)
            return config.EXIT_USAGE
        iso = isolation.Isolation(opts.baseline, opts.run_dir, opts.run_dir / 'evidence',
                                  frozen_inventory=isolation.load_inventory())
        record_features(opts.run_dir, iso, Executables(opts, 'codex'), 'manual')
        return 0
    if args.command == 'freeze':
        rec = freeze_record()
        _write_json(config.FREEZE_FILE, rec)
        print(f'wrote {config.FREEZE_FILE} ({len(rec["files"])} files)')
        return 0
    if args.command == 'verify-freeze':
        problems = verify_freeze()
        print(json.dumps({'ok': not problems, 'problems': problems}, indent=1))
        return 0 if not problems else config.EXIT_FREEZE
    return config.EXIT_USAGE


if __name__ == '__main__':
    sys.exit(main())
