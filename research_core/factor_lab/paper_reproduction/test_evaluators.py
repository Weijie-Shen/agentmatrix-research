from __future__ import annotations

import math
import unittest

import pandas as pd

from research_core.factor_lab.paper_reproduction.evaluators import (
    apply_transform_spec,
    compute_cross_sectional_regression,
    compute_ic_analysis,
    evaluate_paper_case,
)


class PaperReproductionEvaluatorsTest(unittest.TestCase):
    def _base_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": ["2020-01-01"] * 4 + ["2020-01-02"] * 4,
                "code": ["A", "B", "C", "D"] * 2,
                "factor": [1.0, 2.0, 3.0, 100.0, 2.0, 4.0, 6.0, 8.0],
                "forward_return_1d": [0.01, 0.02, 0.03, 0.04, 0.08, 0.06, 0.04, 0.02],
                "industry": ["x", "x", "y", "y"] * 2,
                "market_cap": [10.0, 20.0, 10.0, 20.0] * 2,
            }
        )

    def test_apply_transform_spec_winsorizes_and_zscores_by_date(self) -> None:
        frame = self._base_frame()
        transformed = apply_transform_spec(
            frame,
            value_col="factor",
            transform_spec={
                "steps": [
                    {"name": "winsorization", "method": "median_mad", "threshold": 1},
                    {"name": "standardization", "method": "cross_section_zscore"},
                ]
            },
        )

        first_date = transformed.loc[transformed["date"] == "2020-01-01", "processed_factor"]
        self.assertAlmostEqual(float(first_date.mean()), 0.0, places=12)
        self.assertAlmostEqual(float(first_date.std(ddof=0)), 1.0, places=12)
        self.assertLess(float(first_date.max()), 2.0)

    def test_apply_transform_spec_neutralizes_market_cap_by_date(self) -> None:
        frame = self._base_frame()
        transformed = apply_transform_spec(
            frame,
            value_col="factor",
            transform_spec={
                "steps": [
                    {
                        "name": "neutralization",
                        "method": "cross_sectional_regression_residual",
                        "controls": ["market_cap"],
                    }
                ]
            },
        )

        for _, group in transformed.groupby("date"):
            corr = group["processed_factor"].corr(group["market_cap"])
            self.assertTrue(pd.isna(corr) or abs(float(corr)) < 1e-10)

    def test_compute_ic_analysis_reports_rank_ic_metrics(self) -> None:
        frame = self._base_frame()
        result = compute_ic_analysis(
            frame,
            factor_col="factor",
            return_col="forward_return_1d",
            method="spearman",
        )

        self.assertEqual(result["cross_section_count"], 2)
        self.assertAlmostEqual(result["rank_ic_mean"], 0.0, places=12)
        self.assertAlmostEqual(result["rank_ic_std"], math.sqrt(2), places=12)
        self.assertAlmostEqual(result["ic_positive_ratio"], 0.5, places=12)

    def test_evaluate_paper_case_dispatches_ic_analysis(self) -> None:
        frame = self._base_frame()
        case = {
            "case_id": "demo_ic",
            "evaluation_family": "ic_analysis",
            "evaluation_spec": {"ic_type": "spearman_rank_ic"},
            "transform_spec": {"steps": [{"name": "standardization", "method": "cross_section_zscore"}]},
            "required_data": {"evaluation": ["forward_return_1d"]},
        }

        result = evaluate_paper_case(case, frame, factor_col="factor")

        self.assertEqual(result["case_id"], "demo_ic")
        self.assertEqual(result["evaluation_family"], "ic_analysis")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["metrics"]["cross_section_count"], 2)

    def test_evaluate_paper_case_treats_null_optional_specs_as_empty(self) -> None:
        frame = self._base_frame()
        case = {
            "case_id": "demo_null_specs",
            "evaluation_family": "ic_analysis",
            "evaluation_spec": None,
            "transform_spec": None,
            "required_data": None,
        }

        result = evaluate_paper_case(case, frame, factor_col="factor")

        self.assertEqual(result["case_id"], "demo_null_specs")
        self.assertEqual(result["return_col"], "forward_return_1d")
        self.assertFalse(result["transform_applied"])
        self.assertEqual(result["metrics"]["cross_section_count"], 2)

    def test_evaluate_paper_case_rejects_unknown_ic_type(self) -> None:
        frame = self._base_frame()
        case = {
            "case_id": "demo_bad_ic",
            "evaluation_family": "ic_analysis",
            "evaluation_spec": {"ic_type": "kendall"},
            "required_data": {"evaluation": ["forward_return_1d"]},
        }

        with self.assertRaisesRegex(ValueError, "Unsupported IC type: kendall"):
            evaluate_paper_case(case, frame, factor_col="factor")


    def test_compute_cross_sectional_regression_reports_t_and_factor_return_metrics(self) -> None:
        frame = pd.DataFrame(
            {
                "date": ["2020-01-01"] * 4 + ["2020-01-02"] * 4,
                "code": ["A", "B", "C", "D"] * 2,
                "factor": [1.0, 2.0, 3.0, 4.0, 2.0, 3.0, 4.0, 5.0],
                "forward_return_1d": [0.03, 0.05, 0.07, 0.09, 0.01, 0.02, 0.03, 0.04],
                "market_cap": [10.0, 20.0, 30.0, 40.0] * 2,
            }
        )

        result = compute_cross_sectional_regression(
            frame,
            factor_col="factor",
            return_col="forward_return_1d",
            controls=[],
        )

        self.assertEqual(result["cross_section_count"], 2)
        self.assertAlmostEqual(result["factor_return_mean"], 0.015, places=12)
        self.assertGreater(result["t_abs_mean"], 2.0)
        self.assertEqual(result["t_abs_gt_2_ratio"], 1.0)

    def test_evaluate_paper_case_dispatches_ic_regression_with_controls(self) -> None:
        frame = self._base_frame()
        case = {
            "case_id": "demo_regression",
            "evaluation_family": "ic_regression",
            "evaluation_spec": {
                "return_col": "forward_return_1d",
                "regression_controls": ["market_cap"],
                "regression_type": "ols",
            },
            "transform_spec": {"steps": []},
            "required_data": {"evaluation": ["forward_return_1d"], "controls": ["market_cap"]},
        }

        result = evaluate_paper_case(case, frame, factor_col="factor")

        self.assertEqual(result["case_id"], "demo_regression")
        self.assertEqual(result["evaluation_family"], "ic_regression")
        self.assertEqual(result["status"], "passed")
        self.assertIn("regression", result["metrics"])
        self.assertIn("ic", result["metrics"])
        self.assertEqual(result["metrics"]["regression"]["cross_section_count"], 2)

    def test_evaluate_paper_case_executes_resolved_protocol_instead_of_paper_protocol(self) -> None:
        frame = self._base_frame().rename(columns={"forward_return_1d": "forward_return_t20"})
        case = {
            "case_id": "wls_paper_ols_runtime",
            "source_truth_id": "table_52",
            "evaluation_family": "ic_regression",
            "evaluation_spec": {
                "return_col": "forward_return_20d",
                "regression_type": "wls",
                "weight_col": "sqrt_free_float_market_cap",
            },
            "required_data": {"evaluation": ["forward_return_20d"], "regression_weight": ["sqrt_free_float_market_cap"]},
            "resolved_protocol": {
                "evaluation_family": "ic_regression",
                "evaluation_spec": {
                    "return_col": "forward_return_t20",
                    "regression_type": "ols",
                    "weight_col": None,
                    "regression_controls": ["market_cap"],
                },
                "required_data": {"evaluation": ["forward_return_t20"], "controls": ["market_cap"]},
                "transform_spec": {"steps": []},
            },
        }

        result = evaluate_paper_case(case, frame, factor_col="factor")

        self.assertEqual(result["source_truth_id"], "table_52")
        self.assertEqual(result["return_col"], "forward_return_t20")
        self.assertEqual(result["resolved_parameters"]["evaluation_spec"]["regression_type"], "ols")
        self.assertEqual(result["metrics"]["regression"]["weight_col"], None)


if __name__ == "__main__":
    unittest.main()
