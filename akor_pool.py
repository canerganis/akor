"""Cross-producer pooling runtime (Claude and Astra decision, docs/design/direction-2026-10-26/astra-pool-2.md).

Producers submit ready jobs; the pool sends them to the model in as few calls as the latency budget allows:
FIFO, at most max_jobs per call, and a call leaves when it is full or when the oldest waiting job has waited max_wait
seconds (immediately when a job's deadline does not allow waiting). A call in flight never holds back new jobs: each
batch is dispatched on its own thread. Only jobs with the same key (model, effort, instruction, verifier, data
boundary) are pooled together.

The transport is the caller's send(batch) -> {id: value}; it must return exactly the batch's IDs with valid values or
raise/return {} for an unusable reply (no silent repair). An unusable reply is retried once with the same batch. An
optional verify(id, value) -> bool runs before delivery; a schema-valid answer is not reported as a correct one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from concurrent.futures import Future


@dataclass
class Job:
    id: str
    payload: object
    key: object = None
    deadline: float | None = None
    submitted: float = field(default_factory=time.monotonic)
    future: Future = field(default_factory=Future)


class Pool:
    def __init__(self, send, *, max_jobs: int = 32, max_wait: float = 0.5, retries: int = 1, verify=None,
                 clock=time.monotonic):
        self.send, self.max_jobs, self.max_wait, self.retries, self.verify = send, max_jobs, max_wait, retries, verify
        self.clock = clock
        self.queue: list[Job] = []
        self.cv = threading.Condition()
        self.closed = False
        self.inflight: list[threading.Thread] = []
        self.calls: list[dict] = []  # one record per dispatched batch, for accounting
        self.loop = threading.Thread(target=self._run, daemon=True)
        self.loop.start()

    def submit(self, jid: str, payload, *, key=None, deadline: float | None = None) -> Future:
        job = Job(jid, payload, key, deadline, self.clock())
        with self.cv:
            if self.closed:
                raise RuntimeError('pool is closed')
            if any(j.id == jid for j in self.queue):
                raise ValueError(f'duplicate job id {jid}')
            self.queue.append(job)
            self.cv.notify()
        return job.future

    def close(self):
        """Accept no new jobs; waiting jobs still leave by the normal rule (full, max_wait or deadline), then wait for
        every call in flight. Closing never shortens a wait."""
        with self.cv:
            self.closed = True
            self.cv.notify()
        self.loop.join()
        for t in list(self.inflight):
            t.join()

    def _due(self, now: float):
        """The batch to send now (oldest key first) and the seconds until the next decision."""
        if not self.queue:
            return None, None
        head = self.queue[0]
        group = [j for j in self.queue if j.key == head.key][:self.max_jobs]
        urgent = any(j.deadline is not None and j.deadline - now <= self.max_wait for j in group)
        waited = now - head.submitted
        if len(group) >= self.max_jobs or waited >= self.max_wait or urgent:
            return group, 0.0
        return None, self.max_wait - waited

    def _run(self):
        while True:
            with self.cv:
                while True:
                    batch, wait = self._due(self.clock())
                    if batch or (self.closed and not self.queue):
                        break
                    self.cv.wait(timeout=wait)
                if not batch:
                    return
                ids = {id(j) for j in batch}
                self.queue = [j for j in self.queue if id(j) not in ids]
            t = threading.Thread(target=self._dispatch, args=(batch,), daemon=True)
            self.inflight.append(t)
            t.start()

    def _dispatch(self, batch: list[Job]):
        ids = [j.id for j in batch]
        result = {}
        for attempt in range(1 + self.retries):
            record = {'ids': ids, 'attempt': attempt, 'queued_seconds': round(self.clock() - batch[0].submitted, 3)}
            self.calls.append(record)
            try:
                result = self.send([(j.id, j.payload) for j in batch]) or {}
            except Exception as exc:  # an unusable call: recorded, retried once, never repaired
                record['error'] = f'{type(exc).__name__}: {exc}'[:200]
                result = {}
            if set(result) == set(ids):
                break
            record['rejected'] = True
            result = {}
        for j in batch:
            if j.id not in result:
                j.future.set_exception(RuntimeError(f'job {j.id}: no usable reply after {1 + self.retries} calls'))
            elif self.verify is not None and not self.verify(j.id, result[j.id]):
                j.future.set_exception(RuntimeError(f'job {j.id}: verifier refused the answer'))
            else:
                j.future.set_result(result[j.id])
