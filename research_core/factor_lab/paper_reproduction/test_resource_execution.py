from __future__ import annotations

import unittest

import pandas as pd

from research_core.factor_lab.paper_reproduction.resource_execution import (
    ResourceExecutionConfig,
    estimate_resource_preflight,
    incremental_data_hash,
)


class ResourceExecutionTest(unittest.TestCase):
    def test_resource_config_rejects_invalid_budget(self) -> None:
        with self.assertRaisesRegex(ValueError, "memory_budget_bytes"):
            ResourceExecutionConfig(memory_budget_bytes=0)

    def _frames(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        calculation = pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=100),
                "code": [f"S{index:04d}" for index in range(100)],
                "close": [float(index) for index in range(100)],
                "unused_payload": ["x" * 2_000 for _ in range(100)],
            }
        )
        evaluation = calculation[["date", "code"]].copy()
        evaluation["forward_return_1d"] = 0.01
        evaluation["unused_evaluation_payload"] = ["y" * 2_000 for _ in range(100)]
        return calculation, evaluation

    def test_preflight_selects_projected_bounded_mode_without_methodology_change(self) -> None:
        calculation, evaluation = self._frames()
        unconstrained = estimate_resource_preflight(
            calculation,
            evaluation,
            calculation_columns=["date", "code", "close"],
            evaluation_columns=["date", "code", "forward_return_1d"],
            factor_output_columns=["alpha"],
            selected_case_count=1,
        )
        budget = (unconstrained.estimated_standard_peak_bytes + unconstrained.estimated_projected_peak_bytes) // 2

        bounded = estimate_resource_preflight(
            calculation,
            evaluation,
            calculation_columns=["date", "code", "close"],
            evaluation_columns=["date", "code", "forward_return_1d"],
            factor_output_columns=["alpha"],
            selected_case_count=1,
            config=ResourceExecutionConfig(memory_budget_bytes=budget),
        )

        self.assertEqual(bounded.execution_mode, "resource_bounded_projected")
        self.assertTrue(bounded.within_budget)
        self.assertFalse(bounded.partition_required)
        self.assertEqual(bounded.methodological_deviations, [])
        self.assertLess(bounded.projected_calculation_bytes, bounded.calculation_source_bytes)
        self.assertLess(bounded.projected_evaluation_bytes, bounded.evaluation_source_bytes)

    def test_preflight_requires_partitions_instead_of_silently_shortening_sample(self) -> None:
        calculation, evaluation = self._frames()

        result = estimate_resource_preflight(
            calculation,
            evaluation,
            calculation_columns=["date", "code", "close"],
            evaluation_columns=["date", "code", "forward_return_1d"],
            factor_output_columns=["alpha"],
            selected_case_count=1,
            config=ResourceExecutionConfig(memory_budget_bytes=1),
        )

        self.assertEqual(result.execution_mode, "partition_required")
        self.assertTrue(result.partition_required)
        self.assertIn("rather than shortening the sample", result.limitations[0])

    def test_incremental_hash_is_stable_and_content_sensitive(self) -> None:
        calculation, _ = self._frames()
        narrow = calculation[["date", "code", "close"]]
        first = incremental_data_hash([("calculation", narrow)], chunk_rows=17)
        second = incremental_data_hash([("calculation", narrow)], chunk_rows=17)
        changed = narrow.copy()
        changed.loc[0, "close"] = -1.0

        self.assertEqual(first, second)
        self.assertNotEqual(first, incremental_data_hash([("calculation", changed)], chunk_rows=17))


if __name__ == "__main__":
    unittest.main()
