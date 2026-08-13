from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

import numpy as np
import pandas as pd


DEFAULT_RECOMMENDED_DATA_DIR = Path("/Users/mac/recommended_data_v2")
RECOMMENDED_MANIFEST_FILE = "MANIFEST.json"
RECOMMENDED_KLINE_FILE = "kline_raw_rqdata.parquet"
RECOMMENDED_MARKET_CAP_FILE = "market_cap_history_rqdata.parquet"
LEGACY_RECOMMENDED_UNIFIED_MARKET_CAP_FILE = "market_cap.parquet"
LEGACY_RECOMMENDED_MARKET_CAP_FILE = "market_cap_2010_2026.parquet"
RECOMMENDED_INDUSTRY_FILE = "industry_membership_history_rqdata.parquet"
RECOMMENDED_INDUSTRY_TAXONOMY_FILE = "industry_taxonomy_history_rqdata.parquet"
LEGACY_RECOMMENDED_INDUSTRY_FILE = "industry_map.parquet"
RECOMMENDED_FINANCIAL_STATEMENTS_FILE = "financial_statements_pit_rqdata.parquet"
RECOMMENDED_VALUATION_FACTORS_FILE = "valuation_factors_rqdata.parquet"
RECOMMENDED_INDEX_LEVELS_FILE = "standard_index_daily_levels.parquet"
RECOMMENDED_TRADING_CALENDAR_FILE = "trading_calendar.parquet"
RECOMMENDED_YIELD_CURVE_FILE = "china_government_yield_curve.parquet"
RECOMMENDED_INDEX_COMPONENTS_DIR = "index_components_rqdata"
RECOMMENDED_INDEX_WEIGHTS_MONTHLY_DIR = "index_weights_monthly_rqdata"
RECOMMENDED_INDEX_WEIGHTS_DAILY_DIR = "index_weights_daily_rqdata"

SUPPORTED_INDUSTRY_SOURCES = ("sws", "citics", "citics_2019", "gildata")
MARKET_CAP_FIELD_SOURCES = {
    "market_cap": "market_cap_3",
    "total_market_cap": "market_cap_3",
    "market_cap_3": "market_cap_3",
    "a_share_market_cap": "a_share_market_val_3",
    "a_share_market_val_3": "a_share_market_val_3",
    "circulating_market_cap": "a_share_market_val_in_circulation",
    "circulating_a_market_cap": "a_share_market_val_in_circulation",
    "a_share_market_val_in_circulation": "a_share_market_val_in_circulation",
    "free_float_market_cap": "free_float_market_cap",
}

PriceAdjustmentView = Literal["raw", "qfq", "hfq"]
PAPER_PRICE_ADJUSTMENT_VIEWS: tuple[Literal["qfq", "hfq"], ...] = ("qfq", "hfq")
RAW_PRICE_COLUMNS = ("open", "high", "low", "close", "limit_up", "limit_down", "prev_close")


class RecommendedDataPredicatePushdownError(RuntimeError):
    """A bounded recommended-data read could not enforce its parquet predicates."""

    def __init__(self, *, path: Path, columns: Sequence[str], filters: Sequence[tuple[str, str, Any]], cause: Exception):
        self.path = path
        self.columns = tuple(columns)
        self.filters = tuple(filters)
        self.cause_type = type(cause).__name__
        filter_summary = [
            (column, operator, f"<{len(value)} values>" if operator == "in" and isinstance(value, list) else value)
            for column, operator, value in filters
        ]
        super().__init__(
            "bounded parquet predicate pushdown failed; refusing an unbounded whole-file "
            f"fallback for {path.name} (columns={list(columns)!r}, filters={filter_summary!r}, "
            f"cause={self.cause_type})"
        )


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
    industry_membership: Path | None
    industry_taxonomy: Path | None
    financial_statements: Path | None
    valuation_factors: Path | None
    index_levels: Path | None
    trading_calendar: Path | None
    yield_curve: Path | None
    index_components: Path | None
    index_weights_monthly: Path | None
    index_weights_daily: Path | None

    @property
    def uses_integrated_kline_status(self) -> bool:
        return self.daily_prices.name == RECOMMENDED_KLINE_FILE

    @property
    def industry(self) -> Path | None:
        """Backward-compatible alias for the selected membership dataset."""

        return self.industry_membership

    @property
    def uses_interval_industry_history(self) -> bool:
        return bool(self.industry_membership and self.industry_membership.name == RECOMMENDED_INDUSTRY_FILE)


