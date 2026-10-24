"""oz map kill pilot: plan, dry run, freeze, telemetry, live run and report (joint record 3 to 6, amendment 2 A2.3).

    python bench/ozmap/pilot.py plan       the matrix and the frozen budget allocation per backend and bucket
    python bench/ozmap/pilot.py registry   (re)build bench/ozmap/registry.json from the oracle-labeled admission sets
    python bench/ozmap/pilot.py dry        the live driver over the full matrix with FAKE codex and claude executables
                                           replaying recorded usage (zero model calls)
    python bench/ozmap/pilot.py identity   record each adapter's `--identity` (no model call; runs `<cli> --version`)
    python bench/ozmap/pilot.py freeze     fill the identity placeholders, then hash everything into freeze.json
    python bench/ozmap/pilot.py telemetry --i-have-approval --claude-weekly PCT   the two paired Codex telemetry calls
    python bench/ozmap/pilot.py run --live --i-have-approval --claude-weekly PCT  the pilot (guarded)
    python bench/ozmap/pilot.py quota --percent PCT [RUN_DIR]  record a newer Claude weekly usage reading for a run
    python bench/ozmap/pilot.py report [RUN_DIR]              gold scoring and the ordered gates (score.py)

Standard library. Nothing here calls a model except `telemetry` and `run --live`, and both refuse unless freeze.json
verifies against the current files and interpreter, --i-have-approval is given and a Claude weekly usage reading below
99% is recorded for the launch batch.

One driver (council 3 close, N2). `run --live` and `dry` run the same function, drive(): the same ArmHost, Scheduler,
SlotPool, settlement, registry file loaded from disk, launch-time route verification, launch gate, oz_quota
reservation, frozen max_wait and ChildLauncher children. The dry run differs only in its environment: a temporary
directory holding fake `codex` and `claude` executables (fake_cli.py) comes first on PATH, the routes and the registry
are built for that environment (so the route check sees the fake executables' hashes) and the run directory is
temporary. The dry run also runs the paired telemetry through the fake codex. freeze records the hash of the dry run's
deterministic output.

Frozen configuration (DRIVER choices are listed in ASSUMPTIONS and printed by `plan`).
  Codex   codex exec through examples/bootstrap_codex_adapter.json, model gpt-6.1-sol, effort high, in a fresh empty
          temporary working directory outside the repo; any tool, command, file or web event invalidates the call
  Sonnet  claude -p through examples/bootstrap_claude_adapter.json, model claude-sonnet-5-5, effort default, tools off
  Budget  amendment 3 (owner decisions 2026-10-24): global cap 54; Codex 37 = telemetry 1, bootstraps 2, A 12,
          B residuals 8, C residuals 7, reserve 7 (the second telemetry invocation consumes one reserve call, leaving
          six); Sonnet 17 = telemetry 0, bootstrap 1, A 8, B residuals 4 (dedicated, never the reserve), C residuals 2,
          reserve 2. Audits, overflow, additional telemetry, preparation and permitted infrastructure retries consume
          the applicable reserve; every launch reserves first; exhaustion leaves the evidence incomplete.
  Quota   the 55% weekly launch guard is suspended for this build and pilot (owner decision 1, amendment 3 section 1;
          ends when the pilot report is written). The 99% handoff stop binds every launch, telemetry and retries
          included: there is no programmatic source of the Claude plan usage, so every launch batch (`telemetry`,
          `run`) needs an explicit recorded reading (--claude-weekly PCT, later readings with `quota`), and the launch
          gate refuses without a reading of the batch or at 99% or more. Every launch also reserves an oz_quota slot
          (group ozmap-slot<k>, one per physical slot) before it starts and releases it only after its process tree
          is verified gone.
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
import shutil
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
fake_cli = _sibling('fake_cli')

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
HANDOFF_PERCENT = 99.0
QUOTA_GROUP = 'ozmap'
READINGS = 'quota_readings.jsonl'
QUOTA_STOP = ('99% Claude weekly usage: stop every launch and hand off (owner rule); enforced by the launch gate from '
              'an explicit reading recorded per launch batch; the 55% launch guard is suspended by owner decision 1 '
              'and amendment 3 until the pilot report is written')
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
              'model': 'gpt-6.1-sol', 'effort': 'high', 'host_effort': 'high'},
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
LEDGERS = {'codex': REPO / 'bench' / 'codex_kit' / 'results_gpt-6.1-sol_high.jsonl',
           'sonnet': REPO / 'bench' / 'live' / 'data' / 'pilot2_sonnet64.jsonl'}
LEDGERS_32 = {'codex': LEDGERS['codex'], 'sonnet': REPO / 'bench' / 'live' / 'data' / 'live24_1g_D_sonnet32.jsonl'}
# Bootstrap usage is not measured yet: a recorded 64-job call plus the shim's added system text (chars / 4) and the
# rule output (AST bytes / 3) plus a reasoning allowance. Elapsed scales with output tokens.
BOOTSTRAP_REASONING_ALLOWANCE = 2000
CHARS_PER_TOKEN, AST_BYTES_PER_TOKEN = 4.0, 3.0
# Usage semantics per backend (Astra blocker 1: a backend's telemetry never certifies another backend).
CODEX_REQUIRED = ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens')
# The components each CLI reports on every call (a missing one leaves a cell's evidence incomplete). The Claude CLI has
# no reasoning counter (thinking is billed inside output_tokens); Codex reports cache writes only optionally.
USAGE_COMPONENTS = {'codex': CODEX_REQUIRED,
                    'sonnet': ('input_tokens', 'cached_input_tokens', 'cache_creation_input_tokens', 'output_tokens')}
SONNET_SEMANTICS = ('adapter-constructed inclusive input, not telemetry-certified (Sonnet telemetry allocation 0): the '
                    'frozen claude_cli_adapter sums inputTokens + cacheReadInputTokens + cacheCreationInputTokens of '
                    'every modelUsage entry into input_tokens; the Codex telemetry does not certify it')

ASSUMPTIONS = [
    'Materials is ONE workload of four operations (e, b, m, v): one shared bootstrap per backend proposes a rule or '
    '"none" per operation, batches mix operations, and the 32 audits per evaluation wave are drawn over all four '
    'operations together. oz_host.ArmHost was single-operation; it now accepts op={op id: op text} (DRIVER fix).',
    'Each producer submits 16 jobs per operation per wave (64), one fresh record per job.',
    'e uses json_type + max_bytes + rule_provenance/1, not quoted_span: quoted_span accepts only a string value '
    '(oz_accept and oz_registry), so every correct e answer (a JSON array) would fail it. rule_provenance/1 is '
    'authorized for all four materials contract hashes (amendment 1 D1: "the four supplied materials contracts").',
    'Codex model gpt-6.1-sol, effort high (DRIVER, after the Astra sign-off): at medium 8 of 12 recorded 6.1-sol calls '
    'reported zero reasoning tokens, so paired telemetry could not show that output_tokens includes reasoning; at high '
    'all 12 reasoned (30 to 205 tokens). Every Codex arm uses the same effort. Luna is excluded by the owner.',
    'Sonnet effort is "default" (no --effort flag), the configuration of the historical 91.6 tokens / 20 s cell the '
    'record allows as context; the host passes no OZ_EFFORT.',
    'Op texts are MAT_D verbatim, including "c[N]\'s" in e (live11.py rewrote it to "the ref\'s"; not done here).',
    'BoolQ op text and goal are new (data.BOOLQ_OP_TEXT, data.BOOLQ_GOAL); BoolQ runs on Codex only, cold only.',
    'BoolQ is the SuperGLUE distribution of the BoolQ validation split (owner approved; the Google bucket returned '
    '403); its labels are the dataset annotations, used for the 64 admission cases and for scoring only; no admission '
    'row shares a passage with an evaluation row.',
    'Allocation (amendment 3): Codex reserve 7 = second telemetry invocation 1 + 6 for retries and overflow; Sonnet B '
    'has 4 dedicated residual calls (one per producer) and never uses the Sonnet reserve as its nominal allocation; '
    'Sonnet materials A, B and C form one cell with one shared bootstrap.',
    'No 55% weekly launch guard (owner decision 1); the 99% handoff stop and the frozen caps still bind.',
    'The dry run is the live driver with fake codex and claude executables first on PATH (bench/ozmap/fake_cli.py); '
    'their answers are the oracle and dataset answers (a perfect model) and their rules the spec\'s worked E/B/M/V '
    'ASTs, so the projection is an upper bound on coverage and correctness.',
    'Dry-run usage: every replayed call costs a recorded 64-job call of that backend, chosen by the call\'s content '
    '(deterministic), also the smaller residual and audit calls (conservative for B and C); BoolQ calls use the '
    'materials samples too, so BoolQ input tokens are underestimated by roughly the passage text.',
    'Bootstrap usage is an estimate (recorded 64-job call + shim system text + rule bytes + reasoning allowance).',
    'Dry-run makespans are replay projections (recorded 64-job elapsed per call, list-scheduled on 4 slots); the '
    'gates score measured makespan live; summed physical call seconds are reported separately and never replace '
    'makespan (amendment 3 sections 2 and 3).',
    'Telemetry sends one identical prompt twice; Codex inclusive cached accounting is certified only when both calls '
    'report every required component, the prompts hash the same, input_tokens is equal and cached_input_tokens grows. '
    'Sonnet usage semantics are the adapter construction, not telemetry.',
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


def _digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


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
            raise ValueError(f'{backend}: identity flags {eff["flags"]} differ from the sources {flags}; the '
                             'identity record is stale, run `pilot.py identity` again')
        cli = eff['cli_version']
    return static_route(backend, cli)


def static_route(backend, cli=PLACEHOLDER):
    """The route computed from the sources alone (cli_version given)."""
    import oz_route
    cfg = BACKENDS[backend]
    return {'adapter_hash': oz_route.adapter_hash(cfg['adapter']), 'backend': cfg['route_backend'],
            'model': cfg['model'], 'effort': cfg['effort'], 'cli_version': cli,
            'environment_hash': oz_route.environment_hash(cfg['adapter'], static_flags(backend), route_env(backend))}


def _routes(path=None):
    path = Path(path) if path is not None else ROUTES_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def child_env(backend, base=None, extra=None):
    import oz_host
    cfg = BACKENDS[backend]
    return oz_host.child_env(model=cfg['model'], effort=cfg['host_effort'], base=base, extra=extra)


def build_routes(run=subprocess.run, env=None, path=None):
    """The routes document: for each backend the WHOLE oz_route.build result (route, worker_hash, launch snapshot,
    do_route) computed in the child environment the host launches with (env: the base environment, default
    os.environ). Written to path (default routes.json). No model call (the adapter's --identity)."""
    import oz_route
    doc = {}
    for backend, cfg in BACKENDS.items():
        doc[backend] = oz_route.build(cfg['adapter'], model=cfg['model'], effort=cfg['effort'], run=run,
                                      env=child_env(backend, env))
    _write(Path(path) if path is not None else ROUTES_FILE, doc)
    return doc


def route_check(backend, routes=None):
    """The host's launch-time route check: oz_route.verify of the frozen build result in the real launch env."""
    cfg = BACKENDS[backend]
    frozen = (routes if routes is not None else _routes()).get(backend)
    if frozen is None:
        raise SystemExit(f'refused: no frozen route for {backend} (run `pilot.py freeze`)')
    return {'frozen': frozen, 'adapter': str(cfg['adapter']), 'model': cfg['model'], 'effort': cfg['effort']}


def pilot_config(mode, routes, usage_semantics):
    """The frozen host configuration (oz_host.check_pilot): caps, global cap, slots, limits, intake, routes, the
    declared usage semantics and the usage components each backend's CLI must report on every call."""
    import oz_host
    return {'schema': oz_host.PILOT_SCHEMA, 'mode': mode, 'global_cap': GLOBAL_CAP, 'caps': CAPS,
            'slots': HOST['slots'], 'max_records': HOST['max_records'], 'max_wait': HOST['max_wait'],
            'intake': dict(HOST['intake']), 'limits': dict(HOST['limits']), 'usage_semantics': usage_semantics,
            'usage_components': {b: list(c) for b, c in USAGE_COMPONENTS.items()}, 'routes': routes}


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


def operations(backend, boolq_source, rt=None):
    """build_manifest operations for one backend. boolq_source: data.boolq() (or the dry stand-in) or None. rt: the
    route (default: the frozen or identity-filled route of this checkout)."""
    cases = data.admission_cases(oracle)
    rt = dict(rt) if rt is not None else route(backend, _identity(backend))
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


def build_manifests(boolq_source, routes=None):
    """{backend: manifest}; routes: optional {backend: route dict} (default: route() of each backend)."""
    import oz_registry
    checks = check_definitions()
    return {b: oz_registry.build_manifest(operations(b, boolq_source, (routes or {}).get(b)), checks, APPROVED_BY)
            for b in BACKENDS}


def registry_doc(boolq_source, routes=None):
    """The registry-set document (registry.json) for these routes."""
    import oz_registry
    manifests = build_manifests(boolq_source, routes)
    placeholders = sorted(f'{b}: route.cli_version' for b in BACKENDS
                          if manifests[b]['operations']['e']['route']['cli_version'] == PLACEHOLDER)
    q = boolq_source
    return {'schema': 'ozmap.registry-set/1',
            'boolq': 'available' if q and q.get('available') else 'stand-in' if q and q.get('standin') else
            'unavailable',
            'placeholders': placeholders, 'manifests': manifests,
            'manifest_sha256': {b: oz_registry.digest(m) for b, m in manifests.items()}}


def build_registry_file():
    q = data.boolq()
    doc = registry_doc(q if q['available'] else None)
    if not q['available']:
        doc['boolq'] = q['reason']
    _write(REGISTRY_FILE, doc)
    return doc


def registry_problems(path=None):
    """[] when the registry file is exactly what the builder makes for the routes it carries (so a dry registry that
    differs from it only by route is the same registry)."""
    path = Path(path) if path is not None else REGISTRY_FILE
    if not path.exists():
        return [f'{path.name} is missing (run `pilot.py registry`)']
    doc = json.loads(path.read_text(encoding='utf-8'))
    q = data.boolq()
    try:
        routes = {b: doc['manifests'][b]['operations']['e']['route'] for b in BACKENDS}
        want = registry_doc(q if q['available'] else None, routes)
    except (KeyError, TypeError, ValueError) as exc:
        return [f'{path.name} cannot be rebuilt: {type(exc).__name__}: {exc}']
    if not q['available']:
        want['boolq'] = q['reason']
    if {k: v for k, v in doc.items() if k != 'placeholders'} != {k: v for k, v in want.items() if k != 'placeholders'}:
        return [f'{path.name} differs from the builder for its own routes (stale data, contracts or checks; run '
                '`pilot.py registry` or `freeze`)']
    return []


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


def recorded_usage():
    """{backend: {"call": [...], "bootstrap": [...]}} from real 64-job ledgers, plus the bootstrap estimate. A Sonnet
    sample keeps its raw components ("raw"), which the fake claude reports as modelUsage."""
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
                          'raw': {'in_uncached': r['in'] - r['cache_read'] - r['cache_write'],
                                  'cache_read': r['cache_read'], 'cache_write': r['cache_write'], 'out': r['out']},
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
            if 'raw' in c:
                b['raw'] = dict(c['raw'], in_uncached=c['raw']['in_uncached'] + extra_in,
                                out=c['raw']['out'] + extra_out)
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


# ---------------------------------------------------------------------------------- quota and the handoff stop

def _percent(text):
    try:
        value = float(str(text).strip().rstrip('%'))
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 100 else None


def record_reading(run_dir, percent, source, session):
    """Append one explicit Claude weekly usage reading to the run's quota_readings.jsonl (there is no programmatic
    source of the plan usage; the owner reads it and passes it)."""
    value = _percent(percent)
    if value is None:
        raise SystemExit(f'refused: {percent!r} is not a weekly usage percentage 0..100')
    path = Path(run_dir) / READINGS
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps({'percent': value, 'source': source, 'session': session, 'at': time.time()},
                           sort_keys=True) + '\n')
    return value


