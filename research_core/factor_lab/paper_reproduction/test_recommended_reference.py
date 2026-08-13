from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from research_core.factor_lab.paper_reproduction.data_validation import build_data_profile
from research_core.factor_lab.paper_reproduction.recommended_data import RecommendedDataConfig
from research_core.factor_lab.paper_reproduction.recommended_reference import (
    load_recommended_index_constituents,
    load_recommended_index_levels,
    load_recommended_index_weights,
    load_recommended_trading_calendar,
    load_recommended_yield_curve,
    materialize_calendar_forward_return,
)


class RecommendedReferenceTest(unittest.TestCase):
    def test_calendar_forward_return_uses_exchange_date_not_next_security_observation(self) -> None:
        calendar = pd.DataFrame({"trade_date": pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])})
        panel = pd.DataFrame(
            {
                "date": pd.to_datetime(["2020-01-02", "2020-01-06", "2020-01-02", "2020-01-03"]),
                "code": ["A", "A", "B", "B"],
                "close": [10.0, 12.0, 20.0, 22.0],
            }
        )

        result = materialize_calendar_forward_return(panel, 1, trading_calendar=calendar)

        self.assertTrue(np.isnan(result.loc[result["code"] == "A", "forward_return_1d"].iloc[0]))
        self.assertAlmostEqual(result.loc[result["code"] == "B", "forward_return_1d"].iloc[0], 0.1)
        profile = build_data_profile(result)
        lineage = next(item for item in profile.derived_fields if item["field"] == "forward_return_1d")
        self.assertEqual(lineage["horizon_unit"], "exchange_trading_days")

    def test_loads_calendar_index_levels_constituents_and_explicit_weight_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_reference_fixture(root)
            config = RecommendedDataConfig(data_dir=root)

            calendar = load_recommended_trading_calendar(
                start_date="2020-01-02", end_date="2020-01-03", config=config
            )
            levels = load_recommended_index_levels(
                index_ids=("000300.XSHG",), start_date="2020-01-02", end_date="2020-01-03", config=config
            )
            constituents = load_recommended_index_constituents(
                index_id="000300.XSHG", start_date="2020-01-02", end_date="2020-01-03", config=config
            )
            monthly = load_recommended_index_weights(
                index_id="000300.XSHG",
                frequency="monthly",
                start_date="2020-01-02",
                end_date="2020-01-03",
                config=config,
            )

            self.assertEqual(len(calendar), 2)
            self.assertEqual(levels["index_id"].unique().tolist(), ["000300.XSHG"])
            self.assertEqual(constituents["component_code"].unique().tolist(), ["000001.SZ"])
            self.assertEqual(monthly.attrs["index_reference_selection"]["weight_frequency"], "monthly")

    def test_weight_family_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write_reference_fixture(root, monthly_label="daily")

            with self.assertRaisesRegex(ValueError, "weight-family mismatch"):
                load_recommended_index_weights(
                    index_id="000300.XSHG",
                    frequency="monthly",
                    start_date="2020-01-02",
                    end_date="2020-01-03",
                    config=RecommendedDataConfig(data_dir=root),
                )

    def test_yield_curve_requires_explicit_supported_tenor_and_preserves_unit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            pd.DataFrame(
                {"date": pd.to_datetime(["2020-01-02"]), "1Y": [0.025], "10Y": [0.03]}
            ).to_parquet(root / "china_government_yield_curve.parquet", index=False)

            curve = load_recommended_yield_curve(
                tenors=("1Y",),
                start_date="2020-01-02",
                end_date="2020-01-02",
                config=RecommendedDataConfig(data_dir=root),
            )

            self.assertEqual(curve["1Y"].tolist(), [0.025])
            self.assertEqual(curve.attrs["yield_curve_selection"]["unit"], "decimal_annual_rate")

    def _write_reference_fixture(self, root: Path, *, monthly_label: str = "monthly") -> None:
        pd.DataFrame(
            {"trade_date": pd.to_datetime(["2020-01-02", "2020-01-03"])}
        ).to_parquet(root / "trading_calendar.parquet", index=False)
        pd.DataFrame(
            {
                "order_book_id": ["000300.XSHG", "000300.XSHG"],
                "date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.5, 101.5],
                "prev_close": [99.5, 100.5],
                "volume": [1.0, 2.0],
                "total_turnover": [10.0, 20.0],
            }
        ).to_parquet(root / "standard_index_daily_levels.parquet", index=False)
        component_dir = root / "index_components_rqdata" / "000300_XSHG"
        component_dir.mkdir(parents=True)
        pd.DataFrame(
            {
                "index_id": ["000300.XSHG", "000300.XSHG"],
                "effective_date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
                "component_id": ["000001.XSHE", "000001.XSHE"],
                "provider_create_tm": pd.to_datetime(["2019-12-01", "2019-12-01"]),
            }
        ).to_parquet(component_dir / "2020.parquet", index=False)
        for family, label in (("index_weights_monthly_rqdata", monthly_label), ("index_weights_daily_rqdata", "daily")):
            weight_dir = root / family / "000300_XSHG"
            weight_dir.mkdir(parents=True)
            pd.DataFrame(
                {
                    "index_id": ["000300.XSHG", "000300.XSHG"],
                    "effective_date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
                    "component_id": ["000001.XSHE", "000001.XSHE"],
                    "weight": [1.0, 1.0],
                    "weight_frequency": [label, label],
                }
            ).to_parquet(weight_dir / "2020.parquet", index=False)


if __name__ == "__main__":
    unittest.main()
