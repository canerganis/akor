"""G3b focused tests: the exact-trace oracle, the pass_g3b predicate and its one binding label, per-call thinking tokens,
the allocation, the fresh freeze (live1's record intact), the read-only live1 replay and the live command guards.
The oracle and predicate tests are pure (synthetic dispatch records); the integration tests use the oracle fixture
adapter, so nothing is paid."""
import ast
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'bench' / 'step4'))
sys.path.insert(0, str(ROOT))

import g3b as G  # noqa: E402
import step4 as S  # noqa: E402
import workflow as W  # noqa: E402
import test_oz_flow as T  # noqa: E402

PLAN = ROOT / 'docs' / 'design' / 'step4-2026-10-23' / 'g3b' / 'plan-frozen.md'
LIVE1 = ROOT / 'bench' / 'step4' / 'live1'
OLD_FREEZE = W.FROZEN / 'freeze.json'
ABCD = 'ABCD'


def ids(op, names=ABCD):
    return [f'{op}_{n}' for n in names]


CLOCK = itertools.count(1000)


def dispatch(scenario, stage, jobs, attempt=1, verdicts=None, generation=1, refs=None, receipt=None):
    """A recorded dispatch with current inputs, launched after the previous one. `verdicts` is the story, in the
    independent vocabulary (accepted by default, check_rejected, wire_rejected, model_error, call_failed, held); the
    executor's own verdicts and the preserved evidence are what an honest executor would have left for it."""
    story = {j: (verdicts or {}).get(j, 'accepted') for j in jobs}
    executor, evidence = S.synthetic_facts(scenario, stage, jobs, story)
    return {'stage': stage, 'op': jobs[0].split('_')[0], 'receipt': receipt or f'{stage}.{attempt}.{"+".join(jobs)}',
            'created_at': float(next(CLOCK)),
            'members': [{'id': j, 'generation': generation, 'attempt': attempt, 'compute_key': 'k-' + j} for j in jobs],
            'refs': dict({j: G.expected_text(scenario, stage, j) for j in jobs}, **(refs or {})),
            'verdicts': executor, 'evidence': evidence}


def renumbered(trace):
    """Launch times in trace order (after a test reordered the dispatches)."""
    for i, d in enumerate(trace):
        d['created_at'] = float(i)
    return trace


def clean_trace(rejected=(), kind='check_rejected', scenario='clean'):
    """extract, bounds, classify with `rejected` classify members, recovered by the derived resends."""
    trace = [dispatch(scenario, 0, ids('extract')), dispatch(scenario, 1, ids('bounds')),
             dispatch(scenario, 2, ids('classify'), verdicts={j: kind for j in rejected})]
    rejected = list(rejected)
    if len(rejected) == 4:
        trace.append(dispatch(scenario, 2, rejected, attempt=2))
    else:
        trace += [dispatch(scenario, 2, [j], attempt=2) for j in rejected]
    return trace


def stale_trace(rejected=()):
    trace = [dispatch('stale', 0, ids('extract')), dispatch('stale', 1, ids('bounds')),
             dispatch('stale', 2, ['extract_A']), dispatch('stale', 3, ['bounds_A']),
             dispatch('stale', 4, ids('classify'), verdicts={j: 'check_rejected' for j in rejected})]
    return trace + [dispatch('stale', 4, [j], attempt=2) for j in rejected]


def obs(trace, scenario='clean', **over):
    entry = G.workflow_entry(scenario)
    base = {'scenario': scenario, 'entry': entry, 'status': 'delivered', 'deliveries': 1, 'on_time': True,
            'evaluator_errors': [], 'memo_hits': entry['expected_memo_hits'], 'trace': trace, 'ledger_ok': True,
            'calls_without_usage': 0, 'per_flow_cap': 10, 'observables': None, 'fixture_invocations': None}
    base.update(over)
    return base


def codes(trace, scenario='clean', cap=10):
    return {e['code'] for e in G.trace_errors(scenario, trace, cap)[0]}


class DerivationTests(unittest.TestCase):
    def test_the_primary_table_equals_workflow_json_for_every_scenario(self):
        for name in G.config()['scenarios']:
            row = G.workflow_entry(name)
            sequence, blocked = G.derive(name, {})
            self.assertEqual([len(members) for _, members, _ in sequence], row['expected_packets'], name)
            self.assertEqual(len(sequence), row['expected_launches'], name)
            self.assertTrue(all(attempt == 1 for _, _, attempt in sequence))
            self.assertIsNone(blocked)

    def test_packet_sizes_are_the_largest_allowed_that_fits(self):
        self.assertEqual([G.plan_sizes(n, (4, 1)) for n in range(5)], [[], [1], [1, 1], [1, 1, 1], [4]])

    def test_rejected_members_are_resent_alone_in_job_order_before_the_next_stage(self):
        verdicts = {(1, 'bounds_B', 1): 'check_rejected', (1, 'bounds_D', 1): 'check_rejected'}
        sequence, blocked = G.derive('clean', verdicts)
        self.assertEqual(sequence[1:5], [(1, tuple(ids('bounds')), 1), (1, ('bounds_B',), 2), (1, ('bounds_D',), 2),
                                         (2, tuple(ids('classify')), 1)])
        self.assertIsNone(blocked)

    def test_a_wire_rejected_packet_is_one_whole_resend_when_all_four_members_are_pending(self):
        verdicts = {(2, j, 1): 'wire_rejected' for j in ids('classify')}
        sequence, _ = G.derive('clean', verdicts)
        self.assertEqual(sequence[-1], (2, tuple(ids('classify')), 2))
        self.assertEqual(len(sequence), 4)

    def test_a_second_rejection_ends_the_derivation_unresolved_with_no_third_attempt(self):
        verdicts = {(2, 'classify_C', 1): 'check_rejected', (2, 'classify_C', 2): 'check_rejected'}
        sequence, blocked = G.derive('clean', verdicts)
        self.assertEqual(sequence[-1], (2, ('classify_C',), 2))
        self.assertEqual(blocked['exhausted'], ['classify_C'])

    def test_a_held_member_is_never_resent_and_blocks_the_stage(self):
        sequence, blocked = G.derive('clean', {(2, 'classify_A', 1): 'held'})
        self.assertEqual(len(sequence), 3)
        self.assertEqual(blocked['held'], ['classify_A'])

    def test_a_verdict_never_recorded_is_not_invented_into_a_rejection(self):
        self.assertEqual(G.derive('clean', {})[0], G.derive('clean', {(2, 'classify_A', 1): 'accepted'})[0])

    def test_stale_derivation_has_five_primary_packets_and_resends_stay_inside_their_stage(self):
        verdicts = {(2, 'extract_A', 1): 'check_rejected', (4, 'classify_C', 1): 'check_rejected'}
        sequence, _ = G.derive('stale', verdicts)
        self.assertEqual([(s, a) for s, _, a in sequence], [(0, 1), (1, 1), (2, 1), (2, 2), (3, 1), (4, 1), (4, 2)])


