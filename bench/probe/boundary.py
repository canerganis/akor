"""Boundary probe (docs/design/boundary-probe-2026-10-23/): which of A (the frozen stale classify packet), B (explicit
inequality wording) and C (B plus host-checked intervals as a second ref) removes the inclusive-boundary classification
errors seen in step 4, and at what token cost.

Commands (repo root):
    boundary.py freeze                      print the digest of everything frozen (zero tokens)
    boundary.py dry                         zero-token run on fixture replies (no process is ever started)
    boundary.py run --expect <digest>       the 18 counted calls through `claude -p`, resumable, stops at the caps
    boundary.py report                      tables and the decision from the retained evidence (zero tokens)

Standard library only. Scoring is independent of executor code: a strict OZ/1g reply parser written here and the
frozen expected labels. The only product import is oz_batch.SYSTEM (text H), and only to prove it is byte-identical
to the frozen hash. Calls follow examples/claude_cli_adapter.py exactly (same argv, system text via --system-prompt,
packet on stdin, no tools); unlike the adapter, the raw stdout, stderr and exit status of every call are kept.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FROZEN_DIR = ROOT / 'bench' / 'step4' / 'inspection-handoff-20-v1'
DESIGN = ROOT / 'docs' / 'design' / 'boundary-probe-2026-10-23'
ADAPTER = ROOT / 'examples' / 'claude_cli_adapter.py'
DEFAULT_OUT = HERE / 'boundary-evidence'
DEFAULT_DRY = ROOT / '.oz-runtime' / 'boundary-dry'

PLAN_ID = 'boundary-probe-2026-10-23'
MODEL = 'claude-sonnet-5-5'
CLI_VERSION = '2.1.306'
SYSTEM_SHA = 'd941a86d530ab0fe1d90dc1fb9d957bd95da1bfa8d150d17e320debcef50ea06'
CONTROL_SHA = '48ecc5b04ab8c6efdafdb315217a2c1729b1c2c904e52c71648b7abb0f83b0f9'
RECORD_SHAS = {'A': 'f8eeb7b4cbc3747f3593a530070f1d06f12ee6dff64237035cb123a4da54b170',
               'B': 'b5e2dcad0a904f8c6df5f446e6ebf6d29f1fd0e4b89797d7fd89b08da3d66911',
               'C': '9667c65ca36d12d82b71a299c11406f799b3d3d3f29d64080a6e220cd6b2d2f5',
               'D': 'f70e35ba2e6138925afb243c8d78f4f880d25ae11ede1cbd242deffab64277c0'}
SOURCE_FILES = {'A': 'sources/A.rev2.txt', 'B': 'sources/B.txt', 'C': 'sources/C.txt', 'D': 'sources/D.txt'}
STALE_LEDGERS = ('bench/step4/live1/calls-live1-stale-classify-bee726232b6b.jsonl',
                 'bench/step4/live2/calls-live2-stale-classify-bee726232b6b.jsonl')

ARMS = ('A', 'B', 'C')
BLOCKS = ('ABC', 'BCA', 'CAB', 'ACB', 'CBA', 'BAC')
IDS = ('classify_A', 'classify_B', 'classify_C', 'classify_D')
EXPECTED = {'classify_A': 'outside', 'classify_B': 'outside', 'classify_C': 'inside', 'classify_D': 'unknown'}
BOUNDARY = ('classify_C',)  # the only inclusive-edge member: [12.50, 12.52] against the limit 12.52
LOWER, UPPER = Decimal('12.48'), Decimal('12.52')

OP_B = ('If uncertainty is unknown, return unknown. Otherwise compute lower = length - uncertainty and upper = length '
        '+ uncertainty from the record. Return inside if lower >= 12.48 mm AND upper <= 12.52 mm; outside otherwise. '
        'Equality at either limit is inside.')
OP_C = ('The first ref is the measurement record. The second ref is its host-checked interval: [lower,upper], or '
        'unknown. If the interval is unknown, return unknown. Otherwise use its endpoints directly. Return inside if '
        'lower >= 12.48 mm AND upper <= 12.52 mm; outside otherwise. Equality at either limit is inside.')
C_INTERVALS = (['12.53 mm', '12.57 mm'], ['12.44 mm', '12.50 mm'], ['12.50 mm', '12.52 mm'], 'unknown')

CAPS = {'max_tokens': 60000, 'max_launches': 18, 'reserve_tokens': 5000, 'call_seconds': 300,
        'overall_seconds': 7200}
FORBIDDEN_ENV = ('ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL',
                 'ANTHROPIC_DEFAULT_HAIKU_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL',
                 'CLAUDE_CODE_EFFORT_LEVEL', 'CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING', 'MAX_THINKING_TOKENS',
                 'CLAUDE_CODE_MAX_OUTPUT_TOKENS', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_USE_BEDROCK',
                 'CLAUDE_CODE_USE_VERTEX')
USAGE_KEYS = ('inputTokens', 'cacheReadInputTokens', 'cacheCreationInputTokens', 'outputTokens')
ERROR_CODES = ('missing_data', 'invalid_data', 'conflict', 'unsupported')
HEADER = 'OZ/1g'
MAX_LINE_BYTES = 65536
CLAIM = 'No classification failures were observed in six repetitions of this frozen packet.'
SIDE_FILES = ('01-astra-r1.md', '02-opus-r1.md', '03-astra-r2-signed.md')


class ProbeError(Exception):
    pass


# ---------------------------------------------------------------- small helpers

def sha(data) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode('utf-8')).hexdigest()


def canon(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def file_sha(path: Path) -> str:
    """sha256 of a text file with line endings normalized, so a Windows checkout and a Linux one agree."""
    return sha(Path(path).read_bytes().replace(b'\r\n', b'\n'))


def compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def iso(ts: float) -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(ts)) + f'.{int(ts % 1 * 1000):03d}Z'


def system_text() -> str:
    sys.path.insert(0, str(ROOT))
    try:
        from oz_batch import SYSTEM
    finally:
        sys.path.pop(0)
    return SYSTEM


# ---------------------------------------------------------------- oracle (independent of the executor)

def parse_record(text: str) -> dict:
    fields = [p.split('=', 1) for p in text.split('; ')]
    names = ('length', 'uncertainty', 'n', 'method', 'basis', 'physical_validation')
    if any(len(p) != 2 for p in fields) or tuple(k for k, _ in fields) != names:
        raise ProbeError('record does not have the pinned field order')
    return dict(fields)


def _mm(value: str) -> Decimal:
    if not re.fullmatch(r'-?[0-9]+\.[0-9]{2} mm', value):
        raise ProbeError('not a two-decimal mm value: ' + value)
    try:
        return Decimal(value[:-3])
    except InvalidOperation:
        raise ProbeError('not a number: ' + value) from None


def oracle_interval(record_text: str):
    """[lower, upper] as 'x.xx mm' strings, or 'unknown'."""
    fields = parse_record(record_text)
    if fields['uncertainty'] == 'unknown':
        return 'unknown'
    length, u = _mm(fields['length']), _mm(fields['uncertainty'])
    return [f'{length - u:.2f} mm', f'{length + u:.2f} mm']


def oracle_label(interval) -> str:
    if interval == 'unknown':
        return 'unknown'
    low, high = _mm(interval[0]), _mm(interval[1])
    return 'inside' if low >= LOWER and high <= UPPER else 'outside'


def interval_consistent(record_text: str, interval) -> bool:
    """The two-ref check of arm C: the second ref is exactly the interval recomputed from the first."""
    try:
        return oracle_interval(record_text) == interval
    except ProbeError:
        return False


# ---------------------------------------------------------------- packets

def sources() -> dict:
    return {name: (FROZEN_DIR / rel).read_bytes().decode('utf-8') for name, rel in SOURCE_FILES.items()}


def workflow() -> dict:
    return json.loads((FROZEN_DIR / 'workflow.json').read_text(encoding='utf-8'))


def ops() -> dict:
    return {'A': workflow()['model_ops']['model.classify']['instruction'], 'B': OP_B, 'C': OP_C}


def build_prompt(arm: str) -> str:
    records = list(sources().values())
    if arm == 'C':
        refs = records + list(C_INTERVALS)
        rows = [[i, k, k + 4] for i, k in zip(IDS, range(4))]
    else:
        refs = records
        rows = [[i, k] for i, k in zip(IDS, range(4))]
    body = {'v': '1g', 'goal': workflow()['goal'], 'ops': [ops()[arm]], 'refs': refs, 'jobs': [[0, *rows]]}
    return compact(body)


def validate_packet(arm: str, prompt: str) -> list:
    """Problems with a packet (empty when it is exactly the frozen packet of the arm, with consistent intervals)."""
    problems = []
    if '\n' in prompt or '\r' in prompt:
        problems.append('prompt contains a line break (stdin newline translation would change the bytes)')
    try:
        body = json.loads(prompt)
    except ValueError:
        return problems + ['prompt is not JSON']
    if not isinstance(body, dict) or list(body) != ['v', 'goal', 'ops', 'refs', 'jobs']:
        return problems + ['prompt keys are not v,goal,ops,refs,jobs']
    if body['v'] != '1g' or body['goal'] != workflow()['goal'] or body['ops'] != [ops()[arm]]:
        problems.append('v, goal or op text differs from the frozen text of arm ' + arm)
    records = list(sources().values())
    refs, jobs = body['refs'], body['jobs']
    width = 2 if arm == 'C' else 1
    if not isinstance(refs, list) or refs[:4] != records or len(refs) != 4 * width:
        return problems + ['refs are not the four frozen stale records' + (' plus four intervals' if arm == 'C' else '')]
    if not (isinstance(jobs, list) and len(jobs) == 1 and jobs[0][0] == 0 and
            [r[0] for r in jobs[0][1:]] == list(IDS) and
            all(r[1:] == [k] + ([k + 4] if arm == 'C' else []) for k, r in enumerate(jobs[0][1:]))):
        return problems + ['job block is not the frozen block of arm ' + arm]
    for k, record in enumerate(records):
        if arm == 'C':
            if refs[4 + k] != C_INTERVALS[k]:
                problems.append(f'interval ref {4 + k} is not the frozen interval')
            if not interval_consistent(record, refs[4 + k]):
                problems.append(f'interval ref {4 + k} does not match its record')
        if oracle_label(oracle_interval(record)) != EXPECTED[IDS[k]]:
            problems.append(f'oracle label of {IDS[k]} differs from the frozen label')
    return problems


def schedule() -> list:
    out = []
    for b, block in enumerate(BLOCKS, 1):
        for p, arm in enumerate(block, 1):
            out.append({'slot': len(out) + 1, 'block': b, 'position': p, 'arm': arm})
    return out


def requests() -> dict:
    system = system_text()
    return {arm: {'system': system, 'prompt': build_prompt(arm)} for arm in ARMS}


def call_argv(system: str, claude: str = 'claude') -> list:
    """The adapter's argv (examples/claude_cli_adapter.py), model fixed to MODEL."""
    return [claude, '-p', '--model', MODEL, '--system-prompt', system, '--tools', '', '--setting-sources', '',
            '--strict-mcp-config', '--no-session-persistence', '--output-format', 'json']


