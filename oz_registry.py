"""Owner-approved host registry for oz-rule/1 trusted admission (amendment 1, D6; D2 input policy, D9 decimals).

Standard library only, no model calls. A frozen JSON manifest (a dict or a file path) holds immutable operation
contracts, consumer and provenance check definitions with versions and digests, permissions, input policy, route
definitions and the labeled dataset. Producers and candidates supply none of it: the resolver recomputes every
SHA256 against the manifest, verifies label provenance, derives eligibility and returns a ResolvedPackage that only
this module can issue. oz_rule.admit(ast_bytes, resolved_package) accepts nothing else.

Public API
    canonical(x)                    -> bytes, the one canonical encoding used for every case and identity hash
    digest(x)                       -> SHA256 hex of canonical(x)
    loads_strict(data)              -> JSON value; duplicate keys, constants and invalid Unicode are errors
    apply_input_policy(policy, text)-> the resolved text (amendment 1 D2)
    Registry(manifest, runner=None, expected_sha256=None)
        .resolve(operation_id, claimed=None) -> ResolvedPackage (raises RegistryError)
        .admit(ast_bytes, operation_id, claimed=None) -> admission response; never raises
    CheckRunner                     -> the interface a runtime implements to run pinned checks
    LocalChecks                     -> the five AKOR builtins plus rule_provenance/1, re-implemented here
    build_manifest(...)             -> helper that computes every hash for a manifest (owner tooling and tests)

READING notes are marked "READING" below.
"""
import copy
import hashlib
import inspect
import json

import oz_rule

SCHEMA = 'oz-registry/1'
BINDINGS = ('contract_hash', 'check_hash', 'permission_hash', 'worker_hash', 'dataset_hash', 'input_policy_hash')
ROUTE_KEYS = ('adapter_hash', 'backend', 'model', 'effort', 'cli_version', 'environment_hash')
CASE_KEYS = ('id', 'text', 'expected', 'partition')
INPUT_POLICY_VERSION = 'oz-input/1'
PROVENANCE_CHECK = ('rule_provenance', 1)
CONSUMER, PROVENANCE = 'consumer', 'provenance'
_HEX = frozenset('0123456789abcdef')


class RegistryError(Exception):
    """A resolution or verification failure. code is a short stable reason; the message adds detail."""

    def __init__(self, code, detail=''):
        Exception.__init__(self, code + (': ' + detail if detail else ''))
        self.code = code


class CheckUnavailable(Exception):
    """Raised by a runner whose verifier cannot decide; the outcome is recorded as inconclusive."""


# ------------------------------------------------------------------------------------------------ canonical

def _walk(x, depth=0):
    if depth > 200:
        raise RegistryError('canonical', 'too deep')
    if x is None or type(x) in (bool, int):
        return
    if type(x) is float:
        if x != x or x in (float('inf'), float('-inf')):
            raise RegistryError('canonical', 'non-finite number')
        return
    if type(x) is str:
        try:
            x.encode('utf-8')
        except UnicodeEncodeError:
            raise RegistryError('canonical', 'invalid Unicode') from None
        return
    if type(x) in (list, tuple):
        for item in x:
            _walk(item, depth + 1)
        return
    if type(x) is dict:
        for key, value in x.items():
            if type(key) is not str:
                raise RegistryError('canonical', 'non-string key')
            _walk(key, depth + 1)
            _walk(value, depth + 1)
        return
    raise RegistryError('canonical', 'not a JSON value: ' + type(x).__name__)


def canonical(x):
    """UTF-8 bytes of json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(',',':'), allow_nan=False).

    This is the single definition of canonical(x) for case and identity hashes (amendment 1 D6). Invalid Unicode and
    anything that is not a JSON value raise RegistryError. Duplicate object keys cannot exist in a Python dict, so
    they are rejected where text is parsed (loads_strict).
    """
    _walk(x)
    try:
        return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, RecursionError) as exc:
        raise RegistryError('canonical', str(exc)) from None


def digest(x):
    return hashlib.sha256(canonical(x)).hexdigest()


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise RegistryError('json', 'duplicate key')
        out[key] = value
    return out


