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


def token_counters(names):
    try:
        import tiktoken
    except ImportError:
        raise Error('Token ölçümü için kur: python -m pip install "akor-protocol[benchmark]"') from None
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
        raise Error('Kaynak türü source veya patch olmalı')
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
        raise Error('Başlangıç klasörü boş olmalı; mevcut dosyaların üzerine yazılmaz')
    channel = channel or default_channel()
    reviewer = channel.snapshot()
    reviewer['recipient'] = 'reviewer'
    config = dict(version=1, channels={'worker': channel.snapshot(), 'reviewer': reviewer},
                  encodings=['o200k_base'], max_tokens=2048, batch_size=16)
    with (root / 'oz.json').open('x', encoding='utf-8') as file:
        json.dump(config, file, ensure_ascii=False, indent=2)
        file.write('\n')
    (root / '.gitignore').write_text('inbox.sqlite*\n', encoding='utf-8')
    start_wire = 'V' if 'V' in channel.codebook.macros else 'P' if 'P' in channel.codebook.macros else 'r'
    try:
        channel.accept(start_wire, binding=channel.binding)
    except Error:
        start_wire = 'r'
    (root / 'BASLANGIC.md').write_text(
        '# ÖZ çalışma alanı\n\nBu klasörde çalıştır:\n\n'
        f'```text\noz send {start_wire} --id ilk\noz send r{channel.active} --to reviewer --id kontrol --after ilk\n'
        'oz plan\noz status\n```\n\n'
        'Gerçek ajan için JSON stdin/stdout adaptörünü açıkça seç:\n\n'
        '`oz run --adapter adapter.json`\n\n'
        'adapter.json: {"argv":["python","worker.py"],"protocols":["oz.adapter/3"],"languages":["OZ/9"]}\n'
        'Adaptör istemi modele iletir, {"reply":...,"usage":...} döndürür (OZ9.md).\n'
        'Komut çalışma dizini adaptör dosyasının klasörüdür. oz init hiçbir adaptör çalıştırmaz.\n'
        'oz.json içinde kanallar, hedef tokenizer, girdi bütçesi ve paket büyüklüğü bulunur.\n'
        'Yeni kaynak/sözlük için yeni kanal ekle: oz channel-add yeni kanal.json\n'
        'Tamamlanan işin sonucunu görmek için: oz inspect ilk\n', encoding='utf-8')
    with Inbox(root / 'inbox.sqlite'):
        pass
    return Workspace(root)


class Workspace:
    def __init__(self, path: Path):
        self.root = path.resolve()
        try:
            self.config = loads((self.root / 'oz.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise Error('Çalışma alanı bulunamadı; önce oz init KLASOR çalıştır') from None
        value = self.config
        if (not isinstance(value, dict) or set(value) != {'version', 'channels', 'encodings', 'max_tokens', 'batch_size'}
                or type(value['version']) is not int or value['version'] != 1
                or not isinstance(value['channels'], dict) or not 1 <= len(value['channels']) <= 32
                or any(not valid_id(name) for name in value['channels'])
                or not isinstance(value['encodings'], list) or not 1 <= len(value['encodings']) <= 4
                or any(not isinstance(n, str) or not n for n in value['encodings'])
                or type(value['max_tokens']) is not int or not 1 <= value['max_tokens'] <= 1000000
                or type(value['batch_size']) is not int or not 1 <= value['batch_size'] <= 64):
            raise Error('Geçersiz oz.json yapılandırması')
        self.channels = {name: Channel.from_snapshot(snapshot) for name, snapshot in value['channels'].items()}

    def channel(self, name='worker'):
        if name not in self.channels:
            raise Error('Kanal bulunamadı: ' + name)
        return self.channels[name]

    def inbox(self):
        path = self.root / 'inbox.sqlite'
        if not path.exists():
            raise Error('Kuyruk dosyası bulunamadı; boş kuyruk sessizce oluşturulmadı')
        return Inbox(path)

    def counters(self):
        return token_counters(self.config['encodings'])

    def add_channel(self, name: str, channel: Channel):
        if not valid_id(name) or name in self.channels or len(self.channels) >= 32:
            raise Error('Yeni, geçerli bir kanal adı gerekiyor (en fazla 32 kanal)')
        # Serialize CLI configuration writers using the workspace database lock.
        # A stale in-memory config must never replace another writer's additions.
        with self.inbox() as box:
            with box._transaction():
                self._add_channel_locked(name, channel)

    def _add_channel_locked(self, name, channel):
        config_path = self.root / 'oz.json'
        current = loads(config_path.read_text(encoding='utf-8'))
        if current != self.config:
            raise Error('Yapılandırma değişti; yeniden yükle')
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
        adapter_path = adapter_path.resolve()
        spec = loads(adapter_path.read_text(encoding='utf-8'))
        if (not isinstance(spec, dict) or set(spec) != {'argv', 'protocols', 'languages'}
                or not isinstance(spec['argv'], list)):
            raise Error('Adaptör dosyası argv, protocols ve languages içermeli (oz.adapter/3, OZ/9)')
        adapter = StdioAdapter(tuple(spec['argv']), cwd=adapter_path.parent, timeout=timeout,
                               capabilities={k: spec[k] for k in ('protocols', 'languages')})
        results = []
        counters = self.counters()
        with self.inbox() as box:
            worker = Worker(box, self.channel(name), adapter, counters=counters, owner=name,
                            batch_size=self.config['batch_size'], timeout=timeout,
                            max_tokens=max_tokens if max_tokens is not None else self.config['max_tokens'],
                            context_policy=context_policy, min_batch=min_batch, max_wait=max_wait)
            for _ in range(max_calls):
                result = worker.run_once()
                results.append(result)
                if result['status'] != 'received' or any(v == 'retry' for v in result.get('outcomes', {}).values()):
                    break
        return results


DEMO_SCRIPT = (
    'import json,sys; r=json.load(sys.stdin); '
    'json.dump({"reply":{"results":["DEMO receipt only; no model or task execution." for i in r["ids"]]}},sys.stdout)'
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
        first = Worker(box, worker, adapter, counters=counters, timeout=10).run_once()
        second = Worker(box, reviewer, adapter, counters=counters, timeout=10).run_once()
        host = process_host(box, worker)
        return dict(workspace=str(workspace.root), actual_model_calls=0,
                    reviewer_initially_waited=not before.jobs, worker=first, reviewer=second,
                    host=host, states=box.stats())
