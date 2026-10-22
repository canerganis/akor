"""Portable on-disk workspaces. Configuration never executes an adapter implicitly."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys
import uuid

from oz import Atom, Channel, Codebook, Error, Macro, Reference
from oz_batch import valid_id
from oz_runtime import Inbox
from oz_worker import StdioAdapter, Worker, loads, process_host


def approximate_tokens(text):
    """Upper estimate when tiktoken is absent: one token per 3 UTF-8 bytes (o200k averages about 4 on JSON),
    so packet budgets stay on the safe side. Install akor-protocol[benchmark] for exact counts."""
    return len(text.encode('utf-8', 'surrogatepass')) // 3 + 1


def token_counters(names):
    try:
        import tiktoken
    except ImportError:
        return (approximate_tokens,)
    encodings = [tiktoken.get_encoding(name) for name in names]
    return tuple(lambda text, enc=enc: len(enc.encode(text, disallowed_special=())) for enc in encodings)


def default_channel():
    return Channel(session='s-' + uuid.uuid4().hex, task='demo', revision=1, sender='lead', recipient='worker',
                   goal='DEMO only: read supplied data, retain uncertainty, propose a plan. Do not execute tools.',
                   active=1, references=[Reference(1, 'source', 'DEMO: 12.50 ± 0.02 mm; method unknown.'),
                                         Reference(2, 'proposal', 'DEMO: ask for the measurement method before concluding.'),
                                         Reference(3, 'reason', 'DEMO: measurement method unavailable.')],
                   codebook=Codebook([Macro('P', (Atom('r', 0), Atom('>', 2)))]))


def read_utf8(path: Path) -> str:
    # read_text() performs universal-newline translation; payloads must not.
    return path.read_bytes().decode('utf-8')


def channel_from_files(goal: str, source: Path, *, kind='source', procedure: Path | None = None):
    if kind not in {'source', 'patch'}:
        raise Error('Source kind must be source or patch')
    def reference(number, ref_kind, path):
        data = path.read_bytes()
        return Reference(number, ref_kind, data.decode('utf-8'),
                         str(path.resolve()) + '@sha256:' + hashlib.sha256(data).hexdigest())
    refs = [reference(1, kind, source)]
    steps = [Atom('r', 0)]
    if kind == 'patch':
        steps.append(Atom('a', 0))
    if procedure is not None:
        refs.append(reference(2, 'procedure', procedure))
        steps.append(Atom('t', 2))
    macros = [Macro('V', tuple(steps))] if len(steps) >= 2 else []
    return Channel(session='s-' + uuid.uuid4().hex, task='main', revision=1, sender='lead',
                   recipient='worker', goal=goal, active=1, references=refs, codebook=Codebook(macros))


def initialize(path: Path, channel: Channel | None = None):
    root = path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise Error('The target directory must be empty; existing files are never overwritten')
    channel = channel or default_channel()
    reviewer = channel.snapshot()
    reviewer['recipient'] = 'reviewer'
    config = dict(version=1, channels={'worker': channel.snapshot(), 'reviewer': reviewer},
                  encodings=['o200k_base'], max_tokens=2048, batch_size=64)
    with (root / 'oz.json').open('x', encoding='utf-8') as file:
        json.dump(config, file, ensure_ascii=False, indent=2)
        file.write('\n')
    (root / '.gitignore').write_text('inbox.sqlite*\n', encoding='utf-8')
    start_wire = 'V' if 'V' in channel.codebook.macros else 'P' if 'P' in channel.codebook.macros else 'r'
    try:
        channel.accept(start_wire, binding=channel.binding)
    except Error:
        start_wire = 'r'
    (root / 'START.md').write_text(
        '# AKOR workspace\n\nRun these in this directory:\n\n'
        f'```text\noz send {start_wire} --id first\noz send r{channel.active} --to reviewer --id check --after first\n'
        'oz plan\noz status\n```\n\n'
        'For a real agent, choose the JSON stdin/stdout adapter explicitly:\n\n'
        '`oz run --adapter adapter.json`\n\n'
        'adapter.json: {"argv":["python","worker.py"],"protocols":["oz.adapter/3"],"languages":["OZ/9"]}\n'
        'The adapter passes the prompt to the model and returns {"reply":...,"usage":...} (see OZ9.md).\n'
        "The command runs in the adapter file's directory. oz init never runs an adapter.\n"
        'oz.json holds the channels, the target tokenizer, the input budget and the batch size.\n'
        'For a new source or codebook, add a channel: oz channel-add new-channel channel.json\n'
        'To see the result of a finished job: oz inspect first\n', encoding='utf-8')
    with Inbox(root / 'inbox.sqlite'):
        pass
    return Workspace(root)


def adapter_from_file(adapter_path: Path, *, timeout: float = 120) -> StdioAdapter:
    """The explicit adapter JSON file: argv, protocols and languages; the command runs in the file's directory."""
    adapter_path = Path(adapter_path).resolve()
    spec = loads(adapter_path.read_text(encoding='utf-8'))
    if (not isinstance(spec, dict) or set(spec) != {'argv', 'protocols', 'languages'}
            or not isinstance(spec['argv'], list)):
        raise Error('The adapter file must contain argv, protocols and languages (oz.adapter/3, OZ/9)')
    return StdioAdapter(tuple(spec['argv']), cwd=adapter_path.parent, timeout=timeout,
                        capabilities={k: spec[k] for k in ('protocols', 'languages')})


