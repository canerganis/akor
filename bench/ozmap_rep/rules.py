"""Rule admission and application through the frozen oz_registry and oz_rule (amendment 1 D6, D1, D2, D9).

Standard library only. The registry manifest for Fable's four operations is built from the contracts (prompts.py),
the oracle-labeled admission cases (workload.py) and pinned consumer checks, exactly as the pilot built its own
(bench/ozmap/pilot.py operations, check_definitions). A candidate AST is admitted only by oz_rule.admit on the
resolved package; BoolQ is never eligible (A4.6: its checks cannot authorize adoption). A rule value is used only
when every pinned consumer check passes; the deferred rule_provenance/1 check holds by construction because a rule is
applied only to jobs of the operation whose contract admitted it.
"""
from __future__ import annotations

import base64
import functools
import hashlib
import sys

from . import config

for _p in (str(config.REPO),):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import oz_registry  # noqa: E402
import oz_rule  # noqa: E402

CHECKS = {
    'verdict': [('one_of', {'values': ['pass', 'fail', 'unknown']})],
    'margin': [('max_bytes', {'bytes': 32})],
    'elong': [('max_bytes', {'bytes': 32})],
    'temp_class': [('one_of', {'values': ['cold', 'room', 'hot', 'unknown']})],
}
APPROVED_BY = 'canerganis (owner); replication registry built by bench/ozmap_rep/rules.py from Amendment 4 inputs'


def check_definitions():
    from .prompts import contracts
    hashes = sorted(oz_registry.digest(c) for c in contracts().values())
    checks = {'materials_provenance': {'name': 'rule_provenance', 'version': 1, 'kind': 'provenance', 'params': {},
                                       'authorized_contract_hashes': hashes}}
    for op in config.OPERATIONS:
        checks[f'{op}_type'] = {'name': 'json_type', 'version': 1, 'kind': 'consumer', 'params': {'types': ['string']}}
        for k, (name, params) in enumerate(CHECKS[op]):
            checks[f'{op}_{name}'] = {'name': name, 'version': 1, 'kind': 'consumer', 'params': params}
    return checks


def route():
    """The registry route of the frozen Codex route (ROUTE_KEYS). adapter_hash binds the harness sources that build
    and judge calls; environment_hash binds the environment allowlist and the frozen argument head."""
    import json
    names = ('run.py', 'prompts.py', 'isolation.py', 'events.py', 'usage.py')
    adapter = hashlib.sha256(b''.join((config.HERE / n).read_bytes() for n in names if (config.HERE / n).exists())).hexdigest()
    env = hashlib.sha256(json.dumps([list(config.ENV_ALLOWLIST), config.FROZEN_ARGS]).encode()).hexdigest()
    return {'adapter_hash': adapter, 'backend': 'codex', 'model': config.CODEX_MODEL, 'effort': config.CODEX_EFFORT,
            'cli_version': config.CODEX_CLI_VERSION, 'environment_hash': env}


def _label(value):
    return {'type': 'string', 'value': value}


@functools.lru_cache(maxsize=1)
def manifest():
    from .prompts import contracts
    from .workload import materials
    adm = materials()['admission']
    cons = contracts()
    labeler = 'bench/ozmap_rep/ops/oracle.py sha256:' + hashlib.sha256(
        (config.HERE / 'ops' / 'oracle.py').read_bytes()).hexdigest()
    ops = {}
    for op in config.OPERATIONS:
        ops[op] = {'contract': cons[op],
                   'checks': [f'{op}_type'] + [f'{op}_{name}' for name, _ in CHECKS[op]] + ['materials_provenance'],
                   'permissions': {'rule_provenance': True}, 'input_policy': dict(config.INPUT_POLICY),
                   'route': route(),
                   'cases': [{'id': c['id'], 'text': c['text'], 'partition': c['kind'], 'expected': _label(c['gold'])}
                             for c in adm[op]],
                   'provenance': {'labeler': labeler, 'method': 'independent oracle written by Fable from ops.md; '
                                                                'no oz_rule, no AST',
                                  'independent': True, 'hidden_from_synthesis': True,
                                  'synthesis_agents': [config.CODEX_MODEL, config.SONNET_MODEL]}}
    return oz_registry.build_manifest(ops, check_definitions(), APPROVED_BY)


@functools.lru_cache(maxsize=1)
def registry():
    m = manifest()
    return oz_registry.Registry(m, expected_sha256=oz_registry.digest(m))


def manifest_sha256():
    return oz_registry.digest(manifest())


def admit(op, ast_bytes) -> dict:
    """The admission response for one candidate (never raises). BoolQ and unknown operations are rejected."""
    if op not in config.OPERATIONS:
        return {'status': 'rejected', 'reasons': ['ineligible'], 'operation_id': op, 'coverage': 0,
                'covered_errors': 0, 'cases': []}
    return registry().admit(ast_bytes, op)


def summary(resp) -> dict:
    return {k: resp.get(k) for k in ('status', 'reasons', 'coverage', 'covered_errors', 'ast_hash')}


def decode(entry):
    return base64.b64decode(entry['ast_b64'])


def apply(op, ast_bytes, text):
    """(value or None, detail): the rule's answer for one job text after the input policy, or None when it abstains or
    a pinned consumer check does not pass."""
    resolved = oz_registry.apply_input_policy(config.INPUT_POLICY, text)
    result = oz_rule.evaluate(ast_bytes, resolved)
    if result.get('status') != 'value':
        return None, {'status': 'abstain', 'reason': result.get('reason')}
    pkg = registry().resolve(op)
    outcomes = pkg.run_checks(oz_rule.canonical_value_text(result), resolved)
    if not all(o['verdict'] == 'pass' for o in outcomes):
        return None, {'status': 'check_failed', 'checks': outcomes}
    if result.get('type') != 'string':
        return None, {'status': 'type', 'type': result.get('type')}
    return result['value'], {'status': 'value'}
