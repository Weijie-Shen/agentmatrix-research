from __future__ import annotations

import os
import unittest

import pandas as pd

from research_core.factor_lab.paper_reproduction.quant_api import (
    QuantApiConfig,
    normalize_quant_daily_kline_frame,
)


class QuantApiIntegrationHelperTest(unittest.TestCase):
    def test_config_reads_token_from_environment_without_exposing_it(self) -> None:
        old_value = os.environ.get("QUANT_API_TOKEN")
        os.environ["QUANT_API_TOKEN"] = "sk-test-token"
        try:
            config = QuantApiConfig.from_env()
        finally:
            if old_value is None:
                os.environ.pop("QUANT_API_TOKEN", None)
            else:
                os.environ["QUANT_API_TOKEN"] = old_value

        self.assertEqual(config.base_url, "http://115.159.73.134:8765")
        self.assertEqual(config.headers(), {"Authorization": "Bearer sk-test-token"})
        self.assertNotIn("sk-test-token", repr(config))

    def test_normalize_quant_daily_kline_frame_maps_common_columns_to_factor_lab_panel(self) -> None:
        raw = pd.DataFrame(
            {
                "trade_date": ["2020-01-02", "2020-01-02"],
                "symbol": ["000001.SZ", "000002.SZ"],
                "open": [10.0, 20.0],
                "high": [10.5, 20.5],
                "low": [9.8, 19.8],
                "close": [10.2, 20.2],
                "volume": [1000, 2000],
                "total_turnover": [10200.0, 40400.0],
            }
        )

        panel = normalize_quant_daily_kline_frame(raw)

        self.assertEqual(panel.columns.tolist(), ["date", "code", "open", "high", "low", "close", "volume", "amount"])
        self.assertEqual(panel["code"].tolist(), ["000001.SZ", "000002.SZ"])
        self.assertEqual(panel["amount"].tolist(), [10200.0, 40400.0])
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(panel["date"]))

    def test_normalize_quant_daily_kline_frame_requires_amount_candidate(self) -> None:
        raw = pd.DataFrame(
            {
                "trade_date": ["2020-01-02"],
                "symbol": ["000001.SZ"],
                "open": [10.0],
                "high": [10.5],
                "low": [9.8],
                "close": [10.2],
                "volume": [1000],
            }
        )

        with self.assertRaises(ValueError) as ctx:
            normalize_quant_daily_kline_frame(raw)

        self.assertIn("amount column not found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