def _constant(name):
    raise RegistryError('json', 'non-finite constant')


def loads_strict(data):
    """Parse JSON from bytes or str, rejecting a BOM, invalid UTF-8, duplicate keys, NaN/Infinity and lone surrogates."""
    if isinstance(data, (bytes, bytearray)):
        raw = bytes(data)
        if raw.startswith(b'\xef\xbb\xbf'):
            raise RegistryError('json', 'BOM')
        try:
            data = raw.decode('utf-8')
        except UnicodeDecodeError:
            raise RegistryError('json', 'invalid UTF-8') from None
    try:
        value = json.loads(data, object_pairs_hook=_pairs, parse_constant=_constant)
    except RegistryError:
        raise
    except Exception as exc:
        raise RegistryError('json', type(exc).__name__) from None
    _walk(value)
    return value


def _is_hex(s):
    return type(s) is str and len(s) == 64 and set(s) <= _HEX


def _j(value):
    """Compact JSON in insertion order, as AKOR's check registry writes values (not the canonical form)."""
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


# ----------------------------------------------------------------------------------------------- input policy

def _input_policy_problem(policy):
    if type(policy) is not dict or set(policy) != {'version', 'terminal_newline', 'text_ref'}:
        return 'input policy keys'
    if policy['version'] != INPUT_POLICY_VERSION:
        return 'input policy version'
    if policy['terminal_newline'] not in ('strip_one', 'none'):
        return 'input policy terminal_newline'
    if type(policy['text_ref']) is not int or policy['text_ref'] < 0:
        return 'input policy text_ref'
    return None


def apply_input_policy(policy, text):
    """D2: remove exactly one terminal CRLF, otherwise one terminal LF, and nothing else (policy strip_one)."""
    if policy['terminal_newline'] == 'strip_one':
        if text.endswith('\r\n'):
            return text[:-2]
        if text.endswith('\n'):
            return text[:-1]
    return text


# ------------------------------------------------------------------------------------------------- check runner

class CheckRunner:
    """What a runtime implements to run pinned checks. The registry never accepts a callable from a caller: it asks
    the runner it was constructed with, and only for the (name, version) pairs a manifest pins.

    describe(name, version) -> {"kind": "consumer"|"provenance", "input_bound": bool, "impl_version": int,
                                "impl_digest": hex} or None when the pair is unknown
    validate_params(name, version, params) -> None, raising RegistryError for bad parameters
    run(name, version, params, value, text) -> True or False for the decoded candidate value against the job's own
                                resolved input text; raises CheckUnavailable when the verifier cannot decide
    """

    def describe(self, name, version):
        raise NotImplementedError

    def validate_params(self, name, version, params):
        raise NotImplementedError

    def run(self, name, version, params, value, text):
        raise NotImplementedError


_JSON_TYPES = ('string', 'number', 'integer', 'boolean', 'null', 'array', 'object')


def _type_names(value):
    if value is None:
        return {'null'}
    if isinstance(value, bool):
        return {'boolean'}
    if isinstance(value, int):
        return {'integer', 'number'}
    if isinstance(value, float):
        return {'number'}
    if isinstance(value, str):
        return {'string'}
    return {'array'} if isinstance(value, list) else {'object'}


def _only(params, allowed, required=()):
    if type(params) is not dict or set(params) - set(allowed) or not set(required) <= set(params):
        raise RegistryError('check_params', 'takes ' + (', '.join(sorted(allowed)) or 'no parameters'))


def _params_json_type(params):
    _only(params, {'types'}, {'types'})
    if type(params['types']) is not list or not params['types'] or any(t not in _JSON_TYPES for t in params['types']):
        raise RegistryError('check_params', 'json_type types')


def _run_json_type(value, params, text):
    return bool(_type_names(value) & set(params['types']))


def _params_max_bytes(params):
    _only(params, {'bytes'}, {'bytes'})
    if type(params['bytes']) is not int or not 1 <= params['bytes'] <= 65536:
        raise RegistryError('check_params', 'max_bytes bytes')


def _run_max_bytes(value, params, text):
    return len(_j(value).encode('utf-8')) <= params['bytes']


