from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.factor_lab.paper_reproduction.recommended_data import (
    RecommendedDataConfig,
    apply_a_share_recommended_filters,
    build_recommended_price_view,
    load_recommended_data_manifest,
    load_recommended_paper_panels,
    normalize_recommended_daily_kline_frame,
    normalize_recommended_market_cap_frame,
    normalize_recommended_symbol,
    recommended_data_available,
    resolve_recommended_data_sources,
)


class RecommendedDataHelperTest(unittest.TestCase):
    def test_manifest_and_availability_use_raw_rqdata_kline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_fixture_data(root)
            config = RecommendedDataConfig(data_dir=root)

            self.assertTrue(recommended_data_available(config))
            sources = resolve_recommended_data_sources(config)
            self.assertEqual(sources.daily_prices.name, "kline_raw_rqdata.parquet")
            self.assertTrue(sources.uses_integrated_kline_status)

            manifest = load_recommended_data_manifest(config)
            kline = manifest.loc[manifest["file"] == "kline_raw_rqdata.parquet"].iloc[0]
            self.assertTrue(kline["present_on_disk"])

    def test_normalize_preserves_raw_prices_and_derives_raw_vwap(self) -> None:
        raw = self._raw_fixture_frame()

        panel = normalize_recommended_daily_kline_frame(raw)

        self.assertEqual(panel.loc[0, "code"], "000001.SZ")
        self.assertEqual(panel.loc[0, "open"], 10.0)
        self.assertEqual(panel.loc[0, "vwap"], 10.5)
        self.assertTrue(panel.loc[0, "is_trading"])
        self.assertFalse(panel.loc[4, "is_trading"])
        self.assertTrue(np.isnan(panel.loc[4, "vwap"]))
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(panel["date"]))

    def test_builds_end_anchored_qfq_and_initial_baseline_hfq(self) -> None:
        raw = normalize_recommended_daily_kline_frame(self._raw_fixture_frame())

        qfq = build_recommended_price_view(
            raw,
            price_view="qfq",
            adjustment_end_date="2020-01-03",
        )
        hfq = build_recommended_price_view(raw, price_view="hfq")

        first_two_qfq = qfq.loc[qfq["code"] == "000001.SZ"].head(2)
        first_two_hfq = hfq.loc[hfq["code"] == "000001.SZ"].head(2)
        np.testing.assert_allclose(first_two_qfq["open"], [5.0, 6.0])
        np.testing.assert_allclose(first_two_qfq["vwap"], [5.25, 6.5])
        np.testing.assert_allclose(first_two_hfq["open"], [10.0, 12.0])
        np.testing.assert_allclose(first_two_hfq["vwap"], [10.5, 13.0])
        np.testing.assert_allclose(first_two_qfq["open_raw"], [10.0, 6.0])
        self.assertEqual(qfq["price_adjustment"].unique().tolist(), ["qfq"])
        self.assertEqual(hfq["price_adjustment"].unique().tolist(), ["hfq"])
        self.assertEqual(qfq.attrs["adjustment_anchor_date"], "2020-01-03")
        self.assertEqual(qfq.loc[0, "adjustment_anchor_observation_date"], pd.Timestamp("2020-01-03"))

    def test_load_paper_panels_returns_both_views_from_one_raw_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_fixture_data(root)

            views = load_recommended_paper_panels(
                test_end_date="2020-01-03",
                start_date="2020-01-02",
                end_date="2020-01-03",
                symbols=["000001.SZ", "000002.SZ"],
                include_status=True,
                include_market_cap=True,
                include_industry=True,
                config=RecommendedDataConfig(data_dir=root),
            )

            self.assertEqual(set(views), {"qfq", "hfq"})
            self.assertEqual(len(views["qfq"]), 4)
            self.assertEqual(views["qfq"]["price_adjustment"].unique().tolist(), ["qfq"])
            self.assertEqual(views["hfq"]["price_adjustment"].unique().tolist(), ["hfq"])
            self.assertIn("next_is_suspended", views["qfq"].columns)
            self.assertTrue(views["qfq"].loc[views["qfq"]["code"] == "000001.SZ", "next_is_suspended"].iloc[-1])
            self.assertEqual(views["qfq"].loc[views["qfq"]["code"] == "000001.SZ", "market_cap"].tolist(), [100.0, 110.0])
            self.assertEqual(views["qfq"].loc[views["qfq"]["code"] == "000001.SZ", "industry"].unique().tolist(), ["bank"])

    def test_direct_qfq_load_requires_an_explicit_or_requested_end_anchor(self) -> None:
        raw = normalize_recommended_daily_kline_frame(self._raw_fixture_frame())
        with self.assertRaisesRegex(ValueError, "adjustment_end_date"):
            build_recommended_price_view(raw, price_view="qfq")

    def test_filter_removes_nonobservations_zero_volume_st_and_next_suspension(self) -> None:
        panel = pd.DataFrame(
            {
                "code": ["good", "missing", "zero", "st", "next_suspended"],
                "has_price_observation": [True, False, True, True, True],
                "is_trading": [True, False, False, True, True],
                "is_st": [False, False, False, True, False],
                "is_suspended": [False, True, False, False, False],
                "next_is_suspended": [False, False, False, False, True],
            }
        )

        filtered = apply_a_share_recommended_filters(panel)

        self.assertEqual(filtered["code"].tolist(), ["good"])

    def test_market_cap_and_symbol_normalization_remain_compatible(self) -> None:
        raw = pd.DataFrame(
            {"market_cap": [100.0]},
            index=pd.MultiIndex.from_tuples(
                [("000001.XSHE", "2020-01-02")],
                names=["order_book_id", "date"],
            ),
        )

        normalized = normalize_recommended_market_cap_frame(raw)

        self.assertEqual(normalized["code"].tolist(), ["000001.SZ"])
        self.assertEqual(normalize_recommended_symbol("600000.XSHG"), "600000.SH")

    def _write_fixture_data(self, root: Path) -> None:
        raw = self._raw_fixture_frame()
        raw.to_parquet(root / "kline_raw_rqdata.parquet", index=False)
        (root / "MANIFEST.json").write_text(
            json.dumps([{"file": "kline_raw_rqdata.parquet", "rows": len(raw)}]),
            encoding="utf-8",
        )
        pd.DataFrame(
            {
                "symbol": ["000001.XSHE", "000001.XSHE", "000002.XSHE", "000002.XSHE"],
                "trade_date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-02", "2020-01-03"]),
                "market_cap": [100.0, 110.0, 200.0, 210.0],
            }
        ).to_parquet(root / "market_cap.parquet", index=False)
        pd.DataFrame(
            {
                "symbol": ["000001.XSHE", "000002.XSHE"],
                "industry": ["bank", "property"],
            }
        ).to_parquet(root / "industry_map.parquet", index=False)

    def _raw_fixture_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "symbol": [
                    "000001.XSHE",
                    "000001.XSHE",
                    "000001.XSHE",
                    "000002.XSHE",
                    "000002.XSHE",
                    "000002.XSHE",
                ],
                "trade_date": pd.to_datetime(
                    ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-02", "2020-01-03", "2020-01-06"]
                ),
                "open": [10.0, 6.0, np.nan, 20.0, 21.0, 22.0],
                "high": [11.0, 7.0, np.nan, 21.0, 22.0, 22.0],
                "low": [9.0, 5.0, np.nan, 19.0, 20.0, 22.0],
                "close": [10.5, 6.5, np.nan, 20.5, 21.5, 22.0],
                "volume": [1000.0, 2000.0, np.nan, 1000.0, 0.0, 1000.0],
                "amount": [10500.0, 13000.0, np.nan, 20500.0, 0.0, 22000.0],
                "num_trades": [10.0, 20.0, np.nan, 10.0, 0.0, 10.0],
                "limit_up": [11.5, 7.0, np.nan, 22.5, 23.0, 24.0],
                "limit_down": [9.5, 5.0, np.nan, 18.5, 19.0, 20.0],
                "prev_close": [9.8, 5.5, np.nan, 19.5, 20.5, 21.5],
                "ex_factor": [1.0, 2.0, 1.0, 1.0, 1.0, 1.0],
                "ex_cum_factor": [1.0, 2.0, 2.0, 1.5, 1.5, 1.5],
                "factor_ex_date": pd.to_datetime([None, "2020-01-03", "2020-01-03", "2019-01-01", "2019-01-01", "2019-01-01"]),
                "has_factor_event": [False, True, False, False, False, False],
                "is_st": [False, False, False, False, False, False],
                "is_suspended": [False, False, True, False, False, False],
                "has_price_observation": [True, True, False, True, True, True],
            }
        )


if __name__ == "__main__":
    unittest.main()
