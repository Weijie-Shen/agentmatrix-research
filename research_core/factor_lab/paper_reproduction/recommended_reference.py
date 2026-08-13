from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Sequence

import numpy as np
import pandas as pd

from research_core.factor_lab.paper_reproduction.recommended_data import (
    RecommendedDataConfig,
    normalize_recommended_symbol,
)


RECOMMENDED_INDEX_LEVELS_FILE = "standard_index_daily_levels.parquet"
RECOMMENDED_TRADING_CALENDAR_FILE = "trading_calendar.parquet"
RECOMMENDED_YIELD_CURVE_FILE = "china_government_yield_curve.parquet"
RECOMMENDED_INDEX_COMPONENTS_DIR = "index_components_rqdata"
RECOMMENDED_INDEX_WEIGHTS_MONTHLY_DIR = "index_weights_monthly_rqdata"
RECOMMENDED_INDEX_WEIGHTS_DAILY_DIR = "index_weights_daily_rqdata"

IndexWeightFrequency = Literal["monthly", "daily"]


def load_recommended_trading_calendar(
    *,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    config: RecommendedDataConfig | None = None,
) -> pd.DataFrame:
    data_config = config or RecommendedDataConfig.from_env()
    path = data_config.path(RECOMMENDED_TRADING_CALENDAR_FILE)
    frame = _read_parquet_slice(
        path,
        columns=["trade_date"],
        filters=[
            ("trade_date", ">=", pd.Timestamp(start_date)),
            ("trade_date", "<=", pd.Timestamp(end_date)),
        ],
    )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    frame = frame.sort_values("trade_date", kind="stable").drop_duplicates().reset_index(drop=True)
    frame.attrs["trading_calendar_selection"] = {
        "source_file": str(path),
        "market": "cn",
        "date_range": [pd.Timestamp(start_date).date().isoformat(), pd.Timestamp(end_date).date().isoformat()],
        "horizon_policy": "map T+h on the exchange calendar, not surviving security observations",
    }
    return frame


def materialize_calendar_forward_return(
    frame: pd.DataFrame,
    horizon: int,
    *,
    trading_calendar: pd.DataFrame | Sequence[object],
    price_col: str = "close",
    output_col: str | None = None,
    date_col: str = "date",
    security_col: str = "code",
    copy: bool = True,
) -> pd.DataFrame:
    """Materialize a forward return at exact exchange-calendar date ``T+h``."""

    if horizon <= 0:
        raise ValueError("horizon must be a positive integer")
    missing = [column for column in (date_col, security_col, price_col) if column not in frame.columns]
    if missing:
        raise ValueError(f"calendar forward return inputs are missing columns: {missing}")
    calendar_dates = _calendar_dates(trading_calendar)
    if len(calendar_dates) <= horizon:
        raise ValueError("trading calendar does not contain enough dates for the requested horizon")
    mapping = pd.DataFrame(
        {
            "__formation_date": calendar_dates[:-horizon],
            "__target_date": calendar_dates[horizon:],
        }
    )
    result = frame.copy() if copy else frame
    result[date_col] = pd.to_datetime(result[date_col])
    result["__paper_row_order"] = np.arange(len(result))
    working = result.merge(mapping, left_on=date_col, right_on="__formation_date", how="left")
    future = result[[security_col, date_col, price_col]].rename(
        columns={date_col: "__target_date", price_col: "__future_price"}
    )
    working = working.merge(future, on=[security_col, "__target_date"], how="left", validate="many_to_one")
    column = output_col or f"forward_return_{horizon}d"
    working[column] = pd.to_numeric(working["__future_price"], errors="coerce").div(
        pd.to_numeric(working[price_col], errors="coerce")
    ).sub(1)
    working = working.sort_values("__paper_row_order", kind="stable")
    result[column] = working[column].to_numpy()
    result.drop(columns=["__paper_row_order"], inplace=True)
    result.attrs["forward_return_lineage"] = {
        "field": column,
        "horizon": horizon,
        "horizon_unit": "exchange_trading_days",
        "target_rule": "T+h from canonical China exchange calendar",
        "price_col": price_col,
        "missing_target_price_policy": "remain_missing",
    }
    return result