def _params_one_of(params):
    _only(params, {'values'}, {'values'})
    if type(params['values']) is not list or not params['values']:
        raise RegistryError('check_params', 'one_of values')


def _run_one_of(value, params, text):
    return _j(value) in {_j(x) for x in params['values']}


def _params_quoted_span(params):
    _only(params, {'field'})
    if 'field' in params and (type(params['field']) is not str or not params['field']):
        raise RegistryError('check_params', 'quoted_span field')


def _run_quoted_span(value, params, text):
    # The value (or its string member `field`) occurs verbatim in this job's own resolved input text.
    if 'field' in params:
        value = value.get(params['field']) if isinstance(value, dict) else None
    return isinstance(value, str) and bool(value.strip()) and value in text


def _params_expect(params):
    _only(params, {'value'}, {'value'})


def _run_expect(value, params, text):
    return _j(value) == _j(params['value'])


def _params_rule_provenance(params):
    _only(params, set())


def _run_rule_provenance(value, params, text):
    # D1: decided by the host at adoption, by re-evaluating the admitted AST bytes. It cannot run per case.
    raise CheckUnavailable('rule_provenance/1 is evaluated by the host at commit')


def _source_digest(*fns):
    try:
        blob = ''.join(inspect.getsource(f) for f in fns)
    except (OSError, TypeError):
        blob = ''.join(f.__name__ for f in fns)
    return hashlib.sha256(blob.encode('utf-8')).hexdigest()


class LocalChecks(CheckRunner):
    """The AKOR builtins json_type, max_bytes, one_of, quoted_span and expect, re-implemented here, plus the
    host-evaluated rule_provenance/1.

    READING: oz_accept is not imported. It pulls in oz, oz_batch and oz_reply, and its checks take the runtime's Inputs
    object and the pinned-spec shape, so importing it would couple admission to the worker runtime. The five checks
    are a few lines each, so they are mirrored here with a digest over their own source, and a parity test compares
    them with oz_accept on sample values. A runtime can pass its own CheckRunner instead.

    input_bound means the check judges the candidate against the job's own input text. Only quoted_span does here:
    READING: expect compares with a constant pinned per operation, not per job, so it is not input bound.
    """
    _TABLE = {
        ('json_type', 1): (CONSUMER, False, _params_json_type, _run_json_type),
        ('max_bytes', 1): (CONSUMER, False, _params_max_bytes, _run_max_bytes),
        ('one_of', 1): (CONSUMER, False, _params_one_of, _run_one_of),
        ('quoted_span', 1): (CONSUMER, True, _params_quoted_span, _run_quoted_span),
        ('expect', 1): (CONSUMER, False, _params_expect, _run_expect),
        PROVENANCE_CHECK: (PROVENANCE, True, _params_rule_provenance, _run_rule_provenance),
    }

    def describe(self, name, version):
        row = self._TABLE.get((name, version))
        if row is None:
            return None
        kind, bound, params, run = row
        return {'kind': kind, 'input_bound': bound, 'impl_version': version, 'impl_digest': _source_digest(params, run)}

    def validate_params(self, name, version, params):
        self._TABLE[(name, version)][2](params)

    def run(self, name, version, params, value, text):
        return self._TABLE[(name, version)][3](value, params, text)


# ----------------------------------------------------------------------------------------------- verification

def _hash_ok(value):
    return _is_hex(value)


def cases_problem(cases, policy):
    """None when the cases are exactly 64 well formed labeled cases, else a short reason."""
    if type(cases) is not list or len(cases) != oz_rule.CASES:
        return 'case count'
    ids, texts, resolved = set(), set(), set()
    parts = {'representative': 0, 'challenge': 0}
    for c in cases:
        if type(c) is not dict or set(c) != set(CASE_KEYS):
            return 'case shape'
        if type(c['id']) is not str or type(c['text']) is not str:
            return 'case shape'
        if c['partition'] not in parts or not oz_rule.label_ok(c['expected']):
            return 'case label'
        r = apply_input_policy(policy, c['text'])
        # READING: "distinct" means distinct ids, distinct original texts and distinct resolved texts.
        if c['id'] in ids or c['text'] in texts or r in resolved:
            return 'duplicate case'
        ids.add(c['id'])
        texts.add(c['text'])
        resolved.add(r)
        parts[c['partition']] += 1
    if parts['representative'] != oz_rule.REPRESENTATIVE or parts['challenge'] != oz_rule.CHALLENGE:
        return 'partition counts'
    return None


