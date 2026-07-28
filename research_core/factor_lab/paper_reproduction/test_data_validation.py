from __future__ import annotations

import unittest

import pandas as pd

from research_core.factor_lab.paper_reproduction.data_validation import (
    DataFrameValidationRequest,
    assess_evaluation_case_support,
    build_data_profile,
    validate_input_frame,
)
from research_core.factor_lab.paper_reproduction.evaluators import get_generic_evaluator_capabilities
from research_core.factor_lab.paper_reproduction.extraction import ExtractedFactor


class PaperInputDataValidationTest(unittest.TestCase):
    def _factor(self) -> ExtractedFactor:
        return ExtractedFactor(
            factor_name="pv_close_to_open",
            formula="(close - open) / open",
            required_fields=["open", "close"],
            frequency="day",
            sample_period="2020-01-01 to 2020-01-04",
            universe="demo stocks",
        )

    def _valid_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-01", "2020-01-02"]),
                "code": ["AAA", "AAA", "BBB", "BBB"],
                "open": [10.0, 10.2, 20.0, 19.8],
                "close": [10.1, 10.0, 19.9, 20.2],
            }
        )

    def test_valid_input_frame_passes_required_columns_unique_keys_and_sorting(self) -> None:
        result = validate_input_frame(self._valid_frame(), DataFrameValidationRequest.from_factor(self._factor()))

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.diagnostics["row_count"], 4)
        self.assertEqual(result.diagnostics["date_count"], 2)
        self.assertEqual(result.diagnostics["code_count"], 2)
        self.assertEqual(result.diagnostics["missing_required_columns"], [])

    def test_missing_required_factor_field_fails(self) -> None:
        frame = self._valid_frame().drop(columns=["close"])

        result = validate_input_frame(frame, DataFrameValidationRequest.from_factor(self._factor()))

        self.assertFalse(result.valid)
        self.assertEqual(result.status, "failed")
        self.assertIn("missing required columns: close", result.errors)

    def test_duplicate_date_code_keys_fail(self) -> None:
        frame = pd.concat([self._valid_frame(), self._valid_frame().iloc[[0]]], ignore_index=True)

        result = validate_input_frame(frame, DataFrameValidationRequest.from_factor(self._factor()))

        self.assertFalse(result.valid)
        self.assertIn("duplicate date-code rows: 2", result.errors)

    def test_unsorted_frame_returns_human_review_warning_not_failure(self) -> None:
        frame = self._valid_frame().iloc[[1, 0, 2, 3]].reset_index(drop=True)

        result = validate_input_frame(frame, DataFrameValidationRequest.from_factor(self._factor()))

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.status, "needs_human_review")
        self.assertIn("frame is not sorted by code,date", result.warnings)

    def test_insufficient_history_for_rolling_window_needs_human_review(self) -> None:
        factor = self._factor()
        factor.parameters = {"window": 5}

        result = validate_input_frame(self._valid_frame(), DataFrameValidationRequest.from_factor(factor))

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.status, "needs_human_review")
        self.assertIn("max history per code 2 is shorter than required lookback 5", result.warnings)

    def test_build_data_profile_records_coverage_missingness_and_duplicates(self) -> None:
        frame = pd.concat([self._valid_frame(), self._valid_frame().iloc[[0]]], ignore_index=True)
        frame.loc[0, "close"] = None

        profile = build_data_profile(frame, source_id="unit_panel")

        self.assertEqual(profile.source_id, "unit_panel")
        self.assertEqual(profile.row_count, 5)
        self.assertEqual(profile.date_min, "2020-01-01")
        self.assertGreater(profile.missingness["close"], 0)
        self.assertEqual(profile.duplicate_key_count, 2)
        self.assertIn("close", profile.field_coverage)

    def test_assess_evaluation_case_support_records_missing_evaluation_field_as_proxy(self) -> None:
        profile = build_data_profile(self._valid_frame(), source_id="unit_panel")
        truth_source = {
            "truth_id": "table_52",
            "evaluation_family": "ic_regression",
            "evaluation_method": "WLS rank IC regression",
            "required_data": {"evaluation": ["forward_return_20d"], "regression_weight": ["free_float_market_cap"]},
            "metrics": {"rank_ic_mean": 0.04, "t_abs_mean": 2.0},
        }

        assessment = assess_evaluation_case_support(
            truth_source,
            profile,
            get_generic_evaluator_capabilities(),
        )

        self.assertEqual(assessment.comparability, "proxy")
        self.assertLess(assessment.support_score, 1.0)
        self.assertTrue(any(item.requirement == "free_float_market_cap" for item in assessment.requirement_results))
        self.assertTrue(assessment.deviations)
        self.assertIn("t_abs_mean", assessment.diagnostic_only_metrics)

    def test_assess_evaluation_case_support_resolves_aliases_sample_and_universe_filters(self) -> None:
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2017-01-03", "2019-04-30"]),
                "code": ["AAA", "AAA"],
                "forward_return_t20": [0.01, 0.02],
                "market_cap": [100.0, 110.0],
                "log_market_cap": [4.6, 4.7],
                "is_st": [0, 0],
                "next_is_suspended": [0, 0],
            }
        )
        profile = build_data_profile(frame, source_id="huatai_like")
        truth_source = {
            "truth_id": "table_52",
            "sample_period": "2010-01-04 to 2019-04-30",
            "universe": "All A-shares; exclude ST/PT and next-day suspended stocks",
            "evaluation_family": "ic_regression",
            "evaluation_method": "T=20 OLS rank IC regression",
            "evaluation_spec": {"return_horizon": 20, "return_col": "forward_return_20d", "regression_type": "ols"},
            "required_data": {
                "evaluation": ["forward_return_20d"],
                "controls": ["market_cap_or_log_market_cap"],
                "filters": ["st_or_pt_status", "next_day_suspension_status"],
            },
            "metrics": {"rank_ic_mean": 0.04, "t_abs_mean": 2.0},
        }

        assessment = assess_evaluation_case_support(truth_source, profile, get_generic_evaluator_capabilities())
        results = {item.requirement: item for item in assessment.requirement_results}

        self.assertEqual(results["forward_return_20d"].available_value, "forward_return_t20")
        self.assertEqual(results["market_cap_or_log_market_cap"].available_value, "log_market_cap")
        self.assertEqual(results["st_or_pt_status"].available_value, "is_st")
        self.assertEqual(results["next_day_suspension_status"].available_value, "next_is_suspended")
        self.assertEqual(results["sample_period"].availability, "partially_available")
        self.assertEqual(assessment.comparability, "materially_comparable")


if __name__ == "__main__":
    unittest.main()
