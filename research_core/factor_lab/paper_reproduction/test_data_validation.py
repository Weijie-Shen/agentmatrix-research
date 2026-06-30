from __future__ import annotations

import unittest

import pandas as pd

from research_core.factor_lab.paper_reproduction.data_validation import (
    DataFrameValidationRequest,
    validate_input_frame,
)
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


if __name__ == "__main__":
    unittest.main()
