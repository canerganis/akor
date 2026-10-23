"""oz_registry: canonical(), strict JSON, input policy, manifest resolution, tamper cases, derived eligibility,
registry-resolved admission (amendment 1 D6) and decimal-as-string checks (D9). No model calls."""
import copy
import hashlib
import json
import os
import tempfile
import unittest

import oz_registry as reg
import oz_rule
from oz_registry import RegistryError, canonical, digest

ROUTE = {'adapter_hash': 'a' * 64, 'backend': 'codex', 'model': 'm1', 'effort': 'low', 'cli_version': '1.0',
         'environment_hash': 'b' * 64}
POLICY = {'version': 'oz-input/1', 'terminal_newline': 'strip_one', 'text_ref': 0}
PROVENANCE = {'labeler': 'human-1', 'method': 'hand labeled', 'independent': True, 'hidden_from_synthesis': True,
              'synthesis_agents': ['astra', 'sonnet']}
SPAN = {'name': 'quoted_span', 'version': 1, 'kind': 'consumer', 'params': {}}
ECHO = json.dumps({'lang': 'oz-rule/1', 'expr': ['input']}, separators=(',', ':')).encode()
CONTRACT = {'name': 'echo', 'deterministic': True}


def echo_cases(n_rep=48, n_chal=16):
    out = []
    for i in range(n_rep + n_chal):
        out.append({'id': 'c%d' % i, 'text': 't%d' % i, 'partition': 'representative' if i < n_rep else 'challenge',
                    'expected': {'type': 'string', 'value': 't%d' % i}})
    return out


def operation(**over):
    op = {'contract': copy.deepcopy(CONTRACT), 'checks': ['span'], 'permissions': {}, 'input_policy': dict(POLICY),
          'route': dict(ROUTE), 'cases': echo_cases(), 'provenance': dict(PROVENANCE)}
    op.update(over)
    return op


def make_manifest(operations=None, checks=None, runner=None):
    return reg.build_manifest(operations if operations is not None else {'echo': operation()},
                              checks if checks is not None else {'span': SPAN}, 'owner@example', runner)


def make_registry(operations=None, checks=None):
    return reg.Registry(make_manifest(operations, checks))


def decimal_cases():
    out = []
    for i in range(64):
        out.append({'id': 'd%d' % i, 'text': '%d.50' % i, 'partition': 'representative' if i < 48 else 'challenge',
                    'expected': {'type': 'decimal', 'value': '%d.5' % i}})
    return out


def resolve_error(manifest, op='echo', claimed=None):
    with unittest.TestCase().assertRaises(RegistryError) as cm:
        reg.Registry(manifest).resolve(op, claimed)
    return cm.exception


class Canonical(unittest.TestCase):
    def test_exact_definition(self):
        x = {'b': [1, 'é', True, None], 'a': {'z': 1, 'y': 'x'}}
        want = json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        self.assertEqual(canonical(x), want)
        self.assertEqual(canonical(x), '{"a":{"y":"x","z":1},"b":[1,"é",true,null]}'.encode('utf-8'))
        self.assertEqual(digest(x), hashlib.sha256(want).hexdigest())

    def test_key_order_does_not_matter(self):
        self.assertEqual(canonical({'a': 1, 'b': 2}), canonical({'b': 2, 'a': 1}))

    def test_rejections(self):
        for bad in (float('nan'), float('inf'), '\ud800', {'k\ud800': 1}, ['ok', '\udfff'], {1: 'x'}, {'a': object()},
                    {'a': {1, 2}}):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(RegistryError):
                    canonical(bad)

    def test_loads_strict(self):
        self.assertEqual(reg.loads_strict('{"a":[1,2]}'), {'a': [1, 2]})
        for bad in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":"\\ud800"}', '{"a":1', b'\xef\xbb\xbf{}',
                    b'{"a":"\xff"}', '[1,]'):
            with self.subTest(bad=bad):
                with self.assertRaises(RegistryError):
                    reg.loads_strict(bad)


