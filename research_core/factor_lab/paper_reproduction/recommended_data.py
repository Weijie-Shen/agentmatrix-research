from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_RECOMMENDED_DATA_DIR = Path("/Users/mac/recommended_data_v2")
RECOMMENDED_MANIFEST_FILE = "MANIFEST.json"
RECOMMENDED_KLINE_FILE = "kline_daily_adjusted.parquet"
RECOMMENDED_STATUS_FILE = "security_status.parquet"
LEGACY_RECOMMENDED_STATUS_FILE = "security_status_through_2026-04-09.parquet"
RECOMMENDED_ST_STATUS_2010_2016_FILE = "st_status_2010_2016.parquet"
RECOMMENDED_ST_STATUS_FILE = "st_status_full.parquet"
RECOMMENDED_MARKET_CAP_FILE = "market_cap.parquet"
LEGACY_RECOMMENDED_MARKET_CAP_FILE = "market_cap_2010_2026.parquet"
RECOMMENDED_INDUSTRY_FILE = "industry_map.parquet"
RECOMMENDED_ST_STATUS_FILES = [
    RECOMMENDED_ST_STATUS_2010_2016_FILE,
    RECOMMENDED_ST_STATUS_FILE,
]


@dataclass(slots=True)
class RecommendedDataConfig:
    data_dir: Path = DEFAULT_RECOMMENDED_DATA_DIR

    @classmethod
    def from_env(cls, env_var: str = "RECOMMENDED_DATA_DIR") -> RecommendedDataConfig:
        configured = os.environ.get(env_var, "").strip()
        return cls(data_dir=Path(configured).expanduser() if configured else DEFAULT_RECOMMENDED_DATA_DIR)

    def path(self, name: str) -> Path:
        return self.data_dir / name


@dataclass(frozen=True, slots=True)
class RecommendedDataSources:
    """Physical files selected for each logical recommended-data dataset."""

    daily_prices: Path
    security_status: Path | None
    status_supplements: tuple[Path, ...]
    market_cap: Path | None
    industry: Path | None

    @property
    def uses_canonical_status(self) -> bool:
        return self.security_status is not None and self.security_status.name == RECOMMENDED_STATUS_FILE


def resolve_recommended_data_sources(config: RecommendedDataConfig | None = None) -> RecommendedDataSources:
    """Resolve canonical files once so callers never choose among overlapping sources."""

    data_config = config or RecommendedDataConfig.from_env()
    canonical_status = data_config.path(RECOMMENDED_STATUS_FILE)
    if canonical_status.exists():
        security_status = canonical_status
        status_supplements: tuple[Path, ...] = ()
    else:
        legacy_status = data_config.path(LEGACY_RECOMMENDED_STATUS_FILE)
        security_status = legacy_status if legacy_status.exists() else None
        status_supplements = tuple(
            data_config.path(name) for name in RECOMMENDED_ST_STATUS_FILES if data_config.path(name).exists()
        )

    market_cap = _first_existing_path(
        data_config,
        [RECOMMENDED_MARKET_CAP_FILE, LEGACY_RECOMMENDED_MARKET_CAP_FILE],
        required=False,
    )
    industry = data_config.path(RECOMMENDED_INDUSTRY_FILE)
    return RecommendedDataSources(
        daily_prices=data_config.path(RECOMMENDED_KLINE_FILE),
        security_status=security_status,
        status_supplements=status_supplements,
        market_cap=market_cap,
        industry=industry if industry.exists() else None,
    )


def recommended_data_available(config: RecommendedDataConfig | None = None) -> bool:
    return resolve_recommended_data_sources(config).daily_prices.exists()


def load_recommended_data_manifest(config: RecommendedDataConfig | None = None) -> pd.DataFrame:
    data_config = config or RecommendedDataConfig.from_env()
    path = data_config.path(RECOMMENDED_MANIFEST_FILE)
    if not path.exists():
        raise FileNotFoundError(f"recommended data manifest not found: {path}")
    manifest = pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
    if "file" in manifest.columns:
        manifest["present_on_disk"] = manifest["file"].map(lambda name: data_config.path(str(name)).exists())
    return _augment_manifest_with_present_files(data_config, manifest)


