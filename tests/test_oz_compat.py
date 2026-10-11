"""Saved OZ/2 state from 0.8.0 keeps working; removed OZ/3-5 state fails closed."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from oz import Channel, Error
from oz_runtime import Inbox, Outcome

FIXTURES = Path(__file__).parent / 'fixtures'


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


class CompatibilityTests(unittest.TestCase):
    def test_oz2_binding_is_unchanged_since_0_8_0(self):
        saved = fixture('oz2-channel.json')
        self.assertEqual(saved['binding'], 'f4eaee805ef77d70c4e322d1bd7a4a31fb9ad77d709798e1a555b21abb9b8132')
        channel = Channel.from_snapshot(saved['channel'])
        self.assertEqual(channel.binding, saved['binding'])
        self.assertEqual(Channel.from_snapshot(channel.snapshot()).binding, saved['binding'])

    def test_vectors_false_is_accepted_as_a_no_op(self):
        saved = fixture('oz2-channel.json')
        channel = Channel.from_snapshot(dict(saved['channel'], vectors=False))
        self.assertEqual(channel.binding, saved['binding'])

    def test_saved_inbox_jobs_claim_and_settle_unchanged(self):
        saved = fixture('oz2-channel.json')
        channel = Channel.from_snapshot(saved['channel'])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'inbox.sqlite3'
            shutil.copyfile(FIXTURES / 'oz2-inbox.sqlite3', path)
            with Inbox(path) as box:
                self.assertEqual(box.inspect('work1')['attempts'], 1)
                self.assertEqual(box.channel(saved['binding']).binding, saved['binding'])
                delivery = box.claim(channel, owner='test', limit=8)
                self.assertEqual([job.id for job in delivery.jobs], ['work1', 'work2'])
                box.settle(delivery, {job.id: Outcome('ok', 'done ' + job.id) for job in delivery.jobs})
                follow = box.claim(channel, owner='test', limit=8)
                self.assertEqual([job.id for job in follow.jobs], ['work3'])
                self.assertEqual(channel.accept(follow.jobs[0].wire, binding=channel.binding),
                                 channel.accept('V', binding=channel.binding))

    def test_removed_layers_fail_with_a_specific_message_and_do_not_mutate(self):
        legacy = fixture('oz5-legacy-channel.json')
        before = json.dumps(legacy, sort_keys=True)
        with self.assertRaisesRegex(Error, r'^uses removed OZ/3-5 feature vectors; re-export as OZ/2$'):
            Channel.from_snapshot(legacy)
        self.assertEqual(json.dumps(legacy, sort_keys=True), before)
        oz2 = fixture('oz2-channel.json')['channel']
        for key, value in [('vectors', True), ('basis', [{'code': 'r', 'ref': 1, 'text': None}]),
                           ('form', [{'code': 'r', 'ref': 0, 'text': None}])]:
            with self.subTest(key=key), self.assertRaisesRegex(Error, f'^uses removed OZ/3-5 feature {key}; re-export as OZ/2$'):
                Channel.from_snapshot(dict(oz2, **{key: value}))

    def test_malformed_legacy_fields_are_rejected_before_removal_checks(self):
        oz2 = fixture('oz2-channel.json')['channel']
        for key, value in [('vectors', None), ('vectors', 0), ('vectors', []), ('basis', False),
                           ('basis', None), ('form', 0), ('form', {})]:
            with self.subTest(key=key, value=value), self.assertRaisesRegex(Error, 'invalid legacy field ' + key):
                Channel.from_snapshot(dict(oz2, **{key: value}))
        saved = fixture('oz2-channel.json')['binding']
        self.assertEqual(Channel.from_snapshot(dict(oz2, basis=[], form=[])).binding, saved)

    def test_removed_wire_syntax_is_rejected(self):
        channel = Channel.from_snapshot(fixture('oz2-channel.json')['channel'])
        for wire in ['r[1,2]', '^', '^0=r1', '&1']:
            with self.subTest(wire=wire), self.assertRaises(Error):
                channel.accept(wire, binding=channel.binding)


if __name__ == '__main__':
    unittest.main()
