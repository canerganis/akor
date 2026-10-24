"""Council 3 close (docs/design/ozmap-2026-10-24/council3-close-astra.md and council3-close-opus.md): one named test or
more per remaining item. Opus N1 (Codex isolation and tool-use leakage, Claude tools off), N2 (one driver), N3/B9
(oz_quota, the 99% handoff stop, verified process-tree termination), the Astra telemetry blocker, B4, B5, B6, B8, B10,
B11, B12 and the Opus extras (per-attempt envelopes, failed-call usage, interpreter and full file set in the freeze).
Fake CLIs and in-process fakes only: no model call, no network."""
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest

REPO = Path(__file__).resolve().parent.parent
for p in (REPO, REPO / 'examples', REPO / 'tests'):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import bootstrap_shim as shim  # noqa: E402
import claude_map_adapter as cma  # noqa: E402
import codex_cli_adapter as cca  # noqa: E402
from oz import Error  # noqa: E402
import oz_host  # noqa: E402
import oz_route  # noqa: E402
import oz_rulephase as rp  # noqa: E402
import oz_spool  # noqa: E402
import test_oz_host as th  # noqa: E402


def _load(name):
    key = 'ozmap_' + name
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, REPO / 'bench' / 'ozmap' / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


pilot = _load('pilot')
fake_cli = pilot.fake_cli
score = pilot.score
data = pilot.data

FULL = {'input_tokens': 100, 'cached_input_tokens': 40, 'cache_creation_input_tokens': 0, 'output_tokens': 10,
        'reasoning_output_tokens': 4}
SAMPLE = {'input_tokens': 1000, 'cached_input_tokens': 0, 'cache_creation_input_tokens': 0, 'output_tokens': 50,
          'reasoning_output_tokens': 10, 'elapsed_seconds': 1.0,
          'raw': {'in_uncached': 1000, 'cache_read': 0, 'cache_write': 0, 'out': 50}}
SAMPLES = {'codex': {'call': [SAMPLE], 'bootstrap': [SAMPLE]}, 'claude': {'call': [SAMPLE], 'bootstrap': [SAMPLE]}}

# A fake `codex` that records what isolation it saw: argv, its cwd, the -C directory's listing and repo ancestry.
ISO_FAKE = r'''
import json, os, sys
if sys.argv[1:] == ['--version']:
    print('codex-cli 9.9.9')
    sys.exit(0)
argv = sys.argv[1:]
d = argv[argv.index('-C') + 1] if '-C' in argv else None
def inside(p):
    while True:
        if os.path.exists(os.path.join(p, '.git')):
            return True
        q = os.path.dirname(p)
        if q == p:
            return False
        p = q
real = os.path.realpath(d) if d else None
log = {'argv': argv, 'cwd': os.path.realpath(os.getcwd()), 'dir': real,
       'listing': os.listdir(d) if d and os.path.isdir(d) else None, 'inside_repo': inside(real) if d else None}
with open(os.environ['ISO_LOG'], 'w', encoding='utf-8') as f:
    json.dump(log, f)
sys.stdin.read()
sys.stdout.write(open(os.environ['ISO_EVENTS'], encoding='utf-8').read())
'''


def ev(kind, **fields):
    return json.dumps({'type': kind, **fields})


def stream(reply='OZ/1g', tool=None):
    lines = [ev('thread.started', thread_id='t'), ev('turn.started')]
    if tool:
        lines.append(ev('item.completed', item={'id': 'i1', 'type': tool, 'command': 'cat registry.json'}))
    lines += [ev('item.completed', item={'id': 'i2', 'type': 'agent_message', 'text': reply}),
              ev('turn.completed', usage={'input_tokens': 900, 'cached_input_tokens': 100, 'output_tokens': 20,
                                          'reasoning_output_tokens': 5})]
    return '\n'.join(lines) + '\n'


class Temp(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)


# ---------------------------------------------------------------------------------------------- N1 Codex

class N1CodexIsolation(Temp):
    def setUp(self):
        super().setUp()
        script = self.dir / 'fake_codex.py'
        script.write_text(ISO_FAKE, encoding='utf-8')
        if os.name == 'nt':
            (self.dir / 'codex.cmd').write_text(f'@"{sys.executable}" "{script}" %*\n', encoding='utf-8')
        else:
            exe = self.dir / 'codex'
            exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding='utf-8')
            exe.chmod(0o755)

    def run_adapter(self, events):
        (self.dir / 'events.jsonl').write_text(events, encoding='utf-8')
        env = dict(os.environ, PATH=str(self.dir) + os.pathsep + os.environ['PATH'], ISO_LOG=str(self.dir / 'log.json'),
                   ISO_EVENTS=str(self.dir / 'events.jsonl'), OZ_ENVELOPE_PATH=str(self.dir / 'envelope.json'))
        done = subprocess.run([sys.executable, str(REPO / 'examples' / 'codex_cli_adapter.py')],
                              input=json.dumps({'system': 'S', 'prompt': 'P'}), capture_output=True, text=True,
                              encoding='utf-8', timeout=60, env=env)
        return done, json.loads((self.dir / 'log.json').read_text(encoding='utf-8')), \
            json.loads((self.dir / 'envelope.json').read_text(encoding='utf-8'))

    def test_n1_codex_exec_runs_in_a_fresh_empty_dir_outside_the_repo(self):
        done, log, envelope = self.run_adapter(stream())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('--skip-git-repo-check', log['argv'])
        self.assertEqual(log['argv'][log['argv'].index('-C') + 1], envelope['workdir'])
        self.assertEqual(log['cwd'], log['dir'])  # process cwd and codex root are the same fresh directory
        self.assertEqual(log['listing'], [])  # empty: no gold, label or worked AST to read
        self.assertFalse(log['inside_repo'])
        self.assertNotEqual(os.path.commonpath([log['dir'], str(REPO.resolve())]), str(REPO.resolve()))
        self.assertFalse(Path(log['dir']).exists())  # removed after the call
        self.assertEqual(envelope['leakage'], [])

    def test_n1_tool_events_invalidate_the_call_and_the_capture_keeps_usage(self):
        done, _, envelope = self.run_adapter(stream(tool='command_execution'))
        self.assertEqual(done.returncode, cca.EXIT_LEAKAGE)
        self.assertEqual(done.stdout, '')  # no reply: the worker accepts none of its answers
        self.assertIn('oz-leakage', done.stderr)
        self.assertEqual([x['item_type'] for x in envelope['leakage']], ['command_execution'])
        self.assertEqual(envelope['usage']['input_tokens'], 900)  # the call's usage stays in the capture

    def test_n1_only_text_generation_events_pass_the_leakage_check(self):
        clean = [ev('thread.started'), ev('turn.started'), ev('error', message='Reconnecting... 1/5'),
                 ev('item.started', item={'type': 'reasoning'}), ev('item.completed', item={'type': 'reasoning'}),
                 ev('item.updated', item={'type': 'agent_message'}), ev('item.completed', item={'type': 'agent_message'}),
                 ev('turn.completed', usage={}), ev('turn.failed', error={}), 'Reading prompt from stdin...']
        self.assertEqual(cca.leakage('\n'.join(clean)), [])
        for item in ('command_execution', 'file_change', 'mcp_tool_call', 'web_search', 'todo_list', 'file_read',
                     'something_new'):
            with self.subTest(item=item):
                got = cca.leakage(ev('item.started', item={'type': item}))
                self.assertEqual([x['item_type'] for x in got], [item])
        self.assertEqual([x['type'] for x in cca.leakage(ev('tool.call'))], ['tool.call'])
        self.assertIn('-C', cca.FLAGS)


