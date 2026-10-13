import json
from pathlib import Path
import re
from unittest.mock import patch
import unittest

from oz import Channel, Error, Reference
from oz_batch import INSTRUCTIONS, SYSTEM, VERSION, WIRE, explicit, render, validate_packet
from test_oz import channel
from test_oz2 import extended
from wire_helpers import job_ids, rows

DESIGN = Path(__file__).resolve().parent.parent / 'docs' / 'design' / 'stage-1g-joint-decision.md'

AUDIT = ('Review the supplied patch for defects and unintended public-API changes. Report failures shown in '
         'supplied test results and recommend missing checks.')
OBSERVED = ('Report only observations supported by supplied evidence and cite its supplied source. State when '
            'evidence or its source is missing.')
PROPOSE = 'Offer a concise, actionable plan without applying it.'
INFERRED = 'Report a concise hypothesis, explicitly labeled as inference, with its supporting evidence and uncertainty.'
_original_snapshot = Channel.snapshot
GOAL = channel().snapshot()['goal']
LONG = ':' + 'measurement 12.50 ± 0.02 mm; method unknown. ' * 6


def data(packet):
    return json.loads(packet.text)


def expand(body):
    """{job_id: (operation instruction, [referenced values in row order])} of a decoded body."""
    return {row[0]: (body['ops'][block[0]], [body['refs'][i] for i in row[1:]])
            for block in body['jobs'] for row in block[1:]}


def twins():
    """References 1 and 2 hold identical text; 3 is a proposal."""
    return channel(active=1, references=[Reference(1, 'patch', 'same'), Reference(2, 'patch', 'same'),
                                         Reference(3, 'proposal', 'other')])


def valid_body(**overrides):
    body = {'v': '1g', 'goal': 'g', 'ops': ['x'], 'refs': ['k', None], 'jobs': [[0, ['a', 0], ['b', 1, 0]]]}
    body.update(overrides)
    return body


