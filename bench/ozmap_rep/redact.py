"""Secret redaction before anything leaves the baseline and the worker homes (A4.2; council round 1, item 6).

Standard library only. Every capture, diagnostic, parsed result and event field the harness persists outside the
baseline and the worker homes passes through redact() first. Secrets are the token strings of the authentication
documents involved in a call (baseline, prepared worker, worker after the call) plus generic credential shapes (JWTs,
API keys). A redaction keeps only a short hash prefix of the removed text and is recorded; any redaction marks the
call as a credential disclosure, which the scorer treats as an isolation failure.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

MIN_SECRET = 12
PATTERNS = (
    ('jwt', re.compile(r'eyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{2,}')),
    ('api_key', re.compile(r'\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}')),
    ('bearer', re.compile(r'(?i)\bbearer\s+[A-Za-z0-9_\-.=]{16,}')),
)


def _strings(value, out):
    if isinstance(value, str):
        if len(value) >= MIN_SECRET:
            out.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            _strings(v, out)
    elif isinstance(value, list):
        for v in value:
            _strings(v, out)


def secrets_from_auth(*paths) -> set:
    """Every credential string of the given auth.json files (the `tokens` object, API key fields)."""
    out = set()
    for p in paths:
        if p is None:
            continue
        try:
            doc = json.loads(Path(p).read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeError):
            continue
        if not isinstance(doc, dict):
            continue
        _strings(doc.get('tokens'), out)
        for key in ('OPENAI_API_KEY', 'api_key', 'access_token', 'refresh_token', 'id_token'):
            _strings(doc.get(key), out)
    return out


def _tag(kind, text):
    return f'[REDACTED:{kind}:{hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]}]'


def redact(text, secrets=()) -> tuple:
    """(clean text, record). record = {redactions, kinds, original_sha256} (original_sha256 only when something was
    removed; a hash never reveals the secret)."""
    if not isinstance(text, str) or not text:
        return text, {'redactions': 0, 'kinds': []}
    original = text
    count, kinds = 0, set()
    for secret in sorted(set(secrets or ()), key=len, reverse=True):
        if secret and secret in text:
            n = text.count(secret)
            text = text.replace(secret, _tag('auth', secret))
            count += n
            kinds.add('auth')
    for kind, rx in PATTERNS:
        def sub(m, kind=kind):
            return _tag(kind, m.group(0))
        text, n = rx.subn(sub, text)
        if n:
            count += n
            kinds.add(kind)
    record = {'redactions': count, 'kinds': sorted(kinds)}
    if count:
        record['original_sha256'] = hashlib.sha256(original.encode('utf-8')).hexdigest()
    return text, record


def merge(*records) -> dict:
    out = {'redactions': 0, 'kinds': set()}
    for r in records:
        out['redactions'] += int((r or {}).get('redactions', 0))
        out['kinds'] |= set((r or {}).get('kinds', ()))
    out['kinds'] = sorted(out['kinds'])
    return out


def channels(**named) -> dict:
    """The per channel redaction record of one call (council round 2, item 6): for each channel (original text,
    clean text, redact() record) its own original and sanitized sha256, redaction count and kinds, plus the totals.
    The original hash is kept for every channel, so a raw stream can be matched against it later."""
    out = {'redactions': 0, 'kinds': set(), 'channels': {}}
    for name, (original, clean, rec) in sorted(named.items()):
        rec = rec or {}
        out['channels'][name] = {'original_sha256': hashlib.sha256((original or '').encode('utf-8')).hexdigest(),
                                 'sanitized_sha256': hashlib.sha256((clean or '').encode('utf-8')).hexdigest(),
                                 'redactions': int(rec.get('redactions', 0)), 'kinds': list(rec.get('kinds', ()))}
        out['redactions'] += int(rec.get('redactions', 0))
        out['kinds'] |= set(rec.get('kinds', ()))
    out['kinds'] = sorted(out['kinds'])
    return out