def load_recommended_daily_panel(
    *,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    symbols: list[str] | None = None,
    adjusted: bool = True,
    include_status: bool = False,
    include_market_cap: bool = False,
    include_industry: bool = False,
    config: RecommendedDataConfig | None = None,
) -> pd.DataFrame:
    """Load a Factor Lab-style daily panel from the curated local data folder."""

    data_config = config or RecommendedDataConfig.from_env()
    sources = resolve_recommended_data_sources(data_config)
    panel = _read_recommended_kline(
        sources.daily_prices,
        start_date=start_date,
        end_date=end_date,
        symbols=symbols,
    )
    panel = normalize_recommended_daily_kline_frame(panel, adjusted=adjusted)

    if include_status:
        status = _read_recommended_status_panel(
            sources,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
        panel = panel.merge(add_next_suspension_flag(status), on=["date", "code"], how="left")

    if include_market_cap:
        if sources.market_cap is None:
            raise FileNotFoundError(f"recommended market-cap dataset not found in {data_config.data_dir}")
        market_cap = _read_recommended_market_cap(
            sources.market_cap,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
        panel = panel.merge(market_cap, on=["date", "code"], how="left")

    if include_industry:
        if sources.industry is None:
            raise FileNotFoundError(f"recommended industry dataset not found in {data_config.data_dir}")
        industry = pd.read_parquet(sources.industry)
        panel = panel.merge(normalize_recommended_industry_frame(industry), on="code", how="left")

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
    required = ["symbol", "trade_date", "is_st"]
    missing = [column for column in required if column not in raw_frame.columns]
    if missing:
        raise ValueError(f"missing recommended security status columns: {', '.join(missing)}")
    status = raw_frame.copy().rename(columns={"trade_date": "date", "symbol": "code"})
    status["date"] = pd.to_datetime(status["date"])
    status["code"] = status["code"].map(normalize_recommended_symbol)
    columns = [
        "date",
        "code",
        "is_trading",
        "is_st",
        "is_suspended",
        *[column for column in ("high_limited", "low_limited", "status_code") if column in status.columns],
    ]
    for optional in ("is_trading", "is_suspended"):
        if optional not in status.columns:
            status[optional] = pd.NA
    return status[columns]


def normalize_recommended_market_cap_frame(raw_frame: pd.DataFrame) -> pd.DataFrame:
    frame = raw_frame.reset_index() if isinstance(raw_frame.index, pd.MultiIndex) else raw_frame.copy()
    if "trade_date" in frame.columns and "date" not in frame.columns:
        frame = frame.rename(columns={"trade_date": "date"})
    if "symbol" in frame.columns and "order_book_id" not in frame.columns:
        frame["order_book_id"] = frame["symbol"]
    required = ["order_book_id", "date", "market_cap"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"missing recommended market cap columns: {', '.join(missing)}")
    frame["date"] = pd.to_datetime(frame["date"])
    frame["code"] = frame["order_book_id"].map(normalize_recommended_symbol)
    return frame[["date", "code", "market_cap"]]


def normalize_recommended_industry_frame(raw_frame: pd.DataFrame) -> pd.DataFrame:
    required = ["symbol", "industry"]
    missing = [column for column in required if column not in raw_frame.columns]
    if missing:
        raise ValueError(f"missing recommended industry columns: {', '.join(missing)}")
    frame = raw_frame.copy()
    frame["code"] = frame["symbol"].map(normalize_recommended_symbol)
    return frame[["code", "industry"]]


def add_next_suspension_flag(status_frame: pd.DataFrame) -> pd.DataFrame:
    required = ["date", "code"]
    missing = [column for column in required if column not in status_frame.columns]
    if missing:
        raise ValueError(f"missing status columns for next suspension flag: {', '.join(missing)}")
    status = status_frame.sort_values(["code", "date"]).copy()
    if "is_suspended" in status.columns:
        status["next_is_suspended"] = status.groupby("code")["is_suspended"].shift(-1)
    else:
        status["next_is_suspended"] = pd.NA
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


def _read_recommended_st_status(
    path: Path,
    *,
    start_date: str | pd.Timestamp | None,
    end_date: str | pd.Timestamp | None,
    symbols: list[str] | None,
) -> pd.DataFrame:
    columns = ["symbol", "trade_date", "is_st"]
    return _read_parquet_with_filters(path, columns=columns, date_col="trade_date", start_date=start_date, end_date=end_date, symbols=symbols)


def _read_recommended_status_panel(
    sources: RecommendedDataSources,
    *,
    start_date: str | pd.Timestamp | None,
    end_date: str | pd.Timestamp | None,
    symbols: list[str] | None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for st_path in sources.status_supplements:
        frames.append(
            normalize_recommended_security_status_frame(
                _read_recommended_st_status(
                    st_path,
                    start_date=start_date,
                    end_date=end_date,
                    symbols=symbols,
                )
            )
        )
    if sources.security_status is not None:
        frames.append(
            normalize_recommended_security_status_frame(
                _read_recommended_status(
                    sources.security_status,
                    start_date=start_date,
                    end_date=end_date,
                    symbols=symbols,
                )
            )
        )
    if not frames:
        raise FileNotFoundError(f"recommended security-status dataset not found beside {sources.daily_prices}")
    combined = frames[0]
    for frame in frames[1:]:
        combined = _merge_status_frames(combined, frame)
    return combined


def _read_recommended_market_cap(
    path: Path,
    *,
    start_date: str | pd.Timestamp | None,
    end_date: str | pd.Timestamp | None,
    symbols: list[str] | None,
) -> pd.DataFrame:
    try:
        import pyarrow.parquet as pq

        columns = set(pq.read_schema(path).names)
    except Exception:
        columns = set()
    if {"symbol", "trade_date", "market_cap"}.issubset(columns):
        raw = _read_parquet_with_filters(
            path,
            columns=["symbol", "trade_date", "market_cap"],
            date_col="trade_date",
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
        return normalize_recommended_market_cap_frame(raw)

    frame = pd.read_parquet(path)
    frame = normalize_recommended_market_cap_frame(frame)
    if start_date is not None:
        frame = frame[frame["date"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        frame = frame[frame["date"] <= pd.Timestamp(end_date)]
    if symbols:
        frame = frame[frame["code"].isin(symbols)]
    return frame


def _merge_status_frames(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    merged = left.merge(right, on=["date", "code"], how="outer", suffixes=("", "_right"))
    for column in ("is_st", "is_trading", "is_suspended", "high_limited", "low_limited", "status_code"):
        right_column = f"{column}_right"
        if right_column not in merged.columns:
            continue
        if column in merged.columns:
            merged[column] = merged[column].where(merged[column].notna(), merged[right_column])
        else:
            merged[column] = merged[right_column]
        merged = merged.drop(columns=[right_column])
    return merged


def _first_existing_path(data_config: RecommendedDataConfig, names: list[str], *, required: bool = True) -> Path | None:
    for name in names:
        path = data_config.path(name)
        if path.exists():
            return path
    if required:
        return data_config.path(names[0])
    return None


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
        filters.append(("symbol", "in", _symbol_filter_values(symbols)))
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
            frame = frame[frame["symbol"].isin(_symbol_filter_values(symbols))]
        return frame


def _symbol_filter_values(symbols: list[str]) -> list[str]:
    values: list[str] = []
    for symbol in symbols:
        text = str(symbol)
        candidates = [text]
        if text.endswith(".SZ"):
            candidates.append(f"{text[:-3]}.XSHE")
        elif text.endswith(".SH"):
            candidates.append(f"{text[:-3]}.XSHG")
        elif text.endswith(".XSHE"):
            candidates.append(f"{text[:-5]}.SZ")
        elif text.endswith(".XSHG"):
            candidates.append(f"{text[:-5]}.SH")
        for candidate in candidates:
            if candidate not in values:
                values.append(candidate)
    return values


def _augment_manifest_with_present_files(data_config: RecommendedDataConfig, manifest: pd.DataFrame) -> pd.DataFrame:
    listed = set(manifest["file"].tolist()) if "file" in manifest.columns else set()
    rows: list[dict[str, Any]] = []
    for path in sorted(data_config.data_dir.glob("*.parquet")):
        name = path.name
        if name in listed or not path.exists():
            continue
        rows.append(_parquet_manifest_row(path))
    if not rows:
        return manifest
    return pd.concat([manifest, pd.DataFrame(rows)], ignore_index=True)


def _parquet_manifest_row(path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "file": path.name,
        "bytes": path.stat().st_size,
        "present_on_disk": True,
    }
    try:
        import pyarrow.parquet as pq

        metadata = pq.ParquetFile(path).metadata
        payload["rows"] = metadata.num_rows
        payload["columns"] = metadata.schema.names
    except Exception:
        payload["rows"] = None
        payload["columns"] = []
    payload["source"] = "filesystem_detected"
    return payload
