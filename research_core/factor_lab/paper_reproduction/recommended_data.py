from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_RECOMMENDED_DATA_DIR = Path("/Users/mac/recommended_data")


@dataclass(slots=True)
class RecommendedDataConfig:
    data_dir: Path = DEFAULT_RECOMMENDED_DATA_DIR

    @classmethod
    def from_env(cls, env_var: str = "RECOMMENDED_DATA_DIR") -> RecommendedDataConfig:
        configured = os.environ.get(env_var, "").strip()
        return cls(data_dir=Path(configured).expanduser() if configured else DEFAULT_RECOMMENDED_DATA_DIR)

    def path(self, name: str) -> Path:
        return self.data_dir / name


def recommended_data_available(config: RecommendedDataConfig | None = None) -> bool:
    data_config = config or RecommendedDataConfig.from_env()
    return data_config.path("MANIFEST.csv").exists() and data_config.path("kline_adj.parquet").exists()


def load_recommended_data_manifest(config: RecommendedDataConfig | None = None) -> pd.DataFrame:
    data_config = config or RecommendedDataConfig.from_env()
    path = data_config.path("MANIFEST.csv")
    if not path.exists():
        raise FileNotFoundError(f"recommended data manifest not found: {path}")
    return pd.read_csv(path)


def load_recommended_daily_panel(
    *,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    symbols: list[str] | None = None,
    adjusted: bool = True,
    include_status: bool = False,
    include_market_cap: bool = False,
    config: RecommendedDataConfig | None = None,
) -> pd.DataFrame:
    """Load a Factor Lab-style daily panel from the curated local data folder."""

    data_config = config or RecommendedDataConfig.from_env()
    panel = _read_recommended_kline(
        data_config.path("kline_adj.parquet"),
        start_date=start_date,
        end_date=end_date,
        symbols=symbols,
    )
    panel = normalize_recommended_daily_kline_frame(panel, adjusted=adjusted)

    if include_status:
        status = _read_recommended_status(
            data_config.path("security_status.parquet"),
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
        panel = panel.merge(add_next_suspension_flag(normalize_recommended_security_status_frame(status)), on=["date", "code"], how="left")

    if include_market_cap:
        market_cap = _read_recommended_market_cap(
            data_config.path("market_cap_full.parquet"),
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
        panel = panel.merge(market_cap, on=["date", "code"], how="left")

    return panel.sort_values(["code", "date"]).reset_index(drop=True)


def normalize_recommended_daily_kline_frame(raw_frame: pd.DataFrame, *, adjusted: bool = True) -> pd.DataFrame:
    required = ["symbol", "trade_date", "open", "high", "low", "close", "volume", "amount"]
    missing = [column for column in required if column not in raw_frame.columns]
    if missing:
        raise ValueError(f"missing recommended daily kline columns: {', '.join(missing)}")

    panel = raw_frame.copy()
    if adjusted:
        adjusted_columns = {"open_adj": "open", "high_adj": "high", "low_adj": "low", "close_adj": "close"}
        missing_adjusted = [column for column in adjusted_columns if column not in panel.columns]
        if missing_adjusted:
            raise ValueError(f"missing adjusted price columns: {', '.join(missing_adjusted)}")
        for source, target in adjusted_columns.items():
            panel[target] = panel[source]

    panel = panel.rename(columns={"trade_date": "date", "symbol": "code"})
    panel["date"] = pd.to_datetime(panel["date"])
    columns = ["date", "code", "open", "high", "low", "close", "volume", "amount"]
    optional_columns = [column for column in ("adj_factor", "open_adj", "high_adj", "low_adj", "close_adj") if column in panel.columns]
    return panel[columns + optional_columns]


def normalize_recommended_security_status_frame(raw_frame: pd.DataFrame) -> pd.DataFrame:
    required = ["symbol", "trade_date", "is_trading", "is_st", "is_suspended"]
    missing = [column for column in required if column not in raw_frame.columns]
    if missing:
        raise ValueError(f"missing recommended security status columns: {', '.join(missing)}")
    status = raw_frame.copy().rename(columns={"trade_date": "date", "symbol": "code"})
    status["date"] = pd.to_datetime(status["date"])
    columns = [
        "date",
        "code",
        "is_trading",
        "is_st",
        "is_suspended",
        *[column for column in ("high_limited", "low_limited", "status_code") if column in status.columns],
    ]
    return status[columns]


def normalize_recommended_market_cap_frame(raw_frame: pd.DataFrame) -> pd.DataFrame:
    frame = raw_frame.reset_index() if isinstance(raw_frame.index, pd.MultiIndex) else raw_frame.copy()
    required = ["order_book_id", "date", "market_cap"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"missing recommended market cap columns: {', '.join(missing)}")
    frame["date"] = pd.to_datetime(frame["date"])
    frame["code"] = frame["order_book_id"].map(normalize_recommended_symbol)
    return frame[["date", "code", "market_cap"]]


def add_next_suspension_flag(status_frame: pd.DataFrame) -> pd.DataFrame:
    required = ["date", "code", "is_suspended"]
    missing = [column for column in required if column not in status_frame.columns]
    if missing:
        raise ValueError(f"missing status columns for next suspension flag: {', '.join(missing)}")
    status = status_frame.sort_values(["code", "date"]).copy()
    status["next_is_suspended"] = status.groupby("code")["is_suspended"].shift(-1)
    return status


def apply_a_share_recommended_filters(panel: pd.DataFrame) -> pd.DataFrame:
    """Apply the default all-A-share filters supported by recommended data status columns."""

    result = panel.copy()
    suspension_column = "next_is_suspended" if "next_is_suspended" in result.columns else "is_suspended"
    for column in ("is_st", suspension_column):
        if column in result.columns:
            result = result[result[column].fillna(0).astype(int) == 0]
    if "is_trading" in result.columns:
        result = result[result["is_trading"].fillna(1).astype(int) == 1]
    return result.reset_index(drop=True)


def normalize_recommended_symbol(symbol: Any) -> str:
    text = str(symbol)
    if text.endswith(".XSHE"):
        return f"{text[:-5]}.SZ"
    if text.endswith(".XSHG"):
        return f"{text[:-5]}.SH"
    return text


def _read_recommended_kline(
    path: Path,
    *,
    start_date: str | pd.Timestamp | None,
    end_date: str | pd.Timestamp | None,
    symbols: list[str] | None,
) -> pd.DataFrame:
    columns = [
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adj_factor",
        "open_adj",
        "high_adj",
        "low_adj",
        "close_adj",
    ]
    return _read_parquet_with_filters(path, columns=columns, date_col="trade_date", start_date=start_date, end_date=end_date, symbols=symbols)


def _read_recommended_status(
    path: Path,
    *,
    start_date: str | pd.Timestamp | None,
    end_date: str | pd.Timestamp | None,
    symbols: list[str] | None,
) -> pd.DataFrame:
    columns = ["symbol", "trade_date", "is_trading", "is_st", "is_suspended", "high_limited", "low_limited", "status_code"]
    return _read_parquet_with_filters(path, columns=columns, date_col="trade_date", start_date=start_date, end_date=end_date, symbols=symbols)


def _read_recommended_market_cap(
    path: Path,
    *,
    start_date: str | pd.Timestamp | None,
    end_date: str | pd.Timestamp | None,
    symbols: list[str] | None,
) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame = normalize_recommended_market_cap_frame(frame)
    if start_date is not None:
        frame = frame[frame["date"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        frame = frame[frame["date"] <= pd.Timestamp(end_date)]
    if symbols:
        frame = frame[frame["code"].isin(symbols)]
    return frame


def _read_parquet_with_filters(
    path: Path,
    *,
    columns: list[str],
    date_col: str,
    start_date: str | pd.Timestamp | None,
    end_date: str | pd.Timestamp | None,
    symbols: list[str] | None,
) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"recommended data file not found: {path}")
    filters: list[tuple[str, str, Any]] = []
    if start_date is not None:
        filters.append((date_col, ">=", pd.Timestamp(start_date)))
    if end_date is not None:
        filters.append((date_col, "<=", pd.Timestamp(end_date)))
    if symbols:
        filters.append(("symbol", "in", symbols))
    try:
        return pd.read_parquet(path, columns=columns, filters=filters or None)
    except Exception:
        frame = pd.read_parquet(path, columns=columns)
        frame[date_col] = pd.to_datetime(frame[date_col])
        if start_date is not None:
            frame = frame[frame[date_col] >= pd.Timestamp(start_date)]
        if end_date is not None:
            frame = frame[frame[date_col] <= pd.Timestamp(end_date)]
        if symbols:
            frame = frame[frame["symbol"].isin(symbols)]
        return frame
