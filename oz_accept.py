"""Host acceptance profiles and per-job checks (foundation record 2026-10-23, clauses 1 to 3).

Two profiles exist. oz1g-header is the shipped atomic behavior and stays the default: a wire-valid reply commits every
job's valid record, and a rejected reply retries every job. oz1g-selective-v1 is opt-in per job (pinned at post): the
OZ/1g system text, packet grammar and parser are the same, and the parser alone still decides whether a reply is
wire-valid. Only after that, each job's candidate value is judged by the checks pinned to that job, against that job's
own model-visible inputs. Passing jobs commit on their own; a failing job is rejected alone and returns to bounded
recovery. A structurally invalid reply still yields nothing.

Checks are host functions in a registry, identified by name and version. A job pins check specs when it is posted;
model output never selects or weakens them. A check is job-bound when it judges the candidate against data bound to
that job (its resolved inputs or a host-pinned expectation). A failed job-bound check marks the whole reply suspect:
its other candidates commit only with their own job-bound evidence and are otherwise quarantined. A verifier that is
unavailable or inconclusive leaves the candidate awaiting checks; it never spends another model attempt.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Callable

from oz import Error
from oz_batch import J
from oz_reply import loads, slot_ids

HEADER = 'oz1g-header'
SELECTIVE = 'oz1g-selective-v1'
PROFILES = (HEADER, SELECTIVE)
COMPUTE_SCHEMA = 'oz.compute/1'
MAX_CHECKS = 16
MAX_REASON = 200
TYPES = ('string', 'number', 'integer', 'boolean', 'null', 'array', 'object')


class Unavailable(Exception):
    """Raised by a check whose verifier is unavailable or cannot decide; the candidate then awaits checks."""


@dataclass(frozen=True)
class Check:
    """A registered host check. params(spec) validates the pinned parameters (raises Error); run(value, spec,
    inputs) returns True (pass) or False (fail), or raises Unavailable. value is the decoded candidate value; inputs
    are the job's resolved inputs (Inputs)."""
    name: str
    version: int
    job_bound: bool
    params: Callable[[dict], None]
    run: Callable[[object, dict, 'Inputs'], bool]


@dataclass(frozen=True)
class Inputs:
    """The model-visible inputs of one job: per model slot (atom order) its operation instruction and the exact JSON
    text of each reference it was given, in packet order. texts are the readable reference texts (a string reference
    as is, a {"text":...} reference by its text, any other value as its JSON text)."""
    slots: tuple

    @property
    def texts(self) -> tuple:
        out = []
        for slot in self.slots:
            for raw in slot['refs']:
                value = json.loads(raw)
                if isinstance(value, dict) and isinstance(value.get('text'), str):
                    value = value['text']
                out.append(value if isinstance(value, str) else raw)
        return tuple(out)


def _keys(spec: dict, allowed: set, required: set = frozenset()):
    if set(spec) - {'check', 'version'} - allowed or not required <= set(spec):
        raise Error(f'check {spec["check"]} takes {", ".join(sorted(allowed)) or "no parameters"}')


def _type_params(spec):
    _keys(spec, {'types'}, {'types'})
    if (not isinstance(spec['types'], list) or not spec['types'] or any(t not in TYPES for t in spec['types'])):
        raise Error('json_type types must be a nonempty list of ' + ', '.join(TYPES))


def _type_name(value) -> set:
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


def _bytes_params(spec):
    _keys(spec, {'bytes'}, {'bytes'})
    if type(spec['bytes']) is not int or not 1 <= spec['bytes'] <= 65536:
        raise Error('max_bytes bytes must be an integer 1..65536')


def _values_params(spec):
    _keys(spec, {'values'}, {'values'})
    if not isinstance(spec['values'], list) or not spec['values']:
        raise Error('one_of values must be a nonempty list')


def _span_params(spec):
    _keys(spec, {'field'})
    if 'field' in spec and (not isinstance(spec['field'], str) or not spec['field']):
        raise Error('quoted_span field must be a nonempty string')


def _span(value, spec, inputs):
    if 'field' in spec:
        value = value.get(spec['field']) if isinstance(value, dict) else None
    if not isinstance(value, str) or not value.strip():
        return False
    return any(value in text for text in inputs.texts)


