"""Code-review sizing pilot (docs/design/codereview-pilot-2026-10-24): offline checks of the fixtures, the oracle and
the harness (bench/codereview). No model is called: the caller and the worker are local fixture programs.

    python -m unittest tests.test_codereview_pilot

Witnesses run in the Windows Job Object sandbox of bench/o1, so the oracle and end-to-end classes are Windows-only.
"""
import ast
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
CR = ROOT / 'bench' / 'codereview'
for p in (str(CR), str(ROOT / 'bench' / 'live'), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import oracle as O  # noqa: E402
import pilot as P  # noqa: E402
import verify as V  # noqa: E402

WINDOWS = ('witnesses run in the Windows Job Object sandbox of bench/o1 (bench/o1/sandbox.py refuses when '
           'os.name != "nt")')
KEY = O.load_key()


def seed_finding(file, line=None, cls=None, witness=None):
    m = next(m for m in KEY['modules'] if m['file'] == file)
    s = m['seeds'][0]
    return {'file': file, 'line': s['span']['start_line'] if line is None else line, 'class': cls or s['class'],
            'witness': witness or s['hidden_witness']}


def perfect(pack):
    return {m['file']: [seed_finding(m['file'])] if m['seeds'] else [] for m in O.modules(pack)}


def W(function, args, expected, kwargs=None):
    return {'function': function, 'args': args, 'kwargs': kwargs or {}, 'expected': expected}


def secrets(root=O.FIX):
    """(substrings, whole lines) that must never reach a caller or a worker: the answer key, the reference fixes,
    every hidden witness, the reference files, the oracle's own sources; and every reference-only line."""
    subs = [(root / 'answer_key.json').read_text(encoding='utf-8'), '"classification": "evaluator-only"',
            'reference_fix"', 'hidden_witness"']
    lines = set()
    shipped = {x for m in O.load_key(root)['modules'] for x in O.source(m['file'], root).split('\n')}
    for m in O.load_key(root)['modules']:
        if not m['seeds']:
            continue
        ref = O.source(m['reference_file'], root)
        subs.append(ref)
        lines |= {line for line in ref.split('\n') if line.strip() and line not in shipped}
        for s in m['seeds']:
            subs += [s['reference_fix'], json.dumps(s['hidden_witness'], separators=(',', ':')),
                     json.dumps(s['hidden_witness'])]
    for src in (CR / 'oracle.py', CR / 'eval_worker.py'):
        subs.append(src.read_text(encoding='utf-8').split('\n')[0])
    return subs, lines


def assert_clean(case, text, root=O.FIX, where=''):
    subs, lines = secrets(root)
    for s in subs:
        case.assertNotIn(s, text, where)
    present = set(text.split('\n'))
    case.assertEqual(lines & present, set(), where)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


class SpanAndSchemaTests(unittest.TestCase):
    def test_strict_json(self):
        for bad in ('{"a":1,"a":2}', '[NaN]', '[Infinity]', '[-Infinity]', '[1e400]'):
            with self.assertRaises(ValueError, msg=bad):
                O.strict_json(bad)
        self.assertEqual(O.strict_json(' [1, 2.5, {"a": null}] '), [1, 2.5, {'a': None}])

    def test_finding_schema(self):
        good = seed_finding('packA/paging.py')
        self.assertEqual(O.validate_finding(good, 'packA/paging.py', 65), [])
        cases = [dict(good, extra=1), dict(good, line=True), dict(good, line=0), dict(good, line=66),
                 dict(good, line=36.0), dict(good, **{'class': 'wrong_comparison'}), dict(good, file='packA/x.py'),
                 dict(good, witness=dict(good['witness'], function='_checked')),
                 dict(good, witness=dict(good['witness'], function='m.get_page')),
                 dict(good, witness=dict(good['witness'], kwargs={'_x': 1})),
                 dict(good, witness=dict(good['witness'], expected={'return': 1, 'exception': 'ValueError'})),
                 dict(good, witness=dict(good['witness'], expected={'exception': 'RuntimeError'})),
                 dict(good, witness=dict(good['witness'], args={}))]
        for case in cases:
            self.assertTrue(O.validate_finding(case, 'packA/paging.py', 65), case)

    def test_exact_type_equality(self):
        self.assertTrue(O.equal(1, ['i', '1']))
        self.assertFalse(O.equal(1, ['f', '1.0']))
        self.assertFalse(O.equal(1.0, ['i', '1']))
        self.assertFalse(O.equal(True, ['i', '1']))
        self.assertFalse(O.equal(1, ['b', True]))
        self.assertFalse(O.equal([1], ['t', [['i', '1']]]))
        self.assertTrue(O.equal(0.0, ['f', '-0.0']))
        self.assertTrue(O.equal({'b': [1], 'a': None}, ['d', [['a', ['n']], ['b', ['l', [['i', '1']]]]]]))
        self.assertFalse(O.equal({'a': None}, ['d', [['a', ['n']], ['b', ['n']]]]))
        self.assertFalse(O.equal(1.0, ['f', 'nan']))

    def test_seed_span_rule_as_written(self):
        shipped = 'a\nb\nc\nd\ne\n'
        ins = lambda k: '\n'.join(shipped.split('\n')[:k] + ['X'] + shipped.split('\n')[k:])
        # span 3-4: insertions after k lines are inside exactly when 2 <= k <= 4
        self.assertEqual([O.edits_inside_span(shipped, ins(k), 3, 4)[0] for k in range(6)],
                         [False, False, True, True, True, False])
        self.assertTrue(O.edits_inside_span(shipped, 'a\nb\nC\nd\ne\n', 3, 4)[0])
        self.assertFalse(O.edits_inside_span(shipped, 'a\nB\nc\nd\ne\n', 3, 4)[0])
        self.assertFalse(O.edits_inside_span(shipped, 'a\nb\nd\ne\n', 4, 4)[0])   # deletes line 3
        self.assertFalse(O.edits_inside_span(shipped, shipped, 3, 4)[0])         # no edit at all
        self.assertTrue(O.in_span(25, {'start_line': 25, 'end_line': 26}))
        self.assertFalse(O.in_span(27, {'start_line': 25, 'end_line': 26}))

    def test_evaluator_imports_no_executor_code(self):
        allowed = {'__future__', 'ast', 'builtins', 'copy', 'difflib', 'hashlib', 'importlib', 'inspect',
                   'itertools', 'json', 'keyword', 'math', 'os', 'pathlib', 'sys', 're', 'subprocess'}
        for name in ('oracle.py', 'eval_worker.py', 'verify.py'):
            tree = ast.parse((CR / name).read_text(encoding='utf-8'))
            found = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found |= {a.name.split('.')[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom):
                    found.add(node.module.split('.')[0])
            self.assertEqual(found - allowed - {'sandbox', 'oracle'}, set(), name)
        self.assertEqual(O.norm_sha(O.SANDBOX_FILE), O.SANDBOX_SHA256)

    def test_authored_record_resolves_latest_revision(self):
        files = V.authored(with_source=True)
        self.assertEqual(files['answer_key.json'][1], 'Astra revision 1 (2026-10-24)')
        self.assertEqual(files['SHA256SUMS'][1], 'Claude regeneration for Astra revision 2 (2026-10-24)')
        self.assertEqual(files['DOMAINS.md'][1], 'Astra revision 2 (2026-10-24)')
        self.assertEqual(files['DOMAINS.md'][0], (O.FIX / 'DOMAINS.md').read_bytes())
        self.assertEqual(files['packA/paging.py'][1], 'original')
        span = next(m for m in KEY['modules'] if m['file'] == 'packA/sample_stats.py')['seeds'][0]['span']
        self.assertEqual(span, {'start_line': 25, 'end_line': 26})


@unittest.skipUnless(os.name == 'nt', WINDOWS)
class OracleTests(unittest.TestCase):
    def score(self, answer, pack, **kw):
        return O.score(answer if isinstance(answer, str) else json.dumps(answer), pack, **kw)

    def test_fixture_verification_passes(self):
        res = V.verify()
        self.assertTrue(res['ok'], [r for r in res['rows'] if not r[2]])
        self.assertEqual(res['reference_tests'], 24)

    def test_perfect_answers(self):
        for pack in 'AB':
            s = self.score(perfect(pack), pack)
            self.assertEqual((s['answer_ok'], s['correct_files'], s['recall'], s['false_positives'], s['unproven']),
                             (True, 3, 1.0, 0, 0), s)

    def test_each_category_scores_as_the_rules_say(self):
        a = perfect('A')
        a['packA/paging.py'] = [seed_finding('packA/paging.py', line=35)]                       # mislocated
        a['packA/sample_stats.py'] = [seed_finding('packA/sample_stats.py', line=26),           # seeded (span end)
                                      seed_finding('packA/sample_stats.py', line=25,
                                                   witness=W('describe', [[]], {'return': {
                                                       'count': 0, 'mean': None, 'spread': None}})),  # same seed
                                      seed_finding('packA/sample_stats.py', line=30,
                                                   witness=W('spread', [[1, 2, 6]], {'return': 5.0}))]  # unproven
        a['packA/labels.py'] = [{'file': 'packA/labels.py', 'line': 10, 'class': 'missing_guard',
                                 'witness': W('slug', [''], {'return': ''})}]                   # clean FP (both fail)
        s = self.score(a, 'A')
        f = s['files']
        self.assertEqual([x['category'] for x in f['packA/paging.py']['findings']], ['mislocated'])
        self.assertFalse(f['packA/paging.py']['correct'])
        self.assertEqual([x['category'] for x in f['packA/sample_stats.py']['findings']],
                         ['seeded', 'seeded', 'unproven'])
        self.assertTrue(f['packA/sample_stats.py']['correct'])   # proven findings equal the seed set (02 section 4)
        self.assertEqual(f['packA/labels.py']['findings'][0]['category'], 'unproven')
        self.assertEqual(f['packA/labels.py']['review_both_fail'], 1)
        self.assertFalse(f['packA/labels.py']['correct'])
        self.assertEqual((s['correct_files'], s['seeds_hit'], s['false_positives'], s['unproven'], s['mislocated']),
                         (1, 1, 3, 2, 1))

    def test_wrong_class_and_line_outside_span(self):
        b = perfect('B')
        b['packB/ranges.py'] = [seed_finding('packB/ranges.py', cls='missing_guard')]
        b['packB/rotation.py'] = [seed_finding('packB/rotation.py', line=14)]   # borders the insertion boundary
        s = self.score(b, 'B')
        self.assertEqual(s['mislocated'], 2)
        self.assertEqual(s['correct_files'], 1)

    def test_unseeded_needs_a_registered_fix(self):
        b = perfect('B')
        b['packB/settings.py'] = [{'file': 'packB/settings.py', 'line': 60, 'class': 'missing_guard',
                                   'witness': W('select_prefix', [{'a': '1'}, ''], {'return': {}})}]
        s = self.score(b, 'B')
        self.assertEqual((s['files']['packB/settings.py']['correct'], s['false_positives'], s['review_both_fail']),
                         (False, 1, 1))
        fix = O.source('packB/settings.py').replace('return {key: value', 'if not prefix:\n        return {}\n'
                                                     '    return {key: value')
        s = self.score(b, 'B', fixes={'packB/settings.py': fix})
        self.assertEqual((s['files']['packB/settings.py']['correct'], s['false_positives'], s['unseeded']),
                         (True, 0, 1))

    def test_answer_shapes(self):
        good = json.dumps(perfect('A'))
        for text in ('```json\n' + good + '\n```', 'Here: ' + good, '', '[]', json.dumps(dict(perfect('A'), x=[]))):
            s = O.score(text, 'A')
            self.assertFalse(s['answer_ok'], text[:30])
            self.assertEqual(s['correct_files'], 0)
        nulls = dict(perfect('A'), **{'packA/labels.py': None, 'packA/paging.py': [{'file': 'packA/paging.py'}]})
        s = self.score(nulls, 'A')
        self.assertEqual((s['files']['packA/labels.py']['response'], s['invalid'], s['correct_files']), ('null', 1, 1))

    def test_judgment_is_bound_to_its_own_pack(self):
        """The pilot_k cross-seed bug: an answer judged against another workload. Here the pack is an explicit
        argument, the answer keys are that pack's module paths, and nothing is read from module state."""
        s = self.score(perfect('A'), 'B')
        self.assertFalse(s['answer_ok'])
        self.assertEqual(s['correct_files'], 0)
        self.score(perfect('B'), 'B')
        self.assertEqual(self.score(perfect('A'), 'A')['correct_files'], 3)
        with self.assertRaises(ValueError):
            O.modules('C')

    def test_timeouts_and_errors_never_prove(self):
        loop = 'def spin(n):\n    while True:\n        n += 1\n'
        out = O.run_call(loop, W('spin', [1], {'return': 1}))
        self.assertEqual(out['outcome'], 'error')
        io_src = 'def peek(p):\n    return open(p).read()\n'
        self.assertEqual(O.run_call(io_src, W('peek', ['x'], {'return': ''}))['outcome'], 'error')
        unbound = O.run_call('def f(a):\n    return a\n', W('f', [1, 2], {'exception': 'TypeError'}))
        self.assertEqual(unbound['outcome'], 'error')
        v = O.judge_witness(W('spin', [1], {'return': 1}), loop, 'def spin(n):\n    return n\n')
        self.assertFalse(v['proven'])


class FillAndPromptTests(unittest.TestCase):
    def test_fill_is_pinned_rebuildable_and_sized(self):
        data = P.FILL_FILE.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), P.FILL_SHA256)
        self.assertEqual(P.build_fill(), data)
        self.assertTrue(5500 <= P.fill_tokens() <= 6500, P.fill_tokens())

    def test_fill_screen(self):
        self.assertEqual(P.screen(P.fill_text()), [])
        planted = ['x = get_page(items, 1, 2)', 'off_by_one', '    stop = start + page_size - 1',
                   'the answer_key.json file', 'compact_ranges([[1, 2]])']
        for text in planted:
            self.assertTrue(P.screen('harmless prose\n' + text + '\n'), text)

    def test_arms_differ_by_exactly_the_requirement_line(self):
        for pack in 'AB':
            i, d = P.prompt(pack, 'I').encode('utf-8'), P.prompt(pack, 'D').encode('utf-8')
            li, ld = i.split(b'\n'), d.split(b'\n')
            self.assertEqual(len(li), len(ld))
            diff = [n for n, (x, y) in enumerate(zip(li, ld)) if x != y]
            self.assertEqual(len(diff), 1)
            self.assertEqual(li[diff[0]], P.REQUIREMENT['I'].encode('utf-8'))
            self.assertEqual(ld[diff[0]], P.REQUIREMENT['D'].encode('utf-8'))
            prefix = (P.FILL_HEAD + P.fill_text() + P.FILL_TAIL).encode('utf-8')
            self.assertTrue(i.startswith(prefix) and d.startswith(prefix))
            self.assertEqual(i.count(P.OZ_SNIPPET.encode('utf-8')), 1)
            self.assertEqual(d.count(P.OZ_SNIPPET.encode('utf-8')), 1)
            for module in P.PACKS[pack]:
                self.assertIn(module, P.task_text(pack, 'I'))

    def test_prompts_carry_no_answer_and_no_repo_path(self):
        for pack in 'AB':
            for arm in 'ID':
                text = P.prompt(pack, arm)
                assert_clean(self, text)
                self.assertNotIn(str(ROOT).lower(), text.lower())
                self.assertNotIn('codereview', text)

    def test_specs_are_deterministic_and_bound_to_pack(self):
        a, b = P.build_spec('A', 'I'), P.build_spec('A', 'I')
        self.assertEqual(a['input_sha256'], b['input_sha256'])
        self.assertNotEqual(a['input_sha256'], P.build_spec('B', 'I')['input_sha256'])
        self.assertEqual(sorted(a['files']), sorted(P.PACKS['A'] + ('WITNESS_FORMAT.md',)))
        for rel, data in a['files'].items():
            self.assertEqual(data, (O.FIX / rel).read_bytes())
            self.assertNotIn(b'\r', data)

    def test_findings_sized_against_the_inline_limit(self):
        s = P.sizing()
        self.assertLessEqual(s['largest_expected_bytes'], 4096)
        self.assertGreaterEqual(s['findings_that_fit_inline'], 10)
        self.assertFalse(s['artifact_read_turn_expected'])


