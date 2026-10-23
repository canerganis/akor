"""oz_manual: the packaged manual-graph facade (docs/design/next-2026-10-23/04 to 06) and its zero-token gate.

    python -m unittest tests.test_oz_manual

Three layers. FacadeTests drive install, run, revise, status and artifacts over a host-only flow (any platform, no
model, no adapter): idempotent installation that starts the deadline, read-only reads, the per-request run lock with
two processes, the scope notice once per process. PinTests hold the O1-derived example under examples/ byte-identical
to its frozen bench/o1 sources. AcceptanceGate runs the documented path of that example from an empty workspace on the
fixture route (stored fixture replies, hard exits and resume, run/revise/run) through subprocesses that cannot reach a
provider or the network. The example runs model-written code in the Windows Job Object sandbox of bench/o1, bench-grade
confinement and not a security boundary, so the gate is Windows-only and skips elsewhere with that reason. Nothing
here is paid, and passing it establishes usability and compatibility only.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / 'tests'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

import manual_helpers as MH  # noqa: E402
import oz_fault  # noqa: E402
import oz_manual  # noqa: E402
from oz import Error  # noqa: E402
import oz_flow  # noqa: E402

EXAMPLE_DIR = ROOT / 'examples' / 'oz_manual_o1'
EXAMPLE = EXAMPLE_DIR / 'example.py'
GUARD = TESTS / 'manual_guard.py'
HELPERS = TESTS / 'manual_helpers.py'
WINDOWS_ONLY = ('the O1 example checks model-written code in the Windows Job Object sandbox of bench/o1 '
                '(bench/o1/sandbox.py refuses when os.name != "nt"); the gate is Windows-only')
KILL = oz_fault.KILL_EXIT


def tree(root, ignore_shm=False) -> dict:
    """{relative path: sha256} of every file under root, the whole file set and every byte."""
    out = {}
    for p in sorted(Path(root).rglob('*')):
        if p.is_file() and not (ignore_shm and p.name.endswith('-shm')):
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def helper(workspace, source_dir, command, *args, faults=''):
    env = dict(os.environ, OZ_FAULTS=faults, PYTHONIOENCODING='utf-8')
    return subprocess.run([sys.executable, str(HELPERS), str(workspace), str(source_dir), command, *args], env=env,
                          capture_output=True, text=True, encoding='utf-8')


class Base(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='oz-manual-'))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.ws = self.base / 'ws'
        self.src = self.base / 'src'
        self.src.mkdir()
        (self.src / 'doc.txt').write_bytes(b'first draft\n')
        self.req = MH.request(self.src)
        self.settings = MH.settings(self.ws)


class FacadeTests(Base):
    def test_scope_is_the_exact_contract_notice(self):
        self.assertEqual(oz_manual.SCOPE.splitlines(), [
            'scope=manual-graph; acceptance=oz1g-selective-v1; delivery=local-files',
            'qualification=experimental; live-model-qualification=not-established-by-packaging'])

    def test_the_notice_goes_to_stderr_once_per_process_and_results_stay_clean(self):
        code = ('import sys; sys.path.insert(0, %r); import manual_helpers as H, oz_manual as M; s = H.settings(%r)\n'
                'for _ in range(3):\n'
                '    try: M.status("nope", s)\n'
                '    except M.FlowNotFound: pass\n' % (str(TESTS), str(self.ws)))
        proc = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, '')
        self.assertEqual(proc.stderr.strip().splitlines(), oz_manual.SCOPE.splitlines())

    def test_every_entry_point_announces_the_scope_on_its_first_call(self):
        for call in (lambda: oz_manual.install(self.req, self.settings),
                     lambda: oz_manual.run(self.req, self.settings),
                     lambda: oz_manual.revise('h1', self.settings, 'doc', b'x', reason='r'),
                     lambda: oz_manual.status('h1', self.settings),
                     lambda: oz_manual.artifacts('h1', self.settings, target='package')):
            with patch.object(oz_manual, '_announced', False), patch('sys.stderr') as err:
                try:
                    call()
                except Exception:
                    pass
            written = ''.join(c.args[0] for c in err.write.call_args_list)
            self.assertIn(oz_manual.SCOPE.splitlines()[0], written)

    # ---- install ----

    def test_install_validates_and_installs_without_executing_anything(self):
        info = oz_manual.install(self.req, self.settings)
        self.assertEqual((info['request_id'], info['installed'], info['nodes']), ('h1', True, 3))
        flow = oz_manual._ReadFlow(self.ws / 'flows' / 'h1' / 'flow.sqlite')
        try:
            self.assertEqual([e['event'] for e in flow.events()], ['admitted'])
            self.assertEqual(flow.revisions(), {})
            self.assertEqual(flow.latest(), {})
        finally:
            flow.close()
        self.assertEqual(sorted(p.name for p in (self.ws / 'flows' / 'h1').glob('*') if p.suffix == '.sqlite'),
                         ['flow.sqlite'])
        self.assertFalse((self.ws / 'deliveries').exists())

    def test_install_is_idempotent_and_keeps_the_original_deadline(self):
        first = oz_manual.install(self.req, self.settings)
        time.sleep(0.05)
        again = oz_manual.install(self.req, self.settings)
        self.assertFalse(again['installed'])
        self.assertEqual((again['created_at'], again['deadline_at']), (first['created_at'], first['deadline_at']))
        self.assertAlmostEqual(first['deadline_at'] - first['created_at'], 3600, places=3)

    def test_installation_starts_the_deadline_and_a_later_run_does_not_restart_it(self):
        first = oz_manual.install(self.req, self.settings)
        time.sleep(0.05)
        result = oz_manual.run(self.req, self.settings)
        self.assertEqual(result['status'], 'delivered')
        self.assertEqual((result['flow']['created_at'], result['flow']['deadline_at']),
                         (first['created_at'], first['deadline_at']))

    def test_install_refuses_changed_work_under_the_same_request_id(self):
        oz_manual.install(self.req, self.settings)
        other = MH.request(self.src, deadline_seconds=7200)
        with self.assertRaisesRegex(Error, 'different flow request'):
            oz_manual.install(other, self.settings)
        with self.assertRaisesRegex(Error, 'different flow request'):
            oz_manual.run(other, self.settings)

    def test_install_rejects_an_invalid_request_and_creates_nothing(self):
        bad = dict(self.req, request_id='has space')
        with self.assertRaises(Error):
            oz_manual.install(bad, self.settings)
        broken = dict(self.req, graph=dict(self.req['graph'], nodes=[]))
        for call in (oz_manual.install, oz_manual.run):
            with self.assertRaises(Error):
                call(broken, self.settings)
        self.assertFalse(self.ws.exists())

    def test_oz_flow_admit_stays_validation_only(self):
        self.assertEqual(len(oz_flow.admit(self.req['graph'], self.settings.registry, effects=['local_publish'])), 3)
        self.assertFalse(self.ws.exists())

    # ---- run ----

    def test_run_delegates_to_run_flow_and_returns_its_result_unchanged(self):
        sentinel = {'schema': 'oz.flow.result/1', 'status': 'incomplete'}
        with patch.object(oz_manual, 'run_flow', return_value=sentinel) as run_flow:
            self.assertIs(oz_manual.run(self.req, self.settings), sentinel)
        run_flow.assert_called_once_with(self.req, self.settings)

    def test_run_delivers_installs_when_needed_and_repeating_changes_nothing(self):
        result = oz_manual.run(self.req, self.settings)
        self.assertEqual((result['schema'], result['status']), ('oz.flow.result/1', 'delivered'))
        self.assertEqual(result['targets']['package']['destination'], 'deliveries/h1/pub-g1')
        before = tree(self.ws)
        again = oz_manual.run(self.req, self.settings)
        self.assertEqual(again['status'], 'delivered')
        self.assertEqual(again['targets']['package']['artifacts'], result['targets']['package']['artifacts'])
        after = tree(self.ws)
        self.assertEqual(sorted(set(after) - set(before)), [])
        flow = oz_manual._ReadFlow(self.ws / 'flows' / 'h1' / 'flow.sqlite')
        try:
            self.assertEqual(len(flow.deliveries()), 1)
        finally:
            flow.close()

    # ---- the run lock ----

    def test_a_second_concurrent_run_fails_at_once_with_a_named_error(self):
        gate, entered = self.base / 'gate', self.base / 'entered'
        holder = subprocess.Popen([sys.executable, str(HELPERS), str(self.ws), str(self.src), 'run',
                                   '--gate', str(gate), '--entered', str(entered)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        try:
            end = time.time() + 30
            while not entered.exists() and time.time() < end:
                time.sleep(0.05)
            self.assertTrue(entered.exists(), 'the first run never reached its blocking node')
            started = time.time()
            second = helper(self.ws, self.src, 'run', '--gate', str(gate), '--entered', str(entered))
            self.assertLess(time.time() - started, 20)
            self.assertEqual(second.returncode, 2, second.stdout + second.stderr)
            self.assertIn('RunInProgress', second.stderr)
            self.assertIn('h1', second.stderr)
            in_process = None
            try:
                oz_manual.run(MH.request(self.src, gate_file=str(gate), entered_file=str(entered)), self.settings)
            except oz_manual.RunInProgress as exc:
                in_process = exc
            self.assertIsNotNone(in_process)
            self.assertIsInstance(in_process, oz_manual.ManualError)
            self.assertIsInstance(in_process, Error)
            reading = helper(self.ws, self.src, 'status', '--gate', str(gate), '--entered', str(entered))
            self.assertEqual(reading.returncode, 3, reading.stderr)  # reads are not blocked by the lock
        finally:
            gate.write_text('go', encoding='utf-8')
            out, err = holder.communicate(timeout=60)
        self.assertEqual(holder.returncode, 0, err)
        self.assertEqual(json.loads(out)['status'], 'delivered')
        # the lock is released when the holder ends: a later run resumes
        third = helper(self.ws, self.src, 'run', '--gate', str(gate), '--entered', str(entered))
        self.assertEqual(third.returncode, 0, third.stderr)

    def test_a_killed_runner_releases_the_lock(self):
        gate, entered = self.base / 'gate', self.base / 'entered'
        gate.write_text('open', encoding='utf-8')  # the blocking node passes at once; the kill comes at publication
        killed = helper(self.ws, self.src, 'run', '--gate', str(gate), '--entered', str(entered),
                        faults='flow.publish.after_manifest')
        self.assertEqual(killed.returncode, KILL, killed.stderr)
        again = helper(self.ws, self.src, 'run', '--gate', str(gate), '--entered', str(entered))
        self.assertEqual(again.returncode, 0, again.stderr)

    # ---- read-only status and artifacts ----

    def test_reads_of_a_missing_flow_fail_without_creating_a_single_file(self):
        for call in (lambda: oz_manual.status('h1', self.settings),
                     lambda: oz_manual.artifacts('h1', self.settings, target='package')):
            with self.assertRaises(oz_manual.FlowNotFound) as caught:
                call()
            self.assertIsInstance(caught.exception, oz_manual.ManualError)
            self.assertFalse(self.ws.exists())
        self.ws.mkdir()
        (self.ws / 'flows').mkdir()
        before = tree(self.ws)
        with self.assertRaises(oz_manual.FlowNotFound):
            oz_manual.status('h1', self.settings)
        self.assertEqual(tree(self.ws), before)
        self.assertEqual(sorted(p.name for p in (self.ws / 'flows').iterdir()), [])

    def test_reads_of_a_delivered_flow_leave_the_file_set_and_every_byte_alone(self):
        oz_manual.run(self.req, self.settings)
        before = tree(self.ws)
        self.assertEqual(sorted(k for k in before if k.startswith('flows/')),
                         ['flows/h1/execution-record.json', 'flows/h1/flow.sqlite', 'flows/h1/run.lock'])
        snapshot = oz_manual.status('h1', self.settings)
        delivered = oz_manual.artifacts('h1', self.settings, target='package')
        self.assertEqual(tree(self.ws), before)
        self.assertEqual(snapshot['status'], 'delivered')
        self.assertEqual(delivered['status'], 'current')

    def test_reads_of_an_interrupted_flow_change_neither_files_nor_database_bytes(self):
        killed = helper(self.ws, self.src, 'run', faults='flow.publish.after_manifest')
        self.assertEqual(killed.returncode, KILL, killed.stderr)
        before = tree(self.ws, ignore_shm=True)
        self.assertTrue(any(k.endswith('flow.sqlite-wal') for k in before), 'the kill left a write-ahead log')
        snapshot = oz_manual.status('h1', self.settings)
        self.assertEqual(snapshot['status'], 'incomplete')
        with self.assertRaises(oz_manual.ArtifactsUnavailable) as caught:
            oz_manual.artifacts('h1', self.settings, target='package')
        self.assertEqual(caught.exception.code, 'not_delivered')
        self.assertEqual(tree(self.ws, ignore_shm=True), before)

    def test_status_reports_targets_blocker_revisions_generations_launches_and_accounting(self):
        oz_manual.install(self.req, self.settings)
        pending = oz_manual.status('h1', self.settings)
        self.assertEqual(pending['schema'], 'oz.manual.status/1')
        self.assertEqual((pending['status'], pending['targets']), ('incomplete', {'package': {'status': 'unresolved',
                                                                                              'weight': 1}}))
        self.assertIsNone(pending['blocker'])
        self.assertEqual((pending['launches'], pending['accounting']['coverage']), (0, 'complete'))
        oz_manual.run(self.req, self.settings)
        done = oz_manual.status('h1', self.settings)
        self.assertEqual(done['status'], 'delivered')
        self.assertEqual(done['targets']['package']['destination'], 'deliveries/h1/pub-g1')
        self.assertEqual(done['flow']['revisions'], {'doc': 1})
        self.assertEqual(done['flow']['generations'], {'doc': 1, 'slow': 1, 'pub': 1})
        self.assertEqual((done['launches'], done['accounting']['calls_without_usage']), (0, 0))
        self.assertEqual(done['flow']['deadline_at'], pending['flow']['deadline_at'])
        self.assertGreater(done['flow']['deadline_remaining_seconds'], 3000)
        self.assertEqual(done['accounting']['unreconciled_dispatches'], 0)

    def test_status_never_extends_the_deadline_or_repairs_anything(self):
        killed = helper(self.ws, self.src, 'run', faults='flow.publish.after_manifest')
        self.assertEqual(killed.returncode, KILL)
        first = oz_manual.status('h1', self.settings)
        time.sleep(0.05)
        second = oz_manual.status('h1', self.settings)
        for key in ('created_at', 'deadline_at'):
            self.assertEqual(first['flow'][key], second['flow'][key])
        self.assertLess(second['flow']['deadline_remaining_seconds'], first['flow']['deadline_remaining_seconds'])
        self.assertTrue((self.ws / 'deliveries' / 'h1' / 'pub-g1').exists())  # the kill left its files; no repair

    def test_status_reports_the_blocker_of_the_latest_invocation(self):
        graph = json.loads(json.dumps(self.req['graph']))
        graph['nodes'][0]['in']['name'] = {'lit': 'refuse'}  # the host operation refuses this source
        refused = dict(self.req, request_id='h2', graph=graph)
        result = oz_manual.run(refused, self.settings)
        self.assertEqual(result['blocker']['reason'], 'host_refused')
        self.assertEqual(oz_manual.status('h2', self.settings)['blocker'], result['blocker'])
        self.assertIsNone(oz_manual.status('h2', self.settings)['targets']['package'].get('destination'))

    # ---- artifacts ----

    def test_artifacts_report_destination_paths_bytes_hashes_and_citations(self):
        oz_manual.run(self.req, self.settings)
        got = oz_manual.artifacts('h1', self.settings, target='package')
        self.assertEqual((got['schema'], got['status'], got['current'], got['generation']),
                         ('oz.manual.artifacts/1', 'current', True, 1))
        self.assertEqual((got['request_id'], got['target'], got['node']), ('h1', 'package', 'pub'))
        self.assertEqual(got['destination'], 'deliveries/h1/pub-g1')
        names = [a['name'] for a in got['artifacts']]
        self.assertEqual(names, ['manifest.json', 'notes.txt', 'out.txt'])
        out = next(a for a in got['artifacts'] if a['name'] == 'out.txt')
        data = (self.ws / 'deliveries' / 'h1' / 'pub-g1' / 'out.txt').read_bytes()
        self.assertEqual((out['path'], out['bytes'], out['sha256']),
                         ('deliveries/h1/pub-g1/out.txt', len(data), hashlib.sha256(data).hexdigest()))
        manifest = next(a for a in got['artifacts'] if a['name'] == 'manifest.json')
        self.assertEqual(got['manifest_sha256'], manifest['sha256'])
        self.assertEqual(got['citations'], {'doc': {'revision': 1, 'sha256': hashlib.sha256(
            b'first draft\n').hexdigest()}})
        self.assertNotIn('text', json.dumps(got))  # no body dump
        self.assertNotIn('FIRST DRAFT', json.dumps(got))
        self.assertEqual(oz_manual.artifacts('h1', self.settings), got)  # one output target needs no name

    def test_an_unknown_target_or_a_target_name_is_explicit(self):
        oz_manual.run(self.req, self.settings)
        with self.assertRaisesRegex(Error, 'unknown target'):
            oz_manual.artifacts('h1', self.settings, target='other')

    def test_a_missing_artifact_fails_explicitly_and_is_never_republished(self):
        oz_manual.run(self.req, self.settings)
        path = self.ws / 'deliveries' / 'h1' / 'pub-g1' / 'out.txt'
        path.unlink()
        with self.assertRaises(oz_manual.ArtifactsUnavailable) as caught:
            oz_manual.artifacts('h1', self.settings, target='package')
        self.assertEqual(caught.exception.code, 'missing')
        self.assertIn('out.txt', str(caught.exception))
        self.assertFalse(path.exists())

    def test_a_conflicting_artifact_fails_explicitly(self):
        oz_manual.run(self.req, self.settings)
        path = self.ws / 'deliveries' / 'h1' / 'pub-g1' / 'notes.txt'
        path.write_text('tampered\n', encoding='utf-8')
        with self.assertRaises(oz_manual.ArtifactsUnavailable) as caught:
            oz_manual.artifacts('h1', self.settings, target='package')
        self.assertEqual(caught.exception.code, 'conflict')
        self.assertEqual(path.read_text(encoding='utf-8'), 'tampered\n')

    def test_no_delivery_yet_is_not_found_and_not_a_success(self):
        oz_manual.install(self.req, self.settings)
        with self.assertRaises(oz_manual.ArtifactsUnavailable) as caught:
            oz_manual.artifacts('h1', self.settings, target='package')
        self.assertEqual(caught.exception.code, 'not_delivered')
        with self.assertRaises(oz_manual.ArtifactsUnavailable):
            oz_manual.artifacts('h1', self.settings, target='package', generation=1)

    # ---- revise ----

    def test_revise_adds_a_revision_without_executing_anything(self):
        oz_manual.run(self.req, self.settings)
        before = oz_manual.status('h1', self.settings)
        got = oz_manual.revise('h1', self.settings, 'doc', b'second draft\n', reason='edited')
        self.assertEqual((got['request_id'], got['source'], got['revision']), ('h1', 'doc', 2))
        self.assertEqual(got['sha256'], hashlib.sha256(b'second draft\n').hexdigest())
        after = oz_manual.status('h1', self.settings)
        self.assertEqual(after['flow']['revisions'], {'doc': 2})
        self.assertEqual(after['flow']['generations'], before['flow']['generations'])
        self.assertEqual(after['status'], 'incomplete')
        self.assertEqual(after['targets'], {'package': {'status': 'unresolved', 'weight': 1}})
        flow = oz_manual._ReadFlow(self.ws / 'flows' / 'h1' / 'flow.sqlite')
        try:
            events = flow.events()
            self.assertEqual(events[-1]['event'], 'source_revised')
            self.assertEqual(events[-1]['details']['reason'], 'edited')
            self.assertEqual(len(flow.deliveries()), 1)
        finally:
            flow.close()
        self.assertFalse((self.ws / 'deliveries' / 'h1' / 'pub-g2').exists())

    def test_revise_refuses_a_missing_flow_an_unknown_source_and_bad_arguments(self):
        with self.assertRaises(oz_manual.FlowNotFound):
            oz_manual.revise('h1', self.settings, 'doc', b'x', reason='r')
        self.assertFalse(self.ws.exists())
        oz_manual.install(self.req, self.settings)
        with self.assertRaisesRegex(Error, 'unknown source'):
            oz_manual.revise('h1', self.settings, 'doc', b'x', reason='r')  # not imported until a run reads it
        oz_manual.run(self.req, self.settings)
        with self.assertRaisesRegex(Error, 'unknown source'):
            oz_manual.revise('h1', self.settings, 'other', b'x', reason='r')
        for bad in (dict(data='text'), dict(reason=''), dict(reason=None), dict(source='')):
            kwargs = dict(source='doc', data=b'x', reason='r')
            kwargs.update(bad)
            with self.assertRaises(Error):
                oz_manual.revise('h1', self.settings, **kwargs)

    def test_run_revise_run_artifacts_delivers_g2_and_reports_g1_as_superseded(self):
        first = oz_manual.run(self.req, self.settings)
        g1 = oz_manual.artifacts('h1', self.settings, target='package')
        self.assertEqual((g1['generation'], g1['status']), (1, 'current'))
        oz_manual.revise('h1', self.settings, 'doc', b'second draft\n', reason='edited')
        with self.assertRaises(oz_manual.ArtifactsUnavailable) as stale:
            oz_manual.artifacts('h1', self.settings, target='package')
        self.assertEqual(stale.exception.code, 'stale')
        pinned = oz_manual.artifacts('h1', self.settings, target='package', generation=1)
        self.assertEqual((pinned['status'], pinned['current']), ('superseded', False))
        self.assertEqual(pinned['stale_sources'], {'doc': {'cited': 1, 'current': 2}})
        second = oz_manual.run(self.req, self.settings)
        self.assertEqual(second['status'], 'delivered')
        self.assertEqual(second['flow']['deadline_at'], first['flow']['deadline_at'])
        g2 = oz_manual.artifacts('h1', self.settings, target='package')
        self.assertEqual((g2['generation'], g2['status'], g2['destination']), (2, 'current', 'deliveries/h1/pub-g2'))
        self.assertEqual(g2['citations']['doc']['revision'], 2)
        old = oz_manual.artifacts('h1', self.settings, target='package', generation=1)
        self.assertEqual((old['status'], old['current']), ('superseded', False))
        self.assertEqual(old['superseded_by']['generation'], 2)
        self.assertEqual(old['destination'], 'deliveries/h1/pub-g1')
        self.assertEqual((self.ws / 'deliveries' / 'h1' / 'pub-g1' / 'out.txt').read_text(encoding='utf-8'),
                         'FIRST DRAFT\n\n')
        self.assertEqual((self.ws / 'deliveries' / 'h1' / 'pub-g2' / 'out.txt').read_text(encoding='utf-8'),
                         'SECOND DRAFT\n\n')
        with self.assertRaises(oz_manual.ArtifactsUnavailable):
            oz_manual.artifacts('h1', self.settings, target='package', generation=3)
        flow = oz_manual._ReadFlow(self.ws / 'flows' / 'h1' / 'flow.sqlite')
        try:
            self.assertEqual(len(flow.deliveries()), 2)
            self.assertEqual(flow.db.execute("SELECT COUNT(*) FROM acceptances WHERE node='doc'").fetchone()[0], 2)
        finally:
            flow.close()


class PinTests(unittest.TestCase):
    """The example copies exactly the files it needs from bench/o1 and never edits the frozen sources."""

    COPIES = ('workflow.py', 'sandbox.py', 'sandbox_worker.py', 'fixture_adapter.py',
              'fixture/A_rev1.py', 'fixture/A_rev2.py', 'fixture/B.py', 'fixture/C.py', 'fixture/D.py',
              'repair-handoff-20-v1/policy.json', 'repair-handoff-20-v1/workflow.json',
              'repair-handoff-20-v1/graph.json', 'repair-handoff-20-v1/tier_a.json',
              'repair-handoff-20-v1/tier_i.json', 'repair-handoff-20-v1/tickets/A.rev1.json',
              'repair-handoff-20-v1/tickets/A.rev2.json', 'repair-handoff-20-v1/tickets/B.rev1.json',
              'repair-handoff-20-v1/tickets/C.rev1.json', 'repair-handoff-20-v1/tickets/D.rev1.json')

    def test_each_copy_is_byte_identical_to_its_frozen_source(self):
        for rel in self.COPIES:
            copy, source = EXAMPLE_DIR / rel, ROOT / 'bench' / 'o1' / rel
            self.assertTrue(copy.is_file(), rel)
            self.assertTrue(source.is_file(), rel)
            self.assertEqual(copy.read_bytes(), source.read_bytes(), rel)

    def test_the_example_holds_nothing_but_its_script_and_the_pinned_copies(self):
        found = sorted(p.relative_to(EXAMPLE_DIR).as_posix() for p in EXAMPLE_DIR.rglob('*')
                       if p.is_file() and '__pycache__' not in p.parts)
        self.assertEqual(found, sorted(self.COPIES + ('example.py',)))

    def test_the_copies_sit_at_the_depth_their_relative_paths_assume(self):
        self.assertEqual(EXAMPLE_DIR.parents[1], ROOT)
        self.assertEqual((ROOT / 'bench' / 'o1').parents[1], ROOT)

    def test_the_example_script_neither_imports_nor_points_at_bench(self):
        tree_ = ast.parse(EXAMPLE.read_text(encoding='utf-8'))
        doc = tree_.body[0].value
        for node in ast.walk(tree_):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, 'module', None) or '']
                self.assertFalse([n for n in names if 'bench' in n], names)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node is not doc:
                self.assertNotIn('bench', node.value.replace('bench-grade', ''), node.value)

    def test_the_o1_freeze_still_holds(self):
        proc = subprocess.run([sys.executable, str(ROOT / 'bench' / 'o1' / 'o1.py'), 'freeze'], capture_output=True,
                              text=True, encoding='utf-8')
        self.assertEqual(proc.returncode, 0, proc.stdout[-600:])

    def test_usage_documents_the_facade_and_the_deadline(self):
        text = (ROOT / 'USAGE.md').read_text(encoding='utf-8')
        section = text.split('## Manual graph facade', 1)[1]
        for word in ('oz_manual', 'install', 'run', 'revise', 'status', 'artifacts', 'Windows-only',
                     'starts the deadline', 'oz_flow.admit', 'experimental'):
            self.assertIn(word, section, word)


def log_of(path) -> list:
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()] \
        if Path(path).exists() else []


@unittest.skipUnless(os.name == 'nt', WINDOWS_ONLY)
class AcceptanceGate(unittest.TestCase):
    """The zero-token acceptance gate: the documented path only, from empty workspaces, on the fixture route."""

    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='oz-manual-gate-'))
        cls.log = cls.base / 'guard.jsonl'
        cls.runs = {}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    @classmethod
    def example(cls, ws, *args, faults='', request_id=None):
        env = dict(os.environ, OZ_FAULTS=faults, PYTHONIOENCODING='utf-8', MANUAL_GUARD_LOG=str(cls.log))
        env.pop('OZ_FIXTURE_DIR', None)
        env.pop('OZ_MODEL', None)
        cache = Path(env.get('TIKTOKEN_CACHE_DIR') or ROOT / '.token-cache')
        if cache.is_dir():  # tiktoken is optional; when present its encoding must come from the local cache
            env['TIKTOKEN_CACHE_DIR'] = str(cache.resolve())
        cmd = [sys.executable, str(GUARD), str(EXAMPLE), '--workspace', str(ws)]
        if request_id:
            cmd += ['--request-id', request_id]
        proc = subprocess.run(cmd + list(args), env=env, capture_output=True, text=True, encoding='utf-8',
                              cwd=str(cls.base))
        proc.json = json.loads(proc.stdout) if proc.stdout.strip() else None
        return proc

    @classmethod
    def ws(cls, name):
        return cls.base / name / 'ws'

    @classmethod
    def once(cls, key, build):
        if key not in cls.runs:
            cls.runs[key] = build()
        return cls.runs[key]

    # ---- shared scenarios ----

    @classmethod
    def clean(cls):
        def build():
            first = cls.example(cls.ws('clean'), 'run')
            return {'first': first, 'repeat': cls.example(cls.ws('clean'), 'run')}
        return cls.once('clean', build)

    @classmethod
    def interrupted(cls):
        def build():
            ws = cls.ws('interrupt')
            runs = [cls.example(ws, 'run', faults='worker.after_capture')]
            runs.append(cls.example(ws, 'status'))
            runs.append(cls.example(ws, 'run', faults='flow.publish.after_manifest'))
            runs.append(cls.example(ws, 'run'))
            return runs
        return cls.once('interrupt', build)

    @classmethod
    def user_stale(cls):
        def build():
            ws = cls.ws('stale')
            steps = {'run1': cls.example(ws, 'run'), 'artifacts1': cls.example(ws, 'artifacts')}
            steps['revise'] = cls.example(ws, 'revise', '--source', 'A', '--file',
                                          str(EXAMPLE_DIR / 'repair-handoff-20-v1' / 'tickets' / 'A.rev2.json'),
                                          '--reason', 'ticket A revision 2')
            steps['status_after_revise'] = cls.example(ws, 'status')
            steps['artifacts_stale'] = cls.example(ws, 'artifacts')
            steps['artifacts_g1_pinned'] = cls.example(ws, 'artifacts', '--generation', '1')
            steps['run2'] = cls.example(ws, 'run')
            steps['artifacts2'] = cls.example(ws, 'artifacts')
            steps['artifacts_g1_after'] = cls.example(ws, 'artifacts', '--generation', '1')
            return steps
        return cls.once('stale', build)

    @classmethod
    def hook_stale(cls):
        return cls.once('hook', lambda: cls.example(cls.ws('hook'), 'run', '--mutate-stale-a'))

    @staticmethod
    def invocations(ws) -> list:
        path = Path(ws) / 'fixture' / 'invocations.jsonl'
        return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def independent_check(self, ws, request_id, destination, revisions):
        """The bench evaluator, loaded the way tests/test_o1.py loads it, judging a delivered package against the
        accepted sources the flow holds (A, I and H tiers, byte provenance, patch, provenance file)."""
        o1 = ROOT / 'bench' / 'o1'
        saved = {n: sys.modules.pop(n) for n in ('workflow', 'evaluator', 'fixture_adapter') if n in sys.modules}
        added = [str(o1 / 'evaluator'), str(o1)]
        sys.path[:0] = added
        try:
            import evaluator as E
            flow = oz_manual._ReadFlow(Path(ws) / 'flows' / request_id / 'flow.sqlite')
            try:
                latest = flow.latest()
            finally:
                flow.close()
            accepted = {n: json.loads(a['value']) for n, a in latest.items()
                        if n.startswith(('core_', 'adapter_'))}
            return E.evaluate_package(Path(ws) / destination, revisions, accepted)
        finally:
            for p in added:
                sys.path.remove(p)
            sys.modules.pop('evaluator', None)
            sys.modules.update(saved)

    # ---- the gate ----

    def test_stored_fixture_replies_pass_acceptance_and_the_independent_artifact_checks(self):
        proc = self.clean()['first']
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        out = proc.json
        result = out['result']
        self.assertEqual((result['schema'], result['status']), ('oz.flow.result/1', 'delivered'))
        self.assertEqual(result['launches'], 2)
        self.assertEqual(result['accounting']['coverage'], 'complete')
        target = result['targets']['repair_package']
        check = self.independent_check(self.ws('clean'), 'manual-o1', target['destination'],
                                       {'A': 1, 'B': 1, 'C': 1, 'D': 1})
        self.assertTrue(check['verified'], check['errors'])
        # the stored fixture replies are retained captures; their reported usage is not new billed usage
        fixture = out['fixture']
        self.assertEqual((fixture['route'], fixture['model_calls'], fixture['new_billed_tokens']), ('fixture', 0, 0))
        self.assertEqual((fixture['fixture_invocations_total'], fixture['fixture_invocations_this_call']), (2, 2))
        self.assertGreater(fixture['capture_usage_tokens_reported'], 0)
        captures = list(self.ws('clean').glob('**/captures/*.done'))
        self.assertEqual(len(captures), 2)
        record = json.loads((self.ws('clean') / 'flows' / 'manual-o1' / 'execution-record.json').read_text('utf-8'))
        dispatches = [d for s in record['stages'] for d in s['dispatches']]
        self.assertEqual([d['state'] for d in dispatches], ['captured', 'captured'])
        self.assertTrue(all(d['capture_sha256'] for d in dispatches))
        self.assertEqual({d['route']['effort'] for d in dispatches}, {'fixture'})

    def test_the_notices_go_to_stderr_and_stdout_is_one_clean_json_document(self):
        proc = self.clean()['first']
        lines = proc.stderr.splitlines()
        for line in (*oz_manual.SCOPE.splitlines(), 'route=fixture; model_calls=0; new_billed_tokens=0',
                     'workflow=repair-handoff-20/v1; experimental_sizes=1,4'):
            self.assertEqual(lines.count(line), 1, (line, proc.stderr))
        self.assertIn('windows-only', proc.stderr)
        self.assertIn('bench-grade confinement', proc.stderr)
        json.loads(proc.stdout)
        self.assertEqual(proc.stdout.count('\n'), 1)
        self.assertNotIn('route=fixture', proc.stdout.replace('"route": "fixture"', ''))

    def test_both_o1_packet_sizes_stay_experimental(self):
        self.clean()
        labels = []
        for log in sorted(self.ws('clean').glob('**/do.jsonl')):
            labels += [json.loads(x)['profile'] for x in log.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(labels, ['experimental', 'experimental'])
        stale = self.hook_stale()
        self.assertEqual(stale.returncode, 0, stale.stderr[-400:])
        labels = []
        for log in sorted(self.ws('hook').glob('**/do.jsonl')):
            labels += [json.loads(x)['profile'] for x in log.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(labels, ['experimental'] * 4)  # sizes 4, 4, 1 and 1

    def test_repeating_completed_work_makes_no_adapter_invocation(self):
        runs = self.clean()
        again = runs['repeat']
        self.assertEqual(again.returncode, 0, again.stderr[-800:])
        self.assertEqual(again.json['result']['status'], 'delivered')
        self.assertEqual(again.json['fixture']['fixture_invocations_this_call'], 0)
        self.assertEqual(again.json['fixture']['fixture_invocations_total'], 2)
        self.assertEqual(again.json['result']['targets'], runs['first'].json['result']['targets'])
        self.assertEqual(len(self.invocations(self.ws('clean'))), 2)

    def test_conflicting_request_reuse_fails_with_a_named_error(self):
        self.clean()
        before = tree(self.ws('clean'))
        for command in ('install', 'run'):
            bad = self.example(self.ws('clean'), command, '--deadline-seconds', '7200')
            self.assertEqual(bad.returncode, 2, bad.stderr[-400:])
            self.assertEqual(bad.stdout, '')
            self.assertIn('different flow request', bad.stderr)
        self.assertEqual(tree(self.ws('clean')), before)

    def test_install_is_idempotent_and_executes_nothing(self):
        ws = self.base / 'install_twice' / 'ws'
        first = self.example(ws, 'install')
        again = self.example(ws, 'install')
        self.assertEqual((first.returncode, again.returncode), (0, 0), first.stderr[-400:] + again.stderr[-400:])
        self.assertTrue(first.json['result']['installed'])
        self.assertFalse(again.json['result']['installed'])
        self.assertEqual(first.json['result']['deadline_at'], again.json['result']['deadline_at'])
        self.assertEqual(self.invocations(ws), [])
        self.assertEqual(first.json['fixture']['fixture_invocations_total'], 0)

    def test_status_and_artifacts_reads_cause_no_execution_and_change_nothing(self):
        self.clean()
        before = tree(self.ws('clean'))
        status = self.example(self.ws('clean'), 'status')
        artifacts = self.example(self.ws('clean'), 'artifacts')
        self.assertEqual((status.returncode, artifacts.returncode), (0, 0), status.stderr[-400:])
        self.assertEqual(tree(self.ws('clean')), before)
        self.assertEqual(status.json['result']['status'], 'delivered')
        self.assertEqual(artifacts.json['result']['status'], 'current')
        self.assertEqual(status.json['fixture']['fixture_invocations_total'], 2)
        names = [a['name'] for a in artifacts.json['result']['artifacts']]
        self.assertEqual(names, ['amounts.py', 'config_patch.py', 'intervals.py', 'jobs.py', 'manifest.json',
                                 'provenance.json', 'repair.patch', 'verification.md'])
        self.assertNotIn('def ', artifacts.stdout)

    def test_a_missing_delivery_cannot_appear_successful(self):
        ws = self.base / 'fresh_reads' / 'ws'
        for command in (('status',), ('artifacts',)):
            got = self.example(ws, *command)
            self.assertEqual(got.returncode, 2)
            self.assertIn('FlowNotFound', got.stderr)
            self.assertEqual(got.stdout, '')
        self.assertFalse(ws.exists())
        self.assertFalse(ws.parent.exists())
        installed = self.base / 'installed' / 'ws'
        if not installed.exists():
            self.example(installed, 'install')
        got = self.example(installed, 'artifacts')
        self.assertEqual(got.returncode, 2)
        self.assertIn('ArtifactsUnavailable', got.stderr)
        self.assertIn('not_delivered', got.stderr)
        self.assertEqual(got.stdout, '')

    def test_a_deleted_or_altered_delivered_file_is_reported_not_republished(self):
        self.clean()
        ws = self.base / 'damaged' / 'ws'
        shutil.copytree(self.ws('clean'), ws)
        dest = ws / 'deliveries' / 'manual-o1' / 'publish-g1'
        (dest / 'jobs.py').unlink()
        (dest / 'amounts.py').write_bytes((dest / 'amounts.py').read_bytes() + b'#')
        before = tree(ws)
        got = self.example(ws, 'artifacts')
        self.assertEqual(got.returncode, 2)
        self.assertEqual(got.stdout, '')
        self.assertRegex(got.stderr, r'ArtifactsUnavailable.*(missing|conflict)')
        self.assertEqual(tree(ws), before)
        self.assertFalse((dest / 'jobs.py').exists())

    def test_hard_exits_recover_the_capture_and_reconcile_publication_without_duplicates(self):
        runs = self.interrupted()
        ws = self.ws('interrupt')
        killed1, status, killed2, done = runs
        self.assertEqual((killed1.returncode, killed2.returncode, done.returncode), (KILL, KILL, 0),
                         (killed1.stderr[-300:], killed2.stderr[-300:], done.stderr[-600:]))
        # after the first hard exit one stage call was made and its captured reply is on disk, unaccepted
        self.assertEqual(status.returncode, 0, status.stderr[-400:])
        self.assertEqual(status.json['result']['status'], 'incomplete')
        self.assertEqual(status.json['fixture']['fixture_invocations_total'], 1)
        self.assertEqual(status.json['result']['launches'], 1)
        self.assertEqual(status.json['result']['accounting']['unreconciled_dispatches'], 1)
        # the second hard exit came after both stage replies were accepted and the manifest was written
        self.assertEqual(done.json['fixture']['fixture_invocations_total'], 2)
        self.assertEqual(done.json['fixture']['fixture_invocations_this_call'], 0)
        self.assertEqual(len(self.invocations(ws)), 2)
        result = done.json['result']
        self.assertEqual((result['status'], result['launches']), ('delivered', 2))
        flow = oz_manual._ReadFlow(ws / 'flows' / 'manual-o1' / 'flow.sqlite')
        try:
            events = flow.events()
            deliveries = flow.deliveries()
            info = flow.info()
        finally:
            flow.close()
        self.assertEqual(len(deliveries), 1)
        self.assertEqual([e['event'] for e in events].count('delivered'), 1)
        exported = [e for e in events if e['event'] == 'effect_exported']
        self.assertGreaterEqual(len(exported), 2)
        self.assertEqual(sorted(exported[-1]['details']['detail']['reconciled']),
                         sorted(a for a in result['targets']['repair_package']['artifacts']))
        self.assertAlmostEqual(info['deadline_at'] - info['created_at'], 3600, places=2)
        self.assertEqual(result['flow']['deadline_at'], info['deadline_at'])
        check = self.independent_check(ws, 'manual-o1', result['targets']['repair_package']['destination'],
                                       {'A': 1, 'B': 1, 'C': 1, 'D': 1})
        self.assertTrue(check['verified'], check['errors'])

    def test_run_revise_run_artifacts_delivers_g2_reuses_bcd_and_reports_g1_superseded(self):
        s = self.user_stale()
        ws = self.ws('stale')
        for key in ('run1', 'artifacts1', 'revise', 'status_after_revise', 'artifacts_g1_pinned', 'run2',
                    'artifacts2', 'artifacts_g1_after'):
            self.assertEqual(s[key].returncode, 0, (key, s[key].stderr[-500:]))
        self.assertEqual(s['artifacts1'].json['result']['generation'], 1)
        self.assertEqual(s['revise'].json['result']['revision'], 2)
        # no execution between the revision and the next run
        self.assertEqual(s['revise'].json['fixture']['fixture_invocations_total'], 2)
        after = s['status_after_revise'].json
        self.assertEqual(after['result']['status'], 'incomplete')
        self.assertEqual(after['result']['flow']['revisions']['A'], 2)
        self.assertEqual(after['fixture']['fixture_invocations_total'], 2)
        # the old delivery is no longer current, and a plain read says so explicitly
        self.assertEqual(s['artifacts_stale'].returncode, 2)
        self.assertIn('ArtifactsUnavailable', s['artifacts_stale'].stderr)
        self.assertIn('stale', s['artifacts_stale'].stderr)
        pinned = s['artifacts_g1_pinned'].json['result']
        self.assertEqual((pinned['status'], pinned['current'], pinned['generation']), ('superseded', False, 1))
        # run 2 asks the model only for the changed ticket: core_A and then adapter_A, size one packets
        calls = self.invocations(ws)
        self.assertEqual([c['ids'] for c in calls], [['core_A', 'core_B', 'core_C', 'core_D'],
                                                     ['adapter_A', 'adapter_B', 'adapter_C', 'adapter_D'],
                                                     ['core_A'], ['adapter_A']])
        self.assertEqual(s['run2'].json['fixture']['fixture_invocations_this_call'], 2)
        result = s['run2'].json['result']
        self.assertEqual(result['status'], 'delivered')
        g2 = s['artifacts2'].json['result']
        self.assertEqual((g2['generation'], g2['status'], g2['current']), (2, 'current', True))
        self.assertEqual(g2['destination'], 'deliveries/manual-o1/publish-g2')
        self.assertEqual(g2['citations']['A']['revision'], 2)
        self.assertEqual({k: v['revision'] for k, v in g2['citations'].items()}, {'A': 2, 'B': 1, 'C': 1, 'D': 1})
        old = s['artifacts_g1_after'].json['result']
        self.assertEqual((old['status'], old['current'], old['generation']), ('superseded', False, 1))
        self.assertEqual(old['superseded_by']['generation'], 2)
        self.assertEqual(old['destination'], 'deliveries/manual-o1/publish-g1')
        self.assertEqual(old['citations']['A']['revision'], 1)
        self.assertEqual(result['flow']['generations']['publish'], 2)
        check = self.independent_check(ws, 'manual-o1', g2['destination'], {'A': 2, 'B': 1, 'C': 1, 'D': 1})
        self.assertTrue(check['verified'], check['errors'])
        db = sqlite3.connect(ws.resolve().joinpath('flows', 'manual-o1', 'flow.sqlite').as_uri() + '?mode=ro',
                             uri=True)
        try:
            history = db.execute("SELECT generation, COUNT(*) FROM acceptances WHERE node='snapshot' "
                                 "GROUP BY generation ORDER BY generation").fetchall()
            self.assertEqual(history, [(1, 1), (2, 1)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM deliveries').fetchone()[0], 2)
        finally:
            db.close()

    def test_the_mid_run_stale_a_mutation_blocks_the_old_delivery_and_delivers_a_revision_2(self):
        proc = self.hook_stale()
        ws = self.ws('hook')
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        result = proc.json['result']
        self.assertEqual(result['status'], 'delivered')
        self.assertEqual(result['flow']['revisions']['A'], 2)
        calls = self.invocations(ws)
        self.assertEqual([c['ids'] for c in calls], [['core_A', 'core_B', 'core_C', 'core_D'],
                                                     ['adapter_A', 'adapter_B', 'adapter_C', 'adapter_D'],
                                                     ['core_A'], ['adapter_A']])
        flow = oz_manual._ReadFlow(ws / 'flows' / 'manual-o1' / 'flow.sqlite')
        try:
            self.assertEqual(len(flow.deliveries()), 1)  # the stale package was never delivered
            events = [e['event'] for e in flow.events()]
            self.assertIn('source_revised', events)
            self.assertEqual(flow.db.execute("SELECT COUNT(*) FROM acceptances WHERE node='snapshot'").fetchone()[0], 2)
            citations = flow.deliveries()[0]['cites']
        finally:
            flow.close()
        self.assertEqual(citations['A'], 2)
        dest = result['targets']['repair_package']['destination']
        check = self.independent_check(ws, 'manual-o1', dest, {'A': 2, 'B': 1, 'C': 1, 'D': 1})
        self.assertTrue(check['verified'], check['errors'])

    def test_no_provider_executable_and_no_network_call_occurs(self):
        for key in ('clean', 'interrupt', 'stale', 'hook'):
            {'clean': self.clean, 'interrupt': self.interrupted, 'stale': self.user_stale, 'hook': self.hook_stale}[key]()
        events = log_of(self.log)
        self.assertFalse([e for e in events if 'network' in e], events[:3])
        spawns = [e['spawn'] for e in events if 'spawn' in e]
        self.assertTrue(spawns)
        for argv in spawns:
            self.assertTrue(Path(argv[0]).name.lower().startswith('python'), argv)
            self.assertFalse(any('claude' in part.lower() for part in argv), argv)
        runners = [a for a in spawns if Path(a[1]).name == 'oz_runner.py']
        confined = [a for a in spawns if a[1:5] == ['-P', '-S', '-s', '-B']]  # the O1 sandbox launcher
        self.assertEqual(len(runners) + len(confined), len(spawns), spawns[:3])
        self.assertGreaterEqual(len(runners), 8)
        for argv in runners:  # the runner starts the configured adapter, which is the fixture script and nothing else
            command = argv[argv.index('--') + 1:]
            self.assertEqual(Path(command[1]).name, 'fixture_adapter.py', argv)
        config = json.loads((self.ws('clean') / 'adapter-fixture.json').read_text(encoding='utf-8'))
        self.assertEqual([Path(x).name for x in config['argv'][1:]], ['fixture_adapter.py'])

    def test_fixture_invocations_are_reported_apart_from_zero_new_model_calls(self):
        out = self.clean()['first'].json
        fixture = out['fixture']
        self.assertEqual(fixture['model_calls'], 0)
        self.assertEqual(fixture['new_billed_tokens'], 0)
        self.assertEqual(fixture['fixture_invocations_total'], len(self.invocations(self.ws('clean'))))
        self.assertGreater(fixture['capture_usage_tokens_reported'], 0)
        self.assertEqual(fixture['capture_usage_tokens_reported'], out['result']['accounting']['tokens_known'])

    def test_read_only_usage_matches_the_service_layers_own_accounting(self):
        self.clean()
        self.interrupted()
        for name in ('clean', 'interrupt'):
            ws = self.ws(name)
            copy = self.base / ('parity-' + name)
            shutil.copytree(ws, copy)
            expect = oz_flow.flow_usage(copy, 'manual-o1')
            got = oz_manual._usage(ws, 'manual-o1')
            self.assertEqual(got, expect)


if __name__ == '__main__':
    unittest.main()
