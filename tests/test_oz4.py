import json
from pathlib import Path
import random
import tempfile
import unittest

from examples.oz3_demo import example_channel
from oz import Atom, Channel, Codebook, Error, Macro
from oz_batch import render
from oz_compiler import compile_messages
from oz_delta import delta_spellings
from oz_runtime import Inbox
from oz_worker import Worker, RESPONSE_CONTRACT


def channel(basis='r1a1t30'):
    original = example_channel()
    snapshot = original.snapshot()
    snapshot['basis'] = [vars(a) for a in original.accept(basis, binding=original.binding)]
    return Channel.from_snapshot(snapshot)


class RelativeTests(unittest.TestCase):
    def test_base_identity_and_one_step_replacement(self):
        ch = channel()
        self.assertEqual(ch.accept('^', binding=ch.binding), ch.basis)
        self.assertEqual(ch.accept('^0=r2', binding=ch.binding), (Atom('r', 2), Atom('a', 1), Atom('t', 30)))
        self.assertIn('^', ch.spellings(ch.basis))
        self.assertEqual(ch.accept(ch.encode(ch.basis), binding=ch.binding), ch.basis)

    def test_deletion_insertion_and_interval_replacement(self):
        ch = channel()
        examples = {'^1=': 'r1t30', '^1:1=r2': 'r1r2a1t30', '^3:3=r3': 'r1a1t30r3',
                    '^0:2=V2': 'r2a2t30t30', '^0:0=r2r3': 'r2r3r1a1t30'}
        for wire, expected in examples.items():
            with self.subTest(wire=wire):
                self.assertEqual(ch.accept(wire, binding=ch.binding), ch.accept(expected, binding=ch.binding))

    def test_multiple_edits_address_original_base_and_each_frame_resets(self):
        ch = channel('r1a1r2a2t30')
        actual = ch.accept('^0=;3=a3', binding=ch.binding)
        self.assertEqual(actual, ch.accept('a1r2a3t30', binding=ch.binding))
        self.assertEqual(ch.accept('^', binding=ch.binding), ch.basis)

    def test_simultaneous_reference_swap_does_not_chain(self):
        ch = channel('r1a1r2a2t30')
        self.assertEqual(ch.accept('^@1:2,2:1', binding=ch.binding),
                         ch.accept('r2a2r1a1t30', binding=ch.binding))
        self.assertIn('^@1:2,2:1', delta_spellings(ch.basis, ch.accept('r2a2r1a1t30', binding=ch.binding)))

    def test_ambiguous_or_missing_remaps_rejected(self):
        ch = channel()
        for wire in ['^@', '^@1:1', '^@2:3', '^@1:2,1:3', '^@01:2', '^@1:0', '^@1:99999',
                     '^@1:2;', '^@1:30', '^@1:999', '^@1:2,']:
            with self.subTest(wire=wire), self.assertRaises(Error):
                ch.accept(wire, binding=ch.binding)

    def test_status_claims_literals_and_recursion_never_hidden_in_deltas(self):
        ch = channel()
        for payload in ['.', '/', '?9', '+8', '=8', '~8', '!8', ':text', '^', '^0=r2']:
            with self.subTest(payload=payload), self.assertRaises(Error):
                ch.accept('^0=' + payload, binding=ch.binding)
        text = ':^0=;\r\n0.05 wt%; unverified.'
        self.assertEqual(ch.encode(ch.accept(text, binding=ch.binding)), text)

    def test_invalid_and_overlapping_spans_rejected(self):
        ch = channel()
        for wire in ['^;', '^0', '^00=r2', '^3=r2', '^0:4=', '^2:1=r2', '^1:3=;2=r2',
                     '^2=r2;1=r1', '^1:1=r2;1=r3', '^0:3=', '^0=\nr2', '^64:64=r2', '^0=r2;']:
            with self.subTest(wire=wire), self.assertRaises(Error):
                ch.accept(wire, binding=ch.binding)

    def test_frame_and_expansion_bounds(self):
        ch = channel('r1' * 64)
        self.assertEqual(len(ch.accept('^', binding=ch.binding)), 64)
        for wire in ['^64:64=r1', '^0=' + 'r1' * 65,
                     '^' + ';'.join(f'{i}=r2' for i in range(17)), '^0=' + 'r1' * 5000]:
            with self.subTest(wire=wire), self.assertRaises(Error):
                ch.accept(wire, binding=ch.binding)

    def test_basis_binding_snapshot_and_old_channel_compatibility(self):
        ch = channel()
        self.assertEqual(ch.binding, Channel.from_snapshot(ch.snapshot()).binding)
        self.assertNotEqual(ch.binding, channel('r2a2t30').binding)
        with self.assertRaises(Error):
            ch.accept('^', binding=channel('r2a2t30').binding)
        with self.assertRaises(Error):
            example_channel().accept('^', binding=example_channel().binding)
        with self.assertRaises(AttributeError):
            ch.basis = ()
        path = Path(__file__).parents[1] / 'examples/oz3-channel.json'
        original = Channel.from_snapshot(json.loads(path.read_text(encoding='utf-8')))
        self.assertNotIn('basis', original.snapshot())

    def test_basis_must_be_explicit_typed_work(self):
        original = example_channel().snapshot()
        for steps in [[], [Atom('.', None)], [Atom('a', 30)], [Atom('r', 0)], [Atom('r', 999)],
                      [Atom('V', 1)], [Atom(':', text='text')], [Atom('r', 1)] * 65]:
            with self.subTest(steps=steps), self.assertRaises(Error):
                Channel.from_snapshot(dict(original, basis=[vars(a) for a in steps]))

    def test_relative_payload_dictionary_keeps_macros_and_vector_rules(self):
        ch = channel()
        text = ch.dictionary(['^0=V[2:4]'])
        self.assertIn('VN=rNaNt30', text)
        self.assertIn('OZ/4 relative frames', text)
        self.assertIn('L:H', text)
        self.assertIn('Base=r1a1t30', text)
        self.assertIn('Base=r1a1t30', ch.prompt())
        self.assertNotIn('Base=', ch.dictionary(['r1']))

    def test_random_program_edits_round_trip(self):
        rng = random.Random(704)
        ch = channel('r1a1r2a2r3a3t30')
        for _ in range(250):
            atoms = list(ch.basis)
            for _ in range(rng.randint(1, 6)):
                index = rng.randrange(len(atoms))
                if rng.random() < .25 and len(atoms) > 1:
                    del atoms[index]
                elif rng.random() < .5:
                    atoms.insert(index, Atom('r', rng.randint(1, 24)))
                else:
                    atoms[index] = Atom('r', rng.randint(1, 24))
            expected = tuple(atoms)
            for wire in delta_spellings(ch.basis, expected):
                self.assertEqual(ch.accept(wire, binding=ch.binding), expected)
            self.assertEqual(ch.accept(ch.encode(expected, candidate_limit=8), binding=ch.binding), expected)

    def test_absolute_fallback_is_costed_and_old_queue_semantics_preserved(self):
        ch = channel()
        packet = render(ch, [('m', '^')], counters=[len])
        self.assertIn('oz_absolute/tuples', packet.alternatives)
        self.assertLessEqual(packet.tokens[0], packet.alternatives['oz_absolute/tuples'][0])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'queue.sqlite'
            with Inbox(path) as box:
                box.post(ch, 'm', '^', binding=ch.binding)
                self.assertFalse(box.post(ch, 'm', 'r1a1t30', binding=ch.binding))
            with Inbox(path) as box:
                delivery = box.claim(Channel.from_snapshot(ch.snapshot()), owner='test')
                self.assertEqual(ch.accept(delivery.jobs[0].wire, binding=ch.binding), ch.basis)

    def test_small_messages_reject_unprofitable_basis(self):
        ch = example_channel()
        result = compile_messages(ch, [('m', 'r1')], counters=[len], relative=True, max_macros=0)
        self.assertFalse(result.changed)
        self.assertFalse(result.channel.basis)

    def test_optimizer_measures_basis_and_accepts_only_net_gain(self):
        from examples.oz4_demo import example_channel as code_channel, messages as code_messages
        ch, messages = code_channel(relative=False), code_messages()
        result = compile_messages(ch, messages, counters=[len], relative=True, max_macros=0,
                                  response_contract='RESPONSE CONTRACT', additional_context='PREDECESSOR RESULTS')
        self.assertTrue(result.channel.basis)
        self.assertLess(result.packet.tokens[0], result.absolute_tokens[0])
        self.assertIn('Base=', result.packet.text)
        self.assertIn('RESPONSE CONTRACT', result.packet.text)
        self.assertIn('PREDECESSOR RESULTS', result.packet.text)
        self.assertEqual(result.channel.scope[-1], ch.scope[-1] + 1)
        for (_, wire), (_, original) in zip(result.messages, messages):
            self.assertEqual(result.channel.accept(wire, binding=result.channel.binding), ch.accept(original, binding=ch.binding))

    def test_identical_requests_use_cheaper_table_without_changing_job_identity(self):
        ch = example_channel()
        program = ''.join(f'V{n}' for n in [9, 2, 7, 3, 11, 1, 6, 4, 10, 5, 8, 12, 19, 17, 15, 18])
        messages = [(f'm{i}', program) for i in range(64)]
        result = compile_messages(ch, messages, counters=[len], relative=True, max_macros=0)
        self.assertFalse(result.channel.basis)
        self.assertIn('_table/', result.packet.mode)
        self.assertEqual(result.packet.ids, tuple(mid for mid, _ in messages))
        self.assertEqual(len(result.messages), 64)

    def test_bad_compiler_options(self):
        ch = example_channel()
        for opts in [dict(relative=1), dict(basis_limit=0), dict(basis_limit=17)]:
            with self.subTest(opts=opts), self.assertRaises(Error):
                compile_messages(ch, [('m', 'r1')], counters=[len], **opts)

    def test_worker_delivers_relative_jobs_and_preserves_dependency_results(self):
        ch = channel()
        seen = []
        def adapter(request):
            seen.append(request)
            self.assertIn(RESPONSE_CONTRACT, request['prompt'])
            self.assertEqual(request['estimated_input_tokens'], [len(request['prompt'])])
            return {'results': [[mid, 0, 'Synthetic receipt only; no tests executed.'] for mid in request['ids']]}
        with Inbox() as box:
            box.post(ch, 'first', '^', binding=ch.binding)
            box.post(ch, 'second', '^@1:2', binding=ch.binding, after=['first'])
            worker = Worker(box, ch, adapter, counters=[len], max_tokens=10000)
            self.assertEqual(worker.run_once()['ids'], ['first'])
            self.assertEqual(worker.run_once()['ids'], ['second'])
            self.assertIn('Synthetic receipt only; no tests executed.', seen[1]['prompt'])
            self.assertEqual(box.stats(), {'done': 2})
            self.assertEqual(worker.run_once()['model_calls'], 0)


if __name__ == '__main__':
    unittest.main()
