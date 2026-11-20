"""Regression checks for binary NDCG@k against the full relevant set."""

import math
import unittest

from codegraph_voyage.tests.benchmark import ndcg


class NdcgTests(unittest.TestCase):
    def test_missing_relevant_symbol_lowers_score(self):
        self.assertAlmostEqual(
            ndcg(["d1"], {"d1", "d2"}),
            1 / (1 + 1 / math.log2(3)),
        )

    def test_empty_or_irrelevant_ranking(self):
        self.assertEqual(ndcg([], {"d1"}), 0.0)
        self.assertEqual(ndcg(["other"], {"d1"}), 0.0)
        self.assertEqual(ndcg(["d1"], set()), 0.0)
        self.assertEqual(ndcg([], set()), 0.0)

    def test_relevant_first_fills_ideal(self):
        self.assertEqual(ndcg(["d2", "d1", "other"], {"d1", "d2"}), 1.0)

    def test_cutoff_limits_both_gain_and_ideal(self):
        self.assertEqual(ndcg(["d1"], {"d1", "d2"}, k=1), 1.0)
        self.assertAlmostEqual(
            ndcg(["other", "d1", "d2"], {"d1", "d2", "d3"}, k=2),
            (1 / math.log2(3)) / (1 + 1 / math.log2(3)),
        )
        self.assertEqual(ndcg(["d1", "d2"], {"d1", "d2"}, k=0), 0.0)
        self.assertEqual(ndcg(["d1", "d2"], {"d1", "d2"}, k=-1), 0.0)


if __name__ == "__main__":
    unittest.main()