def readings(run_dir):
    path = Path(run_dir) / READINGS
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def launch_gate_for(budget, run_dir=None, session=None):
    """The launch gate of every pilot launch, telemetry and retries included: the frozen global cap and, with a run
    directory, the 99% handoff stop (council 3 close, N3/B9): a launch needs a reading recorded for this launch batch
    (session), and the newest reading of the run must be below 99%. No 55% weekly guard (owner decision 1)."""
    def gate(view):
        if budget.usage()['total'] >= GLOBAL_CAP:
            return 'global_cap_reached'
        if run_dir is None:
            return None
        found = readings(run_dir)
        if not any(r.get('session') == session for r in found):
            return ('quota_reading_missing: record the Claude weekly usage read just now for this launch batch '
                    '(--claude-weekly PCT); there is no programmatic source')
        latest = found[-1]['percent']
        if latest >= HANDOFF_PERCENT:
            return f'quota_handoff_99: Claude weekly usage {latest:g}% reached {HANDOFF_PERCENT:g}%; stop and hand off'
        return None
    return gate


# -------------------------------------------------------------------- dependency closure (council 3 close, B11)

CLOSURE_PROBE = r'''
import hashlib, json, os, sys
adapter_dir, scripts = sys.argv[1], sys.argv[2:]
sys.path.insert(0, adapter_dir)
import importlib.util
for name in scripts:
    spec = importlib.util.spec_from_file_location(name[:-3] if name.endswith('.py') else name,
                                                  os.path.join(adapter_dir, name))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
modules, unresolved = [], []
for name in sorted(sys.modules):
    if name == '__main__':
        continue  # the probe itself
    m = sys.modules[name]
    path = getattr(m, '__file__', None)
    if path is None:
        spec = getattr(m, '__spec__', None)
        origin = getattr(spec, 'origin', None) if spec is not None else None
        kind = origin if origin in ('built-in', 'frozen') else 'namespace' if spec is not None else 'unknown'
        if kind == 'unknown':
            unresolved.append(name)
        modules.append([name, kind, None, None])
        continue
    try:
        with open(path, 'rb') as f:
            digest = hashlib.sha256(f.read()).hexdigest()
    except OSError:
        unresolved.append(name)
        digest = None
    modules.append([name, 'file', os.path.normcase(os.path.realpath(path)), digest])
with open(sys.executable, 'rb') as f:
    exe = hashlib.sha256(f.read()).hexdigest()
print(json.dumps({'executable': os.path.normcase(os.path.realpath(sys.executable)), 'executable_sha256': exe,
                  'version': sys.version, 'implementation': sys.implementation.name, 'prefix': sys.prefix,
                  'base_prefix': sys.base_prefix, 'modules': modules, 'unresolved': unresolved}))
'''


