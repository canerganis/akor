"""P5 request boundary probe: the frozen exec argv of the harness, no auth.json, with the built in provider's base URL
pointed at a localhost capture server (-c openai_base_url=...). Every request the CLI makes to that server is captured
in full (method, path, headers with credential values replaced by <present>, body). All other traffic is routed to a
localhost refusing proxy through HTTP(S)_PROXY / ALL_PROXY (NO_PROXY covers loopback), and the process tree's TCP
connections are polled; any non loopback remote endpoint is recorded. No model is ever called: the capture server
answers the model request with an error.

usage: python boundary.py <out_dir> <label> [extra argv items inserted before '-' ...]

Live transport (blocker OB-P5b, fix 2). P5_WS=accept (the default) makes the capture server accept the WebSocket
upgrade of GET /v1/responses (RFC 6455 handshake, no extension negotiated, so frames are uncompressed) and record every
client frame in full; it answers the first text frame with an error event and closes the connection. P5_WS=refuse
answers the upgrade with 404 as before, so the CLI falls back to POST /v1/responses over HTTP.

Model metadata (fix 1). P5_MODELS=canary (the default) answers GET /v1/models with the pinned catalog
(bench/ozmap_rep/model-catalog.json) in which every instruction template of the frozen model starts with CANARY, so a
request that used the /models answer carries the canary. P5_MODELS=404 answers 404 as before. P5_UNPIN=1 removes the
model_catalog_json pin from the frozen argv (control: shows what a live /models answer does without the pin).

Environment: P5_SCRAMBLED=1 prepares the worker home with Isolation.prepare(scrambled=True) (baseline account
metadata, tokens no server accepts) and also points chatgpt_base_url at the capture server; the bearer of every
captured request is classified against the prepared and the baseline tokens in memory, and every credential string is
replaced before the record is written. P5_PROMPT replaces the stdin prompt. Diagnostics only (not used for the
annexes): P5_ENABLE=<f1,f2> drops those --disable pairs, P5_MODEL_OVERRIDE=<model> replaces the -m value."""
import base64
import datetime as dt
import hashlib
import http.server
import json
import os
import shutil
import socketserver
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

REPO = Path(r'C:\Users\can02\Projects\akor')
sys.path.insert(0, str(REPO))
from bench.ozmap_rep import config, isolation, run  # noqa: E402

OUT = Path(sys.argv[1])
LABEL = sys.argv[2]
EXTRA = sys.argv[3:]
OUT.mkdir(parents=True, exist_ok=True)
captured, proxied = [], []
REDACT = {'authorization', 'cookie', 'chatgpt-account-id', 'openai-organization', 'x-api-key'}
WS_MODE = os.environ.get('P5_WS', 'accept')
MODELS_MODE = os.environ.get('P5_MODELS', 'canary')
CANARY = 'P5_MODELS_CANARY_91c2 '
WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


def canary_catalog():
    doc = json.loads(Path(config.MODEL_CATALOG_FILE).read_text(encoding='utf-8'))
    for m in doc['models']:
        if m.get('slug') != config.CODEX_MODEL:
            continue
        mm = m.get('model_messages') or {}
        if isinstance(mm.get('instructions_template'), str):
            mm['instructions_template'] = CANARY + mm['instructions_template']
        if isinstance(m.get('base_instructions'), str):
            m['base_instructions'] = CANARY + m['base_instructions']
        m['description'] = CANARY + str(m.get('description') or '')
    return json.dumps(doc).encode('utf-8')


CANARY_BODY = canary_catalog()


def ws_send(wfile, opcode, payload):
    n = len(payload)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack('>H', n)
    else:
        head += bytes([127]) + struct.pack('>Q', n)
    wfile.write(head + payload)
    wfile.flush()


def ws_read(rfile):
    """One frame: (fin, opcode, payload) or None at end of stream. Client frames are masked (RFC 6455 5.3)."""
    hdr = rfile.read(2)
    if len(hdr) < 2:
        return None
    fin, opcode = bool(hdr[0] & 0x80), hdr[0] & 0x0F
    masked, n = bool(hdr[1] & 0x80), hdr[1] & 0x7F
    if n == 126:
        n = struct.unpack('>H', rfile.read(2))[0]
    elif n == 127:
        n = struct.unpack('>Q', rfile.read(8))[0]
    mask = rfile.read(4) if masked else b'\0\0\0\0'
    data = rfile.read(n)
    if masked:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return fin, opcode, data


