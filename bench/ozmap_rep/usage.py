"""A4.7: cache and reasoning certification. Standard library only.

decode_codex reads one `turn.completed` usage object under inclusive cached accounting (cached input is a subset of
input): charged input = input_tokens, charged tokens = input + output; reasoning is a subset of output and is never
added again. A missing counter is never read as zero. Positive cached input needs an applicable inclusion
certificate (the archived live run 1 pair, Certificate); zero cached input needs none. The additive reading
(input + cached + output) is a separate sensitivity number. The per call reasoning predicate is the signed pilot
predicate (bench/ozmap/pilot.reasoning_inclusion, sign-off 5), imported, never copied.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

from . import config

REQUIRED = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens')


def _count(value):
    return type(value) is int


def decode_codex(raw, cache_certified=False):
    out = {'input_tokens': None, 'cached_input_tokens': None, 'uncached_input_tokens': None, 'output_tokens': None,
           'reasoning_output_tokens': None, 'charged_input_tokens': None, 'charged_output_tokens': None,
           'charged_tokens': None, 'status': 'complete', 'problems': []}
    if not isinstance(raw, dict):
        out['status'] = 'incomplete'
        out['problems'].append('no usage object')
        return out
    missing = [k for k in REQUIRED if not _count(raw.get(k))]
    for k in REQUIRED:
        if _count(raw.get(k)):
            out[k] = raw[k]
    if missing:
        out['status'] = 'incomplete'
        out['problems'].append(f'missing or non-integer counters: {missing}')
        return out
    i, c, o, r = (raw[k] for k in REQUIRED)
    if min(i, c, o, r) < 0:
        out['status'] = 'invalid'
        out['problems'].append('a counter is negative')
    if c > i:
        out['status'] = 'invalid'
        out['problems'].append('cached_input_tokens exceeds input_tokens (0 <= cached <= input violated)')
    if r > o:
        out['status'] = 'invalid'
        out['problems'].append('reasoning_output_tokens exceeds output_tokens')
    out['uncached_input_tokens'] = i - c
    out['charged_input_tokens'] = i
    out['charged_output_tokens'] = o
    out['charged_tokens'] = i + o
    if out['status'] == 'complete' and c > 0 and not cache_certified:
        out['status'] = 'unverified'
        out['problems'].append(f'cached_input_tokens {c} without an applicable inclusion certificate')
    return out


def additive_tokens(raw) -> int:
    """The sensitivity reading under additive input accounting: input + cached + output."""
    return raw['input_tokens'] + raw['cached_input_tokens'] + raw['output_tokens']


def decode_sonnet(raw):
    """The Sonnet pilot route: adapter-constructed inclusive input (claude_cli_adapter.usage_from_envelope)."""
    out = {'input_tokens': None, 'cached_input_tokens': None, 'output_tokens': None, 'charged_tokens': None,
           'status': 'complete', 'problems': []}
    keys = ('input_tokens', 'cached_input_tokens', 'output_tokens')
    if not isinstance(raw, dict) or any(not _count(raw.get(k)) or raw[k] < 0 for k in keys):
        out['status'] = 'incomplete'
        out['problems'].append('usage unknown (modelUsage absent or a counter missing)')
        return out
    for k in keys:
        out[k] = raw[k]
    if raw['cached_input_tokens'] > raw['input_tokens']:
        out['status'] = 'invalid'
        out['problems'].append('cached input exceeds input')
    out['charged_tokens'] = raw['input_tokens'] + raw['output_tokens']
    return out


def _pilot():
    from bench.ozmap import pilot
    return pilot


def reasoning_inclusion(usage, visible):
    """Exactly bench.ozmap.pilot.reasoning_inclusion (the frozen sign-off 5 predicate)."""
    return _pilot().reasoning_inclusion(usage, visible)


def decoder_sha256() -> str:
    """The decoder source trace: SHA256 of the source text of decode_codex (line endings normalized)."""
    text = inspect.getsource(decode_codex).replace('\r\n', '\n')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class Certificate:
    """An inclusion certificate from a pair of calls on one route: equal input totals with different cached counts,
    each within 0 <= cached <= input. Repetition alone (equal cached counts) certifies nothing."""

    def __init__(self, run, route, decoder, calls):
        self.run, self.route, self.decoder_sha256, self.calls = run, dict(route or {}), decoder, list(calls or [])

    @classmethod
    def from_pair(cls, pair):
        return cls(pair.get('run'), pair.get('route'), pair.get('decoder_sha256'), pair.get('calls'))

    @property
    def valid(self) -> bool:
        if len(self.calls) != 2:
            return False
        try:
            (i1, c1), (i2, c2) = ((c['input'], c['cached']) for c in self.calls)
        except (KeyError, TypeError):
            return False
        if not all(_count(x) for x in (i1, c1, i2, c2)):
            return False
        if not (0 <= c1 <= i1 and 0 <= c2 <= i2):
            return False
        return i1 == i2 and c1 != c2

    def applies(self, route, decoder_sha256) -> bool:
        keys = ('model', 'effort', 'cli_version')
        return (self.valid and all(route.get(k) == self.route.get(k) for k in keys)
                and decoder_sha256 == self.decoder_sha256)


def replay_fixtures() -> list:
    """A4.7 replay through decode_codex: arithmetic only, never live semantics. Each row has ok True or False."""
    rows = []

    def check(name, raw, certified, want):
        got = decode_codex(raw, cache_certified=certified)
        rows.append({'fixture': name, 'ok': all(got[k] == v for k, v in want.items()),
                     'want': want, 'got': {k: got[k] for k in want}})
    check('cached 4000 of 10000', {'input_tokens': 10000, 'cached_input_tokens': 4000, 'output_tokens': 500,
                                   'reasoning_output_tokens': 300}, True,
          {'uncached_input_tokens': 6000, 'charged_input_tokens': 10000, 'charged_tokens': 10500,
           'status': 'complete'})
    check('cached 0 of 10000', {'input_tokens': 10000, 'cached_input_tokens': 0, 'output_tokens': 500,
                                'reasoning_output_tokens': 300}, False,
          {'uncached_input_tokens': 10000, 'charged_input_tokens': 10000, 'status': 'complete'})
    check('reasoning not added to output', {'input_tokens': 10000, 'cached_input_tokens': 0, 'output_tokens': 500,
                                            'reasoning_output_tokens': 500}, False,
          {'charged_output_tokens': 500, 'charged_tokens': 10500})
    check('reasoning above output invalid', {'input_tokens': 10, 'cached_input_tokens': 0, 'output_tokens': 5,
                                             'reasoning_output_tokens': 6}, False, {'status': 'invalid'})
    check('cached above input invalid', {'input_tokens': 10, 'cached_input_tokens': 11, 'output_tokens': 5,
                                         'reasoning_output_tokens': 0}, True, {'status': 'invalid'})
    check('positive cached without certificate', {'input_tokens': 10, 'cached_input_tokens': 4, 'output_tokens': 5,
                                                  'reasoning_output_tokens': 0}, False, {'status': 'unverified'})
    return rows


def load_archived_certificate(path=None) -> Certificate:
    path = Path(path or config.CERTIFICATE_FILE)
    return Certificate.from_pair(json.loads(path.read_text(encoding='utf-8')))


def cache_certified_for_route() -> bool:
    try:
        return load_archived_certificate().applies(config.ROUTE, decoder_sha256())
    except (OSError, ValueError, KeyError):
        return False