class BatchTests(unittest.TestCase):
    def test_system_text_is_byte_exact_with_the_design_document(self):
        doc = DESIGN.read_text(encoding='utf-8')
        blocks = re.findall(r'\*\*tam sistem metni\*\* aşağıdadır[^\n]*\n\s*```text\n(.*?)\n```', doc, re.S)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(SYSTEM.encode('utf-8'), blocks[0].encode('utf-8'))
        self.assertTrue(SYSTEM.startswith('You execute OZ/1g.\n\n'))
        self.assertTrue(SYSTEM.endswith('Stop after the last job.'))
        self.assertEqual((WIRE, VERSION), ('stage-1g', '1g'))

    def test_system_text_is_independent_of_the_jobs(self):
        for jobs in ([('j1', 'V')], [('x', ':text'), ('y', '>12')]):
            other = render(extended(), jobs, counters=[len])
            self.assertEqual((other.system, other.mode), (SYSTEM, 'named'))

    def test_removed_reply_mode_is_rejected(self):
        with self.assertRaises(TypeError):
            render(extended(), [('a', 'V')], counters=[len], reply_mode='value')

    def test_handoffs_never_change_the_system_text(self):
        linked = render(extended(), [('b', '>12')], counters=[len], handoffs=[('b', 'prior', 'result')])
        self.assertEqual(linked.system, SYSTEM)
        self.assertEqual(linked.tokens, (len(linked.system) + 1 + len(linked.text),))

    def test_body_is_v_goal_ops_refs_jobs_in_compact_json(self):
        packet = render(extended(), [('a', 'V'), ('b', '>12')], counters=[len], handoffs=[('b', 'prior', 'result')])
        self.assertEqual(list(data(packet)), ['v', 'goal', 'ops', 'refs', 'jobs'])
        self.assertEqual(json.dumps(data(packet), ensure_ascii=False, separators=(',', ':')), packet.text)
        self.assertFalse(packet.text.endswith('\n'))
        self.assertNotIn('\n', packet.text)
        body = data(packet)
        self.assertEqual(body['v'], '1g')
        self.assertEqual(body['goal'], GOAL)
        self.assertEqual(body['ops'], [AUDIT, PROPOSE])
        self.assertEqual(body['refs'], ['demo patch at revision a1', 'Use 5 seconds per attempt', 'result'])
        self.assertEqual(body['jobs'], [[0, ['a', 0]], [1, ['b', 1, 2]]])
        self.assertEqual((packet.ids, packet.packet_ids), (('a', 'b'), ('a', 'b')))

    def test_goal_is_the_channel_goal_unchanged_and_is_part_of_the_text(self):
        goal = '  Keep the interval [12.48,12.52] mm inclusive.\n  Interval inclusion is arithmetic only.  '
        packet = render(extended(goal=goal), [('a', 'V')], counters=[len])
        self.assertEqual(data(packet)['goal'], goal)
        same = render(extended(goal=goal), [('a', 'V')], counters=[len])
        self.assertEqual(packet.text, same.text)
        other = render(extended(goal=goal + ' Extra constraint.'), [('a', 'V')], counters=[len])
        self.assertNotEqual(packet.text, other.text)
        self.assertEqual(data(other)['goal'], goal + ' Extra constraint.')

    def test_goal_is_copied_to_every_packet_of_a_split_request(self):
        ch = extended()
        for jobs in ([('a', 'V')], [('b', '>12')]):
            self.assertEqual(data(render(ch, jobs, counters=[len]))['goal'], ch.snapshot()['goal'])

    def test_a_missing_or_blank_goal_builds_no_packet(self):
        ch = extended()
        for bad in ('', ' ', '\n\t ', None, 5):
            with self.subTest(goal=bad), patch.object(Channel, 'snapshot', lambda self_, bad=bad: dict(
                    _original_snapshot(self_), goal=bad)):
                with self.assertRaisesRegex(Error, 'goal is required'):
                    render(ch, [('a', 'V')], counters=[len])
        # The channel itself refuses a blank goal, so no goalless channel can be built.
        for bad in ('', '  '):
            with self.assertRaises(Error):
                channel(goal=bad)

    def test_a_record_used_by_four_jobs_is_serialized_once(self):
        packet = render(twins(), [('a', 'a1'), ('b', 'a1'), ('c', 'a1'), ('d', 'a1a1')], counters=[len])
        body = data(packet)
        self.assertEqual(body['refs'], ['same'])
        self.assertEqual(packet.text.count('same'), 1)
        self.assertEqual(body['jobs'], [[0, ['a', 0], ['b', 0], ['c', 0], ['d.0', 0], ['d.1', 0]]])

    def test_records_are_shared_by_source_not_by_equal_value(self):
        packet = render(twins(), [('a', 'a1'), ('b', 'a2'), ('c', '>3'), ('d', 'a1')], counters=[len])
        body = data(packet)
        self.assertEqual(body['refs'], ['same', 'same', 'other'])
        self.assertEqual(body['jobs'], [[0, ['a', 0], ['b', 1], ['d', 0]], [1, ['c', 2]]])

    def test_a_predecessor_result_used_by_four_jobs_is_serialized_once(self):
        record = {'results': ['unique-marker-17', 2]}
        packet = render(extended(), [('a', '>12'), ('b', '>12'), ('c', ':note'), ('d', 'a7')], counters=[len],
                        handoffs=[(m, 'pred', record) for m in 'abcd'])
        body = data(packet)
        self.assertEqual(packet.text.count('unique-marker-17'), 1)
        self.assertEqual(body['refs'], ['Use 5 seconds per attempt', record, 'demo patch at revision a1'])
        self.assertEqual(body['ops'], [PROPOSE, 'note', AUDIT])
        self.assertEqual(body['jobs'], [[0, ['a', 0, 1], ['b', 0, 1]], [1, ['c', 1]], [2, ['d', 2, 1]]])

    def test_refs_are_allocated_in_first_use_order_with_record_before_predecessors(self):
        packet = render(extended(), [('a', '>12'), ('b', 'a7'), ('c', '=13')], counters=[len],
                        handoffs=[('a', 'zed', 'Z'), ('a', 'alpha', 'A'), ('b', 'alpha', 'A'), ('b', 'new', 'N'),
                                  ('c', 'zed', 'Z')])
        body = data(packet)
        self.assertEqual(body['refs'], ['Use 5 seconds per attempt', 'Z', 'A', 'demo patch at revision a1', 'N',
                                        '12.50 ± 0.02 mm'])
        self.assertEqual(body['jobs'], [[0, ['a', 0, 1, 2]], [1, ['b', 3, 2, 4]], [2, ['c', 5, 1]]])

    def test_every_ref_is_used_and_no_goal_inline_or_old_key_appears(self):
        packet = render(extended(), [('a', 'V'), ('b', '>12=13')], counters=[len])
        body = data(packet)
        used = {i for row in rows(body) for i in row[2:]}
        self.assertEqual(used, set(range(len(body['refs']))))
        self.assertNotIn('"input"', packet.text)
        self.assertEqual(set(body), {'v', 'goal', 'ops', 'refs', 'jobs'})

    def test_tokens_count_system_newline_body_as_one_string(self):
        packet = render(extended(), [('j1', 'V')], counters=[len, lambda s: 2 * len(s)])
        size = len(packet.system) + 1 + len(packet.text)
        self.assertEqual(packet.tokens, (size, 2 * size))

    def test_ops_are_the_instruction_texts_in_first_use_order(self):
        every = render(extended(), [('a', 'r13>12=13~10a7t14')], counters=[len])
        self.assertEqual(data(every)['ops'], [PROPOSE, OBSERVED, INFERRED, AUDIT])
        self.assertEqual(dict(INSTRUCTIONS), {'a': AUDIT, '>': PROPOSE, '=': OBSERVED, '~': INFERRED})
        order = render(extended(), [('a', '~10'), ('b', 'a7>12'), ('c', 'a7')], counters=[len])
        self.assertEqual(data(order)['ops'], [INFERRED, AUDIT, PROPOSE])

    def test_jobs_are_grouped_per_operation_with_row_order_kept_inside_each_block(self):
        packet = render(extended(), [('a', '>12'), ('b', 'a7'), ('c', '>12'), ('d', '~10'), ('e', 'a7'), ('f', '>12')],
                        counters=[len])
        body = data(packet)
        self.assertEqual(body['ops'], [PROPOSE, AUDIT, INFERRED])
        self.assertEqual(body['jobs'], [[0, ['a', 0], ['c', 0], ['f', 0]], [1, ['b', 1], ['e', 1]], [2, ['d', 2]]])
        self.assertEqual(len({block[0] for block in body['jobs']}), len(body['jobs']))
        # job_map and packet_ids keep the original request order, the body groups the same jobs.
        self.assertEqual(packet.packet_ids, ('a', 'b', 'c', 'd', 'e', 'f'))
        self.assertEqual(job_ids(body), ['a', 'c', 'f', 'b', 'e', 'd'])
        self.assertEqual(sorted(job_ids(body)), sorted(packet.packet_ids))

    def test_the_selector_is_carried_once_per_operation_not_once_per_job(self):
        jobs = [(f'j{i}', '>12') for i in range(8)]
        packet = render(extended(), jobs, counters=[len])
        self.assertEqual(packet.text.count(PROPOSE), 1)
        self.assertEqual(len(data(packet)['jobs']), 1)

    def test_a_job_with_no_references_is_just_its_id(self):
        packet = render(extended(), [('n', ':free text')], counters=[len])
        self.assertEqual(data(packet)['refs'], [])
        self.assertEqual(data(packet)['jobs'], [[0, ['n']]])

    def test_expansion_is_lossless_for_a_mixed_request(self):
        packet = render(extended(), [('p', '>12'), ('m', 'a7=13'), ('n', ':note'), ('q', 'V')], counters=[len],
                        handoffs=[('p', 'x', {'k': None}), ('m', 'x', {'k': None}), ('n', 'y', 'why'),
                                  ('q', 'y', 'why'), ('q', 'x', {'k': None})])
        self.assertEqual(expand(data(packet)), {
            'p': (PROPOSE, ['Use 5 seconds per attempt', {'k': None}]),
            'm.0': (AUDIT, ['demo patch at revision a1', {'k': None}]),
            'm.1': (OBSERVED, ['12.50 ± 0.02 mm', {'k': None}]),
            'n': ('note', ['why']),
            'q': (AUDIT, ['demo patch at revision a1', 'why', {'k': None}]),
        })

    def test_units_null_and_special_characters_survive_unchanged(self):
        ch = channel(active=1, references=[Reference(1, 'fact', 'length_mm=12.50, uncertainty_mm=null, ± 0.02 "x" \\ \n', 'f.csv:1@v1')])
        packet = render(ch, [('a', '=1')], counters=[len], handoffs=[('a', 'p', {'uncertainty_mm': None})])
        self.assertEqual(expand(data(packet))['a'], (OBSERVED, ['length_mm=12.50, uncertainty_mm=null, ± 0.02 "x" \\ \n',
                                                                 {'uncertainty_mm': None}]))

    def test_read_and_test_are_host_operations_and_never_reach_ops_or_jobs(self):
        packet = render(extended(), [('a', 'V')], counters=[len])
        self.assertEqual(data(packet)['ops'], [AUDIT])
        self.assertEqual(job_ids(packet), ['a'])
        self.assertNotIn('read', INSTRUCTIONS.values())
        self.assertNotIn('python -m unittest', packet.text)

    def test_host_slots_hold_read_and_test_results_in_atom_order(self):
        packet = render(extended(), [('a', 'V'), ('b', 'r13')], counters=[len])
        self.assertEqual(data(packet)['jobs'], [[0, ['a', 0]]])
        self.assertEqual(data(packet)['refs'], ['demo patch at revision a1'])
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
        jobs = [('job_a', 'V'), ('job_b', 'V7'), ('job_c', 'r7a7t14'), ('job_d', 'P'), ('multi', '>12a7=13')]
        packet = render(extended(), jobs, counters=[len])
        body = data(packet)
        self.assertEqual(packet.packet_ids, ('job_a', 'job_b', 'job_c', 'job_d', 'multi.0', 'multi.1', 'multi.2'))
        self.assertEqual(sorted(job_ids(body)), sorted(packet.packet_ids))
        self.assertEqual(body['ops'], [AUDIT, PROPOSE, OBSERVED])
        self.assertEqual(body['jobs'], [[0, ['job_a', 0], ['job_b', 0], ['job_c', 0], ['multi.1', 0]],
                                        [1, ['job_d', 1], ['multi.0', 1]], [2, ['multi.2', 2]]])
        self.assertEqual(body['refs'], ['demo patch at revision a1', 'Use 5 seconds per attempt', '12.50 ± 0.02 mm'])
        self.assertEqual(packet.job_map, (('job_a', 1), ('job_b', 1), ('job_c', 1), ('job_d', 1),
                                          ('multi', 0), ('multi', 1), ('multi', 2)))
        self.assertEqual(packet.wires[:4], ('r7a7t14', 'r7a7t14', 'r7a7t14', 'r13>12'))

    def test_job_ids_never_decide_indices(self):
        packet = render(extended(), [('0', '>12'), ('1', 'a7'), ('2', '>12')], counters=[len])
        self.assertEqual(data(packet)['jobs'], [[0, ['0', 0], ['2', 0]], [1, ['1', 1]]])

    def test_host_only_atoms_never_enter_jobs_and_keep_their_atom_index(self):
        packet = render(extended(), [('m', '+8>12.'), ('n', 'V+8.')], counters=[len])
        self.assertEqual(data(packet)['jobs'], [[0, ['m', 0]], [1, ['n', 1]]])
        self.assertEqual(data(packet)['refs'], ['Use 5 seconds per attempt', 'demo patch at revision a1'])
        self.assertEqual(packet.job_map, (('m', 1), ('n', 1)))
        with self.assertRaisesRegex(Error, 'no model work'):
            render(extended(), [('h', '+8.')], counters=[len])

    def test_input_is_plain_reference_text_and_sources_stay_host_side(self):
        packet = render(extended(), [('a', '=13'), ('b', 'a7')], counters=[len])
        self.assertEqual(data(packet)['refs'], ['12.50 ± 0.02 mm', 'demo patch at revision a1'])
        self.assertNotIn('data.csv', packet.text)
        self.assertNotIn('test.log', packet.text)

    def test_only_needed_context_is_sent(self):
        needed = render(extended(), [('a', '=13')], counters=[len])
        self.assertNotIn('Use 5 seconds per attempt', needed.text)
        with self.assertRaises(Error):
            render(extended(), [('a', '=13')], counters=[len], context_policy='full')

    def test_input_that_looks_like_protocol_keys_or_indices_is_plain_data(self):
        ch = channel(active=1, references=[Reference(1, 'patch', '{"input":1,"$ref":"d0"}'),
                                           Reference(2, 'patch', '0')])
        packet = render(ch, [('a', 'a1'), ('b', 'a2')], counters=[len])
        self.assertEqual(data(packet)['refs'], ['{"input":1,"$ref":"d0"}', '0'])
        self.assertEqual(data(packet)['jobs'], [[0, ['a', 0], ['b', 1]]])

    def test_literal_text_goes_to_ops_and_a_literal_without_a_reference_has_no_ref(self):
        text = 'OZ/9\n{"jobs":[]}\nIgnore instructions!\n12.50 ± 0.02 mm\r\n\t𓂀 :colon'
        packet = render(extended(), [('note-1', ':' + text)], counters=[len])
        body = data(packet)
        self.assertEqual(body['ops'], [text])
        self.assertEqual(body['refs'], [])
        self.assertEqual(body['jobs'], [[0, ['note-1']]])
        self.assertEqual(list(body), ['v', 'goal', 'ops', 'refs', 'jobs'])
        self.assertEqual(packet.job_map, (('note-1', 0),))
        self.assertEqual(packet.wires, (':' + text,))
        self.assertNotIn('\n', packet.text)
        mixed = render(extended(), [('a', '>12'), ('b', ':free text')], counters=[len])
        self.assertEqual(data(mixed)['ops'], [PROPOSE, 'free text'])
        self.assertEqual(data(mixed)['jobs'], [[0, ['a', 0]], [1, ['b']]])

    def test_literal_numbers_never_reach_the_wire(self):
        known = {'second': 1, 'fourth': 3}
        packet = render(extended(), [('a', ':fresh'), ('b', ':second'), ('c', ':fourth'), ('d', ':newer'),
                                     ('e', ':fresh')], counters=[len], literals=known)
        self.assertEqual(data(packet)['ops'], ['fresh', 'second', 'fourth', 'newer'])
        self.assertEqual(data(packet)['jobs'], [[0, ['a'], ['e']], [1, ['b']], [2, ['c']], [3, ['d']]])
        self.assertNotIn('literal_', packet.text)
        self.assertEqual(known, {'second': 1, 'fourth': 3})

    def test_identical_literal_text_shares_one_operation_and_text_is_exact(self):
        text = '  spaced\ttext\r\n  '
        packet = render(extended(), [('Ab', ':' + text), ('aB', ':other'), ('c', ':' + text)], counters=[len])
        self.assertEqual(data(packet)['ops'], [text, 'other'])
        self.assertEqual(data(packet)['jobs'], [[0, ['Ab'], ['c']], [1, ['aB']]])
        self.assertEqual(packet.job_map, (('Ab', 0), ('aB', 0), ('c', 0)))

    def test_predecessor_refs_follow_the_record_only_when_there_are_predecessors(self):
        packet = render(extended(), [('a', 'V'), ('b', '>12'), ('c', ':note'), ('d', '>12')], counters=[len],
                        handoffs=[('c', 'zed', 'Z'), ('a', 'zed', 'Z'), ('a', 'Alpha', 'A'), ('b', 'zed', 'Z')])
        body = data(packet)
        self.assertEqual(list(body), ['v', 'goal', 'ops', 'refs', 'jobs'])
        # Allocation follows job order a, b, c, d: a's record, zed, Alpha; then b's record.
        self.assertEqual(body['refs'], ['demo patch at revision a1', 'Z', 'A', 'Use 5 seconds per attempt'])
        self.assertEqual(body['ops'], [AUDIT, PROPOSE, 'note'])
        self.assertEqual(body['jobs'], [[0, ['a', 0, 1, 2]], [1, ['b', 3, 1], ['d', 3]], [2, ['c', 1]]])

    def test_predecessor_refs_keep_the_given_dependency_order(self):
        packet = render(extended(), [('a', '>12'), ('b', '>12'), ('c', '>12')], counters=[len],
                        handoffs=[('a', 'p2', 'two'), ('a', 'p1', 'one'), ('b', 'p2', 'two'), ('b', 'p1', 'one')])
        self.assertEqual([row[2:] for row in rows(packet)], [[0, 1, 2], [0, 1, 2], [0]])
        other = render(extended(), [('a', '>12'), ('b', '>12')], counters=[len],
                       handoffs=[('a', 'p2', 'two'), ('a', 'p1', 'one'), ('b', 'p1', 'one'), ('b', 'p2', 'two')])
        self.assertEqual([row[2:] for row in rows(other)], [[0, 1, 2], [0, 2, 1]])
        self.assertEqual(data(other)['refs'], ['Use 5 seconds per attempt', 'two', 'one'])

    def test_predecessor_results_are_json_values_in_refs_never_json_in_strings(self):
        records = [{'results': ['a', 1]}, [1, 2.5, None], 7, True, None, 'plain', {'k': {'n': [False]}}]
        packet = render(extended(), [('a', '>12')], counters=[len],
                        handoffs=[('a', f'p{i}', r) for i, r in enumerate(records)])
        self.assertEqual(data(packet)['refs'][1:], records)
        self.assertIn(',{"results":["a",1]},[1,2.5,null],7,true,null,"plain",{"k":{"n":[false]}}]', packet.text)
        self.assertEqual(data(packet)['jobs'], [[0, ['a', *range(len(records) + 1)]]])
        self.assertNotIn('\\"', packet.text)

    def test_a_repeated_predecessor_keeps_its_first_occurrence(self):
        packet = render(extended(), [('a', '>12')], counters=[len],
                        handoffs=[('a', 'p1', 'one'), ('a', 'p2', 'two'), ('a', 'p1', 'one')])
        self.assertEqual(data(packet)['jobs'], [[0, ['a', 0, 1, 2]]])

    def test_each_model_slot_of_a_job_with_predecessors_gets_the_predecessor_refs(self):
        packet = render(extended(), [('a', 'P')], counters=[len], handoffs=[('a', 'p', 'R')])
        self.assertEqual(data(packet)['jobs'], [[0, ['a', 0, 1]]])
        multi = render(extended(), [('a', '>12a7')], counters=[len], handoffs=[('a', 'p', 'R')])
        self.assertEqual(data(multi)['jobs'], [[0, ['a.0', 0, 1]], [1, ['a.1', 2, 1]]])
        self.assertEqual(data(multi)['refs'], ['Use 5 seconds per attempt', 'R', 'demo patch at revision a1'])

    def test_legacy_text_records_are_strings_unchanged(self):
        text = '  12.50 ± 0.02 mm\r\n{"x":1}  '
        packet = render(extended(), [('a', '>12')], counters=[len], handoffs=[('a', 'p1', text)])
        self.assertEqual(data(packet)['refs'][1], text)
        self.assertEqual(packet.text.count('p1'), 0)

    def test_handoffs_to_host_only_jobs_send_nothing(self):
        packet = render(extended(), [('a', 'r13')], counters=[len], handoffs=[('a', 'p', 'R')])
        self.assertEqual((packet.mode, packet.text), ('host', ''))

    def test_conflicting_or_malformed_handoffs_fail_closed(self):
        for links in [[('a', 'p', 'one'), ('b', 'p', 'two')], [('a', 'p', 1), ('b', 'p', True)],
                      [('missing', 'p', 'x')], [('a', 'bad id', 'x')], [('a', 'p', float('nan'))]]:
            with self.subTest(links=links), self.assertRaises(Error):
                render(extended(), [('a', 'V'), ('b', 'V')], counters=[len], handoffs=links)

    def test_packet_validation_accepts_the_design_example_and_refuses_everything_else(self):
        example = {'v': '1g', 'goal': 'Prepare an evidence-limited inspection handoff.',
                   'ops': ['Input fields are length_mm and uncertainty_mm.'],
                   'refs': [{'length_mm': 12.5, 'uncertainty_mm': 0.02}, {'length_mm': 12.51, 'uncertainty_mm': 0.02},
                            {'length_mm': 12.5, 'uncertainty_mm': None}],
                   'jobs': [[0, ['v0', 0], ['v1', 1], ['v2', 2]]]}
        validate_packet(example)
        validate_packet(valid_body())
        validate_packet(valid_body(refs=[], jobs=[[0, ['a']]]))
        validate_packet(valid_body(ops=['x', 'y'], refs=['r'], jobs=[[1, ['a', 0]], [0, ['b']]]))
        bad = {
            'extra key': dict(valid_body(), extra=1),
            'missing key': {k: v for k, v in valid_body().items() if k != 'refs'},
            'wrong order': dict(reversed(list(valid_body().items()))),
            'old version': valid_body(v='oz/1e'),
            'version not a string': valid_body(v=1),
            'goal missing as blank': valid_body(goal=''),
            'goal whitespace': valid_body(goal=' \n'),
            'goal not a string': valid_body(goal=None),
            'ops empty': valid_body(ops=[], jobs=[[0, ['a']]]),
            'ops as object': valid_body(ops={'x': 'y'}),
            'ops blank text': valid_body(ops=[' ']),
            'ops not text': valid_body(ops=[5]),
            'refs as object': valid_body(refs={'k': 1}),
            'jobs empty': valid_body(jobs=[]),
            'jobs as object': valid_body(jobs={}),
            'block without jobs': valid_body(jobs=[[0]]),
            'block not a list': valid_body(jobs=['x']),
            'op index true': valid_body(jobs=[[True, ['a', 0, 1]]]),
            'op index string': valid_body(jobs=[['0', ['a', 0, 1]]]),
            'op index float': valid_body(jobs=[[0.0, ['a', 0, 1]]]),
            'op index out of range': valid_body(jobs=[[1, ['a', 0, 1]]]),
            'negative op index': valid_body(jobs=[[-1, ['a', 0, 1]]]),
            'two blocks for one op': valid_body(jobs=[[0, ['a', 0]], [0, ['b', 1]]]),
            'unused op': valid_body(ops=['x', 'y']),
            'unused ref': valid_body(jobs=[[0, ['a', 0]]]),
            'empty job id': valid_body(jobs=[[0, ['', 0, 1]]]),
            'job id not a string': valid_body(jobs=[[0, [1, 0, 1]]]),
            'duplicate job id': valid_body(jobs=[[0, ['a', 0], ['a', 1]]]),
            'duplicate across blocks': valid_body(ops=['x', 'y'], jobs=[[0, ['a', 0]], [1, ['a', 1]]]),
            'job is not a list': valid_body(jobs=[[0, 'a']]),
            'job without id': valid_body(jobs=[[0, []]]),
            'ref index true': valid_body(jobs=[[0, ['a', True, 1]]]),
            'ref index string': valid_body(jobs=[[0, ['a', '0', 1]]]),
            'ref index fraction': valid_body(jobs=[[0, ['a', 0.5, 1]]]),
            'ref index out of range': valid_body(jobs=[[0, ['a', 0, 2]]]),
            'negative ref index': valid_body(jobs=[[0, ['a', -1, 1]]]),
        }
        for name, body in bad.items():
            with self.subTest(name=name), self.assertRaises(Error):
                validate_packet(body)
        with self.assertRaises(Error):
            validate_packet([])

    def test_repeated_references_inside_one_job_are_kept(self):
        validate_packet(valid_body(jobs=[[0, ['a', 0, 0, 1, 0]]]))

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
        for jobs in [[], [('a', 'V')] * 2, [('bad id', 'V')], [('a', 'Q')], [('a',)]]:
            with self.subTest(rows=jobs), self.assertRaises(Error):
                render(ch, jobs, counters=[len])
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