def _provenance_problem(prov, cases):
    if type(prov) is not dict or not prov:
        return 'provenance_missing'
    need = {'labeler', 'method', 'independent', 'hidden_from_synthesis', 'synthesis_agents', 'labels_sha256'}
    if set(prov) != need:
        return 'provenance_missing'
    if type(prov['labeler']) is not str or not prov['labeler'] or type(prov['method']) is not str or not prov['method']:
        return 'provenance_missing'
    agents = prov['synthesis_agents']
    if type(agents) is not list or any(type(a) is not str or not a for a in agents):
        return 'provenance_invalid'
    # D6: labels independently prepared and hidden from synthesis.
    if prov['independent'] is not True or prov['hidden_from_synthesis'] is not True or prov['labeler'] in agents:
        return 'provenance_invalid'
    labels = [{'id': c['id'], 'partition': c['partition'], 'expected': c['expected']} for c in cases]
    if prov['labels_sha256'] != digest(labels):
        return 'provenance_labels_mismatch'
    return None


def _boolq(op_id, contract):
    names = [op_id] + [contract.get(k) for k in ('name', 'family', 'dataset', 'task')]
    return any(isinstance(n, str) and 'boolq' in ''.join(ch for ch in n.lower() if ch.isalnum()) for n in names)


def _verify(data, runner):
    """Recompute and check everything in an assembled package record; returns (consumer, deferred) check lists.

    Raises RegistryError with a stable code. Runs before any case is evaluated.
    """
    op_id = data['operation_id']
    if type(op_id) is not str or not op_id:
        raise RegistryError('operation_id')
    bindings = data['bindings']
    if set(bindings) != set(BINDINGS) or not all(_hash_ok(bindings[k]) for k in BINDINGS):
        raise RegistryError('bindings', 'malformed')
    contract = data['contract']
    if type(contract) is not dict or not contract:
        raise RegistryError('contract')
    if digest(contract) != bindings['contract_hash']:
        raise RegistryError('contract_hash_mismatch')
    if type(data['permissions']) is not dict:
        raise RegistryError('permissions')
    if digest(data['permissions']) != bindings['permission_hash']:
        raise RegistryError('permission_hash_mismatch')
    problem = _input_policy_problem(data['input_policy'])
    if problem:
        raise RegistryError('input_policy', problem)
    if digest(data['input_policy']) != bindings['input_policy_hash']:
        raise RegistryError('input_policy_hash_mismatch')
    route = data['route']
    if type(route) is not dict or set(route) != set(ROUTE_KEYS):
        raise RegistryError('route', 'keys')
    if digest(route) != bindings['worker_hash']:  # D7: worker_hash = SHA256(canonical(route))
        raise RegistryError('worker_hash_mismatch')

    # checks: definitions, versions, digests, parameters
    entries = data['checks']
    if type(entries) is not list or not entries:
        raise RegistryError('unresolved_check', 'operation pins no checks')
    consumer, deferred, seen = [], [], set()
    for e in entries:
        if type(e) is not dict or set(e) != {'id', 'definition', 'definition_hash', 'impl_version', 'impl_digest'}:
            raise RegistryError('unresolved_check', 'entry shape')
        cid, d = e['id'], e['definition']
        if type(cid) is not str or not cid or cid in seen:
            raise RegistryError('unresolved_check', 'check id')
        seen.add(cid)
        if type(d) is not dict or not {'name', 'version', 'kind', 'params'} <= set(d):
            raise RegistryError('unresolved_check', cid)
        if digest(d) != e['definition_hash']:
            raise RegistryError('check_definition_hash_mismatch', cid)
        name, version, kind, params = d['name'], d['version'], d['kind'], d['params']
        if type(name) is not str or type(version) is not int or kind not in (CONSUMER, PROVENANCE):
            raise RegistryError('unresolved_check', cid)
        info = runner.describe(name, version)
        if info is None or info['kind'] != kind:
            raise RegistryError('unresolved_check', cid)
        if e['impl_version'] != info['impl_version'] or e['impl_digest'] != info['impl_digest']:
            raise RegistryError('check_impl_mismatch', cid)
        try:
            runner.validate_params(name, version, params)
        except RegistryError as exc:
            raise RegistryError('unresolved_check', cid + ' ' + str(exc)) from None
        if kind == PROVENANCE:
            if (name, version) != PROVENANCE_CHECK or set(d) != {'name', 'version', 'kind', 'params',
                                                                 'authorized_contract_hashes'}:
                raise RegistryError('unresolved_check', cid)
            deferred.append((cid, d, info))
        else:
            if set(d) != {'name', 'version', 'kind', 'params'}:
                raise RegistryError('unresolved_check', cid)
            consumer.append((cid, d, info))
    if digest([{'id': e['id'], 'definition_hash': e['definition_hash'], 'impl_version': e['impl_version'],
                'impl_digest': e['impl_digest']} for e in entries]) != bindings['check_hash']:
        raise RegistryError('check_hash_mismatch')

    # dataset: complete ordered cases, then independent label provenance
    problem = cases_problem(data['cases'], data['input_policy'])
    if problem:
        raise RegistryError('cases', problem)
    if digest(data['cases']) != bindings['dataset_hash']:
        raise RegistryError('dataset_hash_mismatch')
    problem = _provenance_problem(data['provenance'], data['cases'])
    if problem:
        raise RegistryError(problem)

    # eligibility (D6): a declared deterministic contract and authorized input bound checking
    if _boolq(op_id, contract):
        raise RegistryError('ineligible', 'BoolQ')
    if contract.get('deterministic') is not True:
        raise RegistryError('ineligible', 'contract does not declare a deterministic computation')
    authorized = False
    for cid, d, info in deferred:
        # D1 authorizes the named contract only, never an operation that merely shares an ID.
        hashes = d['authorized_contract_hashes']
        if (type(hashes) is list and bindings['contract_hash'] in hashes
                and data['permissions'].get('rule_provenance') is True):
            authorized = True
    if not authorized and not any(info['input_bound'] for cid, d, info in consumer):
        raise RegistryError('ineligible', 'no authorized input bound check (one_of and shape checks alone cannot)')
    return consumer, deferred


