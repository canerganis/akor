"""oz map kill pilot: plan, dry run, freeze, telemetry, live run and report (joint record 3 to 6, amendment 2 A2.3).

    python bench/ozmap/pilot.py plan       the matrix and the frozen budget allocation per backend and bucket
    python bench/ozmap/pilot.py registry   (re)build bench/ozmap/registry.json from the oracle-labeled admission sets
    python bench/ozmap/pilot.py dry        oz_host.dry_run over the full matrix with recorded real usage, zero calls
    python bench/ozmap/pilot.py identity   record each adapter's `--identity` (no model call; runs `<cli> --version`)
    python bench/ozmap/pilot.py freeze     fill the identity placeholders, then hash everything into freeze.json
    python bench/ozmap/pilot.py telemetry --i-have-approval   the two paired Codex telemetry calls (guarded)
    python bench/ozmap/pilot.py run --live --i-have-approval  the pilot (guarded: freeze, approval, telemetry, budget)
    python bench/ozmap/pilot.py report [RUN_DIR]              gold scoring and the ordered gates (score.py)

Standard library. Nothing here calls a model except `telemetry` and `run --live`, and both refuse unless freeze.json
verifies against the current files and --i-have-approval is given.

Frozen configuration (DRIVER choices are listed in ASSUMPTIONS and printed by `plan`).
  Codex   codex exec through examples/bootstrap_codex_adapter.json, model gpt-6.1-sol, effort medium
  Sonnet  claude -p through examples/bootstrap_claude_adapter.json, model claude-sonnet-5-5, effort default
  Budget  amendment 3 (owner decisions 2026-10-24): global cap 54; Codex 37 = telemetry 1, bootstraps 2, A 12,
          B residuals 8, C residuals 7, reserve 7 (the second telemetry invocation consumes one reserve call, leaving
          six); Sonnet 17 = telemetry 0, bootstrap 1, A 8, B residuals 4 (dedicated, never the reserve), C residuals 2,
          reserve 2. Audits, overflow, additional telemetry, preparation and permitted infrastructure retries consume
          the applicable reserve; every launch reserves first; exhaustion leaves the evidence incomplete.
  Quota   the 55% weekly launch guard is suspended for this build and pilot (owner decision 1, amendment 3 section 1;
          ends when the pilot report is written). The 99% quota handoff rule stays a documented stop: at 99% Claude
          weekly usage every launch stops and the work is handed off; oz_quota reservation discipline is unchanged.
  Host    one experiment-wide pool of 4 physical slots across every arm and backend, batches of at most 64 records,
          flush after 1 s, call_timeout_seconds 1200 (the child is killed with its process tree 120 s later),
          deadline_seconds 1800, max_input_tokens 1000000; the four producers of a wave submit from one barrier and a
          wave needs the full 4 x 64 intake before any call.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
EXAMPLES = REPO / 'examples'
for p in (str(REPO), str(EXAMPLES)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _sibling(name):
    """Load bench/ozmap/<name>.py as module ozmap_<name> (other bench folders have their own oracle.py, score.py and
    data modules, so the plain names would collide in one interpreter)."""
    import importlib.util
    key = 'ozmap_' + name
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, HERE / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


data = _sibling('data')
oracle = _sibling('oracle')
score = _sibling('score')

REGISTRY_FILE = HERE / 'registry.json'
IDENTITY_FILE = HERE / 'identity.json'
FREEZE_FILE = HERE / 'freeze.json'
TELEMETRY_FILE = HERE / 'telemetry.json'
ROUTES_FILE = HERE / 'routes.json'
RUNS = HERE / 'runs'
SEED = data.SEED
GLOBAL_CAP = 54
CAPS = {'codex': {'telemetry': 1, 'bootstrap': 2, 'A': 12, 'B': 8, 'C': 7, 'reserve': 7},
        'sonnet': {'telemetry': 0, 'bootstrap': 1, 'A': 8, 'B': 4, 'C': 2, 'reserve': 2}}
HOST = {'slots': 4, 'max_records': 64, 'max_wait': 1.0, 'intake': {'producers': 4, 'per_producer': 64},
        'limits': {'call_timeout_seconds': 1200, 'deadline_seconds': 1800, 'max_input_tokens': 1000000}}
QUOTA_STOP = ('99% Claude weekly usage: stop every launch and hand off (owner rule); the 55% launch guard is '
              'suspended by owner decision 1 and amendment 3 until the pilot report is written')
# Normative documents in precedence order (amendment 3 section 4): a later entry supersedes conflicting text in an
# earlier one.
NORMATIVE = ('docs/design/brainstorm-2026-10-24/05-joint-record.md',
             'docs/design/ozmap-2026-10-24/oz-rule-1-amendment-1.md',
             'docs/design/ozmap-2026-10-24/amendment-2-and-step6-architecture.md',
             'docs/design/ozmap-2026-10-24/council3-astra.md',
             'docs/design/ozmap-2026-10-24/owner-decisions-2026-10-24.md',
             'docs/design/ozmap-2026-10-24/amendment-3.md')
TELEMETRY_KEYS = (('telemetry-1', ['telemetry', 'reserve']), ('telemetry-2', ['telemetry', 'reserve']))
BACKENDS = {
    'codex': {'adapter': EXAMPLES / 'bootstrap_codex_adapter.json', 'real': 'codex_cli_adapter', 'route_backend': 'codex',
              'model': 'gpt-6.1-sol', 'effort': 'medium', 'host_effort': 'medium'},
    'sonnet': {'adapter': EXAMPLES / 'bootstrap_claude_adapter.json', 'real': 'claude_map_adapter',
               'route_backend': 'claude', 'model': 'claude-sonnet-5-5', 'effort': 'default', 'host_effort': None},
}
PLACEHOLDER = 'PLACEHOLDER-needs-identity-probe'
APPROVED_BY = ('canerganis (owner); approval pending until the owner commits this manifest and runs pilot.py freeze')
INPUT_POLICY = {'version': 'oz-input/1', 'terminal_newline': 'strip_one', 'text_ref': 0}
MAX_BYTES = {'e': 256, 'b': 64, 'm': 64, 'v': 16}
JSON_TYPES = {'e': ['array'], 'b': ['array', 'string'], 'm': ['array'], 'v': ['string']}
RESULTS = {'e': 'JSON array of six strings', 'b': 'JSON array of two strings, or the string unknown',
           'm': 'JSON array of field names', 'v': 'one of the strings inside, outside, unknown'}
LEDGERS = {'codex': REPO / 'bench' / 'codex_kit' / 'results_gpt-6.1-sol_medium.jsonl',
           'sonnet': REPO / 'bench' / 'live' / 'data' / 'pilot2_sonnet64.jsonl'}
LEDGERS_32 = {'codex': LEDGERS['codex'], 'sonnet': REPO / 'bench' / 'live' / 'data' / 'live24_1g_D_sonnet32.jsonl'}
# Bootstrap usage is not measured yet: a recorded 64-job call plus the shim's added system text (chars / 4) and the
# rule output (AST bytes / 3) plus a reasoning allowance. Elapsed scales with output tokens.
BOOTSTRAP_REASONING_ALLOWANCE = 2000
CHARS_PER_TOKEN, AST_BYTES_PER_TOKEN = 4.0, 3.0

ASSUMPTIONS = [
    'Materials is ONE workload of four operations (e, b, m, v): one shared bootstrap per backend proposes a rule or '
    '"none" per operation, batches mix operations, and the 32 audits per evaluation wave are drawn over all four '
    'operations together. oz_host.ArmHost was single-operation; it now accepts op={op id: op text} (DRIVER fix).',
    'Each producer submits 16 jobs per operation per wave (64), one fresh record per job.',
    'e uses json_type + max_bytes + rule_provenance/1, not quoted_span: quoted_span accepts only a string value '
    '(oz_accept and oz_registry), so every correct e answer (a JSON array) would fail it. rule_provenance/1 is '
    'authorized for all four materials contract hashes (amendment 1 D1: "the four supplied materials contracts").',
    'Codex model gpt-6.1-sol, effort medium: the Codex default in ~/.codex/config.toml and the 6.1-sol medium runs in '
    'bench/codex_kit; Luna is excluded by the owner.',
    'Sonnet effort is "default" (no --effort flag), the configuration of the historical 91.6 tokens / 20 s cell the '
    'record allows as context; the host passes no OZ_EFFORT.',
    'Op texts are MAT_D verbatim, including "c[N]\'s" in e (live11.py rewrote it to "the ref\'s"; not done here).',
    'BoolQ op text and goal are new (data.BOOLQ_OP_TEXT, data.BOOLQ_GOAL); BoolQ runs on Codex only, cold only.',
    'BoolQ is the SuperGLUE distribution of the BoolQ validation split (owner approved; the Google bucket returned '
    '403); its labels are the dataset annotations, used for the 64 admission cases and for scoring only.',
    'Allocation (amendment 3): Codex reserve 7 = second telemetry invocation 1 + 6 for retries and overflow; Sonnet B '
    'has 4 dedicated residual calls (one per producer) and never uses the Sonnet reserve as its nominal allocation; '
    'Sonnet materials A, B and C form one cell with one shared bootstrap.',
    'No 55% weekly launch guard (owner decision 1); the 99% handoff stop and the frozen caps still bind.',
    'Dry-run replay answers are the oracle answers (a perfect model) and the rules are the spec\'s worked E/B/M/V '
    'ASTs, so the projection is an upper bound on coverage and correctness.',
    'Dry-run usage: every replayed call costs a recorded 64-job call of that backend, also the smaller residual and '
    'audit calls (conservative for B and C); BoolQ calls use the materials samples too, so BoolQ input tokens are '
    'underestimated by roughly the passage text.',
    'Bootstrap usage is an estimate (recorded 64-job call + shim system text + rule bytes + reasoning allowance).',
    'Dry-run makespans are replay projections (recorded 64-job elapsed per call, list-scheduled on 4 slots); the '
    'gates score measured makespan live; summed physical call seconds are reported separately and never replace '
    'makespan (amendment 3 sections 2 and 3).',
    'Gate readings: "preserves correctness" = C gold-correct count >= A; BoolQ "adds no gold errors" = C not-correct '
    'count <= A; the headline needs all five gates.',
]


# ------------------------------------------------------------------------------------------------- helpers

def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _dump(obj):
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + '\n'


def _write(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(_dump(obj))


def _rel(path):
    return Path(path).resolve().relative_to(REPO).as_posix()


# --------------------------------------------------------------------------------------------------- routes

def static_flags(backend):
    """The flags the adapter's `--identity` reports, read from the sources (the probe must agree at freeze)."""
    import bootstrap_shim
    if backend == 'codex':
        import codex_cli_adapter as real
        flags = list(real.FLAGS)
    else:
        import claude_map_adapter as real
        flags = list(real.FLAGS)
    return flags + ['bootstrap-shim=' + bootstrap_shim.ENVELOPE,
                    'bootstrap-spec-sha256=' + bootstrap_shim.SPEC_EXCERPT_SHA256]


