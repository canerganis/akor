import unittest

from support import load_module

m = load_module("packB/rotation.py")


class RotationTests(unittest.TestCase):
    def test_rotation_exhaustively(self):
        for length in range(7):
            items = list(range(length))
            for offset in range(-15, 16):
                if length:
                    expected = [items[(i + offset) % length] for i in range(length)]
                else:
                    expected = []
                result = m.rotate_left(items, offset)
                self.assertEqual(result, expected)
                self.assertIsNot(result, items)
                self.assertEqual(items, list(range(length)))

    def test_rotation_order(self):
        self.assertEqual(m.rotation_order(["a", "b", "c"], 4), ["b", "c", "a"])
        self.assertEqual(m.rotation_order([], 0), [])
        for workers, number in [(["a"], -1), (["a", "a"], 0)]:
            with self.assertRaises(ValueError):
                m.rotation_order(workers, number)

    def test_assignment(self):
        tasks = [0, 1, 2, 3, 4]
        workers = ["a", "b"]
        self.assertEqual(m.assign_tasks(tasks, workers), {"a": [0, 2, 4], "b": [1, 3]})
        self.assertEqual(m.assign_tasks([], workers), {"a": [], "b": []})
        self.assertEqual(tasks, [0, 1, 2, 3, 4])
        self.assertEqual(workers, ["a", "b"])
        for invalid in [[], ["a", "a"]]:
            with self.assertRaises(ValueError):
                m.assign_tasks([], invalid)

    def test_chunks(self):
        self.assertEqual(m.chunk_tasks([1, 2, 3], 2), [[1, 2], [3]])
        self.assertEqual(m.chunk_tasks([1], 4), [[1]])
        self.assertEqual(m.chunk_tasks([], 2), [])
        for size in [0, -1]:
            with self.assertRaises(ValueError):
                m.chunk_tasks([], size)

    def test_interleave(self):
        for left, right, expected in [
            ([], [], []), ([1], [], [1]), ([], [2], [2]),
            ([1, 3], [2, 4], [1, 2, 3, 4]),
            ([1, 3, 5], [2], [1, 2, 3, 5]),
            ([1], [2, 4, 6], [1, 2, 4, 6]),
        ]:
            saved = (left[:], right[:])
            self.assertEqual(m.interleave(left, right), expected)
            self.assertEqual((left, right), saved)
