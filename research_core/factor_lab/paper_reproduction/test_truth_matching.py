from __future__ import annotations

import unittest

from research_core.factor_lab.paper_reproduction.extraction import ExtractedTruthSource
from research_core.factor_lab.paper_reproduction.truth_matching import (
    compare_evaluation_metrics_to_paper_truth,
    interpret_truth_match_quality,
)


class PaperTruthMatchingTest(unittest.TestCase):
    def test_evaluation_metric_truth_match_passes_within_tolerance(self) -> None:
        truth = ExtractedTruthSource(
            truth_id="table_3_eval",
            truth_type="evaluation_results",
            metrics={"rank_ic_mean": 0.042, "rank_ic_ir": 0.31},
        )
        computed = {"rank_ic_mean": 0.0420000001, "rank_ic_ir": 0.31}

        result = compare_evaluation_metrics_to_paper_truth(computed, truth, tolerance=1e-6)

        self.assertTrue(result.passed, result.diagnostics)
        self.assertEqual(result.status, "exact_match")
        self.assertEqual(result.diagnostics["matched_metrics"], ["rank_ic_mean", "rank_ic_ir"])

    def test_evaluation_metric_truth_match_fails_when_metric_missing(self) -> None:
        truth = ExtractedTruthSource(
            truth_id="table_3_eval",
            truth_type="evaluation_results",
            metrics={"rank_ic_mean": 0.042, "rank_ic_ir": 0.31},
        )
        computed = {"rank_ic_mean": 0.042}

        result = compare_evaluation_metrics_to_paper_truth(computed, truth)

        self.assertFalse(result.passed)
        self.assertEqual(result.status, "inconsistent")
        self.assertEqual(result.diagnostics["missing_metrics"], ["rank_ic_ir"])

    def test_evaluation_metric_truth_can_be_acceptable_when_direction_and_relative_error_are_reasonable(self) -> None:
        truth = ExtractedTruthSource(
            truth_id="table_3_eval",
            truth_type="evaluation_results",
            metrics={"rank_ic_mean": 0.04, "rank_ic_ir": 0.30},
        )
        computed = {"rank_ic_mean": 0.038, "rank_ic_ir": 0.28}

        result = compare_evaluation_metrics_to_paper_truth(computed, truth, tolerance=1e-6, relative_tolerance=0.1)

        self.assertFalse(result.passed)
        self.assertEqual(result.status, "approximately_consistent")
        self.assertEqual(result.diagnostics["quality"], "approximately_consistent")
        self.assertEqual(result.diagnostics["sign_match_ratio"], 1.0)

    def test_proxy_case_cannot_be_labeled_exact_match(self) -> None:
        truth = ExtractedTruthSource(
            truth_id="table_52_eval",
            truth_type="evaluation_results",
            metrics={"rank_ic_mean": 0.04},
        )
        computed = {"rank_ic_mean": 0.04}

        result = compare_evaluation_metrics_to_paper_truth(
            computed,
            truth,
            resolved_evaluation_case={
                "comparability": "proxy",
                "truth_match_eligible_metrics": ["rank_ic_mean"],
                "diagnostic_only_metrics": [],
            },
        )

        self.assertFalse(result.passed)
        self.assertEqual(result.status, "directionally_consistent")

    def test_truth_quality_interpreter_separates_passed_acceptable_and_failed(self) -> None:
        self.assertEqual(interpret_truth_match_quality(True, {}), "exact_match")
        self.assertEqual(
            interpret_truth_match_quality(
                False,
                {
                    "missing_metrics": [],
                    "matched_metrics": ["rank_ic_mean"],
                    "within_relative_tolerance_metrics": ["rank_ic_mean"],
                    "sign_match_ratio": 1.0,
                },
            ),
            "approximately_consistent",
        )
        self.assertEqual(
            interpret_truth_match_quality(
                False,
                {
                    "missing_metrics": ["rank_ic_ir"],
                    "matched_metrics": ["rank_ic_mean"],
                    "within_relative_tolerance_metrics": ["rank_ic_mean"],
                    "sign_match_ratio": 1.0,
                },
            ),
            "inconsistent",
        )


if __name__ == "__main__":
    unittest.main()
