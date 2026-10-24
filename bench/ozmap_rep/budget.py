"""A4.4 capacity formulas, A4.5 physical call allocations and reserves, A4.13 preparation ledger and caps.

Standard library only. Every charge is one physical call and stays on record whatever its outcome.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

from . import config


class BudgetExceeded(Exception):
    pass


class ReserveMisuse(BudgetExceeded):
    """Unused capacity cannot authorize new learning, repair or conditions (A4.5)."""


class CapExceeded(Exception):
    """A preparation or review call that would exceed an A4.13 cap (not written)."""


def capacity(producers, bootstrap, audits, M=config.MAX_BATCH) -> dict:
    """A4.4: pooled ceil((sum_p (N_p - b_p) + a) / M) and local sum_p ceil((N_p - b_p + a) / M)."""
    producers, bootstrap = list(producers), list(bootstrap)
    if len(producers) != len(bootstrap):
        raise ValueError('one bootstrap count per producer')
    rest = [n - b for n, b in zip(producers, bootstrap)]
    pooled = math.ceil((sum(rest) + audits) / M)
    local = sum(math.ceil((r + audits) / M) for r in rest)
    return {'pooled': pooled, 'local': local}


class Budget:
    """Allocation and cap enforcement over physical calls. `attempts` is an append-only tuple of every charge."""

    def __init__(self, allocations=None, caps=None, log=None):
        self.allocations = allocations or config.ALLOCATIONS
        self.caps = caps or config.EVAL_CAPS
        self.log = Path(log) if log else None
        self._attempts = []

    @property
    def attempts(self):
        return tuple(self._attempts)

    def _count(self, **match):
        return sum(1 for a in self._attempts if all(a.get(k) == v for k, v in match.items()))

    def charge(self, backend, workload, allocation, reason='nominal', outcome=None, **extra) -> dict:
        if backend not in self.caps:
            raise BudgetExceeded(f'no evaluation cap for backend {backend}')
        cap = self.caps[backend]
        if reason in config.RESERVE_FORBIDDEN:
            raise ReserveMisuse(f'{reason} is never authorized by unused capacity (A4.5)')
        if workload == 'telemetry':
            if allocation != 'telemetry':
                raise BudgetExceeded('telemetry charges use the telemetry allocation')
            if self._count(backend=backend, kind='telemetry') >= cap['telemetry']:
                raise BudgetExceeded(f'{backend} telemetry cap {cap["telemetry"]} reached')
            kind = 'telemetry'
        else:
            key = f'{backend}/{workload}'
            if key not in self.allocations or allocation not in self.allocations[key]:
                raise BudgetExceeded(f'no allocation {allocation} for {key}')
            if reason != 'nominal' and reason not in config.RESERVE_REASONS:
                raise BudgetExceeded(f'unknown charge reason {reason}')
            nominal = self.allocations[key][allocation]
            used = self._count(backend=backend, workload=workload, allocation=allocation, kind='nominal')
            if used < nominal:
                kind = 'nominal'
            elif reason == 'nominal':
                raise BudgetExceeded(f'{key} {allocation}: nominal allocation {nominal} used')
            else:
                reserve = self._count(backend=backend, workload=workload, allocation=allocation, kind='reserve')
                if reserve >= config.RESERVE_PER_ALLOCATION:
                    raise BudgetExceeded(f'{key} {allocation}: both reserve calls used')
                kind = 'reserve'
            if kind == 'nominal' and self._count(backend=backend, kind='nominal') >= cap['nominal']:
                raise BudgetExceeded(f'{backend} nominal cap {cap["nominal"]} reached')
            if kind == 'reserve' and self._count(backend=backend, kind='reserve') >= cap['reserve']:
                raise BudgetExceeded(f'{backend} reserve cap {cap["reserve"]} reached')
        if self.physical_total(backend) >= cap['total']:
            raise BudgetExceeded(f'{backend} evaluation cap {cap["total"]} reached')
        row = dict(extra, backend=backend, workload=workload, allocation=allocation, reason=reason, kind=kind,
                   outcome=outcome)
        self._attempts.append(row)
        if self.log is not None:
            with open(self.log, 'a', encoding='utf-8') as f:
                f.write(json.dumps(row, sort_keys=True) + '\n')
        return {'kind': kind}

    def physical_total(self, backend) -> int:
        return self._count(backend=backend)

    def analytic_calls(self, backend, workload, allocation) -> int:
        """Physical calls of one allocation, with the shared bootstrap charged fully to both cold_B and cold_C."""
        n = self._count(backend=backend, workload=workload, allocation=allocation)
        if allocation in ('cold_B', 'cold_C'):
            n += self._count(backend=backend, workload=workload, allocation='bootstrap')
        return n

    def usage(self) -> dict:
        out = {}
        for b in self.caps:
            out[b] = {k: self._count(backend=b, kind=k) for k in ('nominal', 'reserve', 'telemetry')}
            out[b]['total'] = self.physical_total(b)
        return out


class PrepLedger:
    """A4.13.2: one JSON line per preparation or review call (agent, role, category, timestamp, purpose, count).
    Counts are cumulative over the whole file; a call that would exceed its cap raises CapExceeded unwritten."""

    def __init__(self, path, caps=None):
        self.path = Path(path)
        self.caps = caps or config.PREP_CAPS

    def rows(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines() if line.strip()]

    def counts(self) -> dict:
        out = {}
        for r in self.rows():
            out[r['agent']] = out.get(r['agent'], 0) + int(r.get('count', 1))
        return out

    def would_exceed(self, agent, n=1) -> bool:
        if agent not in self.caps:
            raise ValueError(f'{agent} is not a preparation agent with an A4.13 cap')
        return self.counts().get(agent, 0) + n > self.caps[agent]

    def log(self, agent, role, category, purpose, timestamp=None, count=1) -> dict:
        if agent not in self.caps:
            raise ValueError(f'{agent} is not a preparation agent with an A4.13 cap')
        if type(count) is not int or count < 1:
            raise ValueError('count must be a positive integer')
        if self.would_exceed(agent, count):
            raise CapExceeded(f'{agent}: {self.counts().get(agent, 0)} + {count} exceeds the cap {self.caps[agent]}')
        row = {'agent': agent, 'role': role, 'category': category,
               'timestamp': timestamp or dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
               'purpose': purpose, 'count': count}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row) + '\n')
        return row
