import unittest
from review_terminal import parse_rows


class ReviewTerminalTests(unittest.TestCase):
    def test_parse_single_rows_and_ranges(self):
        self.assertEqual(parse_rows("1,3,5-7", 10), [1, 3, 5, 6, 7])

    def test_parse_rejects_out_of_range_rows(self):
        with self.assertRaises(ValueError):
            parse_rows("1-11", 10)

    def test_parse_rejects_malformed_ranges(self):
        with self.assertRaises(ValueError):
            parse_rows("2-x", 10)


if __name__ == "__main__":
    unittest.main()
