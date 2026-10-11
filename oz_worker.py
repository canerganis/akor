"""Provider-neutral OZ/7 worker and opt-in JSON-over-stdio adapter. No API keys needed."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

from typing import Callable

from oz import Channel, Error
from oz_reply import PROTOCOL, check_capabilities, new_receipt, validate_reply, validate_usage
from oz_runtime import Inbox, Outcome

class AdapterError(Error):
    def __init__(self, code: str):
        allowed = {'adapter_start_failed', 'adapter_output_too_large', 'adapter_invalid_json'}
        self.code = (code if isinstance(code, str) and (code in allowed or re.fullmatch(r'adapter_exit_-?[0-9]{1,10}', code))
                     else 'adapter_failure')
        super().__init__(self.code)


def loads(text: str):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise Error('duplicate JSON key')
            obj[key] = value
        return obj
    def constant(_):
        raise Error('non-finite JSON value')
    return json.loads(text, object_pairs_hook=unique, parse_constant=constant)


@dataclass(frozen=True)
class StdioAdapter:
    argv: tuple[str, ...]
    capabilities: dict | None = None
    cwd: Path | None = None
    timeout: float = 120
    max_output_bytes: int = 1048576

    def __post_init__(self):
        if isinstance(self.argv, str):
            raise Error('adapter argv must be a sequence, not a shell command string')
        object.__setattr__(self, 'argv', tuple(self.argv))
        if (not self.argv or any(not isinstance(s, str) or not s or '\x00' in s for s in self.argv)
                or type(self.timeout) not in {int, float} or not 0 < self.timeout <= 3600
                or type(self.max_output_bytes) is not int or not 1 <= self.max_output_bytes <= 8388608):
            raise Error('invalid adapter command or limits')

    def __call__(self, request: dict) -> dict:
        payload = json.dumps(request, ensure_ascii=False).encode('utf-8')
        try:
            proc = subprocess.Popen(self.argv, cwd=self.cwd, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1'),
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                    start_new_session=os.name != 'nt')
        except OSError as exc:
            raise AdapterError('adapter_start_failed') from None
        try:
            stdout, stderr = proc.communicate(payload, timeout=self.timeout)
        except BaseException:
            # Only the process group/tree started by this adapter is terminated.
            if os.name == 'nt':
                try:
                    subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    proc.kill()
                if proc.poll() is None:
                    proc.kill()
            else:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
            raise
        if proc.returncode:
            raise AdapterError(f'adapter_exit_{proc.returncode}')
        if len(stdout) > self.max_output_bytes or len(stderr) > self.max_output_bytes:
            raise AdapterError('adapter_output_too_large')
        try:
            return loads(stdout.decode('utf-8'))
        except (ValueError, UnicodeError) as exc:
            raise AdapterError('adapter_invalid_json') from exc


class Worker:
    """One bounded attempt per call; no background polling or provider lock-in.

    Callable adapters must return before timeout. StdioAdapter enforces its
    timeout by terminating its child process; an arbitrary Python callable
    cannot be safely forcibly interrupted by this worker.
    """

    def __init__(self, inbox: Inbox, channel: Channel, adapter: Callable[[dict], dict], *,
                 counters, capabilities: dict | None = None, owner: str = 'worker', max_tokens: int = 2048,
                 batch_size: int = 16, timeout: float = 120, retry_delay: float = 2, reply_mode: str = 'rows',
                 encoding: str = 'off', min_savings: int = 0):
        if not callable(adapter) or type(timeout) not in {int, float} or not 0 < timeout <= 3600:
            raise Error('invalid adapter or timeout')
        if isinstance(adapter, StdioAdapter) and adapter.timeout > timeout:
            raise Error('stdio adapter timeout must not exceed worker timeout')
        if type(retry_delay) not in {int, float} or not 0 <= retry_delay <= 86400:
            raise Error('invalid retry delay')
        # Negotiation happens here, before any claim or call; never from model output.
        check_capabilities(capabilities if capabilities is not None else getattr(adapter, 'capabilities', None),
                           reply_mode)
        self.inbox, self.channel, self.adapter = inbox, channel, adapter
        self.options = dict(counters=tuple(counters), owner=owner, max_tokens=max_tokens, limit=batch_size,
                            lease_seconds=timeout + 30, encoding=encoding, min_savings=min_savings,
                            reply_mode=reply_mode)
        self.retry_delay = retry_delay

    def run_once(self) -> dict:
        # A fresh receipt per attempt, made before planning so it is charged.
        receipt = new_receipt()
        claimed = self.inbox.claim_prepared(self.channel, receipt=receipt, **self.options)
        if claimed is None:
            return {'status': 'idle', 'model_calls': 0}
        delivery, packet = claimed
        ids = tuple(j.id for j in delivery.jobs)
        request = {'protocol': PROTOCOL, 'language': 'OZ/7', 'encoding': packet.encoding,
                   'wire_format': packet.mode, 'reply_mode': packet.reply_mode, 'binding': delivery.binding,
                   'receipt': receipt, 'ids': list(ids), 'prompt': packet.text,
                   'prompt_tokens': list(packet.tokens)}
        start = time.monotonic()
        report = {'language': 'OZ/7', 'encoding': packet.encoding, 'wire_format': packet.mode,
                  'reply_mode': packet.reply_mode, 'prompt_tokens': list(packet.tokens),
                  'json_tokens': packet.json_tokens and list(packet.json_tokens),
                  'saved_tokens': packet.saved_tokens and list(packet.saved_tokens),
                  'adapter_calls': 1, 'usage': {}, 'verification': 'unverified'}
        phase = 'adapter'
        try:
            response = self.adapter(request)
            phase = 'validation'
            if not isinstance(response, dict) or 'reply' not in response or set(response) - {'reply', 'usage'}:
                raise Error('adapter response must be {"reply":...,"usage":...}')
            # Usage is provider accounting; keep it even when the reply is invalid.
            report['usage'] = validate_usage(response.get('usage', {}))
            outcomes = {mid: Outcome(status, text) for mid, (status, text)
                        in validate_reply(response['reply'], ids, receipt, packet.reply_mode).items()}
            report['status'] = 'received'
        except Exception as exc:
            # Do not store arbitrary provider exception text: it may contain credentials.
            code = ('adapter_timeout' if isinstance(exc, subprocess.TimeoutExpired) else exc.code
                    if isinstance(exc, AdapterError) else 'adapter_invalid_reply'
                    if phase == 'validation' else 'adapter_exception')
            reason = code + ' (' + type(exc).__name__ + ')'
            outcomes = {mid: Outcome('retry', reason) for mid in ids}
            report['status'] = 'adapter_error'
            report['error_type'] = type(exc).__name__
            report['error_code'] = code
        report['wall_seconds'] = round(time.monotonic() - start, 6)
        self.inbox.settle(delivery, outcomes, retry_delay=self.retry_delay, report=report)
        return dict(report, ids=list(ids), outcomes={mid: o.status for mid, o in outcomes.items()})


def process_host(inbox: Inbox, channel: Channel, *, owner='host', limit=64) -> dict:
    """Record claims without running tools, approving work or acting on stop requests."""
    delivery = inbox.claim(channel, owner=owner, kind='host', limit=limit)
    if delivery is None:
        return {'status': 'idle', 'model_calls': 0}
    results = {}
    for job in delivery.jobs:
        events = channel.dispatch(job.wire, binding=channel.binding)['host_events']
        events = [{k: event[k] for k in ('event', 'ref')} for event in events]
        results[job.id] = Outcome('ok', json.dumps({'events': events, 'action': 'recorded_only'}, ensure_ascii=False))
    report = {'status': 'host_recorded', 'model_calls': 0, 'adapter_calls': 0}
    inbox.settle(delivery, results, report=report)
    return dict(report, ids=[j.id for j in delivery.jobs])
