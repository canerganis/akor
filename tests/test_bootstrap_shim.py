"""examples/bootstrap_shim.py: enablement, claim, raw capture, exact AST slices, A2.1 failure, pinned effective spec,
leakage lint and route closure. No model call: the real adapter is a fake script."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'examples'))
import bootstrap_shim as shim  # noqa: E402
from oz import Error  # noqa: E402
from oz_route import adapter_hash, source_manifest  # noqa: E402

SHIM = ROOT / 'examples' / 'bootstrap_shim.py'
SPEC = ROOT / 'docs' / 'design' / 'ozmap-2026-10-24' / 'oz-rule-1-spec.md'
EXCERPT = ROOT / 'docs' / 'design' / 'ozmap-2026-10-24' / 'bootstrap-spec-excerpt.txt'
USAGE = {'input_tokens': 5, 'output_tokens': 1}
ANSWERS = 'OZ/1g\n{"j1":"ok"}'
MALFORMED = shim.MALFORMED_REPLY

REAL = r'''
import json, os, sys, time
if '--identity' in sys.argv:
    print(json.dumps({'backend': 'fake', 'model': 'm', 'effort': 'e', 'cli_version': '1', 'flags': ['-f']})); raise SystemExit
data = sys.stdin.buffer.read()
if os.environ.get('FAKE_LOG'):
    with open(os.environ['FAKE_LOG'], 'ab') as f:
        f.write(json.dumps({'bootstrap_env': [k for k in os.environ if k.startswith('OZ_BOOTSTRAP')],
                            'system': json.loads(data)['system']}).encode() + b'\n')
if os.environ.get('FAKE_SLEEP'):
    time.sleep(float(os.environ['FAKE_SLEEP']))
mode = os.environ.get('FAKE_MODE', 'reply')
if mode == 'exit':
    sys.stdout.buffer.write(b'partial stdout'); sys.stderr.write('boom on stderr'); sys.exit(3)
if mode == 'binary':
    sys.stdout.buffer.write(b'\xff\xfe\x00{'); sys.stderr.write('warn'); sys.exit(0)
if mode == 'plain':
    reply = 'OZ/1g\n{"j1":"plain"}'
else:
    reply = open(os.environ['FAKE_REPLY_FILE'], encoding='utf-8').read()
sys.stderr.write('note on stderr')
json.dump({'reply': reply, 'usage': {'input_tokens': 5, 'output_tokens': 1}}, sys.stdout)
'''


def envelope(rules, answers=ANSWERS, pre=''):
    return pre + '{"host":"oz-bootstrap/1","answers":' + json.dumps(answers) + ',"rules":' + rules + '}'


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('OZ_BOOTSTRAP', 'FAKE_'))}
    env.update(extra)
    return env


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.real = self.dir / 'real.py'
        self.real.write_text(REAL, encoding='utf-8')
        self.side = self.dir / 'side'
        self.log = self.dir / 'calls.log'
        self.reply_file = self.dir / 'reply.txt'

    def config(self, attempt='a1', ops=('e', 'b'), **override):
        self.side.mkdir(exist_ok=True)
        value = {'schema': shim.CONFIG_SCHEMA, 'ops': list(ops), 'contracts': {o: {'name': o} for o in ops},
                 'eligibility': {o: True for o in ops}}
        value.update(override)
        (self.side / f'{attempt}.config.json').write_text(json.dumps(value), encoding='utf-8')

    def env(self, attempt='a1', **extra):
        env = clean_env(FAKE_REPLY_FILE=str(self.reply_file), FAKE_LOG=str(self.log), **extra)
        if attempt:
            env.update(OZ_BOOTSTRAP_ATTEMPT=attempt, OZ_BOOTSTRAP_DIR=str(self.side))
        return env

    def popen(self, env, request=None, *args):
        request = request or {'receipt': '7', 'ids': ['j1'], 'system': 'SYS', 'prompt': '{}'}
        return subprocess.Popen([sys.executable, str(SHIM), str(self.real), *args], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env), json.dumps(request).encode()

    def run_shim(self, env, request=None, *args):
        proc, data = self.popen(env, request, *args)
        out, err = proc.communicate(data, timeout=120)
        return proc.returncode, out, err

    def read_side(self, attempt='a1'):
        return json.loads((self.side / f'{attempt}.json').read_text(encoding='utf-8'))

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding='utf-8').splitlines()]


class Passthrough(Base):
    def test_without_the_child_env_the_real_answer_comes_back_byte_for_byte(self):
        for env in (self.env(None), self.env(None, OZ_BOOTSTRAP_ATTEMPT='a1'),
                    self.env(None, OZ_BOOTSTRAP_DIR=str(self.side)), self.env(None, OZ_BOOTSTRAP='C:/old/config.json')):
            with self.subTest(env=sorted(k for k in env if k.startswith('OZ_BOOT'))):
                self.log.unlink(missing_ok=True)
                code, out, err = self.run_shim(dict(env, FAKE_MODE='plain'))
                self.assertEqual(code, 0, err)
                self.assertEqual(out, json.dumps({'reply': 'OZ/1g\n{"j1":"plain"}', 'usage': USAGE}).encode())
                self.assertEqual(err, b'note on stderr')
                self.assertNotIn('oz-bootstrap/1', self.calls()[0]['system'])
        self.assertFalse(self.side.exists())

    def test_passthrough_relays_a_failing_adapter_unchanged(self):
        code, out, err = self.run_shim(self.env(None, FAKE_MODE='exit'))
        self.assertEqual((code, out, err), (3, b'partial stdout', b'boom on stderr'))

    def test_identity_is_relayed_with_the_shim_and_adapter_closure(self):
        code, out, err = self.run_shim(self.env(None), None, '--identity')
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertEqual((report['backend'], report['model']), ('fake', 'm'))
        info = report['bootstrap_shim']
        self.assertEqual(info['shim_sha256'], hashlib.sha256(SHIM.read_bytes()).hexdigest())
        self.assertEqual(info['adapter_sha256'], hashlib.sha256(self.real.read_bytes()).hexdigest())
        self.assertIn(['bootstrap_shim.py', info['shim_sha256']], info['shim_closure'])
        names = [n for n, _ in info['shim_closure']]
        self.assertTrue(any(n.endswith('bootstrap-spec-excerpt.txt') for n in names))
        self.assertEqual(info['spec_excerpt_sha256'], shim.SPEC_EXCERPT_SHA256)
        self.assertEqual(sorted(info['closure']), sorted(info['shim_closure'] + info['adapter_closure']))
        self.assertIn('bootstrap-spec-sha256=' + shim.SPEC_EXCERPT_SHA256, report['flags'])


class Claim(Base):
    def test_two_concurrent_processes_one_attempt_exactly_one_launch(self):
        self.config()
        self.reply_file.write_text(envelope('{"e":"none","b":"none"}'), encoding='utf-8')
        env = self.env(FAKE_SLEEP='2')
        first, data = self.popen(env)
        second, _ = self.popen(env)
        results = []
        for proc in (first, second):
            out, err = proc.communicate(data, timeout=120)
            results.append((proc.returncode, out, err))
        codes = sorted(r[0] for r in results)
        self.assertEqual(codes, [0, shim.EXIT_CLAIMED])
        loser = next(r for r in results if r[0] == shim.EXIT_CLAIMED)
        self.assertEqual(loser[1], b'')
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.read_side()['status'], 'ok')
        self.assertTrue((self.side / 'a1.claim').exists())

    def test_claim_function_is_exclusive(self):
        self.side.mkdir()
        self.assertTrue(shim._claim(str(self.side), 'x', '1'))
        self.assertFalse(shim._claim(str(self.side), 'x', '2'))
        self.assertTrue(shim._claim(str(self.side), 'y', '2'))

    def test_invalid_attempt_ids_launch_nothing(self):
        for bad in ('../x', 'a/b', 'a b', '', 'x' * 129):
            if not bad:
                continue
            code, out, err = self.run_shim(self.env(bad))
            self.assertEqual((code, out), (shim.EXIT_REFUSED, b''), bad)
        self.assertEqual(self.calls(), [])

    def test_unusable_config_still_writes_the_side_file_and_launches_nothing(self):
        for name, cfg in (('missing', None), ('badjson', '{'), ('extra key', json.dumps(
                {'schema': shim.CONFIG_SCHEMA, 'ops': ['e'], 'contracts': {'e': 1}, 'eligibility': {'e': True},
                 'spec': 'x'})), ('ops mismatch', json.dumps(
                {'schema': shim.CONFIG_SCHEMA, 'ops': ['e'], 'contracts': {}, 'eligibility': {'e': True}}))):
            with self.subTest(name):
                self.side.mkdir(exist_ok=True)
                attempt = 'c' + str(abs(hash(name)))
                if cfg is not None:
                    (self.side / f'{attempt}.config.json').write_text(cfg, encoding='utf-8')
                code, out, err = self.run_shim(self.env(attempt))
                self.assertEqual((code, out), (shim.EXIT_REFUSED, b''))
                side = self.read_side(attempt)
                self.assertEqual((side['status'], side['launched']), ('failed', False))
                self.assertTrue(side['reason'].startswith('config_invalid'))
        self.assertEqual(self.calls(), [])


class Capture(Base):
    def test_success_records_the_complete_evidence_and_returns_the_answers(self):
        self.config()
        self.reply_file.write_text(envelope('{"e":"none","b":"none"}'), encoding='utf-8')
        code, out, err = self.run_shim(self.env())
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {'reply': ANSWERS, 'usage': USAGE})
        self.assertEqual(err, b'note on stderr')
        side = self.read_side()
        self.assertEqual((side['schema'], side['attempt_id'], side['status'], side['reason']),
                         ('oz.bootstrap.side/2', 'a1', 'ok', None))
        self.assertEqual((side['exit_code'], side['timed_out'], side['launched'], side['envelope_ok']),
                         (0, False, True, True))
        self.assertEqual(side['answers_reply'], ANSWERS)
        self.assertEqual(side['rules'], {'e': {'none': True}, 'b': {'none': True}})
        self.assertEqual(side['usage'], USAGE)
        self.assertEqual(base64.b64decode(side['stderr_b64']), b'note on stderr')
        raw = base64.b64decode(side['stdout_b64'])
        self.assertEqual(json.loads(raw)['reply'], self.reply_file.read_text(encoding='utf-8'))
        self.assertEqual(side['stdout_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual((side['receipt'], side['ids'], side['ops']), ('7', ['j1'], ['e', 'b']))
        self.assertEqual(side['spec_sha256'], shim.SPEC_EXCERPT_SHA256)
        self.assertEqual(side['instruction_sha256'], shim.INSTRUCTION_SHA256)
        capture = json.loads((self.side / 'a1.capture.json').read_text(encoding='utf-8'))
        self.assertEqual((capture['exit_code'], capture['timed_out'], capture['stdout_b64']),
                         (0, False, side['stdout_b64']))
        # The real adapter saw the augmented system text and no bootstrap variable.
        [call] = self.calls()
        self.assertEqual(call['bootstrap_env'], [])
        self.assertTrue(call['system'].startswith('SYS\n\n' + shim.INSTRUCTION))
        self.assertEqual(side['system_sha256'], hashlib.sha256(call['system'].encode('utf-8')).hexdigest())

    def test_nonzero_exit_is_captured_and_relayed(self):
        self.config()
        code, out, err = self.run_shim(self.env(FAKE_MODE='exit'))
        self.assertEqual((code, out, err), (3, b'partial stdout', b'boom on stderr'))
        side = self.read_side()
        self.assertEqual((side['status'], side['exit_code'], side['timed_out'], side['envelope_ok']),
                         ('failed', 3, False, False))
        self.assertEqual((base64.b64decode(side['stdout_b64']), base64.b64decode(side['stderr_b64'])),
                         (b'partial stdout', b'boom on stderr'))
        self.assertEqual(side['reason'], 'adapter_exit_3')
        self.assertEqual(side['rules'], {})

    def test_timeout_is_captured_with_the_flag(self):
        self.config()
        code, out, err = self.run_shim(self.env(FAKE_SLEEP='60', OZ_BOOTSTRAP_TIMEOUT='1.5'))
        self.assertEqual((code, out), (shim.EXIT_TIMEOUT, b''))
        side = self.read_side()
        self.assertEqual((side['status'], side['timed_out'], side['reason'], side['launched']),
                         ('failed', True, 'timeout', True))
        self.assertIsNone(side['exit_code'])
        self.assertTrue((self.side / 'a1.capture.json').exists())

    def test_undecodable_stdout_is_captured_before_parsing_and_relayed(self):
        self.config()
        code, out, err = self.run_shim(self.env(FAKE_MODE='binary'))
        self.assertEqual((code, out, err), (0, b'\xff\xfe\x00{', b'warn'))
        side = self.read_side()
        self.assertEqual((side['status'], side['reason'], side['exit_code']), ('failed', 'stdout_undecodable', 0))
        self.assertEqual(base64.b64decode(side['stdout_b64']), b'\xff\xfe\x00{')
        self.assertEqual(json.loads((self.side / 'a1.capture.json').read_text())['stdout_b64'], side['stdout_b64'])

    def test_in_process_capture_is_published_before_a_parse_defect_escapes(self):
        # A defect after the claim still leaves the side file (status failed, shim_error) and the raw capture.
        self.config()
        original = shim._analyse
        shim._analyse = lambda cap, ops: 1 / 0
        self.addCleanup(setattr, shim, '_analyse', original)
        env = self.env()
        out, err, code = shim.run(json.dumps({'receipt': '1', 'ids': [], 'system': 'S', 'prompt': ''}).encode(),
                                  lambda data, timeout: shim.Capture(b'{"reply":"x"}', b'', 0), env)
        self.assertEqual((code, out), (shim.EXIT_SOFTWARE, b''))
        side = self.read_side()
        self.assertEqual(side['status'], 'failed')
        self.assertTrue(side['reason'].startswith('shim_error: ZeroDivisionError'))
        self.assertEqual(base64.b64decode(side['stdout_b64']), b'{"reply":"x"}')


class ExactSlices(Base):
    AST = '{"lang":"oz-rule/1",\n  "expr" : ["d", "12.50" ,"x\\u00e9"] }'

    def test_slice_bytes_keep_whitespace_numerals_and_escapes(self):
        text = envelope('{ "e" :  ' + self.AST + ' ,\t"b":"none" }', pre='  \n')
        answers, rules = shim.parse_envelope(text, ['e', 'b'])
        self.assertEqual(answers, ANSWERS)
        data = self.AST.encode('utf-8')
        self.assertEqual(rules['e'], {'ast_b64': base64.b64encode(data).decode(), 'ast_sha256':
                                      hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
        self.assertEqual(rules['b'], {'none': True})
        self.assertEqual(list(rules), ['e', 'b'])

    def test_numeric_spelling_is_not_normalized(self):
        ast = '{"lang":"oz-rule/1","expr":["num",["field","k"],"mm"],"n":12.50,"m":1E+2,"z":-0.0}'
        _, rules = shim.parse_envelope(envelope('{"e":' + ast + '}'), ['e'])
        self.assertEqual(base64.b64decode(rules['e']['ast_b64']).decode(), ast)

    def test_multibyte_text_counts_bytes_not_characters(self):
        ast = '{"lang":"oz-rule/1","expr":["s","' + '\u00e9' * 10 + '"]}'
        _, rules = shim.parse_envelope(envelope('{"e":' + ast + '}'), ['e'])
        self.assertEqual(rules['e']['bytes'], len(ast.encode('utf-8')))
        self.assertGreater(rules['e']['bytes'], len(ast))

    def padded(self, size):
        base = '{"lang":"oz-rule/1","expr":["s","'
        ast = base + 'x' * (size - len(base) - 3) + '"]}'
        self.assertEqual(len(ast.encode('utf-8')), size)
        return ast

    def test_2048_bytes_accepted_and_2049_rejected(self):
        _, rules = shim.parse_envelope(envelope('{"e":' + self.padded(2048) + '}'), ['e'])
        self.assertEqual(rules['e']['bytes'], 2048)
        with self.assertRaisesRegex(shim.Malformed, '2049 bytes'):
            shim.parse_envelope(envelope('{"e":' + self.padded(2049) + '}'), ['e'])
        # Whitespace counts: a short AST padded to 2049 bytes with spaces is also over the limit.
        padded = '{"lang":"oz-rule/1","expr":["bool",true]' + ' ' * 2010 + '}'
        self.assertGreater(len(padded), 2048)
        with self.assertRaises(shim.Malformed):
            shim.parse_envelope(envelope('{"e":' + padded + '}'), ['e'])

    def test_invalid_unicode_is_rejected_everywhere(self):
        bad_asts = ['{"lang":"oz-rule/1","expr":["s","\\ud800"]}', '{"lang":"oz-rule/1","expr":["s","\\udc00"]}',
                    '{"lang":"oz-rule/1","expr":["s","\\ud800x"]}', '{"lang":"oz-rule/1","expr":["s","\\ud800\\u0041"]}',
                    '{"lang":"oz-rule/1","expr":["s","\ud800"]}', '{"lang":"oz-rule/1","expr":["s","a\x01"]}',
                    '{"lang":"oz-rule/1","expr":["s","\\x"]}']
        for ast in bad_asts:
            with self.subTest(ast=ast), self.assertRaises(shim.Malformed):
                shim.parse_envelope(envelope('{"e":' + ast + '}'), ['e'])
        with self.assertRaises(shim.Malformed):  # also in answers
            shim.parse_envelope(envelope('{"e":"none"}', answers='ok \ud800'), ['e'])
        good = '{"lang":"oz-rule/1","expr":["s","\\ud83d\\ude00 \U0001F600"]}'
        shim.parse_envelope(envelope('{"e":' + good + '}'), ['e'])

    def test_every_other_defect_is_malformed(self):
        ok = envelope('{"e":"none"}')
        for text in ['```json\n' + ok + '\n```', ok + ' x', ok + '{}', '\ufeff' + ok, 'OZ/1g\n{"j1":"x"}', '', None,
                     ok.replace('"host"', '"hostx"'), ok.replace('oz-bootstrap/1', 'oz-bootstrap/2'),
                     envelope('{"e":"none","b":"none"}'), envelope('{}'), envelope('{"e":"NONE"}'),
                     envelope('{"e":null}'), envelope('{"e":["field"]}'), envelope('{"e":7}'),
                     envelope('{"e":"none"}', answers='  '),
                     '{"host":"oz-bootstrap/1","host":"oz-bootstrap/1","answers":"x","rules":{"e":"none"}}',
                     envelope('{"e":"none","e":"none"}'),
                     envelope('{"e":{"lang":"oz-rule/1","expr":["bool",true],"expr":1}}'),
                     envelope('{"e":{"lang":"oz-rule/1","expr":[01]}}'), envelope('{"e":{"x":NaN}}'),
                     envelope('{"e":{"x":Infinity}}'), envelope('{"e":{"x":[1,]}}'),
                     '{"host":"oz-bootstrap/1","answers":"x","rules":{"e":"none"},"extra":1}',
                     '{"host":"oz-bootstrap/1","answers":5,"rules":{"e":"none"}}',
                     envelope('{"e":' + '[' * 150 + ']' * 150 + '}')]:
            with self.subTest(text=str(text)[:60]), self.assertRaises(shim.Malformed):
                shim.parse_envelope(text, ['e'])
        # A non-object rule value that is the string none, written with an escape, is still none.
        _, rules = shim.parse_envelope(envelope('{"e":"\\u006eone"}'), ['e'])
        self.assertEqual(rules['e'], {'none': True})

    def test_process_returns_exact_slices_in_the_side_file(self):
        self.config()
        self.reply_file.write_text(envelope('{ "e" :  ' + self.AST + ' ,\t"b":"none" }'), encoding='utf-8')
        code, out, err = self.run_shim(self.env())
        self.assertEqual(code, 0, err)
        side = self.read_side()
        self.assertEqual(base64.b64decode(side['rules']['e']['ast_b64']), self.AST.encode('utf-8'))
        self.assertEqual(side['rules']['e']['bytes'], len(self.AST.encode('utf-8')))
        self.assertEqual(side['rules']['b'], {'none': True})


class FailedBootstrap(Base):
    def test_malformed_envelope_fails_with_the_fixed_reply_and_real_usage_and_no_answers(self):
        self.config()
        self.reply_file.write_text(envelope('{"e":"none"}') .replace('"rules"', '"rulez"'), encoding='utf-8')
        code, out, err = self.run_shim(self.env())
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {'reply': MALFORMED, 'usage': USAGE})
        self.assertNotIn('OZ/1g', MALFORMED)
        side = self.read_side()
        self.assertEqual((side['status'], side['envelope_ok'], side['answers_reply'], side['rules']),
                         ('failed', False, None, {}))
        self.assertTrue(side['reason'].startswith('envelope_malformed'))
        self.assertEqual(side['usage'], USAGE)
        captured = json.loads(base64.b64decode(side['stdout_b64']).decode('utf-8'))
        self.assertEqual(json.loads(captured['reply'])['answers'], ANSWERS)  # preserved as evidence, never used
        self.assertEqual(len(self.calls()), 1)  # no repair, no second call

    def test_oversized_and_non_unicode_asts_fail_the_whole_envelope(self):
        self.config()
        self.reply_file.write_text(envelope('{"e":{"lang":"oz-rule/1","expr":["s","' + 'x' * 2100 + '"]},"b":"none"}'),
                                   encoding='utf-8')
        code, out, err = self.run_shim(self.env())
        self.assertEqual(json.loads(out)['reply'], MALFORMED)
        self.assertEqual((self.read_side()['status'], self.read_side()['rules']), ('failed', {}))

    def test_a_reply_that_is_not_text_is_a_failed_stdout(self):
        self.config()
        cap = shim.Capture(b'{"reply": 5}', b'', 0)
        fields, out = shim._analyse(cap, ['e'])
        self.assertEqual((fields['status'], fields['reason']), ('failed', 'stdout_undecodable'))
        self.assertEqual(out, (b'{"reply": 5}', b'', 0))

    def test_efficiency_invalidation_is_documented_for_the_host(self):
        self.assertIn('invalidates efficiency', shim.__doc__.replace('\n', ' ').replace('  ', ' '))


class CallableAdapter(unittest.TestCase):
    def test_callable_shim_uses_the_same_enablement(self):
        seen = []

        def real(request):
            seen.append(request['system'])
            return {'reply': envelope('{"e":"none"}'), 'usage': USAGE}
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'p1.config.json').write_text(json.dumps(
                {'schema': shim.CONFIG_SCHEMA, 'ops': ['e'], 'contracts': {'e': {}}, 'eligibility': {'e': True}}))
            plain = shim.CallableShim(real, env={})
            self.assertEqual(plain({'receipt': '1', 'system': 'S', 'prompt': ''})['reply'], envelope('{"e":"none"}'))
            self.assertEqual(seen, ['S'])
            boot = shim.CallableShim(real, env={'OZ_BOOTSTRAP_ATTEMPT': 'p1', 'OZ_BOOTSTRAP_DIR': d})
            self.assertEqual(boot({'receipt': '2', 'system': 'S', 'prompt': ''}), {'reply': ANSWERS, 'usage': USAGE})
            self.assertIn(shim.INSTRUCTION, seen[1])
            side = json.loads(Path(d, 'p1.json').read_text())
            self.assertEqual((side['status'], side['rules']), ('ok', {'e': {'none': True}}))
            with self.assertRaises(shim.RealAdapterFailed):
                boot({'receipt': '3', 'system': 'S', 'prompt': ''})  # same attempt id: already claimed


def worked_material():
    """Hidden material read independently from the full specification: worked ASTs, conformance vector inputs."""
    text = SPEC.read_bytes().decode('utf-8').replace('\r\n', '\n')
    blocks = re.findall(r'```json\n(.*?)\n```', text, re.S)
    asts = [line for b in blocks for line in b.splitlines() if line.startswith('{"lang"') and '"expr":[' in line]
    vectors = re.search(r'```jsonl\n(.*?)\n```', text, re.S).group(1).splitlines()
    inputs = {json.loads(line)[0] for line in vectors}
    return asts, inputs


class Leakage(unittest.TestCase):
    def test_independent_material_is_found(self):
        asts, inputs = worked_material()
        self.assertEqual(len(asts), 9)  # E, B, M, V, three invalid, T, L
        self.assertGreaterEqual(len(inputs), 15)

    def test_excerpt_holds_no_worked_ast_vector_input_or_pilot_spelling(self):
        asts, inputs = worked_material()
        text = EXCERPT.read_bytes().decode('utf-8')
        for ast in asts:
            self.assertNotIn(ast, text)
            self.assertNotIn(ast[len('{"lang":"oz-rule/1","expr":'):-1], text)
        for item in inputs:
            if len(item) >= 4 and not re.fullmatch(r'[A-Za-z]', item):
                self.assertNotIn(item, text, item)
        for item in ('length=', 'uncertainty=', 'physical_validation'):
            self.assertNotIn(item, text)
        for item in ('"E"', 'admission label', 'BoolQ', 'conformance vector'):
            self.assertNotIn(item, text)
        self.assertEqual(shim.spec_excerpt(), text.replace('\r\n', '\n').rstrip('\n'))

    def test_full_system_text_holds_nothing_hidden(self):
        asts, inputs = worked_material()
        config = {'schema': shim.CONFIG_SCHEMA, 'ops': ['op_a', 'op_b'],
                  'contracts': {'op_a': {'result': 'string'}, 'op_b': {'result': 'list'}},
                  'eligibility': {'op_a': True, 'op_b': False}}
        text = shim.system_text('SYS: the unchanged OZ/1g system text', config)
        self.assertIn(shim.INSTRUCTION, text)
        self.assertIn(shim.spec_excerpt(), text)
        self.assertIn(shim.envelope_shape(['op_a', 'op_b']), text)
        for ast in asts:
            self.assertNotIn(ast, text)
        for item in inputs:
            if len(item) >= 4 and not re.fullmatch(r'[A-Za-z]', item):
                self.assertNotIn(item, text, item)
        for item in ('length=', 'uncertainty=', 'physical_validation'):
            self.assertNotIn(item, text)
        shim.check_hidden(text)

    def test_the_shim_refuses_text_that_carries_a_hidden_ast(self):
        asts, _ = worked_material()
        self.assertEqual(set(shim.HIDDEN_ASTS) <= set(asts), True)
        with self.assertRaises(ValueError):
            shim.check_hidden('x ' + shim.HIDDEN_ASTS[0])
        with self.assertRaises(ValueError):
            shim.check_hidden('record length=1 mm')
        shim.check_hidden('record length=1 mm', strings=False)

    def test_excerpt_still_states_the_amended_semantics(self):
        text = EXCERPT.read_bytes().decode('utf-8')
        for needle in ('Charge one step on node entry', '32,768', 'coefficient has at most 38 digits',
                       'reason input', 'Evaluation result representation', '"status":"abstain"', 'ROUND_HALF_EVEN',
                       'Original AST JSON bytes, including whitespace | 2,048', 'Reasons are invalid_ast',
                       'exactly one terminal CRLF'):
            self.assertIn(needle, text)
        for node in ('"s",s', '"d",s', '"bool",b', '"input"', '"field",key', '"split"', '"at"', '"num"', '"add"',
                     '"sub"', '"fmt"', '"eq"', '"le"', '"if"', '"require"', '"lookup"', '"list"', '"cat"'):
            self.assertIn('[' + node, text)


class PinnedExcerpt(unittest.TestCase):
    def test_sha256_is_pinned(self):
        raw = EXCERPT.read_bytes().replace(b'\r\n', b'\n')
        self.assertEqual(hashlib.sha256(raw).hexdigest(), shim.SPEC_EXCERPT_SHA256)
        self.assertEqual(shim.SPEC_EXCERPT_SHA256, '101d6ae09019c9d91cd267b8c700443db5af9d08dd7176bc59fc101f1816fd14')

    def test_crlf_checkout_loads_identically_and_any_edit_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            raw = EXCERPT.read_bytes().replace(b'\r\n', b'\n')
            crlf = Path(d, 'crlf.txt')
            crlf.write_bytes(raw.replace(b'\n', b'\r\n'))
            self.assertEqual(shim.spec_excerpt(crlf), shim.spec_excerpt())
            edited = Path(d, 'edited.txt')
            edited.write_bytes(raw + b' ')
            with self.assertRaisesRegex(ValueError, 'changed'):
                shim.spec_excerpt(edited)
            with self.assertRaisesRegex(ValueError, 'cannot read'):
                shim.spec_excerpt(Path(d, 'missing.txt'))

    def test_edited_excerpt_stops_the_bootstrap_before_any_launch(self):
        with tempfile.TemporaryDirectory() as d:
            real = Path(d, 'real.py')
            real.write_text("raise SystemExit('must not run')", encoding='utf-8')
            shim_copy = Path(d, 'bootstrap_shim.py')
            shim_copy.write_bytes(SHIM.read_bytes())
            side = Path(d, 'side')
            side.mkdir()
            side.joinpath('a.config.json').write_text(json.dumps(
                {'schema': shim.CONFIG_SCHEMA, 'ops': ['e'], 'contracts': {'e': {}}, 'eligibility': {'e': True}}))
            # SPEC_EXCERPT_PATH of the copy points at <d>/../docs/...: absent, so the pinned load fails.
            done = subprocess.run([sys.executable, str(shim_copy), str(real)], input=b'{"receipt":"1","system":"S"}',
                                  capture_output=True, env=clean_env(OZ_BOOTSTRAP_ATTEMPT='a', OZ_BOOTSTRAP_DIR=str(side)))
            self.assertEqual(done.returncode, shim.EXIT_REFUSED)
            record = json.loads(side.joinpath('a.json').read_text())
            self.assertEqual((record['status'], record['launched']), ('failed', False))


class RouteClosure(unittest.TestCase):
    def test_shipped_bootstrap_adapters_cover_shim_adapter_imports_and_the_excerpt(self):
        for name, real, extra in (('bootstrap_claude_adapter.json', 'claude_map_adapter.py', 'claude_cli_adapter.py'),
                                  ('bootstrap_codex_adapter.json', 'codex_cli_adapter.py', None)):
            path = ROOT / 'examples' / name
            manifest = dict(source_manifest(path))
            self.assertIn('bootstrap_shim.py', manifest, name)
            self.assertIn(real, manifest, name)
            self.assertIn('../docs/design/ozmap-2026-10-24/bootstrap-spec-excerpt.txt', manifest, name)
            if extra:
                self.assertIn(extra, manifest, name)
            # The shim's own identity closure is the same set with the same hashes.
            own = shim.closure([SHIM, ROOT / 'examples' / real], ROOT / 'examples')
            self.assertEqual(own, source_manifest(path), name)

    def test_adapter_hash_changes_with_the_excerpt_the_shim_and_the_real_adapter(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'ex').mkdir()
            (d / 'docs').mkdir()
            (d / 'ex' / 'shim.py').write_text("OZ_ROUTE_DATA = ('../docs/spec.txt',)\nimport helper\n")
            (d / 'ex' / 'helper.py').write_text('x = 1\n')
            (d / 'ex' / 'real.py').write_text('y = 1\n')
            (d / 'docs' / 'spec.txt').write_text('spec v1\n')
            adapter = d / 'ex' / 'a.json'
            adapter.write_text(json.dumps({'argv': ['python', 'shim.py', 'real.py'], 'protocols': ['oz.adapter/3'],
                                           'languages': ['OZ/9']}))
            first = adapter_hash(adapter)
            self.assertEqual([n for n, _ in source_manifest(adapter)],
                             ['../docs/spec.txt', 'helper.py', 'real.py', 'shim.py'])
            seen = {first}
            for path, text in (('docs/spec.txt', 'spec v2\n'), ('ex/helper.py', 'x = 2\n'), ('ex/real.py', 'y = 2\n'),
                               ('ex/shim.py', "OZ_ROUTE_DATA = ('../docs/spec.txt',)\nimport helper\n# e\n")):
                (d / path).write_text(text)
                seen.add(adapter_hash(adapter))
            self.assertEqual(len(seen), 5)
            (d / 'docs' / 'spec.txt').unlink()
            with self.assertRaisesRegex(Error, 'does not exist'):
                adapter_hash(adapter)

    def test_adapter_hash_does_not_depend_on_the_checkout_location(self):
        hashes = set()
        for _ in range(2):
            with tempfile.TemporaryDirectory() as d:
                d = Path(d)
                (d / 'ex').mkdir()
                (d / 'docs').mkdir()
                (d / 'ex' / 'shim.py').write_text("OZ_ROUTE_DATA = ('../docs/spec.txt',)\n")
                (d / 'docs' / 'spec.txt').write_text('spec\n')
                (d / 'ex' / 'a.json').write_text(json.dumps({'argv': ['python', 'shim.py']}))
                hashes.add(adapter_hash(d / 'ex' / 'a.json'))
        self.assertEqual(len(hashes), 1)

    def test_malformed_route_data_declaration_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / 'shim.py').write_text("OZ_ROUTE_DATA = [x for x in range(3)]\n")
            (d / 'a.json').write_text(json.dumps({'argv': ['python', 'shim.py']}))
            with self.assertRaises(Error):
                adapter_hash(d / 'a.json')


if __name__ == '__main__':
    unittest.main()