class AdmissionTests(unittest.TestCase):
    def state(self, attempts=(), records=(), quota=()):
        return {'attempts': list(attempts), 'records': {r['attempt']: r for r in records},
                'quota': {q['attempt']: q['after_percent'] for q in quota}}

    def test_first_run_projection(self):
        a = P.admission(self.state(), '46')
        self.assertTrue(a['admitted'], a)
        self.assertAlmostEqual(a['projection'], 46 + 2 * P.RUN_RESERVE / 55000 + 1)

    def test_refusals(self):
        edge = 58 - 1 - 2 * P.RUN_RESERVE / 55000             # 53.36: the full run reserve must fit
        self.assertFalse(P.admission(self.state(), str(round(edge + 0.01, 2)))['admitted'])
        self.assertTrue(P.admission(self.state(), str(round(edge - 0.01, 2)))['admitted'])
        self.assertFalse(P.admission(self.state(), None)['admitted'])
        self.assertFalse(P.admission(self.state(), 'about 46')['admitted'])
        run = {'attempt': 'A-I#1', 'tag': 'A-I', 'admitted': True, 'quota_before': 46.0}
        unsettled = self.state([run])
        self.assertIn('unsettled', ' '.join(P.admission(unsettled, '47')['reasons']))
        rec = {'attempt': 'A-I#1', 'charged_tokens': 60000}
        settled = self.state([run], [rec], [{'attempt': 'A-I#1', 'after_percent': 47.0}])
        self.assertTrue(P.admission(settled, '47')['admitted'])
        runs = [dict(run, attempt=f'X#{n}') for n in range(4)]
        heavy = self.state(runs, [{'attempt': f'X#{n}', 'charged_tokens': 50000} for n in range(4)],
                           [{'attempt': f'X#{n}', 'after_percent': 46.0} for n in range(4)])
        a = P.admission(heavy, '46')
        self.assertFalse(a['admitted'])
        self.assertIn('total cap', ' '.join(a['reasons']))

    def test_factor_rises_with_observed_movement_and_never_falls(self):
        run = {'attempt': 'A-I#1', 'tag': 'A-I', 'admitted': True, 'quota_before': 46.0}
        rec = {'attempt': 'A-I#1', 'charged_tokens': 30000, 'accounting_complete': True, 'total_tokens': 30000}
        fast = self.state([run], [rec], [{'attempt': 'A-I#1', 'after_percent': 49.0}])
        a = P.admission(fast, '49')
        self.assertAlmostEqual(a['factor'], 3 / 30000)
        self.assertAlmostEqual(a['projection'], 49 + 3 / 30000 * P.RUN_RESERVE + 1)
        self.assertFalse(a['admitted'])
        flat = self.state([run], [rec], [{'attempt': 'A-I#1', 'after_percent': 46.0}])
        self.assertAlmostEqual(P.admission(flat, '46')['factor'], 2 / 55000)