class N1Claude(Temp):
    def test_n1_claude_runs_with_every_tool_disabled(self):
        argv = cma.command('claude', 'm', None, 'SYSTEM')
        self.assertEqual(argv[argv.index('--tools') + 1], '')  # no built-in tool exists
        self.assertEqual(argv[argv.index('--setting-sources') + 1], '')  # no settings, hooks or permissions
        self.assertIn('--strict-mcp-config', argv)  # with no --mcp-config: no MCP tool
        for flag in ('--allowedTools', '--allowed-tools', '--mcp-config', '--dangerously-skip-permissions',
                     '--add-dir'):
            self.assertNotIn(flag, argv)
        self.assertEqual(cma.tool_use({'num_turns': 1, 'permission_denials': []}), [])
        self.assertEqual(cma.tool_use({'num_turns': 3, 'permission_denials': [{'tool_name': 'Read'}]}),
                         ['num_turns=3', 'permission_denials=1'])

    def test_n1_claude_usage_from_a_model_other_than_the_pinned_one_is_flagged(self):
        from unittest import mock
        one = {'num_turns': 1, 'modelUsage': {'claude-sonnet-5-5': {}}}
        two = {'num_turns': 1, 'modelUsage': {'claude-sonnet-5-5': {}, 'claude-haiku-5-5': {}}}
        with mock.patch.dict(os.environ, {'OZ_MODEL': 'claude-sonnet-5-5'}):
            self.assertEqual(cma.tool_use(one), [])
            self.assertEqual(cma.tool_use(two), ['unexpected_model=claude-haiku-5-5'])

    def test_n1_claude_tool_use_exits_86_and_keeps_the_envelope(self):
        fake = self.dir / 'fake'
        fake_cli.build(fake, answers={}, rules={}, samples=SAMPLES, repo=REPO, leak={'claude': True})
        env = dict(fake_cli.env_with(fake), OZ_ENVELOPE_PATH=str(self.dir / 'envelope.json'), OZ_MODEL='m')
        prompt = json.dumps({'jobs': [['e', ['j1', 'r1']]], 'refs': {'r1': 'length=1 mm'}})
        done = subprocess.run([sys.executable, str(REPO / 'examples' / 'claude_map_adapter.py')],
                              input=json.dumps({'system': 'S', 'prompt': prompt}), capture_output=True, text=True,
                              encoding='utf-8', timeout=120, env=env)
        self.assertEqual(done.returncode, cma.EXIT_LEAKAGE, done.stderr)
        self.assertEqual(done.stdout, '')
        envelope = json.loads((self.dir / 'envelope.json').read_text(encoding='utf-8'))
        self.assertEqual(envelope['num_turns'], 2)
        self.assertTrue(oz_host.envelope_evidence(json.dumps(envelope).encode())['leakage'])
        [call] = fake_cli.calls(fake)
        self.assertTrue(call['tools_disabled'])


class LeakyAdapter:
    """A callable adapter that answers correctly but whose envelope (OZ_ENVELOPE_PATH, codex capture format) shows a
    command execution: the host must refuse its answers although the call itself succeeded."""
    capabilities = oz_host.CAPS

    def __init__(self, env=None, tool='command_execution', fail=False, seen=None):
        self.env, self.tool, self.fail = env or {}, tool, fail
        self.seen = seen if seen is not None else []

    def bind_env(self, env):
        return LeakyAdapter(env, self.tool, self.fail, self.seen)

    def __call__(self, req):
        from oz_reply import encode_reply
        body = json.loads(req['prompt'])
        answers = {row[0]: th.extract(body['refs'][row[1]]) for block in body['jobs'] for row in block[1:]}
        events = stream(encode_reply(answers), tool=self.tool)
        usage = {'input_tokens': 900, 'cached_input_tokens': 100, 'output_tokens': 20, 'reasoning_output_tokens': 5,
                 'cache_creation_input_tokens': 0}
        path = self.env.get('OZ_ENVELOPE_PATH')
        self.seen.append(path)
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps({'adapter': 'codex_cli_adapter', 'stdout': events, 'usage': usage,
                                              'exit_code': 1 if self.fail else 0}), encoding='utf-8')
        if self.fail:
            raise RuntimeError('codex exited 1')
        return {'reply': encode_reply(answers), 'usage': usage}


