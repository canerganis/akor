from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from oz import Error
from oz_runtime import Inbox, Outcome
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
        self.assertEqual(body['j'], ['audit 0'])
        self.assertEqual(packet.wires, ('r7a7t14+8.',))
        self.assertEqual(packet.job_map, (('m1', 1),))
        self.assertEqual(packet.host_slots, (('m1', 0, ''), ('m1', 2, 'python -m unittest')))

    def test_new_jobs_default_to_two_attempts_including_the_original(self):
        self.post('m1')
        self.assertEqual(self.box.inspect('m1')['max_attempts'], 2)
        self.box.retry(self.claim(), 'first transport failure')
        self.assertEqual(self.box.inspect('m1')['state'], 'pending')
        self.box.retry(self.claim(), 'second transport failure')
        self.assertEqual(self.box.inspect('m1')['state'], 'failed')
        self.assertEqual(self.box.inspect('m1')['attempts'], 2)
        self.assertIsNone(self.claim())
        self.post('m2', max_attempts=5)
        self.assertEqual(self.box.inspect('m2')['max_attempts'], 5)

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

    def literals(self, box=None):
        return [(r['binding'], r['text'], r['n']) for r in
                (box or self.box).db.execute('SELECT * FROM literal_names ORDER BY binding,n')]

    def test_literal_names_are_allocated_in_post_order_and_persisted_per_binding(self):
        other = extended(recipient='other')
        self.post('a', ':alpha')
        self.post('b', ':beta')
        self.post('c', ':alpha')
        self.post('d', '>12')
        self.box.post(other, 'e', ':beta', binding=other.binding)
        self.assertFalse(self.post('b', ':beta'))
        self.assertEqual(self.literals(), sorted([(self.ch.binding, 'alpha', 0), (self.ch.binding, 'beta', 1),
                                                  (other.binding, 'beta', 0)], key=lambda r: (r[0], r[2])))
        # The text is kept exactly, whitespace included.
        self.post('f', ':  padded\r\n')
        self.assertIn((self.ch.binding, '  padded\r\n', 2), self.literals())
        names = json.loads(self.box.plan(self.ch, counters=[len]).packet.text)['d']
        self.assertEqual(names, {'literal_0': 'alpha', 'literal_1': 'beta', 'propose': names['propose'],
                                 'literal_2': '  padded\r\n'})

    def test_literal_names_are_unique_per_binding_in_the_database(self):
        self.post('a', ':alpha')
        with self.assertRaises(sqlite3.IntegrityError):
            self.box.db.execute('INSERT INTO literal_names VALUES (?,?,?)', (self.ch.binding, 'alpha', 5))
        with self.assertRaises(sqlite3.IntegrityError):
            self.box.db.execute('INSERT INTO literal_names VALUES (?,?,?)', (self.ch.binding, 'other', 0))

    def test_names_do_not_depend_on_which_jobs_are_in_the_packet_or_on_retries(self):
        for mid, text in (('a', ':one'), ('b', ':two'), ('c', ':three')):
            self.post(mid, text)
        first = self.box.claim_prepared(self.ch, owner='w', counters=[len], receipt='a', limit=1)
        self.assertEqual(json.loads(first[1].text)['j'], ['literal_0'])
        self.box.settle(first[0], {'a': Outcome('ok', 'x')})
        # c alone, then b: neither renumbers.
        self.box.db.execute("UPDATE jobs SET seq=seq+10 WHERE id='b'")
        second = self.box.claim_prepared(self.ch, owner='w', counters=[len], receipt='b', limit=1)
        self.assertEqual((second[0].jobs[0].id, json.loads(second[1].text)['j']), ('c', ['literal_2']))
        self.box.settle(second[0], {'c': Outcome('retry', 'again')})
        third = self.box.claim_prepared(self.ch, owner='w', counters=[len], receipt='c', limit=2)
        self.assertEqual([(j.id, n) for j, n in zip(third[0].jobs, json.loads(third[1].text)['j'])],
                         [('c', 'literal_2'), ('b', 'literal_1')])

    def test_schema_two_upgrade_adds_result_json_and_numbers_existing_literals_in_inbox_order(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'v2.sqlite'
            with Inbox(path) as box:
                for mid, wire in (('a', ':first'), ('b', 'V'), ('c', ':second'), ('d', ':first')):
                    box.post(self.ch, mid, wire, binding=self.ch.binding)
                box.db.execute('DROP TABLE literal_names')
                box.db.execute('ALTER TABLE jobs DROP COLUMN result_json')
                box.db.execute('PRAGMA user_version=2')
            with Inbox(path) as box:
                self.assertEqual(box.db.execute('PRAGMA user_version').fetchone()[0], 3)
                self.assertIn('result_json', {r['name'] for r in box.db.execute('PRAGMA table_info(jobs)')})
                self.assertEqual(self.literals(box), [(self.ch.binding, 'first', 0), (self.ch.binding, 'second', 1)])
                self.post_to(box, 'e', ':third')
                self.assertEqual(self.literals(box)[-1], (self.ch.binding, 'third', 2))
            with Inbox(path) as box:
                self.assertEqual(len(self.literals(box)), 3)

    def post_to(self, box, mid, wire, **kw):
        return box.post(self.ch, mid, wire, binding=self.ch.binding, **kw)

    def test_future_schema_versions_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'future.sqlite'
            with Inbox(path) as box:
                box.db.execute('PRAGMA user_version=4')
            with self.assertRaisesRegex(Error, 'unsupported inbox schema'):
                Inbox(path)

    def test_settle_stores_the_json_value_only_for_ok_outcomes_and_only_valid_json(self):
        self.post('a')
        self.post('b')
        delivery = self.claim()
        for outcomes in [{'a': Outcome('ok', 'x', 'not json'), 'b': Outcome('ok', 'y')},
                         {'a': Outcome('ok', 'x'), 'b': Outcome('failed', 'no', '"v"')},
                         {'a': Outcome('ok', 'x', 'NaN'), 'b': Outcome('ok', 'y')},
                         {'a': Outcome('ok', 'x', 5), 'b': Outcome('ok', 'y')}]:
            with self.subTest(outcomes=outcomes), self.assertRaises(Error):
                self.box.settle(delivery, outcomes)
        self.assertEqual(self.box.stats(), {'leased': 2})
        self.box.settle(delivery, {'a': Outcome('ok', 'x', '{"k":[1]}'), 'b': Outcome('ok', 'y')})
        rows = {r['id']: r['result_json'] for r in self.box.db.execute('SELECT id,result_json FROM jobs')}
        self.assertEqual(rows, {'a': '{"k":[1]}', 'b': None})

    def test_handoffs_use_json_values_declaration_order_and_done_direct_predecessors_only(self):
        for mid in ('p', 'q', 'r'):
            self.post(mid, '>12')
        self.post('z', '>12', after=('r', 'p', 'q'))
        self.post('y', '>12', after=('z',))
        delivery = self.claim(limit=3)
        self.box.settle(delivery, {'p': Outcome('ok', 'legacy text'), 'q': Outcome('ok', 'stored', '{"v":[1,2]}'),
                                   'r': Outcome('ok', '""', '""')})
        links = self.box._handoffs(['z', 'y'])
        self.assertEqual(links, [('z', 'r', ''), ('z', 'p', 'legacy text'), ('z', 'q', {'v': [1, 2]})])

    def test_reply_mode_applies_to_first_attempts_only(self):
        self.post('a', '>12')
        self.post('b', '>12')
        from oz_batch import SYSTEMS
        plan = self.box.plan(self.ch, counters=[len], reply_mode='array')
        self.assertEqual((plan.packet.system, plan.packet.reply_mode), (SYSTEMS['array'], 'array'))
        delivery, packet = self.box.claim_prepared(self.ch, owner='w', counters=[len], receipt='a', limit=1,
                                                   reply_mode='array')
        self.assertEqual(packet.reply_mode, 'array')
        self.box.settle(delivery, {'a': Outcome('retry', 'bad reply')}, retry_delay=0)
        # a has been delivered once: any packet holding it asks for jsonl, even with b beside it.
        retry = self.box.plan(self.ch, counters=[len], reply_mode='array')
        self.assertEqual([j.id for j in retry.jobs], ['a', 'b'])
        self.assertEqual((retry.packet.system, retry.packet.reply_mode), (SYSTEMS['jsonl'], 'jsonl'))
        with self.assertRaises(Error):
            self.box.plan(self.ch, counters=[len], reply_mode='x')


if __name__ == '__main__':
    unittest.main()