# ---------------------------------------------------------------- freeze

def freeze_record() -> dict:
    """Everything frozen, as one JSON-able record. Raises ProbeError when the reconstruction disagrees with the
    evidence (control packet hash, H, record hashes, committed ledgers) or a packet fails its own validation."""
    system = system_text()
    if sha(system) != SYSTEM_SHA:
        raise ProbeError(f'H hashes to {sha(system)}, expected {SYSTEM_SHA}')
    srcs = sources()
    for name, text in srcs.items():
        if sha(text) != RECORD_SHAS[name]:
            raise ProbeError(f'record {name} hashes to {sha(text)}, expected {RECORD_SHAS[name]}')
    reqs = requests()
    if sha(reqs['A']['prompt']) != CONTROL_SHA:
        raise ProbeError(f'reconstructed control packet hashes to {sha(reqs["A"]["prompt"])}, expected {CONTROL_SHA}')
    for arm in ARMS:
        problems = validate_packet(arm, reqs[arm]['prompt'])
        if problems:
            raise ProbeError(f'packet {arm}: ' + '; '.join(problems))
    for rel in STALE_LEDGERS:
        starts = [json.loads(l) for l in (ROOT / rel).read_text(encoding='utf-8').splitlines() if l.strip()]
        starts = [e for e in starts if e['event'] == 'call_start' and e['prompt_sha256'] == CONTROL_SHA]
        if not starts or any(e['system_sha256'] != SYSTEM_SHA for e in starts):
            raise ProbeError(f'{rel} does not show the control packet under H')
    adapter = ADAPTER.read_text(encoding='utf-8')
    for flag in ('-p', '--model', '--system-prompt', '--tools', '--setting-sources', '--strict-mcp-config',
                 '--no-session-persistence', '--output-format', 'json'):
        if f"'{flag}'" not in adapter:
            raise ProbeError(f'the adapter no longer passes {flag}')
    sched = schedule()
    if sorted(s['arm'] for s in sched) != sorted(ARMS * 6) or len(sched) != CAPS['max_launches']:
        raise ProbeError('schedule is not 18 slots of 6 per arm')
    return {
        'plan': PLAN_ID,
        'route': {'model': MODEL, 'effort': 'default', 'cli_version': CLI_VERSION, 'transport': 'claude -p, no tools',
                  'argv': call_argv('<H>'), 'prompt_via': 'stdin, utf-8 bytes', 'forbidden_env': list(FORBIDDEN_ENV),
                  'parser': 'oz1g-header strict (boundary.py parse_reply)', 'usage': 'modelUsage only'},
        'system_sha256': SYSTEM_SHA,
        'arms': {arm: {'op': ops()[arm], 'prompt_sha256': sha(reqs[arm]['prompt']),
                       'prompt_bytes': len(reqs[arm]['prompt'].encode('utf-8'))} for arm in ARMS},
        'records': RECORD_SHAS, 'c_intervals': [list(i) if isinstance(i, list) else i for i in C_INTERVALS],
        'expected': EXPECTED, 'boundary_members': list(BOUNDARY),
        'schedule': [f"{s['slot']}:{s['arm']}" for s in sched], 'blocks': list(BLOCKS), 'caps': CAPS,
        'rules': {'call': 'sequential fresh processes, no retries, replacements, continuation or extension',
                  'contrast_floor': 'A not entirely correct on at least 3 of 6 calls',
                  'candidate': 'B or C entirely correct, on time, complete accounting, on 6 of 6',
                  'tie_break': 'lower total tokens, then lower total elapsed', 'claim': CLAIM},
        'files': {'bench/probe/boundary.py': file_sha(Path(__file__)),
                  'examples/claude_cli_adapter.py': file_sha(ADAPTER),
                  'bench/step4/inspection-handoff-20-v1/workflow.json': file_sha(FROZEN_DIR / 'workflow.json'),
                  **{f'docs/design/boundary-probe-2026-10-23/{n}': file_sha(DESIGN / n) for n in SIDE_FILES}},
    }


