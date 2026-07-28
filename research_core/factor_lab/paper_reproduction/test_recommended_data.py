from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from research_core.factor_lab.paper_reproduction.recommended_data import (
    RecommendedDataConfig,
    add_next_suspension_flag,
    apply_a_share_recommended_filters,
    load_recommended_daily_panel,
    load_recommended_data_manifest,
    normalize_recommended_daily_kline_frame,
    normalize_recommended_market_cap_frame,
    normalize_recommended_security_status_frame,
    normalize_recommended_symbol,
    recommended_data_available,
)


class RecommendedDataHelperTest(unittest.TestCase):
    def test_manifest_and_availability_detect_curated_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "MANIFEST.json").write_text('[{"file": "kline_daily_adjusted.parquet", "rows": 0}]', encoding="utf-8")
            pd.DataFrame({"symbol": []}).to_parquet(root / "kline_daily_adjusted.parquet")
            pd.DataFrame({"order_book_id": [], "date": [], "market_cap": []}).to_parquet(root / "market_cap_2010_2026.parquet")
            config = RecommendedDataConfig(data_dir=root)

            self.assertTrue(recommended_data_available(config))
            manifest = load_recommended_data_manifest(config)
            self.assertEqual(manifest["file"].tolist(), ["kline_daily_adjusted.parquet", "market_cap_2010_2026.parquet"])
            self.assertEqual(manifest.loc[manifest["file"] == "kline_daily_adjusted.parquet", "present_on_disk"].iloc[0], True)
            self.assertEqual(manifest.loc[manifest["file"] == "market_cap_2010_2026.parquet", "source"].iloc[0], "filesystem_detected")

    def test_normalize_recommended_daily_kline_uses_adjusted_prices_by_default(self) -> None:
        raw = pd.DataFrame(
            {
                "symbol": ["000001.SZ"],
                "trade_date": ["2020-01-02"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.0],
                "close": [10.5],
                "volume": [1000],
                "amount": [10500.0],
                "adj_factor": [2.0],
                "open_adj": [20.0],
                "high_adj": [22.0],
                "low_adj": [18.0],
                "close_adj": [21.0],
            }
        )

        panel = normalize_recommended_daily_kline_frame(raw)

        self.assertEqual(panel["code"].tolist(), ["000001.SZ"])
        self.assertEqual(panel["open"].tolist(), [20.0])
        self.assertEqual(panel["close"].tolist(), [21.0])
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(panel["date"]))

    def test_market_cap_symbols_normalize_from_rqdata_suffixes(self) -> None:
        raw = pd.DataFrame(
            {"market_cap": [100.0]},
            index=pd.MultiIndex.from_tuples([("000001.XSHE", "2020-01-02")], names=["order_book_id", "date"]),
        )

        normalized = normalize_recommended_market_cap_frame(raw)

        self.assertEqual(normalized["code"].tolist(), ["000001.SZ"])
        self.assertEqual(normalize_recommended_symbol("600000.XSHG"), "600000.SH")

    def test_load_recommended_daily_panel_joins_status_and_market_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_fixture_data(root)

            panel = load_recommended_daily_panel(
                start_date="2020-01-02",
                end_date="2020-01-02",
                symbols=["000001.SZ", "000002.SZ"],
                include_status=True,
                include_market_cap=True,
                include_industry=True,
                config=RecommendedDataConfig(data_dir=root),
            )

            self.assertEqual(panel["code"].tolist(), ["000001.SZ", "000002.SZ"])
            self.assertIn("is_st", panel.columns)
            self.assertIn("market_cap", panel.columns)
            self.assertIn("industry", panel.columns)
            self.assertEqual(panel.loc[panel["code"] == "000001.SZ", "market_cap"].tolist(), [100.0])
            self.assertEqual(panel.loc[panel["code"] == "000001.SZ", "industry"].tolist(), ["bank"])

    def test_load_recommended_daily_panel_prefers_expanded_market_cap_and_st_status_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_fixture_data(root)
            (root / "market_cap.parquet").unlink()
            pd.DataFrame(
                {
                    "order_book_id": ["000001.XSHE", "000002.XSHE"],
                    "date": pd.to_datetime(["2017-01-03", "2017-01-03"]),
                    "market_cap": [300.0, 400.0],
                }
            ).to_parquet(root / "market_cap_2010_2026.parquet")
            pd.DataFrame(
                {
                    "symbol": ["000001.XSHE", "000002.XSHE"],
                    "trade_date": pd.to_datetime(["2017-01-03", "2017-01-03"]),
                    "is_st": [0, 1],
                }
            ).to_parquet(root / "st_status_full.parquet")
            pd.DataFrame(
                {
                    "symbol": ["000001.SZ", "000002.SZ"],
                    "trade_date": pd.to_datetime(["2017-01-03", "2017-01-03"]),
                    "open": [10.0, 20.0],
                    "high": [11.0, 21.0],
                    "low": [9.0, 19.0],
                    "close": [10.5, 20.5],
                    "volume": [1000, 2000],
                    "amount": [10500.0, 41000.0],
                    "adj_factor": [1.0, 1.0],
                    "open_adj": [10.0, 20.0],
                    "high_adj": [11.0, 21.0],
                    "low_adj": [9.0, 19.0],
                    "close_adj": [10.5, 20.5],
                }
            ).to_parquet(root / "kline_daily_adjusted.parquet")

            panel = load_recommended_daily_panel(
                start_date="2017-01-03",
                end_date="2017-01-03",
                symbols=["000001.SZ", "000002.SZ"],
                include_status=True,
                include_market_cap=True,
                config=RecommendedDataConfig(data_dir=root),
            )

            self.assertEqual(panel["market_cap"].tolist(), [300.0, 400.0])
            self.assertEqual(panel["is_st"].tolist(), [0, 1])
            self.assertTrue(panel["is_suspended"].isna().all())

    def test_load_recommended_daily_panel_uses_2010_2016_st_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_fixture_data(root)
            pd.DataFrame(
                {
                    "symbol": ["000001.SZ", "000002.SZ"],
                    "trade_date": pd.to_datetime(["2010-01-04", "2010-01-04"]),
                    "open": [10.0, 20.0],
                    "high": [11.0, 21.0],
                    "low": [9.0, 19.0],
                    "close": [10.5, 20.5],
                    "volume": [1000, 2000],
                    "amount": [10500.0, 41000.0],
                    "adj_factor": [1.0, 1.0],
                    "open_adj": [10.0, 20.0],
                    "high_adj": [11.0, 21.0],
                    "low_adj": [9.0, 19.0],
                    "close_adj": [10.5, 20.5],
                }
            ).to_parquet(root / "kline_daily_adjusted.parquet")
            pd.DataFrame(
                {
                    "symbol": ["000001.XSHE", "000002.XSHE"],
                    "trade_date": pd.to_datetime(["2010-01-04", "2010-01-04"]),
                    "is_st": [0, 1],
                }
            ).to_parquet(root / "st_status_2010_2016.parquet")

            panel = load_recommended_daily_panel(
                start_date="2010-01-04",
                end_date="2010-01-04",
                symbols=["000001.SZ", "000002.SZ"],
                include_status=True,
                config=RecommendedDataConfig(data_dir=root),
            )

            self.assertEqual(panel["is_st"].tolist(), [0, 1])
            self.assertTrue(panel["is_trading"].isna().all())
            self.assertTrue(panel["is_suspended"].isna().all())

    def test_normalize_st_only_status_frame_keeps_optional_status_columns_missing(self) -> None:
        raw = pd.DataFrame(
            {
                "symbol": ["000001.XSHE"],
                "trade_date": ["2017-01-03"],
                "is_st": [1],
            }
        )

        normalized = normalize_recommended_security_status_frame(raw)

        self.assertEqual(normalized["code"].tolist(), ["000001.SZ"])
        self.assertEqual(normalized["is_st"].tolist(), [1])
        self.assertTrue(pd.isna(normalized.loc[0, "is_trading"]))
        self.assertTrue(pd.isna(normalized.loc[0, "is_suspended"]))

    def test_add_next_suspension_flag_and_a_share_filter_use_next_day_suspension(self) -> None:
        status = pd.DataFrame(
            {
                "date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-02", "2020-01-03"]),
                "code": ["a", "a", "b", "b"],
                "is_suspended": [0, 1, 0, 0],
                "is_st": [0, 0, 0, 0],
                "is_trading": [1, 1, 1, 1],
            }
        )

        with_next = add_next_suspension_flag(status)
        first_day = with_next[with_next["date"] == pd.Timestamp("2020-01-02")]
        filtered = apply_a_share_recommended_filters(first_day)

        self.assertEqual(filtered["code"].tolist(), ["b"])

    def test_apply_a_share_recommended_filters_removes_st_suspended_and_non_trading_rows(self) -> None:
        panel = pd.DataFrame(
            {
                "code": ["a", "b", "c", "d"],
                "is_st": [0, 1, 0, 0],
                "is_suspended": [0, 0, 1, 0],
                "is_trading": [1, 1, 1, 0],
            }
        )

        filtered = apply_a_share_recommended_filters(panel)

        self.assertEqual(filtered["code"].tolist(), ["a"])

    def _write_fixture_data(self, root: Path) -> None:
        pd.DataFrame(
            {
                "symbol": ["000001.SZ", "000002.SZ"],
                "trade_date": pd.to_datetime(["2020-01-02", "2020-01-02"]),
                "open": [10.0, 20.0],
                "high": [11.0, 21.0],
                "low": [9.0, 19.0],
                "close": [10.5, 20.5],
                "volume": [1000, 2000],
                "amount": [10500.0, 41000.0],
                "adj_factor": [1.0, 1.0],
                "open_adj": [10.0, 20.0],
                "high_adj": [11.0, 21.0],
                "low_adj": [9.0, 19.0],
                "close_adj": [10.5, 20.5],
            }
        ).to_parquet(root / "kline_daily_adjusted.parquet")
        pd.DataFrame(
            {
                "symbol": ["000001.SZ", "000002.SZ"],
                "trade_date": pd.to_datetime(["2020-01-02", "2020-01-02"]),
                "is_trading": [1, 1],
                "is_st": [0, 1],
                "is_suspended": [0, 0],
                "high_limited": [0, 0],
                "low_limited": [0, 0],
                "status_code": ["NORMAL", "ST"],
            }
        ).to_parquet(root / "security_status_through_2026-04-09.parquet")
        pd.DataFrame(
            {"market_cap": [100.0, 200.0]},
            index=pd.MultiIndex.from_tuples(
                [("000001.XSHE", pd.Timestamp("2020-01-02")), ("000002.XSHE", pd.Timestamp("2020-01-02"))],
                names=["order_book_id", "date"],
            ),
        ).to_parquet(root / "market_cap.parquet")
        pd.DataFrame(
            {
                "symbol": ["000001.SZ", "000002.SZ"],
                "industry": ["bank", "property"],
            }
        ).to_parquet(root / "industry_map.parquet")


if __name__ == "__main__":
    unittest.main()
