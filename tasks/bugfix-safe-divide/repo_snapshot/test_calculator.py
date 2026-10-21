import unittest

from calculator import safe_divide


class SafeDivideTests(unittest.TestCase):
    def test_divides_nonzero_values(self) -> None:
        self.assertEqual(safe_divide(9, 3), 3)

    def test_zero_denominator_returns_none(self) -> None:
        self.assertIsNone(safe_divide(9, 0))


if __name__ == "__main__":
    unittest.main()
