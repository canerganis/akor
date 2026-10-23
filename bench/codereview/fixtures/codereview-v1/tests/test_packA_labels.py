import unittest

from support import load_module

m = load_module("packA/labels.py")


class LabelTests(unittest.TestCase):
    def test_slug(self):
        for source, expected in [
            ("", "item"), ("---", "item"), (" A__B 7 ", "a-b-7"),
            ("Already-good", "already-good"), ("café", "caf"),
            ("éAéBé", "a-b"), ("42", "42"), ("A..-- B", "a-b"),
            ("東京", "item"),
        ]:
            self.assertEqual(m.slug(source), expected)
            self.assertEqual(m.slug(expected), expected)

    def test_uniqueness_and_suffix_collisions(self):
        labels = ["A", "A", "a-2", "", "---", "A"]
        self.assertEqual(m.unique_labels(labels),
                         ["a", "a-2", "a-2-2", "item", "item-2", "a-3"])
        self.assertEqual(m.unique_labels(["x-2", "x", "x"]), ["x-2", "x", "x-3"])
        self.assertEqual(m.unique_labels([]), [])
        self.assertEqual(labels, ["A", "A", "a-2", "", "---", "A"])

    def test_headers(self):
        for delimiter in [",", ";", "\t", "|"]:
            self.assertEqual(m.make_header(["A", "A"], delimiter),
                             delimiter.join(["a", "a-2"]))
        self.assertEqual(m.make_header([]), "")
        self.assertEqual(m.make_header(["A", "B"]), "a,b")
        for delimiter in ["", "::", "\n", "a"]:
            with self.assertRaises(ValueError):
                m.make_header(["A"], delimiter)

    def test_map_and_canonical_check(self):
        self.assertEqual(m.label_map(["A", "a"]), {"a": "A", "a-2": "a"})
        self.assertEqual(m.label_map([]), {})
        for value in ["a", "item", "a-2", "0"]:
            self.assertTrue(m.is_slug(value))
        for value in ["", "A", "-a", "a-", "a--b", "é"]:
            self.assertFalse(m.is_slug(value))
