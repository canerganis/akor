"""oz_host: the step 6 host (arms A, B, C), shared bootstrap, evaluation-wave audits, rule-8 fallback, child env
isolation, re-dispatch without a second call, budget exhaustion, ledger reconciliation and the dry run. Fake and
replay adapters only, no model calls."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'examples'))

import bootstrap_shim as shim  # noqa: E402
from oz import Error  # noqa: E402
import oz_host  # noqa: E402
import oz_registry as reg  # noqa: E402
import oz_rulephase as rp  # noqa: E402
import oz_spool  # noqa: E402

ROUTE = {'adapter_hash': 'a' * 64, 'backend': 'fake', 'model': 'm-test', 'effort': 'low', 'cli_version': 'fake-1',
         'environment_hash': 'b' * 64}
POLICY = {'version': 'oz-input/1', 'terminal_newline': 'strip_one', 'text_ref': 0}
PROV = {'labeler': 'human-1', 'method': 'hand labeled', 'independent': True, 'hidden_from_synthesis': True,
        'synthesis_agents': ['astra']}
FIELD = '{"lang": "oz-rule/1",  "expr": ["field", "length"]}'  # spacing kept on purpose: exact bytes


class Flaky(reg.LocalChecks):
    """The local check runner, with quoted_span switchable to unavailable."""
    off = False

    def run(self, name, version, params, value, text):
        if self.off and name == 'quoted_span':
            raise reg.CheckUnavailable('quoted_span service down')
        return reg.LocalChecks.run(self, name, version, params, value, text)


def registry(runner=None):
    cases = [{'id': f'c{i}', 'text': f'length={i}.{i % 100:02d} mm; n=3',
              'partition': 'representative' if i < 48 else 'challenge',
              'expected': {'type': 'string', 'value': f'{i}.{i % 100:02d} mm'}} for i in range(64)]
    op = {'contract': {'name': 'extract_length', 'deterministic': True}, 'checks': ['span'], 'permissions': {},
          'input_policy': dict(POLICY), 'route': dict(ROUTE), 'cases': cases, 'provenance': dict(PROV)}
    checks = {'span': {'name': 'quoted_span', 'version': 1, 'kind': 'consumer', 'params': {}}}
    return reg.Registry(reg.build_manifest({'e': op}, checks, 'owner@example', runner), runner=runner)


def extract(text):
    m = re.search(r'length=([^;]*)', text)
    return m.group(1) if m else 'unknown'


def producer_jobs(p, n=40, missing=9, tag=''):
    return [{'key': f'k{tag}{i}', 'op': 'e', 'dataset_id': f'd{tag}{p}-{i}',
             'text': (f'length={p}.{i:02d}{tag} mm; n=3\n' if missing is None or i % missing else f'width={i} mm\n')}
            for i in range(n)]


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.hosts = []
        self.registry = registry()

    def tearDown(self):
        for host in self.hosts:
            host.close()

    def host(self, arm, adapter, *, launcher=None, **kw):
        kw.setdefault('registry', self.registry if arm != 'A' else None)
        kw.setdefault('seed', 20261024 if arm != 'A' else None)
        kw.setdefault('max_wait', 0.0)
        h = oz_host.ArmHost(arm=arm, backend='fake', workload='mat', experiment_dir=self.dir,
                            launcher=launcher or oz_host.InProcessLauncher(shim.CallableShim(adapter)), op='e',
                            op_text='Extract the length.', model='m-test', effort='low',
                            identity=oz_host.identity_for(ROUTE), allow_experimental=True, **kw)
        self.hosts.append(h)
        return h

    def cold(self, host, wave='cold', producers=4, n=40, tag='', missing=9):
        for p in range(producers):
            host.submit(f'p{p}', f's{host.arm}{wave}{p}', producer_jobs(p, n, missing, tag=tag), wave=wave)
        return host.run_wave(wave)


class SharedBootstrap(Base):
    def test_one_bootstrap_of_16_per_producer_is_shared_by_b_and_c_and_never_repeated(self):
        b_adapter, c_adapter = oz_host.ReplayAdapter(extract, {'e': FIELD}), oz_host.ReplayAdapter(extract, {'e': FIELD})
        b, c = self.host('B', b_adapter), self.host('C', c_adapter)
        # Every answer passes its check here: a bootstrap is ok only after all 64 answers settle (council 3, B3).
        rb, rc = self.cold(b, missing=None), self.cold(c, missing=None)
        boots = b_adapter.calls(bootstrap=True)
        self.assertEqual(len(boots), 1)
        self.assertEqual(len(boots[0]['ids']), 64)
        self.assertEqual(c_adapter.calls(bootstrap=True), [])
        record = b.experiment.bootstrap('fake', 'mat')['record']
        self.assertEqual((record['status'], record['efficiency_valid'], record['owner']), ('ok', True, 'fake-mat-B'))
        self.assertEqual(sorted(len(v) for v in record['assignment'].values()), [16, 16, 16, 16])
        self.assertEqual({d.split('-')[0] for d in record['jobs']}, {'d0', 'd1', 'd2', 'd3'})
        self.assertEqual((rb['bootstrap']['imported'], rc['bootstrap']['imported']), (False, True))
        # Identical admitted artifact in both arms, from the one physical bootstrap.
        rules = [h.store.active(h.learner.key) for h in (b, c)]
        self.assertEqual(rules[0]['ast'], rules[1]['ast'])
        self.assertEqual(rules[0]['ast'], FIELD.encode('utf-8'))
        # C's bootstrap rows come from the record (no call of C's own), charged analytically.
        crows = [r for r in c.collect('p0', 'sCcold0') if r['phase'] == 'bootstrap']
        self.assertEqual(len(crows), 16)
        self.assertTrue(all(r['imported'] for r in crows))
        allocs = c.ledger.allocations('cold')
        imported = [a for a in allocs if a['basis'] == 'imported']
        self.assertEqual((len(imported), {a['kind'] for a in imported}), (64, {'bootstrap'}))
        self.assertAlmostEqual(sum(a['share'] for a in imported), 1.0)
        self.assertEqual((rb['calls']['imported'], rc['calls']['imported']), (0, 1))
        self.assertTrue(rb['reconciliation']['ok'] and rc['reconciliation']['ok'])
        self.assertEqual(rc['tokens']['imported']['tokens'], rb['tokens']['physical']['tokens'] -
                         sum(c_['usage']['input_tokens'] + c_['usage']['output_tokens'] for a in b.ledger.attempts()
                             if a['round'] != 'bootstrap' for c_ in a['calls']))
        # Never re-learned: a second learning wave in both arms makes no bootstrap call.
        for h, adapter in ((b, b_adapter), (c, c_adapter)):
            again = self.cold(h, wave='cold2', tag='x', missing=None)
            self.assertEqual(adapter.calls(bootstrap=True), boots if h is b else [])
            self.assertIsNone(again['bootstrap'])
            self.assertGreater(again['rule_hits'], 0)

    def test_a_failed_bootstrap_is_recorded_once_without_replacement_answers(self):
        bad = oz_host.ReplayAdapter(extract, envelope=lambda reply: '```json\n' + reply + '\n```')
        b = self.host('B', bad)
        report = self.cold(b)
        record = b.experiment.bootstrap('fake', 'mat')['record']
        self.assertEqual((record['status'], record['efficiency_valid'], record['side']['status']),
                         ('failed', False, 'failed'))
        self.assertEqual(len(bad.calls(bootstrap=True)), 1)
        boot_rows = [r for r in b._rows.values() if r['phase'] == 'bootstrap']
        self.assertEqual(len(boot_rows), 64)
        self.assertEqual({r['status'] for r in boot_rows}, {'failed'})  # no replacement answers (A2.1)
        self.assertFalse(report['efficiency_valid'])
        self.assertIn('bootstrap_failed', report['efficiency_invalid'])
        self.assertEqual(report['rule_hits'], 0)
        # C imports the failure; it never bootstraps again.
        c_adapter = oz_host.ReplayAdapter(extract, {'e': FIELD})
        rc = self.cold(self.host('C', c_adapter))
        self.assertEqual(c_adapter.calls(bootstrap=True), [])
        self.assertEqual(rc['rule_hits'], 0)
        self.assertFalse(rc['efficiency_valid'])


class Audits(Base):
    def test_one_wave_of_32_across_four_producers_with_identical_b_and_c_selection(self):
        b, c = self.host('B', oz_host.ReplayAdapter(extract, {'e': FIELD})), \
            self.host('C', oz_host.ReplayAdapter(extract, {'e': FIELD}))
        rb, rc = self.cold(b), self.cold(c)
        self.assertEqual((rb['audits']['selected'], rc['audits']['selected']), (32, 32))
        self.assertEqual(rb['audits']['agree'], 32)
        picked = [sorted(a['dataset_id'] for a in h.store.audits()) for h in (b, c)]
        self.assertEqual(picked[0], picked[1])
        self.assertEqual(len({d.split('-')[0] for d in picked[0]}), 4)  # one wave across every producer
        waves = b.experiment.waves()
        self.assertEqual(len(waves), 1)
        self.assertEqual(sorted(waves[0]['selection']), picked[0])
        self.assertEqual(len(waves[0]['population']), rb['rule_hits'])
        # B pools fallback and audits per producer; C pools across producers.
        for host, single in ((b, True), (c, False)):
            for attempt in host.ledger.attempts('cold'):
                if attempt['round'] == 'r1':
                    producers = {host._items[i]['producer'] for i in attempt['records']}
                    self.assertEqual(len(producers) == 1, single, attempt['records'][:2])
        mixed = [a for a in c.ledger.attempts('cold') if a['round'] == 'r1']
        self.assertEqual(len(mixed), 1)
        self.assertEqual(set(mixed[0]['kinds']), {'fallback', 'audit'})  # one call, mixed membership

    def test_quarantine_makes_the_undelivered_rule_rows_of_the_wave_fall_back(self):
        assignment = rp.bootstrap_assignment({f'p{p}': [j['dataset_id'] for j in producer_jobs(p)] for p in range(4)},
                                             20261024)
        boot = {j['text'][:-1] for p in range(4) for j in producer_jobs(p) if j['dataset_id'] in
                assignment[f'p{p}']}
        adapter = oz_host.ReplayAdapter(lambda t: extract(t) if t in boot else '9.99 mm', {'e': FIELD})
        c = self.host('C', adapter)
        report = self.cold(c)
        self.assertTrue(report['quarantined'])
        self.assertGreater(report['audits']['disagree'], 0)
        self.assertEqual(report['rule_hits'], 0)  # nothing was delivered before the audits
        self.assertEqual(report['quarantine_fallbacks'], report['audits']['population'])
        late = [r for r in c._rows.values() if r.get('fallback_reason') == 'commit_refused:quarantined']
        self.assertEqual(len(late), report['audits']['population'])
        self.assertTrue(all(r['source'] == 'model' for r in late))
        self.assertTrue(any(a['round'] == 'r3' for a in c.ledger.attempts('cold')))
        self.assertEqual(c.store.results(), [])

    def test_immediate_delivery_keeps_already_delivered_rule_rows(self):
        assignment = rp.bootstrap_assignment({f'p{p}': [j['dataset_id'] for j in producer_jobs(p)] for p in range(4)},
                                             20261024)
        boot = {j['text'][:-1] for p in range(4) for j in producer_jobs(p) if j['dataset_id'] in
                assignment[f'p{p}']}
        c = self.host('C', oz_host.ReplayAdapter(lambda t: extract(t) if t in boot else '9.99 mm', {'e': FIELD}),
                      rule_delivery='immediate')
        report = self.cold(c)
        self.assertTrue(report['quarantined'])
        self.assertEqual(report['rule_hits'], report['audits']['population'])
        self.assertEqual(report['quarantine_fallbacks'], 0)

    def test_an_inconclusive_audit_gets_one_reserve_retry(self):
        from oz_reply import Failure
        seen = set()

        def flaky(text):  # the first non-bootstrap sight of a text (its audit) fails; the retry answers
            if text in seen or 'n=3' not in text:
                return extract(text)
            seen.add(text)
            return Failure('unsupported', 'transient')

        adapter = oz_host.ReplayAdapter(flaky, {'e': FIELD})
        c = self.host('C', adapter)
        for p in range(4):
            c.submit(f'p{p}', f's{p}', producer_jobs(p, 40, missing=1000), wave='cold')
        # The bootstrap call answers its own texts first, so mark those texts as seen through the adapter log.
        original = adapter.__call__

        def call(req):
            if shim.INSTRUCTION in req['system']:
                refs = json.loads(req['prompt'])['refs']
                seen.update(refs.values() if isinstance(refs, dict) else refs)
            return original(req)

        call.capabilities = oz_host.CAPS
        c.launcher = oz_host.InProcessLauncher(shim.CallableShim(call))
        report = c.run_wave('cold')
        self.assertEqual(report['audits']['agree'], 32)
        self.assertEqual(report['audits']['inconclusive'], 0)
        retry = [a for a in c.ledger.attempts('cold') if a['round'] == 'r2']
        self.assertEqual(len(retry), 1)
        self.assertEqual(retry[0]['bucket'], 'reserve')
        self.assertEqual(report['evidence'], 'complete')

    def test_pending_audits_block_warm_reuse_and_budget_exhaustion_is_incomplete(self):
        budget = oz_host.Budget(self.dir / 'budget.sqlite', caps={'fake': {'bootstrap': 1}}, global_cap=50)
        self.addCleanup(budget.close)
        c = self.host('C', oz_host.ReplayAdapter(extract, {'e': FIELD}), budget=budget)
        cold = self.cold(c)
        self.assertEqual(cold['audits']['pending'], 32)
        self.assertEqual(cold['evidence'], 'incomplete')
        self.assertIn('budget_exhausted', cold['incomplete'])
        self.assertIn('audits_unresolved', cold['incomplete'])
        self.assertEqual(cold['calls']['refused'], 1)
        self.assertEqual(cold['unresolved'], cold['fallback'])
        self.assertEqual(budget.usage()['total'], 1)
        warm_jobs = {f'p{p}': producer_jobs(p, 10, tag='w') for p in range(4)}
        for p, jobs in warm_jobs.items():
            c.submit(p, 'warm' + p, jobs, wave='warm')
        warm = c.run_wave('warm', learn=False)
        self.assertEqual(warm['rule_hits'], 0)
        self.assertTrue(all(str(r).startswith('audit_unresolved:pending=32') for r in warm['fallback_reasons']))
        self.assertFalse(warm['efficiency_valid'])
        self.assertTrue(any(x.startswith('warm_reuse_blocked') for x in warm['efficiency_invalid']))


class Verification(Base):
    def test_awaiting_verification_is_never_accepted(self):
        runner = Flaky()
        self.registry = registry(runner)
        c = self.host('C', oz_host.ReplayAdapter(extract, {'e': FIELD}))
        self.assertEqual(self.cold(c)['audits']['agree'], 32)
        runner.off = True  # the input-bound check becomes unavailable for the warm wave
        for p in range(4):
            c.submit(f'p{p}', f'w{p}', producer_jobs(p, 8, tag='w'), wave='warm')
        warm = c.run_wave('warm', learn=False)
        self.assertEqual(warm['accepted_by_checks'], 0)
        self.assertEqual(warm['awaiting_verification'], 32)
        self.assertEqual(warm['rule_hits'], 0)
        rows = [r for r in c._rows.values() if r['submission'].startswith('w')]
        self.assertEqual({r['status'] for r in rows}, {'awaiting_verification'})
        self.assertTrue(all(r.get('value_text') is None for r in rows))
        for row in rows:
            s = c.store.settlement(row['id'])
            self.assertEqual((s['state'], s['winner']), ('awaiting_verification', None))
            self.assertIn('awaiting_verification', {e['outcome'] for e in c.store.emissions(row['id'])})


class Physical(Base):
    def test_a_redispatch_after_a_lost_capture_makes_no_second_call(self):
        adapter = oz_host.ReplayAdapter(extract)
        crashed = []

        def after_execute(view, execution):
            if not crashed:
                crashed.append(view['attempt_id'])
                raise RuntimeError('host crashed after the call returned')

        a = self.host('A', adapter, hooks={'after_execute': after_execute})
        a.submit('p0', 's0', producer_jobs(0, 10), wave='w')
        report = a.run_wave('w')
        self.assertEqual(len(adapter.log), 1)
        self.assertEqual(report['accepted_by_checks'], 10)
        self.assertEqual(report['calls']['physical'], 1)
        self.assertEqual(a.ledger.attempt(crashed[0])['state'], 'captured')
        self.assertEqual(a.spool.unresolved(), [])
        # A new host process over the same directories resumes: still one call.
        a.close()
        self.hosts.remove(a)
        again = self.host('A', adapter)
        again.submit('p0', 's0', producer_jobs(0, 10), wave='w')
        self.assertEqual(again.run_wave('w')['accepted_by_checks'], 10)
        self.assertEqual(len(adapter.log), 1)

    def test_budget_exhaustion_leaves_jobs_unresolved_and_the_evidence_incomplete(self):
        budget = oz_host.Budget(self.dir / 'budget.sqlite', caps={'fake': {'A': 1}}, global_cap=50)
        self.addCleanup(budget.close)
        adapter = oz_host.ReplayAdapter(extract)
        a = self.host('A', adapter, budget=budget)
        a.submit('p0', 's0', producer_jobs(0, 100), wave='w')
        report = a.run_wave('w')
        self.assertEqual(len(adapter.log), 1)
        self.assertEqual((report['accepted_by_checks'], report['unresolved']), (64, 36))
        self.assertEqual(report['evidence'], 'incomplete')
        self.assertEqual(report['calls']['refused'], 1)
        with self.assertRaisesRegex(Error, 'frozen'):
            oz_host.Budget(self.dir / 'budget.sqlite', caps={'fake': {'A': 2}}, global_cap=50)

    def test_a_launch_gate_refusal_launches_nothing_and_reserves_nothing(self):
        budget = oz_host.Budget(self.dir / 'budget.sqlite', caps={'fake': {'A': 5}}, global_cap=50)
        self.addCleanup(budget.close)
        adapter = oz_host.ReplayAdapter(extract)
        a = self.host('A', adapter, budget=budget, hooks={'launch_gate': lambda view: 'quota_projected_over_55pct'})
        a.submit('p0', 's0', producer_jobs(0, 5), wave='w')
        report = a.run_wave('w')
        self.assertEqual((len(adapter.log), budget.usage()['total'], report['unresolved']), (0, 0, 5))
        self.assertIn('quota_projected_over_55pct', report['incomplete'])

    def test_ledger_reconciliation_detects_a_bad_allocation(self):
        c = self.host('C', oz_host.ReplayAdapter(extract, {'e': FIELD}))
        report = self.cold(c)
        self.assertTrue(report['reconciliation']['ok'])
        call = next(a for a in c.ledger.allocations('cold') if a['basis'] == 'physical')
        c.ledger.allocate([dict(call, job='jextra', share=0.5)])
        rec = c.reconcile('cold')
        self.assertFalse(rec['ok'])
        self.assertTrue(any('shares sum' in p for p in rec['problems']))
        with self.assertRaises(Exception):
            c.ledger.db.execute('DELETE FROM allocations')

    def test_resume_of_a_finished_wave_makes_no_call_and_returns_the_same_rows(self):
        adapter = oz_host.ReplayAdapter(extract, {'e': FIELD})
        c = self.host('C', adapter)
        first = self.cold(c)
        rows = {k: dict(v) for k, v in c._rows.items()}
        calls = len(adapter.log)
        c.close()
        self.hosts.remove(c)
        c2 = self.host('C', adapter)
        second = c2.run_wave('cold')
        self.assertEqual(len(adapter.log), calls)
        self.assertEqual(second['accepted_by_checks'], first['accepted_by_checks'])
        strip = lambda r: {k: v for k, v in r.items() if k not in ('delivered_at', 'queue_s', 'resumed', 'checks',
                                                                   'call_kind', 'attempt_id', 'request_id',
                                                                   'fallback_reason', 'imported', 'phase')}
        self.assertEqual({k: strip(v) for k, v in c2._rows.items()}, {k: strip(v) for k, v in rows.items()})


REAL = r'''
import json, os, re, sys
log = os.environ.get('ENV_LOG')
if '--identity' in sys.argv:
    print(json.dumps({'backend': 'fake', 'model': 'm-test', 'effort': 'low', 'cli_version': '1', 'flags': []}))
    raise SystemExit
req = json.loads(sys.stdin.buffer.read().decode('utf-8'))
with open(log, 'a', encoding='utf-8') as f:
    f.write(json.dumps({'ids': req['ids'], 'env': {k: v for k, v in os.environ.items() if k.startswith('OZ_')},
                        'bootstrap': 'oz-bootstrap/1 JSON envelope' in req['system']}) + '\n')
body = json.loads(req['prompt'])
lines = ['OZ/1g']
for block in body['jobs']:
    for row in block[1:]:
        m = re.search(r'length=([^;]*)', body['refs'][row[1]])
        lines.append(json.dumps({row[0]: m.group(1) if m else 'unknown'}))
reply = '\n'.join(lines)
if 'oz-bootstrap/1 JSON envelope' in req['system']:
    reply = '{"host":"oz-bootstrap/1","answers":' + json.dumps(reply) + ',"rules":{"e":' + \
        '{"lang": "oz-rule/1",  "expr": ["field", "length"]}' + '}}'
sys.stdout.write(json.dumps({'reply': reply, 'usage': {'input_tokens': 100, 'output_tokens': 10}}))
'''


class ChildProcesses(Base):
    def test_each_call_is_a_child_with_its_own_env_and_only_the_bootstrap_child_is_enabled(self):
        real = self.dir / 'real.py'
        real.write_text(REAL, encoding='utf-8')
        adapter = self.dir / 'adapter.json'
        adapter.write_text(json.dumps({'argv': [sys.executable, str(REPO / 'examples' / 'bootstrap_shim.py'),
                                                str(real)], **oz_host.CAPS}), encoding='utf-8')
        log = self.dir / 'env.jsonl'
        before = dict(os.environ)
        base = dict(os.environ, ENV_LOG=str(log), OZ_BOOTSTRAP_ATTEMPT='leak', OZ_BOOTSTRAP_DIR=str(self.dir))
        c = self.host('C', None, launcher=oz_host.ChildLauncher(adapter), producers_expected=1,
                      bootstrap_per_producer=2, base_env=base)
        c.submit('p0', 's0', producer_jobs(0, 7, missing=100), wave='w')
        report = c.run_wave('w')
        self.assertEqual(dict(os.environ), before)  # the host never touched its own environment
        calls = [json.loads(x) for x in log.read_text(encoding='utf-8').splitlines()]
        self.assertEqual([x['bootstrap'] for x in calls], [True, False])
        boot, audit = calls
        self.assertEqual((boot['env']['OZ_MODEL'], boot['env']['OZ_EFFORT']), ('m-test', 'low'))
        # The shim was enabled in exactly the bootstrap child, under the host's attempt id, never the inherited one.
        attempts = {a['round']: a['attempt_id'] for a in c.ledger.attempts('w')}
        side = sorted(f.name for f in c.side_dir.iterdir())
        boot_id = attempts['bootstrap']
        self.assertEqual(side, sorted(boot_id + s for s in ('.capture.json', '.claim', '.config.json', '.json')))
        self.assertFalse(list(self.dir.glob('leak*')))
        self.assertFalse({'OZ_BOOTSTRAP_ATTEMPT', 'OZ_BOOTSTRAP_DIR'} & set(audit['env']))
        self.assertEqual(report['rule_hits'] + report['abstains'], 5)
        self.assertEqual(report['audits']['agree'], report['rule_hits'])
        self.assertEqual(c.store.active(c.learner.key)['ast'], FIELD.encode('utf-8'))
        for attempt in c.ledger.attempts('w'):
            evidence = Path(attempt['evidence_dir'])
            self.assertTrue((evidence / 'stdout.bin').exists() and (evidence / 'exit.json').exists())
            self.assertEqual(attempt['exit_code'], 0)

    def test_child_env_strips_inherited_bootstrap_variables(self):
        env = oz_host.child_env(model='m', effort='e', base={'OZ_BOOTSTRAP_DIR': 'x', 'OZ_BOOTSTRAP_ATTEMPT': 'y',
                                                              'OZ_ENVELOPE_PATH': 'z', 'OZ_CODEX_TIMEOUT': '9',
                                                              'PATH': 'p'})
        self.assertEqual(env, {'OZ_CODEX_TIMEOUT': '9', 'PATH': 'p', 'OZ_MODEL': 'm', 'OZ_EFFORT': 'e',
                               'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'})
        extra = oz_host.child_env(model='m', effort='e', base={}, extra={'OZ_BOOTSTRAP_ATTEMPT': 'a1'})
        self.assertEqual(extra['OZ_BOOTSTRAP_ATTEMPT'], 'a1')


COUNT = '{"lang":"oz-rule/1","expr":["field","n"]}'


def two_op_registry():
    """Operations e (the length) and n (the count), each with its own 64 cases, both quoted_span checked."""
    checks = {'span': {'name': 'quoted_span', 'version': 1, 'kind': 'consumer', 'params': {}}}
    ops = {}
    for op, value in (('e', lambda i: f'{i}.{i % 100:02d} mm'), ('n', lambda i: str(1000 + i))):
        cases = [{'id': f'{op}{i}', 'text': f'length={i}.{i % 100:02d} mm; n={1000 + i}',
                  'partition': 'representative' if i < 48 else 'challenge',
                  'expected': {'type': 'string', 'value': value(i)}} for i in range(64)]
        ops[op] = {'contract': {'name': f'extract_{op}', 'deterministic': True}, 'checks': ['span'], 'permissions': {},
                   'input_policy': dict(POLICY), 'route': dict(ROUTE), 'cases': cases, 'provenance': dict(PROV)}
    return reg.Registry(reg.build_manifest(ops, checks, 'owner@example'))


class SeveralOperations(Base):
    """One host runs a workload of several operations: one shared bootstrap with a rule per operation, mixed batches,
    and one min(32, covered) audit selection over every operation of the wave."""

    def jobs(self, p, n=40):
        out, answers = [], {}
        for i in range(n):
            op = 'e' if i % 2 else 'n'
            text = f'length={p}.{i:02d} mm; n={2000 + 100 * p + i}'
            out.append({'key': f'k{i}', 'op': op, 'dataset_id': f'd{p}-{i}', 'text': text + '\n'})
            answers[(text, op)] = f'{p}.{i:02d} mm' if op == 'e' else str(2000 + 100 * p + i)
        return out, answers

    def host2(self, arm, adapter):
        h = oz_host.ArmHost(arm=arm, backend='fake', workload='two', experiment_dir=self.dir,
                            launcher=oz_host.InProcessLauncher(shim.CallableShim(adapter)),
                            op={'e': 'Extract the length.', 'n': 'Extract n.'}, op_text=None, model='m-test',
                            effort='low', identity=oz_host.identity_for(ROUTE), registry=two_op_registry(),
                            seed=20261024 if arm != 'A' else None, allow_experimental=True, max_wait=0.0)
        self.hosts.append(h)
        return h

    def test_one_bootstrap_rules_per_operation_mixed_batches_and_one_audit_wave(self):
        table = {}
        producers = {}
        for p in range(4):
            producers[f'p{p}'], answers = self.jobs(p)
            table.update(answers)
        seen_ops = []

        class Answer:
            def __init__(self):
                self.by_text = {}
                for (text, op), value in table.items():
                    self.by_text.setdefault(text, value)

            def __call__(self, text):
                return self.by_text[text]

        # one text per job, so the replay answer is a function of the text
        self.assertEqual(len({t for t, _ in table}), len(table))
        adapters = {arm: oz_host.ReplayAdapter(Answer(), {'e': FIELD, 'n': COUNT}) for arm in 'ABC'}
        reports = {}
        for arm in 'BCA':
            h = self.host2(arm, adapters[arm])
            for p, jobs in producers.items():
                h.submit(p, f's{arm}{p}', jobs, wave='cold')
            reports[arm] = h.run_wave('cold')
            for a in h.ledger.attempts('cold'):
                seen_ops.append((arm, a['round'], sorted({h._items[i]['job']['op'] for i in a['records']})))
        boots = adapters['B'].calls(bootstrap=True)
        self.assertEqual((len(boots), adapters['C'].calls(bootstrap=True)), (1, []))
        config = json.loads(next((self.dir / 'bootstrap' / 'fake-two' / 'side').glob('*.config.json')).read_text())
        self.assertEqual((config['ops'], sorted(config['contracts'])), (['e', 'n'], ['e', 'n']))
        for arm in 'BC':
            h = next(x for x in self.hosts if x.arm == arm)
            rules = {o: h.store.active(lr.key) for o, lr in h.learners.items()}
            self.assertEqual({o: r['ast'] for o, r in rules.items()},
                             {'e': FIELD.encode('utf-8'), 'n': COUNT.encode('utf-8')})
            self.assertEqual(reports[arm]['audits']['selected'], 32)
            self.assertEqual(reports[arm]['rule_hits'], 160 - 64)
            self.assertEqual(reports[arm]['accepted_by_checks'], 160)
            self.assertTrue(reports[arm]['reconciliation']['ok'])
        picked = [sorted(a['dataset_id'] for a in h.store.audits()) for h in self.hosts if h.arm in 'BC']
        self.assertEqual(picked[0], picked[1])
        by_op = {}
        for d in picked[0]:
            by_op[int(d.split('-')[1]) % 2] = by_op.get(int(d.split('-')[1]) % 2, 0) + 1
        self.assertEqual(sorted(by_op), [0, 1])  # one selection across both operations
        self.assertEqual(sum(by_op.values()), 32)
        # A pools the two operations into the same 64-record calls.
        a_calls = [ops for arm, rnd, ops in seen_ops if arm == 'A']
        self.assertEqual(len(a_calls), 3)
        self.assertIn(['e', 'n'], a_calls)
        self.assertEqual(reports['A']['accepted_by_checks'], 160)
        a_rows = [r for h in self.hosts if h.arm == 'A' for p in producers for r in h.collect(p, f'sA{p}')]
        self.assertEqual({r['op'] for r in a_rows}, {'e', 'n'})
        for r in a_rows:
            text = next(j['text'] for j in producers[r['producer']] if j['key'] == r['key'])
            self.assertEqual(json.loads(r['value_text']), table[(text[:-1], r['op'])])

    def test_op_map_validation_and_a_foreign_operation_is_refused(self):
        with self.assertRaises(Error):
            oz_host.ArmHost(arm='A', backend='fake', workload='two', experiment_dir=self.dir,
                            launcher=oz_host.InProcessLauncher(lambda r: None), op={'e': 'x'}, op_text='y',
                            model='m', effort='low', identity=oz_host.identity_for(ROUTE))
        h = self.host2('A', oz_host.ReplayAdapter(lambda t: 'x'))
        with self.assertRaises(Error):
            h.submit('p0', 's1', [{'key': 'k', 'op': 'z', 'text': 'a', 'dataset_id': 'd'}], wave='w')


def matrix(experiment_dir=None, caps=None, global_cap=50):
    jobs = {f'p{p}': producer_jobs(p, 64) for p in range(4)}
    warm = {f'p{p}': producer_jobs(p, 64, tag='w') for p in range(4)}
    return {'seed': 20261024, 'experiment_dir': experiment_dir, 'global_cap': global_cap,
            'caps': caps or {'codex': {'telemetry': 1, 'bootstrap': 2, 'A': 12, 'B': 8, 'C': 7, 'reserve': 7}},
            'max_wait': 0.0,
            'cells': [{'backend': 'codex', 'workload': 'materials', 'registry': registry(), 'op': 'e',
                       'op_text': 'Extract the length.', 'model': 'm-test', 'effort': 'low', 'route': ROUTE,
                       'answer': extract, 'rules': {'e': FIELD}, 'arms': ['A', 'B', 'C'],
                       'waves': [{'name': 'cold', 'learn': True, 'producers': jobs},
                                 {'name': 'warm', 'learn': False, 'arms': ['A', 'C'], 'producers': warm}]}]}


USAGE = {'codex': {'call': [{'input_tokens': 24000, 'cached_input_tokens': 20000, 'output_tokens': 900,
                             'reasoning_output_tokens': 300, 'elapsed_seconds': 40.0}],
                   'bootstrap': [{'input_tokens': 31000, 'cached_input_tokens': 20000, 'output_tokens': 2500,
                                  'reasoning_output_tokens': 900, 'elapsed_seconds': 90.0}]}}


class DryRun(unittest.TestCase):
    def test_the_matrix_runs_end_to_end_with_zero_external_calls(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            out = oz_host.dry_run(matrix(d), USAGE)
        self.assertEqual(out['external_calls'], 0)
        self.assertTrue(out['fits'])
        self.assertTrue(out['reconciliation']['ok'], out['reconciliation'])
        [cell] = out['cells']
        cold, warm = cell['waves']
        arms = cold['arms']
        self.assertEqual(sorted(arms), ['A', 'B', 'C'])
        self.assertEqual(arms['A']['calls']['physical'], 4)  # 256 jobs in pooled 64-record batches
        boots = [arms[a]['bootstrap'] for a in 'BC']
        self.assertEqual(sorted(b['imported'] for b in boots), [False, True])
        self.assertEqual(boots[0]['attempt_id'], boots[1]['attempt_id'])
        self.assertEqual(arms['B']['audits']['selected'], 32)
        self.assertEqual(arms['B']['audits'], arms['C']['audits'])
        # The bootstrap is charged in full to both B and C; physically once.
        for a in 'BC':
            self.assertEqual(arms[a]['calls']['by_kind']['bootstrap']['jobs'], 64)
            self.assertEqual(arms[a]['tokens']['charged']['usage'], 'complete')
        self.assertEqual(out['reconciliation']['imported_calls'], 1)
        self.assertEqual(out['physical_calls'], out['replayed_calls'])
        self.assertLess(arms['C']['calls']['physical'], arms['B']['calls']['physical'])
        self.assertGreater(arms['C']['projected_makespan_seconds'], 90.0)
        self.assertEqual(sorted(warm['arms']), ['A', 'C'])
        self.assertEqual(warm['arms']['C']['bootstrap'], None)
        self.assertGreater(warm['arms']['C']['rule_hits'], 0)
        self.assertEqual(out['budget']['total'], out['physical_calls'])
        self.assertEqual(out['evidence'], 'complete')
        self.assertTrue(all(r['correctness'].startswith('not assessed') for r in arms.values()))

    def test_a_matrix_that_cannot_fit_reports_incomplete_evidence(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            out = oz_host.dry_run(matrix(d, caps={'codex': {'bootstrap': 1, 'A': 4, 'B': 1, 'C': 1}}), USAGE)
        self.assertFalse(out['fits'])
        self.assertEqual(out['evidence'], 'incomplete')
        self.assertLessEqual(out['budget']['total'], 7)


if __name__ == '__main__':
    unittest.main()