class N1Host(th.Base):
    def test_n1_the_host_refuses_answers_of_a_leaking_call_and_marks_the_run(self):
        a = self.host('A', None, launcher=oz_host.InProcessLauncher(LeakyAdapter()))
        a.submit('p0', 's0', th.producer_jobs(0, 4, None), wave='w')
        report = a.run_wave('w')
        self.assertEqual(report['accepted_by_checks'], 0)
        self.assertTrue(all(r['error'].startswith('tool_use_leakage') for r in a._rows.values()))
        self.assertTrue(any(x.startswith('tool_use_leakage:') for x in report['efficiency_invalid']))
        self.assertEqual(report['leakage'][0]['kind'], 'codex')
        self.assertEqual(len(a.leakage()), 1)
        self.assertEqual(a.ledger.envelopes()[0]['leakage'][0]['item_type'], 'command_execution')

    def test_n1_end_to_end_child_leak_through_the_real_codex_adapter(self):
        fake = self.dir / 'fake'
        fake_cli.build(fake, answers={}, rules={}, samples=SAMPLES, repo=REPO, leak={'codex': True})
        env = fake_cli.env_with(fake)
        adapter = REPO / 'examples' / 'bootstrap_codex_adapter.json'
        built = oz_route.build(adapter, model='m-test', effort='low',
                               env=oz_host.child_env(model='m-test', effort='low', base=env))
        a = oz_host.ArmHost(arm='A', backend='codex', workload='mat', experiment_dir=self.dir,
                            launcher=oz_host.ChildLauncher(adapter), op='e', op_text='Extract the length.',
                            model='m-test', effort='low', identity=oz_host.identity_for(built['route']),
                            allow_experimental=True, max_wait=0.0, base_env=env,
                            route_check={'frozen': built, 'adapter': str(adapter), 'model': 'm-test', 'effort': 'low'})
        self.hosts.append(a)
        a.submit('p0', 's0', th.producer_jobs(0, 3, None), wave='w')
        report = a.run_wave('w')
        self.assertEqual(report['accepted_by_checks'], 0)
        self.assertTrue(any(x.startswith('tool_use_leakage:') for x in report['efficiency_invalid']))
        [envelope] = a.ledger.envelopes()
        self.assertEqual((envelope['kind'], envelope['leakage'][0]['item_type']), ('codex', 'command_execution'))
        self.assertEqual(envelope['usage']['input_tokens'], SAMPLE['input_tokens'])  # the capture keeps the usage
        [call] = fake_cli.calls(fake)
        self.assertTrue(call['isolated'])


# ------------------------------------------------------------------------------------------- N2 one driver

class N2OneDriver(Temp):
    def test_n2_run_live_and_dry_share_one_driver(self):
        for fn in (pilot.run_live, pilot.dry):
            self.assertIn('drive(ctx)', inspect.getsource(fn))
        self.assertNotIn('dry_run', inspect.getsource(pilot.dry))
        src = inspect.getsource(pilot.drive)
        for needle in ('ChildLauncher', 'load_registry', 'route_check(backend, routes)', "hooks={'launch_gate'",
                       'quota=ctx', "max_wait=HOST['max_wait']", 'submit_barrier'):
            self.assertIn(needle, src)
        self.assertIn("json.loads(reg_path.read_text", inspect.getsource(pilot.dry))  # the registry from its file
        self.assertEqual(pilot.pilot_config('dry', {}, 'x')['max_wait'], pilot.HOST['max_wait'])

    def test_n2_a_dry_pilot_refuses_in_process_launchers_callable_checks_and_extra_hooks(self):
        config = pilot.pilot_config('dry', {'fake': oz_host.identity_for(th.ROUTE)}, 'x')
        budget = oz_host.Budget(self.dir / 'b.sqlite', caps=config['caps'], global_cap=config['global_cap'])
        self.addCleanup(budget.close)
        kw = dict(backend='fake', budget=budget, slot_pool=oz_host.SlotPool(self.dir / 's', 4), slots=4,
                  max_records=64, max_wait=1.0, identity=oz_host.identity_for(th.ROUTE),
                  launcher=oz_host.InProcessLauncher(lambda r: None), limits=config['limits'],
                  route_check=lambda env: None, hooks={'evaluate': len}, quota=None)
        with self.assertRaises(Error) as ctx:
            oz_host.check_pilot(config, **kw)
        text = str(ctx.exception)
        for needle in ('launches child processes only', 'a callable check is a bypass', 'through oz_quota',
                       'no hook but launch_gate', 'needs the launch gate', 'no dependency closure'):
            self.assertIn(needle, text)

    def test_n2_the_fake_cli_executables_come_first_on_path(self):
        paths = fake_cli.build(self.dir / 'fake', answers={}, rules={}, samples=SAMPLES, repo=REPO)
        env = fake_cli.env_with(self.dir / 'fake')
        for name in ('codex', 'claude'):
            found = shutil.which(name, path=env['PATH'])
            self.assertEqual(Path(found).resolve(), Path(paths[name]).resolve())
        out = subprocess.run([paths['codex'], '--version'], capture_output=True, text=True, timeout=60).stdout
        self.assertIn('fake-replay', out)
        self.assertEqual(Path(paths['codex']).read_bytes(),
                         fake_cli._program(sys.executable))  # deterministic bytes: a stable dry route


# ---------------------------------------------------------------------------------------- N3 quota, 99% stop

