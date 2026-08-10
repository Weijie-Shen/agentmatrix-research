from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from research_core.factor_lab.paper_reproduction.factor_frame import align_factor_frame, validate_factor_frame


class FactorFrameContractTest(unittest.TestCase):
    def test_equal_keys_use_fast_path_before_any_merge(self) -> None:
        evaluation = pd.DataFrame(
            {"date": ["2026-01-01", "2026-01-02"], "code": ["A", "A"], "return": [0.1, 0.2]}
        )
        factors = pd.DataFrame(
            {"date": ["2026-01-01", "2026-01-02"], "code": ["A", "A"], "alpha": [1.0, 2.0]}
        )

        with patch.object(pd.DataFrame, "merge", side_effect=AssertionError("merge must not run")):
            result = align_factor_frame(
                evaluation,
                factors,
                key_columns=["date", "code"],
                factor_columns=["alpha"],
            )

        self.assertTrue(result.valid)
        self.assertEqual(result.diagnostics["alignment_method"], "verified_positional_fast_path")
        self.assertTrue(result.diagnostics["outer_key_merge_avoided"])

    def test_shuffled_factor_rows_align_by_keys(self) -> None:
        evaluation = pd.DataFrame(
            {
                "date": ["2026-01-01", "2026-01-01", "2026-01-02"],
                "code": ["A", "B", "A"],
                "forward_return_1d": [0.1, 0.2, 0.3],
            }
        )
        factors = pd.DataFrame(
            {
                "date": ["2026-01-02", "2026-01-01", "2026-01-01"],
                "code": ["A", "B", "A"],
                "alpha": [30.0, 20.0, 10.0],
            }
        )

        result = align_factor_frame(
            evaluation,
            factors,
            key_columns=["date", "code"],
            factor_columns=["alpha"],
        )

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.diagnostics["alignment_method"], "one_to_one_key_join")
        self.assertEqual(result.aligned_frame["alpha"].tolist(), [10.0, 20.0, 30.0])

    def test_duplicate_factor_keys_are_blocking(self) -> None:
        factors = pd.DataFrame(
            {
                "date": ["2026-01-01", "2026-01-01"],
                "code": ["A", "A"],
                "alpha": [1.0, 2.0],
            }
        )

        validation = validate_factor_frame(
            factors,
            key_columns=["date", "code"],
            factor_columns=["alpha"],
        )

        self.assertFalse(validation.valid)
        self.assertIn("duplicate keys", validation.errors[0])

    def test_unmatched_keys_and_factor_nulls_are_nonblocking_limitations(self) -> None:
        evaluation = pd.DataFrame(
            {
                "date": ["2026-01-01", "2026-01-02"],
                "code": ["A", "A"],
                "forward_return_1d": [0.1, 0.2],
            }
        )
        factors = pd.DataFrame(
            {"date": ["2026-01-01"], "code": ["A"], "alpha": [1.0]}
        )

        result = align_factor_frame(
            evaluation,
            factors,
            key_columns=["date", "code"],
            factor_columns=["alpha"],
        )

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.execution_status, "completed_with_limitations")
        self.assertEqual(result.diagnostics["left_only_rows"], 1)
        self.assertTrue(pd.isna(result.aligned_frame.loc[1, "alpha"]))

    def test_evaluation_inputs_cannot_override_artifact_factor_column(self) -> None:
        evaluation = pd.DataFrame(
            {"date": ["2026-01-01"], "code": ["A"], "alpha": [999.0]}
        )
        factors = pd.DataFrame(
            {"date": ["2026-01-01"], "code": ["A"], "alpha": [1.0]}
        )

        result = align_factor_frame(
            evaluation,
            factors,
            key_columns=["date", "code"],
            factor_columns=["alpha"],
        )

        self.assertFalse(result.valid)
        self.assertIn("must not contain artifact factor columns", result.errors[0])


if __name__ == "__main__":
    unittest.main()