class Capture(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _bearer(self):
        bearer = None
        for k, v in self.headers.items():
            if k.lower() == 'authorization':
                tok = v.split(' ', 1)[1] if ' ' in v else v
                bearer = ('prepared_access_token' if tok == PREPARED.get('access') else
                          'baseline_token' if tok in BASELINE_TOKENS else 'other')
        return bearer

    def _rec(self, body, **extra):
        rec = {'method': self.command, 'path': self.path, 'bearer_source': self._bearer(),
               'headers': {k: ('<present>' if k.lower() in REDACT else v) for k, v in self.headers.items()},
               'body': body.decode('utf-8', errors='replace'), 'body_b64': base64.b64encode(body).decode(),
               'at': time.time()}
        rec.update(extra)
        captured.append(rec)
        return rec

    def _reply(self, code, obj=None, raw=None):
        data = raw if raw is not None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n) if n else b''
        if not n and self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
            parts = []
            while True:
                size = int(self.rfile.readline().strip() or b'0', 16)
                if size == 0:
                    self.rfile.readline()
                    break
                parts.append(self.rfile.read(size))
                self.rfile.readline()
            body = b''.join(parts)
        self._rec(body)
        self._reply(400, {'error': {'message': 'p5 boundary probe: request captured, no model call',
                                    'type': 'invalid_request_error', 'code': 'p5_probe'}})

    def _websocket(self):
        key = self.headers.get('Sec-WebSocket-Key') or ''
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        rec = self._rec(b'', websocket='accepted', ws_frames=[])
        self.send_response(101, 'Switching Protocols')
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', accept)
        self.end_headers()
        self.wfile.flush()
        self.connection.settimeout(15)
        message, answered = b'', False
        try:
            while True:
                frame = ws_read(self.rfile)
                if frame is None:
                    break
                fin, opcode, data = frame
                rec['ws_frames'].append({'opcode': opcode, 'fin': fin, 'bytes': len(data), 'at': time.time(),
                                         'text': data.decode('utf-8', 'replace') if opcode in (0, 1) else None,
                                         'b64': base64.b64encode(data).decode() if opcode not in (0, 1) else None})
                if opcode == 8:
                    ws_send(self.wfile, 8, data[:2])
                    break
                if opcode == 9:
                    ws_send(self.wfile, 10, data)
                    continue
                if opcode in (0, 1):
                    message += data
                    if fin and not answered:
                        answered = True
                        rec['ws_first_message'] = message.decode('utf-8', 'replace')
                        err = {'type': 'error', 'status': 400,
                               'error': {'type': 'invalid_request_error', 'code': 'p5_probe',
                                         'message': 'p5 boundary probe: frame captured, no model call'}}
                        ws_send(self.wfile, 1, json.dumps(err).encode())
                        ws_send(self.wfile, 8, struct.pack('>H', 1008) + b'p5 probe')
                    if fin:
                        message = b''
        except (OSError, ValueError) as exc:
            rec['ws_end'] = repr(exc)[:200]
        self.close_connection = True

    def do_GET(self):
        if self.headers.get('Upgrade', '').lower() == 'websocket' and WS_MODE == 'accept':
            return self._websocket()
        if self.path.split('?')[0].endswith('/models') and MODELS_MODE == 'canary':
            self._rec(b'', models_answer='canary_catalog', models_answer_sha256=hashlib.sha256(CANARY_BODY).hexdigest())
            return self._reply(200, raw=CANARY_BODY)
        self._rec(b'')
        self._reply(404, {'error': {'message': 'p5 boundary probe', 'type': 'not_found'}})

    def log_message(self, *a):
        pass


