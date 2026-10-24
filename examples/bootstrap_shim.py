"""oz.adapter/3 wrapper for the fused oz-rule/1 bootstrap (signed record section 3; amendments 1 and 2; council 2).

Usage in an adapter JSON: {"argv": ["python", "bootstrap_shim.py", "<real adapter script>", ...]}. The shim has the
same stdin/stdout contract as every adapter: one oz.adapter/3 request on stdin, one {"reply", "usage"?} JSON on
stdout. The real adapter (claude_map_adapter.py, codex_cli_adapter.py or any other script) runs as a child process, so
OZ_MODEL, OZ_EFFORT and the runner's OZ_ENVELOPE_PATH reach it unchanged. Standard library only; nothing in the AKOR
core changes.

Enablement. The shim is enabled by the CHILD process environment of one physical call and by nothing else:
OZ_BOOTSTRAP_ATTEMPT=<attempt id> and OZ_BOOTSTRAP_DIR=<directory>. A call without both is a pure passthrough: the
request bytes go to the real adapter unchanged and its stdout, stderr and exit code come back unchanged. The attempt id
is allocated by the host per physical call (letters, digits, dot, underscore, hyphen; at most 128 characters).

Files in OZ_BOOTSTRAP_DIR, all named by the attempt id:
  <id>.config.json  written by the host before the launch (else config.json in the directory): exactly
                    {"schema": "oz.bootstrap.config/2", "ops": [...], "contracts": {op: ...}, "eligibility": {op: bool}}
  <id>.claim        created with O_EXCL by the shim; the one process that creates it carries the bootstrap. A second
                    process with the same id launches nothing, writes nothing and exits 75 (every launch costs budget).
  <id>.capture.json the complete raw evidence of the real adapter, published atomically right after it exits and BEFORE
                    any parsing: {"schema", "attempt_id", "exit_code", "timed_out", "stdout_b64", "stderr_b64"}.
  <id>.json         the side file (schema oz.bootstrap.side/2), published atomically BEFORE the shim writes stdout:
      {"schema": "oz.bootstrap.side/2", "attempt_id", "receipt", "ids", "ops",
       "status": "ok" | "failed", "reason": null | text, "launched": bool,
       "exit_code": int | null, "timed_out": bool, "elapsed_s",
       "stdout_b64", "stderr_b64", "stdout_sha256", "stderr_sha256",
       "usage": the real adapter's usage object | null,
       "envelope_ok": bool, "answers_reply": text | null,
       "rules": {op: {"none": true} | {"ast_b64": "<exact slice bytes>", "ast_sha256", "bytes": n}}  ({} unless envelope_ok),
       "config_sha256", "spec_sha256", "instruction_sha256", "system_sha256", "prompt_sha256", "shim_sha256"}
  Every path after the claim writes <id>.json, also nonzero exit, timeout, undecodable stdout and an unreadable config.

Reply. The shim appends to the system text Astra's exact 858-character instruction, the pinned effective oz-rule/1
semantics (docs/design/ozmap-2026-10-24/bootstrap-spec-excerpt.txt, SHA256 checked at load), the operation contracts
with eligibility and the envelope shape. The real reply must be the oz-bootstrap/1 envelope
    {"host":"oz-bootstrap/1","answers":"<ordinary OZ/1g reply>","rules":{"<op>": <AST object> | "none", ...}}
with exactly three keys and exactly the requested operation keys. "answers" is returned as the ordinary reply with the
real adapter's other response fields (usage) untouched. Each AST is the ORIGINAL JSON slice of the envelope text, found
by an exact scanner (no re-serialization): whitespace and numeral spellings are preserved, at most 2,048 bytes, no
unpaired surrogate anywhere in the envelope.

Amendment A2.1: a malformed envelope (including an oversized or non-Unicode-clean AST) is status "failed". The reply
is the fixed non-OZ/1g line MALFORMED_REPLY with the real usage; no answer of that envelope is used, nothing is
repaired or revised, and the failed attempt invalidates efficiency (the host must record efficiency_valid false).
A failing real adapter (nonzero exit, timeout) is recorded as "failed" and its stdout, stderr and exit code are relayed
(timeout: exit 124).

Route identity: `--identity` relays the real adapter's identity and adds the shim source hash, the real adapter's
source hash and their import and data closure under "bootstrap_shim", plus two flags. oz_route.source_manifest covers
the same closure through OZ_ROUTE_DATA below.
"""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

