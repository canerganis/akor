"""Provider-neutral worker and opt-in JSON-over-stdio adapter. No API keys needed."""
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
from oz_runtime import Inbox, Outcome

RESPONSE_CONTRACT = (
    'Reply only JSON {"results":[["ID",0,"result text"],...]}. '
    'Include every delivered ID once; no other IDs. Status: 0=completed, '
    '1=retryable failure, 2=permanent failure. Report only actual outcomes; '
    'preserve uncertainty. This response format overrides frame-generation instructions.'
)


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


def validate_reply(value: object, ids: tuple[str, ...]) -> tuple[dict[str, Outcome], dict[str, int]]:
    if not isinstance(value, dict) or set(value) - {'results', 'usage'} or not isinstance(value.get('results'), list):
        raise Error('adapter reply must contain results and optional usage')
    outcomes = {}
    for row in value['results']:
        if (not isinstance(row, list) or len(row) != 3 or not isinstance(row[0], str)
                or row[0] not in ids or row[0] in outcomes or type(row[1]) is not int
                or row[1] not in {0, 1, 2} or not isinstance(row[2], str) or not row[2].strip()
                or len(row[2].encode('utf-8')) > 65536):
            raise Error('invalid, duplicated or unexpected result row')
        outcomes[row[0]] = Outcome({0: 'ok', 1: 'retry', 2: 'failed'}[row[1]], row[2])
    if set(outcomes) != set(ids):
        raise Error('adapter reply is missing delivered IDs')
    usage = value.get('usage', {})
    if (not isinstance(usage, dict) or set(usage) - {'input_tokens', 'output_tokens', 'cached_input_tokens'}
            or any(type(n) is not int or n < 0 for n in usage.values())):
        raise Error('invalid provider-reported usage')
    return outcomes, usage


@dataclass(frozen=True)
class StdioAdapter:
    argv: tuple[str, ...]
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
                 counters, owner: str = 'worker', max_tokens: int = 2048, batch_size: int = 16,
                 timeout: float = 120, retry_delay: float = 2):
        if not callable(adapter) or type(timeout) not in {int, float} or not 0 < timeout <= 3600:
            raise Error('invalid adapter or timeout')
        if isinstance(adapter, StdioAdapter) and adapter.timeout > timeout:
            raise Error('stdio adapter timeout must not exceed worker timeout')
        if type(retry_delay) not in {int, float} or not 0 <= retry_delay <= 86400:
            raise Error('invalid retry delay')
        self.inbox, self.channel, self.adapter = inbox, channel, adapter
        self.options = dict(counters=tuple(counters), owner=owner, max_tokens=max_tokens,
                            limit=batch_size, lease_seconds=timeout + 30, response_contract=RESPONSE_CONTRACT)
        self.retry_delay = retry_delay

    def run_once(self) -> dict:
        claimed = self.inbox.claim_prepared(self.channel, **self.options)
        if claimed is None:
            return {'status': 'idle', 'model_calls': 0}
        delivery, packet = claimed
        ids = tuple(j.id for j in delivery.jobs)
        request = {'protocol': 'oz.adapter/1', 'binding': delivery.binding,
                   'ids': list(ids), 'attempts': {j.id: j.attempt for j in delivery.jobs},
                   'prompt': packet.text, 'estimated_input_tokens': list(packet.tokens)}
        start = time.monotonic()
        report = {'mode': packet.mode, 'estimated_input_tokens': list(packet.tokens),
                  'adapter_calls': 1, 'provider_reported_usage': {}}
        phase = 'adapter'
        try:
            reply = self.adapter(request)
            phase = 'validation'
            outcomes, usage = validate_reply(reply, ids)
            report['provider_reported_usage'] = usage
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
