"""OZ/2 macro compiler: measured, lossless and never mutating live channels."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from oz import Channel, Error, Reference
from oz_batch import REPLY_CONTRACTS
from oz_compiler import compile_messages
from oz_cli import main


def channel():
    return Channel(session='compile', task='review', revision=1, sender='lead', recipient='worker',
                   goal='Synthetic requests only; preserve exact constraints.', active=1,
                   references=[*[Reference(n, 'patch', f'Synthetic patch {n}; 12.50 ± 0.02 mm; method unknown.')
                                 for n in range(1, 25)],
                               Reference(30, 'procedure', 'Request relevant tests; report failures.')])


class CompilerTests(unittest.TestCase):
    def test_full_cost_guard_rejects_useless_dictionary(self):
        ch = channel()
        snap = ch.snapshot()
        result = compile_messages(ch, [('m', 'r1')], counters=[len])
        self.assertFalse(result.changed)
        self.assertEqual(result.channel.binding, ch.binding)
        self.assertEqual(ch.snapshot(), snap)
        self.assertEqual(result.packet.tokens, result.baseline.tokens)

    def test_learns_repeated_exact_sequence_and_charges_full_context(self):
        ch = channel()
        wire = ''.join(f'r{n}a{n}t30' for n in range(1, 17))
        messages = [(f'm{i}', ''.join(f'r{n}a{n}t30' for n in range(1 + i, 17 + i))) for i in range(4)]
        result = compile_messages(ch, messages, counters=[len], max_macros=2, reply_mode='lanes')
        self.assertTrue(result.changed)
        self.assertTrue(result.added_macros)
        self.assertLess(result.packet.tokens[0], result.baseline.tokens[0])
        self.assertEqual(result.channel.scope[-1], ch.scope[-1] + 1)
        for (mid, encoded), (_, original) in zip(result.messages, messages):
            self.assertEqual(result.channel.accept(encoded, binding=result.channel.binding), ch.accept(original, binding=ch.binding))
        self.assertIn(REPLY_CONTRACTS['lanes'], result.packet.text)
        self.assertTrue(result.packet.mode.startswith('oz/'))
        self.assertIn('12.50 ± 0.02 mm', result.packet.text)
        with self.assertRaises(Error):
            ch.accept(result.messages[0][1], binding=result.channel.binding)

    def test_each_target_counter_must_not_regress(self):
        ch = channel()
        messages = [('m', 'r1a1t30' * 16)]
        # A deliberately adversarial second target makes every macro
        # dictionary too costly. A lexicographic max-only rule would miss this.
        counter = lambda text: len(text) + (100000 if ('Macros expand' in text) else 0)
        result = compile_messages(ch, messages, counters=[len, counter], max_macros=1)
        self.assertTrue(all(a <= b for a, b in zip(result.packet.tokens, result.baseline.tokens)))

    def test_literals_claims_and_new_information_are_never_mined(self):
        ch = channel()
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
        ch = channel()
        messages = [['m', 'r1a1t30' * 16]]
        # This test verifies the CLI contract, not token savings. Actual
        # tokenizer measurements live in oz_encoding_benchmark.py.
        tokenizer = SimpleNamespace(get_encoding=lambda name: SimpleNamespace(
            name=name, encode=lambda text, **kwargs: text))
        with tempfile.TemporaryDirectory() as temp, patch.dict('sys.modules', tiktoken=tokenizer):
            root = Path(temp)
            (root / 'in.json').write_text(json.dumps(ch.snapshot()), encoding='utf-8')
            (root / 'messages.json').write_text(json.dumps(messages), encoding='utf-8')
            args = ['compile', '--channel', str(root / 'in.json'), '--messages', str(root / 'messages.json'),
                    '--out', str(root / 'out'), '--max-macros', '1']
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(args), 0)
            report = json.loads(out.getvalue())
            self.assertEqual(report['reply_mode'], 'rows')
            prompt = (root / 'out/prompt.txt').read_bytes().decode('utf-8')
            self.assertEqual(len(prompt), report['after_tokens'][0])
            compiled = Channel.from_snapshot(json.loads((root / 'out/channel.json').read_text(encoding='utf-8')))
            wire = json.loads((root / 'out/messages.json').read_text(encoding='utf-8'))[0][1]
            self.assertEqual(compiled.accept(wire, binding=compiled.binding), ch.accept(messages[0][1], binding=ch.binding))
            saved = (root / 'out/channel.json').read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)
            self.assertEqual((root / 'out/channel.json').read_bytes(), saved)


if __name__ == '__main__':
    unittest.main()
