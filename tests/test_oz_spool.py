import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import oz_spool as sp


class Crash(BaseException):
    pass


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def bind(**over):
    b = {'contract': 'c' * 64, 'check': 'k' * 64, 'permission': 'p' * 64, 'worker_hash': 'w' * 64,
         'input_policy': 'strict'}
    b.update(over)
    return b


def jobs(n, prefix='f'):
    return [{'key': f'{prefix}{i}', 'op': 'extract', 'text': f'text {prefix}{i}'} for i in range(n)]


class Fake:
    def __init__(self):
        self.batches = []
        self.per_id = {}

    def __call__(self, batch):
        self.batches.append(batch)
        for r in batch['records']:
            self.per_id[r['id']] = self.per_id.get(r['id'], 0) + 1
        return {'results': {r['id']: {'echo': r['text'], 'by': r['producer']} for r in batch['records']},
                'call_id': 'call-' + batch['batch_id'][:6]}


class SpoolTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.clock = Clock()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def sub(self, producer, n, submission='s1', prefix='f', **b):
        return sp.submit(self.dir, producer, submission, jobs(n, prefix), bind(**b), clock=self.clock)

    def drain(self, fake, **kw):
        return sp.drain(self.dir, fake, clock=self.clock, sleep=self.clock.sleep, **kw)

    def test_ids_are_53_chars_and_collision_free(self):
        ids = set()
        for p in ('a', 'b'):
            for s in ('s1', 's2'):
                ids.update(sp.submit(self.dir, p, s, jobs(50), bind(), clock=self.clock))
        self.assertEqual(len(ids), 200)
        self.assertTrue(all(len(i) == 53 and i[0] == 'j' and i == i.lower() for i in ids))
        self.assertNotEqual(sp.delivery_id('a', 's', 'x', 'k'), sp.delivery_id('a', 's', 'y', 'k'))

    def test_collision_detected(self):
        d = sp._Drainer(self.dir, None, 64, 1, self.clock, None, 2, None)
        did = sp.delivery_id('a', 's1', 'extract', 'f0')
        d._register({did: ['a', 's1', 'extract', 'f0']})
        d._register({did: ['a', 's1', 'extract', 'f0']})
        with self.assertRaises(sp.SpoolError):
            d._register({did: ['z', 's1', 'extract', 'f0']})

    def test_submit_idempotent_and_changed_payload_rejected(self):
        a = self.sub('a', 3)
        self.assertEqual(a, self.sub('a', 3))
        with self.assertRaises(sp.SpoolError):
            sp.submit(self.dir, 'a', 's1', jobs(2), bind(), clock=self.clock)
        with self.assertRaises(sp.SpoolError):
            sp.submit(self.dir, 'a', 's2', [{'key': 'x', 'text': 't'}, {'key': 'x', 'text': 'u'}], bind())

    def test_no_partial_fragment(self):
        self.sub('a', 3)
        names = os.listdir(Path(self.dir, 'fragments'))
        self.assertEqual(names, ['a.s1.json'])
        json.loads(Path(self.dir, 'fragments', names[0]).read_text())

    def test_two_producers_pooled_into_one_call(self):
        self.sub('a', 5)
        self.sub('b', 5)
        fake = Fake()
        self.drain(fake)
        self.assertEqual(len(fake.batches), 1)
        self.assertEqual(len(fake.batches[0]['records']), 10)

    def test_four_producers_pooled_and_routed(self):
        for p in 'abcd':
            self.sub(p, 16)
        fake = Fake()
        self.drain(fake)
        self.assertEqual(len(fake.batches), 1)
        self.assertEqual(len(fake.batches[0]['records']), 64)
        for p in 'abcd':
            got = sp.collect(self.dir, p, 's1')
            self.assertTrue(got['complete'])
            self.assertEqual(len(got['results']), 16)
            for row in got['results'].values():
                self.assertEqual(row['result']['by'], p)
                self.assertEqual(row['producer'], p)
                self.assertEqual(row['submission'], 's1')
                self.assertEqual(row['result']['echo'], 'text ' + row['key'])

    def test_count_flush_at_64_before_wait(self):
        self.sub('a', 64 + 10)
        fake = Fake()
        self.drain(fake, once=True)
        self.assertEqual([len(b['records']) for b in fake.batches], [64])
        self.drain(fake)
        self.assertEqual([len(b['records']) for b in fake.batches], [64, 10])

    def test_wait_flush_from_oldest_item(self):
        self.sub('a', 2)
        self.clock.t += 0.6
        self.sub('b', 2)
        fake = Fake()
        self.clock.t += 0.3
        self.drain(fake, once=True)
        self.assertEqual(fake.batches, [])
        self.clock.t += 0.1
        self.drain(fake, once=True)
        self.assertEqual(len(fake.batches), 1)
        self.assertEqual(len(fake.batches[0]['records']), 4)

    def test_blocking_drain_waits_via_sleep(self):
        self.sub('a', 1)
        start = self.clock.t
        self.drain(Fake())
        self.assertAlmostEqual(self.clock.t - start, 1.0)
        row = next(iter(sp.collect(self.dir, 'a', 's1')['results'].values()))
        self.assertAlmostEqual(row['queue_s'], 1.0)
        self.assertEqual(sp.queue_report(self.dir)['records'], 1)

    def test_incompatible_bindings_never_pooled(self):
        self.sub('a', 3)
        self.sub('b', 3)
        self.sub('c', 3, worker_hash='x' * 64)
        self.sub('d', 3, input_policy='lenient')
        self.sub('e', 3, permission='q' * 64)
        fake = Fake()
        self.drain(fake)
        self.assertEqual(len(fake.batches), 4)
        self.assertEqual(sorted(len(b['records']) for b in fake.batches), [3, 3, 3, 6])
        for b in fake.batches:
            producers = {r['producer'] for r in b['records']}
            if len(producers) > 1:
                self.assertEqual(producers, {'a', 'b'})

    def _crash_at(self, point):
        self.sub('a', 3)
        self.sub('b', 3)
        fake = Fake()

        def fault(p, bid):
            if p == point:
                raise Crash(p)
        with self.assertRaises(Crash):
            self.drain(fake, fault=fault)
        self.drain(fake)
        return fake

    def test_crash_at_every_boundary_gives_exactly_once_delivery(self):
        for point in ('after_reserve', 'after_dispatch_state', 'after_dispatch_call', 'after_capture_file',
                      'after_capture_state', 'mid_delivery', 'after_delivery_files', 'after_delivery_state'):
            with self.subTest(point=point):
                shutil.rmtree(self.dir)
                os.makedirs(self.dir)
                fake = self._crash_at(point)
                for p in 'ab':
                    got = sp.collect(self.dir, p, 's1')
                    self.assertTrue(got['complete'], point)
                    self.assertEqual(len(got['results']), 3, point)
                expected = 2 if point == 'after_dispatch_call' else 1
                for n in fake.per_id.values():
                    self.assertEqual(n, expected, point)
                states = [json.loads(p.read_text())['state'] for p in Path(self.dir, 'batches').glob('b*.json')]
                self.assertEqual(states, ['delivered'])
                calls = len(fake.batches)
                self.drain(fake)
                self.assertEqual(len(fake.batches), calls)

    def test_mid_delivery_has_no_duplicate_rows(self):
        self._crash_at('mid_delivery')
        for p in 'ab':
            doc = json.loads(Path(self.dir, 'results', p, 's1.json').read_text())
            self.assertEqual(len(doc['results']), 3)

    def test_dispatch_exception_retries_then_abandons(self):
        self.sub('a', 2)
        n = {'c': 0}

        def boom(batch):
            n['c'] += 1
            raise RuntimeError('network')
        with self.assertRaises(RuntimeError):
            self.drain(boom)
        with self.assertRaises(RuntimeError):
            self.drain(boom)
        self.drain(boom)
        self.assertEqual(n['c'], 2)
        rows = sp.collect(self.dir, 'a', 's1')
        self.assertTrue(rows['complete'])
        self.assertTrue(all(r['result']['error'] == 'dispatch_abandoned' for r in rows['results'].values()))

    def test_missing_result_is_a_failed_row_not_a_hang(self):
        self.sub('a', 2)
        self.drain(lambda b: {})
        rows = sp.collect(self.dir, 'a', 's1')
        self.assertTrue(rows['complete'])
        self.assertTrue(all(r['result'] == {'error': 'missing_result'} for r in rows['results'].values()))

    def test_late_fragment_after_delivery_forms_new_batch(self):
        self.sub('a', 2)
        fake = Fake()
        self.drain(fake)
        self.sub('b', 2)
        self.drain(fake)
        self.assertEqual(len(fake.batches), 2)
        self.assertTrue(sp.collect(self.dir, 'a', 's1')['complete'])
        self.assertTrue(sp.collect(self.dir, 'b', 's1')['complete'])

    def test_live_lock_blocks_second_drainer(self):
        self.sub('a', 1)
        with sp.DrainLock(self.dir, clock=self.clock):
            with self.assertRaises(sp.LockHeld):
                self.drain(Fake())
        self.drain(Fake())

    def test_stale_lock_dead_pid_taken_over(self):
        Path(self.dir, 'drain.lock').write_text(json.dumps({'pid': 424242, 'epoch': self.clock(), 'token': 'old'}))
        lock = sp.DrainLock(self.dir, clock=self.clock, alive=lambda pid: False)
        lock.acquire()
        info = json.loads(Path(self.dir, 'drain.lock').read_text())
        self.assertEqual(info['token'], lock.token)
        lock.release()
        self.assertFalse(Path(self.dir, 'drain.lock').exists())

    def test_alive_owner_not_stolen_but_hard_lease_expires(self):
        Path(self.dir, 'drain.lock').write_text(json.dumps({'pid': 7, 'epoch': self.clock(), 'token': 'old'}))
        lock = sp.DrainLock(self.dir, clock=self.clock, alive=lambda pid: True, hard_lease=100)
        with self.assertRaises(sp.LockHeld):
            lock.acquire()
        self.clock.t += 101
        lock.acquire()
        lock.release()

    def test_garbage_lock_is_stale_and_lost_lock_detected(self):
        Path(self.dir, 'drain.lock').write_text('{half')
        a = sp.DrainLock(self.dir, clock=self.clock).acquire()
        Path(self.dir, 'drain.lock').write_text(json.dumps({'pid': 1, 'epoch': 0, 'token': 'thief'}))
        with self.assertRaises(sp.LockLost):
            a.heartbeat()

    def test_crashed_drainer_leaves_stale_lock_and_restart_recovers(self):
        self.sub('a', 2)
        dead = sp.DrainLock(self.dir, clock=self.clock, pid=999999)
        dead.acquire()
        with self.assertRaises(sp.LockHeld):
            sp.DrainLock(self.dir, clock=self.clock, pid=1, alive=lambda pid: True).acquire()
        newer = sp.DrainLock(self.dir, clock=self.clock, pid=2, alive=lambda pid: pid != 999999)
        self.drain(Fake(), lock=newer.acquire())
        self.assertTrue(sp.collect(self.dir, 'a', 's1')['complete'])

    def test_pid_alive_real(self):
        self.assertTrue(sp.pid_alive(os.getpid()))

    def test_queue_times_recorded(self):
        self.sub('a', 2)
        self.clock.t += 0.4
        self.sub('b', 2)
        self.clock.t += 0.6
        self.drain(Fake())
        rep = sp.queue_report(self.dir)
        self.assertEqual(rep['records'], 4)
        self.assertAlmostEqual(rep['max_queue_s'], 1.0)
        self.assertAlmostEqual(rep['makespan_s'], 1.0)
        row = next(iter(sp.collect(self.dir, 'b', 's1')['results'].values()))
        self.assertAlmostEqual(row['queue_s'], 0.6)
        self.assertIsNotNone(row['call_id'])


if __name__ == '__main__':
    unittest.main()