def materialize_natural_month_forward_return(
    frame: pd.DataFrame,
    horizon: int,
    *,
    trading_calendar: pd.DataFrame | Sequence[object],
    price_col: str = "close",
    output_col: str | None = None,
    date_col: str = "date",
    security_col: str = "code",
    copy: bool = True,
) -> pd.DataFrame:
    """Materialize returns to the last exchange date of a following natural month.

    ``horizon=1`` maps every formation date in month ``M`` to the final
    exchange trading date in month ``M + 1``. Target dates come from the
    supplied exchange calendar, never from a security's surviving prices, so
    a missing target price remains missing.
    """

    if horizon <= 0:
        raise ValueError("horizon must be a positive integer")
    missing = [column for column in (date_col, security_col, price_col) if column not in frame.columns]
    if missing:
        raise ValueError(f"natural-month forward return inputs are missing columns: {missing}")

    calendar_dates = _calendar_dates(trading_calendar)
    calendar_months = calendar_dates.to_period("M")
    month_ends = (
        pd.DataFrame({"__calendar_month": calendar_months, "__target_date": calendar_dates})
        .groupby("__calendar_month", sort=False, as_index=False)["__target_date"]
        .max()
    )
    mapping = pd.DataFrame(
        {
            "__formation_date": calendar_dates,
            "__target_month": calendar_months + horizon,
        }
    ).merge(
        month_ends,
        left_on="__target_month",
        right_on="__calendar_month",
        how="left",
        validate="many_to_one",
    )

    result = frame.copy() if copy else frame
    row_order_col = "__paper_reproduction_row_order__"
    while row_order_col in result.columns:
        row_order_col += "_"
    formation_date_col = "__paper_reproduction_formation_date__"
    while formation_date_col in result.columns:
        formation_date_col += "_"
    result[row_order_col] = np.arange(len(result))
    result[formation_date_col] = pd.to_datetime(result[date_col], errors="coerce")
    working = result.merge(
        mapping[["__formation_date", "__target_date"]],
        left_on=formation_date_col,
        right_on="__formation_date",
        how="left",
        validate="many_to_one",
    )
    future = result[[security_col, formation_date_col, price_col]].rename(
        columns={formation_date_col: "__target_date", price_col: "__future_price"}
    )
    working = working.merge(future, on=[security_col, "__target_date"], how="left", validate="many_to_one")
    column = output_col or f"forward_return_{horizon}m"
    working[column] = pd.to_numeric(working["__future_price"], errors="coerce").div(
        pd.to_numeric(working[price_col], errors="coerce")
    ).sub(1)
    working = working.sort_values(row_order_col, kind="stable")
    result[column] = working[column].to_numpy()
    result.drop(columns=[row_order_col, formation_date_col], inplace=True)
    result.attrs["forward_return_lineage"] = {
        "field": column,
        "horizon": horizon,
        "horizon_unit": "natural_month",
        "target_rule": "last exchange trading date of the Nth following natural month",
        "price_col": price_col,
        "calendar_date_count": len(calendar_dates),
        "calendar_date_range": [calendar_dates[0].date().isoformat(), calendar_dates[-1].date().isoformat()],
        "missing_target_price_policy": "remain_missing",
    }
    return result


def load_recommended_index_levels(
    *,
    index_ids: Sequence[str],
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    config: RecommendedDataConfig | None = None,
) -> pd.DataFrame:
    selected = tuple(dict.fromkeys(_normalize_index_id(value) for value in index_ids))
    if not selected:
        raise ValueError("at least one benchmark index id is required")
    data_config = config or RecommendedDataConfig.from_env()
    path = data_config.path(RECOMMENDED_INDEX_LEVELS_FILE)
    frame = _read_parquet_slice(
        path,
        columns=["order_book_id", "date", "open", "high", "low", "close", "prev_close", "volume", "total_turnover"],
        filters=[
            ("order_book_id", "in", list(selected)),
            ("date", ">=", pd.Timestamp(start_date)),
            ("date", "<=", pd.Timestamp(end_date)),
        ],
    )
    frame = frame.rename(columns={"order_book_id": "index_id"})
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values(["index_id", "date"], kind="stable").reset_index(drop=True)
    frame.attrs["index_reference_selection"] = {
        "dataset": "index_levels",
        "source_file": str(path),
        "index_ids": list(selected),
        "price_basis": "provider_unadjusted",
        "stock_adjustment_policy": "never apply stock QFQ/HFQ multipliers",
    }
    return frame


