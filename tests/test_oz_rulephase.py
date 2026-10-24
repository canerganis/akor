"""oz_rulephase and examples/bootstrap_shim.py: rule store, admission of bootstrap candidates, D1 adoption, audit
selection, envelope parsing and the shim's one-call bootstrap. Fake adapters only, no model calls."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'examples'))

import bootstrap_shim as shim
from oz import Error
import oz_registry as reg
import oz_route
import oz_rule
import oz_rulephase as rp

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
CONST = json.dumps({'lang': 'oz-rule/1', 'expr': ['s', '1.00 mm']}, separators=(',', ':'))


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


def registry(**ops):
    ops = ops or {'e': operation()}
    return reg.Registry(reg.build_manifest(ops, {'span': SPAN, 'one_of': ONE_OF}, 'owner@example'))


def side_ok(ast_text, op='e'):
    rules = {op: 'none' if ast_text == 'none' else {'ast': ast_text, 'ast_sha256': rp.sha256_text(ast_text)}}
    return {'schema': 'oz.bootstrap.side/1', 'receipt': '1', 'status': 'ok', 'rules': rules}


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.store = rp.RuleStore(self.dir / 'rules.sqlite')
        self.addCleanup(self.store.close)

    def learner(self, reg_=None, op='e'):
        return rp.Learner(self.store, reg_ or registry(), op, worker_hash=WORKER, map_contract='c' * 64,
                          map_input_policy='strip-one-terminal-newline/1')


class Admission(Base):
    def test_a_field_rule_is_admitted_with_full_bindings_and_immutable_bytes(self):
        learner = self.learner()
        rid = learner.admit_side(side_ok(FIELD), source='r:1:e', provenance={'call_id': 'c1'})
        rule = self.store.rule(rid)
        self.assertEqual(rule['status'], 'admitted')
        self.assertEqual(rule['ast'], FIELD.encode())
        self.assertEqual(rule['ast_sha256'], hashlib.sha256(FIELD.encode()).hexdigest())
        self.assertEqual(rule['admission']['coverage'], 64)
        self.assertEqual(set(rule['bindings']), {'operation_id', 'registry', 'interpreter', 'map_input_policy',
                                                 'worker_hash', 'map_contract'})
        self.assertEqual(rule['bindings']['worker_hash'], WORKER)
        self.assertEqual(rule['bindings']['interpreter'], rp.INTERPRETER)
        self.assertEqual(rule['binding_key'], learner.key)
        self.assertEqual(self.store.active(learner.key)['id'], rid)
        # Idempotent per source; the bytes, bindings and admission can never change, nor the status go back.
        self.assertEqual(learner.admit_side(side_ok(CONST), source='r:1:e', provenance={}), rid)
        for sql in ("UPDATE rules SET ast=x'00'", "UPDATE rules SET bindings='{}'", "UPDATE rules SET admission='{}'",
                    'DELETE FROM rules'):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                self.store.db.execute(sql)
        self.assertTrue(self.store.quarantine(rid, {'why': 'test'}))
        with self.assertRaises(sqlite3.DatabaseError):
            self.store.db.execute("UPDATE rules SET status='admitted'")
        self.assertIsNone(self.store.active(learner.key))

    def test_label_mismatch_none_malformed_and_tampered_side_files_are_rejected(self):
        learner = self.learner()
        cases = [(side_ok(CONST), 'covered_errors'), (side_ok('none'), 'none_proposed'),
                 ({'schema': 'oz.bootstrap.side/1', 'receipt': '2', 'status': 'malformed'}, 'bootstrap_malformed'),
                 (None, 'bootstrap_missing')]
        tampered = side_ok(FIELD)
        tampered['rules']['e']['ast_sha256'] = '0' * 64
        cases.append((tampered, 'side_file_hash_mismatch'))
        for i, (side, reason) in enumerate(cases):
            with self.subTest(reason=reason):
                rule = self.store.rule(learner.admit_side(side, source=f's{i}', provenance={}))
                self.assertEqual(rule['status'], 'rejected')
                self.assertIn(reason, rule['admission']['reasons'])
        self.assertIsNone(self.store.active(learner.key))

    def test_boolq_and_one_of_only_operations_are_ineligible_and_never_admitted(self):
        r = registry(q=operation({'name': 'boolq', 'deterministic': True}, ('one_of',), boolq_cases()),
                     y=operation({'name': 'yesno', 'deterministic': True}, ('one_of',), boolq_cases()))
        for op in ('q', 'y'):
            with self.subTest(op=op):
                learner = self.learner(r, op)
                self.assertFalse(learner.eligible)
                self.assertFalse(learner.bootstrap_config(self.dir)['eligibility'][op])
                ast = json.dumps({'lang': 'oz-rule/1', 'expr': ['s', 'yes']}, separators=(',', ':'))
                rule = self.store.rule(learner.admit_side(side_ok(ast, op), source='b:' + op, provenance={}))
                self.assertEqual(rule['status'], 'rejected')
                self.assertIn('ineligible', rule['admission']['reasons'])
                decision = learner.attempt(rule, job='j1', text='passage', resolved_sha256=rp.sha256_text('passage'),
                                           op_text='Answer.', map_pinned=[], owner={})
                self.assertEqual(decision, {'decision': 'fallback', 'reason': 'ineligible'})

    def test_registry_route_must_be_the_map_worker_identity(self):
        with self.assertRaisesRegex(Error, 'binding_mismatch'):
            rp.Learner(self.store, registry(), 'e', worker_hash='f' * 64, map_contract='c' * 64,
                       map_input_policy='x')
        with self.assertRaisesRegex(Error, 'not in the registry'):
            self.learner(op='nope')


class Adoption(Base):
    def setUp(self):
        Base.setUp(self)
        self.learn = self.learner()
        self.rule = self.store.rule(self.learn.admit_side(side_ok(FIELD), source='s', provenance={}))
        self.owner = {'producer': 'p', 'submission': 's', 'operation': 'e', 'path': 'refs/a.txt'}

    def attempt(self, text, job='j1', **kw):
        return self.learn.attempt(self.rule, job=job, text=text, resolved_sha256=rp.sha256_text(text),
                                  op_text='Extract length.', map_pinned=kw.pop('pinned', []), owner=self.owner, **kw)

    def test_value_with_passing_checks_is_committed_with_provenance(self):
        got = self.attempt('length=12.50 mm; n=3')
        self.assertEqual(got['decision'], 'rule')
        row = got['row']
        self.assertEqual((row['value'], row['type'], row['rule']), ('"12.50 mm"', 'string', self.rule['id']))
        self.assertEqual(row['provenance']['check'], 'rule_provenance/1')
        self.assertTrue(row['provenance']['reevaluated'])
        self.assertEqual([c['verdict'] for c in row['checks']], ['pass'])
        self.assertEqual(self.attempt('length=12.50 mm; n=3')['resumed'], True)
        self.assertEqual([d['decision'] for d in self.store.decisions()], ['rule'])

    def test_abstain_and_check_failures_fall_back(self):
        self.assertEqual(self.attempt('width=3 mm', job='j2')['reason'], 'abstain:missing')
        pinned = [{'check': 'json_type', 'version': 1, 'types': ['array']}]
        self.assertTrue(self.attempt('length=1.00 mm', job='j3', pinned=pinned)['reason'].startswith(
            'check_failed:json_type@1'))
        self.assertIsNone(self.store.result('j2'))
        self.assertIsNone(self.store.result('j3'))

    def test_provenance_recheck_failure_blocks_the_commit(self):
        calls = []

        def drifting(ast, text):
            calls.append(text)
            result = oz_rule.evaluate(ast, text)
            return result if len(calls) == 1 else dict(result, value='99.00 mm')

        got = self.attempt('length=12.50 mm', evaluate=drifting)
        self.assertEqual(got, {'decision': 'fallback', 'reason': 'commit_refused:provenance_failed'})
        self.assertEqual(len(calls), 2)
        self.assertIsNone(self.store.result('j1'))

    def test_commit_rechecks_binding_and_quarantine_in_the_same_transaction(self):
        text = 'length=1.00 mm'
        first = oz_rule.evaluate(FIELD.encode(), text)
        state = self.store.adopt_rule(rule=dict(self.rule, binding_key='0' * 64), binding_key=self.learn.key,
                                      job='j9', text=text, resolved_sha256=rp.sha256_text(text), first=first,
                                      checks=[], owner=self.owner)
        self.assertEqual(state, ('refused', 'binding_changed'))

        def quarantine(db):  # another process quarantines the rule just before this commit
            db.execute("UPDATE rules SET status='quarantined' WHERE id=?", (self.rule['id'],))

        self.assertEqual(self.attempt(text, before_commit=quarantine)['reason'], 'commit_refused:quarantined')
        self.assertIsNone(self.store.result('j1'))
        self.assertIsNone(self.store.result('j9'))

    def test_changed_input_is_refused(self):
        text = 'length=1.00 mm'
        first = oz_rule.evaluate(FIELD.encode(), text)
        state = self.store.adopt_rule(rule=self.rule, binding_key=self.learn.key, job='j5', text=text,
                                      resolved_sha256='0' * 64, first=first, checks=[], owner=self.owner)
        self.assertEqual(state, ('refused', 'input_changed'))


class Audits(unittest.TestCase):
    def test_selection_is_seeded_without_replacement_and_capped(self):
        paths = [f'refs/{i:03d}.txt' for i in range(100)]
        a = rp.select_audits(paths, 20261024)
        self.assertEqual(len(a), 32)
        self.assertEqual(len(set(a)), 32)
        self.assertEqual(a, rp.select_audits(list(reversed(paths)), 20261024))
        self.assertNotEqual(a, rp.select_audits(paths, 1))
        self.assertEqual(sorted(rp.select_audits(paths[:5], 3)), paths[:5])
        with self.assertRaises(Error):
            rp.select_audits(paths, True)

    def test_selection_is_roughly_uniform(self):
        paths = [f'p{i}' for i in range(64)]
        counts = dict.fromkeys(paths, 0)
        for seed in range(400):
            for p in rp.select_audits(paths, seed):
                counts[p] += 1
        # Each path is chosen with probability 1/2: 200 of 400 expected; a fixed hash permutation would fail this.
        self.assertTrue(all(140 < n < 260 for n in counts.values()), counts)

    def test_wave_is_persisted_once_with_its_frozen_seed(self):
        with tempfile.TemporaryDirectory() as d:
            store = rp.RuleStore(Path(d) / 'r.sqlite')
            try:
                w = store.wave('p', 's', 1, 5, ['a', 'b', 'c'])
                self.assertEqual(store.wave('p', 's', 1, 5, ['c', 'b', 'a']), w)
                self.assertEqual(sorted(store.wave('p', 's', 1, 5, ['a', 'b', 'c', 'd'])['selected']),
                                 ['a', 'b', 'c', 'd'])
                with self.assertRaisesRegex(Error, 'seed is frozen'):
                    store.wave('p', 's', 1, 6, ['a'])
            finally:
                store.close()


class Envelope(unittest.TestCase):
    def test_instruction_is_verbatim_858_characters_from_the_spec(self):
        self.assertEqual(len(shim.INSTRUCTION), 858)
        spec = rp.SPEC_PATH.read_bytes().decode('utf-8').replace('\r\n', '\n')
        self.assertIn('```text\n' + shim.INSTRUCTION + '\n```', spec)
        excerpt = rp.spec_excerpt()
        self.assertTrue(excerpt.startswith('`oz-rule/1` is an opt-in'))
        self.assertNotIn('Worked ASTs', excerpt)
        self.assertNotIn('Bootstrap envelope', excerpt)

    def test_exact_envelope_parses_and_anything_else_is_malformed(self):
        good = json.dumps({'host': 'oz-bootstrap/1', 'answers': 'OZ/1g\n{"j":"x"}',
                           'rules': {'e': {'lang': 'oz-rule/1', 'expr': ['field', 'length']}, 'b': 'none'}})
        answers, rules = shim.parse_envelope(good, ['e', 'b'])
        self.assertEqual(answers, 'OZ/1g\n{"j":"x"}')
        self.assertEqual(rules['b'], 'none')
        self.assertEqual(rules['e']['ast'], FIELD)
        bad = ['```json\n' + good + '\n```', good + ' trailing', 'OZ/1g\n{"j":"x"}',
               good.replace('"host"', '"hostx"'), json.dumps({'host': 'oz-bootstrap/1', 'answers': 'x',
                                                              'rules': {'e': 'none'}}),
               json.dumps({'host': 'oz-bootstrap/1', 'answers': 'x', 'rules': {'e': 'none', 'b': 'none'}, 'x': 1}),
               json.dumps({'host': 'oz-bootstrap/1', 'answers': 7, 'rules': {'e': 'none', 'b': 'none'}}),
               json.dumps({'host': 'oz-bootstrap/1', 'answers': 'x', 'rules': {'e': ['field'], 'b': 'none'}}),
               '{"host":"oz-bootstrap/1","host":"oz-bootstrap/1","answers":"x","rules":{"e":"none","b":"none"}}',
               None]
        for text in bad:
            with self.subTest(text=str(text)[:50]), self.assertRaises(shim.Malformed):
                shim.parse_envelope(text, ['e', 'b'])

    def test_system_text_keeps_the_original_and_appends_instruction_spec_contracts(self):
        config = {'ops': ['e'], 'contracts': {'e': E_CONTRACT}, 'eligibility': {'e': True}, 'spec': 'SPEC'}
        text = shim.system_text('ORIGINAL', config)
        self.assertTrue(text.startswith('ORIGINAL\n\n' + shim.INSTRUCTION))
        self.assertIn('SPEC', text)
        self.assertIn('"extract_length"', text)
        self.assertIn('{"host":"oz-bootstrap/1","answers":"<ordinary OZ/1g reply>","rules":{"e":"none"}}', text)


class Shim(unittest.TestCase):
    """The shim's own process contract with a fake real adapter script."""
    REAL = r'''
import json, sys
if '--identity' in sys.argv:
    print(json.dumps({'backend': 'fake', 'model': 'm', 'effort': 'e', 'cli_version': '1', 'flags': []})); raise SystemExit
req = json.load(sys.stdin)
reply = json.dumps({'host': 'oz-bootstrap/1', 'answers': 'OZ/1g\n{"j1":"ok"}', 'rules': {'e': 'none'}})
if 'oz-bootstrap/1 JSON envelope' not in req['system']:
    reply = 'OZ/1g\n{"j1":"plain"}'
json.dump({'reply': reply, 'usage': {'input_tokens': 5, 'output_tokens': 1}}, sys.stdout)
'''

    def run_shim(self, env, *extra, request=None):
        request = request or {'receipt': '7', 'ids': ['j1'], 'system': 'SYS', 'prompt': '{}'}
        done = subprocess.run([sys.executable, str(REPO / 'examples' / 'bootstrap_shim.py'), str(self.real), *extra],
                              input=json.dumps(request), capture_output=True, text=True,
                              env=dict(os.environ, **env), encoding='utf-8')
        return done

    def test_passthrough_bootstrap_once_and_identity(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.real = d / 'real.py'
            self.real.write_text(self.REAL, encoding='utf-8')
            env = {k: v for k, v in os.environ.items() if k != 'OZ_BOOTSTRAP'}
            plain = subprocess.run([sys.executable, str(REPO / 'examples' / 'bootstrap_shim.py'), str(self.real)],
                                   input=json.dumps({'receipt': '1', 'system': 'S', 'prompt': ''}),
                                   capture_output=True, text=True, env=env, encoding='utf-8')
            self.assertEqual(json.loads(plain.stdout)['reply'], 'OZ/1g\n{"j1":"plain"}')
            ident = self.run_shim({}, '--identity')
            self.assertEqual(json.loads(ident.stdout)['backend'], 'fake')
            config = d / 'config.json'
            config.write_text(json.dumps({'schema': 'oz.bootstrap.config/1', 'side_dir': str(d / 'side'),
                                          'ops': ['e'], 'contracts': {'e': {}}, 'eligibility': {'e': True},
                                          'spec': 'S'}), encoding='utf-8')
            first = self.run_shim({'OZ_BOOTSTRAP': str(config)})
            self.assertEqual(first.returncode, 0, first.stderr)
            out = json.loads(first.stdout)
            self.assertEqual(out, {'reply': 'OZ/1g\n{"j1":"ok"}', 'usage': {'input_tokens': 5, 'output_tokens': 1}})
            side = json.loads((d / 'side' / '7.json').read_text(encoding='utf-8'))
            self.assertEqual((side['status'], side['rules'], side['receipt']), ('ok', {'e': 'none'}, '7'))
            self.assertIn('"rules": {"e": "none"}', side['raw_reply'])
            # A second call of the same bootstrap request is a passthrough: one physical bootstrap call only.
            second = self.run_shim({'OZ_BOOTSTRAP': str(config)}, request={'receipt': '8', 'ids': ['j1'],
                                                                           'system': 'SYS', 'prompt': '{}'})
            self.assertEqual(json.loads(second.stdout)['reply'], 'OZ/1g\n{"j1":"plain"}')
            self.assertFalse((d / 'side' / '8.json').exists())


if __name__ == '__main__':
    unittest.main()
