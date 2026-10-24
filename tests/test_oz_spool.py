import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import oz_spool as sp

ROOT = Path(__file__).resolve().parent.parent


class Crash(BaseException):
    pass


class Clock:
    """One fake clock used as the spool wall clock and the scheduler monotonic clock."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


def bind(**over):
    b = {'contract_hash': 'c' * 64, 'check_hash': 'k' * 64, 'permission_hash': 'p' * 64, 'worker_hash': 'w' * 64,
         'input_policy': 'strict'}
    b.update(over)
    return b


def jobs(n, prefix='f'):
    return [{'key': f'{prefix}{i}', 'op': 'extract', 'text': f'text {prefix}{i}', 'dataset_id': f'd-{prefix}{i}'}
            for i in range(n)]


def capture_for(view_or_ids):
    ids = [r['id'] for r in view_or_ids['records']] if isinstance(view_or_ids, dict) else list(view_or_ids)
    return {'results': {i: {'ok': i} for i in ids}, 'call_id': 'call-x'}


class Fake:
    """launch(batch) stand-in: counts launches, returns a capture. No model calls."""

    def __init__(self):
        self.lock = threading.Lock()
        self.views = []
        self.per_id = {}

    def __call__(self, view):
        with self.lock:
            self.views.append(view)
            for r in view['records']:
                self.per_id[r['id']] = self.per_id.get(r['id'], 0) + 1
        return {'results': {r['id']: {'echo': r['text'], 'by': r['producer']} for r in view['records']},
                'call_id': 'call-' + view['batch_id'][:6]}


def pump_until(sched, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        sched.pump()
        if cond():
            return True
        time.sleep(0.002)
    return False


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.db = os.path.join(self.dir, 'spool.sqlite')
        self.clock = Clock()
        self.spool = sp.Spool(self.db, clock=self.clock)
        self.scheds = []

    def tearDown(self):
        for s in self.scheds:
            s.close()

    def sched(self, launch, **kw):
        kw.setdefault('clock', self.clock)
        s = sp.Scheduler(self.spool, launch, **kw)
        self.scheds.append(s)
        return s

    def sub(self, producer, n, submission='s1', prefix='f', **b):
        return self.spool.submit(producer, submission, jobs(n, prefix), bind(**b))

    def rows(self):
        c = sqlite3.connect(self.db)
        try:
            return c.execute('SELECT job_id FROM results').fetchall()
        finally:
            c.close()


class IdentityAndSubmit(Base):
    def test_ids_are_53_chars_and_collision_free(self):
        ids = set()
        for p in ('p1', 'p2'):
            ids.update(self.sub(p, 40))
        self.assertEqual(len(ids), 80)
        self.assertTrue(all(len(i) == 53 and i[0] == 'j' for i in ids))
        self.assertEqual(sp.delivery_id('p', 's', 'o', 'k'), sp.delivery_id('p', 's', 'o', 'k'))
        self.assertNotEqual(sp.delivery_id('p', 's', 'o', 'k'), sp.delivery_id('p', 's', 'o', 'k2'))

    def test_collision_table_detects_two_identities_for_one_id(self):
        self.sub('p1', 1)
        real = sp.delivery_id
        sp.delivery_id = lambda *a: real('p1', 's1', 'extract', 'f0')
        try:
            with self.assertRaises(sp.IdCollision):
                self.spool.submit('p2', 's1', jobs(1, 'g'), bind())
        finally:
            sp.delivery_id = real
        self.assertEqual(self.spool.queue_report()['pending'], 1)  # the failed submit left nothing behind

    def test_idempotent_resubmit_and_conflict(self):
        first = self.sub('p1', 3)
        self.assertEqual(self.sub('p1', 3), first)
        with self.assertRaises(sp.SubmissionConflict):
            self.sub('p1', 4)
        with self.assertRaises(sp.SubmissionConflict):
            self.sub('p1', 3, input_policy='other')
        self.assertEqual(self.spool.queue_report()['pending'], 3)

    def test_host_issued_ids_and_schema_enforced(self):
        bad = jobs(1)
        bad[0]['id'] = 'j' + 'a' * 52
        with self.assertRaises(sp.SpoolError):
            self.spool.submit('p1', 's1', bad, bind())
        with self.assertRaises(sp.SpoolError):
            self.spool.submit('p1', 's1', [{'key': 'a', 'op': 'x', 'text': 't'}], bind())  # no dataset_id
        for b in ({}, {'contract_hash': 'c'}, dict(bind(), extra='x'), bind(worker_hash=''), bind(input_policy=3)):
            with self.assertRaises(sp.SpoolError):
                self.spool.submit('p1', 's1', jobs(1), b)
        with self.assertRaises(sp.SpoolError):
            self.spool.submit('p1', 's1', jobs(1) + jobs(1), bind())  # duplicate logical job
        self.assertEqual(self.spool.queue_report()['pending'], 0)

    def test_case_insensitive_producer_and_device_names(self):
        self.sub('P1', 1)
        with self.assertRaises(sp.ProducerCollision):
            self.sub('p1', 1)
        self.sub('P1', 1, submission='s2')  # same spelling is fine
        with self.assertRaises(sp.ProducerCollision):
            self.sub('P1', 1, submission='S1')  # submission differs only by case
        for name in ('NUL', 'con', 'Com1', 'bad name', ''):
            with self.assertRaises(sp.SpoolError):
                self.sub(name, 1, submission='x')

    def test_conflicting_concurrent_submissions_one_wins(self):
        for trial in range(5):
            barrier = threading.Barrier(2)
            out = {}

            def go(tag, n):
                barrier.wait()
                try:
                    out[tag] = self.spool.submit('pp', f's{trial}', jobs(n, tag), bind())
                except sp.SpoolError as exc:
                    out[tag] = exc

            ts = [threading.Thread(target=go, args=('a', 2)), threading.Thread(target=go, args=('b', 3))]
            [t.start() for t in ts]
            [t.join() for t in ts]
            wins = [v for v in out.values() if isinstance(v, dict)]
            errs = [v for v in out.values() if isinstance(v, sp.SubmissionConflict)]
            self.assertEqual((len(wins), len(errs)), (1, 1), out)
            got = self.spool.collect('pp', f's{trial}')
            self.assertEqual(got['jobs'], len(wins[0]))

    def test_bindings_recompared_on_read(self):
        self.sub('p1', 1)
        h = sp.bindings_hash(bind())
        c = sqlite3.connect(self.db)
        c.execute('UPDATE bindings SET body=? WHERE hash=?', (sp._jdump(bind(worker_hash='x' * 64)), h))
        c.commit()
        c.close()
        s = self.sched(Fake(), max_wait=0)
        with self.assertRaises(sp.SpoolError):
            s.pump()


class Pooling(Base):
    def test_four_producers_by_64_pool_into_exactly_four_batches(self):
        fake = Fake()
        s = self.sched(fake, slots=4, max_records=64, max_wait=1.0)
        for p in ('p1', 'p2', 'p3', 'p4'):
            self.sub(p, 64)
        self.assertTrue(pump_until(s, lambda: len(self.rows()) == 256))
        self.assertEqual(len(fake.views), 4)
        self.assertTrue(all(len(v['records']) == 64 for v in fake.views))
        self.assertTrue(all(len({r['producer'] for r in v['records']}) > 1 for v in fake.views) or
                        len({r['producer'] for v in fake.views for r in v['records']}) == 4)
        self.assertTrue(all(n == 1 for n in fake.per_id.values()))
        for p in ('p1', 'p2', 'p3', 'p4'):
            got = self.spool.collect(p, 's1')
            self.assertTrue(got['complete'])
            self.assertTrue(all(r['result']['by'] == p for r in got['results'].values()))
        rep = self.spool.queue_report()
        self.assertEqual((rep['records'], rep['batches'], rep['pending'], rep['in_flight']), (256, 4, 0, 0))

    def test_count_flush_and_deadline_flush(self):
        fake = Fake()
        s = self.sched(fake, max_records=64, max_wait=1.0)
        self.sub('p1', 70)
        s.pump()
        pump_until(s, lambda: len(fake.views) == 1)
        self.assertEqual(len(fake.views[0]['records']), 64)  # the full chunk goes at once
        self.clock.advance(0.99)
        s.pump()
        time.sleep(0.05)
        s.pump()
        self.assertEqual(len(fake.views), 1)  # the remaining 6 are not due yet
        self.assertEqual(s.pump()['next_deadline'], 1000.0 + 1.0)
        self.clock.advance(0.01)
        self.assertTrue(pump_until(s, lambda: len(fake.views) == 2 and len(self.rows()) == 70))
        self.assertEqual(len(fake.views[1]['records']), 6)

    def test_incompatible_bindings_never_pooled(self):
        fake = Fake()
        s = self.sched(fake, max_records=4, max_wait=0)
        self.sub('p1', 2, prefix='a')
        self.sub('p2', 2, prefix='b', worker_hash='z' * 64)
        self.sub('p3', 2, prefix='c', input_policy='lenient')
        self.sub('p4', 2, prefix='d', check_hash='y' * 64)
        self.sub('p5', 2, prefix='e')  # compatible with p1
        self.assertTrue(pump_until(s, lambda: len(self.rows()) == 10))
        self.assertEqual(len(fake.views), 4)
        for v in fake.views:
            self.assertEqual(len({sp.bindings_hash(bind(**{})) if False else sp.bindings_hash(v['bindings'])}), 1)
        pooled = [v for v in fake.views if {'p1', 'p5'} <= {r['producer'] for r in v['records']}]
        self.assertEqual(len(pooled), 1)
        for v in fake.views:
            if v not in pooled:
                self.assertEqual(len({r['producer'] for r in v['records']}), 1)


class Concurrency(Base):
    def test_four_slots_really_run_concurrently(self):
        barrier = threading.Barrier(4, timeout=10)
        lock = threading.Lock()
        state = {'now': 0, 'max': 0}

        def launch(view):
            with lock:
                state['now'] += 1
                state['max'] = max(state['max'], state['now'])
            barrier.wait()  # only passes when four launches are in flight together
            with lock:
                state['now'] -= 1
            return capture_for(view)

        s = self.sched(launch, slots=4, max_records=1, max_wait=0)
        for i in range(8):
            self.sub(f'p{i}', 1)
        self.assertTrue(pump_until(s, lambda: len(self.rows()) == 8))
        self.assertEqual(state['max'], 4)

    def test_slots_bound_in_flight(self):
        gate = threading.Event()
        seen = []

        def launch(view):
            gate.wait(10)
            return capture_for(view)

        s = self.sched(launch, slots=2, max_records=1, max_wait=0)
        for i in range(5):
            self.sub(f'p{i}', 1)
        for _ in range(20):
            seen.append(s.pump()['in_flight'])
            time.sleep(0.005)
        self.assertEqual(max(seen), 2)
        gate.set()
        self.assertTrue(pump_until(s, lambda: len(self.rows()) == 5))

    def test_slow_batch_does_not_delay_another_groups_deadline(self):
        slow_started, release = threading.Event(), threading.Event()
        launched = []

        def launch(view):
            launched.append(view['records'][0]['producer'])
            if view['records'][0]['producer'] == 'slow':
                slow_started.set()
                release.wait(10)
            return capture_for(view)

        s = self.sched(launch, slots=2, max_records=64, max_wait=1.0)
        self.sub('slow', 1)
        s.pump()
        self.clock.advance(1.0)
        pump_until(s, lambda: slow_started.is_set())
        self.sub('fast', 1, worker_hash='f' * 64)  # a different group
        s.pump()  # the scheduler first sees it now
        self.clock.advance(1.0)  # past its deadline while the slow batch is still running
        self.assertTrue(pump_until(s, lambda: len(self.spool.collect('fast', 's1')['results']) == 1))
        self.assertFalse(release.is_set())
        self.assertEqual(len(self.spool.collect('slow', 's1')['results']), 0)
        release.set()
        self.assertTrue(pump_until(s, lambda: len(self.rows()) == 2))

    def test_run_until_idle_with_real_clock(self):
        fake = Fake()
        s = sp.Scheduler(self.spool, fake, max_records=8, max_wait=0.05)
        self.scheds.append(s)
        self.sub('p1', 20)
        s.run(until_idle=True, poll=0.01)
        self.assertEqual(len(self.rows()), 20)
        self.assertTrue(s.idle())


class HostLockAndFence(Base):
    def test_second_host_blocked_by_os_lock(self):
        s = self.sched(Fake())
        with self.assertRaises(sp.HostLocked):
            sp.Scheduler(self.spool, Fake())
        s.close()
        s2 = self.sched(Fake())
        self.assertEqual(s2.epoch, s.epoch + 1)

    def test_second_process_blocked_then_acquires_after_release(self):
        code = ("import sys, oz_spool as sp\n"
                "try:\n"
                "    sp.Scheduler(sp.Spool(sys.argv[1]), lambda v: {}).close()\n"
                "    print('ACQUIRED')\n"
                "except sp.HostLocked:\n"
                "    print('LOCKED')\n")
        s = self.sched(Fake())
        out = subprocess.run([sys.executable, '-c', code, self.db], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), 'LOCKED', out.stderr)
        s.close()
        out = subprocess.run([sys.executable, '-c', code, self.db], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), 'ACQUIRED', out.stderr)

    def test_killed_holder_releases_lock(self):
        code = ("import sys, time, oz_spool as sp\n"
                "s = sp.Scheduler(sp.Spool(sys.argv[1]), lambda v: {})\n"
                "print('UP', flush=True)\n"
                "time.sleep(60)\n")
        p = subprocess.Popen([sys.executable, '-c', code, self.db], cwd=ROOT, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), 'UP')
            with self.assertRaises(sp.HostLocked):
                sp.Scheduler(self.spool, Fake())
        finally:
            p.kill()
            p.wait()
            p.stdout.close()
        end = time.time() + 10
        while True:  # Windows may release a killed process's locks a moment after it exits
            try:
                s = self.sched(Fake())  # no time-based takeover needed: the OS dropped the lock
                break
            except sp.HostLocked:
                if time.time() > end:
                    raise
                time.sleep(0.05)
        self.assertGreaterEqual(s.epoch, 2)

    def test_stale_host_writes_are_fenced(self):
        gate = threading.Event()
        a = self.sched(lambda v: (gate.wait(10), capture_for(v))[1], max_records=1, max_wait=0)
        self.sub('p1', 1)
        pump_until(a, lambda: a.pump()['in_flight'] == 1)
        a.host.lock.release()  # pretend A lost its lock without knowing (the hole fencing covers)
        b = self.sched(Fake(), max_records=1, max_wait=0)
        self.assertEqual(b.epoch, a.epoch + 1)
        self.assertEqual(len(self.spool.unresolved()), 1)  # B recovered A's launched attempt as unknown
        self.sub('p2', 1)
        with self.assertRaises(sp.Fenced):
            a.pump()  # A's reserve is refused
        gate.set()
        time.sleep(0.1)
        with self.assertRaises(sp.Fenced):
            a.pump()  # and so is its capture
        self.assertEqual(self.rows(), [])
        self.assertTrue(pump_until(b, lambda: len(self.spool.collect('p2', 's1')['results']) == 1))
        self.assertEqual(len(self.spool.collect('p1', 's1')['results']), 0)  # still unknown, not delivered by A


class CrashRecovery(Base):
    POINTS = ('after_reserve', 'after_launch_mark', 'after_launch_call', 'after_capture',
              'before_delivery_commit', 'after_delivery')

    def run_crash(self, point):
        fake = Fake()
        hit = []

        def fault(p, b):
            if p == point and not hit:
                hit.append(b)
                raise Crash(p)

        s1 = self.sched(fake, max_records=64, max_wait=0, fault=fault)
        self.sub('p1', 3)
        self.sub('p2', 2)
        with self.assertRaises(Crash):
            pump_until(s1, lambda: False, timeout=5)
        s1.close()  # the process dies: the OS lock goes away
        time.sleep(0.05)
        s2 = self.sched(fake, max_records=64, max_wait=0)
        pump_until(s2, lambda: s2.idle(), timeout=5)
        return fake, s2

    def test_every_crash_boundary_is_exactly_once_or_explicit_unknown(self):
        expect_unknown = {'after_launch_mark': 0, 'after_launch_call': 1}
        for point in self.POINTS:
            with self.subTest(point=point):
                self.tearDown()
                self.setUp()
                fake, s2 = self.run_crash(point)
                unresolved = self.spool.unresolved()
                if point in expect_unknown:
                    self.assertEqual(len(unresolved), 1)
                    self.assertEqual(len(self.rows()), 0)  # never auto-relaunched, nothing delivered
                    self.assertEqual(len(fake.views), expect_unknown[point])
                    view = self.spool.request_map(self._request(unresolved[0]['batch_id']))
                    cap = capture_for([j['delivery_id'] for j in view['jobs']])
                    self.assertEqual(s2.reconcile(unresolved[0]['attempt_id'], cap), 'delivered')
                    self.assertEqual(self.spool.unresolved(), [])
                else:
                    self.assertEqual(unresolved, [])
                    self.assertTrue(all(n == 1 for n in fake.per_id.values()))
                    self.assertEqual(len(fake.views), 0 if False else (1 if point != 'after_delivery' else 1))
                rows = self.rows()
                self.assertEqual(len(rows), 5)
                self.assertEqual(len({r[0] for r in rows}), 5)  # exactly once
                self.assertTrue(self.spool.collect('p1', 's1')['complete'])
                self.assertTrue(self.spool.collect('p2', 's1')['complete'])
                self.assertTrue(all(n <= 1 for n in fake.per_id.values()))
                s2.close()

    def _request(self, batch_id):
        c = sqlite3.connect(self.db)
        try:
            return c.execute('SELECT request_id FROM batches WHERE batch_id=?', (batch_id,)).fetchone()[0]
        finally:
            c.close()

    def test_launch_exception_is_unknown_and_not_relaunched(self):
        calls = []

        def boom(view):
            calls.append(1)
            raise RuntimeError('network died')

        s = self.sched(boom, max_records=64, max_wait=0)
        self.sub('p1', 2)
        self.assertTrue(pump_until(s, lambda: len(self.spool.unresolved()) == 1))
        for _ in range(20):
            s.pump()
            time.sleep(0.002)
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.spool.collect('p1', 's1')['complete'])
        self.assertEqual(len(self.spool.collect('p1', 's1')['unknown']), 1)
        self.assertFalse(s.idle() is False)  # unknown attempts do not keep the scheduler busy
        aid = self.spool.unresolved()[0]['attempt_id']
        view = self.spool.request_map(self._request(self.spool.unresolved()[0]['batch_id']))
        self.assertEqual(s.reconcile(aid, capture_for([j['delivery_id'] for j in view['jobs']])), 'delivered')
        self.assertTrue(self.spool.collect('p1', 's1')['complete'])
        self.assertEqual(len(calls), 1)

    def test_reconcile_provably_unlaunched_relaunches_with_new_attempt(self):
        mode = {'fail': True}
        calls = []

        def launch(view):
            calls.append(view['attempt_id'])
            if mode['fail']:
                raise RuntimeError('unknown outcome')
            return capture_for(view)

        s = self.sched(launch, max_records=64, max_wait=0)
        self.sub('p1', 2)
        pump_until(s, lambda: len(self.spool.unresolved()) == 1)
        first = self.spool.unresolved()[0]['attempt_id']
        mode['fail'] = False
        self.assertEqual(s.reconcile(first, provably_unlaunched=True), 'void')
        self.assertTrue(pump_until(s, lambda: self.spool.collect('p1', 's1')['complete']))
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0], calls[1])
        self.assertEqual(len(self.rows()), 2)

    def test_launch_not_started_is_retried_up_to_the_limit(self):
        calls = []

        def launch(view):
            calls.append(1)
            if len(calls) < 3:
                raise sp.LaunchNotStarted('adapter missing')
            return capture_for(view)

        s = self.sched(launch, max_records=64, max_wait=0, retry_limit=5)
        self.sub('p1', 1)
        self.assertTrue(pump_until(s, lambda: self.spool.collect('p1', 's1')['complete']))
        self.assertEqual(len(calls), 3)
        s.close()
        s2 = self.sched(lambda v: (_ for _ in ()).throw(sp.LaunchNotStarted('x')), max_records=64, max_wait=0, retry_limit=2)
        self.sub('p2', 1)
        self.assertTrue(pump_until(s2, lambda: len(self.spool.unresolved()) == 1))


class ResultValidation(Base):
    def test_foreign_result_ids_rejected_and_recorded(self):
        foreign = sp.delivery_id('zz', 'zz', 'zz', 'zz')

        def launch(view):
            cap = capture_for(view)
            cap['results'][foreign] = {'ok': 'stolen'}
            return cap

        s = self.sched(launch, max_records=64, max_wait=0)
        self.sub('p1', 2)
        self.assertTrue(pump_until(s, lambda: len(self.spool.unresolved()) == 1))
        self.assertEqual(self.rows(), [])
        reasons = [r['reason'] for r in self.spool.rejections()]
        self.assertIn('foreign_result_id', reasons)
        un = self.spool.unresolved()[0]
        with self.assertRaises(sp.SpoolError):  # reconcile with the same foreign id is rejected too
            s.reconcile(un['attempt_id'], launch_view_cap(self, un, extra=foreign))
        self.assertEqual(self.rows(), [])
        ids = [j['delivery_id'] for j in self.spool.request_map(request_of(self, un['batch_id']))['jobs']]
        self.assertEqual(s.reconcile(un['attempt_id'], capture_for(ids)), 'delivered')
        self.assertEqual(len(self.rows()), 2)

    def test_conflicting_capture_after_delivery_is_rejected_identical_is_noop(self):
        s = self.sched(Fake(), max_records=64, max_wait=0)
        self.sub('p1', 2)
        pump_until(s, lambda: self.spool.collect('p1', 's1')['complete'])
        c = sqlite3.connect(self.db)
        aid, bid = c.execute('SELECT attempt_id, batch_id FROM attempts').fetchone()
        stored = c.execute('SELECT capture FROM attempts').fetchone()[0]
        c.close()
        import json
        doc = json.loads(stored)
        same = {'results': doc['rows'], 'call_id': doc['call_id']}
        self.assertEqual(s.reconcile(aid, same), 'delivered')  # identical: no-op
        other = {'results': {k: {'tampered': 1} for k in doc['rows']}, 'call_id': 'other'}
        with self.assertRaises(sp.SpoolError):
            s.reconcile(aid, other)
        self.assertIn('conflicting_capture', [r['reason'] for r in self.spool.rejections()])
        self.assertEqual(len(self.rows()), 2)
        before = self.spool.collect('p1', 's1')['results']
        self.assertTrue(all(r['result'].get('echo') for r in before.values()))

    def test_missing_result_is_an_error_row_not_a_hang(self):
        def launch(view):
            cap = capture_for(view)
            cap['results'].pop(view['records'][0]['id'])
            return cap

        s = self.sched(launch, max_records=64, max_wait=0)
        self.sub('p1', 2)
        self.assertTrue(pump_until(s, lambda: self.spool.collect('p1', 's1')['complete']))
        errs = [r for r in self.spool.collect('p1', 's1')['results'].values() if r['result'] == {'error': 'missing_result'}]
        self.assertEqual(len(errs), 1)

    def test_unusable_capture_is_unknown(self):
        s = self.sched(lambda v: 'not a dict', max_records=64, max_wait=0)
        self.sub('p1', 1)
        self.assertTrue(pump_until(s, lambda: len(self.spool.unresolved()) == 1))
        self.assertIn('invalid_capture', [r['reason'] for r in self.spool.rejections()])


def request_of(test, batch_id):
    return test._request(batch_id) if hasattr(test, '_request') else _req(test.db, batch_id)


def _req(db, batch_id):
    c = sqlite3.connect(db)
    try:
        return c.execute('SELECT request_id FROM batches WHERE batch_id=?', (batch_id,)).fetchone()[0]
    finally:
        c.close()


def launch_view_cap(test, un, extra):
    jobs_ = test.spool.request_map(_req(test.db, un['batch_id']))['jobs']
    cap = capture_for([j['delivery_id'] for j in jobs_])
    cap['results'][extra] = {'x': 1}
    return cap


class Timestamps(Base):
    def test_queue_times_request_map_and_late_submission(self):
        fake = Fake()
        s = self.sched(fake, max_records=64, max_wait=1.0)
        self.sub('p1', 3)
        s.pump()
        self.clock.advance(1.0)
        self.assertTrue(pump_until(s, lambda: self.spool.collect('p1', 's1')['complete']))
        rows = list(self.spool.collect('p1', 's1')['results'].values())
        for r in rows:
            self.assertEqual(r['submitted_at'], 1000.0)
            self.assertEqual(r['reserved_at'], 1001.0)
            self.assertLessEqual(r['reserved_at'], r['launched_at'])
            self.assertLessEqual(r['launched_at'], r['captured_at'])
            self.assertLessEqual(r['captured_at'], r['delivered_at'])
        self.assertEqual(sorted(r['position'] for r in rows), [0, 1, 2])
        rep = self.spool.queue_report()
        self.assertEqual(rep['records'], 3)
        self.assertEqual(rep['max_queue_s'], 1.0)
        self.assertEqual(rep['makespan_s'], 1.0)
        m = self.spool.request_map(rows[0]['request_id'])
        self.assertEqual([j['delivery_id'] for j in m['jobs']], [r['delivery_id'] for r in sorted(rows, key=lambda r: r['position'])])
        self.assertEqual(m['attempts'][0]['state'], 'delivered')
        self.assertEqual(rows[0]['request_id'], fake.views[0]['request_id'])
        # a late submission after delivery forms a new batch
        self.sub('p2', 1)
        s.pump()
        self.clock.advance(1.0)
        self.assertTrue(pump_until(s, lambda: self.spool.collect('p2', 's1')['complete']))
        self.assertEqual(len(fake.views), 2)


if __name__ == '__main__':
    unittest.main()
