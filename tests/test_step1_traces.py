"""Step 1 trace analysis (bench/analysis/step1_traces.py). Offline, standard library, no model call. It checks that the
script reproduces the frozen manifest digest and the headline totals, and that the committed results document is exactly
what the script regenerates."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'bench' / 'analysis'))

import step1_traces as T  # noqa: E402

MANIFEST_DIGEST = '8a1836182cdceaadfe63db56e808c8ffb0c1b423de2955b7c8c44048aa438191'
RESULTS = ROOT / 'docs' / 'design' / 'next-2026-10-23' / 'step1-results.md'


class Step1Traces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.man, cls.units, cls.fits, cls.cells, cls.runs = T.build()

    def test_manifest_digest_is_the_frozen_one(self):
        self.assertEqual(self.man['digest'], MANIFEST_DIGEST)
        self.assertEqual(T.verify_manifest(self.man), [])

    def test_selectors_regenerate_the_same_manifest(self):
        fresh = T.freeze()
        self.assertEqual(fresh['digest'], MANIFEST_DIGEST)
        self.assertEqual(fresh['count'], 858)

    def test_headline_totals(self):
        h = T.headline(self.units, self.cells, self.man)
        self.assertEqual(h['manifest_files'], 858)
        self.assertEqual(h['observation_files'], 179)
        self.assertEqual(h['units'], 790)
        self.assertEqual(h['denominator_main'], 6281572)
        self.assertEqual(h['denominator_smoke'], 354442)
        self.assertEqual(h['denominator_control'], 74236)
        self.assertEqual(h['cells'], 143)
        # O1 equals the run report's own tokens_known, which is an independent total
        self.assertEqual(h['o1_denominator'], 55413)

    def test_report_totals_agree_with_ledgers_except_the_unrecovered_call(self):
        cc = T.crosschecks(self.units, self.man)
        rep = cc['report_totals_vs_ledgers']
        for label in ('o1-live1', 'step4-live2', 'step4-live3'):
            self.assertEqual(rep[label][0], rep[label][1], label)
        self.assertEqual(rep['step4-live1'][0] - rep['step4-live1'][1], 2709)
        self.assertEqual(cc['k2_aggregate_vs_children']['mismatch'], [])
        self.assertEqual(cc['duplicate_uids'], [])

    def test_prior_claim_o1_thinking_range(self):
        size4 = [u['think'] for u in self.units if u['group'] == 'o1-live1' and u['size'] == 4]
        self.assertEqual(len(size4), 6)
        self.assertEqual((min(size4), max(size4)), (584, 1186))

    def test_prior_claim_fixed_input(self):
        fixed = []
        for u in self.units:
            if u['group'] in ('step4-live1', 'step4-live2', 'step4-live3', 'o1-live1') and u['inu'] is not None:
                f = T.split_tokens(u, self.fits)['fixed_in']
                if f is not None:
                    fixed.append(f)
        self.assertEqual(len(fixed), 42)
        self.assertTrue(2160 <= min(fixed) and max(fixed) <= 2200)
        # H cannot exceed its own byte length in tokens
        self.assertEqual({u['sys_bytes'] for u in self.units if u['sys_bytes']}, {1590})

    def test_only_o1_is_model_needed_and_nothing_qualifies(self):
        needed = {c['cell'][0] for c in self.cells if c['model_needed']}
        self.assertEqual(needed, {'o1-repair-handoff-20/live1'})
        self.assertEqual([r for r in T.qualify(self.cells) if r['qualifies']], [])
        o1 = [c for c in self.cells if c['model_needed']]
        self.assertLess(max(T.share(c, 'thinking')[0] for c in o1), T.THRESHOLD)

    def test_host_scan_flags_the_recomputing_ops_and_not_o1(self):
        scan = T.host_scan(self.man)
        by = {(r['scope'], r['op']): r['flag'] for r in scan}
        self.assertTrue(by[('step4/inspection-handoff-20-v3', 'model.extract@1')])
        self.assertTrue(by[('step4/inspection-handoff-20-v3', 'model.bounds@1')])
        self.assertFalse(by[('o1/repair-handoff-20-v1', 'model.repair_core@1')])
        self.assertFalse(by[('o1/repair-handoff-20-v1', 'model.repair_adapter@1')])

    def test_results_document_is_what_the_script_regenerates(self):
        text = T.render(self.man, self.units, self.fits, self.cells, self.runs)
        self.assertEqual(RESULTS.read_text(encoding='utf-8'), text)
        self.assertNotIn('—', text)
        self.assertNotIn('–', text)

    def test_changed_file_is_refused(self):
        man = dict(self.man)
        man['entries'] = [dict(e) for e in self.man['entries']]
        man['entries'][0]['sha256'] = '0' * 64
        self.assertTrue(T.verify_manifest(man))


if __name__ == '__main__':
    unittest.main()