class N3Quota(th.Base):
    def test_n3_the_launch_gate_needs_a_reading_of_this_batch_and_stops_at_99(self):
        budget = types.SimpleNamespace(usage=lambda: {'total': 0})
        gate = pilot.launch_gate_for(budget, self.dir, 's1')
        self.assertTrue(gate(None).startswith('quota_reading_missing'))
        pilot.record_reading(self.dir, '50', 'owner', 's1')
        self.assertIsNone(gate(None))
        self.assertTrue(pilot.launch_gate_for(budget, self.dir, 's2')(None).startswith('quota_reading_missing'))
        pilot.record_reading(self.dir, '99%', 'owner (quota command)', 'owner')
        self.assertTrue(gate(None).startswith('quota_handoff_99'))
        full = types.SimpleNamespace(usage=lambda: {'total': 54})
        self.assertEqual(pilot.launch_gate_for(full, self.dir, 's1')(None), 'global_cap_reached')
        with self.assertRaises(SystemExit):
            pilot.record_reading(self.dir, 'abc', 'owner', 's1')

    def test_n3_every_launch_reserves_and_releases_an_oz_quota_slot(self):
        quota = oz_host.QuotaStore(self.dir / 'quota.sqlite')
        a = self.host('A', oz_host.ReplayAdapter(th.extract, samples=[FULL]), quota=quota,
                      slot_pool=oz_host.SlotPool(self.dir / 'slots', 4))
        a.submit('p0', 's0', th.producer_jobs(0, 70, None), wave='w')
        report = a.run_wave('w')
        self.assertEqual(report['calls']['physical'], 2)
        events = [e['event'] for e in quota.events()]
        self.assertEqual((events.count('acquired'), events.count('released')), (2, 2))
        self.assertTrue(all(quota.holder(f'oz-host-slot{k}') is None for k in range(4)))

    def test_n3_a_held_quota_slot_refuses_before_any_budget(self):
        quota = oz_host.QuotaStore(self.dir / 'quota.sqlite')
        quota.acquire('oz-host-slot0', run_dir=self.dir / 'other', receipt='r-other')  # held by a live coordinator
        adapter = oz_host.ReplayAdapter(th.extract)
        a = self.host('A', adapter, quota=quota, slot_pool=oz_host.SlotPool(self.dir / 'slots', 1), slots=1)
        a.submit('p0', 's0', th.producer_jobs(0, 3, None), wave='w')
        report = a.run_wave('w')
        self.assertEqual((adapter.log, a.budget.usage()['total']), ([], 0))
        self.assertTrue(any(r.startswith('quota_held') for r in report['incomplete']))

    def test_n3_telemetry_goes_through_the_launch_gate_before_anything(self):
        routes = {'codex': {'worker_hash': 'w' * 64, 'route': dict(th.ROUTE, backend='codex'), 'launch': {}}}
        ctx = {'routes': routes, 'env': None, 'gate': lambda view: 'quota_handoff_99: 99% reached',
               'run_dir': self.dir}
        got = pilot._guarded_call(ctx, key='telemetry-1', buckets=['telemetry'], request={}, evidence=self.dir / 'e')
        self.assertEqual(got['refused'], 'quota_handoff_99: 99% reached')
        self.assertEqual(pilot.certify_codex([got], 'w' * 64)[0], 'unverified')


# ------------------------------------------------------------------------------- B9 verified tree termination

GRANDCHILD = r'''
import subprocess, sys, time
from pathlib import Path
p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
Path(sys.argv[-1]).with_name('grandchild.pid').write_text(str(p.pid))
time.sleep(120)
'''


def _alive(pid):
    if os.name == 'nt':
        out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class B9Termination(Temp):
    def launch(self):
        script = self.dir / 'child.py'
        script.write_text(GRANDCHILD, encoding='utf-8')
        adapter = self.dir / 'adapter.json'
        adapter.write_text('{"argv": ["python"]}', encoding='utf-8')
        launcher = oz_host.ChildLauncher(adapter)
        original = oz_host.HOST_FILE
        oz_host.HOST_FILE = script
        try:
            execution, meta = launcher({'child_timeout': 3}, dict(os.environ), self.dir / 'ev')
        finally:
            oz_host.HOST_FILE = original
        return launcher, execution, meta, int((self.dir / 'ev' / 'grandchild.pid').read_text())

    def test_b9_a_verified_kill_is_the_only_tree_killed_true(self):
        launcher, execution, meta, pid = self.launch()
        self.assertIsNone(execution)
        self.assertTrue(meta['timed_out'])
        self.assertEqual((meta['tree']['killed'], meta['tree']['verified'], meta['tree_killed']), (True, True, True))
        self.assertFalse(_alive(pid), 'the grandchild survived a verified kill')
        self.assertEqual(launcher.unverified, {})
        exit_record = json.loads((self.dir / 'ev' / 'exit.json').read_text(encoding='utf-8'))
        self.assertIs(exit_record['tree_killed'], True)

    def test_b9_an_unverified_kill_never_reports_tree_killed_true(self):
        original = oz_host.ProcessTree.gone
        oz_host.ProcessTree.gone = lambda self, timeout=30.0: False  # termination cannot be confirmed
        try:
            launcher, execution, meta, pid = self.launch()
        finally:
            oz_host.ProcessTree.gone = original
        self.assertIs(meta['tree_killed'], False)
        self.assertIs(meta['tree']['verified'], False)
        key = str(self.dir / 'ev')
        self.assertIn(key, launcher.unverified)  # kept for the host's later re-check
        deadline = time.monotonic() + 30
        while not launcher.settled(key) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertNotIn(key, launcher.unverified)


class _UnverifiedLauncher:
    """In-process execution reported as a child whose process tree could not be verified gone."""

    def __init__(self, inner):
        self.inner, self.gone = inner, False

    def __call__(self, spec, env, evidence):
        execution, meta = self.inner(spec, env, evidence)
        return execution, dict(meta, tree={'mode': 'job', 'killed': True, 'verified': False}, tree_killed=False)

    def settled(self, evidence):
        return self.gone


class B9Host(th.Base):
    def test_b9_the_host_keeps_slot_and_quota_until_the_tree_is_verified_gone(self):
        quota = oz_host.QuotaStore(self.dir / 'quota.sqlite')
        launcher = _UnverifiedLauncher(oz_host.InProcessLauncher(shim.CallableShim(oz_host.ReplayAdapter(th.extract))))
        a = self.host('A', None, launcher=launcher, quota=quota, slot_pool=oz_host.SlotPool(self.dir / 'slots', 1),
                      slots=1)
        a.submit('p0', 's0', th.producer_jobs(0, 3, None), wave='w')
        report = a.run_wave('w')
        [attempt] = a.ledger.attempts('w')
        self.assertEqual(attempt['outcome'], 'unresolved')
        self.assertTrue(any(r.startswith('process_tree_unverified:') for r in report['incomplete']))
        self.assertIn('process tree not verified gone', ' '.join(report['reconciliation']['problems']))
        with self.assertRaises(oz_spool.HostLocked):  # the physical slot is still held
            oz_spool.HostLock(self.dir / 'slots' / 'slot0.lock').acquire()
        self.assertIsNotNone(quota.holder('oz-host-slot0'))  # and so is its oz_quota reservation
        launcher.gone = True
        self.assertEqual(a._reap(), [attempt['attempt_id']])
        oz_spool.HostLock(self.dir / 'slots' / 'slot0.lock').acquire().release()
        self.assertIsNone(quota.holder('oz-host-slot0'))
        self.assertIn('termination_verified', [e['event'] for e in a.ledger.events(attempt['attempt_id'])])


# ------------------------------------------------------------------------------------ telemetry certification

