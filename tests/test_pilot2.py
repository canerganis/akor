import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'bench' / 'live'))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pilot2 as P

SEED = 3005


def lines(prompt):
    return prompt.rstrip('\n').split('\n')


class Pilot2Test(unittest.TestCase):
    def test_per_job_packets(self):
        plain = lines(P.calls(SEED, 'J')[0][1])
        entries = P.calls(SEED, 'P')
        self.assertEqual(len(entries), 16)
        for i, entry in enumerate(entries):
            ls = lines(entry[1])
            self.assertEqual(ls[:2], plain[:2])
            self.assertEqual(ls[-1], plain[-1])
            self.assertEqual(len([l for l in ls if l.startswith('ma_')]), 1)
            msg = next(l for l in ls if l.startswith('ma_'))
            self.assertTrue(msg.startswith(f'ma_{i + 1:02d} '))
            refs = json.loads(ls[3])
            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0][0], int(re.search(r'[Rr]eference (\d+)', msg).group(1)))

    def test_job_union_matches_batch(self):
        union = [j for e in P.calls(SEED, 'P') for j in e[5]]
        self.assertEqual(union, P.calls(SEED, 'J')[0][5])

    def test_subagent_arm(self):
        s, j = P.calls(SEED, 'S')[0], P.calls(SEED, 'J')[0]
        self.assertEqual(s[2], 'Agent')
        self.assertTrue(s[1].endswith(j[1]))

    def test_judge(self):
        system, prompt, tools, dec, native, js = P.calls(SEED, 'P')[0]
        want = P.M.X.oracle(js[0][0], int(js[0][1:]))
        good = json.dumps({'results': [['ma_01', 0, json.dumps(want)]]})
        self.assertEqual(P.judge(dec, good, js, native), ('', 1))
        wrong_id = json.dumps({'results': [['ma_02', 0, json.dumps(want)]]})
        err, ok = P.judge(dec, wrong_id, js, native)
        self.assertTrue(err)
        self.assertEqual(ok, 0)
        failed = json.dumps({'results': [['ma_01', 2, 'cannot']]})
        self.assertEqual(P.judge(dec, failed, js, native), ('', 0))
        err, ok = P.judge(dec, '{not json', js, native)
        self.assertTrue(err)
        self.assertEqual(ok, 0)

    def test_deterministic(self):
        for arm in 'HJPS':
            a = [(c[0], c[1], c[2]) for c in P.calls(SEED, arm)]
            b = [(c[0], c[1], c[2]) for c in P.calls(SEED, arm)]
            self.assertEqual(a, b)


if __name__ == '__main__':
    unittest.main()
