from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from oz import Error
from oz_batch import SYSTEM, BudgetError, render
from oz_runtime import Inbox, Outcome
from test_oz2 import extended

R = 'abcdef0123456789'


def packet_data(packet):
    return json.loads(packet.text)


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.ch = extended()
        self.now = [10.0]
        self.box = Inbox(clock=lambda: self.now[0])
        self.addCleanup(self.box.close)

    def post(self, mid, wire='V', **options):
        return self.box.post(self.ch, mid, wire, binding=self.ch.binding, **options)

    def test_preview_never_consumes_attempts_or_leases(self):
        self.post('one')
        plan = self.box.plan(self.ch, counters=[len])
        self.assertEqual([j.id for j in plan.jobs], ['one'])
        self.assertEqual(self.box.inspect('one')['attempts'], 0)
        self.assertEqual(self.box.stats(), {'pending': 1})
        self.assertEqual([e['event'] for e in self.box.history('one')], ['posted'])

    def test_oversized_head_does_not_block_small_job(self):
        self.post('large', ':' + 'X' * 4000)
        self.post('small', 'r13')
        budget = render(self.ch, [('small', 'r13')], counters=[len]).tokens[0]
        plan = self.box.plan(self.ch, counters=[len], max_tokens=budget)
        self.assertEqual([j.id for j in plan.jobs], ['small'])
        self.assertEqual(plan.deferred, ('large',))
        delivery, packet = self.box.claim_prepared(self.ch, owner='w', counters=[len],
                                                   receipt=R, max_tokens=budget)
        self.assertEqual(packet.tokens, (budget,))
        self.assertEqual(delivery.jobs[0].id, 'small')
        self.assertEqual(self.box.inspect('large')['attempts'], 0)

    def test_no_fitting_job_leaves_attempts_untouched(self):
        self.post('one')
        with self.assertRaises(BudgetError):
            self.box.claim_prepared(self.ch, owner='w', counters=[len], receipt=R, max_tokens=1)
        self.assertEqual(self.box.stats(), {'pending': 1})
        self.assertEqual(self.box.inspect('one')['attempts'], 0)

    def test_budgeted_claim_drains_without_losing_jobs(self):
        wire = ':' + 'measurement 12.50 ± 0.02 mm; ' * 20
        for i in range(3):
            self.post(f'm{i}', wire)
        budget = render(self.ch, [('m0', wire)], counters=[len]).tokens[0]
        delivered = []
        for _ in range(3):
            delivery, packet = self.box.claim_prepared(self.ch, owner='w', counters=[len],
                                                       receipt=R, max_tokens=budget)
            self.assertEqual(len(delivery.jobs), 1)
            self.assertEqual(delivery.jobs[0].wire, wire)
            self.assertLessEqual(packet.tokens[0], budget)
            delivered.extend(j.id for j in delivery.jobs)
            self.box.complete(delivery, {j.id: 'received' for j in delivery.jobs})
        self.assertEqual(delivered, ['m0', 'm1', 'm2'])
        self.assertEqual(self.box.stats(), {'done': 3})

    def test_system_text_is_inside_budget_and_receipt_stays_out_of_packet(self):
        self.post('one')
        packet = self.box.plan(self.ch, counters=[len], receipt='0123456789abcdef').packet
        self.assertEqual(packet.system, SYSTEM)
        self.assertEqual(packet.tokens, (len(SYSTEM) + 1 + len(packet.text),))
        self.assertNotIn('q', packet_data(packet))
        self.assertEqual(packet.receipt, '0123456789abcdef')
        with self.assertRaises(BudgetError):
            self.box.claim_prepared(self.ch, owner='w', counters=[len], receipt=R,
                                   max_tokens=packet.tokens[0] - 1)
        self.assertEqual(self.box.inspect('one')['attempts'], 0)
        claimed = self.box.claim_prepared(self.ch, owner='w', counters=[len], receipt=R,
                                          max_tokens=packet.tokens[0])
        self.assertEqual(claimed[1].system, SYSTEM)
        self.assertNotIn('q', packet_data(claimed[1]))
        self.assertEqual(claimed[1].receipt, R)

    def test_largest_feasible_prefix_found_when_feasibility_is_not_monotonic(self):
        for i in range(17):
            self.post(f'm{i:02d}')
        def jobs_in(text):
            # Each 'V' job expands into three model jobs.
            return len(json.loads(text.splitlines()[-1])['j']) // 3
        counter = lambda s: len(s) + (0 if jobs_in(s) == 16 else 100000)
        budget = self.box.plan(self.ch, counters=[counter], limit=16).packet.tokens[0]
        plan = self.box.plan(self.ch, counters=[counter], limit=17, max_tokens=budget)
        self.assertEqual(len(plan.jobs), 16)
        self.assertEqual([j.id for j in plan.jobs], [f'm{i:02d}' for i in range(16)])
        self.assertEqual(plan.deferred, ())

    def test_budget_counts_every_model_job_of_a_multi_atom_job(self):
        for i in range(4):
            self.post(f'm{i}')
        one = render(self.ch, [('m0', 'V')], counters=[len]).tokens[0]
        two = render(self.ch, [('m0', 'V'), ('m1', 'V')], counters=[len]).tokens[0]
        plan = self.box.plan(self.ch, counters=[len], max_tokens=two)
        self.assertEqual([j.id for j in plan.jobs], ['m0', 'm1'])
        self.assertEqual(plan.packet.tokens, (two,))
        self.assertGreater(two, one)
        self.assertEqual(len(packet_data(plan.packet)['j']), 6)
        self.assertEqual(plan.deferred, ())

    def test_claim_refuses_preview_receipt(self):
        self.post('one')
        with self.assertRaisesRegex(Error, 'fresh receipt'):
            self.box.claim_prepared(self.ch, owner='w', counters=[len], receipt='0' * 16)
        self.assertEqual(self.box.inspect('one')['attempts'], 0)

    def test_mixed_outcomes_only_unlock_successful_dependencies(self):
        self.post('ok')
        self.post('retry')
        self.post('failed')
        self.post('next', after=['ok'])
        self.post('blocked', after=['failed'])
        delivery = self.box.claim(self.ch, owner='w')
        self.box.settle(delivery, {'ok': Outcome('ok', 'actual result'),
                                   'retry': Outcome('retry', 'temporary'),
                                   'failed': Outcome('failed', 'permanent')}, retry_delay=5,
                        report={'provider_reported_usage': {'input_tokens': 20}})
        ready = self.box.claim(self.ch, owner='w')
        self.assertEqual([j.id for j in ready.jobs], ['next'])
        self.assertEqual(self.box.inspect('retry')['state'], 'pending')
        self.assertEqual(self.box.inspect('blocked')['waiting_for'], [{'id': 'failed', 'state': 'failed'}])
        self.now[0] += 5
        self.assertEqual(self.box.claim(self.ch, owner='w').jobs[0].id, 'retry')
        self.assertEqual(self.box.runs()[0]['report']['provider_reported_usage']['input_tokens'], 20)

    def test_partial_or_invalid_outcomes_never_partially_ack(self):
        self.post('one')
        self.post('two')
        delivery = self.box.claim(self.ch, owner='w')
        for outcomes in [{'one': Outcome('ok', 'x')},
                         {'one': Outcome('ok', 'x'), 'two': Outcome('ok', '')}]:
            with self.assertRaises(Error):
                self.box.settle(delivery, outcomes)
            self.assertEqual(self.box.stats(), {'leased': 2})
            self.assertEqual(self.box.runs(), [])

    def test_predecessor_results_are_unverified_data(self):
        self.post('first')
        self.post('next', 'r13', after=['first'])
        first = self.box.claim(self.ch, owner='w')
        text = '12.50 ± 0.02 mm\r\nMethod unknown; V is data.'
        self.box.complete(first, {'first': text})
        plan = self.box.plan(self.ch, counters=[len])
        body = packet_data(plan.packet)
        self.assertEqual(body['p'], {'first': text})
        self.assertEqual(body['h'], [['first', 0]])
        self.assertEqual(plan.packet.tokens, (len(plan.packet.system) + 1 + len(plan.packet.text),))
        self.assertNotIn('"next"', plan.packet.text)

    def test_shared_predecessor_output_is_sent_once_with_edge_per_job(self):
        self.post('first')
        self.post('a', after=['first'])
        self.post('b', after=['first'])
        self.box.complete(self.box.claim(self.ch, owner='w'), {'first': 'UNIQUE-PREDECESSOR-OUTPUT'})
        plan = self.box.plan(self.ch, counters=[len])
        self.assertEqual(plan.packet.text.count('UNIQUE-PREDECESSOR-OUTPUT'), 1)
        body = packet_data(plan.packet)
        self.assertEqual(body['p'], {'first': 'UNIQUE-PREDECESSOR-OUTPUT'})
        self.assertEqual(body['h'], [['first', k] for k in range(6)])
        self.assertEqual([j.id for j in plan.jobs], ['a', 'b'])

    def test_large_handoff_cannot_bypass_input_budget(self):
        self.post('first')
        self.post('next', after=['first'])
        self.box.complete(self.box.claim(self.ch, owner='w'), {'first': 'X' * 4000})
        budget = render(self.ch, [('next', 'V')], counters=[len]).tokens[0]
        with self.assertRaises(BudgetError):
            self.box.claim_prepared(self.ch, owner='w', counters=[len], receipt=R, max_tokens=budget)
        self.assertEqual(self.box.inspect('next')['attempts'], 0)

    def test_retry_backoff_and_explicit_requeue(self):
        self.post('one', max_attempts=1)
        delivery = self.box.claim(self.ch, owner='w')
        self.box.settle(delivery, {'one': Outcome('retry', 'temporary')}, retry_delay=9)
        self.assertEqual(self.box.inspect('one')['state'], 'failed')
        self.box.requeue('one')
        new = self.box.claim(self.ch, owner='w')
        self.assertEqual(new.jobs[0].attempt, 2)
        with self.assertRaises(Error):
            self.box.settle(delivery, {'one': Outcome('ok', 'late')})
        self.box.complete(new, {'one': 'result'})
        with self.assertRaises(Error):
            self.box.requeue('one')
        self.assertIn('requeued', [e['event'] for e in self.box.history('one')])

    def test_list_omits_payloads_and_paginates(self):
        self.post('one', ':private content')
        self.post('two')
        first = self.box.list_jobs(limit=1)
        second = self.box.list_jobs(limit=1, after_seq=first[0]['seq'])
        self.assertEqual(second[0]['id'], 'two')
        self.assertNotIn('private content', json.dumps(first))
        self.assertEqual(first[0]['availability'], 'ready')

    def test_plan_honors_dependencies_and_expired_attempts(self):
        self.post('one', max_attempts=1)
        self.post('two', after=['one'])
        self.box.claim(self.ch, owner='w', lease_seconds=1)
        self.now[0] += 2
        self.assertFalse(self.box.plan(self.ch, counters=[len]).jobs)
        self.assertIsNone(self.box.claim_prepared(self.ch, owner='w', counters=[len], receipt=R))
        self.assertEqual(self.box.inspect('one')['state'], 'failed')

    def test_concurrent_planners_never_reserve_same_job(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'queue.sqlite'
            with Inbox(path) as box:
                for i in range(24):
                    box.post(self.ch, f'm{i}', 'V', binding=self.ch.binding)
            def work(owner):
                with Inbox(path) as box:
                    claimed = box.claim_prepared(self.ch, owner=owner, counters=[len], receipt=R, limit=16)
                    return {j.id for j in claimed[0].jobs} if claimed else set()
            with ThreadPoolExecutor(max_workers=2) as pool:
                a, b = list(pool.map(work, ['a', 'b']))
            self.assertFalse(a & b)
            self.assertEqual(len(a | b), 24)

    def test_schema_one_upgrade_preserves_completed_job(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'v1.sqlite'
            db = sqlite3.connect(path)
            db.executescript('''
                CREATE TABLE channels(binding TEXT PRIMARY KEY,snapshot TEXT NOT NULL);
                CREATE TABLE jobs(seq INTEGER PRIMARY KEY,id TEXT UNIQUE NOT NULL,
                    binding TEXT NOT NULL,wire TEXT NOT NULL,identity TEXT NOT NULL,kind TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,lease TEXT,owner TEXT,deadline REAL,result TEXT,error TEXT NOT NULL DEFAULT '');
                PRAGMA user_version=1;
            ''')
            db.execute('INSERT INTO channels VALUES (?,?)', (self.ch.binding, json.dumps(self.ch.snapshot())))
            db.execute("INSERT INTO jobs(id,binding,wire,identity,kind,state,max_attempts,result) VALUES (?,?,?,?,?,?,?,?)",
                       ('old', self.ch.binding, 'V', 'legacy', 'work', 'done', 3, 'original result'))
            db.commit()
            db.close()
            with Inbox(path) as box:
                self.assertEqual(box.inspect('old')['result'], 'original result')
                self.assertIsNone(box.claim(self.ch, owner='w'))
                self.assertEqual(box.channel(self.ch.binding).binding, self.ch.binding)
                self.assertEqual(box.db.execute('PRAGMA user_version').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