def freeze_digest(record: dict | None = None) -> str:
    return sha(canon(record or freeze_record()))


def cmd_freeze(args) -> int:
    try:
        record = freeze_record()
    except ProbeError as exc:
        print('FREEZE FAILED: ' + str(exc))
        return 2
    print('digest: ' + freeze_digest(record))
    print(f"system H: {record['system_sha256']}")
    for arm in ARMS:
        a = record['arms'][arm]
        print(f"arm {arm}: prompt {a['prompt_sha256']} ({a['prompt_bytes']} bytes)")
    print('control packet matches 48ecc5b0 (checked against live1 and live2 ledgers)')
    print('expected: ' + ', '.join(f'{k}={v}' for k, v in EXPECTED.items()))
    print('schedule: ' + ' '.join(BLOCKS) + ' (' + ' '.join(record['schedule']) + ')')
    print('caps: ' + ', '.join(f'{k}={v}' for k, v in CAPS.items()))
    for name, digest in record['files'].items():
        print(f'file {name}: {digest}')
    return 0


# ---------------------------------------------------------------- strict reply parser (OZ/1g header profile)

def _no_dupes(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate key')
    return dict(pairs)


def _no_const(_):
    raise ValueError('non-finite number')


def _load(line: str):
    return json.loads(line, object_pairs_hook=_no_dupes, parse_constant=_no_const)


def parse_reply(text, ids=IDS) -> dict:
    """Strict judgement of a raw reply. Returns {'ok': bool, 'reason': str|None, 'entries': {id: ('value', v) |
    ('error', code, message)}}. The whole reply is rejected on any malformed nonblank line, an unknown, missing or
    duplicate id, or a missing header. No salvage."""
    ids = tuple(ids)
    if not isinstance(text, str):
        return {'ok': False, 'reason': 'reply is not text', 'entries': {}}
    lines = text.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    first = next((k for k, line in enumerate(lines) if line.removesuffix('\r').strip(' \t')), None)
    if first is None:
        return {'ok': False, 'reason': 'no result line', 'entries': {}}
    if lines[first].removesuffix('\r').rstrip(' \t') != HEADER:
        return {'ok': False, 'reason': f'first nonblank line is not {HEADER}', 'entries': {}}
    entries, bad = {}, []
    for number, line in enumerate(lines[first + 1:], first + 2):
        line = line.removesuffix('\r')
        if not line.strip(' \t'):
            continue
        if len(line.encode('utf-8', 'surrogatepass')) > MAX_LINE_BYTES:
            bad.append(f'line {number} too long')
            continue
        try:
            value = _load(line)
        except (ValueError, RecursionError):
            bad.append(f'line {number} is not one JSON value')
            continue
        if isinstance(value, dict) and len(value) == 1:
            (key, result), = value.items()
            record = ('value', result)
        elif isinstance(value, list) and len(value) == 4:
            key = value[0]
            _, marker, code, message = value
            if marker != 'error' or not isinstance(code, str) or code not in ERROR_CODES or \
                    not isinstance(message, str) or not message.strip():
                bad.append(f'line {number} is a malformed error record')
                continue
            record = ('error', code, message)
        else:
            bad.append(f'line {number} is not a one-member object or four-element error array')
            continue
        if not isinstance(key, str) or key not in ids:
            bad.append(f'line {number} has an unknown or non-string id')
        elif key in entries:
            bad.append(f'line {number} repeats id {key}')
        else:
            entries[key] = record
    if bad:
        return {'ok': False, 'reason': '; '.join(bad[:5]), 'entries': {}}
    if set(entries) != set(ids):
        return {'ok': False, 'reason': 'ids missing: ' + ','.join(sorted(set(ids) - set(entries))), 'entries': {}}
    return {'ok': True, 'reason': None, 'entries': entries}


# ---------------------------------------------------------------- one call: accounting and scoring

def model_usage(envelope) -> dict:
    """Accounting from modelUsage only. complete is False when modelUsage is absent or any entry lacks a required
    non-negative integer counter (never read as zero, never filled in from the CLI's `usage`). thinking is the sum of
    thinkingTokens, or None when any entry lacks it (unknown, never zero); it is not added to output tokens."""
    mu = envelope.get('modelUsage') if isinstance(envelope, dict) else None
    out = {'models': None, 'complete': False, 'input': None, 'cache_read': None, 'cache_creation': None,
           'output': None, 'total': None, 'thinking': None}
    if not isinstance(mu, dict) or not mu:
        return out
    out['models'] = sorted(mu)
    entries = list(mu.values())
    if any(not isinstance(e, dict) or any(type(e.get(k)) is not int or e[k] < 0 for k in USAGE_KEYS) for e in entries):
        return out
    totals = [sum(e[k] for e in entries) for k in USAGE_KEYS]
    out.update(complete=True, input=totals[0], cache_read=totals[1], cache_creation=totals[2], output=totals[3],
               total=sum(totals))
    if all(type(e.get('thinkingTokens')) is int and e['thinkingTokens'] >= 0 for e in entries):
        out['thinking'] = sum(e['thinkingTokens'] for e in entries)
    return out


def evaluate(exit_code, timed_out: bool, elapsed_ms: int, stdout: bytes) -> dict:
    """The whole judgement of one call from its raw evidence. outcome is one of deadline, process_failure,
    wire_rejected, model_error, semantic, correct (mutually exclusive, in that priority)."""
    ev = {'exit_code': exit_code, 'timed_out': bool(timed_out), 'elapsed_ms': elapsed_ms,
          'on_time': (not timed_out) and elapsed_ms <= CAPS['call_seconds'] * 1000,
          'envelope_ok': False, 'usage': model_usage(None), 'route': 'unknown', 'reject_reason': None,
          'members': {}, 'correct_members': 0, 'boundary_error': False, 'model_error_lines': 0,
          'entirely_correct': False}
    envelope = None
    try:
        envelope = json.loads(stdout.decode('utf-8'), parse_constant=_no_const)
    except (ValueError, UnicodeError):
        pass
    if isinstance(envelope, dict):
        ev['envelope_ok'] = True
        ev['usage'] = model_usage(envelope)
        models = ev['usage']['models']
        if models is not None:
            ev['route'] = 'ok' if models == [MODEL] else 'mismatch'
    result = envelope.get('result') if isinstance(envelope, dict) else None
    failed = (exit_code != 0 or not ev['envelope_ok'] or envelope.get('is_error') is True or
              envelope.get('subtype', 'success') != 'success' or not isinstance(result, str))
    if timed_out:
        ev['outcome'] = 'deadline'
        return ev
    if failed:
        ev['outcome'] = 'process_failure'
        return ev
    parsed = parse_reply(result)
    if not parsed['ok']:
        ev['outcome'], ev['reject_reason'] = 'wire_rejected', parsed['reason']
        return ev
    for job in IDS:
        record = parsed['entries'][job]
        right = record[0] == 'value' and type(record[1]) is str and record[1] == EXPECTED[job]
        ev['members'][job] = {'got': record[1] if record[0] == 'value' else list(record[1:]), 'kind': record[0],
                              'expected': EXPECTED[job], 'correct': right}
        ev['model_error_lines'] += record[0] == 'error'
    ev['correct_members'] = sum(m['correct'] for m in ev['members'].values())
    ev['boundary_error'] = any(not ev['members'][j]['correct'] for j in BOUNDARY)
    if ev['model_error_lines']:
        ev['outcome'] = 'model_error'
    elif ev['correct_members'] < len(IDS):
        ev['outcome'] = 'semantic'
    else:
        ev['outcome'] = 'correct'
    ev['entirely_correct'] = ev['outcome'] == 'correct' and ev['on_time']
    return ev


# ---------------------------------------------------------------- evidence store

class Store:
    """Append-only ledger plus one directory per call. Every launched slot is recorded before the process starts."""

    def __init__(self, out: Path):
        self.out = Path(out)
        self.ledger = self.out / 'ledger.jsonl'

    def call_dir(self, slot: dict) -> Path:
        return self.out / 'calls' / f"{slot['slot']:02d}-{slot['arm']}"

    def append(self, event: dict) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        with open(self.ledger, 'ab') as file:
            file.write((canon(event) + '\n').encode('utf-8'))
            file.flush()
            os.fsync(file.fileno())

    def events(self) -> tuple:
        """(events, problems). Problems cover unreadable lines and duplicate or orphan records."""
        events, problems = [], []
        if self.ledger.exists():
            for n, line in enumerate(self.ledger.read_text(encoding='utf-8').splitlines(), 1):
                try:
                    events.append(json.loads(line))
                except ValueError:
                    problems.append(f'ledger line {n} is not JSON')
        launches, ends = {}, {}
        for e in events:
            kind = e.get('event')
            if kind in ('launch', 'end'):
                book = launches if kind == 'launch' else ends
                if e.get('slot') in book:
                    problems.append(f"duplicate {kind} record for slot {e.get('slot')}")
                book[e.get('slot')] = e
        for slot, e in ends.items():
            if slot not in launches:
                problems.append(f'end record for slot {slot} without a launch')
            elif launches[slot].get('call_id') != e.get('call_id'):
                problems.append(f'call id of slot {slot} differs between launch and end')
        ids = [e.get('call_id') for e in launches.values()]
        if len(set(ids)) != len(ids):
            problems.append('call ids are not unique')
        return events, problems


def state_of(events: list) -> dict:
    launches = {e['slot']: e for e in events if e.get('event') == 'launch'}
    ends = {e['slot']: e for e in events if e.get('event') == 'end'}
    halts = [e for e in events if e.get('event') == 'halt']
    acks = [e for e in events if e.get('event') == 'ack']
    plan = next((e for e in events if e.get('event') == 'plan'), None)
    return {'plan': plan, 'launches': launches, 'ends': ends,
            'orphans': sorted(set(launches) - set(ends)),
            'open_halt': next((h for h in reversed(halts) if h['terminal'] or
                               not any(a['halt'] == h['seq'] for a in acks)), None),
            'first_launch': min((e['ts'] for e in launches.values()), default=None)}


def spent_tokens(ends: dict) -> int:
    """Known tokens, with a call of unknown usage charged at the reservation."""
    return sum(e['evaluation']['usage']['total'] if e['evaluation']['usage']['complete'] else CAPS['reserve_tokens']
               for e in ends.values())


# ---------------------------------------------------------------- the runners

def live_runner(request: dict, timeout: int):
    """One fresh `claude -p`, exactly the adapter's invocation. Returns (exit_code, stdout, stderr, timed_out)."""
    claude = shutil.which('claude')
    if claude is None:
        raise ProbeError('claude is not on PATH')
    try:
        proc = subprocess.run(call_argv(request['system'], claude), input=request['prompt'].encode('utf-8'),
                              capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return None, exc.stdout or b'', exc.stderr or b'', True
    return proc.returncode, proc.stdout, proc.stderr, False


def preflight_live() -> list:
    problems = [f'{k} is set; it can change the route or effort (unset it)' for k in FORBIDDEN_ENV if os.environ.get(k)]
    claude = shutil.which('claude')
    if claude is None:
        return problems + ['claude is not on PATH']
    try:
        found = subprocess.run([claude, '--version'], capture_output=True, text=True, timeout=60).stdout.split()
    except (OSError, subprocess.SubprocessError) as exc:
        return problems + [f'claude --version failed: {exc}']
    if not found or found[0] != CLI_VERSION:
        problems.append(f'claude CLI version {found[0] if found else None} != frozen {CLI_VERSION}')
    return problems


# ---------------------------------------------------------------- run

def run(out: Path, expect: str, runner=live_runner, *, clock=time.time, ack_halt: bool = False, preflight=None,
        log=print, record=None) -> dict:
    """Launch the remaining slots of the frozen schedule in order. Resumable: finished slots are never re-run. Stops at
    the first of: a cap, an open halt (accounting incomplete, orphaned launch, route mismatch), the end of the schedule.
    Returns {'launched': n, 'stopped': reason}."""
    record = record or freeze_record()
    digest = freeze_digest(record)
    if expect != digest:
        raise ProbeError(f'--expect {expect} is not the current freeze digest {digest}; nothing was launched')
    if preflight is not None:
        problems = preflight()
        if problems:
            raise ProbeError('preflight failed: ' + '; '.join(problems) + '; nothing was launched')
    store = Store(out)
    events, problems = store.events()
    if problems:
        raise ProbeError('ledger integrity: ' + '; '.join(problems) + '; nothing was launched')
    state = state_of(events)
    if state['plan'] and state['plan']['digest'] != digest:
        raise ProbeError('this evidence directory belongs to another freeze digest; use a fresh directory')
    if not state['plan']:
        store.append({'event': 'plan', 'digest': digest, 'ts': clock(), 'caps': CAPS})
    reqs = requests()
    launched = 0
    seq = sum(1 for e in events if e.get('event') in ('halt', 'ack'))

    def halt(reason, terminal=False):
        nonlocal seq
        seq += 1
        store.append({'event': 'halt', 'seq': seq, 'reason': reason, 'terminal': terminal, 'ts': clock()})
        return {'launched': launched, 'stopped': ('terminal halt: ' if terminal else 'halt: ') + reason}

    if state['orphans']:
        open_orphan = f"slot {state['orphans'][0]} was launched but never recorded as finished"
        if not ack_halt:
            return {'launched': 0, 'stopped': 'halt: ' + open_orphan + ' (inspect it, then run with --acknowledge-halt)'}
        for slot in state['orphans']:
            store.append({'event': 'end', 'slot': slot, 'call_id': state['launches'][slot]['call_id'],
                          'ts': clock(), 'orphan_closed': True, 'stdout_sha256': sha(b''), 'stderr_sha256': sha(b''),
                          'evaluation': evaluate(None, False, 0, b'')})
        events, _ = store.events()
        state = state_of(events)
    elif state['open_halt']:
        if state['open_halt']['terminal']:
            return {'launched': 0, 'stopped': 'terminal halt: ' + state['open_halt']['reason']}
        if not ack_halt:
            return {'launched': 0, 'stopped': 'halt: ' + state['open_halt']['reason'] +
                    ' (inspect it, then run with --acknowledge-halt)'}
        seq += 1
        store.append({'event': 'ack', 'halt': state['open_halt']['seq'], 'ts': clock()})
    for slot in schedule():
        if slot['slot'] in state['ends']:
            continue
        if len(state['launches']) >= CAPS['max_launches']:
            return {'launched': launched, 'stopped': 'launch cap reached'}
        now = clock()
        first = state['first_launch'] if state['first_launch'] is not None else now
        if now - first >= CAPS['overall_seconds']:
            return {'launched': launched, 'stopped': 'overall time cap reached'}
        if spent_tokens(state['ends']) + CAPS['reserve_tokens'] > CAPS['max_tokens']:
            return {'launched': launched, 'stopped': 'token ceiling: no room for another reservation'}
        request = reqs[slot['arm']]
        call_id = uuid.uuid4().hex
        cdir = store.call_dir(slot)
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / 'request.json').write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
        launch = {'event': 'launch', 'slot': slot['slot'], 'arm': slot['arm'], 'block': slot['block'],
                  'position': slot['position'], 'call_id': call_id, 'ts': now, 'at': iso(now),
                  'system_sha256': sha(request['system']), 'prompt_sha256': sha(request['prompt']),
                  'argv_flags': call_argv('<H>')[1:]}
        store.append(launch)
        state['launches'][slot['slot']] = launch
        state['first_launch'] = first
        launched += 1
        log(f"slot {slot['slot']:2d}/18 arm {slot['arm']} block {slot['block']} launching")
        started = clock()
        # An exception here leaves the launch record without an end record: an orphan, counted and never retried.
        exit_code, stdout, stderr, timed_out = runner(request, CAPS['call_seconds'])
        elapsed_ms = int(round((clock() - started) * 1000))
        (cdir / 'envelope.json').write_bytes(stdout)
        (cdir / 'stderr.txt').write_bytes(stderr)
        evaluation = evaluate(exit_code, timed_out, elapsed_ms, stdout)
        end = {'event': 'end', 'slot': slot['slot'], 'call_id': call_id, 'ts': clock(), 'at': iso(clock()),
               'stdout_sha256': sha(stdout), 'stderr_sha256': sha(stderr), 'evaluation': evaluation}
        (cdir / 'meta.json').write_text(json.dumps({'launch': launch, 'end': end}, indent=1), encoding='utf-8')
        store.append(end)
        state['ends'][slot['slot']] = end
        log(f"  -> {evaluation['outcome']}, {evaluation['correct_members']}/4 right, tokens "
            f"{evaluation['usage']['total']}, thinking {evaluation['usage']['thinking']}, {elapsed_ms} ms")
        if evaluation['route'] == 'mismatch':
            return halt(f"slot {slot['slot']} reported models {evaluation['usage']['models']}, not {MODEL}", True)
        if not evaluation['usage']['complete']:
            return halt(f"slot {slot['slot']} has incomplete accounting (modelUsage missing or lacking a counter)")
    return {'launched': launched, 'stopped': 'schedule complete'}


# ---------------------------------------------------------------- statistics

def fisher_two_sided(a_ok: int, a_n: int, b_ok: int, b_n: int) -> float:
    """Two-sided Fisher exact p for the 2x2 table [[a_ok, a_n-a_ok], [b_ok, b_n-b_ok]] (table-probability method)."""
    ok, n, k = a_ok + b_ok, a_n + b_n, a_n

    def p(x):
        return math.comb(ok, x) * math.comb(n - ok, k - x) / math.comb(n, k)

    observed = p(a_ok)
    return min(1.0, sum(p(x) for x in range(max(0, k - (n - ok)), min(k, ok) + 1) if p(x) <= observed * (1 + 1e-9)))


def read_calls(store: Store) -> tuple:
    """Re-evaluate every finished call from its raw envelope. Returns (rows, problems, state)."""
    events, problems = store.events()
    state = state_of(events)
    rows = []
    sched = {s['slot']: s for s in schedule()}
    for slot_no, end in sorted(state['ends'].items()):
        slot = sched.get(slot_no)
        launch = state['launches'].get(slot_no)
        if slot is None or launch is None or launch['arm'] != slot['arm']:
            problems.append(f'slot {slot_no} is not in the frozen schedule')
            continue
        cdir = store.call_dir(slot)
        stdout = (cdir / 'envelope.json').read_bytes() if (cdir / 'envelope.json').exists() else b''
        stderr = (cdir / 'stderr.txt').read_bytes() if (cdir / 'stderr.txt').exists() else b''
        if not end.get('orphan_closed') and (sha(stdout) != end['stdout_sha256'] or sha(stderr) != end['stderr_sha256']):
            problems.append(f'slot {slot_no}: retained output differs from its recorded digest')
        stored = end['evaluation']
        ev = evaluate(stored['exit_code'], stored['timed_out'], stored['elapsed_ms'], stdout)
        if ev != stored:
            problems.append(f'slot {slot_no}: re-scoring the retained output differs from the recorded evaluation')
        rows.append({**slot, 'call_id': end['call_id'], 'orphan_closed': bool(end.get('orphan_closed')), **ev})
    return rows, problems, state


def analyze(out: Path) -> dict:
    store = Store(out)
    rows, problems, state = read_calls(store)
    arms = {}
    for arm in ARMS:
        rs = [r for r in rows if r['arm'] == arm]
        usage_known = [r['usage']['total'] for r in rs if r['usage']['complete']]
        ok_members = sum(r['correct_members'] for r in rs if r['on_time'])
        total = sum(usage_known)
        arms[arm] = {
            'calls': len(rs),
            'entirely_correct': sum(r['entirely_correct'] for r in rs),
            'not_entirely_correct': sum(not r['entirely_correct'] for r in rs),
            'boundary_error_calls': sum(r['boundary_error'] for r in rs),
            'correct_members': sum(r['correct_members'] for r in rs), 'member_total': 4 * len(rs),
            'boundary_correct_members': sum(r['members'][j]['correct'] for r in rs if r['members'] for j in BOUNDARY),
            'boundary_member_total': len(BOUNDARY) * len(rs),
            'outcomes': {o: sum(r['outcome'] == o for r in rs)
                         for o in ('correct', 'semantic', 'model_error', 'wire_rejected', 'process_failure', 'deadline')},
            'accounting_complete_calls': sum(r['usage']['complete'] for r in rs),
            'route_ok_calls': sum(r['route'] == 'ok' for r in rs), 'route_mismatch_calls': sum(r['route'] == 'mismatch' for r in rs),
            'total_tokens_known': total, 'tokens_unknown_calls': len(rs) - len(usage_known),
            'correct_on_time_members': ok_members,
            'tokens_per_correct_member': (total / ok_members) if ok_members else None,
            'elapsed_ms': [r['elapsed_ms'] for r in rs], 'elapsed_total_ms': sum(r['elapsed_ms'] for r in rs),
            'thinking': {'zero': [r for r in rs if r['usage']['thinking'] == 0],
                         'positive': [r for r in rs if (r['usage']['thinking'] or 0) > 0],
                         'unknown': [r for r in rs if r['usage']['thinking'] is None]},
        }
    for arm, a in arms.items():
        strata = {}
        for name, rs in a.pop('thinking').items():
            strata[name] = {'calls': len(rs), 'entirely_correct': sum(r['entirely_correct'] for r in rs),
                            'not_entirely_correct': sum(not r['entirely_correct'] for r in rs),
                            'boundary_errors': sum(r['boundary_error'] for r in rs),
                            'slots': [r['slot'] for r in rs]}
        known = sorted(r['usage']['thinking'] for r in rows if r['arm'] == arm and r['usage']['thinking'] is not None)
        a['thinking_strata'] = strata
        a['thinking_values'] = known
        a['assessable'] = bool(strata['zero']['calls'] and strata['positive']['calls'])
    fisher = {}
    for arm in ('B', 'C'):
        fisher[arm + ' vs A'] = (fisher_two_sided(arms[arm]['entirely_correct'], arms[arm]['calls'],
                                                  arms['A']['entirely_correct'], arms['A']['calls'])
                                 if arms['A']['calls'] and arms[arm]['calls'] else None)
    analysis = {'rows': rows, 'arms': arms, 'fisher': fisher, 'problems': problems,
                'launched': len(state['launches']), 'finished': len(state['ends']), 'orphans': state['orphans'],
                'open_halt': state['open_halt']['reason'] if state['open_halt'] else None,
                'spent_admission_tokens': spent_tokens(state['ends']),
                'digest': state['plan']['digest'] if state['plan'] else None}
    analysis['decision'] = decide(analysis)
    return analysis


def decide(analysis: dict) -> dict:
    """The signed decision rule. Returns {'verdict': code, 'text': sentence, 'candidate': arm|None}."""
    arms, rows = analysis['arms'], analysis['rows']
    reasons = []
    if analysis['problems']:
        reasons.append('evidence problems: ' + '; '.join(analysis['problems']))
    if any(arms[a]['calls'] != 6 for a in ARMS) or analysis['launched'] != 18 or analysis['orphans']:
        reasons.append('allocation incomplete (every arm needs six finished calls)')
    if any(r['route'] != 'ok' for r in rows):
        reasons.append('route not verified on every call')
    if any(not r['usage']['complete'] for r in rows):
        reasons.append('accounting incomplete on at least one call')
    if reasons:
        return {'verdict': 'incomplete', 'candidate': None,
                'text': 'Incomplete: ' + '; '.join(reasons) + '. No selection decision.'}
    a = arms['A']
    if a['boundary_error_calls'] == 0:
        return {'verdict': 'not_reproduced', 'candidate': None,
                'text': 'Not reproduced: A shows no boundary misclassification. No demonstrated correction and no '
                        'workflow change.'}
    if a['not_entirely_correct'] < 3:
        return {'verdict': 'insufficient_contrast', 'candidate': None,
                'text': f"Insufficient contrast: A failed on {a['not_entirely_correct']} of 6 calls (floor is 3). "
                        'Nothing is selected; the counts are reported.'}
    eligible = [x for x in ('B', 'C') if arms[x]['entirely_correct'] == 6]
    if not eligible:
        return {'verdict': 'no_candidate', 'candidate': None,
                'text': 'No candidate: neither B nor C was entirely correct on 6 of 6 calls. Counts reported; '
                        'nothing selected under the zero-failure rule.'}
    if len(eligible) == 1:
        pick, why = eligible[0], f'{eligible[0]} met the criterion alone'
    else:
        key = {x: (arms[x]['total_tokens_known'], arms[x]['elapsed_total_ms']) for x in eligible}
        if key['B'] == key['C']:
            return {'verdict': 'tie', 'candidate': None,
                    'text': 'Both B and C met the criterion with equal total tokens and elapsed time; no preference.'}
        pick = min(eligible, key=key.get)
        why = f'both met the criterion; {pick} has fewer measured total tokens, then less elapsed time (equal reliability is not claimed)'
    return {'verdict': 'nominate', 'candidate': pick,
            'text': f'Nominate {pick} for a separately frozen workflow evaluation and composition qualification: {why}. '
                    f'{CLAIM}'}


# ---------------------------------------------------------------- report rendering

def fmt(x, digits=1):
    return 'n/a' if x is None else (f'{x:.{digits}f}' if isinstance(x, float) else str(x))


def render(analysis: dict) -> str:
    arms, rows = analysis['arms'], analysis['rows']
    out = [f'# Boundary probe report ({PLAN_ID})', '',
           f"Freeze digest in the ledger: {analysis['digest']}. Launched {analysis['launched']} of 18, finished "
           f"{analysis['finished']}. Charged for the token ceiling: {analysis['spent_admission_tokens']} of "
           f"{CAPS['max_tokens']} (a call with unknown usage is charged at {CAPS['reserve_tokens']}).", '']
    if analysis['open_halt']:
        out += [f"Open halt: {analysis['open_halt']}", '']
    if analysis['orphans']:
        out += [f"Launched but never finished: slots {analysis['orphans']}", '']
    if analysis['problems']:
        out += ['Evidence problems:'] + [f'* {p}' for p in analysis['problems']] + ['']
    out += ['## Decision', '', analysis['decision']['text'], '', '## Per arm', '',
            '| Measure | A | B | C |', '|---|---|---|---|']

    def line(label, fn):
        out.append(f'| {label} | ' + ' | '.join(str(fn(arms[a])) for a in ARMS) + ' |')

    line('Calls finished', lambda a: a['calls'])
    line('Entirely correct, strictly accepted, on time (of 6)', lambda a: a['entirely_correct'])
    line('Calls with a boundary misclassification (classify_C)', lambda a: a['boundary_error_calls'])
    line('Correct members (of 24)', lambda a: f"{a['correct_members']}/{a['member_total']}")
    line('Correct boundary members (of 6)', lambda a: f"{a['boundary_correct_members']}/{a['boundary_member_total']}")
    for o in ('semantic', 'model_error', 'wire_rejected', 'process_failure', 'deadline'):
        line(f'Calls: {o}', lambda a, o=o: a['outcomes'][o])
    line('Calls with complete accounting', lambda a: a['accounting_complete_calls'])
    line('Total tokens (known calls)', lambda a: a['total_tokens_known'])
    line('Calls with unknown tokens', lambda a: a['tokens_unknown_calls'])
    line('Tokens per correct on-time member', lambda a: fmt(a['tokens_per_correct_member']) if a['tokens_per_correct_member'] is not None else 'undefined')
    line('Call durations (s)', lambda a: ', '.join(f'{ms / 1000:.1f}' for ms in a['elapsed_ms']) or 'none')
    out += ['', 'Failed calls stay in the token numerator. Reliability is judged per call; the four members of a call '
            'are not independent trials.', '', '## Fisher exact test (two-sided, descriptive only)', '',
            '| Comparison | p |', '|---|---|']
    for name, p in analysis['fisher'].items():
        out.append(f'| {name} (entirely correct calls, 6 vs 6) | {fmt(p, 4)} |')
    out += ['', '## Thinking tokens (observed, not adjusted)', '',
            '| Arm | thinking = 0 (correct / not) | thinking > 0 (correct / not) | unknown (correct / not) | '
            'boundary errors in 0, >0, unknown | known values | within-arm association |', '|---|---|---|---|---|---|---|']
    for arm in ARMS:
        a = arms[arm]
        s = a['thinking_strata']
        cell = lambda k: f"{s[k]['calls']} calls ({s[k]['entirely_correct']} / {s[k]['not_entirely_correct']})"
        out.append(f"| {arm} | {cell('zero')} | {cell('positive')} | {cell('unknown')} | "
                   f"{s['zero']['boundary_errors']}, {s['positive']['boundary_errors']}, {s['unknown']['boundary_errors']} | "
                   f"{a['thinking_values']} | {'assessable' if a['assessable'] else 'unassessable (a stratum is empty)'} |")
    out += ['', 'A correct zero-thinking call contradicts "positive thinking is necessary". An incorrect positive-thinking '
            'call contradicts "positive thinking is sufficient". A shift in thinking between arms is an association, not '
            'evidence of mediation.', '', '## Per-call rows', '',
            '| Slot | Arm | Block | Outcome | Right | Boundary error | Thinking | Input | Cache read | Cache write | '
            'Output | Total | Route | s |', '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        u = r['usage']
        out.append(f"| {r['slot']} | {r['arm']} | {r['block']}.{r['position']} | {r['outcome']} | "
                   f"{r['correct_members']}/4 | {'yes' if r['boundary_error'] else 'no'} | "
                   f"{'unknown' if u['thinking'] is None else u['thinking']} | {fmt(u['input'])} | {fmt(u['cache_read'])} | "
                   f"{fmt(u['cache_creation'])} | {fmt(u['output'])} | {fmt(u['total'])} | {r['route']} | "
                   f"{r['elapsed_ms'] / 1000:.1f} |")
    out += ['', 'Cache counters depend on schedule position; tokens are counted at full weight. Total = input + cache '
            'read + cache write + output over every modelUsage entry; thinking tokens are reported separately and are '
            'not added again.', '']
    return '\n'.join(out)


def write_report(out: Path) -> str:
    analysis = analyze(out)
    text = render(analysis)
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / 'report.md').write_text(text, encoding='utf-8')
    (Path(out) / 'report.json').write_text(json.dumps(analysis, indent=1, default=str), encoding='utf-8')
    return text


# ---------------------------------------------------------------- dry run (fixtures only, no process)

def fixture_envelope(result, *, usage=True, thinking=60, model=MODEL, tokens=(2, 603, 1935, 61), is_error=False):
    """An envelope shaped like the real one (see the retained step 4 captures)."""
    env = {'type': 'result', 'subtype': 'success', 'is_error': is_error, 'result': result, 'duration_ms': 5000,
           'usage': {'input_tokens': 2, 'output_tokens': 61}}
    if usage:
        entry = dict(zip(USAGE_KEYS, tokens))
        if thinking is not None:
            entry['thinkingTokens'] = thinking
        env['modelUsage'] = {model: entry}
    return env


GOOD = 'OZ/1g\n{"classify_A":"outside"}\n{"classify_B":"outside"}\n{"classify_C":"inside"}\n{"classify_D":"unknown"}'
FIXTURES = {
    'pass': (lambda: fixture_envelope(GOOD), 'entirely correct'),
    'wrong_label': (lambda: fixture_envelope(GOOD.replace('"classify_C":"inside"', '"classify_C":"outside"'), thinking=0),
                    'boundary misclassification at zero thinking'),
    'malformed': (lambda: fixture_envelope('The answers are: A outside, B outside, C inside, D unknown.'),
                  'wire rejected'),
    'missing_usage': (lambda: fixture_envelope(GOOD, usage=False), 'accounting incomplete'),
    'missing_thinking': (lambda: fixture_envelope(GOOD, thinking=None), 'thinking unknown, not zero'),
    'model_error_line': (lambda: fixture_envelope(GOOD.replace('{"classify_B":"outside"}',
                                                               '["classify_B","error","invalid_data","bad record"]')),
                         'valid model error line'),
    'code_fence': (lambda: fixture_envelope('```\n' + GOOD + '\n```'), 'wire rejected'),
    'duplicate_id': (lambda: fixture_envelope(GOOD + '\n{"classify_A":"outside"}'), 'wire rejected'),
    'wrong_model': (lambda: fixture_envelope(GOOD, model='claude-haiku-4-5'), 'route mismatch'),
}


def fixture_runner(plan: dict, clock_ref: list, *, seconds=6.0, default='pass'):
    """A runner that answers from fixtures: plan maps slot number -> case name or (envelope, exit_code, timed_out)."""
    calls = []

    def run_one(request, timeout, _calls=calls):
        n = len(_calls) + 1  # nth invocation of this runner
        _calls.append(request)
        case = plan.get(n, default)
        clock_ref[0] += seconds
        if case == 'timeout':
            clock_ref[0] += timeout
            return None, b'', b'', True
        if case == 'process_failure':
            return 1, b'Error: something broke', b'stderr text', False
        envelope = case if isinstance(case, dict) else FIXTURES[case][0]()
        return 0, json.dumps(envelope).encode('utf-8'), b'', False

    run_one.calls = calls
    return run_one


def cmd_dry(args) -> int:
    ok = True

    def check(label, condition, detail=''):
        nonlocal ok
        ok &= bool(condition)
        print(f"  [{'ok' if condition else 'FAIL'}] {label}" + (f': {detail}' if detail else ''))

    try:
        record = freeze_record()
    except ProbeError as exc:
        print('FREEZE FAILED: ' + str(exc))
        return 2
    digest = freeze_digest(record)
    print('dry run: fixtures only, no process is started and no tokens are spent')
    print('fixture replies scored by the real pipeline:')
    for name, (make, what) in FIXTURES.items():
        ev = evaluate(0, False, 6000, json.dumps(make()).encode('utf-8'))
        print(f"  {name:17s} outcome={ev['outcome']:14s} right={ev['correct_members']}/4 boundary_error={ev['boundary_error']!s:5s} "
              f"accounting={'complete' if ev['usage']['complete'] else 'incomplete'} thinking={ev['usage']['thinking']} "
              f"route={ev['route']}  ({what})")
    results = {n: evaluate(0, False, 6000, json.dumps(m()).encode('utf-8')) for n, (m, _) in FIXTURES.items()}
    check('pass is entirely correct', results['pass']['entirely_correct'])
    check('wrong label is a semantic boundary error at 0 thinking',
          results['wrong_label']['outcome'] == 'semantic' and results['wrong_label']['boundary_error'] and
          results['wrong_label']['usage']['thinking'] == 0 and results['wrong_label']['correct_members'] == 3)
    check('malformed reply earns zero accepted work', results['malformed']['outcome'] == 'wire_rejected' and
          results['malformed']['correct_members'] == 0)
    check('missing usage is incomplete accounting, not zero',
          not results['missing_usage']['usage']['complete'] and results['missing_usage']['usage']['total'] is None)
    check('missing thinking is unknown, not zero', results['missing_thinking']['usage']['thinking'] is None and
          results['missing_thinking']['usage']['complete'])
    check('timeout is a deadline miss, a crash a process failure',
          evaluate(None, True, 300000, b'')['outcome'] == 'deadline' and
          evaluate(1, False, 10, b'boom')['outcome'] == 'process_failure')

    base = Path(args.out)
    shutil.rmtree(base, ignore_errors=True)

    def scenario(name, plan, **options):
        clock = [1000.0]
        runner = fixture_runner(plan, clock, seconds=options.pop('seconds', 6.0))
        logs = []
        outcome = run(base / name, digest, runner, clock=lambda: clock[0], log=logs.append, record=record, **options)
        return outcome, runner, clock, logs

    print('scenario 1: mixed fixtures over the full schedule (pass, wrong label, malformed, missing thinking, model error)')
    plan = {1: 'wrong_label', 6: 'wrong_label', 8: 'wrong_label', 10: 'malformed', 7: 'missing_thinking', 12: 'model_error_line'}
    outcome, runner, clock, logs = scenario('mixed', plan)
    check('18 launches, schedule complete', outcome == {'launched': 18, 'stopped': 'schedule complete'} and
          len(runner.calls) == 18, str(outcome))
    again, runner2, _, _ = scenario('mixed', {})
    check('resume launches nothing more', again['launched'] == 0 and again['stopped'] == 'schedule complete')
    text = write_report(base / 'mixed')
    analysis = analyze(base / 'mixed')
    check('report has no evidence problems', not analysis['problems'], '; '.join(analysis['problems']))
    check('A failed 4 of 6 with boundary errors, B has a model error line, C is 6 of 6: C is nominated',
          analysis['decision']['verdict'] == 'nominate' and analysis['decision']['candidate'] == 'C',
          analysis['decision']['verdict'])
    print('  decision: ' + analysis['decision']['text'])

    print('scenario 2: missing usage halts further launches until acknowledged')
    outcome, runner, clock, _ = scenario('halt', {4: 'missing_usage'})
    check('stopped after the call with missing usage', outcome['launched'] == 4 and outcome['stopped'].startswith('halt:'), str(outcome))
    again, runner2, _, _ = scenario('halt', {})
    check('a plain re-run refuses', again['launched'] == 0 and 'acknowledge' in again['stopped'], str(again))
    cont, runner3, _, _ = scenario('halt', {}, ack_halt=True)
    check('acknowledged re-run finishes the schedule', cont == {'launched': 14, 'stopped': 'schedule complete'}, str(cont))
    verdict = analyze(base / 'halt')['decision']
    check('incomplete accounting gives no selection decision', verdict['verdict'] == 'incomplete', verdict['text'])

    print('scenario 3: route mismatch is terminal')
    outcome, runner, clock, _ = scenario('route', {3: 'wrong_model'})
    again, _, _, _ = scenario('route', {}, ack_halt=True)
    check('stops at the mismatch and stays stopped even with acknowledgement',
          outcome['launched'] == 3 and outcome['stopped'].startswith('terminal halt') and again['launched'] == 0,
          f'{outcome} / {again}')

    print('scenario 4: token ceiling (20000 tokens per call, 5000 reservation, 60000 ceiling)')
    big = fixture_envelope(GOOD, tokens=(2, 0, 19900, 98))
    outcome, runner, clock, _ = scenario('ceiling', {n: big for n in range(1, 19)})
    check('admission stops before a fourth call', outcome['launched'] == 3 and outcome['stopped'].startswith('token ceiling'), str(outcome))

    print('scenario 5: overall two-hour cap and the per-call deadline')
    outcome, runner, clock, _ = scenario('time', {}, seconds=2400.0)
    check('overall cap stops the run before a fourth call', outcome['stopped'] == 'overall time cap reached' and
          outcome['launched'] == 3, str(outcome))
    t_row = analyze(base / 'time')['rows'][0]
    check('a reply that took past 300 s is not on time and not entirely correct',
          not t_row['on_time'] and not t_row['entirely_correct'])

    print('scenario 6: an orphaned launch (process died between launch and end) is counted and blocks the run')
    store = Store(base / 'orphan')
    store.append({'event': 'plan', 'digest': digest, 'ts': 1.0, 'caps': CAPS})
    store.append({'event': 'launch', 'slot': 1, 'arm': 'A', 'block': 1, 'position': 1, 'call_id': 'x', 'ts': 2.0})
    outcome, _, _, _ = scenario('orphan', {})
    check('run refuses with an orphan', outcome['launched'] == 0 and 'never recorded as finished' in outcome['stopped'], str(outcome))

    print('scenario 7: a wrong --expect digest launches nothing')
    try:
        run(base / 'expect', '0' * 64, fixture_runner({}, [0.0]), record=record)
        check('refused', False)
    except ProbeError as exc:
        check('refused', 'nothing was launched' in str(exc))
    check('no fixture process was ever started: dry never calls live_runner', True)
    print('mixed-run report is in ' + str(base / 'mixed' / 'report.md'))
    print('DRY OK' if ok else 'DRY FAILED')
    return 0 if ok else 1


# ---------------------------------------------------------------- command line

def cmd_run(args) -> int:
    try:
        outcome = run(Path(args.out), args.expect, preflight=preflight_live, ack_halt=args.acknowledge_halt)
    except ProbeError as exc:
        print('REFUSED: ' + str(exc))
        return 2
    print(f"launched {outcome['launched']} this invocation; {outcome['stopped']}")
    print(write_report(Path(args.out)).split('## Per arm')[0])
    return 0 if outcome['stopped'] == 'schedule complete' else 3


def cmd_report(args) -> int:
    print(write_report(Path(args.out)))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('freeze').set_defaults(fn=cmd_freeze)
    p = sub.add_parser('dry')
    p.add_argument('--out', default=str(DEFAULT_DRY))
    p.set_defaults(fn=cmd_dry)
    p = sub.add_parser('run')
    p.add_argument('--expect', required=True, help='the digest printed by freeze')
    p.add_argument('--out', default=str(DEFAULT_OUT))
    p.add_argument('--acknowledge-halt', action='store_true',
                   help='continue past an accounting halt or an orphaned launch (a route mismatch is never continued)')
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser('report')
    p.add_argument('--out', default=str(DEFAULT_OUT))
    p.set_defaults(fn=cmd_report)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == '__main__':
    sys.exit(main())
