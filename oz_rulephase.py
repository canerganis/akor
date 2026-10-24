"""oz-rule/1 rule phase for `oz map --learn` (build step 4): rule store, admission of bootstrap candidates, D1 rule
adoption, fallback decisions, blind audits and quarantine. Standard library only, no model calls.

Normative texts: docs/design/brainstorm-2026-10-24/05-joint-record.md (sections 2 to 6),
docs/design/ozmap-2026-10-24/oz-rule-1-spec.md and oz-rule-1-amendment-1.md (D1, D2, D6 to D9 here).

Rule store. Its own SQLite file (never the memo store), <workspace>/map/rules.sqlite by default. A rule row holds the
operation, the full bindings and their key, the immutable candidate AST bytes and SHA256 (NULL for "none" or a failed
bootstrap), the status admitted / rejected / quarantined, the complete admission response and the provenance (producer,
submission, bootstrap run, receipt, physical call ID, side file and envelope hashes). Triggers make every column but
the status immutable, and the status can only move admitted -> quarantined. The key covers (D7 and D2): the registry's
contract, check, permission, dataset, input policy and worker hashes, the interpreter version (oz-rule/1 plus the
SHA256 of oz_rule.py), the map's own input policy, the map worker_hash (the full route) and the map contract (operation,
instruction, goal and pinned map checks). A rule is reused only under an identical key.

Rule results. A covered job is committed in the rule store's own `results` table by adopt_rule (D1), never through
oz_do, so a rule result can never reach memo storage. In one IMMEDIATE transaction the host re-reads the rule row,
requires status admitted, the same binding key and the same AST hash, re-hashes the job's resolved input against its
receipt, re-evaluates the exact stored AST bytes (rule_provenance/1) and requires status value with an identical type
and canonical value; only then the row is inserted. Every pinned consumer check (the registry's and the map's
--check specs) must have passed before; an inconclusive check is not a pass. Any other outcome is a fallback to the
model through ordinary oz_do. Every decision is recorded in `decisions`.

Audits. Per wave (one producer submission) the host selects min(32, covered) covered jobs uniformly without
replacement: covered jobs ordered by SHA256(canonical([seed, logical path])), the first k taken (a seeded random
permutation that is identical for every arm given the same dataset paths and seed). The selection is persisted once.
An audit job has its own delivery identity (D8) linked to the original; its packet carries only the instruction and
the job's input text, never the rule's answer. A disagreement quarantines the rule atomically together with the audit
record; results already emitted stay recorded. READING: an audit whose model job did not end accepted, or was
answered from memo storage, is "inconclusive" (no blind model answer exists), counted and reported, and does not
quarantine.

READING notes are marked "READING" below.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import time

from oz import Error
import oz_accept
from oz_batch import J
import oz_registry
from oz_registry import RegistryError, canonical, digest
import oz_rule

SCHEMA_VERSION = 'oz.rulestore/1'
AUDIT_SAMPLE = 32
SPEC_PATH = Path(__file__).resolve().parent / 'docs' / 'design' / 'ozmap-2026-10-24' / 'oz-rule-1-spec.md'
SPEC_START, SPEC_END = '`oz-rule/1` is an opt-in', '**Evaluation and admission.**'
# The language part of the normative spec (representation, types, text and numbers, failure and bounds); worked ASTs,
# conformance vectors and admission text are excluded so no designer-written rule for the pilot operations is shown.
SPEC_EXCERPT_SHA256 = '563b6e32846fbd5a151cbca4ca2dc2bdf0019454ff3e5454a51244b3ca1fefc2'
INTERPRETER = {'lang': oz_rule.LANG,
               'source_sha256': hashlib.sha256(Path(oz_rule.__file__).read_bytes()).hexdigest()}
STATUSES = ('admitted', 'rejected', 'quarantined')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rules(
    id INTEGER PRIMARY KEY, binding_key TEXT NOT NULL, operation TEXT NOT NULL, bindings TEXT NOT NULL,
    ast BLOB, ast_sha256 TEXT, status TEXT NOT NULL CHECK(status IN ('admitted','rejected','quarantined')),
    admission TEXT NOT NULL, provenance TEXT NOT NULL, source TEXT NOT NULL UNIQUE, at REAL NOT NULL,
    quarantined_at REAL, quarantine TEXT);
CREATE INDEX IF NOT EXISTS rule_keys ON rules(binding_key, id);
CREATE TRIGGER IF NOT EXISTS rules_immutable BEFORE UPDATE OF id, binding_key, operation, bindings, ast, ast_sha256,
    admission, provenance, source, at ON rules BEGIN SELECT RAISE(ABORT, 'rule rows are immutable'); END;
CREATE TRIGGER IF NOT EXISTS rules_status BEFORE UPDATE OF status ON rules
    WHEN NOT (OLD.status = 'admitted' AND NEW.status = 'quarantined')
    BEGIN SELECT RAISE(ABORT, 'a rule status only moves from admitted to quarantined'); END;
CREATE TRIGGER IF NOT EXISTS rules_keep BEFORE DELETE ON rules BEGIN SELECT RAISE(ABORT, 'rules are kept'); END;
CREATE TABLE IF NOT EXISTS results(
    job TEXT PRIMARY KEY, rule INTEGER NOT NULL REFERENCES rules(id), binding_key TEXT NOT NULL,
    producer TEXT NOT NULL, submission TEXT NOT NULL, operation TEXT NOT NULL, path TEXT NOT NULL,
    resolved_sha256 TEXT NOT NULL, type TEXT NOT NULL, value TEXT NOT NULL, steps INTEGER NOT NULL,
    checks TEXT NOT NULL, provenance TEXT NOT NULL, at REAL NOT NULL);
CREATE TRIGGER IF NOT EXISTS results_immutable BEFORE UPDATE ON results
    BEGIN SELECT RAISE(ABORT, 'rule results are immutable'); END;
CREATE TABLE IF NOT EXISTS decisions(
    seq INTEGER PRIMARY KEY, job TEXT NOT NULL, rule INTEGER, decision TEXT NOT NULL, reason TEXT, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bootstraps(
    producer TEXT NOT NULL, submission TEXT NOT NULL, binding_key TEXT NOT NULL, request_id TEXT NOT NULL,
    paths TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY(producer, submission, binding_key));
CREATE TABLE IF NOT EXISTS waves(
    producer TEXT NOT NULL, submission TEXT NOT NULL, rule INTEGER NOT NULL, covered_sha256 TEXT NOT NULL,
    seed INTEGER NOT NULL, covered TEXT NOT NULL, selected TEXT NOT NULL, at REAL NOT NULL,
    PRIMARY KEY(producer, submission, rule, covered_sha256));
CREATE TABLE IF NOT EXISTS audits(
    audit_job TEXT PRIMARY KEY, original_job TEXT NOT NULL, rule INTEGER NOT NULL, producer TEXT NOT NULL,
    submission TEXT NOT NULL, path TEXT NOT NULL, verdict TEXT NOT NULL, rule_value TEXT NOT NULL, model_value TEXT,
    detail TEXT, call_id TEXT, request_id TEXT, at REAL NOT NULL)
'''


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def spec_excerpt(path: Path = SPEC_PATH) -> str:
    """The oz-rule/1 language specification excerpt shown in the bootstrap, verified against its pinned SHA256."""
    try:
        text = Path(path).read_bytes().decode('utf-8').replace('\r\n', '\n')
        excerpt = text[text.index(SPEC_START):text.index(SPEC_END)].rstrip()
    except (OSError, UnicodeError, ValueError):
        raise Error(f'cannot read the oz-rule/1 specification excerpt from {path}') from None
    if sha256_text(excerpt) != SPEC_EXCERPT_SHA256:
        raise Error('the oz-rule/1 specification excerpt changed; refusing to bootstrap with an unpinned spec')
    return excerpt


def map_inputs(op_text: str, text: str):
    """oz_accept Inputs for one job with one string reference, as a packet would carry it."""
    return oz_accept.Inputs(({'op': op_text, 'refs': [J(text)]},))


def value_text_of(value) -> str:
    """Compact JSON of a model value as a row carries it (RawJSON numerals keep their spelling)."""
    from oz_reply import dumps
    return dumps(value, ensure_ascii=False, separators=(',', ':'))


def audit_order(paths, seed: int) -> list:
    """The seeded uniform permutation of the covered paths used for audit selection."""
    return sorted(paths, key=lambda p: (hashlib.sha256(canonical([int(seed), p])).hexdigest(), p))


def select_audits(paths, seed: int, k: int = AUDIT_SAMPLE) -> list:
    """min(k, len(paths)) paths, uniformly without replacement for the frozen seed (READING: a hash permutation, so
    the selection never depends on Python's random module or on delivery identities)."""
    if type(seed) is not int or isinstance(seed, bool):
        raise Error('the audit seed must be an integer')
    return audit_order(sorted(set(paths)), seed)[:min(k, len(set(paths)))]


class RuleStore:
    """The rule store. One connection, autocommit off by hand (BEGIN IMMEDIATE for every write)."""

    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        with self.transaction():
            for statement in SCHEMA.split(';\n'):
                if statement.strip():
                    self.db.execute(statement)
            self.db.execute('INSERT OR IGNORE INTO meta VALUES (?, ?)', ('schema', SCHEMA_VERSION))
        if self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] != SCHEMA_VERSION:
            raise Error(f'{self.path} is not an {SCHEMA_VERSION} rule store')

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    class _Tx:
        def __init__(self, db):
            self.db = db

        def __enter__(self):
            self.db.execute('BEGIN IMMEDIATE')
            return self.db

        def __exit__(self, kind, *_):
            if kind is None:
                self.db.commit()
            else:
                self.db.rollback()

    def transaction(self):
        return self._Tx(self.db)

    # ------------------------------------------------------------------------------------------------ rules

    @staticmethod
    def _rule(row) -> dict | None:
        if row is None:
            return None
        out = dict(row)
        out['ast'] = bytes(out['ast']) if out['ast'] is not None else None
        for key in ('bindings', 'admission', 'provenance', 'quarantine'):
            if out.get(key) is not None:
                out[key] = json.loads(out[key])
        return out

    def rule(self, rule_id: int) -> dict | None:
        return self._rule(self.db.execute('SELECT * FROM rules WHERE id=?', (rule_id,)).fetchone())

    def rules(self, binding_key: str | None = None) -> list:
        if binding_key is None:
            rows = self.db.execute('SELECT * FROM rules ORDER BY id')
        else:
            rows = self.db.execute('SELECT * FROM rules WHERE binding_key=? ORDER BY id', (binding_key,))
        return [self._rule(r) for r in rows]

    def active(self, binding_key: str) -> dict | None:
        """The earliest admitted rule for the key, or None."""
        return self._rule(self.db.execute("SELECT * FROM rules WHERE binding_key=? AND status='admitted' "
                                          'ORDER BY id LIMIT 1', (binding_key,)).fetchone())

    def add_rule(self, *, binding_key: str, operation: str, bindings: dict, ast: bytes | None, status: str,
                 admission: dict, provenance: dict, source: str) -> int:
        """Record one candidate outcome; idempotent on source (the bootstrap call and operation)."""
        if status not in ('admitted', 'rejected'):
            raise Error('a new rule is admitted or rejected')
        if status == 'admitted' and ast is None:
            raise Error('an admitted rule needs its AST bytes')
        with self.transaction() as db:
            row = db.execute('SELECT id FROM rules WHERE source=?', (source,)).fetchone()
            if row is not None:
                return row[0]
            cur = db.execute('INSERT INTO rules(binding_key, operation, bindings, ast, ast_sha256, status, admission, '
                             'provenance, source, at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                             (binding_key, operation, canonical(bindings).decode('utf-8'),
                              sqlite3.Binary(ast) if ast is not None else None,
                              hashlib.sha256(ast).hexdigest() if ast is not None else None, status,
                              J(admission), J(provenance), source, self.clock()))
            return cur.lastrowid

    def quarantine(self, rule_id: int, reason: dict, audit: dict | None = None) -> bool:
        """Atomically move an admitted rule to quarantined (with the audit record that caused it). True if it moved."""
        with self.transaction() as db:
            if audit is not None:
                self._insert_audit(db, audit)
            cur = db.execute("UPDATE rules SET status='quarantined', quarantined_at=?, quarantine=? "
                             "WHERE id=? AND status='admitted'", (self.clock(), J(reason), rule_id))
            return cur.rowcount == 1

    # ---------------------------------------------------------------------------------------------- results

    def result(self, job: str) -> dict | None:
        row = self.db.execute('SELECT * FROM results WHERE job=?', (job,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out['checks'] = json.loads(out['checks'])
        out['provenance'] = json.loads(out['provenance'])
        return out

    def results(self) -> list:
        return [self.result(r[0]) for r in self.db.execute('SELECT job FROM results ORDER BY rowid')]

    def decide(self, job: str, rule: int | None, decision: str, reason: str | None = None) -> None:
        with self.transaction() as db:
            db.execute('INSERT INTO decisions(job, rule, decision, reason, at) VALUES (?,?,?,?,?)',
                       (job, rule, decision, reason, self.clock()))

    def decisions(self) -> list:
        return [dict(r) for r in self.db.execute('SELECT * FROM decisions ORDER BY seq')]

    def adopt_rule(self, *, rule: dict, binding_key: str, job: str, text: str, resolved_sha256: str, first: dict,
                   checks: list, owner: dict, evaluate=oz_rule.evaluate, before_commit=None) -> tuple:
        """D1 adoption in one IMMEDIATE transaction. Returns ("adopted", row), ("present", row) for a job already
        committed, or ("refused", reason) with nothing written. first is the evaluation the checks judged."""
        with self.transaction() as db:
            if before_commit is not None:
                before_commit(db)
            present = db.execute('SELECT job FROM results WHERE job=?', (job,)).fetchone()
            if present is not None:
                return 'present', None
            row = self._rule(db.execute('SELECT * FROM rules WHERE id=?', (rule['id'],)).fetchone())
            if row is None or row['status'] != 'admitted':
                return 'refused', 'quarantined' if row is not None and row['status'] == 'quarantined' else 'not_admitted'
            if row['binding_key'] != binding_key or rule['binding_key'] != binding_key:
                return 'refused', 'binding_changed'
            ast = row['ast']
            if (ast is None or hashlib.sha256(ast).hexdigest() != row['ast_sha256']
                    or row['ast_sha256'] != rule['ast_sha256'] or row['admission'].get('ast_hash') != row['ast_sha256']):
                return 'refused', 'ast_changed'
            if sha256_text(text) != resolved_sha256:
                return 'refused', 'input_changed'
            # rule_provenance/1: the exact admitted AST bytes, re-evaluated against this job's resolved input.
            again = evaluate(ast, text)
            if (not isinstance(again, dict) or again.get('status') != 'value' or again.get('type') != first['type']
                    or oz_rule.canonical_value_text(again) != oz_rule.canonical_value_text(first)):
                return 'refused', 'provenance_failed'
            value = oz_rule.canonical_value_text(first)
            provenance = {'check': 'rule_provenance/1', 'ast_sha256': row['ast_sha256'], 'steps': again['steps'],
                          'interpreter': INTERPRETER, 'reevaluated': True}
            db.execute('INSERT INTO results(job, rule, binding_key, producer, submission, operation, path, '
                       'resolved_sha256, type, value, steps, checks, provenance, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (job, row['id'], binding_key, owner['producer'], owner['submission'], owner['operation'],
                        owner['path'], resolved_sha256, first['type'], value, first['steps'], J(checks),
                        J(provenance), self.clock()))
        return 'adopted', self.result(job)

    # ---------------------------------------------------------------------------------- bootstrap and waves

    def bootstrap(self, producer: str, submission: str, binding_key: str) -> dict | None:
        row = self.db.execute('SELECT * FROM bootstraps WHERE producer=? AND submission=? AND binding_key=?',
                              (producer, submission, binding_key)).fetchone()
        return None if row is None else dict(row, paths=json.loads(row['paths']))

    def record_bootstrap(self, producer: str, submission: str, binding_key: str, request_id: str, paths) -> dict:
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO bootstraps VALUES (?,?,?,?,?,?)',
                       (producer, submission, binding_key, request_id, J(list(paths)), self.clock()))
        return self.bootstrap(producer, submission, binding_key)

    def wave(self, producer: str, submission: str, rule: int, seed: int, covered) -> dict:
        """The persisted audit selection for this wave, made once from the covered paths and the seed. A wave is one
        producer submission's covered set under one rule: resuming it returns the same selection (no new audit job),
        and the seed of a submission is frozen once its first wave is drawn."""
        covered = sorted(set(covered))
        key = sha256_text(J(covered))
        with self.transaction() as db:
            earlier = db.execute('SELECT seed FROM waves WHERE producer=? AND submission=? AND rule=? LIMIT 1',
                                 (producer, submission, rule)).fetchone()
            if earlier is not None and earlier[0] != seed:
                raise Error(f'this submission was audited with seed {earlier[0]}; the seed is frozen')
            find = ('SELECT * FROM waves WHERE producer=? AND submission=? AND rule=? AND covered_sha256=?',
                    (producer, submission, rule, key))
            row = db.execute(*find).fetchone()
            if row is None:
                db.execute('INSERT INTO waves VALUES (?,?,?,?,?,?,?,?)',
                           (producer, submission, rule, key, seed, J(covered), J(select_audits(covered, seed)),
                            self.clock()))
                row = db.execute(*find).fetchone()
        out = dict(row)
        out['covered'], out['selected'] = json.loads(out['covered']), json.loads(out['selected'])
        return out

    @staticmethod
    def _insert_audit(db, audit: dict) -> None:
        db.execute('INSERT OR IGNORE INTO audits VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (audit['audit_job'], audit['original_job'], audit['rule'], audit['producer'], audit['submission'],
                    audit['path'], audit['verdict'], audit['rule_value'], audit.get('model_value'),
                    audit.get('detail'), audit.get('call_id'), audit.get('request_id'), time.time()))

    def record_audit(self, audit: dict) -> None:
        with self.transaction() as db:
            self._insert_audit(db, audit)

    def audit(self, audit_job: str) -> dict | None:
        row = self.db.execute('SELECT * FROM audits WHERE audit_job=?', (audit_job,)).fetchone()
        return None if row is None else dict(row)

    def audits(self) -> list:
        return [dict(r) for r in self.db.execute('SELECT * FROM audits ORDER BY rowid')]


