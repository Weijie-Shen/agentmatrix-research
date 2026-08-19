from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


SUPPORTED_FACTORS = (
    "exp_wgt_return_6m",
    "exp_wgt_return_3m",
    "wgt_return_1m",
    "return_1m",
)


def compute_corrected_factors(
    panel: pd.DataFrame,
    *,
    trading_calendar: pd.DataFrame | Sequence[object],
    factor_names: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Compute the four Huatai momentum factors with literal calendar semantics.

    Corrections relative to the rejected reproduction artifact:

    1. Turnover-weighted averages divide by the sum of turnover-adjusted
       weights, including the exponential decay term when present.
    2. N remains the paper's literal month parameter in ``exp(-x / N / 4)``;
       ``x`` is an exchange-session distance from the signal date.
    3. Lookbacks are bounded by natural-month endpoints rather than a fixed
       count of retained security observations.

    The caller supplies pre-sample history. This function does not apply any
    evaluation-universe filter.
    """

    selected = tuple(factor_names or SUPPORTED_FACTORS)
    unknown = sorted(set(selected) - set(SUPPORTED_FACTORS))
    if unknown:
        raise ValueError(f"unsupported Huatai momentum factors: {unknown}")
    required = {"date", "code", "adjusted_close"}
    if any(name != "return_1m" for name in selected):
        required.add("turnover")
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"factor inputs are missing columns: {missing}")
    if panel.duplicated(["date", "code"]).any():
        raise ValueError("factor inputs require unique date/code keys")

    calendar = _calendar_frame(trading_calendar)
    calendar_index = calendar.set_index("date")["exchange_session_index"]
    month_end_by_period = calendar.groupby("month", sort=False)["date"].max().to_dict()
    signal_dates = set(month_end_by_period.values())

    data = panel.sort_values(["code", "date"], kind="stable").reset_index(drop=True).copy()
    data["date"] = pd.to_datetime(data["date"])
    data["adjusted_close"] = pd.to_numeric(data["adjusted_close"], errors="coerce")
    data["exchange_session_index"] = data["date"].map(calendar_index)
    if data["exchange_session_index"].isna().any():
        bad = data.loc[data["exchange_session_index"].isna(), "date"].min()
        raise ValueError(f"panel date is absent from the exchange calendar: {bad}")
    data["exchange_session_index"] = data["exchange_session_index"].astype(int)
    data["is_signal"] = data["date"].isin(signal_dates)
    data["__row_id"] = np.arange(len(data))

    # Status-only rows keep the last observed price. Their zero turnover gives
    # them zero weight, while the exchange calendar still advances distance.
    filled_close = data.groupby("code", sort=False)["adjusted_close"].ffill()
    data["daily_return"] = filled_close.groupby(data["code"], sort=False).pct_change(fill_method=None)
    if "turnover" in data:
        data["turnover"] = pd.to_numeric(data["turnover"], errors="coerce")

    result = data[["date", "code"]].copy()
    for name in selected:
        result[name] = np.nan

    if "return_1m" in selected:
        values = _calendar_endpoint_return(data, month_end_by_period=month_end_by_period, months=1)
        result.loc[values["__row_id"].to_numpy(), "return_1m"] = values["factor_value"].to_numpy()

    weighted_specs = {
        "wgt_return_1m": (1, False),
        "exp_wgt_return_3m": (3, True),
        "exp_wgt_return_6m": (6, True),
    }
    for name, (months, exponential) in weighted_specs.items():
        if name not in selected:
            continue
        values = _calendar_weighted_return(
            data,
            month_end_by_period=month_end_by_period,
            months=months,
            exponential=exponential,
        )
        result.loc[values["__row_id"].to_numpy(), name] = values["factor_value"].to_numpy()

    for name in selected:
        result[name] = result[name].replace([np.inf, -np.inf], np.nan)
    result.attrs["huatai_formula_semantics"] = {
        "lookback": "natural_month_endpoint_window",
        "decay_distance": "exchange_calendar_sessions",
        "decay_parameter_N": "literal_source_months",
        "weighted_denominator": "sum(turnover * decay), with decay=1 for wgt_return_1m",
        "pre_sample_history_required": True,
    }
    return result


def _calendar_endpoint_return(
    data: pd.DataFrame,
    *,
    month_end_by_period: dict[pd.Period, pd.Timestamp],
    months: int,
) -> pd.DataFrame:
    signals = data.loc[data["is_signal"], ["__row_id", "date", "code", "adjusted_close"]].copy()
    signals["start_date"] = signals["date"].dt.to_period("M").sub(months).map(month_end_by_period)
    starts = data[["date", "code", "adjusted_close"]].rename(
        columns={"date": "start_date", "adjusted_close": "start_price"}
    )
    signals = signals.merge(starts, on=["code", "start_date"], how="left", validate="many_to_one")
    signals["factor_value"] = signals["adjusted_close"].div(signals["start_price"]).sub(1)
    return signals[["__row_id", "factor_value"]]


def _calendar_weighted_return(
    data: pd.DataFrame,
    *,
    month_end_by_period: dict[pd.Period, pd.Timestamp],
    months: int,
    exponential: bool,
) -> pd.DataFrame:
    valid_return = data["daily_return"].notna()
    turnover_weight = data["turnover"].where(valid_return, 0.0).fillna(0.0)
    numerator = data["daily_return"].fillna(0.0).mul(turnover_weight)
    if exponential:
        # The global shift prevents overflow and cancels from numerator/denominator.
        literal_month_decay_scale = float(months * 4)
        shifted_index = data["exchange_session_index"] - int(data["exchange_session_index"].max())
        calendar_decay_component = np.exp(shifted_index / literal_month_decay_scale)
        numerator = numerator.mul(calendar_decay_component)
        turnover_weight = turnover_weight.mul(calendar_decay_component)

    cumulative_numerator = numerator.groupby(data["code"], sort=False).cumsum()
    cumulative_denominator = turnover_weight.groupby(data["code"], sort=False).cumsum()
    working = data[["__row_id", "date", "code", "is_signal"]].copy()
    working["cum_numerator"] = cumulative_numerator
    working["cum_denominator"] = cumulative_denominator

    signals = working.loc[working["is_signal"], [
        "__row_id", "date", "code", "cum_numerator", "cum_denominator"
    ]].copy()
    signals["start_date"] = signals["date"].dt.to_period("M").sub(months).map(month_end_by_period)
    starts = working[["date", "code", "cum_numerator", "cum_denominator"]].copy()
    starts["start_row_exists"] = True
    starts = starts.rename(
        columns={
            "date": "start_date",
            "cum_numerator": "start_cum_numerator",
            "cum_denominator": "start_cum_denominator",
        }
    )
    signals = signals.merge(starts, on=["code", "start_date"], how="left", validate="many_to_one")
    window_numerator = signals["cum_numerator"] - signals["start_cum_numerator"]
    window_denominator = signals["cum_denominator"] - signals["start_cum_denominator"]
    signals["factor_value"] = window_numerator.div(window_denominator.where(window_denominator.ne(0)))
    signals.loc[signals["start_row_exists"].ne(True), "factor_value"] = np.nan
    return signals[["__row_id", "factor_value"]]


def _calendar_frame(trading_calendar: pd.DataFrame | Sequence[object]) -> pd.DataFrame:
    if isinstance(trading_calendar, pd.DataFrame):
        source = "trade_date" if "trade_date" in trading_calendar.columns else "date"
        if source not in trading_calendar.columns:
            raise ValueError("trading calendar requires trade_date or date")
        dates = pd.to_datetime(trading_calendar[source], errors="coerce")
    else:
        dates = pd.to_datetime(pd.Series(list(trading_calendar)), errors="coerce")
    dates = pd.Series(dates).dropna().drop_duplicates().sort_values(kind="stable").reset_index(drop=True)
    if dates.empty:
        raise ValueError("trading calendar is empty")
    return pd.DataFrame(
        {
            "date": dates,
            "exchange_session_index": np.arange(len(dates)),
            "month": dates.dt.to_period("M"),
        }
    )
