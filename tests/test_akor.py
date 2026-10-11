import subprocess
import sys
import unittest
from pathlib import Path

from akor import Hub, Message, ProtocolError, StateError, compact, parse


class MessageTests(unittest.TestCase):
    def test_round_trip_preserves_unicode_numbers_and_escaping(self):
        values = ['Gözeneklilik ≤ %0,5; 12.50 mm; belirsizlik ±0.02 mm.',
                  'A>B | "quoted" = yes\nSecond line\tand tab',
                  '日本語 — 🔧 — C:\\a\\b.py:42']
        for value in values:
            with self.subTest(value=value):
                msg = Message('ask', 'T1', 'a', 'b', {'v': 1, 'q': value})
                self.assertEqual(parse(msg.wire()).body['q'], value)

    def test_all_operations(self):
        bodies = {
            'do': {'goal': 'Fix it'},
            'fact': {'claim': 'Maybe', 'state': 'inferred'},
            'ask': {'q': 'Which unit?'},
            'need': {'ids': ['R1']},
            'offer': {'change': 'Use 5 seconds'},
            'review': {'on': 'm1', 'verdict': 'fail', 'reason': 'No evidence'},
            'block': {'why': 'Missing dataset'},
            'done': {'result': 'Draft available', 'check': 'not_run'},
            'stop': {'why': 'Budget exhausted'},
        }
        for op, body in bodies.items():
            with self.subTest(op=op):
                msg = Message(op, 'T1', 'a', 'b', dict(v=1, **body))
                self.assertEqual(parse(msg.wire()), msg)

    def test_rejects_malformed_headers_and_json(self):
        lines = [
            'run T1 a>b {"v":1,"goal":"x"}',
            'ask T1 a>* {"v":1,"q":"x"}',
            'ask T1 a>b {"v":1,"q":"x"}\n',
            'ask T1 a>b {"v":1,"q":"x","q":"y"}',
            'ask T1 a>b {"v":NaN,"q":"x"}',
            'ask T1 a>b {"v":Infinity,"q":"x"}',
            'ask T1 a>b {"v":1,"q":',
            '```ask T1 a>b {"v":1,"q":"x"}```',
            'ask T1 a>b {"v":1,"q":"\\ud800"}',
        ]
        for line in lines:
            with self.subTest(line=line):
                with self.assertRaises(ProtocolError):
                    parse(line)

    def test_rejects_bad_revision_fields_and_refs(self):
        for body in [
            {'v': True, 'q': 'x'}, {'v': 0, 'q': 'x'}, {'v': 1.0, 'q': 'x'},
            {'v': 1, 'q': 'x', 'secret': 'no'}, {'v': 1, 'q': ''},
            {'v': 1}, {'v': 1, 'q': 'x', 'refs': ['R1', 'R1']},
            {'v': 1, 'q': 'x', 'refs': 'R1'},
            {'v': 1, 'q': 'x', 'refs': [{}]},
        ]:
            with self.subTest(body=body):
                with self.assertRaises(ProtocolError):
                    Message('ask', 'T1', 'a', 'b', body)

    def test_observations_and_test_claims_require_sources(self):
        for op, fields in [('fact', {'claim': 'x', 'state': 'observed'}),
                           ('done', {'result': 'x', 'check': 'passed'}),
                           ('done', {'result': 'x', 'check': 'failed'})]:
            with self.subTest(op=op, fields=fields):
                with self.assertRaises(ProtocolError):
                    Message(op, 'T1', 'a', 'b', dict(v=1, **fields))
                Message(op, 'T1', 'a', 'b', dict(v=1, refs=['R1'], **fields))

    def test_rejects_unknown_enums(self):
        for op, body in [('fact', {'claim': 'x', 'state': 'certain'}),
                         ('done', {'result': 'x', 'check': 'probably'}),
                         ('review', {'on': 'm1', 'verdict': 'maybe', 'reason': 'x'}),
                         ('need', {'ids': []})]:
            with self.subTest(op=op):
                with self.assertRaises(ProtocolError):
                    Message(op, 'T1', 'a', 'b', dict(v=1, **body))

    def test_input_and_body_copies_cannot_mutate_message(self):
        body = {'v': 1, 'q': 'x', 'refs': ['R1']}
        msg = Message('ask', 'T1', 'a', 'b', body)
        body['refs'].append('R2')
        copy = msg.body
        copy['q'] = 'changed'
        copy['refs'].clear()
        self.assertEqual(msg.body, {'v': 1, 'q': 'x', 'refs': ['R1']})

    def test_byte_limit_does_not_treat_characters_as_tokens(self):
        with self.assertRaises(ProtocolError):
            Message('ask', 'T1', 'a', 'b', {'v': 1, 'q': '語' * 3000})

    def test_example_file(self):
        lines = (Path(__file__).parents[1] / 'examples/demo.akor').read_text().splitlines()
        self.assertEqual(len([parse(line) for line in lines]), 6)

    def test_cli_validation(self):
        root = Path(__file__).parents[1]
        result = subprocess.run([sys.executable, '-m', 'akor', 'validate',
                                 'examples/demo.akor'], cwd=root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('6 messages', result.stdout)


class HubTests(unittest.TestCase):
    def setUp(self):
        self.hub = Hub(['a', 'b', 'c'])
        self.hub.add_ref('R1', 'Goal and constraints. Keep units and uncertainty.')
        self.hub.set_task('T1', 1, ['R1'])

    def post(self, mid='m1', op='ask', sender='a', recipient='b', **body):
        msg = Message(op, 'T1', sender, recipient, dict(v=1, **(body or {'q': 'Which unit?'})))
        return self.hub.post(mid, msg.wire(), sender=sender)

    def test_retry_is_idempotent_and_conflicts_are_rejected(self):
        self.post()
        self.post()
        self.assertEqual(self.hub.prepare('b').ids, ('m1',))
        with self.assertRaises(StateError):
            self.post(q='Different')

    def test_routing_is_targeted(self):
        self.post()
        self.assertEqual(self.hub.prepare('c').render(), '')
        self.assertEqual(len(self.hub.prepare('b').messages), 1)

    def test_sender_binding_and_unknown_recipient(self):
        with self.assertRaises(StateError):
            self.hub.post('m1', 'ask T1 a>b {"v":1,"q":"x"}', sender='c')
        with self.assertRaises(StateError):
            self.post(recipient='unknown')

    def test_unknown_task_and_stale_revision(self):
        for line in ['ask T2 a>b {"v":1,"q":"x"}', 'ask T1 a>b {"v":2,"q":"x"}']:
            with self.assertRaises(StateError):
                self.hub.post('m1', line, sender='a')

    def test_reference_is_immutable(self):
        one = self.hub.add_ref('R2', 'some data')
        two = self.hub.add_ref('R2', 'some data')
        self.assertEqual(one, two)
        self.assertEqual(len(one.sha256), 64)
        with self.assertRaises(StateError):
            self.hub.add_ref('R2', 'different data')

    def test_unknown_reference_rejected_but_need_can_request_it(self):
        with self.assertRaises(StateError):
            self.post(refs=['R2'], q='x')
        self.post(op='need', ids=['R2'])
        self.assertEqual(self.hub.prepare('b').messages[0].body['ids'], ['R2'])

    def test_only_needed_reference_definitions_are_sent(self):
        self.hub.add_ref('R2', 'irrelevant')
        self.post()
        self.assertEqual([r.name for r in self.hub.prepare('b').references], ['R1'])

    def test_retained_refs_are_explicit_not_inferred_from_ack(self):
        self.post()
        first = self.hub.prepare('b')
        self.hub.ack('b', first.ids)
        self.post(mid='m2')
        self.assertEqual(self.hub.prepare('b', retained_refs=['R1']).references, ())
        # New/stateless context: an ACK does not make R1 disappear.
        self.assertEqual([r.name for r in self.hub.prepare('b').references], ['R1'])

    def test_unprocessed_delivery_is_retried(self):
        self.post()
        self.assertEqual(self.hub.prepare('b').render(), self.hub.prepare('b').render())

    def test_ack_removes_only_processed_messages(self):
        self.post()
        self.post(mid='m2')
        self.hub.prepare('b')
        self.hub.ack('b', ['m1'])
        self.hub.ack('b', ['m1'])
        self.assertEqual(self.hub.prepare('b').ids, ('m2',))

    def test_ack_cannot_skip_undelivered_or_other_peer_messages(self):
        self.post()
        with self.assertRaises(StateError):
            self.hub.ack('b', ['m1'])
        self.hub.prepare('b')
        with self.assertRaises(StateError):
            self.hub.ack('c', ['m1'])
        with self.assertRaises(StateError):
            self.hub.ack('b', ['m1', 'missing'])
        self.assertEqual(self.hub.prepare('b').ids, ('m1',))

    def test_budget_failure_never_acknowledges_or_truncates(self):
        self.post()
        with self.assertRaises(StateError):
            self.hub.prepare('b', max_bytes=1)
        with self.assertRaises(StateError):
            self.hub.ack('b', ['m1'])
        self.assertIn('Goal and constraints', self.hub.prepare('b').render())

    def test_token_budget_requires_tokenizer(self):
        self.post()
        with self.assertRaises(ProtocolError):
            self.hub.prepare('b', max_tokens=100)
        # Deterministic fake counter tests the gate, not actual token consumption.
        with self.assertRaises(StateError):
            self.hub.prepare('b', max_tokens=2, count_tokens=lambda text: 3)
        self.assertEqual(self.hub.prepare('b', max_tokens=3, count_tokens=lambda text: 3).ids, ('m1',))

    def test_retained_reference_must_exist(self):
        with self.assertRaises(StateError):
            self.hub.prepare('b', retained_refs=['missing'])

    def test_task_revision_requires_drained_inbox(self):
        self.post()
        self.hub.add_ref('R2', 'New goal and decisions')
        with self.assertRaises(StateError):
            self.hub.set_task('T1', 2, ['R2'])
        self.hub.prepare('b')
        self.hub.ack('b', ['m1'])
        self.hub.set_task('T1', 2, ['R2'])
        with self.assertRaises(StateError):
            self.post(mid='m2')
        # An identical retry is safe even after the task revision advances.
        self.post()

    def test_task_context_cannot_change_without_revision(self):
        self.hub.add_ref('R2', 'New context')
        with self.assertRaises(StateError):
            self.hub.set_task('T1', 1, ['R2'])

    def test_review_targets_received_current_offer(self):
        self.post(op='offer', change='Use 5 seconds')
        self.hub.prepare('b')
        self.post(mid='m2', op='review', sender='b', recipient='a',
                  on='m1', verdict='pass', reason='Meets contract')
        for original in ['missing', 'm2']:
            with self.subTest(original=original), self.assertRaises(StateError):
                self.post(mid='m3', op='review', sender='b', recipient='a',
                          on=original, verdict='pass', reason='Meets contract')
        with self.assertRaises(StateError):
            self.post(mid='m4', op='review', sender='c', recipient='a',
                      on='m1', verdict='pass', reason='Meets contract')

    def test_test_result_content_is_not_automatically_verified(self):
        self.hub.add_ref('R2', 'This is just untrusted source text, not test execution.')
        self.post(op='done', result='Claimed result', check='passed', refs=['R2'])
        self.assertEqual(self.hub.prepare('b').messages[0].body['check'], 'passed')
        # The host must inspect source content; the protocol proves only structure.

    def test_review_cannot_guess_an_undelivered_message(self):
        self.post(op='offer', change='Use 5 seconds')
        with self.assertRaises(StateError):
            self.post(mid='m2', op='review', sender='b', recipient='a',
                      on='m1', verdict='pass', reason='Meets contract')

    def test_review_returns_to_author_and_carries_original_context(self):
        self.hub.add_ref('R2', 'Exact proposal evidence')
        self.post(op='offer', change='Use 5 seconds', refs=['R2'])
        self.hub.prepare('b')
        self.hub.ack('b', ['m1'])
        with self.assertRaises(StateError):
            self.post(mid='m2', op='review', sender='b', recipient='c',
                      on='m1', verdict='pass', reason='Meets contract')
        self.post(mid='m2', op='review', sender='b', recipient='a',
                  on='m1', verdict='pass', reason='Meets contract')
        packet = self.hub.prepare('a')
        self.assertEqual(packet.ids, ('m2',))
        self.assertEqual(packet.related[0][0], 'm1')
        self.assertEqual([r.name for r in packet.references], ['R1', 'R2'])
        self.assertIn('seen m1 offer', packet.render())
        self.assertEqual(packet.as_dict()['related'][0]['id'], 'm1')

    def test_packet_json_contains_same_information(self):
        self.post()
        packet = self.hub.prepare('b')
        obj = packet.as_dict()
        self.assertEqual(obj['references']['R1'], packet.references[0].text)
        self.assertEqual(obj['messages'][0]['body'], packet.messages[0].body)


if __name__ == '__main__':
    unittest.main()