def dependency_closure(backend, env=None, run=subprocess.run):
    """The executable dependency closure of a backend's adapter as the LAUNCHED interpreter sees it: argv[0] resolved
    on the launch PATH (as oz_route.executables does), run in the launch environment from the adapter directory,
    importing the adapter's Python scripts exactly as `python <script>` would, then every loaded module with its file
    and sha256 (stdlib, site-packages and repo files alike), the interpreter's path, sha256 and version."""
    cfg = BACKENDS[backend]
    argv = json.loads(cfg['adapter'].read_text(encoding='utf-8'))['argv']
    env = dict(os.environ if env is None else env)
    program = shutil.which(argv[0], path=env.get('PATH'))
    if program is None:
        return {'error': f'{argv[0]} is not on the launch PATH', 'unresolved': [argv[0]]}
    scripts = [a for a in argv[1:] if a.endswith('.py')]
    with_real = scripts + [s for s in [f'{cfg["real"]}.py'] if s not in scripts]
    done = run([program, '-c', CLOSURE_PROBE, str(cfg['adapter'].parent), *with_real], cwd=str(cfg['adapter'].parent),
               env=env, capture_output=True, text=True, encoding='utf-8', timeout=120, stdin=subprocess.DEVNULL)
    if done.returncode != 0:
        return {'error': f'the closure probe exited {done.returncode}: {(done.stderr or "")[-300:]}',
                'unresolved': ['<probe>']}
    return json.loads(done.stdout)


def closure_problems(record):
    if not isinstance(record, dict):
        return ['no dependency closure recorded']
    problems = []
    if record.get('error'):
        problems.append(record['error'])
    if record.get('unresolved'):
        problems.append('unresolved modules: ' + ', '.join(record['unresolved'][:10]))
    return problems


def interpreter_record():
    """The interpreter running this driver (it starts every host child: ChildLauncher uses sys.executable)."""
    exe = Path(sys.executable).resolve()
    return {'executable': os.path.normcase(str(exe)), 'sha256': _sha_file(exe), 'version': sys.version,
            'implementation': sys.implementation.name, 'base_prefix': sys.base_prefix}


# ---------------------------------------------------------------------------- telemetry (Astra blocker 1)

REASONING_TOLERANCE = (8, 0.0)  # absolute tokens, fraction of the visible reply; recorded framing residual is 4 or 6


def visible_tokens(reply):
    """o200k token count of the visible reply text, or None when the reply or the tokenizer is unavailable."""
    if not isinstance(reply, str):
        return None
    try:
        import tiktoken
        return len(tiktoken.get_encoding('o200k_base').encode(reply))
    except Exception:  # noqa: BLE001 - no tokenizer means no reasoning evidence, never a guess
        return None


def tokenizer_record():
    """The o200k_base tokenizer the reasoning certification counts with: tiktoken version and the sha256 of every
    cached vocabulary file it loads (tiktoken keeps them in TIKTOKEN_CACHE_DIR or the temp data-gym-cache)."""
    import tempfile
    import tiktoken
    tiktoken.get_encoding('o200k_base')  # loads (from the local cache) before the files are hashed
    cache = Path(os.environ.get('TIKTOKEN_CACHE_DIR') or os.environ.get('DATA_GYM_CACHE_DIR')
                 or Path(tempfile.gettempdir()) / 'data-gym-cache')
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(cache.glob('*')) if p.is_file()}
    return {'tiktoken': getattr(tiktoken, '__version__', 'unknown'), 'encoding': 'o200k_base', 'cache_files': files}


def reasoning_inclusion(usage, visible):
    """Problem text or None. output_tokens includes reasoning when output - reasoning equals the visible reply's
    tokens within REASONING_TOLERANCE; exclusive accounting would make output itself equal the visible tokens. The
    recorded 26 Codex calls with reasoning (bench/codex_kit) give a median deviation of 0.7% for the inclusive reading
    and 10.5% for the exclusive one (docs/design/ozmap-2026-10-24/codex-reasoning-evidence.md)."""
    if visible is None:
        return 'visible reply tokens unavailable: reasoning inclusion not shown'
    absolute, fraction = REASONING_TOLERANCE
    tol = max(absolute, fraction * visible)
    if abs(usage['output_tokens'] - usage['reasoning_output_tokens'] - visible) > tol:
        return (f"output_tokens - reasoning_output_tokens = "
                f"{usage['output_tokens'] - usage['reasoning_output_tokens']} does not match the visible reply "
                f"({visible} tokens, tolerance {tol:g}): reasoning inclusion not shown")
    if abs(usage['output_tokens'] - visible) <= tol:  # whatever the reasoning size (Astra sign-off 2)
        return 'output_tokens also matches the visible reply alone: inclusion and exclusion not distinguishable'
    return None


