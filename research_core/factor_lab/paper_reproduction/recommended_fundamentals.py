from __future__ import annotations

from pathlib import Path
from typing import Literal, Sequence

import pandas as pd

from research_core.factor_lab.paper_reproduction.recommended_data import (
    RecommendedDataConfig,
    normalize_recommended_symbol,
)


RECOMMENDED_FINANCIAL_STATEMENTS_FILE = "financial_statements_pit_rqdata.parquet"
RECOMMENDED_VALUATION_FACTORS_FILE = "valuation_factors_rqdata.parquet"
RECOMMENDED_DIVIDEND_EVENTS_FILE = "dividend_events_rqdata.parquet"
RECOMMENDED_DIVIDEND_AMOUNT_HISTORY_FILE = "dividend_amount_history_rqdata.parquet"

STATEMENT_KEY_COLUMNS = (
    "symbol",
    "report_period",
    "ann_date",
    "if_adjusted",
    "rice_create_tm",
)
StatementVersionPolicy = Literal["latest_available", "original_only", "all_versions"]
DividendHistoryKind = Literal["events", "amount_history"]


def load_recommended_financial_statements(
    *,
    fields: Sequence[str],
    as_of_date: str | pd.Timestamp,
    symbols: Sequence[str] | None = None,
    report_period_start: str | None = None,
    report_period_end: str | None = None,
    version_policy: StatementVersionPolicy = "latest_available",
    config: RecommendedDataConfig | None = None,
) -> pd.DataFrame:
    """Load point-in-time statement fields without looking through the cutoff.

    The announcement cutoff is applied before selecting a filing version. The
    returned frame has one row per security/report period for
    ``latest_available`` and ``original_only``; ``all_versions`` preserves the
    complete eligible version history.
    """

    selected_fields = tuple(dict.fromkeys(str(field) for field in fields))
    if not selected_fields:
        raise ValueError("at least one financial statement field is required")
    if any(field in STATEMENT_KEY_COLUMNS for field in selected_fields):
        raise ValueError("statement key columns are supplied automatically and must not appear in fields")
    if version_policy not in {"latest_available", "original_only", "all_versions"}:
        raise ValueError(f"unsupported statement version policy: {version_policy}")

    data_config = config or RecommendedDataConfig.from_env()
    path = data_config.path(RECOMMENDED_FINANCIAL_STATEMENTS_FILE)
    columns = [*STATEMENT_KEY_COLUMNS, *selected_fields, "source_dataset", "rqdata_as_of"]
    filters: list[tuple[str, str, object]] = [("ann_date", "<=", pd.Timestamp(as_of_date))]
    if symbols:
        filters.append(("symbol", "in", _provider_symbols(symbols)))
    if report_period_start:
        filters.append(("report_period", ">=", str(report_period_start)))
    if report_period_end:
        filters.append(("report_period", "<=", str(report_period_end)))
    frame = _read_filtered(path, columns=columns, filters=filters)
    frame = _normalize_statement_frame(frame)
    cutoff = pd.Timestamp(as_of_date)
    frame = frame[frame["ann_date"] <= cutoff]
    if version_policy == "original_only":
        frame = frame[frame["if_adjusted"] == 0]
    if version_policy != "all_versions":
        frame = (
            frame.sort_values(
                ["code", "report_period", "ann_date", "rice_create_tm", "if_adjusted"],
                kind="stable",
            )
            .groupby(["code", "report_period"], sort=False, as_index=False)
            .tail(1)
        )
    frame = frame.sort_values(["code", "report_period", "ann_date", "rice_create_tm"], kind="stable")
    frame = frame.reset_index(drop=True)
    frame.attrs["financial_statement_selection"] = {
        "source_file": str(path),
        "fields": list(selected_fields),
        "as_of_date": cutoff.date().isoformat(),
        "version_policy": version_policy,
        "version_key": list(STATEMENT_KEY_COLUMNS),
        "cutoff_rule": "ann_date <= as_of_date before version selection",
        "flow_semantics": "Q2/Q3/Q4 income and cash-flow values are generally fiscal-year-to-date",
    }
    return frame


