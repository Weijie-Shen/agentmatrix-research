from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research_core.factor_lab.paper_reproduction.recommended_data import RecommendedDataConfig
from research_core.factor_lab.paper_reproduction.recommended_fundamentals import (
    load_recommended_dividend_history,
    load_recommended_financial_statements,
    load_recommended_valuation_panel,
)


class RecommendedFundamentalsTest(unittest.TestCase):
    def test_statement_cutoff_precedes_latest_version_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_statement_fixture(root)

            frame = load_recommended_financial_statements(
                fields=("total_assets", "net_profit"),
                as_of_date="2020-06-30",
                symbols=("000001.SZ",),
                version_policy="latest_available",
                config=RecommendedDataConfig(data_dir=root),
            )

            self.assertEqual(frame["report_period"].tolist(), ["2019q4", "2020q1"])
            self.assertEqual(frame["total_assets"].tolist(), [110.0, 120.0])
            self.assertLessEqual(frame["ann_date"].max(), pd.Timestamp("2020-06-30"))
            self.assertEqual(
                frame.attrs["financial_statement_selection"]["cutoff_rule"],
                "ann_date <= as_of_date before version selection",
            )

    def test_original_only_does_not_select_adjusted_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_statement_fixture(root)

            frame = load_recommended_financial_statements(
                fields=("total_assets",),
                as_of_date="2021-12-31",
                version_policy="original_only",
                config=RecommendedDataConfig(data_dir=root),
            )

            self.assertEqual(frame.loc[frame["report_period"] == "2019q4", "total_assets"].item(), 100.0)
            self.assertTrue((frame["if_adjusted"] == 0).all())

    def test_valuation_loader_preserves_decimal_yield_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pd.DataFrame(
                {
                    "symbol": ["000001.XSHE", "000001.XSHE"],
                    "date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
                    "pb_ratio": [1.2, 1.3],
                    "dividend_yield": [0.03, 0.031],
                    "source_dataset": ["rqdatac.get_factor"] * 2,
                    "rqdata_as_of": ["2026-08-10"] * 2,
                }
            ).to_parquet(root / "valuation_factors_rqdata.parquet", index=False)

            frame = load_recommended_valuation_panel(
                fields=("pb_ratio", "dividend_yield"),
                start_date="2020-01-02",
                end_date="2020-01-03",
                symbols=("000001.SZ",),
                config=RecommendedDataConfig(data_dir=root),
            )

            self.assertEqual(frame["code"].unique().tolist(), ["000001.SZ"])
            self.assertEqual(frame.attrs["valuation_selection"]["dividend_yield_unit"], "decimal_fraction")

    def test_dividend_history_filters_by_information_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pd.DataFrame(
                {
                    "symbol": ["000001.XSHE", "000001.XSHE"],
                    "quarter": ["2019q4", "2019q4"],
                    "event_procedure": ["proposal", "implementation"],
                    "info_date": pd.to_datetime(["2020-03-01", "2020-07-01"]),
                    "amount": [10.0, 11.0],
                    "rice_create_tm": pd.to_datetime(["2020-03-02", "2020-07-02"]),
                    "source_dataset": ["rqdata"] * 2,
                    "rqdata_as_of": ["2026-08-10"] * 2,
                }
            ).to_parquet(root / "dividend_amount_history_rqdata.parquet", index=False)

            frame = load_recommended_dividend_history(
                kind="amount_history",
                as_of_date="2020-06-30",
                config=RecommendedDataConfig(data_dir=root),
            )

            self.assertEqual(frame["amount"].tolist(), [10.0])
            self.assertEqual(frame.attrs["dividend_history_selection"]["information_date_column"], "info_date")

    def _write_statement_fixture(self, root: Path) -> None:
        pd.DataFrame(
            {
                "symbol": ["000001.XSHE"] * 5,
                "report_period": ["2019q4", "2019q4", "2019q4", "2020q1", "2020q1"],
                "ann_date": pd.to_datetime(
                    ["2020-03-01", "2020-05-01", "2021-03-01", "2020-04-20", "2020-07-20"]
                ),
                "if_adjusted": [0, 1, 1, 0, 1],
                "rice_create_tm": pd.to_datetime(
                    ["2020-03-02", "2020-05-02", "2021-03-02", "2020-04-21", "2020-07-21"]
                ),
                "total_assets": [100.0, 110.0, 999.0, 120.0, 130.0],
                "net_profit": [10.0, 11.0, 99.0, 12.0, 13.0],
                "source_dataset": ["rqdata"] * 5,
                "rqdata_as_of": ["2026-08-10"] * 5,
            }
        ).to_parquet(root / "financial_statements_pit_rqdata.parquet", index=False)


if __name__ == "__main__":
    unittest.main()