def certify_codex(results, worker_hash):
    """(status, evidence) of the paired Codex telemetry. ok only with backend-specific evidence of inclusive cached
    accounting: two calls on the frozen route (worker hash) with the same system and prompt hashes, every required
    component present as a count (input, cached, output, reasoning), cached <= input and reasoning <= output in each,
    input_tokens equal and cached_input_tokens grown on the repeat (a cache hit that leaves the input total unchanged
    is inclusion; exclusive accounting would drop the input total by the cached growth). Inequalities alone never
    certify; an empty or partial usage never certifies; leakage never certifies."""
    problems = []
    calls = []
    for r in results:
        if r.get('refused'):
            problems.append(f"{r['key']}: refused ({r['refused']})")
            continue
        if r.get('worker_hash') != worker_hash:
            problems.append(f"{r['key']}: not on the frozen codex route")
        if r.get('leakage'):
            problems.append(f"{r['key']}: tool use in the event stream")
        if len(r.get('calls') or []) != 1:
            problems.append(f"{r['key']}: {len(r.get('calls') or [])} core calls (one expected)")
            continue
        calls.append(r['calls'][0])
    for c in calls:
        u = c.get('usage')
        if not isinstance(u, dict) or any(type(u.get(k)) is not int or u[k] < 0 for k in CODEX_REQUIRED):
            problems.append(f"call {c.get('call_id')}: a required usage component is missing or not a count "
                            f"({sorted(u) if isinstance(u, dict) else u})")
            continue
        if u['cached_input_tokens'] > u['input_tokens'] or u['reasoning_output_tokens'] > u['output_tokens']:
            problems.append(f"call {c.get('call_id')}: a component exceeds its total")
            continue
        issue = reasoning_inclusion(u, c.get('visible_tokens'))
        if issue:
            problems.append(f"call {c.get('call_id')}: {issue}")
    evidence = {'calls': [{k: c.get(k) for k in ('call_id', 'usage', 'system_sha256', 'prompt_sha256',
                                                  'usage_source', 'visible_tokens')} for c in calls]}
    if len(calls) == 2 and not problems:
        a, b = calls[0], calls[1]
        if not a.get('prompt_sha256') or (a.get('system_sha256'), a.get('prompt_sha256')) != \
                (b.get('system_sha256'), b.get('prompt_sha256')):
            problems.append('the two telemetry prompts are not identical (system and prompt hashes)')
        ua, ub = a['usage'], b['usage']
        if ua['input_tokens'] != ub['input_tokens']:
            problems.append(f"input_tokens changed on the identical repeat ({ua['input_tokens']} -> "
                            f"{ub['input_tokens']}): not inclusive or not identical")
        if ub['cached_input_tokens'] <= ua['cached_input_tokens']:
            problems.append('cached_input_tokens did not grow on the identical repeat: inclusion not shown')
        evidence['inclusion'] = {'input_tokens': [ua['input_tokens'], ub['input_tokens']],
                                 'cached_input_tokens': [ua['cached_input_tokens'], ub['cached_input_tokens']]}
    elif len(calls) != 2 and not problems:
        problems.append(f'{len(calls)} telemetry calls with usage (two expected)')
    evidence['problems'] = problems
    return ('ok' if not problems else 'unverified'), evidence


def usage_semantics(routes, doc, freeze_sha256=None):
    """{backend: declared usage semantics}. Codex is certified only by its own telemetry on its own frozen route (and,
    live, the same freeze); Sonnet is the adapter construction. Nothing certifies across backends."""
    codex = 'unverified'
    ok = (isinstance(doc, dict) and doc.get('status') == 'ok' and doc.get('backend') == 'codex'
          and doc.get('worker_hash') == (routes.get('codex') or {}).get('worker_hash')
          and (freeze_sha256 is None or doc.get('freeze_sha256') == freeze_sha256))
    if ok:
        codex = (f"inclusive cached accounting certified by paired identical-prompt telemetry {doc.get('run_dir')} on "
                 f"worker {doc['worker_hash'][:12]}; reasoning inclusion in output_tokens certified on the same calls "
                 '(output - reasoning equals the visible reply tokens); tokens = input_tokens + output_tokens')
    return {'codex': codex, 'sonnet': SONNET_SEMANTICS}


def _guarded_call(ctx, *, key, buckets, request, evidence, backend='codex', arm='T', kind='telemetry'):
    """One physical call outside an arm host (telemetry), through the same discipline as ArmHost._launch: launch gate
    (cap and 99% stop), route verification, experiment slot, oz_quota slot, budget reservation, ChildLauncher with the
    verified process tree, the core ledger read after the child whatever happened, every adapter envelope harvested."""
    import oz_host
    import oz_route
    cfg = BACKENDS[backend]
    check = route_check(backend, ctx['routes'])
    out = {'key': key, 'worker_hash': check['frozen']['worker_hash'], 'calls': [], 'envelopes': [], 'leakage': []}
    refusal = ctx['gate'](None)
    if refusal:
        return dict(out, refused=refusal)
    env = child_env(backend, ctx['env'], {'OZ_ENVELOPE_PATH': str(Path(evidence) / 'adapter-envelope.json')})
    try:
        oz_route.verify(check['frozen'], {k: v for k, v in check.items() if k != 'frozen'}, env=env)
    except Exception as exc:  # noqa: BLE001 - any failure blocks the launch
        return dict(out, refused='route_unverified: ' + str(exc)[:300])
    pool, quota, budget = ctx['pool'], ctx['quota'], ctx['budget']
    lock = pool.acquire()
    group = f'{QUOTA_GROUP}-slot{lock.slot}'
    ws = Path(ctx['run_dir']) / 'telemetry' / 'ws'
    got = quota.acquire(group, run_dir=ws / 'do' / key, receipt=key)
    if got.get('status') != 'acquired':
        pool.release(lock)
        return dict(out, refused=f"quota_held: {got.get('reason')}")
    bucket = budget.reserve(key, backend=backend, buckets=buckets, arm=arm, kind=kind)
    if bucket is None:
        quota.release(group, got['token'])
        pool.release(lock)
        return dict(out, refused='budget_exhausted')
    launcher = oz_host.ChildLauncher(cfg['adapter'])
    spec = {'workspace': str(ws), 'request': request, 'max_calls': 1, 'route': oz_host.identity_for(
        check['frozen']['route'])['do_route'], 'experimental_sizes': [],
        'child_timeout': oz_host.child_timeout(HOST['limits'])}
    verified = None
    try:
        execution, meta = launcher(spec, env, Path(evidence))
        verified = (meta.get('tree') or {}).get('verified')
    finally:
        if verified is not False:
            quota.release(group, got['token'])
            pool.release(lock)
        else:
            ctx.setdefault('retained', []).append({'key': key, 'lock': lock, 'quota': (group, got['token'])})
    run = ws / 'do' / key
    core = oz_host._ledger_calls(run)
    envelopes = oz_host._run_envelopes(run, [('attempt:' + key, Path(evidence) / 'adapter-envelope.json')])
    by_receipt = {}
    for receipt, env_ in envelopes.items():
        ev = oz_host.envelope_evidence(env_['raw'])
        by_receipt[receipt] = ev
        out['envelopes'].append({'receipt': receipt, 'exit_code': env_['exit_code'], 'kind': ev['kind'],
                                 'usage': ev['usage'], 'leakage': ev['leakage'],
                                 'sha256': hashlib.sha256(env_['raw']).hexdigest()})
        if ev['leakage']:
            out['leakage'].append({'receipt': receipt, 'leakage': ev['leakage']})
    for c in core:
        call = dict(c, usage_source='core_ledger')
        ev = by_receipt.get(c.get('receipt'))
        call['visible_tokens'] = visible_tokens(ev['reply']) if ev is not None else None
        if call.get('usage') is None and ev is not None and ev['usage'] is not None:
            call.update(usage=ev['usage'], usage_source='adapter_envelope:' + c['receipt'])  # failed call: kept
        out['calls'].append(call)
    out.update(bucket=bucket, meta=meta, status=(execution or {}).get('status'), tree_verified=verified,
               unresolved=[c['call_id'] for c in out['calls'] if c.get('usage') is None])
    return out


def run_telemetry(ctx):
    """The two paired Codex telemetry calls: ONE identical request (the first telemetry job) sent twice under two
    request ids, each through _guarded_call. Writes and returns the telemetry document."""
    from oz_workspace import initialize
    import oz_host
    ws = Path(ctx['run_dir']) / 'telemetry' / 'ws'
    if not (ws / 'oz.json').exists():
        initialize(ws)
    job = data.materials()['telemetry'][0]
    cfg = BACKENDS['codex']
    results = []
    for key, buckets in TELEMETRY_KEYS:
        request = {'v': 'oz.do/1', 'request_id': key, 'goal': data.MAT_GOAL, 'ops': {job['op']: data.MAT_D[job['op']]},
                   'refs': {'r0': oracle.resolve(job['text'])}, 'jobs': [['j0', job['op'], 'r0']],
                   'profile': oz_host.PROFILE, 'allow_experimental': True, 'max_inline_bytes': oz_host.MAX_INLINE,
                   'max_attempts': 1, 'max_jobs_per_call': 1, 'max_input_tokens': 1000000, 'model': cfg['model']}
        results.append(_guarded_call(ctx, key=key, buckets=buckets, request=request,
                                     evidence=Path(ctx['run_dir']) / 'telemetry' / key))
    worker = route_check('codex', ctx['routes'])['frozen']['worker_hash']
    status, evidence = certify_codex(results, worker)
    doc = {'status': status, 'backend': 'codex', 'worker_hash': worker, 'freeze_sha256': ctx.get('freeze_sha256'),
           'run_dir': str(ctx['run_dir']) if ctx['mode'] != 'live' else _rel(ctx['run_dir']), 'evidence': evidence,
           'results': results, 'leakage': [x for r in results for x in r['leakage']]}
    _write(ctx['telemetry_file'], doc)
    return doc


