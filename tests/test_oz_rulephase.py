"""oz_rulephase: rule store, exact-bytes admission, the authoritative settlement record (generation fencing, one
winner, identity on resume, history), awaiting_verification, D1 adoption, audit selection and verdicts, and the
shared experiment store (bootstrap assignment and record, evaluation-wave audit selections). The shim itself is
covered by tests/test_bootstrap_shim.py. Fake data only, no model calls."""
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from oz import Error  # noqa: E402
import oz_registry as reg  # noqa: E402
import oz_route  # noqa: E402
import oz_rule  # noqa: E402
import oz_rulephase as rp  # noqa: E402

ROUTE = {'adapter_hash': 'a' * 64, 'backend': 'fake', 'model': 'm-test', 'effort': 'low', 'cli_version': 'fake-1',
         'environment_hash': 'b' * 64}
WORKER = oz_route.worker_hash(ROUTE)
POLICY = {'version': 'oz-input/1', 'terminal_newline': 'strip_one', 'text_ref': 0}
PROVENANCE = {'labeler': 'human-1', 'method': 'hand labeled', 'independent': True, 'hidden_from_synthesis': True,
              'synthesis_agents': ['astra']}
SPAN = {'name': 'quoted_span', 'version': 1, 'kind': 'consumer', 'params': {}}
ONE_OF = {'name': 'one_of', 'version': 1, 'kind': 'consumer', 'params': {'values': ['yes', 'no']}}
E_CONTRACT = {'name': 'extract_length', 'deterministic': True}
FIELD = json.dumps({'lang': 'oz-rule/1', 'expr': ['field', 'length']}, separators=(',', ':'))
SPACED = '{ "lang" : "oz-rule/1",\n  "expr": ["field",   "length"] }'
CONST = json.dumps({'lang': 'oz-rule/1', 'expr': ['s', '1.00 mm']}, separators=(',', ':'))


class Flaky(reg.LocalChecks):
    off = False

    def run(self, name, version, params, value, text):
        if self.off and name == 'quoted_span':
            raise reg.CheckUnavailable('down')
        return reg.LocalChecks.run(self, name, version, params, value, text)


def length_cases():
    return [{'id': f'c{i}', 'text': f'length={i}.{i % 100:02d} mm; n=3',
             'partition': 'representative' if i < 48 else 'challenge',
             'expected': {'type': 'string', 'value': f'{i}.{i % 100:02d} mm'}} for i in range(64)]


def boolq_cases():
    return [{'id': f'q{i}', 'text': f'passage {i}', 'partition': 'representative' if i < 48 else 'challenge',
             'expected': {'type': 'string', 'value': 'yes' if i % 2 else 'no'}} for i in range(64)]


def operation(contract=E_CONTRACT, checks=('span',), cases=None):
    return {'contract': dict(contract), 'checks': list(checks), 'permissions': {}, 'input_policy': dict(POLICY),
            'route': dict(ROUTE), 'cases': cases or length_cases(), 'provenance': dict(PROVENANCE)}


def registry(runner=None, **ops):
    ops = ops or {'e': operation()}
    return reg.Registry(reg.build_manifest(ops, {'span': SPAN, 'one_of': ONE_OF}, 'owner@example', runner),
                        runner=runner)