class EligibilityTests(unittest.TestCase):
    def test_the_derived_traces_have_no_findings(self):
        for rejected in ((), ('classify_A', 'classify_C'), tuple(ids('classify')[:3]), tuple(ids('classify'))):
            self.assertEqual(G.trace_errors('clean', clean_trace(rejected), 10)[0], [], rejected)
        self.assertEqual(G.trace_errors('clean', clean_trace(ids('classify'), 'wire_rejected'), 10)[0], [])
        self.assertEqual(G.trace_errors('clean', clean_trace(['classify_B'], 'model_error'), 10)[0], [])
        self.assertEqual(G.trace_errors('stale', stale_trace(['classify_C']), 10)[0], [])

    def test_whole_packet_resend_is_caught_twice(self):
        trace = clean_trace(['classify_A', 'classify_C'])[:3] + [dispatch('clean', 2, ids('classify'), attempt=2)]
        self.assertEqual(codes(trace), {'accepted_member_resent', 'trace_mismatch'})

    def test_resend_of_an_accepted_sibling_is_caught(self):
        trace = clean_trace(['classify_A']) + [dispatch('clean', 2, ['classify_B'], attempt=2)]
        self.assertIn('accepted_member_resent', codes(trace))

    def test_a_size_two_resend_is_eligible_but_not_the_exact_trace(self):
        trace = clean_trace(['classify_A', 'classify_C'])[:3] + [
            dispatch('clean', 2, ['classify_A', 'classify_C'], attempt=2)]
        self.assertEqual(codes(trace), {'trace_mismatch'})

    def test_a_third_attempt_is_caught(self):
        trace = clean_trace(['classify_A'])
        S._restory(trace[3], 'clean', classify_A='check_rejected')
        trace.append(dispatch('clean', 2, ['classify_A'], attempt=3))
        self.assertIn('third_attempt', codes(trace))

    def test_a_skipped_resend_then_delivery_is_caught_only_by_the_exact_trace(self):
        self.assertEqual(codes(clean_trace(['classify_A', 'classify_C'])[:-1]), {'trace_mismatch'})

    def test_resends_in_another_order_are_caught(self):
        trace = clean_trace(['classify_A', 'classify_C'])
        trace[3], trace[4] = trace[4], trace[3]
        self.assertEqual(codes(renumbered(trace)), {'trace_mismatch'})

    def test_a_wrong_generation_or_computation_is_caught(self):
        trace = clean_trace(['classify_A'])
        trace[3]['members'][0]['generation'] = 2
        self.assertIn('generation_mismatch', codes(trace))
        trace = clean_trace(['classify_A'])
        trace[3]['members'][0]['compute_key'] = 'other'
        self.assertIn('identity_mismatch', codes(trace))

    def test_stale_inputs_are_caught_in_a_resend_and_after_the_mutation(self):
        trace = clean_trace(['classify_A'])
        trace[3]['refs']['classify_A'] = G.expected_text('stale', 4, 'classify_A')
        self.assertIn('stale_input', codes(trace))
        trace = stale_trace()
        trace[4]['refs']['classify_A'] = G.expected_text('clean', 2, 'classify_A')  # old A bytes after the mutation
        self.assertIn('stale_input', codes(trace, 'stale'))

    def test_a_resend_without_recorded_grounds_or_prior_attempt_is_caught(self):
        trace = clean_trace(['classify_A'])
        trace[3]['members'][0]['attempt'] = 1
        self.assertIn('attempt_sequence', codes(trace))
        orphan = [dispatch('clean', 0, ids('extract')), dispatch('clean', 0, ['extract_A'], attempt=2)]
        self.assertIn('accepted_member_resent', codes(orphan))
        self.assertIn('no_prior_attempt', codes([dispatch('clean', 0, ['extract_A'], attempt=2)]))

    def test_exhausted_quota_is_a_launch_beyond_the_scenario_cap(self):
        trace = clean_trace(['classify_A']) + [dispatch('clean', 2, ['classify_A'], attempt=2, receipt=f'q{i}')
                                               for i in range(8)]
        self.assertIn('launch_cap_exceeded', codes(trace))
        self.assertNotIn('launch_cap_exceeded', codes(clean_trace(['classify_A', 'classify_C']), cap=5))
        self.assertIn('launch_cap_exceeded', codes(clean_trace(['classify_A', 'classify_C']), cap=4))

    def test_a_verifier_outage_never_triggers_a_resend_or_a_regeneration(self):
        held = [dispatch('clean', 0, ids('extract')), dispatch('clean', 1, ids('bounds')),
                dispatch('clean', 2, ids('classify'), verdicts={j: 'held' for j in ids('classify')})]
        self.assertEqual(G.trace_errors('clean', held, 10)[0], [])
        self.assertIn('held_member_resent', codes(held + [dispatch('clean', 2, ids('classify'), attempt=2)]))
        self.assertIn('generation_mismatch', codes(held + [dispatch('clean', 2, ids('classify'), generation=2)]))
        verdict = G.scenario_verdict(obs(held, status='incomplete', deliveries=0))
        self.assertFalse(verdict['pass_g3b'])
        self.assertFalse(verdict['checks']['no_unresolved_stage'])

    def test_wire_rejection_must_be_atomic(self):
        trace = clean_trace(ids('classify'), 'wire_rejected')
        trace[2]['verdicts']['classify_A'] = 'accepted'  # a candidate for A out of a reply that is refused whole
        trace[2]['evidence']['candidates']['classify_A'] = {'status': 'accepted', 'value': '"inside"'}
        self.assertIn('wire_rejection_not_atomic', codes(trace))

    def test_an_unrecorded_verdict_is_a_finding(self):
        trace = clean_trace()
        trace[0]['verdicts'].pop('extract_A')
        self.assertIn('verdict_unrecorded', codes(trace))