# --------------------------------------------------------------------------------------------- resolved package

_ISSUE = object()


class ResolvedPackage:
    """Verified definitions, hashes, operation identity and exactly 64 cases. Immutable and issued only by
    Registry.resolve. oz_rule.admit recomputes every hash from it again before evaluating a case."""
    __slots__ = ('_blob', '_runner')

    def __init__(self, token, blob, runner):
        if token is not _ISSUE:
            raise TypeError('a ResolvedPackage is issued only by Registry.resolve')
        object.__setattr__(self, '_blob', blob)
        object.__setattr__(self, '_runner', runner)

    def __setattr__(self, name, value):
        raise AttributeError('ResolvedPackage is immutable')

    def _data(self):
        return json.loads(self._blob.decode('utf-8'))

    @property
    def operation_id(self):
        return self._data()['operation_id']

    @property
    def bindings(self):
        return self._data()['bindings']

    @property
    def cases(self):
        return self._data()['cases']

    @property
    def contract(self):
        return self._data()['contract']

    @property
    def input_policy(self):
        return self._data()['input_policy']

    @property
    def provenance(self):
        return self._data()['provenance']

    @property
    def eligible(self):
        return True  # a package that fails eligibility is never issued

    def verify(self):
        """Recompute and check every hash again. Raises RegistryError; returns None when sound."""
        _verify(self._data(), self._runner)

    def deferred_checks(self):
        """Pinned checks the host evaluates at commit (rule_provenance/1), as [{id, name, version}]."""
        _, deferred = _verify(self._data(), self._runner)
        return [{'id': c, 'name': d['name'], 'version': d['version']} for c, d, _ in deferred]

    def resolved_text(self, case):
        return apply_input_policy(self.input_policy, case['text'])

    def run_checks(self, value_text, text):
        """Run every pinned consumer check from the registry definitions. value_text is canonical_value_text(result),
        so a decimal arrives as a JSON string (D9). Returns [{id, check, version, verdict}], verdict one of pass,
        fail or inconclusive."""
        # The definitions were verified by verify() (admit calls it once before any case), so only read them here.
        data = self._data()
        value = json.loads(value_text)
        out = []
        for e in data['checks']:
            d, cid = e['definition'], e['id']
            if d['kind'] != CONSUMER:
                continue
            row = {'id': cid, 'check': d['name'], 'version': d['version']}
            try:
                ok = self._runner.run(d['name'], d['version'], d['params'], value, text)
                row['verdict'] = 'pass' if ok is True else 'fail'
            except CheckUnavailable:
                row['verdict'] = 'inconclusive'
            except Exception:
                row['verdict'] = 'inconclusive'
            out.append(row)
        return out


