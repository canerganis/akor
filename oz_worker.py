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
import sys
import time
import uuid

from typing import Callable

from oz import Channel, Error
from oz_accept import HEADER, REGISTRY, Inputs, decide, job_inputs, pin, run_checks
from oz_batch import WIRE, valid_receipt
from oz_reply import BINDING, LANGUAGE, PROTOCOL, RETRY_REASON, check_capabilities, loads, regroup, validate_usage
from oz_runner import done_path, process_alive, process_identity, publish, read_capture, request_path
from oz_runtime import Fenced, Inbox, Outcome

RUNNER = Path(__file__).resolve().with_name('oz_runner.py')

LEDGER_SCHEMA = 'akor.call/1'
USAGE_MAP = (('input_tokens', 'input_tokens'), ('output_tokens', 'output_tokens'),
             ('cache_read_tokens', 'cached_input_tokens'), ('cache_write_tokens', 'cache_creation_input_tokens'),
             ('reasoning_tokens', 'reasoning_output_tokens'), ('total_tokens', None))


class AdapterError(Error):
    def __init__(self, code: str):
        allowed = {'adapter_start_failed', 'adapter_output_too_large', 'adapter_invalid_json',
                   'adapter_capture_missing'}
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
    # Durable path (clause 5): run the command under oz_runner, which publishes <receipt>.done in this directory.
    # None keeps the compatibility pipe path.
    capture_dir: Path | None = None

    def __post_init__(self):
        if isinstance(self.argv, str):
            raise Error('adapter argv must be a sequence, not a shell command string')
        object.__setattr__(self, 'argv', tuple(self.argv))
        if (not self.argv or any(not isinstance(s, str) or not s or '\x00' in s for s in self.argv)
                or type(self.timeout) not in {int, float} or not 0 < self.timeout <= 3600
                or type(self.max_output_bytes) is not int or not 1 <= self.max_output_bytes <= 8388608):
            raise Error('invalid adapter command or limits')

    def __call__(self, request: dict, on_launch: Callable[[dict | None], None] | None = None) -> dict:
        """Run the adapter once. on_launch, when given, receives the started process identity (PID and creation
        time) before the adapter's output is awaited."""
        payload = json.dumps(request, ensure_ascii=False).encode('utf-8')
        if self.capture_dir is not None:
            return self._durable(request, payload, on_launch)
        try:
            proc = subprocess.Popen(self.argv, cwd=self.cwd, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1'),
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                    start_new_session=os.name != 'nt')
        except OSError as exc:
            raise AdapterError('adapter_start_failed') from None
        try:
            if on_launch is not None:
                on_launch(process_identity(proc.pid))
            stdout, stderr = proc.communicate(payload, timeout=self.timeout)
        except BaseException:
            _terminate(proc)
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

    def _durable(self, request: dict, payload: bytes, on_launch) -> dict:
        """The runner path: the request goes to <receipt>.request.json, oz_runner runs the command and publishes
        <receipt>.done; only that published record is read back. A runner that ends without publishing raises
        adapter_capture_missing: the adapter may have run, so the dispatch is uncertain, not failed. A record marked
        start_failed (the executable could not be started) raises adapter_start_failed: not launched. An interrupt
        of this coordinator (KeyboardInterrupt, timeout) terminates the runner tree, so it publishes nothing and the
        dispatch is uncertain; only a hard coordinator death leaves the runner to publish."""
        receipt = request.get('receipt')
        if not valid_receipt(receipt):
            raise Error('the durable adapter path needs the request receipt')
        directory = Path(self.capture_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = request_path(directory, receipt)
        if path.exists() and path.read_bytes() != payload:
            raise Error('receipt already used for a different request')
        if done_path(directory, receipt).exists():
            raise Error('receipt already has a completed capture; recover it instead of calling again')
        publish(path, payload)
        try:
            proc = subprocess.Popen((sys.executable, str(RUNNER), str(directory), receipt, '--', *self.argv),
                                    cwd=self.cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1'),
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                    start_new_session=os.name != 'nt')
        except OSError:
            raise AdapterError('adapter_start_failed') from None
        try:
            if on_launch is not None:
                on_launch(process_identity(proc.pid))
            proc.wait(timeout=self.timeout)
        except BaseException:
            _terminate(proc)
            raise
        capture = read_capture(directory, receipt, hashlib.sha256(payload).hexdigest())
        if capture is None:
            raise AdapterError('adapter_capture_missing')
        return _capture_response(capture, self.max_output_bytes, capture.get('stderr_bytes', 0))


def _terminate(proc) -> None:
    """Terminate only the process group/tree started by this adapter."""
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


def _capture_response(capture: dict, max_output_bytes: int = 1048576, stderr_bytes: int = 0) -> dict:
    """The adapter response of a completed capture, with the same errors as the pipe path."""
    if capture.get('start_failed'):
        raise AdapterError('adapter_start_failed')
    if capture['exit_code']:
        raise AdapterError(f'adapter_exit_{capture["exit_code"]}')
    if len(capture['stdout']) > max_output_bytes or (type(stderr_bytes) is int and stderr_bytes > max_output_bytes):
        raise AdapterError('adapter_output_too_large')
    try:
        return loads(capture['stdout'].decode('utf-8'))
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

    A batch whose jobs need no model slot (read and test are host operations) is completed
    locally: status host_completed, adapter_calls 0, no ledger call record.

    Callable adapters must return before timeout. StdioAdapter enforces its
    timeout by terminating its child process; an arbitrary Python callable
    cannot be safely forcibly interrupted by this worker.

    With ledger_path every call appends call_start and call_end lines
    (schema akor.call/1) to an append-only JSONL file; unknown values are null.

    A packet that holds an oz1g-selective-v1 job (pinned at post) takes the journaled path: launch intent with the
    lease, launch with process identity, capture before interpretation, per-job checks (registry) and one conditional
    settlement under this worker's coordinator epoch (epoch, default the current one). route names the execution
    route (model, effort, cli_version) that enters each job's computation key. Packets of oz1g-header jobs only take
    the shipped path unchanged. recover() does the coordinator's work without model calls.
    """

    def __init__(self, inbox: Inbox, channel: Channel, adapter: Callable[[dict], dict], *,
                 counters, capabilities: dict | None = None, owner: str = 'worker', max_tokens: int = 2048,
                 batch_size: int = 64, timeout: float = 120, retry_delay: float = 2,
                 context_policy: str = 'needed', min_batch: int = 1, max_wait: float = 0,
                 ledger_path: str | Path | None = None, tokenizer: str | None = None,
                 epoch: int | None = None, route: dict | None = None, registry: dict | None = None):
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
        if route is not None and (not isinstance(route, dict) or set(route) - {'model', 'effort', 'cli_version'}
                                  or any(v is not None and not isinstance(v, str) for v in route.values())):
            raise Error('route takes model, effort and cli_version strings')
        if epoch is not None and type(epoch) is not int:
            raise Error('epoch must be an integer')
        self.timeout = timeout
        self.route = dict(route or {})
        self.epoch = inbox.epoch() if epoch is None else epoch
        self.registry = REGISTRY if registry is None else registry
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
        call_id = uuid.uuid4().hex
        # The dispatch options only journal a packet that holds an oz1g-selective-v1 job.
        try:
            claimed = self.inbox.claim_prepared(self.channel, receipt=receipt, dispatch=dict(
                epoch=self.epoch, route=self._route(), call_id=call_id, timeout=self.timeout,
                capture_dir=getattr(self.adapter, 'capture_dir', None)), **self.options)
        except Fenced:
            # An obsolete coordinator epoch: nothing was leased or charged and no model was called.
            return {'status': 'fenced', 'model_calls': 0, 'settlement': 'fenced', 'outcomes': {}}
        if claimed is None:
            return {'status': 'idle', 'model_calls': 0}
        delivery, packet = claimed
        ids = tuple(j.id for j in delivery.jobs)
        if not packet.job_map:
            return self._host_only(delivery, packet, ids)
        durable = self.inbox.dispatch(receipt) is not None
        request = {'protocol': PROTOCOL, 'language': LANGUAGE, 'binding': delivery.binding, 'receipt': receipt,
                   'ids': list(ids), 'attempts': [j.attempt for j in delivery.jobs],
                   'system': packet.system, 'prompt': packet.text, 'prompt_tokens': list(packet.tokens)}
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
        report = {'language': LANGUAGE, 'wire': WIRE, 'mode': packet.mode,
                  'prompt_tokens': list(packet.tokens), 'adapter_calls': 1, 'usage': {},
                  'verification': 'unverified', 'call_id': call_id}
        phase, response, usage, failure, grouped = 'adapter', None, None, None, None
        if durable:
            report['dispatch'] = 'journaled'
            self.inbox.dispatch_prepared(receipt, hashlib.sha256(
                json.dumps(request, ensure_ascii=False).encode('utf-8')).hexdigest())
        try:
            if durable:
                response = self._invoke(request, receipt)
                # Capture before interpretation (clause 5 step 3).
                self.inbox.dispatch_captured(receipt, response=response)
            else:
                response = self.adapter(request)
            phase = 'validation'
            if not isinstance(response, dict) or 'reply' not in response or set(response) - {'reply', 'usage'}:
                raise Error('adapter response must be {"reply":...,"usage":...}')
            # Usage is provider accounting; keep it even when the reply is invalid.
            usage = report['usage'] = validate_usage(response.get('usage', {}))
            grouped = regroup(response['reply'], packet.job_map, packet.host_slots)
            if grouped.parsed.rejection:
                # Atomic acceptance: one bad line rejects the whole reply and every job retries. Valid job
                # failures are not rejections: they commit with the successes.
                raise Error('reply rejected: ' + grouped.parsed.rejection)
            outcomes = {mid: Outcome(*grouped.outcomes[mid], grouped.values.get(mid)) for mid in ids}
            report['status'] = 'received'
        except Exception as exc:
            # Do not store arbitrary provider exception text: it may contain credentials.
            failure = exc
            code = ('adapter_timeout' if isinstance(exc, subprocess.TimeoutExpired) else exc.code
                    if isinstance(exc, AdapterError) else 'adapter_invalid_reply'
                    if phase == 'validation' else 'adapter_exception')
            reason = code + ' (' + type(exc).__name__ + ')'
            if durable and phase == 'adapter':
                if code == 'adapter_capture_missing':
                    # The runner ended without publishing: the adapter may have run; its usage is unknown.
                    self.inbox.dispatch_uncertain(receipt)
                else:
                    self.inbox.dispatch_captured(receipt, error=code, executed=code != 'adapter_start_failed')
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
        if durable:
            dispatch = self.inbox.dispatch(receipt)
            decisions = self._decisions(dispatch, grouped if failure is None else None,
                                        None if failure is None else outcomes[ids[0]].text)
            settled = self.inbox.settle_dispatch(receipt, decisions, epoch=self.epoch, retry_delay=self.retry_delay,
                                                 report=report)
            states = {mid: STATUS.get(settled['jobs'].get(mid), 'late') for mid in ids}
            if settled['status'] != 'settled':
                # Fenced by a newer coordinator epoch: the capture stays for that coordinator to adopt.
                states = dict.fromkeys(ids, settled['status'])
            for mid, status in states.items():
                if status == 'retry':
                    self._last_call[mid] = call_id
                else:
                    self._last_call.pop(mid, None)
            return dict(report, ids=list(ids), outcomes=states, settlement=settled['status'])
        for mid, outcome in outcomes.items():
            if outcome.status == 'retry':
                self._last_call[mid] = call_id
            else:
                self._last_call.pop(mid, None)
        self.inbox.settle(delivery, outcomes, retry_delay=self.retry_delay, report=report)
        return dict(report, ids=list(ids), outcomes={mid: o.status for mid, o in outcomes.items()})

    def _route(self) -> dict:
        """The execution route of this worker (clause 1): adapter identity, model, effort, CLI version and wire. A
        field the caller did not give stays null (unknown), never guessed."""
        return {'adapter': getattr(self.adapter, '__name__', type(self.adapter).__name__),
                'model': self.route.get('model'), 'effort': self.route.get('effort'),
                'cli_version': self.route.get('cli_version'), 'wire': WIRE}

    def _invoke(self, request: dict, receipt: str) -> dict:
        if isinstance(self.adapter, StdioAdapter):
            return self.adapter(request, on_launch=lambda identity: self.inbox.dispatch_launched(receipt, identity))
        return self.adapter(request)

    def _decisions(self, dispatch: dict, grouped, reason: str | None) -> dict:
        """Per-member decisions for settle_dispatch. grouped None (no reply, or a reply the parser rejected) gives
        every member a retry and no candidate. In a wire-valid reply a header-pinned job keeps its shipped outcome
        and a selective job's success becomes a candidate judged by its pinned checks against its own inputs."""
        members = [m['id'] for m in dispatch['members']]
        contracts = self.inbox.contracts(members)
        inputs = job_inputs(dispatch['packet'], dispatch['job_map'])
        out, verdicts = {}, {}
        for mid in members:
            profile, checks = contracts[mid]
            if grouped is None:
                out[mid] = ({'kind': 'header', 'status': 'retry', 'text': reason} if profile == HEADER
                            else {'kind': 'retry', 'reason': reason})
                continue
            status, text = grouped.outcomes[mid]
            value = grouped.values.get(mid)
            if profile == HEADER or mid not in inputs:
                out[mid] = {'kind': 'header', 'status': status, 'text': text, 'value': value}
            elif status == 'retry':
                out[mid] = {'kind': 'retry', 'reason': text}
            elif status == 'failed':
                out[mid] = {'kind': 'failure', 'text': text}
            else:
                verdicts[mid] = run_checks(value, inputs[mid], checks, self.registry)
                out[mid] = {'text': text, 'value': value, 'verdicts': verdicts[mid], 'inputs': inputs[mid]}
        decided, reply = decide(verdicts)
        for mid, (kind, why) in decided.items():
            out[mid].update(kind=kind, reason=why, suspect=reply['suspect'])
        return out

    def recover(self) -> dict:
        """Coordinator work for this channel's journaled dispatches, without any model call (clauses 2, 3 and 5).

        1. A dispatch with no completed capture reuses a runner-published capture when one exists. Otherwise, once
           its lease has expired and its recorded process is gone, it becomes uncertain: the attempt stays charged,
           the reservation stays held and its usage stays unknown; its jobs retry within their allowance.
        2. A captured dispatch that was never settled (a crash after capture, a late reply, a fenced worker) is
           interpreted from the stored reply and settled under this worker's epoch, so late successes are adopted
           only under the clause 3 rules.
        3. Candidates awaiting checks get their inconclusive checks run again (recheck)."""
        summary = {'captured': [], 'uncertain': [], 'settled': [], 'rechecked': []}
        for d in self.inbox.dispatches(binding=self.channel.binding, unsettled=True):
            receipt = d['receipt']
            if d['state'] in ('intent', 'launched', 'uncertain'):
                capture = (read_capture(d['capture_dir'], receipt, d['request_sha256'])
                           if d['capture_dir'] else None)
                if capture is not None:
                    try:
                        self.inbox.dispatch_captured(receipt, response=_capture_response(capture))
                    except AdapterError as exc:
                        self.inbox.dispatch_captured(receipt, error=exc.code, executed=exc.code != 'adapter_start_failed')
                    summary['captured'].append(receipt)
                    d = self.inbox.dispatch(receipt)
                else:
                    if (d['state'] != 'uncertain' and not self.inbox.in_flight(receipt)
                            and process_alive(d['process']) is not True):
                        self.inbox.dispatch_uncertain(receipt)
                        summary['uncertain'].append(receipt)
                    continue
            grouped, reason = _interpret(d) if d['state'] == 'captured' else (None, (d['error'] or 'adapter_failure')
                                                                                 + ' (recovered)')
            result = self.inbox.settle_dispatch(
                receipt, self._decisions(d, grouped, reason), epoch=self.epoch, retry_delay=self.retry_delay,
                report={'status': 'recovered', 'receipt': receipt, 'dispatch_state': d['state'],
                        'adapter_calls': 0, 'model_calls': 0})
            if result['status'] == 'settled':
                summary['settled'].append(receipt)
        summary['rechecked'] = self.recheck()
        return summary

    def recheck(self) -> list:
        """Run the inconclusive checks of candidates awaiting checks again and decide them together with the other
        candidates of their reply (a reply found suspect quarantines candidates without job-bound evidence). A
        candidate whose verifier is still unavailable keeps waiting; no model attempt is spent."""
        resolved = []
        awaiting = self.inbox.candidates(status='awaiting')
        for receipt in dict.fromkeys(c['receipt'] for c in awaiting):
            d = self.inbox.dispatch(receipt)
            if d is None or d['binding'] != self.channel.binding:
                continue
            verdicts, decisions = {}, {}
            for c in self.inbox.candidates(receipt=receipt):
                if c['status'] == 'awaiting':
                    inputs = Inputs(tuple(c['inputs']))
                    found = run_checks(c['value'], inputs, c['checks'], self.registry, previous=c['verdicts'])
                    decisions[c['job']] = {'seq': c['seq'], 'text': c['stored'], 'value': c['value'],
                                           'verdicts': found, 'inputs': inputs, 'before': c['verdicts']}
                    verdicts[c['job']] = found
                else:
                    verdicts[c['job']] = c['verdicts']
            decided, reply = decide(verdicts)
            changed = {}
            for mid, decision in decisions.items():
                kind, why = decided[mid]
                if kind == 'await' and decision.pop('before') == decision['verdicts']:
                    continue
                decision.pop('before', None)
                changed[mid] = dict(decision, kind=kind, reason=why, suspect=reply['suspect'])
            if changed:
                result = self.inbox.settle_dispatch(receipt, changed, epoch=self.epoch, retry_delay=self.retry_delay,
                                                    recheck=True)
                resolved.extend({'job': mid, 'receipt': receipt, 'state': state}
                                for mid, state in result['jobs'].items())
        return resolved

    def release(self, seq: int, checks=()) -> dict:
        """Explicit host acceptance association for a quarantined or awaiting candidate (clause 2): its pinned checks
        plus the given registered checks run on that same candidate, and it is accepted only when all of them pass,
        one of them is job-bound, and its job is still live and unresolved. No model call."""
        found = [c for c in self.inbox.candidates() if c['seq'] == seq]
        if not found or found[0]['status'] not in ('quarantined', 'awaiting'):
            raise Error('only a quarantined or awaiting candidate can be released')
        c = found[0]
        verdicts = run_checks(c['value'], Inputs(tuple(c['inputs'])),
                              tuple(c['checks']) + pin(checks, self.registry), self.registry)
        if any(v['verdict'] != 'pass' for v in verdicts) or not any(v['job_bound'] for v in verdicts):
            return {'status': 'not_released', 'verdicts': verdicts}
        result = self.inbox.settle_dispatch(c['receipt'], {c['job']: {
            'kind': 'accept', 'seq': seq, 'text': c['stored'], 'value': c['value'], 'verdicts': verdicts,
            'reason': 'released by host checks'}}, epoch=self.epoch, recheck=True)
        state = result['jobs'].get(c['job'])
        return {'status': 'released' if state == 'done' else 'not_released', 'state': state, 'verdicts': verdicts}

    def _host_only(self, delivery, packet, ids) -> dict:
        """Every slot is filled by the host (read, test): no adapter call, no ledger record."""
        grouped = regroup('', (), packet.host_slots)
        # A host result that cannot be stored will not improve on a retry: settle it as failed.
        outcomes = {mid: Outcome('failed', 'host_result_not_storable') if grouped.outcomes[mid][0] == 'retry'
                    else Outcome(*grouped.outcomes[mid], grouped.values.get(mid)) for mid in ids}
        report = {'language': LANGUAGE, 'mode': packet.mode, 'prompt_tokens': list(packet.tokens),
                  'adapter_calls': 0, 'model_calls': 0, 'usage': {}, 'verification': 'unverified',
                  'call_id': None, 'status': 'host_completed'}
        self.inbox.settle(delivery, outcomes, report=report)
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
                          accepted_results=None, failed_results=None, violations=[],
                          binding=BINDING, semantic_verified=False)
        if parsed is not None:
            validation.update(received_results=parsed.received, accepted_results=len(parsed.accepted),
                              failed_results=len(parsed.failed), violations=list(parsed.violations))
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


STATUS = {'done': 'ok', 'pending': 'retry', 'failed': 'failed', 'checking': 'checking',
          'quarantined': 'quarantined', 'stale': 'late', 'ignored': 'late'}


def _interpret(dispatch: dict):
    """(Regrouped, None) for a stored wire-valid reply, else (None, retry reason). Same rules as run_once."""
    response = dispatch['response']
    try:
        if not isinstance(response, dict) or 'reply' not in response or set(response) - {'reply', 'usage'}:
            raise Error('adapter response must be {"reply":...,"usage":...}')
        validate_usage(response.get('usage', {}))
        grouped = regroup(response['reply'], dispatch['job_map'], dispatch['host_slots'])
    except Exception as exc:
        return None, 'adapter_invalid_reply (' + type(exc).__name__ + ')'
    if grouped.parsed.rejection:
        return None, RETRY_REASON
    return grouped, None


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
