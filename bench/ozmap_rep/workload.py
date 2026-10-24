"""The preregistered workloads (A4.8): Fable's tensile test operations for materials, the pilot BoolQ sample for BoolQ.

Standard library only, deterministic. Task counts and admission design are the pilot's: per wave 4 producers x 64 jobs
(16 per operation per producer), the bootstrap takes the first 16 jobs of each producer of the cold wave, and each
operation has 64 admission cases, 48 representative and 16 challenge. Job and admission texts come only from
bench/ozmap_rep/ops/data.py (independent streams, specimen prefixes J and A) and gold only from its oracle.
"""
from __future__ import annotations

import functools
import hashlib
import importlib.util
import random
import sys
from pathlib import Path

from . import config
from .ops import data as ops_data
from .ops import oracle as ops_oracle

# The challenge partition: the first 16 admission cases of an operation (in stream order) whose edge category is not a
# plain record. The rest are representative. Fixed before any learner call; the plans come from ops/data.py.
PLAIN_CATEGORIES = ('plain', 'room', 'cold', 'hot')


def _ozmap(name):
    """bench/ozmap/<name>.py under the module key the pilot uses (ozmap_<name>), loaded once and never modified."""
    key = 'ozmap_' + name
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, config.REPO / 'bench' / 'ozmap' / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


def resolve(text: str) -> str:
    """The D2 input policy: exactly one terminal CRLF, else one LF, removed."""
    return text[:-2] if text.endswith('\r\n') else text[:-1] if text.endswith('\n') else text


def sub_seed(seed, *parts):
    return ops_data.sub_seed(seed, *parts)


@functools.lru_cache(maxsize=4)
def _materials(seed):
    n_wave = len(config.PRODUCERS) * config.PER_PRODUCER
    per_op = config.PER_PRODUCER // len(config.OPERATIONS)
    rows = ops_data.jobs(seed, 2 * n_wave)
    by_op = {op: [r for r in rows if r['op'] == op] for op in config.OPERATIONS}
    waves = {}
    for w, wave in enumerate(('cold', 'warm')):
        jobs = []
        for k, producer in enumerate(config.PRODUCERS):
            mine = []
            for op in config.OPERATIONS:
                start = w * len(config.PRODUCERS) * per_op + k * per_op
                for i, row in enumerate(by_op[op][start:start + per_op]):
                    mine.append({'id': f'{wave}-{producer}-{op}-{i:02d}', 'op': op, 'text': row['text'],
                                 'producer': producer})
            random.Random(sub_seed(seed, 'order', wave, producer)).shuffle(mine)
            jobs += mine
        waves[wave] = jobs
    boot = []
    for producer in config.PRODUCERS:
        boot += [j['id'] for j in waves['cold'] if j['producer'] == producer][:config.BOOTSTRAP_PER_PRODUCER]
    stream = ops_data._texts(seed, 'admission', 'A', 4 * 64)
    admission = {}
    for op in config.OPERATIONS:
        rows = [(cat, text) for o, cat, text in stream if o == op]
        challenge = set()
        for i, (cat, _) in enumerate(rows):
            if cat not in PLAIN_CATEGORIES and len(challenge) < 16:
                challenge.add(i)
        admission[op] = [{'text': text, 'op': op, 'gold': ops_oracle.gold(op, text),
                          'kind': 'challenge' if i in challenge else 'representative', 'category': cat,
                          'id': f'adm-{op}-{i:02d}'}
                         for i, (cat, text) in enumerate(rows)]
    return {'cold': waves['cold'], 'warm': waves['warm'], 'admission': admission, 'bootstrap_ids': boot}


def materials(seed=config.SEED) -> dict:
    out = _materials(seed)
    return {'cold': [dict(j) for j in out['cold']], 'warm': [dict(j) for j in out['warm']],
            'admission': {op: [dict(c) for c in cases] for op, cases in out['admission'].items()},
            'bootstrap_ids': list(out['bootstrap_ids'])}


@functools.lru_cache(maxsize=1)
def _boolq():
    data = _ozmap('data')
    q = data.boolq()
    if not q.get('available'):
        return {'available': False, 'reason': q.get('reason')}
    jobs, gold = [], {}
    for producer in config.PRODUCERS:
        for j in q['waves']['cold'][producer]:
            jobs.append({'id': j['dataset_id'], 'op': config.BOOLQ_OP, 'text': j['text'], 'producer': producer})
            gold[j['dataset_id']] = 'yes' if q['labels'][j['dataset_id']] else 'no'
    boot = []
    for producer in config.PRODUCERS:
        boot += [j['id'] for j in jobs if j['producer'] == producer][:config.BOOTSTRAP_PER_PRODUCER]
    return {'available': True, 'cold': jobs, 'bootstrap_ids': boot, 'gold': gold, 'sha256': q.get('sha256'),
            'goal': data.BOOLQ_GOAL, 'op_text': data.BOOLQ_OP_TEXT}


def boolq() -> dict:
    out = _boolq()
    return {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in out.items()}


def gold(job_or_case) -> str:
    op = job_or_case['op']
    if op == config.BOOLQ_OP:
        return _boolq()['gold'][job_or_case['id']]
    return ops_oracle.gold(op, job_or_case['text'])


def jobs_for(workload, wave):
    if workload == 'materials':
        return _materials(config.SEED)[wave]
    if wave != 'cold':
        raise ValueError('BoolQ has only a cold wave')
    q = _boolq()
    if not q['available']:
        raise RuntimeError(q['reason'])
    return q['cold']


def bootstrap_ids(workload):
    return list(_materials(config.SEED)['bootstrap_ids'] if workload == 'materials' else _boolq()['bootstrap_ids'])


def fake_answer_table() -> dict:
    """{sha256(resolved text): gold} for every evaluation job of both workloads (the fake model's answers)."""
    table = {}
    for wave in ('cold', 'warm'):
        for j in _materials(config.SEED)[wave]:
            table[hashlib.sha256(resolve(j['text']).encode('utf-8')).hexdigest()] = gold(j)
    q = _boolq()
    if q['available']:
        for j in q['cold']:
            table[hashlib.sha256(resolve(j['text']).encode('utf-8')).hexdigest()] = gold(j)
    return table
