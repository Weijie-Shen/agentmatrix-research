from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd


DEFAULT_RECOMMENDED_DATA_DIR = Path("/Users/mac/recommended_data_v2")
RECOMMENDED_MANIFEST_FILE = "MANIFEST.json"
RECOMMENDED_KLINE_FILE = "kline_raw_rqdata.parquet"
RECOMMENDED_MARKET_CAP_FILE = "market_cap.parquet"
LEGACY_RECOMMENDED_MARKET_CAP_FILE = "market_cap_2010_2026.parquet"
RECOMMENDED_INDUSTRY_FILE = "industry_map.parquet"

PriceAdjustmentView = Literal["raw", "qfq", "hfq"]
PAPER_PRICE_ADJUSTMENT_VIEWS: tuple[Literal["qfq", "hfq"], ...] = ("qfq", "hfq")
RAW_PRICE_COLUMNS = ("open", "high", "low", "close", "limit_up", "limit_down", "prev_close")


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
    market_cap: Path | None
    industry: Path | None

    @property
    def uses_integrated_kline_status(self) -> bool:
        return self.daily_prices.name == RECOMMENDED_KLINE_FILE


def resolve_recommended_data_sources(config: RecommendedDataConfig | None = None) -> RecommendedDataSources:
    """Resolve canonical files once so callers never choose among overlapping sources."""

    data_config = config or RecommendedDataConfig.from_env()
    market_cap = _first_existing_path(
        data_config,
        [RECOMMENDED_MARKET_CAP_FILE, LEGACY_RECOMMENDED_MARKET_CAP_FILE],
        required=False,
    )
    industry = data_config.path(RECOMMENDED_INDUSTRY_FILE)
    return RecommendedDataSources(
        daily_prices=data_config.path(RECOMMENDED_KLINE_FILE),
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
    price_view: PriceAdjustmentView = "raw",
    adjustment_end_date: str | pd.Timestamp | None = None,
    include_status: bool = False,
    include_market_cap: bool = False,
    include_industry: bool = False,
    config: RecommendedDataConfig | None = None,
) -> pd.DataFrame:
    """Load one explicit price view from the canonical raw RQData daily panel.

    Resource-bounded paper reproductions should call this function once per price
    scenario, complete/persist that scenario, release it, and then load the next
    view. Use :func:`load_recommended_paper_panels` only for manageable diagnostics
    that intentionally keep both views resident.
    """

    data_config = config or RecommendedDataConfig.from_env()
    sources = resolve_recommended_data_sources(data_config)
    read_end_date = _status_lookahead_end(end_date) if include_status else end_date
    panel = _read_recommended_kline(
        sources.daily_prices,
        start_date=start_date,
        end_date=read_end_date,
        symbols=symbols,
    )
    panel = normalize_recommended_daily_kline_frame(panel)

    if include_status:
        panel = add_next_suspension_flag(panel)

    if end_date is not None:
        panel = panel[panel["date"] <= pd.Timestamp(end_date)]

    panel = build_recommended_price_view(
        panel,
        price_view=price_view,
        adjustment_end_date=adjustment_end_date if adjustment_end_date is not None else end_date,
    )

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


def load_recommended_paper_panels(
    *,
    test_end_date: str | pd.Timestamp,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    symbols: list[str] | None = None,
    include_status: bool = True,
    include_market_cap: bool = False,
    include_industry: bool = False,
    config: RecommendedDataConfig | None = None,
) -> dict[str, pd.DataFrame]:
    """Load both mandatory price views for a manageable in-memory diagnostic.

    QFQ is anchored independently for each security at the latest cumulative
    factor available on or before ``test_end_date``. HFQ uses the RQData
    initial factor baseline and therefore needs no end-date normalization.

    This convenience API retains raw, QFQ, and HFQ representations during
    construction. Full-period resource-bounded runs should instead call
    :func:`load_recommended_daily_panel` sequentially with ``price_view="qfq"``
    and ``price_view="hfq"``.
    """

    test_end = pd.Timestamp(test_end_date)
    requested_end = pd.Timestamp(end_date) if end_date is not None else test_end
    if requested_end < test_end:
        raise ValueError("end_date must reach test_end_date so QFQ anchor factors are observable")
    raw_panel = load_recommended_daily_panel(
        start_date=start_date,
        end_date=requested_end,
        symbols=symbols,
        price_view="raw",
        include_status=include_status,
        include_market_cap=include_market_cap,
        include_industry=include_industry,
        config=config,
    )
    return {
        "qfq": build_recommended_price_view(
            raw_panel,
            price_view="qfq",
            adjustment_end_date=test_end,
        ),
        "hfq": build_recommended_price_view(raw_panel, price_view="hfq"),
    }


def normalize_recommended_daily_kline_frame(raw_frame: pd.DataFrame) -> pd.DataFrame:
    required = [
        "symbol",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "num_trades",
        "limit_up",
        "limit_down",
        "prev_close",
        "ex_factor",
        "ex_cum_factor",
        "factor_ex_date",
        "has_factor_event",
        "is_st",
        "is_suspended",
        "has_price_observation",
    ]
    missing = [column for column in required if column not in raw_frame.columns]
    if missing:
        raise ValueError(f"missing recommended daily kline columns: {', '.join(missing)}")

    panel = raw_frame.copy().rename(columns={"trade_date": "date", "symbol": "code"})
    panel["date"] = pd.to_datetime(panel["date"])
    panel["factor_ex_date"] = pd.to_datetime(panel["factor_ex_date"])
    panel["code"] = panel["code"].map(normalize_recommended_symbol)
    panel["is_trading"] = panel["has_price_observation"].astype(bool) & panel["volume"].gt(0)
    panel["vwap"] = _raw_vwap(panel)
    columns = [
        "date",
        "code",
        "open",
        "high",
        "low",
        "close",
        "vwap",
        "volume",
        "amount",
        "num_trades",
        "limit_up",
        "limit_down",
        "prev_close",
        "ex_factor",
        "ex_cum_factor",
        "factor_ex_date",
        "has_factor_event",
        "is_st",
        "is_suspended",
        "has_price_observation",
        "is_trading",
    ]
    return panel[columns]