def route_env(backend):
    """The nonsecret OZ_* variables the child sees (oz_host.child_env): OZ_MODEL, and OZ_EFFORT when set."""
    cfg = BACKENDS[backend]
    env = {'OZ_MODEL': cfg['model']}
    if cfg['host_effort'] is not None:
        env['OZ_EFFORT'] = cfg['host_effort']
    return env


def route(backend, identity=None):
    """The D7 route of one backend. With a frozen route record (routes.json, the whole oz_route.build result in the
    launch environment) that route; otherwise the static route whose cli_version is a marked placeholder until an
    identity record fills it."""
    import oz_route
    frozen = _routes().get(backend)
    if frozen is not None:
        return dict(frozen['route'])
    cfg = BACKENDS[backend]
    flags = static_flags(backend)
    cli = PLACEHOLDER
    if identity is not None:
        eff = oz_route.reconcile(identity, model=cfg['model'], effort=cfg['effort'])
        if eff['backend'] != cfg['route_backend']:
            raise ValueError(f'{backend}: identity backend {eff["backend"]!r}')
        if eff['flags'] != flags:
            raise ValueError(f'{backend}: identity flags {eff["flags"]} differ from the sources {flags}')
        cli = eff['cli_version']
    return {'adapter_hash': oz_route.adapter_hash(cfg['adapter']), 'backend': cfg['route_backend'],
            'model': cfg['model'], 'effort': cfg['effort'], 'cli_version': cli,
            'environment_hash': oz_route.environment_hash(cfg['adapter'], flags, route_env(backend))}


def _routes():
    if not ROUTES_FILE.exists():
        return {}
    return json.loads(ROUTES_FILE.read_text(encoding='utf-8'))


def build_routes(run=subprocess.run):
    """routes.json: for each backend the WHOLE oz_route.build result (route, worker_hash, launch snapshot, do_route)
    computed in the child environment the host launches with. No model call (the adapter's --identity)."""
    import oz_host
    import oz_route
    doc = {}
    for backend, cfg in BACKENDS.items():
        env = oz_host.child_env(model=cfg['model'], effort=cfg['host_effort'])
        doc[backend] = oz_route.build(cfg['adapter'], model=cfg['model'], effort=cfg['effort'], run=run, env=env)
    _write(ROUTES_FILE, doc)
    return doc


def route_check(backend):
    """The host's launch-time route check: oz_route.verify of the frozen build result in the real launch env."""
    cfg = BACKENDS[backend]
    frozen = _routes().get(backend)
    if frozen is None:
        raise SystemExit(f'refused: no frozen route for {backend} (run `pilot.py freeze`)')
    return {'frozen': frozen, 'adapter': str(cfg['adapter']), 'model': cfg['model'], 'effort': cfg['effort']}


def pilot_config(mode, routes, usage_semantics):
    """The frozen host configuration (oz_host.check_pilot): caps, global cap, slots, limits, intake, routes."""
    import oz_host
    return {'schema': oz_host.PILOT_SCHEMA, 'mode': mode, 'global_cap': GLOBAL_CAP, 'caps': CAPS,
            'slots': HOST['slots'], 'max_records': HOST['max_records'], 'max_wait': HOST['max_wait'],
            'intake': dict(HOST['intake']), 'limits': dict(HOST['limits']), 'usage_semantics': usage_semantics,
            'routes': routes}


# ------------------------------------------------------------------------------------------------- registry

def contracts():
    out = {op: {'name': f'materials_{op}', 'family': 'materials', 'deterministic': True, 'goal': data.MAT_GOAL,
                'instruction': data.MAT_D[op], 'result': RESULTS[op], 'input': 'one inspection record per job'}
           for op in data.OPS}
    out[data.BOOLQ_OP] = {'name': 'boolq_answer', 'dataset': 'BoolQ', 'deterministic': False,
                          'goal': data.BOOLQ_GOAL, 'instruction': data.BOOLQ_OP_TEXT,
                          'result': 'the string yes or no'}
    return out