# -------------------------------------------------------------------------------------- the one driver (N2)

def preflight(ctx):
    """Problems that refuse a run before any launch: every backend's registry route is its frozen route, oz_route.verify
    of that route passes in the launch environment, the launched interpreter's dependency closure equals the frozen
    one and has no unresolved entry, the frozen route has no unversioned dependency, and the static leakage lint."""
    import oz_route
    problems = []
    doc = ctx['registry']
    for backend, cfg in BACKENDS.items():
        check = route_check(backend, ctx['routes'])
        if doc['manifests'][backend]['operations']['e']['route'] != check['frozen']['route']:
            problems.append(f'the registry route of {backend} is not the frozen route (D7)')
        env = child_env(backend, ctx['env'])
        try:
            oz_route.verify(check['frozen'], {k: v for k, v in check.items() if k != 'frozen'}, env=env)
        except Exception as exc:  # noqa: BLE001
            problems.append(f'{backend}: {exc}')
        loose = [e for e in (check['frozen'].get('launch') or {}).get('externals') or []
                 if e[2] in ('unversioned', None) or e[1] == 'declared-external']
        if loose:
            problems.append(f'{backend}: unversioned dependencies in the frozen route: {loose}')
        now = dependency_closure(backend, env)
        problems += [f'{backend}: {p}' for p in closure_problems(now)]
        frozen = (ctx.get('closure') or {}).get(backend)
        if frozen is None:
            problems.append(f'{backend}: no frozen dependency closure')
        elif now != frozen:
            problems.append(f'{backend}: the launched interpreter\'s dependency closure differs from the freeze')
    problems += leakage_problems()
    return problems


def drive(ctx):
    """The pilot driver shared by `run --live` and `dry` (council 3 close, N2): the matrix through ArmHost with
    ChildLauncher children, the registry loaded from its file, the frozen pilot configuration (max_wait 1 s), the
    launch-time route check, the launch gate and oz_quota. Writes cells/, budget.json and manifest.json in the run
    directory and returns {"cells": [...], "manifest"}."""
    import oz_host
    run_dir = Path(ctx['run_dir'])
    doc = ctx['registry']
    budget, pool, routes = ctx['budget'], ctx['pool'], ctx['routes']
    semantics = ctx['semantics']
    config = pilot_config(ctx['mode'], routes, semantics)
    q = data.boolq()
    mat = data.materials()
    manifest = {'mode': ctx['mode'], 'freeze_sha256': ctx.get('freeze_sha256'), 'session': ctx['session'],
                'gold_accessed_during_run': None, 'leakage_problems': leakage_problems(),
                'boolq': 'available' if q['available'] else q['reason'], 'started_at': time.time(), 'cells': []}
    if manifest['leakage_problems']:
        raise SystemExit('refused: leakage or wave overlap before launch: ' + '; '.join(manifest['leakage_problems']))
    _write(run_dir / 'manifest.json', manifest)
    cells, leaks = [], list((ctx.get('telemetry') or {}).get('leakage') or [])
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
            try:
                for arm in order:
                    hosts[arm] = oz_host.ArmHost(
                        arm=arm, backend=backend, workload=spec['workload'], experiment_dir=run_dir,
                        launcher=oz_host.ChildLauncher(cfg['adapter']), op=spec['op'], op_text=spec.get('op_text'),
                        goal=spec['goal'], model=cfg['model'], effort=cfg['host_effort'],
                        identity=dict(oz_host.identity_for(rt), launch=routes[backend].get('launch')),
                        registry=registry, seed=SEED if arm != 'A' else None,
                        budget=budget, slots=HOST['slots'], max_records=HOST['max_records'],
                        max_wait=HOST['max_wait'], limits=HOST['limits'], allow_experimental=True, slot_pool=pool,
                        route_check=route_check(backend, routes), pilot=config,
                        usage_semantics=oz_host.semantics_for(config, backend), hooks={'launch_gate': ctx['gate']},
                        base_env=ctx['env'], quota=ctx['quota'], quota_group=QUOTA_GROUP)
                for name, learn, arms in spec['waves']:
                    producers = mat['waves'][name] if spec['workload'] == 'materials' else q['waves'][name]
                    for arm in [a for a in order if a in (arms or order)]:
                        host = hosts[arm]
                        subs = {p: f's{name}{arm}{p}'[:64] for p in producers}
                        oz_host.submit_barrier(host, name, producers, subs.get)  # four producers, one barrier
                        report = host.run_wave(name, learn=learn)
                        rows = [r for p, s in subs.items() for r in host.collect(p, s)]
                        texts = {r['delivery']: r['text_sha256'] for r in host.ledger.plan(name)}
                        attempts = [{'attempt_id': a['attempt_id'], 'round': a['round'], 'state': a['state'],
                                     'outcome': a['outcome'], 'call_ids': a['call_ids'], 'records': a['records'],
                                     'elapsed': a['elapsed'], 'text_sha256': [texts.get(x) for x in a['records']]}
                                    for a in host.ledger.attempts(name)]
                        cell = {'id': spec['id'], 'backend': backend, 'workload': spec['workload'], 'wave': name,
                                'arm': arm, 'report': report, 'rows': rows, 'attempts': attempts}
                        _write(run_dir / 'cells' / f'{backend}-{spec["workload"]}-{name}-{arm}.json', cell)
                        cells.append(cell)
                        manifest['cells'].append({'id': spec['id'], 'wave': name, 'arm': arm,
                                                  'evidence': report['evidence']})
                        _write(run_dir / 'manifest.json', manifest)
            finally:
                for h in hosts.values():
                    leaks += h.leakage()
                    h.close()
    finally:
        _write(run_dir / 'budget.json', budget.usage())
        # Derived, never a constant (N1): gold stayed out of reach only when no envelope of the run shows tool use.
        manifest['tool_use_leakage'] = leaks
        manifest['gold_accessed_during_run'] = bool(leaks)
        manifest['finished_at'] = time.time()
        _write(run_dir / 'manifest.json', manifest)
    return {'cells': cells, 'manifest': manifest}


def _context(mode, run_dir, *, env, routes, registry, closure, quota, session, telemetry_file, freeze_sha256=None):
    import oz_host
    run_dir = Path(run_dir)
    budget = oz_host.Budget(run_dir / 'budget.sqlite', caps=CAPS, global_cap=GLOBAL_CAP)
    pool = oz_host.SlotPool(run_dir / 'slots', HOST['slots'])
    return {'mode': mode, 'run_dir': run_dir, 'env': env, 'routes': routes, 'registry': registry, 'closure': closure,
            'quota': quota, 'session': session, 'telemetry_file': Path(telemetry_file), 'freeze_sha256': freeze_sha256,
            'budget': budget, 'pool': pool, 'gate': launch_gate_for(budget, run_dir, session)}


def _close(ctx):
    for thing in (ctx.get('budget'), ctx.get('quota')):
        try:
            thing.close()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------------------------------------------ dry

def fake_answers(boolq_source):
    """{sha256(resolved text): answer} for every evaluation and telemetry job: the fake model's answers (gold)."""
    table = {}
    mat = data.materials()
    for wave in data.WAVES:
        for jobs in mat['waves'][wave].values():
            for j in jobs:
                table[oracle.resolve(j['text'])] = oracle.gold(j['op'], j['text'])
    for j in mat['telemetry']:
        table[oracle.resolve(j['text'])] = oracle.gold(j['op'], j['text'])
    for jobs in boolq_source['waves']['cold'].values():
        for j in jobs:
            table[oracle.resolve(j['text'])] = oracle.gold(data.BOOLQ_OP, '', boolq_source['labels'][j['dataset_id']])
    return {hashlib.sha256(t.encode('utf-8')).hexdigest(): v for t, v in table.items()}


