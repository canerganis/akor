"""Supervised process trees for A4.14.1 (fail closed execution). Standard library only.

Every child the harness starts (a model call or a local CLI probe) runs in a supervised process tree:

* Windows: the child is created suspended, assigned to a job object whose last handle kills every process of the job
  (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, no breakaway), and only then resumed. A descendant can therefore never outlive
  the job, also when the runner itself dies (the OS closes the job handle), and `gone()` asks the job itself how many
  of its processes are still active, so termination of the whole tree is established, not only of the parent
  (Astra council round 3, item 9).
* POSIX: the child leads a new session and process group; `gone()` asks whether any process of the group remains.

`supervised` is False when the tree could not be put under supervision (job assignment refused); the caller must
then treat termination of descendants as not established.
"""
from __future__ import annotations

import os
import subprocess
import time

CREATE_SUSPENDED = 0x00000004
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1


def _k32():
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    k32.SetInformationJobObject.restype = wintypes.BOOL
    k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    k32.AssignProcessToJobObject.restype = wintypes.BOOL
    k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    k32.QueryInformationJobObject.restype = wintypes.BOOL
    k32.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.c_void_p)
    k32.TerminateJobObject.restype = wintypes.BOOL
    k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return k32


def _structs():
    import ctypes
    from ctypes import wintypes

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                    ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                    ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD),
                    ('SchedulingClass', wintypes.DWORD)]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ('ReadOperationCount', 'WriteOperationCount',
                                                   'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount',
                                                   'OtherTransferCount')]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', BASIC_LIMIT), ('IoInfo', IO_COUNTERS),
                    ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

    class ACCOUNTING(ctypes.Structure):
        _fields_ = [('TotalUserTime', ctypes.c_int64), ('TotalKernelTime', ctypes.c_int64),
                    ('ThisPeriodTotalUserTime', ctypes.c_int64), ('ThisPeriodTotalKernelTime', ctypes.c_int64),
                    ('TotalPageFaultCount', wintypes.DWORD), ('TotalProcesses', wintypes.DWORD),
                    ('ActiveProcesses', wintypes.DWORD), ('TotalTerminatedProcesses', wintypes.DWORD)]
    return EXTENDED_LIMIT, ACCOUNTING


class Tree:
    """One supervised process tree. Use: start(), journal the pid, resume(), wait; kill() and gone() establish the
    end of every process of the tree; close() releases the supervision (on Windows this kills what is left)."""

    def __init__(self):
        self.proc = None
        self.job = None
        self.supervised = False
        self.resumed = False
        self.problem = None

    # ------------------------------------------------------------------------------------------- start
    def start(self, argv, **popen):
        if os.name == 'nt':
            import ctypes
            k32 = _k32()
            job = k32.CreateJobObjectW(None, None)
            if job:
                EXTENDED_LIMIT, _ = _structs()
                info = EXTENDED_LIMIT()
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                if not k32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                                   ctypes.byref(info), ctypes.sizeof(info)):
                    k32.CloseHandle(job)
                    job = None
            self.job = job
            flags = popen.pop('creationflags', 0) | CREATE_SUSPENDED
            self.proc = subprocess.Popen(argv, creationflags=flags, **popen)
            if self.job and k32.AssignProcessToJobObject(self.job, int(self.proc._handle)):
                self.supervised = True
            else:
                self.problem = 'the child could not be assigned to a supervising job object'
        else:
            self.proc = subprocess.Popen(argv, start_new_session=True, **popen)
            self.supervised = True
            self.resumed = True
        return self.proc

    def resume(self):
        if self.resumed or self.proc is None:
            return
        import ctypes
        ntdll = ctypes.WinDLL('ntdll')
        ntdll.NtResumeProcess.argtypes = (ctypes.c_void_p,)
        status = ntdll.NtResumeProcess(ctypes.c_void_p(int(self.proc._handle)))
        if status != 0:
            raise OSError(f'NtResumeProcess failed with status {status:#x}')
        self.resumed = True

    # ------------------------------------------------------------------------------------------- end
    def active(self):
        """The number of processes of the tree still running, or None when it cannot be established."""
        if self.proc is None:
            return 0
        if os.name == 'nt':
            if not self.supervised or not self.job:
                return None  # descendants of an unsupervised child cannot be enumerated: not established
            import ctypes
            _, ACCOUNTING = _structs()
            acct = ACCOUNTING()
            if not _k32().QueryInformationJobObject(self.job, JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
                                                    ctypes.byref(acct), ctypes.sizeof(acct), None):
                return None
            return int(acct.ActiveProcesses)
        try:
            os.killpg(self.proc.pid, 0)
        except ProcessLookupError:
            return 0
        except PermissionError:
            return 1
        except OSError:
            return None
        self.proc.poll()
        return 1

    def kill(self):
        if self.proc is None:
            return
        try:
            if os.name == 'nt':
                if self.supervised and self.job:
                    _k32().TerminateJobObject(self.job, 1)
                else:
                    subprocess.run(['taskkill', '/T', '/F', '/PID', str(self.proc.pid)], capture_output=True,
                                   timeout=60)
            else:
                import signal
                os.killpg(self.proc.pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            pass

    def gone(self, seconds=60.0):
        """True once every process of the tree has ended (established through the job or the process group);
        False when that cannot be established within `seconds`."""
        end = time.monotonic() + seconds
        while True:
            try:
                if self.proc is not None:
                    self.proc.poll()
            except OSError:
                pass
            n = self.active()
            if n == 0 and (self.proc is None or self.proc.returncode is not None):
                return True
            if time.monotonic() >= end:
                return False
            time.sleep(0.05)

    def close(self):
        """Release the supervision. On Windows closing the job kills every process still in it."""
        if os.name == 'nt' and self.job:
            try:
                _k32().CloseHandle(self.job)
            except OSError:
                pass
            self.job = None

    def record(self):
        return {'supervised': self.supervised, 'problem': self.problem,
                'mechanism': 'job_object' if os.name == 'nt' else 'process_group'}
