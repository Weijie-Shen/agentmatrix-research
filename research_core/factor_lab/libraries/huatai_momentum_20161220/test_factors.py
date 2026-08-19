import numpy as np
import pandas as pd

from .factors import compute_corrected_factors


def _calendar(start="2020-01-31", end="2020-04-30"):
    return pd.DataFrame({"trade_date": pd.date_range(start, end, freq="B")})


def test_return_1m_uses_previous_natural_month_endpoint():
    calendar = _calendar("2020-01-31", "2020-03-31")
    dates = calendar["trade_date"]
    panel = pd.DataFrame({"date": dates, "code": "A", "adjusted_close": np.arange(len(dates)) + 100.0})
    result = compute_corrected_factors(panel, trading_calendar=calendar, factor_names=["return_1m"])
    feb_end = dates[dates.dt.to_period("M") == pd.Period("2020-02")].max()
    mar_end = dates.max()
    prices = panel.set_index("date")["adjusted_close"]
    actual = result.loc[result["date"].eq(mar_end), "return_1m"].iloc[0]
    assert np.isclose(actual, prices.loc[mar_end] / prices.loc[feb_end] - 1)


def test_turnover_weighted_return_normalizes_by_turnover_weight():
    calendar = _calendar("2020-03-31", "2020-04-30")
    dates = calendar["trade_date"]
    close = pd.Series(100.0, index=dates)
    close.iloc[-2:] = [110.0, 132.0]
    turnover = pd.Series(0.0, index=dates)
    turnover.iloc[-2:] = [1.0, 3.0]
    panel = pd.DataFrame({
        "date": dates,
        "code": "A",
        "adjusted_close": close.to_numpy(),
        "turnover": turnover.to_numpy(),
    })
    result = compute_corrected_factors(panel, trading_calendar=calendar, factor_names=["wgt_return_1m"])
    actual = result.loc[result["date"].eq(dates.max()), "wgt_return_1m"].iloc[0]
    expected = ((0.10 * 1.0) + (0.20 * 3.0)) / 4.0
    assert np.isclose(actual, expected)


def test_exponential_factor_uses_literal_month_n_and_exchange_distance():
    calendar = _calendar("2020-01-31", "2020-04-30")
    dates = calendar["trade_date"]
    close = pd.Series(100.0, index=dates)
    close.iloc[-2:] = [110.0, 132.0]
    turnover = pd.Series(0.0, index=dates)
    turnover.iloc[-2:] = [2.0, 1.0]
    panel = pd.DataFrame({
        "date": dates,
        "code": "A",
        "adjusted_close": close.to_numpy(),
        "turnover": turnover.to_numpy(),
    })
    result = compute_corrected_factors(panel, trading_calendar=calendar, factor_names=["exp_wgt_return_3m"])
    actual = result.loc[result["date"].eq(dates.max()), "exp_wgt_return_3m"].iloc[0]
    decay_previous_session = np.exp(-1.0 / 3.0 / 4.0)
    expected = (0.10 * 2.0 * decay_previous_session + 0.20) / (2.0 * decay_previous_session + 1.0)
    assert np.isclose(actual, expected)


def test_missing_security_row_does_not_collapse_exchange_distance():
    calendar = _calendar("2020-01-31", "2020-04-30")
    dates = calendar["trade_date"]
    retained = dates.drop(dates.index[-2]).reset_index(drop=True)
    close = pd.Series(100.0, index=retained)
    close.iloc[-2:] = [110.0, 132.0]
    turnover = pd.Series(0.0, index=retained)
    turnover.iloc[-2:] = [2.0, 1.0]
    panel = pd.DataFrame({
        "date": retained,
        "code": "A",
        "adjusted_close": close.to_numpy(),
        "turnover": turnover.to_numpy(),
    })
    result = compute_corrected_factors(panel, trading_calendar=calendar, factor_names=["exp_wgt_return_3m"])
    actual = result.loc[result["date"].eq(dates.max()), "exp_wgt_return_3m"].iloc[0]
    # One missing retained row means the earlier observation is two exchange
    # sessions away, not one retained-security observation away.
    decay = np.exp(-2.0 / 3.0 / 4.0)
    expected = (0.10 * 2.0 * decay + 0.20) / (2.0 * decay + 1.0)
    assert np.isclose(actual, expected)
