"""Council 3 blockers (docs/design/ozmap-2026-10-24/council3-astra.md B1 to B12, council3-opus.md A, B and 3 to 7):
one test or more per blocker, including the five Astra asked for by name (missing bootstrap method, replacement after
an unknown bootstrap, a new request after a crash, a wrongly valid report after a memo audit, a missing cost after
reconciliation). Fake and replay adapters only, no model calls, no network."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'examples'))
sys.path.insert(0, str(REPO / 'tests'))

import bootstrap_shim as shim  # noqa: E402
from oz import Error  # noqa: E402
import oz_host  # noqa: E402
import oz_rule  # noqa: E402
import oz_rulephase as rp  # noqa: E402
import oz_spool  # noqa: E402
import test_oz_host as th  # noqa: E402
import test_oz_rulephase as trp  # noqa: E402

FIELD = th.FIELD
FULL = {'input_tokens': 100, 'cached_input_tokens': 40, 'cache_creation_input_tokens': 0, 'output_tokens': 10,
        'reasoning_output_tokens': 4}


def boot_ids(producers=4, n=40, missing=None):
    assignment = rp.bootstrap_assignment(
        {f'p{p}': [j['dataset_id'] for j in th.producer_jobs(p, n, missing)] for p in range(producers)}, 20261024)
    return {d for ids in assignment.values() for d in ids}


class Host(th.Base):
    def submit(self, host, wave='cold', producers=4, n=40, missing=None, tag=''):
        for p in range(producers):
            host.submit(f'p{p}', f's{host.arm}{wave}{p}', th.producer_jobs(p, n, missing, tag=tag), wave=wave)

    def reopen(self, host, adapter, **kw):
        host.close()
        self.hosts.remove(host)
        return self.host(host.arm, adapter, **kw)


# ------------------------------------------------------------------------------------------------- B1

class B1BootstrapMethod(Host):
    def test_missing_bootstrap_method_is_caught_a_real_bootstrap_call_happens(self):
        for workload, multi in (('one', False), ('two', True)):
            with self.subTest(multi=multi):
                adapter = oz_host.ReplayAdapter(th.extract, {'e': FIELD, 'n': th.COUNT} if multi else {'e': FIELD})
                if multi:
                    h = oz_host.ArmHost(arm='B', backend='fake', workload=workload, experiment_dir=self.dir,
                                        launcher=oz_host.InProcessLauncher(shim.CallableShim(adapter)),
                                        op={'e': 'Extract the length.', 'n': 'Extract n.'}, op_text=None,
                                        model='m-test', effort='low', identity=oz_host.identity_for(th.ROUTE),
                                        registry=th.two_op_registry(), seed=20261024, allow_experimental=True,
                                        max_wait=0.0)
                    self.hosts.append(h)
                else:
                    h = oz_host.ArmHost(
                        arm='B', backend='fake', workload=workload, experiment_dir=self.dir,
                        launcher=oz_host.InProcessLauncher(shim.CallableShim(adapter)), op='e',
                        op_text='Extract the length.', model='m-test', effort='low',
                        identity=oz_host.identity_for(th.ROUTE), registry=self.registry, seed=20261024,
                        allow_experimental=True, max_wait=0.0)
                    self.hosts.append(h)
                for p in range(4):
                    jobs = [{'key': f'k{i}', 'op': ('e' if not multi or i % 2 else 'n'), 'dataset_id': f'{workload}{p}-{i}',
                             'text': f'length={p}.{i:02d} mm; n={1000 + 100 * p + i}\n'} for i in range(20)]
                    h.submit(f'p{p}', f's{p}', jobs, wave='cold')
                report = h.run_wave('cold')
                boots = adapter.calls(bootstrap=True)
                self.assertEqual(len(boots), 1)  # the bootstrap call really happened
                self.assertEqual(len(boots[0]['ids']), 64)
                [attempt] = [a for a in h.ledger.attempts('cold') if a['round'] == 'bootstrap']
                self.assertEqual((attempt['outcome'], len(attempt['call_ids'])), ('physical', 1))
                config = json.loads((h.side_dir / f"{attempt['attempt_id']}.config.json").read_text('utf-8'))
                shim.validate_config(config)
                self.assertEqual(config['ops'], list(h.ops))
                self.assertEqual(report['bootstrap']['status'], h.experiment.bootstrap('fake', workload)['record']
                                 ['status'])
                self.assertTrue(report['bootstrap']['one_call'])

    def test_a_broken_bootstrap_config_launches_nothing_and_holds_the_jobs(self):
        adapter = oz_host.ReplayAdapter(th.extract, {'e': FIELD})
        b = self.host('B', adapter)

        def broken():
            raise AttributeError("'ArmHost' object has no attribute '_bootstrap_config'")

        b._bootstrap_config = broken
        self.submit(b)
        with self.assertRaisesRegex(AttributeError, '_bootstrap_config'):
            b.run_wave('cold')  # loud before launch, never a silent report
        self.assertEqual((adapter.log, b.ledger.attempts(), b.budget.usage()['total']), ([], [], 0))
        self.assertIsNone(b.experiment.bootstrap('fake', 'mat')['record'])
        # A config that fails its schema check inside the launch is a proven-unlaunched refusal.
        del b._bootstrap_config

        def invalid(config):
            raise ValueError('the bootstrap config must be exactly {schema, ops, contracts, eligibility}')

        b._check_config = invalid
        report = b.run_wave('cold')
        self.assertEqual(adapter.log, [])
        self.assertEqual(b.budget.usage()['total'], 0)
        [attempt] = b.ledger.attempts('cold')
        self.assertEqual((attempt['state'], attempt['outcome']), ('refused', 'unlaunched'))
        self.assertTrue(attempt['error'].startswith('prelaunch_failed: ValueError'))
        self.assertIsNone(b.experiment.bootstrap('fake', 'mat')['record'])
        self.assertEqual(report['evidence'], 'incomplete')
        self.assertIn('bootstrap_pending', report['incomplete'])


# ------------------------------------------------------------------------------------------------- B2

class B2PendingBootstrap(Host):
    def test_replacement_after_unknown_bootstrap_never_happens(self):
        adapter = oz_host.ReplayAdapter(th.extract, {'e': FIELD})

        def crash_after_bootstrap(view, execution):
            if len(view['records']) == 64:
                raise RuntimeError('host lost the capture of the bootstrap call')

        def reconcile_fails(spec, env, evidence):
            return None, {'exit_code': 1, 'timed_out': False, 'stdout_sha256': None, 'stderr_sha256': None}

        b = self.host('B', adapter, hooks={'after_execute': crash_after_bootstrap,
                                            'reconcile_launcher': reconcile_fails})
        self.submit(b)
        report = b.run_wave('cold')
        self.assertEqual(len(adapter.log), 1)  # only the bootstrap: no fallback or replacement request
        assigned = boot_ids()
        rows = {r['dataset_id']: r for r in b._rows.values()}
        for d, row in rows.items():
            self.assertEqual(row['status'], 'unresolved')
            self.assertTrue(row['error'].startswith('bootstrap_pending' if d in assigned else 'waiting_for_bootstrap'))
        self.assertIn('bootstrap_pending', report['incomplete'])
        self.assertIsNone(b.experiment.bootstrap('fake', 'mat')['record'])
        [attempt] = b.ledger.attempts('cold')
        self.assertIn('reconcile_failed', [e['event'] for e in b.ledger.events(attempt['attempt_id'])])
        # A second arm waits for (never replaces) the pending bootstrap.
        c_adapter = oz_host.ReplayAdapter(th.extract, {'e': FIELD})
        c = self.host('C', c_adapter, bootstrap_wait=0.2)
        self.submit(c)
        rc = c.run_wave('cold')
        self.assertEqual(c_adapter.log, [])
        self.assertEqual(rc['unresolved'], 160)
        # The restarted owner reconciles the existing invocation: still exactly one bootstrap call.
        b2 = self.reopen(b, adapter)
        report = b2.run_wave('cold')
        self.assertEqual(len(adapter.calls(bootstrap=True)), 1)
        record = b2.experiment.bootstrap('fake', 'mat')['record']
        self.assertEqual((record['status'], record['one_call']), ('ok', True))
        self.assertEqual(report['unresolved'], 0)
        self.assertEqual(report['evidence'], 'complete', report['incomplete'])

    def test_a_proven_unlaunched_bootstrap_gets_a_new_try(self):
        adapter = oz_host.ReplayAdapter(th.extract, {'e': FIELD})
        refuse = {'on': True}
        b = self.host('B', adapter, hooks={'launch_gate': lambda view: 'gate_closed' if refuse['on'] else None})
        self.submit(b)
        first = b.run_wave('cold')
        self.assertEqual(adapter.log, [])
        self.assertIn('bootstrap_pending', first['incomplete'])
        refuse['on'] = False
        second = b.run_wave('cold')
        self.assertEqual(len(adapter.calls(bootstrap=True)), 1)
        rounds = sorted({a['round'] for a in b.ledger.attempts('cold') if a['round'].startswith('bootstrap')})
        self.assertEqual(rounds, ['bootstrap', 'bootstrap-2'])
        self.assertEqual(second['bootstrap']['status'], 'ok')
        self.assertEqual([a['attempt_id'] for a in b.experiment.bootstrap('fake', 'mat')['record']['attempts']
                          if a['outcome'] == 'unlaunched'], [a['attempt_id'] for a in b.ledger.attempts('cold')
                                                              if a['round'] == 'bootstrap'])


# ------------------------------------------------------------------------------------------------- B3

class B3BootstrapSettlement(Host):
    def test_success_needs_the_final_settlement_of_all_64_and_the_importer_inherits_failure(self):
        adapter = oz_host.ReplayAdapter(th.extract, {'e': FIELD})
        b = self.host('B', adapter)
        self.submit(b, missing=9)  # some assigned jobs answer "unknown", which fails quoted_span at settlement
        rb = b.run_wave('cold')
        record = b.experiment.bootstrap('fake', 'mat')['record']
        self.assertTrue(all(a['status'] == 'accepted' for a in record['jobs'].values()))  # oz_do accepted them all
        self.assertEqual((record['status'], record['efficiency_valid']), ('answers_failed', False))
        self.assertTrue(record['failures'] and all(':failed:check_failed:' in f for f in record['failures']))
        self.assertEqual(len(record['attempts']), 1)
        self.assertEqual(len(record['calls']), 1)
        self.assertEqual(len(record['calls'][0]['datasets']), 64)
        self.assertIn('bootstrap_answers_failed', rb['efficiency_invalid'])
        c = self.host('C', oz_host.ReplayAdapter(th.extract, {'e': FIELD}))
        self.submit(c, missing=9)
        rc = c.run_wave('cold')
        self.assertTrue(rc['bootstrap']['imported'])
        self.assertIn('bootstrap_answers_failed', rc['efficiency_invalid'])
        failed = [r for r in c._rows.values() if r['phase'] == 'bootstrap' and r['status'] == 'failed']
        self.assertEqual(len(failed), len(record['failures']))

    def test_the_packet_is_checked_against_the_input_limit_before_launch(self):
        adapter = oz_host.ReplayAdapter(th.extract, {'e': FIELD})
        b = self.host('B', adapter, limits={'max_input_tokens': 2000})
        self.submit(b)
        with self.assertRaisesRegex(Error, 'exceeds max_input_tokens'):
            b.run_wave('cold')
        self.assertEqual((adapter.log, b.budget.usage()['total'], b.ledger.attempts()), ([], 0, []))

    def test_the_bootstrap_must_be_one_batch(self):
        with self.assertRaisesRegex(Error, 'one batch'):
            self.host('B', oz_host.ReplayAdapter(th.extract), max_records=32)


# ------------------------------------------------------------------------------------------------- B4 / Opus A

class B4DurablePlan(Host):
    def test_new_request_after_crash_is_never_made(self):
        adapter = oz_host.ReplayAdapter(th.extract, {'e': FIELD})
        settled = []

        def crash_mid_settlement(row):
            if row['phase'] == 'fallback':
                settled.append(row['id'])
                if len(settled) == 5:
                    raise RuntimeError('host crashed while settling the residual answers')

        c = self.host('C', adapter, hooks={'after_row': crash_mid_settlement})
        self.submit(c, missing=9)  # several fallbacks fail their check: terminal, never sent again
        with self.assertRaisesRegex(RuntimeError, 'crashed'):
            c.run_wave('cold')
        calls_before = len(adapter.log)
        requests_before = {a['request_id'] for a in c.ledger.attempts()}
        plan_before = c.ledger.plan('cold')
        c2 = self.reopen(c, adapter)
        report = c2.run_wave('cold')
        self.assertEqual(len(adapter.log), calls_before)  # no new physical call
        self.assertEqual({a['request_id'] for a in c2.ledger.attempts()}, requests_before)
        self.assertEqual(c2.ledger.plan('cold'), plan_before)
        self.assertNotIn('plan_closed:r1', report['incomplete'])
        failed = [r for r in c2._rows.values() if r['phase'] == 'fallback' and r['status'] == 'failed']
        self.assertTrue(failed)
        for r in failed:
            self.assertEqual(c2.store.settlement(r['id'])['state'], 'failed')
            self.assertIsNone(c2.store.claim(r['id']))  # terminal: no execution authority again
        self.assertEqual(report['evidence'], 'complete', report['incomplete'])

    def test_resume_keeps_the_first_delivery_time_and_payload(self):
        adapter = oz_host.ReplayAdapter(th.extract, {'e': FIELD})
        c = self.host('C', adapter)
        self.submit(c)
        c.run_wave('cold')
        first = {k: (v['delivered_at'], v['value_text']) for k, v in c._rows.items()}
        c2 = self.reopen(c, adapter)
        time.sleep(0.05)
        c2.run_wave('cold')
        self.assertEqual({k: (v['delivered_at'], v['value_text']) for k, v in c2._rows.items()}, first)
        self.assertTrue(all(v['resumed'] for v in c2._rows.values()))
        with self.assertRaises(sqlite3.DatabaseError):
            c2.ledger.db.execute('UPDATE deliveries SET at=0')

    def test_a_crash_between_the_spool_launch_mark_and_the_ledger_is_provably_unlaunched(self):
        adapter = oz_host.ReplayAdapter(th.extract)

        def fault(point, batch_id):
            if point == 'after_launch_mark':
                raise RuntimeError('host died after the spool launch mark')

        a = self.host('A', adapter, hooks={'spool_fault': fault})
        a.submit('p0', 's0', th.producer_jobs(0, 6), wave='w')
        with self.assertRaisesRegex(RuntimeError, 'host died'):
            a.run_wave('w')
        self.assertEqual((adapter.log, a.ledger.attempts()), ([], []))
        a2 = self.reopen(a, adapter)
        report = a2.run_wave('w')
        self.assertEqual(len(adapter.log), 1)  # launched once, under the same request id
        self.assertEqual(report['accepted_by_checks'], 6)
        self.assertTrue(report['reconciliation']['ok'], report['reconciliation']['problems'])

    def test_a_reservation_without_a_ledger_attempt_is_a_reconciliation_problem(self):
        a = self.host('A', oz_host.ReplayAdapter(th.extract))
        a.submit('p0', 's0', th.producer_jobs(0, 3), wave='w')
        a.run_wave('w')
        conn = a.spool._connect()
        conn.execute("INSERT INTO batches(batch_id, request_id, bindings_hash, state, size) VALUES "
                     "('bx', 'qorphan', 'h', 'reserved', 1)")
        conn.close()
        a.budget.reserve('qorphan', backend='fake', buckets=['A'], arm='A', kind='dispatch')
        rec = a.reconcile('w')
        self.assertIn('reservation qorphan has no ledger attempt', rec['problems'])

    def test_a_job_outside_the_stored_round_is_not_added(self):
        adapter = oz_host.ReplayAdapter(th.extract)
        a = self.host('A', adapter)
        a.submit('p0', 's0', th.producer_jobs(0, 5), wave='w')
        a.run_wave('w')
        job = a._jobs('w')[0]
        extra = dict(a._item(job, 'ordinary', 'pool'), id='ordinary:new')
        out = a._dispatch('w', 'r1', [extra])
        self.assertEqual(out['ordinary:new'][0]['error'].split(':')[0], 'plan_closed')
        self.assertIn('plan_closed:r1', a.ledger.violations('w')['incomplete'])
        self.assertEqual(len(adapter.log), 1)


# ------------------------------------------------------------------------------------------------- B5

class B5Authority(unittest.TestCase):
    def setUp(self):
        trp.Base.setUp(self)
        self.learn = rp.Learner(self.store, trp.registry(), 'e', worker_hash=trp.WORKER, map_contract='c' * 64,
                                map_input_policy='strip-one-terminal-newline/1')
        self.rule = self.store.rule(self.learn.admit_side(trp.side_ok(trp.FIELD), source='s',
                                                          provenance={}))
        self.owner = {'producer': 'p', 'submission': 's', 'operation': 'e', 'path': 'a'}

    def open(self, job='j1'):
        self.store.open_job(job, payload_sha256='p' * 64, bindings_sha256='b' * 64, required=self.learn.required)
        return self.store.claim(job)

    def test_mark_awaiting_is_fenced(self):
        old = self.open()
        self.store.claim('j1')
        state = self.store.mark_awaiting('j1', generation=old, payload_sha256='p' * 64, bindings_sha256='b' * 64,
                                         source='rule', value_text='"x"', type_='string', checks=[], reason='r')
        self.assertEqual(state, ('refused', 'stale_generation'))
        self.assertEqual(self.store.settlement('j1')['state'], 'open')
        state = self.store.mark_awaiting('j1', generation=old + 1, payload_sha256='q' * 64, bindings_sha256='b' * 64,
                                         source='rule', value_text='"x"', type_='string', checks=[], reason='r')
        self.assertEqual(state, ('refused', 'identity_mismatch'))

    def test_an_existing_result_is_returned_only_for_the_identical_identity(self):
        text = 'length=1.00 mm'
        generation = self.open()
        got = self.learn.attempt(self.rule, job='j1', text=text, resolved_sha256=rp.sha256_text(text), op_text='x',
                                 owner=self.owner, generation=generation, payload_sha256='p' * 64,
                                 bindings_sha256='b' * 64)
        self.assertEqual(got['decision'], 'rule')
        again = self.learn.attempt(self.rule, job='j1', text=text, resolved_sha256=rp.sha256_text(text),
                                   op_text='x', owner=self.owner, generation=generation, payload_sha256='p' * 64,
                                   bindings_sha256='b' * 64)
        self.assertTrue(again['resumed'])
        with self.assertRaisesRegex(Error, 'identity'):
            self.learn.attempt(self.rule, job='j1', text=text, resolved_sha256=rp.sha256_text(text), op_text='x',
                               owner=self.owner, generation=generation, payload_sha256='z' * 64,
                               bindings_sha256='b' * 64)
        first = oz_rule.evaluate(self.rule['ast'], text)
        state = self.store.adopt_rule(rule=self.rule, binding_key=self.learn.key, job='j1', text=text,
                                      resolved_sha256=rp.sha256_text(text), first=first, checks=[], owner=self.owner,
                                      generation=generation, payload_sha256='z' * 64, bindings_sha256='b' * 64)
        self.assertEqual(state, ('refused', 'present_identity_mismatch'))

    def test_a_failed_check_is_terminal(self):
        generation = self.open()
        checks = self.learn.evidence('"9.99 mm"', 'length=1.00 mm', 'x')
        self.assertEqual(self.store.settle_model('j1', generation=generation, payload_sha256='p' * 64,
                                                 bindings_sha256='b' * 64, value_text='"9.99 mm"',
                                                 checks=checks)[0], 'failed')
        self.assertEqual(self.store.settlement('j1')['state'], 'failed')
        self.assertIsNone(self.store.claim('j1'))
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.db.execute("UPDATE settlements SET state='open'")

class B5HostAuthority(Host):
    def test_the_host_claims_authority_before_dispatch_and_audits_never_claim(self):
        c = self.host('C', oz_host.ReplayAdapter(th.extract, {'e': FIELD}))
        claims = []

        def gate(view):
            claims.append({r['id']: c.store.settlement(c._items[r['id']]['job']['name'])['generation']
                           for r in view['records']})

        c.hooks['launch_gate'] = gate
        self.submit(c)
        c.run_wave('cold')
        grants = c.ledger.authority()
        granted = {(g['job'], g['round']) for g in grants}
        for batch in claims:
            for delivery, generation in batch.items():
                item = c._items[delivery]
                if item['kind'] in oz_host.SETTLING:
                    self.assertGreater(generation, 0)  # claimed before the launch
                    self.assertIn((item['job']['name'], item['round']), granted)
        audited = {a['original_job'] for a in c.store.audits()}
        self.assertFalse({g['job'] for g in grants if g['round'] in ('r1', 'r2')} & audited)


# ------------------------------------------------------------------------------------------------- B6 / Opus B

class _CrashAfterCall:
    """Runs the real in-process execution, then reports the child as crashed (no execution returned)."""

    def __init__(self, inner, *, run=True):
        self.inner, self.run = inner, run

    def __call__(self, spec, env, evidence):
        if self.run:
            self.inner(spec, env, evidence)
        evidence.mkdir(parents=True, exist_ok=True)
        return None, oz_host._write_raw(evidence, {'exit_code': 1, 'timed_out': False, 'stdout': b'',
                                                   'stderr': b'child crashed'})


class B6Accounting(Host):
    def test_missing_cost_after_reconciliation_is_never_lost(self):
        adapter = oz_host.ReplayAdapter(th.extract)
        launcher = _CrashAfterCall(oz_host.InProcessLauncher(shim.CallableShim(adapter)))
        a = self.host('A', adapter, launcher=launcher, hooks={'reconcile_launcher': launcher})
        a.submit('p0', 's0', th.producer_jobs(0, 10), wave='w')
        report = a.run_wave('w')
        [attempt] = a.ledger.attempts('w')
        self.assertEqual((attempt['state'], attempt['outcome'], len(attempt['call_ids'])), ('failed', 'physical', 1))
        call = attempt['calls'][0]
        self.assertEqual((call['usage_known'], call['input_tokens'], call['output_tokens']), (1, 100, 10))
        self.assertEqual(len(call['jobs']), 10)
        events = [e['event'] for e in a.ledger.events(attempt['attempt_id'])]
        self.assertEqual(events[:2], ['launched', 'failed'])
        self.assertIn('reconcile_failed', events)
        self.assertEqual(report['tokens']['physical']['tokens'], 110)  # the cost is in the ledger
        self.assertEqual(report['tokens']['charged']['usage'], 'complete')
        self.assertEqual(report['unresolved'], 10)
        self.assertEqual(report['evidence'], 'incomplete')
        self.assertTrue(report['reconciliation']['ok'])
        self.assertEqual(len(a.ledger.allocations('w')), 10)
        # The first evidence and elapsed stay as first written.
        self.assertIsNotNone(attempt['elapsed'])
        with self.assertRaises(sqlite3.DatabaseError):
            a.ledger.db.execute('UPDATE attempts SET elapsed=NULL')
        with self.assertRaises(sqlite3.DatabaseError):
            a.ledger.db.execute("UPDATE attempts SET outcome='unresolved'")

    def test_a_launch_without_any_call_record_stays_unresolved_and_blocks_complete_accounting(self):
        adapter = oz_host.ReplayAdapter(th.extract)
        launcher = _CrashAfterCall(None, run=False)
        a = self.host('A', adapter, launcher=launcher)
        a.submit('p0', 's0', th.producer_jobs(0, 4), wave='w')
        report = a.run_wave('w')
        [attempt] = a.ledger.attempts('w')
        self.assertEqual(attempt['outcome'], 'unresolved')
        self.assertFalse(report['reconciliation']['ok'])
        self.assertEqual(report['reconciliation']['unresolved_attempts'], [attempt['attempt_id']])
        self.assertIn('1 launches without a resolved physical outcome', report['incomplete'])

    def test_conflicting_duplicate_inserts_are_hard_errors(self):
        a = self.host('A', oz_host.ReplayAdapter(th.extract))
        a.submit('p0', 's0', th.producer_jobs(0, 3), wave='w')
        a.run_wave('w')
        row = a.ledger.allocations('w')[0]
        a.ledger.allocate([row])  # identical: no-op
        with self.assertRaisesRegex(Error, 'conflicting duplicate allocation'):
            a.ledger.allocate([dict(row, share=0.5)])
        [attempt] = a.ledger.attempts('w')
        call = dict(attempt['calls'][0])
        with a.ledger.tx() as db:
            with self.assertRaisesRegex(Error, 'conflicting duplicate of call'):
                a.ledger._attribute(db, attempt['attempt_id'], attempt['request_id'],
                                    [dict(call, usage={'input_tokens': 1, 'output_tokens': 1})])
        with self.assertRaisesRegex(Error, 'exists differently'):
            plan = a.ledger.plan('w', 'r1')[0]
            a.ledger.add_plan([dict(plan, kind='audit')], 0.0)


# ------------------------------------------------------------------------------------------------- B7

class B7Membership(Host):
    def test_allocation_follows_the_call_job_map_not_the_batch(self):
        adapter = oz_host.ReplayAdapter(th.extract)
        a = self.host('A', adapter, limits={'max_input_tokens': 700})  # the planner sends only part of the batch
        a.submit('p0', 's0', th.producer_jobs(0, 20), wave='w')
        report = a.run_wave('w')
        [attempt] = a.ledger.attempts('w')
        [call] = attempt['calls']
        self.assertLess(len(call['jobs']), 20)
        allocations = a.ledger.allocations('w')
        self.assertEqual({x['job'] for x in allocations}, set(call['jobs']))
        self.assertTrue(all(abs(x['share'] - 1 / len(call['jobs'])) < 1e-12 for x in allocations))
        m = report['calls']['membership']
        self.assertEqual((m['planned'], m['dispatched']), (20, len(call['jobs'])))
        self.assertEqual(m['accepted_with_call'], report['accepted_by_checks'])
        self.assertTrue(report['reconciliation']['ok'])


# ------------------------------------------------------------------------------------------------- B8

class B8Timing(Host):
    def test_the_importer_is_charged_the_recorded_bootstrap_and_phases_are_persisted(self):
        usage = [{'input_tokens': 100, 'output_tokens': 10}]
        b = self.host('B', oz_host.ReplayAdapter(th.extract, {'e': FIELD}, usage))
        self.submit(b)
        rb = b.run_wave('cold')
        record = b.experiment.bootstrap('fake', 'mat')['record']
        self.assertGreater(record['elapsed_seconds'], 0.0)
        self.assertAlmostEqual(record['elapsed_seconds'], b.ledger.phase_seconds('cold')['bootstrap'], places=6)
        self.assertEqual(rb['charged_makespan_seconds'], rb['measured_makespan_seconds'])
        self.assertIn('bootstrap', rb['phase_seconds'])
        c = self.host('C', oz_host.ReplayAdapter(th.extract, {'e': FIELD}))
        self.submit(c)
        rc = c.run_wave('cold')
        expected = rc['measured_makespan_seconds'] - rc['phase_seconds'].get('bootstrap_wait', 0.0) + \
            record['elapsed_seconds']
        self.assertAlmostEqual(rc['charged_makespan_seconds'], round(expected, 6), places=5)
        self.assertGreater(rc['charged_makespan_seconds'], rc['measured_makespan_seconds'])
        self.assertIn('bootstrap_import', rc['phase_seconds'])
        self.assertEqual(rc['summed_call_seconds'], round(sum(a['elapsed'] for a in c.ledger.attempts('cold')), 6))
        edges = [(t['phase'], t['edge']) for t in c.ledger.timeline('cold')]
        self.assertEqual(edges[0], ('wave', 'start'))
        self.assertEqual(edges[-1], ('wave', 'end'))


# ------------------------------------------------------------------------------------------------- B9

GRANDCHILD = r'''
import subprocess, sys, time
from pathlib import Path
p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
Path(sys.argv[-1]).with_name('grandchild.pid').write_text(str(p.pid))
time.sleep(120)
'''


def _alive(pid):
    if os.name == 'nt':
        out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class B9Launch(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def test_timeout_kills_the_whole_child_process_tree(self):
        script = self.dir / 'child.py'
        script.write_text(GRANDCHILD, encoding='utf-8')
        adapter = self.dir / 'adapter.json'
        adapter.write_text('{"argv": ["python"]}', encoding='utf-8')
        launcher = oz_host.ChildLauncher(adapter)
        original = oz_host.HOST_FILE
        oz_host.HOST_FILE = script
        try:
            started = time.monotonic()
            execution, meta = launcher({'child_timeout': 3}, dict(os.environ), self.dir / 'ev')
        finally:
            oz_host.HOST_FILE = original
        self.assertLess(time.monotonic() - started, 60)
        self.assertIsNone(execution)
        self.assertTrue(meta['timed_out'])
        pid = int((self.dir / 'ev' / 'grandchild.pid').read_text())
        deadline = time.monotonic() + 10
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertFalse(_alive(pid), 'the grandchild survived the timeout')

    def test_the_child_timeout_is_tied_to_call_timeout_seconds(self):
        self.assertEqual(oz_host.child_timeout({'call_timeout_seconds': 1200}), 1200 + oz_host.CHILD_MARGIN)
        self.assertEqual(oz_host.child_timeout({}), oz_host.DEFAULT_CALL_TIMEOUT + oz_host.CHILD_MARGIN)
        h = oz_host.ArmHost(arm='A', backend='fake', workload='t', experiment_dir=self.dir,
                            launcher=oz_host.InProcessLauncher(lambda r: None), op='e', op_text='x', model='m',
                            effort='low', identity=oz_host.identity_for(th.ROUTE),
                            limits={'call_timeout_seconds': 50})
        self.addCleanup(h.close)
        self.assertEqual(h._spec({}, 1)['child_timeout'], 50 + oz_host.CHILD_MARGIN)

    def test_scheduler_close_waits_for_inflight_launches_before_releasing_the_lock(self):
        spool = oz_spool.Spool(self.dir / 'spool.sqlite')
        release = threading.Event()
        entered = threading.Event()

        def launch(view):
            entered.set()
            release.wait(30)
            return {r['id']: {'ok': True} for r in view['records']}

        sched = oz_spool.Scheduler(spool, launch, max_wait=0.0)
        bindings = {k: 'x' for k in oz_spool.BINDING_KEYS}
        spool.submit('p', 's', [{'key': 'k', 'op': 'o', 'text': 't', 'dataset_id': 'd'}], bindings)
        sched.pump()
        self.assertTrue(entered.wait(10))
        closed = threading.Event()
        threading.Thread(target=lambda: (sched.close(), closed.set()), daemon=True).start()
        time.sleep(0.3)
        self.assertFalse(closed.is_set())
        with self.assertRaises(oz_spool.HostLocked):
            oz_spool.Scheduler(spool, launch)  # the lock is still held while the launch runs
        release.set()
        self.assertTrue(closed.wait(10))
        self.assertTrue(spool.collect('p', 's')['complete'])  # captured and delivered before release
        oz_spool.Scheduler(spool, launch).close()

    def test_the_slot_pool_is_experiment_wide_and_frozen(self):
        pool = oz_host.SlotPool(self.dir / 'slots', 2)
        other = oz_host.SlotPool(self.dir / 'slots', 2)  # a second host of the same experiment
        a, b = pool.acquire(), other.acquire()
        got = []
        t = threading.Thread(target=lambda: got.append(pool.acquire()))
        t.start()
        time.sleep(0.3)
        self.assertEqual(got, [])  # both slots held: the third launch waits
        other.release(b)
        t.join(10)
        self.assertEqual(len(got), 1)
        pool.release(a)
        pool.release(got[0])
        with self.assertRaisesRegex(Error, 'frozen at 2'):
            oz_host.SlotPool(self.dir / 'slots', 4)

    def pilot(self, **over):
        caps = {'fake': {'A': 2, 'reserve': 1}}
        config = {'schema': oz_host.PILOT_SCHEMA, 'mode': 'dry', 'global_cap': 3, 'caps': caps, 'slots': 4,
                  'max_records': 64, 'max_wait': 0.0, 'intake': {'producers': 1, 'per_producer': 3},
                  'limits': {'call_timeout_seconds': 60, 'deadline_seconds': 120, 'max_input_tokens': 100000},
                  'usage_semantics': 'replay', 'routes': {'fake': oz_host.identity_for(th.ROUTE)}}
        config.update(over)
        return config

    def pilot_host(self, config, *, budget_caps=None, pool=True, **kw):
        self.n = getattr(self, 'n', 0) + 1
        budget = oz_host.Budget(self.dir / f'budget{self.n}.sqlite',
                                caps=budget_caps or config['caps'], global_cap=config['global_cap'])
        self.addCleanup(budget.close)
        h = oz_host.ArmHost(arm='A', backend='fake', workload=kw.pop('workload', f't{self.n}'), experiment_dir=self.dir,
                            launcher=kw.pop('launcher', oz_host.InProcessLauncher(shim.CallableShim(
                                oz_host.ReplayAdapter(th.extract, samples=[FULL])))), op='e', op_text='x',
                            model='m-test',
                            effort='low', identity=oz_host.identity_for(th.ROUTE), budget=budget,
                            slot_pool=oz_host.SlotPool(self.dir / 'slots', 4) if pool else None, slots=4,
                            max_wait=0.0, limits=config['limits'], pilot=config, usage_semantics='replay',
                            allow_experimental=True, **kw)
        self.addCleanup(h.close)
        return h

    def test_the_pilot_entry_refuses_without_the_complete_frozen_configuration(self):
        good = self.pilot()
        h = self.pilot_host(good)
        h.submit('p0', 's0', th.producer_jobs(0, 3, None), wave='w')
        report = h.run_wave('w')
        self.assertEqual(report['evidence'], 'complete', report['incomplete'])
        # A pilot never takes a missing usage component as zero: such a call leaves the evidence incomplete.
        thin = self.pilot_host(good, launcher=oz_host.InProcessLauncher(shim.CallableShim(
            oz_host.ReplayAdapter(th.extract))), workload='thin')
        thin.submit('p0', 's0', th.producer_jobs(0, 3, None), wave='w')
        self.assertTrue(any(r.startswith('usage_components_unknown') for r in thin.run_wave('w')['incomplete']))
        for over, kw, needle in (({'limits': {'call_timeout_seconds': 60}}, {}, 'limits must freeze'),
                                 ({}, {'budget_caps': {'fake': {'A': 9}}}, 'budget is not frozen'),
                                 ({}, {'pool': False}, 'slot pool'),
                                 ({'mode': 'live'}, {}, 'child processes only'),
                                 ({'routes': {}}, {}, 'frozen route')):
            with self.subTest(needle=needle), self.assertRaisesRegex(Error, 'pilot launch refused.*' + needle):
                config = dict(good, **over)
                self.pilot_host(config, **kw)
        bad = dict(good)
        del bad['routes']
        with self.assertRaisesRegex(Error, 'lacks routes'):
            self.pilot_host(bad)

    def test_the_pilot_intake_must_be_complete_before_any_call(self):
        h = self.pilot_host(self.pilot())
        h.submit('p0', 's0', th.producer_jobs(0, 2, None), wave='w')
        with self.assertRaisesRegex(Error, 'exactly 1 producers with 3 jobs'):
            h.run_wave('w')
        self.assertEqual(h.ledger.attempts(), [])


# ------------------------------------------------------------------------------------------------- B10

class B10Violations(Host):
    def test_memo_audit_never_leaves_a_wrongly_valid_report(self):
        adapter = oz_host.ReplayAdapter(th.extract, {'e': FIELD})
        served = []

        def memo_in_r1(view, execution):
            for rid in view['records']:
                item = c._items[rid['id']]
                if item['kind'] == 'audit' and item['round'] == 'r1':
                    execution['jobs'][rid['id']]['memo'] = True
                    served.append(rid['id'])

        c = self.host('C', adapter, hooks={'after_execute': memo_in_r1})
        self.submit(c)
        report = c.run_wave('cold')
        self.assertEqual(len(served), 32)
        self.assertEqual((report['audits']['agree'], report['audits']['inconclusive']), (32, 0))  # the retry agreed
        self.assertFalse(report['efficiency_valid'])
        self.assertIn('memo_served_audit', report['efficiency_invalid'])
        c2 = self.reopen(c, adapter)
        again = c2.run_wave('cold')
        self.assertIn('memo_served_audit', again['efficiency_invalid'])  # a resume never erases a violation
        with self.assertRaises(sqlite3.DatabaseError):
            c2.ledger.db.execute('DELETE FROM violations')

    def test_awaiting_verification_and_spool_rejections_count_against_evidence(self):
        runner = th.Flaky()
        self.registry = th.registry(runner)
        c = self.host('C', oz_host.ReplayAdapter(th.extract, {'e': FIELD}))
        self.submit(c)
        self.assertEqual(c.run_wave('cold')['evidence'], 'complete')
        runner.off = True
        for p in range(4):
            c.submit(f'p{p}', f'w{p}', th.producer_jobs(p, 8, tag='w'), wave='warm')
        warm = c.run_wave('warm', learn=False)
        self.assertIn(f"{warm['awaiting_verification']} jobs awaiting_verification", warm['incomplete'])
        runner.off = False
        conn = c.spool._connect()
        conn.execute("INSERT INTO rejections(at, attempt_id, job_id, reason, detail) VALUES (0, 'a', 'j', "
                     "'conflicting_duplicate_delivery', 'x')")
        conn.close()
        again = c.run_wave('cold')
        self.assertIn('spool_rejection:conflicting_duplicate_delivery', again['incomplete'])

    def test_usage_components_are_never_inferred_from_field_presence(self):
        out = oz_host._tokens([{'usage': {'input_tokens': 10, 'output_tokens': 2}},
                               {'usage': {'input_tokens': 5, 'output_tokens': 1, 'cached_input_tokens': 3}}])
        self.assertEqual(out['usage'], 'complete')
        self.assertEqual(out['components_missing']['cached_input_tokens'], 1)
        self.assertEqual(out['components_missing']['reasoning_output_tokens'], 2)
        self.assertEqual(out['cached_input_tokens'], 3)
        c = self.host('C', oz_host.ReplayAdapter(th.extract, {'e': FIELD}))
        self.submit(c)
        report = c.run_wave('cold')
        self.assertEqual(report['tokens']['semantics'], 'unverified')


# ------------------------------------------------------------------------------------------------- B11

class B11RouteCheck(Host):
    def test_a_route_mismatch_refuses_the_launch_before_any_budget(self):
        adapter = oz_host.ReplayAdapter(th.extract)
        seen = []

        def verify(env):
            seen.append(env['OZ_MODEL'])
            raise Error('worker route mismatch: frozen aaaa, recomputed bbbb; cli_version: frozen 1, now 2')

        a = self.host('A', adapter, hooks={'route_verify': verify})
        a.submit('p0', 's0', th.producer_jobs(0, 3), wave='w')
        report = a.run_wave('w')
        self.assertEqual((adapter.log, a.budget.usage()['total']), ([], 0))
        self.assertEqual(seen, ['m-test'])  # verified in the real launch env
        self.assertTrue(any(r.startswith('route_unverified: worker route mismatch') for r in report['incomplete']))

    def test_the_frozen_route_must_name_this_worker(self):
        a = self.host('A', oz_host.ReplayAdapter(th.extract), route_check={'frozen': 'f' * 64, 'adapter': 'x.json'})
        a.submit('p0', 's0', th.producer_jobs(0, 2), wave='w')
        report = a.run_wave('w')
        self.assertTrue(any('is not this host worker' in r for r in report['incomplete']))

    def test_oz_route_verify_runs_in_the_launch_env(self):
        calls = []

        def run(argv, **kw):
            calls.append(kw['env'].get('OZ_MODEL'))
            raise OSError('no adapter here')

        a = self.host('A', oz_host.ReplayAdapter(th.extract),
                      route_check={'frozen': {'worker_hash': a_hash()}, 'adapter': str(self.dir / 'a.json'),
                                   'model': 'm-test', 'effort': 'low', 'run': run})
        (self.dir / 'a.json').write_text('{"argv": ["python"]}', encoding='utf-8')
        a.submit('p0', 's0', th.producer_jobs(0, 2), wave='w')
        report = a.run_wave('w')
        self.assertEqual(report['accepted_by_checks'], 0)
        self.assertTrue(any(r.startswith('route_unverified') for r in report['incomplete']))


def a_hash():
    return oz_host.identity_for(th.ROUTE)['worker_hash']


# ------------------------------------------------------------------------------------------------- B12

class B12SealedWave(Host):
    def test_a_dataset_id_occurs_once_per_wave(self):
        a = self.host('A', oz_host.ReplayAdapter(th.extract))
        a.submit('p0', 's0', th.producer_jobs(0, 3), wave='w')
        a.submit('p1', 's1', [dict(th.producer_jobs(1, 1)[0], dataset_id='d0-0')], wave='w')
        with self.assertRaisesRegex(Error, 'occurs twice'):
            a.run_wave('w')
        self.assertEqual(a.ledger.attempts(), [])

    def test_every_arm_consumes_the_sealed_manifest(self):
        b = self.host('B', oz_host.ReplayAdapter(th.extract, {'e': FIELD}))
        self.submit(b)
        b.run_wave('cold')
        c_adapter = oz_host.ReplayAdapter(th.extract, {'e': FIELD})
        c = self.host('C', c_adapter)
        self.submit(c, tag='other')
        with self.assertRaisesRegex(Error, 'sealed manifest'):
            c.run_wave('cold')
        self.assertEqual(c_adapter.log, [])

    def test_bootstrap_import_verifies_binding_assignment_worker_and_payloads(self):
        b = self.host('B', oz_host.ReplayAdapter(th.extract, {'e': FIELD}))
        self.submit(b)
        b.run_wave('cold')
        c_adapter = oz_host.ReplayAdapter(th.extract, {'e': FIELD})
        c = self.host('C', c_adapter, goal='Another goal changes every payload.')
        self.submit(c)
        with self.assertRaisesRegex(Error, 'refusing to import the shared bootstrap: it differs in binding_key, '
                                           '.*dataset-id payloads'):
            c.run_wave('cold')
        self.assertEqual(c_adapter.log, [])

    def test_the_producers_start_from_one_barrier(self):
        seen = []
        lock = threading.Lock()

        class Recorder:
            def submit(self, producer, submission, jobs, *, wave):
                with lock:
                    seen.append((threading.current_thread().name, time.monotonic()))

        oz_host.submit_barrier(Recorder(), 'w', {f'p{i}': [] for i in range(4)}, lambda p: 's' + p)
        self.assertEqual(sorted(n for n, _ in seen), [f'producer-p{i}' for i in range(4)])
        self.assertLess(max(t for _, t in seen) - min(t for _, t in seen), 1.0)

    def test_the_dry_run_matrix_needs_the_full_intake(self):
        m = th.matrix()
        m['intake'] = {'producers': 4, 'per_producer': 65}
        with self.assertRaisesRegex(Error, 'exactly 4 producers with 65 jobs'):
            oz_host.dry_run(m, th.USAGE)


# ------------------------------------------------------------------------------------------------- Opus 3

class Opus3ImportResume(Host):
    def test_a_crash_between_admission_and_the_import_still_charges_the_bootstrap(self):
        b = self.host('B', oz_host.ReplayAdapter(th.extract, {'e': FIELD}))
        self.submit(b)
        b.run_wave('cold')
        c_adapter = oz_host.ReplayAdapter(th.extract, {'e': FIELD})
        c = self.host('C', c_adapter)
        original = c._import_allocations

        def crash(*args):
            raise RuntimeError('crash after admit_side, before the import')

        c._import_allocations = crash
        self.submit(c)
        with self.assertRaisesRegex(RuntimeError, 'crash after admit_side'):
            c.run_wave('cold')
        self.assertTrue(c.store.rules(c.learner.key))  # admitted already
        self.assertEqual(c.ledger.allocations('cold'), [])
        del original
        c2 = self.reopen(c, c_adapter)
        report = c2.run_wave('cold')
        imported = [x for x in c2.ledger.allocations('cold') if x['basis'] == 'imported']
        self.assertEqual(len(imported), 64)
        self.assertEqual(report['calls']['imported'], 1)
        self.assertGreater(report['tokens']['imported']['tokens'], 0)


if __name__ == '__main__':
    unittest.main()