class Learner:
    """One operation's learning context: verified registry package (or its ineligibility), full bindings and key."""

    def __init__(self, store: RuleStore, registry, operation: str, *, worker_hash: str, map_contract: str,
                 map_input_policy: str):
        if not isinstance(registry, oz_registry.Registry):
            raise Error('--learn needs an owner-approved oz_registry.Registry (--registry MANIFEST)')
        if not isinstance(worker_hash, str) or len(worker_hash) != 64:
            raise Error('--learn needs the full worker identity (worker_hash); a model label is not enough (D7)')
        self.store, self.registry, self.operation = store, registry, operation
        self.worker_hash = worker_hash
        manifest_ops = registry._manifest['operations']
        if operation not in manifest_ops:
            raise Error(f'operation {operation!r} is not in the registry; --learn needs a registered operation')
        self.package, self.eligible, self.ineligible_reason = None, True, None
        try:
            self.package = registry.resolve(operation, {'worker_hash': worker_hash})
        except RegistryError as exc:
            if exc.code != 'ineligible':
                raise Error(f'registry refused operation {operation!r}: {exc}') from None
            # The resolver verified every hash before it judged eligibility; the bootstrap still runs (it measures the
            # learning attempt) and any candidate is rejected as ineligible.
            self.eligible, self.ineligible_reason = False, str(exc)
        op = manifest_ops[operation]
        self.contract = self.package.contract if self.package else op['contract']
        registry_bindings = (self.package.bindings if self.package else
                             {'contract_hash': op['contract_hash'], 'check_hash': op['check_hash'],
                              'permission_hash': op['permission_hash'], 'worker_hash': op['worker_hash'],
                              'dataset_hash': op['dataset']['dataset_hash'],
                              'input_policy_hash': op['input_policy_hash']})
        policy = self.package.input_policy if self.package else op['input_policy']
        if policy.get('terminal_newline') != 'strip_one' or policy.get('text_ref') != 0:
            raise Error('the registry input policy must strip one terminal newline from text reference 0, as oz map '
                        'resolves inputs (D2)')
        self.bindings = {'operation_id': operation, 'registry': dict(registry_bindings), 'interpreter': INTERPRETER,
                         'map_input_policy': map_input_policy, 'worker_hash': worker_hash, 'map_contract': map_contract}
        self.key = digest(self.bindings)

    def bootstrap_config(self, side_dir: Path) -> dict:
        return {'schema': 'oz.bootstrap.config/1', 'side_dir': str(side_dir), 'ops': [self.operation],
                'contracts': {self.operation: self.contract}, 'eligibility': {self.operation: self.eligible},
                'spec': spec_excerpt(), 'binding_key': self.key}

    def admit_side(self, side: dict | None, *, source: str, provenance: dict) -> int:
        """Record the bootstrap outcome for the operation: admitted, or rejected with the reason. Idempotent."""
        ast, status = None, 'rejected'
        if side is None:
            admission = {'status': 'rejected', 'reasons': ['bootstrap_missing']}
        elif side.get('status') != 'ok':
            admission = {'status': 'rejected', 'reasons': ['bootstrap_' + str(side.get('status'))],
                         'detail': side.get('reason')}
        else:
            proposal = (side.get('rules') or {}).get(self.operation)
            if proposal == 'none' or proposal is None:
                admission = {'status': 'rejected', 'reasons': ['none_proposed']}
            else:
                ast = proposal['ast'].encode('utf-8')
                if hashlib.sha256(ast).hexdigest() != proposal['ast_sha256']:
                    ast, admission = None, {'status': 'rejected', 'reasons': ['side_file_hash_mismatch']}
                else:
                    admission = self.registry.admit(ast, self.operation, {'worker_hash': self.worker_hash})
                    if (admission['status'] == 'accepted' and self.eligible
                            and admission.get('bindings') == self.bindings['registry']
                            and admission.get('ast_hash') == hashlib.sha256(ast).hexdigest()):
                        status = 'admitted'
        return self.store.add_rule(binding_key=self.key, operation=self.operation, bindings=self.bindings, ast=ast,
                                   status=status, admission=admission, provenance=provenance, source=source)

    def attempt(self, rule: dict, *, job: str, text: str, resolved_sha256: str, op_text: str, map_pinned,
                owner: dict, evaluate=oz_rule.evaluate, before_commit=None) -> dict:
        """One job's rule decision: {"decision": "rule", "row"} or {"decision": "fallback", "reason"}. Recorded."""
        def fallback(reason):
            self.store.decide(job, rule['id'], 'fallback', reason)
            return {'decision': 'fallback', 'reason': reason}

        done = self.store.result(job)
        if done is not None:
            return {'decision': 'rule', 'row': done, 'resumed': True}
        if self.package is None:
            return fallback('ineligible')
        first = evaluate(rule['ast'], text)
        if not isinstance(first, dict) or first.get('status') != 'value':
            return fallback('abstain:' + str((first or {}).get('reason')))
        value_text = oz_rule.canonical_value_text(first)
        verdicts = [dict(v, source='registry') for v in self.package.run_checks(value_text, text)]
        for v in oz_accept.run_checks(value_text, map_inputs(op_text, text), map_pinned):
            verdicts.append({'id': None, 'check': v['check'], 'version': v['version'], 'verdict': v['verdict'],
                             'source': 'map'})
        failed = [v for v in verdicts if v['verdict'] != 'pass']
        if failed:
            kind = 'check_failed' if any(v['verdict'] == 'fail' for v in failed) else 'check_inconclusive'
            return fallback(kind + ':' + ','.join(f"{v['check']}@{v['version']}" for v in failed))
        state, detail = self.store.adopt_rule(rule=rule, binding_key=self.key, job=job, text=text,
                                              resolved_sha256=resolved_sha256, first=first, checks=verdicts,
                                              owner=owner, evaluate=evaluate, before_commit=before_commit)
        if state == 'refused':
            return fallback('commit_refused:' + detail)
        self.store.decide(job, rule['id'], 'rule', None)
        return {'decision': 'rule', 'row': self.store.result(job), 'resumed': state == 'present'}


def read_side_files(side_dir: Path) -> list:
    """The bootstrap side records in a side directory (one per physical bootstrap call), by receipt."""
    out = []
    for file in sorted(Path(side_dir).glob('*.json')) if Path(side_dir).is_dir() else ():
        if file.name == 'config.json':
            continue
        try:
            record = json.loads(file.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get('schema') == 'oz.bootstrap.side/1':
            out.append(dict(record, file=file.name))
    return out
