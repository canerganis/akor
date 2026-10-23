"""Independent evaluator for inspection-handoff-20/v1 (step 4 plan, clause 13).

A separate implementation from the runtime checks and host operations (workflow.py): it imports nothing from the
executor, reads only the frozen sources, the frozen expected values (expected.json) and delivered bytes, and never
consults an executor acceptance flag. evaluate_package scores a delivered handoff.json plus handoff.md;
evaluate_document scores a handoff JSON document alone (the baseline arm, Markdown excluded).

    python bench/step4/evaluator.py DELIVERY_DIR VARIANT REVISIONS_JSON
"""
import hashlib
import json
from pathlib import Path
import re
import sys

PACK = globals().get('PACK', 'inspection-handoff-20-v1')  # bench/step4/packs.py loads a copy for another pack
FROZEN = Path(__file__).resolve().parent / PACK
NAMES = ['A', 'B', 'C', 'D']
KEYS = ['length', 'uncertainty', 'n', 'method', 'basis', 'physical_validation']
WORDING = 'does not authorize physical release'
SCHEMA = 'akor.inspection-handoff/1'
WORKFLOW = {'inspection-handoff-20-v1': 'inspection-handoff-20/v1',
            'inspection-handoff-20-v2': 'inspection-handoff-20/v2'}[PACK]
# The evaluator's own copy of the acceptance interval (both packs); a test checks it against the v2 structured limits.
ACCEPTANCE_INTERVAL = {'lower': '12.48 mm', 'upper': '12.52 mm', 'inclusive': True}
EVIDENCE = ('Numerical status is interval arithmetic on the recorded values only. It is not physical validation and '
            'does not authorize physical release.')
TOP_KEYS = {'schema', 'workflow', 'acceptance_interval', 'physical_validation', 'evidence', 'records'}


def _frozen(name):
    return json.loads((FROZEN / name).read_text(encoding='utf-8'))


def _source(name, variant):
    rel = 'sources/A.rev2.txt' if variant == 'rev2' and name == 'A' else f'sources/{name}.txt'
    return (FROZEN / rel).read_bytes()


def expected_rows(variant):
    exp = _frozen('expected.json')
    out = {}
    for name in NAMES:
        row = dict(exp['rev1'][name])
        fields = exp['fields']['rev1'][name]
        if variant == 'rev2' and name in exp['rev2']:
            row = dict(exp['rev2'][name])
            fields = exp['fields']['rev2'][name]
        row['measurement'] = dict(zip(KEYS, fields))
        out[name] = row
    return out


def evaluate_document(doc, variant, revisions):
    """Errors (empty when correct) for one handoff document against the frozen expectation."""
    errors = []
    if not isinstance(doc, dict):
        return ['document is not a JSON object']
    if set(doc) != TOP_KEYS:
        errors.append('top-level keys are ' + ', '.join(sorted(doc)) + ', not exactly ' + ', '.join(sorted(TOP_KEYS)))
    if doc.get('schema') != SCHEMA:
        errors.append(f'schema must be {SCHEMA}')
    if doc.get('workflow') != WORKFLOW:
        errors.append(f'workflow must be {WORKFLOW}')
    if doc.get('evidence') != EVIDENCE:
        errors.append('evidence wording differs')
    if doc.get('physical_validation') != 'not_claimed':
        errors.append('physical_validation must be not_claimed')
    interval = doc.get('acceptance_interval')
    if interval != ACCEPTANCE_INTERVAL:
        errors.append('acceptance interval differs')
    records = doc.get('records')
    if not isinstance(records, list) or [r.get('record') if isinstance(r, dict) else None for r in records] != NAMES:
        return errors + ['records must be A, B, C, D in order']
    want = expected_rows(variant)
    for row in records:
        name = row['record']
        w = want[name]
        data = _source(name, variant)
        source = {'name': name, 'revision': revisions[name], 'sha256': hashlib.sha256(data).hexdigest()}
        if row.get('source') != source:
            errors.append(f'{name}: source binding {row.get("source")} != {source}')
        if row.get('measurement') != w['measurement']:
            errors.append(f'{name}: measurement differs')
        # The frozen record bytes themselves carry the measurement (no invented values).
        if '; '.join(f'{k}={v}' for k, v in (row.get('measurement') or {}).items()).encode('utf-8') != data:
            errors.append(f'{name}: measurement does not reproduce the source record')
        for key in ('interval', 'status', 'missing', 'follow_ups'):
            if row.get(key) != w[key]:
                errors.append(f'{name}: {key} {row.get(key)!r} != {w[key]!r}')
    return errors


def _md_rows(text):
    """({record: cells}, [records with more than one row]); a duplicate row is never resolved by keeping one."""
    rows, duplicates = {}, []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if line.startswith('|') and cells and cells[0] in NAMES:
            if cells[0] in rows and cells[0] not in duplicates:
                duplicates.append(cells[0])
            rows.setdefault(cells[0], cells)
    return rows, duplicates


def evaluate_package(directory, variant, revisions):
    """Errors for a delivered package: handoff.json, handoff.md, their agreement and the manifest's digests."""
    directory = Path(directory)
    try:
        raw = (directory / 'handoff.json').read_bytes()
        doc = json.loads(raw.decode('utf-8'))
        md = (directory / 'handoff.md').read_text(encoding='utf-8')
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return [f'package unreadable: {type(exc).__name__}']
    errors = evaluate_document(doc, variant, revisions)
    if manifest.get('artifacts', {}).get('handoff.json') != hashlib.sha256(raw).hexdigest():
        errors.append('manifest digest of handoff.json differs')
    if manifest.get('artifacts', {}).get('handoff.md') != hashlib.sha256(md.encode('utf-8')).hexdigest():
        errors.append('manifest digest of handoff.md differs')
    if 'physical_validation=not_claimed' not in md or WORDING not in md:
        errors.append('handoff.md lacks the evidence wording')
    rows, duplicates = _md_rows(md)
    want = expected_rows(variant)
    for name in NAMES:
        cells = rows.get(name)
        w = want[name]
        if name in duplicates:
            errors.append(f'{name}: duplicate Markdown row')
            continue
        if cells is None or len(cells) != 10:
            errors.append(f'{name}: no Markdown row')
            continue
        interval = 'unknown' if w['interval'] == 'unknown' else ' to '.join(w['interval'])
        expect = [name, *[w['measurement'][k] for k in KEYS[:5]], interval, w['status'],
                  ', '.join(w['missing']) or 'none']
        if cells[:9] != expect:
            errors.append(f'{name}: Markdown row disagrees: {cells[:9]} != {expect}')
        frozen = hashlib.sha256(_source(name, variant)).hexdigest()
        if cells[9] != f'{name} rev {revisions[name]} sha256:{frozen}':
            errors.append(f'{name}: Markdown source cell {cells[9]!r}')
    items = re.findall(r'^[0-9]+\. (.*)$', md, flags=re.M)
    expect_items = [f"{n}: {f['category']}" + (f" ({f['field']})" if 'field' in f else '')
                    for n in NAMES for f in want[n]['follow_ups']]
    if items != expect_items:
        errors.append('Markdown follow-ups disagree')
    return errors


if __name__ == '__main__':
    found = evaluate_package(sys.argv[1], sys.argv[2], json.loads(sys.argv[3]))
    print(json.dumps({'verified': not found, 'errors': found}, indent=1))
    sys.exit(0 if not found else 1)
