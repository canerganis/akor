import itertools
import unittest

from support import load_module

m = load_module("packB/ranges.py")


class RangeTests(unittest.TestCase):
    def test_compaction_exhaustively(self):
        pairs = [[a, b] for a in range(-2, 3) for b in range(a, 3)]
        for length in range(3):
            for combination in itertools.product(pairs, repeat=length):
                ranges = [pair[:] for pair in combination]
                values = sorted({x for a, b in ranges for x in range(a, b + 1)})
                expected = []
                for value in values:
                    if expected and value == expected[-1][1] + 1:
                        expected[-1][1] = value
                    else:
                        expected.append([value, value])
                self.assertEqual(m.compact_ranges(ranges), expected)
                self.assertEqual(m.covered_count(ranges), len(values))
                self.assertEqual(ranges, list(combination))

    def test_containment_bounds_and_shift(self):
        ranges = [[5, 7], [-2, 0]]
        for value in range(-3, 9):
            self.assertEqual(m.contains(ranges, value), value in {-2, -1, 0, 5, 6, 7})
        self.assertEqual(m.bounding_range(ranges), [-2, 7])
        self.assertIsNone(m.bounding_range([]))
        self.assertFalse(m.contains([], 0))
        self.assertEqual(m.shift_ranges(ranges, -2), [[3, 5], [-4, -2]])
        self.assertEqual(m.shift_ranges([], 5), [])
        shifted = m.shift_ranges(ranges, 0)
        shifted[0][0] = 100
        compacted = m.compact_ranges(ranges)
        compacted[0][0] = 100
        self.assertEqual(ranges, [[5, 7], [-2, 0]])

    def test_invalid_ranges(self):
        for bad in [[], [1], [1, 2, 3], [2, 1]]:
            for function in [m.compact_ranges, m.covered_count, m.bounding_range,
                             lambda data: m.contains(data, 0),
                             lambda data: m.shift_ranges(data, 1)]:
                with self.assertRaises(ValueError):
                    function([[0, 0], bad])
