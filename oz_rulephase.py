"""oz-rule/1 rule phase (build step 4, revised after council 2): rule store, authoritative job settlement, admission of
exact bootstrap AST bytes, D1 rule adoption, evaluation-wave audits, quarantine and the shared experiment store.
Standard library only, no model calls.

Normative texts: docs/design/brainstorm-2026-10-24/05-joint-record.md (sections 2 to 6), oz-rule-1-spec.md,
oz-rule-1-amendment-1.md (D1 to D9) and docs/design/ozmap-2026-10-24/amendment-2-and-step6-architecture.md with
council2-astra.md (blockers 1, 2, 3, 8 and the rulings).

Rule store (one SQLite file per arm host, never the memo store).
  rules        operation, full bindings and key, the EXACT admitted AST bytes and SHA256, status admitted / rejected /
               quarantined, the complete admission response and provenance. Every column but the status is immutable,
               the status only moves admitted -> quarantined, rows are never deleted; an idempotent insert with a
               different payload raises.
  settlements  the authoritative per-job settlement record (blocker 1): immutable payload, binding and required-check
               hashes, an execution generation, a state open / awaiting_verification / settled / failed and exactly one
               winner (rule or model) when settled. Opening a job again validates its identity; a mismatch raises. A
               settled row never changes again; neither does a failed one (council 3, Opus A: a model answer that
               fails a pinned check is a terminal failure, so a resumed host never sends that job again).
  emissions    every value ever produced for a job (rule or model), with its check evidence and outcome: settled,
               refused, awaiting_verification, failed. Never updated or deleted: the history of earlier emissions.
  results      the rule-winner rows (adopt_rule), immutable.
  decisions    one line per rule-phase decision (rule, staged, awaiting_verification, fallback and its reason).
  audits       one row per blind audit job: wave, original job, frozen dataset id, the rule's value and the verdict
               pending -> agree / disagree / inconclusive (inconclusive may still resolve on the reserve retry). A
               disagreement quarantines the rule in the same transaction.

Settlement boundary (blocker 2). A job opens with the list of every applicable pinned check: the registry's consumer
checks and the map's --check specs (identities "registry:<id>:<name>@<v>" and "map:<k>:<name>@<v>"). settle_model and
adopt_rule themselves compare the supplied evidence with that list inside the committing IMMEDIATE transaction: a
missing or inconclusive verdict makes the job awaiting_verification (never accepted), a failing verdict refuses it,
and only complete passing evidence settles it. The caller is not trusted. The generation fences stale executions: a
settlement must name the job's current generation, and claim() increments it (a resumed host claims again, so an
older in-flight execution can no longer settle). The first valid settlement wins; any later one is kept as a refused
emission.

Exact AST bytes (ruling, implementer reading 2). The shim's side file carries each AST as ast_b64, its SHA256 and
length. decode_ast decodes strictly, requires the length, at most 2,048 bytes, the hash and valid UTF-8; admission,
storage and every re-evaluation use exactly those bytes.

Experiment store (one SQLite file per experiment directory, shared by the B and C hosts of every backend):
  assignments  the frozen bootstrap assignment per (backend, workload): exactly 16 dataset ids from each of the 4
               producers, chosen by seeded hash order of the frozen dataset ids (never by arrival).
  bootstraps   one claim and one immutable record per (backend, workload): answers by dataset id, the raw side file,
               the attempt ledger entry, the status and efficiency_valid. Recorded once, imported by B and C, never
               re-learned. A2.1: a failed bootstrap records its failure; no replacement answers, no revision.
  audit_waves  per evaluation wave (wave id = canonical([backend, workload, wave])) and rule (its AST SHA256): the
               complete eligible population of frozen dataset ids and the min(32, covered) selection, persisted before
               any audit dispatch. A second arm reads the same row, so B and C audit identical dataset ids.
  wave_manifests  the sealed manifest of one (backend, workload, wave), written by the first arm before any call:
               every dataset id bound to exactly one operation, input hash, producer and key (council 3, B12). Every
               later arm must derive the identical manifest or it refuses to run; A, B and C consume the same data.

READING notes are marked "READING" below.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from oz import Error
import oz_accept
from oz_batch import J
import oz_registry
from oz_registry import CheckUnavailable, RegistryError, canonical, digest
import oz_rule

SCHEMA_VERSION = 'oz.rulestore/3'
EXPERIMENT_SCHEMA = 'oz.experiment/2'
RECORD_SCHEMA = 'oz.bootstrap.record/1'
CONFIG_SCHEMA = 'oz.bootstrap.config/2'
SIDE_SCHEMA = 'oz.bootstrap.side/2'
AUDIT_SAMPLE = 32
MAX_AST_BYTES = 2048
BOOTSTRAP_PER_PRODUCER = 16
BOOTSTRAP_PRODUCERS = 4
# READING (ruling 5): oz_rule.py imports only the standard library and holds every evaluation semantic, so its source
# hash identifies the interpreter.
INTERPRETER = {'lang': oz_rule.LANG,
               'source_sha256': hashlib.sha256(Path(oz_rule.__file__).read_bytes()).hexdigest()}
STATUSES = ('admitted', 'rejected', 'quarantined')
VERDICTS = ('pending', 'agree', 'disagree', 'inconclusive')

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
CREATE TRIGGER IF NOT EXISTS rules_quarantine BEFORE UPDATE OF quarantined_at, quarantine ON rules
    WHEN OLD.status = 'quarantined' BEGIN SELECT RAISE(ABORT, 'quarantine metadata is immutable'); END;
CREATE TRIGGER IF NOT EXISTS rules_keep BEFORE DELETE ON rules BEGIN SELECT RAISE(ABORT, 'rules are kept'); END;
CREATE TABLE IF NOT EXISTS settlements(
    job TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL, bindings_sha256 TEXT NOT NULL, required TEXT NOT NULL,
    generation INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('open','awaiting_verification','settled','failed')),
    winner TEXT CHECK(winner IN ('rule','model')), emission INTEGER, opened_at REAL NOT NULL, settled_at REAL,
    CHECK((state = 'settled') = (winner IS NOT NULL)));
CREATE TRIGGER IF NOT EXISTS settlements_identity BEFORE UPDATE OF job, payload_sha256, bindings_sha256, required,
    opened_at ON settlements BEGIN SELECT RAISE(ABORT, 'settlement identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS settlements_final BEFORE UPDATE ON settlements WHEN OLD.state IN ('settled','failed')
    BEGIN SELECT RAISE(ABORT, 'a settled or failed job never changes'); END;
CREATE TRIGGER IF NOT EXISTS settlements_keep BEFORE DELETE ON settlements
    BEGIN SELECT RAISE(ABORT, 'settlements are kept'); END;
CREATE TABLE IF NOT EXISTS emissions(
    seq INTEGER PRIMARY KEY, job TEXT NOT NULL, generation INTEGER NOT NULL,
    source TEXT NOT NULL CHECK(source IN ('rule','model')), phase TEXT NOT NULL, type TEXT, value TEXT NOT NULL,
    checks TEXT NOT NULL, outcome TEXT NOT NULL CHECK(outcome IN ('settled','refused','awaiting_verification','failed')),
    reason TEXT, rule INTEGER, call_id TEXT, at REAL NOT NULL);
CREATE TRIGGER IF NOT EXISTS emissions_immutable BEFORE UPDATE ON emissions
    BEGIN SELECT RAISE(ABORT, 'emissions are history'); END;
CREATE TRIGGER IF NOT EXISTS emissions_keep BEFORE DELETE ON emissions
    BEGIN SELECT RAISE(ABORT, 'emissions are history'); END;
CREATE TABLE IF NOT EXISTS results(
    job TEXT PRIMARY KEY, rule INTEGER NOT NULL REFERENCES rules(id), binding_key TEXT NOT NULL,
    producer TEXT NOT NULL, submission TEXT NOT NULL, operation TEXT NOT NULL, path TEXT NOT NULL,
    resolved_sha256 TEXT NOT NULL, type TEXT NOT NULL, value TEXT NOT NULL, steps INTEGER NOT NULL,
    checks TEXT NOT NULL, provenance TEXT NOT NULL, at REAL NOT NULL);
CREATE TRIGGER IF NOT EXISTS results_immutable BEFORE UPDATE ON results
    BEGIN SELECT RAISE(ABORT, 'rule results are immutable'); END;
CREATE TRIGGER IF NOT EXISTS results_keep BEFORE DELETE ON results
    BEGIN SELECT RAISE(ABORT, 'rule results are kept'); END;
CREATE TABLE IF NOT EXISTS decisions(
    seq INTEGER PRIMARY KEY, job TEXT NOT NULL, rule INTEGER, decision TEXT NOT NULL, reason TEXT, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audits(
    audit_job TEXT PRIMARY KEY, wave_id TEXT NOT NULL, original_job TEXT NOT NULL, rule INTEGER NOT NULL,
    producer TEXT NOT NULL, submission TEXT NOT NULL, dataset_id TEXT NOT NULL, rule_value TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK(verdict IN ('pending','agree','disagree','inconclusive')), model_value TEXT,
    detail TEXT, call_id TEXT, attempt_id TEXT, created_at REAL NOT NULL, decided_at REAL);
CREATE TRIGGER IF NOT EXISTS audits_identity BEFORE UPDATE OF audit_job, wave_id, original_job, rule, producer,
    submission, dataset_id, rule_value, created_at ON audits BEGIN SELECT RAISE(ABORT, 'audit identity is immutable'); END;
CREATE TRIGGER IF NOT EXISTS audits_verdict BEFORE UPDATE OF verdict ON audits
    WHEN NOT (OLD.verdict = 'pending' OR (OLD.verdict = 'inconclusive' AND NEW.verdict IN ('agree','disagree')))
    BEGIN SELECT RAISE(ABORT, 'an audit verdict only moves from pending (or inconclusive, on its retry)'); END;
CREATE TRIGGER IF NOT EXISTS audits_keep BEFORE DELETE ON audits BEGIN SELECT RAISE(ABORT, 'audits are kept'); END
'''

EXPERIMENT_TABLES = '''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assignments(
    backend TEXT NOT NULL, workload TEXT NOT NULL, assignment TEXT NOT NULL, sha256 TEXT NOT NULL, at REAL NOT NULL,
    PRIMARY KEY(backend, workload));
CREATE TRIGGER IF NOT EXISTS assignments_frozen BEFORE UPDATE ON assignments
    BEGIN SELECT RAISE(ABORT, 'a bootstrap assignment is frozen'); END;
CREATE TABLE IF NOT EXISTS bootstraps(
    backend TEXT NOT NULL, workload TEXT NOT NULL, owner TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('claimed','recorded')), record TEXT, sha256 TEXT, claimed_at REAL NOT NULL,
    recorded_at REAL, PRIMARY KEY(backend, workload));
CREATE TRIGGER IF NOT EXISTS bootstraps_final BEFORE UPDATE ON bootstraps WHEN OLD.state = 'recorded'
    BEGIN SELECT RAISE(ABORT, 'a bootstrap record is immutable'); END;
CREATE TRIGGER IF NOT EXISTS bootstraps_keep BEFORE DELETE ON bootstraps
    BEGIN SELECT RAISE(ABORT, 'bootstrap records are kept'); END;
CREATE TABLE IF NOT EXISTS audit_waves(
    wave_id TEXT NOT NULL, rule_sha256 TEXT NOT NULL, seed INTEGER NOT NULL, population TEXT NOT NULL,
    population_sha256 TEXT NOT NULL, selection TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY(wave_id, rule_sha256));
CREATE TRIGGER IF NOT EXISTS audit_waves_frozen BEFORE UPDATE ON audit_waves
    BEGIN SELECT RAISE(ABORT, 'an audit wave is frozen'); END;
CREATE TRIGGER IF NOT EXISTS audit_waves_keep BEFORE DELETE ON audit_waves
    BEGIN SELECT RAISE(ABORT, 'audit waves are kept'); END;
CREATE TABLE IF NOT EXISTS wave_manifests(
    backend TEXT NOT NULL, workload TEXT NOT NULL, wave TEXT NOT NULL, manifest TEXT NOT NULL, sha256 TEXT NOT NULL,
    at REAL NOT NULL, PRIMARY KEY(backend, workload, wave));
CREATE TRIGGER IF NOT EXISTS wave_manifests_frozen BEFORE UPDATE ON wave_manifests
    BEGIN SELECT RAISE(ABORT, 'a sealed wave manifest is frozen'); END;
CREATE TRIGGER IF NOT EXISTS wave_manifests_keep BEFORE DELETE ON wave_manifests
    BEGIN SELECT RAISE(ABORT, 'sealed wave manifests are kept'); END
'''


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def spec_excerpt(path=None) -> str:
    """Obsolete (amendment A2.2): the shim loads and verifies the pinned effective excerpt itself
    (docs/design/ozmap-2026-10-24/bootstrap-spec-excerpt.txt). Kept as a delegating alias."""
    import sys
    examples = str(Path(__file__).resolve().parent / 'examples')
    if examples not in sys.path:
        sys.path.insert(0, examples)
    import bootstrap_shim
    return bootstrap_shim.spec_excerpt(path)


def map_inputs(op_text: str, text: str):
    """oz_accept Inputs for one job with one string reference, as a packet would carry it."""
    return oz_accept.Inputs(({'op': op_text, 'refs': [J(text)]},))


def value_text_of(value) -> str:
    """Compact JSON of a model value as a row carries it (RawJSON numerals keep their spelling)."""
    from oz_reply import dumps
    return dumps(value, ensure_ascii=False, separators=(',', ':'))


def wave_id(backend: str, workload: str, wave: str) -> str:
    """The evaluation-wave identity: canonical([backend, workload, wave]) as text."""
    return canonical([backend, workload, wave]).decode('utf-8')


def audit_order(ids, seed: int) -> list:
    """The seeded uniform permutation of frozen dataset ids used for audit selection."""
    return sorted(ids, key=lambda p: (hashlib.sha256(canonical([int(seed), p])).hexdigest(), p))


def select_audits(ids, seed: int, k: int = AUDIT_SAMPLE) -> list:
    """min(k, len(ids)) distinct ids, uniformly without replacement for the frozen seed (READING: a hash permutation
    of the frozen dataset ids, so the selection never depends on Python's random module or delivery identities)."""
    if type(seed) is not int or isinstance(seed, bool):
        raise Error('the audit seed must be an integer')
    ids = sorted(set(ids))
    return audit_order(ids, seed)[:min(k, len(ids))]


def bootstrap_assignment(producers: dict, seed: int, per_producer: int = BOOTSTRAP_PER_PRODUCER,
                         expected: int = BOOTSTRAP_PRODUCERS) -> dict:
    """{producer: [per_producer dataset ids]} chosen by seeded hash order of each producer's frozen dataset ids.
    Exactly `expected` producers, each with at least per_producer distinct ids, else Error."""
    if type(seed) is not int or isinstance(seed, bool):
        raise Error('the bootstrap seed must be an integer')
    if len(producers) != expected:
        raise Error(f'the bootstrap needs exactly {expected} producers, got {len(producers)}')
    out = {}
    for producer in sorted(producers):
        ids = sorted(set(producers[producer]))
        if len(ids) < per_producer:
            raise Error(f'producer {producer} has {len(ids)} jobs; the bootstrap needs {per_producer} from each')
        order = sorted(ids, key=lambda d: (hashlib.sha256(canonical([int(seed), 'bootstrap', d])).hexdigest(), d))
        out[producer] = order[:per_producer]
    every = [d for ids in out.values() for d in ids]
    if len(set(every)) != len(every):
        raise Error('bootstrap dataset ids must be distinct across producers')
    return out


def decode_ast(entry) -> tuple:
    """(exact AST bytes, None) or (None, reason) for one side-file rule entry
    {"none": true} | {"ast_b64", "ast_sha256", "bytes"}."""
    if entry == {'none': True}:
        return None, 'none_proposed'
    if not isinstance(entry, dict) or set(entry) != {'ast_b64', 'ast_sha256', 'bytes'}:
        return None, 'side_file_malformed'
    if not isinstance(entry['ast_b64'], str) or type(entry['bytes']) is not int:
        return None, 'side_file_malformed'
    try:
        data = base64.b64decode(entry['ast_b64'].encode('ascii'), validate=True)
    except (binascii.Error, ValueError, UnicodeError):
        return None, 'ast_b64_invalid'
    if len(data) != entry['bytes']:
        return None, 'ast_length_mismatch'
    if len(data) > MAX_AST_BYTES:
        return None, 'ast_too_large'
    if hashlib.sha256(data).hexdigest() != entry['ast_sha256']:
        return None, 'side_file_hash_mismatch'
    try:
        data.decode('utf-8', 'strict')
    except UnicodeError:
        return None, 'ast_invalid_unicode'
    return data, None


def evidence_problem(required, checks) -> tuple:
    """(None, None) when checks carry exactly one passing verdict for every required identity. Otherwise
    ("awaiting_verification", detail) for a missing, unknown or inconclusive verdict and ("failed", detail) for a
    failing one. The adoption boundary calls this itself; it never trusts the caller's summary."""
    if not isinstance(checks, list) or any(not isinstance(c, dict) for c in checks):
        return 'awaiting_verification', 'evidence_malformed'
    ids = [c.get('id') for c in checks]
    if len(set(ids)) != len(ids):
        return 'awaiting_verification', 'evidence_duplicate'
    failed = [c['id'] for c in checks if c.get('verdict') == 'fail']
    if failed:
        return 'failed', 'check_failed:' + ','.join(map(str, failed))
    missing = [r for r in required if r not in ids]
    if missing:
        return 'awaiting_verification', 'evidence_missing:' + ','.join(missing)
    unknown = [i for i in ids if i not in required]
    if unknown:
        return 'awaiting_verification', 'evidence_unknown:' + ','.join(map(str, unknown))
    unsure = [c['id'] for c in checks if c.get('verdict') != 'pass']
    if unsure:
        return 'awaiting_verification', 'check_inconclusive:' + ','.join(unsure)
    return None, None


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


def _connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    return db


def _init(db, schema: str, version: str, path):
    with _Tx(db):
        for statement in schema.split(';\n'):
            if statement.strip():
                db.execute(statement)
        db.execute('INSERT OR IGNORE INTO meta VALUES (?, ?)', ('schema', version))
    if db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] != version:
        raise Error(f'{path} is not an {version} store')