class InputPolicy(unittest.TestCase):
    def test_strip_exactly_one_terminal_newline(self):
        f = lambda t: reg.apply_input_policy(POLICY, t)
        self.assertEqual(f('a=b\r\n'), 'a=b')
        self.assertEqual(f('a=b\n'), 'a=b')
        self.assertEqual(f('a=b\n\n'), 'a=b\n')
        self.assertEqual(f('a=b\r\n\r\n'), 'a=b\r\n')
        self.assertEqual(f('a=b\r'), 'a=b\r')
        self.assertEqual(f('a\nb'), 'a\nb')
        self.assertEqual(f(' a=b '), ' a=b ')
        self.assertEqual(reg.apply_input_policy(dict(POLICY, terminal_newline='none'), 'a\n'), 'a\n')

    def test_resolved_texts_must_be_distinct(self):
        cases = echo_cases()
        cases[1]['text'] = 't0\n'  # distinct raw text, same resolved text as case c0
        cases[1]['expected'] = {'type': 'string', 'value': 't0'}
        err = resolve_error(make_manifest({'echo': operation(cases=cases)}))
        self.assertEqual((err.code, 'duplicate case' in str(err)), ('cases', True))

    def test_policy_validated(self):
        for bad in (dict(POLICY, version='x'), dict(POLICY, terminal_newline='all'), dict(POLICY, text_ref=-1),
                    dict(POLICY, text_ref=True), {'version': 'oz-input/1'}):
            with self.subTest(bad=bad):
                self.assertEqual(resolve_error(make_manifest({'echo': operation(input_policy=bad)})).code, 'input_policy')

    def test_admission_evaluates_resolved_text(self):
        cases = echo_cases()
        for c in cases:
            c['text'] += '\n'  # raw files end in LF; the policy strips it so the echo rule matches the label
        r = make_registry({'echo': operation(cases=cases)}).admit(ECHO, 'echo')
        self.assertEqual((r['status'], r['coverage']), ('accepted', 64))
        self.assertEqual(r['cases'][0]['input_sha256'], hashlib.sha256(b't0').hexdigest())


class Resolve(unittest.TestCase):
    def test_resolves_and_binds(self):
        r = make_registry()
        pkg = r.resolve('echo')
        self.assertEqual(pkg.operation_id, 'echo')
        self.assertEqual(set(pkg.bindings), set(reg.BINDINGS))
        m = make_manifest()['operations']['echo']
        self.assertEqual(pkg.bindings['dataset_hash'], hashlib.sha256(canonical(echo_cases())).hexdigest())
        self.assertEqual(pkg.bindings['worker_hash'], hashlib.sha256(canonical(ROUTE)).hexdigest())
        self.assertEqual(pkg.bindings['contract_hash'], m['contract_hash'])
        self.assertEqual(len(pkg.cases), 64)
        self.assertEqual(pkg.deferred_checks(), [])
        self.assertTrue(pkg.eligible)
        self.assertIsNone(pkg.verify())

    def test_manifest_from_file_and_pin(self):
        manifest = make_manifest()
        raw = json.dumps(manifest).encode()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'registry.json')
            with open(path, 'wb') as f:
                f.write(raw)
            pkg = reg.Registry(path, expected_sha256=hashlib.sha256(raw).hexdigest()).resolve('echo')
            self.assertEqual(pkg.operation_id, 'echo')
            with self.assertRaises(RegistryError) as cm:
                reg.Registry(path, expected_sha256='0' * 64)
            self.assertEqual(cm.exception.code, 'manifest_hash_mismatch')
            dup = os.path.join(d, 'dup.json')
            with open(dup, 'wb') as f:
                f.write(raw.replace(b'"schema"', b'"schema":"x","schema"', 1))
            with self.assertRaises(RegistryError):
                reg.Registry(dup)
        with self.assertRaises(RegistryError):
            reg.Registry(manifest, expected_sha256='0' * 64)
        self.assertEqual(reg.Registry(manifest, expected_sha256=digest(manifest)).operations(), ['echo'])

    def test_manifest_must_be_frozen_and_approved(self):
        for key, value in (('frozen', False), ('approved_by', ''), ('schema', 'x')):
            m = make_manifest()
            m[key] = value
            with self.subTest(key=key):
                with self.assertRaises(RegistryError):
                    reg.Registry(m)
        m = make_manifest()
        m['extra'] = 1
        with self.assertRaises(RegistryError):
            reg.Registry(m)

    def test_unknown_operation_and_bindings(self):
        r = make_registry()
        with self.assertRaises(RegistryError) as cm:
            r.resolve('nope')
        self.assertEqual(cm.exception.code, 'unknown_operation')
        good = r.resolve('echo').bindings
        self.assertEqual(r.resolve('echo', claimed=good).operation_id, 'echo')
        self.assertEqual(r.resolve('echo', claimed={'dataset_hash': good['dataset_hash']}).operation_id, 'echo')
        for claimed, code in (({'surprise_hash': 'x'}, 'unknown_binding'), ({'dataset_hash': '0' * 64}, 'binding_mismatch'),
                              (dict(good, worker_hash='1' * 64), 'binding_mismatch'), ('x', 'unknown_binding')):
            with self.subTest(claimed=str(claimed)[:30]):
                with self.assertRaises(RegistryError) as cm:
                    r.resolve('echo', claimed=claimed)
                self.assertEqual(cm.exception.code, code)

    def test_package_is_issued_only_by_the_registry(self):
        with self.assertRaises(TypeError):
            reg.ResolvedPackage(object(), b'{}', reg.LocalChecks())
        pkg = make_registry().resolve('echo')
        with self.assertRaises(AttributeError):
            pkg.operation_id = 'x'
        with self.assertRaises(AttributeError):
            pkg.extra = 1
        pkg.cases[0]['text'] = 'changed'  # a returned copy; the package itself is unchanged
        self.assertEqual(pkg.cases[0]['text'], 't0')