# --------------------------------------------------------------------------------------------------- registry

_MANIFEST_KEYS = {'schema', 'approved_by', 'frozen', 'checks', 'operations'}
_OP_KEYS = {'contract', 'contract_hash', 'checks', 'check_hash', 'permissions', 'permission_hash', 'input_policy',
            'input_policy_hash', 'route', 'worker_hash', 'dataset'}
_DATASET_KEYS = {'cases', 'dataset_hash'}  # provenance is read separately so a missing one has its own reason


class Registry:
    """A frozen, owner-approved manifest and the runner that executes its pinned checks.

    manifest is a dict or a path to a JSON file. With expected_sha256 the manifest must hash to it: for a dict the
    canonical encoding, for a file its raw bytes. That pin is the root of trust; every artifact hash inside is
    recomputed against what the manifest records.
    """

    def __init__(self, manifest, runner=None, expected_sha256=None):
        self.runner = runner if runner is not None else LocalChecks()
        if isinstance(manifest, (str, bytes)) or hasattr(manifest, '__fspath__'):
            with open(manifest, 'rb') as f:
                raw = f.read()
            if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
                raise RegistryError('manifest_hash_mismatch')
            manifest = loads_strict(raw)
        elif expected_sha256 is not None and digest(manifest) != expected_sha256:
            raise RegistryError('manifest_hash_mismatch')
        data = loads_strict(canonical(manifest))  # a private strict copy
        if type(data) is not dict or set(data) != _MANIFEST_KEYS or data['schema'] != SCHEMA:
            raise RegistryError('manifest', 'shape')
        if data['frozen'] is not True or type(data['approved_by']) is not str or not data['approved_by']:
            raise RegistryError('manifest', 'not frozen or not owner approved')
        if type(data['checks']) is not dict or type(data['operations']) is not dict:
            raise RegistryError('manifest', 'shape')
        self._manifest = data

    def operations(self):
        return sorted(self._manifest['operations'])

    def resolve(self, operation_id, claimed=None):
        """Verified ResolvedPackage for one operation, or RegistryError. claimed optionally carries the binding hashes
        a producer says it used; unknown names and any mismatch reject."""
        ops = self._manifest['operations']
        if type(operation_id) is not str or operation_id not in ops:
            raise RegistryError('unknown_operation', str(operation_id)[:40])
        op = ops[operation_id]
        if type(op) is not dict or set(op) != _OP_KEYS or type(op['dataset']) is not dict \
                or not _DATASET_KEYS <= set(op['dataset']) <= _DATASET_KEYS | {'provenance'} \
                or type(op['checks']) is not list:
            raise RegistryError('operation', 'shape')
        entries = []
        for cid in op['checks']:
            entry = self._manifest['checks'].get(cid) if type(cid) is str else None
            if type(entry) is not dict or set(entry) != {'definition', 'definition_hash', 'impl_version', 'impl_digest'}:
                raise RegistryError('unresolved_check', str(cid)[:40])
            entries.append(dict(entry, id=cid))
        data = {
            'operation_id': operation_id,
            'contract': op['contract'],
            'checks': entries,
            'permissions': op['permissions'],
            'input_policy': op['input_policy'],
            'route': op['route'],
            'cases': op['dataset']['cases'],
            'provenance': op['dataset'].get('provenance'),
            'bindings': {'contract_hash': op['contract_hash'], 'check_hash': op['check_hash'],
                         'permission_hash': op['permission_hash'], 'worker_hash': op['worker_hash'],
                         'dataset_hash': op['dataset']['dataset_hash'], 'input_policy_hash': op['input_policy_hash']},
        }
        if claimed is not None:
            if type(claimed) is not dict:
                raise RegistryError('unknown_binding', 'claimed bindings must be a dict')
            for name, value in claimed.items():
                if name not in BINDINGS:
                    raise RegistryError('unknown_binding', str(name)[:40])
                if value != data['bindings'][name]:
                    raise RegistryError('binding_mismatch', name)
        _verify(data, self.runner)
        return ResolvedPackage(_ISSUE, canonical(data), self.runner)

    def admit(self, ast_bytes, operation_id, claimed=None):
        """Resolve, then oz_rule.admit. A resolution failure is a rejection with no evaluated case. Never raises."""
        try:
            package = self.resolve(operation_id, claimed)
        except RegistryError as exc:
            reason = 'ineligible' if exc.code == 'ineligible' else 'unresolved:' + exc.code
            resp = {'status': 'rejected', 'reasons': [reason], 'detail': str(exc), 'operation_id': operation_id,
                    'ast_hash': None, 'bindings': {}, 'coverage': 0, 'covered_errors': 0, 'cases': [],
                    'deferred_checks': []}
            if isinstance(ast_bytes, (bytes, bytearray)):
                resp['ast_hash'] = hashlib.sha256(bytes(ast_bytes)).hexdigest()
            return resp
        except Exception:
            return {'status': 'rejected', 'reasons': ['internal'], 'operation_id': operation_id, 'ast_hash': None,
                    'bindings': {}, 'coverage': 0, 'covered_errors': 0, 'cases': [], 'deferred_checks': []}
        return oz_rule.admit(ast_bytes, package)