class IndependentVerdictTests(unittest.TestCase):
    """The predicate judges every stored candidate against the frozen expected values and re-parses every preserved
    capture itself; any disagreement with the executor's own record fails pass_g3b with a reason."""

    def verdict(self, trace, scenario='clean', **over):
        return G.scenario_verdict(obs(trace, scenario, **over))

    def findings(self, trace, scenario='clean'):
        return [e for e in G.trace_errors(scenario, trace, 10)[0] if e['code'] in G.INDEPENDENCE_CODES]

    def test_expected_values_come_from_the_frozen_table_at_the_revision_in_force(self):
        self.assertEqual(G.expected_value('clean', 2, 'classify_A'), 'inside')
        self.assertEqual(G.expected_value('stale', 1, 'bounds_A'), ['12.48 mm', '12.52 mm'])
        self.assertEqual(G.expected_value('stale', 3, 'bounds_A'), ['12.53 mm', '12.57 mm'])
        self.assertEqual(G.expected_value('stale', 4, 'classify_A'), 'outside')
        self.assertEqual(G.expected_value('stale', 4, 'classify_B'), 'outside')
        self.assertEqual(G.expected_value('clean', 0, 'extract_D')[1], 'unknown')

    def test_an_executor_that_rejects_a_correct_answer_fails_the_scenario(self):
        trace = clean_trace()
        trace[2]['verdicts']['classify_B'] = 'check_rejected'  # the executor's check rejected a correct B ...
        trace[2]['evidence']['candidates']['classify_B']['status'] = 'rejected'
        trace.append(dispatch('clean', 2, ['classify_B'], attempt=2))  # ... and B was resent
        verdict = self.verdict(trace)
        self.assertFalse(verdict['pass_g3b'])
        self.assertFalse(verdict['checks']['independent_verdicts'])
        found = [e for e in verdict['errors'] if e['code'] == 'verdict_disagreement']
        self.assertEqual((found[0]['job'], found[0]['executor'], found[0]['independent']),
                         ('classify_B', 'check_rejected', 'accepted'))
        self.assertIn('differs', found[0]['reason'])

    def test_an_executor_that_accepts_a_wrong_answer_fails_the_scenario(self):
        trace = clean_trace()
        trace[1]['evidence']['candidates']['bounds_C']['value'] = '["12.50 mm","12.53 mm"]'
        verdict = self.verdict(trace)
        self.assertFalse(verdict['pass_g3b'])
        self.assertEqual([(e['job'], e['executor'], e['independent']) for e in verdict['errors']
                          if e['code'] == 'verdict_disagreement'], [('bounds_C', 'accepted', 'check_rejected')])

    def test_a_wire_rejection_is_believed_only_when_the_preserved_capture_is_refused_whole(self):
        trace = clean_trace(ids('classify'), 'wire_rejected')
        self.assertEqual(self.findings(trace), [])
        self.assertEqual(set(G.annotate('clean', trace)[2]['independent'].values()), {'wire_rejected'})
        valid = clean_trace(ids('classify'), 'wire_rejected')  # the same claim, but the preserved reply is a valid one
        valid[2]['evidence'] = clean_trace()[2]['evidence']
        valid[2]['evidence']['candidates'] = {}
        found = self.findings(valid)
        self.assertEqual({e['code'] for e in found}, {'verdict_disagreement'})
        self.assertIn('valid result line', found[0]['reason'])
        self.assertFalse(self.verdict(valid)['pass_g3b'])

    def test_a_model_error_line_is_labeled_as_one_and_still_a_rejection(self):
        trace = clean_trace(['classify_B'], 'model_error')
        self.assertEqual(self.findings(trace), [])
        independent = G.annotate('clean', trace)[2]['independent']
        self.assertEqual((independent['classify_B'], independent['classify_A']), ('model_error', 'accepted'))
        self.assertEqual(trace[2]['verdicts']['classify_B'], 'no_candidate')  # the executor's columns cannot say which
        self.assertTrue(self.verdict(trace)['pass_g3b'])  # the verdict rule is unchanged: rejected, resent once
        first = {f['job']: f['verdict'] for f in G.recovery_report(G.annotate('clean', trace))['first_attempt']}
        self.assertEqual(first['classify_B'], 'model_error')
        self.assertNotIn('wire_rejected', json.dumps(G.annotate('clean', trace)[2]['independent']))

    def test_a_failed_call_is_read_from_the_capture(self):
        trace = clean_trace(ids('classify'), 'call_failed')  # the whole packet's call failed, then it was resent whole
        self.assertEqual(self.findings(trace), [])
        self.assertEqual(set(G.annotate('clean', trace)[2]['independent'].values()), {'call_failed'})
        self.assertTrue(self.verdict(trace)['pass_g3b'])
        trace[2]['verdicts']['classify_A'] = 'no_candidate'  # the executor calls it a refused reply: the capture disagrees
        self.assertEqual({e['code'] for e in self.findings(trace)}, {'verdict_disagreement'})

    def test_a_candidate_must_be_the_value_in_the_preserved_reply(self):
        trace = clean_trace()
        trace[0]['evidence']['candidates']['extract_B']['value'] = json.dumps(G.expected_value('clean', 0, 'extract_A'))
        self.assertEqual({e['code'] for e in self.findings(trace)}, {'verdict_disagreement', 'candidate_reply_mismatch'})
        error = clean_trace(['classify_B'], 'model_error')
        error[2]['evidence']['candidates']['classify_B'] = {'status': 'accepted', 'value': '"outside"'}
        error[2]['verdicts']['classify_B'] = 'accepted'
        self.assertIn('candidate_reply_mismatch', {e['code'] for e in self.findings(error)})

    def test_missing_evidence_or_an_unpreserved_capture_never_passes(self):
        trace = clean_trace()
        del trace[0]['evidence']
        self.assertIn('independent_evidence_missing', {e['code'] for e in self.findings(trace)})
        self.assertFalse(self.verdict(trace)['pass_g3b'])
        trace = clean_trace(ids('classify'), 'wire_rejected')
        trace[2]['evidence']['capture'] = None  # a refusal that cannot be re-parsed is not believed
        self.assertIn('capture_not_preserved', {e['code'] for e in self.findings(trace)})
        self.assertFalse(self.verdict(trace)['pass_g3b'])

    def test_unknown_candidate_statuses_and_labels_fail(self):
        trace = clean_trace()  # a late reply left a 'superseded' candidate; the executor mapped it to 'stale'
        trace[2]['verdicts']['classify_D'] = 'unknown_status:superseded'
        trace[2]['evidence']['candidates']['classify_D']['status'] = 'superseded'
        found = self.findings(trace)
        self.assertEqual([(e['code'], e['job']) for e in found], [('unknown_status', 'classify_D')])
        self.assertFalse(self.verdict(trace)['pass_g3b'])
        trace = clean_trace()
        trace[2]['verdicts']['classify_D'] = 'stale'
        self.assertEqual([e['code'] for e in self.findings(trace)], ['unknown_status'])
        self.assertFalse(self.verdict(trace)['pass_g3b'])

    def test_a_held_candidate_is_independently_held_and_never_resent(self):
        held = clean_trace()[:2] + [dispatch('clean', 2, ids('classify'), verdicts={j: 'held' for j in ids('classify')})]
        self.assertEqual(self.findings(held), [])
        self.assertEqual(set(G.annotate('clean', held)[2]['independent'].values()), {'held'})

    def test_launch_order_is_checked_across_stages(self):
        trace = clean_trace(['classify_A'])
        self.assertNotIn('launch_order', codes(trace))
        early = [dispatch('clean', 0, ids('extract'), verdicts={'extract_B': 'check_rejected'}),
                 dispatch('clean', 0, ['extract_B'], attempt=2), dispatch('clean', 1, ids('bounds')),
                 dispatch('clean', 2, ids('classify'))]
        self.assertNotIn('launch_order', codes(early))
        early[1]['created_at'] = early[2]['created_at'] + 0.5  # the resend was launched after the bounds packet
        self.assertEqual(codes(early), {'launch_order'})
        verdict = self.verdict(early)
        self.assertFalse(verdict['pass_g3b'])
        self.assertFalse(verdict['checks']['recovery_eligibility'])
        self.assertTrue(verdict['checks']['exact_trace'])  # the stage-grouped sequence looks right: only time says no
        del early[1]['created_at']
        self.assertEqual(codes(early), {'launch_order_unrecorded'})

    def test_the_independent_parser_agrees_with_the_executor_s_on_a_corpus_of_replies(self):
        import oz_reply
        ids4 = ('a', 'b')
        corpus = [
            'OZ/1g\n{"a":1}\n{"b":"x"}', 'OZ/1g\n{"a":1}\n{"b":"x"}\n', '\n \tOZ/1g \t\r\n{"a":1}\r\n{"b":2}\r\n',
            '{"a":1}\n{"b":2}', 'OZ/1g\n{"a":1}', 'OZ/1g\n{"a":1}\n{"b":2}\n{"c":3}', 'OZ/1g\n{"a":1}\n{"a":2}\n{"b":3}',
            'OZ/1g\n{"a":1,"b":2}', 'OZ/1g\n["a","error","missing_data","no value"]\n{"b":2}',
            'OZ/1g\n["a","error","nope","no value"]\n{"b":2}', 'OZ/1g\n["a","error","conflict","  "]\n{"b":2}',
            'OZ/1g\n["a","fail","conflict","x"]\n{"b":2}', 'OZ/1g\n{"a":NaN}\n{"b":2}', 'OZ/1g\n{"a":1,"a":2}\n{"b":2}',
            'OZ/1g\nnot json\n{"b":2}', 'OZ/1g\n[1,2]\n{"b":2}', 'OZ/1g\n{"a":"\\ud800"}\n{"b":2}', 'OZ/1g\n{1:2}',
            'OZ/1g\n{"a":"' + 'x' * 70000 + '"}\n{"b":2}', '', '   \n', None, 7, 'OZ/1g\n\n{"a":1}\n  \n{"b":2}',
            'OZ/1g\n{"a":[1,{"c":null}]}\n{"b":true}', 'OZ/1g\n{"a":"  "}\n{"b":""}']
        for text in corpus:
            theirs = oz_reply.parse_reply(text, ids4) if isinstance(text, str) else None
            mine = G.parse_reply(text, ids4)
            if theirs is None:
                self.assertIsNotNone(mine['rejection'])
                continue
            self.assertEqual(mine['rejection'] is None, theirs.rejection is None, repr(text)[:80])
            if theirs.rejection is None:
                self.assertEqual({k for k, v in mine['lines'].items() if v[0] == 'value'}, set(theirs.accepted))
                self.assertEqual({k for k, v in mine['lines'].items() if v[0] == 'error'}, set(theirs.failed))
        for name in ('HEADER', 'MAX_LINE_BYTES', 'MAX_RESULT_BYTES', 'CAPTURE_SLACK', 'ERROR_CODES', 'USAGE_FIELDS'):
            self.assertEqual(getattr(G, name), getattr(oz_reply, name), name)