def load_recommended_valuation_panel(
    *,
    fields: Sequence[str],
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    symbols: Sequence[str] | None = None,
    config: RecommendedDataConfig | None = None,
) -> pd.DataFrame:
    """Load selected daily valuation fields with explicit unit provenance."""

    selected_fields = tuple(dict.fromkeys(str(field) for field in fields))
    if not selected_fields:
        raise ValueError("at least one valuation field is required")
    data_config = config or RecommendedDataConfig.from_env()
    path = data_config.path(RECOMMENDED_VALUATION_FACTORS_FILE)
    columns = ["symbol", "date", *selected_fields, "source_dataset", "rqdata_as_of"]
    filters: list[tuple[str, str, object]] = [
        ("date", ">=", pd.Timestamp(start_date)),
        ("date", "<=", pd.Timestamp(end_date)),
    ]
    if symbols:
        filters.append(("symbol", "in", _provider_symbols(symbols)))
    frame = _read_filtered(path, columns=columns, filters=filters)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["code"] = frame["symbol"].map(normalize_recommended_symbol)
    frame = frame[["date", "code", *selected_fields, "source_dataset", "rqdata_as_of"]]
    frame = frame.sort_values(["code", "date"], kind="stable").reset_index(drop=True)
    frame.attrs["valuation_selection"] = {
        "source_file": str(path),
        "fields": list(selected_fields),
        "date_range": [pd.Timestamp(start_date).date().isoformat(), pd.Timestamp(end_date).date().isoformat()],
        "dividend_yield_unit": "decimal_fraction",
        "raw_dividend_yield_scale": "provider_raw / 10000",
        "provider_ratio_policy": "provider ratios do not replace a differing paper-defined formula",
    }
    return frame


def load_recommended_dividend_history(
    *,
    kind: DividendHistoryKind,
    as_of_date: str | pd.Timestamp,
    symbols: Sequence[str] | None = None,
    config: RecommendedDataConfig | None = None,
) -> pd.DataFrame:
    """Load dividend events using their information-availability date."""

    data_config = config or RecommendedDataConfig.from_env()
    cutoff = pd.Timestamp(as_of_date)
    if kind == "events":
        path = data_config.path(RECOMMENDED_DIVIDEND_EVENTS_FILE)
        info_column = "declaration_announcement_date"
    elif kind == "amount_history":
        path = data_config.path(RECOMMENDED_DIVIDEND_AMOUNT_HISTORY_FILE)
        info_column = "info_date"
    else:
        raise ValueError(f"unsupported dividend history kind: {kind}")
    columns = _parquet_columns(path)
    filters: list[tuple[str, str, object]] = [(info_column, "<=", cutoff)]
    if symbols:
        filters.append(("symbol", "in", _provider_symbols(symbols)))
    frame = _read_filtered(path, columns=columns, filters=filters)
    frame[info_column] = pd.to_datetime(frame[info_column])
    frame = frame[frame[info_column] <= cutoff]
    frame["code"] = frame["symbol"].map(normalize_recommended_symbol)
    frame = frame.sort_values(["code", info_column], kind="stable").reset_index(drop=True)
    frame.attrs["dividend_history_selection"] = {
        "source_file": str(path),
        "kind": kind,
        "as_of_date": cutoff.date().isoformat(),
        "information_date_column": info_column,
        "cutoff_rule": f"{info_column} <= as_of_date",
    }
    return frame


def _normalize_statement_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["ann_date"] = pd.to_datetime(result["ann_date"])
    result["rice_create_tm"] = pd.to_datetime(result["rice_create_tm"])
    result["code"] = result["symbol"].map(normalize_recommended_symbol)
    return result


def _read_filtered(
    path: Path,
    *,
    columns: Sequence[str],
    filters: list[tuple[str, str, object]],
) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"recommended data file not found: {path}")
    available = set(_parquet_columns(path))
    missing = [column for column in columns if column not in available]
    if missing:
        raise ValueError(f"missing recommended data columns in {path.name}: {', '.join(missing)}")
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


def _provider_symbols(symbols: Sequence[str]) -> list[str]:
    values: list[str] = []
    for raw in symbols:
        text = str(raw)
        candidates = [text]
        if text.endswith(".SZ"):
            candidates.append(f"{text[:-3]}.XSHE")
        elif text.endswith(".SH"):
            candidates.append(f"{text[:-3]}.XSHG")
        for candidate in candidates:
            if candidate not in values:
                values.append(candidate)
    return values