# ------------------------------------------------------------------------------------------ owner tooling

def build_check_entry(definition, runner=None):
    """A manifest check entry for a definition, with the runner's current implementation version and digest."""
    runner = runner if runner is not None else LocalChecks()
    info = runner.describe(definition['name'], definition['version'])
    if info is None:
        raise RegistryError('unresolved_check', definition['name'])
    return {'definition': definition, 'definition_hash': digest(definition),
            'impl_version': info['impl_version'], 'impl_digest': info['impl_digest']}


def build_manifest(operations, checks, approved_by, runner=None):
    """Assemble a frozen manifest and compute every hash. checks maps check id -> definition. operations maps
    operation id -> {contract, checks: [ids], permissions, input_policy, route, cases, provenance}; provenance may
    omit labels_sha256, which is then computed. Owner tooling and tests; the result is data only."""
    runner = runner if runner is not None else LocalChecks()
    operations, checks = copy.deepcopy(operations), copy.deepcopy(checks)  # the manifest never aliases its inputs
    entries = {cid: build_check_entry(d, runner) for cid, d in checks.items()}
    ops = {}
    for op_id, op in operations.items():
        prov = dict(op['provenance'])
        prov.setdefault('labels_sha256', digest([{'id': c['id'], 'partition': c['partition'], 'expected': c['expected']}
                                                 for c in op['cases']]))
        ops[op_id] = {
            'contract': op['contract'], 'contract_hash': digest(op['contract']),
            'checks': list(op['checks']),
            'check_hash': digest([{'id': cid, 'definition_hash': entries[cid]['definition_hash'],
                                   'impl_version': entries[cid]['impl_version'],
                                   'impl_digest': entries[cid]['impl_digest']} for cid in op['checks']]),
            'permissions': op['permissions'], 'permission_hash': digest(op['permissions']),
            'input_policy': op['input_policy'], 'input_policy_hash': digest(op['input_policy']),
            'route': op['route'], 'worker_hash': digest(op['route']),
            'dataset': {'cases': op['cases'], 'dataset_hash': digest(op['cases']), 'provenance': prov},
        }
    return {'schema': SCHEMA, 'approved_by': approved_by, 'frozen': True, 'checks': entries, 'operations': ops}