class ProtocolTests(unittest.TestCase):
    def test_module_content_detector(self):
        spec = P.build_spec('B', 'D')
        text = O.source('packB/ranges.py')
        self.assertTrue(P.shows_modules(spec, text))
        numbered = ''.join('%6d\t%s\n' % (n + 1, l) for n, l in enumerate(text.split('\n')))
        self.assertTrue(P.shows_modules(spec, numbered))
        self.assertFalse(P.shows_modules(spec, json.dumps(perfect('B'))))
        self.assertFalse(P.shows_modules(spec, (O.FIX / 'WITNESS_FORMAT.md').read_text(encoding='utf-8')))

    def test_isolation_tripwire(self):
        self.assertTrue(P.breaches_in(['cat ' + str(ROOT / 'bench' / 'codereview' / 'oracle.py')], []))
        self.assertTrue(P.breaches_in(['find / -name answer_key.json'], []))
        self.assertTrue(P.breaches_in([], ['Replace stop = start + page_size - 1 with stop = start + page_size.']))
        self.assertFalse(P.breaches_in(['cat WITNESS_FORMAT.md'], [(O.FIX / 'WITNESS_FORMAT.md').read_text(
            encoding='utf-8')]))

    def test_tripwire_covers_home_and_session_stores(self):
        """Second layer for routes outside the run root: the home directory (Claude's own session transcripts and
        project list live there) and any extracted answer-key structure in a tool result."""
        home = Path(os.path.expanduser('~'))
        run_root = Path(tempfile.gettempdir()) / 'cr-x'
        for text in ('cat ~/.claude.json', 'ls $HOME', 'cat "%s"' % (home / '.claude' / 'projects'),
                     'grep -r witness /c/Users', 'python -c "import glob; print(glob.glob(\'C:/**/*.json\'))"'):
            self.assertTrue(P.breaches_in([text], [], run_root), text)
        for text in ('cat %s' % (run_root / 'ws' / 'WITNESS_FORMAT.md'), 'cat packA/paging.py', 'ls -la'):
            self.assertFalse(P.breaches_in([text], [], run_root), text)
        leaked = json.dumps({'span': {'start_line': 36, 'end_line': 36}})
        self.assertTrue(P.breaches_in([], [leaked], run_root))
        self.assertTrue(P.breaches_in([], [leaked.replace('"', '\\"')], run_root))


class DomainTests(unittest.TestCase):
    """Fix 3: witnesses must stay inside each function's documented domain (WITNESS_FORMAT.md)."""

    def test_hidden_witnesses_are_in_domain(self):
        for m in KEY['modules']:
            for s in m['seeds']:
                self.assertEqual(O.domain_problems(m['file'], s['hidden_witness']), [], s['id'])

    def test_out_of_domain_inputs_are_rejected(self):
        cases = [('packB/rotation.py', W('rotate_left', [[], True], {'return': []})),
                 ('packB/rotation.py', W('chunk_tasks', [[1], 0], {'return': []})),
                 ('packA/paging.py', W('get_page', [['a'], False, 2], {'return': ['a']})),
                 ('packA/paging.py', W('page_count', [3, 0], {'return': 0})),
                 ('packA/sample_stats.py', W('mean', [[True]], {'return': 1.0})),
                 ('packA/sample_stats.py', W('latest', [[1], -1], {'return': []})),
                 ('packB/ranges.py', W('compact_ranges', [[[2, 1]]], {'return': []})),
                 ('packB/ranges.py', W('contains', [[[1, 2]], True], {'return': True})),
                 ('packB/settings.py', W('render_settings', [{'a': ' x'}], {'return': 'a= x\n'})),
                 ('packA/labels.py', W('slug', [3], {'return': '3'})),
                 ('packA/labels.py', W('nope', [], {'return': None}))]
        for file, w in cases:
            self.assertTrue(O.domain_problems(file, w), (file, w))

    def test_documented_rejections_stay_allowed(self):
        self.assertEqual(O.domain_problems('packA/sample_stats.py',
                                           W('mean', [[2000000]], {'exception': 'ValueError'})), [])
        self.assertTrue(O.domain_problems('packA/sample_stats.py', W('mean', [[2000000]], {'return': None})))
        self.assertEqual(O.domain_problems('packA/paging.py', W('page_label', [3, 7, 3],
                                                                {'exception': 'ValueError'})), [])

    def test_live_runs_refuse_while_the_domain_spec_is_provisional(self):
        if O.DOMAIN_STATUS == 'frozen':
            self.skipTest('the domain specification is frozen')
        out = Path(tempfile.mkdtemp(prefix='crd-'))
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(P.counted(P.manifest()[0], '46', out=out), 2)
        self.assertFalse((out / 'attempts.jsonl').exists())

    def test_the_specification_is_astras_frozen_domains_file(self):
        """Revision 2: the classifier is the executable block of DOMAINS.md, pinned by SHA256SUMS, run as written."""
        self.assertEqual(O.DOMAIN_STATUS, 'frozen')
        sums = (O.FIX / 'SHA256SUMS').read_text(encoding='utf-8')
        self.assertIn(hashlib.sha256((O.FIX / 'DOMAINS.md').read_bytes()).hexdigest() + '  DOMAINS.md', sums)
        block = re.search(r'^```python\n(.*?)^```$', (O.FIX / 'DOMAINS.md').read_text(encoding='utf-8'),
                          re.S | re.M).group(1)
        self.assertEqual(O.domain_spec()['source'], block)
        self.assertEqual(O.domain_spec()['classify'].__code__.co_filename, 'DOMAINS.md')

    def test_the_spec_names_every_public_function_with_its_real_signature(self):
        self.assertEqual(V.signature_problems(), [])

    def test_each_domain_kind_per_domains_md(self):
        allowed = [('packA/sample_stats.py', W('mean', [[1000000]], {'return': 1000000.0})),
                   ('packA/sample_stats.py', W('latest', [[2000000], 0], {'exception': 'ValueError'})),
                   ('packA/paging.py', W('page_label', [0, 0, 3], {'exception': 'ValueError'})),
                   ('packA/labels.py', W('make_header', [['a'], '::'], {'exception': 'ValueError'})),
                   ('packA/labels.py', W('make_header', [['a']], {'return': 'a'})),
                   ('packB/ranges.py', W('compact_ranges', [[[]]], {'exception': 'ValueError'})),
                   ('packB/rotation.py', W('rotation_order', [[], 3], {'return': []})),
                   ('packB/rotation.py', W('assign_tasks', [[], []], {'exception': 'ValueError'})),
                   ('packB/settings.py', W('render_settings', [{'a-b': 'x'}], {'exception': 'ValueError'})),
                   ('packB/settings.py', W('parse_settings', ['broken'], {'exception': 'ValueError'})),
                   ('packB/settings.py', W('select_prefix', [{'a': ' x\n'}, ' '], {'return': {}}))]
        for file, w in allowed:
            self.assertEqual(O.domain_problems(file, w), [], (file, w))
        refused = [('packA/paging.py', W('page_label', [3, 7, 3], {'exception': 'IndexError'})),
                   ('packA/paging.py', W('get_page', [['a'], 0, 2.0], {'return': ['a']})),
                   ('packA/paging.py', W('get_page', [['a'], 0, -1], {'exception': 'TypeError'})),
                   ('packA/labels.py', W('make_header', [['a'], 5], {'exception': 'ValueError'})),
                   ('packB/ranges.py', W('compact_ranges', [[[True, 2]]], {'exception': 'ValueError'})),
                   ('packB/settings.py', W('overlay', [{'a-b': 'x'}, {}], {'return': {'a-b': 'x'}})),
                   ('packB/settings.py', {'function': 'parse_settings', 'args': [],
                                          'kwargs': {'text': 'x', 'extra': 1}, 'expected': {'return': {}}})]
        for file, w in refused:
            self.assertTrue(O.domain_problems(file, w), (file, w))

    @unittest.skipUnless(os.name == 'nt', WINDOWS)
    def test_the_acknowledged_overflow_limitation(self):
        """DOMAINS.md, Compatibility limitation: a sample beyond float range is a ValueError rejection, yet both
        implementations raise OverflowError, so such a witness is admissible but can never be proven."""
        w = W('mean', [[10 ** 400]], {'exception': 'ValueError'})
        self.assertEqual(O.domain_problems('packA/sample_stats.py', w), [])
        v = O.judge_witness(w, O.source('packA/sample_stats.py'), O.source('ref/packA/sample_stats.py'))
        self.assertEqual((v['reference']['type'], v['proven']), ('OverflowError', False))

    @unittest.skipUnless(os.name == 'nt', WINDOWS)
    def test_reference_behaviour_conforms_to_the_spec(self):
        res = V.conformance()
        self.assertEqual(res['contradictions'], [], res['contradictions'][:5])
        self.assertGreater(res['calls'], 1000)
        self.assertTrue(res['acknowledged'])


