import unittest

from bounds import clamp


class ClampTests(unittest.TestCase):
    def test_clamps_below_lower_bound(self) -> None:
        self.assertEqual(clamp(-3, 0, 10), 0)

    def test_keeps_values_inside_bounds(self) -> None:
        self.assertEqual(clamp(4, 0, 10), 4)

    def test_clamps_above_upper_bound(self) -> None:
        self.assertEqual(clamp(14, 0, 10), 10)


if __name__ == "__main__":
    unittest.main()
