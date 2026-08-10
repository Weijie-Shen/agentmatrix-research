from __future__ import annotations

import unittest

import pandas as pd

from research_core.factor_lab.paper_reproduction.methodology import apply_universe_protocol


class UniverseProtocolExecutionTest(unittest.TestCase):
    def _frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": ["2026-01-02"] * 4,
                "code": ["A", "B", "C", "D"],
                "is_st": [0, 1, 0, 0],
                "next_is_suspended": [0, 0, 1, None],
            }
        )

    def _protocol(self) -> dict[str, object]:
        return {
            "filters": [
                {
                    "filter_name": "exclude_st_pt",
                    "resolved_field": "is_st",
                    "application_stage": "factor_cross_section",
                    "operator": "falsy",
                    "missing_policy": "exclude",
                },
                {
                    "filter_name": "exclude_next_day_suspension",
                    "resolved_field": "next_is_suspended",
                    "application_stage": "factor_cross_section",
                    "operator": "falsy",
                    "missing_policy": "exclude",
                },
            ]
        }

    def test_evaluation_filters_apply_at_factor_cross_section_stage(self) -> None:
        result = apply_universe_protocol(self._frame(), self._protocol(), stage="factor_cross_section")

        self.assertEqual(result.frame["code"].tolist(), ["A"])
        self.assertEqual(result.diagnostics["removed_rows"], 3)
        self.assertEqual([item["filter_name"] for item in result.applied_filters], ["exclude_st_pt", "exclude_next_day_suspension"])

    def test_evaluation_filters_do_not_modify_factor_time_series_stage(self) -> None:
        result = apply_universe_protocol(self._frame(), self._protocol(), stage="factor_time_series")

        self.assertEqual(len(result.frame), 4)
        self.assertEqual(result.applied_filters, [])

    def test_missing_filter_field_is_a_visible_nonblocking_limitation(self) -> None:
        protocol = self._protocol()
        protocol["filters"][0]["resolved_field"] = "missing_st_field"

        result = apply_universe_protocol(self._frame(), protocol, stage="factor_cross_section")

        self.assertTrue(result.limitations)
        self.assertEqual(result.skipped_filters[0]["reason"], "missing_filter_field")


if __name__ == "__main__":
    unittest.main()