def load_recommended_index_constituents(
    *,
    index_id: str,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    config: RecommendedDataConfig | None = None,
) -> pd.DataFrame:
    normalized_id = _normalize_index_id(index_id)
    data_config = config or RecommendedDataConfig.from_env()
    directory = data_config.path(RECOMMENDED_INDEX_COMPONENTS_DIR) / _index_directory_name(normalized_id)
    frame = _read_annual_partitions(directory, start_date=start_date, end_date=end_date)
    required = ["index_id", "effective_date", "component_id", "provider_create_tm"]
    _require_columns(frame, required, directory)
    frame["effective_date"] = pd.to_datetime(frame["effective_date"])
    frame = frame[
        (frame["effective_date"] >= pd.Timestamp(start_date))
        & (frame["effective_date"] <= pd.Timestamp(end_date))
    ]
    frame["component_code"] = frame["component_id"].map(normalize_recommended_symbol)
    frame = frame.sort_values(["effective_date", "component_id"], kind="stable").reset_index(drop=True)
    frame.attrs["index_reference_selection"] = {
        "dataset": "index_constituents",
        "source_directory": str(directory),
        "index_id": normalized_id,
        "effective_date_rule": "join on the paper-declared formation/evaluation date",
        "provider_create_tm_role": "ingestion lineage only",
    }
    return frame


def load_recommended_index_weights(
    *,
    index_id: str,
    frequency: IndexWeightFrequency,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    config: RecommendedDataConfig | None = None,
) -> pd.DataFrame:
    if frequency not in {"monthly", "daily"}:
        raise ValueError("index weight frequency must be explicitly 'monthly' or 'daily'")
    normalized_id = _normalize_index_id(index_id)
    data_config = config or RecommendedDataConfig.from_env()
    root_name = (
        RECOMMENDED_INDEX_WEIGHTS_MONTHLY_DIR
        if frequency == "monthly"
        else RECOMMENDED_INDEX_WEIGHTS_DAILY_DIR
    )
    directory = data_config.path(root_name) / _index_directory_name(normalized_id)
    frame = _read_annual_partitions(directory, start_date=start_date, end_date=end_date)
    required = ["index_id", "effective_date", "component_id", "weight", "weight_frequency"]
    _require_columns(frame, required, directory)
    frame["effective_date"] = pd.to_datetime(frame["effective_date"])
    frame = frame[
        (frame["effective_date"] >= pd.Timestamp(start_date))
        & (frame["effective_date"] <= pd.Timestamp(end_date))
    ]
    observed = set(frame["weight_frequency"].dropna().astype(str).str.lower().unique())
    if observed and observed != {frequency}:
        raise ValueError(f"weight-family mismatch: requested {frequency}, observed {sorted(observed)}")
    frame["component_code"] = frame["component_id"].map(normalize_recommended_symbol)
    frame = frame.sort_values(["effective_date", "component_id"], kind="stable").reset_index(drop=True)
    frame.attrs["index_reference_selection"] = {
        "dataset": "index_weights",
        "source_directory": str(directory),
        "index_id": normalized_id,
        "weight_frequency": frequency,
        "semantic_policy": (
            "provider monthly-updated constituent/weight basis"
            if frequency == "monthly"
            else "provider reconstructed daily weights; not equivalent to monthly snapshots"
        ),
        "missing_weight_policy": "preserve missing; do not coerce to zero or renormalize implicitly",
    }
    return frame