class Refuse(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline(4096).decode('latin-1', errors='replace').strip()
        proxied.append({'request_line': line, 'at': time.time()})
        self.wfile.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')


class TS(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


class TP(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True


cap = TS(('127.0.0.1', 0), Capture)
prx = TP(('127.0.0.1', 0), Refuse)
for s in (cap, prx):
    threading.Thread(target=s.serve_forever, daemon=True).start()
cport, pport = cap.server_address[1], prx.server_address[1]

stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
root = Path('C:/ozmap_rep/annex-probes') / f'p5-{LABEL}-{stamp}'
iso = isolation.Isolation(baseline=config.BASELINE_DEFAULT, root=root, evidence=root / 'evidence',
                          base_env=dict(os.environ))
SCRAMBLED = os.environ.get('P5_SCRAMBLED') == '1'
SECRETS = set()
PREPARED, BASELINE_TOKENS = {}, set()
if SCRAMBLED:
    prep = iso.prepare(0, scrambled=True)
    SECRETS = set(prep['secrets'])
    _doc = json.loads((Path(prep['home']) / 'auth.json').read_text(encoding='utf-8'))
    PREPARED['access'] = (_doc.get('tokens') or {}).get('access_token')
    _base = json.loads((config.BASELINE_DEFAULT / 'auth.json').read_text(encoding='utf-8'))
    BASELINE_TOKENS = {v for v in (_base.get('tokens') or {}).values() if isinstance(v, str)}
    home, work = Path(prep['home']), Path(prep['workdir'])
    assert os.listdir(home) == ['auth.json'] and os.listdir(work) == []
else:
    home = iso.empty_home(0)
    work = iso.workdir(0)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    assert os.listdir(home) == [] and os.listdir(work) == []
exe = shutil.which('codex')
disable_args, unsupported = run.cli_flags()
argv = isolation.codex_argv(exe, config.CODEX_MODEL, config.CODEX_EFFORT, work, disable_args)
frozen_problems = isolation.argv_check(argv)
frozen_argv = list(argv)
if os.environ.get('P5_UNPIN') == '1':
    _k = [i for i in range(len(argv) - 1) if argv[i] == '-c' and argv[i + 1].startswith('model_catalog_json=')][0]
    del argv[_k:_k + 2]
for _f in filter(None, os.environ.get('P5_ENABLE', '').split(',')):
    _k = [i for i in range(len(argv) - 1) if argv[i] == '--disable' and argv[i + 1] == _f][0]
    del argv[_k:_k + 2]
if os.environ.get('P5_MODEL_OVERRIDE'):
    argv[argv.index('-m') + 1] = os.environ['P5_MODEL_OVERRIDE']
probe_args = ['-c', f'openai_base_url="http://127.0.0.1:{cport}/v1"', *EXTRA]
if SCRAMBLED:
    probe_args[2:2] = ['-c', f'chatgpt_base_url="http://127.0.0.1:{cport}/backend-api/"']
argv = argv[:-1] + probe_args + ['-']
env = isolation.child_env(home, os.environ)
purl = f'http://127.0.0.1:{pport}'
env.update({'HTTPS_PROXY': purl, 'HTTP_PROXY': purl, 'ALL_PROXY': purl, 'https_proxy': purl, 'http_proxy': purl,
            'all_proxy': purl, 'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost'})
PROMPT = os.environ.get('P5_PROMPT') or 'HARNESS_INPUT_MARKER_7f3a p5 boundary probe'
remote, seen_pids = set(), set()
t0 = time.time()
proc = subprocess.Popen(argv, cwd=work, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
done = threading.Event()


def poll():
    while not done.is_set():
        try:
            top = psutil.Process(proc.pid)
            tree = [top] + top.children(recursive=True)
        except psutil.Error:
            tree = []
        for p in tree:
            seen_pids.add(p.pid)
            try:
                for c in p.net_connections(kind='inet'):
                    if c.raddr and c.raddr.ip not in ('127.0.0.1', '::1'):
                        remote.add((c.raddr.ip, c.raddr.port, c.status))
            except psutil.Error:
                pass
        time.sleep(0.02)


th = threading.Thread(target=poll, daemon=True)
th.start()
try:
    out, err = proc.communicate(PROMPT.encode('utf-8'), timeout=300)
except subprocess.TimeoutExpired:
    proc.kill()
    out, err = proc.communicate()
done.set()
th.join()
elapsed = time.time() - t0
time.sleep(0.5)
cap.shutdown()
prx.shutdown()


def inventory(d):
    res = []
    for p in sorted(Path(d).rglob('*')):
        rel = p.relative_to(d).as_posix()
        kind = 'symlink' if p.is_symlink() else 'dir' if p.is_dir() else 'file' if p.is_file() else 'other'
        e = {'path': rel, 'type': kind}
        if kind == 'file':
            e['sha256'] = isolation.sha256_file(p)
            e['bytes'] = p.stat().st_size
        res.append(e)
    return res


rec = {'label': LABEL, 'at': stamp, 'exe': exe, 'exe_identity_sha256': isolation.executable_identity(exe)['sha256'],
       'frozen_argv_check_before_probe_args': frozen_problems, 'probe_args': probe_args,
       'frozen_argv': [Path(exe).name, *frozen_argv[1:]], 'argv': [Path(exe).name, *argv[1:]],
       'unpinned': os.environ.get('P5_UNPIN') == '1', 'ws_mode': WS_MODE, 'models_mode': MODELS_MODE,
       'canary': CANARY, 'canary_catalog_sha256': hashlib.sha256(CANARY_BODY).hexdigest(),
       'model_catalog_sha256': isolation.sha256_file(config.MODEL_CATALOG_FILE),
       'workdir': str(work), 'home': str(home),
       'exit_code': proc.returncode, 'elapsed_s': round(elapsed, 2), 'stdout': out.decode('utf-8', 'replace'),
       'stderr': err.decode('utf-8', 'replace'), 'captured': captured, 'proxied': proxied,
       'non_loopback_connections': sorted(map(list, remote)), 'pids_seen': len(seen_pids),
       'home_after': inventory(home), 'workdir_after': inventory(work), 'prompt': PROMPT,
       'auth_json_present_after': (home / 'auth.json').exists()}
text = json.dumps(rec, indent=1)
for sec in sorted(SECRETS, key=len, reverse=True):
    if sec and len(sec) >= 8:
        text = text.replace(sec, '<secret>')
        text = text.replace(json.dumps(sec)[1:-1], '<secret>')
rec_secret_free = not any(sec and len(sec) >= 8 and sec in text for sec in SECRETS)
assert rec_secret_free
(OUT / f'{LABEL}.json').write_text(text, encoding='utf-8')
print(LABEL, 'exit', proc.returncode, 'elapsed', round(elapsed, 1), 'captured', len(captured),
      [(c['method'], c['path'], len(c['body']), len(c.get('ws_frames') or [])) for c in captured],
      'proxied', proxied, 'remote', sorted(remote))
shutil.rmtree(root, ignore_errors=True)
