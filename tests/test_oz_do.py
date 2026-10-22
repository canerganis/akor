"""oz do: one bounded fan-out call over the shipped runtime, tested with a local fake adapter program (no model)."""
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bench' / 'live'))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oz import Error
from oz_batch import SYSTEM
from oz_cli import main
from oz_do import CELLS, do, size_profile
from oz_reply import encode_reply
from oz_workspace import initialize

# Fake adapter: records each request, then answers every job with [first 10 chars of its op, its refs...].
# mode.json beside it can ask for a sleep, a job failure or a large value.
FAKE = r'''
import json, sys, time
from pathlib import Path
request = json.load(sys.stdin)
here = Path(__file__).parent
mode = json.loads((here / 'mode.json').read_text()) if (here / 'mode.json').exists() else {}
with open(here / 'captured.jsonl', 'a', encoding='utf-8') as f:
    f.write(json.dumps({'system': request['system'], 'prompt': request['prompt'], 'ids': request['ids']}) + '\n')
time.sleep(mode.get('sleep', 0))
body = json.loads(request['prompt'])
lines = ['OZ/1g']
for block in body['jobs']:
    op = body['ops'][block[0]]
    for row in block[1:]:
        if row[0] in mode.get('fail', []):
            lines.append(json.dumps([row[0], 'error', 'missing_data', 'no length']))
        elif row[0] in mode.get('big', []):
            lines.append(json.dumps({row[0]: 'x' * 5000}))
        else:
            lines.append(json.dumps({row[0]: [op[:10]] + [body['refs'][i] for i in row[1:]]}))
json.dump({'reply': '\n'.join(lines), 'usage': {'input_tokens': 100, 'output_tokens': 10}}, sys.stdout)
'''
CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}


def request(n=4, **extra):
    value = {'request_id': 'k1', 'goal': 'Report length facts only.',
             'ops': {'extract': 'Extract the length.', 'bounds': 'Check the bounds.'},
             'refs': {'c1': 'length=12.50 mm', 'c2': 'length=12.47 mm'},
             'jobs': [[f'j{i}', 'extract' if i % 2 else 'bounds', 'c1' if i < 3 else 'c2'] for i in range(1, n + 1)],
             'allow_experimental': True, 'max_input_tokens': 100000}
    value.update(extra)
    return value


class DoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.space(self.base / 'ws')

    def space(self, path):
        initialize(path)
        (path / 'fake.py').write_text(FAKE, encoding='utf-8')
        (path / 'adapter.json').write_text(json.dumps({'argv': [sys.executable, 'fake.py'], **CAPS}), encoding='utf-8')
        return path

    def mode(self, **value):
        (self.root / 'mode.json').write_text(json.dumps(value), encoding='utf-8')

    def captured(self, root=None):
        path = (root or self.root) / 'captured.jsonl'
        return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def run_do(self, req, root=None):
        root = root or self.root
        return do(req, workspace=root, adapter=root / 'adapter.json')

    def cli(self, *args, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        stream = io.TextIOWrapper(io.BytesIO((stdin or '').encode('utf-8')), encoding='utf-8')
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch('sys.stdin', stream):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_pilot_workload_packet_is_byte_identical_to_the_h_arm(self):
        import pilot2 as P
        system, user, _, _, _, js = P.calls(3005, 'H')[0]
        body = json.loads(user)
        where = {job: (block[0], ref) for block in body['jobs'] for job, ref in block[1:]}
        req = {'request_id': 'pilot-3005', 'goal': body['goal'],
               'ops': {f'op{i}': text for i, text in enumerate(body['ops'])},
               'refs': {f'c{i}': text for i, text in enumerate(body['refs'])},
               'jobs': [[j, f'op{where[j][0]}', f'c{where[j][1]}'] for j in js],
               'model': 'claude-sonnet-5-5', 'allow_experimental': True, 'max_input_tokens': 100000}
        result = self.run_do(req)
        sent = self.captured()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]['system'], system)
        self.assertEqual(sent[0]['system'], SYSTEM)
        self.assertEqual(sent[0]['prompt'], user)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['counts'], {'accepted': 16})
        self.assertEqual(result['calls'], [{'jobs': 16, 'profile': 'qualified_cell', 'status': 'received'}])
        for job, (op, ref) in where.items():
            self.assertEqual(result['jobs'][job]['value'], [body['ops'][op][:10], body['refs'][ref]])
        self.assertEqual(result['evidence']['scope'], 'model_declared')
        accounting = result['accounting']
        self.assertEqual((accounting['calls'], accounting['failed_calls'], accounting['usage_coverage']),
                         (1, 0, 'complete'))
        self.assertEqual(accounting['tokens']['input_tokens'], 100)
        self.assertEqual(accounting['qualified_cell_calls'], 1)

    def test_resubmission_posts_nothing_new_and_never_repays_settled_jobs(self):
        first = self.run_do(request())
        self.assertEqual(first['status'], 'complete')
        run = self.root / first['run']['run_dir']
        with contextlib.closing(sqlite3.connect(run / 'inbox.sqlite', isolation_level=None)) as db:
            jobs_before = db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]
        second = self.run_do(request())
        self.assertEqual(len(self.captured()), 1)
        self.assertEqual(second['calls'], [])
        self.assertEqual(second['jobs'], first['jobs'])
        self.assertEqual(second['accounting'], first['accounting'])
        self.assertEqual(second['run']['request_sha256'], first['run']['request_sha256'])
        with contextlib.closing(sqlite3.connect(run / 'inbox.sqlite', isolation_level=None)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0], jobs_before)
        # Execution options may change on resubmission; the work may not.
        self.assertEqual(self.run_do(request(deadline_seconds=30, max_inline_bytes=10))['calls'], [])
        changed = request()
        changed['refs']['c1'] = 'length=12.51 mm'
        with self.assertRaisesRegex(Error, 'different work'):
            self.run_do(changed)
        self.assertEqual(len(self.captured()), 1)

    def test_default_request_id_is_the_work_digest(self):
        req = request()
        del req['request_id']
        first, second = self.run_do(req), self.run_do(req)
        self.assertEqual(first['run']['request_id'], 'h' + first['run']['request_sha256'][:16])
        self.assertEqual(second['run']['run_dir'], first['run']['run_dir'])
        self.assertEqual(len(self.captured()), 1)

    def test_crash_mid_call_is_not_replayed_until_its_lease_ends_then_only_unfinished_jobs_run(self):
        class Crashing:
            capabilities = CAPS
            calls = 0

            def __call__(self, req):
                Crashing.calls += 1
                if Crashing.calls > 1:
                    raise SystemExit('killed during the call')
                return {'reply': encode_reply({i: 'first' for i in req['ids']}),
                        'usage': {'input_tokens': 50, 'output_tokens': 5}}

        req = request(max_jobs_per_call=2)
        with self.assertRaises(SystemExit):
            do(req, workspace=self.root, adapter=Crashing())
        after = self.run_do(req)
        self.assertEqual(self.captured(), [])
        self.assertEqual(after['jobs']['j1'], {'status': 'accepted', 'value': 'first'})
        self.assertEqual({after['jobs'][j]['reason'] for j in ('j3', 'j4')}, {'in_flight'})
        self.assertEqual(after['accounting']['unfinished_calls'], 1)
        self.assertEqual(after['accounting']['usage_coverage'], 'partial')
        # The lease ends (time passes); the next resubmission sends only the unfinished jobs, once.
        run = self.root / after['run']['run_dir']
        with contextlib.closing(sqlite3.connect(run / 'inbox.sqlite', isolation_level=None)) as db:
            db.execute("UPDATE jobs SET deadline=0 WHERE state='leased'")
        done = self.run_do(req)
        self.assertEqual(done['status'], 'complete')
        self.assertEqual([c['ids'] for c in self.captured()], [['j3', 'j4']])
        self.assertEqual(done['jobs']['j2'], {'status': 'accepted', 'value': 'first'})
        self.assertEqual(done['accounting']['calls'], 3)
        self.assertEqual(done['accounting']['tokens']['input_tokens'], 150)

    def test_deadline_bounds_the_foreground_call_and_a_resubmission_finishes(self):
        self.mode(sleep=60)
        start = time.monotonic()
        late = self.run_do(request(deadline_seconds=2))
        self.assertLess(time.monotonic() - start, 30)
        self.assertEqual(late['status'], 'incomplete')
        self.assertEqual(late['calls'][0]['error_code'], 'adapter_timeout')
        job = late['jobs']['j1']
        self.assertEqual((job['status'], job['reason'], job['attempts']), ('unresolved', 'deadline', 1))
        self.assertEqual(late['accounting']['usage_coverage'], 'none')
        self.mode()
        done = self.run_do(request(deadline_seconds=60))
        self.assertEqual(done['status'], 'complete')
        accounting = done['accounting']
        self.assertEqual((accounting['calls'], accounting['failed_calls'], accounting['usage_coverage']),
                         (2, 1, 'partial'))
        self.assertEqual(accounting['tokens_scope'], 'calls with reported usage only')

    def test_sizes_outside_qualified_cells_need_explicit_experimental_authorization(self):
        blocked = self.run_do(request(3, model='claude-sonnet-5-5', allow_experimental=False))
        self.assertEqual(blocked['blocker'], {'reason': 'experimental_size_not_authorized', 'size': 3,
                                              'model': 'claude-sonnet-5-5'})
        self.assertEqual(blocked['calls'], [])
        self.assertEqual(blocked['jobs']['j1']['reason'], 'experimental_size_not_authorized')
        self.assertIsNone(blocked['qualification'])
        self.assertEqual(self.captured(), [])
        allowed = self.run_do(request(3, model='claude-sonnet-5-5'))
        self.assertEqual(allowed['calls'][0]['profile'], 'experimental')
        self.assertIsNone(allowed['qualification'])
        # No declared model: nothing can be presented as qualified.
        anonymous = self.run_do(request(4, request_id='anon', allow_experimental=False))
        self.assertEqual(anonymous['blocker']['reason'], 'experimental_size_not_authorized')
        sonnet = self.run_do(request(4, request_id='s4', model='claude-sonnet-5-5', allow_experimental=False))
        self.assertEqual(sonnet['calls'], [{'jobs': 4, 'profile': 'qualified_cell', 'status': 'received'}])
        self.assertEqual(sonnet['accounting']['qualified_cell_calls'], 1)
        self.assertIn('CLI version', sonnet['qualification']['not_checked'])
        fable = self.run_do(request(16, request_id='f16', model='claude-fable-5-1', allow_experimental=False))
        self.assertEqual(fable['blocker']['reason'], 'experimental_size_not_authorized')

    def test_failed_cells_are_refused_even_when_experimental_work_is_authorized(self):
        result = self.run_do(request(1, model='claude-opus-5-5', allow_experimental=True))
        self.assertEqual(result['blocker'], {'reason': 'unsupported_size', 'size': 1, 'model': 'claude-opus-5-5'})
        self.assertEqual(self.captured(), [])
        self.assertEqual(self.run_do(request(4, request_id='o4', model='claude-opus-5-5',
                                             allow_experimental=False))['calls'][0]['profile'], 'qualified_cell')

    def test_cell_table_matches_the_size_gate_record(self):
        qualified = {}
        for model, size, gate, _ in CELLS:
            if gate == 'pass':
                qualified.setdefault(model, []).append(size)
        self.assertEqual({m: sorted(v) for m, v in qualified.items()},
                         {'claude-sonnet-5-5': [1, 4, 16, 32, 64], 'claude-opus-5-5': [4, 16, 64],
                          'claude-haiku-5-5': [1, 4, 16, 64], 'claude-fable-5-1': [64]})
        for model, size, profile in [('claude-sonnet-5-5', 16, 'qualified_cell'), ('claude-opus-5-5', 1, 'unsupported'),
                                     ('claude-opus-5-5', 32, 'experimental'), ('claude-haiku-5-5', 32, 'experimental'),
                                     ('claude-fable-5-1', 4, 'experimental'), (None, 64, 'experimental'),
                                     ('gpt-x', 64, 'experimental'), ('claude-sonnet-5-5', 2, 'experimental')]:
            self.assertEqual(size_profile(model, size), profile, (model, size))
        # A new gate is one more row of data.
        self.assertEqual(size_profile('claude-fable-5-1', 16, CELLS + (('claude-fable-5-1', 16, 'pass', 'x'),)),
                         'qualified_cell')

    def test_job_failures_and_large_values_come_back_as_outcomes_and_artifacts(self):
        self.mode(fail=['j2'], big=['j3'])
        req = request(max_inline_bytes=1000)
        (self.base / 'req.json').write_text(json.dumps(req), encoding='utf-8')
        code, out, err = self.cli('do', str(self.base / 'req.json'), '--workspace', str(self.root),
                                  '--adapter', str(self.root / 'adapter.json'))
        self.assertEqual(code, 3, err)
        result = json.loads(out)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['jobs']['j2'], {'status': 'failed', 'code': 'missing_data', 'message': 'no length'})
        big = result['jobs']['j3']
        self.assertEqual(json.loads((self.root / big['value_file']).read_text(encoding='utf-8')), 'x' * 5000)
        self.assertEqual(big['bytes'], 5002)
        self.assertLess(len(out), 3000)

    def test_file_references_resolve_inside_the_authorized_directory(self):
        (self.root / 'data').mkdir()
        (self.root / 'data' / 'a.txt').write_bytes('length=12.49 mm\r\nmethod=caliper'.encode('utf-8'))
        (self.base / 'outside.txt').write_text('secret', encoding='utf-8')
        req = request(refs={'c1': {'path': 'data/a.txt'}, 'c2': 'inline'})
        result = self.run_do(req)
        self.assertEqual(result['jobs']['j1']['value'][1], 'length=12.49 mm\r\nmethod=caliper')
        for path in ['../outside.txt', str(self.base / 'outside.txt')]:
            with self.assertRaisesRegex(Error, 'outside the authorized directory'):
                self.run_do(request(request_id='k2', refs={'c1': {'path': path}, 'c2': 'x'}))
        self.assertEqual(len(self.captured()), 1)

    def test_invalid_requests_fail_before_anything_runs(self):
        bad = [request(jobs=[['j1', 'nope', 'c1']]), request(jobs=[['j1', 'extract', 'c9']]),
               request(jobs=[['j1', 'extract'], ['j1', 'bounds']]), request(goal=' '), request(extra=1),
               request(jobs=[['ref-c1', 'extract', 'c1']]), request(max_attempts=0), request(v='oz.do/2')]
        for req in bad:
            with self.assertRaises(Error):
                self.run_do(req)
        with self.assertRaisesRegex(Error, 'adapter'):
            do(request(), workspace=self.root)
        self.assertFalse((self.root / 'do').exists())
        self.assertEqual(self.captured(), [])

    def test_cli_and_python_return_the_same_result(self):
        other = self.space(self.base / 'ws2')
        req = request()
        python = self.run_do(req)
        code, out, err = self.cli('do', '--workspace', str(other), '--adapter', str(other / 'adapter.json'),
                                  stdin=json.dumps(req))
        self.assertEqual(code, 0, err)
        cli = json.loads(out)
        for value in (python, cli):
            value['run'].pop('workspace')
            value['run'].pop('elapsed_seconds')
        self.assertEqual(cli, python)
        self.assertEqual(self.captured(other), self.captured())

    def test_jobs_without_references_and_object_rows(self):
        req = request(jobs=[{'id': 'a', 'op': 'extract'}, {'id': 'b', 'op': 'bounds', 'refs': ['c2', 'c1']}])
        result = self.run_do(req)
        self.assertEqual(result['jobs']['a']['value'], ['Extract th'])
        self.assertEqual(result['jobs']['b']['value'], ['Check the ', 'length=12.47 mm', 'length=12.50 mm'])

    def test_run_directory_is_an_ordinary_workspace_for_the_multi_command_lifecycle(self):
        result = self.run_do(request())
        run = self.root / result['run']['run_dir']
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(['status', '--json', '--workspace', str(run)]), 0)
        status = json.loads(out.getvalue())
        self.assertEqual(status['states'], {'done': 6})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(['inspect', 'j1', '--workspace', str(run)]), 0)
        self.assertEqual(json.loads(out.getvalue())['job']['state'], 'done')


if __name__ == '__main__':
    unittest.main()
