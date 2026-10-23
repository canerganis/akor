"""oz_route: route identity and worker_hash (amendment D7), with fake adapters and fake CLIs (no model call)."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oz import Error
from oz_route import (NOT_APPLICABLE, ROUTE_FIELDS, adapter_hash, build, canonical, environment_hash, probe,
                      reconcile, source_manifest, worker_hash)

ROOT = Path(__file__).resolve().parents[1]
CAPS = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}
ROUTE = {'adapter_hash': 'a' * 64, 'backend': 'codex', 'model': 'm', 'effort': 'high', 'cli_version': '1.0',
         'environment_hash': 'e' * 64}


def report(**kw):
    return dict({'backend': 'fake', 'model': 'm', 'effort': 'high', 'effort_applicable': True, 'cli_version': '1.0',
                 'flags': ['--x']}, **kw)


class Dir(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)

    def adapter(self, argv=None, files=None, **extra):
        for name, text in (files or {'a.py': 'print(1)\n'}).items():
            (self.dir / name).write_text(text, encoding='utf-8')
        path = self.dir / 'adapter.json'
        path.write_text(json.dumps({'argv': argv or [sys.executable, 'a.py'], **CAPS, **extra}), encoding='utf-8')
        return path


class CanonicalTests(unittest.TestCase):
    def test_canonical_is_sorted_compact_unicode_and_rejects_nan(self):
        self.assertEqual(canonical({'b': 1, 'a': ['é', None, True]}), '{"a":["é",null,true],"b":1}')
        with self.assertRaises(ValueError):
            canonical({'x': float('nan')})

    def test_worker_hash_is_sha256_of_the_canonical_route(self):
        expected = hashlib.sha256(canonical(ROUTE).encode('utf-8')).hexdigest()
        self.assertEqual(worker_hash(ROUTE), expected)
        self.assertEqual(worker_hash(dict(reversed(list(ROUTE.items())))), expected)
        self.assertEqual(set(ROUTE), set(ROUTE_FIELDS))

    def test_every_route_field_changes_the_worker_hash(self):
        base = worker_hash(ROUTE)
        for field in ROUTE_FIELDS:
            self.assertNotEqual(worker_hash(dict(ROUTE, **{field: ROUTE[field] + 'x'})), base, field)

    def test_malformed_routes_are_refused(self):
        for bad in (dict(ROUTE, extra='x'), {k: v for k, v in ROUTE.items() if k != 'effort'}, dict(ROUTE, model=''),
                    dict(ROUTE, effort=None), 'route'):
            with self.assertRaises(Error):
                worker_hash(bad)


class AdapterHashTests(Dir):
    def test_manifest_hashes_source_bytes_ordered_by_path(self):
        path = self.adapter([sys.executable, 'z.py', 'b.py'], {'z.py': 'z\n', 'b.py': 'b\n'})
        manifest = source_manifest(path)
        self.assertEqual([m[0] for m in manifest], ['b.py', 'z.py'])
        self.assertEqual(manifest[0][1], hashlib.sha256((self.dir / 'b.py').read_bytes()).hexdigest())
        # Arguments that are not files (flags, missing names) are not sources.
        self.assertEqual(source_manifest(self.adapter([sys.executable, 'a.py', '--flag', 'nothing.py'])),
                         [['a.py', hashlib.sha256((self.dir / 'a.py').read_bytes()).hexdigest()]])

    def test_adapter_hash_covers_config_and_source_bytes(self):
        path = self.adapter()
        base = adapter_hash(path)
        self.assertEqual(base, adapter_hash(path))
        (self.dir / 'a.py').write_text('print(2)\n', encoding='utf-8')
        edited = adapter_hash(path)
        self.assertNotEqual(edited, base)
        self.assertNotEqual(adapter_hash(self.adapter(extra_key=1)), edited)
        self.assertEqual(adapter_hash(self.adapter(files={'a.py': 'print(2)\n'}, extra_key=1)),
                         adapter_hash(self.adapter(files={'a.py': 'print(2)\n'}, extra_key=1)))

    def test_adapter_hash_does_not_depend_on_where_the_directory_is(self):
        one = self.adapter()
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        (Path(other.name) / 'a.py').write_text('print(1)\n', encoding='utf-8')
        (Path(other.name) / 'adapter.json').write_text(json.dumps({'argv': [sys.executable, 'a.py'], **CAPS}),
                                                       encoding='utf-8')
        self.assertEqual(adapter_hash(one), adapter_hash(Path(other.name) / 'adapter.json'))

    def test_unreadable_adapter_files_are_errors(self):
        with self.assertRaises(Error):
            adapter_hash(self.dir / 'missing.json')
        (self.dir / 'bad.json').write_text('{"argv": []}', encoding='utf-8')
        with self.assertRaises(Error):
            adapter_hash(self.dir / 'bad.json')

    def test_environment_hash_covers_argv_flags_and_nonsecret_variables_only(self):
        path = self.adapter()
        base = environment_hash(path, ['--x'], {'OZ_MODEL': 'm', 'API_KEY': 'secret-1'})
        self.assertEqual(base, environment_hash(path, ['--x'], {'OZ_MODEL': 'm', 'API_KEY': 'secret-2'}))
        self.assertNotEqual(base, environment_hash(path, ['--y'], {'OZ_MODEL': 'm'}))
        self.assertNotEqual(base, environment_hash(path, ['--x'], {'OZ_MODEL': 'n'}))
        self.assertNotEqual(base, environment_hash(path, ['--x'], {'OZ_MODEL': 'm', 'OZ_CODEX_TIMEOUT': '5'}))


class ReconcileTests(unittest.TestCase):
    def test_matching_identity_is_accepted(self):
        got = reconcile(report(), model='m', effort='high')
        self.assertEqual((got['backend'], got['model'], got['effort'], got['cli_version']), ('fake', 'm', 'high', '1.0'))

    def test_conflicts_and_unknowns_block(self):
        for bad, text in ((report(model='other'), 'conflict'), (report(effort='low'), 'conflict'),
                          (report(cli_version='unknown (OSError)'), 'unknown'), (report(cli_version=''), 'unknown'),
                          (report(backend=None), 'unknown'), (report(effort_applicable='yes'), 'unknown'),
                          (report(flags='x'), 'unknown')):
            with self.assertRaisesRegex(Error, text):
                reconcile(bad, model='m', effort='high')

    def test_effort_not_applicable_is_recorded_explicitly_not_defaulted(self):
        got = reconcile(report(effort='ignored', effort_applicable=False), model='m', effort='high')
        self.assertEqual(got['effort'], NOT_APPLICABLE)


class ProbeAndBuildTests(Dir):
    def script(self, body):
        return self.adapter(files={'a.py': body})

    def test_probe_runs_identity_with_model_and_effort_in_the_environment(self):
        path = self.script("import json, os, sys\nassert '--identity' in sys.argv\n"
                           "json.dump({'backend': 'fake', 'model': os.environ['OZ_MODEL'], "
                           "'effort': os.environ['OZ_EFFORT'], 'cli_version': '2'}, sys.stdout)\n")
        got = probe(path, model='mm', effort='ee')
        self.assertEqual((got['model'], got['effort']), ('mm', 'ee'))

    def test_probe_failures_are_errors(self):
        for body in ('import sys\nsys.exit(3)\n', 'print("not json")\n', 'print("[1]")\n'):
            with self.assertRaisesRegex(Error, 'unknown'):
                probe(self.script(body), model='m', effort='e')
        with self.assertRaisesRegex(Error, 'unknown'):
            probe(self.adapter([str(self.dir / 'nonexistent-binary')]), model='m', effort='e')

    def test_build_gives_route_hash_and_oz_do_route(self):
        path = self.script("import json, sys\njson.dump({'backend': 'fake', 'model': 'm', 'effort': 'high', "
                           "'cli_version': '2', 'flags': ['-f']}, sys.stdout)\n")
        built = build(path, model='m', effort='high', env={})
        route = built['route']
        self.assertEqual(set(route), set(ROUTE_FIELDS))
        self.assertEqual(built['worker_hash'], worker_hash(route))
        self.assertEqual(route['adapter_hash'], adapter_hash(path))
        self.assertEqual(built['do_route'], {'adapter': route['adapter_hash'], 'model': 'm', 'effort': 'high',
                                             'cli_version': '2'})
        # Same inputs, same hash; another effort is another worker (and the adapter reports it back).
        self.assertEqual(build(path, model='m', effort='high', env={})['worker_hash'], built['worker_hash'])

    def test_build_blocks_on_a_conflict_and_on_blank_model_or_effort(self):
        path = self.script("import json, sys\njson.dump({'backend': 'b', 'model': 'zzz', 'effort': 'high', "
                           "'cli_version': '2'}, sys.stdout)\n")
        with self.assertRaisesRegex(Error, 'conflict'):
            build(path, model='m', effort='high')
        for model, effort in (('', 'high'), ('m', ' '), (None, 'high')):
            with self.assertRaisesRegex(Error, 'required'):
                build(path, model=model, effort=effort)

    def test_source_edit_changes_the_worker_hash(self):
        body = ("import json, os, sys\njson.dump({'backend': 'b', 'model': os.environ['OZ_MODEL'], "
                "'effort': os.environ['OZ_EFFORT'], 'cli_version': '2'}, sys.stdout)\n")
        first = build(self.script(body), model='m', effort='e', env={})['worker_hash']
        second = build(self.script(body + '# edited\n'), model='m', effort='e', env={})['worker_hash']
        self.assertNotEqual(first, second)


class ShippedAdapterIdentityTests(Dir):
    """The real adapter scripts answer --identity from a fake CLI on PATH, with no model call."""

    def fake_cli(self, name, version):
        script = self.dir / f'fake_{name}.py'
        script.write_text(f"import sys\nprint({version!r}) if sys.argv[1:] == ['--version'] else sys.exit(9)\n",
                          encoding='utf-8')
        if os.name == 'nt':
            (self.dir / f'{name}.cmd').write_text(f'@"{sys.executable}" "{script}" %*\n', encoding='utf-8')
        else:
            exe = self.dir / name
            exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding='utf-8')
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC)

    def identity(self, adapter, model, effort, path):
        env = dict(os.environ, PATH=path, OZ_MODEL=model, OZ_EFFORT=effort, PYTHONIOENCODING='utf-8')
        return subprocess.run([sys.executable, str(ROOT / 'examples' / adapter), '--identity'], env=env,
                              capture_output=True, text=True, encoding='utf-8', timeout=60)

    def test_codex_and_claude_report_distinct_backends_and_versions(self):
        self.fake_cli('codex', 'codex-cli 9.9.9')
        self.fake_cli('claude', '7.7.7 (Claude Code)')
        path = str(self.dir) + os.pathsep + os.environ['PATH']
        codex = json.loads(self.identity('codex_cli_adapter.py', 'gpt-x', 'high', path).stdout)
        claude = json.loads(self.identity('claude_map_adapter.py', 'claude-y', 'medium', path).stdout)
        self.assertEqual((codex['backend'], codex['model'], codex['effort'], codex['cli_version']),
                         ('codex', 'gpt-x', 'high', 'codex-cli 9.9.9'))
        self.assertEqual((claude['backend'], claude['model'], claude['effort'], claude['cli_version']),
                         ('claude', 'claude-y', 'medium', '7.7.7 (Claude Code)'))
        self.assertIn('--effort', claude['flags'])
        self.assertTrue(codex['effort_applicable'] and claude['effort_applicable'])
        for item in (codex, claude):
            reconcile(item, model=item['model'], effort=item['effort'])

    def test_claude_adapter_passes_effort_only_when_given_and_keeps_the_model(self):
        script = self.dir / 'fake_claude.py'
        script.write_text("import json, os, sys\n"
                          "if sys.argv[1:] == ['--version']:\n    print('7.7.7'); sys.exit(0)\n"
                          "open(os.environ['FAKE_LOG'], 'w').write(json.dumps(sys.argv[1:]))\n"
                          "sys.stdin.read()\nprint(json.dumps({'result': 'OZ/1g'}))\n", encoding='utf-8')
        if os.name == 'nt':
            (self.dir / 'claude.cmd').write_text(f'@"{sys.executable}" "{script}" %*\n', encoding='utf-8')
        else:
            exe = self.dir / 'claude'
            exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding='utf-8')
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        path = str(self.dir) + os.pathsep + os.environ['PATH']
        log = self.dir / 'argv.json'
        base = dict(os.environ, PATH=path, FAKE_LOG=str(log), OZ_MODEL='claude-q')
        base.pop('OZ_EFFORT', None)
        adapter = str(ROOT / 'examples' / 'claude_map_adapter.py')
        request = json.dumps({'system': 'S', 'prompt': 'P'})
        for env, expect in ((base, None), (dict(base, OZ_EFFORT='high'), 'high')):
            done = subprocess.run([sys.executable, adapter], input=request, capture_output=True, text=True,
                                  encoding='utf-8', timeout=60, env=env)
            self.assertEqual(done.returncode, 0, done.stderr)
            argv = json.loads(log.read_text(encoding='utf-8'))
            self.assertEqual(argv[argv.index('--model') + 1], 'claude-q')
            if expect is None:
                self.assertNotIn('--effort', argv)
            else:
                self.assertEqual(argv[argv.index('--effort') + 1], expect)
        ident = subprocess.run([sys.executable, adapter, '--identity'], capture_output=True, text=True,
                               encoding='utf-8', timeout=60, env=base)
        self.assertEqual(json.loads(ident.stdout)['effort'], 'default')

    def test_a_missing_executable_gives_an_explicit_diagnostic_and_exit_127(self):
        empty = str(self.dir / 'nothing')
        (self.dir / 'nothing').mkdir()
        for adapter, word in (('codex_cli_adapter.py', 'codex'), ('claude_map_adapter.py', 'claude')):
            done = self.identity(adapter, 'm', 'low', empty)
            self.assertEqual(done.returncode, 127, adapter)
            self.assertIn(f'{word} executable not found', done.stderr)

    def test_claude_map_adapter_hash_covers_the_frozen_adapter_it_imports(self):
        manifest = dict(source_manifest(ROOT / 'examples' / 'claude_map_adapter.json'))
        self.assertEqual(set(manifest), {'claude_map_adapter.py', 'claude_cli_adapter.py'})
        for name, digest in manifest.items():
            self.assertEqual(digest, hashlib.sha256((ROOT / 'examples' / name).read_bytes()).hexdigest())

    def test_an_edit_to_an_imported_sibling_changes_the_adapter_hash(self):
        (self.dir / 'lib.py').write_text('X = 1\n', encoding='utf-8')
        path = self.adapter(files={'a.py': 'import lib\n'})
        first = adapter_hash(path)
        (self.dir / 'lib.py').write_text('X = 2\n', encoding='utf-8')
        self.assertNotEqual(first, adapter_hash(path))


if __name__ == '__main__':
    unittest.main()