class Tamper(unittest.TestCase):
    """Every artifact is recomputed against the frozen manifest; a mismatch rejects before any case is evaluated."""

    def edit(self, fn, op='echo'):
        m = make_manifest()
        fn(m, m['operations'][op])
        return resolve_error(m, op).code

    def test_contract_hash_mismatch(self):
        self.assertEqual(self.edit(lambda m, o: o['contract'].update(name='other')), 'contract_hash_mismatch')

    def test_contract_hash_field_mismatch(self):
        self.assertEqual(self.edit(lambda m, o: o.update(contract_hash='0' * 64)), 'contract_hash_mismatch')

    def test_check_definition_mismatch(self):
        self.assertEqual(self.edit(lambda m, o: m['checks']['span']['definition'].update(params={'field': 'x'})),
                         'check_definition_hash_mismatch')

    def test_check_implementation_digest_mismatch(self):
        self.assertEqual(self.edit(lambda m, o: m['checks']['span'].update(impl_digest='0' * 64)), 'check_impl_mismatch')
        self.assertEqual(self.edit(lambda m, o: m['checks']['span'].update(impl_version=2)), 'check_impl_mismatch')

    def test_check_hash_mismatch(self):
        self.assertEqual(self.edit(lambda m, o: o.update(check_hash='0' * 64)), 'check_hash_mismatch')

    def test_permission_hash_mismatch(self):
        self.assertEqual(self.edit(lambda m, o: o['permissions'].update(rule_provenance=True)), 'permission_hash_mismatch')

    def test_input_policy_hash_mismatch(self):
        self.assertEqual(self.edit(lambda m, o: o['input_policy'].update(text_ref=1)), 'input_policy_hash_mismatch')

    def test_route_hash_mismatch(self):
        self.assertEqual(self.edit(lambda m, o: o['route'].update(model='m2')), 'worker_hash_mismatch')
        self.assertEqual(self.edit(lambda m, o: o['route'].update(effort='high')), 'worker_hash_mismatch')

    def test_route_must_carry_the_d7_identity(self):
        self.assertEqual(self.edit(lambda m, o: o['route'].pop('cli_version')), 'route')
        self.assertEqual(self.edit(lambda m, o: o['route'].update(extra=1)), 'route')

    def test_dataset_hash_mismatch_on_text(self):
        self.assertEqual(self.edit(lambda m, o: o['dataset']['cases'][3].update(text='tampered')), 'dataset_hash_mismatch')

    def test_dataset_hash_mismatch_on_label_id_and_order(self):
        self.assertEqual(self.edit(lambda m, o: o['dataset']['cases'][3]['expected'].update(value='z')), 'dataset_hash_mismatch')
        self.assertEqual(self.edit(lambda m, o: o['dataset']['cases'][3].update(id='renamed')), 'dataset_hash_mismatch')

        def swap(m, o):
            c = o['dataset']['cases']
            c[0], c[1] = c[1], c[0]
        self.assertEqual(self.edit(swap), 'dataset_hash_mismatch')

    def test_dataset_hash_mismatch_on_partition(self):
        def flip(m, o):
            c = o['dataset']['cases']
            c[0]['partition'], c[63]['partition'] = 'challenge', 'representative'  # counts stay 48 and 16
        self.assertEqual(self.edit(flip), 'dataset_hash_mismatch')

    def test_dataset_hash_field_mismatch(self):
        self.assertEqual(self.edit(lambda m, o: o['dataset'].update(dataset_hash='0' * 64)), 'dataset_hash_mismatch')

    def test_dataset_extra_case_key_and_count(self):
        self.assertEqual(self.edit(lambda m, o: o['dataset']['cases'][0].update(hint='x')), 'cases')
        self.assertEqual(self.edit(lambda m, o: o['dataset']['cases'].pop()), 'cases')

    def test_label_provenance_missing(self):
        self.assertEqual(self.edit(lambda m, o: o['dataset'].pop('provenance')), 'provenance_missing')
        self.assertEqual(self.edit(lambda m, o: o['dataset'].update(provenance={})), 'provenance_missing')
        self.assertEqual(self.edit(lambda m, o: o['dataset']['provenance'].pop('labeler')), 'provenance_missing')
        self.assertEqual(self.edit(lambda m, o: o['dataset']['provenance'].update(labeler='')), 'provenance_missing')

    def test_label_provenance_must_be_independent(self):
        for change in ({'independent': False}, {'hidden_from_synthesis': False}, {'labeler': 'astra'},
                       {'independent': 'yes'}, {'synthesis_agents': 'astra'}):
            with self.subTest(change=change):
                code = self.edit(lambda m, o: o['dataset']['provenance'].update(change))
                self.assertIn(code, ('provenance_invalid', 'provenance_missing'))

    def test_labels_recomputed_against_provenance(self):
        def relabel(m, o):  # a re-labeled dataset with a consistent dataset hash but stale label provenance
            o['dataset']['cases'][0]['expected']['value'] = 'x'
            o['dataset']['dataset_hash'] = digest(o['dataset']['cases'])
        self.assertEqual(self.edit(relabel), 'provenance_labels_mismatch')

    def test_unresolved_checks(self):
        def missing(m, o):
            o['checks'] = ['ghost']
        self.assertEqual(self.edit(missing), 'unresolved_check')
        self.assertEqual(self.edit(lambda m, o: o.update(checks=[])), 'unresolved_check')
        self.assertEqual(self.edit(lambda m, o: m['checks']['span']['definition'].update(name='nope')),
                         'check_definition_hash_mismatch')

        def renamed(m, o):
            e = m['checks']['span']
            e['definition']['name'] = 'nope'
            e['definition_hash'] = digest(e['definition'])
        self.assertEqual(self.edit(renamed), 'unresolved_check')

        def version(m, o):
            e = m['checks']['span']
            e['definition']['version'] = 7
            e['definition_hash'] = digest(e['definition'])
        self.assertEqual(self.edit(version), 'unresolved_check')

        def params(m, o):
            e = m['checks']['span']
            e['definition']['params'] = {'bogus': 1}
            e['definition_hash'] = digest(e['definition'])
        self.assertEqual(self.edit(params), 'unresolved_check')

    def test_tamper_rejects_before_any_case_is_evaluated(self):
        m = make_manifest()
        m['operations']['echo']['route']['model'] = 'm2'
        seen = []
        real = oz_rule.evaluate
        oz_rule.evaluate = lambda *a: seen.append(a) or real(*a)
        try:
            r = reg.Registry(m).admit(ECHO, 'echo')
        finally:
            oz_rule.evaluate = real
        self.assertEqual(seen, [])
        self.assertEqual((r['status'], r['coverage'], r['cases']), ('rejected', 0, []))
        self.assertEqual(r['reasons'], ['unresolved:worker_hash_mismatch'])

    def test_package_tampered_after_issue_is_rejected_by_admit(self):
        pkg = make_registry().resolve('echo')
        data = json.loads(pkg._blob.decode('utf-8'))
        data['cases'][0]['text'] = 'tampered'
        object.__setattr__(pkg, '_blob', canonical(data))
        r = oz_rule.admit(ECHO, pkg)
        self.assertEqual((r['status'], r['cases']), ('rejected', []))
        self.assertEqual(r['reasons'], ['invalid_package:dataset_hash_mismatch'])

    def test_admit_refuses_anything_but_a_resolved_package(self):
        pkg = make_registry().resolve('echo')
        fake = {'operation_id': 'echo', 'cases': pkg.cases, 'bindings': pkg.bindings, 'eligible': True,
                'check': lambda t, c: True}
        for bad in (fake, None, 'x', object()):
            r = oz_rule.admit(ECHO, bad)
            self.assertEqual((r['status'], r['cases'], r['coverage']), ('rejected', [], 0))
            self.assertEqual(r['reasons'], ['invalid_package:unresolved'])
        with self.assertRaises(TypeError):
            oz_rule.admit(ECHO, pkg, lambda t, c: True)  # no caller callbacks


