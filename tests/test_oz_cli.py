import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from examples.oz2_demo import example_channel
from oz_cli import main, read_json
from oz import Error
from oz_live_eval import encode_prompt, expected_decoding, fixtures, setup_context


ROOT = Path(__file__).parents[1]


class CLITests(unittest.TestCase):
    def test_portable_manifest_and_cli_decode(self):
        proc = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'oz_cli', 'decode',
                               '--channel', 'examples/oz2-channel.json', 'V'], cwd=ROOT,
                              capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual([a['code'] for a in data['atoms']], ['r', 'a', 't'])
        self.assertEqual(data['binding'], example_channel().binding)

    def test_cli_rejects_invalid_frame_without_traceback(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main(['decode', '--channel', str(ROOT / 'examples/oz2-channel.json'), 'V0'])
        self.assertEqual(code, 2)
        self.assertIn('oz:', err.getvalue())
        self.assertNotIn('Traceback', err.getvalue())

    def test_duplicate_manifest_keys_are_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'manifest.json'
            path.write_text('{"active":7,"active":8}', encoding='utf-8')
            with self.assertRaises(Error):
                read_json(path)

    def test_live_suites_are_offline_validated_before_provider_use(self):
        for suite, size in [('oz1', 12), ('oz2', 20)]:
            ch, context = setup_context(suite)
            self.assertEqual(len(fixtures(suite)), size)
            for _, wire in fixtures(suite):
                atoms = ch.accept(wire, binding=ch.binding)
                self.assertTrue(expected_decoding(atoms))
            self.assertIn(f'exactly {size} strings', encode_prompt(suite))
            self.assertIn('12.50 ± 0.02 mm', context)


if __name__ == '__main__':
    unittest.main()
