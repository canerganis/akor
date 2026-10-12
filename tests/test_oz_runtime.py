from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest

from oz import Error
from oz_runtime import Inbox
from test_oz2 import extended


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.ch = extended()
        self.now = [100.0]
        self.box = Inbox(clock=lambda: self.now[0])
        self.addCleanup(self.box.close)

    def post(self, mid, wire='V', **kw):
        return self.box.post(self.ch, mid, wire, binding=self.ch.binding, **kw)

    def claim(self, **kw):
        return self.box.claim(self.ch, owner='worker1', **kw)

    def test_idempotency_uses_meaning_not_spelling(self):
        self.assertTrue(self.post('m1', 'V'))
        self.assertFalse(self.post('m1', 'r7a7t14'))
        with self.assertRaisesRegex(Error, 'different contents'):
            self.post('m1', 'r13')
        self.assertEqual(self.box.stats(), {'pending': 1})

    def test_different_ids_are_not_deduplicated_by_content(self):
        self.post('m1')
        self.post('m2')
        self.assertEqual(len(self.claim().jobs), 2)

    def test_bad_binding_and_evidence_cannot_enter_queue(self):
        for wire, binding in [('V', 'wrong'), ('+9', self.ch.binding), ('+15', self.ch.binding)]:
            with self.subTest(wire=wire), self.assertRaises(Error):
                self.box.post(self.ch, 'm1', wire, binding=binding)
        self.assertEqual(self.box.stats(), {})

    def test_dependency_waits_for_acknowledged_result(self):
        self.post('m1')
        self.post('m2', after=['m1'])
        delivery = self.claim()
        self.assertEqual([j.id for j in delivery.jobs], ['m1'])
        self.assertIsNone(self.claim())
        self.box.complete(delivery, {'m1': 'adapter received result; not evidence of correctness'})
        self.assertEqual([j.id for j in self.claim().jobs], ['m2'])

    def test_dependencies_can_coordinate_different_agents_in_same_task(self):
        self.post('m1')
        other = extended(sender='worker', recipient='reviewer')
        self.box.post(other, 'm2', 'r13', binding=other.binding, after=['m1'])
        self.assertIsNone(self.box.claim(other, owner='reviewer'))
        self.box.complete(self.claim(), {'m1': 'ready'})
        self.assertEqual(self.box.claim(other, owner='reviewer').jobs[0].id, 'm2')

    def test_unknown_self_duplicate_or_other_task_dependencies_rejected(self):
        for after in [['m1'], ['missing'], ['x', 'x']]:
            with self.subTest(after=after), self.assertRaises(Error):
                self.post('m1', after=after)
        self.post('prior')
        other = extended(revision=2)
        with self.assertRaises(Error):
            self.box.post(other, 'm2', 'V', binding=other.binding, after=['prior'])
        self.assertEqual(self.box.stats(), {'pending': 1})

    def test_status_events_do_not_wake_model(self):
        self.post('m1', '+8.')
        self.assertIsNone(self.claim())
        delivery = self.claim(kind='host')
        self.assertEqual(delivery.kind, 'host')
        with self.assertRaises(Error):
            delivery.prepare(self.ch, counters=[len])
        events = self.ch.dispatch(delivery.jobs[0].wire, binding=self.ch.binding)
        self.assertFalse(events['needs_model'])
        self.box.complete(delivery, {'m1': 'recorded sender claim'})
        self.assertIsNone(self.claim(kind='host'))

    def test_mixed_work_and_status_remain_ordered_until_result(self):
        self.post('m1', 'V+8.')
        self.assertIsNone(self.claim(kind='host'))
        delivery = self.claim()
        self.assertEqual(delivery.jobs[0].wire, 'V+8.')
        packet = delivery.prepare(self.ch, counters=[len])
        self.assertEqual(packet.ids, ('m1',))
        self.assertNotIn('m1', packet.text)
        body = json.loads(packet.text)
        # Only model atoms reach the model; the host atoms +8 and . stay behind.
        self.assertEqual(body['j'], ['read 7', 'audit 7', 'test 14'])
        self.assertEqual(packet.wires, ('r7a7t14+8.',))
        self.assertEqual(packet.job_map, (('m1', 0), ('m1', 1), ('m1', 2)))

    def test_retry_cannot_duplicate_acknowledged_work(self):
        self.post('m1')
        first = self.claim()
        self.box.retry(first, 'transport timeout')
        second = self.claim()
        self.assertEqual(second.jobs[0].attempt, 2)
        with self.assertRaises(Error):
            self.box.complete(first, {'m1': 'late response'})
        self.box.complete(second, {'m1': 'received'})
        self.assertFalse(self.post('m1'))
        self.assertIsNone(self.claim())

    def test_expiry_fences_late_workers_and_releases_lease(self):
        self.post('m1')
        old = self.claim(lease_seconds=5)
        self.now[0] = 105
        with self.assertRaises(Error):
            self.box.complete(old, {'m1': 'too late'})
        new = self.claim()
        self.assertNotEqual(old.lease, new.lease)
        self.box.complete(new, {'m1': 'accepted'})

    def test_live_lease_can_be_renewed(self):
        self.post('m1')
        delivery = self.claim(lease_seconds=5)
        self.now[0] = 104
        self.box.renew(delivery, lease_seconds=10)
        self.now[0] = 107
        self.assertIsNone(self.claim())
        self.box.complete(delivery, {'m1': 'accepted'})

    def test_retry_limit_and_permanent_failure_block_dependants(self):
        self.post('m1', max_attempts=1)
        self.post('m2', after=['m1'])
        self.box.retry(self.claim(), 'failure')
        self.assertEqual(self.box.inspect('m1')['state'], 'failed')
        self.assertIsNone(self.claim())
        self.post('m3')
        self.box.retry(self.claim(), 'unsupported operation', permanent=True)
        self.assertEqual(self.box.inspect('m3')['state'], 'failed')

    def test_expiry_also_respects_retry_limit(self):
        self.post('m1', max_attempts=1)
        self.claim(lease_seconds=1)
        self.now[0] += 2
        self.assertIsNone(self.claim())
        self.assertEqual(self.box.inspect('m1')['state'], 'failed')

    def test_partial_results_or_forged_delivery_cannot_ack_batch(self):
        self.post('m1')
        self.post('m2')
        delivery = self.claim()
        with self.assertRaises(Error):
            self.box.complete(delivery, {'m1': 'partial'})
        for fake in [replace(delivery, owner='other'), replace(delivery, binding='wrong'),
                     replace(delivery, jobs=delivery.jobs[:1])]:
            with self.subTest(fake=fake), self.assertRaises(Error):
                self.box.complete(fake, {j.id: 'x' for j in fake.jobs})
        self.assertEqual(self.box.stats(), {'leased': 2})
        self.box.complete(delivery, {'m1': 'one', 'm2': 'two'})
        self.assertEqual(self.box.stats(), {'done': 2})

    def test_other_channel_cannot_claim_or_prepare_messages(self):
        self.post('m1')
        other = extended(recipient='other')
        self.assertIsNone(self.box.claim(other, owner='worker1'))
        with self.assertRaises(Error):
            self.claim().prepare(other, counters=[len])

    def test_restart_recovers_queue_results_and_channel(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'inbox.db'
            with Inbox(path) as first:
                first.post(self.ch, 'm1', 'V', binding=self.ch.binding)
            with Inbox(path) as second:
                restored = second.channel(self.ch.binding)
                delivery = second.claim(restored, owner='worker')
                self.assertEqual(restored.binding, self.ch.binding)
                second.complete(delivery, {'m1': 'persisted'})
            with Inbox(path) as third:
                self.assertEqual(third.inspect('m1')['result'], 'persisted')
                self.assertIsNone(third.claim(self.ch, owner='worker'))

    def test_two_connections_cannot_claim_same_jobs(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'inbox.db'
            with Inbox(path) as first:
                for i in range(20):
                    first.post(self.ch, f'm{i}', 'V', binding=self.ch.binding)
            def worker(owner):
                with Inbox(path) as box:
                    delivery = box.claim(self.ch, owner=owner, limit=10)
                    return {j.id for j in delivery.jobs} if delivery else set()
            with ThreadPoolExecutor(max_workers=2) as pool:
                one, two = list(pool.map(worker, ['a', 'b']))
            self.assertFalse(one & two)
            self.assertEqual(len(one | two), 20)


if __name__ == '__main__':
    unittest.main()