ONE_OF = {'name': 'one_of', 'version': 1, 'kind': 'consumer', 'params': {'values': ['a']}}
JSON_STRING = {'name': 'json_type', 'version': 1, 'kind': 'consumer', 'params': {'types': ['string']}}
MAX_BYTES = {'name': 'max_bytes', 'version': 1, 'kind': 'consumer', 'params': {'bytes': 100}}
EXPECT = {'name': 'expect', 'version': 1, 'kind': 'consumer', 'params': {'value': 'x'}}


def provenance_check(contract):
    return {'name': 'rule_provenance', 'version': 1, 'kind': 'provenance', 'params': {},
            'authorized_contract_hashes': [digest(contract)]}


class Eligibility(unittest.TestCase):
    def code(self, operations, checks):
        with self.assertRaises(RegistryError) as cm:
            reg.Registry(make_manifest(operations, checks)).resolve('echo')
        self.assertEqual(cm.exception.code, 'ineligible', str(cm.exception))
        return str(cm.exception)

    def test_boolq_is_ineligible_even_with_an_input_bound_check(self):
        for contract in ({'name': 'BoolQ', 'deterministic': True}, {'name': 'x', 'family': 'bool-q', 'deterministic': True},
                         {'name': 'x', 'dataset': 'google/boolq', 'deterministic': True}):
            with self.subTest(contract=contract):
                self.assertIn('BoolQ', self.code({'echo': operation(contract=contract)}, {'span': SPAN}))
        with self.assertRaises(RegistryError) as cm:  # also by operation id
            reg.Registry(make_manifest({'boolq-a': operation()}, {'span': SPAN})).resolve('boolq-a')
        self.assertEqual(cm.exception.code, 'ineligible')

    def test_boolq_is_ineligible_even_with_d1(self):
        contract = {'name': 'BoolQ', 'deterministic': True}
        ops = {'echo': operation(contract=contract, checks=['prov'], permissions={'rule_provenance': True})}
        self.assertIn('BoolQ', self.code(ops, {'prov': provenance_check(contract)}))

    def test_one_of_alone_is_ineligible(self):
        self.assertIn('one_of', self.code({'echo': operation(checks=['one'])}, {'one': ONE_OF}))

    def test_shape_checks_cannot_establish_eligibility(self):
        ops = {'echo': operation(checks=['one', 'type', 'size', 'exp'])}
        self.code(ops, {'one': ONE_OF, 'type': JSON_STRING, 'size': MAX_BYTES, 'exp': EXPECT})
        self.code({'echo': operation(checks=['type'])}, {'type': JSON_STRING})

    def test_one_of_plus_input_bound_check_is_eligible(self):
        ops = {'echo': operation(checks=['one', 'span'])}
        pkg = reg.Registry(make_manifest(ops, {'one': ONE_OF, 'span': SPAN})).resolve('echo')
        self.assertTrue(pkg.eligible)

    def test_must_declare_a_deterministic_contract(self):
        for contract in ({'name': 'echo'}, {'name': 'echo', 'deterministic': False}, {'name': 'echo', 'deterministic': 1}):
            with self.subTest(contract=contract):
                self.assertIn('deterministic', self.code({'echo': operation(contract=contract)}, {'span': SPAN}))

    def test_d1_authorization_satisfies_the_input_check_requirement(self):
        ops = {'echo': operation(checks=['prov'], permissions={'rule_provenance': True})}
        pkg = reg.Registry(make_manifest(ops, {'prov': provenance_check(CONTRACT)})).resolve('echo')
        self.assertTrue(pkg.eligible)
        self.assertEqual(pkg.deferred_checks(), [{'id': 'prov', 'name': 'rule_provenance', 'version': 1}])

    def test_d1_needs_explicit_authorization_for_this_contract(self):
        other = {'name': 'other', 'deterministic': True}
        self.code({'echo': operation(checks=['prov'], permissions={'rule_provenance': True})},
                  {'prov': provenance_check(other)})  # authorized for another contract, not an op sharing the ID
        self.code({'echo': operation(checks=['prov'])}, {'prov': provenance_check(CONTRACT)})  # permission absent
        self.code({'echo': operation(checks=['prov'], permissions={'rule_provenance': 'yes'})},
                  {'prov': provenance_check(CONTRACT)})

    def test_d1_cannot_be_claimed_by_a_consumer_definition(self):
        d = dict(provenance_check(CONTRACT), kind='consumer')
        d.pop('authorized_contract_hashes')
        ops = {'echo': operation(checks=['prov'], permissions={'rule_provenance': True})}
        with self.assertRaises(RegistryError) as cm:
            reg.Registry(make_manifest(ops, {'prov': d})).resolve('echo')
        self.assertEqual(cm.exception.code, 'unresolved_check')

    def test_ineligible_rejects_through_admit_before_cases(self):
        r = reg.Registry(make_manifest({'echo': operation(checks=['one'])}, {'one': ONE_OF})).admit(ECHO, 'echo')
        self.assertEqual((r['status'], r['reasons'], r['cases'], r['coverage']), ('rejected', ['ineligible'], [], 0))

    def test_d1_package_admits_with_deferred_provenance(self):
        ops = {'echo': operation(checks=['prov'], permissions={'rule_provenance': True})}
        r = reg.Registry(make_manifest(ops, {'prov': provenance_check(CONTRACT)})).admit(ECHO, 'echo')
        self.assertEqual((r['status'], r['coverage'], r['covered_errors']), ('accepted', 64, 0))
        self.assertEqual(r['deferred_checks'], [{'id': 'prov', 'name': 'rule_provenance', 'version': 1}])
        self.assertEqual(r['cases'][0]['checks'], [])


