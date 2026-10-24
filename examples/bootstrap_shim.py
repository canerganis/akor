"""oz.adapter/3 wrapper for the fused oz-rule/1 bootstrap (signed record section 3; oz-rule/1 "Bootstrap envelope").

Usage in an adapter JSON: {"argv": ["python", "bootstrap_shim.py", "<real adapter script>", ...]}. The shim has the
same stdin/stdout contract as every adapter: one oz.adapter/3 request on stdin, one {"reply", "usage"?} JSON on
stdout. The real adapter (claude_map_adapter.py, codex_cli_adapter.py or any other script) runs as a child process with
the same environment, so OZ_MODEL, OZ_EFFORT and the runner's OZ_ENVELOPE_PATH reach it unchanged; `--identity` is
relayed to it as is. Standard library only; nothing in the AKOR core changes.

Passthrough: without OZ_BOOTSTRAP in the environment the request goes to the real adapter byte for byte and its answer
comes back unchanged. The host sets OZ_BOOTSTRAP to a config file only while it runs the bootstrap request.

Bootstrap: OZ_BOOTSTRAP names a JSON config {"schema": "oz.bootstrap.config/1", "side_dir", "ops", "contracts",
"eligibility", "spec"}. The first call that sees it atomically creates <side_dir>/attempted (O_EXCL), so exactly one
physical call ever carries the bootstrap instruction; any later call of the same request (an ordinary retry) is a
passthrough. For that one call the shim appends, to the system text, Astra's exact 858-character instruction, the
oz-rule/1 language specification excerpt and the operation contracts with their eligibility and the envelope shape,
calls the real adapter once, and parses the reply as the oz-bootstrap/1 envelope:

    {"host":"oz-bootstrap/1","answers":"<ordinary OZ/1g reply>","rules":{"<op>": <AST object> | "none", ...}}

exactly three keys, "rules" with exactly the requested operation keys. Before stdout is written, the shim durably
publishes <side_dir>/<receipt>.json (keyed by the physical call's receipt; the host maps it to the call ID through the
worker's ledger) with the raw envelope, the parsed rules (each AST as its compact JSON text plus SHA256), the status
and the hashes of the config and the augmented system text. Then "answers" is returned as the ordinary reply, with
the real adapter's usage untouched, so the frozen worker parses and accounts it as any call.

A malformed envelope fails the bootstrap: status "malformed", no rule, no repair and no revision. The reply returned is
a fixed non-OZ/1g line, so the worker records an invalid reply (usage kept) and no answer from that envelope is used.
A failing real adapter is recorded as "adapter_failed" and its exit code is relayed.
"""
import hashlib
import json
import os
import subprocess
import sys

ENVELOPE = 'oz-bootstrap/1'
CONFIG_SCHEMA = 'oz.bootstrap.config/1'
SIDE_SCHEMA = 'oz.bootstrap.side/1'
MARKER = 'attempted'
MALFORMED_REPLY = 'oz-bootstrap/1 envelope malformed: bootstrap failed (no repair, no revision)'

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


class Malformed(Exception):
    """The reply is not exactly the oz-bootstrap/1 envelope for the requested operations."""


class RealAdapterFailed(Exception):
    def __init__(self, code, stderr=''):
        Exception.__init__(self, f'real adapter exited {code}')
        self.code, self.stderr = code, stderr


