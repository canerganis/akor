import unittest

from support import load_module

m = load_module("packA/paging.py")


class PagingTests(unittest.TestCase):
    def test_pages_exhaustively(self):
        for count in range(13):
            items = list(range(count))
            for size in range(1, 6):
                pages = [m.get_page(items, n, size) for n in range(count + 2)]
                self.assertEqual([x for page in pages for x in page], items)
                expected = [items[n:n + size] for n in range(0, count, size)]
                self.assertEqual(pages[:len(expected)], expected)
                self.assertTrue(all(page == [] for page in pages[len(expected):]))
                self.assertEqual(m.page_count(count, size), len(expected))
                self.assertEqual(m.page_sizes(count, size), list(map(len, expected)))

    def test_page_indices_and_labels(self):
        for size in range(1, 5):
            for index in range(20):
                self.assertEqual(m.page_for_index(index, size), index // size)
        self.assertEqual(m.page_label(0, 7, 3), "1 / 3")
        self.assertEqual(m.page_label(2, 7, 3), "3 / 3")
        for args in [(0, 0, 3), (3, 7, 3), (-1, 7, 3)]:
            with self.assertRaises(ValueError):
                m.page_label(*args)

    def test_invalid_arguments(self):
        for size in [0, -1]:
            calls = [
                lambda: m.page_count(3, size), lambda: m.get_page([], 0, size),
                lambda: m.page_for_index(0, size), lambda: m.page_sizes(3, size),
                lambda: m.page_label(0, 3, size),
            ]
            for call in calls:
                with self.assertRaises(ValueError):
                    call()
        for call in [
            lambda: m.page_count(-1, 2), lambda: m.get_page([], -1, 2),
            lambda: m.page_for_index(-1, 2), lambda: m.page_sizes(-1, 2),
            lambda: m.page_label(0, -1, 2),
        ]:
            with self.assertRaises(ValueError):
                call()

    def test_copy_and_no_mutation(self):
        items = ["a", "b"]
        result = m.get_page(items, 0, 9)
        self.assertEqual(items, ["a", "b"])
        self.assertIsNot(result, items)
        result.append("c")
        self.assertEqual(items, ["a", "b"])