class PredicateTests(unittest.TestCase):
    def test_a_failure_free_run_is_a_strict_pass_and_a_recovered_one_is_labeled_recovered(self):
        v = G.scenario_verdict(obs(clean_trace()))
        self.assertEqual((v['pass_g3b'], v['strict_pass'], v['recovered']), (True, True, False))
        v = G.scenario_verdict(obs(clean_trace(['classify_A', 'classify_C'])))
        self.assertEqual((v['pass_g3b'], v['strict_pass'], v['recovered']), (True, False, True))

    def test_each_condition_alone_can_fail_the_scenario(self):
        base = obs(clean_trace(['classify_C']))
        failing = {
            'delivered_once_on_time_verified': [{'status': 'incomplete'}, {'deliveries': 2}, {'on_time': False},
                                                {'evaluator_errors': ['x']}],
            'primary_sequence_and_memo_hits': [{'memo_hits': 1}],
            'one_ledger_call_per_launch_and_complete_usage': [{'ledger_ok': False}, {'calls_without_usage': 1},
                                                              {'fixture_invocations': 99}],
            'within_scenario_launch_cap': [{'per_flow_cap': 3}]}
        for check, edits in failing.items():
            for edit in edits:
                verdict = G.scenario_verdict(dict(base, **edit))
                self.assertFalse(verdict['pass_g3b'], edit)
                self.assertFalse(verdict['checks'][check], edit)

    def test_changed_primary_packets_fail_the_primary_sequence_check(self):
        trace = clean_trace()
        trace[0]['members'] = trace[0]['members'][:3]
        verdict = G.scenario_verdict(obs(trace))
        self.assertFalse(verdict['checks']['primary_sequence_and_memo_hits'])
        self.assertFalse(verdict['pass_g3b'])

    def test_interrupt_and_stale_observables_are_required(self):
        good = {'checks': {'a': True}}
        bad = {'checks': {'a': True, 'b': False}}
        self.assertTrue(G.scenario_verdict(obs(clean_trace(), 'interrupt', observables=good))['pass_g3b'])
        self.assertFalse(G.scenario_verdict(obs(clean_trace(), 'interrupt', observables=bad))['pass_g3b'])
        self.assertFalse(G.scenario_verdict(obs(clean_trace(), 'interrupt'))['pass_g3b'])
        self.assertTrue(G.scenario_verdict(obs(stale_trace(['classify_C']), 'stale', observables=good))['pass_g3b'])
        self.assertFalse(G.scenario_verdict(obs(stale_trace(['classify_C']), 'stale', observables=bad))['pass_g3b'])

    def test_stale_order_after_mutation_is_the_derived_one(self):
        trace = stale_trace(['classify_C'])
        trace[2], trace[3] = trace[3], trace[2]
        verdict = G.scenario_verdict(obs(renumbered(trace), 'stale', observables={'checks': {'a': True}}))
        self.assertFalse(verdict['checks']['stale_order_after_mutation'])

    def test_memo_hit_scenarios_pass_with_no_dispatch_and_fail_with_one(self):
        for name in ('repeat', 'bump'):
            self.assertTrue(G.scenario_verdict(obs([], name))['pass_g3b'])
            self.assertFalse(G.scenario_verdict(obs([dispatch(name, 0, ids('extract'))], name))['pass_g3b'])

    def test_a_second_attempt_failure_is_never_a_pass(self):
        trace = clean_trace(['classify_C'])
        S._restory(trace[3], 'clean', classify_C='check_rejected')
        verdict = G.scenario_verdict(obs(trace, status='incomplete', deliveries=0))
        self.assertFalse(verdict['pass_g3b'])
        self.assertTrue(verdict['checks']['exact_trace'])
        self.assertEqual(verdict['blocked']['exhausted'], ['classify_C'])

    def report(self, **scenario_over):
        rows = {name: {'pass': True, 'pass_g3b': True, 'recovered': False} for name in G.config()['scenarios']}
        for name, over in scenario_over.items():
            rows[name].update(over)
        return {'kind': 'live', 'freeze': {'frozen': True}, 'scenarios': rows, 'c5': {'a': {'pass': True}},
                'totals': {'launches': 20, 'tokens_known': 50000, 'accounting': 'complete'}}

    def test_one_label_binds_the_gate(self):
        self.assertEqual(G.LABEL, 'pass_g3b')
        self.assertTrue(G.suite_verdict(self.report())['pass'])
        # strict pass False but pass_g3b True: the gate passes (a recovered pass)
        self.assertTrue(G.suite_verdict(self.report(interrupt={'pass': False, 'recovered': True}))['pass'])
        # strict pass True but pass_g3b False: the gate fails
        self.assertFalse(G.suite_verdict(self.report(stale={'pass_g3b': False}))['pass'])

    def test_suite_requires_freeze_c5_and_the_allocation(self):
        r = self.report()
        r['freeze'] = {'frozen': False}
        self.assertFalse(G.suite_verdict(r)['pass'])
        r = self.report()
        r['c5'] = {'a': {'pass': False}}
        self.assertFalse(G.suite_verdict(r)['pass'])
        for key, value in (('launches', 25), ('tokens_known', 64001), ('accounting', 'incomplete')):
            r = self.report()
            r['totals'][key] = value
            self.assertFalse(G.suite_verdict(r)['pass'], key)
        r = self.report()
        del r['scenarios']['bump']
        self.assertFalse(G.suite_verdict(r)['pass'])

    def test_the_dry_gate_additionally_needs_recovery_sabotage_and_feasibility(self):
        r = self.report()
        r['kind'] = 'fixture'
        self.assertFalse(G.suite_verdict(r)['pass'])
        r.update(sabotage={'a': {'caught': True}}, recovery={'a': {'pass': True}}, g3b_sabotage={'a': {'caught': True}},
                 feasibility={'a': {'pass': True}}, baseline_smoke={'pass': True})
        self.assertTrue(G.suite_verdict(r)['pass'])
        for key in ('sabotage', 'g3b_sabotage'):
            broken = dict(r, **{key: {'a': {'caught': False}}})
            self.assertFalse(G.suite_verdict(broken)['pass'], key)
        for key in ('recovery', 'feasibility'):
            broken = dict(r, **{key: {'a': {'pass': False}}})
            self.assertFalse(G.suite_verdict(broken)['pass'], key)

    def test_recovery_report_keeps_what_the_verdict_does_not_decide_apart(self):
        calls = [{'attempt': 1, 'tokens': 10, 'thinking_tokens': 0}, {'attempt': 2, 'tokens': 5, 'thinking_tokens': 3}]
        rep = G.recovery_report(clean_trace(['classify_A']), calls)
        self.assertEqual((rep['first_attempt_correct'], rep['first_attempt_total']), (11, 12))
        self.assertEqual((rep['rejected_jobs'], rep['rejected_packets']), (['2:classify_A'], 1))
        self.assertEqual((rep['recovery_launches'], rep['recovery_tokens']), (1, 5))
        self.assertEqual([c['thinking_tokens'] for c in rep['calls']], [0, 3])