def dry(experiment_dir=None, verbose=True, leak=None):
    """The dry run: drive() and the paired telemetry with fake CLI executables first on PATH (zero model calls)."""
    import tempfile
    import bootstrap_shim
    import oz_host
    temp = None
    if experiment_dir is None:
        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        experiment_dir = temp.name
    ctx = None
    try:
        root = Path(experiment_dir)
        run_dir = root / 'run'
        q = data.boolq()
        source = q if q['available'] else data.boolq_standin()
        usage = recorded_usage()
        fake = root / 'fake-cli'
        fake_cli.build(fake, answers=fake_answers(source), rules=dict(zip(data.OPS, bootstrap_shim.HIDDEN_ASTS)),
                       samples={'codex': usage['codex'], 'claude': usage['sonnet']}, repo=REPO, leak=leak)
        env = fake_cli.env_with(fake)
        for name in ('codex', 'claude'):  # never a real CLI in a dry run
            found = shutil.which(name, path=env['PATH'])
            if found is None or Path(found).resolve().parent != fake.resolve():
                raise SystemExit(f'refused: {name} does not resolve to the fake CLI directory ({found})')
        routes = build_routes(env=env, path=root / 'routes.json')
        stale = registry_problems()
        reg_path = root / 'registry.json'
        _write(reg_path, registry_doc(source, {b: routes[b]['route'] for b in BACKENDS}))
        registry = json.loads(reg_path.read_text(encoding='utf-8'))  # loaded from its file, as live loads its own
        closure = {b: dependency_closure(b, child_env(b, env)) for b in BACKENDS}
        _write(root / 'closure.json', closure)
        session = 'dry-' + os.urandom(6).hex()
        record_reading(run_dir, 0.0, 'dry run: fake CLIs, no plan usage', session)
        ctx = _context('dry', run_dir, env=env, routes=routes, registry=registry, closure=closure,
                       quota=oz_host.QuotaStore(root / 'quota.sqlite'), session=session,
                       telemetry_file=root / 'telemetry.json')
        t0 = time.time()
        problems = preflight(ctx)
        if problems:
            raise SystemExit('dry run refused: ' + '; '.join(problems))
        ctx['telemetry'] = run_telemetry(ctx)
        ctx['semantics'] = usage_semantics(routes, ctx['telemetry'])
        out = drive(ctx)
        result = summarize_dry(out, ctx, usage, source, fake, stale)
        result['wall_seconds'] = round(time.time() - t0, 1)
        if verbose:
            print_dry(result)
        return result
    finally:
        if ctx is not None:
            _close(ctx)
        if temp is not None:
            temp.cleanup()


def _projection(attempts, elapsed_by_key, slots):
    """Projected seconds of an arm wave: each round's recorded call elapsed list-scheduled over the slots."""
    rounds = {}
    for a in attempts:
        if a['state'] == 'refused' or not a['call_ids']:
            continue
        key = json.dumps(sorted(a['text_sha256']))
        rounds.setdefault(a['round'].split('-')[0], []).append(elapsed_by_key.get(key, 0.0))
    total = 0.0
    for name in sorted(rounds, key=lambda r: ('bootstrap', 'r1', 'r2', 'r3').index(r) if r in
                       ('bootstrap', 'r1', 'r2', 'r3') else 9):
        finish = [0.0] * slots
        for seconds in rounds[name]:
            k = finish.index(min(finish))
            finish[k] += seconds
        total += max(finish)
    return total


def prompt_leakage(calls):
    """B12: no complete prompt the fake CLIs received (every bootstrap and ordinary prompt, as assembled by oz_do and
    the shim) holds a worked AST, a materials admission text or a BoolQ admission passage."""
    import bootstrap_shim
    mat = data.materials()
    admission = {oracle.resolve(t) for rows in mat['admission_texts'].values() for _, t, _, _ in rows}
    q = data.boolq()
    passages = set()
    if q['available']:
        passages = {t.split('\nquestion: ')[0] for _, t, _, _ in q['admission']}
    problems = []
    for c in calls:
        text = c.get('text') or ''
        kind = 'bootstrap' if c.get('bootstrap') else 'ordinary'
        if any(a in text for a in bootstrap_shim.HIDDEN_ASTS):
            problems.append(f'a worked AST is in a {kind} prompt')
        if any(t in text for t in admission):
            problems.append(f'a materials admission text is in a {kind} prompt')
        if any(p in text for p in passages):
            problems.append(f'a BoolQ admission passage is in a {kind} prompt')
    return sorted(set(problems))


def summarize_dry(out, ctx, usage, source, fake, stale):
    calls = fake_cli.calls(fake)
    elapsed = {json.dumps(c['keys']): float(c.get('elapsed_seconds') or 0.0) for c in calls}
    boots = {}
    for cell in out['cells']:
        for a in cell['attempts']:
            if a['round'].startswith('bootstrap') and a['call_ids']:
                boots[(cell['backend'], cell['workload'])] = elapsed.get(json.dumps(sorted(a['text_sha256'])), 0.0)
    rows, summary_cells, by_backend = [], {}, {}
    for cell in out['cells']:
        r = cell['report']
        tok = r['tokens']['charged']
        jobs = r['jobs']
        projected = _projection(cell['attempts'], elapsed, HOST['slots'])
        if (r['bootstrap'] or {}).get('imported'):
            projected += boots.get((cell['backend'], cell['workload']), 0.0)
        call_s = sum(elapsed.get(json.dumps(sorted(a['text_sha256'])), 0.0) for a in cell['attempts']
                     if a['state'] != 'refused' and a['call_ids'])
        row = {'cell': cell['id'], 'backend': cell['backend'], 'workload': cell['workload'], 'wave': cell['wave'],
               'arm': cell['arm'], 'jobs': jobs, 'accepted': r['accepted_by_checks'], 'unresolved': r['unresolved'],
               'rule_hits': r['rule_hits'], 'coverage': r['coverage'], 'physical_calls': r['calls']['physical'],
               'imported_calls': r['calls']['imported'], 'charged_calls': r['calls']['charged'],
               'refused': r['calls']['refused'], 'tokens': tok['tokens'], 'input_tokens': tok['input_tokens'],
               'output_tokens': tok['output_tokens'], 'tokens_per_job': round(tok['tokens'] / jobs, 1) if jobs else None,
               'makespan_s': round(projected, 3), 'replayed_call_seconds': round(call_s, 3),
               'audits_selected': r['audits']['selected'], 'evidence': r['evidence'], 'incomplete': r['incomplete'],
               'efficiency_valid': r['efficiency_valid'], 'efficiency_invalid': r['efficiency_invalid']}
        rows.append(row)
        by_backend[cell['backend']] = by_backend.get(cell['backend'], 0) + r['calls']['physical']
        counts = {'correct': r['accepted_by_checks'], 'incorrect': 0, 'unresolved': jobs - r['accepted_by_checks']}
        summary_cells[f"{cell['backend']}/{cell['workload']}/{cell['wave']}/{cell['arm']}"] = score.summarize(
            jobs, counts, rule_errors=0, fallback_errors=0, rule_hits=r['rule_hits'], report=r,
            makespan=projected, summed_call_seconds=call_s)
    tele = ctx['telemetry']
    tele_calls = sum(len(x['calls']) for x in tele['results'])
    by_backend['codex'] = by_backend.get('codex', 0) + tele_calls
    host_calls = sum(r['physical_calls'] for r in rows)
    total = host_calls + tele_calls
    boot_status = {}
    for cell in out['cells']:
        b = cell['report']['bootstrap']
        if b:
            boot_status[f"{cell['backend']}/{cell['workload']}"] = {'status': b['status'], 'gold_errors': 0,
                                                                    'disagreements': 0}
    budget = ctx['budget'].usage()
    prompt_problems = prompt_leakage(calls)
    leak = out['manifest']['tool_use_leakage']
    projected = {'cells': summary_cells, 'boolq_available': bool(source.get('available')),
                 'validity': {'leakage': leakage_problems() + prompt_problems +
                              (['tool use in the event stream'] if leak else []),
                              'bootstrap': boot_status, 'budget': dict(budget, over=score.budget_over(budget))}}
    gates = score.evaluate(projected)
    incomplete = [f"{r['cell']} {r['wave']} {r['arm']}: {', '.join(r['incomplete'])}" for r in rows
                  if r['evidence'] != 'complete']
    reconciliation = {'physical_calls': host_calls, 'telemetry_calls': tele_calls,
                      'imported_calls': sum(r['imported_calls'] for r in rows),
                      'charged_calls': sum(r['charged_calls'] for r in rows), 'fake_cli_calls': len(calls),
                      'ok': total == len(calls) == budget['total']
                      and all(r['charged_calls'] == r['physical_calls'] + r['imported_calls'] for r in rows)}
    isolation = {'codex_calls': sum(1 for c in calls if c['cli'] == 'codex'),
                 'codex_isolated': sum(1 for c in calls if c['cli'] == 'codex' and c.get('isolated')),
                 'claude_calls': sum(1 for c in calls if c['cli'] == 'claude'),
                 'claude_tools_disabled': sum(1 for c in calls if c['cli'] == 'claude' and c.get('tools_disabled')),
                 'tool_use_leakage': leak, 'gold_accessed_during_run': out['manifest']['gold_accessed_during_run']}
    result = {'rows': rows, 'external_calls': total - len(calls), 'physical_calls_by_backend': by_backend,
              'physical_calls_total': total, 'budget': budget, 'reconciliation': reconciliation,
              'dry_run_fits': all(r['refused'] == 0 for r in rows) and total <= GLOBAL_CAP,
              'within_global_cap': total <= GLOBAL_CAP, 'sources': dry_sources(usage), 'assumptions': ASSUMPTIONS,
              'evidence': 'complete' if not incomplete else 'incomplete', 'incomplete_cells': incomplete,
              'boolq': 'real BoolQ' if source.get('available') else 'synthetic stand-ins (real BoolQ file absent)',
              'usage_samples': {b: [s['source'] for s in usage[b]['call']] for b in BACKENDS},
              'bootstrap_estimate': usage['_estimate'], 'projected_gates': gates,
              'elapsed_sensitivity': elapsed_sensitivity(), 'telemetry': {'status': tele['status'],
                                                                          'evidence': tele['evidence']},
              'usage_semantics': ctx['semantics'], 'isolation': isolation, 'prompt_leakage': prompt_problems,
              'registry_file_problems': stale, 'fake_misses': sum(c.get('misses') or 0 for c in calls),
              'driver': 'pilot.drive (the live driver) with fake codex and claude executables'}
    result['output_sha256'] = _digest(deterministic(result))
    return result