class Workspace:
    def __init__(self, path: Path):
        self.root = path.resolve()
        try:
            self.config = loads((self.root / 'oz.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise Error('Workspace not found; run oz init DIRECTORY first') from None
        value = self.config
        if (not isinstance(value, dict) or set(value) != {'version', 'channels', 'encodings', 'max_tokens', 'batch_size'}
                or type(value['version']) is not int or value['version'] != 1
                or not isinstance(value['channels'], dict) or not 1 <= len(value['channels']) <= 32
                or any(not valid_id(name) for name in value['channels'])
                or not isinstance(value['encodings'], list) or not 1 <= len(value['encodings']) <= 4
                or any(not isinstance(n, str) or not n for n in value['encodings'])
                or type(value['max_tokens']) is not int or not 1 <= value['max_tokens'] <= 1000000
                or type(value['batch_size']) is not int or not 1 <= value['batch_size'] <= 64):
            raise Error('Invalid oz.json configuration')
        self.channels = {name: Channel.from_snapshot(snapshot) for name, snapshot in value['channels'].items()}

    def channel(self, name='worker'):
        if name not in self.channels:
            raise Error('Channel not found: ' + name)
        return self.channels[name]

    def inbox(self):
        path = self.root / 'inbox.sqlite'
        if not path.exists():
            raise Error('Queue file not found; an empty queue is not created silently')
        return Inbox(path)

    def counters(self):
        return token_counters(self.config['encodings'])

    def add_channel(self, name: str, channel: Channel):
        if not valid_id(name) or name in self.channels or len(self.channels) >= 32:
            raise Error('A new, valid channel name is required (at most 32 channels)')
        # Serialize CLI configuration writers using the workspace database lock.
        # A stale in-memory config must never replace another writer's additions.
        with self.inbox() as box:
            with box._transaction():
                self._add_channel_locked(name, channel)

    def _add_channel_locked(self, name, channel):
        config_path = self.root / 'oz.json'
        current = loads(config_path.read_text(encoding='utf-8'))
        if current != self.config:
            raise Error('Configuration changed; reload it')
        updated = dict(current, channels=dict(current['channels'], **{name: channel.snapshot()}))
        temp = self.root / ('oz-' + uuid.uuid4().hex + '.tmp')
        assert temp.resolve().parent == self.root and config_path.resolve().parent == self.root
        try:
            with temp.open('x', encoding='utf-8') as file:
                json.dump(updated, file, ensure_ascii=False, indent=2)
                file.write('\n')
            os.replace(temp, config_path)
        finally:
            if temp.exists():
                temp.unlink()

    def plan(self, box, name='worker', *, max_tokens=None, context_policy='needed'):
        # A preview shows the receipt the next attempt will get; the run is planned and measured again.
        return box.plan(self.channel(name), counters=self.counters(), limit=self.config['batch_size'],
                        max_tokens=max_tokens if max_tokens is not None else self.config['max_tokens'],
                        receipt=box.next_receipt(), context_policy=context_policy)

    def run(self, name, adapter_path, *, max_calls=1, max_tokens=None, timeout=120, context_policy='needed',
            min_batch=1, max_wait=0):
        if type(max_calls) is not int or not 1 <= max_calls <= 100:
            raise Error('max_calls must be 1..100')
        adapter = adapter_from_file(adapter_path, timeout=timeout)
        results = []
        counters = self.counters()
        with self.inbox() as box:
            worker = Worker(box, self.channel(name), adapter, counters=counters, owner=name,
                            batch_size=self.config['batch_size'], timeout=timeout,
                            max_tokens=max_tokens if max_tokens is not None else self.config['max_tokens'],
                            context_policy=context_policy, min_batch=min_batch, max_wait=max_wait,
                            ledger_path=self.root / 'calls.jsonl', tokenizer=self.config['encodings'][0])
            calls = 0
            while calls < max_calls:
                result = worker.run_once()
                results.append(result)
                if (result['status'] not in ('received', 'host_completed')
                        or any(v == 'retry' for v in result.get('outcomes', {}).values())):
                    break
                # Host-completed batches make no adapter call and do not use up max_calls.
                calls += result.get('adapter_calls', 1)
        return results


DEMO_SCRIPT = (
    'import json,sys; r=json.load(sys.stdin); m="DEMO receipt only; no model or task execution."; '
    'json.dump({"reply":"OZ/1g\\n"+"\\n".join(json.dumps({row[0]:m}) for block in json.loads(r["prompt"])["jobs"] for row in block[1:])},sys.stdout)'
)
DEMO_CAPABILITIES = {'protocols': ['oz.adapter/3'], 'languages': ['OZ/9']}


def demo(path: Path):
    counters = token_counters(['o200k_base'])
    workspace = initialize(path)
    worker, reviewer = workspace.channel(), workspace.channel('reviewer')
    adapter = StdioAdapter((sys.executable, '-c', DEMO_SCRIPT), timeout=10, capabilities=DEMO_CAPABILITIES)
    with workspace.inbox() as box:
        box.post(worker, 'read', 'r1', binding=worker.binding)
        box.post(worker, 'propose', 'P', binding=worker.binding)
        box.post(reviewer, 'review', 'r1', binding=reviewer.binding, after=['read', 'propose'])
        box.post(worker, 'notice', '!3', binding=worker.binding)
        before = box.plan(reviewer, counters=counters)
        options = dict(counters=counters, timeout=10, ledger_path=workspace.root / 'calls.jsonl',
                       tokenizer='o200k_base')
        first = Worker(box, worker, adapter, **options).run_once()
        second = Worker(box, reviewer, adapter, **options).run_once()
        host = process_host(box, worker)
        return dict(workspace=str(workspace.root), actual_model_calls=0,
                    reviewer_initially_waited=not before.jobs, worker=first, reviewer=second,
                    host=host, states=box.stats())
