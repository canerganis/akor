import contextlib
import io
import json
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from examples.oz5_demo import example_channel, messages
from oz import Atom, Channel, Error
from oz_batch import render
from oz_cli import main
from oz_compiler import compile_messages
from oz_form import form_spelling, infer_forms
from oz_runtime import Inbox
from oz_worker import Worker, RESPONSE_CONTRACT
from oz_weave import compact_column, decode_matrix, encode_matrix, expand_column, matrix_body


def channel(form=None):
    snapshot = example_channel().snapshot()
    snapshot['form'] = [vars(a) for a in (form if form is not None else
                         (Atom('r', -1), Atom('a', -1), Atom('t', -2), Atom('>', 41)))]
    return Channel.from_snapshot(snapshot)


class FormTests(unittest.TestCase):
    def test_multiple_independent_arguments_and_repeated_slots(self):
        ch = channel()
        self.assertEqual(ch.accept('&7,31', binding=ch.binding), ch.accept('r7a7t31>41', binding=ch.binding))
        self.assertEqual(ch.fill_form(7, 31), '&7,31')
        self.assertEqual(form_spelling(ch.form, ch.accept('r7a7t31>41', binding=ch.binding)), '&7,31')
        self.assertIn('&7,31', ch.spellings(ch.accept('r7a7t31>41', binding=ch.binding)))

    def test_all_arguments_required_and_no_hidden_defaults_or_recursion(self):
        ch = channel()
        for wire in ['&', '&7', '&7,31,32', '&0,31', '&07,31', '&7,031', '&-1,31',
                     '&7,10000', '&7,31,', '&7, 31', '&7,31\n', '&7;31', '&7,^', '&7,:text',
                     '&7,31.', '&7,31/', '&7,31' * 2000]:
            with self.subTest(wire=wire[:30]), self.assertRaises(Error):
                ch.accept(wire, binding=ch.binding)

    def test_missing_and_incompatible_values_rejected(self):
        ch = channel()
        for values in [(999, 31), (30, 31), (7, 7), (7, True), (), (7,), (7, 31, 32)]:
            with self.subTest(values=values), self.assertRaises(Error):
                ch.fill_form(*values)

    def test_form_validation_types_bounds_and_contiguous_slots(self):
        bad = [[], [Atom('r', 0)], [Atom('r', True)], [Atom('r', -33)], [Atom('r', -2)],
               [Atom('r', -1), Atom('r', -3)], [Atom('r', 1)], [Atom('a', -1), Atom('t', -1)],
               [Atom('r', -1), Atom('a', 30)], [Atom('r', -1), Atom('r', 999)],
               [Atom('r', -1)] * 65]
        bad += [[Atom(c, -1)] for c in ['=', '~', '?', '+', '-', '!', '.', '/', ':', 'V', '&', '^']]
        bad += [[Atom('r', -1, 'hidden text')]]
        for form in bad:
            with self.subTest(form=form[:2]), self.assertRaises(Error):
                channel(form)

    def test_maximum_form_and_slots(self):
        ch = channel([Atom('r', -n) for n in range(1, 33)] * 2)
        wire = ch.fill_form(*([1] * 32))
        self.assertEqual(len(ch.accept(wire, binding=ch.binding)), 64)

    def test_binding_portability_immutability_and_legacy_hashes(self):
        ch = channel()
        self.assertEqual(ch.binding, Channel.from_snapshot(ch.snapshot()).binding)
        changed = channel([Atom('r', -1), Atom('a', -1), Atom('t', -2)])
        with self.assertRaises(Error):
            changed.accept('&7,31', binding=ch.binding)
        with self.assertRaises(AttributeError):
            ch.form = ()
        old = example_channel()
        self.assertNotIn('form', old.snapshot())
        self.assertEqual(old.binding, Channel.from_snapshot(old.snapshot()).binding)
        with self.assertRaises(Error):
            old.accept('&7,31', binding=old.binding)
        # This checked-in pre-OZ/5 binding must remain byte-identical.
        root = Path(__file__).parents[1]
        old4 = Channel.from_snapshot(json.loads((root / 'examples/oz4-training-channel.json').read_text(encoding='utf-8')))
        self.assertEqual(old4.binding, 'c9ef165a1c14ef1e2e6daf759c010c960289a27b30b156be33f23c402e8c8fce')

    def test_only_used_form_grammar_is_sent_and_literal_is_exact(self):
        ch = channel()
        self.assertIn('Form=r$0a$0t$1>41', ch.dictionary(['&7,31']))
        self.assertIn('Form=r$0a$0t$1>41', ch.prompt())
        self.assertNotIn('Form=', ch.dictionary(['r7']))
        literal = ':&7,31\r\n12.5 ± 0.02; unknown cause.'
        self.assertEqual(ch.encode(ch.accept(literal, binding=ch.binding)), literal)

    def test_schema_inference_preserves_correlations_without_guessing(self):
        ch = example_channel()
        frames = [ch.accept(w, binding=ch.binding) for w in ['r1a1t30>41', 'r2a2t31>41', 'r3a3t32>41']]
        expected = (Atom('r', -1), Atom('a', -1), Atom('t', -2), Atom('>', 41))
        self.assertEqual(infer_forms(frames), (expected,))
        # Unseen equality violations and new constants never silently coerce.
        for wire in ['r1a2t31>41', 'r1a1t31>42', 'r1a1t31', 'r1a1t31.']:
            self.assertIsNone(form_spelling(expected, ch.accept(wire, binding=ch.binding)))
        self.assertEqual(infer_forms([frames[0]] * 64), ())
        self.assertEqual(infer_forms([(Atom(':', text='r1a1'),)]), ())

    def test_random_reference_bindings_exactly_round_trip(self):
        rng = random.Random(705)
        ch = example_channel(form=True)
        for _ in range(250):
            values = [rng.randint(1, 24) for _ in range(4)] + [rng.randint(30, 32) for _ in range(5)]
            wire = ch.fill_form(*values)
            atoms = ch.accept(wire, binding=ch.binding)
            self.assertEqual(form_spelling(ch.form, atoms), wire)
            self.assertEqual(ch.accept(ch.encode(atoms, candidate_limit=8), binding=ch.binding), atoms)

    def test_compiler_full_cost_and_held_out_fallback(self):
        ch, rows = example_channel(), messages()
        result = compile_messages(ch, rows, counters=[len], max_macros=0, forms=True,
                                  response_contract='OUTPUT CONTRACT', additional_context='EXACT PRIOR OUTPUT')
        self.assertTrue(result.channel.form)
        self.assertLess(result.packet.tokens[0], result.before_form_tokens[0])
        self.assertIn('Form=', result.packet.text)
        self.assertIn('OUTPUT CONTRACT', result.packet.text)
        self.assertIn('EXACT PRIOR OUTPUT', result.packet.text)
        self.assertEqual(result.channel.scope[-1], ch.scope[-1] + 1)
        for (_, wire), (_, original) in zip(result.messages, rows):
            self.assertEqual(result.channel.accept(wire, binding=result.channel.binding), ch.accept(original, binding=ch.binding))
        # Arbitrary unseen work still has an ordinary absolute representation.
        unseen = result.channel.accept('r1a2t31>42', binding=result.channel.binding)
        self.assertEqual(result.channel.accept(result.channel.encode(unseen), binding=result.channel.binding), unseen)

    def test_old_and_absolute_fallbacks_are_measured(self):
        ch = channel()
        packet = render(ch, [('m', '&7,31')], counters=[len])
        self.assertIn('oz_previous/tuples', packet.alternatives)
        self.assertIn('oz_absolute/tuples', packet.alternatives)
        self.assertLessEqual(packet.tokens[0], packet.alternatives['oz_previous/tuples'][0])

    def test_all_target_counters_must_not_regress(self):
        ch = example_channel()
        adversary = lambda text: len(text) + (100000 if 'OZ/5' in text else 0)
        result = compile_messages(ch, messages(), counters=[len, adversary], max_macros=0, forms=True)
        self.assertFalse(result.channel.form)
        self.assertTrue(all(a <= b for a, b in zip(result.packet.tokens, result.before_form_tokens)))

    def test_small_and_identical_messages_do_not_add_dictionary(self):
        ch = example_channel()
        for rows in [[('m', 'r1')], [(f'm{i}', 'r1a1t30') for i in range(64)]]:
            result = compile_messages(ch, rows, counters=[len], forms=True, max_macros=0)
            self.assertFalse(result.channel.form)

    def test_compiler_options(self):
        for opts in [dict(forms=1), dict(form_limit=0), dict(form_limit=17)]:
            with self.subTest(opts=opts), self.assertRaises(Error):
                compile_messages(example_channel(), [('m', 'r1')], counters=[len], **opts)

    def test_queue_semantic_identity_persistence_and_dependency_delivery(self):
        ch, seen = channel(), []
        def adapter(request):
            seen.append(request)
            self.assertIn(RESPONSE_CONTRACT, request['prompt'])
            return {'results': [[mid, 0, 'Synthetic acknowledgement; not code execution.'] for mid in request['ids']]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'jobs.sqlite'
            with Inbox(path) as box:
                box.post(ch, 'a', '&7,31', binding=ch.binding)
                self.assertFalse(box.post(ch, 'a', 'r7a7t31>41', binding=ch.binding))
                box.post(ch, 'b', '&8,32', binding=ch.binding, after=['a'])
            with Inbox(path) as box:
                restored = Channel.from_snapshot(ch.snapshot())
                worker = Worker(box, restored, adapter, counters=[len], max_tokens=10000)
                self.assertEqual(worker.run_once()['ids'], ['a'])
                self.assertEqual(worker.run_once()['ids'], ['b'])
                self.assertIn('Synthetic acknowledgement; not code execution.', seen[1]['prompt'])
                self.assertEqual(box.stats(), {'done': 2})

    def test_cli_compiles_saved_prompt_exactly_and_does_not_overwrite(self):
        tokenizer = SimpleNamespace(get_encoding=lambda name: SimpleNamespace(name=name, encode=lambda text, **kw: text))
        with tempfile.TemporaryDirectory() as temp, patch.dict('sys.modules', tiktoken=tokenizer):
            root = Path(temp)
            (root / 'in.json').write_text(json.dumps(example_channel().snapshot()), encoding='utf-8')
            (root / 'messages.json').write_text(json.dumps(messages()), encoding='utf-8')
            args = ['compile', '--channel', str(root / 'in.json'), '--messages', str(root / 'messages.json'),
                    '--out', str(root / 'out'), '--forms', '--max-macros', '0', '--worker']
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(args), 0)
            report = json.loads(output.getvalue())
            self.assertTrue(report['form_selected'])
            self.assertTrue(report['matrix_exported'])
            self.assertEqual(len((root / 'out/prompt.txt').read_bytes().decode('utf-8')), report['after_tokens'][0])
            saved = (root / 'out/channel.json').read_bytes()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)
            self.assertEqual((root / 'out/channel.json').read_bytes(), saved)
            unpack = ['unpack', '--channel', str(root / 'out/channel.json'), '--matrix', str(root / 'out/matrix.json')]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(unpack), 0)
            self.assertEqual(len(json.loads(output.getvalue())['messages']), 64)
            value = json.loads((root / 'out/matrix.json').read_text(encoding='utf-8'))
            value['binding'] = 'wrong'
            (root / 'out/matrix.json').write_text(json.dumps(value), encoding='utf-8')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(unpack), 2)