def _expect_params(spec):
    _keys(spec, {'value'}, {'value'})


BUILTIN = (
    # The value's JSON type is one of types (integer means a JSON number without fraction or exponent).
    Check('json_type', 1, False, _type_params, lambda v, s, i: bool(_type_name(v) & set(s['types']))),
    # A tighter operation limit on the candidate's compact JSON text (the parser's limits stay in the parser).
    Check('max_bytes', 1, False, _bytes_params, lambda v, s, i: len(J(v).encode('utf-8')) <= s['bytes']),
    # The value equals one of the listed JSON values (true and 1 differ; 12.50 equals 12.5).
    Check('one_of', 1, False, _values_params, lambda v, s, i: J(v) in {J(x) for x in s['values']}),
    # The value (or its string member field) occurs verbatim in one of this job's own reference texts. It verifies
    # the span's presence, not every claim in the result.
    Check('quoted_span', 1, True, _span_params, _span),
    # A host oracle pinned to this job: the value equals the expected JSON value.
    Check('expect', 1, True, _expect_params, lambda v, s, i: J(v) == J(s['value'])),
)
REGISTRY = {c.name: c for c in BUILTIN}


def pin(specs, registry=None) -> tuple:
    """Validated, pinned check specs: [{"check": name, "version": n, ...params}]. Unknown checks, other versions and
    bad parameters are refused before anything is stored."""
    registry = REGISTRY if registry is None else registry
    if specs is None:
        return ()
    if not isinstance(specs, (list, tuple)) or len(specs) > MAX_CHECKS:
        raise Error(f'checks must be a list of at most {MAX_CHECKS} check specs')
    pinned = []
    for spec in specs:
        if not isinstance(spec, dict) or not isinstance(spec.get('check'), str) or spec['check'] not in registry:
            raise Error('each check is {"check": <registered name>, ...}; known: ' + ', '.join(sorted(registry)))
        check = registry[spec['check']]
        if spec.get('version', check.version) != check.version or type(spec.get('version', 1)) is not int:
            raise Error(f'check {check.name} is registered at version {check.version}')
        check.params(spec)
        try:
            text = J(spec)
        except (TypeError, ValueError, Error):
            raise Error('check parameters must be JSON values') from None
        pinned.append(dict(loads(text), check=check.name, version=check.version))
    return tuple(pinned)


def packet_inputs(text: str) -> dict:
    """{packet job ID: {"op": instruction, "refs": [exact JSON text of each reference, in row order]}} of a packet
    body. The reference texts are cut from the body bytes, so equal model-visible inputs give equal texts."""
    body = json.loads(text)
    decoder, raws = json.JSONDecoder(), []
    marker = ',"refs":['
    i = text.index(marker) + len(marker)
    for _ in body['refs']:
        _, end = decoder.raw_decode(text, i)
        raws.append(text[i:end])
        i = end + 1
    out = {}
    for block in body['jobs']:
        for row in block[1:]:
            out[row[0]] = {'op': body['ops'][block[0]], 'refs': [raws[k] for k in row[1:]]}
    return out


def job_inputs(text: str, job_map) -> dict:
    """{inbox job ID: Inputs} for the model slots of a packet."""
    slots = packet_inputs(text)
    grouped = {}
    for pid, (mid, atom) in zip(slot_ids(job_map), job_map):
        grouped.setdefault(mid, []).append((atom, slots[pid]))
    return {mid: Inputs(tuple(s for _, s in sorted(items, key=lambda x: x[0]))) for mid, items in grouped.items()}


def compute_key(goal: str, inputs: Inputs, route: dict) -> str:
    """K_compute (clause 1): the exact goal, each slot's instruction and ordered model-visible input bytes, and the
    pinned execution route. Packet-local IDs, siblings and packet positions are excluded: an OZ/1g job sees only its
    own row's references (the declared independence contract), and the whole packet stays in the dispatch record."""
    manifest = {'v': COMPUTE_SCHEMA, 'goal': goal, 'slots': [[s['op'], list(s['refs'])] for s in inputs.slots],
                'route': route}
    return hashlib.sha256(J(manifest).encode('utf-8')).hexdigest()


