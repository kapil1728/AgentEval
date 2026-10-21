import unittest

from duration import format_duration


class FormatDurationTests(unittest.TestCase):
    def test_formats_zero_seconds(self) -> None:
        self.assertEqual(format_duration(0), "0s")

    def test_formats_minutes_and_remaining_seconds(self) -> None:
        self.assertEqual(format_duration(125), "2m 5s")


if __name__ == "__main__":
    unittest.main()
