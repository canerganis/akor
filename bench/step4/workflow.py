"""inspection-handoff-20/v1: registered host operations, input-bound model checks and the frozen-file loader.

This is the runtime side of the step 4 executor conformance gate (docs/design/step4-2026-10-23/). Host operations are
explicitly registered implementations; model operations are the standard materials instructions (live2 MAT_D e, b, v
as the OZ/1g arm H sends them) with job-bound checks computed from each job's own model-visible record. The final
evaluator (evaluator.py) is a separate implementation and never reads these checks or the executor's flags.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oz_accept import REGISTRY, Check  # noqa: E402
from oz_flow import HostError, HostOp, ModelOp  # noqa: E402

HERE = Path(__file__).resolve().parent
FROZEN = HERE / 'inspection-handoff-20-v1'
WORKFLOW_ID = 'inspection-handoff-20/v1'
FIELDS = ('length', 'uncertainty', 'n', 'method', 'basis', 'physical_validation')
MISSING_ORDER = ('uncertainty', 'method', 'basis')
LOWER, UPPER = Decimal('12.48'), Decimal('12.52')
EVIDENCE = ('Numerical status is interval arithmetic on the recorded values only. It is not physical validation and '
            'does not authorize physical release.')


def load(name: str):
    return json.loads((FROZEN / name).read_text(encoding='utf-8'))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---- record parsing and the host arithmetic (Decimal, two decimals, mm) ----

def parse_record(text: str) -> dict:
    parts = text.split('; ')
    pairs = [p.split('=', 1) for p in parts]
    if any(len(p) != 2 for p in pairs) or tuple(k for k, _ in pairs) != FIELDS:
        raise HostError('record does not have the pinned field order')
    return dict(pairs)


def _mm(value: str) -> Decimal:
    if not re.fullmatch(r'-?[0-9]+\.[0-9]{2} mm', value):
        raise HostError('not a two-decimal mm value: ' + value)
    try:
        return Decimal(value[:-3])
    except InvalidOperation:
        raise HostError('not a number: ' + value) from None


def bounds_of(fields: dict):
    if fields['uncertainty'] == 'unknown':
        return 'unknown'
    length, u = _mm(fields['length']), _mm(fields['uncertainty'])
    return [f'{length - u:.2f} mm', f'{length + u:.2f} mm']


def status_of(bounds) -> str:
    if bounds == 'unknown':
        return 'unknown'
    low, high = _mm(bounds[0]), _mm(bounds[1])
    return 'inside' if low >= LOWER and high <= UPPER else 'outside'


def missing_of(fields: dict) -> list:
    return [f for f in MISSING_ORDER if fields[f] == 'unknown']


def follow_ups(missing, bounds, status) -> list:
    out = [{'category': 'missing_metadata', 'field': f} for f in missing]
    if status == 'outside':
        out.append({'category': 'numerical_review'})
    if bounds == 'unknown':
        out.append({'category': 'uncertainty_required'})
    return out


# ---- job-bound checks against each job's own record (oz_accept registry entries) ----

def _record(inputs) -> dict:
    texts = inputs.texts
    if len(texts) != 1 or not isinstance(texts[0], str):
        raise HostError('a materials job has exactly one record reference')
    return parse_record(texts[0])


def _guard(fn):
    def run(value, spec, inputs):
        try:
            return fn(value, _record(inputs))
        except HostError:
            return False
    return run


def _no_params(spec):
    if set(spec) - {'check', 'version'}:
        from oz import Error
        raise Error(f'check {spec["check"]} takes no parameters')


CHECKS = dict(REGISTRY)
CHECKS.update({c.name: c for c in (
    Check('mat_fields', 1, True, _no_params,
          _guard(lambda v, r: isinstance(v, list) and v == [r[f] for f in FIELDS])),
    Check('mat_bounds', 1, True, _no_params, _guard(lambda v, r: v == bounds_of(r))),
    Check('mat_classify', 1, True, _no_params, _guard(lambda v, r: v == status_of(bounds_of(r)))),
)})


# ---- host operations ----

def op_snapshot(inputs, ctx):
    names = inputs['sources']
    sources = load('workflow.json')['sources']
    if not isinstance(names, list) or names != list(sources):
        raise HostError('snapshot names must be the frozen source set')
    records = {}
    for name in names:
        s = ctx.read_source(name, FROZEN / sources[name])
        records[name] = {'text': s['bytes'].decode('utf-8'), 'revision': s['revision'], 'sha256': s['sha256']}
    return {'records': records}


def op_normalize(inputs, ctx):
    names, fields = inputs['names'], inputs['fields']
    if len(names) != len(fields):
        raise HostError('one extraction per record')
    out = {}
    for name, values in zip(names, fields):
        if not isinstance(values, list) or len(values) != len(FIELDS) or any(not isinstance(v, str) for v in values):
            raise HostError(f'extraction for {name} is not six strings')
        # Pinned field order and separator policy; accepted extractions reproduce the source bytes.
        out[name] = '; '.join(f'{k}={v}' for k, v in zip(FIELDS, values))
    return out


def op_check_intervals(inputs, ctx):
    """The validation barrier: every bound is recomputed on the host before any classification can run."""
    records, bounds = inputs['records'], inputs['bounds']
    names = list(records)
    if len(bounds) != len(names):
        raise HostError('one bounds result per record')
    checked = {}
    for name, value in zip(names, bounds):
        expected = bounds_of(parse_record(records[name]))
        if value != expected:
            raise HostError(f'bounds for {name} do not match the record')
        checked[name] = value
    return {'records': records, 'bounds': checked, 'check': 'host.decimal_bounds@1'}


def op_handoff_rows(inputs, ctx):
    snapshot, records, intervals, statuses = (inputs[k] for k in ('snapshot', 'records', 'intervals', 'status'))
    rows = []
    for name, status in zip(records, statuses):
        fields = parse_record(records[name])
        bounds = intervals['bounds'][name]
        if status != status_of(bounds):
            raise HostError(f'classification for {name} disagrees with its checked interval')
        missing = missing_of(fields)
        src = snapshot['records'][name]
        rows.append({'record': name, 'source': {'name': name, 'revision': src['revision'], 'sha256': src['sha256']},
                     'measurement': fields, 'interval': bounds, 'status': status, 'missing': missing,
                     'follow_ups': follow_ups(missing, bounds, status)})
    return {'rows': rows}


def handoff_document(rows) -> dict:
    return {'schema': 'akor.inspection-handoff/1', 'workflow': WORKFLOW_ID,
            'acceptance_interval': {'lower': '12.48 mm', 'upper': '12.52 mm', 'inclusive': True},
            'physical_validation': 'not_claimed', 'evidence': EVIDENCE, 'records': rows}


def op_render_json(inputs, ctx):
    return json.dumps(handoff_document(inputs['rows']['rows']), ensure_ascii=False, indent=1) + '\n'


def _cell(row, key):
    if key == 'interval':
        return 'unknown' if row['interval'] == 'unknown' else f"{row['interval'][0]} to {row['interval'][1]}"
    if key == 'missing':
        return ', '.join(row['missing']) or 'none'
    if key == 'source':
        s = row['source']
        return f"{s['name']} rev {s['revision']} sha256:{s['sha256']}"
    return row['measurement'][key]


COLUMNS = ('Record', 'Length', 'Uncertainty', 'n', 'Method', 'Basis', 'Interval', 'Status', 'Missing', 'Source')
KEYS = ('record', 'length', 'uncertainty', 'n', 'method', 'basis', 'interval', 'status', 'missing', 'source')


def op_render_markdown(inputs, ctx):
    rows = inputs['rows']['rows']
    lines = [f'# Inspection handoff ({WORKFLOW_ID})', '',
             'Acceptance interval: [12.48 mm, 12.52 mm], inclusive.', '',
             'physical_validation=not_claimed. ' + EVIDENCE, '',
             '| ' + ' | '.join(COLUMNS) + ' |', '|' + '---|' * len(COLUMNS)]
    for row in rows:
        cells = [row['record'] if k == 'record' else row['status'] if k == 'status' else _cell(row, k) for k in KEYS]
        lines.append('| ' + ' | '.join(cells) + ' |')
    lines += ['', '## Follow-ups', '']
    items = [f"{row['record']}: {f['category']}" + (f" ({f['field']})" if 'field' in f else '')
             for row in rows for f in row['follow_ups']]
    lines += [f'{i}. {item}' for i, item in enumerate(items, 1)] or ['None.']
    return '\n'.join(lines) + '\n'


def parse_markdown(text: str) -> dict:
    """Table rows and follow-up items of a rendered handoff (used by the runtime package check)."""
    rows, items = [], []
    for line in text.splitlines():
        if line.startswith('| ') and not line.startswith('| Record '):
            rows.append(dict(zip(KEYS, (c.strip() for c in line.strip('|').split(' | ')))))
        m = re.fullmatch(r'[0-9]+\. (.*)', line)
        if m:
            items.append(m.group(1))
    return {'rows': rows, 'follow_ups': items}


def op_verify_package(inputs, ctx):
    """Runtime package check: both artifacts, their agreement, source bindings, completeness and current freshness."""
    snapshot, text, md = inputs['snapshot'], inputs['json'], inputs['markdown']
    try:
        doc = json.loads(text)
    except ValueError:
        raise HostError('handoff.json is not JSON') from None
    names = list(load('workflow.json')['sources'])
    if doc.get('schema') != 'akor.inspection-handoff/1' or [r.get('record') for r in doc.get('records', [])] != names:
        raise HostError('handoff.json does not cover the records in order')
    if doc.get('physical_validation') != 'not_claimed' or doc.get('evidence') != EVIDENCE:
        raise HostError('handoff.json lacks the required evidence wording')
    if 'physical_validation=not_claimed' not in md or EVIDENCE not in md:
        raise HostError('handoff.md lacks the required evidence wording')
    parsed = parse_markdown(md)
    for row, line in zip(doc['records'], parsed['rows'] + [None] * 4):
        current = ctx.read_source(row['record'])
        if row['source'] != {'name': row['record'], 'revision': current['revision'], 'sha256': current['sha256']}:
            raise HostError(f"source binding for {row['record']} is not the current revision")
        if snapshot['records'][row['record']]['sha256'] != current['sha256']:
            raise HostError(f"snapshot of {row['record']} is not current")
        expected = {k: row['record'] if k == 'record' else row['status'] if k == 'status' else _cell(row, k)
                    for k in KEYS}
        if line != expected:
            raise HostError(f"handoff.md disagrees with handoff.json for {row['record']}")
    items = [f"{row['record']}: {f['category']}" + (f" ({f['field']})" if 'field' in f else '')
             for row in doc['records'] for f in row['follow_ups']]
    if items != parsed['follow_ups'] or len(parsed['rows']) != len(names):
        raise HostError('handoff.md follow-ups or rows disagree with handoff.json')
    files = {'handoff.json': text, 'handoff.md': md}
    return {'files': files, 'sha256': {k: hashlib.sha256(v.encode('utf-8')).hexdigest() for k, v in files.items()}}


def op_publish(inputs, ctx):
    return {'files': inputs['package']['files']}


HOST_OPS = (
    HostOp('host.snapshot', 1, frozenset({'sources'}), op_snapshot),
    HostOp('host.normalize', 1, frozenset({'names', 'fields'}), op_normalize),
    HostOp('host.check_intervals', 1, frozenset({'records', 'bounds'}), op_check_intervals),
    HostOp('host.handoff_rows', 1, frozenset({'snapshot', 'records', 'intervals', 'status'}), op_handoff_rows),
    HostOp('host.render_json', 1, frozenset({'rows'}), op_render_json),
    HostOp('host.render_markdown', 1, frozenset({'rows'}), op_render_markdown),
    HostOp('host.verify_package', 1, frozenset({'snapshot', 'json', 'markdown'}), op_verify_package),
    HostOp('host.publish', 1, frozenset({'package'}), op_publish, effect='local_publish'),
)


def registry(*, overrides=None, extra_checks=None) -> dict:
    """The pinned operation registry. overrides replace host implementations (sabotage fixtures only); extra_checks
    adds checks to one model operation (the C5 strengthened-check variant, acceptance-only)."""
    spec = load('workflow.json')
    ops = {op.name: op for op in HOST_OPS}
    for name, m in spec['model_ops'].items():
        checks = list(m['checks']) + list((extra_checks or {}).get(name, []))
        ops[name] = ModelOp(m['name'], m['version'], spec['goal'], m['instruction'], tuple(checks), m['memo'])
    ops.update(overrides or {})
    return ops


def graph() -> dict:
    return load('graph.json')


def source_bytes(name: str, variant: str = 'rev1') -> bytes:
    spec = load('workflow.json')
    if variant == 'rev2' and name in spec['mutations']['stale']['source']:
        return (FROZEN / spec['mutations']['stale']['file']).read_bytes()
    return (FROZEN / spec['sources'][name]).read_bytes()
