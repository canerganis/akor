"""oz map kill pilot preparation (bench/ozmap): datasets, independent oracle, registry, plan, dry run, freeze, live
guards and the ordered gate logic. Replay adapters only; no model calls, no network."""
from decimal import Decimal
import json
import re
from pathlib import Path
import sys
import tempfile
import types
import unittest

import importlib.util

REPO = Path(__file__).resolve().parent.parent
for p in (REPO, REPO / 'examples'):
    sys.path.insert(0, str(p))

import bootstrap_shim  # noqa: E402
import oz_registry  # noqa: E402
import oz_rule  # noqa: E402


def _load(name):
    """bench/ozmap/<name>.py under the unique module name pilot.py uses (ozmap_<name>)."""
    key = 'ozmap_' + name
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, REPO / 'bench' / 'ozmap' / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


pilot = _load('pilot')
data, oracle, score = pilot.data, pilot.oracle, pilot.score

MAT = data.materials()
# Placeholder routes from the sources alone: the registry tests never depend on an identity record or routes.json.
STATIC = {b: pilot.static_route(b) for b in pilot.BACKENDS}


def eval_jobs(wave=None):
    return [j for w in ([wave] if wave else data.WAVES) for js in MAT['waves'][w].values() for j in js]


def interval(text):
    f = oracle.fields(text)
    if f['uncertainty'] == 'unknown':
        return None
    lo = oracle.quantity(f['length']) - oracle.quantity(f['uncertainty'])
    hi = oracle.quantity(f['length']) + oracle.quantity(f['uncertainty'])
    return lo, hi


class Datasets(unittest.TestCase):
    def test_deterministic_and_exactly_the_planned_shape(self):
        again = data.materials()
        self.assertEqual(again, MAT)
        self.assertEqual(data.dataset_digests(), data.dataset_digests())
        for wave in data.WAVES:
            self.assertEqual(sorted(MAT['waves'][wave]), list(data.PRODUCERS))
            for p, jobs in MAT['waves'][wave].items():
                self.assertEqual(len(jobs), 64)
                self.assertEqual({op: sum(j['op'] == op for j in jobs) for op in data.OPS},
                                 {op: 16 for op in data.OPS})
                for j in jobs:
                    self.assertEqual(set(j), {'key', 'op', 'text', 'dataset_id'})
        texts = [oracle.resolve(j['text']) for j in eval_jobs()]
        self.assertEqual(len(texts), 512)
        self.assertEqual(len(set(texts)), 512)  # cold and warm are fresh, disjoint jobs
        self.assertEqual(len({j['dataset_id'] for j in eval_jobs()}), 512)

    def test_op_texts_are_verbatim_from_live2(self):
        source = (REPO / 'bench' / 'live' / 'live2.py').read_text(encoding='utf-8')
        self.assertIn("'v': \"Return inside if the entire length +/- uncertainty interval lies within the goal's "
                      "acceptance interval; outside otherwise. If uncertainty is unknown, return unknown.\"", source)
        self.assertEqual(data.MAT_D['v'], "Return inside if the entire length +/- uncertainty interval lies within the "
                         "goal's acceptance interval; outside otherwise. If uncertainty is unknown, return unknown.")
        self.assertTrue(data.MAT_GOAL.startswith('Prepare an evidence-limited inspection handoff. The numerical '
                                                 'acceptance interval is [12.48,12.52] mm, inclusive.'))

    def test_boundary_and_drift_coverage_per_wave(self):
        for wave in data.WAVES:
            jobs = eval_jobs(wave)
            boundary = [j for j in jobs if set(MAT['tags'][j['dataset_id']]) & data.BOUNDARY]
            self.assertGreaterEqual(len(boundary), 32)
            ends = [interval(j['text']) for j in jobs]
            ends = [e for e in ends if e]
            self.assertTrue(any(lo == Decimal('12.48') for lo, hi in ends))
            self.assertTrue(any(hi == Decimal('12.52') for lo, hi in ends))
            self.assertTrue(any(lo == Decimal('12.48') and hi == Decimal('12.52') for lo, hi in ends))
            self.assertTrue(any(hi == Decimal('12.48') for lo, hi in ends))  # touching from outside
            fields = [oracle.fields(j['text']) for j in jobs]
            self.assertGreaterEqual(sum(f['uncertainty'] in ('0 mm', '0.00 mm', '0.000 mm') for f in fields), 4)
            self.assertGreaterEqual(sum(f['uncertainty'] == 'unknown' for f in fields), 16)
            self.assertGreaterEqual(sum(f['method'] == 'unknown' or f['basis'] == 'unknown' for f in fields), 16)
            self.assertTrue(any(re.fullmatch(r'\d+\.\d\d0 mm', f['length']) for f in fields))  # 12.500 mm
            self.assertTrue(any(re.fullmatch(r'0\.0\d0 mm', f['uncertainty']) for f in fields))  # 0.020 mm
            self.assertGreaterEqual(sum(len(f['length'].split(' ')[0].split('.')[1]) == 3 for f in fields), 16)
            self.assertGreaterEqual(sum(f['n'].startswith('0') for f in fields), 16)
            self.assertGreaterEqual(sum(j['text'].endswith('\r\n') for j in jobs), 16)
            self.assertGreaterEqual(sum(j['text'].endswith('\n') and not j['text'].endswith('\r\n') for j in jobs), 16)
            self.assertGreaterEqual(sum(list(f) != list(data.FIELDS) for f in fields), 16)

    def test_enough_inside_labels_and_every_v_label_occurs(self):
        for wave in data.WAVES:
            v = [oracle.gold('v', j['text']) for j in eval_jobs(wave) if j['op'] == 'v']
            self.assertEqual(len(v), 64)
            self.assertGreaterEqual(v.count('inside'), 16)
            self.assertGreaterEqual(v.count('outside'), 16)
            self.assertGreaterEqual(v.count('unknown'), 4)
            b = [oracle.gold('b', j['text']) for j in eval_jobs(wave) if j['op'] == 'b']
            self.assertIn('unknown', b)
            self.assertTrue(any(x == ['12.48 mm', '12.52 mm'] for x in b) or
                            any(x[0] == '12.48 mm' for x in b if isinstance(x, list)))

    def test_every_evaluation_and_admission_record_is_defined_by_the_op_texts(self):
        for j in eval_jobs():
            oracle.gold(j['op'], j['text'])  # raises Undefined on a duplicate field, tie or bad quantity
        for op, rows in MAT['admission_texts'].items():
            for _, text, _, _ in rows:
                oracle.gold(op, text)