class RuleStore:
    """The arm host's rule store. One connection, every write in BEGIN IMMEDIATE."""

    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.db = _connect(self.path)
        _init(self.db, SCHEMA, SCHEMA_VERSION, self.path)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def transaction(self):
        return _Tx(self.db)

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
        """Record one candidate outcome. Idempotent on source; a different payload for the same source raises."""
        if status not in ('admitted', 'rejected'):
            raise Error('a new rule is admitted or rejected')
        if status == 'admitted' and ast is None:
            raise Error('an admitted rule needs its AST bytes')
        ast_hash = hashlib.sha256(ast).hexdigest() if ast is not None else None
        with self.transaction() as db:
            row = db.execute('SELECT * FROM rules WHERE source=?', (source,)).fetchone()
            if row is not None:
                if (row['binding_key'], row['ast_sha256'], row['operation']) != (binding_key, ast_hash, operation) or \
                        (row['status'] == 'rejected') != (status == 'rejected'):
                    raise Error(f'rule source {source} already holds a different candidate')
                return row['id']
            cur = db.execute('INSERT INTO rules(binding_key, operation, bindings, ast, ast_sha256, status, admission, '
                             'provenance, source, at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                             (binding_key, operation, canonical(bindings).decode('utf-8'),
                              sqlite3.Binary(ast) if ast is not None else None, ast_hash, status,
                              J(admission), J(provenance), source, self.clock()))
            return cur.lastrowid

    def quarantine(self, rule_id: int, reason: dict) -> bool:
        """Atomically move an admitted rule to quarantined. True if it moved."""
        with self.transaction() as db:
            return self._quarantine(db, rule_id, reason)

    def _quarantine(self, db, rule_id, reason) -> bool:
        cur = db.execute("UPDATE rules SET status='quarantined', quarantined_at=?, quarantine=? "
                         "WHERE id=? AND status='admitted'", (self.clock(), J(reason), rule_id))
        return cur.rowcount == 1

    def reusable(self, rule_id: int) -> tuple:
        """(True, None) when the rule is admitted and every audit of it is conclusive; else (False, reason).
        Pending or inconclusive audits block warm reuse until resolved (council 2, ruling 4 and Opus B5)."""
        rule = self.rule(rule_id)
        if rule is None or rule['status'] != 'admitted':
            return False, 'not_admitted' if rule is None or rule['status'] != 'quarantined' else 'quarantined'
        open_ = self.db.execute("SELECT verdict, COUNT(*) FROM audits WHERE rule=? AND verdict IN "
                                "('pending','inconclusive') GROUP BY verdict", (rule_id,)).fetchall()
        if open_:
            return False, 'audit_unresolved:' + ','.join(f'{v}={n}' for v, n in open_)
        return True, None

    # ------------------------------------------------------------------------------------------ settlements

    def settlement(self, job: str) -> dict | None:
        row = self.db.execute('SELECT * FROM settlements WHERE job=?', (job,)).fetchone()
        return None if row is None else dict(row, required=json.loads(row['required']))

    def open_job(self, job: str, *, payload_sha256: str, bindings_sha256: str, required) -> dict:
        """Open (or, on resume, validate) the authoritative settlement record. A different identity raises."""
        required = sorted(required)
        with self.transaction() as db:
            row = db.execute('SELECT * FROM settlements WHERE job=?', (job,)).fetchone()
            if row is None:
                db.execute("INSERT INTO settlements(job, payload_sha256, bindings_sha256, required, generation, state, "
                           "opened_at) VALUES (?,?,?,?,0,'open',?)",
                           (job, payload_sha256, bindings_sha256, J(required), self.clock()))
            elif (row['payload_sha256'], row['bindings_sha256'], json.loads(row['required'])) != \
                    (payload_sha256, bindings_sha256, required):
                raise Error(f'settlement identity of job {job} changed (payload, bindings or required checks); '
                            'refusing to resume it under the old identity')
        return self.settlement(job)

    def claim(self, job: str) -> int | None:
        """A new execution generation for an open or awaiting job (fences every older execution), or None when the job
        is settled or failed (terminal)."""
        with self.transaction() as db:
            cur = db.execute("UPDATE settlements SET generation=generation+1 WHERE job=? AND state NOT IN "
                             "('settled','failed')", (job,))
            if cur.rowcount != 1:
                return None
            return db.execute('SELECT generation FROM settlements WHERE job=?', (job,)).fetchone()[0]

    def _authority(self, db, job, generation, payload_sha256, bindings_sha256):
        """The settlement row if this execution may settle the job, else a refusal reason."""
        row = db.execute('SELECT * FROM settlements WHERE job=?', (job,)).fetchone()
        if row is None:
            return None, 'not_opened'
        if (row['payload_sha256'], row['bindings_sha256']) != (payload_sha256, bindings_sha256):
            return None, 'identity_mismatch'
        if row['state'] == 'settled':
            return None, 'already_settled:' + row['winner']
        if row['state'] == 'failed':
            return None, 'already_failed'
        if row['generation'] != generation:
            return None, 'stale_generation'
        return row, None

    def _emit(self, db, *, job, generation, source, phase, type_, value, checks, outcome, reason=None, rule=None,
              call_id=None) -> int:
        return db.execute('INSERT INTO emissions(job, generation, source, phase, type, value, checks, outcome, reason, '
                          'rule, call_id, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                          (job, generation, source, phase, type_, value, J(checks), outcome, reason, rule, call_id,
                           self.clock())).lastrowid

    def emissions(self, job: str | None = None) -> list:
        rows = (self.db.execute('SELECT * FROM emissions ORDER BY seq') if job is None else
                self.db.execute('SELECT * FROM emissions WHERE job=? ORDER BY seq', (job,)))
        return [dict(r, checks=json.loads(r['checks'])) for r in rows]

    def settle_model(self, job: str, *, generation: int, payload_sha256: str, bindings_sha256: str, value_text: str,
                     checks: list, phase: str = 'fallback', call_id=None, before_commit=None) -> tuple:
        """Settle a model answer. ("settled", emission) | ("awaiting_verification", detail) | ("failed", detail) |
        ("refused", reason). The evidence is judged here against the job's required checks."""
        with self.transaction() as db:
            if before_commit is not None:
                before_commit(db)
            row, refused = self._authority(db, job, generation, payload_sha256, bindings_sha256)
            emit = dict(job=job, generation=generation, source='model', phase=phase, type_=None, value=value_text,
                        checks=checks, call_id=call_id)
            if row is None:
                self._emit(db, outcome='refused', reason=refused, **emit)
                return 'refused', refused
            kind, detail = evidence_problem(json.loads(row['required']), checks)
            if kind == 'failed':
                self._emit(db, outcome='failed', reason=detail, **emit)
                db.execute("UPDATE settlements SET state='failed', settled_at=? WHERE job=?", (self.clock(), job))
                return 'failed', detail
            if kind == 'awaiting_verification':
                self._emit(db, outcome='awaiting_verification', reason=detail, **emit)
                db.execute("UPDATE settlements SET state='awaiting_verification' WHERE job=?", (job,))
                return 'awaiting_verification', detail
            seq = self._emit(db, outcome='settled', **emit)
            db.execute("UPDATE settlements SET state='settled', winner='model', emission=?, settled_at=? WHERE job=?",
                       (seq, self.clock(), job))
            return 'settled', seq

    def mark_awaiting(self, job: str, *, generation: int, payload_sha256: str, bindings_sha256: str, source: str,
                      value_text: str, type_, checks, reason, rule=None, phase='rule') -> tuple:
        """Record a value whose checks are not all available: the job awaits verification, nothing is accepted.
        Fenced like every settlement (council 3, B5): identity, terminal state and generation are checked in the same
        transaction. Returns ("awaiting_verification", reason) or ("refused", why); a refusal is kept as an emission."""
        with self.transaction() as db:
            row, refused = self._authority(db, job, generation, payload_sha256, bindings_sha256)
            emit = dict(job=job, generation=generation, source=source, phase=phase, type_=type_, value=value_text,
                        checks=checks, rule=rule)
            if row is None:
                self._emit(db, outcome='refused', reason=refused, **emit)
                return 'refused', refused
            self._emit(db, outcome='awaiting_verification', reason=reason, **emit)
            db.execute("UPDATE settlements SET state='awaiting_verification' WHERE job=?", (job,))
            return 'awaiting_verification', reason

    def verify_identity(self, job: str, *, payload_sha256: str, bindings_sha256: str) -> dict:
        """The settlement row when its immutable identity equals this one, else Error (council 3, B5: every resume path
        validates the job identity before it returns an existing result)."""
        row = self.settlement(job)
        if row is None:
            raise Error(f'job {job} has no settlement record')
        if (row['payload_sha256'], row['bindings_sha256']) != (payload_sha256, bindings_sha256):
            raise Error(f'settlement identity of job {job} differs (payload or bindings); refusing to return its result')
        return row

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
                   checks: list, owner: dict, generation: int, payload_sha256: str, bindings_sha256: str,
                   evaluate=oz_rule.evaluate, before_commit=None) -> tuple:
        """D1 adoption and settlement in one IMMEDIATE transaction. Returns ("adopted", row), ("present", row) for a
        job this rule already won, ("awaiting_verification", detail) or ("refused", reason). In the same transaction:
        settlement authority (identity, generation, not settled), rule admitted (not quarantined), bindings, AST bytes
        and hash, resolved input hash, complete passing evidence for every required check, and the re-evaluation of
        the exact admitted bytes (rule_provenance/1) with an identical type and canonical value."""
        value = oz_rule.canonical_value_text(first) or ''
        with self.transaction() as db:
            if before_commit is not None:
                before_commit(db)
            emit = dict(job=job, generation=generation, source='rule', phase='rule', type_=first.get('type'),
                        value=value, checks=checks, rule=rule['id'])
            present = db.execute('SELECT * FROM results WHERE job=?', (job,)).fetchone()
            if present is not None:
                # Idempotent only for the identical job identity, rule, bindings, input and value (council 3, B5).
                s = db.execute('SELECT * FROM settlements WHERE job=?', (job,)).fetchone()
                same = (s is not None
                        and (s['payload_sha256'], s['bindings_sha256']) == (payload_sha256, bindings_sha256)
                        and s['winner'] == 'rule' and present['rule'] == rule['id']
                        and present['binding_key'] == binding_key and present['resolved_sha256'] == resolved_sha256
                        and present['value'] == value)
                if not same:
                    self._emit(db, outcome='refused', reason='present_identity_mismatch', **emit)
                    return 'refused', 'present_identity_mismatch'
                return 'present', None

            def refuse(reason):
                self._emit(db, outcome='refused', reason=reason, **emit)
                return 'refused', reason

            settlement, refused = self._authority(db, job, generation, payload_sha256, bindings_sha256)
            if settlement is None:
                return refuse(refused)
            row = self._rule(db.execute('SELECT * FROM rules WHERE id=?', (rule['id'],)).fetchone())
            if row is None or row['status'] != 'admitted':
                return refuse('quarantined' if row is not None and row['status'] == 'quarantined' else 'not_admitted')
            if row['binding_key'] != binding_key or rule['binding_key'] != binding_key:
                return refuse('binding_changed')
            ast = row['ast']
            if (ast is None or hashlib.sha256(ast).hexdigest() != row['ast_sha256']
                    or row['ast_sha256'] != rule['ast_sha256'] or row['admission'].get('ast_hash') != row['ast_sha256']):
                return refuse('ast_changed')
            if sha256_text(text) != resolved_sha256:
                return refuse('input_changed')
            kind, detail = evidence_problem(json.loads(settlement['required']), checks)
            if kind == 'failed':
                return refuse(detail)
            if kind == 'awaiting_verification':
                self._emit(db, outcome='awaiting_verification', reason=detail, **emit)
                db.execute("UPDATE settlements SET state='awaiting_verification' WHERE job=?", (job,))
                return 'awaiting_verification', detail
            # rule_provenance/1: the exact admitted AST bytes, re-evaluated against this job's resolved input.
            again = evaluate(ast, text)
            if (not isinstance(again, dict) or again.get('status') != 'value' or again.get('type') != first['type']
                    or oz_rule.canonical_value_text(again) != value):
                return refuse('provenance_failed')
            provenance = {'check': 'rule_provenance/1', 'ast_sha256': row['ast_sha256'], 'steps': again['steps'],
                          'interpreter': INTERPRETER, 'reevaluated': True}
            db.execute('INSERT INTO results(job, rule, binding_key, producer, submission, operation, path, '
                       'resolved_sha256, type, value, steps, checks, provenance, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (job, row['id'], binding_key, owner['producer'], owner['submission'], owner['operation'],
                        owner['path'], resolved_sha256, first['type'], value, first['steps'], J(checks),
                        J(provenance), self.clock()))
            seq = self._emit(db, outcome='settled', **emit)
            db.execute("UPDATE settlements SET state='settled', winner='rule', emission=?, settled_at=? WHERE job=?",
                       (seq, self.clock(), job))
        return 'adopted', self.result(job)

    # ------------------------------------------------------------------------------------------------ audits

    def add_audits(self, audits) -> None:
        """Persist pending audit rows before dispatch (idempotent; a different identity for the same job raises)."""
        keys = ('wave_id', 'original_job', 'rule', 'producer', 'submission', 'dataset_id', 'rule_value')
        with self.transaction() as db:
            for a in audits:
                row = db.execute('SELECT * FROM audits WHERE audit_job=?', (a['audit_job'],)).fetchone()
                if row is not None:
                    if tuple(row[k] for k in keys) != tuple(a[k] for k in keys):
                        raise Error(f"audit {a['audit_job']} already exists with a different identity")
                    continue
                db.execute("INSERT INTO audits(audit_job, wave_id, original_job, rule, producer, submission, dataset_id, "
                           "rule_value, verdict, created_at) VALUES (?,?,?,?,?,?,?,?,'pending',?)",
                           (a['audit_job'], *[a[k] for k in keys], self.clock()))

    def decide_audit(self, audit_job: str, verdict: str, *, model_value=None, detail=None, call_id=None,
                     attempt_id=None) -> dict:
        """Move a pending (or inconclusive) audit to its verdict; a disagreement quarantines the rule in the same
        transaction. Returns {"changed", "quarantined_now", "audit"}."""
        if verdict not in VERDICTS[1:]:
            raise Error('an audit verdict is agree, disagree or inconclusive')
        quarantined = False
        with self.transaction() as db:
            row = db.execute('SELECT * FROM audits WHERE audit_job=?', (audit_job,)).fetchone()
            if row is None:
                raise Error(f'unknown audit {audit_job}')
            movable = row['verdict'] == 'pending' or (row['verdict'] == 'inconclusive' and verdict != 'inconclusive')
            if movable:
                db.execute('UPDATE audits SET verdict=?, model_value=?, detail=?, call_id=?, attempt_id=?, decided_at=? '
                           'WHERE audit_job=?', (verdict, model_value, detail, call_id, attempt_id, self.clock(),
                                                 audit_job))
                if verdict == 'disagree':
                    quarantined = self._quarantine(db, row['rule'], {
                        'audit_job': audit_job, 'dataset_id': row['dataset_id'], 'rule_value': row['rule_value'],
                        'model_value': model_value})
        return {'changed': movable, 'quarantined_now': quarantined, 'audit': self.audit(audit_job)}

    def audit(self, audit_job: str) -> dict | None:
        row = self.db.execute('SELECT * FROM audits WHERE audit_job=?', (audit_job,)).fetchone()
        return None if row is None else dict(row)

    def audits(self, wave: str | None = None) -> list:
        rows = (self.db.execute('SELECT * FROM audits ORDER BY rowid') if wave is None else
                self.db.execute('SELECT * FROM audits WHERE wave_id=? ORDER BY rowid', (wave,)))
        return [dict(r) for r in rows]