def accept_key(compute: str, value: str, profile: str, checks, verdicts) -> str:
    """K_accept: K_compute, candidate digest, profile, pinned checks and the verdicts that admitted it."""
    manifest = [compute, hashlib.sha256(value.encode('utf-8')).hexdigest(), profile, list(checks),
                [[v['check'], v['version'], v['verdict']] for v in verdicts]]
    return hashlib.sha256(J(manifest).encode('utf-8')).hexdigest()


def run_checks(value_text: str, inputs: Inputs, pinned, registry=None, previous=None) -> list:
    """One verdict per pinned check: {check, version, job_bound, verdict: pass|fail|inconclusive, reason}. A check
    missing from the registry or registered at another version is inconclusive, as is a verifier that raises. With
    previous verdicts, only the inconclusive ones run again."""
    registry = REGISTRY if registry is None else registry
    value = loads(value_text)
    verdicts = []
    for k, spec in enumerate(pinned):
        if previous is not None and previous[k]['verdict'] != 'inconclusive':
            verdicts.append(previous[k])
            continue
        check = registry.get(spec['check'])
        job_bound = previous[k]['job_bound'] if previous is not None else bool(check and check.job_bound)
        verdict = {'check': spec['check'], 'version': spec['version'], 'job_bound': job_bound}
        if check is None or check.version != spec['version']:
            verdicts.append(dict(verdict, verdict='inconclusive', reason='check not registered at this version'))
            continue
        try:
            ok = check.run(value, spec, inputs)
        except Unavailable as exc:
            verdicts.append(dict(verdict, verdict='inconclusive', reason=('unavailable: ' + str(exc))[:MAX_REASON]))
            continue
        except Exception as exc:
            # Never store arbitrary exception text; the type is enough to diagnose.
            verdicts.append(dict(verdict, verdict='inconclusive', reason='verifier crashed (' + type(exc).__name__ + ')'))
            continue
        verdicts.append(dict(verdict, verdict='pass' if ok is True else 'fail', reason=None))
    return verdicts


def decide(candidates: dict) -> tuple[dict, dict]:
    """Per-candidate decision for one wire-valid reply under oz1g-selective-v1.

    candidates maps job ID -> its verdict list. Returns ({job: (decision, reason)}, reply) where decision is accept,
    reject, await or quarantine, and reply = {"suspect": bool, "pending": bool}. A failed job-bound check makes the
    reply suspect; an inconclusive job-bound check leaves that open (pending). A candidate is rejected by any failed
    check of its own and awaits any inconclusive one. A candidate whose checks all pass is accepted when one of them is
    job-bound; otherwise it is accepted only in a reply known not to be suspect, quarantined in a suspect reply, and
    awaits while the reply's status is pending. With no checks pinned anywhere, every candidate is accepted, which is
    exactly oz1g-header."""
    suspect = any(v['job_bound'] and v['verdict'] == 'fail' for vs in candidates.values() for v in vs)
    pending = not suspect and any(v['job_bound'] and v['verdict'] == 'inconclusive'
                                  for vs in candidates.values() for v in vs)
    out = {}
    for mid, verdicts in candidates.items():
        failed = [v['check'] for v in verdicts if v['verdict'] == 'fail']
        if failed:
            out[mid] = ('reject', 'check failed: ' + ', '.join(failed))
        elif any(v['verdict'] == 'inconclusive' for v in verdicts):
            out[mid] = ('await', 'awaiting checks: ' + ', '.join(v['check'] for v in verdicts
                                                                  if v['verdict'] == 'inconclusive'))
        elif any(v['job_bound'] for v in verdicts):
            out[mid] = ('accept', None)
        elif suspect:
            out[mid] = ('quarantine', 'suspect reply: a sibling failed a job-bound check and this candidate has no '
                                      'job-bound evidence')
        elif pending:
            out[mid] = ('await', 'awaiting the reply status: a sibling job-bound check is inconclusive')
        else:
            out[mid] = ('accept', None)
    return out, {'suspect': suspect, 'pending': pending}


def summary(verdicts) -> str:
    """Display summary of an accepted candidate's evidence: declared (no checks ran) or checked. Eligibility never
    depends on this label, only on the verdicts themselves."""
    return 'checked' if any(v['verdict'] == 'pass' for v in verdicts) else 'declared'
