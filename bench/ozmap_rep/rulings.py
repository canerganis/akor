"""Freeze readiness: the pending ruling slots that must be settled before `run freeze` (council round 2, B1).

Standard library only. Freeze readiness and live telemetry certification are separate gates (joint decision of the
round 2 deadlock, B1). `readiness_problems()` returns why a freeze would be certain to produce an invalid live run:

* every slot of config.REQUIRED_RULINGS (P1 transport notices, P2 unknown usage, P3 quota observation source, P4 CLI
  notice annex, P5 startup manifest and effective instruction context, D1 authentication source attribution, D6
  focused verification and independent operation attestation) must
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
                    'P5': ('startup_manifest', 'effective_context_evidence'), 'D1': ('attribution_evidence',),
                    'D6': ('focused_verification', 'operation_attestation')}
# Closure round 1 (O5, Astra council round 3 item 32): D6 binds two annexes. The focused verification record covers
# the complete closure checklist of the round 2 joint decision (D6: the checklist, one focused verification call);
# the independent operation attestation is the blind review of the operations, bound to the classification and the
# operation files it attests. Each item needs the verdict `pass`.
D6_CHECKLIST = ('rulings_and_annexes', 'authentication', 'instruction_exclusion', 'executable_binding',
                'quota_semantics', 'redaction_recovery', 'timing_bounds', 'independent_scoring',
                'atomic_reservations', 'identities', 'recovery', 'predecessor_evidence', 'acceptance_suite_unchanged',
                'red_team_reproductions', 'new_regressions', 'fake_replacement_and_recovery_exercise')
ATTESTATION_COVERS = ('oracle_correctness', 'classification', 'contract_extraction', 'consumer_checks',
                      'representative_cases', 'challenge_cases', 'sealing_and_access_chronology')
ATTESTATION_CASES = {'representative_cases': 48, 'challenge_cases': 16}
OPS_DIR = config.HERE / 'ops'


def ops_manifest():
    """sha256 (line endings normalized) of every file of the operations under attestation, by repo relative path."""
    out = {}
    for f in sorted(OPS_DIR.rglob('*')) if OPS_DIR.is_dir() else []:
        if f.is_file() and '__pycache__' not in f.parts:
            data = f.read_bytes().replace(b'\r\n', b'\n')
            out[f.relative_to(config.REPO).as_posix()] = hashlib.sha256(data).hexdigest()
    return out


def d6_problems(kind, doc):
    """The content of a D6 annex: every checklist or attestation item present with verdict `pass`, the case counts,
    an attestor recorded as independent of the implementer, and the attestation bound to the classification and the
    operation files the harness uses now."""
    if not isinstance(doc, dict):
        return [f'ruling D6: annex {kind} is not a JSON object']
    problems = []
    items = doc.get('checklist' if kind == 'focused_verification' else 'covers')
    items = items if isinstance(items, dict) else {}
    want = D6_CHECKLIST if kind == 'focused_verification' else ATTESTATION_COVERS
    missing = [k for k in want if not isinstance(items.get(k), dict) or items[k].get('verdict') != 'pass']
    if missing:
        problems.append(f'ruling D6: annex {kind} does not pass {missing}')
    if kind == 'operation_attestation':
        for k, n in ATTESTATION_CASES.items():
            if not isinstance(items.get(k), dict) or items[k].get('count') != n:
                problems.append(f'ruling D6: the attestation does not cover the {n} {k.replace("_", " ")}')
        attestor = str(doc.get('attestor') or '')
        implementer = str(doc.get('implementer') or '')
        if not attestor or not implementer or doc.get('independent') is not True \
                or attestor.lower() == implementer.lower():
            problems.append('ruling D6: the operation attestation is not recorded as independent of the implementer')
        if doc.get('classification_sha256') != isolation.sha256_file(config.CLASSIFICATION_FILE):
            problems.append('ruling D6: the attestation is not bound to the classification the harness uses')
        if doc.get('ops_sha256') != ops_manifest():
            problems.append('ruling D6: the attestation is not bound to the operation files the harness uses')
    return problems


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
        if kind in ('focused_verification', 'operation_attestation'):
            try:
                doc = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                doc = None
            problems += d6_problems(kind, doc)
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


def bound_problems(record_doc) -> list:
    """Closure round 1 (O5): the scorer's check of the rulings a run's freeze bound (freeze.json
    signed_exceptions.rulings): every required slot, D6 included, is bound with its annexes, and each bound file still
    hashes to its recorded value and, for D6, still satisfies its content and bindings."""
    record_doc = record_doc if isinstance(record_doc, dict) else {}
    problems = []
    for name in config.REQUIRED_RULINGS:
        entry = record_doc.get(name)
        if not isinstance(entry, dict) or not entry.get('path') or not entry.get('sha256'):
            problems.append(f'the run bound freeze binds no ruling {name}')
            continue
        path = config.REPO / entry['path']
        if not path.is_file() or _sha(path) != entry['sha256']:
            problems.append(f'ruling {name} differs from the run bound freeze')
            continue
        problems += annex_problems(name, entry, path.read_text(encoding='utf-8', errors='replace'))
    return problems


def record(slots=None) -> dict:
    """The ruling files and hashes freeze.json binds (signed_exceptions.rulings)."""
    slots = config.SIGNED_RULINGS if slots is None else slots
    return {name: {'path': (slots.get(name) or {}).get('path'), 'sha256': (slots.get(name) or {}).get('sha256'),
                   'annexes': (slots.get(name) or {}).get('annexes')}
            for name in config.REQUIRED_RULINGS}