def check_definitions():
    import oz_registry
    hashes = sorted(oz_registry.digest(c) for op, c in contracts().items() if op in data.OPS)
    checks = {}
    for op in data.OPS:
        checks[f'{op}_type'] = {'name': 'json_type', 'version': 1, 'kind': 'consumer',
                                'params': {'types': JSON_TYPES[op]}}
        checks[f'{op}_bytes'] = {'name': 'max_bytes', 'version': 1, 'kind': 'consumer',
                                 'params': {'bytes': MAX_BYTES[op]}}
    checks['materials_provenance'] = {'name': 'rule_provenance', 'version': 1, 'kind': 'provenance', 'params': {},
                                      'authorized_contract_hashes': hashes}
    checks['boolq_one_of'] = {'name': 'one_of', 'version': 1, 'kind': 'consumer', 'params': {'values': ['yes', 'no']}}
    return checks


def provenance(labeler, method):
    return {'labeler': labeler, 'method': method, 'independent': True, 'hidden_from_synthesis': True,
            'synthesis_agents': [BACKENDS[b]['model'] for b in BACKENDS]}


def operations(backend, boolq_source):
    """build_manifest operations for one backend. boolq_source: data.boolq() (or the dry stand-in) or None."""
    cases = data.admission_cases(oracle)
    rt = route(backend, _identity(backend))
    labeler = f'bench/ozmap/oracle.py sha256:{_sha_file(HERE / "oracle.py")}'
    ops = {}
    for op in data.OPS:
        ops[op] = {'contract': contracts()[op], 'checks': [f'{op}_type', f'{op}_bytes', 'materials_provenance'],
                   'permissions': {'rule_provenance': True}, 'input_policy': dict(INPUT_POLICY), 'route': dict(rt),
                   'cases': cases[op],
                   'provenance': provenance(labeler, 'independent oracle written from the op texts (MAT_GOAL, MAT_D); '
                                                     'no oz_rule, no AST')}
    if boolq_source is not None:
        q = boolq_source
        ops[data.BOOLQ_OP] = {
            'contract': contracts()[data.BOOLQ_OP], 'checks': ['boolq_one_of'], 'permissions': {},
            'input_policy': dict(INPUT_POLICY), 'route': dict(rt),
            'cases': [{'id': cid, 'text': text, 'partition': part,
                       'expected': oracle.label(data.BOOLQ_OP, text, answer)} for cid, text, part, answer in
                      q['admission']],
            'provenance': provenance('BoolQ dev labels (official dataset annotations)' if q.get('available') else
                                     'synthetic stand-in labels (dry run only)', 'dataset labels')}
    return ops


def build_manifests(boolq_source):
    import oz_registry
    checks = check_definitions()
    return {b: oz_registry.build_manifest(operations(b, boolq_source), checks, APPROVED_BY) for b in BACKENDS}


def build_registry_file():
    import oz_registry
    q = data.boolq()
    manifests = build_manifests(q if q['available'] else None)
    placeholders = sorted(f'{b}: route.cli_version' for b in BACKENDS if _identity(b) is None)
    doc = {'schema': 'ozmap.registry-set/1', 'boolq': 'available' if q['available'] else q['reason'],
           'placeholders': placeholders, 'manifests': manifests,
           'manifest_sha256': {b: oz_registry.digest(m) for b, m in manifests.items()}}
    _write(REGISTRY_FILE, doc)
    return doc


def load_registry(backend, doc=None):
    import oz_registry
    doc = doc or json.loads(REGISTRY_FILE.read_text(encoding='utf-8'))
    manifest = doc['manifests'][backend]
    return oz_registry.Registry(manifest, expected_sha256=doc['manifest_sha256'][backend])


def _identity(backend):
    if not IDENTITY_FILE.exists():
        return None
    return json.loads(IDENTITY_FILE.read_text(encoding='utf-8')).get(backend)


# --------------------------------------------------------------------------------------------------- matrix

def matrix_spec(boolq_available):
    """The frozen cell order. Each cell: backend, workload, ops, goal, arms, waves [(name, learn, arms)]."""
    mat_ops = {op: data.MAT_D[op] for op in data.OPS}
    cells = [
        {'id': 'codex-materials', 'backend': 'codex', 'workload': 'materials', 'op': mat_ops, 'goal': data.MAT_GOAL,
         'arms': ['A', 'B', 'C'], 'waves': [('cold', True, None), ('warm', False, ['A', 'C'])]},
        {'id': 'codex-boolq', 'backend': 'codex', 'workload': 'boolq', 'op': data.BOOLQ_OP,
         'op_text': data.BOOLQ_OP_TEXT, 'goal': data.BOOLQ_GOAL, 'arms': ['A', 'B', 'C'],
         'waves': [('cold', True, None)], 'available': boolq_available},
        {'id': 'sonnet-materials', 'backend': 'sonnet', 'workload': 'materials', 'op': mat_ops, 'goal': data.MAT_GOAL,
         'arms': ['A', 'B', 'C'], 'waves': [('cold', True, None), ('warm', False, ['A', 'C'])]},
    ]
    return cells


def nominal_calls(cell, wave, arm, n_jobs=256, producers=4, max_records=64, audits=32):
    """Nominal physical calls of one arm and wave, assuming every eligible residual job is covered by a rule
    (materials) and no rule for BoolQ. Returns (calls, bucket list)."""
    boolq = cell['workload'] == 'boolq'
    learn = wave == 'cold'
    if arm == 'A':
        return [(cell['backend'], 'A', math.ceil(n_jobs / max_records), 'ordinary')]
    rest = n_jobs - (64 if learn else 0)
    rows = []
    if learn and arm == cell.get('_bootstrap_arm'):
        rows.append((cell['backend'], 'bootstrap' if 'bootstrap' in CAPS[cell['backend']] else arm, 1,
                     'bootstrap'))
    if arm == 'B':
        rest_p = rest // producers
        # fallbacks + audits of one producer never exceed its residual jobs, so one call per producer
        rows.append((cell['backend'], 'B' if 'B' in CAPS[cell['backend']] else 'reserve',
                     producers * math.ceil(rest_p / max_records), 'residual, producer-local'))
    else:
        residual = rest if boolq else min(audits, rest)
        rows.append((cell['backend'], 'C', math.ceil(residual / max_records), 'residual, pooled'))
    return rows


def plan(boolq_available=None):
    import oz_host
    if boolq_available is None:
        boolq_available = data.boolq()['available']
    cells = matrix_spec(boolq_available)
    need = {}
    lines = []
    claimed = set()
    for cell in cells:
        order = oz_host.arm_order(SEED, cell['backend'], cell['workload'], cell['arms'])
        key = (cell['backend'], cell['workload'])
        for name, learn, arms in cell['waves']:
            for arm in [a for a in order if a in (arms or order)]:
                c = dict(cell)
                if learn and arm in 'BC' and key not in claimed:
                    c['_bootstrap_arm'] = arm
                    claimed.add(key)
                for backend, bucket, n, kind in nominal_calls(c, name, arm):
                    need.setdefault(backend, {}).setdefault(bucket, 0)
                    need[backend][bucket] += n
                    lines.append({'cell': cell['id'], 'wave': name, 'arm': arm, 'bucket': bucket, 'calls': n,
                                  'kind': kind,
                                  'available': cell.get('available', True)})
    need['codex']['telemetry'] = need['codex'].get('telemetry', 0) + 1
    need['codex']['reserve'] = need['codex'].get('reserve', 0) + 1  # the second paired telemetry invocation
    table, incomplete = [], []
    used = {}
    for backend, caps in CAPS.items():
        for bucket, cap in caps.items():
            n = need.get(backend, {}).get(bucket, 0)
            table.append({'backend': backend, 'bucket': bucket, 'allocation': cap, 'nominal': n,
                          'fits': n <= cap})
            used[backend] = used.get(backend, 0) + min(n, cap)
            if n > cap:
                short = n - cap
                cells_short = [l for l in lines if l['bucket'] == bucket and l['cell'].startswith(backend)]
                incomplete.append({'backend': backend, 'bucket': bucket, 'needed': n, 'allocated': cap,
                                   'short_calls': short, 'cells': sorted({f"{l['cell']} {l['wave']} {l['arm']}"
                                                                          for l in cells_short})})
    total_alloc = sum(sum(c.values()) for c in CAPS.values())
    out = {'seed': SEED, 'global_cap': GLOBAL_CAP, 'allocation_total': total_alloc, 'caps': CAPS, 'host': HOST,
           'quota_stop': QUOTA_STOP, 'gate_texts': score.GATE_TEXTS,
           'backends': {b: {k: v for k, v in cfg.items() if k != 'adapter'} | {'adapter': _rel(cfg['adapter'])}
                        for b, cfg in BACKENDS.items()},
           'arm_orders': {c['id']: oz_host.arm_order(SEED, c['backend'], c['workload'], c['arms']) for c in cells},
           'cells': lines, 'table': table, 'nominal_physical_calls': sum(used.values()),
           'fits_global_cap': total_alloc <= GLOBAL_CAP and sum(used.values()) <= GLOBAL_CAP,
           'complete': not incomplete and boolq_available, 'incomplete': incomplete,
           'boolq_available': boolq_available, 'boolq_source': data.BOOLQ_SOURCE, 'assumptions': ASSUMPTIONS}
    if not boolq_available:
        out['incomplete'] = out['incomplete'] + [{'cells': ['codex-boolq cold A', 'codex-boolq cold B',
                                                            'codex-boolq cold C'],
                                                  'reason': 'bench/ozmap/data/boolq-superglue-val.jsonl is absent'}]
    return out