class Oracle(unittest.TestCase):
    HAND = [
        ('e', 'length=12.50 mm; uncertainty=0.02 mm; n=3; method=unknown; basis=unknown; physical_validation=not_claimed',
         ['12.50 mm', '0.02 mm', '3', 'unknown', 'unknown', 'not_claimed']),
        ('e', 'length=12.500 mm; uncertainty=0.020 mm; n=03; method=caliper; basis=expanded; '
              'physical_validation=not_claimed', ['12.500 mm', '0.020 mm', '03', 'caliper', 'expanded', 'not_claimed']),
        ('e', 'basis=resolution; n=7; physical_validation=not_claimed; length=12.47 mm; method=micrometer; '
              'uncertainty=0.03 mm', ['12.47 mm', '0.03 mm', '7', 'micrometer', 'resolution', 'not_claimed']),
        ('e', 'length=12.51 mm; uncertainty=0 mm; n=1; method=caliper; basis=expanded; physical_validation=not_claimed\n',
         ['12.51 mm', '0 mm', '1', 'caliper', 'expanded', 'not_claimed']),
        ('b', 'length=12.50 mm; uncertainty=0.02 mm', ['12.48 mm', '12.52 mm']),
        ('b', 'length=12.47 mm; uncertainty=0.03 mm', ['12.44 mm', '12.50 mm']),
        ('b', 'length=12.50 mm; uncertainty=unknown', 'unknown'),
        ('b', 'length=12.500 mm; uncertainty=0.000 mm', ['12.50 mm', '12.50 mm']),
        ('b', 'length=12.503 mm; uncertainty=0.011 mm', ['12.49 mm', '12.51 mm']),
        ('b', 'length=12.495 mm; uncertainty=0.015 mm', ['12.48 mm', '12.51 mm']),
        ('b', 'length=12.48 mm; uncertainty=0.00 mm\r\n', ['12.48 mm', '12.48 mm']),
        ('m', 'uncertainty=0.02 mm; method=unknown; basis=unknown', ['method', 'basis']),
        ('m', 'uncertainty=unknown; method=unknown; basis=unknown', ['uncertainty', 'method', 'basis']),
        ('m', 'uncertainty=0.02 mm; method=caliper; basis=repeatability', []),
        ('m', 'basis=unknown; uncertainty=unknown; method=caliper', ['uncertainty', 'basis']),
        ('v', 'length=12.50 mm; uncertainty=0.02 mm', 'inside'),
        ('v', 'length=12.49 mm; uncertainty=0.02 mm', 'outside'),
        ('v', 'length=12.51 mm; uncertainty=0.02 mm', 'outside'),
        ('v', 'length=12.48 mm; uncertainty=0 mm', 'inside'),
        ('v', 'length=12.52 mm; uncertainty=0.00 mm', 'inside'),
        ('v', 'length=12.47 mm; uncertainty=0.01 mm', 'outside'),
        ('v', 'length=12.503 mm; uncertainty=0.011 mm', 'inside'),
        ('v', 'length=12.50 mm; uncertainty=unknown', 'unknown'),
        ('v', 'length=12.475 mm; uncertainty=0.005 mm', 'outside'),
    ]

    def test_hand_checked_cases(self):
        self.assertGreaterEqual(len(self.HAND), 20)
        for op, text, want in self.HAND:
            self.assertEqual(oracle.gold(op, text), want, (op, text))
        self.assertEqual(oracle.gold('boolq', 'passage: x\nquestion: y', True), 'yes')
        self.assertEqual(oracle.label('m', 'uncertainty=1 mm; method=x; basis=y'), {'type': 'list', 'value': []})
        self.assertEqual(oracle.label('v', 'length=1 mm; uncertainty=unknown'), {'type': 'string', 'value': 'unknown'})

    def test_undefined_records_are_refused(self):
        for op, text in (('b', 'length=12.485 mm; uncertainty=0.000 mm'),  # rounding tie
                         ('v', 'length=12.50 mm; length=12.51 mm; uncertainty=0.02 mm'),  # duplicate field
                         ('b', 'length=12.50 cm; uncertainty=0.02 mm'), ('v', 'length=twelve mm; uncertainty=0 mm'),
                         ('e', 'length=12.50 mm; uncertainty=0.02 mm'), ('v', 'length=unknown; uncertainty=0 mm')):
            with self.assertRaises(oracle.Undefined, msg=(op, text)):
                oracle.gold(op, text)

    def test_the_oracle_never_uses_the_rule_language(self):
        import ast
        tree = ast.parse((REPO / 'bench' / 'ozmap' / 'oracle.py').read_bytes())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split('.')[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or '').split('.')[0])
        self.assertEqual(imported, {'decimal', 're'})  # standard library only, no rule language, no registry
        strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertFalse(any('oz-rule/1' in s or '"expr"' in s for s in strings if not s.startswith('Independent')))

    def test_the_spec_worked_asts_agree_with_the_oracle_on_every_evaluation_job(self):
        # a cross check of the oracle against the spec's worked rules (never used for labels)
        asts = dict(zip(data.OPS, bootstrap_shim.HIDDEN_ASTS))
        for j in eval_jobs():
            got = oz_rule.evaluate(asts[j['op']].encode('utf-8'), oracle.resolve(j['text']))
            self.assertEqual((got['status'], got.get('value')), ('value', oracle.gold(j['op'], j['text'])),
                             j['dataset_id'])