def deterministic(result):
    """The part of a dry result that must not change between runs on the same checkout (freeze records its hash):
    every count, token total, projection, evidence verdict and gate; no wall clock, path or session."""
    rows = [{k: v for k, v in r.items()} for r in result['rows']]
    return {'rows': rows, 'budget_used': result['budget']['used'], 'budget_total': result['budget']['total'],
            'physical_calls_by_backend': result['physical_calls_by_backend'],
            'reconciliation': {k: v for k, v in result['reconciliation'].items()},
            'gates': [{'gate': g['gate'], 'pass': g['pass']} for g in result['projected_gates']['gates']],
            'verdict': result['projected_gates']['verdict'], 'telemetry': result['telemetry']['status'],
            'isolation': {k: v for k, v in result['isolation'].items()}, 'prompt_leakage': result['prompt_leakage'],
            'external_calls': result['external_calls'], 'fake_misses': result['fake_misses']}


def dry_sources(usage):
    """The dry run's source records (amendment 3 section 4): every recorded usage sample, the bootstrap estimate and
    the fact that BoolQ calls replay materials samples."""
    return {'ledgers': {b: {'file': _rel(LEDGERS[b]), 'sha256': _sha_file(LEDGERS[b])} for b in BACKENDS},
            'samples': {b: [s['source'] for s in usage[b]['call']] for b in BACKENDS},
            'bootstrap': {'estimated': True, **usage['_estimate']},
            'boolq_usage': 'materials usage samples (BoolQ input tokens underestimated by about the passage text)'}


def print_dry(r):
    print(f"driver: {r['driver']}")
    print(f"external calls {r['external_calls']}; physical calls {r['physical_calls_total']} "
          f"(by backend {r['physical_calls_by_backend']}, incl. 2 telemetry); within global cap {GLOBAL_CAP}: "
          f"{r['within_global_cap']}; every launch fit: {r['dry_run_fits']}; reconciliation ok: "
          f"{r['reconciliation']['ok']} (fake CLI calls {r['reconciliation']['fake_cli_calls']})")
    print(f"BoolQ: {r['boolq']}; telemetry: {r['telemetry']['status']}; isolation: {json.dumps(r['isolation'])}")
    print(f"prompt leakage: {r['prompt_leakage'] or 'none'}; registry.json: {r['registry_file_problems'] or 'ok'}; "
          f"fake answer misses: {r['fake_misses']}")
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
    print('dry output sha256:', r['output_sha256'], f"(wall {r.get('wall_seconds')} s)")


# -------------------------------------------------------------------------------------------------- leakage

def leakage_problems():
    """Admission texts disjoint from evaluation and telemetry texts (resolved); the cold and warm evaluation waves
    disjoint (council 3, B12); BoolQ admission separated from evaluation by dataset id, text and passage; no worked AST
    or admission text in any registry contract shown to the model, nor in the assembled bootstrap system text of any
    workload (the shim's text around an empty original system; the complete prompts are scanned by the dry run)."""
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
    q = data.boolq()
    passages = set()
    if q['available']:
        jobs = [j for js in q['waves']['cold'].values() for j in js]
        eval_ids = {j['dataset_id'].rsplit('-', 1)[-1] for j in jobs}
        eval_texts = {j['text'] for j in jobs}
        eval_passages = {j['text'].split('\nquestion: ')[0] for j in jobs}
        adm_texts = {t for _, t, _, _ in q['admission']}
        passages = {t.split('\nquestion: ')[0] for t in adm_texts}
        if eval_texts & adm_texts:
            problems.append(f'{len(eval_texts & adm_texts)} BoolQ admission texts are evaluation texts')
        if eval_passages & passages:
            problems.append(f'{len(eval_passages & passages)} BoolQ admission passages are evaluation passages')
        if len(eval_ids) != len(jobs) or len(adm_texts) != len(q['admission']):
            problems.append('BoolQ evaluation ids or admission texts repeat')
    shown = json.dumps(contracts(), ensure_ascii=False)
    if any(a in shown for a in bootstrap_shim.HIDDEN_ASTS):
        problems.append('a worked AST is in a contract')
    if any(t in shown for t in admission):
        problems.append('an admission text is in a contract')
    for ops in (list(data.OPS), [data.BOOLQ_OP]):
        config = {'schema': 'oz.bootstrap.config/2', 'ops': ops, 'contracts': {o: contracts()[o] for o in ops},
                  'eligibility': {o: o in data.OPS for o in ops}}
        system = bootstrap_shim.system_text('', config)
        try:
            bootstrap_shim.check_hidden(system, strings=False)
        except ValueError as exc:
            problems.append(f'the assembled bootstrap system text: {exc}')
        if any(t in system for t in admission) or any(p in system for p in passages):
            problems.append('an admission text or passage is in the assembled bootstrap system text')
    return problems


# ---------------------------------------------------------------------------------------------------- freeze

FROZEN_CORE = ('oz.py', 'oz_accept.py', 'oz_batch.py', 'oz_cli.py', 'oz_do.py', 'oz_fault.py', 'oz_memo.py',
               'oz_reply.py', 'oz_runner.py', 'oz_runtime.py', 'oz_worker.py', 'oz_workspace.py')