class RegistryAdmission(unittest.TestCase):
    def test_accept_and_retained_outcomes(self):
        r = make_registry().admit(ECHO, 'echo')
        self.assertEqual(r['status'], 'accepted')
        self.assertEqual((r['reasons'], r['coverage'], r['covered_errors'], r['operation_id']), ([], 64, 0, 'echo'))
        self.assertEqual(r['ast_hash'], hashlib.sha256(ECHO).hexdigest())
        self.assertEqual(set(r['bindings']), set(reg.BINDINGS))
        c = r['cases'][5]
        self.assertEqual(c['result'], {'status': 'value', 'type': 'string', 'value': 't5', 'steps': c['steps']})
        self.assertEqual(c['checks'], [{'id': 'span', 'check': 'quoted_span', 'version': 1, 'verdict': 'pass'}])
        self.assertTrue(c['label_match'] and c['check_ok'] and not c['error'])
        self.assertEqual([x['id'] for x in r['cases']], ['c%d' % i for i in range(64)])

    def test_label_mismatch_rejects(self):
        cases = echo_cases()
        cases[5]['expected'] = {'type': 'string', 'value': 'wrong'}
        r = make_registry({'echo': operation(cases=cases)}).admit(ECHO, 'echo')
        self.assertEqual((r['status'], r['covered_errors']), ('rejected', 1))
        self.assertIn('covered_errors', r['reasons'])
        self.assertFalse(r['cases'][5]['label_match'])
        self.assertTrue(r['cases'][5]['check_ok'])

    def test_registry_check_failure_rejects(self):
        # quoted_span fails for a rule that invents a string that is not in the input
        ast = json.dumps({'lang': 'oz-rule/1', 'expr': ['s', 'invented']}).encode()
        cases = echo_cases()
        for c in cases:
            c['expected'] = {'type': 'string', 'value': 'invented'}
        r = make_registry({'echo': operation(cases=cases)}).admit(ast, 'echo')
        self.assertEqual((r['status'], r['coverage'], r['covered_errors']), ('rejected', 64, 64))
        self.assertTrue(all(c['label_match'] and not c['check_ok'] for c in r['cases']))
        self.assertEqual(r['cases'][0]['checks'][0]['verdict'], 'fail')

    def test_coverage_boundary(self):
        def lookup(n):
            return json.dumps({'lang': 'oz-rule/1', 'expr': ['lookup', ['input'], [['t%d' % i, 't%d' % i] for i in range(n)]]}).encode()
        r = make_registry().admit(lookup(31), 'echo')
        self.assertEqual((r['status'], r['coverage'], r['covered_errors']), ('rejected', 31, 0))
        self.assertIn('coverage', r['reasons'])
        self.assertEqual(r['cases'][40]['result']['reason'], 'lookup')
        self.assertEqual(r['cases'][40]['checks'], [])
        r = make_registry().admit(lookup(32), 'echo')
        self.assertEqual((r['status'], r['coverage']), ('accepted', 32))

    def test_invalid_ast_has_no_evaluated_cases(self):
        r = make_registry().admit(b'{"lang":"oz-rule/1","expr":["eval","1"]}', 'echo')
        self.assertEqual((r['status'], r['coverage'], r['cases']), ('rejected', 0, []))
        self.assertTrue(r['reasons'][0].startswith('invalid_ast'))
        for bad in (None, 5, b'\xff'):
            self.assertEqual(make_registry().admit(bad, 'echo')['status'], 'rejected')

    def test_unknown_operation_and_claimed_bindings(self):
        r = make_registry()
        self.assertEqual(r.admit(ECHO, 'nope')['reasons'], ['unresolved:unknown_operation'])
        self.assertEqual(r.admit(ECHO, 'echo', {'bogus': 'x'})['reasons'], ['unresolved:unknown_binding'])
        self.assertEqual(r.admit(ECHO, 'echo', {'dataset_hash': '0' * 64})['reasons'], ['unresolved:binding_mismatch'])
        ok = r.admit(ECHO, 'echo', r.resolve('echo').bindings)
        self.assertEqual(ok['status'], 'accepted')

    def test_type_must_match_label(self):
        cases = echo_cases()
        for c in cases:
            c['text'] = c['text'] + '.5'
            c['expected'] = {'type': 'decimal', 'value': c['text']}
        # canonical decimal labels only: 't0.5' is not one, so the dataset is refused at resolution
        err = resolve_error(make_manifest({'echo': operation(cases=cases)}))
        self.assertEqual((err.code, 'case label' in str(err)), ('cases', True))

    def test_runtime_runner_is_used_and_can_be_unavailable(self):
        class Down(reg.LocalChecks):
            def run(self, name, version, params, value, text):
                raise reg.CheckUnavailable('verifier down')
        r = reg.Registry(make_manifest(), runner=Down()).admit(ECHO, 'echo')
        self.assertEqual((r['status'], r['covered_errors']), ('rejected', 64))
        self.assertEqual(r['cases'][0]['checks'][0]['verdict'], 'inconclusive')
        self.assertFalse(r['cases'][0]['check_ok'])

    def test_runner_with_other_implementation_digest_is_a_mismatch(self):
        class Other(reg.LocalChecks):
            def describe(self, name, version):
                info = reg.LocalChecks.describe(self, name, version)
                return dict(info, impl_digest='f' * 64)
        with self.assertRaises(RegistryError) as cm:
            reg.Registry(make_manifest(), runner=Other()).resolve('echo')
        self.assertEqual(cm.exception.code, 'check_impl_mismatch')

    def test_check_exceptions_never_escape(self):
        class Boom(reg.LocalChecks):
            def run(self, name, version, params, value, text):
                raise RuntimeError('x')
        r = reg.Registry(make_manifest(), runner=Boom()).admit(ECHO, 'echo')
        self.assertEqual((r['status'], r['covered_errors']), ('rejected', 64))