class Learner:
    """One operation's learning context: verified registry package (or its ineligibility), full bindings and key,
    and the list of every applicable pinned check."""

    def __init__(self, store: RuleStore, registry, operation: str, *, worker_hash: str, map_contract: str,
                 map_input_policy: str, map_pinned=()):
        if not isinstance(registry, oz_registry.Registry):
            raise Error('--learn needs an owner-approved oz_registry.Registry (--registry MANIFEST)')
        if not isinstance(worker_hash, str) or len(worker_hash) != 64:
            raise Error('--learn needs the full worker identity (worker_hash); a model label is not enough (D7)')
        self.store, self.registry, self.operation = store, registry, operation
        self.worker_hash = worker_hash
        self.map_pinned = list(map_pinned)
        manifest = registry._manifest
        if operation not in manifest['operations']:
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
        op = manifest['operations'][operation]
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
        self.consumer = [(cid, manifest['checks'][cid]['definition']) for cid in op['checks']
                         if manifest['checks'][cid]['definition']['kind'] == oz_registry.CONSUMER]
        self.bindings = {'operation_id': operation, 'registry': dict(registry_bindings), 'interpreter': INTERPRETER,
                         'map_input_policy': map_input_policy, 'worker_hash': worker_hash, 'map_contract': map_contract}
        self.key = digest(self.bindings)

    @property
    def required(self) -> list:
        """Every applicable pinned check identity: registry consumer checks and map --check specs."""
        return sorted([f"registry:{cid}:{d['name']}@{d['version']}" for cid, d in self.consumer]
                      + [f"map:{k}:{s['check']}@{s['version']}" for k, s in enumerate(self.map_pinned)])

    def evidence(self, value_text: str, text: str, op_text: str) -> list:
        """One verdict per required check for this value on this job's resolved input."""
        out = []
        value = json.loads(value_text)
        for cid, d in self.consumer:
            try:
                ok = self.registry.runner.run(d['name'], d['version'], d['params'], value, text)
                verdict = 'pass' if ok is True else 'fail'
            except CheckUnavailable:
                verdict = 'inconclusive'
            except Exception:
                verdict = 'inconclusive'
            out.append({'id': f"registry:{cid}:{d['name']}@{d['version']}", 'check': d['name'],
                        'version': d['version'], 'verdict': verdict, 'source': 'registry'})
        if self.map_pinned:
            for k, v in enumerate(oz_accept.run_checks(value_text, map_inputs(op_text, text), self.map_pinned)):
                out.append({'id': f"map:{k}:{v['check']}@{v['version']}", 'check': v['check'], 'version': v['version'],
                            'verdict': v['verdict'], 'source': 'map'})
        return out

    def bootstrap_config(self) -> dict:
        """The shim's oz.bootstrap.config/2 for this operation (exactly these keys)."""
        return {'schema': CONFIG_SCHEMA, 'ops': [self.operation], 'contracts': {self.operation: self.contract},
                'eligibility': {self.operation: self.eligible}}

    def admit_side(self, side: dict | None, *, source: str, provenance: dict) -> int:
        """Record the bootstrap outcome for the operation from the shim's side file (oz.bootstrap.side/2): admitted,
        or rejected with the reason. The exact decoded ast_b64 bytes are admitted and stored. Idempotent."""
        ast, status = None, 'rejected'
        if side is None:
            admission = {'status': 'rejected', 'reasons': ['bootstrap_missing']}
        elif side.get('schema') != SIDE_SCHEMA:
            admission = {'status': 'rejected', 'reasons': ['side_file_schema']}
        elif side.get('status') != 'ok' or side.get('envelope_ok') is not True:
            admission = {'status': 'rejected', 'reasons': ['bootstrap_' + str(side.get('status'))],
                         'detail': side.get('reason')}
        else:
            entry = (side.get('rules') or {}).get(self.operation)
            ast, why = decode_ast(entry)
            if ast is None:
                admission = {'status': 'rejected', 'reasons': [why]}
            else:
                admission = self.registry.admit(ast, self.operation, {'worker_hash': self.worker_hash})
                if (admission['status'] == 'accepted' and self.eligible
                        and admission.get('bindings') == self.bindings['registry']
                        and admission.get('ast_hash') == hashlib.sha256(ast).hexdigest()):
                    status = 'admitted'
                elif admission['status'] == 'accepted':
                    admission = dict(admission, status='rejected', reasons=['binding_or_hash_mismatch'])
                if status == 'rejected':
                    ast = ast if admission.get('ast_hash') else None
        return self.store.add_rule(binding_key=self.key, operation=self.operation, bindings=self.bindings, ast=ast,
                                   status=status, admission=admission, provenance=provenance, source=source)

    def attempt(self, rule: dict, *, job: str, text: str, resolved_sha256: str, op_text: str, owner: dict,
                generation: int, payload_sha256: str, bindings_sha256: str, stage: bool = False,
                evaluate=oz_rule.evaluate, before_commit=None) -> dict:
        """One job's rule decision, recorded: {"decision": "rule", "row"} (settled now), {"decision": "staged",
        "first", "checks"} (complete passing evidence; committed later by commit()), {"decision":
        "awaiting_verification", "reason"} or {"decision": "fallback", "reason"}."""
        def fallback(reason):
            self.store.decide(job, rule['id'], 'fallback', reason)
            return {'decision': 'fallback', 'reason': reason}

        done = self.store.result(job)
        if done is not None:
            # A resumed job returns its existing rule result only under the identical identity (council 3, B5).
            self.store.verify_identity(job, payload_sha256=payload_sha256, bindings_sha256=bindings_sha256)
            if (done['rule'], done['binding_key'], done['resolved_sha256']) != (rule['id'], self.key, resolved_sha256):
                raise Error(f'job {job} already holds a rule result under another rule, binding or input')
            return {'decision': 'rule', 'row': done, 'resumed': True}
        if self.package is None:
            return fallback('ineligible')
        first = evaluate(rule['ast'], text)
        if not isinstance(first, dict) or first.get('status') != 'value':
            return fallback('abstain:' + str((first or {}).get('reason')))
        value_text = oz_rule.canonical_value_text(first)
        checks = self.evidence(value_text, text, op_text)
        kind, detail = evidence_problem(self.required, checks)
        if kind == 'failed':
            return fallback(detail.replace('check_failed:', 'check_failed:', 1))
        if kind == 'awaiting_verification':
            state, why = self.store.mark_awaiting(job, generation=generation, payload_sha256=payload_sha256,
                                                  bindings_sha256=bindings_sha256, source='rule',
                                                  value_text=value_text, type_=first['type'], checks=checks,
                                                  reason=detail, rule=rule['id'])
            if state == 'refused':
                return fallback('awaiting_refused:' + why)
            self.store.decide(job, rule['id'], 'awaiting_verification', detail)
            return {'decision': 'awaiting_verification', 'reason': detail}
        staged = {'decision': 'staged', 'rule': rule, 'job': job, 'text': text, 'resolved_sha256': resolved_sha256,
                  'first': first, 'checks': checks, 'owner': owner, 'generation': generation,
                  'payload_sha256': payload_sha256, 'bindings_sha256': bindings_sha256}
        if stage:
            self.store.decide(job, rule['id'], 'staged', None)
            return staged
        return self.commit(staged, evaluate=evaluate, before_commit=before_commit)

    def commit(self, staged: dict, *, evaluate=oz_rule.evaluate, before_commit=None) -> dict:
        """Settle a staged rule value through adopt_rule (which re-checks everything in the committing transaction)."""
        rule, job = staged['rule'], staged['job']
        state, detail = self.store.adopt_rule(
            rule=rule, binding_key=self.key, job=job, text=staged['text'], resolved_sha256=staged['resolved_sha256'],
            first=staged['first'], checks=staged['checks'], owner=staged['owner'], generation=staged['generation'],
            payload_sha256=staged['payload_sha256'], bindings_sha256=staged['bindings_sha256'], evaluate=evaluate,
            before_commit=before_commit)
        if state == 'refused':
            self.store.decide(job, rule['id'], 'fallback', 'commit_refused:' + detail)
            return {'decision': 'fallback', 'reason': 'commit_refused:' + detail}
        if state == 'awaiting_verification':
            self.store.decide(job, rule['id'], 'awaiting_verification', detail)
            return {'decision': 'awaiting_verification', 'reason': detail}
        self.store.decide(job, rule['id'], 'rule', None)
        return {'decision': 'rule', 'row': self.store.result(job), 'resumed': state == 'present'}