class ThinkingTokenTests(unittest.TestCase):
    def test_thinking_tokens_come_from_model_usage_and_unknown_is_not_zero(self):
        envelope = {'modelUsage': {'claude-sonnet-5-5': {'inputTokens': 2, 'outputTokens': 61, 'thinkingTokens': 79}}}
        self.assertEqual(G.envelope_thinking_tokens(envelope), 79)
        envelope['modelUsage']['other'] = {'thinkingTokens': 1}
        self.assertEqual(G.envelope_thinking_tokens(envelope), 80)
        for bad in (None, {}, {'modelUsage': {}}, {'modelUsage': {'m': {}}}, {'modelUsage': {'m': {'thinkingTokens': True}}},
                    {'modelUsage': {'m': {'thinkingTokens': -1}}}, {'modelUsage': {'m': {'thinkingTokens': 3},
                                                                                  'n': {}}}):
            self.assertIsNone(G.envelope_thinking_tokens(bad), bad)


class IntegrationTests(T.FlowFixture):
    def test_each_call_row_carries_thinking_tokens_verdicts_and_ledger_tokens(self):
        self.mode(thinking=7, wrong_first=['classify_C'])
        result = self.run_named('i1')
        self.assertEqual(result['status'], 'delivered')
        trace = S.trace_of(self.ws, 'i1')
        calls = S.calls_of(self.ws, 'i1', trace)
        self.assertEqual([c['members'] for c in calls][-2:], [ids('classify'), ['classify_C']])
        self.assertEqual([c['thinking_tokens'] for c in calls], [7] * 4)
        self.assertEqual([c['attempt'] for c in calls], [1, 1, 1, 2])
        self.assertEqual(calls[2]['verdicts']['classify_C'], 'check_rejected')
        self.assertEqual(sum(c['tokens'] for c in calls), T.flow_usage(self.ws, 'i1')['tokens_known'])
        self.assertEqual(G.trace_errors('clean', trace, 10)[0], [])

    def test_missing_thinking_tokens_are_recorded_as_unknown(self):
        self.mode(no_thinking=True)
        self.run_named('i2')
        calls = S.calls_of(self.ws, 'i2', S.trace_of(self.ws, 'i2'))
        self.assertEqual([c['thinking_tokens'] for c in calls], [None, None, None])

    def test_wire_rejection_is_recorded_without_candidates_and_resent_whole(self):
        self.mode(wire_reject_first=['extract_B'])
        self.run_named('i3')
        trace = S.trace_of(self.ws, 'i3')
        self.assertEqual([d['verdicts']['extract_A'] for d in trace[:2]], ['no_candidate', 'accepted'])  # executor's own
        self.assertEqual([d['independent']['extract_A'] for d in G.annotate('clean', trace)[:2]],
                         ['wire_rejected', 'accepted'])  # re-parsed from the preserved capture
        self.assertEqual([len(d['members']) for d in trace], [4, 4, 4, 4])
        self.assertEqual(G.trace_errors('clean', trace, 10)[0], [])


