"""oz1g-selective-v1, candidate and check persistence, conditional commitment, bounded recovery and the durable dispatch
journal (foundation record 2026-10-23, clauses 1, 2, 3 and 5; step 3). Fault injection without any model."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oz import Channel, Error, Reference
from oz_accept import REGISTRY, SELECTIVE, Check, Unavailable, compute_key, decide, job_inputs
from oz_batch import render
from oz_do import do
from oz_reply import Failure, encode_reply
from oz_runner import done_path, process_identity, request_path
from oz_runtime import Inbox
from oz_worker import RUNNER, StdioAdapter, Worker
from oz_workspace import initialize
from test_oz_do import FAKE as DO_FAKE, request as do_request
from wire_helpers import job_ids

CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}
RIGHT = {'a': '12.50 mm', 'b': '12.47 mm', 'c': '9.00 mm', 'd': 'next'}


def channel(goal='Report lengths.', first='length=12.50 mm'):
    refs = [Reference(1, 'fact', first, 'lab#1'), Reference(2, 'fact', 'length=12.47 mm', 'lab#2'),
            Reference(3, 'fact', 'length=9.00 mm', 'lab#3')]
    return Channel(session='s', task='t', revision=1, sender='caller', recipient='worker', goal=goal,
                   references=refs, active=1)


class Crash(BaseException):
    """A coordinator or runner dying mid-call (not an ordinary adapter error)."""


class Fake:
    """Adapter answering each packet job from values (a Failure value becomes an error line). hook(request) runs
    first; edit(text) may corrupt the reply text."""

    def __init__(self, values=None, hook=None, edit=None, crash=False):
        self.values, self.hook, self.edit, self.crash, self.calls = dict(values or RIGHT), hook, edit, crash, []

    def __call__(self, request):
        self.calls.append(list(job_ids(request['prompt'])))
        if self.hook:
            self.hook(request)
        if self.crash:
            raise Crash()
        text = encode_reply({pid: self.values[pid] for pid in job_ids(request['prompt'])})
        return {'reply': self.edit(text) if self.edit else text, 'usage': {'input_tokens': 50, 'output_tokens': 5}}


def reply_for(ids, values):
    return {'reply': encode_reply({i: values[i] for i in ids}), 'usage': {'input_tokens': 50, 'output_tokens': 5}}


class Base(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.ch = channel()
        self.box = Inbox(clock=lambda: self.now[0])
        self.addCleanup(self.box.close)

    def post(self, mid, wire, checks=None, profile=SELECTIVE, box=None, **kw):
        return (box or self.box).post(self.ch, mid, wire, binding=self.ch.binding, profile=profile, checks=checks,
                                      **kw)

    def worker(self, adapter, box=None, **kw):
        return Worker(box or self.box, self.ch, adapter, counters=[len], max_tokens=100000, capabilities=CAPS,
                      retry_delay=0, **kw)

    def state(self, mid):
        return self.box.records([mid])[mid]['state']

    def events(self, mid, name):
        return sum(1 for e in self.box.history(mid) if e['event'] == name)


class ProfileTests(Base):
    def test_default_header_jobs_take_the_shipped_path_and_journal_nothing(self):
        for mid, wire in (('a', '=1'), ('b', '=2')):
            self.post(mid, wire, profile='oz1g-header')
        result = self.worker(Fake()).run_once()
        self.assertEqual(result['outcomes'], {'a': 'ok', 'b': 'ok'})
        self.assertNotIn('dispatch', result)
        self.assertEqual((self.box.dispatches(), self.box.candidates()), ([], []))

    def test_profile_and_checks_are_pinned_into_the_job_identity(self):
        self.assertTrue(self.post('a', '=1', [{'check': 'quoted_span'}]))
        self.assertFalse(self.post('a', '=1', [{'check': 'quoted_span', 'version': 1}]))
        for kwargs in ({'checks': None}, {'checks': [{'check': 'expect', 'value': 1}]},
                       {'profile': 'oz1g-header', 'checks': None}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(Error, 'different contents'):
                self.post('a', '=1', **kwargs)
        for checks, profile in (([{'check': 'quoted_span'}], 'oz1g-header'), ([{'check': 'nope'}], SELECTIVE),
                                ([{'check': 'max_bytes', 'bytes': 0}], SELECTIVE),
                                ([{'check': 'json_type', 'types': ['float']}], SELECTIVE),
                                ([{'check': 'quoted_span', 'version': 2}], SELECTIVE), (None, 'oz1g-atomic')):
            with self.subTest(checks=checks, profile=profile), self.assertRaises(Error):
                self.post('z', '=1', checks, profile)

    def test_without_checks_the_selective_profile_reproduces_every_header_outcome(self):
        # Annex A: with no added checks or containment triggers, same outcomes, errors and parser limits.
        def cut(text):
            return text[:-5]

        edits = {
            'clean': None,
            'job_failure': None,
            'malformed_extra_line': lambda t: t + '\n{"a" 1}',
            'unknown_id': lambda t: t + '\n{"ghost":"x"}',
            'missing_line': lambda t: t.rsplit('\n', 1)[0],
            'truncated_mid_record': cut,
            'duplicate_id': lambda t: t + '\n' + t.split('\n')[1],
            'conflicting_duplicate': lambda t: t + '\n{"a":"other"}',
            'no_header': lambda t: t.split('\n', 1)[1],
            'line_over_parser_limit': lambda t: t.replace('"9.00 mm"', '"' + 'x' * 70000 + '"'),
        }
        for name, edit in edits.items():
            with self.subTest(case=name):
                seen = {}
                for profile in ('oz1g-header', SELECTIVE):
                    box = Inbox(clock=lambda: self.now[0])
                    self.addCleanup(box.close)
                    for mid, wire in (('a', '=1'), ('b', '=2'), ('c', '=3')):
                        self.post(mid, wire, profile=profile, box=box)
                    values = dict(RIGHT, b=Failure('missing_data', 'no length')) if name == 'job_failure' else RIGHT
                    result = self.worker(Fake(values, edit=edit), box=box).run_once()
                    rows = {k: (v['state'], v['attempts'], v['result'], v['result_json'], v['error'])
                            for k, v in box.records('abc').items()}
                    seen[profile] = (result['outcomes'], rows)
                    if profile == SELECTIVE and name not in ('clean', 'job_failure'):
                        self.assertEqual(box.candidates(), [])
                self.assertEqual(seen['oz1g-header'], seen[SELECTIVE])


class AcceptanceTests(Base):
    def test_one_oracle_wrong_value_keeps_job_bound_siblings_and_only_that_job_retries(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        self.post('b', '=2', [{'check': 'expect', 'value': '12.47 mm'}])
        self.post('c', '=3', [{'check': 'expect', 'value': '9.00 mm'}])
        fake = Fake(dict(RIGHT, b='12.40 mm'))
        worker = self.worker(fake)
        self.assertEqual(worker.run_once()['outcomes'], {'a': 'ok', 'b': 'retry', 'c': 'ok'})
        fake.values['b'] = '12.47 mm'
        self.assertEqual(worker.run_once()['outcomes'], {'b': 'ok'})
        self.assertEqual(fake.calls, [['a', 'b', 'c'], ['b']])
        self.assertEqual([self.state(m) for m in 'abc'], ['done'] * 3)
        b = self.box.candidates(job='b')
        self.assertEqual([(c['status'], c['reason']) for c in b], [('rejected', 'check failed: expect'),
                                                                    ('accepted', None)])
        self.assertTrue(b[0]['suspect'])
        self.assertEqual(self.events('a', 'done'), 1)

    def test_suspect_reply_quarantines_siblings_without_job_bound_evidence_and_redispatches_them(self):
        self.post('a', '=1', [{'check': 'expect', 'value': '12.50 mm'}])
        self.post('b', '=2', [{'check': 'expect', 'value': '12.47 mm'}])
        self.post('c', '=3', [{'check': 'json_type', 'types': ['string']}])
        fake = Fake(dict(RIGHT, b='9.00 mm'))
        worker = self.worker(fake)
        self.assertEqual(worker.run_once()['outcomes'], {'a': 'ok', 'b': 'retry', 'c': 'retry'})
        c = self.box.candidates(job='c')[0]
        self.assertEqual((c['status'], c['suspect']), ('quarantined', True))
        self.assertEqual(self.box.records(['c'])['c']['error'][:12], 'quarantined:')
        fake.values['b'] = '12.47 mm'
        # Redispatched without caller action, inside the authorized allowance; c now commits in a clean reply.
        self.assertEqual(worker.run_once()['outcomes'], {'b': 'ok', 'c': 'ok'})
        self.assertEqual(fake.calls, [['a', 'b', 'c'], ['b', 'c']])

    def test_valid_looking_id_swap_fails_both_records_and_commits_neither(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        self.post('b', '=2', [{'check': 'quoted_span'}])
        fake = Fake(dict(RIGHT, a='12.47 mm', b='12.50 mm'))
        self.assertEqual(self.worker(fake).run_once()['outcomes'], {'a': 'retry', 'b': 'retry'})
        self.assertEqual([c['status'] for c in self.box.candidates()], ['rejected', 'rejected'])
        self.assertEqual(self.box.stats(), {'pending': 2})

    def test_wire_faults_commit_no_candidate_even_when_checks_would_pass(self):
        for edit in (lambda t: t[:-3], lambda t: t + '\n' + t.split('\n')[1], lambda t: t + '\n["a","oops"]'):
            box = Inbox(clock=lambda: self.now[0])
            self.addCleanup(box.close)
            self.post('a', '=1', [{'check': 'quoted_span'}], box=box)
            self.post('b', '=2', [{'check': 'quoted_span'}], box=box)
            self.assertEqual(self.worker(Fake(edit=edit), box=box).run_once()['outcomes'],
                             {'a': 'retry', 'b': 'retry'})
            self.assertEqual((box.candidates(), box.stats()), ([], {'pending': 2}))

    def test_valid_model_failure_record_decides_its_job(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        self.post('b', '=2', [{'check': 'quoted_span'}])
        fake = Fake(dict(RIGHT, a=Failure('missing_data', 'no length')))
        self.assertEqual(self.worker(fake).run_once()['outcomes'], {'a': 'failed', 'b': 'ok'})
        row = self.box.db.execute("SELECT state,failure_kind,error FROM jobs WHERE id='a'").fetchone()
        self.assertEqual(tuple(row), ('failed', 'model_failure', 'missing_data: no length'))
        self.assertEqual(self.worker(fake).run_once()['status'], 'idle')

    def test_tighter_operation_limit_is_a_per_job_check_after_the_parser(self):
        self.post('a', '=1', [{'check': 'max_bytes', 'bytes': 4}])
        self.post('b', '=2', [{'check': 'max_bytes', 'bytes': 100}])
        self.assertEqual(self.worker(Fake()).run_once()['outcomes'], {'a': 'retry', 'b': 'ok'})

    def flaky(self, down):
        def run(value, spec, inputs):
            if down[0] == 'down':
                raise Unavailable('lab database offline')
            if down[0] == 'crash':
                raise RuntimeError('secret token abc')
            return value == spec['expected']
        return dict(REGISTRY, flaky=Check('flaky', 1, True, lambda spec: None, run))

    def test_verifier_outage_keeps_the_candidate_without_another_model_call_then_resumes_from_it(self):
        down = ['down']
        registry = self.flaky(down)
        self.post('a', '=1', [{'check': 'flaky', 'expected': '12.50 mm'}], registry=registry)
        self.post('b', '=2')
        fake = Fake()
        worker = self.worker(fake, registry=registry)
        self.assertEqual(worker.run_once()['outcomes'], {'a': 'checking', 'b': 'checking'})
        reasons = {c['job']: c['reason'] for c in self.box.candidates()}
        self.assertTrue(reasons['a'].startswith('awaiting checks: flaky'))
        self.assertTrue(reasons['b'].startswith('awaiting the reply status'))
        self.now[0] += 1000
        self.assertEqual(worker.run_once()['status'], 'idle')
        down[0] = 'crash'
        self.assertEqual([r['state'] for r in worker.recover()['rechecked']], ['checking'])
        verdict = self.box.candidates(job='a')[0]['verdicts'][0]
        self.assertEqual(verdict['reason'], 'verifier crashed (RuntimeError)')
        down[0] = 'up'
        worker.recover()
        self.assertEqual([self.state(m) for m in 'ab'], ['done', 'done'])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(self.events('a', 'released'), 1)

    def test_a_recheck_that_fails_returns_the_job_and_its_unproven_siblings_to_bounded_recovery(self):
        down = ['down']
        registry = self.flaky(down)
        self.post('a', '=1', [{'check': 'flaky', 'expected': 'something else'}], registry=registry)
        self.post('b', '=2')
        fake = Fake()
        worker = self.worker(fake, registry=registry)
        worker.run_once()
        down[0] = 'up'
        worker.recover()
        self.assertEqual({c['job']: c['status'] for c in self.box.candidates()},
                         {'a': 'rejected', 'b': 'quarantined'})
        self.assertEqual(self.box.stats(), {'pending': 2})
        worker.run_once()
        self.assertEqual(fake.calls, [['a', 'b'], ['a', 'b']])

    def test_exhausted_allowance_reports_quarantined_and_only_job_bound_checks_release_it(self):
        self.post('a', '=1', [{'check': 'expect', 'value': '12.50 mm'}], max_attempts=1)
        self.post('c', '=3', [{'check': 'json_type', 'types': ['string']}], max_attempts=1)
        worker = self.worker(Fake(dict(RIGHT, a='wrong')))
        self.assertEqual(worker.run_once()['outcomes'], {'a': 'failed', 'c': 'quarantined'})
        row = self.box.db.execute("SELECT state,failure_kind FROM jobs WHERE id='a'").fetchone()
        self.assertEqual(tuple(row), ('failed', 'exhausted'))
        self.assertTrue(self.box.records(['c'])['c']['error'].startswith('suspect reply'))
        seq = self.box.candidates(job='c')[0]['seq']
        self.assertEqual(worker.release(seq)['status'], 'not_released')
        self.assertEqual(worker.release(seq, [{'check': 'expect', 'value': 'wrong'}])['status'], 'not_released')
        # A strengthened acceptance contract rechecks the same stored candidate, without a model call.
        self.assertEqual(worker.release(seq, [{'check': 'quoted_span'}])['status'], 'released')
        self.assertEqual((self.state('c'), self.box.records(['c'])['c']['result']), ('done', '9.00 mm'))
        with self.assertRaises(Error):
            worker.release(seq, [{'check': 'quoted_span'}])

    def test_decide_without_any_checks_accepts_everything(self):
        decided, reply = decide({'a': [], 'b': []})
        self.assertEqual((decided, reply), ({'a': ('accept', None), 'b': ('accept', None)},
                                            {'suspect': False, 'pending': False}))


class LateReplyTests(Base):
    def crash_once(self, mid='a', **kw):
        """Dispatch attempt A whose coordinator dies after launch: intent journaled, no capture."""
        fake = Fake(crash=True)
        with self.assertRaises(Crash):
            self.worker(fake, **kw).run_once()
        return self.box.dispatches()[-1]['receipt']

    def test_late_reply_after_the_newer_attempt_committed_is_superseded_and_both_calls_are_accounted(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        newer = Fake({'a': '12.50 mm'})

        def overtake(request):
            self.now[0] += 1000
            self.assertEqual(self.worker(newer).run_once()['outcomes'], {'a': 'ok'})

        late = Fake({'a': 'length=12.50'}, hook=overtake)
        result = self.worker(late).run_once()
        self.assertEqual(result['outcomes'], {'a': 'late'})
        self.assertEqual(self.box.records(['a'])['a']['result'], '12.50 mm')
        self.assertEqual([c['status'] for c in self.box.candidates(job='a')], ['accepted', 'superseded'])
        self.assertEqual([d['state'] for d in self.box.dispatches()], ['captured', 'captured'])
        self.assertEqual(self.events('a', 'done') + self.events('a', 'adopted'), 1)

    def test_late_reply_before_the_newer_attempt_settles_is_adopted_and_the_newer_cannot_overwrite(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        self.post('d', '=2', after=['a'])
        first = self.crash_once()
        self.box.dispatch_captured(first, response=reply_for(['a'], {'a': 'length=12.50'}))
        self.now[0] += 1000
        coordinator = self.worker(Fake())

        def adopt_meanwhile(request):
            self.assertEqual(coordinator.recover()['settled'], [first])

        newer = Fake(hook=adopt_meanwhile)
        self.assertEqual(self.worker(newer).run_once()['outcomes'], {'a': 'late'})
        self.assertEqual(self.box.records(['a'])['a']['result'], 'length=12.50')
        self.assertEqual([c['status'] for c in self.box.candidates(job='a')], ['accepted', 'superseded'])
        # The dependent is released once and dispatched once.
        later = Fake()
        self.assertEqual(self.worker(later).run_once()['outcomes'], {'d': 'ok'})
        self.assertEqual(self.worker(later).run_once()['status'], 'idle')
        self.assertEqual(later.calls, [['d']])
        self.assertEqual((self.events('a', 'adopted'), self.events('a', 'done')), (1, 0))

    def test_an_obsolete_epoch_cannot_commit_and_the_current_coordinator_adopts_its_capture(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        old = Fake(hook=lambda request: self.box.take_over())
        result = self.worker(old).run_once()
        self.assertEqual((result['settlement'], result['outcomes']), ('fenced', {'a': 'fenced'}))
        self.assertEqual(self.state('a'), 'leased')
        summary = self.worker(Fake()).recover()
        self.assertEqual(len(summary['settled']), 1)
        self.assertEqual(self.state('a'), 'done')
        self.assertEqual(len(old.calls), 1)

    def test_a_cancelled_job_is_not_revived_by_a_late_success(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        first = self.crash_once()
        self.box.cancel('a', 'caller withdrew it')
        self.box.dispatch_captured(first, response=reply_for(['a'], RIGHT))
        self.worker(Fake()).recover()
        row = self.box.db.execute("SELECT state,failure_kind FROM jobs WHERE id='a'").fetchone()
        self.assertEqual(tuple(row), ('failed', 'cancelled'))
        self.assertEqual(self.box.candidates(job='a')[0]['status'], 'superseded')

    def test_late_failures_never_overwrite_success_or_cancel_a_live_attempt_but_decide_an_exhausted_job(self):
        failure = {'a': Failure('missing_data', 'late'), 'b': Failure('missing_data', 'late')}
        self.post('a', '=1', [{'check': 'quoted_span'}])
        self.post('b', '=2', [{'check': 'quoted_span'}], max_attempts=1)
        first = self.crash_once()
        self.now[0] += 1000
        self.box.dispatch_captured(first, response=reply_for(['a', 'b'], failure))
        self.worker(Fake()).recover()
        # a still has an attempt left: the late failure is history only; b has none: it decides b.
        self.assertEqual(self.state('a'), 'pending')
        row = self.box.db.execute("SELECT state,failure_kind,error FROM jobs WHERE id='b'").fetchone()
        self.assertEqual(tuple(row), ('failed', 'model_failure', 'missing_data: late'))
        self.worker(Fake()).run_once()
        self.assertEqual(self.state('a'), 'done')
        # A late failure after acceptance changes nothing.
        second = self.box.dispatches()[-1]['receipt']
        self.box.db.execute('UPDATE dispatches SET settled_at=NULL WHERE receipt=?', (second,))
        self.box.db.execute("UPDATE dispatches SET response=? WHERE receipt=?",
                            (json.dumps(reply_for(['a'], failure)), second))
        self.worker(Fake()).recover()
        self.assertEqual((self.state('a'), self.box.records(['a'])['a']['result']), ('done', '12.50 mm'))

    def test_an_exhausted_allowance_does_not_discard_a_captured_success(self):
        self.post('a', '=1', [{'check': 'quoted_span'}], max_attempts=1)
        first = self.crash_once()
        self.now[0] += 1000
        self.assertEqual(self.worker(Fake()).run_once()['status'], 'idle')
        self.box.dispatch_captured(first, response=reply_for(['a'], RIGHT))
        self.worker(Fake()).recover()
        self.assertEqual((self.state('a'), self.box.records(['a'])['a']['attempts']), ('done', 1))

    def test_two_captured_attempts_accept_exactly_once(self):
        self.post('a', '=1', [{'check': 'quoted_span'}], max_attempts=3)
        first = self.crash_once()
        self.now[0] += 1000
        second = self.crash_once()
        self.now[0] += 1000
        self.box.dispatch_captured(second, response=reply_for(['a'], {'a': 'length=12.50'}))
        self.box.dispatch_captured(first, response=reply_for(['a'], {'a': '12.50 mm'}))
        self.worker(Fake()).recover()
        statuses = [(c['receipt'], c['status']) for c in self.box.candidates(job='a')]
        self.assertEqual(statuses, [(first, 'accepted'), (second, 'superseded')])
        self.assertEqual(self.box.records(['a'])['a']['attempts'], 2)

    def test_crash_between_capture_and_settlement_resumes_without_a_model_call_and_only_once(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        self.post('b', '=2', [{'check': 'expect', 'value': 'nope'}])
        fake = Fake()
        with patch.object(self.box, 'settle_dispatch', side_effect=Crash()), self.assertRaises(Crash):
            self.worker(fake).run_once()
        self.assertEqual(self.box.dispatches()[0]['state'], 'captured')
        self.now[0] += 1000
        coordinator = self.worker(Fake(crash=True), epoch=self.box.take_over())
        self.assertEqual(len(coordinator.recover()['settled']), 1)
        self.assertEqual((self.state('a'), self.state('b')), ('done', 'pending'))
        self.assertEqual(coordinator.recover(), {'captured': [], 'uncertain': [], 'settled': [], 'rechecked': []})
        self.assertEqual((self.events('a', 'adopted'), len(fake.calls)), (1, 1))


class IdentityTests(Base):
    def key(self, ch, rows, mid, route=None):
        packet = render(ch, rows, counters=[len])
        return compute_key(json.loads(packet.text)['goal'], job_inputs(packet.text, packet.job_map)[mid],
                           route or {'model': 'm'})

    def test_compute_key_follows_every_manifest_component_and_survives_repacking(self):
        base = self.key(self.ch, [('a', '=1')], 'a')
        self.assertEqual(base, self.key(self.ch, [('x', '=3'), ('b', '=2'), ('a', '=1')], 'a'))
        self.assertEqual(base, self.key(self.ch, [('renamed', '=1')], 'renamed'))
        changed = [self.key(channel(goal='Report lengths now.'), [('a', '=1')], 'a'),
                   self.key(channel(first='length=12.5 mm'), [('a', '=1')], 'a'),
                   self.key(self.ch, [('a', '=2')], 'a'),
                   *(self.key(self.ch, [('a', '=1')], 'a', {'model': 'm', k: 'v'})
                     for k in ('adapter', 'effort', 'cli_version')),
                   self.key(self.ch, [('a', '=1')], 'a', {'model': 'other'})]
        self.assertEqual(len({base, *changed}), len(changed) + 1)
        literal = [self.key(self.ch, [('a', ':Extract the length.')], 'a'),
                   self.key(self.ch, [('a', ':Extract the length!')], 'a')]
        self.assertNotEqual(*literal)

    def test_a_pinned_computation_refuses_another_route_before_charging_an_attempt(self):
        self.post('a', '=1')
        self.crash_once_with(route={'model': 'm1'})
        self.now[0] += 1000
        with self.assertRaisesRegex(Error, 'pinned to another computation'):
            self.worker(Fake(), route={'model': 'm2'}).run_once()
        self.assertEqual((self.box.records(['a'])['a']['attempts'], len(self.box.dispatches())), (1, 1))
        self.assertEqual(self.worker(Fake(), route={'model': 'm1'}).run_once()['outcomes'], {'a': 'ok'})

    def crash_once_with(self, **kw):
        with self.assertRaises(Crash):
            self.worker(Fake(crash=True), **kw).run_once()


class DurableTests(Base):
    PROGRAM = r'''
import json, sys
request = json.load(sys.stdin)
body = json.loads(request['prompt'])
values = {'a': '12.50 mm', 'b': '12.47 mm', 'c': '9.00 mm'}
lines = ['OZ/1g'] + [json.dumps({row[0]: values[row[0]]}) for block in body['jobs'] for row in block[1:]]
json.dump({'reply': '\n'.join(lines), 'usage': {'input_tokens': 70, 'output_tokens': 7}}, sys.stdout)
'''

    def setUp(self):
        super().setUp()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        (self.dir / 'fake.py').write_text(self.PROGRAM, encoding='utf-8')
        self.captures = self.dir / 'captures'

    def adapter(self, argv=None):
        return StdioAdapter(tuple(argv or (sys.executable, 'fake.py')), capabilities=CAPS, cwd=self.dir,
                            timeout=60, capture_dir=self.captures)

    def test_sqlite_durability_settings_are_explicit(self):
        with Inbox(self.dir / 'box.sqlite') as box:
            self.assertEqual(box.db.execute('PRAGMA synchronous').fetchone()[0], 2)
            self.assertEqual(box.db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')

    def test_runner_publishes_the_capture_and_the_journal_records_launch_identity(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        self.post('b', '=2', [{'check': 'quoted_span'}])
        result = self.worker(self.adapter(), timeout=60).run_once()
        self.assertEqual(result['outcomes'], {'a': 'ok', 'b': 'ok'})
        d = self.box.dispatches()[0]
        self.assertEqual((d['state'], d['reservation_state']), ('captured', 'released'))
        self.assertEqual(set(d['process']), {'pid', 'created'})
        payload = request_path(self.captures, d['receipt']).read_bytes()
        self.assertEqual(d['request_sha256'], hashlib.sha256(payload).hexdigest())
        self.assertTrue(done_path(self.captures, d['receipt']).exists())
        self.assertEqual(d['response']['usage'], {'input_tokens': 70, 'output_tokens': 7})
        events = [e['event'] for e in self.box.history('a')]
        self.assertEqual(events[:4], ['posted', 'claimed', 'dispatch_intent', 'dispatch_launched'])
        self.assertIn('dispatch_captured', events)

    def manual_dispatch(self, ids):
        """A dispatch whose coordinator died right after launch intent: returns (receipt, request bytes)."""
        receipt = self.box.new_receipt()
        delivery, packet = self.box.claim_prepared(
            self.ch, owner='w', counters=[len], receipt=receipt, max_tokens=100000, lease_seconds=90,
            dispatch={'epoch': self.box.epoch(), 'route': self.worker(Fake())._route(), 'capture_dir': str(self.captures),
                      'call_id': 'c-' + receipt, 'timeout': 60})
        self.assertEqual([j.id for j in delivery.jobs], ids)
        payload = json.dumps({'receipt': receipt, 'prompt': packet.text, 'system': packet.system},
                             ensure_ascii=False).encode('utf-8')
        self.captures.mkdir(exist_ok=True)
        request_path(self.captures, receipt).write_bytes(payload)
        return receipt, payload

    def run_runner(self, receipt, argv=None):
        return subprocess.run([sys.executable, str(RUNNER), str(self.captures), receipt, '--',
                               *(argv or (sys.executable, 'fake.py'))], cwd=self.dir, capture_output=True)

    def test_coordinator_crash_after_launch_is_recovered_from_the_runner_capture_without_a_new_call(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        self.post('b', '=2', [{'check': 'expect', 'value': '12.47 mm'}])
        receipt, _ = self.manual_dispatch(['a', 'b'])
        self.assertEqual(self.run_runner(receipt).returncode, 0)
        self.now[0] += 1000
        never = Fake(crash=True)
        summary = self.worker(never, epoch=self.box.take_over()).recover()
        self.assertEqual((summary['captured'], summary['settled']), ([receipt], [receipt]))
        self.assertEqual(self.box.stats(), {'done': 2})
        self.assertEqual(self.worker(never).run_once()['status'], 'idle')
        self.assertEqual(never.calls, [])

    def test_runner_death_leaves_an_uncertain_dispatch_until_a_valid_capture_resolves_it(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        receipt, _ = self.manual_dispatch(['a'])
        short = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(0.3)'])
        identity = process_identity(short.pid)
        short.wait()
        self.box.dispatch_launched(receipt, identity)
        self.assertEqual(self.worker(Fake()).recover()['uncertain'], [])  # lease still live: in flight
        self.now[0] += 1000
        self.assertEqual(self.worker(Fake()).recover()['uncertain'], [receipt])
        d = self.box.dispatch(receipt)
        self.assertEqual((d['state'], d['reservation_state'], d['response']), ('uncertain', 'held', None))
        # Bounded recovery: the attempt stays charged, the job retries once more.
        fake = Fake()
        self.assertEqual(self.worker(fake).run_once()['outcomes'], {'a': 'ok'})
        self.assertEqual(self.box.records(['a'])['a']['attempts'], 2)
        # The runner's late completion record still resolves the uncertainty; the accepted result stands.
        self.assertEqual(self.run_runner(receipt).returncode, 0)
        self.assertEqual(self.worker(Fake()).recover()['settled'], [receipt])
        self.assertEqual(self.box.dispatch(receipt)['state'], 'captured')
        self.assertEqual([c['status'] for c in self.box.candidates(job='a')], ['accepted', 'superseded'])

    def test_a_runner_ending_without_a_completion_record_is_uncertain_not_failed(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        adapter = self.adapter(argv=(str(self.dir / 'missing-program.exe'),))
        result = self.worker(adapter, timeout=60).run_once()
        self.assertEqual((result['error_code'], result['outcomes']), ('adapter_capture_missing', {'a': 'retry'}))
        d = self.box.dispatches()[0]
        self.assertEqual((d['state'], d['reservation_state']), ('uncertain', 'held'))

    def test_temporary_or_schema_less_capture_files_do_not_count_as_completion(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        receipt, _ = self.manual_dispatch(['a'])
        self.run_runner(receipt)
        good = done_path(self.captures, receipt)
        # Interrupted before the rename: only the temporary file exists.
        good.rename(good.with_name(f'.{good.name}.999.tmp'))
        self.now[0] += 1000
        self.assertEqual(self.worker(Fake()).recover()['uncertain'], [receipt])
        # Complete-looking JSON that is not a capture record of this receipt.
        good.write_text(json.dumps({'receipt': receipt, 'exit_code': 0, 'stdout_b64': ''}), encoding='utf-8')
        self.assertEqual(self.worker(Fake()).recover()['captured'], [])
        self.assertEqual(self.box.dispatch(receipt)['state'], 'uncertain')

    def test_uncertain_dispatches_keep_usage_coverage_incomplete(self):
        from oz_do import _accounting
        journal = [{'call_id': 'x1', 'state': 'captured', 'response': {'reply': '', 'usage': {
                       'input_tokens': 10, 'output_tokens': 1}}},
                   {'call_id': 'x2', 'state': 'uncertain', 'response': None}]
        result = _accounting(self.dir, journal)
        self.assertEqual((result['calls'], result['usage_coverage'], result['tokens']['input_tokens']),
                         (2, 'partial', 10))
        self.assertEqual((result['dispatches'], result['unreconciled_dispatches']),
                         ({'captured': 1, 'uncertain': 1}, 1))

    def test_a_published_capture_bound_to_other_request_bytes_does_not_count(self):
        self.post('a', '=1', [{'check': 'quoted_span'}])
        receipt, payload = self.manual_dispatch(['a'])
        self.box.dispatch_prepared(receipt, hashlib.sha256(payload + b' ').hexdigest())
        self.run_runner(receipt)
        self.now[0] += 1000
        summary = self.worker(Fake()).recover()
        self.assertEqual((summary['captured'], summary['uncertain']), ([], [receipt]))


class DoSelectiveTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'ws'
        initialize(self.root)
        (self.root / 'fake.py').write_text(DO_FAKE, encoding='utf-8')
        (self.root / 'adapter.json').write_text(json.dumps({'argv': [sys.executable, 'fake.py'], **CAPS}),
                                                encoding='utf-8')

    def calls(self):
        path = self.root / 'captured.jsonl'
        return [json.loads(x)['ids'] for x in path.read_text(encoding='utf-8').splitlines()]

    def test_default_profile_is_unchanged_and_journals_nothing(self):
        result = do(do_request(), workspace=self.root, adapter=self.root / 'adapter.json')
        run = self.root / result['run']['run_dir']
        self.assertEqual(result['evidence']['scope'], 'model_declared')
        self.assertNotIn('profile', json.loads((run / 'request.json').read_text(encoding='utf-8'))['work'])
        self.assertFalse((run / 'captures').exists())
        self.assertNotIn('dispatches', result['accounting'])

    def test_selective_profile_is_opt_in_and_retries_only_jobs_that_fail_their_checks(self):
        checks = {'extract': [{'check': 'json_type', 'types': ['array']}],
                  'bounds': [{'check': 'json_type', 'types': ['string']}]}
        result = do(do_request(4, profile=SELECTIVE, checks=checks), workspace=self.root,
                    adapter=self.root / 'adapter.json')
        self.assertEqual(result['counts'], {'accepted': 2, 'unresolved': 2})
        self.assertEqual(self.calls(), [['j1', 'j2', 'j3', 'j4'], ['j2', 'j4']])
        self.assertEqual(result['jobs']['j1']['evidence'],
                         {'profile': SELECTIVE, 'summary': 'checked', 'checks': ['json_type@1']})
        self.assertEqual(result['jobs']['j2']['reason'], 'attempts_exhausted')
        self.assertEqual(result['evidence']['profile'], SELECTIVE)
        self.assertEqual(result['accounting']['dispatches'], {'captured': 2})
        self.assertEqual(result['accounting']['usage_coverage'], 'complete')
        run = self.root / result['run']['run_dir']
        self.assertEqual(len(list((run / 'captures').glob('*.done'))), 2)
        again = do(do_request(4, profile=SELECTIVE, checks=checks), workspace=self.root,
                   adapter=self.root / 'adapter.json')
        self.assertEqual((again['jobs'], len(self.calls())), (result['jobs'], 2))

    def test_checks_need_the_selective_profile(self):
        for extra in ({'checks': {'extract': [{'check': 'json_type', 'types': ['array']}]}},
                      {'profile': 'other'},
                      {'profile': SELECTIVE, 'checks': {'unknown_op': []}}):
            with self.subTest(extra=extra), self.assertRaises(Error):
                do(do_request(**extra), workspace=self.root, adapter=self.root / 'adapter.json')


if __name__ == '__main__':
    unittest.main()