def load_recommended_yield_curve(
    *,
    tenors: Sequence[str],
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    config: RecommendedDataConfig | None = None,
) -> pd.DataFrame:
    selected = tuple(dict.fromkeys(str(value).upper() for value in tenors))
    if not selected:
        raise ValueError("at least one government yield-curve tenor is required")
    data_config = config or RecommendedDataConfig.from_env()
    path = data_config.path(RECOMMENDED_YIELD_CURVE_FILE)
    available = set(_parquet_columns(path))
    missing = [tenor for tenor in selected if tenor not in available]
    if missing:
        raise ValueError(f"unsupported yield-curve tenors: {', '.join(missing)}")
    frame = _read_parquet_slice(
        path,
        columns=["date", *selected],
        filters=[
            ("date", ">=", pd.Timestamp(start_date)),
            ("date", "<=", pd.Timestamp(end_date)),
        ],
    )
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date", kind="stable").reset_index(drop=True)
    frame.attrs["yield_curve_selection"] = {
        "source_file": str(path),
        "tenors": list(selected),
        "unit": "decimal_annual_rate",
        "conversion_policy": "record any daily or period conversion explicitly before computing excess returns",
        "missing_policy": "preserve missing tenor observations",
    }
    return frame


def _calendar_dates(calendar: pd.DataFrame | Sequence[object]) -> pd.DatetimeIndex:
    if isinstance(calendar, pd.DataFrame):
        if "trade_date" not in calendar.columns:
            raise ValueError("trading calendar frame must contain trade_date")
        values = calendar["trade_date"]
    else:
        values = list(calendar)
    dates = pd.DatetimeIndex(pd.to_datetime(values, errors="coerce")).dropna().unique().sort_values()
    if dates.empty:
        raise ValueError("trading calendar is empty")
    return dates


def _normalize_index_id(value: object) -> str:
    text = str(value).strip().upper().replace("_", ".")
    if not re.fullmatch(r"[0-9A-Z]+\.(XSHG|XSHE|INDX)", text):
        raise ValueError(f"invalid index id: {value!r}")
    return text


def _index_directory_name(index_id: str) -> str:
    return index_id.replace(".", "_")


def _read_annual_partitions(
    directory: Path,
    *,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
) -> pd.DataFrame:
    if not directory.is_dir():
        raise FileNotFoundError(f"recommended index dataset not found: {directory}")
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    paths = [directory / f"{year}.parquet" for year in range(start.year, end.year + 1)]
    existing = [path for path in paths if path.exists()]
    if not existing:
        raise FileNotFoundError(f"no annual partitions found for requested period in {directory}")
    return pd.concat([pd.read_parquet(path) for path in existing], ignore_index=True)


def _read_parquet_slice(
    path: Path,
    *,
    columns: Sequence[str],
    filters: list[tuple[str, str, object]],
) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"recommended data file not found: {path}")
    _require_columns_from_names(columns, _parquet_columns(path), path)
    try:
        return pd.read_parquet(path, columns=list(columns), filters=filters)
    except Exception:
        frame = pd.read_parquet(path, columns=list(columns))
        for field, operator, value in filters:
            if operator == "<=":
                frame = frame[frame[field] <= value]
            elif operator == ">=":
                frame = frame[frame[field] >= value]
            elif operator == "in":
                frame = frame[frame[field].isin(value)]
            else:
                raise ValueError(f"unsupported fallback filter operator: {operator}")
        return frame


def _parquet_columns(path: Path) -> list[str]:
    try:
        import pyarrow.parquet as pq

        return list(pq.read_schema(path).names)
    except Exception:
        return list(pd.read_parquet(path).columns)


def _require_columns(frame: pd.DataFrame, required: Sequence[str], path: Path) -> None:
    _require_columns_from_names(required, frame.columns, path)


def _require_columns_from_names(required: Sequence[str], available: Sequence[object], path: Path) -> None:
    names = {str(value) for value in available}
    missing = [column for column in required if column not in names]
    if missing:
        raise ValueError(f"missing recommended data columns in {path.name}: {', '.join(missing)}")