def print_plan(p):
    print(f"seed {p['seed']}  global cap {p['global_cap']}  allocated {p['allocation_total']}  "
          f"nominal physical calls {p['nominal_physical_calls']}  fits global cap: {p['fits_global_cap']}")
    print('host:', json.dumps(p['host'], sort_keys=True))
    print('quota:', p['quota_stop'])
    print('\nbackend  bucket     alloc  nominal  fits')
    for r in p['table']:
        print(f"{r['backend']:<8} {r['bucket']:<10} {r['allocation']:>5}  {r['nominal']:>7}  {r['fits']}")
    print('\ncell                       wave  arm  bucket     calls  kind')
    for l in p['cells']:
        flag = '' if l['available'] else '  (BoolQ unavailable: not launched)'
        print(f"{l['cell']:<26} {l['wave']:<5} {l['arm']:<4} {l['bucket']:<10} {l['calls']:>5}  {l['kind']}{flag}")
    print('telemetry (codex)          -     -    telemetry      1  paired telemetry 1 of 2')
    print('telemetry (codex)          -     -    reserve        1  paired telemetry 2 of 2')
    print('\narm orders (seeded):', json.dumps(p['arm_orders']))
    src = p['boolq_source']
    print(f"BoolQ: {'available' if p['boolq_available'] else 'UNAVAILABLE'}; {src['file']} sha256 {src['file_sha256']} "
          f"({src['lines']} lines) from {src['url']} (zip sha256 {src['zip_sha256']}, member {src['member']})")
    print('complete matrix fits:', p['complete'])
    for inc in p['incomplete']:
        print('INCOMPLETE:', json.dumps(inc))
    print('\nassumptions:')
    for a in p['assumptions']:
        print(' * ' + a)


# ------------------------------------------------------------------------------------------- recorded usage

def _usage(sample):
    return {k: v for k, v in sample.items()}


def recorded_usage():
    """{backend: {"call": [...], "bootstrap": [...]}} from real 64-job ledgers, plus the bootstrap estimate."""
    import bootstrap_shim
    out = {}
    calls = []
    for line in LEDGERS['codex'].read_text(encoding='utf-8').splitlines():
        r = json.loads(line)
        if r.get('n') == 64 and r.get('arm') == 'S1d' and r.get('exit_code') == 0:
            u = r['usage']
            calls.append({'input_tokens': u['input_tokens'], 'cached_input_tokens': u['cached_input_tokens'],
                          'cache_creation_input_tokens': u.get('cache_write_input_tokens', 0),
                          'output_tokens': u['output_tokens'],
                          'reasoning_output_tokens': u['reasoning_output_tokens'], 'elapsed_seconds': r['wall_s'],
                          'source': f"{_rel(LEDGERS['codex'])} rep {r['rep']}"})
    out['codex'] = {'call': calls}
    calls = []
    for line in LEDGERS['sonnet'].read_text(encoding='utf-8').splitlines():
        r = json.loads(line)
        if r.get('arm') == 'H' and r.get('jobs') == 64 and r.get('valid') and not r.get('is_error'):
            calls.append({'input_tokens': r['in'], 'cached_input_tokens': r['cache_read'],
                          'cache_creation_input_tokens': r['cache_write'], 'output_tokens': r['out'],
                          'reasoning_output_tokens': r['thinking'], 'elapsed_seconds': r['wall_s'],
                          'source': f"{_rel(LEDGERS['sonnet'])} seq {r['seq']}"})
    out['sonnet'] = {'call': calls}
    config = {'schema': 'oz.bootstrap.config/2', 'ops': list(data.OPS),
              'contracts': {op: contracts()[op] for op in data.OPS}, 'eligibility': {op: True for op in data.OPS}}
    added_chars = len(bootstrap_shim.system_text('', config))
    extra_in = round(added_chars / CHARS_PER_TOKEN)
    ast_bytes = sum(len(a.encode('utf-8')) for a in bootstrap_shim.HIDDEN_ASTS) + 64
    extra_out = round(ast_bytes / AST_BYTES_PER_TOKEN) + BOOTSTRAP_REASONING_ALLOWANCE
    for backend in out:
        boots = []
        for c in out[backend]['call']:
            b = dict(c, input_tokens=c['input_tokens'] + extra_in, output_tokens=c['output_tokens'] + extra_out,
                     reasoning_output_tokens=c['reasoning_output_tokens'] + BOOTSTRAP_REASONING_ALLOWANCE,
                     elapsed_seconds=round(c['elapsed_seconds'] * (c['output_tokens'] + extra_out)
                                           / max(1, c['output_tokens']), 3),
                     source='estimate: ' + c['source'] + f' + {extra_in} system tokens + {extra_out} output tokens')
            boots.append(b)
        out[backend]['bootstrap'] = boots
    out['_estimate'] = {'bootstrap_added_system_chars': added_chars, 'bootstrap_extra_input_tokens': extra_in,
                        'bootstrap_extra_output_tokens': extra_out}
    return out


def elapsed_sensitivity():
    """Recorded mean elapsed of 32-job and 64-job calls per backend. The dry run serves 64-job elapsed to every
    call; a warm C wave whose only call carries the 32 audits would instead take about mean32 / mean64 of A's
    makespan (A's four 64-job calls run in parallel on four slots)."""
    out = {}
    for backend in BACKENDS:
        by_n = {32: [], 64: []}
        for path in {LEDGERS[backend], LEDGERS_32[backend]}:
            for line in path.read_text(encoding='utf-8').splitlines():
                r = json.loads(line)
                if backend == 'codex' and r.get('arm') == 'S1d' and r.get('exit_code') == 0 and r.get('n') in by_n:
                    by_n[r['n']].append(r['wall_s'])
                elif backend == 'sonnet' and r.get('arm') == 'H' and r.get('valid') and r.get('jobs') in by_n:
                    by_n[r['jobs']].append(r['wall_s'])
        m32, m64 = (round(sum(v) / len(v), 3) if v else None for v in (by_n[32], by_n[64]))
        out[backend] = {'mean_elapsed_32': m32, 'mean_elapsed_64': m64, 'samples': {k: len(v) for k, v in by_n.items()},
                        'warm_makespan_ratio_if_size_scaled': round(m32 / m64, 3) if m32 and m64 else None}
    return out