class Admission(unittest.TestCase):
    def test_sixty_four_cases_per_op_disjoint_from_evaluation(self):
        cases = data.admission_cases(oracle)
        evaluation = {oracle.resolve(j['text']) for j in eval_jobs()} | \
            {oracle.resolve(j['text']) for j in MAT['telemetry']}
        for op in data.OPS:
            cs = cases[op]
            self.assertEqual(len(cs), 64)
            self.assertEqual(sum(c['partition'] == 'representative' for c in cs), 48)
            self.assertEqual(sum(c['partition'] == 'challenge' for c in cs), 16)
            resolved = {oracle.resolve(c['text']) for c in cs}
            self.assertEqual(len(resolved), 64)
            self.assertFalse(resolved & evaluation, op)
            for c in cs:
                self.assertEqual(c['expected'], oracle.label(op, c['text']))
        v = [c['expected']['value'] for c in cases['v'] if c['partition'] == 'challenge']
        self.assertGreaterEqual(v.count('inside'), 6)
        self.assertEqual(pilot.leakage_problems(), [])

    def test_registry_resolves_and_admits_the_worked_rules_with_oracle_provenance(self):
        manifests = pilot.build_manifests(None, STATIC)
        self.assertEqual(sorted(manifests), ['codex', 'sonnet'])
        sha = pilot._sha_file(REPO / 'bench' / 'ozmap' / 'oracle.py')
        for backend, manifest in manifests.items():
            registry = oz_registry.Registry(manifest)
            for op, ast in zip(data.OPS, bootstrap_shim.HIDDEN_ASTS):
                package = registry.resolve(op)
                self.assertTrue(package.eligible)
                self.assertEqual(package.provenance['labeler'], f'bench/ozmap/oracle.py sha256:{sha}')
                got = registry.admit(ast.encode('utf-8'), op)
                self.assertEqual((got['status'], got['covered_errors']), ('accepted', 0), (op, got['reasons']))
                self.assertGreaterEqual(got['coverage'], 32)
            routes = {manifest['operations'][op]['route']['cli_version'] for op in data.OPS}
            self.assertEqual(routes, {pilot.PLACEHOLDER})
        self.assertNotEqual(manifests['codex']['operations']['e']['worker_hash'],
                            manifests['sonnet']['operations']['e']['worker_hash'])
        self.assertEqual(manifests['codex']['operations']['e']['route']['model'], 'gpt-6.1-sol')
        self.assertEqual(manifests['sonnet']['operations']['e']['route']['model'], 'claude-sonnet-5-5')

    def test_quoted_span_cannot_check_an_array_value_so_e_uses_provenance(self):
        text = 'length=12.50 mm; uncertainty=0.02 mm; n=3; method=x; basis=y; physical_validation=not_claimed'
        runner = oz_registry.LocalChecks()
        self.assertFalse(runner.run('quoted_span', 1, {}, oracle.gold('e', text), text))
        checks = pilot.check_definitions()
        hashes = checks['materials_provenance']['authorized_contract_hashes']
        self.assertEqual(sorted(hashes), sorted(oz_registry.digest(pilot.contracts()[op]) for op in data.OPS))

    def test_the_registry_file_matches_the_builder(self):
        doc = json.loads(pilot.REGISTRY_FILE.read_text(encoding='utf-8'))
        if pilot.IDENTITY_FILE.exists():
            self.skipTest('identity recorded; the file is checked by freeze')
        q = data.boolq()
        self.assertEqual(doc['manifests'], pilot.build_manifests(q if q['available'] else None))
        self.assertEqual(doc['boolq'], 'available' if q['available'] else q['reason'])
        for backend in pilot.BACKENDS:
            self.assertEqual(oz_registry.digest(doc['manifests'][backend]), doc['manifest_sha256'][backend])


