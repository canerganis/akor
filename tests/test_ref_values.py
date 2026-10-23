"""Ordered two-ref model inputs and the opt-in JSON value form of `oz do` refs (boundary adoption, Opus section 7).

The default paths stay as shipped: a string or {"path"} ref is text, a one-input model operation binds `record` only
and its request, identity and packet are unchanged. {"value": <JSON value>} is the opt-in form: the packet carries
the value itself (probe arm C's form), memo identity covers its exact bytes, and an ordered ModelOp sends its inputs
as one row in its declared order through the shipped first-use packer."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oz import Error  # noqa: E402
from oz_accept import SELECTIVE, job_inputs  # noqa: E402
from oz_batch import SYSTEM, J  # noqa: E402
from oz_do import do, normalize  # noqa: E402
from oz_flow import HostError, ModelOp, _model_input, _stage_request, admit  # noqa: E402
from oz_memo import MemoStore  # noqa: E402
from oz_reply import encode_reply  # noqa: E402
from oz_runtime import Inbox  # noqa: E402
from oz_workspace import initialize  # noqa: E402

CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}
RECORD = 'length=12.51 mm; uncertainty=0.01 mm; n=1; method=caliper; basis=resolution; physical_validation=not_claimed'
OP = ('The first ref is the measurement record. The second ref is its host-checked interval: [lower,upper], or '
      'unknown. If the interval is unknown, return unknown.')


class Capture:
    """In-process adapter: records each request and answers every job with the JSON text of its refs."""
    capabilities = CAPS

    def __init__(self):
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        body = json.loads(request['prompt'])
        answers = {row[0]: 'inside' for block in body['jobs'] for row in block[1:]}
        return {'reply': encode_reply(answers), 'usage': {'input_tokens': 10, 'output_tokens': 2}}


def two_ref_op(**extra):
    return ModelOp('classify', 2, 'Goal [12.48,12.52] mm.', OP, (), True, inputs=('record', 'interval'),
                   values=frozenset({'interval'}), **extra)


class ValueRefTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'ws'
        initialize(self.root)
        self.config = json.loads((self.root / 'oz.json').read_text(encoding='utf-8'))

    def norm(self, refs, **extra):
        req = dict({'goal': 'g', 'ops': {'op': 'Do it.'}, 'refs': refs,
                    'jobs': [['j1', 'op', *refs]]}, **extra)
        return normalize(req, allow=self.root, config={'batch_size': 4, 'max_tokens': 1000})

    def test_string_refs_keep_their_text_source_and_digest(self):
        plain = self.norm({'r': 'unknown'})
        self.assertEqual(plain['work']['refs']['r'].split('@')[0], 'inline')
        self.assertNotIn('value', plain['texts']['r'])
        again = self.norm({'r': 'unknown'})
        self.assertEqual(plain['sha256'], again['sha256'])

    def test_value_refs_are_json_values_with_their_own_source_label(self):
        req = self.norm({'r': {'value': ['12.48 mm', '12.52 mm']}, 'u': {'value': 'unknown'}})
        self.assertEqual(req['texts']['r']['text'], '["12.48 mm","12.52 mm"]')
        self.assertEqual(req['texts']['r']['value'], ['12.48 mm', '12.52 mm'])
        self.assertEqual(req['work']['refs']['r'].split('@')[0], 'value')
        self.assertEqual(req['texts']['u']['value'], 'unknown')
        # A value-form ref is different work from a text ref with the same text.
        self.assertNotEqual(self.norm({'r': {'value': 'unknown'}})['sha256'], self.norm({'r': 'unknown'})['sha256'])

    def test_bad_value_refs_are_refused_before_anything_is_stored(self):
        for bad in ({'value': None}, {'value': '  '}, {'value': [1], 'path': 'x'}, {'value': float('nan')},
                    {'value': 'x' * 70000}):
            with self.assertRaises(Error, msg=repr(bad)[:40]):
                self.norm({'r': bad})
        self.assertFalse((self.root / 'do').exists())

    def test_inbox_complete_stores_an_opt_in_json_value(self):
        with Inbox(self.root / 'x.sqlite') as box:
            from oz import Channel, Reference
            ch = Channel(session='s', task='t', revision=1, sender='c', recipient='host', goal='g',
                         references=[Reference(1, 'source', 'x')], active=1)
            box.post(ch, 'a', 'r1', binding=ch.binding, max_attempts=1)
            box.post(ch, 'b', 'r1', binding=ch.binding, max_attempts=1)
            delivery = box.claim(ch, owner='host', kind='work', limit=8, lease_seconds=30)
            with self.assertRaises(Error):
                box.complete(delivery, {'a': 'x', 'b': 'y'}, values={'a': 'not json'})
            box.complete(delivery, {'a': '["1"]', 'b': 'y'}, values={'a': '["1"]'})
            rows = box.records(['a', 'b'])
        self.assertEqual(rows['a']['result_json'], '["1"]')
        self.assertIsNone(rows['b']['result_json'])

    def test_the_ref_form_is_part_of_the_request_identity(self):
        # A file named "value" holding [1] and {"value": [1]} carry the same text and the same label, yet they are
        # different wire types (a string versus an array): they must be different work.
        (self.root / 'value').write_text('[1]', encoding='utf-8')
        as_path = self.norm({'r': {'path': 'value'}})
        as_value = self.norm({'r': {'value': [1]}})
        self.assertEqual(as_path['texts']['r']['text'], as_value['texts']['r']['text'])
        self.assertNotEqual(as_path['sha256'], as_value['sha256'])
        self.assertNotEqual(as_path['work'], as_value['work'])
        # Exact bytes: true, 1 and 1.0 are three different values.
        digests = {self.norm({'r': {'value': v}})['sha256'] for v in (True, 1, 1.0)}
        self.assertEqual(len(digests), 3)

    def test_default_requests_keep_their_identity_without_ref_forms(self):
        plain = self.norm({'r': 'unknown'})
        self.assertEqual(set(plain['work']), {'goal', 'ops', 'refs', 'jobs', 'max_attempts'})
        mixed = self.norm({'r': 'unknown', 's': {'value': [1]}})
        self.assertIn('ref_forms', mixed['work'])

    def test_reusing_a_request_id_with_another_ref_form_is_refused(self):
        (self.root / 'value').write_text('[1]', encoding='utf-8')
        adapter = Capture()

        def req(ref):
            return {'request_id': 'form1', 'goal': 'g', 'ops': {'op': OP}, 'model': 'claude-sonnet-5-5',
                    'refs': {'r': ref}, 'jobs': [['a', 'op', 'r']], 'allow_experimental': True,
                    'max_input_tokens': 100000, 'profile': SELECTIVE}
        first = self.run_do(req({'path': 'value'}), adapter)
        self.assertEqual(first['status'], 'complete', first)
        with self.assertRaisesRegex(Error, 'already names different work'):
            self.run_do(req({'value': [1]}), adapter)
        # And the other way round on a fresh id.
        other = dict(req({'value': [1]}), request_id='form2')
        self.assertEqual(self.run_do(other, adapter)['status'], 'complete')
        with self.assertRaisesRegex(Error, 'already names different work'):
            self.run_do(dict(req({'path': 'value'}), request_id='form2'), adapter)

    def test_the_carried_value_is_exactly_what_the_text_and_digest_say(self):
        # A tuple and an int key do not survive their JSON text; the carried value must be the text's value.
        req = self.norm({'r': {'value': (1, {1: 'a'})}})
        self.assertEqual(req['texts']['r']['text'], '[1,{"1":"a"}]')
        self.assertEqual(req['texts']['r']['value'], [1, {'1': 'a'}])
        self.assertIs(type(self.norm({'r': {'value': True}})['texts']['r']['value']), bool)
        self.assertIs(type(self.norm({'r': {'value': 1.0}})['texts']['r']['value']), float)

    def run_do(self, request, adapter, **options):
        return do(request, workspace=self.root, adapter=adapter, **options)

    def test_the_packet_carries_the_value_and_text_refs_as_strings(self):
        adapter = Capture()
        req = {'request_id': 'v1', 'goal': 'g', 'ops': {'op': OP}, 'model': 'claude-sonnet-5-5',
               'refs': {'a-record': RECORD, 'a-interval': {'value': ['12.50 mm', '12.52 mm']},
                        'b-record': RECORD.replace('12.51', '12.50').replace('0.01 mm', 'unknown'),
                        'b-interval': {'value': 'unknown'}},
               'jobs': [['a', 'op', 'a-record', 'a-interval'], ['b', 'op', 'b-record', 'b-interval']],
               'allow_experimental': True, 'max_input_tokens': 100000, 'profile': SELECTIVE}
        result = self.run_do(req, adapter)
        self.assertEqual(result['status'], 'complete', result)
        self.assertEqual(adapter.requests[0]['system'], SYSTEM)
        body = json.loads(adapter.requests[0]['prompt'])
        # The shipped first-use layout: record and interval interleaved per job, in row order.
        self.assertEqual(body['refs'][1], ['12.50 mm', '12.52 mm'])
        self.assertEqual(body['refs'][3], 'unknown')
        self.assertEqual(body['refs'][0], RECORD)
        self.assertEqual(body['jobs'], [[0, ['a', 0, 1], ['b', 2, 3]]])
        self.assertIn('["12.50 mm","12.52 mm"]', adapter.requests[0]['prompt'])

    def test_memo_identity_covers_the_value_bytes_and_plan_only_agrees_with_dispatch(self):
        store = MemoStore(self.root / 'memo.sqlite')
        self.addCleanup(store.close)
        memo = {'store': store, 'namespace': 'ns', 'ops': ['op']}

        def req(rid, interval):
            return {'request_id': rid, 'goal': 'g', 'ops': {'op': OP}, 'model': 'claude-sonnet-5-5',
                    'refs': {'a-record': RECORD, 'a-interval': {'value': interval}},
                    'jobs': [['a', 'op', 'a-record', 'a-interval']], 'allow_experimental': True,
                    'max_input_tokens': 100000, 'profile': SELECTIVE,
                    'checks': {'op': [{'check': 'expect', 'value': 'inside'}]}}
        first = self.run_do(req('m1', ['12.50 mm', '12.52 mm']), Capture(), memo=memo)
        self.assertEqual(first['status'], 'complete')
        hit = do(req('m2', ['12.50 mm', '12.52 mm']), workspace=self.root, memo=memo, plan_only=True,
                 adapter=Capture())
        self.assertEqual(hit['plan']['memo']['a']['decision'], 'hit', hit['plan']['memo'])
        miss = do(req('m3', ['12.49 mm', '12.52 mm']), workspace=self.root, memo=memo, plan_only=True,
                  adapter=Capture())
        self.assertEqual(miss['plan']['memo']['a']['decision'], 'miss')
        # The dispatched packet's model-visible inputs carry the interval as its JSON bytes.
        run = self.root / first['run']['run_dir']
        db = sqlite3.connect(run / 'inbox.sqlite')
        try:
            packet, members = db.execute('SELECT packet,members FROM dispatches').fetchone()
        finally:
            db.close()
        inputs = job_inputs(packet, [(m['id'], 0) for m in json.loads(members)])
        self.assertEqual(inputs['a'].slots[0]['refs'], [J(RECORD), '["12.50 mm","12.52 mm"]'])


class OrderedInputTests(unittest.TestCase):
    def test_default_model_op_identity_and_request_are_unchanged(self):
        op = ModelOp('classify', 1, 'goal', 'instr', (), True)
        self.assertEqual(op.ref_order, ('record',))
        self.assertTrue(op.identity.startswith('classify@1:sha256:'))
        req = _stage_request('f', op, ['n1'], {'n1': 'text'}, {'n1': 1}, 60, 30, 'm', 1000)
        self.assertEqual(req['refs'], {'n1': 'text'})
        self.assertEqual(req['jobs'], [['n1', 'classify', 'n1']])

    def test_ordered_inputs_change_identity_and_emit_one_row_in_order(self):
        op = two_ref_op()
        plain = ModelOp('classify', 2, op.goal, op.instruction, (), True)
        self.assertNotEqual(op.identity, plain.identity)
        self.assertEqual(op.ref_order, ('record', 'interval'))
        req = _stage_request('f', op, ['classify_A', 'classify_B'],
                             {'classify_A': [RECORD, ['12.50 mm', '12.52 mm']], 'classify_B': [RECORD, 'unknown']},
                             {'classify_A': 1, 'classify_B': 1}, 60, 30, 'm', 1000)
        self.assertEqual(req['jobs'], [['classify_A', 'classify', 'classify_A-record', 'classify_A-interval'],
                                       ['classify_B', 'classify', 'classify_B-record', 'classify_B-interval']])
        self.assertEqual(req['refs']['classify_A-interval'], {'value': ['12.50 mm', '12.52 mm']})
        self.assertEqual(req['refs']['classify_B-interval'], {'value': 'unknown'})
        self.assertEqual(req['refs']['classify_A-record'], RECORD)
        # A changed interval alone changes the stage request identity.
        other = _stage_request('f', op, ['classify_A'], {'classify_A': [RECORD, ['12.49 mm', '12.52 mm']]},
                               {'classify_A': 1}, 60, 30, 'm', 1000)
        same = _stage_request('f', op, ['classify_A'], {'classify_A': [RECORD, ['12.50 mm', '12.52 mm']]},
                              {'classify_A': 1}, 60, 30, 'm', 1000)
        self.assertNotEqual(other['request_id'], same['request_id'])

    def test_admission_needs_exactly_the_declared_inputs(self):
        registry = {'model.c': two_ref_op(), 'host.src': None}
        from oz_flow import HostOp
        registry['host.src'] = HostOp('host.src', 1, frozenset({'x'}), lambda i, c: {})
        node = {'id': 'src', 'op': 'host.src', 'in': {'x': {'lit': 1}}, 'after': []}
        ok = {'v': 1, 'base': 0, 'nodes': [node, {'id': 'c', 'op': 'model.c', 'after': [], 'in': {
            'record': {'node': 'src', 'path': '/r'}, 'interval': {'node': 'src', 'path': '/i'}}}],
            'outputs': {'t': 'c'}}
        descriptors = admit(ok, registry)
        model = next(d for d in descriptors if d['id'] == 'c')
        self.assertEqual(model['refs'], ['record', 'interval'])
        self.assertEqual(model['values'], ['interval'])
        bad = json.loads(json.dumps(ok))
        del bad['nodes'][1]['in']['interval']
        with self.assertRaisesRegex(Error, 'inputs must be exactly'):
            admit(bad, registry)

    def test_bindings_resolve_in_order_and_refuse_blank_or_missing_values(self):
        op = two_ref_op()
        bindings = {'interval': {'node': 'n', 'path': '/bounds/A'}, 'record': {'node': 'n', 'path': '/records/A'}}
        values = {'n': {'records': {'A': RECORD}, 'bounds': {'A': ['12.50 mm', '12.52 mm']}}}
        self.assertEqual(_model_input(op, bindings, values, None), [RECORD, ['12.50 mm', '12.52 mm']])
        for bad in (None, '', '  '):
            with self.assertRaisesRegex(HostError, 'nonblank JSON value'):
                _model_input(op, bindings, {'n': {'records': {'A': RECORD}, 'bounds': {'A': bad}}}, None)
        with self.assertRaisesRegex(HostError, 'nonblank text'):
            _model_input(op, bindings, {'n': {'records': {'A': ['x']}, 'bounds': {'A': 'unknown'}}}, None)
        plain = ModelOp('extract', 1, 'g', 'i', (), True)
        self.assertEqual(_model_input(plain, {'record': {'node': 'n', 'path': '/records/A'}}, values, None), RECORD)


class ResumeInputComparisonTests(unittest.TestCase):
    """A pending stage is reused only when its resolved inputs are the same bytes (foundation clauses 1 and 12)."""

    def pinned_stage(self, stored, fresh):
        """Run _run_stage for node n whose recorded submission carried `stored` and whose inputs now resolve to
        `fresh`; return the regenerated events (the stage is stopped at its first call)."""
        import oz_flow
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        flow = oz_flow.Flow(Path(temp.name) / 'flow.sqlite')
        self.addCleanup(flow.close)
        flow.db.execute("INSERT INTO nodes(id,idx,descriptor) VALUES ('n',0,'{}')")
        op = two_ref_op()
        settings = oz_flow.Settings(workspace=Path(temp.name), adapter=None, registry={}, checks_registry={},
                                    route={}, model='m')
        rid = _stage_request('f', op, ['n'], {'n': stored}, {'n': 1}, 100, 30, settings.model,
                             settings.max_input_tokens)['request_id']
        flow.event('stage_submitted', op=op.name, nodes=['n'], request_id=rid, run_dir='do/' + rid,
                   members=['n'], texts={'n': stored}, generations={'n': 1})
        descriptors = {'n': {'bindings': {'record': {'lit': stored[0]}, 'interval': {'lit': fresh}}, 'deps': [],
                             'generation': 1}}

        class Stop(Exception):
            pass

        def stop(*_a, **_k):
            raise Stop

        from unittest import mock
        with mock.patch.object(oz_flow, 'do', stop), mock.patch.object(oz_flow, 'stage_launches', lambda _r: []):
            try:
                result = oz_flow._run_stage(flow, {'request_id': 'f'}, settings, op, ['n'], descriptors, {}, {},
                                            100, 30, None, None)
            except Stop:
                result = 'stopped'
            self.assertEqual(result, 'stopped')
        return [e['details'] for e in flow.events() if e['event'] == 'regenerated']

    def test_an_equal_but_differently_typed_pending_input_opens_a_new_generation(self):
        for stored, fresh in ((True, 1), (1, 1.0), (1, True), ([True], [1]), ({'a': 1}, {'a': 1.0})):
            regenerated = self.pinned_stage([RECORD, stored], fresh)
            self.assertEqual([r.get('reason') for r in regenerated], ['inputs_changed'], (stored, fresh))

    def test_identical_pending_inputs_are_reused(self):
        for same in (True, 1, 1.0, [1, 'x'], {'a': [1.5]}):
            self.assertEqual(self.pinned_stage([RECORD, same], same), [], same)


if __name__ == '__main__':
    unittest.main()
