import json
import contextlib
import io
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from oz import Atom, Channel, Codebook, Error, Macro, Reference
from oz_batch import render
from oz_compiler import compile_messages
from oz_cli import main
from oz_runtime import Inbox


def channel(*, vectors=True, macros=True):
    return Channel(session='vector', task='review', revision=1, sender='lead', recipient='worker',
                   goal='Synthetic requests only; preserve exact constraints.', active=1,
                   references=[*[Reference(n, 'patch', f'Synthetic patch {n}; 12.50 ± 0.02 mm; method unknown.')
                                 for n in range(1, 25)],
                               Reference(30, 'procedure', 'Request relevant tests; report failures.')],
                   codebook=Codebook([Macro('V', (Atom('r', 0), Atom('a', 0), Atom('t', 30)))]
                                     if macros else [], vectors=vectors))


class VectorTests(unittest.TestCase):
    def test_range_means_complete_macro_per_target(self):
        ch = channel()
        actual = ch.accept('V[1:16]', binding=ch.binding)
        expected = tuple(a for n in range(1, 17) for a in [Atom('r', n), Atom('a', n), Atom('t', 30)])
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 48)
        self.assertEqual(ch.encode(actual), 'V[1:16]')

    def test_lists_keep_order_and_duplicates(self):
        ch = channel()
        self.assertEqual(ch.accept('r[7,2:4,2]', binding=ch.binding),
                         tuple(Atom('r', n) for n in [7, 2, 3, 4, 2]))

    def test_malformed_and_claim_vectors_rejected(self):
        ch = channel()
        for wire in ['r[]', 'r[0]', 'r[01]', 'r[1,]', 'r[1 2]', 'r[3:1]', 'r[1:10000]',
                     'r[1:9999]', 'r[1', 'r[[1]]', 'r[1]2', 'r[1:2:3]', 'r[١]',
                     '+[1,2]', '?[1,2]', '.[1,2]', '=[1,2]', 'V[1:22]']:
            with self.subTest(wire=wire), self.assertRaises(Error):
                ch.accept(wire, binding=ch.binding)

    def test_fixed_macros_cannot_take_a_vector(self):
        snap = channel().snapshot()
        snap['macros'] = [dict(code='F', steps=[vars(Atom('r', 1)), vars(Atom('a', 1))])]
        ch = Channel.from_snapshot(snap)
        with self.assertRaises(Error):
            ch.accept('F[1,2]', binding=ch.binding)

    def test_types_missing_refs_terminals_and_expansion_bounds(self):
        ch = channel()
        for wire in ['V[1,30]', 'r[23:25]', '.r[1,2]', 'V[1:21]r1.']:
            with self.subTest(wire=wire), self.assertRaises(Error):
                ch.accept(wire, binding=ch.binding)
        self.assertEqual(len(ch.accept('V[1:21].', binding=ch.binding)), 64)

    def test_literals_remain_exact(self):
        ch = channel()
        wire = ':V[1:9999]\r\n0.05 wt%; 未验证; do not execute.'
        self.assertEqual(ch.encode(ch.accept(wire, binding=ch.binding)), wire)

    def test_old_channels_reject_vectors_and_keep_binding(self):
        ch = channel(vectors=False)
        with self.assertRaises(Error):
            ch.accept('V[1:16]', binding=ch.binding)
        self.assertNotEqual(ch.binding, channel().binding)
        path = Path(__file__).parents[1] / 'examples/oz2-channel.json'
        old = Channel.from_snapshot(json.loads(path.read_text(encoding='utf-8')))
        # Captured from 0.4.0 before changing the parser (UTF-8 fixture).
        self.assertEqual(old.binding, 'f4eaee805ef77d70c4e322d1bd7a4a31fb9ad77d709798e1a555b21abb9b8132')
        self.assertNotIn('vectors', old.snapshot())

    def test_snapshot_and_grammar_opt_in_are_bound(self):
        ch = channel()
        self.assertEqual(Channel.from_snapshot(ch.snapshot()).binding, ch.binding)
        self.assertIn('OZ/3.', ch.codebook.prompt())
        self.assertNotIn('[IDs]', ch.codebook.prompt(['V'], vectors=False))
        with self.assertRaises(AttributeError):
            ch.codebook.vectors = False
        for bad in [1, 'true', None]:
            with self.assertRaises(Error):
                Codebook(vectors=bad)

    def test_random_ordered_work_round_trips(self):
        rng, ch = random.Random(603), channel()
        for _ in range(180):
            refs = [rng.randint(1, 24) for _ in range(rng.randint(2, 20))]
            wire = 'V[' + ','.join(map(str, refs)) + ']'
            expected = ch.accept(wire, binding=ch.binding)
            for candidate in ch.spellings(expected, limit=16):
                self.assertEqual(ch.accept(candidate, binding=ch.binding), expected)

    def test_scalar_fallback_avoids_unneeded_vector_grammar(self):
        ch = channel()
        packet = render(ch, [('m', 'r1')], counters=[len])
        self.assertIn('oz_scalar/tuples', packet.alternatives)
        self.assertLessEqual(packet.tokens[0], packet.alternatives['oz_scalar/tuples'][0])
        self.assertNotIn('Work codes and parameterized macros accept', packet.text)

    def test_queue_deduplicates_equivalent_vectors(self):
        ch = channel()
        with Inbox() as box:
            self.assertTrue(box.post(ch, 'm', 'r[1:3]', binding=ch.binding))
            self.assertFalse(box.post(ch, 'm', 'r1r2r3', binding=ch.binding))


