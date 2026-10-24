"""Freeze readiness: the pending ruling slots that must be settled before `run freeze` (council round 2, B1).

Standard library only. Freeze readiness and live telemetry certification are separate gates (joint decision of the
round 2 deadlock, B1). `readiness_problems()` returns why a freeze would be certain to produce an invalid live run:

* every slot of config.REQUIRED_RULINGS (P1 transport notices, P2 unknown usage, P3 quota observation source, P4 CLI
  notice annex, P5 startup manifest and effective instruction context, D1 authentication source attribution) must
  name a ruling file in config.SIGNED_RULINGS whose exact bytes hash to the recorded sha256 (the countersigned diff)
  and that carries both signatures, `Signed: Astra A` and `Signed: Opus B`;
* the configuration must match what the rulings settle: with `code_mode_host` disabled every exec emits the Code
  Mode notice, so either its omission is signed (SIGNED_OMITTED_DISABLES) or the P4 notice predicate is active
  (SIGNED_CLI_NOTICES with the approved outer event keys and identifier syntax); the P5 startup manifest must exist
  and be bound to the P5 ruling.

Nothing here is a waiver: a ruling file only satisfies its slot, the predicates it settles stay in code.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import config, isolation

SIGNATURES = ('Signed: Astra A', 'Signed: Opus B')
# Astra council round 3, item 1: the annexes each ruling must bind. A slot entry lists them as
# {'annexes': {kind: {'path': <repo relative>, 'sha256': <hash>}}}; each annex file must hash to its value, its hash
# must appear in the countersigned ruling text, and the configuration the harness runs with must be that annex
# (the startup manifest file itself, the CLI notice predicate exactly as configured).
ANNEXES_REQUIRED = {'P3': ('quota_source_manifest',), 'P4': ('cli_notice_annex',),
                    'P5': ('startup_manifest', 'effective_context_evidence'), 'D1': ('attribution_evidence',)}


def cli_notice_config():
    return {'notices': list(config.SIGNED_CLI_NOTICES),
            'event_keys': sorted(config.SIGNED_CLI_NOTICE_EVENT_KEYS) if config.SIGNED_CLI_NOTICE_EVENT_KEYS else None,
            'id_re': config.SIGNED_CLI_NOTICE_ID_RE}


def annex_problems(name, entry, ruling_text):
    import json
    problems = []
    annexes = entry.get('annexes') if isinstance(entry.get('annexes'), dict) else {}
    for kind in ANNEXES_REQUIRED.get(name, ()):
        a = annexes.get(kind)
        if not isinstance(a, dict) or not a.get('path') or not a.get('sha256'):
            problems.append(f'ruling {name}: the required annex {kind} is not bound')
            continue
        path = config.REPO / a['path']
        if not path.is_file():
            problems.append(f'ruling {name}: annex {kind} {a["path"]} is missing')
            continue
        if _sha(path) != a['sha256']:
            problems.append(f'ruling {name}: annex {kind} {a["path"]} is not the approved annex (hash differs)')
            continue
        if a['sha256'] not in ruling_text:
            problems.append(f'ruling {name}: the countersigned text does not name the hash of annex {kind}')
        if kind == 'startup_manifest' and path.resolve() != Path(config.STARTUP_MANIFEST_FILE).resolve():
            problems.append(f'ruling {name}: the approved startup manifest is not the manifest the harness reads')
        if kind == 'cli_notice_annex':
            try:
                doc = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                doc = None
            if doc != cli_notice_config():
                problems.append(f'ruling {name}: the configured CLI notice predicate is not the approved annex')
    return problems


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ruling_problems(slots=None) -> list:
    slots = config.SIGNED_RULINGS if slots is None else slots
    problems = []
    for name in config.REQUIRED_RULINGS:
        entry = slots.get(name)
        if not isinstance(entry, dict) or not entry.get('path') or not entry.get('sha256'):
            problems.append(f'ruling {name} is not settled (no countersigned ruling file in config.SIGNED_RULINGS)')
            continue
        path = config.REPO / entry['path']
        if not path.is_file():
            problems.append(f'ruling {name}: {entry["path"]} is missing')
            continue
        if _sha(path) != entry['sha256']:
            problems.append(f'ruling {name}: {entry["path"]} is not the countersigned text (hash differs)')
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        missing = [s for s in SIGNATURES if s not in text]
        if missing:
            problems.append(f'ruling {name}: {entry["path"]} lacks {missing}')
            continue
        problems += annex_problems(name, entry, text)
    return problems


def configuration_problems(disable_options=None) -> list:
    problems = []
    disable = list(disable_options or [])
    disabled = {disable[i + 1] for i in range(len(disable) - 1) if disable[i] == '--disable'}
    if 'code_mode_host' in disabled and 'code_mode_host' not in config.SIGNED_OMITTED_DISABLES:
        active = (config.P4_CANDIDATE_NOTICE in tuple(config.SIGNED_CLI_NOTICES)
                  and config.SIGNED_CLI_NOTICE_EVENT_KEYS and config.SIGNED_CLI_NOTICE_ID_RE)
        if not active:
            problems.append('code_mode_host is disabled, so every exec emits the Code Mode notice, and the P4 notice '
                            'predicate is inactive (no approved outer event fixture and identifier syntax): every '
                            'live Codex call would be uncertain under A4.3')
    if not isolation.startup_manifest():
        problems.append('no approved startup manifest (P5): the CLI writes skills/.system/* at startup, so the '
                        'telemetry certificate cannot pass')
    return problems


def readiness_problems(disable_options=None, slots=None) -> list:
    if disable_options is None:
        from .run import cli_flags
        disable_options = cli_flags()[0]
    return ruling_problems(slots) + configuration_problems(disable_options)


def record(slots=None) -> dict:
    """The ruling files and hashes freeze.json binds (signed_exceptions.rulings)."""
    slots = config.SIGNED_RULINGS if slots is None else slots
    return {name: {'path': (slots.get(name) or {}).get('path'), 'sha256': (slots.get(name) or {}).get('sha256'),
                   'annexes': (slots.get(name) or {}).get('annexes')}
            for name in config.REQUIRED_RULINGS}