FREEZE_FILES = (
    [f'bench/ozmap/{n}' for n in ('data.py', 'oracle.py', 'score.py', 'pilot.py', 'fake_cli.py', 'registry.json',
                                  'identity.json')]
    + ['bench/ozmap/routes.json']
    + ['tests/test_ozmap_pilot.py', 'tests/test_ozmap_close.py', 'oz_host.py', 'oz_registry.py', 'oz_rule.py',
       'oz_rulephase.py', 'oz_spool.py', 'oz_route.py', 'oz_map.py', 'oz_quota.py', *FROZEN_CORE,
       'examples/bootstrap_shim.py', 'examples/codex_cli_adapter.py', 'examples/claude_map_adapter.py',
       'examples/claude_cli_adapter.py', 'examples/bootstrap_codex_adapter.json',
       'examples/bootstrap_claude_adapter.json', 'bench/live/live2.py',
       'docs/design/ozmap-2026-10-24/bootstrap-spec-excerpt.txt',
       'docs/design/brainstorm-2026-10-24/05-joint-record.md',
       'docs/design/ozmap-2026-10-24/amendment-2-and-step6-architecture.md',
       'docs/design/ozmap-2026-10-24/oz-rule-1-amendment-1.md', 'docs/design/ozmap-2026-10-24/oz-rule-1-spec.md',
       'docs/design/ozmap-2026-10-24/council2-astra.md', 'docs/design/ozmap-2026-10-24/council2-opus.md',
       'docs/design/ozmap-2026-10-24/council3-astra.md', 'docs/design/ozmap-2026-10-24/council3-opus.md',
       'docs/design/ozmap-2026-10-24/council3-close-astra.md', 'docs/design/ozmap-2026-10-24/council3-close-opus.md',
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
    record = {'schema': 'ozmap.freeze/2', 'seed': SEED, 'files': hashes,
              'datasets': datasets if datasets is not None else data.dataset_digests(),
              'plan': plan_obj, 'plan_sha256': hashlib.sha256(json.dumps(plan_obj, sort_keys=True).encode()).hexdigest()}
    record['boolq_source'] = data.BOOLQ_SOURCE
    record['interpreter'] = interpreter_record()
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


def verify_freeze(record, root=REPO, *, datasets=None, plan_obj=None, files=None):
    """Problems (empty when the freeze record matches the current files, datasets, plan and interpreter). The record
    must hold every required file (files, default FREEZE_FILES), each present at the freeze (council 3 close)."""
    root = Path(root)
    problems = []
    required = list(FREEZE_FILES if files is None else files)
    for rel in required:
        if rel not in record.get('files', {}):
            problems.append(f'{rel} is missing from the freeze record')
        elif record['files'][rel] is None:
            problems.append(f'{rel} was absent at the freeze')
    for rel, sha in record.get('files', {}).items():
        path = root / rel
        now = _sha_file(path) if path.is_file() else None
        if now != sha and sha is not None:
            problems.append(f'{rel} changed since the freeze')
    now = datasets if datasets is not None else data.dataset_digests()
    if now != record.get('datasets'):
        problems.append('a dataset changed since the freeze')
    p = plan_obj if plan_obj is not None else plan()
    if hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest() != record.get('plan_sha256'):
        problems.append('the plan changed since the freeze')
    if record.get('interpreter') != interpreter_record():
        problems.append('the interpreter (path, sha256 or version) changed since the freeze')
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
    problems = leakage_problems() + registry_problems()
    closure = {b: dependency_closure(b, child_env(b)) for b in BACKENDS}
    for b, rec in closure.items():
        problems += [f'{b}: {p}' for p in closure_problems(rec)]
    for b, frozen in _routes().items():
        loose = [e for e in (frozen.get('launch') or {}).get('externals') or []
                 if e[2] in ('unversioned', None) or e[1] == 'declared-external']
        if loose:
            problems.append(f'{b}: unversioned dependencies {loose}')
    if problems:
        print('freeze refused: ' + '; '.join(problems))
        return 2
    result = dry(verbose=False)
    bad = ([f'dry: {result["external_calls"]} external calls'] if result['external_calls'] else []) + \
        ([] if result['reconciliation']['ok'] else ['dry: reconciliation failed']) + \
        [f'dry: {p}' for p in result['prompt_leakage']] + \
        (['dry: tool use'] if result['isolation']['tool_use_leakage'] else []) + \
        ([f'dry: {result["fake_misses"]} fake answer misses'] if result['fake_misses'] else []) + \
        ([] if result['telemetry']['status'] == 'ok' else [f"dry: telemetry {result['telemetry']['status']}"])
    iso = result['isolation']
    if iso.get('codex_isolated') != iso.get('codex_calls') or iso.get('claude_tools_disabled') != iso.get('claude_calls'):
        bad.append(f'dry: isolation counts short ({json.dumps(iso)})')
    if bad:
        print('freeze refused: ' + '; '.join(bad))
        return 2
    record = freeze_record()
    head = run(['git', 'rev-parse', 'HEAD'], cwd=REPO, capture_output=True, text=True).stdout.strip()
    record['git_head'] = head
    record['registry_manifest_sha256'] = json.loads(REGISTRY_FILE.read_text(encoding='utf-8'))['manifest_sha256']
    record['closure'] = closure
    record['tokenizer'] = tokenizer_record()
    record['dry_run']['output_sha256'] = result['output_sha256']
    record['dry_run']['output'] = deterministic(result)
    _write(FREEZE_FILE, record)
    print(f'freeze.json written ({len(record["files"])} files, git {head[:12]}, dry output {result["output_sha256"][:12]})')
    return 0


# ------------------------------------------------------------------------------------------------ identity

def probe_identity(backend):
    """The adapter's own `--identity` report under the child environment the host will use. No model call."""
    cfg = BACKENDS[backend]
    argv = json.loads(cfg['adapter'].read_text(encoding='utf-8'))['argv']
    env = child_env(backend)
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
    if _percent(getattr(args, 'claude_weekly', None)) is None:
        return ('refused: pass --claude-weekly PCT, the Claude weekly usage read just now (the 99% handoff stop has '
                'no programmatic source)')
    if _percent(args.claude_weekly) >= HANDOFF_PERCENT:
        return f'refused: Claude weekly usage {args.claude_weekly}% has reached {HANDOFF_PERCENT:g}%; hand off'
    return None


def _live_run_dir():
    record = json.loads(FREEZE_FILE.read_text(encoding='utf-8'))
    return RUNS / ('live-' + hashlib.sha256(_dump(record).encode()).hexdigest()[:12]), record


def _live_context(args):
    import oz_host
    run_dir, record = _live_run_dir()
    session = 'live-' + os.urandom(6).hex()
    record_reading(run_dir, args.claude_weekly, 'owner (--claude-weekly)', session)
    return _context('live', run_dir, env=None, routes=_routes(),
                    registry=json.loads(REGISTRY_FILE.read_text(encoding='utf-8')), closure=record.get('closure'),
                    quota=oz_host.QuotaStore(), session=session, telemetry_file=TELEMETRY_FILE,
                    freeze_sha256=_sha_file(FREEZE_FILE))


def telemetry(args):
    refusal = guard(args)
    if refusal:
        print(refusal)
        return 2
    ctx = _live_context(args)
    try:
        problems = preflight(ctx)
        if problems:
            print('refused: ' + '; '.join(problems))
            return 2
        doc = run_telemetry(ctx)
    finally:
        _close(ctx)
    print('telemetry', doc['status'], json.dumps(doc['evidence'].get('problems')))
    return 0 if doc['status'] == 'ok' else 1


def run_live(args):
    refusal = guard(args)
    if refusal:
        print(refusal)
        return 2
    if 'OZ_CODEX_TIMEOUT' in os.environ:
        print('refused: OZ_CODEX_TIMEOUT is set but not part of the frozen route environment')
        return 2
    doc = json.loads(TELEMETRY_FILE.read_text(encoding='utf-8')) if TELEMETRY_FILE.exists() else None
    semantics = usage_semantics(_routes(), doc, _sha_file(FREEZE_FILE))
    if semantics['codex'] == 'unverified':
        print('refused: telemetry is not certified for this freeze and the frozen codex route (run `pilot.py '
              'telemetry --i-have-approval --claude-weekly PCT` first)')
        return 2
    ctx = _live_context(args)
    try:
        problems = preflight(ctx)
        if problems:
            print('refused: ' + '; '.join(problems))
            return 2
        ctx['telemetry'], ctx['semantics'] = doc, semantics
        drive(ctx)
    finally:
        _close(ctx)
    print('run finished:', _rel(ctx['run_dir']))
    return 0


def quota_reading(args):
    run_dir = Path(args.run_dir) if args.run_dir else (_live_run_dir()[0] if FREEZE_FILE.exists() else None)
    if run_dir is None:
        print('no run directory')
        return 2
    value = record_reading(run_dir, args.percent, 'owner (quota command)', 'owner')
    print(f'recorded {value:g}% for {run_dir}')
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
    t.add_argument('--claude-weekly')
    r = sub.add_parser('run')
    r.add_argument('--live', action='store_true')
    r.add_argument('--i-have-approval', action='store_true')
    r.add_argument('--claude-weekly')
    qa = sub.add_parser('quota')
    qa.add_argument('--percent', required=True)
    qa.add_argument('run_dir', nargs='?')
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
    if args.command == 'quota':
        return quota_reading(args)
    if args.command == 'report':
        return report(args)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