def sha256(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise Malformed('duplicate key ' + key[:40])
        out[key] = value
    return out


def _constant(name):
    raise Malformed('non-finite constant')


def envelope_shape(ops):
    """The exact envelope shape shown to the model for the requested operations."""
    return _compact({'host': ENVELOPE, 'answers': '<ordinary OZ/1g reply>', 'rules': {op: 'none' for op in ops}})


def system_text(system, config):
    """The original system text followed by the instruction, the language specification excerpt, the operation
    contracts with eligibility, and the envelope shape. Nothing in the original text changes."""
    ops = list(config['ops'])
    contracts = {op: {'contract': config['contracts'].get(op), 'eligible': bool(config['eligibility'].get(op))}
                 for op in ops}
    return '\n\n'.join([
        system,
        INSTRUCTION,
        'oz-rule/1 language specification:\n' + config['spec'],
        'Requested operations (the OZ/1g op instruction for each is in the packet ops): ' + _compact(ops),
        'Operation contracts: ' + _compact(contracts),
        'oz-bootstrap/1 envelope: ' + envelope_shape(ops),
    ])


def parse_envelope(reply, ops):
    """(answers, rules) of an exact envelope, else Malformed. rules maps each requested op to "none" or
    {"ast": compact JSON text of the AST object as written (key order kept), "ast_sha256"}."""
    if not isinstance(reply, str):
        raise Malformed('reply is not text')
    try:
        value = json.loads(reply, object_pairs_hook=_pairs, parse_constant=_constant)
    except Malformed:
        raise
    except ValueError as exc:
        raise Malformed('not one JSON value (' + type(exc).__name__ + ')') from None
    if not isinstance(value, dict) or set(value) != {'host', 'answers', 'rules'}:
        raise Malformed('envelope keys must be exactly host, answers, rules')
    if value['host'] != ENVELOPE:
        raise Malformed('host must be ' + ENVELOPE)
    if not isinstance(value['answers'], str) or not value['answers'].strip():
        raise Malformed('answers must be the ordinary OZ/1g reply as a nonblank string')
    rules = value['rules']
    if not isinstance(rules, dict) or set(rules) != set(ops):
        raise Malformed('rules must map exactly the requested operations')
    out = {}
    for op in ops:
        ast = rules[op]
        if ast == 'none':
            out[op] = 'none'
        elif isinstance(ast, dict):
            try:
                text = _compact(ast)
            except (TypeError, ValueError):
                raise Malformed('rule for ' + op[:40] + ' is not JSON') from None
            out[op] = {'ast': text, 'ast_sha256': sha256(text)}
        else:
            raise Malformed('rule for ' + op[:40] + ' must be an AST object or "none"')
    return value['answers'], out


def _publish(path, data):
    temp = path + '.' + str(os.getpid()) + '.tmp'
    with open(temp, 'wb') as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


def _claim(side_dir, receipt):
    """True for the one call that carries the bootstrap; False when a bootstrap was already attempted."""
    os.makedirs(side_dir, exist_ok=True)
    try:
        fd = os.open(os.path.join(side_dir, MARKER), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(fd, str(receipt).encode('utf-8'))
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def handle(request, call_real, env=None):
    """One adapter call. call_real(request) -> response dict, raising RealAdapterFailed on a failed real adapter."""
    env = os.environ if env is None else env
    path = env.get('OZ_BOOTSTRAP')
    if not path:
        return call_real(request)
    with open(path, 'rb') as file:
        raw_config = file.read()
    config = json.loads(raw_config.decode('utf-8'))
    if not isinstance(config, dict) or config.get('schema') != CONFIG_SCHEMA:
        raise ValueError('OZ_BOOTSTRAP does not name an oz.bootstrap.config/1 file')
    side_dir, receipt = config['side_dir'], str(request.get('receipt'))
    if not _claim(side_dir, receipt):
        return call_real(request)
    system = system_text(request['system'], config)
    side = {'schema': SIDE_SCHEMA, 'receipt': receipt, 'ids': list(request.get('ids') or []), 'ops': list(config['ops']),
            'config_sha256': hashlib.sha256(raw_config).hexdigest(), 'instruction_sha256': INSTRUCTION_SHA256,
            'system_sha256': sha256(system), 'prompt_sha256': sha256(request.get('prompt') or '')}
    target = os.path.join(side_dir, receipt + '.json')
    try:
        response = call_real(dict(request, system=system))
    except RealAdapterFailed as exc:
        side.update(status='adapter_failed', reason=str(exc), stderr=(exc.stderr or '')[-2000:], raw_reply=None,
                    rules=None)
        _publish(target, _compact(side).encode('utf-8'))
        raise
    reply = response.get('reply') if isinstance(response, dict) else None
    side['usage'] = response.get('usage') if isinstance(response, dict) else None
    side['raw_reply'] = reply if isinstance(reply, str) else None
    side['raw_reply_sha256'] = sha256(reply) if isinstance(reply, str) else None
    try:
        answers, rules = parse_envelope(reply, config['ops'])
    except Malformed as exc:
        side.update(status='malformed', reason=str(exc), rules=None)
        _publish(target, _compact(side).encode('utf-8'))
        return dict(response, reply=MALFORMED_REPLY)
    side.update(status='ok', reason=None, rules=rules, answers_sha256=sha256(answers))
    _publish(target, _compact(side).encode('utf-8'))
    return dict(response, reply=answers)


class CallableShim:
    """The same shim around a callable adapter (in-process hosts and fake-adapter tests)."""
    bootstrap_shim = True

    def __init__(self, real):
        self.real = real
        self.capabilities = getattr(real, 'capabilities', None)
        self.__name__ = 'CallableShim'

    def __call__(self, request):
        return handle(request, self.real)


def main():
    if len(sys.argv) < 2:
        sys.stderr.write('usage: bootstrap_shim.py <real adapter script> [args...]')
        sys.exit(2)
    real = os.path.join(os.path.dirname(os.path.abspath(__file__)), sys.argv[1])
    argv = [sys.executable, real, *sys.argv[2:]]
    env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    if '--identity' in sys.argv[2:]:
        done = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', env=env,
                              stdin=subprocess.DEVNULL)
        sys.stdout.write(done.stdout)
        sys.stderr.write(done.stderr)
        sys.exit(done.returncode)
    request = json.loads(sys.stdin.buffer.read().decode('utf-8'))

    def call_real(req):
        done = subprocess.run(argv, input=json.dumps(req, ensure_ascii=False).encode('utf-8'), capture_output=True,
                              env=env)
        if done.returncode:
            raise RealAdapterFailed(done.returncode, done.stderr.decode('utf-8', 'replace'))
        return json.loads(done.stdout.decode('utf-8'))

    try:
        response = handle(request, call_real)
    except RealAdapterFailed as exc:
        sys.stderr.write(exc.stderr[-4000:])
        sys.exit(exc.code)
    sys.stdout.write(json.dumps(response, ensure_ascii=False))


if __name__ == '__main__':
    main()