class BoolQ(unittest.TestCase):
    def test_boolq_is_ineligible_by_construction(self):
        manifests = pilot.build_manifests(data.boolq_standin(), STATIC)
        registry = oz_registry.Registry(manifests['codex'])
        with self.assertRaises(oz_registry.RegistryError) as ctx:
            registry.resolve('boolq')
        self.assertEqual(ctx.exception.code, 'ineligible')
        got = registry.admit(b'{"lang":"oz-rule/1","expr":["s","yes"]}', 'boolq')
        self.assertEqual((got['status'], got['reasons']), ('rejected', ['ineligible']))
        self.assertEqual(manifests['codex']['operations']['boolq']['checks'], ['boolq_one_of'])

    def test_the_recorded_superglue_file_is_used_with_its_hash_and_fields(self):
        if not data.BOOLQ_FILE.exists():
            self.skipTest('BoolQ file absent')
        got = data.boolq()
        self.assertEqual((got['available'], got['sha256'], got['rows']), (True, data.BOOLQ_SHA256, 3270))
        self.assertEqual(got['source']['url'], 'https://dl.fbaipublicfiles.com/glue/superglue/data/v2/BoolQ.zip')
        self.assertEqual(got['source']['zip_sha256'],
                         '853fbe7922f70c59629f06a39e8d9ca440c3d740e760fd3b87a5ddf3dcba2436')
        jobs = [j for js in got['waves']['cold'].values() for j in js]
        self.assertEqual(len(jobs), 256)
        self.assertEqual(len({j['text'] for j in jobs}), 256)
        self.assertEqual(set(got['labels']), {j['dataset_id'] for j in jobs})
        self.assertEqual({oracle.gold('boolq', '', a) for a in got['labels'].values()}, {'yes', 'no'})
        manifests = pilot.build_manifests(got, STATIC)
        self.assertEqual(len(manifests['codex']['operations']['boolq']['dataset']['cases']), 64)
        with self.assertRaises(oz_registry.RegistryError):
            oz_registry.Registry(manifests['codex']).resolve('boolq')
        self.assertTrue(pilot.plan()['boolq_available'])
        self.assertEqual(pilot.plan()['boolq_source']['file_sha256'], data.BOOLQ_SHA256)

    def test_absent_file_makes_the_cells_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            got = data.boolq(Path(d) / 'boolq-superglue-val.jsonl')
        self.assertFalse(got['available'])
        p = pilot.plan(boolq_available=False)
        self.assertFalse(p['complete'])
        self.assertTrue(any('codex-boolq cold A' in i.get('cells', []) for i in p['incomplete']))
        summary = {'cells': {}, 'boolq_available': False}
        g = score.gate_boolq(summary)
        self.assertFalse(g['pass'])
        self.assertTrue(g['incomplete'])
        self.assertIn('unavailable', g['detail'])

    def test_loader_samples_256_plus_64_disjoint_records(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'boolq-superglue-val.jsonl'
            path.write_text(''.join(json.dumps({'idx': i, 'question': f'is it {i}', 'passage': f'passage {i}.',
                                                'label': i % 3 == 0}) + '\n' for i in range(400)), encoding='utf-8')
            got = data.boolq(path)
            again = data.boolq(path)
            with self.assertRaises(ValueError):
                data.boolq(path, expected_sha256='0' * 64)
        self.assertTrue(got['available'])
        self.assertEqual(got, again)
        jobs = [j for js in got['waves']['cold'].values() for j in js]
        self.assertEqual((len(jobs), sorted(len(v) for v in got['waves']['cold'].values())), (256, [64] * 4))
        self.assertTrue(all(j['text'].startswith('passage: ') and '\nquestion: ' in j['text'] for j in jobs))
        self.assertEqual(len(got['admission']), 64)
        self.assertFalse({j['text'] for j in jobs} & {t for _, t, _, _ in got['admission']})
        self.assertEqual(set(got['labels']), {j['dataset_id'] for j in jobs})


class Plan(unittest.TestCase):
    def test_plan_sums_to_the_global_cap_54_and_every_cell_is_complete(self):
        p = pilot.plan(boolq_available=True)
        caps = {b: sum(c.values()) for b, c in pilot.CAPS.items()}
        self.assertEqual(caps, {'codex': 37, 'sonnet': 17})
        self.assertEqual((pilot.GLOBAL_CAP, score.GLOBAL_CAP), (54, 54))
        self.assertEqual(p['allocation_total'], 54)
        self.assertEqual(p['nominal_physical_calls'], 44)
        self.assertLessEqual(p['nominal_physical_calls'], pilot.GLOBAL_CAP)
        self.assertTrue(p['fits_global_cap'])
        self.assertEqual(pilot.CAPS['codex'], {'telemetry': 1, 'bootstrap': 2, 'A': 12, 'B': 8, 'C': 7, 'reserve': 7})
        self.assertEqual(pilot.CAPS['sonnet'], {'telemetry': 0, 'bootstrap': 1, 'A': 8, 'B': 4, 'C': 2, 'reserve': 2})
        self.assertTrue(p['complete'])
        self.assertEqual(p['incomplete'], [])
        self.assertFalse(any('A2.3' in c['cell'] for c in p['cells']))
        sonnet_arms = {(c['wave'], c['arm']) for c in p['cells'] if c['cell'] == 'sonnet-materials'}
        self.assertEqual(sonnet_arms, {('cold', 'A'), ('cold', 'B'), ('cold', 'C'), ('warm', 'A'), ('warm', 'C')})
        rows = {(r['backend'], r['bucket']): r for r in p['table']}
        self.assertEqual(rows[('codex', 'telemetry')]['nominal'], 1)
        self.assertEqual(rows[('codex', 'reserve')]['nominal'], 1)  # the second paired telemetry invocation
        self.assertEqual(rows[('codex', 'A')]['nominal'], 12)
        self.assertEqual(rows[('codex', 'B')]['nominal'], 8)
        self.assertEqual(rows[('sonnet', 'bootstrap')]['nominal'], 1)
        self.assertEqual(rows[('sonnet', 'B')]['nominal'], 4)  # four dedicated calls, not the reserve
        self.assertEqual(rows[('sonnet', 'C')]['nominal'], 2)
        self.assertEqual(rows[('sonnet', 'reserve')]['nominal'], 0)
        self.assertTrue(all(r['fits'] for r in p['table']))

    def test_plan_carries_host_quota_stop_and_the_amendment_3_gate_texts(self):
        p = pilot.plan(boolq_available=True)
        self.assertEqual(p['host'], pilot.HOST)
        self.assertEqual(p['quota_stop'], pilot.QUOTA_STOP)
        self.assertIn('99%', p['quota_stop'])
        self.assertIn('suspended', p['quota_stop'])
        self.assertEqual(p['gate_texts'], score.GATE_TEXTS)
        self.assertEqual(sorted(p['gate_texts']), ['boolq', 'materials_warm'])


class DryRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = pilot.dry(verbose=False)

    def test_dry_run_makes_no_call_reconciles_and_fits_the_cap(self):
        r = self.result
        self.assertEqual(r['external_calls'], 0)
        self.assertTrue(r['reconciliation']['ok'], r['reconciliation'])
        self.assertTrue(r['within_global_cap'])
        self.assertEqual(r['physical_calls_total'], r['budget']['total'])
        self.assertLessEqual(r['physical_calls_total'], pilot.GLOBAL_CAP)
        self.assertEqual(r['physical_calls_total'], 44)
        self.assertEqual(r['physical_calls_by_backend'], {'codex': 29, 'sonnet': 15})
        self.assertEqual(r['budget']['used']['codex'], {'telemetry': 1, 'reserve': 1, 'bootstrap': 2, 'A': 12, 'B': 8,
                                                        'C': 5})
        self.assertEqual(r['budget']['used']['sonnet'], {'bootstrap': 1, 'A': 8, 'B': 4, 'C': 2})

    def test_n2_dry_is_the_live_driver_with_fake_cli_executables(self):
        r = self.result
        self.assertIn('pilot.drive', r['driver'])
        # every physical call (telemetry included) was served by a fake CLI child: zero real CLI calls
        self.assertEqual(r['reconciliation']['fake_cli_calls'], r['physical_calls_total'])
        self.assertEqual(r['reconciliation']['telemetry_calls'], 2)
        iso = r['isolation']
        self.assertEqual((iso['codex_calls'], iso['codex_isolated']), (29, 29))  # N1: empty -C dir outside the repo
        self.assertEqual((iso['claude_calls'], iso['claude_tools_disabled']), (15, 15))
        self.assertEqual((iso['tool_use_leakage'], iso['gold_accessed_during_run']), ([], False))
        self.assertEqual(r['telemetry']['status'], 'ok')  # the paired telemetry ran through the fake codex
        self.assertTrue(r['usage_semantics']['codex'].startswith('inclusive cached accounting certified'))
        self.assertEqual(r['usage_semantics']['sonnet'], pilot.SONNET_SEMANTICS)
        self.assertEqual((r['prompt_leakage'], r['fake_misses']), ([], 0))
        self.assertRegex(r['output_sha256'], r'^[0-9a-f]{64}$')
        self.assertEqual(r['output_sha256'], pilot._digest(pilot.deterministic(r)))
        self.assertNotIn('wall_seconds', json.dumps(pilot.deterministic(r)))

    def test_every_cell_is_complete_and_the_dry_run_fits(self):
        rows = {(x['cell'], x['wave'], x['arm']): x for x in self.result['rows']}
        self.assertEqual(len(rows), 13)
        bad = [k for k, x in rows.items() if x['evidence'] != 'complete']
        self.assertEqual(bad, [])
        self.assertFalse(any('A2.3' in k[0] for k in rows))
        b = rows[('sonnet-materials', 'cold', 'B')]
        self.assertEqual((b['physical_calls'], b['refused']), (4, 0))  # four dedicated residual calls
        self.assertEqual(rows[('sonnet-materials', 'cold', 'C')]['physical_calls'], 2)  # shared bootstrap + 1 pooled
        self.assertEqual(b['incomplete'], [])
        self.assertTrue(self.result['dry_run_fits'])
        self.assertTrue(all('replayed_call_seconds' in x for x in rows.values()))

    def test_dry_run_keeps_its_sources_and_assumptions(self):
        r = self.result
        self.assertEqual(r['assumptions'], pilot.ASSUMPTIONS)
        src = r['sources']
        self.assertEqual(sorted(src['ledgers']), ['codex', 'sonnet'])
        for b, entry in src['ledgers'].items():
            self.assertRegex(entry['sha256'], r'^[0-9a-f]{64}$', b)
            self.assertTrue(entry['file'], b)
            self.assertTrue(src['samples'][b], b)
        self.assertIs(src['bootstrap']['estimated'], True)
        self.assertIn('materials usage samples', src['boolq_usage'])

    def test_projection_numbers_follow_the_record(self):
        rows = {(x['cell'], x['wave'], x['arm']): x for x in self.result['rows']}
        for backend in ('codex', 'sonnet'):
            cold_c = rows[(f'{backend}-materials', 'cold', 'C')]
            self.assertEqual((cold_c['audits_selected'], cold_c['coverage']), (32, 0.75))
            self.assertEqual(rows[(f'{backend}-materials', 'cold', 'A')]['physical_calls'], 4)
            self.assertEqual(rows[(f'{backend}-materials', 'warm', 'C')]['coverage'], 1.0)
            self.assertLess(cold_c['tokens'], rows[(f'{backend}-materials', 'cold', 'A')]['tokens'])
        self.assertEqual(rows[('codex-boolq', 'cold', 'C')]['coverage'], 0.0)
        self.assertEqual(rows[('codex-boolq', 'cold', 'C')]['physical_calls'], 3)
        self.assertEqual(rows[('codex-materials', 'cold', 'B')]['physical_calls'], 5)  # bootstrap + 4 producers
        gates = {g['name']: g for g in self.result['projected_gates']['gates']}
        self.assertTrue(gates['safety']['pass'] and gates['validity']['pass'] and gates['pooling']['pass'])


class Freeze(unittest.TestCase):
    def test_freeze_detects_a_changed_file_dataset_and_plan(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'a.py').write_text('x = 1\n', encoding='utf-8')
            (root / 'b.json').write_text('{}\n', encoding='utf-8')
            plan_obj = {'p': 1}
            files = ['a.py', 'b.json']
            record = pilot.freeze_record(root, files, datasets={'d': 'h'}, plan_obj=plan_obj)
            self.assertEqual(pilot.verify_freeze(record, root, datasets={'d': 'h'}, plan_obj=plan_obj, files=files), [])
            (root / 'a.py').write_text('x = 2\n', encoding='utf-8')
            self.assertEqual(pilot.verify_freeze(record, root, datasets={'d': 'h'}, plan_obj=plan_obj, files=files),
                             ['a.py changed since the freeze'])
            self.assertIn('a dataset changed since the freeze',
                          pilot.verify_freeze(record, root, datasets={'d': 'other'}, plan_obj=plan_obj, files=files))
            self.assertIn('the plan changed since the freeze',
                          pilot.verify_freeze(record, root, datasets={'d': 'h'}, plan_obj={'p': 2}, files=files))
            (root / 'b.json').unlink()
            self.assertIn('b.json changed since the freeze',
                          pilot.verify_freeze(record, root, datasets={'d': 'h'}, plan_obj=plan_obj, files=files))

    def test_freeze_refuses_uncommitted_frozen_files(self):
        def fake(argv, **kw):
            return types.SimpleNamespace(returncode=0, stdout=' M bench/ozmap/pilot.py\n?? bench/ozmap/x.json\n',
                                         stderr='')
        self.assertEqual(pilot.git_dirty(['bench/ozmap'], run=fake), ['bench/ozmap/pilot.py', 'bench/ozmap/x.json'])
        self.assertEqual(pilot.git_dirty(['x'], run=lambda a, **k: types.SimpleNamespace(returncode=0, stdout='',
                                                                                        stderr='')), [])
        for name in ('oz_host.py', 'bench/ozmap/registry.json', 'bench/ozmap/oracle.py', 'oz_do.py',
                     'docs/design/ozmap-2026-10-24/bootstrap-spec-excerpt.txt', 'bench/live/live2.py',
                     'bench/ozmap/data/boolq-superglue-val.jsonl'):
            self.assertIn(name, pilot.FREEZE_FILES)


    def test_freeze_record_carries_amendment_3_precedence_allocation_gate_texts_and_dry_run_sources(self):
        record = pilot.freeze_record(datasets={'d': 'h'}, plan_obj={'p': 1})
        norm = record['normative']
        self.assertEqual(norm['precedence'], list(pilot.NORMATIVE))
        self.assertEqual(list(norm['sha256']), list(pilot.NORMATIVE))
        for rel in pilot.NORMATIVE:
            self.assertRegex(norm['sha256'][rel] or '', r'^[0-9a-f]{64}$', rel)
            self.assertEqual(norm['sha256'][rel], pilot._sha_file(REPO / rel), rel)
        self.assertTrue(pilot.NORMATIVE[-1].endswith('amendment-3.md'))
        self.assertEqual(record['allocation'], {'global_cap': 54, 'caps': pilot.CAPS, 'quota': pilot.QUOTA_STOP})
        self.assertEqual(record['allocation']['caps']['sonnet']['B'], 4)
        self.assertEqual(record['gate_texts'], score.GATE_TEXTS)
        self.assertIn('1.10 times A', record['gate_texts']['boolq'])
        self.assertIn('No bootstrap subtraction', record['gate_texts']['boolq'])
        self.assertIn('0.90 times matched warm A', record['gate_texts']['materials_warm'])
        self.assertEqual(record['timing'], score.TIMING)
        self.assertEqual(record['host'], pilot.HOST)
        self.assertEqual(record['dry_run']['assumptions'], pilot.ASSUMPTIONS)
        sources = record['dry_run']['sources']
        self.assertEqual(sorted(sources['ledgers']), ['codex', 'sonnet'])
        for b, entry in sources['ledgers'].items():
            self.assertRegex(entry['sha256'] or '', r'^[0-9a-f]{64}$', b)
        self.assertTrue(sources['bootstrap'].startswith('estimated'))
        self.assertIn('materials usage samples', sources['boolq_usage'])
        for rel in ('bench/ozmap/routes.json', 'docs/design/ozmap-2026-10-24/council3-astra.md',
                    'docs/design/ozmap-2026-10-24/council3-opus.md',
                    'docs/design/ozmap-2026-10-24/owner-decisions-2026-10-24.md',
                    'docs/design/ozmap-2026-10-24/amendment-3.md'):
            self.assertIn(rel, pilot.FREEZE_FILES)
            self.assertIn(rel, record['files'])

class LiveGuard(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.saved = (pilot.FREEZE_FILE, pilot.probe_identity, pilot.TELEMETRY_FILE, pilot.FREEZE_FILES)
        pilot.FREEZE_FILE = self.dir / 'freeze.json'
        pilot.TELEMETRY_FILE = self.dir / 'telemetry.json'
        # the files this checkout has (routes.json and freeze.json appear only at freeze)
        pilot.FREEZE_FILES = [f for f in self.saved[3] if (REPO / f).is_file()]

        def no_probe(backend):
            raise AssertionError('a guarded command must refuse before probing any CLI')
        pilot.probe_identity = no_probe

    def tearDown(self):
        pilot.FREEZE_FILE, pilot.probe_identity, pilot.TELEMETRY_FILE, pilot.FREEZE_FILES = self.saved

    def args(self, **kw):
        return types.SimpleNamespace(**{'command': 'run', 'live': True, 'i_have_approval': True,
                                        'claude_weekly': '40', **kw})

    def test_live_run_refuses_without_freeze(self):
        self.assertIn('no freeze.json', pilot.guard(self.args()))
        self.assertEqual(pilot.run_live(self.args()), 2)
        self.assertEqual(pilot.telemetry(self.args(command='telemetry')), 2)

    def test_live_run_refuses_with_a_stale_freeze_or_without_approval(self):
        record = pilot.freeze_record(files=pilot.FREEZE_FILES)
        stale = json.loads(json.dumps(record))
        stale['files']['oz_host.py'] = '0' * 64
        pilot._write(pilot.FREEZE_FILE, stale)
        self.assertIn('does not verify', pilot.guard(self.args()))
        pilot._write(pilot.FREEZE_FILE, record)
        self.assertIsNone(pilot.guard(self.args()))
        self.assertIn('--i-have-approval', pilot.guard(self.args(i_have_approval=False)))
        self.assertEqual(pilot.run_live(self.args(i_have_approval=False)), 2)
        self.assertIn('--live', pilot.guard(self.args(live=False)))
        self.assertIn('--claude-weekly', pilot.guard(self.args(claude_weekly=None)))
        self.assertIn('hand off', pilot.guard(self.args(claude_weekly='99')))
        # approval and a verified freeze, but unresolved telemetry: still no call
        self.assertEqual(pilot.run_live(self.args()), 2)


class Quota(unittest.TestCase):
    def test_no_text_says_a_55_percent_guard_is_active(self):
        texts = list(pilot.ASSUMPTIONS) + [pilot.QUOTA_STOP, pilot.plan(boolq_available=True)['quota_stop'],
                                           pilot.freeze_record(datasets={}, plan_obj={})['allocation']['quota']]
        self.assertTrue(any('55%' in t for t in texts))
        for t in texts:
            if '55%' in t:
                # only as suspended, or as an explicit negation ("No 55% weekly launch guard")
                self.assertTrue('suspended' in t or t.startswith('No 55%'), t)
        self.assertIn('99%', pilot.QUOTA_STOP)
        self.assertIn('suspended', pilot.QUOTA_STOP)

    def test_launch_gate_refuses_only_at_the_global_cap(self):
        def fake(total):
            return types.SimpleNamespace(usage=lambda: {'total': total})
        for total in (0, 28, 29, 40, 53):  # nothing refuses near 55% of the cap
            self.assertIsNone(pilot.launch_gate_for(fake(total))(None), total)
        self.assertEqual(pilot.launch_gate_for(fake(54))(None), 'global_cap_reached')
        self.assertEqual(pilot.launch_gate_for(fake(55))(None), 'global_cap_reached')


class PilotConfig(unittest.TestCase):
    ROUTE = {'adapter_hash': 'a' * 8, 'backend': 'codex', 'model': 'm', 'effort': 'medium', 'cli_version': '1',
             'environment_hash': 'e' * 8}

    def setUp(self):
        import oz_host
        self.oz_host = oz_host
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.identity = oz_host.identity_for(self.ROUTE)
        self.routes = {b: oz_host.identity_for(self.ROUTE) for b in pilot.BACKENDS}
        self.budgets = []
        self.addCleanup(lambda: [b.close() for b in self.budgets])

    def budget(self, name, caps=None):
        b = self.oz_host.Budget(self.dir / name, caps=caps or pilot.CAPS, global_cap=pilot.GLOBAL_CAP)
        self.budgets.append(b)
        return b

    def check(self, config, **over):
        host = pilot.HOST
        kw = dict(backend='codex', budget=self.budget('ok.sqlite'),
                  slot_pool=self.oz_host.SlotPool(self.dir / 'slots', 4), slots=host['slots'],
                  max_records=host['max_records'], max_wait=host['max_wait'], identity=self.identity, launcher=None,
                  limits=host['limits'], route_check=None)
        kw.update(over)
        return self.oz_host.check_pilot(config, **kw)

    def test_the_frozen_replay_configuration_passes_check_pilot(self):
        config = pilot.pilot_config('replay', self.routes, 'x')
        self.assertEqual((config['global_cap'], config['caps']), (54, pilot.CAPS))
        self.assertIsNone(self.check(config))

    def test_check_pilot_refuses_mismatched_budget_missing_pool_and_a_live_run_without_launcher(self):
        Error = self.oz_host.Error
        dry = pilot.pilot_config('replay', self.routes, 'x')
        other = json.loads(json.dumps(pilot.CAPS))
        other['codex']['A'] = 13
        other['codex']['reserve'] = 6
        with self.assertRaises(Error) as ctx:
            self.check(dry, budget=self.budget('other.sqlite', other))
        self.assertIn('pilot launch refused', str(ctx.exception))
        self.assertIn('budget', str(ctx.exception))
        with self.assertRaises(Error) as ctx:
            self.check(dry, slot_pool=None)
        self.assertIn('pilot launch refused', str(ctx.exception))
        self.assertIn('slot pool', str(ctx.exception))
        live = pilot.pilot_config('live', self.routes, 'x')
        with self.assertRaises(Error) as ctx:
            self.check(live, route_check=lambda *a, **k: None)
        self.assertIn('pilot launch refused', str(ctx.exception))
        self.assertIn('child processes', str(ctx.exception))


def summary(**over):
    """A synthetic summary where every gate passes; over replaces cells' fields: {'codex/materials/cold/C': {...}}."""
    def cell(jobs=256, correct=256, tokens=100000, span=60.0, rule_errors=0, **kw):
        c = {'jobs': jobs, 'correct': correct, 'incorrect': jobs - correct, 'unresolved': 0, 'rule_errors': rule_errors,
             'fallback_errors': 0, 'rule_hits': 0, 'coverage': 0.0, 'tokens': tokens, 'usage': 'complete',
             'tokens_per_correct': round(tokens / correct, 3) if correct else None, 'makespan_s': span,
             'evidence': 'complete', 'efficiency_valid': True, 'efficiency_invalid': [], 'incomplete': []}
        c.update(kw)
        return c
    cells = {}
    for backend in ('codex', 'sonnet'):
        cells[f'{backend}/materials/cold/A'] = cell(tokens=120000, span=30)
        cells[f'{backend}/materials/cold/C'] = cell(tokens=60000, span=150)
        cells[f'{backend}/materials/warm/A'] = cell(tokens=120000, span=30)
        cells[f'{backend}/materials/warm/C'] = cell(tokens=30000, span=15)
    cells['codex/materials/cold/B'] = cell(tokens=150000, span=160)
    cells['codex/boolq/cold/A'] = cell(tokens=120000, span=30, correct=220)
    cells['codex/boolq/cold/C'] = cell(tokens=125000, span=32, correct=220)
    for key, fields in over.items():
        cells[key].update(fields)
        if 'tokens' in fields or 'correct' in fields:
            c = cells[key]
            c['tokens_per_correct'] = round(c['tokens'] / c['correct'], 3) if c['correct'] else None
    return {'cells': cells, 'boolq_available': True,
            'validity': {'leakage': [], 'bootstrap': {'codex/materials': {'status': 'ok'}},
                         'budget': {'total': 42, 'over': {}}}}


class Gates(unittest.TestCase):
    def verdict(self, s):
        return score.evaluate(s)

    def test_all_pass_permits_the_headline(self):
        got = self.verdict(summary())
        self.assertEqual(got['verdict'], 'all gates pass')
        self.assertTrue(got['headline_permitted'])
        self.assertEqual(got['headline'], score.HEADLINE)

    def test_safety_kill(self):
        got = self.verdict(summary(**{'sonnet/materials/warm/C': {'rule_errors': 1}}))
        self.assertTrue(got['verdict'].startswith('killed: admission'))
        self.assertFalse(got['headline_permitted'])

    def test_validity_kills(self):
        for change in ({'leakage': ['admission text in eval']}, {'bootstrap': {'codex/materials': {'status': 'failed'}}},
                       {'bootstrap': {'codex/materials': {'status': 'ok', 'disagreements': 1}}},
                       {'bootstrap': {'codex/materials': {'status': 'ok', 'gold_errors': 2}}},
                       {'budget': {'total': 55, 'over': {}}}, {'budget': {'total': 40, 'over': {'codex': {'C': 8}}}}):
            s = summary()
            s['validity'].update(change)
            got = self.verdict(s)
            self.assertTrue(got['verdict'].startswith('invalid'), change)
        got = self.verdict(summary(**{'codex/materials/cold/C': {'usage': 'partial'}}))
        self.assertTrue(got['verdict'].startswith('invalid'))
        got = self.verdict(summary(**{'codex/materials/cold/C': {'efficiency_invalid': ['memo_served']}}))
        self.assertTrue(got['verdict'].startswith('invalid'))

    def test_materials_kills(self):
        for key, change in (('codex/materials/cold/C', {'tokens': 95000}),       # 0.79 > 0.75
                            ('sonnet/materials/cold/C', {'correct': 250}),     # correctness not preserved
                            ('codex/materials/warm/C', {'makespan_s': 28.0}),  # 0.93 > 0.9
                            ('sonnet/materials/warm/C', {'tokens': 70000})):   # 0.58 > 0.5
            got = self.verdict(summary(**{key: change}))
            self.assertEqual(got['verdict'], 'killed: materials efficiency gate failed', (key, change))
        got = self.verdict(summary(**{'codex/materials/cold/C': {'tokens': 90000}}))  # exactly 0.75 passes
        self.assertEqual(got['verdict'], 'all gates pass')
        got = self.verdict(summary(**{'codex/materials/warm/C': {'evidence': 'incomplete'}}))
        self.assertTrue(got['verdict'].startswith('incomplete'))

    def test_boolq_kills(self):
        for change in ({'correct': 219}, {'tokens': 133000}, {'makespan_s': 33.5}):
            got = self.verdict(summary(**{'codex/boolq/cold/C': change}))
            self.assertEqual(got['verdict'], 'killed: BoolQ overhead gate failed', change)
        s = summary()
        s['boolq_available'] = False
        self.assertTrue(self.verdict(s)['verdict'].startswith('incomplete: gate 4'))

    def test_validity_budget_is_checked_against_the_global_cap_54(self):
        s = summary()
        s['validity']['budget'] = {'total': 54, 'over': {}}
        self.assertEqual(self.verdict(s)['verdict'], 'all gates pass')
        s['validity']['budget'] = {'total': 55, 'over': {}}
        self.assertTrue(self.verdict(s)['verdict'].startswith('invalid'))

    def test_boolq_gate_uses_measured_makespan_never_summed_call_seconds(self):
        # C's summed physical call seconds are far smaller than A's, but the measured makespan ratio is 1.2: fails
        s = summary(**{'codex/boolq/cold/A': {'summed_call_seconds': 400.0},
                       'codex/boolq/cold/C': {'summed_call_seconds': 20.0, 'makespan_s': 36.0}})
        g = score.gate_boolq(s)
        self.assertFalse(g['pass'])
        self.assertFalse(g['detail']['checks']['measured_makespan_ratio<=1.10'])
        self.assertTrue(g['detail']['checks']['charged_tokens_ratio<=1.10'])
        self.assertEqual(g['detail']['time_ratio'], 1.2)
        self.assertAlmostEqual(g['detail']['summed_call_seconds_ratio_report_only'], 0.05)
        self.assertEqual(self.verdict(s)['verdict'], 'killed: BoolQ overhead gate failed')
        # ratios of 1.05 pass, even when C's summed call seconds are far larger than A's
        s = summary(**{'codex/boolq/cold/A': {'summed_call_seconds': 10.0},
                       'codex/boolq/cold/C': {'summed_call_seconds': 5000.0, 'makespan_s': 31.5, 'tokens': 126000}})
        g = score.gate_boolq(s)
        self.assertTrue(g['pass'], g)
        self.assertEqual((g['detail']['time_ratio'], g['detail']['token_ratio']), (1.05, 1.05))
        self.assertEqual(self.verdict(s)['verdict'], 'all gates pass')

    def test_summarize_reports_summed_call_seconds_separately(self):
        report = {'tokens': {'charged': {'tokens': 300, 'input_tokens': 250, 'output_tokens': 50, 'usage': 'complete'}},
                  'calls': {'physical': 1, 'charged': 1}, 'charged_makespan_seconds': 30.0, 'evidence': 'complete'}
        counts = {'correct': 2, 'incorrect': 0, 'unresolved': 0}
        got = score.summarize(2, counts, rule_errors=0, fallback_errors=0, rule_hits=0, report=report,
                              summed_call_seconds=12.5)
        self.assertEqual((got['makespan_s'], got['summed_call_seconds']), (30.0, 12.5))
        got = score.summarize(2, counts, rule_errors=0, fallback_errors=0, rule_hits=0, report=report)
        self.assertEqual(got['summed_call_seconds'], 0.0)

    def test_pooling_withdrawn(self):
        for change in ({'tokens': 50000}, {'correct': 257}, {'makespan_s': 140}):
            got = self.verdict(summary(**{'codex/materials/cold/B': change}))
            self.assertEqual(got['verdict'], 'gates 1 to 4 pass; pooling contribution claim withdrawn', change)
            self.assertFalse(got['headline_permitted'])

    def test_kills_are_ordered(self):
        got = self.verdict(summary(**{'codex/materials/cold/C': {'rule_errors': 1, 'tokens': 200000}}))
        self.assertTrue(got['verdict'].startswith('killed: admission'))

    def test_row_scoring(self):
        gold = {'d1': ('v', 'inside'), 'd2': ('e', ['1 mm']), 'd3': ('v', 'outside'), 'd4': ('m', [])}
        rows = [{'dataset_id': 'd1', 'status': 'accepted', 'value_text': '"inside"', 'source': 'rule', 'phase': 'rule'},
                {'dataset_id': 'd2', 'status': 'accepted', 'value_text': '["1.0 mm"]', 'source': 'model',
                 'phase': 'fallback'},
                {'dataset_id': 'd3', 'status': 'failed', 'value_text': None, 'source': 'model', 'phase': 'fallback'},
                {'dataset_id': 'd4', 'status': 'accepted', 'value_text': '[]', 'source': 'rule', 'phase': 'rule'}]
        report = {'tokens': {'charged': {'tokens': 300, 'input_tokens': 250, 'output_tokens': 50, 'usage': 'complete'}},
                  'calls': {'physical': 1, 'charged': 1}, 'charged_makespan_seconds': 30.0, 'evidence': 'complete',
                  'efficiency_valid': True}
        got = score.score_cell(rows, report, gold)
        self.assertEqual((got['correct'], got['incorrect'], got['unresolved']), (2, 1, 1))
        self.assertEqual((got['rule_errors'], got['fallback_errors'], got['rule_hits']), (0, 1, 2))
        self.assertEqual((got['tokens_per_correct'], got['coverage'], got['correct_per_min']), (150.0, 0.5, 4.0))


if __name__ == '__main__':
    unittest.main()