def build_recommended_price_view(
    raw_panel: pd.DataFrame,
    *,
    price_view: PriceAdjustmentView,
    adjustment_end_date: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Apply one explicit raw/QFQ/HFQ price convention to a normalized panel."""

    if price_view not in {"raw", "qfq", "hfq"}:
        raise ValueError(f"unsupported price_view: {price_view}")
    required = ["date", "code", "ex_cum_factor", *RAW_PRICE_COLUMNS]
    missing = [column for column in required if column not in raw_panel.columns]
    if missing:
        raise ValueError(f"missing price-view columns: {', '.join(missing)}")

    panel = raw_panel.copy()
    factors = pd.to_numeric(panel["ex_cum_factor"], errors="coerce")
    if factors.isna().any() or (factors <= 0).any():
        raise ValueError("ex_cum_factor must be finite and positive")

    raw_vwap = _raw_vwap(panel)
    for column in RAW_PRICE_COLUMNS:
        raw_column = f"{column}_raw"
        if raw_column not in panel.columns:
            panel[raw_column] = panel[column]
        else:
            panel[column] = panel[raw_column]
    if "vwap_raw" not in panel.columns:
        panel["vwap_raw"] = raw_vwap
    else:
        panel["vwap"] = panel["vwap_raw"]

    if price_view == "raw":
        multiplier = pd.Series(1.0, index=panel.index, dtype=float)
        anchor_factor = pd.Series(1.0, index=panel.index, dtype=float)
        anchor_date = pd.NaT
        anchor_observation_date = pd.Series(pd.NaT, index=panel.index, dtype="datetime64[ns]")
    elif price_view == "hfq":
        multiplier = factors
        anchor_factor = pd.Series(1.0, index=panel.index, dtype=float)
        anchor_date = pd.NaT
        anchor_observation_date = pd.Series(pd.NaT, index=panel.index, dtype="datetime64[ns]")
    else:
        if adjustment_end_date is None:
            raise ValueError("adjustment_end_date is required for the qfq price view")
        anchor_date = pd.Timestamp(adjustment_end_date)
        eligible = panel.loc[panel["date"] <= anchor_date, ["date", "code", "ex_cum_factor"]]
        anchors = (
            eligible.sort_values(["code", "date"])
            .groupby("code", sort=False)
            .last()
        )
        anchor_factor = panel["code"].map(anchors["ex_cum_factor"]).astype(float)
        anchor_observation_date = pd.to_datetime(panel["code"].map(anchors["date"]))
        multiplier = factors / anchor_factor

    for column in (*RAW_PRICE_COLUMNS, "vwap"):
        raw_column = f"{column}_raw"
        panel[column] = panel[raw_column] * multiplier
    panel["price_multiplier"] = multiplier
    panel["price_adjustment"] = price_view
    panel["adjustment_anchor_date"] = anchor_date
    panel["adjustment_anchor_observation_date"] = anchor_observation_date
    panel["adjustment_anchor_factor"] = anchor_factor
    panel.attrs["price_adjustment"] = price_view
    panel.attrs["adjustment_anchor_date"] = None if pd.isna(anchor_date) else str(anchor_date.date())
    return panel


def _raw_vwap(panel: pd.DataFrame) -> pd.Series:
    volume = pd.to_numeric(panel["volume"], errors="coerce")
    amount = pd.to_numeric(panel["amount"], errors="coerce")
    values = np.divide(
        amount.to_numpy(dtype=float),
        volume.to_numpy(dtype=float),
        out=np.full(len(panel), np.nan, dtype=float),
        where=volume.to_numpy(dtype=float) > 0,
    )
    return pd.Series(values, index=panel.index, dtype=float)


def _status_lookahead_end(end_date: str | pd.Timestamp | None) -> pd.Timestamp | None:
    if end_date is None:
        return None
    return pd.Timestamp(end_date) + pd.Timedelta(days=31)


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
    """Build a physically filtered evaluation panel from recommended-data status columns.

    This compatibility helper is for post-calculation evaluation/portfolio eligibility.
    Do not pass its output into rolling factor calculation: deleting ST or suspended rows
    can change historical windows, ranks, lags, and forward-return horizons. Canonical
    paper runs should declare a universe protocol and let ``execute_evaluation_plan``
    apply the filters after the artifact callable has used the full calculation panel.
    """

    result = panel.copy()
    if "has_price_observation" in result.columns:
        result = result[result["has_price_observation"].fillna(False).astype(bool)]
    if "is_trading" in result.columns:
        result = result[result["is_trading"].fillna(False).astype(bool)]
    suspension_column = "next_is_suspended" if "next_is_suspended" in result.columns else "is_suspended"
    for column in ("is_st", suspension_column):
        if column in result.columns:
            result = result[result[column].fillna(0).astype(int) == 0]
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
        "num_trades",
        "limit_up",
        "limit_down",
        "prev_close",
        "ex_factor",
        "ex_cum_factor",
        "factor_ex_date",
        "has_factor_event",
        "is_st",
        "is_suspended",
        "has_price_observation",
    ]
    return _read_parquet_with_filters(path, columns=columns, date_col="trade_date", start_date=start_date, end_date=end_date, symbols=symbols)


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
