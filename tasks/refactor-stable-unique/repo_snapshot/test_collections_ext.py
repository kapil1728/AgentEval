import unittest

from collections_ext import unique_items


class UniqueItemsTests(unittest.TestCase):
    def test_keeps_first_seen_order(self) -> None:
        self.assertEqual(unique_items(["c", "a", "c", "b", "a"]), ["c", "a", "b"])

    def test_empty_input(self) -> None:
        self.assertEqual(unique_items([]), [])


if __name__ == "__main__":
    unittest.main()
