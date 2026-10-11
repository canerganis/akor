import random
import unittest

from oz import Atom, Channel, Codebook, Error, Macro, RULES, parse
from test_oz import channel


def extended(**overrides):
    return channel(codebook=Codebook([
        Macro('V', (Atom('r', 0), Atom('a', 0), Atom('t', 14))),
        Macro('P', (Atom('r', 13), Atom('>', 12))),
    ]), **overrides)


class MacroTests(unittest.TestCase):
    def test_parameterized_macro_preserves_order_and_exact_references(self):
        ch = extended()
        expected = (Atom('r', 7), Atom('a', 7), Atom('t', 14))
        for wire in ['V', 'V7', 'r7a7t14']:
            self.assertEqual(ch.accept(wire, binding=ch.binding), expected)
        self.assertEqual(ch.encode(expected), 'V')
        self.assertEqual(ch.accept('P', binding=ch.binding), (Atom('r', 13), Atom('>', 12)))

    def test_no_hidden_success_or_recursive_expansion(self):
        for code in ['+', '-', '=', '~', '.', '/', '?', '!', ':', 'V']:
            with self.subTest(code=code), self.assertRaises(Error):
                Macro('V', (Atom('r', 0), Atom(code, 8)))

    def test_macro_declarations_are_bounded_and_unambiguous(self):
        for code, steps in [('v', [Atom('r', 0)] * 2), ('VV', [Atom('r', 0)] * 2),
                            ('V', [Atom('r', 0)]), ('V', [Atom('r', 0)] * 17),
                            ('V', [Atom('r', True)] * 2), ('V', [Atom('r', 10000)] * 2)]:
            with self.subTest(code=code, steps=steps), self.assertRaises(Error):
                Macro(code, steps)
        m = Macro('V', [Atom('r', 0), Atom('r', 0)])
        with self.assertRaises(Error):
            Codebook([m, m])

    def test_macro_reference_type_and_existence_are_checked(self):
        ch = extended()
        for wire in ['V13', 'V3', 'V0', 'P7', 'Q', 'V07']:
            with self.subTest(wire=wire), self.assertRaises(Error):
                ch.accept(wire, binding=ch.binding)
        for steps in [(Atom('a', 0), Atom('t', 0)), (Atom('r', 0), Atom('t', 7)),
                      (Atom('r', 0), Atom('t', 500))]:
            with self.subTest(steps=steps), self.assertRaises(Error):
                channel(codebook=Codebook([Macro('V', steps)]))

    def test_expanded_limit_and_terminal_rules_apply(self):
        ch = extended()
        with self.assertRaises(Error):
            ch.accept('V' * 22, binding=ch.binding)
        with self.assertRaises(Error):
            ch.accept('.V', binding=ch.binding)
        self.assertEqual(len(ch.accept('V' * 21 + '.', binding=ch.binding)), 64)

    def test_unknown_dictionary_cannot_silently_interoperate(self):
        ch = extended()
        with self.assertRaises(Error):
            channel().accept('V', binding=ch.binding)
        other = channel(codebook=Codebook([Macro('V', (Atom('a', 0), Atom('r', 0)))]))
        self.assertNotEqual(ch.binding, other.binding)

    def test_codebooks_and_rule_maps_cannot_be_publicly_mutated(self):
        book = extended().codebook
        with self.assertRaises(TypeError):
            book.macros['V'] = None
        with self.assertRaises(AttributeError):
            book.macros = {}
        with self.assertRaises(TypeError):
            RULES['a'] = None

    def test_snapshot_is_independent_and_portable(self):
        ch = extended()
        snapshot = ch.snapshot()
        restored = Channel.from_snapshot(snapshot)
        self.assertEqual(ch.binding, restored.binding)
        snapshot['references'][0]['text'] = 'mutated'
        snapshot['macros'][0]['steps'][0]['ref'] = 90
        self.assertEqual(ch.binding, restored.binding)
        self.assertEqual(restored.encode(restored.accept('V', binding=restored.binding)), 'V')
        self.assertNotIn('mutated', ch.context([Atom('r', 7)]))

    def test_optimizer_can_reject_byte_shortest_spelling(self):
        ch = extended()
        atoms = ch.accept('V', binding=ch.binding)
        counter = lambda text: 1 if text == 'V7' else 10
        self.assertEqual(ch.encode(atoms, counters=[counter]), 'V7')

    def test_candidate_search_is_bounded_and_keeps_explicit_path(self):
        ch = extended()
        atoms = ch.accept('V' * 20, binding=ch.binding)
        seen = []
        ch.encode(atoms, counters=[lambda text: seen.append(text) or len(text)], candidate_limit=16)
        self.assertLessEqual(len(seen), 16)
        self.assertIn('r7a7t14' * 20, seen)
        self.assertIn('V' * 20, seen)

    def test_random_legal_sequences_round_trip_without_drift(self):
        rng = random.Random(571)
        ch = extended()
        fragments = ['V7', 'a7', 'r13', '>12', 't14', 'P', '=13', '~10', '?3', '+8', '-9', '!11']
        for _ in range(250):
            wire = ''.join(rng.choices(fragments, k=rng.randint(1, 8))) + rng.choice(['', '.', '/'])
            atoms = ch.accept(wire, binding=ch.binding)
            compressed = ch.encode(atoms, candidate_limit=32)
            self.assertEqual(ch.accept(compressed, binding=ch.binding), atoms)

    def test_literal_cannot_be_misread_as_a_macro(self):
        ch = extended()
        wire = ':V7\n+8.\n12.50 ± 0.02 mm — 未验证'
        self.assertEqual(ch.encode(ch.accept(wire, binding=ch.binding)), wire)

    def test_prompt_includes_only_needed_macro_dependencies(self):
        text = extended().codebook.prompt(['V'])
        self.assertIn('OZ/2.', text)
        self.assertIn('VN=rNaNt14', text)
        self.assertIn('aN=', text)
        self.assertNotIn('P=', text)
        self.assertNotIn('+N=', text)

    def test_v1_parser_still_rejects_undeclared_macros(self):
        with self.assertRaises(Error):
            parse('V7', active=7)

    def test_read_accepts_procedure_as_source_data(self):
        ch = extended()
        self.assertEqual(ch.accept('r14', binding=ch.binding), (Atom('r', 14),))


if __name__ == '__main__':
    unittest.main()
