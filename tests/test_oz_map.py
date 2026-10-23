"""oz map: glob expansion into oz.do/1 requests, tested with fake adapters (no model, no real CLI)."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oz import Error
from oz_batch import valid_id
from oz_map import main
from oz_do import MAX_JOBS
from oz_map import ADAPTER, apply_input_policy, read_input, INPUT_POLICY, expand, job_name, names_for, pathlike, receipt_line, ref_name, requests, run
from oz_reply import encode_reply
from oz_route import build as build_route
from oz_workspace import initialize

TEXTS = lambda paths: {p: f'text of {p}' for p in paths}
CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}
# Script adapter for the CLI tests: answers every job 'ok', except the jobs of the paths listed in bad.json ('bad'), and
# reports its identity for `--identity` the way the shipped adapters do (model and effort from OZ_MODEL / OZ_EFFORT).
SCRIPT = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, REPO)
if '--identity' in sys.argv:
    json.dump({'backend': 'fake', 'model': os.environ['OZ_MODEL'], 'effort': os.environ['OZ_EFFORT'],
               'effort_applicable': True, 'cli_version': 'fake-1.0', 'flags': ['--fake']}, sys.stdout)
    raise SystemExit(0)
from oz_map import job_name
request = json.load(sys.stdin)
here = Path(__file__).parent
file = here / 'bad.json'
bad = json.loads(file.read_text()) if file.exists() else []
state = json.loads((here / 'map' / 'ownership.json').read_text())['producers']['default']
sub = state['submissions'][-1]['submission']
bad_ids = {job_name(state['producer'], sub, 'map', path) for path in bad}
lines = ['OZ/1g'] + [json.dumps({i: 'bad' if i in bad_ids else 'ok'}) for i in request['ids']]
json.dump({'reply': '\n'.join(lines), 'usage': {'input_tokens': 100, 'output_tokens': 10}}, sys.stdout)
'''.replace('REPO', repr(str(Path(__file__).resolve().parent.parent)))


def owned(root, producer='default'):
    """(producer ID, latest submission ID) the host issued for a producer name."""
    state = json.loads((Path(root) / 'map' / 'ownership.json').read_text(encoding='utf-8'))['producers'][producer]
    return state['producer'], state['submissions'][-1]['submission']


class Fake:
    """Callable adapter: records each call, answers 'ok' (or 'bad' for the jobs of the given paths).
    where() returns the workspace root so the bad paths can be turned into the job names the host issued."""
    capabilities = CAPS

    def __init__(self, bad=(), where=None):
        self.bad, self.seen, self.where = bad, [], where

    def __call__(self, req):
        self.seen.append(list(req['ids']))
        producer, submission = owned(self.where()) if self.bad else (None, None)
        bad = {job_name(producer, submission, 'map', path) for path in self.bad}
        return {'reply': encode_reply({i: 'bad' if i in bad else 'ok' for i in req['ids']}),
                'usage': {'input_tokens': 100, 'output_tokens': 10}}


class MapTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'ws'
        initialize(self.root)
        (self.root / 'refs').mkdir()

    def files(self, names):
        for name in names:
            (self.root / 'refs' / name).write_text(f'text of {name}', encoding='utf-8')

    def map(self, adapter, pattern='refs/*.txt', **kw):
        kw.setdefault('allow_experimental', True)
        return run(pattern, op_text='Say ok.', workspace=self.root, adapter=adapter, **kw)

    def fake(self, bad=()):
        return Fake(bad, where=lambda: self.root)

    def script_adapter(self):
        (self.root / 'adapter.py').write_text(SCRIPT, encoding='utf-8')
        (self.root / 'adapter.json').write_text(json.dumps({'argv': [sys.executable, 'adapter.py'], **CAPS}),
                                                encoding='utf-8')
        return self.root / 'adapter.json'

    def test_expansion_is_sorted_with_deterministic_valid_unique_ids(self):
        self.files(['b.txt', 'a.txt', 'c d.txt', 'B_2.txt'])
        paths = expand('refs/*.txt', self.root)
        self.assertEqual(paths, ['refs/B_2.txt', 'refs/a.txt', 'refs/b.txt', 'refs/c d.txt'])
        names = names_for(paths, 'map', 'pP', 'sS')
        [req] = requests(paths, op='map', text='Say ok.', goal='g', names=names, texts=TEXTS(paths))
        ids = [j[0] for j in req['jobs']]
        self.assertEqual(ids, [job_name('pP', 'sS', 'map', p) for p in paths])
        self.assertTrue(all(valid_id(i) for i in ids) and len(set(ids)) == 4)
        self.assertEqual([req['refs'][j[2]] for j in req['jobs']], [f'text of {p}' for p in paths])
        self.assertEqual(req, requests(paths, op='map', text='Say ok.', goal='g', names=names, texts=TEXTS(paths))[0])
        self.assertTrue(valid_id(job_name('pP', 'sS', 'map', 'x/' * 100 + 'y.txt')))
        self.assertEqual(req['profile'], 'oz1g-selective-v1')
        self.assertNotIn('input_policy', req)

    def test_paths_outside_the_authorized_directory_are_refused(self):
        self.files(['a.txt'])
        (self.root.parent / 'outside.txt').write_text('secret', encoding='utf-8')
        with self.assertRaisesRegex(Error, 'outside'):
            expand('../*.txt', self.root)
        with self.assertRaisesRegex(Error, 'outside'):
            expand(str(self.root.parent / '*.txt'), self.root)
        with self.assertRaisesRegex(Error, 'no files match'):
            expand('nothing/*.txt', self.root)
        adapter = Fake()
        with self.assertRaisesRegex(Error, 'outside'):
            self.map(adapter, pattern='../*.txt')
        self.assertEqual(adapter.seen, [])

    def test_more_than_the_job_limit_splits_into_consecutive_requests_and_merges(self):
        self.files([f'f{i:03d}.txt' for i in range(MAX_JOBS + 44)])
        paths = expand('refs/*.txt', self.root)
        batch = requests(paths, op='map', text='Say ok.', goal='g', names=names_for(paths, 'map', 'pP', 'sS'), texts=TEXTS(paths))
        self.assertEqual([len(r['jobs']) for r in batch], [MAX_JOBS, 44])
        self.assertEqual([j[0] for r in batch for j in r['jobs']], [job_name('pP', 'sS', 'map', p) for p in paths])
        result = self.map(Fake())
        self.assertEqual(result['receipt']['requests'], 2)
        self.assertEqual(result['receipt']['jobs'], MAX_JOBS + 44)
        self.assertEqual(result['receipt']['accepted_by_checks'], MAX_JOBS + 44)
        self.assertEqual([r['path'] for r in result['rows']], paths)

    def test_plan_makes_zero_adapter_calls_and_creates_no_run(self):
        self.files(['a.txt', 'b.txt'])
        adapter = Fake()
        result = self.map(adapter, plan_only=True, learn=True)
        self.assertEqual(adapter.seen, [])
        self.assertEqual(result['plans'][0]['status'], 'planned')
        self.assertEqual(result['plans'][0]['plan']['launched'], 0)
        self.assertEqual(sum(result['plans'][0]['plan']['packets']), 2)
        self.assertEqual(result['receipt']['calls'], 0)
        self.assertFalse((self.root / 'do').exists())

    def test_results_rows_are_in_input_order_with_the_documented_shape(self):
        self.files(['b.txt', 'a.txt'])
        result = self.map(Fake())
        self.assertEqual([r['path'] for r in result['rows']], ['refs/a.txt', 'refs/b.txt'])
        producer, submission = owned(self.root)
        for row in result['rows']:
            self.assertEqual(set(row), {'producer', 'submission', 'worker_hash', 'id', 'request', 'request_id', 'path',
                                        'status', 'value', 'source', 'logical_job', 'reference', 'call_id'})
            self.assertEqual(row['request'], 0)
            self.assertEqual(row['id'], job_name(producer, submission, 'map', row['path']))
            self.assertEqual((row['status'], row['value'], row['source']), ('accepted', 'ok', 'model'))
            self.assertEqual((row['producer'], row['submission']), (producer, submission))
            self.assertEqual(row['logical_job'], {'op': 'map', 'path': row['path']})
            self.assertEqual(row['reference']['name'], ref_name(producer, submission, row['path']))

    def test_receipt_fields_and_one_line(self):
        self.files(['a.txt', 'b.txt'])
        receipt = self.map(Fake())['receipt']
        self.assertEqual((receipt['jobs'], receipt['accepted_by_checks'], receipt['failed'], receipt['calls'],
                          receipt['tokens'], receipt['requests'], receipt['checks'], receipt['usage']),
                         (2, 2, 0, 1, 110, 1, 'none', 'complete'))
        self.assertIn('seconds', receipt)
        line = receipt_line(receipt, 'results.jsonl', learn=True)
        self.assertNotIn('\n', line)
        self.assertIn('accepted_by_checks=2', line)
        self.assertIn('not a correctness claim', line)
        self.assertIn('learn=requested (not active yet)', line)

    def test_a_check_failure_is_reported_per_job_and_never_called_correct(self):
        self.files(['a.txt', 'b.txt', 'c.txt'])
        result = self.map(self.fake(bad=['refs/b.txt']), checks=[{'check': 'one_of', 'values': ['ok']}])
        by_path = {r['path']: r for r in result['rows']}
        self.assertEqual(by_path['refs/a.txt']['status'], 'accepted')
        failed = by_path['refs/b.txt']
        self.assertNotEqual(failed['status'], 'accepted')
        self.assertIn('error', failed)
        self.assertNotIn('value', failed)
        receipt = result['receipt']
        self.assertEqual((receipt['accepted_by_checks'], receipt['failed'], receipt['checks']), (2, 1, 'pinned'))

    def test_cli_writes_jsonl_prints_the_receipt_and_exits_3_on_a_failure(self):
        self.files(['a.txt', 'b.txt'])
        self.script_adapter()
        (self.root / 'checks.json').write_text(json.dumps({'map': [{'check': 'one_of', 'values': ['ok']}]}),
                                               encoding='utf-8')
        out = self.root / 'results.jsonl'

        def cli(*args):
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                return main(list(args)), stdout.getvalue(), stderr.getvalue()

        base = ['refs/*.txt', '--ask', 'Say ok.', '--workspace', str(self.root), '--allow-experimental',
                '--adapter', str(self.root / 'adapter.json'), '--check', str(self.root / 'checks.json'),
                '--model', 'm-test', '--effort', 'high']
        code, text, err = cli(*base, '--out', str(out))
        self.assertEqual((code, err), (0, ''), err)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertIn('accepted_by_checks=2', text)
        rows = [json.loads(x) for x in out.read_text(encoding='utf-8').splitlines()]
        self.assertEqual([r['path'] for r in rows], ['refs/a.txt', 'refs/b.txt'])
        self.assertEqual({r['status'] for r in rows}, {'accepted'})
        # --plan prints the request and plan and calls nothing.
        code, text, err = cli(*base, '--plan', '--learn')
        self.assertEqual(code, 0, err)
        plan = json.loads(text)
        self.assertEqual((plan['schema'], plan['calls'], plan['jobs']), ('oz.map.plan/1', 0, 2))
        self.assertEqual(plan['learn'], 'requested (not active yet)')
        # A failing job gives exit 3 and a failed row (a new goal makes a new request, so nothing is resumed).
        (self.root / 'bad.json').write_text(json.dumps(['refs/b.txt']), encoding='utf-8')
        code, text, err = cli(*base, '--goal', 'Second pass.', '--out', str(out))
        self.assertEqual(code, 3, err)
        self.assertIn('failed=1', text)

    def cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = main(list(args))
            except SystemExit as exc:
                code = exc.code
            except Error as exc:
                code = f'Error: {exc}'
        return code, stdout.getvalue(), stderr.getvalue()

    def test_checks_mapping_without_the_op_or_with_bad_specs_is_an_error_before_dispatch(self):
        self.files(['a.txt'])
        adapter = Fake()
        for bad in ({'other': [{'check': 'one_of', 'values': ['ok']}]}, {'map': 'nope'}, {'map': [1]}, 'x', [], {}):
            with self.assertRaises(Error):
                self.map(adapter, checks=bad)
        self.assertEqual(adapter.seen, [])
        (self.root / 'checks.json').write_text(json.dumps({'other': [{'check': 'one_of', 'values': ['ok']}]}),
                                               encoding='utf-8')
        (self.root / 'adapter.json').write_text(json.dumps({'argv': [sys.executable, '-c', 'raise SystemExit(9)'],
                                                            **CAPS}), encoding='utf-8')
        code, _, err = self.cli('refs/*.txt', '--ask', 'x', '--workspace', str(self.root), '--allow-experimental',
                                '--adapter', str(self.root / 'adapter.json'), '--check', str(self.root / 'checks.json'),
                                '--model', 'm', '--effort', 'low')
        self.assertNotEqual(code, 0)
        self.assertIn('no entry for operation', err)
        self.assertFalse((self.root / 'do').exists())

    def test_bad_inputs_become_failed_rows_and_valid_siblings_still_run(self):
        self.files([f'f{i:03d}.txt' for i in range(MAX_JOBS + 2)])
        (self.root / 'refs' / 'f999.txt').write_bytes(bytes([0xff, 0xfe, 0x20]))
        (self.root / 'refs' / 'f998.txt').write_text('   ', encoding='utf-8')
        (self.root / 'refs' / 'f997.txt').write_text('x' * 70000, encoding='utf-8')
        adapter = self.fake()
        result = self.map(adapter)
        rows = {r['path']: r for r in result['rows']}
        self.assertEqual(len(rows), MAX_JOBS + 5)
        for name, text in (('f999', 'cannot read UTF-8'), ('f998', 'nonblank'), ('f997', 'at most')):
            row = rows[f'refs/{name}.txt']
            self.assertEqual((row['status'], row['source'], row['request'], row['call_id']),
                             ('failed', 'model', None, None))
            self.assertTrue(row['error'].startswith('input_invalid: '), row['error'])
            self.assertIn(text, row['error'])
            self.assertIsNone(row['reference']['input'])
        self.assertEqual(sum(r['status'] == 'accepted' for r in rows.values()), MAX_JOBS + 2)
        self.assertEqual(sum(len(call) for call in adapter.seen), MAX_JOBS + 2)
        self.assertEqual(result['receipt']['invalid_inputs'], 3)
        self.assertEqual(result['receipt']['failed'], 3)
        # Rows stay in sorted path order, failed rows in their place.
        self.assertEqual([r['path'] for r in result['rows']], sorted(rows))

    def test_every_input_invalid_makes_no_call_and_all_rows_failed(self):
        (self.root / 'refs' / 'a.txt').write_bytes(bytes([0xff]))
        (self.root / 'refs' / 'b.txt').write_text('', encoding='utf-8')
        adapter = self.fake()
        result = self.map(adapter)
        self.assertEqual(adapter.seen, [])
        self.assertEqual([r['status'] for r in result['rows']], ['failed', 'failed'])
        self.assertEqual((result['receipt']['calls'], result['receipt']['requests']), (0, 0))
        self.assertFalse((self.root / 'do').exists())

    def test_an_oversized_job_is_isolated_as_a_failed_row(self):
        self.files(['a.txt', 'c.txt'])
        (self.root / 'refs' / 'b.txt').write_text('word ' * 12000, encoding='utf-8')
        adapter = self.fake()
        result = self.map(adapter)
        by_path = {r['path']: r for r in result['rows']}
        self.assertEqual([by_path[p]['status'] for p in ('refs/a.txt', 'refs/b.txt', 'refs/c.txt')],
                         ['accepted', 'failed', 'accepted'])
        self.assertTrue(by_path['refs/b.txt']['error'].startswith('input_budget: '))
        self.assertEqual(sum(len(call) for call in adapter.seen), 2)
        # The limit is exposed: a larger budget runs the same job.
        again = self.map(self.fake(), limits={'max_input_tokens': 40000}, new_submission=True)
        self.assertEqual({r['status'] for r in again['rows']}, {'accepted'})

    def test_the_four_limits_reach_every_request_and_unknown_limits_are_refused(self):
        self.files(['a.txt'])
        limits = {'deadline_seconds': 99, 'call_timeout_seconds': 44, 'max_jobs_per_call': 3, 'max_input_tokens': 777}
        result = self.map(self.fake(), plan_only=True, limits=limits)
        self.assertEqual({k: result['requests'][0][k] for k in limits}, limits)
        with self.assertRaisesRegex(Error, 'limits take'):
            self.map(self.fake(), limits={'bogus': 1})

    def test_ask_and_ask_file_are_exclusive_and_a_missing_file_is_not_the_instruction(self):
        self.files(['a.txt'])
        adapter = self.script_adapter()
        base = ['refs/*.txt', '--workspace', str(self.root), '--allow-experimental', '--plan',
                '--adapter', str(adapter), '--model', 'm', '--effort', 'low']
        (self.root / 'ask.txt').write_text('From file.', encoding='utf-8')
        code, text, err = self.cli(*base, '--ask-file', str(self.root / 'ask.txt'))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(text)['requests'][0]['ops']['map'], 'From file.')
        code, text, err = self.cli(*base, '--ask', 'Inline text.')
        self.assertEqual(json.loads(text)['requests'][0]['ops']['map'], 'Inline text.')
        self.assertNotEqual(self.cli(*base, '--ask-file', str(self.root / 'missing.txt'))[0], 0)
        self.assertEqual(self.cli(*base, '--ask', 'x', '--ask-file', str(self.root / 'ask.txt'))[0], 2)
        self.assertEqual(self.cli(*base)[0], 2)

    def test_a_nonexistent_pathlike_ask_fails_before_dispatch(self):
        self.files(['a.txt'])
        adapter = self.script_adapter()
        base = ['refs/*.txt', '--workspace', str(self.root), '--allow-experimental', '--adapter', str(adapter),
                '--model', 'm', '--effort', 'low']
        for typo in ('prompts/summarize.txt', 'ask.md', 'sub\\dir\\x.txt'):
            code, _, err = self.cli(*base, '--ask', typo)
            self.assertEqual(code, 2, typo)
            self.assertIn('looks like a file path', err)
        self.assertFalse((self.root / 'do').exists())
        self.assertFalse((self.root / 'results.jsonl').exists())
        self.assertTrue(all(pathlike(x) for x in ('a/b', 'x.txt', 'C:\\a')))
        self.assertFalse(any(pathlike(x) for x in ('Say ok.', 'x', 'Extract the value', 'two\nlines.txt')))

    def test_experimental_sizes_need_the_flag_and_fail_before_dispatch(self):
        self.files(['a.txt', 'b.txt'])
        adapter = Fake()
        with self.assertRaisesRegex(Error, 'allow-experimental'):
            self.map(adapter, allow_experimental=False)
        self.assertEqual(adapter.seen, [])
        self.assertFalse((self.root / 'do').exists())
        [req] = requests(['refs/a.txt'], op='map', text='t', goal='g', names=names_for(['refs/a.txt'], 'map', 'p', 's'),
                        texts=TEXTS(['refs/a.txt']))
        self.assertIs(req['allow_experimental'], False)
        # A qualified cell (claude-sonnet-5-5, 4 jobs per packet) runs without the flag.
        self.files(['c.txt', 'd.txt'])
        result = self.map(adapter, allow_experimental=False, model='claude-sonnet-5-5', packet_sizes=[4])
        self.assertEqual(result['receipt']['accepted_by_checks'], 4)

    def test_receipt_separates_this_invocation_from_cumulative_totals(self):
        self.files(['a.txt', 'b.txt'])
        adapter = Fake()
        first = self.map(adapter)['receipt']
        self.assertEqual((first['calls'], first['tokens'], first['cumulative']['calls'],
                          first['cumulative']['tokens']), (1, 110, 1, 110))
        receipt = self.map(adapter)['receipt']
        self.assertEqual(len(adapter.seen), 1)
        self.assertEqual((receipt['calls'], receipt['failed_calls'], receipt['tokens']), (0, 0, 0))
        self.assertEqual((receipt['cumulative']['calls'], receipt['cumulative']['tokens']), (1, 110))
        self.assertEqual(receipt['accepted_by_checks'], 2)
        line = receipt_line(receipt, 'r.jsonl')
        self.assertIn('calls=0 tokens=0', line)
        self.assertIn('cumulative_calls=1 cumulative_tokens=110', line)
        self.assertIn('this invocation', line)

    def test_rows_carry_request_index_and_job_id_across_chunks(self):
        self.files([f'f{i:03d}.txt' for i in range(MAX_JOBS + 3)])
        rows = self.map(Fake())['rows']
        self.assertEqual([r['request'] for r in rows], [0] * MAX_JOBS + [1] * 3)
        self.assertFalse({r['request_id'] for r in rows[:MAX_JOBS]} & {r['request_id'] for r in rows[MAX_JOBS:]})
        producer, submission = owned(self.root)
        self.assertTrue(all(r['id'] == job_name(producer, submission, 'map', r['path']) for r in rows))

    # --- D2: input policy -------------------------------------------------------------------------------------------

    def test_rows_keep_raw_and_resolved_hashes_removed_suffix_and_policy_version(self):
        refs = self.root / 'refs'
        (refs / 'lf.txt').write_bytes(b'v=1\n')
        (refs / 'crlf.txt').write_bytes(b'v=1\r\n')
        (refs / 'two.txt').write_bytes(b'v=1\n\n')
        (refs / 'cr.txt').write_bytes(b'v=1\r')
        (refs / 'none.txt').write_bytes(b'v=1')
        rows = {r['path']: r['reference']['input'] for r in self.map(self.fake())['rows']}
        for name, raw, kept, removed in (('lf', b'v=1\n', b'v=1', '\n'), ('crlf', b'v=1\r\n', b'v=1', '\r\n'),
                                         ('two', b'v=1\n\n', b'v=1\n', '\n'), ('cr', b'v=1\r', b'v=1\r', ''),
                                         ('none', b'v=1', b'v=1', '')):
            receipt = rows[f'refs/{name}.txt']
            self.assertEqual(receipt['policy'], INPUT_POLICY)
            self.assertEqual(receipt['removed'], removed, name)
            self.assertEqual(receipt['raw_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(receipt['resolved_sha256'], hashlib.sha256(kept).hexdigest())

    # --- D7: route identity -----------------------------------------------------------------------------------------

    def test_cli_requires_model_and_effort(self):
        self.files(['a.txt'])
        adapter = self.script_adapter()
        base = ['refs/*.txt', '--ask', 'Say ok.', '--workspace', str(self.root), '--adapter', str(adapter),
                '--allow-experimental']
        for extra in ([], ['--model', 'm'], ['--effort', 'low']):
            code, _, err = self.cli(*base, *extra)
            self.assertEqual(code, 2, extra)
            self.assertIn('--model and --effort are required', err)
        self.assertFalse((self.root / 'do').exists())

    def test_cli_rows_and_receipt_carry_the_worker_hash_and_the_adapter_sees_model_and_effort(self):
        self.files(['a.txt'])
        adapter = self.script_adapter()
        out = self.root / 'r.jsonl'
        code, text, err = self.cli('refs/*.txt', '--ask', 'Say ok.', '--workspace', str(self.root),
                                   '--allow-experimental', '--adapter', str(adapter), '--model', 'm-test',
                                   '--effort', 'high', '--out', str(out))
        self.assertEqual(code, 0, err)
        row = json.loads(out.read_text(encoding='utf-8').splitlines()[0])
        route = build_route(adapter, model='m-test', effort='high')
        self.assertEqual(row['worker_hash'], route['worker_hash'])
        self.assertIn('worker=' + route['worker_hash'][:12], text)
        # A different effort is a different worker and a different submission.
        out2 = self.root / 'r2.jsonl'
        self.cli('refs/*.txt', '--ask', 'Say ok.', '--workspace', str(self.root), '--allow-experimental',
                 '--adapter', str(adapter), '--model', 'm-test', '--effort', 'low', '--out', str(out2))
        row2 = json.loads(out2.read_text(encoding='utf-8').splitlines()[0])
        self.assertNotEqual(row2['worker_hash'], row['worker_hash'])
        self.assertNotEqual(row2['submission'], row['submission'])

    def test_a_conflicting_or_unknown_identity_blocks_dispatch(self):
        self.files(['a.txt'])
        (self.root / 'liar.py').write_text(
            "import json, sys\nif '--identity' in sys.argv:\n"
            "    json.dump({'backend': 'x', 'model': 'other', 'effort': 'low', 'cli_version': '1'}, sys.stdout)\n",
            encoding='utf-8')
        (self.root / 'mute.py').write_text('import sys\nsys.exit(5)\n', encoding='utf-8')
        for script, message in (('liar.py', 'conflict'), ('mute.py', 'unknown')):
            (self.root / 'adapter.json').write_text(json.dumps({'argv': [sys.executable, script], **CAPS}),
                                                    encoding='utf-8')
            code, _, err = self.cli('refs/*.txt', '--ask', 'Say ok.', '--workspace', str(self.root),
                                    '--allow-experimental', '--adapter', str(self.root / 'adapter.json'),
                                    '--model', 'm', '--effort', 'low')
            self.assertEqual(code, 2)
            self.assertIn(message, err)
        self.assertFalse((self.root / 'do').exists())
        self.assertFalse((self.root / 'map').exists())

    # --- D8: ownership ----------------------------------------------------------------------------------------------

    def test_names_are_53_characters_valid_and_namespaced_by_producer_and_submission(self):
        name = job_name('p1', 's1', 'map', 'refs/a.txt')
        self.assertEqual((len(name), name[0]), (53, 'j'))
        self.assertRegex(name, r'^j[a-z2-7]{52}$')
        self.assertTrue(valid_id(name) and valid_id('ref-' + ref_name('p1', 's1', 'refs/a.txt')))
        self.assertEqual(len(ref_name('p1', 's1', 'refs/a.txt')), 53)
        self.assertEqual(name, job_name('p1', 's1', 'map', 'refs/a.txt'))
        # Producer, submission, operation and path each change the name; a job and a reference never share one.
        others = {job_name('p2', 's1', 'map', 'refs/a.txt'), job_name('p1', 's2', 'map', 'refs/a.txt'),
                  job_name('p1', 's1', 'other', 'refs/a.txt'), job_name('p1', 's1', 'map', 'refs/b.txt'), name}
        self.assertEqual(len(others), 5)
        self.assertNotEqual(name[1:], ref_name('p1', 's1', 'refs/a.txt')[1:])

    def test_a_name_collision_is_detected_and_never_truncated(self):
        import oz_map
        original = oz_map._name
        oz_map._name = lambda prefix, identity: prefix + 'a' * 52
        try:
            with self.assertRaisesRegex(Error, 'collision'):
                names_for(['refs/a.txt', 'refs/b.txt'], 'map', 'p', 's')
        finally:
            oz_map._name = original

    def test_ids_are_issued_once_persisted_and_retained_on_resume(self):
        self.files(['a.txt', 'b.txt'])
        adapter = self.fake()
        first = self.map(adapter)
        producer, submission = owned(self.root)
        self.assertTrue((self.root / 'map' / 'ownership.json').is_file())
        self.assertFalse(first['receipt']['resumed'])
        second = self.map(adapter)
        self.assertTrue(second['receipt']['resumed'])
        self.assertEqual(owned(self.root), (producer, submission))
        self.assertEqual([r['id'] for r in first['rows']], [r['id'] for r in second['rows']])
        self.assertEqual(len(adapter.seen), 1)
        self.assertEqual((second['receipt']['calls'], second['receipt']['tokens']), (0, 0))
        self.assertEqual([r['status'] for r in second['rows']], ['accepted', 'accepted'])

    def test_a_new_invocation_with_other_work_gets_a_new_submission_and_new_job_names(self):
        self.files(['a.txt'])
        first = self.map(self.fake())['rows'][0]
        other = self.map(self.fake(), goal='Another goal.')['rows'][0]
        forced = self.map(self.fake(), new_submission=True)['rows'][0]
        self.assertEqual(first['producer'], other['producer'])
        self.assertEqual(len({first['submission'], other['submission'], forced['submission']}), 3)
        self.assertEqual(len({first['id'], other['id'], forced['id']}), 3)

    def test_producers_are_separate_namespaces_for_the_same_path(self):
        self.files(['a.txt'])
        one = self.map(self.fake(), producer='alpha')['rows'][0]
        two = self.map(self.fake(), producer='beta')['rows'][0]
        self.assertNotEqual(one['producer'], two['producer'])
        self.assertNotEqual(one['id'], two['id'])
        self.assertNotEqual(one['reference']['name'], two['reference']['name'])
        with self.assertRaisesRegex(Error, 'producer'):
            self.map(self.fake(), producer='bad name!')

    def test_resume_verifies_each_jobs_payload_and_adds_new_files_under_the_same_ids(self):
        self.files(['a.txt', 'b.txt'])
        first = {r['path']: r for r in self.map(self.fake())['rows']}
        (self.root / 'refs' / 'a.txt').write_text('edited', encoding='utf-8')
        self.files(['c.txt'])
        adapter = self.fake()
        again = {r['path']: r for r in self.map(adapter)['rows']}
        self.assertEqual(again['refs/b.txt']['id'], first['refs/b.txt']['id'])
        self.assertEqual(again['refs/b.txt']['submission'], first['refs/b.txt']['submission'])
        self.assertEqual(again['refs/a.txt']['status'], 'failed')
        self.assertTrue(again['refs/a.txt']['error'].startswith('payload_changed'))
        self.assertEqual(again['refs/c.txt']['status'], 'accepted')
        # Known limit until the step 5 drainer: oz_do settles per request, and a changed file set is a changed request,
        # so the unchanged job b rides in a new request and is sent again (identity is kept, the request is not).
        self.assertNotEqual(again['refs/b.txt']['request_id'], first['refs/b.txt']['request_id'])
        fresh = {r['path']: r for r in self.map(self.fake(), new_submission=True)['rows']}
        self.assertEqual({r['status'] for r in fresh.values()}, {'accepted'})
        self.assertNotEqual(fresh['refs/a.txt']['id'], first['refs/a.txt']['id'])

    def test_an_input_that_was_invalid_can_be_fixed_in_place(self):
        self.files(['a.txt'])
        (self.root / 'refs' / 'b.txt').write_text('', encoding='utf-8')
        first = {r['path']: r for r in self.map(self.fake())['rows']}
        self.assertEqual(first['refs/b.txt']['status'], 'failed')
        (self.root / 'refs' / 'b.txt').write_text('now valid', encoding='utf-8')
        adapter = self.fake()
        second = {r['path']: r for r in self.map(adapter)['rows']}
        self.assertEqual(second['refs/b.txt']['status'], 'accepted')
        self.assertEqual(second['refs/b.txt']['id'], first['refs/b.txt']['id'])
        self.assertEqual(second['refs/a.txt']['id'], first['refs/a.txt']['id'])

    def test_plan_issues_nothing_on_disk(self):
        self.files(['a.txt'])
        self.map(self.fake(), plan_only=True)
        self.assertFalse((self.root / 'map').exists())

    def test_an_unreadable_ownership_record_is_never_overwritten(self):
        self.files(['a.txt'])
        (self.root / 'map').mkdir()
        (self.root / 'map' / 'ownership.json').write_text('{broken', encoding='utf-8')
        with self.assertRaisesRegex(Error, 'ownership|unreadable'):
            self.map(self.fake())
        self.assertEqual((self.root / 'map' / 'ownership.json').read_text(encoding='utf-8'), '{broken')

    def test_rows_carry_the_physical_call_id_and_null_without_a_dispatch(self):
        self.files(['a.txt'])
        (self.root / 'refs' / 'b.txt').write_text('', encoding='utf-8')
        result = self.map(self.fake())
        by_path = {r['path']: r for r in result['rows']}
        ledger = (self.root / 'do' / by_path['refs/a.txt']['request_id'] / 'calls.jsonl').read_text(encoding='utf-8')
        self.assertIn(by_path['refs/a.txt']['call_id'], ledger)
        self.assertIsNone(by_path['refs/b.txt']['call_id'])
        for row in result['rows']:
            self.assertEqual(row['source'], 'model')

    def test_default_adapter_is_the_shipped_claude_adapter_file(self):
        self.assertEqual(ADAPTER.name, 'claude_map_adapter.json')
        self.assertTrue(ADAPTER.exists())


class InputPolicyTests(unittest.TestCase):
    """D2: oz_map resolves the text itself; oz_do receives an inline string and never sees the policy."""

    def test_exactly_one_terminal_crlf_else_one_lf_is_removed_and_nothing_else(self):
        for raw, kept, removed in (('a\n', 'a', '\n'), ('a\r\n', 'a', '\r\n'), ('a\n\n', 'a\n', '\n'),
                                   ('a\r\n\r\n', 'a\r\n', '\r\n'), ('a\r', 'a\r', ''), ('a', 'a', ''),
                                   ('a\n\r\n', 'a\n', '\r\n'), ('  a  \n', '  a  ', '\n'), ('a\nb\n', 'a\nb', '\n')):
            self.assertEqual(apply_input_policy(raw), (kept, removed), raw)

    def test_read_input_receipt_and_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'f.txt').write_bytes(b'length=12.50 mm\r\n')
            receipt, text = read_input('f.txt', root)
            self.assertEqual(text, 'length=12.50 mm')
            self.assertEqual(receipt, {'policy': INPUT_POLICY, 'removed': '\r\n',
                                       'raw_sha256': hashlib.sha256(b'length=12.50 mm\r\n').hexdigest(),
                                       'resolved_sha256': hashlib.sha256(b'length=12.50 mm').hexdigest()})
            (root / 'blank.txt').write_bytes(b'\r\n')
            (root / 'bad.txt').write_bytes(b'\xff\xfe')
            (root / 'big.txt').write_bytes(b'x' * 65537)
            for name in ('blank.txt', 'bad.txt', 'big.txt', 'missing.txt', '../outside.txt'):
                with self.assertRaises(Error, msg=name):
                    read_input(name, root)

    def test_the_request_carries_an_inline_string_and_no_policy_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'f.txt').write_bytes(b'v=1\n')
            text = read_input('f.txt', root)[1]
            [req] = requests(['f.txt'], op='map', text='x', goal='g', names=names_for(['f.txt'], 'map', 'p', 's'),
                             texts={'f.txt': text})
            [ref] = req['refs'].values()
            self.assertEqual(ref, 'v=1')
            self.assertNotIn('input_policy', req)


if __name__ == '__main__':
    unittest.main()