class GuardTests(unittest.TestCase):
    """Fix 1: no further paid call once it could cross the run cap; admission reserves the overshoot."""

    def msg(self, ctx, out, tools=1):
        return {'input_tokens': ctx, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0,
                'output_tokens': out, 'tool_uses': tools}

    def test_next_call_bound(self):
        self.assertEqual(P.next_call_bound(self.msg(12000, 500, 1)), 12000 + 500 + P.TOOL_ALLOW + P.OUT_ALLOW)
        self.assertEqual(P.next_call_bound(self.msg(12000, 500, 2)), 12000 + 500 + 2 * P.TOOL_ALLOW + P.OUT_ALLOW)
        self.assertEqual(P.next_call_bound(self.msg(12000, 500, 0)), 0)   # final message: no next call

    def test_guard_decision(self):
        ok = P.guard_decision([self.msg(12000, 500)], worker_tokens=0)
        self.assertIsNone(ok)
        self.assertEqual(P.guard_decision([self.msg(20000, 500), self.msg(22000, 500)], worker_tokens=0), 'cap')
        self.assertEqual(P.guard_decision([self.msg(5000, 100)], worker_tokens=40000), 'cap')
        five = [self.msg(1000, 10)] * 5
        self.assertEqual(P.guard_decision(five, worker_tokens=0), 'turns')
        self.assertIsNone(P.guard_decision([self.msg(1000, 10)] * 4 + [self.msg(1000, 10, 0)], worker_tokens=0))

    def test_admission_reserves_the_race(self):
        self.assertEqual(P.RUN_RESERVE, P.RUN_CAP + P.RACE)
        run = {'attempt': 'X#1', 'tag': 'A-I', 'admitted': True, 'quota_before': 46.0}
        st = lambda spent: {'attempts': [run], 'records': {'X#1': {'charged_tokens': spent}},
                            'quota': {'X#1': 46.0}}
        self.assertTrue(P.admission(st(P.TOTAL_CAP - P.RUN_RESERVE), '46')['admitted'])
        self.assertFalse(P.admission(st(P.TOTAL_CAP - P.RUN_RESERVE + 1), '46')['admitted'])

    def test_incomplete_runs_are_charged_the_hard_bound(self):
        self.assertEqual(P.charge(None, 30000), P.RUN_RESERVE)
        self.assertEqual(P.charge(None, 150000), 150000)
        self.assertEqual(P.charge(41000, 41000), 41000)

    def test_missing_or_malformed_caller_usage_stops(self):
        """Review 2, finding 1: unknown spend is never read as zero; the guard stops at once."""
        full = {'input_tokens': 10, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0,
                'output_tokens': 5}
        self.assertEqual(P.strict_message_usage(full), full)
        for bad in (None, {}, dict(full, output_tokens=None), dict(full, input_tokens=True),
                    dict(full, cache_read_input_tokens=-1), dict(full, input_tokens=1.5),
                    {k: v for k, v in full.items() if k != 'cache_creation_input_tokens'}):
            self.assertIsNone(P.strict_message_usage(bad), bad)
        unknown = dict(self.msg(1000, 10), usage_unknown=True)
        self.assertEqual(P.guard_decision([unknown], worker_tokens=0), 'usage')
        self.assertEqual(P.guard_decision([self.msg(1000, 10)], worker_tokens=None), 'usage')
        self.assertEqual(P.guard_decision([], worker_tokens=None), 'usage')

    def test_guard_stops_at_the_first_message_over_the_cap(self):
        under = [self.msg(30000, 0, 0), self.msg(P.RUN_CAP - 30000 - 1, 0, 0)]
        self.assertIsNone(P.guard_decision(under, worker_tokens=0))
        over = [self.msg(30000, 0, 0), self.msg(P.RUN_CAP - 30000, 0, 0)]
        self.assertEqual(P.guard_decision(over, worker_tokens=0), 'cap')
        self.assertEqual(P.guard_decision([self.msg(1000, 0, 0)], worker_tokens=P.RUN_CAP - 1000), 'cap')

    def test_worker_sources_are_strict_in_the_live_guard(self):
        tmp = Path(tempfile.mkdtemp(prefix='crg-'))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ledger = tmp / 'ws' / 'do' / 'h1' / 'calls.jsonl'
        ledger.parent.mkdir(parents=True)
        end = lambda u: json.dumps({'event': 'call_end', 'usage': {'raw': u}}) + '\n'
        raw = {'input_tokens': 700, 'cached_input_tokens': 0, 'cache_creation_input_tokens': 0, 'output_tokens': 30}
        ledger.write_text(json.dumps({'event': 'call_start'}) + '\n' + end(raw)
                          + '{"event": "call_e', encoding='utf-8')            # unterminated line: still being written
        self.assertEqual(P.ledger_tokens(tmp / 'ws'), 730)
        for bad in (None, {'input_tokens': 700}, {'input_tokens': 700, 'output_tokens': None}):
            ledger.write_text(end(bad), encoding='utf-8')
            self.assertIsNone(P.ledger_tokens(tmp / 'ws'), bad)
        ledger.write_text('not json\n', encoding='utf-8')
        self.assertIsNone(P.ledger_tokens(tmp / 'ws'))
        env = tmp / 'envelopes'
        env.mkdir()
        counters = {'inputTokens': 100, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0, 'outputTokens': 9}
        (env / '0000.json').write_text(json.dumps({'modelUsage': {'m': counters}}), encoding='utf-8')
        (env / '0001.json').write_text('', encoding='utf-8')                  # reserved name, call in flight
        self.assertEqual(P.envelope_tokens(env), 109)
        (env / '0002.json').write_text(json.dumps({'modelUsage': {'m': {'inputTokens': 100}}}), encoding='utf-8')
        self.assertIsNone(P.envelope_tokens(env))
        self.assertEqual(P.envelope_tokens(tmp / 'missing'), 0)

    def test_output_allowance_rests_on_the_measured_maximum(self):
        """claude -p (2.1.306) has no output limit, so the allowances are margins over the largest single-call
        output of claude-sonnet-5-5 recorded in this repository, never claimed as enforced bounds."""
        rows = []
        for path in sorted((ROOT / 'bench' / 'live' / 'data').glob('*.jsonl')):
            for line in path.read_text(encoding='utf-8').splitlines():
                r = json.loads(line) if line.strip() else {}
                if r.get('model') == 'claude-sonnet-5-5' and type(r.get('out')) is int and not r.get('spawns'):
                    rows.append(r['out'])
        self.assertGreater(len(rows), 500)
        self.assertEqual(max(rows), P.MEASURED_OUT_MAX)
        self.assertGreaterEqual(P.OUT_ALLOW, 2 * P.MEASURED_OUT_MAX)
        self.assertGreaterEqual(P.WORKER_OUT_ALLOW, 2 * P.MEASURED_OUT_MAX)
        self.assertEqual(P.RACE, P.RACE_CONTEXT + P.TOOL_ALLOW + P.OUT_ALLOW)
        self.assertEqual(P.RUN_RESERVE, P.RUN_CAP + P.RACE)

    @unittest.skipUnless(os.name == 'nt', WINDOWS)
    def test_adapter_refuses_and_stops_on_unknown_spend(self):
        """Review 2, finding 1, adapter side: a malformed earlier envelope, an unreadable guard state or a request
        whose size cannot be bounded refuses the launch and sets STOP; a call that returns without known usage
        sets STOP so nothing further is launched."""
        tmp = Path(tempfile.mkdtemp(prefix='crg-'))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        marker = tmp / 'launched'
        good = tmp / 'good.py'
        good.write_text('import json, os\nopen(%r, "w").write("x")\nopen(os.environ["OZ_ENVELOPE_PATH"], "w")'
                        '.write(json.dumps({"modelUsage": {"m": {"inputTokens": 5, "cacheReadInputTokens": 0, '
                        '"cacheCreationInputTokens": 0, "outputTokens": 1}}}))\nprint("{}")\n' % str(marker),
                        encoding='utf-8')
        silent = tmp / 'silent.py'
        silent.write_text('open(%r, "w").write("x")\nprint("{}")\n' % str(marker), encoding='utf-8')
        request = json.dumps({'system': 's', 'prompt': 'p'}).encode()
        run_ok = {'caller_tokens': 1000, 'cap': P.RUN_CAP, 'worker_out': P.WORKER_OUT_ALLOW}
        bad_env = json.dumps({'modelUsage': {'m': {'inputTokens': 70000}}})
        cases = [('malformed envelope', run_ok, bad_env, request, good, True),
                 ('bad guard state', dict(run_ok, caller_tokens=None), None, request, good, True),
                 ('unbounded request', run_ok, None, b'[1, 2]', good, True),
                 ('no usage returned', run_ok, None, request, silent, False),
                 ('clean call', run_ok, None, request, good, False)]
        for n, (name, run, earlier, req, delegate, refused) in enumerate(cases):
            state, arc = tmp / f'state{n}', tmp / f'arc{n}'
            state.mkdir()
            (state / 'run.json').write_text(json.dumps(run), encoding='utf-8')
            if earlier:
                (arc / 'envelopes').mkdir(parents=True)
                (arc / 'envelopes' / '0000.json').write_text(earlier, encoding='utf-8')
            marker.unlink(missing_ok=True)
            subprocess.run([sys.executable, str(CR / 'cr_adapter.py'), '--archive', str(arc), '--state', str(state),
                            '--', sys.executable, str(delegate)], input=req, capture_output=True)
            self.assertEqual(marker.exists(), not refused, name)
            self.assertEqual((state / 'STOP').exists(), name != 'clean call', name)

    @unittest.skipUnless(os.name == 'nt', WINDOWS)
    def test_worker_call_refused_before_launch(self):
        tmp = Path(tempfile.mkdtemp(prefix='crg-'))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        marker = tmp / 'launched'
        delegate = tmp / 'delegate.py'
        delegate.write_text('open(%r, "w").write("x")\nprint("{}")\n' % str(marker), encoding='utf-8')
        state = tmp / 'state'
        state.mkdir()
        request = json.dumps({'system': 's' * 100, 'prompt': 'p' * 4000, 'ids': ['a']}).encode()
        cases = [({'caller_tokens': 50000}, False, True), ({'caller_tokens': 1000}, True, True),
                 ({'caller_tokens': 1000}, False, False)]
        for n, (st, stop, refused) in enumerate(cases):
            (state / 'run.json').write_text(json.dumps(dict(st, cap=P.RUN_CAP, worker_out=P.WORKER_OUT_ALLOW)))
            (state / 'STOP').unlink(missing_ok=True)
            if stop:
                (state / 'STOP').write_text('stop')
            marker.unlink(missing_ok=True)
            arc = tmp / f'arc{n}'
            proc = subprocess.run([sys.executable, str(CR / 'cr_adapter.py'), '--archive', str(arc), '--state',
                                   str(state), '--', sys.executable, str(delegate)], input=request,
                                  capture_output=True)
            self.assertEqual(marker.exists(), not refused, (st, stop))
            if refused:
                out = json.loads(proc.stdout)
                self.assertEqual(out['usage'], {'input_tokens': 0, 'cached_input_tokens': 0,
                                                'cache_creation_input_tokens': 0, 'output_tokens': 0})
                row = json.loads((arc / 'packets.jsonl').read_text(encoding='utf-8').splitlines()[0])
                self.assertTrue(row['refused_by_guard'])


