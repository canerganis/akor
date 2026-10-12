import json
from pathlib import Path
import re
import unittest

from oz import Error, Reference
from oz_batch import INSTRUCTIONS, SYSTEM, VERSION, WIRE, explicit, render, validate_packet
from test_oz import channel
from test_oz2 import extended

DESIGN = Path(__file__).resolve().parent.parent / 'docs' / 'design' / 'stage-1e-astra.md'

INSTRUCTION_TEXT = {
    'audit': 'Review the supplied patch for defects and unintended public-API changes. Report failures shown in '
             'supplied test results and recommend missing checks.',
    'observed': 'Report only observations supported by supplied evidence and cite its supplied source. State when '
                'evidence or its source is missing.',
    'propose': 'Offer a concise, actionable plan without applying it.',
    'inferred': 'Report a concise hypothesis, explicitly labeled as inference, with its supporting evidence and '
                'uncertainty.',
}
LONG = ':' + 'measurement 12.50 ± 0.02 mm; method unknown. ' * 6


def data(packet):
    return json.loads(packet.text)


def twins():
    """References 1 and 2 hold identical text; 3 is a proposal."""
    return channel(active=1, references=[Reference(1, 'patch', 'same'), Reference(2, 'patch', 'same'),
                                         Reference(3, 'proposal', 'other')])