class MatrixTests(unittest.TestCase):
    def test_ranges_runs_and_flat_periods_preserve_order(self):
        expected = (1, 2, 3, 8, 8, 30, 30, 31, 32, 30, 30, 31, 32)
        self.assertEqual(expand_column('1:3,8*2,(30*2,31:32)*2', count=13), expected)
        self.assertEqual(expand_column('1*64', count=64), (1,) * 64)

    def test_malformed_ambiguous_and_excessive_columns_are_rejected(self):
        for value in ['', '0', '01', '1,', ',1', '1,,2', '3:1', '1:10000', '1:9999',
                      '1*0', '1*65', '1*999999', '1*-2', '1:2*3', '1**2', '1 2', '1\n',
                      '()', '(1,2)', '(1,2)*0', '(1,2)*33', '((1,2)*2)*2', '(1,2)*2,',
                      '(1,2)*2x', '1,__import__("os")', '(1,2)*2(1,2)*2']:
            with self.subTest(value=value), self.assertRaises(Error):
                expand_column(value, count=64)
        with self.assertRaises(Error):
            expand_column('1:2', count=3)
        for count in [0, 65, True]:
            with self.assertRaises(Error):
                expand_column('1', count=count)

    def test_random_columns_round_trip(self):
        rng = random.Random(505)
        sequences = [(30, 31, 32) * 21 + (30,), tuple(range(1, 25)) * 2 + tuple(range(1, 17)),
                     (30,) * 27 + (31,) * 27 + (32,) * 10]
        sequences += [tuple(rng.randint(1, 9999) for _ in range(rng.randint(1, 64))) for _ in range(80)]
        sequences += [tuple(rng.randint(30, 32) for _ in range(64)) for _ in range(30)]
        for values in sequences:
            encoded = compact_column(values, counters=[len])
            self.assertEqual(expand_column(encoded, count=len(values)), values)
        for invalid in [(), (0,), (True,), (10000,), (1,) * 65]:
            with self.assertRaises(Error):
                compact_column(invalid)

    def test_matrix_all_ids_are_independent_and_payload_is_exact(self):
        ch = channel()
        value = {'ids': ['one', 'two', 'three'], 'cols': ['7,7,8', '30:32']}
        rows = decode_matrix(ch, value, binding=ch.binding)
        self.assertEqual(rows, (('one', '&7,30'), ('two', '&7,31'), ('three', '&8,32')))
        frames = [ch.accept(w, binding=ch.binding) for _, w in rows]
        body = matrix_body(ch, [mid for mid, _ in rows], frames, counters=[len])
        recovered = decode_matrix(ch, json.loads(body.splitlines()[-1]), binding=ch.binding)
        self.assertEqual(rows, recovered)

    def test_matrix_shape_types_binding_and_ids_are_validated(self):
        ch = channel()
        valid = {'ids': ['m'], 'cols': ['7', '30']}
        bad = [dict(valid, extra=1), {'ids': ['m', 'm'], 'cols': ['7*2', '30*2']},
               {'ids': [], 'cols': []}, {'ids': 'm', 'cols': ['7', '30']},
               {'ids': ['m'], 'cols': ['7']}, {'ids': ['m'], 'cols': ['7*2', '30']},
               {'ids': ['m'], 'cols': ['7', '7']}, {'ids': ['m'], 'cols': ['999', '30']},
               {'ids': ['invalid id'], 'cols': ['7', '30']}]
        for record in bad:
            with self.subTest(record=record), self.assertRaises(Error):
                decode_matrix(ch, record, binding=ch.binding)
        with self.assertRaises(Error):
            decode_matrix(ch, valid, binding=example_channel().binding)
        with self.assertRaises(Error):
            encode_matrix(ch, ['m'], [])

    def test_mixed_shapes_fall_back_without_losing_any_work(self):
        ch = channel()
        rows = [('a', '&7,30'), ('b', 'r1a2t31'), ('c', ':Unknown new failure.\r\nKeep exact.')]
        frames = [ch.accept(w, binding=ch.binding) for _, w in rows]
        self.assertIsNone(matrix_body(ch, [mid for mid, _ in rows], frames, counters=[len]))
        packet = render(ch, rows, counters=[len])
        self.assertNotIn('oz_matrix/tuples', packet.alternatives)
        self.assertEqual(packet.ids, ('a', 'b', 'c'))
        for wire, frame in zip(packet.wires, frames):
            self.assertEqual(ch.accept(wire, binding=ch.binding), frame)

    def test_production_matrix_counts_full_prompt_and_round_trips(self):
        source, rows = example_channel(), messages()
        result = compile_messages(source, rows, counters=[len], forms=True, max_macros=0,
                                  response_contract=RESPONSE_CONTRACT, additional_context='Exact predecessor result.')
        self.assertEqual(result.packet.mode, 'oz_matrix/tuples')
        self.assertIn('Exact predecessor result.', result.packet.text)
        self.assertIn(RESPONSE_CONTRACT, result.packet.text)
        value = next(json.loads(line) for line in result.packet.text.splitlines() if line.startswith('{"cols":'))
        decoded = decode_matrix(result.channel, value, binding=result.channel.binding)
        for (mid, wire), (expected_mid, original) in zip(decoded, rows):
            self.assertEqual(mid, expected_mid)
            self.assertEqual(result.channel.accept(wire, binding=result.channel.binding),
                             source.accept(original, binding=source.binding))
        self.assertEqual(result.packet.tokens, (len(result.packet.text),))


if __name__ == '__main__':
    unittest.main()