class DecimalsAsStrings(unittest.TestCase):
    """D9: decimal wire values are JSON strings and consumer checks see that representation."""
    NUM = json.dumps({'lang': 'oz-rule/1', 'expr': ['add', ['num', ['input'], ''], ['d', '0']]}).encode()

    def registry(self, check):
        ops = {'dec': operation(contract={'name': 'dec', 'deterministic': True}, cases=decimal_cases(),
                                checks=['span', 'k'])}
        # quoted_span sees the string "3.5", which occurs in the input text "3.50"
        return reg.Registry(make_manifest(ops, {'span': SPAN, 'k': check}))

    def test_checks_see_a_json_string(self):
        r = self.registry(JSON_STRING).admit(self.NUM, 'dec')
        self.assertEqual(r['status'], 'accepted', r['reasons'])
        self.assertEqual(r['cases'][3]['result']['value'], '3.5')
        self.assertIsInstance(r['cases'][3]['result']['value'], str)

    def test_number_typed_check_fails_on_decimal(self):
        number = {'name': 'json_type', 'version': 1, 'kind': 'consumer', 'params': {'types': ['number']}}
        r = self.registry(number).admit(self.NUM, 'dec')
        self.assertEqual((r['status'], r['covered_errors']), ('rejected', 64))
        self.assertEqual(r['cases'][0]['checks'][1]['verdict'], 'fail')

    def test_canonical_value_text_is_a_string(self):
        self.assertEqual(oz_rule.canonical_value_text(oz_rule.evaluate(self.NUM, '12.50')), '"12.5"')

    def test_decimal_labels_are_canonical_text(self):
        for bad in ('12.50', '-0', '1e3', '+1', '01', '1.', '.5', '', ' 1', '0.0000000000001', '12.5\n'):
            with self.subTest(label=bad):
                self.assertFalse(oz_rule.label_ok({'type': 'decimal', 'value': bad}))
        self.assertFalse(oz_rule.label_ok({'type': 'decimal', 'value': 12.5}))
        for good in ('0', '12.5', '-3', '0.000000000001', '1' + '0' * 38):
            with self.subTest(label=good):
                self.assertTrue(oz_rule.label_ok({'type': 'decimal', 'value': good}))

    def test_decimal_labels_ignore_input_numeral_limits(self):
        # 10**38 has 39 plain digits, more than an input numeral may carry, but it is a valid result and a valid label
        self.assertTrue(oz_rule.canonical_decimal_label('1' + '0' * 38))
        self.assertFalse(oz_rule.canonical_decimal_label('1' + '0' * 38 + '1'))
        self.assertFalse(oz_rule.canonical_decimal_label('9' * 39))
        self.assertEqual(oz_rule.evaluate(oz_rule_ast(['add', ['d', '9' * 38], ['d', '1']]), '')['value'], '1' + '0' * 38)