class ExperimentStore:
    """Shared experiment state for every arm host of one experiment directory: frozen bootstrap assignments, the one
    bootstrap record per (backend, workload), and the persisted audit populations and selections."""

    def __init__(self, path, *, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.db = _connect(self.path)
        _init(self.db, EXPERIMENT_TABLES, EXPERIMENT_SCHEMA, self.path)

    def close(self):
        self.db.close()

    def assignment(self, backend: str, workload: str, producers: dict, seed: int, *,
                   per_producer: int = BOOTSTRAP_PER_PRODUCER, expected: int = BOOTSTRAP_PRODUCERS) -> dict:
        """The frozen {producer: [dataset ids]} bootstrap assignment; the first call persists it, every later call
        must derive the identical one (else Error: the frozen assignment does not match these producers)."""
        made = bootstrap_assignment(producers, seed, per_producer, expected)
        text = J(made)
        with _Tx(self.db) as db:
            row = db.execute('SELECT assignment FROM assignments WHERE backend=? AND workload=?',
                             (backend, workload)).fetchone()
            if row is None:
                db.execute('INSERT INTO assignments VALUES (?,?,?,?,?)',
                           (backend, workload, text, sha256_text(text), self.clock()))
            elif json.loads(row[0]) != made:
                raise Error(f'the frozen bootstrap assignment of {backend}/{workload} does not match these producers')
        return made

    def bootstrap(self, backend: str, workload: str) -> dict | None:
        row = self.db.execute('SELECT * FROM bootstraps WHERE backend=? AND workload=?', (backend, workload)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out['record'] = json.loads(out['record']) if out['record'] else None
        return out

    def claim_bootstrap(self, backend: str, workload: str, owner: str) -> tuple:
        """("run", row) when this owner claimed it now, ("resume", row) when this owner claimed it before without a
        record, ("wait", row) when another owner holds the claim, ("import", row) when it is recorded. There is no
        time-based takeover; one claim per (backend, workload), ever."""
        with _Tx(self.db) as db:
            row = db.execute('SELECT * FROM bootstraps WHERE backend=? AND workload=?', (backend, workload)).fetchone()
            if row is None:
                db.execute("INSERT INTO bootstraps(backend, workload, owner, state, claimed_at) VALUES (?,?,?,'claimed',?)",
                           (backend, workload, owner, self.clock()))
                state = 'run'
            elif row['state'] == 'recorded':
                state = 'import'
            else:
                state = 'resume' if row['owner'] == owner else 'wait'
        return state, self.bootstrap(backend, workload)

    def record_bootstrap(self, backend: str, workload: str, owner: str, record: dict) -> dict:
        """Write the immutable bootstrap record once (only by the claim owner)."""
        text = J(dict(record, schema=RECORD_SCHEMA))
        with _Tx(self.db) as db:
            row = db.execute('SELECT * FROM bootstraps WHERE backend=? AND workload=?', (backend, workload)).fetchone()
            if row is None or row['owner'] != owner:
                raise Error(f'bootstrap {backend}/{workload} is not claimed by {owner}')
            if row['state'] == 'recorded':
                if row['record'] != text:
                    raise Error(f'bootstrap {backend}/{workload} is already recorded differently')
            else:
                db.execute("UPDATE bootstraps SET state='recorded', record=?, sha256=?, recorded_at=? "
                           'WHERE backend=? AND workload=?', (text, sha256_text(text), self.clock(), backend, workload))
        return self.bootstrap(backend, workload)

    def audit_wave(self, wave: str, rule_sha256: str, seed: int, population) -> dict:
        """The persisted population and selection of one evaluation wave and rule. The first arm persists it; a later
        arm gets the same selection, with "mismatch" true when its own population differs (evidence is then
        incomplete; READING: the persisted selection still binds, restricted by the caller to its own population)."""
        population = sorted(set(population))
        text = J(population)
        selection = select_audits(population, seed)
        with _Tx(self.db) as db:
            row = db.execute('SELECT * FROM audit_waves WHERE wave_id=? AND rule_sha256=?', (wave, rule_sha256)).fetchone()
            if row is None:
                db.execute('INSERT INTO audit_waves VALUES (?,?,?,?,?,?,?)',
                           (wave, rule_sha256, seed, text, sha256_text(text), J(selection), self.clock()))
                row = db.execute('SELECT * FROM audit_waves WHERE wave_id=? AND rule_sha256=?',
                                 (wave, rule_sha256)).fetchone()
        if row['seed'] != seed:
            raise Error(f'wave {wave} was selected with seed {row["seed"]}; the seed is frozen')
        return {'wave_id': wave, 'rule_sha256': rule_sha256, 'seed': row['seed'],
                'population': json.loads(row['population']), 'selection': json.loads(row['selection']),
                'mismatch': row['population_sha256'] != sha256_text(text)}

    def seal_wave(self, backend: str, workload: str, wave: str, manifest: dict) -> str:
        """Seal (first arm) or verify (every later arm) the immutable wave manifest {dataset id: {op, input_sha256,
        producer, key}}. Returns its SHA256; a different manifest raises Error before any call (council 3, B12)."""
        text = J(manifest)
        with _Tx(self.db) as db:
            row = db.execute('SELECT manifest FROM wave_manifests WHERE backend=? AND workload=? AND wave=?',
                             (backend, workload, wave)).fetchone()
            if row is None:
                db.execute('INSERT INTO wave_manifests VALUES (?,?,?,?,?,?)',
                           (backend, workload, wave, text, sha256_text(text), self.clock()))
            elif row[0] != text:
                theirs = json.loads(row[0])
                diff = sorted(set(theirs) ^ set(manifest)) + sorted(d for d in set(theirs) & set(manifest)
                                                                    if theirs[d] != manifest[d])
                raise Error(f'wave {backend}/{workload}/{wave} differs from its sealed manifest '
                            f'({len(diff)} dataset ids, first {diff[:3]}); every arm must consume the same data')
        return sha256_text(text)

    def wave_manifest(self, backend: str, workload: str, wave: str) -> dict | None:
        row = self.db.execute('SELECT manifest FROM wave_manifests WHERE backend=? AND workload=? AND wave=?',
                              (backend, workload, wave)).fetchone()
        return json.loads(row[0]) if row else None

    def waves(self) -> list:
        return [dict(r, population=json.loads(r['population']), selection=json.loads(r['selection']))
                for r in self.db.execute('SELECT * FROM audit_waves ORDER BY rowid')]
