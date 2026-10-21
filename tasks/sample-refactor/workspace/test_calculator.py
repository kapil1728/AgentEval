import unittest

from calculator import calculate_total


class CalculateTotalTests(unittest.TestCase):
    def test_sums_values(self) -> None:
        self.assertEqual(calculate_total([3, 4, 5]), 12)

    def test_empty_values(self) -> None:
        self.assertEqual(calculate_total([]), 0)


if __name__ == "__main__":
    unittest.main()