def oz_rule_ast(expr):
    return json.dumps({'lang': 'oz-rule/1', 'expr': expr}).encode()


class ParityWithAkor(unittest.TestCase):
    """The locally re-implemented builtins agree with oz_accept on sample values (skipped if it cannot be imported)."""

    def test_parity(self):
        try:
            import oz_accept
        except Exception as exc:  # pragma: no cover
            self.skipTest('oz_accept unavailable: %r' % (exc,))
        local = reg.LocalChecks()
        samples = ['abc', '', ' ', 'a b', 1, 12.5, True, None, ['a'], [], {'k': 'abc'}, {'k': ' '}]
        specs = [({'check': 'json_type', 'types': ['string']}, {'types': ['string']}),
                 ({'check': 'json_type', 'types': ['number', 'null']}, {'types': ['number', 'null']}),
                 ({'check': 'json_type', 'types': ['integer']}, {'types': ['integer']}),
                 ({'check': 'max_bytes', 'bytes': 5}, {'bytes': 5}),
                 ({'check': 'one_of', 'values': ['abc', 1, True]}, {'values': ['abc', 1, True]}),
                 ({'check': 'quoted_span'}, {}),
                 ({'check': 'quoted_span', 'field': 'k'}, {'field': 'k'}),
                 ({'check': 'expect', 'value': 'abc'}, {'value': 'abc'})]
        for spec, params in specs:
            name = spec['check']
            check = oz_accept.REGISTRY[name]
            for v in samples:
                with self.subTest(check=name, value=repr(v)):
                    inputs = oz_accept.Inputs(({'op': 'x', 'refs': [json.dumps('abc def')]},))
                    want = check.run(v, dict(spec, version=1), inputs)
                    self.assertEqual(local.run(name, 1, params, v, 'abc def'), want)
        self.assertEqual({n for n, _ in reg.LocalChecks._TABLE} - {'rule_provenance'}, set(oz_accept.REGISTRY))
        for name, flag in (('quoted_span', True), ('expect', False), ('one_of', False)):
            self.assertEqual(local.describe(name, 1)['input_bound'], flag)

    def test_describe_is_stable(self):
        a, b = reg.LocalChecks().describe('one_of', 1), reg.LocalChecks().describe('one_of', 1)
        self.assertEqual(a, b)
        self.assertEqual(len(a['impl_digest']), 64)
        self.assertIsNone(reg.LocalChecks().describe('one_of', 2))
        self.assertEqual(reg.LocalChecks().describe('rule_provenance', 1)['kind'], 'provenance')


if __name__ == '__main__':
    unittest.main()
