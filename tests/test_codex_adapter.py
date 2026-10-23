import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

from oz_reply import validate_usage
from oz_worker import AdapterError, StdioAdapter

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / 'examples' / 'codex_cli_adapter.py'
spec = importlib.util.spec_from_file_location('codex_cli_adapter', ADAPTER)
CCA = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CCA)

# The fake `codex`: records its argv and stdin to FAKE_CODEX_LOG, replays FAKE_CODEX_EVENTS, exits FAKE_CODEX_EXIT.
FAKE = '''import json, os, sys, time
if sys.argv[1:] == ['--version']:
    print('codex-cli 9.9.9')
    sys.exit(0)
with open(os.environ['FAKE_CODEX_LOG'], 'w', encoding='utf-8') as log:
    log.write(json.dumps({'argv': sys.argv[1:], 'stdin': sys.stdin.read()}))
with open(os.environ['FAKE_CODEX_EVENTS'], encoding='utf-8') as events:
    sys.stdout.write(events.read())
sys.stderr.write('boom')
sys.stdout.flush()
time.sleep(float(os.environ.get('FAKE_CODEX_SLEEP', '0')))
sys.exit(int(os.environ.get('FAKE_CODEX_EXIT', '0')))
'''


def event(kind, **fields):
    return json.dumps({'type': kind, **fields})


def message(text):
    return event('item.completed', item={'id': 'item_0', 'type': 'agent_message', 'text': text})


def completed(**usage):
    return event('turn.completed', usage=usage)


USAGE = {'input_tokens': 28652, 'cached_input_tokens': 7296, 'cache_write_input_tokens': 0, 'output_tokens': 1294,
         'reasoning_output_tokens': 175}
HEAD = [event('thread.started', thread_id='t'), event('turn.started')]


class ReduceTests(unittest.TestCase):
    def test_normal_reply_maps_usage(self):
        out = CCA.reduce('\n'.join([*HEAD, message('OZ/1g'), completed(**USAGE)]))
        self.assertEqual(out['reply'], 'OZ/1g')
        self.assertEqual(out['usage'], {'input_tokens': 28652, 'cached_input_tokens': 7296, 'output_tokens': 1294,
                                        'cache_creation_input_tokens': 0, 'reasoning_output_tokens': 175})
        validate_usage(out['usage'])

    def test_cached_is_a_subset_of_input_and_counted_once(self):
        usage = CCA.reduce('\n'.join([message('x'), completed(**USAGE)]))['usage']
        self.assertEqual(usage['input_tokens'], USAGE['input_tokens'])
        self.assertLessEqual(usage['cached_input_tokens'], usage['input_tokens'])
        self.assertLessEqual(usage['reasoning_output_tokens'], usage['output_tokens'])

    def test_last_agent_message_wins(self):
        out = CCA.reduce('\n'.join([message('draft'), message('final'), completed(**USAGE)]))
        self.assertEqual(out['reply'], 'final')

    def test_missing_turn_completed_means_unknown_usage(self):
        self.assertEqual(CCA.reduce('\n'.join([*HEAD, message('x')])), {'reply': 'x'})

    def test_incomplete_or_bad_counter_means_unknown_usage(self):
        for usage in ({'input_tokens': 5, 'output_tokens': 1}, {**USAGE, 'input_tokens': -1},
                      {**USAGE, 'output_tokens': '3'}, {**USAGE, 'reasoning_output_tokens': True}):
            self.assertNotIn('usage', CCA.reduce('\n'.join([message('x'), completed(**usage)])))

    def test_failed_turn_and_missing_message_raise(self):
        with self.assertRaises(RuntimeError):
            CCA.reduce('\n'.join([*HEAD, event('turn.failed', error={'message': 'rate limit'})]))
        with self.assertRaises(RuntimeError):
            CCA.reduce('\n'.join([*HEAD, completed(**USAGE)]))

    def test_recoverable_error_events_do_not_override_a_completed_turn(self):
        lines = [*HEAD, event('error', message='Reconnecting... 1/5'), message('OZ/1g'),
                 event('error', message='stream hiccup'), completed(**USAGE)]
        out = CCA.reduce('\n'.join(lines))
        self.assertEqual(out['reply'], 'OZ/1g')
        self.assertEqual(out['usage']['input_tokens'], 28652)
        self.assertEqual(CCA.parse_events('\n'.join(lines))[2], None)

    def test_a_terminal_failure_after_a_message_still_fails(self):
        lines = [*HEAD, message('draft'), event('turn.failed', error={'message': 'quota'})]
        with self.assertRaisesRegex(RuntimeError, 'quota'):
            CCA.reduce('\n'.join(lines))

    def test_error_events_without_a_message_fail_and_are_quoted_for_the_diagnostic(self):
        with self.assertRaisesRegex(RuntimeError, 'no agent message.*boom event'):
            CCA.reduce('\n'.join([*HEAD, event('error', message='boom event'), completed(**USAGE)]))
        with self.assertRaisesRegex(RuntimeError, 'no agent message'):
            CCA.reduce('\n'.join([*HEAD, event('error', message='x')]))
        self.assertIsNone(CCA.last_error('\n'.join([*HEAD, message('x')])))

    def test_non_event_lines_are_ignored(self):
        out = CCA.reduce('\n'.join(['Reading prompt from stdin...', '{broken', message('x'), completed(**USAGE)]))
        self.assertEqual(out['reply'], 'x')


class FakeCodexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        script = self.dir / 'fake_codex.py'
        script.write_text(FAKE, encoding='utf-8')
        if os.name == 'nt':
            (self.dir / 'codex.cmd').write_text(f'@"{sys.executable}" "{script}" %*\n', encoding='utf-8')
        else:
            exe = self.dir / 'codex'
            exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding='utf-8')
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        self.log = self.dir / 'log.json'
        self.old = dict(os.environ)
        self.addCleanup(self.restore)
        os.environ.update(PATH=str(self.dir) + os.pathsep + os.environ['PATH'], FAKE_CODEX_LOG=str(self.log))
        os.environ.pop('OZ_MODEL', None)
        os.environ.pop('OZ_EFFORT', None)

    def restore(self):
        os.environ.clear()
        os.environ.update(self.old)

    def call(self, lines, code=0, **env):
        events = self.dir / 'events.jsonl'
        events.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        os.environ.update(FAKE_CODEX_EVENTS=str(events), FAKE_CODEX_EXIT=str(code), **env)
        return StdioAdapter((sys.executable, str(ADAPTER)), timeout=60)({'system': 'SYS', 'prompt': 'PROMPT'})

    def test_normal_reply_and_command_line(self):
        out = self.call([*HEAD, message('OZ/1g'), completed(**USAGE)], OZ_MODEL='m1', OZ_EFFORT='high')
        self.assertEqual(out['reply'], 'OZ/1g')
        self.assertEqual(out['usage']['cached_input_tokens'], 7296)
        sent = json.loads(self.log.read_text(encoding='utf-8'))
        self.assertEqual(sent['argv'], ['exec', '-m', 'm1', '-c', 'model_reasoning_effort="high"', '-s', 'read-only',
                                        '--skip-git-repo-check', '--ephemeral', '--json', '-'])
        self.assertTrue(sent['stdin'].startswith('SYS'))
        self.assertTrue(sent['stdin'].endswith('PROMPT'))

    def test_reasoning_tokens_reach_the_worker_response(self):
        out = self.call([message('x'), completed(**USAGE)])
        self.assertEqual(out['usage']['reasoning_output_tokens'], 175)

    def test_missing_turn_completed_has_no_usage(self):
        self.assertEqual(self.call([*HEAD, message('x')]), {'reply': 'x'})

    def test_nonzero_exit_is_an_adapter_exit(self):
        with self.assertRaises(AdapterError) as cm:
            self.call([message('x'), completed(**USAGE)], code=3)
        self.assertEqual(cm.exception.code, 'adapter_exit_3')

    def capture(self, lines, code=0, **env):
        path = self.dir / 'envelope.json'
        path.unlink(missing_ok=True)
        os.environ['OZ_ENVELOPE_PATH'] = str(path)
        try:
            self.call(lines, code, **env)
        except AdapterError:
            pass
        return json.loads(path.read_text(encoding='utf-8'))

    def test_capture_keeps_raw_stdout_stderr_exit_model_effort_and_version(self):
        lines = [*HEAD, message('OZ/1g'), completed(**USAGE)]
        record = self.capture(lines, OZ_MODEL='m1', OZ_EFFORT='high')
        self.assertEqual(record['stdout'], chr(10).join(lines) + chr(10))
        self.assertEqual((record['stderr'], record['exit_code'], record['timed_out']), ('boom', 0, False))
        self.assertEqual((record['model'], record['effort'], record['codex_version']),
                         ('m1', 'high', 'codex-cli 9.9.9'))
        self.assertEqual(record['usage']['input_tokens'], 28652)
        # The version probe must not replace the record of the exec call.
        self.assertEqual(json.loads(self.log.read_text(encoding='utf-8'))['argv'][0], 'exec')

    def test_capture_defaults_record_the_effective_model_and_effort(self):
        record = self.capture([message('x')])
        self.assertEqual((record['model'], record['effort']), ('gpt-6-luna', 'medium'))

    def test_nonzero_exit_keeps_capture_and_usage_but_is_not_accepted(self):
        lines = [message('x'), completed(**USAGE)]
        os.environ['OZ_ENVELOPE_PATH'] = str(self.dir / 'envelope.json')
        with self.assertRaises(AdapterError) as cm:
            self.call(lines, code=3)
        self.assertEqual(cm.exception.code, 'adapter_exit_3')
        record = json.loads((self.dir / 'envelope.json').read_text(encoding='utf-8'))
        self.assertEqual((record['exit_code'], record['usage']['output_tokens']), (3, 1294))
        done = subprocess.run([sys.executable, str(ADAPTER)], input=json.dumps({'system': 'S', 'prompt': 'P'}),
                              capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(done.returncode, 3)
        self.assertEqual(done.stdout, '')
        self.assertIn('oz-usage-not-accepted', done.stderr)

    def test_timeout_is_captured_with_the_flag_and_exits_124(self):
        os.environ['OZ_ENVELOPE_PATH'] = str(self.dir / 'envelope.json')
        with self.assertRaises(AdapterError) as cm:
            self.call([message('x')], OZ_CODEX_TIMEOUT='1', FAKE_CODEX_SLEEP='20')
        self.assertEqual(cm.exception.code, 'adapter_exit_124')
        record = json.loads((self.dir / 'envelope.json').read_text(encoding='utf-8'))
        self.assertEqual((record['timed_out'], record['exit_code']), (True, None))
        self.assertEqual(record['codex_version'], 'codex-cli 9.9.9')

    def test_no_capture_file_without_the_runner_path(self):
        os.environ.pop('OZ_ENVELOPE_PATH', None)
        self.call([message('x')])
        self.assertFalse((self.dir / 'envelope.json').exists())

    def test_error_event_then_success_is_accepted_with_usage(self):
        out = self.call([*HEAD, event('error', message='Reconnecting... 2/5'), message('OZ/1g'), completed(**USAGE)])
        self.assertEqual(out['reply'], 'OZ/1g')
        self.assertEqual(out['usage']['output_tokens'], 1294)

    def test_error_event_without_a_completed_message_is_an_adapter_exit(self):
        with self.assertRaises(AdapterError) as cm:
            self.call([*HEAD, event('error', message='fatal thing'), completed(**USAGE)])
        self.assertEqual(cm.exception.code, 'adapter_exit_1')

    def run_adapter(self, *args, path=None, **env):
        full = dict(os.environ, **env)
        if path is not None:
            full['PATH'] = path
        return subprocess.run([sys.executable, str(ADAPTER), *args], input=json.dumps({'system': 'S', 'prompt': 'P'}),
                              capture_output=True, text=True, encoding='utf-8', timeout=60, env=full)

    def test_a_missing_codex_executable_exits_127_with_a_diagnostic_and_a_capture(self):
        empty = self.dir / 'nothing'
        empty.mkdir()
        done = self.run_adapter(path=str(empty), OZ_ENVELOPE_PATH=str(self.dir / 'envelope.json'))
        self.assertEqual(done.returncode, 127)
        self.assertIn('codex executable not found on PATH', done.stderr)
        record = json.loads((self.dir / 'envelope.json').read_text(encoding='utf-8'))
        self.assertEqual((record['exit_code'], record['timed_out'], record['backend']), (127, False, 'codex'))
        self.assertIn('codex executable not found', record['stderr'])
        events = self.dir / 'events.jsonl'
        events.write_text('', encoding='utf-8')
        with self.assertRaises(AdapterError) as cm:
            old = os.environ['PATH']
            os.environ['PATH'] = str(empty)
            try:
                StdioAdapter((sys.executable, str(ADAPTER)), timeout=60)({'system': 'S', 'prompt': 'P'})
            finally:
                os.environ['PATH'] = old
        self.assertEqual(cm.exception.code, 'adapter_exit_127')

    def test_identity_reports_effective_model_effort_version_and_flags_without_a_model_call(self):
        done = self.run_adapter('--identity', OZ_MODEL='m9', OZ_EFFORT='xhigh')
        self.assertEqual(done.returncode, 0, done.stderr)
        report = json.loads(done.stdout)
        self.assertEqual((report['backend'], report['model'], report['effort'], report['cli_version']),
                         ('codex', 'm9', 'xhigh', 'codex-cli 9.9.9'))
        self.assertIn('--ephemeral', report['flags'])
        self.assertFalse(self.log.exists(), 'identity must not call codex exec')

    def test_failed_turn_is_an_adapter_exit(self):
        with self.assertRaises(AdapterError) as cm:
            self.call([*HEAD, event('error', message='bad'), event('turn.failed', error={'message': 'bad'})])
        self.assertEqual(cm.exception.code, 'adapter_exit_1')


if __name__ == '__main__':
    unittest.main()