# ------------------------------------------------------------------------------------------------------ dry

def _answers(boolq_source):
    table = {}
    mat = data.materials()
    for wave in data.WAVES:
        for jobs in mat['waves'][wave].values():
            for j in jobs:
                table[oracle.resolve(j['text'])] = oracle.gold(j['op'], j['text'])
    for jobs in boolq_source['waves']['cold'].values():
        for j in jobs:
            table[oracle.resolve(j['text'])] = oracle.gold(data.BOOLQ_OP, '', boolq_source['labels'][j['dataset_id']])

    def answer(text):
        return table[text]
    return answer


def dry_matrix(experiment_dir):
    """The dry-run matrix for oz_host.dry_run: the frozen cells with replay answers and the worked ASTs as rules."""
    import bootstrap_shim
    import oz_registry
    q = data.boolq()
    source = q if q['available'] else data.boolq_standin()
    manifests = build_manifests(source)
    mat = data.materials()
    answer = _answers(source)
    rules = dict(zip(data.OPS, bootstrap_shim.HIDDEN_ASTS))
    import oz_host
    routes = {}
    for b in BACKENDS:
        rt = manifests[b]['operations']['e']['route']
        routes[b] = dict(oz_host.identity_for(rt), launch=None)
    cells = []
    for spec in matrix_spec(True):
        backend = spec['backend']
        waves = []
        for name, learn, arms in spec['waves']:
            producers = (mat['waves'][name] if spec['workload'] == 'materials' else source['waves'][name])
            waves.append({'name': name, 'learn': learn, 'arms': arms, 'producers': producers})
        cells.append({'backend': backend, 'workload': spec['workload'],
                      'registry': oz_registry.Registry(manifests[backend]), 'op': spec['op'],
                      'op_text': spec.get('op_text'), 'goal': spec['goal'], 'model': BACKENDS[backend]['model'],
                      'effort': BACKENDS[backend]['host_effort'],
                      'route': manifests[backend]['operations']['e']['route'], 'identity': routes[backend],
                      'answer': answer,
                      'rules': rules if spec['workload'] == 'materials' else {data.BOOLQ_OP: 'none'},
                      'arms': spec['arms'], 'waves': waves, '_id': spec['id']})
    # The dry run runs under the frozen pilot configuration (mode dry, replay launchers) except the flush wait, which
    # is 0 s so a replayed wave does not sleep; the batches it forms are the same (every group is full or final).
    config = pilot_config('dry', routes, 'replay: recorded usage samples (dry run)')
    config['max_wait'] = 0.0
    return {'seed': SEED, 'experiment_dir': str(experiment_dir), 'caps': CAPS, 'global_cap': GLOBAL_CAP,
            'max_wait': 0.0, 'slots': HOST['slots'], 'pilot': config, 'cells': cells}, source


def _reserve_telemetry(budget):
    for key, buckets in TELEMETRY_KEYS:
        if budget.reserve(key, backend='codex', buckets=buckets, arm='T', kind='telemetry') is None:
            raise RuntimeError('telemetry does not fit the frozen budget')


def dry(experiment_dir=None, verbose=True):
    import tempfile
    import oz_host
    temp = None
    if experiment_dir is None:
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        experiment_dir = temp.name
    try:
        experiment_dir = Path(experiment_dir)
        budget = oz_host.Budget(experiment_dir / 'budget.sqlite', caps=CAPS, global_cap=GLOBAL_CAP)
        _reserve_telemetry(budget)
        budget.close()
        matrix, source = dry_matrix(experiment_dir)
        usage = recorded_usage()
        t0 = time.time()
        out = oz_host.dry_run(matrix, {k: v for k, v in usage.items() if not k.startswith('_')})
        result = summarize_dry(out, matrix, usage, source)
        result['wall_seconds'] = round(time.time() - t0, 1)
        if verbose:
            print_dry(result)
        return result
    finally:
        if temp is not None:
            temp.cleanup()


def summarize_dry(out, matrix, usage, source):
    rows, summary_cells = [], {}
    by_backend = {}
    for spec, cell in zip(matrix['cells'], out['cells']):
        for wave in cell['waves']:
            for arm, r in wave['arms'].items():
                tok = r['tokens']['charged']
                jobs = r['jobs']
                row = {'cell': spec['_id'], 'backend': cell['backend'], 'workload': cell['workload'],
                       'wave': wave['name'], 'arm': arm, 'jobs': jobs, 'accepted': r['accepted_by_checks'],
                       'unresolved': r['unresolved'], 'rule_hits': r['rule_hits'], 'coverage': r['coverage'],
                       'physical_calls': r['calls']['physical'], 'imported_calls': r['calls']['imported'],
                       'charged_calls': r['calls']['charged'], 'refused': r['calls']['refused'],
                       'tokens': tok['tokens'], 'input_tokens': tok['input_tokens'],
                       'output_tokens': tok['output_tokens'],
                       'tokens_per_job': round(tok['tokens'] / jobs, 1) if jobs else None,
                       'makespan_s': r['projected_makespan_seconds'],
                       'replayed_call_seconds': r['replayed_call_seconds'],
                       'audits_selected': r['audits']['selected'],
                       'evidence': r['evidence'], 'incomplete': r['incomplete'],
                       'efficiency_valid': r['efficiency_valid'], 'efficiency_invalid': r['efficiency_invalid']}
                rows.append(row)
                by_backend.setdefault(cell['backend'], 0)
                by_backend[cell['backend']] += r['calls']['physical']
                counts = {'correct': r['accepted_by_checks'], 'incorrect': 0,
                          'unresolved': jobs - r['accepted_by_checks']}
                summary_cells[f"{cell['backend']}/{cell['workload']}/{wave['name']}/{arm}"] = score.summarize(
                    jobs, counts, rule_errors=0, fallback_errors=0, rule_hits=r['rule_hits'], report=r,
                    makespan=r['projected_makespan_seconds'], summed_call_seconds=r['replayed_call_seconds'])
    by_backend['codex'] = by_backend.get('codex', 0) + len(TELEMETRY_KEYS)
    total = out['physical_calls'] + len(TELEMETRY_KEYS)
    boots = {}
    for spec, cell in zip(matrix['cells'], out['cells']):
        for wave in cell['waves']:
            for arm, r in wave['arms'].items():
                if r['bootstrap']:
                    boots[f"{cell['backend']}/{cell['workload']}"] = {'status': r['bootstrap']['status'],
                                                                      'gold_errors': 0, 'disagreements': 0}
    budget = out['budget']
    projected = {'cells': summary_cells, 'boolq_available': True,
                 'validity': {'leakage': leakage_problems(), 'bootstrap': boots,
                              'budget': dict(budget, over=score.budget_over(budget))}}
    gates = score.evaluate(projected)
    incomplete = [f"{r['cell']} {r['wave']} {r['arm']}: {', '.join(r['incomplete'])}" for r in rows
                  if r['evidence'] != 'complete']
    return {'rows': rows, 'external_calls': out['external_calls'], 'physical_calls_by_backend': by_backend,
            'physical_calls_total': total, 'budget': budget, 'reconciliation': out['reconciliation'],
            'dry_run_fits': out['fits'], 'within_global_cap': total <= GLOBAL_CAP,
            'sources': dry_sources(usage), 'assumptions': ASSUMPTIONS,
            'evidence': out['evidence'], 'incomplete_cells': incomplete,
            'boolq': 'real BoolQ' if source.get('available') else 'synthetic stand-ins (real BoolQ file absent)',
            'usage_samples': {b: [s['source'] for s in usage[b]['call']] for b in BACKENDS},
            'bootstrap_estimate': usage['_estimate'], 'projected_gates': gates,
            'elapsed_sensitivity': elapsed_sensitivity()}