def tele(key, usage, *, worker='w', system='s', prompt='p', leakage=(), visible='inclusive'):
    if visible == 'inclusive':  # the visible reply is output minus reasoning, as Codex reports it
        visible = (usage['output_tokens'] - usage['reasoning_output_tokens']
                   if isinstance(usage, dict) and {'output_tokens', 'reasoning_output_tokens'} <= set(usage) else None)
    return {'key': key, 'worker_hash': worker, 'leakage': list(leakage),
            'calls': [{'call_id': key, 'usage': usage, 'system_sha256': system, 'prompt_sha256': prompt,
                       'visible_tokens': visible}]}


def u(inp, cached, out=20, reasoning=5):
    return {'input_tokens': inp, 'cached_input_tokens': cached, 'output_tokens': out,
            'reasoning_output_tokens': reasoning}


class Telemetry(Temp):
    def test_telemetry_certifies_only_backend_specific_inclusion_evidence(self):
        status, evidence = pilot.certify_codex([tele('t1', u(900, 0, out=400, reasoning=200)),
                                                tele('t2', u(900, 300, out=400, reasoning=200))], 'w')
        self.assertEqual(status, 'ok', evidence)
        self.assertEqual(evidence['inclusion']['cached_input_tokens'], [0, 300])

    def test_telemetry_exclusive_totals_and_bare_inequalities_never_certify(self):
        cases = {'exclusive (input drops by the cache hit)': (u(900, 0), u(600, 300)),
                 'no cache growth (inequalities only)': (u(900, 100), u(900, 100)),
                 'empty usage': ({}, {}),
                 'reasoning component missing': ({'input_tokens': 900, 'cached_input_tokens': 0, 'output_tokens': 2},
                                                  {'input_tokens': 900, 'cached_input_tokens': 300,
                                                   'output_tokens': 2}),
                 'cached above input': (u(900, 0), u(900, 901)),
                 'unknown usage': (None, None)}
        for name, (a, b) in cases.items():
            with self.subTest(name):
                self.assertEqual(pilot.certify_codex([tele('t1', a), tele('t2', b)], 'w')[0], 'unverified')

    def test_telemetry_certifies_reasoning_inclusion_only_from_the_visible_reply(self):
        a, b = u(900, 0, out=400, reasoning=200), u(900, 300, out=400, reasoning=200)
        self.assertEqual(pilot.certify_codex([tele('t1', a), tele('t2', b)], 'w')[0], 'ok')
        cases = {'no visible reply': None,
                 'exclusive (output equals the visible reply alone)': 400,
                 'neither reading matches': 300}
        for name, visible in cases.items():
            with self.subTest(name):
                got = pilot.certify_codex([tele('t1', a, visible=visible), tele('t2', b, visible=visible)], 'w')
                self.assertEqual(got[0], 'unverified', got)
        self.assertIsNone(pilot.reasoning_inclusion(u(1, 0, out=1324, reasoning=205), 1113))  # a recorded call
        self.assertIsNotNone(pilot.reasoning_inclusion(u(1, 0, out=1324, reasoning=205), 1324))

    def test_telemetry_is_bound_to_the_frozen_route_and_an_identical_prompt(self):
        good = (u(900, 0), u(900, 300))
        self.assertEqual(pilot.certify_codex([tele('t1', good[0]), tele('t2', good[1], worker='other')], 'w')[0],
                         'unverified')
        self.assertEqual(pilot.certify_codex([tele('t1', good[0]), tele('t2', good[1], prompt='q')], 'w')[0],
                         'unverified')
        self.assertEqual(pilot.certify_codex([tele('t1', good[0]), tele('t2', good[1], leakage=[{'x': 1}])], 'w')[0],
                         'unverified')
        self.assertEqual(pilot.certify_codex([tele('t1', good[0])], 'w')[0], 'unverified')

    def test_telemetry_never_certifies_the_other_backend(self):
        routes = {'codex': {'worker_hash': 'w'}, 'sonnet': {'worker_hash': 's'}}
        doc = {'status': 'ok', 'backend': 'codex', 'worker_hash': 'w', 'freeze_sha256': 'f', 'run_dir': 'r'}
        got = pilot.usage_semantics(routes, doc, 'f')
        self.assertTrue(got['codex'].startswith('inclusive cached accounting certified'))
        self.assertEqual(got['sonnet'], pilot.SONNET_SEMANTICS)  # never the Codex result
        self.assertEqual(pilot.usage_semantics({'codex': {'worker_hash': 'x'}}, doc, 'f')['codex'], 'unverified')
        self.assertEqual(pilot.usage_semantics(routes, doc, 'other freeze')['codex'], 'unverified')
        self.assertEqual(pilot.usage_semantics(routes, dict(doc, status='unverified'), 'f')['codex'], 'unverified')

    def test_telemetry_reads_core_calls_after_a_failure_and_keeps_the_failed_usage(self):
        fake = self.dir / 'fake'
        fake_cli.build(fake, answers={}, rules={}, samples=SAMPLES, repo=REPO, leak={'codex': True})
        env = fake_cli.env_with(fake)
        routes = pilot.build_routes(env=env, path=self.dir / 'routes.json')
        run_dir = self.dir / 'run'
        pilot.record_reading(run_dir, 10, 'test', 'sess')
        ctx = pilot._context('dry', run_dir, env=env, routes=routes, registry=None, closure=None,
                             quota=oz_host.QuotaStore(self.dir / 'q.sqlite'), session='sess',
                             telemetry_file=self.dir / 'telemetry.json')
        self.addCleanup(pilot._close, ctx)
        doc = pilot.run_telemetry(ctx)
        self.assertEqual(doc['status'], 'unverified')
        self.assertTrue(doc['leakage'])
        for r in doc['results']:
            [call] = r['calls']
            self.assertTrue(call['usage_source'].startswith('adapter_envelope:'))  # core usage unknown: kept
            self.assertEqual(call['usage']['input_tokens'], SAMPLE['input_tokens'])
            self.assertTrue(r['tree_verified'])
        self.assertEqual(ctx['budget'].usage()['used']['codex'], {'telemetry': 1, 'reserve': 1})


# --------------------------------------------------------------------------------------------------- B4, B5