class CompilerTests(unittest.TestCase):
    def test_full_cost_guard_rejects_useless_dictionary(self):
        ch = channel(vectors=False, macros=False)
        snap = ch.snapshot()
        result = compile_messages(ch, [('m', 'r1')], counters=[len])
        self.assertFalse(result.changed)
        self.assertEqual(result.channel.binding, ch.binding)
        self.assertEqual(ch.snapshot(), snap)
        self.assertEqual(result.packet.tokens, result.baseline.tokens)

    def test_learns_repeated_exact_sequence_and_charges_full_context(self):
        ch = channel(vectors=False, macros=False)
        wire = ''.join(f'r{n}a{n}t30' for n in range(1, 17))
        messages = [(f'm{i}', wire) for i in range(4)]
        result = compile_messages(ch, messages, counters=[len], max_macros=2,
                                  response_contract='KEEP EXACT OUTPUT CONTRACT', additional_context='EXACT PREDECESSOR')
        self.assertTrue(result.changed)
        self.assertTrue(result.added_macros)
        self.assertLess(result.packet.tokens[0], result.baseline.tokens[0])
        self.assertEqual(result.channel.scope[-1], ch.scope[-1] + 1)
        for (mid, encoded), (_, original) in zip(result.messages, messages):
            self.assertEqual(result.channel.accept(encoded, binding=result.channel.binding), ch.accept(original, binding=ch.binding))
        self.assertIn('KEEP EXACT OUTPUT CONTRACT', result.packet.text)
        self.assertIn('EXACT PREDECESSOR', result.packet.text)
        self.assertIn('12.50 ± 0.02 mm', result.packet.text)
        with self.assertRaises(Error):
            ch.accept(result.messages[0][1], binding=result.channel.binding)

    def test_each_target_counter_must_not_regress(self):
        ch = channel(vectors=False, macros=False)
        messages = [('m', 'r1a1t30' * 16)]
        # A deliberately adversarial second target makes every macro/range
        # dictionary too costly. A lexicographic max-only rule would miss this.
        counter = lambda text: len(text) + (100000 if ('Macros expand' in text or '[IDs]' in text) else 0)
        result = compile_messages(ch, messages, counters=[len, counter], max_macros=1)
        self.assertTrue(all(a <= b for a, b in zip(result.packet.tokens, result.baseline.tokens)))

    def test_literals_claims_and_new_information_are_never_mined(self):
        ch = channel(vectors=False, macros=False)
        wire = ':r1a1t30\r\n12.50 ± 0.02 mm; not verified.'
        result = compile_messages(ch, [('m', wire)], counters=[len])
        self.assertEqual(result.messages, (('m', wire),))
        self.assertFalse(result.added_macros)
        self.assertFalse(result.changed)

    def test_compiler_bounds_and_missing_counters(self):
        ch = channel()
        for kwargs in [dict(max_macros=9), dict(template_limit=0), dict(candidate_limit=1), dict(counters=[])]:
            options = dict(counters=[len]) | kwargs
            with self.subTest(kwargs=kwargs), self.assertRaises(Error):
                compile_messages(ch, [('m', 'r1')], **options)

    def test_cli_compiles_portable_bundle_without_overwriting(self):
        ch = channel(vectors=False, macros=False)
        messages = [['m', 'r1a1t30' * 16]]
        # This test verifies the CLI contract, not token savings. Actual
        # tokenizer measurements live in oz3_benchmark.py.
        tokenizer = SimpleNamespace(get_encoding=lambda name: SimpleNamespace(
            name=name, encode=lambda text, **kwargs: text))
        with tempfile.TemporaryDirectory() as temp, patch.dict('sys.modules', tiktoken=tokenizer):
            root = Path(temp)
            (root / 'in.json').write_text(json.dumps(ch.snapshot()), encoding='utf-8')
            (root / 'messages.json').write_text(json.dumps(messages), encoding='utf-8')
            args = ['compile', '--channel', str(root / 'in.json'), '--messages', str(root / 'messages.json'),
                    '--out', str(root / 'out'), '--worker', '--max-macros', '1']
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(args), 0)
            report = json.loads(out.getvalue())
            self.assertTrue(report['worker_contract_included'])
            prompt = (root / 'out/prompt.txt').read_bytes().decode('utf-8')
            self.assertEqual(len(prompt), report['after_tokens'][0])
            compiled = Channel.from_snapshot(json.loads((root / 'out/channel.json').read_text(encoding='utf-8')))
            wire = json.loads((root / 'out/messages.json').read_text(encoding='utf-8'))[0][1]
            self.assertEqual(compiled.accept(wire, binding=compiled.binding), ch.accept(messages[0][1], binding=ch.binding))
            saved = (root / 'out/channel.json').read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)
            self.assertEqual((root / 'out/channel.json').read_bytes(), saved)

    def test_compiled_channel_persists_and_reopens_with_new_binding(self):
        ch = channel()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'inbox.sqlite3'
            with Inbox(path) as box:
                box.post(ch, 'm', 'V[1:16]', binding=ch.binding)
            restored = Channel.from_snapshot(ch.snapshot())
            with Inbox(path) as box:
                delivery = box.claim(restored, owner='test')
                self.assertEqual(len(delivery.jobs), 1)
                self.assertEqual(len(restored.accept(delivery.jobs[0].wire, binding=restored.binding)), 48)


if __name__ == '__main__':
    unittest.main()
