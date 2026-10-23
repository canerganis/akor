"""Controlled launcher and Job Object confinement for the O1 code-running worker (parent side). Standard library only.

run(payload, seed) starts sandbox_worker.py from a fresh empty temporary directory with the base interpreter and
`-P -S -s -B` (no -I or -E: those ignore PYTHONHASHSEED), an environment holding only PYTHONHASHSEED and SYSTEMROOT,
assigns the process to a Job Object (process memory 256 MiB, one active process, 2 s user CPU, kill on close, die on
unhandled exception), confirms the assignment and the limits, and only then writes the payload. A wall timeout of 5 s
terminates the job. Every run returns the worker's own report of its cwd, environment and hash seed so the caller can
check the confinement held for that run.

Outcomes: {'status': 'ok', 'rows': [...]} | {'status': 'refused', 'reasons': {...}} (the policy refused a unit, a
candidate verdict) | {'status': 'resource', 'reason': ...} (the candidate was stopped after setup: CPU, memory, wall,
crash; a candidate verdict). SandboxUnavailable is raised when the worker cannot be created, confined or brought to
its ready line: a verifier failure, never a candidate verdict.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
WORKER = HERE / 'sandbox_worker.py'
MEMORY_BYTES = 256 * 1024 * 1024
CPU_SECONDS = 2.0
WALL_SECONDS = 5.0
READY_SECONDS = 20.0
MAX_STDOUT = 64 * 1024 * 1024
ALLOWED_ENV = ('PYTHONHASHSEED', 'SYSTEMROOT')
LAUNCH_FLAGS = ('-P', '-S', '-s', '-B')

JOB_OBJECT_LIMIT_PROCESS_TIME = 0x2
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x8
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x400
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
LIMIT_FLAGS = (JOB_OBJECT_LIMIT_PROCESS_TIME | JOB_OBJECT_LIMIT_ACTIVE_PROCESS | JOB_OBJECT_LIMIT_PROCESS_MEMORY
               | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
BASIC_ACCOUNTING = 1
EXTENDED_LIMITS = 9
CREATE_NO_WINDOW = 0x08000000


class SandboxUnavailable(Exception):
    """The worker could not be created, confined or started; no candidate verdict exists."""


class _Basic(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]


class _Io(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                                              'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class _Extended(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', _Basic), ('IoInfo', _Io), ('ProcessMemoryLimit', ctypes.c_size_t),
                ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t),
                ('PeakJobMemoryUsed', ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [('TotalUserTime', ctypes.c_int64), ('TotalKernelTime', ctypes.c_int64),
                ('ThisPeriodTotalUserTime', ctypes.c_int64), ('ThisPeriodTotalKernelTime', ctypes.c_int64),
                ('TotalPageFaultCount', wintypes.DWORD), ('TotalProcesses', wintypes.DWORD),
                ('ActiveProcesses', wintypes.DWORD), ('TotalTerminatedProcesses', wintypes.DWORD)]


def _kernel32():
    if os.name != 'nt':
        raise SandboxUnavailable('the Job Object confinement needs Windows')
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.CreateJobObjectW.restype = wintypes.HANDLE
    k.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    k.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    k.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
                                            wintypes.LPVOID)
    k.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    k.IsProcessInJob.argtypes = (wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL))
    k.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k


class Job:
    """One Job Object with the frozen limits, verified by reading them back."""

    def __init__(self, *, memory=MEMORY_BYTES, cpu=CPU_SECONDS, processes=1):
        self.k = _kernel32()
        self.handle = self.k.CreateJobObjectW(None, None)
        if not self.handle:
            raise SandboxUnavailable('CreateJobObject failed: %d' % ctypes.get_last_error())
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = LIMIT_FLAGS
        info.BasicLimitInformation.PerProcessUserTimeLimit = int(cpu * 10_000_000)
        info.BasicLimitInformation.ActiveProcessLimit = processes
        info.ProcessMemoryLimit = memory
        if not self.k.SetInformationJobObject(self.handle, EXTENDED_LIMITS, ctypes.byref(info), ctypes.sizeof(info)):
            self.close()
            raise SandboxUnavailable('SetInformationJobObject failed: %d' % ctypes.get_last_error())
        back = self.limits()
        want = {'flags': LIMIT_FLAGS, 'cpu_100ns': int(cpu * 10_000_000), 'processes': processes, 'memory': memory}
        if back != want:
            self.close()
            raise SandboxUnavailable('the Job Object limits did not read back as set: %r' % (back,))

    def limits(self) -> dict:
        info = _Extended()
        if not self.k.QueryInformationJobObject(self.handle, EXTENDED_LIMITS, ctypes.byref(info), ctypes.sizeof(info),
                                                None):
            raise SandboxUnavailable('QueryInformationJobObject failed: %d' % ctypes.get_last_error())
        b = info.BasicLimitInformation
        return {'flags': b.LimitFlags, 'cpu_100ns': b.PerProcessUserTimeLimit, 'processes': b.ActiveProcessLimit,
                'memory': info.ProcessMemoryLimit}

    def assign(self, process_handle) -> None:
        if not self.k.AssignProcessToJobObject(self.handle, process_handle):
            raise SandboxUnavailable('AssignProcessToJobObject failed: %d' % ctypes.get_last_error())
        inside = wintypes.BOOL()
        if not self.k.IsProcessInJob(process_handle, self.handle, ctypes.byref(inside)) or not inside.value:
            raise SandboxUnavailable('the worker is not inside its Job Object')

    def accounting(self) -> dict:
        info = _Accounting()
        if not self.k.QueryInformationJobObject(self.handle, BASIC_ACCOUNTING, ctypes.byref(info), ctypes.sizeof(info),
                                                None):
            return {}
        return {'user_seconds': info.TotalUserTime / 1e7, 'kernel_seconds': info.TotalKernelTime / 1e7,
                'processes': info.TotalProcesses}

    def terminate(self) -> None:
        self.k.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


def interpreter() -> str:
    """The base interpreter: a venv's python.exe on Windows is a redirector that starts a second process, which the
    one-process limit would refuse."""
    exe = getattr(sys, '_base_executable', None) or sys.executable
    if not Path(exe).exists():
        raise SandboxUnavailable('the base interpreter is missing: ' + str(exe))
    return exe


def environment(seed: int) -> dict:
    return {'PYTHONHASHSEED': str(int(seed)), 'SYSTEMROOT': os.environ.get('SYSTEMROOT', r'C:\Windows')}


def _lines(text: str) -> list:
    out = []
    for line in text.splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({'garbled': line[:200]})
    return out


def run(payload: dict, seed: int, *, wall=WALL_SECONDS, cpu=CPU_SECONDS, memory=MEMORY_BYTES, argv_extra=None,
        worker=WORKER) -> dict:
    """Run one payload in one confined worker with the given hash seed (see the module docstring). worker selects the
    worker program (the evaluator brings its own); the launcher and the confinement are the same for both."""
    started = time.perf_counter()
    temp = Path(tempfile.mkdtemp(prefix='o1-sbx-'))
    job = proc = None
    try:
        shutil.copyfile(worker, temp / 'w.py')
        job = Job(memory=memory, cpu=cpu)
        argv = [interpreter(), *LAUNCH_FLAGS, *(argv_extra or ()), 'w.py']
        try:
            proc = subprocess.Popen(argv, cwd=str(temp), env=environment(seed), stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
        except OSError as exc:
            raise SandboxUnavailable('the worker could not start: ' + type(exc).__name__) from None
        try:
            job.assign(int(proc._handle))
        except SandboxUnavailable:
            proc.kill()
            proc.communicate()
            raise
        data = json.dumps(payload, ensure_ascii=True).encode('ascii')
        try:
            out, err = proc.communicate(data, timeout=wall)
            timed_out = False
        except subprocess.TimeoutExpired:
            job.terminate()
            out, err = proc.communicate()
            timed_out = True
        acct = job.accounting()
    finally:
        if job is not None:
            job.close()
        shutil.rmtree(temp, ignore_errors=True)
    lines = _lines(out[:MAX_STDOUT].decode('ascii', 'replace'))
    elapsed = time.perf_counter() - started
    base = {'seed': seed, 'exit_code': proc.returncode, 'wall_seconds': round(elapsed, 4),
            'cpu_seconds': round(acct.get('user_seconds', 0.0), 4), 'workdir': str(temp)}
    ready = lines[0].get('ready') if lines and isinstance(lines[0], dict) else None
    if ready is None:
        raise SandboxUnavailable('the worker never reached its ready line (exit %s%s): %s' % (
            proc.returncode, ', wall timeout' if timed_out else '', err.decode('utf-8', 'replace')[-300:]))
    base['meta'] = ready
    problems = confinement_problems(ready, temp, seed)
    if problems:
        raise SandboxUnavailable('confinement check failed: ' + '; '.join(problems))
    result = lines[1] if len(lines) > 1 and isinstance(lines[1], dict) else None
    if result is not None and 'refused' in result:
        return dict(base, status='refused', reasons=result['refused'])
    if result is None or 'rows' not in result:
        reason = ('wall_timeout' if timed_out else 'cpu_limit' if acct.get('user_seconds', 0) >= cpu * 0.95
                  else 'stopped (exit %s)' % proc.returncode)
        return dict(base, status='resource', reason=reason)
    return dict(base, status='ok', rows=result['rows'])


def confinement_problems(meta: dict, workdir: Path, seed: int) -> list:
    """What the worker reported about itself that breaks the frozen confinement (empty when it held)."""
    problems = []
    if Path(meta.get('cwd', '')).resolve() != Path(workdir).resolve():
        problems.append('cwd is not the fresh temporary directory')
    extra = sorted(set(meta.get('env', [])) - {k.upper() for k in ALLOWED_ENV} - set(ALLOWED_ENV))
    if extra:
        problems.append('unexpected environment variables: ' + ', '.join(extra))
    flags = meta.get('flags', {})
    if not flags.get('no_site') or not flags.get('safe_path') or flags.get('ignore_environment'):
        problems.append('launcher flags are not -P -S without -E')
    return problems


def run_pair(payload: dict, **options) -> tuple:
    """(seed 0 result, seed 1 result or None): seed 1 runs only when seed 0 completed every row."""
    first = run(payload, 0, **options)
    if first['status'] != 'ok':
        return first, None
    return first, run(payload, 1, **options)