# Files that are executable inputs of this source but not importable Python: oz_route hashes them with the sources.
OZ_ROUTE_DATA = ('../docs/design/ozmap-2026-10-24/bootstrap-spec-excerpt.txt',)

ENVELOPE = 'oz-bootstrap/1'
CONFIG_SCHEMA = 'oz.bootstrap.config/2'
SIDE_SCHEMA = 'oz.bootstrap.side/2'
CAPTURE_SCHEMA = 'oz.bootstrap.capture/1'
ATTEMPT_ENV, DIR_ENV, TIMEOUT_ENV = 'OZ_BOOTSTRAP_ATTEMPT', 'OZ_BOOTSTRAP_DIR', 'OZ_BOOTSTRAP_TIMEOUT'
DEFAULT_TIMEOUT = 1800.0
MAX_AST_BYTES = 2048
ATTEMPT_RE = re.compile(r'[A-Za-z0-9._-]{1,128}\Z')
MALFORMED_REPLY = 'oz-bootstrap/1 envelope malformed: bootstrap failed (no repair, no revision)'
EXIT_TIMEOUT, EXIT_CLAIMED, EXIT_REFUSED, EXIT_SOFTWARE = 124, 75, 2, 70

SPEC_EXCERPT_PATH = Path(__file__).resolve().parent.parent / 'docs' / 'design' / 'ozmap-2026-10-24' / \
    'bootstrap-spec-excerpt.txt'
# SHA256 of the excerpt file bytes with CRLF normalized to LF.
SPEC_EXCERPT_SHA256 = '101d6ae09019c9d91cd267b8c700443db5af9d08dd7176bc59fc101f1816fd14'

# Astra's instruction, verbatim from docs/design/ozmap-2026-10-24/oz-rule-1-spec.md ("Bootstrap envelope").
INSTRUCTION = (
    'Answer every bootstrap job using the unchanged OZ/1g contract. Also propose one oz-rule/1 AST or the JSON string '
    '"none" for each requested operation. Use only the supplied language specification, operation contract, and '
    'visible job inputs. A rule must compute the entire answer from that job\'s own text, preserve extracted strings, '
    'and abstain when required data or computation is invalid. Do not infer missing facts, perform semantic reading, '
    'memorize job answers, or use tools. For BoolQ, passage comprehension, or a contract lacking an authorized '
    'input-bound check, return "none" for every operation. Do not revise job answers to fit a rule. Return exactly the '
    'specified oz-bootstrap/1 JSON envelope, with answers containing the ordinary OZ/1g reply as a string and rules '
    'mapping every requested operation to an AST or "none". No prose or additional keys.')
INSTRUCTION_SHA256 = 'ebb9183a89d8e44c66c9e1ca81fa50407af11449646ecd4be3ea0ae3a032fa87'
assert len(INSTRUCTION) == 858 and hashlib.sha256(INSTRUCTION.encode('utf-8')).hexdigest() == INSTRUCTION_SHA256

# Hidden material (amendment A2.2): the worked E, B, M and V ASTs and the pilot field names must never reach the model.
HIDDEN_ASTS = (
    '{"lang":"oz-rule/1","expr":["list",["field","length"],["field","uncertainty"],["field","n"],["field","method"],'
    '["field","basis"],["field","physical_validation"]]}',
    '{"lang":"oz-rule/1","expr":["if",["eq",["field","uncertainty"],["s","unknown"]],["s","unknown"],["require",'
    '["le",["d","0"],["num",["field","uncertainty"],"mm"]],["list",["fmt",["sub",["num",["field","length"],"mm"],'
    '["num",["field","uncertainty"],"mm"]],2,"mm"],["fmt",["add",["num",["field","length"],"mm"],["num",["field",'
    '"uncertainty"],"mm"]],2,"mm"]]]]}',
    '{"lang":"oz-rule/1","expr":["cat",["if",["eq",["field","uncertainty"],["s","unknown"]],["list",["s",'
    '"uncertainty"]],["list"]],["if",["eq",["field","method"],["s","unknown"]],["list",["s","method"]],["list"]],'
    '["if",["eq",["field","basis"],["s","unknown"]],["list",["s","basis"]],["list"]]]}',
    '{"lang":"oz-rule/1","expr":["if",["eq",["field","uncertainty"],["s","unknown"]],["s","unknown"],["require",'
    '["le",["d","0"],["num",["field","uncertainty"],"mm"]],["if",["le",["d","12.48"],["sub",["num",["field",'
    '"length"],"mm"],["num",["field","uncertainty"],"mm"]]],["if",["le",["add",["num",["field","length"],"mm"],'
    '["num",["field","uncertainty"],"mm"]],["d","12.52"]],["s","inside"],["s","outside"]],["s","outside"]]]]}')
