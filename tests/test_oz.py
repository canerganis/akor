import unittest

from oz import Atom, Channel, Error, Reference, parse, prompt


def channel(**overrides):
    args = dict(session='s1', task='T1', revision=1, sender='lead', recipient='worker',
                goal='Review patch; preserve API. Do not claim physical validation.', active=7,
                references=[Reference(7, 'patch', 'demo patch at revision a1'),
                            Reference(8, 'test', '2 checks passed', 'test.log@a1', 'passed'),
                            Reference(9, 'test', '1 check failed', 'test.log@a2', 'failed'),
                            Reference(10, 'hypothesis', 'May be a timeout'),
                            Reference(11, 'reason', 'Measurement method missing'),
                            Reference(12, 'proposal', 'Use 5 seconds per attempt'),
                            Reference(13, 'fact', '12.50 ± 0.02 mm', 'data.csv:2@v1'),
                            Reference(14, 'procedure', 'python -m unittest'),
                            Reference(15, 'test', 'Tests not executed', 'notes@a1', 'not_run')])
    args.update(overrides)
    return Channel(**args)


class OZTests(unittest.TestCase):
    def test_compound_frame_and_implicit_subject(self):
        self.assertEqual(parse('a?3+8.', active=7),
                         (Atom('a', 7), Atom('?', 3), Atom('+', 8), Atom('.')))

    def test_exact_round_trip_for_each_operation(self):
        ch = channel()
        for wire in ['a7', 'r13', 't14', '>12', '=13', '~10', '?3', '+8', '-9', '!11', '.', '/', '+8.']:
            with self.subTest(wire=wire):
                atoms = ch.accept(wire, binding=ch.binding)
                self.assertEqual(ch.accept(ch.encode(atoms), binding=ch.binding), atoms)

    def test_new_information_is_lossless(self):
        ch = channel()
        for text in ['12.50 ± 0.02 mm; method unknown', 'do not change API\n?3 is quoted text', '日本語𓂀']:
            with self.subTest(text=text):
                atoms = (Atom(':', text=text),)
                self.assertEqual(ch.accept(ch.encode(atoms), binding=ch.binding), atoms)

    def test_rejects_ambiguous_or_malformed_input(self):
        for wire in ['', ':', ':  ', 'a07', 'a0', '+', '.8', 'a10000', 'a 7', 'A7', 'x7', 'a7;?3', 'a7:literal', 'a7\n+8', '+８']:
            with self.subTest(wire=wire), self.assertRaises(Error):
                parse(wire, active=7)

    def test_no_implicit_target_without_context(self):
        with self.assertRaises(Error):
            parse('a')

    def test_no_implicit_evidence_even_with_active(self):
        for wire in ['+', '-', '=', '~', '!', '?']:
            with self.subTest(wire=wire), self.assertRaises(Error):
                parse(wire, active=7)

    def test_unknown_reference_can_only_be_requested(self):
        ch = channel()
        self.assertEqual(ch.accept('?3', binding=ch.binding), (Atom('?', 3),))
        with self.assertRaises(Error):
            ch.accept('r3', binding=ch.binding)

    def test_reference_types_and_test_status_are_checked(self):
        ch = channel()
        for wire in ['+9', '-8', '+15', '=10', '~13', 'a14', '>7', '!7']:
            with self.subTest(wire=wire), self.assertRaises(Error):
                ch.accept(wire, binding=ch.binding)

    def test_finish_and_stop_are_terminal(self):
        ch = channel()
        for wire in ['.a7', '/a7', '..', './']:
            with self.subTest(wire=wire), self.assertRaises(Error):
                ch.accept(wire, binding=ch.binding)

    def test_binding_covers_routing_revision_goal_and_context(self):
        one = channel()
        for change in [dict(session='s2'), dict(task='T2'), dict(revision=2),
                       dict(sender='other'), dict(recipient='other'), dict(goal='Other goal'), dict(active=8)]:
            other = channel(**change)
            with self.subTest(change=change), self.assertRaises(Error):
                other.accept('a7', binding=one.binding)

    def test_source_constraints_and_no_duplicate_reference_aliases(self):
        for refs in [[Reference(7, 'fact', 'No source')],
                     [Reference(7, 'test', 'Tests passed', '', 'passed')],
                     [Reference(7, 'patch', 'p'), Reference(7, 'patch', 'q')]]:
            with self.subTest(refs=refs), self.assertRaises(Error):
                channel(references=refs)

    def test_single_atom_can_be_one_character(self):
        ch = channel()
        self.assertEqual(ch.encode([Atom('a', 7)]), 'a')

    def test_encoder_uses_measured_whole_message_cost(self):
        ch = channel()
        # A synthetic tokenizer tests nonadditive selection, not real token savings.
        counter = lambda s: 1 if s == 'a7' else 3
        self.assertEqual(ch.encode([Atom('a', 7)], counters=[counter]), 'a7')

    def test_encoder_considers_multiple_tokenizers(self):
        ch = channel()
        first = lambda s: 1 if s == 'a7' else 2
        second = lambda s: 8 if s == 'a7' else 2
        self.assertEqual(ch.encode([Atom('a', 7)], counters=[first, second]), 'a')

    def test_invalid_ast_is_not_silently_repaired(self):
        ch = channel()
        for atoms in [[], [Atom('x')], [Atom('a')], [Atom('.', 7)], [Atom('a', 0)], [Atom('a', 7, 'extra')]]:
            with self.subTest(atoms=atoms), self.assertRaises(Error):
                ch.encode(atoms)

    def test_evidence_and_units_survive_input_rendering(self):
        ch = channel()
        text = ch.context([Atom('=', 13)])
        self.assertIn('12.50 ± 0.02 mm', text)
        self.assertIn('data.csv:2@v1', text)
        self.assertNotIn('Measurement method missing', text)

    def test_adaptive_path_charges_dictionary(self):
        ch = channel()
        result = ch.prepare([Atom('a', 7)], counters=[len])
        self.assertEqual(result['mode'], 'plain')
        self.assertLess(result['tokens'][0], result['alternatives']['oz'][0])
        self.assertEqual(result['wire'], 'a')

    def test_literal_path_has_no_unnecessary_codebook(self):
        ch = channel()
        result = ch.prepare([Atom(':', text='New fact, not verified.')], counters=[len])
        self.assertEqual(set(result['alternatives']), {'plain'})

    def test_bad_counter_is_rejected(self):
        with self.assertRaises(Error):
            channel().encode([Atom('a', 7)], counters=[lambda text: -1])

    def test_prompt_is_bound_to_defined_atoms(self):
        self.assertIn('aN=', prompt(['a']))
        self.assertNotIn('+N=', prompt(['a']))
        with self.assertRaises(Error):
            prompt(['unknown'])

    def test_status_frames_do_not_require_another_model_call(self):
        ch = channel()
        result = ch.dispatch('+8.', binding=ch.binding)
        self.assertFalse(result['needs_model'])
        self.assertEqual([e['event'] for e in result['host_events']], ['passed', 'done'])
        self.assertEqual(result['host_events'][0]['record']['source'], 'test.log@a1')
        self.assertEqual(result['work'], ())

    def test_reasoning_work_remains_explicit_and_missing_refs_do_not_get_invented(self):
        ch = channel()
        result = ch.dispatch('a?3', binding=ch.binding)
        self.assertTrue(result['needs_model'])
        self.assertEqual(result['work'], (Atom('a', 7),))
        self.assertIsNone(result['host_events'][0]['record'])

    def test_dispatch_cannot_bypass_evidence_validation(self):
        ch = channel()
        with self.assertRaises(Error):
            ch.dispatch('+15.', binding=ch.binding)


if __name__ == '__main__':
    unittest.main()