class BatchTests(unittest.TestCase):
    def test_system_text_is_byte_exact_with_the_design_document(self):
        doc = DESIGN.read_text(encoding='utf-8')
        blocks = re.findall(r'aynen şöyledir:\*\*\s*```text\n(.*?)\n```', doc, re.S)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(SYSTEM.encode('utf-8'), blocks[0].encode('utf-8'))
        self.assertTrue(SYSTEM.startswith('You are an OZ/1e batch worker.\n\n'))
        self.assertTrue(SYSTEM.endswith('null is an ordinary result value, not a failure marker.'))
        self.assertEqual((WIRE, VERSION), ('stage-1e', 'oz/1e'))

    def test_system_text_is_independent_of_the_jobs(self):
        for rows in ([('j1', 'V')], [('x', ':text'), ('y', '>12')]):
            other = render(extended(), rows, counters=[len])
            self.assertEqual((other.system, other.mode), (SYSTEM, 'named'))

    def test_removed_reply_mode_is_rejected(self):
        with self.assertRaises(TypeError):
            render(extended(), [('a', 'V')], counters=[len], reply_mode='value')

    def test_handoffs_never_change_the_system_text(self):
        linked = render(extended(), [('b', '>12')], counters=[len], handoffs=[('b', 'prior', 'result')])
        self.assertEqual(linked.system, SYSTEM)
        self.assertEqual(linked.tokens, (len(linked.system) + 1 + len(linked.text),))

    def test_body_is_v_ops_refs_jobs_in_compact_json(self):
        packet = render(extended(), [('a', 'V'), ('b', '>12')], counters=[len], handoffs=[('b', 'prior', 'result')])
        self.assertEqual(list(data(packet)), ['v', 'ops', 'refs', 'jobs'])
        self.assertEqual(json.dumps(data(packet), ensure_ascii=False, separators=(',', ':')), packet.text)
        self.assertFalse(packet.text.endswith('\n'))
        self.assertNotIn('\n', packet.text)
        body = data(packet)
        self.assertEqual(body['v'], 'oz/1e')
        self.assertEqual(body['ops'], {'audit': INSTRUCTION_TEXT['audit'], 'propose': INSTRUCTION_TEXT['propose']})
        self.assertEqual(body['refs'], {'d0': 'demo patch at revision a1', 'd1': 'Use 5 seconds per attempt',
                                        'p0': 'result'})
        self.assertEqual(body['jobs'], [['a', 'audit', ['d0']], ['b', 'propose', ['d1', 'p0']]])
        self.assertEqual((packet.ids, packet.packet_ids), (('a', 'b'), ('a', 'b')))

    def test_a_record_used_by_four_jobs_is_serialized_once(self):
        packet = render(twins(), [('a', 'a1'), ('b', 'a1'), ('c', 'a1'), ('d', 'a1a1')], counters=[len])
        body = data(packet)
        self.assertEqual(body['refs'], {'d0': 'same'})
        self.assertEqual(packet.text.count('same'), 1)
        self.assertEqual(body['jobs'], [['a', 'audit', ['d0']], ['b', 'audit', ['d0']], ['c', 'audit', ['d0']],
                                        ['d.0', 'audit', ['d0']], ['d.1', 'audit', ['d0']]])

    def test_records_are_shared_by_source_not_by_equal_value(self):
        packet = render(twins(), [('a', 'a1'), ('b', 'a2'), ('c', '>3'), ('d', 'a1')], counters=[len])
        body = data(packet)
        self.assertEqual(body['refs'], {'d0': 'same', 'd1': 'same', 'd2': 'other'})
        self.assertEqual([j[2] for j in body['jobs']], [['d0'], ['d1'], ['d2'], ['d0']])

    def test_a_predecessor_result_used_by_four_jobs_is_serialized_once(self):
        record = {'results': ['unique-marker-17', 2]}
        packet = render(extended(), [('a', '>12'), ('b', '>12'), ('c', ':note'), ('d', 'a7')], counters=[len],
                        handoffs=[(m, 'pred', record) for m in 'abcd'])
        body = data(packet)
        self.assertEqual(packet.text.count('unique-marker-17'), 1)
        self.assertEqual(body['refs'], {'d0': 'Use 5 seconds per attempt', 'p0': record,
                                        'd1': 'demo patch at revision a1'})
        self.assertEqual(body['jobs'], [['a', 'propose', ['d0', 'p0']], ['b', 'propose', ['d0', 'p0']],
                                        ['c', 'literal_0', ['p0']], ['d', 'audit', ['d1', 'p0']]])

    def test_keys_are_allocated_in_first_use_order_with_record_before_predecessors(self):
        packet = render(extended(), [('a', '>12'), ('b', 'a7'), ('c', '=13')], counters=[len],
                        handoffs=[('a', 'zed', 'Z'), ('a', 'alpha', 'A'), ('b', 'alpha', 'A'), ('b', 'new', 'N'),
                                  ('c', 'zed', 'Z')])
        body = data(packet)
        self.assertEqual(list(body['refs']), ['d0', 'p0', 'p1', 'd1', 'p2', 'd2'])
        self.assertEqual(list(body['refs'].values()),
                         ['Use 5 seconds per attempt', 'Z', 'A', 'demo patch at revision a1', 'N', '12.50 ± 0.02 mm'])
        self.assertEqual(body['jobs'], [['a', 'propose', ['d0', 'p0', 'p1']], ['b', 'audit', ['d1', 'p1', 'p2']],
                                        ['c', 'observed', ['d2', 'p0']]])

    def test_removed_goal_and_inline_input_do_not_appear(self):
        packet = render(extended(), [('a', 'V')], counters=[len])
        self.assertNotIn(extended().snapshot()['goal'], packet.text)
        self.assertNotIn('"input"', packet.text)
        self.assertEqual(set(data(packet)), {'v', 'ops', 'refs', 'jobs'})

    def test_tokens_count_system_newline_body_as_one_string(self):
        packet = render(extended(), [('j1', 'V')], counters=[len, lambda s: 2 * len(s)])
        size = len(packet.system) + 1 + len(packet.text)
        self.assertEqual(packet.tokens, (size, 2 * size))

    def test_ops_strings_are_exact_and_in_first_occurrence_order(self):
        every = render(extended(), [('a', 'r13>12=13~10a7t14')], counters=[len])
        self.assertEqual(data(every)['ops'], {k: INSTRUCTION_TEXT[k] for k in
                                              ['propose', 'observed', 'inferred', 'audit']})
        self.assertEqual({k: v for k, v in INSTRUCTIONS.items()},
                         {'a': INSTRUCTION_TEXT['audit'], '>': INSTRUCTION_TEXT['propose'],
                          '=': INSTRUCTION_TEXT['observed'], '~': INSTRUCTION_TEXT['inferred']})
        order = render(extended(), [('a', '~10'), ('b', 'a7>12'), ('c', 'a7')], counters=[len])
        self.assertEqual(list(data(order)['ops']), ['inferred', 'audit', 'propose'])
        self.assertEqual([j[1] for j in data(order)['jobs']], ['inferred', 'audit', 'propose', 'audit'])

    def test_read_and_test_are_host_operations_and_never_reach_ops_or_jobs(self):
        packet = render(extended(), [('a', 'V')], counters=[len])
        self.assertEqual(list(data(packet)['ops']), ['audit'])
        self.assertNotIn('read', data(packet)['ops'])
        self.assertNotIn('test', data(packet)['ops'])
        self.assertFalse(any(j[1] in ('read', 'test') for j in data(packet)['jobs']))
        self.assertNotIn('read', INSTRUCTIONS.values())
        self.assertNotIn('python -m unittest', packet.text)

    def test_host_slots_hold_read_and_test_results_in_atom_order(self):
        packet = render(extended(), [('a', 'V'), ('b', 'r13')], counters=[len])
        self.assertEqual(data(packet)['jobs'], [['a', 'audit', ['d0']]])
        self.assertEqual(data(packet)['refs'], {'d0': 'demo patch at revision a1'})
        self.assertEqual(packet.job_map, (('a', 1),))
        self.assertEqual(packet.host_slots, (('a', 0, ''), ('a', 2, 'python -m unittest'), ('b', 0, '')))

    def test_batch_with_only_host_operations_needs_no_model(self):
        packet = render(extended(), [('a', 'r13'), ('b', 't14'), ('c', 'r7t14')], counters=[len, len])
        self.assertEqual((packet.mode, packet.system, packet.text, packet.job_map), ('host', '', '', ()))
        self.assertEqual(packet.tokens, (0, 0))
        self.assertEqual(packet.host_slots, (('a', 0, ''), ('b', 0, 'python -m unittest'),
                                             ('c', 0, ''), ('c', 1, 'python -m unittest')))
        # A tiny budget cannot fail a packet that sends nothing.
        self.assertEqual(render(extended(), [('a', 'r13')], counters=[len], max_tokens=1).mode, 'host')

    def test_job_ids_are_inbox_ids_for_one_model_atom_and_suffixed_for_several(self):
        rows = [('job_a', 'V'), ('job_b', 'V7'), ('job_c', 'r7a7t14'), ('job_d', 'P'), ('multi', '>12a7=13')]
        packet = render(extended(), rows, counters=[len])
        jobs = data(packet)['jobs']
        self.assertEqual([j[0] for j in jobs], ['job_a', 'job_b', 'job_c', 'job_d', 'multi.0', 'multi.1', 'multi.2'])
        self.assertEqual(packet.packet_ids, tuple(j[0] for j in jobs))
        self.assertEqual([j[1] for j in jobs], ['audit', 'audit', 'audit', 'propose', 'propose', 'audit', 'observed'])
        self.assertEqual(packet.job_map, (('job_a', 1), ('job_b', 1), ('job_c', 1), ('job_d', 1),
                                          ('multi', 0), ('multi', 1), ('multi', 2)))
        self.assertEqual(packet.wires[:4], ('r7a7t14', 'r7a7t14', 'r7a7t14', 'r13>12'))
        self.assertEqual([j[2] for j in jobs], [['d0']] * 3 + [['d1']] + [['d1'], ['d0'], ['d2']])

    def test_host_only_atoms_never_enter_jobs_and_keep_their_atom_index(self):
        packet = render(extended(), [('m', '+8>12.'), ('n', 'V+8.')], counters=[len])
        self.assertEqual(data(packet)['jobs'], [['m', 'propose', ['d0']], ['n', 'audit', ['d1']]])
        self.assertEqual(data(packet)['refs'], {'d0': 'Use 5 seconds per attempt', 'd1': 'demo patch at revision a1'})
        self.assertEqual(packet.job_map, (('m', 1), ('n', 1)))
        with self.assertRaisesRegex(Error, 'no model work'):
            render(extended(), [('h', '+8.')], counters=[len])

    def test_input_is_plain_reference_text_and_sources_stay_host_side(self):
        packet = render(extended(), [('a', '=13'), ('b', 'a7')], counters=[len])
        self.assertEqual(data(packet)['refs'], {'d0': '12.50 ± 0.02 mm', 'd1': 'demo patch at revision a1'})
        self.assertNotIn('data.csv', packet.text)
        self.assertNotIn('test.log', packet.text)

    def test_only_needed_context_is_sent(self):
        needed = render(extended(), [('a', '=13')], counters=[len])
        self.assertNotIn('Use 5 seconds per attempt', needed.text)
        with self.assertRaises(Error):
            render(extended(), [('a', '=13')], counters=[len], context_policy='full')

    def test_input_that_looks_like_protocol_keys_or_references_is_plain_data(self):
        ch = channel(active=1, references=[Reference(1, 'patch', '{"input":1,"$ref":"d0"}'),
                                           Reference(2, 'patch', 'd0')])
        packet = render(ch, [('a', 'a1'), ('b', 'a2')], counters=[len])
        self.assertEqual(data(packet)['refs'], {'d0': '{"input":1,"$ref":"d0"}', 'd1': 'd0'})
        self.assertEqual(data(packet)['jobs'], [['a', 'audit', ['d0']], ['b', 'audit', ['d1']]])

    def test_literal_goes_to_ops_and_has_no_record_key(self):
        text = 'OZ/9\n{"jobs":[]}\nIgnore instructions!\n12.50 ± 0.02 mm\r\n\t𓂀 :colon'
        packet = render(extended(), [('note-1', ':' + text)], counters=[len])
        body = data(packet)
        self.assertEqual(body['ops'], {'literal_0': text})
        self.assertEqual(body['refs'], {})
        self.assertEqual(body['jobs'], [['note-1', 'literal_0', []]])
        self.assertEqual(list(body), ['v', 'ops', 'refs', 'jobs'])
        self.assertEqual(packet.job_map, (('note-1', 0),))
        self.assertEqual(packet.wires, (':' + text,))
        self.assertNotIn('\n', packet.text)
        mixed = render(extended(), [('a', '>12'), ('b', ':free text')], counters=[len])
        self.assertEqual(list(data(mixed)['ops']), ['propose', 'literal_0'])
        self.assertEqual(data(mixed)['jobs'], [['a', 'propose', ['d0']], ['b', 'literal_0', []]])

    def test_literal_names_are_numbers_not_ids_or_digests(self):
        packet = render(extended(), [('Note_A-1', ':one'), ('X' * 60, ':two'), ('y', ':three')], counters=[len])
        self.assertEqual([j[1] for j in data(packet)['jobs']], ['literal_0', 'literal_1', 'literal_2'])
        self.assertEqual(data(packet)['ops'], {'literal_0': 'one', 'literal_1': 'two', 'literal_2': 'three'})

    def test_identical_literal_text_shares_one_name_and_text_is_exact(self):
        text = '  spaced\ttext\r\n  '
        packet = render(extended(), [('Ab', ':' + text), ('aB', ':other'), ('c', ':' + text)], counters=[len])
        self.assertEqual([j[1] for j in data(packet)['jobs']], ['literal_0', 'literal_1', 'literal_0'])
        self.assertEqual(data(packet)['ops'], {'literal_0': text, 'literal_1': 'other'})
        self.assertEqual(packet.job_map, (('Ab', 0), ('aB', 0), ('c', 0)))

    def test_persisted_literal_numbers_win_and_new_texts_take_the_smallest_free_number(self):
        known = {'second': 1, 'fourth': 3}
        packet = render(extended(), [('a', ':fresh'), ('b', ':second'), ('c', ':fourth'), ('d', ':newer'),
                                     ('e', ':fresh')], counters=[len], literals=known)
        self.assertEqual([j[1] for j in data(packet)['jobs']],
                         ['literal_0', 'literal_1', 'literal_3', 'literal_2', 'literal_0'])
        self.assertEqual(data(packet)['ops'], {'literal_0': 'fresh', 'literal_1': 'second', 'literal_3': 'fourth',
                                               'literal_2': 'newer'})
        self.assertEqual(known, {'second': 1, 'fourth': 3})
        alone = render(extended(), [('c', ':fourth')], counters=[len], literals=known)
        self.assertEqual(data(alone)['jobs'], [['c', 'literal_3', []]])

    def test_literal_without_a_reference_never_collides_with_operation_names(self):
        packet = render(extended(), [('a', '>12'), ('b', ':propose')], counters=[len])
        self.assertEqual(data(packet)['ops'], {'propose': INSTRUCTION_TEXT['propose'], 'literal_0': 'propose'})

    def test_predecessor_keys_follow_the_record_key_only_when_there_are_predecessors(self):
        packet = render(extended(), [('a', 'V'), ('b', '>12'), ('c', ':note'), ('d', '>12')], counters=[len],
                        handoffs=[('c', 'zed', 'Z'), ('a', 'zed', 'Z'), ('a', 'Alpha', 'A'), ('b', 'zed', 'Z')])
        body = data(packet)
        self.assertEqual(list(body), ['v', 'ops', 'refs', 'jobs'])
        self.assertEqual(body['refs'], {'p0': 'Z', 'd0': 'demo patch at revision a1', 'p1': 'A',
                                        'd1': 'Use 5 seconds per attempt'})
        self.assertEqual(body['jobs'], [['a', 'audit', ['d0', 'p0', 'p1']], ['b', 'propose', ['d1', 'p0']],
                                        ['c', 'literal_0', ['p0']], ['d', 'propose', ['d1']]])

    def test_predecessor_keys_keep_the_given_dependency_order(self):
        packet = render(extended(), [('a', '>12'), ('b', '>12'), ('c', '>12')], counters=[len],
                        handoffs=[('a', 'p2', 'two'), ('a', 'p1', 'one'), ('b', 'p2', 'two'), ('b', 'p1', 'one')])
        self.assertEqual([j[2] for j in data(packet)['jobs']], [['d0', 'p0', 'p1'], ['d0', 'p0', 'p1'], ['d0']])
        other = render(extended(), [('a', '>12'), ('b', '>12')], counters=[len],
                       handoffs=[('a', 'p2', 'two'), ('a', 'p1', 'one'), ('b', 'p1', 'one'), ('b', 'p2', 'two')])
        self.assertEqual([j[2] for j in data(other)['jobs']], [['d0', 'p0', 'p1'], ['d0', 'p1', 'p0']])
        self.assertEqual(data(other)['refs'], {'d0': 'Use 5 seconds per attempt', 'p0': 'two', 'p1': 'one'})

    def test_predecessor_results_are_json_values_in_refs_never_json_in_strings(self):
        records = [{'results': ['a', 1]}, [1, 2.5, None], 7, True, None, 'plain', {'k': {'n': [False]}}]
        packet = render(extended(), [('a', '>12')], counters=[len],
                        handoffs=[('a', f'p{i}', r) for i, r in enumerate(records)])
        refs = data(packet)['refs']
        self.assertEqual([refs[f'p{i}'] for i in range(len(records))], records)
        self.assertIn('"p0":{"results":["a",1]},"p1":[1,2.5,null],"p2":7,"p3":true,"p4":null,"p5":"plain",'
                      '"p6":{"k":{"n":[false]}}', packet.text)
        self.assertEqual(data(packet)['jobs'], [['a', 'propose', ['d0'] + [f'p{i}' for i in range(7)]]])
        self.assertNotIn('\\"', packet.text)

    def test_a_repeated_predecessor_keeps_its_first_occurrence(self):
        packet = render(extended(), [('a', '>12')], counters=[len],
                        handoffs=[('a', 'p1', 'one'), ('a', 'p2', 'two'), ('a', 'p1', 'one')])
        self.assertEqual(data(packet)['jobs'][0][2], ['d0', 'p0', 'p1'])

    def test_each_model_slot_of_a_job_with_predecessors_gets_the_predecessor_keys(self):
        packet = render(extended(), [('a', 'P')], counters=[len], handoffs=[('a', 'p', 'R')])
        self.assertEqual(data(packet)['jobs'], [['a', 'propose', ['d0', 'p0']]])
        multi = render(extended(), [('a', '>12a7')], counters=[len], handoffs=[('a', 'p', 'R')])
        self.assertEqual(data(multi)['jobs'], [['a.0', 'propose', ['d0', 'p0']], ['a.1', 'audit', ['d1', 'p0']]])
        self.assertEqual(data(multi)['refs'], {'d0': 'Use 5 seconds per attempt', 'p0': 'R',
                                               'd1': 'demo patch at revision a1'})

    def test_legacy_text_records_are_strings_unchanged(self):
        text = '  12.50 ± 0.02 mm\r\n{"x":1}  '
        packet = render(extended(), [('a', '>12')], counters=[len], handoffs=[('a', 'p1', text)])
        self.assertEqual(data(packet)['refs']['p0'], text)
        self.assertEqual(packet.text.count('p1'), 0)

    def test_handoffs_to_host_only_jobs_send_nothing(self):
        packet = render(extended(), [('a', 'r13')], counters=[len], handoffs=[('a', 'p', 'R')])
        self.assertEqual((packet.mode, packet.text), ('host', ''))

    def test_conflicting_or_malformed_handoffs_fail_closed(self):
        for links in [[('a', 'p', 'one'), ('b', 'p', 'two')], [('a', 'p', 1), ('b', 'p', True)],
                      [('missing', 'p', 'x')], [('a', 'bad id', 'x')], [('a', 'p', float('nan'))]]:
            with self.subTest(links=links), self.assertRaises(Error):
                render(extended(), [('a', 'V'), ('b', 'V')], counters=[len], handoffs=links)

    def test_packet_validation_refuses_malformed_bodies(self):
        ops, refs = {'extract': 'x'}, {'k': 1, 'q': None}
        ok = ['a', 'extract', ['k']]
        validate_packet(ops, refs, [ok, ['b', 'extract', []], ['c', 'extract', ['k', 'k', 'q']]])
        # An operation absent from ops is a valid unknown_operation scenario, not a structural error.
        validate_packet(ops, refs, [['a', 'unknown', ['k']]])
        validate_packet({}, {}, [['a', 'unknown', []]])
        for o, r, j in [({'Extract': 'x'}, refs, [['a', 'Extract', []]]), ({'1x': 'x'}, refs, [['a', '1x', []]]),
                        ({'a' * 65: 'x'}, refs, [['a', 'a' * 65, []]]), ({'extract': 5}, refs, [ok]),
                        ({'extract': ''}, refs, [ok]), ([], refs, [ok]), (ops, [], [ok]),
                        (ops, {'': 1}, [ok]), (ops, {1: 1}, [ok]),
                        (ops, refs, []), (ops, refs, 'x'), (ops, refs, [ok, ok]),
                        (ops, refs, [['', 'extract', []]]), (ops, refs, [[1, 'extract', []]]),
                        (ops, refs, [['a', 'extract']]), (ops, refs, [['a', 'extract', [], []]]),
                        (ops, refs, [['a', '', []]]), (ops, refs, [['a', 5, []]]),
                        (ops, refs, [['a', 'extract', 'k']]), (ops, refs, [['a', 'extract', [1]]]),
                        (ops, refs, [['a', 'extract', ['']]]), (ops, refs, [['a', 'extract', ['missing']]]),
                        (ops, refs, ['a extract'])]:
            with self.subTest(ops=o, refs=r, jobs=j), self.assertRaises(Error):
                validate_packet(o, r, j)

    def test_receipt_is_stored_but_never_sent_to_the_model(self):
        receipt = 'zq9k2m7p4x1c8v5b'
        packet = render(extended(), [('a', 'V')], counters=[len], receipt=receipt)
        self.assertEqual(packet.receipt, receipt)
        self.assertNotIn(receipt, packet.text + packet.system)
        self.assertEqual(packet.text, render(extended(), [('a', 'V')], counters=[len]).text)

    def test_budget_counts_system_and_body_and_does_not_truncate(self):
        ch = extended()
        baseline = render(ch, [('j1', 'V')], counters=[len])
        self.assertEqual(render(ch, [('j1', 'V')], counters=[len], max_tokens=baseline.tokens[0]).text,
                         baseline.text)
        with self.assertRaisesRegex(Error, 'split batch'):
            render(ch, [('j1', 'V')], counters=[len], max_tokens=baseline.tokens[0] - 1)
        size = len((baseline.system + '\n' + baseline.text).encode('utf-8'))
        self.assertEqual(render(ch, [('j1', 'V')], counters=[len], max_bytes=size).text, baseline.text)
        with self.assertRaises(Error):
            render(ch, [('j1', 'V')], counters=[len], max_bytes=size - 1)
        for receipt in ['', 'G', 'A' * 16, 'a' * 17, 'ab-c', '1 ']:
            with self.assertRaises(Error):
                render(ch, [('j1', 'V')], counters=[len], receipt=receipt)

    def test_invalid_rows_counters_and_context_policy_fail_closed(self):
        ch = extended()
        for rows in [[], [('a', 'V')] * 2, [('bad id', 'V')], [('a', 'Q')], [('a',)]]:
            with self.subTest(rows=rows), self.assertRaises(Error):
                render(ch, rows, counters=[len])
        for kwargs in [dict(counters=[]), dict(counters=[lambda s: -1]),
                       dict(counters=[len], max_bytes=0), dict(counters=[len], context_policy='all')]:
            with self.subTest(kwargs=kwargs), self.assertRaises(Error):
                render(ch, [('a', 'V')], **kwargs)

    def test_removed_options_are_rejected(self):
        for option in ['encoding', 'min_savings', 'candidate_limit']:
            with self.subTest(option=option), self.assertRaises(TypeError):
                render(extended(), [('a', 'V')], counters=[len], **{option: 'x'})

    def test_explicit_writes_references_out(self):
        ch = extended()
        self.assertEqual(explicit(ch.accept('V', binding=ch.binding)), 'r7a7t14')

    def test_render_does_not_mutate_channel(self):
        ch = extended()
        before = ch.snapshot()
        render(ch, [('a', 'V')], counters=[len])
        self.assertEqual(ch.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