HIDDEN_STRINGS = ('length=', 'uncertainty=', 'physical_validation')


class Malformed(Exception):
    """The reply is not exactly the oz-bootstrap/1 envelope for the requested operations."""


class RealAdapterFailed(Exception):
    def __init__(self, code, stderr=''):
        Exception.__init__(self, f'real adapter exited {code}')
        self.code, self.stderr = code, stderr


class Capture:
    """The raw evidence of one real adapter run. exit_code is None and launched False when it never started."""

    def __init__(self, stdout=b'', stderr=b'', exit_code=None, timed_out=False, launched=True):
        self.stdout, self.stderr, self.exit_code, self.timed_out, self.launched = \
            stdout, stderr, exit_code, timed_out, launched


def sha256(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _b64(data):
    return base64.b64encode(data).decode('ascii')


# ----------------------------------------------------------------------------------------------------------------
# The pinned effective language specification
# ----------------------------------------------------------------------------------------------------------------

def check_hidden(text, strings=True):
    """Raise ValueError when the text holds a worked AST (or, with strings, a pilot field spelling)."""
    for item in HIDDEN_ASTS:
        if item in text:
            raise ValueError('hidden worked AST in the text shown to the model')
    if strings:
        for item in HIDDEN_STRINGS:
            if item in text:
                raise ValueError('hidden pilot spelling ' + item + ' in the text shown to the model')


def spec_excerpt(path=None):
    """The effective oz-rule/1 semantics shown in the bootstrap, verified against SPEC_EXCERPT_SHA256 and the
    leakage rules. Raises ValueError otherwise."""
    try:
        raw = Path(path or SPEC_EXCERPT_PATH).read_bytes().replace(b'\r\n', b'\n')
    except OSError as exc:
        raise ValueError('cannot read the bootstrap spec excerpt (' + type(exc).__name__ + ')') from None
    if sha256_bytes(raw) != SPEC_EXCERPT_SHA256:
        raise ValueError('the bootstrap spec excerpt changed; refusing to bootstrap with an unpinned spec')
    try:
        text = raw.decode('utf-8').rstrip('\n')
    except UnicodeError:
        raise ValueError('the bootstrap spec excerpt is not UTF-8') from None
    check_hidden(text)
    return text


# ----------------------------------------------------------------------------------------------------------------
# Exact envelope scanner: strict JSON that keeps the offsets of member values
# ----------------------------------------------------------------------------------------------------------------

class _Num:
    """A JSON numeral kept as written (never converted)."""
    __slots__ = ('lexeme',)

    def __init__(self, lexeme):
        self.lexeme = lexeme


_NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?')
_PLAIN = re.compile('[^"\\\\\x00-\x1f\ud800-\udfff]*')
_HEX = re.compile('[0-9a-fA-F]{4}')
_SIMPLE = {'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}
_WS = ' \t\n\r'
MAX_DEPTH = 100


class _Scan:
    """RFC 8259 value scanner over a str. Duplicate keys, unpaired surrogates (raw or escaped), control characters,
    leading zeros, NaN and Infinity are Malformed. value(i, depth, spans) returns (value, end); when spans is a dict
    the (start, end) character offsets of each member value of that object are stored under the member key."""

    def __init__(self, text):
        self.t, self.n = text, len(text)

    def ws(self, i):
        t, n = self.t, self.n
        while i < n and t[i] in _WS:
            i += 1
        return i

    def value(self, i, depth=0, spans=None):
        if depth > MAX_DEPTH:
            raise Malformed('nesting too deep')
        t = self.t
        if i >= self.n:
            raise Malformed('unexpected end of text')
        c = t[i]
        if c == '{':
            return self.obj(i, depth, spans)
        if c == '[':
            return self.arr(i, depth)
        if c == '"':
            return self.string(i)
        for word, val in (('true', True), ('false', False), ('null', None)):
            if t.startswith(word, i):
                return val, i + len(word)
        match = _NUMBER.match(t, i)
        if match and match.end() > i:
            return _Num(match.group()), match.end()
        raise Malformed('not a JSON value at offset ' + str(i))

    def obj(self, i, depth, spans):
        t = self.t
        out = {}
        i = self.ws(i + 1)
        if i < self.n and t[i] == '}':
            return out, i + 1
        while True:
            if i >= self.n or t[i] != '"':
                raise Malformed('object key expected')
            key, i = self.string(i)
            if key in out:
                raise Malformed('duplicate key ' + key[:40])
            i = self.ws(i)
            if i >= self.n or t[i] != ':':
                raise Malformed('colon expected')
            start = self.ws(i + 1)
            value, end = self.value(start, depth + 1)
            out[key] = value
            if spans is not None:
                spans[key] = (start, end)
            i = self.ws(end)
            if i < self.n and t[i] == ',':
                i = self.ws(i + 1)
                continue
            if i < self.n and t[i] == '}':
                return out, i + 1
            raise Malformed('comma or closing brace expected')

    def arr(self, i, depth):
        t = self.t
        out = []
        i = self.ws(i + 1)
        if i < self.n and t[i] == ']':
            return out, i + 1
        while True:
            value, end = self.value(i, depth + 1)
            out.append(value)
            i = self.ws(end)
            if i < self.n and t[i] == ',':
                i = self.ws(i + 1)
                continue
            if i < self.n and t[i] == ']':
                return out, i + 1
            raise Malformed('comma or closing bracket expected')

    def string(self, i):
        t = self.t
        i += 1
        parts = []
        while True:
            match = _PLAIN.match(t, i)
            parts.append(match.group())
            i = match.end()
            if i >= self.n:
                raise Malformed('unterminated string')
            c = t[i]
            if c == '"':
                return ''.join(parts), i + 1
            if c != '\\':
                raise Malformed('invalid character in string (control character or unpaired surrogate)')
            if i + 1 >= self.n:
                raise Malformed('unterminated escape')
            e = t[i + 1]
            if e in _SIMPLE:
                parts.append(_SIMPLE[e])
                i += 2
            elif e == 'u':
                if not _HEX.fullmatch(t, i + 2, i + 6):
                    raise Malformed('bad \\u escape')
                code = int(t[i + 2:i + 6], 16)
                i += 6
                if 0xD800 <= code <= 0xDBFF:
                    if not (t.startswith('\\u', i) and _HEX.fullmatch(t, i + 2, i + 6)
                            and 0xDC00 <= int(t[i + 2:i + 6], 16) <= 0xDFFF):
                        raise Malformed('unpaired high surrogate escape')
                    low = int(t[i + 2:i + 6], 16)
                    i += 6
                    parts.append(chr(0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)))
                elif 0xDC00 <= code <= 0xDFFF:
                    raise Malformed('unpaired low surrogate escape')
                else:
                    parts.append(chr(code))
            else:
                raise Malformed('invalid escape')


def parse_envelope(reply, ops):
    """(answers, rules) of the exact envelope, else Malformed. rules maps each requested op, in request order, to
    {"none": True} or {"ast_b64": base64 of the ORIGINAL JSON slice's UTF-8 bytes, "ast_sha256": its SHA256,
    "bytes": its length}. The slice is cut from the reply text at the offsets the scanner recorded, so whitespace and
    numeral spelling are exactly as the model wrote them."""
    if not isinstance(reply, str):
        raise Malformed('reply is not text')
    scan = _Scan(reply)
    start = scan.ws(0)
    if start >= scan.n or reply[start] != '{':
        raise Malformed('the reply is not a JSON object')
    top = {}
    value, end = scan.value(start, 0, top)
    if scan.ws(end) != scan.n:
        raise Malformed('content after the envelope')
    if set(value) != {'host', 'answers', 'rules'}:
        raise Malformed('envelope keys must be exactly host, answers, rules')
    if value['host'] != ENVELOPE:
        raise Malformed('host must be ' + ENVELOPE)
    answers = value['answers']
    if not isinstance(answers, str) or not answers.strip():
        raise Malformed('answers must be the ordinary OZ/1g reply as a nonblank string')
    rules = value['rules']
    if not isinstance(rules, dict) or set(rules) != set(ops):
        raise Malformed('rules must map exactly the requested operations')
    spans = {}
    scan.value(top['rules'][0], 1, spans)
    out = {}
    for op in ops:
        rule = rules[op]
        if isinstance(rule, str) and rule == 'none':
            out[op] = {'none': True}
        elif isinstance(rule, dict):
            first, last = spans[op]
            data = reply[first:last].encode('utf-8')
            if len(data) > MAX_AST_BYTES:
                raise Malformed(f'rule for {op[:40]} is {len(data)} bytes; the limit is {MAX_AST_BYTES}')
            out[op] = {'ast_b64': _b64(data), 'ast_sha256': sha256_bytes(data), 'bytes': len(data)}
        else:
            raise Malformed('rule for ' + op[:40] + ' must be an AST object or "none"')
    return answers, out


# ----------------------------------------------------------------------------------------------------------------
# Prompt construction
# ----------------------------------------------------------------------------------------------------------------

def envelope_shape(ops):
    """The exact envelope shape shown to the model for the requested operations."""
    return _compact({'host': ENVELOPE, 'answers': '<ordinary OZ/1g reply>', 'rules': {op: 'none' for op in ops}})


def validate_config(config):
    if (not isinstance(config, dict) or set(config) != {'schema', 'ops', 'contracts', 'eligibility'}
            or config['schema'] != CONFIG_SCHEMA):
        raise ValueError('the bootstrap config must be exactly {schema ' + CONFIG_SCHEMA + ', ops, contracts, eligibility}')
    ops = config['ops']
    if (not isinstance(ops, list) or not ops or any(not isinstance(o, str) or not o.strip() for o in ops)
            or len(set(ops)) != len(ops)):
        raise ValueError('config ops must be a nonempty list of distinct nonblank strings')
    if (not isinstance(config['contracts'], dict) or set(config['contracts']) != set(ops)
            or not isinstance(config['eligibility'], dict) or set(config['eligibility']) != set(ops)
            or any(type(v) is not bool for v in config['eligibility'].values())):
        raise ValueError('config contracts and eligibility must have exactly the requested operations (eligibility bool)')
    return config


def system_text(system, config, spec=None):
    """The original system text followed by the instruction, the pinned effective language semantics, the operation
    contracts with eligibility, and the envelope shape. Nothing in the original text changes."""
    ops = list(config['ops'])
    contracts = {op: {'contract': config['contracts'][op], 'eligible': config['eligibility'][op]} for op in ops}
    return '\n\n'.join([
        system,
        INSTRUCTION,
        'oz-rule/1 language specification:\n' + (spec_excerpt() if spec is None else spec),
        'Requested operations (the OZ/1g op instruction for each is in the packet ops): ' + _compact(ops),
        'Operation contracts: ' + _compact(contracts),
        'oz-bootstrap/1 envelope: ' + envelope_shape(ops),
    ])


# ----------------------------------------------------------------------------------------------------------------
# Files
# ----------------------------------------------------------------------------------------------------------------

def _publish(path, data):
    """Atomic durable publication: same-directory temporary file, fsync, os.replace (retried on the Windows sharing
    violation), then a best-effort directory fsync."""
    temp = f'{path}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp'
    with open(temp, 'wb') as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    for attempt in range(40):
        try:
            os.replace(temp, path)
            break
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.05)
    try:
        fd = os.open(os.path.dirname(path) or '.', os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _claim(directory, attempt, receipt):
    """True for the one process that creates <dir>/<attempt>.claim (O_EXCL)."""
    os.makedirs(directory, exist_ok=True)
    try:
        fd = os.open(os.path.join(directory, attempt + '.claim'),
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_BINARY', 0))
    except FileExistsError:
        return False
    try:
        os.write(fd, _compact({'attempt_id': attempt, 'pid': os.getpid(), 'receipt': receipt}).encode('utf-8'))
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def _side_bytes(side):
    return json.dumps(side, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def _own_sha256():
    try:
        return sha256_bytes(Path(__file__).read_bytes())
    except OSError:
        return None


# ----------------------------------------------------------------------------------------------------------------
# One adapter call
# ----------------------------------------------------------------------------------------------------------------

def _analyse(cap, ops):
    """(fields, (stdout, stderr, exit code)) for a captured real run. Never raises for bad content."""
    fields = {'status': 'failed', 'reason': None, 'envelope_ok': False, 'answers_reply': None, 'rules': {},
              'usage': None}
    if cap.timed_out:
        fields['reason'] = 'timeout'
        return fields, (b'', cap.stderr + b'\nbootstrap_shim: the real adapter timed out', EXIT_TIMEOUT)
    if cap.exit_code != 0:
        fields['reason'] = f'adapter_exit_{cap.exit_code}'
        return fields, (cap.stdout, cap.stderr, cap.exit_code if isinstance(cap.exit_code, int) and cap.exit_code else 1)
    try:
        response = json.loads(cap.stdout.decode('utf-8'))
        reply = response['reply']
        if not isinstance(response, dict) or not isinstance(reply, str):
            raise ValueError
    except (UnicodeError, ValueError, KeyError, TypeError):
        fields['reason'] = 'stdout_undecodable'
        return fields, (cap.stdout, cap.stderr, 0)
    if isinstance(response.get('usage'), dict):
        fields['usage'] = response['usage']
    try:
        answers, rules = parse_envelope(reply, ops)
    except Malformed as exc:
        fields['reason'] = 'envelope_malformed: ' + str(exc)[:200]
        return fields, (json.dumps(dict(response, reply=MALFORMED_REPLY), ensure_ascii=False).encode('utf-8'),
                        cap.stderr, 0)
    fields.update(status='ok', envelope_ok=True, answers_reply=answers, rules=rules)
    return fields, (json.dumps(dict(response, reply=answers), ensure_ascii=False).encode('utf-8'), cap.stderr, 0)


def run(stdin_bytes, launch, env=None):
    """One adapter call. launch(request_bytes, timeout) -> Capture runs the real adapter. Returns
    (stdout bytes, stderr bytes, exit code) for the shim process."""
    env = os.environ if env is None else env
    attempt, directory = env.get(ATTEMPT_ENV), env.get(DIR_ENV)
    if not attempt or not directory:
        cap = launch(stdin_bytes, None)
        return cap.stdout, cap.stderr, cap.exit_code if cap.exit_code is not None else 1
    if not ATTEMPT_RE.fullmatch(attempt):
        return b'', f'bootstrap_shim: invalid {ATTEMPT_ENV}; nothing launched'.encode(), EXIT_REFUSED
    request = None
    try:
        request = json.loads(stdin_bytes.decode('utf-8'))
        if not isinstance(request, dict):
            request = None
    except (UnicodeError, ValueError):
        pass
    receipt = str(request.get('receipt')) if request else None
    if not _claim(directory, attempt, receipt):
        return b'', f'bootstrap_shim: attempt {attempt} already claimed; nothing launched'.encode(), EXIT_CLAIMED
    side = {'schema': SIDE_SCHEMA, 'attempt_id': attempt, 'receipt': receipt,
            'ids': list(request.get('ids') or []) if request and isinstance(request.get('ids'), list) else [],
            'ops': None, 'status': 'failed', 'reason': None, 'launched': False, 'exit_code': None,
            'timed_out': False, 'elapsed_s': 0.0, 'stdout_b64': '', 'stderr_b64': '', 'stdout_sha256': None,
            'stderr_sha256': None, 'usage': None, 'envelope_ok': False, 'answers_reply': None, 'rules': {},
            'config_sha256': None, 'spec_sha256': None, 'instruction_sha256': INSTRUCTION_SHA256,
            'system_sha256': None, 'prompt_sha256': None, 'shim_sha256': _own_sha256()}
    target = os.path.join(directory, attempt + '.json')
    out = (b'', b'', EXIT_SOFTWARE)
    try:
        out = _bootstrap(side, request, directory, attempt, launch, env)
    except Exception as exc:  # the side file is written whatever happens after the claim
        side['reason'] = side['reason'] or 'shim_error: ' + type(exc).__name__ + ': ' + str(exc)[:200]
        side['status'] = 'failed'
        out = (b'', f'bootstrap_shim: {side["reason"]}'.encode('utf-8', 'replace'), EXIT_SOFTWARE)
    _publish(target, _side_bytes(side))
    return out


def _bootstrap(side, request, directory, attempt, launch, env):
    """Fill the side record; return (stdout, stderr, code). Raises only on a shim defect (run() handles it)."""
    if request is None:
        side['reason'] = 'request_unparseable'
        return b'', b'bootstrap_shim: the request is not a JSON object; nothing launched', EXIT_REFUSED
    try:
        config_path = os.path.join(directory, attempt + '.config.json')
        if not os.path.exists(config_path):
            config_path = os.path.join(directory, 'config.json')
        raw_config = Path(config_path).read_bytes()
        side['config_sha256'] = sha256_bytes(raw_config)
        config = validate_config(json.loads(raw_config.decode('utf-8')))
        side['ops'] = list(config['ops'])
        spec = spec_excerpt()
        side['spec_sha256'] = SPEC_EXCERPT_SHA256
        system = system_text(request['system'], config, spec)
        check_hidden(system, strings=False)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        side['reason'] = 'config_invalid: ' + type(exc).__name__ + ': ' + str(exc)[:200]
        return b'', f'bootstrap_shim: {side["reason"]}; nothing launched'.encode('utf-8', 'replace'), EXIT_REFUSED
    side['system_sha256'] = sha256(system)
    side['prompt_sha256'] = sha256(request.get('prompt') if isinstance(request.get('prompt'), str) else '')
    try:
        timeout = float(env.get(TIMEOUT_ENV) or DEFAULT_TIMEOUT)
    except ValueError:
        timeout = DEFAULT_TIMEOUT
    started = time.monotonic()
    try:
        cap = launch(json.dumps(dict(request, system=system), ensure_ascii=False).encode('utf-8'), timeout)
    except OSError as exc:
        side['reason'] = 'spawn_failed: ' + type(exc).__name__ + ': ' + str(exc)[:200]
        return b'', side['reason'].encode('utf-8', 'replace'), EXIT_SOFTWARE
    side['elapsed_s'] = round(time.monotonic() - started, 3)
    # Evidence first: the complete raw streams, exit and timeout, before anything is parsed.
    side.update(launched=True, exit_code=cap.exit_code, timed_out=bool(cap.timed_out), stdout_b64=_b64(cap.stdout),
                stderr_b64=_b64(cap.stderr), stdout_sha256=sha256_bytes(cap.stdout),
                stderr_sha256=sha256_bytes(cap.stderr))
    try:
        _publish(os.path.join(directory, attempt + '.capture.json'),
                 _side_bytes({'schema': CAPTURE_SCHEMA, 'attempt_id': attempt, 'exit_code': cap.exit_code,
                              'timed_out': bool(cap.timed_out), 'stdout_b64': side['stdout_b64'],
                              'stderr_b64': side['stderr_b64']}))
    except OSError:
        pass  # the side file below is the contract; a failure there is not swallowed
    fields, out = _analyse(cap, config['ops'])
    side.update(fields)
    return out


# ----------------------------------------------------------------------------------------------------------------
# Launching the real adapter
# ----------------------------------------------------------------------------------------------------------------

def make_launcher(argv, env=None):
    """launch(request_bytes, timeout) -> Capture for a real adapter script run as a child process. The bootstrap
    variables are removed from the child environment so a nested shim stays a passthrough."""
    child = dict(os.environ if env is None else env, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    for name in (ATTEMPT_ENV, DIR_ENV, TIMEOUT_ENV):
        child.pop(name, None)

    def launch(data, timeout):
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child)
        try:
            out, err = proc.communicate(data, timeout=timeout)
            return Capture(out, err, proc.returncode)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            try:
                out, err = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired as again:
                out, err = again.stdout or exc.stdout or b'', again.stderr or exc.stderr or b''
            return Capture(out or b'', err or b'', None, True)
    return launch


class CallableShim:
    """The same shim around a callable adapter (in-process hosts and fake-adapter tests). Enablement is read from
    `env` (default os.environ) exactly as in the process shim."""
    bootstrap_shim = True

    def __init__(self, real, env=None):
        self.real = real
        self.env = env
        self.capabilities = getattr(real, 'capabilities', None)
        self.__name__ = 'CallableShim'

    def _launch(self, data, timeout):
        try:
            response = self.real(json.loads(data.decode('utf-8')))
            return Capture(json.dumps(response, ensure_ascii=False).encode('utf-8'), b'', 0)
        except RealAdapterFailed as exc:
            return Capture(b'', (exc.stderr or '').encode('utf-8'), exc.code)

    def __call__(self, request):
        out, err, code = run(json.dumps(request, ensure_ascii=False).encode('utf-8'), self._launch, self.env)
        if code:
            raise RealAdapterFailed(code, err.decode('utf-8', 'replace'))
        return json.loads(out.decode('utf-8'))


# ----------------------------------------------------------------------------------------------------------------
# Route identity
# ----------------------------------------------------------------------------------------------------------------

def _declared_data(path):
    try:
        tree = ast.parse(path.read_bytes())
    except (OSError, SyntaxError, ValueError):
        return []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'OZ_ROUTE_DATA'
                                                for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return []
            return [str(v) for v in value] if isinstance(value, (list, tuple)) else []
    return []


def _imports(path):
    try:
        tree = ast.parse(path.read_bytes())
    except (OSError, SyntaxError, ValueError):
        return []
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name.split('.')[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.append(node.module.split('.')[0])
    return names


def closure(paths, base):
    """[[name, sha256], ...] ordered by name: the files, the sibling Python modules they import (transitively) and
    the data files they declare in OZ_ROUTE_DATA. Names are relative to base. Mirrors oz_route.source_manifest."""
    files = {Path(p).resolve() for p in paths}
    work = sorted(files)
    while work:
        path = work.pop()
        if path.suffix != '.py':
            continue
        found = [path.parent / (name + '.py') for name in _imports(path)]
        found += [path.parent / rel for rel in _declared_data(path)]
        for item in found:
            if item.is_file() and item.resolve() not in files:
                files.add(item.resolve())
                work.append(item.resolve())
    base = Path(base).resolve()
    entries = {}
    for path in files:
        try:
            name = path.relative_to(base).as_posix()
        except ValueError:
            try:
                name = os.path.relpath(path, base).replace('\\', '/')
            except ValueError:
                name = path.as_posix()
        entries[name] = sha256_bytes(path.read_bytes())
    return [[name, entries[name]] for name in sorted(entries)]


def identity(real, extra):
    """(stdout, stderr, code) of `--identity`: the real adapter's own report plus the shim's contribution."""
    done = subprocess.run([sys.executable, real, *extra], capture_output=True, stdin=subprocess.DEVNULL,
                          env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1'))
    try:
        report = json.loads(done.stdout.decode('utf-8'))
        if done.returncode or not isinstance(report, dict):
            raise ValueError
    except (UnicodeError, ValueError):
        return done.stdout, done.stderr, done.returncode
    here = Path(__file__).resolve()
    try:
        spec_excerpt()
    except ValueError as exc:
        return b'', ('route identity unknown: ' + str(exc)).encode('utf-8'), 3
    shim, adapter = closure([here], here.parent), closure([real], here.parent)
    report['flags'] = (list(report['flags']) if isinstance(report.get('flags'), list) else []) + [
        'bootstrap-shim=' + ENVELOPE, 'bootstrap-spec-sha256=' + SPEC_EXCERPT_SHA256]
    report['bootstrap_shim'] = {
        'shim_sha256': sha256_bytes(here.read_bytes()), 'shim_closure': shim,
        'adapter': os.path.basename(real), 'adapter_sha256': sha256_bytes(Path(real).read_bytes()),
        'adapter_closure': adapter, 'closure': closure([here, real], here.parent),
        'spec_excerpt_sha256': SPEC_EXCERPT_SHA256, 'instruction_sha256': INSTRUCTION_SHA256}
    return json.dumps(report, ensure_ascii=False).encode('utf-8'), done.stderr, 0


def main():
    if len(sys.argv) < 2:
        sys.stderr.write('usage: bootstrap_shim.py <real adapter script> [args...]')
        sys.exit(2)
    real = os.path.join(os.path.dirname(os.path.abspath(__file__)), sys.argv[1])
    extra = sys.argv[2:]
    if '--identity' in extra:
        out, err, code = identity(real, extra)
    else:
        out, err, code = run(sys.stdin.buffer.read(), make_launcher([sys.executable, real, *extra]))
    sys.stderr.buffer.write(err)
    sys.stderr.buffer.flush()
    sys.stdout.buffer.write(out)
    sys.stdout.buffer.flush()
    sys.exit(code)


if __name__ == '__main__':
    main()