def dry_sources(usage):
    """The dry run's source records (amendment 3 section 4): every recorded usage sample, the bootstrap estimate and
    the fact that BoolQ calls replay materials samples."""
    return {'ledgers': {b: {'file': _rel(LEDGERS[b]), 'sha256': _sha_file(LEDGERS[b])} for b in BACKENDS},
            'samples': {b: [s['source'] for s in usage[b]['call']] for b in BACKENDS},
            'bootstrap': {'estimated': True, **usage['_estimate']},
            'boolq_usage': 'materials usage samples (BoolQ input tokens underestimated by about the passage text)'}


def print_dry(r):
    print(f"external calls {r['external_calls']}; physical calls {r['physical_calls_total']} "
          f"(by backend {r['physical_calls_by_backend']}, incl. 2 telemetry); within global cap {GLOBAL_CAP}: "
          f"{r['within_global_cap']}; every launch fit: {r['dry_run_fits']}; reconciliation ok: "
          f"{r['reconciliation']['ok']}")
    print(f"BoolQ: {r['boolq']}")
    print('\ncell                 wave arm jobs  phys/charged/refused   tokens  tok/job  projected_s  call_s  '
          'coverage audits evidence')
    for x in r['rows']:
        print(f"{x['cell']:<20} {x['wave']:<4} {x['arm']:<3} {x['jobs']:>4}  {x['physical_calls']:>4}/"
              f"{x['charged_calls']:>2}/{x['refused']:<2}       {x['tokens']:>9} {x['tokens_per_job']:>8} "
              f"{x['makespan_s']:>12} {x['replayed_call_seconds']:>7} {x['coverage']:>8} {x['audits_selected']:>6} "
              f"{x['evidence']}")
    print('\nbudget used:', json.dumps(r['budget']['used'], sort_keys=True), 'total', r['budget']['total'])
    for line in r['incomplete_cells']:
        print('INCOMPLETE:', line)
    print('\nprojected gates (replay = oracle answers, worked ASTs):', r['projected_gates']['verdict'])
    for g in r['projected_gates']['gates']:
        detail = g['detail'] if not isinstance(g['detail'], dict) else {
            k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk != 'checks'})
            for k, v in g['detail'].items()}
        print(f"  {g['gate']} {g['name']}: {'pass' if g['pass'] else 'FAIL'} {json.dumps(detail)}")
    print('\nelapsed sensitivity (recorded 32-job vs 64-job calls):', json.dumps(r['elapsed_sensitivity']))
    print('bootstrap estimate:', json.dumps(r['bootstrap_estimate']))


# -------------------------------------------------------------------------------------------------- leakage

def leakage_problems():
    """Admission texts disjoint from evaluation and telemetry texts (resolved); the cold and warm evaluation waves
    disjoint (council 3, B12); no worked AST or admission text in any registry contract shown to the model."""
    import bootstrap_shim
    problems = []
    mat = data.materials()
    cold, warm = ({oracle.resolve(j['text']) for js in mat['waves'][w].values() for j in js} for w in ('cold', 'warm'))
    if cold & warm:
        problems.append(f'{len(cold & warm)} warm texts are also cold texts')
    evaluation = {oracle.resolve(j['text']) for w in data.WAVES for js in mat['waves'][w].values() for j in js}
    evaluation |= {oracle.resolve(j['text']) for j in mat['telemetry']}
    admission = {oracle.resolve(t) for rows in mat['admission_texts'].values() for _, t, _, _ in rows}
    if evaluation & admission:
        problems.append(f'{len(evaluation & admission)} admission texts are also evaluation texts')
    shown = json.dumps(contracts(), ensure_ascii=False)
    if any(a in shown for a in bootstrap_shim.HIDDEN_ASTS):
        problems.append('a worked AST is in a contract')
    if any(t in shown for t in admission):
        problems.append('an admission text is in a contract')
    return problems


# ---------------------------------------------------------------------------------------------------- freeze

FROZEN_CORE = ('oz.py', 'oz_accept.py', 'oz_batch.py', 'oz_cli.py', 'oz_do.py', 'oz_fault.py', 'oz_memo.py',
               'oz_reply.py', 'oz_runner.py', 'oz_runtime.py', 'oz_worker.py', 'oz_workspace.py')
FREEZE_FILES = (
    [f'bench/ozmap/{n}' for n in ('data.py', 'oracle.py', 'score.py', 'pilot.py', 'registry.json', 'identity.json')]
    + ['bench/ozmap/routes.json']
    + ['tests/test_ozmap_pilot.py', 'oz_host.py', 'oz_registry.py', 'oz_rule.py', 'oz_rulephase.py', 'oz_spool.py',
       'oz_route.py', 'oz_map.py', 'oz_quota.py', *FROZEN_CORE,
       'examples/bootstrap_shim.py', 'examples/codex_cli_adapter.py', 'examples/claude_map_adapter.py',
       'examples/claude_cli_adapter.py', 'examples/bootstrap_codex_adapter.json',
       'examples/bootstrap_claude_adapter.json', 'bench/live/live2.py',
       'docs/design/ozmap-2026-10-24/bootstrap-spec-excerpt.txt',
       'docs/design/brainstorm-2026-10-24/05-joint-record.md',
       'docs/design/ozmap-2026-10-24/amendment-2-and-step6-architecture.md',
       'docs/design/ozmap-2026-10-24/oz-rule-1-amendment-1.md', 'docs/design/ozmap-2026-10-24/oz-rule-1-spec.md',
       'docs/design/ozmap-2026-10-24/council2-astra.md', 'docs/design/ozmap-2026-10-24/council2-opus.md',
       'docs/design/ozmap-2026-10-24/council3-astra.md', 'docs/design/ozmap-2026-10-24/council3-opus.md',
       'docs/design/ozmap-2026-10-24/owner-decisions-2026-10-24.md', 'docs/design/ozmap-2026-10-24/amendment-3.md',
       _rel(LEDGERS['codex']), _rel(LEDGERS['sonnet']), _rel(LEDGERS_32['sonnet']), data.BOOLQ_SOURCE['file']])


def git_dirty(paths, root=REPO, run=subprocess.run):
    """Paths among these with uncommitted changes (modified, staged or untracked)."""
    done = run(['git', 'status', '--porcelain', '--untracked-files=all', '--', *paths], cwd=root,
               capture_output=True, text=True, encoding='utf-8')
    if done.returncode != 0:
        return ['<git status failed: ' + (done.stderr or '').strip()[:200] + '>']
    return [line[3:] for line in done.stdout.splitlines() if line.strip()]


def freeze_record(root=REPO, files=FREEZE_FILES, *, datasets=None, plan_obj=None):
    root = Path(root)
    hashes = {}
    for rel in files:
        path = root / rel
        hashes[rel] = _sha_file(path) if path.is_file() else None
    plan_obj = plan_obj if plan_obj is not None else plan()
    record = {'schema': 'ozmap.freeze/1', 'seed': SEED, 'files': hashes,
              'datasets': datasets if datasets is not None else data.dataset_digests(),
              'plan': plan_obj, 'plan_sha256': hashlib.sha256(json.dumps(plan_obj, sort_keys=True).encode()).hexdigest()}
    record['boolq_source'] = data.BOOLQ_SOURCE
    # Amendment 3 section 4: the normative documents with their hashes and precedence, the owner decisions, the
    # revised allocation, the exact gate texts, the timing boundaries, and the dry run's sources and assumptions.
    record['normative'] = {'precedence': list(NORMATIVE), 'rule': 'a later document supersedes conflicting text in '
                                                                   'an earlier one',
                           'sha256': {rel: hashes.get(rel) or (_sha_file(root / rel) if (root / rel).is_file()
                                                               else None) for rel in NORMATIVE}}
    record['allocation'] = {'global_cap': GLOBAL_CAP, 'caps': CAPS, 'quota': QUOTA_STOP}
    record['gate_texts'] = score.GATE_TEXTS
    record['timing'] = score.TIMING
    record['host'] = HOST
    record['dry_run'] = {'assumptions': ASSUMPTIONS, 'sources': {
        'ledgers': {b: {'file': _rel(LEDGERS[b]), 'sha256': hashes.get(_rel(LEDGERS[b]))} for b in BACKENDS},
        'bootstrap': 'estimated: recorded 64-job call + shim system text + rule bytes + reasoning allowance',
        'boolq_usage': 'materials usage samples'}}
    return record