class RealExecutorTests(unittest.TestCase):
    def test_a_host_check_that_rejects_a_correct_answer_is_not_a_pass(self):
        """The reviewer's first repro: the fixture model answers everything correctly, the executor's own classify
        check wrongly rejects classify_B once, and the resend has no real grounds."""
        from dataclasses import replace
        original, state = W.CHECKS['mat_classify'].run, {'fired': False}

        def buggy(value, spec, inputs):
            ok = original(value, spec, inputs)
            if not state['fired'] and ok and 'length=12.47 mm' in json.dumps(list(inputs.slots), default=str):
                state['fired'] = True
                return False
            return ok
        checks = dict(W.CHECKS, mat_classify=replace(W.CHECKS['mat_classify'], run=buggy))
        with tempfile.TemporaryDirectory() as tmp, S._fixture_env(), patch.object(W, 'CHECKS', checks):
            ws, outs = S.fixture_case(Path(tmp), 'spurious', {}, ['clean'], 'rp')
            out = outs['clean']
            self.assertTrue(state['fired'])
            self.assertEqual(out['status'], 'delivered')
            self.assertEqual([d['members'][0]['id'] for d in out['trace'][3:]], ['classify_B'])  # the spurious resend
            verdict = out['g3b']
            self.assertFalse(verdict['pass_g3b'])
            self.assertFalse(out['pass_g3b'])
            self.assertFalse(verdict['checks']['independent_verdicts'])
            found = [e for e in verdict['errors'] if e['code'] == 'verdict_disagreement']
            self.assertEqual((found[0]['job'], found[0]['executor'], found[0]['independent']),
                             ('classify_B', 'check_rejected', 'accepted'))

    def test_a_resend_launched_after_the_next_stage_is_not_a_pass(self):
        """The reviewer's second repro: the recorded creation time of the extract_B resend is moved past the bounds
        primary packet, so the global launch order is broken while each stage looks fine."""
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp, S._fixture_env():
            ws, outs = S.fixture_case(Path(tmp), 'order', {'wrong_first': ['extract_B']}, ['clean'], 'g3b')
            self.assertTrue(outs['clean']['pass_g3b'])
            runs = S.stage_runs(ws, 'g3b-clean')
            bounds = sqlite3.connect(str(ws / runs[1] / 'inbox.sqlite'))
            primary = min(r[0] for r in bounds.execute('SELECT created_at FROM dispatches'))
            bounds.close()
            extract = sqlite3.connect(str(ws / runs[0] / 'inbox.sqlite'))
            extract.execute("UPDATE dispatches SET created_at=? WHERE receipt='2'", (primary + 0.5,))
            extract.commit()
            extract.close()
            out = S.scenario_report(ws, 'fixture', 'g3b', 'clean')
            self.assertFalse(out['pass_g3b'])
            self.assertIn('launch_order', {e['code'] for e in out['g3b']['errors']})
            self.assertFalse(out['g3b']['checks']['recovery_eligibility'])

    def test_one_call_counted_twice_under_one_call_id_is_a_ledger_problem(self):
        """The reviewer's third repro (a): a call_start line written twice with the same call_id."""
        with tempfile.TemporaryDirectory() as tmp, S._fixture_env():
            ws, outs = S.fixture_case(Path(tmp), 'ledger', {'wrong_first': ['classify_A']}, ['clean'], 'g3b')
            self.assertTrue(S.ledger_audit(ws, 'g3b-clean')['ok'])
            ledger = ws / S.stage_runs(ws, 'g3b-clean')[2] / 'calls.jsonl'
            lines = ledger.read_text(encoding='utf-8').splitlines()
            start = next(x for x in lines if json.loads(x).get('event') == 'call_start')
            ledger.write_text('\n'.join(lines + [start]) + '\n', encoding='utf-8')
            audit = S.ledger_audit(ws, 'g3b-clean')
            self.assertFalse(audit['ok'])
            self.assertIn('counted as 2 calls', ' '.join(audit['problems']))