class B4B5Resume(th.Base):
    def boot_texts(self):
        assignment = rp.bootstrap_assignment(
            {f'p{p}': [j['dataset_id'] for j in th.producer_jobs(p)] for p in range(4)}, 20261024)
        return {j['text'][:-1] for p in range(4) for j in th.producer_jobs(p) if j['dataset_id'] in assignment[f'p{p}']}

    def reopen(self, host, adapter, **kw):
        host.close()
        self.hosts.remove(host)
        return self.host(host.arm, adapter, **kw)

    def test_b4_resume_after_quarantine_restores_the_staged_r3_continuation(self):
        boot = self.boot_texts()
        adapter = oz_host.ReplayAdapter(lambda t: th.extract(t) if t in boot else '9.99 mm', {'e': th.FIELD})

        def crash(wave, staged):
            raise RuntimeError('host crashed after the audits quarantined the rule, before staged delivery')

        c = self.host('C', adapter, hooks={'before_staged_delivery': crash})
        with self.assertRaisesRegex(RuntimeError, 'before staged delivery'):
            self.cold(c)
        self.assertTrue(any(r['status'] == 'quarantined' for r in c.store.rules(c.learner.key)))
        c2 = self.reopen(c, adapter)
        report = c2.run_wave('cold')
        self.assertFalse([r for r in report['incomplete'] if r.startswith('plan_closed')], report['incomplete'])
        late = [r for r in c2._rows.values() if r.get('fallback_reason') == 'commit_refused:quarantined']
        self.assertEqual(len(late), report['audits']['population'])
        self.assertTrue(all(r['status'] in ('accepted', 'failed') and r['source'] == 'model' for r in late))
        self.assertTrue(any(a['round'] == 'r3' for a in c2.ledger.attempts('cold')))
        self.assertEqual(report['unresolved'], 0)

    def test_b5_a_replayed_round_settles_with_the_original_persisted_grants(self):
        adapter = oz_host.ReplayAdapter(th.extract)
        seen = []

        def crash(row):
            seen.append(row['id'])
            if len(seen) == 3:
                raise RuntimeError('host crashed while settling')

        a = self.host('A', adapter, hooks={'after_row': crash})
        a.submit('p0', 's0', th.producer_jobs(0, 10, None), wave='w')
        with self.assertRaisesRegex(RuntimeError, 'crashed'):
            a.run_wave('w')
        grants = a.ledger.grants('w', 'r1')
        rows_before = len(a.ledger.authority())
        a2 = self.reopen(a, adapter)
        report = a2.run_wave('w')
        self.assertEqual(report['accepted_by_checks'], 10)
        self.assertEqual(len(a2.ledger.authority()), rows_before)  # no new execution authority was claimed
        self.assertEqual(len(adapter.log), 1)
        for (job, _), generation in grants.items():
            s = a2.store.settlement(job)
            [emission] = [e for e in a2.store.emissions(job) if e['seq'] == s['emission']]
            self.assertEqual(emission['generation'], generation)  # settled under the ORIGINAL grant


# ------------------------------------------------------------------------------------------------------- B6

def plain(call, **over):
    return dict({k: call.get(k) for k in ('call_id', 'outcome', 'usage', 'elapsed_ms', 'jobs')}, **over)


class B6Accounting(th.Base):
    def ran(self):
        a = self.host('A', oz_host.ReplayAdapter(th.extract, samples=[FULL]))
        a.submit('p0', 's0', th.producer_jobs(0, 3, None), wave='w')
        a.run_wave('w')
        [attempt] = a.ledger.attempts('w')
        return a, attempt

    def test_b6_identity_and_membership_conflicts_are_hard_errors_whatever_the_usage(self):
        a, attempt = self.ran()
        call = attempt['calls'][0]
        with a.ledger.tx() as db:
            with self.assertRaisesRegex(Error, 'job membership differs'):
                a.ledger._attribute(db, attempt['attempt_id'], attempt['request_id'],
                                    [plain(call, usage=None, jobs=['someone-else'])])
            with self.assertRaisesRegex(Error, 'recorded under request'):
                a.ledger._attribute(db, attempt['attempt_id'], 'q-other', [plain(call, usage=None)])
            with self.assertRaisesRegex(Error, 'usage component differs'):
                a.ledger._attribute(db, attempt['attempt_id'], attempt['request_id'],
                                    [plain(call, usage={'input_tokens': 1})])

    def test_b6_compatible_observations_fold_into_an_auditable_resolved_view(self):
        a, attempt = self.ran()
        led = a.ledger
        first = {'call_id': 'cx', 'outcome': None, 'usage': None, 'elapsed_ms': None, 'jobs': ['j1']}
        with led.tx() as db:
            led._attribute(db, attempt['attempt_id'], 'q-x', [first])
            led._attribute(db, attempt['attempt_id'], 'q-x', [dict(first, outcome='accepted', elapsed_ms=12)])
        view = led.call('cx')
        self.assertEqual((view['outcome'], view['elapsed_ms'], view['usage']), ('accepted', 12, None))
        self.assertEqual(view['resolved_from'], {'outcome': 'core_ledger', 'elapsed_ms': 'core_ledger'})
        self.assertEqual(view['first']['outcome'], None)  # the first record is never rewritten
        status, owner = led.record_envelope(receipt='q-x/1', attempt_id=attempt['attempt_id'], request_id='q-x',
                                            call_id='cx', exit_code=1, raw=b'{"adapter":"codex_cli_adapter"}',
                                            evidence={'kind': 'codex', 'usage': dict(FULL), 'leakage': []}, at=0.0)
        self.assertEqual(status, 'folded')
        view = led.call('cx')
        self.assertEqual((view['usage'], view['usage_known']), (FULL, 1))
        self.assertEqual(view['resolved_from']['usage'], 'adapter_envelope:q-x/1')
        self.assertEqual([o['status'] for o in view['observations']], ['folded', 'folded'])
        with self.assertRaisesRegex(Error, 'differs from the one recorded first'):
            led.record_envelope(receipt='q-x/1', attempt_id=attempt['attempt_id'], request_id='q-x', call_id='cx',
                                exit_code=1, raw=b'{}', evidence={'kind': 'unknown', 'usage': None, 'leakage': []},
                                at=0.0)

    def test_b6_an_incompatible_observation_is_kept_and_fails_reconciliation(self):
        a, attempt = self.ran()
        call = attempt['calls'][0]
        with a.ledger.tx() as db:
            a.ledger._attribute(db, attempt['attempt_id'], attempt['request_id'], [plain(call, outcome='rewritten')])
        self.assertEqual([o['status'] for o in a.ledger.observations(call['call_id'])], ['conflict'])
        self.assertEqual(a.ledger.call(call['call_id'])['outcome'], call['outcome'])  # first record kept
        rec = a.reconcile('w')
        self.assertFalse(rec['ok'])
        self.assertTrue(any('conflicting observation' in p for p in rec['problems']))