class AccountingTests(unittest.TestCase):
    """Fix 4: a missing modelUsage counter is never read as zero; per-message usage is a reported lower bound."""

    def stream(self, model_usage, per_message=(1000, 0, 0, 200)):
        events = [{'type': 'assistant', 'message': {'id': 'm1', 'content': [{'type': 'text', 'text': '{}'}],
                                                    'usage': dict(zip(('input_tokens', 'cache_read_input_tokens',
                                                                       'cache_creation_input_tokens',
                                                                       'output_tokens'), per_message))}},
                  {'type': 'result', 'subtype': 'success', 'is_error': False, 'num_turns': 1, 'result': '{}',
                   'modelUsage': model_usage}]
        return ''.join(json.dumps(e) + '\n' for e in events)

    def test_complete_counters(self):
        u = P.caller_usage(self.stream({'m': {'inputTokens': 1000, 'cacheReadInputTokens': 0,
                                              'cacheCreationInputTokens': 0, 'outputTokens': 200}}))
        self.assertEqual((u['complete'], u['total'], u['lower_bound']), (True, 1200, 1200))

    def test_missing_or_bad_counter_is_incomplete(self):
        for mu in ({'m': {'inputTokens': 1000, 'outputTokens': 200}},
                   {'m': {'inputTokens': 1000, 'cacheReadInputTokens': None, 'cacheCreationInputTokens': 0,
                          'outputTokens': 200}},
                   {'m': {'inputTokens': True, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0,
                          'outputTokens': 200}}, {}, None):
            u = P.caller_usage(self.stream(mu))
            self.assertFalse(u['complete'], mu)
            self.assertIsNone(u['total'])
            self.assertEqual(u['lower_bound'], 1200)

    def test_envelope_below_the_per_message_bound_is_incomplete(self):
        u = P.caller_usage(self.stream({'m': {'inputTokens': 100, 'cacheReadInputTokens': 0,
                                              'cacheCreationInputTokens': 0, 'outputTokens': 20}}))
        self.assertFalse(u['complete'])
        self.assertEqual(u['lower_bound'], 1200)

    def run_dir(self, model_usage, envelope, ledger_end, stop_reason=None):
        run = Path(tempfile.mkdtemp(prefix='cra-'))
        self.addCleanup(shutil.rmtree, run, ignore_errors=True)
        (run / 'transcript.jsonl').write_text(self.stream(model_usage), encoding='utf-8')
        (run / 'meta.json').write_text(json.dumps({'wall_s': 1.0, 'exit_code': 0, 'stop_reason': stop_reason}),
                                       encoding='utf-8')
        (run / 'archive' / 'worker' / 'envelopes').mkdir(parents=True)
        (run / 'archive' / 'worker' / 'envelopes' / '0000.json').write_text(json.dumps(envelope), encoding='utf-8')
        calls = run / 'do' / 'h1' / 'calls.jsonl'
        calls.parent.mkdir(parents=True)
        rows = [{'event': 'call_start', 'call_id': 'c1'}] + ([ledger_end] if ledger_end else [])
        calls.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        return run

    def test_lower_bound_is_the_max_over_every_source(self):
        """Review 2, finding 2: a preserved 120k worker envelope with no ledger completion, and a caller final total
        above the per-message usage, both raise the lower bound; the run is charged max(reserve, lower bound)."""
        spec = P.build_spec('A', 'I')
        partial_final = {'m': {'inputTokens': 50000, 'outputTokens': 900}}          # cache counters missing
        big = {'modelUsage': {'w': {'inputTokens': 119000, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0,
                                    'outputTokens': 1000}}}
        rec = P.build_record(spec, self.run_dir(partial_final, big, None))
        self.assertFalse(rec['accounting_complete'])
        self.assertEqual(rec['lower_bound_tokens'], 50900 + 120000)
        self.assertEqual(rec['charged_tokens'], 50900 + 120000)
        self.assertEqual(rec['lower_bound_sources'], {'caller_messages': 1200, 'caller_final': 50900,
                                                      'worker_ledger': 0, 'worker_envelopes': 120000})
        # the ledger above the envelopes, an envelope with a broken entry still counts its valid counters
        broken = {'modelUsage': {'w': {'inputTokens': 3000, 'outputTokens': None}}}
        end = {'event': 'call_end', 'usage': {'raw': {'input_tokens': 4000, 'output_tokens': 700}}}
        rec = P.build_record(spec, self.run_dir(None, broken, end))
        self.assertEqual(rec['lower_bound_sources']['worker_envelopes'], 3000)
        self.assertEqual(rec['lower_bound_tokens'], 1200 + 4700)
        self.assertEqual(rec['charged_tokens'], P.RUN_RESERVE)

    def test_a_usage_stop_is_charged_the_reserve(self):
        spec = P.build_spec('A', 'I')
        full = {'m': {'inputTokens': 1000, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0,
                      'outputTokens': 200}}
        env = {'modelUsage': {'w': {'inputTokens': 10, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0,
                                    'outputTokens': 1}}}
        end = {'event': 'call_end', 'usage': {'raw': {'input_tokens': 10, 'output_tokens': 1}}}
        rec = P.build_record(spec, self.run_dir(full, env, end, stop_reason='usage'))
        self.assertFalse(rec['accounting_complete'])
        self.assertEqual(rec['charged_tokens'], P.RUN_RESERVE)


BAD = (None, True, False, -1, '5', 5.0, [3], {'n': 3})        # every malformed counter value
MISSING = object()                                              # stands for a missing key


def shapes(good: dict):
    """Every malformed variant of one usage object: non-dict replacements, then each counter replaced by each bad
    value or removed."""
    for whole in (None, 'usage', 7, 2.5, True, [dict(good)]):
        yield whole
    for key in good:
        for bad in BAD + (MISSING,):
            out = dict(good)
            if bad is MISSING:
                del out[key]
            else:
                out[key] = bad
            yield out