def entry(data: bytes) -> dict:
    return {'ast_b64': base64.b64encode(data).decode('ascii'), 'ast_sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data)}


def side_ok(ast, op='e', **extra):
    rule = {'none': True} if ast is None else entry(ast.encode('utf-8') if isinstance(ast, str) else ast)
    return dict({'schema': rp.SIDE_SCHEMA, 'attempt_id': 'a1', 'status': 'ok', 'envelope_ok': True,
                 'rules': {op: rule}}, **extra)


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.store = rp.RuleStore(self.dir / 'rules.sqlite')
        self.addCleanup(self.store.close)

    def learner(self, reg_=None, op='e', pinned=()):
        return rp.Learner(self.store, reg_ or registry(), op, worker_hash=WORKER, map_contract='c' * 64,
                          map_input_policy='strip-one-terminal-newline/1', map_pinned=pinned)


class Admission(Base):
    def test_exact_ast_bytes_are_admitted_stored_and_immutable(self):
        learner = self.learner()
        rid = learner.admit_side(side_ok(SPACED), source='r:1:e', provenance={'call_id': 'c1'})
        rule = self.store.rule(rid)
        self.assertEqual(rule['status'], 'admitted')
        self.assertEqual(rule['ast'], SPACED.encode('utf-8'))  # whitespace kept: never re-serialized
        self.assertEqual(rule['ast_sha256'], hashlib.sha256(SPACED.encode()).hexdigest())
        self.assertEqual(rule['admission']['ast_hash'], rule['ast_sha256'])
        self.assertEqual(rule['admission']['coverage'], 64)
        self.assertEqual(rule['bindings']['interpreter'], rp.INTERPRETER)
        self.assertEqual(self.store.active(learner.key)['id'], rid)
        self.assertEqual(learner.admit_side(side_ok(SPACED), source='r:1:e', provenance={}), rid)
        with self.assertRaisesRegex(Error, 'different candidate'):
            learner.admit_side(side_ok(FIELD), source='r:1:e', provenance={})
        for sql in ("UPDATE rules SET ast=x'00'", "UPDATE rules SET bindings='{}'", "UPDATE rules SET admission='{}'",
                    'DELETE FROM rules'):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                self.store.db.execute(sql)
        self.assertTrue(self.store.quarantine(rid, {'why': 'test'}))
        for sql in ("UPDATE rules SET status='admitted'", "UPDATE rules SET quarantine='{}'"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                self.store.db.execute(sql)
        self.assertIsNone(self.store.active(learner.key))

    def test_bad_side_files_and_candidates_are_rejected(self):
        learner = self.learner()
        big = ('{"lang":"oz-rule/1","expr":["s","' + 'x' * 2100 + '"]}').encode()
        tampered = side_ok(FIELD)
        tampered['rules']['e']['ast_sha256'] = '0' * 64
        short = side_ok(FIELD)
        short['rules']['e']['bytes'] -= 1
        b64 = side_ok(FIELD)
        b64['rules']['e']['ast_b64'] = '!!!'
        bad_utf8 = b'{"lang":"oz-rule/1","expr":["s","\xff"]}'
        cases = [(side_ok(CONST), 'covered_errors'), (side_ok(None), 'none_proposed'),
                 ({'schema': rp.SIDE_SCHEMA, 'status': 'failed', 'envelope_ok': False, 'rules': {}},
                  'bootstrap_failed'),
                 (None, 'bootstrap_missing'), (tampered, 'side_file_hash_mismatch'), (short, 'ast_length_mismatch'),
                 (b64, 'ast_b64_invalid'), (side_ok(big), 'ast_too_large'), (side_ok(bad_utf8), 'ast_invalid_unicode'),
                 ({'schema': 'oz.bootstrap.side/1', 'status': 'ok', 'rules': {}}, 'side_file_schema'),
                 (side_ok(FIELD, op='other'), 'side_file_malformed')]
        for i, (side, reason) in enumerate(cases):
            with self.subTest(reason=reason):
                rule = self.store.rule(learner.admit_side(side, source=f's{i}', provenance={}))
                self.assertEqual(rule['status'], 'rejected')
                self.assertIn(reason, rule['admission']['reasons'])
        self.assertIsNone(self.store.active(learner.key))

    def test_boolq_and_one_of_only_operations_are_ineligible_and_never_admitted(self):
        r = registry(q=operation({'name': 'boolq', 'deterministic': True}, ('one_of',), boolq_cases()))
        learner = self.learner(r, 'q')
        self.assertFalse(learner.eligible)
        self.assertEqual(learner.bootstrap_config(), {'schema': 'oz.bootstrap.config/2', 'ops': ['q'],
                                                      'contracts': {'q': {'name': 'boolq', 'deterministic': True}},
                                                      'eligibility': {'q': False}})
        ast = json.dumps({'lang': 'oz-rule/1', 'expr': ['s', 'yes']}, separators=(',', ':'))
        rule = self.store.rule(learner.admit_side(side_ok(ast, 'q'), source='b:q', provenance={}))
        self.assertEqual(rule['status'], 'rejected')
        self.assertIn('ineligible', rule['admission']['reasons'])

    def test_registry_route_must_be_the_map_worker_identity(self):
        with self.assertRaisesRegex(Error, 'binding_mismatch'):
            rp.Learner(self.store, registry(), 'e', worker_hash='f' * 64, map_contract='c' * 64,
                       map_input_policy='x')
        with self.assertRaisesRegex(Error, 'not in the registry'):
            self.learner(op='nope')


class Settlement(Base):
    def setUp(self):
        Base.setUp(self)
        self.learn = self.learner(pinned=[{'check': 'json_type', 'version': 1, 'types': ['string']}])
        self.rule = self.store.rule(self.learn.admit_side(side_ok(FIELD), source='s', provenance={}))
        self.owner = {'producer': 'p', 'submission': 's', 'operation': 'e', 'path': 'refs/a.txt'}

    def open(self, job='j1'):
        self.store.open_job(job, payload_sha256='p' * 64, bindings_sha256='b' * 64, required=self.learn.required)
        return self.store.claim(job)

    def attempt(self, text, job='j1', generation=None, **kw):
        generation = self.open(job) if generation is None else generation
        return self.learn.attempt(self.rule, job=job, text=text, resolved_sha256=rp.sha256_text(text),
                                  op_text='Extract length.', owner=self.owner, generation=generation,
                                  payload_sha256='p' * 64, bindings_sha256='b' * 64, **kw)

    def model(self, job, value_text, generation, text='length=1.00 mm', **kw):
        return self.store.settle_model(job, generation=generation, payload_sha256='p' * 64, bindings_sha256='b' * 64,
                                       value_text=value_text, checks=self.learn.evidence(value_text, text, 'x'), **kw)

    def test_required_checks_cover_registry_and_map_checks(self):
        self.assertEqual(self.learn.required, ['map:0:json_type@1', 'registry:span:quoted_span@1'])

    def test_a_rule_settlement_is_final_with_one_winner_and_history(self):
        got = self.attempt('length=12.50 mm; n=3')
        self.assertEqual(got['decision'], 'rule')
        self.assertEqual((got['row']['value'], got['row']['provenance']['check']), ('"12.50 mm"', 'rule_provenance/1'))
        s = self.store.settlement('j1')
        self.assertEqual((s['state'], s['winner']), ('settled', 'rule'))
        # A later model answer for the same job loses and is kept as history.
        self.assertIsNone(self.store.claim('j1'))
        state, reason = self.model('j1', '"12.50 mm"', 1, text='length=12.50 mm; n=3')
        self.assertEqual((state, reason), ('refused', 'already_settled:rule'))
        self.assertEqual([e['outcome'] for e in self.store.emissions('j1')], ['settled', 'refused'])
        for sql in ("UPDATE settlements SET winner='model'", 'DELETE FROM settlements', "UPDATE emissions SET value='x'",
                    'DELETE FROM emissions', 'DELETE FROM results'):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                self.store.db.execute(sql)

    def test_model_first_then_the_rule_commit_is_refused(self):
        generation = self.open()
        self.assertEqual(self.model('j1', '"1.00 mm"', generation)[0], 'settled')
        got = self.attempt('length=1.00 mm', generation=generation)
        self.assertEqual(got, {'decision': 'fallback', 'reason': 'commit_refused:already_settled:model'})
        self.assertIsNone(self.store.result('j1'))

    def test_a_stale_generation_cannot_settle(self):
        old = self.open()
        newer = self.store.claim('j1')
        self.assertEqual(newer, old + 1)
        self.assertEqual(self.model('j1', '"1.00 mm"', old), ('refused', 'stale_generation'))
        self.assertEqual(self.model('j1', '"1.00 mm"', newer)[0], 'settled')

    def test_identity_is_validated_on_resume(self):
        self.open()
        with self.assertRaisesRegex(Error, 'identity'):
            self.store.open_job('j1', payload_sha256='q' * 64, bindings_sha256='b' * 64, required=self.learn.required)
        with self.assertRaisesRegex(Error, 'identity'):
            self.store.open_job('j1', payload_sha256='p' * 64, bindings_sha256='b' * 64, required=[])
        self.assertEqual(self.store.open_job('j1', payload_sha256='p' * 64, bindings_sha256='b' * 64,
                                             required=self.learn.required)['state'], 'open')
        state = self.store.settle_model('j1', generation=1, payload_sha256='x' * 64, bindings_sha256='b' * 64,
                                        value_text='"1.00 mm"', checks=[])
        self.assertEqual(state, ('refused', 'identity_mismatch'))

    def test_two_hosts_racing_rule_against_model_get_exactly_one_winner(self):
        for n in range(6):
            job = f'race{n}'
            generation = self.open(job)
            other = rp.RuleStore(self.dir / 'rules.sqlite')
            self.addCleanup(other.close)
            barrier = threading.Barrier(2)
            text = 'length=3.00 mm'
            first = oz_rule.evaluate(self.rule['ast'], text)
            checks = self.learn.evidence('"3.00 mm"', text, 'x')
            out = {}

            def rule_side():
                barrier.wait()
                out['rule'] = self.store.adopt_rule(
                    rule=self.rule, binding_key=self.learn.key, job=job, text=text,
                    resolved_sha256=rp.sha256_text(text), first=first, checks=checks, owner=self.owner,
                    generation=generation, payload_sha256='p' * 64, bindings_sha256='b' * 64)[0]

            def model_side():
                barrier.wait()
                out['model'] = other.settle_model(job, generation=generation, payload_sha256='p' * 64,
                                                  bindings_sha256='b' * 64, value_text='"3.00 mm"',
                                                  checks=checks)[0]

            threads = [threading.Thread(target=rule_side), threading.Thread(target=model_side)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(sorted(out.values()), sorted(['adopted', 'refused']) if out['rule'] == 'adopted'
                             else ['refused', 'settled'], out)
            s = self.store.settlement(job)
            self.assertEqual(s['state'], 'settled')
            winners = [e for e in self.store.emissions(job) if e['outcome'] == 'settled']
            self.assertEqual(len(winners), 1)
            self.assertEqual(winners[0]['source'], s['winner'])

    def test_failing_and_abstaining_values_fall_back(self):
        self.assertEqual(self.attempt('width=3 mm', job='j2')['reason'], 'abstain:missing')
        r = self.learner(pinned=[{'check': 'json_type', 'version': 1, 'types': ['array']}])
        rule = self.store.rule(r.admit_side(side_ok(FIELD), source='s2', provenance={}))
        self.store.open_job('j3', payload_sha256='p' * 64, bindings_sha256='b' * 64, required=r.required)
        got = r.attempt(rule, job='j3', text='length=1.00 mm', resolved_sha256=rp.sha256_text('length=1.00 mm'),
                        op_text='x', owner=self.owner, generation=self.store.claim('j3'), payload_sha256='p' * 64,
                        bindings_sha256='b' * 64)
        self.assertEqual(got['reason'], 'check_failed:map:0:json_type@1')

    def test_provenance_recheck_failure_blocks_the_commit(self):
        calls = []

        def drifting(ast, text):
            calls.append(text)
            result = oz_rule.evaluate(ast, text)
            return result if len(calls) == 1 else dict(result, value='99.00 mm')

        got = self.attempt('length=12.50 mm', evaluate=drifting)
        self.assertEqual(got, {'decision': 'fallback', 'reason': 'commit_refused:provenance_failed'})
        self.assertIsNone(self.store.result('j1'))
        self.assertEqual(self.store.settlement('j1')['state'], 'open')

    def test_quarantine_binding_and_input_are_rechecked_in_the_commit(self):
        def quarantine(db):  # another process quarantines the rule just before this commit
            db.execute("UPDATE rules SET status='quarantined' WHERE id=?", (self.rule['id'],))

        text = 'length=1.00 mm'
        generation = self.open('j9')
        first = oz_rule.evaluate(FIELD.encode(), text)
        common = dict(binding_key=self.learn.key, job='j9', text=text, first=first, owner=self.owner,
                      checks=self.learn.evidence('"1.00 mm"', text, 'x'), generation=generation,
                      payload_sha256='p' * 64, bindings_sha256='b' * 64)
        self.assertEqual(self.store.adopt_rule(rule=dict(self.rule, binding_key='0' * 64),
                                               resolved_sha256=rp.sha256_text(text), **common),
                         ('refused', 'binding_changed'))
        self.assertEqual(self.store.adopt_rule(rule=self.rule, resolved_sha256='0' * 64, **common),
                         ('refused', 'input_changed'))
        staged = self.attempt(text, stage=True)
        self.assertEqual(staged['decision'], 'staged')
        self.assertIsNone(self.store.result('j1'))  # staged is not delivered
        got = self.learn.commit(staged, before_commit=quarantine)
        self.assertEqual(got['reason'], 'commit_refused:quarantined')
        self.assertEqual(self.store.settlement('j1')['state'], 'open')  # free to fall back to the model


class AwaitingVerification(Base):
    def setUp(self):
        Base.setUp(self)
        self.runner = Flaky()
        self.learn = self.learner(registry(self.runner))
        self.rule = self.store.rule(self.learn.admit_side(side_ok(FIELD), source='s', provenance={}))
        self.owner = {'producer': 'p', 'submission': 's', 'operation': 'e', 'path': 'a'}
        self.store.open_job('j1', payload_sha256='p' * 64, bindings_sha256='b' * 64, required=self.learn.required)

    def test_an_unavailable_check_awaits_verification_and_is_never_accepted(self):
        self.runner.off = True
        text = 'length=2.00 mm'
        generation = self.store.claim('j1')
        got = self.learn.attempt(self.rule, job='j1', text=text, resolved_sha256=rp.sha256_text(text), op_text='x',
                                 owner=self.owner, generation=generation, payload_sha256='p' * 64,
                                 bindings_sha256='b' * 64)
        self.assertEqual(got['decision'], 'awaiting_verification')
        self.assertEqual(self.store.settlement('j1')['state'], 'awaiting_verification')
        # The model fallback answers, but its check is unavailable too: still not accepted.
        generation = self.store.claim('j1')
        checks = self.learn.evidence('"2.00 mm"', text, 'x')
        self.assertEqual(self.store.settle_model('j1', generation=generation, payload_sha256='p' * 64,
                                                 bindings_sha256='b' * 64, value_text='"2.00 mm"', checks=checks)[0],
                         'awaiting_verification')
        self.assertIsNone(self.store.settlement('j1')['winner'])
        # Once the check is available again a passing answer settles.
        self.runner.off = False
        checks = self.learn.evidence('"2.00 mm"', text, 'x')
        self.assertEqual(self.store.settle_model('j1', generation=generation, payload_sha256='p' * 64,
                                                 bindings_sha256='b' * 64, value_text='"2.00 mm"', checks=checks)[0],
                         'settled')

    def test_the_boundary_rejects_missing_or_unknown_evidence_itself(self):
        text = 'length=2.00 mm'
        first = oz_rule.evaluate(self.rule['ast'], text)
        common = dict(rule=self.rule, binding_key=self.learn.key, job='j1', text=text,
                      resolved_sha256=rp.sha256_text(text), first=first, owner=self.owner,
                      generation=self.store.claim('j1'), payload_sha256='p' * 64, bindings_sha256='b' * 64)
        for checks, why in (([], 'evidence_missing'),
                            ([{'id': 'registry:span:quoted_span@1', 'verdict': 'pass'},
                              {'id': 'map:9:x@1', 'verdict': 'pass'}], 'evidence_unknown'),
                            ([{'id': 'registry:span:quoted_span@1', 'verdict': 'inconclusive'}], 'check_inconclusive')):
            with self.subTest(why=why):
                state, detail = self.store.adopt_rule(checks=checks, **common)
                self.assertEqual(state, 'awaiting_verification')
                self.assertTrue(detail.startswith(why), detail)
        state, detail = self.store.adopt_rule(checks=[{'id': 'registry:span:quoted_span@1', 'verdict': 'fail'}],
                                              **common)
        self.assertEqual((state, detail.split(':')[0]), ('refused', 'check_failed'))
        self.assertIsNone(self.store.result('j1'))


class Audits(Base):
    def test_selection_is_seeded_without_replacement_and_capped(self):
        ids = [f'd{i:03d}' for i in range(100)]
        a = rp.select_audits(ids, 20261024)
        self.assertEqual((len(a), len(set(a))), (32, 32))
        self.assertEqual(a, rp.select_audits(list(reversed(ids)), 20261024))
        self.assertNotEqual(a, rp.select_audits(ids, 1))
        self.assertEqual(sorted(rp.select_audits(ids[:5], 3)), ids[:5])
        with self.assertRaises(Error):
            rp.select_audits(ids, True)

    def test_selection_is_roughly_uniform(self):
        ids = [f'p{i}' for i in range(64)]
        counts = dict.fromkeys(ids, 0)
        for seed in range(400):
            for p in rp.select_audits(ids, seed):
                counts[p] += 1
        self.assertTrue(all(140 < n < 260 for n in counts.values()), counts)

    def test_verdicts_quarantine_and_unresolved_audits_block_reuse(self):
        learn = self.learner()
        rid = learn.admit_side(side_ok(FIELD), source='s', provenance={})
        rows = [{'audit_job': f'a{i}', 'wave_id': 'w', 'original_job': f'j{i}', 'rule': rid, 'producer': 'p',
                 'submission': 's', 'dataset_id': f'd{i}', 'rule_value': '"1.00 mm"'} for i in range(3)]
        self.store.add_audits(rows)
        self.store.add_audits(rows)  # idempotent
        with self.assertRaisesRegex(Error, 'different identity'):
            self.store.add_audits([dict(rows[0], dataset_id='other')])
        self.assertEqual(self.store.reusable(rid), (False, 'audit_unresolved:pending=3'))
        self.store.decide_audit('a0', 'agree', model_value='"1.00 mm"')
        self.store.decide_audit('a1', 'inconclusive', detail='failed')
        self.assertFalse(self.store.reusable(rid)[0])
        self.store.decide_audit('a2', 'agree', model_value='"1.00 mm"')
        self.assertEqual(self.store.reusable(rid), (False, 'audit_unresolved:inconclusive=1'))
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.db.execute("UPDATE audits SET verdict='pending' WHERE audit_job='a0'")
        got = self.store.decide_audit('a1', 'disagree', model_value='"2.00 mm"')  # the reserve retry decides it
        self.assertTrue(got['quarantined_now'])
        self.assertEqual(self.store.rule(rid)['status'], 'quarantined')
        self.assertEqual(self.store.rule(rid)['quarantine']['dataset_id'], 'd1')
        self.assertEqual(self.store.reusable(rid), (False, 'quarantined'))


class Experiment(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.exp = rp.ExperimentStore(Path(temp.name) / 'experiment.sqlite')
        self.addCleanup(self.exp.close)
        self.producers = {f'p{p}': [f'd{p}-{i}' for i in range(64)] for p in range(4)}

    def test_the_bootstrap_assignment_is_16_from_each_of_4_producers_and_frozen(self):
        got = self.exp.assignment('codex', 'mat', self.producers, 7)
        self.assertEqual(sorted(got), ['p0', 'p1', 'p2', 'p3'])
        self.assertTrue(all(len(v) == 16 and set(v) <= set(self.producers[p]) for p, v in got.items()))
        shuffled = {p: list(reversed(v)) for p, v in self.producers.items()}
        self.assertEqual(self.exp.assignment('codex', 'mat', shuffled, 7), got)  # never by arrival order
        with self.assertRaisesRegex(Error, 'frozen'):
            self.exp.assignment('codex', 'mat', self.producers, 8)
        with self.assertRaisesRegex(Error, 'exactly 4'):
            rp.bootstrap_assignment({'p0': self.producers['p0']}, 7)
        with self.assertRaisesRegex(Error, 'needs 16'):
            rp.bootstrap_assignment(dict(self.producers, p3=['x']), 7)

    def test_one_claim_one_immutable_record(self):
        self.assertEqual(self.exp.claim_bootstrap('codex', 'mat', 'B')[0], 'run')
        self.assertEqual(self.exp.claim_bootstrap('codex', 'mat', 'C')[0], 'wait')
        self.assertEqual(self.exp.claim_bootstrap('codex', 'mat', 'B')[0], 'resume')
        with self.assertRaisesRegex(Error, 'not claimed by C'):
            self.exp.record_bootstrap('codex', 'mat', 'C', {'status': 'ok'})
        self.exp.record_bootstrap('codex', 'mat', 'B', {'status': 'ok', 'jobs': {}})
        self.assertEqual(self.exp.claim_bootstrap('codex', 'mat', 'C')[0], 'import')
        with self.assertRaisesRegex(Error, 'differently'):
            self.exp.record_bootstrap('codex', 'mat', 'B', {'status': 'failed'})
        with self.assertRaises(sqlite3.DatabaseError):
            self.exp.db.execute("UPDATE bootstraps SET record='{}'")

    def test_an_audit_wave_is_persisted_once_and_shared(self):
        population = [f'd{i}' for i in range(100)]
        first = self.exp.audit_wave(rp.wave_id('codex', 'mat', 'cold'), 'h' * 64, 5, population)
        again = self.exp.audit_wave(rp.wave_id('codex', 'mat', 'cold'), 'h' * 64, 5, list(reversed(population)))
        self.assertEqual(first, again)
        self.assertEqual(len(first['selection']), 32)
        self.assertFalse(first['mismatch'])
        other = self.exp.audit_wave(rp.wave_id('codex', 'mat', 'cold'), 'h' * 64, 5, population[:50])
        self.assertTrue(other['mismatch'])
        self.assertEqual(other['selection'], first['selection'])
        with self.assertRaisesRegex(Error, 'seed is frozen'):
            self.exp.audit_wave(rp.wave_id('codex', 'mat', 'cold'), 'h' * 64, 6, population)


class Decode(unittest.TestCase):
    def test_decode_ast_returns_the_exact_bytes(self):
        data = SPACED.encode('utf-8')
        self.assertEqual(rp.decode_ast(entry(data)), (data, None))
        self.assertEqual(rp.decode_ast({'none': True}), (None, 'none_proposed'))
        self.assertEqual(rp.decode_ast({'none': False}), (None, 'side_file_malformed'))


if __name__ == '__main__':
    unittest.main()