@dataclass(frozen=True, slots=True)
class IndustryClassificationSelection:
    """Paper-resolved industry taxonomy used at each evaluation/formation date."""

    source: str
    level: int

    def __post_init__(self) -> None:
        source = str(self.source).strip().lower()
        if source not in SUPPORTED_INDUSTRY_SOURCES:
            raise ValueError(
                f"unsupported industry source {self.source!r}; expected one of {', '.join(SUPPORTED_INDUSTRY_SOURCES)}"
            )
        if int(self.level) not in (1, 2, 3):
            raise ValueError("industry level must be 1, 2, or 3")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "level", int(self.level))


def resolve_recommended_data_sources(config: RecommendedDataConfig | None = None) -> RecommendedDataSources:
    """Resolve canonical files once so callers never choose among overlapping sources."""

    data_config = config or RecommendedDataConfig.from_env()
    market_cap = _first_existing_path(
        data_config,
        [
            RECOMMENDED_MARKET_CAP_FILE,
            LEGACY_RECOMMENDED_UNIFIED_MARKET_CAP_FILE,
            LEGACY_RECOMMENDED_MARKET_CAP_FILE,
        ],
        required=False,
    )
    industry = _first_existing_path(
        data_config,
        [RECOMMENDED_INDUSTRY_FILE, LEGACY_RECOMMENDED_INDUSTRY_FILE],
        required=False,
    )
    taxonomy = data_config.path(RECOMMENDED_INDUSTRY_TAXONOMY_FILE)
    def optional_file(name: str) -> Path | None:
        path = data_config.path(name)
        return path if path.exists() else None

    def optional_dir(name: str) -> Path | None:
        path = data_config.path(name)
        return path if path.is_dir() else None
    return RecommendedDataSources(
        daily_prices=data_config.path(RECOMMENDED_KLINE_FILE),
        market_cap=market_cap,
        industry_membership=industry,
        industry_taxonomy=taxonomy if taxonomy.exists() else None,
        financial_statements=optional_file(RECOMMENDED_FINANCIAL_STATEMENTS_FILE),
        valuation_factors=optional_file(RECOMMENDED_VALUATION_FACTORS_FILE),
        index_levels=optional_file(RECOMMENDED_INDEX_LEVELS_FILE),
        trading_calendar=optional_file(RECOMMENDED_TRADING_CALENDAR_FILE),
        yield_curve=optional_file(RECOMMENDED_YIELD_CURVE_FILE),
        index_components=optional_dir(RECOMMENDED_INDEX_COMPONENTS_DIR),
        index_weights_monthly=optional_dir(RECOMMENDED_INDEX_WEIGHTS_MONTHLY_DIR),
        index_weights_daily=optional_dir(RECOMMENDED_INDEX_WEIGHTS_DAILY_DIR),
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
    market_cap_fields: Sequence[str] | None = None,
    industry_classification: IndustryClassificationSelection | None = None,
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

    selected_market_cap_fields = _resolve_market_cap_fields(include_market_cap, market_cap_fields)
    market_cap_lineage: dict[str, Any] = {}
    if selected_market_cap_fields:
        if sources.market_cap is None:
            raise FileNotFoundError(f"recommended market-cap dataset not found in {data_config.data_dir}")
        market_cap = _read_recommended_market_cap(
            sources.market_cap,
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
            fields=selected_market_cap_fields,
        )
        market_cap_lineage = dict(market_cap.attrs.get("market_cap_lineage", {}))
        panel = panel.merge(market_cap, on=["date", "code"], how="left")

    if include_industry or industry_classification is not None:
        if sources.industry_membership is None:
            raise FileNotFoundError(f"recommended industry dataset not found in {data_config.data_dir}")
        if sources.uses_interval_industry_history:
            if industry_classification is None:
                raise ValueError(
                    "industry_classification is required for interval industry history; "
                    "resolve the paper's taxonomy source and level instead of choosing implicitly"
                )
            industry = _read_recommended_industry_history(
                sources.industry_membership,
                selection=industry_classification,
                start_date=start_date,
                end_date=end_date,
                symbols=symbols,
            )
            panel = resolve_recommended_industry_membership(
                panel,
                industry,
                selection=industry_classification,
            )
        else:
            if industry_classification is not None:
                raise ValueError(
                    "legacy static industry_map.parquet has no taxonomy source/level or point-in-time history"
                )
            industry = pd.read_parquet(sources.industry_membership)
            panel = panel.merge(normalize_recommended_industry_frame(industry), on="code", how="left")

    panel.attrs["market_cap_fields"] = list(selected_market_cap_fields)
    if market_cap_lineage:
        panel.attrs["market_cap_lineage"] = market_cap_lineage
    if industry_classification is not None:
        panel.attrs["industry_classification"] = {
            "source": industry_classification.source,
            "level": industry_classification.level,
            "membership_file": str(sources.industry_membership),
            "taxonomy_file": str(sources.industry_taxonomy) if sources.industry_taxonomy else None,
            "interval_rule": "start_date <= date < cancel_date",
        }

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
    market_cap_fields: Sequence[str] | None = None,
    industry_classification: IndustryClassificationSelection | None = None,
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
        market_cap_fields=market_cap_fields,
        industry_classification=industry_classification,
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


def normalize_recommended_market_cap_frame(
    raw_frame: pd.DataFrame,
    *,
    fields: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Normalize requested capitalization semantics without conflating cap bases.

    ``market_cap`` remains a compatibility name for RQData ``market_cap_3``.
    Callers requiring A-share, circulating-A, or free-float capitalization must
    request that semantic field explicitly.
    """

    frame = raw_frame.reset_index() if isinstance(raw_frame.index, pd.MultiIndex) else raw_frame.copy()
    if "trade_date" in frame.columns and "date" not in frame.columns:
        frame = frame.rename(columns={"trade_date": "date"})
    if "symbol" in frame.columns and "order_book_id" not in frame.columns:
        frame["order_book_id"] = frame["symbol"]
    selected_fields = tuple(fields) if fields is not None else _default_available_market_cap_fields(frame.columns)
    required_sources = {MARKET_CAP_FIELD_SOURCES.get(field, field) for field in selected_fields}
    if "market_cap" in frame.columns and "market_cap_3" in required_sources and "market_cap_3" not in frame.columns:
        frame["market_cap_3"] = frame["market_cap"]
    required = ["order_book_id", "date", *sorted(required_sources)]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"missing recommended market cap columns: {', '.join(missing)}")
    frame["date"] = pd.to_datetime(frame["date"])
    frame["code"] = frame["order_book_id"].map(normalize_recommended_symbol)
    output = frame[["date", "code"]].copy()
    for field in selected_fields:
        source = MARKET_CAP_FIELD_SOURCES.get(field)
        if source is None:
            raise ValueError(
                f"unsupported market-cap field {field!r}; expected one of {', '.join(MARKET_CAP_FIELD_SOURCES)}"
            )
        output[field] = pd.to_numeric(frame[source], errors="coerce")
    output.attrs["market_cap_lineage"] = {
        field: {
            "source_field": MARKET_CAP_FIELD_SOURCES[field],
            "price_basis": "unadjusted",
            "derived": field == "free_float_market_cap",
        }
        for field in selected_fields
    }
    return output


def normalize_recommended_industry_frame(raw_frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize the deprecated static industry snapshot for compatibility only."""

    required = ["symbol", "industry"]
    missing = [column for column in required if column not in raw_frame.columns]
    if missing:
        raise ValueError(f"missing recommended industry columns: {', '.join(missing)}")
    frame = raw_frame.copy()
    frame["code"] = frame["symbol"].map(normalize_recommended_symbol)
    return frame[["code", "industry"]]


def normalize_recommended_industry_history_frame(raw_frame: pd.DataFrame) -> pd.DataFrame:
    required = [
        "symbol",
        "source",
        "level",
        "industry_code",
        "industry_name",
        "start_date",
        "cancel_date",
    ]
    missing = [column for column in required if column not in raw_frame.columns]
    if missing:
        raise ValueError(f"missing recommended industry-history columns: {', '.join(missing)}")
    frame = raw_frame.copy()
    frame["code"] = frame["symbol"].map(normalize_recommended_symbol)
    frame["source"] = frame["source"].astype(str).str.lower()
    frame["level"] = pd.to_numeric(frame["level"], errors="raise").astype(int)
    frame["start_date"] = pd.to_datetime(frame["start_date"])
    frame["cancel_date"] = pd.to_datetime(frame["cancel_date"])
    return frame[
        ["code", "source", "level", "industry_code", "industry_name", "start_date", "cancel_date"]
    ]


def resolve_recommended_industry_membership(
    panel: pd.DataFrame,
    membership_history: pd.DataFrame,
    *,
    selection: IndustryClassificationSelection,
) -> pd.DataFrame:
    """Resolve point-in-time membership using ``start <= date < cancel``."""

    missing_panel = [column for column in ("date", "code") if column not in panel.columns]
    if missing_panel:
        raise ValueError(f"missing panel columns for industry resolution: {', '.join(missing_panel)}")
    history = normalize_recommended_industry_history_frame(membership_history)
    history = history[
        (history["source"] == selection.source) & (history["level"] == selection.level)
    ].copy()
    if history.empty:
        raise ValueError(
            f"no industry memberships found for source={selection.source!r}, level={selection.level}"
        )
    if history.duplicated(["code", "start_date"]).any():
        raise ValueError(
            f"ambiguous industry intervals for source={selection.source!r}, level={selection.level}"
        )

    result = panel.copy().reset_index(drop=True)
    left = result[["code", "date"]].copy()
    left["date"] = pd.to_datetime(left["date"])
    left["__row_order"] = np.arange(len(left))
    left = left.sort_values(["date", "code"])
    right = history.rename(
        columns={
            "source": "industry_source",
            "level": "industry_level",
            "start_date": "industry_start_date",
            "cancel_date": "industry_cancel_date",
        }
    ).sort_values(["industry_start_date", "code"])
    resolved = pd.merge_asof(
        left,
        right,
        left_on="date",
        right_on="industry_start_date",
        by="code",
        direction="backward",
        allow_exact_matches=True,
    )
    active = resolved["date"] < resolved["industry_cancel_date"]
    resolved_columns = [
        "industry_code",
        "industry_name",
        "industry_source",
        "industry_level",
        "industry_start_date",
        "industry_cancel_date",
    ]
    resolved.loc[~active, resolved_columns] = pd.NA
    resolved = resolved.sort_values("__row_order")
    for column in resolved_columns:
        result[column] = resolved[column].to_numpy()
    result["industry"] = result["industry_code"].astype("string")
    result.attrs.update(panel.attrs)
    result.attrs["industry_classification"] = {
        "source": selection.source,
        "level": selection.level,
        "interval_rule": "start_date <= date < cancel_date",
        "categorical_field": "industry_code",
    }
    return result


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
    fields: Sequence[str],
) -> pd.DataFrame:
    try:
        import pyarrow.parquet as pq

        columns = set(pq.read_schema(path).names)
    except Exception:
        columns = set()
    physical_fields = sorted({MARKET_CAP_FIELD_SOURCES.get(field, field) for field in fields})
    canonical_required = {"symbol", "trade_date", *physical_fields}
    if canonical_required.issubset(columns):
        raw = _read_parquet_with_filters(
            path,
            columns=["symbol", "trade_date", *physical_fields],
            date_col="trade_date",
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
        return normalize_recommended_market_cap_frame(raw, fields=fields)

    if {"symbol", "trade_date", "market_cap"}.issubset(columns):
        unsupported = [field for field in fields if MARKET_CAP_FIELD_SOURCES.get(field) != "market_cap_3"]
        if unsupported:
            raise ValueError(
                "legacy market-cap data cannot satisfy semantic fields: " + ", ".join(unsupported)
            )
        raw = _read_parquet_with_filters(
            path,
            columns=["symbol", "trade_date", "market_cap"],
            date_col="trade_date",
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
        return normalize_recommended_market_cap_frame(raw, fields=fields)

    frame = pd.read_parquet(path)
    frame = normalize_recommended_market_cap_frame(frame, fields=fields)
    if start_date is not None:
        frame = frame[frame["date"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        frame = frame[frame["date"] <= pd.Timestamp(end_date)]
    if symbols:
        frame = frame[frame["code"].isin(symbols)]
    return frame


def _read_recommended_industry_history(
    path: Path,
    *,
    selection: IndustryClassificationSelection,
    start_date: str | pd.Timestamp | None,
    end_date: str | pd.Timestamp | None,
    symbols: list[str] | None,
) -> pd.DataFrame:
    columns = [
        "symbol",
        "source",
        "level",
        "industry_code",
        "industry_name",
        "start_date",
        "cancel_date",
    ]
    filters: list[tuple[str, str, Any]] = [
        ("source", "==", selection.source),
        ("level", "==", selection.level),
    ]
    if start_date is not None:
        filters.append(("cancel_date", ">", pd.Timestamp(start_date)))
    if end_date is not None:
        filters.append(("start_date", "<=", pd.Timestamp(end_date)))
    if symbols:
        filters.append(("symbol", "in", _symbol_filter_values(symbols)))
    try:
        return pd.read_parquet(path, columns=columns, filters=filters)
    except Exception as exc:
        raise RecommendedDataPredicatePushdownError(
            path=path,
            columns=columns,
            filters=filters,
            cause=exc,
        ) from exc


def _resolve_market_cap_fields(
    include_market_cap: bool,
    fields: Sequence[str] | None,
) -> tuple[str, ...]:
    selected = tuple(str(field) for field in fields) if fields is not None else (("market_cap",) if include_market_cap else ())
    unsupported = [field for field in selected if field not in MARKET_CAP_FIELD_SOURCES]
    if unsupported:
        raise ValueError(
            f"unsupported market-cap fields: {', '.join(unsupported)}; "
            f"expected one of {', '.join(MARKET_CAP_FIELD_SOURCES)}"
        )
    return tuple(dict.fromkeys(selected))


def _default_available_market_cap_fields(columns: Sequence[Any]) -> tuple[str, ...]:
    available = {str(column) for column in columns}
    if "market_cap" in available and "market_cap_3" not in available:
        return ("market_cap",)
    defaults = (
        "market_cap",
        "a_share_market_cap",
        "circulating_market_cap",
        "free_float_market_cap",
    )
    return tuple(field for field in defaults if MARKET_CAP_FIELD_SOURCES[field] in available)


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
    except Exception as exc:
        if filters:
            raise RecommendedDataPredicatePushdownError(
                path=path,
                columns=columns,
                filters=filters,
                cause=exc,
            ) from exc
        raise


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
