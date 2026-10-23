"""Durable runner (foundation record clause 5, completion protocol). Standard library only.

    python oz_runner.py <capture_dir> <receipt> -- <adapter argv...>

The runner reads <capture_dir>/<receipt>.request.json, runs the adapter command with that request on stdin, and
publishes the completion itself: the adapter's exit status and stdout, bound to the receipt and to the digest of the
request bytes, go to a temporary file that is flushed, synchronized and atomically renamed to <receipt>.done on the
same filesystem. Only a valid record published this way counts as a completed capture; a completed capture can record
a failed process and is never accepted work by itself. If the coordinator dies, the runner still publishes, so a
later coordinator can reuse the capture without another model call. That holds when the coordinator process is killed
or crashes. A coordinator that is still running and unwinds (KeyboardInterrupt, a call timeout or any other exception
inside the adapter call) terminates the runner and its adapter tree first, so nothing is published and recovery
records the dispatch as uncertain, exactly as when the runner dies on its own. If the adapter executable cannot be
started, the runner publishes a record marked start_failed (confirmed non-execution), not a failed run.

Process identity is the PID plus the process creation time (GetProcessTimes through ctypes on Windows, /proc on Linux);
a PID alone is not an identity.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

CAPTURE_SCHEMA = 'oz.capture/1'
STILL_ACTIVE = 259


def _windows_times(pid: int):
    """(creation time in 100 ns units, alive) of a Windows process, or None when it cannot be opened."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, *(ctypes.POINTER(wintypes.FILETIME),) * 4)
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        code = wintypes.DWORD()
        alive = bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime, alive
    finally:
        kernel.CloseHandle(handle)


def _posix_start(pid: int):
    try:
        stat = Path(f'/proc/{pid}/stat').read_text()
    except OSError:
        return None
    return int(stat.rsplit(')', 1)[1].split()[19])


def process_identity(pid: int) -> dict | None:
    """{pid, created} of a running process, or None when its creation time is unavailable."""
    try:
        if os.name == 'nt':
            found = _windows_times(pid)
            return None if found is None else {'pid': pid, 'created': found[0]}
        start = _posix_start(pid)
        return None if start is None else {'pid': pid, 'created': start}
    except (OSError, ValueError, AttributeError, IndexError):
        return None


def process_alive(identity: dict | None) -> bool | None:
    """True when that exact process (PID and creation time) is still running, False when it is gone, None when no
    identity was recorded."""
    if not isinstance(identity, dict) or 'pid' not in identity or 'created' not in identity:
        return None
    try:
        if os.name == 'nt':
            found = _windows_times(identity['pid'])
            return found is not None and found[0] == identity['created'] and found[1]
        return _posix_start(identity['pid']) == identity['created']
    except (OSError, ValueError, AttributeError, IndexError):
        return None


def publish(path: Path, data: bytes) -> None:
    """Write data to a temporary file, flush and fsync it, then atomically rename it to path."""
    temp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    with open(temp, 'wb') as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)
    if os.name != 'nt':
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def request_path(directory, receipt: str) -> Path:
    return Path(directory) / f'{receipt}.request.json'


def done_path(directory, receipt: str) -> Path:
    return Path(directory) / f'{receipt}.done'


def envelope_path(directory, receipt: str) -> Path:
    """Where an adapter that keeps its raw provider envelope writes it (OZ_ENVELOPE_PATH); the runner folds it into the
    completion record, so the envelope is bound to the same receipt and request bytes."""
    return Path(directory) / f'{receipt}.envelope'


def read_capture(directory, receipt: str, request_sha256: str | None = None) -> dict | None:
    """The completed capture of a receipt, or None. A file that is missing, not one JSON object of this schema, bound to
    another receipt or (when given) to other request bytes, does not count."""
    try:
        record = json.loads(done_path(directory, receipt).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        return None
    if (not isinstance(record, dict) or record.get('v') != CAPTURE_SCHEMA or record.get('receipt') != receipt
            or type(record.get('exit_code')) is not int or not isinstance(record.get('stdout_b64'), str)
            or ('start_failed' in record and record['start_failed'] is not True)
            or (request_sha256 is not None and record.get('request_sha256') != request_sha256)):
        return None
    try:
        record['stdout'] = base64.b64decode(record['stdout_b64'], validate=True)
    except ValueError:
        return None
    return record


def main(argv: list[str]) -> int:
    if len(argv) < 4 or argv[2] != '--':
        print('usage: oz_runner.py CAPTURE_DIR RECEIPT -- ADAPTER_ARGV...', file=sys.stderr)
        return 2
    directory, receipt, command = Path(argv[0]), argv[1], argv[3:]
    data = request_path(directory, receipt).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    envelope = envelope_path(directory, receipt)
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1',
                                         OZ_ENVELOPE_PATH=str(envelope)),
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except OSError:
        # The adapter never started, so it never ran: publish that fact (confirmed non-execution), not a failed run.
        record = {'v': CAPTURE_SCHEMA, 'receipt': receipt, 'request_sha256': digest, 'exit_code': -1,
                  'stdout_b64': '', 'stderr_bytes': 0, 'runner': process_identity(os.getpid()), 'adapter': None,
                  'start_failed': True}
        publish(done_path(directory, receipt), json.dumps(record, separators=(',', ':')).encode('utf-8'))
        return 0
    child = process_identity(proc.pid)
    stdout, stderr = proc.communicate(data)
    record = {'v': CAPTURE_SCHEMA, 'receipt': receipt, 'request_sha256': digest,
              'exit_code': proc.returncode, 'stdout_b64': base64.b64encode(stdout).decode('ascii'),
              'stderr_bytes': len(stderr), 'runner': process_identity(os.getpid()), 'adapter': child}
    try:
        # The adapter's raw provider envelope, when it wrote one (additive field; absent means not kept).
        record['envelope_b64'] = base64.b64encode(envelope.read_bytes()).decode('ascii')
    except OSError:
        pass
    publish(done_path(directory, receipt), json.dumps(record, separators=(',', ':')).encode('utf-8'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