# ------------------------------------------------------------------------------------------------------- B8

class B8Timing(th.Base):
    def test_b8_the_importer_is_charged_without_any_wait_subtraction(self):
        self.assertNotIn('bootstrap_wait', inspect.getsource(oz_host.ArmHost.report))
        b = self.host('B', oz_host.ReplayAdapter(th.extract, {'e': th.FIELD}))
        self.cold(b, missing=None)
        c_adapter = oz_host.ReplayAdapter(th.extract, {'e': th.FIELD})
        c = self.host('C', c_adapter)
        self.cold(c, missing=None)
        # The importer's own wait for the shared bootstrap stays inside its makespan: add a long recorded wait.
        c.ledger.phase('cold', 'bootstrap_wait', 'start', 0.0, None, 'other')
        c.ledger.phase('cold', 'bootstrap_wait', 'end', 500.0, None, 'other')
        c.close()
        self.hosts.remove(c)
        c2 = self.host('C', c_adapter)
        report = c2.run_wave('cold')
        self.assertTrue(report['bootstrap']['imported'])
        self.assertEqual(report['phase_seconds']['bootstrap_wait'], 500.0)
        self.assertAlmostEqual(report['charged_makespan_seconds'],
                               report['measured_makespan_seconds'] + report['bootstrap']['elapsed'], places=5)

    def test_b8_interrupted_spans_are_kept_and_closed_at_the_next_stamp(self):
        a = self.host('A', oz_host.ReplayAdapter(th.extract))
        led = a.ledger
        led.phase('w', 'bootstrap', 'start', 10.0, 1.0, 's1')  # session s1 died inside the bootstrap
        led.phase('w', 'x', 'start', 12.0, 3.0, 's1')
        led.phase('w', 'bootstrap', 'start', 20.0, 5.0, 's2')
        led.phase('w', 'bootstrap', 'end', 25.0, 10.0, 's2')
        led.phase('w', 'wave', 'start', 26.0, 11.0, 's2')  # still running in the current session
        spans = led.phase_spans('w', current='s2')
        self.assertEqual(sorted((s['phase'], s['interrupted'], s['seconds']) for s in spans),
                         [('bootstrap', False, 5.0), ('bootstrap', True, 10.0), ('x', True, 8.0)])
        self.assertEqual(led.phase_seconds('w', current='s2'), {'bootstrap': 15.0, 'x': 8.0})

    def test_b8_score_uses_the_inclusive_charged_makespan(self):
        report = {'tokens': {'charged': {'tokens': 10, 'input_tokens': 8, 'output_tokens': 2, 'usage': 'complete'}},
                  'charged_makespan_seconds': 100.0, 'measured_makespan_seconds': 60.0, 'calls': {'physical': 1,
                                                                                                    'charged': 2}}
        got = score.summarize(10, {'correct': 10, 'incorrect': 0, 'unresolved': 0}, rule_errors=0, fallback_errors=0,
                              rule_hits=0, report=report)
        self.assertEqual((got['makespan_s'], got['measured_makespan_s']), (100.0, 60.0))
        self.assertIn('nothing is subtracted', score.TIMING['charged_makespan'])
        self.assertNotIn('drops', json.dumps(score.TIMING))


# ------------------------------------------------------------------------------------------------------ B10

class B10Audits(th.Base):
    def test_b10_audit_completeness_reads_every_persisted_audit_row_of_the_wave(self):
        c = self.host('C', oz_host.ReplayAdapter(th.extract, {'e': th.FIELD}))
        self.cold(c)
        jobs = c._jobs('cold')
        rule = c.store.rules(c.learner.key)[0]['id']
        job = jobs[0]
        c.store.add_audits([{'audit_job': 'extra-audit', 'wave_id': rp.wave_id('fake', 'mat', 'cold'),
                             'original_job': job['name'], 'rule': rule, 'producer': job['producer'],
                             'submission': job['submission'], 'dataset_id': job['dataset_id'], 'rule_value': '"x"'}])
        # A restart after a quarantine has no active rule and so no current audit selection (notes['audits'] None).
        notes = {'bootstrap': None, 'audits': None, 'quarantine_fallbacks': 0, 'state': [], 'manifest_sha256': None}
        report = c.report('cold', jobs, notes)
        self.assertEqual(report['audits']['pending'], 1)
        self.assertEqual(report['audits']['selected'], len(c.store.audits(rp.wave_id('fake', 'mat', 'cold'))))
        self.assertGreater(report['audits']['population'], 0)
        self.assertIn('audits_unresolved', report['incomplete'])


# ------------------------------------------------------------------------------------------------------ B11

