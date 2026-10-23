"""Independent recheck of step 4 candidates against the frozen expected values.

Usage: python bench/step4/recheck.py bench/step4/live2/candidates.jsonl
Each stored model value is judged from the frozen expected.json alone (no executor code): the record and revision come
from the reference text the model saw. Prints every candidate where this verdict and the executor's status disagree.
"""
import json, sys
from pathlib import Path

EXPECTED = json.loads((Path(__file__).parent / 'inspection-handoff-20-v1' / 'expected.json').read_text(encoding='utf-8'))


def record(ref_text):
    """(record letter, revision) whose frozen fields match the reference text."""
    for rev in ('rev2', 'rev1'):
        for name, fields in EXPECTED['fields'][rev].items():
            if f'length={fields[0]}' in ref_text and f'n={fields[2]};' in ref_text and f'method={fields[3]}' in ref_text:
                return name, rev
    raise ValueError(f'no frozen record matches {ref_text!r}')


def expected(job, ref_text):
    name, rev = record(ref_text)
    row = EXPECTED.get(rev, {}).get(name) or EXPECTED['rev1'][name]
    if job.startswith('extract_'):
        return EXPECTED['fields'][rev][name]
    if job.startswith('bounds_'):
        return row['interval']
    if job.startswith('classify_'):
        return row['status']
    raise ValueError(job)


def main(path):
    rows = [json.loads(l) for l in Path(path).read_text(encoding='utf-8').splitlines()]
    disagree = 0
    for r in rows:
        refs = json.loads(r['inputs'])[0]['refs']
        ref_text = json.loads(refs[0])
        right = json.loads(r['value']) == expected(r['job'], ref_text)
        accepted = r['status'] == 'accepted'
        if right != accepted and r['status'] in ('accepted', 'rejected'):
            disagree += 1
            print('DISAGREE', r['run'], r['job'], r['status'], r['value'])
    counts = {}
    for r in rows:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    print(f'{len(rows)} candidates {counts}; independent verdict disagrees with the executor on {disagree}')
    return disagree


if __name__ == '__main__':
    sys.exit(1 if main(sys.argv[1]) else 0)
