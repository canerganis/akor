import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from oz import Error
from oz_batch import SYSTEM
from oz_cli import main
from oz_workspace import DEMO_SCRIPT, DEMO_CAPABILITIES, Workspace, channel_from_files, demo, initialize
from test_oz2 import extended


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'space'

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_init_does_not_overwrite_existing_user_files(self):
        self.root.mkdir()
        path = self.root / 'mine.txt'
        path.write_text('keep me', encoding='utf8')
        with self.assertRaises(Error):
            initialize(self.root)
        self.assertEqual(path.read_text(), 'keep me')
        self.assertFalse((self.root / 'oz.json').exists())

    def test_init_and_load_are_dependency_free(self):
        workspace = initialize(self.root)
        self.assertEqual(set(workspace.channels), {'worker', 'reviewer'})
        self.assertEqual(Workspace(self.root).channel().binding, workspace.channel().binding)
        with workspace.inbox() as box:
            self.assertEqual(box.stats(), {})

    def test_missing_queue_is_not_silently_recreated(self):
        workspace = initialize(self.root)
        (self.root / 'inbox.sqlite').unlink()
        with self.assertRaises(Error):
            workspace.inbox()
        self.assertFalse((self.root / 'inbox.sqlite').exists())

    def test_send_duplicate_preview_and_status_preserve_payload(self):
        initialize(self.root)
        base = ('--workspace', str(self.root))
        for expected in [True, False]:
            code, out, err = self.cli('send', 'P', '--id', 'first', *base)
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)['inserted'], expected)
        with patch('oz_workspace.token_counters', return_value=(len,)):
            code, out, err = self.cli('plan', '--show-prompt', '--max-tokens', '10000', *base)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['attempts_consumed'], 0)
        prompt = json.loads(out)['prompt']
        self.assertIn('DEMO: ask for the measurement method', prompt)
        plan = json.loads(out)
        self.assertEqual(plan['ids'], ['first'])
        self.assertFalse(prompt.endswith('\n'))
        body = json.loads(prompt)
        self.assertEqual(body['j'], ['propose 0'])
        self.assertNotIn('first', prompt)
        # The receipt is host-side only: no q field in the body, and the plan still works.
        self.assertNotIn('q', body)
        self.assertEqual(plan['system'], SYSTEM)
        self.assertEqual(plan['mode'], 'named')
        code, out, err = self.cli('status', '--json', *base)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['jobs'][0]['attempts'], 0)

    def test_file_literal_preserves_unicode_and_newlines(self):
        workspace = initialize(self.root)
        path = Path(self.temp.name) / 'source.txt'
        text = 'Türkçe ± 0.02 mm\r\nV is data; 𓂀'
        path.write_bytes(text.encode('utf8'))
        code, out, err = self.cli('send', '--file', str(path), '--id', 'literal', '--workspace', str(self.root))
        self.assertEqual(code, 0, err)
        with workspace.inbox() as box:
            self.assertEqual(box.inspect('literal')['wire'], ':' + text)

    def test_real_source_cli_creates_channel_without_handwritten_manifest(self):
        source = Path(self.temp.name) / 'source.txt'
        procedure = Path(self.temp.name) / 'checks.txt'
        text = '12.50 ± 0.02 mm\r\nMethod unknown.'
        source.write_bytes(text.encode('utf8'))
        procedure.write_text('Check units and retain uncertainty.', encoding='utf8')
        code, out, err = self.cli('init', str(self.root), '--goal', 'Read and check measurement.',
                                  '--source', str(source), '--procedure', str(procedure))
        self.assertEqual(code, 0, err)
        ch = Workspace(self.root).channel()
        self.assertEqual([a.code for a in ch.accept('V', binding=ch.binding)], ['r', 't'])
        self.assertEqual(ch.snapshot()['references'][0]['text'], text)
        self.assertIn('@sha256:', ch.snapshot()['references'][0]['source'])
        source.write_text('later edit', encoding='utf8')
        self.assertEqual(ch.snapshot()['references'][0]['text'], text)

    def test_patch_profile_and_invalid_init_options(self):
        source = Path(self.temp.name) / 'patch.diff'
        source.write_text('SYNTHETIC diff', encoding='utf8')
        ch = channel_from_files('Review only', source, kind='patch')
        self.assertEqual([a.code for a in ch.accept('V', binding=ch.binding)], ['r', 'a'])
        code, out, err = self.cli('init', str(self.root), '--goal', 'missing source')
        self.assertEqual(code, 2)
        self.assertFalse(self.root.exists())

    def test_new_channel_does_not_change_existing_bindings(self):
        workspace = initialize(self.root)
        original = workspace.channel().binding
        workspace.add_channel('science', extended())
        reloaded = Workspace(self.root)
        self.assertEqual(reloaded.channel().binding, original)
        self.assertEqual(reloaded.channel('science').binding, extended().binding)
        with self.assertRaises(Error):
            reloaded.add_channel('worker', extended())

    def test_stale_config_edit_is_rejected(self):
        workspace = initialize(self.root)
        path = self.root / 'oz.json'
        value = json.loads(path.read_text(encoding='utf8'))
        value['max_tokens'] = 5000
        path.write_text(json.dumps(value), encoding='utf8')
        with self.assertRaises(Error):
            workspace.add_channel('new', extended())
        self.assertEqual(json.loads(path.read_text())['max_tokens'], 5000)

    def test_concurrent_channel_additions_do_not_overwrite_each_other(self):
        initialize(self.root)
        first, second = Workspace(self.root), Workspace(self.root)
        def add(pair):
            workspace, name = pair
            try:
                workspace.add_channel(name, extended())
                return True
            except Error:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(add, [(first, 'a'), (second, 'b')]))
        self.assertEqual(sum(results), 1)
        self.assertEqual(len(Workspace(self.root).channels), 3)

    def test_cli_run_explicit_adapter_and_independent_restart(self):
        workspace = initialize(self.root)
        adapter = self.root / 'adapter.json'
        adapter.write_text(json.dumps({'argv': [sys.executable, '-c', DEMO_SCRIPT],
                                       **DEMO_CAPABILITIES}), encoding='utf8')
        base = ('--workspace', str(self.root))
        self.assertEqual(self.cli('send', 'P', '--id', 'first', *base)[0], 0)
        with patch('oz_workspace.token_counters', return_value=(len,)):
            code, out, err = self.cli('run', '--adapter', str(adapter), '--max-tokens', '10000', *base)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['runs'][0]['status'], 'received')
        with Workspace(self.root).inbox() as box:
            self.assertEqual(box.inspect('first')['state'], 'done')
            result = json.loads(box.inspect('first')['result'])
            self.assertEqual(len(result['results']), 2)
            # read is a host operation (an empty acknowledgement); only propose reached the model.
            self.assertEqual(result['results'][0], '')
            self.assertIn('DEMO', result['results'][1])
        ledger = [json.loads(line) for line in (self.root / 'calls.jsonl').read_text(encoding='utf8').splitlines()]
        self.assertEqual([x['event'] for x in ledger], ['call_start', 'call_end'])
        self.assertEqual(ledger[1]['outcome'], 'ok')
        self.assertEqual(ledger[1]['token_estimates']['tokenizer'], 'o200k_base')
        self.assertEqual(ledger[1]['validation']['expected_results'], 1)

    def test_cli_send_defaults_to_two_attempts(self):
        initialize(self.root)
        base = ('--workspace', str(self.root))
        self.cli('send', 'P', '--id', 'first', *base)
        code, out, err = self.cli('inspect', 'first', *base)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['job']['max_attempts'], 2)

    def test_run_continues_past_host_completed_batches_without_spending_max_calls(self):
        initialize(self.root)
        adapter = self.root / 'adapter.json'
        adapter.write_text(json.dumps({'argv': [sys.executable, '-c', 'raise SystemExit(9)'],
                                       **DEMO_CAPABILITIES}), encoding='utf8')
        base = ('--workspace', str(self.root))
        self.cli('send', 'r1', '--id', 'a', *base)
        self.cli('send', 'r1', '--id', 'b', '--after', 'a', *base)
        self.cli('send', 'r1', '--id', 'c', '--after', 'b', *base)
        with patch('oz_workspace.token_counters', return_value=(len,)):
            code, out, err = self.cli('run', '--adapter', str(adapter), '--max-tokens', '10000', *base)
        self.assertEqual(code, 0, err)
        runs = json.loads(out)['runs']
        self.assertEqual([r['status'] for r in runs], ['host_completed'] * 3 + ['idle'])
        self.assertEqual({r.get('adapter_calls', 0) for r in runs}, {0})
        self.assertFalse((self.root / 'calls.jsonl').exists())
        with Workspace(self.root).inbox() as box:
            self.assertEqual(box.stats(), {'done': 3})

    def test_cli_run_min_batch_waits_without_attempts(self):
        initialize(self.root)
        adapter = self.root / 'adapter.json'
        adapter.write_text(json.dumps({'argv': [sys.executable, '-c', DEMO_SCRIPT],
                                       **DEMO_CAPABILITIES}), encoding='utf8')
        base = ('--workspace', str(self.root))
        self.assertEqual(self.cli('send', 'P', '--id', 'first', *base)[0], 0)
        with patch('oz_workspace.token_counters', return_value=(len,)):
            code, out, err = self.cli('run', '--adapter', str(adapter), '--max-tokens', '10000',
                                      '--min-batch', '2', '--max-wait', '60', *base)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['runs'][0]['status'], 'waiting')
        with Workspace(self.root).inbox() as box:
            self.assertEqual(box.inspect('first')['attempts'], 0)
            self.assertEqual(box.inspect('first')['state'], 'pending')

    def test_cli_failure_returns_nonzero_and_explains_safe_error_code(self):
        initialize(self.root)
        adapter = self.root / 'adapter.json'
        adapter.write_text(json.dumps({'argv': [sys.executable, '-c', 'print("not-json")'],
                                       **DEMO_CAPABILITIES}), encoding='utf8')
        base = ('--workspace', str(self.root))
        self.cli('send', 'P', '--id', 'first', '--max-attempts', '1', *base)
        with patch('oz_workspace.token_counters', return_value=(len,)):
            code, out, err = self.cli('run', '--adapter', str(adapter), '--max-tokens', '10000', *base)
        self.assertEqual(code, 3, err)
        self.assertEqual(json.loads(out)['runs'][0]['error_code'], 'adapter_invalid_json')
        self.assertEqual(self.cli('retry', 'first', *base)[0], 0)
        code, out, err = self.cli('inspect', 'first', *base)
        self.assertEqual(json.loads(out)['job']['state'], 'pending')
        self.assertIn('requeued', [e['event'] for e in json.loads(out)['history']])

    def test_legacy_or_partial_adapter_config_fails_before_claim(self):
        initialize(self.root)
        adapter = self.root / 'adapter.json'
        base = ('--workspace', str(self.root))
        self.cli('send', 'P', '--id', 'first', *base)
        argv = [sys.executable]
        for spec in [{'argv': [sys.executable, '-c', DEMO_SCRIPT]},
                     dict(DEMO_CAPABILITIES, argv=argv, reply_modes=['lanes']),
                     {'argv': argv, 'protocols': ['oz.adapter/3']},
                     {'argv': argv, 'protocols': ['oz.adapter/3'], 'languages': ['OZ/8']},
                     {'argv': argv, 'protocols': ['oz.adapter/2'], 'languages': ['OZ/9']}]:
            with self.subTest(spec=spec):
                adapter.write_text(json.dumps(spec), encoding='utf8')
                with patch('oz_workspace.token_counters', return_value=(len,)):
                    code, out, err = self.cli('run', '--adapter', str(adapter), *base)
                self.assertEqual(code, 2, err)
        code, out, err = self.cli('inspect', 'first', *base)
        self.assertEqual(json.loads(out)['job']['attempts'], 0)

    def test_demo_capabilities_are_adapter3_and_oz9(self):
        self.assertEqual(DEMO_CAPABILITIES, {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']})

    def test_removed_cli_options_and_commands_are_rejected(self):
        initialize(self.root)
        base = ('--workspace', str(self.root))
        for args in [('run', '--adapter', 'a.json', '--reply-mode', 'lanes'), ('plan', '--reply-mode', 'lanes'),
                     ('plan', '--dictionary', 'on'), ('plan', '--min-savings', '5'),
                     ('run', '--adapter', 'a.json', '--dictionary', 'on'),
                     ('pack', '--channel', 'c.json', '--messages', 'm.json', '--dictionary', 'on'),
                     ('pack', '--channel', 'c.json', '--messages', 'm.json', '--min-savings', '5'),
                     ('pack', '--channel', 'c.json', '--messages', 'm.json', '--reply-mode', 'lanes'),
                     ('compile', 'x')]:
            with self.subTest(args=args), self.assertRaises(SystemExit) as caught:
                self.cli(*args, *(base if args[0] in {'plan', 'run'} else ()))
            self.assertEqual(caught.exception.code, 2)

    def test_plan_without_show_prompt_hides_system_and_prompt(self):
        initialize(self.root)
        base = ('--workspace', str(self.root))
        self.cli('send', 'r1', '--id', 'first', *base)
        with patch('oz_workspace.token_counters', return_value=(len,)):
            code, out, err = self.cli('plan', *base)
        self.assertEqual(code, 0, err)
        self.assertNotIn('prompt', json.loads(out))
        self.assertNotIn('system', json.loads(out))

    def test_pack_prints_system_prompt_and_job_map(self):
        initialize(self.root)
        channel = Workspace(self.root).channel()
        manifest = Path(self.temp.name) / 'channel.json'
        manifest.write_text(json.dumps(channel.snapshot()), encoding='utf8')
        messages = Path(self.temp.name) / 'messages.json'
        messages.write_text(json.dumps([['one', 'P'], ['two', ':note']]), encoding='utf8')
        fake = type('Tiktoken', (), {'get_encoding': staticmethod(lambda name: type('E', (), {
            'encode': staticmethod(lambda text, disallowed_special=(): list(text))})())})
        with patch.dict(sys.modules, {'tiktoken': fake}):
            code, out, err = self.cli('pack', '--channel', str(manifest), '--messages', str(messages))
        self.assertEqual(code, 0, err)
        value = json.loads(out)
        self.assertEqual((value['mode'], value['system']), ('named', SYSTEM))
        self.assertEqual(json.loads(value['prompt'])['j'], ['propose 0', 'literal_two'])
        self.assertEqual(value['job_map'], [['one', 1], ['two', 0]])
        self.assertNotIn('alternatives', value)

    def test_context_option_selects_needed_or_full_in_plan(self):
        initialize(self.root)
        base = ('--workspace', str(self.root))
        self.cli('send', '>2', '--id', 'first', *base)
        prompts = {}
        for policy in ['needed', 'full']:
            with patch('oz_workspace.token_counters', return_value=(len,)):
                code, out, err = self.cli('plan', '--show-prompt', '--context', policy, *base)
            self.assertEqual(code, 0, err)
            prompts[policy] = json.loads(out)['prompt']
        self.assertNotIn('DEMO: 12.50', prompts['needed'])
        self.assertIn('DEMO: 12.50', prompts['full'])
        with self.assertRaises(SystemExit):
            self.cli('plan', '--context', 'everything', *base)

    def test_host_events_cli_is_model_free(self):
        initialize(self.root)
        base = ('--workspace', str(self.root))
        self.cli('send', '!3', '--id', 'blocked', *base)
        code, out, err = self.cli('events', *base)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['model_calls'], 0)

    def test_demo_is_real_stdio_but_not_model_or_task_validation(self):
        with patch('oz_workspace.token_counters', return_value=(lambda s: len(s) // 4,)):
            result = demo(self.root)
        self.assertEqual(result['actual_model_calls'], 0)
        self.assertTrue(result['reviewer_initially_waited'])
        self.assertEqual(result['states'], {'done': 4})
        self.assertEqual(result['worker']['adapter_calls'], 1)
        self.assertEqual(result['worker']['outcomes'], {'read': 'ok', 'propose': 'ok'})
        self.assertEqual(result['reviewer']['outcomes'], {'review': 'ok'})
        # The reviewer's only job is a host read: completed locally, no adapter call, no ledger record.
        self.assertEqual((result['reviewer']['status'], result['reviewer']['adapter_calls']), ('host_completed', 0))
        with Workspace(self.root).inbox() as box:
            self.assertEqual(len(json.loads(box.inspect('propose')['result'])['results']), 2)
        ledger = (self.root / 'calls.jsonl').read_text(encoding='utf8').splitlines()
        self.assertEqual(len(ledger), 2)

    def test_bad_config_duplicate_keys_and_unknown_channel_fail_cleanly(self):
        initialize(self.root)
        code, out, err = self.cli('send', 'P', '--to', 'missing', '--workspace', str(self.root))
        self.assertEqual(code, 2)
        self.assertNotIn('Traceback', err)
        (self.root / 'oz.json').write_text('{"version":1,"version":2}', encoding='utf8')
        with self.assertRaises(Error):
            Workspace(self.root)


if __name__ == '__main__':
    unittest.main()
