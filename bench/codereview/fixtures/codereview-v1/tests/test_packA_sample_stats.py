import unittest

from support import load_module

m = load_module("packA/sample_stats.py")


class SampleStatsTests(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(m.mean([]))
        self.assertIsNone(m.spread([]))
        self.assertEqual(m.latest([], 2), [])
        self.assertEqual(m.centered([]), [])
        self.assertEqual(m.describe([]), {"count": 0, "mean": None, "spread": None})

    def test_summaries(self):
        for values, average, width in [
            ([4], 4.0, 0.0), ([1, 2, 6], 3.0, 5.0),
            ([-1000000, 1000000], 0.0, 2000000.0),
            ([1000000, 0.25, -1000000], 0.25 / 3, 2000000.0),
        ]:
            self.assertEqual(m.mean(values), average)
            self.assertEqual(m.spread(values), width)
            self.assertEqual(m.describe(values),
                             {"count": len(values), "mean": average, "spread": width})
        self.assertEqual(m.centered([1, 2, 6]), [-2.0, -1.0, 3.0])

    def test_latest_and_copy(self):
        values = [1, 2, 3]
        for limit, expected in [(0, []), (1, [3.0]), (3, [1.0, 2.0, 3.0]),
                                (9, [1.0, 2.0, 3.0])]:
            result = m.latest(values, limit)
            self.assertEqual(result, expected)
            self.assertIsNot(result, values)
        m.centered(values)
        m.describe(values)
        self.assertEqual(values, [1, 2, 3])
        with self.assertRaises(ValueError):
            m.latest(values, -1)

    def test_validation_in_every_entry_point(self):
        for value in [float("nan"), float("inf"), -float("inf"), 1000001, -1000001]:
            for function in [m.mean, m.spread, m.describe, m.centered,
                             lambda data: m.latest(data, 0)]:
                with self.assertRaises(ValueError):
                    function([value])
