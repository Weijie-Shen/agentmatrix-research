from __future__ import annotations

import unittest

import pandas as pd

from research_core.factor_lab.paper_reproduction.resource_execution import (
    ResourceExecutionConfig,
    certify_security_partition,
    combine_partition_evaluation_rows,
    estimate_resource_preflight,
    incremental_data_hash,
    plan_security_partitions,
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
        self.assertIn("full-history security partitions", result.limitations[0])

    def test_incremental_hash_is_stable_and_content_sensitive(self) -> None:
        calculation, _ = self._frames()
        narrow = calculation[["date", "code", "close"]]
        first = incremental_data_hash([("calculation", narrow)], chunk_rows=17)
        second = incremental_data_hash([("calculation", narrow)], chunk_rows=17)
        changed = narrow.copy()
        changed.loc[0, "close"] = -1.0

        self.assertEqual(first, second)
        self.assertNotEqual(first, incremental_data_hash([("calculation", changed)], chunk_rows=17))

    def test_security_partition_plan_preserves_full_date_range_per_partition(self) -> None:
        plan = plan_security_partitions(
            ["S3", "S1", "S2", "S1"],
            requested_start="2004-10-01",
            requested_end="2017-01-31",
            max_securities_per_partition=2,
        )

        self.assertEqual([item.securities for item in plan], [("S1", "S2"), ("S3",)])
        self.assertEqual({item.requested_start for item in plan}, {"2004-10-01"})
        self.assertEqual({item.requested_end for item in plan}, {"2017-01-31"})

    def test_partition_certification_hashes_coverage_and_signal_only_rows(self) -> None:
        spec = plan_security_partitions(
            ["S1", "S2"],
            requested_start="2026-01-01",
            requested_end="2026-01-05",
            max_securities_per_partition=2,
        )[0]
        calculation = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"] * 2),
                "code": ["S1"] * 3 + ["S2"] * 3,
                "factor": range(6),
            }
        )
        signal_dates = ["2026-01-02", "2026-01-05"]
        evaluation = combine_partition_evaluation_rows([calculation], signal_dates=signal_dates)

        record = certify_security_partition(
            spec,
            calculation,
            evaluation,
            signal_dates=signal_dates,
            source_identity={"scenario": "qfq"},
        )

        self.assertTrue(record.coverage_complete)
        self.assertEqual(record.calculation_row_count, 6)
        self.assertEqual(record.evaluation_row_count, 4)
        self.assertEqual(record.signal_date_count, 2)
        self.assertEqual(len(record.calculation_hash), 64)
        self.assertEqual(len(record.evaluation_hash), 64)

    def test_partition_certification_rejects_history_split_by_unassigned_security(self) -> None:
        spec = plan_security_partitions(
            ["S1"],
            requested_start="2026-01-01",
            requested_end="2026-01-02",
            max_securities_per_partition=1,
        )[0]
        calculation = pd.DataFrame(
            {"date": pd.to_datetime(["2026-01-01"]), "code": ["S2"], "factor": [1.0]}
        )

        with self.assertRaisesRegex(ValueError, "unassigned securities"):
            certify_security_partition(spec, calculation, calculation.iloc[0:0], signal_dates=[])


if __name__ == "__main__":
    unittest.main()
