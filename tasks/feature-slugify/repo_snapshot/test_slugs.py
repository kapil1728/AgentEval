import unittest

from slugs import slugify


class SlugifyTests(unittest.TestCase):
    def test_normalizes_spaces_and_punctuation(self) -> None:
        self.assertEqual(slugify("AgentEval: Tiny Tasks!"), "agenteval-tiny-tasks")

    def test_collapses_repeated_separators(self) -> None:
        self.assertEqual(slugify("  two   words  "), "two-words")


if __name__ == "__main__":
    unittest.main()
