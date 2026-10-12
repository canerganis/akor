"""Provider-neutral OZ/9 worker and opt-in JSON-over-stdio adapter. No API keys needed."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import uuid

from typing import Callable

from oz import Channel, Error
from oz_reply import LANGUAGE, PROTOCOL, RETRY_REASON, check_capabilities, loads, regroup, validate_usage
from oz_runtime import Inbox, Outcome

LEDGER_SCHEMA = 'akor.call/1'
USAGE_MAP = (('input_tokens', 'input_tokens'), ('output_tokens', 'output_tokens'),
             ('cache_read_tokens', 'cached_input_tokens'), ('cache_write_tokens', 'cache_creation_input_tokens'),
             ('reasoning_tokens', 'reasoning_output_tokens'), ('total_tokens', None))


class AdapterError(Error):
    def __init__(self, code: str):
        allowed = {'adapter_start_failed', 'adapter_output_too_large', 'adapter_invalid_json'}
        self.code = (code if isinstance(code, str) and (code in allowed or re.fullmatch(r'adapter_exit_-?[0-9]{1,10}', code))
                     else 'adapter_failure')
        super().__init__(self.code)


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


def _digest(text: str | None):
    """(sha256, utf-8 byte length) of text; (None, None) when it is unknown or not encodable."""
    try:
        data = text.encode('utf-8')
    except (AttributeError, UnicodeEncodeError):
        return None, None
    return hashlib.sha256(data).hexdigest(), len(data)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class Worker:
    """One bounded attempt per call; no background polling or provider lock-in.

    Callable adapters must return before timeout. StdioAdapter enforces its
    timeout by terminating its child process; an arbitrary Python callable
    cannot be safely forcibly interrupted by this worker.

    With ledger_path every call appends call_start and call_end lines
    (schema akor.call/1) to an append-only JSONL file; unknown values are null.
    """

    def __init__(self, inbox: Inbox, channel: Channel, adapter: Callable[[dict], dict], *,
                 counters, capabilities: dict | None = None, owner: str = 'worker', max_tokens: int = 2048,
                 batch_size: int = 64, timeout: float = 120, retry_delay: float = 2,
                 context_policy: str = 'needed', min_batch: int = 1, max_wait: float = 0,
                 ledger_path: str | Path | None = None, tokenizer: str | None = None):
        if not callable(adapter) or type(timeout) not in {int, float} or not 0 < timeout <= 3600:
            raise Error('invalid adapter or timeout')
        if (type(min_batch) is not int or not 1 <= min_batch <= batch_size
                or type(max_wait) not in {int, float} or not 0 <= max_wait <= 86400):
            raise Error('min_batch must be 1..batch_size and max_wait 0..86400 seconds')
        self.min_batch, self.max_wait = min_batch, max_wait
        if isinstance(adapter, StdioAdapter) and adapter.timeout > timeout:
            raise Error('stdio adapter timeout must not exceed worker timeout')
        if type(retry_delay) not in {int, float} or not 0 <= retry_delay <= 86400:
            raise Error('invalid retry delay')
        # Negotiation happens here, before any claim or call; never from model output.
        check_capabilities(capabilities if capabilities is not None else getattr(adapter, 'capabilities', None))
        self.inbox, self.channel, self.adapter = inbox, channel, adapter
        self.options = dict(counters=tuple(counters), owner=owner, max_tokens=max_tokens, limit=batch_size,
                            lease_seconds=timeout + 30, context_policy=context_policy)
        self.retry_delay = retry_delay
        self.ledger_path = None if ledger_path is None else Path(ledger_path)
        self.tokenizer = tokenizer
        self._last_call: dict[str, str] = {}

    def _append(self, record: dict) -> bool:
        if self.ledger_path is None:
            return True
        try:
            line = json.dumps(record, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            with self.ledger_path.open('a', encoding='utf-8', newline='\n') as file:
                file.write(line + '\n')
        except (OSError, ValueError):
            return False
        return True

    def _record(self, event: str, call: dict, **fields) -> dict:
        """One ledger line in schema order; fields not yet known stay null."""
        record = {'event': event, 'schema': LEDGER_SCHEMA, 'call_id': None, 'run_id': None, 'batch_id': None,
                  'attempt': None, 'retry_of': None, 'channel_binding': None, 'adapter': None,
                  'model_requested': None, 'model_reported': None, 'started_at': None, 'ended_at': None,
                  'elapsed_ms': None, 'job_map': None, 'system_sha256': None, 'prompt_sha256': None,
                  'submitted_sha256': None, 'response_sha256': None, 'system_bytes': None,
                  'prompt_bytes': None, 'submitted_bytes': None, 'response_bytes': None,
                  'token_estimates': None,
                  'usage': dict.fromkeys(('source', 'scope', 'raw', *(key for key, _ in USAGE_MAP))),
                  'reported_cost': dict.fromkeys(('amount', 'currency', 'source', 'scope')),
                  'billed_cost': dict.fromkeys(('amount', 'currency', 'source')),
                  'exit_code': None, 'timed_out': None, 'outcome': None, 'error': None, 'validation': None}
        record.update(call, **fields)
        return record

    def _estimate(self, text: str | None):
        try:
            return None if text is None else self.options['counters'][0](text)
        except Exception:
            return None

    def run_once(self) -> dict:
        if self.min_batch > 1 and self.inbox.waiting(self.channel, min_batch=self.min_batch,
                                                     max_wait=self.max_wait):
            # Fewer calls with more jobs each; nothing is claimed and no receipt is used.
            return {'status': 'waiting', 'model_calls': 0}
        # A fresh receipt per attempt, made before planning so it is charged.
        receipt = self.inbox.new_receipt()
        claimed = self.inbox.claim_prepared(self.channel, receipt=receipt, **self.options)
        if claimed is None:
            return {'status': 'idle', 'model_calls': 0}
        delivery, packet = claimed
        ids = tuple(j.id for j in delivery.jobs)
        request = {'protocol': PROTOCOL, 'language': LANGUAGE, 'binding': delivery.binding, 'receipt': receipt,
                   'ids': list(ids), 'attempts': [j.attempt for j in delivery.jobs],
                   'system': packet.system, 'prompt': packet.text, 'prompt_tokens': list(packet.tokens)}
        call_id = uuid.uuid4().hex
        digests = [_digest(t) for t in (packet.system, packet.text, packet.system + '\n' + packet.text)]
        call = dict(call_id=call_id, batch_id=receipt, attempt=max(j.attempt for j in delivery.jobs),
                    retry_of=next((self._last_call[m] for m in ids if m in self._last_call), None),
                    channel_binding=delivery.binding,
                    adapter=getattr(self.adapter, '__name__', type(self.adapter).__name__),
                    job_map=[{'inbox_job_id': mid, 'expanded_atom_index': i} for mid, i in packet.job_map],
                    system_sha256=digests[0][0], prompt_sha256=digests[1][0], submitted_sha256=digests[2][0],
                    system_bytes=digests[0][1], prompt_bytes=digests[1][1], submitted_bytes=digests[2][1])
        started_at, start = _now(), time.monotonic()
        estimates = dict(tokenizer=self.tokenizer, system=self._estimate(packet.system),
                         prompt=self._estimate(packet.text), submitted=packet.tokens[0], response=None)
        ledger_ok = self._append(self._record('call_start', call, started_at=started_at,
                                              token_estimates=estimates))
        report = {'language': LANGUAGE, 'mode': packet.mode, 'prompt_tokens': list(packet.tokens),
                  'adapter_calls': 1, 'usage': {}, 'verification': 'unverified', 'call_id': call_id}
        phase, response, usage, failure, grouped = 'adapter', None, None, None, None
        try:
            response = self.adapter(request)
            phase = 'validation'
            if not isinstance(response, dict) or 'reply' not in response or set(response) - {'reply', 'usage'}:
                raise Error('adapter response must be {"reply":...,"usage":...}')
            # Usage is provider accounting; keep it even when the reply is invalid.
            usage = report['usage'] = validate_usage(response.get('usage', {}))
            grouped = regroup(response['reply'], packet.job_map)
            if not grouped.parsed.accepted:
                raise Error('reply has no accepted result line')
            # Per-job acceptance: a job with an unaccepted item retries alone, the others settle.
            outcomes = {mid: Outcome(*grouped.outcomes[mid]) for mid in ids}
            report['status'] = 'received'
        except Exception as exc:
            # Do not store arbitrary provider exception text: it may contain credentials.
            failure = exc
            code = ('adapter_timeout' if isinstance(exc, subprocess.TimeoutExpired) else exc.code
                    if isinstance(exc, AdapterError) else 'adapter_invalid_reply'
                    if phase == 'validation' else 'adapter_exception')
            reason = code + ' (' + type(exc).__name__ + ')'
            outcomes = {mid: Outcome('retry', reason) for mid in ids}
            report['status'] = 'adapter_error'
            report['error_type'] = type(exc).__name__
            report['error_code'] = code
        elapsed = time.monotonic() - start
        report['wall_seconds'] = round(elapsed, 6)
        end = self._call_end(call, packet, started_at, elapsed, estimates, response, usage, failure,
                             report.get('error_code'), outcomes, grouped)
        if not self._append(end) or not ledger_ok:
            report['ledger_error'] = 'write_failed'
        for mid, outcome in outcomes.items():
            if outcome.status == 'retry':
                self._last_call[mid] = call_id
            else:
                self._last_call.pop(mid, None)
        self.inbox.settle(delivery, outcomes, retry_delay=self.retry_delay, report=report)
        return dict(report, ids=list(ids), outcomes={mid: o.status for mid, o in outcomes.items()})

    def _call_end(self, call, packet, started_at, elapsed, estimates, response, usage, failure, code, outcomes,
                  grouped):
        try:
            text = json.dumps(response, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        except (TypeError, ValueError):
            text = None
        sha, size = _digest(text)
        parsed = grouped.parsed if grouped is not None else None
        if failure is None:
            unaccepted = any(o.status == 'retry' for o in outcomes.values())
            outcome = ('invalid_response' if unaccepted
                       else 'job_error' if any(o.status == 'failed' for o in outcomes.values()) else 'ok')
        elif isinstance(failure, subprocess.TimeoutExpired):
            outcome = 'timeout'
        elif code == 'adapter_start_failed':
            outcome = 'spawn_error'
        elif code in {'adapter_invalid_json', 'adapter_output_too_large', 'adapter_invalid_reply'}:
            outcome = 'invalid_response'
        else:
            outcome = 'process_error'
        validation = dict(expected_results=len(packet.job_map), received_results=None,
                          accepted_results=None, failed_results=None, violations=[])
        if parsed is not None:
            failed = sum(1 for status, _ in parsed.accepted.values() if status == 'failed')
            validation.update(received_results=parsed.received, accepted_results=len(parsed.accepted),
                              failed_results=failed, violations=list(parsed.violations))
        exit_code = None
        if isinstance(failure, AdapterError) and re.fullmatch(r'adapter_exit_-?[0-9]{1,10}', code):
            exit_code = int(code.rsplit('_', 1)[1])
        elif failure is None and isinstance(self.adapter, StdioAdapter):
            exit_code = 0
        fields = dict(started_at=started_at, ended_at=_now(), elapsed_ms=round(elapsed * 1000),
                      response_sha256=sha, response_bytes=size,
                      token_estimates=dict(estimates, response=self._estimate(text)),
                      exit_code=exit_code, timed_out=isinstance(failure, subprocess.TimeoutExpired),
                      outcome=outcome, validation=validation,
                      error=(code + ' (' + type(failure).__name__ + ')' if failure is not None
                             else RETRY_REASON if outcome == 'invalid_response' else None))
        if usage:
            fields['usage'] = dict({'source': 'adapter', 'scope': 'call', 'raw': usage, 'total_tokens': None},
                                   **{key: usage.get(raw) for key, raw in USAGE_MAP if raw})
        return self._record('call_end', call, **fields)


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
