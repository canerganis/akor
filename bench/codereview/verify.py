"""Verify the Astra-authored fixtures (codereview-v1) before anything else. Evaluator-only; standard library only.

    python bench/codereview/verify.py            the verification table; exit 0 only when every check passes

Checks, each per file or module:
  bytes      every file equals the latest revision of its block in the authored record
             docs/design/codereview-pilot-2026-10-24/fixtures-as-authored-by-astra.txt (original plus appended revisions),
             UTF-8 without BOM, LF only, exactly one final LF
  sums       SHA256SUMS lists every other fixture file and each digest matches (SHA256SUMS itself is pinned by the freeze)
  suite      every reference module passes its complete reference suite (FIXTURE_IMPLEMENTATION=reference, a fresh
             `python -B -m unittest` process per suite); the shipped result is recorded too, for information
  span       every defective module differs from its reference only inside its seed span, by the seed span rule of
             WITNESS_FORMAT.md (Astra revision 1), implemented once in oracle.edits_inside_span
  witness    every hidden witness is schema-valid, fails on the shipped module and passes on the reference fix, each
             call in a fresh O1 sandbox process (oracle.judge_witness)
  clean      clean controls have no seeds, use the shipped file as reference and have no ref/ copy
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import oracle as O  # noqa: E402

FIX = O.FIX
AUTHORED = ROOT / 'docs' / 'design' / 'codereview-pilot-2026-10-24' / 'fixtures-as-authored-by-astra.txt'
PREFIX = 'fixtures/codereview-v1/'


def authored(with_source: bool = False) -> dict:
    """{relative path: exact bytes} of the latest revision of each file in the authored record. The record is the
    original block list (each 'FILE: fixtures/codereview-v1/<path>' line, an opening fence, the body, a closing fence;
    nothing else) followed by appended revision sections, each opened by a line starting with '=== '. Inside a
    revision section, paths may also carry the 'bench/codereview/' prefix, blank lines may precede the fence and free
    text may stand between blocks. A later block supersedes an earlier one for the same path. Bodies are saved with
    LF endings and exactly one final LF. with_source=True maps each path to (bytes, section title) instead."""
    lines = AUTHORED.read_bytes().replace(b'\r\n', b'\n').decode('utf-8').split('\n')
    files, i, section = {}, 0, 'original'
    while i < len(lines):
        line = lines[i]
        if line.startswith('=== '):
            section = line.strip('= ').strip()
            i += 1
        elif line.startswith('FILE: '):
            path = line[6:]
            if section != 'original' and path.startswith('bench/codereview/'):
                path = path[len('bench/codereview/'):]
            j = i + 1
            while section != 'original' and j < len(lines) and lines[j] == '':
                j += 1
            if not path.startswith(PREFIX) or not lines[j].startswith('```'):
                raise ValueError('unexpected block at line %d' % (i + 1))
            k = j + 1
            while lines[k] != '```':
                k += 1
            data = ('\n'.join(lines[j + 1:k]) + '\n').encode('utf-8')
            files[path[len(PREFIX):]] = (data, section) if with_source else data
            i = k + 1
        elif line == '' or section != 'original':
            i += 1
        else:
            raise ValueError('text outside a file block at line %d' % (i + 1))
    return files


def on_disk() -> dict:
    return {p.relative_to(FIX).as_posix(): p.read_bytes() for p in sorted(FIX.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def byte_problems(data: bytes) -> list:
    out = []
    if data.startswith(b'\xef\xbb\xbf'):
        out.append('BOM')
    if b'\r' in data:
        out.append('CR byte')
    if not data.endswith(b'\n') or data.endswith(b'\n\n'):
        out.append('not exactly one final LF')
    try:
        data.decode('utf-8')
    except UnicodeError:
        out.append('not UTF-8')
    return out


def check_bytes(rows: list) -> None:
    want, have = authored(), on_disk()
    for rel in sorted(set(want) | set(have)):
        if rel not in have:
            rows.append(('bytes', rel, False, 'missing on disk'))
        elif rel not in want:
            rows.append(('bytes', rel, False, 'not in the authored text'))
        else:
            problems = byte_problems(have[rel]) + ([] if have[rel] == want[rel] else ['differs from the authored block'])
            rows.append(('bytes', rel, not problems, '; '.join(problems) or '%d bytes' % len(have[rel])))


def check_sums(rows: list) -> None:
    listed = {}
    for line in (FIX / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        m = re.fullmatch(r'([0-9a-f]{64})  (\S+)', line)
        if not m:
            rows.append(('sums', 'SHA256SUMS', False, 'malformed line ' + line[:60]))
            continue
        listed[m.group(2)] = m.group(1)
    files = {rel for rel in on_disk() if rel != 'SHA256SUMS'}
    for rel in sorted(files | set(listed)):
        if rel not in listed:
            rows.append(('sums', rel, False, 'not listed'))
        elif rel not in files:
            rows.append(('sums', rel, False, 'listed but missing'))
        else:
            got = hashlib.sha256((FIX / rel).read_bytes()).hexdigest()
            rows.append(('sums', rel, got == listed[rel], 'match' if got == listed[rel] else 'digest differs'))


def run_suite(test_file: str, mode: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'FIXTURE_IMPLEMENTATION')}
    env['FIXTURE_IMPLEMENTATION'] = mode
    proc = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p',
                           Path(test_file).name, '-v'], cwd=FIX, env=env, capture_output=True, text=True,
                          encoding='utf-8', timeout=300)
    ran = re.search(r'^Ran (\d+) tests?', proc.stderr, re.M)
    return {'ok': proc.returncode == 0, 'tests': int(ran.group(1)) if ran else 0,
            'tail': proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ''}


def check_suites(rows: list) -> int:
    total = 0
    for m in O.load_key()['modules']:
        ref = run_suite(m['test_file'], 'reference')
        shipped = run_suite(m['test_file'], 'shipped')
        total += ref['tests']
        rows.append(('suite', m['file'], ref['ok'] and ref['tests'] > 0,
                     'reference %s (%d tests); shipped %s' % ('passes' if ref['ok'] else 'FAILS: ' + ref['tail'],
                                                              ref['tests'], 'passes' if shipped['ok'] else 'fails')))
    return total


def check_spans(rows: list) -> None:
    for m in O.load_key()['modules']:
        if not m['seeds']:
            continue
        if len(m['seeds']) != 1:
            rows.append(('span', m['file'], False, 'expected exactly one seed'))
            continue
        span = m['seeds'][0]['span']
        ok, text = O.edits_inside_span(O.source(m['file']), O.source(m['reference_file']), span['start_line'],
                                       span['end_line'])
        rows.append(('span', m['file'], ok, 'seed span %d-%d: %s' % (span['start_line'], span['end_line'], text)))


def check_witnesses(rows: list) -> None:
    for m in O.load_key()['modules']:
        for seed in m['seeds']:
            w = seed['hidden_witness']
            problems = O.validate_witness(w)
            if seed['class'] not in O.CLASSES:
                problems.append('class outside the frozen list')
            if problems:
                rows.append(('witness', '%s %s' % (m['file'], seed['id']), False, '; '.join(problems)))
                continue
            v = O.judge_witness(w, O.source(m['file']), O.source(m['reference_file']))
            show = lambda o: o['outcome'] + (' ' + json.dumps(o.get('value') or o.get('type') or o.get('reason')))
            rows.append(('witness', '%s %s' % (m['file'], seed['id']), v['proven'],
                         'shipped %s (mismatch %s); reference %s (match %s)' % (
                             show(v['shipped']), v['shipped_mismatch'], show(v['reference']), v['reference_matches'])))


def check_clean(rows: list) -> None:
    key = O.load_key()
    packs = {}
    for m in key['modules']:
        packs.setdefault(m['file'].split('/')[0], []).append(m)
        if not m['seeds']:
            ok = m['reference_file'] == m['file'] and not (FIX / 'ref' / m['file']).exists()
            rows.append(('clean', m['file'], ok, 'no seed; reference is the shipped file' if ok else 'not clean'))
    for pack, mods in sorted(packs.items()):
        shape = (len(mods), sum(1 for m in mods if m['seeds']), sum(1 for m in mods if not m['seeds']))
        on = sorted(p.name for p in (FIX / pack).iterdir())
        ok = shape == (3, 2, 1) and on == sorted(Path(m['file']).name for m in mods)
        rows.append(('clean', pack, ok, '%d modules, %d defective, %d clean; directory holds %s' % (*shape, on)))


def verify() -> dict:
    rows = []
    check_bytes(rows)
    check_sums(rows)
    tests = check_suites(rows)
    check_spans(rows)
    check_witnesses(rows)
    check_clean(rows)
    return {'ok': all(r[2] for r in rows), 'rows': rows, 'reference_tests': tests,
            'sha256sums_sha256': hashlib.sha256((FIX / 'SHA256SUMS').read_bytes()).hexdigest()}


def main() -> int:
    res = verify()
    print('check | item | pass | detail')
    for kind, item, ok, detail in res['rows']:
        print(f'{kind} | {item} | {"PASS" if ok else "FAIL"} | {detail}')
    print('reference test methods:', res['reference_tests'])
    print('SHA256SUMS sha256:', res['sha256sums_sha256'])
    print('ALL PASS' if res['ok'] else 'VERIFICATION FAILED')
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