def verify_freeze(record, root=REPO, *, datasets=None, plan_obj=None):
    """Problems (empty when the freeze record matches the current files, datasets and plan)."""
    root = Path(root)
    problems = []
    for rel, sha in record['files'].items():
        path = root / rel
        now = _sha_file(path) if path.is_file() else None
        if now != sha:
            problems.append(f'{rel} changed since the freeze')
    now = datasets if datasets is not None else data.dataset_digests()
    if now != record['datasets']:
        problems.append('a dataset changed since the freeze')
    p = plan_obj if plan_obj is not None else plan()
    if hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest() != record['plan_sha256']:
        problems.append('the plan changed since the freeze')
    return problems


def fill_identity():
    """Rewrite registry.json with the recorded identities (cli_version). Returns True when it changed."""
    if not IDENTITY_FILE.exists():
        raise SystemExit('freeze refused: no identity record. Run `python bench/ozmap/pilot.py identity` first '
                         '(no model call; it runs each adapter with --identity).')
    before = REGISTRY_FILE.read_bytes() if REGISTRY_FILE.exists() else None
    doc = build_registry_file()
    if doc['placeholders']:
        raise SystemExit('freeze refused: identity placeholders remain: ' + ', '.join(doc['placeholders']))
    return before != REGISTRY_FILE.read_bytes()


def freeze(run=subprocess.run):
    build_routes(run=run)  # the whole oz_route.build result per backend in the launch env (B11); no model call
    if fill_identity():
        print('registry.json was rebuilt with the recorded identities; review and commit bench/ozmap/registry.json '
              'and bench/ozmap/identity.json, then run freeze again.')
        return 3
    dirty = git_dirty(list(FREEZE_FILES), run=run)
    if dirty:
        print('freeze refused: uncommitted changes in frozen files:\n  ' + '\n  '.join(dirty))
        return 2
    problems = leakage_problems()
    if problems:
        print('freeze refused: leakage lint: ' + '; '.join(problems))
        return 2
    record = freeze_record()
    head = run(['git', 'rev-parse', 'HEAD'], cwd=REPO, capture_output=True, text=True).stdout.strip()
    record['git_head'] = head
    record['registry_manifest_sha256'] = json.loads(REGISTRY_FILE.read_text(encoding='utf-8'))['manifest_sha256']
    _write(FREEZE_FILE, record)
    print(f'freeze.json written ({len(record["files"])} files, git {head[:12]})')
    return 0


# ------------------------------------------------------------------------------------------------ identity