class MalformedUsageTests(unittest.TestCase):
    """Re-review, open point: every malformed usage shape, caller or worker, is recorded as incomplete accounting
    with its lower bound and charged max(reserve, lower bound), never raising, on the first record and on recovery."""

    MSG = {'input_tokens': 1000, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0, 'output_tokens': 200}
    MU = {'inputTokens': 1000, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0, 'outputTokens': 200}
    RAW = {'input_tokens': 4000, 'cached_input_tokens': 0, 'cache_creation_input_tokens': 0, 'output_tokens': 700}
    WMU = {'inputTokens': 4000, 'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0, 'outputTokens': 700}
    FULL = 1200 + 4700

    def write(self, base: Path, msg_usage=None, model_usage=None, raw=None, wmu=None) -> Path:
        """A run directory with one caller message, a final envelope, one worker call (ledger and envelope); each
        argument replaces the good value of that source (a callable left as None keeps it good)."""
        run = base
        run.mkdir(parents=True)
        events = [{'type': 'assistant', 'message': {'id': 'm1', 'content': [{'type': 'text', 'text': '{}'}],
                                                    'usage': self.MSG if msg_usage is None else msg_usage[0]}},
                  {'type': 'result', 'subtype': 'success', 'is_error': False, 'num_turns': 1, 'result': '{}',
                   'modelUsage': {'claude-sonnet-5-5': self.MU} if model_usage is None else model_usage[0]}]
        (run / 'transcript.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events), encoding='utf-8')
        (run / 'meta.json').write_text(json.dumps({'wall_s': 1.0, 'exit_code': 0, 'stop_reason': None}),
                                       encoding='utf-8')
        envs = run / 'archive' / 'worker' / 'envelopes'
        envs.mkdir(parents=True)
        (envs / '0000.json').write_text(json.dumps({'modelUsage': {'w': self.WMU} if wmu is None else wmu[0]}),
                                        encoding='utf-8')
        calls = run / 'do' / 'h1' / 'calls.jsonl'
        calls.parent.mkdir(parents=True)
        end = {'event': 'call_end', 'call_id': 'c1', 'usage': {'raw': self.RAW if raw is None else raw[0]}}
        calls.write_text(json.dumps({'event': 'call_start', 'call_id': 'c1'}) + '\n' + json.dumps(end) + '\n',
                         encoding='utf-8')
        (run / 'raw_complete').write_text('raw data kept\n', encoding='utf-8')
        return run

    def cases(self):
        yield 'good', {}, True
        for n, u in enumerate(shapes(self.MSG)):
            yield f'message {n}', {'msg_usage': (u,)}, False
        for n, u in enumerate(shapes(self.MU)):
            yield f'final entry {n}', {'model_usage': ({'claude-sonnet-5-5': u},)}, False
        for whole in (None, [], 'x', 3, {}):
            yield f'final whole {whole!r}', {'model_usage': (whole,)}, False
        for n, u in enumerate(shapes(self.RAW)):
            yield f'ledger raw {n}', {'raw': (u,)}, False
        for n, u in enumerate(shapes(self.WMU)):
            yield f'envelope entry {n}', {'wmu': ({'w': u},)}, False
        for whole in (None, [], 'x', 3, {}):
            yield f'envelope whole {whole!r}', {'wmu': (whole,)}, False

    def check(self, name, rec, complete):
        self.assertEqual(rec['accounting_complete'], complete, name)
        if complete:
            self.assertEqual((rec['total_tokens'], rec['charged_tokens']), (self.FULL, self.FULL), name)
        else:
            self.assertIsNone(rec['total_tokens'], name)
            # one source of a spend broken: the other independent source of that spend keeps the bound
            self.assertEqual(rec['lower_bound_tokens'], self.FULL, name)
            self.assertEqual(rec['charged_tokens'], max(P.RUN_RESERVE, rec['lower_bound_tokens']), name)

    def test_every_malformed_shape_on_the_first_record(self):
        base = Path(tempfile.mkdtemp(prefix='crm-'))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        spec = P.build_spec('A', 'I')
        n = 0
        for n, (name, kw, complete) in enumerate(self.cases()):
            try:
                rec = P.build_record(spec, self.write(base / f'r{n}', **kw))
            except Exception as exc:                                  # noqa: BLE001
                self.fail(f'{name}: {type(exc).__name__}: {exc}')
            self.check(name, rec, complete)
        self.assertGreater(n, 120)

    def test_both_sources_of_one_spend_broken(self):
        base = Path(tempfile.mkdtemp(prefix='crm-'))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        spec = P.build_spec('A', 'I')
        rec = P.build_record(spec, self.write(base / 'c', msg_usage=(dict(self.MSG, output_tokens=None),),
                                              model_usage=({'m': dict(self.MU, outputTokens='200')},)))
        self.assertEqual(rec['lower_bound_tokens'], 1000 + 4700)
        rec = P.build_record(spec, self.write(base / 'w', raw=(dict(self.RAW, input_tokens=4000.0),),
                                              wmu=({'w': dict(self.WMU, inputTokens=None)},)))
        self.assertEqual(rec['lower_bound_tokens'], 1200 + 700)
        self.assertEqual(rec['charged_tokens'], P.RUN_RESERVE)

    def test_malformed_ledger_and_stream_lines(self):
        base = Path(tempfile.mkdtemp(prefix='crm-'))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        run = self.write(base / 'r')
        calls = run / 'do' / 'h1' / 'calls.jsonl'
        calls.write_text(calls.read_text(encoding='utf-8') + 'not json\n5\n{"event": "call_end", "usage": 3}\n',
                         encoding='utf-8')
        with (run / 'transcript.jsonl').open('a', encoding='utf-8') as f:
            f.write('7\n{"type": "assistant", "message": "text"}\n'
                    '{"type": "assistant", "message": {"id": "m2", "content": "x", "usage": [1]}}\n')
        rec = P.build_record(P.build_spec('A', 'I'), run)
        self.assertFalse(rec['accounting_complete'])
        self.assertEqual(rec['charged_tokens'], P.RUN_RESERVE)

    def test_every_malformed_shape_on_recovery(self):
        """recover() rebuilds a kept run through the same record path: it must record the run, charged
        max(reserve, lower bound), and never raise, whatever shape the usage has."""
        base = Path(tempfile.mkdtemp(prefix='crm-'))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        cases = [c for c in self.cases() if not c[2]]
        for n, (name, kw, _) in enumerate(cases):
            out = base / f'o{n}'
            out.mkdir()
            self.write(out / 'A-I', **kw)
            (out / 'attempts.jsonl').write_text(json.dumps({'attempt': 'A-I#1', 'tag': 'A-I', 'admitted': True,
                                                            'quota_before': 46.0}) + '\n', encoding='utf-8')
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    P.recover(out, 'd' * 64)
            except Exception as exc:                                  # noqa: BLE001
                self.fail(f'{name}: {type(exc).__name__}: {exc}')
            recs = [json.loads(x) for x in (out / 'runs.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(recs), 1, name)
            self.assertTrue(recs[0]['recovered'], name)
            self.check(name, recs[0], False)
            self.assertEqual(P.admission(P.state(out), '46')['spent_tokens'], recs[0]['charged_tokens'], name)


class TranscriptShapeTests(unittest.TestCase):
    """Re-review 3: (a) a dropped or unparseable transcript line makes caller accounting incomplete, on the first
    record and on recovery (only the live guard may wait on one unterminated final line); (b) a non-string message,
    tool or tool-result id (unhashable in pilot_k2.parse_stream), or non-string text, never raises and makes the
    accounting incomplete. Each case corrupts only the transcript of an otherwise complete 5,900-token run."""

    MSG, MU, RAW, WMU, FULL = (MalformedUsageTests.MSG, MalformedUsageTests.MU, MalformedUsageTests.RAW,
                               MalformedUsageTests.WMU, MalformedUsageTests.FULL)
    write = MalformedUsageTests.write

    def check(self, name, rec, complete):
        """An injected assistant message may carry its own valid usage, which rightly raises the per-message bound,
        so the bound is checked from below here."""
        if complete:
            return MalformedUsageTests.check(self, name, rec, complete)
        self.assertFalse(rec['accounting_complete'], name)
        self.assertIsNone(rec['total_tokens'], name)
        self.assertTrue(rec['caller']['transcript_problems'], name)
        self.assertGreaterEqual(rec['lower_bound_tokens'], self.FULL, name)
        self.assertEqual(rec['charged_tokens'], max(P.RUN_RESERVE, rec['lower_bound_tokens']), name)

    LINES = {'invalid json': b'{"type": "assistant", "message": {\n', 'number': b'5\n', 'list': b'[1, 2]\n',
             'string': b'"text"\n', 'null': b'null\n', 'blank': b'\n', 'spaces': b'   \n',
             'bad utf-8': b'{"type": "system", "note": "\xff\xfe"}\n'}

    def shape_events(self):
        msg = lambda **kw: {'type': 'assistant', 'message': dict({'id': 'm2', 'usage': self.MSG,
                                                                  'content': [{'type': 'text', 'text': ''}]}, **kw)}
        tool = lambda **kw: {'type': 'assistant', 'message': {'id': 'm2', 'usage': self.MSG, 'content': [
            dict({'type': 'tool_use', 'id': 't1', 'name': 'Bash', 'input': {'command': 'ls'}}, **kw)]}}
        result = lambda **kw: {'type': 'user', 'message': {'content': [
            dict({'type': 'tool_result', 'tool_use_id': 't1', 'content': 'x'}, **kw)]}}
        return {'list id, null usage': msg(id=['m1'], usage=None), 'list id': msg(id=['m1']),
                'dict id': msg(id={'a': 1}), 'int id': msg(id=7), 'missing id': {'type': 'assistant', 'message': {
                    'usage': self.MSG, 'content': []}},
                'list tool id': tool(id=['t1']), 'dict tool id': tool(id={'t': 1}),
                'list tool_use_id': result(tool_use_id=['t1']), 'dict tool_use_id': result(tool_use_id={'t': 1}),
                'list text': msg(content=[{'type': 'text', 'text': ['a']}]),
                'dict thinking': msg(content=[{'type': 'thinking', 'thinking': {'a': 1}}])}

    def corrupted(self, base: Path, name: str) -> Path:
        run = self.write(base)
        t = run / 'transcript.jsonl'
        data = t.read_bytes()
        if name == 'unterminated final line':
            t.write_bytes(data.rstrip(b'\n'))
        elif name in self.LINES:
            first, rest = data.split(b'\n', 1)
            t.write_bytes(first + b'\n' + self.LINES[name] + rest)
        else:
            first, rest = data.split(b'\n', 1)
            t.write_bytes(first + b'\n' + json.dumps(self.shape_events()[name]).encode() + b'\n' + rest)
        return run

    def names(self):
        return list(self.LINES) + ['unterminated final line'] + list(self.shape_events())

    def test_the_uncorrupted_run_is_complete_below_the_reserve(self):
        base = Path(tempfile.mkdtemp(prefix='crt-'))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        rec = P.build_record(P.build_spec('A', 'I'), self.write(base / 'good'))
        self.check('good', rec, True)
        self.assertLess(rec['charged_tokens'], P.RUN_RESERVE)

    def test_each_corrupted_transcript_on_the_first_record(self):
        base = Path(tempfile.mkdtemp(prefix='crt-'))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        for n, name in enumerate(self.names()):
            with self.subTest(name):
                try:
                    rec = P.build_record(P.build_spec('A', 'I'), self.corrupted(base / f'r{n}', name))
                except Exception as exc:                              # noqa: BLE001
                    self.fail(f'{name}: {type(exc).__name__}: {exc}')
                self.check(name, rec, False)
                self.assertEqual(rec['charged_tokens'], P.RUN_RESERVE, name)

    def test_each_corrupted_transcript_on_recovery(self):
        base = Path(tempfile.mkdtemp(prefix='crt-'))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        for n, name in enumerate(self.names()):
            with self.subTest(name):
                out = base / f'o{n}'
                out.mkdir()
                self.corrupted(out / 'A-I', name)
                (out / 'attempts.jsonl').write_text(json.dumps({'attempt': 'A-I#1', 'tag': 'A-I', 'admitted': True,
                                                                'quota_before': 46.0}) + '\n', encoding='utf-8')
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        P.recover(out, 'd' * 64)
                except Exception as exc:                              # noqa: BLE001
                    self.fail(f'{name}: {type(exc).__name__}: {exc}')
                recs = [json.loads(x) for x in (out / 'runs.jsonl').read_text(encoding='utf-8').splitlines()]
                self.assertEqual(len(recs), 1, name)
                self.check(name, recs[0], False)
                self.assertEqual(P.admission(P.state(out), '46')['spent_tokens'], P.RUN_RESERVE, name)

    def live(self, body: str):
        tmp = Path(tempfile.mkdtemp(prefix='crl-'))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / 'state').mkdir()
        (tmp / 'ws').mkdir()
        script = tmp / 'caller.py'
        script.write_text('import sys, time\nw = sys.stdout.write\n' + body, encoding='utf-8')
        P.write_state(tmp / 'state', 0)
        _, _, meta = P.launch([sys.executable, str(script)], b'', tmp / 'ws', tmp / 'state', dict(os.environ), 60,
                              envelopes=tmp / 'env')
        return meta

    def test_the_live_guard_stops_on_a_bad_terminated_line(self):
        good = json.dumps({'type': 'assistant', 'message': {'id': 'm1', 'usage': self.MSG, 'content': []}})
        meta = self.live(f'w({good!r} + "\\n"); sys.stdout.flush()\nw("garbage\\n"); sys.stdout.flush()\n'
                         'time.sleep(20)\n')
        self.assertEqual(meta['stop_reason'], 'usage')
        self.assertLess(meta['wall_s'], 15)
        ids = json.dumps({'type': 'assistant', 'message': {'id': ['m1'], 'usage': self.MSG, 'content': []}})
        meta = self.live(f'w({ids!r} + "\\n"); sys.stdout.flush()\ntime.sleep(20)\n')
        self.assertEqual(meta['stop_reason'], 'usage')

    def test_the_live_guard_waits_on_one_unterminated_final_line(self):
        good = json.dumps({'type': 'assistant', 'message': {'id': 'm1', 'usage': self.MSG, 'content': []}})
        meta = self.live(f'w({good!r} + "\\n")\nw("{{\\"type\\": \\"res")\n')
        self.assertIsNone(meta['stop_reason'])


class SnapshotTests(unittest.TestCase):
    """Fix 5 and fix 2: a run imports only an immutable snapshot inside its own run root, and nothing it can name
    leads back to the repository."""

    def test_runtime_pins_come_from_the_frozen_commit(self):
        for rel in P.RUNTIME_FROM_COMMIT:
            blob = subprocess.run(['git', 'show', f'{P.FROZEN_COMMIT}:{rel}'], cwd=ROOT, capture_output=True,
                                  check=True).stdout
            self.assertEqual(P.sha(blob), P.runtime_pins()[rel], rel)

    def test_snapshot_refuses_drifted_bytes(self):
        tmp = Path(tempfile.mkdtemp(prefix='crs-'))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        real = P.runtime_source
        with mock.patch.object(P, 'runtime_source', side_effect=lambda rel: real(rel) + b'# drift\n'):
            with self.assertRaises(P.SnapshotError):
                P.snapshot(tmp / 'code')

    @unittest.skipUnless(os.name == 'nt', WINDOWS)
    def test_every_runtime_import_resolves_inside_the_run_root(self):
        tmp = Path(tempfile.mkdtemp(prefix='crs-'))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ws, run_root, env = P.setup(tmp, P.build_spec('A', 'D'))
        probe = ('import json, sys, oz_cli, oz_do, oz_batch, oz_workspace, tiktoken, regex\n'
                 'tiktoken.get_encoding("o200k_base")\n'
                 'print(json.dumps(sorted({m.__file__ for m in list(sys.modules.values()) '
                 'if getattr(m, "__file__", None)})))\n')
        shim = P.shim_command(run_root)
        proc = subprocess.run([*shim['argv'][:2], '-c', probe], cwd=ws, env=dict(env, **shim['env']),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        files = json.loads(proc.stdout)
        ours = [f for f in files if Path(f).name.startswith('oz') or 'tiktoken' in Path(f).parts
                or 'regex' in Path(f).parts]
        self.assertTrue(ours)
        for f in ours:
            self.assertTrue(Path(f).resolve().is_relative_to(run_root.resolve()), f)
        for f in files:
            self.assertFalse(Path(f).resolve().is_relative_to(ROOT), f)

    @unittest.skipUnless(os.name == 'nt', WINDOWS)
    def test_init_imports_resolve_inside_the_run_root(self):
        """Review 2, finding 3: the workspace init runs `python -c`, whose sys.path starts with its cwd. Probe with
        exactly the interpreter flags, cwd and environment setup() gives that call, from the repository as cwd (the
        harness's own cwd), so a working-tree oz_cli.py would be found first if the init could reach it."""
        tmp = Path(tempfile.mkdtemp(prefix='crs-'))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        old = os.getcwd()
        os.chdir(ROOT)
        self.addCleanup(os.chdir, old)
        real, seen = subprocess.run, []

        def spy(argv, *a, **kw):
            if '-c' in list(argv):
                seen.append((list(argv), dict(kw)))
            return real(argv, *a, **kw)

        with mock.patch.object(P.subprocess, 'run', side_effect=spy):
            ws, run_root, env = P.setup(tmp, P.build_spec('A', 'D'))
        self.assertEqual(len(seen), 1)
        argv, kw = seen[0]
        cwd = Path(kw.get('cwd') or os.getcwd()).resolve()
        self.assertTrue(cwd.is_relative_to(run_root.resolve()), cwd)
        probe = ('import json, sys, oz_cli, oz_do, oz_workspace, tiktoken\n'
                 'print(json.dumps(sorted({m.__file__ for m in list(sys.modules.values()) '
                 'if getattr(m, "__file__", None)})))\n')
        proc = real([*argv[:argv.index('-c')], '-c', probe], cwd=kw.get('cwd'), env=kw['env'], capture_output=True,
                    text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        files = json.loads(proc.stdout)
        oz = [f for f in files if Path(f).name.startswith('oz')]
        self.assertTrue(oz)
        for f in oz:
            self.assertTrue(Path(f).resolve().is_relative_to(run_root.resolve()), f)
        for f in files:
            self.assertFalse(Path(f).resolve().is_relative_to(ROOT), f)

    @unittest.skipUnless(os.name == 'nt', WINDOWS)
    def test_no_route_to_the_repository_from_inside_the_workspace(self):
        """Attempt the derivation a caller could make: cwd and its parents, the environment, every file in the run
        root (adapter.json, the shim, the snapshot) and every existing file or directory those texts name."""
        tmp = Path(tempfile.mkdtemp(prefix='crs-'))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ws, run_root, env = P.setup(tmp, P.build_spec('B', 'D'))
        forms = P._repo_forms()
        seen_text = []
        for key, value in env.items():
            seen_text.append(f'{key}={value}')
        queue = [p for p in run_root.rglob('*') if p.is_file()]
        visited = set()
        path_re = re.compile(r'(?:[A-Za-z]:[\\/]|/[a-z]/)[^\s"\'<>|*?]+')
        while queue:
            p = queue.pop()
            if p in visited or len(visited) > 4000:
                continue
            visited.add(p)
            try:
                text = p.read_bytes().decode('utf-8', 'replace')
            except OSError:
                continue
            seen_text.append(str(p))
            if p.suffix in ('.pyd', '.tiktoken') or p.stat().st_size > 2_000_000:
                continue
            seen_text.append(text)
            for found in path_re.findall(text):
                q = Path(re.sub(r'^/([a-z])/', r'\1:/', found).rstrip('.,;:)'))
                if q.is_file() and q.stat().st_size < 2_000_000 and not q.is_relative_to(Path(sys.base_prefix)):
                    queue.append(q)
        for part in [str(ws)] + [str(x) for x in ws.parents]:
            seen_text.append(part)
        blob = '\n'.join(seen_text).lower()
        for form in forms:
            self.assertNotIn(form, blob)
        for p in run_root.rglob('*'):
            if p.is_file() and p.suffix not in ('.pyd', '.tiktoken', '.sqlite'):
                assert_clean(self, p.read_bytes().decode('utf-8', 'replace'), where=str(p))


@unittest.skipUnless(os.name == 'nt', WINDOWS)
class EndToEndTests(unittest.TestCase):
    """The dry gate itself, plus resume, rejudge, report and the workspace/packet isolation grep."""

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='crt-'))
        with contextlib.redirect_stdout(io.StringIO()):
            cls.res = P.dry(cls.base / 'dry')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def test_dry_gate_passes_every_scenario(self):
        bad = {k: v['problems'] for k, v in self.res['scenarios'].items() if v['problems']}
        self.assertEqual(bad, {})
        self.assertTrue(self.res['ok'])
        names = set(self.res['scenarios'])
        for need in ('I-clean', 'D-mixed', 'D-violation', 'I-truncated', 'I-malformed', 'D-unseeded',
                     'I-oz-violation', 'I-cap', 'D-worker-cap', 'I-missing-usage', 'D-worker-no-usage',
                     'I-missing-counter', 'I-out-of-domain', 'I-rejection-witness'):
            self.assertIn(need, names)

    def test_rejudge_gives_zero_mismatches(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(P.rejudge(self.res['out'], root_for=self.res['roots'], fixes_for=self.res['fixes']), 0)

    def test_rejudge_detects_tampering(self):
        out = self.base / 'tamper'
        shutil.copytree(self.res['out'], out)
        runs = out / 'runs.jsonl'
        rows = [json.loads(x) for x in runs.read_text(encoding='utf-8').splitlines()]
        rows[0]['score']['correct_files'] += 1
        runs.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertGreater(P.rejudge(out, root_for=self.res['roots'], fixes_for=self.res['fixes']), 0)

    def test_every_run_keeps_its_raw_data(self):
        for tag, sc in self.res['scenarios'].items():
            run = Path(sc['run_dir'])
            for name in ('prompt.txt', 'spec.json', 'meta.json', 'transcript.jsonl', 'stderr.txt', 'record.json',
                         'ws_files.json', 'raw_complete'):
                self.assertTrue((run / name).is_file(), (tag, name))
            if sc['record']['caller']['envelope']:
                self.assertTrue((run / 'caller_envelope.json').is_file(), tag)
            if sc['record']['worker']['calls']:
                self.assertTrue(list(run.glob('archive/oz/*/request.bin')), tag)
                self.assertTrue((run / 'archive' / 'worker' / 'packets.jsonl').is_file(), tag)
                self.assertTrue(list(run.glob('archive/worker/envelopes/*.json')), tag)
                self.assertTrue(list(run.glob('do/*/calls.jsonl')), tag)

    def test_workspace_and_packets_hold_no_key_or_witness_bytes(self):
        tmp = Path(tempfile.mkdtemp(prefix='crw-', dir=self.base))
        ws, run_root, env = P.setup(tmp, P.build_spec('A', 'D'))
        for path in run_root.rglob('*'):
            if path.is_file() and path.suffix not in ('.sqlite', '.pyd', '.tiktoken'):
                assert_clean(self, path.read_bytes().decode('utf-8', 'replace'), where=str(path))
        for key in ('PYTHONPATH', 'TIKTOKEN_CACHE_DIR', 'OZ_MODEL', 'VIRTUAL_ENV'):
            self.assertNotIn(key, env)
        for value in env.values():
            for form in P._repo_forms():
                self.assertNotIn(form, value.lower())
        checked = 0
        for tag, sc in self.res['scenarios'].items():
            for line in Path(sc['run_dir']).glob('archive/worker/packets.jsonl'):
                for row in line.read_text(encoding='utf-8').splitlines():
                    req = json.loads(row)['request']
                    texts = [req['system'], req['prompt']] + list(strings(json.loads(req['prompt'])))
                    for text in texts:
                        assert_clean(self, text, Path(sc['root']), tag)
                    checked += 1
        self.assertGreater(checked, 0)

    def test_report_prints_table_and_fill_slope(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            P.report(self.res['out'])
        text = buf.getvalue()
        for word in ('caller turns', 'cache read', 'worker', 'correct', 'recall', 'FP', 'unproven', '60k', '120k'):
            self.assertIn(word, text)

    def test_resume_never_repays_a_finished_run(self):
        out = self.base / 'resume'
        calls = self.base / 'calls.log'
        with mock.patch.object(P, 'SCHEDULE', (('A', 'I'), ('A', 'D'))), \
                mock.patch.object(P, 'environment', return_value={'cli_version': 'x', 'core_sha256': {}}), \
                contextlib.redirect_stdout(io.StringIO()):
            digest = P.manifest()[0]
            kw = dict(out=out, **P.dry_caller(self.base / 'res', 'perfect', calls))
            self.assertEqual(P.counted(digest, '46', **kw), 0)
            self.assertEqual(P.counted(digest, '47', **kw), 3)         # previous run unsettled: refused before launch
            self.assertEqual(len(calls.read_text().splitlines()), 1)
            P.quota_after('46', out=out)
            # a crash after the raw data was kept but before the record line: rebuilt, not re-run
            with mock.patch.object(P, 'append_record', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    P.counted(digest, '46', **kw)
            self.assertEqual(len(calls.read_text().splitlines()), 2)
            P.quota_after('46', out=out)
            self.assertEqual(P.counted(digest, '46', **kw), 0)         # rebuilds A-D, nothing left to run
            self.assertEqual(len(calls.read_text().splitlines()), 2)
            tags = [json.loads(x)['tag'] for x in (out / 'runs.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(tags, ['A-I', 'A-D'])
            attempts = [json.loads(x) for x in (out / 'attempts.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([a['admitted'] for a in attempts], [True, False, True])
            self.assertEqual(P.counted('0' * 64, '46', **kw), 2)       # wrong digest: nothing runs


class FreezeTests(unittest.TestCase):
    def test_manifest_is_deterministic(self):
        self.assertEqual(P.manifest()[0], P.manifest()[0])

    def test_the_freeze_holds(self):
        frozen = json.loads(P.FREEZE_FILE.read_text(encoding='utf-8'))
        self.assertEqual(frozen['digest'], P.manifest()[0])

    def test_plan_names_the_digest_and_the_four_runs(self):
        plan = (ROOT / 'docs' / 'design' / 'codereview-pilot-2026-10-24' / 'plan-frozen.md').read_text(
            encoding='utf-8')
        digest = P.manifest()[0]
        self.assertIn(digest, plan)
        self.assertEqual(plan.count('pilot.py run --expect ' + digest), 4)


if __name__ == '__main__':
    unittest.main()