class LiveReplayTests(unittest.TestCase):
    def tree_digest(self, root):
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(Path(root).rglob('*')) if p.is_file()}

    def test_the_replay_exercises_the_predicate_on_live1_and_is_not_a_verdict(self):
        before = self.tree_digest(LIVE1)
        out = G.replay_live1()
        self.assertEqual(self.tree_digest(LIVE1), before)  # read-only
        self.assertIn('NOT a verdict on live1', out['label'])
        self.assertTrue(out['read_only'])
        self.assertTrue(out['all_traces_match'])
        got = {n: (s['launches'], s['predicate_returned']['strict_pass'], s['predicate_returned']['recovered'],
                   s['eligibility_errors']) for n, s in out['scenarios'].items()}
        self.assertEqual(got, {'clean': (3, True, False, []), 'repeat': (0, True, False, []),
                               'interrupt': (5, False, True, []), 'stale': (6, False, True, []),
                               'bump': (0, True, False, [])})
        self.assertEqual(out['scenarios']['interrupt']['actual'][-2:], [[2, ['classify_A'], 2], [2, ['classify_C'], 2]])
        self.assertEqual(out['scenarios']['stale']['actual'][-1], [4, ['classify_C'], 2])

    def test_the_new_predicate_on_the_retained_live2_evidence_is_read_only_and_not_a_verdict(self):
        live2 = ROOT / 'bench' / 'step4' / 'live2'
        before = self.tree_digest(live2)
        out = G.replay_live2()
        self.assertEqual(self.tree_digest(live2), before)
        self.assertIn('NOT a verdict on live2', out['label'])
        self.assertTrue(out['all_traces_match'])
        self.assertTrue(out['all_independent_verdicts_agree'])  # the independent recheck, built into the predicate
        got = {n: (s['launches'], s['predicate_returned']['pass_g3b'], s['predicate_returned']['strict_pass'],
                   s['predicate_returned']['recovered'], s['eligibility_errors']) for n, s in out['scenarios'].items()}
        self.assertEqual(got, {'clean': (3, True, True, False, []), 'repeat': (0, True, True, False, []),
                               'interrupt': (3, True, True, False, []), 'stale': (6, True, False, True, []),
                               'bump': (0, True, True, False, [])})

    def test_a_status_edit_alone_is_caught_by_the_independent_verdicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'live1'
            shutil.copytree(LIVE1, copy)
            rows = [json.loads(x) for x in (copy / 'candidates.jsonl').read_text(encoding='utf-8').splitlines()]
            for row in rows:  # the executor "rejected" a correct answer
                if row['run'].startswith('live1-interrupt-classify') and row['receipt'] == '3':
                    row['status'] = 'rejected'
            (copy / 'candidates.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
            out = G.replay_live1(copy)['scenarios']['interrupt']
            self.assertFalse(out['predicate_returned']['pass_g3b'])
            self.assertFalse(out['independent_verdicts_agree'])

    def test_the_replay_catches_edited_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'live1'
            shutil.copytree(LIVE1, copy)
            ledger = next(copy.glob('calls-live1-stale-classify-*.jsonl'))
            lines = ledger.read_text(encoding='utf-8').splitlines()
            ledger.write_text('\n'.join(lines[:2]) + '\n', encoding='utf-8')  # drop the singleton resend of classify_C
            out = G.replay_live1(copy)
            self.assertFalse(out['scenarios']['stale']['trace_matches'])
            self.assertFalse(out['scenarios']['stale']['predicate_returned']['pass_g3b'])
            self.assertTrue(out['scenarios']['interrupt']['trace_matches'])
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'live1'
            shutil.copytree(LIVE1, copy)
            rows = [json.loads(x) for x in (copy / 'candidates.jsonl').read_text(encoding='utf-8').splitlines()]
            for row in rows:  # the attempt-2 classification of classify_C in the interrupted run was rejected too
                if row['run'].startswith('live1-interrupt-classify') and row['receipt'] == '3':
                    row['status'], row['value'] = 'rejected', '"outside"'
            (copy / 'candidates.jsonl').write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
            returned = G.replay_live1(copy)['scenarios']['interrupt']['predicate_returned']
            self.assertFalse(returned['pass_g3b'])
            self.assertFalse(returned['checks']['no_unresolved_stage'])

    def test_the_cli_replay_prints_the_same_labeled_output(self):
        for command, label in (('replay-live1', 'NOT a verdict on live1'), ('replay-live2', 'NOT a verdict on live2')):
            with patch('sys.stdout') as out:
                self.assertEqual(S.main([command]), 0)
            text = ''.join(c.args[0] for c in out.write.call_args_list)
            self.assertIn(label, json.loads(text)['label'])


class OracleIndependenceTests(unittest.TestCase):
    def test_g3b_imports_only_the_standard_library(self):
        tree = ast.parse(Path(G.__file__).read_text(encoding='utf-8'))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules |= {a.name.split('.')[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                modules.add((node.module or '').split('.')[0])
        self.assertLessEqual(modules, set(sys.stdlib_module_names), modules)
        self.assertFalse(modules & {'oz', 'oz_flow', 'oz_do', 'oz_runtime', 'oz_worker', 'workflow', 'step4'})


class AllocationAndFreezeTests(unittest.TestCase):
    def test_the_g3b_allocation_is_the_signed_one_and_settings_use_it(self):
        self.assertEqual(G.allocation(), {'max_tokens': 64000, 'max_launches': 24, 'max_launches_per_flow': 10,
                                          'reserve_per_launch': 5000, 'estimate_tokens': 36000})
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(S.settings(Path(tmp), 'fixture', 'ns', quota=None).budget, G.allocation())
        self.assertEqual(S.spec()['budgets']['executor']['max_launches'], 16)  # live1's allocation, kept byte for byte

    def test_the_live1_freeze_record_is_intact_and_the_workload_bytes_are_unchanged(self):
        old = json.loads(OLD_FREEZE.read_text(encoding='utf-8'))
        self.assertEqual(old['digest'], '49115f95b40b7e5d43d39585da5f9d69c903608c3daa0ee03451a96c1c0c7847')
        again = hashlib.sha256(S.J({'frozen': old['frozen'], 'code': old['code']}).encode('utf-8')).hexdigest()
        self.assertEqual(again, old['digest'])
        for name, digest in old['frozen'].items():  # workflow, graph, op texts, sources, expected values, baseline
            self.assertEqual(S.ndigest(ROOT / name), digest, name)

    def test_the_g3b_freeze_is_a_new_record_covering_the_new_files(self):
        new = json.loads(S.FREEZE_FILE.read_text(encoding='utf-8'))
        old = json.loads(OLD_FREEZE.read_text(encoding='utf-8'))
        self.assertNotEqual(new['digest'], old['digest'])
        self.assertIn('bench/step4/inspection-handoff-20-v1/g3b.json', new['frozen'])
        for name in ('bench/step4/g3b.py', 'bench/step4/fixture_adapter.py', 'bench/step4/evaluator.py'):
            self.assertIn(name, new['code'])
        self.assertTrue(S.freeze()['frozen'])
        self.assertNotIn('freeze.json', ' '.join(new['frozen']))

    def test_the_prefix_workspace_and_gate_identity(self):
        ident = G.config()['identity']
        self.assertEqual((ident['prefix'], ident['workspace']), ('live2', '.oz-runtime/step4-live2'))
        self.assertEqual((G.config()['gate'], G.LABEL), ('G3b', 'pass_g3b'))


class LiveGuardTests(unittest.TestCase):
    def run_main(self, argv):
        with patch('sys.stderr'), patch('sys.stdout'):
            return S.main(argv)

    def test_no_reruns_and_no_baseline_calls_under_g3b(self):
        base = ['live', '--workspace', 'ws']
        self.assertEqual(self.run_main(base + ['--only', 'clean']), 2)
        self.assertEqual(self.run_main(base + ['--rerun', '1']), 2)
        self.assertEqual(self.run_main(['baseline', '--workspace', 'ws']), 2)

    def test_a_live_suite_needs_a_fresh_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            self.assertIsNone(S.fresh_refusal(ws))
            (ws / 'flows' / 'old').mkdir(parents=True)
            self.assertIn('not fresh', S.fresh_refusal(ws))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'memo.sqlite').write_bytes(b'')
            self.assertIn('not fresh', S.fresh_refusal(Path(tmp)))
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp) / 'ws'
            S.prepare(ws, 'fixture')
            (ws / 'flows' / 'old').mkdir(parents=True)
            with patch.object(S, 'cli_version', return_value=S.spec()['route']['cli_version']), \
                    patch.object(S, 'freeze', return_value={'frozen': True, 'digest': 'x', 'problems': []}), \
                    patch.object(S, 'prepare'), patch.object(S, 'scenario_report') as run:
                report = S.suite(ws, 'live', 'live2')
            self.assertFalse(run.called)
            self.assertIn('not fresh', report['blocker'])

    def test_the_default_live_prefix_is_the_g3b_one(self):
        with patch.object(S, 'suite', return_value={'pass': True}) as suite, patch('sys.stdout'), \
                patch.dict('os.environ', {'STEP4_LIVE_CONFIRM': '1'}):
            S.main(['live', '--workspace', 'ws'])
        self.assertEqual(suite.call_args.args[2], 'live2')


class PreregistrationTests(unittest.TestCase):
    def test_the_frozen_plan_states_the_command_caps_label_and_expected_launches(self):
        text = PLAN.read_text(encoding='utf-8')
        for needle in ('bench/step4/step4.py live --workspace .oz-runtime/step4-live2 --prefix live2',
                       'STEP4_LIVE_CONFIRM', '64,000 tokens', '24 launches', '10 per scenario', '5,000',
                       'pass_g3b', 'freeze-g3b.json', S.freeze()['digest']):
            self.assertIn(needle, text, needle)
        for row in S.spec()['scenarios']:
            self.assertIn(f"`live2-{row['name']}`", text)

    def test_the_second_label_of_the_live1_plan_is_retired_everywhere(self):
        self.assertIn('retired', PLAN.read_text(encoding='utf-8'))
        for module in (S, G):
            self.assertNotIn('pass_with_recorded_rejections', Path(module.__file__).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()


class AllocationSourceTests(unittest.TestCase):
    def test_no_g3b_path_reads_the_live1_executor_budget(self):
        root = Path(__file__).resolve().parents[1] / 'bench' / 'step4'
        for name in ('g3b.py', 'step4.py'):
            text = (root / name).read_text(encoding='utf-8')
            self.assertNotIn("['budgets']['executor']", text, name)
            self.assertNotIn('["budgets"]["executor"]', text, name)