class B11Closure(Temp):
    def test_b11_the_closure_is_read_from_the_launched_interpreter(self):
        env = pilot.child_env('codex')
        rec = pilot.dependency_closure('codex', env)
        self.assertEqual(pilot.closure_problems(rec), [])
        program = shutil.which('python', path=env.get('PATH'))
        self.assertIsNotNone(program)
        files = {m[0]: m for m in rec['modules']}
        for name, path in (('codex_cli_adapter', REPO / 'examples' / 'codex_cli_adapter.py'),
                           ('bootstrap_shim', REPO / 'examples' / 'bootstrap_shim.py')):
            self.assertEqual(files[name][3], pilot._sha_file(path))
        self.assertEqual(files['json'][1], 'file')  # stdlib modules are hashed too, as the launched python sees them
        self.assertRegex(rec['executable_sha256'], r'^[0-9a-f]{64}$')
        self.assertTrue(rec['version'][0].isdigit())

    def test_b11_pilot_configs_refuse_unversioned_dependencies(self):
        frozen = dict(oz_host.identity_for(th.ROUTE), launch={'externals': [['json', 'stdlib', 'stdlib'],
                                                                            ['x', 'declared-external', 'unversioned']]})
        config = pilot.pilot_config('live', {'fake': frozen}, 'x')
        budget = oz_host.Budget(self.dir / 'b.sqlite', caps=config['caps'], global_cap=config['global_cap'])
        self.addCleanup(budget.close)
        with self.assertRaisesRegex(Error, 'unresolved or unversioned dependencies'):
            oz_host.check_pilot(config, backend='fake', budget=budget, slot_pool=oz_host.SlotPool(self.dir / 's', 4),
                                slots=4, max_records=64, max_wait=1.0, identity=frozen,
                                launcher=oz_host.ChildLauncher(self.dir / 'a.json'), limits=config['limits'],
                                route_check={'frozen': frozen, 'adapter': 'a.json'},
                                hooks={'launch_gate': lambda v: None}, quota=oz_host.QuotaStore(self.dir / 'q'))

    def test_b11_a_callable_route_check_never_runs_in_a_pilot(self):
        ran = []
        fake_self = types.SimpleNamespace(route_check=lambda env: ran.append(env), hooks={}, pilot={'mode': 'live'},
                                          worker='w')
        got = oz_host.ArmHost._verify_route(fake_self, {})
        self.assertTrue(got.startswith('route_unverified: a callable route check'))
        self.assertEqual(ran, [])

    def test_freeze_records_the_interpreter_and_needs_the_full_file_set(self):
        (self.dir / 'a.py').write_text('x = 1\n', encoding='utf-8')
        record = pilot.freeze_record(self.dir, ['a.py', 'gone.py'], datasets={'d': 'h'}, plan_obj={'p': 1})
        self.assertEqual(record['interpreter'], pilot.interpreter_record())
        self.assertEqual(record['interpreter']['version'], sys.version)
        problems = pilot.verify_freeze(record, self.dir, datasets={'d': 'h'}, plan_obj={'p': 1},
                                       files=['a.py', 'gone.py', 'b.py'])
        self.assertIn('b.py is missing from the freeze record', problems)
        self.assertIn('gone.py was absent at the freeze', problems)
        moved = dict(record, interpreter=dict(record['interpreter'], sha256='0' * 64))
        self.assertIn('the interpreter (path, sha256 or version) changed since the freeze',
                      pilot.verify_freeze(moved, self.dir, datasets={'d': 'h'}, plan_obj={'p': 1}, files=['a.py']))
        for rel in ('bench/ozmap/fake_cli.py', 'tests/test_ozmap_close.py',
                    'docs/design/ozmap-2026-10-24/council3-close-astra.md',
                    'docs/design/ozmap-2026-10-24/council3-close-opus.md'):
            self.assertIn(rel, pilot.FREEZE_FILES)


# ------------------------------------------------------------------------------------------------------ B12

class B12Leakage(unittest.TestCase):
    def test_b12_boolq_admission_is_separated_from_evaluation_by_id_text_and_passage(self):
        q = data.boolq()
        if not q['available']:
            self.skipTest('BoolQ file absent')
        jobs = [j for js in q['waves']['cold'].values() for j in js]
        passage = lambda t: t.split('\nquestion: ')[0]  # noqa: E731
        adm = [t for _, t, _, _ in q['admission']]
        self.assertEqual(len(adm), 64)
        self.assertFalse({j['text'] for j in jobs} & set(adm))
        self.assertFalse({passage(j['text']) for j in jobs} & {passage(t) for t in adm})
        self.assertEqual(pilot.leakage_problems(), [])

    def test_b12_the_assembled_prompts_are_scanned_for_hidden_material(self):
        mat = data.materials()
        admission = next(iter(mat['admission_texts'].values()))[0][1]
        self.assertEqual(pilot.prompt_leakage([{'text': 'clean prompt', 'bootstrap': True}]), [])
        self.assertEqual(pilot.prompt_leakage([{'text': 'x ' + shim.HIDDEN_ASTS[0], 'bootstrap': True}]),
                         ['a worked AST is in a bootstrap prompt'])
        self.assertEqual(pilot.prompt_leakage([{'text': 'y ' + pilot.oracle.resolve(admission)}]),
                         ['a materials admission text is in a ordinary prompt'])
        q = data.boolq()
        if q['available']:
            passage = q['admission'][0][1].split('\nquestion: ')[0]
            self.assertEqual(pilot.prompt_leakage([{'text': passage, 'bootstrap': False}]),
                             ['a BoolQ admission passage is in a ordinary prompt'])


# ---------------------------------------------------------------------------------------------- Opus extras

class OpusExtras(th.Base):
    def test_every_child_gets_its_own_envelope_path(self):
        adapter = LeakyAdapter(tool=None)
        a = self.host('A', None, launcher=oz_host.InProcessLauncher(adapter))
        a.submit('p0', 's0', th.producer_jobs(0, 70, None), wave='w')
        report = a.run_wave('w')
        self.assertEqual(report['accepted_by_checks'], 70)
        attempts = {a_['attempt_id'] for a_ in a.ledger.attempts('w')}
        self.assertEqual(len(adapter.seen), 2)
        self.assertEqual(len(set(adapter.seen)), 2)
        for path in adapter.seen:
            self.assertEqual(Path(path).name, 'adapter-envelope.json')
            self.assertIn(Path(path).parent.name, attempts)
            self.assertTrue(Path(path).parent.is_relative_to(a.arm_dir / 'attempts'))

    def test_a_failed_codex_call_keeps_its_usage_from_its_envelope(self):
        a = self.host('A', None, launcher=oz_host.InProcessLauncher(LeakyAdapter(tool=None, fail=True)))
        a.submit('p0', 's0', th.producer_jobs(0, 3, None), wave='w')
        report = a.run_wave('w')
        self.assertEqual(report['accepted_by_checks'], 0)
        [attempt] = a.ledger.attempts('w')
        [call] = attempt['calls']
        self.assertIsNone(call['first']['usage'])  # the core ledger has no usage for the failed call
        self.assertEqual(call['usage']['input_tokens'], 900)  # its envelope keeps it
        self.assertTrue(call['resolved_from']['usage'].startswith('adapter_envelope:attempt:'))
        self.assertEqual(report['tokens']['charged']['usage'], 'complete')
        self.assertEqual(report['tokens']['physical']['tokens'], 920)


if __name__ == '__main__':
    unittest.main()
