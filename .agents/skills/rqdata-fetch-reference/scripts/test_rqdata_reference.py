from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd

MODULE_PATH = Path(__file__).with_name("rqdata_reference.py")
SPEC = importlib.util.spec_from_file_location("rqdata_reference", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeProvider:
    def get_trading_dates(self, start_date, end_date, market="cn"):
        return [pd.Timestamp(start_date).date(), pd.Timestamp(end_date).date()]

    def get_price(self, order_book_ids, **kwargs):
        index = pd.MultiIndex.from_product(
            [
                order_book_ids,
                pd.to_datetime([kwargs["start_date"], kwargs["end_date"]]),
            ],
            names=["order_book_id", "date"],
        )
        return pd.DataFrame(
            {field: range(len(index)) for field in kwargs["fields"]},
            index=index,
        )

    def index_components(self, index_id, **kwargs):
        if kwargs.get("date"):
            return (
                ["000001.XSHE", "600000.XSHG"],
                pd.Timestamp("2020-01-02 18:00"),
            )
        return {
            pd.Timestamp(kwargs["start_date"]): (
                ["000001.XSHE"],
                pd.Timestamp("2019-12-31"),
            ),
            pd.Timestamp(kwargs["end_date"]): (
                ["600000.XSHG"],
                pd.Timestamp("2020-01-31"),
            ),
        }

    def index_weights(self, index_id, **kwargs):
        date = kwargs.get("date", kwargs.get("start_date"))
        index = pd.MultiIndex.from_tuples(
            [
                (pd.Timestamp(date), "000001.XSHE"),
                (pd.Timestamp(date), "600000.XSHG"),
            ],
            names=["date", "order_book_id"],
        )
        return pd.DataFrame({"weight": [0.4, 0.6]}, index=index)

    index_weights_ex = index_weights

    def get_yield_curve(self, **kwargs):
        columns = {"1M": [1.5, 1.6], "1Y": [2.1, 2.2]}
        if kwargs.get("tenor"):
            columns = {kwargs["tenor"]: columns[kwargs["tenor"]]}
        return pd.DataFrame(
            columns,
            index=pd.DatetimeIndex(
                [kwargs["start_date"], kwargs["end_date"]], name="date"
            ),
        )


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.provider = FakeProvider()

    def test_date_or_range_is_exclusive(self):
        with self.assertRaisesRegex(ValueError, "date or start/end"):
            MODULE.QueryRequest(
                dataset="index-components",
                index_id="000300.XSHG",
                date="2020-01-01",
                start_date="2020-01-01",
                end_date="2020-01-02",
            ).normalized()

    def test_calendar_schema(self):
        request = MODULE.QueryRequest(
            dataset="calendar",
            start_date="20200101",
            end_date="2020-01-02",
        )
        frame = MODULE.execute_query(request, self.provider)
        self.assertEqual(list(frame.columns), ["trade_date"])
        self.assertEqual(len(frame), 2)

    def test_index_levels_are_keyed(self):
        request = MODULE.QueryRequest(
            dataset="index-levels",
            indices=("000300.XSHG", "000905.XSHG"),
            start_date="2020-01-01",
            end_date="2020-01-02",
            fields=("close",),
        )
        frame = MODULE.execute_query(request, self.provider)
        self.assertFalse(
            frame.duplicated(["order_book_id", "date"]).any()
        )
        self.assertEqual(len(frame), 4)

    def test_components_preserve_effective_and_creation_times(self):
        request = MODULE.QueryRequest(
            dataset="index-components",
            index_id="000300.XSHG",
            date="2020-01-02",
        )
        frame = MODULE.execute_query(request, self.provider)
        self.assertEqual(
            set(frame["component_id"]),
            {"000001.XSHE", "600000.XSHG"},
        )
        self.assertTrue(frame["provider_create_tm"].notna().all())

    def test_weight_frequency_is_explicit(self):
        request = MODULE.QueryRequest(
            dataset="index-weights",
            index_id="000300.XSHG",
            date="2020-01-02",
            weight_frequency="daily",
        )
        frame = MODULE.execute_query(request, self.provider)
        self.assertEqual(set(frame["weight_frequency"]), {"daily"})
        self.assertAlmostEqual(frame["weight"].sum(), 1.0)

    def test_yield_curve_can_select_tenors(self):
        request = MODULE.QueryRequest(
            dataset="yield-curve",
            start_date="2020-01-01",
            end_date="2020-01-02",
            tenors=("1Y",),
        )
        frame = MODULE.execute_query(request, self.provider)
        self.assertEqual(list(frame.columns), ["date", "1Y"])

    def test_arrow_round_trip_preserves_provenance(self):
        frame = pd.DataFrame(
            {"trade_date": pd.to_datetime(["2020-01-02"])}
        )
        frame.attrs["rqdata_provenance"] = {
            "persistence": "none_process_scoped"
        }
        restored = MODULE._frame_from_arrow(MODULE._arrow_bytes(frame))
        self.assertEqual(
            restored.attrs["rqdata_provenance"]["persistence"],
            "none_process_scoped",
        )

    def test_environment_flag_is_strict(self):
        with patch.dict(os.environ, {"RQDATA_REMOTE_SHELL_INIT": "yes"}):
            self.assertTrue(
                MODULE._environment_flag("RQDATA_REMOTE_SHELL_INIT")
            )
        with patch.dict(os.environ, {"RQDATA_REMOTE_SHELL_INIT": "maybe"}):
            with self.assertRaisesRegex(ValueError, "must be one of"):
                MODULE._environment_flag("RQDATA_REMOTE_SHELL_INIT")


if __name__ == "__main__":
    unittest.main()