def probe_identity(backend):
    """The adapter's own `--identity` report under the child environment the host will use. No model call."""
    import oz_host
    cfg = BACKENDS[backend]
    argv = json.loads(cfg['adapter'].read_text(encoding='utf-8'))['argv']
    env = oz_host.child_env(model=cfg['model'], effort=cfg['host_effort'])
    done = subprocess.run([sys.executable if argv[0] == 'python' else argv[0], *argv[1:], '--identity'],
                          cwd=cfg['adapter'].parent, env=env, capture_output=True, text=True, encoding='utf-8',
                          timeout=120, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        raise SystemExit(f'{backend}: --identity exited {done.returncode}: {(done.stderr or done.stdout)[:300]}')
    return json.loads(done.stdout)


def record_identity():
    doc = {b: probe_identity(b) for b in BACKENDS}
    _write(IDENTITY_FILE, doc)
    print(_dump(doc))
    return 0


# --------------------------------------------------------------------------------------------- live guards

def guard(args):
    """None when a paid command may proceed, else the refusal text. Order: freeze exists and verifies, approval."""
    if not FREEZE_FILE.exists():
        return 'refused: no freeze.json (run plan, registry, identity, freeze first)'
    record = json.loads(FREEZE_FILE.read_text(encoding='utf-8'))
    problems = verify_freeze(record)
    if problems:
        return 'refused: freeze.json does not verify: ' + '; '.join(problems[:10])
    if not getattr(args, 'i_have_approval', False):
        return 'refused: pass --i-have-approval (explicit owner approval for paid calls)'
    if getattr(args, 'command', None) == 'run' and not getattr(args, 'live', False):
        return 'refused: pass --live'
    return None


def _reconcile_routes():
    """Recompute every backend's route in the launch env (oz_route.verify of the frozen build result, no model call)
    and require the registry manifest to carry exactly that route."""
    import oz_host
    import oz_route
    doc = json.loads(REGISTRY_FILE.read_text(encoding='utf-8'))
    for backend, cfg in BACKENDS.items():
        check = route_check(backend)
        if doc['manifests'][backend]['operations']['e']['route'] != check['frozen']['route']:
            raise SystemExit(f'refused: the registry route of {backend} is not the frozen route (D7)')
        try:
            oz_route.verify(check['frozen'], {k: v for k, v in check.items() if k != 'frozen'},
                            env=oz_host.child_env(model=cfg['model'], effort=cfg['host_effort']))
        except Exception as exc:
            raise SystemExit(f'refused: {exc}') from None
    return doc


def launch_gate_for(budget):
    """The live launch gate: the frozen global cap. There is no 55% weekly guard (owner decision 1, amendment 3)."""
    def gate(view):
        if budget.usage()['total'] >= GLOBAL_CAP:
            return 'global_cap_reached'
        return None
    return gate


def _usage_semantics():
    doc = json.loads(TELEMETRY_FILE.read_text(encoding='utf-8')) if TELEMETRY_FILE.exists() else {}
    return ('inclusive usage verified by paired telemetry ' + doc.get('run_dir', '')) if doc.get('status') == 'ok' \
        else 'unverified'


def telemetry(args):
    refusal = guard(args)
    if refusal:
        print(refusal)
        return 2
    import oz_host
    from oz_workspace import initialize
    doc = _reconcile_routes()
    record = json.loads(FREEZE_FILE.read_text(encoding='utf-8'))
    run_dir = RUNS / ('live-' + hashlib.sha256(_dump(record).encode()).hexdigest()[:12])
    budget = oz_host.Budget(run_dir / 'budget.sqlite', caps=CAPS, global_cap=GLOBAL_CAP)
    pool = oz_host.SlotPool(run_dir / 'slots', HOST['slots'])
    cfg = BACKENDS['codex']
    rt = doc['manifests']['codex']['operations']['e']['route']
    ident = oz_host.identity_for(rt)
    ws = run_dir / 'telemetry' / 'ws'
    if not (ws / 'oz.json').exists():
        initialize(ws)
    launcher = oz_host.ChildLauncher(cfg['adapter'])
    results = []
    for (key, buckets), job in zip(TELEMETRY_KEYS, data.materials()['telemetry']):
        if budget.reserve(key, backend='codex', buckets=buckets, arm='T', kind='telemetry') is None:
            print('telemetry refused: budget')
            return 2
        request = {'v': 'oz.do/1', 'request_id': key, 'goal': data.MAT_GOAL, 'ops': {job['op']: data.MAT_D[job['op']]},
                   'refs': {'r0': oracle.resolve(job['text'])}, 'jobs': [['j0', job['op'], 'r0']],
                   'profile': oz_host.PROFILE, 'allow_experimental': True, 'max_inline_bytes': oz_host.MAX_INLINE,
                   'max_attempts': 1, 'max_jobs_per_call': 1, 'max_input_tokens': 1000000, 'model': cfg['model']}
        spec = {'workspace': str(ws), 'request': request, 'max_calls': 1, 'route': ident['do_route'],
                'experimental_sizes': [], 'child_timeout': oz_host.child_timeout(HOST['limits'])}
        env = oz_host.child_env(model=cfg['model'], effort=cfg['host_effort'])
        import oz_route
        oz_route.verify(route_check('codex')['frozen'], {k: v for k, v in route_check('codex').items()
                                                         if k != 'frozen'}, env=env)
        lock = pool.acquire()  # telemetry takes the same experiment-wide slots (B9)
        try:
            execution, meta = launcher(spec, env, run_dir / 'telemetry' / key)
        finally:
            pool.release(lock)
        calls = (execution or {}).get('calls') or []
        usage = [c.get('usage') for c in calls]
        inclusive = all(isinstance(u, dict) and u.get('input_tokens', 0) >= u.get('cached_input_tokens', 0)
                        and u.get('output_tokens', 0) >= u.get('reasoning_output_tokens', 0) for u in usage) and usage
        results.append({'key': key, 'exit': meta, 'calls': calls, 'inclusive_usage_verified': bool(inclusive)})
    status = 'ok' if all(r['inclusive_usage_verified'] for r in results) else 'unverified'
    _write(TELEMETRY_FILE, {'status': status, 'run_dir': _rel(run_dir), 'results': results})
    print('telemetry', status)
    budget.close()
    return 0 if status == 'ok' else 1


def run_live(args):
    refusal = guard(args)
    if refusal:
        print(refusal)
        return 2
    if not TELEMETRY_FILE.exists() or json.loads(TELEMETRY_FILE.read_text(encoding='utf-8')).get('status') != 'ok':
        print('refused: telemetry is not resolved (run `pilot.py telemetry --i-have-approval` first)')
        return 2
    if 'OZ_CODEX_TIMEOUT' in os.environ:
        print('refused: OZ_CODEX_TIMEOUT is set but not part of the frozen route environment')
        return 2
    import oz_host
    doc = _reconcile_routes()
    record = json.loads(FREEZE_FILE.read_text(encoding='utf-8'))
    run_dir = RUNS / ('live-' + hashlib.sha256(_dump(record).encode()).hexdigest()[:12])
    budget = oz_host.Budget(run_dir / 'budget.sqlite', caps=CAPS, global_cap=GLOBAL_CAP)
    pool = oz_host.SlotPool(run_dir / 'slots', HOST['slots'])
    gate = launch_gate_for(budget)
    semantics = _usage_semantics()
    routes = _routes()
    config = pilot_config('live', routes, semantics)
    q = data.boolq()
    mat = data.materials()
    manifest = {'freeze_sha256': _sha_file(FREEZE_FILE), 'gold_accessed_during_run': False,
                'leakage_problems': leakage_problems(), 'boolq': 'available' if q['available'] else q['reason'],
                'started_at': time.time(), 'cells': []}
    if manifest['leakage_problems']:
        print('refused: leakage or wave overlap before launch: ' + '; '.join(manifest['leakage_problems']))
        return 2
    _write(run_dir / 'manifest.json', manifest)
    try:
        for spec in matrix_spec(q['available']):
            if spec.get('available') is False:
                manifest['cells'].append({'id': spec['id'], 'status': 'unavailable'})
                continue
            backend = spec['backend']
            cfg = BACKENDS[backend]
            registry = load_registry(backend, doc)
            rt = doc['manifests'][backend]['operations']['e']['route']
            order = oz_host.arm_order(SEED, backend, spec['workload'], spec['arms'])
            hosts = {}
            for arm in order:
                hosts[arm] = oz_host.ArmHost(
                    arm=arm, backend=backend, workload=spec['workload'], experiment_dir=run_dir,
                    launcher=oz_host.ChildLauncher(cfg['adapter']), op=spec['op'], op_text=spec.get('op_text'),
                    goal=spec['goal'], model=cfg['model'], effort=cfg['host_effort'],
                    identity=dict(oz_host.identity_for(rt), launch=routes[backend].get('launch')),
                    registry=registry, seed=SEED if arm != 'A' else None,
                    budget=budget, slots=HOST['slots'], max_records=HOST['max_records'], max_wait=HOST['max_wait'],
                    limits=HOST['limits'], allow_experimental=True, slot_pool=pool, route_check=route_check(backend),
                    pilot=config, usage_semantics=semantics, hooks={'launch_gate': gate})
            try:
                for name, learn, arms in spec['waves']:
                    producers = mat['waves'][name] if spec['workload'] == 'materials' else q['waves'][name]
                    for arm in [a for a in order if a in (arms or order)]:
                        host = hosts[arm]
                        subs = {p: f's{name}{arm}{p}'[:64] for p in producers}
                        oz_host.submit_barrier(host, name, producers, subs.get)  # four producers, one barrier
                        report = host.run_wave(name, learn=learn)
                        rows = [r for p, s in subs.items() for r in host.collect(p, s)]
                        _write(run_dir / 'cells' / f'{backend}-{spec["workload"]}-{name}-{arm}.json',
                               {'backend': backend, 'workload': spec['workload'], 'wave': name, 'arm': arm,
                                'report': report, 'rows': rows})
                        manifest['cells'].append({'id': spec['id'], 'wave': name, 'arm': arm,
                                                  'evidence': report['evidence']})
                        _write(run_dir / 'manifest.json', manifest)
            finally:
                for h in hosts.values():
                    h.close()
    finally:
        _write(run_dir / 'budget.json', budget.usage())
        manifest['finished_at'] = time.time()
        _write(run_dir / 'manifest.json', manifest)
        budget.close()
    print('run finished:', _rel(run_dir))
    return 0


def report(args):
    run_dir = Path(args.run_dir) if args.run_dir else max(RUNS.glob('live-*'), key=lambda p: p.stat().st_mtime,
                                                          default=None)
    if run_dir is None:
        print('no run directory')
        return 2
    result = score.write(score.score_run(run_dir), run_dir)
    print(result['verdict'])
    return 0


# ---------------------------------------------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('plan')
    sub.add_parser('registry')
    d = sub.add_parser('dry')
    d.add_argument('--json', action='store_true')
    sub.add_parser('identity')
    sub.add_parser('freeze')
    t = sub.add_parser('telemetry')
    t.add_argument('--i-have-approval', action='store_true')
    r = sub.add_parser('run')
    r.add_argument('--live', action='store_true')
    r.add_argument('--i-have-approval', action='store_true')
    rep = sub.add_parser('report')
    rep.add_argument('run_dir', nargs='?')
    args = p.parse_args(argv)
    if args.command == 'plan':
        print_plan(plan())
        return 0
    if args.command == 'registry':
        doc = build_registry_file()
        print(f"registry.json written: ops {sorted(doc['manifests']['codex']['operations'])}; boolq: {doc['boolq']}; "
              f"placeholders: {doc['placeholders']}")
        return 0
    if args.command == 'dry':
        result = dry(verbose=not args.json)
        if args.json:
            print(_dump(result))
        return 0
    if args.command == 'identity':
        return record_identity()
    if args.command == 'freeze':
        return freeze()
    if args.command == 'telemetry':
        return telemetry(args)
    if args.command == 'run':
        return run_live(args)
    if args.command == 'report':
        return report(args)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
